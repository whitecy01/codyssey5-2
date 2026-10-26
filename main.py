"""Mini Git - 커밋 메타데이터 중심의 CLI 버전 관리 프로그램.

실행: python main.py

구성
- Commit / CommitGraph : 커밋 노드와 DAG(해시맵 기반 저장소)
- InvertedIndex        : keyword/author -> commit_hash 목록 역색인
- 정렬 알고리즘         : merge_sort(안정), quick_sort(불안정) 직접 구현
- 그래프 탐색          : topological_order(Kahn), shortest_path(BFS), find_ancestors(BFS)
- Repository           : INIT/BRANCH/SWITCH/COMMIT/MERGE 등 저장소 상태 관리
- MiniGitCLI           : mini-git> REPL (파싱 -> 실행 -> 출력)
"""

import hashlib
import os
import random
import shlex
import time
from collections import deque
from datetime import datetime

HASH_LENGTH = 7
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class MiniGitError(Exception):
    """사용자에게 그대로 보여줄 표준 에러 메시지."""


# ---------------------------------------------------------------------------
# 커밋 그래프
# ---------------------------------------------------------------------------

class Commit:
    """커밋 노드. parents 로 부모 커밋을 가리켜 DAG 를 이룬다."""

    def __init__(self, commit_hash, message, author, timestamp, parents, seq, branch):
        self.hash = commit_hash
        self.message = message
        self.author = author
        self.timestamp = timestamp  # datetime
        self.parents = parents      # list[str], 0개 이상
        self.seq = seq              # 생성 순번 (같은 초에 만든 커밋의 동률 처리용)
        self.branch = branch        # 커밋이 만들어진 브랜치 이름

    def time_str(self):
        return self.timestamp.strftime(TIME_FORMAT)


class CommitGraph:
    """hash -> Commit 해시맵으로 커밋을 저장하고, 자식 방향 간선도 함께 관리한다.

    새 커밋은 항상 '이미 존재하는' 커밋만 부모로 가질 수 있으므로
    간선이 과거 방향으로만 생겨 사이클이 만들어질 수 없다(DAG 보장).
    """

    def __init__(self):
        self.commits = {}   # hash -> Commit
        self.children = {}  # hash -> list[hash]
        self._seq = 0

    def __contains__(self, commit_hash):
        return commit_hash in self.commits

    def __len__(self):
        return len(self.commits)

    def get(self, commit_hash):
        """hash 로 커밋을 O(1)에 찾는다. 없으면 Unknown commit 에러."""
        commit = self.commits.get(commit_hash)
        if commit is None:
            raise MiniGitError(f"Unknown commit: {commit_hash}")
        return commit

    def add(self, message, author, parents, branch):
        """부모 목록을 받아 새 커밋을 만들고 저장소에 등록한다."""
        for parent in parents:
            self.get(parent)  # 존재하지 않는 부모 금지 -> 사이클 불가
        self._seq += 1
        timestamp = datetime.now()
        commit_hash = self._new_hash(message, author, timestamp)
        commit = Commit(commit_hash, message, author, timestamp, list(parents), self._seq, branch)
        self.commits[commit_hash] = commit
        self.children[commit_hash] = []
        for parent in parents:
            self.children[parent].append(commit_hash)
        return commit

    def _new_hash(self, message, author, timestamp):
        """세션 내 유일한 고정 길이 hash 를 만든다.

        생성 순번(seq)을 섞어 SHA-1 을 구하고, 혹시 앞 7자리가 겹치면
        salt 를 바꿔 다시 계산한다. 길이를 고정해 두면 PATH 의 사전순 비교가
        hash 단위 비교와 같아진다.
        """
        salt = 0
        while True:
            raw = f"{self._seq}|{author}|{message}|{timestamp.isoformat()}|{salt}"
            candidate = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:HASH_LENGTH]
            if candidate not in self.commits:
                return candidate
            salt += 1

    def neighbors(self, commit_hash):
        """부모-자식 연결을 무방향 간선으로 본 이웃 목록."""
        return self.commits[commit_hash].parents + self.children[commit_hash]


