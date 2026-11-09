"""Offline regressions against BotConversa's published BETA API."""
import json
import re
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import botconversa_node as native
from nodes.core.registry import NodeFactory

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/botconversa/operations.json').read_text())
TOKEN = 'synthetic-botconversa-key'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id='botconversa-test', node_type='automation-botconversa',
        node_data={'config': config, 'credentials': {'credential_type': 'botconversa_api_key', 'api_key': TOKEN}})

def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests

def config_for(name):
    _, path, _ = native.ROUTES[name]
    cfg = {'operation': name, **{field: '123' for field in re.findall(r'{(\w+)}', path)}}
    cfg.update({
        'create_subscriber': {'phone': '5511999999999', 'first_name': 'Ana', 'last_name': 'Silva', 'has_opt_in_whatsapp': False},
        'send_message': {'type': 'text', 'value': 'Hello'}, 'send_flow': {'flow': 23},
        'change_conversation_status': {'open_conversation': False, 'manager': 7},
        'set_custom_field': {'value': '09.11.2026'}, 'set_bot_field': {'value': 'active'},
        'list_subscribers': {'page': 2},
    }.get(name, {}))
    return cfg

@pytest.mark.asyncio
@pytest.mark.parametrize('name', FIXTURE['operations'])
async def test_one_documented_request_per_operation(monkeypatch, name):
    fixture = FIXTURE['operations'][name]
    status = int(next(k for k in fixture['operation']['responses'] if k.startswith('2')))
    body = [] if name.startswith('list_') and name != 'list_subscribers' else {'count': 0, 'results': [], 'next': None, 'previous': None} if name == 'list_subscribers' else {}
    requests = transport(monkeypatch, body, status)
    cfg = config_for(name)
    result = await node(cfg).execute({})
    assert result == {'status': 'success', 'data': body}
    assert len(requests) == 1
    request = requests[0]
    path = fixture['path']
    for field in re.findall(r'{(\w+)}', path):
        path = path.replace('{' + field + '}', str(cfg[field]))
    assert str(request.url).split('?')[0] == native.BASE_URL + path
    assert request.method == fixture['method'] and request.headers['API-KEY'] == TOKEN
    fields = native.ROUTES[name][2]
    if request.method != 'GET':
        assert json.loads(request.content) == {f: cfg[f] for f in fields if f in cfg}
    else:
        assert not request.content
    assert dict(request.url.params) == ({'page': '2'} if name == 'list_subscribers' else {})

@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 400, 401, 403, 404, 429, 500])
async def test_provider_failure_and_secret_redaction(monkeypatch, status):
    requests = transport(monkeypatch, {'error_message': 'API-KEY is invalid ' + TOKEN}, status)
    with pytest.raises(ValueError) as error:
        await node({'operation': 'list_tags'}).execute({})
    assert TOKEN not in str(error.value) and len(requests) == 1
    assert f"(HTTP {status})" in str(error.value)

@pytest.mark.asyncio
async def test_success_error_envelope_is_not_evidence(monkeypatch):
    transport(monkeypatch, {'error_message': 'API-KEY is invalid'})
    with pytest.raises(ValueError, match='API-KEY is invalid'):
        await node({'operation': 'list_tags'}).execute({})

def test_credentials_manual_default_and_path_boundaries():
    assert native.BotConversaAPIKeyCredential(api_key=TOKEN).credential_type == 'botconversa_api_key'
    for value in ['../other', '123/456', '123?x=1', '']:
        with pytest.raises(ValidationError):
            native.AddSubscriberTagConfig(subscriber_id=value, tag_id='1')


@pytest.mark.asyncio
async def test_phone_is_one_encoded_segment(monkeypatch):
    requests = transport(monkeypatch, {"id": 1})
    await node({"operation": "find_subscriber_by_phone", "phone": "+5511999999999"}).execute({})
    assert requests[0].url.raw_path.endswith(b"/get_by_phone/%2B5511999999999/")
    with pytest.raises(ValidationError):
        native.FindSubscriberByPhoneConfig(phone="..")


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body,reachable', [
    (200, [{'id': 1, 'name': 'Customers'}], True),
    (403, {'error_message': 'API-KEY is invalid'}, False),
    (500, {'error_message': 'Service unavailable'}, None),
])
async def test_connection_evidence_uses_account_tags_and_definitive_rejection(monkeypatch, status, body, reachable):
    from nodes.core.connection_evidence import collect_evidence
    from nodes.core import run_op
    transport(monkeypatch, body, status)
    async def run(**kwargs):
        assert kwargs['operation'] == 'list_tags' and kwargs['arguments'] == {}
        return await node({'operation': kwargs['operation']}).execute({})
    monkeypatch.setattr(run_op, 'run_node_operation', run)
    result = await collect_evidence(node_type='automation-botconversa', user_id='test-user', pool=None,
        credential_data={'credential_type': 'botconversa_api_key', 'api_key': TOKEN})
    assert result.reachable is reachable
    if reachable:
        assert result.samples[0].label == 'Customers'
    elif reachable is False:
        assert 'API-KEY is invalid' in result.error
