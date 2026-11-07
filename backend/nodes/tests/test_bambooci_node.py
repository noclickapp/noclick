"""Bamboo CI factory, transport, parser, picker and connection-hook regressions."""
from dataclasses import asdict
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import bambooci_node as ad
from nodes.core.base import ConfigValidationError
from nodes.core.registry import NODE_REGISTRY, NodeFactory

USER = "11111111-1111-4111-8111-111111111111"
WF = "22222222-2222-4222-8222-222222222222"
NODE = "automation-bambooci"
PROJECT, PLAN, OTHER = "PROJ", "PROJ-PLAN", "FOREIGN"


@pytest.fixture
def ensure_native_db_pool():
    yield


def credential(**updates):
    return {"credential_type": "bambooci_pat", "access_token": "fixture-token", "instance_url": "https://bamboo.example.com/bamboo", "project_key": PROJECT, **updates}


def make_node(operation, data=None, **config):
    target = {"project_key": PROJECT} if operation in {"get_project", "list_plans", "get_plan"} else {}
    if operation == "get_plan":
        target["plan_key"] = PLAN
    return NodeFactory.create_node("fixture", NODE, {"config": {"operation": operation, **target, **config},
        "credentials": credential() if data is None else data}, user_id=USER)

@pytest.fixture
def http(monkeypatch):
    state = SimpleNamespace(calls=[], client_options=[], responses=[])
    async def respond(request):
        state.calls.append(request)
        assert state.responses, "Unexpected HTTP request"
        item = state.responses.pop(0)
        status, payload = item[:2]
        headers = item[2] if len(item) == 3 else {}
        return httpx.Response(status, content=payload, headers=headers) if isinstance(payload, (str, bytes)) else httpx.Response(status, json=payload, headers=headers) if payload is not None else httpx.Response(status, headers=headers)
    def client(**kwargs):
        state.client_options.append(kwargs)
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(ad, "guarded_async_client", client)
    return state


def project(**updates):
    return {"key": PROJECT, "id": 9007199254740993, "name": "Private project",
        "project": {"token": "private-sentinel"}, "user": {"email": "private-sentinel"},
        "description": "private-sentinel", "link": {"href": "https://private-sentinel"}, **updates}


def plan(**updates):
    return {"planKey": PLAN, "projectKey": PROJECT, "id": 42, "planName": "Private plan",
        "type": "CHAIN", "enabled": True, "active": False,
        "currentRestUser": {"email": "private-sentinel"}, "actions": ["private-sentinel"],
        "variableContext": {"password": "private-sentinel"}, "uri": "https://private-sentinel", **updates}


def catalog(kind, *rows, **page):
    return (200, {kind: {kind: list(rows), **page}, "link": {"href": "https://private-sentinel"}})


def test_actual_factory_schema_exposes_only_five_metadata_operations():
    assert NODE_REGISTRY[NODE] is ad.BambooCINode
    defs = ad.BambooCINode.get_config_schema()["$defs"]
    assert defs["BambooPATCredential"]["required"] == ["instance_url", "project_key", "access_token"]
    assert defs["BambooCIGetPlanConfig"]["properties"]["plan_key"]["x-dynamic-options"]["depends_on"] == "project_key"
    assert defs["BambooCIGetPlanConfig"]["properties"]["plan_key"]["x-dynamic-options"]["field_name"] == "plan_key"
    operations = {v["properties"]["operation"]["const"] for v in defs.values() if "operation" in v.get("properties", {})}
    assert operations == {"check_connection", "list_projects", "get_project", "list_plans", "get_plan"}
    for operation in ("get_result", "queue_build", "update_plan"):
        with pytest.raises(ConfigValidationError, match="not a valid option"):
            make_node(operation)
    with pytest.raises(ConfigValidationError, match="startIndex"):
        make_node("list_projects", startIndex=2)


@pytest.mark.asyncio
async def test_project_catalog_is_bound_reachability_strict_json_and_private_projection(http):
    http.responses = [catalog("projects", project(), project(key=OTHER, id=2), size=2, startIndex=0, maxResult=25)]
    out = await make_node("check_connection").execute({})
    assert out["protected_catalog"] is True and out["items"] == [{"key": PROJECT, "id": "9007199254740993"}]
    assert out["returned"] == 1 and out["provider_returned"] == 2 and out["local_truncated"] is False
    assert out["provider_page_metadata"] == {"size": 2, "startIndex": 0, "maxResult": 25}
    assert "unknown" in out["completion"] and "total" not in out and "next_page_token" not in out
    req = http.calls[0]
    assert req.method == "GET" and str(req.url) == "https://bamboo.example.com/bamboo/rest/api/latest/project?expand=projects"
    assert req.headers["authorization"] == "Bearer fixture-token" and req.headers["accept"] == "application/json"
    assert req.headers["user-agent"].startswith("NoClick-BambooCI/")
    assert "private-sentinel" not in json.dumps(out) and "Private project" not in json.dumps(out)


