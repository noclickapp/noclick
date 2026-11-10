"""TrackingMore parsers and polling use the provider's published quick-start response."""
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nodes import trackingmore_node as tm
from nodes.core.poll_trigger import poll_scope

FIXTURES = Path(__file__).parent / "fixtures" / "trackingmore"
RESPONSE = json.loads((FIXTURES / "get_results.json").read_text())
COURIER = json.loads((FIXTURES / "courier.json").read_text())
KEY = {"credential_type": "trackingmore_api_key", "api_key": "test-trackingmore-secret"}
SINCE = "2022-09-10T10:40:34+08:00"  # Get results query example in provider's OpenAPI.


def node(config):
    raw = {"credentials": dict(KEY), "config": config}
    return tm.TrackingMoreNode("tm", "automation-trackingmore", raw, config=tm.TrackingMoreNode.parse_config(raw))


def state_for(instance):
    state = {}
    async def update(mutator, **kwargs):
        next_state, output = mutator(copy.deepcopy(state))
        if next_state is not None:
            state.clear()
            state.update(next_state)
        return output
    instance._update_node_state = update
    return state


def test_documented_shipments_are_projected_without_contact_data():
    row = RESPONSE["data"][0]
    result = tm.shipments(RESPONSE["data"], KEY, requested=[row["tracking_number"]], code=row["courier_code"], checkpoint_limit=1)
    assert result[0]["id"] == row["id"]
    assert result[0]["update_at"] == row["update_at"]
    assert result[0]["origin_info_checkpoints"] == [{k: v for k, v in row["origin_info"]["trackinfo"][0].items()
        if k in {"checkpoint_date", "checkpoint_delivery_status", "checkpoint_delivery_substatus", "country_iso2"} and v is not None}]
    assert "customer_email" not in result[0] and "latest_event" not in result[0]
    assert "tracking_detail" not in result[0]["origin_info_checkpoints"][0]


@pytest.mark.parametrize("change", [{"tracking_number": "OTHER"}, {"courier_code": "other"}, {"id": ""}])
def test_foreign_or_malformed_shipment_is_refused(change):
    row = RESPONSE["data"][0]
    with pytest.raises(ValueError):
        tm.shipments([{**row, **change}], KEY, requested=[row["tracking_number"]], code=row["courier_code"])


def test_courier_continuation_binds_key_query_and_catalog():
    rows = tm.couriers([COURIER], KEY)
    token = tm.continuation(KEY, "list_couriers", {"limit": 1, "search": ""}, 1, "snapshot")
    with pytest.raises(ValueError):
        tm.position(token, {**KEY, "api_key": "other-test-secret"}, "list_couriers", {"limit": 1, "search": ""}, maximum=10, snapshot="snapshot")
    with pytest.raises(ValueError):
        tm.local_courier_page(rows, KEY, purpose="list_couriers", limit=1, token="1")


@pytest.mark.asyncio
async def test_poll_baselines_then_emits_new_documented_items_once(monkeypatch):
    instance = node({"operation": "on_new_or_updated_shipment", "updated_date_min": SINCE})
    state = state_for(instance)
    request = AsyncMock(side_effect=[[], RESPONSE["data"], RESPONSE["data"]])
    monkeypatch.setattr(tm, "request", request)
    first = await instance.execute({})
    assert first["new_shipment_count"] == 0 and state["seen_ids"] == []
    second = await instance.execute({})
    assert second["new_shipment_count"] == 1
    event = tm.TrackingMoreNode.resolve_agent_event(second)
    row = RESPONSE["data"][0]
    assert event["conversation_key"] == row["id"]
    assert row["tracking_number"] in event["text"] and row["courier_code"] in event["text"] and row["delivery_status"] in event["text"]
    assert "get_tracking_result" in event["text"]
    assert tm.TrackingMoreNode.should_propagate_output(second, {"operation": "on_new_or_updated_shipment"})
    assert (await instance.execute({}))["new_shipment_count"] == 0
    assert request.await_args.kwargs["params"] == {"updated_date_min": SINCE, "items_amount": 100, "pages_amount": 1}


@pytest.mark.asyncio
async def test_poll_existing_shipments_baseline_and_changed_versions(monkeypatch):
    instance = node({"operation": "on_new_or_updated_shipment", "updated_date_min": SINCE})
    state = state_for(instance)
    monkeypatch.setattr(tm, "request", AsyncMock(return_value=RESPONSE["data"]))
    assert (await instance.execute({}))["new_shipment_count"] == 0
    # A previous version's key must not hide an update. The response stays verbatim.
    row = RESPONSE["data"][0]
    state["seen_ids"] = [json.dumps([row["id"], "previous-version", row["delivery_status"]])]
    assert (await instance.execute({}))["new_shipment_count"] == 1
    assert (await instance.execute({}))["new_shipment_count"] == 0


def test_poll_scope_ignores_canvas_metadata_but_tracks_filters():
    config = {"operation": "on_new_or_updated_shipment", "updated_date_min": SINCE}
    assert poll_scope(tm.TrackingMoreNode, config) == poll_scope(tm.TrackingMoreNode, {**config, "label": "New title", "goal": "new goal"})
    assert poll_scope(tm.TrackingMoreNode, config) != poll_scope(tm.TrackingMoreNode, {**config, "courier_code": "usps"})


@pytest.mark.asyncio
async def test_poll_refuses_missing_version_and_duplicate_collection(monkeypatch):
    instance = node({"operation": "on_new_or_updated_shipment", "updated_date_min": SINCE})
    state_for(instance)
    row = dict(RESPONSE["data"][0]); row.pop("update_at")
    monkeypatch.setattr(tm, "request", AsyncMock(return_value=[row]))
    assert (await instance.execute({}))["status"] == "error"
    # Duplicate response rows must not become a successful baseline.
    monkeypatch.setattr(tm, "request", AsyncMock(return_value=RESPONSE["data"] * 100))
    detect = AsyncMock(); instance._filter_unseen = detect
    assert (await instance.execute({}))["status"] == "error"
    detect.assert_not_awaited()


@pytest.mark.parametrize("value", [b'{"meta":1,"meta":2}', b'{"data":NaN}', b'{"data":1e999}'])
def test_invalid_json_is_rejected(value):
    with pytest.raises(ValueError):
        tm.parse_json(value)


@pytest.mark.parametrize("code", ["UPPERCASE", "with_underscore", "https://usps.com/"])
def test_courier_inputs_match_the_provider_pattern(code):
    with pytest.raises(ValueError):
        tm.GetTrackingResult(tracking_number=RESPONSE["data"][0]["tracking_number"], courier_code=code)
