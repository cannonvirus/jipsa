"""마크다운 파일이나 웹 주소를 PNG로 찍는다. 보고서에 넣을 결과 그림을 만드는 도구다.

사용:
  uv run --with playwright python tools/md_shot.py --md 문서.md --out screen-x.png
  uv run --with playwright python tools/md_shot.py --md 문서.md --section "## 3." --out screen-x.png
  uv run --with playwright python tools/md_shot.py --url http://localhost:8000/ --out screen-x.png --height 1400
옵션: --width(기본 1280), --height(URL 모드의 창 높이, 기본 1000. 0이면 전체 쪽), --section(그 소제목부터 다음 같은 급 소제목 앞까지만),
      --max-lines(섹션 없이 앞부분만, 기본 전체), --selector(URL 모드에서 그 요소만), --wait(URL 모드 대기 ms).
마크다운은 작은 변환기로 HTML을 만든다. 제목, 문단, 목록, 표, 코드 상자, 요약 상자, 그림, 굵게, 인라인 코드를 지원한다.
"""

from __future__ import annotations

import argparse
import glob
import html
import os
import re
import sys
import tempfile
from pathlib import Path

CSS = """
html, body { margin: 0; background: #fcfcfb; color: #0b0b0b; font-family: "Pretendard Variable", Pretendard, "Malgun Gothic", "Segoe UI", sans-serif; font-size: 16px; line-height: 1.65; }
main { padding: 36px 48px; max-width: 1180px; }
h1 { font-size: 28px; margin: 0 0 18px; letter-spacing: -0.01em; }
h2 { font-size: 21px; margin: 30px 0 10px; padding-bottom: 6px; border-bottom: 1px solid #e1e0d9; }
h3 { font-size: 17px; margin: 22px 0 8px; }
p { margin: 0 0 12px; }
ul, ol { margin: 0 0 12px; padding-left: 26px; }
li { margin: 3px 0; }
table { border-collapse: collapse; margin: 8px 0 14px; font-size: 14.5px; }
th, td { border: 1px solid #d9d8d0; padding: 6px 12px; text-align: left; vertical-align: top; }
th { background: #f1f0ea; font-weight: 600; }
pre { background: #f1f0ea; border-radius: 6px; padding: 12px 14px; overflow-x: auto; font-size: 13.5px; line-height: 1.45; }
code { font-family: Consolas, "Cascadia Mono", monospace; font-size: .93em; background: #f1f0ea; border-radius: 3px; padding: 0 4px; }
pre code { background: none; padding: 0; }
aside.box { border-left: 4px solid #2a78d6; background: #eef4fc; padding: 10px 14px; margin: 10px 0 14px; border-radius: 0 6px 6px 0; }
aside.box .label { font-weight: 700; margin-bottom: 4px; }
figure { margin: 12px 0 16px; }
figure img { max-width: 100%; display: block; border: 1px solid #e1e0d9; border-radius: 6px; }
figcaption, .caption { color: #6b6a64; font-size: 13.5px; margin-top: 6px; }
strong { font-weight: 650; background: #fff1b8; border-radius: 3px; padding: 0 3px; -webkit-box-decoration-break: clone; box-decoration-break: clone; }
aside.box strong:first-child { background: none; padding: 0; }
blockquote { margin: 0 0 12px; padding: 4px 14px; border-left: 3px solid #d9d8d0; color: #52514e; }
"""

_INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\((https?://[^)\s]+)\))")


def inline(text: str) -> str:
    out = []
    last = 0
    for m in _INLINE.finditer(text):
        out.append(html.escape(text[last:m.start()]))
        tok = m.group(0)
        if tok.startswith("**"):
            out.append(f"<strong>{html.escape(tok[2:-2])}</strong>")
        elif tok.startswith("`"):
            out.append(f"<code>{html.escape(tok[1:-1])}</code>")
        else:
            label = tok[1:tok.index("]")]
            out.append(f"<a href=\"{html.escape(m.group(2))}\">{html.escape(label)}</a>")
        last = m.end()
    out.append(html.escape(text[last:]))
    return "".join(out)


def md_to_html(text: str, base: Path) -> str:
    lines = text.replace("\r", "").split("\n")
    out: list[str] = []
    para: list[str] = []
    stack: list[str] = []  # 열린 목록 태그
    i = 0

    def flush() -> None:
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()

    def close_lists(depth: int = 0) -> None:
        while len(stack) > depth:
            out.append(f"</{stack.pop()}>")

    while i < len(lines):
        line = lines[i]
        m = re.match(r"^```(\S*)\s*$", line)
        if m:
            flush(); close_lists()
            lang = m.group(1)
            buf = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i]); i += 1
            i += 1
            if lang in ("요약", "용어", "핵심"):
                body = "".join(f"<p>{inline(l)}</p>" for l in buf if l.strip())
                out.append(f"<aside class=\"box\"><div class=\"label\">{lang}</div>{body}</aside>")
            else:
                out.append(f"<pre><code>{html.escape(chr(10).join(buf))}</code></pre>")
            continue
        h = re.match(r"^(#{1,3})\s+(.*)$", line)
        if h:
            flush(); close_lists()
            out.append(f"<h{len(h.group(1))}>{inline(h.group(2))}</h{len(h.group(1))}>")
            i += 1; continue
        img = re.match(r"^!\[(.*?)\]\((.*?)\)\s*$", line)
        if img:
            flush(); close_lists()
            src = img.group(2)
            if not re.match(r"^(https?:|data:|/)", src):
                src = (base / src).resolve().as_uri()
            out.append(f"<figure><img src=\"{html.escape(src)}\" alt=\"{html.escape(img.group(1))}\"><figcaption>{inline(img.group(1))}</figcaption></figure>")
            i += 1; continue
        cap = re.match(r"^\{caption=\"(.*?)\".*\}\s*$", line)
        if cap:
            flush(); close_lists()
            out.append(f"<div class=\"caption\">{inline(cap.group(1))}</div>")
            i += 1; continue
        if re.match(r"^\s*\|.*\|\s*$", line):
            flush(); close_lists()
            rows = []
            while i < len(lines) and re.match(r"^\s*\|.*\|\s*$", lines[i]):
                rows.append(lines[i]); i += 1
            out.append("<table>")
            head = True
            for r in rows:
                if re.match(r"^\s*\|[\s:|-]+\|\s*$", r):
                    head = False; continue
                cells = r.strip()[1:-1].split("|")
                tag = "th" if head else "td"
                out.append("<tr>" + "".join(f"<{tag}>{inline(c.strip())}</{tag}>" for c in cells) + "</tr>")
                head = False
            out.append("</table>")
            continue
        li = re.match(r"^(\s*)([-*]|\d+[.)])\s+(.*)$", line)
        if li:
            flush()
            depth = len(li.group(1).replace("\t", "  ")) // 2 + 1
            tag = "ol" if li.group(2)[0].isdigit() else "ul"
            close_lists(depth)
            while len(stack) < depth:
                out.append(f"<{tag}>"); stack.append(tag)
            out.append(f"<li>{inline(li.group(3))}</li>")
            i += 1; continue
        if line.startswith(">"):
            flush(); close_lists()
            out.append(f"<blockquote>{inline(line[1:].strip())}</blockquote>")
            i += 1; continue
        if not line.strip():
            flush(); close_lists(); i += 1; continue
        if stack and re.match(r"^\s{2,}", line):
            out[-1] = out[-1][:-5] + " " + inline(line.strip()) + "</li>"
            i += 1; continue
        close_lists()
        para.append(line.strip()); i += 1
    flush(); close_lists()
    return "\n".join(out)


def cut_section(text: str, section: str) -> str:
    """소제목 `section`으로 시작하는 줄부터 다음 같은 급 소제목 앞까지."""
    lines = text.replace("\r", "").split("\n")
    start = next((k for k, l in enumerate(lines) if l.strip().startswith(section)), None)
    if start is None:
        raise SystemExit(f"소제목을 찾지 못했다: {section}")
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    end = len(lines)
    for k in range(start + 1, len(lines)):
        s = lines[k]
        if s.startswith("#") and (len(s) - len(s.lstrip("#"))) <= level:
            end = k; break
    return "\n".join(lines[start:end])


def chromium_path() -> str | None:
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright")
    cands = sorted(glob.glob(os.path.join(base, "chromium_headless_shell-*", "chrome-headless-shell-win64", "chrome-headless-shell.exe")))
    cands += sorted(glob.glob(os.path.join(base, "chromium-*", "chrome-win64", "chrome.exe")))
    return cands[-1] if cands else None


def main() -> int:
    ap = argparse.ArgumentParser(description="마크다운이나 웹 주소를 PNG로 찍는다")
    ap.add_argument("--md"); ap.add_argument("--url"); ap.add_argument("--html")
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=1000, help="URL 모드 창 높이. 0이면 전체 쪽")
    ap.add_argument("--section", default=None)
    ap.add_argument("--max-lines", type=int, default=0)
    ap.add_argument("--selector", default=None)
    ap.add_argument("--wait", type=int, default=800)
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright

    target = a.url
    tmp = None
    if a.md or a.html:
        if a.md:
            src = Path(a.md)
            text = src.read_text(encoding="utf-8")
            text = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.S)  # 머리말은 뺀다
            if a.section:
                text = cut_section(text, a.section)
            if a.max_lines:
                text = "\n".join(text.split("\n")[: a.max_lines])
            body = md_to_html(text, src.parent)
        else:
            body = Path(a.html).read_text(encoding="utf-8")
        doc = f"<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\"><style>{CSS}</style></head><body><main>{body}</main></body></html>"
        tmp = Path(tempfile.mkdtemp()) / "shot.html"
        tmp.write_text(doc, encoding="utf-8")
        target = tmp.as_uri()
    if not target:
        raise SystemExit("--md, --html, --url 중 하나가 필요하다")
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception:  # noqa: BLE001 - 설치된 다른 판의 크로미움으로 다시 시도한다
            exe = chromium_path()
            if not exe:
                raise
            browser = p.chromium.launch(executable_path=exe)
        page = browser.new_page(viewport={"width": a.width, "height": a.height or 1000}, device_scale_factor=1)
        page.goto(target)
        page.wait_for_timeout(a.wait)
        out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
        if a.selector:
            page.locator(a.selector).first.screenshot(path=str(out))
        elif a.md or a.html:
            page.locator("main").screenshot(path=str(out))
        else:
            page.screenshot(path=str(out), full_page=(a.height == 0))
        browser.close()
    print(f"찍음 {out} ({out.stat().st_size:,}바이트)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
