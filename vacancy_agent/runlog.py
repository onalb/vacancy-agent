"""Operator lines for the run log. No resident names, file bytes, or storage keys."""

from __future__ import annotations

import json
import re
import time
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

_queue: ContextVar[Any] = ContextVar("vacancy_run_queue", default=None)
_turn: ContextVar["TurnLog | None"] = ContextVar("vacancy_turn_log", default=None)

_REASON_LIMIT = 500
_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s])\d{3}[-.\s]\d{4}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_BLOB = re.compile(r"\b[A-Za-z0-9+/]{80,}={0,2}\b")
_PATH = re.compile(r"(?:[A-Za-z]:\\[^\s]+|/(?:Users|home|tmp|var)/[^\s]+)")
_PLAN_TOOLS = frozenset({"create_plan", "update_plan", "update_plan_status"})
_NUMBERED_STEP = re.compile(r"(?m)^\s*\d+\s*[\.\)]")


def bind(queue: Any) -> Token:
    return _queue.set(queue)


def reset(token: Token) -> None:
    _queue.reset(token)


def begin_turn() -> None:
    _turn.set(TurnLog())
    from vacancy_agent.plan_state import reset as reset_plan

    reset_plan()


def scrub(text: str) -> str:
    cleaned = _EMAIL.sub("[redacted]", text or "")
    cleaned = _PHONE.sub("[redacted]", cleaned)
    cleaned = _SSN.sub("[redacted]", cleaned)
    cleaned = _BLOB.sub("[redacted]", cleaned)
    cleaned = _PATH.sub("[redacted]", cleaned)
    return cleaned


