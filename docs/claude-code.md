# Claude Code 연계

jipsa는 Claude Code 세션을 유인 모드의 입구로 쓴다. 세션이 작업을 넣고 서브에이전트를 띄우고, 훅이 세션 활동을 대시보드에 기록한다. 이 연계에 필요한 파일은 저장소에 들어 있으므로 따로 복사하지 않는다. `uv sync`로 가상환경을 만든 뒤 jipsa 폴더에서 `claude`를 켜면 세션이 읽는다. 처음 열 때 나오는 폴더 신뢰 확인에 동의해야 훅이 돈다.

| 파일 | 세션에서 하는 일 |
| --- | --- |
| `CLAUDE.md` | 공통 규칙을 읽히고, 작업 넣기와 상태 보기는 `/jipsa` 스킬을 따르게 한다 |
| `.claude/skills/<이름>/SKILL.md` | 슬래시 명령과 말로 시키는 절차 8개 |
| `.claude/settings.json` | 아래 훅과 상태줄 연결. 경로는 `$CLAUDE_PROJECT_DIR`로 적어 컴퓨터마다 고치지 않는다 |

개인 설정은 `.claude/settings.local.json`에 둔다. 무시 목록에 있어 커밋되지 않는다.

## 훅

`hooks/track.py`는 세션 시작, 입력, 도구 호출, 서브에이전트 시작과 끝, 턴 끝, 세션 끝을 상태 폴더에 적는다. 기록 말고 세션 동작을 바꾸는 일도 한다.

| 때 | 하는 일 | 끄는 법 |
| --- | --- | --- |
| 입력 | 입력이 묻는 말이면 결과지로 내라는 안내를 세션에 붙인다 | `JIPSA_CHAT_MARKERS=0` |
| 입력 | 입력에 '초안'이 있으면 세션 기록에 남겨, 30분 안의 `jipsa begin`이 초안 실행으로 표시한다 | `begin --no-draft` |
| 입력, 턴 끝 | 일하는 중인 세션에 대시보드에서 넣은 답과 Do 요청을 넘긴다. 턴 끝이면 턴을 막고 넘긴다 | 없음 |
| 턴 끝 | 마지막 답이 300자를 넘으면 턴 끝을 한 번 막아 결론은 결과지로 내게 한다. 한 턴에 두 번 막지 않는다 | 한도는 `JIPSA_CHAT_LIMIT` |
| 턴 끝 | 300자 안이라도 "원인은", "때문이다" 같은 결론 문장 꼴이면 같은 방식으로 한 번 막는다 | `JIPSA_CHAT_MARKERS=0` |

턴 끝 막기는 사람이 보는 메인 세션에만 낸다. 서브에이전트와 `claude -p` 작업자에는 내지 않는다. 세션이 답을 다시 쓰는 일이 보이면 이 훅 때문이다. 환경 변수는 세션을 띄우기 전에 준다.

훅은 서브에이전트 모델을 강제하지 않고 세션 시작을 막지 않는다. 서브에이전트 모델 지정은 `jipsa begin` 출력과 `/jipsa` 스킬의 안내로만 전한다.

`hooks/guard.py`는 코드 보호 훅이다. 서브에이전트가 worktree 대신 원본 폴더를 고치는 일을 막는다. jipsa 폴더 자신의 `scheduler`, `adapters`, `web`, `tools`, `hooks`, `policies`, `.claude/skills`, `.claude/settings*`, `projects/*.toml`, 맨 위의 `.py`와 `.toml`을 고치는 Edit와 Write 호출을 거절한다. 셸 명령은 쓰기로 보이면 경고만 붙이고 막지 않는다. jipsa 코드를 세션에서 직접 고치려면 `JIPSA_ALLOW_ORIGIN_EDIT=1`을 주고 세션을 띄운다. 값이 있으면 이 훅은 아무것도 하지 않는다.

훅 안의 오류는 세션을 막지 않는다.

