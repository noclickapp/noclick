"""Remote wire-contract tests; payload fixtures are copied from the pinned OpenAPI."""
import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import ValidationError

from nodes import remote_node as native
from nodes.core.registry import NodeFactory, NODE_REGISTRY

FIXTURES = Path(__file__).parent / 'fixtures' / 'remote'
ACTIONS = json.loads((FIXTURES / 'operations.json').read_text())
EVENTS = json.loads((FIXTURES / 'events.json').read_text())
CREDENTIAL = {'credential_type': 'remote_api_token', 'api_token': 'ra_live_unit-test-credential'}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id='remote-test', node_type='automation-remote',
        node_data={'config': config, 'credentials': credential or CREDENTIAL}, sio=Mock())


def mock_client(monkeypatch, response):
    real_client = httpx.AsyncClient
    requests = []
    def handler(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def factory(**kwargs):
        assert kwargs['follow_redirects'] is False
        return real_client(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(native.httpx, 'AsyncClient', factory)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ACTIONS)
async def test_each_action_maps_to_one_documented_request(monkeypatch, operation):
    spec = ACTIONS[operation]
    config = dict(spec['config'])
    for key in ['id', 'company_id', 'employment_id', 'timeoff_id', 'timesheet_id']:
        if '{' + key + '}' in spec['path']:
            config.setdefault(key, 'documented-resource-id')
    # Fixtures contain provider-authored examples; the untouched response is available to downstream steps.
    response = {'data': {'example': True}}
    requests = mock_client(monkeypatch, response)
    result = await node({'operation': operation, **config}).execute({})
    assert result == {'status': 'success', 'operation': operation, 'data': response}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == spec['method']
    expected_path = spec['path']
    for key, value in config.items():
        expected_path = expected_path.replace('{' + key + '}', str(value))
    assert request.url.path == expected_path
    assert request.url.host == 'gateway.remote.com'
    assert request.headers['Authorization'] == 'Bearer ' + CREDENTIAL['api_token']
    if spec['method'] in {'POST', 'PUT', 'PATCH'} and request.content:
        body = json.loads(request.content)
        # All configured fields that are not path or query parameters reach the JSON body.
        for key, value in config.items():
            if '{' + key + '}' not in spec['path']:
                assert body[key] == (json.loads(value) if key == 'timeoff_days' else value)
    if spec['method'] == 'GET':
        assert not request.content
        for key, value in config.items():
            if '{' + key + '}' not in spec['path']:
                assert request.url.params[key] == (str(value).lower() if isinstance(value, bool) else str(value))


@pytest.mark.asyncio
async def test_sandbox_and_nullable_required_body_keys(monkeypatch):
    requests = mock_client(monkeypatch, {'data': {}})
    await node({'operation': 'approve_timeoff', 'timeoff_id': 'request-id', 'approver_id': None},
               {**CREDENTIAL, 'api_token': 'ra_test_unit-test-credential'}).execute({})
    assert requests[0].url.host == 'gateway.remote-sandbox.com'
    assert json.loads(requests[0].content) == {'approver_id': None}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 400, 401, 403, 404, 422, 429, 500])
async def test_errors_surface_and_do_not_retry_or_leak_token(monkeypatch, status):
    requests = mock_client(monkeypatch, lambda req: httpx.Response(status, text='rejected ' + CREDENTIAL['api_token']))
    with pytest.raises(ValueError) as error:
        await node({'operation': 'list_companies'}).execute({})
    assert str(status) in str(error.value)
    assert CREDENTIAL['api_token'] not in str(error.value)
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('event', EVENTS)
async def test_documented_webhook_register_route_delivery_and_unregister(monkeypatch, event):
    requests = mock_client(monkeypatch, {'data': {'webhook_callback': {'id': 'callback-id', 'signing_key': 'test-signing-key'}}})
    config = {'operation': 'on_event', 'event_type': event}
    state = await native.RemoteNode._register_external_webhook(webhook_url='https://example.com/callback',
        credential=CREDENTIAL, config=config, node_id='remote-test')
    assert state == {'external_webhook_id': 'callback-id', 'signing_secret': 'test-signing-key'}
    assert requests[0].method == 'POST' and requests[0].url.path == '/v1/webhook-callbacks'
    assert json.loads(requests[0].content) == {'url': 'https://example.com/callback', 'subscribed_events': [event]}
    payload = EVENTS[event]['body']
    body = json.dumps(payload).encode()
    timestamp = '1677816097219'
    signature = hmac.new(b'test-signing-key', body + b':' + timestamp.encode(), hashlib.sha256).hexdigest()
    headers = {'X-Remote-Timestamp': timestamp, 'X-Remote-Signature': signature}
    assert native.RemoteNode.verify_webhook_signature(body, headers, state)
    assert not native.RemoteNode.verify_webhook_signature(body + b' ', headers, state)
    assert not native.RemoteNode.verify_webhook_signature(body, {}, state)
    assert not native.RemoteNode.verify_webhook_signature(body, headers, {})
    assert native.RemoteNode.filter_trigger_payload(payload, config)
    assert not native.RemoteNode.filter_trigger_payload({'event_type': 'unsupported'}, config)
    output = native.RemoteNode.resolve_trigger_payload(payload, config)
    turn = native.RemoteNode.resolve_agent_event(output)
    assert 'Remote' in turn['text'] and payload['employment_id'] in turn['text']
    assert payload['company_id'] in turn['text']
    for key, value in payload.items():
        if key.endswith('_id'):
            assert value in turn['text']
    await native.RemoteNode._unregister_external_webhook(credential=CREDENTIAL, config=state, node_id='remote-test')
    assert requests[-1].method == 'DELETE' and requests[-1].url.path == '/v1/webhook-callbacks/callback-id'


def test_provider_signature_example():
    # Verbatim raw request and expected digest from https://developer.remote.com/docs/verifying-webhooks.
    body = b'{"company_id":"9e88cdac-4e57-46ca-a5a8-580150935cd8","completed_task":{"action":"identity_verification","completed_at":"2023-02-16T07:52:26Z","description":"To help us keep you and our platform safe.","name":"Verify your identity","required":true,"status":"completed"},"employment_id":"b6e66f7c-9026-4afc-9f43-37bb31a8e509","event_type":"employment.onboarding_task.completed"}'
    assert native.RemoteNode.verify_webhook_signature(body,
        {'x-remote-timestamp': '1677816097219', 'x-remote-signature': 'e3f4092f158983aea32ab25f6fecc59f64b26d45fadbed6409893f3a882abef7'},
        {'signing_secret': 'wkyzvs764ifdrpct2naqhksmq4'})


def test_discovery_manual_connect_and_input_guards():
    assert NODE_REGISTRY['automation-remote'] is native.RemoteNode
    assert native.RemoteAPITokenCredential.model_validate({'api_token': CREDENTIAL['api_token']}).credential_type == 'remote_api_token'
    for config in [{'operation': 'get_employment', 'employment_id': '../escape'}, {'operation': 'list_timeoff', 'page_size': 101},
                   {'operation': 'create_incentive'}, {'operation': 'on_event', 'event_type': 'invented'}]:
        with pytest.raises((ValidationError, ValueError)):
            node(config)
