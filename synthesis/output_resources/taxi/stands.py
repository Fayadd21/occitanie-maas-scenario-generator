from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd

_EARTH_RADIUS_KM = 6371.0


def classify_zone_type(name: str | None, commune: str | None = None) -> str:
    text = " ".join(part for part in (name, commune) if part).upper()
    if any(token in text for token in ("MATABIAU", "GARE SNCF", "GARE ", "SNCF")):
        return "railway_station"
    if any(token in text for token in ("AERO", "AIRPORT", "BLagnac".upper(), "AEROPORT")):
        return "airport"
    if any(token in text for token in ("CAPITOLE", "WILSON", "CARMES", "JEAN JAURES", "JEAN-JAURES")):
        return "city_center"
    if any(token in text for token in ("BASSO CAMBO", "COMPANS", "CAFFARELLI", "METRO ")):
        return "multimodal_hub"
    return "residential_area"


def zone_weight(
    zone_type: str,
    zone_attractiveness: dict[str, float] | None = None,
) -> float:
    if zone_attractiveness:
        return float(
            zone_attractiveness.get(
                zone_type,
                zone_attractiveness.get("residential_area", 1.0),
            )
        )
    return 1.0


def _stand_slug(name: str, lat: float, lon: float) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", str(name or "").strip()).strip("_").lower()
    if not cleaned:
        cleaned = f"{lat:.5f}_{lon:.5f}".replace(".", "_")
    return cleaned[:80]


def stand_id_from_row(name: str, lat: float, lon: float) -> str:
    return f"taxi_stand:{_stand_slug(name, lat, lon)}"


def finalize_taxi_stands_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) == 0:
        return df.copy()

    frame = df.copy()
    frame["lat"] = pd.to_numeric(frame["lat"], errors="coerce")
    frame["lon"] = pd.to_numeric(frame["lon"], errors="coerce")
    frame = frame.dropna(subset=["lat", "lon"])
    if len(frame) == 0:
        return frame

    frame["name"] = frame["name"].fillna("").astype(str).str.strip()
    frame["commune"] = frame.get("commune", pd.Series("", index=frame.index)).fillna("").astype(str).str.strip()
    frame["nb_places"] = pd.to_numeric(frame.get("nb_places"), errors="coerce").fillna(1).astype(int).clip(lower=1)
    frame["source_file"] = frame.get("source_file", pd.Series("", index=frame.index)).fillna("").astype(str)
    if "city" in frame.columns:
        frame["city"] = frame["city"].fillna("").astype(str).str.strip().str.lower()
    frame["zone_type"] = [
        classify_zone_type(name, commune)
        for name, commune in zip(frame["name"], frame["commune"], strict=False)
    ]
    frame["lat_key"] = frame["lat"].round(4)
    frame["lon_key"] = frame["lon"].round(4)

    grouped_rows: list[dict[str, Any]] = []
    group_cols = ["lat_key", "lon_key"]
    for (_lat_key, _lon_key), group in frame.groupby(group_cols, observed=False):
        best = group.sort_values(
            by=["nb_places", "name"],
            ascending=[False, True],
            kind="mergesort",
        ).iloc[0]
        zone_type = str(group.loc[group["zone_type"].map(zone_weight).idxmax(), "zone_type"])
        name = str(best["name"] or group["name"].iloc[0] or "stand")
        lat = float(best["lat"])
        lon = float(best["lon"])
        row = {
            "stand_id": stand_id_from_row(name, lat, lon),
            "name": name,
            "commune": str(best["commune"] or group["commune"].iloc[0] or ""),
            "nb_places": int(group["nb_places"].sum()),
            "lat": lat,
            "lon": lon,
            "source_file": str(best["source_file"] or group["source_file"].iloc[0] or ""),
            "zone_type": zone_type,
        }
        if "city" in group.columns:
            city = str(best["city"] or group["city"].iloc[0] or "").strip().lower()
            if city:
                row["city"] = city
        grouped_rows.append(row)

    out = pd.DataFrame(grouped_rows)
    return out.sort_values(["name", "lat"], kind="mergesort").reset_index(drop=True)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    chord = math.sin(dlat / 2.0) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2.0) ** 2
    return _EARTH_RADIUS_KM * 2.0 * math.asin(min(1.0, math.sqrt(chord)))


def trip_duration_minutes(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    *,
    average_speed_kmh: float,
    circuity_factor: float,
) -> int:
    distance_km = haversine_km(lat1, lon1, lat2, lon2) * circuity_factor
    if average_speed_kmh <= 0:
        return 1
    return max(1, int(round(distance_km / average_speed_kmh * 60.0)))


def taxi_stand_points_from_dataframe(df: pd.DataFrame) -> list[dict[str, Any]]:
    if len(df) == 0:
        return []
    points: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        stand_id = str(row.get("stand_id") or stand_id_from_row(str(row["name"]), float(row["lat"]), float(row["lon"])))
        points.append(
            {
                "id": stand_id,
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "kind": "taxi_stand",
                "name": str(row["name"]),
                "parking_capacity": int(row.get("nb_places", 1)),
                "zone_type": str(row.get("zone_type", "residential_area")),
            }
        )
    return points
