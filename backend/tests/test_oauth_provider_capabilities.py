"""Opt-in OAuth mechanics: HTTP endpoints are fake; no accounts or secrets required."""
import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from cryptography.fernet import Fernet

from nodes.core.oauth_provider import OAuthContextField, OAuthDeviceSpec, OAuthTokens
from nodes.core.oauth_device import start_device, poll_device
from tests.test_generic_oauth import (
    spec,
    handler,
    CALLBACK,
)  # shared actual-handler fixtures


@pytest.fixture
def transport(monkeypatch):
    requests = []
    responses = []
    original = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        return responses.pop(0)

    factory = lambda **kw: original(transport=httpx.MockTransport(respond), **kw)
    monkeypatch.setattr(httpx, "AsyncClient", factory)
    monkeypatch.setattr("utils.ssrf.guarded_async_client", factory)
    return requests, responses


def token(**extra):
    return httpx.Response(
        200, json={"access_token": "new-access", "refresh_token": "rotated", **extra}
    )


async def test_callback_merchant_and_json_absolute_expiry(spec, transport):
    spec = replace(
        spec,
        context_fields={
            "merchant_id": OAuthContextField(source="callback", pattern=r"[A-Z0-9]+")
        },
        identity_url="https://provider.example/v3/merchants/{merchant_id}",
        name_field="name",
        token_format="json",
        expires_at_field="access_token_expiration",
        refresh_url="https://provider.example/refresh",
        token_grant_fields={
            "authorization_code": ("code",),
            "refresh_token": ("refresh_token",),
        },
        refresh_token_auth="none",
    )
    transport[1].extend(
        [
            token(access_token_expiration=2000000000),
            httpx.Response(200, json={"name": "Merchant"}),
            token(access_token_expiration=2000001000),
        ]
    )
    tokens, name = await spec.exchange(
        "code", CALLBACK, context={"merchant_id": "ABC123"}
    )
    assert name == "Merchant" and tokens.merchant_id == "ABC123"
    assert tokens.expires_at.startswith("2033-")
    assert json.loads(transport[0][0].content) == {
        "code": "code",
        "client_id": "client",
        "client_secret": "secret",
    }
    assert transport[0][1].url.path == "/v3/merchants/ABC123"
    refreshed = await spec.bind_refresh(tokens.model_dump())("rotated")
    assert refreshed.merchant_id == "ABC123"
    assert transport[0][2].url.path == "/refresh"
    assert json.loads(transport[0][2].content) == {
        "refresh_token": "rotated",
        "client_id": "client",
    }


async def test_callback_host_and_token_selected_origin(spec, transport):
    host = OAuthContextField(
        source="callback", kind="host", pattern=r"[a-z0-9-]+\.kommo\.com"
    )
    spec = replace(
        spec,
        context_fields={"referer": host},
        token_url="https://{referer}/oauth2/access_token",
        identity_url="https://{referer}/api/v4/account",
        token_format="json",
    )
    transport[1].extend(
        [token(), httpx.Response(200, json={"account": {"name": "Tenant"}})]
    )
    tokens, _ = await spec.exchange(
        "code", CALLBACK, context={"referer": "company.kommo.com"}
    )
    assert all(request.url.host == "company.kommo.com" for request in transport[0])
    assert tokens.referer == "company.kommo.com"
    with pytest.raises(ValueError):
        await spec.exchange(
            "code", CALLBACK, context={"referer": "company.kommo.com.evil.test"}
        )
    spec = replace(
        spec,
        token_url="https://provider.example/token",
        context_fields={
            "api_base_url_for_customer": OAuthContextField(
                source="token",
                kind="origin",
                pattern=r"https://company-[0-9]+\.api\.gong\.io",
            )
        },
        identity_url="{api_base_url_for_customer}/v2/workspaces",
        name_field="workspaces.0.name",
    )
    transport[1].extend(
        [
            token(api_base_url_for_customer="https://company-17.api.gong.io"),
            httpx.Response(200, json={"workspaces": [{"name": "Workspace"}]}),
        ]
    )
    tokens, name = await spec.exchange("code", CALLBACK)
    assert (
        name == "Workspace"
        and tokens.api_base_url_for_customer == "https://company-17.api.gong.io"
    )
    assert transport[0][-1].url.host == "company-17.api.gong.io"
    transport[1].append(token(api_base_url_for_customer="http://169.254.169.254"))
    with pytest.raises(ValueError):
        await spec.exchange("code", CALLBACK)


