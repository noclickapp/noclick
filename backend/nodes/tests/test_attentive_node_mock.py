"""Synthetic transport regressions; input values come from Attentive's OpenAPI examples."""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from nodes import attentive_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

TOKEN = 'synthetic-attentive-private-key'
CASES = json.loads((Path(__file__).parent / 'fixtures/attentive/requests.json').read_text())['cases']


def node(config):
    return NodeFactory.create_node(node_id='attentive-test', node_type='automation-attentive', node_data={
        'config': config, 'credentials': {'credential_type': 'attentive_api_key', 'api_key': TOKEN},
    })


def transport(monkeypatch, status, body=None):
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(status, json=body) if body is not None else httpx.Response(status)
    def client(**kwargs):
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, 'guarded_async_client', client)
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize('case', CASES, ids=lambda c: c['operation'])
async def test_exact_provider_routes_and_payloads(monkeypatch, case):
    requests = transport(monkeypatch, case['status'], case['response'])
    result = await node(case['config']).execute({})
    assert result['status'] == 'success' and result['http_status'] == case['status']
    assert len(requests) == 1
    request = requests[0]
    assert request.method == case['method'] and request.url.path == case['path']
    assert request.url.host == 'api.attentivemobile.com'
    assert request.headers['Authorization'] == 'Bearer ' + TOKEN
    assert (json.loads(request.content) if request.content else None) == case['body']
    if case['operation'] == 'get_custom_attributes':
        assert '%2B13115552368' in str(request.url)
    if case['operation'] == 'list_segments':
        assert dict(request.url.params) == {'limit': '20'}
        assert result['data']['cursor'] == 'next-page' and result['data']['hasMore'] is True
    assert TOKEN not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [301, 401, 403, 404, 429, 500])
async def test_rejections_are_errors_and_preserve_redacted_provider_reason(monkeypatch, status):
    requests = transport(monkeypatch, status, {'message': 'Rejected ' + TOKEN})
    result = await node({'operation': 'get_me'}).execute({})
    assert result == {'status': 'error', 'http_status': status, 'error': 'Rejected [redacted]'}
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('body', [None, {}, {'companyName': True}, {'success': False}, {'errors': ['bad']}, [], 'html'])
async def test_connection_cannot_succeed_without_identity(monkeypatch, body):
    transport(monkeypatch, 200, body)
    assert (await node({'operation': 'get_me'}).execute({}))['status'] == 'error'


@pytest.mark.asyncio
async def test_encoded_external_id_and_cursor_are_data(monkeypatch):
    requests = transport(monkeypatch, 200, {'externalId': 'owned'})
    await node({'operation': 'get_segment', 'externalId': 'owned/part?query#fragment'}).execute({})
    assert requests[0].url.raw_path == b'/v2/segments/external/owned%2Fpart%3Fquery%23fragment'
    requests = transport(monkeypatch, 200, {'segments': [], 'hasMore': False, 'cursor': None})
    await node({'operation': 'list_segments', 'cursor': 'opaque+&=', 'limit': 5}).execute({})
    assert dict(requests[0].url.params) == {'cursor': 'opaque+&=', 'limit': '5'}


@pytest.mark.asyncio
async def test_accepted_subscription_does_not_claim_completion(monkeypatch):
    transport(monkeypatch, 202, {'newSubscriptions': [{'type': 'MARKETING', 'channel': 'TEXT'}]})
    result = await node({'operation': 'subscribe_user', 'user': {'phone': '+13115552368'}, 'signUpSourceId': 'owned-unit'}).execute({})
    assert result['accepted'] is True and 'completed' not in result


@pytest.mark.parametrize('config', [
    {'operation': 'get_custom_attributes'},
    {'operation': 'get_custom_attributes', 'phone': '+13115552368', 'email': 'test@gmail.com'},
    {'operation': 'subscribe_user', 'user': {'phone': '+13115552368'}},
    {'operation': 'subscribe_user', 'user': {}, 'signUpSourceId': 'owned-unit'},
    {'operation': 'send_custom_event', 'type': 'Bad, Event', 'user': {'email': 'test@gmail.com'}},
    {'operation': 'update_segment', 'externalId': 'owned'},
    {'operation': 'set_custom_attributes', 'user': {'email': 'test@gmail.com'}, 'properties': {'cities': ['Paris']}},
    {'operation': 'record_purchase', 'items': [{'productId': 'p'}], 'user': {'phone': '123'}},
    {'operation': 'list_segments', 'limit': 1001},
])
def test_documented_input_requirements(config):
    with pytest.raises((ValidationError, ValueError)):
        node(config)


def test_registration_manual_credential_and_evidence():
    assert NODE_REGISTRY['automation-attentive'] is native.AttentiveNode
    credential = native.AttentiveAPIKeyCredential(api_key=TOKEN)
    assert credential.credential_type == 'attentive_api_key'
    assert native.AttentiveNode.connection_evidence.identity_operation == 'get_me'
    assert set(native.AttentiveAPIKeyCredential.model_fields) == {'credential_type', 'api_key'}


def test_canvas_metadata_and_json_editor_inputs():
    instance = node({"operation": "send_custom_event", "type": "Order Shipped",
        "user": '{"phone":"+13115552368"}', "properties": '{"order":"123"}',
        "label": "Owned event", "disabled": False, "credentialIds": {"attentive_api_key": "saved-id"}})
    assert instance.config.config.user.phone == "+13115552368"
    assert instance.config.config.properties == {"order": "123"}
    assert "credentialIds" not in instance.config.config.model_dump()
    with pytest.raises(ValueError, match="valid JSON"):
        node({"operation": "send_custom_event", "type": "Order Shipped", "user": "invalid json"})
    with pytest.raises(ValueError):
        node({"operation": "send_custom_event", "type": "Order Shipped",
            "user": {"email": "test@gmail.com"}, "occurredAt": "2026-11-09T12:00:00"})
