"""delete_fit asks on the vacancy session, then removes one temp JSON or all of them."""

from __future__ import annotations

import pytest

from vacancy_agent.plan_state import bind_session, clear_pending_delete, get_pending_delete
from vacancy_agent.store import DirectoryFitStore
from vacancy_agent.tools import QUESTION_ALL, configure, delete_saved, question_for


def _record(name: str) -> dict:
    return {"property": name, "as_of": "2024-01-01", "groups": []}


@pytest.fixture
def fits(tmp_path, monkeypatch):
    monkeypatch.delenv("CAPABILITIES_GATEWAY_URL", raising=False)
    monkeypatch.delenv("AZURE_STORAGE_ACCOUNT", raising=False)
    store = DirectoryFitStore(tmp_path)
    configure(store)
    bind_session("delete-fit-test")
    clear_pending_delete()
    yield store
    clear_pending_delete()


def test_first_call_does_not_delete(fits, tmp_path):
    fits.save(_record("North Tower"))
    fits.save(_record("South Annex"))
    body = delete_saved("north tower")
    assert body["deleted"] is False
    assert body["pending"] is True
    assert body["question"] == question_for("North Tower")
    assert body["property"] == "North Tower"
    assert (tmp_path / "north-tower.json").is_file()
    assert (tmp_path / "south-annex.json").is_file()


def test_confirm_after_pending_deletes_that_json_only(fits, tmp_path):
    fits.save(_record("North Tower"))
    fits.save(_record("South Annex"))
    delete_saved("North Tower")
    body = delete_saved("north-tower", confirm=True)
    assert body["deleted"] is True
    assert body["property"] == "North Tower"
    assert "The JSON file was deleted." in body["text"]
    assert not (tmp_path / "north-tower.json").is_file()
    assert (tmp_path / "south-annex.json").is_file()
    assert get_pending_delete() is None


def test_confirm_without_pending_deletes_nothing(fits, tmp_path):
    fits.save(_record("North Tower"))
    body = delete_saved("North Tower", confirm=True)
    assert body["deleted"] is False
    assert body["error"] == "not_confirmed"
    assert body["text"] == "Nothing was removed."
    assert (tmp_path / "north-tower.json").is_file()
    assert get_pending_delete() is None
    again = delete_saved("North Tower", confirm=True)
    assert again["deleted"] is False
    assert (tmp_path / "north-tower.json").is_file()


def test_all_properties_asks_then_deletes_every_json(fits, tmp_path):
    fits.save(_record("North Tower"))
    fits.save(_record("South Annex"))
    first = delete_saved(all_properties=True)
    assert first["deleted"] is False
    assert first["question"] == QUESTION_ALL
    assert first["question"] == "Are you sure? This removes every trained property."
    assert (tmp_path / "north-tower.json").is_file()
    assert (tmp_path / "south-annex.json").is_file()
    second = delete_saved(all_properties=True, confirm=True)
    assert second["deleted"] is True
    assert second["count"] == 2
    assert "2 JSON files were deleted." in second["text"]
    assert list(tmp_path.glob("*.json")) == []


def test_unknown_name_does_not_create_a_pending_delete(fits, tmp_path):
    fits.save(_record("North Tower"))
    body = delete_saved("No Such Place")
    assert body["deleted"] is False
    assert body["pending"] is False
    assert body["error"] == "not_trained"
    assert "question" not in body
    assert "is not trained" in body["text"]
    assert get_pending_delete() is None
    assert (tmp_path / "north-tower.json").is_file()


def test_different_property_replaces_the_pending_question(fits, tmp_path):
    fits.save(_record("North Tower"))
    fits.save(_record("South Annex"))
    delete_saved("North Tower")
    swapped = delete_saved("South Annex", confirm=True)
    assert swapped["deleted"] is False
    assert swapped["question"] == question_for("South Annex")
    assert (tmp_path / "north-tower.json").is_file()
    assert (tmp_path / "south-annex.json").is_file()
    done = delete_saved("South Annex", confirm=True)
    assert done["deleted"] is True
    assert not (tmp_path / "south-annex.json").is_file()
    assert (tmp_path / "north-tower.json").is_file()


def test_wrapper_calls_gateway_only_after_the_pending_check(monkeypatch):
    monkeypatch.setenv("CAPABILITIES_GATEWAY_URL", "http://127.0.0.1:8010")
    calls: list[tuple[str, dict]] = []

    def fake(name, arguments, timeout=180.0):
        calls.append((name, dict(arguments)))
        if name == "load_fit" and arguments.get("property_name"):
            return {
                "property": "North Tower",
                "as_of": "2024-01-01",
                "plan_keys": [],
                "plans": [],
            }
        if name == "load_fit":
            return {"buildings": [{"property": "North Tower", "as_of": "2024-01-01"}]}
        if name == "delete_fit":
            return {
                "deleted": True,
                "property": "North Tower",
                "text": "Removed North Tower from the trained model. The JSON file was deleted.",
            }
        return {}

    monkeypatch.setattr("vacancy_agent.gateway_client.call_tool", fake)
    bind_session("gateway-gate")
    clear_pending_delete()
    try:
        first = delete_saved("North Tower")
        assert first["question"] == question_for("North Tower")
        assert [name for name, _args in calls if name == "delete_fit"] == []
        second = delete_saved("north tower", confirm=True)
        assert second["deleted"] is True
        deletes = [args for name, args in calls if name == "delete_fit"]
        assert deletes == [
            {
                "confirm": True,
                "all_properties": False,
                "property_name": "North Tower",
            }
        ]
    finally:
        clear_pending_delete()
