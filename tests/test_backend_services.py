from pathlib import Path

import pytest
import yaml
from fastapi import HTTPException

from backend.app.services.baseline_service import (
    BASELINE_REQUIRED_SUFFIXES,
    baseline_run_id_for_target,
    clear_synpp_cache,
    is_baseline_ready,
    require_baseline_for_scenario,
)
from backend.app.services.config_service import build_runtime_config
from backend.app.services.constants import DEFAULT_BASELINE_RUN_ID
from backend.app.services.materialize_service import materialize_run_outputs


def _patch_config_service(tmp_path, monkeypatch):
    template_path = tmp_path / "config_template.yml"
    template_path.write_text(
        """
run:
  - synthesis.output
config:
  processes: 1
  sampling_rate: 0.01
  random_seed: 1234
""".strip(),
        encoding="utf-8",
    )
    runtime_dir = tmp_path / "runtime_configs"
    runtime_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    profiles_path = tmp_path / "profiles.yml"
    profiles_path.write_text("version: 1\nprofiles: []\n", encoding="utf-8")

    import backend.app.services.config_service as config_service

    monkeypatch.setattr(config_service, "CONFIG_TEMPLATE", template_path)
    monkeypatch.setattr(config_service, "RUNTIME_CONFIG_DIR", runtime_dir)
    monkeypatch.setattr(config_service, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(config_service, "PROFILES_PATH", profiles_path)
    return output_dir


def test_baseline_run_id_for_target():
    assert baseline_run_id_for_target(100) == "baseline_occitanie_100"
    assert baseline_run_id_for_target(59_510) == "baseline_occitanie_59510"


def test_build_baseline_runtime_config_uses_requested_baseline_run_id(tmp_path, monkeypatch):
    from backend.app.services import config_service

    template = tmp_path / "config_occitanie.yml"
    template.write_text(
        "working_directory: .\nrun:\n- synthesis.output\nconfig:\n  sampling_rate: 0.01\n  random_seed: 1234\n",
        encoding="utf-8",
    )
    runtime_dir = tmp_path / "configs"
    runtime_dir.mkdir()
    monkeypatch.setattr(config_service, "CONFIG_TEMPLATE", template)
    monkeypatch.setattr(config_service, "RUNTIME_CONFIG_DIR", runtime_dir)
    monkeypatch.setattr(config_service, "OUTPUT_DIR", tmp_path / "output")

    _, _, _, effective = config_service.build_baseline_runtime_config(
        run_id="baseline_build_test",
        target_population=100,
        baseline_run_id="baseline_occitanie_100",
    )
    assert effective["baseline_run_id"] == "baseline_occitanie_100"
    assert effective["target_population"] == 100
    assert effective["job_type"] == "baseline"
    assert effective["sampling_rate"] == pytest.approx(100 / 5_951_000)
    assert effective["assign_constraints"] is True
    assert effective["constraints_path"]


def test_is_baseline_ready_requires_population_artifacts(tmpdir, monkeypatch):
    from backend.app.services import baseline_service

    baseline_dir = Path(str(tmpdir.mkdir("baseline")))
    monkeypatch.setattr(baseline_service, "BASELINES_DIR", baseline_dir.parent)
    monkeypatch.setattr(baseline_service, "DEFAULT_BASELINE_RUN_ID", baseline_dir.name)

    assert is_baseline_ready(baseline_dir.name) is False

    for suffix in BASELINE_REQUIRED_SUFFIXES:
        (baseline_dir / f"{baseline_dir.name}_{suffix}").write_text("x", encoding="utf-8")

    assert is_baseline_ready(baseline_dir.name) is True


def test_list_available_baselines_marks_active_and_ready(tmpdir, monkeypatch):
    from backend.app.services import baseline_service

    baselines_root = Path(str(tmpdir.mkdir("baselines")))
    ready_dir = baselines_root / "baseline_occitanie_100"
    ready_dir.mkdir()
    incomplete_dir = baselines_root / "baseline_occitanie_200"
    incomplete_dir.mkdir()

    monkeypatch.setattr(baseline_service, "BASELINES_DIR", baselines_root)
    monkeypatch.setattr(baseline_service, "get_active_baseline_run_id", lambda: "baseline_occitanie_100")
    monkeypatch.setattr(
        baseline_service,
        "is_baseline_ready",
        lambda run_id: run_id == "baseline_occitanie_100",
    )
    monkeypatch.setattr(baseline_service, "count_baseline_persons", lambda run_id: 100 if run_id == "baseline_occitanie_100" else 0)
    monkeypatch.setattr(baseline_service, "count_baseline_households", lambda run_id: 50 if run_id == "baseline_occitanie_100" else 0)

    baselines = baseline_service.list_available_baselines()
    assert len(baselines) == 2
    ready = next(item for item in baselines if item["baseline_run_id"] == "baseline_occitanie_100")
    incomplete = next(item for item in baselines if item["baseline_run_id"] == "baseline_occitanie_200")
    assert ready["ready"] is True
    assert ready["active"] is True
    assert ready["population"] == 100
    assert incomplete["ready"] is False
    assert incomplete["active"] is False


def test_set_active_baseline_updates_config(tmpdir, monkeypatch):
    from backend.app.services import baseline_service

    baselines_root = Path(str(tmpdir.mkdir("baselines")))
    run_id = "baseline_occitanie_59510"
    baseline_dir = baselines_root / run_id
    baseline_dir.mkdir()
    for suffix in BASELINE_REQUIRED_SUFFIXES:
        (baseline_dir / f"{run_id}_{suffix}").write_text("x", encoding="utf-8")

    config_path = Path(str(tmpdir / "config_occitanie.yml"))
    config_path.write_text(
        "config:\n  baseline_run_id: baseline_occitanie_100\n  baseline_run_path: /old/path\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(baseline_service, "BASELINES_DIR", baselines_root)
    monkeypatch.setattr(baseline_service, "CONFIG_TEMPLATE", config_path)
    from backend.app.services import constants

    monkeypatch.setattr(constants, "CONFIG_TEMPLATE", config_path)
    monkeypatch.setattr(baseline_service, "count_baseline_persons", lambda *_args, **_kwargs: 59510)
    monkeypatch.setattr(baseline_service, "count_baseline_households", lambda *_args, **_kwargs: 29800)

    result = baseline_service.set_active_baseline(run_id)
    assert result["baseline_run_id"] == run_id
    assert result["baseline_population"] == 59510

    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved["config"]["baseline_run_id"] == run_id
    assert str(baseline_dir.resolve()).replace("\\", "/") == saved["config"]["baseline_run_path"]


def test_require_baseline_for_scenario_raises_when_missing(monkeypatch):
    from backend.app.services import baseline_service

    monkeypatch.setattr(baseline_service, "is_baseline_ready", lambda *_args, **_kwargs: False)

    with pytest.raises(HTTPException) as exc:
        require_baseline_for_scenario()
    assert exc.value.status_code == 409


def test_clear_synpp_cache_removes_working_directory(tmpdir, monkeypatch):
    from backend.app.services import baseline_service

    cache_dir = Path(str(tmpdir.mkdir("cache")))
    (cache_dir / "pipeline.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(baseline_service, "get_synpp_working_directory", lambda: cache_dir)

    cleared = clear_synpp_cache()
    assert cleared == cache_dir
    assert cache_dir.is_dir()
    assert not (cache_dir / "pipeline.json").exists()


def test_build_runtime_config_uses_full_synthesis_when_target_exceeds_baseline(tmp_path, monkeypatch):
    _patch_config_service(tmp_path, monkeypatch)
    import backend.app.services.config_service as config_service

    monkeypatch.setattr(config_service, "targets_exceed_baseline", lambda *_args, **_kwargs: True)

    runtime_config_path, _, _, effective = build_runtime_config(
        run_id="run_exceeds_baseline",
        selected_area_geojson=None,
        config_overrides={"strict_target_mode": True},
        target_population=65_000,
        target_households=None,
    )

    yaml_text = runtime_config_path.read_text(encoding="utf-8")
    assert "baseline_run_path" not in yaml_text
    assert effective["population_source"] == "full_synthesis"
    assert effective["exceeds_baseline"] is True
    assert effective["sampling_rate"] is not None


def test_build_runtime_config_keeps_stable_output(tmp_path, monkeypatch):
    output_dir = _patch_config_service(tmp_path, monkeypatch)
    run_id = "run_test_profile"
    job_output_path = output_dir / "jobs" / run_id
    job_output_path.mkdir(parents=True)
    runtime_config_path, source_output_path, source_output_prefix, effective = build_runtime_config(
        run_id=run_id,
        selected_area_geojson=None,
        config_overrides={},
        target_population=10,
        target_households=5,
        job_output_path=job_output_path,
    )

    assert runtime_config_path.exists()
    assert source_output_path == job_output_path.resolve()
    assert source_output_prefix == f"{run_id}_"
    assert effective["target_population"] == 10
    assert effective["target_households"] == 5
    assert effective["export_static_resources"] is False

    content = runtime_config_path.read_text(encoding="utf-8")
    assert f"output_prefix: {run_id}_" in content
    assert "export_static_resources: false" in content


def test_build_runtime_config_strips_bikesharing_station_availability_from_yaml(tmp_path, monkeypatch):
    _patch_config_service(tmp_path, monkeypatch)
    run_id = "run_test_bikesharing_field_strip"
    runtime_config_path, _, _, _ = build_runtime_config(
        run_id=run_id,
        selected_area_geojson=None,
        config_overrides={"bikesharing_station_availability": {"toulouse:1": 5}},
        target_population=10,
        target_households=None,
    )
    yaml_text = runtime_config_path.read_text(encoding="utf-8")
    assert "bikesharing_station_availability" not in yaml_text


def test_cap_availability_to_capacity():
    from backend.app.services.bike_csv_overrides import cap_availability_to_capacity

    assert cap_availability_to_capacity(5, 10) == 5
    assert cap_availability_to_capacity(15, 10) == 10
    assert cap_availability_to_capacity(15, None) == 15


def test_normalize_bikesharing_station_availability_and_job_record():
    from backend.app.services.bike_csv_overrides import (
        bike_station_availability_from_job_record,
        normalize_bikesharing_station_availability,
    )

    assert normalize_bikesharing_station_availability(None) is None
    assert normalize_bikesharing_station_availability({}) is None
    assert normalize_bikesharing_station_availability(
        {"bike_station:toulouse:1": 5, "nimes:2": "3", "skip": "nope"}
    ) == {"toulouse:1": 5, "nimes:2": 3}

    assert bike_station_availability_from_job_record({"bikesharing_station_availability": {"a:1": 2}}) == {
        "a:1": 2
    }


def test_materialize_run_outputs_copies_prefixed_outputs(tmpdir):
    source = Path(str(tmpdir.mkdir("source")))
    destination = Path(str(tmpdir.mkdir("destination")))
    run_id = "run_abc"
    (source / f"{run_id}_persons.csv").write_text("person_id\n1\n", encoding="utf-8")
    (source / f"{run_id}_households.csv").write_text("household_id\n1\n", encoding="utf-8")

    record = {
        "source_output_path": str(source),
        "source_output_prefix": f"{run_id}_",
        "run_id": run_id,
        "output_path": str(destination),
    }
    materialize_run_outputs(record)

    assert (destination / f"{run_id}_persons.csv").exists()
    assert (destination / f"{run_id}_households.csv").exists()


def test_materialize_copies_baseline_gtfs_to_job_folder(monkeypatch, tmpdir):
    from backend.app.services import materialize_service

    destination = Path(str(tmpdir.mkdir("destination_gtfs")))
    run_id = "run_gtfs"
    baseline_dir = Path(str(tmpdir.mkdir("baselines"))) / "baseline_test"
    baseline_dir.mkdir(parents=True)
    (baseline_dir / "baseline_test_gtfs_stops.csv").write_text("stop_id;stop_lat;stop_lon\n1;43;1\n", encoding="utf-8")
    (baseline_dir / "baseline_test_gtfs_routes.csv").write_text("route_id;operator\nR1;Tisseo\n", encoding="utf-8")

    monkeypatch.setattr(
        materialize_service,
        "baseline_artifact_path",
        lambda suffix, baseline_run_id=None: baseline_dir / f"baseline_test_{suffix}",
    )

    record = {
        "source_output_path": str(destination),
        "source_output_prefix": f"{run_id}_",
        "run_id": run_id,
        "output_path": str(destination),
    }
    materialize_service.materialize_run_outputs(record)

    assert (destination / f"{run_id}_gtfs_stops.csv").exists()
    assert (destination / f"{run_id}_gtfs_routes.csv").exists()


def test_materialize_applies_bikesharing_overrides_to_baseline_copy(monkeypatch, tmpdir):
    import pandas as pd

    from backend.app.services import materialize_service

    destination = Path(str(tmpdir.mkdir("destination2")))
    run_id = "run_bike"
    baseline_dir = Path(str(tmpdir.mkdir("baselines"))) / "baseline_test"
    baseline_dir.mkdir(parents=True)
    (baseline_dir / "baseline_test_bikesharing_stations.csv").write_text(
        "station_id;lat;lon;capacity;city_id;operator;city_station_id;available_bikes\n"
        "1;43.0;1.0;10;toulouse;op;toulouse:1;4\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        materialize_service,
        "baseline_artifact_path",
        lambda suffix, baseline_run_id=None: baseline_dir / f"baseline_test_{suffix}",
    )

    def fail_if_loader_called(*_args, **_kwargs):
        raise AssertionError("_load_bikesharing_stations should not be called during materialize")

    monkeypatch.setattr(
        "synthesis.output_resources._load_bikesharing_stations",
        fail_if_loader_called,
    )

    record = {
        "source_output_path": str(destination),
        "source_output_prefix": f"{run_id}_",
        "run_id": run_id,
        "output_path": str(destination),
        "bikesharing_station_availability": {"toulouse:1": 9},
    }
    materialize_service.materialize_run_outputs(record)

    df = pd.read_csv(destination / f"{run_id}_bikesharing_stations.csv", sep=";")
    assert int(df["available_bikes"].iloc[0]) == 9


def test_materialize_keeps_baseline_bikesharing_without_overrides(monkeypatch, tmpdir):
    import pandas as pd

    from backend.app.services import materialize_service

    destination = Path(str(tmpdir.mkdir("destination3")))
    run_id = "run_bike_passthrough"
    baseline_dir = Path(str(tmpdir.mkdir("baselines2"))) / "baseline_test"
    baseline_dir.mkdir(parents=True)
    (baseline_dir / "baseline_test_bikesharing_stations.csv").write_text(
        "station_id;lat;lon;capacity;city_id;operator;city_station_id;available_bikes\n"
        "1;43.0;1.0;10;toulouse;op;toulouse:1;4\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        materialize_service,
        "baseline_artifact_path",
        lambda suffix, baseline_run_id=None: baseline_dir / f"baseline_test_{suffix}",
    )

    record = {
        "source_output_path": str(destination),
        "source_output_prefix": f"{run_id}_",
        "run_id": run_id,
        "output_path": str(destination),
        "bikesharing_station_availability": {},
    }
    materialize_service.materialize_run_outputs(record)

    df = pd.read_csv(destination / f"{run_id}_bikesharing_stations.csv", sep=";")
    assert int(df["available_bikes"].iloc[0]) == 4


def test_normalize_gbfs_localized_text_prefers_french_label():
    from synthesis.output_resources.resources import _normalize_gbfs_localized_text

    assert _normalize_gbfs_localized_text("Rue Jules Ferry") == "Rue Jules Ferry"
    assert (
        _normalize_gbfs_localized_text([{"text": "Le Monastier", "language": "fr"}])
        == "Le Monastier"
    )
    assert (
        _normalize_gbfs_localized_text(
            [{"text": "English", "language": "en"}, {"text": "Français", "language": "fr"}]
        )
        == "Français"
    )
