"""Connecting an integration through its vendor's MCP server (nodes/core/vendor_mcp.py,
nodes/oauth/mcp_connect.py), against a local MCP server that implements the auth spec
(tests/fixtures/fake_mcp_auth_server.py): discovery, one client registration for
everyone, the person's sign-in and the code exchange, the proof (tools/list), the
agent tools it gives, and what it refuses. The database-backed halves (the client
store, storing, refreshing through the choke point, the provide link) are in
test_vendor_mcp_postgres.py."""

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from nodes.canva_node import CanvaMcpCredential, CanvaNode
from nodes.core import vendor_mcp
from nodes.oauth import mcp_connect
from tests.fixtures.fake_mcp_auth_server import ACCOUNT, FakeMcpAuthServer, serve

pytestmark = pytest.mark.asyncio

CALLBACK = "http://localhost:5173/api/auth/mcp/callback"


class MemoryClients:
    """The client store's contract (repositories/mcp_clients.py, proven on Postgres elsewhere), in memory."""

    rows: dict = {}

    def __init__(self, pool):
        pass

    async def get(self, issuer, redirect_uri):
        return self.rows.get((issuer, redirect_uri))

    async def keep(self, issuer, redirect_uri, client_id, sealed, registration):
        self.rows.setdefault((issuer, redirect_uri), {"client_id": client_id, "client_secret_sealed": sealed})
        return self.rows[(issuer, redirect_uri)]

    async def forget(self, issuer, redirect_uri, client_id):
        if (self.rows.get((issuer, redirect_uri)) or {}).get("client_id") == client_id:
            del self.rows[(issuer, redirect_uri)]


@pytest.fixture(autouse=True)
def loopback(monkeypatch):
    monkeypatch.setenv("OUTBOUND_ALLOW_PRIVATE_IPS", "true")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:5173")
    MemoryClients.rows = {}
    monkeypatch.setattr("repositories.mcp_clients.McpClientRepo", MemoryClients)


@pytest.fixture
async def vendor(monkeypatch):
    """The fake server, declared as Canva's: the real Canva wiring, pointed at it."""
    async with serve(FakeMcpAuthServer()) as fake:
        monkeypatch.setattr(CanvaMcpCredential, "mcp_server", vendor_mcp.McpServer(url=fake.mcp_url, app="Canva"))
        yield fake


async def sign_in(authorization_url: str) -> dict:
    """The person consenting in the window: the server sends the browser back with a code."""
    async with httpx.AsyncClient() as client:
        answer = await client.get(authorization_url)
    assert answer.status_code == 302, answer.text
    back = urlsplit(answer.headers["location"])
    assert f"{back.scheme}://{back.netloc}{back.path}" == CALLBACK
    return {k: v[0] for k, v in parse_qs(back.query).items()}


# ------------------------------------------------------------ the declaration


async def test_canva_declares_its_mcp_server_as_a_way_in():
    from nodes.core.base import credential_type_literals
    from nodes.core.credential_connect import credential_classes_for_node

    assert CanvaMcpCredential in credential_classes_for_node(CanvaNode)
    assert vendor_mcp.node_mcp_credential(CanvaNode) is CanvaMcpCredential
    assert "canva_mcp" in credential_type_literals(CanvaNode.get_config_model())
    # Canva's Connect API route, signed into through NoClick's Canva app (mcp.canva.com admits only its waitlist).
    server = vendor_mcp.server_of("canva_mcp")
    assert (server.url, server.client_env) == ("https://api.canva.com/connect/v1/mcp", "CANVA")
    assert vendor_mcp.node_type_of("canva_mcp") == "automation-canva"
    schema = CanvaNode.get_config_schema()
    member = schema["$defs"]["CanvaMcpCredential"]
    assert member["x-credential-type"] == "mcp" and member["x-mcp-server"] == "https://api.canva.com/connect/v1/mcp"
    assert {"$ref": "#/$defs/CanvaMcpCredential"} in schema["properties"]["credentials"]["anyOf"]
    # Canva's own sign-in waits on Canva's review: hidden, so MCP is the way in meanwhile.
    assert schema["$defs"]["CanvaOAuthCredential"]["x-credential-hidden"] is True


