from __future__ import annotations

import logging
import os

import uvicorn

from klipperai_agent.runtime.logging import configure_runtime_logging
from klipperai_agent.runtime.settings import get_settings

logger = logging.getLogger("klipperai_agent.bootstrap")


def main() -> None:
    os.umask(0o077)
    settings = get_settings()
    settings.ensure_directories()
    log_path = configure_runtime_logging(settings)
    logger.info(
        "Starting KlipperAI host=%s port=%s root_path=%s moonraker_url=%s read_only=%s log_path=%s",
        settings.host,
        settings.port,
        settings.root_path or "/",
        settings.moonraker_url,
        not settings.enable_write_actions,
        log_path or "stderr-only",
    )
    uvicorn.run(
        "klipperai_agent.web.app:create_app",
        host=settings.host,
        port=settings.port,
        root_path=settings.root_path.rstrip("/"),
        factory=True,
        log_config=None,
        access_log=False,
        server_header=False,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1,::1",
    )


if __name__ == "__main__":
    main()
