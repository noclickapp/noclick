"""Exercise documented Leexi response examples through the real node factory."""
import json
from pathlib import Path
import httpx
import pytest
from nodes import leexi_node as native
from nodes.core.registry import NodeFactory

RESPONSES = json.loads((Path(__file__).parent / 'fixtures/leexi/responses.json').read_text())
SECRET = 'synthetic-leexi-signature'
UUID = 'befb9860-8661-442a-9496-8743de9e17cd'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id='leexi-test', node_type='automation-leexi', node_data={
        'config': config, 'credentials': {'credential_type': 'leexi_api_key', 'api_key_signature': SECRET}})

def transport(monkeypatch, payload, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=payload)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(native.ROUTES))
async def test_documented_responses_and_exact_routes(monkeypatch, operation):
    method, path, fields = native.ROUTES[operation]
    config = {'operation': operation}
    for field, _, location in fields:
        if location == 'path': config[field] = UUID
    config.update({
        'create_call': {'recording_s3_key': 'leexi/recordings/upload/b969bec6-c572-466b-99cd-37b4bb7d8b4f.mp3',
                        'external_id': '123', 'direction': 'outbound', 'performed_at': '2024-10-18T16:19:22+02:00', 'user_uuid': UUID},
        'request_presigned_url': {'extension': '.mp4'},
        'list_call_notes': {'call_uuid': UUID},
        'update_call_note': {'locale': 'en-US', 'text': 'Updated summary'},
        'create_team': {'name': 'Sales Team'},
        'create_user': {'name': 'John Smith', 'email': 'john.smith@acme.com', 'team_uuid': UUID},
    }.get(operation, {}))
    payload = RESPONSES[operation]
    requests = transport(monkeypatch, payload)
    result = await node(config).execute({})
    assert result['status'] == 'success'
    assert all(result[key] == value for key, value in payload.items())
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert request.url.path == '/v1' + path.replace('{uuid}', UUID)
    assert request.headers['Authorization'] == 'Basic ' + SECRET
    assert SECRET not in json.dumps(result)

@pytest.mark.asyncio
async def test_patch_only_supplied_fields_and_false(monkeypatch):
    requests = transport(monkeypatch, RESPONSES['update_team'])
    await node({'operation': 'update_team', 'uuid': UUID, 'active': False}).execute({})
    assert json.loads(requests[0].content) == {'active': False}

@pytest.mark.asyncio
async def test_filters_pagination_and_raw_provider_envelope(monkeypatch):
    payload = RESPONSES['list_calls']
    requests = transport(monkeypatch, payload)
    result = await node({'operation': 'list_calls', 'page': 3, 'items': 20,
                         'with_simple_transcript': True, 'from_time': '2024-10-18T16:19:22.000Z'}).execute({})
    assert requests[0].url.params['from'] == '2024-10-18T16:19:22.000Z'
    assert requests[0].url.params['page'] == '3'
    assert requests[0].url.params['with_simple_transcript'] == 'true'
    assert result['data'] == payload['data']

@pytest.mark.asyncio
@pytest.mark.parametrize('status', [200, 401, 403, 429, 500])
async def test_error_envelopes_and_redaction(monkeypatch, status):
    transport(monkeypatch, {'success': False, 'message': 'Rejected ' + SECRET}, status)
    result = await node({'operation': 'list_teams'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert result['message'] == 'Rejected [redacted]'

@pytest.mark.parametrize('value', ['../users', '?token=foo', '..'])
def test_path_injection_rejected(value):
    with pytest.raises(ValueError):
        node({'operation': 'get_call', 'uuid': value})

@pytest.mark.parametrize('value', ['Basic abc', 'https://example.com/key'])
def test_bad_credentials_rejected(value):
    with pytest.raises(ValueError):
        native.LeexiCredential(api_key_signature=value)
