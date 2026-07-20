from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GTFS_OCCITANIE_DIR = _REPO_ROOT / "data" / "gtfs_occitanie"
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
for path in (_REPO_ROOT, _SCRIPTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
from backend.app.services.baseline_service import resolve_baseline_directory  # noqa: E402
from export_timetable_lines_csv import export_lines_csvs  # noqa: E402

WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

DEFAULT_GTFS_DIR = _GTFS_OCCITANIE_DIR
DEFAULT_OUTPUT_DIR = _GTFS_OCCITANIE_DIR / "timetables"

REASON_NOT_IN_ANY_FEED = "route_id_not_found_in_any_gtfs_feed"
REASON_NO_SERVICE_DAY = "no_active_service_on_this_weekday"
REASON_NO_TRIPS = "has_service_but_no_trips"
REASON_NO_DEPARTURES = "has_trips_but_no_departure_times"
REASON_STOPS_NOT_IN_BASELINE = "departures_exist_but_stops_not_in_baseline"
REASON_UNKNOWN = "unknown"

MERGE_SUFFIX_RE = re.compile(r"_m\d+$")


def hash_point(lat: float, lon: float, salt: str) -> str:
    payload = f"{lat:.8f},{lon:.8f},{salt}".encode("utf-8")
    return hashlib.sha1(payload).hexdigest()[:12]


def _operator_match_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(text))
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


def normalize_operator_id(raw: Any, fallback: str = "gtfs") -> str:
    text = str(raw).strip() if raw is not None else ""
    if not text:
        text = fallback
    lowered = _operator_match_key(text)
    if "tisseo" in lowered:
        return "TisseoOperator"
    if "lio" in lowered:
        return "lioOperator"
    if "tango" in lowered:
        return "TangoOperator"
    if "tam" in lowered:
        return "TAMOperator"
    if "sncf" in lowered:
        return "SNCFOperator"
    if "sankeo" in lowered:
        return "SankeoOperator"

    text = re.sub(r"^\.+", "", text)
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in ascii_text).strip("_")
    if not cleaned:
        cleaned = fallback
    cleaned = re.sub(r"_\d+$", "", cleaned)
    return f"{cleaned}Operator"


def parse_operator_values(raw: Any, fallback: str = "gtfs") -> list[str]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return [fallback]
    if isinstance(raw, list):
        values = [str(v).strip() for v in raw if str(v).strip()]
        return values or [fallback]
    text = str(raw).strip()
    if not text:
        return [fallback]
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
        except Exception:
            try:
                parsed = ast.literal_eval(text)
            except Exception:
                parsed = None
        if isinstance(parsed, list):
            values = [str(v).strip() for v in parsed if str(v).strip()]
            return values or [fallback]
    if "|" in text:
        values = [part.strip() for part in text.split("|") if part.strip()]
        return values or [fallback]
    return [text]


def gtfs_hhmmss_to_minutes(value: Any) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) < 2:
        return None
    try:
        hours = int(parts[0])
        minutes = int(parts[1])
    except ValueError:
        return None
    return hours * 60 + minutes


def read_gtfs_table(zip_path: Path, table_name: str) -> pd.DataFrame | None:
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        match = next((n for n in names if n.endswith(table_name) or n == table_name), None)
        if match is None:
            basename = table_name.split("/")[-1]
            match = next((n for n in names if Path(n).name == basename), None)
        if match is None:
            return None
        with zf.open(match) as handle:
            try:
                return pd.read_csv(handle, dtype=str, low_memory=False)
            except UnicodeDecodeError:
                with zf.open(match) as handle2:
                    return pd.read_csv(handle2, dtype=str, encoding="latin-1", low_memory=False)


def calendar_day_columns(df_calendar: pd.DataFrame) -> list[str]:
    if len(df_calendar) == 0 or "service_id" not in df_calendar.columns:
        return []
    cols = list(df_calendar.columns)
    start = cols.index("service_id") + 1
    end = cols.index("start_date") if "start_date" in cols else min(start + 7, len(cols))
    return [column for column in cols[start:end] if column not in {"start_date", "end_date"}][:7]


