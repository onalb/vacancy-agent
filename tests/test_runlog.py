"""Run log steps: tool name, and the model text before the call kept as the reason."""

import asyncio
import json

from agent_framework import ChatResponse, Content, Message

from vacancy_agent.agent import LlmTrace, ToolTrace
from vacancy_agent.plan_state import checklist
from vacancy_agent.runlog import begin_turn, bind, note_model_step, reset, summary_message, tool_line


class _Queue:
    def __init__(self):
        self.items = []

    def put_nowait(self, item):
        self.items.append(item)


def _response(text, name, arguments, *, finish_reason="tool_calls"):
    contents = []
    if text:
        contents.append(Content.from_text(text))
    contents.append(Content.from_function_call("call-1", name, arguments=arguments))
    return ChatResponse(messages=[Message("assistant", contents)], finish_reason=finish_reason)


def _result(payload):
    return [Content.from_text(json.dumps(payload))]


async def _run_call(text, payload):
    queue = _Queue()
    token = bind(queue)
    begin_turn()
    from vacancy_agent.plan_state import set_checklist

    set_checklist([{"text": "parse_rent_roll_file", "status": "pending"}])
    try:
        chat = type("Chat", (), {"result": _response(text, "parse_rent_roll_file", {"file_id": "abc"})})()

        async def chat_next():
            return None

        await LlmTrace().process(chat, chat_next)

        tool = type(
            "Tool",
            (),
            {"function": type("Fn", (), {"name": "parse_rent_roll_file"})(), "arguments": {"file_id": "abc"}, "result": None},
        )()

        async def tool_next():
            tool.result = _result(payload)

        await ToolTrace().process(tool, tool_next)
    finally:
        reset(token)
    return queue.items


def test_tool_call_log_keeps_model_reason():
    events = asyncio.run(
        _run_call(
            "I'll parse the rent roll first.",
            {"property": "Bay View", "as_of": "2024-01-01", "units": 10, "vacant": 2, "plans": [{"plan": "A1"}]},
        )
    )
    tools = [event for event in events if event["step"] == "tool"]
    assert tools
    assert "parse_rent_roll_file" in tools[-1]["message"]
    assert tools[-1]["reason"] == "I'll parse the rent roll first."
    assert "file_id=abc" in tools[-1]["message"]
    assert "Bay View" in tools[-1]["message"]
    assert "A1" not in tools[-1]["message"]
    assert tools[-1]["status"] == "done"
    assert any(event["step"] == "reason" and event["message"] == "I'll parse the rent roll first." for event in events)
    assert any(event["step"] == "react" and "ReAct turn 1 — parse_rent_roll_file" in event["message"] for event in events)


def test_error_result_marks_the_checklist_error():
    events = asyncio.run(
        _run_call("", {"error": "file_not_found", "file_id": "abc", "resident": "Jane Doe"})
    )
    tool = [event for event in events if event["step"] == "tool"][-1]
    assert tool["status"] == "error"
    assert "parse_rent_roll_file" in tool["message"]
    assert "file_not_found" in tool["message"]
    assert "Jane" not in tool["message"]


def test_tool_call_without_assistant_text_has_no_invented_reason():
    events = asyncio.run(
        _run_call(
            "",
            {"property": "Bay View", "as_of": "2024-01-01", "units": 4, "vacant": 1},
        )
    )
    assert not any(event["step"] == "reason" for event in events)
    tool = [event for event in events if event["step"] == "tool"][-1]
    assert "parse_rent_roll_file" in tool["message"]
    assert "reason" not in tool
    assert "[done] parse_rent_roll_file" not in " ".join(event["message"] for event in events)


