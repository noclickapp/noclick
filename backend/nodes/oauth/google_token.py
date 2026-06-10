"""Refresh-and-persist for Google OAuth access tokens.

Thin Google-specific wrapper over the shared ``ensure_fresh_oauth_token``
helper, kept so existing Google trigger callers have a stable entry point. The
shared helper provides the per-credential lock, DB re-read, and rotation-safe
retry; this just supplies Google's ``refresh_access_token``.
"""

from typing import Any, Dict, Optional

from nodes.core.oauth_refresh import ensure_fresh_oauth_token
from nodes.oauth.google_oauth import refresh_access_token


async def ensure_fresh_google_token(
    pool,
    credential_id: Optional[str],
    user_id: Optional[str],
    credential: Dict[str, Any],
) -> str:
    """Return a valid Google access token, refreshing + persisting if expired.

    *credential* is the decrypted credential dict and is mutated in place with
    the refreshed tokens.
    """
    return await ensure_fresh_oauth_token(
        pool=pool,
        credential_id=credential_id,
        user_id=user_id,
        credential=credential,
        refresh=refresh_access_token,
        provider="google",
    )
