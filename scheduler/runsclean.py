"""runs/ 중간 산출물 정리(261028-jipsa-10). 끝난 작업의 큰 중간 파일을 휴지통 폴더로 옮긴다. 지우지 않는다.

261028-jipsa-09의 수동 정리 분류를 코드로 옮겼다. 설정값은 config의 RUNS_CLEAN_*(환경 변수 JIPSA_RUNS_CLEAN_*)이다.
- 옮기는 것: 설정에서 고른 종류(KINDS)에 맞는 폴더와 파일 가운데 최소 크기 이상이고, 작업의 마지막 활동에서 보관 일수가 지난 것.
- 설정과 무관하게 지키는 것: 실행 중 작업, 사람 답을 기다리는 작업(확인 필요, 큐에 걸린 줄), 작업 공간이 남은 작업, 실행 기록에 없는 폴더,
  실행 기록과 보고서와 결과지와 그림과 미리보기(KEEP_NAME, KEEP_DIR), git 추적 파일, 다른 보고서와 기록과 등록부가 경로를 가리키는 항목,
  백업과 근거 자료 폴더(HUMAN_DIR, 사람 결정), 최근 사람이 답한 작업(사람 결정).
기본은 미리 보기다. 옮기면 휴지통 폴더의 moved.tsv에 원래 상대 경로를 남기고 상태 폴더 runs_clean.json에 마지막 실행을 적는다.
"""

from __future__ import annotations

import fnmatch
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from scheduler import config, queue
from scheduler.nowindow import hidden
from scheduler.record import read_json

MOVE = "옮김"
HUMAN = "사람 결정"
KEEP = "지킴"
NOT_YET = "기간 전"

# 종류 이름: (폴더인지, 이름 패턴, 최소 크기 밖의 조건). 설정 JIPSA_RUNS_CLEAN_KINDS가 이 열쇠를 고른다
KINDS = {
    "브라우저 프로필": (True, re.compile(r"^(chrome-prof|edge-prof|[a-z]*-?prof(ile)?)$", re.I)),
    "임시 DB 사본": (True, re.compile(r"^tmp[a-z0-9_]{4,}$", re.I)),
    "작업 폴더": (True, re.compile(r"^(cache|_warpc|__pycache__|node_modules|\.venv|work|work_calib|calib)$", re.I)),
    "중간 파일": (False, re.compile(r"\.(npy|npz|pt|ckpt|safetensors|bdic)$", re.I)),
    "원응답 로그": (False, re.compile(r"^log$")),
}
# 백업과 근거 자료라 사람이 정할 폴더 이름
HUMAN_DIR = re.compile(r"^(backup|snapshot|score|scores|home|oldhome|data|ledger|feeds)$", re.I)
# 실행 기록, 보고서, 결과지, 미리보기. 어떤 종류에 맞아도 옮기지 않는다
KEEP_NAME = re.compile(r"^(meta\.json|result\.json|result\.md|report\.md|attack.*\.json|progress\.md|plan\.md|events\.jsonl|analysis\.md|search\.md|.*\.html?|.*\.(png|jpe?g|gif|svg|webp))$", re.I)
KEEP_DIR = re.compile(r"^(figures|preview)$", re.I)
LIVE_STATUS = {"진행 중", config.HOLD}
QUEUE_LIVE = {queue.PENDING, queue.RUNNING, queue.HOLD}
MAX_DEPTH = 4
LAST_FILE = config.STATE / "runs_clean.json"
REF = re.compile(r"runs[\\/]+([0-9A-Za-z_\-\.]+(?:[\\/]+[^\s`'\"\)\],;|<>]+)*)", re.I)
RUNID_REF = re.compile(r"(?<![0-9A-Za-z_\-])(\d{6}-[0-9A-Za-z_]+-\d+(?:[\\/]+[^\s`'\"\)\],;|<>]+)+)")  # runs 없이 실행 ID로 시작한 경로
REL_REF = re.compile(r"(?<![0-9A-Za-z_\-\.:/\\])((?:[0-9A-Za-z_\-\.]+[\\/]+)+[0-9A-Za-z_\-\.]+)")  # 기록 파일 기준 상대 경로
REF_MAX_BYTES = 50_000_000  # 이보다 큰 기록 파일은 읽지 않는다. 보고서와 결과는 이보다 훨씬 작다


