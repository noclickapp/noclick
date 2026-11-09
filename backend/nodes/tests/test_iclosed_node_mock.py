"""Exercise iClosed's real factory and HTTP boundary with published examples.

These tests use a fake key and mock transport; they never access an iClosed account.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import iclosed_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/iclosed/contract_examples.json').read_text())
TOKEN = 'iclosed_synthetic_test_key'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='iclosed-fixture', node_type='automation-iclosed',
        node_data={'config': config, 'credentials': {'credential_type': native.CREDENTIAL_TYPE, 'api_key': TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


def config_for(operation):
    if operation in EXAMPLES['requests']:
        return EXAMPLES['requests'][operation]['config']
    return {'operation': operation, **{
        'get_contact': {'contactId': 2},
        'get_event': {'id': 1},
        'list_contact_notes': {'contactId': 2},
        'delete_transaction': {'id': 1},
    }.get(operation, {})}


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(native.ROUTES))
async def test_every_operation_one_request_published_route_and_body(monkeypatch, operation):
    example = EXAMPLES['responses'][operation]
    requests = transport(monkeypatch, example['body'], example['status'])
    output = await node(config_for(operation)).execute({})
    method, path = native.ROUTES[operation]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert str(request.url).startswith(native.BASE_URL + '/')
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    assert output['success'] and output['http_status'] == example['status']
    assert TOKEN not in str(output)
    if method in {'POST', 'PUT'}:
        expected = {k: v for k, v in config_for(operation).items() if k != 'operation'}
        assert json.loads(request.content) == expected
    else:
        assert not request.content
    if operation.startswith('list_'):
        assert isinstance(output['data'], list)
        assert output['page'] == 0 and output['limit'] > 0


@pytest.mark.asyncio
async def test_pages_and_filters_do_not_drop_false_or_zero(monkeypatch):
    requests = transport(monkeypatch, {'data': {'contacts': [{'id': 9, 'email': 'owned@example.test'}], 'count': 41}})
    output = await node({'operation': 'list_contacts', 'limit': 20, 'page': 1,
                         'search': 'Jane + Doe', 'orderBy': 'desc', 'orderColumn': 'createdAt'}).execute({})
    assert dict(requests[0].url.params) == {'limit': '20', 'page': '1', 'search': 'Jane + Doe',
                                         'orderBy': 'desc', 'orderColumn': 'createdAt'}
    assert output['has_more'] and output['next_page'] == 2
    requests = transport(monkeypatch, {'data': {'id': 2}})
    await node({'operation': 'get_contact', 'contactId': 2, 'includeUtms': False}).execute({})
    assert requests[0].url.params['includeUtms'] == 'false'
    requests = transport(monkeypatch, {'message': 'ok', 'data': {'transaction': {'id': 1}}})
    await node({'operation': 'update_transaction', 'id': 0, 'value': 0}).execute({})
    assert json.loads(requests[0].content) == {'id': 0, 'value': 0}


@pytest.mark.asyncio
async def test_empty_account_and_last_page(monkeypatch):
    transport(monkeypatch, {'data': {'contacts': [], 'count': 0}})
    result = await node({'operation': 'list_contacts'}).execute({})
    assert result['data'] == [] and not result['has_more'] and result['next_page'] is None
    transport(monkeypatch, {'data': {'contacts': [{'id': 2}], 'count': 21}})
    result = await node({'operation': 'list_contacts', 'page': 1}).execute({})
    assert not result['has_more'] and result['next_page'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 400, 401, 403, 429, 500])
async def test_errors_redact_key_and_never_retry_mutations(monkeypatch, status):
    requests = transport(monkeypatch, {'message': 'Rejected ' + TOKEN, 'details': {'apiKey': TOKEN}}, status)
    result = await node({'operation': 'create_product', 'name': 'Premium'}).execute({})
    assert len(requests) == 1 and result['status'] == 'error' and not result['success']
    assert result['http_status'] == status and TOKEN not in str(result)
    assert result['message'] == 'Rejected [redacted]'


@pytest.mark.asyncio
async def test_ambiguous_write_timeout_is_not_replayed(monkeypatch):
    calls = []

    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout('secret ' + TOKEN, request=request)

    monkeypatch.setattr(native, 'guarded_async_client', lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(respond), **kw))
    with pytest.raises(ValueError, match='write may have completed') as exc:
        await node({'operation': 'create_product', 'name': 'Premium'}).execute({})
    assert len(calls) == 1 and TOKEN not in str(exc.value)


@pytest.mark.asyncio
async def test_unexpected_list_and_provider_error_envelope_are_not_success(monkeypatch):
    transport(monkeypatch, {'data': {'contacts': 'bad', 'count': 1}})
    with pytest.raises(ValueError, match='list envelope'):
        await node({'operation': 'list_contacts'}).execute({})
    transport(monkeypatch, {'status': 403, 'message': 'Denied ' + TOKEN})
    with pytest.raises(ValueError, match='Denied') as exc:
        await node({'operation': 'create_product', 'name': 'Premium'}).execute({})
    assert TOKEN not in str(exc.value)


@pytest.mark.parametrize('config', [
    {'operation': 'list_contacts', 'limit': 101},
    {'operation': 'list_calls', 'contactId': 0},
    {'operation': 'list_contacts', 'page': -1},
    {'operation': 'create_product', 'name': 'a' * 41},
    {'operation': 'create_contact_note', 'contactId': 1, 'note': ''},
    {'operation': 'get_event'},
    {'operation': 'create_deal', 'eventCallId': 1},
    {'operation': 'create_call', 'dateTime': '2026-01-01T00:00:00Z', 'timeZone': 'Etc/UTC'},
    {'operation': 'get_contact', 'contactId': 1, 'url': 'https://evil.test'},
    {'operation': 'reschedule_call', 'id': 1, 'dateTime': 'yesterday', 'timeZone': 'Etc/UTC'},
    {'operation': 'reschedule_call', 'id': 1, 'dateTime': '2026-01-01T00:00:00Z', 'timeZone': 'invalid'},
    {'operation': 'list_contacts', 'orderBy': 'desc'},
    {'operation': 'create_transaction', 'value': float('nan')},
    {'operation': 'update_event_status', 'id': 1, 'status': 'DELETED'},
])
def test_invalid_configs(config):
    with pytest.raises(ValueError):
        native.IClosedNode.parse_config({'config': config})


def test_hand_connect_default_and_key_validation():
    credential = native.IClosedAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == native.CREDENTIAL_TYPE
    assert native.IClosedNode.connection_evidence.operation == 'list_contacts'
    for value in ['Bearer iclosed_x', 'https://example.com/key', 'key\r\nInjected: yes']:
        with pytest.raises(ValidationError):
            native.IClosedAPIKeyCredential(api_key=value)
