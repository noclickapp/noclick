"""Provider-saved Postman examples, request signatures and webhook lifecycle."""
import base64
import copy
import hashlib
import hmac
import json
import re
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import dux_soup_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/dux_soup/postman_examples.json').read_text())
CREDS = {'credential_type': 'dux_soup_api_key', 'userid': '102578215570888450487', 'api_key': 'unit-test-auth-key'}

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def config_for(operation):
    cfg = {'operation': operation}
    raw = EXAMPLES[operation]['request'].get('body', {}).get('raw', '')
    if raw.strip():
        raw = re.sub(r'(?<!")\{\{timestamp\}\}', '1783340937755', raw)
        body = json.loads(raw)
        cfg.update(body.get('params', {}) if 'command' in body else
            {k: v for k, v in body.items() if k not in {'targeturl', 'timestamp', 'userid'}})
    if operation in {'get_campaign', 'enroll_profile', 'unenroll_profile'}:
        cfg['campaignid'] = 'default'
    if operation in {'get_conversation', 'add_prospect_tags'}:
        cfg['profileid'] = 'id.123456789'
    return cfg

def node(cfg):
    return NodeFactory.create_node(node_id='dux-fixture', node_type='automation-dux-soup',
        node_data={'config': cfg, 'credentials': CREDS})

def transport(monkeypatch, operation, *, status=None, payload=None):
    calls = []
    real_client = httpx.AsyncClient
    example = EXAMPLES[operation]['response']
    def reply(request):
        calls.append(request)
        return httpx.Response(status or example['code'],
            content=example['body'].encode() if payload is None else json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json'})
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        return real_client(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native.httpx, 'AsyncClient', client)
    return calls

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(EXAMPLES))
async def test_dux_soup_saved_responses_and_signed_requests(monkeypatch, operation):
    calls = transport(monkeypatch, operation)
    cfg = config_for(operation)
    expected = json.loads(EXAMPLES[operation]['response']['body'])
    assert await node(cfg).execute({}) == ({'items': expected} if isinstance(expected, list) else expected)
    assert len(calls) == 1
    req = calls[0]
    assert req.url.host == 'app.dux-soup.com'
    assert req.method == native.OPERATIONS[operation][2]
    if req.method == 'GET':
        assert not req.content
        message = str(req.url).encode()
    else:
        message = req.content
        body = json.loads(message)
        assert body['targeturl'] == str(req.url)
        assert body['userid'] == CREDS['userid']
        assert abs(body['timestamp'] - int(native.time.time() * 1000)) < 1000
        command = native.OPERATIONS[operation][4]
        if command:
            assert body['command'] == command
            assert body['params'] == {k: v for k, v in cfg.items() if k != 'operation'}
    expected = base64.b64encode(hmac.new(CREDS['api_key'].encode(), message, hashlib.sha1).digest()).decode()
    assert req.headers['X-Dux-Signature'] == expected
    assert CREDS['api_key'] not in req.content.decode()
    if operation == 'get_recent_actions':
        assert dict(req.url.params) == {'days': '30', 'limit': '100'}

@pytest.mark.asyncio
async def test_dux_soup_campaign_picker(monkeypatch):
    transport(monkeypatch, 'list_campaigns')
    result = await native.DuxSoupNode.load_field_options('campaignid', CREDS)
    assert result['options'] == [{'value': r['id'], 'label': r['name']} for r in json.loads(EXAMPLES['list_campaigns']['response']['body'])['campaigns']]

@pytest.mark.asyncio
@pytest.mark.parametrize('status,payload', [(401, {'error': 'Invalid signature'}), (200, {'success': False, 'error': 'Remote Control disabled'})])
async def test_dux_soup_rejections_raise(monkeypatch, status, payload):
    transport(monkeypatch, 'get_user_profile', status=status, payload=payload)
    with pytest.raises((httpx.HTTPStatusError, ValueError)):
        await node({'operation': 'get_user_profile'}).execute({})

def test_dux_soup_manual_credential_and_resource_ids():
    assert native.DuxSoupCredential.model_validate({k: v for k, v in CREDS.items() if k != 'credential_type'}).credential_type == 'dux_soup_api_key'
    for change in [{'userid': '../other'}, {'api_key': 'https://example.com/key'}]:
        with pytest.raises(ValidationError):
            native.DuxSoupCredential.model_validate({**CREDS, **change})
    with pytest.raises(ValueError):
        node({'operation': 'visit_profile', 'profile': 'https://evil.example/in/a'})
    for cfg in [{'operation': 'get_campaign', 'campaignid': '..'}, {'operation': 'get_conversation', 'profileid': '.'}]:
        with pytest.raises(ValueError):
            node(cfg)

