"""Commusoft requests exercised at the HTTP boundary with documented input values.

These tests verify regional authentication, one route per operation, payload and
query serialization, and honest handling of rejected or empty responses offline.
"""
import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes import commusoft_node as native
from nodes.core.registry import NodeFactory

FIXTURES = json.loads((Path(__file__).parent / 'fixtures/commusoft/operations.json').read_text())
TOKEN = 'commusoft-synthetic-key-42'


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config, region='uk'):
    return NodeFactory.create_node(node_id='commusoft-fixture', node_type='automation-commusoft',
        node_data={'config': config, 'credentials': {'credential_type': 'commusoft_api_key',
            'api_key': TOKEN, 'region': region}})


def transport(monkeypatch, status=200, body=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs['follow_redirects'] is False
        assert kwargs['trust_env'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', FIXTURES, ids=lambda x:x['config']['operation'])
async def test_documented_operation_one_exact_request(monkeypatch, case):
    response = {'data': [{'id': 1447, 'name': 'Customer property'}],
        'pagination': {'hasMore': True, 'nextCursor': 1447, 'prevCursor': 1}}
    requests = transport(monkeypatch, body=response)
    result = await node(case['config']).execute({})
    assert result['status'] == 'success' and result['data'] == response
    assert len(requests) == 1
    request = requests[0]
    assert request.url.host == 'app.commusoft.co.uk'
    assert request.method == case['method'] and request.url.path == case['path']
    assert dict(request.url.params) == case['query']
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    if case['body'] is not None:
        actual = json.loads(request.content)
        expected = dict(case['body'])
        # ISO 8601 permits either millisecond or microsecond precision.
        for key in ('completeDateTime', 'startTime', 'endTime'):
            if key in expected:
                assert datetime.fromisoformat(actual.pop(key)) == datetime.fromisoformat(expected.pop(key))
        assert actual == expected
        assert request.headers['content-type'] == 'application/json'
    else:
        assert request.content == b''
    if case['config']['operation'] == 'list_jobs':
        assert request.headers['X-API-VERSION'] == '2.0'


@pytest.mark.asyncio
async def test_filters_and_cursor_are_one_page_without_following_links(monkeypatch):
    response = {'data': [], 'pagination': {'hasMore': True, 'nextCursor': 42},
        'links': {'next': 'https://evil.example/steal'}}
    requests = transport(monkeypatch, body=response)
    result = await node({'operation': 'list_opportunities', 'propertyID': 657,
        'createdOnDateTime_gte': '2026-03-02T10:42:00.123Z', 'limit': 20,
        'after': 21, 'includeCount': False}, region='us').execute({})
    assert result['data'] == response and len(requests) == 1
    assert requests[0].url.host == 'app.commusoft.us'
    query = dict(requests[0].url.params)
    assert datetime.fromisoformat(query.pop('createdOnDateTime[gte]')) == datetime.fromisoformat('2026-03-02T10:42:00.123Z')
    assert query == {'propertyID': '657', 'limit': '20',
        'after': '21', 'includeCount': 'false'}


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 302, 400, 401, 403, 404, 429, 500])
async def test_provider_rejections_are_errors_without_retries(monkeypatch, status):
    requests = transport(monkeypatch, status, {'error': {'message': 'API key rejected'}})
    result = await node({'operation': 'list_properties'}).execute({})
    assert result['status'] == 'error' and result['http_status'] == status
    assert 'API key rejected' in result['message'] and len(requests) == 1


@pytest.mark.asyncio
async def test_redacts_key_from_error_and_detects_error_envelope(monkeypatch):
    transport(monkeypatch, body={'error': {'message': 'Invalid ' + TOKEN}})
    result = await node({'operation': 'list_properties'}).execute({})
    assert result['status'] == 'error' and TOKEN not in str(result)


@pytest.mark.asyncio
async def test_empty_successful_delete(monkeypatch):
    requests = transport(monkeypatch, 204)
    result = await node({'operation': 'delete_appointment', 'appointmentID': '42'}).execute({})
    assert result['status'] == 'success' and result['data'] is None
    assert len(requests) == 1


@pytest.mark.parametrize('identifier', ['../1', '1?admin=true', '1#fragment', '1/contacts'])
def test_path_identifiers_cannot_change_routes(identifier):
    with pytest.raises(ValidationError):
        native.GetPropertyConfig(propertyID=identifier)


def test_manual_credential_default_and_host_allowlist():
    credential = native.CommusoftAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == 'commusoft_api_key' and credential.region == 'uk'
    with pytest.raises(ValidationError):
        native.CommusoftAPIKeyCredential(api_key=TOKEN, region='https://evil.example')
    with pytest.raises(ValidationError):
        native.CommusoftAPIKeyCredential(api_key='Bearer ' + TOKEN)


@pytest.mark.asyncio
async def test_empty_update_refused_before_http(monkeypatch):
    requests = transport(monkeypatch, body={})
    with pytest.raises(ValueError, match='at least one field'):
        await node({'operation': 'update_job', 'jobID': '42', 'payload': {}}).execute({})
    assert not requests


@pytest.mark.asyncio
async def test_connection_evidence_names_an_account_property(monkeypatch):
    from nodes.core.connection_evidence import collect_evidence
    requests = transport(monkeypatch, body={'data': [{'id': 1447,
        'addressLine1': '619 W Main', 'postcode': '87241-5785'}]})
    evidence = await collect_evidence(node_type='automation-commusoft',
        credential_data={'credential_type': 'commusoft_api_key', 'api_key': TOKEN, 'region': 'uk'},
        user_id='commusoft-fixture-user')
    assert evidence.reachable is True
    assert evidence.samples[0].label == '619 W Main'
    assert len(requests) == 1 and requests[0].method == 'GET'
