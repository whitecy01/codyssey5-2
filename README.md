# Mini Git

커밋 메타데이터(hash, message, author, timestamp, parents)를 기준으로 Git의 핵심 구조를 직접 구현한 CLI 프로그램입니다.
커밋 그래프(DAG), 그래프 탐색(위상 정렬, BFS), 직접 구현한 정렬 알고리즘, 역색인을 다룹니다.

## 실행

```bash
python main.py      # Python 3.10 이상, 외부 라이브러리 없음
```

`mini-git>` 프롬프트에서 명령을 입력하고 `exit` 또는 `quit`으로 종료합니다.

## 명령어

명령어는 대소문자를 구분하지 않습니다. 공백이 들어간 문자열은 따옴표로 감쌉니다.

| 명령 | 설명 |
| --- | --- |
| `INIT <user_name>` | 저장소 초기화, `main` 브랜치 생성, HEAD와 사용자 설정 |
| `BRANCH <branch_name>` | 현재 HEAD 커밋을 가리키는 브랜치 생성 (`BRANCH`만 입력하면 목록 출력) |
| `SWITCH <branch_name>` | HEAD를 해당 브랜치로 이동 |
| `COMMIT <message>` | HEAD를 부모로 하는 커밋 생성, 역색인 갱신 |
| `LOG` | 부모가 항상 자식보다 먼저 나오는 순서(위상 정렬)로 출력 |
| `LOG --sort-by=date\|author` | 시간순 또는 작성자순 정렬 |
| `PATH <commit1> <commit2>` | 두 커밋 사이 최단 경로, 없으면 `No path` |
| `ANCESTORS <commit_hash>` | 도달 가능한 모든 조상 커밋 |
| `SEARCH <keyword>` | 메시지 키워드 검색 (여러 단어면 모두 포함하는 커밋) |
| `SEARCH --author=<name>` | 작성자 검색 |
| `HELP` | 도움말 |

에러 메시지: `Invalid args`, `Unknown branch: <name>`, `Unknown commit: <hash>`, `Unknown command: <cmd>`, `Not a repository. Run INIT <user_name> first.`

## 실행 예시

```
mini-git> init "Alice"
Initialized repository.
Current branch: main
Current user: Alice

mini-git> commit "Initial commit"
[main 588ece3] Initial commit

mini-git> branch feature
Created branch: feature

mini-git> switch feature
Switched to branch: feature

mini-git> commit "Add login feature"
[feature bb66463] Add login feature

mini-git> switch main
Switched to branch: main

mini-git> commit "Add payment feature"
[main 40bf1c6] Add payment feature

mini-git> log
commit 588ece3 (Alice, 2026-10-26 21:03:31) [main]
    Initial commit
commit bb66463 (Alice, 2026-10-26 21:03:31) [feature]
    Add login feature
commit 40bf1c6 (Alice, 2026-10-26 21:03:31) [main]
    Add payment feature

mini-git> path bb66463 40bf1c6
Path: bb66463 -> 588ece3 -> 40bf1c6

mini-git> search "login"
Found 1 commit:
- bb66463: Add login feature (Alice)
```

LOG의 `[branch]`는 커밋이 만들어진 브랜치입니다. hash는 실행할 때마다 달라집니다.

## 코드 구조 (`main.py`)

| 구성 요소 | 역할 |
| --- | --- |
| `Commit`, `CommitGraph` | 커밋 노드와 `hash -> Commit` 해시맵 저장소, 자식 목록 |
| `InvertedIndex` | `keyword -> [hash]`, `author -> [hash]` 역색인 |
| `merge_sort` | 직접 구현한 정렬 (`sorted()`, `list.sort()` 미사용) |
| `MinHeap` | 위상 정렬에서 준비된 커밋을 생성 순서대로 꺼내는 최소 힙 |
| `topological_order` | Kahn 알고리즘 (LOG) |
| `shortest_path` | 무방향 BFS 최단 경로 (PATH) |
| `find_ancestors` | 부모 방향 BFS (ANCESTORS) |
| `Repository` | 브랜치, HEAD, 사용자 상태와 커밋 처리 |
| `MiniGitCLI` | REPL, 명령 파싱(`shlex`)과 에러 처리 |

## 설계 설명

### 커밋 그래프는 왜 DAG인가

커밋은 부모를 가리키고, 부모는 자식보다 항상 먼저 존재합니다. 새 커밋은 이미 있는 커밋만 부모로 삼을 수 있고, 한 번 만든 커밋의 부모는 바뀌지 않습니다. 그래서 간선은 항상 과거 방향으로만 생기고, 어떤 커밋에서 부모를 따라가도 자기 자신으로 돌아올 수 없습니다(비순환). 또 커밋은 부모를 0개 이상 가질 수 있어서(실제 Git의 merge 커밋은 부모가 2개) 트리가 아닌 일반 그래프가 됩니다. 이 둘을 합치면 방향성 비순환 그래프, 즉 DAG입니다.

