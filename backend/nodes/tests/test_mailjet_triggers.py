"""Exercise Mailjet email triggers with the provider's published event examples.
The delivery credentials and API lifecycle are tested separately from event routing.
"""
import base64
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from nodes import mailjet_node as mailjet
from nodes.tests.test_mailjet_node_integration import CREDS, mock_api, node

EVENTS = json.loads((Path(__file__).parent / 'fixtures/mailjet/events.json').read_text())


@pytest.mark.asyncio
@pytest.mark.parametrize('operation', mailjet.MAILJET_TRIGGER_EVENTS)
async def test_registration_auth_delivery_and_cleanup(monkeypatch, operation):
    event, _ = mailjet.MAILJET_TRIGGER_EVENTS[operation]
    requests = []
    registration = {}

    def handler(request):
        requests.append(request)
        if request.method == 'DELETE':
            assert request.url.path == '/v3/REST/eventcallbackurl/987654'
            return httpx.Response(204)
        assert request.method == 'POST'
        assert request.url.path == '/v3/REST/eventcallbackurl'
        registration.update(json.loads(request.content))
        assert registration['EventType'] == event
        assert registration['Version'] == 1
        assert registration['Status'] == 'alive'
        assert registration['IsBackup'] is False
        return httpx.Response(201, json={'Count': 1, 'Total': 1, 'Data': [{'ID': 987654}]})

    mock_api(monkeypatch, handler)
    config = {'operation': operation}
    extra = await mailjet.MailjetNode._register_external_webhook(
        webhook_url='https://test.hooks.example.test/webhook/example', credential=CREDS,
        config=config, node_id='test')
    url = urlsplit(registration['Url'])
    assert url.hostname == 'test.hooks.example.test'
    assert url.path == '/webhook/example'
    assert url.username == 'noclick'
    assert url.password == extra['signing_secret']
    assert url.password not in CREDS.values()
    config.update(extra)
    parsed = mailjet.MailjetNodeConfig.model_validate({'config': config, 'credentials': CREDS})
    assert parsed.config.signing_secret == url.password
    authorization = 'Basic ' + base64.b64encode(f'noclick:{url.password}'.encode()).decode()
    payload = EVENTS[event]['body']
    body = json.dumps(payload).encode()
    assert mailjet.MailjetNode.verify_webhook_signature(body, {'Authorization': authorization}, config)
    assert not mailjet.MailjetNode.verify_webhook_signature(body, {}, config)
    assert not mailjet.MailjetNode.verify_webhook_signature(body, {'Authorization': authorization}, {})
    for invalid in ['Basic !!!', 'Bearer secret', 'Basic ' + base64.b64encode(b'noclick:wrong').decode(), '']:
        assert not mailjet.MailjetNode.verify_webhook_signature(body, {'authorization': invalid}, config)
    for name, example in EVENTS.items():
        assert mailjet.MailjetNode.filter_trigger_payload(example['body'], config) is (name == event)
    output = mailjet.MailjetNode.resolve_trigger_payload(payload, config)
    turn = mailjet.MailjetNode.resolve_agent_event(output)
    assert payload['email'] in turn['text']
    assert str(payload['MessageID']) in turn['text']
    assert str(payload['mj_contact_id']) in turn['text']
    assert turn['conversation_key'] == str(payload['MessageID'])
    if event == 'click':
        assert payload['url'] in turn['text']
    if event == 'bounce':
        assert payload['comment'] in turn['text']
    if event == 'unsub':
        assert f"Contact list ID: {payload['mj_list_id']}" in turn['text']
    assert (await node(operation).execute({}))['status'] == 'no_event'
    await mailjet.MailjetNode._unregister_external_webhook(credential=CREDS, config=config, node_id='test')
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_registration_and_cleanup_failures_are_visible(monkeypatch):
    mock_api(monkeypatch, lambda request: httpx.Response(401, json={'ErrorMessage': 'secret-test'}))
    with pytest.raises(ValueError, match='HTTP 401'):
        await mailjet.MailjetNode._register_external_webhook(webhook_url='https://test.hooks.example.test/webhook/test',
            credential=CREDS, config={'operation': 'on_email_sent'}, node_id='test')
    with pytest.raises(ValueError, match='HTTP 401'):
        await mailjet.MailjetNode._unregister_external_webhook(credential=CREDS,
            config={'external_webhook_id': '987654'}, node_id='test')
    mock_api(monkeypatch, lambda request: httpx.Response(404, json={}))
    await mailjet.MailjetNode._unregister_external_webhook(credential=CREDS,
        config={'external_webhook_id': '987654'}, node_id='test')
    mock_api(monkeypatch, lambda request: httpx.Response(201, json={'Count': 0, 'Data': [], 'Total': 0}))
    with pytest.raises(ValueError, match='webhook ID'):
        await mailjet.MailjetNode._register_external_webhook(webhook_url='https://test.hooks.example.test/webhook/test',
            credential=CREDS, config={'operation': 'on_email_sent'}, node_id='test')
