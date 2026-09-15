"""``utils.auth.authenticate_http_request`` — the one caller-resolution rule for
browser → backend REST routes (``/api/keys``, ``/admin/cas``).

The session cookie is SameSite=Lax + scoped to the app domain, so it never
reaches the API domain cross-origin in prod: a cookie-only gate 401'd every
Developer-tab API-key request (2026-09-15). The SPA sends its live Supabase
access token as a Bearer header; the cookie is only the same-origin fallback.
"""

from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi import HTTPException

from utils.api_key_routes import _get_user_id
from utils.auth import authenticate_http_request


class _Req:
    def __init__(self, cookie: str | None = None, authorization: str | None = None):
        self.headers = {}
        if cookie is not None:
            self.headers["cookie"] = cookie
        if authorization is not None:
            self.headers["authorization"] = authorization


def _verified(claims):
    return patch("utils.auth.verify_token", AsyncMock(return_value=claims))


@pytest.mark.asyncio
class TestAuthenticateHttpRequest:
    async def test_no_credentials_401(self):
        with pytest.raises(HTTPException) as ei:
            await authenticate_http_request(_Req())
        assert ei.value.status_code == 401

    async def test_bearer_without_cookie_resolves_user(self):
        # The cross-origin path the Developer tab takes in prod.
        with _verified({"sub": "user-42", "email": "a@b.c"}) as vt:
            user_id, claims = await authenticate_http_request(_Req(authorization="Bearer livetok"))
        assert user_id == "user-42"
        assert claims["email"] == "a@b.c"
        vt.assert_awaited_once_with("livetok")

    async def test_bearer_preferred_over_cookie(self):
        cookie_spy = AsyncMock(side_effect=AssertionError("cookie must not be read when Bearer present"))
        with patch("utils.auth.extract_token_from_cookies", cookie_spy), _verified({"sub": "u"}):
            user_id, _ = await authenticate_http_request(_Req(cookie="sb=x", authorization="Bearer livetok"))
        assert user_id == "u"
        cookie_spy.assert_not_called()

    async def test_cookie_fallback_identity_is_the_verified_sub(self):
        # Never the cookie blob's (unverified) user id.
        with patch("utils.auth.extract_token_from_cookies", AsyncMock(return_value=("tok", "cookie-claimed-id"))), \
             _verified({"sub": "verified-id"}):
            user_id, _ = await authenticate_http_request(_Req(cookie="sb=x"))
        assert user_id == "verified-id"

    async def test_unparseable_cookie_401(self):
        with patch("utils.auth.extract_token_from_cookies", AsyncMock(side_effect=ValueError("nope"))):
            with pytest.raises(HTTPException) as ei:
                await authenticate_http_request(_Req(cookie="junk"))
        assert ei.value.status_code == 401

    async def test_invalid_token_401(self):
        with patch("utils.auth.verify_token", AsyncMock(side_effect=jwt.ExpiredSignatureError("expired"))):
            with pytest.raises(HTTPException) as ei:
                await authenticate_http_request(_Req(authorization="Bearer expired"))
        assert ei.value.status_code == 401

    async def test_token_without_sub_401(self):
        with _verified({"email": "no-sub@example.com"}):
            with pytest.raises(HTTPException) as ei:
                await authenticate_http_request(_Req(authorization="Bearer t"))
        assert ei.value.status_code == 401

    async def test_empty_bearer_falls_back_to_cookie(self):
        with patch("utils.auth.extract_token_from_cookies", AsyncMock(return_value=("tok", "x"))), \
             _verified({"sub": "u"}):
            user_id, _ = await authenticate_http_request(_Req(cookie="sb=x", authorization="Bearer "))
        assert user_id == "u"


@pytest.mark.asyncio
async def test_api_key_routes_use_the_shared_rule():
    with _verified({"sub": "user-42"}):
        assert await _get_user_id(_Req(authorization="Bearer livetok")) == "user-42"
    with pytest.raises(HTTPException) as ei:
        await _get_user_id(_Req())
    assert ei.value.status_code == 401
