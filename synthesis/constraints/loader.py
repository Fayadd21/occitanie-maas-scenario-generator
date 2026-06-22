from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from synthesis.profiles.loader import (
    _allowed_tokens,
    _match_token,
    _normalize_rule_value,
    _resolve_series,
    _series_match_tokens,
)


def _rule_matches(series: pd.Series, rule: dict[str, Any]) -> pd.Series:
    op = str(rule.get("op", "")).strip()
    value = _normalize_rule_value(rule.get("value"))
    numeric = pd.to_numeric(series, errors="coerce")

    if op == "<":
        return numeric < float(value)
    if op == "<=":
        return numeric <= float(value)
    if op == ">":
        return numeric > float(value)
    if op == ">=":
        return numeric >= float(value)
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

    raise ValueError(f"Unsupported constraint rule operator: {op}")

FIELD_ALIASES: dict[str, list[str]] = {
    "has_driving_license": ["has_driving_license", "has_license"],
}


def load_constraints_config(constraints_path: str | Path) -> dict[str, Any]:
    path = Path(constraints_path)
    if not path.exists():
        raise FileNotFoundError(f"Constraints config not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data.get("assignments"), list):
        raise ValueError(f"Constraints config has no assignments: {path}")
    return data


def _resolve_constraint_series(df: pd.DataFrame, field: str) -> pd.Series:
    for column in FIELD_ALIASES.get(field, [field]):
        if column in df.columns:
            return df[column]
    return _resolve_series(df, field)


def _assignment_matches(df: pd.DataFrame, assignment: dict[str, Any]) -> pd.Series:
    rules = assignment.get("when") or []
    if not rules:
        return pd.Series(False, index=df.index)
    mask = pd.Series(True, index=df.index)
    for rule in rules:
        field = str(rule.get("field", "")).strip()
        if not field:
            mask &= False
            continue
        series = _resolve_constraint_series(df, field)
        mask &= _rule_matches(series, rule)
    return mask


def _assignment_eligible(df: pd.DataFrame, assignment: dict[str, Any]) -> pd.Series:
    rules = assignment.get("when")
    if rules:
        return _assignment_matches(df, assignment)

    sample = assignment.get("sample")
    if isinstance(sample, dict) and (
        sample.get("tiers") or "probability" in sample
    ):
        return pd.Series(True, index=df.index)

    return pd.Series(False, index=df.index)


def _constraint_payload(source: dict[str, Any]) -> dict[str, Any]:
    params = source.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    payload: dict[str, Any] = {
        "constraint_type": str(source["constraint_type"]),
        "params": params,
    }
    constraint_id = source.get("id")
    if constraint_id is not None and str(constraint_id).strip():
        payload["id"] = str(constraint_id).strip()
    return payload


def _assignment_payloads(assignment: dict[str, Any]) -> list[dict[str, Any]]:
    nested = assignment.get("assign")
    if isinstance(nested, list) and nested:
        return [_constraint_payload(item) for item in nested if isinstance(item, dict)]
    if "constraint_type" in assignment:
        return [_constraint_payload(assignment)]
    return []


def _stable_uniform(person_key: str, assignment_id: str, random_seed: int) -> float:
    digest = hashlib.sha256(f"{random_seed}:{assignment_id}:{person_key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / (2**64)


def _person_key(df: pd.DataFrame, index: Any) -> str:
    if "person_id" in df.columns:
        value = df.loc[index, "person_id"]
        if value is not None and not (isinstance(value, float) and pd.isna(value)):
            return str(value)
    return str(index)


def _tier_probability_for_row(
    df: pd.DataFrame,
    index: Any,
    tiers: list[dict[str, Any]],
) -> float | None:
    frame = df.loc[[index]]
    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        when = tier.get("when") or []
        if not when or bool(_assignment_matches(frame, {"when": when}).iloc[0]):
            return float(tier.get("probability", 0))
    return None


def _person_passes_sample(
    df: pd.DataFrame,
    index: Any,
    assignment: dict[str, Any],
    *,
    random_seed: int,
) -> bool:
    sample = assignment.get("sample")
    if not isinstance(sample, dict):
        return True

    assignment_id = str(assignment.get("id", "sample"))
    tiers = sample.get("tiers")
    if isinstance(tiers, list) and tiers:
        probability = _tier_probability_for_row(df, index, tiers)
        if probability is None:
            return False
    elif "probability" in sample:
        probability = float(sample["probability"])
    else:
        return True

    if probability >= 1.0:
        return True
    if probability <= 0.0:
        return False

    draw = _stable_uniform(_person_key(df, index), assignment_id, random_seed)
    return draw < probability


def _apply_sample_mask(
    df: pd.DataFrame,
    assignment: dict[str, Any],
    eligible: pd.Series,
    *,
    random_seed: int,
) -> pd.Series:
    sample = assignment.get("sample")
    if not isinstance(sample, dict):
        return eligible

    assignment_id = str(assignment.get("id", "sample"))
    tiers = sample.get("tiers")
    if isinstance(tiers, list) and tiers:
        sampled = pd.Series(False, index=df.index)
        for index in df.index[eligible]:
            if _person_passes_sample(df, index, assignment, random_seed=random_seed):
                sampled.loc[index] = True
        return sampled

    if "probability" in sample:
        return _probabilistic_mask(
            df,
            eligible,
            float(sample["probability"]),
            assignment_id=assignment_id,
            random_seed=random_seed,
        )

    return eligible


def _probabilistic_mask(
    df: pd.DataFrame,
    eligible: pd.Series,
    probability: float,
    *,
    assignment_id: str,
    random_seed: int,
) -> pd.Series:
    if not bool(eligible.any()):
        return pd.Series(False, index=df.index)
    if probability >= 1.0:
        return eligible
    if probability <= 0.0:
        return pd.Series(False, index=df.index)

    sampled = pd.Series(False, index=df.index)
    for index in df.index[eligible]:
        draw = _stable_uniform(_person_key(df, index), assignment_id, random_seed)
        if draw < probability:
            sampled.loc[index] = True
    return sampled


def constraints_for_person(
    person_row: pd.Series,
    assignments: list[dict[str, Any]],
    *,
    random_seed: int = 42,
) -> list[dict[str, Any]]:
    frame = person_row.to_frame().T
    assigned: list[dict[str, Any]] = []
    for assignment in assignments:
        if not bool(_assignment_eligible(frame, assignment).iloc[0]):
            continue
        sample = assignment.get("sample")
        if isinstance(sample, dict) and (sample.get("tiers") or "probability" in sample):
            if not _person_passes_sample(frame, frame.index[0], assignment, random_seed=random_seed):
                continue
        assigned.extend(_assignment_payloads(assignment))
    return assigned


def assign_constraints(
    df_persons: pd.DataFrame,
    constraints_path: str | Path,
    *,
    random_seed: int = 42,
) -> pd.DataFrame:
    data = load_constraints_config(constraints_path)
    assignments = data.get("assignments") or []
    if not assignments:
        result = df_persons.copy()
        result["constraints"] = "[]"
        return result

    assigned_by_index: list[list[dict[str, Any]]] = [[] for _ in range(len(df_persons))]
    for assignment in assignments:
        eligible = _assignment_eligible(df_persons, assignment)
        mask = _apply_sample_mask(
            df_persons,
            assignment,
            eligible,
            random_seed=random_seed,
        )

        payloads = _assignment_payloads(assignment)
        if not payloads:
            continue
        for index in df_persons.index[mask]:
            position = df_persons.index.get_loc(index)
            assigned_by_index[position].extend(payloads)

    result = df_persons.copy()
    result["constraints"] = [
        json.dumps(payloads, ensure_ascii=False) for payloads in assigned_by_index
    ]
    return result


def parse_person_constraints(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    try:
        if pd.isna(value):
            return []
    except (TypeError, ValueError):
        pass
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, str):
        text = value.strip()
        if not text or text == "[]":
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    return []
