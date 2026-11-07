"""Generic OAuth discovery, transport, storage, and rotation/CAS contracts."""
import copy
import importlib
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import parse_qs
from unittest.mock import AsyncMock

import httpx
import pytest

from nodes.core.oauth_provider import OAuthProviderSpec
from nodes.core.oauth_registry import discover_oauth_providers, get_oauth_provider
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.core.oauth_refresh import (
    RotatedRefreshTokenMissing,
    ensure_fresh_oauth_token,
)
from wss.receiver.client_events import (
    OAuthExchangeRequest,
    OAuthRefreshRequest,
    OAuthValidateRequest,
)
from wss.receiver.event_routing import EVENT_ROUTING, Handler
from wss.handlers.oauth.generic_oauth_handler import GenericOAuthHandler

CALLBACK = "https://app.example/api/auth/oauth/example/callback"


@pytest.fixture
def spec(monkeypatch):
    for key, value in {
        "EXAMPLE_CLIENT_ID": "client",
        "EXAMPLE_CLIENT_SECRET": "secret",
        "EXAMPLE_REDIRECT_URI": CALLBACK,
    }.items():
        monkeypatch.setenv(key, value)
    return OAuthProviderSpec(
        provider="example",
        authorize_url="https://provider.example/authorize",
        token_url="https://provider.example/token",
        scope_registry=ScopeRegistry("example", {"read": ScopeRequirement(("read",))}),
        client_id_env="EXAMPLE_CLIENT_ID",
        client_secret_env="EXAMPLE_CLIENT_SECRET",
        redirect_uri_env="EXAMPLE_REDIRECT_URI",
        credential_type="example_oauth",
        name_field="account.name",
        identity_url="https://provider.example/me",
        rotates_refresh_tokens=True,
        token_fields=("organization_id",),
    )


@pytest.fixture
def endpoint(monkeypatch):
    """Strict fake endpoint receives real httpx requests, including auth/form encoding."""
    requests = []
    payload = {
        "access_token": "access-new",
        "refresh_token": "refresh-new",
        "expires_in": 3600,
        "scope": "read",
        "organization_id": "org-new",
    }

    def respond(request):
        requests.append(request)
        if request.url.path == "/me":
            assert request.headers["authorization"] == "Bearer access-new"
            return httpx.Response(200, json={"account": {"name": "Example account"}})
        assert request.url.path == "/token"
        assert parse_qs(request.content.decode())["grant_type"][0] in (
            "authorization_code",
            "refresh_token",
        )
        return httpx.Response(200, json=payload)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(respond), **kw),
    )
    return requests, payload


async def test_exchange_identity_and_public_metadata(spec, endpoint):
    tokens, name = await spec.exchange("code", CALLBACK)
    assert name == "Example account"
    assert tokens.organization_id == "org-new"
    assert parse_qs(endpoint[0][0].content.decode()) == {
        "grant_type": ["authorization_code"],
        "code": ["code"],
        "redirect_uri": [CALLBACK],
        "client_id": ["client"],
        "client_secret": ["secret"],
    }
    assert "clientSecretEnv" not in spec.public_metadata()
    assert spec.public_metadata()["scopes"] == ["read"]


async def test_pkce_basic_auth_extra_params(spec, endpoint):
    spec = replace(
        spec, pkce=True, token_auth="basic", token_params={"audience": "api"}
    )
    with pytest.raises(ValueError, match="verifier"):
        await spec.exchange("code", CALLBACK)
    await spec.exchange("code", CALLBACK, "a" * 43)
    request = endpoint[0][0]
    assert request.headers["authorization"] == "Basic Y2xpZW50OnNlY3JldA=="
    body = parse_qs(request.content.decode())
    assert body["code_verifier"] == ["a" * 43]
    assert body["audience"] == ["api"]
    assert "client_secret" not in body


