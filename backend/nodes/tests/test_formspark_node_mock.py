"""Native Formspark wire tests; all credentials and resources are synthetic."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import formspark_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/formspark/contract.json').read_text())
TOKEN = 'fsk_live_synthetic_formspark_42'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield

def node(config):
    return NodeFactory.create_node(node_id='formspark-fixture', node_type='automation-formspark',
        node_data={'config': config, 'credentials': {'credential_type': 'formspark_api_token', 'api_token': TOKEN}})

def transport(monkeypatch, status=200, body=None):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body) if status != 204 else httpx.Response(204)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests

@pytest.mark.asyncio
@pytest.mark.parametrize('operation', CASES)
async def test_every_operation_one_documented_request(monkeypatch, operation):
    case = CASES[operation]
    requests = transport(monkeypatch, case['http_status'], case['response'])
    result = await node(case['config']).execute({})
    assert result['status'] == 'success' and len(requests) == 1
    request = requests[0]
    path = case['path']
    for key, value in case['config'].items():
        path = path.replace('{' + key + '}', str(value))
    assert request.method == case['method']
    assert request.url.host == 'api.formspark.io' and request.url.path == '/public/v1' + path
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    expected = {k: v for k, v in case['config'].items() if k in native.ROUTES[operation]['body']}
    if native.ROUTES[operation]['body']:
        assert json.loads(request.content) == expected
    if operation.startswith('list_'):
        assert request.url.params['limit'] == '25'
    if case['http_status'] == 204:
        assert result['deleted'] is True
    elif not operation.startswith('list_'):
        assert result['data'] == case['response']

@pytest.mark.asyncio
async def test_opaque_cursor_search_and_workspace_query(monkeypatch):
    requests = transport(monkeypatch, body={'data': [], 'hasMore': True, 'nextCursor': 'opaque+/==next'})
    cfg = {'operation': 'list_workspace_submissions', 'workspaceId': 'ws-fixture', 'limit': 50,
           'startingAfter': 'opaque+/==prior', 'search': 'Ada + café'}
    result = await node(cfg).execute({})
    assert result['nextCursor'] == 'opaque+/==next'
    assert dict(requests[0].url.params) == {'limit': '50', 'startingAfter': cfg['startingAfter'], 'search': cfg['search']}
    requests = transport(monkeypatch, body={'data': [], 'hasMore': False, 'nextCursor': None})
    await node({'operation': 'list_forms', 'workspaceId': 'ws-fixture'}).execute({})
    assert requests[0].url.params['workspaceId'] == 'ws-fixture'

@pytest.mark.asyncio
async def test_partial_updates_preserve_null_false_empty_lists_and_paused_template(monkeypatch):
    requests = transport(monkeypatch, body={'id': 'form-fixture'})
    await node({'operation': 'update_form', 'formId': 'form-fixture', 'description': None,
                'automaticSpamFilter': False, 'notificationEmails': []}).execute({})
    assert json.loads(requests[0].content) == {'description': None, 'automaticSpamFilter': False, 'notificationEmails': []}
    requests = transport(monkeypatch, body={'paused': True})
    result = await node({'operation': 'write_template', 'formId': 'a', 'kind': 'notification', 'subject': None}).execute({})
    assert json.loads(requests[0].content) == {'subject': None} and result['data']['paused'] is True

@pytest.mark.asyncio
async def test_template_preview_data_and_nullable_subject(monkeypatch):
    requests = transport(monkeypatch, body={'html': '<p>Ada</p>', 'text': 'Ada', 'subject': None})
    data = {'firstName': 'Ada', 'email': 'ada@example.com'}
    result = await node({'operation': 'preview_template', 'formId': 'a', 'kind': 'autoresponder', 'data': data}).execute({})
    assert json.loads(requests[0].content) == {'data': data} and result['data']['subject'] is None

@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 409, 429, 500, 503])
async def test_problem_detail_preserved_and_no_retry(monkeypatch, status):
    requests = transport(monkeypatch, status, {'detail': 'Required scope forms:write; ' + TOKEN})
    result = await node({'operation': 'create_workspace', 'name': 'Acme'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status and len(requests) == 1
    assert result['error'] == 'Required scope forms:write; [redacted]'
    assert result['ambiguous'] == (status >= 500)

@pytest.mark.asyncio
@pytest.mark.parametrize('body', [{}, {'data': [], 'hasMore': True, 'nextCursor': None},
    {'data': [], 'hasMore': True, 'nextCursor': 'same'}, {'data': {}, 'hasMore': False, 'nextCursor': None}])
async def test_incomplete_or_stalled_page_refused(monkeypatch, body):
    transport(monkeypatch, body=body)
    with pytest.raises(ValueError):
        await node({'operation': 'list_workspaces', 'startingAfter': 'same'}).execute({})

def test_manual_credentials_and_input_bounds():
    assert native.FormsparkAPITokenCredential(api_token=TOKEN).credential_type == 'formspark_api_token'
    for config in [
        {'operation': 'get_form', 'formId': '../other'}, {'operation': 'get_form', 'formId': '..'},
        {'operation': 'list_forms'}, {'operation': 'list_workspaces', 'limit': 101},
        {'operation': 'list_workspaces', 'limit': True}, {'operation': 'create_workspace', 'name': ''},
        {'operation': 'get_template', 'formId': 'a', 'kind': 'other'},
        {'operation': 'create_form', 'name': 'Contact', 'workspaceId': 'a', 'webhookUrl': 'file:///tmp/x'},
    ]:
        with pytest.raises((ValueError, ValidationError)):
            node(config)
    for token in ['Bearer ' + TOKEN, 'https://example.com/key']:
        with pytest.raises((ValueError, ValidationError)):
            native.FormsparkAPITokenCredential(api_token=token)
    schema = native.FormsparkNode.get_config_schema()
    assert schema['$defs']['FormsparkAPITokenCredential']['properties']['api_token']['ui:widget'] == 'password'
    assert native.FormsparkNode.connection_evidence.operation == 'list_workspaces'
