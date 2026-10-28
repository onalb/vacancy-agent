"""Tools the vacancy agent can call.

delete_fit is the model-facing delete. The pending confirmation lives on this
process's session, next to the checklist. This wrapper calls the gateway
delete only with confirm=true after that same scope is pending. A direct
gateway call is not the user prompt: this tool withholds confirm so the model
cannot skip the user.
"""

from __future__ import annotations

from pathlib import Path

from agent_framework import tool

from vacancy_agent.fit import fit_vacancy as fit_model
from vacancy_agent.fit import plan_catalog
from vacancy_agent.fit import score_vacancy as score_model
from vacancy_agent.parse import parse_rent_roll
from vacancy_agent.store import FitStore, slug, without_group_probability


def _gateway(name: str, arguments: dict):
    """None when CAPABILITIES_GATEWAY_URL is unset (keep the local tool)."""
    from vacancy_agent.gateway_client import call_tool, vacancy_mcp_url

    if not vacancy_mcp_url():
        return None
    return call_tool(name, arguments)

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
    from vacancy_agent.gateway_client import call_tool, vacancy_mcp_url

    path = _uploads.get(file_id)
    if vacancy_mcp_url():
        if path is None or not path.is_file():
            return {"error": "file_not_found", "file_id": file_id}
        import base64

        return call_tool(
            "parse_rent_roll_file",
            {
                "file_id": file_id,
                "filename": path.name,
                "content_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
            },
        )
    if path is None or not path.is_file():
        return {"error": "file_not_found", "file_id": file_id}
    parsed = parse_rent_roll(path)
    return {"file_id": file_id, **parsed}


@tool
def fit_vacancy(plans: list[dict]) -> dict:
    """Fit logistic regression for one building from a plan table. plans items have plan, renovated, units, and vacant. Does not save."""
    remote = _gateway("fit_vacancy", {"plans": plans})
    if remote is not None:
        return remote
    return fit_model(plans)


_NOT_TRAINED = "No properties are trained yet."


def _trained_payload(names: list) -> dict:
    cleaned = [str(name).strip() for name in names if str(name).strip()]
    if not cleaned:
        return {"properties": [], "text": _NOT_TRAINED}
    return {"properties": cleaned, "text": ", ".join(cleaned)}


@tool
def list_trained_properties() -> dict:
    """Return the names of properties this model is trained on.

    Call this when the user asks which properties are trained, which buildings, or to list properties. The return is {properties: [...], text}. Reply with those names. If properties is empty, say no properties are trained yet. Do not call load_fit with an empty name for that question. load_fit remains for one named building. Do not score, fit, or delete. Do not invent a building.
    """
    return list_trained()


def list_trained() -> dict:
    remote = _gateway("list_trained_properties", {})
    if remote is not None:
        return remote
    return _trained_payload(_fits().property_names())


@tool
def load_fit(property_name: str = "") -> dict:
    """Read one named building's saved fit.

    Pass the building name. The return is property, as_of, plan_keys, and plans (plan + renovated only). Use those exact plan_keys as score_vacancy plan=. If the user did not name one unique plan, ASK among plan_keys (and renovated 0 vs 1 when both appear in plans). Do not score every plan. This return has no probabilities or betas. Do not use an inventory question as a cue to ask for a rent roll.

    Do not call this with an empty property_name when the user asks which properties are trained. Call list_trained_properties for that question. load_fit remains for one named building.
    """
    return load_saved(property_name)


def load_saved(property_name: str = "") -> dict:
    remote = _gateway("load_fit", {"property_name": property_name})
    if remote is not None:
        return remote
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
    remote = _gateway(
        "save_fit",
        {"property_name": property_name, "as_of": as_of, "model": model},
    )
    if remote is not None:
        return remote
    record = without_group_probability(
        {
            "property": property_name.strip(),
            "as_of": as_of,
            "reference_plan": model["reference_plan"],
            "beta0": model["beta0"],
            "beta_plan": model["beta_plan"],
            "beta_reno": model["beta_reno"],
            "groups": model["groups"],
        }
    )
    return _fits().save(record)


QUESTION_ALL = "Are you sure? This removes every trained property."


def question_for(property_name: str) -> str:
    return f"Remove {property_name} from the trained model?"


def _flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _saved_name(property_name: str) -> tuple[str | None, list]:
    """Resolve a typed name to the saved property string. Slug or name, case-insensitive."""
    typed = property_name.strip()
    view = load_saved(typed)
    buildings: list = []
    if isinstance(view, dict) and isinstance(view.get("buildings"), list):
        buildings = view["buildings"]
    if isinstance(view, dict) and view.get("property") and not view.get("error"):
        return str(view["property"]), buildings
    if not buildings:
        listed = load_saved("")
        if isinstance(listed, dict) and isinstance(listed.get("buildings"), list):
            buildings = listed["buildings"]
    wanted = typed.casefold()
    wanted_slug = slug(typed)
    for item in buildings:
        if not isinstance(item, dict):
            continue
        saved = str(item.get("property") or "").strip()
        if saved and (saved.casefold() == wanted or slug(saved) == wanted_slug):
            return saved, buildings
    return None, buildings


