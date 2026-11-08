"""Pingdom request boundaries and provider response handling."""
import json
from unittest.mock import AsyncMock
import httpx
import pytest
from pydantic import TypeAdapter, ValidationError
from nodes.pingdom_node import PingdomNode, PingdomConfig, PingdomAPITokenCredential, request_for

@pytest.mark.parametrize('operation,fields,method,path,expected', [
    ('list_checks', {'offset': 100}, 'GET', '/checks', {'offset': 100, 'include_tags': 'true'}),
    ('create_check', {'name': 'Website', 'host': 'example.com'}, 'POST', '/checks', {'type': 'http', 'url': '/', 'encryption': True}),
    ('update_check', {'check_id': 123, 'paused': False, 'tags': []}, 'PUT', '/checks/123', {'paused': False, 'tags': []}),
    ('delete_check', {'check_id': 123}, 'DELETE', '/checks/123', {}),
    ('create_maintenance', {'description': 'Deploy', 'from_time': 1, 'to_time': 2000000000, 'uptimeids': [123]}, 'POST', '/maintenance', {'from': 1, 'to': 2000000000, 'uptimeids': [123]}),
    ('update_maintenance', {'maintenance_id': 10, 'description': 'Deploy', 'from_time': 1, 'to_time': 2000000000}, 'PUT', '/maintenance/10', {'description': 'Deploy'}),
    ('list_results', {'check_id': 123, 'from_time': 100, 'to_time': 200}, 'GET', '/results/123', {'from': 100, 'to': 200}),
    ('get_contact', {'contact_id': 12}, 'GET', '/alerting/contacts/12', {}),
])
def test_wire_mapping(operation, fields, method, path, expected):
    config = TypeAdapter(PingdomConfig).validate_python({'operation': operation, **fields})
    actual_method, actual_path, _, values = request_for(config)
    assert (actual_method, actual_path) == (method, path)
    assert all(values[k] == v for k, v in expected.items())
    assert not {'operation', 'check_id', 'maintenance_id', 'contact_id', 'from_time', 'to_time'} & values.keys()

@pytest.mark.parametrize('config', [
    {'operation': 'get_check', 'check_id': '../checks'},
    {'operation': 'update_check', 'check_id': 123},
    {'operation': 'get_average', 'check_id': 123, 'from_time': 200, 'to_time': 100},
    {'operation': 'create_check', 'name': 'x', 'host': 'https://example.com'},
    {'operation': 'create_check', 'name': 'x', 'host': 'example.com', 'url': '//evil.com'},
    {'operation': 'create_maintenance', 'description': 'Deploy', 'from_time': 100, 'to_time': 50},
])
def test_invalid_inputs(config):
    with pytest.raises(ValidationError):
        TypeAdapter(PingdomConfig).validate_python(config)

@pytest.mark.parametrize('token', ['https://example.com/token', 'Bearer abc', 'abc\nxyz'])
def test_invalid_token(token):
    with pytest.raises((ValidationError, ValueError)):
        PingdomAPITokenCredential(api_token=token)

async def run(monkeypatch, config, status, body, redirect=None):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json=body, headers={'location': redirect} if redirect else {})
    original = httpx.AsyncClient
    monkeypatch.setattr('nodes.pingdom_node.httpx.AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs))
    node = PingdomNode.__new__(PingdomNode)
    node._config = PingdomNode.parse_config({'config': config, 'credentials': {'credential_type': 'pingdom_api_token', 'api_token': 'secret-pingdom-token'}})
    node.emit = AsyncMock()
    result = await node.execute({})
    node.emit.assert_awaited_once_with(result)
    assert len(calls) == 1
    assert calls[0].headers['authorization'] == 'Bearer secret-pingdom-token'
    return result, calls[0]

@pytest.mark.asyncio
async def test_connection_evidence(monkeypatch):
    result, _ = await run(monkeypatch, {'operation': 'list_checks'}, 200, {'checks': [{'id': 100, 'name': 'My site'}]})
    assert result['items'][0]['name'] == 'My site'
    assert PingdomNode.connection_evidence.operation == 'list_checks'

@pytest.mark.asyncio
async def test_error_envelope_is_not_success_and_redacts(monkeypatch):
    result, _ = await run(monkeypatch, {'operation': 'get_credits'}, 200, {'error': {'errormessage': 'Rejected secret-pingdom-token'}})
    assert not result['success']
    assert result['message'] == 'Rejected [redacted]'

@pytest.mark.asyncio
async def test_write_acknowledgement(monkeypatch):
    result, request = await run(monkeypatch, {'operation': 'update_check', 'check_id': 123, 'paused': False}, 200, {'message': 'Modification of check was successful!'})
    assert json.loads(request.content) == {'paused': False}
    assert result['acknowledged'] and not result['state_verified']

@pytest.mark.asyncio
async def test_redirect_is_not_followed(monkeypatch):
    result, _ = await run(monkeypatch, {'operation': 'get_credits'}, 302, {}, 'https://evil.example')
    assert not result['success']

@pytest.mark.asyncio
async def test_absent_optional_attributes(monkeypatch):
    result, _ = await run(monkeypatch, {'operation': 'get_check', 'check_id': 123}, 200, {})
    assert result['data'] == {}
