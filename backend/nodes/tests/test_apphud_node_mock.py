"""Native Apphud seams; synthetic storage/transport only, no provider calls."""
import asyncio
import json
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio

from nodes import apphud_node as provider
from nodes.apphud_node import ApphudNode as Node, NODE_TYPE, OPERATIONS, MAX_BYTES
from nodes.core.registry import NodeFactory
from nodes.core import credential_connect as cc, connection_evidence as ce, run_op

TAG, SECRET, PRIVATE = 'apphud_s2s_api_key', 'SyntheticApphudPrivateKey42', 'SyntheticPrivatePayload42'
APP, LINE, COLUMN, FILTER = '60b9058d', 'mrr', 'renewals_performance', 'customer_country'
TIME = {'from': '2026-01-01T00:00:00+00:00', 'to': '2026-01-03T00:00:00+00:00'}


def credential():
    return {'credential_type': TAG, 'api_key': SECRET, 'app_id': APP, 'chart_ids': [LINE, COLUMN], 'allowed_operations': list(OPERATIONS)}


def catalog():
    return {'chart_groups': [{'name': 'Money', 'charts': [{'id': identity, 'name': identity, 'type': kind, 'is_locked': False, 'additional': [{'id': 'view_by', 'name': 'View by', 'required': True, 'default_value': '86400', 'values': [{'id': '86400', 'name': 'Days'}]}], 'doc_url': 'https://example.invalid/' + SECRET} for identity, kind in [(LINE, 'line'), (COLUMN, 'column')]]}]}


def options():
    return {'segment_groups': [{'label': 'General', 'only_one': False, 'options': [{'value': FILTER, 'label': 'Country'}, {'value': 'platform', 'label': 'Platform'}]}], 'filter_groups': [{'name': 'General', 'filters': [{'id': FILTER, 'name': 'Country', 'conditions': [{'value': 'equals', 'label': '='}, {'value': 'not_equals', 'label': '!='}], 'values': []}]}], 'additional': {'view_by': [{'value': '86400', 'label': 'Days'}]}}


def envelope(results, meta=None):
    return {'data': {'results': results, 'meta': meta}, 'errors': None, 'trace_id': PRIVATE, 'customer': PRIVATE}


def node(op, raw=None, **changes):
    config = {'operation': op}
    if op != 'list_charts': config['chart_id'] = LINE
    if op == 'get_filter_values': config['filter_id'] = FILTER
    if op.startswith('query_'): config.update(time_range=TIME, additional={'view_by': '86400'})
    if op == 'query_column_chart': config['chart_id'] = COLUMN
    return NodeFactory.create_node(node_id='apphud-fixture', node_type=NODE_TYPE, node_data={'config': {**config, **changes}, 'credentials': deepcopy(raw or credential())}, sio=None, user_id='fixture-user')


@pytest.fixture
def ensure_native_db_pool():
    yield


