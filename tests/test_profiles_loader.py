import pandas as pd
import pytest

from synthesis.profiles.loader import (
    assign_latent_classes,
    attach_home_destination_distance,
    latent_class_filter_restricts_pool,
    list_profile_summaries,
    merge_household_attributes,
    preferences_for_profile,
)

_SAMPLE_PROFILES_YAML = """
version: 1
latent_class_noise_std: 0.3
default_allowed:
  - cost_efficient
  - prefers_bike
  - prefers_pt
profile_order:
  - cost_efficient
  - prefers_bike
  - prefers_pt
profiles:
  - id: cost_efficient
    rules:
      - { field: household_income, op: "<", value: 1800, points: 2 }
      - { field: car_availability, op: "not_in", value: [all, some], points: 1 }
      - { field: has_pt_subscription, op: "==", value: true, points: 1 }
      - { field: bike_availability, op: "==", value: all, points: 0.5 }
    preferences:
      - { id: fastest_route, metric: duration, objective: minimize, weight: 0.10 }
      - { id: shortest_distance, metric: distance, objective: minimize, weight: 0.10 }
      - { id: cheapest_option, metric: price, objective: minimize, weight: 0.80 }
  - id: prefers_bike
    rules:
      - { field: bike_availability, op: "==", value: all, points: 2 }
      - { field: age, op: between, value: [16, 55], points: 1 }
      - { field: car_availability, op: "not_in", value: [all, some], points: 0.5 }
    preferences:
      - { id: fastest_route, metric: duration, objective: minimize, weight: 0.35 }
      - { id: shortest_distance, metric: distance, objective: minimize, weight: 0.40 }
      - { id: cheapest_option, metric: price, objective: minimize, weight: 0.25 }
  - id: prefers_pt
    rules:
      - { field: has_pt_subscription, op: "==", value: true, points: 2 }
      - { field: car_availability, op: "not_in", value: [all, some], points: 1 }
      - { field: household_income, op: "<", value: 2200, points: 1 }
    preferences:
      - { id: fastest_route, metric: duration, objective: minimize, weight: 0.45 }
      - { id: shortest_distance, metric: distance, objective: minimize, weight: 0.05 }
      - { id: cheapest_option, metric: price, objective: minimize, weight: 0.50 }
""".strip()


def _sample_profiles_path(tmp_path):
    profiles_path = tmp_path / "profiles.yml"
    profiles_path.write_text(_SAMPLE_PROFILES_YAML, encoding="utf-8")
    return profiles_path


def test_list_profile_summaries(tmp_path):
    payload = list_profile_summaries(_sample_profiles_path(tmp_path))
    assert len(payload["profiles"]) == 3
    assert all("id" in p and p["id"] for p in payload["profiles"]), "Every profile summary must include an id"
    assert payload["default_allowed"] == ["cost_efficient", "prefers_bike", "prefers_pt"]
    assert payload["latent_class_noise_std"] == 0.3


def test_latent_class_filter_restricts_pool(tmp_path):
    profiles_path = _sample_profiles_path(tmp_path)
    all_classes = ["cost_efficient", "prefers_bike", "prefers_pt"]
    assert latent_class_filter_restricts_pool(None, profiles_path) is False
    assert latent_class_filter_restricts_pool(all_classes, profiles_path) is False
    assert latent_class_filter_restricts_pool(["cost_efficient", "prefers_bike"], profiles_path) is True


def test_assign_latent_classes_from_profiles(tmp_path):
    df_persons = pd.DataFrame(
        [
            {
                "person_id": 1,
                "household_id": "h1",
                "age": 20,
                "employed": False,
                "has_pt_subscription": True,
                "has_driving_license": False,
            }
        ]
    )
    df_households = pd.DataFrame(
        [
            {
                "household_id": "h1",
                "car_availability": "none",
                "bike_availability": "all",
                "income": 1500,
            }
        ]
    )
    result = assign_latent_classes(
        df_persons,
        _sample_profiles_path(tmp_path),
        df_households=df_households,
    )
    assert str(result.loc[0, "latent_class"]) in {
        "cost_efficient",
        "prefers_bike",
        "prefers_pt",
    }


