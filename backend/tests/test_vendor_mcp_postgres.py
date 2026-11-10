"""An integration connected through its vendor's MCP server, against real Postgres and a
local MCP server that implements the auth spec (tests/fixtures/fake_mcp_auth_server.py),
declared as Canva's: the client registration kept once for everyone, the in-app connect
(mcp:connect:start|finish) storing a proven credential, connection evidence from
``tools/list``, a refresh through the one choke point that persists the rotation, an
agent's tool call audited like a node_op's, and a provide link connecting through MCP."""

import uuid
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from nodes.canva_node import CanvaMcpCredential
from nodes.core import vendor_mcp
from tests.fixtures.fake_mcp_auth_server import ACCOUNT, FakeMcpAuthServer, serve
from tests.fixtures.real_db_fixture import real_database  # noqa: F401

pytestmark = pytest.mark.asyncio

CALLBACK = "http://localhost:5173/api/auth/mcp/callback"


@pytest.fixture
async def vendor(monkeypatch, real_database):  # noqa: F811
    monkeypatch.setenv("OUTBOUND_ALLOW_PRIVATE_IPS", "true")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:5173")
    async with serve(FakeMcpAuthServer()) as fake:
        monkeypatch.setattr(CanvaMcpCredential, "mcp_server", vendor_mcp.McpServer(url=fake.mcp_url, app="Canva"))
        yield fake


@pytest.fixture
async def pool(real_database):  # noqa: F811
    from utils.database_pool import get_native_pool

    return get_native_pool()


async def _user(pool, email=None) -> str:
    return str(await pool.fetchval(
        "INSERT INTO auth.users (email, raw_user_meta_data) VALUES ($1, '{}'::jsonb) RETURNING id",
        email or f"{uuid.uuid4().hex[:10]}@example.com",
    ))


async def _sign_in(authorization_url: str) -> dict:
    async with httpx.AsyncClient() as client:
        answer = await client.get(authorization_url)
    assert answer.status_code == 302, answer.text
    return {k: v[0] for k, v in parse_qs(urlsplit(answer.headers["location"]).query).items()}


class _Socket:
    """The handler's socket: one signed-in person, and every answer it sent."""

    def __init__(self, user_id):
        self.user_id, self.sent = user_id, []

    async def get_session(self, sid):
        return {"user_id": self.user_id, "user_data": {"subscription_tier": "free"}}


async def _in_app(handler, request_cls, **fields):
    from wss.handlers.oauth import mcp_oauth_handler

    sent = []

    async def capture(sio, sid, event, **_):
        sent.append(event)

    original = mcp_oauth_handler.send_event
    mcp_oauth_handler.send_event = capture
    try:
        await getattr(handler, {"McpConnectStartRequest": "connect_start", "McpConnectFinishRequest": "connect_finish"}[
            request_cls.__name__])("sid", request_cls(request_id="r", **fields))
    finally:
        mcp_oauth_handler.send_event = original
    return sent[0].data | ({"error": sent[0].error} if sent[0].error else {})


async def _connect_in_app(pool, user_id):
    from wss.handlers.oauth.mcp_oauth_handler import MCPOAuthHandler
    from wss.receiver.client_events import McpConnectFinishRequest, McpConnectStartRequest

    handler = MCPOAuthHandler(_Socket(user_id))
    started = await _in_app(handler, McpConnectStartRequest, credential_type="canva_mcp", redirect_uri=CALLBACK)
    assert started["success"] and started["kind"] == "oauth", started
    back = await _sign_in(started["authorization_url"])
    return await _in_app(handler, McpConnectFinishRequest, flow=started["flow"], code=back["code"], state=back["state"])


