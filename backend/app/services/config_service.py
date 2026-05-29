from __future__ import annotations

import datetime as dt
import json
import uuid
import random
from pathlib import Path
from typing import Any

import yaml

from backend.app.services.baseline_service import is_baseline_ready, targets_exceed_baseline
from backend.app.services.constants import (
    CONFIG_TEMPLATE,
    CUTTER_DIR,
    DEFAULT_BASELINE_RUN_ID,
    DEFAULTS_PATH,
    OUTPUT_DIR,
    PROFILES_PATH,
    RUNTIME_CONFIG_DIR,
)


def load_defaults() -> dict[str, Any]:
    if not DEFAULTS_PATH.exists():
        return {"target_population": 59510}
    with DEFAULTS_PATH.open("r", encoding="utf-8") as f:
        defaults = yaml.safe_load(f) or {}
    if "target_population" not in defaults:
        defaults["target_population"] = 59510
    defaults["baseline_run_id"] = DEFAULT_BASELINE_RUN_ID
    defaults["baseline_ready"] = is_baseline_ready()
    if defaults["baseline_ready"]:
        from backend.app.services.baseline_service import count_baseline_households, count_baseline_persons

        defaults["baseline_population"] = count_baseline_persons()
        defaults["baseline_households"] = count_baseline_households()
    else:
        defaults["baseline_population"] = 0
        defaults["baseline_households"] = 0
    return defaults


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def new_run_id() -> str:
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"run_{ts}_{uuid.uuid4().hex[:6]}"


def write_selection_geojson(run_id: str, feature_collection: dict[str, Any]) -> Path:
    cutter_path = CUTTER_DIR / f"{run_id}.geojson"
    cutter_path.write_text(json.dumps(feature_collection, indent=2), encoding="utf-8")
    return cutter_path


def build_runtime_config(
    run_id: str,
    selected_area_geojson: dict[str, Any] | None,
    config_overrides: dict[str, Any],
    target_population: int | None,
    target_households: int | None,
) -> tuple[Path, Path, str, dict[str, Any]]:
    if not CONFIG_TEMPLATE.exists():
        raise RuntimeError(f"Missing template config: {CONFIG_TEMPLATE}")

    with CONFIG_TEMPLATE.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    config.setdefault("config", {})
    cfg = config["config"]

    base_output_path = OUTPUT_DIR.resolve()
    base_output_prefix = "occitanie_"
    normalized_output_path = str(base_output_path).replace("\\", "/")

    if selected_area_geojson:
        selection_path = write_selection_geojson(run_id, selected_area_geojson)
        cfg["population_filter_geojson"] = str(selection_path).replace("\\", "/")
    else:
        cfg.pop("population_filter_geojson", None)

    if target_population is None:
        cfg.pop("target_population", None)
    else:
        cfg["target_population"] = int(target_population)
    if target_households is None:
        cfg.pop("target_households", None)
    else:
        cfg["target_households"] = int(target_households)

    overrides = config_overrides or {}
    for key, value in overrides.items():
        cfg[key] = value

    if bool(overrides.get("randomize_each_run", False)):
        cfg["random_seed"] = random.randint(1, 2_147_483_647)

    cfg["export_static_resources"] = False

    strict_target_mode = bool(overrides.get("strict_target_mode", False))
    randomize_each_run = bool(overrides.get("randomize_each_run", False))
    exceeds_baseline = targets_exceed_baseline(target_population, target_households)

    if "sampling_rate" in overrides:
        cfg["sampling_rate"] = overrides["sampling_rate"]
    elif exceeds_baseline or strict_target_mode:
        derived_rate = _derive_sampling_rate_from_targets(cfg, target_population, target_households)
        if derived_rate is not None:
            cfg["sampling_rate"] = derived_rate

    population_source = "baseline"
    if exceeds_baseline:
        cfg.pop("baseline_run_id", None)
        cfg.pop("baseline_run_path", None)
        population_source = "full_synthesis"

    cfg.pop("strict_target_mode", None)
    cfg.pop("randomize_each_run", None)
    cfg.pop("bikesharing_station_availability", None)

    cfg["output_path"] = normalized_output_path
    cfg["output_prefix"] = base_output_prefix
    cfg["profiles_path"] = str(PROFILES_PATH.resolve()).replace("\\", "/")
    cfg["assign_latent_classes"] = True
    cfg["latent_classes.enabled"] = False
    runtime_config_path = RUNTIME_CONFIG_DIR / f"{run_id}.yml"
    with runtime_config_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, sort_keys=False, allow_unicode=True)

    effective = {
        "strict_target_mode": strict_target_mode,
        "randomize_each_run": randomize_each_run,
        "target_population": cfg.get("target_population", None),
        "target_households": cfg.get("target_households", None),
        "sampling_rate": cfg.get("sampling_rate", None),
        "random_seed": cfg.get("random_seed", None),
        "export_static_resources": cfg.get("export_static_resources", None),
        "profiles_path": cfg.get("profiles_path"),
        "assign_latent_classes": cfg.get("assign_latent_classes"),
        "population_source": population_source,
        "exceeds_baseline": exceeds_baseline,
    }

    return runtime_config_path, base_output_path, base_output_prefix, effective


