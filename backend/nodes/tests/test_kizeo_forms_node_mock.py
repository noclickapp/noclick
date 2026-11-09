"""Offline request and documented-envelope regressions for Kizeo Forms v3."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import kizeo_forms_node as native
from nodes.core.base import ConfigValidationError

TOKEN = 'synthetic-kizeo-forms-token-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    data = {'config': config, 'credentials': {'api_token': TOKEN}}
    return native.KizeoFormsNode('kizeo-test', 'automation-kizeo-forms', data,
        config=native.KizeoFormsNode.parse_config(data))


def transport(monkeypatch, body, status=200):
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(reply), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


# Expected wire contracts are deliberately independent of the node route table.
CASES = [
    ({'operation': 'list_forms'}, 'GET', '/forms', None),
    ({'operation': 'get_form', 'form_id': 12}, 'GET', '/forms/12', None),
    ({'operation': 'search_data', 'form_id': 12, 'global_filters': 'customer', 'filters': [{'field': '_user_id', 'operator': '=', 'type': 'simple', 'val': '21'}]}, 'POST', '/forms/12/data/advanced', {'global_filters': 'customer', 'filters': [{'field': '_user_id', 'operator': '=', 'type': 'simple', 'val': '21'}], 'order': []}),
    ({'operation': 'get_data', 'form_id': 12, 'data_id': 34}, 'GET', '/forms/12/data/34', None),
    ({'operation': 'list_unread_data', 'form_id': 12, 'action': 'invoice + receipt', 'limit': 25}, 'GET', '/forms/12/data/unread/invoice%20%2B%20receipt/25', None),
    ({'operation': 'mark_data_read', 'form_id': 12, 'action': 'invoice', 'data_ids': [34, 35]}, 'POST', '/forms/12/markasreadbyaction/invoice', {'data_ids': [34, 35]}),
    ({'operation': 'mark_data_unread', 'form_id': 12, 'action': 'invoice', 'data_ids': [34]}, 'POST', '/forms/12/markasunreadbyaction/invoice', {'data_ids': [34]}),
    ({'operation': 'push_data', 'form_id': 12, 'recipient_user_id': 21, 'fields': {'customer': {'value': 'Acme'}}}, 'POST', '/forms/12/push', {'recipient_user_id': 21, 'fields': {'customer': {'value': 'Acme'}}}),
    ({'operation': 'list_push_inbox'}, 'GET', '/forms/push/inbox', None),
    ({'operation': 'list_exports', 'form_id': 12}, 'GET', '/forms/12/exports', None),
    ({'operation': 'list_lists'}, 'GET', '/lists', None),
    ({'operation': 'get_list', 'list_id': 56}, 'GET', '/lists/56', None),
    ({'operation': 'get_complete_list', 'list_id': 56}, 'GET', '/lists/56/complete', None),
    ({'operation': 'update_list', 'list_id': 56, 'items': ['customer:Acme']}, 'PUT', '/lists/56', {'items': ['customer:Acme']}),
    ({'operation': 'list_users'}, 'GET', '/users', None),
    ({'operation': 'list_groups'}, 'GET', '/groups', None),
    ({'operation': 'get_group', 'group_id': 78}, 'GET', '/group/78', None),
    ({'operation': 'create_group', 'name': 'Field team', 'parent_group_id': 78}, 'POST', '/group', {'name': 'Field team', 'parent_group_id': 78}),
    ({'operation': 'update_group', 'group_id': 78, 'name': 'Field team'}, 'PUT', '/group/78', {'name': 'Field team'}),
    ({'operation': 'delete_group', 'group_id': 78}, 'DELETE', '/group/78', None),
    ({'operation': 'list_group_users', 'group_id': 78}, 'GET', '/group/78/users', None),
]


@pytest.mark.asyncio
@pytest.mark.parametrize('config,method,path,body', CASES, ids=[c[0]['operation'] for c in CASES])
async def test_exact_single_request(monkeypatch, config, method, path, body):
    requests = transport(monkeypatch, {'status': 'ok', 'forms': [{'id': 12, 'name': 'Site visits'}]})
    result = await node(config).execute({})
    assert result['status'] == 'success'
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method
    assert str(request.url) == native.BASE + path
    assert request.headers['Authorization'] == TOKEN
    assert request.headers['Accept'] == 'application/json'
    assert (json.loads(request.content) if request.content else None) == body


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [
    [{'id': 12, 'name': 'Site visits'}],
    {'status': 'ok', 'forms': [{'id': 12, 'name': 'Site visits'}]},
    {'id': 12, 'name': 'Site visits'},
    {'status': 'ok', 'data': {'forms': [{'id': 12, 'name': 'Site visits'}]}},
    {'status': 'ok', 'forms': []},
])
async def test_connection_evidence_form_shapes(monkeypatch, body):
    transport(monkeypatch, body)
    result = await node({'operation': 'list_forms'}).execute({})
    assert isinstance(result['items'], list)
    assert result['data'] == body


@pytest.mark.asyncio
async def test_documented_external_list_envelope(monkeypatch):
    # Published response: https://kizeo.github.io/kizeo-forms-documentations/docs/lists/
    body = json.loads((Path(__file__).parent / 'fixtures/kizeo-forms/external-list.json').read_text())
    transport(monkeypatch, body)
    result = await node({'operation': 'get_list', 'list_id': 56}).execute({})
    assert result['data'] == body
    assert result['data']['list']['items'] == ['key1:value1', 'key2:value2', 'key3:value3', 'key4:value4', 'key5:value5']


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [200, 401, 403, 429, 500])
async def test_provider_errors_are_not_success_or_retried(monkeypatch, status):
    requests = transport(monkeypatch, {'status': 'error', 'message': 'Rejected ' + TOKEN}, status)
    result = await node({'operation': 'update_list', 'list_id': 56, 'items': []}).execute({})
    assert result == {'status': 'error', 'status_code': status, 'error': 'Rejected [redacted]'}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_no_redirect_or_html_success(monkeypatch):
    def client(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(302, text='<html>Sign in</html>', headers={'Location': 'https://other.example'})), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    with pytest.raises(ValueError, match='non-JSON'):
        await node({'operation': 'list_forms'}).execute({})


@pytest.mark.asyncio
async def test_missing_forms_is_not_verified(monkeypatch):
    transport(monkeypatch, {'status': 'ok'})
    with pytest.raises(ValueError, match='did not contain forms'):
        await node({'operation': 'list_forms'}).execute({})


@pytest.mark.asyncio
async def test_empty_list_clears_items_without_dropping_body(monkeypatch):
    requests = transport(monkeypatch, {'status': 'ok', 'message': 'Updated'})
    await node({'operation': 'update_list', 'list_id': 56, 'items': []}).execute({})
    assert json.loads(requests[0].content) == {'items': []}


@pytest.mark.parametrize('config', [
    {'operation': 'get_form', 'form_id': 0},
    {'operation': 'list_unread_data', 'form_id': 12, 'action': '..'},
    {'operation': 'mark_data_read', 'form_id': 12, 'action': 'x', 'data_ids': []},
    {'operation': 'mark_data_read', 'form_id': 12, 'action': 'x', 'data_ids': [-1]},
    {'operation': 'push_data', 'form_id': 12, 'recipient_user_id': 21, 'fields': {'customer': {'other': 'x'}}},
    {'operation': 'get_form', 'form_id': 12, 'url': 'https://other.example'},
])
def test_invalid_configs(config):
    with pytest.raises(ConfigValidationError):
        node(config)


@pytest.mark.parametrize('token', ['https://example.com/key', '<token>', 'Bearer abc', 'abc\r\nInjected: value'])
def test_bad_tokens(token):
    with pytest.raises(ValidationError):
        native.KizeoFormsAPITokenCredential(api_token=token)


def test_manual_credential_default():
    credential = native.KizeoFormsAPITokenCredential(api_token=' ' + TOKEN + '\n')
    assert credential.credential_type == 'kizeo_forms_api_token'
    assert credential.api_token == TOKEN
