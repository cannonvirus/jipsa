"""기록 계층. 실행 주체가 무엇이든 같은 기록을 남긴다.

jipsa는 대시보드다. 스케줄러 작업자, 세션 서브에이전트, 손으로 들여온 기록이 모두 runs/<실행ID>/에
meta.json, attempt-N/result.json, result.md(결과지)를 남기고, 끝날 때 그날 보고를 다시 만든다.
확인 필요와 실패는 결과지 요약 세 줄을 담은 Slack 글 하나를 모드와 스케줄러 실행 여부와 무관하게 바로 보낸다. 완료는 바로 보내지 않는다(261025-jipsa-20).
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path

from notify import slack
from scheduler import confirm, draftask, events, modes, queue, report, workitem
from scheduler.config import HOLD, RUNS, STATE, norm_record, norm_status, now, now_iso, parse_iso
from scheduler.registry import Project

EXECUTORS = {"worker": "스케줄러 작업자", "subagent": "세션 서브에이전트", "session": "세션", "manual": "손으로 들여옴", "collect": "자동 수집"}
STATUS_ALL = ("완료", "실패", HOLD)
_counter_lock = threading.Lock()


# ----- 파일 -----
def new_run_id(project_name: str, stamp: datetime | None = None) -> str:
    """YYMMDD-프로젝트-NN. 같은 날 같은 프로젝트의 번호가 이어진다."""
    day = (stamp or now()).strftime("%y%m%d")
    with _counter_lock:
        existing = [p.name for p in RUNS.glob(f"{day}-{project_name}-*")]
        n = 1 + max([int(x.rsplit("-", 1)[-1]) for x in existing if x.rsplit("-", 1)[-1].isdigit()] or [0])
        run_id = f"{day}-{project_name}-{n:02d}"
        (RUNS / run_id).mkdir(parents=True, exist_ok=True)
    return run_id


def read_json(path: Path) -> dict | None:
    """기록 파일을 읽는다. 옛 기록의 상태 값 판단 대기는 확인 필요로 맞춰 돌려준다(파일은 그대로다)."""
    try:
        return norm_record(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def meta_of(run_id: str) -> dict | None:
    return read_json(RUNS / run_id / "meta.json")


def attempt_dirs(run_id: str) -> list[Path]:
    out = [p for p in (RUNS / run_id).glob("attempt-*") if p.is_dir() and p.name[8:].isdigit()]
    return sorted(out, key=lambda p: int(p.name[8:]))


def _minutes(a: datetime, b: datetime) -> int:
    return max(0, int((b - a).total_seconds() // 60))


# ----- 시작 -----
def begin(project: Project, title: str, criteria: str, *, executor: str, est_minutes: int | None = None,
          started: datetime | None = None, model: str = "", run_id: str | None = None, parent: str = "",
          category: str = "", pick: bool | None = None, match_budget: dict | None = None) -> dict:
    """큐 줄을 만들고 runs/<실행ID>/meta.json을 쓴다. started가 없으면 지금이고 run_start 이벤트도 남긴다.

    parent는 이 일이 나온 같은 프로젝트의 일 이름이다. meta의 parent_item으로 남는다.
    category와 pick은 세션이 정한 작업 종류와 고를 것 표시다. 종류가 없으면 낱말 규칙으로 추정하고 category_guess가 참이다.
    주간 계획 파일에는 줄을 더하지 않는다(261025-jipsa-36 세션 시작, 261025-jipsa-42 기록 들여오기와 나머지). 큐 줄의 file은 빈 글자다.
    match_budget은 판 수로 계산한 상한 근거다(matchcap.budget). 있으면 그 상한이 est_minutes를 대신하고 meta에 근거와 새 판 마감 시각이 남는다.
    """
    live = started is None
    started = started or now()
    if match_budget:
        est_minutes = match_budget["limit_minutes"]
    unattended = modes.is_unattended()
    item = _loose_item(project.name, title, criteria, est_minutes, category, pick)
    entry = queue.add(item, project)
    run_id = run_id or new_run_id(project.name, started)
    limit = est_minutes or project.total_minutes
    queue.update(entry["key"], status=queue.RUNNING, run_id=run_id, started=started.isoformat(timespec="seconds"), executor=executor)
    meta = {
        "run_id": run_id, "project": project.name, "title": title, "criteria": criteria, "kind": project.kind,
        "executor": executor, "model": model, "started": started.isoformat(timespec="seconds"),
        "report_date": modes.report_date(started, unattended), "status": "진행 중", "minutes_limit": limit, "minutes_used": 0,
        "attempts": [], "dry_run": False, "mode": modes.get()["mode"], "queue_key": entry["key"],
        "category": item.category, "pick": item.pick, "category_guess": item.guessed, "updated": now_iso(),
    }
    if parent:
        meta["parent_item"] = f"{project.name}::{parent}"
    if match_budget:
        from scheduler import matchcap

        meta["match_budget"] = {**match_budget, "stop_new_at": matchcap.stop_at(started, match_budget), "text": matchcap.short_text(match_budget)}
    write_json(RUNS / run_id / "meta.json", meta)
    (RUNS / run_id / "attempt-1").mkdir(parents=True, exist_ok=True)
    if live:
        events.emit("run_start", run=run_id, project=project.name, title=title, project_kind=project.kind, limit=limit, executor=executor)
    return meta


def _loose_item(project: str, title: str, criteria: str, est_minutes: int | None, category: str, pick: bool | None) -> workitem.Item:
    """큐 줄의 바탕 항목. 종류가 없으면 낱말 규칙으로 추정한다. 큐 줄의 file은 빈 글자다."""
    guessed = category not in workitem.CATEGORIES
    if guessed:
        category, rule_pick = workitem.guess_category(title, criteria)
        pick = rule_pick if pick is None else pick
    return workitem.Item(project=project, title=title, criteria=criteria, est_minutes=est_minutes, file=Path(""), line=-1, marker=None,
                        checked=False, category=category, pick=bool(pick), guessed=guessed)


# ----- 끝 -----
def evidence_ref(run_id: str, result: dict) -> str:
    if result.get("commit"):
        return f"커밋 {result['commit']}"
    if result.get("changed_files"):
        return f"바뀐 파일 {len(result['changed_files'])}개"
    return f"runs/{run_id}"


class ResultMissing(Exception):
    """마감에 쓸 result.json이 없거나 문법이 깨졌거나 status가 비어 있다. 기록은 진행 중 그대로 둔다."""


def result_problem(run_id: str) -> str:
    """마지막 attempt의 result.json을 마감에 쓸 수 있는지 본다. 쓸 수 있으면 빈 문자열, 아니면 이유 한 문장."""
    dirs = attempt_dirs(run_id)
    path = (dirs[-1] if dirs else RUNS / run_id / "attempt-1") / "result.json"
    if not path.exists():
        return "결과 파일이 없다"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        # 셸 heredoc으로 쓴 Windows 경로는 역슬래시가 하나로 줄어 Invalid \escape가 나기 쉽다
        return f"결과 파일 문법이 깨졌다({str(e)[:60]}). 경로의 역슬래시를 확인한다"
    if not isinstance(data, dict) or norm_status(data.get("status")) not in STATUS_ALL:
        return "결과 파일의 status가 비어 있거나 완료, 실패, 확인 필요가 아니다"
    return ""


def draft_problem(run_id: str) -> str:
    """초안 실행(meta의 draft)이 결과지 '초안 보기'를 띄울 수 있는지 본다. 되면 빈 문자열, 아니면 이유 한 문장(261029-jipsa-35).

    result.json의 preview_url이 비었거나, 로컬 파일을 가리키는데 그 파일이 없으면 문제다. http 주소는 그대로 받는다.
    """
    meta = meta_of(run_id) or {}
    if not meta.get("draft"):
        return ""
    dirs = attempt_dirs(run_id)
    res = read_json((dirs[-1] if dirs else RUNS / run_id / "attempt-1") / "result.json") or {}
    url = str(res.get("preview_url") or "").strip()
    if url.lower().startswith(("http://", "https://")):
        return ""
    if url:
        path = Path(re.sub(r"^file:/*", "", url, flags=re.I))
        if path.is_file():
            return ""
        return f"초안 실행인데 result.json preview_url이 가리키는 파일이 없다({url[:80]})"
    found = sorted(p for p in (RUNS / run_id).rglob("*.html") if "figures" not in p.parts)[:5]
    where = (("실행 폴더의 HTML: " + ", ".join(p.as_posix() for p in found) + " 가운데 사람이 볼 것을 적는다") if found
             else "실행 폴더에 HTML 초안이 없다. 초안을 만든 뒤 그 경로를 적는다")
    return f"초안 실행인데 result.json preview_url이 비었다. 결과지 '초안 보기' 단추가 뜨지 않는다. {where}"


def finish(run_id: str, *, status: str | None = None, result: dict | None = None, finished: datetime | None = None,
           notify: bool = True, require: bool = False) -> dict:
    """작업자 밖에서 끝난 실행을 마감한다. result.json을 읽거나 받은 result를 쓰고, 큐를 갱신하고, close를 부른다.

    require면 status를 따로 받지 않은 한 result.json이 온전해야 한다. 아니면 아무것도 쓰지 않고 ResultMissing을 낸다.
    """
    meta = meta_of(run_id)
    if not meta:
        raise FileNotFoundError(f"runs/{run_id}/meta.json이 없다")
    if require and not status:
        why = result_problem(run_id)
        if why:
            raise ResultMissing(why)
    live = finished is None
    finished = finished or now()
    dirs = attempt_dirs(run_id)
    att_dir = dirs[-1] if dirs else RUNS / run_id / "attempt-1"
    n = int(att_dir.name[8:])
    saved = read_json(att_dir / "result.json") or {}
    result = norm_record({**saved, **(result or {})})
    if status:
        result["status"] = norm_status(status)
    if result.get("status") not in STATUS_ALL:
        result["status"] = "실패"
        result.setdefault("reason", "result.json이 없거나 status가 비어 있다")
    result.setdefault("summary", result.get("reason", ""))
    for key in ("changed_files", "evidence", "options", "added_packages"):
        result.setdefault(key, [])
    for key in ("commit", "reason", "rule", "preview_url"):
        result.setdefault(key, "")
    if not result["options"]:  # 선택지가 비면 보고서 정할 것 번호 목록의 고를 안으로 채우고 자동 채움 표시를 남긴다(261022-jipsa-45 다안)
        auto = alt_options(decision_items(run_id))
        if auto:
            result["options"], result["options_auto"] = auto, True
    started = parse_iso(meta["started"])
    result["minutes"] = result.get("minutes") or _minutes(started, finished)
    write_json(att_dir / "result.json", result)

    attempts = [a for a in meta.get("attempts", []) if a.get("n") != n]
    attempts.append({"n": n, "status": result["status"], "category": result.get("category", ""), "cause": "해당 없음",
                     "minutes": result["minutes"], "issues": None, "sources": None})
    meta.pop("confirmed_from", None)  # 다시 마감하면 새 결과다. 확인으로 바꾼 표시는 지운다
    meta.pop("confirmed_at", None)
    meta.update(
        status=result["status"], finished=finished.isoformat(timespec="seconds"), summary=str(result["summary"])[:200],
        evidence_ref=evidence_ref(run_id, result), minutes_used=_minutes(started, finished), rule=result["rule"],
        options=result["options"], added_packages=result["added_packages"], reason=result["reason"], attempts=attempts,
        label=str(result.get("label") or "")[:20], preview_url=str(result.get("preview_url") or ""),
        options_auto=bool(result.get("options_auto")), updated=now_iso(),
    )
    write_json(RUNS / run_id / "meta.json", meta)

    q_status = {"완료": queue.DONE, "실패": queue.FAILED, HOLD: queue.HOLD}[result["status"]]
    row = queue.by_run(run_id) or (queue.get(meta["queue_key"]) if meta.get("queue_key") else None)
    if row:
        queue.update(row["key"], status=q_status, run_id=run_id, finished=meta["finished"], reason=meta["summary"], answer=None)
    if live:
        events.emit("run_end", run=run_id, status=result["status"], minutes=meta["minutes_used"], evidence=meta["evidence_ref"])
        events.move_run(run_id)
    from scheduler import resources

    resources.release(run_id)  # 세션 실행이 begin에서 잡은 GPU 장부 줄을 돌려준다(261026-jipsa-26). 없으면 아무 일도 없다
    close(meta, notify=notify)
    return meta


STALE_IDLE_MIN = 30  # 세션 실행 폴더에 이만큼 활동이 없고 마감되지 않았으면 남은 실행으로 본다. 옛 기준은 상한 + 15분이었다(261029-jipsa-22 1안)


def stale_session_runs(at: datetime | None = None) -> list[dict]:
    """세션이나 서브에이전트가 맡아 실행 중인 큐 줄 가운데 실행 폴더에 30분 동안 활동이 없고 마감되지 않은 것. 줄에 meta, 결과 문제, 무활동 분을 붙여 돌려준다.

    상한은 보지 않는다. 상한을 넘겨도 활동이 이어지면 닫지 않고, 상한 안이어도 결과 없이 30분 동안 활동이 없으면 닫는다.

    세션이 서브에이전트 끝에 jipsa finish를 부르지 않으면 줄이 실행 중으로 남아 범위 끝 판정과 원본 폴더 작업 시작을 막았다(261023-jipsa-01).
    범위 판정은 이 줄을 실행 중으로 세지 않고, 스케줄러 루프가 expire_stale_sessions로 닫는다.
    """
    at = at or now()
    out = []
    for r in queue.running():
        if not r.get("run_id") or not queue.session_owned(r) or r.get("executor") == "manual":
            continue
        meta = meta_of(r["run_id"]) or {}
        if meta.get("executor") == "manual" or meta.get("status") not in (None, "진행 중"):
            continue
        try:
            started = parse_iso(meta.get("started") or r.get("started"))
        except (TypeError, ValueError):
            continue
        idle = _minutes(run_activity(r["run_id"], started), at)
        if idle < STALE_IDLE_MIN:
            continue
        out.append({**r, "_meta": meta, "_problem": result_problem(r["run_id"]), "_idle": idle})
    return out


def expire_stale_sessions(at: datetime | None = None, notify: bool = False) -> list[dict]:
    """활동 없이 30분이 지난 세션 실행을 닫는다. 결과 파일이 온전하면 그 결과로 마감하고, 없으면 실패로 닫는다.
    Slack 글은 기본으로 보내지 않는다. 아침 보고와 화면에 실패로 남는다."""
    at = at or now()
    closed = []
    for r in stale_session_runs(at):
        run_id = r["run_id"]
        try:
            if not r["_problem"]:
                meta = finish(run_id, notify=notify)
            else:
                why = f"{r['_idle']}분 동안 활동이 없고 마감되지 않았다. {r['_problem']}. jipsa가 실패로 닫았다"
                meta = finish(run_id, status="실패", result={"reason": why, "summary": why, "written_by": "jipsa"}, notify=notify)
        except (OSError, FileNotFoundError, ValueError) as e:
            events.emit("error", where="expire_stale", run=run_id, error=str(e)[:200])
            continue
        events.emit("session_run_expired", run=run_id, status=meta.get("status"), why=r["_problem"] or "결과 있음")
        closed.append(meta)
    return closed


STALL_MIN = 15  # 세션 서브에이전트 실행 폴더에 이만큼 활동이 없으면 멈춤으로 본다. 자동 닫힘(무활동 30분)보다 먼저 알린다
STALL_RENOTIFY_MIN = 20  # 같은 실행에 멈춤을 다시 알리기 전 간격
STALL = STATE / "session_stall.json"  # 실행ID별 멈춤 기록. 스케줄러가 적고 wait-answer가 알림을 꺼내 받음 표시를 한다
_STALL_LOCK = STATE / "session_stall.lock"
_SCAN_DEPTH, _SCAN_MAX = 3, 400  # 실행 폴더 활동을 볼 때 내려가는 깊이와 보는 항목 수 상한


class _stall_lock:
    """멈춤 기록 파일을 스케줄러와 여러 wait-answer가 함께 고친다. 잠금 파일로 한 번에 하나만 고치게 한다. 10초 넘은 잠금은 버려진 것으로 본다."""

    def __enter__(self):
        import time

        _STALL_LOCK.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(40):
            try:
                os.close(os.open(_STALL_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if time.time() - _STALL_LOCK.stat().st_mtime > 10:
                        _STALL_LOCK.unlink()
                        continue
                except OSError:
                    pass
                time.sleep(0.05)
        return self  # 잠금을 못 얻어도 멈춤 감시로 다른 일을 막지 않는다

    def __exit__(self, *exc):
        try:
            _STALL_LOCK.unlink()
        except OSError:
            pass


def stall_load() -> dict:
    try:
        data = json.loads(STALL.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _stall_save(rows: dict) -> None:
    STALL.parent.mkdir(parents=True, exist_ok=True)
    tmp = STALL.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STALL)


def run_activity(run_id: str, started: datetime) -> datetime:
    """실행 폴더 아래 파일의 가장 최근 수정 시각과 시작 시각 중 늦은 것. meta.json은 jipsa가 고치므로 빼고, 깊이와 개수 상한 안에서만 본다."""
    latest = started.timestamp()
    seen = 0
    stack = [(RUNS / run_id, 0)]
    while stack and seen < _SCAN_MAX:
        folder, depth = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for e in entries:
            seen += 1
            if seen > _SCAN_MAX:
                break
            if depth == 0 and e.name == "meta.json":
                continue
            try:
                latest = max(latest, e.stat().st_mtime)
                if e.is_dir() and depth + 1 < _SCAN_DEPTH:
                    stack.append((Path(e.path), depth + 1))
            except OSError:
                continue
    return datetime.fromtimestamp(latest)


def _stall_targets() -> list[dict]:
    """세션이 begin한 서브에이전트 실행 가운데 진행 중인 것. 세션 id(parent_run)가 없거나 작업자, 세션 자신, 손으로 들여온 실행은 뺀다."""
    out = []
    for r in queue.running():
        if not r.get("run_id"):
            continue
        meta = meta_of(r["run_id"]) or {}
        if meta.get("executor") != "subagent" or meta.get("status") != "진행 중" or not str(meta.get("parent_run") or "").startswith("session-"):
            continue
        out.append(meta)
    return out


def watch_stalls(at: datetime | None = None) -> list[dict]:
    """멈춘 세션 서브에이전트 실행을 찾아 알림을 남긴다. 새로 알린 기록을 돌려준다.

    서브에이전트가 긴 계산을 백그라운드로 띄우고 차례를 끝내면 계산이 끝나도 스스로 깨어나지 못한다(한 실행은 76분 멈춰 자동 닫힘으로 실패).
    메시지를 받으면 깨어나므로, 띄운 세션의 wait-answer가 알림을 찍고 끝나 Main이 SendMessage로 깨우게 한다.
    활동이 다시 생기거나 실행이 끝나면 기록을 지운다.
    """
    at = at or now()
    fresh = []
    with _stall_lock():
        rows = stall_load()
        before = json.dumps(rows, sort_keys=True)
        live = set()
        for meta in _stall_targets():
            run_id = meta["run_id"]
            try:
                started = parse_iso(meta["started"])
            except (KeyError, TypeError, ValueError):
                continue
            live.add(run_id)
            last = run_activity(run_id, started)
            idle = _minutes(last, at)
            if idle < STALL_MIN:
                if rows.pop(run_id, None):
                    events.emit("session_stall_clear", run=run_id)
                continue
            row = rows.get(run_id) or {}
            row.update(session=meta["parent_run"], project=meta.get("project"), title=meta.get("title"), agent=meta.get("agent") or "",
                       last_activity=last.isoformat(timespec="seconds"), idle_min=idle, checked=at.isoformat(timespec="seconds"))
            due = not row.get("notified") or at >= parse_iso(row["notified"]) + timedelta(minutes=STALL_RENOTIFY_MIN)
            if due:
                row.update(notified=at.isoformat(timespec="seconds"), notified_idle=idle, delivered=None, delivered_to=None)
                events.emit("session_stall", run=run_id, session=meta["parent_run"], idle=idle)
                fresh.append({"run_id": run_id, **row})
            rows[run_id] = row
        for gone in [k for k in rows if k not in live]:  # 끝났거나 대상이 아니게 된 실행
            rows.pop(gone)
        if json.dumps(rows, sort_keys=True) != before:
            _stall_save(rows)
    return fresh


def stall_of(run_id: str, rows: dict | None = None) -> int:
    """대시보드와 jipsa status가 보일 멈춤 분. 멈춤이 아니면 0이다."""
    row = (stall_load() if rows is None else rows).get(run_id)
    return int(row.get("idle_min") or 0) if row else 0


def stall_take(session_run: str = "") -> list[dict]:
    """이 세션이 받을 멈춤 알림을 꺼내 받음 표시를 한다. 서브에이전트를 깨울 수 있는 것은 띄운 세션뿐이라 세션이 같아야 한다. 세션 id 없이 기다리면 모두 받는다."""
    if not STALL.exists():
        return []
    mine = []
    with _stall_lock():
        rows = stall_load()
        for run_id, r in rows.items():
            if not r.get("notified") or r.get("delivered"):
                continue
            if session_run and r.get("session") != session_run:
                continue
            r.update(delivered=now_iso(), delivered_to=session_run or "wait-answer")
            mine.append({"run_id": run_id, **r})
        if mine:
            _stall_save(rows)
    for r in mine:
        events.emit("session_stall_delivered", run=session_run or r["run_id"], stalled=r["run_id"])
    return mine


def stall_note(rows: list[dict]) -> str:
    """wait-answer가 찍는 멈춤 안내문."""
    lines = []
    for r in rows:
        who = f"{r['agent']}, {r.get('title')}" if r.get("agent") else str(r.get("title"))
        lines.append(f"[jipsa] 멈춤: {r['run_id']} ({who}) {r.get('notified_idle') or r.get('idle_min')}분 무활동. 서브에이전트에게 메시지를 보내 깨워라")
    return "\n".join(lines)


def reopen(run_id: str, *, notify: bool = True) -> dict:
    """잘못 마감한 기록을 attempt 폴더의 result.json으로 다시 마감한다. 마감 시각은 그대로 두고 상태, 요약, 결과지, 큐를 맞춘다.

    Slack은 바로잡은 상태가 확인 필요나 실패일 때만 요약 글을 머리 줄에 정정 표시를 붙여 보낸다. 완료로 바로잡으면 보내지 않는다.
    """
    meta = meta_of(run_id)
    if not meta:
        raise FileNotFoundError(f"runs/{run_id}/meta.json이 없다")
    if meta.get("status") == "진행 중":
        raise ValueError(f"{run_id}는 아직 진행 중이다. 다시 열기 대신 마감한다")
    why = result_problem(run_id)
    if why:
        raise ResultMissing(why)
    prev = meta.get("status", "")
    finished = parse_iso(meta["finished"]) if meta.get("finished") else now()
    meta = finish(run_id, finished=finished, notify=False, require=True)
    events.emit("reopen", run=run_id, was=prev, status=meta["status"])
    if notify and not report.card_skip(meta):  # 완료와 유인 모드 cycle의 중간 단계는 정정 글도 보내지 않는다(261024-jipsa-05)
        text = report.card(meta, note=f"정정, {prev}에서 바로잡음")
        events.emit("slack", run=run_id, kind_detail="reopen_card", result=slack.notify(text))
    return meta


INBOX =STATE / "session_inbox.jsonl"  # 세션이 하던 일에 들어온 답. hook이 세션에 넘기고, 못 넘기면 스케줄러가 작업자로 돌린다


def inbox_load() -> list[dict]:
    try:
        return [json.loads(l) for l in INBOX.read_text(encoding="utf-8").splitlines() if l.strip()]
    except (OSError, ValueError):
        return []


def inbox_save(rows: list[dict]) -> None:
    INBOX.parent.mkdir(parents=True, exist_ok=True)
    INBOX.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def inbox_add(meta: dict, text: str, picks: list[dict] | None = None) -> dict:
    row = {"ts": now_iso(), "run_id": meta["run_id"], "project": meta.get("project"), "title": meta.get("title"), "criteria": meta.get("criteria", ""),
           "answer": text, "parent_run": meta.get("parent_run"), "delivered": None, "delivered_to": None, "worker": None}
    # 답이 "1안, 나안, 추가 지시"처럼 안 이름으로 시작하면 묶음마다 고른 안의 내용을 같이 넘긴다
    got = picked_of(text, choices(meta)[0] if picks is None else picks)
    if got:
        row["picked"] = " / ".join(c["text"] for c in got)  # 옛 기록과 같은 글자 칸이다. 안이 여럿이면 빗금으로 잇는다
        row["picks"] = [c["name"] for c in got]  # 고른 안 이름 목록. 옛 기록에는 없고 picked 글자만 있다
    rows = inbox_load()
    rows.append(row)
    inbox_save(rows)
    return row


# ----- Do를 열린 세션으로(261026-jipsa-26) -----
# 답 대기 명령(wait-answer)이 몇 초마다 심장박동을 적는다. 15초 안에 적었고 그 프로세스가 살아 있으면 열린 세션으로 본다.
# 대시보드 Do와 jipsa todo run은 열린 세션이 있으면 할 일 줄을 받은편지함에 Do 요청(kind do)으로 넣고, 답 대기 명령이 안내를 찍고 끝나 세션을 깨운다.
# 세션이 2분 안에 받지 않으면 스케줄러가 작업자 요청으로 넘긴다(auto.do_fallback).
WAITERS = STATE / "session_waiters.json"
WAITER_FRESH_SEC = 15


def _waiters() -> dict:
    try:
        data = json.loads(WAITERS.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def waiter_beat(session_run: str, pid: int, gone: bool = False) -> None:
    """답 대기 명령의 심장박동. gone이면 지운다."""
    data = _waiters()
    key = session_run or f"pid-{pid}"
    if gone:
        data.pop(key, None)
    else:
        data[key] = {"pid": pid, "at": now_iso()}
    WAITERS.parent.mkdir(parents=True, exist_ok=True)
    tmp = WAITERS.with_suffix(f".{pid}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    try:
        os.replace(tmp, WAITERS)
    except OSError:
        pass


def _fresh_waiters() -> dict:
    """15초 안에 박동을 적었고 프로세스가 살아 있는 답 대기 명령. 키는 세션 기록 id, 값은 박동 시각이다."""
    import psutil

    out = {}
    for key, w in _waiters().items():
        try:
            at = parse_iso(w["at"])
        except (KeyError, TypeError, ValueError):
            continue
        if (now() - at).total_seconds() > WAITER_FRESH_SEC or not psutil.pid_exists(int(w.get("pid") or 0)):
            continue
        out[key] = at
    return out


def waiter_fresh(session_run: str) -> bool:
    """그 세션의 답 대기 명령이 지금 떠 있는지."""
    return session_run in _fresh_waiters()


def open_session() -> str:
    """답 대기 명령이 떠 있는 세션의 기록 id. 가장 최근에 심장박동을 적은 세션이고, 없으면 빈 값이다."""
    best, at_best = "", None
    for key, at in _fresh_waiters().items():
        if at_best is None or at > at_best:
            best, at_best = key, at
    return best


def do_add(item, session_run: str) -> dict:
    """할 일 줄 하나를 세션 받은편지함에 Do 요청으로 넣는다. run_id 칸은 do:<할 일 key>라 답 줄과 섞이지 않는다."""
    row = {"ts": now_iso(), "kind": "do", "run_id": f"do:{item.key}", "project": item.project, "title": item.text,
           "criteria": item.criteria or "", "todo_key": item.key, "todo_no": item.no, "line": item.line(), "answer": "",
           "parent_run": session_run, "delivered": None, "delivered_to": None, "worker": None}
    rows = inbox_load()
    rows.append(row)
    inbox_save(rows)
    events.emit("do_session", key=item.key, project=item.project, title=item.text, session=session_run)
    return row


def do_open(key: str) -> dict | None:
    """그 할 일 줄의 Do 요청이 세션에 가 있으면(아직 받지 않았거나, 받은 지 30분 안이고 begin으로 열지 않았으면) 그 줄이다."""
    for r in reversed(inbox_load()):
        if r.get("kind") != "do" or r.get("todo_key") != key or r.get("worker") or r.get("begun"):
            continue
        if not r.get("delivered"):
            return r
        if (now() - parse_iso(r["delivered"])).total_seconds() < 1800:
            return r
    return None


def do_begun(key: str, run_id: str) -> None:
    """begin --todo가 그 줄을 열었다. Do 요청에 실행ID를 적어 같은 줄 거절을 푼다."""
    rows = inbox_load()
    hit = False
    for r in rows:
        if r.get("kind") == "do" and r.get("todo_key") == key and not r.get("begun"):
            r["begun"] = run_id
            hit = True
    if hit:
        inbox_save(rows)


def do_stale(grace_sec: int) -> list[dict]:
    """세션이 grace_sec 안에 받지 않은 Do 요청. 작업자로 넘긴다고 표시하고 돌려준다."""
    rows = inbox_load()
    out = []
    for r in rows:
        if r.get("kind") == "do" and not r.get("delivered") and not r.get("worker") \
                and (now() - parse_iso(r["ts"])).total_seconds() >= grace_sec:
            r["worker"] = now_iso()
            out.append(r)
    if out:
        inbox_save(rows)
    return out


def _inbox_drop(run_id: str) -> bool:
    """물린 답이 아직 세션에 넘어가지 않았으면 받은편지함에서 뺀다. 이미 넘어간 답이 있었으면 참이다."""
    rows = inbox_load()
    keep = [r for r in rows if r["run_id"] != run_id or r.get("delivered") or r.get("worker")]
    if len(keep) != len(rows):
        inbox_save(keep)
    return any(r["run_id"] == run_id for r in keep)


def session_open(session_run: str) -> bool:
    """그 세션 기록이 아직 열려 있는지. SessionEnd hook이 기록을 완료로 닫으므로 상태가 진행 중이면 열린 것이다.
    기록이 없거나 끝났으면 닫힌 것이고, 그 세션 몫의 답을 붙들지 않는다(261031-jipsa-01). hook의 parent_open과 같은 규칙이다."""
    if not session_run:
        return False
    meta = read_json(RUNS / session_run / "meta.json")
    return bool(meta) and meta.get("status") == "진행 중"


def delivery_note(session_run: str = "") -> str:
    """답을 받은편지함에 넣은 뒤 어디로 가는지 알리는 한 줄. 답 대기 명령이 뜬 세션이 있으면 그 세션에 몇 초 안에 가고,
    없으면 다음 세션이 열릴 때(대기 명령이나 첫 입력) 전달된다. 08:58의 답이 세션 없이 받은편지함에만 남아 사람이 안 된 줄 알았다(261031-jipsa-01)."""
    other = open_session()
    if session_run and session_open(session_run):  # 부모 세션이 아직 열려 있으면 2분 동안 그 세션 몫이다(inbox_take, take_inbox와 같은 규칙)
        if waiter_fresh(session_run):
            return f"열린 세션 {session_run}에 몇 초 안에 전달된다."
        return (f"부모 세션 {session_run}이 일하는 중이라 그 세션의 턴 끝이나 다음 입력 때 전달된다."
                + (f" 2분 안에 받지 않으면 열린 세션 {other}가 받는다." if other and other != session_run else ""))
    if other:
        return f"열린 세션 {other}에 몇 초 안에 전달된다."
    return "지금 열린 세션이 없어 다음 세션이 열릴 때(jipsa 온이나 답 대기 명령) 전달된다. 답은 받은편지함에 남아 있다."


def inbox_take(session_run: str = "") -> list[dict]:
    """세션이 받을 답을 꺼내 받음 표시를 한다. hook의 take_inbox와 같은 규칙이다. 부모 세션이 열려 있으면 그 세션이 우선이고 2분이 지나면 어느 세션이든 받는다.
    부모 세션이 끝났으면 붙들지 않고 바로 받는다(261031-jipsa-01). 이미 받은 답(hook이 넘긴 것 포함)과 작업자로 넘어간 답은 다시 꺼내지 않는다."""
    rows = inbox_load()
    mine = []
    parents: dict[str, bool] = {}
    for r in rows:
        if r.get("delivered") or r.get("worker"):
            continue
        age = (now() - parse_iso(r["ts"])).total_seconds()
        parent = r.get("parent_run") or ""
        if session_run and parent and parent != session_run and age < 120:
            if parent not in parents:
                parents[parent] = session_open(parent)
            if parents[parent]:
                continue
        r["delivered"] = now_iso()
        r["delivered_to"] = session_run or "wait-answer"
        r["delivered_via"] = "wait"
        mine.append(r)
    if mine:
        INBOX.parent.mkdir(parents=True, exist_ok=True)
        tmp = INBOX.with_suffix(".wait.tmp")  # hook이 읽는 중에도 반쯤 쓰인 파일이 보이지 않게 바꿔치기한다
        tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        os.replace(tmp, INBOX)
        for r in mine:
            events.emit("inbox_delivered", run=session_run or r["run_id"], answered=r["run_id"], via="wait")
        remember_draft(session_run, mine)
    return mine


def remember_draft(session_run: str, rows: list[dict]) -> None:
    """답 대기 명령이 꺼낸 답에 '초안'이 있으면 그 세션 기록에 초안 요청을 남긴다. begin이 읽는다(261029-jipsa-35)."""
    k, text = draftask.from_answers(rows)
    if not k or not session_run:
        return
    meta = read_json(RUNS / session_run / "meta.json")
    if meta is None:
        return
    draftask.remember(meta, text, "answer")
    write_json(RUNS / session_run / "meta.json", meta)
    events.emit("draft_ask", run=session_run, draft=k, via="wait")


def inbox_note(rows: list[dict]) -> str:
    """세션에 넘길 안내문. hook이 넘기는 문구와 같다. Do 요청(kind do)은 따로 된 안내 줄이다(261026-jipsa-26)."""
    from scheduler import sessionproc

    lines = sessionproc.do_lines([r for r in rows if r.get("kind") == "do"])
    rows = [r for r in rows if r.get("kind") != "do"]
    if rows:
        lines.append("[jipsa] 대시보드 결과지에 답이 들어왔다. 이 답대로 이어서 처리하고, 결과를 jipsa 기록에 남긴다(새 작업이면 jipsa begin으로 시작, 끝나면 finish).")
    for r in rows:
        lines.append(f"- {r['run_id']} ({r.get('project')} / {r.get('title')}): 답 \"{r['answer']}\"" + (f" (고른 안: {r['picked']})" if r.get("picked") else "")
                     + f". 보고서는 runs/{r['run_id']}/attempt-1/report.md다.")
    line = draftask.note(draftask.from_answers(rows)[0])  # 답의 '초안'이 결과지 초안이면 안내 줄을 붙인다(261029-jipsa-35)
    if line:
        lines.append(line)
    return "\n".join(lines)


_DECIDE = re.compile(r"^##\s*(?:\d+\.\s*)?남은 일과 정할 것")


def decision_items(run_id: str) -> list[str]:
    """마지막 시도 보고서의 "남은 일과 정할 것" 절에 있는 번호 목록 항목. 사람이 고를 것이 남았다는 뜻이다."""
    dirs = attempt_dirs(run_id)
    text = read_text(dirs[-1] / "report.md") if dirs else None
    items, inside = [], False
    for line in (text or "").splitlines():
        if line.startswith("## "):
            inside = bool(_DECIDE.match(line))
        elif inside and re.match(r"^\d+[.)]\s", line):
            items.append(re.sub(r"^\d+[.)]\s+", "", line).strip())
    return items


_ALT = re.compile(r"^\s*(?:[(\[]추천[)\]]\s*|추천\s*[:.]?\s*)?([가나다라마바사아자]안|\d+\s?안|[A-Z]\s?안|안\s?\d+)(?=[\s.:,()]|$)")


def alt_name(text: str) -> str:
    """정할 것 한 항목이 서로 대체하는 고를 안(가안, 1안, A안, 안 1)이면 그 이름, 아니면 빈 문자열. 애매하면 안이 아니다."""
    m = _ALT.match(text.replace("**", ""))
    return re.sub(r"\s+", "", m.group(1)) if m else ""


def alt_options(items: list[str], limit: int = 300) -> list[str]:
    """보고서 정할 것 항목 중 고를 안만 고른다. 안이 둘 미만이거나 같은 이름이 되풀이되면(결정 여러 개가 묶인 보고서) 고르지 않는다.
    추천 표시가 붙은 안을 맨 앞으로 옮긴다. 나머지 항목은 단추가 아니라 서랍에 글자로 보인다."""
    alts = [t for t in items if alt_name(t)]
    names = [alt_name(t) for t in alts]
    if len(alts) < 2 or len(set(names)) != len(names):
        return []
    alts.sort(key=lambda t: "추천" not in t)
    return [(t.replace("**", "")[: limit - 1] + "…") if len(t) > limit else t.replace("**", "") for t in alts]


def alt_group(name: str) -> str:
    """안 이름의 묶음. 1안과 2안은 숫자, 가안과 나안은 가나다, A안과 B안은 영문이다. 한 결과지에 묶음이 둘이면 묶음마다 하나씩 고른다."""
    if re.match(r"^(?:\d|안\d)", name):
        return "숫자"
    return "가나다" if re.match(r"^[가-힣]안", name) else "영문"


_PARTICLE = re.compile(r"(?:\(추천\)|으로|로|을|를|과|와|이|만|도)$")


def picked_of(text: str, picks: list[dict]) -> list[dict]:
    """답 머리에 적힌 안 이름을 모두 읽는다. "1안, 나안, 추가 지시"면 1안과 나안이고, 안 이름이 아닌 낱말이 나오면 거기서 멈춘다.
    "2안으로"처럼 조사가 붙은 이름도 읽는다. 같은 안을 두 번 적으면 한 번만 센다."""
    by = {c["name"]: c for c in picks}
    out: list[dict] = []
    for tok in re.split(r"[,\s]+", text.strip()):
        if tok == "(추천)":
            continue
        name = tok if tok in by else _PARTICLE.sub("", tok)
        if name not in by:
            break
        if by[name] not in out:
            out.append(by[name])
    return out


def option_names(options: list[str]) -> list[str]:
    """선택 단추 이름. 안 이름이 적혀 있으면 그것을, 없으면 놓인 순서로 1안, 2안이다."""
    return [alt_name(o) or f"{i + 1}안" for i, o in enumerate(options)]


def choices(meta: dict) -> tuple[list[dict], list[str]]:
    """서랍의 선택 단추(이름과 안 내용)와 단추 없이 글자로 보일 정할 것.

    선택지에 안 이름(가안, 1안)이 있으면 이름 있는 것만 단추이고 나머지 선택지와 보고서의 안 아닌 항목은 글자다.
    이름이 없으면 확인 필요일 때만 선택지 전부를 놓인 순서로 1안, 2안 단추로 둔다(규칙에 걸린 실행의 선택지).
    끝난 실행의 이름 없는 선택지는 서로 다른 결정이 섞이기 쉬우므로 단추 없이 글자로 둔다.
    선택지가 없으면 보고서 정할 것을 모두 글자로 두고 직접 적는 칸만 쓴다. 같은 안 이름이 되풀이되면 단추를 만들지 않는다.
    """
    clean = lambda t: str(t).replace("**", "").strip()
    opts = [clean(o) for o in meta.get("options") or [] if clean(o)]
    items = [clean(t) for t in decision_items(meta.get("run_id") or "")]
    named = [o for o in opts if alt_name(o)]
    names = [alt_name(o) for o in named]
    if named and len(set(names)) == len(names):
        # 보고서가 "다안을 채택한다"처럼 안을 다시 적은 항목은 단추와 겹치므로 뺀다
        again = lambda t: any(n in re.sub(r"^[(\[]추천[)\]]\s*", "", t)[:15] for n in names)
        notes = [o for o in opts if not alt_name(o)] + [t for t in items if not alt_name(t) and not again(t)]
        return [{"name": n, "text": o, "group": alt_group(n)} for n, o in zip(names, named)], list(dict.fromkeys(notes))
    if opts and not named and meta.get("status") == "확인 필요":
        return [{"name": n, "text": o, "group": alt_group(n)} for n, o in zip(option_names(opts), opts)], []
    return [], list(dict.fromkeys(items or opts))  # 보고서 항목이 추천까지 담아 더 자세하다. 없으면 선택지를 글자로 둔다


ACK_WORDS = ("확인", "확인함", "ok", "OK")  # 끝난 실행에 이 답만 넣으면 답을 남기지 않고 확인만 한다


def answerable(meta: dict) -> bool:
    """결과지에 답 넣기 칸을 열지. 확인 필요는 지금처럼 열고(작업자 실행은 큐 보류일 때만),
    완료와 실패는 아직 답이 없고 확인 필요로 보이면(확인 전) 연다. 확인한 뒤에도 선택지나 보고서 정할 것이 있으면 연다.
    끝난 실행의 답은 받은편지함으로만 가고 다시 돌리지 않는다. 답을 넣으면 확인한 것이라 완료가 된다(261023-jipsa-26)."""
    st, run_id = meta.get("status"), meta.get("run_id") or ""
    if st == "확인 필요":
        if confirm.acked(run_id, str(meta.get("finished") or "")):  # 답 없이 확인을 누르면 답 칸을 닫는다. 상태 값과 큐 보류는 그대로다
            return False
        row = queue.by_run(run_id)
        return bool(row and row["status"] == queue.HOLD) or meta.get("executor", "worker") != "worker"
    if st in ("완료", "실패") and not meta.get("answer") and not run_id.startswith("session-"):
        if confirm.pending(meta):  # 확인 필요로 보이는 끝난 실행은 고를 것이 없어도 답 칸으로 확인한다
            return True
        if confirm.closed(run_id, str(meta.get("finished") or "")):  # 사람이 답 없이 확인한 실행은 답 칸을 열지 않는다. cycle 진행의 자동 확인은 닫은 것이 아니다
            return False
        return bool(meta.get("options")) or bool(decision_items(run_id))
    return False


def _answer_after(meta: dict, text: str, *, close: bool) -> dict:
    """끝난(완료, 실패) 실행에 답을 적는다. 상태, 마감 시각, 큐, 계획 표시는 그대로 두고 답만 기록과 받은편지함에 넣는다.
    상태 값 확인 필요의 집계와 Auto 모드 확인 필요 상한은 상태를 보므로 바뀌지 않는다."""
    run_id = meta["run_id"]
    meta.update(answer=text, answered_at=now_iso(), answered_after=meta["status"], updated=now_iso())
    write_json(RUNS / run_id / "meta.json", meta)
    dirs = attempt_dirs(run_id)
    if dirs:
        res = read_json(dirs[-1] / "result.json") or {}
        res["answer"] = text
        write_json(dirs[-1] / "result.json", res)
    events.emit("answer", run=run_id, answer=text[:120], resume=False, closed=close, after=meta["status"])
    note = ""
    if not close:
        inbox_add(meta, text)
        note = delivery_note(str(meta.get("parent_run") or ""))
    write_sheet(run_id)
    confirm.ack(run_id, str(meta.get("finished") or ""))  # 답을 넣으면 확인한 것이다
    try:
        report.write(meta.get("report_date") or now().date().isoformat())
    except OSError:
        pass
    return {"ok": True, "resume": False, "after": True, **({"delivery": note} if note else {})}


def answer(run_id: str, text: str, *, close: bool = False) -> dict:
    """확인 필요에 답을 넣는다. 스케줄러 작업자 실행은 큐로 돌려 이어 돌리고, 세션과 서브에이전트 실행은 답을 기록에 적고 완료로 닫는다.

    close면 작업자 실행도 이어 돌리지 않고 완료로 닫는다. 답을 이미 다른 실행이 처리했을 때 쓴다. 큐에서 답을 받아 처리 대기인 실행도 닫을 수 있고,
    세션 받은편지함에 넣지 않으므로 Auto 모드에서 작업자로 다시 돌지 않는다.
    완료와 실패 실행도 선택지나 정할 것이 있으면 받는다. 주체와 무관하게 다시 돌리지 않고 받은편지함으로 세션에 넘긴다.
    """
    meta = meta_of(run_id)
    if not meta:
        return {"ok": False, "why": "기록이 없는 실행ID"}
    if meta.get("status") in ("완료", "실패"):
        if meta.get("answer"):
            return {"ok": False, "why": "이미 답이 들어갔다. 바꾸려면 --undo로 물린 뒤 다시 넣는다"}
        if confirm.closed(run_id, str(meta.get("finished") or "")):  # cycle 진행으로 자동 확인한 실행은 닫힌 것이 아니라 답을 받는다(261025-jipsa-04)
            return {"ok": False, "why": "사람이 답 없이 확인해 닫은 실행이다. 결과지의 '확인 필요로 되돌리기'를 누른 뒤 넣는다"}
        if not answerable(meta):
            return {"ok": False, "why": f"고를 것이 없다 (지금 {meta.get('status')}, 선택지와 정할 것 없음)"}
        if text.strip() in ACK_WORDS and not meta.get("options") and not decision_items(run_id):
            confirm.ack(run_id, str(meta.get("finished") or ""))  # 고를 것 없는 확인 필요 결과의 "확인" 답은 확인 단추와 같다. 실패면 완료로 바뀐다
            return {"ok": True, "resume": False, "after": True, "acked": True}
        return _answer_after(meta, text, close=close)
    if meta.get("status") != "확인 필요":
        return {"ok": False, "why": f"확인 필요나 끝난 실행이 아니다 (지금 {meta.get('status')})"}
    row = queue.by_run(run_id)
    # 답을 넣어도 확인이 같이 적히므로 큐에 답이 들어간 작업자 실행은 닫기를 받는다
    if confirm.acked(run_id, str(meta.get("finished") or "")) and not (row and row.get("answer")):
        return {"ok": False, "why": "답 없이 확인한 실행이다(확인함). 결과지의 '확인 필요로 되돌리기'를 누른 뒤 넣는다"}
    if meta.get("executor", "worker") == "worker" and meta.get("cycle_step") == "목표 정하기":
        close = True  # 작업자 목표 정하기의 답은 카드 확인이다. 다시 돌리지 않고 닫으면 다음 걸음에 cycle이 박는다(261024-jipsa-13)
    if meta.get("todo_plan"):
        close = True  # 기준 정하기(기획 단계)의 답은 기준이다. 다시 돌리지 않고 닫고 할 일 줄의 기준 칸에 적는다(261025-jipsa-24)
    if meta.get("executor", "worker") == "worker" and not close:
        if not row:
            return {"ok": False, "why": "큐에 없는 실행ID"}
        queue.update(row["key"], status=queue.PENDING, run_id=run_id, answer=text, reason="답을 받아 이어 돌린다")
        events.emit("answer", run=run_id, answer=text[:120], resume=True)
        confirm.ack(run_id, str(meta.get("finished") or ""))  # 답을 넣으면 확인한 것이다. 이어 돌린 결과는 마감 시각이 바뀌어 다시 확인 필요가 된다
        return {"ok": True, "resume": True}
    picks = choices(meta)[0]  # 완료로 닫기 전의 단추. 확인 필요의 1안, 2안은 닫은 뒤에는 단추가 아니다
    stop = bool(meta.get("collect_stop"))
    if stop:  # 옛 자동 수집 멈춤 결과지의 답은 세션에 넘기지 않고 닫는다. 자동 수집은 261025-jipsa-42에서 뗐다
        close = True
    # close는 일을 다른 실행이 했으므로 마감 시각을 원래 확인 필요로 끝난 때로 둔다. 타임라인에 답 넣은 시각까지 막대가 늘지 않는다
    finished = meta.get("finished") if close and meta.get("finished") else now_iso()
    meta.update(status="완료", answer=text, finished=finished, summary=f"{meta.get('summary', '')} 답: {text}"[:200], updated=now_iso())
    write_json(RUNS / run_id / "meta.json", meta)
    dirs = attempt_dirs(run_id)
    if dirs:
        res = read_json(dirs[-1] / "result.json") or {}
        res.update(status="완료", answer=text)
        write_json(dirs[-1] / "result.json", res)
    if row:
        queue.update(row["key"], status=queue.DONE, run_id=run_id, finished=meta["finished"], reason=meta["summary"], answer=text)
    events.emit("answer", run=run_id, answer=text[:120], resume=False, closed=close)
    note = ""
    if not close:
        inbox_add(meta, text, picks)
        note = delivery_note(str(meta.get("parent_run") or ""))
    todo_line = ""
    if meta.get("todo_plan"):
        from scheduler import auto, todo

        try:
            todo_line = auto.plan_answered(meta, text)
        except (todo.TodoError, OSError) as e:
            events.emit("error", where="plan_answered", run=run_id, error=str(e)[:200])
    write_sheet(run_id)
    confirm.ack(run_id, str(meta["finished"]))
    try:
        report.write(meta.get("report_date") or now().date().isoformat())
    except OSError:
        pass
    return {"ok": True, "resume": False, **({"todo": todo_line} if todo_line else {}), **({"delivery": note} if note else {})}


def unanswer(run_id: str) -> dict:
    """잘못 넣은 답을 물린다. 세션과 서브에이전트 실행만. 확인 필요로 되돌리고 답을 지운다."""
    meta = meta_of(run_id)
    if not meta:
        return {"ok": False, "why": "기록이 없는 실행ID"}
    if meta.get("answered_after") and meta.get("answer"):  # 끝난 실행에 넣은 답은 주체와 무관하게 물린다. 상태는 그대로다
        prev = meta.pop("answer")
        meta.pop("answered_at", None); meta.pop("answered_after", None)
        meta["updated"] = now_iso()
        write_json(RUNS / run_id / "meta.json", meta)
        dirs = attempt_dirs(run_id)
        if dirs:
            res = read_json(dirs[-1] / "result.json") or {}
            res.pop("answer", None)
            write_json(dirs[-1] / "result.json", res)
        delivered = _inbox_drop(run_id)
        confirm.reset(run_id)  # 답을 넣으며 한 확인도 되돌린다. 실패를 확인해 완료로 바꿨다면 실패로 돌아온다
        events.emit("unanswer", run=run_id, was=prev[:120], after=True)
        write_sheet(run_id)
        return {"ok": True, "was": prev, "delivered": delivered}
    if meta.get("executor", "worker") == "worker":
        return {"ok": False, "why": "스케줄러 작업자 실행은 물릴 수 없다. 이어 돌리기가 시작됐을 수 있다"}
    if not meta.get("answer"):
        return {"ok": False, "why": "넣은 답이 없다"}
    prev = meta.pop("answer")
    summary = meta.get("summary", "")
    cut = summary.rfind(" 답: ")
    meta.update(status="확인 필요", finished=None, summary=summary[:cut] if cut > 0 else summary, updated=now_iso())
    write_json(RUNS / run_id / "meta.json", meta)
    dirs = attempt_dirs(run_id)
    if dirs:
        res = read_json(dirs[-1] / "result.json") or {}
        res.pop("answer", None); res["status"] = "확인 필요"
        write_json(dirs[-1] / "result.json", res)
    row = queue.by_run(run_id)
    if row:
        queue.update(row["key"], status=queue.HOLD, run_id=run_id, finished=None, reason=meta["summary"], answer=None)
    events.emit("unanswer", run=run_id, was=prev[:120])
    write_sheet(run_id)
    return {"ok": True, "was": prev}


def close(meta: dict, *, notify: bool = True) -> dict:
    """끝난 실행의 공통 마무리. 결과지를 쓰고, 그날 보고를 다시 만들고, 확인 필요와 실패면 Slack 요약 글 하나를 보낸다. 실행 주체와 무관하다."""
    from scheduler import attack

    run_id = meta["run_id"]
    s = attack.summary(run_id)  # 마감 전 Sol 공격 요약을 기록과 결과지에 붙인다(261024-jipsa-11)
    if s or meta.get("attack"):
        meta["attack"] = s
    from scheduler import wording

    dirs = attempt_dirs(run_id)
    w = wording.check(dirs[-1]) if dirs else {"found": [], "note": ""}  # 바꿀 낱말 검사. 주의 줄만 남기고 막지 않는다(261029-jipsa-05)
    if w["found"] or meta.get("wording"):
        meta["wording"] = w
    if s or meta.get("attack") or meta.get("wording"):
        write_json(RUNS / run_id / "meta.json", meta)
    out: dict = {"sheet": str(write_sheet(run_id)), "slack": "생략", "attack": attack.short(s)}
    date = meta.get("report_date") or now().date().isoformat()
    try:
        out["report"] = str(report.write(date))
    except OSError as e:
        events.emit("error", run=run_id, where="report", error=str(e)[:200])
    # 확인 필요와 실패만 바로 보낸다. 완료는 모드와 무관하게 바로 보내지 않는다(261025-jipsa-20, 기획 3판 가안).
    # 유인 모드 cycle의 중간 단계도 보내지 않는다. 목표 정하기와 Cycle 종합 보고만 보낸다(261024-jipsa-05)
    quiet = report.card_skip(meta) if notify else ""
    if quiet:
        notify = False
        out["slack"] = f"{quiet}라 보내지 않음"
    if notify:
        out["slack"] = slack.notify(report.card(meta))
        events.emit("slack", run=run_id, kind_detail="finish_card", result=out["slack"])
    return out


# ----- 결과지 = 보고서 -----
def _split_files(report: str) -> tuple[str, list[str]]:
    """보고서 본문에서 '열어 볼 파일' 줄을 떼어 낸다(261026-jipsa-30). 원본 보고서 파일은 그대로 둔다."""
    keep, files = [], []
    for line in report.splitlines():
        (files if line.strip().startswith("열어 볼 파일") else keep).append(line)
    return "\n".join(keep).rstrip(), files


def _files_fold(files: list[str], meta: dict) -> str:
    """떼어 낸 파일 줄과 커밋 번호를 접힌 영역 하나로 모은다. 둘 다 없으면 빈 글자다."""
    commit = meta.get("commit") or ""
    if not files and not commit:
        return ""
    lines = ["", "<details>", "<summary>원본 파일과 커밋</summary>", "", *[f + "  " for f in files]]
    if commit:
        lines.append(f"커밋: {commit}")
    return "\n".join(lines + ["", "</details>", ""])


def sheet(meta: dict) -> str:
    """결과지 본문. 작업자나 서브에이전트가 쓴 보고서(report.md)를 그대로 보여 준다.

    보고서가 없으면 결과 한 줄과 확인 필요 선택지만으로 짧은 대체 보고를 만든다. 실행ID, 주체, 시간, 토큰은 화면 머리줄이 보여 주므로 넣지 않는다.
    """
    run_id = meta["run_id"]
    dirs = attempt_dirs(run_id)
    report = read_text(dirs[-1] / "report.md") if dirs else None
    if report and report.strip():
        from scheduler import attack

        body, files = _split_files(report.strip())
        warn = (meta.get("wording") or {}).get("note") or ""  # 마감 때 낱말 검사가 남긴 주의 줄
        body += f"\n\n{warn}\n" if warn else ""
        return body + "\n" + _files_fold(files, meta) + attack.fold(run_id)  # 경로와 커밋은 접고, 공격과 답 표도 접어 아래에 둔다
    st = meta.get("status", "진행 중")
    summary = meta.get("summary") or meta.get("reason") or ""
    lines = [f"# {meta.get('title', run_id)}", "", "보고서가 없다. 작업자가 report.md를 쓰지 않았거나 작업이 아직 끝나지 않았다.", ""]
    if summary:
        lines += ["```요약", summary.rstrip(".") + ".", "```", ""]
    if st == "확인 필요":
        lines += ["## 확인 필요", f"걸린 규칙은 {meta.get('rule') or '(없음)'}이다.", "", "선택지는 아래와 같다. 추천이 앞에 있다.", ""]
        lines += [f"{i + 1}. {o}" for i, o in enumerate(meta.get("options") or [])] + [""]
    if st == "실패" or meta.get("confirmed_from"):
        lines += ["## 실패 사유", meta.get("reason") or "(없음)", ""]
    return "\n".join(lines)


def report_base(run_id: str) -> str:
    """보고서 안의 상대 경로 그림이 붙는 웹 경로."""
    dirs = attempt_dirs(run_id)
    return f"/runs/{run_id}/{dirs[-1].name}/" if dirs else f"/runs/{run_id}/"


def write_sheet(run_id: str) -> Path:
    meta = meta_of(run_id) or {"run_id": run_id}
    path = RUNS / run_id / "result.md"
    path.write_text(sheet(meta), encoding="utf-8")
    return path


# ----- 지금 하는 일 한 문장 -----
def _first_sentence(text: str, limit: int = 120) -> str:
    text = " ".join((text or "").split())
    for cut in ("다. ", ". ", "! ", "? "):
        i = text.find(cut)
        if 0 < i < limit:
            return text[: i + len(cut.strip())]
    return text[:limit]


def now_line(meta: dict) -> str:
    """진행 중인 실행이 지금 무엇을 하는지 한 문장. 세션은 hook이 적은 문장, 작업자는 progress.md의 마지막 한 일이나 계획의 다음 단계다."""
    if meta.get("status") != "진행 중":
        return ""
    if meta.get("now"):
        return _first_sentence(meta["now"])
    if meta.get("executor") == "session":
        return f"요청: {meta['last_prompt']}" if meta.get("last_prompt") else ""
    dirs = attempt_dirs(meta["run_id"])
    if dirs:
        prog = read_text(dirs[-1] / "progress.md") or ""
        bullets = [l.strip()[2:].strip() for l in prog.splitlines() if l.strip().startswith("- ") and len(l.strip()) > 4]
        if bullets:
            return _first_sentence(bullets[-1])
        plan = read_text(dirs[-1] / "plan.md") or ""
        for l in plan.splitlines():
            s = l.strip()
            if s.startswith("- [ ]") or (s[:2].isdigit() and s[1:3] in (". ", ") ")):
                return _first_sentence(s.lstrip("- [ ]").strip())
    return _first_sentence(meta.get("criteria") or meta.get("title") or "")


# ----- 목록 -----
def list_runs(*, limit: int = 50, date: str | None = None, project: str | None = None, status: str | None = None) -> list[dict]:
    """끝난 것과 진행 중인 것을 시작 시각 역순으로 돌려준다."""
    out = []
    for d in RUNS.glob("*"):
        m = read_json(d / "meta.json")
        if not m or not m.get("started"):
            continue
        if date and m.get("report_date") != date:
            continue
        if project and m.get("project") != project:
            continue
        if status and m.get("status") != status:
            continue
        out.append(m)
    out.sort(key=lambda m: m["started"], reverse=True)
    return out[:limit] if limit else out


# ----- Claude Code 세션 서브에이전트 기록 들여오기 -----
_TOOL_KEYS = ("command", "file_path", "pattern", "query", "url", "description", "prompt", "skill", "notebook_path")


def _tool_summary(name: str, inp: dict) -> str:
    val = ""
    for k in _TOOL_KEYS:
        if inp.get(k):
            val = str(inp[k])
            break
    if name in ("Read", "Edit", "Write", "NotebookEdit") and val:
        val = val.replace("\\", "/").rsplit("/", 1)[-1]
    val = " ".join(val.split())
    return f"{name} {val[:90]}".strip()


def _local(ts: str) -> datetime:
    """기록의 UTC 시각(…Z)을 이 컴퓨터의 시각으로 바꾼다."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().replace(tzinfo=None, microsecond=0)


