"""The five tools the vacancy agent can call."""

from __future__ import annotations

from pathlib import Path

from agent_framework import tool

from vacancy_agent.fit import fit_vacancy as fit_model
from vacancy_agent.fit import plan_catalog
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
    """Read saved fits.

    When the user asks what properties you are trained on, which buildings, or to list properties, pass an empty property_name. The return is {buildings: [...]}. Name those buildings. If buildings is empty, say none are trained. Do not ask to upload a rent roll unless they want to train a new one.

    Pass a building name for that one fit. The return is property, as_of, plan_keys, and plans (plan + renovated only). Use those exact plan_keys as score_vacancy plan=. If the user did not name one unique plan, ASK among plan_keys (and renovated 0 vs 1 when both appear in plans). Do not score every plan. This return has no probabilities or betas. Do not use an inventory question as a cue to ask for a rent roll.
    """
    return load_saved(property_name)


def load_saved(property_name: str = "") -> dict:
    store = _fits()
    if not property_name.strip():
        return {"buildings": store.names()}
    record = store.load(property_name.strip())
    if record is None:
        return {"error": "not_saved", "property": property_name.strip(), "buildings": store.names()}
    return {
        "property": record.get("property"),
        "as_of": record.get("as_of"),
        **plan_catalog(record),
    }


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


def score_saved(building: str, plan: str = "", renovated: int | None = None) -> dict:
    name = (building or "").strip()
    if not name:
        return {"error": "building_required", "buildings": _fits().names()}
    record = _fits().load(name)
    if record is None:
        return {"error": "not_saved", "property": name, "buildings": _fits().names()}
    return score_model(record, plan, renovated)


@tool
def score_vacancy(building: str, plan: str = "", renovated: int | None = None) -> dict:
    """Score p(vacant) for one saved building and one unique floor plan.

    Always pass building (the property name from load_fit), including on follow-ups
    that only name a plan. Call this once, after the user named one unique plan.
    Never loop this tool over every plan_key. If plan is missing or is a family
    (1x1, 2x2) matching two or more plan_keys, or the same plan has renovated 0 and 1
    and renovated was not passed, the return is error ambiguous_plan with plan_keys
    and plans — ask among those and give no probability. exact '2x2 F' or compact
    '2x2F' is unique. renovated is 0 or 1 when the same plan has both. Do not pass a
    reconstructed model. Loads the saved fit itself.
    """
    return score_saved(building, plan, renovated)


TOOLS = [parse_rent_roll_file, fit_vacancy, load_fit, save_fit, score_vacancy]