async def test_region_inputs_comma_scopes_and_array_identity(spec, transport):
    spec = replace(
        spec,
        context_fields={
            "accounts": OAuthContextField(
                source="input",
                kind="origin",
                choices=("https://accounts.zoho.com", "https://accounts.zoho.eu"),
            )
        },
        token_url="{accounts}/oauth/v2/token",
        identity_url="{accounts}/users",
        scope_separator=",",
    )
    transport[1].extend(
        [
            token(scope="read"),
            httpx.Response(200, json={"account": {"name": "Regional"}}),
        ]
    )
    tokens, _ = await spec.exchange(
        "code", CALLBACK, context={"accounts": "https://accounts.zoho.eu"}
    )
    assert transport[0][0].url.host == "accounts.zoho.eu"
    assert spec.granted_scopes(tokens, ["read"]) == ["read"]
    with pytest.raises(ValueError):
        await spec.exchange(
            "code", CALLBACK, context={"accounts": "https://accounts.zoho.evil.test"}
        )
    spec = replace(
        spec,
        context_fields={
            "host": OAuthContextField(
                source="token",
                kind="host",
                choices=("www.wrike.com", "app-eu.wrike.com"),
            )
        },
        token_url="https://login.wrike.com/oauth2/token",
        refresh_url="https://{host}/oauth2/token",
        identity_url="https://{host}/api/v4/contacts?me=true",
        name_field="data.0.firstName",
    )
    transport[1].extend(
        [
            token(host="app-eu.wrike.com", scope="read,other"),
            httpx.Response(200, json={"data": [{"firstName": "Person"}]}),
        ]
    )
    tokens, name = await spec.exchange("code", CALLBACK)
    assert tokens.scope == "read other"
    assert name == "Person" and spec.granted_scopes(tokens, ["read"]) == [
        "read",
        "other",
    ]
    transport[1].append(token())  # A refresh can omit unchanged routing context.
    assert (
        await spec.bind_refresh(tokens.model_dump())("rotated")
    ).host == "app-eu.wrike.com"
    assert transport[0][-1].url.host == "app-eu.wrike.com"
    with pytest.raises(ValueError, match="grant"):
        spec.granted_scopes(OAuthTokens(access_token="fake", scope="other"), ["read"])


async def test_tenant_path_is_encoded_and_dynamic_http_is_guarded(spec, monkeypatch):
    guarded = Mock()
    monkeypatch.setattr("utils.ssrf.guarded_async_client", guarded)
    spec = replace(
        spec,
        context_fields={
            "host": OAuthContextField(
                source="input", kind="host", pattern=r"[a-z0-9-]+\.workday\.com"
            ),
            "tenant": OAuthContextField(source="input", pattern=r"[a-zA-Z0-9_-]+"),
        },
        authorize_url="https://{host}/{tenant}/authorize",
        token_url="https://{host}/{tenant}/token",
        identity_url="https://{host}/{tenant}/me",
    )
    context = spec.validate_context(
        {"host": "example.workday.com", "tenant": "company"}
    )
    assert (
        spec.token_request(
            {"grant_type": "authorization_code", "code": "code"}, context=context
        )["url"]
        == "https://example.workday.com/company/token"
    )
    spec._client(spec.token_url)
    guarded.assert_called_once_with(timeout=30)
    with pytest.raises(ValueError):
        spec.validate_context({"host": "example.workday.com", "tenant": "../other"})


