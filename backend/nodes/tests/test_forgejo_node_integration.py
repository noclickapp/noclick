"""UNRUN actual Forgejo factory/run/collector/picker source; HTTP boundary mocked."""
from contextlib import asynccontextmanager
from copy import deepcopy
import json
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.forgejo_node import ForgejoNode, _credential

TYPE = "automation-forgejo"
USER, KEY = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
RAW = {"credential_type": "forgejo_pat", "access_token": "synthetic-forgejo-secret", "instance_url": "https://forgejo.example.test"}
ACTOR = {"id": 7, "login": "PRIVATE-actor", "email": "PRIVATE", "avatar_url": "PRIVATE", "is_admin": True, "full_name": "PRIVATE"}
REPO = {"id": 11, "owner": {"login": "PRIVATE-organization", "email": "PRIVATE"}, "name": "PRIVATE-repository", "full_name": "PRIVATE-organization/PRIVATE-repository", "private": True, "archived": False, "fork": False, "mirror": False, "empty": False, "open_issues_count": 1, "size": 99, "created_at": "2026-01-01T00:00:00Z", "description": "PRIVATE", "permissions": {"admin": True}, "ssh_url": "PRIVATE", "parent": {"secret": "PRIVATE"}}
PARENTS = {"owner": REPO["owner"]["login"], "repo_name": REPO["name"]}
ISSUE = {"id": 33, "number": 2, "state": "open", "is_locked": False, "created_at": "2026-01-01T00:00:00Z", "title": "PRIVATE-title", "body": "PRIVATE", "user": ACTOR, "assignees": [ACTOR], "labels": [{"name": "PRIVATE"}], "repository": {"id": 11, "owner": PARENTS["owner"], "name": PARENTS["repo_name"]}, "pull_request": None, "url": "PRIVATE"}
IARGS = {**PARENTS, "issue_index": 2}
ROOT, CATALOG = "/api/v1/user", "/api/v1/user/repos"
RPATH = "/api/v1/repos/PRIVATE-organization/PRIVATE-repository"
IPATH = RPATH + "/issues"
ROWS = {ROOT: ACTOR, CATALOG: [REPO], RPATH: REPO, IPATH: [ISSUE], IPATH + "/2": ISSUE}


