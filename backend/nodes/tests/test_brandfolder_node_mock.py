"""Check Brandfolder's request shapes and webhook lifecycle without an account.

The fixture preserves the provider's event template. Concrete test deliveries
instantiate that template and are not represented as live recordings.
"""
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from nodes.brandfolder_node import BrandfolderAPIKeyCredential, BrandfolderNode, BrandfolderNodeConfig, BrandfolderOnAssetEventConfig, EVENTS

KEY = {"credential_type": "brandfolder_api_key", "api_key": "unit-test-api-key"}
BF = "oqgiju-21olts-ce9egi"
ASSET = "oqgkkd-fr5iv4-443db"


def node(config):
    return BrandfolderNode("test", "automation-brandfolder", {"config": config},
        config=BrandfolderNodeConfig.model_validate({"config": config, "credentials": KEY}))


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))


@pytest.mark.asyncio
async def test_create_asset_wire_and_preserved_envelope(monkeypatch):
    def handle(request):
        assert str(request.url) == f"https://brandfolder.com/api/v4/brandfolders/{BF}/assets"
        assert request.method == "POST"
        assert request.headers["Authorization"] == "Bearer unit-test-api-key"
        assert request.headers["Content-Type"] == "application/json"
        assert request.headers["Accept"] == "application/json"
        assert json.loads(request.content) == {"data": {"attributes": [{"name": "Brandfolder Logo", "attachments": [{"url": "https://example.com/new-attachment.jpg", "filename": "new-attachment.jpg"}]}]}, "section_key": "oqgol8-dslwxs-58b2z3"}
        return httpx.Response(200, json={"data": [{"id": ASSET, "type": "generic_files", "attributes": {"name": "Brandfolder Logo"}}], "meta": {"total_count": 1}})
    transport(monkeypatch, handle)
    result = await node({"operation": "create_asset", "brandfolder_id": BF, "section_key": "oqgol8-dslwxs-58b2z3", "name": "Brandfolder Logo", "attachment_url": "https://example.com/new-attachment.jpg", "attachment_filename": "new-attachment.jpg"}).execute({})
    assert result["data"][0]["id"] == ASSET
    assert result["meta"]["total_count"] == 1


@pytest.mark.asyncio
async def test_query_and_pagination_are_preserved(monkeypatch):
    def handle(request):
        assert request.method == "GET"
        assert request.url.path == f"/api/v4/brandfolders/{BF}/assets"
        assert dict(request.url.params) == {"page": "2", "per": "20", "search": "extension:png", "fields": "created_at,updated_at", "include": "tags"}
        return httpx.Response(200, json={"data": [], "meta": {"current_page": 2, "total_pages": 3, "next_page": 3}})
    transport(monkeypatch, handle)
    result = await node({"operation": "list_assets", "brandfolder_id": BF, "page": 2, "per": 20, "search": "extension:png", "fields": "created_at,updated_at", "include": "tags"}).execute({})
    assert result["meta"]["next_page"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body,response", [
    ({"operation": "update_asset", "asset_id": ASSET, "name": "Brandfolder Logo", "approved": False}, "PUT", f"/api/v4/assets/{ASSET}", {"data": {"attributes": {"name": "Brandfolder Logo", "approved": False}}}, {"data": {"id": ASSET}}),
    ({"operation": "add_asset_tags", "asset_id": ASSET, "tags_json": '["product"]'}, "POST", f"/api/v4/assets/{ASSET}/tags", {"data": {"attributes": [{"name": "product"}]}}, {"data": []}),
    ({"operation": "create_collection", "brandfolder_id": BF, "name": "My collection"}, "POST", f"/api/v4/brandfolders/{BF}/collections", {"data": {"attributes": {"name": "My collection"}}}, {"id": "collection", "type": "collections", "attributes": {"name": "My collection"}}),
    ({"operation": "create_section", "brandfolder_id": BF, "name": "My section", "default_asset_type": "GenericFile", "position": 0}, "POST", f"/api/v4/brandfolders/{BF}/sections", {"data": {"attributes": {"name": "My section", "default_asset_type": "GenericFile", "position": 0}}}, {"data": {"id": "section"}}),
    ({"operation": "create_label", "brandfolder_id": BF, "name": "onboarding", "parent_key": "abc123"}, "POST", f"/api/v4/brandfolders/{BF}/labels", {"data": {"attributes": {"name": "onboarding", "parent_key": "abc123"}}}, {"data": {"id": "label"}}),
    ({"operation": "delete_asset", "asset_id": ASSET}, "DELETE", f"/api/v4/assets/{ASSET}", None, {}),
    ({"operation": "delete_collection", "collection_id": "collection"}, "DELETE", "/api/v4/collections/collection", None, {}),
])
async def test_writes(monkeypatch, config, method, path, body, response):
    def handle(request):
        assert request.method == method
        assert request.url.path == path
        assert (json.loads(request.content) if request.content else None) == body
        return httpx.Response(200, json=response)
    transport(monkeypatch, handle)
    result = await node(config).execute({})
    assert result["status"] == "success"
    if method == "DELETE":
        assert result["deletion_acknowledged"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
async def test_provider_errors_do_not_leak_key_or_succeed(monkeypatch, status):
    transport(monkeypatch, lambda request: httpx.Response(status, json={"message": "unit-test-api-key rejected"}))
    with pytest.raises(ValueError) as error:
        await node({"operation": "list_brandfolders"}).execute({})
    assert str(status) in str(error.value)
    assert KEY["api_key"] not in str(error.value)


@pytest.mark.asyncio
async def test_success_error_envelope_is_failure(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={"errors": ["Not authorized"]}))
    with pytest.raises(ValueError, match="Not authorized"):
        await node({"operation": "list_brandfolders"}).execute({})


