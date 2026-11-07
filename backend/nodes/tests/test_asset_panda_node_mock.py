"""Native Asset Panda factory/schema/connect and exact Pioneer wire fixtures.

Synthetic current OpenAPI envelopes exercise ancestry, privacy and bounded search.
They do not establish real entitlement, field-name compatibility or provider identity.
"""
import ast
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from nodes import asset_panda_node as p
from nodes.core.registry import NodeFactory
from nodes.core import connection_evidence, credential_connect

KEY = {'credential_type': p.TYPE, 'access_key_id': 'synthetic-private-id', 'access_key_secret': 'synthetic-private-secret', 'account_id': 'account_1'}
PARENTS = {'module_id': 'module_1', 'collection_id': 'collection_1'}


@pytest.fixture
def ensure_native_db_pool():
    yield


class Wire:
    def __init__(self):
        self.calls, self.responses, self.fail = [], [], None
        private = {'email': 'private@example.test', 'url': 'https://private.example.test/capability', 'credentials': {'secret': 'private-data'}}
        self.data = {
            '/accounts': [{'id': 'account_1', 'name': 'undocumented-account-name', **private}],
            '/account/account_1': {'id': 'account_1', **private},
            '/modules': [{'id': 'module_1', 'name': 'undocumented-module-name', **private}],
            '/module/module_1': {'id': 'module_1', **private},
            '/collections': [{'id': 'collection_1', 'name': 'Requested collection', **private}],
            '/collection/collection_1': {'id': 'collection_1', 'name': 'Requested collection', **private},
            '/collection-columns': [{'id': 'column_1', 'name': 'Asset code', 'type': 'Text', **private}],
            '/collection-record/record_1': {'id': 'record_1', 'values': {'name': 'private record content'}, **private},
            '/collection-records/search': [{'id': 'record_1', 'values': {'name': 'private record content'}, **private}],
        }

    @asynccontextmanager
    async def client(self, **options):
        assert options == {'timeout': 12, 'follow_redirects': False, 'trust_env': False}
        wire = self
        class Client:
            @asynccontextmanager
            async def stream(self, method, url, **kwargs):
                assert url.startswith(p.ROOT + '/') and '?' not in url
                path = url[len(p.ROOT):]
                assert path in wire.data
                assert method == ('POST' if path == '/collection-records/search' else 'GET')
                assert kwargs['headers']['Access-Key-Id'] == KEY['access_key_id']
                assert kwargs['headers']['Access-Key-Secret'] == KEY['access_key_secret']
                assert 'Authorization' not in kwargs['headers']
                assert KEY['access_key_id'] not in repr(kwargs) and KEY['access_key_secret'] not in repr(kwargs)
                assert set(kwargs) == ({'params', 'headers', 'json'} if method == 'POST' else {'params', 'headers'})
                wire.calls.append((method, path, deepcopy(kwargs['params']), deepcopy(kwargs.get('json'))))
                if wire.fail:
                    raise wire.fail
                result = wire.responses.pop(0) if wire.responses else {'data': deepcopy(wire.data[path])}
                response = result if isinstance(result, httpx.Response) else httpx.Response(200, json=result)
                response.request = httpx.Request(method, url)
                yield response
        yield Client()


@pytest.fixture
def wire(monkeypatch):
    value = Wire(); monkeypatch.setattr(p, 'guarded_async_client', value.client); return value


def node(config, credentials=None):
    return NodeFactory.create_node('fixture', 'automation-asset-panda', {'config': config, 'credentials': deepcopy(KEY if credentials is None else credentials)})


def test_actual_native_schema_and_production_constraints():
    schema = p.AssetPandaNode.get_config_schema()
    script = Path(__file__).resolve().parents[2] / 'scripts/generate_socket_types.py'
    selected = [n for n in ast.parse(script.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == '_assert_no_incoherent_constraints']
    ns = {}; assert len(selected) == 1
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(script), 'exec'), ns)
    ns['_assert_no_incoherent_constraints']('asset-panda', schema)
    ops = {schema['$defs'][r['$ref'].split('/')[-1]]['properties']['operation']['const'] for r in schema['properties']['config']['oneOf']}
    assert ops == p.OPERATIONS and len(ops) == 9
    assert schema['$defs']['SearchRecords']['properties']['column_id']['x-dynamic-options']['depends_on'] == ['module_id', 'collection_id']
    assert schema['$defs']['SearchRecords']['properties']['page_size']['maximum'] == 100
    assert schema['$defs']['AssetPandaAccessKeyCredential']['properties']['access_key_secret']['ui:widget'] == 'password'
    assert not ops & {'create_record', 'update_record', 'delete_record', 'raw_request', 'login', 'action'}


