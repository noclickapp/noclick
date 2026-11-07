"""Dub native config, protected metadata parsing, transport and saved-key rechecks."""
from dataclasses import asdict
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest

from nodes import dub_node as ad
from nodes.core.registry import NODE_REGISTRY, NodeFactory

NODE = "automation-dub"
CID, USER, OWNER, ORG, WF = [str(UUID(int=i)) for i in (42, 1, 2, 3, 4)]
STAMP = "2026-10-01T00:00:00Z"


@pytest.fixture
def ensure_native_db_pool():
    yield


def credential(**updates):
    return {"credential_type": "dub_api_key", "api_key": "synthetic-test-key", **updates}


def domain(**updates):
    return {"id": "domain_a", "slug": "fixture.example", "verified": True, "primary": False, "archived": False,
        "createdAt": STAMP, "updatedAt": STAMP, "notFoundUrl": "private-sentinel", "assetLinks": {"private": "private-sentinel"}, **updates}


def link(**updates):
    return {"id": "link_a", "domain": "fixture.example", "workspaceId": "workspace_a", "archived": False,
        "clicks": 2.5, "createdAt": STAMP, "updatedAt": STAMP, "expiresAt": None, "disabledAt": None, "lastClicked": None,
        "key": "private-name", "title": None, "url": "private-sentinel", "shortLink": "private-sentinel", "password": "private-sentinel",
        "qrCode": "private-sentinel", "projectId": "deprecated-parent", "saleAmount": 90, **updates}


def make_node(operation, raw=None, **config):
    return NodeFactory.create_node("fixture", NODE, {"config": {"operation": operation, **config}, "credentials": credential() if raw is None else raw}, user_id=USER)


@pytest.fixture
def http(monkeypatch):
    state = SimpleNamespace(calls=[], responses=[], on_response=None)
    async def respond(request):
        state.calls.append(request)
        assert state.responses, "Unexpected provider request"
        status, payload = state.responses.pop(0)
        if state.on_response:
            state.on_response()
        return httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(ad, "guarded_async_client", client)
    return state


def test_real_factory_schema_and_rejected_operations_and_raw_family():
    assert NODE_REGISTRY[NODE] is ad.DubNode
    defs = ad.DubNode.get_config_schema()["$defs"]
    assert defs["DubApiKeyCredential"]["required"] == ["api_key"]
    ops = {d["properties"]["operation"]["const"] for d in defs.values() if "operation" in d.get("properties", {})}
    assert ops == {"list_domains", "list_links", "get_link", "count_links"}
    assert "domain_id" in defs["DubLinkConfig"]["properties"]["link_id"]["x-dynamic-options"]["depends_on"]
    for operation in ("create_link", "analytics", "get_account", "issue_key"):
        with pytest.raises(ValueError): make_node(operation)
    with pytest.raises(ValueError): make_node("list_domains", raw=credential(credential_type="dub_oauth"))


@pytest.mark.parametrize("operation,extra", [("list_links", {}), ("get_link", {"link_id": "link_a"})])
def test_opposing_cursors_are_rejected_before_http(operation, extra):
    with pytest.raises(ValueError, match="never both"):
        make_node(operation, domain_id="domain_a", starting_after="link_a", ending_before="link_b", **extra)


@pytest.mark.asyncio
async def test_real_domains_bare_array_projection_no_principal_or_workspace_invention(http):
    http.responses = [(200, [domain()]), (200, [domain()])]
    out = await make_node("list_domains").execute({})
    assert out["status"] == "success" and out["data"][0]["id"] == "domain_a"
    assert out["has_more"] is None and out["pagination_complete"] is None
    assert "returned_workspace_id" not in out and "slug" not in out["data"][0]
    assert out["principal_identity_proven"] is False and "private-sentinel" not in json.dumps(out)
    for request in http.calls:
        assert request.method == "GET" and request.url.host == "api.dub.co" and request.url.path == "/domains"
        assert dict(request.url.params) == {"archived": "false", "page": "1", "pageSize": "50"}
        assert request.headers["authorization"] == "Bearer synthetic-test-key" and "synthetic-test-key" not in str(request.url)


