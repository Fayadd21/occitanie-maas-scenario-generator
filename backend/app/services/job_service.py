"""Job orchestration: baseline build, scenario runs, scenario.zip export.

Job state lives in backend/state/jobs/*.json. Synpp runs as a subprocess; this
module polls exit codes and materializes outputs when runs finish.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
import hashlib
import ast
import io
import re
import zipfile
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from fastapi import HTTPException

from backend.app.models.job_models import JobCreateRequest, JobResponse, JobRuntime
from backend.app.services.baseline_service import (
    baseline_run_id_for_target,
    clear_synpp_cache,
    finalize_baseline_job,
    get_profiles_payload,
    require_baseline_for_scenario,
)
from backend.app.services.config_service import (
    build_baseline_runtime_config,
    build_runtime_config,
    load_defaults,
    new_run_id,
    utc_now,
)
from backend.app.services.constants import (
    CONFIG_TEMPLATE,
    DATA_DIR,
    baseline_artifact_path,
    JOBS_DIR,
    LOGS_DIR,
    OUTPUT_DIR,
    PROFILES_PATH,
)
from backend.app.services.bike_csv_overrides import (
    bike_station_availability_from_job_record,
    cap_availability_to_capacity,
    normalize_bikesharing_station_availability,
)
from backend.app.services.materialize_service import list_outputs, materialize_run_outputs
from backend.app.services.process_service import get_job_runtime, register_job_runtime, start_synpp_process
from backend.app.services.store import JOBS

_refresh_lock = threading.Lock()


def _require_succeeded_job(job_id: str) -> dict[str, Any]:
    record = refresh_status(job_id)
    if record["status"] != "succeeded":
        raise HTTPException(status_code=409, detail="Job is not in succeeded state")
    return record


def _to_wgs84(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.crs is not None and str(gdf.crs).lower() != "epsg:4326":
        return gdf.to_crs("EPSG:4326")
    return gdf


def _job_file(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _read_job_record(job_id: str) -> dict[str, Any]:
    path = _job_file(job_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Unknown job_id: {job_id}")

    last_error: json.JSONDecodeError | None = None
    for _ in range(5):
        try:
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                raise json.JSONDecodeError("Empty job record", text, 0)
            return json.loads(text)
        except json.JSONDecodeError as exc:
            last_error = exc
            time.sleep(0.02)

    raise HTTPException(
        status_code=500,
        detail=f"Job record for {job_id} is corrupt or unreadable",
    ) from last_error


def _write_job_record(job_id: str, payload: dict[str, Any]) -> None:
    path = _job_file(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2)
    tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.replace(tmp_path, path)
        except OSError:
            path.write_text(text, encoding="utf-8")
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _count_csv_rows(csv_path: Path) -> int:
    if not csv_path.is_file():
        return 0
    return len(pd.read_csv(csv_path, sep=";"))


def _attach_scenario_outcome(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("job_type") != "scenario":
        return record

    run_id = str(record["run_id"])
    output_path = Path(record["output_path"])
    generated_persons = _count_csv_rows(output_path / f"{run_id}_persons.csv")
    generated_households = _count_csv_rows(output_path / f"{run_id}_households.csv")

    requested_population = record.get("requested_target_population")
    requested_households = record.get("requested_target_households")

    population_shortfall = (
        requested_population is not None and generated_persons < int(requested_population)
    )
    household_shortfall = (
        requested_households is not None and generated_households < int(requested_households)
    )

    record["generated_person_count"] = generated_persons
    record["generated_household_count"] = generated_households
    record["target_shortfall"] = population_shortfall or household_shortfall
    return record


def refresh_status(job_id: str) -> dict[str, Any]:
    with _refresh_lock:
        record = _read_job_record(job_id)
        runtime = get_job_runtime(job_id)

        if runtime is None:
            return record

        exit_code = runtime.process.poll()
        if exit_code is None:
            if record.get("status") != "running":
                record["status"] = "running"
                _write_job_record(job_id, record)
            return record

        changed = record.get("status") not in ("succeeded", "failed")
        record["status"] = "succeeded" if exit_code == 0 else "failed"
        record["finished_at"] = utc_now()
        record["exit_code"] = exit_code
        if record["status"] == "succeeded":
            if record.get("job_type") == "baseline":
                if not record.get("baseline_promoted", False):
                    record = finalize_baseline_job(record)
                    changed = True
            elif not record.get("outputs_materialized", False):
                materialize_run_outputs(record)
                record["outputs_materialized"] = True
                record = _attach_scenario_outcome(record)
                changed = True

        if changed:
            _write_job_record(job_id, record)

        JOBS.pop(job_id, None)
        return record


def create_job(payload: JobCreateRequest) -> JobResponse:
    require_baseline_for_scenario()

    target_population = payload.target_population
    target_households = payload.target_households

    requested_target_population = int(target_population) if target_population is not None else None
    effective_target_population = requested_target_population

    job_id = uuid.uuid4().hex
    run_id = new_run_id()
    output_path = OUTPUT_DIR / "jobs" / run_id
    output_path.mkdir(parents=True, exist_ok=True)
    runtime_config_path, source_output_path, source_output_prefix, effective_config = build_runtime_config(
        run_id=run_id,
        selected_area_geojson=payload.selected_area_geojson,
        config_overrides=payload.config_overrides,
        target_population=effective_target_population,
        target_households=target_households,
        job_output_path=output_path,
    )
    log_path = LOGS_DIR / f"{job_id}.log"
    process = start_synpp_process(runtime_config_path, log_path)

    register_job_runtime(
        job_id,
        JobRuntime(
            process=process,
            log_path=log_path,
            output_path=output_path,
            output_prefix=f"{run_id}_",
        ),
    )

    bike_station_availability = normalize_bikesharing_station_availability(
        dict(payload.bikesharing_station_availability or {})
    )
    bike_station_availability = bike_station_availability if bike_station_availability is not None else {}

    _write_job_record(
        job_id,
        {
            "job_id": job_id,
            "run_id": run_id,
            "job_type": "scenario",
            "status": "running",
            "created_at": utc_now(),
            "runtime_config": str(runtime_config_path),
            "log_path": str(log_path),
            "output_path": str(output_path),
            "output_prefix": f"{run_id}_",
            "source_output_path": str(source_output_path),
            "source_output_prefix": source_output_prefix,
            "selected_area": bool(payload.selected_area_geojson),
            "target_population": effective_target_population,
            "requested_target_population": requested_target_population,
            "requested_target_households": int(target_households) if target_households is not None else None,
            "outputs_materialized": False,
            "effective_config": effective_config,
            "config_overrides": dict(payload.config_overrides or {}),
            "bikesharing_station_availability": bike_station_availability,
        },
    )

    return JobResponse(
        job_id=job_id,
        run_id=run_id,
        status="running",
        message="Job started",
    )


def create_baseline_rebuild_job(target_population: int | None = None) -> JobResponse:
    defaults = load_defaults()
    resolved_target = int(target_population if target_population is not None else defaults.get("target_population", 59_510))
    if resolved_target <= 0:
        raise HTTPException(status_code=400, detail="target_population must be greater than 0")
    baseline_run_id = baseline_run_id_for_target(resolved_target)
    cleared_cache_dir = clear_synpp_cache()
    job_id = uuid.uuid4().hex
    run_id = f"baseline_build_{uuid.uuid4().hex[:8]}"
    runtime_config_path, source_output_path, source_output_prefix, effective_config = build_baseline_runtime_config(
        run_id=run_id,
        target_population=resolved_target,
        baseline_run_id=baseline_run_id,
    )

    log_path = LOGS_DIR / f"{job_id}.log"
    process = start_synpp_process(runtime_config_path, log_path)

    register_job_runtime(
        job_id,
        JobRuntime(
            process=process,
            log_path=log_path,
            output_path=source_output_path,
            output_prefix=source_output_prefix,
        ),
    )

    _write_job_record(
        job_id,
        {
            "job_id": job_id,
            "run_id": run_id,
            "job_type": "baseline",
            "status": "running",
            "created_at": utc_now(),
            "runtime_config": str(runtime_config_path),
            "log_path": str(log_path),
            "output_path": str(source_output_path),
            "output_prefix": source_output_prefix,
            "source_output_path": str(source_output_path),
            "source_output_prefix": source_output_prefix,
            "baseline_run_id": baseline_run_id,
            "baseline_promoted": False,
            "outputs_materialized": False,
            "effective_config": effective_config,
            "target_population": resolved_target,
            "synpp_cache_cleared": str(cleared_cache_dir),
        },
    )

    return JobResponse(
        job_id=job_id,
        run_id=run_id,
        status="running",
        message="Baseline build started (synpp cache cleared; full pipeline recompute)",
    )


def get_profiles_config() -> dict[str, Any]:
    return get_profiles_payload()


def get_job(job_id: str) -> dict[str, Any]:
    record = refresh_status(job_id)
    if (
        record.get("job_type") == "scenario"
        and record.get("status") == "succeeded"
        and record.get("outputs_materialized")
        and record.get("generated_person_count") is None
    ):
        record = _attach_scenario_outcome(record)
        _write_job_record(job_id, record)
    return record


def get_job_outputs(job_id: str) -> dict[str, Any]:
    record = refresh_status(job_id)
    output_path = Path(record["output_path"])
    return {
        "job_id": job_id,
        "run_id": record["run_id"],
        "status": record["status"],
        "output_path": str(output_path),
        "files": list_outputs(output_path),
    }


def get_job_log(job_id: str) -> dict[str, Any]:
    record = refresh_status(job_id)
    log_path = Path(record["log_path"])
    if not log_path.exists():
        return {"job_id": job_id, "log": ""}
    return {"job_id": job_id, "log": log_path.read_text(encoding="utf-8")}


def get_job_population_geojson(job_id: str) -> dict[str, Any]:
    record = _require_succeeded_job(job_id)

    run_id = str(record["run_id"])
    output_path = Path(record["output_path"])
    homes_path = output_path / f"{run_id}_homes.gpkg"
    households_path = output_path / f"{run_id}_households.csv"
    persons_path = output_path / f"{run_id}_persons.csv"
    if not homes_path.exists():
        raise HTTPException(status_code=404, detail="Population geometry file not found for this job")

    gdf = gpd.read_file(homes_path)
    if gdf.empty:
        return {"type": "FeatureCollection", "features": []}
    if households_path.exists() and "household_id" in gdf.columns:
        df_households = pd.read_csv(households_path, sep=";")
        if "household_id" in df_households.columns and len(df_households) > 0:
            selected_households = set(df_households["household_id"].astype(str).tolist())
            gdf = gdf[gdf["household_id"].astype(str).isin(selected_households)].copy()
        elif persons_path.exists():
            df_persons = pd.read_csv(persons_path, sep=";")
            if "household_id" in df_persons.columns:
                selected_households = set(df_persons["household_id"].astype(str).tolist())
                gdf = gdf[gdf["household_id"].astype(str).isin(selected_households)].copy()
    gdf = _to_wgs84(gdf)

    keep_columns = [column for column in ("household_id", "commune_id", "departement_id", "region_id") if column in gdf.columns]
    gdf = gdf[keep_columns + ["geometry"]]
    return json.loads(gdf.to_json(drop_id=True))


def get_job_activities_geojson(job_id: str) -> dict[str, Any]:
    record = _require_succeeded_job(job_id)

    run_id = str(record["run_id"])
    output_path = Path(record["output_path"])
    activities_path = output_path / f"{run_id}_activities.gpkg"
    if not activities_path.exists():
        raise HTTPException(status_code=404, detail="Activities geometry file not found for this job")

    gdf = gpd.read_file(activities_path)
    if gdf.empty:
        return {"type": "FeatureCollection", "features": []}
    gdf = _to_wgs84(gdf)

    keep_columns = [
        column
        for column in (
            "person_id",
            "household_id",
            "purpose",
            "start_time",
            "end_time",
            "activity_index",
            "commune_id",
            "departement_id",
        )
        if column in gdf.columns
    ]
    gdf = gdf[keep_columns + ["geometry"]]
    return json.loads(gdf.to_json(drop_id=True))


def _resolve_available_bikes_for_station(
    row: pd.Series,
    station_key: str,
    bike_station_availability: dict[str, int] | None,
) -> int:
    capacity = row.get("capacity") if "capacity" in row.index else None
    if bike_station_availability and station_key in bike_station_availability:
        return cap_availability_to_capacity(int(bike_station_availability[station_key]), capacity)
    if "available_bikes" in row.index and not pd.isna(row.get("available_bikes")):
        try:
            return cap_availability_to_capacity(int(row["available_bikes"]), capacity)
        except (TypeError, ValueError):
            pass
    if "num_bikes_available" in row.index and not pd.isna(row.get("num_bikes_available")):
        try:
            return cap_availability_to_capacity(int(float(row["num_bikes_available"])), capacity)
        except (TypeError, ValueError):
            pass
    return 0


def _profiles_path_for_job(record: dict[str, Any]) -> Path:
    effective = record.get("effective_config") or {}
    configured = effective.get("profiles_path")
    if configured:
        return Path(str(configured))
    return PROFILES_PATH


def _load_yaml_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    import yaml

    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        return {}
    cfg = payload.get("config", payload)
    return cfg if isinstance(cfg, dict) else {}


def _resolve_timetable_settings(record: dict[str, Any] | None = None) -> tuple[Path | None, str]:
    template_cfg = _load_yaml_config(CONFIG_TEMPLATE)
    runtime_cfg: dict[str, Any] = {}
    if record:
        runtime_config = record.get("runtime_config")
        if runtime_config:
            runtime_cfg = _load_yaml_config(Path(str(runtime_config)))

    merged = {**template_cfg, **runtime_cfg}
    raw_path = merged.get("timetables_path")
    if raw_path is None or str(raw_path).strip() in {"", "null", "None"}:
        raw_path = template_cfg.get("timetables_path")

    weekday = str(
        merged.get("timetables_weekday")
        or template_cfg.get("timetables_weekday")
        or "monday"
    ).strip().lower() or "monday"

    if raw_path is None or str(raw_path).strip() in {"", "null", "None"}:
        return None, weekday

    path = Path(str(raw_path).strip())
    if not path.is_absolute():
        data_path = merged.get("data_path") or template_cfg.get("data_path")
        base = Path(str(data_path)) if data_path else DATA_DIR
        path = base / path
    return path, weekday


def _resolve_taxi_fleet_settings(record: dict[str, Any] | None = None) -> Path | None:
    template_cfg = _load_yaml_config(CONFIG_TEMPLATE)
    runtime_cfg: dict[str, Any] = {}
    if record:
        runtime_config = record.get("runtime_config")
        if runtime_config:
            runtime_cfg = _load_yaml_config(Path(str(runtime_config)))

    merged = {**template_cfg, **runtime_cfg}
    raw_path = merged.get("taxi_fleet_path")
    if raw_path is None or str(raw_path).strip() in {"", "null", "None"}:
        raw_path = template_cfg.get("taxi_fleet_path")
    if raw_path is None or str(raw_path).strip() in {"", "null", "None"}:
        return None

    path = Path(str(raw_path).strip())
    if not path.is_absolute():
        data_path = merged.get("data_path") or template_cfg.get("data_path")
        base = Path(str(data_path)) if data_path else DATA_DIR
        path = base / path
    return path


def _load_taxi_operator_payload(
    output_path: Path,
    run_id: str,
    taxi_fleet_dir: Path | None,
) -> dict[str, Any] | None:
    fleet_file = taxi_fleet_dir / "Taxi.json" if taxi_fleet_dir is not None else None
    if fleet_file is not None and fleet_file.is_file():
        payload = json.loads(fleet_file.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload

    from synthesis.output_resources.taxi.fleet import load_taxi_stands_csv
    from synthesis.output_resources.taxi.stands import taxi_stand_points_from_dataframe

    csv_path = _resolve_scenario_resource_path(output_path, run_id, "taxi_stands.csv")
    if not csv_path.is_file():
        return None
    stands = load_taxi_stands_csv(csv_path)
    points = taxi_stand_points_from_dataframe(stands)
    if not points:
        return None
    return {
        "operator_id": "Taxi",
        "modes": [
            {
                "id": "Taxi",
                "operator_id": "Taxi",
                "free": False,
                "restricted_to": [],
            }
        ],
        "resources": [],
        "points": points,
        "positions": [],
        "timetables": [],
    }


def _load_operator_timetables(timetables_dir: Path | None, weekday: str, operator_id: str) -> list[Any]:
    path = _operator_timetable_path(timetables_dir, weekday, operator_id)
    if path is None:
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def _operator_timetable_path(
    timetables_dir: Path | None,
    weekday: str,
    operator_id: str,
) -> Path | None:
    if timetables_dir is None:
        return None
    path = timetables_dir / weekday / f"{operator_id}.json"
    return path if path.is_file() else None


def _operator_json_bytes(payload: dict[str, Any], timetable_path: Path | None = None) -> bytes:
    core = {key: value for key, value in payload.items() if key != "timetables"}
    core_json = json.dumps(core, ensure_ascii=False, separators=(",", ":"))
    if not core_json.endswith("}"):
        raise ValueError("unexpected operator JSON encoding")
    prefix = (core_json[:-1] + ',"timetables":').encode("utf-8")
    if timetable_path is not None:
        timetable_bytes = timetable_path.read_bytes().strip() or b"[]"
    else:
        timetable_bytes = json.dumps(
            payload.get("timetables", []),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    return prefix + timetable_bytes + b"}"


def _build_scenario_parts(job_id: str) -> tuple[dict[str, Any], dict[str, Any], str, Path | None, str]:
    record = _require_succeeded_job(job_id)

    run_id = str(record["run_id"])
    output_path = Path(record["output_path"])
    profiles_path = _profiles_path_for_job(record)
    activities_path = output_path / f"{run_id}_activities.csv"
    activities_gpkg_path = output_path / f"{run_id}_activities.gpkg"
    persons_path = output_path / f"{run_id}_persons.csv"
    if not activities_path.exists():
        raise HTTPException(status_code=404, detail="Activities CSV not found for this job")
    if not activities_gpkg_path.exists():
        raise HTTPException(status_code=404, detail="Activities GPKG not found for this job")
    if not persons_path.exists():
        raise HTTPException(status_code=404, detail="Persons CSV not found for this job")

    df_activities = pd.read_csv(activities_path, sep=";")
    gdf_activities = gpd.read_file(activities_gpkg_path)
    df_persons = pd.read_csv(persons_path, sep=";")
    if "latent_class" not in df_persons.columns:
        raise HTTPException(
            status_code=409,
            detail="Persons CSV has no latent_class column; run synthesis with assign_latent_classes enabled",
        )

    person_to_latent_class: dict[str, str] = {}
    person_to_constraints: dict[str, list[dict[str, Any]]] = {}
    all_person_ids: set[str] = set()
    if "person_id" in df_persons.columns:
        person_ids = df_persons["person_id"].astype(str)
        all_person_ids = set(person_ids.tolist())
        if "latent_class" in df_persons.columns:
            latent_mask = df_persons["latent_class"].notna()
            person_to_latent_class = {
                str(pid): str(lc)
                for pid, lc in zip(
                    df_persons.loc[latent_mask, "person_id"].astype(str),
                    df_persons.loc[latent_mask, "latent_class"].astype(str),
                    strict=False,
                )
            }
        if "constraints" in df_persons.columns:
            from synthesis.constraints.loader import parse_person_constraints

            person_to_constraints = {
                str(pid): parse_person_constraints(raw)
                for pid, raw in zip(person_ids, df_persons["constraints"].tolist(), strict=False)
            }

    persons_export_df = df_persons.copy()
    if "constraints" in persons_export_df.columns:
        persons_export_df["constraints"] = [
            person_to_constraints.get(str(pid), [])
            for pid in persons_export_df["person_id"].astype(str)
        ]
    persons_export = persons_export_df.where(pd.notna(persons_export_df), None).to_dict(orient="records")
    requests = _build_requests(
        df_activities,
        gdf_activities,
        person_to_latent_class,
        person_to_constraints=person_to_constraints,
        profiles_path=profiles_path,
    )
    bike_station_availability = bike_station_availability_from_job_record(record)
    timetables_dir, timetables_weekday = _resolve_timetable_settings(record)
    resources = _build_resources(
        output_path,
        run_id,
        bike_station_availability=bike_station_availability,
        timetables_dir=timetables_dir,
        timetables_weekday=timetables_weekday,
        include_timetables=False,
    )
    request_person_ids = {str(request.get("person_id")) for request in requests if request.get("person_id") is not None}
    persons_without_requests = sorted(all_person_ids - request_person_ids) if all_person_ids else []

    demand = {
        "persons": persons_export,
        "requests": requests,
        "persons_without_requests": persons_without_requests,
        "profiles_path": str(profiles_path),
    }
    return demand, resources, run_id, timetables_dir, timetables_weekday


def build_scenario_zip_bytes(job_id: str) -> tuple[bytes, str]:
    demand, resources, run_id, timetables_dir, timetables_weekday = _build_scenario_parts(job_id)
    return pack_scenario_zip_bytes(
        demand,
        resources,
        run_id=run_id,
        timetables_dir=timetables_dir,
        timetables_weekday=timetables_weekday,
    )


def pack_scenario_zip_bytes(
    demand: dict[str, Any],
    resources: dict[str, Any],
    *,
    run_id: str = "scenario",
    timetables_dir: Path | None = None,
    timetables_weekday: str = "monday",
) -> tuple[bytes, str]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        zf.writestr(
            "scenario.json",
            json.dumps(demand, ensure_ascii=False, separators=(",", ":")),
        )
        for operator_id, payload in sorted(resources.items()):
            timetable_path = _operator_timetable_path(timetables_dir, timetables_weekday, operator_id)
            operator_bytes = _operator_json_bytes(payload, timetable_path)
            compress = zipfile.ZIP_STORED if timetable_path is not None else zipfile.ZIP_DEFLATED
            zf.writestr(f"operators/{operator_id}.json", operator_bytes, compress_type=compress)
    return buffer.getvalue(), f"{run_id}_scenario.zip"


def _hash_point(lat: float, lon: float, salt: str) -> str:
    payload = f"{lat:.8f},{lon:.8f},{salt}".encode("utf-8")
    return hashlib.sha1(payload).hexdigest()[:12]


def _to_min_str(value: Any) -> str | None:
    if pd.isna(value):
        return None
    return str(int(round(float(value) / 60.0)))


def _build_requests(
    df_activities: pd.DataFrame,
    gdf_activities: gpd.GeoDataFrame,
    person_to_latent_class: dict[str, str],
    *,
    person_to_constraints: dict[str, list[dict[str, Any]]] | None = None,
    profiles_path: Path,
) -> list[dict[str, Any]]:
    if len(df_activities) == 0:
        return []
    required = {"person_id", "activity_index"}
    if not required.issubset(df_activities.columns):
        return []

    requests: list[dict[str, Any]] = []
    merge_cols = [c for c in ["person_id", "activity_index"] if c in gdf_activities.columns]
    if len(merge_cols) != 2 or "geometry" not in gdf_activities.columns:
        return []

    if gdf_activities.crs is not None and str(gdf_activities.crs).lower() != "epsg:4326":
        gdf_activities = gdf_activities.to_crs("EPSG:4326")

    from synthesis.profiles.loader import load_profiles_config, preferences_for_profile

    profiles_data = load_profiles_config(profiles_path)

    merged = pd.merge(
        df_activities,
        gdf_activities[["person_id", "activity_index", "geometry"]],
        on=["person_id", "activity_index"],
        how="left",
    )
    merged = merged.sort_values(["person_id", "activity_index"], kind="mergesort")
    grouped = merged.groupby("person_id", observed=False, sort=False)
    request_counter = 0
    for person_id_raw, group in grouped:
        if len(group) < 2:
            continue
        if any(c not in group.columns for c in ["geometry", "start_time", "end_time", "activity_index"]):
            continue

        person_id = str(person_id_raw)
        latent_class = person_to_latent_class.get(person_id)
        constraints = (person_to_constraints or {}).get(person_id, [])
        ordered = group.reset_index(drop=True)
        geometries = ordered["geometry"].tolist()
        start_times = ordered["start_time"].tolist() if "start_time" in ordered.columns else [None] * len(ordered)
        end_times = ordered["end_time"].tolist() if "end_time" in ordered.columns else [None] * len(ordered)
        activity_indices = ordered["activity_index"].tolist()

        for leg_idx in range(len(ordered) - 1):
            start_geom = geometries[leg_idx]
            end_geom = geometries[leg_idx + 1]

            if start_geom is None or end_geom is None or pd.isna(start_geom) or pd.isna(end_geom):
                continue

            start_lat = float(start_geom.y)
            start_lon = float(start_geom.x)
            end_lat = float(end_geom.y)
            end_lon = float(end_geom.x)

            request_id = f"Q{request_counter}"
            preference_index = request_counter
            request_counter += 1

            dep_lo = _to_min_str(start_times[leg_idx])
            dep_hi = _to_min_str(end_times[leg_idx])
            arr_lo = _to_min_str(start_times[leg_idx + 1])
            arr_hi = _to_min_str(end_times[leg_idx + 1])
            origin_activity_index = activity_indices[leg_idx]
            destination_activity_index = activity_indices[leg_idx + 1]

            requests.append(
                {
                    "id": request_id,
                    "person_id": person_id,
                    "origin_activity_index": int(origin_activity_index)
                    if not pd.isna(origin_activity_index)
                    else None,
                    "destination_activity_index": int(destination_activity_index)
                    if not pd.isna(destination_activity_index)
                    else None,
                    "start": {
                        "id": _hash_point(start_lat, start_lon, f"{request_id}:start"),
                        "request_id": request_id,
                        "lat": start_lat,
                        "lon": start_lon,
                        "kind": "start",
                    },
                    "end": {
                        "id": _hash_point(end_lat, end_lon, f"{request_id}:end"),
                        "request_id": request_id,
                        "lat": end_lat,
                        "lon": end_lon,
                        "kind": "end",
                    },
                    "time_window_dep": [dep_lo or "0", dep_hi or dep_lo or "0"],
                    "time_window_arr": [arr_lo or dep_hi or dep_lo or "0", arr_hi or arr_lo or dep_hi or dep_lo or "0"],
                    "personal_benefits": [],
                    "preferences": preferences_for_profile(
                        latent_class,
                        profiles_path,
                        request_index=preference_index,
                        profiles_data=profiles_data,
                    ),
                    "constraints": constraints,
                    "latent_class": latent_class,
                }
            )
    return requests


def _resolve_scenario_resource_path(output_path: Path, run_id: str, suffix: str) -> Path:
    job_path = output_path / f"{run_id}_{suffix}"
    if job_path.is_file():
        return job_path
    baseline_path = baseline_artifact_path(suffix)
    if baseline_path.is_file():
        return baseline_path
    return job_path


def _format_scenario_capacity(raw: Any, default: str = "inf") -> str:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return default
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return default
    return str(value) if value >= 0 else default


def _scenario_row_resource_key(
    row: pd.Series,
    key_columns: tuple[str, ...],
    lat: float,
    lon: float,
    prefix: str,
) -> str:
    for column in key_columns:
        if column in row.index:
            value = row.get(column)
            if value is not None and not pd.isna(value) and str(value).strip():
                return str(value).strip()
    return _hash_point(lat, lon, prefix)


def _append_scenario_point_operator(
    resources: dict[str, Any],
    *,
    operator_id: str,
    mode_id: str,
    operator_resources: list[dict[str, Any]],
    operator_points: list[dict[str, Any]],
) -> None:
    if not operator_resources:
        return
    resources[operator_id] = {
        "modes": [
            {
                "id": mode_id,
                "operator_id": operator_id,
                "free": False,
                "restricted_to": [],
            }
        ],
        "resources": operator_resources,
        "points": operator_points,
        "positions": [],
        "timetables": [],
    }


def _load_scenario_point_layer_from_csv(
    csv_path: Path,
    *,
    operator_id: str,
    mode_id: str,
    point_kind: str,
    resource_id_prefix: str,
    key_columns: tuple[str, ...],
    capacity_column: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not csv_path.is_file():
        return [], []

    df = pd.read_csv(csv_path, sep=";")
    if not {"lat", "lon"}.issubset(df.columns):
        return [], []

    resources: list[dict[str, Any]] = []
    points: list[dict[str, Any]] = []
    for _, row in df.dropna(subset=["lat", "lon"]).iterrows():
        lat = float(row["lat"])
        lon = float(row["lon"])
        resource_key = _scenario_row_resource_key(
            row, key_columns, lat, lon, f"{resource_id_prefix}:{operator_id}"
        )
        point_id = _hash_point(lat, lon, f"{point_kind}:{resource_key}")
        resources.append(
            {
                "id": f"{resource_id_prefix}:{resource_key}",
                "mode": mode_id,
                "capacity": _format_scenario_capacity(row.get(capacity_column)) if capacity_column else "inf",
                "operator_id": operator_id,
            }
        )
        points.append(
            {
                "id": point_id,
                "lat": lat,
                "lon": lon,
                "kind": point_kind,
            }
        )
    return resources, points


def _build_resources(
    output_path: Path,
    run_id: str,
    bike_station_availability: dict[str, int] | None = None,
    timetables_dir: Path | None = None,
    timetables_weekday: str = "monday",
    taxi_fleet_dir: Path | None = None,
    include_timetables: bool = True,
) -> dict[str, Any]:
    routes_path = _resolve_scenario_resource_path(output_path, run_id, "gtfs_routes.csv")
    stops_path = _resolve_scenario_resource_path(output_path, run_id, "gtfs_stops.csv")
    bikes_path = _resolve_scenario_resource_path(output_path, run_id, "bikesharing_stations.csv")

    pt_resources_by_operator: dict[str, list[dict[str, Any]]] = {}
    pt_points_by_operator: dict[str, list[dict[str, Any]]] = {}
    bike_resources_by_operator: dict[str, list[dict[str, Any]]] = {}
    bike_points_by_operator: dict[str, list[dict[str, Any]]] = {}

    def normalize_operator_id(raw: Any, fallback: str) -> str:
        text = str(raw).strip() if raw is not None else ""
        if not text:
            text = fallback
        lowered = text.lower()
        if "tisseo" in lowered:
            return "TisseoOperator"
        if "lio" in lowered:
            return "lioOperator"
        if "tango" in lowered:
            return "TangoOperator"
        if "tam" in lowered:
            return "TAMOperator"
        if "sncf" in lowered:
            return "SNCFOperator"

        text = re.sub(r"^\.+", "", text)
        cleaned = "".join(ch if ch.isalnum() else "_" for ch in text).strip("_")
        if not cleaned:
            cleaned = fallback
        cleaned = re.sub(r"_\d+$", "", cleaned)
        return f"{cleaned}Operator"

    def parse_operator_values(raw: Any, fallback: str) -> list[str]:
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            return [fallback]
        if isinstance(raw, list):
            values = [str(v).strip() for v in raw if str(v).strip()]
            return values or [fallback]
        text = str(raw).strip()
        if not text:
            return [fallback]
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except Exception:
                try:
                    parsed = ast.literal_eval(text)
                except Exception:
                    parsed = None
            if isinstance(parsed, list):
                values = [str(v).strip() for v in parsed if str(v).strip()]
                return values or [fallback]
        if "|" in text:
            values = [part.strip() for part in text.split("|") if part.strip()]
            return values or [fallback]
        return [text]

    if routes_path.exists():
        df_routes = pd.read_csv(routes_path, sep=";")
        route_col = "route_id" if "route_id" in df_routes.columns else None
        if route_col is not None:
            operator_col = None
            if "operator" in df_routes.columns:
                operator_col = "operator"
            elif "feed_id" in df_routes.columns:
                operator_col = "feed_id"
            if operator_col is None:
                df_routes = df_routes.copy()
                operator_col = "operator"
                df_routes[operator_col] = "gtfs"
            for _, row in df_routes[[route_col, operator_col]].dropna(subset=[route_col]).drop_duplicates().iterrows():
                route_id = str(row[route_col])
                operator_name = parse_operator_values(row.get(operator_col), "gtfs")[0]
                operator_id = normalize_operator_id(operator_name, "gtfs")
                pt_resources_by_operator.setdefault(operator_id, []).append(
                    {
                        "id": f"line:{route_id}",
                        "mode": "PublicTransport",
                        "capacity": "inf",
                        "operator_id": operator_id,
                    }
                )

    if stops_path.exists():
        df_stops = pd.read_csv(stops_path, sep=";")
        lat_col = "stop_lat" if "stop_lat" in df_stops.columns else None
        lon_col = "stop_lon" if "stop_lon" in df_stops.columns else None
        if lat_col and lon_col:
            operator_col = None
            if "operator" in df_stops.columns:
                operator_col = "operator"
            elif "feed_id" in df_stops.columns:
                operator_col = "feed_id"
            if operator_col is None:
                df_stops = df_stops.copy()
                operator_col = "operator"
                df_stops[operator_col] = "gtfs"
            stops = df_stops[[lat_col, lon_col, operator_col]].dropna(subset=[lat_col, lon_col]).drop_duplicates()
            for lat, lon, operator_raw in zip(
                stops[lat_col].tolist(),
                stops[lon_col].tolist(),
                stops[operator_col].tolist(),
                strict=False,
            ):
                lat_f = float(lat)
                lon_f = float(lon)
                for operator_name in parse_operator_values(operator_raw, "gtfs"):
                    operator_id = normalize_operator_id(operator_name, "gtfs")
                    pt_points_by_operator.setdefault(operator_id, []).append(
                        {
                            "id": _hash_point(lat_f, lon_f, f"stop:{operator_id}"),
                            "lat": lat_f,
                            "lon": lon_f,
                            "kind": "stop",
                        }
                    )

    if bikes_path.exists():
        df_bikes = pd.read_csv(bikes_path, sep=";")
        if {"lat", "lon"}.issubset(df_bikes.columns):
            bike_cols = [
                c
                for c in [
                    "city_station_id",
                    "station_id",
                    "name",
                    "capacity",
                    "available_bikes",
                    "num_bikes_available",
                    "lat",
                    "lon",
                    "operator",
                    "city_id",
                ]
                if c in df_bikes.columns
            ]
            for _, row in df_bikes[bike_cols].dropna(subset=["lat", "lon"]).iterrows():
                operator_raw = row.get("operator")
                if pd.isna(operator_raw) or str(operator_raw).strip() == "":
                    operator_raw = row.get("city_id", "bikesharing")
                operator_id = normalize_operator_id(operator_raw, "bikesharing")
                station_key = str(
                    row.get("city_station_id")
                    or row.get("station_id")
                    or _hash_point(float(row["lat"]), float(row["lon"]), f"bike:{operator_id}")
                )
                available_bikes = _resolve_available_bikes_for_station(
                    row, station_key, bike_station_availability
                )

                bike_resources_by_operator.setdefault(operator_id, []).append(
                    {
                        "id": f"bike_station:{station_key}",
                        "mode": "Bikesharing",
                        "capacity": str(int(row["capacity"])) if not pd.isna(row.get("capacity")) else "inf",
                        "available_bikes": available_bikes,
                        "operator_id": operator_id,
                    }
                )
                bike_points_by_operator.setdefault(operator_id, []).append(
                    {
                        "id": _hash_point(float(row["lat"]), float(row["lon"]), f"bike_point:{station_key}"),
                        "lat": float(row["lat"]),
                        "lon": float(row["lon"]),
                        "kind": "bike_station",
                    }
                )

    resources: dict[str, Any] = {
        "WalkOperator": {
            "modes": [
                {
                    "id": "Walk",
                    "operator_id": "WalkOperator",
                    "free": True,
                    "restricted_to": [],
                }
            ],
            "resources": [
                {
                    "id": "walk_default",
                    "mode": "Walk",
                    "capacity": "inf",
                    "operator_id": "WalkOperator",
                }
            ],
            "points": [],
            "positions": {},
        },
    }

    for operator_id, operator_resources in pt_resources_by_operator.items():
        resources[operator_id] = {
            "modes": [
                {
                    "id": "PublicTransport",
                    "operator_id": operator_id,
                    "free": False,
                    "restricted_to": [],
                }
            ],
            "resources": operator_resources,
            "points": pt_points_by_operator.get(operator_id, []),
            "positions": [],
            "timetables": (
                _load_operator_timetables(timetables_dir, timetables_weekday, operator_id)
                if include_timetables
                else []
            ),
        }

    for operator_id, operator_resources in bike_resources_by_operator.items():
        resources[operator_id] = {
            "modes": [
                {
                    "id": "Bikesharing",
                    "operator_id": operator_id,
                    "free": False,
                    "restricted_to": [],
                }
            ],
            "resources": operator_resources,
            "points": bike_points_by_operator.get(operator_id, []),
            "positions": [],
            "timetables": [],
        }

    extra_layers = (
        ("carsharing_stations.csv", "Carsharing", "Carsharing", "carsharing_station", "car_station", ("station_id",), "capacity"),
        ("carpooling_stops.csv", "Carpooling", "Carpooling", "carpooling_stop", "carpool_stop", ("id_local",), "nbre_pl"),
        ("pmr_stands.csv", "PMR", "PMR", "pmr_stand", "pmr_stand", ("name", "source_file"), "nb_places"),
        ("public_parking.csv", "Parking", "Parking", "parking", "parking", ("parking_id",), "total_spaces"),
        ("park_and_ride.csv", "ParkAndRide", "ParkAndRide", "park_and_ride", "park_and_ride", ("parking_id",), "park_and_ride_spaces"),
    )
    for suffix, operator_id, mode_id, point_kind, resource_prefix, key_columns, capacity_column in extra_layers:
        csv_path = _resolve_scenario_resource_path(output_path, run_id, suffix)
        layer_resources, layer_points = _load_scenario_point_layer_from_csv(
            csv_path,
            operator_id=operator_id,
            mode_id=mode_id,
            point_kind=point_kind,
            resource_id_prefix=resource_prefix,
            key_columns=key_columns,
            capacity_column=capacity_column,
        )
        _append_scenario_point_operator(
            resources,
            operator_id=operator_id,
            mode_id=mode_id,
            operator_resources=layer_resources,
            operator_points=layer_points,
        )

    taxi_payload = _load_taxi_operator_payload(output_path, run_id, taxi_fleet_dir)
    if taxi_payload is not None:
        resources["Taxi"] = taxi_payload

    return resources
