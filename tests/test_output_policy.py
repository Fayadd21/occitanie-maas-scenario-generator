import pandas as pd
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
import types

_POLICY_PATH = Path(__file__).resolve().parents[1] / "synthesis" / "output" / "policy.py"
_POLICY_SPEC = spec_from_file_location("output_policy_module", _POLICY_PATH)
_POLICY_MODULE = module_from_spec(_POLICY_SPEC)
assert _POLICY_SPEC and _POLICY_SPEC.loader
if "geopandas" not in sys.modules:
    sys.modules["geopandas"] = types.SimpleNamespace(GeoDataFrame=object, sjoin=lambda *args, **kwargs: None)
_POLICY_SPEC.loader.exec_module(_POLICY_MODULE)
apply_population_policy = _POLICY_MODULE.apply_population_policy
_choose_households_for_targets = _POLICY_MODULE._choose_households_for_targets
_choose_households_for_dual_targets = _POLICY_MODULE._choose_households_for_dual_targets
_select_households_edge_then_random = _POLICY_MODULE._select_households_edge_then_random


def _edge_population(selected: set, household_sizes: pd.Series, dist_to_edge: pd.Series, *, edge_threshold: float) -> int:
    total = 0
    for household_id in selected:
        if float(dist_to_edge[household_id]) <= edge_threshold:
            total += int(household_sizes[household_id])
    return total


class _DummyLocations:
    crs = "EPSG:2154"


def test_outskirts_bias_prefers_smaller_distance_to_edge():
    household_sizes = pd.Series({"near": 1, "far": 1, "mid": 1})
    dist_to_edge = pd.Series({"near": 10.0, "mid": 500.0, "far": 1000.0})
    selected = _choose_households_for_targets(
        household_sizes,
        target_households=1,
        target_population=None,
        household_scores=dist_to_edge,
        outskirts_bias=1.0,
        random_seed=42,
    )
    assert selected == {"near"}


def test_outskirts_bias_half_population_from_edge_then_random():
    ids = [f"h{i}" for i in range(20)]
    household_sizes = pd.Series(1, index=ids)
    dist_to_edge = pd.Series({household_id: float(i) for i, household_id in enumerate(ids)})
    selected = _select_households_edge_then_random(
        household_sizes,
        target_households=20,
        target_population=20,
        household_scores=dist_to_edge,
        outskirts_bias=0.5,
        random_seed=42,
    )
    assert len(selected) == 20
    assert {f"h{i}" for i in range(10)}.issubset(selected)


def test_dual_targets_ten_ten_reaches_both_caps_with_outskirts_bias():
    household_sizes = pd.Series(
        {
            "big_a": 3,
            "big_b": 3,
            "big_c": 2,
            "s1": 1,
            "s2": 1,
            "s3": 1,
            "s4": 1,
            "s5": 1,
            "s6": 1,
            "s7": 1,
            "s8": 1,
            "s9": 1,
            "s10": 1,
        }
    )
    dist_to_edge = pd.Series(
        {
            "big_a": 0.0,
            "big_b": 5.0,
            "big_c": 10.0,
            "s1": 20.0,
            "s2": 25.0,
            "s3": 30.0,
            "s4": 35.0,
            "s5": 40.0,
            "s6": 45.0,
            "s7": 50.0,
            "s8": 55.0,
            "s9": 60.0,
            "s10": 65.0,
        }
    )
    selected = _choose_households_for_dual_targets(
        household_sizes,
        target_households=10,
        target_population=10,
        household_scores=dist_to_edge,
        outskirts_bias=0.5,
        random_seed=42,
    )
    assert len(selected) == 10
    assert int(household_sizes[list(selected)].sum()) == 10


def test_outskirts_bias_differs_between_low_and_full_bias_with_multi_person_households():
    household_sizes = pd.Series(
        {
            "edge_a": 4,
            "edge_b": 4,
            "edge_c": 4,
            "far_a": 2,
            "far_b": 2,
            "far_c": 2,
            "far_d": 2,
            "far_e": 2,
            "far_f": 2,
        }
    )
    dist_to_edge = pd.Series(
        {
            "edge_a": 5.0,
            "edge_b": 15.0,
            "edge_c": 25.0,
            "far_a": 400.0,
            "far_b": 500.0,
            "far_c": 600.0,
            "far_d": 700.0,
            "far_e": 800.0,
            "far_f": 900.0,
        }
    )
    low = _choose_households_for_dual_targets(
        household_sizes,
        target_households=5,
        target_population=10,
        household_scores=dist_to_edge,
        outskirts_bias=0.05,
        random_seed=42,
    )
    high = _choose_households_for_dual_targets(
        household_sizes,
        target_households=5,
        target_population=10,
        household_scores=dist_to_edge,
        outskirts_bias=1.0,
        random_seed=42,
    )
    low_edge_pop = _edge_population(low, household_sizes, dist_to_edge, edge_threshold=50.0)
    high_edge_pop = _edge_population(high, household_sizes, dist_to_edge, edge_threshold=50.0)
    assert low_edge_pop < high_edge_pop
    assert high_edge_pop >= 8


