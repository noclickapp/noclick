"""Exercise the actual node factory against requests from the pinned Public API contract."""
import json
from pathlib import Path
import httpx
import pytest
from pydantic import ValidationError
from nodes import bitwarden_node as native
from nodes.core.registry import NodeFactory

CASES = json.loads((Path(__file__).parent / 'fixtures/bitwarden/requests.json').read_text())
TOKEN = 'synthetic-access-token'

@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, region='US'):
    return NodeFactory.create_node(node_id='bitwarden-test', node_type='automation-bitwarden', node_data={
        'config': config, 'credentials': {'credential_type': 'bitwarden_access_token', 'access_token': TOKEN, 'region': region}})


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['config']['operation'])
async def test_contract_requests_and_response_passthrough(monkeypatch, case):
    requests = []
    real = httpx.AsyncClient
    def reply(request):
        requests.append(request)
        return httpx.Response(200, json={'object': 'list', 'data': [{'id': 'owned-id', 'name': 'Development Team'}], 'continuationToken': 'next-cursor'})
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kw: real(transport=httpx.MockTransport(reply), **kw))
    result = await node(case['config']).execute({})
    assert len(requests) == 1
    req = requests[0]
    assert req.method == case['method'] and req.url.path == case['path']
    assert req.url.host == 'api.bitwarden.com'
    assert req.headers['authorization'] == 'Bearer ' + TOKEN
    assert (json.loads(req.content) if req.content else None) == case['body']
    assert result == {'data': [{'id': 'owned-id', 'name': 'Development Team'}], 'continuationToken': 'next-cursor'}


@pytest.mark.asyncio
@pytest.mark.parametrize('region,host', [('EU', 'api.bitwarden.eu'), ('Gov', 'api.bitwarden-gov.com')])
async def test_regions_pagination_and_provider_rejection(monkeypatch, region, host):
    real = httpx.AsyncClient
    def reply(request):
        assert request.url.host == host
        assert request.url.params['continuationToken'] == 'cursor+with/slash='
        return httpx.Response(401, json={'message': 'Token expired'})
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kw: real(transport=httpx.MockTransport(reply), **kw))
    with pytest.raises(ValueError, match='401: Token expired'):
        await node({'operation': 'list_groups', 'continuationToken': 'cursor+with/slash='}, region).execute({})


def test_manual_credential_and_path_validation():
    assert native.BitwardenAccessTokenCredential(access_token=TOKEN).credential_type == 'bitwarden_access_token'
    for config in [{'operation': 'get_member', 'id': '../groups'}, {'operation': 'get_policy', 'policy_type': 1000}, {'operation': 'create_group', 'body': {}}]:
        with pytest.raises(ValidationError):
            native.BitwardenNode.parse_config({'config': config})


def test_custom_permission_null_is_not_a_wire_value():
    with pytest.raises(ValidationError):
        native.MemberCreateRequestModel(type=2, email="jsmith@example.com", permissions=None)
    body = native.MemberCreateRequestModel(type=2, email="jsmith@example.com")
    assert "permissions" not in body.model_dump(mode="json", exclude_unset=True)


# Copied verbatim from https://bitwarden.com/help/public-api/#sample-request.
EVENT_RESPONSE = json.loads((Path(__file__).parent / 'fixtures/bitwarden/events.json').read_text())['body']


def poll_node(config=None):
    instance = node({'operation': 'on_new_event', **(config or {})})
    state = {}
    async def update(mutator, **kwargs):
        replacement, result = mutator(dict(state))
        if replacement is not None:
            state.clear()
            state.update(replacement)
        return result
    instance._update_node_state = update
    return instance, state


