"""Offline route, payload, job-state and credential regressions for OpusClip."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import opusclip_node as native
from nodes.core.registry import NodeFactory

TOKEN = 'synthetic-opusclip-api-key'
FIXTURES = json.loads((Path(__file__).parent / 'fixtures/opusclip/operations.json').read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='opusclip-test', node_type='automation-opusclip',
        node_data={'config': config, 'credentials': {'credential_type': 'opusclip_api_key', 'api_key': TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('fixture', FIXTURES, ids=lambda f: f['config']['operation'])
async def test_fixed_contract_operation(monkeypatch, fixture):
    requests = transport(monkeypatch, fixture['response'])
    result = await node(fixture['config']).execute({})
    response = fixture['response']
    assert result['data'] == (response.get('data', response) if isinstance(response, dict) else response)
    assert len(requests) == 1
    request = requests[0]
    assert request.method == fixture['method']
    assert request.url.host == 'api.opus.pro' and request.url.path == fixture['path']
    assert dict(request.url.params) == fixture['query']
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    assert TOKEN not in str(request.url) and TOKEN not in str(result)
    if fixture['body'] is not None:
        assert json.loads(request.content) == fixture['body']
    else:
        assert request.content == b''
    if fixture['config'].get('organization_id'):
        assert request.headers['x-opus-org-id'] == fixture['config']['organization_id']


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_rejection_is_verbatim_redacted_and_never_retried(monkeypatch, status):
    requests = transport(monkeypatch, {'errorMessage': 'Rejected ' + TOKEN}, status)
    with pytest.raises(ValueError) as error:
        await node({'operation': 'create_collection', 'collectionName': 'Clips'}).execute({})
    assert str(status) in str(error.value) and 'Rejected' in str(error.value)
    assert TOKEN not in str(error.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_json_editor_and_object_expression_are_equivalent(monkeypatch):
    requests = transport(monkeypatch, {'jobId': 'example-job'})
    cfg = {'operation': 'create_censor_job', 'projectId': 'P0000000demo', 'clipId': 'lDIOHRzdac'}
    await node({**cfg, 'options': '{"beepSound":false}'}).execute({})
    await node({**cfg, 'options': {'beepSound': False}}).execute({})
    assert requests[0].content == requests[1].content
    assert json.loads(requests[0].content)['options'] == {'beepSound': False}


@pytest.mark.asyncio
async def test_collection_filter_and_project_clip_source(monkeypatch):
    requests = transport(monkeypatch, [])
    await node({'operation': 'list_exportable_clips', 'q': 'findByCollectionId', 'collectionId': 'collection-1'}).execute({})
    assert dict(requests[0].url.params) == {'q': 'findByCollectionId', 'collectionId': 'collection-1'}
    transport(monkeypatch, {'data': {'list': []}})
    await node({'operation': 'list_collections', 'q': 'findByContentId', 'contentId': 'project.clip'}).execute({})


@pytest.mark.parametrize('config', [
    {'operation': 'list_exportable_clips'},
    {'operation': 'list_exportable_clips', 'q': 'findByCollectionId', 'projectId': 'wrong-kind'},
    {'operation': 'list_collections', 'q': 'findByContentId'},
    {'operation': 'publish_post', 'projectId': 'p', 'clipId': 'c', 'postAccountId': 'a', 'postDetail': {}},
    {'operation': 'create_thumbnail_job', 'sourceUri': 'https://example.com/video', 'jobType': 'unknown'},
])
def test_required_and_conditional_fields(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [[], 'bad', {'errorName': 'QuotaExceed', 'errorMessage': 'Insufficient credits'}])
async def test_invalid_object_or_error_envelope(monkeypatch, body):
    transport(monkeypatch, body)
    with pytest.raises(ValueError):
        await node({'operation': 'create_collection', 'collectionName': 'Clips'}).execute({})


def test_credential_has_manual_default_and_no_header_prefix():
    credential = native.OpusClipAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == 'opusclip_api_key'
    for bad in ('Bearer ' + TOKEN, 'https://example.com/key', 'key\r\ninjection'):
        with pytest.raises(ValueError):
            native.OpusClipAPIKeyCredential(api_key=bad)


@pytest.mark.asyncio
async def test_connection_evidence_uses_social_account_names(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    transport(monkeypatch, {'data': [{'postAccountId': 'a', 'platform': 'YOUTUBE',
        'extUserId': 'youtube-account', 'extUserName': 'My channel'}]})
    result = await collect_evidence(node_type='automation-opusclip', user_id='opusclip-test', credential_data={
        'credential_type': 'opusclip_api_key', 'api_key': TOKEN})
    assert result.reachable is True
    assert result.samples[0].label == 'My channel'


@pytest.mark.asyncio
async def test_incomplete_social_account_read_cannot_prove_connection(monkeypatch):
    transport(monkeypatch, {})
    with pytest.raises(ValueError):
        await node({'operation': 'list_social_accounts'}).execute({})
