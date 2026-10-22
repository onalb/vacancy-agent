"""Logistic regression for current vacancy. No penalty. Gradient descent from zero."""

from __future__ import annotations

import math

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


def score_vacancy(model: dict, plan: str, renovated: int) -> dict:
    plan = " ".join(str(plan).split())
    renovated = 1 if int(renovated) else 0
    known = {(group["plan"], int(group["renovated"])) for group in model.get("groups") or []}
    if (plan, renovated) not in known:
        return {
            "error": "group_not_in_fit",
            "groups": [
                {"plan": group["plan"], "renovated": group["renovated"]}
                for group in model.get("groups") or []
            ],
        }
    reference = model["reference_plan"]
    others = list((model.get("beta_plan") or {}).keys())
    weights = [float(model["beta0"])]
    weights.extend(float(model["beta_plan"][name]) for name in others)
    weights.append(float(model.get("beta_reno") or 0.0))
    probability = _sigmoid(_dot(weights, _features(plan, renovated, reference, others)))
    matched = next(group for group in model["groups"] if group["plan"] == plan and int(group["renovated"]) == renovated)
    if matched["vacant"] == 0 and probability < 0.01:
        probability = 0.0
    return {
        "plan": plan,
        "renovated": renovated,
        "probability": round(probability, 4),
        "units": matched["units"],
        "vacant": matched["vacant"],
    }


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
