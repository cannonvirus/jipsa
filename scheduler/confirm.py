"""결과지 확인 상태. 끝난 작업은 확인 필요, 확인됨 둘 중 하나로 보인다(261022-jipsa-22). 확인을 미루던 생각 중은 없앴다(261029-jipsa-40).

상태는 jipsa 상태 폴더의 confirm.json 하나에 둔다. 폰과 PC가 같은 대시보드 서버를 보므로 같은 상태를 본다.
확인은 그때의 마감 시각을 같이 적는다. 이어 돌리기로 마감 시각이 바뀐 실행은 새 결과이므로 다시 확인 필요가 된다.
since보다 먼저 끝난 실행은 확인된 것으로 본다. 브라우저에 있던 읽음 기록을 처음 옮길 때 그 브라우저의 기준 시각을 받는다.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime

from scheduler.config import STATE, now_iso

PATH = STATE / "confirm.json"
_lock = threading.Lock()


def _load() -> dict:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("since", None)
    data.setdefault("acked", {})
    data.pop("thinking", None)  # 없앤 생각 중의 옛 칸. 읽지 않고 다음 저장 때 지운다(261029-jipsa-40)
    data.setdefault("auto", {})  # 자동 확인한 실행ID -> 사유와 시각(261023-jipsa-33)
    return data


def _save(data: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, PATH)


def view() -> dict:
    """화면에 주는 상태. 실행ID별 확인 마감 시각이다."""
    with _lock:
        return _load()


def _finished(run_id: str) -> str:
    from scheduler.record import meta_of  # record가 이 모듈을 부르므로 늦게 부른다

    return str((meta_of(run_id) or {}).get("finished") or "")


HUMAN_EXECUTORS = ("worker", "subagent", "session", "manual")  # 큐 줄이나 사람의 답으로 이어지는 실행. 나머지(수집 멈춤 등)는 스케줄러가 큐 밖에서 만든 결과지다


def _scheduler_sheet(meta: dict) -> bool:
    """스케줄러가 큐 밖에서 만든 결과지인지. 답을 받아 이어 돌릴 큐 줄이 없으므로 답 없이 확인하면 추천안대로 두고 완료로 닫는다(261023-jipsa-09)."""
    return bool(meta.get("collect_stop")) or meta.get("executor", "subagent") not in HUMAN_EXECUTORS


def _flip(run_id: str, to_done: bool) -> None:
    """확인한 실패를 완료로 바꾸고, 되돌리면 실패로 돌린다. 사유와 요약은 그대로 두고 원래 상태와 확인 시각만 적는다(261022-jipsa-25).
    스케줄러가 큐 밖에서 만든 확인 필요 결과지도 확인하면 완료로 바꾸고 되돌리면 확인 필요로 돌린다.

    기록과 큐 줄을 함께 바꾸므로 타임라인, 표, 필터, 보고 집계, 사이클의 재시도 판단이 모두 같은 상태를 본다. Slack 정정은 보내지 않는다.
    """
    from scheduler import queue, record  # record가 이 모듈을 부르므로 늦게 부른다

    meta = record.meta_of(run_id)
    if not meta:
        return
    if to_done and meta.get("status") == "실패":
        meta.update(status="완료", confirmed_from="실패", confirmed_at=now_iso())
    elif to_done and meta.get("status") == "확인 필요" and _scheduler_sheet(meta):
        meta.update(status="완료", confirmed_from="확인 필요", confirmed_at=now_iso())
    elif not to_done and meta.get("confirmed_from") and meta.get("status") == "완료":
        meta.update(status=meta["confirmed_from"])
        meta.pop("confirmed_from", None)
        meta.pop("confirmed_at", None)
    else:
        return
    record.write_json(record.RUNS / run_id / "meta.json", meta)
    row = queue.by_run(run_id) or (queue.get(meta["queue_key"]) if meta.get("queue_key") else None)
    if row:
        queue.update(row["key"], run_id=run_id, status=queue.DONE if to_done else queue.HOLD if meta["status"] == "확인 필요" else queue.FAILED)
    record.write_sheet(run_id)
    try:
        from scheduler import report

        report.write(meta.get("report_date") or now_iso()[:10])
    except OSError:
        pass


HOLD = "확인 필요"  # 상태 값. 사람의 답이나 확인을 기다린다
ACKED = "확인함"  # 상태 값 확인 필요를 답 없이 확인한 실행의 보이는 상태. 상태 값과 큐 보류는 그대로다


def _is_acked(data: dict, run_id: str, finished: str) -> bool:
    """그 마감 시각으로 확인 기록에 있는지."""
    return data["acked"].get(run_id) == finished


def _before_since(data: dict, finished: str) -> bool:
    """기준 시각 전에 끝났는지. 브라우저 읽음 기록을 옮기기 전의 실행은 확인된 것으로 본다."""
    try:
        since = datetime.fromisoformat(str(data["since"]).replace("Z", "+00:00")).astimezone().replace(tzinfo=None) if data["since"] else None
        return bool(since and finished and datetime.fromisoformat(finished) <= since)
    except ValueError:
        return False


def confirmed(run_id: str, finished: str) -> bool:
    """사람이 확인한 실행인지. 화면의 판정과 같다. 그 마감 시각으로 확인했거나 기준 시각 전에 끝났으면 확인된 것이다."""
    with _lock:
        data = _load()
    return _is_acked(data, run_id, finished) or _before_since(data, finished)


def closed(run_id: str, finished: str) -> bool:
    """사람이 답 없이 확인해 답 칸을 닫은 실행인지. jipsa가 cycle 진행으로 자동 확인한 실행은 사람이 닫은 것이 아니므로
    선택지나 정할 것이 있으면 그대로 답을 받는다(261025-jipsa-04)."""
    with _lock:
        data = _load()
    auto = data["auto"].get(run_id)
    if auto and auto.get("finished") == finished and data["acked"].get(run_id) == finished:
        return False
    return _is_acked(data, run_id, finished) or _before_since(data, finished)


def pending(meta: dict) -> bool:
    """끝난(완료, 실패) 실행이 확인 필요로 보이는지. 화면의 판정(ackState의 cue)와 같다.
    옛 이름 확인 전 완료도 이것이다(261023-jipsa-26). 기준 시각 뒤에 끝났고 확인하지 않았으면 확인 필요, 확인했으면 완료다. 기록은 고쳐 쓰지 않는다."""
    run_id, fin = str(meta.get("run_id") or ""), str(meta.get("finished") or "")
    if meta.get("status") not in ("완료", "실패") or not fin or run_id.startswith("session-"):
        return False
    with _lock:
        since = _load()["since"]
    return bool(since) and not confirmed(run_id, fin)


def acked(run_id: str, finished: str) -> bool:
    """그 마감 시각으로 확인 단추를 누른 실행인지. 기준 시각은 보지 않는다. 상태 값 확인 필요는 기준 시각 전에 끝났어도 답이나 확인을 기다린다."""
    with _lock:
        data = _load()
    return _is_acked(data, run_id, finished)


def shown(meta: dict, data: dict | None = None) -> str:
    """보이는 상태 하나. jipsa status의 확인 필요 목록, 대시보드 서버의 확인 필요 큐, 보고, cycle 종합 보고 줄이 모두 이 값을 쓴다.
    화면의 ackState도 같은 규칙이다(261025-jipsa-04). 상태 값 확인 필요는 답 없이 확인했으면 확인함, 아니면 확인 필요다.
    완료와 실패는 기준 시각 뒤에 끝났고 확인하지 않았으면 확인 필요, 아니면 상태 값이다.
    세션 기록(session-)과 진행 중은 상태 값 그대로다. data는 미리 읽은 확인 기록이다. 실행 여럿을 돌 때 한 번만 읽어 넘긴다."""
    st, run_id, fin = meta.get("status"), str(meta.get("run_id") or ""), str(meta.get("finished") or "")
    if run_id.startswith("session-") or st not in (HOLD, "완료", "실패"):
        return st
    if data is None:
        with _lock:
            data = _load()
    if st == HOLD:
        return ACKED if _is_acked(data, run_id, fin) else HOLD
    if not fin or not data["since"] or _is_acked(data, run_id, fin) or _before_since(data, fin):
        return st
    return HOLD


def ack(run_id: str, finished: str | None = None) -> dict:
    """확인. 확인 필요에서 빼서 보통 완료로 보이게 한다. 실패였다면 완료로 바꾼다."""
    fin = finished if finished is not None else _finished(run_id)
    _flip(run_id, True)
    with _lock:
        data = _load()
        data["acked"][run_id] = fin
        _save(data)
        return data


def auto(run_ids: list[str], why: str) -> list[str]:
    """jipsa가 사람 대신 확인한다. Cycle이 다음 단계로 넘어간 단계 실행에 쓴다(261023-jipsa-33).
    acked에 넣고 auto 칸에 사유를 남긴다. 상태 값은 바꾸지 않아 실패는 실패로 남는다. 이미 확인했거나
    한 번 자동 확인한 실행은 건드리지 않는다. 사람이 확인 필요로 되돌린 것은 그대로 남는다. 새로 확인한 실행ID 목록이다."""
    fins = {r: _finished(r) for r in dict.fromkeys(run_ids) if r}
    with _lock:
        data = _load()
        done = []
        for r, fin in fins.items():
            if not fin or r in data["auto"] or data["acked"].get(r) == fin:
                continue
            data["acked"][r] = fin
            data["auto"][r] = {"why": why, "at": now_iso(), "finished": fin}
            done.append(r)
        if done:
            _save(data)
    return done


def reset(run_id: str) -> dict:
    """확인 필요로 되돌린다. 실패를 확인해 완료로 바꿨다면 다시 실패로 돌린다."""
    _flip(run_id, False)
    with _lock:
        data = _load()
        data["acked"].pop(run_id, None)
        _save(data)
        return data


def migrate(read: list[str], since: str | None) -> dict:
    """브라우저 저장소의 읽음 기록을 확인으로 옮긴다. 기준 시각은 처음 옮길 때만 정하고 뒤에 오는 브라우저는 읽음만 더한다."""
    fins = {r: _finished(r) for r in read if isinstance(r, str) and r}
    with _lock:
        data = _load()
        if not data["since"]:
            data["since"] = since or now_iso()
        for r, fin in fins.items():
            data["acked"].setdefault(r, fin)
        _save(data)
        return data


def act(body: dict) -> dict:
    """대시보드의 확인 요청. action은 ack, reset, migrate다."""
    action, run_id = str(body.get("action", "")), str(body.get("run_id", ""))
    if action == "migrate":
        return {"ok": True, "confirm": migrate(list(body.get("read") or []), body.get("since") or None)}
    if not run_id:
        return {"ok": False, "why": "실행ID가 없다"}
    if action not in ("ack", "reset"):
        return {"ok": False, "why": f"모르는 요청: {action}"}
    from scheduler import events  # 누가 언제 확인했는지 남긴다. 답 없이 확인한 실행이 확인 필요로 보이던 원인을 찾을 때 이 기록이 없었다(261025-jipsa-04)

    events.emit("confirm", run=run_id, action=action, by="web")
    if action == "ack":
        return {"ok": True, "confirm": ack(run_id)}
    return {"ok": True, "confirm": reset(run_id)}
