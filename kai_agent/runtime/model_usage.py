"""Request-scoped public usage, recorded at the HTTP boundary, never inferred."""

from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Iterator

from kai_agent.domain.evidence import AgentEvent
from kai_agent.domain.model_usage import ModelUsage


@dataclass
class UsageScope:
    receipt: ModelUsage
    on_event: Callable[[AgentEvent], Awaitable[None]] | None
    chat_model: str | None
    reasoning_effort: str | None


_scope: ContextVar[UsageScope | None] = ContextVar("model_usage", default=None)


@contextmanager
def track_model_usage(
    on_event: Callable[[AgentEvent], Awaitable[None]] | None = None,
    *,
    chat_model: str | None = None,
    reasoning_effort: str | None = None,
) -> Iterator[ModelUsage]:
    receipt = ModelUsage(status="not_used")
    token = _scope.set(UsageScope(receipt, on_event, chat_model, reasoning_effort))
    try:
        yield receipt
    finally:
        _scope.reset(token)


def selected_chat_model(default: str) -> str:
    """Resolve this request's override without changing shared provider policy."""
    scope = _scope.get()
    return scope.chat_model if scope and scope.chat_model else default


def selected_reasoning_effort(default: str) -> str:
    """Resolve this chat's thinking level without mutating shared profiles."""
    scope = _scope.get()
    return scope.reasoning_effort if scope and scope.reasoning_effort else default


@asynccontextmanager
async def model_request(model: str) -> AsyncIterator[None]:
    scope = _scope.get()
    if scope:
        if scope.on_event:
            await scope.on_event(
                AgentEvent(kind="model_started", message=f"Calling OpenAI · {model}")
            )
        scope.receipt.status = "attempted"
        scope.receipt.requests_started += 1
        label = f"OpenAI / {model}"
        if label not in scope.receipt.models:
            scope.receipt.models.append(label)
    yield
    if scope:
        scope.receipt.requests_completed += 1
        scope.receipt.status = "completed"
        if scope.on_event:
            await scope.on_event(
                AgentEvent(kind="model_completed", message=f"LLM response received · {model}")
            )
