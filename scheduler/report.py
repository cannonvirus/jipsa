"""보고 규격. runs/의 meta.json과 result.json에서 그날의 보고를 만든다.

첫 줄은 집계 다섯 개, 절은 확인 필요, 실패, 완료, 건너뜀, 진행 중, 환경 순서로 여섯 개, 항목 줄은 다섯 칸이다.
사람이 확인하지 않은 완료와 실패는 화면과 같이 확인 필요 절과 확인 필요 낱말로 적는다(261023-jipsa-28). 판정은 confirm.shown 하나다(261025-jipsa-04).
확인 필요 절은 고를 것이 있는 것과 확인만 하면 되는 것으로 나눈다. 확인하면 완료로 바뀌고 보고를 다시 만들 때 반영된다.
그날 위임 cycle이 돌았으면 환경 앞에 cycle 절이 더해진다.
reports/YYYY-MM-DD.md에 전문을 쓴다. Slack 아침 집계에는 전문과 다른 세 줄 묶음(기호와 프로젝트, 결과, 정할 것)을 보낸다.
작업이 끝날 때 바로 보내는 글은 확인 필요와 실패만이고 결과지 요약 세 줄을 담는다(card, 261025-jipsa-20).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from scheduler import confirm, queue
from scheduler.config import REPORTS, RUNS, display_project, norm_record, time_text

SECTIONS = ["확인 필요", "실패", "완료", "건너뜀", "진행 중"]
EXECUTORS = {"worker": "스케줄러 작업자", "subagent": "세션 서브에이전트", "session": "세션", "manual": "손으로 들여옴", "collect": "자동 수집"}
MARKS = {"완료": "✅", "실패": "❌", "확인 필요": "⏸", "건너뜀": "⏭", "진행 중": "▶", "확인함": "✅"}
RESULT_MAX = 80  # Slack 결과 줄의 글자 상한. policies/report.md의 summary 규칙과 같다
# 경로, 파일 이름, 커밋 해시. 한글 조사가 바로 붙으므로 \b 대신 영숫자 경계를 쓴다
_NOISE = re.compile(
    r"[A-Za-z]:\\\S*"
    r"|[\w.-]*[/\\][\w./\\-]+"
    r"|[\w.-]+\.(?:md|py|json|toml|html|png|jpg|txt|csv|ya?ml|js|ts|css|lock)(?![A-Za-z0-9])"
    r"|(?<![A-Za-z0-9])(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}(?![A-Za-z0-9])"
)


def _read_json(path: Path) -> dict:
    try:
        return norm_record(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def runs_for(date: str) -> list[dict]:
    """그 보고 날짜에 속한 실행의 meta(+result)를 모은다."""
    out = []
    for run_dir in sorted(RUNS.glob("*")):
        meta = _read_json(run_dir / "meta.json")
        if not meta or meta.get("report_date") != date:
            continue
        if meta.get("executor") == "session":
            continue  # 세션 자신의 기록은 화면에만 보이고 보고와 Slack에는 넣지 않는다
        out.append(meta)
    return out


def shown(meta: dict) -> str:
    """보고와 Slack에 적는 상태. 사람이 확인하지 않은 완료와 실패는 확인 필요, 답 없이 확인한 상태 값 확인 필요는 확인함이다(대시보드, jipsa status와 같은 기준 confirm.shown).
    상태 값은 그대로이므로 Auto 종료, cycle, 큐, 선행 판정은 이 값을 보지 않는다."""
    return confirm.shown(meta) or "진행 중"


def section(meta: dict) -> str:
    """보고의 절. 확인함은 사람이 본 것이므로 완료 절이다."""
    st = shown(meta)
    if st == confirm.ACKED:
        return "완료"
    return st if st in SECTIONS else "진행 중"


def word(meta: dict) -> str:
    """상태 낱말. 확인하지 않은 실패는 확인 필요(실패), 확인해서 완료로 바뀐 실패는 완료(원래 실패)다."""
    st = shown(meta)
    if st == "확인 필요" and meta.get("status") == "실패":
        return "확인 필요(실패)"
    if st == "완료" and meta.get("confirmed_from") == "실패":
        return "완료(원래 실패)"
    return st


def to_choose(meta: dict) -> bool:
    """확인 필요 중 사람이 고를 것이 있는지. 상태 값 확인 필요이거나 선택지나 보고서 정할 것이 남은 결과다. 아니면 확인만 하면 된다."""
    if meta.get("status") == "확인 필요" or meta.get("options"):
        return True
    from scheduler import record  # record가 이 모듈을 부르므로 늦게 부른다

    return bool(meta.get("run_id") and record.decision_items(meta["run_id"]))


def item_line(meta: dict) -> list[str]:
    """`- 프로젝트 | 항목 | 결과 한 줄 | 근거 | 시간`(상한의 80%를 넘을 때만 상한을 붙인다) 와 들여쓴 보조 줄."""
    status = meta.get("status", "진행 중")
    summary = meta.get("summary") or meta.get("reason") or ""
    if word(meta) != shown(meta) or shown(meta) == confirm.ACKED:  # 실패였다는 것, 상태 값 확인 필요를 답 없이 확인했다는 것을 결과 칸 앞에 남긴다
        summary = f"{word(meta)}: {summary}"
    evidence = meta.get("evidence_ref") or meta.get("run_id", "")
    used = meta.get("minutes_used", 0)
    limit = meta.get("minutes_limit", 0)
    lines = [f"- {display_project(meta.get('project'))} | {meta.get('title')} | {summary} | {evidence} | {time_text(used, limit)}"]
    if meta.get("match_budget"):
        b = meta["match_budget"]
        lines.append(f"  - 판 수 상한: {b.get('text', '')}, 새 판 마감 {str(b.get('stop_new_at', ''))[11:16]}")
    if status == "확인 필요":
        opts = meta.get("options") or []
        if opts:
            lines.append("  - 선택지: " + " / ".join(("(추천) " if i == 0 and "추천" not in o else "") + o for i, o in enumerate(opts)))
        if meta.get("rule"):
            lines.append(f"  - 걸린 규칙: {meta['rule']}")
    if status in ("완료", "실패") and shown(meta) == "확인 필요":
        lines.append(f"  - 확인: 결과지에서 확인하면 완료로 바뀐다 (jipsa answer {meta.get('run_id')} 확인)")
    if status in ("실패", "완료"):
        bits = []
        a = meta.get("analysis_issues")
        s = meta.get("search_sources")
        if a is not None:
            bits.append(f"분석: 지적 {a}건")
        if s is not None:
            bits.append(f"서칭: 출처 {s}건")
        if meta.get("analysis_same_provider"):
            bits.append("분석자 같은 공급자")
        if bits:
            lines.append("  - " + ". ".join(bits))
    if status != "건너뜀" and (meta.get("executor") or meta.get("tokens")):
        who = EXECUTORS.get(meta.get("executor", ""), meta.get("executor") or "알 수 없음")
        tok = meta.get("tokens") or {}
        tok_text = f" 토큰: 출력 {int(tok.get('output', 0)):,}, 캐시 읽기 {int(tok.get('cache_read', 0)):,}" if tok else ""
        lines.append(f"  - 주체: {who}.{tok_text}")
    return lines


def _clean(text: str) -> str:
    """경로와 해시가 든 낱말을 지운다. 지우고 세 낱말이 안 남는 문장은 통째로 뺀다."""
    text = " ".join((text or "").split())
    kept = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        words = [w for w in sentence.split() if not _NOISE.search(w)]
        if len(words) >= 3 or (words and not _NOISE.search(sentence)):
            kept.append(re.sub(r"\(\s*\)", "", " ".join(words)).strip(" ,"))
    return " ".join(kept)


def _shorten(text: str, limit: int = RESULT_MAX) -> str:
    """limit자 안으로. 넘으면 문장 경계나 쉼표에서 자르고 말줄임을 붙인다. 끝 마침표는 뗀다."""
    text = _clean(text).rstrip(" .")
    if len(text) <= limit:
        return text
    head = text[: limit - 1]
    depth, cut = 0, -1
    for i, ch in enumerate(head):  # 괄호 안의 쉼표에서는 자르지 않는다
        depth += (ch == "(") - (ch == ")")
        if depth == 0 and ch in ".," and head[i + 1 : i + 2] == " ":
            cut = i
    if cut < limit // 3:
        cut = head.rfind(" ")
    if cut < limit // 3:
        cut = len(head)
    return head[:cut].rstrip(" .,") + "…"


def _open_count(meta: dict) -> int | None:
    """보고서 마지막 절(남은 일과 정할 것)의 번호 목록 항목 수. 보고서가 없으면 None."""
    run_id = meta.get("run_id")
    if not run_id:
        return None
    reports = sorted((RUNS / run_id).glob("attempt-*/report.md"), key=lambda p: int(p.parent.name.split("-")[-1]))
    if not reports:
        return None
    text = reports[-1].read_text(encoding="utf-8")
    heads = [m.end() for m in re.finditer(r"^## .*$", text, flags=re.M)]
    if not heads:
        return 0
    return len(re.findall(r"^\s*\d+[.)]\s", text[heads[-1]:], flags=re.M))


def slack_block(meta: dict, *, brief: bool = False) -> list[str]:
    """Slack용 작업 묶음. 기호와 프로젝트 줄, 결과 줄, 정할 것 줄(확인 필요면 규칙 줄까지).

    커밋, 주체, 토큰, 실행ID, 근거 경로, 시간은 넣지 않는다. brief(아침 집계)면 완료는 정할 것 줄 없이 두 줄로 줄인다.
    """
    status = meta.get("status") or "진행 중"
    st = shown(meta)
    lines = [f"{MARKS.get(st, '▶')} *{display_project(meta.get('project'))}* | {meta.get('title')} | {word(meta)}"]
    result = _shorten(meta.get("summary") or meta.get("reason") or "")
    if result:
        lines.append(f"결과: {result}")
    if status == "확인 필요":
        opts = meta.get("options") or []
        if opts:
            lines.append("정할 것: " + "  ".join(f"{chr(0x2460 + i)} {_shorten(o, 40)}" + (" (추천)" if i == 0 and "추천" not in o else "")
                                                for i, o in enumerate(opts[:10])))
        if meta.get("rule"):
            lines.append(f"규칙: {_shorten(meta['rule'], 50)}")
    elif status in ("완료", "실패") and not (brief and st == "완료"):  # 확인 전 완료는 아침 집계에도 정할 것 줄을 남긴다
        n = _open_count(meta)
        if n:
            lines.append(f"정할 것: {n}건 (대시보드 결과지)")
    if st == "확인 필요" and status != "확인 필요" and not brief and not to_choose(meta):
        lines.append("할 일: 결과지에서 확인만 하면 된다")
    return lines


def _slack_head(title: str, metas: list[dict]) -> str:
    counts = {s: 0 for s in SECTIONS}
    for m in metas:
        counts[section(m)] += 1
    return f"*{title}*  " + " | ".join(f"{s} {n}" + _failed_note(s, metas) for s, n in counts.items() if n)


def _failed_note(section: str, metas: list[dict]) -> str:
    """확인 필요 집계 뒤에 그중 확인하지 않은 실패 수를 붙인다. 실패가 확인 필요에 묻히지 않게 한다."""
    k = sum(1 for m in metas if m.get("status") == "실패" and shown(m) == "확인 필요")
    return f"(실패 {k} 포함)" if section == "확인 필요" and k else ""


def _slack_body(metas: list[dict], *, brief: bool = False) -> list[str]:
    out: list[str] = []
    for m in metas:
        out += ["", *slack_block(m, brief=brief)]
    return out


def build(date: str, *, extra_env: list[str] | None = None) -> tuple[str, str]:
    """(전문, Slack 요약)을 돌려준다."""
    metas = runs_for(date)
    by: dict[str, list[dict]] = {s: [] for s in SECTIONS}
    for m in metas:
        by[section(m)].append(m)
    # 확인 필요는 고를 것이 있는 것을 앞에, 확인만 하면 되는 것을 뒤에 둔다. 확인만 하는 것 안에서는 실패를 앞에 둔다
    by["확인 필요"].sort(key=lambda m: (not to_choose(m), m.get("status") != "실패"))
    # 큐에서 건너뛴 항목(기준 없음 등)은 runs/가 없으므로 큐에서 더한다
    for r in queue.load():
        if r["status"] == queue.SKIPPED and (r.get("finished") or "")[:10] == date and not r.get("run_id"):
            by["건너뜀"].append({"project": r["project"], "title": r["title"], "summary": r.get("reason", ""),
                               "evidence_ref": "미시작", "minutes_used": 0, "minutes_limit": r.get("est_minutes") or 0, "status": "건너뜀"})
    head = f"[jipsa] {date} " + ", ".join(f"{s} {len(by[s])}" + _failed_note(s, by[s]) for s in SECTIONS)
    full = [head, ""]
    from scheduler import night  # Auto 종합 보고 하나를 맨 위에서 가리킨다(261023-jipsa-39)

    night_line = night.slack_line(date)
    if night_line:
        full = [head, "", f"- {night_line}", ""]
    for s in SECTIONS:
        full.append(f"## {s}")
        if not by[s]:
            full.append("- 없음")
        if s == "확인 필요" and by[s]:
            pick = [m for m in by[s] if to_choose(m)]
            ack = [m for m in by[s] if not to_choose(m)]
            for name, group in (("고를 것이 있는 것", pick), ("확인만 하면 되는 것", ack)):
                if group:
                    full.append(f"### {name} {len(group)}건")
                    for m in group:
                        full += item_line(m)
            continue
        for m in by[s]:
            full += item_line(m)
    ordered = [m for s in SECTIONS for m in by[s]]
    # 완료된 cycle 단계는 Slack 아침 집계에서 cycle 묶음 하나로 갈음한다. 전문에는 단계마다 남는다.
    # 확인하지 않은 단계도 상태 값 완료면 묶음으로 갈음한다. 머리 줄 집계에는 확인 필요로 세어진다
    # 유인 모드 cycle에서 실패와 확인 필요로 끝난 중간 단계도 cycle 묶음의 끝 사유로 갈음한다. Auto 모드 실행은 그대로 둔다(261024-jipsa-05, 07)
    brief = [m for m in ordered if not ((m.get("cycle") and m.get("status") == "완료") or goal_quiet(m))]
    slack = [_slack_head(f"jipsa {date}", ordered)] + ([night_line] if night_line else []) + (_slack_body(brief, brief=True) if brief else ["", "작업 없음"])
    # 목표 cycle 묶음. 목표 한 줄 아래 Cycle마다 명령, 지표, 판정, 피드백 요지를 둔다. cycle이 없던 날은 절이 없다
    from scheduler import cycle

    cyc_full, cyc_slack = cycle.report_lines(date)
    if cyc_full:
        full += ["## cycle", *cyc_full]
        slack += cyc_slack
    rv_full, rv_slack = review_lines(metas)  # 비cycle 항목의 검수 피드백 요지와 반영 결과(261023-jipsa-11)
    if rv_full:
        full += ["## 단발 목표 분석과 반영 Cycle", *rv_full]
        slack += rv_slack
    env_lines = []
    pkgs = package_items(metas)
    if pkgs:
        env_lines.append("- 추가 패키지: " + ", ".join(pkgs))
    waits = [m["limit_wait"] for m in metas if m.get("limit_wait")]
    if waits:
        env_lines.append("- 한도 대기: " + "; ".join(waits))
    rwaits = [f"{display_project(m['project'])} {m['resource_wait']}" for m in metas if m.get("resource_wait")]
    if rwaits:
        env_lines.append("- 자원 대기: " + "; ".join(rwaits))
    env_lines += codex_lines(metas)
    env_lines += extra_env or []
    full.append("## 환경")
    full += env_lines or ["- 없음"]
    return "\n".join(full) + "\n", "\n".join(slack) + "\n"


def review_lines(metas: list[dict]) -> tuple[list[str], list[str]]:
    """원 실행마다 한 줄. 검수 피드백 요지(부족과 개선 첫 항목, 수)와 반영 결과다. 검수와 반영은 원 실행을 from_run으로 건다."""
    from scheduler import review

    kids: dict[str, dict] = {}
    for m in metas:
        parent = m.get("review_of") or m.get("revise_of") or m.get("from_run")
        title = str(m.get("title") or "")
        kind = "review" if m.get("review_of") or title.endswith(f" {review.REVIEW}") else (
            "revise" if m.get("revise_of") or title.endswith(f" {review.REVISE}") else "")
        if parent and kind:
            kids.setdefault(parent, {})[kind] = m
    full, slack = [], []
    for parent, k in kids.items():
        orig = next((m for m in metas if m.get("run_id") == parent), None) or _read_json(RUNS / parent / "meta.json") or {}
        rv, rs = k.get("review"), k.get("revise")
        if rv:
            fb = review.feedback(rv["run_id"])
            n = len(fb["gaps"]) + len(fb["improve"])
            gist = (fb["gaps"] + fb["improve"])[:1]
            fb_text = (f"부족 {len(fb['gaps'])}, 개선 {len(fb['improve'])}" + (f", 첫 지적 {_shorten(gist[0], 60)}" if gist else "")) if n else (
                "고칠 것 없음" if rv.get("status") in ("완료", "확인 필요") else f"검수 {rv.get('status') or '진행 중'}")
        else:
            fb_text = "검수 없음"
        rs_text = f"{rs.get('status') or '진행 중'}, {_shorten(rs.get('summary') or rs.get('reason') or '', 60)}" if rs else "반영 없음"
        name = f"{display_project(orig.get('project') or (rv or rs or {}).get('project'))} | {orig.get('title') or parent}"
        # 고칠 것이 없는 검수는 반영 없이 완료로 끝난다(261023-jipsa-12)
        passed = fb_text == "고칠 것 없음" and not rs
        full.append(f"- {name} | 검수 통과, 반영 없음" if passed else f"- {name} | 검수: {fb_text} | 반영: {rs_text}")
        slack += ["", f"🔍 *{name.split(' | ')[0]}* | {name.split(' | ', 1)[-1]} 검수와 반영",
                  "결과: 검수 통과, 반영 없음" if passed else f"결과: {_shorten(f'검수 {fb_text}, 반영 {rs_text}', RESULT_MAX)}"]
    return full, slack


def package_items(metas: list[dict]) -> list[str]:
    """추가 패키지 항목을 "프로젝트: 패키지 버전"으로 만든다. 기록에 "프로젝트에 패키지"가 이미 있으면 그 프로젝트를 쓰고, 없으면 실행 프로젝트를 붙인다(대시보드와 같은 규칙)."""
    out = []
    for m in metas:
        for p in m.get("added_packages") or []:
            i = p.find("에 ")
            out.append(f"{p[:i]}: {p[i + 2:]}" if i > 0 else f"{display_project(m['project'])}: {p}")
    return out


def codex_lines(metas: list[dict]) -> list[str]:
    """Codex 창 환경 줄과 그 아래 Claude 5시간 창 줄. Codex 줄은 창에 호출이 있거나 그날 Claude로 전환한 일이 있을 때만 쓰고,
    Claude 줄은 기록이 하나라도 있으면 쓴다. 글자는 대시보드 환경 줄과 같다."""
    from scheduler import claude_window, codex_window

    w = codex_window.window()
    n = sum(1 for m in metas for s in m.get("provider_switches") or [] if s.get("to") == codex_window.CLAUDE)
    out = []
    if w["calls"] or w["limit_hit"] or n:
        out.append(f"- {codex_window.state_text(w)}" + (f", Codex 한도 응답으로 Claude 전환 {n}회" if n else ""))
    u = claude_window.usage()
    if u["seen"]:
        out.append(f"- {u['text']}")
    return out


def write(date: str, extra_env: list[str] | None = None) -> Path:
    full, _ = build(date, extra_env=extra_env)
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"{date}.md"
    path.write_text(full, encoding="utf-8")
    return path


def goal_quiet(meta: dict) -> str:
    """유인 모드 cycle의 중간 단계라 Slack 글을 보내지 않는 이유. 보내야 하면 빈 값이다(261024-jipsa-05).

    유인 모드에서 Main이 지휘하는 cycle의 이행과 분석은 중간 단계다. 목표 정하기와 Cycle 종합 보고만 보낸다.
    금지 사항의 확인 필요로 끝난 이행은 그 cycle을 멈추고 사람이 바로 봐야 하므로 중간 단계라도 보낸다.
    Auto 모드에서 시작한 실행은 cycle 단계와 단발 목표를 포함해 이 규칙을 쓰지 않고 원래의 Auto 묶음 규칙을 따른다(261024-jipsa-07).
    """
    # cycle이 이 모듈을 부르므로 늦게 부른다
    from scheduler import cycle, modes

    if meta.get("mode") == modes.AUTO:
        return ""
    title = str(meta.get("title") or "")
    step = meta.get("cycle_step") or ""
    if meta.get("cycle") or step:
        if step in (cycle.SETUP, cycle.FINAL) or (not step and title.endswith((f" {cycle.SETUP}", f" {cycle.FINAL}"))):
            return ""
        rule = str(meta.get("rule") or "")
        if step == cycle.RUN and meta.get("status") == "확인 필요" and (cycle._FATAL.search(rule) or cycle._PUSH.search(rule)):
            return ""
        return "cycle 중간 단계"
    return ""



# ----- 바로 보내는 Slack 글(261025-jipsa-20, TODO 3단계 가안) -----
# 확인 필요와 실패만 바로 보낸다. 글 하나에 머리 줄, 결과지 요약 세 줄, 고를 것 줄, 답하는 곳 줄을 링크 없이 넣는다.
# 완료는 바로 보내지 않는다. 기획 3판 5절의 가안 양식이고, 사람이 "확인 필요와 실패만"을 골랐다.
SEND_NOW = ("확인 필요", "실패")
ANSWER_AT = "원격 세션이 켜져 있으면 폰에서, 아니면 돌아와서 대시보드"
BOX_KEYS = ("한 일", "결과", "사람이 할 일")
BOX_MAX = 200  # 요약 한 줄의 글자 상한. 넘으면 문장 경계에서 자른다
OPTION_MAX = 30  # 선택지 이름 뒤에 붙이는 짧은 내용의 글자 상한
OPTIONS_SHOWN = 6
_BOX_LINE = re.compile(r"^\s*\*\*\s*(한 일|결과|사람이 할 일)\s*\*\*\s*[:：]\s*(.+?)\s*$")


def summary_box(run_id: str) -> dict[str, str]:
    """마지막 시도 보고서 맨 위 요약 상자의 세 줄. 상자가 없거나 보고서가 없으면 빈 dict다(옛 결과지)."""
    reports = sorted((RUNS / run_id).glob("attempt-*/report.md"), key=lambda p: int(p.parent.name.split("-")[-1])) if run_id else []
    if not reports:
        return {}
    try:
        text = reports[-1].read_text(encoding="utf-8")
    except OSError:
        return {}
    m = re.search(r"^```요약[ \t]*\n(.*?)^```", text, flags=re.M | re.S)
    out: dict[str, str] = {}
    for line in (m.group(1) if m else "").splitlines():
        b = _BOX_LINE.match(line)
        if b and b.group(1) not in out:
            body = _shorten(b.group(2).replace("**", ""), BOX_MAX)
            if body:
                out[b.group(1)] = body
    return out


def option_names(meta: dict) -> list[str]:
    """고를 것 줄의 선택지 이름. '가안 Slack 글에 요약(추천)' 꼴이고 추천 표시가 없으면 맨 앞이 추천이다(작업자 규격: 추천을 맨 앞에)."""
    from scheduler import record  # record가 이 모듈을 부르므로 늦게 부른다

    opts = [str(o).replace("**", "").strip() for o in meta.get("options") or []]
    opts = [o for o in opts if o]
    if not opts:
        return []
    marked = any("추천" in o for o in opts)
    names = record.option_names(opts)
    out = []
    for i, (name, text) in enumerate(zip(names, opts)):
        rest = re.sub(r"^\s*(?:[(\[]추천[)\]]\s*|추천\s*[:.]?\s*)", "", text)  # 머리의 추천 표시를 뗀다
        if record.alt_name(text):  # 안 이름(가안, 1안, A안)을 떼고 내용만 남긴다
            rest = re.sub(r"^" + r"\s?".join(map(re.escape, name)) + r"\s*[:.)\-]?\s*", "", rest)
        rest = re.sub(r"\s*[(\[]추천[)\]]", "", rest)
        rest = re.split(r"(?<=[^0-9])[.:]\s|\s\(|\(", rest, maxsplit=1)[0].strip(" .:")
        rest = _shorten(rest, OPTION_MAX) if rest else ""
        rec = ("추천" in text) if marked else i == 0
        out.append(f"{name} {rest}".strip() + ("(추천)" if rec else ""))
    if len(out) > OPTIONS_SHOWN:
        out = out[:OPTIONS_SHOWN] + [f"그 밖 {len(opts) - OPTIONS_SHOWN}개"]
    return out


def card_skip(meta: dict) -> str:
    """바로 보내지 않는 사유. 보내야 하면 빈 값이다. 완료는 보내지 않고, 유인 모드 cycle의 중간 단계도 보내지 않는다."""
    status = meta.get("status") or "진행 중"
    if status not in SEND_NOW:
        return "완료 결과지" if status == "완료" else f"{status} 상태"
    return goal_quiet(meta)


def card_lines(head: str, box: dict[str, str], fallback: str, options: list[str], *, answer: bool = True) -> list[str]:
    """Slack 글 줄. 머리 줄, 요약 세 줄(없으면 결과 한 줄), 고를 것, 답하는 곳 순서다. Auto 끝 글도 이 틀을 쓴다."""
    lines = [head]
    if box:
        lines += [f"{k}: {box[k]}" for k in BOX_KEYS if box.get(k)]
    elif fallback:
        lines.append(f"결과: {fallback}")
    if options:
        lines.append("고를 것: " + ", ".join(options))
    if answer:
        lines.append(f"답하는 곳: {ANSWER_AT}")
    return lines


def card(meta: dict, *, note: str = "") -> str:
    """확인 필요와 실패 결과지의 Slack 글 하나. 링크와 실행ID를 넣지 않는다.

    요약 상자가 없는 옛 결과지는 summary 한 줄(없으면 사유)을 결과 줄로 대신한다. note는 머리 줄 뒤에 붙는다(정정).
    """
    from scheduler import attack

    status = meta.get("status") or "진행 중"
    head = f"[{status}] {display_project(meta.get('project'))}, {meta.get('title')}" + (f" ({note})" if note else "")
    head += attack.slack_tail(meta.get("attack"))  # 공격이 있었으면 머리 줄 끝에 Sol 지적 수만 붙인다(261024-jipsa-11)
    fallback = _shorten(meta.get("summary") or meta.get("reason") or "", BOX_MAX)
    return "\n".join(card_lines(head, summary_box(meta.get("run_id") or ""), fallback, option_names(meta)))
