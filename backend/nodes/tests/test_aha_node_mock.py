"""Aha! native factory and wire-contract regressions; no live account needed."""
import json
from pathlib import Path
import re

import httpx
import pytest
from pydantic import ValidationError

from nodes import aha_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/aha/contract_examples.json').read_text())
TOKEN = 'aha-synthetic-key-123456789'
CREDENTIAL = {'credential_type': 'aha_api_key', 'subdomain': 'company', 'api_key': TOKEN}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credential=None):
    return NodeFactory.create_node(node_id='aha-test', node_type='automation-aha',
        node_data={'config': config, 'credentials': CREDENTIAL if credential is None else credential})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        if callable(response):
            return response(request)
        return httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs['trust_env'] is False
        assert kwargs['follow_redirects'] is False
        assert kwargs['verify'] is True
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


def config_for(operation):
    method, route, _, _ = native.OPERATIONS[operation]
    cfg = {'operation': operation}
    for key in re.findall(r'{(\w+)}', route):
        cfg[key] = {'product_id': 'PRJ1', 'feature_id': 'PRJ1-1', 'release_id': 'PRJ1-R-1',
                    'epic_id': 'PRJ1-E-251', 'idea_id': 'PRJ1-I-251',
                    'requirement_id': 'PRJ1-1-4', 'note_id': 'PRJ1-N-15'}[key]
    if method in {'POST', 'PUT'}:
        cfg.update(name='New name', description='<p>Details</p>')
    if operation == 'create_idea':
        cfg['created_by_email'] = 'no-reply@aha.io'
    return cfg


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(EXAMPLES))
async def test_every_operation_exact_method_path_body_and_official_response(monkeypatch, operation):
    method, route, envelope, many = native.OPERATIONS[operation]
    example = EXAMPLES[operation]
    response = (lambda r: httpx.Response(204)) if method == 'DELETE' else example['response']
    requests = transport(monkeypatch, response)
    cfg = config_for(operation)
    result = await node(cfg).execute({})
    assert result['status'] == 'success', result
    assert len(requests) == 1  # no hidden reads, unbounded paging or write retries
    request = requests[0]
    assert request.method == example['method']
    assert request.url.host == 'company.aha.io'
    expected_path = example['path']
    if '{id}' in expected_path:
        expected_path = expected_path.replace('{id}', cfg[operation.split('_')[-1] + '_id'])
    assert request.url.path == '/api/v1' + expected_path.format(**cfg)
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    assert request.headers['Accept'] == 'application/json'
    if many:
        assert dict(request.url.params) == {'page': '1', 'per_page': '30'}
        assert result[envelope] == example['response'][envelope]
        assert result['next_page'] is None
    elif method != 'DELETE':
        assert result['data'] == example['response'][envelope]
    if method in {'POST', 'PUT'}:
        fields = {'name': cfg['name']}
        fields['description_attributes' if envelope == 'page' else 'description'] = (
            {'body': cfg['description']} if envelope == 'page' else cfg['description'])
        if operation == 'create_idea':
            fields['created_by'] = 'no-reply@aha.io'
        assert json.loads(request.content) == {envelope: fields}
    else:
        assert request.content == b''
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_feature_status_assignee_and_kind_exact_nested_json(monkeypatch):
    requests = transport(monkeypatch, EXAMPLES['create_feature']['response'])
    await node({**config_for('create_feature'), 'workflow_kind': 'new',
                'workflow_status': 'Designed', 'assigned_to_email': 'no-reply@aha.io'}).execute({})
    body = json.loads(requests[0].content)['feature']
    assert body['workflow_status'] == {'name': 'Designed'}
    assert body['assigned_to_user'] == {'email': 'no-reply@aha.io'}
    assert body['workflow_kind'] == 'new'


@pytest.mark.asyncio
async def test_lists_return_one_page_and_continuation_search(monkeypatch):
    payload = {'ideas': [{'id': '123', 'name': 'Idea'}],
               'pagination': {'total_records': 5, 'total_pages': 3, 'current_page': 2}}
    requests = transport(monkeypatch, payload)
    result = await node({'operation': 'list_ideas', 'page': 2, 'per_page': 2, 'q': 'roadmap + café'}).execute({})
    assert len(requests) == 1
    assert dict(requests[0].url.params) == {'page': '2', 'per_page': '2', 'q': 'roadmap + café'}
    assert result['has_more'] is True and result['next_page'] == 3
    payload['pagination'].update(current_page=3)
    result = await node({'operation': 'list_ideas', 'page': 3, 'per_page': 2}).execute({})
    assert result['has_more'] is False and result['next_page'] is None


