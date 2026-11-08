"""Request wire and error handling tests, independent of a live Bolna account."""
import httpx
import pytest
from nodes.bolna_node import BolnaNode, BolnaAPIKeyCredential
from nodes.core.registry import NodeFactory


def node(config):
    return NodeFactory.create_node(node_id="bolna-test", node_type="automation-bolna", node_data={"config": config,
        "credentials": {"credential_type": "bolna_api_key", "api_key": "bolna-test-secret-123"}})


@pytest.mark.asyncio
async def test_call_wire(monkeypatch):
    async def request(self, method, url, **kwargs):
        assert method == 'POST' and url == 'https://api.bolna.ai/call'
        assert kwargs['headers']['Authorization'] == 'Bearer bolna-test-secret-123'
        assert kwargs['json'] == {'agent_id': '123e4567-e89b-12d3-a456-426655440000', 'recipient_phone_number': '+10123456789', 'user_data': {'name': 'Alex'}}
        return httpx.Response(200, json={'execution_id': 'abc', 'status': 'queued'})
    monkeypatch.setattr(httpx.AsyncClient, 'request', request)
    result = await node({'operation': 'make_call', 'agent_id': '123e4567-e89b-12d3-a456-426655440000', 'recipient_phone_number': '+10123456789', 'user_data': {'name': 'Alex'}}).execute({})
    assert result['data']['status'] == 'queued'


@pytest.mark.asyncio
async def test_execution_range_wire(monkeypatch):
    async def request(self, method, url, **kwargs):
        assert method == 'GET' and url.endswith('/v2/agent/abc/executions')
        assert kwargs['params'] == {'from': '2026-11-01T00:00:00Z', 'to': '2026-11-02T00:00:00Z', 'page_number': 2}
        return httpx.Response(200, json={'executions': [], 'page_number': 2})
    monkeypatch.setattr(httpx.AsyncClient, 'request', request)
    assert (await node({'operation': 'list_executions', 'agent_id': 'abc', 'from_time': '2026-11-01T00:00:00Z', 'to_time': '2026-11-02T00:00:00Z', 'page_number': 2}).execute({}))['data']['page_number'] == 2


@pytest.mark.asyncio
async def test_rejection_and_redaction(monkeypatch):
    async def request(self, method, url, **kwargs):
        return httpx.Response(401, text='Invalid bolna-test-secret-123')
    monkeypatch.setattr(httpx.AsyncClient, 'request', request)
    with pytest.raises(ValueError, match=r'Bolna HTTP 401: Invalid \[redacted\]'):
        await node({'operation': 'get_account'}).execute({})


@pytest.mark.parametrize('config', [
    {'operation': 'get_agent', 'agent_id': '../other'},
    {'operation': 'make_call', 'agent_id': 'abc', 'recipient_phone_number': '123'},
    {'operation': 'list_executions', 'agent_id': 'abc', 'from_time': '2026-11-01T00:00:00Z', 'to_time': '2026-11-10T00:00:00Z'},
])
def test_invalid_configs(config):
    assert not BolnaNode.validate_config({'config': config})['valid']


def test_manual_credential_defaults():
    assert BolnaAPIKeyCredential(api_key='real-bolna-key').credential_type == 'bolna_api_key'


@pytest.mark.asyncio
async def test_documented_agent_creation(monkeypatch):
    import json
    from pathlib import Path
    example = json.loads((Path(__file__).parent / 'fixtures/bolna/create_agent.json').read_text())
    async def request(self, method, url, **kwargs):
        assert (method, url) == ('POST', 'https://api.bolna.ai/v2/agent')
        assert kwargs['json'] == example['request']
        return httpx.Response(201, json=example['response'])
    monkeypatch.setattr(httpx.AsyncClient, 'request', request)
    assert (await node({'operation': 'create_agent', **example['request']}).execute({}))['data'] == example['response']
