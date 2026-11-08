"""SignWell request mapping and documented response regressions; no live API calls."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import signwell_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/signwell/published_responses.json').read_text())
TOKEN = 'signwell-test-private-key'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id='signwell-test', node_type='automation-signwell',
        node_data={'config': config, 'credentials': credentials or {'credential_type': 'signwell_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, status, body=None, content=None, headers=None):
    requests = []
    def respond(request):
        requests.append(request)
        if content is not None:
            return httpx.Response(status, content=content, headers=headers)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', FIXTURES)
async def test_one_published_operation_per_request(monkeypatch, operation):
    fixture = FIXTURES[operation]
    requests = transport(monkeypatch, fixture['http_status'], fixture['response'])
    result = await node(fixture['config']).execute({})
    assert result['status'] == 'success'
    assert result['http_status'] == fixture['http_status']
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == 'www.signwell.com' and request.url.scheme == 'https'
    assert request.method == fixture['method'] and request.url.path == fixture['path']
    assert request.headers['X-Api-Key'] == TOKEN
    assert 'authorization' not in request.headers
    assert dict(request.url.params) == fixture['params']
    assert TOKEN not in str(result)
    if operation == 'create_template':
        body = json.loads(request.content)
        assert body['fields'][0][0]['placeholder_id'] == '1'
        assert 'recipient_id' not in body['fields'][0][0]
        assert body['draft'] is True
    elif operation == 'create_document':
        body = json.loads(request.content)
        assert body['fields'][0][0]['recipient_id'] == '1'
        assert body['draft'] is True
        assert 'placeholder_name' not in body['recipients'][0]
    elif operation == 'create_document_from_template':
        body = json.loads(request.content)
        assert body['template_id'] == fixture['config']['template_id']
        assert body['recipients'][0]['placeholder_name'] == 'Client'
    elif operation == 'update_authentication':
        assert 'example-passcode' not in str(result)
        assert json.loads(request.content)['recipients'][0]['passcode'] == 'example-passcode'
    elif operation in ['update_template', 'update_recipients', 'create_webhook']:
        body = json.loads(request.content)
        for key, value in fixture['config'].items():
            if key != 'operation' and not key.endswith('_id'):
                assert body[key] == value
    elif operation == 'get_me':
        assert result['data']['email'] == fixture['response']['user']['email']
        assert result['data']['name'] == fixture['response']['user']['name']
    if fixture['method'] == 'GET':
        assert 'request_acknowledged' not in result
    elif fixture['method'] == 'DELETE':
        assert result['deletion_acknowledged'] is True
    else:
        assert result['request_acknowledged'] is True
        assert 'delivery_verified' not in result


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 422, 429, 500])
async def test_provider_failure_never_looks_successful(monkeypatch, status):
    requests = transport(monkeypatch, status, {'message': f'Not valid authorization token {TOKEN}'})
    result = await node({'operation': 'get_me'}).execute({})
    assert len(requests) == 1
    assert result['status'] == 'error' and result['http_status'] == status
    assert result['message'] == 'Not valid authorization token [redacted]'


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [[], {}, {'user': {'email': 'person@example.com'}}, {'error': 'bad'}, {'errors': ['bad']}])
async def test_missing_identity_or_error_envelope_cannot_prove_connection(monkeypatch, body):
    transport(monkeypatch, 200, body)
    with pytest.raises(ValueError):
        await node({'operation': 'get_me'}).execute({})


@pytest.mark.asyncio
async def test_passcodes_and_api_keys_are_removed_from_output(monkeypatch):
    transport(monkeypatch, 200, {'id': 'doc', 'api_key': TOKEN, 'recipients': [{'passcode': 'private-passcode'}], 'name': TOKEN})
    result = await node({'operation': 'get_document', 'document_id': 'doc'}).execute({})
    assert TOKEN not in str(result) and 'private-passcode' not in str(result)
    assert result['data']['name'] == '[redacted]'


@pytest.mark.asyncio
@pytest.mark.parametrize('identifier', ['../me', 'doc?x=1', 'doc#secret', 'doc/path', '..'])
async def test_path_injection_never_reaches_transport(monkeypatch, identifier):
    requests = transport(monkeypatch, 200, {})
    with pytest.raises(ValueError):
        await node({'operation': 'get_document', 'document_id': identifier}).execute({})
    assert not requests


@pytest.mark.asyncio
async def test_html_is_not_an_account_response(monkeypatch):
    transport(monkeypatch, 200, content=b'<html>login</html>', headers={'content-type': 'text/html'})
    with pytest.raises(ValueError, match='bounded JSON'):
        await node({'operation': 'get_me'}).execute({})


def test_credentials_and_template_fields_are_typed():
    credential = native.SignwellAPIKeyCredential(api_key='  '+TOKEN+'  ')
    assert credential.api_key == TOKEN
    with pytest.raises(ValidationError):
        native.SignwellAPIKeyCredential(credential_type='other_key', api_key=TOKEN)
    with pytest.raises(ValidationError):
        native.SignwellAPIKeyCredential(api_key='https://example.com/key')
    with pytest.raises(ValidationError):
        native.TemplateField(x=1,y=2,page=1,recipient_id='1',type='signature')
    assert native.SignwellNode.connection_evidence.identity_operation == 'get_me'
    with pytest.raises(ValidationError) as invalid:
        native.SignwellFullConfig.model_validate({'config': {'operation': 'get_me'},
            'credentials': {'credential_type': 'other_key', 'api_key': TOKEN}})
    assert TOKEN not in str(invalid.value)
