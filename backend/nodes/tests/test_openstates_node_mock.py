"""Open States v3 routes, API-key placement, public evidence and bill polling.

Bill field examples are copied from the pinned provider OpenAPI's Bill schema:
https://v3.openstates.org/openapi.json (2021.11.12). Timestamps and pagination
exercise the documented date-time and integer schemas; no live account is used.
"""
from copy import deepcopy
from unittest.mock import Mock

import httpx
import pytest
import respx
from pydantic import ValidationError

from nodes.openstates_node import OpenStatesAPIKeyCredential, OpenStatesNode, OpenStatesNodeConfig
from nodes.core.poll_trigger import poll_scope


BILL = {
    "id": "ocd-bill/f0049138-1ad8-4506-a2a4-f4dd1251bbba",
    "session": "2020", "identifier": "SB 113", "title": "Adopting a State Scorpion",
    "created_at": "2020-01-01T00:00:00Z", "updated_at": "2020-02-01T00:00:00Z",
    "openstates_url": "https://openstates.org/nc/bills/2019/HB1105/",
    "jurisdiction": {"id": "ocd-jurisdiction/country:us/state:nc/government", "name": "North Carolina", "classification": "state"},
    "from_organization": {"id": "ocd-organization/123", "name": "Senate", "classification": "upper"},
}


def page(rows, number=1, maximum=1):
    return {"results": rows, "pagination": {"page": number, "max_page": maximum, "per_page": 20, "total_items": len(rows)}}


def node(operation, **values):
    return OpenStatesNode(node_id="openstates-test", node_type="automation-openstates", node_data={},
        config=OpenStatesNodeConfig.model_validate({"config": {"operation": operation, **values},
            "credentials": {"credential_type": "openstates_api_key", "api_key": "test-key"}}),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,values,path,query", [
    ("search_bills", {"jurisdiction": "nc", "identifier": '["SB 113", "HB 1"]', "include": ["actions", "votes"]}, "/bills", {"jurisdiction": ["nc"], "identifier": ["SB 113", "HB 1"], "include": ["actions", "votes"]}),
    ("get_bill_by_id", {"openstates_bill_id": BILL["id"], "include": ["versions"]}, "/bills/ocd-bill/f0049138-1ad8-4506-a2a4-f4dd1251bbba", {"include": ["versions"]}),
    ("get_bill", {"jurisdiction": "nc", "session": "2020", "bill_id": "SB 113"}, "/bills/nc/2020/SB%20113", {}),
    ("search_people", {"id": ["ocd-person/a", "ocd-person/b"], "district": "1"}, "/people", {"id": ["ocd-person/a", "ocd-person/b"], "district": ["1"]}),
    ("find_legislators", {"lat": 35.78, "lng": -78.64}, "/people.geo", {"lat": ["35.78"], "lng": ["-78.64"]}),
    ("list_jurisdictions", {"classification": "state", "page": 2}, "/jurisdictions", {"classification": ["state"], "page": ["2"]}),
    ("get_jurisdiction", {"jurisdiction_id": "ocd-jurisdiction/country:us/state:nc/government"}, "/jurisdictions/ocd-jurisdiction%2Fcountry%3Aus%2Fstate%3Anc%2Fgovernment", {}),
    ("list_committees", {"chamber": "upper", "classification": "committee"}, "/committees", {"chamber": ["upper"], "classification": ["committee"]}),
    ("get_committee", {"committee_id": "ocd-organization/abc"}, "/committees/ocd-organization%2Fabc", {}),
    ("list_events", {"after": "2020-01-01", "require_bills": True}, "/events", {"after": ["2020-01-01"], "require_bills": ["true"]}),
    ("get_event", {"event_id": "ocd-event/abc", "include": ["agenda"]}, "/events/ocd-event%2Fabc", {"include": ["agenda"]}),
])
async def test_routes_and_key_placement(operation, values, path, query):
    n = node(operation, **values)
    is_list = operation in {"search_bills", "search_people", "find_legislators", "list_jurisdictions", "list_committees", "list_events"}
    body = page([BILL], 2, 3) if is_list else BILL
    with respx.mock as router:
        route = router.get("https://v3.openstates.org" + path).mock(return_value=httpx.Response(200, json=body))
        output = await n.execute({})
        request = route.calls.last.request
        assert request.headers["X-API-KEY"] == "test-key"
        assert "apikey" not in request.url.params
        for name, expected in query.items():
            assert request.url.params.get_list(name) == expected
        assert request.content == b""
    if is_list:
        assert output["next_page"] == 3
        assert output["results"] == [BILL]
    else:
        assert output == BILL


