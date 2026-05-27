from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_TEMPLATE = REPO_ROOT / "config_occitanie.yml"
DATA_DIR = REPO_ROOT / "data"
BIKESHARING_PATH = "bikesharing_occitanie"
GBFS_PATH = "gbfs"
OUTPUT_DIR = REPO_ROOT / "output"
DEFAULT_BASELINE_RUN_ID = "baseline_occitanie_59510"
BASELINE_BIKESHARING_STATIONS_CSV = (
    OUTPUT_DIR / "baselines" / DEFAULT_BASELINE_RUN_ID / f"{DEFAULT_BASELINE_RUN_ID}_bikesharing_stations.csv"
)
BACKEND_STATE_DIR = REPO_ROOT / "backend" / "state"
BACKEND_CONFIG_DIR = REPO_ROOT / "backend" / "config"
PROFILES_PATH = BACKEND_CONFIG_DIR / "profiles.yml"
BASELINES_DIR = OUTPUT_DIR / "baselines"
JOBS_DIR = BACKEND_STATE_DIR / "jobs"
LOGS_DIR = BACKEND_STATE_DIR / "logs"
RUNTIME_CONFIG_DIR = BACKEND_STATE_DIR / "configs"
CUTTER_DIR = DATA_DIR / "cutter" / "generated"
DEFAULTS_PATH = BACKEND_CONFIG_DIR / "defaults.yml"

for directory in (JOBS_DIR, LOGS_DIR, RUNTIME_CONFIG_DIR, CUTTER_DIR, OUTPUT_DIR, BASELINES_DIR):
    directory.mkdir(parents=True, exist_ok=True)