마감 때 서브에이전트의 토큰과 도구 호출은 `--agent` 이름이 든 기록 파일에서 들여온다. Agent 호출에 이름을 줄 수 없는 환경(`claude -p` 등)에서는 파일을 찾지 못한다는 줄을 찍고 그 수치 없이 마감한다. 결과지와 실행 기록은 그대로 남는다.

## 상태줄

`tools/statusline.py`는 상태줄 입력의 사용 창(5시간, 주간) 값을 상태 폴더에 남겨 대시보드로 넘기고, 같은 입력을 [ccstatusline](https://www.npmjs.com/package/ccstatusline)에 넘겨 그 출력을 찍는다. 글자를 찍는 일은 ccstatusline이 하므로 따로 설치한다.

```
npm install -g ccstatusline
```

없어도 오류는 없다. 값은 남고 상태줄만 빈다. 다른 상태줄을 쓰려면 `.claude/settings.local.json`에 `statusLine`을 적는다.

## Windows 밖에서

설정의 파이썬 경로는 `.venv/Scripts/python.exe`로 고정했다. jipsa가 Windows 11 기준이고, 훅이 빨라야 해서 `uv run`을 거치지 않으며, 설정 파일에는 운영체제별 분기가 없기 때문이다. macOS와 Linux에는 이 경로가 없어 훅과 상태줄이 돌지 않고, 세션 기록, 턴 끝 막기, 답 전달, 코드 보호가 빠진다. 스킬과 `CLAUDE.md`는 그대로 읽힌다. 쓰려면 `.claude/settings.json`의 `.venv/Scripts/python.exe`를 모두 `.venv/bin/python`으로 바꾼다. 이 환경에서는 확인하지 않았다.

jipsa 자신을 등록해 worktree에서 돌리면 그 worktree가 프로젝트 폴더가 되어 같은 경로를 찾는다. 이때는 등록부 `[links]`의 `dirs`에 `.venv`를 넣는다.

## 스킬

세션에서 "my_app에 X 해 줘", "상태 보여 줘" 같은 말이나 슬래시 명령에 이 절차가 쓰인다.

| 스킬 | 하는 일 |
| --- | --- |
| `/jipsa` | 세션이 따르는 절차(작업 넣기, 서브에이전트로 일 시키기, 확인 필요 답하기) |
| `/todo` | 할 일과 메모, 한 줄 시키기, 멈추기와 마감 고치기, cycle 목표 |
| `/auto` | 없어진 Auto 명령 안내. `jipsa auto`를 돌려 안내와 지금 상태를 보인다 |
| `/jipsa-register` | 프로젝트 등록 만들기, 고치기, 보기 |
| `/jipsa-slack` | Slack Webhook 주소, 시험 글, 아침 요약 시각, 알림 켜짐 |
| `/jipsa-model` | 작업자 모델, 가벼운 호출 모델, Codex 모델, 마감 전 공격 공급자 |
| `/jipsa-config` | 동시 작업 수, Ollama 주소, 자료 폴더, 설정 되돌리기 |
| `/jipsa-cleanup` | 기록 보관 기한과 중간 산출물 정리 |

설정 스킬 다섯의 쓰임은 [설치와 첫 실행](getting-started.md#설정)에 있다. `docs/claude-code/<이름>-skill.md`는 옛 사본 자리이고 원문을 가리키는 안내만 남겼다.

## 작업자 권한

작업자(`claude -p`)는 `policies/claude_settings.json`의 공통 deny 규칙에 등록부의 금지 경로를 더한 설정 파일로 돈다. 공통 규칙 `RULES.md`는 `--append-system-prompt`로 붙는다. Codex 작업자에게는 `jipsa sync-agents`가 만든 `AGENTS.md`가 같은 규칙을 준다. `AGENTS.md`는 생성물이라 git에 넣지 않으며, Codex를 쓸 때만 만들면 된다.
