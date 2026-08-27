"""Authenticated server-side exchange for Shopify App Store installations."""

from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import HTTPException, Request
from pydantic import BaseModel

from nodes.oauth.shopify_oauth import exchange_code_for_tokens
from repositories.credentials import create_credential_with_limit_check
from utils.auth import verify_token
from utils.credentials import update_credential_data_detailed
from utils.database_pool import get_native_pool
from utils.encryption import get_encryption
from utils.ssrf import normalize_provider_subdomain


class ShopifyInstallExchangeRequest(BaseModel):
    code: str
    shop: str
    redirect_uri: str
    scopes: str = ""


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    return token


async def exchange_public_install(
    request: Request,
    body: ShopifyInstallExchangeRequest,
    *,
    pool=None,
) -> Dict[str, Any]:
    """Exchange an install code and upsert the user's Shopify credential."""
    try:
        claims = await verify_token(_bearer_token(request))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid authentication") from None
    user_id = str(claims.get("sub") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid authentication")

    configured_redirect = os.environ.get("SHOPIFY_REDIRECT_URI", "")
    if not configured_redirect or body.redirect_uri != configured_redirect:
        raise HTTPException(status_code=400, detail="Invalid Shopify redirect URI")

    try:
        shop = normalize_provider_subdomain(
            body.shop, "myshopify.com", field_name="Shopify store name"
        )
        tokens, shop_info = await exchange_code_for_tokens(
            code=body.code,
            shop=shop,
            redirect_uri=body.redirect_uri,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    credential_data = {
        "credential_type": "shopify_oauth",
        "access_token": tokens.access_token,
        "scope": tokens.scope,
        "store_name": shop,
        "shop_owner": shop_info.shop_owner,
        "email": shop_info.email,
        "refresh_token": getattr(tokens, "refresh_token", None),
        "expires_at": getattr(tokens, "expires_at", None),
        "refresh_expires_at": getattr(tokens, "refresh_expires_at", None),
    }
    metadata = {
        "provider": "shopify",
        "myshopify_domain": f"{shop}.myshopify.com",
        "shop_name": shop_info.name,
        "shop_domain": shop_info.domain,
        "shop_owner": shop_info.shop_owner,
        "email": shop_info.email,
        "shop_id": shop_info.id,
        "scopes": [scope for scope in body.scopes.split(",") if scope],
        "installation_source": "shopify_app_store",
    }
    credential_name = shop_info.name or shop_info.domain or f"Shopify ({shop_info.id})"

    pool = pool or get_native_pool()
    existing_id = None
    async with pool.acquire() as conn:
        # Reinstall/re-consent updates the existing owner-bound store credential
        # instead of consuming another plan slot or leaving a revoked duplicate.
        existing = await conn.fetchrow(
            """
            SELECT id
            FROM credentials
            WHERE owner_id = $1::uuid
              AND credential_type = 'shopify_oauth'
              AND lower(COALESCE(metadata->>'myshopify_domain', '')) = $2
            ORDER BY created_at ASC
            LIMIT 1
            """,
            user_id,
            f"{shop}.myshopify.com",
        )
        if existing:
            existing_id = existing["id"]
        else:
            user_tier = str(claims.get("subscription_tier") or "free")
            encrypted = get_encryption().encrypt_credential(credential_data)
            row, error = await create_credential_with_limit_check(
                conn,
                user_id,
                user_tier,
                "shopify_oauth",
                credential_name,
                encrypted,
                metadata,
            )
            if error or not row:
                raise HTTPException(
                    status_code=409,
                    detail=error or "Could not store Shopify connection",
                )

    if existing_id is not None:
        rows_updated, error_class = await update_credential_data_detailed(
            credential_id=str(existing_id),
            user_id=user_id,
            new_data=credential_data,
            metadata_updates=metadata,
            pool=pool,
            credential_name=credential_name,
        )
        if rows_updated != 1:
            status = 500 if error_class else 409
            raise HTTPException(
                status_code=status,
                detail="Could not update the existing Shopify connection",
            )
        row = {"id": existing_id, "name": credential_name}

    return {
        "success": True,
        "credential_id": str(row["id"]),
        "credential_name": row["name"],
        "shop": f"{shop}.myshopify.com",
    }
