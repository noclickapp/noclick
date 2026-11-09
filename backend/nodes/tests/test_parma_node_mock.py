"""Real factory execution against provider-authored v1 examples; no live account."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import parma_node as native
from nodes.core.registry import NodeFactory

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/parma/contract_examples.json').read_text())
TOKEN = 'synthetic-parma-token-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='parma-test', node_type='automation-parma', node_data={
        'config': config, 'credentials': {'credential_type': 'parma_api_token', 'api_token': TOKEN},
    })


def transport(monkeypatch, reply):
    requests = []
    def handle(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', FIXTURE['operations'])
async def test_documented_operations_send_exact_request_and_parse_whole_example(monkeypatch, operation):
    fixture = FIXTURE['operations'][operation]
    def reply(request):
        assert request.url.host == 'app.parma.ai'
        assert request.method == fixture['method']
        assert request.url.path == fixture['path']
        assert dict(request.url.params) == fixture['params']
        assert request.headers['authorization'] == 'Bearer ' + TOKEN
        if fixture['body'] is not None:
            assert json.loads(request.content) == fixture['body']
        else:
            assert request.content == b''
        return httpx.Response(fixture['status'], json=fixture['response']) if fixture['status'] != 204 else httpx.Response(204)
    requests = transport(monkeypatch, reply)
    result = await node(fixture['config']).execute({})
    assert result['status'] == 'success', result
    assert len(requests) == 1
    if fixture['status'] == 204:
        assert result['deletion_acknowledged'] is True
        assert 'absence_verified' not in result
    else:
        assert result['data'] == fixture['response']['data']
    if 'page' in fixture['config']:
        assert result['pagination_complete'] is False
        assert result['next_page'] == 2


@pytest.mark.asyncio
async def test_empty_page_is_complete_and_page_is_not_automatically_followed(monkeypatch):
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json={'data': [], 'meta': {'count': 2}}))
    result = await node({'operation': 'list_relationships', 'page': 2}).execute({})
    assert result['pagination_complete'] is True and result['next_page'] is None
    assert len(requests) == 1 and requests[0].url.params['page'] == '2'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 302, 400, 401, 403, 404, 422, 429, 500])
async def test_provider_errors_and_redirects_are_not_success_and_token_is_redacted(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, text='Denied ' + TOKEN, headers={'Location': 'https://example.test'}))
    result = await node({'operation': 'list_users'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert TOKEN not in str(result) and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'data': {}}, {'data': [1]}, {'data': [], 'errors': ['bad']}])
async def test_malformed_success_cannot_prove_connection(monkeypatch, body):
    transport(monkeypatch, lambda r: httpx.Response(200, json=body))
    assert (await node({'operation': 'list_users'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_write_timeout_is_unknown_and_never_retried(monkeypatch):
    def reply(request):
        raise httpx.ReadTimeout('timeout', request=request)
    requests = transport(monkeypatch, reply)
    result = await node(FIXTURE['operations']['create_note']['config']).execute({})
    assert result['status'] == 'error' and result['write_outcome'] == 'unknown'
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_write_unexpected_success_shape_is_unknown(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(201, json={'data': []}))
    assert (await node(FIXTURE['operations']['create_note']['config']).execute({}))['write_outcome'] == 'unknown'


@pytest.mark.asyncio
async def test_token_is_redacted_from_response_keys_and_values(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(200, json={'data': [{'name': TOKEN, TOKEN: TOKEN}]}))
    assert TOKEN not in str(await node({'operation': 'list_users'}).execute({}))


@pytest.mark.parametrize('config', [
    {'operation': 'get_relationship', 'relationship_id': '../other'},
    {'operation': 'get_deal', 'deal_id': 0},
    {'operation': 'get_stage', 'stage_id': True},
    {'operation': 'create_relationship', 'name': 'Person'},
    {'operation': 'create_note', 'body': 'Note', 'relationship_ids': []},
    {'operation': 'update_note', 'note_id': 1},
    {'operation': 'update_relationship', 'relationship_id': 1},
    {'operation': 'list_deals', 'page': 0},
    {'operation': 'list_users', 'url': 'https://example.test'},
    {'operation': 'create_note', 'body': 'Note', 'relationship_ids': [1], 'datetime': '2026-11-09'},
])
def test_invalid_input_fails_before_network(config):
    with pytest.raises(ValueError):
        native.ParmaNode.parse_config({'config': config})


def test_manual_connect_credential_has_default_and_only_one_person_supplied_field():
    credential = native.ParmaAPITokenCredential(api_token='  ' + TOKEN + '\n')
    assert credential.credential_type == 'parma_api_token' and credential.api_token == TOKEN
    assert native.ParmaAPITokenCredential.model_json_schema()['required'] == ['api_token']
    for value in ['<token>', 'https://app.parma.ai/api', 'abc\nxyz', '“token”']:
        with pytest.raises(ValidationError):
            native.ParmaAPITokenCredential(api_token=value)


@pytest.mark.asyncio
async def test_async_acceptance_does_not_claim_write_completion(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(202, json={"data": {"id": 1}}))
    result = await node(FIXTURE['operations']['create_note']['config']).execute({})
    assert result['status'] == 'error' and result['write_outcome'] == 'unknown'
