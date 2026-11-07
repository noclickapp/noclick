"""Scalr factory, operation, evidence, picker and JSON:API privacy tests."""
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict
import json
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.connection_evidence import collect_evidence
from nodes.scalr_node import ScalrNode, ATTRIBUTES, RELATIONSHIPS, _credential

TYPE = "automation-scalr"
USER, KEY = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
ACCOUNT, ENV, WORKSPACE, RUN = "acc-fixture", "env-fixture", "ws-fixture", "run-fixture"
RAW = {"credential_type": "scalr_token", "access_token": "synthetic-scalr-secret", "tenant_host": "fixture.scalr.io", "account_id": ACCOUNT, "account_catalog_page": 1}
PARENTS = {"account_id": ACCOUNT, "environment_id": ENV, "workspace_id": WORKSPACE}


def row(kind, identifier, **relationships):
    return {"type": kind, "id": identifier, "attributes": {"created-at": "2026-01-01T00:00:00Z", "name": "Opt-in name", "status": "pending" if kind == "runs" else "active", "locked": False, "iac-platform": "terraform", "terraform-version": "1.10.0", "inputs": [{"value": "PRIVATE"}], "variables": [{"value": "PRIVATE"}], "error-message": "PRIVATE", "message": "PRIVATE", "vcs-repo": {"identifier": "PRIVATE"}, "hooks": {"pre-plan": "PRIVATE"}, "permissions": {"PRIVATE": True}}, "relationships": {**{key: {"data": {"type": value[0], "id": value[1]}} for key, value in relationships.items()}, "owner": {"data": {"type": "users", "id": "PRIVATE"}}}, "links": {"self": "https://PRIVATE.test"}}


ROWS = {"accounts": row("accounts", ACCOUNT), "environments": row("environments", ENV, account=("accounts", ACCOUNT)), "workspaces": row("workspaces", WORKSPACE, environment=("environments", ENV)), "runs": row("runs", RUN, environment=("environments", ENV), workspace=("workspaces", WORKSPACE))}


@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], {}
    def handle(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == RAW["tenant_host"] and request.url.scheme == "https"
        assert request.headers["Authorization"] == "Bearer " + RAW["access_token"] and request.headers["Accept"] == "application/vnd.api+json"
        assert not request.content and RAW["access_token"] not in str(request.url)
        path = request.url.path.removeprefix("/api/iacp/v3/")
        kind, *identifier = path.split("/")
        assert kind in ROWS and not (kind == "accounts" and identifier)
        fields = request.url.params[f"fields[{kind}]"].split(",")
        assert set(fields) in (set(ATTRIBUTES[kind] + RELATIONSHIPS[kind]), set(ATTRIBUTES[kind] + RELATIONSHIPS[kind] + (() if kind == "runs" else ("name",))))
        assert "include" not in request.url.params and not any(k in fields for k in ("inputs", "variables", "owner", "permissions", "message", "error-message"))
        if kind == "environments" and identifier: assert request.url.params["track_access"] == "false"
        if not identifier:
            assert request.url.params["page[number]"].isdigit() and request.url.params["page[size]"].isdigit()
            if kind != "accounts": assert request.url.params["filter[account]"] == ACCOUNT
            if kind in {"workspaces", "runs"}: assert request.url.params["filter[environment]"] == ENV
            if kind == "runs": assert request.url.params["filter[workspace]"] == WORKSPACE
        default = {"data": deepcopy(ROWS[kind]) if identifier else [deepcopy(ROWS[kind])], "included": [{"credentials": "PRIVATE"}], "meta": {"pagination": {"total-count": 9999, "next-page": "PRIVATE"}}, "links": {"next": "https://PRIVATE.test"}}
        reply = replies.get(path, (200, default))
        if callable(reply): reply = reply(request)
        if isinstance(reply, Exception): raise reply
        code, payload = reply
        return httpx.Response(code, content=payload if isinstance(payload, bytes) else json.dumps(payload).encode())
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as instance: yield instance
    monkeypatch.setattr("nodes.scalr_node.guarded_async_client", client)
    return calls, replies


async def run(operation, **arguments):
    return await run_node_operation(node_type=TYPE, operation=operation, arguments=arguments, credential_data=deepcopy(RAW), user_id=USER)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args", [("list_accounts", {}), ("list_environments", {"account_id": ACCOUNT}), ("get_environment", {"account_id": ACCOUNT, "environment_id": ENV}), ("list_workspaces", {"account_id": ACCOUNT, "environment_id": ENV}), ("get_workspace", PARENTS), ("list_runs", PARENTS), ("get_run", {**PARENTS, "run_id": RUN})])
async def test_all_seven_actual_native_operations_sparse_fields_ancestry_and_privacy(transport, operation, args):
    result = await run(operation, **args)
    assert result["status"] == "success" and result["protected_reachability_verified"] and not result["snapshot_stable"]
    assert not result["mutation_attempted"] and not result["principal_identity_proven"] and not result["tenant_ownership_proven"]
    assert "PRIVATE" not in json.dumps(result) and "Opt-in" not in json.dumps(result) and RAW["access_token"] not in json.dumps(result)
    if operation.startswith("list_"):
        assert result["returned_count"] == 1 and result["total_count"] is None and result["has_more"] is None and result["pagination_complete"] is None


@pytest.mark.asyncio
async def test_factory_execute_config_lens_and_actual_protected_collector(transport):
    node = NodeFactory.create_node("fixture", TYPE, {"credentials": RAW, "config": {"operation": "list_accounts", "label": "Saved canvas"}}, user_id=USER)
    assert (await node.execute({}))["status"] == "success"
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=deepcopy(RAW))
    assert evidence.reachable is True and ScalrNode.connection_evidence.proves == "reachability" and not evidence.account_label
    assert "PRIVATE" not in json.dumps(asdict(evidence))


