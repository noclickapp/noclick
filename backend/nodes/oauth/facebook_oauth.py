"""
Facebook OAuth utility for handling token exchange and refresh.
Manages OAuth 2.0 flow for Instagram Graph API and other Facebook APIs.

Instagram Graph API requires Facebook Login (not Instagram direct OAuth).
This handles the Facebook OAuth flow and extracts Instagram Business account info.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional, Dict, Any, List
import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

FACEBOOK_GRAPH_API = "https://graph.facebook.com/v21.0"
FACEBOOK_TOKEN_URL = f"{FACEBOOK_GRAPH_API}/oauth/access_token"


class MultipleAccountsError(Exception):
    """Raised when the user has multiple Instagram accounts and must choose one."""

    def __init__(
        self, accounts: list, tokens: "FacebookTokens", email: Optional[str] = None
    ):
        self.accounts = accounts
        self.tokens = tokens
        self.email = email
        super().__init__(
            f"Multiple Instagram accounts found ({len(accounts)}). Please select one."
        )


class FacebookTokens(BaseModel):
    """Structured token response from Facebook OAuth"""

    access_token: str
    expires_at: str  # ISO 8601 timestamp
    token_type: str = "Bearer"


class InstagramAccountInfo(BaseModel):
    """Instagram Business/Creator account info linked to Facebook Page"""

    instagram_user_id: str
    instagram_username: Optional[str] = None
    email: Optional[str] = None
    facebook_page_id: Optional[str] = None
    facebook_page_name: Optional[str] = None


class InstagramAccountList(BaseModel):
    """Multiple Instagram accounts found during OAuth (user must select one)"""

    accounts: list  # List of dicts: {instagram_user_id, instagram_username, facebook_page_id, facebook_page_name}
    email: Optional[str] = None


class FacebookUserInfo(BaseModel):
    """Basic Facebook user metadata for a generic Facebook (Pages) credential."""

    facebook_user_id: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None


async def exchange_code_for_facebook_tokens(
    code: str,
    redirect_uri: str,
) -> Tuple["FacebookTokens", "FacebookUserInfo"]:
    """Exchange a Facebook Login code for a long-lived USER token (no Instagram
    account required). Used by the Facebook Pages node — Page tokens are derived
    from this user token via /me/accounts at run time."""
    client_id, client_secret = get_facebook_client_config()
    async with httpx.AsyncClient() as client:
        short = await client.get(FACEBOOK_TOKEN_URL, params={
            "client_id": client_id, "client_secret": client_secret,
            "code": code, "redirect_uri": redirect_uri})
        if short.status_code != 200:
            msg = short.json().get("error", {}).get("message", "Unknown error")
            raise ValueError(f"Token exchange failed: {msg}")
        long = await client.get(FACEBOOK_TOKEN_URL, params={
            "grant_type": "fb_exchange_token", "client_id": client_id,
            "client_secret": client_secret, "fb_exchange_token": short.json()["access_token"]})
        if long.status_code != 200:
            msg = long.json().get("error", {}).get("message", "Unknown error")
            raise ValueError(f"Failed to get long-lived token: {msg}")
        data = long.json()
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 5184000))
        tokens = FacebookTokens(access_token=data["access_token"], expires_at=expires_at.isoformat(),
                                token_type=data.get("token_type", "Bearer"))
        info = FacebookUserInfo()
        try:
            me = await client.get(f"{FACEBOOK_GRAPH_API}/me",
                                  params={"access_token": tokens.access_token, "fields": "id,name,email"})
            if me.status_code == 200:
                d = me.json()
                info = FacebookUserInfo(facebook_user_id=d.get("id"), name=d.get("name"), email=d.get("email"))
        except Exception:
            pass
        return tokens, info


def get_facebook_client_config() -> Tuple[str, str]:
    """
    Get Facebook OAuth client configuration from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        ValueError: If required environment variables are not set
    """
    client_id = os.environ.get("FACEBOOK_APP_ID")
    client_secret = os.environ.get("FACEBOOK_APP_SECRET")

    if not client_id:
        raise ValueError("FACEBOOK_APP_ID environment variable is required")
    if not client_secret:
        raise ValueError("FACEBOOK_APP_SECRET environment variable is required")

    return client_id, client_secret


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
    selected_instagram_user_id: Optional[str] = None,
) -> Tuple[FacebookTokens, InstagramAccountInfo]:
    """
    Exchange authorization code for access and refresh tokens.
    Also fetches the connected Instagram Business account.

    Args:
        code: Authorization code from Facebook OAuth callback
        redirect_uri: Must match the redirect_uri used in authorization
        selected_instagram_user_id: If the user has multiple Instagram accounts,
            pass the chosen instagram_user_id to select it. When None and multiple
            accounts exist, raises MultipleAccountsError.

    Returns:
        Tuple of (FacebookTokens, InstagramAccountInfo)

    Raises:
        ValueError: If token exchange fails or no Instagram account found
        MultipleAccountsError: If multiple accounts found and none selected
    """
    client_id, client_secret = get_facebook_client_config()

    def _collect_accounts_from_pages(
        pages_payload: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Extract linked Instagram business accounts from /me/accounts page objects."""
        discovered: List[Dict[str, Any]] = []
        seen_ids = set()
        for page in pages_payload:
            ig_account = page.get("instagram_business_account") or page.get(
                "connected_instagram_account"
            )
            if not ig_account:
                continue

            ig_id = ig_account.get("id")
            if not ig_id or ig_id in seen_ids:
                continue

            seen_ids.add(ig_id)
            discovered.append(
                {
                    "instagram_user_id": ig_id,
                    "instagram_username": ig_account.get("username"),
                    "facebook_page_id": page.get("id"),
                    "facebook_page_name": page.get("name"),
                }
            )
        return discovered

    async def _discover_accounts_via_page_tokens(
        client: httpx.AsyncClient,
        pages_payload: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Fallback discovery path.
        Some apps/users return pages from /me/accounts without the nested
        instagram_business_account. In that case, query each page directly
        with its page access token.
        """
        discovered: List[Dict[str, Any]] = []
        seen_ids = set()

        for page in pages_payload:
            page_id = page.get("id")
            page_name = page.get("name")
            page_access_token = page.get("access_token")
            if not page_id or not page_access_token:
                continue

            page_resp = await client.get(
                f"{FACEBOOK_GRAPH_API}/{page_id}",
                params={
                    "access_token": page_access_token,
                    "fields": "instagram_business_account{id,username},connected_instagram_account{id,username},name",
                },
            )
            if page_resp.status_code != 200:
                continue

            page_data = page_resp.json()
            ig_account = page_data.get("instagram_business_account") or page_data.get(
                "connected_instagram_account"
            )
            if not ig_account:
                continue

            ig_id = ig_account.get("id")
            if not ig_id or ig_id in seen_ids:
                continue

            seen_ids.add(ig_id)
            discovered.append(
                {
                    "instagram_user_id": ig_id,
                    "instagram_username": ig_account.get("username"),
                    "facebook_page_id": page_id,
                    "facebook_page_name": page_data.get("name") or page_name,
                }
            )

        return discovered

    async def _get_granted_scopes(
        client: httpx.AsyncClient, user_access_token: str
    ) -> List[str]:
        """Best-effort debug helper for actionable error messages."""
        try:
            debug_resp = await client.get(
                f"{FACEBOOK_GRAPH_API}/debug_token",
                params={
                    "input_token": user_access_token,
                    "access_token": f"{client_id}|{client_secret}",
                },
            )
            if debug_resp.status_code != 200:
                return []
            return debug_resp.json().get("data", {}).get("scopes", []) or []
        except Exception:
            return []

    async with httpx.AsyncClient() as client:
        # Step 1: Exchange code for short-lived token
        token_response = await client.get(
            FACEBOOK_TOKEN_URL,
            params={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )

        if token_response.status_code != 200:
            error_data = token_response.json()
            error_msg = error_data.get("error", {}).get("message", "Unknown error")
            logger.error(f"[FacebookOAuth] Token exchange failed: {error_msg}")
            raise ValueError(f"Token exchange failed: {error_msg}")

        token_data = token_response.json()
        short_lived_token = token_data["access_token"]

        # Step 2: Exchange for long-lived token (60 days)
        long_lived_response = await client.get(
            FACEBOOK_TOKEN_URL,
            params={
                "grant_type": "fb_exchange_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "fb_exchange_token": short_lived_token,
            },
        )

        if long_lived_response.status_code != 200:
            error_data = long_lived_response.json()
            error_msg = error_data.get("error", {}).get("message", "Unknown error")
            logger.error(
                f"[FacebookOAuth] Long-lived token exchange failed: {error_msg}"
            )
            raise ValueError(f"Failed to get long-lived token: {error_msg}")

        long_lived_data = long_lived_response.json()

        # Calculate expiry time (60 days for long-lived tokens)
        expires_in = long_lived_data.get("expires_in", 5184000)  # Default 60 days
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        tokens = FacebookTokens(
            access_token=long_lived_data["access_token"],
            expires_at=expires_at.isoformat(),
            token_type=long_lived_data.get("token_type", "Bearer"),
        )

        # Step 3: Get user's Facebook Pages with Instagram Business accounts
        pages_response = await client.get(
            f"{FACEBOOK_GRAPH_API}/me/accounts",
            params={
                "access_token": tokens.access_token,
                "fields": (
                    "id,name,access_token,tasks,"
                    "instagram_business_account{id,username},"
                    "connected_instagram_account{id,username}"
                ),
            },
        )

        if pages_response.status_code != 200:
            error_data = pages_response.json()
            error_msg = error_data.get("error", {}).get("message", "Unknown error")
            logger.error(f"[FacebookOAuth] Failed to get pages: {error_msg}")
            raise ValueError(f"Failed to get Facebook Pages: {error_msg}")

        pages_data = pages_response.json()
        pages = pages_data.get("data", [])

        # Collect all pages with Instagram Business accounts
        all_accounts = _collect_accounts_from_pages(pages)

        # Fallback: inspect each page via its page access token.
        if not all_accounts and pages:
            all_accounts = await _discover_accounts_via_page_tokens(client, pages)

        if not all_accounts:
            granted_scopes = await _get_granted_scopes(client, tokens.access_token)
            granted_scopes_text = (
                ", ".join(granted_scopes) if granted_scopes else "(unknown)"
            )
            raise ValueError(
                "No Instagram Business account found. "
                "Please make sure:\n"
                "1) The Instagram account is linked to the same Facebook Page used in OAuth\n"
                "2) OAuth granted instagram_basic, pages_show_list, pages_read_engagement\n"
                "3) OAuth granted business_management if page access is via Meta Business Manager\n"
                "4) Your user has sufficient Page tasks/permissions in Meta Business settings\n"
                f"Granted scopes on this token: {granted_scopes_text}"
            )

        # Step 4: Get user email (fetch before account selection so it's available in MultipleAccountsError)
        email: Optional[str] = None
        me_response = await client.get(
            f"{FACEBOOK_GRAPH_API}/me",
            params={
                "access_token": tokens.access_token,
                "fields": "email",
            },
        )
        if me_response.status_code == 200:
            email = me_response.json().get("email")

        # Select account: use the requested one, or the only one, or raise for selection
        if selected_instagram_user_id:
            chosen = next(
                (
                    a
                    for a in all_accounts
                    if a["instagram_user_id"] == selected_instagram_user_id
                ),
                None,
            )
            if not chosen:
                raise ValueError(
                    f"Instagram account {selected_instagram_user_id} not found in connected accounts."
                )
        elif len(all_accounts) == 1:
            chosen = all_accounts[0]
        else:
            # Multiple accounts — caller must supply selected_instagram_user_id
            raise MultipleAccountsError(all_accounts, tokens, email)

        instagram_info = InstagramAccountInfo(
            instagram_user_id=chosen["instagram_user_id"],
            instagram_username=chosen.get("instagram_username"),
            facebook_page_id=chosen.get("facebook_page_id"),
            facebook_page_name=chosen.get("facebook_page_name"),
            email=email,
        )

        logger.info(
            f"[FacebookOAuth] Successfully connected Instagram account @{instagram_info.instagram_username}"
        )
        return tokens, instagram_info


async def refresh_access_token(
    current_token: str,
    last_refreshed_at: Optional[str] = None,
) -> FacebookTokens:
    """
    Refresh a Facebook long-lived token.

    Facebook long-lived tokens can only be refreshed once they are at least
    24 hours old. If last_refreshed_at is provided and is less than 24 hours
    ago, the current token is returned unchanged (no API call made).

    Args:
        current_token: The current long-lived access token
        last_refreshed_at: ISO 8601 timestamp of the last refresh (or token
            issuance). When provided, enforces the Facebook 24hr restriction.

    Returns:
        New FacebookTokens with updated access_token and expires_at

    Raises:
        ValueError: If refresh fails
    """
    if last_refreshed_at:
        try:
            last_refresh_time = datetime.fromisoformat(
                last_refreshed_at.replace("Z", "+00:00")
            )
            hours_since_refresh = (
                datetime.now(timezone.utc) - last_refresh_time
            ).total_seconds() / 3600
            if hours_since_refresh < 24:
                logger.info(
                    f"[FacebookOAuth] Skipping refresh — token was last refreshed "
                    f"{hours_since_refresh:.1f}h ago (Facebook requires 24h minimum)."
                )
                # Return a stub with the same token; caller must not update expires_at
                raise ValueError(
                    f"Token refresh too soon: last refreshed {hours_since_refresh:.1f}h ago. "
                    "Facebook requires 24 hours between refreshes."
                )
        except ValueError:
            raise
        except Exception as e:
            logger.warning(f"[FacebookOAuth] Could not parse last_refreshed_at: {e}")

    client_id, client_secret = get_facebook_client_config()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            FACEBOOK_TOKEN_URL,
            params={
                "grant_type": "fb_exchange_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "fb_exchange_token": current_token,
            },
        )

        if response.status_code != 200:
            error_data = response.json()
            error_msg = error_data.get("error", {}).get("message", "Unknown error")
            logger.error(f"[FacebookOAuth] Token refresh failed: {error_msg}")
            raise ValueError(f"Token refresh failed: {error_msg}")

        token_data = response.json()

        # Calculate new expiry time
        expires_in = token_data.get("expires_in", 5184000)  # Default 60 days
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        tokens = FacebookTokens(
            access_token=token_data["access_token"],
            expires_at=expires_at.isoformat(),
            token_type=token_data.get("token_type", "Bearer"),
        )

        logger.info("[FacebookOAuth] Successfully refreshed access token")
        return tokens


async def validate_token(access_token: str) -> bool:
    """
    Validate if an access token is still valid.

    Args:
        access_token: The access token to validate

    Returns:
        True if valid, False if expired/invalid
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{FACEBOOK_GRAPH_API}/debug_token",
            params={
                "input_token": access_token,
                "access_token": access_token,
            },
        )

        if response.status_code != 200:
            return False

        data = response.json()
        token_data = data.get("data", {})

        # Check if token is valid and not expired
        is_valid = token_data.get("is_valid", False)
        expires_at = token_data.get("expires_at", 0)

        if not is_valid:
            return False

        # Check expiry (expires_at is Unix timestamp, 0 means never expires)
        if expires_at > 0:
            return datetime.now(timezone.utc).timestamp() < expires_at

        return True