def parse_transcript(path: Path) -> dict:
    """서브에이전트 jsonl에서 도구 호출, 사용량, 모델, 시작과 끝, 마지막 보고 본문을 뽑는다.

    기록은 API 응답 하나를 내용 조각마다 한 줄씩 남기고 줄마다 같은 usage를 붙인다. 그래서 사용량은 message.id별로 한 번만 센다.
    id가 없는 옛 줄은 줄마다 한 번으로 센다(261102-jipsa-50)."""
    first = last = None
    seen: dict[str, dict] = {}
    no_id: list[dict] = []
    tools: list[dict] = []
    models: set[str] = set()
    report_text = ""
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = rec.get("timestamp")
            if ts:
                first = first or ts
                last = ts
            msg = rec.get("message")
            if not isinstance(msg, dict):
                continue
            u = msg.get("usage")
            if u:
                if msg.get("id"):
                    seen[msg["id"]] = u  # 뒤 줄이 앞 줄을 덮는다
                else:
                    no_id.append(u)
                if msg.get("model"):
                    models.add(msg["model"])
            if msg.get("role") != "assistant" or not isinstance(msg.get("content"), list):
                continue
            texts = []
            for c in msg["content"]:
                if c.get("type") == "tool_use":
                    tools.append({"ts": ts, "tool": c.get("name", ""), "tool_id": c.get("id", ""), "summary": _tool_summary(c.get("name", ""), c.get("input") or {})})
                elif c.get("type") == "text" and c.get("text", "").strip():
                    texts.append(c["text"])
            if texts:
                report_text = texts[-1]
    rows = [*seen.values(), *no_id]
    usage = {"input": sum(int(u.get("input_tokens", 0)) for u in rows),
             "cache_write": sum(int(u.get("cache_creation_input_tokens", 0)) for u in rows),
             "cache_read": sum(int(u.get("cache_read_input_tokens", 0)) for u in rows),
             "output": sum(int(u.get("output_tokens", 0)) for u in rows), "calls": len(rows)}
    return {"first": _local(first) if first else None, "last": _local(last) if last else None, "usage": usage,
            "tools": tools, "model": ", ".join(sorted(models)), "report": report_text}


