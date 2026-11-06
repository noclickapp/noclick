"""UNRUN actual native schema/factory/connect contracts, synthetic wire only.

The public vendor demo keys/examples are neither used nor emitted. Fixtures
exercise only synthetic IDs/private keys and the exact closed GET surfaces.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
import json
import httpx
import pytest
from nodes import rebrandly_node as p
from nodes.core.registry import NodeFactory
from nodes.core import connection_evidence as evidence, credential_connect as cc

KEY = {"credential_type": p.TYPE, "api_key": "synthetic_private_key", "workspace_id": "workspaceA"}
WORKSPACE = {"id": "workspaceA", "default": True, "createdAt": "2026-10-01T00:00:00Z", "name": "private-name", "type": "inline-unknown", "role": "manager", "owner": {"email": "private-owner"}, "subscription": {"billing": {"secret": KEY["api_key"]}}}
DOMAIN = {"id": "domainA", "fullName": "private-domain.example", "type": "USER", "createdAt": "2026-10-01T00:00:00Z", "status": {"dns": "verified", "subscription": "private-subscription"}, "workspace": {"id": "workspaceA"}}
LINK = {"id": "linkA", "domain": {"id": "domainA", "fullName": DOMAIN["fullName"], "sharing": {"private": True}}, "workspace": {"id": "workspaceA"}, "status": "blocked", "https": True, "clicks": 0, "createdAt": "2026-10-01T00:00:00Z", "updatedAt": "2026-10-02T00:00:00Z", "title": "private-title", "slashtag": "private-slash", "destination": "https://private-destination.example", "shortUrl": "private-short-url", "scripts": [{"secret": KEY["api_key"]}]}

@pytest.fixture
def ensure_native_db_pool():
    yield

def create(operation, **args):
    return NodeFactory.create_node("fixture", "automation-rebrandly", {"config": {"operation": operation, **args}, "credentials": deepcopy(KEY)})

@pytest.fixture
def wire(monkeypatch):
    state = {"calls": [], "responses": {}, "status": 200, "content": None, "headers": {"content-type": "application/json"}}
    @asynccontextmanager
    async def client(**options):
        assert options == {"timeout": 12, "follow_redirects": False, "trust_env": False}
        class Client:
            @asynccontextmanager
            async def stream(self, method, url, **kwargs):
                assert method == "GET" and url.startswith(p.ROOT + "/")
                assert kwargs["headers"]["apikey"] == KEY["api_key"]
                assert KEY["api_key"] not in url and KEY["api_key"] not in repr(kwargs)
                assert "json" not in kwargs and "data" not in kwargs and "Authorization" not in kwargs["headers"]
                endpoint, query = url.removeprefix(p.ROOT), deepcopy(kwargs["params"])
                if endpoint == "/workspaces": assert "Workspace" not in kwargs["headers"] and query == {"limit": query["limit"], "offset": 0}
                else: assert kwargs["headers"]["Workspace"] == "workspaceA"
                state["calls"].append((endpoint, query))
                if endpoint in state["responses"]:
                    payload = state["responses"][endpoint]
                    if callable(payload): payload = payload(query)
                else:
                    payload = {"/workspaces": [WORKSPACE], "/domains": [DOMAIN], "/domains/domainA": DOMAIN, "/links": [LINK], "/links/linkA": LINK}[endpoint]
                yield httpx.Response(state["status"], content=state["content"] if state["content"] is not None else json.dumps(payload).encode(), headers=state["headers"], request=httpx.Request(method, url))
        yield Client()
    monkeypatch.setattr(p, "guarded_async_client", client)
    return state


def test_real_native_schema_five_discriminators_and_manual_visible_credential():
    schema = p.RebrandlyNode.get_config_schema()
    refs = schema["properties"]["config"].get("oneOf") or schema["properties"]["config"]["anyOf"]
    actual = {schema["$defs"][ref["$ref"].rsplit("/", 1)[1]]["properties"]["operation"]["const"] for ref in refs}
    assert actual == p.OPERATIONS == {"list_workspaces", "list_domains", "get_domain", "list_links", "get_link"}
    for ref in refs:
        props = schema["$defs"][ref["$ref"].rsplit("/", 1)[1]]["properties"]
        assert not set(props) & {"url", "method", "headers", "body", "query", "destination", "shortUrl", "create", "delete"}
    visible = {k: v for k, v in KEY.items() if k != "credential_type"}
    assert p.RebrandlyAPIKeyCredential.model_validate(visible).model_dump(exclude_unset=True) == KEY
    assert KEY["api_key"] not in repr(p.guard(KEY))


@pytest.mark.asyncio
async def test_real_manual_connect_catalog_is_access_not_identity(wire, monkeypatch):
    monkeypatch.setattr(cc, "_collect_evidence", evidence.collect_evidence)
    verdict = await cc.validate_for_connect(credential_type=p.TYPE, credential_data={k: v for k, v in KEY.items() if k != "credential_type"}, user_id="fixture", probe=True)
    assert verdict.ok and verdict.credential_data == KEY
    assert verdict.evidence.reachable is True and p.RebrandlyNode.connection_evidence.proves == "reachability"
    assert verdict.evidence.account_label is None and verdict.evidence.answers_field is None
    assert wire["calls"] == [("/workspaces", {"limit": 25, "offset": 0})]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", sorted(p.OPERATIONS))
async def test_actual_factory_five_closed_reads_and_no_sensitive_subtrees(wire, operation):
    args = {"domain_id": "domainA"} if operation in {"get_domain", "list_links", "get_link"} else {}
    if operation == "get_link": args["link_id"] = "linkA"
    result = await create(operation, **args).execute({})
    serialized = json.dumps(result)
    assert not any(s in serialized for s in (KEY["api_key"], "private-name", "private-domain", "private-title", "private-slash", "private-destination", "private-short-url", "private-owner", "private-subscription", "manager", "inline-unknown"))
    if operation == "list_workspaces":
        assert result["selected_workspace_access_witnessed"] and not result["principal_identity_verified"] and not result["workspace_ownership_verified"]
    if operation.startswith("list_"):
        assert result["total"] is None and result["has_more"] is None and result["completion_verified"] is False
    if operation == "get_domain": assert result["dns_status"] == "verified" and "type" not in result
    if operation == "get_link": assert result["status"] == "blocked" and result["clicks"] == 0 and result["https"] is True
    if operation in {"list_links", "get_link"}: assert ("/links", {"limit": 25, "domain.id": "domainA"}) in wire["calls"]


@pytest.mark.asyncio
async def test_names_opt_in_and_workspace_inline_shape_not_common_enum(wire):
    result = await create("list_workspaces", include_names=True).execute({})
    assert result["items"][0]["name"] == "private-name" and "role" not in result["items"][0] and "type" not in result["items"][0]
    result = await create("get_link", domain_id="domainA", link_id="linkA", include_names=True).execute({})
    assert result["title"] == "private-title" and result["slashtag"] == "private-slash"
    assert "destination" not in result and "domainName" not in result


@pytest.mark.asyncio
async def test_workspace_binding_denies_foreign_before_http_and_catalog_absence_is_not_global(wire):
    with pytest.raises(ValueError, match="saved scope"): await create("list_domains", workspace_id="workspaceB").execute({})
    assert wire["calls"] == []
    wire["responses"]["/workspaces"] = [{"id": "workspaceB", "type": "other-inline"}]
    with pytest.raises(ValueError, match="bounded current catalog"): await create("get_domain", domain_id="domainA").execute({})
    assert [ep for ep, _ in wire["calls"]] == ["/workspaces"]


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint,change", [("/domains/domainA", {"id": "domainB"}), ("/domains/domainA", {"fullName": "different.example"}), ("/domains/domainA", {"workspace": {"id": "workspaceB"}}), ("/links/linkA", {"id": "linkB"}), ("/links/linkA", {"domain": {"id": "domainB"}}), ("/links/linkA", {"workspace": {"id": "workspaceB"}})])
async def test_exact_current_workspace_domain_and_point_binding(wire, endpoint, change):
    wire["responses"][endpoint] = {**(DOMAIN if endpoint.startswith("/domains") else LINK), **change}
    with pytest.raises(ValueError): await create("get_link", domain_id="domainA", link_id="linkA").execute({})


@pytest.mark.asyncio
async def test_absent_members_and_missing_nested_parent_deny_point_without_alias_fallback(wire):
    wire["responses"]["/domains"] = []
    with pytest.raises(ValueError, match="bounded"): await create("get_domain", domain_id="domainA").execute({})
    assert all(ep != "/domains/domainA" for ep, _ in wire["calls"])
    wire["calls"].clear(); wire["responses"]["/domains"] = [DOMAIN]
    alias = {**LINK, "domainId": "domainA", "domainName": DOMAIN["fullName"]}; del alias["domain"]
    wire["responses"]["/links"] = [alias]
    with pytest.raises(ValueError, match="nested domain"): await create("get_link", domain_id="domainA", link_id="linkA").execute({})
    assert all(ep != "/links/linkA" for ep, _ in wire["calls"])


@pytest.mark.asyncio
async def test_real_picker_parent_context_string_values_and_search_binding(wire):
    workspace = await p.RebrandlyNode.load_field_options("workspace_id", KEY)
    domains = await p.RebrandlyNode.load_field_options("domain_id", KEY, {"workspace_id": "workspaceA"})
    links = await p.RebrandlyNode.load_field_options("link_id", KEY, {"workspace_id": "workspaceA", "domain_id": "domainA"})
    assert workspace["options"] == [{"value": "workspaceA", "label": "Saved workspace"}]
    assert domains["options"] == [{"value": "domainA", "label": "Domain domainA"}]
    assert links["options"] == [{"value": "linkA", "label": "Link linkA"}]
    wire["calls"].clear()
    with pytest.raises(ValueError): await p.RebrandlyNode.load_field_options("domain_id", KEY)
    with pytest.raises(ValueError): await p.RebrandlyNode.load_field_options("link_id", KEY, {"workspace_id": "workspaceA"})
    with pytest.raises(ValueError, match="continuation"): await p.RebrandlyNode.load_field_options("domain_id", KEY, {"workspace_id": "workspaceA"}, search="changed", page_token=domains["next_page_token"])
    assert wire["calls"] == []


@pytest.mark.asyncio
async def test_short_page_candidate_preceding_id_and_unknown_completion(wire):
    first = await create("list_domains").execute({})
    assert first["count"] == 1 and first["next_page_token"] and first["has_more"] is None and not first["completion_verified"]
    wire["responses"]["/domains"] = lambda q: [] if q.get("last") == "domainA" else [DOMAIN]
    second = await create("list_domains", page_token=first["next_page_token"]).execute({})
    assert second["count"] == 0 and second["next_page_token"] is None and second["completion_verified"] is False
    assert wire["calls"][-1] == ("/domains", {"limit": 25, "last": "domainA"})
    for args in ({"limit": 24}, {"include_names": True}):
        wire["calls"].clear()
        with pytest.raises(ValueError, match="continuation"): await create("list_domains", page_token=first["next_page_token"], **args).execute({})
        assert wire["calls"] == []


@pytest.mark.asyncio
async def test_ten_caller_driven_page_cap_without_automatic_traversal(wire):
    counter = 0
    def page(_query):
        nonlocal counter
        counter += 1
        return [{**DOMAIN, "id": f"domain{counter}"}]
    wire["responses"]["/domains"] = page
    token = None
    for _ in range(p.MAX_PAGES):
        result = await create("list_domains", page_token=token).execute({})
        token = result["next_page_token"]
    assert result["local_limit_reached"] and token is None and result["has_more"] is None
    assert counter == p.MAX_PAGES


@pytest.mark.parametrize("kind,payload", [("workspace", [{"id": "workspaceA", "default": 1}]), ("domain", [{**DOMAIN, "status": {"dns": "unknown"}}]), ("domain", [DOMAIN, DOMAIN]), ("link", [{**LINK, "clicks": True}]), ("link", [{**LINK, "status": "unknown"}]), ("link", [{**LINK, "https": "true"}])])
def test_exact_scalar_metadata_and_bare_array_contract(kind, payload):
    with pytest.raises(ValueError): p.rows(payload, kind, 25, p.guard(KEY), domain="domainA")


@pytest.mark.asyncio
@pytest.mark.parametrize("status,content,headers", [(401, None, None), (403, None, None), (404, None, None), (429, None, None), (302, None, {"location": "http://127.0.0.1"}), (200, b'{}', None), (200, b'[{"id":"a","id":"b"}]', None), (200, b'[NaN]', None), (200, b'private body', {"content-type": "text/plain"})])
async def test_sanitized_refusals_shapes_and_no_retry_or_refusal_identity(wire, status, content, headers):
    wire.update(status=status, content=content)
    if headers is not None: wire["headers"] = headers
    with pytest.raises(ValueError) as error: await create("list_workspaces").execute({})
    assert len(wire["calls"]) == 1 and KEY["api_key"] not in str(error.value) and "private body" not in str(error.value)


@pytest.mark.asyncio
async def test_local_body_and_route_query_bounds(wire):
    wire["content"] = b'x' * (p.MAX_BYTES + 1)
    with pytest.raises(ValueError): await create("list_workspaces").execute({})
    assert len(wire["calls"]) == 1
    wire["calls"].clear()
    for endpoint, query in (("/links/linkA/scripts", {}), ("/links", {"limit": 25, "domain.fullName": "private-domain.example"}), ("/domains", {"limit": True}), ("/workspaces", {"limit": 25, "offset": 1})):
        with pytest.raises(ValueError): await p.request(p.guard(KEY), endpoint, query=query)
    assert wire["calls"] == []
