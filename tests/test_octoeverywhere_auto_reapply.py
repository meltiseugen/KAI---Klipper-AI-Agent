from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "integrations/octoeverywhere"


@pytest.fixture
def moonraker_updates():
    state = {"result": {"busy": True}, "refreshes": 0, "status": 200}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"result": state["result"]}).encode()
            self.send_response(state["status"])
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            assert self.path.startswith("/machine/update/refresh?")
            state["refreshes"] += 1
            self.do_GET()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture
def reapply(tmp_path, oe_checkout, run_shell, shell_env, moonraker_updates):
    root, router, ui = oe_checkout
    state, url = moonraker_updates
    legacy_backup = router.with_name(router.name + ".klippyai-backup-old")
    legacy_backup.write_text("legacy\n")
    runner = tmp_path / "reapply"
    env = {
        **shell_env,
        "KLIPPERAI_OE_RUNNER_PATH": runner.as_posix(),
        "KLIPPERAI_SYSTEMD_DIR": (tmp_path / "systemd").as_posix(),
    }
    run_shell(
        (INTEGRATION / "apply-local-klipperai-route-patch.sh").as_posix(),
        "--oe-root",
        root.as_posix(),
        env=env,
    )
    run_shell(
        (INTEGRATION / "install-auto-reapply.sh").as_posix(),
        "--install-dir",
        ROOT.as_posix(),
        "--oe-root",
        root.as_posix(),
        "--moonraker-url",
        url,
        env=env,
    )
    state_dir = Path(env["KLIPPERAI_STATE_DIR"])
    assert (state_dir / "octoeverywhere-backups/legacy" / legacy_backup.name).exists()
    assert not legacy_backup.exists()
    assert (tmp_path / "systemd/klipperai-octoeverywhere-reapply.path").exists()
    # A systemd runner must retain its configured storage without shell environment hints.
    env.pop("HOME", None)
    env.pop("KLIPPERAI_STATE_DIR")

    def run(check=True):
        return run_shell(runner.as_posix(), env=env, check=check)

    return state, router, ui, state_dir, run


def test_auto_reapply_coordinates_pending_update(reapply):
    state, router, ui, state_dir, run = reapply
    state["result"] = {
        "busy": False,
        "version_info": {"OctoEverywhere": {"commits_behind_count": 2}},
    }
    run()
    assert "KlipperAI local route patch init start" not in router.read_text()
    assert "KlipperAI local route patch start" not in ui.read_text()
    assert (state_dir / "octoeverywhere-reapply.suspended").exists()
    assert state["refreshes"] == 1
    run()  # An already clean checkout does not keep refreshing Moonraker.
    assert state["refreshes"] == 1
    state["result"]["version_info"]["OctoEverywhere"]["commits_behind_count"] = 0
    run()
    assert "KlipperAI local route patch init start" in router.read_text()
    assert not (state_dir / "octoeverywhere-reapply.suspended").exists()
    before = router.read_bytes(), ui.read_bytes()
    run()
    assert (router.read_bytes(), ui.read_bytes()) == before


@pytest.mark.parametrize(
    "result,status,code",
    [
        ({"busy": True}, 200, 0),
        ({"version_info": {"octoeverywhere": {"commits_behind_count": 0}}}, 200, 1),
        ({"busy": False, "version_info": {}}, 200, 1),
        ({"busy": False, "version_info": {"octoeverywhere": {}}}, 200, 1),
        ({"busy": False, "version_info": {"octoeverywhere": {"commits_behind_count": -1}}}, 200, 1),
        (
            {"busy": False, "version_info": {"octoeverywhere": {"commits_behind_count": True}}},
            200,
            1,
        ),
        (
            {"busy": False, "version_info": {"octoeverywhere": {"commits_behind_count": "0"}}},
            200,
            1,
        ),
        ({}, 503, 1),
    ],
)
def test_auto_reapply_leaves_checkout_and_suspension_unchanged(reapply, result, status, code):
    state, router, ui, state_dir, run = reapply
    marker = state_dir / "octoeverywhere-reapply.suspended"
    marker.write_text("Waiting for update")
    before = router.read_bytes(), ui.read_bytes()
    state.update(result=result, status=status)
    assert run(check=False).returncode == code
    assert (router.read_bytes(), ui.read_bytes()) == before
    assert marker.read_text() == "Waiting for update"
    assert state["refreshes"] == 0


def test_hook_install_enables_retries_even_if_initial_moonraker_query_fails(
    tmp_path, oe_checkout, run_shell, shell_env, moonraker_updates
):
    state, url = moonraker_updates
    state["status"] = 503
    runner = tmp_path / "reapply"
    units = tmp_path / "systemd"
    calls = tmp_path / "service-calls"
    fake = tmp_path / "shell-bin/systemctl"
    fake.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$SYSTEMCTL_CALLS"\n', encoding="utf-8", newline="\n"
    )
    env = {
        **shell_env,
        "SYSTEMCTL_CALLS": calls.as_posix(),
        "KLIPPERAI_OE_RUNNER_PATH": runner.as_posix(),
        "KLIPPERAI_SYSTEMD_DIR": units.as_posix(),
    }
    result = run_shell(
        (INTEGRATION / "install-auto-reapply.sh").as_posix(),
        "--install-dir",
        ROOT.as_posix(),
        "--oe-root",
        oe_checkout[0].as_posix(),
        "--moonraker-url",
        url,
        env=env,
    )
    assert "retries remain enabled" in result.stderr
    assert "enable --now klipperai-octoeverywhere-reapply.timer" in calls.read_text()
    assert "enable --now klipperai-octoeverywhere-reapply.path" in calls.read_text()
    assert (
        "restart klipperai-octoeverywhere-reapply.timer klipperai-octoeverywhere-reapply.path"
        in calls.read_text()
    )
    assert (
        "OnUnitInactiveSec=5min" in (units / "klipperai-octoeverywhere-reapply.timer").read_text()
    )
    assert "OnBootSec=30s" in (units / "klipperai-octoeverywhere-reapply.timer").read_text()
    assert (
        "WantedBy=timers.target" in (units / "klipperai-octoeverywhere-reapply.timer").read_text()
    )
    state.update(
        status=200,
        result={"busy": False, "version_info": {"octoeverywhere": {"commits_behind_count": 0}}},
    )
    run_shell(runner.as_posix(), env=env)
    before = calls.read_text().splitlines()
    assert before.count("restart octoeverywhere") == 1
    run_shell(runner.as_posix(), env=env)
    assert calls.read_text().splitlines() == before
