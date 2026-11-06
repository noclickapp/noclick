"""UNRUN native Exoscale factory/connect/dispatcher/signing/current-row/socket fixtures.
Synthetic resources and MockTransport do not prove provider, database or live UI access.
"""
import base64
import hashlib
import hmac
import importlib.util
import logging
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import requests
from nodes import exoscale_node as native
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.credential_connect import validate_for_connect
from nodes.exoscale_node import ExoscaleCredentialRow as CredentialValidationRow

NT = "automation-exoscale"
USER = "11111111-1111-4111-8111-111111111111"
CID = "22222222-2222-4222-8222-222222222222"
IID = "33333333-3333-4333-8333-333333333333"
TID = "44444444-4444-4444-8444-444444444444"
GID = "55555555-5555-4555-8555-555555555555"
KEY = {"credential_type": native.TYPE, "api_key": "synthetic-key", "api_secret": "synthetic-secret", "zone": "ch-gva-2"}
TYPE = {"id": TID, "cpus": 2, "gpus": 0, "memory": 2048, "size": "small", "family": "standard", "authorized": True, "zones": ["ch-gva-2"]}
INSTANCE = {"id": IID, "state": "running", "created-at": "2026-10-01T12:30:00Z", "instance-type": TYPE, "disk-size": 10, "name": "opt-in-name", "public-ip": "omit-IP", "ipv6-address": "omit-IP6", "labels": {"omit": "private"}, "user-data": "omit-secret", "ssh-keys": [{"omit": "private"}], "private-networks": [{"omit": "private"}], "console-url": "omit-capability"}
GROUP = {"id": GID, "name": "opt-in-group", "description": "omit-note", "instances": [INSTANCE]}
PAGE = {"instances": [INSTANCE]}


def node(operation="list_instances", raw=KEY, **args):
    return NodeFactory.create_node(node_id="exoscale-fixture", node_type=NT, node_data={"config": {"operation": operation, **args}, "credentials": deepcopy(raw)}, sio=None, sid=None, user_id=USER)


@pytest.fixture(autouse=True)
def admission(monkeypatch):
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value=None))
    monkeypatch.setattr(native.time, "time", lambda: 1700000000)


@pytest.fixture
def transport(monkeypatch):
    calls, responses = [], []
    async def receive(request):
        assert request.url.host in {"api-ch-gva-2.exoscale.com", "api-de-fra-1.exoscale.com"} and request.url.scheme == "https"
        assert request.method == "GET" and request.content == b"" and not request.url.query
        assert not request.url.username and not request.url.password
        assert KEY["api_key"] not in str(request.url) and KEY["api_secret"] not in str(request.url)
        msg = f"GET {request.url.path}\n\n\n\n1700000600".encode()
        sig = base64.standard_b64encode(hmac.new(KEY["api_secret"].encode(), msg, hashlib.sha256).digest()).decode()
        assert request.headers["Authorization"] == f'EXO2-HMAC-SHA256 credential={KEY["api_key"]},expires=1700000600,signature={sig}'
        calls.append(request)
        value = responses.pop(0)
        if callable(value): value = value(request)
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 30, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(receive)) as instance:
            yield instance
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls, responses