# ---------------------------------------------------------------------------
# 역색인
# ---------------------------------------------------------------------------

def tokenize(text):
    """공백 기준 split 후 소문자로 정규화한 토큰 목록."""
    return [token.lower() for token in text.split()]


class InvertedIndex:
    """keyword -> [commit_hash], author -> [commit_hash] 두 가지 역색인.

    검색 시 전체 커밋(N개)을 훑지 않고 해시맵에서 후보 목록을 O(1)에 꺼낸다.
    결과 크기를 k 라 하면 검색 비용은 O(k) 로, 순회 검색 O(N * 메시지 길이)보다 빠르다.
    """

    def __init__(self):
        self.by_keyword = {}
        self.by_author = {}

    def add(self, commit):
        """커밋 생성 시 호출되어 두 인덱스를 갱신한다."""
        seen = set()
        for token in tokenize(commit.message):
            if token in seen:
                continue  # 같은 메시지에 같은 단어가 반복돼도 hash 는 한 번만
            seen.add(token)
            self.by_keyword.setdefault(token, []).append(commit.hash)
        self.by_author.setdefault(commit.author.lower(), []).append(commit.hash)

    def search_keyword(self, keyword):
        """키워드(여러 단어면 모두 포함하는 커밋, AND)로 검색한다."""
        tokens = tokenize(keyword)
        if not tokens:
            return []
        result = self.by_keyword.get(tokens[0], [])
        for token in tokens[1:]:
            other = set(self.by_keyword.get(token, []))
            result = [h for h in result if h in other]
        return list(result)

    def search_author(self, author):
        return list(self.by_author.get(author.lower(), []))


# ---------------------------------------------------------------------------
# 정렬 알고리즘 (sorted / list.sort 사용 금지)
# ---------------------------------------------------------------------------

def merge_sort(items, key=lambda x: x):
    """병합 정렬. 평균/최악 O(n log n), 추가 메모리 O(n), 안정 정렬.

    왼쪽 원소를 동률일 때 먼저 가져가므로(<=) 입력 순서가 보존된다.
    """
    if len(items) <= 1:
        return list(items)
    mid = len(items) // 2
    left = merge_sort(items[:mid], key)
    right = merge_sort(items[mid:], key)
    merged = []
    i = j = 0
    while i < len(left) and j < len(right):
        if key(left[i]) <= key(right[j]):
            merged.append(left[i])
            i += 1
        else:
            merged.append(right[j])
            j += 1
    merged.extend(left[i:])
    merged.extend(right[j:])
    return merged


def quick_sort(items, key=lambda x: x):
    """퀵 정렬(무작위 피벗, 3-way 분할). 평균 O(n log n), 최악 O(n^2), 불안정 정렬.

    제자리(in-place) 분할을 쓰므로 같은 키를 가진 원소의 상대 순서가 바뀔 수 있다.
    """
    arr = list(items)
    keys = [key(x) for x in arr]

    def swap(a, b):
        arr[a], arr[b] = arr[b], arr[a]
        keys[a], keys[b] = keys[b], keys[a]

    stack = [(0, len(arr) - 1)]
    while stack:
        lo, hi = stack.pop()
        if lo >= hi:
            continue
        swap(lo, random.randint(lo, hi))
        pivot = keys[lo]
        lt, i, gt = lo, lo + 1, hi
        while i <= gt:
            if keys[i] < pivot:
                swap(lt, i)
                lt += 1
                i += 1
            elif keys[i] > pivot:
                swap(i, gt)
                gt -= 1
            else:
                i += 1
        stack.append((lo, lt - 1))
        stack.append((gt + 1, hi))
    return arr


