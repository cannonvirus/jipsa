"""사람 입력의 '초안'을 가른다(261029-jipsa-35). hook이 빨리 들이도록 표준 라이브러리만 쓴다.

규칙: 사람 입력의 '초안'은 대시보드 결과지의 '초안 보기'다.
결과지 초안은 실행 폴더 안의 HTML 파일이고 result.json의 preview_url이 그 경로를 가리켜야 단추가 뜬다.
사람 입력(UserPromptSubmit)과 결과지 답(hook 전달, 답 대기 명령)에서 초안 요청을 찾아 세션 기록 meta의 draft_ask에 남기고,
begin이 그 요청을 읽어 실행에 초안 표시를 하고, finish가 미리보기 주소가 빈 초안 실행의 마감을 막는다.
"""

from __future__ import annotations

import re
from datetime import datetime

DRAFT_WORD = re.compile(r"초안")
WINDOW_MIN = 30  # 이 시간 안에 받은 요청만 begin이 쓴다. 지난 요청이 상관없는 작업에 붙지 않게 한다

SHEET = "sheet"  # 결과지 초안 보기

SHEET_NOTE = ("[jipsa] 입력의 '초안'은 대시보드 결과지의 '초안 보기'다. "
              "그 일의 프로젝트로 jipsa begin에 --draft를 붙여 열고, 서브에이전트가 실행 폴더 안에 HTML 초안을 만들어 result.json preview_url에 그 경로를 적게 한다. "
              "초안과 상관없는 일이면 begin에 --no-draft를 붙인다.")


def kind(text: str) -> str:
    """글에 '초안'이 있으면 sheet다. 없으면 빈 글이다."""
    return SHEET if text and DRAFT_WORD.search(text) else ""


# 할 일 줄의 초안 판정(261103-jipsa-07). 초안 기능이나 파일 이름을 말하는 자리는 요청으로 세지 않는다.
# '초안 보기 고쳐 줘'는 기능 수정이고 '초안 보기로 보여 줘'는 요청이라 조사 로, 에가 붙은 꼴은 빼지 않는다
_FEATURE = re.compile(r"초안\s*(?:보기|단추|버튼|표식|기능|판정|인식|검사|마감|주소|경로|실행|요청)(?![로에으])")
_FILE_NAME = re.compile(r"[\w./\\-]*초안[\w./\\-]*\.[A-Za-z0-9]+|초안_\w+")

# 있는 초안을 읽거나 요약하는 말은 새 초안 요청이 아니다. 놓치면 주소 검사만 빠지고, 잘못 잡으면 확인 필요로 멈추므로 이쪽으로 좁힌다
_READING = re.compile(r"(?:지난|기존|이전|앞선|만든|받은|옛)\s*초안|초안(?:을|의|에서)?\s*(?:읽|요약|검토|분석|비교|참고)")


def line_wants(project: str, text: str, criteria: str = "") -> bool:
    """Do로 시킨 단발 줄이 결과지 초안을 바라는지. begin --draft와 같게 처리할 줄이다."""
    rest = _READING.sub(" ", _FILE_NAME.sub(" ", _FEATURE.sub(" ", f"{text} {criteria}")))
    return kind(rest) == SHEET


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(timespec="seconds")


def remember(meta: dict, text: str, via: str) -> str:
    """초안 요청이면 세션 기록 meta에 draft_ask로 남기고 종류를 돌려준다. 요청이 아니면 meta를 건드리지 않는다."""
    k = kind(text)
    if k:
        meta["draft_ask"] = {"kind": k, "text": " ".join(text.split())[:200], "ts": now_iso(), "via": via, "used_by": ""}
    return k


def from_answers(rows: list[dict]) -> tuple[str, str]:
    """결과지 답 줄들에서 마지막 초안 요청의 (종류, 원문)을 찾는다. 답 글만 보고 실행 제목은 보지 않는다."""
    found = ("", "")
    for r in rows:
        text = str(r.get("answer") or "")
        if kind(text):
            found = (kind(text), text)
    return found


def note(k: str) -> str:
    """세션에 붙일 안내 줄. 결과지 초안일 때만 있다."""
    return SHEET_NOTE if k == SHEET else ""


def pending(meta: dict | None, at: datetime | None = None) -> dict | None:
    """begin이 쓸 초안 요청. 아직 실행에 쓰지 않았고 WINDOW_MIN 안에 받은 것만이다."""
    ask = (meta or {}).get("draft_ask")
    if not isinstance(ask, dict) or ask.get("used_by") or ask.get("kind") != SHEET:
        return None
    try:
        age = ((at or datetime.now()) - datetime.fromisoformat(str(ask.get("ts")))).total_seconds() / 60
    except (TypeError, ValueError):
        return None
    return ask if 0 <= age <= WINDOW_MIN else None