@pytest.mark.parametrize(
    "value",
    [
        "evil.test",
        "tenant.kommo.com@evil.test",
        "tenant.kommo.com:443",
        "tenant.kommo.com/path",
        "127.0.0.1",
        "tenant.kommo.com?x=y",
        "tenant.kommo.com#x",
        "tenant.kommo.com&x=1",
        "tenant..kommo.com",
    ],
)
def test_untrusted_hosts_refused(value):
    field = OAuthContextField(source="callback", kind="host", pattern=r".*")
    if value in ("evil.test", "127.0.0.1"):
        field = replace(field, pattern=r"[a-z0-9-]+\.kommo\.com")
    with pytest.raises(ValueError):
        field.validate(value)


def test_declaration_rejects_missing_identity_unbounded_context_and_protocol_overrides(
    spec,
):
    with pytest.raises(ValueError, match="identity_url"):
        replace(spec, identity_url=None)
    with pytest.raises(ValueError, match="allowlist"):
        OAuthContextField(source="input")
    with pytest.raises(ValueError, match="reserved"):
        replace(
            spec,
            context_fields={
                "access_token": OAuthContextField(source="input", pattern=".*")
            },
        )
    with pytest.raises(ValueError, match="Unknown OAuth URL"):
        replace(spec, identity_url="https://{unknown}/me")
    with pytest.raises(ValueError, match="authority"):
        replace(
            spec,
            token_url="https://{tenant}/token",
            context_fields={
                "tenant": OAuthContextField(source="input", pattern="[a-z]+")
            },
        )
    with pytest.raises(ValueError, match="protocol"):
        replace(
            spec,
            device=OAuthDeviceSpec(
                authorization_url="https://provider.example/device",
                params={"client_secret": "forbidden"},
            ),
        )


class MemoryRedis:
    """Only external storage is fake; production locks, handler and transport run normally."""

    def __init__(self):
        self.values = {}
        self.locks = {}

    async def set(self, key, value, **kw):
        if not kw.get("nx") or key not in self.values:
            self.values[key] = value

    async def incr(self, key):
        self.values[key] += 1
        return self.values[key]

    async def get(self, key):
        return self.values.get(key)

    async def delete(self, key):
        self.values.pop(key, None)

    def lock(self, key, **kw):
        lock = self.locks.setdefault(key, asyncio.Lock())
        return SimpleNamespace(acquire=lock.acquire, release=self.release(lock))

    def release(self, lock):
        async def release():
            lock.release()

        return release


@pytest.fixture
def device(spec, monkeypatch):
    from utils.encryption import CredentialEncryption

    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    redis = MemoryRedis()
    monkeypatch.setattr("nodes.core.oauth_device._redis", lambda: redis)
    monkeypatch.setattr("nodes.core.oauth_device._encryption", CredentialEncryption)
    now = [1000.0]
    monkeypatch.setattr("nodes.core.oauth_device.time.time", lambda: now[0])
    spec = replace(
        spec,
        authorize_url=None,
        client_id_env="",
        client_secret_env="",
        redirect_uri_env="",
        token_auth="none",
        token_format="json",
        rotates_refresh_tokens=False,
        device=OAuthDeviceSpec(authorization_url="https://provider.example/device"),
    )
    return spec, redis, now


async def begin(device, transport):
    transport[1].append(
        httpx.Response(
            200,
            json={
                "device_code": "never-in-browser",
                "user_code": "ABCD",
                "verification_uri": "https://provider.example/activate",
                "interval": 5,
                "expires_in": 60,
            },
        )
    )
    return await start_device(device[0], binding="owner", scopes=["read"], context={})


async def test_device_pending_slowdown_success_single_use(device, transport):
    spec, redis, now = device
    started = await begin(device, transport)
    assert "never-in-browser" not in str(started) and "never-in-browser" not in str(
        redis.values
    )
    assert json.loads(transport[0][0].content) == {"scope": "read"}
    complete = AsyncMock(return_value={"credential_id": "stored"})
    poll = lambda: poll_device(
        spec,
        binding="owner",
        authorization_id=started["authorization_id"],
        complete=complete,
    )
    assert (await poll())["status"] == "pending"
    assert len(transport[0]) == 1
    for error, interval in [("authorization_pending", 5), ("slow_down", 10)]:
        now[0] += 5
        transport[1].append(httpx.Response(400, json={"error": error}))
        result = await poll()
        assert result["interval"] == interval
    now[0] += 5
    assert (await poll())["interval"] == 5  # Still too early after slow_down.
    now[0] += 5
    transport[1].extend(
        [token(), httpx.Response(200, json={"account": {"name": "Device account"}})]
    )
    assert (await poll())["credential_id"] == "stored"
    complete.assert_awaited_once()
    assert (await poll())["status"] == "expired"
    body = json.loads(transport[0][-2].content)
    assert body == {
        "device_code": "never-in-browser",
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }


