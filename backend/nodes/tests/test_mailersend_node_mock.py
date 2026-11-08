"""MailerSend serialization and published-response regression coverage."""
import json
from pathlib import Path
import httpx
import pytest
from nodes import mailersend_node as native
from nodes.core.registry import NodeFactory

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/mailersend/documented_contract.json').read_text())
AUTH = {'credential_type': 'mailersend_api_token', 'api_token': 'synthetic-mailersend-token'}

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config, auth=None):
    return NodeFactory.create_node(node_id='mailersend-test', node_type='automation-mailersend',
        node_data={'config': config, 'credentials': AUTH if auth is None else auth})

def transport(monkeypatch, response):
    requests = []
    def reply(request):
        requests.append(request)
        return response
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(native.ROUTES))
async def test_documented_requests_and_responses(monkeypatch, operation):
    method, path = native.ROUTES[operation]
    config = FIXTURE['inputs'][operation]['config']
    example = FIXTURE['witnesses'].get(method + ' ' + path)
    response = httpx.Response(200, json=example['body']) if example else httpx.Response(204)
    if operation == 'send_email':
        response = httpx.Response(202, headers={'x-message-id': 'queued-message'})
    requests = transport(monkeypatch, response)
    result = await node(config).execute({})
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.host == 'api.mailersend.com'
    assert req.headers['authorization'] == 'Bearer ' + AUTH['api_token']
    for key, value in config.items():
        path = path.replace('{' + key + '}', str(value))
    assert req.url.path == '/v1' + path
    assert not req.url.query
    if operation == 'send_email':
        assert json.loads(req.content) == config['message']
        assert result['status'] == 'accepted' and result['delivery_verified'] is False
        assert result['message_id'] == 'queued-message'
    elif operation == 'send_bulk_email':
        assert json.loads(req.content) == config['messages']
        assert result['data']['bulk_email_id'] == example['body']['bulk_email_id']
    elif operation.startswith('add_'):
        assert json.loads(req.content) == {k: v for k, v in config.items() if k != 'operation'}
    else:
        assert req.content == b''
    if operation.startswith('list_'):
        assert result['data'] == example['body']['data']
        assert result.get('meta') == example['body'].get('meta')
    assert AUTH['api_token'] not in json.dumps(result)

@pytest.mark.parametrize('bad', ['a/b', '..', 'a%2fb', 'https://example.com', 'id\n'])
def test_invalid_id_before_transport(bad):
    with pytest.raises(ValueError):
        node({'operation': 'get_domain', 'domain_id': bad})

@pytest.mark.parametrize('credential', [
    {**AUTH, 'credential_type': 'other_api_key'},
    {**AUTH, 'api_token': 'Bearer abc'},
    {**AUTH, 'api_token': 'https://example.com/token'},
])
def test_invalid_credential_before_transport(credential):
    with pytest.raises(ValueError):
        node({'operation': 'list_domains'}, auth=credential)

@pytest.mark.asyncio
@pytest.mark.parametrize('code', [301, 401, 403, 422, 429, 500])
async def test_error_status_and_token_redaction(monkeypatch, code):
    requests = transport(monkeypatch, httpx.Response(code, json={'message': 'Rejected ' + AUTH['api_token']}))
    with pytest.raises(ValueError) as exc:
        await node({'operation': 'list_domains'}).execute({})
    assert 'HTTP ' + str(code) in str(exc.value)
    assert AUTH['api_token'] not in str(exc.value)
    assert len(requests) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize('response', [
    httpx.Response(200, text='<html>login</html>'),
    httpx.Response(200, json={'errors': {'token': ['invalid']}}),
    httpx.Response(200, json={}),
    httpx.Response(200, json={'data': {}}),
    httpx.Response(200, text='broken', headers={'content-type': 'application/json'}),
])
async def test_bad_list_response_is_not_connection_evidence(monkeypatch, response):
    transport(monkeypatch, response)
    with pytest.raises(ValueError):
        await node({'operation': 'list_domains'}).execute({})

@pytest.mark.asyncio
async def test_empty_account_and_no_link_following(monkeypatch):
    requests = transport(monkeypatch, httpx.Response(200, json={
        'data': [], 'links': {'next': 'https://other.example/steal-token'}, 'meta': {'current_page': 1}}))
    result = await node({'operation': 'list_domains'}).execute({})
    assert result['status'] == 'success' and result['data'] == []
    assert len(requests) == 1

def test_missing_required_body_and_unrecognized_fields():
    for config in [
        {'operation': 'send_email', 'message': {'from': {'email': 'a@example.com'}, 'to': []}},
        {'operation': 'send_bulk_email', 'messages': []},
        {'operation': 'add_blocklist_recipients', 'domain_id': 'abc', 'recipients': ['invalid']},
        {'operation': 'list_domains', 'url': 'https://example.com'},
    ]:
        with pytest.raises(ValueError):
            node(config)