@pytest.mark.asyncio
async def test_project_detail_requires_current_catalog_and_matching_json_key(http):
    http.responses = [catalog("projects", project()), (200, project())]
    out = await make_node("get_project", include_names=True).execute({})
    assert out["project"] == {"key": PROJECT, "id": "9007199254740993", "name": "Private project"}
    assert http.calls[-1].url.path.endswith("/project/PROJ") and not http.calls[-1].url.params
    http.responses = [catalog("projects", project()), (200, project(key=OTHER))]
    with pytest.raises(RuntimeError):
        await make_node("get_project").execute({})


@pytest.mark.asyncio
async def test_plan_catalog_is_locally_bound_and_detail_matches_current_plan_ancestry(http):
    http.responses = [catalog("projects", project()), catalog("plans", plan(), plan(planKey="FOREIGN-PLAN", projectKey=OTHER)), (200, plan())]
    out = await make_node("get_plan", include_names=True).execute({})
    assert out["plan"] == {"planKey": PLAN, "projectKey": PROJECT, "id": "42", "planName": "Private plan",
        "type": "CHAIN", "enabled": True, "active": False}
    assert len(http.calls) == 3 and dict(http.calls[1].url.params) == {"expand": "plans"}
    assert http.calls[-1].url.path.endswith("/plan/PROJ-PLAN") and not http.calls[-1].url.params
    assert "private-sentinel" not in json.dumps(out)
    http.responses = [catalog("projects", project()), catalog("plans", plan(), plan(planKey="PROJ-TWO"), plan(planKey="FOREIGN-PLAN", projectKey=OTHER))]
    bounded = await make_node("list_plans", max_items=1).execute({})
    assert bounded["returned"] == 1 and bounded["provider_returned"] == 3 and bounded["local_truncated"] is True
    assert bounded["items"][0]["planKey"] == PLAN and "planName" not in bounded["items"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["config-project", "plan-prefix", "project-catalog", "plan-catalog", "detail-id"])
async def test_binding_mismatches_stop_before_unwitnessed_child_route(http, mismatch):
    config = {}
    http.responses = [catalog("projects", project()), catalog("plans", plan()), (200, plan())]
    if mismatch == "config-project":
        config["project_key"] = OTHER
    elif mismatch == "plan-prefix":
        config["plan_key"] = "FOREIGN-PLAN"
    elif mismatch == "project-catalog":
        http.responses[0] = catalog("projects", project(key=OTHER))
    elif mismatch == "plan-catalog":
        http.responses[1] = catalog("plans", plan(planKey="FOREIGN-PLAN", projectKey=OTHER))
    else:
        http.responses[2] = (200, plan(planKey="PROJ-TWO"))
    with pytest.raises((ValueError, RuntimeError)):
        await make_node("get_plan", **config).execute({})
    assert len(http.calls) == {"config-project": 0, "plan-prefix": 0, "project-catalog": 1, "plan-catalog": 2, "detail-id": 3}[mismatch]


@pytest.mark.asyncio
async def test_parent_picker_uses_bound_context_current_catalog_and_id_search(http):
    for context in ({}, {"project_key": OTHER}):
        with pytest.raises(ValueError):
            await ad.BambooCINode.load_field_options("plan_key", credential(), context=context)
    assert http.calls == []
    http.responses = [catalog("projects", project()), catalog("plans", plan(), plan(planKey="PROJ-TWO"))]
    out = await ad.BambooCINode.load_field_options("plan_key", credential(), context={"project_key": PROJECT,
        "access_token": "forged", "workflow_id": WF}, search="-plan")
    assert out == {"options": [{"value": PLAN, "label": PLAN}], "next_page_token": None}
    assert all(req.headers["authorization"] == "Bearer fixture-token" for req in http.calls)
    before = len(http.calls)
    with pytest.raises(ValueError):
        await ad.BambooCINode.load_field_options("project_key", credential(), page_token="fabricated")
    assert len(http.calls) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, [], {"projects": {"project": [project()]}},
    {"projects": {"projects": [project(), project()]}}, {"projects": {"projects": [project(key="../other")]}},
    {"projects": {"projects": [project()], "size": True}}, {"projects": {"projects": []}, "error": "private-sentinel"}])
