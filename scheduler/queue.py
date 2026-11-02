"""큐. 작업 항목(scheduler/workitem.py)을 받아 우선순위로 정렬하고 상태를 기록한다.

runtime/state/queue.jsonl에 항목 한 줄씩 둔다. 상태는 대기, 실행 중, 완료, 실패, 확인 필요, 건너뜀이다.
"""

from __future__ import annotations

import json
import threading

from scheduler import workitem
from scheduler.config import HOLD, RUNS, STATE, norm_record, now_iso
from scheduler.registry import Project

QUEUE_FILE = STATE / "queue.jsonl"
_lock = threading.Lock()

PENDING = "대기"
RUNNING = "실행 중"
DONE = "완료"
FAILED = "실패"
SKIPPED = "건너뜀"
SESSION_EXECUTORS = {"subagent", "session", "manual"}  # 세션이 jipsa begin, finish로 맡는 실행. 스케줄러는 손대지 않는다
SESSION_HOLD = "세션 실행 대기로 미룸"  # 같은 원본 폴더의 세션 실행이 끝날 때까지 작업 중 저장과 시작을 미룬 대기 줄의 사유 머리


def load() -> list[dict]:
    if not QUEUE_FILE.exists():
        return []
    rows = []
    for line in QUEUE_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(norm_record(json.loads(line)))  # 옛 줄의 판단 대기는 확인 필요로 읽는다
    return rows


def save(rows: list[dict]) -> None:
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_FILE.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def _entry_from_item(item: workitem.Item, project: Project, source: str) -> dict:
    return {
        "key": item.key,
        "project": project.name,
        "title": item.title,
        "criteria": item.criteria,
        "est_minutes": item.est_minutes,
        "kind": project.kind,
        "priority": project.priority,
        "needs_gpu": project.needs_gpu,
        "status": PENDING,
        "reason": "",
        "run_id": None,
        "source": source,
        "file": "" if str(item.file) in ("", ".") else str(item.file),  # 주간 계획 파일을 뗀 뒤로는 빈 글자다. Cycle 단계 줄만 할 일 파일 경로다
        "line": item.line,
        "added": now_iso(),
        "started": None,
        "finished": None,
        "answer": None,
        "wait_since": None,
        "tier": item.tier,
        **_category(item),
    }


def _category(item: workitem.Item) -> dict:
    """큐 줄의 분류 칸. 작업자 실행의 meta가 이 칸을 그대로 옮긴다."""
    cat, pick, guessed = workitem.category_of(item)
    return {"category": cat, "pick": pick, "category_guess": guessed}


def add(item: workitem.Item, project: Project, after: list[str] | None = None, worker: str | None = None) -> dict:
    with _lock:
        rows = load()
        for r in rows:
            if r["key"] == item.key and r["status"] in (PENDING, RUNNING):
                return r
        entry = _entry_from_item(item, project, "add")
        entry["after"] = list(after or [])
        if worker:
            entry["worker"] = worker  # 작업자 공급자. 등록부 worker.provider보다 앞선다
        rows.append(entry)
        save(rows)
        return entry


def add_entry(entry: dict) -> dict:
    """만들어 둔 줄을 그대로 더한다. 범위의 확장과 예비가 쓴다. 같은 key가 대기나 실행 중이면 그 줄을 돌려준다."""
    with _lock:
        rows = load()
        for r in rows:
            if r["key"] == entry["key"] and r["status"] in (PENDING, RUNNING):
                return r
        rows.append(entry)
        save(rows)
        return entry


ENDED = (DONE, FAILED, SKIPPED)  # 끝난 줄. 키만으로는 다시 덮지 않는다


