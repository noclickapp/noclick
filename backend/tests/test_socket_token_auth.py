"""Socket auth token contract (docs/auth-refactor-spec.md Phase 1).

The socket connect/update_auth path authenticates with a Supabase access
token; identity is the VERIFIED JWT's sub claim. Pins:
  - expired tokens raise ExpiredSignatureError (reject code token_expired —
    the client refreshes + reconnects instead of logging out)
  - invalid/missing tokens raise InvalidTokenError (token_invalid)
  - user_id comes from claims['sub'], never a client-supplied field
"""

import jwt
import pytest
from unittest.mock import AsyncMock, patch

from utils.auth import verify_socket_token


async def test_valid_token_returns_sub_and_claims():
    claims = {"sub": "user-123", "email": "a@b.c", "exp": 9999999999}
    with patch("utils.auth.verify_token", new=AsyncMock(return_value=claims)):
        user_id, returned = await verify_socket_token("tok")
    assert user_id == "user-123"
    assert returned is claims


async def test_expired_token_raises_expired_signature():
    with patch(
        "utils.auth.verify_token",
        new=AsyncMock(side_effect=jwt.ExpiredSignatureError("Signature has expired")),
    ):
        with pytest.raises(jwt.ExpiredSignatureError):
            await verify_socket_token("tok")


async def test_invalid_token_raises_invalid():
    with patch(
        "utils.auth.verify_token",
        new=AsyncMock(side_effect=jwt.InvalidSignatureError("bad sig")),
    ):
        with pytest.raises(jwt.InvalidTokenError):
            await verify_socket_token("tok")


async def test_missing_token_raises_invalid():
    with pytest.raises(jwt.InvalidTokenError):
        await verify_socket_token("")
    with pytest.raises(jwt.InvalidTokenError):
        await verify_socket_token(None)  # type: ignore[arg-type]


async def test_token_without_sub_raises_invalid():
    with patch("utils.auth.verify_token", new=AsyncMock(return_value={"email": "a@b.c"})):
        with pytest.raises(jwt.InvalidTokenError):
            await verify_socket_token("tok")
