"""Exercise ContentStudio's HTTP requests and published response envelopes.

Fixtures use the provider's v1 examples, with explicit expectations for all 24
operations, credential redaction, pagination and ambiguous write outcomes.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import content_studio_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-content-studio-key"
CASES = json.loads((Path(__file__).parent / "fixtures/content-studio/requests.json").read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="content-studio-test", node_type="automation-content-studio",
        node_data={"config": config, "credentials": {"credential_type": "content_studio_api_key", "api_key": TOKEN}})


def transport(monkeypatch, response):
    requests = []

    def respond(request):
        requests.append(request)
        if isinstance(response, Exception):
            raise response
        return response

    def client(**kwargs):
        assert kwargs == {"timeout": 30, "trust_env": False, "follow_redirects": False}
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=lambda case: case["config"]["operation"])
async def test_content_studio_request_contract(monkeypatch, case):
    requests = transport(monkeypatch, httpx.Response(case['response_status'], json=case['response']))
    result = await node(case['config']).execute({})
    assert result['status'] == 'success'
    assert result['http_status'] == case['response_status']
    assert result['operation'] == case['config']['operation']
    for key, value in case['response'].items():
        if key != 'status':
            assert result[key] == value
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case['method']
    assert str(request.url).startswith('https://api.contentstudio.io/api/v1/')
    assert request.url.path == case['path']
    query = {key: values if len(values := request.url.params.get_list(key)) > 1 else values[0] for key in request.url.params}
    assert query == case.get('query', {})
    assert (json.loads(request.content) if request.content else None) == case.get('body')
    assert request.headers['X-API-Key'] == TOKEN
    assert 'authorization' not in request.headers
    assert TOKEN not in str(request.url)


@pytest.mark.asyncio
async def test_content_studio_empty_page_connection_evidence(monkeypatch):
    payload = {'status': True, 'data': [], 'current_page': 2, 'per_page': 10, 'total': 0, 'last_page': 1, 'from': None, 'to': None}
    transport(monkeypatch, httpx.Response(200, json=payload))
    result = await node({'operation': 'list_workspaces', 'page': 2}).execute({})
    assert result['data'] == [] and result['total'] == 0 and result['current_page'] == 2
    assert native.ContentStudioNode.connection_evidence.operation == 'list_workspaces'
    assert native.ContentStudioNode.connection_evidence.identity_operation == 'get_me'


@pytest.mark.asyncio
@pytest.mark.parametrize('code', [401, 403, 422, 429, 500])
async def test_content_studio_provider_rejection_and_redaction(monkeypatch, code):
    payload = {'status': False, 'message': 'Rejected ' + TOKEN, 'errors': {'text': [TOKEN]}, 'retry_after': 60}
    transport(monkeypatch, httpx.Response(code, json=payload))
    result = await node({'operation': 'get_me'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == code
    assert result['error'] == 'Rejected [redacted]'
    assert result['errors'] == {'text': ['[redacted]']}
    assert result['retry_after'] == 60
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_content_studio_200_error_is_not_success(monkeypatch):
    transport(monkeypatch, httpx.Response(200, json={'status': False, 'message': 'Invalid or revoked API key'}))
    result = await node({'operation': 'get_me'}).execute({})
    assert result['status'] == 'error' and result['error'] == 'Invalid or revoked API key'


@pytest.mark.asyncio
async def test_content_studio_partial_social_deletion_and_warnings(monkeypatch):
    case = next(c for c in CASES if c['config']['operation'] == 'delete_post')
    payload = {'status': True, 'post_id': case['config']['post_id'], 'contentstudio': 'deleted',
        'accounts': {'350830594784444': {'platform': 'facebook', 'name': 'My Business Page', 'status': 'error', 'reason': 'Access token expired.'}}}
    transport(monkeypatch, httpx.Response(207, json=payload))
    result = await node(case['config']).execute({})
    assert result['http_status'] == 207 and result['accounts'] == payload['accounts']
    case = next(c for c in CASES if c['config']['operation'] == 'create_post')
    transport(monkeypatch, httpx.Response(201, json={'status': True, 'data': {'id': 'a1', 'warning': 'Workflow attach failed ' + TOKEN}}))
    assert (await node(case['config']).execute({}))['data']['warning'] == 'Workflow attach failed [redacted]'


@pytest.mark.asyncio
async def test_content_studio_no_automatic_retry_after_write_timeout(monkeypatch):
    requests = transport(monkeypatch, httpx.ReadTimeout('secret ' + TOKEN))
    case = next(c for c in CASES if c['config']['operation'] == 'create_post')
    with pytest.raises(ValueError, match='write outcome is unknown') as caught:
        await node(case['config']).execute({})
    assert TOKEN not in str(caught.value) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [
    httpx.Response(302, headers={'Location': 'https://example.com'}),
    httpx.Response(200, text='<html>Unexpected page</html>'),
    httpx.Response(200, content=b'broken', headers={'content-type': 'application/json'}),
    httpx.Response(200, json=[]), httpx.Response(200, json={}),
    httpx.Response(200, json={'status': True, 'data': []}),
])
async def test_content_studio_refuses_unconfirmed_response(monkeypatch, response):
    requests = transport(monkeypatch, response)
    with pytest.raises(ValueError):
        await node({'operation': 'get_me'}).execute({})
    assert len(requests) == 1


@pytest.mark.parametrize('operation,extra', [
    ('get_post', {'workspace_id': '../other', 'post_id': '123'}),
    ('get_post', {'workspace_id': '123', 'post_id': 'x?key=bad'}),
    ('create_label', {'workspace_id': '123', 'name': 'Urgent', 'color': 'red'}),
    ('update_label', {'workspace_id': '123', 'label_id': '456'}),
    ('create_post', {'workspace_id': '123', 'text': 'Test', 'accounts': []}),
    ('create_post', {'workspace_id': '123', 'text': 'Test', 'accounts': ['456'], 'publish_type': 'scheduled'}),
    ('create_post', {'workspace_id': '123', 'text': 'Test', 'accounts': ['456'], 'scheduled_at': '2026-01-10T15:30:00'}),
    ('create_post', {'workspace_id': '123', 'text': 'Test', 'accounts': ['456'], 'publish_type': 'content_category'}),
    ('list_workspaces', {'per_page': 101}),
    ('list_posts', {'workspace_id': '123', 'date_from': '2026-12-31', 'date_to': '2026-01-01'}),
])
def test_content_studio_config_refuses_invalid_inputs(operation, extra):
    with pytest.raises(ValidationError):
        native.ContentStudioFullConfig.model_validate({'config': {'operation': operation, **extra}})


def test_content_studio_credential_hides_and_normalizes_key():
    credential = native.ContentStudioAPIKeyCredential(api_key='  ' + TOKEN + '  ')
    assert credential.api_key == TOKEN and TOKEN not in repr(credential)
    with pytest.raises(ValidationError) as caught:
        native.ContentStudioAPIKeyCredential(api_key='X-API-Key: private-key')
    assert 'private-key' not in str(caught.value)
