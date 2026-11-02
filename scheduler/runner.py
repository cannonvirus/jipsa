"""실행기. 작업 하나를 run, analyze(Sol 공격), search, reply로 돌린다(261024-jipsa-11).

구간과 진전 검사(2.5), 재시도(2.4), 시간 상한에 걸리면 jipsa가 대신 커밋(2.5), doc 프로젝트의 저장 커밋(3.2),
한도 대기(2.8)를 여기서 한다. 모든 단계는 파일만 넘긴다. 분석자는 작업자의 컨텍스트를 물려받지 않는다.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from adapters import claude, codex
from adapters.base import AdapterError, LimitError
from scheduler import attack, codex_window, events, modes, prompts, queue, record, resources, workspace
from scheduler.config import (
    CODEX_WORKER_MODEL,
    NO_PROGRESS_LIMIT,
    RULES_FILE,
    RUNS,
    SEARCH_SOURCES,
    SEARCH_TIMEOUT_SEC,
    SETTINGS_FILE,
    norm_record,
    now,
    now_iso,
    redact,
)
from scheduler.registry import Project, write_settings

VALID_STATUS = {"완료", "실패", "확인 필요"}
new_run_id = record.new_run_id  # 실행ID 규칙은 기록 계층에 있다


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict | None:
    try:
        return norm_record(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _minutes(a: datetime, b: datetime) -> int:
    return max(0, int((b - a).total_seconds() // 60))


class TaskRun:
    def __init__(self, project: Project, qitem: dict, *, run_id: str, dry_run: bool = False):
        self.project = project
        self.q = qitem
        self.run_id = run_id
        self.dry_run = dry_run
        self.run_dir = RUNS / run_id
        self.meta = _read_json(self.run_dir / "meta.json") or {}
        self.unattended = modes.is_unattended()

    # ----- 기록 -----
    def save_meta(self, **fields) -> dict:
        self.meta.update(fields)
        self.meta["updated"] = now_iso()
        _write_json(self.run_dir / "meta.json", self.meta)
        return self.meta

    def emit(self, kind: str, **data) -> None:
        events.emit(kind, run=self.run_id, **data)

    def add_tokens(self, usage: dict | None, calls: int = 1) -> None:
        """작업자 호출의 사용량을 meta.tokens에 더한다. 판정과 분석 호출은 세지 않는다."""
        u = usage or {}
        tok = dict(self.meta.get("tokens") or {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0, "calls": 0})
        tok["input"] += int(u.get("input_tokens", 0))
        tok["cache_write"] += int(u.get("cache_creation_input_tokens", 0))
        tok["cache_read"] += int(u.get("cache_read_input_tokens", 0))
        tok["output"] += int(u.get("output_tokens", 0))
        tok["calls"] += calls
        self.save_meta(tokens=tok)

    # ----- 준비 -----
    def prepare(self) -> tuple[Path, str | None, str] | None:
        """작업 폴더, 브랜치, 분기점을 돌려준다. 저장 커밋이 막히면 None(확인 필요)."""
        p = self.project
        if self.meta.get("workspace"):
            return Path(self.meta["workspace"]), self.meta.get("branch"), self.meta["base"]
        if p.uses_worktree:
            wt, branch, base = workspace.add_worktree(p, self.run_id, self.q["title"], self.q.get("start_ref") or "")
            self.save_meta(workspace=str(wt), branch=branch, base=base)
            self.emit("worktree", path=str(wt), branch=branch)
            return wt, branch, base
        # doc 프로젝트. 원본 폴더에서 돌고, 커밋 안 된 파일은 저장 커밋으로 묶는다.
        if workspace.is_repo(p.path):
            def msg_fn(files, diff):
                return claude.judge(prompts.save_commit_message(files, diff))

            saved = workspace.save_commit(p, msg_fn)
            if saved.get("hold"):
                self.save_meta(status="확인 필요", rule="읽지 않음 경로가 커밋 안 된 상태", reason=saved["reason"],
                               options=["그 파일을 사람이 정리한 뒤 다시 돌린다", "이 항목을 할 일 목록에서 뺀다"], summary=saved["reason"])
                return None
            if saved.get("done"):
                self.save_meta(save_commit=saved["commit"])
                self.emit("save_commit", commit=saved["commit"], files=len(saved["files"]))
            base = workspace.head(p.path)
        else:
            base = ""
        self.save_meta(workspace=str(p.path), branch=None, base=base)
        return p.path, None, base

    # ----- 공급자 -----
    def switch(self, stage: str, src: str, dst: str, why: str, attempt: int | None = None) -> None:
        """공급자 전환을 이벤트와 meta에 남긴다. 보고서 환경 줄과 대시보드 기록이 이것을 센다."""
        self.emit("provider_switch", attempt=attempt, stage=stage, **{"from": src, "to": dst, "why": why})
        rows = list(self.meta.get("provider_switches") or [])
        rows.append({"ts": now_iso(), "stage": stage, "from": src, "to": dst, "why": why})
        self.save_meta(provider_switches=rows)

    def pick_worker(self, attempt: int) -> str:
        """시도 시작 때 작업자 공급자를 정한다. 큐 항목, 등록부, 기본값 순서다. 구간 중간에는 바꾸지 않는다."""
        requested = self.q.get("worker") or self.project.worker_provider or codex_window.CLAUDE
        provider = codex_window.pick_worker(requested)
        # 등록부 모델은 요청한 공급자의 것이다. 요청 값이 잘못되어 Claude로 갔으면 Claude 기본 모델을 쓴다
        own = self.project.worker_model if provider == requested else ""
        model = own or (CODEX_WORKER_MODEL if provider == codex_window.CODEX else claude.MODEL_WORKER)
        self.save_meta(worker_provider=provider, worker_requested=requested, worker_switched="", model=model)
        return provider

    def forbidden_writes(self, ws: Path, before: set[str]) -> list[str]:
        """Codex 작업자는 deny 설정이 없으므로 구간 끝에 git 상태로 금지 경로 쓰기를 찾는다. 시작 전부터 바뀌어 있던 파일은 뺀다."""
        if not workspace.is_repo(ws):
            return []
        p = self.project
        files = set(workspace.dirty_files(ws))
        if self.meta.get("base"):
            files |= set(workspace.changed_files(ws, self.meta["base"]))
        files -= before
        return sorted(set(workspace.matches_no_read(sorted(files), p.no_read + p.read_only + list(p.generated))))

    def late_feedback(self, att_dir: Path) -> str:
        """Cycle 단계가 열린 뒤 들어온 사람 피드백 중 아직 넘기지 않은 것의 문장(261027-jipsa-02). 구간 지시문에 한 번 붙인다.
        피드백 명령이 이미 plan.md에 넣은 id는 작업자가 그 파일에서 읽으므로 넘긴 것으로 친다."""
        if not self.q.get("cycle"):
            return ""
        from scheduler import cycle

        sent = set(self.meta.get("feedback_sent") or [])
        plan = _read_text(att_dir / "plan.md") or ""
        new = [e for e in cycle.feedback_late(self.q) if e["id"] not in sent and f"[{e['id']}]" not in plan]
        if not new:
            return ""
        self.save_meta(feedback_sent=sorted(sent | {e["id"] for e in new}))
        self.emit("cycle_feedback_live", ids=[e["id"] for e in new])
        return cycle.live_note(new)

    # ----- run 단계 -----
    def run_stage(self, attempt: int, ws: Path, branch: str | None, base: str, total_deadline: datetime,
                  prior_analysis: str | None, answer: str | None) -> dict:
        p = self.project
        att_dir = self.run_dir / f"attempt-{attempt}"
        att_dir.mkdir(parents=True, exist_ok=True)
        settings = write_settings(p)
        provider = self.pick_worker(attempt)
        same = (self.meta.get("session_provider") or codex_window.CLAUDE) == provider
        session = self.meta.get("session") if answer and same else None
        handover = False  # 같은 시도 안에서 Codex 한도로 Claude가 이어받는 첫 구간
        before = set(workspace.dirty_files(ws)) if provider == codex_window.CODEX and workspace.is_repo(ws) else set()
        model = self.meta.get("model") or claude.MODEL_WORKER
        seg = 1
        prev_progress = None
        no_progress = 0
        segments: list[dict] = []
        outcome: dict = {}
        limit_waits: list[str] = []
        stage_start = now()
        self.emit("stage_start", attempt=attempt, stage="run")

        while True:
            t0 = now()
            if t0 >= total_deadline:
                outcome = {"status": "실패", "reason": "시간 상한", "category": "시간 초과"}
                break
            seg_deadline = min(t0 + timedelta(minutes=p.segment_minutes), total_deadline)
            timeout = max(60, int((seg_deadline - t0).total_seconds()))
            late = self.late_feedback(att_dir)
            if (seg == 1 and not session) or handover:
                prompt = prompts.worker_first(
                    project=p, title=self.q["title"], criteria=self.q["criteria"] + (" " + late if late else ""), run_id=self.run_id, attempt=attempt,
                    workspace=ws, run_dir=att_dir, branch=branch, total_deadline=total_deadline,
                    segment_deadline=seg_deadline, dry_run=self.dry_run, prior_analysis=prior_analysis, answer=answer,
                    handover=handover, codex=provider == codex_window.CODEX, limits=self.q.get("limits"),
                )
                handover = False
            else:
                prompt = prompts.worker_next(segment=seg, segment_deadline=seg_deadline, total_deadline=total_deadline,
                                             run_dir=att_dir, note=late, answer=answer if seg == 1 else None)
            self.emit("segment_start", attempt=attempt, stage="run", segment=seg, deadline=seg_deadline.isoformat(timespec="minutes"))

            def on_tool(ev, _seg=seg):
                self.emit("tool", attempt=attempt, stage="run", segment=_seg, parent=ev.parent_id,
                          tool=ev.tool, summary=ev.summary, tool_id=ev.tool_id)

            try:
                if provider == codex_window.CODEX:
                    res = codex.run_worker(
                        prompt, ws, model=model, session_id=session, system_text=_read_text(RULES_FILE), timeout_sec=timeout,
                        add_dirs=[att_dir], log_path=att_dir / "log", on_tool=on_tool, run=self.run_id,
                    )
                else:
                    res = claude.run_worker(
                        prompt, ws, model=model, session_id=session, settings=settings, system_file=RULES_FILE,
                        timeout_sec=timeout, log_path=att_dir / "log", on_tool=on_tool,
                    )
            except LimitError as e:
                if provider == codex_window.CODEX:
                    # 같은 시도의 남은 구간은 새 Claude 세션이 plan.md와 progress.md를 읽고 이어간다
                    self.switch("run", provider, codex_window.CLAUDE, f"Codex 한도 응답: {redact(str(e))[:120]}", attempt)
                    provider, session, handover, model = codex_window.CLAUDE, None, True, claude.MODEL_WORKER
                    self.save_meta(worker_provider=provider, model=model, session=None, session_provider=provider)
                    continue
                waited = self._wait_limit(total_deadline, str(e))
                limit_waits.append(waited)
                if now() >= total_deadline:
                    outcome = {"status": "실패", "reason": "Claude 한도 대기 중 총 상한", "category": "시간 초과"}
                    break
                continue
            except AdapterError as e:
                outcome = {"status": "실패", "reason": f"작업자 호출 실패: {redact(str(e))[:300]}", "category": "프로세스 비정상"}
                break

            session = res.session_id or session
            self.save_meta(session=session, session_provider=provider)
            t1 = now()
            self.add_tokens(res.usage, res.num_turns or 1)
            seg_info = {
                "n": seg, "turns": res.num_turns, "input_tokens": res.input_tokens, "output_tokens": res.output_tokens,
                "minutes": _minutes(t0, t1), "killed": res.killed, "returncode": res.returncode, "verdict": "",
                "provider": provider,
            }
            if provider == codex_window.CODEX:
                hits = self.forbidden_writes(ws, before)
                if hits:
                    seg_info["verdict"] = "금지 경로"
                    segments.append(seg_info)
                    self.emit("segment_end", attempt=attempt, stage="run", segment=seg, **{k: v for k, v in seg_info.items() if k != "n"})
                    outcome = {"status": "확인 필요", "category": "금지 경로", "result": {
                        "status": "확인 필요", "summary": f"Codex 작업자가 금지 경로 {len(hits)}개에 썼다", "changed_files": hits,
                        "evidence": [], "commit": "", "reason": "", "rule": "등록부 경로 규칙(읽지 않음, 읽기만, 생성물) 쓰기: " + ", ".join(hits[:10]),
                        "options": ["바뀐 금지 경로를 되돌리고 다시 돌린다", "사람이 변경을 확인하고 그대로 둔다"], "added_packages": [],
                        "written_by": "jipsa"}}
                    break
            result = _read_json(att_dir / "result.json")
            if result and result.get("status") in VALID_STATUS:
                seg_info["verdict"] = "결과 보고"
                segments.append(seg_info)
                self.emit("segment_end", attempt=attempt, stage="run", segment=seg, **{k: v for k, v in seg_info.items() if k != "n"})
                outcome = {"status": result["status"], "result": result, "category": "작업자 보고"}
                break

            progress = _read_text(att_dir / "progress.md")
            if res.killed:
                no_progress += 1
                seg_info["verdict"] = "구간 상한"
            elif res.returncode not in (0, None) and not res.text:
                outcome = {"status": "실패", "reason": f"작업자 프로세스 비정상 종료 (exit {res.returncode})", "category": "프로세스 비정상"}
                segments.append(seg_info)
                break
            elif not progress:
                no_progress += 1
                seg_info["verdict"] = "메모 없음"
            else:
                verdict = self._judge(progress, prev_progress, seg)
                seg_info["verdict"] = verdict["progress"]
                seg_info["judge_reason"] = verdict["reason"]
                if verdict["progress"] == "없음":
                    no_progress += 1
                else:
                    no_progress = 0
                prev_progress = progress
            segments.append(seg_info)
            self.emit("segment_end", attempt=attempt, stage="run", segment=seg, **{k: v for k, v in seg_info.items() if k != "n"})
            self.save_meta(session=session, segments_done=len(segments))
            if no_progress >= NO_PROGRESS_LIMIT:
                outcome = {"status": "실패", "reason": f"연속 {NO_PROGRESS_LIMIT}구간 진전 없음", "category": "진전 없음"}
                break
            seg += 1

        # 작업자가 result.json을 못 썼으면 jipsa가 쓴다
        result = outcome.get("result")
        if not result:
            result = {
                "status": outcome.get("status", "실패"), "summary": outcome.get("reason", ""), "changed_files": [],
                "evidence": [], "commit": "", "reason": outcome.get("reason", ""), "rule": "", "options": [], "added_packages": [],
                "written_by": "jipsa",
            }
        # 커밋 정리. code와 experiment는 worktree에서, 모의 실행과 doc은 커밋하지 않는다.
        if p.commit and p.uses_worktree and not self.dry_run and workspace.is_repo(ws):
            if result["status"] == "완료" and not result.get("commit"):
                commits = workspace.commits_since(ws, base)
                if commits:
                    result["commit"] = commits[0].split()[0]
            if workspace.dirty_files(ws):
                tag = "시간 상한 중단, 미완성" if outcome.get("category") in ("시간 초과", "진전 없음") else "작업 종료 정리"
                h = workspace.commit_all(ws, f"[jipsa] {tag}: {self.q['title']}")
                if h:
                    result.setdefault("jipsa_commit", h)
                    if not result.get("commit"):
                        result["commit"] = h
                    self.emit("commit", attempt=attempt, stage="run", commit=h, by="jipsa", tag=tag)
        if base and workspace.is_repo(ws):
            result["changed_files"] = workspace.changed_files(ws, base) or result.get("changed_files", [])
        result["segments"] = segments
        result["limit_waits"] = limit_waits
        result["category"] = outcome.get("category", "")
        result["minutes"] = _minutes(stage_start, now())
        _write_json(att_dir / "result.json", result)
        self.emit("stage_end", attempt=attempt, stage="run", status=result["status"], minutes=result["minutes"])
        self.save_meta(session=session)
        return result

    def _judge(self, progress: str, prev: str | None, seg: int) -> dict:
        try:
            data = claude.judge_json(prompts.judge_progress(criteria=self.q["criteria"], prev=prev, cur=progress, segment=seg))
            verdict = {"progress": "없음" if str(data.get("progress", "")).strip().startswith("없") else "있음",
                       "reason": str(data.get("reason", ""))[:200]}
        except AdapterError as e:
            verdict = {"progress": "있음", "reason": f"판정 실패로 진전 있음으로 본다: {redact(str(e))[:120]}"}
        self.emit("judge", stage="run", segment=seg, progress=verdict["progress"], reason=verdict["reason"])
        return verdict

    def _wait_limit(self, total_deadline: datetime, why: str) -> str:
        """Claude 한도. 재설정 시각까지 기다린다. Auto 모드에서는 종료 시각, 유인 모드에서는 총 상한까지다."""
        start = now()
        stop_at = min(total_deadline, modes.cutoff_for()) if self.unattended else total_deadline
        self.emit("limit_wait", stage="run", provider="claude", until=stop_at.isoformat(timespec="minutes"), why=redact(why)[:200])
        self.save_meta(limit_wait=f"Claude {start:%H:%M}~")
        while now() < stop_at:
            time.sleep(min(600, max(30, int((stop_at - now()).total_seconds()))))
            try:
                claude.judge("한 단어로 답한다: 준비", timeout=60)
                break
            except LimitError:
                continue
            except AdapterError:
                break
        waited = f"Claude {start:%H:%M}~{now():%H:%M}"
        self.save_meta(limit_wait=waited)
        return waited

    # ----- analyze 단계: Sol 공격(261024-jipsa-11) -----
    def analyze_stage(self, attempt: int, ws: Path, base: str, result: dict) -> tuple[str, dict]:
        """시도마다의 분석을 마감 전 Sol 공격으로 바꿨다. 결과의 주장까지 넣고 판정, 지적, 실패면 원인을 받는다.
        Sol 호출이 한도 오류나 다른 오류로 실패하면 공격 없음을 남긴다. 실패한 시도는 재시도를 가르기 위해 옛 원인 분석만 돌린다."""
        att_dir = self.run_dir / f"attempt-{attempt}"
        self.emit("stage_start", attempt=attempt, stage="analyze")
        diff = workspace.diff_text(ws, base) if base and workspace.is_repo(ws) else "(git 저장소가 아니라 diff 없음)"
        info = {"same_provider": False, "issues": 0, "cause": "해당 없음", "error": ""}
        data = attack.run({**self.meta, "run_id": self.run_id, "title": self.q["title"], "criteria": self.q["criteria"]}, att_dir, diff=diff)
        if data["state"] == "있음":
            text = attack.as_analysis(data, result["status"])
        elif result["status"] != "실패":
            text = f"원인: 해당 없음\n\nSol 공격 없음({data.get('why')}).\n"
        else:
            text = self._cause_analysis(attempt, diff, result, info) + f"\n\nSol 공격 없음({data.get('why')}).\n"
        (att_dir / "analysis.md").write_text(text.strip() + "\n", encoding="utf-8")
        for line in text.strip().splitlines()[:3]:
            m = re.match(r"\s*원인\s*[:：]\s*(.+)", line)
            if m:
                info["cause"] = m.group(1).strip()
                break
        info["issues"] = sum(1 for line in text.splitlines() if re.match(r"\s*\d+[.)]\s", line))
        self.emit("stage_end", attempt=attempt, stage="analyze", cause=info["cause"], issues=info["issues"], same_provider=info["same_provider"])
        return text, info

    def _cause_analysis(self, attempt: int, diff: str, result: dict, info: dict) -> str:
        """Sol 공격이 없을 때 실패한 시도의 원인만 가르는 옛 분석. 작업자와 다른 공급자로 둔다."""
        prompt = prompts.analyze(project=self.project, title=self.q["title"], criteria=self.q["criteria"], result=result, diff=diff)
        worker = self.meta.get("worker_provider") or codex_window.CLAUDE
        analyst = codex_window.pick_analyst(worker)
        try:
            if analyst == codex_window.CLAUDE:
                return claude.judge(prompt, model=claude.MODEL_WORKER, timeout=600)
            return codex.ask(prompt, run=self.run_id)
        except LimitError as e:
            self.emit("limit", stage="analyze", provider=analyst, why=redact(str(e))[:200])
            if analyst == codex_window.CODEX:
                self.switch("analyze", codex_window.CODEX, codex_window.CLAUDE, "Codex 한도 응답", attempt)
            try:
                info["same_provider"] = True
                return "같은 공급자(Codex 창 한도 응답으로 Claude가 분석했다)\n" + claude.judge(prompt, model=claude.MODEL_WORKER, timeout=600)
            except AdapterError as e2:
                info["error"] = str(e2)[:200]
                return f"원인: 작업자 변경 밖\n\n분석 실패: {redact(str(e2))[:300]}"
        except AdapterError as e:
            info["error"] = str(e)[:200]
            return f"원인: 작업자 변경 밖\n\n분석 실패: {redact(str(e))[:300]}"

    # ----- reply 단계: 공격 답과 보고서 수정(261024-jipsa-11) -----
    REPLY_MIN = 15  # 수정 단계의 짧은 재확인까지 포함한 상한(분)

    def reply_stage(self, attempt: int, ws: Path, total_deadline: datetime, result: dict) -> dict:
        """끝난 시도(완료, 확인 필요)에 지적이 있으면 같은 작업자 세션을 이어 불러 지적마다 답하고 보고서를 한 번 고치게 한다.
        공방은 한 번이라 고친 뒤 다시 공격하지 않는다. 시간이 5분 안 남았거나 호출이 실패하면 답 없이 마감한다."""
        att_dir = self.run_dir / f"attempt-{attempt}"
        data = attack.load(att_dir) or {}
        if self.dry_run or data.get("state") != "있음" or not data.get("findings"):
            return result
        left = (total_deadline - now()).total_seconds()
        if left < 300:
            self.emit("attack_reply", attempt=attempt, why="총 상한까지 5분 안 남아 답 없이 마감")
            return result
        provider = self.meta.get("session_provider") or codex_window.CLAUDE
        session = self.meta.get("session")
        prompt = attack.reply_prompt({**self.meta, "run_id": self.run_id}, att_dir, subagent=False)
        timeout = int(min(self.REPLY_MIN * 60, left))
        self.emit("stage_start", attempt=attempt, stage="reply")
        before = set(workspace.dirty_files(ws)) if workspace.is_repo(ws) else set()

        def on_tool(ev):
            self.emit("tool", attempt=attempt, stage="reply", parent=ev.parent_id, tool=ev.tool, summary=ev.summary, tool_id=ev.tool_id)

        try:
            if provider == codex_window.CODEX:
                res = codex.run_worker(prompt, ws, model=self.meta.get("model") or CODEX_WORKER_MODEL, session_id=session, timeout_sec=timeout,
                                       add_dirs=[att_dir], log_path=att_dir / "log", on_tool=on_tool, run=self.run_id)
            else:
                res = claude.run_worker(prompt, ws, model=self.meta.get("model") or claude.MODEL_WORKER, session_id=session,
                                        settings=write_settings(self.project), system_file=RULES_FILE, timeout_sec=timeout,
                                        log_path=att_dir / "log", on_tool=on_tool)
            self.add_tokens(res.usage, res.num_turns or 1)
        except AdapterError as e:
            self.emit("stage_end", attempt=attempt, stage="reply", error=redact(str(e))[:200])
            return result
        new = _read_json(att_dir / "result.json") or {}
        if new.get("status") in VALID_STATUS:
            keep = {k: result[k] for k in ("segments", "limit_waits", "category", "minutes", "changed_files", "commit", "jipsa_commit") if k in result}
            result = {**result, **new, **keep}
        p = self.project
        if p.commit and p.uses_worktree and workspace.is_repo(ws) and set(workspace.dirty_files(ws)) - before:
            h = workspace.commit_all(ws, f"[jipsa] Sol 공격 반영: {self.q['title']}")
            if h:
                result["jipsa_commit"] = h
                self.emit("commit", attempt=attempt, stage="reply", commit=h, by="jipsa", tag="Sol 공격 반영")
        _write_json(att_dir / "result.json", result)
        n = len(attack.replies(att_dir))
        self.emit("stage_end", attempt=attempt, stage="reply", issues=n)
        return result

    # ----- search 단계 -----
    def search_stage(self, attempt: int, analysis: str) -> int:
        att_dir = self.run_dir / f"attempt-{attempt}"
        self.emit("stage_start", attempt=attempt, stage="search")
        sources = [(label, path) for label, path in SEARCH_SOURCES if path.exists()]
        prompt = prompts.search(project=self.project, title=self.q["title"], criteria=self.q["criteria"], analysis=analysis, sources=sources)
        from scheduler.config import CLI_CWD

        def on_tool(ev):
            self.emit("tool", attempt=attempt, stage="search", parent=ev.parent_id, tool=ev.tool, summary=ev.summary, tool_id=ev.tool_id)

        try:
            res = claude.run_worker(
                prompt, CLI_CWD, settings=SETTINGS_FILE, timeout_sec=SEARCH_TIMEOUT_SEC, skip_permissions=False,
                allowed_tools=["Read", "Grep", "Glob", "WebSearch", "WebFetch"], add_dirs=[p for _, p in sources],
                log_path=att_dir / "log", on_tool=on_tool,
            )
            text = res.text or "찾은 자료 없음"
            self.add_tokens(res.usage, res.num_turns or 1)
            if res.killed:
                text = "서칭 시간 초과\n" + text
        except AdapterError as e:
            text = f"서칭 실패: {redact(str(e))[:300]}"
        (att_dir / "search.md").write_text(text.strip() + "\n", encoding="utf-8")
        n = sum(1 for line in text.splitlines() if line.strip().startswith("- ") and "출처" in line)
        self.emit("stage_end", attempt=attempt, stage="search", sources=n)
        return n

    # ----- 전체 -----
    def run(self) -> dict:
        p, q = self.project, self.q
        start = now()
        total_minutes = q.get("est_minutes") or p.total_minutes
        continuing = bool(self.meta.get("started"))
        if not continuing:
            self.save_meta(
                run_id=self.run_id, project=p.name, title=q["title"], criteria=q["criteria"], kind=p.kind,
                started=start.isoformat(timespec="seconds"), report_date=modes.report_date(start, self.unattended),
                status="진행 중", minutes_limit=total_minutes, minutes_used=0, attempts=[], dry_run=self.dry_run,
                mode=modes.get()["mode"], executor="worker", model=claude.MODEL_WORKER, queue_key=q.get("key"),
                cycle=q.get("cycle") or "",
                **{k: q[k] for k in ("category", "pick", "category_guess", "from_run", "review_of", "revise_of", "cycle_step", "cycle_round",
                                     "todo_key", "todo_line", "limits", "auto_since", "todo_plan", "run_now") if k in q},
            )
            self.emit("run_start", project=p.name, title=q["title"], project_kind=p.kind, limit=total_minutes, dry_run=self.dry_run)
        else:
            self.save_meta(status="진행 중")
            self.emit("run_resume", project=p.name, title=q["title"], answer=bool(q.get("answer")))
        used_before = int(self.meta.get("minutes_used", 0))
        total_deadline = start + timedelta(minutes=max(10, total_minutes - used_before))
        if q.get("source") == "todo" and self.unattended:
            # Auto 줄은 마감 전에 못 끝날 일도 시작하고 마감에 끊는다. 마감 10분 안에 시작한 줄은 10분을 준다(261026-jipsa-03)
            total_deadline = min(total_deadline, max(modes.cutoff_for(), start + timedelta(minutes=10)))
        if q.get("run_cutoff"):  # 시킨 줄은 요청 마감에 끊는다. Auto 줄과 같이 10분은 준다(261026-jipsa-12)
            total_deadline = min(total_deadline, max(datetime.fromisoformat(q["run_cutoff"]), start + timedelta(minutes=10)))
        queue.update(q["key"], status=queue.RUNNING, run_id=self.run_id, started=start.isoformat(timespec="seconds"))

        try:
            prepared = self.prepare()
            if prepared is None:
                return self.finish("확인 필요", start)
            ws, branch, base = prepared
            prior_analysis = None
            answer = q.get("answer")
            attempt = len(self.meta.get("attempts", [])) + 1
            final_result: dict = {}
            while True:
                result = self.run_stage(attempt, ws, branch, base, total_deadline, prior_analysis, answer)
                answer = None
                analysis, ainfo = self.analyze_stage(attempt, ws, base, result)
                nsrc = self.search_stage(attempt, analysis)
                attempts = self.meta.get("attempts", [])
                attempts.append({"n": attempt, "status": result["status"], "category": result.get("category"), "cause": ainfo["cause"],
                                 "minutes": result.get("minutes", 0), "issues": ainfo["issues"], "sources": nsrc})
                self.save_meta(attempts=attempts, minutes_used=used_before + _minutes(start, now()),
                               analysis_issues=ainfo["issues"], search_sources=nsrc, analysis_same_provider=ainfo["same_provider"])
                final_result = result
                retry = (
                    result["status"] == "실패" and not self.dry_run
                    and (result.get("category") == "프로세스 비정상" or ainfo["cause"].startswith("작업자 변경 안"))
                    and (total_deadline - now()) >= timedelta(minutes=10)
                )
                if not retry:
                    if result["status"] in ("완료", "확인 필요"):
                        final_result = self.reply_stage(attempt, ws, total_deadline, result)
                    break
                self.emit("retry", attempt=attempt, next=attempt + 1, cause=ainfo["cause"])
                prior_analysis = analysis
                attempt += 1
            return self.finish(final_result["status"], start, final_result)
        except Exception as e:  # noqa: BLE001 - 실행기 자체 오류도 실패로 기록한다
            self.save_meta(reason=f"실행기 오류: {redact(str(e))[:300]}", summary=f"실행기 오류: {redact(str(e))[:120]}")
            self.emit("error", where="runner", error=redact(str(e))[:300])
            return self.finish("실패", start)

    def finish(self, status: str, start: datetime, result: dict | None = None) -> dict:
        result = result or {}
        from scheduler import auto  # auto가 이 모듈의 이웃을 부르므로 늦게 부른다

        status, result = auto.plan_settle(self.meta, status, result)  # 기준 정하기(기획 단계)는 늘 확인 필요다(261025-jipsa-24)
        summary = result.get("summary") or self.meta.get("summary") or result.get("reason") or self.meta.get("reason") or ""
        commit = result.get("commit") or ""
        if commit:
            evidence_ref = f"커밋 {commit}"
        elif result.get("changed_files"):
            evidence_ref = f"바뀐 파일 {len(result['changed_files'])}개"
        else:
            evidence_ref = f"runs/{self.run_id}"
        self.save_meta(
            status=status, finished=now_iso(), summary=summary[:200], evidence_ref=evidence_ref,
            minutes_used=int(self.meta.get("minutes_used", 0)) or _minutes(start, now()),
            rule=result.get("rule") or self.meta.get("rule", ""), options=result.get("options") or self.meta.get("options", []),
            added_packages=result.get("added_packages") or [], reason=result.get("reason") or self.meta.get("reason", ""),
            label=str(result.get("label") or "")[:20], preview_url=str(result.get("preview_url") or ""),
        )
        q_status = {"완료": queue.DONE, "실패": queue.FAILED, "확인 필요": queue.HOLD}.get(status, queue.FAILED)
        queue.update(self.q["key"], status=q_status, run_id=self.run_id, finished=now_iso(), reason=summary[:120], answer=None)
        unloaded = resources.release(self.run_id)
        if unloaded:
            self.emit("ollama_unload", models=unloaded)
        self.emit("run_end", status=status, minutes=self.meta.get("minutes_used", 0), evidence=evidence_ref)
        events.move_run(self.run_id)
        # 결과지, 그날 보고, 확인 필요와 실패면 Slack 요약 글. 실행 주체와 무관한 공통 마무리다.
        try:
            record.close(self.meta, notify=not self.dry_run)
        except Exception as e:  # noqa: BLE001 - 마무리 실패가 결과를 지우지 않는다
            self.emit("error", where="close", error=redact(str(e))[:200])
        return self.meta


def run_task(project: Project, qitem: dict, *, run_id: str | None = None, dry_run: bool = False) -> dict:
    run_id = run_id or qitem.get("run_id") or new_run_id(project.name)
    task = TaskRun(project, qitem, run_id=run_id, dry_run=dry_run)
    if task.meta.get("executor", "worker") in queue.SESSION_EXECUTORS:
        # 세션이 맡은 실행이다. 작업 중 저장, 작업 폴더, 작업자 호출 없이 기록을 그대로 둔다
        task.emit("session_run_skipped", executor=task.meta.get("executor"))
        resources.release(run_id)
        return task.meta
    return task.run()


_ = os  # 보존
