from __future__ import annotations

import fnmatch
import glob
import hashlib
import re
from pathlib import Path

from klipperai_agent.config.models import (
    ConfigDocument,
    ConfigPlaceholder,
    ConfigReadError,
    ConfigSectionLocation,
    ConfigSnapshot,
)
from klipperai_agent.config.parser import ConfigParser
from klipperai_agent.domain.redaction import redact_text

MAX_CONFIG_CHARS = 1_000_000


def read_config_text(path: Path) -> str:
    """Bound allocation before parsing; preserve universal newline/digest semantics."""
    with path.open(encoding="utf-8", errors="replace") as handle:
        parts: list[str] = []
        size = 0
        while size <= MAX_CONFIG_CHARS:
            chunk = handle.read(min(65536, MAX_CONFIG_CHARS + 1 - size))
            if not chunk:
                break
            parts.append(chunk)
            size += len(chunk)
    if size > MAX_CONFIG_CHARS:
        raise ConfigReadError("Configuration exceeds the full-read limit.")
    return "".join(parts)


class ConfigCollector:
    def __init__(
        self,
        printer_data_root: Path,
        *,
        config_dir_name: str = "config",
        root_config_name: str | None = None,
        ignore_globs: str | list[str] | tuple[str, ...] | None = None,
        max_documents: int | None = None,
        max_chars_per_document: int | None = None,
    ) -> None:
        self.parser = ConfigParser()
        self._config_dir = printer_data_root / config_dir_name
        self._root_config_name = self._normalize_root_config_name(root_config_name)
        self._ignore_globs = self._normalize_ignore_globs(ignore_globs)
        self._max_documents = max_documents
        self._max_chars_per_document = max_chars_per_document

    def collect(self) -> ConfigSnapshot:
        return self.collect_with_options()

    def read_collected_document(self, document: ConfigDocument) -> ConfigDocument:
        """Expand a collector-issued reference; tools cannot supply this reference directly."""
        path = self._config_dir / document.path
        # Bound expansion independently of model context, and reject mid-run edits.
        try:
            content = read_config_text(path)
        except OSError as exc:
            raise ConfigReadError(
                "Configuration could not be read. Refresh the evidence and retry."
            ) from exc
        digest = hashlib.sha256(content.encode()).hexdigest()
        if digest != document.content_digest:
            raise ConfigReadError(
                "Configuration changed during this investigation. Start a new question to refresh the evidence."
            )
        return ConfigDocument(
            document.path, redact_text(content).rstrip(), document.sections, digest
        )

    def collect_with_options(self, *, include_unincluded_configs: bool = False) -> ConfigSnapshot:
        notes: list[str] = []
        if not self._config_dir.exists():
            notes.append(f"Config directory does not exist: {self._config_dir}")
            return ConfigSnapshot(root_file=None, documents=[], notes=notes)

        if not self._config_dir.is_dir():
            notes.append(f"Config path is not a directory: {self._config_dir}")
            return ConfigSnapshot(root_file=None, documents=[], notes=notes)

        root_file = self._resolve_root_file(notes)
        if root_file is None:
            return ConfigSnapshot(root_file=None, documents=[], notes=notes)

        visited: set[Path] = set()
        documents: list[ConfigDocument] = []
        section_locations: list[ConfigSectionLocation] = []
        placeholders: list[ConfigPlaceholder] = []
        self._collect_file(root_file, visited, documents, section_locations, placeholders, notes)
        if include_unincluded_configs:
            self._collect_unincluded_config_files(
                visited, documents, section_locations, placeholders, notes
            )
        if self._max_documents is not None and len(documents) >= self._max_documents:
            notes.append(
                f"Config collection stopped after {self._max_documents} files to keep context bounded."
            )

        return ConfigSnapshot(
            root_file=self._relative_path_string(root_file),
            documents=documents,
            section_locations=section_locations,
            placeholders=placeholders,
            notes=notes,
        )

    @staticmethod
    def _normalize_root_config_name(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _normalize_ignore_globs(value: str | list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            parts = [item.strip() for item in re.split(r"[,\n;]+", value) if item.strip()]
            return tuple(parts)
        return tuple(str(item).strip() for item in value if str(item).strip())

    def _resolve_root_file(self, notes: list[str]) -> Path | None:
        if self._root_config_name:
            root_file = self._resolve_root_candidate(self._root_config_name)
            if not root_file.exists():
                notes.append(
                    f"Configured root config file was not found: {self._relative_path_string(root_file)}"
                )
                return None
            if not root_file.is_file():
                notes.append(
                    f"Configured root config path is not a file: {self._relative_path_string(root_file)}"
                )
                return None
            return root_file

        auto_detected = self._auto_detect_root_file()
        if auto_detected is None:
            notes.append(f"No root config file could be auto-detected under: {self._config_dir}")
            return None
        notes.append(f"Auto-detected root config file: {self._relative_path_string(auto_detected)}")
        return auto_detected

    def _resolve_root_candidate(self, value: str) -> Path:
        candidate = Path(value).expanduser()
        if candidate.is_absolute():
            return candidate
        return self._config_dir / candidate

    def _auto_detect_root_file(self) -> Path | None:
        # Prefer the conventional active root to reading every archived config.
        # An explicitly configured root remains authoritative.
        standard = self._config_dir / "printer.cfg"
        if standard.is_file() and not self._should_ignore(standard):
            try:
                if any(
                    section.lower() == "printer"
                    for section in self.parser.extract_sections(read_config_text(standard))
                ):
                    return standard
            except (OSError, ConfigReadError):
                pass
        candidates = [
            path
            for path in self._config_dir.rglob("*.cfg")
            if path.is_file() and not self._should_ignore(path)
        ]
        if not candidates:
            return None

        ranked: list[tuple[int, Path]] = []
        for path in candidates:
            try:
                content = read_config_text(path)
            except (OSError, ConfigReadError):
                continue
            sections = self.parser.extract_sections(content)
            includes = self.parser.extract_include_patterns(content)
            score = 0
            if path.name.lower() == "printer.cfg":
                score += 8
            if path.parent == self._config_dir:
                score += 3
            if any(section.lower() == "printer" for section in sections):
                score += 12
            score += min(len(includes), 5)
            ranked.append((score, path))

        if not ranked:
            return None

        ranked.sort(key=lambda item: (item[0], str(item[1]).lower()), reverse=True)
        return ranked[0][1]

    def _collect_file(
        self,
        path: Path,
        visited: set[Path],
        documents: list[ConfigDocument],
        section_locations: list[ConfigSectionLocation],
        placeholders: list[ConfigPlaceholder],
        notes: list[str],
    ) -> None:
        if self._max_documents is not None and len(documents) >= self._max_documents:
            return

        try:
            resolved = path.resolve()
        except OSError:
            resolved = path

        if resolved in visited:
            return
        visited.add(resolved)

        try:
            raw_content = read_config_text(path)
        except (OSError, ConfigReadError) as exc:
            notes.append(f"Could not read config file {self._relative_path_string(path)}: {exc}")
            return

        display_path = self._relative_path_string(path)
        sections = self.parser.extract_sections(raw_content)
        section_locations.extend(self.parser.extract_section_locations(display_path, raw_content))
        placeholders.extend(self.parser.detect_placeholders(display_path, raw_content))
        # Keep leading blank lines and indentation: citations use original file line numbers.
        content = redact_text(raw_content).rstrip()
        clipped_content = self._clip_text(content, self._max_chars_per_document)
        if clipped_content != content:
            notes.append(f"Config content truncated after the opening excerpt: {display_path}")
        documents.append(
            ConfigDocument(
                path=display_path,
                content=clipped_content,
                sections=sections,
                content_digest=hashlib.sha256(raw_content.encode()).hexdigest(),
                truncated=clipped_content != content,
            )
        )

        for pattern in self.parser.extract_include_patterns(raw_content):
            matches = self._resolve_include_matches(path.parent, pattern)
            if not matches:
                notes.append(f"Include pattern matched no files: {pattern} (from {display_path})")
                continue
            for match in matches:
                if self._should_ignore(match):
                    notes.append(
                        f"Ignored config file due to config_context.ignore_globs: {self._relative_path_string(match)}"
                    )
                    continue
                self._collect_file(
                    match, visited, documents, section_locations, placeholders, notes
                )
                if self._max_documents is not None and len(documents) >= self._max_documents:
                    return

    def _collect_unincluded_config_files(
        self,
        visited: set[Path],
        documents: list[ConfigDocument],
        section_locations: list[ConfigSectionLocation],
        placeholders: list[ConfigPlaceholder],
        notes: list[str],
    ) -> None:
        if self._ignore_globs:
            notes.append(
                "File inventory is filtered by config_context.ignore_globs; absence of ignored targets cannot be verified."
            )
        candidates = [
            path
            for path in sorted(
                self._config_dir.rglob("*.cfg"), key=lambda candidate: candidate.as_posix().lower()
            )
            if path.is_file() and not self._should_ignore(path)
        ]
        added = 0
        for path in candidates:
            if self._relative_path_string(path) != path.relative_to(self._config_dir).as_posix():
                notes.append(
                    "File inventory contains a redirected config path; verify managed targets manually."
                )
            if self._max_documents is not None and len(documents) >= self._max_documents:
                return
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if resolved in visited:
                continue

            notes.append(
                "Additional config file collected for lookup context; it may not be active unless included: "
                f"{self._relative_path_string(path)}"
            )
            before_count = len(documents)
            self._collect_file(path, visited, documents, section_locations, placeholders, notes)
            if len(documents) > before_count:
                added += 1

        if added:
            notes.append(
                f"Collected {added} additional config file(s) outside the active include walk for lookup context."
            )

    @staticmethod
    def _resolve_include_matches(base_dir: Path, pattern: str) -> list[Path]:
        expanded_pattern = str((base_dir / pattern).expanduser())
        matches = [
            Path(candidate)
            for candidate in sorted(glob.glob(expanded_pattern))
            if Path(candidate).is_file()
        ]
        return matches

    def _should_ignore(self, path: Path) -> bool:
        if not self._ignore_globs:
            return False
        relative = self._relative_path_string(path)
        path_name = path.name
        absolute = path.as_posix()
        return any(
            fnmatch.fnmatch(relative, pattern)
            or fnmatch.fnmatch(path_name, pattern)
            or fnmatch.fnmatch(absolute, pattern)
            for pattern in self._ignore_globs
        )

    def _relative_path_string(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self._config_dir.resolve()).as_posix()
        except (OSError, ValueError):
            try:
                return path.relative_to(self._config_dir).as_posix()
            except ValueError:
                return path.as_posix()

    @staticmethod
    def _clip_text(text: str, limit: int | None) -> str:
        if limit is None or len(text) <= limit:
            return text

        # Never splice the tail into a shortened document: that changes source line numbers.
        marker = "\n...[truncated]..."
        if limit < len(marker):
            return text[: max(limit, 0)]
        return text[: limit - len(marker)] + marker
