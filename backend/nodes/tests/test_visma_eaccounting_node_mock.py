"""Offline factory/HTTP tests: exact routes, bodies, pagination, errors and OAuth."""
import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes.core.credential_connect import shape_credential
from nodes.visma_eaccounting_node import VismaEAccountingNode, VismaEAccountingOAuthCredential
from nodes.visma_eaccounting_operations import VISMA_OPERATIONS
from nodes.oauth.visma_eaccounting_oauth import OAUTH_PROVIDER
from nodes.scopes.visma_eaccounting import VISMA_EACCOUNTING_SCOPES

CASES = json.loads((Path(__file__).parent / 'fixtures/visma-eaccounting/operations.json').read_text())['cases']
AUTH = {'credential_type': 'visma_eaccounting_oauth', 'access_token': 'synthetic-visma-token'}


def node(config, credential=None):
    return NodeFactory.create_node(node_id='visma-test', node_type='automation-visma-eaccounting',
        node_data={'config': config, 'credentials': credential or AUTH})


@pytest.fixture
def transport(monkeypatch):
    calls, replies = [], []
    async def send(client, request, **kwargs):
        calls.append(request)
        status, payload = replies.pop(0)
        return httpx.Response(status, json=payload, request=request)
    monkeypatch.setattr(httpx.AsyncClient, 'send', send)
    return calls, replies


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_visma_eaccounting_operation_boundary(operation, transport):
    case = CASES[operation]
    calls, replies = transport
    replies.append((case['status'], case['response']))
    result = await node(case['config']).execute({})
    assert result['status'] == 'success' and len(calls) == 1
    request = calls[0]
    assert request.method == case['method'] and request.url.path == case['path']
    assert request.url.host == 'eaccountingapi.vismaonline.com'
    assert request.headers['Authorization'] == 'Bearer ' + AUTH['access_token']
    if case['body']:
        assert json.loads(request.content) == case['body']
    if operation.startswith('list_'):
        assert result['items'] == case['response']['Data']
        assert result['next_page'] == 2 and result['has_more'] is True
    elif case['response'] is None:
        assert result['deleted'] is True
    else:
        assert result['data'] == case['response']


@pytest.mark.asyncio
async def test_visma_eaccounting_pagination(transport):
    transport[1].append((200, {'Data': [], 'Meta': {'CurrentPage': 2, 'TotalNumberOfPages': 2}}))
    result = await node({'operation': 'list_articles', 'page': 2, 'page_size': 100}).execute({})
    assert dict(transport[0][0].url.params) == {'$page': '2', '$pagesize': '100', 'showPricesWithTwoDecimals': 'false'}
    assert result['has_more'] is False and result['next_page'] is None


@pytest.mark.asyncio
async def test_visma_eaccounting_null_and_omitted_body(transport):
    case = CASES['update_customer']
    transport[1].append((200, case['response']))
    await node({**case['config'], 'EmailAddress': None}).execute({})
    body = json.loads(transport[0][0].content)
    assert body['EmailAddress'] is None and 'Telephone' not in body


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302, 400, 401, 403, 429, 500])
async def test_visma_eaccounting_errors_redacted_and_never_retried(transport, status):
    transport[1].append((status, {'Message': 'Refused ' + AUTH['access_token']}))
    result = await node(CASES['create_customer']['config']).execute({})
    assert result['status'] == 'error' and result['status_code'] == status
    assert AUTH['access_token'] not in json.dumps(result) and len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'Name': None}, {'ErrorCode': 4006, 'Message': 'No scope'}])
async def test_visma_eaccounting_bad_identity_cannot_prove_connection(transport, body):
    transport[1].append((200, body))
    with pytest.raises(ValueError):
        await node({'operation': 'get_company_settings'}).execute({})


@pytest.mark.parametrize('config', [
    {'operation': 'get_customer', 'customerId': '../companysettings'},
    {'operation': 'list_customers', 'page': 0},
    {'operation': 'list_customers', 'page_size': 1001},
    {'operation': 'create_customer', 'Name': 'Incomplete'},
    {'operation': 'list_customers', 'url': 'https://elsewhere.example'},
])
def test_visma_eaccounting_invalid_config(config):
    with pytest.raises(ValueError):
        node(config)


def test_visma_eaccounting_manual_credential_and_scope_coverage():
    credential = VismaEAccountingOAuthCredential(access_token=AUTH['access_token'])
    assert credential.credential_type == 'visma_eaccounting_oauth'
    _, errors, resolved = shape_credential('visma_eaccounting_oauth', {'access_token': AUTH['access_token']})
    assert not errors and resolved is not None
    assert set(VISMA_OPERATIONS) == set(VISMA_EACCOUNTING_SCOPES.keys_declared)
    assert set(VISMA_EACCOUNTING_SCOPES.declared_scopes()) == {'ea:api', 'offline_access', 'ea:sales', 'ea:purchase'}
    assert OAUTH_PROVIDER.identity_url == 'https://eaccountingapi.vismaonline.com/v2/companysettings'
    assert OAUTH_PROVIDER.rotates_refresh_tokens and OAUTH_PROVIDER.token_auth == 'basic'


@pytest.mark.asyncio
async def test_visma_eaccounting_freshen_uses_shared_refresh(monkeypatch):
    refresh = AsyncMock(return_value={'access_token': 'new'})
    monkeypatch.setattr('nodes.core.oauth_refresh.freshen_oauth_credential', refresh)
    await VismaEAccountingNode.freshen_credential(AUTH, user_id='u', credential_id='c')
    assert refresh.await_args.kwargs['provider'] == 'visma-eaccounting'
    assert refresh.await_args.kwargs['credential_id'] == 'c'


@pytest.mark.asyncio
async def test_visma_eaccounting_execute_adopts_rotation(monkeypatch, transport):
    async def fresh(**kwargs):
        kwargs['credential'].update(access_token='renewed', refresh_token='rotated', expires_at='2099-01-01T00:00:00Z')
        return 'renewed'
    monkeypatch.setattr('nodes.core.oauth_refresh.ensure_fresh_oauth_token', fresh)
    transport[1].append((200, {'Name': 'Connected Company'}))
    instance = node({'operation': 'get_company_settings'})
    await instance.execute({})
    assert transport[0][0].headers['Authorization'] == 'Bearer renewed'
    assert instance.config.credentials.refresh_token == 'rotated'