@pytest.mark.parametrize(
    "error,status", [("expired_token", "expired"), ("access_denied", "denied")]
)
async def test_device_definitive_endings(device, transport, error, status):
    started = await begin(device, transport)
    device[2][0] += 5
    transport[1].append(httpx.Response(400, json={"error": error}))
    complete = AsyncMock()
    assert (
        await poll_device(
            device[0],
            binding="owner",
            authorization_id=started["authorization_id"],
            complete=complete,
        )
    )["status"] == status
    complete.assert_not_awaited()


async def test_device_binding_expiry_and_no_redis(device, transport, monkeypatch):
    started = await begin(device, transport)
    with pytest.raises(ValueError, match="belong"):
        await poll_device(
            device[0],
            binding="someone-else",
            authorization_id=started["authorization_id"],
            complete=AsyncMock(),
        )
    device[2][0] += 61
    assert (
        await poll_device(
            device[0],
            binding="owner",
            authorization_id=started["authorization_id"],
            complete=AsyncMock(),
        )
    )["status"] == "expired"
    monkeypatch.undo()
    monkeypatch.setattr("utils.redis_client.get_shared_redis", lambda: None)
    with pytest.raises(ValueError, match="Redis"):
        await start_device(device[0], binding="owner", scopes=["read"], context={})


async def test_context_free_declarations_preserve_specialized_transport_signatures(spec, transport):
    """Productboard specializes all three original methods without context kwargs."""
    from dataclasses import fields
    from nodes.core.oauth_provider import OAuthProviderSpec

    calls = []

    class LegacySpec(OAuthProviderSpec):
        def token_request(self, grant):
            calls.append("request")
            return super().token_request(grant)

        async def _tokens(self, grant):
            calls.append("tokens")
            return await super()._tokens(grant)

        async def account_name(self, access_token):
            calls.append("identity")
            return await super().account_name(access_token)

    legacy = LegacySpec(**{field.name: getattr(spec, field.name) for field in fields(spec)})
    _, responses = transport
    responses.extend([
        httpx.Response(200, json={"access_token": "access", "refresh_token": "refresh"}),
        httpx.Response(200, json={"account": {"name": "Existing account"}}),
        httpx.Response(200, json={"access_token": "renewed", "refresh_token": "rotated"}),
    ])
    _, name = await legacy.exchange("code", CALLBACK)
    renewed = await legacy.refresh("refresh")
    assert name == "Existing account"
    assert renewed.refresh_token == "rotated"
    assert calls == ["tokens", "request", "identity", "tokens", "request"]


def test_existing_declarations_metadata_matches_prechange_snapshot():
    from pathlib import Path
    from nodes.core.oauth_registry import get_oauth_provider

    snapshot = json.loads(
        (Path(__file__).parent / "fixtures/oauth_legacy_metadata.json").read_text()
    )
    for provider, expected in snapshot.items():
        assert get_oauth_provider(provider).public_metadata() == expected


async def test_dynamic_identity_uses_real_ssrf_guard_for_private_address(
    spec, monkeypatch
):
    from utils.ssrf import SSRFError

    monkeypatch.delenv("OUTBOUND_ALLOW_PRIVATE_IPS", raising=False)
    monkeypatch.delenv("HTTP_NODE_ALLOW_PRIVATE_IPS", raising=False)
    spec = replace(
        spec,
        identity_url="https://{host}/me",
        context_fields={
            "host": OAuthContextField(source="token", kind="host", pattern=".*")
        },
    )
    with pytest.raises(SSRFError, match="non-public"):
        await spec.account_name("fake", context={"host": "169.254.169.254"})


