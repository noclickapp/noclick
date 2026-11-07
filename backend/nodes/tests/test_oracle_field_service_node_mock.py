"""Native schema/factory/connect/wire regression tests; synthetic responses only."""
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
import base64
import json

import httpx
import pytest

from nodes import oracle_field_service_node as p
from nodes.core.registry import NodeFactory
from nodes.core import credential_connect, connection_evidence

KEY = {"credential_type": "oracle_field_service_basic", "instance_name": "fixture-env", "auth_instance_name": "Fixture.test", "client_id": "fixture-app", "client_secret": "synthetic-secret"}
BEARER = {"credential_type": "oracle_field_service_bearer", "instance_name": "fixture-env", "access_token": "synthetic-token", "expires_at": "2999-01-01T00:00:00Z"}
RESOURCE = {"resourceId": "bucket.1", "resourceType": "BK", "status": "active", "parentResourceId": "root", "name": "omit-personal-name", "phone": "omit-phone", "avatar": {"href": "https://private.example.test"}}
ACTIVITY = {"activityId": 11, "resourceId": "bucket.1", "activityType": "IN", "status": "pending", "recordType": "regular", "apptNumber": "fixture-reference", "customerName": "omit-customer", "customerPhone": "omit-phone", "secret_property": "omit-value"}
TYPE = {"label": "IN", "name": "Internal", "active": True, "features": {"allowCreationInBuckets": True, "allowNonScheduled": True, "isSegmentingEnabled": False, "isTeamworkAvailable": False}}
BUCKET_TYPES = {"items": [{"label": "BK", "name": "Bucket", "active": True, "role": "bucket"}], "offset": 0, "limit": 100, "totalResults": 1}


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def wire(monkeypatch):
    replies, calls = [], []
    @asynccontextmanager
    async def client(**options):
        assert options == {"timeout": 12, "follow_redirects": False, "trust_env": False}
        class Client:
            @asynccontextmanager
            async def stream(self, method, url, **kwargs):
                calls.append((method, url, kwargs))
                status, body = replies.pop(0)
                yield httpx.Response(status, content=body if isinstance(body, bytes) else json.dumps(body).encode(), headers={"content-type": "application/json"}, request=httpx.Request(method, url))
        yield Client()
    monkeypatch.setattr(p, "guarded_async_client", client)
    return replies, calls


def node(config, key=KEY):
    return NodeFactory.create_node("fixture", "automation-oracle-field-service", {"config": config, "credentials": deepcopy(key)}, user_id="fixture-owner")


def test_real_native_schema_and_exact_seventeen_actions():
    schema = p.OracleFieldServiceNode.get_config_schema()
    actions = {schema["$defs"][ref["$ref"].split("/")[-1]]["properties"]["operation"]["const"] for ref in schema["properties"]["config"]["oneOf"]}
    assert actions == p.OPERATIONS and len(actions) == 17
    assert schema["$defs"]["GetActivity"]["properties"]["activity_id"]["x-dynamic-options"]["depends_on"] == "resource_id"
    assert "oauth" not in schema["$defs"]["OracleFieldServiceBearerCredential"]["properties"]


@pytest.mark.parametrize("bad", [True, 1.5, "1e3", "01", "0", "9223372036854775808"])
def test_actual_factory_rejects_noncanonical_activity_ids(bad):
    with pytest.raises(ValueError): node({"operation": "get_activity", "resource_id": "bucket.1", "activity_id": bad})


@pytest.mark.parametrize("bad", ["https://attacker.example", "localhost", "host.fs.ocs.oraclecloud.com", "host:443", "host/path", "host%2e", "-host"])
def test_actual_factory_refuses_arbitrary_host_and_url_credentials(bad):
    # localhost as a label still builds an Oracle subdomain, not loopback; it is
    # harmless DNS syntax and is handled by public-address resolution later.
    if bad == "localhost":
        assert p.guard({**KEY, "instance_name": bad}).instance_name == bad
    else:
        with pytest.raises(ValueError): node({"operation": "list_resources"}, {**KEY, "instance_name": bad})


@pytest.mark.asyncio
async def test_real_factory_resource_fields_basic_wire_and_privacy(wire):
    replies, calls = wire
    replies.append((200, {"items": [RESOURCE], "totalResults": 1, "offset": 0, "limit": 50}))
    result = await node({"operation": "list_resources"}).execute({})
    assert result["items"][0]["id"] == "bucket.1" and result["has_more"] is False
    assert "omit-" not in json.dumps(result)
    method, url, kwargs = calls[0]
    assert url == "https://fixture-env.fs.ocs.oraclecloud.com/rest/ofscCore/v1/resources"
    assert base64.b64decode(kwargs["headers"]["Authorization"].split()[1]).decode() == "fixture-app@Fixture.test:synthetic-secret"
    assert kwargs["params"]["fields"] == p.RESOURCE_FIELDS and "expand" not in kwargs["params"]


