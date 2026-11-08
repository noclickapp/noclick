"""Validate request wiring against provider-contract fixtures and error handling."""
import json
from pathlib import Path
from contextlib import asynccontextmanager
import httpx
import pytest
from nodes.core.registry import NodeFactory
from nodes import supadata_node as module

CASES = json.loads((Path(__file__).parent / 'fixtures/supadata/requests.json').read_text())
KEY = 'supadata-test-secret-12345'


def node(operation, config):
    return NodeFactory.create_node(node_id='supadata-test', node_type='automation-supadata',
        node_data={'config': {'operation': operation, **config},
                   'credentials': {'credential_type': 'supadata_api_key', 'api_key': KEY}})


def transport(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as instance:
            yield instance
    monkeypatch.setattr(module, 'guarded_async_client', client)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_contract_request(monkeypatch, operation):
    case = CASES[operation]
    calls = []
    def handle(request):
        calls.append(request)
        assert request.method == case['method']
        assert request.url.host == 'api.supadata.ai'
        assert request.url.path == '/v1' + case['path'].replace('{jobId}', case['config'].get('jobId', ''))
        assert request.headers['x-api-key'] == KEY
        expected = {k: v for k, v in case['config'].items() if k != 'jobId'}
        if request.method == 'POST':
            assert json.loads(request.content) == expected
        else:
            assert dict(request.url.params) == {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in expected.items()}
        return httpx.Response(202 if operation == 'create_extract' else 200, json={'jobId': 'provider-job', 'nextPageToken': 'provider-page', **({'organizationId': 'org-123'} if operation == 'get_account' else {})})
    transport(monkeypatch, handle)
    result = await node(operation, case['config']).execute({})
    assert len(calls) == 1
    assert result['status'] == 'success'
    assert result['data']['jobId'] == 'provider-job'
    assert result['data']['nextPageToken'] == 'provider-page'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [206, 400, 401, 403, 429, 500])
async def test_errors_preserve_provider_message_and_redact_key(monkeypatch, status):
    transport(monkeypatch, lambda r: httpx.Response(status, json={'error': 'unauthorized', 'message': 'Rejected ' + KEY}))
    result = await node('get_account', {}).execute({})
    assert result['status'] == 'error'
    assert result['http_status'] == status
    assert result['error']['message'] == 'Rejected [redacted]'
    assert KEY not in json.dumps(result)


@pytest.mark.asyncio
async def test_job_id_is_path_encoded(monkeypatch):
    def handle(request):
        assert request.url.raw_path == b'/v1/extract/job%2Fpart%3Fsecret%3D1'
        return httpx.Response(200, json={'status': 'queued'})
    transport(monkeypatch, handle)
    assert (await node('get_extract_job', {'jobId': 'job/part?secret=1'}).execute({}))['status'] == 'success'


@pytest.mark.parametrize('operation,config', [
    ('create_video_batch', {}),
    ('create_transcript_batch', {'videoIds': []}),
    ('create_video_batch', {'videoIds': ['a'], 'channelId': 'b'}),
    ('create_extract', {'url': 'https://youtu.be/dQw4w9WgXcQ'}),
    ('list_youtube_channel_videos', {'id': '@rickastley', 'limit': 5001}),
])
def test_invalid_requests(operation, config):
    with pytest.raises(ValueError):
        module.SupadataFullConfig.model_validate({'config': {'operation': operation, **config}})


@pytest.mark.asyncio
async def test_account_proof_requires_organization(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(200, json={}))
    with pytest.raises(ValueError, match='organization ID'):
        await node('get_account', {}).execute({})
