"""Shared body for the per-provider ``refresh_oauth_token`` socket handlers.

Every OAuth handler exposes a manual "Refresh token" entry point. These used
to roll their own refresh — an unlocked, unaudited raw-SQL blob overwrite
that raced the node-execution refresh path and, on rotating providers, could
double-spend a single-use refresh token. This helper routes them all through
the same freshen choke point node execution uses (per-credential lock,
in-lock re-read, CAS persist, ``operator refresh audit`` audit row tagged
``caller_path=manual_refresh``).

Semantics follow the Slack handler's precedent: refresh-if-expired, not
forced — a manual refresh of a still-valid token is a no-op, so users
clicking the button can't burn rotations.
"""

from typing import Any, Awaitable, Callable, Dict, Optional

from nodes.core.oauth_refresh import freshen_oauth_credential, is_token_expired


async def manual_refresh_credential(
    pool,
    *,
    user_id: str,
    credential_id: str,
    provider: str,
    refresh: Optional[Callable[[str], Awaitable[Any]]] = None,
    make_refresh: Optional[Callable[[Dict[str, Any]], Callable[[str], Awaitable[Any]]]] = None,
    is_expired: Callable[[Optional[str]], bool] = is_token_expired,
    refresh_token_key: str = "refresh_token",
    access_token_key: str = "access_token",
    expires_at_key: str = "expires_at",
) -> Dict[str, Any]:
    """Load + freshen a credential for a manual refresh request.

    Pass ``refresh`` for providers whose refresher only needs the refresh
    token; pass ``make_refresh`` when the refresher needs fields from the
    loaded credential (Salesforce's instance_url, custom OAuth clients).
    Returns the freshened decrypted dict. Raises ``ValueError`` when the
    credential can't be loaded (missing, no access, or auto-revoked — revoked
    credentials recover via reconnect, not refresh) or when the refresh fails.
    """
    from utils.credential_loader import load_credential

    credential = await load_credential(pool, user_id, credential_id)
    if not credential:
        raise ValueError("Credential not found or access denied")
    if not credential.get(refresh_token_key):
        raise ValueError("No refresh token available")

    refresh_fn = make_refresh(credential) if make_refresh else refresh
    if refresh_fn is None:
        raise ValueError(f"No refresh function for provider {provider!r}")

    await freshen_oauth_credential(
        credential,
        pool=pool,
        user_id=user_id,
        credential_id=credential_id,
        refresh=refresh_fn,
        is_expired=is_expired,
        refresh_token_key=refresh_token_key,
        access_token_key=access_token_key,
        expires_at_key=expires_at_key,
        provider=provider,
        caller_path="manual_refresh",
    )
    return credential
