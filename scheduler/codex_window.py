"""Codex 창 기록과 공급자 선택(261022-jipsa-02, 261022-jipsa-14 이어받기).

5시간 사용 창은 Codex에만 있으므로 화면과 보고에서는 Codex 창이라고 부른다.

상태 폴더의 호출 장부(codex_calls.jsonl)에 한 줄씩 `{ts, kind, stage, run}`을 붙인다. kind는 `call`(호출 시작)이나
`limit`(한도 응답)이다. 창은 고정 시각이 아니라 지금부터 거꾸로 5시간이고, 재설정 시각은 창 안 첫 줄에 5시간을 더한 값이다.
실측 비율은 Codex 앱 서버의 계정 한도 조회(토큰을 쓰지 않는 읽기)와 세션 파일의 rate_limits 줄 가운데 더 새 것이다.
실측이 있으면 상태는 실측 비율로 정하고, 실측이 없을 때만 호출 횟수로 어림한다. 한도 응답은 그 뒤 실측이 없을 때만 우선한다(261023-jipsa-02).

상태는 여유, 한도 둘이고 표시에만 쓴다. 한도는 한도 응답을 받았거나 사용량이 100%에 닿은 때다.
비율과 상태는 작업과 마감 전 Sol 공격을 막지 않고 공급자를 바꾸지 않는다(261102-jipsa-42, 261102-jipsa-44 사용자 답). Codex로 갈 일은 95%든 100%든 Codex로 간다.
실제 호출이 한도 오류로 끝난 뒤의 처리만 호출한 쪽(runner, attack)에 있다.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
from datetime import datetime, timedelta
from pathlib import Path

from scheduler.config import CODEX_WINDOW_CALLS, STATE, now, parse_iso, setting

WINDOW = timedelta(hours=5)
KEEP = timedelta(hours=6)  # 장부 정리 기준
FREE, LIMIT = "여유", "한도"
CLAUDE, CODEX = "claude", "codex"
PROVIDERS = (CLAUDE, CODEX)
ATTACK_PROVIDERS = ("codex", "claude", "none")


def attack_provider() -> str:
    """공격 공급자 설정값(261103-jipsa-02 사용자 답 1안). 기본은 codex이고 모르는 값도 codex로 본다."""
    value = setting("JIPSA_ATTACK_PROVIDER", "codex").lower()
    return value if value in ATTACK_PROVIDERS else "codex"


def codex_installed() -> bool:
    return shutil.which("codex") is not None


def effective_attack_provider() -> str:
    """실제로 도는 공격 공급자. codex를 골랐는데 실행 파일이 없으면 none과 같게 돈다(Claude가 대신 공격하지 않는다)."""
    p = attack_provider()
    return "none" if p == "codex" and not codex_installed() else p


def codex_shown() -> bool:
    """사용 창 표시에 Codex 칸을 보일지. 공급자가 codex가 아니거나 실행 파일이 없으면 숨긴다."""
    return attack_provider() == "codex" and codex_installed()

LEDGER = STATE / "codex_calls.jsonl"
_lock = threading.Lock()


def _rows() -> list[dict]:
    if not LEDGER.exists():
        return []
    out = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            row["_t"] = parse_iso(row["ts"])
            out.append(row)
        except (ValueError, KeyError):
            continue
    return out


def _append(kind: str, stage: str, run: str | None, at: datetime | None = None) -> None:
    at = at or now()
    row = {"ts": at.isoformat(timespec="seconds"), "kind": kind, "stage": stage, "run": run or ""}
    with _lock:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        keep = [r for r in _rows() if r["_t"] > at - KEEP]
        lines = [json.dumps({k: v for k, v in r.items() if k != "_t"}, ensure_ascii=False) for r in keep]
        lines.append(json.dumps(row, ensure_ascii=False))
        LEDGER.write_text("\n".join(lines) + "\n", encoding="utf-8")


def record_call(stage: str, run: str | None = None, at: datetime | None = None) -> None:
    """Codex 호출 하나를 장부에 붙인다. 분석자 호출과 작업자 구간 호출을 모두 센다. 6시간이 지난 줄은 이때 지운다."""
    _append("call", stage, run, at)


def record_limit(stage: str, run: str | None = None, at: datetime | None = None) -> None:
    _append("limit", stage, run, at)


def _sessions_dir() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "sessions"


def _rate_pct(w: dict | None, at: datetime) -> dict:
    """한 창의 사용 비율. 초기화 시각이 지났으면 0%이고 cleared가 참이다."""
    w = w or {}
    if w.get("used") is None:
        return {"pct": None, "reset": None, "cleared": False}
    reset = w.get("reset")
    cleared = bool(reset and reset <= at)
    return {"pct": 0.0 if cleared else float(w["used"]), "reset": reset, "cleared": cleared}


def _from_epoch(v) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(v)) if v else None
    except (TypeError, ValueError, OSError):
        return None


_tail_cache: dict[str, tuple[int, dict | None]] = {}  # 세션 파일별 (크기, 마지막 기록). 크기가 같으면 다시 읽지 않는다


def _file_last(f: Path) -> dict | None:
    """세션 파일 끝 512KB에서 마지막 rate_limits 줄. 줄의 timestamp(UTC)를 지역 시각으로 바꿔 seen에 둔다."""
    try:
        size = f.stat().st_size
    except OSError:
        return None
    hit = _tail_cache.get(str(f))
    if hit and hit[0] == size:
        return hit[1]
    found = None
    try:
        with f.open("rb") as fh:
            fh.seek(max(0, size - 512 * 1024))
            lines = fh.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if '"rate_limits"' not in line:
            continue
        try:
            row = json.loads(line)
            rl = row["payload"]["rate_limits"] or {}
            five, week = rl.get("primary") or {}, rl.get("secondary") or {}
            seen = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00")).astimezone().replace(tzinfo=None, microsecond=0)
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        if not five and not week:
            continue
        found = {"five": {"used": five.get("used_percent"), "reset": _from_epoch(five.get("resets_at"))},
                 "week": {"used": week.get("used_percent"), "reset": _from_epoch(week.get("resets_at"))},
                 "seen": seen, "source": "세션 기록"}
        break
    _tail_cache[str(f)] = (size, found)
    return found


def _session_last(at: datetime, days: int) -> dict | None:
    """최근 세션 파일들의 rate_limits 가운데 기록 시각이 가장 늦은 것.

    Windows는 Codex가 열어 둔 세션 파일의 수정 시각을 만든 시각에 묶어 두므로 수정 시각 순으로 고르지 않는다.
    """
    root = _sessions_dir()
    files: list[Path] = []
    for back in range(days + 1):
        d = (at - timedelta(days=back)).date()
        folder = root / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.day:02d}"
        if folder.is_dir():
            files += folder.glob("rollout-*.jsonl")
    best = None
    for f in sorted(files, key=lambda p: p.name, reverse=True)[:40]:
        rec = _file_last(f)
        if rec and rec["seen"] <= at and (best is None or rec["seen"] > best["seen"]):
            best = rec
    return best


LIVE_FILE = STATE / "codex_usage.json"
LIVE_TTL = timedelta(minutes=5)
LIVE_ON = setting("JIPSA_CODEX_LIVE", "1") not in ("0", "off", "false")
_live_lock = threading.Lock()


def _ask_live(timeout: int = 20) -> dict:
    """Codex 앱 서버에 계정 사용 한도를 묻는다. 모델을 부르지 않는 읽기 호출이라 창을 쓰지 않는다."""
    import subprocess

    from adapters.codex import _env, command
    from scheduler.nowindow import hidden

    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "jipsa", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "account/rateLimits/read"}]
    p = subprocess.Popen(command() + ["app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True, encoding="utf-8", errors="replace", env=_env(), **hidden())
    got: list[dict] = []

    def read() -> None:
        for line in p.stdout:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("id") == 2:
                got.append(row)
                return

    t = threading.Thread(target=read, daemon=True)
    t.start()
    try:
        p.stdin.write("".join(json.dumps(m) + "\n" for m in msgs))
        p.stdin.flush()
        t.join(timeout)
    finally:
        try:
            p.stdin.close()
        except OSError:
            pass
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
    if not got or "result" not in got[0]:
        raise RuntimeError("한도 조회 응답 없음")
    rl = got[0]["result"].get("rateLimits") or {}
    five, week = rl.get("primary") or {}, rl.get("secondary") or {}
    return {"five": {"used": five.get("usedPercent"), "reset": five.get("resetsAt")},
            "week": {"used": week.get("usedPercent"), "reset": week.get("resetsAt")},
            "reached": rl.get("rateLimitReachedType")}


def _live(at: datetime) -> dict | None:
    """계정 한도 조회 결과. 상태 폴더에 5분 동안 보관하고, 실패도 5분 동안 다시 묻지 않는다.
    지난 시각을 넣은 호출(임시 상태 폴더 점검)에서는 새로 묻지 않는다."""
    try:
        cached = json.loads(LIVE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cached = {}
    asked = parse_iso(cached["asked"]) if cached.get("asked") else None
    fresh_call = abs((now() - at).total_seconds()) < 120
    if LIVE_ON and fresh_call and (asked is None or now() - asked >= LIVE_TTL) and _live_lock.acquire(blocking=False):
        try:
            try:
                got = {**_ask_live(), "seen": now().isoformat(timespec="seconds")}
            except Exception as e:  # 조회 실패는 세션 기록이나 어림으로 돌아간다
                got = {**{k: v for k, v in cached.items() if k != "error"}, "error": str(e)[:120]}
            cached = {**got, "asked": now().isoformat(timespec="seconds")}
            LIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
            LIVE_FILE.write_text(json.dumps(cached, ensure_ascii=False), encoding="utf-8")
        finally:
            _live_lock.release()
    if not cached.get("seen") or not cached.get("five"):
        return None
    seen = parse_iso(cached["seen"])
    if seen > at + timedelta(minutes=2):  # 방금 물은 값은 at보다 몇 초 늦다
        return None
    return {"five": {"used": cached["five"].get("used"), "reset": _from_epoch(cached["five"].get("reset"))},
            "week": {"used": (cached.get("week") or {}).get("used"), "reset": _from_epoch((cached.get("week") or {}).get("reset"))},
            "seen": seen, "source": "계정 조회", "reached": cached.get("reached")}


def usage(at: datetime | None = None, days: int = 2) -> dict | None:
    """Codex 실측 사용 비율. `{five, week, five_reset, week_reset, five_cleared, week_cleared, seen, source, reached}`이고
    실측이 없으면 None이다.

    계정 한도 조회와 세션 파일의 rate_limits 줄(261022-jipsa-47) 가운데 기록 시각이 늦은 것을 쓴다. 사용자가 직접 쓴
    Codex도 같은 계정 창이라 호출 수 어림보다 정확하다. 초기화 시각이 지난 창은 0%로 보고 cleared를 참으로 둔다.
    """
    at = at or now()
    recs = [r for r in (_live(at), _session_last(at, days)) if r]
    if not recs:
        return None
    rec = max(recs, key=lambda r: r["seen"])
    f5, fw = _rate_pct(rec["five"], at), _rate_pct(rec["week"], at)
    return {"five": f5["pct"], "week": fw["pct"], "five_reset": f5["reset"], "week_reset": fw["reset"],
            "five_cleared": f5["cleared"], "week_cleared": fw["cleared"], "seen": rec["seen"], "source": rec["source"],
            "reached": rec.get("reached") if not f5["cleared"] else None}


def window(at: datetime | None = None) -> dict:
    """지금 창의 상태. `{state, calls, cap, reset_at, limit_hit, five_pct, week_pct, ...}`.

    실측이 있으면 5시간과 주간 비율 가운데 큰 값으로 상태를 정한다. 장부의 한도 응답은 그 뒤에 들어온 실측이 없을 때만 한도로 친다.
    실측이 없으면 호출 수를 기준 횟수로 나눈 어림이다. reset_at은 HH:MM이고 모르면 빈 문자열이다.
    """
    at = at or now()
    u = usage(at)
    with _lock:
        inside = [r for r in _rows() if at - WINDOW < r["_t"] <= at]
        calls = sum(r.get("kind") == "call" for r in inside)
        hits = [r["_t"] for r in inside if r.get("kind") == "limit"]
        if u and u["five_cleared"] and u["five_reset"]:
            hits = [t for t in hits if t >= u["five_reset"]]  # 초기화 전에 받은 한도 응답은 지난 창의 것이다
        start = min((r["_t"] for r in inside), default=None)
        cap = CODEX_WINDOW_CALLS
        measured = u is not None and u["five"] is not None
        hit = bool(hits) and not (measured and u["seen"] >= max(hits))  # 한도 응답 뒤 실측이 들어왔으면 실측이 우선이다
        pct = max(u["five"], u["week"] or 0.0) if measured else 100.0 * calls / max(1, cap)
        if hit or pct >= 100 or (measured and u.get("reached")):
            state = LIMIT
        else:
            state = FREE
        if measured:
            reset = u["five_reset"] if not u["five_cleared"] else None
        else:
            reset = start + WINDOW if start else None
        out = {"state": state, "calls": calls, "cap": cap, "reset_at": f"{reset:%H:%M}" if reset else "",
               "reset_iso": reset.isoformat(timespec="minutes") if reset else "", "limit_hit": hit,
               "pct": round(pct, 1), "source": u["source"] if measured else "어림"}
        if measured:
            out.update(five_pct=u["five"], week_pct=u["week"], five_cleared=u["five_cleared"], week_cleared=u["week_cleared"],
                       cleared_at=f"{u['five_reset']:%H:%M}" if u["five_cleared"] and u["five_reset"] else "",
                       week_reset_at=f"{u['week_reset']:%m-%d %H:%M}" if u["week_reset"] and not u["week_cleared"] else "",
                       usage_seen=u["seen"].isoformat(timespec="minutes"), five_reset_at=out["reset_at"],
                       # 화면 막대가 초기화까지 남은 시간을 셀 때 쓴다. 지난 시각이면 cleared 칸이 참이다
                       five_reset_iso=u["five_reset"].isoformat(timespec="minutes") if u["five_reset"] else "",
                       week_reset_iso=u["week_reset"].isoformat(timespec="minutes") if u["week_reset"] else "")
        return out


def env_text(w: dict | None = None) -> str:
    """환경 줄 글자. 실측이 있으면 `Codex 5시간 창 사용 12%, 11:58 초기화, 주간 3%`이고, 초기화 시각이 지났으면
    `Codex 5시간 창 초기화됨(23:34), 주간 19%`다. 기록이 1시간보다 오래되면 끝에 기록 시각을 붙인다.
    실측이 없으면 `Codex 5시간 창 실측 없음, 호출 어림 12/40회, 03:10 초기화`다."""
    w = w or window()
    if w.get("five_pct") is not None:
        if w.get("five_cleared"):
            text = f"Codex 5시간 창 초기화됨({w['cleared_at']})" if w.get("cleared_at") else "Codex 5시간 창 초기화됨"
        else:
            text = f"Codex 5시간 창 사용 {w['five_pct']:g}%" + (f", {w['reset_at']} 초기화" if w.get("reset_at") else "")
        if w.get("week_pct") is not None:
            text += ", 주간 초기화됨" if w.get("week_cleared") else f", 주간 {w['week_pct']:g}%"
        seen = parse_iso(w["usage_seen"]) if w.get("usage_seen") else None
        if seen and now() - seen > timedelta(hours=1):
            text += f" ({seen:%m-%d %H:%M} 기록)"
        return text
    text = f"Codex 5시간 창 실측 없음, 호출 어림 {w['calls']}/{w['cap']}회"
    return text + (f", {w['reset_at']} 초기화" if w["reset_at"] else "")


def with_usage(w: dict | None = None) -> dict:
    """옛 호출 자리. 이제 window가 실측을 함께 돌려준다."""
    return dict(w or window())


def state_text(w: dict | None = None) -> str:
    """상태 글자. `여유, Codex 5시간 창 사용 12%, 11:58 초기화`다. 표시만 하고 공급자 선택에 쓰지 않는다."""
    w = w or window()
    return f"{w['state']}, {env_text(w)}"


def pick_worker(requested: str) -> str:
    """작업자 공급자. 요청한 공급자를 그대로 쓴다. Codex 창 비율과 상태는 보지 않는다(261102-jipsa-42)."""
    return requested if requested in PROVIDERS else CLAUDE


def pick_analyst(worker: str) -> str:
    """분석자 공급자. 작업자와 다른 공급자로 둔다. Codex 창 비율과 상태는 보지 않는다(261102-jipsa-42)."""
    return CLAUDE if worker == CODEX else CODEX
