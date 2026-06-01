# Unit tests

Tests live under `tests/`. Run them from the repository root with [uv](https://docs.astral.sh/uv/):

```bash
uv sync
uv run pytest
```

Run one file:

```bash
uv run pytest tests/test_profiles_loader.py -q
```

## Occitanie MaaS tests (fast)

These cover the backend API, scenario export helpers, latent classes, GTFS labels, and
population policy. No national datasets and no full synpp run.

| File | What it checks |
|------|----------------|
| `test_backend_services.py` | Baseline readiness, runtime YAML, bike overrides, materialize outputs |
| `test_output_policy.py` | Area targets, dual population/household caps, outskirts bias |
| `test_profiles_loader.py` | Latent-class rules, assignment, preference weights |
| `test_gtfs_operator_labels.py` | GTFS operator label formatting in resource export |

Quick subset for MaaS work:

```bash
uv run pytest tests/test_backend_services.py tests/test_output_policy.py tests/test_profiles_loader.py tests/test_gtfs_operator_labels.py -q
```

Other MaaS tests build temporary YAML and CSV under pytest's `tmp_path`. They do not depend on
your local `backend/config/profiles.yml`, `config_occitanie.yml`, or baseline outputs.

## Upstream eqasim tests (slow)

These come from upstream eqasim-france. They build synthetic `testdata/` regions and run long
synpp pipelines (population synthesis, and optionally MATSim).

| File | What it checks |
|------|----------------|
| `test_pipeline.py` | End-to-end population stages on fake data |
| `test_determinism.py` | Reproducible outputs for synthesis on fake data |

Expect minutes of runtime and several GB of temp data under pytest's `tmpdir`. They are not
required to develop the Occitanie UI or API.
