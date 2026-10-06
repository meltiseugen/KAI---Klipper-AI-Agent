from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import klipperai_agent.profile.persistence as profile_persistence
from klipperai_agent.config.collector import ConfigCollector
from klipperai_agent.config.models import ConfigDocument, ConfigSnapshot
from klipperai_agent.infrastructure.moonraker import MoonrakerError
from klipperai_agent.profile.collector import PrinterProfileCollector
from klipperai_agent.profile.models import (
    DetectedAddon,
    PrinterProfile,
    ProfileEvidence,
    _as_bool,
)
from klipperai_agent.profile.persistence import write_profile_to_cfg
from klipperai_agent.profile.saved import _split_addon_names
from klipperai_agent.profile.values import _first_non_empty


def _collector(tmp_path: Path) -> PrinterProfileCollector:
    return PrinterProfileCollector(SimpleNamespace(), ConfigCollector(tmp_path))  # type: ignore[arg-type]


def _snapshot(path: str = "printer.cfg", content: str = "", sections=()) -> ConfigSnapshot:
    return ConfigSnapshot(
        root_file=path,
        documents=[ConfigDocument(path=path, content=content, sections=list(sections))],
    )


def test_profile_ini_rewrite_edge_paths(monkeypatch, tmp_path: Path) -> None:
    assert profile_persistence._split_ini_blocks(["plain\n"]) == (["plain\n"], [])
    assert (
        profile_persistence._rewrite_ini_section_block(
            [], values={}, removed_option_names=set(), newline="\n"
        )
        == ""
    )
    rewritten = profile_persistence._rewrite_ini_section_block(
        ["[section]\n", "key: old\n", "key: duplicate\n", "other: keep\n"],
        values={"key": "new"},
        removed_option_names=set(),
        newline="\n",
    )
    assert rewritten.count("key: new") == 1
    assert "other: keep" in rewritten

    config = tmp_path / "profile.cfg"
    config.write_text("[section]\n", encoding="utf-8")
    monkeypatch.setattr(
        profile_persistence, "_rewrite_ini_section_block", lambda *_args, **_kwargs: "block"
    )
    profile_persistence._rewrite_cfg_preserving_comments(
        config,
        section_values={},
        removed_sections=set(),
        removed_options={},
    )
    assert config.read_text(encoding="utf-8") == "block\n"


def test_profile_rendering_state_roundtrip_and_summaries() -> None:
    addon = DetectedAddon("Beacon", "config", "high", "probe")
    assert addon.to_state()["detail"] == "probe"
    profile = PrinterProfile(
        firmware_flavor="Kalico",
        firmware_version="v1",
        printer_state="ready",
        state_message="Ready",
        host_model="Pi",
        host_distribution="Debian",
        mainboard="Octopus",
        mainboard_mcu="stm32",
        toolhead="Stealthburner",
        toolhead_board="EBB36",
        probe_type="beacon",
        accelerometer="adxl345",
        filament_sensor="switch",
        camera_stack="crowsnest",
        mcu_names=["mcu", "toolhead"],
        canbus_interfaces=["can0"],
        addons=[addon],
        notes=["note"],
        evidence=[ProfileEvidence("detected", "test", "high")],
    )
    assert "Kalico v1" in profile.summary_label()
    assert "EBB36" in profile.summary_label()
    assert "Beacon" in profile.summary_label()
    prompt = profile.to_prompt_block()
    for expected in (
        "Printer state",
        "Host model",
        "Mainboard",
        "Toolhead",
        "Probe type",
        "MCUs",
        "CAN interfaces",
        "Detected addons",
        "Profile notes",
    ):
        assert expected in prompt
    state = profile.to_state()
    restored = PrinterProfile.from_state(state)
    assert restored.to_summary()["summary"] == profile.summary_label()
    assert restored.addons[0].detail == "probe"
    assert (
        PrinterProfile(firmware_flavor="Klipper", mainboard="Board").summary_label()
        == "Klipper | Board"
    )


