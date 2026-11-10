"""Test Bungie request serialization, account evidence and poll state offline.

Synthetic responses use the published contract's fields. The conformance harness
independently checks these operations against the unchanged provider contract.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
import json

import httpx
import pytest
from pydantic import ValidationError
from nodes import bungie_node as b

AUTH = {"credential_type": "bungie_token", "api_key": "bungie-unit-key", "access_token": "bungie-unit-token"}
CHAR = {"membershipType": 3, "destinyMembershipId": 4611686018467237196, "characterId": 2305843009264970629}
ITEM = {"membershipType": 3, "characterId": CHAR["characterId"], "itemId": 6917529812345678901}
ACTIVITY = json.loads((Path(__file__).parent / "fixtures/bungie/activity_history.json").read_text())["body"]["Response"]["activities"][0]


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    async def send(request):
        requests.append(request)
        assert request.url.host == "www.bungie.net"
        assert request.headers["X-API-Key"] == AUTH["api_key"]
        assert request.headers["Authorization"] == "Bearer " + AUTH["access_token"]
        status, data = replies.pop(0)
        return httpx.Response(status, json=data)
    @asynccontextmanager
    async def client():
        async with httpx.AsyncClient(transport=httpx.MockTransport(send)) as value:
            yield value
    monkeypatch.setattr(b, "guarded_async_client", client)
    return requests, replies


def node(operation, args=None):
    raw = {"config": {"operation": operation, **(args or {})}, "credentials": AUTH}
    return b.BungieNode("bungie-test", "automation-bungie", raw, config=b.BungieNode.parse_config(raw))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,args,path", [
    ("equip_item", ITEM, "Items/EquipItem"),
    ("equip_items", {"membershipType": 3, "characterId": CHAR["characterId"], "itemIds": [ITEM["itemId"]]}, "Items/EquipItems"),
    ("transfer_item", {**ITEM, "itemReferenceHash": 123, "stackSize": 1, "transferToVault": True}, "Items/TransferItem"),
    ("pull_from_postmaster", {**ITEM, "itemReferenceHash": 123, "stackSize": 1}, "Items/PullFromPostmaster"),
    ("set_item_lock_state", {**ITEM, "state": False}, "Items/SetLockState"),
    ("equip_loadout", {"membershipType": 3, "characterId": CHAR["characterId"], "loadoutIndex": 0}, "Loadouts/EquipLoadout"),
    ("snapshot_loadout", {"membershipType": 3, "characterId": CHAR["characterId"], "loadoutIndex": 0, "colorHash": 1, "iconHash": 2, "nameHash": 3}, "Loadouts/SnapshotLoadout"),
])
async def test_action_bodies(transport, operation, args, path):
    requests, replies = transport
    replies.append((200, {"ErrorCode": 1, "Response": 0}))
    assert await node(operation, args).execute({}) == {"data": 0}
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/Platform/Destiny2/Actions/" + path + "/"
    assert json.loads(requests[0].content) == args


@pytest.mark.asyncio
async def test_identity_query_components_and_pagination(transport):
    requests, replies = transport
    replies.append((200, {"ErrorCode": 1, "Response": {"bungieNetUser": {"displayName": "Guardian"}}}))
    output = await node("get_current_user").execute({})
    assert output["data"]["bungieNetUser"]["displayName"] == "Guardian"
    assert requests[-1].url.path == "/Platform/User/GetMembershipsForCurrentUser/"
    assert not requests[-1].content
    replies.append((200, {"ErrorCode": 1, "Response": {}}))
    await node("get_profile", {"membershipType": 3, "destinyMembershipId": CHAR["destinyMembershipId"], "components": [100, 200]}).execute({})
    assert requests[-1].url.params["components"] == "100,200"
    replies.append((200, {"ErrorCode": 1, "Response": {"activities": []}}))
    await node("get_activity_history", {**CHAR, "count": 50, "page": 2}).execute({})
    assert dict(requests[-1].url.params) == {"count": "50", "mode": "0", "page": "2"}


@pytest.mark.asyncio
@pytest.mark.parametrize("response,error", [
    ({"ErrorCode": 99, "Message": "Authentication is required"}, "Authentication is required"),
    ({"ErrorCode": 1}, "missing Response"),
    ([], "invalid response envelope"),
    ({"ErrorCode": 99, "Message": AUTH["access_token"]}, "redacted"),
])
async def test_error_envelopes_cannot_verify_connection(transport, response, error):
    transport[1].append((200, response))
    with pytest.raises(ValueError, match=error):
        await node("get_current_user").execute({})


@pytest.mark.asyncio
async def test_http_rejection(transport):
    transport[1].append((401, {"Message": "Unauthorized"}))
    with pytest.raises(httpx.HTTPStatusError):
        await node("get_current_user").execute({})


@pytest.mark.asyncio
async def test_poll_baseline_dedup_scope_and_agent_event(transport):
    from nodes.core.poll_trigger import poll_scope
    instance = node("on_new_activity", CHAR)
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        updated, result = mutator(deepcopy(state))
        if updated is not None:
            state = updated
        return result
    instance._update_node_state = update
    transport[1].append((200, {"ErrorCode": 1, "Response": {"activities": [ACTIVITY]}}))
    assert (await instance.execute({}))["activities"] == []
    assert instance.trigger_produced_no_event({})
    newer = {**ACTIVITY, "activityDetails": {"instanceId": 12345678902, "mode": 4}}
    transport[1].append((200, {"ErrorCode": 1, "Response": {"activities": [newer, ACTIVITY]}}))
    output = await instance.execute({})
    assert output["activities"] == [newer]
    event = instance.resolve_agent_event(output)
    assert str(CHAR["characterId"]) in event["text"]
    assert "12345678902" in event["text"]
    transport[1].append((200, {"ErrorCode": 1, "Response": {"activities": [newer, ACTIVITY]}}))
    assert (await instance.execute({}))["activities"] == []
    config = {"operation": "on_new_activity", **CHAR}
    assert poll_scope(b.BungieNode, config) != poll_scope(b.BungieNode, {**config, "characterId": 42})
    assert dict(transport[0][0].url.params) == {"count": "250", "mode": "0", "page": "0"}


@pytest.mark.parametrize("key", ["api_key", "access_token"])
@pytest.mark.parametrize("value", ["", "https://example.com/token", "Bearer token", "<token>"])
def test_manual_credential_validation(key, value):
    with pytest.raises(ValidationError):
        b.BungieTokenCredential(**{**AUTH, key: value})


def test_default_credential_type_and_declared_scopes():
    assert b.BungieTokenCredential(api_key=AUTH["api_key"], access_token=AUTH["access_token"]).credential_type == "bungie_token"
    assert set(b.BUNGIE_SCOPES.declared_scopes()) == {"ReadBasicUserProfile", "ReadDestinyInventoryAndVault", "MoveEquipDestinyItems"}


@pytest.mark.asyncio
@pytest.mark.parametrize("memberships", [[{"displayName": "Guardian", "membershipId": "123"}], []])
async def test_connect_shows_membership_names_or_bungie_identity(monkeypatch, memberships):
    from unittest.mock import AsyncMock
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core import run_op
    call = AsyncMock(return_value={"data": {"destinyMemberships": memberships,
                                            "bungieNetUser": {"displayName": "Bungie Guardian"}}})
    monkeypatch.setattr(run_op, "run_node_operation", call)
    evidence = await collect_evidence(node_type="automation-bungie", user_id="bungie-test", credential_data=AUTH)
    assert evidence.reachable is True
    if memberships:
        assert [sample.label for sample in evidence.samples] == ["Guardian"]
        assert call.await_count == 1
    else:
        assert evidence.account_label == "Bungie Guardian"


def test_int64_ids_stay_text_in_the_editor_and_exact_on_the_wire():
    schema = b.BungieNode.get_config_schema()
    assert schema["$defs"]["BungieGetProfileConfig"]["properties"]["destinyMembershipId"]["type"] == "string"
    assert schema["$defs"]["BungieEquipItemsConfig"]["properties"]["itemIds"]["items"]["type"] == "string"
    config = node("equip_item", ITEM).config.config
    assert config.itemId == "6917529812345678901"
    assert int(config.itemId) == ITEM["itemId"]


@pytest.mark.parametrize("value", ["-1", "1/2", "9223372036854775808", "1e18", True])
def test_invalid_decimal_ids_are_rejected(value):
    with pytest.raises(ValueError):
        node("equip_item", {**ITEM, "itemId": value})
