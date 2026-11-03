# 프로젝트 등록부 형식

등록부는 `projects/<이름>.toml` 한 파일에 프로젝트 하나다. 작업자가 무엇을 고칠 수 있고 무엇을 못 하는지, 얼마나 오래 돌 수 있는지를 적는다. jipsa는 이 값으로 작업자 권한 설정(`--settings`의 deny 규칙)과 지시문을 만든다. 저장소에 든 예는 `projects/` 아래 `example_app`과 `misc` 2개다. 새로 만든 등록부는 `.gitignore`가 막아 git에 들어가지 않는다.

## 최상위

| 키 | 뜻 |
| --- | --- |
| `name` | 등록부 이름. 할 일 줄의 프로젝트 칸과 같다 |
| `path` | 저장소 위치. 절대 경로로 적는다. 코드가 `~`를 풀지 않는다 |
| `kind` | `code`, `doc`, `experiment`, `hardware`, `game` 가운데 하나. `code`와 `experiment`는 worktree에서 돈다 |
| `priority` | 큐 순서. 작을수록 먼저다 |
| `run_prefix` | 작업자가 명령을 돌릴 때 앞에 붙이는 접두어(예: `uv run`) |

## 절

| 절 | 키 | 뜻 |
| --- | --- | --- |
| `[scope]` | `auto` | 자동으로 해도 되는 범위 한 줄 |
| | `commit` | 기능 브랜치에 커밋할지 |
| | `manual_only` | 세션 기록 전용이면 true. 스케줄러가 고르지 않는다 |
| | `allowed_dirs` | 새 파일을 만들 수 있는 폴더(문서 프로젝트) |
| | `notes` | 작업자 지시문에 들어가는 추가 규칙 |
| `[paths]` | `no_read` | 읽지도 쓰지도 않는 경로(예: `.env`) |
| | `read_only` | 읽기만 하는 경로 |
| `[paths.generated]` | `"<경로>" = "<명령>"` | 직접 고치지 않고 명령으로 다시 만드는 생성물 |
| `[links]` | `dirs` | worktree에 연결해 줄 큰 폴더(예: `.venv`) |
| `[external]` | `read`, `forbid` | 허용하는 외부 읽기와 금지하는 외부 행동 |
| `[resources]` | `gpu_vram_gb`, `gpu_exclusive`, `ram_gb`, `ollama_models` | 자원 리스. 모자라면 기다린다 |
| `[limits]` | `total_minutes`, `segment_minutes` | 총 상한과 구간 상한(분) |
| `[deps]` | `manager`, `lock_file`, `venv` | 의존성 관리 방식(`uv-lock` 또는 `uv-pip`) |
| `[worker]` | `provider`, `model` | 작업자 공급자(`claude` 또는 `codex`)와 모델 |
| `[preview]` | `base` | 미리보기 서버 주소. 문서 사이트 초안 주소를 결과지에 건다 |
| `[match_minutes]` | `"<게임>:<인원>" = 분` | 게임 같은 반복 실험의 한 판 시간. 있으면 `jipsa begin --games`가 판 수로 상한을 계산한다 |
| `[questions]` | `items` | 사람이 정해야 할 열린 질문 |

## 만들고 고치기

파일을 직접 고치지 않아도 된다. 새 프로젝트는 대시보드 TODO 탭의 **프로젝트 만들기**나 세션의 `/jipsa-register <이름>`으로 이름 하나만 넣어 만든다. 세션에서 고치고 보려면 `/jipsa-register <이름> edit`, `/jipsa-register <이름> show`를 부른다. 스킬이 부르는 명령은 아래와 같다. 이름은 영문 소문자, 숫자, 밑줄만 40자 안으로 쓴다.

- `uv run jipsa registry show [<이름>]`: 등록 목록, 또는 그 등록의 칸 19개와 값을 보인다.
- `uv run jipsa registry new <이름> [path=<경로>] [kind=<종류>]`: 새 등록을 만든다. 경로를 주지 않으면 jipsa 저장소와 나란한 폴더를 만들어 git 첫 커밋까지 하고, 종류 기본값은 code다. `--check`를 붙이면 쓰지 않고 검사만 한다.
- `uv run jipsa registry edit <이름> <칸>=<값> <칸>+=<값>`: 바뀐 키 줄만 고치고 주석과 키 순서는 둔다. `--check`도 같다.
- `uv run jipsa registry add <프로젝트> <칸> <문구> --run <실행ID>`: 그 실행의 사람 답에 적힌 문구만 목록 칸 끝에 더한다.

쓰는 명령은 메인 세션 전용이고 작업자 셸에서는 거절한다.

## 기타 등록부

`projects/misc.toml`은 등록부 프로젝트에 속하지 않는 세션 일(점검, 조사, 선정)을 기록하는 자리다. 화면에는 "기타"로 보인다. 코드가 이 이름을 쓰므로 지우지 않는다.