@pytest.mark.parametrize('bad', [True, 19, 'a/b', '..', '', ' white ', 'a?b', 'https://evil.example', 'x' * 129])
def test_actual_native_ids_reject_non_string_or_unsafe_path_values(bad):
    with pytest.raises(ValidationError): p.GetModule(module_id=bad)


def test_actual_search_validation_preserves_string_and_documented_page_bounds():
    cfg = p.SearchRecords(**PARENTS, column_id='column_1', value='fixture')
    assert cfg.value == 'fixture' and cfg.page_size == 50 and cfg.offset == 0
    for change in ({'value': ''}, {'page_size': 101}, {'offset': -1}, {'page_size': True}, {'operator': 'arbitrary'}):
        with pytest.raises(ValidationError): p.SearchRecords(**{**PARENTS, 'column_id': 'column_1', 'value': 'fixture', **change})


def test_visible_credential_shape_privacy_and_raw_family_guard():
    value = p.AssetPandaAccessKeyCredential(**{k: v for k, v in KEY.items() if k != 'credential_type'})
    assert value.model_dump(exclude_unset=True)['credential_type'] == p.TYPE
    assert KEY['access_key_id'] not in repr(value) and KEY['access_key_secret'] not in repr(value)
    with pytest.raises(ValueError): p.guard({**KEY, 'credential_type': 'asset_panda_legacy_oauth'})
    with pytest.raises(ValueError): node({'operation': 'list_accounts'}, {**KEY, 'credential_type': 'foreign'})


@pytest.mark.asyncio
async def test_actual_connect_collector_uses_protected_account_membership_not_public_metadata(wire, monkeypatch):
    credential_connect._class_index.cache_clear()
    monkeypatch.setattr(credential_connect, '_collect_evidence', connection_evidence.collect_evidence)
    verdict = await credential_connect.validate_for_connect(credential_type=p.TYPE, credential_data={k: v for k, v in KEY.items() if k != 'credential_type'}, user_id='fixture-user', probe=True)
    assert verdict.ok and verdict.evidence.reachable is True
    result = await node({'operation': 'list_accounts'}).execute({})
    assert result['items'] == [{'id': 'account_1'}] and result['principal_identity_verified'] is False
    assert result['provider_permissions_verified'] is False
    assert all(path == '/accounts' for _, path, _, _ in wire.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,args', [
    ('list_accounts', {}), ('get_account', {}), ('list_modules', {}), ('get_module', {'module_id': 'module_1'}),
    ('list_collections', {'module_id': 'module_1'}), ('get_collection', PARENTS), ('list_collection_columns', PARENTS),
    ('get_collection_record', {**PARENTS, 'record_id': 'record_1'}),
    ('search_collection_records', {**PARENTS, 'column_id': 'column_1', 'value': 'fixture', 'offset': 3, 'page_size': 7}),
])
async def test_actual_factory_nine_routes_emit_only_documented_requested_metadata(wire, operation, args):
    result = await node({'operation': operation, **args}).execute({})
    for private in [*KEY.values(), 'private@example.test', 'private.example.test', 'private-data', 'private record content', 'undocumented-account-name', 'undocumented-module-name', 'Requested collection', 'Asset code']:
        if private not in {p.TYPE, 'account_1'}:
            assert private not in json.dumps(result)
    assert wire.calls[0][1] == '/accounts'
    if operation == 'search_collection_records':
        method, path, query, body = wire.calls[-1]
        assert method == 'POST' and path == '/collection-records/search' and query == {}
        assert body == {'tenant': {'accountId': 'account_1', 'moduleId': 'module_1'}, 'collectionId': 'collection_1', 'searchInput': {'selection': {'matchType': 'All', 'filters': [{'field': 'Asset code', 'operator': 'eq', 'value': 'fixture'}]}}, 'pagination': {'from': 3, 'size': 7}}
        assert result['items'] == [{'id': 'record_1'}] and result['total'] is None and result['has_more'] is None and result['next_cursor'] is None
    if operation == 'get_collection_record':
        assert wire.calls[-1][2] == {'accountId': 'account_1', 'moduleId': 'module_1', 'collectionId': 'collection_1'}


@pytest.mark.asyncio
async def test_names_require_explicit_opt_in_and_account_module_names_stay_unsupported(wire):
    result = await node({'operation': 'list_collection_columns', **PARENTS, 'include_names': True}).execute({})
    assert result['items'] == [{'id': 'column_1', 'name': 'Asset code', 'type': 'Text'}]
    result = await node({'operation': 'get_collection', **PARENTS, 'include_names': True}).execute({})
    assert result == {'id': 'collection_1', 'name': 'Requested collection'}


