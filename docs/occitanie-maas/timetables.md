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

### CLI options

**Normal build** (default): generate timetables, export CSVs, then run validation.

| Option | Default | Meaning |
|--------|---------|---------|
| `--gtfs-dir` | `data/gtfs_occitanie/` | Folder of GTFS `.zip` feeds |
| `--baseline-dir` | From `config_occitanie.yml` | Baseline with `*_gtfs_routes.csv` and `*_gtfs_stops.csv` |
| `--output-dir` | `data/gtfs_occitanie/timetables/` | Parent folder for timestamped runs |
| `--timestamp` | Current time (`YYYYMMDD_HHMMSS`) | Output folder name under `--output-dir` |
| `--weekday` | All seven weekdays | Day(s) to build; repeat for several, e.g. `--weekday monday --weekday sunday` |
| `--jobs` | omitted / auto(0) | Max weekdays built in parallel (see below) |

Validation (`validation_report.json`) **always runs at the end of a normal build** — no flag required.

**Validate-only** (no rebuild): pass both flags below.

| Option | Default | Meaning |
|--------|---------|---------|
| `--validate` | not set | Set to skip generation and only validate an existing run |
| `--run-dir` | — | Required with `--validate`: existing timetable run folder |

**`--jobs`:** Each weekday (monday, tuesday, …) is built independently. GTFS zips are
loaded once, then weekday folders are written. `--jobs` caps how many weekdays run
at the same time:

| Value | Behaviour |
|-------|-----------|
| omitted or `0` | Auto: `min(weekdays to build, CPU count)`. **All seven weekdays → 7 workers** on a machine with ≥7 cores (what you see as `parallel jobs: 7` in the log). |
| `1` | Sequential (one weekday at a time) |
| `4` | At most four weekdays in parallel (never more than the weekdays you asked for) |

Example: `--jobs 4` with all seven weekdays uses four worker processes; when one
finishes, the next weekday starts until all seven are done. With no `--jobs` flag
and all seven weekdays, the script uses seven workers if the CPU count allows it.

The script creates a timestamped folder, e.g.
`data/gtfs_occitanie/timetables/20260717_163230/`, with one subdirectory per weekday
and one JSON file per PT operator (`TisseoOperator.json`, `SNCFOperator.json`, …).

Generation also writes:

- `generation_stats.json` — feed-level stats per weekday
- `validation_skeleton.json` — baseline routes with vs without departures
- `validation_report.json` — zero-departure diagnosis (see below)
- `lines_by_weekday.csv` and `lines_by_weekday_summary.csv` — route coverage summary

**Examples:**

```bash
# All weekdays (typically 7 parallel workers if CPU count ≥ 7)
uv run data/gtfs/build_timetables.py

# Monday only
uv run data/gtfs/build_timetables.py --weekday monday

# Saturday and Sunday, four parallel workers
uv run data/gtfs/build_timetables.py --weekday saturday --weekday sunday --jobs 4

# Fixed output folder name
uv run data/gtfs/build_timetables.py --timestamp smoke_monday

# Re-validate an existing run (no rebuild)
uv run data/gtfs/build_timetables.py --validate --run-dir data/gtfs_occitanie/timetables/20260717_163230
```

## Entry format

Each operator file is a JSON array of line objects:

```json
[
  {
    "line_id": "line:10",
    "patterns": [
      {
        "pattern_id": "p1",
        "stops": ["<point_id_A>", "<point_id_B>", "<point_id_C>"],
        "trips": [
          { "departure_times": [480, 488, 495] },
          { "departure_times": [510, 518, 525] }
        ]
      }
    ]
  }
]
```

| Field | Meaning |
|-------|---------|
| `line_id` | Baseline route id (matches `*_gtfs_routes.csv`) |
| `pattern_id` | Ordered stop sequence for one service variant (typically one travel direction) |
| `stops[]` | Ordered stop `point_id`s along the pattern |
| `trips[]` | One complete vehicle run along that pattern |
| `departure_times[]` | Minutes from midnight at each stop; `departure_times[i]` matches `stops[i]` |

Each direction is its own pattern (ordered `stops[]`). There is no `direction_id` field.

Cross-border trips export only contiguous in-baseline stop runs; an out-of-region stop splits the trip into separate patterns.

`point_id` values are 12-char SHA1 hashes of stop lat/lon +
`stop:{OperatorId}` (same hashing as scenario export).

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

Every full build ends with validation and writes `validation_report.json`. To run
validation again without rebuilding:

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
