"""Native Contabo factory/connect/dispatcher fixtures on staging contracts.
Synthetic resources and MockTransport do not prove provider, database or live UI access.
"""
import logging
from contextlib import asynccontextmanager
from copy import deepcopy
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from nodes import contabo_node as native
from nodes.core.registry import NodeFactory
from nodes.core.run_op import run_node_operation
from nodes.core.credential_connect import validate_for_connect

NT = "automation-contabo"
USER = "11111111-1111-4111-8111-111111111111"
CID = "22222222-2222-4222-8222-222222222222"
IID = 12345
IMG = "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"
SID = "snap1628603855"
KEY = {"credential_type": native.TYPE, "access_token": "synthetic-issued-token"}
INSTANCE = {"instanceId": IID, "status": "running", "createdDate": "2026-10-01T12:30:00Z", "cpuCores": 4, "ramMb": 1024, "diskMb": 2048.5, "region": "EU", "osType": "Linux", "productType": "ssd", "imageId": IMG, "displayName": "opt-in-name", "name": "omit-internal", "ipConfig": {"v4": {"ip": "omit-IP"}}, "additionalIps": ["omit-IP"], "macAddress": "omit-MAC", "vHostName": "omit-infra", "vHostId": 2, "defaultUser": "omit-admin", "sshKeys": ["omit-private"], "customerId": "omit-customer", "tenantId": "omit-tenant", "userData": "omit-secret", "errorMessage": "omit-private"}
IMAGE = {"imageId": IMG, "status": "Available", "creationDate": "2026-10-01T12:30:00Z", "lastModifiedDate": "2026-10-01T12:30:00Z", "sizeMb": 1024, "uploadedSizeMb": 1024.5, "osType": "Linux", "version": "20.04", "format": "qcow2", "standardImage": False, "gpu": False, "name": "opt-in-image", "description": "omit-note", "url": "https://private.example.test/omit-capability", "errorMessage": "omit-error", "customerId": "omit-customer"}
SNAPSHOT = {"snapshotId": SID, "instanceId": IID, "createdDate": "2026-10-01T12:30:00Z", "autoDeleteDate": "2026-11-01T12:30:00Z", "imageId": IMG, "name": "opt-in-snapshot", "description": "omit-note", "imageName": "omit-name", "customerId": "omit-customer"}
STATS = {"currentImagesCount": 4, "totalSizeMb": 10240, "usedSizeMb": 4096.5, "freeSizeMb": 6143.5, "customerId": "omit-customer", "tenantId": "omit-tenant"}


def page(items, number=1, size=20, total=None, pages=1):
    return {"data": deepcopy(items), "_pagination": {"page": number, "size": size, "totalElements": len(items) if total is None else total, "totalPages": pages}, "_links": {"next": "https://evil.example.test/omit-capability"}}


PAGE = page([INSTANCE])


def node(operation="list_instances", raw=KEY, **args):
    return NodeFactory.create_node(node_id="contabo-fixture", node_type=NT, node_data={"config": {"operation": operation, **args}, "credentials": deepcopy(raw)}, sio=None, sid=None, user_id=USER)


@pytest.fixture(autouse=True)
def admission(monkeypatch):
    monkeypatch.setattr("utils.credential_approval.admit_node", AsyncMock(return_value=None))


@pytest.fixture
def transport(monkeypatch):
    calls, responses = [], []
    async def receive(request):
        assert request.url.host == "api.contabo.com" and request.url.scheme == "https"
        assert request.method == "GET" and request.content == b""
        assert not request.url.username and not request.url.password
        assert KEY["access_token"] not in str(request.url)
        assert request.headers["Authorization"] == "Bearer " + KEY["access_token"]
        assert UUID(request.headers["x-request-id"]).version == 4
        assert request.headers["x-request-id"] not in {r.headers["x-request-id"] for r in calls}
        assert set(request.url.params) <= {"page", "size", "orderBy"}
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


@pytest.mark.parametrize("args", [{"page": "1"}, {"page": True}, {"page": 0}, {"page": 1000001}, {"page_size": 101}, {"page_size": "20x"}, {"page_size": 20.5}, {"include_names": "false"}, {"host": "https://evil.example.test"}, {"operation": "start_instance"}, {"operation": "region_change_check"}])
def test_actual_factory_strict_integer_and_closed_operation_refusal(transport, args):
    with pytest.raises(ValueError):
        node(args.get("operation", "list_instances"), **{k:v for k,v in args.items() if k != "operation"})
    assert transport[0] == []


