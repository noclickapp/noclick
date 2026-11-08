"""Kit V4 credential, operation, schema and request contracts."""

import hashlib
import hmac
import json
import time
from unittest.mock import Mock
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from nodes.kit_node import (
    CONFIG_MODELS, KIT_SCOPES, KIT_WEBHOOK_EVENTS, OPERATIONS, KitAPIKeyCredential,
    KitNode, KitNodeConfig, KitOAuthCredential, KitOnEventConfig,
)
from nodes.oauth.kit_oauth import OAUTH_PROVIDER, refresh_access_token


def node(operation_name: str, *, api_key: bool = False, **values):
    config = CONFIG_MODELS[operation_name](**values)
    credential = (KitAPIKeyCredential(api_key="key") if api_key else
                  KitOAuthCredential(access_token="access", refresh_token="refresh",
                                     expires_at="2099-01-01T00:00:00Z"))
    return KitNode(
        node_id="kit-test", node_type="automation-kit", node_data={},
        config=KitNodeConfig(config=config, credentials=credential),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )


@pytest.mark.asyncio
async def test_oauth_code_exchange_and_single_use_refresh(monkeypatch):
    monkeypatch.setenv("KIT_CLIENT_ID", "client")
    monkeypatch.setenv("KIT_CLIENT_SECRET", "secret")
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://api.kit.com/v4/oauth/token").mock(side_effect=[
            httpx.Response(200, json={"access_token": "one", "refresh_token": "rotate-1",
                                      "expires_in": 3600, "scope": "public"}),
            httpx.Response(200, json={"access_token": "two", "refresh_token": "rotate-2",
                                      "expires_in": 3600, "scope": "public"}),
        ])
        router.get("https://api.kit.com/v4/account").mock(
            return_value=httpx.Response(200, json={"account": {"name": "Kit Greetings"}}))
        first, account_name = await OAUTH_PROVIDER.exchange(
            "code", "https://noclick.com/api/auth/oauth/kit/callback")
        assert account_name == "Kit Greetings"
        second = await refresh_access_token(first.refresh_token)
    assert first.refresh_token == "rotate-1"
    assert second.refresh_token == "rotate-2"
    assert route.call_count == 2
    assert all(call.request.headers["content-type"] == "application/x-www-form-urlencoded"
               for call in route.calls)
    assert dict(parse_qs(route.calls[0].request.content.decode(), strict_parsing=True)) == {
        "client_id": ["client"], "client_secret": ["secret"], "grant_type": ["authorization_code"],
        "code": ["code"], "redirect_uri": ["https://noclick.com/api/auth/oauth/kit/callback"],
    }
    assert dict(parse_qs(route.calls[1].request.content.decode(), strict_parsing=True)) == {
        "client_id": ["client"], "client_secret": ["secret"],
        "grant_type": ["refresh_token"], "refresh_token": ["rotate-1"],
    }


@pytest.mark.asyncio
async def test_missing_rotated_refresh_token_is_rejected(monkeypatch):
    monkeypatch.setenv("KIT_CLIENT_ID", "client")
    monkeypatch.setenv("KIT_CLIENT_SECRET", "secret")
    with respx.mock:
        respx.post("https://api.kit.com/v4/oauth/token").mock(
            return_value=httpx.Response(200, json={"access_token": "new", "expires_in": 3600}))
        with pytest.raises(ValueError, match="single-use"):
            await refresh_access_token("consumed")


