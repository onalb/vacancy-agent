"""The five tools the vacancy agent can call."""

from __future__ import annotations

from pathlib import Path

from agent_framework import tool

from vacancy_agent.fit import fit_vacancy as fit_model
from vacancy_agent.fit import score_vacancy as score_model
from vacancy_agent.parse import parse_rent_roll
from vacancy_agent.store import FitStore

_uploads: dict[str, Path] = {}
_store: FitStore | None = None


def configure(store: FitStore, uploads: dict[str, Path] | None = None) -> None:
    global _store, _uploads
    _store = store
    if uploads is not None:
        _uploads = uploads


def _fits() -> FitStore:
    if _store is None:
        raise RuntimeError("The fit store is not configured.")
    return _store


@tool
def parse_rent_roll_file(file_id: str) -> dict:
    """Parse an uploaded rent roll. Returns property, as-of, unit count, vacant count, and the plan table. Does not save."""
    path = _uploads.get(file_id)
    if path is None or not path.is_file():
        return {"error": "file_not_found", "file_id": file_id}
    parsed = parse_rent_roll(path)
    return {"file_id": file_id, **parsed}


@tool
def fit_vacancy(plans: list[dict]) -> dict:
    """Fit logistic regression for one building from a plan table. plans items have plan, renovated, units, and vacant. Does not save."""
    return fit_model(plans)


@tool
def load_fit(property_name: str = "") -> dict:
    """Read saved fits. Pass a building name for that fit. Pass an empty name for every saved building and as-of."""
    store = _fits()
    if not property_name.strip():
        return {"buildings": store.names()}
    record = store.load(property_name.strip())
    if record is None:
        return {"error": "not_saved", "property": property_name.strip(), "buildings": store.names()}
    return record


@tool
def save_fit(property_name: str, as_of: str, model: dict) -> dict:
    """Write one building fit. model is the object returned by fit_vacancy."""
    record = {
        "property": property_name.strip(),
        "as_of": as_of,
        "reference_plan": model["reference_plan"],
        "beta0": model["beta0"],
        "beta_plan": model["beta_plan"],
        "beta_reno": model["beta_reno"],
        "groups": model["groups"],
    }
    return _fits().save(record)


@tool
def score_vacancy(model: dict, plan: str, renovated: int) -> dict:
    """Apply saved weights to one plan and one renovated flag, 0 or 1. Returns the probability and the counts."""
    return score_model(model, plan, renovated)


TOOLS = [parse_rent_roll_file, fit_vacancy, load_fit, save_fit, score_vacancy]
