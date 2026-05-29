from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

FIELD_ALIASES: dict[str, list[str]] = {
    "has_license": ["has_license", "has_driving_license"],
    "household_income": ["household_income", "income"],
}


def load_profiles_config(profiles_path: str | Path) -> dict[str, Any]:
    path = Path(profiles_path)
    if not path.exists():
        raise FileNotFoundError(f"Profiles config not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data.get("profiles"), list) or not data["profiles"]:
        raise ValueError(f"Profiles config has no profiles: {path}")
    return data


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
        return series.astype(str).str.strip().str.lower() == str(value).strip().lower()
    if op == "between":
        low, high = value
        return numeric.between(float(low), float(high), inclusive="both")
    if op == "in":
        allowed = {_normalize_rule_value(item) for item in value}
        normalized = series.astype(str).str.strip().str.lower()
        return normalized.isin({str(item).strip().lower() for item in allowed})
    if op == "not_in":
        allowed = {_normalize_rule_value(item) for item in value}
        normalized = series.astype(str).str.strip().str.lower()
        return ~normalized.isin({str(item).strip().lower() for item in allowed})

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

    households = df_households.copy()
    if "income" in households.columns and "household_income" not in households.columns:
        households["household_income"] = households["income"]

    merge_columns = ["household_id"]
    for column in ("car_availability", "bike_availability", "household_income"):
        if column in households.columns:
            merge_columns.append(column)

    merged = df_persons.merge(
        households[merge_columns].drop_duplicates("household_id"),
        on="household_id",
        how="left",
        suffixes=("", "_household"),
    )
    return merged


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
