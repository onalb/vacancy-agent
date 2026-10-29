"""list_trained_properties reads saved property names and does not invent one."""

from __future__ import annotations

import asyncio
import json

from vacancy_agent.agent import ToolTrace
from vacancy_agent.gateway_client import vacancy_mcp_url
from vacancy_agent.plan_state import WORK_TOOLS, reset as reset_plan
from vacancy_agent.runlog import PlanItem, _visible_plan, begin_turn, bind, reset
from vacancy_agent.store import BlobFitStore, DirectoryFitStore
from vacancy_agent.tools import configure, list_trained


def _local(monkeypatch, store: DirectoryFitStore) -> None:
    monkeypatch.delenv("CAPABILITIES_GATEWAY_URL", raising=False)

    def boom(*_args, **_kwargs):
        raise AssertionError("gateway must not be called")

    monkeypatch.setattr("vacancy_agent.gateway_client.call_tool", boom)
    configure(store, {})


def _record(name: str) -> dict:
    return {"property": name, "as_of": "2024-01-01", "groups": []}


def test_two_saved_fits_return_both_property_names(tmp_path, monkeypatch):
    store = DirectoryFitStore(tmp_path)
    store.save(_record("North Tower"))
    store.save(_record("South Annex"))
    _local(monkeypatch, store)
    result = list_trained()
    assert result["properties"] == ["North Tower", "South Annex"]
    assert result["text"] == "North Tower, South Annex"
    assert "north-tower" not in result["properties"]
    assert "south-annex" not in result["properties"]
    assert "probability" not in result
    assert "deleted" not in result
    assert (tmp_path / "north-tower.json").is_file()
    assert (tmp_path / "south-annex.json").is_file()


def test_empty_directory_says_none_are_trained(tmp_path, monkeypatch):
    store = DirectoryFitStore(tmp_path)
    _local(monkeypatch, store)
    result = list_trained()
    assert result == {"properties": [], "text": "No properties are trained yet."}
    blob = json.dumps(result).lower()
    assert "north tower" not in blob
    assert "south annex" not in blob
    assert list(tmp_path.glob("*.json")) == []


def test_property_field_wins_and_slug_is_the_fallback(tmp_path, monkeypatch):
    (tmp_path / "other-slug.json").write_text(
        json.dumps({"property": "North Tower", "as_of": "2024-01-01"}),
        encoding="utf-8",
    )
    (tmp_path / "west-court.json").write_text(
        json.dumps({"as_of": "2024-01-01"}),
        encoding="utf-8",
    )
    _local(monkeypatch, DirectoryFitStore(tmp_path))
    result = list_trained()
    assert result["properties"] == ["North Tower", "west-court"]
    assert "other-slug" not in result["properties"]


class _Blob:
    def __init__(self, container: "_Container", name: str) -> None:
        self.container = container
        self.name = name

    def exists(self) -> bool:
        return self.name in self.container.blobs

    def download_blob(self):
        data = self.container.blobs[self.name]

        class _Download:
            def readall(_self):
                return data

        return _Download()


class _Container:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    def get_blob_client(self, name: str) -> _Blob:
        return _Blob(self, name)

    def upload_blob(self, name: str, data, overwrite: bool = False) -> None:
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.blobs[name] = data

    def list_blobs(self):
        return [type("Item", (), {"name": name})() for name in list(self.blobs)]


def test_azure_store_returns_property_names_not_slugs():
    store = BlobFitStore.__new__(BlobFitStore)
    store.container = _Container()
    store.save(_record("North Tower"))
    store.container.blobs["west-court.json"] = b'{"as_of": "2024-01-01"}'
    assert store.property_names() == ["North Tower", "west-court"]
    assert "north-tower" not in store.property_names()


def test_list_trained_calls_the_gateway_when_the_url_is_set(monkeypatch):
    monkeypatch.setenv("CAPABILITIES_GATEWAY_URL", "http://127.0.0.1:8010")
    calls: list[tuple[str, dict]] = []

    def fake(name, arguments, timeout=180.0):
        calls.append((name, dict(arguments)))
        return {"properties": ["North Tower"], "text": "North Tower"}

    monkeypatch.setattr("vacancy_agent.gateway_client.call_tool", fake)
    assert list_trained() == {"properties": ["North Tower"], "text": "North Tower"}
    assert calls == [("list_trained_properties", {})]
    assert vacancy_mcp_url() == "http://127.0.0.1:8010"


def test_run_log_keeps_list_trained_properties_on_the_plan():
    assert "list_trained_properties" in WORK_TOOLS
    visible = _visible_plan(
        [
            PlanItem(tool="list_trained_properties", status="pending"),
            PlanItem(tool="reply with the names", status="pending"),
        ]
    )
    assert [item.tool for item in visible] == ["list_trained_properties"]


def test_list_trained_properties_before_the_plan_does_not_run():
    async def run():
        queue = type("Queue", (), {"items": [], "put_nowait": lambda self, item: self.items.append(item)})()
        token = bind(queue)
        begin_turn()
        called = 0
        try:
            tool = type(
                "Tool",
                (),
                {
                    "function": type("Fn", (), {"name": "list_trained_properties"})(),
                    "arguments": {},
                    "result": None,
                },
            )()

            async def tool_next():
                nonlocal called
                called += 1
                tool.result = {"properties": ["North Tower"], "text": "North Tower"}

            await ToolTrace().process(tool, tool_next)
            return called, tool.result
        finally:
            reset(token)
            reset_plan()

    called, result = asyncio.run(run())
    assert called == 0
    assert result["error"] == "no_checklist"
    assert result["text"] == "Call create_plan first."
    assert "North Tower" not in json.dumps(result)