class MinHeap:
    """(key, value) 최소 힙. 위상 정렬에서 '준비된 커밋' 중 가장 오래된 것을 꺼낼 때 쓴다."""

    def __init__(self):
        self._data = []

    def __len__(self):
        return len(self._data)

    def push(self, key, value):
        data = self._data
        data.append((key, value))
        i = len(data) - 1
        while i > 0:
            parent = (i - 1) // 2
            if data[parent][0] <= data[i][0]:
                break
            data[parent], data[i] = data[i], data[parent]
            i = parent

    def pop(self):
        data = self._data
        top = data[0]
        last = data.pop()
        if data:
            data[0] = last
            i = 0
            while True:
                left, right, smallest = 2 * i + 1, 2 * i + 2, i
                if left < len(data) and data[left][0] < data[smallest][0]:
                    smallest = left
                if right < len(data) and data[right][0] < data[smallest][0]:
                    smallest = right
                if smallest == i:
                    break
                data[i], data[smallest] = data[smallest], data[i]
                i = smallest
        return top[1]


# ---------------------------------------------------------------------------
# 그래프 탐색 알고리즘
# ---------------------------------------------------------------------------

def topological_order(graph):
    """Kahn 알고리즘으로 '부모가 항상 자식보다 먼저' 나오는 커밋 순서를 만든다.

    진입 차수(= 부모 수)가 0인 커밋부터 출력하고, 출력된 커밋의 자식들의
    차수를 줄여 0이 되면 준비 목록에 넣는다. 준비 목록이 여럿이면
    생성 순번이 빠른 커밋을 먼저 꺼낸다. 시간복잡도 O((V + E) log V).
    """
    indegree = {h: len(c.parents) for h, c in graph.commits.items()}
    ready = MinHeap()
    for h, degree in indegree.items():
        if degree == 0:
            ready.push(graph.commits[h].seq, h)

    order = []
    while ready:
        h = ready.pop()
        order.append(graph.commits[h])
        for child in graph.children[h]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.push(graph.commits[child].seq, child)
    return order


def shortest_path(graph, start, goal):
    """무방향 BFS 최단 경로. 여러 개면 'h1->h2->...' 문자열이 사전순 최소인 경로.

    1) goal 에서 BFS 를 돌려 모든 노드의 goal 까지 거리를 구한다.
    2) start 에서 출발해 '거리가 정확히 1 줄어드는 이웃' 중 hash 가 가장 작은 것을
       고르며 전진한다. hash 길이가 고정이라 각 단계의 최소 선택이 곧 문자열 사전순 최소다.
    없으면 None. 시간복잡도 O(V + E).
    """
    graph.get(start)
    graph.get(goal)

    dist = {goal: 0}
    queue = deque([goal])
    while queue:
        node = queue.popleft()
        for nxt in graph.neighbors(node):
            if nxt not in dist:
                dist[nxt] = dist[node] + 1
                queue.append(nxt)

    if start not in dist:
        return None

    path = [start]
    node = start
    while node != goal:
        best = None
        for nxt in graph.neighbors(node):
            if dist.get(nxt) == dist[node] - 1 and (best is None or nxt < best):
                best = nxt
        node = best
        path.append(node)
    return path


def find_ancestors(graph, commit_hash):
    """부모 방향 BFS 로 도달 가능한 모든 조상을 빠짐없이(중복 없이) 모은다.

    merge 커밋처럼 경로가 여러 갈래여도 visited 집합으로 한 번만 방문한다.
    시간복잡도 O(V + E).
    """
    graph.get(commit_hash)
    visited = {commit_hash}
    queue = deque([commit_hash])
    ancestors = []
    while queue:
        node = queue.popleft()
        for parent in graph.commits[node].parents:
            if parent not in visited:
                visited.add(parent)
                ancestors.append(graph.commits[parent])
                queue.append(parent)
    return ancestors


def lcs_diff(old_lines, new_lines):
    """LCS(최장 공통 부분 수열) DP 로 줄 단위 diff 를 만든다. O(n * m).

    반환: [(기호, 줄)] 목록. ' ' 공통, '-' 삭제, '+' 추가.
    """
    n, m = len(old_lines), len(new_lines)
    table = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            if old_lines[i] == new_lines[j]:
                table[i][j] = table[i + 1][j + 1] + 1
            else:
                table[i][j] = max(table[i + 1][j], table[i][j + 1])

    result = []
    i = j = 0
    while i < n and j < m:
        if old_lines[i] == new_lines[j]:
            result.append((" ", old_lines[i]))
            i += 1
            j += 1
        elif table[i + 1][j] >= table[i][j + 1]:
            result.append(("-", old_lines[i]))
            i += 1
        else:
            result.append(("+", new_lines[j]))
            j += 1
    result.extend(("-", line) for line in old_lines[i:])
    result.extend(("+", line) for line in new_lines[j:])
    return result


