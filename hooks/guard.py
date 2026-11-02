"""Claude Code PreToolUse hook. worktree가 아닌 원본 폴더의 코드와 설정 파일을 고치는 도구 호출을 막는다.

서브에이전트가 worktree에서 일하다가 경로를 잘못 써서 원본 코드를 고친 일이 있어 넣었다(261023-jipsa-02, -12).
Edit, Write, MultiEdit, NotebookEdit은 대상 경로가 원본의 코드 영역이면 거절한다. Bash와 PowerShell은
명령 문자열만 보고 판정이 어려우므로 원본 코드 경로와 쓰기 연산이 함께 보이면 경고만 붙이고 막지 않는다.
환경변수 JIPSA_ALLOW_ORIGIN_EDIT=1이면 아무것도 막지 않는다. 표준 라이브러리만 쓰고, 판정 밖의 오류는 막지 않고 넘긴다.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
# worktree 안의 사본이 돌아도 원본은 worktrees/의 부모다. JIPSA_ORIGIN_ROOT로 바꿀 수 있다(확인용).
ORIGIN = Path(os.environ.get("JIPSA_ORIGIN_ROOT") or (HERE.parent.parent if HERE.parent.name == "worktrees" else HERE))
CODE_DIRS = {"scheduler", "adapters", "web", "tools", "hooks", "policies"}
FREE_DIRS = {"runs", "reports", "runtime", "worktrees"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SHELL_TOOLS = {"Bash", "PowerShell"}
WRITE_OPS = re.compile(
    r"(?<![<>=-])>>?(?!=)|\btee\b|\bsed\s+-i|\b(?:cp|mv|rm|touch|truncate)\s|\bgit\s+(?:checkout|restore|apply|reset)\b"
    r"|\b(?:Set-Content|Add-Content|Out-File|New-Item|Remove-Item|Copy-Item|Move-Item|Rename-Item|Clear-Content)\b"
    r"|WriteAllText|WriteAllLines|write_text\(|open\([^)]*['\"][wa]",
    re.I,
)
# 버리는 출력과 스트림 합치기는 쓰기가 아니다(2>/dev/null, 2>&1, >$null, > NUL).
HARMLESS = re.compile(r"\d*>>?\s*(?:/dev/null|\$null|NUL\b)|\d*>&\d", re.I)


def norm(path: str, cwd: str) -> str:
    """대소문자, 슬래시, 상대 경로, ..를 정리한 비교용 경로. Git Bash 꼴(/d/...)도 드라이브 경로로 바꾼다."""
    path = path.strip().strip("\"'")
    m = re.match(r"^/([a-zA-Z])(/|$)", path)
    if m:
        path = f"{m.group(1)}:/{path[3:]}"
    if not os.path.isabs(path):
        path = os.path.join(cwd or os.getcwd(), path)
    return os.path.normcase(os.path.abspath(path)).replace("\\", "/")


def code_area(path: str, cwd: str) -> str | None:
    """원본 폴더의 코드나 설정 영역이면 원본 기준 상대 경로를, 아니면 None을 돌려준다."""
    full = norm(path, cwd)
    root = norm(str(ORIGIN), cwd).rstrip("/")
    if not full.startswith(root + "/"):
        return None
    rel = full[len(root) + 1:]
    parts = rel.split("/")
    head = parts[0]
    if head in FREE_DIRS:
        return None
    if head in CODE_DIRS:
        return rel
    if head == ".claude" and len(parts) > 1 and (parts[1] == "skills" or parts[1].startswith("settings")):
        return rel
    if head == "projects" and len(parts) == 2 and rel.endswith(".toml"):
        return rel
    if len(parts) == 1 and rel.endswith((".py", ".toml")):
        return rel
    return None


def say(obj: dict) -> None:
    """한국어를 유니코드 이스케이프로 내보내 Windows 출력 인코딩과 무관하게 한다(track.py와 같은 방식)."""
    sys.stdout.buffer.write((json.dumps(obj, ensure_ascii=True) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def deny(rel: str) -> None:
    reason = (f"원본 폴더 코드 수정 금지: 대상은 원본({ORIGIN.as_posix()})의 코드 영역({rel})이다. "
              f"worktrees/<실행ID>/ 아래 같은 경로를 고친다. 사용자가 원본 수정을 원하면 JIPSA_ALLOW_ORIGIN_EDIT=1로 세션을 띄운다.")
    say({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                "permissionDecisionReason": reason}})


def warn_shell(command: str, cwd: str) -> None:
    """명령에 원본 코드 경로와 쓰기 연산이 함께 있으면 경고만 붙인다. 읽기 명령은 쓰기 연산이 없으므로 걸리지 않는다."""
    command = HARMLESS.sub(" ", command)
    if not WRITE_OPS.search(command):
        return
    posix = ORIGIN.as_posix().rstrip("/")
    root = re.escape(posix).replace("/", r"[\\/]+")
    if re.match(r"^[a-zA-Z]:", posix):  # Git Bash 꼴 /d/coding/... 도 같은 원본이다
        root = f"(?:{root}|/{posix[0]}{re.escape(posix[2:])})"
    hits = []
    for m in re.finditer(root + r"[\\/]+([^\s\"'`;|&<>()]+)", command, re.I):
        rel = code_area(ORIGIN.as_posix() + "/" + m.group(1).replace("\\", "/"), cwd)
        if rel:
            hits.append(rel)
    if hits:
        msg = (f"경고: 명령이 원본 폴더의 코드 경로({', '.join(sorted(set(hits))[:3])})에 쓰는 것으로 보인다. "
               f"worktree 작업이면 worktrees/<실행ID>/ 아래 경로로 바꾼다.")
        say({"systemMessage": msg,
             "hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": msg}})


def main() -> None:
    if os.environ.get("JIPSA_ALLOW_ORIGIN_EDIT") == "1":
        return
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
    except ValueError:
        return
    tool = data.get("tool_name") or ""
    args = data.get("tool_input") or {}
    cwd = data.get("cwd") or ""
    if tool in EDIT_TOOLS:
        path = args.get("file_path") or args.get("notebook_path") or ""
        rel = code_area(path, cwd) if path else None
        if rel:
            deny(rel)
    elif tool in SHELL_TOOLS:
        warn_shell(str(args.get("command") or ""), cwd)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # 판정 밖의 오류로 일반 작업을 막지 않는다
        pass
    sys.exit(0)