@pytest.mark.parametrize("query", ["", "?z=a&a=z", "?z=%CE%BB&a=x%2By"])
def test_signer_matches_exact_official_v2_auth_utf8_five_segments(query):
    path = Path(__file__).parents[2] / "tests/fixtures/exoscale/exoscale_auth_reference.py"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == "16db92ae2276595c78d447e9291a1fd05f4b13ebf6ade5fcb0a5f1ead06a5a5f"
    spec = importlib.util.spec_from_file_location("exoscale_primary_auth", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    url = "https://api-ch-gva-2.exoscale.com/v2/instance" + query
    cred = native.ExoscaleAPIKeyCredential.model_validate({**KEY, "api_secret": "synthetic-secret-λ"})
    actual = httpx.Request("GET", url)
    native.sign_request(actual, cred, 1700000600)
    reference = requests.Request("GET", url).prepare()
    module.ExoscaleV2Auth(cred.api_key, cred.api_secret)._sign_request(reference, 1700000600)
    assert actual.headers["Authorization"] == reference.headers["Authorization"]
    assert "signed-query-args=a;z" in actual.headers["Authorization"] if query else "signed-query-args" not in actual.headers["Authorization"]
    assert cred.api_secret not in actual.headers["Authorization"]


def test_repeated_signing_arguments_are_explicitly_refused_not_ambiguously_signed():
    with pytest.raises(ValueError):
        native.sign_request(httpx.Request("GET", "https://api-ch-gva-2.exoscale.com/v2/instance?a=x&a=y"), native.credential(KEY), 1)


@pytest.mark.parametrize("args", [{"max_records": "1"}, {"max_records": True}, {"max_records": 0}, {"max_records": 1001}, {"max_records": 20.5}, {"max_records": "20x"}, {"include_names": "false"}, {"host": "https://evil.example.test"}, {"page": 1}, {"labels": "private"}, {"operation": "create_instance"}, {"operation": "start_instance"}])
def test_actual_factory_strict_bounds_and_closed_operations_zero_io(transport, args):
    operation = args.get("operation", "list_instances")
    with pytest.raises(ValueError): node(operation, **{k:v for k,v in args.items() if k != "operation"})
    assert transport[0] == []


@pytest.mark.parametrize("raw", [{**KEY, "zone": "ch-gva-1"}, {**KEY, "api_key": "key,expires=0"}, {**KEY, "api_secret": 42}, {**KEY, "api_secret": "https://private"}, {**KEY, "expected_instance_id": "../instance"}])
def test_credential_fields_refuse_foreign_host_header_injection_and_wrong_types(raw):
    with pytest.raises(ValueError): native.credential(raw)


@pytest.mark.parametrize("model,args", [(native.ListInstances, {"include_names": None}), (native.GetInstance, {"instance_id": "../private"}), (native.GetInstanceType, {}), (native.GetAntiAffinityGroup, {"anti_affinity_group_id": True})])
def test_direct_native_required_ids_and_boolean_refusal(model, args):
    with pytest.raises(ValueError): model.model_validate(args)


@pytest.mark.asyncio
@pytest.mark.parametrize("items", [[], [INSTANCE]])
async def test_visible_manual_form_actual_connect_is_zone_reachability_not_identity(transport, items):
    transport[1].append({"instances": items})
    verdict = await validate_for_connect(credential_type=native.TYPE, credential_data={"api_key": KEY["api_key"], "api_secret": KEY["api_secret"]}, user_id=USER)
    assert verdict.ok and verdict.credential_data["credential_type"] == native.TYPE
    assert native.ExoscaleNode.connection_evidence.proves == "reachability"
    assert verdict.evidence.reachable is True and not verdict.evidence.account_label
    assert {sample.label for sample in verdict.evidence.samples} <= {item["id"] for item in items}
    assert [r.url.path for r in transport[0]] == ["/v2/instance"]


@pytest.mark.asyncio
async def test_foreign_original_tag_cannot_be_reconciled_or_preparsed(transport):
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="foreign", node_type=NT, node_data={"config": {"operation": "list_instances"}, "credentials": {**KEY, "credential_type": "foreign"}, "credentialIds": {native.TYPE: CID}}, sio=None, sid=None)
    instance = node(); instance.node_data["credentials"]["credential_type"] = "foreign"
    with pytest.raises(ValueError): await instance.execute({})
    assert transport[0] == []


@pytest.mark.asyncio
async def test_actual_dispatch_unpaged_projection_no_false_completion(transport):
    transport[1].append(PAGE)
    result = await run_node_operation(node_type=NT, operation="list_instances", arguments={"max_records": 10}, user_id=USER, credential_data=KEY)
    assert result["data"]["items"][0]["id"] == IID and "omit" not in repr(result)
    assert "name" not in result["data"]["items"][0]
    assert result["data"]["items"][0]["instance-type"]["gpus"] == 0
    assert result["data"]["inventory_completion"] == "unknown" and "total" not in result["data"]
    assert len(transport[0]) == 1 and not transport[0][0].url.query


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,replies,paths", [
    ("get_instance", {"instance_id": IID}, [PAGE, INSTANCE], ["/v2/instance", f"/v2/instance/{IID}"]),
    ("list_instance_types", {}, [{"instance-types":[TYPE]}], ["/v2/instance-type"]),
    ("get_instance_type", {"instance_type_id": TID}, [{"instance-types":[TYPE]}, TYPE], ["/v2/instance-type", f"/v2/instance-type/{TID}"]),
    ("list_anti_affinity_groups", {}, [{"anti-affinity-groups":[GROUP]}], ["/v2/anti-affinity-group"]),
    ("get_anti_affinity_group", {"anti_affinity_group_id": GID}, [{"anti-affinity-groups":[GROUP]}, GROUP], ["/v2/anti-affinity-group", f"/v2/anti-affinity-group/{GID}"]),
])
async def test_remaining_native_exact_routes_and_projected_nested_resources(transport, operation, args, replies, paths):
    transport[1].extend(deepcopy(replies))
    result = await node(operation, **args).execute({})
    assert "omit" not in repr(result) and [r.url.path for r in transport[0]] == paths
    assert "authorized" not in repr(result) and "zones" not in repr(result)