# ---------------------------------------------------------------------------
# 저장소
# ---------------------------------------------------------------------------

class Repository:
    """브랜치/HEAD/사용자 상태와 커밋 그래프, 역색인을 묶어 관리한다."""

    def __init__(self, user):
        self.user = user
        self.graph = CommitGraph()
        self.index = InvertedIndex()
        self.branches = {"main": None}  # branch -> 가리키는 commit hash (커밋 전이면 None)
        self.head = "main"              # 현재 브랜치 이름

    def head_commit(self):
        return self.branches[self.head]

    def create_branch(self, name):
        """현재 HEAD 커밋을 가리키는 새 브랜치를 만든다."""
        if name in self.branches:
            raise MiniGitError(f"Branch already exists: {name}")
        self.branches[name] = self.head_commit()

    def switch(self, name):
        if name not in self.branches:
            raise MiniGitError(f"Unknown branch: {name}")
        self.head = name

    def commit(self, message):
        """HEAD 를 부모로 하는 커밋을 만들고 브랜치를 전진시키며 역색인을 갱신한다."""
        parent = self.head_commit()
        parents = [parent] if parent else []
        return self._record(message, parents)

    def merge(self, name):
        """현재 브랜치 HEAD 와 대상 브랜치 HEAD 를 부모로 갖는 merge 커밋을 만든다."""
        if name not in self.branches:
            raise MiniGitError(f"Unknown branch: {name}")
        if name == self.head:
            raise MiniGitError("Cannot merge a branch into itself")
        ours, theirs = self.head_commit(), self.branches[name]
        if theirs is None:
            raise MiniGitError(f"Nothing to merge: {name} has no commits")
        if ours is None:
            raise MiniGitError(f"Nothing to merge into: {self.head} has no commits")
        if theirs == ours or theirs in {c.hash for c in find_ancestors(self.graph, ours)}:
            return None  # 이미 포함됨
        return self._record(f"Merge branch '{name}' into {self.head}", [ours, theirs])

    def _record(self, message, parents):
        commit = self.graph.add(message, self.user, parents, self.head)
        self.branches[self.head] = commit.hash
        self.index.add(commit)
        return commit

    def labels(self, commit_hash):
        """해당 커밋을 현재 가리키는 브랜치 이름들 (HEAD 표시 포함)."""
        names = []
        for name, target in self.branches.items():
            if target == commit_hash:
                names.append(f"HEAD -> {name}" if name == self.head else name)
        return names


# ---------------------------------------------------------------------------
# CLI (REPL)
# ---------------------------------------------------------------------------

HELP_TEXT = """Commands (case-insensitive):
  INIT <user_name>                 저장소 초기화 (main 브랜치, 사용자 설정)
  BRANCH <branch_name>             현재 HEAD 에서 새 브랜치 생성
  BRANCH                           브랜치 목록
  SWITCH <branch_name>             HEAD 를 브랜치로 이동
  COMMIT <message>                 새 커밋 생성
  LOG [--sort-by=date|author]      커밋 로그 (기본: 부모가 먼저 오는 위상 순서)
  PATH <commit1> <commit2>         두 커밋 사이 최단 경로
  ANCESTORS <commit_hash>          모든 조상 커밋
  SEARCH <keyword>                 메시지 키워드 검색
  SEARCH --author=<name>           작성자 검색
  MERGE <branch_name>              (보너스) merge 커밋 생성
  DIFF <file1> <file2>             (보너스) 텍스트 파일 줄 단위 비교
  BENCH [size ...]                 (보너스) 정렬 알고리즘 성능 비교
  HELP                             도움말
  EXIT | QUIT                      종료
문자열에 공백이 있으면 따옴표로 감싸세요. 예) COMMIT "Add login feature\""""


