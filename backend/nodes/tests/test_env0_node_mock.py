"""Env zero wire, parent-chain and privacy regressions.

Factory, dispatcher, connect and schema seams use synthetic HTTP boundaries.
"""
from copy import deepcopy
import base64
import json
from types import SimpleNamespace
import httpx
import pytest
from nodes import env0_node as p
from nodes.core.registry import NodeFactory, NODE_REGISTRY
from nodes.core.run_op import run_node_operation

USER = "00000000-0000-4000-8000-000000000001"
ORG, PROJECT, ENV, DEPLOYMENT, FOREIGN = "org_123", "project_123", "environment_123", "deployment_123", "foreign_999"
PRIVATE = "SYNTHETIC_PRIVATE_MARKER"
TIME = "2026-10-07T04:00:00.000Z"


def blob(**changes):
    approved = {"organizations": [ORG], "projects": [PROJECT], "environments": [ENV], "deployments": [DEPLOYMENT]}
    return {"credential_type": p.FAMILY, "api_key_id": "synthetic-key-id", "api_key_secret": "synthetic-key:secret",
            "approved_resources_json": json.dumps(approved), "include_labels": False, **changes}


def org(uid=ORG):
    return {"id": uid, "createdAt": TIME, "updatedAt": TIME, "name": PRIVATE, "description": PRIVATE,
        "createdBy": PRIVATE, "role": PRIVATE, "mode": PRIVATE, "photoUrl": PRIVATE, "ipAllowlist": [PRIVATE],
        "projectCustomFlowsPolicy": PRIVATE, "enableOidc": True, "trialEnd": PRIVATE}


def project(uid=PROJECT, parent=ORG):
    return {"id": uid, "organizationId": parent, "isArchived": False, "name": PRIVATE,
        "description": PRIVATE, "createdBy": PRIVATE, "hierarchy": [PRIVATE], "role": PRIVATE,
        "users": [PRIVATE], "settings": PRIVATE, "tags": PRIVATE}


def environment(uid=ENV, org_id=ORG, project_id=PROJECT):
    return {"id": uid, "organizationId": org_id, "projectId": project_id, "status": "ACTIVE", "name": PRIVATE,
        "createdAt": TIME, "updatedAt": TIME, "latestDeploymentLog": {"output": PRIVATE, "plan": PRIVATE},
        "user": PRIVATE, "userId": PRIVATE, "workspaceName": PRIVATE, "config": PRIVATE,
        "discoveryRepository": PRIVATE, "variables": PRIVATE, "outputs": PRIVATE, "tags": PRIVATE}


def deployment(uid=DEPLOYMENT, parent=ENV):
    return {"id": uid, "environmentId": parent, "status": "SUCCESS", "type": "deploy", "createdAt": TIME,
        "updatedAt": TIME, "queuedAt": TIME, "startedAt": TIME, "finishedAt": TIME, "output": PRIVATE,
        "error": PRIVATE, "failedCommand": PRIVATE, "customEnv0EnvironmentVariables": PRIVATE,
        "costEstimation": PRIVATE, "resources": PRIVATE, "startedByUser": PRIVATE, "blueprintRepository": PRIVATE,
        "comment": PRIVATE, "git": PRIVATE, "reviewers": PRIVATE, "plan": PRIVATE, "planSummary": PRIVATE,
        "workflow": PRIVATE, "variables": PRIVATE, "providerVersions": PRIVATE, "moduleVersions": PRIVATE,
        "state": PRIVATE, "hash": PRIVATE, "targets": PRIVATE, "link": PRIVATE}


def parents(): return [[org()], org(), [project()], project()]
def env_chain(): return parents() + [environment()]
def option(value): return {"value": value, "label": value, "metadata": {"completion": "unknown", "identity_verified": False}}


@pytest.fixture
def wire(monkeypatch):
    state = SimpleNamespace(queue=[], calls=[], after_headers=None, after_body=None)
    class Response:
        def __init__(self, payload, status, ctype):
            self.status_code, self.headers = status, {"content-type": ctype, "location": PRIVATE}
            self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        async def __aenter__(self):
            if state.after_headers: state.after_headers()
            return self
        async def __aexit__(self, *_): return False
        async def aiter_bytes(self):
            yield self.payload
            if state.after_body: state.after_body()
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *_): return False
        def stream(self, method, url, **kwargs):
            state.calls.append((method, url, deepcopy(kwargs)))
            assert state.queue, "Unexpected request beyond synthetic boundary"
            value = state.queue.pop(0)
            if isinstance(value, BaseException): raise value
            return Response(*value) if isinstance(value, tuple) else Response(value, 200, "application/json")
    def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        return Client()
    monkeypatch.setattr(p, "guarded_async_client", client)
    return state


async def execute(config, data=None, inputs=None):
    node = NodeFactory.create_node("fixture", p.NODE_TYPE, {"config": config, "credentials": data or blob()}, user_id=USER)
    return await node.execute(inputs or {})



