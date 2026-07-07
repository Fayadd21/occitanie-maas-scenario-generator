# Profiles and latent classes

## Setup `profiles.yml`

The API reads **`backend/config/profiles.yml`**. That file is **gitignored** so each
developer or deployment can keep its own class rules and weights.

Before your first scenario job, create it in one of these ways:

```bash
cp backend/config/example.profiles.yml backend/config/profiles.yml
```

Or copy `example.profiles.yml` to `profiles.yml` in `backend/config/` and edit the
fields below. The repository ships only **`backend/config/example.profiles.yml`**
as the reference template. Scenario jobs fail if `profiles.yml` is missing.

## File layout

- `profiles` - `id`, `label`, `rules`, `preferences` per class
- `profile_order` - tie-break on equal total score
- `default_allowed` - classes listed in the UI by default
- `default_preferences` - fallback preference weights if a profile has no `preferences` block
- `latent_class_noise_std` - standard deviation of Gaussian noise applied to exported preference weights; `0` disables noise

## Assignment

Enabled when `assign_latent_classes: true` in the job config (set by the backend for
`POST /jobs` scenario jobs).

In `synthesis/profiles/loader.py`, each person is scored on every profile. Household
fields are merged before scoring, and the class with the highest score is kept.

Baseline persons are not classified. Enrichment does not assign classes (`latent_classes.enabled: false`).

## Rules

Rules reference person or household columns (`age`, `car_availability`, `income`, ...).
Operators include `==`, `>`, `<`, `between`, `in`, `not_in`. Matching rules add `points`.

## Preferences in scenario.json

`preferences_for_profile()` reads the weights for the assigned class and normalizes
them for export. All persons with the same class share the same preference set.

## Noise

`latent_class_noise_std` is the sigma of `N(0, sigma)` applied independently to
each preference weight marked with `noise_target: true`, then weights are
renormalized to sum to 1. If no preference has `noise_target: true`, no noise is
applied.

---

## Creating new latent classes

This section is for editing `backend/config/profiles.yml` beyond the shipped
`example.profiles.yml` template.

### 1. Add a profile block

Each class is one list entry under `profiles`:

```yaml
  - id: prefers_walking
    label: Prefers walking
    rules:
      - { field: age, op: between, value: [16, 70], points: 1 }
      - { field: car_availability, op: "not_in", value: [all, some], points: 2 }
    preferences:
      - { id: fastest_route, metric: duration, objective: minimize, weight: 0.25 }
      - { id: shortest_distance, metric: distance, objective: minimize, weight: 0.55 }
      - { id: cheapest_option, metric: price, objective: minimize, weight: 0.20 }
```

- **`id`** - stored in `persons.csv` as `latent_class` and used in the UI checkboxes.
  Use lowercase snake_case, no spaces.
- **`label`** - shown in the frontend latent-class panel.
- **`rules`** - scoring rules (see below).
- **`preferences`** - routing weights exported in `scenario.json` (`duration`, `distance`, `price`).

### 2. Register the class globally

Add the new `id` in three places at the top of `profiles.yml`:

```yaml
default_allowed:
  - prefers_walking   # include if it should be checked by default in the UI

profile_order:
  - prefers_walking   # earlier = wins ties on equal total score
```

If you omit a class from `default_allowed`, users can still enable it manually in the UI.
If you omit it from `profile_order`, it is still scored but tie-breaks fall back to list order.

### 3. Rule syntax

Each rule is a dict:

```yaml
{ field: <column_name>, op: <operator>, value: <literal>, points: <number> }
```

| Operator | `value` type | Meaning |
|----------|--------------|---------|
| `==` | bool, string, number | Equal (strings compared case-insensitive) |
| `>` | number | Greater than |
| `<` | number | Less than |
| `between` | `[low, high]` | Numeric inclusive range |
| `in` | list | String value in list (case-insensitive) |
| `not_in` | list | String value not in list |

**Points** are summed per profile. The profile with the highest total wins.

### 4. Usable Fields

At scenario time, assignment reads **baseline** `persons.csv` and merges **baseline**
`households.csv` on `household_id`.

**Person columns** (in `*_persons.csv`):

| Field | Example value | Notes |
|-------|-----------------|-------|
| `age` | `31` | `{ field: age, op: between, value: [25, 54], points: 1 }` |
| `employed` | `true` | `{ field: employed, op: "==", value: true, points: 2 }` |
| `sex` | `male` | `{ field: sex, op: "==", value: female, points: 1 }` |
| `socioprofessional_class` | `5` | Employee; see code table below |
| `has_license` | `true` | CSV column: `has_driving_license` (alias in code) |
| `has_pt_subscription` | `false` | `{ field: has_pt_subscription, op: "==", value: true, points: 2 }` |
| `person_id`, `household_id`, ... | | IDs; rarely useful in rules |

**Socioprofessional class codes** (`socioprofessional_class` is an integer 1-8; [PCS-style](https://www.insee.fr/en/metadonnees/definition/c1493)
job/status from census / ENTD matching).

| Code | Meaning |
|------|---------|
| 1 | Agriculture |
| 2 | Independent / self-employed |
| 3 | Executive / intellectual (cadres, prof. liberales) |
| 4 | Intermediate professions |
| 5 | Employee (employes) |
| 6 | Worker (ouvriers) |
| 7 | Retired |
| 8 | Other / inactive |

Example rule targeting employees:

```yaml
{ field: socioprofessional_class, op: "==", value: 5, points: 2 }
```

**Household columns** (merged from `*_households.csv`):

| Field | Example value | Notes |
|-------|-----------------|-------|
| `household_income` | `3257` | CSV column: `income`; monthly EUR; `{ field: household_income, op: "<", value: 2200, points: 1 }` |
| `car_availability` | `all` | `all`, `some`, `none` |
| `bike_availability` | `some` | `{ field: bike_availability, op: "==", value: all, points: 1 }` |
| `commune_id` | `31555` | Home commune INSEE code (household); use `in` for a list of communes |

**Commune-based bonus points** (one home location per household; all persons in the
household share it):

```yaml
- { field: commune_id, op: in, value: ["31555", "31424"], points: 2 }
```

Copy codes from `*_households.csv` in your baseline or run output. Strings and
numbers both match (`31555` in CSV works with `"31555"` in YAML).

**Home-to-destination distance** (straight-line haversine × 1.3 circuity factor):

```yaml
- { field: home_destination_distance_km, op: "<", value: 5, points: 2 }
- { field: home_destination_distance_km, op: ">", value: 25, points: 1 }
```

Thresholds are in **approximate road kilometres**, not raw crow-fly distance.

If a rule references a column that is missing after the merge, the job fails with
`KeyError: Missing field for profile rules: ...`.

### 5. Preferences for routing export

Each profile should define `preferences` with weighted metrics:

- `metric`: commonly `duration`, `distance`, or `price`, but not limited to those three
  (you can add other metric ids your downstream routing stack understands)
- `objective`: `maximize` or `minimize`.
- `weight`: any non-negative numbers (normalized to sum to 1 on export)
- `noise_target` (optional): set `true` on one or more preferences to make
  `latent_class_noise_std` change those weights; if omitted on all preferences, no
  noise is applied.

The example file's `default_preferences` are used only when a profile has no
`preferences` block.
