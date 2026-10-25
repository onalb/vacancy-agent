"""Vacancy agent. The model decides. Tools parse, fit, score, and store."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from agent_framework import Agent, ChatMiddleware, FileSkillsSource, FunctionMiddleware, SkillsProvider
from agent_framework.openai import OpenAIChatClient
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AsyncOpenAI

from vacancy_agent.runlog import emit, tool_line
from vacancy_agent.tools import TOOLS

log = logging.getLogger("vacancy")
ROOT = Path(__file__).resolve().parents[1]
_agent: Agent | None = None
_sessions: dict[str, object] = {}

INSTRUCTIONS = (
    "You are the vacancy prediction agent. "
    "Load the vacancy skill before you decide. "
    "You choose whether to ask which floor plan, refuse, fit, or score. "
    "When a question names a building, call load_fit for that name "
    "(or load_fit empty to list trained properties). "
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
    "If score_vacancy returns ambiguous_plan, ask among the listed plan_keys. "
    "On a follow-up that is only a plan name, still pass that same building. "
    "If the fit has only one plan and one renovated variant, you may score it. "
    "MCP ask_vacancy callers are questions-only: never ask them to parse or upload a rent roll. "
    "If there is no fit, say which properties are trained instead of asking for a file. "
    "The tools only parse a rent roll, fit the logistic regression, score that fit, "
    "and read or write the saved fit."
)


class LlmTrace(ChatMiddleware):
    async def process(self, context, call_next):
        emit("llm", "vacancy-chat")
        await call_next()
        emit("llm", "vacancy-chat returned")


class ToolTrace(FunctionMiddleware):
    async def process(self, context, call_next):
        name = getattr(getattr(context, "function", None), "name", "tool")
        emit("tool", f"{name} started")
        await call_next()
        result = context.result
        if isinstance(result, dict):
            for key in ("resident", "email", "phone", "ssn"):
                result.pop(key, None)
        log.info("tool %s", name)
        emit("tool", tool_line(name, context.arguments, result))


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
    skills = SkillsProvider(
        FileSkillsSource(ROOT / "skills"),
        disable_load_skill_approval=True,
        disable_read_skill_resource_approval=True,
    )
    return Agent(
        client=client,
        name="VacancyAgent",
        instructions=INSTRUCTIONS,
        tools=TOOLS,
        context_providers=[skills],
        middleware=[LlmTrace(), ToolTrace()],
    )
