"""Immutable firmware source selection; a pinned reference is not a live-version claim."""

from hashlib import sha256

from klipperai_agent.domain.knowledge import DocumentSource, KnowledgeSetup


def firmware_key(setup: KnowledgeSetup) -> str:
    return sha256((setup.firmware_repository + "@" + setup.firmware_commit).encode()).hexdigest()


def firmware_sources(setup: KnowledgeSetup) -> list[DocumentSource]:
    if not setup.firmware_commit:
        return []
    repo = setup.firmware_repository.removeprefix("https://github.com/")
    return [
        DocumentSource(
            sha256((firmware_key(setup) + path).encode()).hexdigest()[:32],
            f"Firmware {path} @ {setup.firmware_commit[:12]}",
            f"https://raw.githubusercontent.com/{repo}/{setup.firmware_commit}/{path}",
            firmware_key(setup),
        )
        for path in (
            "docs/Config_Reference.md",
            "docs/Command_Templates.md",
            "docs/Config_Changes.md",
        )
    ]


def firmware_scope(setup: KnowledgeSetup, live_version: str = "") -> dict:
    import re

    hashes = re.findall(r"(?<![a-f0-9])g?([a-f0-9]{7,40})(?![a-f0-9])", live_version.casefold())
    matched = bool(
        setup.firmware_commit and any(setup.firmware_commit.startswith(value) for value in hashes)
    )
    return {
        "repository": setup.firmware_repository,
        "commit": setup.firmware_commit,
        "live_version": live_version,
        "commit_prefix_matches": matched,
        "compatibility_verified": False,
        "note": "A reported commit prefix matches the selected reference; confirm repository/fork and MCU builds separately."
        if matched
        else "Installed firmware has not been matched to the selected source commit. References do not prove command or hardware compatibility.",
    }
