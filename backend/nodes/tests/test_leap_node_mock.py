"""Leap request/response regressions using the provider's published examples."""
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from nodes import leap_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/leap/responses.json').read_text())
TOKEN = 'synthetic-leap-test-token'
CREDS = {'credential_type': 'leap_api_token', 'api_token': TOKEN}
CUSTOMER = {'first_name': 'Roger', 'last_name': 'Binny', 'phones': [{'label': 'cell', 'number': '7656565757'}]}
JOB = {'customer_id': 25, 'description': 'Carpentry Job', 'trades': [1]}
CONFIGS = {
    'list_customers': {}, 'get_customer': {'customer_id': 375},
    'create_customer': CUSTOMER, 'update_customer': {**CUSTOMER, 'customer_id': 70},
    'list_jobs': {}, 'get_job': {'job_id': 178},
    'create_job': JOB, 'update_job': {**JOB, 'job_id': 178},
    'get_job_financial_summary': {'job_id': 178},
    'get_job_workflow_history': {'job_id': 178},
    'update_job_stage': {'job_id': 28666, 'stage': 2006909067},
    'list_job_notes': {'job_id': 178},
    'create_job_note': {'job_id': 178, 'note': 'Test Update'},
    'update_job_note': {'note_id': 2, 'note': 'Test Update'},
    'list_contacts': {}, 'list_users': {}, 'list_trades': {}, 'list_workflow_stages': {},
    'create_task': {'title': 'Job Completed', 'users': [22], 'origin': 'Public API'},
}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **changes):
    return NodeFactory.create_node(node_id='leap-test', node_type='automation-leap',
        node_data={'config': {'operation': operation, **CONFIGS[operation], **changes}, 'credentials': CREDS})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(CONFIGS))
async def test_published_response_and_exact_endpoint(monkeypatch, operation):
    fixture = FIXTURES[operation]
    requests = transport(monkeypatch, fixture['body'])
    result = await node(operation).execute({})
    assert result['status'] == 'success'
    assert result['data'] == {k: v for k, v in fixture['body'].items() if k != 'status'}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture['method']
    route = fixture['path']
    for field, placeholder in native.ROUTES[operation][2].items():
        route = route.replace('{' + placeholder + '}', str(CONFIGS[operation][field]))
    assert request.url == httpx.URL(native.BASE_URL + route, params={'page': 1, 'limit': 20} if operation in {'list_customers', 'list_jobs', 'list_contacts', 'list_users', 'list_trades', 'list_workflow_stages'} else {})
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    if operation == 'create_customer':
        data = parse_qs(request.content.decode())
        assert data['phones[0][number]'] == ['7656565757']
        assert data['first_name'] == ['Roger']
    elif operation in {'create_job', 'update_job'}:
        data = parse_qs(request.content.decode())
        assert data['trades[]'] == ['1']
        assert data['customer_id'] == ['25']
        assert 'job_id' not in data
    elif operation in {'create_job_note', 'update_job_stage', 'create_task'}:
        assert request.headers['content-type'].startswith('multipart/form-data; boundary=')
        assert b'name="' in request.content
        if operation == 'create_task':
            assert b'name="users[]"' in request.content


@pytest.mark.asyncio
async def test_page_and_filters_preserve_pagination(monkeypatch):
    fixture = FIXTURES['list_customers']['body']
    requests = transport(monkeypatch, fixture)
    result = await node('list_customers', page=2, limit=10, keyword='roof + repair').execute({})
    assert dict(requests[0].url.params) == {'page': '2', 'limit': '10', 'keyword': 'roof + repair'}
    assert result['data']['meta'] == fixture['meta']


@pytest.mark.asyncio
@pytest.mark.parametrize('status, body', [(401, {'error': {'message': TOKEN}}), (302, {}), (429, {}), (500, {}), (200, {'error': {'message': 'refused'}}), (200, []), (200, None)])
async def test_errors_do_not_claim_success_or_retry(monkeypatch, status, body):
    requests = transport(monkeypatch, body, status)
    with pytest.raises(ValueError) as exc:
        await node('create_job_note').execute({})
    assert TOKEN not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.parametrize('token', ['', 'Bearer token', 'https://example.com/token'])
def test_manual_credential_refuses_invalid_secret(token):
    with pytest.raises(ValidationError):
        native.LeapTokenCredential(api_token=token)


def test_manual_credential_defaults_type_and_strips_secret():
    assert native.LeapTokenCredential(api_token='  valid-token  ').model_dump() == {'credential_type': 'leap_api_token', 'api_token': 'valid-token'}
