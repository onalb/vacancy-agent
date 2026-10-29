import pytest


@pytest.fixture(autouse=True)
def _isolate_gateway_env(monkeypatch):
    """Keep ambient shell env from leaking a live gateway into tests.

    Tests that exercise the MCP or the skills URL set MCP_URL or
    CAPABILITIES_GATEWAY_URL themselves.
    """
    monkeypatch.delenv("MCP_URL", raising=False)
    monkeypatch.delenv("CAPABILITIES_GATEWAY_URL", raising=False)
    monkeypatch.delenv("MCP_CALLER_ROLE_ARN", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AGENTCORE_GATEWAY_URL", raising=False)
