"""Authenticated server-side exchange for Shopify App Store installations."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel

from nodes.oauth.shopify_oauth import SHOPIFY_API_VERSION, exchange_code_for_tokens
from repositories.credentials import create_credential_with_limit_check
from utils.auth import verify_token
from utils.credentials import update_credential_data_detailed
from utils.database_pool import get_native_pool
from utils.encryption import get_encryption
from utils.hosted_defaults import webhook_worker_base_url
from utils.ssrf import normalize_provider_subdomain


logger = logging.getLogger(__name__)


def _shopify_uninstall_webhook_uri() -> str:
    configured = os.environ.get("SHOPIFY_UNINSTALL_WEBHOOK_URI", "").strip()
    if configured:
        return configured
    return f"{webhook_worker_base_url()}/webhook/shopify/lifecycle"


async def ensure_app_uninstalled_webhook(
    shop: str,
    access_token: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Ensure the legacy install flow has a shop-specific uninstall hook."""
    shop = normalize_provider_subdomain(
        shop, "myshopify.com", field_name="Shopify store name"
    )
    graphql_url = (
        f"https://{shop}.myshopify.com/admin/api/" f"{SHOPIFY_API_VERSION}/graphql.json"
    )
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }
    webhook_uri = _shopify_uninstall_webhook_uri()
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=30.0)
    try:
        existing_response = await client.post(
            graphql_url,
            headers=headers,
            json={
                "query": """
                query NoClickAppUninstalledWebhooks {
                  webhookSubscriptions(first: 50, topics: [APP_UNINSTALLED]) {
                    nodes { id uri }
                  }
                }
                """,
            },
        )
        existing_response.raise_for_status()
        existing_payload = existing_response.json()
        if existing_payload.get("errors"):
            raise ValueError("Shopify could not list uninstall webhooks")
        nodes = (
            (existing_payload.get("data") or {}).get("webhookSubscriptions") or {}
        ).get("nodes") or []
        for node in nodes:
            if node.get("uri") == webhook_uri and node.get("id"):
                return str(node["id"])

        create_response = await client.post(
            graphql_url,
            headers=headers,
            json={
                "query": """
                mutation NoClickAppUninstalledWebhookCreate(
                  $subscription: WebhookSubscriptionInput!
                ) {
                  webhookSubscriptionCreate(
                    topic: APP_UNINSTALLED,
                    webhookSubscription: $subscription
                  ) {
                    webhookSubscription { id }
                    userErrors { field message }
                  }
                }
                """,
                "variables": {
                    "subscription": {
                        "uri": webhook_uri,
                        "format": "JSON",
                    }
                },
            },
        )
        create_response.raise_for_status()
        create_payload = create_response.json()
        if create_payload.get("errors"):
            raise ValueError("Shopify could not create the uninstall webhook")
        result = (create_payload.get("data") or {}).get(
            "webhookSubscriptionCreate"
        ) or {}
        user_errors = result.get("userErrors") or []
        if user_errors:
            raise ValueError("Shopify rejected the uninstall webhook")
        webhook_id = (result.get("webhookSubscription") or {}).get("id")
        if not webhook_id:
            raise ValueError("Shopify did not return an uninstall webhook ID")
        return str(webhook_id)
    finally:
        if owns_client:
            await client.aclose()


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

    try:
        await ensure_app_uninstalled_webhook(shop, tokens.access_token)
    except (httpx.HTTPError, ValueError):
        logger.exception(
            "[ShopifyInstall] Failed to register app/uninstalled webhook for %s",
            shop,
        )
        raise HTTPException(
            status_code=502,
            detail="Could not register Shopify uninstall lifecycle handling",
        ) from None

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
        "installation_source": "shopify_app_store",
    }
    metadata = {
        "provider": "shopify",
        "myshopify_domain": f"{shop}.myshopify.com",
        "shop_name": shop_info.name,
        "shop_domain": shop_info.domain,
        "shop_owner": shop_info.shop_owner,
        "email": shop_info.email,
        "shop_id": shop_info.id,
        # Persist Shopify's authoritative grant, not the scopes requested by
        # the browser.  The two can diverge for an older install or after a
        # merchant changes access, and reviewer credentials must never look
        # healthier than the token Shopify actually issued.
        "scopes": [scope.strip() for scope in tokens.scope.split(",") if scope.strip()],
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
