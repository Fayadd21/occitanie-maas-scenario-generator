# Person constraints

Constraints tag individuals in the synthetic population with mobility rules that the
downstream scenario router must enforce (forbidden modes, max walk distance, direct
itinerary, wheelchair access, and so on).

They are **not** the same as latent classes:

| | Latent classes | Constraints |
|--|----------------|-------------|
| Config | `backend/config/profiles.yml` | `backend/config/constraints.yml` |
| When assigned | Scenario jobs (`assign_latent_classes: true`) | **Baseline build only** |
| Column on `persons.csv` | `latent_class` | `constraints` (JSON list) |
| Purpose | Preference weights per class | Hard feasibility rules per person |

## Config file

Edit **`backend/config/constraints.yml`**. Unlike `profiles.yml`.

Implementation: `synthesis/constraints/loader.py`  
Tests: `tests/test_constraints_loader.py`

After changing the YAML, **rebuild the baseline** (`POST /baseline/rebuild` or **Build
baseline** in the UI). Scenario jobs reload persons from the baseline; they do not
re-run constraint assignment.

## YAML layout

```yaml
version: 1

constraint_types:
  # Catalog for the router: metric, params schema, rule expression.
  forbidden_modes:
    metric: modes
    params:
      forbidden: list[str]
    rule: "intersection(modes, forbidden) == empty"

assignments:
  # Who gets which constraint instances at baseline synthesis.
  - id: forbidden_modes_child
    constraint_type: forbidden_modes
    when:
      - { field: age, op: "<=", value: 14 }
    params:
      forbidden: [bikesharing, car]
```

### `constraint_types`

Describes each constraint **type** for documentation and for the router. The synthesis
pipeline does not evaluate `rule` or `metric`; it only copies `constraint_type` and
`params` onto each person.

### `assignments`

Defines **who** receives constraints. Each matching assignment appends one or more
constraint objects to that person's list.

## Exported shape

Each person stores a JSON array in the `constraints` column of `persons.csv`:

```json
[
  {
    "id": "forbidden_modes_child",
    "constraint_type": "forbidden_modes",
    "params": { "forbidden": ["bikesharing", "car"] }
  }
]
```

`GET /jobs/{id}/scenario.json` copies the same list onto each **person** and onto every
**request** for that person (activity-chain legs). The router reads `constraint_type` and
`params`; `id` is a stable label for debugging.

## Assignment patterns

### 1. Deterministic rule

Everyone matching `when` gets the constraint:

```yaml
  - id: max_walk_distance_70plus
    constraint_type: max_walk_distance_m
    when:
      - { field: age, op: ">", value: 70 }
    params:
      max: 2000
```

### 2. Flat random sample

A fixed share of eligible persons is sampled (seed-stable per `person_id`):

```yaml
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
```

Use `assign` to attach **several** constraints from one sampled draw.

The shipped `wheelchair_working_age_sample` rule uses **`probability: 0.09`** (9%) for
persons aged 15–64. That rate matches the share of 15–64 year-olds in **Occitanie** with
an **official recognition of handicap or loss of autonomy** in the
[Agefiph tableau de bord Occitanie (TB N°2025-1, July 2025)](https://www.agefiph.fr/sites/default/files/medias/fichiers/2025-07/TB%20N%C2%B02025-1-%20Occitanie.pdf)
(table *Le handicap et la santé*, source: Enquête Vie quotidienne et santé 2021, DREES).

Update `probability` in `constraints.yml` if you retarget a newer
statistical release.

### 3. Age-tiered probabilities

One assignment, different `probability` per tier (first matching tier wins):

```yaml
  - id: direct_itinerary
    sample:
      tiers:
        - when:
            - { field: age, op: "<", value: 25 }
          probability: 0.10
        - when:
            - { field: age, op: "between", value: [25, 64] }
          probability: 0.15
        - when:
            - { field: age, op: "between", value: [65, 74] }
          probability: 0.20
        - when:
            - { field: age, op: ">=", value: 75 }
          probability: 0.30
    assign:
      - id: direct_itinerary
        constraint_type: direct_itinerary
        params: {}
```

Omit top-level `when` to consider all persons; tiers then select the probability.

## `when` rules

Rules are combined with **AND** (all must match). Supported operators:

| Operator | Example |
|----------|---------|
| `==` | `{ field: has_driving_license, op: "==", value: false }` |
| `<`, `<=`, `>`, `>=` | `{ field: age, op: "<=", value: 14 }` |
| `between` | `{ field: age, op: "between", value: [15, 64] }` (inclusive) |
| `in`, `not_in` | `{ field: commune_id, op: "in", value: ["31555"] }` |

Fields must exist on `persons.csv` at assignment time (`age`, `has_driving_license`,
`sex`, …). `has_driving_license` also matches a `has_license` column if present.

## Merging `forbidden_modes`

Put every mode a person must avoid in **one** `params.forbidden` list when the same
`when` block applies. Example: children get bikesharing and car in a single assignment
(they cannot hold a driving licence):

```yaml
  - id: forbidden_modes_child
    constraint_type: forbidden_modes
    when:
      - { field: age, op: "<=", value: 14 }
    params:
      forbidden: [bikesharing, car]
```

Adults without a licence use a separate rule with `age > 14`.

If several assignments each add `forbidden_modes`, the person keeps **separate** list
entries. The router should treat them as the union of all forbidden modes, or you can
merge them explicitly in YAML as above.

## Shipped constraint types

| Type | `params` | Router rule (summary) |
|------|----------|------------------------|
| `forbidden_modes` | `forbidden: [mode, ...]` | Trip modes must not intersect the list |
| `max_walk_distance_m` | `max: int` (metres) | Walk leg length ≤ `max` |
| `wheelchair_access_required` | `{}` | Only wheelchair-accessible resources |
| `direct_itinerary` | `{}` | Zero transfers (`nb_transfers == 0`) |

Mode ids in this project use names such as `car`, `bike`, `bikesharing` (not
`shared_car` / `shared_bikes`).

## Randomness

Probabilistic assignments use `random_seed` from the synpp config (default `1234` in
`config_occitanie.yml`). The draw is a deterministic hash of
`random_seed`, assignment `id`, and `person_id`, so the same baseline rebuild always
assigns the same people.

## Adding a new constraint

1. **Add a `constraint_types` entry** (for documentation and the router).
2. **Add an `assignment`** with `when` / `sample` / `assign` as needed.
3. **Implement enforcement** in the scenario router for the new `constraint_type`.
4. **Rebuild the baseline** and check `persons.csv` or `scenario.json`.
5. **Add a test** in `tests/test_constraints_loader.py` if the YAML pattern is new.

Example: forbid car for persons without a licence:

```yaml
  - id: forbidden_modes_car_no_license
    constraint_type: forbidden_modes
    when:
      - { field: has_driving_license, op: "==", value: false }
      - { field: age, op: ">", value: 14 }
    params:
      forbidden: [car]
```

## Baseline wiring

`build_baseline_runtime_config()` in `config_service.py` sets:

- `assign_constraints: true`
- `constraints_path` -> `backend/config/constraints.yml`

Scenario runtime configs do not re-assign constraints; they inherit the `constraints`
column from baseline persons.

## Verify

```bash
python -m pytest tests/test_constraints_loader.py -q
```
