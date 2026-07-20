from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

import pandas as pd

from data.gtfs.build_timetables import (
    build_feed_route_map,
    build_route_lookup,
    normalize_operator_id,
    strip_merge_suffix,
)


def _write_gtfs_zip(path: Path, tables: dict[str, pd.DataFrame]) -> None:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, frame in tables.items():
            zf.writestr(name, frame.to_csv(index=False))
    path.write_bytes(buffer.getvalue())


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

    from data.gtfs.build_timetables import load_baseline_lookups

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