@pytest.mark.parametrize("node_type, credential_type, url", [
    ("automation-notion", "notion_mcp", "https://mcp.notion.com/mcp"),
    ("automation-calendly", "calendly_mcp", "https://mcp.calendly.com"),
])
async def test_notion_and_calendly_declare_their_servers_beside_their_own_ways_in(node_type, credential_type, url):
    from nodes.core.credential_connect import credential_classes_for_node
    from nodes.core.registry import NODE_REGISTRY

    node = NODE_REGISTRY[node_type]
    declared = vendor_mcp.node_mcp_credential(node)
    assert declared is not None and declared.mcp_server.url == url and declared.mcp_server.client_env is None
    assert vendor_mcp.node_type_of(credential_type) == node_type
    assert len(credential_classes_for_node(node)) == 3  # its sign-in and key stay


async def test_a_nodes_own_refresh_never_spends_an_mcp_token(monkeypatch):
    """Dropdowns and trigger paths freshen what they load through the node's own hook: an MCP
    credential refreshes at its MCP server, never through the node's REST OAuth app."""
    from nodes.notion_node import NotionMcpCredential, NotionNode
    from nodes.oauth import notion_oauth

    async def notion_refresh(*args, **kwargs):
        raise AssertionError("Notion's own OAuth refresh was used on an MCP token")

    monkeypatch.setattr(notion_oauth, "refresh_access_token", notion_refresh)
    async with serve(FakeMcpAuthServer()) as fake:
        monkeypatch.setattr(NotionMcpCredential, "mcp_server", vendor_mcp.McpServer(url=fake.mcp_url, app="Notion"))
        started = await mcp_connect.start("notion_mcp", redirect_uri=CALLBACK, principal="user:ana")
        back = await sign_in(started.authorization_url)
        connected = await mcp_connect.finish(started.flow, principal="user:ana", code=back["code"], state=back["state"])
        stale = {**connected.credential_data, "credential_type": "notion_mcp", "expires_at": "2020-01-01T00:00:00+00:00"}
        fresh = await NotionNode.freshen_credential(stale, pool=None, user_id=None, credential_id=None)
    assert fake.refreshes == 1 and fresh["access_token"] != connected.credential_data["access_token"]


async def test_an_mcp_credential_is_never_typed_in():
    from nodes.core.credential_connect import validate_for_connect

    verdict = await validate_for_connect(
        credential_type="canva_mcp", credential_data={"mcp_server_url": "https://evil.example/mcp", "access_token": "x"},
        user_id="u", probe=False,
    )
    assert not verdict.ok
    assert "set by NoClick when you connect through MCP" in verdict.field_errors["mcp_server_url"]


async def test_a_workflow_step_refuses_an_mcp_credential():
    from nodes.core.base import ConfigValidationError
    from nodes.core.registry import NodeFactory

    node = NodeFactory.create_node(
        node_id="c1", node_type="automation-canva",
        node_data={"config": {"operation": "list_user_designs"},
                   "credentials": {"credential_type": "canva_mcp", "mcp_server_url": "https://api.canva.com/connect/v1/mcp",
                                   "access_token": "t"}},
        user_id="u",
    )
    with pytest.raises(ConfigValidationError, match="connected through Canva's MCP server"):
        await node.run({})


async def test_a_call_only_reaches_the_declared_server():
    with pytest.raises(ValueError, match="Connect Canva through MCP again"):
        await vendor_mcp.list_tools("canva_mcp", {"mcp_server_url": "https://evil.example/mcp", "access_token": "t"})


