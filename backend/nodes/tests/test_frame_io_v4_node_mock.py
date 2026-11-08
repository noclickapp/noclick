"""Exercise the real factory against provider-authored V4 request/response examples."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import frame_io_v4_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/frame-io-v4/contract_cases.json').read_text())['cases']
TOKEN = 'frameio-synthetic-access-token'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **creds):
    return NodeFactory.create_node(node_id='frameio-contract-test', node_type=native.NODE_TYPE,
        node_data={'config': config, 'credentials': {'credential_type': 'frame_io_v4_token', 'api_token': TOKEN, **creds}})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['config']['operation'])
async def test_published_contract_examples(monkeypatch, case):
    def reply(request):
        if case['status'] == 204:
            return httpx.Response(204)
        return httpx.Response(case['status'], json=case['response'])
    requests = transport(monkeypatch, reply)
    result = await node(case['config']).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1  # each action maps to exactly one provider operation
    request = requests[0]
    assert request.method == case['method'] and request.url.path == case['path']
    assert dict(request.url.params) == {k: str(v) for k, v in case['params'].items()}
    assert request.url.host == 'api.frame.io' and request.headers['authorization'] == 'Bearer ' + TOKEN
    assert 'x-frameio-legacy-token-auth' not in request.headers
    if case['body'] is not None:
        assert json.loads(request.content) == case['body']
    else:
        assert not request.content
    if case['status'] == 204:
        assert result['deletion_acknowledged'] is True
    else:
        assert result['data'] == case['response']['data']


@pytest.mark.asyncio
async def test_pagination_retains_filters_and_uses_only_opaque_cursor(monkeypatch):
    cursor = 'g3QAAAACZAACaWRtAAAA+J==='
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json={
        'data': [], 'links': {'next': '/v4/accounts?after=g3QAAAACZAACaWRtAAAA%2BJ%3D%3D%3D'}, 'total_count': 5}))
    config = {'operation': 'list_accounts', 'page_size': 10, 'sort': 'display_name_asc'}
    first = await node(config).execute({})
    assert first['has_more'] and not first['complete'] and first['next_after'] == cursor
    await node({**config, 'after': first['next_after']}).execute({})
    assert dict(requests[1].url.params) == {'page_size': '10', 'sort': 'display_name_asc', 'after': cursor}


@pytest.mark.asyncio
@pytest.mark.parametrize('link', ['https://evil.example/v4/accounts?after=secret', '/v4/other?after=wrong', '/v4/accounts', '/v4/accounts?after=old'])
async def test_unusable_continuations_never_claim_completion_or_follow_urls(monkeypatch, link):
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json={'data': [], 'links': {'next': link}}))
    result = await node({'operation': 'list_accounts', 'after': 'old'}).execute({})
    assert not result['complete'] and result['has_more'] and not result['continuation_available']
    assert result['next_after'] is None and len(requests) == 1


@pytest.mark.asyncio
async def test_adobe_ids_are_encoded_and_legacy_header_is_explicit(monkeypatch):
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json={'data': {'id': 'adobe:asset|1'}}))
    await node({'operation': 'get_file', 'account_id': 'adobe:org@AdobeOrg', 'file_id': 'adobe:asset|1'}, legacy_developer_token="true").execute({})
    assert requests[0].url.raw_path == b'/v4/accounts/adobe%3Aorg%40AdobeOrg/files/adobe%3Aasset%7C1'
    assert requests[0].headers['x-frameio-legacy-token-auth'] == 'true'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 429, 500])
async def test_provider_errors_are_not_retried_or_misreported(monkeypatch, status):
    requests = transport(monkeypatch, lambda req: httpx.Response(status, text='Provider says ' + TOKEN))
    with pytest.raises(ValueError) as error:
        await node({'operation': 'get_current_user'}).execute({})
    assert str(status) in str(error.value) and 'Provider says' in str(error.value)
    assert TOKEN not in str(error.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_ambiguous_write_is_not_retried(monkeypatch):
    def fail(request):
        raise httpx.ReadTimeout('timeout ' + TOKEN)
    requests = transport(monkeypatch, fail)
    with pytest.raises(ValueError, match='write outcome is unknown') as error:
        await node({'operation': 'create_folder', 'account_id': 'account', 'folder_id': 'parent', 'name': 'New'}).execute({})
    assert len(requests) == 1 and TOKEN not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{'data': None}, {'error': 'rejected'}, {'data': []}])
async def test_invalid_identity_is_not_connection_evidence(monkeypatch, body):
    transport(monkeypatch, lambda req: httpx.Response(200, json=body))
    with pytest.raises(ValueError):
        await node({'operation': 'get_current_user'}).execute({})


@pytest.mark.asyncio
async def test_token_reflection_redacted_recursively(monkeypatch):
    transport(monkeypatch, lambda req: httpx.Response(200, json={'data': {'name': TOKEN, TOKEN: [TOKEN]}}))
    result = await node({'operation': 'get_current_user'}).execute({})
    assert TOKEN not in str(result)


@pytest.mark.parametrize('cfg', [
    {'operation': 'get_file', 'account_id': 'a', 'file_id': '../escape'},
    {'operation': 'get_file', 'account_id': '..', 'file_id': 'file'},
    {'operation': 'update_folder', 'account_id': 'a', 'folder_id': 'f'},
    {'operation': 'list_accounts', 'page_size': 101},
    {'operation': 'create_comment', 'account_id': 'a', 'file_id': 'f', 'text': ''},
    {'operation': 'delete_file', 'account_id': 'a', 'file_id': 'f', 'arbitrary': 'value'},
])
def test_invalid_configs_fail_before_network(cfg):
    with pytest.raises(ValueError):
        node(cfg)


@pytest.mark.parametrize('token', ['Bearer abc', 'https://frame.io/token', '<token>', 'abc\nheader'])
def test_credential_refuses_headers_urls_and_placeholders(token):
    with pytest.raises(ValidationError):
        native.FrameIoV4TokenCredential(api_token=token)


@pytest.mark.asyncio
async def test_current_documented_file_response(monkeypatch):
    documented = json.loads((Path(__file__).parent / 'fixtures/frame-io-v4/documented_file_response.json').read_text())
    transport(monkeypatch, lambda req: httpx.Response(200, json=documented['body']))
    result = await node({'operation': 'get_file', 'account_id': 'account', 'file_id': 'file'}).execute({})
    assert result['data'] == documented['body']['data']
    assert result['data']['name'] == 'asset.png'


@pytest.mark.asyncio
async def test_sorting_comments_by_owner_supplies_required_include(monkeypatch):
    requests = transport(monkeypatch, lambda req: httpx.Response(200, json={'data': [], 'links': {'next': None}}))
    await node({'operation': 'list_comments', 'account_id': 'a', 'file_id': 'f', 'sort': 'owner_asc'}).execute({})
    assert requests[0].url.params['include'] == 'owner'
    with pytest.raises(ValueError, match='requires include=owner'):
        await node({'operation': 'list_comments', 'account_id': 'a', 'file_id': 'f', 'sort': 'owner_asc', 'include': 'replies'}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_adobe_account_pagination_accepts_provider_decoded_path(monkeypatch):
    transport(monkeypatch, lambda req: httpx.Response(200, json={
        'data': [], 'links': {'next': '/v4/accounts/adobe:org@AdobeOrg/workspaces?after=next-cursor'}}))
    result = await node({'operation': 'list_workspaces', 'account_id': 'adobe:org@AdobeOrg'}).execute({})
    assert result['next_after'] == 'next-cursor'