@pytest.mark.asyncio
@pytest.mark.parametrize("name,values,method,path,body", [
    ("get_account", {}, "GET", "/account", None),
    ("list_subscribers", {"email_address": "test@example.com", "per_page": 10}, "GET", "/subscribers", None),
    ("get_subscriber", {"subscriber_id": 123}, "GET", "/subscribers/123", None),
    ("create_subscriber", {"email_address": "test@example.com", "fields_json": '{"source":"noclick"}'},
     "POST", "/subscribers", {"email_address": "test@example.com", "fields": {"source": "noclick"}}),
    ("update_subscriber", {"subscriber_id": 123, "email_address": "test@example.com"},
     "PUT", "/subscribers/123", {"email_address": "test@example.com"}),
    ("unsubscribe_subscriber", {"subscriber_id": 123}, "POST", "/subscribers/123/unsubscribe", {}),
    ("create_tag", {"name": "NoClick Test"}, "POST", "/tags", {"name": "NoClick Test"}),
    ("tag_subscriber", {"tag_id": 3, "subscriber_id": 123}, "POST", "/tags/3/subscribers/123", {}),
    ("untag_subscriber", {"tag_id": 3, "subscriber_id": 123}, "DELETE", "/tags/3/subscribers/123", None),
    ("add_email_to_form", {"form_id": 4, "email_address": "test@example.com"},
     "POST", "/forms/4/subscribers", {"email_address": "test@example.com"}),
    ("create_sequence", {"name": "Welcome"}, "POST", "/sequences", {"name": "Welcome"}),
    ("create_sequence_email", {"sequence_id": 5, "subject": "Hello", "delay_value": 1, "delay_unit": "days"},
     "POST", "/sequences/5/emails", {"subject": "Hello", "delay_value": 1, "delay_unit": "days"}),
    ("create_custom_field", {"label": "Interest"}, "POST", "/custom_fields", {"label": "Interest"}),
    ("create_webhook", {"url": "https://example.com/hook", "events": "subscriber.created,subscriber.updated"},
     "POST", "/webhook_endpoints", {"url": "https://example.com/hook",
                                    "events": ["subscriber.created", "subscriber.updated"]}),
    ("update_webhook", {"webhook_id": 77, "status": "disabled"},
     "PATCH", "/webhook_endpoints/77", {"status": "disabled"}),
])
async def test_api_request(name, values, method, path, body):
    with respx.mock(assert_all_called=True) as router:
        route = router.request(method, "https://api.kit.com/v4" + path).mock(
            return_value=httpx.Response(204) if method == "DELETE" else
            httpx.Response(200, json={"result": True}))
        result = await node(name, **values).execute({})
    request = route.calls[0].request
    assert request.headers["Authorization"] == "Bearer access"
    if body is not None:
        assert json.loads(request.content) == body
    if name == "list_subscribers":
        assert request.url.params["email_address"] == "test@example.com"
        assert request.url.params["per_page"] == "10"
    assert result == {"status": "success", "operation": name,
                      "data": {"ok": True} if method == "DELETE" else {"result": True}}


@pytest.mark.asyncio
async def test_api_key_uses_kit_header_and_errors_are_visible():
    with respx.mock:
        route = respx.get("https://api.kit.com/v4/account").mock(
            return_value=httpx.Response(401, json={"error": "unauthorized"}))
        with pytest.raises(ValueError, match="Kit API error 401: unauthorized"):
            await node("get_account", api_key=True).execute({})
    assert route.calls[0].request.headers["X-Kit-Api-Key"] == "key"
    assert "Authorization" not in route.calls[0].request.headers


@pytest.mark.asyncio
async def test_invalid_json_is_rejected_before_request():
    with pytest.raises(ValueError, match="fields_json must contain valid JSON"):
        await node("create_subscriber", email_address="test@example.com", fields_json="{").execute({})


def test_every_operation_is_in_schema_and_public_scope():
    assert len(OPERATIONS) == 48
    schema = KitNode.get_config_schema()
    for name, model in CONFIG_MODELS.items():
        assert model.__name__ in schema["$defs"]
        assert KIT_SCOPES.require(name) is not None
    assert "KitOnEventConfig" in schema["$defs"]
    assert KIT_SCOPES.require("on_event") is not None
    assert schema["$defs"]["KitOAuthCredential"]["x-oauth-scopes"] == ["public"]


@pytest.mark.asyncio
async def test_trigger_registration_and_cleanup():
    assert len(KIT_WEBHOOK_EVENTS) == 23
    with respx.mock(assert_all_called=True) as router:
        created = router.post("https://api.kit.com/v4/webhook_endpoints").mock(
            return_value=httpx.Response(201, json={"webhook_endpoint": {
                "id": 42, "secret": "whsec_test", "events": ["subscriber.created"]}}))
        deleted = router.delete("https://api.kit.com/v4/webhook_endpoints/42").mock(
            return_value=httpx.Response(204))
        result = await KitNode._register_external_webhook(
            webhook_url="https://hook.hooks.example.test", credential={"api_key": "key"},
            config={"event_type": "subscriber.created"}, node_id="node-1")
        await KitNode._unregister_external_webhook(
            credential={"api_key": "key"}, config=result, node_id="node-1")
    assert json.loads(created.calls[0].request.content) == {
        "url": "https://hook.hooks.example.test", "events": ["subscriber.created"], "name": "NoClick node-1"}
    assert created.calls[0].request.headers["X-Kit-Api-Key"] == "key"
    assert deleted.call_count == 1
    assert result == {"external_webhook_id": "42", "signing_secret": "whsec_test"}


