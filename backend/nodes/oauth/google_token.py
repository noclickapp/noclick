"""Refresh-and-persist for Google OAuth access tokens.

Push-notification triggers run unattended for days. When an access token is
refreshed it must be written back to the credentials table — otherwise the
renewal job and the trigger node keep refreshing a token that was already
rotated, and eventually the stored refresh flow drifts out of sync.
"""

import logging
from typing import Any, Dict, Optional

from nodes.oauth.google_oauth import is_token_expired, refresh_access_token
from utils.credentials import update_credential_data

logger = logging.getLogger(__name__)


async def ensure_fresh_google_token(
    pool,
    credential_id: Optional[str],
    user_id: Optional[str],
    credential: Dict[str, Any],
) -> str:
    """Return a valid Google access token, refreshing + persisting if expired.

    *credential* is the decrypted credential dict (access_token, refresh_token,
    expires_at). A fresh token is returned as-is. An expired token is refreshed
    and, when *credential_id* and *user_id* are known, written back to the
    credentials row so subsequent callers don't refresh again. The passed
    *credential* dict is updated in place.
    """
    access_token = credential.get("access_token")
    expires_at = credential.get("expires_at")
    if access_token and expires_at and not is_token_expired(expires_at):
        return access_token

    refresh_token = credential.get("refresh_token")
    if not refresh_token:
        raise ValueError("Google credential is missing a refresh token")

    new_tokens = await refresh_access_token(refresh_token)
    credential["access_token"] = new_tokens.access_token
    credential["expires_at"] = new_tokens.expires_at

    if credential_id and user_id:
        await update_credential_data(
            credential_id=credential_id,
            user_id=user_id,
            new_data=credential,
            pool=pool,
        )
    else:
        logger.warning(
            "[google_token] Refreshed a Google token but could not persist it "
            "(missing credential_id/user_id)"
        )
    return new_tokens.access_token