def test_write_profile_overwrite_split_and_bool_helpers(tmp_path: Path) -> None:
    cfg = tmp_path / "klippyai.cfg"
    cfg.write_text("[printer_identity]\nfirmware_flavor = Old\n", encoding="utf-8")
    write_profile_to_cfg(cfg, PrinterProfile(firmware_flavor="New"), overwrite=True)
    assert "firmware_flavor = New" in cfg.read_text(encoding="utf-8")
    write_profile_to_cfg(cfg, PrinterProfile(firmware_flavor="Ignored"), overwrite=False)
    assert "firmware_flavor = New" in cfg.read_text(encoding="utf-8")
    write_profile_to_cfg(cfg, PrinterProfile(canbus_interfaces=["can0"]), overwrite=False)
    write_profile_to_cfg(cfg, PrinterProfile(), overwrite=False)
    assert "canbus_enabled: true" in cfg.read_text(encoding="utf-8")
    assert _split_addon_names(None) == []
    assert _split_addon_names("Beacon, beacon; Eddy") == ["Beacon", "Eddy"]
    assert _as_bool(True) is True
    assert _as_bool(None) is False
    assert _as_bool("yes") is True


@pytest.mark.asyncio
async def test_optional_collection_and_scalar_helpers(tmp_path: Path) -> None:
    collector = _collector(tmp_path)

    async def fail():
        raise MoonrakerError("offline")

    notes = []
    assert await collector._collect_optional("server", fail, notes) is None
    assert notes == ["Could not collect server: offline"]
    assert _first_non_empty(None, "") is None
    assert collector.host.extract_klipper_version_info("bad") == {}
    assert collector.host.extract_klipper_version_info({"version_info": "bad"}) == {}
    assert (
        collector.host.detect_firmware_flavor({}, "https://github.com/Klipper3d/klipper")
        == "Klipper"
    )
    assert (
        collector.host.detect_firmware_flavor({}, "https://example.com/fork")
        == "Custom Klipper fork"
    )
    assert collector.host.detect_firmware_flavor({}, None) is None
    assert collector.host.detect_host_model("bad") is None
    assert collector.host.detect_host_model({}) is None
    assert collector.host.detect_distribution("bad") is None
    assert collector.host.detect_distribution({"distribution": {"version": "12"}}) == "12"
    assert collector.host.detect_distribution({}) is None
    assert collector.host.extract_services("bad") == []
    assert collector.host.extract_services({}) == []
    assert collector.host.extract_canbus_interfaces("bad") == []
    assert collector.host.extract_canbus_interfaces({}) == []


