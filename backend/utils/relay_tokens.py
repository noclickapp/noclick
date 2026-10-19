"""User room tokens: what lets a browser tab into its own user's relay room.

A user room carries everything addressed to one user (chat frames, coordinator
messages, tool results, notifications), so a viewer proves it is that user by
sending one of these as its first frame. The token is an HS256 JWT signed with
WORKFLOW_JWT_SECRET, the secret the relay already verifies workflow room tokens
with. Its audience keeps the two apart: no other token signed with that secret
(workflow collab, executor) opens a user room, and a user room token names no
workflow.
"""

import os
import time
from typing import Tuple

import jwt

# Every relay implementation checks this exact audience.
USER_ROOM_AUDIENCE = "relay:user"

# Checked once, when a viewer connects; the client mints another to reconnect.
USER_ROOM_TOKEN_TTL_S = 5 * 60


def _signing_secret() -> str:
    secret = os.environ.get("WORKFLOW_JWT_SECRET", "")
    if not secret:
        raise RuntimeError("WORKFLOW_JWT_SECRET not configured")
    return secret


def mint_user_room_token(user_id: str) -> Tuple[str, int]:
    """A token for ``user_id``'s own room, and when it expires (epoch seconds)."""
    now = int(time.time())
    expires_at = now + USER_ROOM_TOKEN_TTL_S
    token = jwt.encode(
        {"sub": str(user_id), "aud": USER_ROOM_AUDIENCE, "iat": now, "exp": expires_at},
        _signing_secret(),
        algorithm="HS256",
    )
    return token, expires_at


def verify_user_room_token(token: str, user_id: str) -> dict:
    """The token's claims if it opens ``user_id``'s room; raises otherwise."""
    payload = jwt.decode(
        token,
        _signing_secret(),
        algorithms=["HS256"],
        audience=USER_ROOM_AUDIENCE,
        options={"require": ["exp", "sub", "aud"]},
    )
    if payload.get("sub") != str(user_id):
        raise jwt.InvalidTokenError("Token user mismatch")
    return payload
