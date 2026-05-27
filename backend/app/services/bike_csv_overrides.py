from __future__ import annotations

from typing import Any

import pandas as pd


def cap_availability_to_capacity(available: int, capacity: Any) -> int:
    bikes = max(0, int(available))
    if capacity is None or (isinstance(capacity, float) and pd.isna(capacity)):
        return bikes
    try:
        cap = int(round(float(capacity)))
    except (TypeError, ValueError):
        return bikes
    if cap < 0:
        return bikes
    return min(bikes, cap)


def normalize_bikesharing_station_availability(raw: Any) -> dict[str, int] | None:
    if not isinstance(raw, dict) or not raw:
        return None
    out: dict[str, int] = {}
    for key, value in raw.items():
        text = str(key).strip()
        if text.startswith("bike_station:"):
            text = text[len("bike_station:") :].strip()
        if not text:
            continue
        try:
            out[text] = int(value)
        except (TypeError, ValueError):
            continue
    return out or None


def bike_station_availability_from_job_record(record: dict[str, Any]) -> dict[str, int] | None:
    direct = record.get("bikesharing_station_availability")
    if isinstance(direct, dict) and direct:
        return normalize_bikesharing_station_availability(direct)
    return None


def apply_bikesharing_station_availability_to_dataframe(
    df: pd.DataFrame, availability: dict[str, int] | None
) -> pd.DataFrame:
    if not availability or len(df) == 0:
        return df
    out = df.copy()
    if "available_bikes" not in out.columns:
        out["available_bikes"] = 0
    if "city_station_id" not in out.columns:
        return out

    for idx, row in out.iterrows():
        raw_key = row.get("city_station_id")
        if raw_key is None or (isinstance(raw_key, float) and pd.isna(raw_key)):
            continue
        key = str(raw_key).strip()
        if not key:
            continue
        if key in availability:
            bikes = max(0, int(availability[key]))
            cap = row.get("capacity") if "capacity" in out.columns else None
            out.at[idx, "available_bikes"] = cap_availability_to_capacity(bikes, cap)
    return out
