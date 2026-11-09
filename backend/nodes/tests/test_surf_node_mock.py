"""Exercise Surf's factory, validation and HTTP boundary without an account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import surf_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/surf/requests.json').read_text())['configs']
TOKEN = 'sk-synthetic-surf-key-42'
JOB = 'a59a252b-2b25-4a72-90d5-6c2f88a6ea10'
PATHS = {
    'get_fear_greed': ('GET', '/market/fear-greed'),
    'get_price_history': ('GET', '/market/price'),
    'list_token_rankings': ('GET', '/market/ranking'),
    'get_credits': ('GET', '/me/credits'), 'get_news': ('GET', '/news/detail'),
    'list_news': ('GET', '/news/feed'), 'get_gas_price': ('GET', '/onchain/gas-price'),
    'create_sql_job': ('POST', '/onchain/sql/jobs'),
    'cancel_sql_job': ('DELETE', '/onchain/sql/jobs/' + JOB),
    'get_sql_job': ('GET', '/onchain/sql/jobs/' + JOB),
    'preflight_sql': ('POST', '/onchain/sql/preflight'),
    'get_defi_metrics': ('GET', '/project/defi/metrics'),
    'get_project': ('GET', '/project/detail'), 'search_projects': ('GET', '/search/project'),
    'search_tokens': ('GET', '/search/token'), 'search_web': ('GET', '/search/web'),
    'list_token_holders': ('GET', '/token/holders'), 'get_wallet': ('GET', '/wallet/detail'),
    'list_wallet_transfers': ('GET', '/wallet/transfers'), 'fetch_web_page': ('GET', '/web/fetch'),
}
LISTS = {'get_fear_greed', 'get_price_history', 'list_token_rankings', 'list_news', 'get_defi_metrics',
    'search_projects', 'search_tokens', 'search_web', 'list_token_holders', 'list_wallet_transfers'}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='surf-test', node_type='automation-surf', node_data={
        'config': config, 'credentials': {'credential_type': 'surf_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', EXAMPLES)
async def test_surf_exact_contract_routes_and_typed_parameters(monkeypatch, operation):
    cfg = EXAMPLES[operation]
    data = [{'symbol': 'BTC'}] if operation in LISTS else {'credit_balance': 12840}
    reply = {'data': data, 'meta': {'credits_used': 0, 'cached': False}}
    requests = transport(monkeypatch, reply)
    result = await node(cfg).execute({})
    evidence = {'items': [{'label': '12840 Surf credits remaining'}]} if operation == 'get_credits' else {}
    assert result == {**reply, **evidence, 'status': 'success', 'operation': operation}
    assert len(requests) == 1
    req = requests[0]
    method, path = PATHS[operation]
    assert req.method == method and req.url.path == '/gateway/v1' + path
    assert req.url.scheme == 'https' and req.url.host == 'api.asksurf.ai'
    assert req.headers['Authorization'] == 'Bearer ' + TOKEN
    expected = node(cfg).config.config.model_dump(mode='json', by_alias=True, exclude_none=True,
        exclude={'operation', 'job_id', 'idempotency_key'})
    if method == 'POST':
        assert json.loads(req.content) == expected and not req.url.query
    else:
        assert dict(req.url.params) == {k: str(v).lower() if isinstance(v, bool) else str(v) for k,v in expected.items()}
        assert not req.content
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_surf_idempotency_and_pending_cancellation(monkeypatch):
    reply = {'data': {'job_id': JOB, 'status': 'queued', 'cancellation_requested': True}, 'meta': {}}
    requests = transport(monkeypatch, reply)
    result = await node({'operation': 'create_sql_job', 'sql': 'SELECT 1', 'idempotency_key': 'stable-job-1'}).execute({})
    assert requests[0].headers['Idempotency-Key'] == 'stable-job-1'
    assert json.loads(requests[0].content) == {'sql': 'SELECT 1', 'max_rows': 1000}
    assert result['data']['status'] == 'queued'
    result = await node({'operation': 'cancel_sql_job', 'job_id': JOB}).execute({})
    assert result['data']['cancellation_requested'] is True and result['data']['status'] == 'queued'


@pytest.mark.asyncio
async def test_surf_pagination_preserves_meta_and_null_empty_page(monkeypatch):
    reply = {'data': None, 'meta': {'has_more': True, 'limit': 20, 'offset': 40, 'total': 100}}
    requests = transport(monkeypatch, reply)
    result = await node({'operation': 'search_projects', 'q': 'bitcoin', 'offset': 40}).execute({})
    assert result['meta'] == reply['meta'] and result['data'] is None
    assert requests[0].url.params['offset'] == '40'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [200, 401, 403, 429, 502])
async def test_surf_error_envelopes_preserve_message_redact_key(monkeypatch, status):
    transport(monkeypatch, lambda request: httpx.Response(status, json={'error': {'code': 'UNAUTHORIZED', 'message': 'Rejected ' + TOKEN}}))
    result = await node({'operation': 'get_credits'}).execute({})
    assert result['status'] == 'error' and result['error'] == 'Rejected [redacted]'
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'data': {}, 'meta': {}}, {'data': {'credit_balance': True}, 'meta': {}}, {'data': [], 'meta': {}}])
async def test_surf_connection_requires_integer_credit_balance(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({'operation': 'get_credits'}).execute({})


@pytest.mark.asyncio
async def test_surf_html_redirect_refused_without_following(monkeypatch):
    requests = transport(monkeypatch, lambda request: httpx.Response(302, headers={'Location': 'https://evil.example'}, text='<html>'))
    with pytest.raises(ValueError, match='JSON'):
        await node({'operation': 'get_credits'}).execute({})
    assert len(requests) == 1


@pytest.mark.parametrize('config', [
    {'operation': 'cancel_sql_job', 'job_id': '../../me/credits'},
    {'operation': 'search_projects', 'q': 'btc', 'limit': 101},
    {'operation': 'list_news', 'limit': 51},
    {'operation': 'search_projects', 'q': 'btc', 'offset': -1},
    {'operation': 'get_gas_price', 'chain': 'eth'},
    {'operation': 'get_price_history', 'symbol': 'BTC', 'from': '2025-01-01'},
    {'operation': 'get_project'}, {'operation': 'get_defi_metrics'},
    {'operation': 'create_sql_job', 'sql': 'SELECT 1', 'max_rows': 10001},
])
def test_surf_invalid_inputs_fail_before_http(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.parametrize('token', ['Bearer sk-example', 'https://agents.asksurf.ai/key', 'bad\nheader'])
def test_surf_manual_default_and_invalid_tokens(token):
    assert native.SurfApiKeyCredential(api_key=TOKEN).credential_type == 'surf_api_key'
    with pytest.raises(ValidationError):
        native.SurfApiKeyCredential(api_key=token)


@pytest.mark.asyncio
async def test_surf_official_documented_workspace_balance(monkeypatch):
    reply = json.loads((Path(__file__).parent / 'fixtures/surf/credits.json').read_text())['body']
    transport(monkeypatch, reply)
    result = await node({'operation': 'get_credits'}).execute({})
    assert result['data']['credit_balance'] == 12840
    assert result['meta']['credits_used'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('balance', [12840, 0])
async def test_surf_real_connect_evidence_shows_account_credit_balance(monkeypatch, balance):
    from nodes.core.connection_evidence import collect_evidence
    requests = transport(monkeypatch, {'data': {'credit_balance': balance}, 'meta': {'credits_used': 0, 'cached': False}})
    result = await collect_evidence(node_type='automation-surf', user_id='surf-test-user',
        credential_data={'credential_type': 'surf_api_key', 'api_key': TOKEN})
    assert result.reachable is True
    assert [sample.label for sample in result.samples] == [f'{balance} Surf credits remaining']
    assert len(requests) == 1 and requests[0].url.path == '/gateway/v1/me/credits'


@pytest.mark.asyncio
async def test_surf_editor_credential_attachment_is_not_a_provider_argument(monkeypatch):
    config = {'operation': 'get_credits', 'credentialIds': {'surf_api_key': JOB}}
    reply = {'data': {'credit_balance': 0}, 'meta': {'credits_used': 0, 'cached': False}}
    requests = transport(monkeypatch, reply)
    result = await node(config).execute({})
    assert result['data']['credit_balance'] == 0
    assert config['credentialIds'] == {'surf_api_key': JOB}
    assert len(requests) == 1 and not requests[0].url.query
