"""Exercise real Nextcloud HTTP dispatch and trigger lifecycle with documented shapes."""
import base64
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes.nextcloud_node import (
    EVENTS, FILES, WEBHOOKS, NextcloudAppPasswordCredential,
    NextcloudNode, TemplateField,
)

CREDENTIAL = {"credential_type": "nextcloud_app_password", "server_url": "https://cloud.example.com/nextcloud",
              "username": "admin", "app_password": "a-real-test-app-password"}


def envelope(data):
    return {"ocs": {"meta": {"status": "ok", "statuscode": 200}, "data": data}}


@pytest.fixture
def transport(monkeypatch):
    requests = []
    responses = []

    async def handle(request):
        requests.append(request)
        return responses.pop(0)

    from nodes import nextcloud_node
    monkeypatch.setattr(nextcloud_node, "guarded_async_client", lambda **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(handle), **kw))
    return requests, responses


CASES = [
    ({"operation": "list_folders", "path": "/Documents", "depth": 2, "withParents": True}, "GET", "/folder-tree", {}, {"path": "/Documents", "depth": "2", "withParents": "true"}),
    ({"operation": "list_templates"}, "GET", "/templates", {}, {}),
    ({"operation": "get_template_fields", "fileId": 42}, "GET", "/templates/fields/42", {}, {}),
    ({"operation": "create_from_template", "filePath": "/report.odt", "templatePath": "/Templates/report.odt"}, "POST", "/templates/create", {"filePath": "/report.odt", "templatePath": "/Templates/report.odt", "templateType": "user", "templateFields": []}, {}),
    ({"operation": "create_from_template", "filePath": "/report.odt", "templateFields": [{"index": "0", "type": "text", "alias": None, "tag": None, "id": None, "content": "Hello"}]}, "POST", "/templates/create", {"filePath": "/report.odt", "templatePath": "", "templateType": "user", "templateFields": [{"index": "0", "type": "text", "alias": None, "tag": None, "id": None, "content": "Hello"}]}, {}),
    ({"operation": "initialize_templates"}, "POST", "/templates/path", {"templatePath": "", "copySystemTemplates": False}, {}),
    ({"operation": "get_editing_capabilities"}, "GET", "/directEditing", {}, {}),
    ({"operation": "list_editor_templates", "editorId": "text", "creatorId": "text"}, "GET", "/directEditing/templates/text/text", {}, {}),
    ({"operation": "open_editor", "path": "/notes.md", "fileId": 42}, "POST", "/directEditing/open", {"path": "/notes.md", "fileId": 42}, {}),
    ({"operation": "create_for_editing", "path": "/notes.md", "editorId": "text", "creatorId": "text"}, "POST", "/directEditing/create", {"path": "/notes.md", "editorId": "text", "creatorId": "text"}, {}),
    ({"operation": "convert_file", "fileId": 42, "targetMimeType": "application/pdf"}, "POST", "/convert", {"fileId": 42, "targetMimeType": "application/pdf"}, {}),
    ({"operation": "transfer_ownership", "recipient": "alice", "path": "/Documents"}, "POST", "/transferownership", {"recipient": "alice", "path": "/Documents"}, {}),
    ({"operation": "accept_transfer", "id": 42}, "POST", "/transferownership/42", {}, {}),
    ({"operation": "reject_transfer", "id": 42}, "DELETE", "/transferownership/42", {}, {}),
    ({"operation": "create_local_editor", "path": "/notes.md"}, "POST", "/openlocaleditor", {"path": "/notes.md"}, {}),
    ({"operation": "validate_local_editor", "token": "a/token?#", "path": "/notes.md"}, "POST", "/openlocaleditor/a%2Ftoken%3F%23", {"path": "/notes.md"}, {}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body,query", CASES)
async def test_nextcloud_actions(transport, config, method, path, body, query):
    requests, responses = transport
    payload = [{"id": 42, "basename": "Documents", "children": []}] if config["operation"] == "list_folders" else {"a": "value"}
    responses.append(httpx.Response(201 if config["operation"] == "convert_file" else 200,
                                    json=payload if config["operation"] == "list_folders" else envelope(payload)))
    node_data = {"config": config, "credentials": CREDENTIAL}
    node = NextcloudNode(node_id="test", node_type="automation-nextcloud", node_data=node_data, config=NextcloudNode.parse_config(node_data))
    result = await node.execute({})
    assert result["data"] == payload
    request = requests[0]
    assert request.method == method
    assert request.url.raw_path.split(b"?")[0].decode() == "/nextcloud" + FILES + path
    assert dict(request.url.params) == query
    assert (json.loads(request.content) if request.content else {}) == body
    assert request.headers["OCS-APIRequest"] == "true"
    assert request.headers["Accept"] == "application/json"
    assert request.headers["Authorization"] == "Basic " + base64.b64encode(b"admin:a-real-test-app-password").decode()


@pytest.mark.parametrize("url", ["http://cloud.example.com", "https://user:pass@cloud.example.com", "https://cloud.example.com/?x=1", "https://cloud.example.com/#fragment", "https://cloud.example.com/../x", "https://cloud.example.com:8443"])
def test_nextcloud_refuses_invalid_installations(url):
    with pytest.raises(ValidationError):
        NextcloudAppPasswordCredential.model_validate({**CREDENTIAL, "server_url": url})


def test_nextcloud_manual_fields_and_template_schema():
    credential = NextcloudAppPasswordCredential.model_validate({k: v for k, v in CREDENTIAL.items() if k != "credential_type"})
    assert credential.credential_type == "nextcloud_app_password"
    assert TemplateField(index="1", type="text", alias=None, tag=None, id=None).model_dump(exclude_none=True) == {"index": "1", "type": "text"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [(401, {"message": "Denied"}), (302, {}), (200, {"ocs": {"meta": {"status": "failure", "statuscode": 997}, "data": []}}), (200, {"ocs": {"meta": {"status": "ok", "statuscode": 200}}}), (200, [])])
async def test_nextcloud_refuses_unsuccessful_responses(transport, status, body):
    _, responses = transport
    responses.append(httpx.Response(status, json=body))
    with pytest.raises(ValueError):
        await NextcloudNode._request(CREDENTIAL, "GET", FILES + "/templates")


@pytest.mark.asyncio
async def test_nextcloud_webhook_lifecycle_and_header_auth(transport):
    requests, responses = transport
    config = {"operation": "on_file_event", "event_type": EVENTS[0], "user_id": "admin"}
    responses.append(httpx.Response(200, json=envelope({"id": "42", "userId": "admin", "httpMethod": "POST", "uri": "https://hooks.hooks.example.test/abc", "authMethod": "header"})))
    registration = await NextcloudNode._register_external_webhook(webhook_url="https://hooks.hooks.example.test/abc", credential=CREDENTIAL, config=config, node_id="test")
    sent = json.loads(requests[0].content)
    assert sent == {"httpMethod": "POST", "uri": "https://hooks.hooks.example.test/abc", "event": EVENTS[0],
                    "userIdFilter": "admin", "authMethod": "none", "headers": {"X-NoClick-Webhook-Secret": registration["signing_secret"]}}
    assert "tokenNeeded" not in sent
    assert str(requests[0].url).endswith(WEBHOOKS)
    config.update(registration)
    assert NextcloudNode.verify_webhook_signature(b"{}", {"X-NoClick-Webhook-Secret": registration["signing_secret"]}, config)
    assert not NextcloudNode.verify_webhook_signature(b"{}", {}, config)
    assert not NextcloudNode.verify_webhook_signature(b"{}", {"x-noclick-webhook-secret": "wrong"}, config)
    assert not NextcloudNode.verify_webhook_signature(b"{}", {"x-noclick-webhook-secret": registration["signing_secret"]}, {})
    responses.append(httpx.Response(200, json=envelope(True)))
    await NextcloudNode._unregister_external_webhook(credential=CREDENTIAL, config=config, node_id="test")
    assert requests[-1].method == "DELETE"
    assert str(requests[-1].url).endswith(WEBHOOKS + "/42")


@pytest.mark.asyncio
async def test_nextcloud_webhook_deletion_requires_confirmation(transport):
    _, responses = transport
    responses.append(httpx.Response(200, json=envelope("unconfirmed")))
    with pytest.raises(ValueError, match="confirm"):
        await NextcloudNode._unregister_external_webhook(credential=CREDENTIAL, config={"external_webhook_id": "42"}, node_id="test")


@pytest.mark.parametrize("event", json.loads((Path(__file__).parent / "fixtures/nextcloud/events.json").read_text()).values())
def test_nextcloud_documented_event_agent_context(event):
    payload = event["body"]
    config = {"operation": "on_file_event", "event_type": payload["event"]["class"], "user_id": payload["user"]["uid"]}
    assert NextcloudNode.filter_trigger_payload(payload, config)
    assert not NextcloudNode.filter_trigger_payload(payload, {**config, "user_id": "someone-else"})
    result = NextcloudNode.resolve_trigger_payload(payload, config)
    agent = NextcloudNode.resolve_agent_event(result)
    resource = payload["event"].get("target") or payload["event"].get("node")
    assert resource["path"] in agent["text"]
    assert payload["user"]["displayName"] in agent["text"]
    assert str(payload["time"]) in agent["text"]
    assert agent["conversation_key"] == str(resource.get("id") or resource["path"])


@pytest.mark.asyncio
async def test_nextcloud_webhook_cleanup_is_idempotent(transport):
    _, responses = transport
    responses.append(httpx.Response(200, json=envelope(False)))
    await NextcloudNode._unregister_external_webhook(credential=CREDENTIAL, config={"external_webhook_id": "42"}, node_id="test")