def _same_scope(pending: dict | None, scope: dict) -> bool:
    if not pending or pending.get("scope") != scope.get("scope"):
        return False
    if scope["scope"] == "all":
        return True
    return pending.get("property") == scope.get("property")


def _execute_delete(scope: dict) -> dict:
    """Delete only after the session gate. The gateway sees confirm=true."""
    arguments: dict = {"confirm": True, "all_properties": scope["scope"] == "all"}
    if scope["scope"] == "one":
        arguments["property_name"] = scope["property"]
    remote = _gateway("delete_fit", arguments)
    if remote is not None:
        return remote
    if scope["scope"] == "all":
        result = _fits().delete_all()
        count = int(result.get("count") or 0)
        return {
            "deleted": True,
            "pending": False,
            "scope": "all",
            "count": count,
            "text": f"Deleted every trained property. {count} JSON files were deleted.",
        }
    result = _fits().delete(str(scope["property"]))
    if not result.get("deleted"):
        return {
            "deleted": False,
            "pending": False,
            "error": "not_found",
            "property": scope.get("property"),
            "text": f"{scope.get('property')} is not trained.",
        }
    saved = str(result.get("property") or scope["property"])
    return {
        "deleted": True,
        "pending": False,
        "scope": "one",
        "property": saved,
        "text": f"Removed {saved} from the trained model. The JSON file was deleted.",
    }


def delete_saved(
    property_name: str = "",
    all_properties: bool = False,
    confirm: bool = False,
) -> dict:
    """Session gate. The first call records a question and does not delete."""
    from vacancy_agent.plan_state import (
        clear_pending_delete,
        get_pending_delete,
        set_pending_delete,
    )

    confirmed = _flag(confirm)
    if _flag(all_properties):
        scope = {"scope": "all", "question": QUESTION_ALL}
    else:
        typed = (property_name or "").strip()
        if not typed:
            return {
                "deleted": False,
                "pending": False,
                "error": "property_required",
                "text": "Name a trained property, or ask to remove every trained property.",
            }
        saved, buildings = _saved_name(typed)
        if not saved:
            return {
                "deleted": False,
                "pending": False,
                "error": "not_trained",
                "property": typed,
                "buildings": buildings,
                "text": f"{typed} is not trained.",
            }
        scope = {"scope": "one", "property": saved, "question": question_for(saved)}

    pending = get_pending_delete()
    if confirmed and pending is None:
        return {
            "deleted": False,
            "pending": False,
            "error": "not_confirmed",
            "text": "Nothing was removed.",
        }
    if not confirmed or not _same_scope(pending, scope):
        set_pending_delete(scope)
        body = {
            "deleted": False,
            "pending": True,
            "scope": scope["scope"],
            "question": scope["question"],
        }
        if scope["scope"] == "one":
            body["property"] = scope["property"]
        return body
    result = _execute_delete(scope)
    clear_pending_delete()
    return result


@tool
def delete_fit(
    property_name: str = "",
    all_properties: bool = False,
    confirm: bool = False,
) -> dict:
    """Remove one trained property, or every trained property.

    The first call for a scope does not delete. Show the returned question and
    wait. Call again with confirm=true only after the user agrees to that same
    scope. confirm=true with no pending question deletes nothing. A different
    property replaces the pending question and does not delete the earlier one.
    If the property is not trained, say so and do not delete. Set all_properties
    true and leave property_name empty to remove every trained property. Do not
    use this tool to train or to score.
    """
    return delete_saved(property_name, all_properties=all_properties, confirm=confirm)


_PLAN_HINT = (
    "The first action is create_plan. The numbered list is only the work tools "
    "this turn will call. It does not require a reply row. Do not add a line for "
    "create_plan, update_plan, update_plan_status, reflection, or a reply-only step. "
    "Rows start pending. After each work tool, call update_plan_status "
    "for that row before the next work tool or the final answer. Mark it completed "
    "on success and incomplete on error. Call update_plan only when the list is "
    "wrong or a step is missing, not after every successful tool. Call reflection "
    "when you need to replan. Work tools are parse_rent_roll_file, fit_vacancy, "
    "load_fit, save_fit, score_vacancy, delete_fit, and list_trained_properties. "
    "Call whichever the question needs. "
    "Do not force parse then fit then save."
)
_GATEWAY_REQUIRED = "capabilities gateway is required (set CAPABILITIES_GATEWAY_URL)"


