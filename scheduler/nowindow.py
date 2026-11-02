"""Windows에서 자식 프로세스가 콘솔 창을 띄우지 않게 하는 공통 설정(261022-jipsa-35).

jipsa가 띄우는 모든 자식 프로세스는 subprocess 호출에 hidden()을 펼쳐 넣는다. CREATE_NO_WINDOW는 자식에게 보이지 않는
새 콘솔을 주고, 그 자식이 다시 띄우는 콘솔 프로그램(가상환경 python 실행기가 띄우는 실제 python, claude가 띄우는 bash와 git)은
그 숨은 콘솔을 물려받는다. DETACHED_PROCESS를 같이 주면 CREATE_NO_WINDOW가 무시되고 콘솔이 없는 자식이 띄운 손자가
새 콘솔을 만들어 Windows Terminal 탭이 뜬다. 그래서 DETACHED_PROCESS는 쓰지 않는다. 다른 운영체제에서는 빈 값이다.
"""

from __future__ import annotations

import os
import subprocess

_WIN = os.name == "nt"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# 대시보드와 따로 사는 장기 백그라운드. 새 프로세스 그룹이라 대시보드 콘솔의 Ctrl+C가 닿지 않는다
BACKGROUND = NO_WINDOW | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
BREAKAWAY = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)  # 부모의 작업 개체(Job)가 닫힐 때 같이 죽지 않게


def _startupinfo() -> subprocess.STARTUPINFO:
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE  # 창을 만드는 프로그램이 첫 창을 숨긴 채 열게 한다
    return si


def hidden(flags: int = NO_WINDOW) -> dict:
    """subprocess.run, Popen에 펼쳐 넣을 인자. 예: subprocess.run(cmd, **hidden())."""
    if not _WIN:
        return {}
    return {"creationflags": flags, "startupinfo": _startupinfo()}