@pytest.mark.asyncio
async def test_actual_factory_dispatcher_basic_pair_header_and_no_input_overlay(wire):
    assert NODE_REGISTRY[p.NODE_TYPE] is p.Env0Node
    wire.queue = [[org()], []]
    result = await execute({"operation": "check_connection"}, inputs={"api_key_secret": "spoof", "operation": "apply"})
    assert result["witness_verified"] and not result["identity_verified"] and not result["organization_ownership_verified"]
    result = await run_node_operation(node_type=p.NODE_TYPE, operation="check_connection", arguments={}, user_id=USER, credential_data=blob())
    assert result["witness_verified"] and result["received_count"] == 0 and result["completion"] == "unknown"
    expected = "Basic " + base64.b64encode(b"synthetic-key-id:synthetic-key:secret").decode()
    for method, url, kwargs in wire.calls:
        assert method == "GET" and url == p.ROOT + "/organizations" and kwargs["params"] is None
        assert kwargs["headers"] == {"Authorization": expected, "Accept": "application/json", "Content-Type": "application/json"}
        assert "synthetic-key" not in url


@pytest.mark.asyncio
async def test_actual_connect_empty_bare_catalog_is_only_reachability(wire, monkeypatch):
    from nodes.core import credential_connect as cc
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(cc, "_collect_evidence", collect_evidence)
    wire.queue = [[], {"data": []}]
    result = await cc.validate_for_connect(credential_type=p.FAMILY, credential_data=blob(), user_id=USER)
    assert result.evidence.reachable is True and p.Env0Node.connection_evidence.proves == "reachability" and result.evidence.account_label is None
    assert "verified_as" not in result.verified_metadata()
    unknown = await cc.validate_for_connect(credential_type=p.FAMILY, credential_data=blob(), user_id=USER)
    assert unknown.evidence.reachable is None and not unknown.verified_metadata()


@pytest.mark.asyncio
async def test_all_eight_resource_reads_project_only_metadata(wire):
    org_args = {"organization_id": ORG}
    project_args = {**org_args, "project_id": PROJECT}
    env_args = {**project_args, "environment_id": ENV}
    cases = [({"operation": "list_organizations"}, [[org(), org(FOREIGN)]]),
        ({"operation": "get_organization", **org_args}, [[org()], org()]),
        ({"operation": "list_projects", **org_args, "is_archived": False}, [[org()], org(), [project()]]),
        ({"operation": "get_project", **project_args}, parents()),
        ({"operation": "list_environments", **project_args, "limit": 1, "offset": 7}, parents() + [[environment()]]),
        ({"operation": "get_environment", **env_args}, env_chain()),
        ({"operation": "list_deployments", **env_args, "limit": 1, "offset": 9}, env_chain() + [[deployment()]]),
        ({"operation": "get_deployment", **env_args, "deployment_id": DEPLOYMENT}, env_chain() + [[deployment()], deployment()])]
    for cfg, queue in cases:
        wire.queue = queue
        result = await execute(cfg)
        assert result["status"] == "success" and result["resource_access_verified"] and not result["identity_verified"]
        assert PRIVATE not in json.dumps(result) and not wire.queue
        if cfg["operation"].startswith("list_"):
            assert result["completion"] == "unknown" and not ({"total", "has_more", "next_offset", "page", "next_page"} & result.keys())
    assert {url.removeprefix(p.ROOT) for _, url, _ in wire.calls} == {"/organizations", "/organizations/" + ORG,
        "/projects", "/projects/" + PROJECT, "/environments", "/environments/" + ENV,
        "/environments/" + ENV + "/deployments", "/environments/deployments/" + DEPLOYMENT}
    env_calls = [args for _, url, args in wire.calls if url == p.ROOT + "/environments"]
    assert env_calls[0]["params"] == {"organizationId": ORG, "projectId": PROJECT, "limit": "1", "offset": "7"}
    detail = next(args for _, url, args in wire.calls if url == p.ROOT + "/environments/" + ENV)
    assert detail["params"] == {"fields": p.ENV_FIELDS}
    dep_detail = wire.calls[-1][2]
    assert dep_detail["params"] == {"fields": p.DEPLOYMENT_FIELDS}
    assert not any("fields" in args["params"] for _, url, args in wire.calls if url.endswith("/deployments"))
    assert any(args["params"] == {"organizationId": ORG, "isArchived": "false"} for _, url, args in wire.calls if url == p.ROOT + "/projects")


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["unapproved", "foreign-org", "foreign-project", "foreign-env", "foreign-deployment", "foreign-detail"])
async def test_selected_ids_and_actual_parent_chain_are_required(wire, case):
    cfg = {"operation": "get_deployment", "organization_id": ORG, "project_id": PROJECT, "environment_id": ENV, "deployment_id": DEPLOYMENT}
    queue = env_chain() + [[deployment()], deployment()]
    if case == "unapproved": cfg["deployment_id"] = FOREIGN
    if case == "foreign-org": queue[1] = org(FOREIGN)
    if case == "foreign-project": queue[2] = [project(parent=FOREIGN)]
    if case == "foreign-env": queue[4] = environment(project_id=FOREIGN)
    if case == "foreign-deployment": queue[5] = [deployment(parent=FOREIGN)]
    if case == "foreign-detail": queue[6] = deployment(parent=FOREIGN)
    wire.queue = queue
    with pytest.raises((ValueError, RuntimeError)): await execute(cfg)
    assert len(wire.calls) == {"unapproved": 0, "foreign-org": 2, "foreign-project": 3, "foreign-env": 5, "foreign-deployment": 6, "foreign-detail": 7}[case]


