"""운영 모드. 261029-jipsa-17(1안)에서 Auto 모드를 없앴다. 모드 파일에 옛 값 auto, cycle, unattended가 남아 있어도 유인(attended)으로 읽는다.
Cycle은 시킬 때 시작과 마감을 정하고(scheduler/auto.py 시키기), 동시 실행 수와 자원은 모드와 무관하게 스케줄러가 나눈다.
AUTO 값과 cutoff_for는 시키기 한 건의 마감을 셈하는 데만 쓴다(auto.run_mode). 아래는 옛 설명이다.

Auto 모드 안의 실행 단위는 모두 목표이고 목표마다 Cycle로 돈다(261023-jipsa-39). Auto 마감 하나로 멈춘다.
261023-jipsa-39에서 잠시 Cycle 모드라 불렀다가 261023-jipsa-40(사용자 답)에서 Auto로 되돌렸다. 시간대와 무관하게 낮에도 켠다.
옛 모드 값 cycle도 auto로 읽는다. 옛 jipsa mode 명령은 261026-jipsa-07에서 뗐고 켜고 끄기는 jipsa auto on, off다.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta

from scheduler.config import STATE, next_cutoff, now, now_iso, parse_hhmm, parse_iso, setting

MODE_FILE = STATE / "mode.json"
ATTENDED = "attended"
AUTO = "auto"
UNATTENDED = AUTO  # 옛 이름
AUTO_HOURS = float(setting("JIPSA_AUTO_HOURS", "8"))  # 마감을 정하지 않고 켰을 때 켠 뒤 이만큼(시간)이 Auto 마감이다
_SPAN = re.compile(r"^\+?\s*(\d+(?:\.\d+)?)\s*(h|시간|m|분)$", re.I)


def parse_span(text: str) -> timedelta | None:
    """`+4h`, `3시간`, `90m`, `90분` 꼴의 길이. 아니면 None이다."""
    m = _SPAN.match(str(text or "").strip())
    if not m:
        return None
    n = float(m.group(1))
    return timedelta(hours=n) if m.group(2).lower() in ("h", "시간") else timedelta(minutes=n)
_ALIASES = {"auto": AUTO, "cycle": AUTO, "unattended": AUTO, "attended": ATTENDED}
_READ = {"auto": ATTENDED, "cycle": ATTENDED, "unattended": ATTENDED, "attended": ATTENDED}  # 모드 파일 읽기. Auto 모드는 없다


def get() -> dict:
    try:
        data = json.loads(MODE_FILE.read_text(encoding="utf-8"))
        if data.get("mode") in _READ:
            if data["mode"] != ATTENDED:
                data["old_mode"] = data["mode"]  # 옛 Auto 모드가 켜진 채 남은 파일이다. 켜진 것으로 보지 않는다
            data["mode"] = _READ[data["mode"]]
            return data
    except (OSError, ValueError):
        pass
    return {"mode": ATTENDED, "since": now_iso(), "morning_sent": None}


def set_mode(mode: str, until: str | None = None) -> dict:
    mode = _ALIASES.get(mode)
    if mode is None:
        raise ValueError(mode)
    data = {"mode": mode, "since": now_iso(), "morning_sent": None}
    if until and mode == AUTO:
        if parse_span(until) is None:
            parse_hhmm(until)  # HH:MM도 길이(+4h, 90m)도 아니면 ValueError
        data["until"] = until.strip()
    prev = get()
    MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    MODE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    _log_switch(prev, data)
    return data


def _log_switch(prev: dict, data: dict) -> None:
    """모드 전환 값을 사건 기록에 한 줄로 남긴다. 모드 파일은 덮어쓰므로 지난 종료 시각과 목표 수는 여기서만 확인된다(261023-jipsa-01 버그 6)."""
    from scheduler import events

    row = {"to": data["mode"], "since": data["since"], "prev_mode": prev.get("mode"), "prev_since": prev.get("since"),
           "prev_until": prev.get("until") or "", "until": data.get("until") or ""}
    try:
        if data["mode"] == AUTO:
            row["cutoff"] = cutoff_for(data).isoformat(timespec="minutes")
        elif prev.get("mode") == AUTO:
            row["prev_cutoff"] = cutoff_for(prev).isoformat(timespec="minutes")
            row["morning_sent"] = prev.get("morning_sent")
        from scheduler import todo  # 목표 수는 할 일 파일 Auto 절 줄 수다. 옛 범위 계약 셈은 261025-jipsa-42에서 뗐다

        rows, _, _ = todo.load()
        autos = [it for it in rows if it.section == todo.AUTO]
        row.update(goals=len(autos), goals_cycle=sum(1 for it in autos if it.cycle))
    except (OSError, ValueError, KeyError) as e:
        row["error"] = str(e)[:120]
    events.emit("mode_switch", **row)


def save(data: dict) -> None:
    MODE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def is_unattended() -> bool:
    return get()["mode"] == UNATTENDED


def cutoff_for(data: dict | None = None) -> datetime:
    """Auto 마감. 전환 시각 뒤 처음 오는 지정 시각(until)이나 켠 뒤 시간(+4h)이다. 없으면 Auto는 켠 뒤 AUTO_HOURS 시간,
    유인 모드는 하루 경계(06:30)다. 옛 범위 절 시각은 261025-jipsa-42에서 뗐다."""
    data = data or get()
    since = parse_iso(data["since"])
    span = parse_span(data.get("until") or "")
    if span is not None:
        return since + span
    until = data.get("until")
    if until:
        return next_cutoff(since, parse_hhmm(until))
    # 정한 마감이 없으면 켠 뒤 AUTO_HOURS 시간이다. 시간대와 무관하게 낮에도 켤 수 있다(261023-jipsa-40). 유인 모드의 보고 날짜는 하루 경계(06:30)를 쓴다
    return since + timedelta(hours=AUTO_HOURS) if data.get("mode") == AUTO else next_cutoff(since)


def past_cutoff(data: dict | None = None) -> bool:
    data = data or get()
    return data["mode"] == UNATTENDED and now() >= cutoff_for(data)


def report_date(start: datetime, unattended: bool) -> str:
    """보고 파일의 날짜. Auto 모드에서 그날의 종료 시각 뒤에 시작한 작업은 다음 종료 시각의 날짜 파일에 들어간다."""
    cut = cutoff_for() if unattended else next_cutoff(start)
    if unattended and cut.date() != start.date():
        return cut.date().isoformat()
    return start.date().isoformat()
