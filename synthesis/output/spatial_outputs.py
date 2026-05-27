from __future__ import annotations

import geopandas as gpd
import pandas as pd
import shapely.geometry as geo

from synthesis.output.io import write_geodataframe


def write_activity_geometries(df_activities: pd.DataFrame, df_locations, output_path: str, output_prefix: str, output_formats: list[str]) -> gpd.GeoDataFrame:
    df_spatial = gpd.GeoDataFrame(
        df_activities[
            [
                "person_id",
                "household_id",
                "activity_index",
                "iris_id",
                "commune_id",
                "departement_id",
                "region_id",
                "preceding_trip_index",
                "following_trip_index",
                "purpose",
                "start_time",
                "end_time",
                "is_first",
                "is_last",
                "geometry",
            ]
        ],
        crs=df_locations.crs,
    )
    df_spatial = df_spatial.astype({"purpose": "str", "departement_id": "str"})
    write_geodataframe(df_spatial, output_path, output_prefix, "activities", output_formats)
    return df_spatial


def write_homes(df_spatial: gpd.GeoDataFrame, output_path: str, output_prefix: str, output_formats: list[str]) -> None:
    df_spatial_homes = df_spatial[df_spatial["purpose"] == "home"].drop_duplicates("household_id")[
        ["household_id", "iris_id", "commune_id", "departement_id", "region_id", "geometry"]
    ]
    write_geodataframe(df_spatial_homes, output_path, output_prefix, "homes", output_formats)


def write_commutes(df_spatial: gpd.GeoDataFrame, df_locations, output_path: str, output_prefix: str, output_formats: list[str]) -> None:
    df_commutes = pd.merge(
        df_spatial[df_spatial["purpose"] == "home"].drop_duplicates("person_id")[["person_id", "geometry"]].rename(
            columns={"geometry": "home_geometry"}
        ),
        df_spatial[df_spatial["purpose"] == "work"].drop_duplicates("person_id")[["person_id", "geometry"]].rename(
            columns={"geometry": "work_geometry"}
        ),
    )
    df_commutes["geometry"] = gpd.GeoSeries(
        [geo.LineString(od) for od in zip(df_commutes["home_geometry"], df_commutes["work_geometry"])],
        crs=df_locations.crs,
    )
    df_commutes = gpd.GeoDataFrame(df_commutes.drop(columns=["home_geometry", "work_geometry"]), crs=df_locations.crs)
    write_geodataframe(df_commutes, output_path, output_prefix, "commutes", output_formats)


def write_trip_geometries(
    df_trips: pd.DataFrame,
    df_locations,
    output_path: str,
    output_prefix: str,
    output_formats: list[str],
) -> None:
    df_trip_spatial = pd.merge(
        df_trips,
        df_locations[["person_id", "activity_index", "geometry"]].rename(
            columns={"activity_index": "preceding_activity_index", "geometry": "preceding_geometry"}
        ),
        how="left",
        on=["person_id", "preceding_activity_index"],
    )
    df_trip_spatial = pd.merge(
        df_trip_spatial,
        df_locations[["person_id", "activity_index", "geometry"]].rename(
            columns={"activity_index": "following_activity_index", "geometry": "following_geometry"}
        ),
        how="left",
        on=["person_id", "following_activity_index"],
    )
    df_trip_spatial["geometry"] = [
        geo.LineString(od) for od in zip(df_trip_spatial["preceding_geometry"], df_trip_spatial["following_geometry"])
    ]
    df_trip_spatial = gpd.GeoDataFrame(
        df_trip_spatial.drop(columns=["preceding_geometry", "following_geometry"]),
        crs=df_locations.crs,
    )
    df_trip_spatial["following_purpose"] = df_trip_spatial["following_purpose"].astype(str)
    df_trip_spatial["preceding_purpose"] = df_trip_spatial["preceding_purpose"].astype(str)
    if "mode" in df_trip_spatial:
        df_trip_spatial["mode"] = df_trip_spatial["mode"].astype(str)
    write_geodataframe(df_trip_spatial, output_path, output_prefix, "trips", output_formats)
