from __future__ import annotations

from pathlib import Path

import klipperai_agent.config.lookup as config_lookup
import klipperai_agent.config.macro_names as config_macro_names
from klipperai_agent.config.collector import ConfigCollector
from klipperai_agent.config.lookup import build_config_lookup_response
from klipperai_agent.config.matching import (
    _infer_feature_from_section_name,
    _section_matches_prefix,
)
from klipperai_agent.config.models import (
    ConfigDocument,
    ConfigPlaceholder,
    ConfigRequestTarget,
    ConfigSectionLocation,
    ConfigSnapshot,
)
from klipperai_agent.config.parser import ConfigParser
from klipperai_agent.config.targeting import (
    infer_config_request_target,
    looks_like_config_request,
)


def test_config_value_objects_render_and_round_trip() -> None:
    placeholder = ConfigPlaceholder("printer.cfg", 2, "pin: <PIN>", "<PIN>", "fan", "pin")
    assert "section [fan]" in placeholder.summary()
    snapshot = ConfigSnapshot(
        root_file="printer.cfg",
        documents=[ConfigDocument("printer.cfg", "[fan]\npin: <PIN>", ["fan"])],
        section_locations=[ConfigSectionLocation("printer.cfg", 1, "fan")],
        placeholders=[placeholder],
        notes=["note"],
    )
    prompt = snapshot.to_prompt_block(max_documents=1)
    assert "Detected placeholder" in prompt
    restored = ConfigSnapshot.from_state(snapshot.to_state())
    assert restored.placeholders[0].option == "pin"
    assert restored.section_locations[0].summary() == "[fan] at printer.cfg:1"
    assert restored.find_section_locations(ConfigRequestTarget("fan", "test", section_name="FAN"))

    empty = ConfigSnapshot(root_file=None, documents=[])
    assert "No config files" in empty.to_prompt_block()


def test_config_collector_reports_missing_invalid_and_unresolved_roots(tmp_path: Path) -> None:
    assert "does not exist" in ConfigCollector(tmp_path / "missing").collect().notes[0]

    data = tmp_path / "file-data"
    data.mkdir()
    (data / "config").write_text("file", encoding="utf-8")
    assert "not a directory" in ConfigCollector(data).collect().notes[0]

    empty = tmp_path / "empty"
    (empty / "config").mkdir(parents=True)
    assert "No root config" in ConfigCollector(empty).collect().notes[0]

    missing = ConfigCollector(empty, root_config_name="missing.cfg").collect()
    assert "was not found" in missing.notes[0]
    directory = empty / "config" / "directory.cfg"
    directory.mkdir()
    non_file = ConfigCollector(empty, root_config_name="directory.cfg").collect()
    assert "not a file" in non_file.notes[0]


def test_config_collector_bounds_clips_cycles_and_missing_includes(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "printer.cfg").write_text(
        "[include printer.cfg]\n[include missing/*.cfg]\n[include child.cfg]\n[printer]\nkinematics: cartesian\n",
        encoding="utf-8",
    )
    (config / "child.cfg").write_text("[fan]\npin: PA1\n" + "x" * 100, encoding="utf-8")
    collector = ConfigCollector(
        tmp_path,
        root_config_name=str(config / "printer.cfg"),
        ignore_globs=[" blank ", ""],
        max_documents=1,
        max_chars_per_document=50,
    )
    snapshot = collector.collect()
    assert len(snapshot.documents) == 1
    assert any("stopped after 1" in note for note in snapshot.notes)

    unlimited = ConfigCollector(
        tmp_path, root_config_name="printer.cfg", max_chars_per_document=50
    ).collect()
    assert any("matched no files" in note for note in unlimited.notes)
    assert any("...[truncated]..." in document.content for document in unlimited.documents)


