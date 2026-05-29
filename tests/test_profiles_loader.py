import pandas as pd

from synthesis.profiles.loader import assign_latent_classes, list_profile_summaries, preferences_for_profile

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
