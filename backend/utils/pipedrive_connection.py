"""Persist Pipedrive connections through the same encrypted credential seam.

Editor popups and authenticated Marketplace installs share token exchange and
grant metadata; installs reconnect only the owner's exact company/user pair.
"""

import os
import re
from typing import Optional

from nodes.oauth.pipedrive_oauth import exchange_code_for_tokens
from repositories.credentials import CredentialsRepo, create_credential_with_limit_check
from utils.credentials import update_credential_data_detailed
from utils.encryption import get_encryption


class PipedriveConnectionError(ValueError):
    """A safe, user-facing connection failure without provider response data."""


async def connect_pipedrive(
    *,
    user_id: str,
    user_tier: str,
    code: str,
    redirect_uri: str,
    pool,
    installation: bool = False,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> dict:
    try:
        tokens, user_info = await exchange_code_for_tokens(
            code=code, redirect_uri=redirect_uri, client_id=client_id, client_secret=client_secret
        )
    except ValueError:
        raise PipedriveConnectionError(
            "Pipedrive authorization could not be verified. Please reconnect."
        ) from None

    # Do not call an unresolved tenant or failed /users/me response "connected".
    if (
        not tokens.access_token
        or not tokens.api_domain
        or not str(user_info.id).isdigit()
        or not str(user_info.company_id or "").isdigit()
    ):
        raise PipedriveConnectionError(
            "Pipedrive account identity could not be verified. Please reconnect."
        )

    granted_scopes = [
        scope for scope in re.split(r"[,\s]+", tokens.scope or "") if scope
    ]
    credential_data = {
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "expires_at": tokens.expires_at,
        "api_domain": tokens.api_domain,
        "name": user_info.name,
        "email": user_info.email,
        "scope": tokens.scope,
    }
    # Store custom client credentials for token refresh if provided
    if client_id and client_secret:
        credential_data["client_id"] = client_id
        credential_data["client_secret"] = client_secret
    metadata = {
        "provider": "pipedrive",
        "name": user_info.name,
        "email": user_info.email,
        "pipedrive_user_id": user_info.id,
        "pipedrive_company_id": user_info.company_id,
        "api_domain": tokens.api_domain,
        "scopes": granted_scopes,
        "scope_verified": tokens.scope is not None,
        "oauth_client_id": client_id or os.environ.get("PIPEDRIVE_CLIENT_ID"),
    }
    if installation:
        metadata["installation_source"] = "pipedrive_install"
    name = user_info.name or user_info.email or f"Pipedrive ({user_info.id})"
    encrypted = get_encryption().encrypt_credential(credential_data)

    if installation:
        row, created, error = await CredentialsRepo(
            pool
        ).find_or_create_pipedrive_install(
            user_id,
            user_tier,
            name,
            encrypted,
            metadata,
        )
        if row and not created:
            updated, update_error = await update_credential_data_detailed(
                credential_id=str(row["id"]),
                user_id=user_id,
                new_data=credential_data,
                metadata_updates=metadata,
                pool=pool,
                credential_name=name,
                expected_owner_id=user_id,
                expected_credential_type="pipedrive_oauth",
            )
            if updated != 1 or update_error:
                raise PipedriveConnectionError(
                    "Could not update the Pipedrive connection. Please reconnect."
                )
    else:
        async with pool.acquire() as conn:
            row, error = await create_credential_with_limit_check(
                conn,
                user_id,
                user_tier,
                "pipedrive_oauth",
                name,
                encrypted,
                metadata,
            )
    if error or not row:
        raise PipedriveConnectionError(
            error or "Could not save the Pipedrive connection."
        )
    return {
        "success": True,
        "credential_id": str(row["id"]),
        "credential_name": name,
        "name": user_info.name,
        "email": user_info.email,
        "message": "Pipedrive account connected successfully",
    }
