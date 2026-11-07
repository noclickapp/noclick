"""UNRUN real factory/run/collector/picker seams; repository/HTTP boundaries only."""
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict
import json
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.connection_evidence import collect_evidence
from nodes.pulumi_node import PulumiNode, _credential

TYPE = "automation-pulumi"
USER, KEY = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
RAW = {"credential_type": "pulumi_access_token", "access_token": "synthetic-pulumi-secret", "organization": "studio", "project": "infra"}
PARENTS = {"project_name": "infra", "stack_name": "dev"}
STACK_ROW = {"id": "studio/infra/dev", "orgName": "studio", "projectName": "infra", "stackName": "dev", "lastUpdate": 1770000000, "resourceCount": 4, "links": {"self": "https://PRIVATE.test"}}
DETAIL = {**STACK_ROW, "version": 3, "activeUpdate": "PRIVATE", "config": {"secret": "PRIVATE"}, "tags": {"owner": "PRIVATE"}, "secretsProvider": "PRIVATE", "encryptedKey": "PRIVATE", "encryptionSalt": "PRIVATE", "environment": "PRIVATE", "currentOperation": {"author": {"name": "PRIVATE"}, "kind": "preview", "started": 1770000001}}
CATALOG = {"stacks": [STACK_ROW], "continuationToken": None}
ROOT = "/api/stacks/studio/infra/dev"
ROWS = {"/api/user/stacks": CATALOG, ROOT: DETAIL, ROOT + "/resources/count": {"version": 3, "resourceCount": 4}, ROOT + "/downstreamreferences": {"referencedStacks": [{"organization": "studio", "routingProject": "other-project", "name": "consumer", "version": 9}, {"organization": "PRIVATE-org", "routingProject": "PRIVATE-project", "name": "PRIVATE-name", "version": 2}]}}


@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], {}
    def handle(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "api.pulumi.com" and request.url.scheme == "https"
        assert request.headers["Authorization"] == "token " + RAW["access_token"]
        assert request.headers["Accept"] == "application/vnd.pulumi+8" and request.headers["Content-Type"] == "application/json"
        assert not request.content and RAW["access_token"] not in str(request.url)
        path = request.url.path; assert path in ROWS
        if path == "/api/user/stacks":
            params = dict(request.url.params)
            assert params.pop("organization") == "studio" and params.pop("project") == "infra"
            assert 1 <= int(params.pop("maxResults")) <= 100
            assert not set(params) - {"continuationToken"}
        else: assert not request.url.params
        reply = replies.get(path, (200, deepcopy(ROWS[path])))
        if callable(reply): reply = reply(request)
        if isinstance(reply, Exception): raise reply
        code, payload, *extra = reply
        headers = {"Content-Type": "application/vnd.pulumi+8", "Link": '<https://PRIVATE.test/?token=PRIVATE>; rel="next"'}
        if extra: headers.update(extra[0])
        return httpx.Response(code, content=payload if isinstance(payload, bytes) else json.dumps(payload).encode(), headers=headers)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as instance: yield instance
    monkeypatch.setattr("nodes.pulumi_node.guarded_async_client", client)
    return calls, replies


async def run(operation, **arguments):
    return await run_node_operation(node_type=TYPE, operation=operation, arguments=arguments, credential_data=deepcopy(RAW), user_id=USER)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args", [("list_stacks", {}), ("get_stack", PARENTS), ("get_resource_count", PARENTS), ("list_downstream_references", PARENTS)])
async def test_actual_four_factory_operations_headers_ancestry_and_private_projection(transport, operation, args):
    result = await run(operation, **args)
    assert result["status"] == "success" and result["protected_reachability_verified"]
    assert not result["mutation_attempted"] and not result["snapshot_stable"] and not result["principal_identity_proven"] and not result["organization_ownership_proven"]
    assert all(value not in json.dumps(result) for value in ("PRIVATE", RAW["access_token"], "studio/infra/dev", '"orgName"', "config", "encryptedKey", "author", "activeUpdate", "environment"))
    if operation == "get_resource_count": assert result["data"] == {"resource_type": "stack_resource_count", "resourceCount": 4, "version": 3}
    if operation == "list_downstream_references":
        assert result["provider_returned_count"] == 2 and result["same_organization_returned_count"] == 1
        assert result["data"] == [{"resource_type": "downstream_stack_reference", "version": 9}]
        assert result["referenced_resource_access_proven"] is False and result["pagination_complete"] is None
        assert not any("other-project" in str(r.url) for r in transport[0])


@pytest.mark.asyncio
async def test_actual_factory_config_lens_raw_witness_and_connect_collector(transport):
    node = NodeFactory.create_node("fixture", TYPE, {"credentials": RAW, "config": {"operation": "get_stack", **PARENTS, "label": "Saved canvas", "disabled": False}}, user_id=USER)
    assert (await node.execute({}))["data"]["version"] == 3
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=deepcopy(RAW))
    assert evidence.reachable is True and PulumiNode.connection_evidence.proves == "reachability" and not evidence.account_label
    assert "PRIVATE" not in json.dumps(asdict(evidence))
    node.node_data["credentials"] = {**RAW, "credential_type": "foreign"}; transport[0].clear()
    with pytest.raises(ValueError): await node.execute({})
    assert not transport[0]


