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