async def test_malformed_or_xml_alias_catalog_has_no_legacy_fallback(http, payload):
    http.responses = [(200, payload)]
    with pytest.raises(RuntimeError) as failure:
        await make_node("check_connection").execute({})
    assert len(http.calls) == 1 and "private-sentinel" not in str(failure.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"plans": {"plan": [plan()]}}, {"plans": {"plans": [{"key": PLAN, "projectKey": PROJECT}]}},
    {"plans": {"plans": [plan(projectKey=OTHER)]}}, {"plans": {"plans": [plan(enabled="true")]}}])
async def test_plan_json_names_and_strict_ancestry_cannot_be_xml_aliases(http, payload):
    http.responses = [catalog("projects", project()), (200, payload)]
    with pytest.raises(RuntimeError):
        await make_node("list_plans").execute({})
    assert len(http.calls) == 2


@pytest.mark.parametrize("url", ["http://bamboo.example.com", "https://127.0.0.1", "https://[::1]", "https://bamboo.local",
    "https://localhost", "https://user:pass@bamboo.example.com", "https://bamboo.example.com/bamboo/rest",
    "https://bamboo.example.com/rest", "https://bamboo.example.com/bamboo//", "https://bamboo.example.com/bamboo?",
    "https://bamboo.example.com/#", "https://bamboo.example.com/%62amboo"])
def test_instance_contract_refuses_ip_private_alias_or_arbitrary_context(url):
    with pytest.raises(ValidationError):
        ad.BambooPATCredential.model_validate(credential(instance_url=url))
    assert ad._instance("https://bamboo.example.com/bamboo/") == "https://bamboo.example.com/bamboo"


@pytest.mark.asyncio
async def test_raw_family_and_token_refuse_before_provider_io(http):
    for data in (credential(credential_type="bamboo_basic"), credential(access_token="Bearer private-sentinel")):
        with pytest.raises(ValueError):
            await ad.BambooCINode.load_field_options("project_key", data)
    assert http.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 302, 204])
async def test_provider_refusal_is_static_unknown_and_never_retried(http, status):
    http.responses = [(status, {"error": "private-sentinel fixture-token"})]
    with pytest.raises(RuntimeError) as failure:
        await make_node("check_connection").execute({})
    assert "private-sentinel" not in str(failure.value) and "fixture-token" not in str(failure.value) and len(http.calls) == 1


@pytest.mark.asyncio
async def test_actual_manual_connect_uses_bound_catalog_reachability_without_identity(http, monkeypatch):
    from nodes.core import credential_connect
    from nodes.core.connection_evidence import collect_evidence
    monkeypatch.setattr(credential_connect, "_collect_evidence", collect_evidence)
    http.responses = [catalog("projects", project())]
    result = await credential_connect.validate_for_connect(credential_type="bambooci_pat", credential_data=credential(), user_id=USER)
    assert result.ok and result.node_type == NODE and result.evidence.reachable is True
    assert ad.BambooCINode.connection_evidence.proves == "reachability" and [sample.label for sample in result.evidence.samples] == [PROJECT] and result.evidence.account_label is None
    assert "private-sentinel" not in json.dumps(asdict(result.evidence))


@pytest.mark.asyncio
async def test_staging_validation_hook_uses_bound_catalog_and_keeps_failures_unknown(http):
    http.responses = [catalog("projects", project())]
    assert await ad.BambooCINode.validate_credential_access(credential()) == {"valid": True}
    http.responses = [(403, {"error": "private-sentinel"})]
    out = await ad.BambooCINode.validate_credential_access(credential())
    assert out["valid"] is None and "private-sentinel" not in json.dumps(out)
    assert await ad.BambooCINode.freshen_credential(credential()) == credential()


@pytest.mark.asyncio
@pytest.mark.parametrize("private_override", [False, True])
async def test_actual_public_transport_refuses_private_dns_despite_legacy_override(monkeypatch, private_override):
    import asyncio
    import socket
    from utils import ssrf
    transport_calls = []
    lookup = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    monkeypatch.setattr(ssrf, "allow_private_hosts", lambda: private_override)
    monkeypatch.setattr(ad, "allow_private_hosts", lambda: private_override)
    def guarded(**kwargs):
        return ssrf.guarded_async_client(transport=httpx.MockTransport(
            lambda request: transport_calls.append(request) or httpx.Response(200, json={})), **kwargs)
    monkeypatch.setattr(ad, "guarded_async_client", guarded)
    with pytest.raises(RuntimeError, match="could not be reached"):
        await make_node("check_connection").execute({})
    if private_override:
        lookup.assert_not_awaited()
    else:
        lookup.assert_awaited_once_with("bamboo.example.com", 443, type=socket.SOCK_STREAM)
    assert transport_calls == []
