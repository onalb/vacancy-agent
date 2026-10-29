"""Vacancy tools use /mcp/vacancy only when the gateway URL is set."""

from __future__ import annotations

import inspect

import httpx
import pytest

from vacancy_agent.gateway_client import fetch_vacancy_skill, vacancy_mcp_url
from vacancy_agent.store import DirectoryFitStore
from vacancy_agent.tools import configure, load_saved, score_saved


def test_math_stays_local_when_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("MCP_URL", raising=False)

    def boom(*_args, **_kwargs):
        raise AssertionError("gateway must not be called")

    monkeypatch.setattr("vacancy_agent.gateway_client.call_tool", boom)
    configure(DirectoryFitStore(tmp_path), {})
    assert load_saved("") == {"buildings": []}
    assert vacancy_mcp_url() == ""
    with pytest.raises(RuntimeError, match="capabilities gateway is required"):
        fetch_vacancy_skill()


def test_skill_comes_from_gateway_when_set(monkeypatch):
    monkeypatch.setenv("CAPABILITIES_GATEWAY_URL", "http://127.0.0.1:8010")
    requested: list[str] = []

    class Response:
        text = "---\nname: vacancy\n---\nTrain starts when the user uploads a rent roll.\n"

        def raise_for_status(self) -> None:
            return None

    def fake_get(url, **_kwargs):
        requested.append(url)
        return Response()

    monkeypatch.setattr(httpx, "get", fake_get)
    text = fetch_vacancy_skill()
    assert requested == ["http://127.0.0.1:8010/skills/vacancy"]
    assert text.startswith("### skill:vacancy\n")
    assert "Train starts when the user uploads a rent roll." in text


def test_load_and_score_call_vacancy_mcp_when_set(monkeypatch):
    monkeypatch.setenv("MCP_URL", "https://example.test/mcp")
    calls: list[tuple[str, dict]] = []

    def fake(name, arguments, timeout=180.0):
        calls.append((name, arguments))
        if name == "load_fit":
            return {"buildings": [{"property": "Hill", "as_of": "2024-01-31"}]}
        return {"plan": "A1", "probability": 0.25}

    monkeypatch.setattr("vacancy_agent.gateway_client.call_tool", fake)
    listed = load_saved("")
    scored = score_saved("Hill", "A1", 0)
    assert listed["buildings"][0]["property"] == "Hill"
    assert scored["probability"] == 0.25
    assert calls[0][0] == "load_fit"
    assert calls[1][0] == "score_vacancy"
    assert calls[1][1]["building"] == "Hill"
    assert vacancy_mcp_url() == "https://example.test/mcp"


def test_ask_vacancy_server_does_not_call_the_gateway():
    from vacancy_agent import mcp_server

    source = inspect.getsource(mcp_server)
    assert "gateway_client" not in source
    assert "CAPABILITIES_GATEWAY" not in source
    assert "/mcp/deal" not in source
    assert "/mcp/vacancy" not in source
    assert "ask_vacancy" in source
