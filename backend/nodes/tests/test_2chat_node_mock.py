"""Replay unmodified 2Chat Postman responses through the real node factory."""
import importlib
import json
from pathlib import Path
import httpx
import pytest
from nodes.core.registry import NodeFactory, NODE_REGISTRY
from nodes.core.connection_evidence import collect_evidence

native = importlib.import_module('nodes.2chat_node')
FIXTURE = json.loads((Path(__file__).parent / 'fixtures/2chat/postman_examples.json').read_text())['operations']
TOKEN = 'synthetic-2chat-key'
CREDENTIAL = {'credential_type': '2chat_api_key', 'api_key': TOKEN}
VALUES = {
    'contact_uuid': 'CON58147f7c-3756-4ca1-893c-c3360342b424',
    'channel_uuid': 'WPN66037eca-9ad1-4c96-9eff-526a90a48c77',
    'connected_number': '+595981048477', 'from_number': '+595981048477', 'to_number': '+5215512345432',
    'session_key': 'WA-WAN8fd3442f-e111-4fed-9323-1824fd7546c9-14085550176',
    'message_uuid': 'MSG205dec10-523d-4ab3-b739-fd56e7cdeba2',
    'whatsapp_group_uuid': 'WAG768beeef-2b96-4bc7-9b7f-045078568723',
    'tag_uuid': 'TAGd37f22fa-fe01-4a90-b57d-7e83ccc6a05a',
    'first_name': '2Chat', 'name': 'Hot lead', 'query': 'augusto',
    'text': 'Test from 2Chat API',
    'contact_detail': [{'type': 'PH', 'value': '+17137157533'}],
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def make_node(operation, **changes):
    schema = native.TwoChatNode.get_config_schema()
    member = next(v for v in schema['$defs'].values() if v.get('properties', {}).get('operation', {}).get('const') == operation)
    cfg = {f: VALUES[f] for f in member.get('required', []) if f != 'operation'}
    return NodeFactory.create_node(node_id='2chat-test', node_type='automation-2chat',
        node_data={'config': {'operation': operation, **cfg, **changes}, 'credentials': CREDENTIAL})


def mock_client(monkeypatch, response):
    calls = []
    def respond(request):
        calls.append(request)
        return response(request) if callable(response) else response
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls


CASES = [(op, response) for op, entry in FIXTURE.items() for response in entry['responses']]


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,response', CASES, ids=[f'{op}-{r["name"]}' for op, r in CASES])
async def test_every_saved_provider_response(monkeypatch, operation, response):
    calls = mock_client(monkeypatch, httpx.Response(response['code'], content=response['body'],
        headers=[(h['key'], h['value']) for h in response.get('header', [])]))
    node = make_node(operation)
    body = json.loads(response['body'])
    if not 200 <= response['code'] < 300 or body.get('success') is not True or body.get('error'):
        with pytest.raises(ValueError, match='2Chat'):
            await node.execute({})
    else:
        out = await node.execute({})
        assert out['data'] == body and out['http_status'] == response['code']
    assert len(calls) == 1
    request = calls[0]
    assert request.method == FIXTURE[operation]['method']
    assert request.url.host == 'api.p.2chat.io'
    assert request.headers['X-User-API-Key'] == TOKEN
    assert TOKEN not in str(request.url) and TOKEN.encode() not in request.content
    if request.method in {'POST', 'PUT'}:
        assert request.headers['Content-Type'] == 'application/json'
    if operation == 'create_contact':
        assert json.loads(request.content)['contact_detail'] == VALUES['contact_detail']


@pytest.mark.asyncio
async def test_connection_names_the_actual_account(monkeypatch):
    response = FIXTURE['get_account']['responses'][0]
    calls = mock_client(monkeypatch, httpx.Response(200, content=response['body']))
    result = await collect_evidence(node_type='automation-2chat', user_id='2chat-test', credential_data=CREDENTIAL)
    assert result.reachable is True
    assert 'Account Name' in result.account_label
    assert len(calls) == 1 and calls[0].url.path == '/open/info'


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{'success':False,'error_message':'Rejected'}, {'success':True,'error':True}, {}, [], {'success':True}])
async def test_invalid_account_never_proves_connection(monkeypatch, body):
    mock_client(monkeypatch, httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await make_node('get_account').execute({})


@pytest.mark.asyncio
async def test_rejection_keeps_provider_text_and_redacts_key(monkeypatch):
    mock_client(monkeypatch, httpx.Response(401, text=f'Invalid API key {TOKEN}'))
    with pytest.raises(ValueError, match=r'2Chat HTTP 401: Invalid API key \[redacted\]'):
        await make_node('get_account').execute({})


@pytest.mark.asyncio
async def test_path_segments_encoded_and_response_not_followed(monkeypatch):
    calls = mock_client(monkeypatch, httpx.Response(200, json={'success':True,'contact':{'name':TOKEN}}))
    out = await make_node('get_contact', contact_uuid='../other?x=1').execute({})
    assert calls[0].url.raw_path == b'/open/contacts/..%2Fother%3Fx%3D1'
    assert out['data']['contact']['name'] == '[redacted]'


@pytest.mark.asyncio
async def test_transport_failure_does_not_retry_send(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout('timeout', request=request)
    calls = mock_client(monkeypatch, fail)
    with pytest.raises(ValueError, match='write outcome is unknown'):
        await make_node('send_message').execute({})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_manual_pagination_and_filter_placement(monkeypatch):
    calls = mock_client(monkeypatch, httpx.Response(200, json={'success':True,'contacts':[]}))
    await make_node('search_contacts', page_number=2, results_per_page=10).execute({})
    assert dict(calls[0].url.params) == {'query':'augusto','results_per_page':'10','page_number':'2'}
    assert not calls[0].content


def test_discovery_and_required_shapes():
    assert NODE_REGISTRY['automation-2chat'] is native.TwoChatNode
    assert len(FIXTURE) == 25
    for config in [{'operation':'send_sms','from_number':'123','to_number':'+5215512345432','text':'Hello'},
                   {'operation':'create_contact','first_name':'Name','contact_detail':[]},
                   {'operation':'list_contacts','results_per_page':101}]:
        assert native.TwoChatNode.validate_config({'config':config, 'credentials':CREDENTIAL})['valid'] is False
    for key in ['https://example.com', '<token>', 'key\nvalue', 'Bearer value']:
        with pytest.raises(ValueError):
            native.TwoChatAPIKeyCredential(api_key=key)
