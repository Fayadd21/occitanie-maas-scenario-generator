"""Reuse baseline spatial layers when counts and polygon are unchanged."""

from __future__ import annotations

import os
import shutil

import pandas as pd

SPATIAL_LAYERS = ("activities", "homes", "commutes")


def spatial_subset_unchanged(
    *,
    baseline_mode: bool,
    population_filter_geojson: str | None,
    initial_person_count: int | None,
    initial_activity_count: int | None,
    df_persons: pd.DataFrame,
    df_activities: pd.DataFrame,
) -> bool:
    if not baseline_mode:
        return False
    if population_filter_geojson:
        return False
    if initial_person_count is None or initial_activity_count is None:
        return False
    return len(df_persons) == initial_person_count and len(df_activities) == initial_activity_count


def needs_geometry_for_profiles(
    df_persons: pd.DataFrame,
    assign_latent_classes_enabled: bool,
    profiles_path: str | None,
) -> bool:
    if not assign_latent_classes_enabled or not profiles_path:
        return False
    from synthesis.profiles.loader import persons_have_home_destination_distance, profiles_reference_field

    if persons_have_home_destination_distance(df_persons):
        return False
    return profiles_reference_field(profiles_path, "home_destination_distance_km")


def copy_baseline_spatial_layers(
    baseline_run_path: str,
    baseline_run_id: str,
    output_path: str,
    output_prefix: str,
    output_formats: list[str],
    layers: tuple[str, ...] = SPATIAL_LAYERS,
) -> None:
    if "gpkg" not in output_formats:
        return
    for layer in layers:
        source = os.path.join(baseline_run_path, f"{baseline_run_id}_{layer}.gpkg")
        target = os.path.join(output_path, f"{output_prefix}{layer}.gpkg")
        if os.path.isfile(source):
            shutil.copy2(source, target)


def load_geometry_for_home_distance(activities_gpkg_path: str, person_ids: set | None) -> pd.DataFrame:
    import geopandas as gpd
    import pyogrio

    where = "purpose IN ('home', 'work', 'education')"
    if person_ids is not None and 0 < len(person_ids) <= 5000:
        quoted = ",".join(f"'{pid}'" for pid in person_ids)
        where = f"{where} AND person_id IN ({quoted})"

    gdf = pyogrio.read_dataframe(
        activities_gpkg_path,
        columns=["person_id", "activity_index", "purpose", "geometry"],
        where=where,
    )
    if not isinstance(gdf, gpd.GeoDataFrame):
        gdf = gpd.GeoDataFrame(gdf, geometry="geometry")
    if gdf.crs is None:
        from synthesis.profiles.loader import _looks_like_projected_meters

        sample = gdf[gdf["geometry"].notna()]
        if len(sample) > 0:
            x = float(sample.geometry.iloc[0].x)
            y = float(sample.geometry.iloc[0].y)
            if _looks_like_projected_meters(x, y):
                gdf = gdf.set_crs("EPSG:2154", allow_override=True)
            else:
                gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    crs_text = str(gdf.crs).upper() if gdf.crs is not None else ""
    if crs_text not in {"", "EPSG:4326", "OGC:CRS84"}:
        gdf = gdf.to_crs("EPSG:4326")
    keep_cols = [
        column
        for column in ["person_id", "activity_index", "purpose", "geometry"]
        if column in gdf.columns
    ]
    return pd.DataFrame(gdf[keep_cols].copy())
