"""세션의 Claude Code 프로세스와 그 세션이 띄운 답 대기 명령을 찾는다(261025-jipsa-13 1안).

답 대기 명령(wait-answer. 옛 Auto 모드의 cycle wait는 261025-jipsa-42에서 뗐다)은 세션이 자기 도구로 백그라운드에 띄운 것이어야 끝날 때 세션을 깨운다.
그래서 이 세션의 Claude Code 프로세스 자손 가운데 같은 세션 기록 id로 띄운 대기 명령만 있는 것으로 친다.
분리 프로세스로 띄운 대기 명령은 부모 사슬이 끊겨 자손에 들지 않으므로 없는 것으로 친다.

hook(hooks/track.py)도 부르므로 표준 라이브러리와 psutil만 쓰고 scheduler의 다른 모듈을 들이지 않는다.
어떤 오류도 밖으로 내지 않는다. 판단할 수 없으면 안내하지 않는 쪽(빈 글, None)으로 둔다.

JIPSA_CLAUDE_PID는 확인용 옵션이고 운영에서는 쓰지 않는다. 값이 있으면 그 번호의 프로세스만 Claude Code 프로세스로 친다.
검증 스크립트가 자기를 Claude Code 역할로 세워 자식으로 띄운 대기 명령과 hook을 시험할 때 쓴다.
"""

from __future__ import annotations

import os


def _is_claude(proc) -> bool:
    fake = os.environ.get("JIPSA_CLAUDE_PID", "").strip()
    if fake:
        return str(proc.pid) == fake
    return "claude" in proc.name().lower()


def claude_proc():
    """이 프로세스의 부모 사슬에서 가장 가까운 Claude Code 프로세스(psutil.Process). 없거나 psutil을 쓸 수 없으면 None이다."""
    try:
        import psutil

        p = psutil.Process().parent()
        while p is not None:
            if _is_claude(p):
                return p
            p = p.parent()
    except Exception:  # noqa: BLE001 - 확인하지 못하면 없다고 둔다
        return None
    return None


def is_print_mode(proc) -> bool:
    """`claude -p`로 띄운 작업자 세션이다. 사람과 대화하는 세션이 아니므로 안내와 경고를 내지 않는다."""
    try:
        args = proc.cmdline()
    except Exception:  # noqa: BLE001
        return False
    return any(a in ("-p", "--print") for a in args[1:])


def alive(proc) -> bool:
    """처음 찾은 Claude Code 프로세스가 아직 살아 있는지. 번호가 다른 프로세스에 다시 쓰였으면 죽은 것으로 본다."""
    try:
        return bool(proc.is_running())
    except Exception:  # noqa: BLE001
        return True  # 확인하지 못하면 살아 있다고 둔다. 대기 명령을 잘못 끝내지 않는다


def wait_kind(args: list[str]) -> str:
    """명령줄 인자 목록이 답 대기 명령이면 종류를 돌려준다. 셸이 명령 글 전체를 인자 하나로 받은 줄은 세지 않는다."""
    return "wait-answer" if "wait-answer" in args else ""  # 옛 cycle wait는 jipsa cycle 명령과 함께 뗐다


def session_arg(args: list[str]) -> str:
    for i, a in enumerate(args):
        if a == "--session" and i + 1 < len(args):
            return args[i + 1]
        if a.startswith("--session="):
            return a.split("=", 1)[1]
    return ""


def find_waits(session_run: str, claude) -> list[dict]:
    """claude 프로세스의 자손 가운데 이 세션 기록 id로 띄운 답 대기 명령. 자손만 보므로 부모 사슬이 그 프로세스에 닿는 것만 남는다."""
    out = []
    for c in claude.children(recursive=True):
        try:
            args = c.cmdline()
        except Exception:  # noqa: BLE001 - 그 사이 끝난 프로세스다
            continue
        kind = wait_kind(args)
        if kind and session_arg(args) == session_run:
            out.append({"pid": c.pid, "kind": kind})
    return out


def wait_command(session_run: str) -> str:
    """띄울 답 대기 명령. Auto 모드에서 쓰던 cycle wait는 jipsa cycle 명령과 함께 261025-jipsa-42에서 뗐다."""
    return f"uv run jipsa wait-answer --session {session_run} --timeout 0"


def missing_wait_line(session_run: str) -> str:
    """이 세션의 Claude Code 프로세스 아래에 답 대기 명령이 없으면 띄우라는 한 줄. 있거나 판단할 수 없으면 빈 글이다."""
    if not session_run:
        return ""
    claude = claude_proc()
    if claude is None or is_print_mode(claude):
        return ""
    try:
        if find_waits(session_run, claude):
            return ""
    except Exception:  # noqa: BLE001
        return ""
    return f"[jipsa] 답 대기 명령이 없다. 메인 세션이 백그라운드로 띄운다: {wait_command(session_run)}"


def do_lines(rows: list[dict]) -> list[str]:
    """받은편지함의 Do 요청(kind do)을 세션에 넘기는 안내 줄(261026-jipsa-26).
    대시보드 Do와 jipsa todo run이 열린 세션으로 보낸 할 일 줄이다. 세션은 CLI에서 지시받은 것처럼 begin으로 열고 서브에이전트에 맡긴다.
    hook도 같은 글을 쓰므로 여기 둔다."""
    out = []
    for r in rows:
        crit = r.get("criteria") or ""
        out.append(f"[jipsa] Do 요청: {r.get('project')} {r.get('title')} (할 일 {r.get('todo_no') or '?'}번). "
                   "CLI에서 지시받은 것처럼 jipsa begin으로 시작해 서브에이전트에 맡겨라.")
        out.append(f"- 기준: {crit}" if crit else "- 기준: 줄에 없다. 할 일 문장에서 세션 안에서 직접 확인할 수 있는 완료 기준 한 문장을 정해 --criteria로 준다")
        out.append(f"- 시작: uv run jipsa begin {r.get('project')} \"{r.get('title')}\" --criteria \"{crit or '<정한 기준>'}\" --todo \"{r.get('todo_key')}\""
                   " --executor subagent --model <모델> --agent <이름> [--est <분>]")
        out.append("- --todo는 그 할 일 줄을 파일에서 빼고 실행 기록에 줄 원문을 남긴다. 순서는 jipsa 스킬의 서브에이전트로 일 시키기와 같고 끝나면 attack과 finish로 마감한다.")
    return out


def session_run_from_env() -> str:
    """Bash 도구가 받는 CLAUDE_CODE_SESSION_ID로 세션 기록 id를 만든다. hook과 같은 규칙(session-앞 8글자)이다."""
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip()
    return f"session-{sid[:8]}" if sid else ""
