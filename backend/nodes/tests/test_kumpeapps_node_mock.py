"""Replay the provider's published v5 response examples through the native node.

These regressions also check query-only mutations, false/zero values, failure
handling and credential shaping without a live KumpeApps account.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import kumpeapps_node as native
from nodes.core.registry import NodeFactory

EXAMPLES = json.loads((Path(__file__).parent / 'fixtures/kumpeapps/responses.json').read_text())['examples']
TOKEN = 'synthetic-kumpeapps-key'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id='kumpeapps-fixture', node_type='automation-kumpeapps',
        node_data={'config': config, 'credentials': {'credential_type': 'kumpeapps_auth_key', 'auth_key': TOKEN}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,example,status', [
    ({'operation': 'get_current_user'}, 'GET', 'user', 'userlist', 200),
    ({'operation': 'list_users', 'isChild': False, 'userID': 10}, 'GET', 'userlist', 'userlist', 200),
    ({'operation': 'update_user', 'userID': 10, 'username': 'janedoe', 'email': 'jane@doe.com', 'firstName': 'Jane', 'lastName': 'Doe', 'enableChores': False}, 'PUT', 'userlist', 'addUserResponse', 200),
    ({'operation': 'create_child_user', 'username': 'janedoe', 'password': 'test-child-secret', 'email': 'jane@doe.com', 'firstName': 'Jane', 'lastName': 'Doe'}, 'POST', 'userlist', 'addUserResponse', 200),
    ({'operation': 'list_chores', 'kidUsername': 'jane', 'day': 'Monday', 'optional': False}, 'GET', 'chorelist', 'chorelist', 200),
    ({'operation': 'create_chore', 'kidUsername': 'jane', 'choreName': 'Wash Dishes', 'extraAllowance': 0, 'oneTime': False}, 'POST', 'chorelist', 'success', 200),
    ({'operation': 'update_chore', 'idChoreList': 1, 'status': 'todo', 'updatedByAutomation': True}, 'PUT', 'chorelist', 'success', 200),
    ({'operation': 'delete_chore', 'idChoreList': 1}, 'DELETE', 'chorelist', 'success', 200),
    ({'operation': 'get_allowance', 'kidUserId': 1, 'transactionDays': 7}, 'GET', 'allowance', 'allowance', 200),
    ({'operation': 'add_allowance_transaction', 'kidUserId': 1, 'amount': 10.5, 'description': 'Weekly Allowance for Chores', 'transactionType': 'Add'}, 'POST', 'allowance', 'success', 200),
    ({'operation': 'list_wishlist', 'kidUserId': 1}, 'GET', 'wishlist', 'wishlist', 200),
    ({'operation': 'create_wish', 'kidUserId': 1, 'title': 'Pokemon Cards', 'priority': 1}, 'POST', 'wishlist', 'success', 201),
    ({'operation': 'update_wish', 'wishId': 1, 'title': 'Pokemon Cards', 'priority': 0}, 'PUT', 'wishlist', 'success', 201),
    ({'operation': 'delete_wish', 'wishId': 1}, 'DELETE', 'wishlist', 'success', 200),
    ({'operation': 'create_share_link', 'linkUserId': '1', 'link': 'https://khome.kumpeapps.com/portal/wish-list.php', 'scope': 'WishList'}, 'GET', 'share', '201_share', 201),
])
async def test_published_examples_and_query_contract(monkeypatch, config, method, path, example, status):
    requests = transport(monkeypatch, EXAMPLES[example], status)
    result = await node(config).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and str(request.url).startswith(native.BASE_URL + '/kkid/' + path)
    assert request.url.path == '/v5/kkid/' + path
    assert request.headers['X-Auth'] == TOKEN and request.content == b''
    assert dict(request.url.params) == {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in config.items() if k != 'operation'}
    assert TOKEN not in str(result) and 'plain_password' not in str(result) and 'remember_key' not in str(result)
    if config['operation'] in native.LIST_KEYS:
        assert result['items'] == native._redact(EXAMPLES[example][native.LIST_KEYS[config['operation']]], [TOKEN])


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(401, {'message': 'Key rejected'}), (412, {'message': 'API Key invalid'}), (202, None), (302, None), (200, {'success': False, 'message': 'Rejected'}), (200, {'success': True, 'user': {}})])
async def test_failed_ambiguous_and_malformed_reads_do_not_prove_connection(monkeypatch, status, body):
    transport(monkeypatch, body, status)
    with pytest.raises(ValueError):
        await node({'operation': 'list_users'}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,status', [('list_users', 204), ('list_chores', 206)])
async def test_documented_no_data_reads(monkeypatch, operation, status):
    transport(monkeypatch, None, status)
    result = await node({'operation': operation}).execute({})
    assert result['items'] == []


@pytest.mark.asyncio
async def test_provider_error_and_transport_query_secrets_are_redacted(monkeypatch):
    transport(monkeypatch, {'message': 'Rejected ' + TOKEN}, 412)
    with pytest.raises(ValueError) as exc:
        await node({'operation': 'list_users'}).execute({})
    assert TOKEN not in str(exc.value) and 'Rejected' in str(exc.value)
    def client(**kwargs):
        raise httpx.TransportError('https://service.test?password=test-child-secret')
    monkeypatch.setattr(native, 'guarded_async_client', client)
    with pytest.raises(ValueError) as exc:
        await node({'operation': 'create_child_user', 'username': 'jane', 'password': 'test-child-secret', 'email': 'jane@doe.com', 'firstName': 'Jane', 'lastName': 'Doe'}).execute({})
    assert 'test-child-secret' not in str(exc.value)


def test_manual_credential_default_and_required_operation_fields():
    credential = native.KumpeAppsAuthKeyCredential(auth_key=TOKEN)
    assert credential.credential_type == 'kumpeapps_auth_key'
    for key in ['https://example.com/key', 'has spaces', 'bad\nheader']:
        with pytest.raises(ValidationError):
            native.KumpeAppsAuthKeyCredential(auth_key=key)
    with pytest.raises(ValidationError):
        native.CreateChoreConfig(kidUsername='jane')
    with pytest.raises(ValidationError):
        native.AddAllowanceTransactionConfig(kidUserId=1, amount=1, description='test', transactionType='Invalid')


@pytest.mark.asyncio
async def test_allowance_poll_baseline_dedup_and_agent_event(monkeypatch):
    import copy
    response = copy.deepcopy(EXAMPLES['allowance'])
    # The provider's example repeats the same transaction; one real transaction
    # represents the initial baseline, and a second ID represents a later poll.
    response['allowanceTransaction'] = response['allowanceTransaction'][:1]
    requests = transport(monkeypatch, response)
    state = {}
    async def update_state(self, mutator, **kwargs):
        nonlocal state
        new_state, result = mutator(state)
        if new_state is not None:
            state = new_state
        return result
    monkeypatch.setattr(native.KumpeAppsNode, '_update_node_state', update_state)
    instance = node({'operation': 'on_new_allowance_transaction', 'kidUserId': 1, 'transactionDays': 7})
    baseline = await instance.execute({})
    assert baseline['new_transaction_count'] == 0
    assert instance.trigger_produced_no_event(baseline)
    later = copy.deepcopy(response['allowanceTransaction'][0])
    later['transactionId'] = 86
    response['allowanceTransaction'].append(later)
    output = await instance.execute({})
    assert output['new_transactions'] == [later]
    assert instance.trigger_emitted_event(output)
    event = native.KumpeAppsNode.resolve_agent_event(output)
    assert 'User 1' in event['text'] and 'Weekly Allowance for Chores' in event['text'] and '86' in event['text']
    assert native.KumpeAppsNode.should_propagate_output(output, {'operation': 'on_new_allowance_transaction'})
    assert (await instance.execute({}))['new_transaction_count'] == 0
    assert all(dict(request.url.params) == {'kidUserId': '1', 'transactionDays': '7'} for request in requests)
    assert native.KumpeAppsNode.schedule_poll_scope({'operation': 'on_new_allowance_transaction', 'kidUserId': 1}) != native.KumpeAppsNode.schedule_poll_scope({'operation': 'on_new_allowance_transaction', 'kidUserId': 2})
    assert native.KumpeAppsNode.schedule_poll_scope({'operation': 'on_new_allowance_transaction', 'kidUserId': 1, 'label': 'changed'}) == native.KumpeAppsNode.schedule_poll_scope({'operation': 'on_new_allowance_transaction', 'kidUserId': 1})
