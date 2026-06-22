import json

import pandas as pd
import pytest

from synthesis.constraints.loader import assign_constraints, parse_person_constraints


_SAMPLE_CONSTRAINTS_YAML = """
version: 1
constraint_types:
  wheelchair_access_required:
    metric: wheelchair_accessible
    params: {}
    rule: "wheelchair_accessible == True"
  forbidden_modes:
    metric: modes
    params:
      forbidden: list[str]
    rule: "intersection(modes, forbidden) == empty"
  max_walk_distance_m:
    metric: walk_distance_m
    rule: "walk_distance_m <= max"
assignments:
  - id: forbidden_modes_child
    constraint_type: forbidden_modes
    when:
      - { field: age, op: "<=", value: 14 }
    params:
      forbidden: [bikesharing, car]
  - id: forbidden_modes_car_no_license
    constraint_type: forbidden_modes
    when:
      - { field: has_driving_license, op: "==", value: false }
      - { field: age, op: ">", value: 14 }
    params:
      forbidden: [car]
  - id: max_walk_distance_70plus
    constraint_type: max_walk_distance_m
    when:
      - { field: age, op: ">", value: 70 }
    params:
      max: 2000
  - id: wheelchair_working_age_sample
    when:
      - { field: age, op: "between", value: [15, 64] }
    sample:
      probability: 0.09
    assign:
      - id: wheelchair_access_required
        constraint_type: wheelchair_access_required
        params: {}
      - id: forbidden_modes_bike_bikesharing
        constraint_type: forbidden_modes
        params:
          forbidden: [bikesharing, bike]
"""


@pytest.fixture
def sample_constraints_path(tmp_path):
    path = tmp_path / "constraints.yml"
    path.write_text(_SAMPLE_CONSTRAINTS_YAML, encoding="utf-8")
    return path


def test_assign_constraints_child_no_license_elderly(sample_constraints_path):
    df_persons = pd.DataFrame(
        [
            {"person_id": "child", "age": 10, "has_driving_license": False},
            {"person_id": "adult", "age": 40, "has_driving_license": True},
            {"person_id": "elder", "age": 75, "has_driving_license": True},
            {"person_id": "no_license", "age": 40, "has_driving_license": False},
        ]
    )

    result = assign_constraints(df_persons, sample_constraints_path, random_seed=42)
    by_person = {
        row["person_id"]: json.loads(row["constraints"])
        for _, row in result.iterrows()
    }

    assert by_person["child"] == [
        {
            "constraint_type": "forbidden_modes",
            "params": {"forbidden": ["bikesharing", "car"]},
            "id": "forbidden_modes_child",
        },
    ]
    assert by_person["adult"] == []
    assert by_person["elder"] == [
        {
            "constraint_type": "max_walk_distance_m",
            "params": {"max": 2000},
            "id": "max_walk_distance_70plus",
        },
    ]
    assert by_person["no_license"] == [
        {
            "constraint_type": "forbidden_modes",
            "params": {"forbidden": ["car"]},
            "id": "forbidden_modes_car_no_license",
        },
    ]


def test_assign_constraints_wheelchair_sample_is_deterministic(sample_constraints_path):
    rows = [{"person_id": f"p{i}", "age": 20 + (i % 40), "has_driving_license": True} for i in range(1000)]
    df_persons = pd.DataFrame(rows)

    first = assign_constraints(df_persons, sample_constraints_path, random_seed=1234)
    second = assign_constraints(df_persons, sample_constraints_path, random_seed=1234)

    first_flags = {
        row["person_id"]: json.loads(row["constraints"])
        for _, row in first.iterrows()
    }
    second_flags = {
        row["person_id"]: json.loads(row["constraints"])
        for _, row in second.iterrows()
    }
    assert first_flags == second_flags

    sampled = [person_id for person_id, constraints in first_flags.items() if constraints]
    assert len(sampled) == pytest.approx(1000 * 0.09, rel=0.2)
    for constraints in first_flags.values():
        if not constraints:
            continue
        assert constraints == [
            {
                "id": "wheelchair_access_required",
                "constraint_type": "wheelchair_access_required",
                "params": {},
            },
            {
                "id": "forbidden_modes_bike_bikesharing",
                "constraint_type": "forbidden_modes",
                "params": {"forbidden": ["bikesharing", "bike"]},
            },
        ]


def test_assign_constraints_direct_itinerary_tiered_probability(tmp_path):
    path = tmp_path / "constraints.yml"
    path.write_text(
        """
version: 1
constraint_types:
  direct_itinerary:
    metric: nb_transfers
    params: {}
    rule: "nb_transfers == 0"
assignments:
  - id: direct_itinerary
    sample:
      tiers:
        - when:
            - { field: age, op: "<", value: 25 }
          probability: 1.0
        - when:
            - { field: age, op: "between", value: [25, 64] }
          probability: 0.0
    assign:
      - id: direct_itinerary
        constraint_type: direct_itinerary
        params: {}
""".strip(),
        encoding="utf-8",
    )
    df_persons = pd.DataFrame(
        [
            {"person_id": "young", "age": 20},
            {"person_id": "adult", "age": 40},
            {"person_id": "senior", "age": 80},
        ]
    )

    result = assign_constraints(df_persons, path, random_seed=42)
    by_person = {
        row["person_id"]: json.loads(row["constraints"])
        for _, row in result.iterrows()
    }

    payload = [
        {
            "id": "direct_itinerary",
            "constraint_type": "direct_itinerary",
            "params": {},
        }
    ]
    assert by_person["young"] == payload
    assert by_person["adult"] == []
    assert by_person["senior"] == []


def test_parse_person_constraints_handles_json_and_empty():
    payload = [
        {
            "id": "forbidden_modes_car_no_license",
            "constraint_type": "forbidden_modes",
            "params": {"forbidden": ["car"]},
        }
    ]
    assert parse_person_constraints(json.dumps(payload)) == payload
    assert parse_person_constraints("[]") == []
    assert parse_person_constraints(None) == []
    assert parse_person_constraints(payload) == payload