async def test_the_client_store_keeps_the_first_registration(pool):
    from repositories.mcp_clients import McpClientRepo

    repo = McpClientRepo(pool)
    issuer = f"https://as-{uuid.uuid4().hex[:6]}.example"
    first = await repo.keep(issuer, CALLBACK, "client-a", None, {"client_name": "NoClick"})
    second = await repo.keep(issuer, CALLBACK, "client-b", None, {"client_name": "NoClick"})
    assert first["client_id"] == second["client_id"] == "client-a"
    assert (await repo.get(issuer, "https://app.example/api/auth/mcp/callback")) is None
    stored = await pool.fetchrow("SELECT registration FROM mcp_oauth_clients WHERE issuer = $1", issuer)
    assert stored["registration"] == {"client_name": "NoClick"}
    await repo.forget(issuer, CALLBACK, "client-b")  # not the kept one: stays
    assert (await repo.get(issuer, CALLBACK))["client_id"] == "client-a"
    await repo.forget(issuer, CALLBACK, "client-a")
    assert await repo.get(issuer, CALLBACK) is None


async def test_connecting_in_app_stores_a_proven_credential_and_registers_once(vendor, pool):
    ana, bo = await _user(pool), await _user(pool)
    answer = await _connect_in_app(pool, ana)
    await _connect_in_app(pool, bo)
    assert len(vendor.registrations) == 1

    assert answer["success"] is True, answer
    assert answer["verification"]["reachable"] is True and answer["verification"]["noun"] == "tools"
    credential = answer["credential"]
    row = await pool.fetchrow("SELECT owner_id, credential_type, name, metadata FROM credentials WHERE id = $1::uuid",
                              credential["id"])
    assert str(row["owner_id"]) == ana and row["credential_type"] == "canva_mcp"
    assert row["name"] == f"Canva (MCP, {ACCOUNT})"
    assert row["metadata"]["verified_as"] == ACCOUNT and row["metadata"]["provider"] == "mcp"

    from nodes.core.connection_evidence import collect_evidence

    evidence = await collect_evidence(node_type="automation-canva", credential_id=credential["id"], user_id=ana, pool=pool)
    assert evidence.reachable is True and [s.label for s in evidence.samples] == ["search_designs", "whoami"]


async def test_a_stale_token_refreshes_through_the_choke_point_and_persists_the_rotation(vendor, pool, monkeypatch):
    from nodes.core.run_op import run_node_mcp_tool
    from utils.credential_loader import load_credential
    from utils.encryption import get_encryption

    ana = await _user(pool)
    credential_id = (await _connect_in_app(pool, ana))["credential"]["id"]
    stored = await load_credential(pool, ana, credential_id)
    old_access, old_refresh, version = stored["access_token"], stored["refresh_token"], stored["token_version"]
    # The token is past its time: the next call must refresh before it reaches the server.
    stale = {k: v for k, v in stored.items() if k not in ("token_version", "credential_type")}
    await pool.execute("UPDATE credentials SET credential = $2 WHERE id = $1::uuid", credential_id,
                       get_encryption().encrypt_credential({**stale, "expires_at": "2020-01-01T00:00:00+00:00"}))
    info = {"tool_type": "node_mcp", "node_type": "automation-canva", "mcp_tool": "search_designs",
            "credential_id": credential_id}

    result = await run_node_mcp_tool(info, {"query": "launch"}, user_id=ana, pool=pool)

    assert result == {"success": True, "result": '{"designs": [{"id": "D1", "title": "launch poster"}]}'}
    assert vendor.refreshes == 1
    fresh = await load_credential(pool, ana, credential_id)
    assert fresh["access_token"] != old_access and fresh["refresh_token"] != old_refresh
    assert old_refresh not in vendor.refresh_tokens  # single use: the old one is spent
    assert fresh["token_version"] > version
    assert vendor.calls[-1]["authorization"] == f"Bearer {fresh['access_token']}"
    # A live token is used as is.
    await run_node_mcp_tool(info, {"query": "again"}, user_id=ana, pool=pool)
    assert vendor.refreshes == 1


