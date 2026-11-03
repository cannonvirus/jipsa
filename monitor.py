"""jipsa 서비스를 켜고 끄는 콘솔 모니터(261024-jipsa-23).

    python monitor.py

메뉴 위에 서비스마다 상태(떠 있음, PID, 포트, 주소)를 보이고, 대시보드와 스케줄러는 하나의 단축키로 함께 켜기,
끄기, 다시 켜기를 하며 서비스마다 로그가 있다. 서비스 목록과 묶음은 scheduler/services.toml 한 곳에 있다.
켜고 끄는 일은 scheduler/monitor.py가 한다. 끄면 대시보드 감시가 스케줄러를 다시 띄우지 않게 멈춤을 적고, 켜면 푼다. 서비스는 창 없는 분리 프로세스로 뜨므로 이 창을 닫아도 계속 돈다.

**어떤 파이썬으로 켜든 가상환경에서 돈다.** 가상환경 밖의 파이썬으로 켜면 가상환경의 파이썬으로 이 파일을 다시
실행한다. 서비스도 그 파이썬으로 뜬다.

**단축키는 손으로 붙이지 않는다.** `_menu_layout()`에 적힌 순서대로 위에서부터 a, b, c가 붙고, 화면 출력과 입력
처리가 같은 표에서 나온다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def venv_python() -> Path | None:
    """가상환경의 파이썬. worktree에서 켜면 본 저장소의 가상환경을 쓴다."""
    roots = [ROOT]
    if ROOT.parent.name == "worktrees":
        roots.append(ROOT.parent.parent)
    for root in roots:
        for candidate in (root / ".venv" / "Scripts" / "python.exe", root / ".venv" / "bin" / "python"):
            if candidate.exists():
                return candidate
    return None


def _in_venv(py: Path) -> bool:
    return Path(sys.prefix).resolve() == py.parent.parent.resolve()


if __name__ == "__main__" and (_py := venv_python()) and not _in_venv(_py):
    sys.exit(subprocess.call([str(_py), str(Path(__file__).resolve()), *sys.argv[1:]], cwd=str(ROOT)))

# sys.path에 루트를 넣은 뒤라야 import된다 (monitor.py는 패키지 밖에 있다)
sys.path.insert(0, str(ROOT))

import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime

from scheduler import monitor as svc

_LOG_LINES = (40, 300)  # 로그 화면의 끝줄 수. l로 바꾼다
_LINE = 72


def _wait() -> None:
    input("\n엔터를 누르면 메뉴로 돌아갑니다...")


def _width(text: str) -> int:
    """터미널에서 차지하는 칸 수. 한글과 전각은 두 칸이다."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _pad(text: str, cells: int) -> str:
    return text + " " * max(cells - _width(text), 0)


def _clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


# --- 동작 ---


def _label(name: str) -> str:
    return next((s.get("label", name) for s in svc.services() if s["name"] == name), name)


def _act_group(group: str, action: str) -> None:
    """묶음 전체를 켜고, 끄고, 다시 켠다. 실행 중 작업이 있으면 묻지 않고 거절한다."""
    g = next(x for x in svc.groups() if x["name"] == group)
    rows = {s["name"]: s for s in svc.state()}
    running = sum(rows[n]["running"] for n in g["members"])
    word = {"start": "켜기", "stop": "끄기", "restart": "다시 켜기"}[action]
    print(f"\n{g['label']} {word}")
    print("-" * _LINE)
    if action != "start" and running:
        print(f"  실행 중 작업 {running}개가 있어 거절합니다. 작업이 끝난 뒤에 다시 고르세요.")
        _wait()
        return
    print("  하는 중...")
    print(f"  {svc.act_group(group, action)['message']}")
    after = {s["name"]: s for s in svc.state()}
    for n in g["members"]:
        print(f"  지금: {_label(n)} {_status_word(after[n])}  PID {', '.join(map(str, after[n]['pids'])) or '-'}")
    _wait()


def show_log(name: str) -> None:
    """고른 서비스의 로그 끝을 보인다. 1, 2, 3으로 서비스를 바꾸고, l로 줄 수를 바꾸고, r로 새로 읽는다."""
    names = [s["name"] for s in svc.services()]
    lines = _LOG_LINES[0]
    while True:
        _clear()
        d = svc.log_tail(name, lines)
        print(f"로그 — {_label(name)} 끝 {len(d['lines'])}줄 ({Path(d['path']).name})")
        print("=" * _LINE)
        if d["missing"]:
            print("  아직 로그가 없습니다. Monitor나 대시보드가 띄운 뒤에 생깁니다.")
        for line in d["lines"]:
            print(f"  {line}")
        print("=" * _LINE)
        keys = "   ".join(f"{i}. {_label(n)}" for i, n in enumerate(names, start=1))
        other = _LOG_LINES[1] if lines == _LOG_LINES[0] else _LOG_LINES[0]
        choice = input(f"  {keys}   l. {other}줄   r. 새로 읽기   엔터 메뉴 > ")
        choice = choice.strip().lower()
        if choice.isdigit() and 1 <= int(choice) <= len(names):
            name = names[int(choice) - 1]
        elif choice == "l":
            lines = _LOG_LINES[1] if lines == _LOG_LINES[0] else _LOG_LINES[0]
        elif choice != "r":
            return


