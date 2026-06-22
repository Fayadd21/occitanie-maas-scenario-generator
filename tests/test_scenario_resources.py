from __future__ import annotations

from pathlib import Path

from backend.app.services.job_service import _build_resources


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