def test_tool_line_omits_bytes_names_and_model_dump():
    parsed = tool_line(
        "parse_rent_roll_file",
        {"file_id": "abc", "content_base64": "A" * 120, "filename": r"C:\secret\roll.xlsx"},
        {
            "property": "Bay View",
            "as_of": "2024-01-01",
            "units": 3,
            "vacant": 1,
            "resident": "Jane Doe",
            "email": "jane@example.com",
        },
    )
    assert "parse_rent_roll_file" in parsed
    assert "file_id=abc" in parsed
    assert "Jane" not in parsed
    assert "jane@" not in parsed
    assert "AAAA" not in parsed
    assert "secret" not in parsed
    assert "content_base64" not in parsed

    fitted = tool_line(
        "fit_vacancy",
        {"plans": [{"plan": "A1", "resident": "Jane Doe", "units": 2, "vacant": 0}]},
        {"groups": [{}, {}], "beta0": 9.8765},
    )
    assert "1 plan" in fitted
    assert "2 groups" in fitted
    assert "Jane" not in fitted
    assert "9.8765" not in fitted
    assert "A1" not in fitted

    saved = tool_line(
        "save_fit",
        {
            "property_name": "La Cordoba",
            "as_of": "2024-06-01",
            "model": {"beta0": 9.8765, "groups": [{}, {}, {}], "reference_plan": "A1"},
        },
        {"property": "La Cordoba", "as_of": "2024-06-01", "saved": True},
    )
    assert "property=La Cordoba" in saved
    assert "as_of=2024-06-01" in saved
    assert "3 groups" in saved
    assert "9.8765" not in saved


def test_summary_omits_tokens_the_framework_did_not_send():
    queue = _Queue()
    token = bind(queue)
    begin_turn()
    try:
        note_model_step(_response("Asking which plan.", "load_fit", {"property_name": "La Cordoba"}))
        text = summary_message(True)
    finally:
        reset(token)
    assert "tok" not in text
    assert "1 step" in text
    assert "1 tool" in text
    assert "1 tools" not in text


def test_skipped_tool_is_not_invented():
    queue = _Queue()
    token = bind(queue)
    begin_turn()
    try:
        note_model_step(_response("The user named one plan.", "score_vacancy", {"building": "La Cordoba", "plan": "A1", "renovated": 0}))
    finally:
        reset(token)
    blob = " ".join(event["message"] for event in queue.items)
    assert "score_vacancy" in blob
    assert "fit_vacancy" not in blob
    assert "parse_rent_roll_file" not in blob
    assert "load_fit" not in blob
    assert not any(event["step"] == "plan" for event in queue.items)


def _visible_log(events):
    """Same fold as the page: one checklist block, tool rows update by id."""
    rows = []
    for event in events:
        if event.get("step") == "plan" and isinstance(event.get("items"), list):
            idx = next(
                (i for i, row in enumerate(rows) if row.get("step") == "plan" and isinstance(row.get("items"), list)),
                -1,
            )
            if idx >= 0:
                rows[idx] = event
            else:
                rows.append(event)
        elif event.get("id"):
            idx = next((i for i, row in enumerate(rows) if row.get("id") == event["id"]), -1)
            if idx >= 0:
                rows[idx] = event
            else:
                rows.append(event)
        else:
            rows.append(event)
    return rows


async def _finish_tool(name, arguments, payload):
    tool = type(
        "Tool",
        (),
        {"function": type("Fn", (), {"name": name})(), "arguments": arguments, "result": None},
    )()

    async def tool_next():
        tool.result = _result(payload)

    await ToolTrace().process(tool, tool_next)


