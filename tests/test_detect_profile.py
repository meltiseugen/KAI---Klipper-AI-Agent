from __future__ import annotations

import argparse
from types import SimpleNamespace

import pytest

import klipperai_agent.cli.detect_profile as detect_profile
from klipperai_agent.infrastructure.moonraker import MoonrakerError
from klipperai_agent.profile.models import PrinterProfile


class _Moonraker:
    instances = []

    def __init__(self, url: str) -> None:
        self.url = url
        self.closed = False
        self.instances.append(self)

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_run_detection_collects_writes_and_reports(monkeypatch, tmp_path, capsys) -> None:
    cfg = tmp_path / "klippyai.cfg"
    cfg.write_text("[server]\n", encoding="utf-8")
    config_dir = tmp_path / "printer_data" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "printer.cfg").write_text("[printer]\nkinematics: corexy\n", encoding="utf-8")
    profile = PrinterProfile(firmware_flavor="Kalico", mainboard="Octopus", notes=["one", "two"])
    written = {}

    class Collector:
        def __init__(self, moonraker, config_collector) -> None:
            assert moonraker.url == "http://moonraker"
            self.config_collector = config_collector

        async def collect(self, snapshot):
            assert snapshot.root_file.endswith("printer.cfg")
            return profile

    monkeypatch.setattr(detect_profile, "MoonrakerClient", _Moonraker)
    monkeypatch.setattr(detect_profile, "PrinterProfileCollector", Collector)
    monkeypatch.setattr(
        detect_profile, "_detect_root_config_override", lambda *_args: _async_value("printer.cfg")
    )
    monkeypatch.setattr(
        detect_profile,
        "write_profile_to_cfg",
        lambda *args, **kwargs: written.update(args=args, kwargs=kwargs),
    )

    args = argparse.Namespace(
        config_file=str(cfg),
        moonraker_url="http://moonraker",
        printer_data_root=str(tmp_path / "printer_data"),
        overwrite=True,
    )
    assert await detect_profile._run_detection(args) == 0
    assert written["kwargs"]["root_config_file"] == "printer.cfg"
    assert written["kwargs"]["overwrite"] is True
    assert _Moonraker.instances[-1].closed is True
    output = capsys.readouterr().out
    assert "Kalico" in output
    assert "Active root config" in output
    assert "note: one" in output


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_run_detection_requires_existing_config(tmp_path) -> None:
    args = argparse.Namespace(
        config_file=str(tmp_path / "missing.cfg"),
        moonraker_url="http://moonraker",
        printer_data_root=str(tmp_path),
        overwrite=False,
    )
    with pytest.raises(FileNotFoundError, match="does not exist"):
        await detect_profile._run_detection(args)


@pytest.mark.asyncio
async def test_detect_root_override_handles_fields_and_connection_errors(
    monkeypatch, tmp_path
) -> None:
    class Client:
        async def get_printer_info(self):
            return {
                "config_file": " ",
                "config_path": str(tmp_path / "config" / "nested" / "main.cfg"),
            }

    assert (
        await detect_profile._detect_root_config_override(Client(), tmp_path) == "nested/main.cfg"
    )

    class Failed:
        async def get_printer_info(self):
            raise MoonrakerError("offline")

    assert await detect_profile._detect_root_config_override(Failed(), tmp_path) is None

    class NoPath:
        async def get_printer_info(self):
            return {"other": "value"}

    assert await detect_profile._detect_root_config_override(NoPath(), tmp_path) is None


def test_normalize_root_config_setting_and_parser(tmp_path) -> None:
    assert detect_profile._normalize_root_config_setting(None, tmp_path) is None
    assert detect_profile._normalize_root_config_setting("  ", tmp_path) is None
    assert (
        detect_profile._normalize_root_config_setting("nested/main.cfg", tmp_path)
        == "nested/main.cfg"
    )
    outside = (tmp_path.parent / "outside.cfg").resolve()
    assert detect_profile._normalize_root_config_setting(outside, tmp_path) == outside.as_posix()

    args = detect_profile.build_argument_parser().parse_args(
        ["--config-file", "a", "--moonraker-url", "b", "--printer-data-root", "c", "--overwrite"]
    )
    assert args.overwrite is True


def test_detect_profile_main_runs_async_entrypoint(monkeypatch) -> None:
    args = SimpleNamespace()
    parser = SimpleNamespace(parse_args=lambda: args)
    monkeypatch.setattr(detect_profile, "build_argument_parser", lambda: parser)
    monkeypatch.setattr(detect_profile.asyncio, "run", lambda coroutine: (coroutine.close(), 4)[1])
    with pytest.raises(SystemExit) as exc:
        detect_profile.main()
    assert exc.value.code == 4
