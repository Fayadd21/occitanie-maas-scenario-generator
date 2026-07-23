from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from synthesis.output_resources.taxi.demand import (
    TaxiDemandConfig,
    demand_zones_dataframe,
    load_taxi_demand_config,
    sample_booking_location,
    sample_demand_zone,
)
from synthesis.output_resources.taxi.stands import (
    finalize_taxi_stands_dataframe,
    trip_duration_minutes,
    zone_weight,
)
from synthesis.output_resources.taxi.stands_loader import TAXI_CITY_PROFILES

WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def parse_passenger_capacity_weights(raw: Any) -> dict[int, float]:
    """Accept a fixed int or a capacity -> weight map; weights are renormalized at sample time."""
    if raw is None:
        return {4: 1.0}
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return {int(raw): 1.0}
    if isinstance(raw, dict) and raw:
        return {int(k): float(v) for k, v in raw.items()}
    raise ValueError("passenger_capacity must be an int or a non-empty weight map")


def sample_passenger_capacity(
    rng: np.random.Generator,
    weights: dict[int, float],
) -> int:
    values = np.array(list(weights.keys()), dtype=int)
    probs = np.array(list(weights.values()), dtype=float)
    total = float(probs.sum())
    if total <= 0:
        raise ValueError("passenger_capacity weights must sum to a positive value")
    probs = probs / total
    return int(rng.choice(values, p=probs))


@dataclass
class TaxiFleetConfig:
    random_seed: int = 42
    n_fleet: int = 0
    passenger_capacity_weights: dict[int, float] | None = None
    wheelchair_accessible_fraction: float = 0.0
    average_speed_kmh: float = 25.0
    circuity_factor: float = 1.0
    p_day: dict[str, float] | None = None
    shift_profiles: list[dict[str, Any]] | None = None
    occupancy_mean: float = 0.0
    occupancy_std: float = 0.0
    occupancy_min: float = 0.0
    occupancy_max: float = 1.0
    hourly_demand: dict[int, float] | None = None
    zone_attractiveness: dict[str, float] | None = None
    demand_config_path: str | None = None
    target_cities: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.passenger_capacity_weights is None:
            self.passenger_capacity_weights = {4: 1.0}

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> TaxiFleetConfig:
        occupancy = payload.get("occupancy") or {}
        hourly = payload.get("hourly_demand") or {}
        hourly_norm = {int(k): float(v) for k, v in hourly.items()} if hourly else None
        p_day_raw = payload.get("p_day") or {}
        return cls(
            random_seed=int(payload["random_seed"]) if "random_seed" in payload else 42,
            n_fleet=int(payload.get("N_fleet", payload.get("n_fleet", 0))),
            passenger_capacity_weights=parse_passenger_capacity_weights(
                payload.get("passenger_capacity")
            ),
            wheelchair_accessible_fraction=float(payload.get("wheelchair_accessible_fraction", 0.0)),
            average_speed_kmh=float(payload.get("average_speed_kmh", 25.0)),
            circuity_factor=float(payload.get("circuity_factor", 1.0)),
            p_day={str(k).lower(): float(v) for k, v in p_day_raw.items()} or None,
            shift_profiles=list(payload["shift_profiles"]) if payload.get("shift_profiles") else None,
            occupancy_mean=float(occupancy["mean"]) if "mean" in occupancy else float(payload.get("occupancy_mean", 0.0)),
            occupancy_std=float(occupancy["std"]) if "std" in occupancy else float(payload.get("occupancy_std", 0.0)),
            occupancy_min=float(occupancy["min"]) if "min" in occupancy else float(payload.get("occupancy_min", 0.0)),
            occupancy_max=float(occupancy["max"]) if "max" in occupancy else float(payload.get("occupancy_max", 1.0)),
            hourly_demand=hourly_norm,
            zone_attractiveness={
                str(k): float(v) for k, v in (payload.get("zone_attractiveness") or {}).items()
            }
            or None,
            demand_config_path=payload.get("demand_config_path"),
            target_cities=tuple(str(c).lower() for c in (payload.get("target_cities") or ())) or None,
        )


def load_taxi_fleet_config(path: Path | None = None) -> TaxiFleetConfig:
    if path is None or not path.is_file():
        return TaxiFleetConfig()
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return TaxiFleetConfig.from_mapping(payload if isinstance(payload, dict) else {})


