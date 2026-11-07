"""Native factory/collector/admission and scoped transport fixtures.

Only HTTP/storage boundaries are synthetic; assertions traverse real native
dispatch, response projection, parent validation and metadata-write contracts.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict
import json
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.connection_evidence import collect_evidence
from nodes.northflank_node import NorthflankNode, _credential, NorthflankDeleteProjectConfig

TYPE = "automation-northflank"
USER = "11111111-1111-4111-8111-111111111111"
KEY = "22222222-2222-4222-8222-222222222222"
RAW = {"credential_type": "northflank_api_token", "api_token": "synthetic-northflank-issued-token", "target": "token_default", "team_id": None}
PROJECT, SERVICE, JOB, ADDON, RUN = "fixture-project", "fixture-service", "fixture-job", "fixture-addon", "fixture-run"
UID = "111111111111111111111111"
SERVICE_DATA = {"id": SERVICE, "uid": "222222222222222222222222", "name": "Fixture Service", "projectId": PROJECT, "serviceType": "combined", "status": {"deployment": {"status": "COMPLETED", "reason": "DEPLOYING"}}, "runtimeEnvironment": {"SECRET": "PRIVATE-ENV"}, "vcsData": {"projectUrl": "PRIVATE-REPO"}, "buildArguments": [{"key": "PRIVATE-KEY"}]}
JOB_DATA = {"id": JOB, "uid": "333333333333333333333333", "name": "Fixture Job", "projectId": PROJECT, "jobType": "manual", "suspended": True, "billing": {"deploymentPlan": "PRIVATE-BILLING"}, "settings": {"cron": "PRIVATE-CRON"}}
ADDON_DATA = {"id": ADDON, "uid": "444444444444444444444444", "name": "Fixture Addon", "status": "running", "spec": {"type": "postgresql", "config": {"password": "PRIVATE-PASSWORD"}}}
PROJECT_DATA = {"id": PROJECT, "uid": UID, "name": "Fixture Project", "deployment": {"region": "europe-west"}, "services": [SERVICE_DATA], "jobs": [JOB_DATA], "addons": [ADDON_DATA], "customRegistry": {"credentialId": "PRIVATE-REGISTRY"}, "networking": {"tailscale": {"secrets": "PRIVATE-NETWORK"}}}
RUN_DATA = {"id": RUN, "status": "SUCCESS", "concluded": True, "active": 0, "failed": 0, "succeeded": 1, "backoffLimit": 0, "completions": 1, "startedAt": "2026-01-01T00:00:00Z", "concludedAt": "2026-01-01T00:01:00Z", "logs": "PRIVATE-LOGS"}
DEPLOYMENT = {"id": "fixture-deployment", "createdAt": "2026-01-01T00:00:00Z", "active": True, "releaseType": "stable", "image": {"imagePath": "PRIVATE-IMAGE"}, "commit": {"author": "PRIVATE-AUTHOR"}, "reason": {"user": {"email": "PRIVATE-EMAIL"}}}


def page(name, rows): return {"data": {name: deepcopy(rows)}, "pagination": {"count": len(rows), "hasNextPage": False}}


@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], {}
    def handle(request):
        calls.append(request)
        assert request.url.host == "api.northflank.com" and request.url.scheme == "https"
        assert request.headers["Authorization"] == "Bearer " + RAW["api_token"]
        assert RAW["api_token"] not in str(request.url) and RAW["api_token"].encode() not in request.content
        path = request.url.path.replace("/v1/teams/fixture-team", "/v1")
        defaults = {
            "/v1/projects": page("projects", [PROJECT_DATA]),
            "/v1/projects/" + PROJECT: {"data": PROJECT_DATA},
            f"/v1/projects/{PROJECT}/services": page("services", [SERVICE_DATA]),
            f"/v1/projects/{PROJECT}/services/{SERVICE}": {"data": SERVICE_DATA},
            f"/v1/projects/{PROJECT}/services/{SERVICE}/deployments": page("deployments", [DEPLOYMENT]),
            f"/v1/projects/{PROJECT}/jobs": page("jobs", [JOB_DATA]),
            f"/v1/projects/{PROJECT}/jobs/{JOB}": {"data": JOB_DATA},
            f"/v1/projects/{PROJECT}/jobs/{JOB}/runs": page("runs", [RUN_DATA]),
            f"/v1/projects/{PROJECT}/jobs/{JOB}/runs/{RUN}": {"data": RUN_DATA},
            f"/v1/projects/{PROJECT}/addons": page("addons", [ADDON_DATA]),
            f"/v1/projects/{PROJECT}/addons/{ADDON}": {"data": ADDON_DATA},
            "/v1/regions": {"data": {"regions": [{"id": "europe-west", "name": "Europe West", "regionName": "Belgium", "gpuDevices": [{"PRIVATE": "GPU"}]}]}},
        }
        reply = replies.get((request.method, path), replies.get(path, (200, defaults[path])))
        if isinstance(reply, Exception): raise reply
        status, payload = reply
        return httpx.Response(status, content=payload if isinstance(payload, bytes) else json.dumps(payload).encode())
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as instance: yield instance
    monkeypatch.setattr("nodes.northflank_node.guarded_async_client", client)
    return calls, replies


async def run(operation, **arguments):
    return await run_node_operation(node_type=TYPE, operation=operation, arguments=arguments, credential_data=deepcopy(RAW), user_id=USER)


@pytest.mark.asyncio
async def test_real_factory_and_collector_prove_reachability_only(transport):
    node = NodeFactory.create_node("fixture", TYPE, {"credentials": RAW, "config": {"operation": "check_connection", "label": "Saved metadata", "disabled": False}}, user_id=USER)
    result = await node.execute({})
    assert result["protected_reachability_verified"] is True and result["principal_identity_proven"] is False
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=deepcopy(RAW))
    assert evidence.reachable is True and NorthflankNode.connection_evidence.proves == "reachability" and not evidence.account_label and not evidence.samples
    assert "PRIVATE" not in json.dumps(asdict(evidence))


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,reachable", [({}, None), ({"data": {}}, None), ({"data": [], "pagination": {}}, None), (page("projects", []), True)])
async def test_empty_protected_collection_is_valid_but_empty_envelope_is_not_proof(transport, payload, reachable):
    _, replies = transport
    replies["/v1/projects"] = (200, payload)
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=deepcopy(RAW))
    assert evidence.reachable is reachable and not evidence.account_label


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args", [
    ("list_projects", {}), ("get_project", {"project_id": PROJECT}),
    ("list_services", {"project_id": PROJECT}), ("get_service", {"project_id": PROJECT, "service_id": SERVICE}),
    ("list_deployments", {"project_id": PROJECT, "service_id": SERVICE, "release_type": "stable"}),
    ("list_jobs", {"project_id": PROJECT}), ("get_job", {"project_id": PROJECT, "job_id": JOB}),
    ("list_runs", {"project_id": PROJECT, "job_id": JOB}), ("get_run", {"project_id": PROJECT, "job_id": JOB, "run_id": RUN}),
    ("list_addons", {"project_id": PROJECT}), ("get_addon", {"project_id": PROJECT, "addon_id": ADDON}), ("list_regions", {}),
])
async def test_actual_read_dispatch_closed_projection_and_no_mutation(transport, operation, args):
    calls, _ = transport
    result = await run(operation, **args)
    assert result["status"] == "success" and "PRIVATE" not in json.dumps(result)
    assert all(request.method == "GET" for request in calls)
    assert all(not any(part in request.url.path for part in ("/secrets", "/logs", "/builds")) for request in calls)
    if operation == "list_deployments": assert any(request.url.params.get("releaseType") == "stable" for request in calls)


@pytest.mark.asyncio
async def test_actual_picker_parent_context_and_page_continuation(transport):
    calls, replies = transport
    with pytest.raises(ValueError): await NorthflankNode.load_field_options("run_id", RAW, context={"job_id": JOB})
    assert not calls
    replies[f"/v1/projects/{PROJECT}/services"] = (200, {**page("services", [SERVICE_DATA]), "pagination": {"count": 1, "hasNextPage": True, "cursor": "555555555555555555555555"}})
    options = await NorthflankNode.load_field_options("service_id", RAW, context={"project_id": PROJECT})
    assert options["has_more"] and options["options"][0]["metadata"]["project_id"] == PROJECT
    before = len(calls)
    with pytest.raises(ValueError): await NorthflankNode.load_field_options("service_id", RAW, context={"project_id": "other-project"}, page_token=options["next_page_token"])
    with pytest.raises(ValueError): await NorthflankNode.load_field_options("service_id", {**RAW, "target": "team", "team_id": "fixture-team"}, context={"project_id": PROJECT}, page_token=options["next_page_token"])
    assert len(calls) == before


@pytest.mark.asyncio
async def test_explicit_team_routes_and_public_region_is_not_identity(transport):
    calls, _ = transport
    result = await NorthflankNode.load_field_options("project_id", {**RAW, "target": "team", "team_id": "fixture-team"})
    assert result["options"][0]["value"] == PROJECT and calls[0].url.path == "/v1/teams/fixture-team/projects"
    result = await run("list_regions")
    assert result["protected_project_evidence"] is False and "principal_identity_proven" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"id": "foreign-service"}, {"projectId": "foreign-project"}, {"uid": "999999999999999999999999"}])
async def test_selected_child_id_parent_and_permanent_uid_are_enforced(transport, change):
    _, replies = transport
    replies[f"/v1/projects/{PROJECT}/services/{SERVICE}"] = (200, {"data": {**SERVICE_DATA, **change}})
    result = await run("get_service", project_id=PROJECT, service_id=SERVICE)
    assert result["status"] == "error" and "data" not in result


@pytest.mark.asyncio
async def test_empty_project_writes_use_only_documented_fields_and_separate_readback(transport):
    calls, replies = transport
    empty = {**PROJECT_DATA, "services": [], "jobs": [], "addons": []}
    replies["/v1/projects/" + PROJECT] = (200, {"data": empty})
    ack = {"data": {"id": PROJECT, "name": "Fixture Project", "region": "europe-west"}}
    replies[("POST", "/v1/projects")] = (200, ack)
    create = await run("create_project", name="Fixture Project", region="europe-west", description="Disposable project", color="#123456")
    assert create["mutation_outcome"] == "acknowledged" and create["readback_required"]
    assert json.loads(calls[-1].content) == {"name": "Fixture Project", "region": "europe-west", "description": "Disposable project", "color": "#123456"}
    replies[("PATCH", "/v1/projects/" + PROJECT)] = (200, ack)
    args = {"project_id": PROJECT, "expected_project_uid": UID, "confirm_owned_empty_project": True}
    update = await run("update_project", **args, description="Updated fixture")
    assert update["status"] == "success" and json.loads(calls[-1].content) == {"description": "Updated fixture"}
    replies[("DELETE", "/v1/projects/" + PROJECT)] = (200, {"data": {}})
    delete = await run("delete_project", **args)
    assert delete["http_status"] == 200 and delete["data"] == {} and delete["expected_readback_http_status"] == 404
    assert calls[-1].method == "DELETE" and dict(calls[-1].url.params) == {"delete_child_objects": "false"}


@pytest.mark.asyncio
async def test_nonempty_or_reused_project_refuses_before_any_write(transport):
    calls, replies = transport
    args = {"project_id": PROJECT, "expected_project_uid": UID, "confirm_owned_empty_project": True}
    assert (await run("delete_project", **args))["status"] == "error"
    assert all(request.method == "GET" for request in calls)
    replies["/v1/projects/" + PROJECT] = (200, {"data": {**PROJECT_DATA, "uid": "999999999999999999999999", "services": [], "jobs": [], "addons": []}})
    assert (await run("update_project", **args, color="#123"))["status"] == "error"
    assert all(request.method == "GET" for request in calls)


@pytest.mark.asyncio
async def test_atomic_server_nonempty_refusal_and_uncertain_write_are_not_retried(transport):
    calls, replies = transport
    replies["/v1/projects/" + PROJECT] = (200, {"data": {**PROJECT_DATA, "services": [], "jobs": [], "addons": []}})
    replies[("DELETE", "/v1/projects/" + PROJECT)] = (409, {"message": RAW["api_token"]})
    args = {"project_id": PROJECT, "expected_project_uid": UID, "confirm_owned_empty_project": True}
    result = await run("delete_project", **args)
    assert result["status_code"] == 409 and RAW["api_token"] not in json.dumps(result)
    assert len([c for c in calls if c.method == "DELETE"]) == 1
    replies[("DELETE", "/v1/projects/" + PROJECT)] = httpx.ReadTimeout("synthetic")
    result = await run("delete_project", **args)
    assert result["mutation_attempted"] is True and result["mutation_outcome"] == "unverified"
    assert len([c for c in calls if c.method == "DELETE"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(200, {}), (200, b"not JSON"), (204, b""), (429, {"error": "synthetic"}), (200, {"data": {}, "errors": ["synthetic"]})])
async def test_nonjson_empty_body_error_and_rate_limit_are_not_proof_or_retried(transport, status, payload):
    calls, replies = transport
    replies["/v1/projects"] = (status, payload)
    result = await run("check_connection")
    assert result["status"] == "error" and "data" not in result and len(calls) == 1


@pytest.mark.parametrize("change", [{"credential_type": "other_token"}, {"target": None}, {"target": "team"}, {"team_id": "fixture-team"}, {"base_url": "https://attacker.invalid"}, {"refresh_token": "synthetic"}, {"api_token": None}])
def test_authoritative_raw_family_and_context_precede_defaults(change):
    with pytest.raises(ValueError): _credential({**RAW, **change})


def test_falsey_confirmation_cannot_coerce_to_true():
    for value in (False, 1, "true"):
        with pytest.raises(ValueError): NorthflankDeleteProjectConfig(project_id=PROJECT, expected_project_uid=UID, confirm_owned_empty_project=value)


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["pending", "rejected"])
async def test_real_stored_admission_and_collector_refuse_before_http(transport, monkeypatch, decision):
    calls, _ = transport
    monkeypatch.setattr("repositories.credential_approvals.CredentialApprovalRepo.admit", AsyncMock(return_value={"id": KEY, "status": decision, "new_request": False}))
    monkeypatch.setattr("nodes.core.run_op.resolve_operation_credential", AsyncMock(return_value=deepcopy(RAW)))
    monkeypatch.setattr("utils.credential_approval.get_native_pool", lambda: object())
    result = await run_node_operation(node_type=TYPE, operation="check_connection", arguments={}, user_id=USER, credential_id=KEY, pool=object())
    assert result["executed"] is False and result["_halt_downstream"] is True
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_id=KEY, pool=object())
    assert evidence.reachable is None and not calls


def test_staging_row_bookkeeping_is_not_provider_credential_data():
    credential = _credential({**RAW, "token_version": 2, "updated_at": "2026-01-01T00:00:00Z"})
    assert credential.model_dump(mode="json") == RAW