def service_ids_from_calendar(df_calendar: pd.DataFrame | None, weekday: str) -> set[str]:
    if df_calendar is None or len(df_calendar) == 0:
        return set()
    day_columns = calendar_day_columns(df_calendar)
    if weekday not in day_columns:
        lowered = {c.lower(): c for c in day_columns}
        if weekday not in lowered:
            return set()
        column = lowered[weekday]
    else:
        column = weekday
    if "service_id" not in df_calendar.columns:
        return set()
    active = df_calendar[pd.to_numeric(df_calendar[column], errors="coerce").fillna(0).astype(int) == 1]
    return set(active["service_id"].astype(str))


def service_ids_from_calendar_dates(df_dates: pd.DataFrame | None, weekday_index: int) -> set[str]:
    if df_dates is None or len(df_dates) == 0 or "service_id" not in df_dates.columns:
        return set()
    if weekday_index < 0 or weekday_index > 6:
        return set()
    dates = pd.to_datetime(df_dates["date"].astype(str), format="%Y%m%d", errors="coerce")
    active = df_dates[
        dates.dt.weekday.eq(weekday_index)
        & pd.to_numeric(df_dates["exception_type"], errors="coerce").fillna(0).astype(int).eq(1)
    ]
    return set(active["service_id"].astype(str))


def service_ids_for_weekday(
    df_calendar: pd.DataFrame | None,
    df_dates: pd.DataFrame | None,
    weekday: str,
    weekday_index: int,
) -> set[str]:
    from_calendar = service_ids_from_calendar(df_calendar, weekday)
    if from_calendar:
        return from_calendar
    return service_ids_from_calendar_dates(df_dates, weekday_index)