@pytest.mark.asyncio
async def test_second_demonstrated_host_and_expected_protected_instance_witness(transport):
    transport[1].extend([INSTANCE, PAGE])
    result = await node(raw={**KEY, "zone": "de-fra-1", "expected_instance_id": IID}).execute({})
    assert result["zone"] == "de-fra-1"
    assert {r.url.host for r in transport[0]} == {"api-de-fra-1.exoscale.com"}
    assert [r.url.path for r in transport[0]] == [f"/v2/instance/{IID}", "/v2/instance"]


@pytest.mark.asyncio
async def test_absent_catalog_parent_stops_before_detail(transport):
    transport[1].append({"instances": []})
    with pytest.raises(native.OutcomeUnverified): await node("get_instance", instance_id=IID).execute({})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_mismatched_detail_and_expected_witness_fail_before_return_or_next_call(transport):
    transport[1].extend([PAGE, {**INSTANCE, "id": GID}])
    with pytest.raises(native.OutcomeUnverified): await node("get_instance", instance_id=IID).execute({})
    assert len(transport[0]) == 2
    transport[1].append({**INSTANCE, "id": GID})
    with pytest.raises(native.OutcomeUnverified): await node(raw={**KEY, "expected_instance_id": IID}).execute({})
    assert len(transport[0]) == 3


@pytest.mark.asyncio
async def test_opt_in_names_stay_conservative(transport):
    transport[1].append({"anti-affinity-groups": [GROUP]})
    result = await node("list_anti_affinity_groups", include_names=True).execute({})
    item = result["data"]["items"][0]
    assert item["name"] == GROUP["name"] and item["instances"][0]["name"] == INSTANCE["name"]
    assert "omit" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"instances": [INSTANCE, INSTANCE]}, {"instances": [True]}, {"instances": None}, {"instances": [{"id": True}]}, {"instances": [{**INSTANCE, "state": "invented"}]}, {"instances": [{**INSTANCE, "created-at": "yesterday"}]}, {"instances": [{**INSTANCE, "instance-type": {**TYPE, "cpus": True}}]}, {"error": "omit-secret", "instances": []}])
async def test_malformed_catalog_and_projected_fields_fail_safely(transport, payload):
    transport[1].append(payload)
    with pytest.raises(native.OutcomeUnverified) as error: await node().execute({})
    assert "omit" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text='{"instances":[],"instances":[]}', headers={"content-type":"application/json"}), httpx.Response(200, text='{"instances":[NaN]}', headers={"content-type":"application/json"}), httpx.Response(200, text="omit-private", headers={"content-type":"text/plain"}), httpx.Response(200, content=b"x"*(native.MAX_BODY+1), headers={"content-type":"application/json"})])
async def test_json_content_and_body_bound_fail_without_private_errors(transport, response):
    transport[1].append(response)
    with pytest.raises(native.OutcomeUnverified) as error: await node().execute({})
    assert "omit-private" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401,403,429,500,302])
async def test_actual_error_status_preserved_no_body_or_retry(transport, status):
    transport[1].append(httpx.Response(status, json={"message":"omit-private"}))
    with pytest.raises(native.ApiError) as error: await node().execute({})
    assert error.value.status_code == status and "omit-private" not in str(error.value)
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_local_bound_refuses_without_truncation(transport):
    transport[1].append({"instances": [INSTANCE, {**INSTANCE, "id": GID}]})
    with pytest.raises(native.OutcomeUnverified): await node(max_records=1).execute({})
    assert len(transport[0]) == 1


