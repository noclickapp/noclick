"""Exercise Club OS's documented request shapes and creation-time triggers offline.
Fixtures copy the provider's field examples; they are not live-account recordings.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes.club_os_node import ClubOSNode, ClubOSTokenCredential
from nodes.core.poll_trigger import poll_scope

FIXTURE = json.loads((Path(__file__).parent / "fixtures/club-os/documented_fields.json").read_text())
TOKEN = "club-os-test-private-token"


def node(config):
    return ClubOSNode(node_id="club", node_type="automation-club-os", node_data={"config": config},
        config=ClubOSNode.parse_config({"config": config, "credentials": {"credential_type": "club_os_token", "api_token": TOKEN}}))


@pytest.fixture
def transport(monkeypatch):
    calls = []
    state = {"body": {}, "status": 200}
    original = httpx.AsyncClient
    def handle(request):
        calls.append(request)
        return httpx.Response(state["status"], json=state["body"])
    monkeypatch.setattr("nodes.club_os_node.httpx.AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    monkeypatch.setattr(ClubOSNode, "emit", AsyncMock())
    return calls, state


@pytest.mark.asyncio
async def test_club_os_connection_evidence_is_account_locations(transport):
    calls, state = transport
    state["body"] = [{"location": FIXTURE["location"]}]
    output = await node({"operation": "list_locations"}).execute({})
    assert output["data"][0]["name"] == "Chicago Wicker Park"
    assert calls[0].url == "http://api2.club-os.com/access/locations"
    assert calls[0].headers["Authorization"] == TOKEN
    assert "Bearer" not in calls[0].headers["Authorization"]


@pytest.mark.asyncio
async def test_club_os_create_booking_body_and_query_placement(transport):
    calls, _ = transport
    config = {"operation": "create_pt_booking", "location_id": 2870, "staff_id": 129934079,
        "customer_id": 133165588, "start_time": "2016-08-01T17:00:00.000Z", "duration": 60, "service_id": 1234}
    await node(config).execute({})
    req = calls[0]
    assert req.method == "POST"
    assert req.url.path == "/locations/2870/staff/129934079/pt-bookings"
    assert dict(req.url.params) == {"locationId": "2870", "staffId": "129934079"}
    assert json.loads(req.content) == {**FIXTURE["booking_body"], "customerId": 133165588}


@pytest.mark.asyncio
async def test_club_os_cancel_attendee_is_one_patch(transport):
    calls, _ = transport
    await node({"operation": "update_event_attendee", "location_id": 2870, "event_id": 28537526,
        "customer_id": 133165588, "series_start_time": "2016-08-01T17:00:00.000Z", "attendee_status": "CANCEL"}).execute({})
    assert len(calls) == 1
    assert calls[0].method == "PATCH"
    assert calls[0].url.path == "/locations/2870/events/28537526/attendees"
    assert dict(calls[0].url.params) == {"customerId": "133165588", "seriesStartTime": "2016-08-01T17:00:00.000Z", "attendeeStatus": "CANCEL"}


@pytest.mark.asyncio
async def test_club_os_get_event_retains_required_series_start(transport):
    calls, _ = transport
    await node({"operation": "get_event", "event_id": 28537526, "start_time_start_at": "2016-08-01T17:00:00.000Z"}).execute({})
    assert calls[0].url.path == "/events/28537526"
    assert dict(calls[0].url.params) == {"startTimeStartAt": "2016-08-01T17:00:00.000Z"}


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,fixture,who,identifier", [
    ("on_new_lead", "lead", "Richard Richardson", "customerId"),
    ("on_new_sales_event", "sales_event", "Waylon Smithers", "eventId"),
])
async def test_club_os_poll_baseline_new_items_dedup_and_agent(transport, operation, fixture, who, identifier):
    calls, response = transport
    config = {"operation": operation, "club_id": 123, "location_id": 2870}
    n = node(config)
    state = {}
    async def update(mutator, **kwargs):
        changed, result = mutator(dict(state))
        if changed is not None:
            state.clear(); state.update(changed)
        return result
    n._update_node_state = update
    response["body"] = dict(FIXTURE[fixture])
    first = await n.execute({})
    assert first["new_count"] == 0
    response["body"] = {**FIXTURE[fixture], identifier: 999999}
    new = await n.execute({})
    assert new["new_count"] == 1
    assert ClubOSNode.should_propagate_output(new, config)
    event = ClubOSNode.resolve_agent_event(new)
    assert who in event["text"] and "999999" in event["text"]
    assert "Chicago Wicker Park" in event["text"]
    assert (await n.execute({}))["new_count"] == 0
    params = dict(calls[-1].url.params)
    assert params["clubId"] == "123" and params["locationId"] == "2870"
    assert "startAt" in params if fixture == "lead" else "createdAtStartAt" in params


def test_club_os_poll_scope_changes_only_with_declared_watch_fields():
    config = {"operation": "on_new_lead", "club_id": 123, "location_id": 2870}
    scope = poll_scope(ClubOSNode, config)
    assert scope is not None
    assert scope == poll_scope(ClubOSNode, {**config, "label": "Renamed", "goal": "New instruction"})
    assert scope != poll_scope(ClubOSNode, {**config, "location_id": 2871})
    assert scope != poll_scope(ClubOSNode, {**config, "lookback_hours": 48})


@pytest.mark.asyncio
async def test_club_os_rejection_preserves_provider_words_without_token(transport):
    calls, state = transport
    state.update(status=401, body={"message": "Unauthorized " + TOKEN})
    with pytest.raises(ValueError, match="Unauthorized") as error:
        await node({"operation": "list_locations"}).execute({})
    assert TOKEN not in str(error.value)
    assert len(calls) == 1


def test_club_os_token_default_and_header_rejection():
    assert ClubOSTokenCredential(api_token=TOKEN).credential_type == "club_os_token"
    with pytest.raises(ValidationError):
        ClubOSTokenCredential(api_token="Bearer " + TOKEN)
