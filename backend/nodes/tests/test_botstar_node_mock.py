"""BotStar request and response regressions; all credentials and records are synthetic."""
import json
import httpx
import pytest
from pydantic import ValidationError
from pathlib import Path
from nodes.core.base import ConfigValidationError
from nodes import botstar_node as native
from nodes.core.registry import NodeFactory

TOKEN = "synthetic-botstar-token"


@pytest.fixture(autouse=True)
def ensure_native_db_pool():
    yield


def node(config):
    return NodeFactory.create_node(node_id="botstar-test", node_type="automation-botstar",
        node_data={"config": config, "credentials": {"credential_type": "botstar_api_token", "api_token": TOKEN}})


def transport(monkeypatch, response):
    requests = []
    def respond(request):
        requests.append(request)
        return response(request) if callable(response) else httpx.Response(200, json=response)
    real_client = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return real_client(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(native, "guarded_async_client", client)
    return requests


CASES = [
    ({"operation": "list_bots"}, "GET", "/bots/", None, []),
    ({"operation": "create_bot", "name": "Lead Generation Bot"}, "POST", "/bots/", {"name": "Lead Generation Bot"}, {"id": "bot"}),
    ({"operation": "get_bot", "bot_id": "bot"}, "GET", "/bots/bot", None, {"id": "bot"}),
    ({"operation": "publish_bot", "bot_id": "bot"}, "POST", "/bots/bot/publish", None, {"status": "success"}),
    ({"operation": "list_bot_attributes", "bot_id": "bot"}, "GET", "/bots/bot/attributes", None, []),
    ({"operation": "delete_bot_attribute", "bot_id": "bot", "attribute_id": "attr"}, "DELETE", "/bots/bot/attributes/attr", None, None),
    ({"operation": "get_user", "bot_id": "bot", "user_id": "user"}, "GET", "/bots/bot/users/user", None, {"id": "user", "first_name": "Pat"}),
    ({"operation": "update_user", "bot_id": "bot", "user_id": "user", "first_name": "Pat"}, "PATCH", "/bots/bot/users/user", {"first_name": "Pat"}, {"first_name": "Pat"}),
    ({"operation": "create_user_attribute", "bot_id": "bot", "field_name": "customer", "field_type": "boolean"}, "POST", "/bots/bot/users/attributes", {"field_name": "customer", "field_type": "boolean"}, {"id": "attr", "field_name": "customer", "field_type": "boolean"}),
    ({"operation": "list_entities", "bot_id": "bot"}, "GET", "/bots/bot/cms_entities", None, []),
    ({"operation": "get_entity", "bot_id": "bot", "entity_id": "entity"}, "GET", "/bots/bot/cms_entities/entity", None, {"id": "entity", "name": "Polo Shirt"}),
    ({"operation": "update_entity", "bot_id": "bot", "entity_id": "entity", "name": "Summer Polo Shirt"}, "PATCH", "/bots/bot/cms_entities/entity", {"name": "Summer Polo Shirt"}, {"status": "success"}),
    ({"operation": "delete_entity", "bot_id": "bot", "entity_id": "entity"}, "DELETE", "/bots/bot/cms_entities/entity", None, {"status": "success"}),
    ({"operation": "list_entity_items", "bot_id": "bot", "entity_id": "entity", "limit": 2}, "GET", "/bots/bot/cms_entities/entity/items", None, [{"id": "item", "name": "Polo"}]),
    ({"operation": "get_entity_item", "bot_id": "bot", "entity_id": "entity", "entity_item_id": "item"}, "GET", "/bots/bot/cms_entities/entity/items/item", None, {"id": "item", "name": "Polo"}),
    ({"operation": "create_entity_item", "bot_id": "bot", "entity_id": "entity", "name": "Polo", "custom_fields": {"color": ["red"], "price": "$10"}}, "POST", "/bots/bot/cms_entities/entity/items", {"name": "Polo", "color": ["red"], "price": "$10"}, {"id": "item", "name": "Polo"}),
    ({"operation": "update_entity_item", "bot_id": "bot", "entity_id": "entity", "entity_item_id": "item", "status": "disabled"}, "PATCH", "/bots/bot/cms_entities/entity/items/item", {"status": "disabled"}, {"status": "success"}),
    ({"operation": "delete_entity_item", "bot_id": "bot", "entity_id": "entity", "entity_item_id": "item"}, "DELETE", "/bots/bot/cms_entities/entity/items/item", None, {"status": "success"}),
    ({"operation": "send_message", "recipient_id": "recipient", "text": "Hello World", "message_tag": "ACCOUNT_UPDATE"}, "POST", "/messages", {"recipient": {"id": "recipient"}, "message": {"text": "Hello World"}, "options": {"message_tag": "ACCOUNT_UPDATE"}}, {"recipient_id": "recipient", "message_id": "message"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("config,method,path,body,response", CASES, ids=[case[0]["operation"] for case in CASES])
async def test_single_documented_request(monkeypatch, config, method, path, body, response):
    status = 201 if config["operation"] in {"create_user_attribute", "create_entity_item"} else 200
    requests = transport(monkeypatch, lambda request: httpx.Response(status, json=response) if response is not None else httpx.Response(status))
    result = await node(config).execute({})
    assert result["status"] == "success" and result["data"] == response
    assert len(requests) == 1
    request = requests[0]
    assert request.method == method and str(request.url).split("?")[0] == native.BASE_URL + path
    assert request.headers["authorization"] == "Bearer " + TOKEN
    assert (json.loads(request.content) if request.content else None) == body
    assert TOKEN not in str(result)


@pytest.mark.asyncio
async def test_pagination_filters_and_environment(monkeypatch):
    requests = transport(monkeypatch, [{"id": "1", "name": "Polo"}])
    result = await node({"operation": "list_entity_items", "bot_id": "bot", "entity_id": "entity",
        "page": 3, "limit": 1, "env": "live", "status": "enabled", "name": "A + B"}).execute({})
    assert dict(requests[0].url.params) == {"page": "3", "limit": "1", "env": "live", "status": "enabled", "name": "A + B"}
    assert result["next_page"] == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 401, 403, 404, 429, 500])
async def test_failure_does_not_follow_or_retry_and_redacts_token(monkeypatch, status):
    requests = transport(monkeypatch, lambda request: httpx.Response(status, json={"message": "Rejected " + TOKEN}, headers={"location": "https://example.test"}))
    result = await node({"operation": "list_bots"}).execute({})
    assert result["status"] == "error" and result["http_status"] == status
    assert result["error"] == "Rejected [redacted]" and len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>"), httpx.Response(200, json={"not": "a list"})])
async def test_invalid_response_fails(monkeypatch, response):
    transport(monkeypatch, lambda request: response)
    with pytest.raises(ValueError):
        await node({"operation": "list_bots"}).execute({})


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"error": "invalid_token", "message": "Rejected"}, {"status": "failed"}])
async def test_provider_error_envelope(monkeypatch, body):
    transport(monkeypatch, body)
    assert (await node({"operation": "list_bots"}).execute({}))["status"] == "error"