def format_commit(commit, labels=None):
    """커밋 한 개를 'commit <hash> (author, time) [labels]\\n<message>' 형태로 만든다."""
    header = f"commit {commit.hash} ({commit.author}, {commit.time_str()})"
    if labels is None:
        labels = [commit.branch]
    if labels:
        header += f" [{', '.join(labels)}]"
    return f"{header}\n    {commit.message}"


class MiniGitCLI:
    """mini-git> 프롬프트에서 명령을 파싱해 Repository 에 위임하고 결과 문자열을 돌려준다."""

    def __init__(self):
        self.repo = None
        self.handlers = {
            "init": self.cmd_init,
            "branch": self.cmd_branch,
            "switch": self.cmd_switch,
            "commit": self.cmd_commit,
            "log": self.cmd_log,
            "path": self.cmd_path,
            "ancestors": self.cmd_ancestors,
            "search": self.cmd_search,
            "merge": self.cmd_merge,
            "diff": self.cmd_diff,
            "bench": self.cmd_bench,
            "help": self.cmd_help,
        }
        # 저장소 없이 실행 가능한 명령
        self.no_repo_needed = {"init", "diff", "bench", "help"}

    def run(self):
        print("Mini Git - type HELP for commands, EXIT to quit.")
        while True:
            try:
                line = input("mini-git> ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if line.strip().lower() in ("exit", "quit"):
                print("Bye.")
                break
            output = self.execute(line)
            if output:
                print(output)
            print()

    def execute(self, line):
        """한 줄을 파싱/실행해 출력할 문자열을 반환한다."""
        try:
            tokens = shlex.split(line)
        except ValueError:
            return "Invalid args"
        if not tokens:
            return ""
        command, args = tokens[0].lower(), tokens[1:]
        handler = self.handlers.get(command)
        if handler is None:
            return f"Unknown command: {tokens[0]}"
        if command not in self.no_repo_needed and self.repo is None:
            return "Not a repository. Run INIT <user_name> first."
        try:
            return handler(args)
        except MiniGitError as error:
            return str(error)

    # --- 인자 헬퍼 ---------------------------------------------------------

    @staticmethod
    def _text_arg(args):
        """공백 포함 문자열 인자. 따옴표 없이 여러 토큰이 와도 하나로 합친다."""
        text = " ".join(args).strip()
        if not text:
            raise MiniGitError("Invalid args")
        return text

    @staticmethod
    def _exact_args(args, count):
        if len(args) != count:
            raise MiniGitError("Invalid args")
        return args

    # --- 명령 --------------------------------------------------------------

    def cmd_init(self, args):
        user = self._text_arg(args)
        reinit = self.repo is not None
        self.repo = Repository(user)
        title = "Reinitialized repository." if reinit else "Initialized repository."
        return f"{title}\nCurrent branch: main\nCurrent user: {user}"

    def cmd_branch(self, args):
        if not args:
            lines = []
            for name, target in self.repo.branches.items():
                mark = "*" if name == self.repo.head else " "
                lines.append(f"{mark} {name} -> {target or '(no commits)'}")
            return "\n".join(lines)
        (name,) = self._exact_args(args, 1)
        self.repo.create_branch(name)
        return f"Created branch: {name}"

    def cmd_switch(self, args):
        (name,) = self._exact_args(args, 1)
        self.repo.switch(name)
        return f"Switched to branch: {name}"

    def cmd_commit(self, args):
        commit = self.repo.commit(self._text_arg(args))
        return f"[{self.repo.head} {commit.hash}] {commit.message}"

    def cmd_log(self, args):
        commits = list(self.repo.graph.commits.values())
        if not commits:
            return "No commits yet."
        if not args:
            ordered = topological_order(self.repo.graph)
            return "\n".join(format_commit(c) for c in ordered)

        (option,) = self._exact_args(args, 1)
        if option.lower() == "--sort-by=date":
            # 동률(같은 초)이면 생성 순번으로
            ordered = merge_sort(commits, key=lambda c: (c.timestamp, c.seq))
        elif option.lower() == "--sort-by=author":
            # 작성자 이름(대소문자 무시) -> 동률이면 시간순
            ordered = merge_sort(commits, key=lambda c: (c.author.lower(), c.timestamp, c.seq))
        else:
            raise MiniGitError("Invalid args")
        return "\n".join(format_commit(c, labels=[]) for c in ordered)

    def cmd_path(self, args):
        start, goal = self._exact_args(args, 2)
        path = shortest_path(self.repo.graph, start, goal)
        if path is None:
            return "No path"
        return "Path: " + " -> ".join(path)

    def cmd_ancestors(self, args):
        (commit_hash,) = self._exact_args(args, 1)
        ancestors = find_ancestors(self.repo.graph, commit_hash)
        if not ancestors:
            return f"No ancestors of {commit_hash}"
        lines = [f"Ancestors of {commit_hash} ({len(ancestors)}):"]
        lines += [f"- {c.hash}: {c.message}" for c in ancestors]
        return "\n".join(lines)

    def cmd_search(self, args):
        if not args:
            raise MiniGitError("Invalid args")
        if args[0].lower().startswith("--author="):
            name = " ".join([args[0][len("--author="):]] + args[1:]).strip()
            if not name:
                raise MiniGitError("Invalid args")
            hashes = self.repo.index.search_author(name)
        elif args[0].startswith("--"):
            raise MiniGitError("Invalid args")
        else:
            hashes = self.repo.index.search_keyword(self._text_arg(args))

        commits = merge_sort([self.repo.graph.commits[h] for h in hashes], key=lambda c: c.seq)
        if not commits:
            return "No commits found."
        noun = "commit" if len(commits) == 1 else "commits"
        lines = [f"Found {len(commits)} {noun}:"]
        lines += [f"- {c.hash}: {c.message} ({c.author})" for c in commits]
        return "\n".join(lines)

    def cmd_merge(self, args):
        (name,) = self._exact_args(args, 1)
        commit = self.repo.merge(name)
        if commit is None:
            return "Already up to date."
        return f"[{self.repo.head} {commit.hash}] {commit.message}\nParents: {' '.join(commit.parents)}"

    def cmd_diff(self, args):
        file1, file2 = self._exact_args(args, 2)
        contents = []
        for path in (file1, file2):
            if not os.path.isfile(path):
                raise MiniGitError(f"File not found: {path}")
            with open(path, encoding="utf-8") as f:
                contents.append(f.read().splitlines())
        diff = lcs_diff(contents[0], contents[1])
        added = sum(1 for sign, _ in diff if sign == "+")
        removed = sum(1 for sign, _ in diff if sign == "-")
        lines = [f"--- {file1}", f"+++ {file2}"]
        lines += [f"{sign} {line}" for sign, line in diff]
        lines.append(f"({added} added, {removed} removed, {len(diff) - added - removed} common)")
        return "\n".join(lines)

    def cmd_bench(self, args):
        try:
            sizes = [int(a) for a in args] if args else [1000, 5000, 20000]
        except ValueError:
            raise MiniGitError("Invalid args")
        if any(size <= 0 for size in sizes):
            raise MiniGitError("Invalid args")
        return benchmark_sorts(sizes)

    def cmd_help(self, args):
        return HELP_TEXT


def benchmark_sorts(sizes):
    """merge_sort 와 quick_sort 의 실행 시간을 입력 크기별로 비교한다."""
    lines = [f"{'size':>8} | {'merge_sort':>12} | {'quick_sort':>12}"]
    lines.append("-" * len(lines[0]))
    for size in sizes:
        data = [random.randint(0, size) for _ in range(size)]
        timings = []
        for sort in (merge_sort, quick_sort):
            start = time.perf_counter()
            sort(data)
            timings.append(time.perf_counter() - start)
        lines.append(f"{size:>8} | {timings[0] * 1000:>10.2f}ms | {timings[1] * 1000:>10.2f}ms")
    return "\n".join(lines)


def main():
    MiniGitCLI().run()


if __name__ == "__main__":
    main()
