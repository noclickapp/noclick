"""Credential-boundary regressions for Google service-account exchanges."""

import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import nodes.bigquery_node as bigquery
import nodes.dv360_node as dv360
import nodes.firestore_node as firestore
import nodes.google_cloud_storage_node as cloud_storage
import nodes.google_translate_node as translate
from utils.google_service_account import (
    BoundedTTLTokenCache,
    GOOGLE_SERVICE_ACCOUNT_TOKEN_URL,
    google_service_account_authority_key,
)
from utils.ssrf import SSRFError


_INVALID_TOKEN_URIS = [
    "https://oauth2.googleapis.com.attacker.example/token",
    "https://attacker@oauth2.googleapis.com/token",
    "http://oauth2.googleapis.com/token",
    "https://oauth2.googleapis.com:8443/token",
    "https://oauth2.googleapis.com/token/extra",
    "https://oauth2.googleapis.com/token?target=attacker",
]
_EXCHANGE_CASES = ["firestore", "translate", "bigquery", "dv360", "cloud_storage"]


def _service_account_json(token_uri: str, *, private_key: str = "private-key") -> str:
    return json.dumps(
        {
            "type": "service_account",
            "client_email": "service@example.iam.gserviceaccount.com",
            "private_key": private_key,
            "private_key_id": "key-id",
            "project_id": "project-a",
            "token_uri": token_uri,
        }
    )


def _firestore_credential(
    token_uri: str = GOOGLE_SERVICE_ACCOUNT_TOKEN_URL,
    *,
    private_key: str = "private-key",
    project_id: str = "project-a",
):
    return firestore.FirestoreServiceAccountCredential(
        client_email="service@example.iam.gserviceaccount.com",
        private_key=private_key,
        private_key_id="key-id",
        project_id=project_id,
        token_uri=token_uri,
    )


def _translate_credential(
    token_uri: str = GOOGLE_SERVICE_ACCOUNT_TOKEN_URL,
    *,
    private_key: str = "private-key",
    project_id: str = "project-a",
):
    return translate.GoogleTranslateServiceAccountCredential(
        client_email="service@example.iam.gserviceaccount.com",
        private_key=private_key,
        private_key_id="key-id",
        project_id=project_id,
        token_uri=token_uri,
    )


def _exchange(case: str, token_uri: str, *, private_key: str = "private-key"):
    if case == "firestore":
        return firestore._exchange_service_account_access_token(
            _firestore_credential(token_uri, private_key=private_key)
        )
    if case == "translate":
        return translate._exchange_service_account_access_token(
            _translate_credential(token_uri, private_key=private_key)
        )

    raw = _service_account_json(token_uri, private_key=private_key)
    return {
        "bigquery": bigquery._mint_service_account_access_token,
        "dv360": dv360._mint_service_account_access_token,
        "cloud_storage": cloud_storage._mint_service_account_access_token,
    }[case](raw)


def _module_for(case: str):
    return {
        "firestore": firestore,
        "translate": translate,
        "bigquery": bigquery,
        "dv360": dv360,
        "cloud_storage": cloud_storage,
    }[case]


def _successful_client(token: str = "access-token"):
    response = MagicMock(status_code=200, text="")
    response.json.return_value = {"access_token": token, "expires_in": 3600}
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=None)
    return context, client


@pytest.mark.parametrize("case", _EXCHANGE_CASES)
@pytest.mark.parametrize("token_uri", _INVALID_TOKEN_URIS)
@pytest.mark.asyncio
async def test_service_account_exchange_rejects_nonstandard_token_uri_before_signing(
    case, token_uri
):
    module = _module_for(case)
    if case in {"firestore", "translate"}:
        module._sa_token_cache.clear()

    with patch("jwt.encode") as sign, patch.object(
        module, "guarded_async_client"
    ) as client_factory:
        with pytest.raises(SSRFError, match="must be exactly"):
            await _exchange(case, token_uri)

    sign.assert_not_called()
    client_factory.assert_not_called()


