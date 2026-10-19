"""Verify install authentication, encrypted storage and owner-scoped reconnect.

Provider HTTP is mocked; persistence and duplicate/ownership checks run against
the isolated Postgres testcontainer, never production or customer accounts.
"""

import asyncio
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
import respx
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from tests.fixtures.real_db_fixture import real_database  # noqa: F401
from utils import pipedrive_connection as connection
from utils import pipedrive_install as install
from utils.encryption import get_encryption
from nodes.oauth.pipedrive_oauth import (
    PIPEDRIVE_TOKEN_URL,
    exchange_code_for_tokens,
    refresh_access_token,
)
from repositories.credentials import CredentialsRepo
from wss.handlers.oauth import pipedrive_oauth_handler as handler_module
from wss.receiver.client_events import PipedriveOAuthExchangeRequest


CALLBACK = "https://frontend.example.test/api/auth/pipedrive/callback"
DOMAIN = "https://test-company.pipedrive.com"


def request(authorization="Bearer test-session"):
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/credential-request/pipedrive/install/exchange",
            "headers": [(b"authorization", authorization.encode())],
        }
    )


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("PIPEDRIVE_CLIENT_ID", "fixture-client")
    monkeypatch.setenv("PIPEDRIVE_CLIENT_SECRET", "fixture-secret")
    monkeypatch.setenv("PIPEDRIVE_REDIRECT_URI", CALLBACK)
    with respx.mock(assert_all_called=False) as mock:
        token = mock.post(PIPEDRIVE_TOKEN_URL).respond(
            200,
            json={
                "access_token": "fixture-access",
                "refresh_token": "fixture-refresh",
                "expires_in": 3600,
                "api_domain": DOMAIN,
                "scope": "base,deals:read",
            },
        )
        me = mock.get(DOMAIN + "/api/v1/users/me").respond(
            200,
            json={
                "data": {
                    "id": 123,
                    "company_id": 456,
                    "name": "Test account",
                    "email": "fixture@example.test",
                },
            },
        )
        yield token, me


@pytest_asyncio.fixture
async def accounts(real_database, monkeypatch):  # noqa: F811 (pytest fixture import)
    db = real_database
    owners = [str(uuid.uuid4()), str(uuid.uuid4())]
    for owner in owners:
        await db.execute(
            "INSERT INTO auth.users (id, email) VALUES ($1, $2)",
            owner,
            f"{owner}@example.test",
        )
    monkeypatch.setattr(
        "billing.plan_limits.check_credential_limit",
        AsyncMock(return_value=(True, None)),
    )
    monkeypatch.setattr(
        "repositories.credentials.log_activity_background", lambda *args: None
    )
    yield db, owners


async def connect(db, owner, code="fixture-code", installation=True):
    return await connection.connect_pipedrive(
        user_id=owner,
        user_tier="free",
        code=code,
        redirect_uri=CALLBACK,
        pool=db.pool,
        installation=installation,
    )


async def test_install_encrypts_real_grants_and_reconnects_only_the_same_owner(
    accounts, provider
):
    db, (owner, other_owner) = accounts
    first = await connect(db, owner)
    second = await connect(db, owner, code="second-code")
    other = await connect(db, other_owner, code="other-code")
    assert second["credential_id"] == first["credential_id"]
    assert other["credential_id"] != first["credential_id"]
    rows = await db.fetch(
        "SELECT owner_id, credential, metadata FROM credentials WHERE id = ANY($1::uuid[])",
        [first["credential_id"], other["credential_id"]],
    )
    assert len(rows) == 2
    for row in rows:
        assert "fixture-access" not in row["credential"]
        assert (
            get_encryption().decrypt_credential(row["credential"])["refresh_token"]
            == "fixture-refresh"
        )
        assert row["metadata"]["scopes"] == ["base", "deals:read"]
        assert row["metadata"]["scope_verified"] is True
        assert row["metadata"]["pipedrive_company_id"] == "456"
        assert row["metadata"]["pipedrive_user_id"] == "123"
    assert (
        await db.fetchval(
            "SELECT count(*) FROM credentials WHERE owner_id=$1 AND credential_type='pipedrive_oauth'",
            owner,
        )
        == 1
    )


async def test_concurrent_installs_do_not_create_duplicate_credentials(
    accounts, provider
):
    db, (owner, _) = accounts
    results = await asyncio.gather(
        connect(db, owner, code="first-code"), connect(db, owner, code="second-code")
    )
    assert results[0]["credential_id"] == results[1]["credential_id"]
    assert (
        await db.fetchval(
            "SELECT count(*) FROM credentials WHERE owner_id=$1 AND credential_type='pipedrive_oauth'",
            owner,
        )
        == 1
    )


