from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class BaselineRebuildRequest(BaseModel):
    target_population: int | None = None


class JobCreateRequest(BaseModel):
    selected_area_geojson: dict[str, Any] | None = None
    config_overrides: dict[str, Any] = Field(default_factory=dict)
    bikesharing_station_availability: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-station available bike counts (city_station_id keys). Generator input; not written to synpp YAML.",
    )
    target_population: int | None = None
    target_households: int | None = None


class JobResponse(BaseModel):
    job_id: str
    run_id: str
    status: str
    message: str


@dataclass
class JobRuntime:
    process: subprocess.Popen[str]
    log_path: Path
    output_path: Path
    output_prefix: str
