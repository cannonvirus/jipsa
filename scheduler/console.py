"""콘솔. 상태 줄, 타임라인, 트리를 한 화면에 그린다. events.jsonl과 큐, 리스, 모드만 읽는다."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.tree import Tree

from scheduler import claude_window, codex_window, events, modes, queue, resources
from scheduler.config import RUNS, display_project, norm_record, now, parse_iso, time_text

STAGE_CHAR = {"run": "▓", "analyze": "▒", "search": "░"}
STATUS_STYLE = {"완료": "green", "실패": "red", "확인 필요": "yellow", "건너뜀": "dim", "진행 중": "cyan", "실행 중": "cyan", "대기": "white"}


def _runs_today() -> dict[str, dict]:
    """최근 24시간 안에 시작한 실행의 meta."""
    out = {}
    cut = now() - timedelta(hours=24)
    for d in RUNS.glob("*"):
        try:
            meta = norm_record(json.loads((d / "meta.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        if meta.get("started") and parse_iso(meta["started"]) >= cut:
            out[meta["run_id"]] = meta
    return out


def _events_for(run_ids: set[str]) -> dict[str, list[dict]]:
    rows = events.read_all()
    for rid in run_ids:
        for n in range(1, 10):
            p = RUNS / rid / f"attempt-{n}" / "events.jsonl"
            if p.exists():
                rows += events.read_all(p)
    by: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("run") in run_ids:
            by.setdefault(r["run"], []).append(r)
    for v in by.values():
        v.sort(key=lambda r: r["ts"])
    return by


def status_line() -> Text:
    mode = modes.get()
    c = queue.counts()
    s = resources.summary()
    t = Text()
    t.append(f"jipsa {now():%H:%M}  ", style="bold")
    t.append(f"{'Auto' if mode['mode'] == modes.AUTO else '유인'} 모드  ", style="magenta" if mode["mode"] == modes.AUTO else "cyan")
    t.append(f"대기 {c.get(queue.PENDING, 0)}  실행 중 {c.get(queue.RUNNING, 0)}  확인 필요 {c.get(queue.HOLD, 0)}  ")
    if s["gpu_ok"]:
        t.append(f"GPU {s['gpu_used_gb']:.1f}/{s['gpu_total_gb']:.1f}GB 리스 {len(s['leases'])}  ")
    else:
        t.append("GPU 측정 불가  ", style="dim")
    if s["ollama"]:
        t.append(f"Ollama {', '.join(s['ollama'])}  ", style="dim")
    if mode["mode"] == modes.UNATTENDED:
        t.append(f"종료 {modes.cutoff_for(mode):%H:%M}", style="magenta")
    limit = [r for r in events.read_all()[-200:] if r.get("kind") == "limit_wait"]
    if limit:
        t.append(f"  한도 대기 {limit[-1].get('until', '')[-5:]}까지", style="yellow")
    w = codex_window.window()
    t.append(f"  {codex_window.state_text(w)}", style="green" if w["state"] == codex_window.FREE else "red")
    u = claude_window.usage()  # Codex 창 바로 뒤에 Claude 5시간 창. 대시보드 환경 줄과 같은 글자다
    t.append(f"  {u['text']}", style="dim" if u["pct"] is None else "red" if u["pct"] >= 100 else "yellow" if u["pct"] >= 90 else "green")
    return t


def timeline(metas: dict[str, dict], evs: dict[str, list[dict]], width: int = 60, hours: float = 8.0) -> Text:
    end = now()
    start = end - timedelta(hours=hours)
    span = (end - start).total_seconds()
    t = Text()
    ticks = Text(" " * 26)
    step = max(6, width // 4)
    for i in range(0, width - 5, step):
        tm = start + timedelta(seconds=span * i / width)
        ticks.append(f"{tm:%H:%M}".ljust(step))
    t.append_text(ticks)
    t.append("\n")
    for rid, meta in sorted(metas.items(), key=lambda kv: kv[1].get("started", "")):
        cells = [" "] * width
        stage_open: dict[str, datetime] = {}
        for r in evs.get(rid, []):
            ts = parse_iso(r["ts"])
            k = r["kind"]
            if k == "stage_start":
                stage_open[r["stage"]] = ts
            elif k == "stage_end" and r.get("stage") in stage_open:
                a, b = stage_open.pop(r["stage"]), ts
                _fill(cells, start, span, width, a, b, STAGE_CHAR.get(r["stage"], "▓"))
            elif k in ("wait_resource", "limit_wait"):
                _fill(cells, start, span, width, ts, ts + timedelta(minutes=5), "┈")
            elif k == "retry":
                _put(cells, start, span, width, ts, "R")
        for st, a in stage_open.items():
            _fill(cells, start, span, width, a, end, STAGE_CHAR.get(st, "▓"))
        label = f"{display_project(meta.get('project', ''))}/{meta.get('title', '')}"[:24].ljust(24)
        status = meta.get("status", "진행 중")
        t.append(label + "  ", style=STATUS_STYLE.get(status, "white"))
        t.append("".join(cells))
        mark = {"완료": " ✓", "실패": " ✗", "확인 필요": " ?", "건너뜀": " -"}.get(status, "")
        t.append(mark + "\n", style=STATUS_STYLE.get(status, "white"))
    if not metas:
        t.append("  (최근 24시간 실행 없음)\n", style="dim")
    return t


def _idx(start: datetime, span: float, width: int, ts: datetime) -> int:
    return max(0, min(width - 1, int((ts - start).total_seconds() / span * width)))


def _fill(cells, start, span, width, a, b, ch):
    for i in range(_idx(start, span, width, a), _idx(start, span, width, b) + 1):
        cells[i] = ch


def _put(cells, start, span, width, ts, ch):
    cells[_idx(start, span, width, ts)] = ch


def tree(metas: dict[str, dict], evs: dict[str, list[dict]]) -> Tree:
    root = Tree("scheduler", guide_style="dim")
    for rid, meta in sorted(metas.items(), key=lambda kv: kv[1].get("started", "")):
        status = meta.get("status", "진행 중")
        used = meta.get("minutes_used", 0)
        node = root.add(Text(f"{display_project(meta.get('project'))}/{meta.get('title')}  {rid}  {status}  {time_text(used, meta.get('minutes_limit'))}",
                             style=STATUS_STYLE.get(status, "white")))
        rows = evs.get(rid, [])
        attempts = sorted({int(r.get("attempt") or 0) for r in rows if r.get("attempt")})
        for n in attempts or [1]:
            arows = [r for r in rows if int(r.get("attempt") or 0) == n]
            anode = node.add(f"attempt-{n}")
            for stage in ("run", "analyze", "search"):
                srows = [r for r in arows if r.get("stage") == stage]
                if not srows:
                    continue
                ended = [r for r in srows if r["kind"] == "stage_end"]
                tail = ""
                if ended:
                    e = ended[-1]
                    tail = {"run": f"{e.get('status', '')} {e.get('minutes', 0)}분", "analyze": f"원인 {e.get('cause', '')}, 지적 {e.get('issues', 0)}건",
                            "search": f"출처 {e.get('sources', 0)}건"}.get(stage, "")
                else:
                    tail = "진행 중"
                snode = anode.add(f"{stage}  {tail}")
                segs = sorted({int(r.get("segment") or 0) for r in srows if r.get("segment")})
                for seg in segs:
                    segrows = [r for r in srows if int(r.get("segment") or 0) == seg]
                    end = [r for r in segrows if r["kind"] == "segment_end"]
                    judge = [r for r in segrows if r["kind"] == "judge"]
                    info = ""
                    if end:
                        e = end[-1]
                        info = f"{e.get('turns', 0)}턴 {e.get('minutes', 0)}분 {e.get('verdict', '')}"
                    if judge:
                        info += f"  판정 {judge[-1].get('progress')}"
                    gnode = snode.add(f"구간 {seg}  {info}")
                    tools = [r for r in segrows if r["kind"] == "tool"]
                    parents = [r for r in tools if r.get("tool") in ("Agent", "Task") and not r.get("parent")]
                    for pr in parents:
                        kids = [r for r in tools if r.get("parent") == pr.get("tool_id")]
                        gnode.add(f"{pr.get('summary')}  하위 도구 {len(kids)}개")
                    recent = [r for r in tools if not r.get("parent")][-3:]
                    for r in recent:
                        if r.get("tool") not in ("Agent", "Task"):
                            gnode.add(Text(f"{r.get('summary')}", style="dim"))
                if stage == "search":
                    tools = [r for r in srows if r["kind"] == "tool"][-3:]
                    for r in tools:
                        snode.add(Text(f"{r.get('summary')}", style="dim"))
    for item in queue.pending()[:5]:
        root.add(Text(f"(대기) {display_project(item['project'])}/{item['title']}  {item.get('reason') or ''}", style="dim"))
    return root


def render() -> Group:
    metas = _runs_today()
    evs = _events_for(set(metas))
    width = max(24, Console().size.width - 36)
    return Group(
        Panel(status_line(), title="상태", border_style="blue"),
        Panel(timeline(metas, evs, width=width), title="타임라인 (최근 8시간)", border_style="blue"),
        Panel(tree(metas, evs), title="트리", border_style="blue"),
    )


def live(refresh: float = 3.0) -> None:
    console = Console()
    with Live(render(), console=console, refresh_per_second=1, screen=True) as lv:
        while True:
            time.sleep(refresh)
            lv.update(render())


def once() -> None:
    Console().print(render())


_ = Path  # 보존
