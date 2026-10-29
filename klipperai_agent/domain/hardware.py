"""Explicitly confirmed physical observations and source-scoped bus evidence."""

from typing import Literal

from pydantic import Field, StrictBool, root_validator

from klipperai_agent.domain.base import BaseModel


class BusMapping(BaseModel):
    bus: str = Field(regex=r"^[A-Za-z0-9_]{1,60}$")
    pins: list[str] = Field(min_items=1, max_items=8)
    quote: str = Field(min_length=1, max_length=1200)


class ConnectorObservation(BaseModel):
    role: str = Field(regex=r"^[a-z][a-z0-9_-]{0,39}$")
    connector: str = Field(min_length=1, max_length=60)
    occupancy: Literal["unknown", "free", "occupied"] = "unknown"
    attached_device: str = Field(default="", max_length=160)
    electrical_notes: str = Field(default="", max_length=500)
    electrical_confirmed: StrictBool = False
    confirmed: StrictBool = False
    observed_at: str = ""
    identity_signature: str = ""

    @root_validator
    def explicit_observation(cls, values: dict) -> dict:
        if not values.get("confirmed"):
            raise ValueError("Explicit physical observation confirmation is required.")
        if values.get("occupancy") == "occupied" and not values.get("attached_device", "").strip():
            raise ValueError("Name the device occupying this connector.")
        if values.get("electrical_confirmed") and not values.get("electrical_notes", "").strip():
            raise ValueError("Record the checked electrical requirements.")
        return values

    class Config:
        extra = "forbid"


class PdfPageIndex(BaseModel):
    page: int = Field(ge=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    text: str = Field(max_length=24000)
    images: int = Field(default=0, ge=0)
    vector_paths: int = Field(default=0, ge=0)
    diagram_labels: list[str] = Field(default_factory=list, max_items=32)
    needs_visual_review: bool = True


class DiagramNote(BaseModel):
    document_id: str = Field(regex=r"^[a-f0-9]{32}$")
    digest: str = Field(regex=r"^[a-f0-9]{64}$")
    page: int = Field(ge=1, le=80)
    text: str = Field(min_length=3, max_length=2000)
    confirmed: StrictBool
    observed_at: str = ""

    class Config:
        extra = "forbid"