async def test_concurrent_polls_only_store_once(device, transport):
    started = await begin(device, transport)
    device[2][0] += 5
    transport[1].extend(
        [token(), httpx.Response(200, json={"account": {"name": "Person"}})]
    )
    complete = AsyncMock(return_value={"credential_id": "once"})

    async def poll():
        return await poll_device(
            device[0],
            binding="owner",
            authorization_id=started["authorization_id"],
            complete=complete,
        )

    results = await asyncio.gather(poll(), poll())
    assert sorted(r["status"] for r in results) == ["completed", "expired"]
    complete.assert_awaited_once()


async def test_generic_device_handler_stores_encrypted_context_and_refuses_partial_grant(
    handler, device, transport, monkeypatch
):
    from wss.receiver.client_events import (
        OAuthDeviceStartRequest,
        OAuthDevicePollRequest,
    )

    spec = replace(
        device[0],
        context_fields={"tenant": OAuthContextField(source="input", pattern="[a-z]+")},
    )
    monkeypatch.setattr(
        "wss.handlers.oauth.generic_oauth_handler.get_oauth_provider", lambda _: spec
    )
    create = AsyncMock(return_value=({"id": "credential", "name": "Person"}, None))
    monkeypatch.setattr(
        "repositories.credentials.create_credential_with_limit_check", create
    )
    transport[1].append(
        httpx.Response(
            200,
            json={
                "device_code": "secret-device",
                "user_code": "ABCD",
                "verification_uri": "https://provider.example/activate",
                "expires_in": 60,
            },
        )
    )
    await handler.start_device_authorization(
        "sid",
        OAuthDeviceStartRequest(
            provider="example", context={"tenant": "company"}, request_id="start"
        ),
    )
    answer = handler.sio.emit.call_args.args[1]["data"]
    assert answer["success"] and "secret-device" not in str(answer)
    device[2][0] += 5
    transport[1].extend(
        [token(scope="read"), httpx.Response(200, json={"account": {"name": "Person"}})]
    )
    await handler.poll_device_authorization(
        "sid",
        OAuthDevicePollRequest(
            provider="example",
            authorization_id=answer["authorization_id"],
            request_id="poll",
        ),
    )
    assert handler.sio.emit.call_args.args[1]["data"]["credential_id"] == "credential"
    encrypted = create.call_args.args[5]
    saved = handler.encryption.decrypt_credential(encrypted)
    assert saved["tenant"] == "company" and saved["scope"] == "read"
    create.reset_mock()
    transport[1].append(
        httpx.Response(
            200,
            json={
                "device_code": "secret-device",
                "user_code": "ABCD",
                "verification_uri": "https://provider.example/activate",
                "expires_in": 60,
            },
        )
    )
    await handler.start_device_authorization(
        "sid",
        OAuthDeviceStartRequest(
            provider="example", context={"tenant": "company"}, request_id="start2"
        ),
    )
    answer = handler.sio.emit.call_args.args[1]["data"]
    device[2][0] += 5
    transport[1].extend(
        [token(scope=""), httpx.Response(200, json={"account": {"name": "Person"}})]
    )
    await handler.poll_device_authorization(
        "sid",
        OAuthDevicePollRequest(
            provider="example",
            authorization_id=answer["authorization_id"],
            request_id="poll2",
        ),
    )
    assert not handler.sio.emit.call_args.args[1]["data"]["success"]
    create.assert_not_awaited()


