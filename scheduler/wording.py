"""낱말 고르기 검사(261029-jipsa-05, 261029-jipsa-02 1안).

policies/wording.md 2절 표의 바꿀 낱말을 보고서 본문에서 센다. 표가 원천이고 이 모듈은 표를 읽기만 한다.
마감 공통 경로(record.close)가 결과지를 쓰기 전에 부르고, 찾으면 결과지 아래와 마감 출력에 주의 줄 하나를 남긴다. 결과는 막지 않는다.
요약 상자를 뺀 코드 블록, 인라인 코드, 경로와 주소, 링크 대상, 따옴표 인용, 인용 줄, '열어 볼 파일' 줄은 세지 않는다.
result.json의 label, summary, reason, options도 같이 센다. 기준 정하기의 1안 문장이 다음 작업의 제목과 기준이 되기 때문이다(261031-jipsa-07).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from scheduler.config import POLICIES

POLICY_FILE = POLICIES / "wording.md"
SECTION = "## 2. 바꿀 낱말"
_FENCE = re.compile(r"^(`{3,}|~{3,})(.*)$")
_INLINE = re.compile(r"`[^`\n]*`")
_LINK = re.compile(r"\]\([^)\s]*\)")
_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|https?://|\.{0,2}/)?[\w.\-]+(?:[\\/][\w.\-가-힣]+)+[\\/]?|https?://\S+")
_QUOTE = re.compile(r"\"[^\"\n]*\"|“[^”\n]*”|「[^」\n]*」|『[^』\n]*』")


def rules(path: Path | None = None) -> list[dict]:
    """표의 줄마다 {words, to, skip}. N이 앞에 붙은 낱말은 숫자 뒤에서만 찾는다. 표가 없거나 읽지 못하면 빈 목록이다."""
    try:
        text = (path or POLICY_FILE).read_text(encoding="utf-8")
    except OSError:
        return []
    out, inside = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line.strip() == SECTION
            continue
        s = line.strip()
        if not inside or not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 4 or cells[0] in ("지금 낱말", "") or set(cells[0]) <= {"-", " "}:
            continue
        words = [w.strip() for w in cells[0].split(",") if w.strip()]
        out.append({"words": words, "to": cells[1], "skip": [w.strip() for w in cells[3].split(",") if w.strip()]})
    return out


def body(report: str) -> str:
    """세는 대상만 남긴다. 요약 상자(```요약)는 남기고 다른 코드 블록, 인라인 코드, 경로, 링크 대상, 인용은 지운다."""
    keep, fence, summary = [], "", False
    for line in (report or "").splitlines():
        m = _FENCE.match(line.strip())
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not m.group(2).strip():
                fence = ""
            elif summary:
                keep.append(line)
            continue
        if m:
            fence, summary = m.group(1), m.group(2).strip() == "요약"
            continue
        s = line.strip()
        if s.startswith(">") or s.startswith("열어 볼 파일"):
            continue
        keep.append(line)
    text = "\n".join(keep)
    for rx in (_INLINE, _LINK, _QUOTE, _PATH):
        text = rx.sub(" ", text)
    return text


def _count(text: str, word: str, skip: list[str]) -> int:
    for s in skip:  # 뺄 꼴에 든 자리는 같은 길이의 빈칸으로 지운다
        if word.lstrip("N") in s:
            text = text.replace(s, " " * len(s))
    if word.startswith("N"):
        return len(re.findall(r"\d\s?" + re.escape(word[1:]), text))
    return text.count(word)


def scan(report: str, table: list[dict] | None = None) -> list[tuple[str, int, str]]:
    """[(낱말, 횟수, 바꿀 말)]. 많은 것부터다."""
    text = body(report)
    found = []
    for r in table if table is not None else rules():
        for w in r["words"]:
            n = _count(text, w, r["skip"])
            if n:
                found.append((w, n, r["to"]))
    return sorted(found, key=lambda x: -x[1])


def note(found: list[tuple[str, int, str]] | list[list]) -> str:
    """결과지와 마감 출력의 주의 줄. 찾은 것이 없으면 빈 글자다."""
    if not found:
        return ""
    total = sum(int(f[1]) for f in found)
    return (f"주의: 바꿀 낱말 {total}곳(" + ", ".join(f"{_shown(f[0])} {f[1]}" for f in found) + "). "
            "낱말 고르기 규칙(policies/wording.md)의 바꿀 말: " + ", ".join(f"{_shown(f[0])} 대신 {_first(f[2])}" for f in found[:5]) + ".")


def _shown(word: str) -> str:
    """'N칸'은 '숫자 뒤 칸'으로 보인다."""
    return f"숫자 뒤 {word[1:]}" if word.startswith("N") else word


def _first(to: str) -> str:
    return to.split(",")[0].strip()


def result_text(att_dir: Path) -> str:
    """result.json의 label, summary, reason, options를 줄로 이은 글. 기준 정하기의 1안 문장이 다음 작업의 제목과 기준으로 가므로 같이 센다(261031-jipsa-07)."""
    try:
        data = json.loads((att_dir / "result.json").read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    lines = [str(data.get(k) or "") for k in ("label", "summary", "reason")]
    lines += [str(o) for o in (data.get("options") or []) if o]
    return "\n".join(l for l in lines if l)


def check(att_dir: Path) -> dict:
    """마지막 시도 보고서와 result.json 요약, 선택지의 검사 결과 {found: [[낱말, 횟수, 바꿀 말]], note}. 둘 다 없으면 빈 결과다."""
    try:
        report = (att_dir / "report.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        report = ""
    extra = result_text(att_dir)
    if not report and not extra:
        return {"found": [], "note": ""}
    found = scan(report + ("\n\n" + extra if extra else ""))
    return {"found": [list(f) for f in found], "note": note(found)}


def prompt_words(limit: int = 8) -> str:
    """지시문에 넣는 '씨앗 대신 시드, 장부 대신 GPU 할당 현황' 꼴의 짧은 대응. 표를 읽지 못하면 빈 글자다."""
    pairs = [f"{_shown(r['words'][0])} 대신 {_first(r['to'])}" for r in rules() if r["words"]]
    return ", ".join(pairs[:limit])


def prompt_table() -> str:
    """공격 지시문에 넣는 표 전체. 줄마다 '낱말, 낱말 -> 바꿀 말, 바꿀 말'이고 줄은 쌍반점으로 잇는다. 표를 읽지 못하면 빈 글자다."""
    return "; ".join(", ".join(_shown(w) for w in r["words"]) + " -> " + r["to"] for r in rules() if r["words"])
