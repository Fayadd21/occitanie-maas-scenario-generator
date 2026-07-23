# API and outputs

## Endpoints

| Method | Path | Notes |
|--------|------|-------|
| GET | `/health` | |
| GET | `/config/defaults` | `target_population`, `baseline_run_id`, `baseline_ready` (whether scenario jobs are allowed) |
| GET | `/config/profiles` | |
| POST | `/baseline/rebuild` | Clears synpp cache, full recompute, promotes to `output/baselines/` |
| POST | `/jobs` | **409** if baseline folder is missing or incomplete |
| GET | `/jobs/{id}` | Poll until `status` is `succeeded` or `failed` |
| GET | `/jobs/{id}/outputs` | |
| GET | `/jobs/{id}/log` | |
| GET | `/jobs/{id}/population.geojson` | |
| GET | `/jobs/{id}/activities.geojson` | |
| GET | `/jobs/{id}/scenario.zip` | Demand `scenario.json` + `operators/{OperatorId}.json` (PT timetables from `timetables_path`; taxi fleet from `taxi_fleet_path`; see [GTFS timetables](timetables.md), [Taxi fleet](taxi-fleet.md)) |

### `GET /config/defaults`

Example fields:

- `target_population` - default cap for baseline build (`backend/config/defaults.yml`)
- `baseline_run_id` - e.g. `baseline_occitanie_59510`
- `baseline_ready` - `true` when `output/baselines/<baseline_run_id>/` contains the required population tables

The UI uses `baseline_ready` to enable **Generate population**.

### `POST /baseline/rebuild`

Starts a synpp job (`job_type: baseline`). On success, copies `occitanie_*` outputs into
`output/baselines/<baseline_run_id>/` and updates `baseline_run_path` in `config_occitanie.yml`.

### `POST /jobs`

Requires a complete baseline (same checks as `baseline_ready`). Otherwise **409** with a message
to run rebuild baseline first.

## Job directory

`output/jobs/<run_id>/`:

- `<run_id>_persons.csv` (`latent_class` on scenario runs; `constraints` JSON from baseline)
- `<run_id>_activities.csv`, `<run_id>_activities.gpkg`
- `<run_id>_households.csv`
- resource CSVs when exported (bikes, GTFS, ...)

## scenario.json

Contains `persons`, `requests` (activity chains with preferences per class and
`constraints` per leg), `resources`, and `profiles_path`. Returns 409 if persons lack
`latent_class`.

Constraint assignment is documented in [Person constraints](constraints.md).

Runtime YAML per job is written under the backend runtime config directory (`config_service`).
