"""지난 단발 목표의 분석과 반영 Cycle 기록 읽기(261023-jipsa-39). 그날 보고가 옛 실행의 분석 판정을 보일 때 쓴다.

분석 실행은 result.json의 check 칸에 체크 항목별 O와 X를, 옛 검수 실행은 review 칸에 부족과 개선을 적었다. 분석과 반영 줄은 원 실행을
review_of, revise_of로 걸었다. 이 줄을 큐에 넣고 잇던 경로는 261026-jipsa-08에서 뗐다. Auto 줄(층 auto)과 Cycle 단계 줄(층 cycle)은
그 경로의 층(필수, 확장, 예비)에 들지 않아 들어갈 수 없었고, 그 층의 새 작업자 줄을 만드는 곳도 없었다.
"""

from __future__ import annotations

from scheduler import record

REVIEW, REVISE = "분석", "반영 Cycle 2"
LIMIT = 5  # 칸마다 지적 상한
CHECK_MAX = 12  # 체크 항목 상한


def _block(run_id: str) -> dict:
    dirs = record.attempt_dirs(run_id)
    return (record.read_json(dirs[-1] / "result.json") or {}) if dirs else {}


def checks(run_id: str) -> dict:
    """분석 실행의 체크 판정. {items, ox, human, x, gaps, improve, verdict}. ox는 사람 확인을 뺀 체크가 모두 O일 때 O다.
    체크 칸이 없는 옛 검수 기록은 review 칸의 부족 목록으로 본다(부족이 없으면 O)."""
    res = _block(run_id)
    clean = lambda xs: [str(x).strip() for x in (xs or []) if str(x).strip()][:LIMIT]  # noqa: E731
    ck = res.get("check") if isinstance(res.get("check"), dict) else None
    if ck is None:
        rv = res.get("review") if isinstance(res.get("review"), dict) else {}
        gaps = clean(rv.get("gaps"))
        ox = ("O" if not gaps else "X") if rv else ""
        return {"items": [], "ox": ox, "human": [], "x": gaps, "gaps": gaps, "improve": clean(rv.get("improve")),
                "verdict": str(rv.get("verdict") or "")}
    items = []
    for x in (ck.get("items") or [])[:CHECK_MAX]:
        if not isinstance(x, dict) or not str(x.get("item") or "").strip():
            continue
        items.append({"item": str(x["item"]).strip(), "ox": "O" if str(x.get("ox") or "").strip().upper() == "O" else "X",
                      "evidence": str(x.get("evidence") or "").strip()[:200], "human": bool(x.get("human"))})
    machine = [x for x in items if not x["human"]]
    xs = [x["item"] for x in machine if x["ox"] != "O"]
    ox = "O" if machine and not xs else "X"
    return {"items": items, "ox": ox, "human": [x["item"] for x in items if x["human"]], "x": xs,
            "gaps": xs[:LIMIT], "improve": clean(ck.get("improve")), "verdict": "충분" if ox == "O" else "보완 필요"}


def feedback(run_id: str) -> dict:
    """옛 이름. 보고가 쓰는 {gaps, improve, verdict}다."""
    c = checks(run_id)
    return {"gaps": c["gaps"], "improve": c["improve"], "verdict": c["verdict"]}
