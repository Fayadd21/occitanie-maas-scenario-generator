# Quickstart

## Start backend and frontend

```bash
uv sync
uv run uvicorn backend.app.main:app --port 8000
```

```bash
cd frontend
npm install
npm run dev
```

Set `VITE_BACKEND_URL=http://localhost:8000` if the UI does not reach the API.

## Baseline

Use **Rebuild baseline** in the UI, or:

```bash
curl -X POST http://localhost:8000/baseline/rebuild
```

Poll `GET /jobs/{job_id}` until `status` is `succeeded`. This can take a long time (synpp cache
is cleared and upstream stages are recomputed).

Check readiness:

```bash
curl http://localhost:8000/config/defaults
```

Look for `"baseline_ready": true` before starting a scenario.

## Scenario job

**Generate population** stays disabled in the UI until `baseline_ready` is true (baseline folder
exists with the required tables). The API returns **409** if you call `POST /jobs` earlier.

1. Draw or import a polygon.
2. Set target population and households if needed.
3. Select allowed latent classes.
4. Click **Generate population** (enabled only after a successful baseline rebuild).

Files appear under `output/jobs/<run_id>/` (`<run_id>_persons.csv`, activities, households, resources).

## Export

After success, use **Export scenario JSON** or `GET /jobs/{job_id}/scenario.json`.
Preferences on each request come from the person `latent_class` and `profiles.yml`.
