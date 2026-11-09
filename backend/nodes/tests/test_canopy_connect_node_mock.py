"""Offline Canopy Connect contract, credential and failure regressions."""
import base64
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import canopy_connect_node as native
from nodes.core.registry import NodeFactory

TEAM = '123e4567-e89b-12d3-a456-426614174000'
RESOURCE = '4dadb30c-95cd-4b17-aa99-0245e4ff6064'
CREDENTIAL = {'credential_type': 'canopy_connect_api_key', 'canopy_team_id': TEAM,
              'client_id': 'synthetic-client', 'client_secret': 'synthetic-secret'}
PROFILE = json.loads((Path(__file__).parent / 'fixtures/canopy-connect/team.json').read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='canopy-test', node_type='automation-canopy-connect',
        node_data={'config': config, 'credentials': CREDENTIAL})


def transport(monkeypatch, payload, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        if isinstance(payload, Exception):
            raise payload
        return httpx.Response(status, json=payload)
    original = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


# Independent expectations from the provider's published 1.0.0 routes.
CASES = [
    ('get_team', {}, 'GET', '', PROFILE),
    ('list_pulls', {'limit': 2, 'offset': 4}, 'GET', '/pulls', {'pulls': []}),
    ('get_pull', {'pullId': RESOURCE}, 'GET', '/pulls/' + RESOURCE, {'pull_id': RESOURCE}),
    ('update_pull', {'pullId': RESOURCE, 'is_archived': False}, 'PATCH', '/pulls/' + RESOURCE, {'success': True}),
    ('check_pull_policy', {'pullId': RESOURCE}, 'POST', '/pulls/' + RESOURCE + '/policyCheck', {'success': True}),
    ('list_webhooks', {}, 'GET', '/webhooks', {'webhooks': []}),
    ('create_webhook', {'hookUrl': 'https://example.com/hook', 'eventTypes': ['COMPLETE']}, 'POST', '/webhooks', {'webhook_id': RESOURCE}),
    ('update_webhook', {'webhookId': RESOURCE, 'isActive': False}, 'PATCH', '/webhooks/' + RESOURCE, {'success': True}),
    ('delete_webhook', {'webhookId': RESOURCE}, 'DELETE', '/webhooks/' + RESOURCE, {'success': True}),
    ('list_monitorings', {}, 'GET', '/monitorings', {'monitorings_count': 0, 'monitorings': []}),
    ('create_monitoring', {'pull_id': RESOURCE, 'interval': 'P1M'}, 'POST', '/monitorings', {'success': True}),
    ('get_monitoring', {'monitoringId': RESOURCE}, 'GET', '/monitorings/' + RESOURCE, {'monitoring': {'monitoring_id': RESOURCE}}),
    ('update_monitoring', {'monitoringId': RESOURCE, 'interval': 'P2M'}, 'PATCH', '/monitorings/' + RESOURCE, {'success': True}),
    ('delete_monitoring', {'monitoringId': RESOURCE}, 'DELETE', '/monitorings/' + RESOURCE, {'success': True}),
    ('get_monitoring_reconnect_token', {'monitoringId': RESOURCE}, 'GET', '/monitorings/' + RESOURCE + '/reconnectToken', {'reconnect_url': 'https://example.com'}),
    ('refresh_monitoring', {'monitoringId': RESOURCE}, 'POST', '/monitorings/' + RESOURCE + '/refresh', {'pull_id': RESOURCE}),
    ('get_monitoring_events', {'monitoringId': RESOURCE}, 'GET', '/monitorings/' + RESOURCE + '/events', {'events': []}),
    ('list_widgets', {}, 'GET', '/widgets', {'widgets': []}),
    ('create_widget', {'public_alias': 'example', 'company_name': 'Example'}, 'POST', '/widgets', {'widget_id': RESOURCE}),
    ('get_widget', {'widgetId': RESOURCE}, 'GET', '/widgets/' + RESOURCE, {'widget_id': RESOURCE}),
    ('update_widget', {'widgetId': RESOURCE, 'company_name': 'Updated'}, 'PATCH', '/widgets/' + RESOURCE, {'success': True}),
    ('delete_widget', {'widgetId': RESOURCE}, 'DELETE', '/widgets/' + RESOURCE, {'success': True}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,config,method,path,payload', CASES)
async def test_canopy_connect_exact_request(monkeypatch, operation, config, method, path, payload):
    requests = transport(monkeypatch, payload)
    result = await node({'operation': operation, **config}).execute({})
    assert result['data'] == payload
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url).split('?')[0] == native.BASE + '/teams/' + TEAM + path
    assert request.headers['Authorization'] == 'Basic ' + base64.b64encode(b'synthetic-client:synthetic-secret').decode()
    if method in {'POST', 'PATCH'} and operation != 'refresh_monitoring':
        expected = {key: value for key, value in config.items() if key not in {'pullId', 'webhookId', 'widgetId', 'monitoringId'}}
        assert json.loads(request.content) == expected
    else:
        assert not request.content
    if operation == 'list_pulls':
        assert dict(request.url.params) == {'limit': '2', 'offset': '4'}
        assert result['pagination']['single_page'] is True


@pytest.mark.asyncio
async def test_canopy_connect_cursor_and_null_clear(monkeypatch):
    requests = transport(monkeypatch, {'monitoring': {}})
    await node({'operation': 'get_monitoring', 'monitoringId': RESOURCE,
                'with_pulls': True, 'before': RESOURCE, 'limit': '5'}).execute({})
    assert dict(requests[0].url.params) == {'with_pulls': 'true', 'before': RESOURCE, 'limit': '5'}
    requests = transport(monkeypatch, {'success': True})
    await node({'operation': 'update_widget', 'widgetId': RESOURCE, 'on_success_redirect_url': None}).execute({})
    assert json.loads(requests[0].content) == {'on_success_redirect_url': None}


@pytest.mark.asyncio
@pytest.mark.parametrize('status,payload', [(401, {'error': 'UNAUTHORIZED'}), (403, {'error': 'SUBSCRIPTION_INACTIVE'}),
    (429, {'error': 'RATE_LIMITED'}), (302, {}), (200, {'error': 'NOT_FOUND'}), (200, {'success': False}), (200, []), (200, {})])
async def test_canopy_connect_provider_rejection(monkeypatch, status, payload):
    transport(monkeypatch, payload, status)
    with pytest.raises(ValueError):
        await node({'operation': 'get_team'}).execute({})


@pytest.mark.asyncio
async def test_canopy_connect_ambiguous_write_and_redaction(monkeypatch):
    requests = transport(monkeypatch, httpx.ReadTimeout(CREDENTIAL['client_secret']))
    with pytest.raises(ValueError, match='write outcome is unknown') as error:
        await node({'operation': 'update_pull', 'pullId': RESOURCE, 'is_archived': True}).execute({})
    assert len(requests) == 1 and CREDENTIAL['client_secret'] not in str(error.value)
    transport(monkeypatch, {**PROFILE, 'debug': CREDENTIAL['client_secret']})
    assert CREDENTIAL['client_secret'] not in str(await node({'operation': 'get_team'}).execute({}))


def test_canopy_connect_manual_credentials_and_validation():
    from nodes.core.credential_connect import typed_fields, shape_credential
    assert {field['name'] for field in typed_fields('canopy_connect_api_key')} == {'canopy_team_id', 'client_id', 'client_secret'}
    shaped, errors, _ = shape_credential('canopy_connect_api_key', CREDENTIAL)
    assert errors == {} and json.loads(json.dumps(shaped))['canopy_team_id'] == TEAM
    assert native.CanopyConnectCredential(**{k: v for k, v in CREDENTIAL.items() if k != 'credential_type'}).credential_type == 'canopy_connect_api_key'
    for changes in [{'client_secret': '<token>'}, {'client_id': 'https://example.com'}, {'canopy_team_id': '../pulls'}]:
        with pytest.raises(ValidationError):
            native.CanopyConnectCredential(**{**CREDENTIAL, **changes})
    for config in [
        {'operation': 'get_pull', 'pullId': '../widgets'},
        {'operation': 'update_webhook', 'webhookId': RESOURCE},
        {'operation': 'create_webhook', 'hookUrl': 'https://example.com', 'eventTypes': ['UNKNOWN']},
        {'operation': 'list_monitorings', 'pull_id': RESOURCE, 'account_identifier': 'other'},
        {'operation': 'list_pulls', 'limit': 101},
    ]:
        with pytest.raises(ValueError):
            native.CanopyConnectNode.parse_config({'config': config})
