"""Vacancy app client for POST {CAPABILITIES_GATEWAY_URL}/mcp/vacancy.

ask_vacancy stays on this app. This module never calls /mcp/deal.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

_MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-03-26",
}


def gateway_base() -> str:
    return os.environ.get("CAPABILITIES_GATEWAY_URL", "").strip().rstrip("/")


def vacancy_mcp_url() -> str:
    base = gateway_base()
    return f"{base}/mcp/vacancy" if base else ""


def _rpc_payload(data: dict) -> dict:
    if data.get("error"):
        err = data["error"]
        if isinstance(err, dict):
            raise RuntimeError(err.get("message") or json.dumps(err))
        raise RuntimeError(str(err))
    result = data.get("result")
    return result if isinstance(result, dict) else {}


def _parse_body(response: httpx.Response) -> dict:
    if response.status_code in {301, 302, 303, 307, 308}:
        raise RuntimeError(f"MCP URL redirected ({response.status_code}); refusing to follow")
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("MCP server returned a non-object response")
    return _rpc_payload(data)


def _content_text(result: dict) -> str:
    content = result.get("content")
    if isinstance(content, list) and content:
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
            elif isinstance(item, str):
                parts.append(item)
        if parts:
            return "\n".join(parts)
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return json.dumps(structured)
    if isinstance(structured, str):
        return structured
    return ""


def _post(client: httpx.Client, url: str, headers: dict[str, str], method: str, params: dict | None, req_id):
    body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if req_id is not None:
        body["id"] = req_id
    if params is not None:
        body["params"] = params
    response = client.post(url, json=body, headers=headers, follow_redirects=False)
    session = response.headers.get("mcp-session-id") or response.headers.get("Mcp-Session-Id")
    if session:
        headers = {**headers, "Mcp-Session-Id": session}
    if req_id is None:
        if response.status_code >= 400 or response.status_code in {301, 302, 303, 307, 308}:
            _parse_body(response)
        return {}, headers
    return _parse_body(response), headers


def call_tool(name: str, arguments: dict[str, Any], timeout: float = 180.0) -> Any:
    """Call one vacancy-math tool. Returns a dict (or {"text": ...})."""
    url = vacancy_mcp_url()
    if not url:
        raise RuntimeError("CAPABILITIES_GATEWAY_URL is not set")
    if "/mcp/deal" in url:
        raise RuntimeError("vacancy math must not call /mcp/deal")
    headers = dict(_MCP_HEADERS)
    clean = {key: value for key, value in arguments.items() if value is not None}
    with httpx.Client(timeout=timeout) as client:
        _, headers = _post(
            client,
            url,
            headers,
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "vacancy-agent", "version": "0.1.0"},
            },
            1,
        )
        _post(client, url, headers, "notifications/initialized", None, None)
        result, _ = _post(
            client,
            url,
            headers,
            "tools/call",
            {"name": name, "arguments": clean},
            2,
        )
    if result.get("isError"):
        return {"error": _content_text(result) or "gateway tool error"}
    text = _content_text(result)
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}
    return parsed if isinstance(parsed, dict) else {"result": parsed}


def fetch_vacancy_skill() -> str:
    """Skill markdown from GET {gateway}/skills/vacancy. No local file."""
    base = gateway_base()
    if not base:
        raise RuntimeError("capabilities gateway is required (set CAPABILITIES_GATEWAY_URL)")
    response = httpx.get(f"{base}/skills/vacancy", timeout=15.0, follow_redirects=False)
    response.raise_for_status()
    text = response.text.strip()
    if not text:
        raise RuntimeError("capabilities gateway returned an empty vacancy skill")
    return f"### skill:vacancy\n{text}"