@pytest.mark.asyncio
async def test_real_dependent_pickers_no_parent_no_http_and_no_link_following(transport):
    calls, _ = transport
    with pytest.raises(ValueError): await ScalrNode.load_field_options("workspace_id", RAW, {"account_id": ACCOUNT})
    assert not calls
    options = await ScalrNode.load_field_options("run_id", RAW, PARENTS)
    assert options["options"] == [{"value": RUN, "label": RUN, "metadata": {"resource_type": "runs", "environment_id": ENV, "workspace_id": WORKSPACE}}]
    assert options["has_more"] is None and options["next_page_token"] is None
    result = await run("list_workspaces", account_id=ACCOUNT, environment_id=ENV, page=2, include_names=True)
    assert result["data"][0]["name"] == "Opt-in name"
    assert any(c.url.params.get("page[number]") == "2" for c in calls)


@pytest.mark.asyncio
async def test_empty_catalog_wrong_types_cross_parent_and_current_move_refuse(transport):
    calls, replies = transport
    replies["accounts"] = (200, {"data": []})
    assert (await collect_evidence(node_type=TYPE, user_id=USER, credential_data=RAW)).reachable is None
    replies.clear(); calls.clear()
    result = await run("list_environments", account_id="acc-other")
    assert result["status"] == "error" and not calls
    for kind, config, args, relation in [("environments", "get_environment", {"account_id": ACCOUNT, "environment_id": ENV}, "account"), ("workspaces", "get_workspace", PARENTS, "environment"), ("runs", "get_run", {**PARENTS, "run_id": RUN}, "workspace")]:
        replies.clear(); calls.clear(); mutated = deepcopy(ROWS[kind]); mutated["relationships"][relation]["data"]["id"] = "outside"
        replies[kind + "/" + mutated["id"]] = (200, {"data": mutated})
        result = await run(config, **args)
        assert result["status"] == "error" and "data" not in result
    replies.clear(); calls.clear()
    def moved(request):
        changed = deepcopy(ROWS["workspaces"])
        if sum(c.url.path.endswith("/workspaces/" + WORKSPACE) for c in calls) >= 3: changed["relationships"]["environment"]["data"]["id"] = "outside"
        return 200, {"data": changed}
    replies["workspaces/" + WORKSPACE] = moved
    assert (await run("get_workspace", **PARENTS))["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [401, 403, 404, 429, 204, {"data": {}}, {"data": [{"type": "users", "id": "acc-fixture"}]}, httpx.ReadTimeout("synthetic"), b"x" * (2 * 1024 * 1024 + 1)])
async def test_unknown_or_auth_denial_private_body_no_retry(transport, reply):
    calls, replies = transport
    replies["accounts"] = reply if isinstance(reply, Exception) else (reply, b"PRIVATE") if isinstance(reply, int) else (200, reply)
    result = await run("list_accounts")
    assert result["status"] == "error" and "data" not in result and len(calls) == 1 and "PRIVATE" not in json.dumps(result)
    if reply == 404: assert "ambiguous" in result["error"]


def test_literal_family_tenant_and_raw_grant_before_base_reconciliation():
    for change in ({"credential_type": "foreign"}, {"access_token": "Bearer synthetic"}, {"tenant_host": "https://fixture.scalr.io"}, {"tenant_host": "fixture.scalr.io.evil.test"}, {"tenant_host": "nested.fixture.scalr.io"}, {"tenant_host": "localhost"}, {"account_id": True}, {"account_id": "../users"}, {"account_catalog_page": True}, {"refresh_token": "synthetic"}, {"expires_at": "synthetic"}, {"token_version": True}):
        with pytest.raises(ValueError): _credential({**RAW, **change})
    with pytest.raises(ValueError): ScalrNode.parse_config({"credentials": {**RAW, "credential_type": "foreign"}, "config": {"operation": "list_accounts"}})


def test_documented_run_without_environment_relationship():
    from pathlib import Path
    from nodes.scalr_node import _resource
    document = json.loads((Path(__file__).parent / "fixtures/scalr/get-run.json").read_text())
    resource = _resource(document["data"], "runs")
    assert resource["workspace_id"] == "ws-t61fnk5nffoujpg"
    assert resource["status"] == "applied"
    assert "environment_id" not in resource
    assert "inputs" not in resource and "message" not in resource


@pytest.mark.asyncio
async def test_run_environment_can_be_established_through_verified_workspace(transport):
    _, replies = transport
    document = deepcopy(ROWS["runs"])
    document["relationships"].pop("environment")
    replies["runs/" + RUN] = (200, {"data": document})
    result = await run("get_run", **PARENTS, run_id=RUN)
    assert result["status"] == "success"
    assert result["data"]["environment_id"] == ENV
    document["relationships"]["workspace"]["data"]["id"] = "ws-outside"
    assert (await run("get_run", **PARENTS, run_id=RUN))["status"] == "error"