@pytest.mark.asyncio
async def test_dux_soup_path_id_encoded(monkeypatch):
    calls = transport(monkeypatch, 'get_campaign')
    await node({'operation': 'get_campaign', 'campaignid': 'a/b?x=1'}).execute({})
    assert calls[0].url.raw_path.endswith(b'/campaigns/a%2Fb%3Fx%3D1')

@pytest.mark.asyncio
async def test_dux_soup_connection_probe_refuses_another_account(monkeypatch):
    transport(monkeypatch, 'get_user_profile')
    creds = {**CREDS, 'userid': 'different-account'}
    n = NodeFactory.create_node(node_id='dux-probe', node_type='automation-dux-soup',
        node_data={'config': {'operation': 'get_user_profile'}, 'credentials': creds})
    with pytest.raises(ValueError, match='unexpected account identity'):
        await n.execute({})


EVENTS = json.loads((Path(__file__).parent / 'fixtures/dux_soup/webhook_events.json').read_text())
SETTINGS = json.loads((Path(__file__).parent / 'fixtures/dux_soup/webhook_settings.json').read_text())

@pytest.mark.parametrize('event', list(EVENTS))
def test_dux_soup_documented_webhook_payloads(event):
    payload = EVENTS[event]['body']
    op = next(op for op, kind in native.TRIGGERS.items() if kind == payload['type'])
    config = {'operation': op}
    assert native.DuxSoupNode.verify_webhook_signature(json.dumps(payload).encode(), {}, config)
    assert native.DuxSoupNode.filter_trigger_payload(payload, config)
    output = native.DuxSoupNode.resolve_trigger_payload(payload, config)
    result = native.DuxSoupNode.resolve_agent_event(output)
    assert result['text'].startswith('Dux-Soup account ')
    assert payload['userid'] in result['text']
    assert 'id.' in result['text'] and result['conversation_key'].startswith('dux-soup:')
    if payload['type'] == 'message':
        assert payload['data']['text'] in result['text']
    for other in native.TRIGGERS:
        if other != op:
            assert not native.DuxSoupNode.filter_trigger_payload(payload, {'operation': other})

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(native.TRIGGERS))
async def test_dux_soup_webhook_register_idempotent_and_unregister_preserves_others(monkeypatch, operation):
    state = json.loads(SETTINGS['Read User Settings']['response']['body'])
    original_hooks = copy.deepcopy(state['webhooks'])
    calls = []
    real_client = httpx.AsyncClient
    def reply(req):
        calls.append(req)
        if req.method == 'GET':
            return httpx.Response(200, json=state)
        body = json.loads(req.content)
        assert set(body) == {'targeturl', 'timestamp', 'userid', 'settings'}
        state.update(body['settings'])
        return httpx.Response(200, content=SETTINGS['Update User Settings']['response']['body'].encode())
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(reply), **kw))
    url = 'https://unique-workflow.hooks.example.test/webhook-fixture'
    cfg = {'operation': operation}
    extra = await native.DuxSoupNode._register_external_webhook(webhook_url=url, credential=CREDS, config=cfg, node_id='test')
    assert extra == {'external_webhook_id': url}
    assert state['webhookprofileflag'] is True
    assert state['webhooks'] == [*original_hooks, {'url': url, 'events': [native.TRIGGERS[operation]]}]
    await native.DuxSoupNode._register_external_webhook(webhook_url=url, credential=CREDS, config=cfg, node_id='test')
    assert len(state['webhooks']) == len(original_hooks) + 1
    await native.DuxSoupNode._unregister_external_webhook(credential=CREDS, config={**cfg, **extra}, node_id='test')
    assert state['webhooks'] == original_hooks
    assert json.loads(calls[-1].content)['settings'] == {'webhooks': original_hooks}
    before = len(calls)
    await native.DuxSoupNode._unregister_external_webhook(credential=CREDS, config={**cfg, **extra}, node_id='test')
    assert len(calls) == before + 1  # only a read, already removed

@pytest.mark.asyncio
async def test_dux_soup_trigger_manual_run_cannot_pass_other_nodes_data():
    output = await node({'operation': 'on_linkedin_message'}).execute({'unrelated': {'text': 'do not deliver'}})
    assert output == {'status': 'no_event', 'operation': 'on_linkedin_message'}
    assert native.DuxSoupNode.resolve_agent_event(output) is None