@pytest.mark.parametrize("config", [
    {"operation": "get_bot", "bot_id": "../other"},
    {"operation": "update_user", "bot_id": "b", "user_id": "u"},
    {"operation": "list_entities", "bot_id": "b", "env": "draft,live"},
    {"operation": "update_entity_item", "bot_id": "b", "entity_id": "e", "entity_item_id": "i"},
    {"operation": "create_entity_item", "bot_id": "b", "entity_id": "e", "name": "x", "custom_fields": {"name": "override"}},
])
def test_invalid_configs(config):
    with pytest.raises(ConfigValidationError):
        native.BotstarNode.parse_config({"config": config})


def test_manual_credential_default_and_connection_evidence():
    assert native.BotstarAPITokenCredential(api_token=TOKEN).credential_type == "botstar_api_token"
    assert native.BotstarNode.connection_evidence.operation == "list_bots"
    for token in ["Bearer token", "https://example.test", "<token>"]:
        with pytest.raises((ValueError, ValidationError)):
            native.BotstarAPITokenCredential(api_token=token)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["entity", "item"])
async def test_documented_response_preserved(monkeypatch, kind):
    fixture = json.loads((Path(__file__).parent / "fixtures/botstar/documented.json").read_text())
    transport(monkeypatch, fixture[kind])
    config = {"operation": "get_entity" if kind == "entity" else "get_entity_item",
        "bot_id": "bot", "entity_id": "1"}
    if kind == "item":
        config["entity_item_id"] = "1"
    result = await node(config).execute({})
    assert result["data"] == fixture[kind]