def _derive_sampling_rate_from_targets(
    cfg: dict[str, Any],
    target_population: int | None,
    target_households: int | None,
) -> float | None:
    if target_population is None and target_households is None:
        return None

    reference_total_persons = float(cfg.get("reference_total_population", 5_951_000))
    reference_total_households = float(cfg.get("reference_total_households", 2_600_000))

    if target_population is not None:
        derived = float(target_population) / max(reference_total_persons, 1.0)
    elif target_households is not None:
        derived = float(target_households) / max(reference_total_households, 1.0)
    else:
        return None

    if target_population is not None:
        if target_households is not None:
            household_cap = float(target_households) / max(reference_total_households, 1.0)
            derived = min(derived, household_cap)
    return max(1e-6, min(1.0, derived))


def build_baseline_runtime_config(
    run_id: str,
    *,
    target_population: int | None,
    config_overrides: dict[str, Any] | None = None,
) -> tuple[Path, Path, str, dict[str, Any]]:
    if not CONFIG_TEMPLATE.exists():
        raise RuntimeError(f"Missing template config: {CONFIG_TEMPLATE}")

    with CONFIG_TEMPLATE.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    config.setdefault("config", {})
    cfg = config["config"]

    base_output_path = OUTPUT_DIR.resolve()
    base_output_prefix = "occitanie_"
    normalized_output_path = str(base_output_path).replace("\\", "/")

    cfg.pop("baseline_run_id", None)
    cfg.pop("baseline_run_path", None)
    cfg.pop("population_filter_geojson", None)
    cfg.pop("target_households", None)
    cfg.pop("allowed_latent_classes", None)
    cfg.pop("outskirts_bias", None)
    
    cfg.pop("assign_latent_classes", None)
    cfg.pop("profiles_path", None)

    if target_population is None:
        cfg.pop("target_population", None)
    else:
        cfg["target_population"] = int(target_population)

    overrides = config_overrides or {}
    for key, value in overrides.items():
        cfg[key] = value
    cfg.pop("assign_latent_classes", None)
    cfg.pop("profiles_path", None)

    cfg["export_static_resources"] = True
    cfg["export_trips"] = False

    cfg["output_path"] = normalized_output_path
    cfg["output_prefix"] = base_output_prefix

    runtime_config_path = RUNTIME_CONFIG_DIR / f"{run_id}.yml"
    with runtime_config_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False, allow_unicode=True)

    effective = {
        "job_type": "baseline",
        "baseline_run_id": DEFAULT_BASELINE_RUN_ID,
        "target_population": cfg.get("target_population"),
        "sampling_rate": cfg.get("sampling_rate"),
        "random_seed": cfg.get("random_seed"),
        "export_static_resources": cfg.get("export_static_resources"),
    }
    return runtime_config_path, base_output_path, base_output_prefix, effective
