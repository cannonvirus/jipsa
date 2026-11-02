"""스케줄러 중복 실행 잠금과 대시보드의 스케줄러 감시(261022-jipsa-34).

잠금: 스케줄러는 시작할 때 상태 폴더의 잠금 파일에 pid, 프로세스 생성 시각, 명령줄을 적는다. 이미 잠금이 있으면
그 pid의 프로세스가 살아 있고 생성 시각과 명령줄이 같을 때만 살아 있는 스케줄러로 본다. pid는 Windows에서 금방 다시 쓰이므로
pid만으로 판단하지 않는다. 잠금이 없는 옛 스케줄러도 심장박동 파일의 pid가 스케줄러 명령줄이고 마지막 확인 전에 생겼으면 산 것으로 본다.

감시: 대시보드는 시작할 때와 WATCH_SEC마다 스케줄러가 살아 있는지 보고, 없으면 분리된 백그라운드 프로세스로 띄운다.
중간 프로세스를 한 번 거쳐 띄우므로 스케줄러의 부모가 대시보드가 아니고, 대시보드를 꺼도 스케줄러는 계속 돈다.
둘 다 숨은 콘솔로 띄운다(261022-jipsa-35). 분리 플래그를 쓰면 가상환경 python 실행기가 띄우는 실제 python이 새 콘솔 창을 만든다.
10분 안에 3번 꺼지면 다시 띄우기를 멈추고 화면에 경고와 로그 끝줄을 보인다. 심장박동만 멈춘 산 프로세스는 죽이지 않고 경고만 한다.
Monitor(저장소 루트의 python monitor.py)에서 끈 스케줄러도 멈춤으로 적어 감시가 다시 띄우지 않는다. 이 멈춤은 대시보드를 다시 켜도 남고,
Monitor나 jipsa settings start나 jipsa settings restart로 풀고, jipsa run으로 다시 켜서 스케줄러가 살아 있어도 풀린다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta

import psutil

from scheduler.config import ROOT, STATE, now, now_iso, parse_iso, redact
from scheduler.nowindow import BACKGROUND, BREAKAWAY, hidden

LOCK_FILE = STATE / "scheduler.lock"
HEARTBEAT = STATE / "scheduler.json"  # loop.HEARTBEAT와 같은 파일. loop를 불러오지 않으려고 따로 적는다
WATCH_FILE = STATE / "watchdog.json"  # 띄운 기록, 멈춤, 심장박동 멈춤 경고
LOG_FILE = STATE / "scheduler.log"  # 대시보드가 띄운 스케줄러의 출력

WATCH_SEC = int(os.environ.get("JIPSA_WATCH_SEC", "").strip() or 30)  # 감시 주기. 시험용으로 줄일 수 있다
STALL_MIN = 5  # 프로세스는 있는데 심장박동이 이만큼 멈추면 경고한다
CRASH_WINDOW_MIN = 10  # 이 시간 안에
CRASH_LIMIT = 3  # 이만큼 꺼지면 다시 띄우기를 멈춘다
STARTING_SEC = 120  # 띄운 뒤 이 시간 안에는 잠금이 아직 없어도 뜨는 중으로 본다
LOG_MAX = 1_000_000  # 로그가 이보다 크면 띄울 때 뒤쪽만 남긴다
KEEP_RECORDS = 50



def _read(path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _proc(pid) -> psutil.Process | None:
    try:
        p = psutil.Process(int(pid))
        return p if p.is_running() and p.status() != psutil.STATUS_ZOMBIE else None
    except (psutil.Error, ValueError, TypeError):
        return None


def _identity(p: psutil.Process) -> dict:
    return {"pid": p.pid, "created": p.create_time(), "cmdline": p.cmdline(),
            "started": datetime.fromtimestamp(p.create_time()).isoformat(timespec="seconds")}


def _is_scheduler_cmd(cmd: list[str]) -> bool:
    """jipsa run 또는 python -m scheduler.cli run의 명령줄인지."""
    joined = " ".join(cmd).lower()
    return "run" in cmd[1:] and ("jipsa" in joined or "scheduler.cli" in joined)


def _same(rec: dict) -> bool:
    """잠금에 적힌 프로세스가 아직 그 프로세스인지. pid 재사용을 생성 시각과 명령줄로 거른다."""
    p = _proc(rec.get("pid"))
    if not p:
        return False
    try:
        if abs(p.create_time() - float(rec.get("created") or 0)) > 1:
            return False
        return not rec.get("cmdline") or p.cmdline() == rec["cmdline"]
    except psutil.Error:
        return False


def holder(exclude: int | None = None) -> dict | None:
    """살아 있는 스케줄러. 잠금이 먼저이고, 잠금이 없는 옛 스케줄러는 심장박동 파일로 본다."""
    rec = _read(LOCK_FILE)
    if rec.get("pid") and rec["pid"] != exclude and _same(rec):
        return {**rec, "source": "잠금"}
    hb = _read(HEARTBEAT)
    if hb.get("pid") and hb["pid"] != exclude and hb.get("last_tick"):
        p = _proc(hb["pid"])
        try:
            if p and _is_scheduler_cmd(p.cmdline()) and p.create_time() <= parse_iso(hb["last_tick"]).timestamp() + 1:
                return {**_identity(p), "source": "심장박동"}
        except (psutil.Error, ValueError):
            pass
    return None


def acquire() -> dict | None:
    """잠금을 잡는다. 잡으면 None, 살아 있는 스케줄러가 있으면 그 정보를 돌려준다. 죽은 프로세스의 잠금은 넘겨받는다."""
    me = _identity(psutil.Process(os.getpid()))
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(3):
        h = holder(exclude=me["pid"])
        if h:
            return h
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            # 잠금은 있는데 주인이 죽었다. 새 파일을 만들기 전에 지운다. 동시에 둘이 넘겨받으면 아래 다시 읽기에서 한쪽이 진다
            try:
                LOCK_FILE.unlink()
            except OSError:
                pass
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(me, f, ensure_ascii=False)
        if _read(LOCK_FILE).get("pid") == me["pid"]:
            return None
    h = holder(exclude=me["pid"])
    return h or {"pid": None, "started": "", "source": "잠금 파일을 만들지 못함"}


def release() -> None:
    rec = _read(LOCK_FILE)
    if rec.get("pid") == os.getpid():
        try:
            LOCK_FILE.unlink()
        except OSError:
            pass


def status() -> dict:
    """스케줄러가 살아 있는지와 심장박동 나이. 화면과 감시가 같이 쓴다."""
    h = holder()
    hb = _read(HEARTBEAT)
    age = None
    if hb.get("last_tick"):
        try:
            age = int((now() - parse_iso(hb["last_tick"])).total_seconds())
        except ValueError:
            age = None
    alive = bool(h)
    return {"alive": alive, "pid": (h or {}).get("pid"), "source": (h or {}).get("source"), "started": (h or {}).get("started"),
            "last_tick": hb.get("last_tick"), "hb_age": age, "concurrency": hb.get("concurrency"),
            "stalled": bool(alive and (age is None or age > STALL_MIN * 60))}


# ----- 띄우기 -----
def _popen_detached(cmd: list[str], stdout) -> subprocess.Popen:
    # 감시가 띄우는 스케줄러는 운영으로 도는 것이 맞다. 에이전트 셸에서 띄운 대시보드여도 운영 폴더 보호(config.live_guard)에 막히지 않게 한다
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "JIPSA_LIVE": "1"}
    kw = dict(cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=stdout, stderr=subprocess.STDOUT if stdout is not subprocess.PIPE else subprocess.DEVNULL,
              env=env, close_fds=True)
    if os.name != "nt":
        return subprocess.Popen(cmd, start_new_session=True, **kw)
    try:
        return subprocess.Popen(cmd, **hidden(BACKGROUND | BREAKAWAY), **kw)
    except OSError:  # 작업 개체가 떨어져 나가기를 막으면 그 플래그 없이 띄운다
        return subprocess.Popen(cmd, **hidden(BACKGROUND), **kw)


def _trim_log() -> None:
    try:
        if LOG_FILE.stat().st_size > LOG_MAX:
            LOG_FILE.write_bytes(LOG_FILE.read_bytes()[-LOG_MAX // 2:])
    except OSError:
        pass


def launch() -> int:
    """중간 프로세스에서 돈다. 스케줄러를 분리해 띄우고 그 pid를 찍고 바로 끝난다. 그래서 스케줄러의 부모는 대시보드가 아니다."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _trim_log()
    with LOG_FILE.open("ab") as log:
        log.write(f"\n===== {now_iso()} 대시보드 감시가 스케줄러를 띄움 =====\n".encode("utf-8"))
        log.flush()
        p = _popen_detached([sys.executable, "-m", "scheduler.cli", "run"], log)
    print(p.pid, flush=True)
    return 0


