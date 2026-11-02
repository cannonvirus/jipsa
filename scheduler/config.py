"""경로, 환경 변수, 상수. .env.example을 따른다."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

POLICIES = ROOT / "policies"
PROJECTS = Path(os.environ["JIPSA_PROJECTS_DIR"]) if os.environ.get("JIPSA_PROJECTS_DIR") else ROOT / "projects"  # 시험용으로 등록부 사본 폴더를 준다
RUNS = Path(os.environ["JIPSA_RUNS_DIR"]) if os.environ.get("JIPSA_RUNS_DIR") else ROOT / "runs"  # 시험용
WORKTREES = ROOT / "worktrees"
RUNTIME = ROOT / "runtime"
STATE = Path(os.environ["JIPSA_STATE_DIR"]) if os.environ.get("JIPSA_STATE_DIR") else RUNTIME / "state"  # 시험용으로 상태 폴더를 바꾼다
CLI_CWD = RUNTIME / "cli"  # 가벼운 호출과 서칭 호출의 작업 폴더. 프로젝트 CLAUDE.md를 읽지 않게 따로 둔다
SETTINGS_DIR = STATE / "settings"
REPORTS = Path(os.environ["JIPSA_REPORTS_DIR"]) if os.environ.get("JIPSA_REPORTS_DIR") else ROOT / "reports"  # 시험용

RULES_FILE = ROOT / "RULES.md"
AGENTS_FILE = ROOT / "AGENTS.md"
RECOMMEND_FILE = POLICIES / "recommend.md"
SETTINGS_FILE = POLICIES / "claude_settings.json"


# 전역 설정 파일(261102-jipsa-26). 상태 폴더의 config.json 한 장이고 키는 환경 변수 이름 그대로다.
# 읽는 순서는 환경 변수, 설정 파일, 기본값이다. 환경 변수(.env 포함)가 있으면 설정 파일 값은 쓰지 않고 저장도 거절한다.
# 저장 직전 판 하나를 config.prev.json에 남긴다. 항목 목록과 저장은 scheduler/settings.py다.
CONFIG_FILE = STATE / "config.json"
CONFIG_PREV_FILE = STATE / "config.prev.json"


def file_values(path: Path | None = None) -> dict[str, str]:
    """설정 파일의 값. 키와 값 모두 문자열로 맞춘다. 파일이 없거나 깨졌으면 빈 사전이다."""
    import json

    try:
        raw = json.loads((path or CONFIG_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): ("1" if v is True else "0" if v is False else str(v)) for k, v in raw.items() if v is not None}


_FILE_VALUES = file_values()


def setting(name: str, default: str) -> str:
    """설정값 하나. 환경 변수, 설정 파일, 기본값 순이다. 빈 문자열은 없는 것으로 본다."""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    value = _FILE_VALUES.get(name, "").strip()
    return value or default


def setting_source(name: str) -> str:
    """값의 출처. 환경 변수, 설정 파일, 기본값 가운데 하나다."""
    if os.environ.get(name, "").strip():
        return "환경 변수"
    if _FILE_VALUES.get(name, "").strip():
        return "설정 파일"
    return "기본값"


_env = setting


MODEL_WORKER = _env("JIPSA_MODEL_WORKER", "opus")
MODEL_FAST = _env("JIPSA_MODEL_FAST", "claude-haiku-5-5")
CODEX_MODEL = _env("JIPSA_CODEX_MODEL", "gpt-6.1-sol")
CODEX_WORKER_MODEL = _env("JIPSA_CODEX_WORKER_MODEL", CODEX_MODEL)
CODEX_WINDOWS_SANDBOX = _env("JIPSA_CODEX_WINDOWS_SANDBOX", "elevated")  # Codex 작업자의 Windows 샌드박스 방식
# Codex 창(Codex의 5시간 사용 창). 실제 사용량이 없을 때 어림에 쓰는 기준 호출 횟수다.
# 비율로 Codex를 막거나 Claude로 넘기는 규칙은 없앴다(261102-jipsa-42 사용자 답). 예전 설정 파일과 .env의 JIPSA_CODEX_NEAR, JIPSA_CODEX_RESUME은 읽지 않는다
CODEX_WINDOW_CALLS = int(_env("JIPSA_CODEX_WINDOW_CALLS", "40"))
# Claude 사용 창 비율로 새 시작과 동시 수를 막는 규칙도 없앴다(261102-jipsa-50 사용자 답). 예전 JIPSA_CLAUDE_STOP, JIPSA_CLAUDE_RESUME, JIPSA_AUTO_CAP_SOFT는 읽지 않는다
OLLAMA_URL = _env("JIPSA_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
# 비밀값은 환경 변수(.env 포함) 다음에 상태 폴더의 비밀값 파일(secrets.json)에서 읽는다(261102-jipsa-28). 설정 파일(config.json)에는 두지 않는다.
# 비밀값 파일은 jipsa settings webhook이 표준 입력으로 받아 쓴다. 값은 화면, 로그, 결과지에 나오지 않는다
SECRETS_FILE = STATE / "secrets.json"


def secret(name: str) -> str:
    """비밀값 하나. 환경 변수, 비밀값 파일 순이다. 부를 때마다 파일을 읽어 저장 직후에도 새 값을 쓴다."""
    value = os.environ.get(name, "").strip()
    if value:
        return value
    try:
        raw = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(raw.get(name) or "").strip() if isinstance(raw, dict) else ""


def secret_source(name: str) -> str:
    """비밀값의 출처. 환경 변수, 비밀값 파일, 없음 가운데 하나다."""
    if os.environ.get(name, "").strip():
        return "환경 변수"
    return "비밀값 파일" if secret(name) else "없음"


SLACK_WEBHOOK = secret("JIPSA_SLACK_WEBHOOK")  # 시작 때 값. 보내는 쪽은 notify.slack이 부를 때마다 secret()으로 다시 읽는다
CONCURRENCY = int(_env("JIPSA_CONCURRENCY", "3"))
WEB_PORT_DEFAULT = 8765  # 운영 대시보드 포트. 이 값이 아니면 시험 포트로 보고 운영 폴더 보호가 든다
WEB_PORT = int(_env("JIPSA_WEB_PORT", str(WEB_PORT_DEFAULT)))  # jipsa web의 기본 포트. --port가 앞선다

_h, _m = _env("JIPSA_CUTOFF", "06:30").split(":")
CUTOFF = time(int(_h), int(_m))

# 종류별 총 상한과 구간 상한(분).
DEFAULT_TOTAL_MIN = {"code": 90, "doc": 30, "experiment": 180, "hardware": 90, "game": 90}
DEFAULT_SEGMENT_MIN = {"code": 30, "doc": 15, "experiment": 60, "hardware": 30, "game": 30}
LIMIT_SHOW_RATIO = 0.8  # 걸린 분이 상한의 이 비율 이상일 때만 상한을 같이 보인다(261029-jipsa-22 1안). web/app.js의 dur도 같은 값이다


def time_text(used, limit) -> str:
    """화면과 마감 출력의 시간 글자. 걸린 분만 보이다가 상한의 80% 이상이면 "48분/60분", 상한을 넘기면 "75분, 상한 60분 넘김"이다."""
    used, limit = int(used or 0), int(limit or 0)
    if limit and used > limit:
        return f"{used}분, 상한 {limit}분 넘김"
    if limit and used >= limit * LIMIT_SHOW_RATIO:
        return f"{used}분/{limit}분"
    return f"{used}분"

# runs/ 보관 기한(일). jipsa prune이 쓰고 명령 인자로 바꿀 수 있다.
ARCHIVE = RUNS / "archive"
RETAIN_RUN_DAYS = int(_env("JIPSA_RETAIN_RUN_DAYS", "30"))  # 실행 기록을 월별 묶음으로 옮기기까지
RETAIN_OTHER_DAYS = int(_env("JIPSA_RETAIN_OTHER_DAYS", "14"))  # 세션 기록과 일회성 폴더를 묶음으로 옮기기까지
RETAIN_ARCHIVE_DAYS = int(_env("JIPSA_RETAIN_ARCHIVE_DAYS", "180"))  # 묶음을 지우기까지

# runs/ 중간 산출물 정리(261028-jipsa-10). jipsa runs-clean이 쓰고 명령 인자로 바꿀 수 있다.
# 끝난 작업의 브라우저 프로필, 임시 DB 사본, 원응답 로그 같은 중간 파일을 보고서가 가리키지 않으면 휴지통 폴더로 옮긴다. 지우지 않는다.
# 종류 이름은 scheduler/runsclean.py의 KINDS 열쇠다. 쉼표로 고른다
RUNS_CLEAN_ON = _env("JIPSA_RUNS_CLEAN_ON", "0") == "1"  # 스케줄러가 하루 한 번 스스로 옮길지. 기본 꺼짐이다
RUNS_CLEAN_DAYS = int(_env("JIPSA_RUNS_CLEAN_DAYS", "3"))  # 작업의 마지막 활동에서 이 일수가 지나야 옮긴다
RUNS_CLEAN_KINDS = [k.strip() for k in _env("JIPSA_RUNS_CLEAN_KINDS", "브라우저 프로필,임시 DB 사본,작업 폴더,중간 파일,원응답 로그").split(",") if k.strip()]
RUNS_CLEAN_TRASH = _env("JIPSA_RUNS_CLEAN_TRASH", (Path.home() / "jipsa-trash" / "runs-{date}").as_posix())  # {date}는 옮긴 날짜(YYYYMMDD)다
RUNS_CLEAN_MIN_MB = float(_env("JIPSA_RUNS_CLEAN_MIN_MB", "1"))  # 이보다 작은 항목은 두고 넘어간다
RUNS_CLEAN_KEEP = [k.strip() for k in _env("JIPSA_RUNS_CLEAN_KEEP", "").split(",") if k.strip()]  # 늘 지키는 이름 위에 더 지킬 파일과 폴더 이름 패턴(*.wav 같은 글롭)
RUNS_CLEAN_ANSWER_DAYS =int(_env("JIPSA_RUNS_CLEAN_ANSWER_DAYS", "7"))  # 사람이 이 일수 안에 답한 작업은 사람 결정으로 남긴다

# 사람 답이 필요한 실행의 상태 값. 261022-jipsa-50 전 기록은 판단 대기로 적혀 있어 읽을 때 새 값으로 맞춘다.
# 확인하지 않은 완료와 실패(confirm.pending, 옛 이름 확인 전 완료)도 화면과 jipsa status에서 확인 필요로 보이지만 상태 값이 아니다.
# 상태 값으로 세는 곳(Auto 종료, cycle, 큐, 선행, 보고 절)은 이 값만 본다
HOLD = "확인 필요"
OLD_HOLD = "판단 대기"


def norm_status(value):
    """옛 상태 값 판단 대기를 확인 필요로 바꾼다. 나머지 값은 그대로다."""
    return HOLD if value in (OLD_HOLD, "판단대기") else value


def norm_record(data):
    """meta, result, 큐 줄, 이벤트 같은 기록 한 건의 상태 값을 맞춘다. 시도 목록의 상태도 맞춘다. 파일은 고쳐 쓰지 않는다."""
    if isinstance(data, dict):
        if "status" in data:
            data["status"] = norm_status(data["status"])
        for a in data.get("attempts") or []:
            if isinstance(a, dict) and "status" in a:
                a["status"] = norm_status(a["status"])
    return data


TICK_SEC = 30  # 스케줄러 확인 주기
RESOURCE_WAIT_MAX_MIN = 120  # 이 시간 넘게 못 얻으면 건너뜀(5절)
# 동시 실행과 GPU 장부(261026-jipsa-26)
WAKE_SEC = 1  # 요청 목록과 할 일 파일이 바뀌었는지 보는 간격. 바뀌면 30초 주기를 기다리지 않고 한 바퀴를 돈다. 2초 안에 시작하도록 1초로 둔다
AUTO_CAP = int(_env("JIPSA_AUTO_CAP", "6"))  # 사람 없이 이어지는 Auto 줄과 Cycle 새 단계를 합친 동시 상한. 사람이 시킨 단발 Do는 세지 않는다
GPU_RESERVE_MIN = 10  # Cycle 단계가 끝나면 그 단계가 쓰던 GPU 몫을 다음 단계를 위해 잡아 두는 시간
GPU_JUMP_MIN = 30  # 대기열 맨 앞이 이만큼 기다리기 전에는 빈 자리에 드는 작은 줄이 먼저 시작할 수 있다
GPU_OVER_HOLD_MIN = 10  # 실측이 장부보다 커 장부를 올린 뒤 새 GPU 작업을 멈추는 시간
# 실측 기반 예약(261029-jipsa-07, 261029-jipsa-04 2안). 시작 판정은 요구량으로 하고, 관찰 시간이 지나면 그동안의 실측 최댓값에 여유를 더해 센다
GPU_OBSERVE_MIN = int(_env("JIPSA_GPU_OBSERVE_MIN", "10"))  # 작업 시작 뒤 요구량으로 세는 관찰 시간
GPU_SIGNAL_MIN = int(_env("JIPSA_GPU_SIGNAL_MIN", "5"))  # 큰 GPU 일 신호 뒤 지난 최댓값으로 세며 새 GPU 작업을 들이지 않는 관찰 시간
GPU_PAD_GB = float(_env("JIPSA_GPU_PAD_GB", "1.0"))  # 관찰 실측 최댓값에 더하는 여유
# RAM 예약(261029-jipsa-17, GPU와 같은 방식): 시작 때는 요구량(한도 칸 RAM, 지난 실측 최댓값, 기본값 순)으로 잡고,
# 관찰 시간이 지나면 그동안의 프로세스 트리 실측 최댓값 + 여유로 고친다. 남은 RAM이 모자라면 대기열에 선다
RAM_OBSERVE_MIN = int(_env("JIPSA_RAM_OBSERVE_MIN", "5"))
RAM_PAD_GB = float(_env("JIPSA_RAM_PAD_GB", "1.0"))
RAM_DEFAULT_GB = float(_env("JIPSA_RAM_DEFAULT_GB", "2.0"))  # 한도 칸도 지난 실측도 없을 때의 시작 요구량
MORNING_AT = _env("JIPSA_MORNING_AT", "07:30")  # 밤 사이 끝난 Cycle 모음 Slack 글을 보내는 시각(하루 한 번)
DO_SESSION_GRACE_SEC = 120  # 세션 받은편지함에 넣은 Do를 이 안에 받지 않으면 스케줄러 작업자로 넘긴다
NO_PROGRESS_LIMIT = 2  # 연속 진전 없음 구간 수(2.5)
JUDGE_TIMEOUT_SEC = 180
CODEX_TIMEOUT_SEC = 900
SEARCH_TIMEOUT_SEC = 900

# 서칭 순서(2.2). 로컬 자료 폴더를 먼저 보고 웹을 본다.
# JIPSA_SEARCH_SOURCES에 `이름=경로;이름=경로`로 준다. 비어 있으면 로컬 자료 없이 웹만 본다
def _search_sources(text: str) -> list[tuple[str, Path]]:
    out = []
    for part in text.split(";"):
        label, sep, path = part.partition("=")
        if sep and label.strip() and path.strip():
            out.append((label.strip(), Path(path.strip()).expanduser()))
    return out


SEARCH_SOURCES = _search_sources(_env("JIPSA_SEARCH_SOURCES", ""))

_SECRET_PATTERNS = [
    re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"xox[abpr]-[A-Za-z0-9-]{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{12,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*['\"]?[A-Za-z0-9._-]{8,}"),
]


def redact(text: str) -> str:
    """밖으로 나가는 문자열에서 비밀값을 가린다."""
    if not text:
        return text
    out = text
    for value in (SLACK_WEBHOOK, secret("JIPSA_SLACK_WEBHOOK")):
        if value and len(value) > 8:
            out = out.replace(value, "[가림]")
    for pat in _SECRET_PATTERNS:
        out = pat.sub("[가림]", out)
    return out


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def parse_iso(text: str) -> datetime:
    return datetime.fromisoformat(text)


def parse_hhmm(text: str) -> time:
    h, m = text.strip().split(":")
    return time(int(h), int(m))


def next_cutoff(after: datetime, at: time | None = None) -> datetime:
    """`after` 뒤에 처음 오는 종료 시각. `at`이 없으면 기본 종료 시각."""
    candidate = datetime.combine(after.date(), at or CUTOFF)
    if candidate <= after:
        candidate += timedelta(days=1)
    return candidate


def ensure_dirs() -> None:
    for d in (RUNS, WORKTREES, STATE, CLI_CWD, SETTINGS_DIR, REPORTS, PROJECTS):
        d.mkdir(parents=True, exist_ok=True)


# ----- 운영 폴더 보호(261023-jipsa-08) -----
# 서브에이전트가 시험하며 원본 폴더에서 수집과 실행을 돌려 운영 상태 폴더를 쓴 일이 있었다(261023-jipsa-01).
# 운영 폴더는 원본 저장소의 상태, 실행 기록, 보고 폴더다. 할 일 파일은 상태 폴더 안이다. worktree에서 돌면 상태 폴더는 그 worktree 안이라 운영과 다르다.
MAIN_ROOT = ROOT.parent.parent if ROOT.parent.name == "worktrees" else ROOT
# 프로젝트 전용 규칙(261102-jipsa-50 사용자 답). git과 공개판에서 빠지는 파일이라 worktree에는 없어 원본 기준으로 읽는다. 없으면 조용히 넘어간다
LOCAL_RULES_FILE = Path(os.environ["JIPSA_LOCAL_RULES"]) if os.environ.get("JIPSA_LOCAL_RULES") else MAIN_ROOT / "docs" / "local" / "rules.md"
LIVE_DIRS = {"상태": MAIN_ROOT / "runtime" / "state", "실행 기록": MAIN_ROOT / "runs", "보고": MAIN_ROOT / "reports"}
AGENT_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CODEX_SANDBOX", "CODEX_THREAD_ID")  # 에이전트 셸에서 돈다는 표시


def _same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def live_guard(what: str) -> tuple[str, list[str]]:
    """운영 폴더를 쓰는 실행을 막을지. (막는 이유, 경고 문장들)이다. 막지 않으면 이유가 빈 문자열이다.

    - 에이전트 셸(Claude Code, Codex)에서 운영 상태 폴더로 스케줄러 루프, 모의 실행, 수집 바로 돌리기, 다른 포트의 대시보드를 띄우면 막는다.
      시험이면 JIPSA_STATE_DIR, JIPSA_RUNS_DIR, JIPSA_REPORTS_DIR를 임시 폴더로 준다.
      운영으로 돌릴 것이 맞으면 JIPSA_LIVE=1을 준다. 대시보드 감시가 띄우는 스케줄러는 이 값을 받는다.
    - 상태 폴더만 시험 폴더이고 나머지가 운영 폴더면 막지 않고 경고한다. 시험 결과가 운영 실행 기록과 보고에 섞인다.
    """
    used = {"상태": STATE, "실행 기록": RUNS, "보고": REPORTS}
    live = [k for k, p in used.items() if _same(p, LIVE_DIRS[k])]
    warns = []
    if "상태" not in live and live:
        warns.append(f"상태 폴더는 시험 폴더인데 {', '.join(live)} 폴더는 운영 폴더다. 시험이면 JIPSA_RUNS_DIR, JIPSA_REPORTS_DIR도 임시 폴더로 준다")
    agent = any(os.environ.get(k) for k in AGENT_ENV)
    if "상태" in live and agent and os.environ.get("JIPSA_LIVE", "").strip() != "1":
        return (f"에이전트 셸에서 운영 상태 폴더로 {what}를 돌리려 했다. 시험이면 JIPSA_STATE_DIR 등 시험용 폴더 환경 변수를 주고, "
                "운영으로 돌릴 것이 맞으면 JIPSA_LIVE=1을 준다"), warns
    return "", warns


def display_project(name) -> str:
    """화면과 보고에 보이는 프로젝트 이름. 등록부 misc는 등록부 프로젝트에 속하지 않는 일이고 화면에서는 기타다."""
    return "기타" if name == "misc" else str(name or "")