@pytest.mark.asyncio
async def test_empty_protected_catalog_manual_connect_is_reachability_without_identity(http, monkeypatch):
    from nodes.core import credential_connect
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(credential_connect, "_collect_evidence", collect_evidence)
    http.responses = [(200, []), (200, [])]
    verdict = await credential_connect.validate_for_connect(credential_type="dub_api_key", credential_data=credential(), user_id=USER)
    assert verdict.ok and verdict.evidence.reachable is True
    assert ad.DubNode.connection_evidence.proves == "reachability"
    assert verdict.evidence.account_label is None and verdict.evidence.samples == []
    assert "workspaceId" not in json.dumps(asdict(verdict.evidence))


@pytest.mark.asyncio
@pytest.mark.parametrize("cursor,query", [("starting_after", "startingAfter"), ("ending_before", "endingBefore")])
async def test_real_selected_domain_link_cursor_route_and_unknown_completion(http, cursor, query):
    http.responses = [(200, [domain()]), (200, [link()]), (200, [link()]), (200, [domain()])]
    out = await make_node("list_links", domain_id="domain_a", **{cursor: "opaque_cursor"}).execute({})
    assert out["data"][0]["clicks"] == 2.5 and out["returned_workspace_id"] == "workspace_a"
    assert out["next_page_token"] is None and out["has_more"] is None
    for request in http.calls[1:3]:
        assert dict(request.url.params) == {"domain": "fixture.example", "showArchived": "false", "pageSize": "100", query: "opaque_cursor"}
    assert "private-sentinel" not in json.dumps(out) and "projectId" not in json.dumps(out)


@pytest.mark.asyncio
async def test_current_link_detail_is_bound_before_and_after_with_linkid_only(http):
    http.responses = [(200, [domain()]), (200, [link()]), (200, link()), (200, [link()]), (200, [domain()])]
    out = await make_node("get_link", domain_id="domain_a", link_id="link_a").execute({})
    assert out["status"] == "success" and out["data"]["expiresAt"] is None
    assert http.calls[2].url.path == "/links/info" and dict(http.calls[2].url.params) == {"linkId": "link_a"}


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [0, 12, 1.25])
async def test_count_preserves_number_and_selected_nonarchived_query(http, value):
    http.responses = [(200, [domain()]), (200, value), (200, [domain()])]
    out = await make_node("count_links", domain_id="domain_a").execute({})
    assert out["count"] == value and type(out["count"]) is type(value)
    assert dict(http.calls[1].url.params) == {"domain": "fixture.example", "showArchived": "false"}
    assert out["count_scope"] == "current_token_filtered_selected_domain_nonarchived_links"


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [True, -1, {"domain": 1}, None, "1"])
async def test_malformed_count_never_becomes_success(http, value):
    http.responses = [(200, [domain()]), (200, value)]
    out = await make_node("count_links", domain_id="domain_a").execute({})
    assert out["status"] == "error" and out["_halt_downstream"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [link(id="other"), link(domain="other.example"), link(workspaceId="other_workspace"), link(archived=True)])
async def test_detail_ancestry_mismatch_stops_before_readback_or_output(http, bad):
    http.responses = [(200, [domain()]), (200, [link()]), (200, bad)]
    out = await make_node("get_link", domain_id="domain_a", link_id="link_a").execute({})
    assert out["status"] == "error" and len(http.calls) == 3 and "private-sentinel" not in json.dumps(out)


@pytest.mark.asyncio
async def test_missing_parent_and_wrong_raw_family_before_provider(http):
    for context in ({}, {"domain_id": "../foreign", "approved": True}):
        with pytest.raises(ValueError): await ad.DubNode.load_field_options("link_id", credential(), context=context)
    with pytest.raises(ValueError): await ad.DubNode.load_field_options("domain_id", credential(credential_type="other"))
    with pytest.raises(ValueError): make_node("list_links", domain_id="domain_a", starting_after="a", ending_before="b")
    assert http.calls == []


@pytest.mark.asyncio
async def test_names_opt_in_and_picker_search_only_uses_safe_current_labels(http):
    http.responses = [(200, [domain()]), (200, [link()]), (200, [link()]), (200, [domain()])]
    out = await ad.DubNode.load_field_options("link_id", credential(), context={"domain_id": "domain_a", "include_names": True, "workspaceId": "forged", "organization_id": OWNER}, search="private-name")
    assert out["options"][0]["value"] == "link_a" and out["options"][0]["metadata"]["domain_id"] == "domain_a"
    assert "private-sentinel" not in json.dumps(out) and out["next_page_token"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 302, 204])
