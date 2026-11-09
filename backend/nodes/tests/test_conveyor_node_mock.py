"""Conveyor Portal API contract regressions through the native node factory.

Fixtures retain provider-authored examples from the pinned Portal OpenAPI;
MockTransport verifies requests without connecting to a provider account.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import conveyor_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/conveyor/portal_examples.json').read_text())
KEY = 'synthetic-conveyor-api-key'
IDENTIFIER = '6f82c222-3c4b-4699-89bd-fdc9c79ca283'
CREDENTIAL = {'credential_type': 'conveyor_api_key', 'api_key': KEY}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id='conveyor-fixture', node_type='automation-conveyor',
        node_data={'config': config, 'credentials': CREDENTIAL if credentials is None else credentials})


def mock(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response(request) if callable(response) else response
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


def config_for(operation):
    value = {'operation': operation}
    for name in native.ROUTES[operation]['path_fields']:
        value[name] = IDENTIFIER
    if operation == 'create_folder':
        value['name'] = 'super'
    if operation == 'ignore_authorization_request':
        value['reviewer_email'] = 'reviewer@example.com'
    if operation == 'create_authorization':
        value['email'] = 'foo@bar.com'
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(EXAMPLES))
async def test_conveyor_one_published_request_and_documented_response(monkeypatch, operation):
    example = EXAMPLES[operation]
    response = httpx.Response(example['status'], **({'json': example['body']} if example['status'] != 204 else {}))
    requests = mock(monkeypatch, response)
    result = await node(config_for(operation)).execute({})
    assert result['status'] == 'success'
    assert result['data'] == (None if example['status'] == 204 else example['body'])
    assert len(requests) == 1
    request = requests[0]
    assert request.method == example['method']
    assert request.url.scheme == 'https' and request.url.host == 'api.conveyor.com'
    expected_path = example['path']
    for field in native.ROUTES[operation]['path_fields']:
        expected_path = expected_path.replace('{' + field + '}', IDENTIFIER)
    assert request.url.path == '/api' + expected_path
    assert request.headers['X-API-KEY'] == KEY
    assert request.content == b''
    if operation == 'ignore_authorization_request':
        assert dict(request.url.params) == {'status': 'ignored', 'reviewer_email': 'reviewer@example.com'}
    if operation in native.LIST_KEYS:
        assert isinstance(result['items'], list)
    assert KEY not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('recipient', [{'email': 'foo@bar.com'}, {'request_id': IDENTIFIER}])
async def test_conveyor_authorization_accepts_either_documented_recipient(monkeypatch, recipient):
    requests = mock(monkeypatch, httpx.Response(204))
    result = await node({'operation': 'create_authorization', **recipient, 'nda_bypass': False,
        'access_group_ids': ['group-one', 'group-two'], 'expires_at': '2026-12-31'}).execute({})
    assert result['status'] == 'success'
    params = requests[0].url.params
    assert params.get_list('access_group_ids') == ['group-one', 'group-two']
    assert params['nda_bypass'] == 'false' and params['expires_at'] == '2026-12-31'
    assert all(params[k] == v for k, v in recipient.items())
    assert ('request_id' if 'email' in recipient else 'email') not in params


@pytest.mark.asyncio
async def test_conveyor_document_edit_preserves_false_and_only_sends_supplied_fields(monkeypatch):
    requests = mock(monkeypatch, httpx.Response(200, json=EXAMPLES['update_document']['body']))
    result = await node({'operation': 'update_document', 'document_id': IDENTIFIER,
        'featured': False, 'disable_downloads': False, 'access_level': 'internal',
        'access_group_ids': 'group-one,group-two'}).execute({})
    assert result['status'] == 'success'
    assert dict(requests[0].url.params) == {'featured': 'false', 'disable_downloads': 'false',
        'access_level': 'internal', 'access_group_ids': 'group-one,group-two'}


@pytest.mark.asyncio
async def test_conveyor_authorization_revoke(monkeypatch):
    requests = mock(monkeypatch, httpx.Response(200, json=EXAMPLES['update_authorization']['body']))
    result = await node({'operation': 'update_authorization', 'authorization_id': IDENTIFIER,
        'status': 'revoked'}).execute({})
    assert result['status'] == 'success'
    assert dict(requests[0].url.params) == {'status': 'revoked'}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 400, 401, 403, 404, 429, 500])
async def test_conveyor_errors_are_failures_and_redact_key(monkeypatch, status):
    requests = mock(monkeypatch, httpx.Response(status, json={'message': 'Denied: ' + KEY}))
    result = await node({'operation': 'list_folders'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert KEY not in json.dumps(result)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{'wrong': []}, {'_embedded': {'folders': 'bad'}}, {'error': 'denied'}, None])
async def test_conveyor_malformed_connection_evidence_never_succeeds(monkeypatch, body):
    mock(monkeypatch, httpx.Response(200, json=body))
    result = await node({'operation': 'list_folders'}).execute({})
    assert result['status'] == 'error'


@pytest.mark.asyncio
async def test_conveyor_empty_account_folder_list_is_valid_evidence(monkeypatch):
    mock(monkeypatch, httpx.Response(200, json={'_embedded': {'folders': []}}))
    result = await node({'operation': 'list_folders'}).execute({})
    assert result['status'] == 'success' and result['items'] == []
    assert native.ConveyorNode.connection_evidence.operation == 'list_folders'
    assert native.ConveyorNode.connection_evidence.proves == 'account'


@pytest.mark.asyncio
async def test_conveyor_network_failure_is_unconfirmed(monkeypatch):
    def fail(request):
        raise httpx.ConnectError('offline', request=request)
    mock(monkeypatch, fail)
    assert (await node({'operation': 'list_folders'}).execute({}))['status'] == 'error'


@pytest.mark.parametrize('key', ['', 'https://example.com/key', '<token>', 'key\nvalue'])
def test_conveyor_invalid_pasted_key_is_rejected(key):
    with pytest.raises(ValidationError):
        native.ConveyorAPIKeyCredential(api_key=key)


def test_conveyor_manual_credential_defaults_type_and_trims_key():
    value = native.ConveyorAPIKeyCredential(api_key='  '+KEY+'  ')
    assert value.credential_type == 'conveyor_api_key' and value.api_key == KEY


@pytest.mark.parametrize('config', [
    {'operation': 'create_authorization'},
    {'operation': 'get_authorization_request', 'authorization_request_id': '../other'},
    {'operation': 'ignore_authorization_request', 'authorization_request_id': IDENTIFIER, 'reviewer_email': 'a@b.com', 'status': 'approved'},
    {'operation': 'update_authorization', 'authorization_id': IDENTIFIER, 'status': 'authorized'},
    {'operation': 'create_folder', 'name': 'folder', 'unknown': 'field'},
])
def test_conveyor_invalid_operations_rejected(config):
    assert not native.ConveyorNode.validate_config({'config': config, 'credentials': CREDENTIAL})['valid']