@pytest.mark.parametrize("raw", [{**KEY, "access_token": 42}, {**KEY, "access_token": "Bearer token"}, {**KEY, "access_token": "token\r\nprivate"}, {**KEY, "access_token": "https://private"}, {**KEY, "expected_instance_id": "001"}, {**KEY, "expected_instance_id": "../1"}, {**KEY, "expected_instance_id": True}])
def test_credential_fields_refuse_malformed_token_and_witness(raw):
    with pytest.raises(ValueError): native.credential(raw)


@pytest.mark.parametrize("model,args", [(native.ListInstances, {"include_names": None}), (native.GetInstance, {"instance_id": "12345"}), (native.GetInstance, {"instance_id": True}), (native.GetSnapshot, {"instance_id": IID}), (native.GetImage, {"image_id": "../private"})])
def test_native_required_ids_boolean_and_path_refusal(model, args):
    with pytest.raises(ValueError): model.model_validate(args)


@pytest.mark.asyncio
@pytest.mark.parametrize("items", [[], [INSTANCE]])
async def test_visible_manual_form_actual_connect_is_resource_reachability(transport, items):
    transport[1].append(page(items))
    verdict = await validate_for_connect(credential_type=native.TYPE, credential_data={"access_token": KEY["access_token"]}, user_id=USER)
    assert verdict.ok and verdict.credential_data["credential_type"] == native.TYPE
    assert verdict.evidence.reachable is True and not verdict.evidence.account_label
    assert native.ContaboNode.connection_evidence.proves == "reachability"
    assert {sample.label for sample in verdict.evidence.samples} <= {str(item["instanceId"]) for item in items}
    assert [r.url.path for r in transport[0]] == ["/v1/compute/instances"]


@pytest.mark.asyncio
async def test_foreign_original_tag_cannot_be_reconciled_or_preparsed(transport):
    with pytest.raises(ValueError):
        NodeFactory.create_node(node_id="foreign", node_type=NT, node_data={"config": {"operation": "list_instances"}, "credentials": {**KEY, "credential_type": "foreign"}, "credentialIds": {native.TYPE: CID}}, sio=None, sid=None)
    instance = node(); instance.node_data["credentials"]["credential_type"] = "foreign"
    with pytest.raises(ValueError): await instance.execute({})
    assert transport[0] == []


@pytest.mark.asyncio
async def test_actual_dispatch_preserves_numeric_pagination_not_short_page_completion(transport):
    transport[1].append(page([INSTANCE], number=2, size=20, total=50, pages=3))
    result = await run_node_operation(node_type=NT, operation="list_instances", arguments={"page": 2, "page_size": 20}, user_id=USER, credential_data=KEY)
    assert result["data"]["items"][0]["instanceId"] == IID and "omit" not in repr(result)
    assert "displayName" not in result["data"]["items"][0]
    assert result["data"]["has_more"] is True and result["data"]["next_page"] == 3
    assert result["data"]["pagination"] == {"page": 2, "size": 20, "totalElements": 50, "totalPages": 3}
    assert list(transport[0][0].url.params.multi_items()) == [("page", "2"), ("size", "20")]
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,replies,paths", [
    ("get_instance", {"instance_id": IID}, [{"data":[INSTANCE]}], [f"/v1/compute/instances/{IID}"]),
    ("list_images", {}, [page([IMAGE])], ["/v1/compute/images"]),
    ("get_image", {"image_id": IMG}, [{"data":[IMAGE]}], [f"/v1/compute/images/{IMG}"]),
    ("list_snapshots", {"instance_id": IID}, [{"data":[INSTANCE]}, page([SNAPSHOT])], [f"/v1/compute/instances/{IID}", f"/v1/compute/instances/{IID}/snapshots"]),
    ("get_snapshot", {"instance_id": IID, "snapshot_id": SID}, [{"data":[INSTANCE]}, {"data":[SNAPSHOT]}], [f"/v1/compute/instances/{IID}", f"/v1/compute/instances/{IID}/snapshots/{SID}"]),
    ("image_stats", {}, [{"data":[STATS]}], ["/v1/compute/images/stats"]),
])
async def test_all_documented_routes_singleton_arrays_parent_and_projection(transport, operation, args, replies, paths):
    transport[1].extend(deepcopy(replies))
    result = await node(operation, **args).execute({})
    assert "omit" not in repr(result) and [r.url.path for r in transport[0]] == paths