@pytest_asyncio.fixture
async def transport(monkeypatch):
    from utils import ssrf
    state = SimpleNamespace(requests=[], override=None, on_request=None, addresses=['93.184.216.34'])
    monkeypatch.setattr(asyncio.get_running_loop(), 'getaddrinfo', AsyncMock(side_effect=lambda *a, **k: [(2 if ':' not in ip else 10, 1, 6, '', (ip, 443)) for ip in state.addresses]))
    def answer(request):
        state.requests.append(request)
        if state.on_request: state.on_request(request)
        if state.override:
            response = state.override(request)
            if response is not None: return response
        assert request.url.host == 'api.apphud.com' and request.headers['Authorization'] == 'Bearer ' + SECRET
        data = dict(request.url.params) if request.method == 'GET' else json.loads(request.content)
        assert data['app_id'] == APP and SECRET not in str(request.url) + request.content.decode()
        if request.method == 'GET': assert request.content == b''
        route = request.url.path.removeprefix('/api/public/v1/')
        if route == 'chart/list':
            assert data == {'app_id': APP}
            value = catalog()
        elif route == 'chart/options':
            assert set(data) == {'app_id', 'chart_id'}
            value = options()
        elif route == 'chart/filter':
            assert data['filter_id'] == FILTER and request.method == 'POST'
            value = {'id': FILTER, 'values': [{'value': 'US', 'label': 'United States'}], 'input_type': 'text'}
        elif route == 'chart/query/line':
            assert request.method == 'POST' and data['chart_id'] == LINE
            assert 'segments' not in data or len(data['segments']) == 1
            value = {'lines': [{'name': '(none)', 'cnt': 2, 'points': [{'point': TIME['from'], 'is_predict': 0, 'values': [{'name': 'MRR', 'type': 'money', 'value': 12.5, 'private': PRIVATE}]}]}]}
        else:
            assert route == 'chart/query/column' and request.method == 'POST' and data['chart_id'] == COLUMN
            assert 'segments' not in data or 1 <= len(data['segments']) <= 2
            value = {'rows': [{'segments': [{'name': FILTER, 'value': 'US', 'in_progress': False}], 'values': [{'name': 'Renewals', 'type': 'simple', 'value': 2}]}]}
        return httpx.Response(200, json=envelope(value))
    original = httpx.AsyncClient
    monkeypatch.setattr(ssrf.httpx, 'AsyncClient', lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(answer)))
    return state


def test_actual_factory_native_config_and_default_tag():
    instance = node('query_line_chart')
    assert isinstance(instance.config, provider.ApphudFullConfig) and instance.config.config.time_range.from_time == TIME['from']
    assert instance.node_data['credentials'] == credential() and cc.credential_classes_for_node(Node) == [provider.ApphudAPIKeyCredential, provider.ApphudMcpCredential]  # and its vendor's MCP server, last (nodes/core/vendor_mcp.py)
    assert Node.connection_evidence.operation == 'list_charts' and Node.connection_evidence.proves == 'reachability'
    assert Node.connection_evidence.identity_operation is None


@pytest.mark.asyncio
@pytest.mark.parametrize('op', OPERATIONS)
async def test_actual_native_run_five_closed_reads(transport, caplog, op):
    result = await node(op).run({})
    assert result['status'] == 'success' and result['action'] == op and result['configured_app_reachability_verified'] is True
    assert result['provider_account_identity_verified'] is False and result['expert_plus_entitlement_inferred'] is False
    assert SECRET not in json.dumps(result) + caplog.text and PRIVATE not in json.dumps(result) + caplog.text
    assert result['errors'] is None and 'meta' in result['data'] and result['local_scope_auto_extended'] is False
    assert len(transport.requests) == (1 if op == 'list_charts' else 2 if op == 'get_chart_options' else 3)
    if op == 'query_column_chart': assert result['pagination'] == {'offset': 0, 'limit': 100, 'next_offset': None, 'total_count': None, 'automatic_paging_performed': False}


@pytest.mark.asyncio
async def test_real_connect_shape_and_read_only_reachability(transport, monkeypatch):
    monkeypatch.setattr(cc, '_collect_evidence', ce.collect_evidence)
    raw = credential(); raw.pop('credential_type')
    shaped, errors, _ = cc.shape_credential(TAG, raw)
    assert not errors and shaped['credential_type'] == TAG
    result = await cc.validate_for_connect(credential_type=TAG, credential_data=raw, user_id='fixture-user')
    assert result.ok and result.evidence.reachable is True and Node.connection_evidence.proves == 'reachability'
    assert result.evidence.account_label is None and len(transport.requests) == 1
    assert transport.requests[0].url.path.endswith('/chart/list') and SECRET not in json.dumps(asdict(result.evidence))


