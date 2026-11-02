"""어댑터 공통 자료형. 한 백엔드가 실패해도 다른 경로로 조용히 넘어가지 않는다."""

from __future__ import annotations

from dataclasses import dataclass, field


class AdapterError(RuntimeError):
    """실행, 인증, 응답 오류. 호출부가 보고 사유를 적는다."""


class LimitError(AdapterError):
    """사용 한도에 닿았다. 2.8의 한도 처리 대상이다."""


@dataclass
class ToolEvent:
    ts: str
    tool: str
    summary: str
    tool_id: str | None = None
    parent_id: str | None = None


@dataclass
class WorkerResult:
    text: str = ""
    session_id: str | None = None
    num_turns: int = 0
    usage: dict = field(default_factory=dict)
    cost_usd: float | None = None
    duration_ms: int | None = None
    is_error: bool = False
    subtype: str = ""
    killed: bool = False
    returncode: int | None = None
    tools: list[ToolEvent] = field(default_factory=list)

    @property
    def input_tokens(self) -> int:
        u = self.usage or {}
        return int(u.get("input_tokens", 0)) + int(u.get("cache_read_input_tokens", 0)) + int(
            u.get("cache_creation_input_tokens", 0)
        )

    @property
    def output_tokens(self) -> int:
        return int((self.usage or {}).get("output_tokens", 0))


_LIMIT_WORDS = ("rate limit", "rate_limit", "usage limit", "limit reached", "quota", "429", "too many requests", "out of extra usage")


def looks_like_limit(text: str) -> bool:
    low = (text or "").lower()
    return any(w in low for w in _LIMIT_WORDS)
