from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import pathlib
import time
import urllib.error
import urllib.request

_BIKESHARING_DIR = pathlib.Path(__file__).resolve().parent
_STATUS_DATA_DIR = _BIKESHARING_DIR / "station_status_data"
_DEFAULT_FEEDS_CONFIG = _BIKESHARING_DIR / "station_status_feeds.json"

DEFAULT_INTERVAL_SECONDS = 900


def load_city_feeds(config_path: pathlib.Path) -> dict[str, str]:
    if not config_path.exists():
        raise RuntimeError(f"Feeds config not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Feeds config must be a JSON object: {config_path}")
    cities = payload.get("cities", payload)
    if not isinstance(cities, dict) or not cities:
        raise RuntimeError(f"Feeds config has no city URLs: {config_path}")
    out: dict[str, str] = {}
    for city, url in cities.items():
        city_key = str(city).strip().lower()
        url_text = str(url).strip()
        if not city_key or not url_text:
            raise RuntimeError(f"Invalid city feed entry in {config_path}: {city!r} -> {url!r}")
        out[city_key] = url_text
    return out

CSV_FIELDS = [
    "snapshot_ts_utc",
    "feed_last_updated",
    "station_id",
    "num_bikes_available",
    "num_docks_available",
    "is_installed",
    "is_renting",
    "is_returning",
    "is_charging_station",
    "num_bikes_disabled",
    "num_docks_disabled",
]


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def utc_stamp(ts: dt.datetime | None = None) -> str:
    if ts is None:
        ts = utc_now()
    return ts.strftime("%Y%m%dT%H%M%SZ")