async def test_static_provider_failure_no_retry_or_private_body(http, status):
    http.responses = [(status, {"message": "synthetic-test-key private-sentinel"})]
    out = await make_node("list_domains").execute({})
    assert out["status"] == "error" and out["http_status"] == status and len(http.calls) == 1
    assert "private-sentinel" not in json.dumps(out) and "synthetic-test-key" not in json.dumps(out)


@pytest.mark.asyncio
async def test_saved_key_rechecked_through_staging_resolver(http, monkeypatch):
    resolve = AsyncMock(return_value=credential())
    monkeypatch.setattr("utils.credentials.resolve_credential_with_owner_fallback", resolve)
    authority = dict(credential_id=CID, user_id=USER, pool=object(), org_id=ORG, workflow_id=WF)
    current = ad._CurrentCredential(credential(), authority)
    http.responses = [(200, [domain()]), (200, [domain()])]
    result = await ad.DubNode._dispatch(current, ad.DubDomainsConfig())
    assert result["status"] == "success" and resolve.await_count == 4
    assert all(call.kwargs == authority for call in resolve.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement", [None, credential(api_key="changed-key"), credential(credential_type="foreign")])
async def test_saved_key_change_or_denial_stops_before_provider(http, monkeypatch, replacement):
    monkeypatch.setattr("utils.credentials.resolve_credential_with_owner_fallback", AsyncMock(return_value=replacement))
    current = ad._CurrentCredential(credential(), {})
    result = await ad.DubNode._dispatch(current, ad.DubDomainsConfig())
    assert result["status"] == "error" and http.calls == []


@pytest.mark.asyncio
async def test_saved_key_change_during_request_stops_before_second_request(http, monkeypatch):
    resolve = AsyncMock(side_effect=[credential(), credential(api_key="changed-key")])
    monkeypatch.setattr("utils.credentials.resolve_credential_with_owner_fallback", resolve)
    http.responses = [(200, [domain()])]
    result = await ad.DubNode._dispatch(ad._CurrentCredential(credential(), {}), ad.DubDomainsConfig())
    assert result["status"] == "error" and len(http.calls) == 1 and "data" not in result


@pytest.mark.asyncio
async def test_nonrotating_api_key_hook():
    assert await ad.DubNode.freshen_credential(credential()) == credential()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [(200, True), (401, False), (403, None)])
async def test_access_probe_preserves_reachability_and_tristate(http, status, expected):
    http.responses = [(200, [domain()]), (200, [domain()])] if status == 200 else [(status, {"error": "private-sentinel"})]
    result = await ad.DubNode.validate_credential_access(credential())
    assert result["valid"] is expected and "private-sentinel" not in json.dumps(result)


@pytest.mark.parametrize("operation,model,extra", [
    ("list_links", "DubLinksConfig", {}),
    ("get_link", "DubLinkConfig", {"link_id": "link_a"}),
])
@pytest.mark.parametrize("cursors,valid", [
    ({}, True),
    ({"starting_after": None, "ending_before": None}, True),
    ({"starting_after": "link_a"}, True),
    ({"ending_before": "link_b"}, True),
    ({"starting_after": None, "ending_before": "link_b"}, True),
    ({"starting_after": "link_a", "ending_before": None}, True),
    ({"starting_after": "link_a", "ending_before": "link_b"}, False),
])
def test_cursor_schema_matches_runtime_validation(operation, model, extra, cursors, valid):
    from jsonschema import Draft202012Validator
    schema = ad.DubNode.get_config_schema()
    validator = Draft202012Validator({"$ref": "#/$defs/" + model, "$defs": schema["$defs"]})
    config = {"operation": operation, "domain_id": "domain_a", **extra, **cursors}
    assert validator.is_valid(config) is valid
    if valid:
        make_node(operation, domain_id="domain_a", **extra, **cursors)
    else:
        with pytest.raises(ValueError, match="never both"):
            make_node(operation, domain_id="domain_a", **extra, **cursors)