def is_token_expired(expires_at: str, buffer_days: int = 7) -> bool:
    """
    Check if a token is expired or will expire soon.

    Facebook long-lived tokens last 60 days, so we use a larger buffer.

    Args:
        expires_at: ISO 8601 timestamp of token expiry
        buffer_days: Consider expired if expires within this many days

    Returns:
        True if expired or expiring soon
    """
    try:
        expiry_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        buffer = timedelta(days=buffer_days)
        now = datetime.now(timezone.utc)

        return now + buffer >= expiry_time
    except (ValueError, TypeError) as e:
        logger.error(f"[FacebookOAuth] Error parsing expiry time: {e}")
        # If we can't parse, assume expired for safety
        return True


def get_facebook_auth_url(
    scopes: list[str],
    state: str,
    redirect_uri: str,
) -> str:
    """
    Generate Facebook OAuth authorization URL.

    Args:
        scopes: List of OAuth scopes to request
        state: State parameter for CSRF protection
        redirect_uri: Redirect URI for OAuth callback

    Returns:
        Full authorization URL to redirect user to
    """
    client_id, _ = get_facebook_client_config()

    # Facebook OAuth endpoint
    base_url = "https://www.facebook.com/v21.0/dialog/oauth"

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": ",".join(scopes),
        "state": state,
    }

    query_string = "&".join(
        f'{k}={httpx.URL("", params={k: v}).params[k]}' for k, v in params.items()
    )
    return f"{base_url}?{query_string}"
