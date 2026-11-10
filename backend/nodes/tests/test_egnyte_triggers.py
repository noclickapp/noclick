"""Webhook lifecycle and deliveries from Egnyte's published documentation."""
import copy
import json
from pathlib import Path

import httpx
import pytest

from nodes import egnyte_node as egnyte
from nodes.tests.test_egnyte_node_mock import AUTH, transport  # noqa: F401

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/egnyte/file_uploaded.json').read_text())


async def test_register_verify_and_unregister(transport):
    transport[1].extend([
        httpx.Response(201, json={"webhookId": "c9ac0519-284a-4bee-9574-30ae7891e5dc", "expires": 2100000000, "status": "enabled"}),
        httpx.Response(204),
    ])
    config = {"operation": "on_file_uploaded", "path": "/Shared/Documents/Invoices,/Shared/Documents/Samples"}
    extra = await egnyte.EgnyteNode._register_external_webhook(
        webhook_url="https://example.com/webhook", credential=AUTH, config=config, node_id="test")
    request = transport[0][0]
    body = json.loads(request.content)
    assert request.method == "POST" and request.url.path == "/pubapi/v1/webhooks"
    assert request.headers['authorization'] == 'Bearer synthetic-access'
    assert body == {"url": "https://example.com/webhook", "eventType": ["fs:add_file"],
                    "path": config['path'], "authHeader": f"Bearer {extra['signing_secret']}"}
    delivery = json.dumps(FIXTURE['body']).encode()
    verify = egnyte.EgnyteNode.verify_webhook_signature
    assert verify(delivery, {"Authorization": body['authHeader']}, extra)
    assert verify(delivery, {"authorization": body['authHeader']}, extra)
    assert not verify(delivery, {}, extra)
    assert not verify(delivery, {"Authorization": "Bearer wrong"}, extra)
    assert not verify(delivery, {"Authorization": body['authHeader']}, {})
    assert not verify(delivery, {"Authorization": extra['signing_secret']}, extra)
    # Egnyte authenticates a header value, not a body digest.
    assert verify(delivery + b' ', {"Authorization": body['authHeader']}, extra)
    await egnyte.EgnyteNode._unregister_external_webhook(credential=AUTH, config=extra, node_id="test")
    assert transport[0][1].method == 'DELETE'
    assert transport[0][1].url.path == '/pubapi/v1/webhooks/c9ac0519-284a-4bee-9574-30ae7891e5dc'


async def test_registration_default_scope_and_failures(transport):
    transport[1].append(httpx.Response(403))
    with pytest.raises(httpx.HTTPStatusError):
        await egnyte.EgnyteNode._register_external_webhook(
            webhook_url='https://example.com/webhook', credential=AUTH,
            config={'operation': 'on_file_uploaded'}, node_id='test')
    assert 'path' not in json.loads(transport[0][0].content)
    transport[1].append(httpx.Response(201, json={}))
    with pytest.raises(ValueError, match='webhook ID'):
        await egnyte.EgnyteNode._register_external_webhook(
            webhook_url='https://example.com/webhook', credential=AUTH,
            config={'operation': 'on_file_uploaded'}, node_id='test')


async def test_cleanup_already_removed_and_missing_credential(transport):
    config = {'external_webhook_id': 'c9ac0519-284a-4bee-9574-30ae7891e5dc'}
    transport[1].append(httpx.Response(404))
    await egnyte.EgnyteNode._unregister_external_webhook(credential=AUTH, config=config, node_id='test')
    with pytest.raises(ValueError, match='Connect Egnyte'):
        await egnyte.EgnyteNode._unregister_external_webhook(credential=None, config=config, node_id='test')


def test_documented_payload_and_agent_turn():
    payload = copy.deepcopy(FIXTURE['body'])
    config = {'operation': 'on_file_uploaded'}
    node = egnyte.EgnyteNode
    assert node.filter_trigger_payload(payload, config)
    output = node.resolve_trigger_payload(payload, config)
    assert output == {'events': payload['data']}
    event = node.resolve_agent_event(output)
    assert 'Egnyte file uploaded by ...' in event['text']
    assert '1710000000000' in event['text']
    assert event['conversation_key'] == '...:...'
    for malformed in ({'data': []}, {'data': [{}]}, {'data': {}}, {}):
        assert not node.filter_trigger_payload(malformed, config)
    payload['data'][0]['eventType'] = 'fs:add_folder'
    assert not node.filter_trigger_payload(payload, config)


@pytest.mark.parametrize('path', ['/Shared/../secret', '/Shared,,/Private', 'Shared/Documents', ','.join(['/Shared'] * 101)])
def test_invalid_registration_scope(path):
    with pytest.raises(ValueError):
        egnyte.OnFileUploaded(path=path)


def test_registration_fingerprint_only_tracks_paths():
    node = egnyte.EgnyteNode
    assert node.registration_fingerprint_fields({'operation': 'on_file_uploaded', 'path': '/Shared', 'label': 'New label'}) == {'path': '/Shared'}
    assert node.registration_fingerprint_fields({'operation': 'on_file_uploaded', 'path': '  '}) == {'path': None}


def test_trigger_scope_and_metadata():
    assert egnyte.EGNYTE_SCOPES.require('on_file_uploaded').scopes == ('Egnyte.webhooks',)
    operation = egnyte.OnFileUploaded.model_json_schema()['properties']['operation']
    assert operation['x-is-trigger'] is True
    assert egnyte.OnFileUploaded.model_json_schema()['x-requires-webhook'] is True