@pytest.mark.asyncio
async def test_expected_instance_is_independent_exact_witness_not_tenant_identity(transport):
    transport[1].extend([{"data":[INSTANCE]}, PAGE])
    result = await node(raw={**KEY, "expected_instance_id": str(IID)}).execute({})
    assert "tenant" not in repr(result) and "customer" not in repr(result)
    assert [r.url.path for r in transport[0]] == [f"/v1/compute/instances/{IID}", "/v1/compute/instances"]


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [{"data":[]}, {"data":INSTANCE}, {"data":[{**INSTANCE,"instanceId":IID+1}]}, {"data":[INSTANCE,INSTANCE]}])
async def test_parent_detail_malformed_or_wrong_id_prevents_child_request(transport, reply):
    transport[1].append(reply)
    with pytest.raises(native.OutcomeUnverified): await node("list_snapshots", instance_id=IID).execute({})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_wrong_snapshot_parent_and_resource_id_never_return(transport):
    transport[1].extend([{"data":[INSTANCE]}, {"data":[{**SNAPSHOT,"instanceId":IID+1}]}])
    with pytest.raises(native.OutcomeUnverified): await node("get_snapshot", instance_id=IID, snapshot_id=SID).execute({})
    transport[1].append({"data":[{**IMAGE,"imageId":"different"}]})
    with pytest.raises(native.OutcomeUnverified): await node("get_image", image_id=IMG).execute({})


@pytest.mark.asyncio
async def test_names_opt_in_never_discloses_internal_names_or_notes(transport):
    transport[1].extend([PAGE, page([IMAGE]), {"data":[INSTANCE]}, page([SNAPSHOT])])
    for operation,args in [("list_instances",{}),("list_images",{}),("list_snapshots",{"instance_id":IID})]:
        result = await node(operation, include_names=True, **args).execute({})
        assert "opt-in" in repr(result) and "omit" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"data":[INSTANCE,INSTANCE],"_pagination":PAGE["_pagination"]}, {"data":[True],"_pagination":PAGE["_pagination"]}, {"data":[{**INSTANCE,"cpuCores":True}],"_pagination":PAGE["_pagination"]}, {"data":[{**INSTANCE,"status":"invented"}],"_pagination":PAGE["_pagination"]}, page([INSTANCE],number=2), page([INSTANCE],size=101), page([INSTANCE],total=0), {"data":[], "_pagination": {"page":1,"size":20,"totalElements":0,"totalPages":"0"}}, {"data":[], "_pagination": {"page":1.5,"size":20,"totalElements":0,"totalPages":0}}])
async def test_malformed_rows_or_pagination_fail_without_private_errors(transport, payload):
    transport[1].append(payload)
    with pytest.raises(native.OutcomeUnverified) as error: await node().execute({})
    assert "omit" not in str(error.value)


@pytest.mark.asyncio
async def test_documented_numeric_integral_counts_accept_float_without_truncation(transport):
    transport[1].append({"data":[], "_pagination":{"page":1.0,"size":20.0,"totalElements":0.0,"totalPages":0.0}})
    result = await node().execute({})
    assert result["data"]["pagination"] == {"page":1,"size":20,"totalElements":0,"totalPages":0}
    assert result["data"]["next_page"] is None


@pytest.mark.asyncio
async def test_capacity_retains_documented_array_without_aggregation_or_identity(transport):
    transport[1].append({"data":[STATS,{**STATS,"currentImagesCount":2.0}]})
    result=await node("image_stats").execute({})
    assert [item["currentImagesCount"] for item in result["data"]["items"]] == [4,2]
    assert result["data"]["provider_paging"] == "not_documented" and "omit" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200,text='{"data":[],"data":[]}',headers={"content-type":"application/json"}), httpx.Response(200,text='{"data":[NaN]}',headers={"content-type":"application/json"}),httpx.Response(200,text="omit-private",headers={"content-type":"text/plain"}),httpx.Response(200,content=b"x"*(native.MAX_BODY+1),headers={"content-type":"application/json"})])
