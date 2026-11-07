"""Prepared Koyeb contracts through actual native/connect/socket seams.
Only provider transport, SQL/encryption and socket delivery boundaries are synthetic.
These unrun fixtures do not prove provider or database behavior.
"""
import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError
from nodes import koyeb_node as ad
from nodes.core.registry import NODE_REGISTRY, NodeFactory

NODE = "automation-koyeb"
USER = "e267e09d-a2ef-4672-95c7-bf88d787a274"
WF = "14c3d333-2f3a-455a-aa86-ef83dff6913b"
TENANT = "14c3d333-2f3a-455a-aa86-ef83dff6913b"
APP = "d8533a10-bcce-4e33-8c9d-88b05ac56559"
SERVICE = "3286abd3-48b0-4e9c-a5f6-ac0a006804a6"
DEPLOYMENT = "3fa85f64-5717-4562-b3fc-2c963f66afa6"
INSTANCE = "2464031a-6f3c-440c-a0bf-a35a5aa9634b"
OTHER = "03f72dbe-5aeb-4a80-8b2e-eeb9ad11e573"


@pytest.fixture
def ensure_native_db_pool():
    yield


def credential(**updates):
    return {"credential_type": "koyeb_api_key", "api_key": "fixture-secret", "organization_id": TENANT, **updates}


def organization(**updates):
    return {"organization": {"id": TENANT, "name": "Fixture organization", "status": "ACTIVE",
        "billing_email": "private@example.test", "plan": "private", "address1": "private", **updates}}


def resource(kind="app", **updates):
    identifiers = {"app": APP, "service": SERVICE, "deployment": DEPLOYMENT, "instance": INSTANCE}
    raw = {"id": identifiers[kind], "organization_id": TENANT, "name": "fixture-app" if kind == "app" else "Fixture " + kind,
        "status": "HEALTHY", "created_at": "2026-10-06T00:00:00Z", "updated_at": None,
        "messages": ["private"], "state": {"env": {"SECRET": "private"}}, "definition": {"private": "private"},
        "metadata": {"private": "private"}, "domains": [{"type": "AUTOASSIGNED", "name": "private.koyeb.app"}],
        "xyz_deployment_id": "private-unstable", "version": "18446744073709551615"}
    if kind != "app":
        raw["app_id"] = APP
    if kind in {"deployment", "instance"}:
        raw["service_id"] = SERVICE
    if kind == "instance":
        raw.update(region="fra", replica_index=0)
    raw.update(updates)
    return {kind: raw}


def page(kind="app", rows=None, *, limit=50, offset=0, count=None, more=False):
    rows = [resource(kind)[kind]] if rows is None else rows
    payload = {kind + "s": rows, "limit": limit, "offset": offset, "count": len(rows) if count is None else count}
    if kind != "instance":
        payload["has_next"] = more
    return payload


def empty_preflight():
    return [(200, organization()), (200, resource()), (200, page("service", [], limit=1))]


def make_node(operation, data=None, **config):
    target = {}
    if operation not in {"check_connection", "get_organization", "list_apps", "create_empty_app"}:
        target["app_id"] = APP
    if operation in {"get_service", "list_deployments", "get_deployment", "list_instances", "get_instance"}:
        target["service_id"] = SERVICE
    if operation == "get_deployment":
        target["deployment_id"] = DEPLOYMENT
    if operation == "get_instance":
        target["instance_id"] = INSTANCE
    return NodeFactory.create_node("fixture", NODE, {"config": {"operation": operation, **target, **config},
        "credentials": credential() if data is None else data}, user_id=USER)


@pytest.fixture
def http(monkeypatch):
    state = SimpleNamespace(calls=[], client_options=[], responses=[])
    async def respond(request):
        state.calls.append(request)
        assert state.responses, "Unexpected HTTP request"
        status, payload = state.responses.pop(0)
        return httpx.Response(status, content=payload) if isinstance(payload, (str, bytes)) else httpx.Response(status, json=payload) if payload is not None else httpx.Response(status)
    def client(**kwargs):
        state.client_options.append(kwargs)
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(ad, "guarded_async_client", client)
    return state