def test_config_collector_read_and_resolution_error_paths(monkeypatch, tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    root = config / "printer.cfg"
    root.write_text("[printer]\n", encoding="utf-8")
    collector = ConfigCollector(tmp_path, root_config_name="printer.cfg")

    original_read = Path.read_text
    monkeypatch.setattr(
        Path, "read_text", lambda self, *args, **kwargs: (_ for _ in ()).throw(OSError("bad"))
    )
    snapshot = collector.collect()
    assert any("Could not read" in note for note in snapshot.notes)
    monkeypatch.setattr(Path, "read_text", original_read)

    visited = set()
    documents = []
    notes = []
    original_resolve = Path.resolve
    monkeypatch.setattr(
        Path, "resolve", lambda self, *args, **kwargs: (_ for _ in ()).throw(OSError("bad"))
    )
    collector._collect_file(root, visited, documents, [], [], notes)
    assert documents
    monkeypatch.setattr(Path, "resolve", original_resolve)

    assert collector._relative_path_string(tmp_path.parent / "outside.cfg").endswith("outside.cfg")


def test_auto_detection_skips_unreadable_candidates(monkeypatch, tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    candidate = config / "candidate.cfg"
    candidate.write_text("[printer]\n", encoding="utf-8")
    monkeypatch.setattr(
        Path, "read_text", lambda self, *args, **kwargs: (_ for _ in ()).throw(OSError("bad"))
    )
    snapshot = ConfigCollector(tmp_path).collect()
    assert snapshot.root_file is None
    assert any("No root config" in note for note in snapshot.notes)


def test_config_request_edge_cases_and_lookup_responses() -> None:
    generic = infer_config_request_target("please help")
    assert generic.feature == "generic"
    assert looks_like_config_request("plain diagnostics") is False
    assert _infer_feature_from_section_name("unknown custom") == "generic"
    assert _section_matches_prefix("stepper_x", "stepper_") is True
    assert _section_matches_prefix("fan", "fan") is True
    assert _section_matches_prefix("fantastic", "fan") is False
    assert _section_matches_prefix("fan2", "fan") is True

    target = ConfigRequestTarget("fan", "test")
    snapshot = ConfigSnapshot(
        root_file="printer.cfg",
        documents=[],
        section_locations=[
            ConfigSectionLocation("a.cfg", 1, "fan"),
            ConfigSectionLocation("b.cfg", 2, "fan_generic aux"),
        ],
    )
    text, actions = build_config_lookup_response(snapshot, target)
    assert "2 active" in text
    assert actions

    text, actions = build_config_lookup_response(ConfigSnapshot(None, []), target)
    assert "couldn't find" in text
    assert len(actions) == 2


def test_normalizers_and_placeholder_parser() -> None:
    assert ConfigCollector._normalize_root_config_name("  ") is None
    assert ConfigCollector._normalize_ignore_globs(None) == ()
    assert ConfigCollector._normalize_ignore_globs("a, b;c") == ("a", "b", "c")
    placeholders = ConfigParser.detect_placeholders(
        Path("x.cfg"),
        "[include y.cfg]\n[fan]\ninvalid line\npin: PA1\nother: '<OTHER_PIN>' # comment\n",
    )
    assert len(placeholders) == 1
    assert placeholders[0].value == "<OTHER_PIN>"


def test_config_parser_and_macro_edge_paths(monkeypatch, tmp_path: Path) -> None:
    snapshot = ConfigSnapshot(
        root_file="printer.cfg",
        documents=[ConfigDocument("printer.cfg", "[fan]\npin: PA1", ["fan"])],
    )
    assert snapshot.section_block(ConfigSectionLocation("missing.cfg", 1, "fan")) is None
    assert snapshot.section_block(ConfigSectionLocation("printer.cfg", 99, "fan")) is None

    assert infer_config_request_target("Change [fan]").intent == "edit"
    assert infer_config_request_target("Explain [fan]").intent == "explain"
    assert infer_config_request_target("Edit START_PRINT macro").intent == "edit"
    assert infer_config_request_target("Change my fan settings").intent == "edit"
    assert infer_config_request_target("Explain my fan settings").intent == "explain"

    assert (
        config_macro_names._extract_macro_section_name("Run STARTPRINT") == "gcode_macro STARTPRINT"
    )
    assert config_macro_names._last_macro_candidate("") is None
    assert config_macro_names._last_macro_candidate("one two three four five") is not None
    assert config_macro_names._first_macro_candidate("START_PRINT now") == "gcode_macro START_PRINT"
    assert config_macro_names._first_macro_candidate("the alpha beta") == "gcode_macro ALPHA_BETA"
    assert (
        config_macro_names._first_macro_candidate("alpha beta in gamma") == "gcode_macro ALPHA_BETA"
    )
    assert (
        config_macro_names._first_macro_candidate("alpha beta gamma delta epsilon")
        == "gcode_macro ALPHA_BETA_GAMMA_DELTA"
    )
    assert config_macro_names._first_macro_candidate("") is None
    assert config_macro_names._normalize_macro_name_candidate(
        "the START_PRINT macro", allow_plain=True
    )
    assert (
        config_macro_names._normalize_macro_name_candidate(
            "alpha beta gamma delta epsilon", allow_plain=True
        )
        is None
    )
    assert (
        config_macro_names._normalize_macro_name_candidate("foo in bar", allow_plain=True) is None
    )
    assert config_macro_names._normalize_macro_name_candidate("lower", allow_plain=False) is None
    original_fullmatch = config_macro_names.re.fullmatch
    monkeypatch.setattr(config_macro_names.re, "fullmatch", lambda *_args, **_kwargs: None)
    assert config_macro_names._normalize_macro_name_candidate("VALID", allow_plain=True) is None
    monkeypatch.setattr(config_macro_names.re, "fullmatch", original_fullmatch)

    definition = ConfigSectionLocation("macros.cfg", 1, "gcode_macro TEST")
    content = "[gcode_macro TEST]\ndescription: demo\ngcode:\n  G28\n" + "\n".join(
        f"TEST ; call {index}" for index in range(10)
    )
    macro_snapshot = ConfigSnapshot(
        root_file="macros.cfg",
        documents=[
            ConfigDocument("macros.cfg", content, ["gcode_macro TEST"]),
            ConfigDocument(
                "caller.cfg", "[gcode_macro CALLER]\ngcode:\n  TEST\n  TEST", ["gcode_macro CALLER"]
            ),
        ],
        section_locations=[definition],
    )
    references = config_lookup._find_macro_references(
        macro_snapshot, "TEST", definition=definition, limit=2
    )
    assert len(references) == 2
    assert "no direct calls" in config_lookup._format_macro_reference_lines("NONE", [])[0]
    assert config_lookup._macro_name_from_section("fan") is None

    assert config_lookup._format_macro_behavior_lines(None) == []
    assert config_lookup._format_macro_behavior_lines("[gcode_macro X]\ndescription: only") == [
        "Description: only"
    ]
    behavior = config_lookup._format_macro_behavior_lines(
        "[gcode_macro X]\n"
        "description: demo\n"
        "variable_value: 1\n"
        "ignored before gcode\n"
        "gcode: G28\n"
        "\n"
        "{% if true %}\n"
        "G90\nG91\nM400\nG28\nG29\nM117 done\n"
    )
    assert any("more command" in line for line in behavior)
    assert "disables filament sensor" in config_lookup._summarize_macro_command(
        "SET_FILAMENT_SENSOR SENSOR=runout ENABLE=0"
    )
    assert "updates filament sensor" in config_lookup._summarize_macro_command(
        "SET_FILAMENT_SENSOR SENSOR=runout"
    )
    assert "runs" in config_lookup._summarize_macro_command("G28")

    duplicate_snapshot = ConfigSnapshot(
        root_file="macros.cfg",
        documents=[],
        section_locations=[
            ConfigSectionLocation("one.cfg", 1, "gcode_macro TEST"),
            ConfigSectionLocation("two.cfg", 1, "gcode_macro TEST"),
        ],
    )
    duplicate_text, duplicate_actions = build_config_lookup_response(
        duplicate_snapshot,
        ConfigRequestTarget(
            "macro",
            "test",
            intent="locate",
            section_name="gcode_macro TEST",
        ),
    )
    assert "2 active definitions" in duplicate_text
    assert duplicate_actions

    exact_text, _ = build_config_lookup_response(
        macro_snapshot,
        ConfigRequestTarget(
            "macro",
            "test",
            intent="explain",
            section_name="gcode_macro TEST",
        ),
        include_content=True,
    )
    assert "```ini" in exact_text

    lookup_snapshot = ConfigSnapshot(
        root_file="printer.cfg",
        documents=[ConfigDocument("printer.cfg", "[fan]\npin: PA1", ["fan"])],
        section_locations=[ConfigSectionLocation("printer.cfg", 1, "fan")],
    )
    text, _ = build_config_lookup_response(
        lookup_snapshot,
        ConfigRequestTarget("fan", "test", intent="explain", section_name="fan"),
        include_content=True,
    )
    assert "```ini" in text


def test_unincluded_collector_limits_and_resolution_failure(monkeypatch, tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    candidate = config_dir / "extra.cfg"
    candidate.write_text("[fan]\n", encoding="utf-8")

    limited = ConfigCollector(tmp_path, max_documents=0)
    limited._collect_unincluded_config_files(set(), [], [], [], [])

    collector = ConfigCollector(tmp_path)
    original_resolve = Path.resolve
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda self, *args, **kwargs: (_ for _ in ()).throw(OSError("bad")),
    )
    documents: list[ConfigDocument] = []
    collector._collect_unincluded_config_files(set(), documents, [], [], [])
    assert documents
    monkeypatch.setattr(Path, "resolve", original_resolve)


def test_config_source_lines_survive_leading_blanks_and_bounded_excerpts(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "printer.cfg").write_text(
        "\n\n[fan]\npin: PA1\n" + "# padding\n" * 20 + "[extruder]\nstep_pin: PA2"
    )
    snapshot = ConfigCollector(
        tmp_path, root_config_name="printer.cfg", max_chars_per_document=60
    ).collect()
    fan = next(location for location in snapshot.section_locations if location.section == "fan")
    extruder = next(
        location for location in snapshot.section_locations if location.section == "extruder"
    )
    assert fan.line_number == 3
    assert snapshot.section_block(fan).startswith("[fan]\npin: PA1")
    assert snapshot.section_block(extruder) is None
    assert any("truncated" in note for note in snapshot.notes)
    assert len(snapshot.documents[0].content) == 60
    assert ConfigCollector._clip_text("abcdef", 3) == "abc"
