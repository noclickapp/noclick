"""Sympla request and response regressions; no live credentials or network calls."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import sympla_node as native
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / 'fixtures/sympla'
CONFIGS = json.loads((FIXTURES / 'operations.json').read_text())
CREDENTIAL = {'credential_type': 'sympla_api_token', 'api_token': 'synthetic-token'}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='sympla-test', node_type='automation-sympla',
        node_data={'config': config, 'credentials': CREDENTIAL})


def transport(monkeypatch, body, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,method,suffix', [
    ('list_events', 'GET', ''),
    ('get_event', 'GET', '/abc123def456'),
    ('list_orders', 'GET', '/abc123def456/orders'),
    ('get_order', 'GET', '/abc123def456/orders/abc123def456'),
    ('list_order_participants', 'GET', '/abc123def456/orders/12345/participants'),
    ('list_participants', 'GET', '/abc123def456/participants'),
    ('get_participant_by_ticket', 'GET', '/abc123def456/participants/ticketNumber/94461180000001'),
    ('check_in_by_ticket', 'POST', '/abc123def456/participants/ticketNumber/abc123def456/check-in'),
    ('get_participant', 'GET', '/abc123def456/participants/12345'),
    ('check_in_participant', 'POST', '/abc123def456/participants/12345/check-in'),
    ('list_presentations', 'GET', '/abc123def456/presentations'),
    ('get_presentation', 'GET', '/abc123def456/presentations/12345'),
    ('list_presentation_orders', 'GET', '/abc123def456/presentations/12345/orders'),
    ('list_presentation_participants', 'GET', '/abc123def456/presentations/12345/participants'),
    ('check_in_qr_code', 'POST', '/abc123def456/qrcode/check-in'),
])
async def test_factory_routes_auth_and_response_shapes(monkeypatch, operation, method, suffix):
    body = {'id': '123', 'name': 'An event'} if operation in {'get_event', 'get_presentation'} else {'data': [] if operation.startswith('list_') else {'id': '123'}}
    requests = transport(monkeypatch, body)
    result = await node(CONFIGS[operation]).execute({})
    assert result['status'] == 'success'
    assert result['data'] == (body if operation in {'get_event', 'get_presentation'} else body['data'])
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url).startswith('https://api.sympla.com.br/public/v1.6.0/events')
    assert request.url.path == '/public/v1.6.0/events' + suffix
    assert request.headers['s_token'] == CREDENTIAL['api_token']
    if operation == 'check_in_qr_code':
        assert json.loads(request.content) == CONFIGS[operation]['qr_code']
    else:
        assert request.content == b''


@pytest.mark.asyncio
async def test_required_queries_and_cursor_preserved(monkeypatch):
    body = {'data': [{'id': '123', 'name': 'Conference'}], 'pagination': {'next_cursor': 'opaque+/=', 'quantity': 1, 'page_size': 100}, 'sort': {'field_sort': 'start_date', 'sort': 'asc'}}
    requests = transport(monkeypatch, body)
    result = await node({'operation': 'list_events', 'published': 'all', 'cursor': 'opaque+/=', 'from_date': '2025-09-08T00:00:00-03:00'}).execute({})
    assert result['pagination'] == body['pagination']
    assert dict(requests[0].url.params) == {'published': 'all', 'timezone': 'America/Sao_Paulo', 'sort': 'asc', 'cursor': 'opaque+/=', 'from': '2025-09-08T00:00:00-03:00'}
    requests = transport(monkeypatch, {'data': []})
    await node(CONFIGS['list_order_participants']).execute({})
    assert requests[0].url.params.get_list('fields') == ['ticket_number', 'first_name', 'email']
    assert requests[0].url.params['timezone'] == 'America/Sao_Paulo'
    requests = transport(monkeypatch, {'data': []})
    await node(CONFIGS['list_presentations']).execute({})
    assert requests[0].url.params['published'] == 'true'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_errors_and_redirects_propagate(monkeypatch, status):
    requests = transport(monkeypatch, {'message': 'Provider rejected request'}, status)
    with pytest.raises(httpx.HTTPStatusError):
        await node({'operation': 'list_events'}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_no_content_and_invalid_envelopes(monkeypatch):
    transport(monkeypatch, None, 204)
    assert (await node(CONFIGS['check_in_participant']).execute({}))['http_status'] == 204
    for body in [{}, {'data': {}}, {'error': 'rejected', 'data': []}]:
        transport(monkeypatch, body)
        with pytest.raises(ValueError):
            await node({'operation': 'list_events'}).execute({})


def test_invalid_input_rejected_before_request():
    for config in [
        {'operation': 'get_event', 'event_id': '../other'},
        {'operation': 'get_event'},
        {'operation': 'list_events', 'from_date': 'not-a-date'},
        {'operation': 'list_events', 'page_size': 201},
        {'operation': 'check_in_qr_code', 'event_id': 'abc', 'qr_code': {}},
    ]:
        with pytest.raises(ValueError):
            node(config)
    with pytest.raises(ValidationError):
        native.SymplaTokenCredential(api_token='\r\n')
