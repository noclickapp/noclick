"""Validate Rezdy's operations using the native factory and a mock HTTP transport."""
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
