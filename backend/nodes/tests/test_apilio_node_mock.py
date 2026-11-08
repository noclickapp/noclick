"""Replay only the provider's own saved Postman responses; no live account."""
import base64
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import apilio_node as native
from nodes.core.registry import NodeFactory

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/apilio/postman_examples.json').read_text())
TOKEN = base64.b64encode(b'username:password').decode()
CASES = [(operation, response) for operation in FIXTURE['operations'] for response in operation['responses']]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def make_node(config):
    return NodeFactory.create_node(node_id='apilio-fixture', node_type='automation-apilio',
        node_data={'config': config, 'credentials': {'credential_type': 'apilio_api_token', 'api_token': TOKEN}})


def mock_transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,response', CASES, ids=[o['operation']+'-'+str(n) for n,(o,r) in enumerate(CASES)])
async def test_apilio_verbatim_saved_responses_and_wire(monkeypatch, operation, response):
    requests = mock_transport(monkeypatch, httpx.Response(response['status'], content=response['body'], headers={'Content-Type': 'application/json'}))
    result = await make_node(operation['config']).execute({})
    assert result['status'] == 'success'
    assert result['data'] == json.loads(response['body'])
    assert len(requests) == 1
    request = requests[0]
    assert request.method == operation['method']
    assert str(request.url) == native.BASE_URL + operation['path'].format(**operation['config'])
    assert request.headers['Authorization'] == 'Basic ' + TOKEN
    assert not request.url.params
    for key, value in operation['headers'].items():
        assert request.headers[key] == value
    assert (json.loads(request.content) if request.content else None) == operation['body']


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_apilio_refusal_no_redirect_or_retry(monkeypatch, status):
    body = FIXTURE['operations'][0]['responses'][0]['body']
    requests = mock_transport(monkeypatch, httpx.Response(status, content=body,
        headers={'Content-Type': 'application/json', 'Location': 'https://example.invalid'}))
    result = await make_node({'operation': 'list_boolean_variables'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_apilio_malformed_response_rejected(monkeypatch):
    mock_transport(monkeypatch, httpx.Response(200, content=b'invalid JSON', headers={'Content-Type': 'application/json'}))
    with pytest.raises(ValueError, match='invalid JSON'):
        await make_node({'operation': 'list_boolean_variables'}).execute({})


@pytest.mark.asyncio
async def test_apilio_wrong_envelope_rejected(monkeypatch):
    # A documented list cannot stand in for a documented object response.
    response = FIXTURE['operations'][0]['responses'][0]['body']
    mock_transport(monkeypatch, httpx.Response(200, content=response, headers={'Content-Type': 'application/json'}))
    with pytest.raises(ValueError, match='unexpected resource'):
        await make_node(FIXTURE['operations'][1]['config']).execute({})


@pytest.mark.parametrize('token', ['Basic '+TOKEN, 'invalid-token', base64.b64encode(b'no-colon').decode(), base64.b64encode(b'user:').decode(), base64.b64encode(b'user:pass\n').decode()])
def test_apilio_invalid_token_hidden(token):
    with pytest.raises(ValidationError) as exc:
        native.ApilioAPITokenCredential(api_token=token)
    assert token not in str(exc.value)


@pytest.mark.parametrize('resource_id', ['../other', 'x?active=true', 'not-a-uuid'])
def test_apilio_resource_id_is_one_uuid(resource_id):
    with pytest.raises(ValidationError):
        native.GetBooleanVariable(resource_id=resource_id)


def test_apilio_manual_credential_defaults_and_account_evidence():
    credential = native.ApilioAPITokenCredential(api_token=TOKEN)
    assert credential.credential_type == 'apilio_api_token'
    assert native.ApilioNode.connection_evidence.operation == 'list_boolean_variables'
    assert len(native.ROUTES) == 19
    assert all(route.startswith('/api/v1/') for _,route in native.ROUTES.values())
