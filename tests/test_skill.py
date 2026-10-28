from pathlib import Path

from vacancy_agent.agent import INSTRUCTIONS

SKILL = (
    Path(__file__).resolve().parents[2]
    / "capabilities-gateway"
    / "skills"
    / "vacancy"
    / "SKILL.md"
).read_text(encoding="utf-8")


def test_skill_allows_a_checklist_without_a_fixed_work_order():
    assert "create_plan" in SKILL
    assert "update_plan_status" in SKILL
    assert "update_plan" in SKILL
    assert "reflection" in SKILL
    assert "parse_rent_roll_file" in SKILL
    assert "Do not force parse then fit then save" in SKILL
    assert "score_gcr" not in SKILL


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


def test_delete_flow_is_in_the_skill_and_instructions_without_building_names():
    blob = (SKILL + "\n" + INSTRUCTIONS).lower()
    assert "delete_fit" in SKILL
    assert "delete_fit" in INSTRUCTIONS
    assert "call delete_fit without confirm" in SKILL.lower()
    assert "do not use it for a training upload or a score question" in SKILL.lower()
    assert "do not use that flow for a training upload or a score question" in INSTRUCTIONS.lower()
    for banned in ("la cordoba", "bay view", "chambers"):
        assert banned not in blob


def test_checklist_requires_create_plan_before_work():
    phrase = "create_plan, then load_fit, then update_plan_status, then the reply"
    for blob in (SKILL, INSTRUCTIONS):
        lowered = blob.lower()
        assert "you may call create_plan" not in lowered
        assert "the first action is create_plan" in lowered
        assert phrase in lowered
        assert "the numbered list is only the work tools this turn will call" in lowered
        assert "does not require a reply row" in lowered
        assert "including the final reply" not in lowered
        assert "do not add a line for create_plan, update_plan, update_plan_status, reflection, or a reply-only step" in lowered
        for banned in ("la cordoba", "bay view", "chambers"):
            assert banned not in lowered


def test_which_properties_question_calls_list_trained_properties():
    lowered = SKILL.lower()
    start = lowered.index("when the user asks which properties are trained")
    end = lowered.index("answer starts from a text question")
    paragraph = lowered[start:end]
    assert "list_trained_properties" in paragraph
    assert "the plan contains list_trained_properties" in paragraph
    assert "no properties are trained yet" in paragraph
    assert "do not use load_fit with an empty name for that question" in paragraph
    assert "load_fit remains for one named building" in paragraph
    assert "empty property_name" not in paragraph
    assert "list_trained_properties" in INSTRUCTIONS
    assert "the plan contains list_trained_properties" in INSTRUCTIONS.lower()
    for banned in ("la cordoba", "bay view", "chambers"):
        assert banned not in lowered
        assert banned not in INSTRUCTIONS.lower()


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
