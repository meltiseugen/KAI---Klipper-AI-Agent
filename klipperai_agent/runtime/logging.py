from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from klipperai_agent.domain.redaction import redact_text
from klipperai_agent.infrastructure.private_files import open_private_file
from klipperai_agent.runtime.settings import Settings

_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


class RedactingFormatter(logging.Formatter):
    def __init__(self, secret: str = ""):
        super().__init__(_FORMAT)
        self.secrets: tuple[str, ...] = (secret,)

    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record), self.secrets)


class PrivateRotatingFileHandler(RotatingFileHandler):
    def _open(self):
        return open_private_file(Path(self.baseFilename))


def register_provider_secret(secret: str | None) -> None:
    """Include the active private-store credential in existing log redaction."""
    if secret:
        for handler in logging.getLogger().handlers:
            formatter = handler.formatter
            if isinstance(formatter, RedactingFormatter) and secret not in formatter.secrets:
                formatter.secrets += (secret,)


def configure_runtime_logging(settings: Settings) -> Path | None:
    level_name = settings.agent_log_level.upper()
    level = getattr(logging, level_name, logging.INFO)
    formatter = RedactingFormatter(
        settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
    )

    handlers: list[logging.Handler] = []

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    handlers.append(console_handler)

    file_path: Path | None = None
    try:
        candidate = settings.agent_log_path()
        candidate.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        file_handler = PrivateRotatingFileHandler(
            candidate,
            maxBytes=settings.agent_log_max_bytes,
            backupCount=settings.agent_log_backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
        file_path = candidate
    except OSError:
        console_handler.handle(
            logging.LogRecord(
                "klipperai_agent.logging",
                logging.WARNING,
                "",
                0,
                "Could not open KlipperAI log file. Falling back to stderr/journal only.",
                (),
                None,
            )
        )

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)
    for handler in handlers:
        root_logger.addHandler(handler)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "klipperai_agent"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)

    logger = logging.getLogger("klipperai_agent.logging")
    if file_path is not None:
        logger.info("Runtime logging configured at %s", file_path)
    else:
        logger.warning("Runtime logging configured without a file sink.")
    return file_path