def _target(rows: list[dict], key: str, run_id: str | None) -> dict | None:
    """갱신할 줄 하나를 고른다. 같은 키의 줄이 여럿이어도(끝난 목표를 다시 올린 줄) 한 줄만 고친다(261026-jipsa-04).

    run_id가 있으면 그 실행의 줄이고, 맞는 줄이 없으면 아직 시작 전(run_id 없음)이고 끝나지 않은 첫 줄만 후보다.
    다른 실행 ID가 달린 줄은 고르지 않는다(Sol 지적 1). 작업자 시작은 줄의 run_id를 이어 쓰고 새 ID는 빈 줄에만 붙인다.
    run_id가 없으면 시작 전 첫 줄, 그것도 없으면 대기, 실행 중, 확인 필요 순의 첫 줄이다. 끝난 줄은 실행 ID로만 고친다.
    """
    same = [r for r in rows if r["key"] == key]
    if run_id:
        hit = next((r for r in same if r.get("run_id") == run_id), None)
        if hit:
            return hit
    hit = next((r for r in same if not r.get("run_id") and r["status"] not in ENDED), None)
    if hit or run_id:
        return hit
    for status in (PENDING, RUNNING, HOLD):
        hit = next((r for r in same if r["status"] == status), None)
        if hit:
            return hit
    return None


def update(key: str, **fields) -> dict | None:
    """키가 같은 줄 가운데 한 줄만 고친다. fields에 run_id가 있으면 그 실행의 줄을 먼저 고른다(_target)."""
    with _lock:
        rows = load()
        hit = _target(rows, key, fields.get("run_id"))
        if hit:
            hit.update(fields)
            save(rows)
        return hit


def get(key: str) -> dict | None:
    for r in load():
        if r["key"] == key:
            return r
    return None


def by_run(run_id: str) -> dict | None:
    for r in load():
        if r.get("run_id") == run_id:
            return r
    return None


def session_owned(row: dict) -> bool:
    """세션이나 서브에이전트가 맡은 줄인지 본다. 줄의 executor가 없으면 실행의 meta.json을 본다."""
    executor = row.get("executor")
    if not executor and row.get("run_id"):
        try:
            executor = json.loads((RUNS / row["run_id"] / "meta.json").read_text(encoding="utf-8")).get("executor")
        except (OSError, ValueError):
            executor = None
    return executor in SESSION_EXECUTORS


def pending() -> list[dict]:
    """5절 순서. 우선순위 정수, 같은 순위면 GPU가 필요 없는 작업 먼저, GPU 작업은 예상 시간이 짧은 순.

    세션이 맡은 줄은 대기여도 스케줄러가 시작하지 않으므로 넣지 않는다.
    """
    rows = [r for r in load() if r["status"] == PENDING and not session_owned(r)]
    from scheduler.config import DEFAULT_TOTAL_MIN

    def sort_key(r: dict):
        est = r.get("est_minutes") or DEFAULT_TOTAL_MIN.get(r.get("kind", "code"), 90)
        return (r.get("priority", 50), 1 if r.get("needs_gpu") else 0, est if r.get("needs_gpu") else 0, r["added"])

    return sorted(rows, key=sort_key)


def check_after(row: dict) -> tuple[str, str]:
    """선행 지정을 본다. ("ok", "") 시작해도 됨, ("wait", 사유) 선행이 아직 끝나지 않음, ("skip", 사유) 선행이 완료로 끝나지 않음."""
    rows = load()
    for key in row.get("after") or []:
        prior = [r for r in rows if r["key"] == key]
        if not prior:
            return "skip", f"선행 {key} 없음"
        status = prior[-1]["status"]
        if status in (FAILED, SKIPPED, HOLD):
            return "skip", f"선행 {key} {status}"
        if status != DONE:
            return "wait", f"선행 대기: {key}"
    return "ok", ""


def running() -> list[dict]:
    return [r for r in load() if r["status"] == RUNNING]


def counts() -> dict[str, int]:
    out: dict[str, int] = {}
    for r in load():
        out[r["status"]] = out.get(r["status"], 0) + 1
    return out


def reset_running() -> int:
    """스케줄러가 죽었다 살아났을 때 실행 중으로 남은 항목을 대기로 되돌린다.

    세션이 맡은 실행은 스케줄러가 띄운 것이 아니므로 실행 중 그대로 두고 세션의 jipsa finish가 받게 한다.
    """
    with _lock:
        rows = load()
        n = 0
        for r in rows:
            if r["status"] == RUNNING and not session_owned(r):
                r["status"] = PENDING
                r["reason"] = "스케줄러 재시작"
                n += 1
        if n:
            save(rows)
        return n