def test_trigger_verifies_signature_and_rejects_replays():
    body = b'{"events":[{"type":"subscriber.created"}]}'
    timestamp = str(int(time.time()))
    signature = hmac.new(b"whsec_test", timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    header = {"X-Kit-Signature": f"t={timestamp},v1=bad,v1={signature}"}
    config = {"signing_secret": "whsec_test"}
    assert KitNode.verify_webhook_signature(body, header, config)
    assert not KitNode.verify_webhook_signature(body + b" ", header, config)
    assert not KitNode.verify_webhook_signature(body, header, {})
    assert not KitNode.verify_webhook_signature(body, {"X-Kit-Signature": f"t={int(timestamp)-301},v1={signature}"}, config)


@pytest.mark.asyncio
async def test_trigger_executes_with_received_event():
    credential = KitAPIKeyCredential(api_key="key")
    trigger = KitNode(
        node_id="kit-trigger", node_type="automation-kit", node_data={},
        config=KitNodeConfig(config=KitOnEventConfig(event_type="subscriber.created"), credentials=credential),
        sio=Mock(), sid="sid", workflow_id="workflow", user_id="user",
    )
    event = {"events": [{"type": "subscriber.created", "data": {"subscriber": {"id": 1}}}]}
    assert (await trigger.execute(event))["data"] == event


# Requests and responses from the provider's examples:
# https://developers.kit.com/api-reference/forms/add-subscriber-to-form.md
# https://developers.kit.com/api-reference/broadcasts/create-a-broadcast.md
# Draft creation overrides public=False and keeps the documented send_at=None.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,values,path,body,status,response",
    [
        (
            "add_subscriber_to_form",
            {
                "referrer": "https://mywebsite.com/bfpromo/?utm_source=facebook&utm_medium=cpc&utm_campaign=black_friday&utm_term=car_owners&utm_content=get_10_off",
                "form_id": 287,
                "subscriber_id": 772,
            },
            "/forms/287/subscribers/772",
            {
                "referrer": "https://mywebsite.com/bfpromo/?utm_source=facebook&utm_medium=cpc&utm_campaign=black_friday&utm_term=car_owners&utm_content=get_10_off"
            },
            200,
            {
                "subscriber": {
                    "id": 767,
                    "first_name": "Alice",
                    "email_address": "alice@convertkit.dev",
                    "state": "active",
                    "created_at": "2023-02-17T11:43:55Z",
                    "added_at": "2023-02-17T11:43:55Z",
                    "fields": {},
                    "referrer": "https://mywebsite.com/bfpromo/?utm_source=facebook&utm_medium=cpc&utm_campaign=black_friday&utm_term=car_owners&utm_content=get_10_off",
                    "referrer_utm_parameters": {
                        "source": "facebook",
                        "medium": "cpc",
                        "campaign": "black_friday",
                        "term": "car_owners",
                        "content": "get_10_off",
                    },
                }
            },
        ),
        (
            "create_broadcast_draft",
            {
                "content": "<p>Let me introduce myself</p>",
                "description": "Intro email",
                "published_at": "2023-02-17T11:43:55+00:00",
                "preview_text": "Pleased to meet you!",
                "subject": "Hello!",
                "subscriber_filter_json": '[{"all":[{"type":"segment","ids":[2]}],"any":null,"none":null}]',
            },
            "/broadcasts",
            {
                "content": "<p>Let me introduce myself</p>",
                "description": "Intro email",
                "public": False,
                "published_at": "2023-02-17T11:43:55+00:00",
                "send_at": None,
                "preview_text": "Pleased to meet you!",
                "subject": "Hello!",
                "subscriber_filter": [{"all": [{"type": "segment", "ids": [2]}], "any": None, "none": None}],
            },
            201,
            {
                "broadcast": {
                    "id": 7,
                    "publication_id": 7,
                    "created_at": "2023-02-17T11:43:55Z",
                    "subject": "Hello!",
                    "preview_text": "Pleased to meet you!",
                    "description": "Intro email",
                    "content": "<p>Let me introduce myself</p>",
                    "public": True,
                    "published_at": "2023-02-17T11:43:55Z",
                    "send_at": None,
                    "thumbnail_alt": None,
                    "thumbnail_url": None,
                    "public_url": None,
                    "email_address": "greetings@kit.dev",
                    "email_template": {"id": 2, "name": "Classic"},
                    "subscriber_filter": [{"all": [{"type": "segment", "ids": [2]}]}],
                    "status": "draft",
                    "ab_test": None,
                }
            },
        ),
    ],
)
async def test_required_form_referrer_and_broadcast_timestamp(name, values, path, body, status, response):
    with respx.mock(assert_all_called=True) as router:
        route = router.post("https://api.kit.com/v4" + path).mock(
            return_value=httpx.Response(status, json=response)
        )
        result = await node(name, **values).execute({})
    assert json.loads(route.calls[0].request.content) == body
    assert result == {"status": "success", "operation": name, "data": response}


def test_kit_oauth_has_a_discoverable_standard_provider_declaration():
    from nodes.core.oauth_provider import OAuthProviderSpec
    from nodes.core.oauth_registry import get_oauth_provider

    assert type(OAUTH_PROVIDER) is OAuthProviderSpec
    assert get_oauth_provider("kit") is OAUTH_PROVIDER
    assert OAUTH_PROVIDER.credential_type == "kit_oauth"
    assert OAUTH_PROVIDER.scopes == ["public"]
    assert OAUTH_PROVIDER.identity_url == "https://api.kit.com/v4/account"