@pytest.mark.parametrize('value', ['https://evil.test', 'foo.aha.io', '../x', 'a/b', 'a@b', '-tenant', 'a:443', 'a\nother'])
def test_refuse_invalid_tenants(value):
    with pytest.raises(ValidationError):
        native.AhaAPIKeyCredential(**{**CREDENTIAL, 'subdomain': value})


@pytest.mark.parametrize('value', ['https://secret.test', '<token>', 'Bearer secret', 'a\r\nb', 'a b', 'é'])
def test_refuse_bad_keys(value):
    with pytest.raises(ValidationError):
        native.AhaAPIKeyCredential(**{**CREDENTIAL, 'api_key': value})


def test_credential_paste_normalization_and_foreign_type_guard():
    shaped = native.AhaAPIKeyCredential(**{**CREDENTIAL, 'subdomain': ' Company ', 'api_key': ' ' + TOKEN + '\n'})
    assert shaped.subdomain == 'company' and shaped.api_key == TOKEN
    with pytest.raises(ValueError, match='Aha! API key'):
        node({'operation': 'get_me'}, {**CREDENTIAL, 'credential_type': 'other_api_key'})


@pytest.mark.parametrize('identifier', ['../me', 'x/y', 'x?x=y', '//evil', 'a#x', 'a%2fb'])
def test_identifiers_cannot_change_route(identifier):
    with pytest.raises(Exception):
        node({'operation': 'get_feature', 'feature_id': identifier})


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 302, 401, 403, 404, 429, 500])
async def test_provider_errors_redact_secret_and_never_retry(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, json={'error': 'Rejected ' + TOKEN},
        headers={'Location': 'https://evil.test/steal'}))
    result = await node(config_for('create_feature')).execute({})
    assert result['status'] == 'error' and result['status_code'] == status
    assert result['error'] == 'Rejected [redacted]'
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'error': 'denied'}, {'features': {}}, {'features': [1]},
    {'features': [], 'pagination': {}}, {'features': [], 'pagination': {'current_page': True, 'total_pages': 1}}])
async def test_bad_response_envelopes_fail_closed(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node({'operation': 'list_features'}).execute({})
    assert result['status'] == 'error'
    assert 'features' not in result


@pytest.mark.asyncio
async def test_empty_account_and_current_user_connection_reads(monkeypatch):
    transport(monkeypatch, {'products': [], 'pagination': {'current_page': 1, 'total_pages': 0, 'total_records': 0}})
    result = await node({'operation': 'list_products'}).execute({})
    assert result['status'] == 'success' and result['data'] == []
    transport(monkeypatch, EXAMPLES['get_me']['response'])
    result = await node({'operation': 'get_me'}).execute({})
    assert result['data']['name'] == 'Mary Humpty'
    assert native.AhaNode.connection_evidence.identity_operation == 'get_me'


@pytest.mark.asyncio
async def test_non_json_and_network_failure_do_not_claim_success(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(200, text='<html>login</html>'))
    result = await node({'operation': 'get_me'}).execute({})
    assert result['status'] == 'error'
    def timeout(request):
        raise httpx.ReadTimeout('not returned', request=request)
    requests = transport(monkeypatch, timeout)
    result = await node(config_for('create_feature')).execute({})
    assert result['status'] == 'error' and 'before retrying a write' in result['error']
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_pagination_array_from_provider_overview(monkeypatch):
    # https://www.aha.io/api#pagination
    payload = {
        "pagination": [{"total_records": 2, "total_pages": 1, "current_page": 1}],
        "features": [
            {"reference_num": "APP-1", "name": "Add buttons everywhere", "id": "5938362174479841842"},
            {"reference_num": "APP-2", "name": "Second feature", "id": "5938399016717176704"},
        ],
    }
    transport(monkeypatch, payload)
    result = await node({"operation": "list_features"}).execute({})
    assert result['status'] == 'success'
    assert result['pagination'] == payload['pagination'][0]
    assert result['features'] == payload['features']
    assert result['has_more'] is False


def test_all_declared_operations_have_independent_provider_fixtures():
    assert set(native.OPERATIONS) == set(EXAMPLES)
    assert len(EXAMPLES) == 25
