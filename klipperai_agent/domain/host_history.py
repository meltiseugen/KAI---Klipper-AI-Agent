"""Public, bounded host measurements; no process arguments or environment."""

from __future__ import annotations

from pydantic import Field

from klipperai_agent.domain.base import BaseModel


class ProcessSample(BaseModel):
    pid: int = Field(ge=1)
    name: str = Field(max_length=64)
    cpu_percent_one_core: float | None = Field(default=None, ge=0)
    rss_kib: int = Field(ge=0)


class PressureSample(BaseModel):
    some_avg10: float | None = Field(default=None, ge=0, le=100)
    full_avg10: float | None = Field(default=None, ge=0, le=100)
    some_total_us: int | None = Field(default=None, ge=0)
    full_total_us: int | None = Field(default=None, ge=0)


class HostSample(BaseModel):
    unix_time: float = Field(ge=0)
    uptime_seconds: float = Field(ge=0)
    interval_seconds: float | None = Field(default=None, gt=0)
    cpu_busy_percent: float | None = Field(default=None, ge=0, le=100)
    cpu_iowait_percent: float | None = Field(default=None, ge=0, le=100)
    memory_kib: dict[str, int] = Field(default_factory=dict)
    vm_counters: dict[str, int] = Field(default_factory=dict)
    pressure: dict[str, PressureSample] = Field(default_factory=dict)
    processes: list[ProcessSample] = Field(default_factory=list, max_items=8)
    notes: list[str] = Field(default_factory=list, max_items=12)

    class Config:
        allow_inf_nan = False