def load_baseline_lookups(baseline_dir: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    run_id = baseline_dir.name
    stops_path = baseline_dir / f"{run_id}_gtfs_stops.csv"
    routes_path = baseline_dir / f"{run_id}_gtfs_routes.csv"
    if not stops_path.is_file() or not routes_path.is_file():
        raise FileNotFoundError(f"Missing baseline GTFS CSVs under {baseline_dir}")

    df_stops = pd.read_csv(stops_path, sep=";", dtype=str, low_memory=False)
    df_routes = pd.read_csv(routes_path, sep=";", dtype=str, low_memory=False)

    stop_by_id: dict[str, dict[str, Any]] = {}
    for _, row in df_stops.dropna(subset=["stop_id", "stop_lat", "stop_lon"]).iterrows():
        stop_id = str(row["stop_id"]).strip()
        if not stop_id:
            continue
        try:
            lat = float(row["stop_lat"])
            lon = float(row["stop_lon"])
        except (TypeError, ValueError):
            continue
        operators = parse_operator_values(row.get("operator"), "gtfs")
        operator_ids = [normalize_operator_id(name) for name in operators]
        point_ids = {op_id: hash_point(lat, lon, f"stop:{op_id}") for op_id in operator_ids}
        stop_by_id[stop_id] = {
            "lat": lat,
            "lon": lon,
            "operator_ids": operator_ids,
            "point_ids": point_ids,
        }

    route_by_id: dict[str, dict[str, Any]] = {}
    for _, row in df_routes.dropna(subset=["route_id"]).iterrows():
        route_id = str(row["route_id"]).strip()
        if not route_id:
            continue
        operator_name = parse_operator_values(row.get("operator"), "gtfs")[0]
        operator_id = normalize_operator_id(operator_name)
        route_by_id[route_id] = {
            "operator_id": operator_id,
            "line_id": f"line:{route_id}",
        }

    return stop_by_id, route_by_id


def strip_merge_suffix(route_id: str) -> str:
    return MERGE_SUFFIX_RE.sub("", str(route_id).strip())


def build_route_lookup(route_by_id: dict[str, dict[str, Any]]) -> dict[tuple[str, str], str]:
    lookup: dict[tuple[str, str], str] = {}
    for baseline_id, meta in route_by_id.items():
        lookup[(strip_merge_suffix(baseline_id), meta["operator_id"])] = baseline_id
    return lookup


def infer_feed_operator_ids(zip_path: Path) -> set[str]:
    operator_ids: set[str] = set()
    df_agency = read_gtfs_table(zip_path, "agency.txt")
    if df_agency is not None:
        for column in ("agency_name", "agency_id", "agency_url"):
            if column not in df_agency.columns:
                continue
            for value in df_agency[column].dropna().astype(str):
                text = value.strip()
                if text:
                    operator_ids.add(normalize_operator_id(text))
    operator_ids.add(normalize_operator_id(zip_path.stem.replace("_", " ")))
    return operator_ids


def resolve_baseline_route_id(
    raw_route_id: str,
    route_by_id: dict[str, dict[str, Any]],
    route_lookup: dict[tuple[str, str], str],
    feed_operator_ids: set[str],
) -> str | None:
    raw_route_id = str(raw_route_id).strip()
    if not raw_route_id:
        return None

    if raw_route_id in route_by_id:
        if route_by_id[raw_route_id]["operator_id"] in feed_operator_ids:
            return raw_route_id

    matches = {
        route_lookup[(raw_route_id, operator_id)]
        for operator_id in feed_operator_ids
        if (raw_route_id, operator_id) in route_lookup
    }
    if len(matches) == 1:
        return next(iter(matches))
    if len(matches) > 1:
        return sorted(matches)[0]
    return None


def build_feed_route_map(
    zip_path: Path,
    route_by_id: dict[str, dict[str, Any]],
    route_lookup: dict[tuple[str, str], str],
) -> dict[str, str]:
    feed_operator_ids = infer_feed_operator_ids(zip_path)
    df_routes = read_gtfs_table(zip_path, "routes.txt")
    if df_routes is None or "route_id" not in df_routes.columns:
        return {}

    raw_to_baseline: dict[str, str] = {}
    for raw_id in df_routes["route_id"].astype(str):
        baseline_id = resolve_baseline_route_id(raw_id, route_by_id, route_lookup, feed_operator_ids)
        if baseline_id is not None:
            raw_to_baseline[raw_id] = baseline_id
    return raw_to_baseline


def expand_frequency_departures(
    trip_stop_times: pd.DataFrame,
    df_frequencies: pd.DataFrame,
) -> list[tuple[str, int]]:
    if len(trip_stop_times) == 0 or len(df_frequencies) == 0:
        return []

    times = trip_stop_times.copy()
    times["dep_min"] = times["departure_time"].map(gtfs_hhmmss_to_minutes)
    times = times.dropna(subset=["dep_min", "stop_id"])
    if len(times) == 0:
        return []

    if "stop_sequence" in times.columns:
        times["_seq"] = pd.to_numeric(times["stop_sequence"], errors="coerce")
        times = times.sort_values("_seq", kind="mergesort")
    base = int(times["dep_min"].iloc[0])
    offsets = [(str(row["stop_id"]), int(row["dep_min"]) - base) for _, row in times.iterrows()]

    expanded: list[tuple[str, int]] = []
    for _, freq in df_frequencies.iterrows():
        start = gtfs_hhmmss_to_minutes(freq.get("start_time"))
        end = gtfs_hhmmss_to_minutes(freq.get("end_time"))
        try:
            headway = int(float(str(freq.get("headway_secs", "0")).strip() or "0"))
        except (TypeError, ValueError):
            continue
        if start is None or end is None or headway <= 0:
            continue
        t_sec = start * 60
        end_sec = end * 60
        while t_sec < end_sec:
            trip_start_min = t_sec // 60
            for stop_id, offset in offsets:
                expanded.append((stop_id, int(trip_start_min + offset)))
            t_sec += headway
    return expanded


def parse_direction_id(value: Any) -> int:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0
    text = str(value).strip()
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def process_feed(
    zip_path: Path,
    stop_by_id: dict[str, dict[str, Any]],
    route_by_id: dict[str, dict[str, Any]],
    route_lookup: dict[tuple[str, str], str],
    weekday: str,
    weekday_index: int,
    accum: dict[str, dict[tuple[str, str, int], set[int]]],
    stats: dict[str, Any],
) -> None:
    feed_route_map = build_feed_route_map(zip_path, route_by_id, route_lookup)
    df_calendar = read_gtfs_table(zip_path, "calendar.txt")
    df_dates = read_gtfs_table(zip_path, "calendar_dates.txt")
    service_ids = service_ids_for_weekday(df_calendar, df_dates, weekday, weekday_index)
    if not service_ids:
        stats["feeds_no_service"].append(zip_path.name)
        return

    df_trips = read_gtfs_table(zip_path, "trips.txt")
    df_stop_times = read_gtfs_table(zip_path, "stop_times.txt")
    if df_trips is None or df_stop_times is None:
        stats["feeds_missing_tables"].append(zip_path.name)
        return
    if not {"trip_id", "route_id", "service_id"}.issubset(df_trips.columns):
        stats["feeds_missing_tables"].append(zip_path.name)
        return
    if not {"trip_id", "stop_id"}.issubset(df_stop_times.columns):
        stats["feeds_missing_tables"].append(zip_path.name)
        return

    df_trips = df_trips.copy()
    df_trips["trip_id"] = df_trips["trip_id"].astype(str)
    df_trips["route_id"] = df_trips["route_id"].astype(str)
    df_trips["service_id"] = df_trips["service_id"].astype(str)
    if "direction_id" in df_trips.columns:
        df_trips["direction_id"] = df_trips["direction_id"].map(parse_direction_id)
    else:
        df_trips["direction_id"] = 0

    df_trips["baseline_route_id"] = df_trips["route_id"].map(feed_route_map)
    df_trips = df_trips[df_trips["service_id"].isin(service_ids) & df_trips["baseline_route_id"].notna()]
    if len(df_trips) == 0:
        stats["feeds_no_matching_trips"].append(zip_path.name)
        return

    trip_to_route = dict(zip(df_trips["trip_id"], df_trips["baseline_route_id"].astype(str)))
    trip_to_direction = dict(zip(df_trips["trip_id"], df_trips["direction_id"].astype(int)))
    active_trip_ids = set(trip_to_route.keys())

    df_stop_times = df_stop_times.copy()
    df_stop_times["trip_id"] = df_stop_times["trip_id"].astype(str)
    df_stop_times["stop_id"] = df_stop_times["stop_id"].astype(str)
    df_stop_times = df_stop_times[df_stop_times["trip_id"].isin(active_trip_ids)]
    if "departure_time" not in df_stop_times.columns:
        stats["feeds_no_departures"].append(zip_path.name)
        return

    df_frequencies = read_gtfs_table(zip_path, "frequencies.txt")
    frequency_trip_ids: set[str] = set()
    if df_frequencies is not None and len(df_frequencies) > 0 and "trip_id" in df_frequencies.columns:
        df_frequencies = df_frequencies.copy()
        df_frequencies["trip_id"] = df_frequencies["trip_id"].astype(str)
        frequency_trip_ids = set(df_frequencies["trip_id"]) & active_trip_ids

    # Frequency trips are expanded separately from fixed stop_times
    fixed = df_stop_times[~df_stop_times["trip_id"].isin(frequency_trip_ids)].copy()
    fixed["dep_min"] = fixed["departure_time"].map(gtfs_hhmmss_to_minutes)
    fixed = fixed.dropna(subset=["dep_min"])

    rows: list[tuple[str, str, int, int]] = []  # route_id, stop_id, direction, minutes
    if len(fixed) > 0:
        fixed["route_id"] = fixed["trip_id"].map(trip_to_route)
        fixed["direction_id"] = fixed["trip_id"].map(trip_to_direction).fillna(0).astype(int)
        for route_id, stop_id, direction, minutes in zip(
            fixed["route_id"].astype(str),
            fixed["stop_id"].astype(str),
            fixed["direction_id"].astype(int),
            fixed["dep_min"].astype(int),
        ):
            rows.append((route_id, stop_id, int(direction), minutes))

    if frequency_trip_ids and df_frequencies is not None:
        for trip_id in frequency_trip_ids:
            trip_times = df_stop_times[df_stop_times["trip_id"] == trip_id]
            trip_freqs = df_frequencies[df_frequencies["trip_id"] == trip_id]
            route_id = trip_to_route.get(trip_id)
            if route_id is None:
                continue
            direction = int(trip_to_direction.get(trip_id, 0))
            for stop_id, minutes in expand_frequency_departures(trip_times, trip_freqs):
                rows.append((route_id, stop_id, direction, minutes))

    matched = 0
    skipped_unknown_stop = 0
    skipped_operator_mismatch = 0
    for route_id, stop_id, direction, minutes in rows:
        route_meta = route_by_id.get(route_id)
        stop_meta = stop_by_id.get(stop_id)
        if route_meta is None:
            continue
        if stop_meta is None:
            skipped_unknown_stop += 1
            continue
        operator_id = route_meta["operator_id"]
        line_id = route_meta["line_id"]
        point_id = stop_meta["point_ids"].get(operator_id)
        if point_id is None:
            if operator_id not in stop_meta["operator_ids"]:
                skipped_operator_mismatch += 1
            point_id = hash_point(stop_meta["lat"], stop_meta["lon"], f"stop:{operator_id}")
        key = (point_id, line_id, int(direction))
        accum[operator_id][key].add(int(minutes))
        matched += 1

    stats["feed_rows"].append(
        {
            "feed": zip_path.name,
            "weekday": weekday,
            "active_services": len(service_ids),
            "active_trips": len(active_trip_ids),
            "departure_rows": len(rows),
            "matched": matched,
            "skipped_unknown_stop": skipped_unknown_stop,
            "skipped_operator_mismatch": skipped_operator_mismatch,
            "frequency_trips": len(frequency_trip_ids),
        }
    )


def write_operator_files(
    output_day_dir: Path,
    accum: dict[str, dict[tuple[str, str, int], set[int]]],
) -> dict[str, int]:
    output_day_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for operator_id, entries in sorted(accum.items()):
        payload = [
            [point_id, line_id, direction, sorted(times)]
            for (point_id, line_id, direction), times in sorted(
                entries.items(),
                key=lambda item: (item[0][1], item[0][2], item[0][0]),
            )
            if times
        ]
        path = output_day_dir / f"{operator_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        counts[operator_id] = len(payload)
    return counts


def build_validation_skeleton(
    route_by_id: dict[str, dict[str, Any]],
    per_weekday_lines: dict[str, set[str]],
) -> dict[str, Any]:
    all_routes = set(route_by_id.keys())
    report: dict[str, Any] = {"weekdays": {}}
    for weekday, present in per_weekday_lines.items():
        missing = sorted(all_routes - present)
        report["weekdays"][weekday] = {
            "baseline_routes": len(all_routes),
            "routes_with_departures": len(present),
            "routes_with_zero_departures": len(missing),
            "zero_departure_route_ids": missing,
        }
    return report


def load_timetable_route_ids(day_dir: Path) -> set[str]:
    route_ids: set[str] = set()
    if not day_dir.is_dir():
        return route_ids
    for path in day_dir.glob("*.json"):
        if path.name in {"generation_stats.json", "validation_skeleton.json", "validation_report.json"}:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for entry in payload:
            if not isinstance(entry, list) or len(entry) < 2:
                continue
            line_id = str(entry[1])
            if line_id.startswith("line:"):
                route_ids.add(line_id[len("line:") :])
    return route_ids


def classify_routes_for_weekday(
    weekday: str,
    weekday_index: int,
    missing_routes: set[str],
    baseline_stop_ids: set[str],
    zip_paths: list[Path],
    route_by_id: dict[str, dict[str, Any]],
    route_lookup: dict[tuple[str, str], str],
) -> dict[str, str]:
    # Prefer more specific reasons when a route appears in multiple feeds
    rank = {
        REASON_UNKNOWN: 0,
        REASON_STOPS_NOT_IN_BASELINE: 1,
        REASON_NO_DEPARTURES: 2,
        REASON_NO_TRIPS: 3,
        REASON_NO_SERVICE_DAY: 4,
        REASON_NOT_IN_ANY_FEED: 5,
    }
    best: dict[str, str] = {route_id: REASON_NOT_IN_ANY_FEED for route_id in missing_routes}

    def improve(route_id: str, reason: str) -> None:
        if route_id not in best:
            return
        if rank[reason] < rank[best[route_id]]:
            best[route_id] = reason

    for zip_path in zip_paths:
        print(f"  scanning {zip_path.name} ...", flush=True)
        feed_route_map = build_feed_route_map(zip_path, route_by_id, route_lookup)
        feed_missing = set(feed_route_map.values()) & missing_routes
        if not feed_missing:
            continue

        for baseline_route_id in feed_missing:
            improve(baseline_route_id, REASON_NO_SERVICE_DAY)

        df_calendar = read_gtfs_table(zip_path, "calendar.txt")
        df_dates = read_gtfs_table(zip_path, "calendar_dates.txt")
        service_ids = service_ids_for_weekday(df_calendar, df_dates, weekday, weekday_index)
        if not service_ids:
            continue

        df_trips = read_gtfs_table(zip_path, "trips.txt")
        if df_trips is None or not {"trip_id", "route_id", "service_id"}.issubset(df_trips.columns):
            continue
        trips = df_trips[df_trips["service_id"].astype(str).isin(service_ids)].copy()
        trips["baseline_route_id"] = trips["route_id"].astype(str).map(feed_route_map)
        trips = trips[trips["baseline_route_id"].notna() & trips["baseline_route_id"].isin(missing_routes)]
        if len(trips) == 0:
            continue
        trips["trip_id"] = trips["trip_id"].astype(str)
        trips["baseline_route_id"] = trips["baseline_route_id"].astype(str)
        for baseline_route_id in set(trips["baseline_route_id"]):
            improve(baseline_route_id, REASON_NO_DEPARTURES)

        trip_to_route = dict(zip(trips["trip_id"], trips["baseline_route_id"]))
        active_trip_ids = set(trip_to_route.keys())

        routes_with_deps: set[str] = set()
        routes_with_baseline_stop: set[str] = set()
        df_stop_times = read_gtfs_table(zip_path, "stop_times.txt")
        if df_stop_times is not None and {"trip_id", "stop_id"}.issubset(df_stop_times.columns):
            times = df_stop_times[df_stop_times["trip_id"].astype(str).isin(active_trip_ids)].copy()
            if "departure_time" in times.columns:
                times = times[times["departure_time"].astype(str).str.strip().ne("")]
            if len(times) > 0:
                times["trip_id"] = times["trip_id"].astype(str)
                times["stop_id"] = times["stop_id"].astype(str)
                times["baseline_route_id"] = times["trip_id"].map(trip_to_route)
                routes_with_deps |= set(times["baseline_route_id"].dropna().astype(str))
                in_baseline = times[times["stop_id"].isin(baseline_stop_ids)]
                routes_with_baseline_stop |= set(in_baseline["baseline_route_id"].dropna().astype(str))

        df_freq = read_gtfs_table(zip_path, "frequencies.txt")
        if df_freq is not None and "trip_id" in df_freq.columns:
            for trip_id in set(df_freq["trip_id"].astype(str)) & active_trip_ids:
                routes_with_deps.add(trip_to_route[trip_id])

        for baseline_route_id in routes_with_deps:
            if baseline_route_id in routes_with_baseline_stop:
                improve(baseline_route_id, REASON_UNKNOWN)
            else:
                improve(baseline_route_id, REASON_STOPS_NOT_IN_BASELINE)

    return best


def validate_run(
    run_dir: Path,
    baseline_dir: Path,
    gtfs_dir: Path,
    weekdays: tuple[str, ...] = WEEKDAYS,
) -> dict:
    stop_by_id, route_by_id = load_baseline_lookups(baseline_dir)
    route_lookup = build_route_lookup(route_by_id)
    baseline_stop_ids = set(stop_by_id.keys())
    zip_paths = sorted(gtfs_dir.glob("*.zip"))
    if not zip_paths:
        raise FileNotFoundError(f"No GTFS zip files in {gtfs_dir}")

    report: dict = {
        "run_dir": str(run_dir),
        "baseline_dir": str(baseline_dir),
        "gtfs_dir": str(gtfs_dir),
        "baseline_routes": len(route_by_id),
        "weekdays": {},
    }

    weekday_index_by_name = {name: idx for idx, name in enumerate(WEEKDAYS)}
    for weekday in weekdays:
        weekday_index = weekday_index_by_name[weekday]
        print(f"\n=== {weekday} ===")
        present = load_timetable_route_ids(run_dir / weekday)
        missing = set(route_by_id.keys()) - present
        print(f"  with departures: {len(present)}  zero: {len(missing)}")

        reasons_by_route = classify_routes_for_weekday(
            weekday,
            weekday_index,
            missing,
            baseline_stop_ids,
            zip_paths,
            route_by_id,
            route_lookup,
        )
        reasons: dict[str, list[str]] = defaultdict(list)
        reason_counts: Counter[str] = Counter()
        for route_id, reason in reasons_by_route.items():
            reasons[reason].append(route_id)
            reason_counts[reason] += 1

        report["weekdays"][weekday] = {
            "routes_with_departures": len(present),
            "routes_with_zero_departures": len(missing),
            "reason_counts": dict(reason_counts),
            "routes_by_reason": {k: sorted(v) for k, v in sorted(reasons.items())},
        }
        for reason, count in reason_counts.most_common():
            print(f"  {reason}: {count}")

    out_path = run_dir / "validation_report.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {out_path}")
    return report


