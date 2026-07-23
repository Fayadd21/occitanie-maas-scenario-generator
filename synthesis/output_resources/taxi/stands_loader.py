from __future__ import annotations

import json
import os
import re
from typing import Any

import pandas as pd

from synthesis.output_resources.taxi.stands import finalize_taxi_stands_dataframe

TAXI_CITY_PROFILES: dict[str, dict[str, Any]] = {
    "toulouse": {
        "label": "Toulouse",
        "insee_codes": {"31555"},
        "bbox": (1.20, 1.60, 43.50, 43.75),
        "source_hints": ("toulouse",),
    },
    "montpellier": {
        "label": "Montpellier",
        "insee_codes": {"34172"},
        "bbox": (3.75, 4.00, 43.55, 43.68),
        "source_hints": ("montpellier",),
    },
    "nimes": {
        "label": "Nimes",
        "insee_codes": {"30189"},
        "bbox": (4.25, 4.45, 43.78, 43.88),
        "source_hints": ("nimes", "nîmes"),
    },
    "perpignan": {
        "label": "Perpignan",
        "insee_codes": {"66136"},
        "bbox": (2.85, 3.00, 42.65, 42.75),
        "source_hints": ("perpignan",),
    },
}


def _normalize_target_cities(target_cities: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if not target_cities:
        return tuple(TAXI_CITY_PROFILES.keys())
    normalized: list[str] = []
    for city in target_cities:
        key = str(city).strip().lower().replace("î", "i").replace(" ", "_")
        if key in TAXI_CITY_PROFILES and key not in normalized:
            normalized.append(key)
    return tuple(normalized or TAXI_CITY_PROFILES.keys())


def _extract_lat_lon(properties: dict[str, Any]) -> tuple[Any, Any]:
    gp = properties.get("geo_point_2d")
    if isinstance(gp, dict) and "lat" in gp and "lon" in gp:
        return gp.get("lat"), gp.get("lon")
    if "coord_y" in properties and "coord_x" in properties:
        return properties.get("coord_y"), properties.get("coord_x")
    return None, None


def _city_from_source_file(source_file: str, target_cities: tuple[str, ...]) -> str | None:
    lowered = source_file.lower()
    for city in target_cities:
        profile = TAXI_CITY_PROFILES[city]
        if any(hint in lowered for hint in profile["source_hints"]):
            return city
    return None


def _city_from_insee(insee: str | None, target_cities: tuple[str, ...]) -> str | None:
    if insee is None:
        return None
    code = str(insee).strip().zfill(5)
    for city in target_cities:
        if code in TAXI_CITY_PROFILES[city]["insee_codes"]:
            return city
    return None


def _city_from_coordinates(
    lat: float | None,
    lon: float | None,
    target_cities: tuple[str, ...],
) -> str | None:
    if lat is None or lon is None:
        return None
    for city in target_cities:
        lon_min, lon_max, lat_min, lat_max = TAXI_CITY_PROFILES[city]["bbox"]
        if lon_min <= float(lon) <= lon_max and lat_min <= float(lat) <= lat_max:
            return city
    return None


def _resolve_city(
    *,
    source_file: str,
    commune: str | None,
    insee: str | None,
    lat: float | None,
    lon: float | None,
    target_cities: tuple[str, ...],
) -> str | None:
    city = _city_from_source_file(source_file, target_cities)
    if city is not None:
        return city
    city = _city_from_insee(insee, target_cities)
    if city is not None:
        return city
    if commune:
        commune_key = re.sub(r"[^a-z0-9]+", "_", str(commune).strip().lower())
        for city in target_cities:
            if commune_key == city or commune_key.startswith(city):
                return city
    return _city_from_coordinates(lat, lon, target_cities)


def _normalize_record_type(raw_type: str | None, *, source_kind: str) -> str:
    value = str(raw_type or "").strip().lower()
    if not value or value in {"none", "null"}:
        return "unknown"
    if value == "taxi":
        return "taxi"
    if "pmr" in value and "taxi" not in value:
        return "pmr"
    if "livraison" in value:
        return "livraison"
    if "transport" in value and "fond" in value:
        return "transport_fond"
    return value


def _is_taxi_stand_record(record_type: str) -> bool:
    return record_type == "taxi"


def _append_record(
    rows: list[dict[str, Any]],
    *,
    name: str | None,
    commune: str | None,
    nb_places: Any,
    lat: Any,
    lon: Any,
    source_file: str,
    record_type: str,
    city: str | None,
    target_cities: tuple[str, ...],
) -> None:
    if lat is None or lon is None:
        return
    if city is None or city not in target_cities:
        return
    rows.append(
        {
            "name": name,
            "commune": commune,
            "nb_places": nb_places,
            "lat": lat,
            "lon": lon,
            "source_file": source_file,
            "record_type": record_type,
            "city": city,
            "is_taxi_stand": _is_taxi_stand_record(record_type),
        }
    )


def _load_json_taxi_records(
    path: str,
    *,
    source_file: str,
    target_cities: tuple[str, ...],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)

    records = payload if isinstance(payload, list) else payload.get("features", [])
    montpellier_source = "montpellier" in source_file.lower()

    for item in records:
        if isinstance(item, dict) and "properties" in item:
            props = item.get("properties", {})
            lat, lon = _extract_lat_lon(props)
            geometry = item.get("geometry", {})
            if (lat is None or lon is None) and isinstance(geometry, dict):
                coordinates = geometry.get("coordinates", [])
                if isinstance(coordinates, list) and len(coordinates) >= 2:
                    lon, lat = coordinates[0], coordinates[1]
        else:
            props = item if isinstance(item, dict) else {}
            lat, lon = _extract_lat_lon(props)

        record_type = _normalize_record_type(
            props.get("tipe"),
            source_kind="montpellier" if montpellier_source else "toulouse",
        )
        if montpellier_source and not _is_taxi_stand_record(record_type):
            city = _resolve_city(
                source_file=source_file,
                commune=props.get("commune"),
                insee=props.get("insee"),
                lat=lat,
                lon=lon,
                target_cities=target_cities,
            )
            if city is not None:
                _append_record(
                    rows,
                    name=props.get("lib_voie") or props.get("nom") or props.get("name"),
                    commune=props.get("commune"),
                    nb_places=props.get("nb_places") or props.get("nbr_emplacement"),
                    lat=lat,
                    lon=lon,
                    source_file=source_file,
                    record_type=record_type,
                    city=city,
                    target_cities=target_cities,
                )
            continue

        if not montpellier_source:
            record_type = "taxi"

        city = _resolve_city(
            source_file=source_file,
            commune=props.get("commune"),
            insee=props.get("insee"),
            lat=lat,
            lon=lon,
            target_cities=target_cities,
        )
        _append_record(
            rows,
            name=props.get("lib_voie") or props.get("nom") or props.get("name"),
            commune=props.get("commune"),
            nb_places=props.get("nb_places") or props.get("nbr_emplacement"),
            lat=lat,
            lon=lon,
            source_file=source_file,
            record_type=record_type,
            city=city,
            target_cities=target_cities,
        )
    return rows


def load_raw_taxi_stand_records(
    data_path: str | os.PathLike[str],
    relative_paths: list[str] | tuple[str, ...],
    *,
    target_cities: list[str] | tuple[str, ...] | None = None,
) -> pd.DataFrame:
    cities = _normalize_target_cities(target_cities)
    rows: list[dict[str, Any]] = []
    for rel_path in relative_paths:
        path = os.path.join(data_path, rel_path)
        if not os.path.exists(path):
            continue
        source_file = os.path.basename(path)
        rows.extend(
            _load_json_taxi_records(
                path,
                source_file=source_file,
                target_cities=cities,
            )
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "name",
                "commune",
                "nb_places",
                "lat",
                "lon",
                "source_file",
                "record_type",
                "city",
                "is_taxi_stand",
            ]
        )
    return pd.DataFrame(rows)


