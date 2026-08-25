"""
BambooHR OAuth 2.0 / OIDC utility for token exchange and refresh.

BambooHR OAuth is subdomain-scoped — the authorize and token endpoints live
under the customer's own BambooHR account host, so the company subdomain must
be threaded through the authorize + token calls:
- Authorization URL: https://{companyDomain}.bamboohr.com/authorize.php?request=authorize
- Token URL:         https://{companyDomain}.bamboohr.com/token.php?request=token
- Refresh:           POST token URL with grant_type=refresh_token

The token response returns ``companyDomain`` (the company context), plus
``access_token`` / ``refresh_token`` / ``expires_in`` / ``id_token``. A refresh
token is only issued when ``offline_access`` is among the requested scopes.
BambooHR OAuth is restricted to approved Marketplace apps; the API-key Basic-auth
path is the primary, unrestricted credential.

client_id / client_secret default to BAMBOOHR_CLIENT_ID / BAMBOOHR_CLIENT_SECRET
but accept user-supplied values so a "bring your own app" custom OAuth client
(x-oauth-supports-custom-client) can be used.

Docs: https://documentation.bamboohr.com/page/authenticate-integration
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
from urllib.parse import urlencode

import httpx
from opentelemetry import trace
from pydantic import BaseModel
from utils.ssrf import normalize_provider_subdomain

logger = logging.getLogger(__name__)


def _auth_url(subdomain: str) -> str:
    tenant = normalize_provider_subdomain(
        subdomain, "bamboohr.com", field_name="BambooHR company subdomain"
    )
    return f"https://{tenant}.bamboohr.com/authorize.php"


def _token_url(subdomain: str) -> str:
    tenant = normalize_provider_subdomain(
        subdomain, "bamboohr.com", field_name="BambooHR company subdomain"
    )
    return f"https://{tenant}.bamboohr.com/token.php"


class BambooHRTokens(BaseModel):
    """Structured token response from BambooHR OAuth."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601 timestamp
    token_type: str = "Bearer"
    company_domain: Optional[str] = None


class BambooHRUserInfo(BaseModel):
    """Identity extracted from the OIDC id_token / token response."""

    id: str
    name: str
    email: Optional[str] = None


