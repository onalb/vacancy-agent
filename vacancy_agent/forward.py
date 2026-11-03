"""One forwarder for every gateway tool the vacancy model calls.

tools/list supplies the schema. Session fields stay off that schema. A tool
with a checklist argument gets the checklist this session stored. The four
plan-tool names are not written here.
"""

from __future__ import annotations

import base64
import inspect
from typing import Any, Callable

HIDDEN = frozenset(
    {
        "route",
        "username",
        "checklist",
        "last_work_tool",
        "last_work_status",
        "ran_ok",
        "status_since_work",
        "confirm",
        "content_base64",
        "roll",
        "hitl_allow",
        "filename",
    }
)


def schema_properties(spec: dict[str, Any]) -> dict[str, Any]:
    schema = spec.get("input_schema") if isinstance(spec.get("input_schema"), dict) else {}
    props = schema.get("properties") if isinstance(schema, dict) else {}
    return props if isinstance(props, dict) else {}


def has_argument(spec: dict[str, Any], name: str) -> bool:
    return name in schema_properties(spec)


def visible_properties(spec: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in schema_properties(spec).items() if key not in HIDDEN}


def stamp_arguments(spec: dict[str, Any], model_args: dict[str, Any], *, route: str) -> dict[str, Any]:
    from vacancy_agent.plan_state import harness

    props = schema_properties(spec)
    clean = {
        key: value
        for key, value in model_args.items()
        if key in props and key not in HIDDEN and value is not None
    }
    if "route" in props:
        clean["route"] = route
    if "content_base64" in props:
        _attach_upload(clean)
    if "checklist" in props:
        state = harness()
        clean["checklist"] = state.get("checklist") or []
        for key in ("last_work_tool", "last_work_status", "ran_ok", "status_since_work"):
            if key in props:
                clean[key] = state.get(key)
    return clean


def _attach_upload(clean: dict[str, Any]) -> None:
    from vacancy_agent.tools import _uploads

    path = _uploads.get(str(clean.get("file_id") or ""))
    if path is None or not path.is_file():
        return
    clean["filename"] = path.name
    clean["content_base64"] = base64.b64encode(path.read_bytes()).decode("ascii")


def _annotation(prop: dict[str, Any], required: bool) -> Any:
    kind = prop.get("type") if isinstance(prop, dict) else None
    base: Any = {
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }.get(str(kind or ""), str)
    if required:
        return base
    return base | None


def tool_function(spec: dict[str, Any], call: Callable[[str, dict[str, Any]], Any]) -> Callable[..., Any]:
    props = visible_properties(spec)
    schema = spec.get("input_schema") if isinstance(spec.get("input_schema"), dict) else {}
    required = {name for name in (schema.get("required") or []) if name in props}
    parameters = [
        inspect.Parameter(
            name,
            inspect.Parameter.KEYWORD_ONLY,
            default=inspect.Parameter.empty if name in required else None,
            annotation=_annotation(prop if isinstance(prop, dict) else {}, name in required),
        )
        for name, prop in props.items()
    ]
    name = str(spec.get("name") or "tool")

    def fn(**kwargs: Any) -> Any:
        return call(name, kwargs)

    fn.__name__ = name
    fn.__doc__ = str(spec.get("description") or name)
    fn.__signature__ = inspect.Signature(parameters)  # type: ignore[attr-defined]
    return fn


def _session_call(name: str, model_args: dict[str, Any]) -> Any | None:
    """Upload, unsaved fit, and delete confirmation stay in this process."""
    from vacancy_agent.plan_state import get_pending_delete, get_transient_fit
    from vacancy_agent.tools import delete_saved, load_saved, save_fit, score_saved

    if name == "load_fit" and get_transient_fit() is not None:
        return load_saved(str(model_args.get("property_name") or ""))
    if name == "save_fit" and get_transient_fit() is not None:
        return save_fit(
            str(model_args.get("property_name") or ""),
            str(model_args.get("as_of") or ""),
            model_args.get("model") or {},
        )
    if name == "score_vacancy" and get_transient_fit() is not None:
        renovated = model_args.get("renovated")
        return score_saved(
            str(model_args.get("building") or ""),
            str(model_args.get("plan") or ""),
            None if renovated is None else int(renovated),
        )
    if name == "delete_fit":
        return delete_saved(
            str(model_args.get("property_name") or ""),
            bool(model_args.get("all_properties")),
            confirm=get_pending_delete() is not None,
        )
    return None


def vacancy_call(name: str, model_args: dict[str, Any], specs: list[dict[str, Any]]) -> Any:
    from vacancy_agent.gateway_client import call_tool
    from vacancy_agent.plan_state import note, set_checklist

    spec = next((item for item in specs if item.get("name") == name), {"name": name})
    local = _session_call(name, model_args)
    if local is not None:
        note(name, local)
        return local
    remote = stamp_arguments(spec, model_args, route="vacancy")
    body = call_tool(name, remote)
    if isinstance(body, dict):
        rows = body.get("checklist")
        if isinstance(rows, list):
            set_checklist([row for row in rows if isinstance(row, dict)])
    note(name, body)
    return body


def tools_from_specs(specs: list[dict[str, Any]]) -> list[Any]:
    """Agent-framework tools whose bodies post tools/call."""
    from agent_framework import tool as af_tool

    held = list(specs)
    built = []
    for spec in specs:
        name = str(spec.get("name") or "")
        if not name or name == "cre_ping":
            continue
        fn = tool_function(
            spec,
            lambda tool_name, args, _specs=held: vacancy_call(tool_name, args, _specs),
        )
        built.append(af_tool(name=name, description=str(spec.get("description") or name))(fn))
    return built