@pytest.mark.asyncio
async def test_raw_foreign_tag_and_context_parent_reject_before_transport(transport):
    raw = credential(); raw['credential_type'] = 'apphud_sdk_key'
    nested = {'config': {'operation': 'list_charts'}, 'credentials': raw}
    assert not Node.validate_config(nested)['valid']
    with pytest.raises(ValueError): Node.parse_config(nested)
    with pytest.raises(ValueError): await Node.load_field_options('chart_id', raw)
    assert not (await cc.validate_for_connect(credential_type=TAG, credential_data=raw, user_id='fixture-user')).ok
    for context in ({'app_id': 'ffffffff'}, {'api_base_url': 'https://example.invalid'}, {'chart_id': 'foreign'}, {}):
        with pytest.raises(ValueError): await Node.load_field_options('filter_id', credential(), context=context)
    assert transport.requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['foreign-chart', 'policy', 'locked', 'wrong-type', 'additional-key', 'additional-number', 'segment', 'condition', '190'])
async def test_current_catalog_query_admission_and_boundaries(transport, case):
    raw, changes = credential(), {}
    if case == 'foreign-chart': changes['chart_id'] = 'outside'
    elif case == 'policy': raw['allowed_operations'] = ['list_charts']
    elif case == 'locked':
        value = catalog(); value['chart_groups'][0]['charts'][0]['is_locked'] = True
        transport.override = lambda request: httpx.Response(200, json=envelope(value)) if request.url.path.endswith('/list') else None
    elif case == 'wrong-type': changes['chart_id'] = COLUMN
    elif case == 'additional-key': changes['additional'] = {'unknown': '86400'}
    elif case == 'additional-number': changes['additional'] = {'view_by': 86400}
    elif case == 'segment': changes['segments'] = [{'id': 'unknown'}]
    elif case == 'condition': changes['filters'] = [{'id': FILTER, 'values': [{'condition': 'contains', 'value': 'US'}]}]
    else: changes['time_range'] = {**TIME, 'to': '2027-01-01T00:00:00+00:00'}
    if case == 'additional-number':
        with pytest.raises(ValueError): node('query_line_chart', raw, **changes)
    else: assert (await node('query_line_chart', raw, **changes).run({}))['status'] == 'error'
    assert not any('/query/' in request.url.path for request in transport.requests)


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['202', '204', '401', '403', '408', '429', 'errors200', 'missing', 'text', 'oversize', 'null-metric'])
async def test_actual_transport_and_envelope_errors_are_private(transport, caplog, case):
    def answer(request):
        if case.isdigit(): return httpx.Response(int(case), content=PRIVATE.encode(), headers={'content-type': 'text/plain'})
        if case == 'errors200': return httpx.Response(200, json={'data': None, 'errors': [{'id': 'unknown', 'title': SECRET + PRIVATE}]})
        if case == 'missing': return httpx.Response(200, json={'data': {'results': {}}, 'errors': None})
        if case == 'text': return httpx.Response(200, text=SECRET)
        if case == 'oversize': return httpx.Response(200, content=b'x' * (MAX_BYTES + 1), headers={'content-type': 'application/json'})
        if request.url.path.endswith('/query/line'): return httpx.Response(200, json=envelope({'lines': [{'name': 'X', 'cnt': 1, 'points': [{'point': TIME['from'], 'is_predict': 0, 'values': [{'name': 'X', 'type': 'money', 'value': None}]}]}]}))
    transport.override = answer
    result = await node('query_line_chart').run({})
    assert result['status'] == 'error' and result['automatic_retry_performed'] is False
    assert SECRET not in json.dumps(result) + caplog.text and PRIVATE not in json.dumps(result) + caplog.text


@pytest.mark.asyncio
async def test_real_run_op_body_alias_and_current_filter_discovery(transport):
    result = await run_op.run_node_operation(node_type=NODE_TYPE, operation='query_line_chart', arguments={'operation': 'delete_cache', 'chart_id': LINE, 'time_range': TIME, 'additional': {'view_by': '86400'}, 'filters': [{'id': FILTER, 'condition': 'not_equals', 'values': [{'condition': 'not_equals', 'value': 'US'}]}]}, credential_data=credential(), user_id='fixture-user')
    assert result['status'] == 'success' and result['action'] == 'query_line_chart'
    body = json.loads(transport.requests[-1].content)
    assert body['time_range'] == TIME and body['filters'][0]['condition'] == 'not_equals'
    assert 'segments' not in body and 'operation' not in body and [request.url.path.rsplit('/', 1)[-1] for request in transport.requests] == ['list', 'options', 'filter', 'line']


