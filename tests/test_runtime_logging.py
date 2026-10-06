from __future__ import annotations

import logging
from pathlib import Path

import klipperai_agent.runtime.logging as runtime_logging
from klipperai_agent.runtime.settings import Settings


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        printer_data_root=tmp_path / "printer_data",
        data_dir=tmp_path / "data",
        checkpoint_db=tmp_path / "data" / "db.sqlite",
        agent_log_level="debug",
        agent_log_max_bytes=1000,
        agent_log_backup_count=2,
    )


def test_configure_runtime_logging_with_file_sink(tmp_path) -> None:
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    try:
        log_path = runtime_logging.configure_runtime_logging(_settings(tmp_path))
        assert (
            log_path.resolve() == (tmp_path / "printer_data" / "logs" / "klipperai.log").resolve()
        )
        assert root.level == logging.DEBUG
        assert len(root.handlers) == 2
        logging.getLogger("klipperai_agent.test").info("hello")
        for handler in root.handlers:
            handler.flush()
        assert "hello" in log_path.read_text(encoding="utf-8")
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("uvicorn.access").level == logging.INFO
    finally:
        for handler in list(root.handlers):
            handler.close()
        root.handlers[:] = original_handlers


def test_configure_runtime_logging_falls_back_to_console(monkeypatch, tmp_path) -> None:
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    monkeypatch.setattr(
        runtime_logging,
        "RotatingFileHandler",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("read only")),
    )
    try:
        assert runtime_logging.configure_runtime_logging(_settings(tmp_path)) is None
        assert len(root.handlers) == 1
    finally:
        for handler in list(root.handlers):
            handler.close()
        root.handlers[:] = original_handlers
