"""Vacancy agent. The model decides. Tools parse, fit, score, and store."""

from __future__ import annotations

import json
import logging
import os

from agent_framework import Agent, ChatMiddleware, FunctionMiddleware
from agent_framework.openai import OpenAIChatClient
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AsyncOpenAI

from vacancy_agent.runlog import note_model_step, note_tool_finish, note_tool_start
from vacancy_agent.tools import TOOLS

log = logging.getLogger("vacancy")
_agent: Agent | None = None
_sessions: dict[str, object] = {}

INSTRUCTIONS = (
    "You are the vacancy prediction agent. "
    "The vacancy skill is already in these instructions. Do not call load_skill. "
    "On a work turn the order is create_plan, then the work tool, then "
    "update_plan_status once, then the reply. "
    "Do not call update_plan_status before a work tool has returned. "
    "Do not call update_plan_status twice unless another work tool returned in between. "
    "You choose whether to ask which floor plan, refuse, fit, or score. "
    "When a question names a building, the first action is create_plan, then "
    "load_fit for that name, then update_plan_status, then the reply. "
    "If load_fit says the building is not saved, call list_trained_properties "
    "before that reply. "
    "When the user asks which properties are trained, the first action is "
    "create_plan. The plan contains list_trained_properties. Call that tool. "
    "Then update_plan_status. Then reply with those names, or say no properties "
    "are trained yet. Do not use load_fit with an empty name for that question. "
    "load_fit remains for one named building. "
    "load_fit returns plan_keys and plans (plan + renovated) with no rates; "
    "never copy p(vacant) from a fit JSON. "
    "Building-only vacancy, occupancy, or predicted vacancy (no exact floor plan "
    "in the question): ASK which floor plan. List exact plan_keys, and reno 0 vs 1 "
    "when both exist in plans. NEVER call score_vacancy in a loop for every plan. "
    "NEVER present a bullet list of rates unless the user named one unique plan "
    "(and renovated when both exist). "
    "Ask which group, and give no probability, when the user's label covers more "
    "than one saved group. Never pick the first matching key. "
    "If renovation (or any extra 0/1 attribute) is a separate feature on the "
    "same plan name, an underspecified plan name must ask which variant; an "
    "attribute with no plan must ask which plan has that attribute. "
    "If a suffix or token is part of the saved plan name (not a separate "
    "feature), a partial family name that matches several keys must ask which "
    "full saved key. "
    "If the user's string is not a saved plan name, ask which of the saved plans. "
    "If they already named one unique plan, score that plan only: call "
    "score_vacancy(building=<property from load_fit>, plan=<exact plan_keys value>). "
    "Write the percent from that tool, such as 73.6%. Do not write the probability decimal. "
    "If score_vacancy returns ambiguous_plan, ask among the listed plan_keys. "
    "On a follow-up that is only a plan name, still pass that same building. "
    "If the fit has only one plan and one renovated variant, you may score it. "
    "MCP ask_vacancy callers are questions-only: never ask them to parse or upload a rent roll. "
    "A clarifying question or not-trained list is the whole MCP answer. "
    "If there is no fit, say which properties are trained instead of asking for a file. "
    "If list_trained_properties is empty, say no properties are trained yet. "
    "Do not ask for a different building. The reply does not say a skill was loaded. "
    "Do not list every plan's p(vacant). "
    "The tools parse a rent roll, fit the logistic regression, score that fit, "
    "and read, write, or delete the saved fit. "
    "On every user turn that will call a work tool, or that answers about "
    "training, scoring, listing trained properties, or deletion, the first "
    "action is create_plan. The numbered list is only the work tools this "
    "turn will call. It does not require a reply row. Do not add a line for "
    "create_plan, update_plan, update_plan_status, reflection, or a reply-only "
    "step. Rows start pending. "
    "A question that only checks whether a building is trained still starts with "
    "create_plan, then load_fit, then update_plan_status, then the reply. "
    "A question that asks which properties are trained still starts with "
    "create_plan. The plan contains list_trained_properties. Call that tool. "
    "Then update_plan_status. Then reply with those names, or say no properties "
    "are trained yet. "
    "After each work tool returns, the next call is update_plan_status for "
    "that row before the next work tool or the final answer. Mark the row "
    "completed on success and incomplete on error. "
    "Call update_plan only when the list is wrong or a step is missing, not "
    "after every successful tool. Call reflection when you need to replan. "
    "Work tools are parse_rent_roll_file, fit_vacancy, load_fit, save_fit, "
    "score_vacancy, delete_fit, and list_trained_properties. Call whichever "
    "the question needs. "
    "Do not force parse then fit then save. "
    "When the user asks to remove a property from training, or to remove every "
    "trained property, call create_plan once with the steps that request needs. "
    "Resolve the target with load_fit: pass the named property, or an empty "
    "property_name when they asked to remove every trained property. "
    "If the named property is not trained, say so and do not delete. "
    "Call delete_fit without confirm, show the returned question, call "
    "update_plan_status, and stop. "
    "If the user does not agree, do not call delete_fit with confirm, and say "
    "nothing was removed. "
    "If the user agrees, call delete_fit with confirm=true, then "
    "update_plan_status, then tell them the JSON was deleted. "
    "Do not use that flow for a training upload or a score question."
)


