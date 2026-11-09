"""Wire-contract regressions replaying Paradym's published response examples."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import paradym_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/paradym/contract_examples.json").read_text())
KEY = "synthetic-paradym-api-key"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="paradym-test", node_type="automation-paradym", node_data={
        "config": config, "credentials": {"credential_type": "paradym_api_key", "api_key": KEY},
    })


def transport(monkeypatch, body, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", EXAMPLES)
async def test_paradym_documented_requests_and_responses(monkeypatch, operation):
    case = EXAMPLES[operation]
    requests = transport(monkeypatch, case['response'], case['status'])
    out = await node(case['config']).execute({})
    expected = case['response'] if operation.startswith('list_') else {'data': case['response']}
    assert out == (expected if case['status'] != 204 else {'success': True})
    assert len(requests) == 1
    req = requests[0]
    assert req.method == case['method']
    assert str(req.url.copy_with(query=None)) == native.BASE_URL + case['path']
    assert req.headers['x-access-token'] == KEY
    assert (json.loads(req.content) if req.content else None) == case['body']
    assert dict(req.url.params) == ({'page[size]': '10'} if operation.startswith('list_') else {})


@pytest.mark.asyncio
async def test_paradym_cursor_and_search_are_encoded_and_next_is_not_followed(monkeypatch):
    response = {'data': [], 'meta': {'next': 'https://other.example/steal'}}
    requests = transport(monkeypatch, response)
    assert await node({'operation': 'list_wallets', 'page_after': 'cursor+id', 'page_size': 25, 'search_name': 'A & B'}).execute({}) == response
    assert len(requests) == 1
    assert dict(requests[0].url.params) == {'page[size]': '25', 'page[after]': 'cursor+id', 'search[name]': 'A & B'}


@pytest.mark.parametrize('field', ['wallet_id', 'credential_template_id'])
@pytest.mark.parametrize('value', ['../other', 'a/b', 'a?b', 'a#b', 'a\nb'])
def test_paradym_rejects_path_injection(field, value):
    config = {**EXAMPLES['get_credential_template']['config'], field: value}
    with pytest.raises(ValueError):
        node(config)


def test_paradym_manual_credential_default_and_cursor_bounds():
    assert native.ParadymAPIKeyCredential(api_key=KEY).credential_type == 'paradym_api_key'
    with pytest.raises(ValidationError):
        native.ListWallets(page_after='one', page_before='two')
    with pytest.raises(ValidationError):
        native.ListWallets(page_size=101)
    for key in ['https://example.com/key', 'bad\nkey', '<token>']:
        with pytest.raises(ValueError):
            native.ParadymAPIKeyCredential(api_key=key)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302, 401, 403, 429, 500])
async def test_paradym_errors_are_not_success_and_keys_are_redacted(monkeypatch, status):
    requests = transport(monkeypatch, {'message': 'Rejected ' + KEY}, status)
    with pytest.raises(ValueError) as exc:
        await node({'operation': 'list_wallets'}).execute({})
    assert str(status) in str(exc.value) and KEY not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_paradym_connection_evidence_empty_wallets_and_bad_envelope(monkeypatch):
    transport(monkeypatch, {'data': [], 'meta': {}})
    assert (await node({'operation': native.ParadymNode.connection_evidence.operation}).execute({}))['data'] == []
    transport(monkeypatch, {'error': 'Invalid key'})
    with pytest.raises(ValueError, match='Invalid key'):
        await node({'operation': 'list_wallets'}).execute({})
    transport(monkeypatch, {'data': {}})
    with pytest.raises(ValueError, match='without data'):
        await node({'operation': 'list_wallets'}).execute({})


@pytest.mark.asyncio
async def test_paradym_failed_session_is_readable_domain_data(monkeypatch):
    session = {"id": "session123", "status": "failed", "error": {"message": "Holder declined"}}
    transport(monkeypatch, session)
    out = await node({"operation": "get_verification_session", "wallet_id": "wallet123", "verification_id": "session123"}).execute({})
    assert out == {"data": session}
    assert "error" not in out and "status" not in out