def test_create_plan_shows_pending_rows_before_work_and_status_updates_in_place():
    tasks = (
        "1. parse_rent_roll_file\n"
        "2. fit_vacancy\n"
        "3. save_fit\n"
        "Jane Doe jane@example.com\n"
        + ("A" * 120)
    )
    pending = [
        {"text": "parse_rent_roll_file", "status": "pending"},
        {"text": "fit_vacancy", "status": "pending"},
        {"text": "save_fit", "status": "pending"},
    ]
    started = [
        {"text": "parse_rent_roll_file", "status": "in_progress"},
        {"text": "fit_vacancy", "status": "pending"},
        {"text": "save_fit", "status": "pending"},
    ]
    moved = [
        {"text": "parse_rent_roll_file", "status": "completed"},
        {"text": "fit_vacancy", "status": "in_progress"},
        {"text": "save_fit", "status": "pending"},
    ]
    names = ["parse_rent_roll_file", "fit_vacancy", "save_fit"]

    async def run():
        queue = _Queue()
        token = bind(queue)
        begin_turn()
        try:
            note_model_step(_response("Plan the train.", "create_plan", {"tasks": tasks}))
            await _finish_tool("create_plan", {"tasks": tasks}, {"ok": True, "checklist": pending, "text": tasks})
            plans = [event for event in queue.items if event["step"] == "plan"]
            assert len(plans) == 1
            assert [item["tool"] for item in plans[0]["items"]] == names
            assert [item["status"] for item in plans[0]["items"]] == ["pending", "pending", "pending"]
            assert plans[0]["message"] == (
                "1. [pending] parse_rent_roll_file\n"
                "2. [pending] fit_vacancy\n"
                "3. [pending] save_fit"
            )
            assert not any(
                event["step"] == "tool" and event["message"].split()[0] in names for event in queue.items
            )
            assert any(
                event["step"] == "react" and "ReAct turn 1 — create_plan" in event["message"] for event in queue.items
            )
            create_line = [event for event in queue.items if event["step"] == "tool"][-1]
            assert create_line["message"].startswith("create_plan 3 steps")
            assert "Jane" not in json.dumps(queue.items)
            assert "jane@" not in json.dumps(queue.items)
            assert "AAAA" not in json.dumps(queue.items)

            note_model_step(
                _response("", "update_plan_status", {"tasks": "1. [in_progress] parse_rent_roll_file"})
            )
            await _finish_tool(
                "update_plan_status",
                {"tasks": "1. [in_progress] parse_rent_roll_file\n2. [pending] fit_vacancy\n3. [pending] save_fit"},
                {"ok": True, "checklist": started},
            )
            note_model_step(
                _response("", "update_plan_status", {"tasks": "1. [completed] parse_rent_roll_file"})
            )
            await _finish_tool(
                "update_plan_status",
                {
                    "tasks": "1. [completed] parse_rent_roll_file\n2. [in_progress] fit_vacancy\n3. [pending] save_fit"
                },
                {"ok": True, "checklist": moved},
            )
            note_model_step(_response("", "parse_rent_roll_file", {"file_id": "abc"}))
            await _finish_tool(
                "parse_rent_roll_file",
                {"file_id": "abc", "resident": "Jane Doe"},
                {"property": "Bay View", "as_of": "2024-01-01", "units": 4, "vacant": 1},
            )
            return list(queue.items)
        finally:
            reset(token)

    events = asyncio.run(run())
    plans = [event for event in events if event["step"] == "plan"]
    assert [event.get("id") for event in plans] == ["checklist", "checklist", "checklist"]
    assert [item["status"] for item in plans[0]["items"]] == ["pending", "pending", "pending"]
    assert [item["status"] for item in plans[1]["items"]] == ["in_progress", "pending", "pending"]
    assert [item["status"] for item in plans[2]["items"]] == ["completed", "in_progress", "pending"]
    assert all([item["tool"] for item in plan["items"]] == names for plan in plans)
    plan_at = next(i for i, event in enumerate(events) if event["step"] == "plan")
    parse_at = next(
        i
        for i, event in enumerate(events)
        if event["step"] == "tool" and event["message"].startswith("parse_rent_roll_file")
    )
    assert plan_at < parse_at
    shown = [row for row in _visible_log(events) if row["step"] == "plan"]
    assert len(shown) == 1
    assert shown[0]["message"] == (
        "1. [completed] parse_rent_roll_file\n"
        "2. [in_progress] fit_vacancy\n"
        "3. [pending] save_fit"
    )
    assert "[done]" not in shown[0]["message"]


