"""Hivelocity factory, reads, discovery, field-mask and privacy contracts."""
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict
import json
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.connection_evidence import collect_evidence
from nodes.hivelocity_node import HivelocityNode, FIELD_MASK, _credential

TYPE = "automation-hivelocity"
USER, KEY = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
DEVICE, SELECTED = 10, 11
RAW = {"credential_type": "hivelocity_api_key", "api_key": "synthetic-hivelocity-secret", "reference_device_id": DEVICE}
DEVICE_ROW = {"deviceId": DEVICE, "status": "active", "spsStatus": "IN_USE", "deviceType": "Bare Metal", "deviceTypeGroup": "Server", "createdDate": "2026-01-01", "isProvisioning": False, "isReload": False, "selfProvisioning": True, "provisioningProgress": "end", "monitorsTotal": 2, "monitorsUp": 2, "name": "Opt-in device", "hostname": "PRIVATE", "primaryIp": "PRIVATE", "ipmiAddress": {"address": "PRIVATE"}, "currentApp": {"cloud_init_template": "PRIVATE", "app_form": {"test_data": "PRIVATE"}}, "currentAppOption": {"form": "PRIVATE"}, "location": {"name": "PRIVATE"}, "ports": ["PRIVATE"], "metadata": {"notes": "PRIVATE"}, "tags": ["PRIVATE"], "billingInfo": {"card": "PRIVATE"}, "enterpriseCloud": {"network": "PRIVATE"}, "sharedHosting": {"password": "PRIVATE"}, "serviceMonitors": ["PRIVATE"], "reloadBlockedReason": "PRIVATE", "canReload": True}
SELECTED_ROW = {**DEVICE_ROW, "deviceId": SELECTED, "name": "Opt-in selected device"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool(): yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], {}
    def handle(request):
        calls.append(request)
        assert request.method == "GET" and request.url.host == "core.hivelocity.net" and request.url.scheme == "https"
        assert request.headers["X-API-KEY"] == RAW["api_key"] and request.headers["Accept"] == "application/json"
        assert request.headers["X-Fields"] in {FIELD_MASK, FIELD_MASK + ",name"}
        assert "Authorization" not in request.headers and not request.content and not request.url.query
        assert RAW["api_key"] not in str(request.url)
        path = request.url.path.removeprefix("/api/v2")
        assert path in {"/device/", "/device/10", "/device/11"}
        default = [DEVICE_ROW, SELECTED_ROW] if path == "/device/" else DEVICE_ROW if path == "/device/10" else SELECTED_ROW
        reply = replies.get(path, (200, deepcopy(default)))
        if callable(reply): reply = reply(request)
        if isinstance(reply, Exception): raise reply
        code, payload = reply
        return httpx.Response(code, content=payload if isinstance(payload, bytes) else json.dumps(payload).encode())
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {"timeout": 20, "follow_redirects": False, "trust_env": False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as instance: yield instance
    monkeypatch.setattr("nodes.hivelocity_node.guarded_async_client", client)
    return calls, replies


async def run(operation, **arguments):
    return await run_node_operation(node_type=TYPE, operation=operation, arguments=arguments, credential_data=deepcopy(RAW), user_id=USER)


@pytest.mark.asyncio
async def test_actual_factory_execute_config_lens_and_protected_collector(transport):
    node = NodeFactory.create_node("fixture", TYPE, {"credentials": RAW, "config": {"operation": "list_devices", "label": "Saved canvas"}}, user_id=USER)
    result = await node.execute({})
    assert result["protected_reachability_verified"] and not result["principal_identity_proven"] and not result["tenant_ownership_proven"]
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=deepcopy(RAW))
    assert evidence.reachable is True and HivelocityNode.connection_evidence.proves == "reachability" and not evidence.account_label
    assert "PRIVATE" not in json.dumps(asdict(evidence))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args", [("list_devices", {}), ("get_device", {"device_id": SELECTED})])
async def test_exact_two_native_read_operations_direct_shapes_and_private_projection(transport, operation, args):
    result = await run(operation, **args)
    assert result["status"] == "success" and not result["mutation_attempted"] and not result["snapshot_stable"]
    encoded = json.dumps(result)
    assert "PRIVATE" not in encoded and "Opt-in" not in encoded and RAW["api_key"] not in encoded
    assert all(request.headers["X-Fields"] == FIELD_MASK for request in transport[0])
    if operation == "list_devices":
        assert result["returned_count"] == 2 and result["total_count"] is None and result["has_more"] is None and result["pagination_complete"] is None
    else:
        assert result["data"]["deviceId"] == SELECTED and result["data"]["createdDate"] == "2026-01-01"
        assert result["data"]["monitorsTotal"] == 2 and result["data"]["isReload"] is False


@pytest.mark.asyncio
async def test_names_opt_in_only_changes_the_closed_mask_and_blank_names_are_not_identity(transport):
    calls, replies = transport
    result = await run("get_device", device_id=SELECTED, include_names=True, fields="initial-creds", rack_id=9)
    assert result["data"]["name"] == "Opt-in selected device" and "PRIVATE" not in json.dumps(result)
    assert any(request.headers["X-Fields"] == FIELD_MASK + ",name" for request in calls)
    assert all("initial-creds" not in request.url.path and not request.url.query for request in calls)
    replies["/device/"] = (200, [{**DEVICE_ROW, "name": ""}])
    options = await HivelocityNode.load_field_options("device_id", RAW, {"include_names": True})
    assert options["options"] == [{"value": DEVICE, "label": str(DEVICE), "metadata": {"resource_type": "device"}}]


