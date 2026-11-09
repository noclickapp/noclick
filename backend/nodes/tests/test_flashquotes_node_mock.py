"""Exercise every pinned Flashquotes route through the real node factory.

Responses use published examples where available and synthetic legacy fixtures
otherwise. No account, database, or provider network is used.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import flashquotes_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / 'fixtures' / 'flashquotes'
RESPONSES = json.loads((FIXTURES / 'responses.json').read_text())
CONTRACT = json.loads((FIXTURES / 'openapi.json').read_text())
TOKEN = 'synthetic-flashquotes-key-42'
AUTH = {'credential_type': native.CREDENTIAL_TYPE, 'api_key': TOKEN}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=AUTH):
    return NodeFactory.create_node(node_id='flashquotes-fixture', node_type='automation-flashquotes',
        node_data={'config': config, 'credentials': credentials})


def transport(monkeypatch, body, status=200):
    requests = []
    def send(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(send), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


CASES = [
    ('list_events', {}, '/events'),
    ('get_event', {'event_id': 'evt_8K3aN1qV2x'}, '/events/evt_8K3aN1qV2x'),
    ('list_resources', {}, '/resources'),
    ('get_resource', {'resource_id': 'res_5M2wQ8'}, '/resources/res_5M2wQ8'),
    ('get_event_legacy', {'event_id': 'cm123abc456'}, '/event/getEventData/cm123abc456'),
    ('list_events_legacy', {'event_starts_after': '2024-01-01T00:00:00-05:00', 'event_starts_before': '2024-01-08T00:00:00-05:00'}, '/event/get-events'),
    ('get_form_response', {'form_response_id': 'form_123'}, '/form_response/form_123'),
    ('get_staff', {'staff_id': 'stf_5J9pK2mR7t'}, '/staff/stf_5J9pK2mR7t'),
    ('list_invoices', {'booking_id': 'book_123'}, '/invoice/book_123'),
    ('get_quote', {'quote_id': 'cmf2q8n4x0000kz01a1b2c3d4'}, '/quotes/cmf2q8n4x0000kz01a1b2c3d4'),
    ('list_quotes', {}, '/quotes'),
]


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,arguments,path', CASES)
async def test_every_contract_operation(monkeypatch, operation, arguments, path):
    requests = transport(monkeypatch, RESPONSES[operation])
    result = await node({'operation': operation, **arguments}).execute({})
    assert result['status'] == 'success' and result['data'] == RESPONSES[operation]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == 'GET' and request.url.path == '/api' + path
    assert request.url.host == 'app.flashquotes.com'
    assert request.headers['x-api-key'] == TOKEN and request.headers['Accept'] == 'application/json'
    assert not request.content and TOKEN not in str(request.url) and TOKEN not in str(result)
    assert set(native.ROUTES) == set(RESPONSES)
    assert len(native.ROUTES) == sum('get' in item for item in CONTRACT['paths'].values())


@pytest.mark.asyncio
async def test_exact_bracket_filters_repeated_expansion_and_paging(monkeypatch):
    requests = transport(monkeypatch, RESPONSES['list_events'])
    result = await node({'operation': 'list_events', 'limit': 25, 'starting_after': 'evt_previous',
        'service_start_time_gte': '2026-06-01T00:00:00Z', 'created_at_lt': '2026-06-01T00:00:00Z',
        'location_id': 'loc_7H2pQ9', 'booking_id': 'bkg_4F2yL8',
        'expand': ['data.booking.lead', 'data.location']}).execute({})
    assert requests[0].url.params.multi_items() == [
        ('limit', '25'), ('starting_after', 'evt_previous'),
        ('service_start_time[gte]', '2026-06-01T00:00:00Z'), ('created_at[lt]', '2026-06-01T00:00:00Z'),
        ('location_id', 'loc_7H2pQ9'), ('booking_id', 'bkg_4F2yL8'),
        ('expand[]', 'data.booking.lead'), ('expand[]', 'data.location')]
    assert result['has_more'] is True and result['next_cursor'] == 'evt_8K3aN1qV2x'


@pytest.mark.asyncio
async def test_empty_last_page(monkeypatch):
    transport(monkeypatch, {'object': 'list', 'url': '/api/resources', 'hasMore': False, 'data': []})
    result = await node({'operation': 'list_resources'}).execute({})
    assert result['has_more'] is False and result['next_cursor'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body,message', [
    (401, {'error': {'message': 'Unauthorized, invalid or missing API key'}}, 'Unauthorized, invalid or missing API key'),
    (403, {'message': 'Plan does not allow public API'}, 'Plan does not allow public API'),
    (429, {'error': {'message': 'Rate limit exceeded'}}, 'Rate limit exceeded'),
    (200, {'error': {'message': 'Provider error'}}, 'Provider error'),
    (302, {'message': 'Redirect refused'}, 'Redirect refused'),
])
async def test_provider_errors_not_success(monkeypatch, status, body, message):
    requests = transport(monkeypatch, body, status)
    with pytest.raises(ValueError, match=message):
        await node({'operation': 'list_resources'}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_redacts_key_in_provider_errors_and_data(monkeypatch):
    transport(monkeypatch, {'error': {'message': 'Refused ' + TOKEN}}, 401)
    with pytest.raises(ValueError) as exc:
        await node({'operation': 'list_resources'}).execute({})
    assert TOKEN not in str(exc.value) and '[redacted]' in str(exc.value)
    transport(monkeypatch, {'id': 'evt_1', 'nested': [TOKEN]})
    assert TOKEN not in str(await node({'operation': 'get_event', 'event_id': 'evt_1'}).execute({}))


@pytest.mark.asyncio
async def test_invoices_preserve_both_pinned_and_documented_shapes(monkeypatch):
    for payload in (RESPONSES['list_invoices'], [{'id': 'inv_456', 'url': 'https://app.flashquotes.com/invoices/encrypted/abc123'}]):
        transport(monkeypatch, payload)
        assert (await node({'operation': 'list_invoices', 'booking_id': 'book_123'}).execute({}))['data'] == payload


@pytest.mark.parametrize('config', [
    {'operation': 'get_event', 'event_id': '../staff/foreign'},
    {'operation': 'get_event', 'event_id': 'https://evil.test/'},
    {'operation': 'list_events', 'limit': 101},
    {'operation': 'list_events', 'created_at_gt': '2026-06-01'},
    {'operation': 'list_events', 'expand': ['booking.lead']},
    {'operation': 'get_event', 'event_id': 'evt_1', 'expand': ['data.location']},
    {'operation': 'get_staff', 'staff_id': 'stf_1', 'expand': ['location']},
    {'operation': 'list_resources', 'expand': ['data.location']},
    {'operation': 'list_events_legacy', 'event_starts_after': '2024-01-01T00:00:00Z', 'event_starts_before': '2024-01-09T00:00:00Z'},
    {'operation': 'list_events_legacy', 'event_starts_after': '2024-01-01T00:00:00Z', 'event_starts_before': '2024-01-01T00:00:00Z'},
])
def test_invalid_input_refused_before_network(config):
    with pytest.raises(ValidationError):
        native.FlashquotesConfig.model_validate({'config': config, 'credentials': AUTH})


def test_manual_credential_defaults_and_shape():
    from nodes.core.credential_connect import shape_credential
    shaped, errors, _ = shape_credential(native.CREDENTIAL_TYPE, {'api_key': '  ' + TOKEN + '  '})
    assert errors == {} and shaped['api_key'] == TOKEN
    assert native.FlashquotesApiKeyCredential.model_validate(shaped).credential_type == native.CREDENTIAL_TYPE
    assert native.FlashquotesApiKeyCredential.model_fields['credential_type'].default == native.CREDENTIAL_TYPE


@pytest.mark.asyncio
async def test_account_specific_connection_evidence(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    requests = transport(monkeypatch, RESPONSES['list_resources'])
    evidence = await collect_evidence(node_type="automation-flashquotes", credential_data=AUTH, user_id='00000000-0000-4000-8000-000000000001')
    assert evidence.reachable is True
    assert 'Espresso Cart' in str(evidence.samples)
    assert len(requests) == 1 and requests[0].url.path == '/api/resources'