def test_actual_factory_schema_operations_and_parent_metadata():
    assert NODE_REGISTRY[NODE] is ad.KoyebNode
    schema = ad.KoyebNode.get_config_schema()
    defs = schema["$defs"]
    operations = {defs[ref["$ref"].split("/")[-1]]["properties"]["operation"]["const"] for ref in schema["properties"]["config"]["oneOf"]}
    assert operations == {"check_connection", "get_organization", "list_apps", "get_app", "create_empty_app", "rename_empty_app", "delete_empty_app",
        "list_services", "get_service", "list_deployments", "get_deployment", "list_instances", "get_instance"}
    assert defs["KoyebAPIKeyCredential"]["required"] == ["api_key", "organization_id"]
    props = defs["KoyebGetDeploymentConfig"]["properties"]
    assert props["service_id"]["x-dynamic-options"]["depends_on"] == "app_id"
    assert props["deployment_id"]["x-dynamic-options"]["depends_on"] == "service_id"
    assert defs["KoyebListInstancesConfig"]["properties"]["limit"]["maximum"] == 100
    for config in ({"operation": "create_empty_app", "name": "bad/app"}, {"operation": "get_service", "app_id": APP},
            {"operation": "list_apps", "limit": 101}, {"operation": "delete_empty_app", "app_id": APP}, {"operation": "deploy"}):
        with pytest.raises(ValidationError):
            ad.KoyebNodeConfig(config=config, credentials=credential())


@pytest.mark.parametrize("updates", [{"credential_type": "other"}, {"organization_id": "not-uuid"},
    {"api_key": "fixture-secret\nprivate"}, {"api_key": "Bearer fixture-secret"}])
def test_raw_family_and_binding_errors_never_include_secrets(updates):
    with pytest.raises(ValueError) as failure:
        ad._credential(credential(**updates))
    assert "fixture-secret" not in str(failure.value) and "private" not in str(failure.value)


@pytest.mark.asyncio
async def test_current_organization_bearer_header_projection_and_no_identity_claim(http):
    http.responses = [(200, organization())]
    out = await make_node("check_connection").execute({})
    request = http.calls[0]
    assert request.method == "GET" and str(request.url) == ad.ROOT + "/v1/account/organization"
    assert request.headers["Authorization"] == "Bearer fixture-secret" and not request.url.query
    assert out["organization_id"] == TENANT and out["items"][0]["name"] == "Fixture organization"
    assert "private" not in json.dumps(out) and "individual account identity" in out["proof"]


@pytest.mark.asyncio
async def test_deployment_and_instance_parents_status_and_private_projection(http):
    http.responses = [(200, organization()), (200, resource()), (200, resource("service")), (200, resource("deployment"))]
    result = await make_node("get_deployment").execute({})
    assert [request.url.path for request in http.calls] == ["/v1/account/organization", "/v1/apps/" + APP,
        "/v1/services/" + SERVICE, "/v1/deployments/" + DEPLOYMENT]
    assert result["deployment"]["version"] == "18446744073709551615" and "private" not in json.dumps(result)
    http.responses = [(200, organization()), (200, resource()), (200, resource("service")), (200, resource("instance"))]
    result = await make_node("get_instance").execute({})
    assert result["instance"]["replica_index"] == 0 and result["instance"]["region"] == "fra"
    assert "xyz_deployment_id" not in result["instance"] and "private" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong", ["organization", "app", "service"])
