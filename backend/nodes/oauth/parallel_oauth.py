"""
Parallel OAuth utility for handling token exchange.

Parallel uses Authorization Code + PKCE (S256). There is no client registration
required — the client_id is simply the app's hostname (default: noclick.com).
The access_token returned IS the user's permanent Parallel API key; no refresh
token is issued and the token does not expire.

Auth URL:  https://platform.parallel.ai/getKeys/authorize
Token URL: https://platform.parallel.ai/getKeys/token
Scope:     key:read
Docs:      https://docs.parallel.ai/resources/oauth-provider
"""

import os
import logging
from typing import Optional
import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

PARALLEL_AUTH_URL = "https://platform.parallel.ai/getKeys/authorize"
PARALLEL_TOKEN_URL = "https://platform.parallel.ai/getKeys/token"
PARALLEL_SCOPES = ["key:read"]


class ParallelTokens(BaseModel):
    """Token response from Parallel OAuth — access_token IS the API key."""
    access_token: str


def get_parallel_client_id() -> str:
    """Return the OAuth client_id (app hostname). No secret — public PKCE client."""
    return os.environ.get("PARALLEL_CLIENT_ID", "noclick.com")


def get_parallel_auth_url(state: str, redirect_uri: str, code_challenge: str) -> str:
    """Build the Parallel authorization URL with PKCE S256."""
    from urllib.parse import urlencode
    params = {
        "client_id": get_parallel_client_id(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(PARALLEL_SCOPES),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{PARALLEL_AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> ParallelTokens:
    """Exchange an authorization code for the user's Parallel API key."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        "client_id": get_parallel_client_id(),
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            PARALLEL_TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            err = resp.json() if resp.content else {}
            msg = err.get("error_description") or err.get("error") or f"HTTP {resp.status_code}"
            logger.error(f"[ParallelOAuth] Token exchange failed: {msg}")
            raise ValueError(f"Token exchange failed: {msg}")
        token_data = resp.json()
    logger.info("[ParallelOAuth] Token exchange successful")
    return ParallelTokens(access_token=token_data["access_token"])


async def validate_api_key(api_key: str) -> bool:
    """Check that an API key is still valid by making a lightweight call."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            "https://api.parallel.ai/v1/monitors",
            headers={"x-api-key": api_key},
            params={"limit": "1"},
        )
    return resp.status_code < 400
