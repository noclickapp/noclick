"""MOCO request and response regressions use the provider's published v1 examples.

These tests exercise factory discovery, exact request bodies, pagination, account
host restrictions and credential rejection without using a live MOCO account.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import moco_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / "fixtures/moco/contract_examples.json").read_text())
TOKEN = "moco-fixture-secret-token"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="moco-test", node_type="automation-moco", node_data={
        "config": config, "credentials": {"credential_type": "moco_api_key", "subdomain": "example", "api_key": TOKEN}})


def transport(monkeypatch, body, status=200, headers=None):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, json=body, headers=headers)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", EXAMPLES)
async def test_provider_examples_preserve_exact_request_and_response(monkeypatch, operation):
    example = EXAMPLES[operation]
    # Invoice variants are documented separately; the draft example is used here.
    body = example['response']
    calls = transport(monkeypatch, body, example['status'])
    result = await node(example['config']).execute({})
    assert result['status'] == 'success'
    assert len(calls) == 1
    request = calls[0]
    assert request.method == example['method']
    path = example['path']
    for key, value in example['config'].items():
        path = path.replace('{' + key + '}', str(value))
    assert request.url.path == '/api/v1' + path
    assert request.url.host == 'example.mocoapp.com'
    assert request.headers['Authorization'] == 'Token token=' + TOKEN
    assert request.headers['Content-Type'] == 'application/json'
    if example['expected_body'] is not None:
        assert json.loads(request.content) == example['expected_body']
    if operation.startswith('list_'):
        assert result['items'] == body and not result['has_more']
        assert dict(request.url.params) == {'page': '1', 'per_page': '100'}
    elif operation == 'delete_activity':
        assert result['deleted'] is True
    else:
        assert result['item'] == body


@pytest.mark.parametrize('subdomain', ['https://example.mocoapp.com', 'example.mocoapp.com', 'a/b', 'a@b', 'example:443', '-bad', 'a.b', 'a?b'])
def test_credential_refuses_non_account_hosts(subdomain):
    with pytest.raises(ValidationError):
        native.MocoAPIKeyCredential(subdomain=subdomain, api_key=TOKEN)


@pytest.mark.asyncio
async def test_account_company_evidence_and_explicit_pagination(monkeypatch):
    calls = transport(monkeypatch, [{'id': 44, 'name': 'My customer'}], headers={
        'Link': '<https://example.mocoapp.com/api/v1/companies?page=2>; rel="next"'})
    result = await node({'operation': 'list_companies'}).execute({})
    assert result['next_page'] == 2 and result['has_more']
    assert len(calls) == 1
    assert native.MocoNode.connection_evidence.operation == 'list_companies'


@pytest.mark.asyncio
async def test_filters_dates_and_false_flags_reach_api(monkeypatch):
    calls = transport(monkeypatch, [])
    await node({'operation': 'list_activities', 'from_date': '2024-03-01', 'to_date': '2024-03-31', 'billable': False}).execute({})
    assert dict(calls[0].url.params) == {'page': '1', 'per_page': '100', 'from': '2024-03-01', 'to': '2024-03-31', 'billable': 'false'}


@pytest.mark.asyncio
@pytest.mark.parametrize('link', ['https://evil.example/api/v1/companies?page=2', 'https://example.mocoapp.com/api/v1/users?page=2', 'https://example.mocoapp.com/api/v1/companies?page=1'])
async def test_pagination_rejects_changed_host_resource_or_backwards_page(monkeypatch, link):
    calls = transport(monkeypatch, [], headers={'Link': '<' + link + '>; rel="next"'})
    with pytest.raises(ValueError, match='pagination|next page'):
        await node({'operation': 'list_companies'}).execute({})
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_provider_rejection_is_verbatim_and_token_redacted(monkeypatch):
    transport(monkeypatch, {'message': 'Unauthorized ' + TOKEN}, 401)
    result = await node({'operation': 'list_companies'}).execute({})
    assert result['status'] == 'error' and result['status_code'] == 401
    assert 'Unauthorized' in result['error'] and TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('fields', [{'tags_json': '{}'}, {'custom_properties_json': '[]'}, {'tags_json': 'broken'}])
async def test_invalid_json_write_makes_no_request(monkeypatch, fields):
    calls = transport(monkeypatch, {})
    with pytest.raises(ValueError):
        await node({'operation': 'update_company', 'company_id': 1233434, **fields}).execute({})
    assert not calls