@pytest.mark.asyncio
async def test_documented_events_baseline_pagination_dedup_and_agent(monkeypatch):
    instance, state = poll_node({'actingUserId': 'a2549f79-a71f-4eb9-9234-eb7247333f94'})
    requests = []
    real = httpx.AsyncClient
    def reply(request):
        requests.append(request)
        assert request.url.path == '/public/events'
        assert request.url.params['actingUserId'] == 'a2549f79-a71f-4eb9-9234-eb7247333f94'
        assert 'schedule' not in request.url.params and 'lookback_hours' not in request.url.params
        from datetime import datetime, timedelta
        start, end = (datetime.fromisoformat(request.url.params[k]) for k in ('start', 'end'))
        assert end - start == timedelta(hours=24)
        if request.url.params.get('continuationToken'):
            assert request.url.params['continuationToken'] == 'string'
            return httpx.Response(200, json={'object': 'list', 'data': [], 'continuationToken': None})
        return httpx.Response(200, json=EVENT_RESPONSE)
    monkeypatch.setattr(native.httpx, 'AsyncClient', lambda **kw: real(transport=httpx.MockTransport(reply), **kw))
    assert await instance.execute({}) == {'events': [], 'new_event_count': 0}
    assert instance.trigger_produced_no_event({})
    assert native.BitwardenNode.resolve_agent_event({'events': []}) is None
    assert len(state['seen_ids']) == 1
    # An existing empty baseline models the documented event arriving after arming.
    state['seen_ids'] = []
    result = await instance.execute({})
    assert result == {'events': EVENT_RESPONSE['data'], 'new_event_count': 1}
    assert instance.trigger_emitted_event(result)
    assert native.BitwardenNode.should_propagate_output(result, {'operation': 'on_new_event'})
    event = native.BitwardenNode.resolve_agent_event(result)
    assert 'string logged in' in event['text']
    assert '2020-11-04T15:01:21.698Z' in event['text'] and 'itemId=string' in event['text']
    assert await instance.execute({}) == {'events': [], 'new_event_count': 0}
    assert len(requests) == 6
    for first, second in zip(requests[::2], requests[1::2]):
        assert first.url.params['start'] == second.url.params['start']
        assert first.url.params['end'] == second.url.params['end']


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,code', list(native.EVENT_KINDS.items()))
async def test_event_kind_filters_are_contract_enum_values(monkeypatch, kind, code):
    instance, state = poll_node({'event_kind': kind})
    state['seen_ids'] = []
    # Vary only the documented EventType enum to exercise each configured filter.
    matching = {**EVENT_RESPONSE['data'][0], 'type': code}
    other = {**matching, 'type': 1000}
    async def request(*args, **kwargs):
        return {'object': 'list', 'data': [other, matching, matching], 'continuationToken': None}
    monkeypatch.setattr(instance, '_request', request)
    result = await instance.execute({})
    assert result == {'events': [matching], 'new_event_count': 1}
    assert native.EVENT_LABELS[code] in native.BitwardenNode.resolve_agent_event(result)['text']


@pytest.mark.asyncio
async def test_poll_scope_rebaselines_only_on_watched_fields(monkeypatch):
    from nodes.core.poll_trigger import poll_scope
    instance, state = poll_node()
    async def request(*args, **kwargs):
        return {**EVENT_RESPONSE, 'continuationToken': None}
    monkeypatch.setattr(instance, '_request', request)
    state.update(seen_ids=[], scope=poll_scope(native.BitwardenNode, {'operation': 'on_new_event'}))
    scope = state['scope']
    assert poll_scope(native.BitwardenNode, {'operation': 'on_new_event', 'label': 'New label',
        'schedule': {'frequency': 'minutes', 'interval': 10}}) == scope
    instance._config = native.BitwardenNode.parse_config({'config': {'operation': 'on_new_event',
        'event_kind': 'item_created'}, 'credentials': instance.config.credentials.model_dump()})
    assert await instance.execute({}) == {'events': [], 'new_event_count': 0}
    assert state['scope'] != scope


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['repeated_cursor', 'http_error', 'invalid_list', 'too_many', 'page_limit'])
async def test_incomplete_poll_never_advances_seen_state(monkeypatch, failure):
    instance, state = poll_node()
    state['seen_ids'] = []
    calls = 0
    async def request(*args, **kwargs):
        nonlocal calls
        calls += 1
        if failure == 'http_error' and calls == 2:
            raise ValueError('Bitwarden HTTP 401: Token expired')
        if failure == 'invalid_list':
            return {'object': 'list'}
        if failure == 'too_many':
            return {'data': EVENT_RESPONSE['data'] * 10001}
        return {**EVENT_RESPONSE, 'continuationToken': str(calls) if failure == 'page_limit' else 'string'}
    monkeypatch.setattr(instance, '_request', request)
    with pytest.raises(ValueError):
        await instance.execute({})
    assert state == {'seen_ids': []}


def test_event_identity_uses_documented_fields_and_is_order_independent():
    event = EVENT_RESPONSE['data'][0]
    assert native.BitwardenNode._event_key(event) == native.BitwardenNode._event_key(dict(reversed(list(event.items()))))
    assert native.BitwardenNode._event_key(event) != native.BitwardenNode._event_key({**event, 'type': 1100})