async def test_redirect_mismatch_never_sends_code(spec, endpoint):
    with pytest.raises(ValueError, match="redirect URI"):
        await spec.exchange("code", "https://attacker.example/callback")
    assert endpoint[0] == []


async def test_token_field_identity_and_missing_name(spec, endpoint):
    _, name = await replace(
        spec, identity_url=None, name_field="organization_id"
    ).exchange("code", CALLBACK)
    assert name == "org-new"
    with pytest.raises(KeyError):
        await replace(spec, name_field="absent").exchange("code", CALLBACK)


async def test_rotation_missing_successor_refused(spec, endpoint):
    del endpoint[1]["refresh_token"]
    with pytest.raises(RotatedRefreshTokenMissing):
        await spec.refresh("consumed")
    assert (
        await replace(spec, rotates_refresh_tokens=False).refresh("reusable")
    ).refresh_token is None


async def test_refresh_cas_rebases_rotation(spec, endpoint, monkeypatch):
    credential = {
        "credential_type": "example_oauth",
        "access_token": "old",
        "refresh_token": "old-refresh",
        "expires_at": "2000-01-01T00:00:00+00:00",
        "token_version": 7,
    }
    loads = [
        copy.deepcopy(credential),
        {**credential, "token_version": 8, "label": "concurrent edit"},
    ]
    writes = []

    async def persist(**kwargs):
        writes.append(copy.deepcopy(kwargs))
        return (0, None) if len(writes) == 1 else (1, None)

    monkeypatch.setattr(
        "utils.credential_loader.load_credential", AsyncMock(side_effect=loads)
    )
    monkeypatch.setattr("utils.credentials.update_credential_data_detailed", persist)
    monkeypatch.setattr("nodes.core.oauth_refresh.record_refresh_event", AsyncMock())
    token = await ensure_fresh_oauth_token(
        pool=object(),
        credential_id="generic-cas",
        user_id="user",
        provider=spec.provider,
        credential=credential,
        refresh=spec.refresh,
        additional_token_fields=spec.token_fields,
    )
    assert token == "access-new"
    assert [w["expected_token_version"] for w in writes] == [7, 8]
    assert writes[1]["new_data"]["refresh_token"] == "refresh-new"
    assert writes[1]["new_data"]["organization_id"] == "org-new"
    assert writes[1]["new_data"]["label"] == "concurrent edit"
    assert len(endpoint[0]) == 1
    assert parse_qs(endpoint[0][0].content.decode())["refresh_token"] == ["old-refresh"]


async def test_persist_failure_fatal(spec, endpoint, monkeypatch):
    cred = {
        "access_token": "old",
        "refresh_token": "old-refresh",
        "expires_at": "2000-01-01T00:00:00+00:00",
        "token_version": 1,
    }
    monkeypatch.setattr(
        "utils.credential_loader.load_credential", AsyncMock(return_value=cred.copy())
    )
    monkeypatch.setattr(
        "utils.credentials.update_credential_data_detailed",
        AsyncMock(return_value=(0, "database_error")),
    )
    monkeypatch.setattr("nodes.core.oauth_refresh.record_refresh_event", AsyncMock())
    with pytest.raises(ValueError, match="could not be persisted"):
        await ensure_fresh_oauth_token(
            pool=object(),
            credential_id="generic-failed",
            user_id="user",
            credential=cred,
            refresh=spec.refresh,
            provider=spec.provider,
        )


def test_unknown_provider():
    with pytest.raises(ValueError, match="Unknown OAuth provider"):
        get_oauth_provider("unknown-example")