class LlmTrace(ChatMiddleware):
    async def process(self, context, call_next):
        await call_next()
        note_model_step(getattr(context, "result", None))


def _result_text(result: object) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        parts = []
        for item in result:
            if isinstance(item, str):
                parts.append(item)
            else:
                parts.append(str(getattr(item, "text", "") or ""))
        return "".join(parts)
    return ""


def _result_failed(result: object) -> bool:
    if isinstance(result, dict):
        return result.get("ok") is False or bool(result.get("error"))
    raw = _result_text(result).strip()
    if not raw:
        return False
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, dict) and (parsed.get("ok") is False or bool(parsed.get("error")))


def _status_sentence(result: object) -> str:
    if _result_failed(result):
        return "Call update_plan_status for this row and mark it incomplete."
    return "Call update_plan_status for this row and mark it completed."


def _merge_sentence(prior: str, sentence: str) -> str:
    cleaned = (prior or "").strip()
    if not cleaned:
        return sentence
    if sentence in cleaned:
        return cleaned
    return f"{cleaned} {sentence}"


def _stamp_mapping(body: dict, sentence: str) -> dict:
    stamped = dict(body)
    stamped["text"] = _merge_sentence(str(stamped.get("text") or ""), sentence)
    return stamped


def _stamp_json_text(text: str, sentence: str) -> str:
    stripped = text.strip()
    if not stripped:
        return sentence
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return _merge_sentence(stripped, sentence)
    if isinstance(parsed, dict):
        return json.dumps(_stamp_mapping(parsed, sentence))
    return _merge_sentence(stripped, sentence)


def _with_status_sentence(result: object) -> object:
    """Append one sentence so the next model call is update_plan_status."""
    sentence = _status_sentence(result)
    if isinstance(result, dict):
        return _stamp_mapping(result, sentence)
    if isinstance(result, str):
        return _stamp_json_text(result, sentence)
    if isinstance(result, list):
        for item in result:
            if hasattr(item, "text"):
                item.text = _stamp_json_text(str(getattr(item, "text", "") or ""), sentence)
                return result
        return result
    if hasattr(result, "text"):
        result.text = _stamp_json_text(str(getattr(result, "text", "") or ""), sentence)
    return result


