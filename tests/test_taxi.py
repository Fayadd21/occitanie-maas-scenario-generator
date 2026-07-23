from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from synthesis.output_resources.taxi.demand import TaxiDemandConfig, load_taxi_demand_config
from synthesis.output_resources.taxi.fleet import (
    TaxiFleetConfig,
    _fits_schedule,
    generate_taxi_operator_payload,
    load_taxi_fleet_config,
)
from synthesis.output_resources.taxi.stands import (
    classify_zone_type,
    finalize_taxi_stands_dataframe,
    trip_duration_minutes,
)
from synthesis.output_resources.taxi.stands_loader import (
    load_raw_taxi_stand_records,
    load_taxi_stands_dataframe,
    summarize_taxi_stand_sources,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_config() -> dict:
    config_path = _repo_root() / "config_occitanie.yml"
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return payload.get("config", payload)


def _fleet_config(**overrides: object) -> TaxiFleetConfig:
    config = load_taxi_fleet_config(_repo_root() / "backend" / "config" / "taxi_fleet.yml")
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def test_finalize_taxi_stands_deduplicates_same_location():
    df = pd.DataFrame(
        [
            {"name": "PL WILSON", "commune": "TOULOUSE", "nb_places": 10, "lat": 43.6047, "lon": 1.4477, "source_file": "a.json"},
            {"name": "PL DU PRESIDENT THOMAS WOODROW WILSON", "commune": "TOULOUSE", "nb_places": 5, "lat": 43.604721, "lon": 1.447737, "source_file": "a.json"},
        ]
    )
    out = finalize_taxi_stands_dataframe(df)
    assert len(out) == 1
    assert out.iloc[0]["nb_places"] == 15
    assert out.iloc[0]["zone_type"] == "city_center"


def test_classify_zone_type_keywords():
    assert classify_zone_type("GARE SNCF MATABIAU") == "railway_station"
    assert classify_zone_type("AV D AEROCONSTELLATION", "BLAGNAC") == "airport"
    assert classify_zone_type("METRO BASSO CAMBO") == "multimodal_hub"


def test_trip_duration_minutes_positive():
    minutes = trip_duration_minutes(43.6045, 1.4440, 43.6293, 1.3676, average_speed_kmh=25, circuity_factor=1.3)
    assert minutes >= 1


def test_generate_taxi_operator_payload_shape():
    stands = finalize_taxi_stands_dataframe(
        pd.DataFrame(
            [
                {
                    "name": "PL WILSON",
                    "commune": "TOULOUSE",
                    "nb_places": 10,
                    "lat": 43.6047,
                    "lon": 1.4477,
                    "source_file": "a.json",
                    "city": "toulouse",
                },
                {
                    "name": "METRO BASSO CAMBO",
                    "commune": "TOULOUSE",
                    "nb_places": 4,
                    "lat": 43.5695,
                    "lon": 1.3920,
                    "source_file": "a.json",
                    "city": "toulouse",
                },
            ]
        )
    )
    config = _fleet_config(
        random_seed=7,
        n_fleet=20,
        occupancy_mean=0.12,
        occupancy_std=0.02,
        target_cities=("toulouse",),
    )
    demand_full = load_taxi_demand_config(
        _repo_root() / "backend" / "config" / "taxi_demand_zones.yml"
    )
    demand_config = TaxiDemandConfig(
        cities={"toulouse": {"n_fleet": 20}},
        demand_zones=demand_full.demand_zones,
        stand_probability=demand_full.stand_probability,
        zone_attractiveness=demand_full.zone_attractiveness,
    )
    payload, stats = generate_taxi_operator_payload(
        stands,
        weekday="monday",
        config=config,
        rng=np.random.default_rng(7),
        demand_config=demand_config,
    )
    assert payload["operator_id"] == "Taxi"
    assert payload["resources"]
    assert payload["points"]
    assert all("parking_capacity" in point for point in payload["points"])
    assert all("zone_type" in point for point in payload["points"])
    assert all(resource["mode"] == "Taxi" for resource in payload["resources"])
    assert stats["n_day"] <= config.n_fleet
    assert "cities" in stats


def test_demand_only_city_generates_without_stand_points():
    demand_config = TaxiDemandConfig(
        cities={"perpignan": {"n_fleet": 20}},
        demand_zones={
            "perpignan": [
                {
                    "id": "gare_perpignan",
                    "name": "Gare de Perpignan",
                    "lat": 42.6965,
                    "lon": 2.8787,
                    "zone_type": "railway_station",
                    "weight": 3.0,
                }
            ]
        },
    )
    payload, stats = generate_taxi_operator_payload(
        pd.DataFrame(),
        weekday="monday",
        config=_fleet_config(random_seed=5, n_fleet=20, target_cities=("perpignan",)),
        rng=np.random.default_rng(5),
        demand_config=demand_config,
    )
    assert stats["cities"]["perpignan"]["has_stand_data"] is False
    assert stats["cities"]["perpignan"]["stands"] == 0
    assert payload["points"] == []
    assert payload["resources"]
    assert payload["resources"][0]["start_stand"].startswith("demand_zone:")
    assert stats["cities"]["perpignan"]["pickup_from_stand_share"] == 0.0


def test_bookings_are_not_always_sampled_from_stands():
    stands = finalize_taxi_stands_dataframe(
        pd.DataFrame(
            [
                {
                    "name": "PL WILSON",
                    "commune": "TOULOUSE",
                    "nb_places": 10,
                    "lat": 43.6047,
                    "lon": 1.4477,
                    "source_file": "a.json",
                    "city": "toulouse",
                },
            ]
        )
    )
    config = _fleet_config(
        random_seed=11,
        n_fleet=80,
        occupancy_mean=0.20,
        occupancy_std=0.02,
        target_cities=("toulouse",),
    )
    demand_full = load_taxi_demand_config(
        _repo_root() / "backend" / "config" / "taxi_demand_zones.yml"
    )
    demand_config = TaxiDemandConfig(
        cities={"toulouse": {"n_fleet": 80}},
        demand_zones=demand_full.demand_zones,
        stand_probability=demand_full.stand_probability,
        zone_attractiveness=demand_full.zone_attractiveness,
    )
    _payload, stats = generate_taxi_operator_payload(
        stands,
        weekday="monday",
        config=config,
        rng=np.random.default_rng(11),
        demand_config=demand_config,
    )
    assert stats["bookings"] > 0
    assert stats["pickup_from_stand_share"] < 1.0
    assert stats["dropoff_from_stand_share"] < 1.0


def test_fits_schedule_rejects_overlap():
    bookings = [
        {
            "pickup": {"time": 480, "lat": 43.6, "lon": 1.44},
            "dropoff": {"time": 510, "lat": 43.61, "lon": 1.45},
        }
    ]
    assert not _fits_schedule(500, 520, 420, 1020, bookings)
    assert _fits_schedule(520, 550, 420, 1020, bookings)


def test_taxi_resources_do_not_use_stand_capacity_field():
    stands = finalize_taxi_stands_dataframe(
        pd.DataFrame(
            [
                {"name": "PL WILSON", "commune": "TOULOUSE", "nb_places": 15, "lat": 43.6047, "lon": 1.4477, "source_file": "a.json"},
            ]
        )
    )
    config = _fleet_config(random_seed=1, n_fleet=5, target_cities=("toulouse",))
    demand_config = TaxiDemandConfig(
        cities={"toulouse": {"n_fleet": 5}},
        demand_zones={"toulouse": []},
    )
    payload, _stats = generate_taxi_operator_payload(
        stands,
        weekday="monday",
        config=config,
        rng=np.random.default_rng(1),
        demand_config=demand_config,
    )
    allowed = set(config.passenger_capacity_weights or {})
    for resource in payload["resources"]:
        assert "capacity" not in resource
        assert resource["passenger_capacity"] in allowed
        assert "bookings" in resource


def test_montpellier_source_keeps_only_taxi_stands_for_export():
    data_path = _repo_root() / "data"
    raw = load_raw_taxi_stand_records(
        data_path,
        ["taxi_pmr_occitanie/pmr_taxis_delivery_Montpellier.json"],
        target_cities=["montpellier"],
    )
    stats = summarize_taxi_stand_sources(raw, target_cities=["montpellier"])
    city = stats["cities"]["montpellier"]
    assert city["data_available"]
    assert city["taxi_stands"] == 16
    assert city["non_taxi"] > 0
    assert city["exported_taxi_stands_after_dedup"] <= city["taxi_stands"]

    exported = load_taxi_stands_dataframe(
        data_path,
        ["taxi_pmr_occitanie/pmr_taxis_delivery_Montpellier.json"],
        target_cities=["montpellier"],
    )
    assert len(exported) <= 16
    assert (exported["city"] == "montpellier").all()


def test_toulouse_open_data_records_are_all_taxi():
    data_path = _repo_root() / "data"
    raw = load_raw_taxi_stand_records(
        data_path,
        ["taxi_pmr_occitanie/taxis_toulouse.json"],
        target_cities=["toulouse"],
    )
    stats = summarize_taxi_stand_sources(raw, target_cities=["toulouse"])
    city = stats["cities"]["toulouse"]
    assert city["total_records"] == 42
    assert city["taxi_stands"] == 42
    assert city["non_taxi"] == 0


def test_perpignan_and_nimes_have_no_local_stand_sources():
    config = _load_config()
    data_path = Path(config["data_path"])
    if not data_path.is_absolute():
        data_path = _repo_root() / data_path
    taxi_data_paths = config.get("taxi_data_paths") or []
    raw = load_raw_taxi_stand_records(data_path, taxi_data_paths)
    stats = summarize_taxi_stand_sources(raw)
    assert stats["cities"]["perpignan"]["data_available"] is False
    assert stats["cities"]["nimes"]["data_available"] is False
