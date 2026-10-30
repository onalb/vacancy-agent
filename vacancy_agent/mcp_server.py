"""Answer-only MCP server. Other agents call ask_vacancy. Training stays on the web page."""

from __future__ import annotations

import logging

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from vacancy_agent.agent import answer_question

log = logging.getLogger("vacancy")

mcp = MCPServer(
    "vacancy",
    instructions=(
        "Current vacancy for one saved building. "
        "Call ask_vacancy with the building name; include a floor plan when known. "
        "If several plans are trained and none was named, the agent asks which floor plan. "
        "The tool returns that sentence. Reuse session_id on a follow-up. "
        "This server does not train and does not accept a rent roll. An optional "
        "plan_table (aggregated per-plan group counts) is fit transiently on "
        "that session and is never saved."
    ),
)


@mcp.tool()
async def ask_vacancy(question: str, session_id: str = "", plan_table: list = []) -> str:
    """Ask about current vacancy for one building and floor plan.

    question names the building. Include a floor plan when the caller knows one. The vacancy agent load_fits that building, asks which floor plan when several are trained and none was named, or scores one plan. Pass the same session_id on the next call when the sentence asks a follow-up. This tool does not accept a rent roll and does not train: never tell the caller to parse or upload a file. plan_table is optional — aggregated per-plan group counts ({plan, renovated, units, vacant}) of the caller's roll, fit transiently on this session and never saved; when it is present the agent answers this session's probability questions from that transient fit.
    """
    if not question.strip():
        return "Name the building and the floor plan."
    try:
        return await answer_question(question, session_id, plan_table)
    except Exception:
        log.exception("ask_vacancy failed")
        return "The vacancy agent could not answer."


def http_app():
    """Streamable HTTP app mounted at /mcp. Any caller Host is accepted."""
    return mcp.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        host="0.0.0.0",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
