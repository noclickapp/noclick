"""Exercise all Memberspot routes through the native operation runner."""
import json
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import quote

import httpx
import pytest
from pydantic import ValidationError

from nodes import memberspot_node as provider
from nodes.core.run_op import run_node_operation
from utils import ssrf

CASES = json.loads((Path(__file__).parent / 'fixtures/memberspot/operations.json').read_text())
AUTH = {'credential_type': 'memberspot_api_key', 'api_key': 'fixture-memberspot-key'}

@pytest.fixture
def ensure_native_db_pool():
    yield

@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))
    async def send(request):
        requests.append(request)
        assert request.url.host == 'api.memberspot.de'
        assert request.headers['X-API-KEY'] == AUTH['api_key']
        assert AUTH['api_key'] not in str(request.url)
        status, body = replies.pop(0)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    native = ssrf.guarded_async_client
    monkeypatch.setattr(provider, 'guarded_async_client', lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return requests, replies

async def run(operation, config=None):
    return await run_node_operation(node_type='automation-memberspot', operation=operation,
        arguments=config or {}, credential_data=AUTH, user_id='00000000-0000-4000-8000-000000000001')

@pytest.mark.parametrize('case', CASES, ids=lambda c: c['operation'])
async def test_memberspot_routes(case, transport):
    requests, replies = transport
    replies.append((case['status'], case['response']))
    result = await run(case['operation'], case['config'])
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    method, route, path_keys, query_keys = provider.ROUTES[case['operation']]
    for key in path_keys:
        route = route.replace('{' + key + '}', quote(str(case['config'][key]), safe=''))
    assert request.method == case['method'] == method
    assert request.url.raw_path.split(b'?')[0].decode() == route
    if method == 'GET':
        for key in query_keys:
            if key in case['config']:
                value = case['config'][key]
                assert request.url.params[key] == (str(value).lower() if isinstance(value, bool) else str(value))
        assert not request.content
    else:
        assert json.loads(request.content) == case['config']
    body = case['response']
    assert result['data'] == (body.get('data', body) if isinstance(body, dict) else body)

async def test_memberspot_pagination_and_flags(transport):
    requests, replies = transport
    body = {'data': [{'uid': 'u1', 'active': False, 'progress': []}], 'nextPage': 'next+/=?'}
    replies.append((200, body))
    result = await run('list_users', {'lastLoadedId': 'previous+/=?', 'active': False, 'pageLength': 100})
    assert result['data'] == body['data']
    assert result['nextPage'] == body['nextPage']
    assert requests[0].url.params['lastLoadedId'] == 'previous+/=?'
    assert requests[0].url.params['active'] == 'false'

@pytest.mark.parametrize('operation,config', [
    ('set_offer_state_by_email', {'email': 'member@example.com', 'offerId': 'offer-1'}),
    ('set_offer_expiration', {'uid': 'u1', 'offerId': 'offer-1', 'expiresAt': None}),
])
async def test_memberspot_omission_semantics(operation, config, transport):
    requests, replies = transport
    replies.append((201 if operation.startswith('set_offer_state') else 200, None))
    await run(operation, config)
    assert json.loads(requests[0].content) == {k: v for k, v in config.items() if v is not None}

async def test_memberspot_missing_user_is_null(transport):
    _, replies = transport
    replies.append((200, None))
    assert (await run('get_user_by_email', {'email': 'nobody@example.com'}))['data'] is None

async def test_memberspot_path_encoding(transport):
    requests, replies = transport
    replies.append((200, {'uid': 'u/a?b#c'}))
    await run('get_user_by_uid', {'uid': 'u/a?b#c'})
    assert requests[0].url.raw_path == b'/v1/users/find-by-uid/u%2Fa%3Fb%23c'

@pytest.mark.parametrize('code', [400, 401, 403, 429, 500])
async def test_memberspot_errors_are_not_success_or_retried(code, transport):
    requests, replies = transport
    replies.append((code, {'message': 'provider rejection'}))
    with pytest.raises(ValueError, match=f'Memberspot HTTP {code}.*provider rejection'):
        await run('list_courses')
    assert len(requests) == 1

@pytest.mark.parametrize('config', [
    {'operation': 'list_users', 'pageLength': 101},
    {'operation': 'grant_offer_by_email', 'email': 'invalid'},
    {'operation': 'get_user_by_uid', 'uid': '..'},
    {'operation': 'get_user_by_uid', 'uid': '\n'},
    {'operation': 'set_course_start_date', 'uid': 'u1', 'courseId': 'c1', 'startDate': '2026-01-15T00:00:00'},
    {'operation': 'list_courses', 'unknown': 'value'},
])
def test_memberspot_invalid_configs(config):
    with pytest.raises(ValidationError):
        provider.MemberspotFullConfig.model_validate({'config': config, 'credentials': AUTH})

def test_memberspot_credential_and_evidence():
    assert provider.MemberspotNode.connection_evidence.operation == 'list_courses'
    assert provider.MemberspotAPIKeyCredential.model_validate({**AUTH, 'api_key': ' fixture-key '}).api_key == 'fixture-key'
    with pytest.raises(ValidationError):
        provider.MemberspotAPIKeyCredential.model_validate({**AUTH, 'credential_type': 'foreign'})

async def test_memberspot_connection_evidence_uses_account_courses(transport):
    from nodes.core.connection_evidence import collect_evidence
    requests, replies = transport
    replies.append((200, {'data': [{'id': 'c1', 'name': 'My onboarding course', 'type': 'regular'}]}))
    evidence = await collect_evidence(node_type='automation-memberspot', credential_data=AUTH,
        user_id='00000000-0000-4000-8000-000000000001')
    assert evidence.reachable is True
    assert evidence.samples[0].label == 'My onboarding course'
    assert requests[0].url.path == '/v1/courses'

@pytest.mark.parametrize('status,body,expected', [
    (401, {'message': 'Unauthorized'}, False),
    (200, {'unexpected': 'shape'}, None),
    (500, {'message': 'Temporary outage'}, None),
])
async def test_memberspot_connection_verdicts(status, body, expected, transport):
    from nodes.core.connection_evidence import collect_evidence
    _, replies = transport
    replies.append((status, body))
    evidence = await collect_evidence(node_type='automation-memberspot', credential_data=AUTH,
        user_id='00000000-0000-4000-8000-000000000001')
    assert evidence.reachable is expected

async def test_memberspot_empty_custom_property_is_sent(transport):
    requests, replies = transport
    replies.append((201, {'uid': 'u1', 'customUserProperties': {'p1': ''}}))
    await run('set_custom_properties_by_uid', {'uid': 'u1', 'properties': [{'id': 'p1', 'value': ''}]})
    assert json.loads(requests[0].content)['properties'][0]['value'] == ''
