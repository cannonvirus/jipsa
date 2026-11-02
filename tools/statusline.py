"""상태줄 감싸기. Claude Code가 상태줄 명령에 넘기는 JSON에서 rate_limits 칸(5시간 창, 주간 창)을 상태 폴더에 남기고,
같은 입력을 ccstatusline에 넘겨 그 출력을 그대로 찍는다(261023-jipsa-42).

ccstatusline은 상태줄 입력에 rate_limits가 있으면 사용량 API를 부르지 않아 자기 캐시(usage.json)를 다시 쓰지 않는다.
그래서 대시보드가 읽던 캐시 파일은 수정 시각이 오래되어 Claude 값이 늘 오래된 측정으로 보였다. 이 감싸기가 신선한 값을 남긴다.
토큰이나 자격 증명은 읽지 않는다. 입력의 rate_limits 칸만 본다. 어떤 오류가 나도 상태줄 출력은 막지 않는다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN_GAP = 30  # 초. 상태줄은 10초마다 돌므로 값이 같으면 이 간격 안에서는 다시 쓰지 않는다


def _record(payload: dict) -> None:
    sys.path.insert(0, str(ROOT))
    from scheduler import claude_window

    rl = payload.get("rate_limits") if isinstance(payload, dict) else None
    if not isinstance(rl, dict):
        return
    try:
        prev = json.loads(claude_window.STATE_FILE.read_text(encoding="utf-8"))
        age = time.time() - claude_window.STATE_FILE.stat().st_mtime
    except (OSError, ValueError):
        prev, age = {}, None
    five = (rl.get("five_hour") or {}).get("used_percentage") if isinstance(rl.get("five_hour"), dict) else None
    week = (rl.get("seven_day") or {}).get("used_percentage") if isinstance(rl.get("seven_day"), dict) else None
    same = claude_window._pct(five) == prev.get("five") and claude_window._pct(week) == prev.get("week")
    if same and age is not None and age < MIN_GAP:
        return
    claude_window.record_statusline(payload)


def _ccstatusline() -> list[str] | None:
    """ccstatusline을 셸 없이 부를 명령. npm 전역 설치의 node 스크립트를 먼저 찾고, 없으면 PATH의 실행 파일이다."""
    shim = shutil.which("ccstatusline")
    node = shutil.which("node")
    if shim and node:
        js = Path(shim).parent / "node_modules" / "ccstatusline" / "dist" / "ccstatusline.js"
        if js.is_file():
            return [node, str(js)]
    return [shim] if shim else None


def main() -> int:
    env = os.environ.copy()  # 기록이 .env를 읽기 전의 환경. ccstatusline에 jipsa 비밀값이 넘어가지 않게 한다
    raw = sys.stdin.buffer.read()
    try:
        _record(json.loads(raw.decode("utf-8-sig") or "{}"))
    except Exception:  # noqa: BLE001 - 기록이 실패해도 상태줄은 찍는다
        pass
    cmd = _ccstatusline()
    if not cmd:
        return 0
    try:
        # 창 없는 부모에서 불려도 node 콘솔 창이 뜨지 않게 한다. scheduler.nowindow.hidden()과 같은 플래그다
        r = subprocess.run(cmd, input=raw, capture_output=True, timeout=20, env=env,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return 0
    sys.stdout.buffer.write(r.stdout)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
