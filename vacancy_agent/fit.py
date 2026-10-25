"""Logistic regression for current vacancy. No penalty. Gradient descent from zero."""

from __future__ import annotations

import math
import re

_LEARNING_RATE = 0.5
_EPOCHS = 4000
_CLIP = 12.0


def fit_vacancy(plans: list[dict]) -> dict:
    rows = _expand(plans)
    if not rows:
        raise ValueError("The plan table has no units.")
    names = sorted({plan for plan, _renovated, _label in rows})
    reference = names[0]
    others = names[1:]
    width = 2 + len(others)
    weights = [0.0] * width
    count = len(rows)
    for _epoch in range(_EPOCHS):
        gradient = [0.0] * width
        for plan, renovated, label in rows:
            features = _features(plan, renovated, reference, others)
            probability = _sigmoid(_dot(weights, features))
            error = probability - label
            for index, feature in enumerate(features):
                gradient[index] += error * feature
        for index in range(width):
            weights[index] = _clip(weights[index] - _LEARNING_RATE * gradient[index] / count)
    groups = []
    for plan, renovated, units, vacant in _groups(plans):
        probability = _sigmoid(_dot(weights, _features(plan, renovated, reference, others)))
        if vacant == 0 and probability < 0.01:
            probability = 0.0
        groups.append(
            {
                "plan": plan,
                "renovated": renovated,
                "units": units,
                "vacant": vacant,
                "probability": round(probability, 4),
            }
        )
    return {
        "reference_plan": reference,
        "beta0": round(weights[0], 4),
        "beta_plan": {name: round(weights[index + 1], 4) for index, name in enumerate(others)},
        "beta_reno": round(weights[-1], 4),
        "groups": groups,
    }


def plan_catalog(model: dict) -> dict:
    """Plan names and reno flags only. No probabilities, betas, or counts."""
    plans = []
    keys: list[str] = []
    for group in model.get("groups") or []:
        name = group.get("plan")
        if not name:
            continue
        if name not in keys:
            keys.append(name)
        plans.append({"plan": name, "renovated": int(group.get("renovated") or 0)})
    return {"plan_keys": keys, "plans": plans}


def _ambiguous(model: dict, keys: list[str] | None = None) -> dict:
    catalog = plan_catalog(model)
    if keys is None:
        keys = catalog["plan_keys"]
    chosen = set(keys)
    return {
        "error": "ambiguous_plan",
        "plan_keys": keys,
        "plans": [item for item in catalog["plans"] if item["plan"] in chosen],
    }


def score_vacancy(model: dict, plan: str = "", renovated: int | None = None) -> dict:
    query = " ".join(str(plan or "").split())
    if not query:
        return _ambiguous(model)
    keys = _matching_plan_keys(model, plan)
    if not keys:
        return {"error": "group_not_in_fit", **plan_catalog(model)}
    if len(keys) > 1:
        return _ambiguous(model, keys)
    matched = _resolve_group(model, keys[0], renovated)
    if matched is None:
        same = [item for item in plan_catalog(model)["plans"] if item["plan"] == keys[0]]
        if len(same) > 1 and renovated is None:
            return _ambiguous(model, keys)
        catalog = plan_catalog(model)
        return {"error": "group_not_in_fit", **catalog}
    plan = matched["plan"]
    renovated = int(matched["renovated"])
    reference = model["reference_plan"]
    others = list((model.get("beta_plan") or {}).keys())
    weights = [float(model["beta0"])]
    weights.extend(float(model["beta_plan"][name]) for name in others)
    weights.append(float(model.get("beta_reno") or 0.0))
    probability = _sigmoid(_dot(weights, _features(plan, renovated, reference, others)))
    if matched["vacant"] == 0 and probability < 0.01:
        probability = 0.0
    return {
        "plan": plan,
        "renovated": renovated,
        "probability": round(probability, 4),
        "units": matched["units"],
        "vacant": matched["vacant"],
    }


_LAYOUT = re.compile(r"(\d+x\d+(?:\.\d+)?)")


def _norm_plan(plan: str) -> str:
    return "".join(str(plan).split()).casefold()


def _layout_token(plan: str) -> str | None:
    match = _LAYOUT.search(_norm_plan(plan))
    return match.group(1) if match else None


def _plan_matches_query(query: str, key: str) -> bool:
    needle = _norm_plan(query)
    haystack = _norm_plan(key)
    if not needle or not haystack:
        return False
    if haystack == needle:
        return True
    if haystack.startswith(needle) and haystack[len(needle) :].isalpha():
        return True
    query_layout = _layout_token(query)
    if query_layout and needle == query_layout and _layout_token(key) == query_layout:
        return True
    last = _norm_plan(str(key).split()[-1])
    return bool(last) and last == needle and needle.isalpha()


def _matching_plan_keys(model: dict, plan: str) -> list[str]:
    query = " ".join(str(plan).split())
    if not query:
        return []
    keys: list[str] = []
    for group in model.get("groups") or []:
        key = group.get("plan")
        if key and _plan_matches_query(query, key) and key not in keys:
            keys.append(key)
    return keys


def _resolve_group(model: dict, plan: str, renovated: int | None) -> dict | None:
    plan = " ".join(str(plan).split())
    groups = [group for group in (model.get("groups") or []) if group.get("plan") == plan]
    if not groups:
        return None
    reno = None if renovated is None else (1 if int(renovated) else 0)
    if reno is None:
        return groups[0] if len(groups) == 1 else None
    hits = [group for group in groups if int(group["renovated"]) == reno]
    if len(hits) == 1:
        return hits[0]
    if not hits and len(groups) == 1:
        return groups[0]
    return None




def _expand(plans: list[dict]) -> list[tuple[str, int, int]]:
    rows: list[tuple[str, int, int]] = []
    for plan, renovated, units, vacant in _groups(plans):
        rows.extend((plan, renovated, 1 if index < vacant else 0) for index in range(units))
    return rows


def _groups(plans: list[dict]) -> list[tuple[str, int, int, int]]:
    grouped: list[tuple[str, int, int, int]] = []
    for item in plans:
        plan = " ".join(str(item["plan"]).split())
        renovated = 1 if int(item.get("renovated") or 0) else 0
        units = int(item["units"])
        vacant = int(item["vacant"])
        if units > 0 and plan:
            grouped.append((plan, renovated, units, vacant))
    return grouped


def _features(plan: str, renovated: int, reference: str, others: list[str]) -> list[float]:
    features = [1.0]
    features.extend(1.0 if plan == name else 0.0 for name in others)
    features.append(float(renovated))
    if plan != reference and plan not in others:
        raise KeyError(plan)
    return features


def _dot(weights: list[float], features: list[float]) -> float:
    return sum(weight * feature for weight, feature in zip(weights, features))


def _sigmoid(value: float) -> float:
    value = _clip(value)
    if value >= 0:
        exponent = math.exp(-value)
        return 1.0 / (1.0 + exponent)
    exponent = math.exp(value)
    return exponent / (1.0 + exponent)


def _clip(value: float) -> float:
    return max(-_CLIP, min(_CLIP, value))