_TRAIN_ROWS = [
    "Check if property 'La Cordoba' is already trained (load_fit)",
    "Fit vacancy model to the parsed plans (fit_vacancy)",
    "Save the trained fit for 'La Cordoba' (save_fit)",
    "Report that the model was saved and give summary info",
]


def _answer(text):
    return ChatResponse(
        messages=[Message("assistant", [Content.from_text(text)])],
        finish_reason="stop",
    )


def _plan_statuses(event):
    return [item["status"] for item in event["items"]]


def test_work_tools_update_the_same_checklist_as_they_finish():
    """Rows leave [pending] when the matching tool finishes. The model never calls update_plan_status."""
    pending = [{"text": text, "status": "pending"} for text in _TRAIN_ROWS]
    tasks = "\n".join(f"{index}. {text}" for index, text in enumerate(_TRAIN_ROWS, 1))

    async def run():
        queue = _Queue()
        token = bind(queue)
        begin_turn()
        try:
            note_model_step(_response("Plan the train.", "create_plan", {"tasks": tasks}))
            await _finish_tool("create_plan", {"tasks": tasks}, {"ok": True, "checklist": pending})
            await _finish_tool(
                "load_fit",
                {"property_name": "La Cordoba"},
                {"property": "La Cordoba", "as_of": "2024-01-01", "plans": []},
            )
            await _finish_tool("fit_vacancy", {"plans": [{}, {}]}, {"groups": [{}, {}]})
            await _finish_tool(
                "save_fit",
                {"property_name": "La Cordoba", "as_of": "2024-06-01", "model": {"groups": [{}, {}, {}]}},
                {"property": "La Cordoba", "as_of": "2024-06-01", "saved": True},
            )
            note_model_step(_answer("Saved the vacancy model for La Cordoba."))
            return list(queue.items), checklist()
        finally:
            reset(token)

    events, held = asyncio.run(run())
    plans = [event for event in events if event["step"] == "plan"]
    assert [event.get("id") for event in plans] == ["checklist"] * len(plans)
    assert len(plans) == 8
    work_rows = _TRAIN_ROWS[:3]
    assert [_plan_statuses(plan) for plan in plans] == [
        ["pending", "pending", "pending"],
        ["in_progress", "pending", "pending"],
        ["completed", "pending", "pending"],
        ["completed", "in_progress", "pending"],
        ["completed", "completed", "pending"],
        ["completed", "completed", "in_progress"],
        ["completed", "completed", "completed"],
        ["completed", "completed", "completed"],
    ]
    assert [item["tool"] for item in plans[0]["items"]] == work_rows
    assert all([item["tool"] for item in plan["items"]] == work_rows for plan in plans)
    assert plans[0]["message"] == (
        "1. [pending] Check if property 'La Cordoba' is already trained (load_fit)\n"
        "2. [pending] Fit vacancy model to the parsed plans (fit_vacancy)\n"
        "3. [pending] Save the trained fit for 'La Cordoba' (save_fit)"
    )
    assert "[done]" not in plans[-1]["message"]
    assert "Report that the model was saved" not in plans[-1]["message"]
    assert "1. [completed] Check if property 'La Cordoba' is already trained (load_fit)" in plans[-1]["message"]
    draft_at = next(i for i, event in enumerate(events) if event["step"] == "draft")
    prior = [event for event in events[:draft_at] if event["step"] == "plan"]
    assert len(prior[-1]["items"]) == 3
    assert prior[-1]["items"][2]["status"] == "completed"
    assert "Report that the model was saved" not in prior[-1]["message"]
    shown = [row for row in _visible_log(events) if row["step"] == "plan"]
    assert len(shown) == 1
    assert _plan_statuses(shown[0]) == ["completed", "completed", "completed"]
    assert held == [{"text": text, "status": "completed"} for text in _TRAIN_ROWS]