@pytest.fixture
def stored(monkeypatch):
    state = {"accessible": True, "row": CredentialValidationRow(native.TYPE, USER, 1, datetime(2026,10,1,tzinfo=timezone.utc), 1, None, deepcopy(KEY))}
    async def fetch(pool, identifier, principal, organization_id=None):
        assert identifier == CID and principal == USER and organization_id is None
        return state["row"] if state["accessible"] else None
    monkeypatch.setattr(native, "fetch_exoscale_authority", fetch)
    monkeypatch.setattr(native, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda raw: deepcopy(raw)))
    return state
@pytest.mark.asyncio
async def test_saved_missing_caller_and_stale_original_key_refuse_before_transport(stored, transport):
    instance = NodeFactory.create_node(node_id="saved", node_type=NT, node_data={"credential_id": CID, "config": {"operation": "list_instances"}, "credentials": KEY}, sio=None, sid=None)
    with pytest.raises(ValueError): await instance.execute({})
    with pytest.raises(ValueError): await native.Authority.create({**KEY, "api_key": "stale"}, pool=object(), user_id=USER, credential_id=CID, organization_id=None)
    assert transport[0] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["owner", "version", "approval", "revoked", "access", "kind", "original_kind", "key", "secret", "zone"])
async def test_actual_saved_execute_discards_racing_response(stored, transport, change):
    instance = node(); instance.node_data.update({"credential_id": CID, "_approval_pool": object()})
    def changed(request):
        if change == "access": stored["accessible"] = False
        else:
            delta = {"owner": {"owner_id": CID}, "version": {"token_version": 2}, "approval": {"approval_revision": 2}, "revoked": {"revoked_at": datetime.now(timezone.utc)}, "kind": {"credential_type": "foreign"}, "original_kind": {"credential": {**KEY, "credential_type": "foreign"}}, "key": {"credential": {**KEY, "api_key": "changed"}}, "secret": {"credential": {**KEY, "api_secret": "changed"}}, "zone": {"credential": {**KEY, "zone": "de-fra-1"}}}[change]
            stored["row"] = replace(stored["row"], **delta)
        return deepcopy(PAGE)
    transport[1].append(changed)
    with pytest.raises(ValueError): await instance.execute({})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_saved_actor_picker_unpaged_current_access(stored, transport, monkeypatch):
    current_organization = AsyncMock(return_value=None)
    monkeypatch.setattr(native.Authority, "current_organization", current_organization)
    fresh = await native.ExoscaleNode.freshen_credential(credential_data=KEY, pool=object(), user_id=USER, credential_id=CID)
    current_organization.assert_awaited_once()
    transport[1].append(deepcopy(PAGE))
    result = await native.ExoscaleNode.load_field_options(field_name="instance_id", credential_data=fresh, context={"_user_id": USER})
    assert result == {"options": [{"value": IID, "label": IID}], "next_page_token": None}
    for args in [{"context": {"_user_id": CID}}, {"page_token": "2"}, {"credential_data": {**KEY, native.AUTH_KEY: {}}}]:
        with pytest.raises(ValueError): await native.ExoscaleNode.load_field_options(**{"field_name": "instance_id", "credential_data": fresh, "context": {"_user_id": USER}, **args})
    stored["accessible"] = False
    with pytest.raises(ValueError): await native.ExoscaleNode.load_field_options(field_name="instance_id", credential_data=fresh, context={"_user_id": USER})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_local_diagnostics_hide_key_but_unrelated_logs_survive(transport, caplog):
    logger = logging.getLogger("httpx")
    def observed(request):
        logger.warning("%s %s", request.headers["authorization"], "omit-private")
        return deepcopy(PAGE)
    transport[1].append(observed)
    with caplog.at_level(logging.WARNING):
        await node().execute({}); logger.warning("Ordinary unrelated message")
    assert "Exoscale transport activity" in caplog.text and "Ordinary unrelated message" in caplog.text
    assert KEY["api_key"] not in caplog.text and "omit-private" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [None, "authorization", "owner"])
