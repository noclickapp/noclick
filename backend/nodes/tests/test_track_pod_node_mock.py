"""Track-POD published request shapes, manual key connection and poll lifecycle.

All HTTP is mocked. The order fixture uses published schema property examples.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from pydantic import ValidationError

from nodes.core.poll_trigger import poll_scope
from nodes.core.registry import NodeFactory
from nodes.track_pod_node import TrackPODAPIKeyCredential, TrackPODNode

TOKEN = "track-pod-test-key"
BASE = "https://api.track-pod.com"
ORDER = json.loads(
    (Path(__file__).parent / "fixtures/track-pod/order.json").read_text()
)["order"]


def node(operation, **values):
    return NodeFactory.create_node(
        node_id="track-pod-test",
        node_type="automation-track-pod",
        node_data={
            "config": {"operation": operation, **values},
            "credentials": {"credential_type": "track_pod_api_key", "api_key": TOKEN},
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,config,method,path,body,query",
    [
        (
            "create_order",
            {
                "body_number": "cv30001-2",
                "client": "Maxima",
                "address": "2 St Josephs Crescent, Liverpool L3 3JF",
                "type": 0,
                "update_address_gps": False,
                "goods_list_json": '[{"GoodsId":"30495","Quantity":10.5}]',
            },
            "POST",
            "/Order",
            {
                "Number": "cv30001-2",
                "Client": "Maxima",
                "Type": 0,
                "Address": "2 St Josephs Crescent, Liverpool L3 3JF",
                "GoodsList": [{"GoodsId": "30495", "Quantity": 10.5}],
            },
            {"updateAddressGps": "false"},
        ),
        (
            "update_order",
            {
                "body_number": "cv30001-2",
                "note": "Only to sign Invoice",
                "force_update": True,
            },
            "PUT",
            "/Order",
            {"Number": "cv30001-2", "Note": "Only to sign Invoice"},
            {"forceUpdate": "true"},
        ),
        (
            "complete_order",
            {"number": "cv30001-2", "cod_actual": 10.5, "signature_name": "John Dow"},
            "PUT",
            "/Order/Number/cv30001-2/Complete",
            {"CODActual": 10.5, "SignatureName": "John Dow"},
            {},
        ),
        (
            "reject_order",
            {"number": "cv30001-2", "reject_reason_id": 19},
            "PUT",
            "/Order/Number/cv30001-2/Reject",
            {"RejectReasonId": 19},
            {},
        ),
        (
            "create_route",
            {
                "route_code": "R0001234",
                "body_date": "2019-02-01",
                "orders_json": "[]",
                "merge_addresses": False,
            },
            "POST",
            "/Route",
            {"Code": "R0001234", "Date": "2019-02-01T00:00:00", "Orders": []},
            {"mergeAddresses": "false"},
        ),
        (
            "update_route",
            {"code": "R0001234", "driver_login": "RT567"},
            "PUT",
            "/Route/Code/R0001234",
            {"DriverLogin": "RT567"},
            {},
        ),
        (
            "move_order_to_route",
            {"code": "R0001234", "number": "cv30001-2", "allow_transfer": False},
            "PUT",
            "/Route/Code/R0001234/Order/Number/cv30001-2",
            None,
            {"allowTransfer": "false"},
        ),
        (
            "delete_route",
            {"code": "R0001234", "delete_orders": False},
            "DELETE",
            "/Route/Code/R0001234",
            None,
            {"deleteOrders": "false"},
        ),
        (
            "create_vehicle",
            {
                "body_number": "XXX777",
                "driver_username": "MyDriver",
                "depot": "9 Riverside, Salford M7 1PA",
            },
            "POST",
            "/Vehicle",
            {
                "Number": "XXX777",
                "DriverUsername": "MyDriver",
                "Depot": "9 Riverside, Salford M7 1PA",
            },
            {},
        ),
        (
            "upsert_address",
            {
                "full_address": "2 St Josephs Crescent, Liverpool, L3 3JF",
                "lat": 25.290479,
            },
            "POST",
            "/Address",
            {
                "FullAddress": "2 St Josephs Crescent, Liverpool, L3 3JF",
                "Lat": 25.290479,
            },
            {},
        ),
    ],
)
async def test_track_pod_published_write_shapes(
    operation, config, method, path, body, query
):
    with respx.mock as router:
        route = router.request(method, BASE + path).mock(
            return_value=httpx.Response(202)
        )
        result = await node(operation, **config).execute({})
    request = route.calls[0].request
    assert request.headers["X-API-KEY"] == TOKEN
    assert request.headers["Accept"] == "application/json"
    assert dict(request.url.params) == query
    assert (json.loads(request.content) if request.content else None) == body
    assert result["status"] == "success" and result["data"] is None


@pytest.mark.asyncio
async def test_track_pod_account_evidence_uses_credential_only():
    with respx.mock as router:
        route = router.get(BASE + "/Driver").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "Name": "Peter G.",
                        "Username": "RT567",
                        "Id": "00000000-0000-0000-0000-000000000000",
                    }
                ],
            )
        )
        result = await node("list_drivers").execute({})
    assert result["data"][0]["Name"] == "Peter G."
    assert len(route.calls) == 1
    assert TrackPODNode.connection_evidence.operation == "list_drivers"
    assert (
        TrackPODAPIKeyCredential(api_key=TOKEN).credential_type == "track_pod_api_key"
    )


@pytest.mark.asyncio
async def test_track_pod_number_is_encoded_as_one_path_segment():
    with respx.mock as router:
        router.get(url__regex=r"https://api\.track-pod\.com/Order/Number/.*").mock(
            return_value=httpx.Response(200, json=ORDER)
        )
        result = await node("get_order", number="ord123/1 +?").execute({})
        request = router.calls[0].request
    assert b"ord123%2F1%20%2B%3F" in request.url.raw_path
    assert result["data"] == ORDER


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,body",
    [
        (401, {"Title": "Invalid X-API-KEY", "Detail": "Key rejected"}),
        (429, {"Detail": "Too Many Requests"}),
        (500, {"Detail": "Internal Server Error"}),
        (200, {"Status": 400, "Detail": "Invalid order"}),
    ],
)
async def test_track_pod_provider_refusal_and_error_envelope_are_not_success(
    status, body
):
    body = {**body, "Detail": body.get("Detail", "") + " " + TOKEN}
    with respx.mock as router:
        route = router.get(BASE + "/Driver").mock(
            return_value=httpx.Response(status, json=body)
        )
        with pytest.raises(ValueError) as error:
            await node("list_drivers").execute({})
    assert TOKEN not in str(error.value)
    assert len(route.calls) == 1


@pytest.mark.asyncio
async def test_track_pod_redirect_does_not_forward_key():
    with respx.mock as router:
        router.get(BASE + "/Driver").mock(
            return_value=httpx.Response(
                302, headers={"Location": "https://other.test/"}
            )
        )
        with pytest.raises(ValueError, match="302"):
            await node("list_drivers").execute({})
        assert len(router.calls) == 1


@pytest.mark.asyncio
async def test_track_pod_poll_baselines_deduplicates_and_emits_status_update():
    instance = node("on_order_status_changed", lookback_minutes=60)
    state = {}

    async def update(mutator, **kwargs):
        new_state, result = mutator(state)
        if new_state is not None:
            state.update(new_state)
        return result

    instance._update_node_state = AsyncMock(side_effect=update)
    current = dict(ORDER)
    with respx.mock as router:
        router.get(url__regex=r"https://api\.track-pod\.com/Order/Status/Date/.*").mock(
            side_effect=lambda request: httpx.Response(200, json=[current.copy()])
        )
        assert (await instance.execute({}))["orders"] == []
        assert (await instance.execute({}))["orders"] == []
        current.update(Status="Not Delivered", StatusDate="2019-02-01T16:31:00")
        output = await instance.execute({})
        assert output["orders"] == [current]
        assert (await instance.execute({}))["orders"] == []
        since = str(router.calls[0].request.url.path).split("/Date/")[1]
        age = datetime.now(timezone.utc) - datetime.fromisoformat(since)
        assert 3590 < age.total_seconds() < 3610
    event = TrackPODNode.resolve_agent_event(output)
    for value in [
        "cv30001-2",
        "Maxima",
        "Liverpool",
        "Not Delivered",
        ORDER["TrackId"],
        ORDER["Id"],
    ]:
        assert value in event["text"]
    assert TrackPODNode.should_propagate_output(
        output, {"operation": "on_order_status_changed"}
    )
    assert not TrackPODNode.should_propagate_output(
        {"new_order_count": 0}, {"operation": "on_order_status_changed"}
    )
    assert poll_scope(
        TrackPODNode,
        {"operation": "on_order_status_changed", "lookback_minutes": 60, "label": "a"},
    ) == poll_scope(
        TrackPODNode,
        {"operation": "on_order_status_changed", "lookback_minutes": 60, "label": "b"},
    )
    assert poll_scope(
        TrackPODNode, {"operation": "on_order_status_changed", "lookback_minutes": 60}
    ) != poll_scope(
        TrackPODNode, {"operation": "on_order_status_changed", "lookback_minutes": 120}
    )


@pytest.mark.parametrize(
    "operation,values",
    [
        ("create_order", {}),
        ("update_order", {}),
        ("create_vehicle", {"body_number": "XXX777"}),
        ("upsert_address", {}),
        ("on_order_status_changed", {"lookback_minutes": 1440}),
        ("list_updated_orders", {"date": "bad-date"}),
        (
            "create_order",
            {"client": "Maxima", "address": "Liverpool", "goods_list_json": "{}"},
        ),
    ],
)
def test_track_pod_invalid_required_inputs(operation, values):
    with pytest.raises((ValueError, ValidationError)):
        node(operation, **values)