async def test_foreign_resource_parent_is_refused_before_child_request(http, wrong):
    http.responses = [(200, organization(id=OTHER))] if wrong == "organization" else [(200, organization()),
        (200, resource(organization_id=OTHER) if wrong == "app" else resource()),
        (200, resource("service", app_id=OTHER))]
    with pytest.raises(RuntimeError, match="outside"):
        await make_node("get_deployment").execute({})
    assert all(not request.url.path.startswith("/v1/deployments/") for request in http.calls)


@pytest.mark.asyncio
async def test_list_cursor_total_count_and_zero_match_continuation(http):
    http.responses = [(200, organization()), (200, page(limit=1, count=2, more=True))]
    first = await make_node("list_apps", limit=1, search="missing").execute({})
    assert first["items"] == [] and first["total"] == 2 and first["returned"] == 1 and first["has_more"]
    assert first["next_page_token"]
    http.responses = [(200, organization()), (200, page(rows=[resource(id=OTHER)["app"]], limit=1, offset=1, count=2))]
    second = await make_node("list_apps", limit=1, search="missing", page_token=first["next_page_token"]).execute({})
    assert dict(http.calls[-1].url.params) == {"limit": "1", "offset": "1"} and second["next_page_token"] is None
    before = len(http.calls)
    for kwargs in ({"search": "changed"}, {"limit": 2}, {"data": credential(organization_id=OTHER)}):
        with pytest.raises(ValueError, match="page token"):
            await make_node("list_apps", limit=kwargs.get("limit", 1), search=kwargs.get("search", "missing"),
                data=kwargs.get("data"), page_token=first["next_page_token"]).execute({})
    assert len(http.calls) == before


@pytest.mark.asyncio
async def test_instances_count_based_paging_and_scoped_picker_context(http):
    http.responses = [(200, organization()), (200, resource()), (200, resource("service")), (200, page("instance", count=2))]
    out = await ad.KoyebNode.load_field_options("instance_id", credential(), context={"app_id": APP, "service_id": SERVICE,
        "organization_id": OTHER, "api_key": "forged", "workflow_id": WF}, search="")
    assert out["options"][0]["value"] == INSTANCE and out["next_page_token"]
    assert dict(http.calls[-1].url.params) == {"app_id": APP, "service_id": SERVICE, "limit": "50", "offset": "0"}
    assert all(request.headers["Authorization"] == "Bearer fixture-secret" for request in http.calls)
    before = len(http.calls)
    for field, context, token in (("service_id", {}, None), ("unknown", {}, None), ("instance_id", {"app_id": APP, "service_id": OTHER}, out["next_page_token"])):
        with pytest.raises(ValueError):
            await ad.KoyebNode.load_field_options(field, credential(), context=context, page_token=token)
    assert len(http.calls) == before


@pytest.mark.asyncio
async def test_create_empty_app_name_only_and_actual_readbacks(http):
    http.responses = [(200, organization()), (200, resource()), (200, resource()), *empty_preflight()]
    out = await make_node("create_empty_app", name="fixture-app").execute({})
    assert http.calls[1].method == "POST" and json.loads(http.calls[1].content) == {"name": "fixture-app"}
    assert out["readback_verified"] and out["empty_at_readback"] and out["http_status"] == 200
    assert "managed Koyeb subdomain" in out["effect"]
    assert all(request.method == "GET" or request.url.path == "/v1/apps" for request in http.calls)


