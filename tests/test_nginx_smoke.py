"""Exercise the generated location through real nginx, never the host nginx service."""

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request

import pytest

from tests.release_helpers import ROOT, daemon, free_port, http
from tests.test_installer import bash


def test_real_nginx_routes_klipperai_and_preserves_mainsail(tmp_path, run_shell):
    nginx = shutil.which("nginx")
    if not nginx:
        if os.environ.get("KLIPPERAI_REQUIRE_NGINX") == "1":
            pytest.fail("CI requires a real nginx binary for the reverse-proxy smoke test.")
        pytest.skip("real nginx is required; Linux CI installs it")
    frontend_port = free_port()
    with daemon(tmp_path) as backend:
        backend_port = backend.rsplit(":", 1)[1]
        snippet = tmp_path / "location.conf"
        bash(
            run_shell,
            """
set -euo pipefail
source "$1/deployment/installer/nginx.sh"
OUTPUT="$2"
KLIPPERAI_ROOT_PATH=/klipperai
KLIPPERAI_PORT="$3"
backup_file() { :; }
run_root() { [[ "$1" == install ]] || return 1; cp "${@: -2:1}" "$OUTPUT"; }
write_nginx_snippet
""",
            ROOT.as_posix(),
            snippet.as_posix(),
            backend_port,
        )
        config = tmp_path / "nginx.conf"
        config.write_text(f"""
worker_processes 1;
pid {tmp_path.as_posix()}/nginx.pid;
error_log {tmp_path.as_posix()}/nginx.log;
events {{ worker_connections 32; }}
http {{
  access_log off;
  client_body_temp_path {tmp_path.as_posix()}/body;
  proxy_temp_path {tmp_path.as_posix()}/proxy;
  server {{
    listen 127.0.0.1:{frontend_port};
    include {snippet.as_posix()};
    location ~* \\.(css|js)$ {{ return 200 'mainsail-asset'; }}
    location / {{ return 200 'mainsail'; }}
  }}
}}
""")
        process = subprocess.Popen(
            [nginx, "-p", tmp_path.as_posix() + "/", "-c", str(config), "-g", "daemon off;"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        base = f"http://127.0.0.1:{frontend_port}"
        try:
            deadline = time.monotonic() + 10
            while True:
                try:
                    with http(base, "/") as response:
                        assert response.read() == b"mainsail"
                    break
                except OSError:
                    if process.poll() is not None or time.monotonic() >= deadline:
                        process.terminate()
                        raise AssertionError(process.stderr.read().decode())
                    time.sleep(0.1)

            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *args):
                    return None

            opener = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))
            with pytest.raises(urllib.error.HTTPError) as redirect:
                opener.open(base + "/klipperai?probe=1", timeout=3)
            assert redirect.value.code == 308
            assert redirect.value.headers["Location"] == "/klipperai/?probe=1"
            with http(base, "/klipperai/") as response:
                assert b'data-api-base="/klipperai/api"' in response.read()
            with http(base, "/klipperai/assets/embed.css") as response:
                assert b"mainsail-asset" not in response.read()
                assert "text/css" in response.headers["Content-Type"]
            with http(base, "/klipperai/readyz") as response:
                assert json.load(response)["printer_access"] == "read_only"
            with http(base, "/klipperai/api/ui-sessions", {}) as response:
                session = json.load(response)["session_id"]
            with http(base, "/klipperai/api/bootstrap?session_id=" + session) as response:
                assert json.load(response)["provider_configured"] is False
            with pytest.raises(urllib.error.HTTPError) as chat:
                http(
                    base, "/klipperai/api/chat", {"session_id": session, "message": "Check printer"}
                )
            assert chat.value.code == 503
        finally:
            process.terminate()
            process.communicate(timeout=5)
