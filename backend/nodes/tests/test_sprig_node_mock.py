"""Wire-level contract tests; HTTP fixtures come from Sprig's published examples."""
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import sprig_node as sprig
from nodes.core.poll_trigger import poll_scope

FIXTURES = Path(__file__).parent / 'fixtures' / 'sprig'
EXAMPLE = json.loads((FIXTURES / 'response.json').read_text())['body']
PAGE_EXAMPLE = json.loads((FIXTURES / 'response-page.json').read_text())['body']
INPUTS = json.loads((FIXTURES / 'inputs.json').read_text())
KEY = 'sprig-fixture-key'
ID = '11111111-1111-4111-8111-111111111111'
AUTH = {'credential_type': 'sprig_api_key', 'api_key': KEY}


@pytest.fixture
def ensure_native_db_pool():
    yield


def node(config):
    data = {'config': config, 'credentials': AUTH}
    return sprig.SprigNode('sprig-test', 'automation-sprig', data, config=sprig.SprigNode.parse_config(data))


def transport(monkeypatch, handler):
    requests = []
    real = httpx.AsyncClient
    def handle(request):
        requests.append(request)
        return handler(request) if callable(handler) else httpx.Response(200, json=handler)
    monkeypatch.setattr(sprig.httpx, 'AsyncClient', lambda **kw: real(transport=httpx.MockTransport(handle), **kw))
    return requests


def config_for(name, op):
    if name in INPUTS: return {'operation': name, **INPUTS[name]['config']}
    if name == 'update_question': return {'operation': name, 'study_id': ID, 'question_id': ID, 'version': 126300, 'title': 'What should we improve?'}
    values = {'study_id': ID, 'question_id': ID, 'version': 126300, 'title': 'What should we improve?',
              'status': 'OPEN', 'count': 500, 'idempotency_key': 'quarterly-feedback-2026-q4', 'user_id': '12347'}
    return {'operation': name, **{f: values[f] for f in op.required}}


@pytest.mark.asyncio
@pytest.mark.parametrize('name', list(sprig.OPERATIONS))
async def test_every_operation_has_one_fixed_request_and_correct_authorization(monkeypatch, name):
    op = sprig.OPERATIONS[name]
    requests = transport(monkeypatch, lambda r: httpx.Response(202 if name == 'upsert_user' else 204, headers={'ETag': '"126301"'}))
    result = await node(config_for(name, op)).execute({})
    assert result['status'] == 'success' and result['etag'] == '"126301"'
    assert len(requests) == 1
    request = requests[0]
    assert request.method == op.method
    assert request.url.host == 'api.sprig.com'
    assert request.url.path == op.path.replace('{study_id}', ID).replace('{question_id}', ID).replace('{user_id}', '12347')
    assert request.headers['Authorization'] == ('Bearer ' if op.path.startswith('/v1/') else 'API-Key ') + KEY
    assert ('if-match' in request.headers) == op.versioned
    if op.versioned: assert request.headers['if-match'] == '"' + str(config_for(name, op)['version']) + '"'
    if name == 'upsert_user':
        assert json.loads(request.content) == {'userId': '12347', 'attributes': {'customer': 'true'}, 'events': [{'event': 'login', 'timestamp': 1626448859836}]}
    if name == 'create_question': assert json.loads(request.content) == {'type': 'OPEN_TEXT', 'title': {'html': 'What should we improve?'}}
    if name == 'create_invitations': assert json.loads(request.content) == {'count': 500, 'idempotencyKey': 'quarterly-feedback-2026-q4'}


@pytest.mark.asyncio
async def test_encoding_filters_and_boolean_wire_values(monkeypatch):
    requests = transport(monkeypatch, {'data': [], 'cursor': None})
    await node({'operation': 'get_user', 'user_id': 'person/+? #'}).execute({})
    assert requests[0].url.raw_path == b'/v2/users/person%2F%2B%3F%20%23'
    await node({'operation': 'list_responses', 'start': 1626448859836, 'with_urls': False, 'with_meta': True}).execute({})
    assert dict(requests[1].url.params) == {'start': '1626448859836', 'with_urls': 'false', 'with_meta': 'true'}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 302, 400, 401, 403, 404, 409, 412, 422, 428, 429, 500])