def test_failed_work_tool_marks_its_row_incomplete():
    pending = [{"text": text, "status": "pending"} for text in _TRAIN_ROWS]

    async def run():
        queue = _Queue()
        token = bind(queue)
        begin_turn()
        try:
            await _finish_tool("create_plan", {"tasks": "1. load_fit"}, {"ok": True, "checklist": pending})
            await _finish_tool(
                "load_fit",
                {"property_name": "La Cordoba"},
                {"error": "not_saved", "property": "La Cordoba"},
            )
            return list(queue.items), checklist()
        finally:
            reset(token)

    events, held = asyncio.run(run())
    plans = [event for event in events if event["step"] == "plan"]
    assert [_plan_statuses(plan) for plan in plans] == [
        ["pending", "pending", "pending"],
        ["in_progress", "pending", "pending"],
        ["incomplete", "pending", "pending"],
    ]
    assert "Report that the model was saved" not in plans[-1]["message"]
    assert held[0]["status"] == "incomplete"
    assert held[-1]["status"] == "pending"
    assert len([row for row in _visible_log(events) if row["step"] == "plan"]) == 1


def test_same_tool_updates_the_first_open_row():
    pending = [
        {"text": "load_fit the saved building", "status": "pending"},
        {"text": "load_fit again if needed", "status": "pending"},
    ]

    async def run():
        queue = _Queue()
        token = bind(queue)
        begin_turn()
        try:
            await _finish_tool("create_plan", {"tasks": "1. load_fit\n2. load_fit"}, {"ok": True, "checklist": pending})
            await _finish_tool("load_fit", {"property_name": "La Cordoba"}, {"property": "La Cordoba", "as_of": "2024-01-01"})
            await _finish_tool("load_fit", {}, {"buildings": []})
            return list(queue.items)
        finally:
            reset(token)

    plans = [event for event in asyncio.run(run()) if event["step"] == "plan"]
    assert [_plan_statuses(plan) for plan in plans] == [
        ["pending", "pending"],
        ["in_progress", "pending"],
        ["completed", "pending"],
        ["completed", "in_progress"],
        ["completed", "completed"],
    ]


def test_final_answer_does_not_invent_a_report_row():
    pending = [
        {"text": "load_fit", "status": "pending"},
        {"text": "save_fit", "status": "pending"},
    ]

    async def run():
        queue = _Queue()
        token = bind(queue)
        begin_turn()
        try:
            await _finish_tool("create_plan", {"tasks": "1. load_fit\n2. save_fit"}, {"ok": True, "checklist": pending})
            note_model_step(_answer("Nothing was saved."))
            return list(queue.items), checklist()
        finally:
            reset(token)

    events, held = asyncio.run(run())
    plans = [event for event in events if event["step"] == "plan"]
    assert len(plans) == 1
    assert _plan_statuses(plans[0]) == ["pending", "pending"]
    assert len(held) == 2
    assert [row["status"] for row in held] == ["pending", "pending"]


def _call(name, arguments):
    return type(
        "Tool",
        (),
        {"function": type("Fn", (), {"name": name})(), "arguments": arguments, "result": None},
    )()


def test_work_tool_before_create_plan_does_not_run():
    async def run():
        queue = _Queue()
        token = bind(queue)
        begin_turn()
        called = 0
        try:
            tool = _call("load_fit", {"property_name": "Hill"})

            async def tool_next():
                nonlocal called
                called += 1
                tool.result = {"property": "Hill", "as_of": "2024-01-01", "plans": []}

            await ToolTrace().process(tool, tool_next)
            return called, tool.result
        finally:
            reset(token)

    called, result = asyncio.run(run())
    assert called == 0
    assert result["error"] == "no_checklist"
    assert result["text"] == "Call create_plan first."
    assert "Hill" not in result["text"]


