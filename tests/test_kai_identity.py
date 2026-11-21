"""Fresh KAI installations use one consistent package, configuration and identity."""

from pathlib import Path

from kai_agent.infrastructure.credential_cipher import CREDENTIAL_NAME, PREFIX
from kai_agent.runtime.settings import Settings


def test_kai_defaults_and_environment_use_the_new_identity(monkeypatch):
    monkeypatch.setenv("KAI_ROOT_PATH", "/kai")
    settings = Settings()
    assert settings.app_name == "KAI"
    assert settings.root_path == "/kai"
    assert settings.managed_config_dir_name == "kai"
    assert settings.agent_log_file_name == "kai.log"
    assert Settings.Config.env_prefix == "KAI_"
    assert CREDENTIAL_NAME == "kai-provider-master"
    assert PREFIX == "kai:aes256gcm:v1:"
    assert Path("kai_agent/__main__.py").is_file()
