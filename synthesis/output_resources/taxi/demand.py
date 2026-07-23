from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from synthesis.output_resources.taxi.stands import zone_weight


@dataclass
class TaxiDemandConfig:
    cities: dict[str, dict[str, Any]]
    demand_zones: dict[str, list[dict[str, Any]]]
    stand_probability: float = 0.0
    zone_attractiveness: dict[str, float] | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> TaxiDemandConfig:
        booking = payload.get("booking_endpoint") or {}
        attractiveness = {
            str(k): float(v) for k, v in (payload.get("zone_attractiveness") or {}).items()
        }
        return cls(
            cities={str(k).lower(): dict(v) for k, v in (payload.get("cities") or {}).items()},
            demand_zones={
                str(k).lower(): list(v)
                for k, v in (payload.get("demand_zones") or {}).items()
            },
            stand_probability=float(booking["stand_probability"])
            if "stand_probability" in booking
            else 0.0,
            zone_attractiveness=attractiveness or None,
        )


def load_taxi_demand_config(path: Path | None = None) -> TaxiDemandConfig:
    if path is None or not path.is_file():
        return TaxiDemandConfig(cities={}, demand_zones={})
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return TaxiDemandConfig.from_mapping(payload if isinstance(payload, dict) else {})


def _zone_weight(zone_type: str, zone_attractiveness: dict[str, float] | None) -> float:
    return zone_weight(zone_type, zone_attractiveness)


def demand_zones_dataframe(
    demand_config: TaxiDemandConfig,
    *,
    cities: list[str] | tuple[str, ...] | None = None,
) -> pd.DataFrame:
    city_keys = [str(c).lower() for c in (cities or demand_config.demand_zones.keys())]
    rows: list[dict[str, Any]] = []
    for city in city_keys:
        for zone in demand_config.demand_zones.get(city, []):
            rows.append(
                {
                    "city": city,
                    "zone_id": str(zone["id"]),
                    "name": str(zone["name"]),
                    "lat": float(zone["lat"]),
                    "lon": float(zone["lon"]),
                    "zone_type": str(zone.get("zone_type", "residential_area")),
                    "weight": float(zone.get("weight", 1.0)),
                    "waiting_stand": bool(zone.get("waiting_stand", False)),
                }
            )
    return pd.DataFrame(
        rows,
        columns=["city", "zone_id", "name", "lat", "lon", "zone_type", "weight", "waiting_stand"],
    )



def _build_endpoint_pool(
    city: str,
    stands: pd.DataFrame,
    demand_zones: pd.DataFrame,
    *,
    zone_attractiveness: dict[str, float] | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    city_key = city.lower()
    if len(stands) and "city" in stands.columns:
        city_stands = stands[stands["city"].astype(str).str.lower() == city_key]
    else:
        city_stands = stands.iloc[0:0]
    city_zones = demand_zones[demand_zones["city"].astype(str).str.lower() == city_key]

    lats: list[float] = []
    lons: list[float] = []
    stand_flags: list[bool] = []
    weights: list[float] = []

    for _, row in city_stands.iterrows():
        zone_type = str(row["zone_type"])
        attractiveness = _zone_weight(zone_type, zone_attractiveness)
        lats.append(float(row["lat"]))
        lons.append(float(row["lon"]))
        stand_flags.append(True)
        weights.append(max(1.0, float(row.get("nb_places", 1))) * attractiveness)

    for _, row in city_zones.iterrows():
        zone_type = str(row["zone_type"])
        attractiveness = _zone_weight(zone_type, zone_attractiveness)
        lats.append(float(row["lat"]))
        lons.append(float(row["lon"]))
        stand_flags.append(False)
        weights.append(float(row.get("weight", 1.0)) * attractiveness)

    if not lats:
        raise ValueError(f"No booking locations configured for city: {city}")

    arr = np.array(weights, dtype=float)
    total = arr.sum()
    if total <= 0:
        arr = np.ones(len(arr), dtype=float) / len(arr)
    else:
        arr = arr / total
    return np.array(lats), np.array(lons), np.array(stand_flags), arr


def _city_demand_zones(demand_zones: pd.DataFrame, city: str) -> pd.DataFrame:
    return demand_zones[demand_zones["city"].astype(str).str.lower() == city.lower()].reset_index(drop=True)


def sample_demand_zone(
    rng: np.random.Generator,
    city: str,
    demand_zones: pd.DataFrame,
    *,
    demand_config: TaxiDemandConfig,
) -> tuple[str, float, float]:
    city_zones = _city_demand_zones(demand_zones, city)
    if len(city_zones) == 0:
        raise ValueError(f"No demand zones configured for city: {city}")
    weights = np.array(
        [
            float(row["weight"]) * _zone_weight(str(row["zone_type"]), demand_config.zone_attractiveness)
            for _, row in city_zones.iterrows()
        ],
        dtype=float,
    )
    total = weights.sum()
    probs = weights / total if total > 0 else np.ones(len(weights)) / len(weights)
    idx = int(rng.choice(len(city_zones), p=probs))
    row = city_zones.iloc[idx]
    return f"demand_zone:{row['zone_id']}", float(row["lat"]), float(row["lon"])


def sample_booking_location(
    rng: np.random.Generator,
    city: str,
    stands: pd.DataFrame,
    demand_zones: pd.DataFrame,
    *,
    demand_config: TaxiDemandConfig,
    stand_probability: float | None = None,
) -> tuple[float, float, str]:
    stand_probability = (
        demand_config.stand_probability if stand_probability is None else stand_probability
    )
    lats, lons, stand_flags, probs = _build_endpoint_pool(
        city,
        stands,
        demand_zones,
        zone_attractiveness=demand_config.zone_attractiveness,
    )
    use_stand = bool(rng.random() < stand_probability)
    if use_stand and stand_flags.any():
        mask = stand_flags
    else:
        mask = ~stand_flags if (~stand_flags).any() else stand_flags
    masked_probs = probs.copy()
    masked_probs[~mask] = 0.0
    total = masked_probs.sum()
    if total <= 0:
        masked_probs = probs
    else:
        masked_probs = masked_probs / total
    idx = int(rng.choice(len(lats), p=masked_probs))
    source = "stand" if stand_flags[idx] else "demand_zone"
    return float(lats[idx]), float(lons[idx]), source