@pytest.mark.asyncio
async def test_activity_scope_dates_short_page_continuation_and_projection(wire):
    replies, calls = wire
    replies.extend([(200, RESOURCE), (200, {"items": [ACTIVITY], "limit": 50, "offset": 0, "hasMore": True})])
    result = await node({"operation": "list_activities", "resource_id": "bucket.1", "date_from": "2026-10-01", "date_to": "2026-10-06", "status": "pending"}).execute({})
    assert result["next_offset"] == 1 and result["has_more"] is True
    assert "omit-" not in json.dumps(result)
    assert calls[-1][2]["params"] == {"offset": 0, "limit": 50, "resources": "bucket.1", "includeChildren": "none", "includeNonScheduled": "true", "fields": p.ACTIVITY_FIELDS, "dateFrom": "2026-10-01", "dateTo": "2026-10-06", "q": "status=='pending'"}


@pytest.mark.asyncio
async def test_create_is_nonscheduled_bucket_bound_and_read_back(wire):
    replies, calls = wire
    replies.extend([(200, RESOURCE), (200, BUCKET_TYPES), (200, TYPE), (201, ACTIVITY), (200, ACTIVITY)])
    result = await node({"operation": "create_nonscheduled_activity", "resource_id": "bucket.1", "activity_type_label": "IN", "appointment_reference": "fixture-reference"}).execute({})
    assert result["created"] is True and len(result["snapshot"]) == 64
    assert calls[3][2]["json"] == {"resourceId": "bucket.1", "activityType": "IN", "apptNumber": "fixture-reference"}
    assert all("custom-actions" not in call[1] for call in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"role": "resource"}, {"active": False}])
async def test_create_refuses_technician_or_inactive_type_before_write(wire, change):
    replies, calls = wire
    rows = deepcopy(BUCKET_TYPES)
    rows["items"][0].update(change)
    replies.extend([(200, RESOURCE), (200, rows)])
    with pytest.raises(ValueError):
        await node({"operation": "create_nonscheduled_activity", "resource_id": "bucket.1", "activity_type_label": "IN", "appointment_reference": "fixture-reference"}).execute({})
    assert all(call[0] == "GET" for call in calls)


@pytest.mark.asyncio
async def test_update_only_reference_and_delete_has_separate_absence_readback(wire):
    replies, calls = wire
    original = p.record(ACTIVITY, "activity")
    updated = {**ACTIVITY, "apptNumber": "new-reference"}
    replies.extend([(200, ACTIVITY), (200, RESOURCE), (200, BUCKET_TYPES), (200, updated), (200, updated)])
    result = await node({"operation": "update_activity_reference", "resource_id": "bucket.1", "activity_id": "11", "expected_snapshot": p.snapshot(original), "appointment_reference": "new-reference"}).execute({})
    assert result["updated"] is True and calls[3][2]["json"] == {"apptNumber": "new-reference"}
    replies.extend([(200, updated), (200, RESOURCE), (200, BUCKET_TYPES), (204, b""), (404, {"detail": "not returned"})])
    result = await node({"operation": "delete_nonscheduled_activity", "resource_id": "bucket.1", "activity_id": "11", "expected_snapshot": result["snapshot"], "expected_reference": "new-reference"}).execute({})
    assert result["deletion_accepted"] is True and result["absence_observed"] is True and result["absence_status"] == 404
    assert [call[0] for call in calls[-2:]] == ["DELETE", "GET"] and "erased" not in result


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"resourceId": "bucket.2"}, {"status": "started"}, {"date": "2026-10-06"}, {"recordType": "multiday_activity"}])
async def test_write_refuses_foreign_parent_or_active_scheduled_record(wire, change):
    replies, calls = wire
    replies.append((200, {**ACTIVITY, **change}))
    with pytest.raises(ValueError):
        await node({"operation": "delete_nonscheduled_activity", "resource_id": "bucket.1", "activity_id": "11", "expected_snapshot": p.snapshot(p.record(ACTIVITY, "activity")), "expected_reference": "fixture-reference"}).execute({})
    assert len(calls) == 1 and calls[0][0] == "GET"


@pytest.mark.asyncio
async def test_delete_204_alone_does_not_claim_absence(wire):
    replies, calls = wire
    replies.extend([(200, ACTIVITY), (200, RESOURCE), (200, BUCKET_TYPES), (204, b""), (200, ACTIVITY)])
    with pytest.raises(ValueError, match="still visible"):
        await node({"operation": "delete_nonscheduled_activity", "resource_id": "bucket.1", "activity_id": "11", "expected_snapshot": p.snapshot(p.record(ACTIVITY, "activity")), "expected_reference": "fixture-reference"}).execute({})
    assert len(calls) == 5


@pytest.mark.asyncio
async def test_picker_string_ids_bind_parent_search_and_credential(wire):
    replies, _ = wire
    replies.extend([(200, RESOURCE), (200, {"items": [ACTIVITY], "hasMore": True})])
    page = await p.OracleFieldServiceNode.load_field_options("activity_id", KEY, context={"resource_id": "bucket.1"}, search="11")
    assert page["options"][0]["value"] == "11"
    for key, context, search in [(KEY, {"resource_id": "bucket.2"}, "11"), (KEY, {"resource_id": "bucket.1"}, "other"), ({**KEY, "client_secret": "replacement"}, {"resource_id": "bucket.1"}, "11")]:
        with pytest.raises(ValueError, match="continuation"):
            await p.OracleFieldServiceNode.load_field_options("activity_id", key, context=context, search=search, page_token=page["next_page_token"])


