"""Replay Credly's published examples through the native operation runner.

Independent request expectations check auth, paths, filters and write payloads;
negative cases cover rejected tokens, redirects, malformed responses and retries.
"""
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import credlys_acclaim_platform_node as credly
from nodes.core.run_op import run_node_operation
from utils import ssrf

CASES = json.loads((Path(__file__).parent / 'fixtures/credlys-acclaim-platform/documented.json').read_text())
AUTH = {'credential_type': 'credly_api_token', 'api_token': 'fixture-credly-token'}
NODE = 'automation-credlys-acclaim-platform'


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], []
    monkeypatch.setattr(ssrf, '_resolve_host_addresses', AsyncMock(return_value=['93.184.216.34']))

    async def send(request):
        calls.append(request)
        assert request.url.host == 'api.credly.com'
        assert request.headers['Authorization'] == 'Basic ' + base64.b64encode(b'fixture-credly-token:').decode()
        assert AUTH['api_token'] not in str(request.url)
        status, body = replies.pop(0)
        return httpx.Response(status, content=body) if isinstance(body, bytes) else httpx.Response(status, json=body)

    native = ssrf.guarded_async_client
    monkeypatch.setattr(credly, 'guarded_async_client', lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    return calls, replies


async def run(operation, config=None):
    return await run_node_operation(node_type=NODE, operation=operation, arguments=config or {},
        credential_data=AUTH, user_id='00000000-0000-4000-8000-000000000001')


@pytest.mark.parametrize('case', CASES, ids=lambda c: 'credlys-acclaim-platform-' + c['operation'])
async def test_documented_requests_and_responses(case, transport):
    calls, replies = transport
    replies.append((case['status'], case['response'] if case['response'] is not None else b''))
    result = await run(case['operation'], case['config'])
    assert len(calls) == 1
    request = calls[0]
    assert request.method == case['method']
    assert request.url.path == case['path']
    if request.method in {'POST', 'PUT'}:
        payload = json.loads(request.content)
        assert payload == case['expected']
    else:
        assert dict(request.url.params) == case['expected']
        assert not request.content
    if case['response'] is not None:
        assert result == case['response']
    else:
        assert result == {'acknowledged': True, 'http_status': case['status']}


@pytest.mark.parametrize('status,body,message', [
    (401, {'data': {'message': 'Invalid authorization token'}}, 'Invalid authorization token'),
    (422, {'data': {'message': 'Badge cannot be revoked'}}, 'Badge cannot be revoked'),
    (302, b'', 'HTTP 302'),
    (200, b'<html>not JSON</html>', 'invalid JSON'),
    (200, {'unexpected': True}, 'unexpected response'),
])
async def test_rejections_are_not_success_or_retried(status, body, message, transport):
    calls, replies = transport
    replies.append((status, body))
    with pytest.raises(ValueError, match=message):
        await run('list_organizations')
    assert len(calls) == 1


async def test_write_timeout_is_not_retried(monkeypatch, transport):
    calls = []
    async def fail(request):
        calls.append(request)
        raise httpx.ReadTimeout('timeout')
    native = ssrf.guarded_async_client
    monkeypatch.setattr(credly, 'guarded_async_client', lambda **kw: native(**kw, transport=httpx.MockTransport(fail)))
    with pytest.raises(ValueError, match='inspect writes before retrying'):
        await run('issue_badge', next(c['config'] for c in CASES if c['operation'] == 'issue_badge'))
    assert len(calls) == 1


@pytest.mark.parametrize('token', ['https://example.com/token', 'Basic abc', 'a:b', 'a\r\nb'])
def test_invalid_token_is_rejected(token):
    with pytest.raises(ValidationError):
        credly.CredlyTokenCredential(api_token=token)


def test_manual_credential_type_defaults_and_trims():
    credential = credly.CredlyTokenCredential(api_token=' fixture-credly-token ')
    assert credential.credential_type == 'credly_api_token'
    assert credential.api_token == 'fixture-credly-token'


def test_invalid_resource_id_cannot_change_route():
    with pytest.raises(ValidationError):
        credly.GetOrganization(organization_id='../authorization_tokens')


async def test_replacement_location_is_returned_without_following(monkeypatch, transport):
    calls = []
    location = 'https://api.credly.com/v1/organizations/550e8400-e29b-41d4-a716-446655440000/badges/550e8400-e29b-41d4-a716-446655440000'
    async def send(request):
        calls.append(request)
        return httpx.Response(201, headers={'Location': location})
    native = ssrf.guarded_async_client
    monkeypatch.setattr(credly, 'guarded_async_client', lambda **kw: native(**kw, transport=httpx.MockTransport(send)))
    result = await run('replace_badge', next(c['config'] for c in CASES if c['operation'] == 'replace_badge'))
    assert result == {'acknowledged': True, 'http_status': 201, 'location': location}
    assert len(calls) == 1
