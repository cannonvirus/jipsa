"""등록 toml을 고치고 새로 만든다(261102-jipsa-28에서 시작, 261102-jipsa-34에서 /jipsa-register 스킬과 jipsa registry 명령용으로 바꿨다).

고칠 수 있는 등록 칸 19개만 다룬다. 쓰기는 줄 단위다. 바뀐 키의 값 글자만 바꾸고 주석, 빈 줄, 키 순서, 따옴표 꼴은
그대로 둔다. 없는 키는 그 표의 마지막 값 줄 뒤에 한 줄로 더하고, 없는 표는 파일 끝에 더한다. 고친 뒤 다시 읽어 바뀐 칸 말고
달라진 값이 없을 때만 쓴다. 이름은 파일 이름과 같아야 하므로 새로 등록할 때만 정하고 있는 등록에서는 잠근다.
목록 칸은 한 줄에 하나씩 받는다. 사람 승인 문구가 드는 칸(scope.notes, questions.items)은 jipsa registry add만 쓴다.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path

from scheduler.config import DEFAULT_SEGMENT_MIN, DEFAULT_TOTAL_MIN, PROJECTS, ROOT, now
from scheduler.regline import LineError, _array_end
from scheduler.registry import KINDS, WORKER_PROVIDERS, RegistryError, _load_one

# 칸 하나는 (표, 키, 형식, 한글 이름, 설명, 선택). 표가 빈 글자면 맨 위 키다. 형식은 str, path, int, float, bool, list, choice다
F = dict
FIELDS: list[dict] = [
    F(sec="", key="name", kind="str", name="이름", desc="등록 파일 이름과 같다. 영문 소문자, 숫자, 밑줄만 쓰고 등록할 때만 정한다.", required=True, create_only=True),
    F(sec="", key="path", kind="path", name="경로", desc="작업할 저장소 폴더다.", required=True),
    F(sec="", key="kind", kind="choice", name="종류", desc="code, doc, experiment, hardware, game 가운데 하나다. 시간 상한 기본값과 worktree 사용이 이 값을 따른다.", options=sorted(KINDS), required=True),
    F(sec="", key="priority", kind="int", name="우선순위", desc="작을수록 먼저 고른다. 기본 50이다.", default=50, min=0, max=999),
    F(sec="worker", key="provider", kind="choice", name="작업자 종류", desc="claude 또는 codex다. 할 일 줄의 worker가 앞선다.", options=sorted(WORKER_PROVIDERS), default="claude"),
    F(sec="worker", key="model", kind="str", name="작업자 모델", desc="비우면 전역 작업자 모델을 쓴다.", default=""),
    F(sec="scope", key="auto", kind="str", name="자동 범위", desc="사람 없이 할 수 있는 일의 범위를 한 문장으로 적는다. 작업자 지시문에 들어간다.", default=""),
    F(sec="scope", key="commit", kind="bool", name="커밋", desc="자동 작업이 기능 브랜치에 커밋까지 할지다. doc 종류는 기본 꺼짐이다.", default=None),
    F(sec="scope", key="manual_only", kind="bool", name="세션 전용", desc="켜면 스케줄러가 자동 작업 대상으로 고르지 않고 세션 기록만 받는다.", default=False),
    F(sec="scope", key="allowed_dirs", kind="list", name="새 파일 허용 폴더", desc="doc 종류에서 새 파일을 만들 수 있는 폴더다. 한 줄에 하나씩 적는다.", default=[]),
    F(sec="paths", key="no_read", kind="list", name="읽기 금지 경로", desc="작업자가 읽지 못하는 경로다. 한 줄에 하나씩 적는다.", default=[]),
    F(sec="paths", key="read_only", kind="list", name="읽기 전용 경로", desc="작업자가 읽기만 하고 고치지 못하는 경로다. 한 줄에 하나씩 적는다.", default=[]),
    F(sec="external", key="read", kind="list", name="외부 읽기 허용", desc="허용하는 외부 읽기 호출을 한 줄에 하나씩 적는다.", default=[]),
    F(sec="external", key="forbid", kind="list", name="외부 금지", desc="금지하는 외부 호출을 한 줄에 하나씩 적는다.", default=[]),
    F(sec="resources", key="gpu_vram_gb", kind="float", name="GPU 요구량", desc="작업 하나가 잡는 GPU 메모리(GB)다. 0이면 GPU를 쓰지 않는다.", default=0, min=0, max=200, unit="GB"),
    F(sec="resources", key="ram_gb", kind="float", name="RAM 요구량", desc="작업 하나가 잡는 RAM(GB)이다. 0이면 전역 기본값을 쓴다.", default=0, min=0, max=1000, unit="GB"),
    F(sec="resources", key="ollama_models", kind="list", name="Ollama 모델", desc="작업이 로드하는 Ollama 모델 이름이다. 한 줄에 하나씩 적는다.", default=[]),
    F(sec="limits", key="total_minutes", kind="int", name="총 상한", desc="작업 하나의 총 시간 상한(분)이다. 비우면 종류별 기본값이다.", default=None, min=5, max=1440, unit="분"),
    F(sec="limits", key="segment_minutes", kind="int", name="구간 상한", desc="호출 하나의 시간 상한(분)이다. 비우면 종류별 기본값이다.", default=None, min=5, max=240, unit="분"),
]
_BY_ID = {(f["sec"], f["key"]): f for f in FIELDS}
_NAME_RE = re.compile(r"^[a-z0-9_]{1,40}$")
_HEADER = re.compile(r"^[ \t]*\[\[?([A-Za-z0-9_.\" -]+)\]\]?[ \t]*(?:#.*)?$", re.MULTILINE)
# 새 등록의 표 순서. 있는 등록들과 같은 순서로 쓴다
_ALWAYS = {"paths.generated", "limits"}  # 값이 없어도 머리 줄을 둔다. 있는 등록들과 같은 표 9개를 갖춘다
_ORDER = ["scope", "paths", "paths.generated", "links", "external", "resources", "limits", "deps", "questions", "worker"]


def field_id(f: dict) -> str:
    return f"{f['sec']}.{f['key']}" if f["sec"] else f["key"]


def _split_id(fid: str) -> tuple[str, str]:
    sec, _, key = fid.rpartition(".")
    return sec, key


def version_of(path: Path) -> str:
    try:
        st = path.stat()
        return f"{st.st_mtime_ns}-{st.st_size}"
    except OSError:
        return ""


# ----- 읽기 -----
def _value(data: dict, f: dict):
    sec = data if not f["sec"] else data.get(f["sec"]) or {}
    return sec.get(f["key"]) if isinstance(sec, dict) else None


def _text(f: dict, val) -> str:
    """사람에게 보이는 글자. 목록은 줄로 나눈다."""
    if val is None:
        return ""
    if f["kind"] == "bool":
        return "1" if val else "0"
    if f["kind"] == "list":
        return "\n".join(str(x) for x in val)
    if isinstance(val, float) and val.is_integer():
        return str(int(val))
    return str(val)


def fields_view(project: str) -> dict:
    """등록 한 장의 고칠 칸 19개. 값이 없는 칸은 빈 글자와 기본값 설명이다."""
    path = PROJECTS / f"{project}.toml"
    if not path.exists():
        return {"ok": False, "why": f"등록에 {project}가 없다"}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"ok": False, "why": f"등록를 읽지 못했다: {e}"}
    kind = str(data.get("kind", ""))
    rows = []
    for f in FIELDS:
        val = _value(data, f)
        present = val is not None
        default = f.get("default")
        if f["key"] == "commit":
            default = kind != "doc"
        if f["sec"] == "limits" and default is None:
            default = (DEFAULT_TOTAL_MIN if f["key"] == "total_minutes" else DEFAULT_SEGMENT_MIN).get(kind)
        rows.append({"id": field_id(f), "sec": f["sec"], "key": f["key"], "kind": f["kind"], "name": f["name"], "desc": f["desc"],
                     "value": _text(f, val), "present": present, "default": _text(f, default) if default is not None else "", "editable": not f.get("create_only"),
                     "options": f.get("options") or [], "min": f.get("min"), "max": f.get("max"), "unit": f.get("unit", ""), "required": bool(f.get("required"))})
    return {"ok": True, "project": project, "version": version_of(path), "file": str(path), "fields": rows}


def find_field(token: str) -> dict | None:
    """칸 id(scope.auto)나 한글 이름(자동 범위)으로 칸을 찾는다."""
    token = token.strip()
    for f in FIELDS:
        if token in (field_id(f), f["name"]):
            return f
    return None


# ----- 값 검사 -----
def normalize(f: dict, value) -> tuple[object, str]:
    """명령에서 받은 글자를 toml 값으로 맞춘다. (값, 오류)다. 값이 None이면 그 키를 지운다(기본값으로 돌아간다)."""
    kind = f["kind"]
    if kind == "list":
        items = [s.strip() for s in str(value if value is not None else "").replace("\r", "").split("\n")]
        items = [s for s in items if s]
        return items, ""
    text = str(value if value is not None else "").strip()
    if text == "":
        if f.get("required"):
            return None, f"{f['name']}은(는) 비울 수 없다"
        return None, ""
    if kind == "bool":
        low = text.lower()
        if low in ("1", "true", "on", "켜짐", "예", "yes", "y"):
            return True, ""
        if low in ("0", "false", "off", "꺼짐", "아니오", "no", "n"):
            return False, ""
        return None, f"{f['name']}은(는) 예 또는 아니오여야 한다: {text}"
    if kind in ("int", "float"):
        try:
            num = int(text) if kind == "int" else float(text)
        except ValueError:
            return None, f"{f['name']}은(는) 숫자여야 한다: {text}"
        if f.get("min") is not None and num < f["min"]:
            return None, f"{f['name']}은(는) {f['min']} 이상이어야 한다"
        if f.get("max") is not None and num > f["max"]:
            return None, f"{f['name']}은(는) {f['max']} 이하여야 한다"
        if kind == "float" and float(num).is_integer():
            num = int(num)
        return num, ""
    if kind == "choice" and text not in f["options"]:
        return None, f"{f['name']}은(는) {', '.join(f['options'])} 가운데 하나여야 한다"
    if f["key"] == "name" and not _NAME_RE.match(text):
        return None, "이름은 영문 소문자, 숫자, 밑줄만 40자 안으로 쓴다"
    if "\n" in text:
        return None, f"{f['name']}은(는) 한 줄이어야 한다"
    return text, ""


# ----- toml 글자 만들기 -----
def _str_lit(s: str, like: str = "") -> str:
    """toml 문자열. 원래 값이 리터럴('...')이었거나 백슬래시가 들면 리터럴을, 아니면 기본 문자열을 쓴다."""
    if "'" not in s and "\n" not in s and (like.startswith("'") or ("\\" in s and '"' not in s)):
        return f"'{s}'"
    return json.dumps(s, ensure_ascii=False)


def _scalar_lit(val, like: str = "") -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return repr(val)
    return _str_lit(str(val), like)


def _array_lit(items: list[str], indent: str = "", multiline: bool = False) -> str:
    if not items:
        return "[]"
    if multiline:
        return "[\n" + "".join(f"{indent}{_str_lit(x)},\n" for x in items) + "]"
    return "[" + ", ".join(_str_lit(x) for x in items) + "]"


def _tokens(arr: str) -> list[tuple[int, int, str]]:
    """여러 줄 문자열 목록 '[...]'의 항목마다 (시작, 끝, 값). 주석은 건너뛴다."""
    out, i, n = [], 1, len(arr) - 1
    while i < n:
        c = arr[i]
        if c == "#":
            j = arr.find("\n", i)
            i = n if j < 0 else j
            continue
        if c in "\"'":
            q = c * 3 if arr.startswith(c * 3, i) else c
            j = i + len(q)
            while j < n and not arr.startswith(q, j):
                j += 2 if (c == '"' and arr[j] == "\\") else 1
            lit = arr[i:j + len(q)]
            try:
                val = tomllib.loads(f"x = {lit}")["x"]
            except ValueError as e:
                raise LineError("목록 항목을 읽지 못했다") from e
            out.append((i, j + len(q), str(val)))
            i = j + len(q)
            continue
        i += 1
    return out


def _edit_multiline(old: str, new_items: list[str], base_indent: str) -> str:
    """여러 줄 목록을 최소로 고친다. 남는 항목은 제자리에 두고, 빠진 항목은 그 자리만 지우며, 더한 항목은 끝에 한 줄씩 넣는다.
    순서가 바뀌었으면 한 줄에 하나씩 다시 쓴다."""
    toks = _tokens(old)
    olds = [t[2] for t in toks]
    kept = [x for x in olds if x in new_items]
    if [x for x in new_items if x in olds] != kept or len(set(new_items)) != len(new_items):
        first = re.search(r"\n([ \t]+)\S", old)
        return _array_lit(new_items, first.group(1) if first else base_indent + "  ", True)
    text = old
    # 빠진 항목을 뒤에서부터 지운다. 항목 뒤의 쉼표와 공백을 함께 지우고, 줄에 남는 것이 없으면 줄을 지운다
    for s, e, v in reversed(toks):
        if v in new_items:
            continue
        j = e
        while j < len(text) and text[j] in " \t":
            j += 1
        if j < len(text) and text[j] == ",":
            j += 1
            while j < len(text) and text[j] in " \t":
                j += 1
        text = text[:s] + text[j:]
        ls = text.rfind("\n", 0, s) + 1
        le = text.find("\n", ls)
        if ls > 0 and le > 0 and not text[ls:le].strip():
            text = text[:ls] + text[le + 1:]
    # 더한 항목을 닫는 괄호 앞에 한 줄씩 넣는다
    added = [x for x in new_items if x not in olds]
    if added:
        first = re.search(r"\n([ \t]+)\S", text)
        indent = first.group(1) if first else base_indent + "  "
        close = len(text) - 1
        line_start = text.rfind("\n", 0, close) + 1
        toks2 = _tokens(text)
        if toks2:
            last_end = toks2[-1][1]
            rest = text[last_end:close]
            if "," not in rest.split("#")[0]:
                text = text[:last_end] + "," + text[last_end:]
                close += 1
                line_start = text.rfind("\n", 0, close) + 1
        if text[line_start:close].strip():  # 닫는 괄호가 마지막 항목 줄에 붙어 있다
            return _array_lit(new_items, indent, True)
        text = text[:line_start] + "".join(f"{indent}{_str_lit(x)},\n" for x in added) + text[line_start:]
    return text


# ----- 줄 단위 고치기 -----
def _section_range(text: str, section: str) -> tuple[int, int] | None:
    """표의 본문 범위(머리 줄 끝, 다음 머리 줄 앞). 맨 위 키는 (0, 첫 머리 줄 앞)이다. 표가 없으면 None이다."""
    if not section:
        m = _HEADER.search(text)
        return 0, (m.start() if m else len(text))
    for m in _HEADER.finditer(text):
        if m.group(1).strip() == section:
            nxt = _HEADER.search(text, m.end())
            return m.end(), (nxt.start() if nxt else len(text))
    return None


def _key_line(text: str, start: int, end: int, key: str):
    return re.compile(r"^([ \t]*)" + re.escape(key) + r"[ \t]*=[ \t]*", re.MULTILINE).search(text, start, end)


def _scalar_end(text: str, i: int, end: int) -> int:
    """text[i]에서 시작하는 스칼라 값의 끝 위치. 문자열은 닫는 따옴표까지, 그 밖은 주석이나 줄 끝 앞의 마지막 글자까지다."""
    c = text[i]
    if c in "\"'":
        q = c * 3 if text.startswith(c * 3, i) else c
        j = i + len(q)
        while j < end and not text.startswith(q, j):
            j += 2 if (c == '"' and text[j] == "\\") else 1
        if j >= end:
            raise LineError("등록 문자열이 닫히지 않았다")
        return j + len(q)
    line_end = text.find("\n", i)
    line_end = end if line_end < 0 or line_end > end else line_end
    seg = text[i:line_end]
    hash_at = seg.find("#")
    seg = seg[:hash_at] if hash_at >= 0 else seg
    return i + len(seg.rstrip())


def _insert_at(text: str, start: int, end: int) -> int:
    """표 안에서 새 줄을 넣을 위치. 마지막 값 줄(주석과 빈 줄이 아닌 줄)의 끝이다. 없으면 머리 줄 끝이다."""
    pos, i = start, start
    while i < end:
        nl = text.find("\n", i)
        nl = end if nl < 0 or nl > end else nl
        line = text[i:nl]
        if line.strip() and not line.strip().startswith("#"):
            eq = line.find("=")
            v = eq + 1
            while eq >= 0 and v < len(line) and line[v] in " \t":
                v += 1
            if eq >= 0 and v < len(line) and line[v] == "[":  # 여러 줄 목록이면 닫는 괄호 줄까지 건너뛴다
                close, _, _ = _array_end(text, i + v)
                nl = text.find("\n", close)
                nl = end if nl < 0 or nl > end else nl
            pos = nl
        i = nl + 1
    return pos


def apply(text: str, changes: dict[str, object]) -> str:
    """changes({칸 id: 값 또는 None})를 toml 글에 줄 단위로 적용한다. 다른 줄은 그대로다."""
    for fid, val in changes.items():
        sec, key = _split_id(fid)
        f = _BY_ID[(sec, key)]
        rng = _section_range(text, sec)
        if rng is None:
            if val is None or val == []:
                continue
            if not text.endswith("\n"):
                text += "\n"
            text += f"\n[{sec}]\n"
            rng = _section_range(text, sec)
        start, end = rng
        m = _key_line(text, start, end, key)
        if m is None:
            if val is None or (val == [] and f["kind"] == "list" and not f.get("required")):
                continue  # 없는 키를 비우는 것은 그대로 둔다
            lit = _array_lit(val) if f["kind"] == "list" else _scalar_lit(val)
            pos = _insert_at(text, start, end)
            line = f"{key} = {lit}"
            if pos == start == 0:  # 맨 위 키가 하나도 없다
                text = line + "\n" + text
            else:  # 머리 줄 끝이거나 마지막 값 줄 끝이다. 그 뒤 줄 바꿈은 원문 것을 쓴다
                text = text[:pos] + "\n" + line + text[pos:]
            continue
        vstart = m.end()
        if text[vstart] == "[":
            close, _, _ = _array_end(text, vstart)
            vend = close + 1
            old = text[vstart:vend]
            if not val:
                new = "[]"
            elif "\n" in old:
                new = _edit_multiline(old, list(val), m.group(1))
            else:
                new = _array_lit(val)
            text = text[:vstart] + new + text[vend:]
            continue
        vend = _scalar_end(text, vstart, end)
        if val is None:
            # 키 줄을 지운다. 뒤에 주석이 붙어 있으면 값만 비우지 않고 줄 전체를 지운다. 표에 값 줄이 남지 않으면 머리 줄도 지운다
            ls = text.rfind("\n", 0, m.start()) + 1
            le = text.find("\n", vend)
            le = len(text) if le < 0 else le + 1
            text = text[:ls] + text[le:]
            rng = _section_range(text, sec)
            if sec and rng and _insert_at(text, rng[0], rng[1]) == rng[0]:
                hs = text.rfind("\n", 0, rng[0]) + 1
                he = text.find("\n", hs)
                he = len(text) if he < 0 else he + 1
                text = text[:hs] + text[he:]
                if text[:hs].endswith("\n\n") and text[hs:hs + 1] in ("\n", ""):  # 머리 줄 앞 빈 줄 하나도 지운다
                    text = text[:hs - 1] + text[hs:]
            continue
        text = text[:vstart] + _scalar_lit(val, text[vstart:vend]) + text[vend:]
    return text


def _expected(before: dict, changes: dict[str, object]) -> dict:
    want = json.loads(json.dumps(before))
    for fid, val in changes.items():
        sec, key = _split_id(fid)
        tbl = want if not sec else want.setdefault(sec, {})
        if val is None or (val == [] and _BY_ID[(sec, key)]["kind"] == "list" and key not in tbl):
            tbl.pop(key, None)
        else:
            tbl[key] = val
        if sec and not tbl:  # 값 줄이 남지 않은 표는 머리 줄도 지운다
            want.pop(sec, None)
    return want


def save(project: str, values: dict, version: str | None = None, dry_run: bool = False) -> dict:
    """등록 한 장의 칸을 고친다. 판이 다르면 거절하고, 고친 뒤 다시 읽어 바뀐 칸 말고 달라진 값이 없을 때만 쓴다. dry_run이면 바뀐 줄만 돌려주고 쓰지 않는다."""
    path = PROJECTS / f"{project}.toml"
    if not path.exists():
        return {"ok": False, "why": f"등록에 {project}가 없다"}
    if version is not None and version != version_of(path):
        return {"ok": False, "why": "다른 곳에서 등록를 고쳤다. 다시 읽은 뒤 고친다", "conflict": True}
    errors, changes = [], {}
    for fid, raw in (values or {}).items():
        sec, key = _split_id(str(fid))
        f = _BY_ID.get((sec, key))
        if f is None:
            errors.append(f"모르는 칸이다: {fid}")
            continue
        if f.get("create_only"):
            errors.append(f"{f['name']}은(는) 파일 이름과 같아야 해서 등록할 때만 정한다")
            continue
        val, err = normalize(f, raw)
        if err:
            errors.append(err)
        else:
            changes[field_id(f)] = val
    if errors:
        return {"ok": False, "why": " / ".join(errors), "errors": errors}
    if not changes:
        return {"ok": False, "why": "바뀐 칸이 없다"}
    try:
        raw = path.read_bytes()
        old = raw.decode("utf-8").replace("\r\n", "\n")
        before = tomllib.loads(old)
        new = apply(old, changes)
        after = tomllib.loads(new)
    except (OSError, ValueError, LineError) as e:
        return {"ok": False, "why": f"등록를 고치지 못했다: {e}"}
    if after != _expected(before, changes):
        return {"ok": False, "why": "고친 뒤 다시 읽은 값이 바뀐 칸만의 변화와 다르다. 쓰지 않았다"}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(new, encoding="utf-8", newline="\r\n" if b"\r\n" in raw else "\n")  # 줄 끝 꼴은 원문을 따른다
    try:
        _load_one(tmp)
    except (RegistryError, KeyError, ValueError) as e:
        tmp.unlink(missing_ok=True)
        return {"ok": False, "why": f"고친 등록가 읽히지 않는다: {e}"}
    import difflib

    diff = [d for d in difflib.ndiff(old.splitlines(), new.splitlines()) if d[:1] in "+-"]
    if dry_run:
        tmp.unlink(missing_ok=True)
    else:
        os.replace(tmp, path)
    return {"ok": True, "project": project, "changed": sorted(changes), "lines": len(diff), "diff": diff, "dry_run": dry_run, "version": version_of(path)}


# ----- 새 프로젝트 폴더 -----
def default_repo(name: str, cwd: Path | None = None) -> Path:
    """이름만 받았을 때 프로젝트 폴더. 실행한 폴더 아래 <이름>이다. 실행한 폴더가 jipsa 저장소 안이면 저장소 안에 저장소를 겹치지 않도록
    저장소 바로 위 폴더 아래로 한다. 세션 입구가 jipsa 저장소라 평소에는 이쪽이고, 있던 등록들이 놓인 자리와 같다."""
    home = (ROOT.parent.parent if ROOT.parent.name == "worktrees" else ROOT).resolve()  # worktree에서 돌려도 본 저장소 기준이다
    here = Path(cwd or Path.cwd()).resolve()
    return (home.parent if here == home or home in here.parents else here) / name


def make_repo(repo: Path) -> dict:
    """프로젝트 폴더를 준비한다. 있는 폴더는 건드리지 않고 worktree를 못 만드는 상태면 알린다. 없는 폴더는 만들고 git 첫 커밋까지 한다.
    code 작업은 HEAD에서 worktree를 만들므로 첫 커밋이 있어야 돈다."""
    from scheduler.workspace import GitError, git, is_repo

    if repo.exists():
        if not repo.is_dir():
            return {"ok": False, "why": f"같은 이름의 파일이 있다: {repo}"}
        if not is_repo(repo):
            return {"ok": True, "made": False, "note": "있던 폴더가 git 저장소가 아니다. 그 폴더에서 git init과 첫 커밋을 해야 작업이 돈다"}
        if not git(repo, "rev-parse", "--verify", "-q", "HEAD", check=False).strip():
            return {"ok": True, "made": False, "note": "있던 저장소에 커밋이 없다. 첫 커밋을 해야 작업이 돈다"}
        return {"ok": True, "made": False, "note": ""}
    try:
        repo.mkdir(parents=True)
        git(repo, "init", "-q")
        (repo / ".gitignore").write_text(".env\n.venv/\n__pycache__/\n", encoding="utf-8")
        git(repo, "add", ".gitignore")
        who = []  # git 사용자 설정이 없는 컴퓨터에서도 첫 커밋이 되게 한다. 있으면 그 값을 쓴다
        if not git(repo, "config", "user.name", check=False).strip():
            who += ["-c", "user.name=jipsa"]
        if not git(repo, "config", "user.email", check=False).strip():
            who += ["-c", "user.email=jipsa@localhost"]
        git(repo, *who, "commit", "-q", "-m", "프로젝트를 시작한다")
    except (OSError, GitError) as e:
        return {"ok": False, "why": f"폴더 {repo}를 준비하지 못했다. 등록하지 않았다. 원인을 고친 뒤 다시 돌리면 그 폴더를 쓴다: {e}"}
    return {"ok": True, "made": True, "note": ""}


def made_text(path: str | Path, made: dict) -> str:
    return f"폴더 {Path(path).as_posix()}{'를 만들고 git 첫 커밋까지 했다' if made['made'] else '는 있던 폴더를 그대로 썼다'}"


# Windows가 파일 이름으로 받지 않는 이름. 이름 규칙은 통과하지만 폴더를 만들 수 없다
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def new_project(values: dict, cwd: Path | None = None, check: bool = False) -> dict:
    """무질문 등록(261103-jipsa-06). 경로가 없으면 이름으로 폴더를 정해 첫 커밋까지 하고 등록한다. /jipsa-register와 대시보드 만들기가 함께 쓴다.
    이름과 값 검사를 통과한 뒤에만 폴더를 만든다. 경로를 이름에서 만들므로 이름은 규칙에 온전히 맞아야 하고 예약어는 받지 않는다."""
    values = dict(values)
    name = str(values.get("name") or "").strip()
    if not _NAME_RE.fullmatch(name):
        return {"ok": False, "why": "이름은 영문 소문자, 숫자, 밑줄만 40자 안으로 쓴다"}
    if name in _RESERVED:
        return {"ok": False, "why": f"{name}은(는) Windows 예약어라 폴더 이름으로 쓰지 못한다"}
    values["name"] = name
    auto = "path" not in values
    if auto:
        values["path"] = str(default_repo(name, cwd))
    values.setdefault("kind", "code")
    out = create(values, dry_run=True)
    if not out["ok"] or check:
        return out
    made = None
    if auto:
        made = make_repo(Path(values["path"]))
        if not made["ok"]:
            return {"ok": False, "why": made["why"]}
    out = create(values)
    if out["ok"] and made:
        out["made"] = {**made, "path": values["path"]}
        if made["note"]:
            out["note"] = made["note"]
    return out


# ----- 새 등록 -----
def create(values: dict, dry_run: bool = False) -> dict:
    """필수 키(이름, 경로, 종류)를 채운 새 등록을 만든다. 이름이 겹치면 거절한다. 경로 폴더는 만들지 않고 없으면 알린다. dry_run이면 쓰지 않고 글만 돌려준다."""
    errors, vals = [], {}
    for f in FIELDS:
        val, err = normalize(f, (values or {}).get(field_id(f)))
        if err:
            errors.append(err)
        else:
            vals[field_id(f)] = val
    if errors:
        return {"ok": False, "why": " / ".join(errors), "errors": errors}
    name = vals["name"]
    path = PROJECTS / f"{name}.toml"
    if path.exists():
        return {"ok": False, "why": f"이미 있는 이름이다: {name}"}
    kind = vals["kind"]
    repo = Path(str(vals["path"]))
    note = "" if repo.exists() else "경로 폴더가 아직 없다. 작업이 돌기 전에 만든다"
    sections: dict[str, list[str]] = {s: [] for s in _ORDER}
    top = [f"# {name} 등록. {now():%Y-%m-%d} /jipsa-register로 등록했다.", f'name = "{name}"', f"path = {_str_lit(str(repo))}", f'kind = "{kind}"',
           f"priority = {vals.get('priority') if vals.get('priority') is not None else 50}", 'run_prefix = "uv run"']
    commit = vals.get("scope.commit")
    sections["scope"] += [f"auto = {_str_lit(str(vals.get('scope.auto') or ('기능 브랜치 커밋까지. 원격 생성과 푸시 없음' if kind != 'doc' else '문서 초안까지. 커밋 없음')))}",
                         f"commit = {'true' if (commit if commit is not None else kind != 'doc') else 'false'}"]
    if vals.get("scope.manual_only"):
        sections["scope"].append("manual_only = true")
    sections["scope"].append(f"allowed_dirs = {_array_lit(vals.get('scope.allowed_dirs') or [])}")
    sections["scope"].append("notes = []")
    sections["paths"] += [f"no_read = {_array_lit(vals.get('paths.no_read') or ['.env'])}", f"read_only = {_array_lit(vals.get('paths.read_only') or ['CLAUDE.md', 'AGENTS.md'])}"]
    sections["links"].append("dirs = []")
    sections["external"] += [f"read = {_array_lit(vals.get('external.read') or [])}", f"forbid = {_array_lit(vals.get('external.forbid') or [])}"]
    sections["resources"] += [f"gpu_vram_gb = {vals.get('resources.gpu_vram_gb') or 0}"]
    if vals.get("resources.ram_gb"):
        sections["resources"].append(f"ram_gb = {vals['resources.ram_gb']}")
    if vals.get("resources.ollama_models"):
        sections["resources"].append(f"ollama_models = {_array_lit(vals['resources.ollama_models'])}")
    # 상한은 적은 것만 쓴다. 비운 칸은 종류별 기본값을 따른다
    sections["limits"] += [f"{k} = {vals[f'limits.{k}']}" for k in ("total_minutes", "segment_minutes") if vals.get(f"limits.{k}")]
    sections["deps"] += ['manager = "uv-lock"', 'venv = ".venv"']
    sections["questions"].append("items = []")
    if (vals.get("worker.provider") or "claude") != "claude" or vals.get("worker.model"):
        sections["worker"] += [f'provider = "{vals.get("worker.provider") or "claude"}"'] + ([f"model = {_str_lit(str(vals['worker.model']))}"] if vals.get("worker.model") else [])
    text = "\n".join(top) + "\n"
    for s in _ORDER:
        if sections[s] or s in _ALWAYS:
            text += f"\n[{s}]\n" + "".join(x + "\n" for x in sections[s])
    try:
        tomllib.loads(text)
    except ValueError as e:
        return {"ok": False, "why": f"만든 등록가 읽히지 않는다: {e}"}
    PROJECTS.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    crlf = any(b"\r\n" in q.read_bytes() for q in list(PROJECTS.glob("*.toml"))[:3])  # 줄 끝 꼴은 있는 등록들을 따른다
    tmp.write_text(text, encoding="utf-8", newline="\r\n" if crlf else "\n")
    try:
        _load_one(tmp)
    except (RegistryError, KeyError, ValueError) as e:
        tmp.unlink(missing_ok=True)
        return {"ok": False, "why": f"만든 등록가 읽히지 않는다: {e}"}
    if dry_run:
        tmp.unlink(missing_ok=True)
        return {"ok": True, "project": name, "file": str(path), "note": note, "dry_run": True, "text": text}
    os.replace(tmp, path)
    view = fields_view(name)
    return {"ok": True, "project": name, "file": str(path), "note": note, "fields_read": len(view.get("fields", [])), "version": version_of(path)}
