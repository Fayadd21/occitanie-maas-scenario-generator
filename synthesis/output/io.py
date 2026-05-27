from __future__ import annotations

import geopandas as gpd
import pandas as pd

from synthesis.output_resources import clean_gpkg


def write_table(df: pd.DataFrame, output_path: str, output_prefix: str, name: str, output_formats: list[str]) -> None:
    if "csv" in output_formats:
        df.to_csv(f"{output_path}/{output_prefix}{name}.csv", sep=";", index=None, lineterminator="\n")
    if "parquet" in output_formats:
        df.to_parquet(f"{output_path}/{output_prefix}{name}.parquet")


def write_geodataframe(gdf: gpd.GeoDataFrame, output_path: str, output_prefix: str, name: str, output_formats: list[str]) -> None:
    if "gpkg" in output_formats:
        gpkg_path = f"{output_path}/{output_prefix}{name}.gpkg"
        gdf.to_file(gpkg_path, driver="GPKG", mode="w")
        clean_gpkg(gpkg_path)
    if "geoparquet" in output_formats:
        gdf.to_parquet(f"{output_path}/{output_prefix}{name}.geoparquet")


def write_points_layer(
    df: pd.DataFrame,
    lon_column: str,
    lat_column: str,
    output_path: str,
    output_prefix: str,
    name: str,
    output_formats: list[str],
) -> None:
    if "csv" in output_formats:
        df.to_csv(f"{output_path}/{output_prefix}{name}.csv", sep=";", index=None, lineterminator="\n")
    if "gpkg" in output_formats and {lon_column, lat_column}.issubset(df.columns):
        gdf = gpd.GeoDataFrame(
            df.copy(),
            geometry=gpd.points_from_xy(df[lon_column], df[lat_column]),
            crs="EPSG:4326",
        )
        write_geodataframe(gdf, output_path, output_prefix, name, output_formats)