@pytest.mark.asyncio
async def test_rename_empty_app_mask_name_only_and_verified_readback(http):
    renamed = resource(name="renamed-app")
    http.responses = [(200, organization()), (200, resource()), *empty_preflight(), (200, renamed), (200, renamed),
        (200, organization()), (200, renamed), (200, page("service", [], limit=1))]
    out = await make_node("rename_empty_app", expected_name="fixture-app", name="renamed-app").execute({})
    writes = [request for request in http.calls if request.method != "GET"]
    assert len(writes) == 1 and writes[0].method == "PATCH"
    assert dict(writes[0].url.params) == {"update_mask": "name"} and json.loads(writes[0].content) == {"name": "renamed-app"}
    assert out["app"]["name"] == "renamed-app" and out["readback_verified"]


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["name", "custom-domain", "service"])
async def test_nonempty_or_custom_domain_app_changes_never_write(http, reason):
    app = resource(domains=[{"type": "CUSTOM", "name": "private.example.test"}]) if reason == "custom-domain" else resource()
    http.responses = [(200, organization()), (200, app)]
    if reason == "service":
        http.responses += [(200, organization()), (200, app), (200, page("service", limit=1))]
    with pytest.raises(ValueError):
        await make_node("delete_empty_app", expected_name="different" if reason == "name" else "fixture-app").execute({})
    assert all(request.method == "GET" for request in http.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("readback,absent", [(404, True), (200, False)])
async def test_delete_http200_ack_not204_and_single_absence_readback(http, readback, absent):
    http.responses = [(200, organization()), (200, resource()), *empty_preflight(), (200, {}), (readback, resource())]
    out = await make_node("delete_empty_app", expected_name="fixture-app").execute({})
    assert out["deletion_acknowledged"] is True and out["confirmed_absent"] is absent and out["pending"] is not absent
    assert http.calls[-2].method == "DELETE" and http.calls[-1].method == "GET" and len(http.calls) == 7


@pytest.mark.asyncio
async def test_undocumented_delete_204_is_not_a_completed_cleanup(http):
    http.responses = [(200, organization()), (200, resource()), *empty_preflight(), (204, None)]
    with pytest.raises(RuntimeError, match="HTTP 200"):
        await make_node("delete_empty_app", expected_name="fixture-app").execute({})
    assert len(http.calls) == 6 and http.calls[-1].method == "DELETE"


@pytest.mark.asyncio
@pytest.mark.parametrize("status,payload", [(401, {"error": "fixture-secret"}), (403, {"detail": "sensitive-response-marker"}), (429, {}), (500, {}),
    (200, {"error": "sensitive-response-marker"}), (200, {}),
    (200, organization(id=OTHER, billing_email="sensitive-response-marker@example.test", plan="sensitive-response-marker", address1="sensitive-response-marker")),
    (200, "not JSON")])
async def test_provider_errors_unknown_and_malformed_contracts_are_static_no_retry(http, status, payload):
    http.responses = [(status, payload)]
    with pytest.raises(RuntimeError) as failure:
        await make_node("check_connection").execute({})
    assert "fixture-secret" not in str(failure.value) and "sensitive-response-marker" not in str(failure.value) and len(http.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"has_next": "yes"}, {"count": -1}, {"offset": 3}, {"limit": 500}, {"apps": [{}]},
    {"apps": [], "count": 1, "has_next": True}, {"apps": [resource()["app"], resource()["app"]]}])
async def test_malformed_list_pages_fail_without_private_output(http, change):
    http.responses = [(200, organization()), (200, {**page(), **change})]
    with pytest.raises(RuntimeError, match="invalid list"):
        await make_node("list_apps").execute({})
    assert len(http.calls) == 2


@pytest.mark.asyncio
async def test_actual_manual_connect_uses_readonly_org_evidence(http, monkeypatch):
    from nodes.core import credential_connect
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(credential_connect, "_collect_evidence", collect_evidence)
    bad = await credential_connect.validate_for_connect(credential_type="koyeb_api_key", credential_data=credential(organization_id="bad"), user_id=USER)
    assert not bad.ok and bad.field_errors and http.calls == []
    http.responses = [(200, organization())]
    valid = await credential_connect.validate_for_connect(credential_type="koyeb_api_key", credential_data=credential(), user_id=USER)
    assert valid.ok and valid.node_type == NODE and valid.evidence.reachable is True
    assert ad.KoyebNode.connection_evidence.proves == "reachability" and valid.evidence.account_label is None
    assert valid.evidence.samples[0].label == "Fixture organization" and len(http.calls) == 1 and http.calls[0].method == "GET"