async def test_json_and_body_bounds_fail_without_sensitive_errors(transport, response):
    transport[1].append(response)
    with pytest.raises(native.OutcomeUnverified) as error: await node().execute({})
    assert "omit-private" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status",[401,403,429,500,302])
async def test_actual_http_status_distinction_and_no_retry(transport,status):
    transport[1].append(httpx.Response(status,json={"message":"omit-private"}))
    with pytest.raises(native.ApiError) as error: await node().execute({})
    assert error.value.status_code == status and "omit-private" not in str(error.value)
    if status == 401: assert "invalid or expired" in str(error.value)
    if status == 403: assert "permission" in str(error.value)
    assert len(transport[0]) == 1


@pytest.mark.asyncio
async def test_local_transport_diagnostics_hide_token_preserve_unrelated_logs(transport,caplog):
    logger=logging.getLogger("httpx")
    def observed(request):
        logger.warning("%s %s",request.headers["authorization"],"omit-private")
        return deepcopy(PAGE)
    transport[1].append(observed)
    with caplog.at_level(logging.WARNING):
        await node().execute({});logger.warning("Ordinary unrelated message")
    assert "Contabo transport activity" in caplog.text and "Ordinary unrelated message" in caplog.text
    assert KEY["access_token"] not in caplog.text and "omit-private" not in caplog.text


@pytest.mark.asyncio
async def test_image_picker_uses_staging_credential_and_numeric_pages(transport):
    transport[1].append(page([IMAGE], number=2, size=100, total=300, pages=3))
    result = await native.ContaboNode.load_field_options(field_name="image_id", credential_data=KEY, page_token="2")
    assert result == {"options": [{"value": IMG, "label": IMG}], "next_page_token": "3"}
    assert dict(transport[0][0].url.params) == {"page": "2", "size": "100"}
    for args in [{"page_token": "02"}, {"page_token": "https://evil.example.test"}, {"field_name": "snapshot_id"}, {"credential_data": {**KEY, "credential_type": "foreign"}}]:
        with pytest.raises(ValueError):
            await native.ContaboNode.load_field_options(**{"field_name": "image_id", "credential_data": KEY, **args})
    assert len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["-1", "1.5", "1e3", "NaN", " 1024", "001024", True])
async def test_ram_refuses_undocumented_numeric_encodings(transport, value):
    transport[1].append(page([{**INSTANCE, "ramMb": value}]))
    with pytest.raises(native.OutcomeUnverified):
        await node().execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,example,args", [
    ("list_instances", "retrieveInstancesList", {"page_size": 10}),
    ("get_instance", "retrieveInstance", {"instance_id": 100}),
    ("list_images", "retrieveImageList", {"page_size": 10}),
    ("get_image", "retrieveImage", {"image_id": IMG}),
    ("list_snapshots", "retrieveSnapshotList", {"instance_id": 100, "page_size": 10}),
    ("get_snapshot", "retrieveSnapshot", {"instance_id": 100, "snapshot_id": SID}),
    ("image_stats", "retrieveCustomImagesStats", {}),
])
async def test_published_contabo_responses(transport, operation, example, args):
    import json
    from pathlib import Path
    fixtures = Path(__file__).parent / "fixtures" / "contabo"
    if operation in {"list_snapshots", "get_snapshot"}:
        transport[1].append(json.loads((fixtures / "retrieveInstance-examples.json").read_text())[0])
    transport[1].append(json.loads((fixtures / (example + "-examples.json")).read_text())[0])
    if operation in {"list_snapshots", "get_snapshot"}:
        # The published parent is 100, but the snapshot example names 1234.
        # Preserve parent validation and exercise the snapshot parser separately.
        with pytest.raises(native.OutcomeUnverified, match="requested instance parent"):
            await node(operation, **args).execute({})
        raw = json.loads((fixtures / (example + "-examples.json")).read_text())[0]
        parsed = native.records(native.Snapshot, raw, 10, parent=1234)
        assert parsed[0]["snapshotId"] == SID
        return
    result = await node(operation, **args).execute({})
    assert result["status"] == "success"
    if operation == "get_instance":
        assert result["data"]["ramMb"] == 1024