async def test_the_callback_must_be_this_apps_own(monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", "https://app.example")
    allowed = mcp_connect.allowed_callback
    assert allowed("https://app.example/api/auth/mcp/callback")
    assert allowed("https://staging.app.example/api/auth/mcp/callback")
    assert allowed("http://wt5173.localhost:5173/api/auth/mcp/callback")
    assert not allowed("https://app.example.evil.example/api/auth/mcp/callback")
    assert not allowed("https://evil.example/api/auth/mcp/callback")
    assert not allowed("http://app.example/api/auth/mcp/callback")
    assert not allowed("https://app.example/api/auth/mcp/callback?next=x")
    assert not allowed("https://app.example/elsewhere")


# ------------------------------------------------------------------ discovery


async def test_discovery_reads_the_resource_and_its_authorization_server(vendor):
    from nodes.oauth.mcp_oauth import discover_oauth_requirements

    found = await discover_oauth_requirements(vendor.mcp_url)
    assert found.requires_oauth and found.error is None
    assert found.authorization_endpoint == f"{vendor.base}/authorize"
    assert found.registration_endpoint == f"{vendor.base}/register"
    assert found.resource_url == vendor.mcp_url
    assert found.resource_scopes == ["designs:read", "designs:write"]
    assert found.issuer == vendor.base


async def test_discovery_reads_a_server_on_the_earlier_spec():
    from nodes.oauth.mcp_oauth import discover_oauth_requirements

    async with serve(FakeMcpAuthServer(legacy=True)) as fake:
        found = await discover_oauth_requirements(fake.mcp_url)
    assert found.requires_oauth and found.error is None
    assert found.authorization_endpoint == f"{fake.base}/authorize"
    assert found.resource_url == fake.mcp_url


# ---------------------------------------------------------------- the connect


async def test_connect_registers_once_signs_in_and_proves_the_account(vendor):
    first = await mcp_connect.start("canva_mcp", redirect_uri=CALLBACK, principal="user:ana")
    second = await mcp_connect.start("canva_mcp", redirect_uri=CALLBACK, principal="user:bo")
    # One client at the vendor for every person connecting from this app.
    assert len(vendor.registrations) == 1
    registered = next(iter(vendor.registrations.values()))
    assert registered["redirect_uris"] == [CALLBACK] and registered["token_endpoint_auth_method"] == "none"
    assert (registered["client_name"], registered["client_uri"]) == ("NoClick", "http://localhost:5173")
    assert first.kind == "oauth" and second.state != first.state
    params = parse_qs(urlsplit(first.authorization_url).query)
    assert params["code_challenge_method"] == ["S256"] and params["resource"] == [vendor.mcp_url]
    assert params["scope"] == ["designs:read designs:write"]

    back = await sign_in(first.authorization_url)
    assert back["state"] == first.state
    connected = await mcp_connect.finish(first.flow, principal="user:ana", code=back["code"], state=back["state"])

    assert connected.credential_type == "canva_mcp"
    data = connected.credential_data
    assert data["mcp_server_url"] == vendor.mcp_url and data["client_id"] == "client-1"
    assert data["access_token"] in vendor.access_tokens and data["refresh_token"] in vendor.refresh_tokens
    assert data["account"] == ACCOUNT and connected.name == f"Canva (MCP, {ACCOUNT})"
    # The proof is the server listing its tools for this token.
    assert connected.evidence.reachable is True and connected.evidence.noun == "tools"
    assert [s.label for s in connected.evidence.samples] == ["search_designs", "whoami"]
    assert connected.metadata["verified_as"] == ACCOUNT and connected.metadata["mcp_server_url"] == vendor.mcp_url
    # The class parses what was stored.
    assert CanvaMcpCredential.model_validate({**data, "credential_type": "canva_mcp"}).account == ACCOUNT


async def test_finish_belongs_to_whoever_started_it(vendor):
    started = await mcp_connect.start("canva_mcp", redirect_uri=CALLBACK, principal="request:r1")
    back = await sign_in(started.authorization_url)
    with pytest.raises(mcp_connect.McpConnectError, match="started by someone else"):
        await mcp_connect.finish(started.flow, principal="user:mallory", code=back["code"], state=back["state"])
    with pytest.raises(mcp_connect.McpConnectError, match="doesn't belong to this connection"):
        await mcp_connect.finish(started.flow, principal="request:r1", code=back["code"], state="another")
    with pytest.raises(mcp_connect.McpConnectError, match="isn't valid"):
        await mcp_connect.finish(started.flow[:-4] + "AAAA", principal="request:r1", code=back["code"], state=back["state"])
    with pytest.raises(mcp_connect.McpConnectError, match="didn't accept the sign-in"):
        await mcp_connect.finish(started.flow, principal="request:r1", code="not-the-code", state=back["state"])


async def test_an_expired_attempt_is_refused(vendor, monkeypatch):
    started = await mcp_connect.start("canva_mcp", redirect_uri=CALLBACK, principal="user:ana")
    back = await sign_in(started.authorization_url)
    monkeypatch.setattr(mcp_connect, "FLOW_TTL_S", -1)
    with pytest.raises(mcp_connect.McpConnectError, match="expired"):
        await mcp_connect.finish(started.flow, principal="user:ana", code=back["code"], state=back["state"])


async def test_a_server_that_refuses_noclicks_redirect_says_so_before_any_window(monkeypatch):
    async with serve(FakeMcpAuthServer(allowed_redirect_hosts={"claude.ai"})) as fake:
        monkeypatch.setattr(CanvaMcpCredential, "mcp_server", vendor_mcp.McpServer(url=fake.mcp_url, app="Canva"))
        with pytest.raises(mcp_connect.McpConnectError) as refused:
            await mcp_connect.start("canva_mcp", redirect_uri=CALLBACK, principal="user:ana")
    assert str(refused.value).startswith("Canva's MCP server refused NoClick's sign-in: Invalid redirect URI.")


async def test_a_server_that_takes_a_key_asks_for_it_and_proves_it(monkeypatch):
    async with serve(FakeMcpAuthServer(key="sk-right")) as fake:
        monkeypatch.setattr(CanvaMcpCredential, "mcp_server", vendor_mcp.McpServer(url=fake.mcp_url, app="Canva"))
        started = await mcp_connect.start("canva_mcp", redirect_uri=CALLBACK, principal="user:ana")
        assert started.kind == "key" and started.authorization_url is None
        with pytest.raises(mcp_connect.McpConnectError, match="refused this account"):
            await mcp_connect.finish(started.flow, principal="user:ana", api_key="sk-wrong")
        connected = await mcp_connect.finish(started.flow, principal="user:ana", api_key=" sk-right ")
    assert connected.credential_data == {"mcp_server_url": fake.mcp_url, "api_key": "sk-right"}
    assert connected.evidence.reachable is True


async def test_a_server_for_registered_apps_signs_in_through_noclicks_app(monkeypatch):
    """No self-registration: the declaration names NoClick's app at the vendor, whose secret is
    read where it's configured, at the exchange and at every refresh, and never stored per person."""
    fake = FakeMcpAuthServer(dcr=False)
    fake.registrations["noclick-app"] = {"redirect_uris": [CALLBACK], "client_secret": "app-secret"}
    async with serve(fake):
        server = vendor_mcp.McpServer(url=fake.mcp_url, app="Canva", client_env="FAKEVENDOR")
        monkeypatch.setattr(CanvaMcpCredential, "mcp_server", server)
        with pytest.raises(mcp_connect.McpConnectError, match=r"none set up \(FAKEVENDOR_CLIENT_ID\)"):
            await mcp_connect.start("canva_mcp", redirect_uri=CALLBACK, principal="user:ana")

        monkeypatch.setenv("FAKEVENDOR_CLIENT_ID", "noclick-app")
        monkeypatch.setenv("FAKEVENDOR_CLIENT_SECRET", "app-secret")
        started = await mcp_connect.start("canva_mcp", redirect_uri=CALLBACK, principal="user:ana")
        assert fake.registrations.keys() == {"noclick-app"}  # nothing registered
        back = await sign_in(started.authorization_url)
        connected = await mcp_connect.finish(started.flow, principal="user:ana", code=back["code"], state=back["state"])
        data = connected.credential_data
        assert data["client_id"] == "noclick-app" and "client_secret" not in data
        assert connected.evidence.reachable is True

        stale = {**data, "credential_type": "canva_mcp", "expires_at": "2020-01-01T00:00:00+00:00"}
        fresh = await vendor_mcp.fresh_credential(stale, credential_id=None, user_id=None)
        assert fake.refreshes == 1 and fresh["access_token"] != data["access_token"]


async def test_a_server_with_metadata_documents_only_takes_noclicks_document(monkeypatch):
    """CIMD: the client id is NoClick's document on the callback's own (public) origin."""
    callback = "https://app.example/api/auth/mcp/callback"
    document = "https://app.example/mcp/client.json"
    monkeypatch.setenv("FRONTEND_URL", "https://app.example")
    fake = FakeMcpAuthServer(dcr=False, documents={document: {"client_id": document, "redirect_uris": [callback]}})
    async with serve(fake):
        monkeypatch.setattr(CanvaMcpCredential, "mcp_server", vendor_mcp.McpServer(url=fake.mcp_url, app="Canva"))
        started = await mcp_connect.start("canva_mcp", redirect_uri=callback, principal="user:ana")
        assert parse_qs(urlsplit(started.authorization_url).query)["client_id"] == [document]
        assert fake.registrations == {}
        # A dev server's loopback origin can't be fetched: no document is offered from there.
        with pytest.raises(mcp_connect.McpConnectError, match="only clients it approved"):
            await mcp_connect.start("canva_mcp", redirect_uri=CALLBACK, principal="user:ana")


async def test_a_refused_token_is_definitive_evidence(vendor):
    result = await vendor_mcp.evidence("canva_mcp", {"mcp_server_url": vendor.mcp_url, "access_token": "revoked"})
    assert result.reachable is False and "refused this account (HTTP 401)" in result.error


# ----------------------------------------------------------------- the agent


async def test_an_agent_gets_the_servers_tools_named_like_node_op_tools(vendor):
    from nodes.agent.node_op_tools import build_node_mcp_tools

    vendor.access_tokens["live"] = 9e12
    tools = await vendor_mcp.list_tools("canva_mcp", {"mcp_server_url": vendor.mcp_url, "access_token": "live"})
    params, configs = build_node_mcp_tools("automation-canva", tools + [{"name": "odd.name/x", "inputSchema": {}}],
                                           node_id="canva-1", credential_id="cred-1")
    assert [p["function"]["name"] for p in params] == ["canva__search_designs", "canva__whoami", "canva__odd_name_x"]
    search = configs["canva__search_designs"]
    assert search["tool_type"] == "node_mcp" and search["mcp_tool"] == "search_designs"
    assert search["operation"] == "mcp:search_designs" and search["credential_id"] == "cred-1"
    assert search["_parameters"]["required"] == ["query"] and search["_description"].startswith("Find designs")
    assert configs["canva__odd_name_x"]["_parameters"] == {"type": "object", "properties": {}}


async def test_the_agent_node_collects_mcp_tools_in_place_of_operations():
    from nodes.agent_node import AgentNode

    agent = AgentNode.__new__(AgentNode)
    agent.node_id = "agent-1"
    agent._workflow_nodes = [{"id": "canva-1", "type": "automation-canva"}, {"id": "agent-1", "type": "agent"}]
    agent._workflow_edges = [{"source": "canva-1", "target": "agent-1", "sourceHandle": "top", "targetHandle": "bottom"}]
    output = {
        "type": "node_op_tool_provider", "node_type": "automation-canva", "credential_id": "cred-1",
        "allowed_operations": ["list_user_designs"], "label": None, "sandbox_repos": [],
        "mcp_tools": [{"name": "search_designs", "description": "Find designs.", "inputSchema": {"type": "object"}}],
    }
    params, configs, _ = agent._collect_tool_definitions({"canva-1": output})
    names = {p["function"]["name"] for p in params}
    assert "canva__search_designs" in names and "canva__list_user_designs" not in names
    assert configs["canva__search_designs"]["tool_type"] == "node_mcp"