def _pending_work_tool(rows: list) -> str:
    from vacancy_agent.plan_state import WORK_TOOLS, _mentions

    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "") in {"completed", "incomplete"}:
            continue
        text = str(row.get("text") or "")
        for tool in WORK_TOOLS:
            if _mentions(text, tool):
                return tool
    return ""


def _next_work_sentence(rows: list) -> str:
    tool = _pending_work_tool(rows)
    if tool:
        return (
            f"Next call {tool}. Do not call update_plan_status until that tool returns."
        )
    return "Next call the pending work tool. Do not call update_plan_status until it returns."


def _plan(name: str, model_args: dict) -> dict:
    """Send this turn's checklist to /mcp/vacancy and store the returned rows."""
    from vacancy_agent.gateway_client import call_tool, vacancy_mcp_url
    from vacancy_agent.plan_state import harness, set_checklist

    if not vacancy_mcp_url():
        return {"ok": False, "rejected": True, "error": _GATEWAY_REQUIRED}
    state = harness()
    if name == "update_plan_status" and not state.get("last_work_tool"):
        rows = state.get("checklist") or []
        sentence = _next_work_sentence(rows)
        return {
            "ok": False,
            "rejected": True,
            "reason": "work_tool_first",
            "checklist": rows,
            "text": f"No work tool has run yet. {sentence}",
        }
    remote = {key: value for key, value in model_args.items() if value is not None}
    remote.update(state)
    body = call_tool(name, remote)
    if not isinstance(body, dict):
        return {"ok": False, "rejected": True, "error": "capabilities gateway returned a non-object"}
    rows = body.get("checklist")
    if isinstance(rows, list):
        set_checklist(rows)
    if name == "create_plan" and isinstance(rows, list):
        body = dict(body)
        sentence = _next_work_sentence(rows)
        stored = str(body.get("text") or "").strip()
        body["text"] = f"{stored} {sentence}".strip()
    if name == "reflection":
        stored = str(body.get("text") or "Reflection stored.")
        body = dict(body)
        body["hint"] = _PLAN_HINT
        body["text"] = f"{stored}\n{_PLAN_HINT}"
    return body


@tool
def create_plan(tasks: str) -> dict:
    """Open this turn's checklist first. The numbered list is only the work tools this turn will call.

    It does not require a reply row. Do not add a line for create_plan, update_plan,
    update_plan_status, reflection, or a reply-only step. Rows start pending.
    After this returns, call the work tool it names. Do not call update_plan_status until that tool returns.
    Call update_plan_status once after each work tool, before the next work tool or the final answer.
    Call update_plan only when the list is wrong or a step is missing. Do not call create_plan again.
    """
    return _plan("create_plan", {"tasks": tasks})


@tool
def update_plan(tasks: str) -> dict:
    """Replace the remaining checklist steps. Keeps completed and incomplete rows.

    Use this when the list is wrong or a step is missing, not after every successful tool.
    Do not use it only to mark a step completed.
    """
    return _plan("update_plan", {"tasks": tasks})


@tool
def update_plan_status(tasks: str) -> dict:
    """Mark statuses on the existing checklist. Send the same rows with new statuses.

    Call this only after a work tool has returned. A call before any work tool
    is rejected. A second call with no work tool in between is rejected.
    A wholly new list is rejected — use update_plan for that.
    """
    return _plan("update_plan_status", {"tasks": tasks})


@tool
def reflection(analysis: str, need_replan: bool = False) -> dict:
    """Store a short analysis. Set need_replan when the checklist should change.

    This does not rewrite the checklist. Call update_plan with the new steps.
    """
    return _plan("reflection", {"analysis": analysis, "need_replan": bool(need_replan)})


def score_saved(building: str, plan: str = "", renovated: int | None = None) -> dict:
    arguments: dict = {"building": building, "plan": plan}
    if renovated is not None:
        arguments["renovated"] = renovated
    remote = _gateway("score_vacancy", arguments)
    if remote is not None:
        return remote
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
    Never loop this tool over every plan_key. If plan is missing, or is a partial
    family name matching two or more plan_keys, or the same plan has renovated 0 and 1
    and renovated was not passed, the return is error ambiguous_plan with plan_keys
    and plans — ask among those and give no probability. An exact saved plan_key
    (including compact form with no space) is unique. renovated is 0 or 1 when the
    same plan has both. Write the percent field in the reply, such as 73.6%.
    Do not write the probability decimal. Do not pass a reconstructed model.
    Loads the saved fit itself.
    """
    return score_saved(building, plan, renovated)


TOOLS = [
    create_plan,
    update_plan,
    update_plan_status,
    reflection,
    parse_rent_roll_file,
    fit_vacancy,
    load_fit,
    list_trained_properties,
    save_fit,
    delete_fit,
    score_vacancy,
]