@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], {}
    def handle(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "forgejo.example.test" and request.url.scheme == "https"
        assert request.headers["Authorization"] == "token " + RAW["access_token"] and request.headers["Accept"] == "application/json"
        assert not request.content and RAW["access_token"] not in str(request.url)
        for forbidden in ("Sudo", "X-Gitea-OTP"): assert forbidden not in request.headers
        path = request.url.path; assert path in ROWS
        params = dict(request.url.params)
        if path in {CATALOG, IPATH}:
            assert set(params) == ({"page", "limit"} if path == CATALOG else {"page", "limit", "state", "type"})
            assert 1 <= int(params["page"]) and 1 <= int(params["limit"]) <= 100
            if path == IPATH: assert params["type"] == "issues" and params["state"] in {"open", "closed", "all"}
        else: assert not params
        reply = replies.get(path, (200, deepcopy(ROWS[path])))
        if callable(reply): reply = reply(request)
        if isinstance(reply, Exception): raise reply
        code, payload, *extra = reply
        headers = {"Content-Type": "application/json", "Link": '<https://PRIVATE.test/?token=PRIVATE>; rel="next"'}
        if path == CATALOG: headers["X-Total-Count"] = "1"
        if extra: headers.update(extra[0])
        return httpx.Response(code, content=payload if isinstance(payload, bytes) else json.dumps(payload).encode(), headers=headers)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as instance: yield instance
    monkeypatch.setattr("nodes.forgejo_node.guarded_async_client", client)
    return calls, replies


async def run(operation, **arguments):
    return await run_node_operation(node_type=TYPE, operation=operation, arguments=arguments, credential_data=deepcopy(RAW), user_id=USER)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args", [("get_user", {}), ("list_repositories", {}), ("get_repository", PARENTS), ("list_issues", PARENTS), ("get_issue", IARGS)])
async def test_actual_five_factory_operations_header_shapes_privacy_and_foreign_owner_access(transport, operation, args):
    result = await run(operation, **args)
    assert result["status"] == "success" and result["protected_authentication_verified"] and result["principal_identity_proven"]
    assert not result["mutation_attempted"] and not result["snapshot_stable"] and not result["repository_ownership_proven"]
    assert "PRIVATE" not in json.dumps(result) and RAW["access_token"] not in json.dumps(result)
    assert transport[0][0].url.path == ROOT and transport[0][-1].url.path == ROOT
    if operation.startswith("list_"):
        assert result["pagination_complete"] is None and result["has_more"] is None and result["next_page_token"] is None
        assert result["link_header_present"] is True
    if operation == "list_issues": assert result["reported_total"] is None and result["data"][0]["number"] == 2
    if operation == "list_repositories": assert result["reported_total"] == 1


@pytest.mark.asyncio
async def test_actual_config_lens_and_raw_witness(transport):
    node = NodeFactory.create_node("fixture", TYPE, {"credentials": RAW, "config": {"operation": "get_user", "label": "Saved canvas", "disabled": False}}, user_id=USER)
    assert (await node.execute({}))["data"] == {"id": 7}
    node.node_data["credentials"] = {**RAW, "credential_type": "foreign"}; transport[0].clear()
    with pytest.raises(ValueError): await node.execute({})
    assert not transport[0]


@pytest.mark.asyncio
async def test_empty_actor_never_authentication_and_empty_catalog_never_owner_or_absence_proof(transport):
    calls, replies = transport; replies[ROOT] = (200, {})
    result = await run("get_repository", **PARENTS)
    assert result["status"] == "error" and "data" not in result and [r.url.path for r in calls] == [ROOT]
    calls.clear(); replies.clear(); replies[CATALOG] = (200, [])
    result = await run("list_repositories")
    assert result["status"] == "success" and result["data"] == [] and not result["repository_ownership_proven"]
    assert (await run("get_repository", **PARENTS))["status"] == "error"
    assert not any(r.url.path == RPATH for r in calls)


@pytest.mark.asyncio
async def test_opt_in_routing_name_picker_and_numeric_issue_picker_no_automatic_continuation(transport):
    calls, _ = transport
    assert (await ForgejoNode.load_field_options("owner", RAW))["options"] == [] and not calls
    picker = await ForgejoNode.load_field_options("repo_name", RAW, context={"owner": PARENTS["owner"], "include_names": True}, page_token="2")
    assert picker["options"][0]["value"] == PARENTS["repo_name"] and picker["has_more"] is None and picker["next_page_token"] is None
    assert any(r.url.params.get("page") == "2" for r in calls)
    picker = await ForgejoNode.load_field_options("issue_index", RAW, context=PARENTS)
    assert picker["options"][0]["value"] == "2" and picker["options"][0]["label"] == "2"
    for token in ("0", "https://PRIVATE.test", "9999999999"):
        with pytest.raises(ValueError): await ForgejoNode.load_field_options("issue_index", RAW, context=PARENTS, page_token=token)


@pytest.mark.asyncio
@pytest.mark.parametrize("route,patch", [(RPATH, {"id": 12}), (IPATH + "/2", {"id": 34}), (IPATH + "/2", {"number": 3}), (IPATH + "/2", {"repository": {"id": 99}}), (IPATH + "/2", {"pull_request": {}})])
async def test_independent_current_repository_issue_ancestry_and_pull_rejection(transport, route, patch):
    transport[1][route] = (200, {**ROWS[route], **patch})
    result = await run("get_issue", **IARGS)
    assert result["status"] == "error" and "data" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("race", ["actor", "repository", "issue"])
async def test_after_read_actor_parent_and_issue_catalog_races_discard_output(transport, race):
    calls, replies = transport
    if race == "actor": replies[ROOT] = lambda r: (200, {**ACTOR, "id": 8} if sum(c.url.path == ROOT for c in calls) > 1 else ACTOR)
    if race == "repository": replies[CATALOG] = lambda r: (200, [] if sum(c.url.path == CATALOG for c in calls) > 1 else [REPO])
    if race == "issue": replies[IPATH] = lambda r: (200, [] if sum(c.url.path == IPATH for c in calls) > 1 else [ISSUE])
    assert (await run("get_issue", **IARGS))["status"] == "error"


@pytest.mark.asyncio
async def test_missing_optional_parent_not_fabricated_and_undocumented_null_timestamp_rejected(transport):
    transport[1][IPATH] = (200, [{k: v for k, v in ISSUE.items() if k != "repository"}])
    result = await run("list_issues", **PARENTS)
    assert result["status"] == "success" and "repository" not in result["data"][0]
    transport[1][IPATH] = (200, [{**ISSUE, "closed_at": None}])
    assert (await run("list_issues", **PARENTS))["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"repositories": [REPO]}, [REPO] * 21, [{**REPO, "id": True}], [{**REPO, "private": 1}], [{**REPO, "created_at": None}], [{**REPO, "id": 2**53}]])
async def test_bare_array_local_scalar_and_page_bounds(transport, payload):
    transport[1][CATALOG] = (200, payload)
    result = await run("list_repositories")
    assert result["status"] == "error" and "data" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [401, 403, 404, 429, 204, httpx.ReadTimeout("synthetic"), b"x" * (2 * 1024 * 1024 + 1), (200, ACTOR, {"Content-Type": "text/plain"})])
async def test_private_errors_transport_bounds_and_no_retry(transport, reply):
    calls, replies = transport
    replies[ROOT] = reply if isinstance(reply, (Exception, tuple)) else (reply, b"PRIVATE") if isinstance(reply, int) else (200, reply)
    result = await run("get_user")
    assert result["status"] == "error" and "data" not in result and len(calls) == 1 and "PRIVATE" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("header", ["-1", "1.0", "true", "9007199254740992"])
async def test_total_header_not_coerced_or_followed(transport, header):
    transport[1][CATALOG] = (200, [REPO], {"X-Total-Count": header})
    assert (await run("list_repositories"))["status"] == "error"


def test_raw_family_public_origin_and_five_closed_schema_operations():
    assert _credential(RAW).instance_url == RAW["instance_url"]
    assert _credential({**RAW, "instance_url": "https://FORGEJO.example.test:443/"}).instance_url == RAW["instance_url"]
    for patch in ({"credential_type": "foreign"}, {"instance_url": "https://127.0.0.1"}, {"instance_url": "https://forgejo.example.test/api/v1"}, {"instance_url": "https://user@forgejo.example.test"}, {"access_token": "Bearer secret"}, {"refresh_token": "secret"}, {"token_version": True}, {"sudo": "other"}):
        with pytest.raises(ValueError): _credential({**RAW, **patch})
    schema = ForgejoNode.get_config_schema()
    ops = {schema["$defs"][r["$ref"].split("/")[-1]]["properties"]["operation"]["const"] for r in schema["properties"]["config"]["oneOf"]}
    assert ops == {"get_user", "list_repositories", "get_repository", "list_issues", "get_issue"}
    for field in ("body", "labels", "assignees", "url", "headers", "detailed", "q", "token", "sudo", "pull_request"): assert field not in schema["$defs"]["ForgejoIssueConfig"]["properties"]


@pytest.mark.asyncio
async def test_forgejo_refuses_private_outbound_opt_out(transport, monkeypatch):
    monkeypatch.setenv("OUTBOUND_ALLOW_PRIVATE_IPS", "true")
    result = await run("get_user")
    assert result["status"] == "error" and "data" not in result
    assert not transport[0]
