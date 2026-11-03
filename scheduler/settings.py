"""전역 설정의 항목 목록과 저장(261102-jipsa-26에서 시작, 261102-jipsa-34에서 스킬용으로 바꿨다).

대시보드 설정 탭을 없애고 /jipsa-slack, /jipsa-model, /jipsa-config, /jipsa-cleanup 스킬이 jipsa settings 명령으로 이 모듈을 부른다.
전역 설정은 상태 폴더의 config.json 한 장에 두고 키는 환경 변수 이름 그대로다. 읽는 순서는 환경 변수, 설정 파일, 기본값이다(config.setting).
환경 변수나 .env가 덮은 칸은 저장을 거절한다. .env는 읽기만 한다. 비밀값은 설정 파일에 두지 않고 설정됨 여부만 보인다.
저장은 직전 판 하나를 config.prev.json에 남기고, 되돌리기는 두 판을 맞바꾼다. 저장한 값은 스케줄러와 대시보드를 다시 띄워야 반영된다.
여기에 없는 값(측정 내부 조정값, 설치 때 한 번 정하는 폴더와 포트)은 환경 변수로만 바꾼다.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from dotenv import dotenv_values

from scheduler.config import CONFIG_FILE, CONFIG_PREV_FILE, ROOT, SECRETS_FILE, STATE, WEB_PORT, file_values, now_iso, redact, secret, setting

# 묶음은 부르는 스킬이다. config는 /jipsa-config, slack은 /jipsa-slack, model은 /jipsa-model, cleanup은 /jipsa-cleanup이다
SKILLS = ("config", "slack", "model", "cleanup")

# 항목 하나는 (키, 스킬, 한글 이름, 설명 한 문장, 형식, 기본값, 선택). 형식은 int, str, bool, ratio(0~1을 %로 보임), hhmm, path, url, secret다.
# 선택: unit(단위 글자), min, max, options(고를 값), note(기본값 설명)
I = dict
ITEMS: list[dict] = [
    I(key="JIPSA_CONCURRENCY", group="config", name="동시 작업 수", desc="스케줄러가 한 번에 돌리는 작업 수의 상한이다.", kind="int", default="3", unit="개", min=1, max=20),
    I(key="JIPSA_AUTO_CAP", group="config", name="자동 작업 동시 수", desc="사람 없이 이어지는 자동 작업(Cycle)을 동시에 몇 개까지 돌릴지다.", kind="int", default="6", unit="개", min=1, max=20),
    I(key="JIPSA_OLLAMA_URL", group="config", name="Ollama 주소", desc="로드한 모델을 묻고 내리는 Ollama 서버 주소다.", kind="url", default="http://127.0.0.1:11434"),
    I(key="JIPSA_SEARCH_SOURCES", group="config", name="로컬 자료 폴더", desc="서칭 단계가 웹보다 먼저 뒤지는 폴더다. 이름=경로;이름=경로 꼴이고 비우면 웹만 본다.", kind="str", default=""),
    I(key="JIPSA_SLACK_WEBHOOK", group="slack", name="Slack 연결 주소", desc="Slack 연결 주소(Webhook URL)다. Slack으로 보고를 보내는 주소다. 비밀값이라 쓰기만 되고 값은 보이지 않으며 상태 폴더의 비밀값 파일에 저장한다. .env에 있으면 그 값이 앞선다.", kind="secret", default=""),
    I(key="slack.enabled", group="slack", name="알림 켜짐", desc="Slack 보고를 보낼지다. 상태 폴더의 알림 설정 파일에 저장하고 위쪽 메뉴의 스위치와 같은 값이다.", kind="bool", default="1"),
    I(key="JIPSA_MORNING_AT", group="slack", name="아침 요약 알림 시각", desc="밤 사이 끝난 자동 작업을 모아 Slack 글 하나로 보내는 시각이다.", kind="hhmm", default="07:30"),
    I(key="JIPSA_MODEL_WORKER", group="model", name="작업자 모델", desc="Claude 작업자가 쓰는 모델이고 첫 실행 때 정해야 돈다.", kind="str", default="opus", options=["opus", "sonnet", "haiku"]),
    I(key="JIPSA_MODEL_FAST", group="model", name="가벼운 호출 모델", desc="판정, 요약 같은 짧은 호출에 쓰는 모델이다.", kind="str", default="claude-haiku-5-5"),
    I(key="JIPSA_CODEX_MODEL", group="model", name="분석자 모델(Codex)", desc="결과 분석과 마감 전 반대 검토에 쓰는 Codex 모델이다.", kind="str", default="gpt-6.1-sol"),
    I(key="JIPSA_ATTACK_PROVIDER", group="model", name="마감 전 공격 공급자", desc="마감 전 반대 검토를 어디에 맡길지다. codex는 Codex가 하고 실행 파일이 없으면 공격 없이 돈다(Claude가 대신 공격하지 않는다). claude는 같은 계열 모델이 새 호출 한 번으로 하고 결과지에 같은 공급자 공격이라고 적는다. none은 부르지 않는다. 기본 codex를 바꾸지 않으면 Codex가 없어도 Claude가 대신 공격하지 않는다.", kind="str", default="codex", options=["codex", "claude", "none"]),
    I(key="JIPSA_CODEX_WORKER_MODEL", group="model", name="Codex 작업자 모델", desc="등록이 Codex 작업자를 고른 프로젝트에 쓰는 모델이고 비우면 분석자 모델과 같다.", kind="str", default="", note="비움(분석자 모델과 같음)"),
    I(key="JIPSA_RETAIN_RUN_DAYS", group="cleanup", name="실행 기록 보관 기한", desc="실행 기록을 월별 보관함으로 옮기기까지 두는 일수다.", kind="int", default="30", unit="일"),
    I(key="JIPSA_RETAIN_OTHER_DAYS", group="cleanup", name="세션 기록 보관 기한", desc="세션 기록과 일회성 폴더를 월별 보관함으로 옮기기까지 두는 일수다.", kind="int", default="14", unit="일"),
    I(key="JIPSA_RETAIN_ARCHIVE_DAYS", group="cleanup", name="월별 보관함 보관 기한", desc="월별 보관함을 지우기까지 두는 일수다.", kind="int", default="180", unit="일"),
    I(key="JIPSA_RUNS_CLEAN_ON", group="cleanup", name="중간 산출물 정리", desc="끝난 작업의 브라우저 프로필, 임시 DB 사본 같은 중간 파일을 스케줄러가 하루 한 번 휴지통 폴더로 옮길지다.", kind="bool", default="0"),
    I(key="JIPSA_RUNS_CLEAN_DAYS", group="cleanup", name="정리까지 기다리는 일수", desc="작업의 마지막 활동에서 이 일수가 지나야 중간 산출물을 옮긴다.", kind="int", default="3", unit="일"),
    I(key="JIPSA_RUNS_CLEAN_TRASH", group="cleanup", name="정리 휴지통 폴더", desc="중간 산출물을 옮겨 두는 폴더이고 {date}는 옮긴 날짜로 바뀐다.", kind="path", default=(Path.home() / "jipsa-trash" / "runs-{date}").as_posix()),
]

_BY_KEY = {it["key"]: it for it in ITEMS}
_HHMM = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")
_WEBHOOK = re.compile(r"^https://hooks\.slack\.com/\S{10,}$")
_TRUE, _FALSE = ("1", "true", "on", "켜짐", "예", "yes", "y"), ("0", "false", "off", "꺼짐", "아니오", "no", "n")


def _env_file_keys() -> set[str]:
    """.env에 적힌 키 이름. 값은 쓰지 않는다."""
    try:
        return set(dotenv_values(ROOT / ".env").keys())
    except OSError:
        return set()


def _display(it: dict, raw: str) -> str:
    """사람에게 보이는 값 글자."""
    kind = it["kind"]
    if kind == "bool":
        return "켜짐" if raw not in ("", "0", "off", "false") else "꺼짐"
    if kind == "ratio":
        try:
            return f"{round(float(raw) * 100)}%"
        except ValueError:
            return raw
    if raw == "" and it.get("note"):
        return it["note"]
    return raw + (it.get("unit") or "") if kind == "int" and raw else raw


def _path_note(it: dict, raw: str) -> str:
    """폴더 칸의 존재 여부. 휴지통 폴더는 날짜 자리가 있어 드라이브만 본다."""
    if it["kind"] != "path" or not raw:
        return ""
    if "{date}" in raw:
        return "드라이브 있음" if Path(Path(raw).anchor or ".").exists() else "드라이브 없음"
    return "폴더 있음" if Path(raw).exists() else "폴더 없음"


def _item_view(it: dict, file_vals: dict[str, str], env_keys: set[str]) -> dict:
    key, kind = it["key"], it["kind"]
    raw, source, locked = it["default"], "기본값", False
    if kind == "secret":  # 값은 절대 내보내지 않는다. 설정됨 여부와 출처만이다
        env_has = bool(os.environ.get(key, "").strip())
        has = env_has or bool(secret(key))
        raw = "설정됨" if has else "없음"
        source = ((".env" if key in env_keys else "환경 변수") if env_has else "비밀값 파일") if has else "기본값"
        locked = env_has
    elif key == "slack.enabled":
        from notify import slack

        raw, source = ("1" if slack.is_enabled() else "0"), "알림 설정 파일"
    else:
        env = os.environ.get(key, "").strip()
        if env:
            raw, source, locked = env, (".env" if key in env_keys else "환경 변수"), True
        elif file_vals.get(key, "").strip():
            raw, source = file_vals[key].strip(), "설정 파일"
    return {"key": key, "skill": it["group"], "name": it["name"], "desc": it["desc"], "kind": kind, "text": _display(it, raw) if kind != "secret" else raw,
            "source": source, "locked": locked, "note": _path_note(it, raw), "options": it.get("options") or []}


def view(skill: str = "") -> dict:
    """칸마다 값, 출처, 잠김. 비밀값은 설정됨 여부만이다. skill을 주면 그 스킬의 칸만이다."""
    file_vals, env_keys = file_values(), _env_file_keys()
    return {"file": str(CONFIG_FILE), "has_prev": CONFIG_PREV_FILE.exists(), "scheduler": _scheduler_brief(),
            "items": [_item_view(it, file_vals, env_keys) for it in ITEMS if not skill or it["group"] == skill]}


def normalize(key: str, value) -> tuple[str, str]:
    """명령에서 받은 값 하나를 설정 파일에 쓸 글자로 맞춘다. (값, 오류)다. 값이 빈 글자면 키를 지운다."""
    it = _BY_KEY.get(key)
    if it is None:
        return "", f"스킬로 고치는 설정이 아니다: {key}"
    if it["kind"] == "secret":  # 값은 오류 글에도 넣지 않는다
        text = str(value if value is not None else "").strip()
        if os.environ.get(key, "").strip():
            return "", f"{it['name']}은(는) 환경 변수(.env)가 덮고 있어 비밀값 파일 값을 쓰지 않는다"
        if text and not _WEBHOOK.match(text):
            return "", f"{it['name']}은(는) Slack 연결 주소(Incoming Webhook)여야 한다"
        return text, ""
    if os.environ.get(key, "").strip():
        return "", f"{it['name']}은(는) 환경 변수가 덮고 있어 설정 파일 값을 쓰지 않는다"
    text = str(value if value is not None else "").strip()
    kind = it["kind"]
    if text == "":
        return "", ""
    if kind == "bool":
        if text.lower() not in _TRUE + _FALSE:
            return "", f"{it['name']}은(는) 예 또는 아니오여야 한다: {text}"
        return ("1" if text.lower() in _TRUE else "0"), ""
    if kind == "int":
        try:
            num = int(text)
        except ValueError:
            return "", f"{it['name']}은(는) 숫자여야 한다: {text}"
        if it.get("min") is not None and num < it["min"]:
            return "", f"{it['name']}은(는) {it['min']} 이상이어야 한다"
        if it.get("max") is not None and num > it["max"]:
            return "", f"{it['name']}은(는) {it['max']} 이하여야 한다"
        return str(num), ""
    if kind == "ratio":
        try:
            num = float(text.rstrip("%"))
        except ValueError:
            return "", f"{it['name']}은(는) 백분율 숫자여야 한다: {text}"
        if num > 1:
            num = num / 100
        if not 0 < num <= 1:
            return "", f"{it['name']}은(는) 1~100% 사이여야 한다"
        return f"{num:g}", ""
    if kind == "hhmm":
        if not _HHMM.match(text):
            return "", f"{it['name']}은(는) HH:MM 꼴이어야 한다: {text}"
        h, m = text.split(":")
        return f"{int(h):02d}:{m}", ""
    if kind == "url" and not re.match(r"^https?://", text):
        return "", f"{it['name']}은(는) http:// 또는 https://로 시작해야 한다"
    if kind == "str" and it.get("options") and text not in it["options"]:
        return "", f"{it['name']}은(는) {', '.join(it['options'])} 가운데 하나여야 한다"
    return text, ""


def check(values: dict) -> dict:
    """쓰지 않고 값을 검사한다. 칸마다 지금 값과 새 값 글자, 오류를 돌려준다. 비밀값 글자는 설정됨, 없음으로만 보인다."""
    errors, merged, rows = [], dict(file_values()), []
    current = {x["key"]: x for x in view()["items"]}
    for key, value in (values or {}).items():
        key = str(key)
        if key == "slack.enabled":
            if str(value).strip().lower() not in _TRUE + _FALSE:
                errors.append(f"알림 켜짐은 예 또는 아니오여야 한다: {value}")
                continue
            new = "켜짐" if str(value).strip().lower() in _TRUE else "꺼짐"
        else:
            text, err = normalize(key, value)
            if err:
                errors.append(err)
                continue
            it = _BY_KEY[key]
            if it["kind"] == "secret":
                new = "설정됨" if text else "없음"
            elif text == "":
                merged.pop(key, None)
                new = _display(it, it["default"])
            else:
                merged[key] = text
                new = _display(it, text)
        rows.append({"key": key, "name": current[key]["name"], "before": current[key]["text"], "after": new})
    return {"ok": not errors, "why": " / ".join(errors), "errors": errors, "rows": rows, "merged": merged}


def save(values: dict) -> dict:
    """값을 검사해 쓴다. 전역 값은 설정 파일에, 비밀값은 비밀값 파일에, 알림 켜짐은 알림 설정 파일에 간다. 설정 파일을 바꿀 때만 직전 판을 남긴다."""
    checked = check(values)
    if not checked["ok"]:
        return {"ok": False, "why": checked["why"], "errors": checked["errors"]}
    secrets = {str(k): str(v or "").strip() for k, v in (values or {}).items() if _BY_KEY.get(str(k), {}).get("kind") == "secret"}
    slack_keys = [k for k in (values or {}) if str(k) == "slack.enabled"]
    plain = [str(k) for k in (values or {}) if str(k) not in secrets and str(k) != "slack.enabled"]
    STATE.mkdir(parents=True, exist_ok=True)
    if secrets:
        _write_secrets(secrets)
    if slack_keys:
        from notify import slack
        from scheduler import events

        slack.set_enabled(str(values[slack_keys[0]]).strip().lower() in _TRUE)
        events.emit("slack_switch", enabled=slack.is_enabled())
    if plain:
        if CONFIG_FILE.exists():
            shutil.copyfile(CONFIG_FILE, CONFIG_PREV_FILE)
        else:
            CONFIG_PREV_FILE.write_text("{}", encoding="utf-8")  # 파일이 없던 판. 되돌리면 빈 설정이 된다
        body = {"_saved": now_iso(), "_note": "jipsa 설정 파일. 키는 환경 변수 이름이고 환경 변수가 있으면 그 값이 앞선다. 저장한 값은 스케줄러와 대시보드를 다시 띄워야 반영된다"}
        body.update({k: v for k, v in sorted(checked["merged"].items()) if not k.startswith("_")})
        tmp = CONFIG_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, CONFIG_FILE)
    return {"ok": True, "rows": checked["rows"], "restart": bool(plain)}


def _write_secrets(values: dict[str, str]) -> None:
    """비밀값 파일에 쓴다. 빈 글자는 그 키를 지운다. 값은 로그와 이벤트에 남기지 않는다."""
    try:
        cur = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
        cur = cur if isinstance(cur, dict) else {}
    except (OSError, ValueError):
        cur = {}
    for k, v in values.items():
        if v:
            cur[k] = v
        else:
            cur.pop(k, None)
    cur["_note"] = "jipsa 비밀값 파일. 환경 변수(.env)가 있으면 그 값이 앞선다. 이 파일은 출력하지 않고 커밋하지 않는다"
    tmp = SECRETS_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, SECRETS_FILE)


def slack_test() -> dict:
    """Slack 보내기 경로로 시험 글 한 줄을 보낸다. 꺼져 있어도 사람이 고른 것이므로 보낸다(force). 200이 아니면 예외가 온다. 결과 글은 마스킹을 거친다."""
    from notify import slack

    if not slack.is_available():
        return {"ok": False, "why": "Slack 연결 주소가 없다. 먼저 저장한다"}
    try:
        slack.send_message(f"[jipsa] 시험 글 {now_iso()[11:16]}. 이 줄이 보이면 Slack 연결이 맞다", force=True)
    except Exception as e:  # noqa: BLE001 - 실패 사유를 보인다
        return {"ok": False, "why": redact(str(e))[:200]}
    return {"ok": True, "text": "시험 글 한 줄을 보냈다. 응답 코드 200이다"}


def _scheduler_brief() -> dict:
    """다시 시작 단추가 보는 스케줄러 상태. 살아 있는지와 실행 중 작업 수다."""
    try:
        from scheduler import supervise

        st = supervise.status()
        hb = supervise._read(supervise.HEARTBEAT)
        return {"alive": st["alive"], "pid": st["pid"], "running": int(hb.get("running") or 0)}
    except Exception:  # noqa: BLE001
        return {"alive": False, "pid": None, "running": 0}


def restart(force: bool = False, port: int = 0) -> dict:
    """스케줄러와 대시보드를 창 없이 다시 띄운다. 분리된 도우미 프로세스가 둘을 끄고 같은 포트로 대시보드를 다시 띄우며,
    새 대시보드의 감시가 스케줄러를 띄운다. 실행 중 작업이 있으면 force 없이는 거절한다. 다시 뜰 때까지 기다린다."""
    import subprocess
    import sys
    import time

    from scheduler import monitor, supervise
    from scheduler.nowindow import BACKGROUND, BREAKAWAY, hidden

    brief = _scheduler_brief()
    if brief["running"] and not force:
        return {"ok": False, "why": f"실행 중 작업이 {brief['running']}개 있다. 끝나기를 기다리거나 --force를 준다. --force는 그 작업을 끊는다", "running": brief["running"]}
    port = port or WEB_PORT
    listener = monitor._listener(port)
    if listener and not monitor._is_dashboard(listener):
        return {"ok": False, "why": f"{port} 포트를 다른 프로그램이 쓴다. 다시 띄우지 않았다"}
    if listener:
        why = monitor.foreign_reason(listener)
        if why:
            return {"ok": False, "why": f"{port} 포트 대시보드(pid {listener.pid})를 끄지 않았다. {why}. 이 저장소의 대시보드를 따로 띄우려면 JIPSA_WEB_PORT를 다른 값으로 준다"}
    dash_pid = listener.pid if listener else 0
    supervise.unhold()
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "JIPSA_LIVE": "1"}
    cmd = [sys.executable, "-m", "scheduler.settings", "restart", "--port", str(port), "--dash-pid", str(dash_pid), "--sched-pid", str(brief["pid"] or 0)]
    kw = dict(cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env, close_fds=True)
    started = time.monotonic()
    try:
        if os.name == "nt":
            try:
                subprocess.Popen(cmd, **hidden(BACKGROUND | BREAKAWAY), **kw)
            except OSError:
                subprocess.Popen(cmd, **hidden(BACKGROUND), **kw)
        else:
            subprocess.Popen(cmd, start_new_session=True, **kw)
    except OSError as e:
        return {"ok": False, "why": f"다시 시작 도우미를 띄우지 못했다: {e}"}
    while time.monotonic() - started < 45:  # 옛 대시보드가 내려가고 새 대시보드가 응답할 때까지 본다
        time.sleep(1)
        now_listener = monitor._listener(port)
        if now_listener and now_listener.pid != dash_pid and monitor._responds(port):
            return {"ok": True, "text": f"스케줄러와 대시보드를 창 없이 다시 띄웠다({round(time.monotonic() - started)}초). 포트 {port}이고 스케줄러는 대시보드 감시가 띄운다", "port": port}
    return {"ok": False, "why": f"45초 안에 {port} 포트 대시보드가 응답하지 않았다. 상태 폴더 restart.log를 본다"}


def _restart_main(argv: list[str]) -> int:
    """도우미 프로세스. 대시보드와 스케줄러를 끄고 같은 포트로 대시보드를 다시 띄운다. 로그는 상태 폴더 restart.log다."""
    import argparse
    import subprocess
    import sys
    import time

    from scheduler import monitor

    ap = argparse.ArgumentParser()
    ap.add_argument("action")
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--dash-pid", type=int, default=0)
    ap.add_argument("--sched-pid", type=int, default=0)
    a = ap.parse_args(argv)
    log = STATE / "restart.log"
    STATE.mkdir(parents=True, exist_ok=True)

    def say(t: str) -> None:
        with log.open("a", encoding="utf-8") as f:
            f.write(f"{now_iso()} {t}\n")

    say(f"다시 시작 요청. 포트 {a.port}, 대시보드 pid {a.dash_pid}, 스케줄러 pid {a.sched_pid}")
    time.sleep(1.0)  # 대시보드가 응답을 다 보내게 둔다
    # 이 도우미는 대시보드의 자식이므로 monitor._kill(자식까지 끈다)을 그대로 쓰면 자기도 죽는다. 가상환경의 python.exe는 실제 python을
    # 자식으로 띄우는 실행기라 그 실행기(내 부모)를 끄면 나도 죽으므로, 나와 내 조상은 모두 뺀다
    import psutil

    me = os.getpid()
    mine = {me}
    for q in psutil.Process(me).parents():  # 대시보드까지 올라가며 그 사이의 실행기만 뺀다. 대시보드 자신은 끈다
        if q.pid == a.dash_pid:
            break
        mine.add(q.pid)
    procs = []
    for pid in (a.sched_pid, a.dash_pid):
        p = monitor._proc(pid) if pid else None
        if p:
            try:
                procs += [p, *p.children(recursive=True)]
            except psutil.Error:
                procs.append(p)
    procs = [p for p in {p.pid: p for p in procs}.values() if p.pid not in mine]
    for p in procs:
        try:
            p.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(procs, timeout=5)
    for p in alive:
        try:
            p.kill()
        except psutil.Error:
            pass
    say(f"껐다. pid {[p.pid for p in procs]}")
    for _ in range(30):
        if monitor._listener(a.port) is None:
            break
        time.sleep(0.5)
    proc = monitor._popen([sys.executable, "-m", "scheduler.cli", "web", "--no-open", "--port", str(a.port)], monitor.DASH_LOG, ROOT)
    ok = monitor._wait_until(lambda: monitor._responds(a.port) or proc.poll() is not None, 30) and monitor._responds(a.port)
    say(f"대시보드 다시 띄움 pid {proc.pid}, 응답 {'있음' if ok else '없음'}. 스케줄러는 대시보드 감시가 띄운다")
    return 0 if ok else 1


def restore() -> dict:
    """저장 직전 판으로 되돌린다. 지금 판과 직전 판을 맞바꾸므로 한 번 더 누르면 돌아온다."""
    if not CONFIG_PREV_FILE.exists():
        return {"ok": False, "why": "되돌릴 직전 판이 없다"}
    cur = CONFIG_FILE.read_text(encoding="utf-8") if CONFIG_FILE.exists() else ""
    prev = CONFIG_PREV_FILE.read_text(encoding="utf-8")
    if prev.strip() in ("", "{}"):
        if CONFIG_FILE.exists():
            CONFIG_FILE.unlink()
    else:
        CONFIG_FILE.write_text(prev, encoding="utf-8")
    CONFIG_PREV_FILE.write_text(cur or "{}", encoding="utf-8")
    return {"ok": True, "restart": True}


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "restart":
        try:
            raise SystemExit(_restart_main(sys.argv[1:]))
        except SystemExit:
            raise
        except Exception:  # noqa: BLE001 - 도우미는 출력이 없으므로 로그에 남긴다
            import traceback

            with (STATE / "restart.log").open("a", encoding="utf-8") as f:
                f.write(traceback.format_exc())
            raise
    raise SystemExit("사용: python -m scheduler.settings restart --port N --dash-pid N --sched-pid N")
