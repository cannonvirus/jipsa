"""사람 답이 기록된 실행을 근거로 등록부의 정해진 목록 칸 끝에 한 줄을 더한다(261029-jipsa-38 1안).

원본 보호 hook은 작업자가 등록부를 고치지 못하게 막는다. 사람이 승인한 줄도 같이 막혀 사람 손으로 돌아오던 것을
이 명령이 메인 세션에서 받는다. 더하는 문구는 승인 실행의 사람 답, 고른 안의 선택지, 보고서의 같은 안 항목 가운데
따옴표로 적힌 원문과 글자까지 같아야 한다. 칸은 FIELDS의 목록 칸만이고 숫자와 참거짓 값은 바꾸지 않는다.
toml은 글자 단위로 끼워 넣어 주석과 줄 바꿈을 그대로 두고, 쓰기 전에 다시 읽어 그 칸 말고 달라진 값이 없는지 본다.
"""

from __future__ import annotations

import json
import os
import re
import tomllib

from scheduler import events, record
from scheduler.config import PROJECTS, RUNS, STATE, now_iso
from scheduler.registry import RegistryError, _load_one

# 더할 수 있는 목록 칸과, 승인 글(따옴표 원문 밖)에 그 칸을 가리키는 말로 나와야 하는 낱말.
# 숫자, 참거짓, 경로, 자원과 허용 폴더(allowed_dirs)는 넣지 않는다
FIELDS = {
    "external.read": ("외부 읽기",),
    "external.forbid": ("외부 금지", "금지 목록"),
    "scope.notes": ("범위 메모", "범위 칸", "notes"),
    "paths.no_read": ("읽기 금지",),
    "paths.read_only": ("읽기 전용",),
    "questions.items": ("남은 질문", "질문 목록"),
}
_QUOTED = re.compile(r'"([^"\n]+)"|“([^”\n]+)”')


class LineError(ValueError):
    pass


def worker_shell() -> str:
    """작업자 셸이면 그 이름. 스케줄러 작업자는 어댑터가 JIPSA_WORKER=1을 주고(Claude와 Codex 모두), 스케줄러가 띄운 셸은 JIPSA_LIVE=1을 물려받는다.
    Codex 표시(CODEX_THREAD_ID 등)는 사람이 연 Codex 메인 세션에도 있으므로 보지 않는다."""
    if os.environ.get("JIPSA_WORKER", "").strip() == "1":
        return "스케줄러 작업자"
    if os.environ.get("JIPSA_LIVE", "").strip() == "1":
        return "스케줄러가 띄운 셸"
    return ""


def _answer_logged(run_id: str, answer: str) -> bool:
    """jipsa answer가 남긴 답 줄이 있고 그 뒤에 물리기가 없는지. 기록 파일만 고친 답은 받지 않는다."""
    files = [STATE / "events.jsonl"] + [d / "events.jsonl" for d in record.attempt_dirs(run_id)]
    last = None
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in lines:
            if f'"{run_id}"' not in raw:
                continue
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            if (row.get("run") == run_id and row.get("kind") in ("answer", "unanswer")
                    and (last is None or str(row.get("ts", "")) >= str(last.get("ts", "")))):
                last = row
    return bool(last and last["kind"] == "answer" and str(last.get("answer", "")) == answer[:120])


def approval(run_id: str, project: str) -> tuple[dict, list[str], str, str]:
    """승인 실행의 기록, 따옴표 원문 목록, 고른 안 이름, 원문을 뺀 승인 글. 근거가 못 되면 LineError다."""
    meta = record.meta_of(run_id)
    if not meta:
        raise LineError(f"기록이 없는 실행이다 ({run_id})")
    answer = str(meta.get("answer") or "").strip()
    if not answer:
        raise LineError(f"사람 답이 없는 실행이다 ({run_id})")
    if meta.get("status") not in ("완료", "실패") or not meta.get("finished"):
        raise LineError(f"끝나지 않은 실행이다 ({run_id}, 지금 {meta.get('status')})")
    if not _answer_logged(run_id, answer):
        raise LineError(f"답 넣기 명령이 남긴 답 기록이 없다 ({run_id})")
    if meta.get("project") != project:
        raise LineError(f"승인 실행의 프로젝트가 다르다 (승인 {meta.get('project')}, 요청 {project})")
    opts = [str(o).replace("**", "").strip() for o in meta.get("options") or [] if str(o).strip()]
    picks = [{"name": n, "text": o} for n, o in zip(record.option_names(opts), opts)]
    names = [c["name"] for c in record.picked_of(answer, picks)]
    texts = [answer] + [c["text"] for c in picks if c["name"] in names]
    texts += [t for t in record.decision_items(run_id) if record.alt_name(t) in names]
    quoted = [a or b for t in texts for a, b in _QUOTED.findall(t)]
    prose = " ".join(_QUOTED.sub(" ", t) for t in texts)
    return meta, [q.strip() for q in quoted], ",".join(names), prose


def _table(text: str, section: str) -> tuple[int, int]:
    """[section] 표의 본문 범위(시작, 끝 글자 위치)."""
    head = re.compile(r"^[ \t]*\[[ \t]*" + re.escape(section) + r"[ \t]*\][ \t]*(?:#.*)?$", re.MULTILINE)
    m = head.search(text)
    if not m:
        raise LineError(f"등록부에 [{section}] 표가 없다")
    nxt = re.compile(r"^[ \t]*\[\[?[A-Za-z0-9_.\" -]+\]\]?[ \t]*(?:#.*)?$", re.MULTILINE).search(text, m.end())
    return m.end(), nxt.start() if nxt else len(text)