def _require_generation_config(config: TaxiFleetConfig) -> None:
    missing: list[str] = []
    if not config.p_day:
        missing.append("p_day")
    if not config.shift_profiles:
        missing.append("shift_profiles")
    if not config.hourly_demand:
        missing.append("hourly_demand")
    if missing:
        raise ValueError(
            "Taxi fleet config missing required keys "
            f"({', '.join(missing)}); set them in taxi_fleet.yml"
        )

def load_taxi_stands_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", dtype=str)
    if "zone_type" not in df.columns or "stand_id" not in df.columns:
        numeric = df.copy()
        numeric["lat"] = pd.to_numeric(df["lat"], errors="coerce")
        numeric["lon"] = pd.to_numeric(df["lon"], errors="coerce")
        numeric["nb_places"] = pd.to_numeric(df.get("nb_places"), errors="coerce")
        return finalize_taxi_stands_dataframe(numeric)
    out = df.copy()
    out["lat"] = pd.to_numeric(out["lat"], errors="coerce")
    out["lon"] = pd.to_numeric(out["lon"], errors="coerce")
    out["nb_places"] = pd.to_numeric(out["nb_places"], errors="coerce").fillna(1).astype(int)
    return out.dropna(subset=["lat", "lon"]).reset_index(drop=True)


def _shift_profile_weights(weekday: str, profiles: list[dict[str, Any]]) -> np.ndarray:
    weights = np.array([float(p.get("proportion", 0.0)) for p in profiles], dtype=float)
    if weekday in {"friday", "saturday"} and len(weights) >= 4:
        moved = min(weights[1] * 0.15, weights[1])
        weights[1] -= moved
        weights[3] += moved
    total = weights.sum()
    return weights / total if total > 0 else np.ones(len(weights)) / len(weights)


def _sample_shift(rng: np.random.Generator, profile: dict[str, Any]) -> tuple[int, int]:
    start_lo, start_hi = profile["start_min"]
    dur_lo, dur_hi = profile["duration_hours"]
    start = int(rng.integers(int(start_lo), int(start_hi) + 1))
    duration_min = int(rng.integers(int(dur_lo * 60), int(dur_hi * 60) + 1))
    end = start + duration_min
    return start, end


def _hourly_demand_weights(
    weekday: str,
    hourly_demand: dict[int, float],
) -> tuple[np.ndarray, np.ndarray]:
    hours = np.array(sorted(hourly_demand.keys()), dtype=int)
    weights = np.array([hourly_demand[int(h)] for h in hours], dtype=float)
    if weekday in {"friday", "saturday"}:
        for idx, hour in enumerate(hours):
            if hour >= 22 or hour <= 3:
                weights[idx] *= 1.4
    total = weights.sum()
    if total <= 0:
        weights = np.ones(len(hours))
        total = len(hours)
    return hours, weights / total


def _sample_pickup_minute(
    rng: np.random.Generator,
    shift_start: int,
    shift_end: int,
    weekday: str,
    hourly_demand: dict[int, float],
) -> int | None:
    hours, weights = _hourly_demand_weights(weekday, hourly_demand)
    for _ in range(40):
        hour = int(rng.choice(hours, p=weights))
        minute = int(rng.integers(0, 60))
        pickup = hour * 60 + minute
        if shift_end > 1440:
            if pickup < (shift_end - 1440):
                pickup += 1440
        if shift_start <= pickup < shift_end:
            return pickup
    return None


def _booking_intervals(bookings: list[dict[str, Any]]) -> list[tuple[int, int]]:
    return [
        (int(b["pickup"]["time"]), int(b["dropoff"]["time"]))
        for b in bookings
    ]


def _fits_schedule(
    pickup_time: int,
    dropoff_time: int,
    shift_start: int,
    shift_end: int,
    bookings: list[dict[str, Any]],
) -> bool:
    if pickup_time < shift_start or dropoff_time > shift_end:
        return False
    for start, end in _booking_intervals(bookings):
        if not (dropoff_time <= start or pickup_time >= end):
            return False
    return True


