"""Claude 사용 창 기록. 화면과 보고의 표시에만 쓴다. 비율로 새 시작을 막는 규칙은 없앴다(261102-jipsa-50).

jipsa는 Claude 호출의 사용률을 직접 재지 않는다. 실제 원천은 둘이다.
- 상태줄 입력: Claude Code가 상태줄 명령에 넘기는 JSON의 rate_limits 칸(5시간 창, 주간 창의 used_percentage).
  `jipsa claude-usage record`가 표준 입력으로 받아 상태 폴더의 claude_usage.json에 남긴다. 상태줄 명령 앞에 끼우면 된다.
  jipsa 폴더의 세션은 프로젝트 설정의 상태줄 감싸기(tools/statusline.py)가 남기고 ccstatusline 출력을 그대로 찍는다(261023-jipsa-42).
- ccstatusline 캐시: 사용자의 상태줄(ccstatusline)이 계정 사용량을 읽어 남기는 usage.json의 sessionUsage(5시간 창)와 weeklyUsage(주간 창),
  초기화 시각 sessionResetAt과 weeklyResetAt.
  파일 수정 시각을 기록 시각으로 본다. 읽기만 한다.
  ccstatusline은 상태줄 입력에 rate_limits가 있으면 API를 부르지 않아 이 파일을 다시 쓰지 않는다. 그래서 감싸기가 없으면 값이 오래된 측정으로 남는다.
둘 가운데 기록 시각이 늦은 것을 쓴다. 기록이 STALE보다 오래되면 값을 비우고 글자에 기록 시각을 붙인다. 자리를 비운 사이 세션이 닫혀 상태줄이 돌지 않으면 그렇다.
표시의 주 값은 5시간 창이고 주간 창은 글자에 덧붙인다.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scheduler.config import STATE, now, parse_iso, setting

STATE_FILE = STATE / "claude_usage.json"
CACHE_FILE = Path(setting("JIPSA_CLAUDE_USAGE_CACHE", str(Path.home() / ".cache" / "ccstatusline" / "usage.json")))
STALE = timedelta(minutes=int(setting("JIPSA_CLAUDE_USAGE_STALE", "30")))
NONE_TEXT = "Claude 5시간 창 측정 없음"


def _pct(v) -> float | None:
    try:
        return round(float(v), 1) if v is not None and str(v).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _when(v) -> datetime | None:
    """초기화 시각. 에포크 초나 ISO 글자를 받아 지역 시각(시간대 없음)으로 돌려준다. 모르면 None이다."""
    if v is None or str(v).strip() == "":
        return None
    try:
        if isinstance(v, (int, float)) or str(v).replace(".", "", 1).isdigit():
            return datetime.fromtimestamp(float(v), tz=timezone.utc).astimezone().replace(tzinfo=None)
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return t.astimezone().replace(tzinfo=None) if t.tzinfo else t
    except (TypeError, ValueError, OSError):
        return None


def record(five: float | None, week: float | None, source: str, at: datetime | None = None, five_reset=None, week_reset=None) -> dict:
    """사용률 한 번을 상태 폴더에 남긴다. five_reset, week_reset은 5시간 창과 주간 창의 초기화 시각이고 모르면 비운다."""
    reset, wreset = _when(five_reset), _when(week_reset)
    rec = {"five": _pct(five), "week": _pct(week), "seen": (at or now()).isoformat(timespec="seconds"), "source": source,
           "five_reset": reset.isoformat(timespec="seconds") if reset else "",
           "week_reset": wreset.isoformat(timespec="seconds") if wreset else ""}
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    return rec


def record_statusline(payload: dict, at: datetime | None = None) -> dict | None:
    """상태줄 입력 JSON의 rate_limits 칸을 남긴다. 칸이 없으면 아무것도 쓰지 않고 None이다."""
    rl = payload.get("rate_limits") if isinstance(payload, dict) else None
    if not isinstance(rl, dict):
        return None
    fh = rl.get("five_hour") if isinstance(rl.get("five_hour"), dict) else {}
    five = fh.get("used_percentage")
    sd = rl.get("seven_day") if isinstance(rl.get("seven_day"), dict) else {}
    week = sd.get("used_percentage")
    if _pct(five) is None and _pct(week) is None:
        return None
    return record(five, week, "상태줄", at, five_reset=fh.get("resets_at"), week_reset=sd.get("resets_at"))


def _from_state() -> dict | None:
    try:
        rec = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return {**rec, "seen": parse_iso(rec["seen"]), "five_reset": _when(rec.get("five_reset")), "week_reset": _when(rec.get("week_reset"))}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _from_cache() -> dict | None:
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        seen = datetime.fromtimestamp(CACHE_FILE.stat().st_mtime, tz=timezone.utc).astimezone().replace(tzinfo=None)
    except (OSError, ValueError):
        return None
    five, week = _pct(data.get("sessionUsage")), _pct(data.get("weeklyUsage"))
    if five is None and week is None:
        return None
    return {"five": five, "week": week, "seen": seen, "source": "ccstatusline", "five_reset": _when(data.get("sessionResetAt")),
            "week_reset": _when(data.get("weeklyResetAt"))}


def env_text(five: float | None, week: float | None, reset: datetime | None, cleared: bool, seen: datetime | None, fresh: bool,
             week_cleared: bool = False) -> str:
    """환경 줄 글자. Codex 창 글자와 같은 꼴이다. `Claude 5시간 창 사용 41%, 13:20 초기화, 주간 55%`이고
    초기화 시각이 지났으면 `Claude 5시간 창 초기화됨(13:20)`, 기록이 오래되면 끝에 기록 시각을 붙인다."""
    if five is None:
        text = NONE_TEXT
    elif cleared:
        text = f"Claude 5시간 창 초기화됨({reset:%H:%M})"
    else:
        text = f"Claude 5시간 창 사용 {five:g}%" + (f", {reset:%H:%M} 초기화" if reset else "")
    if week is not None:
        text += ", 주간 초기화됨" if week_cleared else f", 주간 {week:g}%"
    if seen and not fresh:
        text += f" ({seen:%m-%d %H:%M} 기록)"
    return text


def usage(at: datetime | None = None) -> dict:
    """지금 Claude 창. `{pct, five, week, five_reset, week_reset, cleared, week_cleared, seen, source, fresh, text}`.

    pct는 표시 값이고 5시간 창이다. 초기화 시각이 지났으면 0이고, 쓸 기록이 없거나 오래되면 None이다. 주간 값은 week로 따로 준다.
    week는 기록 값 그대로이고 주간 초기화 시각이 지났으면 week_cleared가 참이다. 두 초기화 시각은 화면 막대가 남은 시간을 셀 때 쓴다."""
    at = at or now()
    recs = [r for r in (_from_state(), _from_cache()) if r]
    if not recs:
        return {"pct": None, "five": None, "week": None, "five_reset": "", "week_reset": "", "reset_at": "", "cleared": False, "week_cleared": False,
                "seen": None, "source": "", "fresh": False, "text": NONE_TEXT}
    rec = max(recs, key=lambda r: r["seen"])
    seen = rec["seen"].replace(tzinfo=None) if rec["seen"].tzinfo else rec["seen"]
    fresh = at - seen <= STALE
    five, week, reset = rec.get("five"), rec.get("week"), rec.get("five_reset")
    cleared = five is not None and reset is not None and reset <= at
    wreset = rec.get("week_reset")
    week_cleared = week is not None and wreset is not None and wreset <= at
    pct = None if five is None or not fresh else (0.0 if cleared else five)
    return {"pct": pct, "five": five, "week": week, "five_reset": reset.isoformat(timespec="seconds") if reset else "",
            "week_reset": wreset.isoformat(timespec="seconds") if wreset else "", "week_cleared": week_cleared,
            "reset_at": f"{reset:%H:%M}" if reset else "", "cleared": cleared, "seen": seen.isoformat(timespec="minutes"),
            "source": rec["source"], "fresh": fresh, "text": env_text(five, week, reset, cleared, seen, fresh, week_cleared)}
