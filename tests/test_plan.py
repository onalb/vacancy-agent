"""Checklist tools call /mcp/vacancy and show up only when the model calls them."""

from __future__ import annotations

import asyncio
import json

from agent_framework import ChatResponse, Content, Message

from vacancy_agent.agent import INSTRUCTIONS, LlmTrace
from vacancy_agent.plan_state import checklist, note, reset
from vacancy_agent.runlog import begin_turn, bind, note_model_step
from vacancy_agent.tools import TOOLS, create_plan, reflection, update_plan_status


class _Queue:
    def __init__(self):
        self.items = []

    def put_nowait(self, item):
        self.items.append(item)


def test_create_plan_doc_lists_only_work_tools():
    doc = " ".join((getattr(create_plan, "description", None) or "").lower().split())
    assert "the numbered list is only the work tools this turn will call" in doc
    assert "does not require a reply row" in doc
    assert "including the final reply" not in doc
    assert "reply-only step" in doc


def test_plan_tools_are_registered_and_described():
    names = [getattr(tool, "name", None) or getattr(tool, "__name__", "") for tool in TOOLS]
    assert names[:4] == ["create_plan", "update_plan", "update_plan_status", "reflection"]
    assert "score_gcr" not in names
    assert "create_plan" in INSTRUCTIONS
    assert "update_plan_status" in INSTRUCTIONS
    assert "do not force parse then fit then save" in INSTRUCTIONS.lower()
    assert "score_gcr" not in INSTRUCTIONS


def test_plan_tools_require_gateway_when_unset(monkeypatch):
    monkeypatch.delenv("CAPABILITIES_GATEWAY_URL", raising=False)
    monkeypatch.delenv("MCP_URL", raising=False)

    def boom(*_args, **_kwargs):
        raise AssertionError("gateway must not be called")

    monkeypatch.setattr("vacancy_agent.gateway_client.call_tool", boom)
    reset()
    body = create_plan("1. load_fit")
    assert body["ok"] is False
    assert body["rejected"] is True
    assert "capabilities gateway is required" in body["error"]


def test_update_plan_status_before_a_work_tool_does_not_call_the_gateway(monkeypatch):
    monkeypatch.setenv("CAPABILITIES_GATEWAY_URL", "http://127.0.0.1:8010")

    def boom(*_args, **_kwargs):
        raise AssertionError("gateway must not be called")

    monkeypatch.setattr("vacancy_agent.gateway_client.call_tool", boom)
    reset()
    from vacancy_agent.plan_state import set_checklist

    set_checklist([{"text": "list_trained_properties", "status": "pending"}])
    out = update_plan_status("1. [completed] list_trained_properties")
    assert out["ok"] is False
    assert out["rejected"] is True
    assert out["reason"] == "work_tool_first"
    assert "list_trained_properties" in out["text"]
    assert "Do not call update_plan_status until that tool returns" in out["text"]


def test_wrapper_sends_harness_fields_and_stores_checklist(monkeypatch):
    monkeypatch.setenv("CAPABILITIES_GATEWAY_URL", "http://127.0.0.1:8010")
    seen: dict = {}

    def fake(name, arguments, timeout=180.0):
        seen["name"] = name
        seen["arguments"] = arguments
        return {
            "ok": True,
            "rejected": False,
            "checklist": [{"text": "load_fit", "status": "completed"}],
            "text": "Plan updated",
        }

    monkeypatch.setattr("vacancy_agent.gateway_client.call_tool", fake)
    reset()
    note("load_fit", {"buildings": []})
    out = update_plan_status("1. [completed] load_fit")
    assert seen["name"] == "update_plan_status"
    assert seen["arguments"]["last_work_tool"] == "load_fit"
    assert seen["arguments"]["last_work_status"] == "ok"
    assert seen["arguments"]["checklist"] == []
    assert out["checklist"][0]["status"] == "completed"
    assert checklist() == [{"text": "load_fit", "status": "completed"}]


def test_reflection_appends_vacancy_hint_not_deal_hints(monkeypatch):
    monkeypatch.setenv("CAPABILITIES_GATEWAY_URL", "http://127.0.0.1:8010")

    def fake(name, arguments, timeout=180.0):
        return {
            "ok": True,
            "rejected": False,
            "need_replan": True,
            "checklist": arguments.get("checklist") or [],
            "text": "Reflection stored: look again",
        }

    monkeypatch.setattr("vacancy_agent.gateway_client.call_tool", fake)
    reset()
    out = reflection("look again", need_replan=True)
    assert "look again" in out["text"]
    assert "parse_rent_roll_file" in out["hint"]
    assert "fit_vacancy" in out["hint"]
    assert "load_fit" in out["hint"]
    assert "save_fit" in out["hint"]
    assert "score_vacancy" in out["hint"]
    assert "score_gcr" not in out["text"]
    assert "do not force parse then fit then save" in out["text"].lower()
    assert "the numbered list is only the work tools this turn will call" in out["hint"].lower()
    assert "does not require a reply row" in out["hint"].lower()
    assert "including the final reply" not in out["text"].lower()
    assert out["checklist"] == []


def test_run_log_shows_update_plan_status_only_when_the_model_calls_it():
    queue = _Queue()
    token = bind(queue)
    begin_turn()
    try:
        called = ChatResponse(
            messages=[
                Message(
                    "assistant",
                    [
                        Content.from_text("Mark load_fit done."),
                        Content.from_function_call(
                            "call-1",
                            "update_plan_status",
                            arguments={"tasks": "1. [completed] load_fit"},
                        ),
                    ],
                )
            ],
            finish_reason="tool_calls",
        )
        note_model_step(called)
        quiet = ChatResponse(
            messages=[
                Message(
                    "assistant",
                    [
                        Content.from_function_call(
                            "call-2",
                            "load_fit",
                            arguments={"property_name": "Hill"},
                        )
                    ],
                )
            ],
            finish_reason="tool_calls",
        )
        note_model_step(quiet)
    finally:
        from vacancy_agent.runlog import reset as reset_log

        reset_log(token)
    react = [row["message"] for row in queue.items if row["step"] == "react"]
    assert any("update_plan_status" in line for line in react)
    assert any("load_fit" in line and "update_plan_status" not in line for line in react)


def test_llm_trace_does_not_invent_a_status_step():
    queue = _Queue()
    token = bind(queue)
    begin_turn()
    try:
        chat = type(
            "Chat",
            (),
            {
                "result": ChatResponse(
                    messages=[
                        Message(
                            "assistant",
                            [
                                Content.from_function_call(
                                    "call-1",
                                    "parse_rent_roll_file",
                                    arguments={"file_id": "abc"},
                                )
                            ],
                        )
                    ],
                    finish_reason="tool_calls",
                )
            },
        )()

        async def _next():
            return None

        asyncio.run(LlmTrace().process(chat, _next))
    finally:
        from vacancy_agent.runlog import reset as reset_log

        reset_log(token)
    blob = json.dumps(queue.items)
    assert "parse_rent_roll_file" in blob
    assert "update_plan_status" not in blob