def test_outskirts_bias_low_value_takes_few_edge_persons():
    ids = [f"h{i}" for i in range(20)]
    household_sizes = pd.Series(1, index=ids)
    dist_to_edge = pd.Series({household_id: float(i) for i, household_id in enumerate(ids)})
    selected = _select_households_edge_then_random(
        household_sizes,
        target_households=20,
        target_population=20,
        household_scores=dist_to_edge,
        outskirts_bias=0.05,
        random_seed=42,
    )
    assert "h0" in selected
    assert "h19" in selected


def test_policy_applies_household_and_population_targets_without_geo_filter():
    df_persons = pd.DataFrame(
        [
            {"person_id": 1, "household_id": "h1"},
            {"person_id": 2, "household_id": "h1"},
            {"person_id": 3, "household_id": "h2"},
            {"person_id": 4, "household_id": "h2"},
            {"person_id": 5, "household_id": "h3"},
        ]
    )
    df_activities = pd.DataFrame(
        [
            {"person_id": 1, "household_id": "h1", "purpose": "home", "geometry": None},
            {"person_id": 2, "household_id": "h1", "purpose": "home", "geometry": None},
            {"person_id": 3, "household_id": "h2", "purpose": "home", "geometry": None},
            {"person_id": 4, "household_id": "h2", "purpose": "home", "geometry": None},
            {"person_id": 5, "household_id": "h3", "purpose": "home", "geometry": None},
        ]
    )

    filtered_persons, filtered_activities, selected_person_ids = apply_population_policy(
        df_persons=df_persons,
        df_activities=df_activities,
        df_locations=_DummyLocations(),
        population_filter_geojson=None,
        target_population=3,
        target_households=2,
    )

    assert len(filtered_persons["person_id"].unique()) == 3
    assert len(filtered_persons["household_id"].unique()) <= 2
    assert set(filtered_activities["person_id"].unique()) == set(filtered_persons["person_id"].unique())
    assert selected_person_ids is not None


def test_population_target_keeps_whole_households():
    df_persons = pd.DataFrame(
        [
            {"person_id": 1, "household_id": "h1"},
            {"person_id": 2, "household_id": "h1"},
            {"person_id": 3, "household_id": "h2"},
            {"person_id": 4, "household_id": "h3"},
            {"person_id": 5, "household_id": "h3"},
        ]
    )
    df_activities = pd.DataFrame(
        [
            {"person_id": i, "household_id": hid, "purpose": "home", "geometry": None}
            for i, hid in [(1, "h1"), (2, "h1"), (3, "h2"), (4, "h3"), (5, "h3")]
        ]
    )

    filtered_persons, _, _ = apply_population_policy(
        df_persons=df_persons,
        df_activities=df_activities,
        df_locations=_DummyLocations(),
        population_filter_geojson=None,
        target_population=2,
        target_households=None,
        random_seed=42,
    )

    assert len(filtered_persons["person_id"].unique()) == 2
    assert len(filtered_persons["household_id"].unique()) == 1


def test_dual_targets_stop_when_population_cap_reached_before_household_cap():
    persons = []
    activities = []
    for household_index in range(80):
        household_id = f"h{household_index}"
        person_id = household_index + 1
        persons.append({"person_id": person_id, "household_id": household_id})
        activities.append(
            {"person_id": person_id, "household_id": household_id, "purpose": "home", "geometry": None}
        )
    df_persons = pd.DataFrame(persons)
    df_activities = pd.DataFrame(activities)

    filtered_persons, _, _ = apply_population_policy(
        df_persons=df_persons,
        df_activities=df_activities,
        df_locations=_DummyLocations(),
        population_filter_geojson=None,
        target_population=500,
        target_households=100,
    )

    assert len(filtered_persons["household_id"].unique()) == 80
    assert len(filtered_persons["person_id"].unique()) == 80


def test_dual_targets_prefers_households_near_target_average_size():
    persons = []
    activities = []
    for household_index in range(120):
        household_id = f"h{household_index}"
        person_id = household_index + 1
        persons.append({"person_id": person_id, "household_id": household_id})
        activities.append(
            {"person_id": person_id, "household_id": household_id, "purpose": "home", "geometry": None}
        )
    df_persons = pd.DataFrame(persons)
    df_activities = pd.DataFrame(activities)

    filtered_persons, _, _ = apply_population_policy(
        df_persons=df_persons,
        df_activities=df_activities,
        df_locations=_DummyLocations(),
        population_filter_geojson=None,
        target_population=100,
        target_households=100,
        random_seed=42,
    )

    assert len(filtered_persons["household_id"].unique()) == 100
    assert len(filtered_persons["person_id"].unique()) == 100


def test_dual_targets_stop_when_no_household_fits_population_cap():
    df_persons = pd.DataFrame(
        [
            {"person_id": 1, "household_id": "h1"},
            {"person_id": 2, "household_id": "h2"},
        ]
    )
    df_activities = pd.DataFrame(
        [
            {"person_id": 1, "household_id": "h1", "purpose": "home", "geometry": None},
            {"person_id": 2, "household_id": "h2", "purpose": "home", "geometry": None},
        ]
    )

    filtered_persons, _, _ = apply_population_policy(
        df_persons=df_persons,
        df_activities=df_activities,
        df_locations=_DummyLocations(),
        population_filter_geojson=None,
        target_population=1,
        target_households=10,
    )

    assert len(filtered_persons["person_id"].unique()) == 1
    assert len(filtered_persons["household_id"].unique()) == 1
