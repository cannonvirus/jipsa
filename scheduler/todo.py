"""할 일 파일. 상태 폴더의 todo.md 하나에 사람이 넣은 할 일을 둔다(261025-jipsa-14, TODO와 Auto 1단계).
주간 계획 파일을 떼며 계획 폴더(planner/todo.md)에서 상태 폴더로 옮겼다(261025-jipsa-42). 시험은 JIPSA_STATE_DIR로 함께 바뀐다.

파일은 `## 할 일` 절 하나다(261029-jipsa-17에서 Auto 절을 뗐다). 한 줄이 할 일 하나이고 칸은 세로 막대로 나눈다.

    ## 할 일
    - game_ai | 2인 점수 올리기 | cycle 고정 시드 40판 평균 점수 50 이상 상한 8
    - example_app | 요약을 한국어로 바꾸기 | 세 피드에서 한국어 요약 줄이 나온다 | 한도 VRAM 6GB, RAM 12GB, CPU 4

옛 `## Auto` 절이 남은 파일은 그 절의 줄도 할 일로 읽는다. 파일을 고쳐 쓸 때 옛 Auto 절 머리를 떼고 그 줄을 할 일 절 맨 위로 옮긴다(_merge_old_auto).

- 첫 칸은 등록부 프로젝트 이름이고 둘째 칸은 할 일 문장이다. 둘 다 있어야 한다. 기타는 등록부 misc로 읽는다.
- 나머지 칸은 모두 선택이고 칸 이름으로 가른다. 이름 없는 칸은 기준(완료 기준)이고 하나만 둔다. 앞에 붙은 "기준:"은 뗀다.
- cycle 칸은 "cycle <지표> <목표값><단위> 이상|이하"이고 끝에 "상한 N"과 "도달하면 끝"을 이 순서로 붙일 수 있다. 상한은 나아지지 않은 Cycle을
  몇 번 연속까지 볼지이고 1 이상의 정수다. 적지 않으면 상한이 없어 마감까지 돈다(261026-jipsa-03, 전에는 5). 상한은 따로 "| 상한 N" 칸으로
  적어도 되지만 cycle 칸이 있어야 한다. "도달하면 끝"을 적지 않으면 목표에 닿아도 끝내지 않고 마감까지 다음 Cycle을 돈다.
- 한도 칸은 "한도 VRAM 6GB, RAM 12GB, CPU 4"처럼 필요한 것만 쉼표로 적는다. VRAM과 RAM은 GB, CPU는 스레드 수(정수)다.
- 같은 프로젝트와 같은 문장의 줄은 두 절을 통틀어 하나만 둔다. 상태 표시는 적지 않는다.
- 번호는 할 일 절 위에서부터 매긴다. 지우기와 찾기는 번호나 문장 일부로 하고, 일부가 여러 줄에 걸리면 거절한다.
- 손으로 고쳐도 명령과 같게 읽는다. 절 밖의 줄과 "- "로 시작하지 않는 줄은 읽지 않고, 칸이 틀린 줄은 목록에 읽지 못한 줄로 보인다.
- 넣는 명령은 할 일 절 끝에 한 줄을 더하고 지우는 명령은 그 줄만 뺀다. 파일의 다른 줄은 그대로 둔다.

할 일 절은 큐가 읽지 않는다. 넣어도 돌지 않고 시킨 줄만 돈다(jipsa todo run, scheduler/auto.py). 시작한 일회성 줄은 take로 파일에서 빠진다.
Cycle 목표 줄(cycle 칸)은 끝날 때까지 제자리에 남고 끝나면 move로 할 일 절 맨 아래로 간다. 기준 없는 줄은 기획 단계의 답을 set_criteria로
기준 칸에 적는다(261025-jipsa-24, 4단계).

`## 메모` 절은 자유 글 한 줄이 메모 하나다(261025-jipsa-36, 주간 계획 파일을 대신하는 메모 전환). 프로젝트와 기준 규칙이 없고
큐와 Auto 모두 읽지 않는다. 번호는 메모끼리 따로 1부터 매기고 목록에는 m1처럼 찍는다. memo_add로 넣고 memo_remove로 지우며,
promote가 메모 한 줄을 할 일 절 줄(프로젝트 | 할 일 | 기준 ..)로 바꿔 옮긴다. 메모 글이 이미 그 꼴이면 그대로 받는다.

cycle 칸 바꾸기(261025-jipsa-49): set_cycle이 번호나 문장 일부로 고른 줄의 cycle 칸을 채우거나 덮어쓰거나 비운다. 줄은 제자리에 두고
다른 칸은 그대로다. 명령 인자 '<지표> <목표값> [이상|이하] [상한 N]'은 cycle_cell이 읽는다. 방향을 적지 않으면 이상이고, 상한을 적지 않으면
칸에 적지 않아 상한 없이 돈다(DEFAULT_CAP None). 덮어쓰기는 칸 전체를 바꾸므로 옛 상한도 남지 않는다.
도는 줄(큐의 대기나 실행 중 줄)은 부르는 쪽이 busy로 넘겨 거절한다.

목표 미정 Cycle(261026-jipsa-11): 지표나 목표값을 비운 cycle 칸도 받는다. 둘 다 비면 "cycle 미정"이고, 하나만 비면
"cycle 지표 미정 50 이상", "cycle 첫 글자 지연 목표 미정"처럼 빈 쪽에 미정을 적는다. 방향, 상한, 도달하면 끝은 적었을 때만 붙는다.
이런 줄은 Cycle 1 분석이 빈 칸(지표, 목표값, 방향, 상한)을 정하고 jipsa가 fill_cycle로 빈 칸만 채운다(scheduler/cycle.py).
사람이 적은 값은 덮지 않는다. 지표와 목표값이 모두 찬 칸은 옛 꼴 그대로다.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from scheduler.config import STATE

TODO_FILE = STATE / "todo.md"
AUTO = "Auto"  # 옛 절 이름. 261029-jipsa-17부터 이 절의 줄은 할 일로 읽는다
TODO = "할 일"
MEMO = "메모"
SECTIONS = (TODO,)  # 할 일 줄이 드는 절. 메모 절은 따로 읽는다(memos). 옛 Auto 절은 할 일로 읽는다
PENDING = "미정"  # 목표 미정 cycle 칸의 빈 값 표기(261026-jipsa-11)
DEFAULT_CAP = None  # cycle 칸에 상한이 없을 때의 연속 정체 Cycle 수. None이면 상한 없이 마감까지 돈다(261026-jipsa-03, 전에는 5)
STOP_WORDS = "도달하면 끝"  # cycle 칸 끝의 선택 낱말. 적으면 목표에 닿은 Cycle에서 끝낸다
ALIASES = {"기타": "misc"}  # 화면 이름을 등록부 이름으로

TEMPLATE = (
    "# 할 일\n\n"
    "손으로 고쳐도 된다. 한 줄이 할 일 하나다. 프로젝트 | 할 일 문장 | 기준(선택) | cycle 지표 목표값 이상 상한 N(선택) | 한도 VRAM 6GB, RAM 12GB, CPU 4(선택)\n"
    "할 일 절의 줄은 넣어도 돌지 않고 시킨 줄만 돈다. 메모 절은 자유 글 한 줄씩이고 할 일로 올리기 전에는 아무것도 읽지 않는다.\n\n"
    f"## {TODO}\n\n"
    f"## {MEMO}\n"
)

_CYCLE = re.compile(r"^cycle\s+(?P<metric>.+?)\s+(?P<target>-?\d+(?:\.\d+)?)\s*(?P<unit>[^\s\d]*?)\s*(?P<dir>이상|이하)"
                    r"(?:\s+상한\s+(?P<cap>\S+?))?(?P<stop>\s+도달하면\s*끝)?$", re.I)
# 목표 미정 꼴. 지표나 목표값 자리에 미정을 적은 칸이다. 미정 낱말이 있을 때만 이 꼴로 읽는다
_CYCLE_TBD = re.compile(r"^cycle\s+(?:(?P<all>미정)|(?:지표\s+미정|(?P<metric>.+?))\s+(?:목표\s+미정|(?P<target>-?\d+(?:\.\d+)?)(?P<unit>[^\s\d]*?)))"
                        r"(?:\s+(?P<dir>이상|이하))?(?:\s+상한\s+(?P<cap>\S+?))?(?P<stop>\s+도달하면\s*끝)?$", re.I)
_LIMIT = re.compile(r"^(?P<key>vram|ram|cpu)\s*(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>gb|gib|g|스레드|코어)?$", re.I)
_HEAD = re.compile(r"^##\s+(.+?)\s*$")
_ITEM = re.compile(r"^\s*[-*]\s+(.*)$")


class TodoError(ValueError):
    pass


@dataclass
class Todo:
    project: str
    text: str
    criteria: str = ""
    cycle: dict | None = None  # metric, target, unit, dir, cap(없으면 None). 목표 미정이면 metric이나 target이 빈 글이다
    limits: dict = field(default_factory=dict)  # vram_gb, ram_gb, cpu
    section: str = TODO
    lineno: int = -1  # 파일 안 줄 번호(0부터)
    no: int = 0  # 목록 번호(1부터)

    @property
    def key(self) -> str:
        return f"{self.project}::{self.text}"

    def line(self) -> str:
        """정해진 칸 순서로 쓴 줄 본문(앞의 "- " 없이)."""
        cells = [self.project, self.text]
        if self.criteria:
            cells.append(self.criteria)
        if self.cycle:
            cells.append(cycle_text(self.cycle))
        if self.limits:
            parts = []
            if "vram_gb" in self.limits:
                parts.append(f"VRAM {self.limits['vram_gb']:g}GB")
            if "ram_gb" in self.limits:
                parts.append(f"RAM {self.limits['ram_gb']:g}GB")
            if "cpu" in self.limits:
                parts.append(f"CPU {self.limits['cpu']}")
            cells.append("한도 " + ", ".join(parts))
        return " | ".join(cells)


def cycle_text(c: dict) -> str:
    """cycle 칸 글. 할 일 줄과 명령 출력이 같은 글을 쓴다. 비운 지표나 목표값은 미정으로 적는다."""
    metric = c.get("metric") or ""
    target = f"{c['target']}{c.get('unit') or ''}" if c.get("target") else ""
    if metric and target:
        head = f"{metric} {target}"
    elif not metric and not target:
        head = PENDING
    else:
        head = f"{metric or '지표 ' + PENDING} {target or '목표 ' + PENDING}"
    return (f"cycle {head}" + (f" {c['dir']}" if c.get("dir") else "") + (f" 상한 {c['cap']}" if c.get("cap") else "")
            + (f" {STOP_WORDS}" if c.get("stop") else ""))


def cycle_pending(c: dict | None) -> list[str]:
    """목표 미정 cycle 칸에서 비어 있는 칸 이름(지표, 목표값). cycle 칸이 없거나 둘 다 찼으면 빈 목록이다."""
    if not c:
        return []
    return [name for k, name in (("metric", "지표"), ("target", "목표값")) if not str(c.get(k) or "").strip()]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _section_of(head: str) -> str | None:
    name = re.sub(r"\s+", "", head).lower()
    if name == "auto":
        return TODO  # 옛 Auto 절(261029-jipsa-17에서 뗐다)의 줄은 할 일로 읽는다
    if name == "할일":
        return TODO
    if name == "메모":
        return MEMO
    return None


def _named(cell: str, name: str) -> str | None:
    """칸이 이름으로 시작하면 이름 뒤 내용을, 아니면 None을 돌려준다."""
    m = re.match(rf"^{name}(?:\s+|\s*:\s*|$)(.*)$", cell, re.I)
    return m.group(1).strip() if m else None


def _parse_cap(text: str) -> int:
    if not re.fullmatch(r"\d+", text or "") or int(text) < 1:
        raise TodoError(f"상한은 1 이상의 정수다 (지금 {text or '빈 값'})")
    return int(text)


def _parse_cycle(cell: str) -> dict:
    m = _CYCLE_TBD.match(cell) if re.search(rf"(?:^|\s){PENDING}(?:\s|$)", cell) else None
    if m:
        target = m.group("target") or ""
        return {"metric": _norm(m.group("metric") or ""), "target": target, "unit": (m.group("unit") or "") if target else "",
                "dir": m.group("dir") or ("이상" if target else ""), "cap": _parse_cap(m.group("cap")) if m.group("cap") else None,
                "stop": bool(m.group("stop"))}
    m = _CYCLE.match(cell)
    if not m:
        raise TodoError("cycle 칸은 'cycle 지표 목표값 이상' 꼴이다. 비운 칸은 'cycle 미정'이나 'cycle 지표 미정 50 이상'처럼 미정으로 적는다")
    return {"metric": _norm(m.group("metric")), "target": m.group("target"), "unit": m.group("unit") or "",
            "dir": m.group("dir"), "cap": _parse_cap(m.group("cap")) if m.group("cap") else None, "stop": bool(m.group("stop"))}


def _parse_limits(body: str) -> dict:
    out: dict = {}
    parts = [p.strip() for p in re.split(r"[,，]", body or "") if p.strip()]
    if not parts:
        raise TodoError("한도 칸이 비었다. 'VRAM 6GB, RAM 12GB, CPU 4'처럼 적는다")
    for p in parts:
        m = _LIMIT.match(p)
        if not m:
            raise TodoError(f"한도 '{p}'를 읽지 못했다. VRAM, RAM은 GB 수, CPU는 스레드 수로 적는다")
        key, value = m.group("key").lower(), float(m.group("value"))
        if value <= 0:
            raise TodoError(f"한도 '{p}'는 0보다 커야 한다")
        name = {"vram": "vram_gb", "ram": "ram_gb", "cpu": "cpu"}[key]
        if name in out:
            raise TodoError(f"한도 {m.group('key').upper()}를 두 번 적었다")
        if name == "cpu":
            if not value.is_integer():
                raise TodoError("CPU 한도는 정수 스레드 수다")
            out[name] = int(value)
        else:
            out[name] = value
    return out


def parse_line(body: str, projects: set[str] | None = None) -> Todo:
    """줄 본문(앞의 "- " 없이)을 읽는다. projects가 있으면 첫 칸이 그 안에 있어야 한다. 틀리면 TodoError다."""
    cells = [_norm(c) for c in (body or "").split("|")]
    while cells and not cells[-1]:
        cells.pop()
    if not cells or not cells[0]:
        raise TodoError("프로젝트 이름이 없다")
    project = ALIASES.get(cells[0], cells[0].lower())
    if projects is not None and project not in projects:
        raise TodoError(f"등록부에 없는 프로젝트다 ({cells[0]})")
    if len(cells) < 2 or not cells[1]:
        raise TodoError("할 일 문장이 비었다")
    item = Todo(project=project, text=cells[1])
    cap = None
    for cell in cells[2:]:
        if not cell:
            continue
        if (rest := _named(cell, "cycle")) is not None:
            if item.cycle:
                raise TodoError("cycle 칸을 두 번 적었다")
            item.cycle = _parse_cycle(f"cycle {rest}")
        elif (rest := _named(cell, "한도")) is not None:
            if item.limits:
                raise TodoError("한도 칸을 두 번 적었다")
            item.limits = _parse_limits(rest)
        elif (rest := _named(cell, "상한")) is not None:
            if cap is not None:
                raise TodoError("상한을 두 번 적었다")
            cap = _parse_cap(rest)
        else:
            crit = re.sub(r"^기준\s*:\s*", "", cell)
            if item.criteria:
                raise TodoError("이름 없는 칸이 둘이다. 기준은 하나만 적고, 다른 칸은 cycle, 한도, 상한으로 시작한다")
            item.criteria = crit
    if cap is not None:
        if not item.cycle:
            raise TodoError("상한은 cycle 칸이 있는 줄에만 쓴다")
        if item.cycle.get("cap"):
            raise TodoError("상한을 두 번 적었다")
        item.cycle["cap"] = cap
    return item


def project_names() -> set[str]:
    from scheduler.registry import load_all

    return set(load_all())


def _read(path: Path) -> list[str] | None:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None


def _old_auto(head: str) -> bool:
    return re.sub(r"\s+", "", head).lower() == "auto"


def _merge_old_auto(lines: list[str]) -> list[str]:
    """옛 Auto 절 머리를 떼고 그 절의 글줄을 할 일 절 맨 위로 옮긴다. 옛 절이 없으면 그대로다(261029-jipsa-17)."""
    if not any((h := _HEAD.match(raw)) and _old_auto(h.group(1)) for raw in lines):
        return lines
    out, moved, inside = [], [], False
    for raw in lines:
        h = _HEAD.match(raw)
        if h:
            inside = _old_auto(h.group(1))
            if inside:
                continue
        if inside:
            if raw.strip():
                moved.append(raw)
            continue
        out.append(raw)
    head = next((i for i, raw in enumerate(out) if (h := _HEAD.match(raw)) and _section_of(h.group(1)) == TODO), None)
    if head is None:
        out += ["", f"## {TODO}", ""]
        head = len(out) - 2
    at = head + 2 if head + 1 < len(out) and not out[head + 1].strip() else head + 1
    out[at:at] = moved
    return out


def _write(path: Path, lines: list[str]) -> None:
    lines[:] = _merge_old_auto(lines)  # 부른 쪽이 이 목록을 다시 읽어 줄을 찾으므로 그 자리에서 바꾼다
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _scan(lines: list[str], projects: set[str] | None) -> tuple[list[Todo], list[tuple[int, str, str]]]:
    found: dict[str, list[Todo]] = {s: [] for s in SECTIONS}
    bad: list[tuple[int, str, str]] = []
    section = None
    for i, raw in enumerate(lines):
        h = _HEAD.match(raw)
        if h:
            section = _section_of(h.group(1))
            continue
        m = _ITEM.match(raw)
        if not section or section == MEMO or not m:
            continue
        try:
            item = parse_line(m.group(1), projects)
        except TodoError as e:
            bad.append((i, raw.strip(), str(e)))
            continue
        item.section, item.lineno = section, i
        found[section].append(item)
    items = found[TODO]
    for n, it in enumerate(items, 1):
        it.no = n
    return items, bad


def load(path: Path | None = None, projects: set[str] | None = None) -> tuple[list[Todo], list[tuple[int, str, str]], bool]:
    """(할 일 목록, 읽지 못한 줄(줄 번호, 원문, 이유), 파일이 있는지)를 돌려준다. 파일이 없으면 만들지 않는다."""
    path = path or TODO_FILE
    lines = _read(path)
    if lines is None:
        return [], [], False
    items, bad = _scan(lines, project_names() if projects is None else projects)
    return items, bad, True


def split_args(words: list[str]) -> tuple[str, str]:
    """명령 인자를 (프로젝트, 나머지 칸)으로 나눈다. 따옴표 없이 여러 인자로 와도 공백으로 합친다."""
    joined = _norm(" ".join(words or []))
    m = re.match(r"^([^\s|]+)\s*\|?\s*(.*)$", joined)
    if not m:
        return "", ""
    return m.group(1), m.group(2)


def add(project: str, rest: str, section: str = TODO, path: Path | None = None) -> Todo:
    """한 줄을 그 절 끝에 더한다. 등록부에 없는 프로젝트, 빈 문장, 칸 오류, 같은 프로젝트와 문장의 중복은 TodoError다."""
    path = path or TODO_FILE
    if section not in SECTIONS:
        raise TodoError(f"절은 {', '.join(SECTIONS)} 가운데 하나다")
    names = project_names()
    item = parse_line(f"{project} | {rest}", names)
    lines = _read(path)
    if lines is None:
        lines = TEMPLATE.splitlines()
    items, _ = _scan(lines, names)
    for it in items:
        if it.project == item.project and _norm(it.text) == _norm(item.text):
            raise TodoError(f"같은 줄이 이미 있다 ({it.no}번 {it.section})")
    _insert(lines, section, f"- {item.line()}")
    _write(path, lines)
    items, _ = _scan(lines, names)
    return next(it for it in items if it.key == item.key)


def _insert(lines: list[str], section: str, text: str, top: bool = False) -> int:
    """절의 맨 아래(마지막 글줄 뒤)나 맨 위(첫 할 일 줄 앞)에 한 줄을 넣는다. 절이 없으면 파일 끝에 만든다. 넣은 줄 번호다."""
    lines[:] = _merge_old_auto(lines)  # 옛 Auto 절에 넣지 않게 먼저 합친다
    head = next((i for i, raw in enumerate(lines) if (h := _HEAD.match(raw)) and _section_of(h.group(1)) == section), None)
    if head is None:
        lines += ["", f"## {section}"]
        head = len(lines) - 1
    end = next((i for i in range(head + 1, len(lines)) if _HEAD.match(lines[i])), len(lines))
    if top:
        at = next((i for i in range(head + 1, end) if _ITEM.match(lines[i])), None)
        if at is None:
            at = max([i + 1 for i in range(head + 1, end) if lines[i].strip()], default=head + 1)
    else:
        at = max([i + 1 for i in range(head + 1, end) if lines[i].strip()], default=head + 1)  # 절의 마지막 글줄 뒤
    lines.insert(at, text)
    if at + 1 < len(lines) and _HEAD.match(lines[at + 1]):
        lines.insert(at + 1, "")
    return at


def move(query: str, section: str, top: bool = False, path: Path | None = None, items: list[Todo] | None = None,
         key: str = "") -> Todo:
    """번호나 문장 일부로 고른 줄을 그 절의 맨 아래(top이면 맨 위)로 옮긴다. 줄 원문은 그대로 옮긴다. 옮긴 뒤의 줄이다.

    items를 주면 그 안에서만 고른다. 번호는 전체 목록의 번호다.
    key(프로젝트::문장)를 주면 query 대신 그 줄을 옮긴다. 끝난 Cycle 목표를 할 일 절 맨 아래로 돌릴 때 쓴다."""
    path = path or TODO_FILE
    lines = _read(path)
    if lines is None:
        raise TodoError("할 일 파일이 아직 없다")
    names = project_names()
    every, _ = _scan(lines, names)
    pool = every if items is None else [it for it in every if any(it.key == x.key for x in items)]
    if not key and query.strip().isdigit() and items is not None and not any(it.no == int(query) for it in pool):
        hit = [it for it in every if it.no == int(query)]
        if hit:
            raise TodoError(f"{query}번은 이미 {section} 절에 있다" if hit[0].section == section else f"{query}번은 {hit[0].section} 절의 줄이다")
    if key:
        item = next((it for it in pool if it.key == key), None)
        if item is None:
            raise TodoError(f"줄이 없다 ({key})")
    else:
        item = find(query, pool)
    raw = lines[item.lineno]
    del lines[item.lineno]
    _insert(lines, section, raw.strip() if raw.strip().startswith("- ") else f"- {item.line()}", top=top)
    _write(path, lines)
    after, _ = _scan(lines, names)
    return next(it for it in after if it.key == item.key and it.section == section)


def take(key: str, path: Path | None = None) -> Todo | None:
    """프로젝트::문장 key의 줄을 파일에서 뺀다. 시작한 일회성 줄을 뺄 때 쓴다. 없으면 None이다."""
    path = path or TODO_FILE
    lines = _read(path)
    if lines is None:
        return None
    items, _ = _scan(lines, project_names())
    hit = next((it for it in items if it.key == key), None)
    if hit is None:
        return None
    del lines[hit.lineno]
    _write(path, lines)
    return hit


def set_criteria(key: str, criteria: str, path: Path | None = None) -> Todo:
    """프로젝트::문장 key의 줄에 기준 칸을 적는다(있으면 바꾼다). 줄은 제자리에 둔다. 기획 단계의 답을 적을 때 쓴다."""
    path = path or TODO_FILE
    lines = _read(path)
    if lines is None:
        raise TodoError("할 일 파일이 아직 없다")
    names = project_names()
    items, _ = _scan(lines, names)
    hit = next((it for it in items if it.key == key), None)
    if hit is None:
        raise TodoError(f"줄이 없다 ({key})")
    hit.criteria = re.sub(r"^기준\s*:\s*", "", _norm(criteria).replace("|", "/"))
    if not hit.criteria:
        raise TodoError("기준이 비었다")
    lines[hit.lineno] = f"- {hit.line()}"
    _write(path, lines)
    return hit


def find(query: str, items: list[Todo]) -> Todo:
    """번호나 문장 일부로 한 줄을 고른다. 없거나 여러 줄에 걸리면 TodoError다. 문장과 똑같으면 그 줄이 먼저다."""
    q = _norm(query)
    if not q:
        raise TodoError("번호나 문장 일부가 필요하다")
    if q.isdigit():
        hit = [it for it in items if it.no == int(q)]
        if not hit:
            raise TodoError(f"{q}번 줄이 없다 (지금 {len(items)}줄)")
        return hit[0]
    low = q.lower()
    exact = [it for it in items if _norm(it.text).lower() == low]
    if len(exact) == 1:
        return exact[0]
    hit = [it for it in items if low in _norm(it.text).lower()]
    if not hit:
        raise TodoError(f"맞는 줄이 없다 (문장 일부 {q})")
    if len(hit) > 1:
        raise TodoError(f"문장 일부 {q}에 {len(hit)}줄이 걸린다 ({', '.join(f'{it.no}번' for it in hit)}). 번호나 더 긴 문장 일부로 고른다")
    return hit[0]


def remove(query: str, path: Path | None = None) -> Todo:
    """번호나 문장 일부로 고른 줄 하나를 뺀다. 파일이 없으면 TodoError다."""
    path = path or TODO_FILE
    lines = _read(path)
    if lines is None:
        raise TodoError("할 일 파일이 아직 없다")
    items, _ = _scan(lines, project_names())
    item = find(query, items)
    del lines[item.lineno]
    _write(path, lines)
    return item


# ----- 메모 절(261025-jipsa-36) -----
@dataclass
class Memo:
    text: str
    lineno: int = -1  # 파일 안 줄 번호(0부터)
    no: int = 0  # 메모 번호(1부터, 메모끼리)

    @property
    def label(self) -> str:
        return f"m{self.no}"


def _memo_scan(lines: list[str]) -> list[Memo]:
    out: list[Memo] = []
    section = None
    for i, raw in enumerate(lines):
        h = _HEAD.match(raw)
        if h:
            section = _section_of(h.group(1))
            continue
        m = _ITEM.match(raw)
        if section == MEMO and m and _norm(m.group(1)):
            out.append(Memo(text=_norm(m.group(1)), lineno=i, no=len(out) + 1))
    return out


def memos(path: Path | None = None) -> list[Memo]:
    """메모 절의 줄. 파일이 없으면 빈 목록이다."""
    lines = _read(path or TODO_FILE)
    return _memo_scan(lines) if lines is not None else []


def memo_find(query: str, items: list[Memo]) -> Memo:
    """번호(1이나 m1)나 글 일부로 메모 한 줄을 고른다. 없거나 여러 줄에 걸리면 TodoError다. 글과 똑같으면 그 줄이 먼저다."""
    q = _norm(query)
    if not q:
        raise TodoError("메모 번호나 글 일부가 필요하다")
    if re.fullmatch(r"[mM]?\d+", q):
        n = int(q.lstrip("mM"))
        hit = [it for it in items if it.no == n]
        if not hit:
            raise TodoError(f"메모 {n}번이 없다 (지금 메모 {len(items)}줄)")
        return hit[0]
    low = q.lower()
    exact = [it for it in items if it.text.lower() == low]
    if len(exact) == 1:
        return exact[0]
    hit = [it for it in items if low in it.text.lower()]
    if not hit:
        raise TodoError(f"맞는 메모가 없다 (글 일부 {q})")
    if len(hit) > 1:
        raise TodoError(f"글 일부 {q}에 메모 {len(hit)}줄이 걸린다 ({', '.join(it.label for it in hit)}). 번호나 더 긴 글 일부로 고른다")
    return hit[0]


def memo_add(text: str, path: Path | None = None) -> Memo:
    """메모 절 끝에 자유 글 한 줄을 더한다. 빈 글과 같은 글의 중복은 TodoError다. 파일이 없으면 양식으로 만든다."""
    path = path or TODO_FILE
    body = _norm(text)
    if not body:
        raise TodoError("메모 글이 비었다")
    lines = _read(path)
    if lines is None:
        lines = TEMPLATE.splitlines()
    for it in _memo_scan(lines):
        if it.text == body:
            raise TodoError(f"같은 메모가 이미 있다 ({it.label})")
    _insert(lines, MEMO, f"- {body}")
    _write(path, lines)
    return next(it for it in reversed(_memo_scan(lines)) if it.text == body)


def memo_remove(query: str, path: Path | None = None) -> Memo:
    """번호나 글 일부로 고른 메모 한 줄을 뺀다."""
    path = path or TODO_FILE
    lines = _read(path)
    if lines is None:
        raise TodoError("할 일 파일이 아직 없다")
    item = memo_find(query, _memo_scan(lines))
    del lines[item.lineno]
    _write(path, lines)
    return item


def split_promote(words: list[str], projects: set[str]) -> tuple[str, str, str]:
    """`up` 인자를 (메모 고르기, 프로젝트, 덧붙일 칸)으로 나눈다. 첫 세로 막대 앞이 '<번호|글 일부> [프로젝트]'이고 뒤가 칸이다.

    번호로 고르면 번호 뒤 낱말이 프로젝트다. 글 일부로 고르면 마지막 낱말이 등록부 이름일 때만 프로젝트로 뗀다."""
    joined = _norm(" ".join(words or []))
    head, _, cells = joined.partition("|")
    toks = head.split()
    if not toks:
        return "", "", _norm(cells)
    if re.fullmatch(r"[mM]?\d+", toks[0]):
        return toks[0], " ".join(toks[1:]), _norm(cells)
    last = toks[-1]
    if len(toks) > 1 and ALIASES.get(last, last.lower()) in projects:
        return " ".join(toks[:-1]), last, _norm(cells)
    return " ".join(toks), "", _norm(cells)


def promote(query: str, project: str = "", rest: str = "", path: Path | None = None) -> tuple[Memo, Todo]:
    """메모 한 줄을 할 일 절 끝으로 올린다. 메모에서 빠지고 할 일 줄(프로젝트 | 메모 글 | rest)로 들어간다.

    메모 글이 이미 '프로젝트 | 할 일 ..' 꼴로 읽히면 그 줄을 그대로 받는다. 그때 다른 프로젝트나 덧붙일 칸을 주면 거절한다.
    프로젝트가 없거나 등록부에 없으면, 칸 오류와 같은 줄 중복이면 TodoError이고 파일은 그대로다."""
    path = path or TODO_FILE
    lines = _read(path)
    if lines is None:
        raise TodoError("할 일 파일이 아직 없다")
    names = project_names()
    memo = memo_find(query, _memo_scan(lines))
    whole = None
    if "|" in memo.text:
        try:
            whole = parse_line(memo.text, names)
        except TodoError:
            whole = None
    if whole is not None:
        if project and ALIASES.get(project, project.lower()) != whole.project:
            raise TodoError(f"메모에 이미 프로젝트({whole.project})가 있다. 프로젝트 없이 올리면 그대로 받는다")
        if rest:
            raise TodoError("메모에 이미 칸이 있다. 덧붙일 칸 없이 올리면 그대로 받는다")
        item = whole
    else:
        if not project:
            raise TodoError(f"프로젝트가 없다. 할 일 줄은 프로젝트가 있어야 한다. jipsa todo up {memo.label} <프로젝트> | <기준>으로 올린다")
        text = _norm(memo.text.replace("|", "/"))
        item = parse_line(" | ".join(x for x in (project, text, rest) if x), names)
    every, _ = _scan(lines, names)
    for it in every:
        if it.project == item.project and _norm(it.text) == _norm(item.text):
            raise TodoError(f"같은 줄이 이미 있다 ({it.no}번 {it.section})")
    del lines[memo.lineno]
    _insert(lines, TODO, f"- {item.line()}")
    _write(path, lines)
    after, _ = _scan(lines, names)
    return memo, next(it for it in after if it.key == item.key)


# ----- cycle 칸 바꾸기(261025-jipsa-49) -----
CYCLE_OFF = ("off", "끄기", "해제", "없음")  # cycle 칸을 비우는 낱말
CYCLE_USAGE = ("jipsa todo cycle <번호|문장 일부> [<지표>] [<목표값>] [이상|이하] [상한 N] [도달하면 끝], 비운 칸은 첫 분석이 정한다. "
               "비우려면 jipsa todo cycle <번호> off")


def split_cycle(words: list[str]) -> tuple[str, list[str]]:
    """`cycle` 인자를 (줄 고르기, 나머지 낱말)로 나눈다. 세로 막대가 있으면 그 앞이 고르기이고(여러 낱말 문장 일부),
    없으면 첫 낱말이다. 스킬은 인자 전체를 따옴표 하나로 넘기므로 인자 경계가 아니라 낱말로 가른다."""
    joined = _norm(" ".join(words or []))
    if "|" in joined:
        head, _, tail = joined.partition("|")
        return _norm(head), tail.split()
    toks = joined.split()
    return (toks[0], toks[1:]) if toks else ("", [])


FEEDBACK_USAGE = "jipsa todo feedback <번호|문장 일부> | <글>"


def split_feedback(words: list[str]) -> tuple[str, str]:
    """`feedback` 인자를 (줄 고르기, 글)로 나눈다. 첫 낱말이 번호면 나머지가 글이고, 아니면 세로 막대 앞이 고르기다. 글은 공백을 고치지 않고 앞뒤만 다듬는다."""
    joined = " ".join(words or []).strip()
    first, _, rest = joined.partition(" ")
    if first.isdigit():
        query, text = first, rest.strip()
        return query, text[1:].strip() if text.startswith("|") else text
    if "|" in joined:
        head, _, tail = joined.partition("|")
        return _norm(head), tail.strip()
    return "", ""


def feedback_target(query: str, path: Path | None = None) -> Todo:
    """피드백을 받을 줄. cycle 칸이 있는 줄만 받는다(피드백은 도는 Cycle 목표의 다음 분석과 명령에 들어간다)."""
    items, _, _ = load(path)
    item = find(query, items)
    if not item.cycle:
        raise TodoError(f"{item.no}번에는 cycle 칸이 없다. 피드백은 Cycle 목표에만 넣는다. jipsa todo cycle {item.no}로 먼저 켠다")
    return item


def cycle_cell(tokens: list[str]) -> dict | None:
    """'[<지표>] [<목표값>] [이상|이하] [상한 N] [도달하면 끝]' 낱말을 cycle 칸으로 읽는다. off 꼴이면 None이다.

    끝에서부터 도달하면 끝, 상한 N, 방향, 목표값(숫자와 단위)을 떼고 남은 낱말이 지표다. 지표나 목표값이 없으면 그 칸을 비운
    목표 미정 칸이고 Cycle 1 분석이 채운다(261026-jipsa-11). 방향은 목표값이 있을 때만 이상이 기본이고, 목표값이 비면 적었을 때만 둔다.
    만든 칸을 줄 읽기로 다시 읽어 같은 값인지 본다."""
    toks = list(tokens or [])
    if len(toks) == 1 and toks[0].lower() in CYCLE_OFF:
        return None
    stop = False
    if toks and toks[-1] in ("끝", "도달하면끝"):
        if toks[-1] == "끝" and len(toks) >= 2 and toks[-2] == "도달하면":
            toks, stop = toks[:-2], True
        elif toks[-1] == "도달하면끝":
            toks, stop = toks[:-1], True
    cap = None
    if len(toks) >= 2 and toks[-2] == "상한":
        cap = _parse_cap(toks[-1])
        toks = toks[:-2]
    direction = ""
    if toks and toks[-1] in ("이상", "이하"):
        direction = toks.pop()
    target = unit = ""
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)([^\s\d|]*)", toks[-1]) if toks else None
    if m:
        target, unit = m.group(1), m.group(2)
        toks.pop()
        if not direction and unit.endswith(("이상", "이하")):  # 50이상처럼 붙여 쓴 꼴
            direction, unit = unit[-2:], unit[:-2]
    elif toks[-2:] == ["목표", PENDING]:
        toks = toks[:-2]
    if toks in (["지표", PENDING], [PENDING]):
        toks = []
    elif not target and toks[-1:] == [PENDING]:  # '점수 미정'처럼 목표값 자리에 미정만 적은 꼴
        toks = toks[:-1]
    metric = _norm(" ".join(toks).replace("|", "/"))
    if re.fullmatch(rf"(?:\d+(?:\.\d+)?|{PENDING})", metric):
        raise TodoError(f"지표 '{metric}'를 읽지 못했다. 무엇을 잴지 글로 적거나 비운다")
    cyc = {"metric": metric, "target": target, "unit": unit, "dir": direction or ("이상" if target else ""), "cap": cap, "stop": stop}
    got = _parse_cycle(cycle_text(cyc))
    if got != cyc:
        raise TodoError(f"'{cycle_text(cyc)}'이 다르게 읽힌다. 지표 끝의 숫자를 글로 바꿔 적는다")
    return cyc


def set_cycle(query: str, cyc: dict | None, path: Path | None = None, busy: set[str] | None = None) -> tuple[Todo, dict | None]:
    """번호나 문장 일부로 고른 줄의 cycle 칸을 cyc로 바꾼다(None이면 비운다). (바꾼 뒤의 줄, 옛 cycle 칸)이다.

    줄은 제자리에 두고 다른 칸은 그대로다. busy(도는 줄의 key)에 든 줄과 비울 칸이 없는 줄은 TodoError이고 파일은 그대로다."""
    path = path or TODO_FILE
    lines = _read(path)
    if lines is None:
        raise TodoError("할 일 파일이 아직 없다")
    names = project_names()
    items, _ = _scan(lines, names)
    item = find(query, items)
    if busy and item.key in busy:
        raise TodoError(f"{item.no}번은 도는 중이다. 끝나거나 멈춘 뒤 바꾼다")
    old = dict(item.cycle) if item.cycle else None
    if cyc is None and old is None:
        raise TodoError(f"{item.no}번에는 비울 cycle 칸이 없다")
    item.cycle = dict(cyc) if cyc else None
    lines[item.lineno] = f"- {item.line()}"
    _write(path, lines)
    after, _ = _scan(lines, names)
    return next(it for it in after if it.key == item.key), old


def fill_cycle(key: str, goal: dict, path: Path | None = None) -> tuple[Todo | None, list[str]]:
    """목표 미정 cycle 칸의 빈 칸만 goal(metric, target, unit, dir, cap)로 채운다(261026-jipsa-11). Cycle 1 분석이 정한 값을 jipsa가 적는다.
    사람이 적은 칸은 덮지 않는다. 방향은 사람이 목표값을 비웠고 방향도 적지 않았을 때만 채운다.
    상한은 채우지 않는다. 사람이 비운 상한은 비운 채 두고 마감까지 돈다(261029-jipsa-03 1안).
    도는 줄도 받는다(부르는 쪽이 jipsa다). (바꾼 뒤의 줄, 채운 칸 이름)이고 줄이 없으면 (None, [])다.
    채운 칸이 줄 읽기로 다르게 읽히면 TodoError이고 파일은 그대로다."""
    path = path or TODO_FILE
    lines = _read(path)
    if lines is None:
        return None, []
    names = project_names()
    items, _ = _scan(lines, names)
    item = next((it for it in items if it.key == key), None)
    if item is None or not item.cycle:
        return None, []
    cy, filled = dict(item.cycle), []
    if not cy.get("metric") and str(goal.get("metric") or "").strip():
        cy["metric"] = _norm(str(goal["metric"]).replace("|", "/"))
        filled.append("지표")
    if not cy.get("target") and goal.get("target") not in (None, ""):
        cy["target"], cy["unit"] = f"{float(goal['target']):g}", re.sub(r"[\s|]+", "", str(goal.get("unit") or ""))
        filled.append("목표값")
        if not cy.get("dir"):
            cy["dir"] = goal.get("dir") if goal.get("dir") in ("이상", "이하") else "이상"
            filled.append("방향")
    if not filled:
        return item, []
    if _parse_cycle(cycle_text(cy)) != cy:
        raise TodoError(f"'{cycle_text(cy)}'이 다르게 읽힌다. 지표 끝의 숫자를 글로 바꿔 적는다")
    item.cycle = cy
    lines[item.lineno] = f"- {item.line()}"
    _write(path, lines)
    after, _ = _scan(lines, names)
    return next(it for it in after if it.key == item.key), filled
