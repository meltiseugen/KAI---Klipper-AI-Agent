import json
import logging
import os
import sqlite3
import stat
from contextlib import closing
from pathlib import Path

import pytest
from pydantic import ValidationError

from klipperai_agent.config.collector import ConfigCollector
from klipperai_agent.config.models import ConfigReadError
from klipperai_agent.domain.investigation import (
    Investigation,
    InvestigationResult,
    InvestigationTurn,
)
from klipperai_agent.domain.redaction import REDACTED, redact_data, redact_text
from klipperai_agent.infrastructure.host.logs import HostLogCollector
from klipperai_agent.infrastructure.host.system import SystemCommandRunner
from klipperai_agent.infrastructure.investigations import SqliteInvestigationRepository
from klipperai_agent.infrastructure.private_files import open_private_file
from klipperai_agent.runtime.logging import PrivateRotatingFileHandler, RedactingFormatter
from klipperai_agent.runtime.settings import Settings, _load_klipperai_cfg_values


@pytest.mark.parametrize(
    "value",
    [
        "api_key: hidden-value",
        'OPENAI_API_KEY="hidden-value"',
        "password='hidden-value'",
        "Authorization: Bearer hidden-value",
        "Cookie: x=hidden-value; y=other-value",
        "Set-Cookie: sid=hidden-value; HttpOnly",
        "Bearer hidden-value",
        "Basic hidden-value",
        "https://name:hidden-value@example.org/",
        "https://example.org/?access_token=hidden-value&x=1",
        "session_id=hidden-value",
        "wifi_psk: hidden-value",
        "-----BEGIN PRIVATE KEY-----\nhidden-value\n-----END PRIVATE KEY-----",
        "-----BEGIN RSA PRIVATE KEY-----\nhidden-value",
        "password: |\n  hidden-value\n  second-line\n",
    ],
)
def test_redaction_removes_credentials_and_preserves_lines(value):
    text = value + "\n[fan]\npin: toolhead:PA1\n"
    result = redact_text(text)
    assert "hidden-value" not in result and REDACTED in result
    assert result.count("\n") == text.count("\n")
    if "-----BEGIN RSA" not in value:  # Unterminated PEM fails closed to end of input.
        assert "[fan]\npin: toolhead:PA1" in result


def test_redaction_preserves_json_types_and_nonsecret_diagnostics():
    original = {
        "nested": [{"token": "opaque", "count": 3, "enabled": True}],
        "pin": "PA1",
        "message": "sk-proj-abcdefghijklmnopqrst and configured-provider-key",
    }
    result = redact_data(original, ("configured-provider-key", ""))
    assert result["nested"][0] == {"token": REDACTED, "count": 3, "enabled": True}
    assert result["pin"] == "PA1" and original["nested"][0]["token"] == "opaque"
    assert result["message"] == f"{REDACTED} and {REDACTED}"
    assert redact_data((None, 4)) == [None, 4]
    for text in (
        "token=x",
        "password='x'",
        "Bearer a",
        "Cookie: x",
        "https://u:p@example.org",
        "password: |\n  x\n",
        "a\nb",
    ):
        masked = redact_text(text, ("a\nb",))
        assert len(masked) <= len(text)
        assert masked.count("\n") == text.count("\n")
    assert json.loads(redact_text('{"password":"opaque","pin":"PA1"}')) == {
        "password": "******",
        "pin": "PA1",
    }
    assert redact_text("password:\n[fan]\npin: PA1") == "password:\n[fan]\npin: PA1"
    plain = "Stats 123: mcu: bytes_retransmit=12 sysload=2.1 memavail=500000\n"
    assert redact_text(plain) == plain


