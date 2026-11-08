"""Provider-published v1 examples through the real factory, with mocked HTTP only."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import hello_tracks_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/hello-tracks/contract_examples.json').read_text())
KEY = 'synthetic-hello-tracks-key-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, credentials=None):
    return NodeFactory.create_node(node_id='hello-tracks-test', node_type='automation-hello-tracks',
        node_data={'config': config, 'credentials': credentials or {'credential_type': 'hello_tracks_api_key', 'api_key': KEY}})


def transport(monkeypatch, reply, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=reply)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', EXAMPLES)
async def test_hello_tracks_published_examples(operation, monkeypatch):
    example = EXAMPLES[operation]
    assert example['response'] is not None
    requests = transport(monkeypatch, example['response'])
    result = await node(example['config']).execute({})
    assert result == {**example['response']['data'], 'status': 'success'}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == example['method']
    assert request.url.host == 'api.hellotracks.com'
    assert request.url.path == '/v1' + example['path'].replace('{id}', example['config'].get('id', ''))
    assert request.headers['API-Key'] == KEY
    assert KEY not in str(result)
    if example['method'] in {'POST', 'PATCH'} and operation not in {'archive_job', 'restore_job'}:
        assert json.loads(request.content) == example['request_body']
    else:
        assert request.content == b''


@pytest.mark.asyncio
async def test_hello_tracks_job_paging_and_false_filters(monkeypatch):
    response = EXAMPLES['list_jobs']['response']
    requests = transport(monkeypatch, response)
    result = await node({'operation': 'list_jobs', 'limit': 10, 'skip': 20, 'include_archived': False, 'assignee_id': 'a1b2c3'}).execute({})
    assert dict(requests[0].url.params) == {'limit': '10', 'skip': '20', 'includeArchived': 'false', 'assigneeId': 'a1b2c3'}
    assert result['hasMore'] == response['data']['hasMore']
    assert result['totalCount'] == response['data']['totalCount']


@pytest.mark.asyncio
async def test_hello_tracks_repeated_query_ids(monkeypatch):
    requests = transport(monkeypatch, EXAMPLES['list_members']['response'])
    await node({'operation': 'list_members', 'uids': ['a1b2c3', 'd4e5f6'], 'max': 2}).execute({})
    assert requests[0].url.params.get_list('uids') == ['a1b2c3', 'd4e5f6']


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [200, 401, 403, 429, 500])
async def test_hello_tracks_error_envelope_never_succeeds(status, monkeypatch):
    transport(monkeypatch, {'data': None, 'error': {'code': 'invalid_api_key', 'message': 'Key rejected: ' + KEY}}, status=status)
    result = await node({'operation': 'get_who_am_i'}).execute({})
    assert result['status'] == 'error'
    assert result['http_status'] == status
    assert result['error'] == 'Key rejected: [redacted]'


@pytest.mark.asyncio
async def test_hello_tracks_non_success_status(monkeypatch):
    transport(monkeypatch, {'data': {}}, status=503)
    with pytest.raises(httpx.HTTPStatusError):
        await node({'operation': 'get_company'}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [{}, {'data': None}, {'data': []}])
async def test_hello_tracks_malformed_envelope(monkeypatch, response):
    transport(monkeypatch, response)
    with pytest.raises(ValueError, match='invalid data envelope'):
        await node({'operation': 'get_company'}).execute({})


@pytest.mark.parametrize('config', [
    {'operation': 'get_job', 'id': '../jobs'},
    {'operation': 'get_place', 'id': 'https://other.example'},
    {'operation': 'list_jobs', 'assignee_id': 'a1b2c3', 'assignee_username': 'alex@example.com'},
    {'operation': 'create_timesheet_entry', 'member_id': 'a1b2c3'},
    {'operation': 'create_timesheet_entry', 'member_id': 'a1b2c3', 'clock_in': '07:00'},
    {'operation': 'update_timesheet_entry', 'id': 'a_b'},
    {'operation': 'list_timesheets', 'from_': '2026-10-01'},
    {'operation': 'list_timesheets', 'from_': '2026-10-02', 'until': '2026-10-01'},
    {'operation': 'create_place', 'name': 'Site', 'unexpected': 'refused'},
    {'operation': 'optimize_route', 'date': '2026-11-02'},
])
def test_hello_tracks_rejects_invalid_config(config):
    with pytest.raises((ValueError, ValidationError)):
        node(config)


def test_hello_tracks_manual_credential_and_identity_declaration():
    credential = native.HelloTracksAPIKeyCredential(api_key=KEY)
    assert credential.credential_type == 'hello_tracks_api_key'
    assert native.HelloTracksNode.connection_evidence.identity_operation == 'get_who_am_i'
    for invalid in ['https://example.com/key', '<token>', 'API-Key key']:
        with pytest.raises(ValidationError):
            native.HelloTracksAPIKeyCredential(api_key=invalid)
