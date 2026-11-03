"""jipsa 명령. run, console, web, status, todo, auto, answer, registry, settings, wait-answer, report, runs, result, begin, finish, record, dry-run, check, sync-agents, worktrees."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from scheduler.config import AGENTS_FILE, CUTOFF, HOLD, ROOT, RULES_FILE, SETTINGS_FILE, SLACK_WEBHOOK, WORKTREES, ensure_dirs, norm_status, now, time_text
from scheduler.nowindow import hidden


def _print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))


def cmd_run(args) -> int:
    from scheduler.loop import Scheduler

    _print(f"jipsa 스케줄러 시작. 동시 {args.concurrency}개. 종료 시각 {CUTOFF:%H:%M}. Ctrl+C로 멈춘다.")
    other = Scheduler(concurrency=args.concurrency).run_forever()
    if other:
        _print(f"이미 스케줄러가 돌고 있다(pid {other.get('pid')}, {str(other.get('started') or '')[11:16]} 시작). 새로 띄우지 않고 끝낸다.")
        return 1
    return 0


def cmd_console(args) -> int:
    from scheduler import console

    if args.once:
        console.once()
    else:
        console.live()
    return 0


def cmd_web(args) -> int:
    from scheduler import web

    _print(f"웹 화면 http://127.0.0.1:{args.port}/  (Ctrl+C로 멈춘다. 데모 데이터는 화면의 날짜 선택에서 '데모'를 고른다)")
    web.serve(port=args.port, open_browser=not args.no_open, watch=not args.no_watch)
    return 0


def cmd_status(args) -> int:
    from scheduler import modes, queue, resources
    from scheduler.registry import load_all

    _ = modes  # 모드는 없다(261029-jipsa-17). Cycle은 시킬 때 시작과 마감을 정한다
    # 확인 필요 목록은 확인 기록과 대조한 기준 하나(confirm.shown)다. 대시보드 상단 확인 필요 수, 보고와 같다(261025-jipsa-04).
    # 상태 값 확인 필요라도 답 없이 확인한 실행은 확인함으로 따로 적고(상태 값과 큐 보류는 그대로), 확인하지 않은 완료와 실패는 확인 필요다(옛 이름 확인 전 완료, 261023-jipsa-26)
    from scheduler import confirm, record

    conf = confirm.view()
    answered = {r.get("run_id") for r in queue.pending() if r.get("answer")}  # 답이 큐에 들어가 처리 대기인 작업자 실행. 아래 대기 줄에 있다
    rows = {r.get("run_id"): r for r in queue.load() if r.get("run_id")}
    hold, unseen, acked_hold = [], [], []
    for m in sorted(record.list_runs(limit=0), key=lambda m: str(m.get("finished") or "")):
        if m.get("run_id") in answered:
            continue
        s = confirm.shown(m, conf)
        if m.get("status") == confirm.HOLD:
            (hold if s == confirm.HOLD else acked_hold if s == confirm.ACKED else []).append(m)
        elif s == confirm.HOLD:
            unseen.append(m)
    c = queue.counts()
    n_ack = sum(1 for m in acked_hold if (rows.get(m["run_id"]) or {}).get("status") == queue.HOLD)
    if n_ack:  # 큐 줄은 보류 그대로지만 확인 필요로 세지 않는다
        c[queue.HOLD] = c.get(queue.HOLD, 0) - n_ack
        c = {s: n for s, n in c.items() if n} | {"확인함(보류)": n_ack}
    _print("큐: " + ", ".join(f"{k} {v}" for k, v in c.items()) if c else "큐: 비어 있음")
    stalls = record.stall_load()
    for r in queue.running():
        stall = record.stall_of(r.get("run_id") or "", stalls)
        _print(f"  실행 중  {r['project']} | {r['title']} | {r.get('run_id')} | {r.get('started', '')[11:16]}"
               + (f" | 멈춤 {stall}분 (띄운 세션에 깨우라고 알렸다)" if stall else ""))
    for r in queue.pending():
        _print(f"  대기     {r['project']} | {r['title']} | 우선순위 {r.get('priority')} | {r.get('reason') or ''}")
    for m in hold:
        r = rows.get(m["run_id"]) or {}
        _print(f"  확인 필요 {m.get('project')} | {m.get('title')} | {m.get('run_id')} | {r.get('reason') or m.get('summary') or m.get('reason') or ''}")
        _print(f"    걸린 규칙: {m.get('rule', '')}")
        for i, o in enumerate(m.get("options") or []):
            _print(f"    {'(추천) ' if i == 0 and '추천' not in o else ''}{i + 1}. {o}")
    for m in unseen[:20]:
        _print(f"  확인 필요 {m.get('project')} | {m.get('title')} | {m.get('run_id')} | {m.get('status')}, 결과 확인 필요 (jipsa answer <실행ID> 확인)")
    if len(unseen) > 20:
        _print(f"  확인 필요 {len(unseen) - 20}건 더 있다. 대시보드 상단 확인 필요 단추에서 본다")
    for m in acked_hold[-5:]:
        _print(f"  확인함   {m.get('project')} | {m.get('title')} | {m.get('run_id')} | 답 없이 확인함. 상태 값과 큐 보류는 그대로다(결과지 '확인 필요로 되돌리기'로 답 칸을 다시 연다)")
    # 범위 계약(scope.status) 대신 할 일 파일과 실행 기록으로 보인다(261025-jipsa-42, 계획 파일 떼기)
    from scheduler import auto, cycle, todo

    for line in auto.status_lines(load_all()):
        _print(line)
    memo_n = len(todo.memos())
    rows_t, bad_t, _ = todo.load()
    _print(f"할 일 파일: 할 일 {len(rows_t)}줄, "
           f"메모 {memo_n}줄" + (f", 읽지 못한 줄 {len(bad_t)}" if bad_t else "") + " (jipsa todo)")
    g = cycle.window_view()
    _print(f"사용 창(표시만, 새 시작을 막지 않는다): {g['claude']}" + (f" | {g['codex']}" if g["codex"] else ""))
    s = resources.summary()
    gpu = f"GPU {s['gpu_used_gb']}/{s['gpu_total_gb']}GB" if s["gpu_ok"] else "GPU 측정 불가"
    ram = (s.get("ledger") or {}).get("ram") or {}
    _print(f"자원: {gpu}, RAM 여유 {s['ram_free_gb']}GB" + (f"(RAM 예약 {ram['reserved']}GB, 새 작업이 쓸 수 있는 RAM {ram['free']}GB)" if ram else "") + f", Ollama {(', '.join(s['ollama']) or '적재 모델 없음') if s['ollama'] is not None else '꺼짐'}, 리스 {len(s['leases'])}개")
    if s["gpu_ok"]:
        _print(f"  GPU 사용처: {resources.format_owners(s['gpu_owners'])}")
    for lease in s["leases"]:
        _print(f"  장부 {lease['run']} {lease.get('amount_gb')}GB ({'세션' if lease.get('pid_kind') == 'session' else '작업자'}) 만료 {lease['expires'][11:16]}")
    led = s.get("ledger") or {}
    if led:
        _print(f"  GPU 장부: 몫 합 {led['leased']}GB, 장부 밖 {led['outside']}GB, 예약 {led['reserve']}GB, 남은 자리 {max(0, led['free']):g}GB"
               + (f", 실측 초과로 새 GPU 작업 멈춤({led['over']['until'][11:16]}까지)" if led.get("over") else ""))
        for i, r in enumerate(led.get("queue") or [], 1):
            _print(f"  GPU 대기 {i}. {r['project']} | {r['title']} | 필요 {r['need']}GB | {r['why']}")
    return 0


def _meta(run_id: str | None) -> dict | None:
    import json

    from scheduler.config import RUNS, norm_record

    if not run_id:
        return None
    try:
        return norm_record(json.loads((RUNS / run_id / "meta.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


TODO_USAGE = ("jipsa todo, jipsa todo add <프로젝트> <할 일 문장>, jipsa todo rm <번호|문장 일부>, jipsa todo memo <글>, "
              "jipsa todo memo-rm <번호|글 일부>, jipsa todo up <메모 번호|글 일부> <프로젝트> | <기준>, "
              "jipsa todo cycle <번호|문장 일부> [<지표>] [<목표값>] [이상|이하] [상한 N] [도달하면 끝], jipsa todo cycle <번호> off, "
              "jipsa todo run <번호|문장 일부> [HH:MM|+4h], jipsa todo feedback <번호|문장 일부> | <글>")


def cmd_todo(args) -> int:
    """할 일 파일의 목록, 넣기, 지우기, 메모 넣기와 지우기, 메모를 할 일로 올리기, cycle 칸 바꾸기(scheduler/todo.py). 넣어도 큐에 들지 않는다.
    run은 고른 줄 하나를 시킨다(시키기, scheduler/auto.py, 261026-jipsa-12). stop은 시킨 Cycle을 멈추고, until은 마감을 고친다(261029-jipsa-17)."""
    from scheduler import todo

    words = list(args.words or [])
    action = words[0] if words and words[0] in ("add", "rm", "list", "memo", "memo-rm", "up", "cycle", "run", "feedback", "stop", "until") else ("list" if not words else "")
    rest = words[1:]
    if not action:
        _print(f"모르는 동작이다 ({words[0]}). {TODO_USAGE} 가운데 하나다.")
        return 1
    if action in ("memo", "memo-rm"):
        return _todo_memo(rest, remove=action == "memo-rm")
    if action == "up":
        return _todo_up(rest)
    if action == "cycle":
        return _todo_cycle(rest)
    if action == "run":
        return _todo_run(rest)
    if action in ("stop", "until"):
        return _todo_stop(rest, action)
    if action == "feedback":
        return _todo_feedback(rest)
    try:
        if action == "add":
            project, cells = todo.split_args(rest)
            if not project:
                _print("넣지 못했다: 프로젝트와 할 일 문장이 필요하다. jipsa todo add <프로젝트> <할 일 문장> | <기준>")
                return 1
            item = todo.add(project, cells)
            _print(f"넣었다({item.no}번): {item.line()}")
            _print(f"할 일은 넣어도 돌지 않는다. 돌리려면 jipsa todo run {item.no}" + (" [시작 HH:MM] [마감 HH:MM|+4h]" if item.cycle else "") + ".")
            return 0
        if action == "rm":
            item = todo.remove(" ".join(rest))
            _print(f"지웠다({item.no}번): {item.line()}")
            return 0
    except todo.TodoError as e:
        _print(f"{'넣지' if action == 'add' else '지우지'} 못했다: {e}.")
        return 1
    for line in todo_lines():
        _print(line)
    return 0


def _is_when(text: str) -> bool:
    from scheduler import modes
    from scheduler.config import parse_hhmm

    try:
        return modes.parse_span(text) is not None or bool(parse_hhmm(text))
    except ValueError:
        return False


def split_run(rest: list[str]) -> tuple[str, str | None, str | None]:
    """jipsa todo run 인자를 (고르는 말, 시작, 마감)으로 나눈다. 끝에서부터 "시작 HH:MM|지금"과 "마감 HH:MM|+4h"를 떼고, 이름 없이 끝에 온
    시각 하나는 마감이다(옛 꼴). 따옴표 하나로 온 '문장 일부 +4h'도 끝 낱말을 읽는다."""
    words = " ".join(rest).split()
    start = until = None
    while len(words) > 2 and words[-2] in ("시작", "마감", "--start", "--until") and (_is_when(words[-1]) or words[-1] in ("지금", "now")):
        val = words.pop()
        if words.pop() in ("시작", "--start"):
            start = val
        else:
            until = val
    if until is None and len(words) > 1 and _is_when(words[-1]):
        until = words.pop()
    from scheduler import todo

    return todo._norm(" ".join(words)), start, until


def _todo_run(rest: list[str]) -> int:
    """jipsa todo run <번호|문장 일부> [시작 HH:MM|지금] [마감 HH:MM|+4h]. 고른 줄 하나를 다음 스케줄러 주기에 돌린다.
    일회성 줄은 시작 시각 없이 바로 돈다. Cycle 줄은 시작 시각을 적으면 그때 대기열에 선다. 마감은 Cycle이 멈추는 시각이고 정하지 않으면 시작 뒤 8시간이다."""
    from scheduler import auto, todo

    query, start, until = split_run(rest)
    if not query:
        _print("시키지 못했다: 번호나 문장 일부가 필요하다. jipsa todo run <번호|문장 일부> [시작 HH:MM] [마감 HH:MM|+4h]")
        return 1
    try:
        _, lines = auto.ask_run(query, until, start=start)
    except todo.TodoError as e:
        _print(f"시키지 못했다: {e}.")
        return 1
    for line in lines:
        _print(line)
    return 0


def _todo_stop(rest: list[str], action: str) -> int:
    """jipsa todo stop <번호|문장 일부>는 시킨 줄을 멈추고(마감을 지금으로), jipsa todo until <번호|문장 일부> <HH:MM|+4h>는 마감을 고친다."""
    from scheduler import auto, todo

    words = " ".join(rest).split()
    when = words.pop() if action == "until" and len(words) > 1 and _is_when(words[-1]) else ""
    query = todo._norm(" ".join(words))
    if not query or (action == "until" and not when):
        _print("바꾸지 못했다: jipsa todo stop <번호|문장 일부> 또는 jipsa todo until <번호|문장 일부> <HH:MM|+4h>")
        return 1
    try:
        _, lines = auto.stop_run(query) if action == "stop" else auto.set_until(query, when)
    except todo.TodoError as e:
        _print(f"{'멈추지' if action == 'stop' else '바꾸지'} 못했다: {e}.")
        return 1
    for line in lines:
        _print(line)
    return 0


def _todo_feedback(rest: list[str]) -> int:
    """jipsa todo feedback <번호|문장 일부> | <글>. 도는 Cycle 목표에 사람 피드백을 넣는다(261026-jipsa-19).
    할 일 줄과 Cycle 기록은 고치지 않고 상태 폴더의 피드백 파일에 한 줄을 덧붙인다. 스케줄러가 꺼져 있어도 쓴다.
    다음 분석과 다음 Cycle 명령 단계의 지시문에 원문 그대로 들어가고, 돌던 단계에는 계획 파일과 다음 구간 지시문으로 닿는다. 판정 기준은 바꾸지 않는다."""
    from scheduler import cycle, todo

    query, text = todo.split_feedback(rest)
    if not query or not text:
        _print(f"넣지 못했다: 줄과 피드백 글이 필요하다. {todo.FEEDBACK_USAGE}")
        return 1
    try:
        item = todo.feedback_target(query)
    except todo.TodoError as e:
        _print(f"넣지 못했다: {e}.")
        return 1
    e = cycle.feedback_add(item.key, text)
    _print(f"피드백을 넣었다({item.no}번, {e['id']}): {text}")
    pushed = cycle.feedback_push(item.key)  # 돌던 단계는 계획 파일로 받는다. 스케줄러를 다시 띄우지 않아도 다음 구간부터 읽는다
    _print(_feedback_where(item, pushed) + " 판정 기준(지표, 목표값)은 바뀌지 않는다.")
    return 0


def _feedback_where(item, pushed: list[str] | None = None) -> str:
    """피드백을 읽는 단계를 cycle 기록으로 알린다. 돌던 단계는 계획 파일에 넣은 절(pushed)을 다음 구간에 읽고,
    시작 전 대기 단계는 실행기가 첫 지시문에 붙인다(261027-jipsa-02)."""
    from scheduler import auto, cycle, queue

    rec = cycle.load(auto.as_cycle(item))
    rounds = rec.get("rounds") or []
    last = rounds[-1] if rounds and rec.get("status") != cycle.ENDED else None
    if last is None:
        return "이 목표의 다음 Cycle 명령 이행과 분석이 원문 그대로 읽는다."
    n = last["n"]
    if last.get("judge"):
        return f"Cycle {n + 1} 명령 이행과 그 분석이 원문 그대로 읽는다."
    step = cycle.ANALYSIS if cycle.ANALYSIS in last["steps"] else cycle.RUN
    s = last["steps"][step]
    row = (cycle._row(s["key"]) if s.get("key") else None) or {}  # 기록의 칸은 단계를 열 때 값이라 큐 줄이 더 새롭다
    rid = s.get("run_id") or row.get("run_id") or ""
    open_ = (row.get("status") or s.get("status")) in (queue.PENDING, queue.RUNNING, "진행 중")
    name = f"Cycle {n} {step}{'(' + rid + ')' if rid else ''}"
    if rid and rid in (pushed or []):
        head = f"지금 도는 {name}의 계획 파일에 넣었다. 작업자가 다음 구간에 읽는다. "
    elif open_:
        head = f"지금 열린 {name}에는 실행기가 다음 구간 지시문에 붙인다. "
    else:
        head = ""
    if step == cycle.RUN:
        return head + f"Cycle {n} 분석과 피드백이 먼저 읽어 다음 명령에 반영하고, Cycle {n + 1} 명령 이행도 원문 그대로 읽는다."
    return head + f"Cycle {n + 1} 명령 이행과 그 분석이 원문 그대로 읽는다."


def _todo_memo(rest: list[str], remove: bool = False) -> int:
    """jipsa todo memo <글>(넣기), jipsa todo memo-rm <번호|글 일부>(지우기), jipsa todo memo(메모만 보기). 메모는 돌지 않는다.

    지우기를 따로 된 동작 이름으로 두어 memo 뒤의 글은 첫 낱말이 무엇이든 그대로 넣는다."""
    from scheduler import todo

    if remove:
        try:
            item = todo.memo_remove(" ".join(rest))
        except todo.TodoError as e:
            _print(f"지우지 못했다: {e}.")
            return 1
        _print(f"메모를 지웠다({item.label}): {item.text}")
        return 0
    text = " ".join(rest)
    if not todo._norm(text):
        for line in memo_lines():
            _print(line)
        return 0
    try:
        item = todo.memo_add(text)
    except todo.TodoError as e:
        _print(f"넣지 못했다: {e}.")
        return 1
    _print(f"메모를 넣었다({item.label}): {item.text}")
    _print(f"메모는 돌지 않는다. 할 일로 올리려면 jipsa todo up {item.label} <프로젝트> | <기준>")
    return 0


def _todo_up(rest: list[str]) -> int:
    """jipsa todo up <메모 번호|글 일부> <프로젝트> [| 기준 ..]. 메모 한 줄을 할 일 절 끝으로 올린다."""
    from scheduler import todo

    query, project, cells = todo.split_promote(rest, todo.project_names())
    if not query:
        _print("올리지 못했다: 메모 번호나 글 일부가 필요하다. jipsa todo up <메모 번호|글 일부> <프로젝트> | <기준>")
        return 1
    try:
        memo, item = todo.promote(query, project, cells)
    except todo.TodoError as e:
        _print(f"올리지 못했다: {e}.")
        return 1
    _print(f"메모 {memo.label}을 할 일로 올렸다({item.no}번): {item.line()}")
    _print("할 일은 넣어도 돌지 않는다.")
    return 0


def _todo_cycle(rest: list[str]) -> int:
    """jipsa todo cycle <번호|문장 일부> [<지표>] [<목표값>] [이상|이하] [상한 N]. 그 줄의 cycle 칸을 채우거나 덮어쓴다. off면 비운다.
    줄은 제자리에 두고, 도는 줄(큐의 대기나 실행 중 줄)은 거절한다(261025-jipsa-49).
    지표나 목표값을 비우면 목표 미정 Cycle이고 Cycle 1 분석이 빈 칸을 정한다(261026-jipsa-11)."""
    from scheduler import auto, todo

    query, toks = todo.split_cycle(rest)
    if not query:
        _print(f"바꾸지 못했다: 번호나 문장 일부가 필요하다. {todo.CYCLE_USAGE}.")
        return 1
    try:
        cyc = todo.cycle_cell(toks)
        # 시킨 줄과 도는 단계가 있는 줄만 막는다. 마감으로 멈춘 Cycle의 남은 단계 줄은 큐에 있어도 사람이 칸을 고칠 수 있다
        busy = {r["todo_key"] for r in auto.lane_rows() if r.get("todo_key") and r["status"] == "실행 중"} | auto.run_keys()
        item, old = todo.set_cycle(query, cyc, busy=busy)
    except todo.TodoError as e:
        _print(f"바꾸지 못했다: {e}.")
        return 1
    if cyc is None:
        _print(f"cycle 칸을 비웠다({item.no}번, 뗀 칸: {todo.cycle_text(old)}): {item.line()}")
        return 0
    _print(f"{'cycle 칸을 덮어썼다' if old else 'Cycle 목표로 바꿨다'}({item.no}번): {item.line()}")
    if miss := todo.cycle_pending(cyc):  # 목표 미정 Cycle(261026-jipsa-11)
        _print(f"목표 미정이다. 비운 칸({', '.join(miss)})은 Cycle 1 분석이 정해 이 줄에 채우고 그 값으로 판정한다.")
    if not cyc.get("cap"):  # 목표 미정이어도 분석은 상한을 채우지 않는다(261029-jipsa-03 1안)
        _print("상한을 적지 않아 나아지지 않아도 마감까지 Cycle을 잇는다. 멈추려면 끝에 상한 N을 적는다.")
    if not cyc.get("stop"):
        _print("목표에 닿아도 마감까지 다음 Cycle을 잇는다. 닿으면 끝내려면 끝에 도달하면 끝을 적는다.")
    _print(f"할 일 줄은 돌지 않는다. 돌리려면 jipsa todo run {item.no} [시작 HH:MM] [마감 HH:MM|+4h].")
    return 0


def memo_lines() -> list[str]:
    """`jipsa todo`와 `jipsa todo memo`가 찍는 메모 절 줄."""
    from scheduler import todo

    rows = todo.memos()
    return [f"{todo.MEMO} {len(rows)}건"] + [f"  {it.label}. {it.text}" for it in rows]


def todo_lines(sections: tuple[str, ...] | None = None) -> list[str]:
    """`jipsa todo`가 찍는 목록 줄. 대시보드 TODO 탭의 할 일 칸이 sections=("할 일",)로 같은 줄을 그린다(261025-jipsa-29).

    sections를 주면 그 절의 줄과 읽지 못한 줄만 준다. 파일 전체가 비면 sections와 무관하게 명령과 같은 안내 한 줄이다."""
    from scheduler import auto, record, todo

    items, bad, _ = todo.load()
    memo_n = len(todo.memos()) if sections is None else 0
    plans = auto.open_plans() if items else {}  # 기준 정하기가 도는 줄은 끝에 그 상태를 붙인다(261025-jipsa-54)
    reqs = {r["key"]: r for r in auto.run_requests()}  # 시킨 줄은 끝에 시키기 상태를 붙인다(261026-jipsa-12, 여러 줄은 261026-jipsa-26)
    if not items and not bad and not memo_n:
        return ["할 일이 없다. jipsa todo add <프로젝트> <할 일 문장>으로 넣는다."]
    lines = []
    for section in sections or todo.SECTIONS:
        rows = [it for it in items if it.section == section]
        lines.append(f"{section} {len(rows)}건")
        lines += [f"  {it.no}. {it.line()}" + (f" | {auto.run_note(reqs[it.key])}" if it.key in reqs else
                                                f" | {auto.DO_TAG}. 세션이 받아 서브에이전트로 시작한다" if record.do_open(it.key) else
                                                f" | {auto.plan_note(plans[it.key])}" if it.key in plans else "") for it in rows]
        if section == todo.TODO:  # 시켜서 줄이 파일에서 빠진 뒤 도는 실행. 할 일 칸에서도 진행 중으로 보인다
            lines += [f"도는 중: {r['project']} | {r['title']} | {r.get('run_id')} | {str(r.get('started') or '')[11:16]} 시작 | {auto.RUN_TAG}"
                      for r in auto.lane_rows() if r.get("run_now") and r["status"] == "실행 중"
                      and not any(it.key == r.get("todo_key") for it in rows)]
    lines += [f"  읽지 못한 줄({line_no + 1}줄): {raw} ({why})" for line_no, raw, why in bad]
    if sections is None:  # jipsa todo는 메모 절도 끝에 보인다(261025-jipsa-36)
        lines += memo_lines()
    return lines


def cmd_answer(args) -> int:
    from scheduler import queue

    from scheduler import record

    if args.undo:
        out = record.unanswer(args.run_id)
        if not out.get("ok"):
            _print(f"물리지 못했다: {out.get('why')}")
            return 1
        extra = f" 작업자 실행 {out['cancelled']}는 시작 전이라 함께 거뒀다." if out.get("cancelled") else ""
        extra += (f" 작업자 실행 {out['worker_run']}가 이미 시작해 거두지 못했다. 필요하면 그 실행을 멈춘다." if out.get("worker_run")
                  else " 이미 세션에 넘어간 답이 있다." if out.get("delivered") else "")
        _print(f"답을 물렸다: {out.get('was')}.{extra}")
        return 0
    out = record.answer(args.run_id, args.answer, close=args.close)
    if not out.get("ok"):
        _print(f"넣지 못했다: {out.get('why')}")
        return 1
    if out.get("acked"):
        _print("확인했다. 확인 필요에서 빠지고 완료로 보인다. 답은 남기지 않았다.")
        return 0
    if out.get("after"):  # 끝난 실행의 답은 그 실행을 다시 돌리지 않고 받은편지함으로 간다. 답을 넣으면 확인한 것이라 확인 필요에서 빠지고 실패였으면 완료가 된다
        _print("끝난 실행에 답을 적었다. 확인 필요에서 빠지고 완료로 보이며 그 실행은 다시 돌리지 않는다." + ("" if args.close else " " + out.get("delivery", "")))
        return 0
    if out.get("todo"):  # 기준 정하기 결과지의 답(261025-jipsa-24)
        _print(f"답한 기준을 할 일 줄에 적었다. 돌리려면 jipsa todo run으로 시킨다: {out['todo']}")
        return 0
    if args.close:
        _print("답을 기록에 적고 완료로 닫았다. 스케줄러가 이어 돌리지 않는다.")
        return 0
    _print("답을 넣었다. 스케줄러가 다음 확인 주기에 이어 돌린다." if out.get("resume") else "답을 기록에 적고 완료로 닫았다. " + out.get("delivery", ""))
    return 0


def _pairs(items: list[str]) -> tuple[list[tuple[str, str, str]], str]:
    """'칸=값', '칸+=값', '칸-=값' 인자를 (칸, 연산, 값)으로 나눈다. 앞에서 처음 나오는 연산만 본다."""
    out = []
    for item in items:
        m = re.match(r"^([^=+\-]+?)\s*(\+=|-=|=)(.*)$", item, re.S)
        if not m:
            return [], f"'칸=값' 꼴이 아니다: {item}"
        out.append((m.group(1).strip(), m.group(2), m.group(3)))
    return out, ""


def _guard_worker(what: str) -> int:
    """설정과 등록을 쓰는 명령은 사람이 있는 세션 전용이다. 작업자가 자기 범위를 넓히지 못하게 작업자 셸에서는 거절한다."""
    from scheduler import regline

    shell = regline.worker_shell()
    if shell:
        _print(f"거절: {what}는 메인 세션 전용이다. 지금 셸은 {shell}이다")
        return 2
    return 0


def cmd_settings(args) -> int:
    """전역 설정 보기, 검사, 저장, 되돌리기, Webhook, 시험 글, 다시 시작. /jipsa-slack, /jipsa-model, /jipsa-config, /jipsa-cleanup 스킬이 부른다(261102-jipsa-34)."""
    from scheduler import events, settings, supervise

    if args.action == "show":
        v = settings.view(args.skill or "")
        sch = v["scheduler"]
        _print(f"설정 파일 {v['file']}, 직전 판 {'있음' if v['has_prev'] else '없음'}")
        _print(f"스케줄러 {'켜짐' if sch['alive'] else '꺼짐'}, 실행 중 작업 {sch['running']}개" + (", 다시 띄우기 멈춤(jipsa settings start로 푼다)" if not sch["alive"] and supervise.view().get("stopped") else ""))
        for it in v["items"]:
            tail = (f" ({it['note']})" if it["note"] else "") + (" [환경 변수가 앞선다. .env를 고쳐야 바뀐다]" if it["locked"] else "")
            opts = f" 고를 값: {', '.join(it['options'])}." if it["options"] else ""
            _print(f"{it['key']} | {it['name']} | {it['text']}{tail} | 출처 {it['source']} | {it['desc']}{opts}")
        return 0
    if _guard_worker(f"jipsa settings {args.action}"):
        return 2
    if args.action in ("check", "set"):
        pairs, why = _pairs(args.pairs)
        if why:
            _print(f"거절: {why}")
            return 1
        values = {k: v for k, op, v in pairs}
        if any(op != "=" for _, op, _ in pairs):
            _print("거절: 전역 설정은 '칸=값' 꼴만 받는다")
            return 1
        if "JIPSA_SLACK_WEBHOOK" in values:
            _print("거절: Webhook 주소는 명령줄로 받지 않는다. jipsa settings webhook에 표준 입력으로 준다")
            return 1
        out = settings.check(values) if args.action == "check" else settings.save(values)
        if not out["ok"]:
            _print(f"거절: {out['why']}")
            return 1
        for row in out["rows"]:
            _print(f"{row['name']}: {row['before']} -> {row['after']}")
        if args.action == "check":
            _print("검사 통과. 쓰지 않았다")
            return 0
        events.emit("settings_save", changed=[r["key"] for r in out["rows"]])
        _print("저장했다." + (" 스케줄러와 대시보드를 다시 띄워야 반영된다" if out["restart"] else " 바로 반영된다"))
        return 0
    if args.action == "undo":
        out = settings.restore()
        if not out["ok"]:
            _print(f"거절: {out['why']}")
            return 1
        events.emit("settings_restore")
        _print("설정 파일을 직전 판으로 되돌렸다. 한 번 더 하면 다시 돌아온다. 스케줄러와 대시보드를 다시 띄워야 반영된다")
        return 0
    if args.action == "webhook":
        value = "" if args.clear else sys.stdin.read().strip()
        if not args.clear and not value:
            _print("거절: 표준 입력이 비었다. 지우려면 --clear를 준다")
            return 1
        out = settings.save({"JIPSA_SLACK_WEBHOOK": value})
        if not out["ok"]:
            _print(f"거절: {out['why']}")
            return 1
        events.emit("settings_save", changed=["JIPSA_SLACK_WEBHOOK"])
        _print(f"Webhook 주소: {out['rows'][0]['before']} -> {out['rows'][0]['after']}. 값은 비밀값 파일에만 있다")
        return 0
    if args.action == "slack-test":
        out = settings.slack_test()
        _print(out["text"] if out["ok"] else f"거절: {out['why']}")
        return 0 if out["ok"] else 1
    if args.action == "stop":
        out = supervise.stop_scheduler(force=args.force)
        if out["ok"]:
            events.emit("scheduler_stop", running=out["running"], by="settings stop")
        _print(out["text"] if out["ok"] else f"끄지 않았다: {out['why']}")
        return 0 if out["ok"] else 1
    if args.action == "start":
        out = supervise.start_scheduler()
        if out["ok"]:
            events.emit("settings_start")
        _print(out["text"] if out["ok"] else f"켜지 못했다: {out['why']}")
        return 0 if out["ok"] else 1
    out = settings.restart(force=args.force, port=args.port or 0)  # restart
    if out["ok"]:
        events.emit("settings_restart")
    _print(out["text"] if out["ok"] else f"다시 띄우지 않았다: {out['why']}")
    return 0 if out["ok"] else 1


def _registry_write(args) -> int:
    """등록 새로 만들기와 고치기. /jipsa-register 스킬이 부른다(261102-jipsa-34). 쓰기는 줄 단위이고 사람 승인 문구 칸은 jipsa registry add만 쓴다."""
    from scheduler import events, regedit

    if _guard_worker(f"jipsa registry {args.action}"):
        return 2
    pairs, why = _pairs(args.pairs)
    if why:
        _print(f"거절: {why}")
        return 1
    current = regedit.fields_view(args.project) if args.action == "edit" else {}
    if args.action == "edit" and not current.get("ok"):
        _print(f"거절: {current['why']}")
        return 1
    now_vals = {f["id"]: f["value"] for f in current.get("fields", [])}
    values: dict[str, str] = {}
    for token, op, val in pairs:
        f = regedit.find_field(token)
        if f is None:
            _print(f"거절: 모르는 칸이다: {token}")
            return 1
        fid = regedit.field_id(f)
        if op == "=":
            values[fid] = val.replace("\\n", "\n") if f["kind"] == "list" else val
            continue
        if f["kind"] != "list":
            _print(f"거절: {f['name']}은(는) 목록 칸이 아니라 '칸=값'으로 고친다")
            return 1
        items = [x for x in values.get(fid, now_vals.get(fid, "")).split("\n") if x.strip()]
        if op == "+=" and val.strip() not in items:
            items.append(val.strip())
        if op == "-=":
            if val.strip() not in items:
                _print(f"거절: {f['name']}에 없는 값이다: {val.strip()}")
                return 1
            items.remove(val.strip())
        values[fid] = "\n".join(items)
    made = None
    if args.action == "new":
        values["name"] = args.project
        out = regedit.new_project(values, check=args.check)
        made = out.get("made")
    else:
        out = regedit.save(args.project, values, dry_run=args.check)
    if not out["ok"]:
        _print(f"거절: {out['why']}")
        return 1
    if args.action == "new":
        if args.check:
            _print(out["text"].rstrip())
            _print("검사 통과. 쓰지 않았다")
        else:
            events.emit("registry_create", project=out["project"])
            _print(f"등록 {out['project']}를 만들었다. 다시 읽어 칸 {out['fields_read']}개가 읽힌다. 스케줄러는 다음 주기에 새 등록을 읽는다")
            if made:
                _print(f"{regedit.made_text(made['path'], made)}. 대시보드 TODO 탭에서 이 프로젝트로 일을 넣는다")
    else:
        for d in out["diff"]:
            _print(d)
        if args.check:
            _print(f"검사 통과. 바뀌는 줄 {out['lines']}개, 쓰지 않았다")
        else:
            events.emit("registry_save", project=out["project"], changed=out["changed"])
            _print(f"등록 {out['project']}를 고쳤다. 바뀐 칸 {len(out['changed'])}개, 바뀐 줄 {out['lines']}개")
    if out.get("note"):
        _print(f"주의: {out['note']}")
    return 0


def cmd_registry(args) -> int:
    """등록 보기(show), 새로 만들기(new), 고치기(edit), 사람 답이 기록된 실행을 근거로 목록 칸 끝에 한 줄 더하기(add). add는 메인 세션이 답을 받은 뒤 부른다(261029-jipsa-38 1안)."""
    from scheduler import regedit, regline

    if args.action == "show":
        if not args.project:
            from scheduler.config import PROJECTS

            for q in sorted(PROJECTS.glob("*.toml")):
                _print(q.stem)
            return 0
        v = regedit.fields_view(args.project)
        if not v["ok"]:
            _print(f"{v['why']}. 새 등록의 경로 기본값은 {regedit.default_repo(args.project).as_posix()}다")
            return 1
        for f in v["fields"]:
            value = f["value"].replace("\n", ", ") if f["value"] else f"(비움, 기본값 {f['default'] or '없음'})"
            _print(f"{f['id']} | {f['name']} | {value}")
        return 0
    if args.action in ("new", "edit"):
        return _registry_write(args)
    out = regline.add(args.project, args.field, args.line, args.run, dry_run=args.dry_run)
    if not out.get("ok"):
        _print(f"더하지 않았다: {out['why']}")
        return 1
    _print(("미리 보기, 쓰지 않았다: " if out.get("dry_run") else f"{args.project} 등록부 {args.field} 끝에 더했다: ") + out["line"])
    return 0


def cmd_wait_answer(args) -> int:
    """받은편지함을 지켜보다 세션 몫의 답이 생기면 받음 표시를 하고 안내문을 찍고 끝난다. 세션의 백그라운드 명령이 끝나면 세션이 깨어난다."""
    import time

    from scheduler import record, sessionproc

    deadline = time.monotonic() + args.timeout * 60 if args.timeout > 0 else None
    claude = sessionproc.claude_proc()  # 이 대기를 띄운 세션의 Claude Code 프로세스. 터미널에서 직접 띄웠으면 None이고 생존 검사를 하지 않는다
    try:
        return _wait_loop(args, deadline, claude)
    finally:
        record.waiter_beat(args.session, os.getpid(), gone=True)  # 끝나면 열린 세션에서 빠진다. 그 뒤 Do는 작업자로 간다


def _wait_loop(args, deadline, claude) -> int:
    import time

    from scheduler import record, sessionproc

    beat = 0.0
    while True:
        if claude is not None and not sessionproc.alive(claude):
            # 세션이 사라졌다. 남으면 2분 뒤 다른 세션의 답까지 받음 처리하므로 답을 꺼내기 전에 끝낸다
            _print("[jipsa] 이 대기 명령을 띄운 세션이 없어 끝낸다.")
            return 0
        if time.monotonic() - beat >= 5:  # 열린 세션 표시. 대시보드 Do가 이 값을 보고 세션으로 보낸다(261026-jipsa-26)
            record.waiter_beat(args.session, os.getpid())
            beat = time.monotonic()
        rows = record.inbox_take(args.session)
        stalls = record.stall_take(args.session)  # 스케줄러가 찾은 멈춘 서브에이전트. 답과 같이 이 대기를 끝내 Main을 깨운다
        if rows or stalls:
            if rows:
                _print(record.inbox_note(rows))
            if stalls:
                _print(record.stall_note(stalls))
            _print("처리를 서브에이전트에 넘긴 뒤 이 대기 명령을 다시 백그라운드로 띄운다." if rows else "SendMessage로 깨운 뒤 이 대기 명령을 다시 백그라운드로 띄운다.")
            return 0
        if deadline is not None and time.monotonic() >= deadline:
            _print(f"[jipsa] {args.timeout:g}분 동안 답이 없어 대기를 끝냈다. 계속 받으려면 다시 띄운다.")
            return 0
        time.sleep(max(0.5, args.interval))


def cmd_claude_usage(args) -> int:
    """Claude 사용 창 기록. show는 지금 값, record는 값 하나를 상태 폴더에 남긴다.
    record에 --five, --week가 없으면 표준 입력의 상태줄 JSON에서 rate_limits 칸을 읽는다. 상태줄 명령 앞에 끼워 쓴다."""
    import json

    from scheduler import claude_window, cycle

    if args.action == "record":
        if args.five is None and args.week is None:
            try:
                payload = json.loads(sys.stdin.read() or "{}")
            except ValueError:
                payload = {}
            rec = claude_window.record_statusline(payload)
            if rec is None:
                _print("상태줄 입력에 rate_limits 칸이 없어 남기지 않았다")
                return 1
        else:
            rec = claude_window.record(args.five, args.week, args.source)
        _print(f"남김: 5시간 {rec['five']}%, 주간 {rec['week']}% ({rec['source']}, {rec['seen'][11:16]})")
    u = claude_window.usage()
    g = cycle.window_view()
    _print(f"{u['text']}{' (' + u['source'] + ', ' + str(u['seen'])[11:16] + ' 기록)' if u['fresh'] else ''}")
    _print(f"{g['codex']} (사용 창은 표시만 하고 새 시작을 막지 않는다)" if g["codex"] else "Codex 칸은 숨겼다(공격 공급자가 codex가 아니거나 Codex가 없다)")
    return 0


def cmd_auto(args) -> int:
    """옛 Auto 명령(261029-jipsa-17에서 Auto 모드를 뗐다). 없어졌다는 안내와 지금 상태를 찍는다. 상태 보기는 0, 나머지 동작은 1로 끝난다."""
    from scheduler import auto
    from scheduler.registry import load_all

    words = list(args.words or [])
    action = words[0] if words else "status"
    _print(auto.AUTO_GONE + ".")
    if action in ("add", "top", "rm"):
        _print("Auto 목록이 없어 줄을 옮기지 않았다. 할 일 줄은 제자리에 있다. 순서는 대기열(대시보드 TODO 탭의 맨 앞으로, 내리기)에서 바꾼다.")
    elif action == "on":
        _print("켜지 않았다. 밤새 돌릴 Cycle은 jipsa todo run <번호> 시작 HH:MM 마감 HH:MM으로 하나씩 시킨다.")
    elif action == "off":
        _print("끌 것이 없다. 도는 Cycle을 멈추려면 jipsa todo stop <번호>다.")
    for line in auto.status_lines(load_all()):
        _print(line)
    return 0 if action == "status" else 1


def cmd_report(args) -> int:
    from notify import slack
    from scheduler import report

    date = args.date or now().date().isoformat()
    full, summary = report.build(date)
    path = report.write(date)
    _print(full)
    _print(f"(저장: {path})")
    if args.send:
        _print(slack.notify(summary, force=True))  # 사람이 직접 보낸 요청은 꺼져 있어도 보낸다
    return 0


def _slack_note(no_slack: bool, meta: dict, sent: str = "Slack 요약 글 전송") -> str:
    """마감 줄 끝의 Slack 표시. 확인 필요와 실패만 바로 보내고 완료는 보내지 않는다(261025-jipsa-20)."""
    from notify import slack
    from scheduler import report

    if no_slack:
        return ""
    quiet = report.card_skip(meta)
    if quiet:
        return f" | {quiet}라 Slack은 보내지 않음"
    return " | " + (sent if slack.is_enabled() else slack.SKIPPED)


def cmd_slack(args) -> int:
    from notify import slack

    if args.state == "on":
        slack.set_enabled(True)
    elif args.state == "off":
        slack.set_enabled(False)
    on = slack.is_enabled()
    _print("Slack 알림 " + ("켜짐" if on else "꺼짐. 자동 알림은 보내지 않는다. jipsa report --send는 보낸다"))
    if not slack.is_available():
        _print("(웹훅이 비어 있어 켜 두어도 보낼 곳이 없다)")
    return 0


def cmd_runs(args) -> int:
    from scheduler import record
    from scheduler.config import display_project

    rows = record.list_runs(limit=args.last, date=args.date, project=args.project, status=args.status)
    if not rows:
        _print("기록 없음")
        return 0
    _print(f"{'시작':16} {'프로젝트':14} {'상태':6} {'주체':10} {'시간':10} {'출력토큰':>9}  항목 | 결과")
    for m in rows:
        tok = (m.get("tokens") or {}).get("output")
        exe = {"worker": "스케줄러", "subagent": "서브에이전트", "session": "세션", "manual": "들여옴"}.get(m.get("executor", ""), m.get("executor") or "")
        _print(f"{m.get('started', '')[:16].replace('T', ' '):16} {display_project(m.get('project', '')):14} {m.get('status', ''):6} {exe:10} "
               f"{time_text(m.get('minutes_used'), m.get('minutes_limit')):10} {(f'{tok:,}' if tok else ''):>9}  "
               f"{m.get('title', '')} | {m.get('summary') or m.get('reason') or ''}")
        _print(f"{'':16} {m.get('run_id', '')}")
    return 0


def cmd_result(args) -> int:
    from scheduler import record
    from scheduler.config import RUNS

    meta = record.meta_of(args.run_id)
    if not meta:
        from scheduler import prune

        bundle = prune.archived_in(args.run_id)
        _print(f"runs/{args.run_id}는 보관됐다(runs/archive/{bundle})" if bundle else f"runs/{args.run_id}가 없다")
        return 1
    if args.rebuild or not (RUNS / args.run_id / "result.md").exists():
        record.write_sheet(args.run_id)
    _print((RUNS / args.run_id / "result.md").read_text(encoding="utf-8"))
    return 0


def _result_block(run_id: str, executor: str = "", draft: bool = False) -> str:
    from scheduler import prompts
    from scheduler.config import RUNS
    import json

    att = RUNS / run_id / "attempt-1"
    draft_line = [prompts.DRAFT_NOTE.format(draft=(att / "draft" / "index.html").as_posix())] if draft else []
    if executor == "subagent":
        # 서브에이전트의 Write는 REPORT, ANALYSIS 등으로 시작하는 .md 쓰기를 막으므로 본문은 마지막 답으로 돌려준다
        report_line = (f"보고서: 본문은 {prompts.REPORT_FILE} 규격(한국어 평서체, A4 두 장 안)으로 쓰되 파일로 쓰지 말고 마지막 답에 마크다운 전체로 돌려준다. "
                       f"셸 쓰기나 이름 바꾸기로 우회하지 않는다. 메인 세션이 {att / 'report.md'} 로 옮긴다. 그림은 {att / 'figures'}/ 에 PNG로 직접 두고 본문에서 figures/이름.png 로 건다.")
    else:
        report_line = f"보고서: {att / 'report.md'} 에 {prompts.REPORT_FILE} 규격대로 쓴다(한국어 평서체, A4 두 장 안). 그림은 {att / 'figures'}/ 에 PNG로 둔다."
    return "\n".join([
        report_line,
        prompts.wording_note(),
        *prompts.REPORT_GUIDE,
        prompts.ATTACK_NOTE,
        prompts.CONCURRENCY_NOTE,
        prompts.GPU_SIGNAL_NOTE.format(run_id=run_id),
        *prompts.local_rules(),
        f"웹 화면 찍기: uv run --project {ROOT.as_posix()} --with playwright python {ROOT.as_posix()}/tools/md_shot.py --url <주소> --height 1400 --out {att / 'figures' / '화면-결과.png'}",
        f"끝나면 {att / 'result.json'} 에 아래 JSON을 쓴다. 진행 중 메모는 같은 폴더의 progress.md다.",
        prompts.STEP_NOTE,
        "```json",
        json.dumps(prompts.RESULT_SCHEMA, ensure_ascii=False, indent=2),
        "```",
        prompts.RESULT_WRITE,
        *draft_line,
    ])


def resolve_parent(project: str, name: str) -> str:
    """--parent로 받은 이름을 같은 프로젝트의 할 일 줄, 메모, 실행 기록 제목에서 찾는다. `프로젝트::이름` key도 받는다.

    이름이 똑같은 것이 먼저이고, 없으면 받은 글자가 든 것이 하나뿐일 때 그것이다. 없거나 여럿이면 LookupError다.
    옛 주간 계획 파일의 메모 항목에서 찾던 것을 261025-jipsa-42에서 할 일 파일과 실행 기록으로 바꿨다.
    """
    from scheduler import record, todo

    name = name.strip()
    if "::" in name:
        p, _, name = name.partition("::")
        if p.strip() != project:
            raise LookupError(f"부모는 같은 프로젝트의 일이어야 한다: {p.strip()}")
        name = name.strip()
    rows, _, _ = todo.load()
    names = [it.text for it in rows if it.project == project] + [m.text for m in todo.memos()]
    names += [str(m.get("title") or "") for m in record.list_runs(limit=0, project=project)]
    names = list(dict.fromkeys(n for n in names if n))
    if name in names:
        return name
    part = [n for n in names if name in n]
    if len(part) == 1:
        return part[0]
    why = f"여러 일에 걸린다({', '.join(part[:5])})" if part else "일이 없다(할 일 줄, 메모, 실행 기록 제목에서 찾는다)"
    raise LookupError(f"{project}에 부모 '{name}' {why}")


def cmd_begin(args) -> int:
    from scheduler import record, workitem
    from scheduler.registry import load

    project = load(args.project)
    # 사용 창 비율로 시작을 막지 않는다(261102-jipsa-32, 42, 50 사용자 답)
    # 사람 입력의 '초안'(261029-jipsa-35). hook과 답 대기 명령이 세션 기록에 남긴 요청을 읽는다. '초안'은 결과지 초안 보기다
    from scheduler import draftask, sessionproc

    session_run = sessionproc.session_run_from_env()
    session_meta = record.meta_of(session_run) if session_run else None
    ask = None if args.no_draft else draftask.pending(session_meta)
    sheet_ask = bool(ask and ask["kind"] == draftask.SHEET)
    draft = bool(args.draft) or sheet_ask
    todo_item = None
    if args.todo:  # Do 요청으로 받은 할 일 줄. 시작하면 줄을 파일에서 빼고 실행 기록에 원문을 남긴다
        from scheduler import todo

        try:
            items, _, _ = todo.load()
            todo_item = next((it for it in items if it.key == args.todo), None) or todo.find(args.todo, items)
        except todo.TodoError as e:
            _print(f"시작하지 않았다: --todo 줄을 찾지 못했다({e})")
            return 1
    # Do로 시킨 단발 줄의 문장에 초안 요청이 있으면 --draft와 같다(261103-jipsa-07). 스케줄러 작업자 경로는 auto.entry가 같은 판정을 쓴다
    line_draft = bool(todo_item is not None and not args.no_draft and not args.draft and not todo_item.cycle
                      and draftask.line_wants(project.name, todo_item.text, todo_item.criteria))
    draft = draft or line_draft
    parent = ""
    if args.parent:  # 할 일 줄, 메모, 실행 기록 제목에서 찾아 meta의 parent_item에만 건다
        try:
            parent = resolve_parent(project.name, args.parent)
        except LookupError as e:
            _print(f"시작하지 않았다: {e}")
            return 1
    mb = None
    if args.games or args.parallel:
        from scheduler import matchcap

        if not project.match_minutes:
            _print(f"시작하지 않았다: {project.name} 등록부에 판 시간 표([match_minutes])가 없어 --games를 쓸 수 없다. --est로 준다")
            return 1
        try:
            mb = matchcap.budget(matchcap.parse_games(args.games or ""), args.parallel or 0, project.match_minutes)
        except matchcap.GamesError as e:
            _print(f"시작하지 않았다: {e}" + ("" if args.parallel else ". --parallel(동시 판 수)도 준다"))
            return 1
    # 세션이 연 작업은 큐 줄과 meta만 만든다(261025-jipsa-36). 주간 계획 파일은 261025-jipsa-42에서 뗐다
    meta = record.begin(project, args.title, args.criteria, executor=args.executor, est_minutes=args.est, model=args.model or "", parent=parent,
                        category=args.kind or "", pick=args.pick, match_budget=mb)
    if args.agent:  # 멈춤 알림이 깨울 서브에이전트 이름을 같이 찍는다
        meta["agent"] = args.agent
    if draft:  # finish가 preview_url을 대조한다
        meta["draft"] = True
        if ask:
            meta["draft_ask"] = {k: ask[k] for k in ("text", "ts", "via")}
    if ask and session_meta is not None:  # 요청은 한 실행에만 쓴다
        session_meta["draft_ask"] = {**ask, "used_by": meta["run_id"]}
        record.write_json(record.RUNS / session_run / "meta.json", session_meta)
    if todo_item is not None:
        from scheduler import todo

        meta.update(todo_key=todo_item.key, todo_line=todo_item.line(), from_do=True)
        todo.take(todo_item.key)
        record.do_begun(todo_item.key, meta["run_id"])
    if args.agent or todo_item is not None or draft:
        record.write_json(record.RUNS / meta["run_id"] / "meta.json", meta)
    _print(f"시작 기록: {meta['run_id']} | {project.name} | {args.title} | 상한 {meta['minutes_limit']}분 | 주체 {record.EXECUTORS.get(args.executor, args.executor)}")
    if todo_item is not None:
        _print(f"할 일 줄을 파일에서 뺐다: {todo_item.line()}")
    _print(_gpu_register(project, meta))
    _print(f"분류: {workitem.category_text(meta['category'], meta['pick'], meta['category_guess'])}"
           + (" (제목 낱말로 추정했다. 세션이 정하면 --kind로 넣는다)" if meta["category_guess"] else ""))
    if mb:
        _print(f"판 수 상한: {matchcap.rows_text(mb)}")
        _print(f"계산: {matchcap.formula_text(mb)}")
        if mb["defaulted"]:
            _print(f"판 시간 표에 없어 기본값 {matchcap.DEFAULT_MATCH_MIN:g}분을 썼다: {', '.join(mb['defaulted'])}. 재고 나면 등록부 [match_minutes]에 더한다")
        if args.est is not None:
            _print(f"--est {args.est}분은 쓰지 않았다. --games를 주면 판 수 계산이 상한이다")
        _print(f"새 판 시작 마감: {meta['match_budget']['stop_new_at'].replace('T', ' ')} (시작 + 계산 예산 {mb['compute_minutes']}분). 이 시각 뒤에는 새 판을 띄우지 않고 남은 판이 끝나면 마무리한다. 서브에이전트 지시에 넣는다")
    if parent:
        _print(f"부모: {parent} (실행 기록에만 걸었다)")
    if draft:
        _print("초안 실행: 결과지 '초안 보기'로 열 HTML 초안과 result.json preview_url이 있어야 마감된다"
               + (f" (사람 입력 \"{ask['text'][:60]}\"에서 표시했다. 초안이 아닌 일이면 --no-draft로 다시 연다)" if sheet_ask and not args.draft else "")
               + (f" (할 일 줄 \"{todo_item.text[:60]}\"에서 표시했다. 초안이 아닌 일이면 --no-draft로 다시 연다)" if line_draft else "")
               + ". 아래 규격의 초안 줄을 서브에이전트 지시에 넣는다")
    if args.executor == "subagent":  # 대화 요약 뒤 모델 지정이 빠지지 않게 세션에 매번 알린다(261102-jipsa-33)
        _print(f"Agent 호출 model: 인자에 {args.model}을(를) 명시한다. 생략하면 세션 모델을 물려받는다" if args.model
               else "Agent 호출 model: --model 없이 열었다. 그래도 Agent 호출에 model 인자를 정해 명시한다. 생략하면 세션 모델을 물려받는다")
    _print(_result_block(meta["run_id"], args.executor, draft=draft))
    _print(f"끝나면: 보고서를 옮겨 쓰고 uv run jipsa attack {meta['run_id']}, 공격 글을 같은 서브에이전트에게 보내 답을 받은 뒤 "
           f"uv run jipsa finish {meta['run_id']}" + (" --agent <서브에이전트 이름>" if args.executor == "subagent" else ""))
    from scheduler import sessionproc

    # 이 세션의 Claude Code 프로세스 아래에 답 대기 명령이 없으면 띄우라고 끝에 한 줄 남긴다(261025-jipsa-13 1안). 직접 띄우지 않는다
    wait_line = sessionproc.missing_wait_line(sessionproc.session_run_from_env())
    if wait_line:
        _print(wait_line)
    return 0


def _gpu_register(project, meta: dict) -> str:
    """세션 실행을 GPU 장부에 적는다(261026-jipsa-26). 프로젝트 GPU 요구량(등록부, 지난 실측 최댓값)이 0이면 적지 않는다.
    프로세스 번호는 이 세션의 Claude Code 프로세스다. 자리가 모자라도 막지 않고 알린다. finish가 돌려준다."""
    from scheduler import resources, sessionproc

    project = resources.with_peak(project)
    if not project.needs_gpu or not (project.gpu_vram_gb or project.gpu_exclusive):
        return "GPU 장부: 요구량 0이라 적지 않았다"
    ok, why = resources.can_acquire(project)
    claude = sessionproc.claude_proc()
    resources.acquire(project, meta["run_id"], claude.pid if claude else None, int(meta.get("minutes_limit") or 90),
                      pid_kind="session", check=False)
    need = resources.need_gb(project)
    return f"GPU 장부: {need:g}GB를 적었다" + ("" if ok else f". 주의: {why}. 서브에이전트가 GPU를 쓰면 다른 작업과 겹칠 수 있다")


def cmd_gpu(args) -> int:
    """jipsa gpu signal <실행ID> --kind 학습 [--gb N] [--wait 분] [--done]. 큰 GPU 일 시작과 끝 신호(261029-jipsa-07).
    작업자와 세션 서브에이전트가 학습, 대량 추론, 모델 서버 띄우기 직전에 보낸다. 스케줄러가 그 실행의 GPU 예약을 지난 최댓값으로 올리고
    관찰 시간 동안 새 GPU 작업을 들이지 않은 채 실제 사용량을 보고, 그 최댓값 + 1GB로 고친다. --wait이면 남은 메모리가 0 이상이 될 때까지 기다린다."""
    import json
    import time

    from scheduler import resources, sessionproc
    from scheduler.config import GPU_PAD_GB, GPU_SIGNAL_MIN, RUNS
    from scheduler.registry import load

    run_id = args.run_id
    if args.done:
        r = resources.signal_done(run_id)
        if r is None:
            _print(f"GPU 신호: {run_id}의 GPU 예약 줄이 없다. 이미 끝났거나 GPU를 잡지 않은 실행이다")
            return 1
        _print(f"GPU 신호 끝: {run_id}. GPU 예약을 {r['was']:g}GB에서 {r['amount']:g}GB로 돌렸다")
        return 0
    project = None
    if not any(r.get("run") == run_id for r in resources.leases()):
        try:
            meta = json.loads((RUNS / run_id / "meta.json").read_text(encoding="utf-8"))
            project = load(meta["project"])
        except (OSError, ValueError, KeyError):
            _print(f"GPU 신호: {run_id}의 GPU 예약 줄도 실행 기록도 없다")
            return 1
    claude = sessionproc.claude_proc() if project is not None else None
    info = resources.signal(run_id, args.kind, args.gb, wait=args.wait > 0, project=project, pid=claude.pid if claude else None)
    if info is None:
        _print(f"GPU 신호: {run_id}의 GPU 예약 줄이 없다")
        return 1
    moved = f"{info['was']:g}GB에서 {info['amount']:g}GB로 올렸다" if info["amount"] > info["was"] else f"{info['amount']:g}GB로 둔다"
    _print(f"GPU 신호: {run_id} {args.kind}. GPU 예약을 {moved}. 남은 메모리 {info['free']:.1f}GB")
    if info["waiting"]:
        _print(f"남은 메모리가 모자라 최대 {args.wait:g}분 기다린다. 그동안 새 GPU 작업을 들이지 않는다")
        deadline = time.monotonic() + args.wait * 60
        while True:
            r = resources.signal_ready(run_id)
            if r is None or r["ready"] or time.monotonic() >= deadline:
                break
            time.sleep(15)
        if r is not None and not r["ready"]:
            # 자리가 나지 않았으면 신호를 거둔다. 기다리는 줄이 남으면 새 GPU 작업을 계속 막는다
            resources.signal_done(run_id)
            _print(f"자리 없음: {args.wait:g}분이 지나도 남은 메모리가 {r['free']:.1f}GB다. 큰 GPU 일을 시작하지 않는다. "
                   f"신호를 거두고 GPU 예약을 관찰 값으로 돌렸다. 배치를 줄여 --gb를 낮추거나 잠시 뒤 다시 신호를 보낸다")
            return 2
        if r is not None:
            info["until"] = r["until"]
    elif info["free"] < 0:
        _print("주의: 남은 메모리가 0 아래다. --wait 분을 주면 자리가 날 때까지 기다린다")
    _print(f"관찰: {info['until'][11:16]}까지({GPU_SIGNAL_MIN}분) 새 GPU 작업을 들이지 않고 실제 사용량을 보고, GPU 예약을 그 최댓값 + {GPU_PAD_GB:g}GB로 고친다. "
           f"일이 끝나면 jipsa gpu signal {run_id} --done")
    return 0


def cmd_install_lock(args) -> int:
    """jipsa install-lock <프로젝트> -- <설치 명령>. 프로젝트의 공용 가상환경에 패키지를 설치하는 동안 잠금을 잡는다(261026-jipsa-26).
    코드와 실험 프로젝트는 실행마다 작업 폴더가 따로지만 원본 저장소의 가상환경을 같이 쓴다. 같은 가상환경을 두 작업이 동시에 고치지 않게
    잠금 파일(상태 폴더 locks/)을 만들고, 이미 있으면 풀릴 때까지 기다린다(기본 10분). 잡은 프로세스가 죽은 잠금은 버린다. 명령은 창 없이 돌린다."""
    import hashlib
    import json
    import time

    import psutil

    from scheduler.config import STATE
    from scheduler.registry import load

    raw = list(args.command or [])  # 프로젝트 뒤를 모두 받으므로 -- 앞의 --wait는 여기서 읽는다
    pre, cmd = (raw[:raw.index("--")], raw[raw.index("--") + 1:]) if "--" in raw else ([], raw)
    if "--wait" in pre and pre.index("--wait") + 1 < len(pre):
        args.wait = float(pre[pre.index("--wait") + 1])
    if not cmd:
        _print("돌리지 않았다: 설치 명령이 필요하다. jipsa install-lock <프로젝트> -- <설치 명령>")
        return 1
    project = load(args.project)
    venv = (project.path / project.deps_venv).resolve()
    lock = STATE / "locks" / f"venv-{hashlib.sha1(str(venv).lower().encode()).hexdigest()[:12]}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.wait * 60
    told = False
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, json.dumps({"pid": os.getpid(), "venv": str(venv), "cmd": " ".join(cmd)[:200]}).encode("utf-8"))
            os.close(fd)
            break
        except FileExistsError:
            try:
                held = json.loads(lock.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                held = {}
            if held.get("pid") and not psutil.pid_exists(int(held["pid"])):
                lock.unlink(missing_ok=True)  # 잡은 프로세스가 죽었다
                continue
            if time.monotonic() >= deadline:
                _print(f"돌리지 않았다: {args.wait:g}분 동안 다른 설치가 가상환경 잠금을 잡고 있었다(pid {held.get('pid')}, {held.get('cmd', '')})")
                return 1
            if not told:
                _print(f"다른 설치가 끝나기를 기다린다(pid {held.get('pid')}): {held.get('cmd', '')}")
                told = True
            time.sleep(2)
    try:
        _print(f"가상환경 잠금을 잡았다: {venv}")
        r = subprocess.run(cmd, cwd=os.getcwd(), check=False, **hidden())
        return r.returncode
    finally:
        lock.unlink(missing_ok=True)


def cmd_topic(args) -> int:
    """세션이 지금 하는 일을 짧은 이름과 소속 프로젝트로 건다. 기록은 hook이 이 출력 줄을 읽어 자기 세션에 적는다(어느 세션인지는 hook만 안다)."""
    from scheduler.registry import load_all

    if args.done:
        return _topic_done(args.at)
    title = " ".join((args.title or "").split())[:40]
    if not title:
        _print("이름이 비었다")
        return 1
    if not args.project:
        _print("--project가 필요하다. 주제를 닫으려면 --done")
        return 1
    names = sorted(load_all())
    if args.project != "기타" and args.project not in names:
        _print(f"등록부에 없는 프로젝트다: {args.project}. 고를 수 있는 값: {', '.join(names)}, 기타")
        return 1
    _print(f"세션 주제: {title} | 프로젝트: {args.project}")
    return 0


def _topic_done(at: str | None) -> int:
    """걸린 주제를 닫는다. --at이 없으면 지금, "HH:MM"이면 오늘 그 시각, ISO 시각이면 그대로다. 미래 시각은 받지 않는다."""
    from datetime import datetime

    t = now().replace(microsecond=0)
    if at:
        try:
            t = datetime.combine(t.date(), datetime.strptime(at.strip(), "%H:%M").time()) if ":" in at and len(at.strip()) <= 5 else datetime.fromisoformat(at.strip())
        except ValueError:
            _print(f"주제 닫기 실패: 시각을 읽지 못했다: {at}. HH:MM 또는 ISO 시각으로 준다")
            return 1
        if t.tzinfo is not None:
            t = t.replace(tzinfo=None)
        if t > now():
            _print(f"주제 닫기 실패: 미래 시각이다: {t.isoformat(timespec='seconds')}")
            return 1
    _print(f"세션 주제 닫힘: {t.replace(microsecond=0).isoformat(timespec='seconds')}")
    return 0


def cmd_finish(args) -> int:
    from pathlib import Path as _P

    from scheduler import record
    from scheduler.config import parse_iso

    meta = record.meta_of(args.run_id)
    if not meta:
        _print(f"runs/{args.run_id}가 없다")
        return 1
    if args.reopen:
        try:
            meta = record.reopen(args.run_id, notify=not args.no_slack)
        except (ValueError, record.ResultMissing) as e:
            _print(f"다시 열지 못했다: {e}")
            return 1
        _print(f"다시 마감: {meta['status']} | {meta['summary']} | {meta['evidence_ref']}")
        _print(f"결과지: runs/{args.run_id}/result.md" + _slack_note(args.no_slack, meta, "Slack 정정 요약 글 전송"))
        return 0
    if meta.get("status") != "진행 중":
        _print(f"{args.run_id}는 이미 {meta['status']}다. 결과 파일을 고쳤으면 --reopen으로 다시 마감한다")
        return 1
    why = "" if args.status else record.result_problem(args.run_id)
    if why:
        _print(f"{why}. 서브에이전트에게 쓰게 한 뒤 다시 마감한다. 기록은 진행 중으로 둔다"
               " (일부러 상태를 고르려면 --status와 --summary를 준다)")
        return 2
    why = "" if args.status else record.draft_problem(args.run_id)  # 초안 실행의 초안 보기 주소(261029-jipsa-35)
    if why:
        _print(f"{why}. 서브에이전트에게 preview_url을 채우게 한 뒤 다시 마감한다. 기록은 진행 중으로 둔다"
               " (초안 없이 닫으려면 --status와 --summary를 준다)")
        return 2
    tpath = _P(args.transcript) if args.transcript else (record.find_transcript(args.agent, parse_iso(meta["started"])) if args.agent else None)
    if args.agent and not tpath:
        _print(f"서브에이전트 기록을 찾지 못했다: {args.agent}. 토큰과 도구 호출 없이 마감한다")
    if tpath:
        info = record.import_transcript(args.run_id, tpath, status=args.status or "")
        _print(f"기록 들여옴: 도구 호출 {len(info['tools'])}개, 호출 {info['usage']['calls']}회, 출력 토큰 {info['usage']['output']:,}, 모델 {info['model'] or '?'}")
    result = {}
    if args.summary:
        result["summary"] = args.summary
    meta = record.finish(args.run_id, status=args.status, result=result or None, notify=not args.no_slack, require=True)
    _print(f"마감: {meta['status']} | {meta['summary']} | {meta['evidence_ref']} | {time_text(meta['minutes_used'], meta['minutes_limit'])}")
    att = record.attempt_dirs(args.run_id)[-1]
    from scheduler import attack

    a = meta.get("attack")
    if not a:
        _print("주의: Sol 공격 기록이 없다. 마감 전 uv run jipsa attack을 거치지 않았다")
    else:
        _print(f"Sol 공격: {attack.short(a)}" + (f" | 주의: 답 없는 지적 {a['unanswered']}개" if a.get("unanswered") else ""))
    if not (att / "report.md").exists():
        _print("주의: report.md가 없다. 보고서 규격(policies/report.md)대로 써야 결과지가 생긴다")
    elif not list((att / "figures").glob("*.png")):
        _print("주의: figures/에 그림이 없다. 그림이 뜻이 없는 작업이면 보고서 도입에 그 이유가 있어야 한다")
    if (meta.get("wording") or {}).get("note"):
        _print(meta["wording"]["note"])
    _print(f"결과지: runs/{args.run_id}/result.md" + _slack_note(args.no_slack, meta))
    return 0


def cmd_attack(args) -> int:
    """마감 전 Sol 공격 한 번(261024-jipsa-11). 결과를 시도 폴더에 남기고, 같은 서브에이전트에게 보낼 글을 찍는다."""
    from scheduler import attack, record

    meta = record.meta_of(args.run_id)
    if not meta:
        _print(f"runs/{args.run_id}가 없다")
        return 1
    if meta.get("status") != "진행 중":
        _print(f"{args.run_id}는 이미 {meta['status']}로 마감했다. 공격은 마감 전에 한 번만 한다")
        return 1
    why = record.result_problem(args.run_id) or record.draft_problem(args.run_id)
    if why:
        _print(f"{why}. 서브에이전트가 result.json을 쓴 뒤 공격한다")
        return 2
    att = record.attempt_dirs(args.run_id)[-1]
    data = attack.run(meta, att)
    done = f"uv run jipsa finish {args.run_id}" + (f" --agent {meta['agent']}" if meta.get("agent") else " --agent <서브에이전트 이름>")
    if data["state"] != "있음":
        _print(f"공격 없음({data.get('why')}). 막지 않는다. 그대로 마감한다: {done}")
        return 0
    if data.get("again"):
        _print("이미 공격했다. 공방은 한 번이라 Sol을 다시 부르지 않는다. 아래는 앞 공격 그대로다")
    fs = data.get("findings") or []
    _print(f"공격: 판정 {data['verdict']}, 지적 {len(fs)}개 | 기록 {(att / attack.ATTACK_MD).as_posix()}")
    if not fs:
        _print(f"지적이 없다. 답 없이 마감한다: {done}")
        return 0
    who = meta.get("agent") or "<그 서브에이전트>"
    _print(f"아래 글을 SendMessage로 같은 서브에이전트({who})에게 그대로 보낸다. 답이 오면 고친 보고서를 다시 옮겨 쓰고 {done}")
    _print("---")
    _print(attack.reply_prompt(meta, att, subagent=meta.get("executor", "worker") != "worker"))
    return 0


def cmd_record(args) -> int:
    """지난 작업을 뒤늦게 들여온다. begin과 finish를 시각을 지정해 한 번에 한다."""
    import json
    from pathlib import Path as _P

    from scheduler import record
    from scheduler.config import parse_iso
    from scheduler.registry import load

    project = load(args.project)
    started = parse_iso(args.started)
    finished = parse_iso(args.finished)
    meta = record.begin(project, args.title, args.criteria, executor=args.executor, est_minutes=args.est, started=started, model=args.model or "")
    run_id = meta["run_id"]
    result = json.loads(_P(args.result).read_text(encoding="utf-8")) if args.result else {}
    if args.status:
        result["status"] = args.status
    if args.summary:
        result["summary"] = args.summary
    if args.report:
        (record.RUNS / run_id / "attempt-1").mkdir(parents=True, exist_ok=True)
        (record.RUNS / run_id / "attempt-1" / "report.md").write_text(_P(args.report).read_text(encoding="utf-8"), encoding="utf-8")
    if args.transcript:
        info = record.import_transcript(run_id, _P(args.transcript), status=result.get("status", ""), minutes=max(0, int((finished - started).total_seconds() // 60)))
        _print(f"기록 들여옴: 도구 호출 {len(info['tools'])}개, 출력 토큰 {info['usage']['output']:,}")
    meta = record.finish(run_id, result=result, finished=finished, notify=not args.no_slack)
    _print(f"들여옴: {run_id} | {meta['status']} | {meta['summary']} | {meta['minutes_used']}분" + _slack_note(args.no_slack, meta))
    return 0


def cmd_dry_run(args) -> int:
    from scheduler import queue, record, resources, runner
    from scheduler.registry import load

    ensure_dirs()
    project = load(args.project)
    item = record._loose_item(project.name, args.title, args.criteria, args.est, "", None)  # 주간 계획 파일에 줄을 더하지 않는다(261025-jipsa-42)
    entry = queue.add(item, project)
    run_id = runner.new_run_id(project.name)
    ok, why = resources.can_acquire(project)
    if not ok:
        _print(f"자원을 얻지 못했다: {why}")
        return 1
    resources.acquire(project, run_id, None, args.est or project.total_minutes)
    _print(f"모의 실행 {run_id} 시작. 커밋하지 않는다. 작업 폴더와 runs/{run_id}만 만든다.")
    meta = runner.run_task(project, entry, run_id=run_id, dry_run=True)
    _print(f"결과: {meta.get('status')} | {meta.get('summary')} | {meta.get('evidence_ref')} | {meta.get('minutes_used')}분")
    _print(f"기록: runs/{run_id}/  작업 폴더: {meta.get('workspace')}")
    return 0


def cmd_check(args) -> int:
    from scheduler import todo
    from scheduler.registry import load_all

    ok = True

    def line(label: str, good: bool, detail: str = "", optional: bool = False) -> None:
        nonlocal ok
        ok = ok and (good or optional)  # 선택 항목은 없어도 종료 코드에 영향을 주지 않는다
        _print(f"  [{'OK' if good else '선택' if optional else '확인'}] {label} {detail}")

    _print("jipsa 점검")
    for tool in ("claude", "codex", "uv", "git", "nvidia-smi"):
        path = shutil.which(tool)
        none = {"codex": "없음. 선택 항목이고 공격 공급자 codex는 none과 같게 돈다", "nvidia-smi": "없음. GPU는 선택 항목이다. GPU를 쓰는 작업만 영향을 받는다"}.get(tool, "없음")
        line(tool, bool(path), path or none, optional=tool in ("codex", "nvidia-smi"))
    line("RULES.md", RULES_FILE.exists())
    line("AGENTS.md(RULES.md 사본)", AGENTS_FILE.exists(), "" if AGENTS_FILE.exists() else "Codex 작업자를 쓸 때만 필요하다. jipsa sync-agents로 만든다", optional=True)
    line("policies/claude_settings.json", SETTINGS_FILE.exists())
    line("Slack Webhook", bool(SLACK_WEBHOOK), "" if SLACK_WEBHOOK else ".env의 JIPSA_SLACK_WEBHOOK이 비어 있다. 보고는 reports/에만 남는다", optional=True)
    try:
        reg = load_all()
        line("등록부", bool(reg), f"{len(reg)}개: {', '.join(reg)}")
        for p in reg.values():
            if not p.path.exists():
                line(f"  {p.name} 경로", False, str(p.path) + (" (예시 등록부라 내 프로젝트를 등록하면 지워도 된다)" if p.name == "example_app" else ""), optional=p.name == "example_app")
            if p.questions:
                _print(f"    {p.name} 확인 필요: " + " / ".join(p.questions))
    except Exception as e:  # noqa: BLE001
        line("등록부", False, str(e))
    rows_t, bad_t, have = todo.load()
    line("할 일 파일", not bad_t, (f"{todo.TODO_FILE.name}: 줄 {len(rows_t)}개, 메모 {len(todo.memos())}개" + (f", 읽지 못한 줄 {len(bad_t)}개" if bad_t else ""))
         if have else "아직 없다. jipsa todo add로 넣으면 만든다")
    if args.llm:
        from adapters import claude, codex
        from adapters.base import AdapterError

        try:
            t = claude.judge("한 단어로 답한다: 준비")
            line("Claude 판정 호출", True, t[:30])
        except AdapterError as e:
            line("Claude 판정 호출", False, str(e)[:120])
        try:
            t = codex.ask("한 단어로 답한다: 준비", timeout=180)
            line("Codex 호출", True, t[:30])
        except AdapterError as e:
            line("Codex 호출", False, str(e)[:120], optional=True)
    _print("끝" if ok else "확인할 항목이 있다")
    return 0 if ok else 1


def cmd_sync_agents(args) -> int:
    text = RULES_FILE.read_text(encoding="utf-8")
    body = text.split("\n", 1)[1] if text.startswith("#") else text
    AGENTS_FILE.write_text("# AGENTS.md\n\nRULES.md에서 생성한 사본이다. 손으로 고치지 않는다. `uv run jipsa sync-agents`로 다시 만든다.\n" + body, encoding="utf-8")
    _print(f"AGENTS.md를 RULES.md에서 다시 만들었다 ({len(body)}자)")
    return 0


def cmd_worktrees(args) -> int:
    from scheduler.registry import load_all

    reg = load_all()
    found = sorted(WORKTREES.glob("*")) if WORKTREES.exists() else []
    if not found:
        _print("worktree 없음")
        return 0
    for wt in found:
        _print(f"  {wt.name}")
    if args.remove:
        target = WORKTREES / args.remove
        meta = _meta(args.remove) or {}
        project = reg.get(meta.get("project", ""))
        if project is None:
            _print("등록부에서 프로젝트를 찾지 못해 git worktree remove를 직접 부른다")
            subprocess.run(["git", "worktree", "remove", "--force", str(target)], check=False, **hidden())
        else:
            from scheduler import workspace

            workspace.remove_worktree(project, target, delete_branch=args.delete_branch, branch=meta.get("branch", ""))
        _print(f"{args.remove} 제거")
    return 0


def cmd_prune(args) -> int:
    from scheduler import prune

    runs_dir = Path(args.runs_dir) if args.runs_dir else None
    items = prune.plan(runs_dir, run_days=args.run_days, other_days=args.other_days, archive_days=args.archive_days)
    _print(f"{'처리':10} {'종류':8} {'마지막 활동':10}  {'대상':32} 까닭")
    for it in items:
        _print(f"{it.action:10} {it.kind:8} {it.last.isoformat():10}  {it.path.name:32} {it.why}{' -> ' + it.bundle if it.bundle else ''}")
    todo = [it for it in items if it.action in (prune.ARCHIVE, prune.DELETE)]
    if not args.apply:
        _print(f"미리보기다. 대상 {len(todo)}개. 실제로 하려면 --apply를 붙인다")
        return 0
    for line in prune.apply(todo, runs_dir):
        _print(line.replace("\t", " "))
    return 0


def cmd_runs_clean(args) -> int:
    from scheduler import runsclean

    runs_dir = Path(args.runs_dir) if args.runs_dir else None
    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()] if args.kinds else None
    bad = [k for k in kinds or [] if k not in runsclean.KINDS]
    if bad:
        _print(f"모르는 종류: {', '.join(bad)}. 고를 수 있는 종류: {', '.join(runsclean.KINDS)}")
        return 2
    s = runsclean.settings()
    _print(f"설정: 자동 {'켜짐' if s['on'] else '꺼짐'}, 보관 {s['days'] if args.days is None else args.days}일, "
           f"종류 {', '.join(kinds or s['kinds'])}, 최소 {s['min_mb'] if args.min_mb is None else args.min_mb}MB")
    try:
        items = runsclean.plan(runs_dir, days=args.days, kinds=kinds, min_mb=args.min_mb)
    except runsclean.TrackedError as e:
        _print(str(e))
        return 2
    show = [it for it in items if it.action != runsclean.KEEP or args.all]
    for it in show:
        _print(f"{it.action:6} {it.size / 2**20:8.1f}MB  {it.rel:60} {it.why}")
    tot: dict[str, list[int]] = {}
    for it in items:
        if it.size or it.action != runsclean.KEEP:
            tot.setdefault(it.action, [0, 0])
            tot[it.action][0] += 1
            tot[it.action][1] += it.size
    _print("합계: " + ", ".join(f"{k} {n}건 {b / 2**20:.1f}MB" for k, (n, b) in tot.items()))
    if not args.apply:
        _print(f"미리 보기다. 옮김 줄만 휴지통 폴더({runsclean.trash_dir(pattern=args.trash).as_posix()})로 옮기려면 --apply를 붙인다")
        return 0
    rec = runsclean.apply(items, runs_dir, runsclean.trash_dir(pattern=args.trash) if args.trash else None)
    _print(f"옮김 {rec['moved']}건 {rec['bytes'] / 2**20:.1f}MB -> {rec['trash']} (목록 moved.tsv)")
    for f in rec["fails"]:
        _print(f"못 옮김 {f}")
    return 1 if rec["fails"] else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="jipsa", description="jipsa 명령")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("run", help="스케줄러 루프를 돌린다 (보통은 jipsa web이 띄운다. 이미 돌고 있으면 바로 끝난다)")
    s.add_argument("--concurrency", type=int, default=None)
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("console", help="상태 줄, 타임라인, 트리 화면")
    s.add_argument("--once", action="store_true", help="한 번만 그리고 끝낸다")
    s.set_defaults(fn=cmd_console)

    s = sub.add_parser("status", help="모드, 큐, 리스, 자원")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("web", help="브라우저 화면. 타임라인, 트리, 확인 필요, 지난 날짜 재생")
    s.add_argument("--port", type=int, default=None, help="대시보드 포트. 비우면 설정 JIPSA_WEB_PORT(기본 8765)다")
    s.add_argument("--no-open", action="store_true", help="브라우저를 자동으로 열지 않는다")
    s.add_argument("--no-watch", action="store_true", help="스케줄러 감시와 자동 띄우기를 끈다(화면 미리보기용)")
    s.set_defaults(fn=cmd_web)

    s = sub.add_parser("todo", help="할 일 파일. 인자 없으면 번호 목록, add <프로젝트> <할 일 문장> | <기준> | cycle .. | 한도 .., rm <번호|문장 일부>, "
                       "memo <글>, memo-rm <번호|글 일부>, up <메모 번호|글 일부> <프로젝트> | <기준>, "
                       "cycle <번호|문장 일부> [<지표>] [<목표값>] [이상|이하] [상한 N] (비운 칸은 첫 분석이 정한다, off면 비운다), "
                       "run <번호|문장 일부> [시작 HH:MM] [마감 HH:MM|+4h](그 줄을 시킨다. 일회성은 바로, Cycle은 시작과 마감 사이에 돈다), "
                       "stop <번호|문장 일부>(시킨 Cycle을 멈춘다. 다시 시키면 잇는다), until <번호|문장 일부> <HH:MM|+4h>(마감을 고친다), "
                       "feedback <번호|문장 일부> | <글>(도는 Cycle의 다음 분석과 명령에 사람 피드백을 넣는다). 넣기만 해서는 돌지 않는다")
    s.add_argument("words", nargs=argparse.REMAINDER, help="동작과 인자. 따옴표 없이 여러 낱말로 와도 공백으로 합친다")
    s.set_defaults(fn=cmd_todo)

    s = sub.add_parser("answer", help="확인 필요에 답을 넣어 이어 돌린다. 선택지나 정할 것이 있는 완료와 실패 실행은 답을 받은편지함으로 세션에 넘기고, 세션이 2분 안에 받지 않으면 작업자로 넘긴다. --undo로 답을 물린다")
    s.add_argument("run_id")
    s.add_argument("answer", nargs="?", default="")
    s.add_argument("--undo", action="store_true", help="잘못 넣은 답을 물린다. 확인 필요였던 실행은 확인 필요로 되돌리고(세션과 서브에이전트 실행만), 끝난 실행은 답만 지운다")
    s.add_argument("--close", action="store_true", help="이어 돌리지 않고 완료로 닫는다. 답을 이미 다른 실행이 처리한 작업자 실행에 쓴다(답을 넣어 처리 대기인 실행 포함)")
    s.set_defaults(fn=cmd_answer)

    s = sub.add_parser("registry", help="등록부 고치기. add <프로젝트> <칸> <문구> --run <실행ID>는 그 실행의 사람 답과 고른 안에 따옴표로 적힌 문구만 "
                       "정해진 목록 칸(external.read, external.forbid, scope.notes, paths.no_read, paths.read_only, questions.items) 끝에 더한다. 메인 세션 전용이고 작업자 셸에서는 거절한다")
    rs = s.add_subparsers(dest="action", required=True)
    a = rs.add_parser("add", help="승인 원문과 같은 문구 한 줄을 목록 칸 끝에 더한다. 더한 줄 끝에 승인 실행을 붙인다")
    a.add_argument("project", help="등록부 이름(projects/<이름>.toml)")
    a.add_argument("field", help="목록 칸. 예: external.read")
    a.add_argument("line", help="더할 문구. 승인 원문과 글자까지 같아야 한다")
    a.add_argument("--run", required=True, help="사람 답이 기록된 승인 실행ID")
    a.add_argument("--dry-run", action="store_true", help="쓰지 않고 더할 줄만 보인다")
    a = rs.add_parser("show", help="등록 목록, 또는 이름을 주면 그 등록의 칸 19개와 값")
    a.add_argument("project", nargs="?", default="", help="등록 이름")
    a = rs.add_parser("new", help="새 등록을 만든다. 메인 세션 전용. 이름만 주면 폴더를 만들고 git 첫 커밋까지 하며 종류는 code다. 있는 폴더는 건드리지 않고 등록한다. path를 주면 폴더를 만들지 않는다. 예: registry new my_app")
    a.add_argument("project", help="등록 이름. 영문 소문자, 숫자, 밑줄")
    a.add_argument("pairs", nargs="*", help="'칸=값'. 칸은 scope.auto 꼴이나 자동 범위 같은 한글 이름이다. 목록 칸은 '칸+=값'으로 더한다")
    a.add_argument("--check", action="store_true", help="쓰지 않고 만들 글만 보인다")
    a = rs.add_parser("edit", help="등록의 바뀐 키 줄만 고친다. 메인 세션 전용. 예: registry edit ocr_new priority=40 external.read+=로컬")
    a.add_argument("project", help="등록 이름")
    a.add_argument("pairs", nargs="+", help="'칸=값', 목록 칸은 '칸+=값', '칸-=값'. 값을 비우면 그 키를 지워 기본값으로 돌아간다")
    a.add_argument("--check", action="store_true", help="쓰지 않고 바뀔 줄만 보인다")
    s.set_defaults(fn=cmd_registry)

    s = sub.add_parser("settings", help="전역 설정. /jipsa-slack, /jipsa-model, /jipsa-config, /jipsa-cleanup 스킬이 부른다. show만 빼고 메인 세션 전용이다")
    rs = s.add_subparsers(dest="action", required=True)
    a = rs.add_parser("show", help="지금 값과 출처. 비밀값은 설정됨 여부만 보인다")
    a.add_argument("--skill", choices=["config", "slack", "model", "cleanup"], default="", help="그 스킬의 칸만 보인다")
    a = rs.add_parser("check", help="쓰지 않고 '키=값'을 검사하고 전후를 보인다")
    a.add_argument("pairs", nargs="+", help="'키=값'. 값을 비우면 기본값으로 돌아간다")
    a = rs.add_parser("set", help="'키=값'을 저장한다. 설정 파일 직전 판 하나를 남긴다")
    a.add_argument("pairs", nargs="+", help="'키=값'. 값을 비우면 기본값으로 돌아간다")
    rs.add_parser("undo", help="설정 파일을 직전 판과 맞바꾼다")
    a = rs.add_parser("webhook", help="Slack Webhook 주소를 표준 입력으로 받아 비밀값 파일에 쓴다. 값은 출력하지 않는다")
    a.add_argument("--clear", action="store_true", help="비밀값 파일의 주소를 지운다")
    rs.add_parser("slack-test", help="Slack에 시험 글 한 줄을 보낸다")
    a = rs.add_parser("stop", help="스케줄러를 끄고 멈춤을 적어 대시보드 감시가 다시 띄우지 않게 한다. 실행 중 작업이 있으면 --force 없이는 거절한다")
    a.add_argument("--force", action="store_true", help="실행 중 작업을 끊고 끈다")
    rs.add_parser("start", help="멈춤을 풀고 스케줄러를 창 없이 띄운다")
    a = rs.add_parser("restart", help="스케줄러와 대시보드를 창 없이 다시 띄운다. 실행 중 작업이 있으면 --force 없이는 거절한다")
    a.add_argument("--force", action="store_true", help="실행 중 작업을 끊고 다시 띄운다")
    a.add_argument("--port", type=int, default=0, help="대시보드 포트. 비우면 설정값이다")
    s.set_defaults(fn=cmd_settings)

    s = sub.add_parser("wait-answer", help="세션 받은편지함에 답이 들어올 때까지 기다렸다가 안내문을 찍고 끝난다. 세션이 백그라운드로 띄워 쉬는 동안 깨어나게 한다")
    s.add_argument("--session", default="", help="이 세션의 기록 id(session-xxxxxxxx). 다른 세션이 시작한 실행의 답은 2분 뒤에 받는다")
    s.add_argument("--interval", type=float, default=2.0, help="받은편지함을 보는 간격(초)")
    s.add_argument("--timeout", type=float, default=720, help="이 시간(분)이 지나면 답 없이 끝난다. 0이면 끝없이 기다린다")
    s.set_defaults(fn=cmd_wait_answer)

    s = sub.add_parser("slack", help="Slack 알림 켜짐/꺼짐. 인자 없이 status")
    s.add_argument("state", nargs="?", choices=["on", "off", "status"], default="status")
    s.set_defaults(fn=cmd_slack)

    s = sub.add_parser("auto", help="없어진 Auto 명령(261029-jipsa-17). 안내와 지금 상태를 찍는다. Cycle은 jipsa todo run으로 시킨다")
    s.add_argument("words", nargs=argparse.REMAINDER, help="동작과 인자. 따옴표 없이 여러 낱말로 와도 공백으로 합친다")
    s.set_defaults(fn=cmd_auto)

    s = sub.add_parser("claude-usage", help="Claude 사용 창 기록. 화면과 보고의 표시에 쓰고 새 시작을 막지 않는다")
    s.add_argument("action", nargs="?", default="show", choices=["show", "record"])
    s.add_argument("--five", type=float, default=None, help="record와 같이 쓴다. 5시간 창 사용률(%%)")
    s.add_argument("--week", type=float, default=None, help="record와 같이 쓴다. 주간 창 사용률(%%)")
    s.add_argument("--source", default="손으로 넣음", help="record와 같이 쓴다. 값의 출처")
    s.set_defaults(fn=cmd_claude_usage)

    s = sub.add_parser("report", help="그날의 보고 전문을 만들고 출력한다")
    s.add_argument("date", nargs="?", default=None)
    s.add_argument("--send", action="store_true", help="Slack 요약도 보낸다")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("runs", help="지난 작업 목록(시작 역순)")
    s.add_argument("--last", type=int, default=30, help="보여줄 개수")
    s.add_argument("--date", default=None, help="보고 날짜 YYYY-MM-DD")
    s.add_argument("--project", default=None)
    s.add_argument("--status", default=None, type=norm_status, choices=["완료", "실패", HOLD, "진행 중"], help="옛 이름 판단 대기도 받는다")
    s.set_defaults(fn=cmd_runs)

    s = sub.add_parser("result", help="실행 하나의 결과지(runs/<실행ID>/result.md)")
    s.add_argument("run_id")
    s.add_argument("--rebuild", action="store_true", help="meta와 attempt 파일에서 결과지를 다시 만든다")
    s.set_defaults(fn=cmd_result)

    s = sub.add_parser("begin", help="세션이나 서브에이전트가 할 작업의 시작을 기록한다")
    s.add_argument("project")
    s.add_argument("title")
    s.add_argument("--criteria", required=True)
    s.add_argument("--est", type=int, default=None)
    s.add_argument("--games", default=None, help="판 수로 상한을 계산한다(등록부에 판 시간 표가 있는 프로젝트). 게임:인원:판 수를 쉼표로 잇는다. 예: game_a:4:28,game_b:4:22. 주면 --est보다 앞선다")
    s.add_argument("--parallel", type=int, default=None, help="--games와 함께 쓰는 동시 판 수")
    s.add_argument("--executor", default="subagent", choices=["subagent", "session", "manual"])
    s.add_argument("--model", default=None)
    s.add_argument("--parent", default=None, help="이 일이 나온 같은 프로젝트의 할 일 줄, 메모, 지난 실행 제목 또는 '프로젝트::이름' key. 이름 일부만 줘도 하나로 좁혀지면 된다. 실행 기록의 parent_item에만 건다")
    s.add_argument("--kind", default=None, choices=["구현", "글쓰기", "조사", "기획", "실험"],
                   help="작업 종류. 세션이 정해 넣는다. 없으면 제목과 기준의 낱말로 추정하고 TODO에 추정으로 보인다")
    s.add_argument("--pick", action="store_true", default=None, help="사람이 고를 것이 남는 제안형 작업. TODO에 고를 것으로 보인다")
    s.add_argument("--agent", default=None, help="이 일을 맡길 서브에이전트 이름(Agent 도구의 name). 멈춤 알림이 이 이름으로 깨울 대상을 알린다")
    s.add_argument("--todo", default=None, help="Do 요청으로 받은 할 일 줄의 key(또는 번호, 문장 일부). 시작하면 줄을 할 일 파일에서 빼고 실행 기록에 원문을 남긴다")
    s.add_argument("--force", action="store_true", help="쓰지 않는다. 사용 창으로 막지 않게 된 뒤 예전 명령이 깨지지 않게 받아 둔다")
    s.add_argument("--draft", action="store_true", help="결과지 '초안 보기' HTML 초안을 내는 일. 규격에 초안 줄이 붙고 preview_url이 비면 finish가 막는다. "
                   "사람 입력에 '초안'이 30분 안에 있었으면 주지 않아도 붙는다")
    s.add_argument("--no-draft", action="store_true", help="사람 입력의 '초안'을 이 일에 쓰지 않는다(초안과 상관없는 일)")
    s.set_defaults(fn=cmd_begin)

    s = sub.add_parser("gpu", help="큰 GPU 일 신호. jipsa gpu signal <실행ID> --kind 학습 [--gb N] [--wait 분], 끝나면 --done")
    s.add_argument("action", choices=["signal"])
    s.add_argument("run_id")
    s.add_argument("--kind", default="학습", help="학습, 추론, 모델서버 같은 일 종류")
    s.add_argument("--gb", type=float, default=None, help="쓸 양을 알면 GB. 없으면 등록부 값, 지난 최댓값, 시작 요구량 가운데 큰 값")
    s.add_argument("--wait", type=float, default=0, help="남은 메모리가 0 아래면 이 시간(분)까지 기다린다")
    s.add_argument("--done", action="store_true", help="큰 GPU 일이 끝났다. GPU 예약을 관찰 값으로 돌린다")
    s.set_defaults(fn=cmd_gpu)

    s = sub.add_parser("install-lock", help="프로젝트 공용 가상환경 잠금을 잡고 설치 명령을 돌린다. jipsa install-lock <프로젝트> -- <설치 명령>")
    s.add_argument("project")
    s.add_argument("--wait", type=float, default=10, help="다른 설치를 기다리는 시간(분)")
    s.add_argument("command", nargs=argparse.REMAINDER)
    s.set_defaults(fn=cmd_install_lock)

    s = sub.add_parser("topic", help="세션이 지금 하는 일을 '메모리 누수 확인'처럼 짧은 이름과 프로젝트로 건다. 화면에서 그 프로젝트 아래 줄이 된다")
    s.add_argument("title", nargs="?", default=None)
    s.add_argument("--project", default=None, help="등록부 프로젝트 이름. 어느 프로젝트에도 속하지 않는 일(시스템 점검 등)은 기타")
    s.add_argument("--done", action="store_true", help="걸린 주제를 닫는다. 맡긴 일이 끝나 세션이 그 주제로 일하지 않을 때 쓴다")
    s.add_argument("--at", default=None, help="--done과 함께 닫는 시각. HH:MM(오늘) 또는 ISO 시각. 없으면 지금")
    s.set_defaults(fn=cmd_topic)

    s = sub.add_parser("finish", help="begin으로 시작한 작업을 마감한다. 결과지, 보고, 확인 필요와 실패면 Slack 요약 글")
    s.add_argument("run_id")
    s.add_argument("--agent", default=None, help="서브에이전트 이름. ~/.claude의 기록에서 도구 호출과 토큰을 들여온다")
    s.add_argument("--transcript", default=None, help="기록 jsonl 경로를 직접 준다")
    s.add_argument("--status", default=None, type=norm_status, choices=["완료", "실패", HOLD], help="옛 이름 판단 대기도 받는다")
    s.add_argument("--summary", default=None)
    s.add_argument("--no-slack", action="store_true")
    s.add_argument("--reopen", action="store_true", help="이미 마감한 기록을 attempt 폴더의 result.json으로 다시 마감한다. 확인 필요와 실패면 Slack 정정 요약 글")
    s.set_defaults(fn=cmd_finish)

    s = sub.add_parser("attack", help="마감 전 Sol 공격 한 번. 공격 목록과 같은 서브에이전트에게 보낼 글을 찍는다. Codex 사용량과 무관하게 호출하고, 한도 오류나 실패면 공격 없음으로 마감한다")
    s.add_argument("run_id")
    s.set_defaults(fn=cmd_attack)

    s = sub.add_parser("record", help="지난 작업을 뒤늦게 들여온다(시작과 끝 시각 지정)")
    s.add_argument("project")
    s.add_argument("title")
    s.add_argument("--criteria", required=True)
    s.add_argument("--started", required=True, help="ISO 시각")
    s.add_argument("--finished", required=True, help="ISO 시각")
    s.add_argument("--status", default=None, type=norm_status, choices=["완료", "실패", HOLD], help="옛 이름 판단 대기도 받는다")
    s.add_argument("--summary", default=None)
    s.add_argument("--result", default=None, help="result.json 경로")
    s.add_argument("--report", default=None, help="보고 본문 md 경로")
    s.add_argument("--transcript", default=None, help="서브에이전트 기록 jsonl 경로")
    s.add_argument("--executor", default="subagent", choices=["subagent", "session", "manual"])
    s.add_argument("--model", default=None)
    s.add_argument("--est", type=int, default=None)
    s.add_argument("--no-slack", action="store_true")
    s.set_defaults(fn=cmd_record)

    s = sub.add_parser("dry-run", help="모의 실행. 커밋 없이 세 단계를 한 번 돌린다")
    s.add_argument("project")
    s.add_argument("title")
    s.add_argument("--criteria", required=True)
    s.add_argument("--est", type=int, default=None)
    s.set_defaults(fn=cmd_dry_run)

    s = sub.add_parser("check", help="환경과 설정을 점검한다")
    s.add_argument("--llm", action="store_true", help="Claude와 Codex를 실제로 한 번 부른다")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("sync-agents", help="RULES.md에서 AGENTS.md를 다시 만든다")
    s.set_defaults(fn=cmd_sync_agents)

    s = sub.add_parser("worktrees", help="worktree 목록과 제거")
    s.add_argument("--remove", default=None, help="제거할 실행ID")
    s.add_argument("--delete-branch", action="store_true")
    s.set_defaults(fn=cmd_worktrees)

    s = sub.add_parser("prune", help="runs/ 보관 기한. 오래된 기록을 월별 묶음으로 옮기고 오래된 묶음을 지운다. 기본은 미리보기")
    s.add_argument("--apply", action="store_true", help="미리보기 대신 실제로 한다")
    s.add_argument("--run-days", type=int, default=None, help="실행 기록을 묶기까지 일수(기본 JIPSA_RETAIN_RUN_DAYS, 30)")
    s.add_argument("--other-days", type=int, default=None, help="세션 기록과 일회성 폴더를 묶기까지 일수(기본 14)")
    s.add_argument("--archive-days", type=int, default=None, help="묶음을 지우기까지 일수(기본 180)")
    s.add_argument("--runs-dir", default=None, help="runs 대신 다룰 폴더(확인용)")
    s.set_defaults(fn=cmd_prune)

    s = sub.add_parser("runs-clean", help="runs/ 중간 산출물 정리. 끝난 작업의 브라우저 프로필, 임시 DB 사본, 원응답 로그 같은 큰 파일을 휴지통 폴더로 옮긴다. 기본은 미리 보기")
    s.add_argument("--apply", action="store_true", help="미리 보기 대신 실제로 옮긴다. 지우지 않는다")
    s.add_argument("--days", type=int, default=None, help="작업의 마지막 활동에서 옮기기까지 일수(기본 JIPSA_RUNS_CLEAN_DAYS, 3)")
    s.add_argument("--kinds", default=None, help="옮길 종류를 쉼표로(기본 JIPSA_RUNS_CLEAN_KINDS)")
    s.add_argument("--min-mb", type=float, default=None, help="이보다 작은 항목은 둔다(기본 JIPSA_RUNS_CLEAN_MIN_MB, 1)")
    s.add_argument("--trash", default=None, help="휴지통 폴더({date}는 YYYYMMDD, 기본 JIPSA_RUNS_CLEAN_TRASH)")
    s.add_argument("--runs-dir", default=None, help="runs 대신 다룰 폴더(확인용)")
    s.add_argument("--all", action="store_true", help="작업째 지킨 줄도 보인다")
    s.set_defaults(fn=cmd_runs_clean)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = ap.parse_args(argv)
    if getattr(args, "concurrency", None) is None and args.cmd == "run":
        from scheduler.config import CONCURRENCY

        args.concurrency = CONCURRENCY
    if args.cmd == "web" and args.port is None:
        from scheduler.config import WEB_PORT

        args.port = WEB_PORT
    guarded = {"run": "스케줄러 루프", "dry-run": "모의 실행"}.get(args.cmd)
    if args.cmd == "web" and args.port != 8765:
        guarded = f"{args.port} 포트 대시보드"
    if guarded:
        from scheduler.config import live_guard

        why, warns = live_guard(guarded)
        for w in warns:
            print(f"경고: {w}", file=sys.stderr)
        if why:
            print(f"막음: {why}", file=sys.stderr)
            return 2
    ensure_dirs()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
