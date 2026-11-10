"""CyCAT wire regression tests and provider-authored JSON preservation.

Four payloads come verbatim from https://www.cycat.org/services/ (the copied
examples include their source URL). Other responses exercise untyped JSON,
not an asserted provider schema. No live writes or credentials are used.
"""
import json
from pathlib import Path

import httpx
import pytest

from nodes import cycat_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/cycat/requests.json').read_text())


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, **kwargs):
    return NodeFactory.create_node(node_id='cycat-test', node_type='automation-cycat', node_data={'config': config, **kwargs})


def transport(monkeypatch, body, status=200, raw=None):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, **({'content': raw} if raw is not None else {'json': body}))

    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', FIXTURES, ids=lambda c: c['config']['operation'])
async def test_cycat_exact_wire_and_json_preservation(monkeypatch, case):
    requests = transport(monkeypatch, case['response'])
    result = await node(case['config']).execute({})
    assert result == {'status': 'success', 'operation': case['config']['operation'], 'data': case['response']}
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case['method']
    assert str(request.url) == native.BASE + case['path']
    assert not request.url.query
    assert 'authorization' not in request.headers and 'x-api-key' not in request.headers
    assert request.headers['accept'] == 'application/json'
    assert (json.loads(request.content) if request.content else None) == case['config'].get('proposal')


@pytest.mark.asyncio
async def test_cycat_path_values_are_encoded_as_data(monkeypatch):
    requests = transport(monkeypatch, [])
    await node({'operation': 'search', 'searchquery': 'APT33 ?#&%'}).execute({})
    assert str(requests[0].url) == native.BASE + '/search/APT33%20%3F%23%26%25'
    assert not requests[0].url.query


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 302, 400, 401, 403, 404, 429, 500, 503])
async def test_cycat_http_failure_never_claims_success(monkeypatch, status):
    requests = transport(monkeypatch, {'message': 'Provider rejection'}, status)
    with pytest.raises(httpx.HTTPStatusError):
        await node({'operation': 'get_info'}).execute({})
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_cycat_undocumented_success_status_and_non_json_rejected(monkeypatch):
    transport(monkeypatch, {}, 202)
    with pytest.raises(ValueError, match='documented success'):
        await node({'operation': 'get_info'}).execute({})
    transport(monkeypatch, None, raw=b'<html>unavailable</html>')
    with pytest.raises(ValueError):
        await node({'operation': 'get_info'}).execute({})


@pytest.mark.asyncio
async def test_cycat_write_timeout_propagates_without_retry(monkeypatch):
    requests = []

    def timeout(request):
        requests.append(request)
        raise httpx.ReadTimeout('No response after proposal submission', request=request)

    monkeypatch.setattr(native, 'guarded_async_client', lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(timeout), **kw))
    with pytest.raises(httpx.ReadTimeout):
        await node({'operation': 'propose_resource', 'proposal': {'test': 'data'}}).execute({})
    assert len(requests) == 1


@pytest.mark.parametrize('config', [
    {'operation': 'lookup', 'uuid': '../info'},
    {'operation': 'lookup'},
    {'operation': 'list_projects', 'start': 10, 'end': 1},
    {'operation': 'list_publishers', 'start': -1},
    {'operation': 'list_publishers', 'end': 1000},
    {'operation': 'find_namespace_uuids', 'namespace': '..', 'namespaceid': 'id'},
    {'operation': 'list_namespace_ids', 'namespace': 'x/y'},
    {'operation': 'search', 'searchquery': ''},
    {'operation': 'search', 'searchquery': 'x\ny'},
    {'operation': 'search', 'searchquery': '..'},
    {'operation': 'propose_resource'},
    {'operation': 'propose_resource', 'proposal': 'text'},
    {'operation': 'get_info', 'base_url': 'https://example.org'},
    {'operation': 'delete_resource'},
])
def test_cycat_invalid_configs_rejected(config):
    with pytest.raises(ValueError):
        native.CycatNode.parse_config({'config': config})


def test_cycat_public_api_schema_and_reachability():
    schema = native.CycatFullConfig.model_json_schema()
    assert len(schema['properties']['config']['discriminator']['mapping']) == 14
    assert 'credential_type' not in str(schema)
    assert native.CycatNode.validate_config({'config': {'operation': 'get_info'}, 'credentials': {}})['valid']
    assert native.CycatNode.connection_evidence.operation == 'get_info'
    assert native.CycatNode.connection_evidence.proves == 'reachability'
    assert not any(d.get('x-is-trigger') for d in schema.get('$defs', {}).values())