def _clean(message: str) -> str:
    lines = [" ".join(scrub(line).split()) for line in (message or "").splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _short(text: str) -> str:
    cleaned = " ".join(scrub(text).split())
    if len(cleaned) <= _REASON_LIMIT:
        return cleaned
    return cleaned[: _REASON_LIMIT - 1].rstrip() + "…"


def emit(step: str, message: str, **extra: Any) -> None:
    queue = _queue.get()
    if queue is None:
        return
    payload: dict[str, Any] = {
        "step": step,
        "message": _clean(message),
        "ts": int(time.time() * 1000),
    }
    if extra.get("id"):
        payload["id"] = str(extra["id"])
    if extra.get("status"):
        payload["status"] = str(extra["status"])
    if extra.get("reason"):
        payload["reason"] = _short(str(extra["reason"]))
    items = extra.get("items")
    if isinstance(items, list):
        payload["items"] = [
            {
                "tool": str(item.get("tool") or ""),
                "status": str(item.get("status") or ""),
                "reason": _short(str(item.get("reason") or "")),
            }
            for item in items
            if isinstance(item, dict)
        ]
    queue.put_nowait(payload)


@dataclass
class CheckItem:
    id: str
    tool: str
    status: str
    reason: str
    args: str = ""
    opened: bool = False


@dataclass
class PlanItem:
    tool: str
    status: str
    reason: str = ""


@dataclass
class TurnLog:
    n: int = 0
    seq: int = 0
    items: list[CheckItem] = field(default_factory=list)
    plan: list[PlanItem] = field(default_factory=list)
    pending_reason: str = ""
    started: float = field(default_factory=time.perf_counter)
    input_tokens: int | None = None
    output_tokens: int | None = None

    def next_id(self) -> str:
        self.seq += 1
        return f"t{self.seq}"


def _state() -> TurnLog:
    state = _turn.get()
    if state is None:
        state = TurnLog()
        _turn.set(state)
    return state


def _mapping(arguments: Any) -> dict:
    if hasattr(arguments, "model_dump"):
        dumped = arguments.model_dump()
        return dumped if isinstance(dumped, dict) else {}
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        text = arguments.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _count(value: Any) -> int | None:
    return len(value) if isinstance(value, list) else None


def _counted(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def summarize_args(name: str, arguments: Any) -> str:
    """Property, plan, file id, as-of, and counts. Never file bytes or a model dump."""
    args = _mapping(arguments)
    if name == "fit_vacancy":
        count = _count(args.get("plans"))
        return _counted(count, "plan", "plans") if count is not None else ""
    if name == "save_fit":
        bits: list[str] = []
        property_name = str(args.get("property_name") or "").strip()
        as_of = str(args.get("as_of") or "").strip()
        if property_name:
            bits.append(f"property={property_name}")
        if as_of:
            bits.append(f"as_of={as_of}")
        model = args.get("model") if isinstance(args.get("model"), dict) else {}
        groups = _count(model.get("groups") if isinstance(model, dict) else None)
        if groups is not None:
            bits.append(_counted(groups, "group", "groups"))
        return " ".join(bits)
    if name == "load_fit":
        asked = str(args.get("property_name") or "").strip()
        return f"property={asked}" if asked else "all buildings"
    if name == "list_trained_properties":
        return ""
    if name == "parse_rent_roll_file":
        file_id = str(args.get("file_id") or "").strip()
        return f"file_id={file_id}" if file_id else ""
    if name == "score_vacancy":
        bits = []
        building = str(args.get("building") or "").strip()
        plan = str(args.get("plan") or "").strip()
        if building:
            bits.append(f"building={building}")
        if plan:
            bits.append(f"plan={plan}")
        if args.get("renovated") is not None and args.get("renovated") != "":
            bits.append(f"renovated={args.get('renovated')}")
        return " ".join(bits)
    if name in {"load_skill", "read_skill_resource"}:
        skill = str(args.get("skill_name") or args.get("name") or "").strip()
        return f"skill={skill}" if skill else ""
    if name in _PLAN_TOOLS:
        tasks = args.get("tasks")
        if isinstance(tasks, str) and tasks.strip():
            numbered = _NUMBERED_STEP.findall(tasks)
            count = len(numbered) if numbered else len([line for line in tasks.splitlines() if line.strip()])
            return _counted(count, "step", "steps") if count else ""
        return ""
    if name == "reflection":
        return ""
    bits = []
    for key in ("property_name", "property", "building", "plan", "file_id", "as_of"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            bits.append(f"{key}={value.strip()}")
    return " ".join(bits)


def _payload(result: Any) -> dict | None:
    if isinstance(result, dict):
        return result
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
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _error_text(result: Any, payload: dict | None) -> str:
    if isinstance(payload, dict) and payload.get("error"):
        return str(payload["error"])
    items = result if isinstance(result, list) else []
    for item in items:
        if getattr(item, "type", None) == "error":
            return str(getattr(item, "message", None) or "error")
    return ""


def summarize_result(name: str, result: Any) -> str:
    payload = _payload(result)
    error = _error_text(result, payload)
    if name == "load_skill":
        return error or "loaded"
    if name == "read_skill_resource":
        return error or "read"
    if error and name == "load_fit" and isinstance(payload, dict):
        saved = payload.get("buildings") or []
        names = ", ".join(
            item.get("property", "") for item in saved if isinstance(item, dict) and item.get("property")
        ) or "none"
        return f"{error} (saved: {names})"
    if error:
        return error
    if not isinstance(payload, dict):
        return ""
    if name == "parse_rent_roll_file":
        return (
            f"{payload.get('property')} as of {payload.get('as_of')}, "
            f"{payload.get('units')} units, {payload.get('vacant')} vacant"
        )
    if name == "fit_vacancy":
        count = _count(payload.get("groups"))
        return _counted(count or 0, "group", "groups")
    if name == "list_trained_properties":
        names = payload.get("properties")
        if isinstance(names, list) and names:
            shown = ", ".join(str(item) for item in names if str(item).strip())
            if shown:
                return shown
        text = str(payload.get("text") or "").strip()
        return text or "No properties are trained yet."
    if name == "load_fit":
        if "buildings" in payload and "as_of" not in payload:
            return _counted(len(payload["buildings"]), "saved", "saved")
        plans = _count(payload.get("plans"))
        line = f"{payload.get('property')} as of {payload.get('as_of')}"
        if plans is not None:
            line += f", {plans} plans"
        return line
    if name == "save_fit":
        return f"{payload.get('property')} as of {payload.get('as_of')}"
    if name == "delete_fit":
        if payload.get("question"):
            return str(payload["question"])
        if payload.get("text"):
            return str(payload["text"])
        return ""
    if name == "score_vacancy":
        shown = payload.get("percent") or payload.get("probability")
        return f"{shown} ({payload.get('vacant')} vacant of {payload.get('units')})"
    return ""


def tool_line(name: str, arguments: Any, result: Any = None, *, pending: bool = False) -> str:
    head = f"{name} {summarize_args(name, arguments)}".strip()
    if pending or result is None:
        return scrub(head)
    outcome = summarize_result(name, result)
    if outcome:
        return scrub(f"{head} → {outcome}")
    return scrub(head)


def _checklist_message(rows: list[PlanItem]) -> str:
    lines = []
    for index, item in enumerate(rows, 1):
        status = item.status or "pending"
        if item.reason:
            lines.append(f"{index}. [{status}] {item.tool} — {item.reason}")
        else:
            lines.append(f"{index}. [{status}] {item.tool}")
    return "\n".join(lines)


def _plan_rows(payload: dict | None) -> list[PlanItem] | None:
    """Rows the gateway returned. Missing checklist means do not invent one."""
    if not isinstance(payload, dict):
        return None
    raw = payload.get("checklist")
    if not isinstance(raw, list):
        return None
    rows: list[PlanItem] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        tool = _short(str(item.get("text") or item.get("tool") or ""))
        if not tool:
            continue
        status = " ".join(scrub(str(item.get("status") or "pending")).split()) or "pending"
        rows.append(PlanItem(tool=tool, status=status, reason=_short(str(item.get("reason") or ""))))
    return rows


def _visible_plan(rows: list[PlanItem]) -> list[PlanItem]:
    """Rows the checklist shows. A row stays when it names a work tool."""
    from vacancy_agent.plan_state import WORK_TOOLS, _mentions

    return [
        item
        for item in rows
        if any(_mentions(item.tool, tool) for tool in WORK_TOOLS)
    ]


def _emit_plan(state: TurnLog) -> None:
    visible = _visible_plan(state.plan)
    if not visible:
        return
    items = [
        {"tool": item.tool, "status": item.status, "reason": item.reason}
        for item in visible
    ]
    emit("plan", _checklist_message(visible), id="checklist", items=items)


def _sync_held(state: TurnLog) -> None:
    """Keep the process checklist on the same rows the log paints."""
    from vacancy_agent.plan_state import set_checklist

    set_checklist([{"text": item.tool, "status": item.status} for item in state.plan])


def _reflect_held() -> None:
    """Copy status changes onto the one checklist block and emit that same block."""
    from vacancy_agent.plan_state import checklist as held_checklist

    state = _state()
    held = held_checklist()
    if not state.plan or len(held) != len(state.plan):
        return
    changed = False
    for item, row in zip(state.plan, held):
        status = str(row.get("status") or "pending")
        if item.status != status:
            item.status = status
            changed = True
    if changed:
        _emit_plan(state)


def _advance_plan(name: str, status: str) -> None:
    from vacancy_agent.plan_state import advance_tool

    if advance_tool(name, status):
        _reflect_held()


def _complete_plan_reports() -> None:
    from vacancy_agent.plan_state import complete_report_rows

    if complete_report_rows():
        _reflect_held()


def _complete_succeeded_rows(state: TurnLog) -> None:
    """A create_plan row for a tool that already succeeded this turn is completed."""
    from vacancy_agent.plan_state import WORK_TOOLS, _mentions

    succeeded = [
        item.tool for item in state.items if item.status == "done" and item.tool in WORK_TOOLS
    ]
    for tool in succeeded:
        for row in state.plan:
            if row.status in {"completed", "incomplete"}:
                continue
            if _mentions(row.tool, tool):
                row.status = "completed"
                break


def _apply_gateway_plan(name: str, result: Any) -> None:
    """Paint or replace the one checklist from a plan tool result. Does not invent rows."""
    if name not in _PLAN_TOOLS:
        return
    rows = _plan_rows(_payload(result))
    if not rows:
        return
    state = _state()
    state.plan = rows
    if name == "create_plan":
        _complete_succeeded_rows(state)
    _sync_held(state)
    _emit_plan(state)


def _add_usage(state: TurnLog, response: Any) -> None:
    usage = getattr(response, "usage_details", None)
    if usage is None:
        return

    def grab(key: str) -> int | None:
        value = usage.get(key) if isinstance(usage, dict) else getattr(usage, key, None)
        return value if isinstance(value, int) else None

    incoming = grab("input_token_count")
    outgoing = grab("output_token_count")
    if incoming is not None:
        state.input_tokens = (state.input_tokens or 0) + incoming
    if outgoing is not None:
        state.output_tokens = (state.output_tokens or 0) + outgoing


def _model_parts(response: Any) -> tuple[str, list[tuple[str, Any]], str | None]:
    texts: list[str] = []
    calls: list[tuple[str, Any]] = []
    for message in getattr(response, "messages", None) or []:
        role = getattr(message, "role", None)
        if role not in (None, "assistant"):
            continue
        for content in getattr(message, "contents", None) or []:
            kind = getattr(content, "type", None)
            if kind == "text":
                text = str(getattr(content, "text", "") or "").strip()
                if text:
                    texts.append(text)
            elif kind == "function_call":
                name = str(getattr(content, "name", "") or "").strip()
                if name:
                    calls.append((name, getattr(content, "arguments", None)))
    reason = _short(" ".join(texts))
    finish = getattr(response, "finish_reason", None)
    return reason, calls, str(finish) if finish else None


def note_model_step(response: Any) -> None:
    """One ReAct step from a finished model response. Does not invent a reason."""
    state = _state()
    state.n += 1
    if response is None or not hasattr(response, "messages"):
        emit("react", f"ReAct turn {state.n} — model step")
        return
    _add_usage(state, response)
    reason, calls, finish = _model_parts(response)
    if calls:
        bits = []
        for name, arguments in calls:
            summary = summarize_args(name, arguments)
            bits.append(f"{name} {summary}".strip())
        message = f"ReAct turn {state.n} — {', '.join(bits)}"
    else:
        message = f"ReAct turn {state.n} — text-only"
    if finish:
        message += f" stop={finish}"
    emit("react", message)
    if calls:
        state.pending_reason = reason
        if reason:
            emit("reason", reason)
        for name, arguments in calls:
            state.items.append(
                CheckItem(
                    id=state.next_id(),
                    tool=name,
                    status="running",
                    reason=reason,
                    args=summarize_args(name, arguments),
                )
            )
        return
    state.pending_reason = ""
    if reason or finish in {"stop", "end_turn"}:
        _complete_plan_reports()
    if reason:
        emit("draft", reason)


def note_tool_start(name: str, arguments: Any) -> str:
    state = _state()
    item = next(
        (row for row in state.items if row.tool == name and row.status == "running" and not row.opened),
        None,
    )
    if item is None:
        item = CheckItem(
            id=state.next_id(),
            tool=name,
            status="running",
            reason=state.pending_reason,
            args=summarize_args(name, arguments),
        )
        state.items.append(item)
    item.opened = True
    item.args = summarize_args(name, arguments) or item.args
    emit("tool", tool_line(name, arguments, pending=True), id=item.id, status="running", reason=item.reason)
    _advance_plan(name, "in_progress")
    return item.id


def note_tool_finish(item_id: str, name: str, arguments: Any, result: Any) -> None:
    state = _state()
    item = next((row for row in state.items if row.id == item_id), None)
    payload = _payload(result)
    failed = bool(_error_text(result, payload))
    if item is None:
        item = CheckItem(
            id=item_id or state.next_id(),
            tool=name,
            status="error" if failed else "done",
            reason=state.pending_reason,
            args=summarize_args(name, arguments),
            opened=True,
        )
        state.items.append(item)
    else:
        item.status = "error" if failed else "done"
    emit(
        "tool",
        tool_line(name, arguments, result),
        id=item.id,
        status=item.status,
        reason=item.reason,
    )
    from vacancy_agent.plan_state import note as note_plan

    note_plan(name, result)
    _apply_gateway_plan(name, result)
    _advance_plan(name, "incomplete" if failed else "completed")


def fail_running() -> None:
    state = _turn.get()
    if state is None:
        return
    for item in state.items:
        if item.status != "running":
            continue
        item.status = "error"
        if item.opened:
            emit(
                "tool",
                scrub(f"{item.tool} {item.args}".strip() + " → failed"),
                id=item.id,
                status="error",
                reason=item.reason,
            )


def summary_message(ok: bool) -> str:
    state = _state()
    elapsed = max(0.0, time.perf_counter() - state.started)
    parts = [
        "answered" if ok else "failed",
        _counted(state.n, "step", "steps"),
        _counted(len(state.items), "tool", "tools"),
        f"{elapsed:.1f}s",
    ]
    if state.input_tokens is not None and state.output_tokens is not None:
        parts.append(f"in {state.input_tokens} tok · out {state.output_tokens} tok")
    return " · ".join(parts)


def end_turn(*, ok: bool) -> None:
    if not ok:
        fail_running()
    else:
        _complete_plan_reports()
    emit("stop", "answered" if ok else "failed")
    emit("summary", summary_message(ok))
