"""Gemini 어댑터 자리. 역할이 없다. Gemini CLI 0.32.1은 설치되어 있고 구독 상태는 미확인이다."""

from __future__ import annotations

from adapters.base import AdapterError


def ask(prompt: str, **_) -> str:
    raise AdapterError("Gemini 어댑터는 비어 있다. 역할을 정한 뒤 채운다.")