def generate(
    gtfs_dir: Path,
    baseline_dir: Path,
    output_dir: Path,
    timestamp: str | None = None,
    weekdays: tuple[str, ...] = WEEKDAYS,
) -> Path:
    stop_by_id, route_by_id = load_baseline_lookups(baseline_dir)
    route_lookup = build_route_lookup(route_by_id)
    zip_paths = sorted(gtfs_dir.glob("*.zip"))
    if not zip_paths:
        raise FileNotFoundError(f"No GTFS zip files in {gtfs_dir}")

    stamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_dir / stamp
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"[start] building timetables")
    print(f"  baseline: {baseline_dir}")
    print(f"  stops={len(stop_by_id)} routes={len(route_by_id)} feeds={len(zip_paths)}")
    print(f"  weekdays: {', '.join(weekdays)}")
    print(f"  output: {run_dir}")

    per_weekday_lines: dict[str, set[str]] = {day: set() for day in weekdays}
    all_stats: dict[str, Any] = {
        "baseline_dir": str(baseline_dir),
        "gtfs_dir": str(gtfs_dir),
        "timestamp": stamp,
        "baseline_stops": len(stop_by_id),
        "baseline_routes": len(route_by_id),
        "feeds": [p.name for p in zip_paths],
        "weekdays": list(weekdays),
        "days": {},
    }

    weekday_index_by_name = {name: idx for idx, name in enumerate(WEEKDAYS)}
    for weekday in weekdays:
        weekday_index = weekday_index_by_name[weekday]
        print(f"\n=== {weekday} ===")
        accum: dict[str, dict[tuple[str, str, int], set[int]]] = defaultdict(lambda: defaultdict(set))
        day_stats: dict[str, Any] = {
            "feeds_no_service": [],
            "feeds_missing_tables": [],
            "feeds_no_matching_trips": [],
            "feeds_no_departures": [],
            "feed_rows": [],
        }
        for zip_path in zip_paths:
            print(f"  {zip_path.name} ...", flush=True)
            process_feed(
                zip_path,
                stop_by_id,
                route_by_id,
                route_lookup,
                weekday,
                weekday_index,
                accum,
                day_stats,
            )

        counts = write_operator_files(run_dir / weekday, accum)
        lines_with_times: set[str] = set()
        for entries in accum.values():
            for (_point_id, line_id, _direction) in entries:
                if line_id.startswith("line:"):
                    lines_with_times.add(line_id[len("line:") :])
        per_weekday_lines[weekday] = lines_with_times

        day_stats["operators"] = counts
        day_stats["routes_with_departures"] = len(lines_with_times)
        all_stats["days"][weekday] = day_stats
        print(f"  operators: {len(counts)}  routes with times: {len(lines_with_times)}")

    validation = build_validation_skeleton(route_by_id, per_weekday_lines)
    (run_dir / "generation_stats.json").write_text(
        json.dumps(all_stats, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "validation_skeleton.json").write_text(
        json.dumps(validation, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n[done] wrote {run_dir}")
    export_lines_csvs(run_dir, baseline_dir)
    print("\n[validation]")
    validate_run(run_dir, baseline_dir, gtfs_dir, weekdays=weekdays)
    return run_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build / validate Occitanie GTFS departure timetables")
    parser.add_argument("--gtfs-dir", type=Path, default=DEFAULT_GTFS_DIR)
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=None,
        help="Defaults to baseline_run_path / baseline_run_id in config_occitanie.yml",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", type=str, default=None)
    parser.add_argument("--weekday", action="append", choices=list(WEEKDAYS))
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--run-dir", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    weekdays = tuple(args.weekday) if args.weekday else WEEKDAYS
    baseline_dir = resolve_baseline_directory(args.baseline_dir)

    if args.validate:
        if args.run_dir is None:
            raise SystemExit("--validate requires --run-dir")
        if not args.run_dir.is_dir():
            raise SystemExit(f"Run directory not found: {args.run_dir}")
        validate_run(args.run_dir, baseline_dir, args.gtfs_dir, weekdays=weekdays)
        return

    generate(args.gtfs_dir, baseline_dir, args.output_dir, args.timestamp, weekdays=weekdays)


if __name__ == "__main__":
    main()