@pytest.mark.asyncio
@pytest.mark.parametrize('missing,last_path', [('/accounts', '/accounts'), ('/modules', '/modules'), ('/collections', '/collections')])
async def test_actual_ancestor_membership_refuses_before_descendant_request(wire, missing, last_path):
    wire.data[missing] = []
    with pytest.raises(ValueError): await node({'operation': 'get_collection_record', **PARENTS, 'record_id': 'record_1'}).execute({})
    assert wire.calls[-1][1] == last_path and all(path != '/collection-record/record_1' for _, path, _, _ in wire.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize('path', ['/module/module_1', '/collection/collection_1', '/collection-record/record_1'])
async def test_actual_foreign_point_response_is_not_projected(wire, path):
    wire.data[path] = {'id': 'foreign_id'}
    with pytest.raises(ValueError, match='different scoped'): await node({'operation': 'get_collection_record', **PARENTS, 'record_id': 'record_1'}).execute({})


@pytest.mark.asyncio
async def test_current_column_membership_and_documented_string_name_are_required_before_search(wire):
    wire.data['/collection-columns'] = [{'id': 'foreign_column', 'name': 'Asset code'}]
    with pytest.raises(ValueError, match='Filter column'): await node({'operation': 'search_collection_records', **PARENTS, 'column_id': 'column_1', 'value': 'fixture'}).execute({})
    assert all(path != '/collection-records/search' for _, path, _, _ in wire.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [httpx.Response(403, text=KEY['access_key_secret']), httpx.Response(429, text=KEY['access_key_id']), httpx.Response(302, headers={'Location': 'https://private.example.test'}), httpx.Response(200, text='not-json'), {'data': {'id': 'account_1'}}])
async def test_refusal_or_bad_envelope_is_sanitized_without_retry_or_false_auth_claim(wire, response):
    wire.responses = [response]
    with pytest.raises(ValueError) as error: await node({'operation': 'list_accounts'}).execute({})
    assert KEY['access_key_secret'] not in str(error.value) and KEY['access_key_id'] not in str(error.value)
    assert len(wire.calls) == 1


@pytest.mark.asyncio
async def test_picker_uses_ids_and_local_continuation_bound_to_current_parents_and_inventory(wire):
    wire.data['/modules'] = [{'id': f'module_{i:03d}', 'name': 'private name'} for i in range(60)]
    first = await p.AssetPandaNode.load_field_options('module_id', KEY)
    assert len(first['options']) == 50 and all(v['label'] == v['value'] for v in first['options'])
    second = await p.AssetPandaNode.load_field_options('module_id', KEY, page_token=first['next_page_token'])
    assert len(second['options']) == 10 and second['next_page_token'] is None
    with pytest.raises(ValueError): await p.AssetPandaNode.load_field_options('module_id', KEY, search='059', page_token=first['next_page_token'])
    with pytest.raises(ValueError): await p.AssetPandaNode.load_field_options('collection_id', KEY, context={'module_id': 'module_1'}, page_token=first['next_page_token'])


@pytest.mark.asyncio
async def test_actual_collection_picker_rejects_same_ids_under_a_different_valid_parent(wire):
    wire.data['/modules'] = [{'id': 'module_1'}, {'id': 'module_2'}]
    wire.data['/module/module_2'] = {'id': 'module_2'}
    wire.data['/collections'] = [{'id': f'collection_{i:03d}'} for i in range(60)]
    first = await p.AssetPandaNode.load_field_options('collection_id', KEY, context={'module_id': 'module_1'})
    second = await p.AssetPandaNode.load_field_options('collection_id', KEY, context={'module_id': 'module_1'}, page_token=first['next_page_token'])
    assert len(second['options']) == 10
    with pytest.raises(ValueError, match='continuation'):
        await p.AssetPandaNode.load_field_options('collection_id', KEY, context={'module_id': 'module_2'}, page_token=first['next_page_token'])
    assert wire.calls[-1][1:3] == ('/collections', {'accountId': 'account_1', 'moduleId': 'module_2'})


@pytest.mark.asyncio
async def test_oversized_or_repeated_metadata_and_search_pages_are_refused(wire):
    wire.data['/accounts'] = [{'id': 'account_1'}, {'id': 'account_1'}]
    with pytest.raises(ValueError, match='repeated'): await node({'operation': 'list_accounts'}).execute({})
    wire.data['/accounts'] = [{'id': 'account_1'}]
    wire.data['/collection-records/search'] = [{'id': 'r1'}, {'id': 'r2'}]
    with pytest.raises(ValueError, match='oversized'): await node({'operation': 'search_collection_records', **PARENTS, 'column_id': 'column_1', 'value': 'fixture', 'page_size': 1}).execute({})
