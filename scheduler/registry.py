"""프로젝트 등록부. projects/<이름>.toml을 읽고 작업자 --settings의 deny 규칙을 만든다."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from scheduler.config import (
    ROOT,
    DEFAULT_SEGMENT_MIN,
    DEFAULT_TOTAL_MIN,
    PROJECTS,
    SETTINGS_DIR,
    SETTINGS_FILE,
)

KINDS = {"code", "doc", "experiment", "hardware", "game"}
WORKER_PROVIDERS = {"claude", "codex"}


class RegistryError(ValueError):
    pass


@dataclass
class Project:
    name: str
    path: Path
    kind: str
    priority: int = 50
    run_prefix: str = "uv run"
    auto_scope: str = ""
    commit: bool = True
    manual_only: bool = False  # 세션이 jipsa begin이나 record로만 기록한다. 스케줄러가 큐로 올리지 않고(Auto 줄이면 건너뜀) 세션 폴더 판정에도 쓰지 않는다(misc)
    allowed_dirs: list[str] = field(default_factory=list)
    scope_notes: list[str] = field(default_factory=list)
    no_read: list[str] = field(default_factory=list)
    read_only: list[str] = field(default_factory=list)
    generated: dict[str, str] = field(default_factory=dict)
    link_dirs: list[str] = field(default_factory=list)
    external_read: list[str] = field(default_factory=list)
    external_forbid: list[str] = field(default_factory=list)
    gpu_vram_gb: float = 0.0
    gpu_exclusive: bool = False
    ram_gb: float = 0.0
    ollama_models: list[str] = field(default_factory=list)
    total_minutes: int = 90
    segment_minutes: int = 30
    deps_manager: str = "uv-lock"
    deps_lock_file: str = ""
    deps_venv: str = ".venv"
    questions: list[str] = field(default_factory=list)
    worker_provider: str = "claude"  # 작업자 공급자 claude 또는 codex. 큐 항목의 worker가 앞선다
    worker_model: str = ""  # 비우면 공급자별 기본 모델
    match_minutes: dict[str, float] = field(default_factory=dict)  # 게임:인원별 한 판 분. 있으면 begin --games로 상한을 판 수로 계산한다
    preview_base: str = ""  # 미리보기 서버 주소. content/<절>/<글>/index.md를 바꾼 작업은 <주소><절>/<글>/가 초안 주소다

    @property
    def needs_gpu(self) -> bool:
        return self.gpu_vram_gb > 0 or self.gpu_exclusive or bool(self.ollama_models)

    @property
    def uses_worktree(self) -> bool:
        return self.kind in {"code", "experiment"}


def _project_path(text: str) -> Path:
    """등록부의 path. ~는 홈 폴더로 풀고, 상대 경로는 jipsa 폴더 기준이다."""
    p = Path(text).expanduser()
    return p if p.is_absolute() else (ROOT / p).resolve()


def _load_one(path: Path) -> Project:
    with path.open("rb") as f:
        raw = tomllib.load(f)
    name = raw.get("name") or path.stem
    kind = raw.get("kind", "")
    if kind not in KINDS:
        raise RegistryError(f"{path.name}: kind가 {sorted(KINDS)} 가운데 하나여야 한다 (지금 {kind!r})")
    scope = raw.get("scope", {})
    paths = raw.get("paths", {})
    links = raw.get("links", {})
    ext = raw.get("external", {})
    res = raw.get("resources", {})
    lim = raw.get("limits", {})
    deps = raw.get("deps", {})
    q = raw.get("questions", {})
    worker = raw.get("worker", {})
    provider = str(worker.get("provider", "claude")).strip().lower() or "claude"
    if provider not in WORKER_PROVIDERS:
        raise RegistryError(f"{path.name}: worker.provider가 {sorted(WORKER_PROVIDERS)} 가운데 하나여야 한다 (지금 {provider!r})")
    return Project(
        name=name,
        path=_project_path(raw["path"]),
        kind=kind,
        priority=int(raw.get("priority", 50)),
        run_prefix=raw.get("run_prefix", "uv run"),
        auto_scope=scope.get("auto", ""),
        commit=bool(scope.get("commit", kind != "doc")),
        manual_only=bool(scope.get("manual_only", False)),
        allowed_dirs=list(scope.get("allowed_dirs", [])),
        scope_notes=list(scope.get("notes", [])),
        no_read=list(paths.get("no_read", [])),
        read_only=list(paths.get("read_only", [])),
        generated=dict(paths.get("generated", {})),
        link_dirs=list(links.get("dirs", [])),
        external_read=list(ext.get("read", [])),
        external_forbid=list(ext.get("forbid", [])),
        gpu_vram_gb=float(res.get("gpu_vram_gb", 0)),
        gpu_exclusive=bool(res.get("gpu_exclusive", False)),
        ram_gb=float(res.get("ram_gb", 0)),
        ollama_models=list(res.get("ollama_models", [])),
        total_minutes=int(lim.get("total_minutes", DEFAULT_TOTAL_MIN.get(kind, 90))),
        segment_minutes=int(lim.get("segment_minutes", DEFAULT_SEGMENT_MIN.get(kind, 30))),
        deps_manager=deps.get("manager", "uv-lock"),
        deps_lock_file=deps.get("lock_file", ""),
        deps_venv=deps.get("venv", ".venv"),
        questions=list(q.get("items", [])),
        preview_base=str(raw.get("preview", {}).get("base", "")),
        match_minutes={str(k).lower(): float(v) for k, v in raw.get("match_minutes", {}).items()},
        worker_provider=provider,
        worker_model=str(worker.get("model", "")).strip(),
    )


def load_all() -> dict[str, Project]:
    out: dict[str, Project] = {}
    for p in sorted(PROJECTS.glob("*.toml")):
        proj = _load_one(p)
        out[proj.name] = proj
    return out


def load(name: str) -> Project:
    path = PROJECTS / f"{name}.toml"
    if not path.exists():
        raise RegistryError(f"등록부에 {name}이 없다 ({path})")
    return _load_one(path)


def _pattern(entry: str) -> str:
    """등록부의 경로 표기를 Claude Code 권한 규칙의 경로로 바꾼다."""
    entry = entry.strip()
    if entry.startswith("*"):
        return f"**/{entry}"
    if entry.endswith("/"):
        return f"./{entry}**"
    return f"./{entry}"


def deny_rules(project: Project) -> list[str]:
    rules: list[str] = []
    for e in project.no_read:
        p = _pattern(e)
        rules += [f"Read({p})", f"Edit({p})", f"Write({p})"]
    for e in project.read_only:
        p = _pattern(e)
        rules += [f"Edit({p})", f"Write({p})"]
    for e in project.generated:
        p = _pattern(e)
        rules += [f"Edit({p})", f"Write({p})"]
    return rules


def write_settings(project: Project) -> Path:
    """공통 deny와 프로젝트 deny를 합친 --settings 파일을 runtime/state/settings/에 만든다."""
    base = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    perms = base.setdefault("permissions", {})
    deny = list(perms.get("deny", []))
    for r in deny_rules(project):
        if r not in deny:
            deny.append(r)
    perms["deny"] = deny
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    target = SETTINGS_DIR / f"{project.name}.json"
    target.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