def spawn() -> int | None:
    """스케줄러를 띄우고 pid를 돌려준다. 중복은 스케줄러 쪽 잠금이 막는다."""
    mid = _popen_detached([sys.executable, "-m", "scheduler.supervise", "launch"], subprocess.PIPE)
    try:
        out, _ = mid.communicate(timeout=30)
        return int(out.decode().strip().splitlines()[-1])
    except (subprocess.TimeoutExpired, ValueError, IndexError):
        return None


def log_tail(lines: int = 8) -> list[str]:
    try:
        with LOG_FILE.open("rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 8000))
            text = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    rows = [redact(r.rstrip()) for r in text.splitlines() if r.strip()]
    return rows[-lines:]


# ----- 감시 -----
_watch = {"thread": None, "stop": threading.Event()}


def _load() -> dict:
    d = _read(WATCH_FILE)
    d.setdefault("launches", [])
    return d


def _save(d: dict) -> None:
    d["launches"] = d["launches"][-KEEP_RECORDS:]
    try:
        WATCH_FILE.parent.mkdir(parents=True, exist_ok=True)
        WATCH_FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _notify(text: str) -> str:
    from notify import slack

    return slack.notify(f"[jipsa] {text}")


def check(first: bool = False) -> dict:
    """한 번 확인한다. 살아 있으면 심장박동만 보고, 없으면 띄운다. 짧은 시간에 반복해서 꺼지면 멈춘다."""
    from scheduler import events

    d = _load()
    if first and d.get("stopped") and not d["stopped"].get("by"):
        events.emit("scheduler_watch_resume", why="대시보드를 다시 켬")
        d["stopped"] = None
    st = status()
    last = d["launches"][-1] if d["launches"] else None
    if st["alive"]:
        if d.get("stopped") and d["stopped"].get("pid") != st["pid"]:  # 사람이 손으로 켰다. 감시를 다시 돌린다. 지금 끄는 중인 그 프로세스면 풀지 않는다
            events.emit("scheduler_watch_resume", why="스케줄러가 다시 살아 있음", pid=st["pid"])
            d["stopped"] = None
        if st["stalled"] and not d.get("stall"):
            d["stall"] = {"at": now_iso(), "pid": st["pid"], "last_tick": st["last_tick"]}
            mins = (st["hb_age"] or 0) // 60
            out = _notify(f"스케줄러 심장박동이 {mins}분째 멈췄다. 프로세스는 살아 있어 죽이지 않았다")
            events.emit("scheduler_stall", pid=st["pid"], last_tick=st["last_tick"], minutes=mins, slack=out)
        elif not st["stalled"] and d.get("stall"):
            events.emit("scheduler_stall_clear", pid=st["pid"])
            d["stall"] = None
        _save(d)
        return d
    d["stall"] = None
    if last and last.get("pid") and _proc(last["pid"]) and (now() - parse_iso(last["at"])).total_seconds() < STARTING_SEC:
        _save(d)  # 방금 띄운 것이 아직 잠금을 잡기 전이다
        return d
    if d.get("stopped"):
        _save(d)
        return d
    since = now() - timedelta(minutes=CRASH_WINDOW_MIN)
    recent = [r for r in d["launches"] if parse_iso(r["at"]) >= since]
    hb = _read(HEARTBEAT)
    if first:
        kind = "시작"
        why = "대시보드 시작 때 스케줄러 없음" + (f", 마지막 확인 {hb['last_tick'][11:16]}에서 끊김" if hb.get("last_tick") else "")
    else:
        kind = "재기동"
        why = f"프로세스 없음, 마지막 확인 {hb['last_tick'][11:16]}에서 끊김" if hb.get("last_tick") else "프로세스 없음, 정상 종료 기록"
    if not first and len(recent) >= CRASH_LIMIT:
        tail = log_tail()
        d["stopped"] = {"at": now_iso(), "count": len(recent), "window": CRASH_WINDOW_MIN, "log": tail, "why": why}
        out = _notify(f"스케줄러가 {CRASH_WINDOW_MIN}분 안에 {len(recent)}번 꺼져 다시 띄우기를 멈췄다. 대시보드 환경 칸에 마지막 로그가 있다")
        events.emit("scheduler_watch_stop", count=len(recent), window=CRASH_WINDOW_MIN, why=why, slack=out)
        _save(d)
        return d
    today = now().date().isoformat()
    n = sum(1 for r in d["launches"] if r.get("kind") == "재기동" and r["at"].startswith(today)) + 1
    pid = spawn()
    rec = {"at": now_iso(), "kind": kind, "why": why, "pid": pid}
    if kind == "재기동":
        rec["n"] = n
        rec["slack"] = _notify(f"스케줄러가 꺼져 다시 띄웠다. 오늘 {n}번째. {why}")
    d["launches"].append(rec)
    events.emit("scheduler_restart" if kind == "재기동" else "scheduler_spawn", pid=pid, why=why, n=rec.get("n"), slack=rec.get("slack"))
    _save(d)
    return d


def hold(by: str, pid: int | None = None) -> None:
    """사람이 끈 스케줄러를 감시가 다시 띄우지 않게 멈춤을 적는다."""
    d = _load()
    d["stopped"] = {"at": now_iso(), "by": by, "why": f"{by}에서 끔", **({"pid": pid} if pid else {})}
    _save(d)


def unhold() -> None:
    d = _load()
    if d.get("stopped"):
        d["stopped"] = None
        _save(d)


def stop_scheduler(by: str = "jipsa settings stop", force: bool = False) -> dict:
    """스케줄러를 끄고 멈춤을 적어 감시가 다시 띄우지 않게 한다. 실행 중 작업이 있으면 force 없이는 거절한다.
    force는 그 작업 프로세스까지 끊고, 끊긴 줄은 다음 시작 때 큐가 대기로 되돌린다. 세션 서브에이전트 작업은 스케줄러 밖이라 끊지 않는다."""
    h = holder()
    running = int(_read(HEARTBEAT).get("running") or 0) if h else 0
    if running and not force:
        return {"ok": False, "running": running, "why": f"실행 중 작업이 {running}개 있다. 끝나기를 기다리거나 --force를 준다. --force는 그 작업을 끊는다"}
    hold(by, pid=h["pid"] if h else None)  # 끄는 사이 감시가 다시 띄우지 않게 먼저 적는다
    if not h:
        return {"ok": True, "running": 0, "text": "스케줄러는 떠 있지 않다. 감시가 다시 띄우지 않게 멈춤을 적었다"}
    p = _proc(h["pid"])
    procs = []
    if p:
        try:
            procs = [p, *p.children(recursive=True)]
        except psutil.Error:
            procs = [p]
    for q in procs:
        try:
            q.terminate()
        except psutil.Error:
            pass
    left = [q.pid for q in psutil.wait_procs(procs, timeout=8)[1]]
    hold(by, pid=h["pid"])  # 끄는 사이 감시의 저장이 멈춤을 덮었을 수 있다
    if left:
        return {"ok": False, "running": running, "why": f"끄지 못한 프로세스가 남았다(pid {left}). 멈춤은 적어 두었다"}
    for f in (HEARTBEAT, LOCK_FILE):  # 강제 종료라 스케줄러가 스스로 지우지 못한다
        try:
            f.unlink()
        except OSError:
            pass
    return {"ok": True, "running": running, "text": f"스케줄러를 껐다(pid {h['pid']})" + (f". 실행 중 작업 {running}개를 끊었다" if running else "") + ". 다시 켜는 명령은 jipsa settings start다"}


def start_scheduler(wait_sec: int = 20) -> dict:
    """멈춤을 풀고 스케줄러를 띄운다. 이미 떠 있으면 멈춤만 푼다."""
    import time

    unhold()
    h = holder()
    if h:
        return {"ok": True, "text": f"스케줄러는 이미 떠 있다(pid {h['pid']})"}
    pid = spawn()
    end = time.monotonic() + wait_sec
    while time.monotonic() < end:
        h = holder()
        if h:
            return {"ok": True, "text": f"스케줄러를 켰다(pid {h['pid']})"}
        time.sleep(0.5)
    return {"ok": False, "why": f"{wait_sec}초 안에 잠금을 잡지 못했다(띄운 pid {pid}). 상태 폴더 scheduler.log를 본다"}


def _loop() -> None:
    from scheduler import events

    first = True
    while not _watch["stop"].is_set():
        try:
            check(first=first)
        except Exception as e:  # noqa: BLE001 - 감시의 오류로 대시보드를 죽이지 않는다
            events.emit("error", where="scheduler_watch", error=str(e)[:300])
        first = False
        _watch["stop"].wait(WATCH_SEC)


def start_watch() -> None:
    if _watch["thread"] and _watch["thread"].is_alive():
        return
    t = threading.Thread(target=_loop, name="scheduler-watch", daemon=True)
    _watch["thread"] = t
    t.start()


def watching() -> bool:
    return bool(_watch["thread"] and _watch["thread"].is_alive())


def view() -> dict:
    """화면의 환경 칸. 최근 24시간 띄운 기록, 오늘 재기동 횟수, 멈춤과 심장박동 멈춤 경고."""
    d = _load()
    since = now() - timedelta(hours=24)
    recent = [r for r in d["launches"] if parse_iso(r["at"]) >= since]
    today = now().date().isoformat()
    return {"watching": watching(), "interval": WATCH_SEC, "recent": recent[-5:],
            "restarts_today": sum(1 for r in d["launches"] if r.get("kind") == "재기동" and r["at"].startswith(today)),
            "stopped": d.get("stopped"), "stall": d.get("stall")}


if __name__ == "__main__":
    if sys.argv[1:] == ["launch"]:
        sys.exit(launch())
    sys.exit(f"알 수 없는 인자: {sys.argv[1:]}")