async def test_execute_workflow_owner_fallback_revalidates_trusted_scope(monkeypatch, transport, change):
    owner = "33333333-3333-4333-8333-333333333333"
    workflow = "44444444-4444-4444-8444-444444444444"
    organization = "55555555-5555-4555-8555-555555555555"
    pool = object(); state = {"owner": owner, "authorized": True}; principals = []
    row = CredentialValidationRow(native.TYPE, owner, 1, datetime(2026, 10, 1, tzinfo=timezone.utc), 1, None, deepcopy(KEY))
    async def fetch(pool, identifier, principal, org=None):
        assert identifier == CID and org == organization
        principals.append(principal)
        return row if principal == owner else None
    async def get_owner(actual_pool, actual_workflow):
        assert actual_pool is pool and actual_workflow == workflow
        return state["owner"]
    async def allowed(actual_pool, actual_workflow, identifier):
        assert actual_pool is pool and actual_workflow == workflow and identifier == CID
        return state["authorized"]
    monkeypatch.setattr(native, "fetch_exoscale_authority", fetch)
    monkeypatch.setattr(native, "get_encryption", lambda: SimpleNamespace(decrypt_credential=lambda raw: deepcopy(raw)))
    monkeypatch.setattr("utils.credentials.credential_lender", AsyncMock(return_value=None))
    monkeypatch.setattr("utils.credentials.get_workflow_owner_id", get_owner)
    monkeypatch.setattr("utils.credentials.is_credential_authorized_for_workflow", allowed)
    instance = NodeFactory.create_node(node_id="fallback", node_type=NT, node_data={"config": {"operation": "list_instances"}, "credentials": deepcopy(KEY), "credential_id": CID, "_approval_pool": pool}, user_id=USER, organization_id=organization, workflow_id=workflow, sio=None, sid=None)
    def changed(request):
        if change == "authorization": state["authorized"] = False
        if change == "owner": state["owner"] = CID
        return deepcopy(PAGE)
    transport[1].append(changed)
    if change is None:
        assert (await instance.execute({}))["data"]["items"][0]["id"] == IID
        assert principals[:2] == [USER, owner]
    else:
        with pytest.raises(ValueError): await instance.execute({})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", [None, "foreign_original"])
async def test_real_socket_actor_and_native_loader(stored, transport, monkeypatch, decision):
    from utils import encryption
    from wss.handlers import workflow_handler as module
    from wss.receiver.client_events import WorkflowNodeLoadOptionsRequest
    class Pool:
        @asynccontextmanager
        async def acquire(self): yield connection
    if decision == "foreign_original":
        stored["row"] = replace(stored["row"], credential={**KEY, "credential_type": "foreign"})
    row = stored["row"]
    connection = SimpleNamespace(fetchrow=AsyncMock(return_value={"credential": row.credential, "credential_type": native.TYPE, "revoked_at": None, "token_version": 1, "updated_at": row.updated_at}))
    pool = Pool(); send = AsyncMock()
    crypto = SimpleNamespace(decrypt_credential=lambda value: deepcopy(value))
    monkeypatch.setattr(encryption, "get_encryption", lambda: crypto)
    monkeypatch.setattr(module, "get_encryption", lambda: crypto)
    monkeypatch.setattr(module, "get_user_org_context", AsyncMock(return_value=None))
    monkeypatch.setattr(module, "send_event", send)
    freshen = AsyncMock(wraps=native.ExoscaleNode.freshen_credential)
    monkeypatch.setattr(native.ExoscaleNode, "freshen_credential", freshen)
    handler = module.WorkflowHandler.__new__(module.WorkflowHandler)
    handler.sio = SimpleNamespace(get_session=AsyncMock(return_value={"user_id": USER}))
    handler.get_pool = AsyncMock(return_value=pool)
    if decision is None: transport[1].append(deepcopy(PAGE))
    request = WorkflowNodeLoadOptionsRequest(request_id="exoscale-socket", node_type=NT, field_name="instance_id", credential_id=CID, context={"_user_id": CID})
    await handler.load_node_options("fixture-sid", request)
    result = send.await_args.args[2].data
    if decision is None:
        assert result["success"] and result["options"] == [{"value": IID, "label": IID, "metadata": None}]
        assert len(transport[0]) == 1 and freshen.await_count == 1
    else:
        assert not result["success"] and transport[0] == []
