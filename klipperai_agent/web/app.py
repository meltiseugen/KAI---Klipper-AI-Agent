from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from klipperai_agent.application.recovery import InvestigationRecovery
from klipperai_agent.bootstrap.container import AppContainer, build_container
from klipperai_agent.contracts.api import (
    BootstrapResponse,
    ChatRequest,
    ChatResponse,
    UiSessionResponse,
)
from klipperai_agent.domain.context import ModeUnavailableError
from klipperai_agent.domain.provider_settings import ProviderLimitError
from klipperai_agent.domain.repositories import InvestigationConflict
from klipperai_agent.domain.version import __version__
from klipperai_agent.runtime.release import release_info
from klipperai_agent.runtime.settings import get_settings
from klipperai_agent.web.chat_readiness import provider_configured, require_provider
from klipperai_agent.web.investigations import investigation_routes
from klipperai_agent.web.knowledge import knowledge_routes
from klipperai_agent.web.memory import memory_routes
from klipperai_agent.web.moonraker import moonraker_routes
from klipperai_agent.web.providers import provider_routes
from klipperai_agent.web.security import RequestSecurity
from klipperai_agent.web.streaming import ChatEventStream

logger = logging.getLogger("klipperai_agent.app")


def create_app() -> FastAPI:
    settings = get_settings()
    settings.ensure_directories()

    package_dir = Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=str(package_dir / "templates"))
    static_dir = package_dir / "static"
    embed_css = (static_dir / "embed.css").read_text(encoding="utf-8")
    embed_js = "\n".join(
        (static_dir / name).read_text(encoding="utf-8")
        for name in json.loads((static_dir / "scripts.json").read_text(encoding="utf-8"))
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(
            "Application startup printer_data_root=%s host_logs_dir=%s",
            settings.printer_data_root,
            settings.host_logs_dir(),
        )
        container = build_container(settings)
        app.state.container = container
        memory = getattr(container.chat_service, "investigations", None)
        recovery = InvestigationRecovery(memory, container.chat_service.resume) if memory else None
        if recovery:
            recovery.start()
        integration = getattr(container, "moonraker_agent", None)
        if integration is not None:
            integration.start()
        recorder = getattr(container, "host_flight_recorder", None)
        if recorder is not None:
            recorder.start()
        logger.info("Application startup complete.")
        try:
            yield
        finally:
            logger.info("Application shutdown started.")
            if recovery:
                await recovery.aclose()
            await container.aclose()
            logger.info("Application shutdown complete.")

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        root_path=settings.root_path.rstrip("/"),
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[
            host.strip() for host in settings.security_allowed_hosts.split(",") if host.strip()
        ],
        www_redirect=False,
    )
    app.add_middleware(RequestSecurity, allowed_origins=settings.security_allowed_origins)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Validation diagnostics must not echo user content or secret values.
        return JSONResponse(
            {"detail": "Invalid request. Check the required fields and their values."},
            status_code=422,
        )

    @app.exception_handler(ProviderLimitError)
    async def provider_limited(request: Request, exc: ProviderLimitError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=429)

    app.mount("/assets", StaticFiles(directory=str(static_dir)), name="assets")
    app.include_router(investigation_routes(lambda request: _get_container(request).chat_service))
    app.include_router(memory_routes(lambda request: _get_container(request).chat_service))
    app.include_router(knowledge_routes(lambda request: _get_container(request).chat_service))
    app.include_router(provider_routes(_get_container))
    app.include_router(moonraker_routes(_get_container))

    root_base = settings.root_path.rstrip("/") if settings.root_path else ""
    api_base = f"{root_base}/api" if root_base else "/api"

    @app.get("/", response_class=HTMLResponse)
    async def standalone(request: Request) -> HTMLResponse:
        response = templates.TemplateResponse(
            request=request,
            name="embed.html",
            context={
                "session_id": "",
                "api_base": api_base,
                "embed_css": embed_css,
                "embed_js": embed_js,
            },
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/direct", response_class=HTMLResponse)
    async def direct(request: Request) -> HTMLResponse:
        response = templates.TemplateResponse(
            request=request,
            name="embed.html",
            context={
                "session_id": "",
                "api_base": api_base,
                "embed_css": embed_css,
                "embed_js": embed_js,
            },
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        # No provider/printer I/O: deployments validate the running code itself.
        return {"status": "ok", "printer_access": "read_only", **release_info()}

    @app.get("/healthz")
    async def healthz(request: Request) -> dict[str, object]:
        container = _get_container(request)
        return {
            "status": "ok",
            "moonraker_reachable": await container.moonraker.ping(),
        }

    @app.post("/api/ui-sessions", response_model=UiSessionResponse, name="create_ui_session")
    async def create_ui_session(request: Request) -> UiSessionResponse:
        container = _get_container(request)
        return await container.chat_service.create_ui_session()

    @app.get("/api/bootstrap", response_model=BootstrapResponse)
    async def bootstrap(session_id: str, request: Request) -> BootstrapResponse:
        container = _get_container(request)
        try:
            result = await container.chat_service.bootstrap(session_id)
            if getattr(container, "providers", None) is not None:
                result.features.append("provider-management")
                result.provider_configured = provider_configured(container)
            if getattr(container, "moonraker_agent", None) is not None:
                result.features.append("moonraker-events")
            return result
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
        container = _get_container(request)
        require_provider(container, payload.session_id)
        try:
            return await container.chat_service.chat(payload)
        except InvestigationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ModeUnavailableError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/api/chat/stream")
    async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
        container = _get_container(request)
        if container.sessions.get(payload.session_id) is None:
            raise HTTPException(status_code=403, detail="Invalid or expired session.")
        require_provider(container, payload.session_id)
        if payload.mode == "debug" and not container.chat_service.agent_workflow:
            raise HTTPException(status_code=400, detail="Debug mode requires the tool-using agent.")
        return StreamingResponse(
            ChatEventStream(container.chat_service).events(payload),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.get("/embed", response_class=HTMLResponse)
    async def embed(request: Request, session: str | None = None) -> HTMLResponse:
        if session:
            logger.info(
                "Serving embed UI; client will bootstrap a fresh session if needed",
            )
        response = templates.TemplateResponse(
            request=request,
            name="embed.html",
            context={
                "session_id": session or "",
                "api_base": api_base,
                "embed_css": embed_css,
                "embed_js": embed_js,
            },
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    return app


def _get_container(request: Request) -> AppContainer:
    container = getattr(request.app.state, "container", None)
    if not container:
        raise RuntimeError("Application container is not initialized.")
    return container
