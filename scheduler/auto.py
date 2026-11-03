"""Cycle과 일회성 할 일 시키기(261026-jipsa-12에서 시작, 261029-jipsa-17 1안에서 Auto 모드를 없앴다).

규칙.
- 모드 없음: Auto 모드(켜기, 끄기, Auto 절, Manual과 Auto 표시)는 없다. 할 일 줄은 넣어도 돌지 않고 시킨 줄만 돈다.
  `jipsa todo run <번호> [시작 HH:MM] [마감 HH:MM|+4h]`과 대시보드 Do 단추가 같다. 옛 `jipsa auto` 명령은 없어졌다는 안내를 찍는다.
- 일회성 줄: 시작 시각 없이 바로 돈다. 열린 세션이 있으면 세션 서브에이전트로 보내고, 없거나 2분 안에 받지 않으면 스케줄러 작업자로 돈다.
  시작하면 할 일 파일에서 빠지고 결과지가 남는다. 동시 상한을 보지 않는다.
- Cycle 목표 줄(cycle 칸): 시킬 때 시작(지금 또는 HH:MM)과 마감(HH:MM이나 +4h, 없으면 시작 뒤 8시간)을 정한다. 시작 시각 전에는
  시작 예정으로 기다리고, 그 시각이 되면 자원 판정과 대기열을 거쳐 돈다. Cycle 한 바퀴(명령 이행, 분석과 피드백, 목표 판정과 다음 플랜)는
  scheduler/cycle.py가 하고 단계마다 큐 줄 하나다. 기록은 상태 폴더 cycles/todo-<프로젝트>-<이름>.json이다.
- 동시 실행과 자원: 모드와 무관하게 스케줄러가 나눈다. Cycle 단계와 기준 정하기는 합쳐 AUTO_CAP(6)개까지 같이 돈다. 사용 창 비율로는 막지 않고
  실제 한도 오류만 실행기가 기다리거나 실패로 끝낸다(261102-jipsa-50). GPU와 RAM은 장부의 예약으로 판정하고, 모자라면 대기열에 선다
  (resources.can_acquire). 대기열 순서는 사람이 맨 앞으로, 내리기, 빼기로 바꾼다.
- 마감 처리(하나로 맞췄다): 마감이 되거나 마감 전에 다음 단계를 마칠 시간이 없으면 새 단계를 열지 않고, 돌던 단계가 끝나기를 기다린 뒤
  끝 결과지를 쓰고 요청을 닫는다. 줄은 할 일 절 맨 아래로 돌아간다. Cycle 기록은 끝내지 않으므로 같은 줄을 다시 시키면 멈춘 자리부터 잇는다(판정까지 마친 회차면 다음 회차, 아니면 그 회차의 남은 단계).
  사람이 멈추기를 누르면 마감을 지금으로 당긴 것과 같다.
- 끝 조건: 사람이 적은 것과 금지 사항뿐이다. 다음 명령이 금지 사항, 이행이 금지 규칙의 확인 필요, cycle 칸 끝의 "상한 N"만큼 연속 정체,
  "도달하면 끝"을 적었을 때 목표 도달이다. 끝나면 끝 결과지(목표 도달이면 완료, 나머지는 확인 필요)를 쓰고 줄을 할 일 절 맨 아래로 돌린다.
  끝난 목표와 같은 줄을 다시 시키면 지난 기록을 ended- 이름으로 옮기고 Cycle 1부터 새로 돌되, 첫 명령은 지난 분석이 쓴 다음 명령이다.
- 기준 없는 줄은 시키면 기획 단계 작업 하나("기준 정하기")를 먼저 돌리고, 1안 기준을 그 줄에 적은 뒤 같은 요청으로 본 작업을 잇는다.
- Slack: 결과지 글은 지금처럼 확인 필요와 실패만 바로 보낸다. 밤 사이 끝난 Cycle은 아침 한 번(MORNING_AT, 기본 07:30) 모음 글로 보낸다
  (morning_digest). 옛 Auto 끝 글은 없다.
- 옛 파일: 할 일 파일의 옛 Auto 절 줄은 할 일로 읽는다(todo.py). 모드 파일의 옛 auto 값은 유인으로 읽는다(modes.py). 옛 Auto가 꺼낸 큐 줄은
  다시 시키면 그 줄의 남은 단계부터 잇는다.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import datetime, timedelta

from scheduler import cycle, events, modes, queue, record, report, resources, todo, workitem
from scheduler.config import (AUTO_CAP, DO_SESSION_GRACE_SEC, MORNING_AT, STATE, next_cutoff,
                              now, now_iso, parse_hhmm, parse_iso)
from scheduler.registry import Project

SOURCE = "todo"  # 큐 줄의 source. 할 일 파일에서 꺼낸 줄이다
TIER = "auto"
NO_CRITERIA = "기준 없음, 기획 단계로 기준 후보를 받는다"
NO_PROJECT = "등록부에 없는 프로젝트라 건너뜀"
MANUAL_ONLY = "세션 전용 프로젝트라 건너뜀"
DROP = (NO_PROJECT, MANUAL_ONLY)  # 결과지를 남기고 할 일 절로 내리는 사유
PLAN_MIN = 15  # 기준 정하기(기획 단계) 작업의 상한(분). 문서 구간 상한과 같다
PLAN_TITLE = "기준 정하기"
PLAN_RULE = "기준 정하기: 사람이 기준을 고른다"  # 옛 기록과 채택 실패 때만 쓴다
# 기준 정하기가 후보를 내지 못했거나 실패했을 때 그 줄의 기준 칸에 적는 기본 기준(261026-jipsa-03)
PLAN_DEFAULT = "할 일 문장이 말한 변경을 마치고, 세션 안에서 직접 실행해 확인한 증거를 결과에 남긴다"
NO_CAP = "상한 없음"
END_TITLES = 3  # 아침 모음 글의 사람이 할 일 줄에 이름을 적는 결과지 수
AUTO_GONE = ("Auto 모드는 없어졌다(261029-jipsa-17). Cycle은 jipsa todo run <번호> [시작 HH:MM] [마감 HH:MM|+4h]으로 시킬 때 시작과 마감을 정하고, "
             "일회성 줄은 jipsa todo run <번호>로 바로 돈다. 동시 실행 수와 GPU, RAM 나눔은 스케줄러가 맡는다")


# ----- 요청의 기록 -----
def _state(mode: dict, path=None) -> dict:
    """이번 요청의 GPU 대기와 건너뜀 기록."""
    try:
        st = json.loads((path or RUN_STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    if st.get("since") != mode.get("since"):
        st = {"since": mode.get("since"), "gpu_wait": {}, "passed": {}}
    st.setdefault("gpu_wait", {})
    st.setdefault("passed", {})
    return st


def _save_state(st: dict, path=None) -> None:
    path = path or RUN_STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


# ----- 줄 읽기 -----
def effective(project: Project, limits: dict | None) -> Project:
    """한도 칸의 VRAM과 RAM을 요구량으로 쓴 프로젝트. VRAM 칸이 없으면 등록부, 그것도 없으면 지난 실측 최댓값이다.
    RAM 칸이 있으면 RAM 요구량이 되고(261029-jipsa-17), 없으면 resources.ram_need_gb가 등록부와 지난 실측으로 정한다. CPU 한도는 지시문에만 들어간다."""
    vram, ram = (limits or {}).get("vram_gb"), (limits or {}).get("ram_gb")
    # 한도 칸도 등록부 값도 없으면 지난 실측 최댓값을 요구량으로 쓴다(261026-jipsa-26, GPU 장부)
    out = replace(project, gpu_vram_gb=float(vram)) if vram else resources.with_peak(project)
    return replace(out, ram_gb=float(ram)) if ram else out


def gpu_text(project: Project) -> str:
    """GPU 필요 표시. 필요 없으면 빈 값이다."""
    if not project.needs_gpu:
        return ""
    if project.gpu_exclusive:
        return "GPU 배타" + (f" {project.gpu_vram_gb:g}GB" if project.gpu_vram_gb else "")
    if project.gpu_vram_gb:
        return f"GPU {project.gpu_vram_gb:g}GB"
    return "GPU 필요(Ollama)"


def lane_rows() -> list[dict]:
    """할 일 파일에서 꺼낸 도는 줄. 큐의 source todo 줄 가운데 대기나 실행 중이다."""
    return [r for r in queue.load() if r.get("source") == SOURCE and r["status"] in (queue.PENDING, queue.RUNNING)]


def classify(it: todo.Todo, registry: dict, st: dict | None = None) -> str:
    """돌리지 않을 사유. 돌릴 줄이면 빈 값이다. 자원과 마감은 보지 않는다."""
    project = registry.get(it.project)
    if project is None:
        return NO_PROJECT
    if project.manual_only:
        return MANUAL_ONLY
    if not it.criteria and not it.cycle:
        return NO_CRITERIA
    if st and it.key in st["passed"]:
        return st["passed"][it.key]
    return ""


# ----- 결과지와 큐 줄 -----
def entry(it: todo.Todo, project: Project, run_id: str, mode: dict) -> dict:
    """시킨 줄의 큐 줄. key에 실행ID를 붙여 같은 문장의 지난 줄과 섞이지 않게 한다."""
    return {
        "key": f"{it.key}@{run_id}", "project": project.name, "title": it.text, "criteria": it.criteria,
        "est_minutes": None, "kind": project.kind, "priority": project.priority, "needs_gpu": project.needs_gpu,
        "status": queue.PENDING, "reason": "", "run_id": run_id, "source": SOURCE, "file": "", "line": None,
        "added": now_iso(), "started": None, "finished": None, "answer": None, "wait_since": None, "tier": TIER,
        "category": "", "pick": False, "category_guess": False, "after": [],
        "todo_key": it.key, "todo_line": it.line(), "limits": dict(it.limits), "auto_since": mode.get("since"),
    }


def skip_sheet(it: todo.Todo, why: str, mode: dict) -> str:
    """돌리지 않은 시킨 줄의 결과지. jipsa가 바로 쓰고 확인 필요로 둔다. 실행ID다."""
    project = it.project if it.project else "jipsa"
    run_id = record.new_run_id(project)
    fix = {NO_CRITERIA: "기준 칸을 적어 다시 시킨다",
           NO_PROJECT: "줄의 프로젝트 이름이 등록부 파일 이름과 같은지 본다. 같으면 등록 직후 스케줄러가 아직 읽지 못한 것이므로 한 주기 뒤 다시 시킨다",
           MANUAL_ONLY: "세션에서 바로 시킨다"}.get(why, "고쳐 다시 올린다")
    cause = {NO_CRITERIA: "기준(완료 기준) 칸이 없어 돌리지 않았다",
             NO_PROJECT: "등록부에 없는 프로젝트라 돌리지 않았다",
             MANUAL_ONLY: "세션 전용 프로젝트라 스케줄러가 돌리지 않는다"}.get(why, why)
    options = [f"1안: {fix}(추천)", "2안: 할 일 절에 그대로 둔다"]
    summary = f"시킨 줄 하나를 돌리지 않고 할 일 절로 돌렸다. {cause}"
    body = [f"# {it.text}", "", "```요약", "**한 일**: 시킨 이 줄을 돌리지 않고 할 일 절 맨 아래로 돌렸다.",
            f"**결과**: 그대로다. {cause}. 작업자를 부르지 않았다.", f"**사람이 할 일**: {fix}.", "```", "",
            "돌릴 수 없는 줄은 결과지 한 장을 남기고 할 일로 돌린다. 그림은 뜻이 없어 두지 않았다.", "",
            "## 1. 돌리지 않은 줄", "", f"줄 원문은 \"{it.line()}\"이다. {cause}.",
            "", "## 남은 일과 정할 것", "", *[f"{i + 1}. {o}" for i, o in enumerate(options)], ""]
    d = record.RUNS / run_id / "attempt-1"
    d.mkdir(parents=True, exist_ok=True)
    (d / "report.md").write_text("\n".join(body), encoding="utf-8")
    at = now_iso()
    result = {"status": "확인 필요", "label": "시킨 줄 건너뜀", "summary": summary[:80], "changed_files": [], "evidence": [f"할 일 줄: {it.line()}"],
              "commit": "", "reason": why, "rule": f"시킨 줄 건너뜀: {why}", "options": options, "added_packages": [], "preview_url": ""}
    record.write_json(d / "result.json", result)
    meta = {"run_id": run_id, "project": project, "title": it.text, "criteria": it.criteria or "기준 없음", "kind": "doc",
            "executor": "jipsa", "started": at, "finished": at, "report_date": now().date().isoformat(), "status": "확인 필요",
            "minutes_limit": 0, "minutes_used": 0, "attempts": [{"n": 1, "status": "확인 필요"}], "mode": modes.ATTENDED,
            "summary": summary[:200], "rule": result["rule"], "options": options, "reason": why, "evidence_ref": f"runs/{run_id}",
            "todo_line": it.line(), "limits": dict(it.limits), "auto_since": mode.get("since"), "auto_skip": why, "updated": at}
    record.write_json(record.RUNS / run_id / "meta.json", meta)
    try:
        record.close(meta)  # 결과지, 그날 보고, 확인 필요 Slack 글 하나(요약 세 줄과 고를 것, 261025-jipsa-20)
    except OSError as e:
        events.emit("error", where="auto_skip", error=str(e)[:200])
    return run_id


def _orch_sheet(it: todo.Todo, *, status: str, label: str, summary: str, box: dict, intro: str, sections: list[str],
                options: list[str], rule: str, reason: str, extra: dict, mode: dict) -> str:
    """jipsa가 바로 쓰는 결과지 하나(Cycle 목표의 끝). 실행ID다. 확인 필요면 record.close가 요약 Slack 글을 보낸다."""
    project = it.project or "jipsa"
    run_id = record.new_run_id(project)
    body = [f"# {it.text}", "", "```요약", f"**한 일**: {box['한 일']}", f"**결과**: {box['결과']}", f"**사람이 할 일**: {box['사람이 할 일']}",
            "```", "", intro, "", *sections, "", "## 남은 일과 정할 것", "",
            *([f"{i + 1}. {o}" for i, o in enumerate(options)] or ["없다."]), ""]
    d = record.RUNS / run_id / "attempt-1"
    d.mkdir(parents=True, exist_ok=True)
    (d / "report.md").write_text("\n".join(body), encoding="utf-8")
    at = now_iso()
    result = {"status": status, "label": label, "summary": summary[:80], "changed_files": [], "evidence": [f"할 일 줄: {it.line()}"],
              "commit": "", "reason": reason, "rule": rule, "options": options, "added_packages": [], "preview_url": ""}
    record.write_json(d / "result.json", result)
    meta = {"run_id": run_id, "project": project, "title": it.text, "criteria": it.criteria or "cycle 칸의 지표와 목표값", "kind": "doc",
            "executor": "jipsa", "started": at, "finished": at, "report_date": now().date().isoformat(), "status": status,
            "minutes_limit": 0, "minutes_used": 0, "attempts": [{"n": 1, "status": status}],
            "mode": modes.ATTENDED,
            "summary": summary[:200], "rule": rule, "options": options, "reason": reason, "evidence_ref": f"runs/{run_id}",
            "todo_line": it.line(), "limits": dict(it.limits), "auto_since": mode.get("since"), "updated": at, **extra}
    record.write_json(record.RUNS / run_id / "meta.json", meta)
    try:
        record.close(meta)
    except OSError as e:
        events.emit("error", where="auto_sheet", error=str(e)[:200])
    return run_id


# ----- Cycle 목표(261025-jipsa-24, 4단계) -----
def cap_of(it: todo.Todo) -> int:
    """연속 정체 상한. 사람이 적지 않았으면 0(상한 없음)이다."""
    return int((it.cycle or {}).get("cap") or todo.DEFAULT_CAP or 0)


def cap_text(it: todo.Todo) -> str:
    cap = cap_of(it)
    return f"상한 {cap}" if cap else NO_CAP


def as_cycle(it: todo.Todo) -> workitem.Cycle:
    """할 일 줄의 cycle 칸을 옛 Cycle 한 바퀴가 읽는 목표로 바꾼다. 주간 파일 줄은 없고(origin todo), 단계 큐 줄은 Auto 한 줄로 센다."""
    cy = it.cycle or {}
    return workitem.Cycle(project=it.project, title=it.text, file=todo.TODO_FILE, line=-1, marker=None, checked=False,
                         goal=it.text + (f". {it.criteria}" if it.criteria else ""), metric=cy.get("metric", ""),
                         success=f"{cy.get('target')}{cy.get('unit', '')} {cy.get('dir', '이상')}",
                         target=float(cy["target"]) if cy.get("target") else None,
                         direction=cy.get("dir") or "이상", no_gain_limit=cap_of(it), stop_on_reach=bool(cy.get("stop")), origin="todo",
                         pending=todo.cycle_pending(cy),
                         entry_extra={"source": SOURCE, "todo_key": it.key, "todo_line": it.line(), "limits": dict(it.limits)})


def _records() -> list[dict]:
    out = []
    for path in sorted(cycle.CYCLE_DIR.glob("todo-*.json")) if cycle.CYCLE_DIR.exists() else []:
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if rec.get("origin") == "todo":
            out.append(rec)
    return out


def _archive(c: workitem.Cycle, rec: dict) -> None:
    """끝나고 결과지까지 쓴 기록을 옆 이름으로 옮긴다. 같은 줄을 다시 올리면 새 기록으로 시작한다."""
    path = cycle.record_path(c)
    cycle.feedback_clear(c.key)  # 사람 피드백 사용 기록(261026-jipsa-19). 같은 줄을 다시 올려도 옛 피드백을 다시 넣지 않는다
    stamp = str(rec.get("finished") or now_iso()).replace(":", "").replace("-", "")[:13]
    try:
        path.replace(path.with_name(f"ended-{path.stem}-{stamp}.json"))
    except OSError:
        pass


def _next_round(rec: dict) -> int:
    rounds = rec.get("rounds") or []
    if not rounds:
        return 1
    return rounds[-1]["n"] + 1 if rounds[-1].get("judge") else rounds[-1]["n"]


def _note_resume(c: workitem.Cycle, rec: dict, mode: dict) -> None:
    """이번 요청에서 이 목표를 처음 볼 때. 지난 요청에서 돌던 목표면 이은 사실을 기록의 resumed 칸에 남긴다."""
    since = mode.get("since")
    if rec.get("todo_since") == since:
        return
    if rec.get("rounds") and rec.get("todo_since"):
        nxt = _next_round(rec)
        rec.setdefault("resumed", []).append({"since": since, "from_since": rec["todo_since"], "after": len(rec["rounds"]),
                                              "next": nxt, "at": now_iso()})
        events.emit("auto_cycle_resume", cycle=c.key, after=len(rec["rounds"]), next=nxt)
    rec["todo_since"] = since
    rec.pop("paused", None)  # 지난 요청의 마감 멈춤은 다시 시키면 풀린다
    cycle.save(c, rec)


def _fmt(x) -> str:
    return "-" if x is None else f"{x:g}"


def cycle_sheet(it: todo.Todo, c: workitem.Cycle, rec: dict, mode: dict, why: str = "") -> str:
    """Cycle 목표의 끝 결과지. 목표 도달이면 완료, 나머지는 확인 필요다. 실행ID다.
    why를 주면 마감 결과지(261029-jipsa-17)다. 기록은 끝내지 않았으므로 다시 시키면 멈춘 자리부터 잇는다(판정까지 마친 회차면 다음 회차, 아니면 그 회차의 남은 단계)고 적는다."""
    deadline = bool(why)
    why = why or str(rec.get("end_reason") or "")
    rounds = rec.get("rounds") or []
    reached = (not deadline and why.startswith("목표 도달")) or bool(rec.get("reached"))
    hit = rec.get("reached") or {}
    best, best_n = rec.get("score"), rec.get("baseline_round")
    target = f"{c.metric} {_fmt(c.target)} {c.direction}"
    nxt = _next_round(rec)
    rows = ["| Cycle | 지표 | 나아짐 | 명령 |", "| --- | --- | --- | --- |"]
    for r in rounds:
        j = r.get("judge") or {}
        adopt = {True: "나아짐", False: "그대로"}.get(r.get("adopt"), "-")
        cmd = ("[방향 전환] " if r.get("pivot") else "") + (f"[{r['branch']}] " if r.get("branch") else "") + str((r.get("plan") or {}).get("plan") or "").replace("|", "/")[:60]
        rows.append(f"| {r['n']} | {_fmt(j.get('metric', r.get('score')))} | {adopt} | {cmd} |")
    again = f"같은 줄을 다시 시키면 Cycle {nxt}부터 잇는다" if deadline else "같은 줄을 다시 시키면 이 목표의 마지막 분석이 쓴 다음 명령으로 첫 Cycle을 연다"
    if reached:
        status, options = "완료", []
        todo_line = "없다. 결과를 보고 병합을 정한다" if best_n else "없다"
    elif best_n:
        status = "확인 필요"
        options = [f"1안: 최고 기록인 Cycle {best_n}의 결과를 병합한다(추천)",
                   "2안: 다시 시켜 이어 돈다" if deadline else "2안: 상한이나 목표를 고쳐 같은 줄을 다시 시킨다", "3안: 병합하지 않고 끝낸다"]
        todo_line = f"Cycle {best_n}의 결과를 병합할지 고른다"
    else:
        status = "확인 필요"
        options = (["1안: 다시 시켜 이어 돈다(추천)", "2안: 목표나 지표를 고쳐 다시 시킨다", "3안: 여기서 끝낸다"] if deadline else
                   ["1안: 목표나 지표를 고쳐 같은 줄을 다시 시킨다(추천)", "2안: 여기서 끝낸다"])
        todo_line = "다시 시킬지 고른다" if deadline else "목표를 고쳐 다시 시킬지 고른다"
    summary = (f"Cycle 목표가 마감으로 {len(rounds)} Cycle에서 멈췄다. {why[:40]}" if deadline
               else f"Cycle 목표가 {len(rounds)} Cycle 만에 끝났다. {why[:40]}")
    box = {"한 일": f"시킨 Cycle 목표를 {len(rounds)} Cycle 돌렸다. 목표는 {target}이다.",
           "결과": (f"{'목표에 닿았다' if reached else '목표에 아직 닿지 못했다'}. {why}에 돌던 단계를 마치고 멈췄고 " if deadline else
                  f"{'목표에 닿았다' if reached else '목표에 닿지 못하고 끝났다'}. 끝 사유는 {why}이고 ")
           + (f"최고 기록은 {_fmt(best)}이다." if best is not None else "잰 지표가 없다."),
           "사람이 할 일": todo_line + "."}
    cap = f"상한은 연속 정체 {c.no_gain_limit} Cycle이었다." if c.no_gain_limit else "연속 정체 상한은 없었다."
    turns = [str(r["n"]) for r in rounds if r.get("pivot")]
    if turns:  # 연속 정체 2바퀴마다 최고 기록에서 다른 쪽 후보로 연 Cycle(261029-jipsa-03 1안)
        cap += f" 방향 전환은 Cycle {', '.join(turns)}에서 했다(연속 정체 2바퀴마다 최고 기록에서 다른 쪽 후보로 갔다)."
    bs = cycle.branch_view(rec)
    if bs:  # 아이디어 갈래(261029-jipsa-10 1안). 닫힌 갈래와 안 간 갈래를 한 줄씩 적는다
        shut = [f"{b['name']}(Cycle {b['closed_at']})" for b in bs if b["status"] == cycle.CLOSED]
        idle = [b["name"] + (", 사람 확인" if b["status"] == cycle.ASK else "") for b in bs if not b["rounds"]]
        cap += (f" 아이디어 갈래는 {len(bs)}개였다. 같은 갈래가 연속 2바퀴 나아지지 않으면 닫았다. 닫힌 갈래: {', '.join(shut) or '없음'}. "
                f"안 간 갈래: {', '.join(idle) or '없음'}.")
    note = (f" 목표에는 Cycle {hit.get('n')}에서 처음 닿았고(지표 {_fmt(hit.get('metric'))}) 그 뒤로도 이어 돌았다." if hit else "")
    gs = rec.get("goal_set") or {}
    if gs:  # 목표 미정으로 시작해 분석이 정한 목표(261026-jipsa-11)
        note += (f" 목표는 사람이 비워 두었고 Cycle {gs.get('n')} 분석이 {', '.join(gs.get('filled') or [])}을 정했다"
                 f"({gs.get('text') or ''}). 근거: {str(gs.get('why') or '없음')[:200]}")
    sections = ["## 1. Cycle별 지표", "", *rows, "", f"{cap} 판정 값은 분석이 다시 잰 값이다.{note}",
                "", "## 2. 멈춘 까닭" if deadline else "## 2. 끝난 까닭", "", f"{why}. 줄은 할 일 절 맨 아래로 돌아갔다. {again}."]
    ex = next((r["explore"] for r in reversed(rounds) if r.get("explore")), None)
    if ex:  # 마지막 분석의 탐색 칸(261027-jipsa-03). 사람이 다음 후보를 보고 피드백한다
        cands = [f"- {x['method'][:120]} (출처 {x.get('source') or '-'}{', 시도함' if x.get('tried') else ''})" for x in ex.get("candidates") or []][:5]
        sections += ["", "## 3. 탐색과 다음 후보", "", f"시도한 것 {len(ex.get('tried') or [])}건, 찾은 후보 {len(ex.get('candidates') or [])}건이다. "
                     + (f"찾아본 곳: {'; '.join(ex.get('searched') or [])[:300]}." if ex.get("searched") else "찾아본 곳 기록이 없다."),
                     "", *(cands or ["- 후보 없음"])]
        if ex.get("repeat_why"):
            sections += ["", f"마지막 다음 명령은 기존 방법의 반복이다. 이유: {ex['repeat_why'][:200]}"]
    intro = ("Cycle 목표는 시킬 때 정한 마감까지 Cycle을 돌았다. 마감에 돌던 단계를 마치고 멈췄다. 그림은 뜻이 없어 두지 않았다." if deadline else
             "Cycle 목표는 끝 조건이 올 때까지 Cycle을 돌았다. 그림은 뜻이 없어 두지 않았다.")
    return _orch_sheet(it, status=status, label="Cycle 마감" if deadline else "Cycle 목표 끝", summary=summary, box=box, intro=intro,
                       sections=sections, options=options, rule="" if reached else f"Cycle 목표 {'마감' if deadline else '끝'}: {why[:60]}", reason=why,
                       extra={"auto_cycle": it.key, "cycle_rounds": len(rounds), "cycle_end": why, "cycle_deadline": deadline}, mode=mode)


def _close_goal(it: todo.Todo, c: workitem.Cycle, mode: dict) -> str:
    """끝난 목표의 결과지를 한 번만 쓰고 기록에 실행ID를 남긴다."""
    rec = cycle.load(c)
    if rec.get("sheet"):
        return rec["sheet"]
    rid = cycle_sheet(it, c, rec, mode)
    rec["sheet"] = rid
    cycle.save(c, rec)
    events.emit("auto_cycle_end", cycle=c.key, why=rec.get("end_reason"), rounds=len(rec.get("rounds") or []), run=rid)
    return rid


def _deadline_goal(it: todo.Todo, c: workitem.Cycle, mode: dict, why: str) -> str:
    """마감으로 멈춘 Cycle 목표(261029-jipsa-17). 기록은 끝내지 않고 마감 결과지를 쓴 뒤 멈춘 사유를 남긴다. 다시 시키면 멈춘 자리부터 잇는다(판정까지 마친 회차면 다음 회차, 아니면 그 회차의 남은 단계). 실행ID다."""
    rec = cycle.load(c)
    rid = cycle_sheet(it, c, rec, mode, why=why)
    rec = cycle.load(c)
    rec.setdefault("deadline_sheets", []).append({"run": rid, "at": now_iso(), "why": why, "rounds": len(rec.get("rounds") or [])})
    rec["paused"] = f"{why}. 다시 시키면 Cycle {_next_round(rec)}부터 잇는다"
    cycle.save(c, rec)
    events.emit("cycle_deadline", cycle=c.key, why=why, rounds=len(rec.get("rounds") or []), run=rid)
    return rid


def cycle_turn(it: todo.Todo, project: Project, mode: dict, st: dict, start, cutoff: datetime, tag: dict | None = None) -> dict | None:
    """시킨 Cycle 목표의 차례. 단계 하나를 열어 시작하면 결과 dict이고, 끝났으면 None이다.
    tag는 시키기가 단계 큐 줄에 붙이는 칸(run_now, run_cutoff)이다."""
    c = as_cycle(it)
    c.entry_extra.update(tag or {})
    rec = cycle.load(c)
    if rec.get("status") == cycle.ENDED and rec.get("sheet"):
        carry = cycle.carry_plan(rec)
        _archive(c, rec)  # 끝난 목표와 같은 줄을 다시 올렸다
        rec = cycle.load(c)
        if carry and not rec.get("rounds"):
            rec["carry"] = {**carry, "at": now_iso()}  # 지난 분석의 다음 명령을 첫 Cycle 명령으로 잇는다
            cycle.save(c, rec)
            events.emit("auto_cycle_carry", cycle=c.key, plan=str(carry["plan"].get("plan") or "")[:120], after=carry.get("n"))
    if rec.get("todo_line") != it.line():
        rec["todo_line"] = it.line()  # 줄 원문으로 목표를 다시 만든다. 상한을 고치면 여기서 바뀐다
        cycle.save(c, rec)
    _note_resume(c, rec, mode)
    # 마감까지 남은 시간이 새 단계의 상한보다 짧으면 cycle.advance가 단계를 열지 않고 paused에 이유를 남긴다(261027-jipsa-03)
    for _ in range(4):  # 한 주기에 여러 걸음(분석 끝, 판정, 새 Cycle)을 갈 수 있다
        if cycle.load(c).get("status") == cycle.ENDED:
            break
        if not cycle.advance(c, {it.project: project}, mode):
            break
    rec = cycle.load(c)
    if rec.get("status") == cycle.ENDED:
        _close_goal(it, c, mode)
        try:  # 끝난 줄은 지우지 않고 할 일 절 맨 아래로 돌려놓는다. 다시 올리면 같은 목표로 돈다(261026-jipsa-03)
            todo.move("", todo.TODO, key=it.key)
        except todo.TodoError:
            todo.take(it.key)
        return None
    pend = [r for r in queue.load() if r.get("source") == SOURCE and r.get("todo_key") == it.key and r["status"] == queue.PENDING]
    if pend:
        r = pend[-1]
        events.emit("auto_start", project=it.project, title=r["title"], run=r.get("run_id"), gpu=gpu_text(project), cycle=it.key)
        start(r, project)
        return {"state": "start", "run": r.get("run_id"), "key": r["key"], "title": r["title"], "cycle": it.key}
    return {"state": "wait", "key": it.key, "why": rec.get("paused") or "Cycle 단계 대기"}


def cycle_view(it: todo.Todo, mode: dict | None = None) -> str:
    """상태 명령의 Cycle 목표 한 줄. 몇 번째 Cycle인지, 최고 기록, 연속 정체와 상한, 마감으로 멈춘 사실."""
    c = as_cycle(it)
    rec = cycle.load(c)
    cap = cap_of(it)
    rounds = rec.get("rounds") or []
    if rec.get("status") == cycle.ENDED and rec.get("sheet"):
        return f"Cycle 목표, {cap_text(it)}. 지난 목표는 끝났고({rec.get('end_reason')}) 다시 시키면 Cycle 1부터 새로 돈다"
    miss = todo.cycle_pending(it.cycle)
    pend = f". 목표 미정({', '.join(miss)}), Cycle 1 분석이 정한다" if miss else ""
    if not rounds:
        return f"Cycle 목표, {cap_text(it)}" + ("(연속 정체 Cycle 수)" if cap else ", 마감까지 돈다") + pend + ". 아직 돌지 않았다"
    last = rounds[-1]
    rows = {r["key"]: r["status"] for r in queue.load()}  # 기록의 단계 상태는 다음 걸음에야 맞춰지므로 큐 줄에서 읽는다
    live = [k for k in (cycle.RUN, cycle.ANALYSIS)
            if rows.get((last["steps"].get(k) or {}).get("key") or "", (last["steps"].get(k) or {}).get("status")) in (queue.PENDING, queue.RUNNING)]
    where = f"Cycle {last['n']} {live[-1]} 중" if live else (f"Cycle {last['n']}까지 돌았다" if last.get("judge") else f"Cycle {last['n']} 판정 대기")
    text = f"Cycle 목표, {where}. 최고 {_fmt(rec.get('score'))}, 연속 정체 {cycle.no_gain_streak(rec)}/{cap or '없음'}" + pend
    if rec.get("reached"):
        text += f". 목표에 Cycle {rec['reached']['n']}에서 닿았고 " + ("끝낸다" if (it.cycle or {}).get("stop") else "마감까지 잇는다")
    if rec.get("paused"):
        text += f". 멈춤: {rec['paused']}"
    return text


# ----- 기준 없는 줄의 기획 단계(261025-jipsa-24) -----
def plan_criteria(it: todo.Todo) -> str:
    """기준 정하기 작업자의 완료 기준. 코드를 고치지 않고 기준 후보를 선택지로 쓴다."""
    return " ".join([
        f"이 작업은 할 일 줄의 기획 단계다. 줄 원문은 \"{it.line()}\"이고 완료 기준 칸이 비었다.",
        "코드, 문서, 설정을 고치지 않고 새 파일을 만들지 않으며 커밋하지 않는다. 쓰는 것은 보고서와 결과 파일뿐이다.",
        "저장소와 관련 자료를 읽어 이 할 일의 완료 기준 후보 2~3개를 만든다. 후보마다 세션 안에서 직접 실행해 확인할 수 있는 한 문장이고,",
        "보고서에 후보마다 재는 방법과 예상 시간을 적는다.",
        "result.json의 status는 완료, options는 \"1안: <기준 문장>(추천)\", \"2안: <기준 문장>\" 꼴이고 가장 권하는 기준을 1안에 둔다.",
        "jipsa가 1안의 기준 문장을 그대로 할 일 줄의 기준 칸에 적고 사람 답 없이 바로 본 작업을 돌리므로 세로 막대를 쓰지 않는다.",
        "기준 문장은 다음 작업의 제목과 기준이 되므로 낱말 고르기 규칙(policies/wording.md)대로 seed, LoRA, epoch, 모델 이름 같은 고유 명칭을 번역하지 않고 원어로 쓴다.",
    ])


def plan_project(project: Project) -> Project:
    """기준 정하기 작업은 GPU를 쓰지 않는다."""
    return replace(project, gpu_vram_gb=0.0, gpu_exclusive=False, ollama_models=[])


def plan_entry(it: todo.Todo, project: Project, run_id: str, mode: dict) -> dict:
    e = entry(it, project, run_id, mode)
    e.update(title=f"{PLAN_TITLE}: {it.text}"[:80], criteria=plan_criteria(it), est_minutes=PLAN_MIN, needs_gpu=False, todo_plan=it.key)
    return e


def first_criteria(options: list[str]) -> str:
    """후보 가운데 채택할 기준 문장. 추천 표시가 있는 안, 없으면 맨 앞 안이다. "N안:" 머리와 추천 표시는 뗀다. 없으면 빈 값이다."""
    opts = [str(o) for o in options or [] if str(o).strip()]
    if not opts:
        return ""
    pick = next((o for o in opts if "추천" in o), opts[0])
    m = re.match(r"^\s*\d+\s*안\s*[:：.]?\s*(.*)$", pick)
    return todo._norm(re.sub(r"\s*\(추천\)\s*$", "", m.group(1) if m else pick)).replace("|", "/").strip()


def adopt_criteria(meta: dict, crit: str) -> str:
    """기준 정하기가 끝났다. 기준을 그 줄의 기준 칸에 적는다. 줄은 제자리에 두고 같은 요청이 다음 주기에 본 작업을 시작한다.
    바뀐 줄 본문이고, 사람이 줄을 지웠으면 빈 값이다."""
    key = meta["todo_plan"]
    items, _, _ = todo.load()
    if not any(it.key == key for it in items):
        return ""  # 사람이 그 사이 줄을 지웠다. 다시 넣지 않는다
    line = todo.set_criteria(key, crit).line()
    events.emit("auto_plan_adopt", run=meta.get("run_id"), key=key, criteria=crit[:120], run_now=key in run_keys())
    return line


def _note_report(run_id: str, lines: list[str]) -> None:
    """결과지(마지막 시도의 보고서) 끝에 jipsa가 쓴 절을 붙인다."""
    dirs = record.attempt_dirs(run_id) if run_id else []
    if not dirs:
        return
    path = dirs[-1] / "report.md"
    try:
        old = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(old.rstrip() + "\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


PLAN_OPEN = (queue.PENDING, queue.RUNNING, "확인 필요")  # 기준 정하기 실행이 닫히지 않은 큐 상태. 확인 필요는 기준을 줄에 적지 못해 사람이 고르기 전이다


def open_plans() -> dict[str, dict]:
    """기준 정하기가 닫히지 않은 할 일 줄. key(프로젝트::문장) -> 그 기준 정하기의 큐 줄이다(261025-jipsa-54).

    기준 없는 줄을 시키면 기준 정하기를 먼저 돌린다. 그동안 할 일 칸과 jipsa todo는 그 줄에 이 상태를 붙이고,
    같은 줄을 다시 시키면 기준 정하기가 한 번 더 돌므로 거절한다.
    기준 칸이나 cycle 칸이 이미 찬 줄은 뺀다. 기준 정하기가 1안을 적은 뒤 결과지만 확인 필요로 남은 경우다(261026-jipsa-03)."""
    from scheduler import confirm

    filled = {it.key for it in todo.load()[0] if it.criteria or it.cycle}
    out: dict[str, dict] = {}
    for r in queue.load():
        if not r.get("todo_plan") or r.get("status") not in PLAN_OPEN or r["todo_plan"] in filled:
            continue
        if r.get("status") == "확인 필요":  # 답 없이 확인 단추로 닫았거나 결과지가 이미 닫혔으면 기준을 기다리지 않는다
            meta = record.read_json(record.RUNS / str(r.get("run_id")) / "meta.json") or {}
            if meta.get("status") != "확인 필요" or confirm.acked(str(r.get("run_id")), str(meta.get("finished") or "")):
                continue
        out[r["todo_plan"]] = r
    return out


def plan_note(r: dict) -> str:
    """기준 정하기가 닫히지 않은 할 일 줄에 붙이는 상태 글. jipsa todo 줄 끝과 대시보드 할 일 칸이 같은 글을 쓴다."""
    if r.get("status") == "확인 필요":
        return f"기준 고르기 대기({r.get('run_id')}). 기준을 줄에 적지 못했다. 확인 필요에서 기준을 고르면 이 줄에 들어가고, 그 뒤 다시 시킨다"
    return f"{PLAN_TITLE} 중({r.get('run_id')}). 끝나면 1안 기준을 이 줄에 적고 본 작업을 잇는다"


def _refuse_open_plan(it: todo.Todo) -> None:
    """기준 없는 줄에 닫히지 않은 기준 정하기가 있으면 올리기를 거절한다. 기준이나 cycle 칸을 손으로 적었으면 받는다."""
    if it.criteria or it.cycle:
        return
    r = open_plans().get(it.key)
    if r:
        raise todo.TodoError(f"{it.no}번은 {plan_note(r)}. 지금 시키면 {PLAN_TITLE}가 한 번 더 돈다")


def plan_settle(meta: dict, status: str, result: dict) -> tuple[str, dict]:
    """기준 정하기 실행의 마감. 1안 기준을 그 줄에 적고 사람 답 없이 같은 요청으로 본 작업을 잇는다(261026-jipsa-03).
    후보가 없거나 실행이 실패했으면 기본 기준을 적는다. 상태는 완료이고, 실패는 실패로 둔다. 기획 작업자가 파일을 바꿨으면 확인 필요로 둔다."""
    if not meta.get("todo_plan"):
        return status, result
    opts = [str(o) for o in result.get("options") or [] if str(o).strip()]
    crit = first_criteria(opts) if status != "실패" else ""
    src = "추천 후보" if crit else "기본 기준"
    crit = crit or PLAN_DEFAULT
    try:
        line = adopt_criteria(meta, crit)
    except (todo.TodoError, OSError) as e:
        events.emit("error", where="plan_adopt", run=meta.get("run_id"), error=str(e)[:200])
        if status == "실패":
            return status, result
        return "확인 필요", {**result, "status": "확인 필요", "rule": f"{PLAN_RULE}(기준을 줄에 적지 못했다: {str(e)[:60]})", "options": opts}
    where = ("시킨 줄이라 제자리에 두고 다음 주기에 본 작업을 시작한다" if meta.get("run_now") else "줄을 제자리에 두었다. 다시 시키면 본 작업이 돈다") \
        if line else "사람이 그 사이 줄을 지워 본 작업은 돌지 않는다"
    note = f"jipsa가 {'추천 후보를 기준으로' if src == '추천 후보' else '기본 기준을'} 채택했다: {crit}. {where}"
    _note_report(meta.get("run_id") or "", ["## jipsa가 채택한 기준", "", f"{note}."])
    evidence = [str(x) for x in result.get("evidence") or []] + [note] + ([f"바뀐 줄: {line}"] if line else [])
    out = {**result, "evidence": evidence, "options": opts, "adopted": crit, "summary": f"기준을 정해 본 작업으로 잇는다. 채택: {crit}"[:80]}
    if status == "실패":
        return status, out
    if result.get("commit") or result.get("changed_files"):
        return "확인 필요", {**out, "status": "확인 필요", "rule": "기획 작업자가 파일을 바꿨다. 그 변경은 병합하지 않는다. 기준은 채택해 본 작업을 잇는다"}
    return "완료", {**out, "status": "완료", "rule": ""}


def pick_criteria(text: str, options: list[str]) -> str:
    """답에서 기준 문장을 고른다. "1안"처럼 안 이름만 적었으면 그 안의 문장이고, 아니면 답 문장 그대로다."""
    m = re.fullmatch(r"\s*(\d+)\s*안\s*(?:으로|대로|이요|요)?\s*", text or "")
    if m:
        for o in options:
            om = re.match(rf"^\s*{m.group(1)}\s*안\s*[:：.]?\s*(.*)$", str(o))
            if om:
                return re.sub(r"\s*\(추천\)\s*$", "", om.group(1)).strip()
    return todo._norm(text)


def plan_answered(meta: dict, text: str) -> str:
    """기준 정하기 결과지에 사람이 답했다. 고른 기준을 그 줄의 기준 칸에 적는다. 줄은 제자리(할 일 절)에 두고 시키는 것은 사람이 한다.
    바뀐 줄 본문이다."""
    key = meta["todo_plan"]
    crit = pick_criteria(text, meta.get("options") or []).replace("|", "/")
    if not crit:
        raise todo.TodoError("답에서 기준 문장을 읽지 못했다")
    items, _, _ = todo.load()
    if any(it.key == key for it in items):
        line = todo.set_criteria(key, crit).line()
    else:  # 사람이 그 사이 줄을 지웠다. 원문에 기준을 붙여 할 일 절에 다시 넣는다
        base = todo.parse_line(meta.get("todo_line") or "")
        base.criteria = crit
        project, rest = base.line().split(" | ", 1)
        line = todo.add(project, rest, todo.TODO).line()
    events.emit("auto_plan_answer", run=meta.get("run_id"), key=key, criteria=crit[:120])
    return line


# ----- 한 주기 -----
def _minutes_since(iso: str) -> float:
    return (now() - parse_iso(iso)).total_seconds() / 60


def auto_running(active: set | None = None) -> list[dict]:
    """동시 상한에 드는 도는 줄. Cycle 단계와 기준 정하기다. 일회성 줄과 그 기준 정하기는 사람이 바로 시킨 일이라 뺀다."""
    active = active or set()
    return [r for r in queue.load() if r.get("source") == SOURCE and (r["status"] == queue.RUNNING or r["key"] in active)
            and not (r.get("run_now") and not r.get("cycle"))]


FOLDER_HOLD = "같은 원본 폴더의 작업자가 돌고 있다"


def folder_hold(project: Project, registry: dict, active: set | None = None) -> str:
    """원본 폴더를 쓰는 프로젝트(문서 프로젝트, jipsa 포함)는 같은 폴더에서 스케줄러 작업자 하나만 돈다. 그 작업자의 실행ID다.
    세션과 서브에이전트 실행은 세지도 막지도 않는다. 사람이 CLI처럼 여럿을 같이 돌릴 수 있게 둔다(261026-jipsa-26)."""
    if project.uses_worktree:
        return ""
    active = active or set()
    for r in queue.load():
        if r["status"] != queue.RUNNING and r["key"] not in active:
            continue
        if queue.session_owned(r):
            continue
        other = registry.get(r.get("project") or "")
        if other and not other.uses_worktree and other.path == project.path:
            return r.get("run_id") or r["key"]
    return ""


def _can(can, project: Project, registry: dict, active: set, *, key: str, kind: str, title: str = "", owner: str = "") -> tuple[bool, str]:
    """시작 판정. 원본 폴더 잠금, 그다음 자원(GPU 장부와 대기열). can은 시험에서 바꿔 끼운 자원 판정이다."""
    held = folder_hold(project, registry, active)
    if held:
        return False, f"{FOLDER_HOLD}({held})"
    if can is not None:
        return can(project)
    return resources.can_acquire_auto(project, key=key, kind=kind, title=title, owner=owner)


def step(registry: dict, mode: dict, start, *, only: str, can=None, active: set | None = None) -> dict:
    """시킨 줄 하나(key가 only)의 주기. 돌릴 것이 있으면 start(큐 줄, 프로젝트)를 부른다. 사람이 볼 결과를 dict로 돌려준다.

    state: busy(상한이 찼거나 그 줄이 돈다), resume(대기 줄을 다시 시작), start, wait(자원 대기), idle(돌릴 것이 없다).
    can은 자원 판정 함수이고 시험에서 바꿔 끼운다. active는 스케줄러가 띄운 스레드의 큐 key다. 스레드가 살아 있는 줄은 큐 상태와 무관하게
    도는 줄로 센다(261025-jipsa-23). 일회성 줄은 상한을 보지 않는다. Cycle 목표의 새 단계는 동시 상한만 본다. 사용 창 비율은 보지 않는다(261102-jipsa-50).
    261029-jipsa-17에서 Auto 목록 주기를 떼고 시킨 줄 하나만 보게 했다."""
    custom = can
    st = _state(mode)
    active = active or set()
    lanes = lane_rows()
    pool = [it for it in todo.load()[0] if it.key == only]
    mine = [r for r in lanes if r.get("todo_key") == only]
    if any(r["status"] == queue.RUNNING or r["key"] in active for r in mine):
        return {"state": "busy", "run": next(r.get("run_id") for r in mine if r["status"] == queue.RUNNING or r["key"] in active)}
    if any(it.cycle for it in pool) or any(r.get("cycle") for r in mine):
        n = len(auto_running(active))
        if n >= AUTO_CAP:
            return {"state": "busy", "why": f"Cycle 단계 {n}개가 돌아 동시 상한 {AUTO_CAP}개다"}
    tag = {"run_now": True, "run_cutoff": modes.cutoff_for(mode).isoformat(timespec="seconds")}
    first_wait: dict | None = None
    for r in [r for r in mine if r["status"] == queue.PENDING]:  # 대기로 돌아온 줄(스케줄러가 다시 켜졌다, 마감으로 멈췄다)과 Cycle의 다음 단계
        project = registry.get(r["project"])
        if not project:
            queue.update(r["key"], status=queue.SKIPPED, reason=NO_PROJECT, finished=now_iso())
            continue
        project = effective(project, r.get("limits"))
        ok, why = _can(custom, project, registry, active, key=r["key"], kind="cycle" if r.get("cycle") else "do",
                       title=r.get("title") or "", owner=r.get("todo_key") or "" if r.get("cycle") else "")
        if not ok:
            if r.get("reason") != f"자원 대기: {why}":
                queue.update(r["key"], reason=f"자원 대기: {why}")
            first_wait = first_wait or {"state": "wait", "key": r["key"], "why": why}
            continue
        if r.get("run_cutoff") != tag["run_cutoff"] or not r.get("run_now"):
            # 다시 시켰거나 마감을 고쳤다. 실행기가 이번 요청의 마감에 끊게 한다. 옛 Auto가 꺼낸 줄도 이 요청으로 잇는다
            r.update(tag)
            queue.update(r["key"], **tag)
        start(r, project)
        return {"state": "resume", "run": r.get("run_id"), "key": r["key"]}
    if first_wait:
        return first_wait

    cutoff = modes.cutoff_for(mode)
    for it in pool:
        why = classify(it, registry, st)
        if why in DROP:
            rid = skip_sheet(it, why, mode)
            todo.move("", todo.TODO, key=it.key)
            events.emit("auto_skip", project=it.project, title=it.text, why=why, run=rid)
            continue
        if why == NO_CRITERIA:
            # 기획 단계. GPU를 쓰지 않는다. 줄은 제자리에 두고 기준이 들어오면 같은 요청으로 본 작업을 잇는다
            project = plan_project(registry[it.project])
            held = folder_hold(project, registry, active)
            if held:
                return {"state": "wait", "key": it.key, "why": f"{FOLDER_HOLD}({held})"}
            run_id = record.new_run_id(project.name)
            e = queue.add_entry({**plan_entry(it, project, run_id, mode), **tag})
            _save_state(st)
            events.emit("auto_start", project=it.project, title=e["title"], run=run_id, gpu="", plan=it.key)
            start(e, project)
            return {"state": "start", "run": run_id, "key": e["key"], "title": e["title"], "plan": it.key}
        if why:
            continue
        project = effective(registry[it.project], it.limits)
        if it.cycle:
            c = as_cycle(it)
            if c.reject:
                rid = skip_sheet(it, c.reject, mode)
                todo.move("", todo.TODO, key=it.key)
                events.emit("auto_skip", project=it.project, title=it.text, why=c.reject, run=rid)
                continue
            ok, gwhy = _can(custom, project, registry, active, key=it.key, kind="cycle", title=it.text, owner=it.key)
            if not ok:
                since = st["gpu_wait"].setdefault(it.key, now_iso())
                _save_state(st)
                return {"state": "wait", "key": it.key, "why": gwhy, "minutes": int(_minutes_since(since))}
            st["gpu_wait"].pop(it.key, None)
            res = cycle_turn(it, project, mode, st, start, cutoff, tag)
            _save_state(st)
            if res is None:
                continue  # 끝났다
            return res
        ok, why = _can(custom, project, registry, active, key=it.key, kind="do", title=it.text)
        if not ok:
            since = st["gpu_wait"].setdefault(it.key, now_iso())
            _save_state(st)
            return {"state": "wait", "key": it.key, "why": why, "minutes": int(_minutes_since(since))}
        st["gpu_wait"].pop(it.key, None)
        run_id = record.new_run_id(project.name)
        e = queue.add_entry({**entry(it, project, run_id, mode), **tag})
        todo.take(it.key)
        _save_state(st)
        events.emit("auto_start", project=it.project, title=it.text, run=run_id, gpu=gpu_text(project))
        start(e, project)
        return {"state": "start", "run": run_id, "key": e["key"], "title": it.text}
    return {"state": "idle", "why": "돌릴 것이 없다"}


# ----- 시키기(261026-jipsa-12, 여러 줄과 세션 넘기기는 261026-jipsa-26, 시작과 마감은 261029-jipsa-17) -----
# 할 일 줄 하나를 돌린다. `jipsa todo run <번호|문장 일부> [시작 HH:MM] [마감 HH:MM|+4h]`과 대시보드 Do 단추가 같다.
# 일회성 줄은 시작 시각을 받지 않고 바로 돈다. 열린 세션(답 대기 명령이 떠 있는 세션)이 있으면 그 세션의 받은편지함에 Do 요청으로 넣고,
# 세션이 없거나 2분 안에 받지 않으면 스케줄러 작업자 요청으로 넘긴다(do_fallback). Cycle 목표 줄은 세션으로 보내지 않고 작업자로 돈다.
# 요청은 상태 폴더 run_now.json의 목록이고 줄마다 하나다. 같은 줄을 두 번 시키는 것만 거절한다. 스케줄러 주기마다 요청마다 run_turn이
# 그 줄 하나로 step(only=key)을 돈다. 요청은 그 일이 끝날 때 지운다: 일회성 줄은 큐 줄이 끝날 때, 기준 없는 줄은 기준 정하기 뒤 본 작업이
# 끝날 때, Cycle 목표는 끝 조건이나 마감(정하지 않으면 시작 뒤 8시간, 멈추기는 마감을 지금으로 당긴다)에.
RUN_FILE = STATE / "run_now.json"
RUN_STATE = STATE / "run_now_state.json"  # 시키기의 GPU 대기 기록
_RUN_LOCK = STATE / "run_now.lock"
RUN_END = "마감"
STOP_END = "사람이 멈춤"
RUN_TAG = "시킨 줄"
DO_TAG = "세션에 보낸 줄"
DEADLINE_HOLD = "마감 "  # cycle.deadline_room 문장의 머리. 마감 전에 다음 단계를 마칠 시간이 없다는 멈춤이다
NOW_WORDS = ("", "지금", "now", "바로")


class _run_lock:
    """요청 목록을 읽고 고치는 동안 잡는 파일 잠금. 대시보드, 명령, 스케줄러가 같은 파일을 고친다. 10초 넘은 잠금은 버린다."""

    def __enter__(self):
        import os
        import time

        _RUN_LOCK.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(100):
            try:
                os.close(os.open(_RUN_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if time.time() - _RUN_LOCK.stat().st_mtime > 10:
                        _RUN_LOCK.unlink()
                except OSError:
                    pass
                time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        try:
            _RUN_LOCK.unlink()
        except OSError:
            pass


def run_requests() -> list[dict]:
    """시킨 줄 요청 목록. 옛 한 건 꼴(dict)도 읽는다."""
    try:
        data = json.loads(RUN_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(data, dict):
        data = [data]
    return [r for r in data if isinstance(r, dict) and r.get("key")] if isinstance(data, list) else []


def run_request(key: str = "") -> dict | None:
    """key의 요청. key가 없으면 첫 요청이다."""
    reqs = run_requests()
    return next((r for r in reqs if not key or r["key"] == key), None)


def run_keys() -> set[str]:
    return {r["key"] for r in run_requests()}


def _write_runs(reqs: list[dict]) -> None:
    RUN_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not reqs:
        try:
            RUN_FILE.unlink()
        except OSError:
            pass
        return
    RUN_FILE.write_text(json.dumps(reqs, ensure_ascii=False, indent=1), encoding="utf-8")


def _save_run(req: dict) -> None:
    with _run_lock():
        reqs = run_requests()
        if any(r["key"] == req["key"] for r in reqs):
            reqs = [req if r["key"] == req["key"] else r for r in reqs]
        else:
            reqs.append(req)
        _write_runs(reqs)


def _clear_run(req: dict, why: str) -> dict:
    with _run_lock():
        _write_runs([r for r in run_requests() if r["key"] != req.get("key")])
    events.emit("run_now_end", key=req.get("key"), why=why, row=req.get("row"))
    return {"state": "end", "why": why, "key": req.get("key")}


def parse_when(text: str, after: datetime) -> datetime:
    """시각 글을 after 뒤의 시각으로. HH:MM은 after 뒤 처음 오는 그 시각, +4h와 90m은 after에서 그만큼 뒤다. 틀리면 TodoError다."""
    t = str(text or "").strip()
    span = modes.parse_span(t)
    if span is not None:
        return after + span
    try:
        return next_cutoff(after, parse_hhmm(t))
    except ValueError:
        raise todo.TodoError(f"시각 형식이 틀렸다({t}). HH:MM이나 +4h 꼴이다") from None


def req_cutoff(req: dict) -> datetime:
    """요청의 마감. 시킬 때 정한 시각(cutoff)이고, 옛 요청은 시킨 시각과 마감 글(until)로 셈한다."""
    if req.get("cutoff"):
        return parse_iso(req["cutoff"])
    return modes.cutoff_for({"mode": modes.AUTO, "since": req["since"], "until": req.get("until") or f"+{modes.AUTO_HOURS:g}h"})


def req_start(req: dict) -> datetime | None:
    return parse_iso(req["start_at"]) if req.get("start_at") else None


def run_mode(req: dict) -> dict:
    """시키기 한 건이 쓰는 모드 값. cycle.deadline_room과 단계 큐 줄의 마감(modes.cutoff_for)이 요청 마감이 되도록 시킨 시각과 길이로 만든다.
    모드 파일은 바꾸지 않는다. since는 이 요청의 표지이기도 해서 Cycle 기록이 다시 시킨 것을 알아본다(_note_resume)."""
    # 길이를 분으로 적으면 반올림으로 마감이 1초 앞당겨질 수 있어(초 단위로 자르는 단계 줄 마감) 1ms를 더해 요청 마감 뒤로 맞춘다
    mins = max(0.0, (req_cutoff(req) - parse_iso(req["since"])).total_seconds() + 0.001) / 60
    return {"mode": modes.AUTO, "since": req["since"], "until": f"+{mins:.6f}m", "run_now": True}


def ask_run(query: str, until: str | None = None, *, start: str | None = None, session: bool = True) -> tuple[todo.Todo, list[str]]:
    """시키기 명령. 고른 줄을 열린 세션에 Do 요청으로 넣거나 작업자 요청으로 적는다. 거절이면 TodoError다. 고른 줄과 알릴 줄이다.
    start는 시작 시각(HH:MM이나 +30m, 비우거나 지금이면 바로)이고, until은 마감(HH:MM이나 +4h, 비우면 시작 뒤 8시간)이다.
    시작 시각을 적은 줄은 예약이다. Cycle이 아닌 줄도 예약하면 세션에 보내지 않고 그 시각에 스케줄러 작업자로 돈다(261029-jipsa-20).
    session이 거짓이면 세션을 보지 않고 작업자 요청으로 적는다(세션이 받지 않은 Do를 넘길 때)."""
    from scheduler import supervise
    from scheduler.registry import load_all

    items, _, _ = todo.load()
    it = next((x for x in items if x.key == query), None) or todo.find(query, items)  # 세션이 받지 않은 Do는 줄 key로 넘어온다
    req = run_request(it.key)
    if req:
        raise todo.TodoError(f"{it.no}번은 이미 시킨 줄이다({run_note(req)}). 같은 줄은 두 번 시키지 않는다")
    live = [r for r in lane_rows() if r.get("todo_key") == it.key and r["status"] == queue.RUNNING]
    if live:
        r = live[0]
        raise todo.TodoError(f"{it.no}번은 이미 도는 줄이다({r['project']} | {r['title']} | {r.get('run_id')}). 끝난 뒤 다시 시킨다")
    sent = record.do_open(it.key) if session else None
    if sent:
        raise todo.TodoError(f"{it.no}번은 이미 세션에 보낸 줄이다({str(sent['ts'])[11:16]}). 같은 줄은 두 번 시키지 않는다")
    start = (start or "").strip()
    if start.lower() in NOW_WORDS:
        start = ""
    registry = load_all()
    why = classify(it, registry)
    if why == NO_PROJECT:
        raise todo.TodoError(f"{it.no}번은 등록부에 없는 프로젝트라 시키지 못한다")
    _refuse_open_plan(it)
    if it.cycle and as_cycle(it).reject:
        raise todo.TodoError(f"{it.no}번의 cycle 칸을 읽지 못한다({as_cycle(it).reject})")
    target = record.open_session() if session and not it.cycle and not start else ""  # 예약은 시각에 맞춰 스케줄러가 시작한다
    if target:
        record.do_add(it, target)
        return it, [f"세션에 보냈다({it.no}번): {it.line()}",
                    f"열린 세션({target})의 답 대기 명령이 몇 초 안에 깨워 jipsa begin으로 열고 서브에이전트에 맡긴다. "
                    f"{DO_SESSION_GRACE_SEC // 60}분 안에 받지 않으면 스케줄러 작업자로 넘긴다."]
    if why == MANUAL_ONLY:
        raise todo.TodoError(f"{it.no}번은 세션 전용 프로젝트라 스케줄러가 돌리지 않는다. 열린 세션이 없다. 세션을 열고 답 대기 명령을 띄운 뒤 다시 시킨다")
    at = now()
    begin = parse_when(start, at) if start else None
    span = (until or "").strip() or f"+{modes.AUTO_HOURS:g}h"
    cut = parse_when(span, begin or at)
    req = {"key": it.key, "project": it.project, "text": it.text, "line": it.line(), "at": at.isoformat(timespec="seconds"),
           # since는 요청의 표지다. 같은 초에 다시 시켜도 Cycle 기록이 다시 시킨 것을 알아보게 마이크로초까지 적는다
           "since": datetime.now().isoformat(timespec="microseconds"), "until": span, "cutoff": cut.isoformat(timespec="seconds"),
           "state": "시작 예정" if begin else "시작 대기", "why": ""}
    if begin:
        req["start_at"] = begin.isoformat(timespec="seconds")
    _save_run(req)
    events.emit("run_now", key=it.key, project=it.project, title=it.text, until=span, cutoff=req["cutoff"], start=req.get("start_at") or "")
    if begin:
        lines = [f"예약했다({it.no}번): {it.line()}", f"{begin:%m-%d %H:%M}에 대기열에 서고 자원이 나면 시작한다. 마감 {cut:%m-%d %H:%M}."]
    else:
        lines = [f"시켰다({it.no}번): {it.line()}",
                 "2초 안에 스케줄러 작업자로 시작한다. 자원이 모자라면 대기열에 선다." + ("" if it.cycle or not session else " 열린 세션이 없어 작업자로 넘겼다.")]
    if it.cycle:
        lines.append(f"Cycle 목표라 작업자로 돈다. 끝 조건이나 마감 {cut:%m-%d %H:%M}까지 돌고, 마감이면 돌던 단계를 마친 뒤 끝 결과지를 쓰고 "
                     "할 일 절 맨 아래로 돌아간다. 다시 시키면 멈춘 자리부터 잇는다(판정까지 마친 회차면 다음 회차, 아니면 그 회차의 남은 단계).")
    elif not it.criteria:
        lines.append(f"기준 칸이 없어 {PLAN_TITLE}를 먼저 돌리고, 1안 기준을 이 줄에 적은 뒤 본 작업을 잇는다.")
    else:
        lines.append("시작하면 줄은 할 일 파일에서 빠지고 끝나면 결과지가 남는다.")
    if not supervise.status().get("alive"):
        lines.append("스케줄러가 꺼져 있다. 켜야 시작한다(jipsa run).")
    return it, lines


def _pick_req(query: str) -> dict:
    """번호, 문장 일부, 줄 key로 고른 줄의 요청. 없으면 TodoError다."""
    req = run_request(query)
    if req:
        return req
    items, _, _ = todo.load()
    it = todo.find(query, items)
    req = run_request(it.key)
    if not req:
        raise todo.TodoError(f"{it.no}번은 시킨 줄이 아니다")
    return req


def stop_run(query: str) -> tuple[dict, list[str]]:
    """멈추기(261029-jipsa-17). 마감을 지금으로 당긴다. 돌던 단계는 끝까지 가고, 그 뒤 끝 결과지를 쓰고 할 일로 돌아간다. 다시 시키면 잇는다."""
    req = _pick_req(query)
    begin = req_start(req)
    if begin and now() < begin and not any(r.get("todo_key") == req["key"] for r in lane_rows()):
        # 시작 전 예약은 돌던 단계가 없어 바로 지운다. 줄은 할 일에 그대로 있어 다음 주기를 기다리지 않고 할 일 칸에 돌아온다(261029-jipsa-20)
        _clear_run(req, "예약을 지웠다")
        return req, [f"예약을 지웠다: {req['text']}", "줄은 할 일에 그대로 있다."]
    with _run_lock():
        reqs = run_requests()
        hit = next((r for r in reqs if r["key"] == req["key"]), None)
        if hit is None:
            raise todo.TodoError("요청이 그 사이 끝났다")
        hit["cutoff"], hit["stopped"] = now_iso(), now_iso()
        _write_runs(reqs)
    events.emit("run_now_stop", key=req["key"])
    running = [r for r in lane_rows() if r.get("todo_key") == req["key"] and r["status"] == queue.RUNNING]
    return hit, [f"멈췄다: {req['text']}", "돌던 단계는 끝까지 간다. 그 뒤 끝 결과지를 쓰고 할 일 절 맨 아래로 돌아가며, 다시 시키면 멈춘 자리부터 잇는다(판정까지 마친 회차면 다음 회차, 아니면 그 회차의 남은 단계)."
                 if running else "도는 단계가 없어 다음 주기에 닫는다. 다시 시키면 멈춘 자리부터 잇는다(판정까지 마친 회차면 다음 회차, 아니면 그 회차의 남은 단계)."]


def set_until(query: str, text: str) -> tuple[dict, list[str]]:
    """도는 Cycle의 마감을 고친다. HH:MM이나 +4h이고, 기준은 지금(시작 예정이면 시작 시각)이다. 다음 단계부터 따른다."""
    req = _pick_req(query)
    base = max(now(), req_start(req) or now())
    cut = parse_when(text, base)
    with _run_lock():
        reqs = run_requests()
        hit = next((r for r in reqs if r["key"] == req["key"]), None)
        if hit is None:
            raise todo.TodoError("요청이 그 사이 끝났다")
        hit["cutoff"], hit["until"] = cut.isoformat(timespec="seconds"), text.strip()
        hit.pop("stopped", None)
        _write_runs(reqs)
    for r in lane_rows():  # 아직 시작하지 않은 단계 줄은 새 마감에 끊는다. 도는 단계는 시작할 때의 마감을 쓴다
        if r.get("todo_key") == req["key"] and r["status"] == queue.PENDING:
            queue.update(r["key"], run_cutoff=cut.isoformat(timespec="seconds"))
    events.emit("run_now_until", key=req["key"], cutoff=hit["cutoff"])
    return hit, [f"마감을 {cut:%m-%d %H:%M}로 바꿨다: {req['text']}", "다음 단계부터 따른다."]


def do_fallback() -> list[str]:
    """세션이 2분 안에 받지 않은 Do 요청을 작업자 요청으로 넘긴다. 스케줄러 주기마다 부른다. 넘긴 줄 key 목록이다."""
    out = []
    for r in record.do_stale(DO_SESSION_GRACE_SEC):
        try:
            ask_run(r["todo_key"], session=False)
            out.append(r["todo_key"])
            events.emit("do_fallback", key=r["todo_key"], session=r.get("parent_run"))
        except todo.TodoError as e:
            events.emit("do_fallback_refused", key=r["todo_key"], why=str(e)[:200])
    return out


def run_note(req: dict) -> str:
    """시킨 줄 끝에 붙이는 상태 글. jipsa todo 줄 끝과 대시보드가 같은 글을 쓴다."""
    state, why = req.get("state") or "시작 대기", req.get("why") or ""
    st = req_start(req)
    text = {"시작 대기": "곧 작업자로 시작한다", "시작 예정": f"{st:%H:%M}에 시작한다" if st else "곧 시작한다",
            "busy": "상한이 차 기다린다",
            "wait": "기다린다", "plan": f"{PLAN_TITLE} 중. 끝나면 1안 기준으로 본 작업을 잇는다",
            "cycle": "Cycle 목표를 돈다", "run": "도는 중", "closing": "마감, 돌던 단계가 끝나면 닫는다"}.get(state, state)
    return f"{RUN_TAG}. {text}" + (f"({why})" if why and state in ("busy", "wait") else "")


def _finish(req: dict, it: todo.Todo | None, live: list[dict], active: set, why: str) -> dict:
    """마감이나 멈추기로 요청을 닫는다(마감 처리 하나, 261029-jipsa-17). 돌던 단계가 있으면 끝날 때까지 기다린다.
    Cycle 목표는 기록을 끝내지 않고 마감 결과지를 쓴 뒤 할 일 절 맨 아래로 돌린다. 한 회차도 돌지 않았으면 결과지 없이 닫는다.
    아직 시작하지 않은 Cycle 단계 줄은 대기열에서만 빼고 큐에 남긴다. 다시 시키면 그 단계부터 잇는다."""
    if any(r["status"] == queue.RUNNING or r["key"] in active for r in live):
        if req.get("state") != "closing" and run_request(req["key"]) is not None:
            req.update(state="closing", why="")
            _save_run(req)
        return {"state": "busy", "why": "마감, 돌던 단계가 끝나면 닫는다"}
    mode = run_mode(req)
    if it is not None and it.cycle:
        c = as_cycle(it)
        rec = cycle.load(c)
        if rec.get("status") == cycle.ENDED:
            _close_goal(it, c, mode)
        elif rec.get("rounds"):
            _deadline_goal(it, c, mode, why)
        try:
            todo.move("", todo.TODO, key=it.key)
        except todo.TodoError:
            pass
    for r in live:
        if r.get("cycle"):
            resources.queue_drop(r["key"])
            queue.update(r["key"], reason="마감으로 멈춘 Cycle의 남은 단계. 다시 시키면 잇는다")
        else:
            queue.update(r["key"], status=queue.SKIPPED, reason=RUN_END, finished=now_iso())
    resources.queue_drop(req["key"])
    return _clear_run(req, why)


def run_turn(registry: dict, start, req: dict | None = None, *, can=None, active: set | None = None) -> dict | None:
    """시키기 한 건의 한 주기. req가 없으면 첫 요청이고, 요청이 없으면 None이다. 스케줄러 주기마다 요청마다 부른다."""
    req = req or run_request()
    if not req:
        return None
    active = active or set()
    key = req["key"]
    rows = {r["key"]: r for r in queue.load()}
    live = [r for r in lane_rows() if r.get("todo_key") == key]
    if req.get("row"):  # 일회성 본 작업을 시작했다. 큐 줄이 끝나면 요청을 지운다
        r = rows.get(req["row"])
        if r is None or (r["status"] not in (queue.PENDING, queue.RUNNING) and req["row"] not in active):
            return _clear_run(req, f"끝났다({(r or {}).get('status', '큐 줄 없음')})")
        if r["status"] == queue.RUNNING or req["row"] in active:
            return {"state": "busy", "run": r.get("run_id")}
    items, _, _ = todo.load()
    it = next((x for x in items if x.key == key), None)
    if it is None and not live:
        return _clear_run(req, "줄이 없어졌다")
    cut = req_cutoff(req)
    begin = req_start(req)
    if now() >= cut:
        stopped = req.get("stopped")
        return _finish(req, it, live, active, f"{STOP_END} {stopped[5:16].replace('T', ' ')}" if stopped else f"{RUN_END} {cut:%m-%d %H:%M}")
    if begin and now() < begin and not live:
        return {"state": "scheduled", "key": key, "at": req["start_at"]}
    if it is not None and not it.criteria and not it.cycle and req.get("plan") and not live:
        return _clear_run(req, f"{PLAN_TITLE} 뒤에도 기준이 줄에 들지 않았다")  # 기준 정하기를 두 번 돌리지 않는다
    res = step(registry, run_mode(req), start, can=can, active=active, only=key)
    state = res["state"]
    if state == "idle":
        return _clear_run(req, "Cycle 목표가 끝났다" if it is not None and it.cycle else "돌릴 것이 없다")
    if state == "wait" and it is not None and it.cycle and str(cycle.load(as_cycle(it)).get("paused") or "").startswith(DEADLINE_HOLD):
        # 마감 전에 다음 단계를 마칠 시간이 없다. 마감까지 기다리지 않고 지금 닫는다(마감 처리 하나)
        return _finish(req, it, [r for r in lane_rows() if r.get("todo_key") == key], active, f"{RUN_END} {cut:%m-%d %H:%M}(다음 단계를 마칠 시간이 없다)")
    if state == "start":
        if res.get("plan"):
            req.update(plan=res.get("run"), state="plan", why="")
        elif res.get("cycle"):
            req.update(state="cycle", why="")
        else:
            req.update(row=res.get("key"), run=res.get("run"), state="run", why="")
    elif state == "resume":
        r = rows.get(res.get("key") or "") or {}
        req.update(state="plan" if r.get("todo_plan") else "cycle" if r.get("cycle") else "run", why="")
        if not r.get("todo_plan") and not r.get("cycle"):
            req["row"] = res.get("key")
    elif state in ("busy", "wait"):
        if not (state == "busy" and req.get("state") in ("plan", "cycle", "run")):
            req.update(state=state, why=str(res.get("why") or res.get("run") or ""))
    if run_request(key) is not None:  # 그 사이 사람이 취소했으면 되살리지 않는다
        _save_run(req)
    return res


def cancel_wait(key: str) -> str:
    """대기열에서 사람이 뺀 줄(261026-jipsa-26). 시킨 줄이면 멈추기와 같고(Cycle은 다시 시키면 잇는다), 그 밖의 큐 대기 줄은 건너뜀으로 닫는다.
    한 일 한 문장을 돌려준다."""
    resources.queue_drop(key)
    row = queue.get(key)
    req = run_request(key) or (run_request(row["todo_key"]) if row and row.get("todo_key") else None)
    if req:
        stop_run(req["key"])
        return f"대기열에서 뺐다. 시킨 줄은 할 일로 돌아간다: {req['text']}"
    if row and row["status"] == queue.PENDING:
        queue.update(key, status=queue.SKIPPED, reason="사람이 대기열에서 뺌", finished=now_iso())
        return f"대기 줄을 닫았다: {row['title']}"
    return "대기열에서 뺐다"


# ----- 아침 모음 글(261029-jipsa-17, 옛 Auto 끝 글을 대신한다) -----
MORNING_FILE = STATE / "morning.json"  # 마지막으로 보낸 날짜와 시각


def _morning_at(day) -> datetime:
    try:
        t = parse_hhmm(MORNING_AT)
    except ValueError:
        t = parse_hhmm("07:30")
    return datetime.combine(day, t)


def cycle_sheets(since: str) -> list[dict]:
    """since 뒤에 쓴 Cycle 끝 결과지와 마감 결과지의 실행 기록(jipsa가 쓴 결과지, auto_cycle 칸)이다."""
    day = since[2:10].replace("-", "")  # 실행ID 머리의 날짜(YYMMDD). 그날 이후 폴더만 읽는다
    out = []
    for d in sorted(record.RUNS.glob("[0-9]" * 6 + "-*")) if record.RUNS.exists() else []:
        if d.name[:6] < day:
            continue
        m = record.meta_of(d.name)
        if m and m.get("auto_cycle") and str(m.get("finished") or "") >= since:
            out.append(m)
    last = {m["auto_cycle"]: m for m in sorted(out, key=lambda m: str(m.get("finished") or ""))}  # 같은 목표는 마지막 결과지 하나다
    return list(last.values())


def digest_card(metas: list[dict], since: str, at: datetime) -> str:
    """아침 모음 Slack 글. 결과지 글과 같은 틀(머리 줄, 한 일, 결과, 사람이 할 일, 답하는 곳)이고 링크와 실행ID를 넣지 않는다."""
    head = f"[밤 사이 Cycle] {since[5:16].replace('T', ' ')}부터 {at:%m-%d %H:%M}까지 끝나거나 멈춘 Cycle {len(metas)}건"
    names = [f"{report._shorten(str(m.get('title') or ''), 30)}(Cycle {m.get('cycle_rounds') or 0}, "
             f"{'마감' if m.get('cycle_deadline') else '끝'}, {m.get('status')})" for m in metas]
    reached = sum(1 for m in metas if m.get("status") == "완료")
    stopped = sum(1 for m in metas if m.get("cycle_deadline"))
    held = [m for m in metas if m.get("status") in report.SEND_NOW]
    did = "; ".join(names[:6]) + (f" 외 {len(names) - 6}건" if len(names) > 6 else "")
    res = f"목표에 닿음 {reached}, 마감으로 멈춤 {stopped}(다시 시키면 멈춘 자리부터 잇는다(판정까지 마친 회차면 다음 회차, 아니면 그 회차의 남은 단계)), 끝 조건으로 끝남 {len(metas) - stopped}"
    if held:
        todo_line = (f"확인 필요 결과지 {len(held)}건을 보고 고른다: " + ", ".join(report._shorten(str(m.get("title") or ""), 30) for m in held[:END_TITLES])
                     + (f" 외 {len(held) - END_TITLES}건" if len(held) > END_TITLES else ""))
    else:
        todo_line = "목표에 닿은 Cycle의 결과를 보고 병합을 정한다" if reached else "없다"
    return "\n".join(report.card_lines(head, {"한 일": did, "결과": res, "사람이 할 일": todo_line}, "", [], answer=bool(held)))


def morning_digest(at: datetime | None = None, send: bool = True) -> str | None:
    """하루 한 번 아침 시각(MORNING_AT)이 지나면 지난 모음 뒤에 끝나거나 마감으로 멈춘 Cycle을 모아 Slack 글 하나를 보낸다.
    처음이면 하루 전 아침 시각부터 본다. 모을 것이 없으면 보내지 않는다. 보낸 글이고, 보낼 때가 아니거나 없으면 None이다."""
    at = at or now()
    mark = _morning_at(at.date())
    if at < mark:
        return None
    try:
        st = json.loads(MORNING_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st = {}
    if st.get("date") == at.date().isoformat():
        return None
    since = str(st.get("at") or (mark - timedelta(days=1)).isoformat(timespec="seconds"))
    metas = cycle_sheets(since)
    MORNING_FILE.parent.mkdir(parents=True, exist_ok=True)
    MORNING_FILE.write_text(json.dumps({"date": at.date().isoformat(), "at": at.isoformat(timespec="seconds"), "count": len(metas)},
                                       ensure_ascii=False), encoding="utf-8")
    if not metas:
        events.emit("morning_digest", count=0, since=since)
        return None
    text = digest_card(metas, since, at)
    result = ""
    if send:
        from notify import slack

        result = slack.notify(text)
    events.emit("morning_digest", count=len(metas), since=since, result=result)
    return text


# ----- 상태 -----
def status_lines(registry: dict) -> list[str]:
    """`jipsa status`와 옛 `jipsa auto`가 찍는 줄. 동시 Cycle 수와 상한, 시킨 줄, 대기열, 시작 예정."""
    lines = [f"동시 Cycle {len(auto_running())}/{AUTO_CAP}. 일회성 Do는 세지 않는다"]
    items = {it.key: it for it in todo.load()[0]}
    for req in run_requests():
        it = items.get(req["key"])
        st = req_start(req)
        when = (f"시작 {st:%m-%d %H:%M}, " if st else "") + f"마감 {req_cutoff(req):%m-%d %H:%M}"
        extra = f" | {cycle_view(it)}" if it is not None and it.cycle else ""
        lines.append(f"  {req['project']} | {req['text']} | {run_note(req)} | {when}{extra}")
    q = resources.queue_rows()
    lines.append(f"대기열 {len(q)}건")
    for i, r in enumerate(q, 1):
        lines.append(f"  {i}. {r['project']} | {r['title']} | GPU {r.get('need') or 0:g}GB, RAM {r.get('ram') or 0:g}GB | {r.get('why') or ''}")
    return lines


_ = datetime  # 형 표기
