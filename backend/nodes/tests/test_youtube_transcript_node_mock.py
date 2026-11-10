"""Check one-request provider mappings and manual-key behavior without network."""
import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest

from nodes import youtube_transcript_node as module
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/youtube-transcript/requests.json').read_text())['operations']
KEY = 'yt_sk_live_unit_test_secret_98765'


def node(operation, config=None):
    return NodeFactory.create_node(node_id='youtube-transcript-test', node_type='automation-youtube-transcript',
        node_data={'config': {'operation': operation, **(config or {})},
                   'credentials': {'credential_type': 'youtube_transcript_api_key', 'api_key': KEY}})


def transport(monkeypatch, handler):
    @asynccontextmanager
    async def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as instance:
            yield instance
    monkeypatch.setattr(module, 'guarded_async_client', client)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_youtube_transcript_contract_requests(monkeypatch, operation):
    case = CASES[operation]
    calls = []
    payload = {'history': [{'id': 'job-id', 'video_id': 'dQw4w9WgXcQ', 'video_title': 'Account video'}],
               'pagination': {'page': 2, 'total_pages': 3}, 'status': 'processing', 'job_id': 'job-id'}
    def handle(request):
        calls.append(request)
        assert request.method == case['method']
        assert request.url.host == 'www.youtubetranscript.dev'
        assert request.url.path == '/api/v2' + case['path']
        assert request.headers['authorization'] == 'Bearer ' + KEY
        assert dict(request.url.params) == {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in case['query'].items()}
        assert (json.loads(request.content) if request.content else None) == case['body']
        return httpx.Response(case['status'], json=payload)
    transport(monkeypatch, handle)
    result = await node(operation, case['config']).execute({})
    assert len(calls) == 1
    assert result['status'] == 'success'
    assert result['data'] == payload
    assert result['http_status'] == case['status']
    if operation == 'list_transcripts':
        assert result['items'] == payload['history']


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302, 400, 401, 402, 403, 404, 429, 500])
async def test_youtube_transcript_errors_do_not_retry_and_redact(monkeypatch, status):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json={'error': 'rejected', 'message': 'Rejected ' + KEY})
    transport(monkeypatch, handle)
    result = await node('get_credits').execute({})
    assert len(calls) == 1
    assert result['status'] == 'error'
    assert result['error']['message'] == 'Rejected [redacted]'
    assert KEY not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [{'error': 'invalid_key'}, {'status': 'failed', 'message': 'Transcription failed'}])
async def test_youtube_transcript_error_envelopes(monkeypatch, payload):
    transport(monkeypatch, lambda request: httpx.Response(200, json=payload))
    result = await node('get_credits').execute({})
    assert result['status'] == 'error'
    assert result['error'] == payload


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [{}, {'history': 'wrong shape'}, []])
async def test_youtube_transcript_connection_proof_rejects_bad_shapes(monkeypatch, payload):
    transport(monkeypatch, lambda request: httpx.Response(200, json=payload))
    with pytest.raises(ValueError):
        await node('list_transcripts').execute({})


@pytest.mark.asyncio
async def test_youtube_transcript_non_json(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, text='<html>Sign in</html>'))
    with pytest.raises(ValueError, match='non-JSON'):
        await node('get_credits').execute({})


@pytest.mark.asyncio
async def test_youtube_transcript_path_encoded(monkeypatch):
    def handle(request):
        assert request.url.raw_path == b'/api/v2/transcripts/video%2Fpart%3Fx%3D1'
        return httpx.Response(200, json={'video_id': 'video/part?x=1'})
    transport(monkeypatch, handle)
    await node('get_transcript', {'video_id': 'video/part?x=1'}).execute({})


@pytest.mark.parametrize('operation,config', [
    ('transcribe_video', {}),
    ('create_batch', {'video_ids': []}),
    ('create_batch', {'video_ids': ['dQw4w9WgXcQ'], 'mode': 'auto'}),
    ('get_batch', {'batch_id': '../other'}),
    ('create_folder', {'name': 'x' * 81}),
    ('list_transcripts', {'limit': 101}),
    ('translate_transcript', {'video_id': 'dQw4w9WgXcQ'}),
    ('resolve_playlist', {}),
])
def test_youtube_transcript_invalid_requests(operation, config):
    with pytest.raises(ValueError):
        node(operation, config)


def test_youtube_transcript_manual_key_and_default_type():
    cred = module.YoutubeTranscriptAPIKeyCredential(api_key='  ' + KEY + '  ')
    assert cred.api_key == KEY
    assert cred.credential_type == 'youtube_transcript_api_key'
    with pytest.raises(ValueError):
        module.YoutubeTranscriptAPIKeyCredential(api_key='Bearer ' + KEY)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,route', [('transcribe_video', 'POST /transcribe'), ('get_job', 'GET /jobs/{job_id}')])
