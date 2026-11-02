"""판 수로 실험 상한을 정한다(261023-jipsa-23 1안, 사람 답 "보드게임만 판 수 대비로").

계산 예산 = max(판 수 x 판 시간의 합 / 동시 수, 가장 긴 판 시간) x 1.2이고, 상한 = 계산 예산 + 마무리 여유 20분이다.
판 수가 동시 수보다 적으면 합을 동시 수로 나눈 값이 가장 긴 한 판보다 짧아지므로 둘 중 큰 값을 쓴다.
판 시간은 등록부 [match_minutes] 표의 "게임:인원" 값이고, 인원이 없는 칸은 "게임" 값, 둘 다 없으면 보수적 기본값이다.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

SAFETY = 1.2
WRAPUP_MIN = 20
DEFAULT_MATCH_MIN = 60.0  # 표에 없는 게임과 인원. 지금까지 잰 판 가운데 가장 긴 것(4인 57분)보다 길다


class GamesError(ValueError):
    """--games 문자열을 읽지 못했다."""


def parse_games(text: str) -> list[tuple[str, str, int]]:
    """"game_a:4:28,game_b:4:22" 또는 인원 없는 "game_c:40"을 [(게임, 인원, 판 수)]로 읽는다."""
    out = []
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        bits = [b.strip() for b in part.split(":")]
        if len(bits) == 2:
            bits = [bits[0], "", bits[1]]
        if len(bits) != 3 or not bits[0] or not bits[2].isdigit() or int(bits[2]) <= 0 or (bits[1] and not bits[1].isdigit()):
            raise GamesError(f"'{part}'를 읽지 못했다. 게임:인원:판 수(인원 없으면 게임:판 수)를 쉼표로 잇는다. 예: game_a:4:28,game_b:4:22")
        out.append((bits[0].lower(), bits[1], int(bits[2])))
    if not out:
        raise GamesError("--games가 비었다")
    return out


def budget(games: list[tuple[str, str, int]], parallel: int, table: dict[str, float]) -> dict:
    """계산 근거 dict. meta의 match_budget로 그대로 남긴다."""
    if parallel <= 0:
        raise GamesError("--parallel은 1 이상이어야 한다")
    rows, missing = [], []
    for game, players, n in games:
        key = f"{game}:{players}" if players else game
        per = table.get(key)
        if per is None and players:
            per = table.get(game)
        defaulted = per is None
        if defaulted:
            per = DEFAULT_MATCH_MIN
            missing.append(key)
        rows.append({"game": game, "players": players, "matches": n, "match_minutes": float(per), "default": defaulted})
    total = sum(r["matches"] * r["match_minutes"] for r in rows)
    longest = max(r["match_minutes"] for r in rows)
    spread = total / parallel
    compute = math.ceil(max(spread, longest) * SAFETY)
    return {
        "rows": rows, "parallel": parallel, "match_total": sum(r["matches"] for r in rows), "match_minutes_sum": round(total, 1),
        "spread_minutes": round(spread, 1), "longest_minutes": longest, "safety": SAFETY, "compute_minutes": compute,
        "wrapup_minutes": WRAPUP_MIN, "limit_minutes": compute + WRAPUP_MIN, "defaulted": missing,
    }


def stop_at(started: str | datetime, b: dict) -> str:
    """새 판 시작 마감 시각 = 시작 + 계산 예산."""
    t = datetime.fromisoformat(started) if isinstance(started, str) else started
    return (t + timedelta(minutes=b["compute_minutes"])).isoformat(timespec="minutes")


def rows_text(b: dict) -> str:
    """'game_a 4인 28판 x 42분, game_b 4인 22판 x 27.3분' 꼴. 기본값을 쓴 칸은 (기본값)을 붙인다."""
    return ", ".join(f"{r['game']}{' ' + r['players'] + '인' if r['players'] else ''} {r['matches']}판 x {r['match_minutes']:g}분"
                     + (" (기본값)" if r["default"] else "") for r in b["rows"])


def formula_text(b: dict) -> str:
    base = (f"합 {b['match_minutes_sum']:g}분 / 동시 {b['parallel']} = {b['spread_minutes']:g}분" if b["spread_minutes"] >= b["longest_minutes"]
            else f"가장 긴 판 {b['longest_minutes']:g}분(합 {b['match_minutes_sum']:g}분 / 동시 {b['parallel']} = {b['spread_minutes']:g}분보다 길다)")
    return f"{base} x {b['safety']:g} = 계산 예산 {b['compute_minutes']}분, + 마무리 {b['wrapup_minutes']}분 = 상한 {b['limit_minutes']}분"


def short_text(b: dict) -> str:
    """대시보드 머리줄용 한 줄."""
    return f"{b['match_total']}판 동시 {b['parallel']}, 계산 {b['compute_minutes']}분 + 마무리 {b['wrapup_minutes']}분"
