from __future__ import annotations

import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "integrations/octoeverywhere/apply-local-klipperai-route-patch.sh"
RoutePatch = runpy.run_path(str(SCRIPT.with_name("route_patch.py")))["RoutePatch"]


@pytest.mark.parametrize("prefix", ["/klipperai", "/assistant/printer"])
def test_patch_routes_round_trip_and_idempotence(oe_checkout, run_shell, prefix):
    root, router, ui = oe_checkout
    original_router, original_ui = router.read_text(), ui.read_text()
    args = [SCRIPT.as_posix(), "--oe-root", root.as_posix(), "--klipperai-prefix", prefix]
    run_shell(*args)
    patched_router, patched_ui = router.read_text(), ui.read_text()
    assert "KlipperAI local route patch start" in patched_ui
    namespace = {}
    exec(compile(patched_router, str(router), "exec"), namespace)
    cls = namespace["MoonrakerApiRouter"]
    instance = cls.__new__(cls)
    instance.Logger = SimpleNamespace(info=lambda _: None)
    instance.MoonrakerHostAndPortStr = "127.0.0.1:7125"
    cls.__init__(instance)
    for suffix, forwarded in [
        ("", "/"),
        ("?rescue=1", "/?rescue=1"),
        ("/", "/"),
        ("/direct?rescue=1", "/direct?rescue=1"),
        ("/assets/agent.js", "/assets/agent.js"),
        ("/api/bootstrap?session_id=a%20b", "/api/bootstrap?session_id=a%20b"),
        ("/api/chat/stream", "/api/chat/stream"),
        ("/api/investigations/thread", "/api/investigations/thread"),
        (
            "/api/investigations/t/proposals/p/revalidate",
            "/api/investigations/t/proposals/p/revalidate",
        ),
    ]:
        assert instance.MapRelativePathToAbsolutePathIfNeeded(prefix + suffix, "http://") == (
            "http://127.0.0.1:8811" + forwarded
        )
    for url in ("", "/api/printer", prefix + "-other", "/different" + prefix):
        assert instance.MapRelativePathToAbsolutePathIfNeeded(url, "http://") is None
    run_shell(*args)
    assert (router.read_text(), ui.read_text()) == (patched_router, patched_ui)
    run_shell(*args, "--restore-original")
    assert (router.read_text(), ui.read_text()) == (original_router, original_ui)


@pytest.mark.parametrize("damage", ["router-anchor", "ui-anchor", "incomplete-marker"])
def test_patch_refuses_upstream_drift_without_changing_either_file(oe_checkout, run_shell, damage):
    root, router, ui = oe_checkout
    if damage == "router-anchor":
        router.write_text(router.read_text().replace("# !! Interface Function !!", "# changed"))
    elif damage == "ui-anchor":
        ui.write_text("// upstream changed its initialization\n")
    else:
        ui.write_text(ui.read_text() + "// KlipperAI local route patch start\n")
    before = router.read_bytes(), ui.read_bytes()
    result = run_shell(SCRIPT.as_posix(), "--oe-root", root.as_posix(), check=False)
    assert result.returncode != 0
    assert (router.read_bytes(), ui.read_bytes()) == before


@pytest.mark.parametrize(
    "options",
    [
        {"prefix": "/"},
        {"prefix": "/bad?query"},
        {"prefix": "/bad\npath"},
        {"port": "0"},
        {"port": "65536"},
        {"port": "abc"},
        {"target": "frame"},
    ],
)
def test_patch_rejects_invalid_configuration(options):
    with pytest.raises(ValueError):
        RoutePatch(**options)