class _Quit(Exception):
    """종료를 골랐다. `main`이 잡는다."""


def run_quit() -> None:
    raise _Quit


# --- 메뉴 ---
#
# 화면과 처리가 같은 표에서 나온다. 서비스 하나가 한 묶음이고, 묶음마다 켜기, 끄기, 다시 켜기, 로그를 한 줄에 둔다.


@dataclass(frozen=True)
class Item:
    label: str
    run: Callable[[], None]
    note: str = ""
    key: str = ""  # _build_menu가 채운다. 고정 키가 필요하면 여기 적는다


@dataclass(frozen=True)
class Group:
    """구분선으로 갈리는 한 묶음. `title`은 줄 앞에 붙는 이름이고 `cols`는 한 줄에 몇 개씩 늘어놓을지다."""

    items: tuple[Item, ...]
    cols: int = 1
    title: str = ""


def _bundle_group(g: dict) -> Group:
    """묶음 하나가 켜기, 끄기, 다시 켜기를 한 줄로 가진다. 묶음의 서비스는 한 단축키로 함께 움직인다."""
    name = g["name"]
    return Group(
        (
            Item("켜기", lambda: _act_group(name, "start")),
            Item("끄기", lambda: _act_group(name, "stop")),
            Item("다시 켜기", lambda: _act_group(name, "restart")),
        ),
        cols=3,
        title=g["label"],
    )


def _log_group() -> Group:
    return Group(tuple(Item(f"{s.get('label', s['name'])} 로그", lambda n=s["name"]: show_log(n)) for s in svc.services()), cols=4, title="로그")


def _menu_layout() -> tuple[Group, ...]:
    return (
        *(_bundle_group(g) for g in svc.groups()),
        _log_group(),
        Group((Item("모니터 종료", run_quit, "켠 서비스는 계속 돈다", key="0"),)),
    )


_KEYS = "abcdefghijklmnopqrstuvwxyz"


def _build_menu() -> tuple[Group, ...]:
    """자리 순서대로 단축키를 붙인다. `key`가 이미 적힌 항목은 그대로 둔다."""
    letters = iter(_KEYS)
    groups = []
    for group in _menu_layout():
        items = tuple(it if it.key else replace(it, key=next(letters)) for it in group.items)
        groups.append(replace(group, items=items))
    return tuple(groups)


def _status_word(s: dict) -> str:
    return "떠 있음" if s["up"] else "꺼짐"


def _print_state(rows: list[dict]) -> None:
    """서비스마다 상태, PID, 포트, 주소를 표처럼 늘어놓는다. 주소는 떠 있을 때만 보인다. 열 폭은 칸 수로 잰다."""
    table = [("서비스", "상태", "PID", "포트", "주소")]
    for s in rows:
        url = s["url"] if s["up"] and s["url"] else "-"
        table.append((s["label"], _status_word(s), ", ".join(map(str, s["pids"])) or "-", str(s["port"] or "-"), url))
    widths = [max(_width(r[c]) for r in table) + 3 for c in range(4)]
    for r in table:
        print("   " + "".join(_pad(cell, widths[i]) for i, cell in enumerate(r[:4])) + r[4])


def _title_width(menu: tuple[Group, ...]) -> int:
    return max((_width(g.title) for g in menu if g.title), default=0) + 3


def _print_group(group: Group, title_cells: int) -> None:
    cells = [f"{it.key}. {it.label}" for it in group.items]
    if group.cols == 1:
        for it, cell in zip(group.items, cells):
            print(f"   {_pad(cell, 16)}{it.note}".rstrip())
        return
    rows = [cells[i : i + group.cols] for i in range(0, len(cells), group.cols)]
    head = _pad(group.title, title_cells)
    for row in rows:
        print("   " + head + "".join(_pad(c, _width(c) + 4) for c in row).rstrip())
        head = " " * title_cells


def print_menu(menu: tuple[Group, ...]) -> None:
    _clear()
    rows = svc.state()
    print("=" * _LINE)
    print("   JIPSA MONITOR")
    print("=" * _LINE)
    print(f"   {datetime.now():%Y-%m-%d %H:%M:%S}   엔터를 누르면 상태를 새로 읽습니다")
    for s in rows:
        if s["note"]:
            print(f"   ⚠️  {s['label']}: {s['note']}")
    print("-" * _LINE)
    _print_state(rows)
    title_cells = _title_width(menu)
    for group in menu:
        print("-" * _LINE)
        _print_group(group, title_cells)
    print("=" * _LINE)


def main() -> None:
    if os.name == "nt":
        os.system("title jipsa Monitor")
    menu = _build_menu()
    actions: dict[str, Item] = {it.key: it for g in menu for it in g.items}
    while True:
        print_menu(menu)
        choice = input(" 선택 > ").strip().lower()
        if not choice:
            continue
        item = actions.get(choice)
        if item is None:
            print("\n잘못된 입력입니다.")
            time.sleep(1.5)
            continue
        try:
            item.run()
        except _Quit:
            return


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # 윈도우 콘솔 한글 깨짐 방지
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\n모니터를 닫습니다. 켠 서비스는 계속 돕니다.")
