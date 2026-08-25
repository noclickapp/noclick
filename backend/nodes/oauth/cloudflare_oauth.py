"""
Cloudflare OAuth 2.0 utility for token exchange and refresh.

Auth URL:  https://dash.cloudflare.com/oauth2/auth
Token URL: https://dash.cloudflare.com/oauth2/token

Scope strings use dot notation (resource-name.action) — the format required by
Cloudflare's new OAuth Clients system (Manage Account → OAuth Clients). The old
Wrangler colon format (account:read, workers:write) is NOT valid here.

Register an OAuth app at: Cloudflare Dashboard → Manage Account → OAuth clients
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
import httpx
from pydantic import BaseModel

logger = logging.getLogger(__name__)

CLOUDFLARE_AUTH_URL = "https://dash.cloudflare.com/oauth2/auth"
CLOUDFLARE_TOKEN_URL = "https://dash.cloudflare.com/oauth2/token"
CLOUDFLARE_USERINFO_URL = "https://dash.cloudflare.com/oauth2/userinfo"
CLOUDFLARE_USER_API_URL = "https://api.cloudflare.com/client/v4/user"
CLOUDFLARE_REVOKE_URL = "https://dash.cloudflare.com/oauth2/revoke"


class CloudflareTokens(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None  # ISO 8601
    scope: str = ""
    token_type: str = "Bearer"


class CloudflareUserInfo(BaseModel):
    id: str
    email: str
    name: Optional[str] = None
    account_id: Optional[str] = None


def get_cloudflare_client_config() -> Tuple[str, str]:
    client_id = os.environ.get("CLOUDFLARE_CLIENT_ID")
    client_secret = os.environ.get("CLOUDFLARE_CLIENT_SECRET")
    if not client_id:
        raise ValueError("CLOUDFLARE_CLIENT_ID environment variable is required")
    if not client_secret:
        raise ValueError("CLOUDFLARE_CLIENT_SECRET environment variable is required")
    return client_id, client_secret


async def exchange_code_for_tokens(
    code: str,
    redirect_uri: str,
) -> Tuple[CloudflareTokens, CloudflareUserInfo]:
    """Exchange authorization code for tokens and fetch basic user info."""
    client_id, client_secret = get_cloudflare_client_config()

    async with httpx.AsyncClient(timeout=30.0) as client:
        token_response = await client.post(
            CLOUDFLARE_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        )

        if token_response.status_code != 200:
            logger.error(f"[CloudflareOAuth] Token exchange failed: HTTP {token_response.status_code}")
            raise ValueError(f"Token exchange failed: HTTP {token_response.status_code}")

        token_data = token_response.json()
        if "error" in token_data:
            msg = token_data.get("error_description", token_data.get("error", "Unknown error"))
            raise ValueError(f"Token exchange failed: {msg}")

        expires_at = None
        if "expires_in" in token_data:
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])).isoformat()

        tokens = CloudflareTokens(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            expires_at=expires_at,
            scope=token_data.get("scope", ""),
            token_type=token_data.get("token_type", "Bearer"),
        )

        # Fetch user info via the Cloudflare REST API (richer than OIDC userinfo)
        user_response = await client.get(
            CLOUDFLARE_USER_API_URL,
            headers={"Authorization": f"Bearer {tokens.access_token}", "Content-Type": "application/json"},
        )

        if user_response.status_code == 200:
            ud = user_response.json().get("result", {})
            user_info = CloudflareUserInfo(
                id=str(ud.get("id", "unknown")),
                email=ud.get("email", "unknown@unknown.com"),
                name=ud.get("first_name"),
            )
        else:
            logger.warning(f"[CloudflareOAuth] Could not fetch user info: HTTP {user_response.status_code}")
            user_info = CloudflareUserInfo(id="unknown", email="unknown@unknown.com")

        # Fetch primary account_id — required for account-level APIs (Workers, KV, D1, R2, …)
        try:
            accounts_response = await client.get(
                f"https://api.cloudflare.com/client/v4/accounts",
                headers={"Authorization": f"Bearer {tokens.access_token}", "Content-Type": "application/json"},
                params={"per_page": 1},
            )
            if accounts_response.status_code == 200:
                accounts = accounts_response.json().get("result", [])
                if accounts:
                    user_info.account_id = accounts[0]["id"]
        except Exception as e:
            logger.warning(f"[CloudflareOAuth] Could not fetch account_id: {e}")

    logger.info(f"[CloudflareOAuth] Token exchange succeeded for {user_info.email} (account: {user_info.account_id})")
    return tokens, user_info


async def refresh_access_token(refresh_token: str) -> CloudflareTokens:
    """Refresh an expired Cloudflare OAuth access token."""
    client_id, client_secret = get_cloudflare_client_config()

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            CLOUDFLARE_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        )

        if response.status_code != 200:
            logger.error(f"[CloudflareOAuth] Token refresh failed: HTTP {response.status_code}")
            raise ValueError(f"Token refresh failed: HTTP {response.status_code}")

        data = response.json()
        if "error" in data:
            msg = data.get("error_description", data.get("error", "Unknown error"))
            raise ValueError(f"Token refresh failed: {msg}")

        expires_at = None
        if "expires_in" in data:
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=data["expires_in"])).isoformat()

        tokens = CloudflareTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", refresh_token),
            expires_at=expires_at,
            scope=data.get("scope", ""),
            token_type=data.get("token_type", "Bearer"),
        )

    logger.info("[CloudflareOAuth] Token refreshed successfully")
    return tokens


def is_token_expired(expires_at: Optional[str], buffer_minutes: int = 5) -> bool:
    if not expires_at:
        return False
    try:
        expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) + timedelta(minutes=buffer_minutes) >= expiry
    except (ValueError, TypeError) as e:
        logger.error(f"[CloudflareOAuth] Error parsing expiry time: {e}")
        return False


def get_cloudflare_auth_url(scopes: list, state: str, redirect_uri: str) -> str:
    from urllib.parse import urlencode
    client_id, _ = get_cloudflare_client_config()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": state,
        "response_type": "code",
    }
    return f"{CLOUDFLARE_AUTH_URL}?{urlencode(params)}"


# Scope strings for Cloudflare's new OAuth Clients system (dot notation: resource-name.action).
# Must match what is registered on the OAuth client in Cloudflare dashboard AND
# what cloudflare.authorize.tsx sends in the authorize URL.
CLOUDFLARE_WORKFLOW_SCOPES = [
    # Developer Platform
    "agent-memory.write",
    "browser-rendering.read", "browser-rendering.write",
    "cf-agents.read", "cf-agents.write",
    "cloud-connector.read", "cloud-connector.write",
    "cloudchamber.read", "cloudchamber.write",
    "constellation.read", "constellation.write",
    "d1.read", "d1.write",
    "flagship.evaluate", "flagship.read", "flagship.write",
    "query-cache.read", "query-cache.write",
    "mcp-portals.read", "mcp-portals.write",
    "page.read", "page.write",
    "pipelines.read", "pipelines.send", "pipelines.write",
    "pubsub.read", "pubsub.write",
    "queues.read", "queues.write",
    "realtime.realtime", "realtime.admin",
    "secrets-store.read", "secrets-store.write",
    "vectorize.read", "vectorize.write",
    "workers-ci.read", "workers-ci.write",
    "containers.read", "containers.write",
    "workers-kv-storage.read", "workers-kv-storage.write",
    "workers-observability.read", "workers-observability.write", "workers-observability-telemetry.write",
    "r2-catalog.read", "r2-catalog.write", "r2-catalog-sql.read",
    "workers-r2-bucket-item.read", "workers-r2-bucket-item.write",
    "workers-r2.read", "workers-r2.write",
    "workers-routes.read", "workers-routes.write",
    "workers-scripts.read", "workers-scripts.write",
    "workers-tail.read",
    # AI & Machine Learning
    "aiaudit.read", "aiaudit.write",
    "aig.read", "aig.run", "aig.write",
    "ai-search.index", "ai-search.read", "ai-search.run", "ai-search.write",
    "agw.read", "agw.run", "agw.write",
    "rag.read", "rag.run", "rag.write",
    "firewall-for-ai.read", "firewall-for-ai.write",
    "websearch.run",
    "ai.read", "ai.write",
    # DNS & Zones
    "account-dns-settings.read", "account-dns-settings.write",
    "dns-firewall.read", "dns-firewall.write",
    "dns.read", "dns.write",
    "dns-view.read", "dns-view.write",
    "registrar-domains.admin", "registrar-domains.read",
    "registrar-sandbox-domains.admin", "registrar-sandbox-domains.read",
    "zone-custom-asset.read", "zone-custom-asset.write",
    "zone-dns-settings.read", "zone-dns-settings.write",
    "zone.read", "zone.write",
    "zone-settings.read", "zone-settings.write",
    "zone-versioning.read", "zone-versioning.write",
    # App Security
    "fraud-detection-pii.read",
    "account-firewall-access-rules.read", "account-firewall-access-rules.write",
    "account-security-center-insights.read", "account-security-center-insights.write",
    "account-waf.read", "account-waf.write",
    "request-tracer.read",
    "reports-application-security-report.read",
    "bot-management-feedback.read", "bot-management-feedback.write",
    "bot-management.read", "bot-management.write",
    "cloudforce-one.read", "cloudforce-one.write",
    "ddos-botnet-feed.read", "ddos-botnet-feed.write",
    "ddos-protection.read", "ddos-protection.write",
    "api-gateway.read", "api-gateway.write",
    "domain-page.shield", "domain-page-shield.read",
    "firewall-services.read", "firewall-services.write",
    "fraud-detection.read", "fraud-detection.write",
    "fraud-events.write",
    "fraud-feedback.read", "fraud-feedback.write",
    "http-applications.read", "http-applications.write",
    "http-ddos-managed-ruleset.read", "http-ddos-managed-ruleset.write",
    "iot.read", "iot.write",
    "l4-ddos-managed-ruleset.read", "l4-ddos-managed-ruleset.write",
    "page-rules.read", "page-rules.write",
    "page.shield", "page-shield.read",
    "precursor.read", "precursor.write",
    "sanitize.read", "sanitize.write",
    "tag.read", "tag.write",
    "trust-and-safety.read", "trust-and-safety.write",
    "challenge-widgets.read", "challenge-widgets.write",
    "url-scanner.read", "url-scanner.write",
    "zaraz.edit", "zaraz.read", "zaraz.write",
    "zone-security-center-insights.read", "zone-security-center-insights.write",
    "zone-waf.read", "zone-waf.write",
    # Rules & Configuration
    "account-custom-error-rules.read", "account-custom-error-rules.write",
    "account-custom-pages.read", "account-custom-pages.write",
    "account-rule-lists.read", "account-rule-lists.write",
    "account-rulesets.read", "account-rulesets.write",
    "config-settings.read", "config-settings.write",
    "custom-errors.read", "custom-errors.write",
    "custom-pages.read", "custom-pages.write",
    "dynamic-redirect.read", "dynamic-redirect.write",
    "managed-headers.read", "managed-headers.write",
    "mass-url-redirects.read", "mass-url-redirects.write",
    "origin.read", "origin.write",
    "response-compression.read", "response-compression.write",
    "select-configuration.read", "select-configuration.write",
    "snippets.read", "snippets.write",
    "transform-rules.read", "transform-rules.write",
    "zone-transform-rules.read", "zone-transform-rules.write",
    # Cloudflare One / Zero Trust
    "access-app.read", "access-app.revoke", "access-app.write",
    "access.read", "access.revoke", "access.write",
    "zone-access.read", "zone-access.revoke", "zone-access.write",
    "access-audit-log.read",
    "access-custom-page.read", "access-custom-page.write",
    "access-device-posture.read", "access-device-posture.write",
    "access-group.read", "access-group.write",
    "access-idp.read", "access-idp.write",
    "access-key.read", "access-key.write",
    "access-certificate.read", "access-certificate.write",
    "access-org.read", "access-org.revoke", "access-org.write",
    "access-acct.read", "access-acct.revoke", "access-acct.write",
    "access-policy.read", "access-policy.write",
    "access-policy-test.read", "access-policy-test.write",
    "access-population.read", "access-population.write",
    "access-saml-certificate.read", "access-saml-certificate.write",
    "access-scim-log.read",
    "access-ssh-auditing.read", "access-ssh-auditing.write",
    "access-service-token.read", "access-service-token.write",
    "access-tag.read", "access-tag.write",
    "access-users.read", "access-users.write",
    "access-seats.write",
    "casb.read", "casb.write",
    "teams-cds-compute-account.read", "teams-cds-compute-account.write",
    "teams-dex.read", "teams-dex.write",
    "teams-connector-cloudflared.monitoring", "teams-connector-cloudflared.read", "teams-connector-cloudflared.write",
    "teams-connector-warp.read", "teams-connector-warp.write",
    "teams-connectors.read", "teams-connectors.write",
    "teams-networks.read", "teams-networks.write",
    "argotunnel.read", "argotunnel.write",
    "teams-secure.location",
    "dls.read", "dls.write",
    "teams.read", "teams.report", "teams.write",
    "teams-resilience.read", "teams-resilience.write",
    "teams-pii.read",
    # Analytics & Logs
    "account-analytics.read",
    "analytics.read",
    "intel.read", "intel.write",
    "account-logs.read", "account-logs.write",
    "logs.read", "logs.write",
    "radar.read",
    # Network Services
    "account-waiting-rooms.read",
    "address-maps.read", "address-maps.write",
    "chinanetwork-steering.read", "chinanetwork-steering.write",
    "connectivity-directory.admin", "connectivity-directory.bind", "connectivity-directory.read",
    "healthcheck.read", "healthcheck.write",
    "ip-prefix-bgp-on-demand.read", "ip-prefix-bgp-on-demand.write",
    "ip-prefix.read", "ip-prefix.write",
    "load-balancers-account.read", "load-balancers-account.write",
    "load-balancers.read", "load-balancers.write",
    "load-balancing-monitors-and-pools.read", "load-balancing-monitors-and-pools.write",
    "pcaps-api.read", "pcaps-api.write",
    "magic-firewall.read", "magic-firewall.write",
    "fbm.admin", "fbm.read", "fbm.write",
    "magic-transit.read", "magic-transit.write",
    "magic-wan.read", "magic-wan.write",
    "waiting-rooms.read", "waiting-rooms.write",
    "web3-hostnames.read", "web3-hostnames.write",
    # Media
    "calls.read", "calls.write",
    "images.read", "images.write",
    "moq.read", "moq.write",
    "stream.read", "stream.write",
    # Email & Messaging
    "cloud-email-security.read", "cloud-email-security.write",
    "email-routing-address.read", "email-routing-address.write",
    "email-routing-rule.read", "email-routing-rule.write",
    "email-routing-suppression.read", "email-routing-suppression.write",
    "email-security-dmarcreports.read", "email-security-dmarcreports.write",
    "email-sending.read", "email-sending.write",
    # Cache & Performance
    "account-ssl-and-certificates.read", "account-ssl-and-certificates.write",
    "cache.purge",
    "cache-settings.read", "cache-settings.write",
    "account-disable-esc.read", "account-disable-esc.write",
    "zone-disable-esc.read", "zone-disable-esc.write",
    "ssl-and-certificates.read", "ssl-and-certificates.write",
    # Account & Billing
    "account-api-gateway.read", "account-api-gateway.write",
    "account-custom-asset.read", "account-custom-asset.write",
    "account-settings.read", "account-settings.write",
    "apps.write",
    "integration.write",
    "memberships.read", "memberships.write",
    "notifications.read", "notifications.write",
    "scim-provisioning.write",
    "user-details.read", "user-details.write",
    # Other
    "artifacts.read", "artifacts.write",
    "resource-library.read", "resource-library.write",
    "resource-sharing.read",
]