@pytest.mark.asyncio
async def test_connection_options_and_manual_credential_shape(monkeypatch):
    assert BrandfolderAPIKeyCredential(api_key="  unit-test-api-key  ").model_dump() == KEY
    def handle(request):
        assert request.url.path == "/api/v4/brandfolders"
        assert request.url.params["search"] == "marketing"
        return httpx.Response(200, json={"data": [{"id": BF, "attributes": {"name": "Marketing"}}]})
    transport(monkeypatch, handle)
    assert await BrandfolderNode.load_field_options("brandfolder_id", KEY, search="marketing") == [{"value": BF, "label": "Marketing"}]


@pytest.mark.parametrize("key", ["https://brandfolder.com/profile", "Bearer abc", "a\nb"])
def test_bad_key(key):
    with pytest.raises(ValidationError):
        BrandfolderAPIKeyCredential(api_key=key)


@pytest.mark.parametrize("config", [
    {"operation": "get_asset", "asset_id": "../webhooks"},
    {"operation": "get_asset", "asset_id": "a?x=b"},
    {"operation": "list_assets", "brandfolder_id": BF, "page": 0},
    {"operation": "list_assets", "brandfolder_id": BF, "per": 3001},
    {"operation": "create_asset", "brandfolder_id": BF, "name": "Logo"},
    {"operation": "add_asset_tags", "asset_id": ASSET, "tags_json": '{}'},
    {"operation": "add_asset_tags", "asset_id": ASSET, "tags_json": '[]'},
    {"operation": "create_asset", "brandfolder_id": BF, "section_key": "section", "name": "Logo", "attachment_url": "file:///etc/passwd"},
])
def test_invalid_operation_fields(config):
    assert not BrandfolderNode.validate_config({"config": config, "credentials": KEY})["valid"]


@pytest.mark.asyncio
@pytest.mark.parametrize("event", EVENTS)
async def test_webhook_registration_v1_teardown_and_fingerprint(monkeypatch, event):
    calls = []
    def handle(request):
        calls.append(request.method)
        if request.method == "POST":
            assert str(request.url) == "https://brandfolder.com/api/v1/webhooks"
            assert json.loads(request.content) == {"data": {"attributes": {"event_type": event, "resource_key": BF, "resource_type": "brandfolder", "callback_url": "https://example.com/callback"}}}
            return httpx.Response(200, json={"data": {"id": "oqgkkd-fr5iv4-hh142d"}})
        assert str(request.url) == "https://brandfolder.com/api/v1/webhooks/oqgkkd-fr5iv4-hh142d"
        return httpx.Response(200, json={})
    transport(monkeypatch, handle)
    config = {"operation": "on_asset_event", "brandfolder_id": BF, "event_type": event}
    extra = await BrandfolderNode._register_external_webhook(webhook_url="https://example.com/callback", credential=KEY, config=config, node_id="test")
    assert extra == {"external_webhook_id": "oqgkkd-fr5iv4-hh142d"}
    assert BrandfolderNode.registration_fingerprint_fields(config) == {"brandfolder_id": BF, "event_type": event}
    await BrandfolderNode._unregister_external_webhook(credential=KEY, config={**config, **extra}, node_id="test")
    assert calls == ["POST", "DELETE"]
    assert BrandfolderOnAssetEventConfig(**config, **extra).external_webhook_id == extra["external_webhook_id"]


def test_documented_payload_template_and_agent_event():
    fixture = json.loads((Path(__file__).parent / "fixtures/brandfolder/asset_event_template.json").read_text())
    payload = fixture["body"]
    assert BrandfolderNode.verify_webhook_signature(json.dumps(payload).encode(), {}, {})
    turn = BrandfolderNode.resolve_agent_event(BrandfolderNode.resolve_trigger_payload(payload, {}))
    for text in ("<unique_asset_identifier>", "<unique_brandfolder_identifier>", "<unique_organization_identifier>", "does not include the actor or asset content"):
        assert text in turn["text"]
    for kind in EVENTS:
        concrete = {"data": {"attributes": {**payload["data"]["attributes"], "event_type": kind, "key": ASSET, "brandfolder_key": BF}}}
        event = BrandfolderNode.resolve_agent_event(concrete)
        assert kind in event["text"]
        assert event["conversation_key"] == f"brandfolder:{BF}:asset:{ASSET}"


@pytest.mark.asyncio
async def test_manual_trigger_run_does_not_invent_an_event():
    assert (await node({"operation": "on_asset_event", "brandfolder_id": BF}).execute({}))["status"] == "no_event"


@pytest.mark.asyncio
async def test_empty_brandfolder_list_does_not_claim_working_credentials(monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={"data": []}))
    with pytest.raises(ValueError, match="account access is unverified"):
        await BrandfolderNode.load_field_options("brandfolder_id", KEY)
