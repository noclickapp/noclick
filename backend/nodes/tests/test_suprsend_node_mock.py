"""SuprSend published wire requests, responses, and polling regressions."""
import copy
import json
from pathlib import Path
import httpx
import pytest
from nodes import suprsend_node as native
from nodes.core.poll_trigger import poll_scope
from nodes.core.registry import NodeFactory

FIXTURES = Path(__file__).parent / 'fixtures/suprsend'
CASES = json.loads((FIXTURES / 'request_cases.json').read_text())
EXAMPLES = json.loads((FIXTURES / 'provider_examples.json').read_text())
AUTH = {'credential_type': 'suprsend_api_key', 'api_key': 'synthetic-suprsend-key'}

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config, credential=None):
    return NodeFactory.create_node(node_id='suprsend-test', node_type='automation-suprsend',
        node_data={'config': config, 'credentials': AUTH if credential is None else credential})

def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request) if callable(reply) else reply
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['operation'])
async def test_published_endpoint_request_and_response(monkeypatch, case):
    op = case['operation']
    if op == 'trigger_event':
        response = httpx.Response(202, text='OK')
    elif op == 'delete_user':
        response = httpx.Response(204)
    else:
        response = httpx.Response(EXAMPLES[op]['status'], json=EXAMPLES[op]['body'])
    requests = transport(monkeypatch, response)
    result = await node({'operation': op, **case['config']}).execute({})
    assert len(requests) == 1
    req = requests[0]
    assert req.method == case['method'] and req.url.host == 'hub.suprsend.com'
    assert req.url.path == case['path'] and dict(req.url.params) == case['query']
    assert req.headers['authorization'] == 'Bearer ' + AUTH['api_key']
    assert (json.loads(req.content) if req.content else None) == case['body']
    expected = {'accepted': True, 'delivery_verified': False} if op == 'trigger_event' else {} if op == 'delete_user' else EXAMPLES[op]['body']
    assert result['data'] == expected
    assert AUTH['api_key'] not in json.dumps(result)

@pytest.mark.parametrize('credential', [
    {**AUTH, 'credential_type': 'other_api_key'}, {**AUTH, 'api_key': 'Bearer abc'},
    {**AUTH, 'api_key': 'https://example.com/key'},
])
def test_reject_invalid_manual_credentials(credential):
    with pytest.raises(ValueError): node({'operation': 'list_lists'}, credential)

def test_manual_credential_type_has_default():
    assert native.SuprSendAPIKeyCredential(api_key='synthetic-key').credential_type == 'suprsend_api_key'

@pytest.mark.parametrize('value', ['issued–key', 'issued\u200bkey', 'https://example.com/settings/tokens'])
def test_credential_class_itself_rejects_non_ascii_or_address_keys(value):
    with pytest.raises(ValueError):
        native.SuprSendAPIKeyCredential(api_key=value)

@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 422, 429, 500])
async def test_rejection_is_not_success_and_key_is_redacted(monkeypatch, status):
    requests = transport(monkeypatch, httpx.Response(status, text='Rejected ' + AUTH['api_key']))
    with pytest.raises(ValueError, match=f'HTTP {status}') as exc:
        await node({'operation': 'list_lists'}).execute({})
    assert AUTH['api_key'] not in str(exc.value) and len(requests) == 1

@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'code': 401, 'message': 'invalid key'}, {'results': {}}, {'results': [], 'meta': None}])
async def test_malformed_list_cannot_prove_connection(monkeypatch, body):
    transport(monkeypatch, httpx.Response(200, json=body))
    with pytest.raises(ValueError, match='list response'):
        await node({'operation': 'list_lists'}).execute({})

@pytest.mark.asyncio
async def test_empty_workspace_can_prove_connection(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={'meta': {'count': 0}, 'results': []}))
    assert (await node({'operation': 'list_lists'}).execute({}))['data']['results'] == []

@pytest.mark.asyncio
@pytest.mark.parametrize('config', [
    {'operation': 'trigger_workflow', 'workflow': 'task-reminder', 'recipients_json': '{}'},
    {'operation': 'upsert_user', 'distinct_id': 'user1', 'payload_json': '[]'},
    {'operation': 'update_user', 'distinct_id': 'user1', 'operations_json': 'broken'},
    {'operation': 'cancel_workflow'},
    {'operation': 'update_tenant_properties', 'tenant_id': 'acme', 'payload_json': '{"properties": {}, "operations": []}'},
    {'operation': 'get_user', 'distinct_id': '../someone'},
])
async def test_invalid_request_refused_before_transport(monkeypatch, config):
    requests = transport(monkeypatch, httpx.Response(200, json={}))
    with pytest.raises(ValueError): await node(config).execute({})
    assert not requests

@pytest.mark.asyncio
async def test_poll_baselines_then_emits_new_provider_message_once(monkeypatch):
    messages = EXAMPLES['list_messages']['body']['results']
    visible = [messages[0]]
    def reply(req):
        assert req.url.path == '/v1/message/'
        for key, value in {'channel': 'inbox', 'tenant_id': 'acme', 'workflow_slug': 'order-confirmation',
                           'created_at_gte': '2026-04-26T21:34:33Z'}.items():
            assert req.url.params[key] == value
        return httpx.Response(200, json={'results': visible, 'meta': {'has_next': False}})
    transport(monkeypatch, reply)
    instance = node({'operation': 'on_new_message', 'channel': 'inbox', 'tenant_id': 'acme',
                     'workflow_slug': 'order-confirmation', 'created_at_gte': '2026-04-26T21:34:33Z'})
    state = {}
    async def update(mutator, **kwargs):
        nonlocal state
        next_state, result = mutator(copy.deepcopy(state))
        if next_state is not None: state = next_state
        return result
    monkeypatch.setattr(instance, '_update_node_state', update)
    baseline = await instance.execute({})
    assert baseline['messages'] == [] and instance.trigger_produced_no_event(baseline)
    visible.insert(0, messages[1])
    fresh = await instance.execute({})
    assert fresh['messages'] == [messages[1]] and instance.trigger_emitted_event(fresh)
    event = native.SuprSendNode.resolve_agent_event(fresh)
    for value in [messages[1]['message_id'], messages[1]['recipient']['distinct_id'], messages[1]['content']['body']]:
        assert value in event['text']
    assert (await instance.execute({}))['new_message_count'] == 0
    assert poll_scope(native.SuprSendNode, {'operation': 'on_new_message', 'tenant_id': 'other'}) != state['scope']

@pytest.mark.asyncio
async def test_poll_follows_opaque_cursor_and_refuses_loop_before_recording(monkeypatch):
    example = EXAMPLES['list_messages']['body']
    requests = transport(monkeypatch, httpx.Response(200, json=example))
    instance = node({'operation': 'on_new_message'})
    async def no_state(*args, **kwargs): pytest.fail('Incomplete pagination must not update the seen set')
    monkeypatch.setattr(instance, '_update_node_state', no_state)
    with pytest.raises(ValueError, match='pagination did not advance'): await instance.execute({})
    assert len(requests) == 2
    assert requests[1].url.params['after'] == example['meta']['after']
