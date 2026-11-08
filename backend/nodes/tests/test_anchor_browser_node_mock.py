"""Exercise the actual node factory; all HTTP is intercepted locally."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from nodes import anchor_browser_node as ab
from nodes.core.run_op import run_node_operation
from utils import ssrf

SID = "550e8400-e29b-41d4-a716-446655440000"
KEY = "anchor-unit-test-secret"
AUTH = {"credential_type": "anchor_browser_api_key", "api_key": KEY}
USER = "00000000-0000-4000-8000-000000000001"
FIXTURES = json.loads((Path(__file__).parent / 'fixtures/anchor-browser/operations.json').read_text())


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest.fixture
def transport(monkeypatch):
    requests, replies = [], []
    monkeypatch.setattr(ssrf, "_resolve_host_addresses", AsyncMock(return_value=["93.184.216.34"]))
    async def send(request):
        requests.append(request)
        assert request.url.host == "api.anchorbrowser.io"
        assert request.headers["anchor-api-key"] == KEY
        assert KEY not in str(request.url)
        code, body = replies.pop(0)
        if isinstance(body, Exception):
            raise body
        return httpx.Response(code, content=body) if isinstance(body, bytes) else httpx.Response(code, json=body)
    original = ssrf.guarded_async_client
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(**kwargs, transport=httpx.MockTransport(send))
    monkeypatch.setattr(ab, "guarded_async_client", client)
    return requests, replies


async def run(operation, config=None):
    return await run_node_operation(node_type=ab.AnchorBrowserNode.integration_type, operation=operation,
        arguments=config or {}, credential_data=AUTH.copy(), user_id=USER)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", FIXTURES, ids=lambda c: 'anchor-browser:' + c['operation'])
async def test_anchor_browser_exact_method_route_query_body_and_response(transport, case):
    requests, replies = transport
    replies.append((200, case['response']))
    result = await run(case['operation'], case['config'])
    assert result['status'] == 'success', result
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case['method']
    assert request.url.path == case['path']
    assert dict(request.url.params) == case['query']
    assert (json.loads(request.content) if request.content else None) == case['body']
    assert result['data'] == case['response'].get('data', case['response'])


@pytest.mark.asyncio
async def test_anchor_browser_session_pagination_and_empty_connection_read(transport):
    _, replies = transport
    replies.append((200, {'data': {'sessions': [], 'page': 2, 'total_pages': 3, 'total': 25}}))
    result = await run('list_sessions', {'page': 2})
    assert result['items'] == [] and result['next_page'] == 3
    replies.append((200, {'data': {'sessions': [], 'page': 1, 'total_pages': 0, 'total': 0}}))
    result = await run('list_sessions')
    assert result['status'] == 'success' and result['next_page'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('code,body', [(401, {'error': {'message': 'Invalid API Key'}}), (403, {'message': 'Forbidden'}),
    (429, {'error': {'message': 'Rate limit exceeded'}}), (500, {'message': 'Unavailable'}),
    (302, b''), (200, b'<html>unexpected</html>'), (200, {}), (200, {'success': False, 'message': 'Code failed'}),
    (200, {'error': {'message': 'Action failed'}})])
async def test_anchor_browser_failures_do_not_retry_or_claim_success(transport, code, body):
    requests, replies = transport
    replies.append((code, body))
    result = await run('navigate', {'session_id': SID, 'url': 'https://example.com'})
    assert result['status'] == 'error' and len(requests) == 1
    if code == 401:
        assert result['error'] == 'Invalid API Key'


@pytest.mark.asyncio
async def test_anchor_browser_redacts_provider_echoes_and_retains_task_state(transport):
    _, replies = transport
    replies.append((401, {'error': {'message': 'Rejected ' + KEY}}))
    result = await run('list_sessions')
    assert KEY not in str(result) and '[redacted]' in str(result)
    replies.append((200, {'data': {'status': 'running', 'workflow_id': 'wf-123'}}))
    result = await run('perform_web_task', {'prompt': 'Read the title'})
    assert result['data']['status'] == 'running'
    replies.append((200, {'data': {'status': 'failed', 'error': 'Task failed'}}))
    result = await run('get_web_task_status', {'workflow_id': 'wf-123'})
    assert result['data']['status'] == 'failed'


@pytest.mark.asyncio
async def test_anchor_browser_incomplete_pagination_is_not_connection_evidence(transport):
    _, replies = transport
    replies.append((200, {'data': {'sessions': []}}))
    assert (await run('list_sessions'))['status'] == 'error'


@pytest.mark.parametrize('operation,config', [('navigate', {'session_id': '../bad', 'url': 'https://example.com'}),
    ('get_session', {'session_id': '../bad'}), ('get_profile', {'name': '..'}),
    ('create_profile', {'name': 'saved'}), ('list_sessions', {'limit': 100}),
    ('scroll', {'session_id': SID, 'x': 1, 'y': 1}), ('click', {'session_id': SID, 'x': 1, 'y': 1})])
def test_anchor_browser_invalid_inputs(operation, config):
    with pytest.raises((ValueError, ValidationError)):
        ab.AnchorBrowserNodeConfig.model_validate({'config': {'operation': operation, **config}, 'credentials': AUTH})


def test_anchor_browser_evidence_and_hidden_secret():
    assert ab.AnchorBrowserNode.connection_evidence.operation == 'list_sessions'
    props = ab.AnchorBrowserAPIKeyCredential.model_json_schema()['properties']
    assert props['api_key']['ui:widget'] == 'password'
    assert props['credential_type']['const'] == AUTH['credential_type']
