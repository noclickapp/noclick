"""Factory execution against Typecast's published response examples; no account needed."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import typecast_node as native
from nodes.core.binary_output import BinaryOutput
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/typecast/responses.json').read_text())
TOKEN = 'synthetic-typecast-key-42'
VOICE = 'tc_60e5426de8b95f1d3000d7b5'
CUSTOM = 'uc_6700000000000000000000bb'
SPEECH = {'voice_id': VOICE, 'text': 'Hello. Thank you for listening.', 'model': 'ssfm-v31'}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='typecast-test', node_type='automation-typecast',
        node_data={'config': config, 'credentials': {'credential_type': 'typecast_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, responder):
    requests = []
    def reply(request):
        requests.append(request)
        return responder(request)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,values,method,path', [
    ('list_voices', {}, 'GET', '/v3/voices'),
    ('get_voice', {'voice_id': VOICE}, 'GET', '/v3/voices/{voice_id}'),
    ('list_custom_voices', {}, 'GET', '/v1/custom-voices'),
    ('get_custom_voice', {'voice_id': CUSTOM}, 'GET', '/v1/custom-voices/{voice_id}'),
    ('delete_custom_voice', {'voice_id': CUSTOM}, 'DELETE', '/v1/custom-voices/{voice_id}'),
    ('recommend_voices', {'query': 'warm female voice for product tutorial', 'count': 5}, 'GET', '/v1/voices/recommendations'),
    ('get_subscription', {}, 'GET', '/v1/users/me/subscription'),
    ('text_to_speech', SPEECH, 'POST', '/v1/text-to-speech'),
    ('stream_speech', SPEECH, 'POST', '/v1/text-to-speech/stream'),
    ('compose_speech', {'segments': [{'type': 'tts', **SPEECH}, {'type': 'pause', 'duration_seconds': 1.5}]}, 'POST', '/v1/text-to-speech/compose'),
])
async def test_typecast_documented_routes_auth_response_examples(monkeypatch, operation, values, method, path):
    def reply(request):
        if method == 'DELETE':
            return httpx.Response(204)
        if method == 'POST':
            return httpx.Response(200, content=b'RIFF-test-audio', headers={'content-type': 'audio/wav'})
        return httpx.Response(200, json=EXAMPLES[method + ' ' + path]['body'])
    requests = transport(monkeypatch, reply)
    result = await node({'operation': operation, **values}).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.host == 'api.typecast.ai'
    assert request.url.path == path.replace('{voice_id}', values.get('voice_id', ''))
    assert request.headers['X-API-KEY'] == TOKEN
    if method == 'POST':
        body = json.loads(request.content)
        assert 'operation' not in body
        assert all(body[key] == value for key, value in values.items())
        assert isinstance(result['audio'], BinaryOutput)
        assert result['audio'].data == b'RIFF-test-audio'
    elif method == 'DELETE':
        assert result == {'deleted': True, 'voice_id': CUSTOM}
    else:
        assert result['data'] == EXAMPLES[method + ' ' + path]['body']
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_typecast_filters_and_zero_audio_settings(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json=[]))
    await node({'operation': 'list_voices', 'model': 'ssfm-v31', 'use_cases': 'Tiktok/Reels', 'voice_type': 'custom'}).execute({})
    assert dict(requests[0].url.params) == {'model': 'ssfm-v31', 'use_cases': 'Tiktok/Reels', 'voice_type': 'custom'}
    requests = transport(monkeypatch, lambda r: httpx.Response(200, content=b'audio', headers={'content-type': 'audio/mpeg'}))
    result = await node({'operation': 'text_to_speech', **SPEECH, 'output': {'audio_format': 'mp3', 'volume': 0, 'remove_silence_ms': 0}}).execute({})
    body = json.loads(requests[0].content)
    assert body['output']['volume'] == 0 and body['output']['remove_silence_ms'] == 0
    assert result['audio'].filename == 'typecast.mp3'


@pytest.mark.asyncio
async def test_typecast_rejection_is_visible_and_redacts_key(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(401, json={'detail': 'Invalid API key ' + TOKEN}))
    with pytest.raises(ValueError, match='Invalid API key') as exc:
        await node({'operation': 'get_subscription'}).execute({})
    assert TOKEN not in str(exc.value)


@pytest.mark.parametrize('config', [
    {'operation': 'text_to_speech', **SPEECH, 'output': {'volume': 0, 'target_lufs': -14}},
    {'operation': 'text_to_speech', **SPEECH, 'output': {'remove_silence_ms': True}},
    {'operation': 'text_to_speech', **SPEECH, 'output': {'remove_silence_ms': 0.5}},
    {'operation': 'text_to_speech', **SPEECH, 'model': 'ssfm-v21', 'prompt': {'emotion_type': 'smart'}},
    {'operation': 'stream_speech', **SPEECH, 'output': {'volume': 100}},
    {'operation': 'recommend_voices', 'query': 'warm', 'count': 11},
    {'operation': 'get_voice', 'voice_id': '../subscription'},
    {'operation': 'compose_speech', 'segments': [{'type': 'pause', 'duration_seconds': 1}]},
    {'operation': 'compose_speech', 'segments': [{'type': 'tts', **SPEECH}] + [{'type': 'pause', 'duration_seconds': 10}] * 7},
    {'operation': 'compose_speech', 'segments': [{'type': 'tts', **SPEECH}, {'type': 'tts', **SPEECH, 'output': {'audio_format': 'mp3'}}]},
])
def test_typecast_documented_constraints(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_typecast_manual_key_defaults_and_connection_evidence():
    assert native.TypecastAPIKeyCredential(api_key=TOKEN).credential_type == 'typecast_api_key'
    assert native.TypecastNode.connection_evidence.operation == 'get_subscription'


@pytest.mark.asyncio
@pytest.mark.parametrize('model,prompt', [
    ('ssfm-v31', {'emotion_type': 'smart', 'previous_text': 'I feel happy.', 'next_text': 'What a wonderful day.'}),
    ('ssfm-v31', {'emotion_type': 'preset', 'emotion_preset': 'happy', 'emotion_intensity': 2}),
    ('ssfm-v21', {'emotion_preset': 'happy', 'emotion_intensity': 1}),
])
async def test_typecast_model_specific_prompt_wire_contract(monkeypatch, model, prompt):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, content=b'RIFF-audio', headers={'content-type': 'audio/wav'}))
    await node({'operation': 'text_to_speech', **SPEECH, 'model': model, 'prompt': prompt}).execute({})
    assert json.loads(requests[0].content)['prompt'] == prompt
