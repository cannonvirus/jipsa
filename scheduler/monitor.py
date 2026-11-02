"""jipsa 서비스를 켜고 끄고 로그를 보는 Monitor의 제어 부분(261024-jipsa-22, 23).

화면은 저장소 루트의 monitor.py(콘솔 메뉴)이고, 이 모듈은 상태, 켜기와 끄기, 로그 끝을 돌려준다.
서비스 목록은 scheduler/services.toml 한 곳에 둔다. 서비스는 창 없는 분리 프로세스로 띄우므로 Monitor를 꺼도 계속 돈다.

- 스케줄러: 잠금(supervise.holder)으로 살아 있는지 보고, 대시보드 감시와 같은 방법(supervise.spawn)으로 띄운다.
  끌 때는 감시 기록에 멈춤을 적어 대시보드 감시가 다시 띄우지 않게 한다. 다시 켜면 멈춤이 풀린다.
- 대시보드: 포트를 듣는 jipsa web 프로세스를 본다. 띄운 대시보드는 지금처럼 스케줄러가 없으면 스케줄러를 띄운다.
- 묶음: services.toml의 group이 같은 서비스(스케줄러와 대시보드)는 하나의 단축키로 함께 끄고, 켜고, 다시 켠다(261103-jipsa-02).
  끌 때는 `jipsa settings stop`과 같은 함수(supervise.stop_scheduler)로 스케줄러를 먼저 끄고 멈춤을 적은 뒤 대시보드를 끄며,
  실행 중 작업이 있으면 force 없이는 거절한다. 켤 때는 멈춤을 풀고 스케줄러, 대시보드 순으로 띄운다.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import tomllib
import urllib.request
from datetime import datetime
from pathlib import Path

import psutil

from scheduler import supervise
from scheduler.config import ROOT, STATE, redact
from scheduler.nowindow import BACKGROUND, BREAKAWAY, hidden

SERVICES_FILE = Path(os.environ.get("JIPSA_SERVICES", "").strip() or Path(__file__).with_name("services.toml"))
LOG_DIR = STATE / "monitor"
DASH_LOG = LOG_DIR / "dashboard.log"
LOG_LINES = 300  # 로그 칸이 기본으로 보이는 끝줄 수
LOG_MAX = 1_000_000  # 띄울 때 로그가 이보다 크면 뒤쪽만 남긴다


def _read() -> dict:
    with open(SERVICES_FILE, "rb") as f:
        return tomllib.load(f)


def services() -> list[dict]:
    return _read().get("service", [])


def _find(name: str) -> dict:
    for s in services():
        if s.get("name") == name:
            return s
    raise KeyError(name)


# ----- 프로세스 -----
def _proc(pid) -> psutil.Process | None:
    try:
        p = psutil.Process(int(pid))
        return p if p.is_running() and p.status() != psutil.STATUS_ZOMBIE else None
    except (psutil.Error, ValueError, TypeError):
        return None


def _listener(port: int) -> psutil.Process | None:
    try:
        for c in psutil.net_connections(kind="tcp"):
            if c.status == psutil.CONN_LISTEN and c.laddr.port == port and c.pid:
                return psutil.Process(c.pid)
    except (psutil.Error, OSError):
        pass
    return None


def _kill(pids: list[int]) -> list[int]:
    """프로세스와 그 자식을 끈다. 끄지 못하고 남은 pid를 돌려준다."""
    procs = []
    for pid in pids:
        p = _proc(pid)
        if p:
            try:
                procs += [p, *p.children(recursive=True)]
            except psutil.Error:
                procs.append(p)
    procs = list({p.pid: p for p in procs}.values())
    for p in procs:
        try:
            p.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(procs, timeout=5)
    for p in alive:
        try:
            p.kill()
        except psutil.Error:
            pass
    return [p.pid for p in procs if p.is_running() and p.status() != psutil.STATUS_ZOMBIE]


def _popen(cmd: list[str], log: Path, cwd: Path) -> subprocess.Popen:
    """창 없는 분리 프로세스. 새 프로세스 그룹이고 Monitor의 작업 개체에서 떨어져 나가 Monitor를 꺼도 남는다."""
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        if log.stat().st_size > LOG_MAX:
            log.write_bytes(log.read_bytes()[-LOG_MAX // 2:])
    except OSError:
        pass
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    with log.open("ab") as f:
        f.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} Monitor가 띄움 =====\n".encode("utf-8"))
        f.flush()
        kw = dict(cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT, env=env, close_fds=True)
        if os.name != "nt":
            return subprocess.Popen(cmd, start_new_session=True, **kw)
        try:
            return subprocess.Popen(cmd, **hidden(BACKGROUND | BREAKAWAY), **kw)
        except OSError:  # 작업 개체가 떨어져 나가기를 막으면 그 플래그 없이 띄운다
            return subprocess.Popen(cmd, **hidden(BACKGROUND), **kw)


def _wait_until(check, sec: float) -> bool:
    deadline = time.monotonic() + sec
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.3)
    return False


def _responds(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


# ----- 스케줄러 -----
def _sched_info(s: dict) -> dict:
    st = supervise.status()
    p = _proc(st["pid"]) if st["alive"] else None
    hb = supervise._read(supervise.HEARTBEAT)
    note = []
    if st["stalled"]:
        note.append(f"심장박동 {int((st['hb_age'] or 0) // 60)}분 멈춤")
    if p and hb.get("running"):
        note.append(f"실행 중 작업 {hb['running']}개")
    stopped = supervise.view().get("stopped")
    if not p and stopped:
        note.append(stopped.get("why") or "다시 띄우기 멈춤")
    return {"up": bool(p), "pids": [p.pid] if p else [], "port": None, "created": p.create_time() if p else None,
            "note": ", ".join(note), "running": int(hb.get("running") or 0) if p else 0, "log": supervise.LOG_FILE}


def _sched_start(s: dict) -> str:
    if supervise.holder():
        return "이미 떠 있다"
    supervise.unhold()
    pid = supervise.spawn()
    if _wait_until(lambda: supervise.holder() is not None, 20):
        return f"켰다(pid {supervise.holder()['pid']})"
    return f"잠금을 잡지 못했다(띄운 pid {pid}). 로그를 본다"


def _sched_stop(s: dict) -> str:
    h = supervise.holder()
    supervise.hold("Monitor")  # 끄는 사이 대시보드 감시가 다시 띄우지 않게 먼저 적는다
    if not h:
        return "떠 있지 않다. 감시가 다시 띄우지 않게 멈춤을 적었다"
    left = _kill([h["pid"]])
    supervise.hold("Monitor")  # 끄는 사이 감시가 살아 있는 것을 보고 멈춤을 지웠을 수 있다
    return f"끄지 못한 프로세스가 남았다(pid {left})" if left else f"껐다(pid {h['pid']})"


# ----- 대시보드 -----
def _is_dashboard(p: psutil.Process) -> bool:
    try:
        cmd = [a.lower() for a in p.cmdline()]
    except (psutil.Error, OSError):
        return False
    joined = " ".join(cmd)
    return "web" in cmd and ("jipsa" in joined or "scheduler.cli" in joined)


def _dash_info(s: dict) -> dict:
    port = int(s.get("port", 8765))
    p = _listener(port)
    ours = bool(p and _is_dashboard(p))
    return {"up": ours, "pids": [p.pid] if ours else [], "port": port, "created": p.create_time() if ours else None,
            "note": "다른 프로그램이 포트를 쓴다" if p and not ours else "", "log": DASH_LOG}


def _dash_start(s: dict) -> str:
    port = int(s.get("port", 8765))
    p = _listener(port)
    if p:
        return "이미 떠 있다" if _is_dashboard(p) else f"{port} 포트를 다른 프로그램이 쓴다(pid {p.pid}). 띄우지 않는다"
    proc = _popen([sys.executable, "-m", "scheduler.cli", "web", "--no-open", "--port", str(port)], DASH_LOG, ROOT)
    if _wait_until(lambda: _responds(port) or proc.poll() is not None, 20) and _responds(port):
        return f"켰다(포트 {port})"
    return "응답하지 않는다. 로그를 본다"


def _dash_stop(s: dict) -> str:
    info = _dash_info(s)
    if not info["up"]:
        return "떠 있지 않다"
    left = _kill(info["pids"])
    return f"끄지 못한 프로세스가 남았다(pid {left})" if left else f"껐다(pid {info['pids'][0]})"


KINDS = {
    "scheduler": (_sched_info, _sched_start, _sched_stop),
    "dashboard": (_dash_info, _dash_start, _dash_stop),
}


# ----- 화면에 주는 값 -----
def _url(port: int | None) -> str:
    """서비스가 듣는 주소. 서버는 모두 127.0.0.1에 묶이므로 포트만 다르다. 포트가 없는 서비스는 빈 문자열이다."""
    return f"http://127.0.0.1:{port}/" if port else ""


def state() -> list[dict]:
    out = []
    for s in services():
        info = KINDS[s["kind"]][0](s)
        out.append({"name": s["name"], "label": s.get("label", s["name"]), "up": info["up"], "pids": info["pids"],
                    "port": info["port"], "url": _url(info["port"]),
                    "note": info["note"], "running": info.get("running", 0)})
    return out


def groups() -> list[dict]:
    """services.toml의 group이 같은 서비스를 묶는다. group이 없는 서비스는 혼자 한 묶음이다. 묶음 이름과 글자는 [[group]] 표에서 온다."""
    labels = {g["name"]: g.get("label", g["name"]) for g in _read().get("group", [])}
    out: dict[str, dict] = {}
    for s in services():
        key = s.get("group") or s["name"]
        g = out.setdefault(key, {"name": key, "label": labels.get(key) or s.get("label", s["name"]), "members": []})
        g["members"].append(s["name"])
    return list(out.values())


def act_group(group: str, action: str, force: bool = False) -> dict:
    """묶음 전체를 끄고, 켜고, 다시 켠다. 끄기는 스케줄러를 먼저 끄고(멈춤 표시, 실행 중 작업이 있으면 force 없이 거절) 나머지를 끈다."""
    g = next((x for x in groups() if x["name"] == group), None)
    if not g:
        return {"ok": False, "message": f"모르는 묶음: {group}"}
    members = [_find(n) for n in g["members"]]
    sched = [s for s in members if s["kind"] == "scheduler"]
    rest = [s for s in members if s["kind"] != "scheduler"]
    if action not in ("start", "stop", "restart"):
        return {"ok": False, "message": f"모르는 동작: {action}"}
    msgs = []
    if action in ("stop", "restart"):
        for s in sched:
            out = supervise.stop_scheduler(by="Monitor", force=force)
            if not out["ok"]:
                return {"ok": False, "message": f"{g['label']}: 끄지 않았다. {redact(out['why'])}"}
            msgs.append(f"{s.get('label', s['name'])}: {redact(out['text'])}")
        for s in rest:
            msgs.append(f"{s.get('label', s['name'])}: {redact(KINDS[s['kind']][2](s))}")
    if action in ("start", "restart"):
        for s in sched:  # 멈춤을 풀고 먼저 띄운다. 대시보드 감시와 겹쳐 띄우지 않으려는 순서다
            out = supervise.start_scheduler()
            msgs.append(f"{s.get('label', s['name'])}: {redact(out['text'] if out['ok'] else out['why'])}")
        for s in rest:
            msgs.append(f"{s.get('label', s['name'])}: {redact(KINDS[s['kind']][1](s))}")
    return {"ok": True, "message": " / ".join(msgs)}


def act(name: str, action: str) -> dict:
    s = _find(name)
    _, start, stop = KINDS[s["kind"]]
    if action == "start":
        msg = start(s)
    elif action == "stop":
        msg = stop(s)
    elif action == "restart":
        msg = f"{stop(s)}. {start(s)}"
    else:
        return {"ok": False, "message": f"모르는 동작: {action}"}
    return {"ok": True, "message": f"{s.get('label', name)}: {redact(msg)}"}


def _decode(line: bytes) -> str:
    """로그 줄은 UTF-8이 기본이고, 인코딩을 정하지 않고 띄운 옛 서버의 줄은 Windows 한글 코드 페이지(cp949)다."""
    try:
        return line.decode("utf-8")
    except UnicodeDecodeError:
        return line.decode("cp949", errors="replace")


def log_tail(name: str, lines: int = LOG_LINES) -> dict:
    s = _find(name)
    path = Path(KINDS[s["kind"]][0](s)["log"])
    try:
        with path.open("rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 400 * max(lines, 1)))  # 한 줄 400바이트로 어림해 끝쪽만 읽는다
            raw = f.read()
    except OSError:
        return {"name": name, "lines": [], "path": str(path), "missing": True}
    rows = [redact(_decode(r).rstrip()) for r in raw.splitlines()]
    return {"name": name, "lines": rows[-lines:], "path": str(path), "missing": False}