def get_bamboohr_client_config() -> Tuple[str, str]:
    """Get BambooHR OAuth client configuration from environment variables.

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("BAMBOOHR_CLIENT_ID")
    client_secret = os.environ.get("BAMBOOHR_CLIENT_SECRET")

    if not client_id:
        raise ValueError("BAMBOOHR_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("BAMBOOHR_CLIENT_SECRET environment variable is required")

    return client_id, client_secret


def _resolve_client(
    client_id: Optional[str], client_secret: Optional[str]
) -> Tuple[str, str]:
    """Use user-supplied client credentials if both are provided, else fall back
    to the env-configured NoClick OAuth app."""
    if client_id and client_secret:
        return client_id, client_secret
    return get_bamboohr_client_config()


def _tokens_from_response(token_data: dict, subdomain: str) -> BambooHRTokens:
    expires_at = None
    if "expires_in" in token_data:
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])
        ).isoformat()
    return BambooHRTokens(
        access_token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token"),
        expires_at=expires_at,
        token_type=token_data.get("token_type", "Bearer"),
        company_domain=token_data.get("companyDomain") or subdomain,
    )


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    subdomain: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> Tuple[BambooHRTokens, BambooHRUserInfo]:
    """Exchange an authorization code for tokens (subdomain-scoped token host)."""
    if not subdomain:
        raise ValueError("A BambooHR company subdomain is required to exchange the code")
    cid, csecret = _resolve_client(client_id, client_secret)

    data = {
        "grant_type": "authorization_code",
        "client_id": cid,
        "client_secret": csecret,
        "redirect_uri": redirect_uri,
        "code": code,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _token_url(subdomain),
            params={"request": "token"},
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        if resp.status_code != 200:
            logger.error(f"[BambooHROAuth] Token exchange failed: HTTP {resp.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {resp.status_code}")
        token_data = resp.json()
        if "error" in token_data:
            error_msg = token_data.get("error_description", token_data.get("error", "Unknown error"))
            logger.error(f"[BambooHROAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        tokens = _tokens_from_response(token_data, subdomain)
        user_info = _userinfo_from_token_data(token_data)
        logger.info(f"[BambooHROAuth] Exchanged code for tokens ({user_info.name})")
        return tokens, user_info


def _userinfo_from_token_data(token_data: dict) -> BambooHRUserInfo:
    """Best-effort identity from the token response. BambooHR returns an OIDC
    id_token (a JWT); we decode its unverified payload only for display fields."""
    import base64 as _b64
    import json as _json

    id_token = token_data.get("id_token")
    if not id_token or id_token.count(".") != 2:
        return BambooHRUserInfo(id="unknown", name="BambooHR Account")
    try:
        payload_b64 = id_token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        claims = _json.loads(_b64.urlsafe_b64decode(payload_b64))
        return BambooHRUserInfo(
            id=str(claims.get("sub", "unknown")),
            name=claims.get("name") or claims.get("preferred_username") or "BambooHR Account",
            email=claims.get("email"),
        )
    except Exception as e:  # noqa: BLE001 — identity is display-only
        logger.warning(f"[BambooHROAuth] Could not decode id_token: {e}")
        return BambooHRUserInfo(id="unknown", name="BambooHR Account")


async def refresh_access_token(
    refresh_token: str,
    subdomain: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> BambooHRTokens:
    """Refresh an access token. BambooHR's token endpoint is subdomain-scoped."""
    if not subdomain:
        raise ValueError("A BambooHR company subdomain is required to refresh the token")
    cid, csecret = _resolve_client(client_id, client_secret)

    data = {
        "grant_type": "refresh_token",
        "client_id": cid,
        "client_secret": csecret,
        "refresh_token": refresh_token,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            _token_url(subdomain),
            params={"request": "token"},
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        if resp.status_code != 200:
            logger.error(f"[BambooHROAuth] Token refresh failed: HTTP {resp.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {resp.status_code}")
        token_data = resp.json()
        if "error" in token_data:
            error_msg = token_data.get("error_description", token_data.get("error", "Unknown error"))
            error_code = token_data.get("error")
            span = trace.get_current_span()
            if span and span.is_recording() and error_code:
                span.set_attribute("oauth.provider_error_code", str(error_code))
            logger.error(f"[BambooHROAuth] Token refresh failed: {error_msg}")
            raise ValueError(f"Token refresh failed: {error_msg}")

        tokens = _tokens_from_response(token_data, subdomain)
        # Refresh tokens may be omitted on refresh — keep the existing one.
        if not tokens.refresh_token:
            tokens.refresh_token = refresh_token
        logger.info("[BambooHROAuth] Refreshed access token")
        return tokens


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    """True if the token is expired or expires within *buffer_minutes*."""
    if not expires_at:
        return False
    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) + timedelta(minutes=buffer_minutes) >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[BambooHROAuth] Error parsing expiry time: {e}")
        return False


def get_bamboohr_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
    subdomain: str,
    client_id: Optional[str] = None,
) -> str:
    """Generate the BambooHR OAuth authorization URL (subdomain-scoped host).

    BambooHR uses plus-separated scopes and requires ``request=authorize``.
    ``offline_access`` must be present to receive a refresh token.
    """
    cid = client_id or get_bamboohr_client_config()[0]
    params = {
        "request": "authorize",
        "response_type": "code",
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
    }
    return f"{_auth_url(subdomain)}?{urlencode(params)}"


# Default scopes. `openid` for OIDC identity, `offline_access` for the refresh
# token. Mirror the x-oauth-scopes in BambooHROAuthCredential.
BAMBOOHR_DEFAULT_SCOPES = [
    "openid",
    "offline_access",
]