@pytest.mark.asyncio
async def test_two_column_segments_sorting_and_full_single_page(transport):
    result = await node('query_column_chart', segments=[{'id': FILTER}, {'id': 'platform'}], pagination={'limit': 1, 'offset': 7}, sorting={'field': 'Segment', 'order': 'DESC'}).run({})
    assert result['status'] == 'success' and result['pagination']['next_offset'] == 8 and result['pagination']['total_count'] is None
    body = json.loads(transport.requests[-1].content)
    assert body['segments'] == [{'id': FILTER}, {'id': 'platform'}] and body['sorting'] == {'field': 'Segment', 'order': 'DESC'}
    assert body['pagination'] == {'limit': 1, 'offset': 7} and len(transport.requests) == 3


@pytest.mark.asyncio
async def test_actual_pickers_and_single_page_empty_result(transport):
    charts = await Node.load_field_options('chart_id', credential(), context={'operation': 'query_line_chart'})
    filters = await Node.load_field_options('filter_id', credential(), context={'chart_id': LINE})
    assert [row['value'] for row in charts['options']] == [LINE, COLUMN]
    assert filters['options'][0]['metadata']['chart_id'] == LINE
    transport.override = lambda request: httpx.Response(200, json=envelope({'rows': []})) if request.url.path.endswith('/query/column') else None
    result = await node('query_column_chart', pagination={'limit': 1, 'offset': 7}).run({})
    assert result['status'] == 'success' and result['data']['results'] == {'rows': []} and result['pagination']['next_offset'] is None


def test_actual_parser_disconnected_shape_private_diagnostics_and_time_limits():
    assert Node.parse_config(Node._wrap_flat_config({'operation': 'list_charts'}, Node.get_config_model())).config.operation == 'list_charts'
    assert Node.validate_saved_config({'operation': 'list_charts'})['valid']
    for changes in ({'api_key': 'Bearer ' + SECRET}, {'api_base_url': 'https://example.invalid'}, {'app_id': 'com.example.app'}, {'chart_ids': [LINE, LINE]}):
        with pytest.raises(ValueError): provider.ApphudAPIKeyCredential.model_validate({**credential(), **changes})
    for time_range in ({'from': TIME['to'], 'to': TIME['from']}, {'from': TIME['from'], 'to': '2026-01-04T00:00:00+01:00'}, {'from': '2026-01-01', 'to': TIME['to']}):
        with pytest.raises(ValueError): node('query_line_chart', time_range=time_range)
    with pytest.raises(ValueError) as error: NodeFactory.create_node(node_id='apphud-bad', node_type=NODE_TYPE, node_data={'credentials': credential(), 'config': {'operation': SECRET}}, sio=None, user_id='fixture-user')
    assert SECRET not in str(error.value)


def test_documented_analytics_responses():
    # Keep the strict parsers compatible with the provider's published examples.
    from pathlib import Path
    examples = json.loads((Path(__file__).parent / 'fixtures/apphud/analytics.json').read_text())['responses']
    assert provider._catalog(examples['chart_groups']['data']['results'])['chart_groups'][0]['charts'][0]['id'] == 'mrr'
    assert provider._options(examples['segment_groups']['data']['results'])['segment_groups'][0]['options'][0]['value'] == 'customer_country'
    for key, operation in [('lines', 'query_line_chart'), ('rows', 'query_column_chart')]:
        result = provider._series(examples[key]['data']['results'], node(operation).config.config)
        assert len(result[key]) == 1
