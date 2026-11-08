"""Offline VideoDB contract examples; no live account or credentials are used."""
import json
from contextlib import asynccontextmanager
from pathlib import Path
import httpx
import pytest
from nodes import video_db_node as module
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/video-db/requests.json').read_text())
KEY = 'sk-videodb-test-secret-12345'


def node(operation, config=None):
    return NodeFactory.create_node(node_id='video-db-test', node_type='automation-video-db',
        node_data={'config': {'operation': operation, **(config or {})},
                   'credentials': {'credential_type': 'video_db_api_key', 'api_key': KEY}})


def transport(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as instance:
            yield instance
    monkeypatch.setattr(module, 'guarded_async_client', client)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_video_db_documented_request(monkeypatch, operation):
    case = CASES[operation]
    calls = []
    def handle(request):
        calls.append(request)
        assert request.method == case['method']
        assert request.url.host == 'api.videodb.io'
        path = case['path']
        for field in case['path_fields']:
            path = path.replace('{' + field + '}', case['config'][field])
        assert request.url.path == path
        assert request.headers['x-access-token'] == KEY
        assert set(request.url.params) == set(case['query_fields']) & set(case['config'])
        for field in case['query_fields']:
            if field in case['config']:
                expected = case['config'][field]
                actual = request.url.params[field]
                assert (float(actual) == expected) if isinstance(expected, (int, float)) else (actual == expected)
        payload = {k: v for k, v in case['config'].items() if k not in case['path_fields'] + case['query_fields']}
        if request.method in {'POST', 'PATCH'}:
            assert json.loads(request.content) == payload
        else:
            assert not request.content
        return httpx.Response(200, json={'success': True, 'data': {'user_id': 'u-12345', 'id': 'job-123', 'output_url': 'https://api.videodb.io/async-response/job-123'}, 'status': 'processing'})
    transport(monkeypatch, handle)
    result = await node(operation, case['config']).execute({})
    assert len(calls) == 1 and result['status'] == 'success'
    assert result['data']['data']['id'] == 'job-123'
    assert result['data']['status'] == 'processing'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [202, 204, 301, 401, 403, 404, 429, 500])
async def test_video_db_failure_no_retry_and_redacted_provider_message(monkeypatch, status):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json={'success': False, 'message': 'Rejected ' + KEY}, headers={'Location': 'https://example.test'})
    transport(monkeypatch, handle)
    result = await node('get_account').execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert result['error']['message'] == 'Rejected [redacted]'
    assert KEY not in json.dumps(result) and len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{'success': False, 'message': 'Key rejected'}, {'error': 'Denied'}, {'status': 'failed', 'data': {'id': 'job-123'}}])
async def test_video_db_error_envelopes(monkeypatch, body):
    transport(monkeypatch, lambda r: httpx.Response(200, json=body))
    assert (await node('get_async_result', {'response_id': 'job-123'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'success': True, 'data': []}, {'success': True, 'data': {'user_id': ''}}])
async def test_video_db_account_evidence_needs_identity(monkeypatch, body):
    transport(monkeypatch, lambda r: httpx.Response(200, json=body))
    with pytest.raises(ValueError, match='user ID'):
        await node('get_account').execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize('content', [b'<html>Invalid gateway</html>', b'[]'])
async def test_video_db_invalid_response(monkeypatch, content):
    transport(monkeypatch, lambda r: httpx.Response(200, content=content))
    with pytest.raises(ValueError):
        await node('list_collections').execute({})


@pytest.mark.parametrize('operation,config', [
    ('get_video', {'video_id': '../user'}),
    ('get_video', {'video_id': 'wrong-prefix'}),
    ('get_collection', {'collection_id': '..'}),
    ('get_async_result', {'response_id': 'job/other'}),
    ('list_videos', {'count': 5001}),
    ('get_video_index', {'video_id': 'm-12345'}),
    ('upload_media', {'collection_id': 'default'}),
    ('search_collection', {'collection_id': 'default'}),
    ('create_video_stream', {'video_id': 'm-12345', 'format': 'invalid'}),
])
def test_video_db_invalid_config(operation, config):
    with pytest.raises(ValueError):
        module.VideoDbFullConfig.model_validate({'config': {'operation': operation, **config}})


def test_video_db_credential_shaping():
    credential = module.VideoDbAPIKeyCredential(api_key='  ' + KEY + '  ')
    assert credential.api_key == KEY
    for value in ['https://console.videodb.io', 'Bearer secret key']:
        with pytest.raises(ValueError):
            module.VideoDbAPIKeyCredential(api_key=value)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,config,body', [
    ('upload_media', {'collection_id': 'default', 'url': 'https://example.com/video.mp4'},
     {'success': True, 'data': {'id': 'm-12345', 'name': 'video.mp4', 'collection_id': 'default'}}),
    ('upload_media', {'collection_id': 'default', 'url': 'https://example.com/video.mp4'},
     {'success': True, 'status': 'processing', 'data': {'id': 'job-123', 'output_url': 'https://api.videodb.io/async-response/job-123'}}),
    ('generate_video_transcription', {'video_id': 'm-12345'},
     {'success': True, 'status': 'processing', 'data': {'id': 'job-123', 'output_url': 'https://api.videodb.io/async-response/job-123'}}),
    ('generate_video_transcription', {'video_id': 'm-12345'},
     {'success': True, 'message': 'transcription already exists'}),
])
async def test_video_db_documented_overlapping_success_branches(monkeypatch, operation, config, body):
    # Provider references publish these shapes as oneOf alternatives despite
    # accepting the same object in both branches (neither declares required keys).
    # https://docs.videodb.io/api-reference/upload-media-to-collection.md
    # https://docs.videodb.io/api-reference/generate-video-transcription.md
    transport(monkeypatch, lambda r: httpx.Response(200, json=body))
    result = await node(operation, config).execute({})
    assert result['status'] == 'success' and result['data'] == body


@pytest.mark.asyncio
async def test_video_db_connection_evidence_names_account(monkeypatch):
    from nodes.core import run_op
    from nodes.core.connection_evidence import collect_evidence
    transport(monkeypatch, lambda r: httpx.Response(200, json={'success': True,
        'data': {'user_id': 'u-12345', 'user_name': 'John Doe', 'user_email': 'john@example.com'}}))
    calls = []
    async def run(**kwargs):
        calls.append(kwargs['operation'])
        return await node(kwargs['operation']).execute({})
    monkeypatch.setattr(run_op, 'run_node_operation', run)
    result = await collect_evidence(node_type='automation-video-db', user_id='fixture',
        credential_data={'credential_type': 'video_db_api_key', 'api_key': KEY})
    assert result.reachable is True and result.account_label == 'John Doe'
    assert calls == ['get_account']
