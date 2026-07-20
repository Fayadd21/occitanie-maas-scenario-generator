# GTFS timetables

Public-transport departure times for scenario export are **not** computed during a
scenario job. They are built separately using the Occitanie GTFS zips and the baseline
stop/route tables, then wired into exports via `config_occitanie.yml`.

## Prerequisites

- GTFS zips under `data/gtfs_occitanie/` (see [Data layout](data-layout.md))
- Active baseline from `config_occitanie.yml` (`baseline_run_path` or
  `baseline_run_id`) with `*_gtfs_routes.csv` and `*_gtfs_stops.csv`

## Build a run

From the repo root:

```bash
uv run data/gtfs/build_timetables.py
```

Defaults:

| Option | Default |
|--------|---------|
| `--gtfs-dir` | `data/gtfs_occitanie/` |
| `--baseline-dir` | `baseline_run_path` or `output/baselines/<baseline_run_id>/` from `config_occitanie.yml` |
| `--output-dir` | `data/gtfs_occitanie/timetables/` |

The script creates a timestamped folder, e.g.
`data/gtfs_occitanie/timetables/20260717_163230/`, with one subdirectory per weekday
and one JSON file per PT operator (`TisseoOperator.json`, `SNCFOperator.json`, …).

Generation also writes:

- `generation_stats.json` — feed-level stats per weekday
- `validation_skeleton.json` — baseline routes with vs without departures
- `validation_report.json` — zero-departure diagnosis (see below)
- `lines_by_weekday.csv` and `lines_by_weekday_summary.csv` — route coverage summary

### Build one weekday

```bash
uv run data/gtfs/build_timetables.py --weekday monday
```

Repeat `--weekday` for multiple days. Omit it to build all seven weekdays.

### Custom output stamp

```bash
uv run data/gtfs/build_timetables.py --timestamp smoke_monday
```

## Entry format

Each operator file is a JSON array. Each row is:

```json
["<point_id>", "line:<route_id>", <direction_id>, [<departure_minutes>, ...]]
```

| Field | Meaning |
|-------|---------|
| `point_id` | 12-char SHA1 of stop lat/lon + `stop:{OperatorId}` (same hashing as scenario export) |
| `line:<route_id>` | Baseline route id (matches `*_gtfs_routes.csv`) |
| `direction_id` | GTFS `trips.direction_id`: `0` or `1` (missing → `0`). Opposite directions are **separate rows**, not merged |
| departure minutes | Minutes from midnight (GTFS `stop_times.departure_time`) |

### Direction ids

`0` and `1` are the two travel directions of a route in GTFS. Which physical
direction each value represents is defined by the agency (often outbound vs inbound).
Use `trip_headsign` or stop order in the raw feed if you need the human label.

## Wire into scenarios

In `config_occitanie.yml`:

```yaml
baseline_run_id: baseline_occitanie_59510
baseline_run_path: output/baselines/baseline_occitanie_59510
timetables_path: gtfs_occitanie/timetables/20260717_163230
timetables_weekday: monday
```

`baseline_run_path` / `baseline_run_id` define which stop and route tables the
timetable builder uses. `timetables_path` / `timetables_weekday` define which
built run scenario export loads.

Paths are relative to `data_path`. After changing the run folder, **start a new
scenario job** — existing jobs keep the `timetables_path` from their runtime YAML.

On **Export scenario zip**, PT operators get timetables from:

```text
{timetables_path}/{timetables_weekday}/{OperatorId}.json
```

Example: `data/gtfs_occitanie/timetables/20260717_163230/monday/TisseoOperator.json`
→ `operators/TisseoOperator.json` inside the zip.

If `timetables_path` is unset, operators export with empty `"timetables": []`.

## Validate an existing run

Validation runs automatically at the end of `build_timetables.py`. To re-run only
validation:

```bash
uv run data/gtfs/build_timetables.py --validate --run-dir data/gtfs_occitanie/timetables/20260717_163230
```

Optional: `--weekday monday` to validate a single day.

### Zero-departure reasons

`validation_report.json` classifies baseline routes that have no departures in the
built timetables:

| Reason | Typical cause |
|--------|----------------|
| `departures_exist_but_stops_not_in_baseline` | Service exists in GTFS but stops are outside the Occitanie baseline (common for SNCF) |
| `no_active_service_on_this_weekday` | Weekend-only, night, or sparse calendar |
| `route_id_not_found_in_any_gtfs_feed` | Route id in baseline does not match raw zip ids (see note below) |
| `has_service_but_no_trips` | Active calendar but no trips |
| `has_trips_but_no_departure_times` | Trips without usable `stop_times` |

Use `lines_by_weekday.csv` for per-route, per-weekday stop and departure counts.

### Route id mismatches (`_mN` suffixes)

When eqasim merges GTFS feeds, colliding route ids are renamed in the baseline
(e.g. `10_m5` for TAM while the TAM zip still has `10`). The builder resolves
this automatically:

1. Strip `_mN` from baseline route ids to get the raw GTFS id.
2. Match each zip trip using **operator** (baseline `operator` column ↔ zip
   `agency.txt` / feed name).
3. Write timetables under the **baseline** id (`line:10_m5`).

Validation uses the same mapping, so those lines are no longer reported as
`route_id_not_found_in_any_gtfs_feed` when the feed and operator match.

## Re-export line CSVs only

If you already have a run and only need the CSV summaries:

```bash
uv run scripts/export_timetable_lines_csv.py \
  --run-dir data/gtfs_occitanie/timetables/20260717_163230
```

`--baseline-dir` is optional; it defaults to the active baseline from
`config_occitanie.yml`.
