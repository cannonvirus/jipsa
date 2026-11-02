"""Slack Incoming Webhook. 송신 전용.

Webhook URL 하나에 {"text": ...}를 POST한다. 받는 기능은 없다. 원격 명령은 Claude Code Remote Control로 받는다.
전송 여부는 runtime/state/slack_config.json의 {"enabled": bool}로 끈다. 파일이 없으면 켠 것으로 본다.
Webhook 주소는 환경 변수(.env) 다음에 상태 폴더 secrets.json에서 읽는다(261102-jipsa-28).
"""

from __future__ import annotations

import json

import requests

from scheduler.config import STATE, redact, secret

_TIMEOUT = 10
_MAX_MESSAGE = 4000
_CONFIG_FILE = STATE / "slack_config.json"


class SlackError(RuntimeError):
    pass


def _webhook() -> str:
    """Webhook 주소. 환경 변수 다음에 상태 폴더 비밀값 파일이다(261102-jipsa-28). 부를 때마다 읽어 스킬에서 저장한 직후에도 쓴다."""
    return secret("JIPSA_SLACK_WEBHOOK")


def is_available() -> bool:
    return bool(_webhook())


def is_enabled() -> bool:
    try:
        return bool(json.loads(_CONFIG_FILE.read_text(encoding="utf-8")).get("enabled", True))
    except (OSError, ValueError, AttributeError):
        return True


def set_enabled(value: bool) -> None:
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps({"enabled": bool(value)}), encoding="utf-8")


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _split(text: str) -> list[str]:
    """빈 줄로 나뉜 작업 묶음 경계에서 자른다. 묶음 하나가 상한을 넘을 때만 줄 단위로 자른다."""
    if len(text) <= _MAX_MESSAGE:
        return [text]
    parts, buf = [], ""
    for block in text.split("\n\n"):
        if len(buf) + len(block) + 2 > _MAX_MESSAGE and buf:
            parts.append(buf)
            buf = ""
        if len(block) > _MAX_MESSAGE:
            for line in block.split("\n"):
                if len(buf) + len(line) + 1 > _MAX_MESSAGE and buf:
                    parts.append(buf)
                    buf = ""
                while len(line) > _MAX_MESSAGE:
                    parts.append(line[:_MAX_MESSAGE])
                    line = line[_MAX_MESSAGE:]
                buf = f"{buf}\n{line}" if buf else line
            continue
        buf = f"{buf}\n\n{block}" if buf else block
    if buf:
        parts.append(buf)
    return parts


def _post(text: str) -> None:
    try:
        resp = requests.post(_webhook(), json={"text": text}, timeout=_TIMEOUT)
    except requests.RequestException as e:
        raise SlackError(f"슬랙 요청 실패: {redact(str(e))}") from e
    if resp.status_code != 200:
        raise SlackError(f"슬랙 HTTP {resp.status_code}: {redact(resp.text[:300])}")


SKIPPED = "Slack 꺼짐으로 건너뜀"


def send_message(text: str, *, force: bool = False) -> bool:
    """평문으로 보낸다. URL이 없으면 오류이고, 꺼져 있으면 보내지 않고 False를 돌려준다. force는 사람이 직접 보낸 요청이다."""
    if not is_available():
        raise SlackError("JIPSA_SLACK_WEBHOOK이 없다")
    if not force and not is_enabled():
        return False
    for part in _split(_escape(redact(text))):
        _post(part)
    return True


def notify(text: str, *, force: bool = False) -> str:
    """보내되 실패해도 부르는 쪽을 죽이지 않는다. 결과를 한 줄로 돌려준다. 꺼져 있으면 건너뛴다(force는 사람이 직접 보낸 요청)."""
    if not is_available():
        return "알림 생략: JIPSA_SLACK_WEBHOOK 없음"
    try:
        return "전송" if send_message(text, force=force) else SKIPPED
    except Exception as e:  # noqa: BLE001
        return f"알림 실패: {redact(str(e))}"
