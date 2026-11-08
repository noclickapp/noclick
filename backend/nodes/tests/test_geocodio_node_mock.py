"""Geocodio native requests and provider-authored v2.1 response examples, offline."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import geocodio_node as native
from nodes.core.binary_output import BinaryOutput
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-geocodio-api-key-42"
EXAMPLES = json.loads((Path(__file__).parent / "fixtures/geocodio/provider_examples.json").read_text())["responses"]
CONFIGS = [
    {"operation": "geocode_address", "q": "1109 N Highland St, Arlington VA", "fields": ["timezone", "census"], "limit": 1},
    {"operation": "batch_geocode", "queries": {"customer1": "1109 N Highland St, Arlington VA"}},
    {"operation": "reverse_geocode", "q": "38.9002898,-76.9990361"},
    {"operation": "batch_reverse_geocode", "queries": ["38.9002898,-76.9990361"]},
    {"operation": "parse_address", "q": "1109 N Highland St, Arlington VA"},
    {"operation": "calculate_distance", "origin": "38.8977,-77.0365", "destinations": ["38.8895,-77.0353", "38.9072,-77.0369"], "mode": "driving", "min_distance": 0, "units": "km"},
    {"operation": "calculate_distance_matrix", "origins": ["38.8977,-77.0365,home"], "destinations": ["38.9072,-77.0369,capitol"], "calculation_type": "pairs", "mode": "straightline"},
    {"operation": "list_spreadsheets", "page": 2},
    {"operation": "upload_spreadsheet", "file": "Zip\n20003\n20001", "filename": "file.csv", "direction": "forward", "format": "{{A}}", "fields": ["timezone"]},
    {"operation": "get_spreadsheet", "list_id": "149"},
    {"operation": "download_spreadsheet", "list_id": "149"},
    {"operation": "delete_spreadsheet", "list_id": "149"},
]


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, creds=None):
    return NodeFactory.create_node(node_id="geocodio-fixture", node_type="automation-geocodio", node_data={
        "config": config, "credentials": creds or {"credential_type": "geocodio_api_key", "api_key": TOKEN}})


def transport(monkeypatch, reply):
    requests = []
    def respond(request):
        requests.append(request)
        return reply(request)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("config", CONFIGS, ids=lambda c: c['operation'])
async def test_geocodio_one_request_per_operation_provider_examples(monkeypatch, config):
    method, route = native.ROUTES[config['operation']]
    payload = EXAMPLES.get(f"{method} {route}", {"success": True})
    download = config['operation'] == 'download_spreadsheet'
    requests = transport(monkeypatch, lambda _: httpx.Response(200, content=b"address,lat,lng\na,38,-77\n", headers={"content-type": "text/csv"}) if download else httpx.Response(200, json=payload))
    result = await node(config).execute({})
    assert len(requests) == 1
    req = requests[0]
    assert req.method == method and req.url.host == "api.geocod.io"
    assert req.url.path == '/v2.1' + route.replace('{id}', config.get('list_id', ''))
    assert req.url.params['api_key'] == TOKEN
    assert result['status'] == 'success'
    assert TOKEN not in str(result)
    if download:
        assert isinstance(result['file'], BinaryOutput)
        assert result['file'].data.startswith(b'address,lat,lng')
    else:
        assert result['data'] == payload
    if config['operation'].startswith('batch_'):
        assert json.loads(req.content) == config['queries']
    if config['operation'] == 'calculate_distance':
        assert req.url.params.get_list('destinations[]') == config['destinations']
        assert req.url.params['min_distance'] == '0.0'
    if config['operation'] == 'calculate_distance_matrix':
        assert json.loads(req.content) == {k: v for k,v in config.items() if k != 'operation'}
        assert set(req.url.params) == {'api_key'}
    if config['operation'] == 'upload_spreadsheet':
        assert json.loads(req.content) == {k: v for k,v in config.items() if k not in {'operation', 'fields'}}
        assert req.headers['content-type'] == 'application/json'
    if config.get('fields'):
        assert req.url.params['fields'] == ','.join(config['fields'])


@pytest.mark.asyncio
async def test_geocodio_page_preserves_pagination_without_following_urls(monkeypatch):
    payload = EXAMPLES['GET /lists']
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json=payload))
    result = await node({'operation': 'list_spreadsheets'}).execute({})
    assert result['data'] == payload and len(requests) == 1
    assert requests[0].url.params['page'] == '1'
    from nodes.core.connection_evidence import _rows_from_operation
    assert _rows_from_operation(result) == payload['data']


@pytest.mark.asyncio
async def test_geocodio_skip_geocoding_and_component_address(monkeypatch):
    requests = transport(monkeypatch, lambda _: httpx.Response(200, json={'results': []}))
    await node({'operation':'reverse_geocode','q':'38.9002898,-76.9990361','skip_geocoding':True,'fields':['timezone']}).execute({})
    assert requests[0].url.params['skipGeocoding'] == '1'
    await node({'operation':'geocode_address','street':'1109 N Highland St','city':'Arlington','state_province':'VA'}).execute({})
    assert requests[1].url.params['state_province'] == 'VA' and 'q' not in requests[1].url.params


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302, 403, 422, 429, 500])
async def test_geocodio_rejection_is_redacted_and_never_retried(monkeypatch, status):
    requests = transport(monkeypatch, lambda _: httpx.Response(status, json={'error':f'Invalid key {TOKEN}'}, headers={'location':'https://other.example/'}))
    with pytest.raises(ValueError) as exc:
        await node(CONFIGS[8]).execute({})
    assert TOKEN not in str(exc.value) and str(status) in str(exc.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_geocodio_timeout_never_leaks_authenticated_url_or_retries_write(monkeypatch):
    def fail(req):
        raise httpx.ReadTimeout(str(req.url), request=req)
    requests = transport(monkeypatch, fail)
    with pytest.raises(ValueError) as exc:
        await node(CONFIGS[8]).execute({})
    assert TOKEN not in str(exc.value) and len(requests) == 1


@pytest.mark.asyncio
async def test_geocodio_rejects_error_envelope_and_invalid_json(monkeypatch):
    transport(monkeypatch, lambda _: httpx.Response(200, json={'error':'Not allowed'}))
    with pytest.raises(ValueError, match='Not allowed'):
        await node(CONFIGS[7]).execute({})
    transport(monkeypatch, lambda _: httpx.Response(200, text='<html>Bad gateway</html>'))
    with pytest.raises(ValueError, match='invalid JSON'):
        await node(CONFIGS[7]).execute({})


@pytest.mark.parametrize('config', [
    {'operation':'geocode_address'},
    {'operation':'reverse_geocode','q':'38,-77','skip_geocoding':True},
    {'operation':'batch_geocode','queries':[]},
    {'operation':'batch_geocode','queries':['a']*5001,'fields':['timezone']},
    {'operation':'calculate_distance_matrix','origins':['a'],'destinations':['b','c'],'calculation_type':'pairs'},
    {'operation':'calculate_distance_matrix','origins':['a'],'destinations':['b'],'calculation_type':'pairs','max_distance':1},
    {'operation':'get_spreadsheet','list_id':'../elsewhere'},
    {'operation':'upload_spreadsheet','file':'a','filename':'/tmp/a.csv','format':'{{A}}'},
])
def test_geocodio_invalid_input_refused(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


def test_geocodio_manual_credential_default_and_secret_validation():
    credential = native.GeocodioAPIKeyCredential(api_key='  '+TOKEN+'\n')
    assert credential.credential_type == 'geocodio_api_key' and credential.api_key == TOKEN
    for key in ['https://api.geocod.io/key', '<your key>', 'some key']:
        with pytest.raises(ValueError):
            native.GeocodioAPIKeyCredential(api_key=key)
