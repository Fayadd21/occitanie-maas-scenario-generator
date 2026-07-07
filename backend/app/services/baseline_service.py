"""Baseline storage, readiness checks, and rebuild finalization.

A baseline is ready when output/baselines/<id>/ contains the required CSV/GPKG
suffixes listed in BASELINE_REQUIRED_SUFFIXES.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException

from backend.app.services.constants import (
    BASELINES_DIR,
    CONFIG_TEMPLATE,
    DEFAULT_BASELINE_RUN_ID,
    OUTPUT_DIR,
    PROFILES_PATH,
    REPO_ROOT,
)

BASELINE_REQUIRED_SUFFIXES = (
    "persons.csv",
    "activities.csv",
    "activities.gpkg",
    "households.csv",
    "vehicle_types.csv",
    "vehicles.csv",
)

BASELINE_RUN_ID_PREFIX = "baseline_occitanie_"


def baseline_run_id_for_target(target_population: int) -> str:
    population = int(target_population)
    if population <= 0:
        raise ValueError("target_population must be greater than 0")
    return f"{BASELINE_RUN_ID_PREFIX}{population}"


def get_active_baseline_run_id() -> str:
    if not CONFIG_TEMPLATE.exists():
        return DEFAULT_BASELINE_RUN_ID

    with CONFIG_TEMPLATE.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    run_id = (config.get("config") or {}).get("baseline_run_id")
    if run_id and str(run_id).strip():
        return str(run_id).strip()
    return DEFAULT_BASELINE_RUN_ID


def get_synpp_working_directory() -> Path:
    if not CONFIG_TEMPLATE.exists():
        raise RuntimeError(f"Missing template config: {CONFIG_TEMPLATE}")

    with CONFIG_TEMPLATE.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    working_directory = config.get("working_directory")
    if not working_directory:
        raise RuntimeError("config_occitanie.yml is missing working_directory")

    path = Path(str(working_directory))
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    return path


def clear_synpp_cache() -> Path:
    """Remove synpp pipeline cache so the next run recomputes all stages from scratch."""
    cache_dir = get_synpp_working_directory()
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def baseline_directory(baseline_run_id: str | None = None) -> Path:
    run_id = baseline_run_id or get_active_baseline_run_id()
    return BASELINES_DIR / run_id


def count_baseline_persons(baseline_run_id: str | None = None) -> int:
    run_id = baseline_run_id or get_active_baseline_run_id()
    persons_path = baseline_directory(run_id) / f"{run_id}_persons.csv"
    if not persons_path.is_file():
        return 0
    import pandas as pd

    return int(len(pd.read_csv(persons_path, sep=";", usecols=["person_id"])))


def count_baseline_households(baseline_run_id: str | None = None) -> int:
    run_id = baseline_run_id or get_active_baseline_run_id()
    households_path = baseline_directory(run_id) / f"{run_id}_households.csv"
    if not households_path.is_file():
        return 0
    import pandas as pd

    return int(len(pd.read_csv(households_path, sep=";", usecols=["household_id"])))


def targets_exceed_baseline(
    target_population: int | None,
    target_households: int | None,
    baseline_run_id: str | None = None,
) -> bool:
    run_id = baseline_run_id or get_active_baseline_run_id()
    if not is_baseline_ready(run_id):
        return False
    if target_population is not None and int(target_population) > count_baseline_persons(run_id):
        return True
    if target_households is not None and int(target_households) > count_baseline_households(run_id):
        return True
    return False


def is_baseline_ready(baseline_run_id: str | None = None) -> bool:
    run_id = baseline_run_id or get_active_baseline_run_id()
    baseline_dir = baseline_directory(run_id)
    if not baseline_dir.is_dir():
        return False

    for suffix in BASELINE_REQUIRED_SUFFIXES:
        artifact = baseline_dir / f"{run_id}_{suffix}"
        if not artifact.is_file() or artifact.stat().st_size == 0:
            return False
    return True


def require_baseline_for_scenario() -> None:
    run_id = get_active_baseline_run_id()
    if is_baseline_ready(run_id):
        return
    raise HTTPException(
        status_code=409,
        detail=(
            f"Baseline '{run_id}' is missing or incomplete under output/baselines/. "
            "Run Build baseline in the UI or POST /baseline/rebuild before starting a scenario job."
        ),
    )


def list_available_baselines() -> list[dict[str, Any]]:
    active_id = get_active_baseline_run_id()
    baselines: list[dict[str, Any]] = []
    if not BASELINES_DIR.is_dir():
        return baselines

    for path in BASELINES_DIR.iterdir():
        if not path.is_dir():
            continue
        run_id = path.name
        if not run_id.startswith(BASELINE_RUN_ID_PREFIX):
            continue
        ready = is_baseline_ready(run_id)
        baselines.append(
            {
                "baseline_run_id": run_id,
                "ready": ready,
                "active": run_id == active_id,
                "population": count_baseline_persons(run_id) if ready else 0,
                "households": count_baseline_households(run_id) if ready else 0,
            }
        )

    baselines.sort(
        key=lambda item: (
            not bool(item["ready"]),
            -int(item["population"]),
            str(item["baseline_run_id"]),
        )
    )
    return baselines


def set_active_baseline(baseline_run_id: str) -> dict[str, Any]:
    run_id = str(baseline_run_id).strip()
    if not run_id:
        raise HTTPException(status_code=400, detail="baseline_run_id is required")
    if not is_baseline_ready(run_id):
        raise HTTPException(
            status_code=409,
            detail=f"Baseline '{run_id}' is missing or incomplete under output/baselines/.",
        )
    baseline_run_path = baseline_directory(run_id).resolve()
    update_occitanie_baseline_pointer(run_id, baseline_run_path)
    return {
        "baseline_run_id": run_id,
        "baseline_ready": True,
        "baseline_population": count_baseline_persons(run_id),
        "baseline_households": count_baseline_households(run_id),
    }


def promote_synpp_output_to_baseline(
    *,
    source_output_path: Path,
    source_output_prefix: str,
    baseline_run_id: str,
) -> Path:
    destination = BASELINES_DIR / baseline_run_id
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)

    for source_file in source_output_path.glob(f"{source_output_prefix}*"):
        if not source_file.is_file():
            continue
        suffix = source_file.name[len(source_output_prefix) :]
        target_file = destination / f"{baseline_run_id}_{suffix}"
        shutil.copy2(source_file, target_file)

    return destination.resolve()


def update_occitanie_baseline_pointer(baseline_run_id: str, baseline_run_path: Path) -> None:
    if not CONFIG_TEMPLATE.exists():
        raise RuntimeError(f"Missing template config: {CONFIG_TEMPLATE}")

    with CONFIG_TEMPLATE.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    config.setdefault("config", {})
    config["config"]["baseline_run_id"] = baseline_run_id
    config["config"]["baseline_run_path"] = str(baseline_run_path).replace("\\", "/")

    with CONFIG_TEMPLATE.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False, allow_unicode=True)


def finalize_baseline_job(record: dict[str, Any]) -> dict[str, Any]:
    baseline_run_id = str(record.get("baseline_run_id") or DEFAULT_BASELINE_RUN_ID)
    source_output_path = Path(record["source_output_path"])
    source_output_prefix = str(record["source_output_prefix"])
    baseline_run_path = promote_synpp_output_to_baseline(
        source_output_path=source_output_path,
        source_output_prefix=source_output_prefix,
        baseline_run_id=baseline_run_id,
    )
    update_occitanie_baseline_pointer(baseline_run_id, baseline_run_path)
    record["baseline_run_path"] = str(baseline_run_path)
    record["baseline_promoted"] = True
    return record


def get_profiles_payload() -> dict[str, Any]:
    from synthesis.profiles.loader import list_profile_summaries

    return list_profile_summaries(PROFILES_PATH)
