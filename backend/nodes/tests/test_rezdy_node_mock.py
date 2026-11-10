"""Validate Rezdy actions and scheduled booking triggers with mock HTTP transport.

Booking fixtures are copied from the publisher's examples at
https://developers.rezdy.com/rezdyapi/swagger-supplier.json.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes import rezdy_node as db
from nodes.core.registry import NodeFactory
from utils import ssrf

AUTH = {"credential_type": "rezdy_api_key", "api_key": "fixture-rezdy-private-key"}
BOOKING = {"items": [{"productCode": "PWQF1Y", "startTimeLocal": "2025-10-01 09:00:00", "quantities": [{"optionLabel": "Adult", "value": 1}]}], "customer": {"firstName": "Rick", "lastName": "Sanchez"}}
EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/rezdy/published_responses.json').read_text())

@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "api.rezdy.com"
        assert request.headers["apiKey"] == AUTH['api_key']
        assert AUTH['api_key'] not in str(request.url)
        code, payload = replies.pop(0)
        return httpx.Response(code, json=payload)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(db, "guarded_async_client", lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies

async def run(config):
    node = NodeFactory.create_node(node_id="rezdy-test", node_type="automation-rezdy", node_data={"config": config, "credentials": AUTH})
    return await node.execute({})

CASES = {
    "get_product": {"productCode": "PWQF1Y"}, "get_booking": {"orderNumber": "RKM1ULT"},
    "create_booking": {"booking": BOOKING}, "quote_booking": {"booking": BOOKING},
    "update_booking": {"orderNumber": "RKM1ULT", "booking": BOOKING}, "cancel_booking": {"orderNumber": "RKM1ULT"},
    "get_customer": {"customerId": 29650}, "create_customer": {"customer": {"firstName": "Rick"}},
    "delete_customer": {"customerId": 29650},
    "search_availability": {"productCode": ["PWQF1Y", "P12345"], "startTimeLocal": "2025-10-01 00:00:00", "endTimeLocal": "2025-10-02 00:00:00"},
    "get_category": {"categoryId": 123}, "list_category_products": {"categoryId": 123},
    "get_voucher": {"voucherCode": "GIFT123"}, "list_product_pickups": {"productCode": "PWQF1Y"},
}

@pytest.mark.asyncio
@pytest.mark.parametrize("operation", db.ROUTES)
async def test_rezdy_each_operation_makes_one_contract_request(transport, operation):
    requests, replies = transport
    method, path, result_key = db.ROUTES[operation]
    config = {"operation": operation, **CASES.get(operation, {})}
    list_result = operation.startswith("list_") or operation == "search_availability"
    payload = {"requestStatus": {"success": True, "version": "v1"}}
    if result_key:
        payload[result_key] = [{"name": "My account category", "id": 123}] if list_result else {"id": 123}
    payload = EXAMPLES.get(method.lower() + ' ' + path, payload)
    replies.append((200, payload))
    result = await run(config)
    assert result['status'] == 'success'
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method
    for field, value in config.items():
        path = path.replace('{' + field + '}', str(value))
    assert req.url.path == path
    if method in {'POST', 'PUT'}:
        expected = config.get('booking', config.get('customer'))
        body = json.loads(req.content)
        assert all(body[k] == v for k, v in expected.items())
        if operation == 'create_booking':
            assert body['sendNotifications'] is False
    if operation == 'search_availability':
        assert req.url.params.get_list('productCode') == ['PWQF1Y', 'P12345']
    if operation == 'cancel_booking':
        assert req.url.params['sendNotifications'] == 'false'

@pytest.mark.asyncio
@pytest.mark.parametrize('code,payload', [(200, {'requestStatus': {'success': False, 'error': {'errorCode': '6', 'errorMessage': 'Invalid API Key'}}}), (200, {'requestStatus': {'success': True}}), (502, {'message': 'upstream error'})])
async def test_rezdy_rejects_error_and_incomplete_responses(transport, code, payload):
    requests, replies = transport
    replies.append((code, payload))
    result = await run({'operation': 'list_categories'})
    assert result['status'] == 'error'
    assert len(requests) == 1
    if payload.get('requestStatus', {}).get('success') is False:
        assert result['error'] == 'Invalid API Key'

@pytest.mark.asyncio
async def test_rezdy_offset_and_secret_redaction(transport):
    requests, replies = transport
    replies.append((200, {'requestStatus': {'success': True}, 'categories': [{'name': AUTH['api_key'], 'apiKey': AUTH['api_key']}]}))
    result = await run({'operation': 'list_categories', 'limit': 1, 'offset': 7})
    assert result['next_offset'] == 8
    assert result['has_more'] is True
    assert AUTH['api_key'] not in json.dumps(result)
    assert 'apiKey' not in result['items'][0]
    assert requests[0].url.params['offset'] == '7'

def test_rezdy_manual_credential_defaults_and_fields():
    credential = db.RezdyAPIKeyCredential.model_validate({'api_key': AUTH['api_key']})
    assert credential.credential_type == 'rezdy_api_key'
    assert db.RezdyNode.connection_evidence.operation == 'list_categories'


@pytest.mark.parametrize("code", [".", "..", "\r\n", " "])
def test_rezdy_refuses_unsafe_path_identifiers(code):
    with pytest.raises(ValueError):
        db.GetProduct(productCode=code)

@pytest.mark.parametrize('value', ['2025-02-30 09:00:00', '2025-1-01 09:00:00', '1'])
def test_rezdy_local_time_validation(value):
    with pytest.raises(ValueError):
        db.BookingItem(productCode='PWQF1Y', quantities=[{'value': 1}], startTimeLocal=value)

@pytest.mark.asyncio
async def test_rezdy_iso_times_are_json_and_query_strings(transport):
    requests, replies = transport
    replies.append((200, {'requestStatus': {'success': True}, 'booking': {'orderNumber': 'R123456'}}))
    config = {'operation': 'create_booking', 'booking': {'items': [{'productCode': 'PWQF1Y', 'quantities': [{'value': 1}], 'startTime': '2025-10-01T09:00:00Z'}]}}
    assert (await run(config))['status'] == 'success'
    assert json.loads(requests[0].content)['items'][0]['startTime'] == '2025-10-01T09:00:00Z'
    replies.append((200, {'requestStatus': {'success': True}, 'bookings': []}))
    assert (await run({'operation': 'list_bookings', 'updatedSince': '2025-10-01T09:00:00Z'}))['status'] == 'success'
    assert requests[1].url.params['updatedSince'] == '2025-10-01T09:00:00Z'


def poll_node(operation, **config):
    node = NodeFactory.create_node(node_id="rezdy-poll", node_type="automation-rezdy",
        node_data={"config": {"operation": operation, **config}, "credentials": AUTH})
    state = {}
    async def update(mutator, **kwargs):
        new, result = mutator(dict(state))
        if new is not None:
            state.clear()
            state.update(new)
        return result
    node._update_node_state = update
    return node, state


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["on_new_booking", "on_new_or_updated_booking"])
async def test_rezdy_poll_baselines_and_emits_documented_booking(transport, operation):
    from copy import deepcopy
    requests, replies = transport
    node, state = poll_node(operation, minDateCreated="2014-03-01T00:00:00Z", productCode=["P12345"])
    empty = {"requestStatus": {"success": True}, "bookings": []}
    replies.append((200, empty))
    baseline = await node.execute({})
    assert baseline["bookings"] == []
    assert node.trigger_produced_no_event(baseline)
    replies.append((200, deepcopy(EXAMPLES["get /v1/bookings"])))
    fresh = await node.execute({})
    booking = EXAMPLES["get /v1/bookings"]["bookings"][0]
    assert fresh["bookings"] == [booking]
    assert node.trigger_emitted_event(fresh)
    assert node.should_propagate_output(fresh, {"operation": operation})
    event = node.resolve_agent_event(fresh)
    assert booking["orderNumber"] in event["text"]
    assert booking["customer"]["name"] in event["text"]
    assert booking["items"][0]["productCode"] in event["text"]
    assert booking["items"][0]["startTimeLocal"] in event["text"]
    assert booking["status"] in event["text"]
    assert booking["supplierName"] in event["text"]
    replies.append((200, deepcopy(EXAMPLES["get /v1/bookings"])))
    again = await node.execute({})
    assert again["bookings"] == []
    assert node.resolve_agent_event(again) is None
    assert node.should_propagate_output(again, {"operation": operation}) is False
    assert all(r.url.params["minDateCreated"] == "2014-03-01T00:00:00Z" for r in requests)
    assert all(r.url.params.get_list("productCode") == ["P12345"] for r in requests)
    assert all("schedule" not in r.url.params for r in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,expected", [("on_new_booking", 0), ("on_new_or_updated_booking", 1)])
async def test_rezdy_poll_updated_timestamp_and_scope(transport, operation, expected):
    from copy import deepcopy
    from nodes.core.poll_trigger import poll_scope
    requests, replies = transport
    node, state = poll_node(operation)
    payload = deepcopy(EXAMPLES["get /v1/bookings"])
    replies.append((200, payload))
    assert (await node.execute({}))["booking_count"] == 0
    # A later edit changes the documented dateUpdated field, keeping the order id.
    payload = deepcopy(payload)
    payload["bookings"][0]["dateUpdated"] = "2025-09-04T00:00:04Z"
    replies.append((200, payload))
    assert (await node.execute({}))["booking_count"] == expected
    assert poll_scope(db.RezdyNode, {"operation": operation}) == poll_scope(db.RezdyNode, {"operation": operation, "label": "Cosmetic"})
    assert poll_scope(db.RezdyNode, {"operation": operation}) != poll_scope(db.RezdyNode, {"operation": operation, "productCode": ["PWQF1Y"]})
    node._config = db.RezdyNode.parse_config({"config": {"operation": operation, "productCode": ["PWQF1Y"]}, "credentials": AUTH})
    replies.append((200, payload))
    assert (await node.execute({}))["booking_count"] == 0  # Repoint re-baselines.


@pytest.mark.asyncio
async def test_rezdy_poll_pages_before_advancing_state_and_retries_failures(transport):
    from copy import deepcopy
    requests, replies = transport
    node, state = poll_node("on_new_or_updated_booking")
    page = deepcopy(EXAMPLES["get /v1/bookings"])
    # A full first page must be followed before the baseline is committed.
    page["bookings"] *= 100
    replies.extend([(200, page), (503, {"requestStatus": {"success": False}})])
    assert (await node.execute({}))["status"] == "error"
    assert state == {}
    assert requests[1].url.params["offset"] == "100"
    replies.extend([(200, page), (200, {"requestStatus": {"success": True}, "bookings": []})])
    assert (await node.execute({}))["booking_count"] == 0
    assert state["seen_ids"]
    assert requests[2].url.params["offset"] == "0"


@pytest.mark.asyncio
async def test_rezdy_poll_refuses_overflow_without_advancing_state(transport):
    from copy import deepcopy
    requests, replies = transport
    node, state = poll_node("on_new_booking")
    page = deepcopy(EXAMPLES["get /v1/bookings"])
    page["bookings"] *= 100
    replies.extend((200, page) for _ in range(101))
    with pytest.raises(ValueError, match="10,000"):
        await node.execute({})
    assert state == {}


def test_rezdy_trigger_schema_and_declared_scope_validation():
    from nodes.core.poll_trigger import PollTriggerConfigBase
    for model in (db.OnNewBooking, db.OnNewOrUpdatedBooking):
        assert issubclass(model, PollTriggerConfigBase)
        assert model.model_json_schema()["properties"]["operation"]["x-is-trigger"] is True
        with pytest.raises(ValueError):
            model(productCode=[".."])
        with pytest.raises(ValueError):
            model(minDateCreated="2025-09-04")


def test_rezdy_optional_product_filter_accepts_none():
    assert db.ListBookings(productCode=None).productCode is None
    assert db.OnNewBooking(productCode=None).productCode is None


@pytest.mark.asyncio
async def test_rezdy_poll_deduplicates_overlapping_pages(transport):
    from copy import deepcopy
    requests, replies = transport
    node, state = poll_node("on_new_booking")
    replies.append((200, {"requestStatus": {"success": True}, "bookings": []}))
    await node.execute({})
    page = deepcopy(EXAMPLES["get /v1/bookings"])
    page["bookings"] *= 100
    replies.extend([(200, page), (200, deepcopy(EXAMPLES["get /v1/bookings"]))])
    assert (await node.execute({}))["booking_count"] == 1
