"""Exercise RocketReach through discovery and the normal node factory.

Contract-shaped responses cover routes, authentication, bulk acknowledgements,
and the poll family's baseline, version deduplication and scope changes.
"""
import json
from pathlib import Path
from copy import deepcopy

import httpx
import pytest
from pydantic import ValidationError

from nodes import rocket_reach_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/rocket-reach/responses.json').read_text())
TOKEN = 'rocket-reach-test-token'
CREDENTIAL = {'credential_type': native.FAMILY, 'api_key': TOKEN}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='rocket-test', node_type='automation-rocket-reach',
        node_data={'config': config, 'credentials': CREDENTIAL})


def transport(monkeypatch, responder):
    calls = []
    def respond(request):
        calls.append(request)
        return responder(request)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return calls


def config_for(operation):
    if 'bulk' in operation:
        return {'operation': operation, 'queries': [{'id': 123456}], 'profile_list': 'API Bulk Lookup'}
    if 'search' in operation:
        return {'operation': operation, 'query': {'name': ['RocketReach']}, 'start': 11, 'page_size': 10}
    if 'status' in operation:
        return {'operation': operation, 'ids': [123456, 234567]}
    if operation == 'create_email_verify':
        return {'operation': operation, 'email': 'jamie@rocketreach.co'}
    if 'lookup' in operation:
        return {'operation': operation, 'id': 123456}
    return {'operation': operation}


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(native.ROUTES))
async def test_routes_auth_bodies_and_documented_shapes(monkeypatch, operation):
    method, path, shape = native.ROUTES[operation]
    body = FIXTURES['account' if shape == 'account' else 'email' if operation == 'create_email_verify' else 'company' if 'company' in operation else 'person']
    if shape == 'list':
        body = [body]
    def responder(request):
        assert request.method == method
        assert request.url.path == '/api/v2' + path
        assert request.headers['Api-Key'] == TOKEN
        assert request.url.host == 'api.rocketreach.co'
        assert 'api_key' not in request.url.params
        if method == 'POST':
            sent = json.loads(request.content)
            assert 'operation' not in sent
            if 'bulk' in operation:
                assert sent['queries'][0]['id'] == 123456
            if 'search' in operation:
                assert sent['start'] == 11 and sent['page_size'] == 10
        elif 'status' in operation:
            assert request.url.params.get_list('ids') == ['123456', '234567']
        return httpx.Response(201 if 'search' in operation else 200,
            json=body if shape != 'accepted' else None,
            headers={'RR-Request-ID': '7143391e-0485-446e-ae4f-6e8325bcc3ed'})
    calls = transport(monkeypatch, responder)
    result = await node(config_for(operation)).execute({})
    assert result['status'] == 'success' and len(calls) == 1
    if shape == 'accepted':
        assert result['accepted'] is True and result['completion_verified'] is False
        assert result['rr_request_id'] == '7143391e-0485-446e-ae4f-6e8325bcc3ed'
    else:
        assert result['data'] == body


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(native.TRIGGERS))
async def test_poll_baseline_updates_dedup_and_scope(monkeypatch, operation):
    person = deepcopy(FIXTURES['person'])
    bodies = [[person]]
    calls = transport(monkeypatch, lambda r: httpx.Response(201, json=bodies[0]))
    instance = node({'operation': operation, 'updated_since': '2023-01-01', 'query': {'company_domain': ['rocketreach.co']}})
    state = {}
    async def update(mutator, **kwargs):
        new_state, result = mutator(deepcopy(state))
        if new_state is not None:
            state.clear(); state.update(new_state)
        return result
    instance._update_node_state = update
    assert (await instance.execute({}))['people'] == []
    assert instance.trigger_produced_no_event({})
    person['update_time'] = '2023-10-02T12:00:00Z'
    result = await instance.execute({})
    assert result['people'] == [person] and instance.trigger_emitted_event(result)
    event = native.RocketReachNode.resolve_agent_event(result)
    assert 'Jamie Gullbrand' in event['text'] and '123456' in event['text']
    assert (await instance.execute({}))['people'] == []
    sent = json.loads(calls[0].content)
    assert sent['query'] == {'company_domain': ['rocketreach.co'], 'update_time': ['2023-01-01']}
    instance._config.config.updated_since = '2023-02-01'
    assert (await instance.execute({}))['people'] == []


@pytest.mark.asyncio
async def test_pagination_finishes_before_poll_state_changes(monkeypatch):
    people = [{**FIXTURES['person'], 'id': i} for i in range(1, 101)]
    calls = transport(monkeypatch, lambda r: httpx.Response(201, json=people if json.loads(r.content)['start'] == 1 else []))
    instance = node({'operation': 'on_updated_person', 'updated_since': '2023-01-01'})
    async def update(mutator, **kwargs):
        _, result = mutator({'seen_ids': []})
        assert len(calls) == 2
        return result
    instance._update_node_state = update
    assert (await instance.execute({}))['new_or_updated_count'] == 100
    assert json.loads(calls[1].content)['start'] == 101


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(401, {'detail': 'Invalid API Key'}), (429, {'detail': 'Rate limit'}), (302, {}), (500, {}), (200, {'errors': [TOKEN]}), (200, {})])
async def test_account_failure_is_not_evidence_and_never_retries_or_exposes_key(monkeypatch, status, body):
    calls = transport(monkeypatch, lambda r: httpx.Response(status, json=body))
    with pytest.raises(ValueError) as caught:
        await node({'operation': 'get_account'}).execute({})
    assert TOKEN not in str(caught.value) and len(calls) == 1


@pytest.mark.asyncio
async def test_universal_account_key_is_removed(monkeypatch):
    transport(monkeypatch, lambda r: httpx.Response(200, json={**FIXTURES['account'], 'api_key': 'new-provider-secret'}))
    result = await node({'operation': 'get_universal_account'}).execute({})
    assert 'api_key' not in result['data']


def test_manual_key_defaults_and_invalid_matches():
    assert native.RocketReachAPIKeyCredential(api_key='  real-token  ').model_dump() == {'credential_type': native.FAMILY, 'api_key': 'real-token'}
    for key in ['https://rocketreach.co/account', '<token>', 'a\nb']:
        with pytest.raises(ValidationError):
            native.RocketReachAPIKeyCredential(api_key=key)
    for config in [{'operation': 'create_person_lookup'}, {'operation': 'create_company_lookup'}, {'operation': 'check_person_lookup_status'}, {'operation': 'on_updated_person', 'updated_since': 'not-a-date'}]:
        assert not native.RocketReachNode.validate_config({'config': config})['valid']
