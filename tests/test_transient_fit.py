"""ask_vacancy plan_table fits transiently on the session. Never saved, never listed."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from vacancy_agent.agent import answer_question
from vacancy_agent.fit import fit_vacancy as fit_model, plan_probability
from vacancy_agent.plan_state import bind_session, get_transient_fit, set_transient_fit
from vacancy_agent.store import DirectoryFitStore
from vacancy_agent.tools import configure, fit_plans, list_trained, load_saved, save_fit, score_saved

_TABLE = [
    {"plan": "A1", "renovated": 0, "units": 10, "vacant": 3},
    {"plan": "B2", "renovated": 0, "units": 8, "vacant": 1},
]


class _FakeAgent:
    """Stands in for the LLM loop: loads the catalog, scores one plan."""

    def __init__(self) -> None:
        self.questions: list[str] = []

    def create_session(self):
        return object()

    async def run(self, question, session=None):
        self.questions.append(question)
        catalog = load_saved("Fixture Towers")
        score = score_saved("Fixture Towers", "A1")
        return SimpleNamespace(text=json.dumps({"catalog": catalog, "score": score}))


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.delenv("CAPABILITIES_GATEWAY_URL", raising=False)
    monkeypatch.delenv("MCP_URL", raising=False)
    directory = DirectoryFitStore(tmp_path)
    directory.save({"property": "North Tower", "as_of": "2024-01-01", "groups": []})
    configure(directory, {})
    return directory


def test_plan_table_fits_transiently_and_answers_without_saving(store, monkeypatch):
    fake = _FakeAgent()
    monkeypatch.setattr("vacancy_agent.agent.get_agent", lambda: fake)
    text = asyncio.run(
        answer_question(
            "Which floor plan at Fixture Towers is more likely vacant?",
            "sess-transient",
            plan_table=_TABLE,
        )
    )
    body = json.loads(text)
    catalog = body["catalog"]
    assert catalog["property"] == "Fixture Towers"
    assert catalog["transient"] is True
    assert catalog["plan_keys"] == ["A1", "B2"]
    score = body["score"]
    assert score["plan"] == "A1"
    assert score["probability"] == plan_probability(fit_model(_TABLE), "A1", 0, 3)
    assert "%" in score["percent"]
    # The fit store is untouched and the transient fit is not listed.
    assert store.property_names() == ["North Tower"]
    assert list_trained() == {"properties": ["North Tower"], "text": "North Tower"}
    assert list(store.root.glob("*.json")) == [store.root / "north-tower.json"]


def test_transient_fit_does_not_leak_across_sessions(store, monkeypatch):
    fake = _FakeAgent()
    monkeypatch.setattr("vacancy_agent.agent.get_agent", lambda: fake)
    asyncio.run(answer_question("score A1", "sess-a", plan_table=_TABLE))
    bind_session("sess-b")
    assert get_transient_fit() is None
    assert load_saved("Fixture Towers").get("error") == "not_saved"
    bind_session("sess-a")
    assert get_transient_fit() is not None
    assert load_saved("Fixture Towers")["plan_keys"] == ["A1", "B2"]


def test_a_call_without_plan_table_clears_the_transient_fit(store, monkeypatch):
    fake = _FakeAgent()
    monkeypatch.setattr("vacancy_agent.agent.get_agent", lambda: fake)
    asyncio.run(answer_question("score A1", "sess-clear", plan_table=_TABLE))
    assert load_saved("Fixture Towers")["plan_keys"] == ["A1", "B2"]
    asyncio.run(answer_question("score A1", "sess-clear"))
    bind_session("sess-clear")
    assert get_transient_fit() is None
    # Trained-store behavior is exactly as before.
    assert load_saved("Fixture Towers").get("error") == "not_saved"
    assert load_saved("Fixture Towers")["buildings"] == [{"property": "North Tower", "as_of": "2024-01-01"}]


def test_save_fit_refuses_during_a_transient_session(store):
    bind_session("sess-guard")
    set_transient_fit(fit_plans(_TABLE))
    out = save_fit("Fixture Towers", "2024-01-31", fit_plans(_TABLE))
    assert out["ok"] is False
    assert out["error"] == "transient_fit"
    assert "never saved" in out["text"]
    assert store.property_names() == ["North Tower"]
    set_transient_fit(None)


def test_empty_plan_table_rows_are_ignored(store, monkeypatch):
    fake = _FakeAgent()
    monkeypatch.setattr("vacancy_agent.agent.get_agent", lambda: fake)
    asyncio.run(answer_question("score A1", "sess-junk", plan_table=["nope", _TABLE[0]]))
    bind_session("sess-junk")
    fit = get_transient_fit()
    assert fit["reference_plan"] == "A1"
    assert fit["groups"] == [{"plan": "A1", "renovated": 0, "units": 10, "vacant": 3}]
    set_transient_fit(None)