def test_load_skill_runs_without_a_checklist():
    async def run():
        queue = _Queue()
        token = bind(queue)
        begin_turn()
        called = 0
        try:
            tool = _call("load_skill", {"skill_name": "vacancy"})

            async def tool_next():
                nonlocal called
                called += 1
                tool.result = "loaded"

            await ToolTrace().process(tool, tool_next)
            return called, tool.result
        finally:
            reset(token)

    called, result = asyncio.run(run())
    assert called == 1
    assert result == "loaded"


def test_successful_load_fit_tells_the_model_to_call_update_plan_status():
    async def run():
        queue = _Queue()
        token = bind(queue)
        begin_turn()
        try:
            from vacancy_agent.plan_state import set_checklist

            set_checklist([{"text": "load_fit", "status": "pending"}])
            tool = _call("load_fit", {"property_name": "Hill"})

            async def tool_next():
                tool.result = {"property": "Hill", "as_of": "2024-01-01", "plans": []}

            await ToolTrace().process(tool, tool_next)
            return tool.result
        finally:
            reset(token)

    result = asyncio.run(run())
    assert result["property"] == "Hill"
    assert result["text"] == "Call update_plan_status for this row and mark it completed."


def test_failed_load_fit_tells_the_model_to_mark_the_row_incomplete():
    async def run():
        queue = _Queue()
        token = bind(queue)
        begin_turn()
        try:
            from vacancy_agent.plan_state import set_checklist

            set_checklist([{"text": "load_fit", "status": "pending"}])
            tool = _call("load_fit", {"property_name": "Hill"})

            async def tool_next():
                tool.result = {"error": "not_saved", "property": "Hill", "buildings": []}

            await ToolTrace().process(tool, tool_next)
            return tool.result
        finally:
            reset(token)

    result = asyncio.run(run())
    assert result["error"] == "not_saved"
    assert result["text"] == "Call update_plan_status for this row and mark it incomplete."


def test_update_plan_status_checklist_replaces_the_pending_row():
    pending = [
        {"text": "load_fit", "status": "pending"},
        {"text": "Reply with the trained list", "status": "pending"},
    ]
    replaced = [
        {"text": "load_fit", "status": "completed"},
        {"text": "Reply with the trained list", "status": "pending"},
    ]

    async def run():
        queue = _Queue()
        token = bind(queue)
        begin_turn()
        try:
            await _finish_tool(
                "create_plan",
                {"tasks": "1. load_fit\n2. Reply with the trained list"},
                {"ok": True, "checklist": pending},
            )
            await _finish_tool(
                "update_plan_status",
                {"tasks": "1. [completed] load_fit\n2. [pending] Reply with the trained list"},
                {"ok": True, "checklist": replaced},
            )
            return list(queue.items)
        finally:
            reset(token)

    events = asyncio.run(run())
    plans = [event for event in events if event["step"] == "plan"]
    assert [event.get("id") for event in plans] == ["checklist", "checklist"]
    assert _plan_statuses(plans[0]) == ["pending"]
    assert _plan_statuses(plans[1]) == ["completed"]
    shown = [row for row in _visible_log(events) if row["step"] == "plan"]
    assert len(shown) == 1
    assert [item["tool"] for item in shown[0]["items"]] == ["load_fit"]
    assert _plan_statuses(shown[0]) == ["completed"]
    assert "Reply with the trained list" not in shown[0]["message"]


def test_create_plan_marks_a_tool_that_already_succeeded():
    fresh = [
        {"text": "load_fit", "status": "pending"},
        {"text": "Reply with the trained list", "status": "pending"},
    ]

    async def run():
        queue = _Queue()
        token = bind(queue)
        begin_turn()
        try:
            from vacancy_agent.plan_state import set_checklist

            set_checklist([{"text": "load_fit", "status": "pending"}])
            await _finish_tool(
                "load_fit",
                {"property_name": "Hill"},
                {"property": "Hill", "as_of": "2024-01-01", "plans": []},
            )
            await _finish_tool(
                "create_plan",
                {"tasks": "1. load_fit\n2. Reply with the trained list"},
                {"ok": True, "checklist": fresh},
            )
            opened = [event for event in queue.items if event["step"] == "plan"][-1]
            assert _plan_statuses(opened) == ["completed"]
            assert [item["tool"] for item in opened["items"]] == ["load_fit"]
            note_model_step(_answer("Hill is trained."))
            closed = [event for event in queue.items if event["step"] == "plan"][-1]
            assert _plan_statuses(closed) == ["completed"]
            shown = [row for row in _visible_log(queue.items) if row["step"] == "plan"]
            assert len(shown) == 1
            assert [item["tool"] for item in shown[0]["items"]] == ["load_fit"]
            assert "Reply with the trained list" not in shown[0]["message"]
        finally:
            reset(token)

    asyncio.run(run())


