"""이벤트 기록. 어댑터와 스케줄러가 일어나는 일을 한 줄씩 붙인다.

한 줄은 {"ts", "kind", "run", "attempt", "stage", "segment", "parent", ...}다. 콘솔과 재생은 이 파일만 읽는다.
작업이 끝나면 `move_run`이 그 작업의 줄을 runs/<실행ID>/attempt-N/events.jsonl로 옮긴다.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from scheduler.config import RUNS, STATE, norm_record, now_iso

EVENTS_FILE = STATE / "events.jsonl"
_lock = threading.Lock()


def emit(kind: str, *, run: str | None = None, attempt: int | None = None, stage: str | None = None,
         segment: int | None = None, parent: str | None = None, **data) -> dict:
    row = {"ts": now_iso(), "kind": kind}
    if run:
        row["run"] = run
    if attempt is not None:
        row["attempt"] = attempt
    if stage:
        row["stage"] = stage
    if segment is not None:
        row["segment"] = segment
    if parent:
        row["parent"] = parent
    row.update(data)
    line = json.dumps(row, ensure_ascii=False)
    with _lock:
        EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with EVENTS_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    return row


def read_all(path: Path = EVENTS_FILE) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(norm_record(json.loads(line)))
            except json.JSONDecodeError:
                continue
    return rows


def move_run(run_id: str) -> int:
    """실행 하나의 줄을 runs/ 아래로 옮기고 상태 파일에서 뺀다. 옮긴 줄 수를 돌려준다."""
    with _lock:
        rows = read_all()
        mine = [r for r in rows if r.get("run") == run_id]
        rest = [r for r in rows if r.get("run") != run_id]
        if not mine:
            return 0
        by_attempt: dict[int, list[dict]] = {}
        for r in mine:
            by_attempt.setdefault(int(r.get("attempt") or 1), []).append(r)
        for n, group in by_attempt.items():
            target = RUNS / run_id / f"attempt-{n}" / "events.jsonl"
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as f:
                for r in group:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        with EVENTS_FILE.open("w", encoding="utf-8") as f:
            for r in rest:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return len(mine)
