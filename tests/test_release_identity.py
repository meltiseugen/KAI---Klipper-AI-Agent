import json

import pytest
from fastapi.testclient import TestClient

import kai_agent.__main__ as main
import kai_agent.runtime.release as release
from kai_agent.domain.moonraker import AGENT_VERSION
from kai_agent.domain.version import __version__


def test_cli_version_does_not_load_settings_or_touch_printer(monkeypatch, capsys):
    monkeypatch.setattr(main.sys, "argv", ["kai-agent", "--version"])
    monkeypatch.setattr(
        main, "get_settings", lambda: pytest.fail("Version must not initialize settings")
    )
    main.main()
    assert capsys.readouterr().out.strip() == __version__ == AGENT_VERSION


@pytest.mark.parametrize(
    "content,build",
    [
        (None, "source"),
        ("not-json", "source"),
        ("[]", "source"),
        ('{"build":3}', "source"),
        ('{"build":"private data"}', "source"),
        (json.dumps({"build": "a" * 16}), "a" * 16),
    ],
)
def test_build_identity_is_bounded_public_metadata(tmp_path, monkeypatch, content, build):
    package = tmp_path / "kai_agent"
    runtime = package / "runtime"
    runtime.mkdir(parents=True)
    monkeypatch.setattr(release, "__file__", str(runtime / "release.py"))
    if content is not None:
        (package / "build-info.json").write_text(content)
    assert release.release_info() == {"version": __version__, "build": build}


def test_readiness_works_without_provider_or_printer_io(monkeypatch, tmp_path):
    import kai_agent
    import kai_agent.web.app as web
    from kai_agent.runtime.settings import Settings

    monkeypatch.setattr(web, "get_settings", lambda: Settings(_env_file=None, data_dir=tmp_path))
    app = web.create_app()
    assert app.version == __version__
    assert kai_agent.__version__ == __version__
    # No lifespan/container needed; readiness makes no outbound requests.
    response = TestClient(app).get("/readyz")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "printer_access": "read_only",
        **release.release_info(),
    }