def test_git_remote_detection_success_empty_and_error(monkeypatch, tmp_path: Path) -> None:
    collector = _collector(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(
        "klipperai_agent.profile.host.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout="https://example.com/repo.git\n"),
    )
    assert collector.host.detect_git_remote(str(repo)) == "https://example.com/repo.git"
    monkeypatch.setattr(
        "klipperai_agent.profile.host.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout=""),
    )
    assert collector.host.detect_git_remote(str(repo)) is None
    monkeypatch.setattr(
        "klipperai_agent.profile.host.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("git missing")),
    )
    assert collector.host.detect_git_remote(str(repo)) is None


def test_hardware_feature_detection_fallbacks(tmp_path: Path) -> None:
    collector = _collector(tmp_path)
    generic_probe = _snapshot(content="[probe]", sections=["probe"])
    assert collector.capabilities.detect_probe_type(generic_probe, []) == "generic"
    assert collector.capabilities.detect_probe_type(_snapshot(), []) == "none"
    assert (
        collector.capabilities.detect_accelerometer(_snapshot(sections=["lis2dw"]), []) == "lis2dw"
    )
    assert (
        collector.capabilities.detect_accelerometer(_snapshot(sections=["resonance_tester"]), [])
        == "generic"
    )
    assert collector.capabilities.detect_accelerometer(_snapshot(), []) == "none"
    assert (
        collector.capabilities.detect_filament_sensor(
            _snapshot(sections=["filament_motion_sensor runout"])
        )
        == "motion"
    )
    assert (
        collector.capabilities.is_bed_mesh_configured(_snapshot(sections=["bed_mesh"]), []) is True
    )
    assert collector.capabilities.detect_camera_stack([], []) == "none"


def test_mcu_selection_and_description_fallbacks(tmp_path: Path) -> None:
    collector = _collector(tmp_path)
    parsed = [
        {"section": "not_mcu", "options": {}, "path": "x"},
        {"section": "mcu aux", "options": {"canbus_uuid": "1234567890abcdef"}, "path": "x"},
    ]
    sections = collector.hardware.extract_mcu_sections(parsed)
    assert collector.hardware.select_primary_mcu(sections) == sections[0]
    assert collector.hardware.select_primary_mcu([]) is None
    assert collector.hardware.select_toolhead_mcu(sections) == sections[0]
    assert collector.hardware.describe_mcu({"options": "bad"}, [], []) is None

    serial = "/dev/serial/by-id/usb-Klipper_stm32f446xx_123-if00"
    serial_device = {"path_by_id": serial, "usb_location": "1:1", "device_name": "ttyACM0"}
    assert (
        collector.hardware.describe_mcu(
            {"options": {"serial": serial}},
            [serial_device],
            [{"usb_location": "1:1", "product": "MCU"}],
        )
        == "MCU"
    )
    no_usb = {"path_by_id": serial, "device_name": "ttyACM0"}
    assert collector.hardware.describe_mcu({"options": {"serial": serial}}, [no_usb], []) == serial
    assert (
        collector.hardware.describe_mcu({"options": {"serial": "/dev/ttyUSB0"}}, [], [])
        == "ttyUSB0"
    )
    assert (
        collector.hardware.describe_mcu({"options": {"canbus_uuid": "abcdef1234567890"}}, [], [])
        == "CAN UUID abcdef123456"
    )
    assert collector.hardware.describe_mcu({"options": {}}, [], []) is None

    board = collector.hardware.detect_toolhead_board(
        {"name": "aux", "options": {"canbus_uuid": "abcdef1234567890"}}, [], [], _snapshot()
    )
    assert board == "aux (CAN UUID abcdef123456)"
    primary_named = collector.hardware.detect_toolhead_board(
        {"name": "mcu", "options": {"canbus_uuid": "abcdef1234567890"}}, [], [], _snapshot()
    )
    assert primary_named == "CAN UUID abcdef123456"
    assert collector.hardware.detect_toolhead_board(None, [], [], _snapshot()) is None


def test_device_matching_tokens_and_addon_sources(tmp_path: Path) -> None:
    collector = _collector(tmp_path)
    assert collector.hardware._match_serial_device("missing", [{"path_by_id": "other"}]) is None
    assert collector.hardware._match_usb_device(None, []) is None
    assert collector.hardware._match_usb_device("1:1", [{"usb_location": "2:2"}]) is None
    assert (
        collector.hardware._extract_mcu_token("/dev/serial/by-id/usb-Klipper_stm32f4") == "stm32f4"
    )
    assert collector.hardware._extract_mcu_token("custom-device") == "custom-device"
    assert collector.hardware._extract_mcu_token("/dev/ttyACM0") == "ttyACM0"

    section_addons = collector.addons.detect_addons(_snapshot(sections=["beacon"]), [], {}, [])
    assert section_addons[0].source == "Klipper config sections"
    path_addons = collector.addons.detect_addons(_snapshot(path="extras/crowsnest.cfg"), [], {}, [])
    assert path_addons[0].source == "Klipper include paths"
    assert collector.addons.detect_addons(_snapshot(), [], {}, []) == []

    collector.addons._ADDON_SIGNATURES = (("Same", ("one",)), ("Same", ("two",)))
    duplicate = collector.addons.detect_addons(_snapshot(sections=["one", "two"]), [], {}, [])
    assert len(duplicate) == 1