def ensure_city_dirs(city_dir: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    raw_dir = city_dir / "raw"
    flat_dir = city_dir / "flat"
    raw_dir.mkdir(parents=True, exist_ok=True)
    flat_dir.mkdir(parents=True, exist_ok=True)
    return raw_dir, flat_dir


def fetch_json(url: str, timeout_seconds: int) -> dict:
    request = urllib.request.Request(
        url=url,
        headers={"User-Agent": "station-status-collector/1.0"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = response.read()
    return json.loads(payload)


def write_raw_snapshot(raw_dir: pathlib.Path, snapshot_ts: dt.datetime, payload: dict) -> pathlib.Path:
    day_dir = raw_dir / snapshot_ts.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    file_path = day_dir / f"{utc_stamp(snapshot_ts)}_station_status.json"
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    return file_path


def flatten_rows(payload: dict, snapshot_ts: dt.datetime) -> list[dict]:
    feed_last_updated = payload.get("last_updated")
    stations = payload.get("data", {}).get("stations", [])
    snapshot_label = snapshot_ts.isoformat()
    rows = []
    for station in stations:
        num_bikes_available = station.get("num_bikes_available")
        if num_bikes_available is None:
            num_bikes_available = station.get("num_vehicles_available")
        rows.append(
            {
                "snapshot_ts_utc": snapshot_label,
                "feed_last_updated": feed_last_updated,
                "station_id": station.get("station_id"),
                "num_bikes_available": num_bikes_available,
                "num_docks_available": station.get("num_docks_available"),
                "is_installed": station.get("is_installed"),
                "is_renting": station.get("is_renting"),
                "is_returning": station.get("is_returning"),
                "is_charging_station": station.get("is_charging_station"),
                "num_bikes_disabled": station.get("num_bikes_disabled"),
                "num_docks_disabled": station.get("num_docks_disabled"),
            }
        )
    return rows


def append_rows_csv(csv_path: pathlib.Path, rows: list[dict]) -> None:
    if not rows:
        return
    write_header = not csv_path.exists()
    with csv_path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def seconds_until_next_tick(interval_seconds: int) -> float:
    now = time.time()
    next_tick = ((int(now) // interval_seconds) + 1) * interval_seconds
    return max(0.0, next_tick - now)


def collect_once_for_city(root_dir: pathlib.Path, city: str, url: str, timeout_seconds: int) -> None:
    city_dir = root_dir / city
    raw_dir, flat_dir = ensure_city_dirs(city_dir)
    snapshot_ts = utc_now()
    payload = fetch_json(url, timeout_seconds)
    raw_path = write_raw_snapshot(raw_dir, snapshot_ts, payload)
    rows = flatten_rows(payload, snapshot_ts)
    csv_path = flat_dir / "station_status_history.csv"
    append_rows_csv(csv_path, rows)
    print(f"[ok] city={city} snapshot={utc_stamp(snapshot_ts)} rows={len(rows)} raw={raw_path}")


def run_loop_multi_city(
    root_dir: pathlib.Path,
    city_urls: dict[str, str],
    interval_seconds: int,
    timeout_seconds: int,
) -> None:
    print(f"[start] collecting {len(city_urls)} cities every {interval_seconds}s into {root_dir}")
    while True:
        for city, url in city_urls.items():
            try:
                collect_once_for_city(root_dir, city, url, timeout_seconds)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                print(f"[warn] city={city} fetch/parse failed: {exc}")
            except Exception as exc:  # pragma: no cover
                print(f"[warn] city={city} unexpected error: {exc}")

        sleep_seconds = seconds_until_next_tick(interval_seconds)
        time.sleep(sleep_seconds)


def parse_city_url_args(values: list[str] | None) -> dict[str, str]:
    if not values:
        return {}

    parsed = {}
    for value in values:
        if "=" not in value:
            raise RuntimeError(f"Invalid --city-url value (expected city=url): {value}")
        city, url = value.split("=", 1)
        city = city.strip().lower()
        url = url.strip()
        if not city or not url:
            raise RuntimeError(f"Invalid --city-url value (empty city or url): {value}")
        parsed[city] = url
    return parsed


def resolve_city_urls(args: argparse.Namespace) -> dict[str, str]:
    city_urls = load_city_feeds(args.feeds_config)
    city_urls.update(parse_city_url_args(args.city_url))
    if args.cities:
        wanted = {city.strip().lower() for city in args.cities if city.strip()}
        missing = sorted(wanted - set(city_urls))
        if missing:
            raise RuntimeError(f"Unknown city slug(s): {', '.join(missing)}")
        city_urls = {city: url for city, url in city_urls.items() if city in wanted}
    return city_urls


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect GBFS station_status snapshots into station_status_data/<city>/."
    )
    parser.add_argument(
        "--feeds-config",
        type=pathlib.Path,
        default=_DEFAULT_FEEDS_CONFIG,
        help="JSON file mapping city slug to GBFS station_status URL.",
    )
    parser.add_argument(
        "--base-dir",
        type=pathlib.Path,
        default=_STATUS_DATA_DIR,
        help="Root directory for per-city folders (default: station_status_data/).",
    )
    parser.add_argument(
        "--cities",
        nargs="+",
        default=None,
        help="Collect only these city slugs (default: all configured cities).",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help="Polling interval in seconds (default: 900).",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=30,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Collect one snapshot and exit.",
    )
    parser.add_argument(
        "--city-url",
        action="append",
        help="Custom city URL mapping in format city=url (repeatable).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    city_urls = resolve_city_urls(args)
    if not city_urls:
        raise RuntimeError("No cities selected.")

    if args.once:
        print(f"[start] collecting one snapshot for {len(city_urls)} cities into {args.base_dir}")
        for city, url in city_urls.items():
            try:
                collect_once_for_city(args.base_dir, city, url, args.timeout_seconds)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                print(f"[warn] city={city} fetch/parse failed: {exc}")
            except Exception as exc:  # pragma: no cover
                print(f"[warn] city={city} unexpected error: {exc}")
        return

    run_loop_multi_city(args.base_dir, city_urls, args.interval_seconds, args.timeout_seconds)


if __name__ == "__main__":
    main()
