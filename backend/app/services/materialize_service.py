from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from backend.app.services.bike_csv_overrides import (
    apply_bikesharing_station_availability_to_dataframe,
    bike_station_availability_from_job_record,
)
from backend.app.services.constants import (
    BASELINE_STATIC_RESOURCE_SUFFIXES,
    baseline_artifact_path,
)


def list_outputs(output_path: Path) -> list[str]:
    if not output_path.exists():
        return []
    return sorted([p.name for p in output_path.glob("*") if p.is_file()])


def _copy_baseline_static_resources(destination_output_path: Path, run_id: str) -> None:
    for suffix in BASELINE_STATIC_RESOURCE_SUFFIXES:
        source = baseline_artifact_path(suffix)
        if not source.is_file():
            continue
        target = destination_output_path / f"{run_id}_{suffix}"
        shutil.copy2(source, target)


def materialize_run_outputs(record: dict) -> None:
    source_output_path = Path(record["source_output_path"])
    source_prefix = str(record["source_output_prefix"])
    run_id = str(record["run_id"])
    destination_output_path = Path(record["output_path"])
    destination_output_path.mkdir(parents=True, exist_ok=True)

    if source_output_path.resolve() != destination_output_path.resolve():
        for source_file in source_output_path.glob(f"{source_prefix}*"):
            if not source_file.is_file():
                continue
            suffix = source_file.name[len(source_prefix) :]
            target_file = destination_output_path / f"{run_id}_{suffix}"
            shutil.copy2(source_file, target_file)

    _copy_baseline_static_resources(destination_output_path, run_id)

    stops_path = destination_output_path / f"{run_id}_gtfs_stops.csv"
    routes_path = destination_output_path / f"{run_id}_gtfs_routes.csv"
    if stops_path.exists():
        try:
            df_stops = pd.read_csv(stops_path, sep=";")
            if "operator" not in df_stops.columns:
                operator_by_feed: dict[str, str] = {}
                if routes_path.exists():
                    df_routes = pd.read_csv(routes_path, sep=";")
                    if {"feed_id", "operator"}.issubset(df_routes.columns):
                        routes_map = df_routes[["feed_id", "operator"]].dropna()
                        if not routes_map.empty:
                            operator_by_feed = (
                                routes_map.drop_duplicates("feed_id")
                                .set_index("feed_id")["operator"]
                                .astype(str)
                                .to_dict()
                            )
                if "feed_id" in df_stops.columns:
                    df_stops["operator"] = (
                        df_stops["feed_id"].astype(str).map(operator_by_feed).fillna(df_stops["feed_id"].astype(str))
                    )
                else:
                    df_stops["operator"] = ""
                df_stops.to_csv(stops_path, sep=";", index=False, lineterminator="\n")
        except Exception:
            pass

    _refresh_bikesharing_stations_csv(destination_output_path, run_id, record)


def _refresh_bikesharing_stations_csv(destination_output_path: Path, run_id: str, record: dict[str, Any]) -> None:
    stations_path = destination_output_path / f"{run_id}_bikesharing_stations.csv"
    if not stations_path.exists():
        return

    availability = bike_station_availability_from_job_record(record)
    if not availability:
        return

    try:
        df = pd.read_csv(stations_path, sep=";")
    except Exception:
        return
    if len(df) == 0:
        return

    df = apply_bikesharing_station_availability_to_dataframe(df, availability)
    df.to_csv(stations_path, sep=";", index=False, lineterminator="\n")