class TrackedError(RuntimeError):
    """git 추적 목록을 못 읽었다. 추적 파일을 지킬 수 없으므로 정리를 멈춘다."""


@dataclass
class Item:
    run: str
    rel: str  # runs 기준 상대 경로. 작업 단위로 지킨 줄은 실행 ID다
    size: int
    kind: str
    action: str
    why: str


def settings() -> dict:
    return {"on": config.RUNS_CLEAN_ON, "days": config.RUNS_CLEAN_DAYS, "kinds": list(config.RUNS_CLEAN_KINDS),
            "all_kinds": list(KINDS), "trash": config.RUNS_CLEAN_TRASH, "min_mb": config.RUNS_CLEAN_MIN_MB,
            "answer_days": config.RUNS_CLEAN_ANSWER_DAYS, "keep": list(config.RUNS_CLEAN_KEEP)}


def trash_dir(today: date | None = None, pattern: str | None = None) -> Path:
    return Path((pattern or config.RUNS_CLEAN_TRASH).replace("{date}", f"{today or config.now().date():%Y%m%d}"))


def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def _last_activity(d: Path, meta: dict) -> date:
    """파일의 가장 늦은 수정 날짜와 meta 시각 가운데 늦은 쪽. 폴더 수정 시각은 옮기기만 해도 바뀌므로 세지 않는다."""
    stamps = []
    for p in d.rglob("*"):
        try:
            if p.is_file():
                stamps.append(datetime.fromtimestamp(p.stat().st_mtime))
        except OSError:
            pass
    for key in ("started", "updated", "finished", "answered_at"):
        v = meta.get(key)
        if v:
            try:
                stamps.append(config.parse_iso(str(v)))
            except ValueError:
                pass
    return max(stamps).date() if stamps else date.min


def referenced(runs_dir: Path) -> set[str]:
    """보고서, 결과, 기록, 등록부가 가리키는 runs 아래 경로(소문자, 슬래시)."""
    root = config.MAIN_ROOT
    files = list(runs_dir.glob("*/meta.json")) + list(runs_dir.glob("*/*.md")) + list(runs_dir.glob("*/attempt-*/report.md")) \
        + list(runs_dir.glob("*/attempt-*/result.json")) + list(runs_dir.glob("*/attempt-*/result.md")) \
        + list((root / "reports").rglob("*.md")) + list((root / "projects").rglob("*.*"))
    refs: set[str] = set()
    norm = lambda s: re.sub(r"[\\/]+", "/", s).rstrip("./").lower()  # noqa: E731
    for f in files:
        try:
            if f.stat().st_size > REF_MAX_BYTES:
                continue
            t = f.read_text(encoding="utf-8", errors="ignore").replace("%5C", "/").replace("\\\\", "/")
        except OSError:
            continue
        for m in REF.finditer(t):
            refs.add(norm(m.group(1)))
        for m in RUNID_REF.finditer(t):
            refs.add(norm(m.group(1)))
        # runs 안의 기록이 자기 작업 폴더나 시도 폴더 기준 상대 경로로 가리킨 것도 지킨다. 넓게 잡아도 지키는 쪽으로만 틀린다
        try:
            own = f.resolve().relative_to(runs_dir.resolve()).parts[:-1]
        except ValueError:
            continue
        for m in REL_REF.finditer(t):
            rel = norm(m.group(1))
            for i in range(1, len(own) + 1):
                refs.add("/".join(own[:i]).lower() + "/" + rel)
    return refs


def _hit(rel: str, refs: set[str]) -> bool:
    r = rel.lower()
    return any(x == r or x.startswith(r + "/") or (r.startswith(x + "/") and x.count("/") >= 1) for x in refs)


