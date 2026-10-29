"""Request-scoped public usage, recorded at the HTTP boundary, never inferred."""

from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import AsyncIterator, Awaitable, Callable, Iterator

from klipperai_agent.domain.evidence import AgentEvent
from klipperai_agent.domain.model_usage import ModelUsage


@dataclass
class UsageScope:
    receipt: ModelUsage
    on_event: Callable[[AgentEvent], Awaitable[None]] | None


_scope: ContextVar[UsageScope | None] = ContextVar("model_usage", default=None)


@contextmanager
def track_model_usage(
    on_event: Callable[[AgentEvent], Awaitable[None]] | None = None,
) -> Iterator[ModelUsage]:
    receipt = ModelUsage(status="not_used")
    token = _scope.set(UsageScope(receipt, on_event))
    try:
        yield receipt
    finally:
        _scope.reset(token)


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