def find_transcript(agent_name: str, since: datetime | None = None) -> Path | None:
    """~/.claude/projects 아래에서 이름이 들어간 가장 최근 서브에이전트 기록을 찾는다."""
    base = Path.home() / ".claude" / "projects"
    found = [p for p in base.glob(f"*/*/subagents/agent-*{agent_name}*.jsonl")]
    if since:
        found = [p for p in found if datetime.fromtimestamp(p.stat().st_mtime) >= since]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def import_transcript(run_id: str, path: Path, *, attempt: int = 1, status: str = "", minutes: int | None = None) -> dict:
    """기록에서 도구 이벤트, 토큰, 모델, 보고 본문을 runs/<실행ID>/attempt-N/에 들여온다. 이벤트 파일은 없을 때만 만든다."""
    info = parse_transcript(path)
    att_dir = RUNS / run_id / f"attempt-{attempt}"
    att_dir.mkdir(parents=True, exist_ok=True)
    existing = read_text(att_dir / "report.md")
    if info["report"] and not (existing and existing.strip()):
        # 서브에이전트가 규격대로 쓴 report.md가 있으면 그대로 두고, 없을 때만 마지막 보고 본문을 넣는다
        (att_dir / "report.md").write_text(info["report"].strip() + "\n", encoding="utf-8")
    meta = meta_of(run_id) or {"run_id": run_id}
    meta["tokens"] = info["usage"]
    if info["model"]:
        meta["model"] = info["model"]
    meta["transcript"] = str(path)
    write_json(RUNS / run_id / "meta.json", meta)
    ev_path = att_dir / "events.jsonl"
    if not ev_path.exists() and info["first"] and info["last"]:
        t0, t1 = info["first"].isoformat(timespec="seconds"), info["last"].isoformat(timespec="seconds")
        base = {"run": run_id, "attempt": attempt}
        rows = [
            {"ts": t0, "kind": "run_start", "run": run_id, "project": meta.get("project"), "title": meta.get("title"),
             "project_kind": meta.get("kind"), "limit": meta.get("minutes_limit"), "executor": meta.get("executor", "subagent")},
            {"ts": t0, "kind": "stage_start", "stage": "run", **base},
            {"ts": t0, "kind": "segment_start", "stage": "run", "segment": 1, **base},
        ]
        for t in info["tools"]:
            rows.append({"ts": _local(t["ts"]).isoformat(timespec="seconds") if t["ts"] else t0, "kind": "tool", "stage": "run", "segment": 1,
                         "tool": t["tool"], "summary": t["summary"], "tool_id": t["tool_id"], **base})
        mins = minutes if minutes is not None else _minutes(info["first"], info["last"])
        rows += [
            {"ts": t1, "kind": "segment_end", "stage": "run", "segment": 1, "turns": info["usage"]["calls"],
             "input_tokens": info["usage"]["input"] + info["usage"]["cache_read"] + info["usage"]["cache_write"],
             "output_tokens": info["usage"]["output"], "minutes": mins, "verdict": "결과 보고", **base},
            {"ts": t1, "kind": "stage_end", "stage": "run", "status": status or meta.get("status", ""), "minutes": mins, **base},
            {"ts": t1, "kind": "run_end", "run": run_id, "status": status or meta.get("status", ""), "minutes": mins, "evidence": meta.get("evidence_ref", "")},
        ]
        with ev_path.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return info