def test_discovery_prefilter_duplicates_invalid(tmp_path, monkeypatch, spec):
    (tmp_path / "ignored_oauth.py").write_text(
        'raise RuntimeError("must not import legacy module")'
    )
    for name in ("first", "second"):
        (tmp_path / f"{name}_oauth.py").write_text("OAUTH_PROVIDER = declaration")
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: SimpleNamespace(OAUTH_PROVIDER=spec, __name__=name),
    )
    with pytest.raises(ValueError, match="Duplicate OAuth"):
        discover_oauth_providers(tmp_path, "fake")
    (tmp_path / "second_oauth.py").unlink()
    assert discover_oauth_providers(tmp_path, "fake") == {"example": spec}
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: SimpleNamespace(OAUTH_PROVIDER=None, __name__=name),
    )
    with pytest.raises(ValueError, match="Invalid OAUTH_PROVIDER"):
        discover_oauth_providers(tmp_path, "fake")


def test_bespoke_route_retained(monkeypatch):
    assert EVENT_ROUTING["API"]["attio:oauth:exchange"] == Handler.ATTIO_OAUTH
    assert EVENT_ROUTING["API"]["oauth:exchange"] == Handler.GENERIC_OAUTH
    from utils.link_sign_in import exchange_request, _handler
    from wss.receiver.client_events import AttioOAuthExchangeRequest
    from wss.handlers.oauth.attio_oauth_handler import AttioOAuthHandler

    monkeypatch.setattr(
        "wss.handlers.oauth.attio_oauth_handler.get_encryption", lambda: object()
    )
    assert exchange_request("attio") is AttioOAuthExchangeRequest
    assert _handler("attio", object()).__func__ is AttioOAuthHandler.exchange_oauth_code


@pytest.fixture
def handler(monkeypatch, spec):
    from utils.encryption import CredentialEncryption
    from cryptography.fernet import Fernet

    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(
        "wss.handlers.oauth.generic_oauth_handler.get_encryption", CredentialEncryption
    )
    monkeypatch.setattr(
        "wss.handlers.oauth.generic_oauth_handler.get_oauth_provider",
        lambda provider: spec
        if provider == spec.provider
        else get_oauth_provider(provider),
    )

    @asynccontextmanager
    async def acquire():
        yield object()

    sio = SimpleNamespace(
        get_session=AsyncMock(return_value={"user_id": "user"}), emit=AsyncMock()
    )
    handler = GenericOAuthHandler(sio)
    handler.get_pool = AsyncMock(return_value=SimpleNamespace(acquire=acquire))
    return handler


async def test_handler_encrypted_repository_store(handler, spec, endpoint, monkeypatch):
    saved = []

    async def create(*args):
        saved.append(args)
        return {"id": "credential", "name": args[4]}, None

    monkeypatch.setattr(
        "repositories.credentials.create_credential_with_limit_check", create
    )
    await handler.exchange_oauth_code(
        "sid",
        OAuthExchangeRequest(
            provider="example", code="code", redirect_uri=CALLBACK, request_id="request"
        ),
    )
    assert saved[0][3:5] == ("example_oauth", "Example account")
    assert (
        handler.encryption.decrypt_credential(saved[0][5])["refresh_token"]
        == "refresh-new"
    )
    reply = handler.sio.emit.call_args.args[1]
    assert reply["data"]["credential_id"] == "credential"
    assert "access-new" not in str(reply)


async def test_handler_unknown_and_mismatched_credential(
    handler, monkeypatch, endpoint
):
    await handler.exchange_oauth_code(
        "sid",
        OAuthExchangeRequest(
            provider="unknown-example",
            code="code",
            redirect_uri=CALLBACK,
            request_id="request",
        ),
    )
    assert not handler.sio.emit.call_args.args[1]["data"]["success"]
    monkeypatch.setattr(
        "utils.credential_loader.load_credential",
        AsyncMock(return_value={"credential_type": "attio_oauth"}),
    )
    await handler.refresh_oauth_token(
        "sid",
        OAuthRefreshRequest(
            provider="example", credential_id="credential", request_id="refresh"
        ),
    )
    assert not handler.sio.emit.call_args.args[1]["data"]["success"]
    await handler.validate_oauth_token(
        "sid",
        OAuthValidateRequest(
            provider="example", credential_id="credential", request_id="validate"
        ),
    )
    assert not handler.sio.emit.call_args.args[1]["data"]["valid"]
    assert not endpoint[0]


