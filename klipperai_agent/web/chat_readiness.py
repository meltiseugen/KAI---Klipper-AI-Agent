"""The assistant requires an active model provider; credentials stay private."""

from fastapi import HTTPException

from klipperai_agent.bootstrap.container import AppContainer


def provider_configured(container: AppContainer) -> bool:
    manager = getattr(container, "providers", None)
    return manager is None or (
        manager.active_policy.provider == "openai" and bool(manager.active_key)
    )


def require_provider(container: AppContainer, session_id: str) -> None:
    if not provider_configured(container):
        if container.sessions.get(session_id) is None:
            raise HTTPException(status_code=403, detail="Invalid or expired session.")
        raise HTTPException(
            status_code=503,
            detail={
                "code": "provider_not_configured",
                "message": "Configure an LLM provider and API key to use the agent. Open Provider settings.",
            },
        )
