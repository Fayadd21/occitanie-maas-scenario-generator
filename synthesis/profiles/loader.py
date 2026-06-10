from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

FIELD_ALIASES: dict[str, list[str]] = {
    "has_license": ["has_license", "has_driving_license"],
    "household_income": ["household_income", "income"],
}

_EARTH_RADIUS_KM = 6371.0


def load_profiles_config(profiles_path: str | Path) -> dict[str, Any]:
    path = Path(profiles_path)
    if not path.exists():
        raise FileNotFoundError(f"Profiles config not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data.get("profiles"), list) or not data["profiles"]:
        raise ValueError(f"Profiles config has no profiles: {path}")
    return data


def latent_class_filter_restricts_pool(
    allowed_latent_classes: list[str] | None,
    profiles_path: str | Path | None,
) -> bool:
    """True when allowed_latent_classes would drop persons after assignment."""
    if not allowed_latent_classes:
        return False
    allowed = {str(value).strip() for value in allowed_latent_classes if str(value).strip()}
    if not allowed:
        return False
    if not profiles_path:
        return True
    data = load_profiles_config(profiles_path)
    all_ids = {str(profile["id"]).strip() for profile in data.get("profiles", [])}
    return allowed != all_ids


def list_profile_summaries(profiles_path: str | Path) -> dict[str, Any]:
    data = load_profiles_config(profiles_path)
    profiles = data["profiles"]
    default_allowed = data.get("default_allowed")
    if not default_allowed:
        default_allowed = data.get("profile_order") or [str(p["id"]) for p in profiles]
    return {
        "profiles": [
            {"id": str(profile["id"]), "label": str(profile.get("label") or profile["id"])}
            for profile in profiles
        ],
        "default_allowed": [str(value) for value in default_allowed],
        "profile_order": [str(value) for value in (data.get("profile_order") or default_allowed)],
        "latent_class_noise_std": _resolve_latent_class_noise(data),
    }


def _resolve_series(df: pd.DataFrame, field: str) -> pd.Series:
    for column in FIELD_ALIASES.get(field, [field]):
        if column in df.columns:
            return df[column]
    raise KeyError(f"Missing field for profile rules: {field}")


def _normalize_rule_value(value: Any) -> Any:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    return value


def _match_token(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.notna(numeric) and float(numeric).is_integer():
        return str(int(numeric))
    return str(value).strip().lower()


def _series_match_tokens(series: pd.Series) -> pd.Series:
    return series.map(_match_token)


def _allowed_tokens(values: list[Any]) -> set[str]:
    tokens: set[str] = set()
    for item in values:
        token = _match_token(item)
        if token is not None:
            tokens.add(token)
    return tokens


def _rule_matches(series: pd.Series, rule: dict[str, Any]) -> pd.Series:
    op = str(rule.get("op", "")).strip()
    value = _normalize_rule_value(rule.get("value"))
    numeric = pd.to_numeric(series, errors="coerce")

    if op == "<":
        threshold = float(value)
        return numeric < threshold
    if op == ">":
        threshold = float(value)
        return numeric > threshold
    if op == "==":
        if isinstance(value, bool):
            return series.fillna(False).astype(bool) == value
        token = _match_token(value)
        if token is None:
            return pd.Series(False, index=series.index)
        return _series_match_tokens(series) == token
    if op == "between":
        low, high = value
        return numeric.between(float(low), float(high), inclusive="both")
    if op == "in":
        return _series_match_tokens(series).isin(_allowed_tokens(list(value)))
    if op == "not_in":
        return ~_series_match_tokens(series).isin(_allowed_tokens(list(value)))

    raise ValueError(f"Unsupported profile rule operator: {op}")


def _score_profile(df: pd.DataFrame, profile: dict[str, Any]) -> pd.Series:
    total = pd.Series(0.0, index=df.index, dtype=float)
    for rule in profile.get("rules") or []:
        series = _resolve_series(df, str(rule["field"]))
        total = total + float(rule.get("points", 0)) * _rule_matches(series, rule).astype(float)
    return total


def merge_household_attributes(df_persons: pd.DataFrame, df_households: pd.DataFrame | None) -> pd.DataFrame:
    if df_households is None or "household_id" not in df_persons.columns:
        return df_persons.copy()

    persons = df_persons.copy()
    households = df_households.copy()
    persons["household_id"] = persons["household_id"].astype(str)
    households["household_id"] = households["household_id"].astype(str)
    if "income" in households.columns and "household_income" not in households.columns:
        households["household_income"] = households["income"]

    merge_columns = ["household_id"]
    for column in ("car_availability", "bike_availability", "household_income", "commune_id"):
        if column in households.columns:
            merge_columns.append(column)

    merged = persons.merge(
        households[merge_columns].drop_duplicates("household_id"),
        on="household_id",
        how="left",
        suffixes=("", "_household"),
    )
    return merged


def _geodesic_distance_km(origin: Any, destination: Any) -> float | None:
    if origin is None or destination is None:
        return None
    try:
        if pd.isna(origin) or pd.isna(destination):
            return None
    except TypeError:
        pass
    try:
        lat1 = math.radians(float(origin.y))
        lon1 = math.radians(float(origin.x))
        lat2 = math.radians(float(destination.y))
        lon2 = math.radians(float(destination.x))
    except (AttributeError, TypeError, ValueError):
        return None
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    chord = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    return _EARTH_RADIUS_KM * 2.0 * math.asin(min(1.0, math.sqrt(chord)))


def _geometry_by_purpose(df_activities: pd.DataFrame, purpose: str) -> pd.Series:
    subset = df_activities[df_activities["purpose"].astype(str) == purpose]
    if len(subset) == 0:
        return pd.Series(dtype=object)
    ordered = subset.sort_values(["person_id", "activity_index"])
    return ordered.drop_duplicates("person_id", keep="first").set_index("person_id")["geometry"]


def profiles_reference_field(profiles_path: str | Path, field: str) -> bool:
    data = load_profiles_config(profiles_path)
    for profile in data["profiles"]:
        for rule in profile.get("rules") or []:
            if str(rule.get("field")) == field:
                return True
    return False


def _coords_by_person(geometries: pd.Series) -> pd.DataFrame:
    if len(geometries) == 0:
        return pd.DataFrame(columns=["person_id", "lat", "lon"])
    rows = []
    for person_id, geometry in geometries.items():
        if geometry is None or (isinstance(geometry, float) and pd.isna(geometry)):
            continue
        try:
            rows.append({"person_id": str(person_id), "lat": float(geometry.y), "lon": float(geometry.x)})
        except (AttributeError, TypeError, ValueError):
            continue
    return pd.DataFrame(rows)


def _haversine_km_vector(
    lat1: pd.Series,
    lon1: pd.Series,
    lat2: pd.Series,
    lon2: pd.Series,
) -> pd.Series:
    lat1_rad = np.radians(lat1.to_numpy(dtype=float))
    lon1_rad = np.radians(lon1.to_numpy(dtype=float))
    lat2_rad = np.radians(lat2.to_numpy(dtype=float))
    lon2_rad = np.radians(lon2.to_numpy(dtype=float))
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    chord = np.sin(dlat / 2.0) ** 2 + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2.0) ** 2
    return pd.Series(_EARTH_RADIUS_KM * 2.0 * np.arcsin(np.minimum(1.0, np.sqrt(chord))), index=lat1.index)


def attach_home_destination_distance(
    df_persons: pd.DataFrame,
    df_activities: pd.DataFrame,
) -> pd.DataFrame:
    result = df_persons.copy()
    if "person_id" not in result.columns:
        result["home_destination_distance_km"] = np.nan
        return result

    if "geometry" not in df_activities.columns or "purpose" not in df_activities.columns:
        result["home_destination_distance_km"] = np.nan
        return result

    activities = df_activities
    if activities["person_id"].dtype != object:
        activities = activities.copy()
        activities["person_id"] = activities["person_id"].astype(str)
    else:
        activities = activities.copy()
        activities["person_id"] = activities["person_id"].astype(str)

    home = _geometry_by_purpose(activities, "home")
    work = _geometry_by_purpose(activities, "work")
    education = _geometry_by_purpose(activities, "education")

    person_ids = result["person_id"].astype(str)
    coords = pd.DataFrame({"person_id": person_ids})
    coords = coords.merge(
        _coords_by_person(home).rename(columns={"lat": "home_lat", "lon": "home_lon"}),
        on="person_id",
        how="left",
    )
    coords = coords.merge(
        _coords_by_person(work).rename(columns={"lat": "work_lat", "lon": "work_lon"}),
        on="person_id",
        how="left",
    )
    coords = coords.merge(
        _coords_by_person(education).rename(columns={"lat": "education_lat", "lon": "education_lon"}),
        on="person_id",
        how="left",
    )

    dest_lat = coords["work_lat"].fillna(coords["education_lat"])
    dest_lon = coords["work_lon"].fillna(coords["education_lon"])
    valid = coords["home_lat"].notna() & coords["home_lon"].notna() & dest_lat.notna() & dest_lon.notna()
    distances = np.full(len(result), np.nan, dtype=float)
    if valid.any():
        distances[valid.to_numpy()] = _haversine_km_vector(
            coords.loc[valid, "home_lat"],
            coords.loc[valid, "home_lon"],
            dest_lat.loc[valid],
            dest_lon.loc[valid],
        ).to_numpy()

    result["home_destination_distance_km"] = distances
    return result


def _resolve_latent_class_noise(data: dict[str, Any]) -> float:
    configured = data.get("latent_class_noise_std", 0.0)
    return max(0.0, float(configured))


def assign_latent_classes(
    df_persons: pd.DataFrame,
    profiles_path: str | Path,
    *,
    df_households: pd.DataFrame | None = None,
    random_seed: int | None = None,
) -> pd.DataFrame:
    data = load_profiles_config(profiles_path)
    profiles = data["profiles"]
    profile_order = [str(profile["id"]) for profile in profiles]
    tie_order = [str(value) for value in (data.get("profile_order") or profile_order)]

    frame = merge_household_attributes(df_persons, df_households)
    scores = pd.DataFrame(index=frame.index)
    for profile in profiles:
        profile_id = str(profile["id"])
        scores[profile_id] = _score_profile(frame, profile)

    ordered_columns = [column for column in tie_order if column in scores.columns]
    for column in scores.columns:
        if column not in ordered_columns:
            ordered_columns.append(column)

    scores_array = scores[ordered_columns].to_numpy(dtype=float)

    best_idx = np.argmax(scores_array, axis=1)
    result = df_persons.copy()
    result["latent_class"] = pd.Categorical(
        [ordered_columns[index] for index in best_idx],
        categories=ordered_columns,
    )
    return result


def _normalize_preference_weights(preference_rows: list[dict[str, Any]]) -> list[float]:
    weights = [max(0.0, float(row.get("weight", 0.0))) for row in preference_rows]
    total = float(sum(weights))
    if total <= 0.0:
        if not weights:
            return []
        return [1.0 / len(weights)] * len(weights)
    return [weight / total for weight in weights]


def _resolve_noise_target_indices(
    preference_rows: list[dict[str, Any]],
    normalized_weights: list[float],
) -> list[int]:
    if not normalized_weights:
        return []
    return [
        idx
        for idx, row in enumerate(preference_rows)
        if bool(row.get("noise_target") or row.get("preferred_noise"))
    ]


def _apply_preference_weight_noise(
    preference_rows: list[dict[str, Any]],
    normalized_weights: list[float],
    *,
    noise_std: float,
    random_seed: int,
) -> list[float]:
    if noise_std <= 0.0 or not normalized_weights:
        return normalized_weights

    target_indices = _resolve_noise_target_indices(preference_rows, normalized_weights)
    if not target_indices:
        return normalized_weights

    weights = np.asarray(normalized_weights, dtype=float)
    rng = np.random.default_rng(random_seed)
    for target_idx in target_indices:
        weights[target_idx] = float(
            np.clip(float(weights[target_idx]) + rng.normal(0.0, noise_std), 0.0, 1.0)
        )

    total = float(weights.sum())
    if total <= 0.0:
        return [1.0 / len(weights)] * len(weights)
    return (weights / total).tolist()


def preferences_for_profile(
    profile_id: str | None,
    profiles_path: str | Path,
    *,
    request_index: int,
) -> list[dict[str, Any]]:
    data = load_profiles_config(profiles_path)
    normalized = (profile_id or "").strip().lower()
    selected = None
    for profile in data["profiles"]:
        if str(profile["id"]).strip().lower() == normalized:
            selected = profile
            break

    preference_rows = list(
        (selected or {}).get("preferences")
        or data.get("default_preferences")
        or []
    )
    if not preference_rows:
        raise ValueError(f"No preferences defined for profile '{profile_id}' in {profiles_path}")

    normalized_weights = _normalize_preference_weights(preference_rows)
    noise_std = _resolve_latent_class_noise(data)
    normalized_weights = _apply_preference_weight_noise(
        preference_rows,
        normalized_weights,
        noise_std=noise_std,
        random_seed=int(request_index),
    )
    preferences: list[dict[str, Any]] = []
    for row, weight in zip(preference_rows, normalized_weights):
        metric = str(row["metric"])
        objective = str(row.get("objective", "minimize"))
        preference_id = str(row.get("id", metric))
        preferences.append(
            {
                "id": f"P-{request_index}-{preference_id}",
                "preference_type": {
                    "id": preference_id,
                    "metric": metric,
                    "objective": objective,
                    "params": list(row.get("params") or []),
                },
                "weight": weight,
            }
        )
    return preferences