def test_assign_latent_classes_commune_id_rules(tmp_path):
    profiles_path = tmp_path / "profiles_commune.yml"
    profiles_path.write_text(
        """
version: 1
profile_order:
  - prefers_bike
  - prefers_car
profiles:
  - id: prefers_bike
    rules:
      - { field: commune_id, op: in, value: ["31555"], points: 10 }
      - { field: age, op: ">", value: 0, points: 0 }
    preferences:
      - { id: a, metric: duration, objective: minimize, weight: 1 }
  - id: prefers_car
    rules:
      - { field: age, op: ">", value: 0, points: 1 }
    preferences:
      - { id: a, metric: duration, objective: minimize, weight: 1 }
""".strip(),
        encoding="utf-8",
    )
    df_persons = pd.DataFrame([{"person_id": 1, "household_id": "h1", "age": 30}])
    df_households = pd.DataFrame([{"household_id": "h1", "commune_id": 31555.0}])
    result = assign_latent_classes(df_persons, profiles_path, df_households=df_households)
    assert str(result.loc[0, "latent_class"]) == "prefers_bike"


def test_merge_household_attributes_coerces_household_id_types():
    df_persons = pd.DataFrame([{"person_id": 1, "household_id": 42, "age": 30}])
    df_households = pd.DataFrame([{"household_id": "42", "commune_id": 31069.0}])
    merged = merge_household_attributes(df_persons, df_households)
    assert merged.loc[0, "commune_id"] == 31069.0


class _Point:
    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y


def test_attach_home_destination_distance_applies_circuity_factor():
    df_persons = pd.DataFrame([{"person_id": "p1", "age": 30}])
    df_activities = pd.DataFrame(
        [
            {"person_id": "p1", "activity_index": 0, "purpose": "home", "geometry": _Point(1.444, 43.604)},
            {"person_id": "p1", "activity_index": 1, "purpose": "work", "geometry": _Point(1.450, 43.610)},
        ]
    )
    result = attach_home_destination_distance(df_persons, df_activities)
    from synthesis.profiles.loader import _HOME_DESTINATION_CIRCUITY_FACTOR, _haversine_km_vector

    raw = float(
        _haversine_km_vector(
            pd.Series([43.604]),
            pd.Series([1.444]),
            pd.Series([43.610]),
            pd.Series([1.450]),
        ).iloc[0]
    )
    assert result.loc[0, "home_destination_distance_km"] == pytest.approx(raw * _HOME_DESTINATION_CIRCUITY_FACTOR)


def test_attach_home_destination_distance_work(tmp_path):
    df_persons = pd.DataFrame([{"person_id": "p1", "age": 30}])
    df_activities = pd.DataFrame(
        [
            {"person_id": "p1", "activity_index": 0, "purpose": "home", "geometry": _Point(1.444, 43.604)},
            {"person_id": "p1", "activity_index": 1, "purpose": "work", "geometry": _Point(1.450, 43.610)},
        ]
    )
    result = attach_home_destination_distance(df_persons, df_activities)
    assert result.loc[0, "home_destination_distance_km"] > 0.5
    assert result.loc[0, "home_destination_distance_km"] < 2.0


def test_attach_home_destination_distance_education_fallback():
    df_persons = pd.DataFrame([{"person_id": "p1", "age": 16}])
    df_activities = pd.DataFrame(
        [
            {"person_id": "p1", "activity_index": 0, "purpose": "home", "geometry": _Point(1.0, 43.0)},
            {"person_id": "p1", "activity_index": 1, "purpose": "education", "geometry": _Point(1.1, 43.0)},
        ]
    )
    result = attach_home_destination_distance(df_persons, df_activities)
    assert result.loc[0, "home_destination_distance_km"] > 5.0


def test_attach_home_destination_distance_lambert93():
    geopandas = pytest.importorskip("geopandas")
    from shapely.geometry import Point

    gpd = geopandas
    df_persons = pd.DataFrame([{"person_id": "p1", "age": 30}])
    df_activities = gpd.GeoDataFrame(
        [
            {"person_id": "p1", "activity_index": 0, "purpose": "home", "geometry": Point(564600.45, 6212636.06)},
            {"person_id": "p1", "activity_index": 1, "purpose": "work", "geometry": Point(563950.0, 6212650.0)},
        ],
        geometry="geometry",
        crs="EPSG:2154",
    )
    result = attach_home_destination_distance(df_persons, df_activities)
    assert result.loc[0, "home_destination_distance_km"] < 20.0


def test_persons_have_home_destination_distance_rejects_projected_misread():
    from synthesis.profiles.loader import persons_have_home_destination_distance

    df_persons = pd.DataFrame({"person_id": ["p1"], "home_destination_distance_km": [5508.0]})
    assert persons_have_home_destination_distance(df_persons) is False


