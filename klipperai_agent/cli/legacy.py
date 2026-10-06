"""Compatibility for installed command names, without a second Python package."""

from __future__ import annotations

import os

from klipperai_agent.__main__ import main
from klipperai_agent.cli.detect_profile import main as detect_profile


def export_legacy_environment() -> None:
    """Map legacy variables without overriding the current configuration."""
    for key, value in tuple(os.environ.items()):
        if key.startswith("KLIPPYAI_"):
            os.environ.setdefault(f"KLIPPERAI_{key.removeprefix('KLIPPYAI_')}", value)


def agent_main() -> None:
    export_legacy_environment()
    main()


def detect_main() -> None:
    export_legacy_environment()
    detect_profile()