async def test_manual_handler_refresh_uses_audited_cas(handler, endpoint, monkeypatch):
    cred = {
        "credential_type": "example_oauth",
        "access_token": "old",
        "refresh_token": "old-refresh",
        "expires_at": "2000-01-01T00:00:00+00:00",
        "token_version": 4,
    }
    monkeypatch.setattr(
        "utils.credential_loader.load_credential",
        AsyncMock(side_effect=lambda *args: cred.copy()),
    )
    persist = AsyncMock(return_value=(1, None))
    audit = AsyncMock()
    monkeypatch.setattr("utils.credentials.update_credential_data_detailed", persist)
    monkeypatch.setattr("nodes.core.oauth_refresh.record_refresh_event", audit)
    await handler.refresh_oauth_token(
        "sid",
        OAuthRefreshRequest(
            provider="example", credential_id="manual-generic", request_id="refresh"
        ),
    )
    assert handler.sio.emit.call_args.args[1]["data"]["success"]
    assert persist.call_args.kwargs["expected_token_version"] == 4
    assert persist.call_args.kwargs["new_data"]["refresh_token"] == "refresh-new"
    assert audit.call_args.args[0]["caller_path"] == "manual_refresh"


async def test_public_sign_in_uses_same_repository_store(
    handler, spec, endpoint, monkeypatch
):
    from utils.link_sign_in import sign_in, exchange_request

    monkeypatch.setattr(
        "nodes.core.oauth_registry.oauth_providers", lambda: {"example": spec}
    )
    monkeypatch.setattr(GenericOAuthHandler, "get_pool", handler.get_pool)
    stored = []

    async def store(credential_type, name, encrypted, metadata):
        stored.append((credential_type, name, encrypted, metadata))
        return {"id": "provided", "name": name}, None

    try:
        credential_id, response = await sign_in(
            "example",
            {"provider": "attacker", "code": "code", "redirect_uri": CALLBACK},
            user_id="requester",
            tier="free",
            store=store,
        )
        assert credential_id == "provided"
        assert response["success"]
        assert stored[0][:2] == ("example_oauth", "Example account")
        assert (
            handler.encryption.decrypt_credential(stored[0][2])["refresh_token"]
            == "refresh-new"
        )
    finally:
        exchange_request.cache_clear()


async def test_validate_uses_actual_expiry_not_refresh_buffer(
    handler, endpoint, monkeypatch
):
    from datetime import datetime, timedelta, timezone

    expires = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    credential = {
        "credential_type": "example_oauth",
        "access_token": "access-new",
        "expires_at": expires,
    }
    monkeypatch.setattr(
        "utils.credential_loader.load_credential", AsyncMock(return_value=credential)
    )
    await handler.validate_oauth_token(
        "sid",
        OAuthValidateRequest(
            provider="example", credential_id="credential", request_id="validate"
        ),
    )
    assert handler.sio.emit.call_args.args[1]["data"] == {
        "valid": True,
        "expired": False,
        "message": None,
    }
    assert [request.url.path for request in endpoint[0]] == ["/me"]


async def test_token_field_validation_requires_an_access_token(
    handler, spec, monkeypatch
):
    monkeypatch.setattr(
        "wss.handlers.oauth.generic_oauth_handler.get_oauth_provider",
        lambda _: replace(spec, identity_url=None),
    )
    monkeypatch.setattr(
        "utils.credential_loader.load_credential",
        AsyncMock(return_value={"credential_type": "example_oauth"}),
    )
    await handler.validate_oauth_token(
        "sid",
        OAuthValidateRequest(
            provider="example", credential_id="credential", request_id="validate"
        ),
    )
    assert not handler.sio.emit.call_args.args[1]["data"]["valid"]