def test_assign_latent_classes_home_destination_distance_rules(tmp_path):
    profiles_path = tmp_path / "profiles_distance.yml"
    profiles_path.write_text(
        """
version: 1
profile_order:
  - prefers_bike
  - prefers_car
profiles:
  - id: prefers_bike
    rules:
      - { field: home_destination_distance_km, op: "<", value: 2, points: 10 }
    preferences:
      - { id: a, metric: duration, objective: minimize, weight: 1 }
  - id: prefers_car
    rules:
      - { field: age, op: ">", value: 0, points: 1 }
    preferences:
      - { id: a, metric: duration, objective: minimize, weight: 1 }
""".strip(),
        encoding="utf-8",
    )
    df_persons = pd.DataFrame([{"person_id": "p1", "age": 30}])
    df_activities = pd.DataFrame(
        [
            {"person_id": "p1", "activity_index": 0, "purpose": "home", "geometry": _Point(1.444, 43.604)},
            {"person_id": "p1", "activity_index": 1, "purpose": "work", "geometry": _Point(1.450, 43.610)},
        ]
    )
    df_persons = attach_home_destination_distance(df_persons, df_activities)
    result = assign_latent_classes(df_persons, profiles_path)
    assert str(result.loc[0, "latent_class"]) == "prefers_bike"


def test_preferences_for_profile_reads_yaml(tmp_path):
    preferences = preferences_for_profile("prefers_bike", _sample_profiles_path(tmp_path), request_index=3)
    assert len(preferences) == 3
    assert abs(sum(row["weight"] for row in preferences) - 1.0) < 1e-6


def test_preferences_normalize_weights_when_sum_is_not_one(tmp_path):
    profiles_path = tmp_path / "profiles_normalize.yml"
    profiles_path.write_text(
        """
version: 1
profiles:
  - id: test_profile
    rules:
      - { field: age, op: ">", value: 0, points: 1 }
    preferences:
      - { id: a, metric: duration, objective: minimize, weight: 2 }
      - { id: b, metric: distance, objective: minimize, weight: 2 }
      - { id: c, metric: price, objective: minimize, weight: 2 }
""".strip(),
        encoding="utf-8",
    )
    preferences = preferences_for_profile("test_profile", profiles_path, request_index=0)
    assert len(preferences) == 3
    assert abs(sum(row["weight"] for row in preferences) - 1.0) < 1e-9
    assert all(abs(row["weight"] - (1.0 / 3.0)) < 1e-9 for row in preferences)


def test_assign_latent_classes_deterministic_without_noise(tmp_path):
    profiles_path = tmp_path / "profiles_no_noise.yml"
    profiles_path.write_text(
        """
version: 1
latent_class_noise_std: 0
profiles:
  - id: cost_efficient
    rules: []
    preferences:
      - { id: a, metric: duration, objective: minimize, weight: 1 }
profile_order:
  - cost_efficient
""".strip(),
        encoding="utf-8",
    )
    df_persons = pd.DataFrame(
        [
            {
                "person_id": 1,
                "household_id": "h1",
                "age": 20,
                "employed": False,
                "has_pt_subscription": True,
                "has_driving_license": False,
            }
        ]
    )
    df_households = pd.DataFrame(
        [
            {
                "household_id": "h1",
                "car_availability": "none",
                "bike_availability": "all",
                "income": 1500,
            }
        ]
    )
    first = assign_latent_classes(
        df_persons,
        profiles_path,
        df_households=df_households,
        random_seed=42,
    )
    second = assign_latent_classes(
        df_persons,
        profiles_path,
        df_households=df_households,
        random_seed=99,
    )
    assert str(first.loc[0, "latent_class"]) == str(second.loc[0, "latent_class"])


def test_assign_latent_classes_noise_std_does_not_change_assignment(tmp_path):
    profiles_path = tmp_path / "profiles_noise.yml"
    profiles_path.write_text(
        """
version: 1
latent_class_noise_std: 2.0
profiles:
  - id: profile_a
    rules:
      - { field: age, op: ">", value: 0, points: 1 }
    preferences:
      - { id: a, metric: duration, objective: minimize, weight: 1 }
  - id: profile_b
    rules:
      - { field: age, op: ">", value: 0, points: 1.01 }
    preferences:
      - { id: b, metric: duration, objective: minimize, weight: 1 }
profile_order:
  - profile_a
  - profile_b
""".strip(),
        encoding="utf-8",
    )
    df_persons = pd.DataFrame([{"person_id": 1, "age": 30}])
    no_noise_path = tmp_path / "profiles_no_noise_tie.yml"
    no_noise_path.write_text(
        profiles_path.read_text(encoding="utf-8").replace("latent_class_noise_std: 2.0", "latent_class_noise_std: 0"),
        encoding="utf-8",
    )
    deterministic = assign_latent_classes(df_persons, no_noise_path)
    assert str(deterministic.loc[0, "latent_class"]) == "profile_b"

    assignments = {
        str(assign_latent_classes(df_persons, profiles_path, random_seed=seed).loc[0, "latent_class"])
        for seed in range(30)
    }
    assert assignments == {"profile_b"}