def _occupied_minutes(bookings: list[dict[str, Any]]) -> int:
    return sum(int(b["dropoff"]["time"]) - int(b["pickup"]["time"]) for b in bookings)


def _stand_weights(stands: pd.DataFrame, zone_attractiveness: dict[str, float] | None) -> np.ndarray:
    weights = []
    for _, row in stands.iterrows():
        attractiveness = zone_weight(str(row["zone_type"]), zone_attractiveness)
        weights.append(int(row["nb_places"]) * float(attractiveness))
    arr = np.array(weights, dtype=float)
    total = arr.sum()
    return arr / total if total > 0 else np.ones(len(arr)) / len(arr)


def _sample_stand_index(
    rng: np.random.Generator,
    stands: pd.DataFrame,
    zone_attractiveness: dict[str, float] | None,
) -> int:
    probs = _stand_weights(stands, zone_attractiveness)
    return int(rng.choice(len(stands), p=probs))


def _infer_city_from_coordinates(lat: float, lon: float) -> str | None:
    for city, profile in TAXI_CITY_PROFILES.items():
        lon_min, lon_max, lat_min, lat_max = profile["bbox"]
        if lon_min <= float(lon) <= lon_max and lat_min <= float(lat) <= lat_max:
            return city
    return None


def _ensure_city_column(stands: pd.DataFrame) -> pd.DataFrame:
    if len(stands) == 0:
        return stands.copy()
    frame = stands.copy()
    if "city" not in frame.columns:
        frame["city"] = ""
    frame["city"] = frame["city"].fillna("").astype(str).str.strip().str.lower()
    missing = frame["city"] == ""
    if missing.any():
        frame.loc[missing, "city"] = [
            _infer_city_from_coordinates(float(lat), float(lon)) or ""
            for lat, lon in zip(frame.loc[missing, "lat"], frame.loc[missing, "lon"], strict=False)
        ]
    return frame


def _resolve_target_cities(
    config: TaxiFleetConfig,
    demand_config: TaxiDemandConfig,
) -> tuple[str, ...]:
    if config.target_cities:
        return tuple(config.target_cities)
    if demand_config.cities:
        return tuple(demand_config.cities.keys())
    return ()