def test_plan_block_renders_only_the_work_tool_row():
    """Plan lines for planning itself stay out of the checklist. Tool calls stay in the log."""
    pending = [
        {"text": "load_fit", "status": "pending"},
        {"text": "update_plan_status", "status": "pending"},
        {"text": "create_plan", "status": "pending"},
    ]
    completed = [
        {"text": "load_fit", "status": "completed"},
        {"text": "update_plan_status", "status": "pending"},
        {"text": "create_plan", "status": "pending"},
    ]

    async def run():
        queue = _Queue()
        token = bind(queue)
        begin_turn()
        try:
            note_model_step(_response("Plan the load.", "create_plan", {"tasks": "1. load_fit"}))
            await _finish_tool(
                "create_plan",
                {"tasks": "1. load_fit\n2. update_plan_status\n3. create_plan"},
                {"ok": True, "checklist": pending},
            )
            note_model_step(_response("", "update_plan_status", {"tasks": "1. [completed] load_fit"}))
            await _finish_tool(
                "update_plan_status",
                {"tasks": "1. [completed] load_fit"},
                {"ok": True, "checklist": completed},
            )
            return list(queue.items)
        finally:
            reset(token)

    events = asyncio.run(run())
    shown = [row for row in _visible_log(events) if row["step"] == "plan"]
    assert len(shown) == 1
    assert [item["tool"] for item in shown[0]["items"]] == ["load_fit"]
    assert shown[0]["items"][0]["status"] == "completed"
    assert shown[0]["message"] == "1. [completed] load_fit"
    react = [row["message"] for row in events if row["step"] == "react"]
    tools = [row["message"] for row in events if row["step"] == "tool"]
    assert any("create_plan" in line for line in react)
    assert any("update_plan_status" in line for line in react)
    assert any(line.startswith("create_plan") for line in tools)
    assert any(line.startswith("update_plan_status") for line in tools)

    mixed = [
        {"text": "load_fit", "status": "pending"},
        {"text": "update_plan", "status": "pending"},
        {"text": "reflection", "status": "pending"},
        {"text": "Mark the row completed", "status": "pending"},
        {"text": "Update the checklist", "status": "pending"},
        {"text": "Open the plan", "status": "pending"},
        {"text": "Mark load_fit completed", "status": "in_progress"},
    ]

    async def run_mixed():
        queue = _Queue()
        token = bind(queue)
        begin_turn()
        try:
            await _finish_tool(
                "create_plan",
                {"tasks": "1. load_fit"},
                {"ok": True, "checklist": mixed},
            )
            return list(queue.items)
        finally:
            reset(token)

    mixed_plans = [event for event in asyncio.run(run_mixed()) if event["step"] == "plan"]
    assert len(mixed_plans) == 1
    assert [item["tool"] for item in mixed_plans[0]["items"]] == [
        "load_fit",
        "Mark load_fit completed",
    ]
    message = mixed_plans[0]["message"]
    assert "update_plan" not in message
    assert "reflection" not in message
    assert "Mark the row completed" not in message
    assert "Update the checklist" not in message
    assert "Open the plan" not in message
    assert message == (
        "1. [pending] load_fit\n"
        "2. [in_progress] Mark load_fit completed"
    )
