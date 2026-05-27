from __future__ import annotations

import glob
import os

import pandas as pd

from synthesis.output.io import write_points_layer
from synthesis.output_resources import (
    _load_carpooling_stops,
    _load_carsharing_stations,
    _load_gtfs_resources,
    _load_park_and_ride,
    _load_pmr_stands,
    _load_bikesharing_stations,
    _load_public_parking,
    _load_taxi_stands,
)


def _split_public_parking_only(df):
    if len(df) == 0:
        return df

    source = df.get("source_file", "").astype(str).str.lower() if "source_file" in df.columns else ""
    name = df.get("name", "").astype(str).str.lower() if "name" in df.columns else ""
    function_type = df.get("function_type", "").astype(str).str.lower() if "function_type" in df.columns else ""
    park_type = df.get("parking_type", "").astype(str).str.lower() if "parking_type" in df.columns else ""
    pnr_spaces = (
        pd.to_numeric(df.get("park_and_ride_spaces", 0), errors="coerce").fillna(0)
        if "park_and_ride_spaces" in df.columns
        else 0
    )

    is_park_and_ride = (
        source.str.contains("p+r|parkings-relais|parkings_relais|parcs-relais", regex=True)
        | name.str.contains("parc relais|park\\s*and\\s*ride|p\\+r", regex=True)
        | function_type.str.contains("relais", regex=False)
        | park_type.str.contains("relais", regex=False)
        | (pnr_spaces > 0)
    )

    return df[~is_park_and_ride].copy()


def export_static_resources(
    context,
    output_path: str,
    output_prefix: str,
    output_formats: list[str],
    bikesharing_path: str,
    gbfs_path: str,
    gtfs_path: str,
    carsharing_path: str,
    carpooling_path: str,
    taxi_data_paths: list[str],
    pmr_data_paths: list[str],
    parking_data_paths: list[str],
    pnr_data_paths: list[str],
) -> None:
    df_bikesharing_stations = _load_bikesharing_stations(
        context.config("data_path"),
        bikesharing_path,
        gbfs_path,
    )
    if len(df_bikesharing_stations) > 0:
        write_points_layer(
            df_bikesharing_stations,
            "lon",
            "lat",
            output_path,
            output_prefix,
            "bikesharing_stations",
            output_formats,
        )

    clipped_gtfs_path = os.path.join(context.path("data.gtfs.cleaned"), context.stage("data.gtfs.cleaned"))
    gtfs_zip_paths = [clipped_gtfs_path] if os.path.exists(clipped_gtfs_path) else []
    if not gtfs_zip_paths and gtfs_path:
        gtfs_zip_paths = sorted(glob.glob(os.path.join(context.config("data_path"), gtfs_path, "*.zip")))
    df_gtfs_stops, df_gtfs_routes = _load_gtfs_resources(gtfs_zip_paths)
    if len(df_gtfs_stops) > 0:
        write_points_layer(df_gtfs_stops, "stop_lon", "stop_lat", output_path, output_prefix, "gtfs_stops", output_formats)
    if len(df_gtfs_routes) > 0 and "csv" in output_formats:
        df_gtfs_routes.to_csv(
            f"{output_path}/{output_prefix}gtfs_routes.csv",
            sep=";",
            index=None,
            lineterminator="\n",
        )

    df_parking = _load_public_parking(context.config("data_path"), parking_data_paths)
    df_public_parking = _split_public_parking_only(df_parking)
    df_park_and_ride = _load_park_and_ride(context.config("data_path"), pnr_data_paths)

    resources = [
        (_load_carsharing_stations(context.config("data_path"), carsharing_path), "carsharing_stations", "lon", "lat"),
        (_load_carpooling_stops(context.config("data_path"), carpooling_path), "carpooling_stops", "lon", "lat"),
        (_load_taxi_stands(context.config("data_path"), taxi_data_paths), "taxi_stands", "lon", "lat"),
        (_load_pmr_stands(context.config("data_path"), pmr_data_paths), "pmr_stands", "lon", "lat"),
        (df_public_parking, "public_parking", "lon", "lat"),
        (df_park_and_ride, "park_and_ride", "lon", "lat"),
    ]
    for df_resource, name, lon_col, lat_col in resources:
        if len(df_resource) > 0:
            write_points_layer(df_resource, lon_col, lat_col, output_path, output_prefix, name, output_formats)