@pytest.mark.asyncio
async def test_poll_baselines_then_emits_new_bill_revision_and_deduplicates():
    n = node("on_bill_updated", jurisdiction="nc", session="2020", updated_since="2020-01-01")
    state = {}

    async def update(mutator, **kwargs):
        nonlocal state
        replacement, result = mutator(deepcopy(state))
        if replacement is not None:
            state = replacement
        return result

    n._update_node_state = update
    with respx.mock as router:
        route = router.get("https://v3.openstates.org/bills").mock(return_value=httpx.Response(200, json=page([BILL])))
        assert (await n.execute({}))["bills"] == []
        assert n.trigger_produced_no_event({})
        revised = {**BILL, "updated_at": "2020-03-01T00:00:00Z"}
        route.mock(return_value=httpx.Response(200, json=page([revised])))
        output = await n.execute({})
        assert output["bills"] == [revised]
        assert n.trigger_emitted_event(output)
        event = n.resolve_agent_event(output)
        assert "Adopting a State Scorpion" in event["text"]
        assert BILL["id"] in event["text"] and BILL["openstates_url"] in event["text"]
        assert (await n.execute({}))["bill_count"] == 0
        params = route.calls.last.request.url.params
        assert dict(params) == {"jurisdiction": "nc", "session": "2020", "updated_since": "2020-01-01", "sort": "updated_desc", "per_page": "20", "page": "1"}


@pytest.mark.asyncio
async def test_poll_fetches_all_pages_before_recording_seen(monkeypatch):
    n = node("on_bill_updated", jurisdiction="nc")
    seen = []

    async def unseen(items, identify):
        seen.extend(identify(item) for item in items)
        return items

    monkeypatch.setattr(n, "_filter_unseen", unseen)
    with respx.mock as router:
        route = router.get("https://v3.openstates.org/bills").mock(side_effect=[
            httpx.Response(200, json=page([BILL], 1, 2)),
            httpx.Response(200, json=page([{**BILL, "id": "ocd-bill/second"}], 2, 2)),
        ])
        assert (await n.execute({}))["bill_count"] == 2
        assert [call.request.url.params["page"] for call in route.calls] == ["1", "2"]
    assert len(seen) == 2


@pytest.mark.asyncio
async def test_incomplete_poll_does_not_consume_items(monkeypatch):
    n = node("on_bill_updated", jurisdiction="nc")
    from unittest.mock import AsyncMock
    unseen = AsyncMock()
    monkeypatch.setattr(n, "_filter_unseen", unseen)
    with respx.mock as router:
        router.get("https://v3.openstates.org/bills").mock(side_effect=[
            httpx.Response(200, json=page([BILL], 1, 2)), httpx.Response(429, json={"detail": "Rate limit exceeded"})])
        with pytest.raises(ValueError, match="429: Rate limit exceeded"):
            await n.execute({})
    unseen.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,detail", [(401, "Invalid API Key."), (403, "Must provide API Key"), (429, "Rate limit exceeded")])
async def test_provider_errors_surface_without_secret(status, detail):
    with respx.mock:
        respx.get("https://v3.openstates.org/jurisdictions").mock(return_value=httpx.Response(status, json={"detail": detail}))
        with pytest.raises(ValueError, match=detail) as error:
            await node("list_jurisdictions").execute({})
        assert "test-key" not in str(error.value)


def test_manual_credential_default_and_reachability_evidence():
    credential = OpenStatesAPIKeyCredential(api_key=" pasted-key ")
    assert credential.credential_type == "openstates_api_key" and credential.api_key == "pasted-key"
    assert OpenStatesNode.connection_evidence.proves == "reachability"
    assert OpenStatesNode.connection_evidence.operation == "list_jurisdictions"
    with pytest.raises(ValidationError):
        OpenStatesAPIKeyCredential(api_key="bad\nkey")


def test_trigger_scope_uses_declared_filters_only():
    a = {"operation": "on_bill_updated", "jurisdiction": "nc", "session": "2020"}
    assert poll_scope(OpenStatesNode, a) == poll_scope(OpenStatesNode, {**a, "label": "Renamed", "goal": "Monitor"})
    assert poll_scope(OpenStatesNode, a) != poll_scope(OpenStatesNode, {**a, "jurisdiction": "oh"})


@pytest.mark.parametrize("operation,limit", [("search_bills", 20), ("search_people", 50), ("list_jurisdictions", 52), ("list_committees", 20), ("list_events", 20)])
def test_provider_page_size_limits(operation, limit):
    node(operation, per_page=limit)
    with pytest.raises(ValidationError):
        node(operation, per_page=limit + 1)