@pytest.mark.asyncio
async def test_empty_catalog_is_scoped_access_and_not_global_stack_absence(transport):
    calls, replies = transport; replies["/api/user/stacks"] = (200, {"stacks": [], "continuationToken": None})
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=RAW)
    assert evidence.reachable is True and not evidence.account_label
    assert (await run("get_stack", **PARENTS))["status"] == "error"
    assert not any(r.url.path == ROOT for r in calls)


@pytest.mark.asyncio
async def test_names_opt_in_picker_parent_and_cross_project_references(transport):
    calls, _ = transport
    for field, context in (("project_name", {}), ("stack_name", {"include_names": True}), ("stack_name", {"include_names": True, "project_name": "foreign"})):
        with pytest.raises(ValueError): await PulumiNode.load_field_options(field, RAW, context=context)
    assert not calls
    picker = await PulumiNode.load_field_options("stack_name", RAW, context={"include_names": True, "project_name": "infra"})
    assert [row["value"] for row in picker["options"]] == ["dev"] and picker["has_more"] is False
    result = await run("list_downstream_references", **PARENTS, include_names=True)
    assert result["data"] == [{"resource_type": "downstream_stack_reference", "organization": "studio", "routingProject": "other-project", "name": "consumer", "version": 9}]
    assert "PRIVATE" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("token,expected", [(None, (False, True)), ("opaque-next", (True, False)), ("absent", (None, None))])
async def test_documented_cursor_nil_vs_string_and_omission(transport, token, expected):
    payload = {"stacks": [STACK_ROW]}
    if token != "absent": payload["continuationToken"] = token
    transport[1]["/api/user/stacks"] = (200, payload)
    result = await run("list_stacks", max_results=1, continuation_token="prior-cursor")
    assert result["status"] == "success" and (result["has_more"], result["pagination_complete"]) == expected
    assert transport[0][-1].url.params["continuationToken"] == "prior-cursor"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"stacks": [] , "continuationToken": ""}, {"stacks": [STACK_ROW], "continuationToken": 1}, {"stacks": [STACK_ROW] * 21}, {"stacks": [{**STACK_ROW, "id": "foreign/infra/dev"}]}, {"stacks": [{**STACK_ROW, "resourceCount": True}]}, {"stacks": [STACK_ROW], "continuationToken": "https://PRIVATE.test"}])
async def test_published_wrapper_bounds_logical_id_and_no_cursor_urls(transport, payload):
    transport[1]["/api/user/stacks"] = (200, payload)
    result = await run("list_stacks")
    assert result["status"] == "error" and "data" not in result and len(transport[0]) == 1


@pytest.mark.asyncio
async def test_detail_current_operation_null_and_parent_version_races(transport):
    calls, replies = transport; replies[ROOT] = (200, {**DETAIL, "currentOperation": None})
    assert (await run("get_stack", **PARENTS))["data"]["currentOperation"] is None
    replies[ROOT + "/resources/count"] = (200, {"version": 4, "resourceCount": 4})
    assert (await run("get_resource_count", **PARENTS))["status"] == "error"
    replies.clear(); calls.clear()
    def changed(request): return 200, {**DETAIL, "version": 4 if sum(r.url.path == ROOT for r in calls) >= 2 else 3}
    replies[ROOT] = changed
    assert (await run("get_resource_count", **PARENTS))["status"] == "error"
    replies[ROOT] = (200, {**DETAIL, "orgName": "other"})
    calls.clear()
    assert (await run("list_downstream_references", **PARENTS))["status"] == "error"
    assert not any(r.url.path.endswith("downstreamreferences") for r in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [401, 404, 429, 204, httpx.ReadTimeout("synthetic"), b"x" * (2 * 1024 * 1024 + 1), (200, CATALOG, {"Content-Type": "text/plain"})])
async def test_private_errors_transport_limits_and_no_retry(transport, reply):
    calls, replies = transport
    replies["/api/user/stacks"] = reply if isinstance(reply, (Exception, tuple)) else (reply, b"PRIVATE") if isinstance(reply, int) else (200, reply)
    result = await run("list_stacks")
    assert result["status"] == "error" and "data" not in result and len(calls) == 1 and "PRIVATE" not in json.dumps(result)
    if reply == 404: assert "missing-or-invisible" in result["error"]


def test_raw_family_fixed_host_and_four_closed_native_schema_operations():
    for patch in ({"credential_type": "foreign"}, {"organization": "../studio"}, {"organization": "https://evil.test"}, {"project": "nested/path"}, {"access_token": "token secret"}, {"host": "evil.test"}, {"refresh_token": "secret"}, {"token_version": True}):
        with pytest.raises(ValueError): _credential({**RAW, **patch})
    schema = PulumiNode.get_config_schema()
    ops = {schema["$defs"][r["$ref"].split("/")[-1]]["properties"]["operation"]["const"] for r in schema["properties"]["config"]["oneOf"]}
    assert ops == {"list_stacks", "get_stack", "get_resource_count", "list_downstream_references"}
    for field in ("roleID", "tagName", "tags", "config", "url", "body", "resources", "outputs", "requestedByToken"): assert field not in schema["$defs"]["PulumiResourceCountConfig"]["properties"]
