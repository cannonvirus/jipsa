"""프로세스 도우미. 대시보드와 스케줄러를 다시 띄우는 jipsa settings restart가 쓴다."""
from __future__ import annotations

import os
import subprocess
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import psutil

from scheduler.config import STATE
from scheduler.nowindow import BACKGROUND, BREAKAWAY, hidden

DASH_LOG = STATE / "dashboard.log"
LOG_MAX = 1_000_000  # 띄울 때 로그가 이보다 크면 뒤쪽만 남긴다


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


def _popen(cmd: list[str], log: Path, cwd: Path) -> subprocess.Popen:
    """창 없는 분리 프로세스. 새 프로세스 그룹이고 부모의 작업 개체에서 떨어져 나가 부모를 꺼도 남는다."""
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        if log.stat().st_size > LOG_MAX:
            log.write_bytes(log.read_bytes()[-LOG_MAX // 2:])
    except OSError:
        pass
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    with log.open("ab") as f:
        f.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} 다시 띄움 =====\n".encode("utf-8"))
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


def _is_dashboard(p: psutil.Process) -> bool:
    try:
        cmd = [a.lower() for a in p.cmdline()]
    except (psutil.Error, OSError):
        return False
    joined = " ".join(cmd)
    return "web" in cmd and ("jipsa" in joined or "scheduler.cli" in joined)
