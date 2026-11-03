"""웹 화면 서버. web/의 HTML 한 장을 내주고 events.jsonl, 큐, 리스, 모드, 지난 작업 목록과 결과지를 JSON으로 준다.

jipsa는 대시보드다. 실행 주체가 무엇이든 runs/에 남은 기록을 그대로 보여준다.
의존성을 더하지 않으려고 표준 라이브러리 http.server를 쓴다. 로컬에서만 연다.
"""

from __future__ import annotations

import json
import mimetypes
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from scheduler import claude_window, codex_window, confirm, cycle, events, modes, queue, record, report, resources, supervise
from scheduler.config import CUTOFF, HOLD, ROOT, RUNS, TICK_SEC, norm_record, now, now_iso, parse_iso
from notify import slack

WEB_DIR = ROOT / "web"
SERVER_STARTED = now_iso()  # 화면이 이 값이 바뀐 것을 보면 스스로 새로고침한다
EVENT_KEYS = ("ts", "kind", "attempt", "stage", "segment", "parent", "tool", "summary", "tool_id", "status", "minutes",
              "turns", "verdict", "progress", "reason", "cause", "issues", "sources", "why", "until", "commit", "by", "tag",
              "input_tokens", "output_tokens", "killed", "next", "error", "models", "deadline", "same_provider", "from", "to", "provider")
META_KEYS = ("run_id", "project", "title", "criteria", "kind", "started", "finished", "status", "summary", "evidence_ref",
             "minutes_used", "minutes_limit", "report_date", "rule", "options", "added_packages", "limit_wait", "save_commit",
             "workspace", "branch", "mode", "dry_run", "analysis_issues", "search_sources", "analysis_same_provider", "attempts",
             "executor", "model", "tokens", "reason", "queue_key", "parent_run", "agent", "label", "topic", "topics", "cwd_project",
             "confirmed_from", "confirmed_at", "preview_url", "worker_provider", "worker_switched", "provider_switches",
             "category", "pick", "category_guess", "from_run", "cycle", "cycle_round", "cycle_step", "review_of", "revise_of", "attack", "match_budget",
             "draft")  # draft는 begin --draft나 사람 입력의 '초안'으로 표시한 결과지 초안 실행이다(261029-jipsa-35, 261031-jipsa-10)


