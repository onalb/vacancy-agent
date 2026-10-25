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
        "Call ask_vacancy with the building and floor plan. "
        "The tool returns the vacancy agent's sentence. "
        "Reuse session_id when that sentence asks a follow-up. "
        "This server does not train."
    ),
)


@mcp.tool()
async def ask_vacancy(question: str, session_id: str = "") -> str:
    """Ask about current vacancy for one building and floor plan.

    question names the building and the plan. The vacancy agent decides whether to ask which group, refuse, or score. The return value is that sentence. Pass the same session_id on the next call when the sentence asks a follow-up. This tool does not accept a rent roll and does not train.
    """
    if not question.strip():
        return "Name the building and the floor plan."
    try:
        return await answer_question(question, session_id)
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