def _array_end(text: str, i: int) -> tuple[int, int, bool]:
    """text[i]의 '['에 맞는 ']' 위치, 마지막 값 끝 위치(없으면 -1), 마지막 값 뒤에 쉼표가 있는지. 문자열과 주석 안의 괄호는 건너뛴다."""
    depth, last, comma, n = 0, -1, False, len(text)
    while i < n:
        c = text[i]
        if c == "#":
            i = text.find("\n", i)
            i = n if i < 0 else i
            continue
        if c in "\"'":
            q = c * 3 if text.startswith(c * 3, i) else c
            j = i + len(q)
            while j < n and not text.startswith(q, j):
                j += 2 if (c == '"' and text[j] == "\\") else 1
            if j >= n:
                raise LineError("등록부 문자열이 닫히지 않았다")
            i = j + len(q)
            last, comma = i, False
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return i, last, comma
            last, comma = i + 1, False
        elif c == ",":
            comma = True
        elif not c.isspace():
            last, comma = i + 1, False
        i += 1
    raise LineError("목록이 닫히지 않았다")


def insert(text: str, field: str, value: str) -> str:
    """field 목록의 끝에 value를 더한 toml 글. 다른 줄, 주석, 들여쓰기는 그대로 둔다."""
    section, key = field.rsplit(".", 1)
    start, end = _table(text, section)
    m = re.compile(r"^([ \t]*)" + re.escape(key) + r"[ \t]*=[ \t]*\[", re.MULTILINE).search(text, start, end)
    if not m:
        raise LineError(f"등록부 [{section}] 표에 {key} 목록이 없다")
    open_at = m.end() - 1
    close, last, comma = _array_end(text, open_at)
    lit = json.dumps(value, ensure_ascii=False)  # JSON 문자열 이스케이프는 toml 기본 문자열과 같다
    line_start = text.rfind("\n", 0, close) + 1
    if "\n" in text[open_at:close] and not text[line_start:close].strip():
        # 여러 줄 목록: 닫는 괄호 줄 앞에 앞 값과 같은 들여쓰기로 한 줄을 넣는다
        first = re.search(r"\n([ \t]+)\S", text[open_at:close])
        indent = first.group(1) if first else m.group(1) + "  "
        if last >= 0 and not comma:
            text, close, line_start = text[:last] + "," + text[last:], close + 1, line_start + 1
        return text[:line_start] + f"{indent}{lit},\n" + text[line_start:]
    sep = "" if last < 0 else (" " if comma else ", ")
    return text[:close] + sep + lit + text[close:]


def _get(data: dict, field: str):
    section, key = field.rsplit(".", 1)
    return data.get(section, {}).get(key)


def add(project: str, field: str, phrase: str, run_id: str, *, dry_run: bool = False) -> dict:
    """승인 실행을 근거로 한 줄을 더한다. 돌려주는 값은 {ok, line, path} 또는 {ok: False, why}."""
    try:
        who = worker_shell()
        if who:
            raise LineError(f"{who}에서는 부를 수 없다. 사람 답을 받은 메인 세션만 부른다")
        if field not in FIELDS:
            raise LineError(f"정해지지 않은 칸이다 ({field}). 더할 수 있는 칸: {', '.join(FIELDS)}")
        phrase = phrase.strip()
        if not phrase or "\n" in phrase:
            raise LineError("문구는 비지 않은 한 줄이어야 한다")
        path = PROJECTS / f"{project}.toml"
        if not path.exists():
            raise LineError(f"등록부에 {project}가 없다")
        meta, quoted, names, prose = approval(run_id, project)
        if phrase not in quoted:
            raise LineError(f"승인 원문에 없는 문구다. {run_id}의 사람 답과 고른 안({names or '없음'})에 따옴표로 적힌 문구와 글자까지 같아야 한다")
        if field not in prose and not any(w in prose for w in FIELDS[field]):
            raise LineError(f"승인한 안이 가리킨 칸이 아니다. {run_id}의 고른 안 글에 {field}({', '.join(FIELDS[field])})가 나오지 않는다")
        old = path.read_text(encoding="utf-8")
        before = tomllib.loads(old)
        cur = _get(before, field)
        if not isinstance(cur, list):
            raise LineError(f"{field}가 목록이 아니다")
        if any(str(v) == phrase or str(v).startswith(phrase + " [승인 실행 ") for v in cur):
            raise LineError(f"{field}에 이미 있는 문구다")
        line = f"{phrase} [승인 실행 {run_id}, 답 {names or '원문'}]"
        new = insert(old, field, line)
        after = tomllib.loads(new)
        want = json.loads(json.dumps(before))
        section, key = field.rsplit(".", 1)
        want[section][key] = cur + [line]
        if after != want:
            raise LineError("끼워 넣은 뒤 다시 읽은 값이 그 칸 한 줄 추가와 다르다. 쓰지 않았다")
        if dry_run:
            return {"ok": True, "line": line, "path": str(path), "dry_run": True}
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(new, encoding="utf-8", newline="")
        try:
            _load_one(tmp)  # 등록부 읽기 규칙(kind, provider 등)으로도 읽히는지
        except (RegistryError, KeyError, ValueError) as e:
            tmp.unlink(missing_ok=True)
            raise LineError(f"고친 등록부가 읽히지 않는다: {e}") from e
        os.replace(tmp, path)
    except LineError as e:
        return {"ok": False, "why": str(e)}
    meta.setdefault("registry_lines", []).append({"project": project, "field": field, "line": line, "at": now_iso()})
    record.write_json(RUNS / run_id / "meta.json", meta)
    events.emit("registry_add", run=run_id, project=project, field=field, line=line[:200])
    return {"ok": True, "line": line, "path": str(path)}