def test_preferences_noise_perturbs_selected_weight(tmp_path):
    profiles_path = tmp_path / "profiles_noise_weight.yml"
    profiles_path.write_text(
        """
version: 1
latent_class_noise_std: 0.2
profiles:
  - id: test_profile
    rules: []
    preferences:
      - { id: fastest_route, metric: duration, objective: minimize, weight: 0.6, noise_target: true }
      - { id: shortest_distance, metric: distance, objective: minimize, weight: 0.2 }
      - { id: cheapest_option, metric: price, objective: minimize, weight: 0.2 }
""".strip(),
        encoding="utf-8",
    )
    run_a = preferences_for_profile("test_profile", profiles_path, request_index=1)
    run_b = preferences_for_profile("test_profile", profiles_path, request_index=2)

    assert abs(sum(row["weight"] for row in run_a) - 1.0) < 1e-9
    assert abs(sum(row["weight"] for row in run_b) - 1.0) < 1e-9
    assert abs(run_a[0]["weight"] - run_b[0]["weight"]) > 1e-6


def test_preferences_noise_perturbs_multiple_targets(tmp_path):
    profiles_path = tmp_path / "profiles_noise_multi_target.yml"
    profiles_path.write_text(
        """
version: 1
latent_class_noise_std: 0.2
profiles:
  - id: test_profile
    rules: []
    preferences:
      - { id: fastest_route, metric: duration, objective: minimize, weight: 0.5, noise_target: true }
      - { id: cheapest_option, metric: price, objective: minimize, weight: 0.3, noise_target: true }
      - { id: shortest_distance, metric: distance, objective: minimize, weight: 0.2 }
""".strip(),
        encoding="utf-8",
    )
    run_a = preferences_for_profile("test_profile", profiles_path, request_index=1)
    run_b = preferences_for_profile("test_profile", profiles_path, request_index=2)

    assert abs(sum(row["weight"] for row in run_a) - 1.0) < 1e-9
    assert abs(sum(row["weight"] for row in run_b) - 1.0) < 1e-9
    assert abs(run_a[0]["weight"] - run_b[0]["weight"]) > 1e-6
    assert abs(run_a[1]["weight"] - run_b[1]["weight"]) > 1e-6


def test_preferences_noise_not_applied_without_noise_target(tmp_path):
    profiles_path = tmp_path / "profiles_noise_without_target.yml"
    profiles_path.write_text(
        """
version: 1
latent_class_noise_std: 0.2
profiles:
  - id: test_profile
    rules: []
    preferences:
      - { id: fastest_route, metric: duration, objective: minimize, weight: 0.6 }
      - { id: shortest_distance, metric: distance, objective: minimize, weight: 0.2 }
      - { id: cheapest_option, metric: price, objective: minimize, weight: 0.2 }
""".strip(),
        encoding="utf-8",
    )
    run_a = preferences_for_profile("test_profile", profiles_path, request_index=1)
    run_b = preferences_for_profile("test_profile", profiles_path, request_index=2)
    assert [row["weight"] for row in run_a] == [row["weight"] for row in run_b]


def test_preferences_support_more_than_three_objectives(tmp_path):
    profiles_path = tmp_path / "profiles_extra.yml"
    profiles_path.write_text(
        """
version: 1
profiles:
  - id: test_profile
    rules:
      - { field: age, op: ">", value: 0, points: 1 }
    preferences:
      - { id: fastest_route, metric: duration, objective: minimize, weight: 0.25 }
      - { id: shortest_distance, metric: distance, objective: minimize, weight: 0.25 }
      - { id: cheapest_option, metric: price, objective: minimize, weight: 0.25 }
      - { id: low_co2, metric: co2, objective: minimize, weight: 0.25 }
""".strip(),
        encoding="utf-8",
    )
    preferences = preferences_for_profile("test_profile", profiles_path, request_index=0)
    assert len(preferences) == 4
    assert {row["preference_type"]["metric"] for row in preferences} == {
        "duration",
        "distance",
        "price",
        "co2",
    }