@pytest.mark.asyncio
async def test_bearer_header_and_expired_token_no_io(wire):
    replies, calls = wire
    replies.append((200, {"items": []}))
    await node({"operation": "list_resources"}, BEARER).execute({})
    assert calls[0][2]["headers"]["Authorization"] == "Bearer synthetic-token"
    with pytest.raises(ValueError, match="expired"):
        await node({"operation": "list_resources"}, {**BEARER, "expires_at": "2000-01-01T00:00:00Z"}).execute({})
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(302, b"redirect"), (401, {"detail": "synthetic-secret"}), (429, {"detail": "synthetic-secret"}), (500, {"detail": "synthetic-secret"}), (200, b'{"items":[],"items":[]}'), (200, b'{"items":[],"number":NaN}')])
async def test_safe_errors_no_echo_or_retry(wire, status, body):
    replies, calls = wire
    replies.append((status, body))
    with pytest.raises(ValueError) as error: await node({"operation": "list_resources"}).execute({})
    assert len(calls) == 1 and "synthetic-secret" not in str(error.value) and "fixture-env" not in str(error.value)


@pytest.mark.asyncio
async def test_visible_only_actual_connect_and_empty_reachability(wire, monkeypatch):
    replies, calls = wire
    visible = {k: v for k, v in KEY.items() if k != "credential_type"}
    replies.append((200, {"items": []}))
    credential_connect._class_index.cache_clear()
    monkeypatch.setattr(credential_connect, "_collect_evidence", connection_evidence.collect_evidence)
    verdict = await credential_connect.validate_for_connect(credential_type=KEY["credential_type"], credential_data=visible, user_id="fixture-owner")
    assert verdict.ok and verdict.credential_data["credential_type"] == KEY["credential_type"] and verdict.credential_data["service_variant"] == "oracle_field_service"
    assert verdict.evidence.reachable is True
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_property_entity_and_capacity_area_response_are_bound(wire):
    replies, calls = wire
    replies.append((200, {"label": "property", "entity": "resource", "type": "enumeration"}))
    with pytest.raises(ValueError, match="different entity"):
        await node({"operation": "list_property_enumerations", "entity": "activity", "property_label": "property"}).execute({})
    assert len(calls) == 1
    replies.extend([(200, {"label": "area", "type": "area", "status": "active"}), (200, {"items": [{"date": "2026-10-06", "areas": [{"label": "other", "calendar": []}]}]})])
    with pytest.raises(ValueError, match="different or repeated area"):
        await node({"operation": "get_available_capacity", "capacity_area_label": "area", "dates": ["2026-10-06"]}).execute({})


@pytest.mark.asyncio
async def test_actual_capacity_action_projects_fixed_area_date_metrics(wire):
    replies, calls = wire
    replies.extend([(200, {"label": "area", "type": "area", "status": "active"}), (200, {"items": [{"date": "2026-10-06", "areas": [{"label": "area", "calendar": [{"count": [4], "minutes": [240]}], "available": [{"count": [2], "minutes": [120]}], "private_property": "omit-capacity"}]}]})])
    result = await node({"operation": "get_available_capacity", "capacity_area_label": "area", "dates": ["2026-10-06"]}).execute({})
    assert result["items"][0]["areas"][0]["available"][0]["minutes"] == [120]
    assert "omit-capacity" not in json.dumps(result)
    assert calls[-1][2]["params"]["areas"] == "area" and calls[-1][2]["params"]["aggregateResults"] == "false"


@pytest.mark.parametrize("payload", [{"items": [], "hasMore": True}, {"items": [ACTIVITY, ACTIVITY], "hasMore": False}, {"items": [ACTIVITY], "offset": True}, {"items": [ACTIVITY], "totalResults": -1}])
def test_real_response_projection_refuses_stalled_repeated_and_malformed_pages(payload):
    with pytest.raises(ValueError): p.page_record(payload, "activity", 0, 50, "bucket.1")


def test_activity_absent_hasmore_is_terminal_but_metadata_full_page_is_conservative():
    assert p.page_record({"items": [ACTIVITY]}, "activity", 0, 1, "bucket.1")["has_more"] is False
    assert p.page_record({"items": [RESOURCE]}, "resource", 0, 1)["next_offset"] == 1


def test_capacity_preserves_documented_integer_values_without_invented_minimum():
    payload = {"items": [{"date": "2026-10-06", "areas": [{"label": "area", "available": [{"count": [-1], "minutes": [-30]}]}]}]}
    assert p.capacity_record(payload, "area", {"2026-10-06"})["items"][0]["areas"][0]["available"][0]["minutes"] == [-30]
    payload["items"][0]["areas"][0]["available"][0]["count"] = [True]
    with pytest.raises(ValueError): p.capacity_record(payload, "area", {"2026-10-06"})
