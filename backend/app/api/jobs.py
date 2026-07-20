"""REST routes for baseline build and scenario jobs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response

from backend.app.models.job_models import BaselineRebuildRequest, BaselineSelectRequest, JobCreateRequest, JobResponse
from backend.app.services.baseline_service import list_available_baselines, set_active_baseline
from backend.app.services.config_service import load_defaults
from backend.app.services.job_service import (
    build_scenario_zip_bytes,
    create_baseline_rebuild_job,
    create_job,
    get_job,
    get_job_activities_geojson,
    get_job_log,
    get_job_outputs,
    get_job_population_geojson,
    get_profiles_config,
)

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/config/defaults")
def get_defaults() -> dict[str, Any]:
    return load_defaults()


@router.get("/config/profiles")
def get_profiles() -> dict[str, Any]:
    return get_profiles_config()


@router.get("/config/baselines")
def get_baselines() -> dict[str, Any]:
    baselines = list_available_baselines()
    active = next((item for item in baselines if item.get("active")), None)
    return {
        "baselines": baselines,
        "baseline_run_id": active["baseline_run_id"] if active else None,
    }


@router.put("/config/baseline")
def select_baseline(payload: BaselineSelectRequest) -> dict[str, Any]:
    return set_active_baseline(payload.baseline_run_id)


@router.post("/baseline/rebuild", response_model=JobResponse)
def rebuild_baseline_endpoint(payload: BaselineRebuildRequest | None = None) -> JobResponse:
    request = payload or BaselineRebuildRequest()
    return create_baseline_rebuild_job(target_population=request.target_population)


@router.post("/jobs", response_model=JobResponse)
def create_job_endpoint(payload: JobCreateRequest) -> JobResponse:
    return create_job(payload)


@router.get("/jobs/{job_id}")
def get_job_endpoint(job_id: str) -> dict[str, Any]:
    return get_job(job_id)


@router.get("/jobs/{job_id}/outputs")
def get_job_outputs_endpoint(job_id: str) -> dict[str, Any]:
    return get_job_outputs(job_id)


@router.get("/jobs/{job_id}/log")
def get_job_log_endpoint(job_id: str) -> dict[str, Any]:
    return get_job_log(job_id)


@router.get("/jobs/{job_id}/population.geojson")
def get_job_population_geojson_endpoint(job_id: str) -> dict[str, Any]:
    return get_job_population_geojson(job_id)


@router.get("/jobs/{job_id}/activities.geojson")
def get_job_activities_geojson_endpoint(job_id: str) -> dict[str, Any]:
    return get_job_activities_geojson(job_id)


@router.get("/jobs/{job_id}/scenario.zip")
def get_job_scenario_zip_endpoint(job_id: str) -> Response:
    zip_bytes, filename = build_scenario_zip_bytes(job_id)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