def tracked(runs_dir: Path) -> set[str]:
    """git이 추적하는 runs 아래 파일(runs 기준 상대 경로, 소문자). 저장소 밖 시험 폴더는 추적 파일이 없다.
    git을 못 부르거나 실패 코드로 끝나면 TrackedError를 낸다. 빈 목록으로 넘어가면 추적 파일을 옮길 수 있다."""
    if not runs_dir.resolve().is_relative_to(config.MAIN_ROOT.resolve()):
        return set()
    try:
        out = subprocess.run(["git", "ls-files", "-z", "--", str(runs_dir)], cwd=str(config.MAIN_ROOT), capture_output=True,
                             timeout=60, **hidden())
    except (OSError, subprocess.SubprocessError) as e:
        raise TrackedError(f"git 추적 목록을 못 읽어 정리를 멈춘다: {e}") from e
    if out.returncode != 0:
        raise TrackedError(f"git 추적 목록을 못 읽어 정리를 멈춘다: {out.stderr.decode('utf-8', 'ignore').strip()[:200]}")
    names = out.stdout.decode("utf-8", "ignore").split("\0")
    base = runs_dir.resolve().relative_to(config.MAIN_ROOT.resolve()).as_posix() + "/"
    return {n[len(base):].lower() for n in names if n and n.startswith(base)}


def _guard(rid: str, meta: dict) -> str:
    """작업째 지키는 까닭. 없으면 빈 문자열."""
    st = config.norm_status(meta.get("status", ""))
    q = queue.by_run(rid) or {}
    if st == "진행 중" or q.get("status") == queue.RUNNING:
        return "실행 중"
    if st in LIVE_STATUS or q.get("status") in QUEUE_LIVE:
        return "사람 답 대기"
    if (config.MAIN_ROOT / "worktrees" / rid).exists():
        return "작업 공간 남음"
    return ""


def _user_keep(name: str, keep: list[str]) -> bool:
    """설정 JIPSA_RUNS_CLEAN_KEEP의 이름 패턴에 맞는지. 대소문자를 가리지 않는다."""
    return any(fnmatch.fnmatch(name.lower(), k.lower()) for k in keep)


def _kind(p: Path, kinds: list[str]) -> str:
    for name in kinds:
        is_dir, pat = KINDS[name]
        if is_dir != p.is_dir():
            continue
        if name == "원응답 로그":
            # 원응답 로그는 시도 폴더 바로 아래 log 파일이다
            if pat.match(p.name) and p.parent.name.startswith("attempt-"):
                return name
        elif (pat.match(p.name) if is_dir else pat.search(p.name)) and not KEEP_NAME.match(p.name):
            return name
    return ""


def _skip_parent(parts: tuple[str, ...]) -> bool:
    """위 폴더에서 이미 다뤘거나 지키는 폴더 아래다."""
    return any(KEEP_DIR.match(x) or HUMAN_DIR.match(x) or any(KINDS[k][0] and KINDS[k][1].match(x) for k in KINDS) for x in parts)