async def test_different_company_identity_creates_a_separate_connection(
    accounts, provider
):
    db, (owner, _) = accounts
    first = await connect(db, owner)
    _, me = provider
    me.respond(
        200, json={"data": {"id": 123, "company_id": 789, "name": "Other test company"}}
    )
    second = await connect(db, owner, code="other-company-code")
    assert first["credential_id"] != second["credential_id"]


@pytest.mark.parametrize(
    "metadata_patch",
    [
        {"oauth_client_id": "another-app"},
        {"hidden_from_owner": True},
    ],
)
async def test_install_does_not_replace_another_app_or_held_credential(
    accounts, provider, metadata_patch
):
    db, (owner, _) = accounts
    first = await connect(db, owner)
    await db.execute(
        "UPDATE credentials SET metadata=metadata || $1::jsonb WHERE id=$2",
        metadata_patch,
        first["credential_id"],
    )
    second = await connect(db, owner, code="other-install-code")
    assert first["credential_id"] != second["credential_id"]


async def test_plan_limit_failure_does_not_claim_success(
    accounts, provider, monkeypatch
):
    db, (owner, _) = accounts
    monkeypatch.setattr(
        "billing.plan_limits.check_credential_limit",
        AsyncMock(return_value=(False, "Credential limit reached")),
    )
    with pytest.raises(
        connection.PipedriveConnectionError, match="Credential limit reached"
    ):
        await connect(db, owner)
    assert (
        await db.fetchval(
            "SELECT count(*) FROM credentials WHERE owner_id=$1 AND credential_type='pipedrive_oauth'",
            owner,
        )
        == 0
    )


async def test_transferred_credential_cannot_be_overwritten_during_reconnect(
    accounts, provider, monkeypatch
):
    db, (owner, other) = accounts
    first = await connect(db, owner)
    original = CredentialsRepo.find_or_create_pipedrive_install

    async def transfer_after_lookup(self, *args):
        result = await original(self, *args)
        await db.execute(
            "UPDATE credentials SET owner_id=$1 WHERE id=$2",
            other,
            first["credential_id"],
        )
        return result

    monkeypatch.setattr(
        CredentialsRepo, "find_or_create_pipedrive_install", transfer_after_lookup
    )
    with pytest.raises(connection.PipedriveConnectionError, match="Could not update"):
        await connect(db, owner, code="reconnect-code")
    assert await db.fetchval(
        "SELECT owner_id FROM credentials WHERE id=$1", first["credential_id"]
    ) == uuid.UUID(other)


async def test_popup_uses_the_shared_grant_storage_seam(
    accounts, provider, monkeypatch
):
    db, (owner, _) = accounts
    sio = AsyncMock()
    sio.get_session.return_value = {
        "user_id": owner,
        "user_data": {"subscription_tier": "free"},
    }
    handler = handler_module.PipedriveOAuthHandler(sio)
    monkeypatch.setattr(handler, "get_pool", AsyncMock(return_value=db.pool))
    sent = AsyncMock()
    monkeypatch.setattr(handler_module, "send_event", sent)
    await handler.exchange_oauth_code(
        "sid",
        PipedriveOAuthExchangeRequest(
            request_id="fixture-request",
            code="fixture-code",
            redirect_uri=CALLBACK,
            scopes=["requested-scope-is-not-a-grant"],
        ),
    )
    result = sent.call_args.args[2].data
    assert result["success"] is True
    metadata = await db.fetchval(
        "SELECT metadata FROM credentials WHERE id=$1", result["credential_id"]
    )
    assert metadata["scopes"] == ["base", "deals:read"]


async def test_backend_authenticates_before_exchanging(monkeypatch):
    exchange = AsyncMock()
    monkeypatch.setattr(install, "connect_pipedrive", exchange)
    monkeypatch.setattr(
        install, "verify_token", AsyncMock(side_effect=ValueError("invalid token"))
    )
    for authorization in ("", "Basic fake", "Bearer invalid"):
        with pytest.raises(HTTPException) as caught:
            await install.exchange_public_install(
                request(authorization),
                install.PipedriveInstallExchangeRequest(
                    code="fixture-code", redirect_uri=CALLBACK
                ),
            )
        assert caught.value.status_code == 401
    exchange.assert_not_awaited()


