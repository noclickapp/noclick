"""Contract routes, bearer auth, typed writes, and poll state behavior.

Response fixtures use fields declared in the pinned v1 schemas; the date, email,
phone and source literals below are the contract's examples. IDs/names are test
values, not live recordings or conformance witness overrides.
"""
from copy import deepcopy
from unittest.mock import AsyncMock
import json
from pathlib import Path

import httpx
import pytest

from nodes.inmobalia_crm_node import (
    OPERATIONS, TRIGGERS, InmobaliaCRMNode, InmobaliaCRMPersonalToken,
)
from nodes.core.poll_trigger import poll_scope

TOKEN = 'test-inmobalia-valid-token-abc123'
CREDENTIAL = {'credential_type': 'inmobalia_crm_pat', 'api_token': TOKEN}
FIXTURES = Path(__file__).parent / 'fixtures' / 'inmobalia-crm'


def node(config):
    parsed = InmobaliaCRMNode.parse_config({'config': config, 'credentials': CREDENTIAL})
    instance = object.__new__(InmobaliaCRMNode)
    instance.node_id = "inmobalia-test"
    instance._config = parsed
    instance.node_data = {'config': config}
    return instance


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', OPERATIONS)
async def test_each_action_maps_to_one_contract_request(operation):
    spec = OPERATIONS[operation]
    values = {'operation': operation}
    for key in spec.required:
        values[key] = 42 if key.endswith('Id') or key == 'contact' else {
            'source': 'https://www.example.com/contact?property=P12345',
            'type': 'Call', 'subject': 'Follow up', 'dateCompleted': '2025-03-21T17:00:00Z',
            'status': 'PENDING',
        }[key]
    if operation == 'create_contact':
        values['name'] = 'Marta'
    if operation == 'patch_contact':
        values['notes'] = 'Prefers city centre'
    instance = node(values)
    response = {'content': [], 'totalPages': 0} if 'page' in spec.query else [] if operation == 'list_users' else {'id': 42}
    instance._request = AsyncMock(return_value=response)
    result = await instance.execute({})
    args = instance._request.call_args
    assert instance._request.await_count == 1
    assert args.args == (spec.method, spec.path.replace('{contactId}', '42').replace('{webLeadId}', '42').replace('{propertyId}', '42').replace('{enquiryId}', '42').replace('{activityTaskId}', '42'))
    assert result['data'] == response
    if operation == 'patch_contact':
        assert args.kwargs['body'] == [{'op': 'add', 'path': '/notes', 'value': 'Prefers city centre'}]
    if operation == 'process_web_lead':
        assert args.kwargs['body'] == {'contact': 42}
    if operation.startswith('create_'):
        assert 'operation' not in args.kwargs['body']


@pytest.mark.asyncio
async def test_transport_auth_patch_media_errors_and_no_write_retry(monkeypatch):
    calls = []
    status = 200
    def handle(request):
        calls.append(request)
        if status == 200:
            return httpx.Response(status, json={'id': 42})
        return httpx.Response(status, text=f'Rejected {TOKEN}', headers={'Retry-After': '30'})
    client_type = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: client_type(transport=httpx.MockTransport(handle), **kw))
    instance = node({'operation': 'patch_contact', 'contactId': 42, 'email': 'marta.garcia@example.com'})
    await instance.execute({})
    req = calls[0]
    assert str(req.url) == 'https://api-crm.inmobalia.com/v1/contacts/42'
    assert req.headers['Authorization'] == f'Bearer {TOKEN}'
    assert req.headers['Content-Type'] == 'application/json-patch+json'
    assert json.loads(req.content) == [{'op': 'add', 'path': '/email', 'value': 'marta.garcia@example.com'}]
    status = 429
    with pytest.raises(ValueError, match='Retry-After: 30') as exc:
        await instance.execute({})
    assert TOKEN not in str(exc.value)
    assert len(calls) == 2


@pytest.mark.parametrize('config', [
    {'operation': 'create_contact'},
    {'operation': 'create_activity_log', 'type': 'x', 'subject': 'Call'},
    {'operation': 'create_activity_log', 'type': '<Call>', 'subject': 'Call'},
    {'operation': 'patch_contact', 'contactId': 42},
    {'operation': 'get_contact', 'contactId': '../users/me'},
    {'operation': 'create_web_lead', 'source': 'not a URL'},
    {'operation': 'create_activity_task', 'type': 'Call', 'subject': 'Visit'},
    {'operation': 'list_contacts', 'size': 501},
    {'operation': 'list_properties', 'fromDateModified': '2025-03-21T17:00:00Z', 'toDateModified': '2025-03-01T17:00:00Z'},
])
def test_invalid_configs_are_rejected(config):
    with pytest.raises(ValueError):
        node(config)


@pytest.mark.parametrize('token', ['Bearer secret123', 'abc\n123', 'https://example.com/token'])
def test_invalid_credentials(token):
    with pytest.raises(ValueError):
        InmobaliaCRMPersonalToken(api_token=token)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', TRIGGERS)
async def test_poll_baseline_new_changes_and_agent_context(operation):
    instance = node({'operation': operation})
    payload = json.loads((FIXTURES / (operation + '.json')).read_text())
    instance._request = AsyncMock(return_value=deepcopy(payload))
    state = {}
    async def update(mutator, **kwargs):
        new_state, result = mutator(deepcopy(state))
        if new_state is not None:
            state.clear()
            state.update(new_state)
        return result
    instance._update_node_state = update
    first = await instance.execute({})
    assert first['count'] == 0
    assert instance.trigger_produced_no_event(first)
    assert InmobaliaCRMNode.resolve_agent_event(first) is None
    changed = deepcopy(payload)
    changed['content'].append({**changed['content'][0], 'id': 99})
    instance._request.return_value = changed
    second = await instance.execute({})
    assert [r['id'] for r in second['items']] == [99]
    assert '99' in InmobaliaCRMNode.resolve_agent_event(second)['text']
    assert instance.trigger_emitted_event(second)
    assert (await instance.execute({}))['count'] == 0
    if operation != 'on_new_web_lead':
        changed['content'][0]['dateModified'] = '2025-03-14T10:15:00Z'
        instance._request.return_value = changed
        assert (await instance.execute({}))['count'] == 1


@pytest.mark.asyncio
async def test_poll_exhausts_pages_and_never_baselines_partial_result():
    instance = node({'operation': 'on_new_web_lead'})
    payload = json.loads((FIXTURES / 'on_new_web_lead.json').read_text())
    a = {**payload, 'totalPages': 2}
    b = {**deepcopy(payload), 'number': 1, 'totalPages': 2}
    b['content'][0]['id'] = 99
    instance._request = AsyncMock(side_effect=[a, b])
    instance._filter_unseen = AsyncMock(side_effect=lambda rows, fn: rows)
    assert len((await instance.execute({}))['items']) == 2
    assert [c.kwargs['params']['page'] for c in instance._request.call_args_list] == [0, 1]
    instance._request = AsyncMock(side_effect=[a, ValueError('page failed')])
    instance._filter_unseen.reset_mock()
    with pytest.raises(ValueError, match='page failed'):
        await instance.execute({})
    instance._filter_unseen.assert_not_called()


def test_poll_scope_only_declared_config_fields():
    a = {'operation': 'on_new_or_updated_contact'}
    assert poll_scope(InmobaliaCRMNode, a) == poll_scope(InmobaliaCRMNode, {**a, 'goal': 'renamed'})
    assert poll_scope(InmobaliaCRMNode, a) != poll_scope(InmobaliaCRMNode, {**a, 'fromDateModified': '2025-03-01T00:00:00Z'})