def test_config_redacts_before_clipping_without_changing_source_or_line_numbers(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    source = config / "printer.cfg"
    content = "\n[printer]\npassword: super-private\n[fan]\npin: PA1\n"
    source.write_text(content)
    collector = ConfigCollector(tmp_path, max_chars_per_document=50)
    snapshot = collector.collect()
    assert "super-private" not in snapshot.documents[0].content
    expanded = collector.read_collected_document(snapshot.documents[0])
    assert "[REDACTED]" in expanded.content
    assert expanded.content.splitlines()[3] == "[fan]"
    assert snapshot.section_locations[-1].line_number == 4
    assert source.read_text() == content
    source.unlink()
    with pytest.raises(ConfigReadError, match="could not be read"):
        collector.read_collected_document(snapshot.documents[0])


def test_log_collection_keeps_extra_logs_and_redacts_content(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "crowsnest.log").write_text("camera online\napi_key=hidden-value\n")
    artifacts, _ = HostLogCollector(tmp_path).collect()
    assert len(artifacts) == 1 and artifacts[0].label == "crowsnest.log"
    assert "camera online" in artifacts[0].content and "hidden-value" not in artifacts[0].content


def test_private_file_creation_rotation_and_redacted_tracebacks(tmp_path, monkeypatch):
    calls = []
    original_open = os.open

    def capture(path, flags, mode=0o777):
        calls.append(mode)
        return original_open(path, flags, mode)

    monkeypatch.setattr(os, "open", capture)
    path = tmp_path / "agent.log"
    handler = PrivateRotatingFileHandler(path, maxBytes=100, backupCount=1)
    handler.setFormatter(RedactingFormatter("configured-secret"))
    try:
        try:
            raise ValueError("configured-secret password=hidden-value")
        except ValueError:
            import sys

            record = logging.LogRecord(
                "test", logging.ERROR, "", 0, "configured-secret", (), sys.exc_info()
            )
        handler.emit(record)
        handler.doRollover()
        handler.emit(logging.LogRecord("test", logging.INFO, "", 0, "rotation", (), None))
    finally:
        handler.close()
    text = path.read_text() + path.with_suffix(".log.1").read_text()
    assert "configured-secret" not in text and "hidden-value" not in text
    assert "ValueError" in text and REDACTED in text
    assert calls and all(mode == 0o600 for mode in calls)
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_private_files_reject_redirects_and_close_failed_descriptors(tmp_path, monkeypatch):
    path = tmp_path / "private"
    path.write_text("keep")
    linked = tmp_path / "linked"
    linked.hardlink_to(path)
    with pytest.raises(OSError, match="hardlinks"):
        open_private_file(linked)
    assert path.read_text() == "keep"
    linked.unlink()
    with monkeypatch.context() as patch:
        patch.setattr(Path, "is_symlink", lambda _: True)
        with pytest.raises(OSError, match="symlink"):
            open_private_file(path)
    permissions = []
    with monkeypatch.context() as patch:
        patch.setattr(os, "fchmod", lambda fd, mode: permissions.append(mode), raising=False)
        with open_private_file(path) as handle:
            handle.write(" more")
    assert permissions == [0o600]
    with monkeypatch.context() as patch:
        patch.delattr(os, "fchmod", raising=False)
        with open_private_file(path):
            pass
    with monkeypatch.context() as patch:
        descriptors = []
        original_close = os.close
        patch.setattr(os, "close", lambda fd: (descriptors.append(fd), original_close(fd))[-1])
        patch.setattr(
            os, "fchmod", lambda *_: (_ for _ in ()).throw(OSError("chmod failed")), raising=False
        )
        with pytest.raises(OSError, match="chmod failed"):
            open_private_file(path)
        assert len(descriptors) == 1


def test_persistence_redacts_new_and_legacy_history(tmp_path):
    store = SqliteInvestigationRepository(tmp_path, protected_dirs=())
    investigation = Investigation(printer_id="p", title="password=private-title")
    turn = InvestigationTurn(
        question="token=private-question",
        result=InvestigationResult(response_text="password=private-answer"),
    )
    store.save_turn(investigation, turn)
    path = tmp_path / "investigations.sqlite3"
    with closing(sqlite3.connect(path)) as db, db:
        assert "private-" not in str(db.execute("SELECT * FROM investigations").fetchall())
        assert "private-" not in str(db.execute("SELECT * FROM turns").fetchall())
        # Simulate a database created before redaction was introduced.
        db.execute("UPDATE investigations SET title=?", ("password=legacy-secret",))
        db.execute("UPDATE turns SET content=?", (turn.json(),))
    loaded = store.get("p", investigation.id)
    assert "private-" not in loaded.json() and "legacy-secret" not in loaded.json()
    assert "[REDACTED]" in loaded.json()


def test_secret_configuration_and_private_log_path(tmp_path, monkeypatch):
    config = tmp_path / "klipperai.cfg"
    config.write_text("[klipperai]\nopenai_api_key: never-show-this\n")
    with pytest.raises(ValueError, match="protected environment") as error:
        _load_klipperai_cfg_values(config)
    assert "never-show-this" not in str(error.value)
    monkeypatch.setenv("KLIPPERAI_OPENAI_API_KEY", "environment-key")
    settings = Settings(data_dir=tmp_path / "private", printer_data_root=tmp_path / "printer")
    assert settings.openai_api_key.get_secret_value() == "environment-key"
    assert "environment-key" not in repr(settings)
    settings.ensure_directories()
    assert settings.agent_log_path() == tmp_path / "private/logs/klipperai.log"
    for name in ("../shared.log", "/tmp/shared.log", "shared.txt"):
        with pytest.raises(ValidationError, match="plain .log"):
            Settings(agent_log_file_name=name)


def test_command_environment_keeps_diagnostics_and_drops_provider_keys(monkeypatch):
    import sys

    monkeypatch.setenv("KLIPPERAI_OPENAI_API_KEY", "private-key")
    monkeypatch.setenv("OPENAI_API_KEY", "other-private-key")
    monkeypatch.setenv("DIAGNOSTIC_VALUE", "retained")
    result = SystemCommandRunner().run(
        (
            sys.executable,
            "-c",
            "import os; print(os.getenv('KLIPPERAI_OPENAI_API_KEY'), os.getenv('OPENAI_API_KEY'), os.getenv('DIAGNOSTIC_VALUE')); print('password=command-secret')",
        )
    )
    assert "None None retained" in result.stdout
    assert "command-secret" not in result.stdout and REDACTED in result.stdout