@pytest.mark.parametrize("case", _EXCHANGE_CASES)
@pytest.mark.asyncio
async def test_service_account_exchange_uses_exact_google_token_endpoint(case):
    module = _module_for(case)
    if case in {"firestore", "translate"}:
        module._sa_token_cache.clear()
    context, client = _successful_client()

    with patch("jwt.encode", return_value="signed-assertion") as sign, patch.object(
        module, "guarded_async_client", return_value=context
    ):
        token = await _exchange(case, GOOGLE_SERVICE_ACCOUNT_TOKEN_URL)

    assert token == "access-token"
    assert sign.call_args.args[0]["aud"] == GOOGLE_SERVICE_ACCOUNT_TOKEN_URL
    client.post.assert_awaited_once()
    assert client.post.await_args.args[0] == GOOGLE_SERVICE_ACCOUNT_TOKEN_URL


@pytest.mark.parametrize("case", ["firestore", "translate"])
@pytest.mark.asyncio
async def test_service_account_cache_is_bound_to_private_key_and_project(case):
    module = _module_for(case)
    module._sa_token_cache.clear()
    context, client = _successful_client()
    credential_factory = {
        "firestore": _firestore_credential,
        "translate": _translate_credential,
    }[case]
    exchange = module._exchange_service_account_access_token

    credential = credential_factory(private_key="key-one", project_id="project-a")
    same_credential = credential_factory(
        private_key="key-one", project_id="project-a"
    )
    rotated_key = credential_factory(private_key="key-two", project_id="project-a")
    other_project = credential_factory(private_key="key-two", project_id="project-b")

    with patch("jwt.encode", return_value="signed-assertion") as sign, patch.object(
        module, "guarded_async_client", return_value=context
    ):
        assert await exchange(credential) == "access-token"
        assert await exchange(same_credential) == "access-token"
        assert await exchange(rotated_key) == "access-token"
        assert await exchange(other_project) == "access-token"

    # The exact credential reused its token. Key rotation and project authority
    # each minted independently despite identical public email/key-id fields.
    assert sign.call_count == 3
    assert client.post.await_count == 3
    assert len(module._sa_token_cache) == 3


def test_authority_fingerprint_normalizes_pem_without_exposing_it():
    common = {
        "client_email": "service@example.iam.gserviceaccount.com",
        "token_uri": GOOGLE_SERVICE_ACCOUNT_TOKEN_URL,
        "scopes": ("scope-a", "scope-b"),
        "project_id": "project-a",
        "private_key_id": "key-id",
    }
    escaped = google_service_account_authority_key(
        private_key="line-one\\nline-two", **common
    )
    multiline = google_service_account_authority_key(
        private_key="line-one\nline-two\n", **common
    )
    other_scope = google_service_account_authority_key(
        private_key="line-one\nline-two",
        **{**common, "scopes": ("scope-a",)},
    )

    assert escaped == multiline
    assert escaped != other_scope
    assert re.fullmatch(r"[0-9a-f]{64}", escaped)
    assert "line-one" not in escaped


@pytest.mark.parametrize(
    "override",
    [
        {"client_email": "other@example.iam.gserviceaccount.com"},
        {"token_uri": "https://other.example/token"},
        {"scopes": ("scope-a",)},
        {"project_id": "project-b"},
        {"private_key_id": "other-key-id"},
    ],
)
def test_authority_fingerprint_covers_every_non_key_authority_field(override):
    common = {
        "private_key": "private-key",
        "client_email": "service@example.iam.gserviceaccount.com",
        "token_uri": GOOGLE_SERVICE_ACCOUNT_TOKEN_URL,
        "scopes": ("scope-a", "scope-b"),
        "project_id": "project-a",
        "private_key_id": "key-id",
    }

    baseline = google_service_account_authority_key(**common)
    changed = google_service_account_authority_key(**{**common, **override})
    assert baseline != changed


def test_service_account_token_cache_is_ttl_bounded():
    cache = BoundedTTLTokenCache(max_entries=2, refresh_skew_seconds=0)
    cache.put("one", "token-1", expires_at=100, now=0)
    cache.put("two", "token-2", expires_at=100, now=0)
    cache.put("three", "token-3", expires_at=100, now=0)

    assert len(cache) == 2
    assert cache.get("one", now=1) is None
    assert cache.get("two", now=1) == "token-2"
    assert cache.get("three", now=100) is None
    assert len(cache) == 0
