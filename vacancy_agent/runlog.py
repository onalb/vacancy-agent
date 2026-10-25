"""Operator lines for the run log. No resident names."""

from __future__ import annotations

import json
import time
from contextvars import ContextVar, Token
from typing import Any

_queue: ContextVar[Any] = ContextVar("vacancy_run_queue", default=None)


def bind(queue: Any) -> Token:
    return _queue.set(queue)


def reset(token: Token) -> None:
    _queue.reset(token)


def emit(step: str, message: str) -> None:
    queue = _queue.get()
    if queue is None:
        return
    queue.put_nowait(
        {
            "step": step,
            "message": " ".join((message or "").split()),
            "ts": int(time.time() * 1000),
        }
    )


def _payload(result: Any) -> dict | None:
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        text = result
    elif isinstance(result, list):
        text = "".join(item if isinstance(item, str) else str(getattr(item, "text", "") or "") for item in result)
    else:
        text = str(getattr(result, "text", "") or "")
    if not text.strip():
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _plain(arguments: Any) -> dict:
    if hasattr(arguments, "model_dump"):
        dumped = arguments.model_dump()
        return dumped if isinstance(dumped, dict) else {}
    if isinstance(arguments, dict):
        return arguments
    return {}


def tool_line(name: str, arguments: Any, result: Any) -> str:
    args = _plain(arguments)
    payload = _payload(result)
    if name == "load_skill":
        return f"load_skill {args.get('skill_name', '')}".strip()
    if name == "parse_rent_roll_file":
        if isinstance(payload, dict) and payload.get("error"):
            return f"parse_rent_roll_file → {payload['error']}"
        if isinstance(payload, dict):
            return (
                f"parse_rent_roll_file → {payload.get('property')} "
                f"as of {payload.get('as_of')}, {payload.get('units')} units, "
                f"{payload.get('vacant')} vacant"
            )
    if name == "fit_vacancy":
        groups = payload.get("groups") if isinstance(payload, dict) else None
        count = len(groups) if isinstance(groups, list) else 0
        return f"fit_vacancy → {count} groups"
    if name == "load_fit":
        asked = (args.get("property_name") or "").strip() or "all buildings"
        if isinstance(payload, dict) and payload.get("error"):
            saved = payload.get("buildings") or []
            names = ", ".join(
                item.get("property", "") for item in saved if isinstance(item, dict) and item.get("property")
            ) or "none"
            return f"load_fit {asked} → {payload['error']} (saved: {names})"
        if isinstance(payload, dict) and "buildings" in payload and "as_of" not in payload:
            return f"load_fit → {len(payload['buildings'])} saved"
        if isinstance(payload, dict):
            return f"load_fit → {payload.get('property')} as of {payload.get('as_of')}"
    if name == "save_fit":
        if isinstance(payload, dict):
            return f"save_fit → {payload.get('property')} as of {payload.get('as_of')}"
    if name == "score_vacancy":
        plan = args.get("plan") or ""
        building = args.get("building") or ""
        renovated = args.get("renovated")
        if isinstance(payload, dict) and payload.get("error"):
            return f"score_vacancy {building} {plan} → {payload['error']}"
        if isinstance(payload, dict):
            return (
                f"score_vacancy {building} {plan} renovated={renovated} → {payload.get('probability')} "
                f"({payload.get('vacant')} vacant of {payload.get('units')})"
            )
    return name
