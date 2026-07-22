from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import pandas as pd

WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from backend.app.services.baseline_service import resolve_baseline_directory  # noqa: E402


def load_route_meta(baseline_dir: Path) -> dict[str, dict[str, str]]:
    routes_path = baseline_dir / f"{baseline_dir.name}_gtfs_routes.csv"
    if not routes_path.is_file():
        raise FileNotFoundError(f"Missing baseline routes CSV: {routes_path}")
    routes = pd.read_csv(routes_path, sep=";", dtype=str)
    return {
        str(row.route_id): {
            "operator": row.get("operator") or "",
            "route_short_name": row.get("route_short_name") or "",
            "route_long_name": row.get("route_long_name") or "",
            "route_type": row.get("route_type") or "",
            "mode": row.get("mode") or "",
        }
        for _, row in routes.iterrows()
    }


def resolve_route_meta(line_id: str, meta: dict[str, dict[str, str]]) -> tuple[str, dict[str, str]]:
    route_id = line_id[len("line:") :] if line_id.startswith("line:") else line_id
    info = meta.get(route_id)
    if info is None and route_id.startswith("line:"):
        route_id = route_id[len("line:") :]
        info = meta.get(route_id)
    if info is None:
        info = {
            "operator": "",
            "route_short_name": "",
            "route_long_name": "",
            "route_type": "",
            "mode": "",
        }
    return route_id, info


def collect_rows(run_dir: Path, meta: dict[str, dict[str, str]]) -> list[dict]:
    rows: list[dict] = []
    for weekday in WEEKDAYS:
        day_dir = run_dir / weekday
        if not day_dir.is_dir():
            continue
        for path in sorted(day_dir.glob("*.json")):
            if path.name in {
                "generation_stats.json",
                "validation_skeleton.json",
                "validation_report.json",
            }:
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                continue
            by_line: dict[str, dict] = {}
            for entry in payload:
                if not isinstance(entry, dict):
                    continue
                line_id = str(entry.get("line_id", ""))
                if not line_id:
                    continue
                bucket = by_line.setdefault(
                    line_id,
                    {"patterns": 0, "stop_slots": 0, "trips": 0, "departure_events": 0},
                )
                for pattern in entry.get("patterns") or []:
                    if not isinstance(pattern, dict):
                        continue
                    stops = pattern.get("stops") or []
                    trips = pattern.get("trips") or []
                    bucket["patterns"] += 1
                    bucket["stop_slots"] += len(stops)
                    for trip in trips:
                        if not isinstance(trip, dict):
                            continue
                        times = trip.get("departure_times") or []
                        if not isinstance(times, list):
                            continue
                        bucket["trips"] += 1
                        bucket["departure_events"] += len(times)

            for line_id, agg in sorted(by_line.items()):
                route_id, info = resolve_route_meta(line_id, meta)
                rows.append(
                    {
                        "weekday": weekday,
                        "operator_file": path.stem,
                        "operator": info["operator"],
                        "route_id": route_id,
                        "line_id": line_id,
                        "route_short_name": info["route_short_name"],
                        "route_long_name": info["route_long_name"],
                        "route_type": info["route_type"],
                        "mode": info["mode"],
                        "patterns": agg["patterns"],
                        "stop_slots": agg["stop_slots"],
                        "trips": agg["trips"],
                        "departure_events": agg["departure_events"],
                    }
                )
    return rows


def write_detail_csv(path: Path, rows: list[dict]) -> None:
    fieldnames = [
        "weekday",
        "operator_file",
        "operator",
        "route_id",
        "line_id",
        "route_short_name",
        "route_long_name",
        "route_type",
        "mode",
        "patterns",
        "stop_slots",
        "trips",
        "departure_events",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_summary_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "weekday",
                    "operator_file",
                    "operator",
                    "lines",
                    "patterns",
                    "stop_slots",
                    "trips",
                    "departure_events",
                ],
            )
            writer.writeheader()
        return

    df = pd.DataFrame(rows)
    summary_rows: list[dict] = []
    for weekday in WEEKDAYS:
        day = df[df["weekday"] == weekday]
        if len(day) == 0:
            continue
        summary_rows.append(
            {
                "weekday": weekday,
                "operator_file": "(all)",
                "operator": "(all)",
                "lines": int(day["route_id"].nunique()),
                "patterns": int(day["patterns"].sum()),
                "stop_slots": int(day["stop_slots"].sum()),
                "trips": int(day["trips"].sum()),
                "departure_events": int(day["departure_events"].sum()),
            }
        )
        for (op_file, op), group in day.groupby(["operator_file", "operator"], dropna=False):
            summary_rows.append(
                {
                    "weekday": weekday,
                    "operator_file": op_file,
                    "operator": op,
                    "lines": int(group["route_id"].nunique()),
                    "patterns": int(group["patterns"].sum()),
                    "stop_slots": int(group["stop_slots"].sum()),
                    "trips": int(group["trips"].sum()),
                    "departure_events": int(group["departure_events"].sum()),
                }
            )

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "weekday",
                "operator_file",
                "operator",
                "lines",
                "patterns",
                "stop_slots",
                "trips",
                "departure_events",
            ],
        )
        writer.writeheader()
        writer.writerows(summary_rows)


def export_lines_csvs(
    run_dir: Path,
    baseline_dir: Path,
    output_dir: Path | None = None,
) -> tuple[Path, Path]:
    if not run_dir.is_dir():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    out = output_dir or run_dir
    out.mkdir(parents=True, exist_ok=True)

    meta = load_route_meta(baseline_dir)
    rows = collect_rows(run_dir, meta)

    detail_path = out / "lines_by_weekday.csv"
    summary_path = out / "lines_by_weekday_summary.csv"
    write_detail_csv(detail_path, rows)
    write_summary_csv(summary_path, rows)

    print(f"wrote {detail_path} ({len(rows)} rows)")
    print(f"wrote {summary_path}")
    if rows:
        df = pd.DataFrame(rows)
        print("lines per weekday:")
        for weekday in WEEKDAYS:
            n = int(df[df["weekday"] == weekday]["route_id"].nunique())
            if n:
                print(f"  {weekday}: {n}")
    return detail_path, summary_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export per-weekday line coverage CSVs from a GTFS timetable run folder"
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        required=True,
        help="Timetable run folder (e.g. data/gtfs_occitanie/timetables/20260717_123612)",
    )
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=None,
        help="Defaults to baseline_run_path / baseline_run_id in config_occitanie.yml",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Where to write CSVs (default: --run-dir)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    baseline_dir = resolve_baseline_directory(args.baseline_dir)
    export_lines_csvs(args.run_dir, baseline_dir, args.output_dir)


if __name__ == "__main__":
    main()
