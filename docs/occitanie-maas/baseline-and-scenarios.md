# Baseline and scenarios

## Baseline build

| | Baseline | Scenario job |
|--|----------|----------------|
| Synpp | `synthesis.output` and all upstream stages (cache cleared first) | `synthesis.output` with `baseline_run_path` |
| `latent_class` in persons CSV | no | yes |
| `constraints` in persons CSV | yes (JSON list) | copied from baseline |
| Output dir | `output/baselines/baseline_occitanie_59510/` | `output/jobs/<run_id>/` |

`POST /baseline/rebuild` drops scenario-only keys (`profiles_path`, `assign_latent_classes`, polygon filter, allowed classes, …), enables constraint assignment from `backend/config/constraints.yml`, clears the synpp `working_directory` cache, runs the pipeline, and promotes `occitanie_*` files into the baseline folder.

See [Person constraints](constraints.md) for editing `constraints.yml`.

`POST /jobs` returns 409 until that baseline folder has the required tables (`persons`, `activities`, `households`, `vehicles`, …).

**Generate population** in the UI stays disabled until `GET /config/defaults` has `baseline_ready: true`.

## Scenario job

`POST /jobs` accepts `selected_area_geojson`, `target_population`, `target_households`, and `config_overrides` (strict targets, random seed, outskirts bias, allowed classes, …).

Runtime YAML uses `baseline_run_path`, `assign_latent_classes: true`, and `profiles_path`. The output stage reloads baseline tables, filters by polygon, assigns `latent_class` on that subset, then applies allowed classes and population/household targets.

## Bike overrides

Station availability edits from the UI are stored on the job record as `bikesharing_station_availability`. They are applied when writing job outputs and `scenario.json`, not in the synpp YAML.