def summarize_taxi_stand_sources(
    raw_records: pd.DataFrame,
    target_cities: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    cities = _normalize_target_cities(target_cities)
    city_stats: dict[str, dict[str, Any]] = {}
    for city in cities:
        profile = TAXI_CITY_PROFILES[city]
        city_stats[city] = {
            "label": profile["label"],
            "data_available": False,
            "total_records": 0,
            "taxi_stands": 0,
            "non_taxi": 0,
            "record_types": {},
        }

    if len(raw_records) == 0:
        return {
            "cities": city_stats,
            "exported_taxi_stands_after_dedup": 0,
            "total_raw_records": 0,
            "total_taxi_stands_raw": 0,
            "total_non_taxi_raw": 0,
        }

    for city in cities:
        subset = raw_records[raw_records["city"] == city]
        if len(subset) == 0:
            continue
        city_stats[city]["data_available"] = True
        city_stats[city]["total_records"] = int(len(subset))
        city_stats[city]["taxi_stands"] = int(subset["is_taxi_stand"].sum())
        city_stats[city]["non_taxi"] = int((~subset["is_taxi_stand"]).sum())
        city_stats[city]["record_types"] = {
            str(record_type): int(count)
            for record_type, count in subset["record_type"].value_counts().items()
        }

    exportable = raw_records[raw_records["is_taxi_stand"]].copy()
    exported = finalize_taxi_stands_dataframe(exportable)
    exported_by_city = (
        exportable.groupby("city", observed=False).size().to_dict() if len(exportable) else {}
    )
    for city in cities:
        city_stats[city]["exported_taxi_stands_before_dedup"] = int(exported_by_city.get(city, 0))
    dedup_by_city = exported.groupby("city", observed=False).size().to_dict() if "city" in exported.columns and len(exported) else {}
    for city in cities:
        city_stats[city]["exported_taxi_stands_after_dedup"] = int(dedup_by_city.get(city, 0))

    return {
        "cities": city_stats,
        "exported_taxi_stands_after_dedup": int(len(exported)),
        "total_raw_records": int(len(raw_records)),
        "total_taxi_stands_raw": int(raw_records["is_taxi_stand"].sum()),
        "total_non_taxi_raw": int((~raw_records["is_taxi_stand"]).sum()),
    }


def load_taxi_stands_dataframe(
    data_path: str | os.PathLike[str],
    relative_paths: list[str] | tuple[str, ...],
    *,
    target_cities: list[str] | tuple[str, ...] | None = None,
) -> pd.DataFrame:
    raw_records = load_raw_taxi_stand_records(
        data_path,
        relative_paths,
        target_cities=target_cities,
    )
    if len(raw_records) == 0:
        return raw_records
    exportable = raw_records[raw_records["is_taxi_stand"]].copy()
    return finalize_taxi_stands_dataframe(exportable)