async def test_context_refresh_uses_manual_choke_point_and_rebases_cas(
    handler, spec, transport, monkeypatch
):
    import copy
    from wss.receiver.client_events import OAuthRefreshRequest

    spec = replace(
        spec,
        context_fields={
            "host": OAuthContextField(
                source="token",
                kind="host",
                choices=("old.provider.example", "new.provider.example"),
            )
        },
        refresh_url="https://{host}/refresh",
    )
    monkeypatch.setattr(
        "wss.handlers.oauth.generic_oauth_handler.get_oauth_provider", lambda _: spec
    )
    credential = {
        "credential_type": "example_oauth",
        "access_token": "old",
        "refresh_token": "old-refresh",
        "expires_at": "2000-01-01T00:00:00+00:00",
        "token_version": 7,
        "host": "old.provider.example",
    }
    monkeypatch.setattr(
        "utils.credential_loader.load_credential",
        AsyncMock(
            side_effect=[
                credential.copy(),
                credential.copy(),
                {**credential, "token_version": 8, "label": "concurrent edit"},
            ]
        ),
    )
    writes = []

    async def persist(**kw):
        writes.append(copy.deepcopy(kw))
        return (0, None) if len(writes) == 1 else (1, None)

    monkeypatch.setattr("utils.credentials.update_credential_data_detailed", persist)
    audit = AsyncMock()
    monkeypatch.setattr("nodes.core.oauth_refresh.record_refresh_event", audit)
    transport[1].append(token(host="new.provider.example", expires_in=3600))
    await handler.refresh_oauth_token(
        "sid",
        OAuthRefreshRequest(
            provider="example", credential_id="context-refresh", request_id="refresh"
        ),
    )
    assert handler.sio.emit.call_args.args[1]["data"]["success"]
    assert transport[0][0].url.host == "old.provider.example"
    assert [write["expected_token_version"] for write in writes] == [7, 8]
    assert writes[-1]["new_data"]["host"] == "new.provider.example"
    assert writes[-1]["new_data"]["refresh_token"] == "rotated"
    assert writes[-1]["new_data"]["label"] == "concurrent edit"
    assert audit.call_args.args[0]["caller_path"] == "manual_refresh"


async def test_connect_link_device_uses_bound_repository_store(
    handler, device, transport, monkeypatch
):
    from fastapi import HTTPException
    from utils import credential_request_routes as routes
    from wss.handlers.oauth.generic_oauth_handler import GenericOAuthHandler

    spec, redis, now = device
    row = {
        "id": "link-id",
        "credential_type": "example_oauth",
        "requester_id": "requester",
        "target_email": "owner@example.test",
        "metadata": {},
    }
    pool = await handler.get_pool()
    monkeypatch.setattr(routes, "get_native_pool", lambda: pool)
    monkeypatch.setattr(GenericOAuthHandler, "get_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(
        "wss.handlers.oauth.generic_oauth_handler.get_oauth_provider", lambda _: spec
    )
    monkeypatch.setattr("nodes.core.oauth_registry.get_oauth_provider", lambda _: spec)
    monkeypatch.setattr(routes, "_load_active_request", AsyncMock(return_value=row))
    monkeypatch.setattr(routes, "_get_sibling_methods", lambda _: [])
    monkeypatch.setattr(routes, "_get_oauth_provider", lambda _: "example")
    monkeypatch.setattr(routes, "_oauth_app", AsyncMock(return_value=None))
    monkeypatch.setattr(
        routes, "_provided_credential_owner", AsyncMock(return_value="owner")
    )
    monkeypatch.setattr(
        routes, "_requester_effective_tier", AsyncMock(return_value="free")
    )
    monkeypatch.setattr("utils.redis_client.get_shared_redis", lambda: redis)
    store = AsyncMock(return_value="stored-for-link")
    monkeypatch.setattr(routes, "_store_provided", store)
    monkeypatch.setattr(
        routes,
        "_fulfilled",
        AsyncMock(
            return_value={"status": "success", "credential_id": "stored-for-link"}
        ),
    )
    transport[1].append(
        httpx.Response(
            200,
            json={
                "device_code": "private-device",
                "user_code": "ABCD",
                "verification_uri": "https://provider.example/activate",
                "expires_in": 60,
            },
        )
    )
    started = await routes.declared_device_start(
        "link-token", routes.DeclaredDeviceBody(credential_type="example_oauth")
    )
    assert started["success"] and "private-device" not in str(started)
    # A device id from this link cannot be polled by a different link, even for the same owner.
    monkeypatch.setattr(
        routes,
        "_load_active_request",
        AsyncMock(return_value={**row, "id": "other-link"}),
    )
    with pytest.raises(HTTPException):
        await routes.declared_device_poll(
            "other",
            routes.DeclaredDeviceBody(
                credential_type="example_oauth",
                authorization_id=started["authorization_id"],
            ),
        )
    monkeypatch.setattr(routes, "_load_active_request", AsyncMock(return_value=row))
    now[0] += 5
    transport[1].extend(
        [token(), httpx.Response(200, json={"account": {"name": "Linked account"}})]
    )
    result = await routes.declared_device_poll(
        "link-token",
        routes.DeclaredDeviceBody(
            credential_type="example_oauth",
            authorization_id=started["authorization_id"],
        ),
    )
    assert (
        result["status"] == "completed" and result["credential_id"] == "stored-for-link"
    )
    store.assert_awaited_once()
    assert store.call_args.args[2:5] == ("owner", "example_oauth", "Linked account")
    from nodes.core.oauth_device import _encryption

    assert (
        _encryption().decrypt_credential(store.call_args.args[5])["access_token"]
        == "new-access"
    )
    with pytest.raises(HTTPException, match="400"):
        await routes.declared_device_start(
            "link-token", routes.DeclaredDeviceBody(credential_type="other_oauth")
        )

    monkeypatch.setattr(
        routes,
        "_oauth_app",
        AsyncMock(
            return_value={"client_id": "custom", "client_secret": "unused-test-value"}
        ),
    )
    with pytest.raises(HTTPException) as failure:
        await routes.declared_device_start(
            "link-token", routes.DeclaredDeviceBody(credential_type="example_oauth")
        )
    assert failure.value.status_code == 400
    monkeypatch.setattr(routes, "_oauth_app", AsyncMock(return_value=None))
    monkeypatch.setattr(redis, "incr", AsyncMock(return_value=21))
    with pytest.raises(HTTPException) as failure:
        await routes.declared_device_start(
            "link-token", routes.DeclaredDeviceBody(credential_type="example_oauth")
        )
    assert failure.value.status_code == 429
    from redis.exceptions import ConnectionError

    monkeypatch.setattr(
        redis, "incr", AsyncMock(side_effect=ConnectionError("offline"))
    )
    with pytest.raises(HTTPException) as failure:
        await routes.declared_device_start(
            "link-token", routes.DeclaredDeviceBody(credential_type="example_oauth")
        )
    assert failure.value.status_code == 503


