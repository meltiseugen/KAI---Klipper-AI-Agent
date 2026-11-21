"""Read-only log references and bounded, redacted observations."""

from dataclasses import dataclass, field

LOG_WINDOW_BYTES = 256 * 1024
LOG_INFLATE_BYTES = 8 * 1024 * 1024
LOG_RUN_BYTES = 12 * 1024 * 1024
LOG_RUN_WINDOWS = 8


class LogReadError(ValueError):
    """A fixed public explanation of unavailable log evidence."""


@dataclass(frozen=True)
class LogFile:
    id: str
    name: str
    size_bytes: int
    modified_at: str
    device: int
    inode: int
    compressed: bool = False
    rotated: bool = False


@dataclass
class LogInventory:
    files: list[LogFile] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    truncated: bool = False


@dataclass(frozen=True)
class LogWindow:
    id: str
    log_id: str
    name: str
    content: str
    observed_at: str
    digest: str
    start_byte: int
    end_byte: int
    next_before_byte: int | None
    partial: bool
    compressed: bool
