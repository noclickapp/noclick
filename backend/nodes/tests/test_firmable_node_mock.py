"""Offline tests against provider examples and the native node factory."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import firmable_node as native
from nodes.core.registry import NodeFactory

INPUTS = json.loads((Path(__file__).parent / 'fixtures/firmable/inputs.json').read_text())
KEY = 'fbl_synthetic-unit-test-key'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, creds=None):
    return NodeFactory.create_node(node_id='firmable-test', node_type='automation-firmable', node_data={
        'config': config, 'credentials': creds or {'credential_type': 'firmable_api_key', 'api_key': KEY}})


def transport(monkeypatch, body, status=200):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', list(INPUTS))
async def test_all_actions_use_documented_route_and_parameter_names(monkeypatch, operation):
    if operation == 'list_filter_options':
        body = {'markets': [{'code': 'AU', 'label': 'Australia'}], 'filters': []}
    elif operation == 'search_people':
        body = {'success': True, 'total': 1, 'records': [{'person_id': 'f000000117274', 'name': 'Jane Smith'}]}
    elif operation == 'get_tech_intelligence':
        body = {'id': 'f000000740279', 'total': 558, 'tech_intelligence': [], 'next_cursor': 'opaque-cursor'}
    else:
        body = {'id': 'f000000117274', 'name': 'SMEC'}
    requests = transport(monkeypatch, body)
    config = INPUTS[operation]['config']
    result = await node(config).execute({})
    assert result == {'status': 'success', 'data': body}
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == 'api.firmable.com'
    assert request.headers['Authorization'] == 'Bearer ' + KEY
    if operation in native.LOOKUPS:
        path, parameter, field = native.LOOKUPS[operation]
        assert request.method == 'GET' and request.url.path == path
        assert dict(request.url.params) == {parameter: config[field]}
    elif operation == 'search_people':
        assert request.method == 'POST' and request.url.path == '/people/search'
        assert json.loads(request.content) == {'companyId': 'f000000117274', 'selectedCountry': 'AU',
            'position': 'Software Engineer', 'seniority': 'Senior', 'department': 'Engineering', 'from': '0', 'size': '10'}
    elif operation == 'get_tech_intelligence':
        assert request.url.path == '/tech-intel' and dict(request.url.params) == {'id': 'f000000740279'}
    else:
        assert request.url.path == '/filter-options' and not request.url.query


@pytest.mark.asyncio
async def test_empty_search_is_success_and_preserves_documented_shape(monkeypatch):
    body = {'success': False, 'totalPeople': 0}
    transport(monkeypatch, body)
    assert (await node(INPUTS['search_people']['config']).execute({}))['data'] == body


@pytest.mark.asyncio
async def test_query_serialization_and_pagination_are_explicit(monkeypatch):
    requests = transport(monkeypatch, {'markets': [], 'filters': []})
    await node({'operation': 'list_filter_options', 'identifiers': ['industry'], 'search': 'new south', 'offset': 20, 'level_one': 'l1:J'}).execute({})
    assert dict(requests[0].url.params) == {'identifiers': 'industry', 'search': 'new south', 'offset': '20', 'levelOne': 'l1:J'}
    requests = transport(monkeypatch, {'tech_intelligence': [], 'next_cursor': 'next'})
    await node({'operation': 'get_tech_intelligence', 'company_id': 'f000000740279', 'cursor': 'opaque+/=='}).execute({})
    assert dict(requests[0].url.params) == {'id': 'f000000740279', 'cursor': 'opaque+/=='}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_company_market_and_string_search_offset(monkeypatch):
    requests = transport(monkeypatch, {'id': 'f000000117274'})
    await node({'operation': 'enrich_company_by_id', 'company_id': 'f000000117274', 'country': 'NZ'}).execute({})
    assert dict(requests[0].url.params) == {'id': 'f000000117274', 'country': 'NZ'}
    requests = transport(monkeypatch, {'success': True, 'records': [], 'total': 0})
    await node({'operation': 'search_people', 'company_id': 'f000000117274', 'offset': 10, 'size': 20}).execute({})
    assert json.loads(requests[0].content) == {'companyId': 'f000000117274', 'from': '10', 'size': '20'}


@pytest.mark.parametrize('config', [
    {'operation': 'list_filter_options', 'search': 'new south'},
    {'operation': 'list_filter_options', 'identifiers': ['position'], 'offset': 0},
    {'operation': 'list_filter_options', 'identifiers': ['location'], 'level_one': 'l1:J'},
    {'operation': 'list_filter_options', 'identifiers': ['industry'], 'level_one': 'bogus'},
    {'operation': 'list_filter_options', 'identifiers': ['unknown']},
    {'operation': 'search_people', 'company_id': 'id', 'size': 0},
    {'operation': 'enrich_company_by_id', 'company_id': 'id', 'country': 'XX'},
    {'operation': 'enrich_person_by_id'},
])
def test_invalid_inputs_rejected_before_request(config):
    assert native.FirmableNode.validate_config({'config': config})['valid'] is False


@pytest.mark.parametrize('value', ['https://api.firmable.com', 'Bearer abc', 'abc\ndef'])
def test_manual_key_validation(value):
    with pytest.raises(ValidationError):
        native.FirmableAPIKeyCredential(api_key=value)


def test_manual_credential_has_default_tag_and_reachability_evidence():
    assert native.FirmableAPIKeyCredential(api_key='  ' + KEY + '  ').api_key == KEY
    assert native.FirmableAPIKeyCredential(api_key=KEY).credential_type == 'firmable_api_key'
    assert native.FirmableNode.connection_evidence.proves == 'reachability'
    assert native.FirmableNode.connection_evidence.operation == 'list_filter_options'


@pytest.mark.asyncio
@pytest.mark.parametrize('status,body', [(401, {'error': 'Invalid API key'}), (402, {'error': 'Not enough credits'}),
    (403, {'error': 'Tech Intelligence is not on the plan'}), (429, {'error': 'Rate limit exceeded'}),
    (200, {'error': 'unexpected error'})])
async def test_provider_errors_fail_with_verbatim_reason(monkeypatch, status, body):
    transport(monkeypatch, body, status)
    with pytest.raises(ValueError, match=body['error']):
        await node({'operation': 'list_filter_options'}).execute({})


@pytest.mark.asyncio
async def test_errors_redact_key_and_malformed_success_is_not_evidence(monkeypatch):
    transport(monkeypatch, {'error': 'Rejected ' + KEY}, 401)
    with pytest.raises(ValueError) as exc:
        await node({'operation': 'list_filter_options'}).execute({})
    assert KEY not in str(exc.value)
    transport(monkeypatch, {})
    with pytest.raises(ValueError, match='missing filters or markets'):
        await node({'operation': 'list_filter_options'}).execute({})
