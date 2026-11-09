"""Vocal Video v2 factory/transport tests; synthetic credentials and results."""
import json
from pathlib import Path

import httpx
import pytest

from nodes import vocal_video_node as vv
from nodes.core.registry import NodeFactory

TOKEN = 'fixture-vocal-video-token'
AUTH = {'credential_type': 'vocal_video_api_key', 'api_key': TOKEN}
CASES = json.loads((Path(__file__).parent / 'fixtures/vocal-video/operations.json').read_text())['operations']


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(operation, **config):
    return NodeFactory.create_node(node_id='vocal-video-fixture', node_type='automation-vocal-video',
        node_data={'config': {'operation': operation, **config}, 'credentials': AUTH})


@pytest.fixture
def transport(monkeypatch):
    requests, responses = [], []
    def respond(request):
        requests.append(request)
        return responses.pop(0)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(vv, 'guarded_async_client', client)
    return requests, responses


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,case', CASES.items(), ids=['vocal-video:' + op for op in CASES])
async def test_each_operation_exactly_one_documented_tool_request(transport, operation, case):
    requests, responses = transport
    payload = {'tool': operation, 'result': {'id': 42}}
    responses.append(httpx.Response(200, json=payload))
    result = await node(operation, **case['config']).execute({})
    assert result == {'status': 'success', 'operation': operation, 'tool': operation, 'data': {'id': 42}}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case['method'] and request.url.path == case['path']
    assert request.url.host == 'vocalvideo.com' and not request.url.query
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    assert json.loads(request.content) == case['config']


@pytest.mark.asyncio
async def test_nullable_update_fields_and_explicit_false_preserved(transport):
    transport[1].append(httpx.Response(200, json={'tool': 'update_collector', 'result': {}}))
    await node('update_collector', collector_id=42, template_id=None, release_id=None, reward=None, show_logo=False, nickname='Customer stories').execute({})
    assert json.loads(transport[0][0].content) == {'collector_id': 42, 'template_id': None, 'release_id': None, 'reward': None, 'show_logo': False, 'nickname': 'Customer stories'}


@pytest.mark.asyncio
async def test_shortlist_pending_and_truncated_write_flags_are_retained(transport):
    for operation, config, data in [
        ('list_collectors', {}, {'collectors': [{'id': 42, 'nickname': 'Customer stories'}], 'returned': 1, 'matched': 20, 'truncated': True}),
        ('list_replies', {}, {'replies': [], 'index_status': 'pending'}),
        ('create_gallery', {'title': 'Stories'}, {'response_truncated': True}),
    ]:
        transport[1].append(httpx.Response(200, json={'tool': operation, 'result': data}))
        result = await node(operation, **config).execute({})
        assert result['data'] == data
    assert len(transport[0]) == 3


@pytest.mark.asyncio
async def test_invitation_preview_and_confirmation_are_separate_calls(transport):
    args = {'collector_id': 42, 'emails': ['fixture@example.test'], 'message': 'Tell us your story'}
    transport[1].append(httpx.Response(200, json={'tool': 'send_collector_invitation', 'result': {'confirmation_token': 'preview-token', 'deliverable': ['fixture@example.test']}}))
    preview = await node('send_collector_invitation', **args, confirm=False).execute({})
    assert preview['data']['confirmation_token'] == 'preview-token'
    assert len(transport[0]) == 1 and json.loads(transport[0][0].content)['confirm'] is False
    with pytest.raises(ValueError):
        node('send_collector_invitation', **args, confirm=True)
    transport[1].append(httpx.Response(200, json={'tool': 'send_collector_invitation', 'result': {'sent': 1}}))
    await node('send_collector_invitation', **args, confirm=True, confirmation_token='preview-token').execute({})
    assert json.loads(transport[0][-1].content)['confirmation_token'] == 'preview-token'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 302, 400, 401, 403, 413, 422, 429, 500])
async def test_refusals_never_succeed_or_retry_and_error_text_redacts_key(transport, status):
    transport[1].append(httpx.Response(status, json={'error': {'code': 'unauthorized', 'message': 'Rejected ' + TOKEN}}, headers={'Location': 'https://example.test'}))
    result = await node('list_collectors').execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert result['error'] == 'Rejected [redacted]' and len(transport[0]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [{}, {'tool': 'get_reply'}, {'tool': 'get_reply', 'result': []}, {'tool': 'get_reply', 'result': {}, 'error': {'message': 'failed'}}])
async def test_invalid_success_envelopes_do_not_pass(transport, payload):
    transport[1].append(httpx.Response(200, json=payload))
    with pytest.raises(ValueError):
        await node('get_reply', id=42).execute({})


@pytest.mark.asyncio
async def test_nonjson_and_oversized_results_refuse_without_retry(transport):
    for response in [httpx.Response(200, text='<html>login</html>'), httpx.Response(200, content=b'x' * 262145, headers={'Content-Type': 'application/json'})]:
        transport[1].append(response)
        with pytest.raises(ValueError):
            await node('create_collector', title='Stories').execute({})
    assert len(transport[0]) == 2


@pytest.mark.parametrize('operation,config', [
    ('get_reply', {}), ('get_reply', {'id': True}), ('list_collectors', {'limit': 51}),
    ('set_collector_status', {'collector_id': 42, 'status': 'deleted'}),
    ('add_storyboard_to_gallery', {'gallery_id': 42}), ('remove_from_gallery', {'gallery_id': 42}),
    ('get_reply', {'id': 42, 'url': 'https://example.test'}), ('unknown_tool', {}),
])
def test_invalid_configs_refused_before_transport(operation, config):
    with pytest.raises(ValueError):
        node(operation, **config)


def test_manual_credential_default_and_read_only_evidence():
    shaped = vv.VocalVideoAPIKeyCredential(api_key='  ' + TOKEN + '  ')
    assert shaped.credential_type == 'vocal_video_api_key' and shaped.api_key == TOKEN
    assert vv.VocalVideoNode.connection_evidence.operation == 'list_collectors'
    assert vv.VocalVideoNode.connection_evidence.proves == 'account'
    for bad in ['Bearer fixture-token', 'https://example.test/key', 'token\nheader']:
        with pytest.raises(ValueError):
            vv.VocalVideoAPIKeyCredential(api_key=bad)


@pytest.mark.asyncio
async def test_workflow_credential_attachment_metadata_is_not_sent(transport):
    transport[1].append(httpx.Response(200, json={'tool': 'list_collectors', 'result': {'collectors': []}}))
    result = await node('list_collectors', credentialIds={'vocal_video_api_key': 'saved-credential-id'}).execute({})
    assert result['status'] == 'success'
    assert json.loads(transport[0][0].content) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize('shadow,body', [(None, {'storyboard_id': 42}), ('None', {'storyboard_id': 42, 'shadow': 'None'})])
async def test_optional_embed_shadow_distinguishes_unset_from_none_style(transport, shadow, body):
    transport[1].append(httpx.Response(200, json={'tool': 'get_storyboard_embed_code', 'result': {}}))
    await node('get_storyboard_embed_code', storyboard_id=42, shadow=shadow).execute({})
    assert json.loads(transport[0][0].content) == body