async def test_backend_rejects_redirect_mismatch_before_exchange(monkeypatch):
    monkeypatch.setenv("PIPEDRIVE_REDIRECT_URI", CALLBACK)
    monkeypatch.setattr(
        install, "verify_token", AsyncMock(return_value={"sub": str(uuid.uuid4())})
    )
    exchange = AsyncMock()
    monkeypatch.setattr(install, "connect_pipedrive", exchange)
    with pytest.raises(HTTPException) as caught:
        await install.exchange_public_install(
            request(),
            install.PipedriveInstallExchangeRequest(
                code="fixture-code", redirect_uri="https://evil.example/callback"
            ),
        )
    assert caught.value.status_code == 400
    exchange.assert_not_awaited()


async def test_http_install_uses_verified_subject_not_user_metadata(
    accounts, provider, monkeypatch
):
    db, (owner, other) = accounts
    monkeypatch.setattr(
        install,
        "verify_token",
        AsyncMock(
            return_value={
                "sub": owner,
                "user_metadata": {"sub": other, "subscription_tier": "enterprise"},
            }
        ),
    )
    result = await install.exchange_public_install(
        request(),
        install.PipedriveInstallExchangeRequest(
            code="fixture-code", redirect_uri=CALLBACK
        ),
    )
    assert result["success"] is True
    assert await db.fetchval(
        "SELECT owner_id FROM credentials WHERE id=$1", result["credential_id"]
    ) == uuid.UUID(owner)


@pytest.mark.parametrize("field", ["code", "redirect_uri"])
def test_exchange_input_is_bounded(field):
    with pytest.raises(ValidationError):
        install.PipedriveInstallExchangeRequest(
            **{"code": "fixture-code", "redirect_uri": CALLBACK, field: "x" * 4097}
        )


async def test_unverified_identity_is_not_persisted(provider, monkeypatch):
    _, me = provider
    me.respond(503, text="private provider response")
    save = AsyncMock()
    monkeypatch.setattr(connection, "create_credential_with_limit_check", save)
    with pytest.raises(
        connection.PipedriveConnectionError, match="identity could not be verified"
    ):
        await connection.connect_pipedrive(
            user_id=str(uuid.uuid4()),
            user_tier="free",
            code="fixture-code",
            redirect_uri=CALLBACK,
            pool=None,
        )
    save.assert_not_awaited()


async def test_provider_errors_do_not_expose_codes_or_response_bodies(provider, caplog):
    token, _ = provider
    token.respond(400, text="private provider response: fixture-code fixture-secret")
    with pytest.raises(ValueError) as caught:
        await exchange_code_for_tokens("fixture-code", CALLBACK)
    assert "fixture-code" not in str(caught.value)
    assert "private provider response" not in caplog.text


async def test_refresh_failure_keeps_the_oauth_code_not_the_body(provider, caplog):
    token, _ = provider
    token.respond(
        400,
        json={"error": "invalid_grant", "error_description": "private provider response"},
    )
    with pytest.raises(ValueError) as caught:
        await refresh_access_token("fixture-refresh")
    # The refresh choke point reads the code to tell the owner to reconnect.
    assert "invalid_grant" in str(caught.value)
    assert "private provider response" not in str(caught.value) + caplog.text


async def test_missing_grant_is_not_fabricated(accounts, provider):
    db, (owner, _) = accounts
    token, _ = provider
    token.respond(
        200,
        json={
            "access_token": "fixture-access",
            "refresh_token": "fixture-refresh",
            "api_domain": DOMAIN,
        },
    )
    result = await connect(db, owner)
    metadata = await db.fetchval(
        "SELECT metadata FROM credentials WHERE id=$1", result["credential_id"]
    )
    assert metadata["scopes"] == []
    assert metadata["scope_verified"] is False


async def test_http_failure_is_sanitized(monkeypatch):
    monkeypatch.setenv("PIPEDRIVE_REDIRECT_URI", CALLBACK)
    monkeypatch.setattr(
        install, "verify_token", AsyncMock(return_value={"sub": str(uuid.uuid4())})
    )
    monkeypatch.setattr(install, "get_native_pool", lambda: None)
    monkeypatch.setattr(
        install,
        "connect_pipedrive",
        AsyncMock(side_effect=httpx.TimeoutException("private request data")),
    )
    with pytest.raises(HTTPException) as caught:
        await install.exchange_public_install(
            request(),
            install.PipedriveInstallExchangeRequest(
                code="fixture-code", redirect_uri=CALLBACK
            ),
        )
    assert caught.value.status_code == 502
    assert "private" not in caught.value.detail
