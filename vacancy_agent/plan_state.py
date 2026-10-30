"""This turn's checklist for the vacancy app. The gateway does not store it."""

from __future__ import annotations

import re
from contextvars import ContextVar
from typing import Any

WORK_TOOLS = frozenset(
    {
        "parse_rent_roll_file",
        "fit_vacancy",
        "load_fit",
        "list_trained_properties",
        "save_fit",
        "delete_fit",
        "score_vacancy",
    }
)

_checklist: ContextVar[list[dict[str, str]] | None] = ContextVar("vacancy_checklist", default=None)
_events: ContextVar[list[dict[str, str]] | None] = ContextVar("vacancy_plan_events", default=None)
# Pending delete survives reset(). Checklist rows are per turn; this flag is per session.
_session_key: ContextVar[str | None] = ContextVar("vacancy_session_key", default=None)
_fallback_session = ""
_pending_deletes: dict[str, dict] = {}
# Tool calls run on separate tasks. A ContextVar set in create_plan is invisible
# to the next tool, so the checklist and tool events live on the session.
_session_checklists: dict[str, list[dict[str, str]]] = {}
_session_events: dict[str, list[dict[str, str]]] = {}


def reset() -> None:
    key = current_session()
    _session_checklists[key] = []
    _session_events[key] = []
    _checklist.set([])
    _events.set([])


def bind_session(session_id: str) -> None:
    """Remember which chat session the next tool call belongs to."""
    global _fallback_session
    key = (session_id or "").strip()
    _session_key.set(key)
    _fallback_session = key


def current_session() -> str:
    value = _session_key.get()
    if value is not None:
        return value
    return _fallback_session


def get_pending_delete() -> dict | None:
    item = _pending_deletes.get(current_session())
    return dict(item) if item else None


def set_pending_delete(scope: dict) -> None:
    _pending_deletes[current_session()] = dict(scope)


def clear_pending_delete() -> None:
    _pending_deletes.pop(current_session(), None)


# Transient plan-table fits. An MCP ask_vacancy call may attach plan_table
# (aggregated per-plan group counts). It is fit here, per session, and is
# NEVER written to the FitStore — no disk, no Azure blob, and never in
# list_trained_properties. A call without plan_table clears it, so every
# call is fit-by-value and nothing leaks across sessions.
_transient_fits: dict[str, dict] = {}


def set_transient_fit(record: dict | None) -> None:
    key = current_session()
    if record is None:
        _transient_fits.pop(key, None)
    else:
        _transient_fits[key] = dict(record)


def get_transient_fit() -> dict | None:
    item = _transient_fits.get(current_session())
    return dict(item) if item else None


def checklist() -> list[dict[str, str]]:
    key = current_session()
    if key in _session_checklists:
        return [dict(row) for row in _session_checklists[key]]
    return [dict(row) for row in (_checklist.get() or [])]


def _save_rows(rows: list[dict[str, str]]) -> None:
    copied = [dict(row) for row in rows]
    _session_checklists[current_session()] = copied
    _checklist.set([dict(row) for row in copied])


def _read_events() -> list[dict[str, str]]:
    key = current_session()
    if key in _session_events:
        return [dict(row) for row in _session_events[key]]
    return [dict(row) for row in (_events.get() or [])]


def _save_events(events: list[dict[str, str]]) -> None:
    copied = [dict(row) for row in events]
    _session_events[current_session()] = copied
    _events.set([dict(row) for row in copied])


def set_checklist(items: list[dict[str, Any]]) -> None:
    rows: list[dict[str, str]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        status = str(item.get("status") or "pending")
        if status not in {"pending", "in_progress", "completed", "incomplete"}:
            status = "pending"
        rows.append({"text": text, "status": status})
    _save_rows(rows)


def _mentions(text: str, tool: str) -> bool:
    """True when the task text names this tool, in parentheses or as a bare word."""
    return (
        re.search(rf"(?<![A-Za-z0-9_]){re.escape(tool)}(?![A-Za-z0-9_])", text or "", re.IGNORECASE)
        is not None
    )


def _open_row(rows: list[dict[str, str]], tool: str) -> int | None:
    """First row that names tool and is not already completed."""
    for index, row in enumerate(rows):
        if row.get("status") == "completed":
            continue
        if _mentions(row.get("text") or "", tool):
            return index
    return None


def advance_tool(name: str, status: str) -> bool:
    """Move the matching checklist row. No checklist means do not invent one."""
    if name not in WORK_TOOLS or status not in {"in_progress", "completed", "incomplete"}:
        return False
    rows = checklist()
    if not rows:
        return False
    index = _open_row(rows, name)
    if index is None:
        return False
    current = rows[index].get("status") or "pending"
    if status == "in_progress" and current != "pending":
        return False
    if current == status:
        return False
    rows[index]["status"] = status
    _save_rows(rows)
    return True


def complete_report_rows() -> bool:
    """Mark each still-pending row that names no work tool completed. Do not add a row."""
    rows = checklist()
    if not rows:
        return False
    changed = False
    for row in rows:
        if row.get("status") != "pending":
            continue
        if any(_mentions(row.get("text") or "", tool) for tool in WORK_TOOLS):
            continue
        row["status"] = "completed"
        changed = True
    if changed:
        _save_rows(rows)
    return changed


def _payload(result: Any) -> dict | None:
    if isinstance(result, dict):
        return result
    text = ""
    if isinstance(result, str):
        text = result
    elif isinstance(result, list):
        text = "".join(
            item if isinstance(item, str) else str(getattr(item, "text", "") or "") for item in result
        )
    else:
        text = str(getattr(result, "text", "") or "")
    if not text.strip():
        return None
    import json

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def note(name: str, result: Any) -> None:
    """Remember a finished tool so the next checklist call can describe this turn."""
    payload = _payload(result)
    status = "ok"
    if isinstance(payload, dict) and (payload.get("ok") is False or payload.get("error")):
        status = "error"
    events = _read_events()
    events.append({"name": str(name or ""), "status": status})
    _save_events(events)


def harness() -> dict[str, Any]:
    last_tool = ""
    last_status = ""
    ran_ok: list[str] = []
    status_since_work = False
    for row in _read_events():
        name = row.get("name") or ""
        if name in WORK_TOOLS:
            last_tool = name
            last_status = "error" if row.get("status") == "error" else "ok"
            status_since_work = False
            if last_status == "ok" and name not in ran_ok:
                ran_ok.append(name)
        elif name == "update_plan_status":
            status_since_work = True
    return {
        "checklist": checklist(),
        "last_work_tool": last_tool,
        "last_work_status": last_status if last_tool else "",
        "ran_ok": ran_ok,
        "status_since_work": status_since_work,
    }
