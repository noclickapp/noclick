"""Wire and failure regressions for the Practice Better v1 integration.

Synthetic fixtures exercise all public operations without an account or network.
They verify exact payloads, pagination, notification controls and token redaction.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import practice_better_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-practice-better-secret"
CREDENTIAL = {"credential_type": native.CREDENTIAL_TYPE, "access_token": TOKEN}
CASES = json.loads((Path(__file__).parent / 'fixtures/practice-better/wire_cases.json').read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def make_node(config):
    node = NodeFactory.create_node(node_id="practice-better-test", node_type=native.PracticeBetterNode.integration_type,
        node_data={"config": config, "credentials": CREDENTIAL})
    node.emit = AsyncMock()
    return node


def transport(monkeypatch, status=200, payload=None, raw=None, exception=None):
    requests = []
    original = httpx.AsyncClient
    def respond(request):
        requests.append(request)
        if exception:
            raise exception
        if raw is not None:
            return httpx.Response(status, content=raw)
        return httpx.Response(status, json=payload if payload is not None else {"id": "result-1"})
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        assert kwargs['timeout'] == 30
        return original(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native.httpx, 'AsyncClient', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,body', CASES, ids=[case[0]['operation'] for case in CASES])
async def test_practice_better_exact_wire(monkeypatch, config, method, path, body):
    payload = {"count": 1, "hasMore": False, "items": [{"id": "result-1", "name": "Consultation"}]} if config['operation'].startswith('list_') else {"id": "result-1"}
    requests = transport(monkeypatch, payload=payload)
    result = await make_node(config).execute({})
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and request.url.path == path
    assert request.url.host == 'api.practicebetter.io' and request.url.scheme == 'https'
    assert request.headers['authorization'] == 'Bearer ' + TOKEN
    assert TOKEN not in str(request.url) and TOKEN not in request.content.decode()
    assert (json.loads(request.content) if request.content else None) == body
    params = dict(request.url.params)
    if config['operation'].startswith('list_'):
        assert params == ({'limit': '20', 'details': 'false'} if config['operation'] == 'list_clients' else {'limit': '20'})
    elif config['operation'] == 'unregister_client':
        assert params == {'recordId': 'client-1'}
    else:
        assert params == {}
    assert result['success'] and result['data'] == payload
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_practice_better_cursor_and_filters(monkeypatch):
    requests = transport(monkeypatch, payload={'items': [], 'hasMore': True, 'count': 30})
    result = await make_node({'operation': 'list_sessions', 'limit': 7, 'before_id': 'last-id', 'group': False,
        'date_gte': '2026-11-10T09:00:00Z'}).execute({})
    assert dict(requests[0].url.params) == {'limit': '7', 'before_id': 'last-id', 'group': 'false', 'date_gte': '2026-11-10T09:00:00Z'}
    assert result['data']['hasMore'] is True


@pytest.mark.asyncio
async def test_practice_better_virtual_booking(monkeypatch):
    requests = transport(monkeypatch)
    await make_node({'operation': 'book_session', 'record_id': 'c1', 'service_id': 's1',
        'session_date': '2026-11-10T09:00:00Z', 'service_type': 'virtual', 'launch_application': 'system',
        'notify': True, 'duration': 900, 'time_zone': 'Pacific Standard Time'}).execute({})
    body = json.loads(requests[0].content)
    assert body['telehealthSettings'] == {'launchApplication': 'system'}
    assert body['notify'] is True and body['duration'] == 900 and body['timeZone'] == 'Pacific Standard Time'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403, 429, 500, 302])
async def test_practice_better_rejection_redacted_and_never_retried(monkeypatch, status):
    requests = transport(monkeypatch, status=status, raw=f'Provider rejected {TOKEN}'.encode())
    result = await make_node({'operation': 'create_tag', 'name': 'Intake'}).execute({})
    assert len(requests) == 1 and result['success'] is False
    assert result['status_code'] == status and result['error'] == 'Provider rejected [redacted]'
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', ['cancel_session', 'delete_session', 'reschedule_session'])
async def test_practice_better_empty_mutation_acknowledgement(monkeypatch, operation):
    requests = transport(monkeypatch, raw=b'')
    config = {'operation': operation, 'session_id': 's1'}
    if operation == 'reschedule_session':
        config['session_date'] = '2026-11-10T09:00:00Z'
    result = await make_node(config).execute({})
    assert len(requests) == 1 and result['data'] is None and result['http_status'] == 200


@pytest.mark.asyncio
async def test_practice_better_async_and_partial_enrollment_not_claimed_verified(monkeypatch):
    transport(monkeypatch, status=202, raw=b'')
    result = await make_node({'operation': 'register_clients', 'course_id': 'p1', 'record_ids': ['c1', 'c2']}).execute({})
    assert result['status'] == 'accepted' and result['enrollment_results_verified'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('raw', [b'not JSON', b'[]', b'{"items":null}'])
async def test_practice_better_invalid_collection(monkeypatch, raw):
    transport(monkeypatch, raw=raw)
    with pytest.raises(ValueError, match='response|collection'):
        await make_node({'operation': 'list_services'}).execute({})


@pytest.mark.asyncio
async def test_practice_better_transport_failure_does_not_retry_or_echo(monkeypatch):
    requests = transport(monkeypatch, exception=httpx.ReadTimeout(TOKEN))
    with pytest.raises(ValueError, match='write may have completed') as exc:
        await make_node({'operation': 'create_tag', 'name': 'Intake'}).execute({})
    assert len(requests) == 1 and TOKEN not in str(exc.value)


@pytest.mark.parametrize('config', [
    {'operation': 'list_clients', 'limit': 101},
    {'operation': 'list_clients', 'before_id': 'a', 'after_id': 'b'},
    {'operation': 'get_client', 'record_id': '../other'},
    {'operation': 'book_session', 'record_id': 'c1', 'service_id': 's1', 'session_date': '2026-11-10T09:00:00Z', 'service_type': 'virtual'},
    {'operation': 'book_session', 'record_id': 'c1', 'service_id': 's1', 'session_date': '2026-11-10T09:00:00'},
    {'operation': 'register_clients', 'course_id': 'p1', 'record_ids': []},
    {'operation': 'create_tag', 'name': 'x', 'url': 'https://elsewhere.example'},
])
def test_practice_better_reject_invalid_config(config):
    with pytest.raises((ValidationError, ValueError)):
        make_node(config)


@pytest.mark.parametrize('value', ['Bearer abc', 'https://example.com', 'token\r\nInjected: yes', ''])
def test_practice_better_token_shaping(value):
    with pytest.raises((ValidationError, ValueError)):
        native.PracticeBetterAccessToken(access_token=value)


def test_practice_better_manual_credential_defaults_and_operation_coverage():
    assert native.PracticeBetterAccessToken(access_token=TOKEN).credential_type == native.CREDENTIAL_TYPE
    assert {case[0]['operation'] for case in CASES} == set(native.OPERATIONS)
    assert len(CASES) == 24


@pytest.mark.asyncio
async def test_practice_better_echo_redaction_before_error_truncation(monkeypatch):
    long_token = 'a' * 3000
    transport(monkeypatch, status=401, raw=long_token.encode())
    node = NodeFactory.create_node(node_id='long-token', node_type='automation-practice-better',
        node_data={'config': {'operation': 'get_profile'},
            'credentials': {'access_token': long_token}})
    node.emit = AsyncMock()
    result = await node.execute({})
    assert result['error'] == '[redacted]'


def test_practice_better_editor_metadata_and_foreign_credential():
    node = make_node({'operation': 'list_services', 'credentialIds': {native.CREDENTIAL_TYPE: 'saved-id'}})
    assert node.config.config.operation == 'list_services'
    raw = {'config': {'operation': 'get_profile'}, 'credentials': {'credential_type': 'other_token', 'access_token': TOKEN}}
    assert native.PracticeBetterNode.validate_config(raw)['valid'] is False
    with pytest.raises(ValueError, match='Practice Better'):
        native.PracticeBetterNode.parse_config(raw)
