from __future__ import annotations

import json
import os
import threading
import time
import uuid
import hashlib
import ast
import re
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from fastapi import HTTPException

from backend.app.models.job_models import JobCreateRequest, JobResponse, JobRuntime
from backend.app.services.baseline_service import (
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
    baseline_artifact_path,
    DEFAULT_BASELINE_RUN_ID,
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


def create_baseline_rebuild_job() -> JobResponse:
    defaults = load_defaults()
    target_population = int(defaults.get("target_population", 59_510))
    cleared_cache_dir = clear_synpp_cache()
    job_id = uuid.uuid4().hex
    run_id = f"baseline_build_{uuid.uuid4().hex[:8]}"
    runtime_config_path, source_output_path, source_output_prefix, effective_config = build_baseline_runtime_config(
        run_id=run_id,
        target_population=target_population,
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
            "baseline_run_id": DEFAULT_BASELINE_RUN_ID,
            "baseline_promoted": False,
            "outputs_materialized": False,
            "effective_config": effective_config,
            "target_population": target_population,
            "synpp_cache_cleared": str(cleared_cache_dir),
        },
    )

    return JobResponse(
        job_id=job_id,
        run_id=run_id,
        status="running",
        message="Baseline rebuild started (synpp cache cleared; full pipeline recompute)",
    )


def get_profiles_config() -> dict[str, Any]:
    return get_profiles_payload()


def get_job(job_id: str) -> dict[str, Any]:
    return refresh_status(job_id)


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


def get_job_scenario_export(job_id: str) -> dict[str, Any]:
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
    all_person_ids: set[str] = set()
    if "person_id" in df_persons.columns:
        all_person_ids = set(df_persons["person_id"].astype(str).tolist())
        latent_df = df_persons[["person_id", "latent_class"]].dropna()
        person_to_latent_class = {
            str(row["person_id"]): str(row["latent_class"]) for _, row in latent_df.iterrows()
        }

    persons_export = df_persons.where(pd.notna(df_persons), None).to_dict(orient="records")
    requests = _build_requests(
        df_activities,
        gdf_activities,
        person_to_latent_class,
        profiles_path=profiles_path,
    )
    bike_station_availability = bike_station_availability_from_job_record(record)
    resources = _build_resources(output_path, run_id, bike_station_availability=bike_station_availability)
    request_person_ids = {str(request.get("person_id")) for request in requests if request.get("person_id") is not None}
    persons_without_requests = sorted(all_person_ids - request_person_ids) if all_person_ids else []

    return {
        "persons": persons_export,
        "requests": requests,
        "resources": resources,
        "persons_without_requests": persons_without_requests,
        "profiles_path": str(profiles_path),
    }


def _hash_point(lat: float, lon: float, salt: str) -> str:
    payload = f"{lat:.8f},{lon:.8f},{salt}".encode("utf-8")
    return hashlib.sha1(payload).hexdigest()[:12]


def _to_min_str(value: Any) -> str | None:
    if pd.isna(value):
        return None
    return str(int(round(float(value) / 60.0)))


def _preferences_for_latent_class(
    index: int,
    latent_class: str | None,
    profiles_path: Path,
) -> list[dict[str, Any]]:
    from synthesis.profiles.loader import preferences_for_profile

    return preferences_for_profile(
        latent_class,
        profiles_path,
        request_index=index,
    )


def _build_requests(
    df_activities: pd.DataFrame,
    gdf_activities: gpd.GeoDataFrame,
    person_to_latent_class: dict[str, str],
    *,
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

    merged = pd.merge(
        df_activities,
        gdf_activities[["person_id", "activity_index", "geometry"]],
        on=["person_id", "activity_index"],
        how="left",
    )
    grouped = merged.sort_values(["person_id", "activity_index"]).groupby("person_id", observed=False)
    request_counter = 0
    for _, group in grouped:
        if len(group) < 2:
            continue
        if any(c not in group.columns for c in ["geometry", "start_time", "end_time", "activity_index"]):
            continue

        person_id = str(group.iloc[0]["person_id"])
        latent_class = person_to_latent_class.get(person_id)
        ordered = group.sort_values("activity_index").reset_index(drop=True)

        for leg_idx in range(len(ordered) - 1):
            origin = ordered.iloc[leg_idx]
            destination = ordered.iloc[leg_idx + 1]

            if pd.isna(origin["geometry"]) or pd.isna(destination["geometry"]):
                continue

            start_geom = origin["geometry"]
            end_geom = destination["geometry"]
            start_lat = float(start_geom.y)
            start_lon = float(start_geom.x)
            end_lat = float(end_geom.y)
            end_lon = float(end_geom.x)

            request_id = f"Q{request_counter}"
            preference_index = request_counter
            request_counter += 1

            dep_lo = _to_min_str(origin.get("start_time", None))
            dep_hi = _to_min_str(origin.get("end_time", None))
            arr_lo = _to_min_str(destination.get("start_time", None))
            arr_hi = _to_min_str(destination.get("end_time", None))

            requests.append(
                {
                    "id": request_id,
                    "person_id": person_id,
                    "origin_activity_index": int(origin["activity_index"]) if not pd.isna(origin["activity_index"]) else None,
                    "destination_activity_index": int(destination["activity_index"])
                    if not pd.isna(destination["activity_index"])
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
                    "preferences": _preferences_for_latent_class(
                        preference_index,
                        latent_class,
                        profiles_path,
                    ),
                    "constraints": [],
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


def _build_resources(
    output_path: Path,
    run_id: str,
    bike_station_availability: dict[str, int] | None = None,
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
            for _, row in df_stops[[lat_col, lon_col, operator_col]].dropna(subset=[lat_col, lon_col]).drop_duplicates().iterrows():
                lat = float(row[lat_col])
                lon = float(row[lon_col])
                for operator_name in parse_operator_values(row.get(operator_col), "gtfs"):
                    operator_id = normalize_operator_id(operator_name, "gtfs")
                    pt_points_by_operator.setdefault(operator_id, []).append(
                        {
                            "id": _hash_point(lat, lon, f"stop:{operator_id}"),
                            "lat": lat,
                            "lon": lon,
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
            "timetables": [],
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

    return resources
