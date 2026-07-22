from __future__ import annotations

import json
import zipfile
from collections import defaultdict
from io import BytesIO
from pathlib import Path

import pandas as pd

from data.gtfs.build_timetables import (
    OperatorTimetableAccum,
    build_feed_route_map,
    build_point_lookup_by_operator,
    build_route_lookup,
    hash_point,
    load_baseline_lookups,
    normalize_operator_id,
    process_feed,
    strip_merge_suffix,
    write_operator_files,
)


def _write_gtfs_zip(path: Path, tables: dict[str, pd.DataFrame]) -> None:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, frame in tables.items():
            zf.writestr(name, frame.to_csv(index=False))
    path.write_bytes(buffer.getvalue())


def _empty_feed_stats() -> dict:
    return {
        "feeds_no_service": [],
        "feeds_missing_tables": [],
        "feeds_no_matching_trips": [],
        "feeds_no_departures": [],
        "feed_rows": [],
    }


def test_strip_merge_suffix():
    assert strip_merge_suffix("10_m5") == "10"
    assert strip_merge_suffix("101_m2") == "101"
    assert strip_merge_suffix("line:10") == "line:10"


def test_normalize_operator_id_folds_accents():
    assert normalize_operator_id("Sankéo") == "SankeoOperator"
    assert normalize_operator_id("Sankeo") == "SankeoOperator"
    assert normalize_operator_id("Tisséo") == "TisseoOperator"


def test_build_feed_route_map_matches_merged_baseline_ids(tmp_path):
    baseline_dir = Path(tmp_path) / "baseline_occitanie_test"
    baseline_dir.mkdir()
    pd.DataFrame(
        [
            {"route_id": "10", "operator": "TANGO"},
            {"route_id": "10_m5", "operator": "TAM"},
        ]
    ).to_csv(baseline_dir / "baseline_occitanie_test_gtfs_routes.csv", sep=";", index=False)
    pd.DataFrame(
        [{"stop_id": "s1", "stop_lat": "43.6", "stop_lon": "1.44", "operator": "TAM"}]
    ).to_csv(baseline_dir / "baseline_occitanie_test_gtfs_stops.csv", sep=";", index=False)

    _, route_by_id = load_baseline_lookups(baseline_dir)
    route_lookup = build_route_lookup(route_by_id)

    tam_zip = Path(tmp_path) / "TAM_MMM_GTFS.zip"
    _write_gtfs_zip(
        tam_zip,
        {
            "agency.txt": pd.DataFrame([{"agency_name": "TAM", "agency_id": "TAM"}]),
            "routes.txt": pd.DataFrame([{"route_id": "10", "route_short_name": "10"}]),
        },
    )

    tango_zip = Path(tmp_path) / "gtfs-production.zip"
    _write_gtfs_zip(
        tango_zip,
        {
            "agency.txt": pd.DataFrame([{"agency_name": "TANGO", "agency_id": "generic"}]),
            "routes.txt": pd.DataFrame([{"route_id": "10", "route_short_name": "10"}]),
        },
    )

    tam_map = build_feed_route_map(tam_zip, route_by_id, route_lookup)
    tango_map = build_feed_route_map(tango_zip, route_by_id, route_lookup)

    assert tam_map == {"10": "10_m5"}
    assert tango_map == {"10": "10"}


