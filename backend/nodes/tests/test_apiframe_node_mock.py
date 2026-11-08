"""Synthetic transport tests for Apiframe's pinned v2 wire shapes; no live key."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import apiframe_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = 'afk_synthetic_apiframe_test_key'
ID = '00000000-0000-4000-8000-000000000001'
CASES = json.loads((Path(__file__).parent / 'fixtures/apiframe/requests.json').read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='apiframe-test', node_type='automation-apiframe',
        node_data={'config': config, 'credentials': {'credential_type': 'apiframe_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, body=None, status=200, error=None):
    requests = []
    def respond(req):
        requests.append(req)
        if error:
            raise error
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


def response(operation):
    if native.ROUTES[operation][0] == 'POST':
        return {'jobId': ID, 'status': 'QUEUED'}
    return {
        'get_account': {'user': {'id': ID, 'email': 'owner@example.test', 'role': 'OWNER'}, 'team': None, 'apiKey': None},
        'list_models': {'models': []},
        'list_jobs': {'jobs': [], 'nextCursor': 'next-page', 'hasMore': True},
        'get_job': {'id': ID, 'status': 'COMPLETED', 'result': ['https://cdn.example.test/song1.mp3', 'https://cdn.example.test/song2.mp3'], 'error': None},
        'list_loras': {'items': [], 'nextCursor': None},
        'get_lora': {'id': ID, 'status': 'READY', 'error': None},
        'archive_lora': None,
    }[operation]


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['config']['operation'])
async def test_factory_exact_single_request_per_operation(monkeypatch, case):
    operation = case['config']['operation']
    body = response(operation)
    reqs = transport(monkeypatch, body, 204 if operation == 'archive_lora' else 202 if case['method'] == 'POST' else 200)
    result = await node(case['config']).execute({})
    assert result['status'] == 'success'
    assert len(reqs) == 1
    req = reqs[0]
    assert req.method == case['method']
    assert req.url.scheme == 'https' and req.url.host == 'api.apiframe.ai'
    assert req.url.path == case['path']
    assert req.headers['X-API-Key'] == TOKEN
    assert 'authorization' not in req.headers
    if case['method'] == 'POST':
        assert json.loads(req.content) == case['body']
        assert req.headers['Idempotency-Key'] == case['config']['idempotency_key']
        assert result['accepted'] is True and result['data'] == body
        assert 'completed' not in result
    else:
        assert not req.content
        expected = {k: str(v) for k, v in case['config'].items() if k not in {'operation', 'id'}}
        assert dict(req.url.params) == expected
    if operation == 'get_account':
        assert result['email'] == 'owner@example.test'
    if operation == 'get_job':
        assert len(result['data']['result']) == 2
    if operation == 'list_jobs':
        assert result['data']['nextCursor'] == 'next-page'  # Preserve continuation, no hidden paging.
    if operation == 'archive_lora':
        assert result['archived'] and result['archived_id'] == ID


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302, 400, 401, 402, 403, 429, 503])
async def test_provider_rejection_is_not_acceptance_and_never_retried(monkeypatch, status):
    reqs = transport(monkeypatch, {'error': 'Rejected ' + TOKEN}, status)
    result = await node({'operation': 'generate_image', 'prompt': 'A red fox'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert result['error'] == 'Rejected [redacted]' and len(reqs) == 1


@pytest.mark.asyncio
async def test_timeout_does_not_retry_a_billed_submission(monkeypatch):
    reqs = transport(monkeypatch, error=httpx.ReadTimeout('private ' + TOKEN))
    with pytest.raises(ValueError, match='inspect jobs') as exc:
        await node({'operation': 'generate_music', 'prompt': 'Instrumental jazz'}).execute({})
    assert TOKEN not in str(exc.value) and len(reqs) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,config,body', [
    ('get_account', {}, {}),
    ('get_job', {'id': ID}, {'id': 'another-job'}),
    ('get_lora', {'id': ID}, {'id': 'another-lora'}),
    ('list_jobs', {}, {'jobs': {}}),
    ('list_loras', {}, {'items': None}),
    ('list_models', {}, {'models': None}),
    ('generate_image', {'prompt': 'A fox'}, {}),
])
async def test_malformed_envelopes_or_different_ids_cannot_claim_success(monkeypatch, operation, config, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({'operation': operation, **config}).execute({})


def test_credential_default_manual_field_and_evidence():
    credential = native.ApiframeAPIKeyCredential(api_key='  ' + TOKEN + '  ')
    assert credential.credential_type == 'apiframe_api_key' and credential.api_key == TOKEN
    assert NODE_REGISTRY['automation-apiframe'] is native.ApiframeNode
    assert native.ApiframeNode.connection_evidence.identity_operation == 'get_account'
    assert set(native.ApiframeAPIKeyCredential.model_fields) == {'credential_type', 'api_key'}


@pytest.mark.parametrize('config', [
    {'operation': 'get_job', 'id': '../escape'},
    {'operation': 'list_jobs', 'limit': 101},
    {'operation': 'generate_image', 'prompt': ''},
    {'operation': 'generate_image', 'prompt': 'fox', 'model': 'invented-model'},
    {'operation': 'edit_image', 'fluxFillParams': {'image': 'image-url', 'prompt': 'fox', 'mode': 'inpaint'}},
    {'operation': 'edit_image', 'fluxFillParams': {'image': 'image-url', 'prompt': 'fox', 'mode': 'outpaint'}},
])
def test_invalid_requests_fail_before_transport(config):
    with pytest.raises((ValueError, ValidationError)):
        native.ApiframeNode.parse_config({'config': config})