@pytest.mark.asyncio
async def test_bounded_deployment_witness_never_claims_short_page_completion(wire):
    wire.queue = env_chain() + [[]] * 5
    cfg = {"operation": "get_deployment", "organization_id": ORG, "project_id": PROJECT, "environment_id": ENV, "deployment_id": DEPLOYMENT}
    with pytest.raises(ValueError, match="witness budget exhausted"): await execute(cfg)
    pages = [args["params"] for _, url, args in wire.calls if url.endswith("/deployments")]
    assert pages == [{"limit": "100", "offset": str(offset)} for offset in (0, 100, 200, 300, 400)]
    assert len(wire.calls) == 10 and not wire.queue


@pytest.mark.asyncio
async def test_opt_in_names_and_picker_context_do_not_replace_saved_restrictions(wire):
    wire.queue = [[org()], org(), [org()], org(), [org()]]
    hidden = await execute({"operation": "get_organization", "organization_id": ORG}, inputs={"include_labels": True})
    shown = await execute({"operation": "get_organization", "organization_id": ORG}, blob(include_labels=True))
    assert "name" not in hidden["data"] and shown["data"]["name"] == PRIVATE and "role" not in shown["data"]
    result = await p.Env0Node.load_field_options("organization_id", blob(), context={"organization_id": FOREIGN, "include_labels": True})
    assert result == {"options": [option(ORG)], "next_page_token": None, "completion": "unknown"}
    with pytest.raises(ValueError): await p.Env0Node.load_field_options("environment_id", blob(), context={})
    with pytest.raises(ValueError): await p.Env0Node.load_field_options("organization_id", blob(), page_token="100")
    assert len(wire.calls) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"data": []}, [org(), org()], [{**org(), "id": True}], [{**org(), "createdAt": "no-zone"}], [org()] * 1001])
async def test_bare_array_type_duplicate_and_size_contract(wire, payload):
    wire.queue = [payload]
    with pytest.raises(RuntimeError): await execute({"operation": "check_connection"})


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload,ctype", [(401, {"message": PRIVATE}, "application/json"),
    (403, {"error": PRIVATE}, "application/json"), (202, {}, "application/json"), (302, {}, "application/json"),
    (500, {}, "text/html"), (200, {}, "text/html"), (200, b'{"id":"x","id":"y"}', "application/json"),
    (200, b'[NaN]', "application/json"), (200, b' ' * 2_000_001, "application/json")])
async def test_errors_redirects_and_invalid_json_never_escape(wire, status, payload, ctype):
    wire.queue = [(payload, status, ctype)]
    with pytest.raises((ValueError, RuntimeError)) as caught: await execute({"operation": "check_connection"})
    assert PRIVATE not in str(caught.value) and len(wire.calls) == 1


def test_actual_native_schema_key_pair_hierarchy_and_local_bounds():
    schema = p.Env0Node.get_config_schema()
    model = schema["$defs"]["Env0APIKeyCredential"]
    assert model["title"] == "env zero API Key" and "x-credential-type" not in model
    assert all(model["properties"][field]["ui:widget"] == "password" for field in ("api_key_id", "api_key_secret"))
    assert set(schema["properties"]["config"]["discriminator"]["mapping"]) == set(p.OPS) and len(p.OPS) == 9
    assert p.Env0Node.validate_config({"config": {"operation": "check_connection"}})["valid"] is True
    for changes in ({"credential_type": None}, {"credential_type": "env0_oidc"}, {"api_key_id": "user:invalid"},
        {"token": PRIVATE}, {"approved_resources_json": '{"organizations":[123]}'}, {"include_labels": "true"}):
        raw = {"config": {"operation": "check_connection"}, "credentials": blob(**changes)}
        assert p.Env0Node.validate_config(raw)["valid"] is False
        with pytest.raises(ValueError) as caught: p.Env0Node.parse_config(raw)
        assert PRIVATE not in str(caught.value)
    for value in (True, "", "../other", "https://invalid/", "other?x", "org%2Fother", 123):
        with pytest.raises(ValueError): p.resource_id(value)
    for args in ({"limit": True}, {"limit": 101}, {"offset": -1}, {"offset": True}):
        with pytest.raises(ValueError): p.Page(**args)
