"""Clerk.io actual factory, evidence and privacy regression source.

Keys, rows and HTTP responses are synthetic. A root-granted offline runner must
install guards before registry import; these fixtures are not live proof.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote

import httpx
import pytest
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from nodes import clerk_io_node as api
from nodes.clerk_io_node import ClerkIONode, ClerkIONodeConfig, KIND
from nodes.core import credential_connect as cc
from nodes.core.connection_evidence import collect_evidence
from nodes.core.registry import NodeFactory, NODE_REGISTRY
from nodes.core.run_op import run_node_operation
from repositories.credentials import credential_access_predicate
USER = "00000000-0000-0000-0000-000000000001"
from utils import ssrf

NODE = 'automation-clerk-io'
KEYS = {'credential_type': KIND, 'public_key': 'synthetic-public-store-key-42',
        'private_key': 'synthetic+private&store-key-42'}
PRODUCT = {'id': 42, 'name': 'Owned fixture', 'description': 'Disposable catalog metadata',
           'price': 12.5, 'image': 'https://catalog.example.test/42.png',
           'url': 'https://catalog.example.test/product/42', 'categories': [7], 'created_at': 1700000000}
CATEGORY = {'id': 7, 'name': 'Owned fixture', 'url': 'https://catalog.example.test/category/7', 'subcategories': []}
SCENARIOS = [
    ('check_connection', {}), ('check_public_connection', {}), ('get_products', {'products': [42]}),
    ('search_products', {'query': 'owned', 'limit': 2, 'offset': 3}),
    ('search_categories', {'query': 'owned', 'limit': 2}),
    ('popular_products', {'limit': 2, 'offset': 3}), ('trending_products', {'limit': 2}),
    ('new_products', {'limit': 2}), ('complementary_products', {'products': ['42'], 'limit': 2}),
    ('substituting_products', {'products': ['42'], 'limit': 2}),
    ('category_popular_products', {'category': '7', 'limit': 2}),
    ('upsert_products', {'products': [PRODUCT]}), ('patch_products', {'products': [{'id': 42, 'stock': 0}]}),
    ('remove_products', {'products': ['42']}), ('upsert_categories', {'categories': [CATEGORY]}),
    ('patch_categories', {'categories': [{'id': 7, 'name': 'Changed'}]}),
    ('upsert_customers', {'customers': [{'customerid': 'owned-42', 'name': 'Owned fixture'}]}),
    ('patch_customers', {'customers': [{'customerid': 'owned-42', 'name': 'Changed'}]}),
    ('remove_customers', {'customers': ['owned-42']}),
    ('upsert_orders', {'orders': [{'id': 'owned-42', 'customer': 'owned-42', 'time': 1700000000,
                                  'products': [{'id': 42, 'price': 12.5, 'quantity': 1}]}]}),
    ('patch_orders', {'orders': [{'id': 'owned-42', 'status': 'CANCELLED'}]}),
    ('remove_orders', {'orders': ['owned-42']}),
]


@pytest.fixture
def ensure_native_db_pool():
    yield  # Supersede repository autouse DB startup; no pool is opened.


@pytest.fixture
def fixture(monkeypatch):
    monkeypatch.setattr(ssrf, 'assert_url_allowed', AsyncMock())
    state = SimpleNamespace(requests=[], clients=[], response=None, after=None, error=None, storage=None)
    async def respond(request):
        state.requests.append(request)
        if state.after: state.after()
        if state.error: raise state.error(request)
        if state.response is not None: return state.response(request)
        if request.url.path == '/v2/product/attributes':
            return httpx.Response(200, json=[{'id': 42, 'name': 'Owned fixture', 'price': 12.5, 'private': 'not-exported'}])
        if request.url.path == '/v2/search/categories':
            return httpx.Response(200, json={'status': 'ok', 'result': [7], 'categories': [{'id': 7, 'name': 'Owned fixture', 'private': 'not-exported'}]})
        if request.url.path.startswith(('/v2/search/', '/v2/recommendations/')):
            return httpx.Response(200, json={'status': 'ok', 'result': [42], 'count': 1, 'hits': 9,
                                             'product_data': [{'id': 42, 'name': 'Owned fixture'}], 'debug': 'not-exported'})
        return httpx.Response(200, json={'status': 'ok', 'private': 'not-exported'})
    def client(**kwargs):
        state.clients.append(kwargs)
        return ssrf.guarded_async_client(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(api, 'guarded_async_client', client)
    cc._class_index.cache_clear()
    yield state
    cc._class_index.cache_clear()


async def run(fixture, operation, arguments=None, *, saved=True):
    node = NodeFactory.create_node('fixture', NODE, {
        'config': {'operation': operation, **(arguments or {})}, 'credentials': deepcopy(KEYS),
    })
    return await node.execute({})

@pytest.mark.asyncio
async def test_execute_uses_validated_credentials_when_raw_node_data_is_empty(fixture):
    config = ClerkIONodeConfig.model_validate({
        'config': {'operation': 'check_connection'}, 'credentials': deepcopy(KEYS),
    })
    instance = ClerkIONode(node_id='configured', node_type=NODE, node_data={}, config=config)
    result = await instance.execute({})
    assert result['private_key_accepted'] is True
    assert len(fixture.requests) == 1
    assert fixture.requests[0].url.params['private_key'] == KEYS['private_key']


@pytest.mark.asyncio
@pytest.mark.parametrize('operation,arguments', SCENARIOS)
async def test_actual_factory_dispatch_key_placement_and_closed_projection(fixture, operation, arguments):
    assert NODE_REGISTRY[NODE] is ClerkIONode
    output = await run(fixture, operation, arguments)
    assert len(fixture.requests) == 1
    request = fixture.requests[0]
    assert str(request.url).startswith(api.ORIGIN + '/')
    assert fixture.clients[0] == {'timeout': 30.0, 'follow_redirects': False, 'trust_env': False}
    assert 'not-exported' not in json.dumps(output) and KEYS['private_key'] not in json.dumps(output)
    if operation in api.WRITES:
        method, path, resource = api.WRITES[operation]
        assert request.method == method and request.url.path == '/v2' + path
        if method == 'DELETE':
            fields = dict(request.url.params)
            assert json.loads(fields[resource]) == arguments[resource]
        else:
            fields = json.loads(request.content)
            assert resource in fields and 'private_key' not in request.url.params
            if operation == 'patch_customers': assert fields[resource] == arguments[resource]
        assert fields['private_key'] == KEYS['private_key'] and fields['key'] == KEYS['public_key']
        assert output['applied'] is None and output['readback_verified'] is False
    else:
        assert request.url.params['key'] == KEYS['public_key']
        assert ('private_key' in request.url.params) == (operation == 'check_connection')
        assert not {'visitor', 'labels', 'debug', 'callback', 'filter'} & set(request.url.params)
        if operation in {'get_products', 'complementary_products', 'substituting_products'}:
            assert json.loads(request.url.params['products']) == arguments['products']
        if operation not in {'check_connection', 'search_categories'}:
            assert json.loads(request.url.params['attributes']) == list(api.ATTRIBUTES)
        if operation in {'new_products', 'search_categories', 'complementary_products', 'substituting_products'}:
            assert 'offset' not in request.url.params


@pytest.mark.asyncio
async def test_actual_manual_shape_and_private_evidence_without_account_identity(fixture, monkeypatch):
    from nodes.core import connection_evidence
    monkeypatch.setattr(cc, '_collect_evidence', connection_evidence.collect_evidence)
    shaped, errors, resolved = cc.shape_credential(KIND, {'public_key': KEYS['public_key'], 'private_key': KEYS['private_key']})
    assert not errors and resolved[0] == NODE and shaped['credential_type'] == KIND
    verdict = await cc.validate_for_connect(credential_type=KIND, credential_data=shaped, user_id=USER, pool=fixture.storage)
    assert verdict.ok and verdict.evidence.reachable is True and verdict.evidence.proves == 'reachability'
    assert not verdict.evidence.account_label and not verdict.evidence.samples
    assert fixture.requests[0].url.path == '/v2/audiences/list'
    public = await run(fixture, 'check_public_connection', saved=False)
    assert public['private_key_accepted'] is None and public['identity_verified'] is False


@pytest.mark.asyncio
@pytest.mark.parametrize('body,expected', [
    ({'status': 'error', 'type': 'AuthenticationError', 'message': KEYS['private_key']}, False),
    ({'status': 'error', 'type': 'InternalError', 'message': KEYS['private_key']}, None),
    ({}, None), ({'status': 'ok', 'echo': KEYS['private_key']}, None),
])
async def test_200_refusal_unknown_and_secret_echo_never_report_success(fixture, body, expected):
    fixture.response = lambda req: httpx.Response(200, json=body)
    evidence = await collect_evidence(node_type=NODE, credential_data=deepcopy(KEYS), user_id=USER, pool=fixture.storage)
    assert evidence.reachable is expected and KEYS['private_key'] not in str(evidence)


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [
    [{'id': 43, 'name': 'Foreign product'}],
    [{'id': 42}, {'id': 42}],
    [{'id': True}],
    [{'id': 42, 'price': 'unknown-number'}],
])
async def test_requested_product_boundary_and_metadata_types(fixture, response):
    fixture.response = lambda req: httpx.Response(200, json=response)
    with pytest.raises(ValueError): await run(fixture, 'get_products', {'products': [42]})


@pytest.mark.asyncio
async def test_partial_category_metadata_is_unknown_not_an_invented_complete_page(fixture):
    fixture.response = lambda req: httpx.Response(200, json={'status': 'ok', 'result': [7, 8], 'categories': [{'id': 7, 'name': 'Owned'}]})
    result = await run(fixture, 'search_categories', {'limit': 2})
    assert result['metadata_complete'] is False and result['complete_export'] is False
    assert 'next_page_token' not in result and 'total' not in result


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [
    lambda req: httpx.Response(302, headers={'location': 'https://foreign.example.test/?private_key=echo'}),
    lambda req: httpx.Response(429, json={'message': KEYS['private_key']}),
    lambda req: httpx.Response(500, json={'message': KEYS['private_key']}),
    lambda req: httpx.Response(200, content=b'<private>xml</private>', headers={'content-type': 'application/xml'}),
    lambda req: httpx.Response(200, content=b'{"status":"ok","status":"error"}', headers={'content-type': 'application/json'}),
    lambda req: httpx.Response(200, content=b'{"status":"ok","value":NaN}', headers={'content-type': 'application/json'}),
    lambda req: httpx.Response(200, content=b' ' * (api.MAX_BODY + 1), headers={'content-type': 'application/json'}),
])
async def test_status_media_json_and_size_errors_without_retry(fixture, response):
    fixture.response = response
    with pytest.raises(ValueError) as error: await run(fixture, 'check_connection', saved=False)
    assert KEYS['private_key'] not in str(error.value) and len(fixture.requests) == 1


@pytest.mark.asyncio
async def test_actual_httpx_logs_and_exception_are_secret_free_and_scoped(fixture, caplog):
    caplog.set_level(logging.DEBUG)
    def fail(request):
        logging.getLogger('httpcore.http11').debug('request failed %s', request.url)
        logging.getLogger('unrelated.clerk.fixture').info('unrelated diagnostics stay intact')
        return httpx.ConnectError('wire failure ' + str(request.url), request=request)
    fixture.error = fail
    with pytest.raises(ValueError) as error: await run(fixture, 'check_connection', saved=False)
    assert 'unrelated diagnostics stay intact' in caplog.text
    assert 'request failed https://api.clerk.io/v2/audiences/list' in caplog.text
    for secret in (KEYS['private_key'], quote(KEYS['private_key'], safe=''), KEYS['public_key']):
        assert secret not in caplog.text + str(error.value)
    assert api._SECRETS.get() == ()
    logging.getLogger('httpcore.http11').debug('outside request diagnostics')
    assert 'outside request diagnostics' in caplog.text


@pytest.mark.asyncio
async def test_http_instrumentation_is_suppressed_only_inside_clerk_request(fixture):
    exporter = InMemorySpanExporter(); provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    instrumentor = HTTPXClientInstrumentor(); original = api.guarded_async_client
    def instrumented(**kwargs):
        client = original(**kwargs)
        instrumentor.instrument_client(client, tracer_provider=provider)
        return client
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={})))
    instrumentor.instrument_client(client, tracer_provider=provider)
    try:
        with patch.object(api, 'guarded_async_client', instrumented): await run(fixture, 'check_connection', saved=False)
        async with client: await client.get('https://unrelated.example.test/diagnostic')
        spans = exporter.get_finished_spans()
        assert len(spans) == 1 and 'unrelated.example.test' in spans[0].to_json()
    finally:
        instrumentor.uninstrument_client(client)
        provider.shutdown()


@pytest.mark.parametrize('operation,arguments', [
    ('get_products', {'products': [True]}), ('get_products', {'products': [2147483648]}),
    ('search_categories', {'limit': 11}), ('popular_products', {'limit': 101}),
    ('patch_products', {'products': [{'id': 42}]}), ('upsert_customers', {'customers': [{'name': 'missing identity'}]}),
    ('upsert_customers', {'customers': [{'customerid': 'owned', 'subscribed': True}]}),
    ('patch_orders', {'orders': [{'id': 'owned', 'status': 'arbitrary'}]}),
    ('upsert_products', {'products': [{**PRODUCT, 'price': True}]}),
])
def test_actual_factory_refuses_invalid_bounds_missing_identity_and_fields(operation, arguments):
    with pytest.raises(ValueError):
        NodeFactory.create_node('fixture', NODE, {'config': {'operation': operation, **arguments}, 'credentials': deepcopy(KEYS)})


def test_foreign_tag_and_validation_errors_never_include_credentials():
    with pytest.raises(ValueError) as error:
        ClerkIONode.parse_config({'config': {'operation': 'check_connection'}, 'credentials': {**KEYS, 'credential_type': 'foreign_secret'}})
    assert KEYS['private_key'] not in str(error.value)
    bad = {**KEYS, 'private_key': KEYS['private_key'] + '\nprivate'}
    with pytest.raises(ValueError) as error: ClerkIONode.validate_credential(bad)
    assert bad['private_key'] not in str(error.value)
    leaf = ClerkIONode.get_config_schema()['$defs']['ClerkIOStoreCredential']
    assert leaf['required'] == ['public_key', 'private_key']
    assert leaf['properties']['private_key']['ui:widget'] == 'password'


def test_native_schema_golden_has_exact_actions_credentials_and_no_trigger():
    schema = ClerkIONode.get_config_schema()
    definitions = schema['$defs']
    variants = schema['properties']['config']['oneOf']
    names = {definitions[variant['$ref'].split('/')[-1]]['properties']['operation']['const'] for variant in variants}
    assert len(variants) == 22 and names == {operation for operation, _ in SCENARIOS}
    assert ClerkIONode.connection_evidence.proves == 'reachability'
    assert definitions['SearchCategories']['properties']['limit']['maximum'] == 10
    assert 'offset' not in definitions['NewProducts']['properties']
    assert definitions['ClerkIOStoreCredential']['properties']['credential_type']['const'] == KIND
    assert 'customerid' in definitions['Customer']['properties'] and 'id' not in definitions['Customer']['properties']


def test_real_factory_model_discovery_and_schema_are_not_annotation_only():
    assert ClerkIONode.get_config_model() is ClerkIONodeConfig
    instance = NodeFactory.create_node('config-regression', NODE, {
        'config': {'operation': 'check_connection'}, 'credentials': deepcopy(KEYS),
    })
    assert isinstance(instance.config, ClerkIONodeConfig)
    assert instance.config.config.operation == 'check_connection'
    schema = ClerkIONode.get_config_schema()
    assert schema['properties']['config']['oneOf']
    assert schema['$defs']['ClerkIOStoreCredential']['required'] == ['public_key', 'private_key']
