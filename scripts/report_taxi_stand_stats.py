#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from synthesis.output_resources.taxi.stands_loader import (
    TAXI_CITY_PROFILES,
    load_raw_taxi_stand_records,
    summarize_taxi_stand_sources,
)


def _load_config(config_path: Path) -> dict:
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return payload.get("config", payload)


def _resolve_data_path(config: dict, config_path: Path) -> Path:
    raw = Path(str(config["data_path"]))
    if raw.is_dir():
        return raw
    repo_root = config_path.resolve().parent
    fallback = repo_root / "data"
    if fallback.is_dir():
        return fallback
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description="Report taxi stand coverage by city.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config_occitanie.yml"),
        help="Scenario config YAML (default: config_occitanie.yml)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of a text table.",
    )
    args = parser.parse_args()

    config = _load_config(args.config)
    data_path = _resolve_data_path(config, args.config)
    taxi_data_paths = config.get("taxi_data_paths") or []
    target_cities = config.get("taxi_cities") or list(TAXI_CITY_PROFILES.keys())

    raw = load_raw_taxi_stand_records(data_path, taxi_data_paths, target_cities=target_cities)
    stats = summarize_taxi_stand_sources(raw, target_cities=target_cities)

    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return

    print("Taxi stand source statistics")
    print(f"Data path: {data_path}")
    print(f"Sources: {', '.join(taxi_data_paths) if taxi_data_paths else '(none)'}")
    print()
    print(
        f"{'City':<14} {'Data?':<7} {'Total':<7} {'Taxi':<7} {'Non-taxi':<9} "
        f"{'Export':<7} {'Dedup':<7} Record types"
    )
    print("-" * 90)
    for city, city_stats in stats["cities"].items():
        types = ", ".join(
            f"{name}={count}"
            for name, count in sorted(city_stats.get("record_types", {}).items())
        ) or "-"
        print(
            f"{city_stats['label']:<14} "
            f"{'yes' if city_stats['data_available'] else 'no':<7} "
            f"{city_stats['total_records']:<7} "
            f"{city_stats['taxi_stands']:<7} "
            f"{city_stats['non_taxi']:<9} "
            f"{city_stats.get('exported_taxi_stands_before_dedup', 0):<7} "
            f"{city_stats.get('exported_taxi_stands_after_dedup', 0):<7} "
            f"{types}"
        )
    print()
    print(
        "Totals: "
        f"{stats['total_raw_records']} raw records, "
        f"{stats['total_taxi_stands_raw']} taxi stands, "
        f"{stats['total_non_taxi_raw']} non-taxi, "
        f"{stats['exported_taxi_stands_after_dedup']} exported after dedup"
    )


if __name__ == "__main__":
    main()