async def test_an_agent_gets_the_tools_and_its_calls_are_audited_like_node_op_calls(vendor, pool, monkeypatch):
    from nodes.agent.node_op_tools import build_node_mcp_tools, describe_provider_credential
    from nodes.agent.tool_execution import execute_tool

    ana = await _user(pool)
    credential_id = (await _connect_in_app(pool, ana))["credential"]["id"]
    output = {"type": "node_op_tool_provider", "node_type": "automation-canva", "credential_id": credential_id,
              "allowed_operations": ["list_user_designs"], "label": None, "sandbox_repos": []}
    await describe_provider_credential(pool, output, user_id=ana)
    assert [t["name"] for t in output["mcp_tools"]] == ["search_designs", "whoami"]
    _, configs = build_node_mcp_tools("automation-canva", output["mcp_tools"], node_id="canva-1",
                                      credential_id=credential_id)

    audited = []
    monkeypatch.setattr("utils.tool_call_log.record_tool_call", lambda **row: audited.append(row))
    agent = SimpleNamespace(user_id=ana, organization_id=None, workflow_id=None, conversation_id=None,
                            node_id="agent-1", execution_id=None, _effective_model="m")
    result = await execute_tool(agent, "canva__search_designs", {"query": "menu"}, configs)

    assert result["success"] is True and "menu poster" in result["result"]
    assert audited[0]["tool_type"] == "node_mcp" and audited[0]["operation"] == "mcp:search_designs"
    assert audited[0]["credential_id"] == credential_id and audited[0]["result_status"] == "success"
    assert audited[0]["provider_node_id"] == "canva-1"


async def test_a_provide_link_offers_mcp_for_canva_and_connects_through_it(vendor, pool):
    from utils.credential_request_routes import (
        McpFinishBody, McpStartBody, get_credential_request, mcp_finish, mcp_start,
    )

    requester = await _user(pool)
    token = (await pool.fetchrow(
        "INSERT INTO credential_requests (requester_id, target_email, credential_type, metadata) "
        "VALUES ($1, $2, 'canva_oauth', '{\"notify_requester\": false}'::jsonb) RETURNING token",
        uuid.UUID(requester), "designer@example.com",
    ))["token"]

    details = await get_credential_request(token)
    # Canva's own sign-in is hidden while it awaits Canva's review: the link offers MCP, naming the declared server.
    assert [(m.credential_type, m.method_kind, m.mcp_server) for m in details.available_methods] == [
        ("canva_mcp", "mcp", "https://api.canva.com/connect/v1/mcp")]

    started = await mcp_start(token, McpStartBody(credential_type="canva_mcp", redirect_uri=CALLBACK))
    back = await _sign_in(started["authorization_url"])
    stored = await mcp_finish(token, McpFinishBody(credential_type="canva_mcp", flow=started["flow"],
                                                   code=back["code"], state=back["state"]))

    assert stored["status"] == "success" and stored["verification"]["reachable"] is True
    request = await pool.fetchrow("SELECT status, credential_id FROM credential_requests WHERE token = $1", token)
    assert request["status"] == "fulfilled" and str(request["credential_id"]) == stored["credential_id"]
    row = await pool.fetchrow("SELECT credential_type, metadata FROM credentials WHERE id = $1",
                              request["credential_id"])
    assert row["credential_type"] == "canva_mcp" and row["metadata"]["provided_by"] == "designer@example.com"


async def test_a_provide_link_never_connects_an_unrelated_integration_through_mcp(vendor, pool):
    from fastapi import HTTPException

    from utils.credential_request_routes import McpStartBody, mcp_start

    requester = await _user(pool)
    token = (await pool.fetchrow(
        "INSERT INTO credential_requests (requester_id, target_email, credential_type) "
        "VALUES ($1, 'x@example.com', 'openai_api_key') RETURNING token", uuid.UUID(requester),
    ))["token"]
    with pytest.raises(HTTPException) as refused:
        await mcp_start(token, McpStartBody(credential_type="canva_mcp", redirect_uri=CALLBACK))
    assert refused.value.status_code == 400
