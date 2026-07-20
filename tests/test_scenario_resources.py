from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
import yaml

from backend.app.services.job_service import (
    _build_resources,
    _resolve_timetable_settings,
    pack_scenario_zip_bytes,
)


def _write_csv(path: Path, header: str, row: str) -> None:
    path.write_text(f"{header}\n{row}\n", encoding="utf-8")


def test_build_resources_includes_multimodal_layers(tmp_path):
    output_path = Path(tmp_path)
    run_id = "run_resources"

    _write_csv(
        output_path / f"{run_id}_carsharing_stations.csv",
        "station_id;lat;lon;capacity",
        "s1;43.6;1.44;2",
    )
    _write_csv(
        output_path / f"{run_id}_carpooling_stops.csv",
        "id_local;lat;lon;nbre_pl",
        "c1;43.6;1.44;8",
    )
    _write_csv(
        output_path / f"{run_id}_taxi_stands.csv",
        "name;lat;lon;nb_places;source_file",
        "Stand A;43.6;1.44;3;taxi.json",
    )
    _write_csv(
        output_path / f"{run_id}_pmr_stands.csv",
        "name;lat;lon;nb_places;source_file",
        "PMR A;43.6;1.44;2;pmr.json",
    )
    _write_csv(
        output_path / f"{run_id}_public_parking.csv",
        "parking_id;lat;lon;total_spaces",
        "p1;43.6;1.44;120",
    )
    _write_csv(
        output_path / f"{run_id}_park_and_ride.csv",
        "parking_id;lat;lon;park_and_ride_spaces",
        "pnr1;43.6;1.44;80",
    )

    resources = _build_resources(output_path, run_id)

    assert "WalkOperator" in resources
    assert "Carsharing" in resources
    assert "Carpooling" in resources
    assert "Taxi" in resources
    assert "PMR" in resources
    assert "Parking" in resources
    assert "ParkAndRide" in resources
    assert "CarsharingOperator" not in resources

    assert resources["Carsharing"]["resources"][0]["mode"] == "Carsharing"
    assert resources["Carpooling"]["resources"][0]["capacity"] == "8"
    assert resources["Taxi"]["points"][0]["kind"] == "taxi_stand"
    assert resources["ParkAndRide"]["resources"][0]["id"] == "park_and_ride:pnr1"


def test_build_resources_loads_pt_timetables(tmp_path):
    output_path = Path(tmp_path)
    run_id = "run_tt"
    timetables_dir = output_path / "timetables_run"
    monday = timetables_dir / "monday"
    monday.mkdir(parents=True)

    _write_csv(
        output_path / f"{run_id}_gtfs_routes.csv",
        "route_id;operator",
        "10;Tisseo",
    )
    _write_csv(
        output_path / f"{run_id}_gtfs_stops.csv",
        "stop_id;stop_lat;stop_lon;operator",
        "s1;43.6;1.44;Tisseo",
    )
    payload = [["abc123def456", "line:10", 0, [480, 510, 540]]]
    (monday / "TisseoOperator.json").write_text(json.dumps(payload), encoding="utf-8")

    resources = _build_resources(
        output_path,
        run_id,
        timetables_dir=timetables_dir,
        timetables_weekday="monday",
    )

    assert resources["TisseoOperator"]["timetables"] == payload
    assert not (timetables_dir / "tuesday" / "TisseoOperator.json").is_file()


def test_resolve_timetable_settings_from_config_template():
    from backend.app.services.constants import CONFIG_TEMPLATE

    with CONFIG_TEMPLATE.open("r", encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle) or {}
    config = cfg.get("config") or {}
    raw_path = config.get("timetables_path")
    if raw_path is None or str(raw_path).strip() in {"", "null", "None"}:
        pytest.skip("timetables_path not configured")

    path, weekday = _resolve_timetable_settings(None)
    assert weekday == str(config.get("timetables_weekday", "monday")).strip().lower() or "monday"
    assert path is not None
    assert path.name == Path(str(raw_path)).name


def test_pack_scenario_zip_splits_demand_and_operators(tmp_path):
    output_path = Path(tmp_path)
    run_id = "run_zip"
    timetables_dir = output_path / "timetables_run"
    monday = timetables_dir / "monday"
    monday.mkdir(parents=True)

    _write_csv(
        output_path / f"{run_id}_gtfs_routes.csv",
        "route_id;operator",
        "10;Tisseo",
    )
    _write_csv(
        output_path / f"{run_id}_gtfs_stops.csv",
        "stop_id;stop_lat;stop_lon;operator",
        "s1;43.6;1.44;Tisseo",
    )
    _write_csv(
        output_path / f"{run_id}_carsharing_stations.csv",
        "station_id;lat;lon;capacity",
        "s1;43.6;1.44;2",
    )
    payload = [["abc123def456", "line:10", 0, [480, 510]]]
    (monday / "TisseoOperator.json").write_text(json.dumps(payload), encoding="utf-8")

    resources = _build_resources(
        output_path,
        run_id,
        timetables_dir=timetables_dir,
        timetables_weekday="monday",
        include_timetables=False,
    )
    demand = {
        "persons": [{"person_id": "1"}],
        "requests": [],
        "persons_without_requests": ["1"],
        "profiles_path": "/tmp/profiles.yml",
    }

    zip_bytes, filename = pack_scenario_zip_bytes(
        demand,
        resources,
        run_id=run_id,
        timetables_dir=timetables_dir,
        timetables_weekday="monday",
    )
    assert filename == f"{run_id}_scenario.zip"

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        names = set(zf.namelist())
        assert "scenario.json" in names
        assert "operators/TisseoOperator.json" in names
        assert "operators/WalkOperator.json" in names
        assert "operators/Carsharing.json" in names

        scenario = json.loads(zf.read("scenario.json"))
        assert "resources" not in scenario
        assert scenario["persons"] == [{"person_id": "1"}]
        assert scenario["persons_without_requests"] == ["1"]

        tisseo = json.loads(zf.read("operators/TisseoOperator.json"))
        assert tisseo["timetables"] == payload
        assert tisseo["resources"][0]["id"] == "line:10"

        carsharing = json.loads(zf.read("operators/Carsharing.json"))
        assert carsharing["timetables"] == []