def _read_meta(d: Path) -> dict | None:
    try:
        return norm_record(json.loads((d / "meta.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


_DONE_EVENTS: dict[str, tuple[tuple, list[dict], list[dict]]] = {}  # 실행ID -> (사건 파일의 수정 시각과 크기, 읽은 줄, 화면용으로 묶은 줄)


def _by_run(rows: list[dict]) -> dict[str, list[dict]]:
    """전역 사건 기록을 실행별로 나눈다. 실행마다 전역 기록을 다시 읽으면 실행 수만큼 1만 줄을 해석했다(261023-jipsa-13)."""
    out: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("run"):
            out.setdefault(r["run"], []).append(r)
    return out


def _view(rows: list[dict]) -> list[dict]:
    rows = sorted(rows, key=lambda r: r["ts"])
    return [{k: r[k] for k in EVENT_KEYS if k in r} for r in rows]


def _folder_events(run_id: str) -> tuple[list[dict], list[dict]]:
    """실행 폴더의 사건 파일(끝난 시도에서 옮긴 줄). (읽은 줄, 화면용으로 묶은 줄)이다.
    파일의 수정 시각과 크기가 그대로면 전에 읽은 값을 다시 쓴다."""
    key = []
    try:
        names = os.listdir(RUNS / run_id)
    except OSError:
        names = []
    for n in range(1, 20):
        if f"attempt-{n}" not in names:
            continue
        p = RUNS / run_id / f"attempt-{n}" / "events.jsonl"
        try:
            st = p.stat()
        except OSError:
            continue
        key.append((n, st.st_mtime_ns, st.st_size))
    key = tuple(key)
    hit = _DONE_EVENTS.get(run_id)
    if hit and hit[0] == key:
        return hit[1], hit[2]
    rows = []
    for n, _, _ in key:
        rows += events.read_all(RUNS / run_id / f"attempt-{n}" / "events.jsonl")
    view = _view(rows)
    _DONE_EVENTS[run_id] = (key, rows, view)
    return rows, view


def _run_events(run_id: str, live: list[dict] | None = None) -> list[dict]:
    """실행 하나의 사건. live는 전역 기록 가운데 이 실행의 줄이고, 없으면 전역 기록을 읽는다."""
    if live is None:
        live = [r for r in events.read_all() if r.get("run") == run_id]
    rows, view = _folder_events(run_id)
    return _view(rows + live) if live else view


def _compact(view: list[dict]) -> list[dict]:
    """타임라인용 사건. 도구 사건이 응답의 9할이라 서브에이전트(하위 도구가 있는 도구) 줄만 남기고 하위 도구 수를 kids에 적는다.
    막대, 대기, 재시도, 서브에이전트 선은 이것으로 그린다. 서브에이전트 줄에는 마지막 하위 도구 요약(last_kid)을 붙여 트리의 지금 줄로 쓰고,
    실행의 마지막 도구 줄 하나는 지금 하는 일로 남긴다. 하위 도구 전부는 결과지 서랍이 /api/run으로 따로 받는다(261023-jipsa-37)."""
    kids: dict[str, int] = {}
    last_kid: dict[str, str] = {}
    last = None
    for e in view:
        if e.get("kind") == "tool":
            last = e
            if e.get("parent"):
                kids[e["parent"]] = kids.get(e["parent"], 0) + 1
                last_kid[e["parent"]] = e.get("summary") or ""
    out = []
    for e in view:
        if e.get("kind") == "tool":
            if e.get("tool_id") in kids and not e.get("parent"):
                e = {**e, "kids": kids[e["tool_id"]], "last_kid": last_kid[e["tool_id"]]}
            elif e is not last:
                continue
        out.append(e)
    return out


def _pack(meta: dict, live: dict[str, list[dict]] | None = None, compact: bool = False) -> dict:
    out = {k: meta.get(k) for k in META_KEYS}
    out["events"] = _run_events(meta["run_id"], None if live is None else live.get(meta["run_id"], []))
    if compact:
        out["events"] = _compact(out["events"])
    out["now_line"] = record.now_line(meta)
    out["preview_url"] = preview_url(meta)
    out["stall_min"] = record.stall_of(meta["run_id"]) if meta.get("status") == "진행 중" else 0  # 세션 서브에이전트가 활동 없이 멈춘 분
    if str(meta.get("run_id", "")).startswith("session-") and "cwd_project" not in meta:
        out["cwd_project"] = _cwd_project(meta.get("cwd") or "")  # hook이 이 값을 적기 전의 세션
    return out


_PAGE_RE = re.compile(r"(?:^|/)content/(.+)/index\.md$")
_NO_PROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 로컬 주소 확인이 시스템 프록시로 새지 않게
_BASES: dict = {"at": 0.0, "map": {}}


def _preview_bases() -> dict[str, str]:
    """등록부의 미리보기 주소. 화면이 몇 초마다 묻는 값이라 30초 동안 다시 읽지 않는다."""
    from scheduler.registry import load_all

    if time.monotonic() - _BASES["at"] > 30:
        _BASES["map"] = {n: p.preview_base for n, p in load_all().items() if p.preview_base}
        _BASES["at"] = time.monotonic()
    return _BASES["map"]


def _local_runs_url(url: str) -> str:
    """runs 폴더 아래 파일을 가리키는 file:// 주소나 윈도 경로를 대시보드가 내주는 /runs/ 주소로 바꾼다. 브라우저는 http 페이지에서 file:// 링크를 막는다."""
    if not url:
        return url
    u = url.strip()
    if u.lower().startswith("file:"):
        path = unquote(urlparse(u).path)
        if re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
    elif re.match(r"^[A-Za-z]:[\/]", u):
        path = u
    else:
        return url
    try:
        rel = Path(os.path.normpath(path)).relative_to(RUNS)
    except ValueError:
        try:
            rel = Path(os.path.normcase(os.path.normpath(path))).relative_to(os.path.normcase(str(RUNS)))
        except ValueError:
            return url  # runs 밖의 주소는 그대로 둔다
    return "/runs/" + "/".join(quote(x) for x in rel.parts)


def preview_url(meta: dict) -> str:
    return _local_runs_url(_preview_raw(meta))


def _preview_raw(meta: dict) -> str:
    """초안 미리보기 주소. result.json의 preview_url이 먼저이고, 없으면 등록부의 미리보기 주소와 바뀐 글 경로로 만든다."""
    if meta.get("preview_url"):
        return str(meta["preview_url"])
    base = _preview_bases().get(str(meta.get("project") or ""))
    if not base:
        return ""
    files = meta.get("changed_files")
    if files is None:
        dirs = record.attempt_dirs(meta["run_id"])
        res = (record.read_json(dirs[-1] / "result.json") or {}) if dirs else {}
        if res.get("preview_url"):
            return str(res["preview_url"])
        files = res.get("changed_files") or []
    for f in files:
        m = _PAGE_RE.search(str(f).replace("\\", "/"))
        if m:
            return base.rstrip("/") + f"/{m.group(1)}/"
    return ""


def preview_check(url: str) -> dict:
    """미리보기 서버가 응답하는지. 127.0.0.1과 localhost 주소만 1.5초 안에 확인하고 외부 주소는 보지 않는다."""
    if url.startswith("/runs/"):
        return {"url": url, "checked": True, "up": (RUNS / unquote(url[len("/runs/"):])).resolve().is_file(), "status": 200}  # 대시보드가 직접 내주는 파일이다
    u = urlparse(url)
    if u.scheme not in ("http", "https") or u.hostname not in ("127.0.0.1", "localhost"):
        return {"url": url, "checked": False, "up": None}
    try:
        with _NO_PROXY.open(urllib.request.Request(url, method="HEAD"), timeout=1.5) as r:
            return {"url": url, "checked": True, "up": True, "status": r.status}
    except urllib.error.HTTPError as e:  # 서버는 떠 있다
        return {"url": url, "checked": True, "up": True, "status": e.code}
    except (OSError, ValueError):
        return {"url": url, "checked": True, "up": False, "status": 0}


def _cwd_project(cwd: str) -> str:
    """세션 시작 폴더가 들어 있는 등록부 프로젝트. 없으면 빈 값이고 화면은 기타로 보낸다."""
    from scheduler.registry import load_all

    c = os.path.normcase(os.path.normpath(cwd)) if cwd else ""
    best, best_len = "", -1
    for name, proj in load_all().items():
        if proj.manual_only:
            continue
        p = os.path.normcase(os.path.normpath(str(proj.path)))
        if c and (c == p or c.startswith(p + os.sep)) and len(p) > best_len:
            best, best_len = name, len(p)
    return best


def _metas() -> list[dict]:
    """시작한 실행 전부의 meta. 한 번의 상태 응답에서 한 번만 읽고 타임라인, 확인 필요, 현황판이 같이 쓴다."""
    out = []
    for d in RUNS.glob("*"):
        meta = _read_meta(d)
        if meta and meta.get("started") and meta.get("run_id"):
            out.append(meta)
    return out


def _runs(filter_fn, live: list[dict] | None = None, metas: list[dict] | None = None, compact: bool = False) -> list[dict]:
    """조건에 맞는 실행의 meta와 사건. live는 이미 읽은 전역 사건 기록이고, 없으면 여기서 한 번 읽는다."""
    grouped = _by_run(events.read_all() if live is None else live)
    out = [_pack(meta, grouped, compact) for meta in (_metas() if metas is None else metas) if filter_fn(meta)]
    out.sort(key=lambda m: m["started"])
    return out


def scheduler_status() -> dict:
    """jipsa run이 돌고 있는지. 잠금이나 심장박동의 프로세스가 살아 있고 마지막 확인이 세 주기 안이면 켜진 것이다."""
    st = supervise.status()
    fresh = st["hb_age"] is not None and st["hb_age"] <= TICK_SEC * 3
    return {"running": bool(st["alive"] and fresh), "alive": st["alive"], "stalled": st["stalled"], "hb_age": st["hb_age"],
            "last_tick": st["last_tick"], "pid": st["pid"], "concurrency": st["concurrency"], "watch": supervise.view()}


def todo_cycles(mode: dict) -> list[dict]:
    """할 일 파일의 Cycle 목표 줄 가운데 시킨 줄과 회차 기록이 있는 줄마다 Cycle 요약 하나(cycle.summary). 타임라인 목표 줄과 현황판 작은 그래프가 읽는다.
    옛 범위 계약 값(scope.status의 cycles)을 261025-jipsa-42에서 이것으로 바꿨다. 261029-jipsa-17에서 Auto 절 대신 시킨 줄과 회차 기록으로 고른다."""
    from scheduler import auto, todo as todofile

    out = []
    try:
        rows, _, _ = todofile.load()
    except (OSError, ValueError):
        return out
    reqs = {r["key"]: r for r in auto.run_requests()}
    for it in rows:
        if not it.cycle:
            continue
        try:
            c = auto.as_cycle(it)
            rec = cycle.load(c)
            if it.key not in reqs and not rec.get("rounds"):
                continue
            out.append(cycle.summary(c, rec, auto.run_mode(reqs[it.key]) if it.key in reqs else mode))
        except (OSError, ValueError, KeyError) as e:
            events.emit("error", where="todo_cycles", error=str(e)[:200])
    return out


def codex_window_state(runs: list[dict]) -> dict:
    """Codex 창. 환경 불 줄의 Codex 불과 옆 글자, 화면에 든 실행의 Claude 전환 횟수다."""
    w = codex_window.with_usage(codex_window.window())  # 실행 기록의 실측 비율이 있으면 화면 글자는 그것이 먼저다
    switches = sum(1 for m in runs for s in m.get("provider_switches") or [] if s.get("to") == codex_window.CLAUDE)
    return {**w, "text": codex_window.env_text(w), "switches": switches, "shown": codex_window.codex_shown()}


def web_stamp() -> str:
    """화면 파일의 마지막 수정 시각. 서버를 다시 띄우지 않고 화면 파일만 고쳐도 열린 화면이 이 값이 바뀐 것을 보고 새로 받는다."""
    try:
        return str(max(p.stat().st_mtime_ns for p in WEB_DIR.iterdir() if p.is_file()))
    except (OSError, ValueError):
        return ""


# ----- 확인 필요 큐(261023-jipsa-37 3안) -----
# 머리 숫자, 확인 필요 탭 배지, 현황판 카드가 모두 이 목록의 길이를 센다. 기준은 261023-jipsa-26과 같다.
# 상태 값 확인 필요(답을 넣을 것)는 확인하거나 답이 큐에 들어가기 전까지, 끝난 완료와 실패는 확인 기준 시각 뒤에 끝났고 확인하지 않았으면 든다.
# 판정은 confirm.shown 하나이고 jipsa status, 보고, 화면의 ackState가 같은 규칙이다(261025-jipsa-04). 24시간 창 밖의 실행도 센다. 세션 기록(session-)은 결과지가 없어 뺀다
FINAL_STEP = "종합 보고"
CUE_ORDER = {FINAL_STEP: 0, "답 대기": 1, "실패": 2, "확인 필요": 3}


def _cue_kind(meta: dict, conf: dict, answered: set[str]) -> str:
    """확인 필요 큐에 드는 종류. 빈 값이면 들지 않는다. 종합 보고, 답 대기(상태 값 확인 필요), 실패, 확인 필요(확인하지 않은 완료)다.
    답이 큐에 들어가 처리 대기인 작업자 실행은 들지 않는다."""
    st = meta.get("status")
    if (st == HOLD and meta.get("run_id") in answered) or confirm.shown(meta, conf) != HOLD:
        return ""
    final = meta.get("cycle_step") == FINAL_STEP or bool(meta.get("night_report"))  # Auto 종합 보고도 종합 보고 칸에 든다
    if st == HOLD:
        return FINAL_STEP if final else "답 대기"
    return FINAL_STEP if final else ("실패" if st == "실패" else "확인 필요")


def cue_queue(metas: list[dict], conf: dict, pending: list[dict]) -> list[dict]:
    """확인 필요 큐. 실행 기록에서만 고른다. 종합 보고, 답 대기, 실패, 확인 필요 순이고 같은 종류는 오래된 것부터다.
    옛 주간 계획 메모의 답 대기 줄과 Auto 목표 큐 셈 글자는 261025-jipsa-42에서 뗐다."""
    answered = {r["run_id"] for r in pending if r.get("answer") and r.get("run_id")}
    out = []
    for m in metas:
        kind = _cue_kind(m, conf, answered)
        if kind:
            out.append({"kind": kind, "run_id": m["run_id"], "project": m.get("project") or "", "title": m.get("title") or "",
                        "label": m.get("label") or "", "status": m.get("status"), "finished": m.get("finished") or "",
                        "cycle": m.get("cycle") or "", "executor": m.get("executor") or ""})
    out.sort(key=lambda r: (CUE_ORDER.get(r["kind"], 9), r["finished"] or "9"))
    return out


# ----- 미병합 브랜치 수(1안). 등록부 저장소의 orch/ 브랜치 가운데 기본 브랜치에 병합되지 않은 수를 git으로 읽기만 해서 센다 -----
UNMERGED_SEC = 300  # 저장소 열몇 곳에 git을 두 번씩 부르므로 5분 동안 보관한다
_UNMERGED: dict = {"at": None, "map": {}, "busy": False}
_UNMERGED_LOCK = threading.Lock()


def _git(path: Path, *args: str) -> str | None:
    import subprocess

    from scheduler.nowindow import hidden

    try:
        r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, **hidden())
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _count_unmerged(path: Path) -> int | None:
    if not (path / ".git").exists():
        return None
    base = next((b for b in ("main", "master") if _git(path, "rev-parse", "--verify", "--quiet", f"refs/heads/{b}") is not None), None)
    if not base:
        return None
    out = _git(path, "branch", "--list", "orch/*", "--no-merged", base, "--format=%(refname:short)")
    return None if out is None else sum(1 for line in out.splitlines() if line.strip())


def _refresh_unmerged() -> None:
    from scheduler.registry import load_all

    try:
        by_path: dict[str, int | None] = {}
        out = {}
        for name, p in load_all().items():
            key = os.path.normcase(os.path.normpath(str(p.path)))
            if key not in by_path:
                by_path[key] = _count_unmerged(p.path)
            out[name] = by_path[key]
        _UNMERGED.update(map=out, at=time.monotonic())
    finally:
        _UNMERGED["busy"] = False


def unmerged() -> dict[str, int | None]:
    """프로젝트별 미병합 orch/ 브랜치 수. 처음 한 번은 그 자리에서 세고, 뒤로는 5분이 지나면 뒤에서 다시 세며 그동안 보관한 값을 준다."""
    with _UNMERGED_LOCK:
        first = _UNMERGED["at"] is None
        stale = first or time.monotonic() - _UNMERGED["at"] > UNMERGED_SEC
        start = stale and not _UNMERGED["busy"]
        if start:
            _UNMERGED["busy"] = True
    if start and first:
        _refresh_unmerged()
    elif start:
        threading.Thread(target=_refresh_unmerged, daemon=True).start()
    return _UNMERGED["map"]


# ----- 프로젝트 현황판(1안) -----
def _spark(c: dict) -> dict:
    return {"title": c.get("title") or "", "status": c.get("status") or "", "where": c.get("where") or c.get("state_text") or "",
            "score": c.get("score"), "target": c.get("target"), "direction": c.get("direction") or "", "base": c.get("base"), "first": c.get("first"),
            # 작은 그래프가 95% 구간과 목표 판정까지 그린다(261023-jipsa-38 6안)
            "rounds": [{"n": r.get("n"), "score": r.get("score"), "delta": r.get("delta"), "low": r.get("low"), "high": r.get("high"),
                        "adopt": bool(r.get("adopt")), "judge": r.get("judge") or "", "branch": r.get("branch") or ""} for r in c.get("rounds") or []],
            "branches": c.get("branches") or [],  # 아이디어 갈래 줄(261029-jipsa-10 1안)
            "final": (c.get("final") or {}).get("run_id") or "", "final_shown": (c.get("final") or {}).get("shown") or "",
            "pending": c.get("pending") or ""}  # 목표 미정 칸 이름. 카드가 목표 미정으로 보인다(261026-jipsa-11)


_PLAN_ITEM = re.compile(r"^(?:#+\s*)?(\d+)\s*(?:[.)]|단계\s*[:.]?)\s*(.+)$")  # '1. 이름. 설명'이나 '## 1단계 이름'
_STEP_EVT = re.compile(r"^(?:[-*]\s+|#+\s*)?(?:(\d{1,2}):(\d{2})\s+)?(\d+(?:\s*(?:,|~|-|와|과)\s*\d+)*)\s*단계(.*)$")
_STEP_START = re.compile(r"시작|진행 ?중|하는 중|대기|실패|막힘|막혔|보류|중단")


def _step_name(text: str) -> str:
    """계획 줄에서 단계 이름만 둔다. 괄호 속 글을 빼고 첫 마침표나 쌍점 앞까지다. 글을 지어내지 않는다."""
    t = re.sub(r"\s*\([^)]*\)", "", text.replace("**", "").replace("`", "")).strip()
    return re.split(r"\.\s|[:：]|\s—\s", t + " ", maxsplit=1)[0].strip().rstrip(".")


def _steps(run_id: str, started: str) -> dict:
    """진행 중 실행 안의 단계(261029-jipsa-47). 끝난 단계, 지금 단계, 다음 단계의 이름과 시각이다. 모르면 빈 값이고 화면이 --로 보인다.
    단계 이름은 마지막 시도의 계획 파일 번호 목록이다. 어느 단계까지 끝났는지는 진행 메모에서 줄 머리가 'N단계'인 줄로 읽는다(시각 'HH:MM'이 앞에 붙으면 그 시각).
    끝, 마쳤, 완료가 든 줄은 끝이고, 시작, 진행 중, 대기, 실패, 막힘이 든 줄은 그 단계를 하는 중이며(시작을 적은 마지막 단계가 지금 단계), 나머지는 단계 하나를 끝내고 적는 규칙(RULES 크기와 시간)대로 끝으로 본다. 진행 메모가 비었으면 1단계를 하는 중이고, 메모가 있는데 단계 줄이 없으면 모른다."""
    blank = {"done": None, "now": None, "next": None}
    try:
        n = max(int(d[8:]) for d in os.listdir(RUNS / run_id) if re.fullmatch(r"attempt-\d+", d))
        att = RUNS / run_id / f"attempt-{n}"
        plan = (att / "plan.md").read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, ValueError):
        return blank
    names: dict[int, str] = {}
    for ln in plan:  # 들여 쓴 하위 목록은 단계가 아니다
        m = _PLAN_ITEM.match(ln.rstrip())
        if m and not ln[:1].isspace() and int(m.group(1)) not in names:
            names[int(m.group(1))] = _step_name(m.group(2))
    if not names:
        return blank
    try:
        prog = (att / "progress.md").read_text(encoding="utf-8", errors="replace").splitlines()
        mtime = datetime.fromtimestamp((att / "progress.md").stat().st_mtime)
    except OSError:
        prog, mtime = [], None
    base = parse_iso(started) if started else None
    done_at: dict[int, str] = {}
    start_at: dict[int, str] = {}
    for ln in prog:
        m = _STEP_EVT.match(ln.strip())
        if not m:
            continue
        at, tail = "", re.search(r"\((\d{1,2}):(\d{2})\)", m.group(4))  # '## 1단계 시작 (21:07)' 꼴도 받는다
        hm = (m.group(1), m.group(2)) if m.group(1) else tail.groups() if tail else None
        if hm and base and int(hm[0]) < 24 and int(hm[1]) < 60:
            t = base.replace(hour=int(hm[0]), minute=int(hm[1]), second=0)
            if t < base - timedelta(minutes=5):  # 자정을 넘긴 시각
                t += timedelta(days=1)
            if mtime and t > mtime:  # 적은 시각이 메모를 고친 시각보다 늦으면 고친 시각이다. 22:39에 '- 23:05'를 적은 실행이 있었다
                t = mtime.replace(microsecond=0)
            at = t.isoformat(timespec="seconds")
        nums = [int(x) for x in re.findall(r"\d+", m.group(3))]
        if re.match(r"\d+\s*(?:~|-)\s*\d+", m.group(3)) and len(nums) == 2:
            nums = list(range(nums[0], nums[1] + 1))
        for k in (x for x in nums if x in names):
            if re.search(r"끝|마쳤|마침|완료", m.group(4)):
                done_at[k] = at or done_at.get(k, "")
            elif _STEP_START.search(m.group(4)):  # 시작, 대기, 실패, 막힘은 끝이 아니다. 그 단계를 하는 중이다
                start_at.setdefault(k, at)
            else:
                done_at[k] = at or done_at.get(k, "")
    order = sorted(names)
    if not done_at and not start_at and any(ln.strip() and not ln.startswith("#") for ln in prog):
        return blank  # 메모는 있는데 단계를 적지 않았다. 지어내지 않는다
    last = max(done_at) if done_at else None
    rest = [k for k in order if k not in done_at and (last is None or k > last)]
    begun = [k for k in rest if k in start_at]
    if begun:  # 시작을 적은 단계가 있으면 그중 마지막이 지금 단계다. 1단계 끝 없이 3단계 시작만 적어도 3단계다
        rest = rest[rest.index(begun[-1]):]
    cur = rest[0] if rest else None
    if cur is not None and start_at.get(cur):
        cur_at = start_at[cur]
    elif cur is not None and last is not None and cur == next((k for k in order if k > last), None):
        cur_at = done_at[last]  # 바로 앞 단계가 끝난 때 시작했다
    elif cur == order[0] and not done_at:
        cur_at = started
    else:
        cur_at = ""
    nxt = rest[1] if len(rest) > 1 else None
    return {"done": {"no": last, "name": names[last], "at": done_at[last]} if last is not None else None,
            "now": {"no": cur, "name": names[cur], "at": cur_at} if cur is not None else None,
            "next": {"no": nxt, "name": names[nxt]} if nxt is not None else None}


def _is_cycle(run_id: str, parent_of: dict) -> bool:
    seen, cur = set(), run_id
    while cur in parent_of:
        if cur in seen:
            return True
        seen.add(cur); cur = parent_of[cur]
    return False


def _recent_done(mine: list[dict], since: str) -> list[dict]:
    """프로젝트의 끝난(완료, 실패) 실행 가운데 마감이 since 뒤인 것. 끝난 순(최근 먼저)이고, 다른 실행에 넣은 답으로 시작한 실행은
    할 일 줄(parent_item)이 같은 부모 실행 바로 뒤에 두며 parent에 그 실행ID를 적는다. 부모가 목록에 없으면 제 자리다(261031-jipsa-08)."""
    done = sorted((m for m in mine if m.get("finished") and m.get("status") in ("완료", "실패") and str(m["finished"]) >= since),
                  key=lambda m: str(m["finished"]), reverse=True)
    by_key = {str(m.get("queue_key") or ""): m["run_id"] for m in done if m.get("queue_key")}
    parent_of = {m["run_id"]: by_key.get(str(m.get("parent_item") or ""), "") for m in done}
    parent_of = {k: v for k, v in parent_of.items() if v and v != k}
    parent_of = {k: v for k, v in parent_of.items() if not _is_cycle(k, parent_of)}  # 서로를 부모로 적은 기록은 둘 다 최상위다
    kids: dict[str, list[dict]] = {}
    for m in done:
        if m["run_id"] in parent_of:
            kids.setdefault(parent_of[m["run_id"]], []).append(m)
    row = lambda m: {"run_id": m["run_id"], "title": m.get("title") or "", "label": m.get("label") or "", "status": m.get("status"),  # noqa: E731
                     "finished": m["finished"], "answer": str(m.get("answer") or ""), "parent": parent_of.get(m["run_id"], ""),
                     # 초안 실행 표식(261031-jipsa-10). 초안인데 미리보기 주소가 비면 화면이 주소 없음을 붙인다
                     "draft": bool(m.get("draft")), "preview": bool(preview_url(m))}
    out: list[dict] = []

    def emit(m: dict) -> None:  # 부모 뒤에 자식, 그 뒤에 손자다. 순환이 생겨도 한 번만 넣는다
        if any(r["run_id"] == m["run_id"] for r in out):
            return
        out.append(row(m))
        for k in kids.get(m["run_id"], []):
            emit(k)

    for m in done:
        if m["run_id"] not in parent_of:
            emit(m)
    for m in done:  # 부모가 목록 밖이거나 순환이면 제 자리다
        emit(m)
    return out


def board(metas: list[dict], cycles: list[dict]) -> dict:
    """프로젝트마다 카드 하나. 진행 중, 할 일, 미병합 브랜치 수, 목표 cycle, 최근 결과, 다음 할 일이다.
    확인 필요 수는 화면이 머리의 확인 필요 큐에서 프로젝트별로 센다(머리 숫자와 같은 목록).
    할 일 수와 다음 할 일은 할 일 파일(Auto 절과 할 일 절)의 그 프로젝트 줄이고, 작은 그래프는 Auto 절 Cycle 목표의 값이다(cycles, todo_cycles).
    옛 주간 계획 항목과 Auto 목표 큐는 261025-jipsa-42에서 떼었고, 남은 목표 큐 칸은 261026-jipsa-07에서 뗐다."""
    from scheduler import todo as todofile
    from scheduler.registry import load_all

    try:
        trows, _, _ = todofile.load()
    except (OSError, ValueError):
        trows = []

    reg = load_all()
    um = unmerged()
    names = [n for n in reg if n != "misc"]
    # 등록부에서 뺀 프로젝트는 지난 실행 기록이 남아도 카드와 쉬는 목록에서 뺀다. 진행 중인 실행이 있을 때만 보인다(261026-jipsa-21).
    names += sorted({m.get("project") for m in metas if m.get("project") and m.get("status") == "진행 중"} - set(names) - {"misc"})
    week = (now() - timedelta(days=7)).isoformat(timespec="seconds")
    day = (now() - timedelta(hours=24)).isoformat(timespec="seconds")
    cards, idle = [], []
    for p in names:
        mine = [m for m in metas if m.get("project") == p and not str(m["run_id"]).startswith("session-")]
        running = sorted((m for m in mine if m.get("status") == "진행 중"), key=lambda m: m["started"])
        fin = max((m for m in mine if m.get("finished") and m.get("status") != "진행 중"), key=lambda m: m["finished"], default=None)
        done24 = _recent_done(mine, day)
        opens = [t for t in trows if t.project == p]
        cyc = [c for c in cycles if c.get("project") == p and c.get("status") != "거절"]
        cyc.sort(key=lambda c: c.get("status") == "끝")  # 도는 목표가 먼저다
        spark = cyc[0] if cyc else None
        card = {"name": p, "running": [{"run_id": m["run_id"], "title": m.get("title") or "", "started": m["started"],
                                         "stall_min": record.stall_of(m["run_id"]), "executor": m.get("executor") or "",
                                         "agent": m.get("agent") or "", "steps": _steps(m["run_id"], m["started"])} for m in running],
                "todo_n": len(opens), "next": opens[0].text if opens else "", "unmerged": um.get(p),
                "cycle": _spark(spark) if spark else None,
                "last": {"run_id": fin["run_id"], "title": fin.get("title") or "", "label": fin.get("label") or "", "status": fin.get("status"),
                         "finished": fin["finished"]} if fin else None,
                # 24시간 안에 끝난 실행(261031-jipsa-08). 확인을 거친 완료는 확인 필요 목록에서 빠지고 카드에 자리가 없어 답으로 낳은 초안이 보이지 않았다.
                # 끝난 순이고 다른 실행의 답으로 시작한 실행(parent)은 그 부모 바로 뒤다. 화면은 세 건까지 그린다
                "recent": done24}
        recent = bool(fin and fin["finished"] >= week)
        if running or opens or cyc or (um.get(p) or 0) or recent:
            cards.append(card)
        else:
            idle.append(p)
    # 오늘 끝난 일(261029-jipsa-44, 42 초안 구역 7): 현황판 카드 아래 두 열 표의 오른쪽이다. 최근 5건만 주고 전체 건수는 today_n이다
    today = now().date().isoformat()
    done = sorted((m for m in metas if str(m.get("finished") or "").startswith(today) and m.get("status") not in ("진행 중", None)
                   and not str(m["run_id"]).startswith("session-")), key=lambda m: m["finished"], reverse=True)
    today_rows = [{"run_id": m["run_id"], "project": m.get("project") or "", "title": m.get("title") or "", "label": m.get("label") or "",
                   "summary": m.get("summary") or "", "status": m.get("status"), "finished": m["finished"],
                   "draft": bool(m.get("draft")), "preview": bool(preview_url(m))} for m in done[:5]]
    return {"projects": cards, "idle": idle, "today": today_rows, "today_n": len(done)}


TABS = ("board", "timeline", "cue", "todo")
_HEAD: dict = {"at": 0.0, "val": None}


def head_line(metas: list[dict]) -> dict:
    """머리 줄 한 줄 현황(261023-jipsa-41). 환경 탭을 없애고 Claude와 Codex 사용률, GPU, RAM, 이상 경고만 탭마다 싣는다.
    사용률은 쓴 %이고 초기화 시각과 측정 시각을 같이 준다. 스케줄러, Slack 웹훅은 이상할 때만 alerts에 든다. 15초 보관한다."""
    if _HEAD["val"] is not None and time.time() - _HEAD["at"] < 15:
        return _HEAD["val"]
    since = now() - timedelta(hours=24)
    try:
        cw = codex_window_state([m for m in metas if parse_iso(m["started"]) >= since])
    except Exception:  # noqa: BLE001 - 사용 창을 못 읽어도 머리는 그린다
        cw = {}
    try:
        lw = claude_window.usage()
    except Exception:  # noqa: BLE001
        lw = {}
    try:
        res = resources.summary()
    except Exception:  # noqa: BLE001
        res = {}
    measured = cw.get("five_pct") is not None
    seen = parse_iso(cw["usage_seen"]) if measured and cw.get("usage_seen") else None
    alerts = []
    sch = scheduler_status()
    sw = sch["watch"]
    if sw.get("stopped"):
        st = sw["stopped"]
        if st.get("by"):
            alerts.append({"text": "스케줄러 꺼짐", "title": f"{st['by']}에서 껐다. 감시가 다시 띄우지 않는다. {st['by']}에서 켠다"})
        else:
            alerts.append({"text": "스케줄러 꺼짐", "title": f"{st.get('window')}분 안에 {st.get('count')}번 꺼져 다시 띄우기를 멈췄다. 원인을 고친 뒤 대시보드를 다시 켜거나 uv run jipsa run으로 켠다"
                       + "".join(f"\n{line}" for line in st.get("log") or [])})
    elif not sch["running"] and sch["alive"]:
        alerts.append({"text": f"스케줄러 {int((sch['hb_age'] or 0) // 60)}분 멈춤", "title": "심장박동이 멈췄다. 프로세스는 있다"})
    elif not sch["running"]:
        alerts.append({"text": "스케줄러 꺼짐", "title": f"{sw.get('interval') or 30}초 안에 감시가 띄운다" if sw.get("watching") else "uv run jipsa web으로 켠다"})
    if not slack.is_available():  # 환경 변수 다음에 비밀값 파일을 본다. 스킬에서 저장한 직후에도 맞다
        alerts.append({"text": "웹훅 없음", "title": "Slack 웹훅이 없다. 보고는 파일에만 남는다"})
    ram_total, ram_free = res.get("ram_total_gb"), res.get("ram_free_gb")
    val = {"claude": {"five": lw.get("five"), "week": lw.get("week"), "five_reset": lw.get("five_reset") or "", "week_reset": lw.get("week_reset") or "",
                      "cleared": bool(lw.get("cleared")), "week_cleared": bool(lw.get("week_cleared")), "fresh": bool(lw.get("fresh")), "seen": lw.get("seen")},
           # Codex 실측이 없으면 호출 수 어림을 5시간 값으로 쓰고 주간은 비운다. 1시간 넘은 실측은 오래된 값이다
           "codex": {"five": cw.get("five_pct") if measured else cw.get("pct"), "week": cw.get("week_pct") if measured else None,
                     "five_reset": (cw.get("five_reset_iso") if measured else cw.get("reset_iso")) or "", "week_reset": cw.get("week_reset_iso") or "",
                     "cleared": bool(cw.get("five_cleared")), "week_cleared": bool(cw.get("week_cleared")), "measured": measured,
                     "fresh": not measured or (seen is not None and now() - seen <= timedelta(hours=1)), "seen": cw.get("usage_seen"),
                     "calls": cw.get("calls"), "cap": cw.get("cap"), "hidden": not cw.get("shown", True)},
           "gpu": {"used": res.get("gpu_used_gb"), "total": res.get("gpu_total_gb"), "ok": bool(res.get("gpu_ok"))},
           "ram": {"used": round(ram_total - ram_free, 1) if ram_total and ram_free is not None else None, "total": ram_total},
           "ollama": res.get("ollama"), "alerts": alerts,
           # GPU 장부(261026-jipsa-26): 막대의 일별 색칸(장부 줄, 장부 밖, 예약, 남은 자리)과 대기열
           "ledger": res.get("ledger") or {}}
    _HEAD.update(at=time.time(), val=val)
    return val


# ----- 할 일 파일과 Auto 목록(261025-jipsa-29, TODO 구현 6가 단계) -----
# TODO 탭의 할 일 칸은 jipsa todo가 찍는 줄 그대로다. 서버가 같은 함수로 줄을 만들고 화면은 그리기만 한다. 자원과 대기열 상자와
# 도는 Cycle 줄은 lanes_view가 준다(261029-jipsa-17 다안 3차, Auto 칸은 뗐다).
# 넣기 줄과 단추는 명령 요청 하나(POST /api/command)로 같은 명령 함수(cli.cmd_todo)를 돌리고 찍은 줄을 돌려준다.
_ITEM_LINE = re.compile(r"^\s+(\d+)\. ")
# 화면이 보낼 수 있는 명령. 이름 -> (명령 줄의 첫 낱말, 동작, 줄을 고르는지). 이 밖의 이름은 거절하고 셸은 부르지 않는다
COMMANDS = {
    "todo add": ("todo", "add", False), "todo rm": ("todo", "rm", True),
    # 메모 칸(261025-jipsa-36). 줄을 고르는 값이 "memo"면 key는 메모 글이고 서버가 그때의 메모 번호(m1)로 바꾼다
    "todo memo": ("todo", "memo", False), "todo memo-rm": ("todo", "memo-rm", "memo"), "todo up": ("todo", "up", "memo"),
    # cycle 칸 바꾸기(261025-jipsa-49). key로 고른 줄에 metric, target, dir, cap을 붙이고 off가 참이면 비운다
    "todo cycle": ("todo", "cycle", True),
    # 시키기(261026-jipsa-12). key로 고른 줄 하나를 다음 주기에 시작한다. Cycle은 start(지금이나 HH:MM)와 until(마감)을 받는다(261029-jipsa-17)
    "todo run": ("todo", "run", True),
    # 도는 Cycle 멈추기와 마감 고치기(261029-jipsa-17). 멈추면 돌던 단계를 마치고 할 일로 돌아가며 다시 시키면 잇는다
    "todo stop": ("todo", "stop", True), "todo until": ("todo", "until", True),
    # 사람 피드백(261026-jipsa-19). key로 고른 Cycle 줄에 text를 원문 그대로 넣는다
    "todo feedback": ("todo", "feedback", True),
}
_COMMAND_LOCK = threading.Lock()  # 명령 출력을 잡는 동안 다른 요청이 표준 출력을 섞지 않게 한 번에 하나만 돌린다


def _cells(line: str, start: int, it) -> dict | None:
    """번호 줄을 칸(프로젝트, 할 일, 기준, cycle, 한도, 상태)으로 나눈다. 칸은 명령 줄의 글을 자른 것이라 " | "로 이으면 줄과 같다.
    상태는 jipsa auto 줄에서 할 일 본문 뒤에 붙은 글(차례, Cycle 진행, GPU)이다. 본문이 줄과 맞지 않으면 None이고 화면은 줄 글을 그대로 그린다."""
    body, own = line[start:], it.line()
    if body != own and not body.startswith(own + " | "):
        return None
    parts = own.split(" | ")  # 프로젝트와 문장, 칸에는 세로 막대가 들어가지 않는다(할 일 파일이 막대로 칸을 나눈다)
    cells = {"no": it.no, "project": parts[0], "text": parts[1], "criteria": "", "cycle": "", "limits": "", "status": body[len(own) + 3:]}
    rest = parts[2:]
    for name, has in (("criteria", it.criteria), ("cycle", it.cycle), ("limits", it.limits)):
        if has and rest:
            cells[name] = rest.pop(0)
    return cells if not rest else None


def _rows(lines: list[str], by_no: dict) -> list[dict]:
    """줄마다 글과, 번호 줄이면 그 할 일(번호, key, 절)과 칸을 붙인다. 단추는 key를 보내고 서버가 그때 번호로 바꾼다.
    화면은 칸을 표로 그린다(261025-jipsa-33). 줄 차례와 칸 글은 명령 출력과 같다."""
    out = []
    for line in lines:
        m = _ITEM_LINE.match(line)
        it = by_no.get(int(m.group(1))) if m else None
        row: dict = {"text": line}
        if it:
            row["item"] = {"no": it.no, "key": it.key, "section": it.section}
            cells = _cells(line, m.end(), it)
            if cells:
                row["cells"] = cells
        out.append(row)
    return out


def _todo_file_n() -> int | None:
    from scheduler import todo as todofile

    try:
        return len(todofile.load()[0])
    except Exception:  # noqa: BLE001 - 할 일 파일 오류로 머리 숫자를 멈추지 않는다
        return None


def _when(dt: datetime | None) -> str:
    return dt.isoformat(timespec="seconds") if dt else ""


def _eta(rows: list[dict], key: str, led: dict, leases: list[dict], t: datetime) -> str:
    """대기열 한 줄의 예상 대기. 도는 장부 줄이 끝 예상 시각(만료 - 10분) 순으로 내놓는 GPU와 RAM을 더해 필요량에 닿는 때다.
    앞 줄이 먼저 가져갈 몫을 빼고 센다. 셈은 어림이고 화면 글에만 쓴다."""
    free = float(led.get("free") or 0)
    ram = float(((led.get("ram") or {}).get("free")) or 0)
    rel = sorted(((parse_iso(x["expires"]) - timedelta(minutes=10), float(x.get("amount_gb") or 0) if not x.get("watch") else 0.0,
                   float(x.get("ram_gb") or 0)) for x in leases if x.get("expires")), key=lambda z: z[0])
    when = None
    for r in rows:
        need, rneed = float(r.get("need") or 0), float(r.get("ram") or 0)
        while not (need <= free and rneed <= ram) and rel:
            end, g, m = rel.pop(0)
            free, ram, when = free + g, ram + m, max(end, t)
        if not (need <= free and rneed <= ram):
            return "도는 일이 다 끝난 뒤"
        if r["key"] == key:
            return f"약 {int((when - t).total_seconds() // 60)}분({when:%H:%M})" if when else "다음 주기"
        free, ram = free - need, ram - rneed
    return ""


def lanes_view(reg: dict) -> dict:
    """TODO 탭의 자원과 대기열 상자, 도는 Cycle 줄(261029-jipsa-17 다안 3차). 시킨 Cycle 요청마다 진척, 회차별 값, 갈래, 시작과 마감,
    끝 예상, GPU와 RAM 예약을 주고, 대기열은 줄마다 필요량, 기다린 시간, 사유, 예상 대기를 준다.
    예약(scheduled)은 시작 시각 전의 요청이고 Cycle과 Cycle이 아닌 줄을 함께 담는다(261029-jipsa-20)."""
    from scheduler import auto
    from scheduler import todo as todofile

    t = now()
    items = {it.key: it for it in todofile.load(projects=set(reg))[0]}
    led = resources.ledger_summary()
    leases = resources.leases()
    lanes = auto.lane_rows()
    reqs = auto.run_requests()
    by_req = {r["key"]: r for r in reqs}
    cycles, scheduled = [], []
    for req in reqs:
        it = items.get(req["key"])
        if it is None:
            continue
        begin, cut = auto.req_start(req), auto.req_cutoff(req)
        if not it.cycle:  # Cycle이 아닌 줄은 예약만 띠에 보인다. 시작하면 줄이 할 일에서 빠지고 현황판에 보인다
            if begin and t < begin:
                scheduled.append({"key": it.key, "no": it.no, "project": it.project, "text": it.text, "cycle": False,
                                  "start": _when(begin), "cutoff": _when(cut)})
            continue
        c = auto.as_cycle(it)
        rec = cycle.load(c)
        sm = cycle.summary(c, rec, auto.run_mode(req), at=t)
        live = [r for r in lanes if r.get("todo_key") == it.key]
        mine = [x for x in leases if x.get("owner") == it.key]
        sig = next((x["signal"] for x in mine if x.get("signal") and not x["signal"].get("observed")), None)
        rounds = sm.get("rounds") or []
        done = [r for r in rounds if r.get("judge")]
        avg = sum(r.get("minutes") or 0 for r in done) / len(done) if done else 0
        start_at = begin or parse_iso(req["since"])
        left = (cut - t).total_seconds() / 60
        est = t + timedelta(minutes=int(left // avg) * avg) if avg and left > 0 else cut
        fb = [e for e in cycle.feedback_entries(it.key) if e.get("text")][-3:]
        bs = sm.get("branches") or []
        last_branch = next((r.get("branch") for r in reversed(rounds) if r.get("branch")), "")
        row = {"key": it.key, "no": it.no, "project": it.project, "text": it.text, "note": auto.run_note(req), "state": req.get("state") or "",
               "where": sm.get("where") or sm.get("phase") or "", "paused": sm.get("paused") or "",
               "metric": sm.get("metric") or "", "target": sm.get("target"), "direction": sm.get("direction") or "이상",
               "score": sm.get("score"), "first": sm.get("first"), "base": sm.get("base"), "pending": sm.get("pending") or "",
               "rounds": [{"n": r["n"], "score": r.get("score"), "delta": r.get("delta"), "adopt": bool(r.get("adopt")), "judge": r.get("judge") or ""} for r in rounds],
               "branch": last_branch, "branch_open": sum(1 for b in bs if b.get("status") != cycle.CLOSED), "branch_closed": sum(1 for b in bs if b.get("status") == cycle.CLOSED),
               "start": _when(start_at), "cutoff": _when(cut), "est_end": _when(min(est, cut)), "stopped": bool(req.get("stopped")),
               "progress": max(0.0, min(1.0, (t - start_at).total_seconds() / max(1.0, (cut - start_at).total_seconds()))),
               "gpu": round(sum(float(x.get("amount_gb") or 0) for x in mine if not x.get("watch")), 1),
               "gpu_measured": next((r.get("measured") for r in led.get("rows") or [] if r.get("run") in {x.get("run") for x in mine}), None),
               "ram": round(sum(float(x.get("ram_gb") or 0) for x in mine), 1),
               "ram_measured": round(sum(float(x.get("ram_now") or 0) for x in mine), 1) if any(x.get("ram_now") is not None for x in mine) else None,
               "signal": {"kind": sig.get("kind"), "until": sig.get("until"), "waiting": bool(sig.get("waiting"))} if sig else None,
               "running": any(r["status"] == queue.RUNNING for r in live),
               "feedback": [{"at": e.get("at") or "", "text": str(e.get("text") or "")[:600]} for e in fb], "cycle": True}
        (scheduled if begin and t < begin and not live else cycles).append(row)
    scheduled.sort(key=lambda r: r["start"])  # 예약은 시작 시각 순이다
    q = led.get("queue") or []
    rows_by_key = {r["key"]: r for r in queue.load()}
    out_q = []
    for r in q:
        row = rows_by_key.get(r["key"]) or {}
        tk = row.get("todo_key") or r["key"]
        it = items.get(tk)
        out_q.append({"key": r["key"], "todo_key": tk, "no": it.no if it else None, "project": r.get("project") or "", "title": (it.text if it else r.get("title")) or "",
                      "cycle": bool(it and it.cycle) or bool(row.get("cycle")), "need": r.get("need") or 0, "ram": r.get("ram") or 0,
                      "since": r.get("since") or "", "why": r.get("why") or "", "eta": _eta(q, r["key"], led, leases, t),
                      "cutoff": _when(auto.req_cutoff(by_req[tk])) if tk in by_req else ""})
    singles = sum(1 for r in queue.load() if r["status"] == queue.RUNNING and not r.get("cycle") and not r.get("todo_plan"))
    return {"cap": auto.AUTO_CAP, "stop": "", "n": len(auto.auto_running()), "cycles": cycles, "queue": out_q, "scheduled": scheduled,
            "singles": singles, "gpu": {k: led.get(k) for k in ("total", "used", "leased", "outside", "reserve", "free", "ok", "rows", "over")}, "ram": led.get("ram") or {}}


def _cap() -> dict:
    from scheduler import auto

    try:
        return {"n": len(auto.auto_running()), "cap": auto.AUTO_CAP, "stop": "", "queue": len(resources.queue_rows())}
    except Exception:  # noqa: BLE001 - 머리 줄은 늘 그린다
        return {}


def _placing(items: list) -> list[dict]:
    """스케줄러에 넣는 중인 줄(261029-jipsa-49). Do로 시켰고 아직 첫 실행이 시작하지 않아 타임라인과 현황판에 없는 줄이다.
    세션에 보낸 Do는 begin이 줄을 열 때까지, 작업자 요청은 시킨 뒤 시작한 큐 줄(본 작업, 기준 정하기, Cycle 단계)이 생길 때까지다.
    시작 시각 전 예약은 위 띠의 예약에 있어 넣지 않는다. 실행이 시작되면 빠지므로 화면의 넣는 중 띠가 저절로 사라진다."""
    from scheduler import auto, record

    t = now()
    by_key = {it.key: it for it in items}
    started: dict[str, str] = {}  # 할 일 key마다 가장 늦게 시작한 큐 줄의 시작 시각
    for r in queue.load():
        k, s = r.get("todo_key"), str(r.get("started") or "")
        if k and s and s > started.get(k, ""):
            started[k] = s
    out = []
    for req in auto.run_requests():
        begin = auto.req_start(req)
        if begin and t < begin:
            continue
        since = str(req.get("at") or req.get("since") or "")
        if started.get(req["key"], "") >= since[:19]:
            continue
        it = by_key.get(req["key"])
        out.append({"key": req["key"], "project": req.get("project") or "", "text": req.get("text") or "", "cycle": bool(it and it.cycle),
                    "session": False, "note": auto.run_note(req), "at": since})
    for it in items:
        if it.key in {p["key"] for p in out}:
            continue
        sent = record.do_open(it.key)
        if sent:
            out.append({"key": it.key, "project": it.project, "text": it.text, "cycle": bool(it.cycle), "session": True,
                        "note": f"{auto.DO_TAG}. 세션이 받아 서브에이전트로 시작한다", "at": str(sent.get("ts") or "")})
    return out


def todo_view() -> dict:
    """TODO 탭의 할 일 칸(jipsa todo의 할 일 절 줄), 자원과 대기열 상자와 도는 Cycle 줄(lanes), 넣기 줄의 프로젝트 목록.
    시킨 줄(요청이 있는 줄)은 할 일 칸에서 빼고 위 띠에 보인다. 일회성 줄은 시키면 파일에서 빠지고 현황판에 보인다."""
    from scheduler import auto, cli
    from scheduler import todo as todofile
    from scheduler.registry import load_all

    reg = load_all()
    items, bad, exists = todofile.load(projects=set(reg))
    by_no = {it.no: it for it in items}
    asked = auto.run_keys()
    placing = _placing(items)
    sent = {p["key"] for p in placing if p["session"]}  # 세션에 보낸 Do 줄도 넣는 중 띠에만 보인다(261029-jipsa-49)
    rows = [r for r in _rows(cli.todo_lines((todofile.TODO,)), by_no)
            if not (r.get("item") and r["item"]["key"] in asked | sent) and not r["text"].startswith("도는 중: ")]
    for r in rows:
        it = by_no.get((r.get("item") or {}).get("no"))
        if it and it.cycle:  # 할 일 칸의 Cycle 줄은 회차 기록을 같이 준다. 마감으로 멈춘 줄은 다시 시키면 잇는 회차를 보인다
            c = auto.as_cycle(it)
            rec = cycle.load(c)
            r["cycle"] = {"rounds": [{"n": x["n"], "score": x.get("score"), "adopt": bool(x.get("adopt"))} for x in rec.get("rounds") or []],
                          "score": rec.get("score"), "paused": rec.get("paused") or "" if rec.get("status") != cycle.ENDED else "",
                          "ended": rec.get("status") == cycle.ENDED, "limits": it.limits}
    try:
        lanes = lanes_view(reg)
    except Exception as e:  # noqa: BLE001 - 띠를 못 그려도 할 일 칸은 그린다
        events.emit("error", where="lanes_view", error=str(e)[:300])
        lanes = {}
    return {"lanes": lanes, "todo": rows, "placing": placing,
            "projects": sorted(reg), "n": len(items), "bad": len(bad), "exists": exists,
            # 메모 칸의 줄. key는 메모 글이다. 단추가 key를 보내면 서버가 그때의 번호로 바꾼다(261025-jipsa-36)
            "memo": [{"no": m.no, "label": m.label, "text": m.text, "key": m.text} for m in todofile.memos()]}


def command(body: dict) -> dict:
    """명령 요청. name은 COMMANDS 가운데 하나다. 줄을 고르는 명령은 key(프로젝트::문장)를 받아 지금 번호로 바꿔 넘긴다.
    넣기는 project와 text, 켜기는 until(비우면 8시간)을 받는다. 돌려주는 out은 명령이 찍은 줄 그대로다."""
    import contextlib
    import io
    from argparse import Namespace

    from scheduler import cli
    from scheduler import todo as todofile

    name = re.sub(r"\s+", " ", str(body.get("name") or "")).strip()
    if name not in COMMANDS:
        return {"ok": False, "out": f"받지 않는 명령이다 ({name or '빈 이름'}). {', '.join(COMMANDS)} 가운데 하나다.", "view": todo_view()}
    head, action, pick = COMMANDS[name]
    words = action.split()
    fn = cli.cmd_todo
    buf = io.StringIO()
    # key를 번호로 바꾸는 조회와 명령을 한 잠금 안에서 한다. 조회 뒤 다른 요청이 줄을 옮겨 번호가 밀리는 틈을 막는다
    with _COMMAND_LOCK:
        if pick == "memo":  # 메모 지우기와 할 일로 올리기. 올리기는 project와 text(덧붙일 칸)를 받는다
            key = re.sub(r"\s+", " ", str(body.get("key") or "")).strip()
            hit = next((m for m in todofile.memos() if m.text == key), None)
            if hit is None:
                return {"ok": False, "out": f"메모가 없다 ({key or '빈 key'}). 목록이 바뀌었을 수 있어 새로 그렸다.", "view": todo_view()}
            words.append(hit.label)
            if action == "up":
                project, cells = str(body.get("project") or "").strip(), re.sub(r"\s+", " ", str(body.get("text") or "")).strip()
                words += [w for w in (project, f"| {cells}" if cells else "") if w]
        elif pick:
            key = str(body.get("key") or "")
            hit = next((it for it in todofile.load()[0] if it.key == key), None)
            if hit is None:
                return {"ok": False, "out": f"줄이 없다 ({key or '빈 key'}). 목록이 바뀌었을 수 있어 새로 그렸다.", "view": todo_view()}
            words.append(str(hit.no))
            if action == "feedback":
                words += ["|", str(body.get("text") or "").strip()]
            if action == "run":  # Cycle의 시작(지금이나 HH:MM)과 마감. 빈 값은 붙이지 않는다
                for name in ("start", "until"):
                    v = re.sub(r"\s+", "", str(body.get(name) or ""))
                    if v and (name == "until" or v not in ("지금", "now")):
                        words += ["시작" if name == "start" else "마감", v]
            if action == "until":
                words.append(re.sub(r"\s+", "", str(body.get("until") or "")))
            if action == "cycle":  # 빈 칸은 붙이지 않는다. 지표나 목표값이 비면 목표 미정 Cycle이고 첫 분석이 정한다(261026-jipsa-11)
                if body.get("off"):
                    words.append("off")
                else:
                    cap = str(body.get("cap") or "").strip()
                    metric, target = (re.sub(r"[\s|]+", " ", str(body.get(k) or "")).strip() for k in ("metric", "target"))
                    # 숫자가 아닌 값이 지표 낱말로 읽혀 목표 미정이 되거나 상한이 사라지지 않게 먼저 막는다(261103-jipsa-07)
                    if target and not re.fullmatch(r"-?\d+(?:\.\d+)?\S*", target):
                        return {"ok": False, "out": f"바꾸지 못했다: 목표값은 숫자로 시작해야 한다({target}).", "cmd": "jipsa todo cycle", "view": todo_view()}
                    if cap and not cap.isdigit():
                        return {"ok": False, "out": f"바꾸지 못했다: 상한은 숫자여야 한다({cap}).", "cmd": "jipsa todo cycle", "view": todo_view()}
                    # 하나만 비면 빈 쪽에 미정을 적어 넘긴다. 지표 끝의 숫자가 목표값으로 읽히지 않게 한다
                    if metric and not target:
                        words += [metric, "목표", todofile.PENDING]
                    elif target and not metric:
                        words += ["지표", todofile.PENDING, target]
                    else:
                        words += [w for w in (metric, target) if w]
                    d = str(body.get("dir") or "").strip()
                    words += [d] if d in ("이상", "이하") else []  # 방향 자동이면 목표값이 있을 때 이상, 비면 분석이 정한다
                    words += ["상한", re.sub(r"\s+", "", cap)] if cap else []
                    words += ["도달하면", "끝"] if body.get("stop") else []  # 고치기 칸이 끝 조건을 지우지 않게 넘긴다(261103-jipsa-07)
        elif action == "add":
            project, text = str(body.get("project") or "").strip(), re.sub(r"\s+", " ", str(body.get("text") or "")).strip()
            words += [w for w in (project, text) if w]
        elif action == "memo":
            text = re.sub(r"\s+", " ", str(body.get("text") or "")).strip()
            if not text:  # 빈 글은 명령에서 메모 보기가 되므로 넣기 단추는 여기서 거절한다
                return {"ok": False, "out": "넣지 못했다: 메모 글이 비었다.", "cmd": "jipsa todo memo", "view": todo_view()}
            words.append(text)
        with contextlib.redirect_stdout(buf):
            code = fn(Namespace(words=words))
    return {"ok": code == 0, "code": code, "cmd": f"jipsa {head} {' '.join(words)}", "out": buf.getvalue().rstrip("\n"), "view": todo_view()}


def new_project(body: dict) -> dict:
    """TODO 탭의 프로젝트 만들기(261103-jipsa-07). 이름 하나만 받아 /jipsa-register의 무질문 등록과 같은 코드를 부른다.
    경로와 다른 칸은 요청에서 받지 않는다. 폴더는 늘 jipsa 저장소와 나란한 자리이고, 이름 검사가 상위 폴더 탈출을 막는다."""
    from scheduler import regedit

    name = body.get("name")
    with _COMMAND_LOCK:
        out = regedit.new_project({"name": name if isinstance(name, str) else ""}, cwd=ROOT)
    if not out["ok"]:
        return {"ok": False, "text": f"만들지 못했다: {out['why']}", "view": todo_view()}
    events.emit("registry_create", project=out["project"], by="web")
    text = f"{out['project']}를 등록했다. {regedit.made_text(out['made']['path'], out['made'])}."
    if out.get("note"):
        text += f" 주의: {out['note']}."
    return {"ok": True, "project": out["project"], "text": text, "view": todo_view()}


def state(tab: str = "") -> dict:
    """상태 응답. tab을 주면 머리(모드, 확인 필요 큐, 머리 숫자)와 그 탭이 그리는 값만 준다(261023-jipsa-37 2안).
    전에는 모든 칸의 값과 실행 사건 전부를 한 번에 주어 4.5MB를 15초마다 받았다. tab이 없으면 모든 탭의 값을 준다."""
    tab = "board" if tab == "env" else tab if tab in TABS else ""  # 옛 환경 탭 주소는 현황판으로 받는다
    want = (lambda *t: True) if not tab else (lambda *t: tab in t)
    mode = modes.get()
    cut = modes.cutoff_for(mode) if mode["mode"] == modes.UNATTENDED else None
    metas = _metas()
    conf = confirm.view()
    pend = queue.pending()
    today = now().date().isoformat()
    out = {
        "tab": tab, "now": now_iso(), "server": SERVER_STARTED, "web": web_stamp(), "cutoff_time": f"{CUTOFF:%H:%M}", "cutoff": cut.isoformat(timespec="seconds") if cut else None,
        "mode": mode, "counts": queue.counts(), "pending": pend, "hold": [r for r in queue.load() if r["status"] == queue.HOLD],
        "slack": slack.is_available(), "slack_on": slack.is_enabled(), "confirm": conf,
        "cue": cue_queue(metas, conf, pend),
        "running": sum(1 for m in metas if m.get("status") == "진행 중" and not str(m["run_id"]).startswith("session-")),
        "today_done": sum(1 for m in metas if m.get("status") == "완료" and str(m.get("finished") or "").startswith(today) and not str(m["run_id"]).startswith("session-")),
        "todo_file_n": _todo_file_n(),  # TODO 탭 숫자. 할 일 파일의 줄 수다(261025-jipsa-29)
        "cap": _cap(),  # 머리 줄 동시 Cycle n/상한과 GPU 대기 수(261029-jipsa-17)
        # 머리 상태창(261023-jipsa-38): 진행 중인 실행 한 줄씩과 멈춘 분. 사용 창과 자원은 머리 줄 한 줄 현황이다(261023-jipsa-41)
        "live": [{"run_id": m["run_id"], "project": m.get("project") or "", "title": m.get("title") or "", "started": m["started"],
                  "stall_min": record.stall_of(m["run_id"])}
                 for m in sorted(metas, key=lambda m: m["started"]) if m.get("status") == "진행 중" and not str(m["run_id"]).startswith("session-")],
        "head": head_line(metas),
    }
    cycles = todo_cycles(mode) if want("board", "timeline") else []
    if want("board"):
        out["board"] = board(metas, cycles)
    if want("timeline"):
        since = now() - timedelta(hours=24)
        # 확인 필요 큐의 실행은 24시간 밖이어도 그린다. 막대가 왼쪽 끝에 짧게 붙는다
        cue_ids = {r["run_id"] for r in out["cue"]}
        out["runs"] = _runs(lambda m: parse_iso(m["started"]) >= since or m.get("status") == "진행 중" or m["run_id"] in cue_ids, events.read_all(), metas, compact=True)
    if want("timeline"):
        out["scope"] = {"cycles": cycles}  # 타임라인 목표 줄. 할 일 파일 Auto 절 Cycle 목표의 요약이다(todo_cycles)
    if want("todo"):
        out["todofile"] = todo_view()  # runs 정리 칸은 할 일 탭에서 뗐다(261029-jipsa-20). 설정과 미리 보기는 jipsa runs-clean이다
    return out


def day(date: str) -> dict:
    if date == "demo":
        return demo()
    runs = _runs(lambda m: m.get("report_date") == date)
    return {"date": date, "cutoff_time": f"{CUTOFF:%H:%M}", "runs": runs}


def runs_list(limit: int = 100) -> list[dict]:
    """지난 작업 목록. 이벤트 없이 meta만 준다(시작 역순)."""
    return [{k: m.get(k) for k in META_KEYS} for m in record.list_runs(limit=limit)]


def run_detail(run_id: str) -> dict:
    """결과지 본문과 meta. 결과지가 없으면 그 자리에서 만든다."""
    meta = record.meta_of(run_id)
    if not meta:
        return {"error": f"runs/{run_id}가 없다"}
    sheet_path = RUNS / run_id / "result.md"
    if not sheet_path.exists() or meta.get("status") == "진행 중":
        text = record.sheet(meta)
    else:
        text = sheet_path.read_text(encoding="utf-8")
    # 끝난 실행도 선택지나 정할 것이 있으면 답 칸이 열린다. 넣은 답은 answered로 보여 준다
    # 단추는 고를 안에만 두고(1안, 2안) 나머지 정할 것은 글자로 보인다
    answered = {k: meta.get(k) for k in ("answer", "answered_at", "answered_after")} if meta.get("answer") else None
    if answered:
        answered["images"] = answer_images(meta.get("answer") or "")  # 답 표시의 [Image #N]을 눌러 그림을 연다
        answered["route"] = record.answer_route(run_id)  # 그 답이 지금 어디에 있는지. 새로 고쳐도 같은 줄을 보인다(261103-jipsa-08)
    answerable = record.answerable(meta)
    choices, notes = record.choices(meta) if answerable else ([], [])
    return {"meta": {**{k: meta.get(k) for k in META_KEYS}, "preview_url": preview_url(meta), "options_auto": bool(meta.get("options_auto"))},
            "sheet": text, "events": _run_events(run_id), "base": record.report_base(run_id), "shown": confirm.shown(meta),  # 서랍 머리 배지가 쓰는 판정. 상단 수와 같은 기준이다
            "answerable": answerable, "answered": answered, "choices": choices, "notes": notes}


def report_text(date: str) -> dict:
    """그날 보고를 기록에서 다시 만들어 파일에 쓰고 돌려준다. 지운 기록이 남지 않게 늘 다시 만든다."""
    path = report.write(date)
    return {"date": date, "text": path.read_text(encoding="utf-8")}


# 답 칸에 붙인 그림. 서버가 이름을 정해 runs/<실행>/answers/에 둔다. 실행 기록을 지우면 같이 지워진다(261029-jipsa-23)
IMAGE_MAX = 10 * 1024 * 1024
_IMAGE_KINDS = ((b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpg"), (b"GIF87a", "gif"), (b"GIF89a", "gif"))
_IMAGE_NAME = re.compile(r"^\d{6}-[0-9a-f]{8}\.(?:png|jpg|gif|webp)$")
_IMAGE_LINE = re.compile(r"^\[Image #(\d+)\] (\S.*)$")


def image_kind(data: bytes) -> str:
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return next((ext for sig, ext in _IMAGE_KINDS if data.startswith(sig)), "")


def upload_image(run_id: str, data: bytes) -> dict:
    """답 칸에 붙인 그림 하나를 저장한다. 형식은 머리 서명으로만 본다. 그림으로 읽히는지는 올리기 전에 브라우저가 한 번 해독해 본다."""
    if not re.fullmatch(r"[0-9A-Za-z_-]+", run_id or "") or not (RUNS / run_id / "meta.json").is_file():
        return {"ok": False, "why": "기록이 없는 실행ID"}
    ext = image_kind(data)
    if not ext:
        return {"ok": False, "why": "PNG, JPEG, GIF, WebP가 아니다"}
    folder = RUNS / run_id / "answers"
    folder.mkdir(parents=True, exist_ok=True)
    import hashlib

    name = f"{now():%H%M%S}-{hashlib.sha1(data).hexdigest()[:8]}.{ext}"
    (folder / name).write_bytes(data)
    events.emit("answer_image", run=run_id, name=name, bytes=len(data))
    return {"ok": True, "name": name, "url": f"/runs/{quote(run_id)}/answers/{name}", "bytes": len(data)}


def image_lines(run_id: str, text: str, images) -> str:
    """답 글에 남은 [Image #N]마다 저장 경로 줄을 끝에 붙인다. 받은편지함, 세션 안내문, 작업자 답이 모두 이 글을 받으므로 받는 쪽이 경로로 그림을 연다.
    글에서 표시 글자를 지운 그림과 이 실행의 answers/에 없는 이름은 붙이지 않는다."""
    lines = []
    for im in images if isinstance(images, list) else []:
        try:
            n, name = int(im.get("n")), str(im.get("name") or "")
        except (AttributeError, TypeError, ValueError):
            continue
        path = RUNS / run_id / "answers" / name
        if f"[Image #{n}]" in text and _IMAGE_NAME.match(name) and path.is_file():
            lines.append(f"[Image #{n}] {str(path.resolve()).replace(chr(92), '/')}")
    return text + ("\n\n" + "\n".join(lines) if lines else "")


def answer_images(text: str) -> list[dict]:
    """넣은 답 끝의 그림 경로 줄을 결과지 화면이 열 주소로 바꾼다."""
    out = []
    for line in (text or "").splitlines():
        m = _IMAGE_LINE.match(line.strip())
        if m:
            url = _local_runs_url(m.group(2))
            if url.startswith("/runs/"):
                out.append({"n": int(m.group(1)), "path": m.group(2), "url": url})
    return out


def answer(run_id: str, text: str, images=None) -> dict:
    if images:
        text = image_lines(run_id, text, images)
    out = record.answer(run_id, text)
    if out.get("ok"):
        events.emit("answer_by", run=run_id, by="web")
        out["confirm"] = confirm.view()  # 답을 넣으며 적은 확인을 같이 돌려준다. 상태 전체를 받는 데 10초쯤 걸려 그 사이 화면이 확인 필요로 남았다(261022-jipsa-59)
    return out


def dates() -> list[str]:
    out = set()
    for d in RUNS.glob("*"):
        meta = _read_meta(d)
        if meta and meta.get("report_date"):
            out.add(meta["report_date"])
    return sorted(out, reverse=True)


def demo() -> dict:
    """화면을 미리 보기 위한 가짜 하루. 실제 기록이 아니다."""
    rnd = random.Random(7)
    base = datetime.combine(now().date(), datetime.min.time()).replace(hour=22, minute=10) - timedelta(days=1)
    tools = ["Read weekly_prompts.py", "Grep 표본", "Edit weekly.py", "Bash uv run python -m src.tasks.weekly --draft", "Read AGENTS.md",
             "Bash git status", "Write progress.md", "Agent Explore 표본 위치 찾기", "Read llm.py", "Bash python hello.py"]
    specs = [
        ("example_app", "설정 화면 검증 추가", "code", "확인 필요", 41, 90, 3, 0, ["설정 파일 쓰기 금지에 걸림"]),
        ("web_api", "휴일 판정 정리", "code", "실패", 90, 90, 6, 1, []),
        ("game_ai", "기보 검증 재실행", "code", "완료", 55, 90, 3, 0, []),
        ("vision_lab", "8B 라벨 실험", "experiment", "진행 중", 70, 180, 2, 0, []),
    ]
    runs = []
    t = base
    for i, (proj, title, kind, status, used, limit, segs, retries, _) in enumerate(specs):
        rid = f"{base:%y%m%d}-{proj}-{i + 1:02d}"
        start = t + timedelta(minutes=rnd.randint(0, 25))
        evs = [{"ts": start.isoformat(timespec="seconds"), "kind": "run_start"}]
        cur = start
        attempt = 1
        for a in range(retries + 1):
            evs.append({"ts": cur.isoformat(timespec="seconds"), "kind": "stage_start", "attempt": attempt, "stage": "run"})
            for s in range(1, segs + 1):
                seg_start = cur
                evs.append({"ts": cur.isoformat(timespec="seconds"), "kind": "segment_start", "attempt": attempt, "stage": "run", "segment": s})
                for k in range(rnd.randint(3, 6)):
                    cur += timedelta(minutes=rnd.randint(1, 3))
                    name = rnd.choice(tools)
                    tid = f"t{i}{a}{s}{k}"
                    evs.append({"ts": cur.isoformat(timespec="seconds"), "kind": "tool", "attempt": attempt, "stage": "run", "segment": s,
                                "tool": name.split()[0], "summary": name, "tool_id": tid})
                    if name.startswith("Agent"):
                        for j in range(3):
                            cur += timedelta(minutes=1)
                            evs.append({"ts": cur.isoformat(timespec="seconds"), "kind": "tool", "attempt": attempt, "stage": "run", "segment": s,
                                        "tool": "Grep", "summary": f"Grep 표본 {j}", "tool_id": f"{tid}c{j}", "parent": tid})
                cur += timedelta(minutes=1)
                evs.append({"ts": cur.isoformat(timespec="seconds"), "kind": "segment_end", "attempt": attempt, "stage": "run", "segment": s,
                            "turns": rnd.randint(8, 30), "minutes": int((cur - seg_start).total_seconds() // 60), "verdict": "있음" if s < segs else "결과 보고",
                            "input_tokens": rnd.randint(20000, 90000), "output_tokens": rnd.randint(800, 4000)})
                evs.append({"ts": cur.isoformat(timespec="seconds"), "kind": "judge", "stage": "run", "segment": s, "progress": "있음", "reason": "단계가 끝났다"})
            st = "실패" if (a < retries or status == "실패") else status
            evs.append({"ts": cur.isoformat(timespec="seconds"), "kind": "stage_end", "attempt": attempt, "stage": "run", "status": st, "minutes": 20})
            if status != "진행 중":
                evs.append({"ts": cur.isoformat(timespec="seconds"), "kind": "stage_start", "attempt": attempt, "stage": "analyze"})
                cur += timedelta(minutes=rnd.randint(3, 6))
                evs.append({"ts": cur.isoformat(timespec="seconds"), "kind": "stage_end", "attempt": attempt, "stage": "analyze", "cause": "작업자 변경 안" if a < retries else "해당 없음", "issues": rnd.randint(1, 4)})
                evs.append({"ts": cur.isoformat(timespec="seconds"), "kind": "stage_start", "attempt": attempt, "stage": "search"})
                cur += timedelta(minutes=rnd.randint(3, 8))
                evs.append({"ts": cur.isoformat(timespec="seconds"), "kind": "stage_end", "attempt": attempt, "stage": "search", "sources": rnd.randint(0, 3)})
            if a < retries:
                evs.append({"ts": cur.isoformat(timespec="seconds"), "kind": "retry", "attempt": attempt, "next": attempt + 1, "cause": "작업자 변경 안"})
                attempt += 1
        if status != "진행 중":
            evs.append({"ts": cur.isoformat(timespec="seconds"), "kind": "run_end", "status": status})
        runs.append({
            "run_id": rid, "project": proj, "title": title, "kind": kind, "started": start.isoformat(timespec="seconds"),
            "finished": None if status == "진행 중" else cur.isoformat(timespec="seconds"), "status": status,
            "summary": {"확인 필요": "프롬프트 파일 쓰기 금지에 걸림", "실패": "작업자 변경 안의 버그로 수집 실패, 재시도 2회",
                        "완료": "완료 기준을 채웠다", "진행 중": "구간 2 진행 중"}[status],
            "evidence_ref": f"runs/{rid}", "minutes_used": used, "minutes_limit": limit, "report_date": "demo",
            "rule": "읽기만 경로" if status == "확인 필요" else "", "options": ["표본만 임시 폴더에 둔다", "이 항목을 할 일 목록에서 뺀다"] if status == "확인 필요" else [],
            "attempts": [], "events": evs, "demo": True,
        })
        t = start + timedelta(minutes=rnd.randint(10, 40))
    cut = datetime.combine(base.date() + timedelta(days=1), CUTOFF)
    return {"date": "demo", "cutoff_time": f"{CUTOFF:%H:%M}", "cutoff": cut.isoformat(timespec="seconds"), "runs": runs, "demo": True}


_CONN_ERRORS = (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False  # Windows에서는 재사용을 켜면 같은 포트에 두 번 묶여 옛 서버가 응답한다. 두 번째 시작은 바로 실패해야 한다

    def handle_error(self, request, client_address):
        # 브라우저가 새로고침이나 화면 전환으로 먼저 끊은 요청이다. 추적 내용을 찍지 않는다.
        if isinstance(sys.exc_info()[1], _CONN_ERRORS):
            return
        super().handle_error(request, client_address)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):  # 조용히
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        try:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except _CONN_ERRORS:
            pass

    def _json(self, data) -> None:
        self._send(200, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        q = parse_qs(url.query)
        try:
            if url.path == "/api/state":
                return self._json(state((q.get("tab") or [""])[0]))
            if url.path == "/api/day":
                return self._json(day((q.get("date") or ["demo"])[0]))
            if url.path == "/api/dates":
                return self._json(dates())
            if url.path == "/api/runs":
                return self._json(runs_list(int((q.get("limit") or ["100"])[0])))
            if url.path == "/api/run":
                return self._json(run_detail((q.get("id") or [""])[0]))
            if url.path == "/api/report":
                return self._json(report_text((q.get("date") or [now().date().isoformat()])[0]))
            if url.path == "/api/preview":
                return self._json(preview_check((q.get("url") or [""])[0]))
            if url.path == "/api/sheet":
                d = run_detail((q.get("id") or [""])[0])
                return self._send(200 if "sheet" in d else 404, (d.get("sheet") or d.get("error", "")).encode("utf-8"), "text/markdown; charset=utf-8")
            if url.path.startswith("/runs/"):
                # 보고서의 그림과 첨부. runs/ 아래 파일만 내준다
                rel = unquote(url.path[len("/runs/"):])
                target = (RUNS / rel).resolve()
                if RUNS.resolve() not in target.parents or not target.is_file():
                    return self._send(404, "없음".encode("utf-8"), "text/plain; charset=utf-8")
                ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                if ctype.startswith("text/"):
                    ctype += "; charset=utf-8"
                return self._send(200, target.read_bytes(), ctype)
            name = "index.html" if url.path in ("/", "") else url.path.lstrip("/")
            target = (WEB_DIR / name).resolve()
            if WEB_DIR.resolve() not in target.parents or not target.is_file():
                return self._send(404, "없음".encode("utf-8"), "text/plain; charset=utf-8")
            ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                ctype += "; charset=utf-8"
            return self._send(200, target.read_bytes(), ctype)
        except _CONN_ERRORS:
            return None
        except Exception as e:  # noqa: BLE001
            return self._send(500, f"오류: {e}".encode("utf-8"), "text/plain; charset=utf-8")

    def do_POST(self):  # noqa: N802
        url = urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if url.path == "/api/answer_image":  # 답 칸에 붙인 그림. 몸통은 그림 그대로다. 로컬 요청만, 10MB까지 받는다
                if self.client_address[0] not in ("127.0.0.1", "::1"):
                    return self._send(403, "로컬에서만 받는다".encode("utf-8"), "text/plain; charset=utf-8")
                if n <= 0 or n > IMAGE_MAX:
                    self.close_connection = True  # 넘는 몸통은 읽지 않고 끊는다
                    return self._json({"ok": False, "why": f"크기가 {n:,}바이트다. 0보다 크고 10MB 이하만 받는다"})
                return self._json(upload_image((parse_qs(url.query).get("run") or [""])[0], self.rfile.read(n)))
            body = json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}
            if url.path == "/api/answer":
                return self._json(answer(str(body.get("run_id", "")), str(body.get("answer", "")).strip(), body.get("images")))
            if url.path == "/api/confirm":
                return self._json(confirm.act(body))
            if url.path == "/api/command":  # TODO 탭의 넣기 줄과 Auto 단추. 할 일 파일과 모드를 바꾸므로 로컬 요청만 받는다
                if self.client_address[0] not in ("127.0.0.1", "::1"):
                    return self._send(403, "로컬에서만 바꾼다".encode("utf-8"), "text/plain; charset=utf-8")
                return self._json(command(body))
            if url.path == "/api/project":  # 프로젝트 만들기. 폴더와 등록을 만들므로 로컬 요청만 받고, 다른 사이트의 페이지가 보낸 요청도 거절한다
                origin = self.headers.get("Origin") or ""
                if self.client_address[0] not in ("127.0.0.1", "::1") or (origin and urlparse(origin).netloc != self.headers.get("Host")):
                    return self._send(403, "로컬에서만 바꾼다".encode("utf-8"), "text/plain; charset=utf-8")
                return self._json(new_project(body))
            if url.path == "/api/gpuqueue":  # GPU 대기열 단추(맨 앞으로, 내리기, 취소). 로컬 요청만 받는다(261026-jipsa-26)
                if self.client_address[0] not in ("127.0.0.1", "::1"):
                    return self._send(403, "로컬에서만 바꾼다".encode("utf-8"), "text/plain; charset=utf-8")
                return self._json(gpu_queue_action(body))
            if url.path == "/api/slack":
                slack.set_enabled(bool(body.get("enabled")))
                events.emit("slack_switch", enabled=slack.is_enabled())
                return self._json({"slack_on": slack.is_enabled()})
            return self._send(404, "없음".encode("utf-8"), "text/plain; charset=utf-8")
        except _CONN_ERRORS:
            return None
        except Exception as e:  # noqa: BLE001
            return self._send(500, f"오류: {e}".encode("utf-8"), "text/plain; charset=utf-8")


def gpu_queue_action(body: dict) -> dict:
    """GPU 대기열 한 줄의 순서를 바꾸거나 취소한다. action은 top, down, cancel이다. 머리 줄 보관을 비워 다음 응답에 바로 보이게 한다."""
    from scheduler import auto

    key, action = str(body.get("key") or ""), str(body.get("action") or "")
    if not key or action not in ("top", "down", "cancel"):
        return {"ok": False, "text": "줄과 동작(top, down, cancel)이 필요하다"}
    if action == "cancel":
        text = auto.cancel_wait(key)
    else:
        ok = resources.queue_move(key, action)
        text = ("맨 앞으로 옮겼다" if action == "top" else "한 칸 내렸다") if ok else "대기열에 없는 줄이다"
    events.emit("gpu_queue", key=key, action=action, text=text)
    _HEAD.update(at=0.0, val=None)
    return {"ok": True, "text": text}


def serve(port: int = 8765, open_browser: bool = True, watch: bool = True) -> None:
    try:
        server = Server(("127.0.0.1", port), Handler)
    except OSError as e:
        raise SystemExit(f"포트 {port}를 열지 못했다. 이미 jipsa web이 돌고 있으면 그 창을 쓰거나 끄고 다시 켠다. ({e.strerror or e})") from e
    if watch:
        supervise.start_watch()  # 대시보드가 켜져 있는 동안 스케줄러가 늘 돌게 한다. 없으면 띄우고 꺼지면 다시 띄운다
    url = f"http://127.0.0.1:{port}/"
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
