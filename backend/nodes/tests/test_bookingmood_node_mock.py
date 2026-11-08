"""Exercise Bookingmood's request boundary without an account.

These tests cover exact-ID deletes, paging, booking payloads and provider failures.
"""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import bookingmood_node as native
from nodes.core.registry import NodeFactory

ID = '11111111-1111-4111-8111-111111111111'
TOKEN = 'bookingmood-test-token'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='fixture', node_type='automation-bookingmood',
        node_data={'config': config, 'credentials': {'credential_type': 'bookingmood_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, status=200, body=None):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', [k for k in native.ROUTES if k.startswith('list_')])
async def test_list_paging(monkeypatch, operation):
    requests = transport(monkeypatch, body=[{'id': ID, 'name': 'Guest house'}])
    result = await node({'operation': operation, 'limit': 1, 'offset': 4}).execute({})
    assert result['next_offset'] == 5 and result['data'][0]['id'] == ID
    assert dict(requests[0].url.params) == {'limit': '1', 'offset': '4'}
    assert requests[0].headers['authorization'] == 'Bearer ' + TOKEN


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', [k for k in native.ROUTES if k.startswith(('delete_', 'get_'))])
async def test_exact_id(monkeypatch, operation):
    deleting = operation.startswith('delete_')
    requests = transport(monkeypatch, status=204 if deleting else 200, body=None if deleting else [{'id': ID}])
    result = await node({'operation': operation, 'id': ID}).execute({})
    assert result['status'] == 'success'
    assert requests[0].url.params['id'] == 'eq.' + ID
    assert requests[0].method == ('DELETE' if deleting else 'GET')


@pytest.mark.asyncio
async def test_booking_payload_and_pending_payment(monkeypatch):
    fixture = json.loads((Path(__file__).parent / 'fixtures/bookingmood/booking_confirmation.json').read_text())
    requests = transport(monkeypatch, status=201, body=fixture)
    result = await node({'operation': 'create_booking', 'product_id': ID,
        'interval': {'start': '2027-01-01', 'end': '2027-01-03'}, 'occupancy': {ID: 2}}).execute({})
    body = json.loads(requests[0].content)
    assert body['occupancy'] == {ID: 2} and body['currency'] is None
    assert body['form_values'] == {} and body['show_pending_as'] == 'TENTATIVE'
    assert requests[0].url.path == '/v1/book'
    assert result['data']['payment_url'].endswith('/pay')


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,fields', [
    ('create_contact', {'organization_id': ID, 'email': 'guest@example.test'}),
    ('create_task', {'calendar_event_id': ID, 'label': 'Clean', 'due_at': '2027-01-03T12:00:00Z'}),
    ('create_calendar_event_note', {'calendar_event_id': ID, 'note': 'Late arrival'})])
async def test_minimal_creates(monkeypatch, operation, fields):
    requests = transport(monkeypatch, status=201)
    result = await node({'operation': operation, **fields}).execute({})
    assert result['acknowledged'] is True
    assert requests[0].headers['prefer'] == 'return=minimal'
    body = json.loads(requests[0].content)
    assert 'operation' not in body and body['id']


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302, 401, 403, 429, 500])
async def test_rejection_redaction(monkeypatch, status):
    requests = transport(monkeypatch, status=status, body={'message': TOKEN})
    result = await node({'operation': 'list_organizations'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
async def test_wrong_id_and_unexpected_shape(monkeypatch):
    transport(monkeypatch, body=[{'id': 'other'}])
    with pytest.raises(ValueError, match='different resource'):
        await node({'operation': 'get_contact', 'id': ID}).execute({})
    transport(monkeypatch, body={'error': 'bad'})
    with pytest.raises(ValueError, match='rows'):
        await node({'operation': 'list_contacts'}).execute({})


@pytest.mark.parametrize('config', [
    {'operation': 'delete_booking', 'id': 'eq.1'},
    {'operation': 'list_contacts', 'limit': 0},
    {'operation': 'delete_task'},
    {'operation': 'create_booking', 'product_id': ID, 'occupancy': {}, 'interval': {'start': '2027-01-03', 'end': '2027-01-01'}}])
def test_refuse_invalid_inputs(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)
