# Overview

## Pipeline

A full synpp run is stored as `output/baselines/baseline_occitanie_59510/` after **Rebuild baseline**
(clears synpp cache and recomputes upstream stages). Later scenario jobs call `synthesis.output` only:
load that baseline, assign `latent_class`
from `backend/config/profiles.yml`, apply the polygon and population filters, write
CSVs under `output/jobs/<run_id>/`. Person **constraints** are assigned at baseline
build from `backend/config/constraints.yml` and copied through to `scenario.json`.
The backend can export `scenario.json` for routing.

```
baseline (full synpp, once)
    -> output/baselines/baseline_occitanie_59510/

scenario job (UI or POST /jobs)
    -> synthesis.output + profiles.yml + policy
    -> output/jobs/<run_id>/
    -> scenario.json (optional export)
```

## Code layout

- `backend/` - FastAPI, job records, scenario export
- `frontend/` - map, targets, profile filters, bike station overrides
- `backend/config/profiles.yml` - class rules and preference weights
- `backend/config/constraints.yml` - person mobility constraints (baseline only)
- `config_occitanie.yml` - synpp template for Occitanie

Latent classes are written in `synthesis/output`, not in `synthesis.population.enriched`.
`latent_classes.enabled` stays `false` in the runtime config.