def _city_fleet_sizes(
    config: TaxiFleetConfig,
    demand_config: TaxiDemandConfig,
    cities: tuple[str, ...],
) -> dict[str, int]:
    if demand_config.cities:
        return {
            city: int(demand_config.cities[city].get("n_fleet", config.n_fleet))
            for city in cities
            if city in demand_config.cities
        }
    if len(cities) == 1:
        return {cities[0]: config.n_fleet}
    share = max(1, config.n_fleet // len(cities))
    return {city: share for city in cities}


def _cities_with_real_stands(frame: pd.DataFrame) -> tuple[str, ...]:
    if len(frame) == 0 or "city" not in frame.columns:
        return ()
    configured = frame[frame["city"].astype(str).str.strip() != ""]
    if len(configured) == 0:
        return ()
    return tuple(sorted(configured["city"].astype(str).str.lower().unique()))


def _prepare_fleet_context(
    stands: pd.DataFrame,
    *,
    config: TaxiFleetConfig,
    demand_config: TaxiDemandConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, tuple[str, ...], tuple[str, ...]]:
    configured = _resolve_target_cities(config, demand_config)
    frame = _ensure_city_column(stands)
    stand_cities = _cities_with_real_stands(frame)
    if configured:
        fleet_cities = tuple(
            city
            for city in configured
            if city in stand_cities or city in demand_config.demand_zones
        )
    else:
        fleet_cities = tuple(
            sorted(set(stand_cities) | set(demand_config.demand_zones.keys()))
        )
    if not fleet_cities:
        raise ValueError("No taxi cities configured for fleet generation")
    if len(frame) == 0:
        stand_points = frame.copy()
    else:
        stand_points = frame[frame["city"].isin(stand_cities)].reset_index(drop=True)
    zones = demand_zones_dataframe(demand_config, cities=fleet_cities)
    return stand_points, zones, fleet_cities, stand_cities


def _build_stand_points(stands: pd.DataFrame) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for _, row in stands.iterrows():
        points.append(
            {
                "id": str(row["stand_id"]),
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "kind": "taxi_stand",
                "name": str(row["name"]),
                "parking_capacity": int(row["nb_places"]),
                "zone_type": str(row["zone_type"]),
            }
        )
    return points


def generate_taxi_operator_payload(
    stands: pd.DataFrame,
    *,
    weekday: str,
    config: TaxiFleetConfig,
    rng: np.random.Generator | None = None,
    demand_config: TaxiDemandConfig | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    weekday = weekday.lower()
    if weekday not in WEEKDAYS:
        raise ValueError(f"Invalid weekday: {weekday}")

    rng = rng or np.random.default_rng(config.random_seed)
    _require_generation_config(config)
    demand_config = demand_config or load_taxi_demand_config(None)
    if not demand_config.cities and not demand_config.demand_zones:
        default_path = Path(__file__).resolve().parents[3] / "backend" / "config" / "taxi_demand_zones.yml"
        if default_path.is_file():
            demand_config = load_taxi_demand_config(default_path)
    if len(stands) == 0 and not demand_config.demand_zones:
        raise ValueError("No taxi stands or demand zones available for fleet generation")
    # Prefer demand YAML attractiveness (fuller); fall back to fleet YAML if present.
    zone_attractiveness = demand_config.zone_attractiveness or config.zone_attractiveness
    if zone_attractiveness and not demand_config.zone_attractiveness:
        demand_config.zone_attractiveness = zone_attractiveness
    stand_points, demand_zones, fleet_cities, stand_cities = _prepare_fleet_context(
        stands,
        config=config,
        demand_config=demand_config,
    )
    profiles = config.shift_profiles or []
    profile_weights = _shift_profile_weights(weekday, profiles)
    p_day = (config.p_day or {}).get(weekday)
    if p_day is None:
        raise ValueError(f"p_day missing entry for weekday '{weekday}' in taxi_fleet.yml")
    fleet_by_city = _city_fleet_sizes(config, demand_config, fleet_cities)

    taxi_resources: list[dict[str, Any]] = []
    booking_count = 0
    rejected = 0
    pickup_from_stand = 0
    dropoff_from_stand = 0
    city_stats: dict[str, dict[str, Any]] = {}

    for city in fleet_cities:
        has_stands = city in stand_cities
        if has_stands:
            city_stands = stand_points[stand_points["city"] == city].reset_index(drop=True)
        else:
            city_stands = stand_points.iloc[0:0]
        booking_stand_probability = demand_config.stand_probability if has_stands else 0.0
        n_fleet = fleet_by_city.get(city)
        if not n_fleet:
            continue
        n_day = int(rng.binomial(n_fleet, p_day))
        city_bookings = 0
        city_pickup_stand = 0
        city_dropoff_stand = 0

        for _taxi_index in range(n_day):
            profile = profiles[int(rng.choice(len(profiles), p=profile_weights))]
            shift_start, shift_end = _sample_shift(rng, profile)
            if has_stands:
                start_idx = _sample_stand_index(rng, city_stands, zone_attractiveness)
                start_stand = str(city_stands.iloc[start_idx]["stand_id"])
            else:
                start_stand, _, _ = sample_demand_zone(
                    rng,
                    city,
                    demand_zones,
                    demand_config=demand_config,
                )
            wheelchair = bool(rng.random() < config.wheelchair_accessible_fraction)

            target_occupancy = float(
                np.clip(
                    rng.normal(config.occupancy_mean, config.occupancy_std),
                    config.occupancy_min,
                    config.occupancy_max,
                )
            )
            shift_minutes = shift_end - shift_start
            target_service_minutes = target_occupancy * shift_minutes
            bookings: list[dict[str, Any]] = []

            while _occupied_minutes(bookings) < target_service_minutes:
                pickup_time = _sample_pickup_minute(
                    rng,
                    shift_start,
                    shift_end,
                    weekday,
                    config.hourly_demand or {},
                )
                if pickup_time is None:
                    break

                pickup_lat, pickup_lon, pickup_source = sample_booking_location(
                    rng,
                    city,
                    city_stands,
                    demand_zones,
                    demand_config=demand_config,
                    stand_probability=booking_stand_probability,
                )
                dropoff_lat, dropoff_lon, dropoff_source = sample_booking_location(
                    rng,
                    city,
                    city_stands,
                    demand_zones,
                    demand_config=demand_config,
                    stand_probability=booking_stand_probability,
                )
                if pickup_source == "stand":
                    city_pickup_stand += 1
                    pickup_from_stand += 1
                if dropoff_source == "stand":
                    city_dropoff_stand += 1
                    dropoff_from_stand += 1

                duration = trip_duration_minutes(
                    pickup_lat,
                    pickup_lon,
                    dropoff_lat,
                    dropoff_lon,
                    average_speed_kmh=config.average_speed_kmh,
                    circuity_factor=config.circuity_factor,
                )
                dropoff_time = pickup_time + duration
                booking = {
                    "pickup": {
                        "time": pickup_time,
                        "lat": pickup_lat,
                        "lon": pickup_lon,
                    },
                    "dropoff": {
                        "time": dropoff_time,
                        "lat": dropoff_lat,
                        "lon": dropoff_lon,
                    },
                }
                if _fits_schedule(pickup_time, dropoff_time, shift_start, shift_end, bookings):
                    bookings.append(booking)
                    booking_count += 1
                    city_bookings += 1
                else:
                    rejected += 1
                    if rejected > 200:
                        break

            taxi_resources.append(
                {
                    "id": f"taxi_{len(taxi_resources) + 1:04d}",
                    "mode": "Taxi",
                    "operator_id": "Taxi",
                    "passenger_capacity": sample_passenger_capacity(
                        rng, config.passenger_capacity_weights or {4: 1.0}
                    ),
                    "wheelchair_accessible": wheelchair,
                    "start_stand": start_stand,
                    "availability_period": {"start": shift_start, "end": shift_end},
                    "bookings": bookings,
                    "city": city,
                }
            )

        city_stats[city] = {
            "n_fleet": n_fleet,
            "n_day": n_day,
            "stands": len(city_stands),
            "has_stand_data": has_stands,
            "bookings": city_bookings,
            "pickup_from_stand_share": (
                round(city_pickup_stand / city_bookings, 3) if city_bookings else 0.0
            ),
            "dropoff_from_stand_share": (
                round(city_dropoff_stand / city_bookings, 3) if city_bookings else 0.0
            ),
        }

    operator_payload = {
        "operator_id": "Taxi",
        "modes": [
            {
                "id": "Taxi",
                "operator_id": "Taxi",
                "free": False,
                "restricted_to": [],
            }
        ],
        "resources": taxi_resources,
        "points": _build_stand_points(stand_points),
        "positions": [],
        "timetables": [],
    }
    stats = {
        "weekday": weekday,
        "n_fleet": sum(fleet_by_city.values()),
        "p_day": p_day,
        "n_day": len(taxi_resources),
        "stands": len(stand_points),
        "bookings": booking_count,
        "rejected_bookings": rejected,
        "pickup_from_stand_share": round(pickup_from_stand / booking_count, 3) if booking_count else 0.0,
        "dropoff_from_stand_share": round(dropoff_from_stand / booking_count, 3) if booking_count else 0.0,
        "booking_stand_probability": demand_config.stand_probability,
        "cities": city_stats,
        "random_seed": config.random_seed,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    return operator_payload, stats


def write_taxi_fleet_run(
    stands_csv: Path,
    output_dir: Path,
    *,
    weekday: str,
    config: TaxiFleetConfig,
    timestamp: str | None = None,
    demand_config: TaxiDemandConfig | None = None,
) -> Path:
    stands = load_taxi_stands_csv(stands_csv)
    if demand_config is None:
        demand_path = (
            Path(config.demand_config_path)
            if config.demand_config_path
            else Path(__file__).resolve().parents[3] / "backend" / "config" / "taxi_demand_zones.yml"
        )
        demand_config = load_taxi_demand_config(demand_path)
    rng = np.random.default_rng(config.random_seed)
    operator_payload, stats = generate_taxi_operator_payload(
        stands,
        weekday=weekday,
        config=config,
        rng=rng,
        demand_config=demand_config,
    )
    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_dir / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "Taxi.json").write_text(
        json.dumps(operator_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    stats["stands_csv"] = str(stands_csv)
    stats["run_dir"] = str(run_dir)
    (run_dir / "generation_stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return run_dir