def plan(runs_dir: Path | None = None, *, days: int | None = None, kinds: list[str] | None = None,
         min_mb: float | None = None, today: date | None = None) -> list[Item]:
    runs_dir = runs_dir or config.RUNS
    days = config.RUNS_CLEAN_DAYS if days is None else days
    kinds = [k for k in (config.RUNS_CLEAN_KINDS if kinds is None else kinds) if k in KINDS]
    min_bytes = int((config.RUNS_CLEAN_MIN_MB if min_mb is None else min_mb) * 1_000_000)
    today = today or config.now().date()
    keep = list(config.RUNS_CLEAN_KEEP)
    refs, git = referenced(runs_dir), tracked(runs_dir)
    out: list[Item] = []
    for d in sorted(p for p in runs_dir.iterdir() if p.is_dir() and p.name != "archive"):
        rid = d.name
        meta = read_json(d / "meta.json") or {}
        if not meta:
            out.append(Item(rid, rid, 0, "", KEEP, "실행 기록에 없는 폴더"))
            continue
        why = _guard(rid, meta)
        if why:
            out.append(Item(rid, rid, 0, "", KEEP, why))
            continue
        age = (today - _last_activity(d, meta)).days
        answered = str(meta.get("answered_at") or "")
        recent_answer = False
        if answered:
            try:
                recent_answer = (today - config.parse_iso(answered).date()).days < config.RUNS_CLEAN_ANSWER_DAYS
            except ValueError:
                recent_answer = True
        for p in sorted(d.rglob("*")):
            parts = p.relative_to(d).parts
            if len(parts) > MAX_DEPTH or _skip_parent(parts[:-1]):
                continue
            if p.is_dir() and HUMAN_DIR.match(p.name):
                sz = _size(p)
                if sz >= min_bytes:
                    out.append(Item(rid, p.relative_to(runs_dir).as_posix(), sz, "백업과 근거 자료", HUMAN, "백업이나 근거 자료"))
                continue
            kind = _kind(p, kinds)
            if not kind:
                continue
            sz = _size(p)
            if sz < min_bytes:
                continue
            rel = p.relative_to(runs_dir).as_posix()
            low = rel.lower()
            if keep and (any(_user_keep(x, keep) for x in parts) or (p.is_dir() and any(_user_keep(f.name, keep) for f in p.rglob("*")))):
                act, why = KEEP, "설정에서 지키는 이름"
            elif any(g == low or g.startswith(low + "/") for g in git):
                act, why = KEEP, "git 추적 파일"
            elif _hit(rel, refs):
                act, why = HUMAN, "보고서나 다른 기록이 경로를 가리킨다"
            elif recent_answer:
                act, why = HUMAN, f"최근 {config.RUNS_CLEAN_ANSWER_DAYS}일 안에 사람이 답한 작업"
            elif age < days:
                act, why = NOT_YET, f"마지막 활동 {age}일 전, 보관 {days}일"
            else:
                act, why = MOVE, kind
            out.append(Item(rid, rel, sz, kind, act, why))
    return out


def last() -> dict:
    try:
        return json.loads(LAST_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def apply(items: list[Item], runs_dir: Path | None = None, trash: Path | None = None, how: str = "명령") -> dict:
    """옮김 줄만 휴지통 폴더의 같은 상대 경로로 옮긴다. 옮긴 목록을 moved.tsv에 덧붙이고 마지막 실행을 적는다."""
    runs_dir = runs_dir or config.RUNS
    trash = trash or trash_dir()
    trash.mkdir(parents=True, exist_ok=True)
    listing = trash / "moved.tsv"
    new = not listing.exists()
    moved, total, fails = 0, 0, []
    with listing.open("a", encoding="utf-8") as f:
        if new:
            f.write("path\tbytes\tkind\tmoved_at\n")
        for it in items:
            if it.action != MOVE:
                continue
            src, dst = runs_dir / it.rel, trash / it.rel
            if dst.exists():
                fails.append(f"{it.rel}: 휴지통에 같은 경로가 있다")
                continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
            except OSError as e:
                fails.append(f"{it.rel}: {e}")
                continue
            moved += 1
            total += it.size
            f.write(f"{it.rel}\t{it.size}\t{it.kind}\t{config.now_iso()}\n")
    rec = {"at": config.now_iso(), "how": how, "moved": moved, "bytes": total, "trash": trash.as_posix(), "fails": fails[:20],
           "runs_dir": runs_dir.as_posix()}
    if runs_dir.resolve() == config.RUNS.resolve():  # 시험 폴더에 돌린 것은 마지막 실행으로 적지 않는다
        try:
            LAST_FILE.parent.mkdir(parents=True, exist_ok=True)
            LAST_FILE.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return rec


def maybe_auto() -> dict | None:
    """스케줄러 주기에서 부른다. 설정이 켜져 있고 오늘 아직 돌지 않았을 때만 옮긴다. 기본은 꺼짐이라 아무것도 하지 않는다."""
    if not config.RUNS_CLEAN_ON:
        return None
    done = str(last().get("at") or "")
    if done.startswith(config.now().date().isoformat()):
        return None
    return apply(plan(), how="스케줄러")


def view() -> dict:
    """대시보드 표시용. 설정값과 마지막 실행이다. 미리 보기는 폴더를 다 훑으므로 화면에서 돌리지 않는다."""
    return {**settings(), "trash_today": trash_dir().as_posix(), "last": last()}
