# Prerequisites

## Eqasim population

Set up the region and data using [Gathering the data](gathering-the-data.md):
Python environment, files under `data/`, and `config_occitanie.yml` with the
desired departments. A file-name checklist is in [Data layout](data-layout.md).

Scenario jobs use `synthesis.output` only. The MATSim simulation stack has been removed from this project.
GeoPackage map layers (`homes.gpkg`, `activities.gpkg`) come from population spatial
data (BAN/BDTOPO/IRIS); see [Data layout](data-layout.md). GTFS zips under
`data/gtfs_occitanie/` (Tisséo, TAM, liO, SNCF, Tango, Sankéo, and so on) are needed
for transit stop/route layers in baseline exports.

## Baseline

Run a baseline before the first scenario job (the API blocks `POST /jobs` until this exists;
the UI keeps **Generate population** disabled until then):

- Using the UI: **Rebuild baseline**
- Using the API: `POST /baseline/rebuild`

Each rebuild clears the synpp cache under `working_directory` in `config_occitanie.yml`, then
recomputes the full dependency chain for `synthesis.output` (not a fast cache-only refresh).

Output is copied to `output/baselines/baseline_occitanie_59510/`. Scenario runtime configs set `baseline_run_path` to this folder.

Default target population for baseline rebuild comes from `backend/config/defaults.yml`, corresponding to 1% of the total population of the Occitanie region.

## Profiles (Latent Classes)

Copy the template:

```bash
cp backend/config/example.profiles.yml backend/config/profiles.yml
```

See [Profiles and latent classes](profiles-and-latent-classes.md).

## MaaS resource data

`config_occitanie.yml` lists paths such as `bikesharing_path` (status history),
`gbfs_path` (static station/system JSON), GTFS, and parking feeds.
See [Data layout](data-layout.md) for expected file names.
Static CSVs are exported on **baseline rebuild** (`export_static_resources: true`
in the runtime config written by the backend).

## Running the Project

Backend:

```bash
uv sync
uv run uvicorn backend.app.main:app --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