def test_process_feed_groups_trips_by_ordered_stop_pattern(tmp_path):
    baseline_dir = Path(tmp_path) / "baseline_occitanie_test"
    baseline_dir.mkdir()
    pd.DataFrame(
        [{"route_id": "10", "operator": "Tisseo"}]
    ).to_csv(baseline_dir / "baseline_occitanie_test_gtfs_routes.csv", sep=";", index=False)
    pd.DataFrame(
        [
            {"stop_id": "A", "stop_lat": "43.60", "stop_lon": "1.40", "operator": "Tisseo"},
            {"stop_id": "B", "stop_lat": "43.61", "stop_lon": "1.41", "operator": "Tisseo"},
            {"stop_id": "C", "stop_lat": "43.62", "stop_lon": "1.42", "operator": "Tisseo"},
            {"stop_id": "D", "stop_lat": "43.63", "stop_lon": "1.43", "operator": "Tisseo"},
        ]
    ).to_csv(baseline_dir / "baseline_occitanie_test_gtfs_stops.csv", sep=";", index=False)

    stop_by_id, route_by_id = load_baseline_lookups(baseline_dir)
    route_lookup = build_route_lookup(route_by_id)
    point_lookup = build_point_lookup_by_operator(stop_by_id)

    gtfs_zip = Path(tmp_path) / "Tisseo.zip"
    _write_gtfs_zip(
        gtfs_zip,
        {
            "agency.txt": pd.DataFrame([{"agency_name": "Tisseo", "agency_id": "Tisseo"}]),
            "routes.txt": pd.DataFrame([{"route_id": "10", "route_short_name": "10"}]),
            "calendar.txt": pd.DataFrame(
                [
                    {
                        "service_id": "weekday",
                        "monday": "1",
                        "tuesday": "1",
                        "wednesday": "1",
                        "thursday": "1",
                        "friday": "1",
                        "saturday": "0",
                        "sunday": "0",
                        "start_date": "20260101",
                        "end_date": "20261231",
                    }
                ]
            ),
            "trips.txt": pd.DataFrame(
                [
                    {"route_id": "10", "service_id": "weekday", "trip_id": "t1", "direction_id": "0"},
                    {"route_id": "10", "service_id": "weekday", "trip_id": "t2", "direction_id": "0"},
                    {"route_id": "10", "service_id": "weekday", "trip_id": "t3", "direction_id": "1"},
                ]
            ),
            "stop_times.txt": pd.DataFrame(
                [
                    {"trip_id": "t1", "stop_id": "A", "stop_sequence": "1", "departure_time": "08:00:00"},
                    {"trip_id": "t1", "stop_id": "B", "stop_sequence": "2", "departure_time": "08:08:00"},
                    {"trip_id": "t1", "stop_id": "C", "stop_sequence": "3", "departure_time": "08:15:00"},
                    {"trip_id": "t2", "stop_id": "A", "stop_sequence": "1", "departure_time": "08:10:00"},
                    {"trip_id": "t2", "stop_id": "B", "stop_sequence": "2", "departure_time": "08:18:00"},
                    {"trip_id": "t2", "stop_id": "C", "stop_sequence": "3", "departure_time": "08:25:00"},
                    {"trip_id": "t3", "stop_id": "D", "stop_sequence": "1", "departure_time": "09:00:00"},
                    {"trip_id": "t3", "stop_id": "C", "stop_sequence": "2", "departure_time": "09:07:00"},
                    {"trip_id": "t3", "stop_id": "B", "stop_sequence": "3", "departure_time": "09:14:00"},
                    {"trip_id": "t3", "stop_id": "A", "stop_sequence": "4", "departure_time": "09:21:00"},
                ]
            ),
        },
    )

    accum: OperatorTimetableAccum = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    process_feed(
        gtfs_zip,
        stop_by_id,
        route_by_id,
        route_lookup,
        "monday",
        0,
        accum,
        _empty_feed_stats(),
        point_lookup=point_lookup,
    )

    out_dir = Path(tmp_path) / "monday"
    write_operator_files(out_dir, accum)
    payload = json.loads((out_dir / "TisseoOperator.json").read_text(encoding="utf-8"))

    assert len(payload) == 1
    line = payload[0]
    assert line["line_id"] == "line:10"
    assert len(line["patterns"]) == 2

    forward = line["patterns"][0]
    reverse = line["patterns"][1]
    point_a = hash_point(43.60, 1.40, "stop:TisseoOperator")
    point_b = hash_point(43.61, 1.41, "stop:TisseoOperator")
    point_c = hash_point(43.62, 1.42, "stop:TisseoOperator")
    point_d = hash_point(43.63, 1.43, "stop:TisseoOperator")

    assert forward["stops"] == [point_a, point_b, point_c]
    assert reverse["stops"] == [point_d, point_c, point_b, point_a]
    assert forward["trips"] == [
        {"passage_times": [480, 488, 495]},
        {"passage_times": [490, 498, 505]},
    ]
    assert reverse["trips"] == [{"passage_times": [540, 547, 554, 561]}]