@pytest.mark.asyncio
async def test_optional_scalars_are_not_fabricated_and_discovery_has_no_cursor(transport):
    calls, replies = transport
    replies["/device/"] = (200, [{"deviceId": DEVICE}])
    replies["/device/10"] = (200, {"deviceId": DEVICE})
    result = await run("list_devices")
    assert result["data"] == [{"deviceId": DEVICE, "resource_type": "device"}]
    options = await HivelocityNode.load_field_options("device_id", RAW)
    assert options["options"][0]["label"] == "10" and options["has_more"] is None and options["next_page_token"] is None
    calls.clear()
    with pytest.raises(ValueError): await HivelocityNode.load_field_options("device_id", RAW, page_token="2")
    assert not calls


@pytest.mark.asyncio
async def test_reference_and_selected_catalog_and_direct_echo_must_remain_current(transport):
    calls, replies = transport
    for rows in ([], [SELECTED_ROW]):
        replies["/device/"] = (200, rows)
        evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=deepcopy(RAW))
        assert evidence.reachable is None
    replies.clear(); calls.clear()
    replies["/device/10"] = (200, SELECTED_ROW)
    result = await run("list_devices")
    assert result["status"] == "error" and "data" not in result
    replies.clear(); calls.clear()
    result = await run("get_device", device_id=99)
    assert result["status"] == "error" and all(not c.url.path.endswith("/99") for c in calls)
    calls.clear()
    def moved(request):
        times = sum(c.url.path == "/api/v2/device/" for c in calls)
        return 200, [DEVICE_ROW, SELECTED_ROW] if times == 1 else [DEVICE_ROW]
    replies["/device/"] = moved
    result = await run("get_device", device_id=SELECTED)
    assert result["status"] == "error" and "data" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [401, 403, 429, 204, {"data": [DEVICE_ROW]}, {}, httpx.ReadTimeout("synthetic")])
async def test_errors_permission403_unknown_private_body_no_retry(transport, reply):
    calls, replies = transport
    replies["/device/"] = reply if isinstance(reply, Exception) else (reply, b"PRIVATE") if isinstance(reply, int) else (200, reply)
    evidence = await collect_evidence(node_type=TYPE, user_id=USER, credential_data=deepcopy(RAW))
    assert evidence.reachable is None and len(calls) == 1 and "PRIVATE" not in json.dumps(asdict(evidence))
    if reply == 403:
        result = await run("list_devices")
        assert "permission" in result["error"] and result["http_status"] == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("shape", ["boolean_id", "string_id", "duplicate", "oversized_rows", "oversized_bytes", "flag", "count", "unknown_state", "bad_date", "count_inconsistent"])
async def test_closed_types_bounds_no_fallback_or_unmasked_retry(transport, shape):
    calls, replies = transport
    payload = [deepcopy(DEVICE_ROW)]
    if shape == "boolean_id": payload[0]["deviceId"] = True
    if shape == "string_id": payload[0]["deviceId"] = "10"
    if shape == "duplicate": payload.append(deepcopy(DEVICE_ROW))
    if shape == "oversized_rows": payload = [{**DEVICE_ROW, "deviceId": n} for n in range(501)]
    if shape == "flag": payload[0]["isReload"] = "false"
    if shape == "count": payload[0]["monitorsTotal"] = True
    if shape == "unknown_state": payload[0]["spsStatus"] = "unsupported"
    if shape == "bad_date": payload[0]["createdDate"] = {"raw": "PRIVATE"}
    if shape == "count_inconsistent": payload[0]["monitorsUp"] = 3
    replies["/device/"] = (200, b"x" * (2 * 1024 * 1024 + 1) if shape == "oversized_bytes" else payload)
    result = await run("list_devices")
    assert result["status"] == "error" and "data" not in result and len(calls) == 1


@pytest.mark.asyncio
async def test_real_factory_preserves_raw_bound_family_witness_before_execute(transport):
    node = NodeFactory.create_node("fixture", TYPE, {"credentials": RAW, "config": {"operation": "list_devices"}}, user_id=USER)
    node.node_data["credentials"] = {**RAW, "credential_type": "foreign"}
    with pytest.raises(ValueError): await node.execute({})
    assert not transport[0]


def test_raw_family_literal_key_reference_before_reconciliation():
    for change in ({"credential_type": "foreign"}, {"api_key": "Bearer synthetic"}, {"api_key": "https://private.test"}, {"reference_device_id": True}, {"reference_device_id": -1}, {"refresh_token": "synthetic"}, {"base_url": "https://private.test"}, {"token_version": True}):
        with pytest.raises(ValueError): _credential({**RAW, **change})
    assert _credential({**RAW, "reference_device_id": "10", "token_version": 1}).reference_device_id == DEVICE
    with pytest.raises(ValueError): HivelocityNode.parse_config({"credentials": {**RAW, "credential_type": "foreign"}, "config": {"operation": "list_devices"}})
