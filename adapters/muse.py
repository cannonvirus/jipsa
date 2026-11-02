"""Muse 어댑터 자리. 역할이 없다."""

from __future__ import annotations

from adapters.base import AdapterError


def ask(prompt: str, **_) -> str:
    raise AdapterError("Muse 어댑터는 비어 있다. 역할을 정한 뒤 채운다.")