def test_process_feed_clips_cross_border_trips_to_baseline_segments(tmp_path):
    baseline_dir = Path(tmp_path) / "baseline_occitanie_test"
    baseline_dir.mkdir()
    pd.DataFrame([{"route_id": "reg", "operator": "LIO"}]).to_csv(
        baseline_dir / "baseline_occitanie_test_gtfs_routes.csv", sep=";", index=False
    )
    pd.DataFrame(
        [
            {"stop_id": "A", "stop_lat": "43.60", "stop_lon": "1.40", "operator": "LIO"},
            {"stop_id": "B", "stop_lat": "43.61", "stop_lon": "1.41", "operator": "LIO"},
            {"stop_id": "C", "stop_lat": "43.62", "stop_lon": "1.42", "operator": "LIO"},
        ]
    ).to_csv(baseline_dir / "baseline_occitanie_test_gtfs_stops.csv", sep=";", index=False)

    stop_by_id, route_by_id = load_baseline_lookups(baseline_dir)
    route_lookup = build_route_lookup(route_by_id)
    point_lookup = build_point_lookup_by_operator(stop_by_id)

    gtfs_zip = Path(tmp_path) / "lio.zip"
    _write_gtfs_zip(
        gtfs_zip,
        {
            "agency.txt": pd.DataFrame([{"agency_name": "LIO", "agency_id": "LIO"}]),
            "routes.txt": pd.DataFrame([{"route_id": "reg", "route_short_name": "953"}]),
            "calendar.txt": pd.DataFrame(
                [
                    {
                        "service_id": "weekday",
                        "monday": "1",
                        "tuesday": "0",
                        "wednesday": "0",
                        "thursday": "0",
                        "friday": "0",
                        "saturday": "0",
                        "sunday": "0",
                        "start_date": "20260101",
                        "end_date": "20261231",
                    }
                ]
            ),
            "trips.txt": pd.DataFrame(
                [{"route_id": "reg", "service_id": "weekday", "trip_id": "t1"}]
            ),
            "stop_times.txt": pd.DataFrame(
                [
                    {"trip_id": "t1", "stop_id": "A", "stop_sequence": "1", "departure_time": "08:00:00"},
                    {"trip_id": "t1", "stop_id": "B", "stop_sequence": "2", "departure_time": "08:08:00"},
                    {"trip_id": "t1", "stop_id": "X_out", "stop_sequence": "3", "departure_time": "09:00:00"},
                    {"trip_id": "t1", "stop_id": "C", "stop_sequence": "4", "departure_time": "10:00:00"},
                ]
            ),
        },
    )

    accum: OperatorTimetableAccum = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    process_feed(
        gtfs_zip,
        stop_by_id,
        route_by_id,
        route_lookup,
        "monday",
        0,
        accum,
        _empty_feed_stats(),
        point_lookup=point_lookup,
    )

    out_dir = Path(tmp_path) / "monday"
    write_operator_files(out_dir, accum)
    payload = json.loads((out_dir / "lioOperator.json").read_text(encoding="utf-8"))

    point_a = hash_point(43.60, 1.40, "stop:lioOperator")
    point_b = hash_point(43.61, 1.41, "stop:lioOperator")
    point_c = hash_point(43.62, 1.42, "stop:lioOperator")

    patterns = {tuple(p["stops"]): p for line in payload for p in line["patterns"]}
    assert (point_a, point_b) in patterns
    assert (point_c,) in patterns
    assert patterns[(point_a, point_b)]["trips"] == [{"passage_times": [480, 488]}]
    assert patterns[(point_c,)]["trips"] == [{"passage_times": [600]}]