`CommitGraph.add`는 존재하지 않는 부모를 거부하므로 사이클이 생길 수 없습니다.

### hash 생성

`생성 순번 | 작성자 | 메시지 | 시각 | salt`를 SHA-1로 해시해 앞 7자리를 씁니다. 이미 있는 hash와 겹치면 salt를 올려 다시 계산하므로 세션 안에서 중복되지 않습니다. 길이를 7자리로 고정한 이유는 아래 PATH 설명에 있습니다.

### LOG: 부모가 먼저 나오는 출력 (위상 정렬)

최신순이나 단순 시간순은 "부모가 먼저"를 구조적으로 보장하지 않습니다(시계가 같거나 어긋날 수 있음). 그래서 Kahn 알고리즘을 씁니다.

1. 각 커밋의 진입 차수를 부모 수로 둡니다.
2. 차수가 0인 커밋(루트)을 준비 목록에 넣습니다.
3. 준비 목록에서 하나를 꺼내 출력하고, 그 자식들의 차수를 1씩 줄입니다. 0이 된 자식을 준비 목록에 넣습니다.

모든 부모가 출력된 뒤에야 자식의 차수가 0이 되므로 부모가 항상 먼저 나옵니다. 준비된 커밋이 여럿이면 최소 힙으로 생성 순번이 빠른 것을 먼저 꺼냅니다. 시간복잡도는 O((V + E) log V)입니다.

### PATH: 최단 경로와 사전순 최소 경로

부모-자식 연결을 무방향 간선으로 보고 BFS를 씁니다. 간선 가중치가 모두 1이라 BFS가 처음 도달한 거리가 최단 거리입니다.

최단 경로가 여러 개일 때 `hash1->hash2->...` 문자열이 사전순으로 가장 작은 경로를 고르는 방법은 다음과 같습니다.

1. 도착 커밋에서 BFS를 돌려 모든 커밋의 "도착까지 거리"를 구합니다.
2. 출발 커밋에서 시작해, 거리가 정확히 1 줄어드는 이웃 중 hash가 가장 작은 것을 골라 전진합니다.

거리가 1씩 줄어드는 이웃만 따라가므로 항상 최단 경로 위에 있고, 막다른 길이 없습니다. hash 길이가 고정이라 문자열의 사전순 비교는 앞에서부터 hash를 하나씩 비교하는 것과 같습니다. 따라서 각 단계에서 가장 작은 hash를 고르면 전체 문자열도 사전순 최소가 됩니다. 시간복잡도는 O(V + E)입니다. 도착 커밋에 닿지 못하면 `No path`를 출력합니다. 예를 들어 첫 커밋 전에 브랜치를 만들고 양쪽에서 각각 커밋하면 루트가 2개인 분리된 그래프가 됩니다.

### ANCESTORS: 모든 조상 탐색

부모 방향으로 BFS를 돌면서 `visited` 집합으로 중복 방문을 막습니다. 같은 조상으로 가는 경로가 여러 개여도 한 번씩만, 빠짐없이 출력합니다. 시간복잡도는 O(V + E)입니다.

### 정렬 알고리즘 (병합 정렬)

| 평균 | 최악 | 추가 메모리 | 안정성 |
| --- | --- | --- | --- |
| O(n log n) | O(n log n) | O(n) | 안정 |

- 배열을 반으로 나눠 각각 정렬한 뒤 병합합니다. 분할 깊이가 log n이고 각 깊이에서 n번 비교하므로 입력 모양과 관계없이 O(n log n)입니다.
- 병합할 때 키가 같으면 왼쪽 원소를 먼저 가져가므로(`<=`) 입력 순서가 유지되는 안정 정렬입니다.
- `key` 함수를 받아 비교 기준을 바꿀 수 있습니다.
  - `--sort-by=date`: `(timestamp, 생성 순번)`
  - `--sort-by=author`: `(작성자 소문자, timestamp, 생성 순번)`, 즉 같은 작성자 안에서는 시간순

### 역색인

커밋을 만들 때 메시지를 공백으로 split한 뒤 lower로 정규화한 토큰마다 `keyword -> [hash]` 목록에 hash를 추가합니다. 작성자도 `author -> [hash]`에 추가합니다.

- 순회 검색: 커밋 N개의 메시지를 모두 확인하므로 O(N × 메시지 길이)
- 역색인 검색: 해시맵에서 키워드 목록을 O(1)에 꺼내므로 결과 수 k에 대해 O(k)

커밋 수가 늘어도 검색 비용은 결과 크기에만 비례합니다. 대신 인덱스를 저장할 메모리가 더 들고, 커밋할 때 갱신 비용(토큰 수만큼)이 생깁니다.

## 제약 사항 준수

- 그래프 라이브러리, `sorted()`, `list.sort()`, `heapq`를 쓰지 않습니다.
- 파일 내용 추적, 네트워크, 영속 저장은 구현하지 않습니다. 모든 데이터는 메모리에만 있습니다.
