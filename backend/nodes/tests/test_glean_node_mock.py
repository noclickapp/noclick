"""Contract regressions for Glean's native node and managed webhook lifecycle.

Webhook events and the fixed signature vector come from the pinned official spec.
"""
import base64
import json
from pathlib import Path

import httpx
import pytest

from nodes import glean_node as native
from nodes.core.registry import NODE_REGISTRY, NodeFactory

FIXTURE = json.loads((Path(__file__).parent / "fixtures/glean/webhooks.json").read_text())
TOKEN = "unit-test-glean-token"
CREDENTIAL = {"credential_type": "glean_api_token", "api_token": TOKEN, "backend_url": "https://acme-be.glean.com"}


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="glean-test", node_type="automation-glean",
        node_data={"config": config, "credentials": CREDENTIAL})


def transport(monkeypatch, response):
    requests = []
    def handle(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    def client(**kwargs):
        assert kwargs["follow_redirects"] is False
        assert kwargs["trust_env"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


def test_discovery_manual_credential_and_schema():
    assert NODE_REGISTRY["automation-glean"] is native.GleanNode
    credential = native.GleanAPITokenCredential.model_validate({"api_token": TOKEN, "backend_url": "acme-be.glean.com"})
    assert credential.credential_type == "glean_api_token"
    assert credential.backend_url == "https://acme-be.glean.com"
    assert native.GleanNode.connection_evidence.operation == "list_collections"
    assert len(native.OPERATIONS) == 21
    assert native.GleanNode.get_config_schema()["$defs"]["GleanOnEventConfig"]["properties"]["operation"]["x-is-trigger"]


def test_saved_canvas_metadata_is_not_an_api_parameter():
    raw = {"config": {"operation": "get_answer", "id": 3, "id__label": "Knowledge", "goal": "Read answer",
        "credentialIds": {"glean_api_token": "saved-credential"}}, "credentials": CREDENTIAL}
    assert native.GleanNode.validate_config(raw)["valid"]
    assert native.GleanNode.parse_config(raw).config.model_dump() == {"operation": "get_answer", "id": 3}


def test_invalid_config_errors_do_not_expose_credentials():
    with pytest.raises(ValueError) as error:
        native.GleanNode.parse_config({"config": {"operation": "get_answer"}, "credentials": CREDENTIAL})
    assert TOKEN not in str(error.value)
    assert TOKEN not in repr(native.GleanAPITokenCredential.model_validate(CREDENTIAL))


@pytest.mark.parametrize("url", ["https://glean.com", "https://evil.com", "http://acme-be.glean.com",
    "https://acme-be.glean.com.evil.com", "https://evil.com@acme-be.glean.com", "https://acme-be.glean.com/api", "https://127.0.0.1", "https://acme-be.glean.com:8080"])
def test_refuses_wrong_credential_destination(url):
    with pytest.raises(ValueError):
        native.GleanAPITokenCredential.model_validate({**CREDENTIAL, "backend_url": url})


@pytest.mark.parametrize("token", ["Bearer abc123", "https://acme-be.glean.com", "<token>"])
def test_refuses_header_url_and_placeholder_tokens(token):
    with pytest.raises(ValueError):
        native.GleanAPITokenCredential.model_validate({**CREDENTIAL, "api_token": token})


@pytest.mark.asyncio
@pytest.mark.parametrize("config,path,body", [
    ({"operation": "create_answer", "question": "Why is the sky blue?", "bodyText": "Blue light scatters."}, "/rest/api/v1/createanswer", {"data": {"question": "Why is the sky blue?", "bodyText": "Blue light scatters."}}),
    ({"operation": "update_answer", "id": 3, "question": "Question", "bodyText": "Answer"}, "/rest/api/v1/editanswer", {"id": 3, "question": "Question", "bodyText": "Answer"}),
    ({"operation": "create_collection", "name": "Knowledge", "parentId": 0}, "/rest/api/v1/createcollection", {"name": "Knowledge", "parentId": 0}),
    ({"operation": "update_collection", "id": 4, "name": "Updated"}, "/rest/api/v1/editcollection", {"id": 4, "name": "Updated"}),
    ({"operation": "delete_collections", "ids": [3, 4]}, "/rest/api/v1/deletecollection", {"ids": [3, 4]}),
    ({"operation": "create_shortcut", "inputAlias": "handbook", "destinationUrl": "https://example.com"}, "/rest/api/v1/createshortcut", {"data": {"inputAlias": "handbook", "destinationUrl": "https://example.com"}}),
    ({"operation": "get_documents", "documentSpecs": [{"id": "ANSWERS_answer_3"}]}, "/rest/api/v1/getdocuments", {"documentSpecs": [{"id": "ANSWERS_answer_3"}]}),
    ({"operation": "delete_collection_item", "collectionId": 3, "itemId": "item-1"}, "/rest/api/v1/deletecollectionitem", {"collectionId": 3, "itemId": "item-1"}),
])
async def test_exact_contract_write_and_read_bodies(monkeypatch, config, path, body):
    requests = transport(monkeypatch, {})
    output = await node(config).execute({})
    assert output["status"] == "success"
    assert len(requests) == 1
    assert requests[0].method == "POST" and requests[0].url.path == path
    assert json.loads(requests[0].content) == body
    assert requests[0].headers["Authorization"] == "Bearer " + TOKEN


@pytest.mark.asyncio
async def test_search_and_pagination_preserved(monkeypatch):
    reply = {"results": [], "cursor": "next-page"}
    requests = transport(monkeypatch, reply)
    assert (await node({"operation": "search", "query": "vacation policy", "cursor": "prior-page"}).execute({}))["data"] == reply
    assert json.loads(requests[0].content) == {"query": "vacation policy", "pageSize": 10, "cursor": "prior-page"}
    requests = transport(monkeypatch, {"results": [], "next_cursor": "more", "has_more": True})
    result = await node({"operation": "list_trigger_presets", "page_size": 10, "cursor": "opaque"}).execute({})
    assert requests[0].method == "GET" and dict(requests[0].url.params) == {"page_size": "10", "cursor": "opaque"}
    assert result["data"]["next_cursor"] == "more"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
async def test_errors_are_not_success_and_secrets_are_redacted(monkeypatch, status):
    requests = transport(monkeypatch, lambda request: httpx.Response(status, text=f"Rejected {TOKEN}"))
    with pytest.raises(ValueError) as error:
        await node({"operation": "list_collections"}).execute({})
    assert str(status) in str(error.value) and TOKEN not in str(error.value)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_registration_and_teardown_exact_contract(monkeypatch):
    secret = "whsec_" + base64.b64encode(b"test_webhook_signing_secret_1234").decode()
    requests = transport(monkeypatch, {"trigger": {"trigger_id": "trigger_test_123", "signing_secret": secret}})
    config = {"operation": "on_event", "preset_id": "GITHUB_1", "inputs": {"repository": "acme/payments-api"}}
    saved = await native.GleanNode._register_external_webhook(webhook_url="https://example.com/webhook", credential=CREDENTIAL, config=config, node_id="test")
    assert requests[0].headers["x-glean-include-experimental"] == "true"
    assert json.loads(requests[0].content) == {"preset_id": "GITHUB_1", "inputs": {"repository": "acme/payments-api"}, "delivery": {"webhook_url": "https://example.com/webhook"}}
    assert saved == {"external_webhook_id": "trigger_test_123", "signing_secret": secret}
    requests = transport(monkeypatch, lambda request: httpx.Response(204))
    await native.GleanNode._unregister_external_webhook(credential=CREDENTIAL, config=saved, node_id="test")
    assert requests[0].method == "DELETE" and requests[0].url.path == "/api/triggers/trigger_test_123"
    assert native.GleanNode.registration_fingerprint_fields(config) == {"preset_id": "GITHUB_1", "inputs": {"repository": "acme/payments-api"}}


def test_provider_published_signature_vector_and_tampering(monkeypatch):
    monkeypatch.setattr(native.time, "time", lambda: 1700000000)
    event = FIXTURE["events"]["PlatformDocumentChangeWebhookEvent"]
    # The vector's exact key order is significant: it signs the raw JSON bytes.
    body = b'{"version":"1","trigger_id":"trigger_test_123","datasource":"GITHUB","reason":"REVIEW_REQUESTED","doc_type":"pull","event_type":"DOCUMENT_CHANGE","doc_id":"GITHUB_pull_123","view_url":"https://github.com/acme/payments-api/pull/123","title":"Add retry backoff to the crawler","event_time":"2025-04-23T11:00:00Z"}'
    assert json.loads(body) == event
    config = {"signing_secret": "whsec_" + base64.b64encode(b"test_webhook_signing_secret_1234").decode()}
    headers = {"webhook-id": "81e6dc877ac553ef96ecbc939c1e46431159491991ba55cd131fbd0e3746c6bc", "webhook-timestamp": "1700000000", "webhook-signature": "v1,JqvHW0dwAOSLndiwQdXLUS/P+2RvOO8x4sOWgA/w0Gs="}
    assert native.GleanNode.verify_webhook_signature(body, headers, config)
    assert native.GleanNode.verify_webhook_signature(body, {k.upper(): v for k, v in headers.items()}, config)
    assert not native.GleanNode.verify_webhook_signature(body + b" ", headers, config)
    assert not native.GleanNode.verify_webhook_signature(body, {**headers, "webhook-id": "other"}, config)
    assert not native.GleanNode.verify_webhook_signature(body, {**headers, "webhook-timestamp": "1700000001"}, config)
    assert not native.GleanNode.verify_webhook_signature(body, headers, {"signing_secret": "whsec_!!!"})
    assert not native.GleanNode.verify_webhook_signature(body, {}, config)
    assert native.GleanNode.verify_webhook_signature(body, {**headers, "webhook-signature": "v2,other v1,other " + headers["webhook-signature"]}, config)
    monkeypatch.setattr(native.time, "time", lambda: 1700000301)
    assert not native.GleanNode.verify_webhook_signature(body, headers, config)


@pytest.mark.asyncio
async def test_invalid_registration_secret_is_removed_not_activated(monkeypatch):
    def response(request):
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(201, json={"trigger": {"trigger_id": "trigger_test_123", "signing_secret": "whsec_xxx"}})
    requests = transport(monkeypatch, response)
    with pytest.raises(ValueError, match="invalid Standard Webhooks"):
        await native.GleanNode._register_external_webhook(webhook_url="https://example.com/webhook", credential=CREDENTIAL,
            config={"operation": "on_event", "preset_id": "GITHUB_1"}, node_id="test")
    assert [request.method for request in requests] == ["POST", "DELETE"]


@pytest.mark.parametrize("event", FIXTURE["events"].values())
def test_documented_events_survive_payload_hooks_and_describe_agent_turn(event):
    output = native.GleanNode.resolve_trigger_payload(event, {"external_webhook_id": "trigger_test_123"})
    assert output == event
    turn = native.GleanNode.resolve_agent_event(output)
    assert turn["conversation_key"] == event["doc_id"]
    for field in ["title", "view_url", "doc_id", "trigger_id", "datasource", "reason"]:
        assert event[field] in turn["text"]
    assert native.GleanNode.resolve_trigger_payload(event, {"external_webhook_id": "other"}) == {"status": "no_event"}
    assert native.GleanNode.resolve_trigger_payload({"event_type": "UNKNOWN"}, {}) == {"status": "no_event"}