async def test_youtube_transcript_documented_responses(monkeypatch, operation, route):
    examples = json.loads((Path(__file__).parent / 'fixtures/youtube-transcript/responses.json').read_text())
    body = examples[route]['body']
    transport(monkeypatch, lambda request: httpx.Response(200, json=body))
    result = await node(operation, CASES[operation]['config']).execute({})
    assert result['status'] == 'success'
    assert result['data'] == body


# The provider's published GET /transcripts response is kept verbatim in this
# fixture. Changed ids below simulate subsequent deliveries of that same shape.
HISTORY = json.loads((Path(__file__).parent / 'fixtures/youtube-transcript/responses.json').read_text())['GET /transcripts']['body']


def memory_state(instance, monkeypatch):
    state = {}

    async def update(mutator, *, skip_result):
        replacement, result = mutator(state.copy())
        if replacement is not None:
            state.clear()
            state.update(replacement)
        return result

    monkeypatch.setattr(instance, '_update_node_state', update)
    return state


@pytest.mark.asyncio
async def test_youtube_transcript_poll_baseline_new_item_and_agent(monkeypatch):
    from copy import deepcopy
    payload = deepcopy(HISTORY)
    calls = []

    def handle(request):
        calls.append(request)
        assert request.url.path == '/api/v2/transcripts'
        assert dict(request.url.params) == {
            'page': '1', 'limit': '100', 'status': 'succeeded',
            'language': 'en', 'search': 'Example', 'date_from': '2026-07-06T00:00:00Z'}
        return httpx.Response(200, json=payload)

    transport(monkeypatch, handle)
    instance = node('on_new_transcript', {'language': 'en', 'search': 'Example', 'date_from': '2026-07-06T00:00:00Z'})
    memory_state(instance, monkeypatch)
    baseline = await instance.execute({})
    assert baseline['transcripts'] == []
    assert not instance.should_propagate_output(baseline, {'operation': 'on_new_transcript'})
    assert instance.resolve_agent_event(baseline) is None
    fresh = {**payload['history'][0], 'id': 'next-transcript'}
    payload['history'].append(fresh)
    result = await instance.execute({})
    assert result['transcripts'] == [fresh]
    assert result['new_transcript_count'] == 1
    assert instance.should_propagate_output(result, {'operation': 'on_new_transcript'})
    assert instance.trigger_emitted_event(result)
    text = instance.resolve_agent_event(result)['text']
    for value in ('Example video', 'next-transcript', 'dQw4w9WgXcQ', 'en', '2026-07-06'):
        assert value in text
    assert (await instance.execute({}))['new_transcript_count'] == 0
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_youtube_transcript_poll_pagination_and_scope(monkeypatch):
    from copy import deepcopy
    pages = []

    def handle(request):
        page = int(request.url.params['page'])
        pages.append(page)
        payload = deepcopy(HISTORY)
        payload['history'][0]['id'] = f'transcript-{page}'
        payload['pagination']['hasMore'] = page == 1
        return httpx.Response(200, json=payload)

    transport(monkeypatch, handle)
    instance = node('on_new_transcript')
    state = memory_state(instance, monkeypatch)
    assert (await instance.execute({}))['new_transcript_count'] == 0
    assert set(state['seen_ids']) == {'transcript-1', 'transcript-2'}
    state['seen_ids'] = ['transcript-1']
    assert (await instance.execute({}))['transcripts'][0]['id'] == 'transcript-2'
    instance.config.config.language = 'es'
    assert (await instance.execute({}))['new_transcript_count'] == 0
    assert pages == [1, 2, 1, 2, 1, 2]


@pytest.mark.asyncio
@pytest.mark.parametrize('payload,status', [
    ({'error': 'invalid_api_key'}, 401),
    ({'history': []}, 200),
    ({'history': 'not a list', 'pagination': {'hasMore': False}}, 200),
    ({'history': [{}], 'pagination': {'hasMore': False}}, 200),
])
async def test_youtube_transcript_poll_failure_preserves_baseline(monkeypatch, payload, status):
    transport(monkeypatch, lambda request: httpx.Response(status, json=payload))
    instance = node('on_new_transcript')
    state = memory_state(instance, monkeypatch)
    with pytest.raises(ValueError):
        await instance.execute({})
    assert state == {}


@pytest.mark.asyncio
async def test_youtube_transcript_poll_page_limit_preserves_baseline(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={
        **HISTORY, 'pagination': {**HISTORY['pagination'], 'hasMore': True}}))
    instance = node('on_new_transcript')
    state = memory_state(instance, monkeypatch)
    with pytest.raises(ValueError, match='2,000'):
        await instance.execute({})
    assert state == {}