# Payload fixtures are copied from the published Contabo list responses at
# https://api.contabo.com/ (retrieveInstancesList/retrieveImageList/retrieveSnapshotList).
@pytest.mark.asyncio
@pytest.mark.parametrize("operation,example,parent,order", [
    ("on_new_instance", "retrieveInstancesList", None, "createdDate:DESC"),
    ("on_new_or_updated_image", "retrieveImageList", None, "lastModifiedDate:DESC"),
    ("on_new_snapshot", "retrieveSnapshotList", 1234, "createdDate:DESC"),
])
async def test_poll_documented_payload_baseline_new_items_and_agent_event(transport, monkeypatch, operation, example, parent, order):
    import json
    from pathlib import Path
    from nodes.core.poll_trigger import poll_scope
    payload = json.loads((Path(__file__).parent / "fixtures" / "contabo" / (example + "-examples.json")).read_text())[0]
    args = {"instance_id": parent} if parent else {}
    instance = node(operation, **args)
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        changed, result = mutator(state)
        if changed is not None:
            state = changed
        return result
    monkeypatch.setattr(instance, "_update_node_state", update)
    for rows, count in [([], 0), (payload["data"], len(payload["data"])), (payload["data"], 0)]:
        reply = deepcopy(payload); reply["data"] = deepcopy(rows)
        reply["_pagination"].update(totalElements=len(rows), totalPages=1)
        transport[1].append(reply)
        result = await instance.execute({})
        assert result["data"]["new_item_count"] == count
        assert instance.trigger_produced_no_event(result) is (count == 0)
        assert instance.should_propagate_output(result, {"operation": operation}) is bool(count)
        event = instance.resolve_agent_event(result)
        if count:
            assert "Contabo" in event["text"]
            assert str(rows[0][{"on_new_instance": "instanceId", "on_new_or_updated_image": "imageId", "on_new_snapshot": "snapshotId"}[operation]]) in event["text"]
        else:
            assert event is None
        assert transport[0][-1].url.params["orderBy"] == order
    assert poll_scope(native.ContaboNode, {"operation": operation, **args}) == poll_scope(native.ContaboNode, {"operation": operation, **args, "label": "cosmetic", "goal": "irrelevant"})
    if parent:
        assert poll_scope(native.ContaboNode, {"operation": operation, "instance_id": parent}) != poll_scope(native.ContaboNode, {"operation": operation, "instance_id": parent + 1})
    if operation == "on_new_or_updated_image":
        changed = deepcopy(payload)
        changed["_pagination"].update(totalElements=len(changed["data"]), totalPages=1)
        changed["data"][0]["lastModifiedDate"] = "2026-11-10T12:00:00Z"
        transport[1].append(changed)
        assert (await instance.execute({}))["data"]["new_item_count"] == 1


@pytest.mark.asyncio
async def test_poll_bounded_window_and_failure_never_consume_state(transport, monkeypatch):
    instance = node("on_new_instance")
    filter_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(instance, "_filter_unseen", filter_mock)
    transport[1].append(page([INSTANCE], size=100, total=200, pages=2))
    await instance.execute({})
    assert len(transport[0]) == 1
    filter_mock.assert_awaited_once()
    filter_mock.reset_mock()
    transport[1].append(page([INSTANCE] * 101, size=100, total=200, pages=2))
    with pytest.raises(native.OutcomeUnverified):
        await instance.execute({})
    filter_mock.assert_not_awaited()
    transport[1].append(httpx.Response(401, json={"message": "private"}))
    with pytest.raises(native.ApiError):
        await instance.execute({})
    filter_mock.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("ram", [1024, "1024"])
async def test_instance_poll_schema_number_and_documented_text_ram_emit_agent_event(transport, monkeypatch, ram):
    # The contract declares a number; Contabo's published example uses text.
    # Both representations must reach detection and agent delivery unchanged in identity.
    instance = node("on_new_instance")
    observed = []

    async def unseen(items, event_id):
        observed.extend(event_id(item) for item in items)
        return items

    monkeypatch.setattr(instance, "_filter_unseen", unseen)
    transport[1].append(page([{**INSTANCE, "ramMb": ram}], size=100))
    output = await instance.execute({})
    assert observed == [str(IID)]
    assert output["data"]["new_item_count"] == 1
    item = output["data"]["items"][0]
    assert item["ramMb"] == 1024 and item["instanceId"] == IID
    event = native.ContaboNode.resolve_agent_event(output)
    assert str(IID) in event["text"] and "state running" in event["text"]
    assert "omit" not in repr(output) and "omit" not in event["text"]