async def test_device_provider_refuses_code_exchange_and_still_requires_identity(
    device,
):
    with pytest.raises(ValueError, match="device authorization"):
        await device[0].exchange("code", CALLBACK)
    with pytest.raises(ValueError, match="identity_url"):
        replace(device[0], identity_url=None)


async def test_device_state_has_bounded_lifetime(device, transport):
    transport[1].append(
        httpx.Response(
            200,
            json={
                "device_code": "private",
                "user_code": "ABCD",
                "verification_uri": "https://provider.example/activate",
                "expires_in": 86401,
            },
        )
    )
    with pytest.raises(ValueError, match="lifetime"):
        await start_device(device[0], binding="owner", scopes=["read"], context={})
    assert not device[1].values


async def test_device_state_is_resealed_when_polled_after_a_dual_key_deploy(
    device, transport, monkeypatch
):
    import os

    started = await begin(device, transport)
    previous = os.environ["CREDENTIALS_ENCRYPTION_KEY"]
    primary = Fernet.generate_key()
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", primary.decode())
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY_OLD", previous)
    device[2][0] += 5
    transport[1].append(httpx.Response(400, json={"error": "authorization_pending"}))

    async def poll():
        return await poll_device(
            device[0],
            binding="owner",
            authorization_id=started["authorization_id"],
            complete=AsyncMock(return_value={"credential_id": "stored"}),
        )

    assert (await poll())["status"] == "pending"
    key = "oauth:device:" + started["authorization_id"]
    assert (
        json.loads(Fernet(primary).decrypt(device[1].values[key].encode()))["binding"]
        == "owner"
    )
    monkeypatch.delenv("CREDENTIALS_ENCRYPTION_KEY_OLD")
    device[2][0] += 5
    transport[1].extend(
        [token(), httpx.Response(200, json={"account": {"name": "Person"}})]
    )
    assert (await poll())["status"] == "completed"