class ToolTrace(FunctionMiddleware):
    async def process(self, context, call_next):
        from vacancy_agent.plan_state import WORK_TOOLS, checklist

        name = getattr(getattr(context, "function", None), "name", "tool")
        arguments = getattr(context, "arguments", None)
        held = checklist()
        if name in WORK_TOOLS and not held:
            context.result = {
                "ok": False,
                "error": "no_checklist",
                "text": "Call create_plan first.",
            }
            item_id = note_tool_start(name, arguments)
            note_tool_finish(item_id, name, arguments, context.result)
            return
        item_id = note_tool_start(name, arguments)
        try:
            await call_next()
        except Exception:
            note_tool_finish(item_id, name, arguments, {"error": "tool_failed"})
            raise
        log.info("tool %s", name)
        if name in WORK_TOOLS:
            context.result = _with_status_sentence(context.result)
        note_tool_finish(item_id, name, arguments, context.result)


def _openai_base(project_endpoint: str) -> str:
    """Account data plane for vacancy-chat.

    FoundryChatClient posts to the project path with an ai.azure.com token.
    That path returns 403. The account path /openai/v1/responses returns 200
    with a cognitiveservices token and no api-version query.
    """
    override = os.environ.get("FOUNDRY_OPENAI_BASE_URL", "").strip()
    if override:
        return override if override.endswith("/") else override + "/"
    host = project_endpoint.split("/api/projects/")[0].rstrip("/")
    return f"{host}/openai/v1/"


def get_agent() -> Agent:
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent


async def answer_question(question: str, session_id: str = "") -> str:
    """Run one answer turn. Reuse session_id to continue after a follow-up question."""
    from vacancy_agent.plan_state import bind_session, reset as reset_plan

    bind_session(session_id)
    reset_plan()
    from vacancy_agent.gateway_client import vacancy_mcp_url
    from vacancy_agent.mcp_call import list_tools, reset_menu

    if vacancy_mcp_url():
        reset_menu()
        list_tools()
    vacancy = get_agent()
    key = session_id.strip()
    session = _sessions.get(key) if key else None
    if session is None:
        session = vacancy.create_session()
        if key:
            _sessions[key] = session
    result = await vacancy.run(question.strip(), session=session)
    return getattr(result, "text", None) or str(result)


_COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"


def _azure_credential_works() -> bool:
    try:
        DefaultAzureCredential(exclude_interactive_browser_credential=True).get_token(_COGNITIVE_SCOPE)
        return True
    except Exception:
        log.warning("Azure credential unavailable; falling back to OPENAI_API_KEY if set")
        return False


def _foundry_client(endpoint: str, model: str) -> OpenAIChatClient:
    token = get_bearer_token_provider(DefaultAzureCredential(), _COGNITIVE_SCOPE)

    async def api_key() -> str:
        return token()

    raw = AsyncOpenAI(base_url=_openai_base(endpoint), api_key=api_key)
    return OpenAIChatClient(model=model, async_client=raw)


def _openai_fallback_client() -> OpenAIChatClient:
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    return OpenAIChatClient(model=model, async_client=AsyncOpenAI())


def _skill_body() -> str:
    """Vacancy skill from GET /skills/vacancy. It is already in the prompt, so the model does not call load_skill."""
    from vacancy_agent.gateway_client import fetch_vacancy_skill

    return fetch_vacancy_skill()


def build_agent() -> Agent:
    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    model = os.environ.get("FOUNDRY_MODEL", "vacancy-chat").strip() or "vacancy-chat"
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if endpoint and _azure_credential_works():
        client = _foundry_client(endpoint, model)
    elif openai_key:
        client = _openai_fallback_client()
    elif not endpoint:
        raise RuntimeError("FOUNDRY_PROJECT_ENDPOINT is not set.")
    else:
        raise RuntimeError("Azure credential failed and OPENAI_API_KEY is not set.")
    return Agent(
        client=client,
        name="VacancyAgent",
        instructions=f"{INSTRUCTIONS}\n\n{_skill_body()}",
        tools=TOOLS,
        middleware=[LlmTrace(), ToolTrace()],
    )
