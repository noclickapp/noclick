"""Focused regressions for production-facing Python security findings."""

import hashlib
import json
from types import SimpleNamespace
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_wordpress_dot_com_detection_uses_hostname_boundaries():
    from nodes.wordpress_node import (
        WordPressApplicationPasswordCredential,
        WordPressNode,
    )

    node = object.__new__(WordPressNode)

    def credential(site_url: str) -> WordPressApplicationPasswordCredential:
        return WordPressApplicationPasswordCredential(
            site_url=site_url,
            username="operator",
            application_password="test-only-password",
        )

    with pytest.raises(ValueError, match="require OAuth"):
        node._get_api_base_url(credential("https://blog.wordpress.com"))
    with pytest.raises(ValueError, match="require OAuth"):
        node._get_api_base_url(credential("https://WORDPRESS.COM./site"))

    for external_url in (
        "https://wordpress.com.attacker.example",
        "https://notwordpress.com",
        "https://self-hosted.example/.wordpress.com/path",
    ):
        assert node._get_api_base_url(credential(external_url)) == (
            f"{external_url}/wp-json/wp/v2"
        )


def test_usage_cache_key_uses_sha256_and_is_stable():
    from wss.handlers.usage_dashboard_handler import UsageDashboardHandler

    handler = object.__new__(UsageDashboardHandler)
    request = SimpleNamespace(
        organization_id=None,
        start_date="2026-08-01",
        end_date="2026-08-22",
        usage_type="ai",
        usage_subtype="agent",
        group_by="day",
    )

    first = handler._generate_cache_key("user-1", request)
    second = handler._generate_cache_key("user-1", request)
    other = handler._generate_cache_key("user-2", request)

    assert first == second
    assert first != other
    assert len(first) == hashlib.sha256().digest_size * 2


def test_database_health_does_not_reflect_exception_details(monkeypatch):
    import utils.database_pool as database_pool
    from utils.health_routes import router

    class FailingPool:
        async def fetchval(self, _query):
            raise RuntimeError("postgres://operator:secret-password@db.example")

    monkeypatch.setattr(database_pool, "get_native_pool", lambda: FailingPool())
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get("/health/db")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unhealthy",
        "error": "Database unavailable",
    }
    assert "secret-password" not in response.text


def test_local_harness_does_not_reflect_tool_exception_details(monkeypatch):
    import nodes.agent.local_harness as local_harness
    import nodes.agent.tool_execution as tool_execution
    import utils.tool_call_log as tool_call_log

    async def fail_tool(*_args, **_kwargs):
        raise RuntimeError("provider request contained password=secret-password")

    audits = []
    monkeypatch.setattr(tool_execution, "execute_tool", fail_tool)
    monkeypatch.setattr(
        tool_call_log, "record_tool_call", lambda **values: audits.append(values)
    )
    monkeypatch.setattr(local_harness, "_spawn_step", lambda *_args: None)

    token = local_harness._register_session(
        local_harness._ToolSession(
            node=SimpleNamespace(workflow_id="workflow-1"),
            tool_configs={"provider__operation": {"tool_type": "node_op"}},
            user_id="user-1",
            conversation_id="conversation-1",
        )
    )
    app = FastAPI()
    app.include_router(local_harness.router)
    try:
        response = TestClient(app).post(
            f"/local-agent-mcp/{token}",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "provider__operation", "arguments": {}},
            },
        )
    finally:
        local_harness._sessions.pop(token, None)

    payload = response.json()["result"]
    returned = json.loads(payload["content"][0]["text"])
    assert returned == {"success": False, "error": "Tool execution failed"}
    assert payload["isError"] is True
    assert audits[0]["error"] == "Tool execution failed"
    assert "secret-password" not in response.text
