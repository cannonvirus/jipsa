# 설치와 첫 실행

## 설치

```
git clone <이 저장소> jipsa
cd jipsa
uv sync
claude
```

받은 폴더에서 Claude Code를 켜면 세션이 `CLAUDE.md`, 스킬, 훅을 읽는다. 복사할 파일은 없다. 처음 열 때 폴더 신뢰 확인에 동의한다. 훅은 `uv sync`가 만든 가상환경으로 돌므로 `uv sync`를 먼저 한다. 자세한 내용은 [Claude Code 연계](claude-code.md)다.

아래는 필요할 때만 한다.

- `.env`: Slack 웹훅이나 모델을 파일로 정하려면 `.env.example`을 `.env`로 복사해 채운다. 없어도 돈다. Slack 웹훅이 비어 있으면 보고는 `reports/`에만 남는다. `.env`는 git에 넣지 않는다. `.env`에 적은 값은 설정 스킬로 저장한 값보다 앞선다([설정](#설정)).
- `uv run jipsa sync-agents`: Codex 작업자를 쓸 때 `RULES.md`에서 `AGENTS.md`를 만든다.
- `npm install -g ccstatusline`: 상태줄 글자를 찍는다([상태줄](claude-code.md#상태줄)).
- `uv run jipsa check`: 환경을 점검한다.

Claude Code CLI가 경로에 있어야 세션과 작업자가 돈다. Codex CLI는 없으면 Codex 관련 기능(분석자, Codex 작업자, Codex 창 표시)만 빠진다.

## Monitor와 반대 검토 공급자

`python monitor.py`는 대시보드와 스케줄러를 보여 주는 콘솔 메뉴다. 위쪽에 서비스마다 상태, PID, 포트, 주소가 나오고, 대시보드와 스케줄러는 단축키 하나로 함께 켜기, 끄기, 다시 켜기를 한다. 끄면 대시보드 감시가 스케줄러를 다시 띄우지 않고, 켜면 그 멈춤이 풀린다. 실행 중 작업이 있으면 끄기와 다시 켜기는 묻지 않고 거절만 한다. 서비스는 창 없는 프로세스라 Monitor 창을 닫아도 돈다. 서비스 목록은 `scheduler/services.toml`이다.

마감 전 반대 검토는 `/jipsa-model`의 마감 전 공격 공급자(`JIPSA_ATTACK_PROVIDER`)로 고른다. 기본은 `codex`이고 Codex CLI가 없으면 `none`과 같게 돌아 검토 없이 마감한다. `claude`는 작업자와 같은 계열 모델이 도구와 웹 없이 한 번 검토하며 결과지에 같은 공급자 공격이라고 적힌다. 공급자가 `codex`가 아니거나 Codex가 없으면 사용 창 표시의 Codex 칸이 숨겨지고, `jipsa check`의 codex 줄은 선택 항목으로 나온다.

## 임시 폴더로 화면 보기

실제 상태 폴더를 쓰지 않고 화면만 보려면 임시 폴더를 환경 변수로 준다. 등록부는 이 저장소의 `projects/`를 그대로 읽는다. PowerShell 예다.

```
$t = "$env:TEMP\jipsa-try"
$env:JIPSA_STATE_DIR = "$t\state"; $env:JIPSA_RUNS_DIR = "$t\runs"; $env:JIPSA_REPORTS_DIR = "$t\reports"
uv run jipsa status
uv run jipsa web --port 8798 --no-open --no-watch
```

`--no-watch`는 스케줄러를 띄우지 않는 미리보기다. 브라우저에서 http://127.0.0.1:8798/ 을 연다. 화면 오른쪽 위 날짜 선택의 "데모"는 가짜 하루 기록을 그린다.

## 내 프로젝트 등록

1. Claude Code 세션에서 `/jipsa-register <이름>`을 부른다. 이름은 영문 소문자, 숫자, 밑줄만 쓴다. 경로, 종류, 자동 범위, 커밋 여부, GPU 메모리를 차례로 묻고(종류가 doc이면 허용 폴더까지) `projects/<이름>.toml`을 쓴다. 고치기는 `/jipsa-register <이름> edit`이다. 형식은 [registry.md](registry.md)다. 저장소에 든 등록부는 예시 `example_app`과 기타 일을 받는 `misc` 2개뿐이고, 새 등록부는 `.gitignore`가 막아 git에 들어가지 않는다.
   손으로 쓰려면 `projects/example_app.toml`을 복사해 편집기로 고친다. 세션의 편집 도구로 고치면 코드 보호 훅이 거절한다([훅](claude-code.md#훅)).
2. 할 일을 넣는다. `uv run jipsa todo add "<이름> <할 일> | <완료 기준>"`이나 대시보드 TODO 탭으로 넣는다. 형식은 [todo.md](todo.md)다. 넣은 할 일은 그대로는 돌지 않고, `uv run jipsa todo run <번호>`로 시킨 줄만 돈다.
3. `uv run jipsa web`으로 대시보드를 켠다. 대시보드가 스케줄러를 함께 띄우고, 스케줄러가 시킨 줄을 worktree와 기능 브랜치에서 작업자로 돌린다. 자동 범위는 기능 브랜치 커밋까지이고 푸시는 하지 않는다.

## 일을 시키는 길

사람이 시킨 일만 돈다. 시키는 길은 줄 종류에 따라 둘이다.

- 일회성 줄: `uv run jipsa todo run <번호>`나 대시보드의 Do 단추로 바로 돈다. 열린 세션이 있으면 세션 서브에이전트가, 없으면 스케줄러 작업자가 맡는다.
- Cycle 줄(cycle 칸이 있는 줄): `uv run jipsa todo run <번호> [시작 HH:MM] [마감 HH:MM|+4h]`로 시작과 마감을 정한다. 시작 기본값은 지금이다. 멈추기는 `uv run jipsa todo stop <번호>`, 마감 고치기는 `uv run jipsa todo until <번호> <HH:MM|+4h>`다.

Auto 모드는 없어졌다. `uv run jipsa auto`는 없어졌다는 안내와 지금 상태만 찍고, `on`, `off`, `add`, `top`, `rm`은 아무것도 바꾸지 않고 종료 코드 1로 끝난다.

## 설정

대시보드의 설정 탭은 없어졌고, 설정은 세션 스킬 다섯으로 질문에 답해 넣는다. 스킬은 `jipsa settings`와 `jipsa registry` 명령을 부른다.

| 스킬 | 다루는 값 |
| --- | --- |
| `/jipsa-register` | 프로젝트 등록 만들기, 고치기(`edit`), 보기(`show`) |
| `/jipsa-slack` | Webhook 주소, 시험 글(`test`), 아침 요약 시각, 알림 켜짐 |
| `/jipsa-model` | 작업자 모델, 가벼운 호출 모델, Codex 모델, 마감 전 공격 공급자 |
| `/jipsa-config` | 동시 작업 수, 자동 작업 동시 수, Ollama 주소, 자료 폴더, 되돌리기(`undo`) |
| `/jipsa-cleanup` | 기록 보관 기한 셋, 중간 산출물 정리 |

- 지금 값은 `uv run jipsa settings show`로 본다. 비밀값은 설정됨 여부만 보인다. `/jipsa-slack`, `/jipsa-model`, `/jipsa-config`, `/jipsa-cleanup`은 `show`를 붙이면 묻지 않고 그 값만 보인다.
- 값은 상태 폴더의 `config.json`에 저장한다. `.env`나 환경 변수에 있는 값이 앞서므로 그 칸은 `.env`를 고쳐야 바뀐다. Webhook 주소와 알림 켜짐은 이 파일에 들지 않아 `/jipsa-config undo`로 되돌아가지 않는다.
- 저장한 값은 스케줄러와 대시보드를 다시 띄워야 반영된다. 스킬이 다시 띄울지 묻고 `uv run jipsa settings restart`를 돌린다. 등록은 스케줄러가 다음 주기에 읽고, Webhook 주소와 알림 켜짐은 바로 반영된다.
- 스케줄러만 끄려면 `uv run jipsa settings stop`이다. 대시보드 감시가 다시 띄우지 않고, `uv run jipsa settings start`나 `restart`가 멈춤을 푼다. 실행 중 작업이 있으면 거절하며, `--force`를 주면 스케줄러가 띄운 작업 프로세스까지 끊고 그 줄은 다음 시작 때 대기로 돌아간다. 세션 서브에이전트 작업은 스케줄러 밖이라 끊지 않는다.
- 대시보드 오른쪽 위 메뉴에는 새로고침 주기와 Slack 알림 스위치, GPU 대기 표시가 있다.

## 낱말 검사, 결과지 초안, 기록 정리, 등록부 한 줄

- **낱말 검사**: 마감 때 보고서 본문과 result.json 요약, 선택지에서 `policies/wording.md` 2절 표의 낱말을 세어 결과지 아래와 마감 출력에 주의 줄을 남긴다. 결과는 막지 않는다. 자기 팀에서 자주 나오는 번역 투 낱말은 표에 줄로 더한다.
- **결과지 초안**: 사람 입력이나 결과지 답에 '초안'이 들어오면 훅이 세션 기록에 남기고, 30분 안에 연 `jipsa begin`이 그 실행을 초안 실행으로 표시한다. `--draft`로 직접 표시하고 `--no-draft`로 뺄 수 있다. 초안 실행은 실행 폴더 안의 HTML 경로를 result.json `preview_url`에 적어야 마감된다.
- **기록 정리**: `jipsa runs-clean`은 끝난 작업의 브라우저 프로필, 임시 DB 사본, 원응답 로그 같은 큰 중간 파일을 휴지통 폴더(기본 홈 폴더 아래 `jipsa-trash/runs-<날짜>`)로 옮긴다. 지우지 않는다. 기본은 미리 보기이고 `--apply`로 옮긴다.
- **등록부 한 줄**: `jipsa registry add <프로젝트> <칸> "<문구>" --run <실행ID>`는 그 실행의 사람 답과 고른 안에 따옴표로 적힌 문구만 등록부의 정해진 목록 칸 끝에 더한다. 작업자 셸에서는 거절하고, `--dry-run`으로 더할 줄만 볼 수 있다.
- **프로젝트 전용 규칙**: `docs/local/rules.md`를 만들면 그 내용이 공통 규칙 뒤에 작업자 지시로 들어간다. git에 넣지 않으며, 파일이 없으면 그 절만 빠진다.

## 테스트할 때 주의

에이전트 셸(Claude Code, Codex 안)에서 운영 상태 폴더로 스케줄러 루프, 모의 실행, 기본 포트가 아닌 대시보드를 띄우면 `jipsa`가 막는다. 테스트면 위처럼 `JIPSA_STATE_DIR`, `JIPSA_RUNS_DIR`, `JIPSA_REPORTS_DIR`를 임시 폴더로 주고, 운영으로 돌릴 것이 맞으면 `JIPSA_LIVE=1`을 준다.

## 그림 찍기

보고서 그림은 `tools/md_shot.py`로 찍는다. Playwright 브라우저가 필요하다.

```
uv run --with playwright python -m playwright install chromium
uv run --with playwright python tools/md_shot.py --url http://127.0.0.1:8765/ --height 1000 --out screen-x.png
```
