from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from klipperai_agent.profile.values import _first_non_empty, _string


class HostDetector:
    def __init__(self, timeout_seconds: float = 4.0) -> None:
        self._git_timeout_seconds = timeout_seconds

    @staticmethod
    def extract_klipper_version_info(update_status: Any) -> dict[str, Any]:
        if not isinstance(update_status, dict):
            return {}
        version_info = update_status.get("version_info")
        if not isinstance(version_info, dict):
            return {}
        klipper = version_info.get("klipper")
        return klipper if isinstance(klipper, dict) else {}

    def detect_firmware_flavor(
        self, klipper_version_info: dict[str, Any], repo_origin: str | None
    ) -> str | None:
        owner = _string(klipper_version_info.get("owner"))
        repo_name = _string(klipper_version_info.get("repo_name"))
        remote_url = repo_origin or _string(klipper_version_info.get("remote_url"))
        candidate = " ".join(item for item in (owner, repo_name, remote_url) if item)
        lowered = candidate.lower()
        if "kalicocrew" in lowered or "kalico" in lowered:
            return "Kalico"
        if "klipper3d" in lowered or "/klipper" in lowered:
            return "Klipper"
        if candidate:
            return "Custom Klipper fork"
        return None

    def detect_host_model(self, system_info: Any) -> str | None:
        if not isinstance(system_info, dict):
            return None
        cpu_info = system_info.get("cpu_info")
        if isinstance(cpu_info, dict):
            return _first_non_empty(
                _string(cpu_info.get("model")),
                _string(cpu_info.get("hardware_desc")),
                _string(cpu_info.get("cpu_desc")),
            )
        return None

    def detect_distribution(self, system_info: Any) -> str | None:
        if not isinstance(system_info, dict):
            return None
        distribution = system_info.get("distribution")
        if isinstance(distribution, dict):
            name = _string(distribution.get("name"))
            version = _string(distribution.get("version"))
            if name and version:
                return f"{name} {version}"
            return name or version
        return None

    def extract_services(self, system_info: Any) -> list[str]:
        if not isinstance(system_info, dict):
            return []
        service_state = system_info.get("service_state")
        if not isinstance(service_state, dict):
            return []
        return sorted(str(key) for key in service_state)

    def extract_canbus_interfaces(self, system_info: Any) -> list[str]:
        if not isinstance(system_info, dict):
            return []
        canbus = system_info.get("canbus")
        if not isinstance(canbus, dict):
            return []
        return sorted(str(key) for key in canbus)

    def detect_git_remote(self, repo_path: str) -> str | None:
        path = Path(repo_path).expanduser()
        if not path.exists():
            return None
        try:
            result = subprocess.run(
                ["git", "-C", str(path), "config", "--get", "remote.origin.url"],
                capture_output=True,
                text=True,
                timeout=self._git_timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        remote = result.stdout.strip()
        return remote or None
