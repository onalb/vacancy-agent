"""Vacancy agent. The model decides. Tools parse, fit, score, and store."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from agent_framework import Agent, FileSkillsSource, FunctionMiddleware, SkillsProvider
from agent_framework.foundry import FoundryChatClient
from azure.identity import DefaultAzureCredential

from vacancy_agent.tools import TOOLS

log = logging.getLogger("vacancy")
ROOT = Path(__file__).resolve().parents[1]

INSTRUCTIONS = (
    "You are the vacancy prediction agent. "
    "Load the vacancy skill before you decide. "
    "You choose whether to ask, refuse, fit, or score. "
    "The tools only parse a rent roll, fit the logistic regression, score that fit, "
    "and read or write the saved fit."
)


class ToolTrace(FunctionMiddleware):
    async def process(self, context, call_next):
        await call_next()
        result = context.result
        if isinstance(result, dict):
            for key in ("resident", "email", "phone", "ssn"):
                result.pop(key, None)
        name = getattr(getattr(context, "function", None), "name", "tool")
        log.info("tool %s", name)


def build_agent() -> Agent:
    endpoint = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    model = os.environ.get("FOUNDRY_MODEL", "vacancy-chat").strip() or "vacancy-chat"
    if not endpoint:
        raise RuntimeError("FOUNDRY_PROJECT_ENDPOINT is not set.")
    client = FoundryChatClient(
        project_endpoint=endpoint,
        model=model,
        credential=DefaultAzureCredential(),
    )
    skills = SkillsProvider(FileSkillsSource(ROOT / "skills"))
    return Agent(
        client=client,
        name="VacancyAgent",
        instructions=INSTRUCTIONS,
        tools=TOOLS,
        context_providers=[skills],
        middleware=[ToolTrace()],
    )
