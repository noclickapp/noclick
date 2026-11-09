"""Offline wire and failure tests. Responses are synthetic contract-shaped fixtures.

Request bodies mirror the official examples; the conformance harness separately
validates requests and provider-authored examples against the pinned contract.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from contextlib import asynccontextmanager

import httpx
import pytest
from pydantic import ValidationError
from nodes.sakari_sms_node import SakariSMSNode, SakariSMSFullConfig, SakariSMSAPICredential

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/sakari-sms/operations.json').read_text())
CREDENTIAL = {'credential_type': 'sakari_sms_api_credentials', 'account_id': 'account-1',
              'client_id': 'sakari-client-id', 'client_secret': 'sakari-client-secret'}


async def run(config, payload=None, code=200, auth=None, transport_error=False):
    requests = []
    def handle(request):
        requests.append(request)
        if request.url.path == '/oauth2/token':
            return httpx.Response(200, json=auth if auth is not None else {'access_token': 'sakari-issued-token', 'token_type': 'Bearer'})
        if transport_error:
            raise httpx.ReadTimeout('timeout', request=request)
        return httpx.Response(code, json=payload)

    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs == {'timeout': 30, 'follow_redirects': False, 'trust_env': False}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as c:
            yield c
    node = SakariSMSNode(node_id='test', node_type='automation-sakari-sms', node_data={},
                         config=SakariSMSFullConfig(config=config, credentials=CREDENTIAL), sio=Mock())
    node.emit = AsyncMock()
    with patch('nodes.sakari_sms_node.guarded_async_client', client):
        result = await node.execute({})
    node.emit.assert_awaited_once_with(result)
    return result, requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', FIXTURES)
async def test_operation_wire_contract(operation):
    fixture = FIXTURES[operation]
    result, requests = await run(fixture['config'], fixture['response'], fixture['status'])
    assert len(requests) == 2
    auth, request = requests
    assert auth.url == 'https://api.sakari.io/oauth2/token'
    assert json.loads(auth.content) == {'grant_type': 'client_credentials',
        'client_id': CREDENTIAL['client_id'], 'client_secret': CREDENTIAL['client_secret']}
    assert 'authorization' not in auth.headers
    assert request.url.host == 'api.sakari.io'
    assert request.method == fixture['method']
    assert request.url.path == '/v1/accounts/account-1' + fixture['path']
    assert dict(request.url.params) == fixture['query']
    assert request.headers['Authorization'] == 'Bearer sakari-issued-token'
    assert (json.loads(request.content) if request.content else None) == fixture['body']
    assert result['status'] == 'success'
    assert result['success'] is True
    if operation == 'send_message':
        assert result['delivery_verified'] is False
    if operation.startswith('list_'):
        assert result['pagination'] == fixture['response']['pagination']


@pytest.mark.asyncio
async def test_provider_rejection_preserves_words_and_removes_secrets():
    payload = {'success': False, 'error': {'code': 'ERR-001', 'message': 'Request declined for sakari-client-secret'}}
    result, _ = await run({'operation': 'list_contacts'}, payload, 403)
    assert result['status'] == 'error'
    assert result['status_code'] == 403
    from nodes.core.connection_evidence import _raise_if_error_envelope, _looks_like_auth_rejection
    with pytest.raises(Exception) as rejected:
        _raise_if_error_envelope(result)
    assert _looks_like_auth_rejection(str(rejected.value))
    assert result['error'] == {'code': 'ERR-001', 'message': 'Request declined for [redacted]'}


@pytest.mark.asyncio
async def test_account_output_omits_credentials_and_billing():
    result, _ = await run({'operation': 'get_account'}, {'success': True, 'data': {
        'id': 'account-1', 'name': 'My Account', 'apiCredentials': {'clientSecret': 'provider-secret'},
        'billing': {'card': 'sensitive'}, 'balance': 10}})
    assert result['data'] == {'id': 'account-1', 'name': 'My Account', 'balance': 10}


@pytest.mark.asyncio
async def test_token_failure_never_sends_resource_request():
    result, requests = await run({'operation': 'list_contacts'}, auth={'error': 'invalid_client'})
    assert result['success'] is False
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_send_timeout_is_uncertain_and_never_retried():
    result, requests = await run({'operation': 'send_message', 'mobile_number': '+1234567890', 'template': 'Hello'}, transport_error=True)
    assert result['status'] == 'unknown'
    assert result['success'] is False
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_malformed_success_is_not_reported_as_success():
    result, _ = await run({'operation': 'list_contacts'}, {'success': True, 'data': {}})
    assert result['success'] is False


@pytest.mark.parametrize('value', ['../other', 'https://example.com/a', 'a/b', 'a?b', 'a%2fb'])
def test_ids_cannot_change_routes(value):
    with pytest.raises(ValidationError):
        SakariSMSFullConfig(config={'operation': 'get_contact', 'contact_id': value}, credentials=CREDENTIAL)


def test_manual_credential_default_and_normalization():
    value = SakariSMSAPICredential(account_id=' account-1 ', client_id='sakari-client-id', client_secret=' sakari-client-secret ')
    assert value.credential_type == 'sakari_sms_api_credentials'
    assert value.account_id == 'account-1'
    assert value.client_secret == 'sakari-client-secret'
    assert SakariSMSNode.connection_evidence.operation == 'list_contacts'
