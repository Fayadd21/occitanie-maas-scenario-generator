from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.app.services.baseline_service import get_active_baseline_directory  # noqa: E402
from synthesis.output_resources.taxi.fleet import (  # noqa: E402
    WEEKDAYS,
    load_taxi_fleet_config,
    write_taxi_fleet_run,
)

_DEFAULT_OUTPUT_DIR = _REPO_ROOT / "data" / "taxi_occitanie" / "fleet"
_DEFAULT_CONFIG = _REPO_ROOT / "backend" / "config" / "taxi_fleet.yml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate taxi fleet and bookings for scenario export")
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=None,
        help="Defaults to baseline_run_path / baseline_run_id in config_occitanie.yml",
    )
    parser.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT_DIR)
    parser.add_argument("--config", type=Path, default=_DEFAULT_CONFIG)
    parser.add_argument("--weekday", choices=list(WEEKDAYS), default="monday")
    parser.add_argument("--timestamp", type=str, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    baseline_dir = get_active_baseline_directory() if args.baseline_dir is None else args.baseline_dir.resolve()
    stands_csv = baseline_dir / f"{baseline_dir.name}_taxi_stands.csv"
    if not stands_csv.is_file():
        raise SystemExit(f"Missing baseline taxi stands CSV: {stands_csv}")

    config = load_taxi_fleet_config(args.config)
    run_dir = write_taxi_fleet_run(
        stands_csv,
        args.output_dir,
        weekday=args.weekday,
        config=config,
        timestamp=args.timestamp,
    )
    stats_path = run_dir / "generation_stats.json"
    print(f"wrote {run_dir / 'Taxi.json'}")
    print(f"wrote {stats_path}")


if __name__ == "__main__":
    main()
