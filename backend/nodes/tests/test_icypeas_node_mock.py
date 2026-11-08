"""Provider-published request/response examples, exercised through the real factory."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import icypeas_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/icypeas/contract_examples.json').read_text())
KEY = 'synthetic-icypeas-key'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='icypeas-test', node_type='automation-icypeas',
        node_data={'config': config, 'credentials': {'credential_type': 'icypeas_api_key', 'api_key': KEY, 'email': 'example@icypeas.com'}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(EXAMPLES))
async def test_provider_examples_exact_request_and_response(monkeypatch, operation):
    example = EXAMPLES[operation]
    requests = transport(monkeypatch, example['response'])
    result = await node(example['config']).execute({})
    assert result['status'] == 'success'
    assert result['data'] == example['response']
    assert len(requests) == 1
    request = requests[0]
    assert request.method == example['method'] and request.url.path == example['path']
    assert request.url.host == 'app.icypeas.com'
    assert request.headers['Authorization'] == KEY
    expected = {k: v for k, v in example['config'].items() if k != 'operation'}
    if operation == 'get_subscription': expected = {'email': 'example@icypeas.com'}
    if request.method == 'GET':
        assert dict(request.url.params) == expected and not request.content
    else:
        body = json.loads(request.content)
        assert all(body[k] == v for k, v in expected.items())
        assert set(body) - set(expected) <= {'limit'}


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(200, {'success': False, 'validationErrors': [{'actual': KEY}]}),
    (401, {'message': 'Unauthorized access.'}), (302, {}), (429, {'message': 'Rate limit exceeded'}),
    (200, []), (200, {})])
async def test_failed_or_incomplete_evidence_is_not_success(monkeypatch, status, body):
    requests = transport(monkeypatch, body, status)
    result = await node({'operation': 'get_subscription'}).execute({})
    assert result['status'] == 'error' and KEY not in str(result)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_empty_not_found_and_async_states_preserved(monkeypatch):
    body = {'success': True, 'searchId': 'pending-id', 'status': 'IN_PROGRESS', 'result': None}
    transport(monkeypatch, body)
    result = await node(EXAMPLES['scrape_company']['config']).execute({})
    assert result['data'] == body
    body = {'success': True, 'items': [], 'sorts': []}
    transport(monkeypatch, body)
    assert (await node({'operation': 'read_results'}).execute({}))['data'] == body


@pytest.mark.asyncio
async def test_secret_redacted_recursively(monkeypatch):
    transport(monkeypatch, {'success': True, 'result': {KEY: ['echo ' + KEY]}})
    result = await node(EXAMPLES['create_domain_search']['config']).execute({})
    assert KEY not in str(result)


@pytest.mark.parametrize('config', [
    {'operation': 'create_bulk_search', 'name': 'Test', 'task': 'email-search', 'data': [['one']]},
    {'operation': 'reverse_email_lookups', 'data': ['one@example.com']},
    {'operation': 'create_email_search', 'domainOrCompany': 'icypeas.com'},
    {'operation': 'scrape_company', 'url': 'https://example.com/company/test'},
    {'operation': 'find_urls', 'type': 'company', 'data': [{'firstname': 'A', 'lastname': 'B', 'jobTitle': 'C'}]},
    {'operation': 'read_results', 'limit': 101},
])
def test_invalid_inputs_fail_before_request(config):
    with pytest.raises(ValueError):
        node(config)


def test_manual_credential_defaults_and_secret_validation():
    credential = native.IcypeasAPIKeyCredential(api_key=KEY, email=' example@icypeas.com ')
    assert credential.credential_type == 'icypeas_api_key' and credential.email == 'example@icypeas.com'
    for value in ['https://app.icypeas.com/token', 'Bearer secret', 'YOUR_API_KEY']:
        with pytest.raises(ValidationError):
            native.IcypeasAPIKeyCredential(api_key=value, email='example@icypeas.com')


@pytest.mark.asyncio
@pytest.mark.parametrize("sorts", [[[1678195083294]], [{"creationDate": 1678195083294}]])
async def test_bulk_progress_accepts_documented_and_schema_cursor_shapes(monkeypatch, sorts):
    requests = transport(monkeypatch, {"success": True, "files": [], "total": 0})
    result = await node({"operation": "read_bulk_progress", "next": True, "sorts": sorts}).execute({})
    assert result["status"] == "success"
    assert json.loads(requests[0].content)["sorts"] == sorts


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"success": False, "validationErrors": [{"message": "validation_required"}]}])
async def test_search_needs_an_explicit_success_flag(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node(EXAMPLES["create_domain_search"]["config"]).execute({})
    assert result["status"] == "error"
