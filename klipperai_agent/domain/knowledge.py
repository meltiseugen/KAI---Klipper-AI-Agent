"""Public component identities, source documents and application-storage ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import Field, StrictBool, constr, root_validator, validator

from klipperai_agent.domain.base import BaseModel
from klipperai_agent.domain.hardware import (
    BusMapping,
    ConnectorObservation,
    DiagramNote,
    PdfPageIndex,
)

MCU_PIN_PATTERN = r"(?:P[A-Z][0-9]+|P[0-9]+\.[0-9]+|gpio[0-9]+)"


class ComponentIdentity(BaseModel):
    role: str = Field(regex=r"^[a-z][a-z0-9_-]{0,39}$")
    category: Literal["board", "probe", "device"] = "board"
    manufacturer: str = Field(default="", max_length=80)
    model: str = Field(default="", max_length=120)
    revision: str = Field(default="", max_length=30)
    mcu: str = Field(default="", max_length=60, regex=r"^[A-Za-z0-9_-]*$")
    connection: Literal["unknown", "USB", "CAN", "UART", "I2C", "SPI"] = "unknown"
    confirmed: StrictBool = False
    reference_urls: list[constr(max_length=2048)] = Field(default_factory=list, max_items=3)  # type: ignore[valid-type]

    @validator("role")
    def named_component(cls, value: str) -> str:
        if value == "all":
            raise ValueError("Use a component name other than the reserved search scope 'all'.")
        return value

    class Config:
        extra = "forbid"


class KnowledgeSetup(BaseModel):
    components: list[ComponentIdentity] = Field(default_factory=list, max_items=12)
    printer_model: str = Field(default="", max_length=120)
    firmware_flavor: str = Field(default="", max_length=80)
    firmware_version: str = Field(default="", max_length=120)
    facts: str = Field(
        default="",
        max_length=3000,
        description="User-confirmed wiring details and past resolutions; dated when saved.",
    )
    profile_signature: str = ""
    updated_at: str = ""
    revision: int = Field(default=0, ge=0)
    reviewed_fan_mappings: dict[str, str] = Field(default_factory=dict)
    reviewed_bus_mappings: dict[str, str] = Field(default_factory=dict)
    connectors: list[ConnectorObservation] = Field(default_factory=list, max_items=64)
    diagram_notes: list[DiagramNote] = Field(default_factory=list, max_items=64)
    firmware_repository: str = Field(default="", max_length=200)
    firmware_commit: str = Field(default="", max_length=40)
    validation: dict = Field(default_factory=dict)

    @root_validator
    def pinned_firmware(cls, values: dict) -> dict:
        import re

        repository, commit = (
            values.get("firmware_repository", ""),
            values.get("firmware_commit", ""),
        )
        if repository or commit:
            if not re.fullmatch(
                r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository
            ) or not re.fullmatch(r"[a-fA-F0-9]{40}", commit):
                raise ValueError(
                    "Use a public GitHub repository URL and full 40-character firmware commit."
                )
        values["firmware_commit"] = commit.lower()
        return values

    @validator("components")
    def unique_roles(cls, value: list[ComponentIdentity]) -> list[ComponentIdentity]:
        if len({item.role for item in value}) != len(value):
            raise ValueError("Each component role may appear only once.")
        return value

    class Config:
        extra = "forbid"


@dataclass(frozen=True)
class DocumentSource:
    id: str
    title: str
    url: str
    component_key: str = ""


class FanMapping(BaseModel):
    connector: str = Field(min_length=1, max_length=60)
    pin: str = Field(regex="^" + MCU_PIN_PATTERN + "$")
    quote: str = Field(min_length=1, max_length=1200)
    electrical: str = Field(default="", max_length=1000)

    class Config:
        extra = "forbid"


class CachedDocument(BaseModel):
    id: str
    title: str
    url: str
    kind: str
    digest: str
    fetched_at: str
    content: str = ""
    version: str = ""
    component_key: str = ""
    fan_mappings: list[FanMapping] = Field(default_factory=list, max_items=16)
    bus_mappings: list[BusMapping] = Field(default_factory=list, max_items=64)
    firmware_commit: str = ""
    firmware_repository: str = ""
    pages: list[PdfPageIndex] = Field(default_factory=list, max_items=80)
    index_notes: list[str] = Field(default_factory=list, max_items=12)


class KnowledgeConflict(ValueError):
    pass


class KnowledgeRepository(Protocol):
    def setup(self) -> KnowledgeSetup | None: ...
    def save_setup(self, setup: KnowledgeSetup) -> KnowledgeSetup: ...
    def documents(self) -> list[CachedDocument]: ...
    def save_document(self, document: CachedDocument, original: bytes) -> None: ...
    def original(self, document_id: str, digest: str | None = None) -> bytes | None: ...
    def retain_components(self, keys: set[str]) -> None: ...
    def retain_sources(self, component_key: str, ids: set[str]) -> None: ...


class DocumentationFetcher(Protocol):
    async def fetch(self, source: DocumentSource) -> tuple[bytes, str, str]: ...


class KnowledgeResearcher(Protocol):
    async def discover(
        self, component: ComponentIdentity, setup: KnowledgeSetup
    ) -> list[DocumentSource]: ...
    async def extract(
        self, component: ComponentIdentity, document: CachedDocument
    ) -> list[FanMapping]: ...