async def test_api_rejections_and_redirects_are_errors_and_redact_key(monkeypatch, status):
    requests = transport(monkeypatch, lambda r: httpx.Response(status, text='Provider says: ' + KEY, headers={'Location': 'https://other.test'}))
    with pytest.raises(ValueError) as exc: await node({'operation': 'list_studies'}).execute({})
    assert str(status) in str(exc.value) and KEY not in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_poll_baselines_deduplicates_pages_and_emits_agent_context(monkeypatch):
    state = {}
    async def update(self, mutate, **kw):
        nonlocal state
        replacement, result = mutate(deepcopy(state))
        if replacement is not None: state = replacement
        return result
    monkeypatch.setattr(sprig.SprigNode, '_update_node_state', update)
    page = deepcopy(EXAMPLE)
    requests = transport(monkeypatch, lambda r: httpx.Response(200, json=page))
    config = {'operation': 'on_new_response', 'sid': 30402, 'start': 1626448859836}
    first = node(config)
    assert (await first.execute({}))['new_response_count'] == 0
    assert not first.should_propagate_output({'new_response_count': 0}, config)
    # A different question in the same response group is a distinct response.
    page['data'][0]['questionId'] += 1
    second = node(config)
    result = await second.execute({})
    assert result['new_response_count'] == 1
    event = second.resolve_agent_event(result)
    for value in ('rank it', 'apple', '30402', page['data'][0]['responseGroupUid']): assert value in event['text']
    assert (await node(config).execute({}))['new_response_count'] == 0
    assert all(dict(r.url.params) == {'limit': '1000', 'sid': '30402', 'start': '1626448859836'} for r in requests)
    assert poll_scope(sprig.SprigNode, config) == poll_scope(sprig.SprigNode, {**config, 'label': 'renamed', 'goal': 'ignored'})
    assert poll_scope(sprig.SprigNode, config) != poll_scope(sprig.SprigNode, {**config, 'sid': 999})


@pytest.mark.asyncio
async def test_poll_drains_pages_and_deduplicates_overlapping_pages(monkeypatch):
    checkpoints = []
    async def unseen(self, items, key):
        checkpoints.append(items)
        return list({key(i): i for i in items}.values())
    monkeypatch.setattr(sprig.SprigNode, '_filter_unseen', unseen)
    def pages(r):
        body = deepcopy(EXAMPLE)
        if 'cursor' not in r.url.params:
            body['cursor'] = 'next'
            body['data'] = [dict(body['data'][0], questionId=239618 + i) for i in range(1000)]
        return httpx.Response(200, json=body)
    requests = transport(monkeypatch, pages)
    result = await node({'operation': 'on_new_response'}).execute({})
    assert result['new_response_count'] == 1000 and len(requests) == 2 and len(checkpoints[0]) == 1000


@pytest.mark.asyncio
async def test_cursor_cycle_never_consumes_poll_state(monkeypatch):
    calls = []
    async def unseen(self, items, key): calls.append(items); return items
    monkeypatch.setattr(sprig.SprigNode, '_filter_unseen', unseen)
    body = {**EXAMPLE, 'cursor': 'loop', 'data': [dict(EXAMPLE['data'][0], questionId=i) for i in range(1000)]}
    requests = transport(monkeypatch, body)
    with pytest.raises(ValueError, match='repeated'): await node({'operation': 'on_new_response'}).execute({})
    assert len(requests) == 2 and not calls


@pytest.mark.parametrize('config', [
    {'operation': 'get_study', 'study_id': '../oops'},
    {'operation': 'update_study', 'study_id': ID, 'version': 1, 'name': 'x', 'status': 'PAUSED'},
    {'operation': 'create_study', 'name': 'x', 'type': 'IN_PRODUCT_SURVEY'},
    {'operation': 'list_studies', 'limit': 51},
    {'operation': 'create_invitations', 'study_id': ID, 'count': 1},
    {'operation': 'delete_study', 'study_id': ID},
])
def test_invalid_configs_are_rejected(config):
    with pytest.raises((ValueError, ValidationError)): node(config)


def test_manual_credential_default_and_trigger_schema():
    credential = sprig.SprigAPIKeyCredential(api_key=KEY)
    assert credential.credential_type == 'sprig_api_key'
    schema = sprig.SprigNodeConfig.model_json_schema()
    assert schema['$defs']['SprigOnNewResponseConfig']['properties']['operation']['x-is-trigger'] is True
    assert sprig.SprigNode.connection_evidence.operation == 'list_studies'


@pytest.mark.asyncio
async def test_documented_short_page_with_position_cursor_emits_new_response(monkeypatch):
    async def update(self, mutate, **kw):
        _, result = mutate({'seen_ids': []})
        return result
    monkeypatch.setattr(sprig.SprigNode, '_update_node_state', update)
    requests = transport(monkeypatch, PAGE_EXAMPLE)
    n = node({'operation': 'on_new_response', 'sid': 1})
    result = await n.execute({})
    assert len(requests) == 1 and result['new_response_count'] == 1
    event = n.resolve_agent_event(result)
    assert '2603' in event['text'] and 'Option 2' in event['text']
    assert PAGE_EXAMPLE['data'][0]['responseGroupUid'] in event['text']


def test_success_response_redaction_preserves_unmodified_mappings():
    data = {'data': [{'id': '1', 'name': 'account data'}]}
    assert sprig._redact(data, KEY) is data
    echoed = {'data': [{'name': 'echo ' + KEY}], KEY: KEY}
    cleaned = sprig._redact(echoed, KEY)
    assert KEY not in str(cleaned)
    assert echoed['data'][0]['name'] == 'echo ' + KEY
