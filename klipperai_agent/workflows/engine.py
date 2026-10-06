from __future__ import annotations

import inspect
from typing import Any

from klipperai_agent.workflows.configuration import (
    call_config_llm,
    collect_config_context,
    compose_config_response,
    detect_config_target,
)
from klipperai_agent.workflows.context import WorkflowContext, WorkflowRuntime
from klipperai_agent.workflows.diagnosis import (
    call_llm,
    collect_context,
    compose_response,
    run_rules,
)


class SimpleWorkflow:
    def __init__(self, nodes: list[Any]) -> None:
        self._nodes = nodes

    async def ainvoke(
        self,
        state: dict[str, Any],
        *,
        config: dict[str, Any] | None = None,
        context: WorkflowContext,
    ) -> dict[str, Any]:
        del config
        current = dict(state)
        runtime = WorkflowRuntime(context=context)
        for node in self._nodes:
            update = node(current, runtime) if _accepts_runtime(node) else node(current)
            if inspect.isawaitable(update):
                update = await update
            if update:
                current.update(update)
        return current


class ConfigWorkflow(SimpleWorkflow):
    def __init__(self) -> None:
        super().__init__(
            [
                detect_config_target,
                collect_config_context,
                call_config_llm,
                compose_config_response,
            ]
        )


def _accepts_runtime(node: Any) -> bool:
    return len(inspect.signature(node).parameters) >= 2


def build_diagnosis_graph() -> SimpleWorkflow:
    return SimpleWorkflow([collect_context, run_rules, call_llm, compose_response])


def build_config_graph() -> ConfigWorkflow:
    return ConfigWorkflow()
