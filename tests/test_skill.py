from pathlib import Path

from vacancy_agent.agent import INSTRUCTIONS

SKILL = (Path(__file__).resolve().parents[1] / "skills" / "vacancy" / "SKILL.md").read_text(
    encoding="utf-8"
)


def test_skill_named_building_loads_fit_not_parse():
    assert "If the question names a property, call load_fit" in SKILL
    assert "Do not call parse_rent_roll_file for a named-building question" in SKILL
    assert "NEVER ask an MCP / ask_vacancy caller to parse" in SKILL
    assert "listing which properties are trained" in SKILL
    assert "Do not ask for a file" in SKILL


def test_skill_asks_which_floor_plan_when_many():
    assert "Building-only" in SKILL
    assert "ASK which floor plan they want" in SKILL
    assert "NEVER call score_vacancy in a loop" in SKILL
    assert "NEVER present a bullet list of rates" in SKILL
    assert "score that plan only" in SKILL
    assert "only one plan_key and only one renovated variant, you may score that plan" in SKILL
    assert "On MCP this clarifying question is the whole answer" in SKILL
    assert "score_vacancy(building=" in SKILL
    assert "still call score_vacancy with the same building" in SKILL
    assert "Do not score with an empty building" in SKILL
    assert "Never pick the first matching key" in SKILL
    assert "ambiguous_plan" in SKILL
    assert "does not include p(vacant)" in SKILL


def test_agent_instructions_ask_which_plan_not_parse():
    assert "ask which floor plan" in INSTRUCTIONS
    assert "NEVER call score_vacancy in a loop" in INSTRUCTIONS
    assert "NEVER present a bullet list of rates" in INSTRUCTIONS
    assert "do not list every plan's p(vacant)" in INSTRUCTIONS.lower()
    assert "never ask them to parse or upload a rent roll" in INSTRUCTIONS
    assert "say which properties are trained" in INSTRUCTIONS
    assert "score that plan only" in INSTRUCTIONS
    assert "score_vacancy(building=" in INSTRUCTIONS
    assert "still pass that same building" in INSTRUCTIONS
    assert "Never pick the first matching key" in INSTRUCTIONS
    assert "ambiguous_plan" in INSTRUCTIONS
    assert "reno 0 vs 1" in INSTRUCTIONS
