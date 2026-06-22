from __future__ import annotations

import pandas as pd

from synthesis.output.baseline_spatial import (
    needs_geometry_for_profiles,
    spatial_subset_unchanged,
)


def test_spatial_subset_unchanged_when_counts_match():
    df_persons = pd.DataFrame({"person_id": [1, 2]})
    df_activities = pd.DataFrame({"person_id": [1, 2, 1], "activity_index": [0, 0, 1]})
    assert spatial_subset_unchanged(
        baseline_mode=True,
        population_filter_geojson=None,
        initial_person_count=2,
        initial_activity_count=3,
        df_persons=df_persons,
        df_activities=df_activities,
    )


def test_spatial_subset_unchanged_false_when_subset():
    df_persons = pd.DataFrame({"person_id": [1]})
    df_activities = pd.DataFrame({"person_id": [1], "activity_index": [0]})
    assert not spatial_subset_unchanged(
        baseline_mode=True,
        population_filter_geojson=None,
        initial_person_count=2,
        initial_activity_count=3,
        df_persons=df_persons,
        df_activities=df_activities,
    )


def test_needs_geometry_for_profiles_skips_precomputed_column(tmp_path):
    profiles_path = tmp_path / "profiles.yml"
    profiles_path.write_text(
        """
profiles:
  - id: prefers_bike
    rules:
      - { field: home_destination_distance_km, op: "<", value: 5, points: 1 }
    preferences:
      - { id: a, metric: duration, objective: minimize, weight: 1 }
""".strip(),
        encoding="utf-8",
    )
    df_persons = pd.DataFrame({"person_id": ["p1"], "home_destination_distance_km": [2.0]})
    assert not needs_geometry_for_profiles(df_persons, True, str(profiles_path))


def test_needs_geometry_for_profiles_when_column_missing(tmp_path):
    profiles_path = tmp_path / "profiles.yml"
    profiles_path.write_text(
        """
profiles:
  - id: prefers_bike
    rules:
      - { field: home_destination_distance_km, op: "<", value: 5, points: 1 }
    preferences:
      - { id: a, metric: duration, objective: minimize, weight: 1 }
""".strip(),
        encoding="utf-8",
    )
    df_persons = pd.DataFrame({"person_id": ["p1"]})
    assert needs_geometry_for_profiles(df_persons, True, str(profiles_path))
