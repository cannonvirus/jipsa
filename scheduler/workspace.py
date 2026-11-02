"""작업 트리와 커밋. git worktree, 저장 커밋, diff, jipsa 대신 커밋."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from scheduler.config import WORKTREES, redact
from scheduler.nowindow import hidden
from scheduler.registry import Project


class GitError(RuntimeError):
    pass


def git(path: Path, *args: str, check: bool = True, timeout: int = 120) -> str:
    try:
        proc = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout, check=False, **hidden())
    except (OSError, subprocess.TimeoutExpired) as e:
        raise GitError(f"git {' '.join(args[:2])} 실행 실패: {redact(str(e))}") from e
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args[:3])} 실패: {redact((proc.stderr or proc.stdout)[-600:])}")
    return proc.stdout


def is_repo(path: Path) -> bool:
    try:
        return git(path, "rev-parse", "--is-inside-work-tree", check=False).strip() == "true"
    except GitError:
        return False


def head(path: Path) -> str:
    return git(path, "rev-parse", "HEAD").strip()


def branch_name(run_id: str, title: str) -> str:
    """orch/YYMMDD-프로젝트-작업. 항목 이름은 공백을 -로 바꾸고 git이 못 받는 글자를 뺀다."""
    slug = re.sub(r"[^\w가-힣-]+", "-", title.strip())
    slug = re.sub(r"-+", "-", slug).strip("-")[:40] or "task"
    return f"orch/{run_id}-{slug}"


def dirty_files(path: Path) -> list[str]:
    out = git(path, "status", "--porcelain", "--untracked-files=all")
    files = []
    for line in out.splitlines():
        if len(line) > 3:
            files.append(line[3:].strip().strip('"'))
    return files


def matches_no_read(files: list[str], no_read: list[str]) -> list[str]:
    hits = []
    for f in files:
        for pat in no_read:
            p = pat.strip().rstrip("/")
            if not p:
                continue
            if p.startswith("*"):
                if f.endswith(p.lstrip("*")):
                    hits.append(f)
            elif f == p or f.startswith(p + "/"):
                hits.append(f)
    return hits


def add_worktree(project: Project, run_id: str, title: str, start: str = "") -> tuple[Path, str, str]:
    """worktrees/<실행ID>에 jipsa 브랜치를 만든다. (경로, 브랜치, 분기점 해시)를 돌려준다.

    start가 있으면 그 브랜치에서 갈라진다. 위임 cycle이 채택된 앞 바퀴 브랜치 위에서 다음 바퀴를 돌릴 때 쓴다.
    """
    WORKTREES.mkdir(parents=True, exist_ok=True)
    target = WORKTREES / run_id
    branch = branch_name(run_id, title)
    base = git(project.path, "rev-parse", start).strip() if start else head(project.path)
    git(project.path, "worktree", "add", str(target), "-b", branch, *([base] if start else []))
    link_dirs(project, target)
    return target, branch, base


def link_dirs(project: Project, worktree: Path) -> list[str]:
    """`.venv`와 데이터 폴더는 원본 경로를 가리킨다. Windows 정션으로 잇는다."""
    linked = []
    for rel in project.link_dirs:
        src = project.path / rel
        dst = worktree / rel
        if not src.exists() or dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            proc = subprocess.run(["cmd", "/c", "mklink", "/J", str(dst), str(src)], capture_output=True, text=True, errors="replace", **hidden())
            if proc.returncode == 0:
                linked.append(rel)
        else:
            proc = subprocess.run(["cmd", "/c", "mklink", "/H", str(dst), str(src)], capture_output=True, text=True, errors="replace", **hidden())
            if proc.returncode == 0:
                linked.append(rel)
    return linked


def remove_worktree(project: Project, worktree: Path, *, delete_branch: bool = False, branch: str = "") -> None:
    git(project.path, "worktree", "remove", "--force", str(worktree), check=False)
    if delete_branch and branch:
        git(project.path, "branch", "-D", branch, check=False)


def diff_text(path: Path, base: str, *, max_bytes: int = 300_000) -> str:
    """분기점(또는 저장 커밋)과 지금 작업 트리의 차이. 커밋된 것과 안 된 것을 모두 담는다."""
    out = git(path, "diff", base, "--", ".", check=False)
    untracked = git(path, "ls-files", "--others", "--exclude-standard", check=False).strip()
    if untracked:
        out += "\n\n# 추적되지 않은 새 파일\n" + untracked
    if len(out) > max_bytes:
        out = out[:max_bytes] + f"\n\n# ... {len(out) - max_bytes}자 생략"
    return out


def changed_files(path: Path, base: str) -> list[str]:
    names = git(path, "diff", "--name-only", base, "--", ".", check=False).split()
    untracked = git(path, "ls-files", "--others", "--exclude-standard", check=False).split()
    return sorted(set(names) | set(untracked))


def commits_since(path: Path, base: str) -> list[str]:
    out = git(path, "log", "--format=%h %s", f"{base}..HEAD", check=False)
    return [line for line in out.splitlines() if line.strip()]


def commit_all(path: Path, message: str) -> str | None:
    """작업 트리가 더러우면 전부 커밋하고 해시를 돌려준다. 깨끗하면 None."""
    if not dirty_files(path):
        return None
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", message)
    return git(path, "rev-parse", "--short", "HEAD").strip()


def save_commit(project: Project, message_fn) -> dict:
    """doc 프로젝트의 커밋 안 된 파일을 [jipsa] 작업 중 저장 커밋으로 묶는다(3.2).

    message_fn(files, diff) -> str. 읽지 않음 경로가 섞여 있으면 커밋하지 않고 그 사실을 돌려준다.
    """
    if not is_repo(project.path):
        return {"done": False, "reason": "git 저장소가 아니다", "files": []}
    files = dirty_files(project.path)
    if not files:
        return {"done": False, "reason": "", "files": []}
    hits = matches_no_read(files, project.no_read)
    if hits:
        return {"done": False, "reason": f"읽지 않음 경로가 커밋 안 된 상태: {', '.join(hits[:5])}", "files": files, "hold": True}
    diff = git(project.path, "diff", "--stat", check=False)
    try:
        msg = message_fn(files, diff)
    except Exception:  # noqa: BLE001 - 메시지 생성 실패는 파일 수로 대신한다
        msg = f"파일 {len(files)}개"
    msg = msg.strip().splitlines()[0][:80] if msg.strip() else f"파일 {len(files)}개"
    git(project.path, "add", "-A")
    git(project.path, "commit", "-q", "-m", f"[jipsa] 작업 중 저장: {msg}")
    return {"done": True, "reason": "", "files": files, "commit": git(project.path, "rev-parse", "--short", "HEAD").strip()}
