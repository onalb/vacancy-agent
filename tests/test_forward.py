"""The vacancy forwarder hides session fields and fills a checklist argument."""

from vacancy_agent.forward import stamp_arguments, tool_function, vacancy_call
from vacancy_agent.plan_state import bind_session, checklist, reset


def _plan() -> dict:
    return {
        "name": "create_plan",
        "description": "Store this turn's checklist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tasks": {"type": "string"},
                "checklist": {"type": "array"},
                "route": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
        },
    }


def test_stamp_hides_confirm_and_sets_route():
    stamped = stamp_arguments(_plan(), {"tasks": "1. load_fit", "confirm": True}, route="vacancy")
    assert stamped["route"] == "vacancy"
    assert stamped["tasks"] == "1. load_fit"
    assert "confirm" not in stamped
    assert stamped["checklist"] == []


def test_visible_signature_omits_checklist():
    fn = tool_function(_plan(), lambda name, args: {})
    assert list(fn.__signature__.parameters) == ["tasks"]


def test_vacancy_call_stores_returned_checklist(monkeypatch):
    bind_session("sess-1")
    reset()

    def fake(name, arguments, timeout=180.0):
        assert arguments["route"] == "vacancy"
        assert arguments["checklist"] == []
        return {
            "ok": True,
            "text": "Plan stored.",
            "checklist": [{"text": "load_fit", "status": "pending"}],
        }

    monkeypatch.setattr("vacancy_agent.gateway_client.call_tool", fake)
    body = vacancy_call("create_plan", {"tasks": "1. load_fit"}, [_plan()])
    assert body["text"] == "Plan stored."
    assert checklist() == [{"text": "load_fit", "status": "pending"}]
