"""runs/ 보관 기한. 오래된 실행 기록을 월별 묶음(runs/archive/<YYYY-MM>.zip)으로 옮기고 오래된 묶음을 지운다.

기본은 미리보기다. 진행 중, 확인 필요 기록, 큐에 걸린 실행, worktree가 남은 실행, 오늘 기록은 건드리지 않는다.
압축 뒤 묶음을 다시 열어 파일 수를 맞춰 본 다음에만 원본 폴더를 지우고, 한 일을 runs/archive/prune.log에 남긴다.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from scheduler import config, queue
from scheduler.record import read_json

RUN_ID = re.compile(r"^\d{6}-.+-\d+$")
KEEP_STATUS = {"진행 중", "확인 필요"}
QUEUE_LIVE = {queue.PENDING, queue.RUNNING, queue.HOLD}

ARCHIVE = "묶음으로 옮김"
DELETE = "묶음 삭제"
KEEP = "유지"
NOT_YET = "기한 전"


@dataclass
class Item:
    path: Path
    kind: str  # 실행 기록, 세션 기록, 일회성 폴더, 보관 묶음
    last: date
    action: str
    why: str = ""
    bundle: str = ""


def _last_activity(d: Path, meta: dict | None) -> date:
    """폴더 안 파일의 가장 늦은 수정 날짜와 meta의 시각 가운데 늦은 쪽."""
    stamps = [datetime.fromtimestamp(d.stat().st_mtime)]
    for p in d.rglob("*"):
        try:
            stamps.append(datetime.fromtimestamp(p.stat().st_mtime))
        except OSError:
            pass
    for key in ("started", "updated", "finished"):
        v = (meta or {}).get(key)
        if v:
            try:
                stamps.append(config.parse_iso(v))
            except ValueError:
                pass
    return max(stamps).date()


def _protected(run_id: str, meta: dict | None, today: date) -> str:
    """지켜야 하는 까닭. 없으면 빈 문자열."""
    if meta and meta.get("status") in KEEP_STATUS:
        return meta["status"]
    q = queue.by_run(run_id)
    if q and q.get("status") in QUEUE_LIVE:
        return f"큐 {q['status']}"
    if (config.WORKTREES / run_id).exists():
        return "worktree 남음"
    if run_id.startswith(today.strftime("%y%m%d")) or (meta or {}).get("report_date") == today.isoformat():
        return "오늘 기록"
    return ""


def _month_end(ym: str) -> date:
    y, m = map(int, ym.split("-"))
    return (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))


def plan(runs_dir: Path | None = None, *, run_days: int | None = None, other_days: int | None = None,
         archive_days: int | None = None, today: date | None = None) -> list[Item]:
    runs_dir = runs_dir or config.RUNS
    run_days = config.RETAIN_RUN_DAYS if run_days is None else run_days
    other_days = config.RETAIN_OTHER_DAYS if other_days is None else other_days
    archive_days = config.RETAIN_ARCHIVE_DAYS if archive_days is None else archive_days
    today = today or config.now().date()
    out: list[Item] = []
    for d in sorted(p for p in runs_dir.iterdir() if p.is_dir() and p.name != "archive"):
        meta = read_json(d / "meta.json")
        is_session = d.name.startswith("session-")
        is_run = not is_session and (bool(meta) or bool(RUN_ID.match(d.name)))
        kind = "실행 기록" if is_run else ("세션 기록" if is_session else "일회성 폴더")
        last = _last_activity(d, meta)
        limit = run_days if is_run else other_days
        why = _protected(d.name, meta, today) if meta or is_run else ""
        why = why or ("오늘 기록" if last >= today else "")
        if why:
            out.append(Item(d, kind, last, KEEP, why))
        elif (today - last).days <= limit:
            out.append(Item(d, kind, last, NOT_YET, f"{(today - last).days}일 지남, 기한 {limit}일"))
        else:
            out.append(Item(d, kind, last, ARCHIVE, f"{(today - last).days}일 지남", f"{last:%Y-%m}.zip"))
    arch = runs_dir / "archive"
    for z in sorted(arch.glob("*.zip")) if arch.exists() else []:
        if not re.match(r"^\d{4}-\d{2}$", z.stem):
            continue
        end = _month_end(z.stem)
        age = (today - end).days
        act = DELETE if age > archive_days else NOT_YET
        out.append(Item(z, "보관 묶음", end, act, f"달 끝에서 {max(age, 0)}일 지남, 기한 {archive_days}일"))
    return out


def _rm_readonly(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _log(runs_dir: Path, line: str) -> None:
    log = runs_dir / "archive" / "prune.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as f:
        f.write(f"{config.now_iso()}\t{line}\n")


def _archive_one(item: Item, runs_dir: Path) -> str:
    """폴더를 묶음에 넣고 다시 열어 파일 수를 맞춘 뒤 원본을 지운다. 결과 한 줄을 돌려준다."""
    src = item.path
    zpath = runs_dir / "archive" / item.bundle
    zpath.parent.mkdir(parents=True, exist_ok=True)
    files = [p for p in src.rglob("*") if p.is_file()]
    prefix = src.name + "/"
    with zipfile.ZipFile(zpath, "a", compression=zipfile.ZIP_DEFLATED) as zf:
        have = {n for n in zf.namelist() if n.startswith(prefix)}
        for p in files:
            name = prefix + p.relative_to(src).as_posix()
            if name not in have:
                zf.write(p, name)
    with zipfile.ZipFile(zpath) as zf:
        bad = zf.testzip()
        got = sum(1 for n in zf.namelist() if n.startswith(prefix) and not n.endswith("/"))
    if bad or got != len(files):
        msg = f"묶기 실패\t{src.name}\t{item.bundle}\t파일 {len(files)}개 중 {got}개 확인{', 손상 ' + bad if bad else ''}. 원본 유지"
        _log(runs_dir, msg)
        return msg
    shutil.rmtree(src, onerror=_rm_readonly)
    msg = f"묶음으로 옮김\t{src.name}\t{item.bundle}\t파일 {len(files)}개"
    _log(runs_dir, msg)
    return msg


def apply(items: list[Item], runs_dir: Path | None = None) -> list[str]:
    runs_dir = runs_dir or config.RUNS
    done = []
    for it in items:
        if it.action == ARCHIVE:
            done.append(_archive_one(it, runs_dir))
        elif it.action == DELETE:
            it.path.unlink()
            msg = f"묶음 삭제\t{it.path.name}\t\t{it.why}"
            _log(runs_dir, msg)
            done.append(msg)
    return done


def archived_in(run_id: str, runs_dir: Path | None = None) -> str:
    """보관된 실행이 든 묶음 이름. 없으면 빈 문자열."""
    arch = (runs_dir or config.RUNS) / "archive"
    for z in sorted(arch.glob("*.zip"), reverse=True) if arch.exists() else []:
        try:
            with zipfile.ZipFile(z) as zf:
                if any(n.startswith(run_id + "/") for n in zf.namelist()):
                    return z.name
        except zipfile.BadZipFile:
            continue
    return ""
