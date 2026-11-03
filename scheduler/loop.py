"""스케줄러 루프. 큐를 돌보고 작업을 동시에 3개까지 띄운다.

컴퓨터가 켜져 있는 동안 늘 돈다. 모드는 없다(261029-jipsa-17에서 Auto 모드를 뗐다). 대기 줄은 사람이 답을 넣어 이어 돌리는 줄만
시작한다. 할 일을 넣어도 돌지 않게 하려는 것이다(261025-jipsa-14).
시키기(261026-jipsa-12): 할 일 줄을 시킨 요청이 있으면 요청마다 그 줄을 돌린다(auto.run_turn). Cycle은 시킬 때 정한 시작과 마감 사이에 돈다.
동시 실행(261026-jipsa-26): 일회성 줄은 개수로 막지 않고, Cycle 단계와 기준 정하기는 합쳐 AUTO_CAP(6)개까지다. 사용 창 비율로는 멈추지 않는다(261102-jipsa-50).
2초마다 요청 목록, 할 일 파일, 모드 파일이 바뀌었거나
끝난 작업자가 있는지 보고, 있으면 30초 주기를 기다리지 않고 한 바퀴를 돈다. 주기마다 GPU와 RAM 실측과 장부를 맞추고(resources.reconcile,
resources.reconcile_ram), 세션이 받지 않은 Do 요청을 작업자로 넘기며(auto.do_fallback), 아침 시각이 지나면 밤 사이 끝난 Cycle 모음 글을
하루 한 번 보낸다(auto.morning_digest).
작업마다 보내는 Slack 요약 글(확인 필요와 실패만)과 결과지는 실행기가 기록 계층(record.close)으로 처리하므로 여기서는 보내지 않는다.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import timedelta

from scheduler import auto, events, modes, queue, record, resources, runner, runsclean, supervise, todo
from scheduler.config import CONCURRENCY, RESOURCE_WAIT_MAX_MIN, STATE, TICK_SEC, WAKE_SEC, ensure_dirs, now, now_iso, parse_iso
from scheduler.registry import load_all

HEARTBEAT = STATE / "scheduler.json"  # 화면이 스케줄러가 켜져 있는지 보는 파일
SESSION_HOLD = queue.SESSION_HOLD
MANUAL_HOLD = "시킨 줄이 아니라 시작하지 않는다"
LANE_HOLD = "시킨 요청이 없어 기다린다. 그 줄을 다시 시키면 잇는다"


def manual_startable(item: dict) -> bool:
    """Manual 모드에서 시작할 대기 줄인지. 사람이 결과지에 답을 넣어 이어 돌리는 작업자 실행만 시작한다."""
    return bool(str(item.get("answer") or "").strip())


class Scheduler:
    def __init__(self, concurrency: int = CONCURRENCY):
        self.concurrency = concurrency
        self.registry = load_all()
        self.threads: dict[str, threading.Thread] = {}
        self.results: dict[str, dict] = {}
        self.wait_since: dict[str, str] = {}
        self.stop = threading.Event()
        self._run_last = ""  # 같은 시키기 대기 사건을 주기마다 되풀이해 남기지 않는다

    # ----- 보조 -----
    def _reap(self) -> list[dict]:
        done = []
        for key, t in list(self.threads.items()):
            if not t.is_alive():
                t.join(timeout=1)
                self.threads.pop(key, None)
                meta = self.results.pop(key, None)
                if meta:
                    done.append((key, meta))
        finished = []
        for key, meta in done:
            self._after_task(key, meta)
            finished.append(meta)
        return finished

    def _after_task(self, key: str, meta: dict) -> None:
        # 결과지, 보고, Slack 요약 글은 실행기의 record.close가 이미 했다. 여기서는 스레드 정리만 남긴다.
        events.emit("task_reaped", run=meta.get("run_id"), status=meta.get("status"))

    def _start(self, item: dict, project=None) -> None:
        project = project or self.registry[item["project"]]  # 시킨 줄은 한도 칸 VRAM과 RAM을 반영한 프로젝트를 받는다
        run_id = item.get("run_id") or runner.new_run_id(project.name)
        est = item.get("est_minutes") or project.total_minutes
        owner = item.get("todo_key") or "" if item.get("cycle") else ""  # Cycle 단계면 목표 key. 단계 사이 예약을 이 목표 몫으로 남긴다
        # 장부 줄은 먼저 스케줄러 번호로 적고, 어댑터가 작업자를 띄우면 그 번호로 바꾼다(resources.spawned). GPU가 필요 없으면 감시 줄이다
        resources.acquire(project, run_id, os.getpid(), est, owner=owner, check=False)
        events.emit("lease_acquire", run=run_id, project=project.name, gpu=project.needs_gpu)
        key = item["key"]

        def work():
            resources.bind(run_id)
            self.results[key] = runner.run_task(project, item, run_id=run_id)

        t = threading.Thread(target=work, name=run_id, daemon=True)
        self.threads[key] = t
        t.start()
        self.wait_since.pop(key, None)

    def _reload_registry(self) -> None:
        """주기마다 등록부를 다시 읽는다. 스케줄러가 켜진 뒤 등록한 프로젝트도 다음 주기부터 돈다. 읽지 못하면 앞 값을 쓴다."""
        try:
            fresh = load_all()
        except Exception as e:  # noqa: BLE001 - 고치던 중인 등록부 한 파일로 루프를 멈추지 않는다
            events.emit("error", where="registry_reload", error=str(e)[:300])
            return
        if set(fresh) != set(self.registry):
            events.emit("registry_reload", added=sorted(set(fresh) - set(self.registry)), removed=sorted(set(self.registry) - set(fresh)))
        self.registry = fresh

    def _session_hold(self, project) -> str:
        """원본 폴더에서 도는 doc 프로젝트에 세션이나 서브에이전트 실행이 진행 중이면 그 실행ID를 돌려준다. 같은 폴더를 쓰는 등록부도 같이 본다."""
        if project.uses_worktree:
            return ""
        for r in queue.running():
            other = self.registry.get(r.get("project") or "")
            if other and not other.uses_worktree and other.path == project.path and queue.session_owned(r):
                return r.get("run_id") or r["key"]
        return ""

    def _skip(self, item: dict, reason: str) -> None:
        queue.update(item["key"], status=queue.SKIPPED, reason=reason, finished=now().isoformat(timespec="seconds"))
        events.emit("queue_skip", project=item["project"], title=item["title"], reason=reason)

    def _run_step(self) -> None:
        """시키기 한 주기(auto.run_turn). 요청마다 그 줄을 동시 상한과 자원 규칙으로 돌린다. 일회성 줄은 개수로 막지 않는다(261026-jipsa-26)."""
        sigs = []
        for req in auto.run_requests():
            try:
                res = auto.run_turn(self.registry, self._start, req, active=set(self.threads))
            except Exception as e:  # noqa: BLE001 - 시키기 오류로 큐를 멈추지 않는다
                events.emit("error", where="run_turn", key=req.get("key"), error=str(e)[:300])
                continue
            if res and res["state"] == "wait":
                sig = f"{req['key']}|{res['state']}|{res.get('why', '')}"
                sigs.append(sig)
                if sig not in self._run_last:
                    events.emit("run_now_wait", key=res.get("key") or req["key"], why=res.get("why"))
        self._run_last = "\n".join(sigs)

    # ----- 한 바퀴 -----
    def tick(self) -> None:
        try:
            HEARTBEAT.write_text(json.dumps({"pid": os.getpid(), "last_tick": now_iso(), "concurrency": self.concurrency, "running": len(self.threads)}), encoding="utf-8")
        except OSError:
            pass
        self._reload_registry()
        for gone in resources.expire():
            events.emit("lease_expire", run=gone.get("run"))
        # 결과 없이 상한을 넘긴 세션 실행을 닫는다. 남겨 두면 원본 폴더 작업이 세션 실행 대기로 계속 밀린다
        record.expire_stale_sessions()
        # 활동이 끊긴 세션 서브에이전트를 찾아 띄운 세션의 wait-answer로 알린다. Main이 메시지를 보내야 깨어난다
        try:
            record.watch_stalls()
        except Exception as e:  # noqa: BLE001 - 감시 오류로 큐를 멈추지 않는다
            events.emit("error", where="watch_stalls", error=str(e)[:300])
        self._reap()
        try:
            for r in resources.reconcile():  # 실측이 장부보다 크면 장부를 올리고 새 GPU 작업을 멈춘다. 강제로 끄지 않는다
                # 관찰 시간이 지나 GPU 예약을 실측 + 1GB로 고친 줄은 gpu_measured다(261029-jipsa-07)
                events.emit("gpu_over" if r["kind"] == "over" else "gpu_measured", run=r["run"], project=r["project"], was=r["was"], now=r["now"],
                            **({} if r["kind"] == "over" else {"by": r["kind"]}))
        except Exception as e:  # noqa: BLE001 - 장부 오류로 큐를 멈추지 않는다
            events.emit("error", where="reconcile", error=str(e)[:300])
        try:
            for r in resources.reconcile_ram():  # 시작 관찰이 끝난 줄의 RAM 몫을 실측 최댓값 + 여유로 고친다(261029-jipsa-17)
                events.emit("ram_measured", run=r["run"], project=r["project"], was=r["was"], now=r["now"], by=r["kind"])
        except Exception as e:  # noqa: BLE001
            events.emit("error", where="reconcile_ram", error=str(e)[:300])
        try:
            auto.morning_digest()  # 밤 사이 끝난 Cycle 모음 글. 하루 한 번이고 모을 것이 없으면 보내지 않는다
        except Exception as e:  # noqa: BLE001
            events.emit("error", where="morning_digest", error=str(e)[:300])
        try:
            auto.do_fallback()  # 세션이 2분 안에 받지 않은 Do 요청은 작업자로 넘긴다
        except Exception as e:  # noqa: BLE001
            events.emit("error", where="do_fallback", error=str(e)[:300])
        try:
            # runs 중간 산출물 정리. JIPSA_RUNS_CLEAN_ON=1일 때만 하루 한 번 휴지통 폴더로 옮긴다. 기본은 꺼짐이다(261028-jipsa-10)
            done = runsclean.maybe_auto()
            if done:
                events.emit("runs_clean", moved=done["moved"], bytes=done["bytes"], trash=done["trash"])
        except Exception as e:  # noqa: BLE001 - 정리 오류로 큐를 멈추지 않는다
            events.emit("error", where="runs_clean", error=str(e)[:300])

        asked = bool(auto.run_requests())
        if asked:
            self._run_step()

        cutoff = None  # 시킨 줄 밖의 줄은 사람이 답을 넣은 줄뿐이라 마감으로 막지 않는다. 시킨 줄의 마감은 auto.run_turn이 본다
        lane = {r["key"] for r in queue.load() if r.get("source") == auto.SOURCE}
        for item in queue.pending():
            if sum(1 for k in self.threads if k not in lane) >= self.concurrency:
                break  # 답을 넣어 잇는 줄만 3개까지다. 시킨 줄은 auto.step이 따로 센다(261026-jipsa-26)
            if item["key"] in self.threads:
                continue
            if item.get("source") == auto.SOURCE:
                # 할 일 파일에서 꺼낸 줄은 auto.run_turn이 시작한다. 요청이 없는 줄(옛 Auto 줄, 마감으로 멈춘 Cycle 단계)은 다시 시킬 때까지 기다린다
                if not item.get("run_now") and item.get("reason") != LANE_HOLD and not str(item.get("reason") or "").startswith("마감으로 멈춘"):
                    queue.update(item["key"], reason=LANE_HOLD)
                continue
            if not manual_startable(item):
                hold = MANUAL_HOLD
                if item.get("reason") != hold:
                    queue.update(item["key"], reason=hold)
                continue
            state, why = queue.check_after(item)
            if state == "skip":
                self._skip(item, why)
                continue
            if state == "wait":
                self.wait_since.pop(item["key"], None)  # 선행 대기는 자원 대기 상한에 세지 않는다
                if item.get("reason") != why:
                    queue.update(item["key"], reason=why)
                continue
            project = self.registry.get(item["project"])
            if not project:
                self._skip(item, "등록부에 없는 프로젝트")
                continue
            if project.manual_only:
                self._skip(item, "세션 전용 등록부라 자동으로 돌리지 않는다")
                continue
            est = item.get("est_minutes") or project.total_minutes
            if cutoff and now() + timedelta(minutes=est) > cutoff:
                self._skip(item, f"{cutoff:%H:%M} 초과 미시작(예상 {est}분)")
                continue
            held = self._session_hold(project) or auto.folder_hold(project, self.registry, set(self.threads))
            if held:
                # 작업 중 저장이 세션이 고치던 파일을 묶지 않게 저장과 시작을 미루고 다음 주기에 다시 본다(261023-jipsa-03 1안)
                self.wait_since.pop(item["key"], None)
                why = f"{SESSION_HOLD}: {held}"
                if item.get("reason") != why:
                    queue.update(item["key"], reason=why)
                    events.emit("defer_session", project=item["project"], title=item["title"], run=held)
                continue
            ok, why = resources.can_acquire(project, key=item["key"], kind="answer", title=item.get("title") or "")
            if not ok:
                since = self.wait_since.setdefault(item["key"], now().isoformat(timespec="seconds"))
                waited = now() - parse_iso(since)
                if waited >= timedelta(minutes=RESOURCE_WAIT_MAX_MIN):
                    self._skip(item, f"자원 {RESOURCE_WAIT_MAX_MIN}분 대기 초과: {why}")
                    self.wait_since.pop(item["key"], None)
                else:
                    queue.update(item["key"], wait_since=since, reason=f"자원 대기: {why}")
                    events.emit("wait_resource", project=item["project"], title=item["title"], why=why, minutes=int(waited.total_seconds() // 60))
                continue
            self._start(item)

    def _marks(self) -> tuple:
        """바뀌면 바로 한 바퀴를 돌 표시. 요청 목록, 할 일 파일, 모드 파일의 수정 시각과 끝난 작업자 스레드 수다."""
        out = []
        for path in (auto.RUN_FILE, todo.TODO_FILE, modes.MODE_FILE, record.INBOX):
            try:
                out.append(path.stat().st_mtime_ns)
            except OSError:
                out.append(0)
        out.append(sum(1 for t in self.threads.values() if not t.is_alive()))
        return tuple(out)

    def _sleep(self) -> None:
        """30초 주기를 쉬되 2초마다 표시를 보고, 바뀌었으면 바로 깬다(261026-jipsa-26)."""
        base = self._marks()
        waited = 0.0
        while waited < TICK_SEC and not self.stop.is_set():
            if self.stop.wait(WAKE_SEC):
                return
            waited += WAKE_SEC
            if self._marks() != base:
                return

    def run_forever(self) -> dict | None:
        """잠금을 잡고 돈다. 이미 살아 있는 스케줄러가 있으면 큐를 건드리지 않고 그 정보를 돌려준다."""
        ensure_dirs()
        other = supervise.acquire()
        if other:
            events.emit("scheduler_refused", pid=os.getpid(), holder=other.get("pid"), source=other.get("source"))
            return other
        n = queue.reset_running()
        events.emit("scheduler_start", pid=os.getpid(), reset=n, projects=len(self.registry), concurrency=self.concurrency)
        try:
            while not self.stop.is_set():
                try:
                    self.tick()
                except Exception as e:  # noqa: BLE001 - 한 바퀴의 오류로 루프를 죽이지 않는다
                    events.emit("error", where="tick", error=str(e)[:300])
                self._sleep()
        finally:
            events.emit("scheduler_stop", running=len(self.threads))
            try:
                HEARTBEAT.unlink()
            except OSError:
                pass
            supervise.release()
        return None
