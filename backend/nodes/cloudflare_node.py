"""
Cloudflare REST API automation node.

Provides workflow integration for Cloudflare APIs including DNS, Workers, KV, D1,
R2, Pages, Stream, Images, Zones, Cache, WAF, Access, Tunnels, Email Routing,
Queues, Workers AI, Vectorize, and Load Balancing. Supports both API Token
(recommended) and legacy API Key + Email authentication.
"""

import hmac
import httpx
import logging
import secrets as _secrets
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Union
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from nodes.core.base import WorkflowNode, NodeConfig
from utils.ssrf import guarded_async_client, normalize_provider_subdomain
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import WebhookTriggerConfigBase, ExternalWebhookTriggerMixin
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.scopes.cloudflare import CLOUDFLARE_SCOPES

logger = logging.getLogger(__name__)

BASE_URL = "https://api.cloudflare.com/client/v4"


def _r2_endpoint_url(account_id: str) -> str:
    account = normalize_provider_subdomain(
        account_id,
        "r2.cloudflarestorage.com",
        field_name="Cloudflare account ID",
    )
    return f"https://{account}.r2.cloudflarestorage.com"


# ─── Credential Models ─────────────────────────────────────────────────────────


class CloudflareAPITokenCredential(BaseModel):
    """
    Cloudflare API Token (Recommended).
    Fine-grained, scoped token created from the Cloudflare dashboard.

    Create your API Token at: https://dash.cloudflare.com/profile/api-tokens
    """

    credential_type: Literal["cloudflare_api_token"] = "cloudflare_api_token"
    api_token: str = Field(
        description="Your Cloudflare API Token (Bearer token)",
        json_schema_extra={"ui:widget": "password"},
    )
    account_id: Optional[str] = Field(
        default=None,
        description="Your Cloudflare Account ID (required for account-level APIs like Workers, KV, D1, R2, Queues)",
    )

    model_config = {
        "json_schema_extra": {
            "x-credential-url": "https://dash.cloudflare.com/profile/api-tokens",
            "x-credential-instructions": "Create a scoped API Token from your Cloudflare dashboard. Grant permissions only for the resources you need.",
        }
    }


class CloudflareAPIKeyCredential(BaseModel):
    """
    Cloudflare Global API Key (Legacy).
    Provides full account access. Use API Tokens for better security.

    Find your Global API Key at: https://dash.cloudflare.com/profile/api-tokens
    """

    credential_type: Literal["cloudflare_api_key"] = "cloudflare_api_key"
    api_key: str = Field(
        description="Your Cloudflare Global API Key",
        json_schema_extra={"ui:widget": "password"},
    )
    email: str = Field(
        description="Your Cloudflare account email address",
    )
    account_id: Optional[str] = Field(
        default=None,
        description="Your Cloudflare Account ID (required for account-level APIs)",
    )

    model_config = {
        "json_schema_extra": {
            "x-credential-url": "https://dash.cloudflare.com/profile/api-tokens",
            "x-credential-instructions": "Use your Global API Key and account email. We recommend API Tokens instead for better security.",
        }
    }


class CloudflareOAuthCredential(BaseModel):
    """OAuth 2.0 credential for Cloudflare. Obtained via OAuth flow — not entered manually.
    Register an OAuth app at: Cloudflare Dashboard → Manage Account → OAuth clients
    """

    credential_type: Literal["cloudflare_oauth"] = Field(
        "cloudflare_oauth", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(..., title="Access Token")
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")
    email: Optional[str] = Field(None, title="Account Email")
    account_id: Optional[str] = Field(None, title="Account ID")

    model_config = ConfigDict(
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "cloudflare",
            "x-oauth-scopes": [
                # 'offline_access' is required for Cloudflare to issue a
                # refresh_token — the client's "Refresh Token" grant type alone
                # doesn't (verified: resource-scopes-only connect stored an empty
                # refresh_token). It's an OIDC scope; do NOT add 'openid' (the
                # client rejects it). If offline_access is also rejected it must
                # first be allowed on the client.
                "offline_access",
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
                "realtime.admin",
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
            ],
        }
    )


# OAuth first in the Union so the UI offers it as the primary option
CloudflareCredential = Union[CloudflareOAuthCredential, CloudflareAPITokenCredential, CloudflareAPIKeyCredential]


# ─── DNS Record Config Models ──────────────────────────────────────────────────


class CloudflareListDNSRecordsConfig(BaseModel):
    """List DNS records for a zone"""

    operation: Literal["list_dns_records"] = Field(
        default="list_dns_records",
        title="List Dns Records",
        json_schema_extra={
            "x-category": "DNS Record",
            "x-is-trigger": False,
            "x-display-name": "List Dns Records",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID to list DNS records for", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    record_type: Optional[str] = Field(
        default=None,
        description="Filter by record type (A, AAAA, CNAME, MX, TXT, NS, etc.)",
        json_schema_extra={
            "enum": [
                "A",
                "AAAA",
                "CNAME",
                "MX",
                "TXT",
                "NS",
                "SRV",
                "CAA",
                "PTR",
                "SOA",
                "CERT",
                "DNSKEY",
                "DS",
                "NAPTR",
                "SMIMEA",
                "SSHFP",
                "SVCB",
                "TLSA",
                "URI",
            ],
            "x-enum-searchable": True,
        },
    )
    name: Optional[str] = Field(default=None, description="Filter by DNS record name")


class CloudflareCreateDNSRecordConfig(BaseModel):
    """Create a new DNS record"""

    operation: Literal["create_dns_record"] = Field(
        default="create_dns_record",
        title="Create Dns Record",
        json_schema_extra={
            "x-category": "DNS Record",
            "x-is-trigger": False,
            "x-display-name": "Create Dns Record",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    record_type: str = Field(
        description="DNS record type",
        json_schema_extra={
            "enum": ["A", "AAAA", "CNAME", "MX", "TXT", "NS", "SRV", "CAA"],
            "x-enum-searchable": True,
        },
    )
    name: str = Field(
        description="DNS record name (e.g., example.com or sub.example.com)"
    )
    content: str = Field(description="DNS record content/value (e.g., IP address)")
    ttl: Optional[int] = Field(default=1, description="TTL in seconds (1 = automatic)")
    proxied: Optional[str] = Field(
        default="false",
        description="Whether to proxy through Cloudflare",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    priority: Optional[int] = Field(
        default=None, description="Priority for MX/SRV records"
    )


class CloudflareGetDNSRecordConfig(BaseModel):
    """Get a specific DNS record"""

    operation: Literal["get_dns_record"] = Field(
        default="get_dns_record",
        title="Get Dns Record",
        json_schema_extra={
            "x-category": "DNS Record",
            "x-is-trigger": False,
            "x-display-name": "Get Dns Record",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    record_id: str = Field(description="The DNS record ID")


class CloudflareUpdateDNSRecordConfig(BaseModel):
    """Update an existing DNS record"""

    operation: Literal["update_dns_record"] = Field(
        default="update_dns_record",
        title="Update Dns Record",
        json_schema_extra={
            "x-category": "DNS Record",
            "x-is-trigger": False,
            "x-display-name": "Update Dns Record",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    record_id: str = Field(description="The DNS record ID to update")
    record_type: Optional[str] = Field(
        default=None,
        description="DNS record type",
        json_schema_extra={
            "enum": ["A", "AAAA", "CNAME", "MX", "TXT", "NS", "SRV", "CAA"],
            "x-enum-searchable": True,
        },
    )
    name: Optional[str] = Field(default=None, description="DNS record name")
    content: Optional[str] = Field(default=None, description="DNS record content/value")
    ttl: Optional[int] = Field(
        default=None, description="TTL in seconds (1 = automatic)"
    )
    proxied: Optional[str] = Field(
        default=None,
        description="Whether to proxy through Cloudflare",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareDeleteDNSRecordConfig(BaseModel):
    """Delete a DNS record"""

    operation: Literal["delete_dns_record"] = Field(
        default="delete_dns_record",
        title="Delete Dns Record",
        json_schema_extra={
            "x-category": "DNS Record",
            "x-is-trigger": False,
            "x-display-name": "Delete Dns Record",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    record_id: str = Field(description="The DNS record ID to delete")


# ─── Zone Management Config Models ────────────────────────────────────────────


class CloudflareListZonesConfig(BaseModel):
    """List all zones in an account"""

    operation: Literal["list_zones"] = Field(
        default="list_zones",
        title="List Zones",
        json_schema_extra={
            "x-category": "Zone",
            "x-is-trigger": False,
            "x-display-name": "List Zones",
            "ui:hidden": True,
        },
    )
    name: Optional[str] = Field(
        default=None, description="Filter by zone name (domain)"
    )
    status: Optional[str] = Field(
        default=None,
        description="Filter by zone status",
        json_schema_extra={
            "enum": ["active", "pending", "initializing", "moved", "deleted"],
            "x-enum-searchable": True,
        },
    )


class CloudflareGetZoneConfig(BaseModel):
    """Get details for a specific zone"""

    operation: Literal["get_zone"] = Field(
        default="get_zone",
        title="Get Zone",
        json_schema_extra={
            "x-category": "Zone",
            "x-is-trigger": False,
            "x-display-name": "Get Zone",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareGetZoneSettingsConfig(BaseModel):
    """Get all settings for a zone"""

    operation: Literal["get_zone_settings"] = Field(
        default="get_zone_settings",
        title="Get Zone Settings",
        json_schema_extra={
            "x-category": "Zone",
            "x-is-trigger": False,
            "x-display-name": "Get Zone Settings",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareUpdateZoneSettingConfig(BaseModel):
    """Update a specific zone setting"""

    operation: Literal["update_zone_setting"] = Field(
        default="update_zone_setting",
        title="Update Zone Setting",
        json_schema_extra={
            "x-category": "Zone",
            "x-is-trigger": False,
            "x-display-name": "Update Zone Setting",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    setting_id: str = Field(
        description="Zone setting identifier (e.g., ssl, security_level, cache_level)",
        json_schema_extra={
            "enum": [
                "ssl",
                "security_level",
                "cache_level",
                "minify",
                "rocket_loader",
                "browser_cache_ttl",
                "always_use_https",
                "automatic_https_rewrites",
                "http2",
                "http3",
                "zero_rtt",
                "ip_geolocation",
                "email_obfuscation",
                "server_side_exclude",
                "hotlink_protection",
                "development_mode",
            ],
            "x-enum-searchable": True,
        },
    )
    value: str = Field(description="New value for the setting")


class CloudflarePurgeZoneCacheConfig(BaseModel):
    """Purge zone cache"""

    operation: Literal["purge_zone_cache"] = Field(
        default="purge_zone_cache",
        title="Purge Zone Cache",
        json_schema_extra={
            "x-category": "Zone",
            "x-is-trigger": False,
            "x-display-name": "Purge Zone Cache",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    purge_all: Optional[str] = Field(
        default="true",
        description="Purge all cached files",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    files: Optional[str] = Field(
        default=None,
        description="Comma-separated URLs to purge (if not purging all)",
    )
    tags: Optional[str] = Field(
        default=None,
        description="Comma-separated cache tags to purge",
    )
    hosts: Optional[str] = Field(
        default=None,
        description="Comma-separated hostnames to purge",
    )


# ─── Workers Config Models ─────────────────────────────────────────────────────


class CloudflareListWorkersConfig(BaseModel):
    """List all Workers in an account"""

    operation: Literal["list_workers"] = Field(
        default="list_workers",
        title="List Workers",
        json_schema_extra={
            "x-category": "Worker",
            "x-is-trigger": False,
            "x-display-name": "List Workers",
            "ui:hidden": True,
        },
    )


class CloudflareGetWorkerConfig(BaseModel):
    """Get a Worker script"""

    operation: Literal["get_worker"] = Field(
        default="get_worker",
        title="Get Worker",
        json_schema_extra={
            "x-category": "Worker",
            "x-is-trigger": False,
            "x-display-name": "Get Worker",
            "ui:hidden": True,
        },
    )
    script_name: str = Field(description="The Worker script name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "worker_script_name",
            "placeholder": "Select a Worker script...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareUploadWorkerConfig(BaseModel):
    """Upload or update a Worker script"""

    operation: Literal["upload_worker_script"] = Field(
        default="upload_worker_script",
        title="Upload Worker Script",
        json_schema_extra={"x-creates-resource": True, "x-resource-type": "cloudflare_worker_script", "x-resource-id-path": "result.id", 
            "x-category": "Worker",
            "x-is-trigger": False,
            "x-display-name": "Upload Worker Script",
            "ui:hidden": True,
        },
    )
    script_name: str = Field(description="The Worker script name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "worker_script_name",
            "placeholder": "Select a Worker script...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    script_content: str = Field(
        description="JavaScript Worker script content",
        json_schema_extra={"ui:widget": "code_editor"},
    )
    compatibility_date: Optional[str] = Field(
        default=None,
        description="Compatibility date (e.g., 2024-01-01)",
    )


class CloudflareDeleteWorkerConfig(BaseModel):
    """Delete a Worker script"""

    operation: Literal["delete_worker"] = Field(
        default="delete_worker",
        title="Delete Worker",
        json_schema_extra={
            "x-category": "Worker",
            "x-is-trigger": False,
            "x-display-name": "Delete Worker",
            "ui:hidden": True,
        },
    )
    script_name: str = Field(description="The Worker script name to delete", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "worker_script_name",
            "placeholder": "Select a Worker script...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareListWorkerRoutesConfig(BaseModel):
    """List Worker routes for a zone"""

    operation: Literal["list_worker_routes"] = Field(
        default="list_worker_routes",
        title="List Worker Routes",
        json_schema_extra={
            "x-category": "Worker",
            "x-is-trigger": False,
            "x-display-name": "List Worker Routes",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareCreateWorkerRouteConfig(BaseModel):
    """Create a Worker route"""

    operation: Literal["create_worker_route"] = Field(
        default="create_worker_route",
        title="Create Worker Route",
        json_schema_extra={
            "x-category": "Worker",
            "x-is-trigger": False,
            "x-display-name": "Create Worker Route",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    pattern: str = Field(
        description="URL pattern for the route (e.g., example.com/api/*)"
    )
    script_name: Optional[str] = Field(
        default=None,
        description="Worker script name (leave empty to remove workers from pattern)",
    )


class CloudflareDeleteWorkerRouteConfig(BaseModel):
    """Delete a Worker route"""

    operation: Literal["delete_worker_route"] = Field(
        default="delete_worker_route",
        title="Delete Worker Route",
        json_schema_extra={
            "x-category": "Worker",
            "x-is-trigger": False,
            "x-display-name": "Delete Worker Route",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    route_id: str = Field(description="The route ID to delete")


# ─── Workers KV Config Models ──────────────────────────────────────────────────


class CloudflareListKVNamespacesConfig(BaseModel):
    """List all KV namespaces in an account"""

    operation: Literal["list_kv_namespaces"] = Field(
        default="list_kv_namespaces",
        title="List Kv Namespaces",
        json_schema_extra={
            "x-category": "KV",
            "x-is-trigger": False,
            "x-display-name": "List Kv Namespaces",
            "ui:hidden": True,
        },
    )


class CloudflareCreateKVNamespaceConfig(BaseModel):
    """Create a new KV namespace"""

    operation: Literal["create_kv_namespace"] = Field(
        default="create_kv_namespace",
        title="Create Kv Namespace",
        json_schema_extra={"x-creates-resource": True, "x-resource-type": "cloudflare_kv_namespace", "x-resource-id-path": "result.id", 
            "x-category": "KV",
            "x-is-trigger": False,
            "x-display-name": "Create Kv Namespace",
            "ui:hidden": True,
        },
    )
    title: str = Field(description="The namespace title")


class CloudflareDeleteKVNamespaceConfig(BaseModel):
    """Delete a KV namespace"""

    operation: Literal["delete_kv_namespace"] = Field(
        default="delete_kv_namespace",
        title="Delete Kv Namespace",
        json_schema_extra={
            "x-category": "KV",
            "x-is-trigger": False,
            "x-display-name": "Delete Kv Namespace",
            "ui:hidden": True,
        },
    )
    namespace_id: str = Field(description="The KV namespace ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "namespace_id",
            "placeholder": "Select a KV namespace...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareListKVKeysConfig(BaseModel):
    """List keys in a KV namespace"""

    operation: Literal["list_kv_keys"] = Field(
        default="list_kv_keys",
        title="List Kv Keys",
        json_schema_extra={
            "x-category": "KV",
            "x-is-trigger": False,
            "x-display-name": "List Kv Keys",
            "ui:hidden": True,
        },
    )
    namespace_id: str = Field(description="The KV namespace ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "namespace_id",
            "placeholder": "Select a KV namespace...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    prefix: Optional[str] = Field(default=None, description="Filter keys by prefix")
    limit: Optional[int] = Field(
        default=None, description="Max number of keys to return (1-1000)"
    )
    cursor: Optional[str] = Field(default=None, description="Cursor for pagination")


class CloudflareReadKVValueConfig(BaseModel):
    """Read a value from KV storage"""

    operation: Literal["read_kv_value"] = Field(
        default="read_kv_value",
        title="Read Kv Value",
        json_schema_extra={
            "x-category": "KV",
            "x-is-trigger": False,
            "x-display-name": "Read Kv Value",
            "ui:hidden": True,
        },
    )
    namespace_id: str = Field(description="The KV namespace ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "namespace_id",
            "placeholder": "Select a KV namespace...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    key_name: str = Field(description="The key to read")


class CloudflareWriteKVValueConfig(BaseModel):
    """Write a value to KV storage"""

    operation: Literal["write_kv_value"] = Field(
        default="write_kv_value",
        title="Write Kv Value",
        json_schema_extra={
            "x-category": "KV",
            "x-is-trigger": False,
            "x-display-name": "Write Kv Value",
            "ui:hidden": True,
        },
    )
    namespace_id: str = Field(description="The KV namespace ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "namespace_id",
            "placeholder": "Select a KV namespace...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    key_name: str = Field(description="The key to write")
    value: str = Field(description="The value to store")
    expiration_ttl: Optional[int] = Field(
        default=None,
        description="Time-to-live in seconds (key auto-deletes after this time)",
    )


class CloudflareDeleteKVValueConfig(BaseModel):
    """Delete a key from KV storage"""

    operation: Literal["delete_kv_value"] = Field(
        default="delete_kv_value",
        title="Delete Kv Value",
        json_schema_extra={
            "x-category": "KV",
            "x-is-trigger": False,
            "x-display-name": "Delete Kv Value",
            "ui:hidden": True,
        },
    )
    namespace_id: str = Field(description="The KV namespace ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "namespace_id",
            "placeholder": "Select a KV namespace...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    key_name: str = Field(description="The key to delete")


class CloudflareBulkWriteKVConfig(BaseModel):
    """Write multiple key-value pairs at once (up to 10,000 pairs)"""

    operation: Literal["bulk_write_kv_pairs"] = Field(
        default="bulk_write_kv_pairs",
        title="Bulk Write Kv Pairs",
        json_schema_extra={
            "x-category": "KV",
            "x-is-trigger": False,
            "x-display-name": "Bulk Write Kv Pairs",
            "ui:hidden": True,
        },
    )
    namespace_id: str = Field(description="The KV namespace ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "namespace_id",
            "placeholder": "Select a KV namespace...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    pairs: str = Field(
        description='JSON array of {key, value} objects. Example: [{"key": "foo", "value": "bar"}]',
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 5},
    )


# ─── D1 Database Config Models ─────────────────────────────────────────────────


class CloudflareListD1DatabasesConfig(BaseModel):
    """List all D1 databases in an account"""

    operation: Literal["list_d1_databases"] = Field(
        default="list_d1_databases",
        title="List D1 Databases",
        json_schema_extra={
            "x-category": "D1 Database",
            "x-is-trigger": False,
            "x-display-name": "List D1 Databases",
            "ui:hidden": True,
        },
    )
    name: Optional[str] = Field(default=None, description="Filter databases by name")


class CloudflareGetD1DatabaseConfig(BaseModel):
    """Get details for a D1 database"""

    operation: Literal["get_d1_database"] = Field(
        default="get_d1_database",
        title="Get D1 Database",
        json_schema_extra={
            "x-category": "D1 Database",
            "x-is-trigger": False,
            "x-display-name": "Get D1 Database",
            "ui:hidden": True,
        },
    )
    database_id: str = Field(description="The D1 database ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "database_id",
            "placeholder": "Select a D1 database...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareCreateD1DatabaseConfig(BaseModel):
    """Create a new D1 database"""

    operation: Literal["create_d1_database"] = Field(
        default="create_d1_database",
        title="Create D1 Database",
        json_schema_extra={"x-creates-resource": True, "x-resource-type": "cloudflare_d1_database", "x-resource-id-path": "result.uuid", 
            "x-category": "D1 Database",
            "x-is-trigger": False,
            "x-display-name": "Create D1 Database",
            "ui:hidden": True,
        },
    )
    name: str = Field(description="The database name")
    location: Optional[str] = Field(
        default=None,
        description="Preferred geographic location hint",
        json_schema_extra={
            "enum": ["wnam", "enam", "weur", "eeur", "apac", "oc"],
            "x-enum-searchable": True,
        },
    )


class CloudflareDeleteD1DatabaseConfig(BaseModel):
    """Delete a D1 database"""

    operation: Literal["delete_d1_database"] = Field(
        default="delete_d1_database",
        title="Delete D1 Database",
        json_schema_extra={
            "x-category": "D1 Database",
            "x-is-trigger": False,
            "x-display-name": "Delete D1 Database",
            "ui:hidden": True,
        },
    )
    database_id: str = Field(description="The D1 database ID to delete", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "database_id",
            "placeholder": "Select a D1 database...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareQueryD1DatabaseConfig(BaseModel):
    """Execute a SQL query against a D1 database"""

    operation: Literal["execute_d1_sql_query"] = Field(
        default="execute_d1_sql_query",
        title="Execute D1 Sql Query",
        json_schema_extra={
            "x-category": "D1 Database",
            "x-is-trigger": False,
            "x-display-name": "Execute D1 Sql Query",
            "ui:hidden": True,
        },
    )
    database_id: str = Field(description="The D1 database ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "database_id",
            "placeholder": "Select a D1 database...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    sql: str = Field(
        description="SQL query to execute",
        json_schema_extra={"ui:widget": "code_editor"},
    )
    params: Optional[str] = Field(
        default=None,
        description='JSON array of query parameters for parameterized queries (e.g., ["value1", 42])',
    )


class CloudflareExportD1DatabaseConfig(BaseModel):
    """Export a D1 database as SQL"""

    operation: Literal["export_d1_database_as_sql"] = Field(
        default="export_d1_database_as_sql",
        title="Export D1 Database As Sql",
        json_schema_extra={
            "x-category": "D1 Database",
            "x-is-trigger": False,
            "x-display-name": "Export D1 Database As Sql",
            "ui:hidden": True,
        },
    )
    database_id: str = Field(description="The D1 database ID to export", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "database_id",
            "placeholder": "Select a D1 database...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    output_format: Optional[str] = Field(
        default="polling",
        description="Export format",
        json_schema_extra={"enum": ["polling"], "x-enum-searchable": True},
    )


# ─── R2 Storage Config Models ──────────────────────────────────────────────────


class CloudflareListR2BucketsConfig(BaseModel):
    """List all R2 buckets in an account"""

    operation: Literal["list_r2_buckets"] = Field(
        default="list_r2_buckets",
        title="List R2 Buckets",
        json_schema_extra={
            "x-category": "R2 Bucket",
            "x-is-trigger": False,
            "x-display-name": "List R2 Buckets",
            "ui:hidden": True,
        },
    )
    name_contains: Optional[str] = Field(
        default=None, description="Filter buckets by name substring"
    )


class CloudflareGetR2BucketConfig(BaseModel):
    """Get details for an R2 bucket"""

    operation: Literal["get_r2_bucket"] = Field(
        default="get_r2_bucket",
        title="Get R2 Bucket",
        json_schema_extra={
            "x-category": "R2 Bucket",
            "x-is-trigger": False,
            "x-display-name": "Get R2 Bucket",
            "ui:hidden": True,
        },
    )
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareCreateR2BucketConfig(BaseModel):
    """Create a new R2 bucket"""

    operation: Literal["create_r2_bucket"] = Field(
        default="create_r2_bucket",
        title="Create R2 Bucket",
        json_schema_extra={"x-creates-resource": True, "x-resource-type": "cloudflare_r2_bucket", "x-resource-id-path": "result.name", 
            "x-category": "R2 Bucket",
            "x-is-trigger": False,
            "x-display-name": "Create R2 Bucket",
            "ui:hidden": True,
        },
    )
    bucket_name: str = Field(
        description="The bucket name (must be globally unique within your account)"
    )
    location_hint: Optional[str] = Field(
        default=None,
        description="Geographic location hint",
        json_schema_extra={
            "enum": ["apac", "eeur", "enam", "oc", "weur", "wnam"],
            "x-enum-searchable": True,
        },
    )
    storage_class: Optional[str] = Field(
        default=None,
        description="Default storage class",
        json_schema_extra={
            "enum": ["Standard", "InfrequentAccess"],
            "x-enum-searchable": True,
        },
    )


class CloudflareDeleteR2BucketConfig(BaseModel):
    """Delete an R2 bucket"""

    operation: Literal["delete_r2_bucket"] = Field(
        default="delete_r2_bucket",
        title="Delete R2 Bucket",
        json_schema_extra={
            "x-category": "R2 Bucket",
            "x-is-trigger": False,
            "x-display-name": "Delete R2 Bucket",
            "ui:hidden": True,
        },
    )
    bucket_name: str = Field(description="The R2 bucket name to delete", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })




# ─── Pages Config Models ───────────────────────────────────────────────────────


class CloudflareListPagesProjectsConfig(BaseModel):
    """List all Pages projects in an account"""

    operation: Literal["list_pages_projects"] = Field(
        default="list_pages_projects",
        title="List Pages Projects",
        json_schema_extra={
            "x-category": "Pages",
            "x-is-trigger": False,
            "x-display-name": "List Pages Projects",
            "ui:hidden": True,
        },
    )


class CloudflareGetPagesProjectConfig(BaseModel):
    """Get a Pages project"""

    operation: Literal["get_pages_project"] = Field(
        default="get_pages_project",
        title="Get Pages Project",
        json_schema_extra={
            "x-category": "Pages",
            "x-is-trigger": False,
            "x-display-name": "Get Pages Project",
            "ui:hidden": True,
        },
    )
    project_name: str = Field(description="The Pages project name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "project_name",
            "placeholder": "Select a Pages project...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareDeletePagesProjectConfig(BaseModel):
    """Delete a Pages project"""

    operation: Literal["delete_pages_project"] = Field(
        default="delete_pages_project",
        title="Delete Pages Project",
        json_schema_extra={
            "x-category": "Pages",
            "x-is-trigger": False,
            "x-display-name": "Delete Pages Project",
            "ui:hidden": True,
        },
    )
    project_name: str = Field(description="The Pages project name to delete", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "project_name",
            "placeholder": "Select a Pages project...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareListPagesDeploymentsConfig(BaseModel):
    """List deployments for a Pages project"""

    operation: Literal["list_pages_deployments"] = Field(
        default="list_pages_deployments",
        title="List Pages Deployments",
        json_schema_extra={
            "x-category": "Pages",
            "x-is-trigger": False,
            "x-display-name": "List Pages Deployments",
            "ui:hidden": True,
        },
    )
    project_name: str = Field(description="The Pages project name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "project_name",
            "placeholder": "Select a Pages project...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareGetPagesDeploymentConfig(BaseModel):
    """Get a specific Pages deployment"""

    operation: Literal["get_pages_deployment"] = Field(
        default="get_pages_deployment",
        title="Get Pages Deployment",
        json_schema_extra={
            "x-category": "Pages",
            "x-is-trigger": False,
            "x-display-name": "Get Pages Deployment",
            "ui:hidden": True,
        },
    )
    project_name: str = Field(description="The Pages project name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "project_name",
            "placeholder": "Select a Pages project...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    deployment_id: str = Field(description="The deployment ID")


class CloudflareDeletePagesDeploymentConfig(BaseModel):
    """Delete a Pages deployment"""

    operation: Literal["delete_pages_deployment"] = Field(
        default="delete_pages_deployment",
        title="Delete Pages Deployment",
        json_schema_extra={
            "x-category": "Pages",
            "x-is-trigger": False,
            "x-display-name": "Delete Pages Deployment",
            "ui:hidden": True,
        },
    )
    project_name: str = Field(description="The Pages project name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "project_name",
            "placeholder": "Select a Pages project...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    deployment_id: str = Field(description="The deployment ID to delete")


# ─── Stream (Video) Config Models ──────────────────────────────────────────────


class CloudflareListStreamVideosConfig(BaseModel):
    """List videos in Cloudflare Stream"""

    operation: Literal["list_stream_videos"] = Field(
        default="list_stream_videos",
        title="List Stream Videos",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "List Stream Videos",
            "ui:hidden": True,
        },
    )
    search: Optional[str] = Field(default=None, description="Search by video name")
    status: Optional[str] = Field(
        default=None,
        description="Filter by processing status",
        json_schema_extra={
            "enum": [
                "pendingupload",
                "downloading",
                "queued",
                "inprogress",
                "ready",
                "error",
            ],
            "x-enum-searchable": True,
        },
    )
    limit: Optional[int] = Field(default=None, description="Max number of results")


class CloudflareGetStreamVideoConfig(BaseModel):
    """Get details for a Stream video"""

    operation: Literal["get_stream_video"] = Field(
        default="get_stream_video",
        title="Get Stream Video",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Get Stream Video",
            "ui:hidden": True,
        },
    )
    video_id: str = Field(description="The Stream video UID")


class CloudflareDeleteStreamVideoConfig(BaseModel):
    """Delete a Stream video"""

    operation: Literal["delete_stream_video"] = Field(
        default="delete_stream_video",
        title="Delete Stream Video",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Delete Stream Video",
            "ui:hidden": True,
        },
    )
    video_id: str = Field(description="The Stream video UID to delete")


class CloudflareGetStreamVideoEmbedConfig(BaseModel):
    """Get embed code for a Stream video"""

    operation: Literal["get_stream_video_embed_code"] = Field(
        default="get_stream_video_embed_code",
        title="Get Stream Video Embed Code",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Get Stream Video Embed Code",
            "ui:hidden": True,
        },
    )
    video_id: str = Field(description="The Stream video UID")
    autoplay: Optional[str] = Field(
        default="false",
        description="Enable autoplay",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    loop: Optional[str] = Field(
        default="false",
        description="Enable loop",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    muted: Optional[str] = Field(
        default="false",
        description="Start muted",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareListStreamLiveInputsConfig(BaseModel):
    """List all live inputs for Stream"""

    operation: Literal["list_stream_live_inputs"] = Field(
        default="list_stream_live_inputs",
        title="List Stream Live Inputs",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "List Stream Live Inputs",
            "ui:hidden": True,
        },
    )
    include_counts: Optional[str] = Field(
        default="false",
        description="Include connection counts",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareCreateStreamLiveInputConfig(BaseModel):
    """Create a new Stream live input"""

    operation: Literal["create_stream_live_input"] = Field(
        default="create_stream_live_input",
        title="Create Stream Live Input",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Create Stream Live Input",
            "ui:hidden": True,
        },
    )
    name: Optional[str] = Field(default=None, description="Name for the live input")
    recording_mode: Optional[str] = Field(
        default="off",
        description="Recording mode for the live input",
        json_schema_extra={"enum": ["off", "automatic"], "x-enum-searchable": True},
    )


class CloudflareDeleteStreamLiveInputConfig(BaseModel):
    """Delete a Stream live input"""

    operation: Literal["delete_stream_live_input"] = Field(
        default="delete_stream_live_input",
        title="Delete Stream Live Input",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Delete Stream Live Input",
            "ui:hidden": True,
        },
    )
    live_input_id: str = Field(description="The live input ID to delete")


# ─── Stream Extended Config Models ────────────────────────────────────────────


class CloudflareCreateStreamUploadUrlConfig(BaseModel):
    """Create a Stream upload URL or initiate a URL-based upload"""

    operation: Literal["create_stream_upload_url"] = Field(
        default="create_stream_upload_url",
        title="Create Stream Upload URL",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Create Stream Upload URL",
            "ui:hidden": True,
        },
    )
    max_duration_seconds: Optional[int] = Field(
        default=3600, description="Max video duration in seconds"
    )
    require_signed_urls: Optional[str] = Field(
        default="false",
        description="Require signed URLs to view the video",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    allowed_origins: Optional[str] = Field(
        default=None, description="Comma-separated allowed origins"
    )
    video_url: Optional[str] = Field(
        default=None, description="URL to fetch video from (for URL-based upload)"
    )


class CloudflareCreateStreamSignedUrlConfig(BaseModel):
    """Create a signed URL token for a Stream video"""

    operation: Literal["create_stream_signed_url"] = Field(
        default="create_stream_signed_url",
        title="Create Stream Signed URL",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Create Stream Signed URL",
            "ui:hidden": True,
        },
    )
    video_id: str = Field(description="The Stream video UID")
    expiry_seconds: Optional[int] = Field(
        default=3600, description="Token validity in seconds"
    )


class CloudflareListStreamSigningKeysConfig(BaseModel):
    """List Stream signing keys"""

    operation: Literal["list_stream_signing_keys"] = Field(
        default="list_stream_signing_keys",
        title="List Stream Signing Keys",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "List Stream Signing Keys",
            "ui:hidden": True,
        },
    )


class CloudflareCreateStreamSigningKeyConfig(BaseModel):
    """Create a new Stream signing key"""

    operation: Literal["create_stream_signing_key"] = Field(
        default="create_stream_signing_key",
        title="Create Stream Signing Key",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Create Stream Signing Key",
            "ui:hidden": True,
        },
    )


class CloudflareDeleteStreamSigningKeyConfig(BaseModel):
    """Delete a Stream signing key"""

    operation: Literal["delete_stream_signing_key"] = Field(
        default="delete_stream_signing_key",
        title="Delete Stream Signing Key",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Delete Stream Signing Key",
            "ui:hidden": True,
        },
    )
    key_id: str = Field(description="The signing key ID to delete")


class CloudflareListStreamCaptionsConfig(BaseModel):
    """List captions for a Stream video"""

    operation: Literal["list_stream_captions"] = Field(
        default="list_stream_captions",
        title="List Stream Captions",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "List Stream Captions",
            "ui:hidden": True,
        },
    )
    video_id: str = Field(description="The Stream video UID")


class CloudflareUploadStreamCaptionConfig(BaseModel):
    """Upload a caption track for a Stream video"""

    operation: Literal["upload_stream_caption"] = Field(
        default="upload_stream_caption",
        title="Upload Stream Caption",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Upload Stream Caption",
            "ui:hidden": True,
        },
    )
    video_id: str = Field(description="The Stream video UID")
    language: str = Field(description="BCP 47 language code e.g. en, es, fr")
    caption_content: str = Field(description="WebVTT or SRT caption content")


class CloudflareDeleteStreamCaptionConfig(BaseModel):
    """Delete a caption track from a Stream video"""

    operation: Literal["delete_stream_caption"] = Field(
        default="delete_stream_caption",
        title="Delete Stream Caption",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Delete Stream Caption",
            "ui:hidden": True,
        },
    )
    video_id: str = Field(description="The Stream video UID")
    language: str = Field(description="BCP 47 language code of the caption to delete")


class CloudflareListStreamWatermarksConfig(BaseModel):
    """List Stream watermark profiles"""

    operation: Literal["list_stream_watermarks"] = Field(
        default="list_stream_watermarks",
        title="List Stream Watermarks",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "List Stream Watermarks",
            "ui:hidden": True,
        },
    )


class CloudflareCreateStreamWatermarkConfig(BaseModel):
    """Create a Stream watermark profile from a URL"""

    operation: Literal["create_stream_watermark"] = Field(
        default="create_stream_watermark",
        title="Create Stream Watermark",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Create Stream Watermark",
            "ui:hidden": True,
        },
    )
    watermark_url: str = Field(description="URL of the PNG watermark image to download and use")
    name: Optional[str] = Field(default=None, description="Watermark profile name")
    opacity: Optional[float] = Field(default=1.0, description="Opacity 0.0-1.0")
    padding: Optional[float] = Field(default=0.05, description="Padding from edge 0.0-0.5")
    scale: Optional[float] = Field(default=0.15, description="Scale relative to video size 0.0-1.0")
    position: Optional[str] = Field(
        default="upperRight",
        description="Position of the watermark on the video",
        json_schema_extra={
            "enum": ["upperRight", "upperLeft", "lowerRight", "lowerLeft", "center"],
            "x-enum-searchable": True,
        },
    )


class CloudflareGetStreamWatermarkConfig(BaseModel):
    """Get a Stream watermark profile"""

    operation: Literal["get_stream_watermark"] = Field(
        default="get_stream_watermark",
        title="Get Stream Watermark",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Get Stream Watermark",
            "ui:hidden": True,
        },
    )
    watermark_uid: str = Field(description="The watermark profile UID")


class CloudflareDeleteStreamWatermarkConfig(BaseModel):
    """Delete a Stream watermark profile"""

    operation: Literal["delete_stream_watermark"] = Field(
        default="delete_stream_watermark",
        title="Delete Stream Watermark",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Delete Stream Watermark",
            "ui:hidden": True,
        },
    )
    watermark_uid: str = Field(description="The watermark profile UID to delete")


class CloudflareListStreamAudioTracksConfig(BaseModel):
    """List audio tracks for a Stream video"""

    operation: Literal["list_stream_audio_tracks"] = Field(
        default="list_stream_audio_tracks",
        title="List Stream Audio Tracks",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "List Stream Audio Tracks",
            "ui:hidden": True,
        },
    )
    video_id: str = Field(description="The Stream video UID")


class CloudflareAddStreamAudioTrackConfig(BaseModel):
    """Add an audio track to a Stream video by copying from a URL"""

    operation: Literal["add_stream_audio_track"] = Field(
        default="add_stream_audio_track",
        title="Add Stream Audio Track",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Add Stream Audio Track",
            "ui:hidden": True,
        },
    )
    video_id: str = Field(description="The Stream video UID")
    audio_url: str = Field(description="URL of audio track to copy")
    track_label: str = Field(description="Label e.g. English, Spanish")


class CloudflareEditStreamAudioTrackConfig(BaseModel):
    """Edit an audio track on a Stream video"""

    operation: Literal["edit_stream_audio_track"] = Field(
        default="edit_stream_audio_track",
        title="Edit Stream Audio Track",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Edit Stream Audio Track",
            "ui:hidden": True,
        },
    )
    video_id: str = Field(description="The Stream video UID")
    audio_id: str = Field(description="The audio track ID")
    track_label: Optional[str] = Field(default=None, description="New label for the audio track")
    is_default: Optional[str] = Field(
        default=None,
        description="Set as default audio track",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareDeleteStreamAudioTrackConfig(BaseModel):
    """Delete an audio track from a Stream video"""

    operation: Literal["delete_stream_audio_track"] = Field(
        default="delete_stream_audio_track",
        title="Delete Stream Audio Track",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Delete Stream Audio Track",
            "ui:hidden": True,
        },
    )
    video_id: str = Field(description="The Stream video UID")
    audio_id: str = Field(description="The audio track ID to delete")


class CloudflareUpdateStreamVideoConfig(BaseModel):
    """Update metadata and settings for a Stream video"""

    operation: Literal["update_stream_video"] = Field(
        default="update_stream_video",
        title="Update Stream Video",
        json_schema_extra={
            "x-category": "Stream",
            "x-is-trigger": False,
            "x-display-name": "Update Stream Video",
            "ui:hidden": True,
        },
    )
    video_id: str = Field(description="The Stream video UID")
    require_signed_urls: Optional[str] = Field(
        default=None,
        description="Require signed URLs to view the video",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    allowed_origins: Optional[str] = Field(
        default=None, description="Comma-separated allowed origins"
    )
    scheduled_deletion: Optional[str] = Field(
        default=None, description="ISO 8601 datetime for auto-deletion"
    )


# ─── Images Config Models ──────────────────────────────────────────────────────


class CloudflareListImagesConfig(BaseModel):
    """List images in Cloudflare Images"""

    operation: Literal["list_images"] = Field(
        default="list_images",
        title="List Images",
        json_schema_extra={
            "x-category": "Image",
            "x-is-trigger": False,
            "x-display-name": "List Images",
            "ui:hidden": True,
        },
    )
    page: Optional[int] = Field(default=1, description="Page number for pagination")
    per_page: Optional[int] = Field(default=50, description="Images per page (max 100)")


class CloudflareGetImageConfig(BaseModel):
    """Get details for an image"""

    operation: Literal["get_image"] = Field(
        default="get_image",
        title="Get Image",
        json_schema_extra={
            "x-category": "Image",
            "x-is-trigger": False,
            "x-display-name": "Get Image",
            "ui:hidden": True,
        },
    )
    image_id: str = Field(description="The image ID")


class CloudflareDeleteImageConfig(BaseModel):
    """Delete an image"""

    operation: Literal["delete_image"] = Field(
        default="delete_image",
        title="Delete Image",
        json_schema_extra={
            "x-category": "Image",
            "x-is-trigger": False,
            "x-display-name": "Delete Image",
            "ui:hidden": True,
        },
    )
    image_id: str = Field(description="The image ID to delete")


class CloudflareGetImagesStatsConfig(BaseModel):
    """Get image usage statistics"""

    operation: Literal["get_image_usage_statistics"] = Field(
        default="get_image_usage_statistics",
        title="Get Image Usage Statistics",
        json_schema_extra={
            "x-category": "Image",
            "x-is-trigger": False,
            "x-display-name": "Get Image Usage Statistics",
            "ui:hidden": True,
        },
    )


class CloudflareCreateImageDirectUploadConfig(BaseModel):
    """Create a direct upload URL for images"""

    operation: Literal["create_image_direct_upload_url"] = Field(
        default="create_image_direct_upload_url",
        title="Create Image Direct Upload Url",
        json_schema_extra={
            "x-category": "Image",
            "x-is-trigger": False,
            "x-display-name": "Create Image Direct Upload Url",
            "ui:hidden": True,
        },
    )
    metadata: Optional[str] = Field(
        default=None,
        description='Optional JSON metadata for the image (e.g., {"source": "user-upload"})',
    )
    require_signed_urls: Optional[str] = Field(
        default="false",
        description="Require signed URLs to access this image",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


# ─── Firewall / WAF Config Models ──────────────────────────────────────────────


class CloudflareListFirewallRulesConfig(BaseModel):
    """List firewall rules for a zone"""

    operation: Literal["list_firewall_rules"] = Field(
        default="list_firewall_rules",
        title="List Firewall Rules",
        json_schema_extra={
            "x-category": "Firewall Rule",
            "x-is-trigger": False,
            "x-display-name": "List Firewall Rules",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareCreateFirewallRuleConfig(BaseModel):
    """Create a firewall rule for a zone"""

    operation: Literal["create_firewall_rule"] = Field(
        default="create_firewall_rule",
        title="Create Firewall Rule",
        json_schema_extra={
            "x-category": "Firewall Rule",
            "x-is-trigger": False,
            "x-display-name": "Create Firewall Rule",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    expression: str = Field(
        description="Firewall rule expression (e.g., ip.src eq 1.2.3.4)",
    )
    rule_action: str = Field(
        description="Action to take",
        json_schema_extra={
            "enum": [
                "block",
                "challenge",
                "js_challenge",
                "managed_challenge",
                "allow",
                "log",
                "bypass",
            ],
            "x-enum-searchable": True,
        },
    )
    description: Optional[str] = Field(default=None, description="Rule description")
    priority: Optional[int] = Field(
        default=None, description="Rule priority (higher = higher priority)"
    )
    paused: Optional[str] = Field(
        default="false",
        description="Whether the rule is paused",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareDeleteFirewallRuleConfig(BaseModel):
    """Delete a firewall rule"""

    operation: Literal["delete_firewall_rule"] = Field(
        default="delete_firewall_rule",
        title="Delete Firewall Rule",
        json_schema_extra={
            "x-category": "Firewall Rule",
            "x-is-trigger": False,
            "x-display-name": "Delete Firewall Rule",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    rule_id: str = Field(description="The firewall rule ID to delete")


class CloudflareListWAFPackagesConfig(BaseModel):
    """List WAF packages for a zone"""

    operation: Literal["list_zone_waf_packages"] = Field(
        default="list_zone_waf_packages",
        title="List Zone Waf Packages",
        json_schema_extra={
            "x-category": "WAF",
            "x-is-trigger": False,
            "x-display-name": "List Zone Waf Packages",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


# ─── Access (Zero Trust) Config Models ────────────────────────────────────────


class CloudflareListAccessApplicationsConfig(BaseModel):
    """List Cloudflare Access applications"""

    operation: Literal["list_access_applications"] = Field(
        default="list_access_applications",
        title="List Access Applications",
        json_schema_extra={
            "x-category": "Access",
            "x-is-trigger": False,
            "x-display-name": "List Access Applications",
            "ui:hidden": True,
        },
    )


class CloudflareGetAccessApplicationConfig(BaseModel):
    """Get a specific Access application"""

    operation: Literal["get_access_application"] = Field(
        default="get_access_application",
        title="Get Access Application",
        json_schema_extra={
            "x-category": "Access",
            "x-is-trigger": False,
            "x-display-name": "Get Access Application",
            "ui:hidden": True,
        },
    )
    app_id: str = Field(description="The Access application UUID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "access_app_id",
            "placeholder": "Select an Access application...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareCreateAccessApplicationConfig(BaseModel):
    """Create an Access application"""

    operation: Literal["create_access_application"] = Field(
        default="create_access_application",
        title="Create Access Application",
        json_schema_extra={"x-creates-resource": True, "x-resource-type": "cloudflare_access_application", "x-resource-id-path": "result.id", 
            "x-category": "Access",
            "x-is-trigger": False,
            "x-display-name": "Create Access Application",
            "ui:hidden": True,
        },
    )
    name: str = Field(description="Application name")
    domain: str = Field(description="Application domain (e.g., app.example.com)")
    session_duration: Optional[str] = Field(
        default="24h",
        description="Session duration (e.g., 24h, 7d)",
    )
    app_type: Optional[str] = Field(
        default="self_hosted",
        description="Application type",
        json_schema_extra={
            "enum": [
                "self_hosted",
                "saas",
                "ssh",
                "vnc",
                "app_launcher",
                "warp",
                "biso",
                "bookmark",
                "dash_sso",
            ],
            "x-enum-searchable": True,
        },
    )


class CloudflareDeleteAccessApplicationConfig(BaseModel):
    """Delete an Access application"""

    operation: Literal["delete_access_application"] = Field(
        default="delete_access_application",
        title="Delete Access Application",
        json_schema_extra={
            "x-category": "Access",
            "x-is-trigger": False,
            "x-display-name": "Delete Access Application",
            "ui:hidden": True,
        },
    )
    app_id: str = Field(description="The Access application UUID to delete", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "access_app_id",
            "placeholder": "Select an Access application...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareListAccessPoliciesConfig(BaseModel):
    """List policies for an Access application"""

    operation: Literal["list_access_application_policies"] = Field(
        default="list_access_application_policies",
        title="List Access Application Policies",
        json_schema_extra={
            "x-category": "Access",
            "x-is-trigger": False,
            "x-display-name": "List Access Application Policies",
            "ui:hidden": True,
        },
    )
    app_id: str = Field(description="The Access application UUID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "access_app_id",
            "placeholder": "Select an Access application...",
            "searchable": True,
            "allow_custom": True,
        }
    })


# ─── Tunnels Config Models ─────────────────────────────────────────────────────


class CloudflareListTunnelsConfig(BaseModel):
    """List Cloudflare Tunnels"""

    operation: Literal["list_tunnels"] = Field(
        default="list_tunnels",
        title="List Tunnels",
        json_schema_extra={
            "x-category": "Tunnel",
            "x-is-trigger": False,
            "x-display-name": "List Tunnels",
            "ui:hidden": True,
        },
    )
    name: Optional[str] = Field(default=None, description="Filter tunnels by name")
    is_deleted: Optional[str] = Field(
        default="false",
        description="Include deleted tunnels",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareGetTunnelConfig(BaseModel):
    """Get details for a specific tunnel"""

    operation: Literal["get_tunnel"] = Field(
        default="get_tunnel",
        title="Get Tunnel",
        json_schema_extra={
            "x-category": "Tunnel",
            "x-is-trigger": False,
            "x-display-name": "Get Tunnel",
            "ui:hidden": True,
        },
    )
    tunnel_id: str = Field(description="The tunnel UUID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "tunnel_id",
            "placeholder": "Select a tunnel...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareCreateTunnelConfig(BaseModel):
    """Create a new Cloudflare Tunnel"""

    operation: Literal["create_tunnel"] = Field(
        default="create_tunnel",
        title="Create Tunnel",
        json_schema_extra={"x-creates-resource": True, "x-resource-type": "cloudflare_tunnel", "x-resource-id-path": "result.id", 
            "x-category": "Tunnel",
            "x-is-trigger": False,
            "x-display-name": "Create Tunnel",
            "ui:hidden": True,
        },
    )
    name: str = Field(description="Tunnel name")
    tunnel_secret: Optional[str] = Field(
        default=None,
        description="Tunnel secret (base64 string, auto-generated if not provided)",
    )


class CloudflareDeleteTunnelConfig(BaseModel):
    """Delete a Cloudflare Tunnel"""

    operation: Literal["delete_tunnel"] = Field(
        default="delete_tunnel",
        title="Delete Tunnel",
        json_schema_extra={
            "x-category": "Tunnel",
            "x-is-trigger": False,
            "x-display-name": "Delete Tunnel",
            "ui:hidden": True,
        },
    )
    tunnel_id: str = Field(description="The tunnel UUID to delete", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "tunnel_id",
            "placeholder": "Select a tunnel...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareGetTunnelTokenConfig(BaseModel):
    """Get the token for a tunnel (used to run cloudflared)"""

    operation: Literal["get_tunnel_token"] = Field(
        default="get_tunnel_token",
        title="Get Tunnel Token",
        json_schema_extra={
            "x-category": "Tunnel",
            "x-is-trigger": False,
            "x-display-name": "Get Tunnel Token",
            "ui:hidden": True,
        },
    )
    tunnel_id: str = Field(description="The tunnel UUID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "tunnel_id",
            "placeholder": "Select a tunnel...",
            "searchable": True,
            "allow_custom": True,
        }
    })


# ─── Email Routing Config Models ───────────────────────────────────────────────


class CloudflareGetEmailRoutingConfig(BaseModel):
    """Get Email Routing settings for a zone"""

    operation: Literal["get_email_routing_settings"] = Field(
        default="get_email_routing_settings",
        title="Get Email Routing Settings",
        json_schema_extra={
            "x-category": "Email Routing",
            "x-is-trigger": False,
            "x-display-name": "Get Email Routing Settings",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareListEmailRoutingRulesConfig(BaseModel):
    """List Email Routing rules for a zone"""

    operation: Literal["list_email_routing_rules"] = Field(
        default="list_email_routing_rules",
        title="List Email Routing Rules",
        json_schema_extra={
            "x-category": "Email Routing",
            "x-is-trigger": False,
            "x-display-name": "List Email Routing Rules",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareCreateEmailRoutingRuleConfig(BaseModel):
    """Create an Email Routing rule"""

    operation: Literal["create_email_routing_rule"] = Field(
        default="create_email_routing_rule",
        title="Create Email Routing Rule",
        json_schema_extra={
            "x-category": "Email Routing",
            "x-is-trigger": False,
            "x-display-name": "Create Email Routing Rule",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    name: str = Field(description="Rule name")
    matchers: str = Field(
        description='JSON array of matchers. Example: [{"type": "literal", "field": "to", "value": "inbox@example.com"}]',
    )
    actions: str = Field(
        description='JSON array of actions. Example: [{"type": "forward", "value": ["destination@example.com"]}]',
    )
    enabled: Optional[str] = Field(
        default="true",
        description="Whether this rule is enabled",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareDeleteEmailRoutingRuleConfig(BaseModel):
    """Delete an Email Routing rule"""

    operation: Literal["delete_email_routing_rule"] = Field(
        default="delete_email_routing_rule",
        title="Delete Email Routing Rule",
        json_schema_extra={
            "x-category": "Email Routing",
            "x-is-trigger": False,
            "x-display-name": "Delete Email Routing Rule",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    rule_id: str = Field(description="The routing rule ID to delete")


class CloudflareListEmailRoutingAddressesConfig(BaseModel):
    """List destination email addresses for Email Routing"""

    operation: Literal["list_email_routing_destination_addresses"] = Field(
        default="list_email_routing_destination_addresses",
        title="List Email Routing Destination Addresses",
        json_schema_extra={
            "x-category": "Email Routing",
            "x-is-trigger": False,
            "x-display-name": "List Email Routing Destination Addresses",
            "ui:hidden": True,
        },
    )


# ─── Queues Config Models ──────────────────────────────────────────────────────


class CloudflareListQueuesConfig(BaseModel):
    """List all Queues in an account"""

    operation: Literal["list_queues"] = Field(
        default="list_queues",
        title="List Queues",
        json_schema_extra={
            "x-category": "Queue",
            "x-is-trigger": False,
            "x-display-name": "List Queues",
            "ui:hidden": True,
        },
    )


class CloudflareGetQueueConfig(BaseModel):
    """Get details for a Queue"""

    operation: Literal["get_queue"] = Field(
        default="get_queue",
        title="Get Queue",
        json_schema_extra={
            "x-category": "Queue",
            "x-is-trigger": False,
            "x-display-name": "Get Queue",
            "ui:hidden": True,
        },
    )
    queue_id: str = Field(description="The queue ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "queue_id",
            "placeholder": "Select a Queue...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareCreateQueueConfig(BaseModel):
    """Create a new Queue"""

    operation: Literal["create_queue"] = Field(
        default="create_queue",
        title="Create Queue",
        json_schema_extra={"x-creates-resource": True, "x-resource-type": "cloudflare_queue", "x-resource-id-path": "result.queue_id", 
            "x-category": "Queue",
            "x-is-trigger": False,
            "x-display-name": "Create Queue",
            "ui:hidden": True,
        },
    )
    queue_name: str = Field(description="The queue name")
    delivery_type: Optional[str] = Field(
        default=None,
        description="Delivery type. Use 'http_pull' to enable pull-based consumers via the Pull Queue Messages operation.",
        json_schema_extra={
            "enum": ["workers", "http_pull"],
            "enumNames": ["Workers (push to Worker)", "HTTP Pull (pull via API)"],
            "x-enum-searchable": True,
        },
    )


class CloudflareDeleteQueueConfig(BaseModel):
    """Delete a Queue"""

    operation: Literal["delete_queue"] = Field(
        default="delete_queue",
        title="Delete Queue",
        json_schema_extra={
            "x-category": "Queue",
            "x-is-trigger": False,
            "x-display-name": "Delete Queue",
            "ui:hidden": True,
        },
    )
    queue_id: str = Field(description="The queue ID to delete", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "queue_id",
            "placeholder": "Select a Queue...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareSendQueueMessageConfig(BaseModel):
    """Send a message to a Queue"""

    operation: Literal["send_queue_message"] = Field(
        default="send_queue_message",
        title="Send Queue Message",
        json_schema_extra={
            "x-category": "Queue",
            "x-is-trigger": False,
            "x-display-name": "Send Queue Message",
            "ui:hidden": True,
        },
    )
    queue_id: str = Field(description="The queue ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "queue_id",
            "placeholder": "Select a Queue...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    body: str = Field(description="Message body (string or JSON)")
    content_type: Optional[str] = Field(
        default="text",
        description="Message content type",
        json_schema_extra={
            "enum": ["text", "json", "bytes", "v8"],
            "x-enum-searchable": True,
        },
    )
    delay_seconds: Optional[int] = Field(
        default=None,
        description="Delay delivery by N seconds (0-43200)",
    )


class CloudflarePullQueueMessagesConfig(BaseModel):
    """Pull messages from a Queue"""

    operation: Literal["pull_queue_messages"] = Field(
        default="pull_queue_messages",
        title="Pull Queue Messages",
        json_schema_extra={
            "x-category": "Queue",
            "x-is-trigger": False,
            "x-display-name": "Pull Queue Messages",
            "ui:hidden": True,
        },
    )
    queue_id: str = Field(description="The queue ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "queue_id",
            "placeholder": "Select a Queue...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    batch_size: Optional[int] = Field(
        default=5,
        description="Number of messages to pull (1-100)",
    )
    visibility_timeout_ms: Optional[int] = Field(
        default=None,
        description="Visibility timeout in milliseconds",
    )


# ─── Workers AI Config Models ──────────────────────────────────────────────────


class CloudflareRunAIModelConfig(BaseModel):
    """Run inference with a Workers AI model"""

    operation: Literal["run_workers_ai_inference"] = Field(
        default="run_workers_ai_inference",
        title="Run Workers Ai Inference",
        json_schema_extra={
            "x-category": "Workers AI",
            "x-is-trigger": False,
            "x-display-name": "Run Workers Ai Inference",
            "ui:hidden": True,
        },
    )
    model_name: str = Field(
        description="Model identifier",
        json_schema_extra={
            "enum": [
                "@cf/meta/llama-3.1-8b-instruct",
                "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
                "@cf/mistral/mistral-7b-instruct-v0.1",
                "@cf/google/gemma-7b-it",
                "@cf/stabilityai/stable-diffusion-xl-base-1.0",
                "@cf/runwayml/stable-diffusion-v1-5-img2img",
                "@cf/openai/whisper",
                "@cf/meta/m2m100-1.2b",
                "@cf/baai/bge-base-en-v1.5",
                "@cf/baai/bge-large-en-v1.5",
                "@cf/cloudflare/radar-email-spam-detection-v0.1",
                "@cf/huggingface/distilbert-sst-2-int8",
            ],
            "x-enum-searchable": True,
            "x-dynamic-options": {
                "field_name": "workers_ai_model",
                "placeholder": "Select or search an AI model...",
                "searchable": True,
                "allow_custom": True,
            },
        },
    )
    input_data: str = Field(
        description='JSON input for the model. For text generation: {"messages": [{"role": "user", "content": "Hello"}]}',
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 4},
    )


class CloudflareListAIModelsConfig(BaseModel):
    """List available Workers AI models"""

    operation: Literal["list_workers_ai_models"] = Field(
        default="list_workers_ai_models",
        title="List Workers Ai Models",
        json_schema_extra={
            "x-category": "Workers AI",
            "x-is-trigger": False,
            "x-display-name": "List Workers Ai Models",
            "ui:hidden": True,
        },
    )
    search: Optional[str] = Field(
        default=None, description="Search models by name or description"
    )
    task: Optional[str] = Field(
        default=None,
        description="Filter by task type",
        json_schema_extra={
            "enum": [
                "Text Generation",
                "Text Embeddings",
                "Automatic Speech Recognition",
                "Image Classification",
                "Object Detection",
                "Image-to-Text",
                "Text-to-Image",
                "Translation",
                "Summarization",
            ],
            "x-enum-searchable": True,
        },
    )


# ─── Vectorize Config Models ───────────────────────────────────────────────────


class CloudflareListVectorizeIndexesConfig(BaseModel):
    """List all Vectorize indexes in an account"""

    operation: Literal["list_vectorize_indexes"] = Field(
        default="list_vectorize_indexes",
        title="List Vectorize Indexes",
        json_schema_extra={
            "x-category": "Vectorize",
            "x-is-trigger": False,
            "x-display-name": "List Vectorize Indexes",
            "ui:hidden": True,
        },
    )


class CloudflareGetVectorizeIndexConfig(BaseModel):
    """Get details for a Vectorize index"""

    operation: Literal["get_vectorize_index"] = Field(
        default="get_vectorize_index",
        title="Get Vectorize Index",
        json_schema_extra={
            "x-category": "Vectorize",
            "x-is-trigger": False,
            "x-display-name": "Get Vectorize Index",
            "ui:hidden": True,
        },
    )
    index_name: str = Field(description="The Vectorize index name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "index_name",
            "placeholder": "Select a Vectorize index...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareCreateVectorizeIndexConfig(BaseModel):
    """Create a new Vectorize index"""

    operation: Literal["create_vectorize_index"] = Field(
        default="create_vectorize_index",
        title="Create Vectorize Index",
        json_schema_extra={"x-creates-resource": True, "x-resource-type": "cloudflare_vectorize_index", "x-resource-id-path": "result.name", 
            "x-category": "Vectorize",
            "x-is-trigger": False,
            "x-display-name": "Create Vectorize Index",
            "ui:hidden": True,
        },
    )
    name: str = Field(description="Index name")
    dimensions: int = Field(description="Number of dimensions for vectors")
    metric: str = Field(
        description="Distance metric",
        json_schema_extra={
            "enum": ["cosine", "euclidean", "dot-product"],
            "x-enum-searchable": True,
        },
    )


class CloudflareDeleteVectorizeIndexConfig(BaseModel):
    """Delete a Vectorize index"""

    operation: Literal["delete_vectorize_index"] = Field(
        default="delete_vectorize_index",
        title="Delete Vectorize Index",
        json_schema_extra={
            "x-category": "Vectorize",
            "x-is-trigger": False,
            "x-display-name": "Delete Vectorize Index",
            "ui:hidden": True,
        },
    )
    index_name: str = Field(description="The Vectorize index name to delete", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "index_name",
            "placeholder": "Select a Vectorize index...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareUpsertVectorsConfig(BaseModel):
    """Upsert vectors into a Vectorize index"""

    operation: Literal["upsert_vectors_to_index"] = Field(
        default="upsert_vectors_to_index",
        title="Upsert Vectors to Index",
        json_schema_extra={
            "x-category": "Vectorize",
            "x-is-trigger": False,
            "x-display-name": "Upsert Vectors to Index",
            "ui:hidden": True,
        },
    )
    index_name: str = Field(description="The Vectorize index name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "index_name",
            "placeholder": "Select a Vectorize index...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    vectors: str = Field(
        description='JSON array of vectors. Example: [{"id": "vec1", "values": [0.1, 0.2, ...], "metadata": {"key": "value"}}]',
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 5},
    )


class CloudflareQueryVectorsConfig(BaseModel):
    """Query vectors from a Vectorize index"""

    operation: Literal["query_vectorize_index"] = Field(
        default="query_vectorize_index",
        title="Query Vectorize Index",
        json_schema_extra={
            "x-category": "Vectorize",
            "x-is-trigger": False,
            "x-display-name": "Query Vectorize Index",
            "ui:hidden": True,
        },
    )
    index_name: str = Field(description="The Vectorize index name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "index_name",
            "placeholder": "Select a Vectorize index...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    query_vector: str = Field(
        description="JSON array of floats representing the query vector (e.g., [0.1, 0.2, ...])",
    )
    top_k: Optional[int] = Field(
        default=5, description="Number of nearest neighbors to return"
    )
    return_values: Optional[str] = Field(
        default="false",
        description="Whether to return vector values",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    return_metadata: Optional[str] = Field(
        default="true",
        description="Whether to return vector metadata",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareDeleteVectorsConfig(BaseModel):
    """Delete vectors from a Vectorize index by ID"""

    operation: Literal["delete_vectors_from_index"] = Field(
        default="delete_vectors_from_index",
        title="Delete Vectors from Index",
        json_schema_extra={
            "x-category": "Vectorize",
            "x-is-trigger": False,
            "x-display-name": "Delete Vectors from Index",
            "ui:hidden": True,
        },
    )
    index_name: str = Field(description="The Vectorize index name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "index_name",
            "placeholder": "Select a Vectorize index...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    vector_ids: str = Field(
        description='Comma-separated list of vector IDs to delete (e.g., "vec1,vec2,vec3")',
    )


# ─── Load Balancing Config Models ──────────────────────────────────────────────


class CloudflareListLoadBalancersConfig(BaseModel):
    """List load balancers for a zone"""

    operation: Literal["list_load_balancers"] = Field(
        default="list_load_balancers",
        title="List Load Balancers",
        json_schema_extra={
            "x-category": "Load Balancer",
            "x-is-trigger": False,
            "x-display-name": "List Load Balancers",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareGetLoadBalancerConfig(BaseModel):
    """Get a specific load balancer"""

    operation: Literal["get_load_balancer"] = Field(
        default="get_load_balancer",
        title="Get Load Balancer",
        json_schema_extra={
            "x-category": "Load Balancer",
            "x-is-trigger": False,
            "x-display-name": "Get Load Balancer",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    lb_id: str = Field(description="The load balancer ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "lb_id",
            "placeholder": "Select a load balancer...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareCreateLoadBalancerConfig(BaseModel):
    """Create a new load balancer"""

    operation: Literal["create_load_balancer"] = Field(
        default="create_load_balancer",
        title="Create Load Balancer",
        json_schema_extra={"x-creates-resource": True, "x-resource-type": "cloudflare_load_balancer", "x-resource-id-path": "result.id", 
            "x-category": "Load Balancer",
            "x-is-trigger": False,
            "x-display-name": "Create Load Balancer",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    name: str = Field(description="Load balancer hostname")
    default_pools: str = Field(
        description='JSON array of pool IDs (e.g., ["pool_id1", "pool_id2"])',
    )
    fallback_pool: str = Field(description="Fallback pool ID")
    proxied: Optional[str] = Field(
        default="true",
        description="Whether to proxy through Cloudflare",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    ttl: Optional[int] = Field(default=30, description="DNS TTL (when not proxied)")


class CloudflareDeleteLoadBalancerConfig(BaseModel):
    """Delete a load balancer"""

    operation: Literal["delete_load_balancer"] = Field(
        default="delete_load_balancer",
        title="Delete Load Balancer",
        json_schema_extra={
            "x-category": "Load Balancer",
            "x-is-trigger": False,
            "x-display-name": "Delete Load Balancer",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    lb_id: str = Field(description="The load balancer ID to delete", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "lb_id",
            "placeholder": "Select a load balancer...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareListLBPoolsConfig(BaseModel):
    """List origin pools for load balancing"""

    operation: Literal["list_load_balancer_pools"] = Field(
        default="list_load_balancer_pools",
        title="List Load Balancer Pools",
        json_schema_extra={
            "x-category": "Load Balancer",
            "x-is-trigger": False,
            "x-display-name": "List Load Balancer Pools",
            "ui:hidden": True,
        },
    )


class CloudflareCreateLBPoolConfig(BaseModel):
    """Create a new origin pool for load balancing"""

    operation: Literal["create_load_balancer_pool"] = Field(
        default="create_load_balancer_pool",
        title="Create Load Balancer Pool",
        json_schema_extra={"x-creates-resource": True, "x-resource-type": "cloudflare_lb_pool", "x-resource-id-path": "result.id", 
            "x-category": "Load Balancer",
            "x-is-trigger": False,
            "x-display-name": "Create Load Balancer Pool",
            "ui:hidden": True,
        },
    )
    name: str = Field(description="Pool name")
    origins: str = Field(
        description='JSON array of origins. Example: [{"name": "web-1", "address": "1.2.3.4", "enabled": true}]',
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 4},
    )
    description: Optional[str] = Field(default=None, description="Pool description")
    enabled: Optional[str] = Field(
        default="true",
        description="Whether the pool is enabled",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


# ─── SSL / TLS Config Models ───────────────────────────────────────────────────


class CloudflareGetSSLSettingsConfig(BaseModel):
    """Get SSL/TLS settings for a zone"""

    operation: Literal["get_zone_ssl_settings"] = Field(
        default="get_zone_ssl_settings",
        title="Get Zone Ssl Settings",
        json_schema_extra={
            "x-category": "SSL",
            "x-is-trigger": False,
            "x-display-name": "Get Zone Ssl Settings",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareListSSLCertificatesConfig(BaseModel):
    """List SSL certificates for a zone"""

    operation: Literal["list_zone_ssl_certificates"] = Field(
        default="list_zone_ssl_certificates",
        title="List Zone Ssl Certificates",
        json_schema_extra={
            "x-category": "SSL",
            "x-is-trigger": False,
            "x-display-name": "List Zone Ssl Certificates",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


# ─── Analytics Config Models ───────────────────────────────────────────────────


class CloudflareGetZoneAnalyticsConfig(BaseModel):
    """Get analytics summary for a zone"""

    operation: Literal["get_zone_analytics"] = Field(
        default="get_zone_analytics",
        title="Get Zone Analytics",
        json_schema_extra={
            "x-category": "Zone",
            "x-is-trigger": False,
            "x-display-name": "Get Zone Analytics",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    since: Optional[str] = Field(
        default=None,
        description="Start date (ISO 8601, e.g., 2024-01-01T00:00:00Z)",
    )
    until: Optional[str] = Field(
        default=None,
        description="End date (ISO 8601, e.g., 2024-01-31T23:59:59Z)",
    )
    continuous: Optional[str] = Field(
        default="true",
        description="Whether to use continuous analytics",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )




class CloudflareListWorkerSecretsConfig(BaseModel):
    """List secrets for a Worker script"""
    operation: Literal["list_worker_secrets"] = Field(default="list_worker_secrets", title="List Worker Secrets", json_schema_extra={"x-category": "Workers", "x-is-trigger": False, "x-display-name": "List Worker Secrets", "ui:hidden": True})
    script_name: str = Field(description="The Worker script name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "worker_script_name",
            "placeholder": "Select a Worker script...",
            "searchable": True,
            "allow_custom": True,
        }
    })

class CloudflarePutWorkerSecretConfig(BaseModel):
    """Create or update a secret for a Worker script"""
    operation: Literal["put_worker_secret"] = Field(default="put_worker_secret", title="Put Worker Secret", json_schema_extra={"x-category": "Workers", "x-is-trigger": False, "x-display-name": "Put Worker Secret", "ui:hidden": True})
    script_name: str = Field(description="The Worker script name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "worker_script_name",
            "placeholder": "Select a Worker script...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    secret_name: str = Field(description="The secret binding name")
    secret_value: str = Field(description="The secret value", json_schema_extra={"ui:widget": "password"})
    secret_type: Optional[str] = Field(default="secret_text", description="The secret type", json_schema_extra={"enum": ["secret_text", "secret_key", "secret_json"], "x-enum-searchable": True})

class CloudflareDeleteWorkerSecretConfig(BaseModel):
    """Delete a secret from a Worker script"""
    operation: Literal["delete_worker_secret"] = Field(default="delete_worker_secret", title="Delete Worker Secret", json_schema_extra={"x-category": "Workers", "x-is-trigger": False, "x-display-name": "Delete Worker Secret", "ui:hidden": True})
    script_name: str = Field(description="The Worker script name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "worker_script_name",
            "placeholder": "Select a Worker script...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    secret_name: str = Field(description="The secret binding name to delete")

class CloudflareBulkUpsertWorkerSecretsConfig(BaseModel):
    """Bulk upsert secrets for a Worker script"""
    operation: Literal["bulk_upsert_worker_secrets"] = Field(default="bulk_upsert_worker_secrets", title="Bulk Upsert Worker Secrets", json_schema_extra={"x-category": "Workers", "x-is-trigger": False, "x-display-name": "Bulk Upsert Worker Secrets", "ui:hidden": True})
    script_name: str = Field(description="The Worker script name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "worker_script_name",
            "placeholder": "Select a Worker script...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    secrets_json: str = Field(description='JSON array of secret objects. Example: [{"name": "MY_SECRET", "text": "value", "type": "secret_text"}]', json_schema_extra={"ui:widget": "textarea", "ui:rows": 5})

class CloudflareGetWorkerCronTriggersConfig(BaseModel):
    """Get cron triggers (schedules) for a Worker script"""
    operation: Literal["get_worker_cron_triggers"] = Field(default="get_worker_cron_triggers", title="Get Worker Cron Triggers", json_schema_extra={"x-category": "Workers", "x-is-trigger": False, "x-display-name": "Get Worker Cron Triggers", "ui:hidden": True})
    script_name: str = Field(description="The Worker script name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "worker_script_name",
            "placeholder": "Select a Worker script...",
            "searchable": True,
            "allow_custom": True,
        }
    })

class CloudflareUpdateWorkerCronTriggersConfig(BaseModel):
    """Update cron triggers (schedules) for a Worker script"""
    operation: Literal["update_worker_cron_triggers"] = Field(default="update_worker_cron_triggers", title="Update Worker Cron Triggers", json_schema_extra={"x-category": "Workers", "x-is-trigger": False, "x-display-name": "Update Worker Cron Triggers", "ui:hidden": True})
    script_name: str = Field(description="The Worker script name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "worker_script_name",
            "placeholder": "Select a Worker script...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    crons: str = Field(description='JSON array of cron strings e.g. ["*/5 * * * *", "0 12 * * MON"]', json_schema_extra={"ui:widget": "textarea", "ui:rows": 3})

class CloudflareListDurableObjectNamespacesConfig(BaseModel):
    """List all Durable Object namespaces in an account"""
    operation: Literal["list_durable_object_namespaces"] = Field(default="list_durable_object_namespaces", title="List Durable Object Namespaces", json_schema_extra={"x-category": "Workers", "x-is-trigger": False, "x-display-name": "List Durable Object Namespaces", "ui:hidden": True})

class CloudflareListDurableObjectsConfig(BaseModel):
    """List Durable Objects in a namespace"""
    operation: Literal["list_durable_objects"] = Field(default="list_durable_objects", title="List Durable Objects", json_schema_extra={"x-category": "Workers", "x-is-trigger": False, "x-display-name": "List Durable Objects", "ui:hidden": True})
    namespace_id: str = Field(description="The Durable Object namespace ID")
    limit: Optional[int] = Field(default=100, description="Maximum number of objects to return")
    cursor: Optional[str] = Field(default=None, description="Pagination cursor from a previous response")

class CloudflareUpdateWorkerRouteConfig(BaseModel):
    """Update an existing Worker route"""
    operation: Literal["update_worker_route"] = Field(default="update_worker_route", title="Update Worker Route", json_schema_extra={"x-category": "Workers", "x-is-trigger": False, "x-display-name": "Update Worker Route", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    route_id: str = Field(description="The Worker route ID to update")
    pattern: Optional[str] = Field(default=None, description="URL pattern for the route (e.g., example.com/api/*)")
    script_name: Optional[str] = Field(default=None, description="Worker script name to associate with the route (leave empty to detach)")

class CloudflareListPipelinesConfig(BaseModel):
    """List all Workers Pipelines in an account"""
    operation: Literal["list_pipelines"] = Field(default="list_pipelines", title="List Pipelines", json_schema_extra={"x-category": "Pipelines", "x-is-trigger": False, "x-display-name": "List Pipelines", "ui:hidden": True})
    page: Optional[int] = Field(default=None, description="Page number")
    per_page: Optional[int] = Field(default=None, description="Number of results per page")

class CloudflareGetPipelineConfig(BaseModel):
    """Get a specific Workers Pipeline"""
    operation: Literal["get_pipeline"] = Field(default="get_pipeline", title="Get Pipeline", json_schema_extra={"x-category": "Pipelines", "x-is-trigger": False, "x-display-name": "Get Pipeline", "ui:hidden": True})
    pipeline_id: str = Field(description="The pipeline ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "pipeline_id",
            "placeholder": "Select a Pipeline...",
            "searchable": True,
            "allow_custom": True,
        }
    })

class CloudflareCreatePipelineConfig(BaseModel):
    """Create a new Workers Pipeline"""
    operation: Literal["create_pipeline"] = Field(default="create_pipeline", title="Create Pipeline", json_schema_extra={"x-creates-resource": True, "x-resource-type": "cloudflare_pipeline", "x-resource-id-path": "result.id", "x-category": "Pipelines", "x-is-trigger": False, "x-display-name": "Create Pipeline", "ui:hidden": True})
    pipeline_name: str = Field(description="Name for the new pipeline")
    source_type: Optional[str] = Field(default="http", description="Source type for the pipeline", json_schema_extra={"enum": ["http", "r2"], "x-enum-searchable": True})
    dest_type: Optional[str] = Field(default="r2", description="Destination type for the pipeline", json_schema_extra={"enum": ["r2", "d1"], "x-enum-searchable": True})
    config_json: Optional[str] = Field(default=None, description="JSON for full pipeline config (overrides other fields if provided)")

class CloudflareUpdatePipelineConfig(BaseModel):
    """Update an existing Workers Pipeline"""
    operation: Literal["update_pipeline"] = Field(default="update_pipeline", title="Update Pipeline", json_schema_extra={"x-category": "Pipelines", "x-is-trigger": False, "x-display-name": "Update Pipeline", "ui:hidden": True})
    pipeline_id: str = Field(description="The pipeline ID to update", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "pipeline_id",
            "placeholder": "Select a Pipeline...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    config_json: str = Field(description="JSON for full pipeline config")

class CloudflareDeletePipelineConfig(BaseModel):
    """Delete a Workers Pipeline"""
    operation: Literal["delete_pipeline"] = Field(default="delete_pipeline", title="Delete Pipeline", json_schema_extra={"x-category": "Pipelines", "x-is-trigger": False, "x-display-name": "Delete Pipeline", "ui:hidden": True})
    pipeline_id: str = Field(description="The pipeline ID to delete", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "pipeline_id",
            "placeholder": "Select a Pipeline...",
            "searchable": True,
            "allow_custom": True,
        }
    })


# ─── Secrets Store Config Models ───────────────────────────────────────────────


class CloudflareListSecretsStoresConfig(BaseModel):
    """List all Secrets Stores in an account"""
    operation: Literal["list_secrets_stores"] = Field(default="list_secrets_stores", title="List Secrets Stores", json_schema_extra={"x-category": "Secrets Store", "x-is-trigger": False, "x-display-name": "List Secrets Stores", "ui:hidden": True})
    page: Optional[int] = Field(default=None, description="Page number")
    per_page: Optional[int] = Field(default=None, description="Number of results per page")

class CloudflareCreateSecretsStoreConfig(BaseModel):
    """Create a new Secrets Store"""
    operation: Literal["create_secrets_store"] = Field(default="create_secrets_store", title="Create Secrets Store", json_schema_extra={"x-category": "Secrets Store", "x-is-trigger": False, "x-display-name": "Create Secrets Store", "ui:hidden": True})
    store_name: str = Field(description="Name for the new secrets store")

class CloudflareDeleteSecretsStoreConfig(BaseModel):
    """Delete a Secrets Store"""
    operation: Literal["delete_secrets_store"] = Field(default="delete_secrets_store", title="Delete Secrets Store", json_schema_extra={"x-category": "Secrets Store", "x-is-trigger": False, "x-display-name": "Delete Secrets Store", "ui:hidden": True})
    store_id: str = Field(description="The secrets store ID to delete", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "store_id",
            "placeholder": "Select a Secrets Store...",
            "searchable": True,
            "allow_custom": True,
        }
    })

class CloudflareListStoreSecretsConfig(BaseModel):
    """List all secrets in a Secrets Store"""
    operation: Literal["list_store_secrets"] = Field(default="list_store_secrets", title="List Store Secrets", json_schema_extra={"x-category": "Secrets Store", "x-is-trigger": False, "x-display-name": "List Store Secrets", "ui:hidden": True})
    store_id: str = Field(description="The secrets store ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "store_id",
            "placeholder": "Select a Secrets Store...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    page: Optional[int] = Field(default=None, description="Page number")
    per_page: Optional[int] = Field(default=None, description="Number of results per page")

class CloudflareGetStoreSecretConfig(BaseModel):
    """Get a specific secret from a Secrets Store"""
    operation: Literal["get_store_secret"] = Field(default="get_store_secret", title="Get Store Secret", json_schema_extra={"x-category": "Secrets Store", "x-is-trigger": False, "x-display-name": "Get Store Secret", "ui:hidden": True})
    store_id: str = Field(description="The secrets store ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "store_id",
            "placeholder": "Select a Secrets Store...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    secret_id: str = Field(description="The secret ID")

class CloudflareCreateStoreSecretConfig(BaseModel):
    """Create a new secret in a Secrets Store"""
    operation: Literal["create_store_secret"] = Field(default="create_store_secret", title="Create Store Secret", json_schema_extra={"x-category": "Secrets Store", "x-is-trigger": False, "x-display-name": "Create Store Secret", "ui:hidden": True})
    store_id: str = Field(description="The secrets store ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "store_id",
            "placeholder": "Select a Secrets Store...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    secret_name: str = Field(description="Name for the new secret")
    secret_value: str = Field(description="Value of the secret")
    secret_scopes: Optional[str] = Field(default=None, description="Comma-separated scopes e.g. workers.ai")

class CloudflareUpdateStoreSecretConfig(BaseModel):
    """Update an existing secret in a Secrets Store"""
    operation: Literal["update_store_secret"] = Field(default="update_store_secret", title="Update Store Secret", json_schema_extra={"x-category": "Secrets Store", "x-is-trigger": False, "x-display-name": "Update Store Secret", "ui:hidden": True})
    store_id: str = Field(description="The secrets store ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "store_id",
            "placeholder": "Select a Secrets Store...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    secret_id: str = Field(description="The secret ID to update")
    secret_value: Optional[str] = Field(default=None, description="New value for the secret")
    secret_scopes: Optional[str] = Field(default=None, description="Comma-separated scopes e.g. workers.ai")

class CloudflareDeleteStoreSecretConfig(BaseModel):
    """Delete a secret from a Secrets Store"""
    operation: Literal["delete_store_secret"] = Field(default="delete_store_secret", title="Delete Store Secret", json_schema_extra={"x-category": "Secrets Store", "x-is-trigger": False, "x-display-name": "Delete Store Secret", "ui:hidden": True})
    store_id: str = Field(description="The secrets store ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "store_id",
            "placeholder": "Select a Secrets Store...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    secret_id: str = Field(description="The secret ID to delete")


# ─── Rulesets Config Models ────────────────────────────────────────────────────

_RULESET_PHASE_ENUM = ["http_request_firewall_custom", "http_request_transform", "http_response_headers_transform", "http_request_cache_settings", "http_request_redirect", "http_ratelimit", "http_request_sbfm"]
_RULESET_PHASE_ENUM_NAMES = ["Firewall Custom Rules", "Transform Rules", "Response Header Transform", "Cache Settings Rules", "Redirect Rules", "Rate Limiting Rules", "Bot Management"]

class CloudflareListZoneRulesetsConfig(BaseModel):
    """List all rulesets for a zone"""
    operation: Literal["list_zone_rulesets"] = Field(default="list_zone_rulesets", title="List Zone Rulesets", json_schema_extra={"x-category": "Rulesets", "x-is-trigger": False, "x-display-name": "List Zone Rulesets", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })

class CloudflareGetZoneRulesetConfig(BaseModel):
    """Get a specific ruleset for a zone"""
    operation: Literal["get_zone_ruleset"] = Field(default="get_zone_ruleset", title="Get Zone Ruleset", json_schema_extra={"x-category": "Rulesets", "x-is-trigger": False, "x-display-name": "Get Zone Ruleset", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    ruleset_id: str = Field(description="The ruleset ID")

class CloudflareCreateZoneRulesetConfig(BaseModel):
    """Create a new ruleset for a zone"""
    operation: Literal["create_zone_ruleset"] = Field(default="create_zone_ruleset", title="Create Zone Ruleset", json_schema_extra={"x-category": "Rulesets", "x-is-trigger": False, "x-display-name": "Create Zone Ruleset", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    ruleset_name: str = Field(description="Name for the new ruleset")
    kind: str = Field(description="The kind of ruleset", json_schema_extra={"enum": ["root", "zone", "managed", "custom"], "x-enum-searchable": True})
    phase: str = Field(description="The phase the ruleset applies to", json_schema_extra={"enum": _RULESET_PHASE_ENUM, "enumNames": _RULESET_PHASE_ENUM_NAMES, "x-enum-searchable": True})
    description: Optional[str] = Field(default=None, description="Optional description for the ruleset")
    rules_json: Optional[str] = Field(default=None, description="JSON array of rule objects to include in the ruleset")

class CloudflareUpdateZoneRulesetConfig(BaseModel):
    """Update an existing zone ruleset"""
    operation: Literal["update_zone_ruleset"] = Field(default="update_zone_ruleset", title="Update Zone Ruleset", json_schema_extra={"x-category": "Rulesets", "x-is-trigger": False, "x-display-name": "Update Zone Ruleset", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    ruleset_id: str = Field(description="The ruleset ID to update")
    ruleset_name: Optional[str] = Field(default=None, description="New name for the ruleset")
    description: Optional[str] = Field(default=None, description="New description for the ruleset")
    rules_json: Optional[str] = Field(default=None, description="JSON array of rule objects to replace the ruleset rules")

class CloudflareDeleteZoneRulesetConfig(BaseModel):
    """Delete a zone ruleset"""
    operation: Literal["delete_zone_ruleset"] = Field(default="delete_zone_ruleset", title="Delete Zone Ruleset", json_schema_extra={"x-category": "Rulesets", "x-is-trigger": False, "x-display-name": "Delete Zone Ruleset", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    ruleset_id: str = Field(description="The ruleset ID to delete")

class CloudflareGetZoneRulesetPhaseConfig(BaseModel):
    """Get the entrypoint ruleset for a phase in a zone"""
    operation: Literal["get_zone_ruleset_phase"] = Field(default="get_zone_ruleset_phase", title="Get Zone Ruleset Phase", json_schema_extra={"x-category": "Rulesets", "x-is-trigger": False, "x-display-name": "Get Zone Ruleset Phase", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    phase: str = Field(description="The phase to retrieve the entrypoint ruleset for", json_schema_extra={"enum": _RULESET_PHASE_ENUM, "enumNames": _RULESET_PHASE_ENUM_NAMES, "x-enum-searchable": True})

class CloudflareUpdateZoneRulesetPhaseConfig(BaseModel):
    """Update the entrypoint ruleset for a phase in a zone"""
    operation: Literal["update_zone_ruleset_phase"] = Field(default="update_zone_ruleset_phase", title="Update Zone Ruleset Phase", json_schema_extra={"x-category": "Rulesets", "x-is-trigger": False, "x-display-name": "Update Zone Ruleset Phase", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    phase: str = Field(description="The phase whose entrypoint ruleset to update", json_schema_extra={"enum": _RULESET_PHASE_ENUM, "enumNames": _RULESET_PHASE_ENUM_NAMES, "x-enum-searchable": True})
    rules_json: str = Field(description="JSON array of ruleset rules to set for this phase entrypoint")

class CloudflareCreateZoneRulesetRuleConfig(BaseModel):
    """Create a rule inside a zone ruleset"""
    operation: Literal["create_zone_ruleset_rule"] = Field(default="create_zone_ruleset_rule", title="Create Zone Ruleset Rule", json_schema_extra={"x-category": "Rulesets", "x-is-trigger": False, "x-display-name": "Create Zone Ruleset Rule", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    ruleset_id: str = Field(description="The ruleset ID to add the rule to")
    action: str = Field(description="The action the rule performs when matched", json_schema_extra={"enum": ["block", "challenge", "js_challenge", "managed_challenge", "allow", "log", "rewrite", "redirect", "skip", "set_cache_settings", "score"], "x-enum-searchable": True})
    expression: str = Field(description="Wirefilter expression that defines when the rule matches")
    description: Optional[str] = Field(default=None, description="Optional description for the rule")
    enabled: Optional[str] = Field(default="true", description="Whether the rule is enabled", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})

class CloudflareDeleteZoneRulesetRuleConfig(BaseModel):
    """Delete a rule from a zone ruleset"""
    operation: Literal["delete_zone_ruleset_rule"] = Field(default="delete_zone_ruleset_rule", title="Delete Zone Ruleset Rule", json_schema_extra={"x-category": "Rulesets", "x-is-trigger": False, "x-display-name": "Delete Zone Ruleset Rule", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    ruleset_id: str = Field(description="The ruleset ID containing the rule")
    rule_id: str = Field(description="The rule ID to delete")

class CloudflareListAccountRulesetsConfig(BaseModel):
    """List all rulesets for the account"""
    operation: Literal["list_account_rulesets"] = Field(default="list_account_rulesets", title="List Account Rulesets", json_schema_extra={"x-category": "Rulesets", "x-is-trigger": False, "x-display-name": "List Account Rulesets", "ui:hidden": True})

class CloudflareGetAccountRulesetConfig(BaseModel):
    """Get a specific ruleset for the account"""
    operation: Literal["get_account_ruleset"] = Field(default="get_account_ruleset", title="Get Account Ruleset", json_schema_extra={"x-category": "Rulesets", "x-is-trigger": False, "x-display-name": "Get Account Ruleset", "ui:hidden": True})
    ruleset_id: str = Field(description="The ruleset ID")

class CloudflareListPageRulesConfig(BaseModel):
    """List all Page Rules for a zone"""
    operation: Literal["list_page_rules"] = Field(default="list_page_rules", title="List Page Rules", json_schema_extra={"x-category": "Page Rules", "x-is-trigger": False, "x-display-name": "List Page Rules", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    status: Optional[str] = Field(default=None, description="Filter by page rule status", json_schema_extra={"enum": ["active", "disabled"], "x-enum-searchable": True})

class CloudflareGetPageRuleConfig(BaseModel):
    """Get a specific Page Rule"""
    operation: Literal["get_page_rule"] = Field(default="get_page_rule", title="Get Page Rule", json_schema_extra={"x-category": "Page Rules", "x-is-trigger": False, "x-display-name": "Get Page Rule", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    pagerule_id: str = Field(description="The Page Rule ID")

class CloudflareCreatePageRuleConfig(BaseModel):
    """Create a new Page Rule for a zone"""
    operation: Literal["create_page_rule"] = Field(default="create_page_rule", title="Create Page Rule", json_schema_extra={"x-category": "Page Rules", "x-is-trigger": False, "x-display-name": "Create Page Rule", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    url_pattern: str = Field(description="URL pattern e.g. example.com/images/*")
    actions_json: str = Field(description='JSON array of action objects e.g. [{"id": "always_use_https"}]')
    status: Optional[str] = Field(default="active", description="Page rule status", json_schema_extra={"enum": ["active", "disabled"], "x-enum-searchable": True})
    priority: Optional[int] = Field(default=None, description="Priority of the page rule (higher number = higher priority)")

class CloudflareUpdatePageRuleConfig(BaseModel):
    """Update an existing Page Rule"""
    operation: Literal["update_page_rule"] = Field(default="update_page_rule", title="Update Page Rule", json_schema_extra={"x-category": "Page Rules", "x-is-trigger": False, "x-display-name": "Update Page Rule", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    pagerule_id: str = Field(description="The Page Rule ID to update")
    url_pattern: Optional[str] = Field(default=None, description="URL pattern e.g. example.com/images/*")
    actions_json: Optional[str] = Field(default=None, description='JSON array of action objects e.g. [{"id": "always_use_https"}]')
    status: Optional[str] = Field(default=None, description="Page rule status", json_schema_extra={"enum": ["active", "disabled"], "x-enum-searchable": True})
    priority: Optional[int] = Field(default=None, description="Priority of the page rule")

class CloudflareDeletePageRuleConfig(BaseModel):
    """Delete a Page Rule"""
    operation: Literal["delete_page_rule"] = Field(default="delete_page_rule", title="Delete Page Rule", json_schema_extra={"x-category": "Page Rules", "x-is-trigger": False, "x-display-name": "Delete Page Rule", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    pagerule_id: str = Field(description="The Page Rule ID to delete")

class CloudflareListRateLimitsConfig(BaseModel):
    """List Rate Limits for a zone"""
    operation: Literal["list_rate_limits"] = Field(default="list_rate_limits", title="List Rate Limits", json_schema_extra={"x-category": "Rate Limiting", "x-is-trigger": False, "x-display-name": "List Rate Limits", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    page: Optional[int] = Field(default=None, description="Page number of paginated results")
    per_page: Optional[int] = Field(default=20, description="Number of results per page")

class CloudflareGetRateLimitConfig(BaseModel):
    """Get a specific Rate Limit"""
    operation: Literal["get_rate_limit"] = Field(default="get_rate_limit", title="Get Rate Limit", json_schema_extra={"x-category": "Rate Limiting", "x-is-trigger": False, "x-display-name": "Get Rate Limit", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    rate_limit_id: str = Field(description="The Rate Limit ID")

class CloudflareCreateRateLimitConfig(BaseModel):
    """Create a new Rate Limit rule for a zone"""
    operation: Literal["create_rate_limit"] = Field(default="create_rate_limit", title="Create Rate Limit", json_schema_extra={"x-category": "Rate Limiting", "x-is-trigger": False, "x-display-name": "Create Rate Limit", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    url_pattern: str = Field(description="URL pattern to rate limit (e.g. example.com/api/*)")
    threshold: int = Field(description="Requests per period before the rule triggers")
    period: int = Field(description="Period in seconds (1-3600) over which requests are counted")
    action_mode: str = Field(description="Action to take when threshold is reached", json_schema_extra={"enum": ["simulate", "ban", "challenge", "js_challenge", "managed_challenge"], "x-enum-searchable": True})
    ban_duration: Optional[int] = Field(default=None, description="Seconds to ban the client (ban mode only)")
    request_methods: Optional[str] = Field(default=None, description="Comma-separated HTTP methods to match e.g. GET,POST (leave empty for all)")

class CloudflareUpdateRateLimitConfig(BaseModel):
    """Update an existing Rate Limit rule"""
    operation: Literal["update_rate_limit"] = Field(default="update_rate_limit", title="Update Rate Limit", json_schema_extra={"x-category": "Rate Limiting", "x-is-trigger": False, "x-display-name": "Update Rate Limit", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    rate_limit_id: str = Field(description="The Rate Limit ID to update")
    url_pattern: Optional[str] = Field(default=None, description="URL pattern to rate limit")
    threshold: Optional[int] = Field(default=None, description="Requests per period before the rule triggers")
    period: Optional[int] = Field(default=None, description="Period in seconds (1-3600) over which requests are counted")
    action_mode: Optional[str] = Field(default=None, description="Action to take when threshold is reached", json_schema_extra={"enum": ["simulate", "ban", "challenge", "js_challenge", "managed_challenge"], "x-enum-searchable": True})
    ban_duration: Optional[int] = Field(default=None, description="Seconds to ban the client (ban mode only)")

class CloudflareDeleteRateLimitConfig(BaseModel):
    """Delete a Rate Limit rule"""
    operation: Literal["delete_rate_limit"] = Field(default="delete_rate_limit", title="Delete Rate Limit", json_schema_extra={"x-category": "Rate Limiting", "x-is-trigger": False, "x-display-name": "Delete Rate Limit", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    rate_limit_id: str = Field(description="The Rate Limit ID to delete")


# ─── Custom Hostnames Config Models ───────────────────────────────────────────


class CloudflareListCustomHostnamesConfig(BaseModel):
    """List all custom hostnames for a zone"""
    operation: Literal["list_custom_hostnames"] = Field(default="list_custom_hostnames", title="List Custom Hostnames", json_schema_extra={"x-category": "Custom Hostnames", "x-is-trigger": False, "x-display-name": "List Custom Hostnames", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    hostname_filter: Optional[str] = Field(default=None, description="Filter by hostname")
    page: Optional[int] = Field(default=None, description="Page number")
    per_page: Optional[int] = Field(default=20, description="Results per page")

class CloudflareGetCustomHostnameConfig(BaseModel):
    """Get a specific custom hostname"""
    operation: Literal["get_custom_hostname"] = Field(default="get_custom_hostname", title="Get Custom Hostname", json_schema_extra={"x-category": "Custom Hostnames", "x-is-trigger": False, "x-display-name": "Get Custom Hostname", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    custom_hostname_id: str = Field(description="The custom hostname ID")

class CloudflareCreateCustomHostnameConfig(BaseModel):
    """Create a custom hostname for a zone"""
    operation: Literal["create_custom_hostname"] = Field(default="create_custom_hostname", title="Create Custom Hostname", json_schema_extra={"x-category": "Custom Hostnames", "x-is-trigger": False, "x-display-name": "Create Custom Hostname", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    hostname: str = Field(description="The custom hostname to add")
    ssl_method: Optional[str] = Field(default="http", description="SSL validation method", json_schema_extra={"enum": ["http", "txt", "email"], "x-enum-searchable": True})
    ssl_type: Optional[str] = Field(default="dv", description="SSL certificate type", json_schema_extra={"enum": ["dv"], "x-enum-searchable": True})
    custom_metadata_json: Optional[str] = Field(default=None, description="JSON object for custom metadata")

class CloudflareUpdateCustomHostnameConfig(BaseModel):
    """Update a custom hostname"""
    operation: Literal["update_custom_hostname"] = Field(default="update_custom_hostname", title="Update Custom Hostname", json_schema_extra={"x-category": "Custom Hostnames", "x-is-trigger": False, "x-display-name": "Update Custom Hostname", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    custom_hostname_id: str = Field(description="The custom hostname ID")
    ssl_method: Optional[str] = Field(default=None, description="SSL validation method", json_schema_extra={"enum": ["http", "txt", "email"], "x-enum-searchable": True})
    custom_metadata_json: Optional[str] = Field(default=None, description="JSON object for custom metadata")

class CloudflareDeleteCustomHostnameConfig(BaseModel):
    """Delete a custom hostname"""
    operation: Literal["delete_custom_hostname"] = Field(default="delete_custom_hostname", title="Delete Custom Hostname", json_schema_extra={"x-category": "Custom Hostnames", "x-is-trigger": False, "x-display-name": "Delete Custom Hostname", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    custom_hostname_id: str = Field(description="The custom hostname ID")


# ─── Waiting Rooms Config Models ──────────────────────────────────────────────


class CloudflareListWaitingRoomsConfig(BaseModel):
    """List all waiting rooms for a zone"""
    operation: Literal["list_waiting_rooms"] = Field(default="list_waiting_rooms", title="List Waiting Rooms", json_schema_extra={"x-category": "Waiting Rooms", "x-is-trigger": False, "x-display-name": "List Waiting Rooms", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    page: Optional[int] = Field(default=None, description="Page number")
    per_page: Optional[int] = Field(default=25, description="Results per page")

class CloudflareGetWaitingRoomConfig(BaseModel):
    """Get a specific waiting room"""
    operation: Literal["get_waiting_room"] = Field(default="get_waiting_room", title="Get Waiting Room", json_schema_extra={"x-category": "Waiting Rooms", "x-is-trigger": False, "x-display-name": "Get Waiting Room", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    waiting_room_id: str = Field(description="The waiting room ID")

class CloudflareCreateWaitingRoomConfig(BaseModel):
    """Create a waiting room for a zone"""
    operation: Literal["create_waiting_room"] = Field(default="create_waiting_room", title="Create Waiting Room", json_schema_extra={"x-category": "Waiting Rooms", "x-is-trigger": False, "x-display-name": "Create Waiting Room", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    name: str = Field(description="Name of the waiting room")
    host: str = Field(description="Hostname e.g. shop.example.com")
    path: Optional[str] = Field(default="/", description="Path the waiting room covers")
    total_active_users: int = Field(description="Max concurrent active users")
    new_users_per_minute: int = Field(description="Max new users per minute")
    session_duration: Optional[int] = Field(default=5, description="Session duration in minutes")
    queue_all: Optional[str] = Field(default="false", description="Queue all visitors regardless of capacity", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    custom_page_html: Optional[str] = Field(default=None, description="Custom HTML for waiting page")

class CloudflareUpdateWaitingRoomConfig(BaseModel):
    """Update a waiting room"""
    operation: Literal["update_waiting_room"] = Field(default="update_waiting_room", title="Update Waiting Room", json_schema_extra={"x-category": "Waiting Rooms", "x-is-trigger": False, "x-display-name": "Update Waiting Room", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    waiting_room_id: str = Field(description="The waiting room ID")
    name: Optional[str] = Field(default=None, description="Name of the waiting room")
    host: Optional[str] = Field(default=None, description="Hostname e.g. shop.example.com")
    path: Optional[str] = Field(default=None, description="Path the waiting room covers")
    total_active_users: Optional[int] = Field(default=None, description="Max concurrent active users")
    new_users_per_minute: Optional[int] = Field(default=None, description="Max new users per minute")
    session_duration: Optional[int] = Field(default=None, description="Session duration in minutes")
    queue_all: Optional[str] = Field(default=None, description="Queue all visitors regardless of capacity", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    custom_page_html: Optional[str] = Field(default=None, description="Custom HTML for waiting page")

class CloudflareDeleteWaitingRoomConfig(BaseModel):
    """Delete a waiting room"""
    operation: Literal["delete_waiting_room"] = Field(default="delete_waiting_room", title="Delete Waiting Room", json_schema_extra={"x-category": "Waiting Rooms", "x-is-trigger": False, "x-display-name": "Delete Waiting Room", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    waiting_room_id: str = Field(description="The waiting room ID")

class CloudflareGetWaitingRoomStatusConfig(BaseModel):
    """Get status of a waiting room"""
    operation: Literal["get_waiting_room_status"] = Field(default="get_waiting_room_status", title="Get Waiting Room Status", json_schema_extra={"x-category": "Waiting Rooms", "x-is-trigger": False, "x-display-name": "Get Waiting Room Status", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    waiting_room_id: str = Field(description="The waiting room ID")

class CloudflareListWaitingRoomEventsConfig(BaseModel):
    """List events for a waiting room"""
    operation: Literal["list_waiting_room_events"] = Field(default="list_waiting_room_events", title="List Waiting Room Events", json_schema_extra={"x-category": "Waiting Rooms", "x-is-trigger": False, "x-display-name": "List Waiting Room Events", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    waiting_room_id: str = Field(description="The waiting room ID")

class CloudflareCreateWaitingRoomEventConfig(BaseModel):
    """Create an event for a waiting room"""
    operation: Literal["create_waiting_room_event"] = Field(default="create_waiting_room_event", title="Create Waiting Room Event", json_schema_extra={"x-category": "Waiting Rooms", "x-is-trigger": False, "x-display-name": "Create Waiting Room Event", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    waiting_room_id: str = Field(description="The waiting room ID")
    event_name: str = Field(description="Name of the event")
    event_start_time: str = Field(description="Event start time in ISO 8601 format")
    event_end_time: str = Field(description="Event end time in ISO 8601 format")
    new_users_per_minute: Optional[int] = Field(default=None, description="Max new users per minute during event")
    total_active_users: Optional[int] = Field(default=None, description="Max concurrent active users during event")

class CloudflareListAccountLogpushJobsConfig(BaseModel):
    """List all Logpush jobs for an account"""
    operation: Literal["list_account_logpush_jobs"] = Field(default="list_account_logpush_jobs", title="List Account Logpush Jobs", json_schema_extra={"x-category": "Logpush", "x-is-trigger": False, "x-display-name": "List Account Logpush Jobs", "ui:hidden": True})

class CloudflareGetLogpushJobConfig(BaseModel):
    """Get a specific Logpush job"""
    operation: Literal["get_logpush_job"] = Field(default="get_logpush_job", title="Get Logpush Job", json_schema_extra={"x-category": "Logpush", "x-is-trigger": False, "x-display-name": "Get Logpush Job", "ui:hidden": True})
    job_id: str = Field(description="The Logpush job ID")

class CloudflareCreateLogpushJobConfig(BaseModel):
    """Create an account-level Logpush job"""
    operation: Literal["create_logpush_job"] = Field(default="create_logpush_job", title="Create Logpush Job", json_schema_extra={"x-category": "Logpush", "x-is-trigger": False, "x-display-name": "Create Logpush Job", "ui:hidden": True})
    job_name: str = Field(description="Name of the Logpush job")
    destination_conf: str = Field(description="Destination URL e.g. s3://bucket/prefix?region=us-east-1&access-key-id=...")
    dataset: str = Field(description="Dataset to push", json_schema_extra={"enum": ["http_requests", "firewall_events", "nel_reports", "network_analytics_logs", "dns_logs", "workers_trace_events", "gateway_http", "gateway_dns", "zero_trust_network_sessions"], "x-enum-searchable": True})
    logpull_options: Optional[str] = Field(default=None, description="Fields to include e.g. ClientIP,ClientRequestURI")
    frequency: Optional[str] = Field(default="high", description="Push frequency", json_schema_extra={"enum": ["high", "low"], "x-enum-searchable": True})
    enabled: Optional[str] = Field(default="true", description="Whether the job is enabled", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})

class CloudflareUpdateLogpushJobConfig(BaseModel):
    """Update an existing Logpush job"""
    operation: Literal["update_logpush_job"] = Field(default="update_logpush_job", title="Update Logpush Job", json_schema_extra={"x-category": "Logpush", "x-is-trigger": False, "x-display-name": "Update Logpush Job", "ui:hidden": True})
    job_id: str = Field(description="The Logpush job ID to update")
    destination_conf: Optional[str] = Field(default=None, description="Destination URL")
    enabled: Optional[str] = Field(default=None, description="Whether the job is enabled", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    frequency: Optional[str] = Field(default=None, description="Push frequency", json_schema_extra={"enum": ["high", "low"], "x-enum-searchable": True})
    logpull_options: Optional[str] = Field(default=None, description="Fields to include e.g. ClientIP,ClientRequestURI")

class CloudflareDeleteLogpushJobConfig(BaseModel):
    """Delete a Logpush job"""
    operation: Literal["delete_logpush_job"] = Field(default="delete_logpush_job", title="Delete Logpush Job", json_schema_extra={"x-category": "Logpush", "x-is-trigger": False, "x-display-name": "Delete Logpush Job", "ui:hidden": True})
    job_id: str = Field(description="The Logpush job ID to delete")

class CloudflareListZoneLogpushJobsConfig(BaseModel):
    """List all Logpush jobs for a zone"""
    operation: Literal["list_zone_logpush_jobs"] = Field(default="list_zone_logpush_jobs", title="List Zone Logpush Jobs", json_schema_extra={"x-category": "Logpush", "x-is-trigger": False, "x-display-name": "List Zone Logpush Jobs", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })

class CloudflareCreateZoneLogpushJobConfig(BaseModel):
    """Create a zone-level Logpush job"""
    operation: Literal["create_zone_logpush_job"] = Field(default="create_zone_logpush_job", title="Create Zone Logpush Job", json_schema_extra={"x-category": "Logpush", "x-is-trigger": False, "x-display-name": "Create Zone Logpush Job", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    job_name: str = Field(description="Name of the Logpush job")
    destination_conf: str = Field(description="Destination URL e.g. s3://bucket/prefix?region=us-east-1&access-key-id=...")
    dataset: str = Field(description="Dataset to push", json_schema_extra={"enum": ["http_requests", "firewall_events", "nel_reports", "network_analytics_logs", "dns_logs", "workers_trace_events", "gateway_http", "gateway_dns", "zero_trust_network_sessions"], "x-enum-searchable": True})
    logpull_options: Optional[str] = Field(default=None, description="Fields to include e.g. ClientIP,ClientRequestURI")
    enabled: Optional[str] = Field(default="true", description="Whether the job is enabled", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})

class CloudflareDeleteZoneLogpushJobConfig(BaseModel):
    """Delete a zone-level Logpush job"""
    operation: Literal["delete_zone_logpush_job"] = Field(default="delete_zone_logpush_job", title="Delete Zone Logpush Job", json_schema_extra={"x-category": "Logpush", "x-is-trigger": False, "x-display-name": "Delete Zone Logpush Job", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    job_id: str = Field(description="The Logpush job ID to delete")

class CloudflareListAuditLogsConfig(BaseModel):
    """List audit logs for an account"""
    operation: Literal["list_audit_logs"] = Field(default="list_audit_logs", title="List Audit Logs", json_schema_extra={"x-category": "Audit Logs", "x-is-trigger": False, "x-display-name": "List Audit Logs", "ui:hidden": True})
    since: Optional[str] = Field(default=None, description="ISO 8601 start time")
    before: Optional[str] = Field(default=None, description="ISO 8601 end time")
    action_type: Optional[str] = Field(default=None, description="Filter by action type e.g. add,delete")
    actor_email: Optional[str] = Field(default=None, description="Filter by actor email")
    zone_name: Optional[str] = Field(default=None, description="Filter by zone name")
    direction: Optional[str] = Field(default="desc", description="Sort direction", json_schema_extra={"enum": ["desc", "asc"], "x-enum-searchable": True})
    per_page: Optional[int] = Field(default=25, description="Number of results per page")

class CloudflareListAvailableAlertsConfig(BaseModel):
    """List all available alert types for an account"""
    operation: Literal["list_available_alerts"] = Field(default="list_available_alerts", title="List Available Alerts", json_schema_extra={"x-category": "Notifications", "x-is-trigger": False, "x-display-name": "List Available Alerts", "ui:hidden": True})

class CloudflareListAlertPoliciesConfig(BaseModel):
    """List all alert policies for an account"""
    operation: Literal["list_alert_policies"] = Field(default="list_alert_policies", title="List Alert Policies", json_schema_extra={"x-category": "Notifications", "x-is-trigger": False, "x-display-name": "List Alert Policies", "ui:hidden": True})

class CloudflareGetAlertPolicyConfig(BaseModel):
    """Get a specific alert policy"""
    operation: Literal["get_alert_policy"] = Field(default="get_alert_policy", title="Get Alert Policy", json_schema_extra={"x-category": "Notifications", "x-is-trigger": False, "x-display-name": "Get Alert Policy", "ui:hidden": True})
    policy_id: str = Field(description="The alert policy ID")

class CloudflareCreateAlertPolicyConfig(BaseModel):
    """Create a new alert policy"""
    operation: Literal["create_alert_policy"] = Field(default="create_alert_policy", title="Create Alert Policy", json_schema_extra={"x-category": "Notifications", "x-is-trigger": False, "x-display-name": "Create Alert Policy", "ui:hidden": True})
    policy_name: str = Field(description="Name for the alert policy")
    alert_type: str = Field(description="Alert type e.g. dos_attack_l7. Use list_available_alerts to see all types")
    enabled: Optional[str] = Field(default="true", description="Whether the policy is enabled", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    webhook_ids: Optional[str] = Field(default=None, description="Comma-separated notification webhook destination IDs")
    email_addresses: Optional[str] = Field(default=None, description="Comma-separated email addresses for alerts")
    filters_json: Optional[str] = Field(default=None, description="JSON object of alert-specific filters")

class CloudflareUpdateAlertPolicyConfig(BaseModel):
    """Update an existing alert policy"""
    operation: Literal["update_alert_policy"] = Field(default="update_alert_policy", title="Update Alert Policy", json_schema_extra={"x-category": "Notifications", "x-is-trigger": False, "x-display-name": "Update Alert Policy", "ui:hidden": True})
    policy_id: str = Field(description="The alert policy ID to update")
    policy_name: Optional[str] = Field(default=None, description="Name for the alert policy")
    alert_type: Optional[str] = Field(default=None, description="Alert type")
    enabled: Optional[str] = Field(default=None, description="Whether the policy is enabled", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    webhook_ids: Optional[str] = Field(default=None, description="Comma-separated notification webhook destination IDs")
    email_addresses: Optional[str] = Field(default=None, description="Comma-separated email addresses for alerts")
    filters_json: Optional[str] = Field(default=None, description="JSON object of alert-specific filters")

class CloudflareDeleteAlertPolicyConfig(BaseModel):
    """Delete an alert policy"""
    operation: Literal["delete_alert_policy"] = Field(default="delete_alert_policy", title="Delete Alert Policy", json_schema_extra={"x-category": "Notifications", "x-is-trigger": False, "x-display-name": "Delete Alert Policy", "ui:hidden": True})
    policy_id: str = Field(description="The alert policy ID to delete")

class CloudflareListNotificationWebhooksConfig(BaseModel):
    """List all notification webhook destinations for an account"""
    operation: Literal["list_notification_webhooks"] = Field(default="list_notification_webhooks", title="List Notification Webhooks", json_schema_extra={"x-category": "Notifications", "x-is-trigger": False, "x-display-name": "List Notification Webhooks", "ui:hidden": True})

class CloudflareCreateNotificationWebhookConfig(BaseModel):
    """Create a new notification webhook destination"""
    operation: Literal["create_notification_webhook"] = Field(default="create_notification_webhook", title="Create Notification Webhook", json_schema_extra={"x-category": "Notifications", "x-is-trigger": False, "x-display-name": "Create Notification Webhook", "ui:hidden": True})
    webhook_name: str = Field(description="Name for the webhook destination")
    webhook_url: str = Field(description="HTTPS URL to send notifications to")
    webhook_secret: Optional[str] = Field(default=None, description="Optional HMAC secret for signature verification", json_schema_extra={"ui:widget": "password"})

class CloudflareUpdateNotificationWebhookConfig(BaseModel):
    """Update an existing notification webhook destination"""
    operation: Literal["update_notification_webhook"] = Field(default="update_notification_webhook", title="Update Notification Webhook", json_schema_extra={"x-category": "Notifications", "x-is-trigger": False, "x-display-name": "Update Notification Webhook", "ui:hidden": True})
    webhook_id: str = Field(description="The webhook destination ID to update")
    webhook_name: Optional[str] = Field(default=None, description="Name for the webhook destination")
    webhook_url: Optional[str] = Field(default=None, description="HTTPS URL to send notifications to")
    webhook_secret: Optional[str] = Field(default=None, description="Optional HMAC secret for signature verification", json_schema_extra={"ui:widget": "password"})

class CloudflareDeleteNotificationWebhookConfig(BaseModel):
    """Delete a notification webhook destination"""
    operation: Literal["delete_notification_webhook"] = Field(default="delete_notification_webhook", title="Delete Notification Webhook", json_schema_extra={"x-category": "Notifications", "x-is-trigger": False, "x-display-name": "Delete Notification Webhook", "ui:hidden": True})
    webhook_id: str = Field(description="The webhook destination ID to delete")

class CloudflareGetNotificationHistoryConfig(BaseModel):
    """Get notification delivery history for an account"""
    operation: Literal["get_notification_history"] = Field(default="get_notification_history", title="Get Notification History", json_schema_extra={"x-category": "Notifications", "x-is-trigger": False, "x-display-name": "Get Notification History", "ui:hidden": True})
    since: Optional[str] = Field(default=None, description="Filter history from this datetime (ISO 8601)")
    before: Optional[str] = Field(default=None, description="Filter history before this datetime (ISO 8601)")
    per_page: Optional[int] = Field(default=25, description="Number of results per page (default 25)")


# ─── Health Checks Config Models ──────────────────────────────────────────────


class CloudflareListHealthChecksConfig(BaseModel):
    """List all Health Checks for a zone"""
    operation: Literal["list_health_checks"] = Field(default="list_health_checks", title="List Health Checks", json_schema_extra={"x-category": "Health Checks", "x-is-trigger": False, "x-display-name": "List Health Checks", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })

class CloudflareGetHealthCheckConfig(BaseModel):
    """Get a specific Health Check"""
    operation: Literal["get_health_check"] = Field(default="get_health_check", title="Get Health Check", json_schema_extra={"x-category": "Health Checks", "x-is-trigger": False, "x-display-name": "Get Health Check", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    healthcheck_id: str = Field(description="The Health Check ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "health_check_id",
            "placeholder": "Select a health check...",
            "searchable": True,
            "allow_custom": True,
        }
    })

class CloudflareCreateHealthCheckConfig(BaseModel):
    """Create a new Health Check"""
    operation: Literal["create_health_check"] = Field(default="create_health_check", title="Create Health Check", json_schema_extra={"x-creates-resource": True, "x-resource-type": "cloudflare_health_check", "x-resource-id-path": "result.id", "x-category": "Health Checks", "x-is-trigger": False, "x-display-name": "Create Health Check", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    check_name: str = Field(description="Name of the health check")
    address: str = Field(description="Hostname or IP of target")
    check_type: str = Field(description="Type of health check", json_schema_extra={"enum": ["HTTP", "HTTPS", "TCP"], "x-enum-searchable": True})
    path: Optional[str] = Field(default="/", description="URL path for HTTP/HTTPS checks")
    port: Optional[int] = Field(default=None, description="Port number to connect to")
    method: Optional[str] = Field(default="GET", description="HTTP method for HTTP/HTTPS checks", json_schema_extra={"enum": ["GET", "HEAD"], "x-enum-searchable": True})
    expected_codes: Optional[str] = Field(default="2xx", description="Expected HTTP response codes")
    check_regions: Optional[str] = Field(default=None, description="Comma-separated list of regions to run health checks from")
    interval: Optional[int] = Field(default=60, description="Check interval seconds")
    retries: Optional[int] = Field(default=2, description="Number of retries before marking unhealthy")
    timeout: Optional[int] = Field(default=5, description="Seconds before timeout")
    description: Optional[str] = Field(default=None, description="Description of the health check")

class CloudflareUpdateHealthCheckConfig(BaseModel):
    """Update an existing Health Check"""
    operation: Literal["update_health_check"] = Field(default="update_health_check", title="Update Health Check", json_schema_extra={"x-category": "Health Checks", "x-is-trigger": False, "x-display-name": "Update Health Check", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    healthcheck_id: str = Field(description="The Health Check ID to update", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "health_check_id",
            "placeholder": "Select a health check...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    check_name: Optional[str] = Field(default=None, description="Name of the health check")
    address: Optional[str] = Field(default=None, description="Hostname or IP of target")
    check_type: Optional[str] = Field(default=None, description="Type of health check", json_schema_extra={"enum": ["HTTP", "HTTPS", "TCP"], "x-enum-searchable": True})
    path: Optional[str] = Field(default=None, description="URL path for HTTP/HTTPS checks")
    port: Optional[int] = Field(default=None, description="Port number to connect to")
    method: Optional[str] = Field(default=None, description="HTTP method for HTTP/HTTPS checks", json_schema_extra={"enum": ["GET", "HEAD"], "x-enum-searchable": True})
    expected_codes: Optional[str] = Field(default=None, description="Expected HTTP response codes")
    interval: Optional[int] = Field(default=None, description="Check interval seconds")
    retries: Optional[int] = Field(default=None, description="Number of retries before marking unhealthy")
    timeout: Optional[int] = Field(default=None, description="Seconds before timeout")

class CloudflareDeleteHealthCheckConfig(BaseModel):
    """Delete a Health Check"""
    operation: Literal["delete_health_check"] = Field(default="delete_health_check", title="Delete Health Check", json_schema_extra={"x-category": "Health Checks", "x-is-trigger": False, "x-display-name": "Delete Health Check", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    healthcheck_id: str = Field(description="The Health Check ID to delete", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "health_check_id",
            "placeholder": "Select a health check...",
            "searchable": True,
            "allow_custom": True,
        }
    })


# ─── Spectrum Applications Config Models ──────────────────────────────────────


class CloudflareListSpectrumAppsConfig(BaseModel):
    """List all Spectrum applications for a zone"""
    operation: Literal["list_spectrum_apps"] = Field(default="list_spectrum_apps", title="List Spectrum Apps", json_schema_extra={"x-category": "Spectrum", "x-is-trigger": False, "x-display-name": "List Spectrum Apps", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    page: Optional[int] = Field(default=None, description="Page number")
    per_page: Optional[int] = Field(default=20, description="Results per page")

class CloudflareGetSpectrumAppConfig(BaseModel):
    """Get a specific Spectrum application"""
    operation: Literal["get_spectrum_app"] = Field(default="get_spectrum_app", title="Get Spectrum App", json_schema_extra={"x-category": "Spectrum", "x-is-trigger": False, "x-display-name": "Get Spectrum App", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    app_id: str = Field(description="The Spectrum application ID")

class CloudflareCreateSpectrumAppConfig(BaseModel):
    """Create a new Spectrum application"""
    operation: Literal["create_spectrum_app"] = Field(default="create_spectrum_app", title="Create Spectrum App", json_schema_extra={"x-category": "Spectrum", "x-is-trigger": False, "x-display-name": "Create Spectrum App", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    protocol: str = Field(description="Protocol e.g. tcp/22, http/80")
    dns_name: str = Field(description="Spectrum app hostname")
    origin_direct: Optional[str] = Field(default=None, description="Origin address e.g. tcp://1.2.3.4:22")
    origin_dns_name: Optional[str] = Field(default=None, description="Origin DNS hostname")
    origin_port: Optional[int] = Field(default=None, description="Origin port number")
    ip_firewall: Optional[str] = Field(default=None, description="Enable IP firewall for the application", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    tls: Optional[str] = Field(default="off", description="TLS mode for the application", json_schema_extra={"enum": ["off", "flexible", "full", "strict"], "x-enum-searchable": True})

class CloudflareUpdateSpectrumAppConfig(BaseModel):
    """Update an existing Spectrum application"""
    operation: Literal["update_spectrum_app"] = Field(default="update_spectrum_app", title="Update Spectrum App", json_schema_extra={"x-category": "Spectrum", "x-is-trigger": False, "x-display-name": "Update Spectrum App", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    app_id: str = Field(description="The Spectrum application ID to update")
    protocol: Optional[str] = Field(default=None, description="Protocol e.g. tcp/22, http/80")
    dns_name: Optional[str] = Field(default=None, description="Spectrum app hostname")
    origin_direct: Optional[str] = Field(default=None, description="Origin address e.g. tcp://1.2.3.4:22")
    origin_port: Optional[int] = Field(default=None, description="Origin port number")
    ip_firewall: Optional[str] = Field(default=None, description="Enable IP firewall for the application", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    tls: Optional[str] = Field(default=None, description="TLS mode for the application", json_schema_extra={"enum": ["off", "flexible", "full", "strict"], "x-enum-searchable": True})

class CloudflareDeleteSpectrumAppConfig(BaseModel):
    """Delete a Spectrum application"""
    operation: Literal["delete_spectrum_app"] = Field(default="delete_spectrum_app", title="Delete Spectrum App", json_schema_extra={"x-category": "Spectrum", "x-is-trigger": False, "x-display-name": "Delete Spectrum App", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    app_id: str = Field(description="The Spectrum application ID to delete")


# ─── Snippets Config Models ────────────────────────────────────────────────────


class CloudflareListSnippetsConfig(BaseModel):
    """List all Snippets for a zone"""
    operation: Literal["list_snippets"] = Field(default="list_snippets", title="List Snippets", json_schema_extra={"x-category": "Snippets", "x-is-trigger": False, "x-display-name": "List Snippets", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })

class CloudflareGetSnippetConfig(BaseModel):
    """Get a specific Snippet"""
    operation: Literal["get_snippet"] = Field(default="get_snippet", title="Get Snippet", json_schema_extra={"x-category": "Snippets", "x-is-trigger": False, "x-display-name": "Get Snippet", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    snippet_name: str = Field(description="The snippet name")

class CloudflarePutSnippetConfig(BaseModel):
    """Create or update a Snippet"""
    operation: Literal["put_snippet"] = Field(default="put_snippet", title="Put Snippet", json_schema_extra={"x-category": "Snippets", "x-is-trigger": False, "x-display-name": "Put Snippet", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    snippet_name: str = Field(description="The snippet name")
    snippet_code: str = Field(description="JavaScript code for the snippet")

class CloudflareDeleteSnippetConfig(BaseModel):
    """Delete a Snippet"""
    operation: Literal["delete_snippet"] = Field(default="delete_snippet", title="Delete Snippet", json_schema_extra={"x-category": "Snippets", "x-is-trigger": False, "x-display-name": "Delete Snippet", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    snippet_name: str = Field(description="The snippet name to delete")

class CloudflareListSnippetRulesConfig(BaseModel):
    """List all Snippet rules for a zone"""
    operation: Literal["list_snippet_rules"] = Field(default="list_snippet_rules", title="List Snippet Rules", json_schema_extra={"x-category": "Snippets", "x-is-trigger": False, "x-display-name": "List Snippet Rules", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


# ─── Zaraz Config Models ───────────────────────────────────────────────────────


class CloudflareGetZarazConfigConfig(BaseModel):
    """Get the Zaraz configuration for a zone"""
    operation: Literal["get_zaraz_config"] = Field(default="get_zaraz_config", title="Get Zaraz Config", json_schema_extra={"x-category": "Zaraz", "x-is-trigger": False, "x-display-name": "Get Zaraz Config", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })

class CloudflareUpdateZarazConfigConfig(BaseModel):
    """Update the Zaraz configuration for a zone"""
    operation: Literal["update_zaraz_config"] = Field(default="update_zaraz_config", title="Update Zaraz Config", json_schema_extra={"x-category": "Zaraz", "x-is-trigger": False, "x-display-name": "Update Zaraz Config", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    config_json: str = Field(description="Zaraz configuration as JSON object. Get current config first with get_zaraz_config.")

class CloudflarePublishZarazConfigConfig(BaseModel):
    """Publish the Zaraz configuration for a zone"""
    operation: Literal["publish_zaraz_config"] = Field(default="publish_zaraz_config", title="Publish Zaraz Config", json_schema_extra={"x-category": "Zaraz", "x-is-trigger": False, "x-display-name": "Publish Zaraz Config", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    description: Optional[str] = Field(default=None, description="Description of this publish")


# ─── Bot Management Config Models ─────────────────────────────────────────────


class CloudflareGetBotManagementConfig(BaseModel):
    """Get Bot Management settings for a zone"""
    operation: Literal["get_bot_management"] = Field(default="get_bot_management", title="Get Bot Management", json_schema_extra={"x-category": "Bot Management", "x-is-trigger": False, "x-display-name": "Get Bot Management", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })

class CloudflareUpdateBotManagementConfig(BaseModel):
    """Update Bot Management settings for a zone"""
    operation: Literal["update_bot_management"] = Field(default="update_bot_management", title="Update Bot Management", json_schema_extra={"x-category": "Bot Management", "x-is-trigger": False, "x-display-name": "Update Bot Management", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    enable_js: Optional[str] = Field(default=None, description="Enable JS injection for bot detection", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    fight_mode: Optional[str] = Field(default=None, description="Enable Bot Fight Mode (blocks bad bots)", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    suppress_session_score: Optional[str] = Field(default=None, description="Suppress session score from being included in the response", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    auto_update_model: Optional[str] = Field(default=None, description="Automatically update the bot detection model", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})


# ─── Speed Observatory Config Models ──────────────────────────────────────────


class CloudflareListObservatoryPagesConfig(BaseModel):
    """List pages tracked in the Speed Observatory for a zone"""
    operation: Literal["list_observatory_pages"] = Field(default="list_observatory_pages", title="List Observatory Pages", json_schema_extra={"x-category": "Speed", "x-is-trigger": False, "x-display-name": "List Observatory Pages", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    region: Optional[str] = Field(default="us-central1", description="Test region e.g. us-central1, eu-west-1")

class CloudflareListPageSpeedTestsConfig(BaseModel):
    """List speed tests for a specific page"""
    operation: Literal["list_page_speed_tests"] = Field(default="list_page_speed_tests", title="List Page Speed Tests", json_schema_extra={"x-category": "Speed", "x-is-trigger": False, "x-display-name": "List Page Speed Tests", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    page_url: str = Field(description="URL path to test e.g. /blog")
    region: Optional[str] = Field(default="us-central1", description="Test region e.g. us-central1, eu-west-1")
    per_page: Optional[int] = Field(default=20, description="Number of results per page")

class CloudflareCreatePageSpeedTestConfig(BaseModel):
    """Create a new speed test for a page"""
    operation: Literal["create_page_speed_test"] = Field(default="create_page_speed_test", title="Create Page Speed Test", json_schema_extra={"x-category": "Speed", "x-is-trigger": False, "x-display-name": "Create Page Speed Test", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    page_url: str = Field(description="URL path to test e.g. /blog")
    region: Optional[str] = Field(default="us-central1", description="Test region e.g. us-central1, eu-west-1")

class CloudflareDeletePageSpeedTestsConfig(BaseModel):
    """Delete all speed tests for a page"""
    operation: Literal["delete_page_speed_tests"] = Field(default="delete_page_speed_tests", title="Delete Page Speed Tests", json_schema_extra={"x-category": "Speed", "x-is-trigger": False, "x-display-name": "Delete Page Speed Tests", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    page_url: str = Field(description="URL path to delete tests for e.g. /blog")
    region: Optional[str] = Field(default="us-central1", description="Test region e.g. us-central1, eu-west-1")

class CloudflareGetSpeedTestScheduleConfig(BaseModel):
    """Get the scheduled speed test for a page"""
    operation: Literal["get_speed_test_schedule"] = Field(default="get_speed_test_schedule", title="Get Speed Test Schedule", json_schema_extra={"x-category": "Speed", "x-is-trigger": False, "x-display-name": "Get Speed Test Schedule", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    page_url: str = Field(description="URL path to check schedule for e.g. /blog")
    region: Optional[str] = Field(default="us-central1", description="Test region e.g. us-central1, eu-west-1")


# ─── Web Analytics / RUM Config Models ────────────────────────────────────────


class CloudflareListWebAnalyticsSitesConfig(BaseModel):
    """List all Web Analytics sites in an account"""
    operation: Literal["list_web_analytics_sites"] = Field(default="list_web_analytics_sites", title="List Web Analytics Sites", json_schema_extra={"x-category": "Web Analytics", "x-is-trigger": False, "x-display-name": "List Web Analytics Sites", "ui:hidden": True})
    per_page: Optional[int] = Field(default=25, description="Number of results per page")
    page: Optional[int] = Field(default=1, description="Page number")

class CloudflareCreateWebAnalyticsSiteConfig(BaseModel):
    """Create a new Web Analytics site"""
    operation: Literal["create_web_analytics_site"] = Field(default="create_web_analytics_site", title="Create Web Analytics Site", json_schema_extra={"x-category": "Web Analytics", "x-is-trigger": False, "x-display-name": "Create Web Analytics Site", "ui:hidden": True})
    host: str = Field(description="Hostname to track e.g. example.com")
    zone_tag: Optional[str] = Field(default=None, description="Zone ID to auto-install beacon")
    auto_install: Optional[str] = Field(default="false", description="Automatically install the beacon script on the zone", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})

class CloudflareGetWebAnalyticsSiteConfig(BaseModel):
    """Get a specific Web Analytics site"""
    operation: Literal["get_web_analytics_site"] = Field(default="get_web_analytics_site", title="Get Web Analytics Site", json_schema_extra={"x-category": "Web Analytics", "x-is-trigger": False, "x-display-name": "Get Web Analytics Site", "ui:hidden": True})
    site_id: str = Field(description="The Web Analytics site ID")

class CloudflareDeleteWebAnalyticsSiteConfig(BaseModel):
    """Delete a Web Analytics site"""
    operation: Literal["delete_web_analytics_site"] = Field(default="delete_web_analytics_site", title="Delete Web Analytics Site", json_schema_extra={"x-category": "Web Analytics", "x-is-trigger": False, "x-display-name": "Delete Web Analytics Site", "ui:hidden": True})
    site_id: str = Field(description="The Web Analytics site ID to delete")



# ─── Account Members Config Models ────────────────────────────────────────────


class CloudflareListAccountMembersConfig(BaseModel):
    """List all members of an account"""
    operation: Literal["list_account_members"] = Field(default="list_account_members", title="List Account Members", json_schema_extra={"x-category": "Account", "x-is-trigger": False, "x-display-name": "List Account Members", "ui:hidden": True})
    page: Optional[int] = Field(default=None, description="Page number of results")
    per_page: Optional[int] = Field(default=20, description="Number of results per page")
    status: Optional[str] = Field(default=None, description="Filter by membership status", json_schema_extra={"enum": ["accepted", "pending", "rejected"], "x-enum-searchable": True})

class CloudflareGetAccountMemberConfig(BaseModel):
    """Get a specific account member"""
    operation: Literal["get_account_member"] = Field(default="get_account_member", title="Get Account Member", json_schema_extra={"x-category": "Account", "x-is-trigger": False, "x-display-name": "Get Account Member", "ui:hidden": True})
    member_id: str = Field(description="The member ID")

class CloudflareAddAccountMemberConfig(BaseModel):
    """Add a member to an account"""
    operation: Literal["add_account_member"] = Field(default="add_account_member", title="Add Account Member", json_schema_extra={"x-category": "Account", "x-is-trigger": False, "x-display-name": "Add Account Member", "ui:hidden": True})
    email: str = Field(description="Email address of the user to add")
    role_ids: str = Field(description="Comma-separated role IDs to assign to the member")
    status: Optional[str] = Field(default="pending", description="Initial membership status", json_schema_extra={"enum": ["accepted", "pending"], "x-enum-searchable": True})

class CloudflareUpdateAccountMemberConfig(BaseModel):
    """Update an account member's roles"""
    operation: Literal["update_account_member"] = Field(default="update_account_member", title="Update Account Member", json_schema_extra={"x-category": "Account", "x-is-trigger": False, "x-display-name": "Update Account Member", "ui:hidden": True})
    member_id: str = Field(description="The member ID to update")
    role_ids: str = Field(description="Comma-separated role IDs to assign to the member")

class CloudflareRemoveAccountMemberConfig(BaseModel):
    """Remove a member from an account"""
    operation: Literal["remove_account_member"] = Field(default="remove_account_member", title="Remove Account Member", json_schema_extra={"x-category": "Account", "x-is-trigger": False, "x-display-name": "Remove Account Member", "ui:hidden": True})
    member_id: str = Field(description="The member ID to remove")

class CloudflareListAccountRolesConfig(BaseModel):
    """List all roles available for an account"""
    operation: Literal["list_account_roles"] = Field(default="list_account_roles", title="List Account Roles", json_schema_extra={"x-category": "Account", "x-is-trigger": False, "x-display-name": "List Account Roles", "ui:hidden": True})


# ─── Zero Trust - Tunnel Routes / Virtual Networks Config Models ───────────────


class CloudflareListTunnelRoutesConfig(BaseModel):
    """List all tunnel routes in an account"""
    operation: Literal["list_tunnel_routes"] = Field(default="list_tunnel_routes", title="List Tunnel Routes", json_schema_extra={"x-category": "Zero Trust", "x-is-trigger": False, "x-display-name": "List Tunnel Routes", "ui:hidden": True})
    tunnel_id: Optional[str] = Field(default=None, description="Filter by tunnel ID")
    virtual_network_id: Optional[str] = Field(default=None, description="Filter by virtual network ID")
    per_page: Optional[int] = Field(default=25, description="Number of results per page")

class CloudflareCreateTunnelRouteConfig(BaseModel):
    """Create a new tunnel route"""
    operation: Literal["create_tunnel_route"] = Field(default="create_tunnel_route", title="Create Tunnel Route", json_schema_extra={"x-category": "Zero Trust", "x-is-trigger": False, "x-display-name": "Create Tunnel Route", "ui:hidden": True})
    network_cidr: str = Field(description="CIDR notation e.g. 10.0.0.0/8")
    tunnel_id: str = Field(description="The tunnel ID to route traffic through", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "tunnel_id",
            "placeholder": "Select a tunnel...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    virtual_network_id: Optional[str] = Field(default=None, description="Virtual network ID to associate with the route")
    comment: Optional[str] = Field(default=None, description="Optional comment for the route")

class CloudflareUpdateTunnelRouteConfig(BaseModel):
    """Update an existing tunnel route"""
    operation: Literal["update_tunnel_route"] = Field(default="update_tunnel_route", title="Update Tunnel Route", json_schema_extra={"x-category": "Zero Trust", "x-is-trigger": False, "x-display-name": "Update Tunnel Route", "ui:hidden": True})
    network_cidr: str = Field(description="CIDR to update e.g. 10.0.0.0/8")
    tunnel_id: Optional[str] = Field(default=None, description="New tunnel ID to route traffic through")
    virtual_network_id: Optional[str] = Field(default=None, description="New virtual network ID")
    comment: Optional[str] = Field(default=None, description="Updated comment for the route")

class CloudflareDeleteTunnelRouteConfig(BaseModel):
    """Delete a tunnel route"""
    operation: Literal["delete_tunnel_route"] = Field(default="delete_tunnel_route", title="Delete Tunnel Route", json_schema_extra={"x-category": "Zero Trust", "x-is-trigger": False, "x-display-name": "Delete Tunnel Route", "ui:hidden": True})
    network_cidr: str = Field(description="CIDR notation of the route to delete e.g. 10.0.0.0/8")

class CloudflareListVirtualNetworksConfig(BaseModel):
    """List all virtual networks in an account"""
    operation: Literal["list_virtual_networks"] = Field(default="list_virtual_networks", title="List Virtual Networks", json_schema_extra={"x-category": "Zero Trust", "x-is-trigger": False, "x-display-name": "List Virtual Networks", "ui:hidden": True})
    is_default_network: Optional[str] = Field(default=None, description="Filter by whether this is the default network", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})

class CloudflareCreateVirtualNetworkConfig(BaseModel):
    """Create a new virtual network"""
    operation: Literal["create_virtual_network"] = Field(default="create_virtual_network", title="Create Virtual Network", json_schema_extra={"x-category": "Zero Trust", "x-is-trigger": False, "x-display-name": "Create Virtual Network", "ui:hidden": True})
    vnet_name: str = Field(description="Name for the virtual network")
    is_default_network: Optional[str] = Field(default="false", description="Whether this should be the default virtual network", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    comment: Optional[str] = Field(default=None, description="Optional comment for the virtual network")

class CloudflareGetVirtualNetworkConfig(BaseModel):
    """Get a specific virtual network"""
    operation: Literal["get_virtual_network"] = Field(default="get_virtual_network", title="Get Virtual Network", json_schema_extra={"x-category": "Zero Trust", "x-is-trigger": False, "x-display-name": "Get Virtual Network", "ui:hidden": True})
    virtual_network_id: str = Field(description="The virtual network ID")

class CloudflareUpdateVirtualNetworkConfig(BaseModel):
    """Update an existing virtual network"""
    operation: Literal["update_virtual_network"] = Field(default="update_virtual_network", title="Update Virtual Network", json_schema_extra={"x-category": "Zero Trust", "x-is-trigger": False, "x-display-name": "Update Virtual Network", "ui:hidden": True})
    virtual_network_id: str = Field(description="The virtual network ID to update")
    vnet_name: Optional[str] = Field(default=None, description="New name for the virtual network")
    is_default_network: Optional[str] = Field(default=None, description="Whether this should be the default virtual network", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    comment: Optional[str] = Field(default=None, description="Updated comment for the virtual network")

class CloudflareDeleteVirtualNetworkConfig(BaseModel):
    """Delete a virtual network"""
    operation: Literal["delete_virtual_network"] = Field(default="delete_virtual_network", title="Delete Virtual Network", json_schema_extra={"x-category": "Zero Trust", "x-is-trigger": False, "x-display-name": "Delete Virtual Network", "ui:hidden": True})
    virtual_network_id: str = Field(description="The virtual network ID to delete")


# ─── Load Balancer Extensions Config Models ───────────────────────────────────


class CloudflareUpdateLoadBalancerConfig(BaseModel):
    """Update an existing load balancer"""
    operation: Literal["update_load_balancer"] = Field(default="update_load_balancer", title="Update Load Balancer", json_schema_extra={"x-category": "Load Balancer", "x-is-trigger": False, "x-display-name": "Update Load Balancer", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    lb_id: str = Field(description="The load balancer ID to update", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "lb_id",
            "placeholder": "Select a load balancer...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    lb_name: Optional[str] = Field(default=None, description="Load balancer hostname")
    fallback_pool: Optional[str] = Field(default=None, description="ID of fallback pool")
    default_pools: Optional[str] = Field(default=None, description="Comma-separated ordered pool IDs")
    proxied: Optional[str] = Field(default=None, description="Whether to proxy through Cloudflare", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    session_affinity: Optional[str] = Field(default="none", description="Session affinity type", json_schema_extra={"enum": ["none", "cookie", "ip_cookie", "ip-cookie"], "x-enum-searchable": True})
    ttl: Optional[int] = Field(default=None, description="DNS TTL for proxied:false LBs")
    description: Optional[str] = Field(default=None, description="Load balancer description")

class CloudflareGetLBPoolConfig(BaseModel):
    """Get a specific load balancer origin pool"""
    operation: Literal["get_load_balancer_pool"] = Field(default="get_load_balancer_pool", title="Get Load Balancer Pool", json_schema_extra={"x-category": "Load Balancer", "x-is-trigger": False, "x-display-name": "Get Load Balancer Pool", "ui:hidden": True})
    pool_id: str = Field(description="The pool ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "pool_id",
            "placeholder": "Select a load balancer pool...",
            "searchable": True,
            "allow_custom": True,
        }
    })

class CloudflareUpdateLBPoolConfig(BaseModel):
    """Update an existing load balancer origin pool"""
    operation: Literal["update_load_balancer_pool"] = Field(default="update_load_balancer_pool", title="Update Load Balancer Pool", json_schema_extra={"x-category": "Load Balancer", "x-is-trigger": False, "x-display-name": "Update Load Balancer Pool", "ui:hidden": True})
    pool_id: str = Field(description="The pool ID to update", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "pool_id",
            "placeholder": "Select a load balancer pool...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    pool_name: Optional[str] = Field(default=None, description="Pool name")
    origins_json: Optional[str] = Field(default=None, description='JSON array of origin objects {name, address, enabled?, weight?}', json_schema_extra={"ui:widget": "textarea", "ui:rows": 4})
    monitor: Optional[str] = Field(default=None, description="Monitor ID")
    description: Optional[str] = Field(default=None, description="Pool description")
    enabled: Optional[str] = Field(default=None, description="Whether the pool is enabled", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})
    minimum_origins: Optional[int] = Field(default=None, description="Minimum origins before pool is unhealthy")
    notification_email: Optional[str] = Field(default=None, description="Email for pool status notifications")

class CloudflareDeleteLBPoolConfig(BaseModel):
    """Delete a load balancer origin pool"""
    operation: Literal["delete_load_balancer_pool"] = Field(default="delete_load_balancer_pool", title="Delete Load Balancer Pool", json_schema_extra={"x-category": "Load Balancer", "x-is-trigger": False, "x-display-name": "Delete Load Balancer Pool", "ui:hidden": True})
    pool_id: str = Field(description="The pool ID to delete", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "pool_id",
            "placeholder": "Select a load balancer pool...",
            "searchable": True,
            "allow_custom": True,
        }
    })

class CloudflareListLBMonitorsConfig(BaseModel):
    """List all load balancer monitors in an account"""
    operation: Literal["list_load_balancer_monitors"] = Field(default="list_load_balancer_monitors", title="List Load Balancer Monitors", json_schema_extra={"x-category": "Load Balancer", "x-is-trigger": False, "x-display-name": "List Load Balancer Monitors", "ui:hidden": True})

class CloudflareGetLBMonitorConfig(BaseModel):
    """Get a specific load balancer monitor"""
    operation: Literal["get_load_balancer_monitor"] = Field(default="get_load_balancer_monitor", title="Get Load Balancer Monitor", json_schema_extra={"x-category": "Load Balancer", "x-is-trigger": False, "x-display-name": "Get Load Balancer Monitor", "ui:hidden": True})
    monitor_id: str = Field(description="The monitor ID")

class CloudflareCreateLBMonitorConfig(BaseModel):
    """Create a new load balancer monitor"""
    operation: Literal["create_load_balancer_monitor"] = Field(default="create_load_balancer_monitor", title="Create Load Balancer Monitor", json_schema_extra={"x-category": "Load Balancer", "x-is-trigger": False, "x-display-name": "Create Load Balancer Monitor", "ui:hidden": True})
    monitor_type: str = Field(default="http", description="Protocol type for the monitor", json_schema_extra={"enum": ["http", "https", "tcp", "udp_icmp", "icmp_ping", "smtp"], "x-enum-searchable": True})
    expected_codes: Optional[str] = Field(default="2xx", description="Expected HTTP response codes (e.g. 2xx, 200)")
    method: Optional[str] = Field(default="GET", description="HTTP method for the health check", json_schema_extra={"enum": ["GET", "HEAD"], "x-enum-searchable": True})
    path: Optional[str] = Field(default="/", description="Path to probe for HTTP/HTTPS monitors")
    timeout: Optional[int] = Field(default=5, description="Probe timeout in seconds")
    interval: Optional[int] = Field(default=60, description="Interval between probes in seconds")
    retries: Optional[int] = Field(default=2, description="Number of retries before marking unhealthy")
    description: Optional[str] = Field(default=None, description="Monitor description")
    port: Optional[int] = Field(default=None, description="Port to connect to for the probe")

class CloudflareDeleteLBMonitorConfig(BaseModel):
    """Delete a load balancer monitor"""
    operation: Literal["delete_load_balancer_monitor"] = Field(default="delete_load_balancer_monitor", title="Delete Load Balancer Monitor", json_schema_extra={"x-category": "Load Balancer", "x-is-trigger": False, "x-display-name": "Delete Load Balancer Monitor", "ui:hidden": True})
    monitor_id: str = Field(description="The monitor ID to delete")

class CloudflareGetLBPoolHealthConfig(BaseModel):
    """Get health status of a load balancer origin pool"""
    operation: Literal["get_load_balancer_pool_health"] = Field(default="get_load_balancer_pool_health", title="Get Load Balancer Pool Health", json_schema_extra={"x-category": "Load Balancer", "x-is-trigger": False, "x-display-name": "Get Load Balancer Pool Health", "ui:hidden": True})
    pool_id: str = Field(description="The pool ID to check health for", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "pool_id",
            "placeholder": "Select a load balancer pool...",
            "searchable": True,
            "allow_custom": True,
        }
    })


# ─── Access Extensions Config Models ──────────────────────────────────────────


class CloudflareCreateAccessPolicyConfig(BaseModel):
    """Create a policy for an Access application"""
    operation: Literal["create_access_policy"] = Field(default="create_access_policy", title="Create Access Policy", json_schema_extra={"x-category": "Access", "x-is-trigger": False, "x-display-name": "Create Access Policy", "ui:hidden": True})
    app_id: str = Field(description="The Access application UUID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "access_app_id",
            "placeholder": "Select an Access application...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    policy_name: str = Field(description="Name of the policy")
    decision: str = Field(description="Policy decision action", json_schema_extra={"enum": ["allow", "deny", "non_identity", "bypass"], "x-enum-searchable": True})
    include_json: str = Field(description='JSON array of include rules e.g. [{"email": {"email": "user@example.com"}}]')
    exclude_json: Optional[str] = Field(default=None, description="JSON array of exclude rules")
    require_json: Optional[str] = Field(default=None, description="JSON array of require rules")
    precedence: Optional[int] = Field(default=None, description="Policy precedence order")
    session_duration: Optional[str] = Field(default=None, description="Session duration e.g. 24h")

class CloudflareUpdateAccessPolicyConfig(BaseModel):
    """Update a policy for an Access application"""
    operation: Literal["update_access_policy"] = Field(default="update_access_policy", title="Update Access Policy", json_schema_extra={"x-category": "Access", "x-is-trigger": False, "x-display-name": "Update Access Policy", "ui:hidden": True})
    app_id: str = Field(description="The Access application UUID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "access_app_id",
            "placeholder": "Select an Access application...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    policy_id: str = Field(description="The Access policy UUID")
    policy_name: Optional[str] = Field(default=None, description="Name of the policy")
    decision: Optional[str] = Field(default=None, description="Policy decision action", json_schema_extra={"enum": ["allow", "deny", "non_identity", "bypass"], "x-enum-searchable": True})
    include_json: Optional[str] = Field(default=None, description='JSON array of include rules')
    exclude_json: Optional[str] = Field(default=None, description="JSON array of exclude rules")
    require_json: Optional[str] = Field(default=None, description="JSON array of require rules")
    precedence: Optional[int] = Field(default=None, description="Policy precedence order")

class CloudflareDeleteAccessPolicyConfig(BaseModel):
    """Delete a policy from an Access application"""
    operation: Literal["delete_access_policy"] = Field(default="delete_access_policy", title="Delete Access Policy", json_schema_extra={"x-category": "Access", "x-is-trigger": False, "x-display-name": "Delete Access Policy", "ui:hidden": True})
    app_id: str = Field(description="The Access application UUID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "access_app_id",
            "placeholder": "Select an Access application...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    policy_id: str = Field(description="The Access policy UUID to delete")

class CloudflareGetAccessPolicyConfig(BaseModel):
    """Get a specific Access policy"""
    operation: Literal["get_access_policy"] = Field(default="get_access_policy", title="Get Access Policy", json_schema_extra={"x-category": "Access", "x-is-trigger": False, "x-display-name": "Get Access Policy", "ui:hidden": True})
    app_id: str = Field(description="The Access application UUID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "access_app_id",
            "placeholder": "Select an Access application...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    policy_id: str = Field(description="The Access policy UUID")

class CloudflareListAccessGroupsConfig(BaseModel):
    """List all Access groups in an account"""
    operation: Literal["list_access_groups"] = Field(default="list_access_groups", title="List Access Groups", json_schema_extra={"x-category": "Access", "x-is-trigger": False, "x-display-name": "List Access Groups", "ui:hidden": True})
    page: Optional[int] = Field(default=None, description="Page number")
    per_page: Optional[int] = Field(default=25, description="Results per page")

class CloudflareGetAccessGroupConfig(BaseModel):
    """Get a specific Access group"""
    operation: Literal["get_access_group"] = Field(default="get_access_group", title="Get Access Group", json_schema_extra={"x-category": "Access", "x-is-trigger": False, "x-display-name": "Get Access Group", "ui:hidden": True})
    group_id: str = Field(description="The Access group UUID")

class CloudflareCreateAccessGroupConfig(BaseModel):
    """Create an Access group"""
    operation: Literal["create_access_group"] = Field(default="create_access_group", title="Create Access Group", json_schema_extra={"x-category": "Access", "x-is-trigger": False, "x-display-name": "Create Access Group", "ui:hidden": True})
    group_name: str = Field(description="Name of the Access group")
    include_json: str = Field(description='JSON array of include rules e.g. [{"email": {"email": "user@example.com"}}]')
    exclude_json: Optional[str] = Field(default=None, description="JSON array of exclude rules")
    require_json: Optional[str] = Field(default=None, description="JSON array of require rules")

class CloudflareUpdateAccessGroupConfig(BaseModel):
    """Update an Access group"""
    operation: Literal["update_access_group"] = Field(default="update_access_group", title="Update Access Group", json_schema_extra={"x-category": "Access", "x-is-trigger": False, "x-display-name": "Update Access Group", "ui:hidden": True})
    group_id: str = Field(description="The Access group UUID")
    group_name: Optional[str] = Field(default=None, description="Name of the Access group")
    include_json: Optional[str] = Field(default=None, description='JSON array of include rules')
    exclude_json: Optional[str] = Field(default=None, description="JSON array of exclude rules")
    require_json: Optional[str] = Field(default=None, description="JSON array of require rules")

class CloudflareDeleteAccessGroupConfig(BaseModel):
    """Delete an Access group"""
    operation: Literal["delete_access_group"] = Field(default="delete_access_group", title="Delete Access Group", json_schema_extra={"x-category": "Access", "x-is-trigger": False, "x-display-name": "Delete Access Group", "ui:hidden": True})
    group_id: str = Field(description="The Access group UUID to delete")

class CloudflareListAccessServiceTokensConfig(BaseModel):
    """List all Access service tokens in an account"""
    operation: Literal["list_access_service_tokens"] = Field(default="list_access_service_tokens", title="List Access Service Tokens", json_schema_extra={"x-category": "Access", "x-is-trigger": False, "x-display-name": "List Access Service Tokens", "ui:hidden": True})

class CloudflareCreateAccessServiceTokenConfig(BaseModel):
    """Create an Access service token"""
    operation: Literal["create_access_service_token"] = Field(default="create_access_service_token", title="Create Access Service Token", json_schema_extra={"x-category": "Access", "x-is-trigger": False, "x-display-name": "Create Access Service Token", "ui:hidden": True})
    token_name: str = Field(description="Name for the service token")
    duration: Optional[str] = Field(default=None, description="Token lifetime e.g. 8760h for 1 year")

class CloudflareRefreshAccessServiceTokenConfig(BaseModel):
    """Refresh an Access service token"""
    operation: Literal["refresh_access_service_token"] = Field(default="refresh_access_service_token", title="Refresh Access Service Token", json_schema_extra={"x-category": "Access", "x-is-trigger": False, "x-display-name": "Refresh Access Service Token", "ui:hidden": True})
    token_id: str = Field(description="The Access service token UUID to refresh")

class CloudflareDeleteAccessServiceTokenConfig(BaseModel):
    """Delete an Access service token"""
    operation: Literal["delete_access_service_token"] = Field(default="delete_access_service_token", title="Delete Access Service Token", json_schema_extra={"x-category": "Access", "x-is-trigger": False, "x-display-name": "Delete Access Service Token", "ui:hidden": True})
    token_id: str = Field(description="The Access service token UUID to delete")


# ─── Tunnel Extensions Config Models ──────────────────────────────────────────


class CloudflareUpdateTunnelConfig(BaseModel):
    """Update a Cloudflare Tunnel"""
    operation: Literal["update_tunnel"] = Field(default="update_tunnel", title="Update Tunnel", json_schema_extra={"x-category": "Tunnel", "x-is-trigger": False, "x-display-name": "Update Tunnel", "ui:hidden": True})
    tunnel_id: str = Field(description="The tunnel UUID to update", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "tunnel_id",
            "placeholder": "Select a tunnel...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    tunnel_name: Optional[str] = Field(default=None, description="New name for tunnel")
    tunnel_secret: Optional[str] = Field(default=None, description="New 32-byte base64 secret")

class CloudflareGetTunnelConfigurationConfig(BaseModel):
    """Get the configuration for a Cloudflare Tunnel"""
    operation: Literal["get_tunnel_configuration"] = Field(default="get_tunnel_configuration", title="Get Tunnel Configuration", json_schema_extra={"x-category": "Tunnel", "x-is-trigger": False, "x-display-name": "Get Tunnel Configuration", "ui:hidden": True})
    tunnel_id: str = Field(description="The tunnel UUID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "tunnel_id",
            "placeholder": "Select a tunnel...",
            "searchable": True,
            "allow_custom": True,
        }
    })

class CloudflarePutTunnelConfigurationConfig(BaseModel):
    """Set the ingress configuration for a Cloudflare Tunnel"""
    operation: Literal["put_tunnel_configuration"] = Field(default="put_tunnel_configuration", title="Put Tunnel Configuration", json_schema_extra={"x-category": "Tunnel", "x-is-trigger": False, "x-display-name": "Put Tunnel Configuration", "ui:hidden": True})
    tunnel_id: str = Field(description="The tunnel UUID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "tunnel_id",
            "placeholder": "Select a tunnel...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    ingress_json: str = Field(description='JSON array of ingress rules e.g. [{"hostname": "app.example.com", "service": "http://localhost:8080"}]', json_schema_extra={"ui:widget": "textarea", "ui:rows": 4})
    warp_routing_enabled: Optional[str] = Field(default="false", description="Enable WARP routing", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})

class CloudflareListTunnelConnectionsConfig(BaseModel):
    """List active connections for a Cloudflare Tunnel"""
    operation: Literal["list_tunnel_connections"] = Field(default="list_tunnel_connections", title="List Tunnel Connections", json_schema_extra={"x-category": "Tunnel", "x-is-trigger": False, "x-display-name": "List Tunnel Connections", "ui:hidden": True})
    tunnel_id: str = Field(description="The tunnel UUID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "tunnel_id",
            "placeholder": "Select a tunnel...",
            "searchable": True,
            "allow_custom": True,
        }
    })


# ─── Email Routing Extensions Config Models ───────────────────────────────────


class CloudflareEnableEmailRoutingConfig(BaseModel):
    """Enable Email Routing for a zone"""
    operation: Literal["enable_email_routing"] = Field(default="enable_email_routing", title="Enable Email Routing", json_schema_extra={"x-category": "Email Routing", "x-is-trigger": False, "x-display-name": "Enable Email Routing", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })

class CloudflareDisableEmailRoutingConfig(BaseModel):
    """Disable Email Routing for a zone"""
    operation: Literal["disable_email_routing"] = Field(default="disable_email_routing", title="Disable Email Routing", json_schema_extra={"x-category": "Email Routing", "x-is-trigger": False, "x-display-name": "Disable Email Routing", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })

class CloudflareCreateEmailRoutingDestinationConfig(BaseModel):
    """Create a destination email address for Email Routing (triggers verification email)"""
    operation: Literal["create_email_routing_destination"] = Field(default="create_email_routing_destination", title="Create Email Routing Destination", json_schema_extra={"x-category": "Email Routing", "x-is-trigger": False, "x-display-name": "Create Email Routing Destination", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    destination_email: str = Field(description="Email address to verify as destination")

class CloudflareDeleteEmailRoutingDestinationConfig(BaseModel):
    """Delete a destination email address from Email Routing"""
    operation: Literal["delete_email_routing_destination"] = Field(default="delete_email_routing_destination", title="Delete Email Routing Destination", json_schema_extra={"x-category": "Email Routing", "x-is-trigger": False, "x-display-name": "Delete Email Routing Destination", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    address_id: str = Field(description="The destination address ID to delete")


# ─── Queue Extensions Config Models ───────────────────────────────────────────


class CloudflareUpdateQueueConfig(BaseModel):
    """Update a Queue's name"""
    operation: Literal["update_queue"] = Field(default="update_queue", title="Update Queue", json_schema_extra={"x-category": "Queue", "x-is-trigger": False, "x-display-name": "Update Queue", "ui:hidden": True})
    queue_id: str = Field(description="The queue ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "queue_id",
            "placeholder": "Select a Queue...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    new_queue_name: str = Field(description="New name for the queue")

class CloudflareAcknowledgeQueueMessagesConfig(BaseModel):
    """Acknowledge or retry pulled Queue messages"""
    operation: Literal["acknowledge_queue_messages"] = Field(default="acknowledge_queue_messages", title="Acknowledge Queue Messages", json_schema_extra={"x-category": "Queue", "x-is-trigger": False, "x-display-name": "Acknowledge Queue Messages", "ui:hidden": True})
    queue_id: str = Field(description="The queue ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "queue_id",
            "placeholder": "Select a Queue...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    lease_ids: str = Field(description="Comma-separated lease IDs from pulled messages to acknowledge")
    retry_lease_ids: Optional[str] = Field(default=None, description="Comma-separated lease IDs to return for retry")
    retry_delay_seconds: Optional[int] = Field(default=None, description="Delay in seconds before retry messages become visible")

class CloudflareListQueueConsumersConfig(BaseModel):
    """List consumers for a Queue"""
    operation: Literal["list_queue_consumers"] = Field(default="list_queue_consumers", title="List Queue Consumers", json_schema_extra={"x-category": "Queue", "x-is-trigger": False, "x-display-name": "List Queue Consumers", "ui:hidden": True})
    queue_id: str = Field(description="The queue ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "queue_id",
            "placeholder": "Select a Queue...",
            "searchable": True,
            "allow_custom": True,
        }
    })

class CloudflareCreateQueueConsumerConfig(BaseModel):
    """Create a Worker consumer for a Queue"""
    operation: Literal["create_queue_consumer"] = Field(default="create_queue_consumer", title="Create Queue Consumer", json_schema_extra={"x-category": "Queue", "x-is-trigger": False, "x-display-name": "Create Queue Consumer", "ui:hidden": True})
    queue_id: str = Field(description="The queue ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "queue_id",
            "placeholder": "Select a Queue...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    script_name: str = Field(description="Worker script to consume messages", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "worker_script_name",
            "placeholder": "Select a Worker script...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    batch_size: Optional[int] = Field(default=10, description="Number of messages per batch")
    max_retries: Optional[int] = Field(default=3, description="Maximum retry attempts per message")
    max_wait_time_ms: Optional[int] = Field(default=5000, description="Max wait milliseconds before delivering a partial batch")

class CloudflareDeleteQueueConsumerConfig(BaseModel):
    """Delete a consumer from a Queue"""
    operation: Literal["delete_queue_consumer"] = Field(default="delete_queue_consumer", title="Delete Queue Consumer", json_schema_extra={"x-category": "Queue", "x-is-trigger": False, "x-display-name": "Delete Queue Consumer", "ui:hidden": True})
    queue_id: str = Field(description="The queue ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "queue_id",
            "placeholder": "Select a Queue...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    consumer_name: str = Field(description="The consumer (Worker script) name to remove")


# ─── SSL / TLS Extensions Config Models ───────────────────────────────────────


class CloudflareUpdateZoneSSLSettingsConfig(BaseModel):
    """Update the SSL/TLS mode for a zone"""
    operation: Literal["update_zone_ssl_settings"] = Field(default="update_zone_ssl_settings", title="Update Zone Ssl Settings", json_schema_extra={"x-category": "SSL / TLS", "x-is-trigger": False, "x-display-name": "Update Zone Ssl Settings", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    ssl_mode: str = Field(description="SSL/TLS encryption mode", json_schema_extra={"enum": ["off", "flexible", "full", "strict"], "x-enum-searchable": True})

class CloudflareUploadSSLCertificateConfig(BaseModel):
    """Upload a custom SSL certificate for a zone"""
    operation: Literal["upload_ssl_certificate"] = Field(default="upload_ssl_certificate", title="Upload Ssl Certificate", json_schema_extra={"x-category": "SSL / TLS", "x-is-trigger": False, "x-display-name": "Upload Ssl Certificate", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    certificate: str = Field(description="PEM-encoded certificate", json_schema_extra={"ui:widget": "textarea", "ui:rows": 6})
    private_key: str = Field(description="PEM-encoded private key", json_schema_extra={"ui:widget": "password"})
    bundle_method: Optional[str] = Field(default="ubiquitous", description="Certificate bundle method", json_schema_extra={"enum": ["ubiquitous", "optimal", "force"], "x-enum-searchable": True})

class CloudflareDeleteSSLCertificateConfig(BaseModel):
    """Delete a custom SSL certificate from a zone"""
    operation: Literal["delete_ssl_certificate"] = Field(default="delete_ssl_certificate", title="Delete Ssl Certificate", json_schema_extra={"x-category": "SSL / TLS", "x-is-trigger": False, "x-display-name": "Delete Ssl Certificate", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    certificate_id: str = Field(description="The custom certificate ID to delete")


# ─── Pages Extensions Config Models ───────────────────────────────────────────


class CloudflareCreatePagesProjectConfig(BaseModel):
    """Create a new Cloudflare Pages project"""
    operation: Literal["create_pages_project"] = Field(default="create_pages_project", title="Create Pages Project", json_schema_extra={"x-creates-resource": True, "x-resource-type": "cloudflare_pages_project", "x-resource-id-path": "result.name", "x-category": "Pages", "x-is-trigger": False, "x-display-name": "Create Pages Project", "ui:hidden": True})
    project_name: str = Field(description="The Pages project name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "project_name",
            "placeholder": "Select a Pages project...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    production_branch: Optional[str] = Field(default="main", description="Production branch name")
    build_command: Optional[str] = Field(default=None, description="Build command e.g. npm run build")
    destination_dir: Optional[str] = Field(default=None, description="Build output directory e.g. dist")

class CloudflareRetryPagesDeploymentConfig(BaseModel):
    """Retry a failed or cancelled Cloudflare Pages deployment"""
    operation: Literal["retry_pages_deployment"] = Field(default="retry_pages_deployment", title="Retry Pages Deployment", json_schema_extra={"x-category": "Pages", "x-is-trigger": False, "x-display-name": "Retry Pages Deployment", "ui:hidden": True})
    project_name: str = Field(description="The Pages project name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "project_name",
            "placeholder": "Select a Pages project...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    deployment_id: str = Field(description="The deployment ID to retry")


# ─── DNS Extensions Config Models ─────────────────────────────────────────────


class CloudflareExportDNSRecordsConfig(BaseModel):
    """Export DNS records for a zone as a BIND zone file"""
    operation: Literal["export_dns_records"] = Field(default="export_dns_records", title="Export Dns Records", json_schema_extra={"x-category": "DNS", "x-is-trigger": False, "x-display-name": "Export Dns Records", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID to export DNS records from", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })

class CloudflareGetDNSSECConfig(BaseModel):
    """Get DNSSEC settings for a zone"""
    operation: Literal["get_dnssec"] = Field(default="get_dnssec", title="Get Dnssec", json_schema_extra={"x-category": "DNS", "x-is-trigger": False, "x-display-name": "Get Dnssec", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })

class CloudflareUpdateDNSSECConfig(BaseModel):
    """Update DNSSEC status for a zone"""
    operation: Literal["update_dnssec"] = Field(default="update_dnssec", title="Update Dnssec", json_schema_extra={"x-category": "DNS", "x-is-trigger": False, "x-display-name": "Update Dnssec", "ui:hidden": True})
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    dnssec_status: str = Field(description="DNSSEC status", json_schema_extra={"enum": ["active", "disabled"], "x-enum-searchable": True})


# ─── R2 Object Operations Config Models ───────────────────────────────────────


class CloudflareListR2ObjectsConfig(BaseModel):
    """List objects in an R2 bucket"""
    operation: Literal["list_r2_objects"] = Field(default="list_r2_objects", title="List R2 Objects", json_schema_extra={"x-category": "R2 Storage", "x-is-trigger": False, "x-display-name": "List R2 Objects", "ui:hidden": True})
    account_id: str = Field(description="Your Cloudflare Account ID", json_schema_extra={"ui:loadValue": True})
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    r2_access_key_id: str = Field(description="R2 API Token Access Key ID from R2 > Manage API Tokens", json_schema_extra={"ui:widget": "password"})
    r2_secret_access_key: str = Field(description="R2 API Token Secret Access Key", json_schema_extra={"ui:widget": "password"})
    prefix: Optional[str] = Field(default=None, description="Filter objects by key prefix")
    max_keys: Optional[int] = Field(default=1000, description="Max objects to list")

class CloudflareGetR2ObjectConfig(BaseModel):
    """Get an object from an R2 bucket"""
    operation: Literal["get_r2_object"] = Field(default="get_r2_object", title="Get R2 Object", json_schema_extra={"x-category": "R2 Storage", "x-is-trigger": False, "x-display-name": "Get R2 Object", "ui:hidden": True})
    account_id: str = Field(description="Your Cloudflare Account ID", json_schema_extra={"ui:loadValue": True})
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    object_key: str = Field(description="The object key (path) within the bucket")
    r2_access_key_id: str = Field(description="R2 API Token Access Key ID from R2 > Manage API Tokens", json_schema_extra={"ui:widget": "password"})
    r2_secret_access_key: str = Field(description="R2 API Token Secret Access Key", json_schema_extra={"ui:widget": "password"})

class CloudflarePutR2ObjectConfig(BaseModel):
    """Upload an object to an R2 bucket"""
    operation: Literal["put_r2_object"] = Field(default="put_r2_object", title="Put R2 Object", json_schema_extra={"x-category": "R2 Storage", "x-is-trigger": False, "x-display-name": "Put R2 Object", "ui:hidden": True})
    account_id: str = Field(description="Your Cloudflare Account ID", json_schema_extra={"ui:loadValue": True})
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    object_key: str = Field(description="The object key (path) within the bucket")
    r2_access_key_id: str = Field(description="R2 API Token Access Key ID from R2 > Manage API Tokens", json_schema_extra={"ui:widget": "password"})
    r2_secret_access_key: str = Field(description="R2 API Token Secret Access Key", json_schema_extra={"ui:widget": "password"})
    content: str = Field(description="Content to upload (text or base64-encoded binary)")
    content_type: Optional[str] = Field(default="text/plain", description="MIME type of the object")
    is_base64: Optional[str] = Field(default="false", description="Set true if content is base64-encoded binary", json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True})

class CloudflareDeleteR2ObjectConfig(BaseModel):
    """Delete an object from an R2 bucket"""
    operation: Literal["delete_r2_object"] = Field(default="delete_r2_object", title="Delete R2 Object", json_schema_extra={"x-category": "R2 Storage", "x-is-trigger": False, "x-display-name": "Delete R2 Object", "ui:hidden": True})
    account_id: str = Field(description="Your Cloudflare Account ID", json_schema_extra={"ui:loadValue": True})
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    object_key: str = Field(description="The object key (path) within the bucket")
    r2_access_key_id: str = Field(description="R2 API Token Access Key ID from R2 > Manage API Tokens", json_schema_extra={"ui:widget": "password"})
    r2_secret_access_key: str = Field(description="R2 API Token Secret Access Key", json_schema_extra={"ui:widget": "password"})

class CloudflareGetR2PresignedUrlConfig(BaseModel):
    """Generate a presigned URL for an R2 object"""
    operation: Literal["get_r2_presigned_url"] = Field(default="get_r2_presigned_url", title="Get R2 Presigned URL", json_schema_extra={"x-category": "R2 Storage", "x-is-trigger": False, "x-display-name": "Get R2 Presigned URL", "ui:hidden": True})
    account_id: str = Field(description="Your Cloudflare Account ID", json_schema_extra={"ui:loadValue": True})
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    object_key: str = Field(description="The object key (path) within the bucket")
    r2_access_key_id: str = Field(description="R2 API Token Access Key ID from R2 > Manage API Tokens", json_schema_extra={"ui:widget": "password"})
    r2_secret_access_key: str = Field(description="R2 API Token Secret Access Key", json_schema_extra={"ui:widget": "password"})
    expiry_seconds: Optional[int] = Field(default=3600, description="URL validity in seconds")
    operation_type: Optional[str] = Field(default="get_object", description="S3 operation for the presigned URL", json_schema_extra={"enum": ["get_object", "put_object"], "x-enum-searchable": True})


# ─── Trigger Config Models ─────────────────────────────────────────────────────


class CloudflareAlertTriggerConfig(WebhookTriggerConfigBase):
    """Trigger workflow when a Cloudflare alert fires"""
    operation: Literal["cloudflare_alert"] = Field(default="cloudflare_alert", title="On Cloudflare Alert", json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Cloudflare Alert", "ui:hidden": True})
    webhook_url: Optional[str] = Field(default=None, json_schema_extra={"ui:widget": "webhook", "ui:loadValue": True})
    alert_type: str = Field(description="Cloudflare alert type. Use list_available_alerts to see all types enabled for your account.", json_schema_extra={"x-enum-searchable": True, "enum": ["universal_ssl_event_type", "dedicated_ssl_certificate_event_type", "ssl_expiry_event", "dos_attack_l7", "health_check_status_notification", "load_balancing_health_alert", "load_balancing_pool_enablement_alert", "failing_logpush_job_disabled_alert", "pages_event_alert", "web_analytics_metrics_update", "scriptmonitor_alert_new_hosts", "scriptmonitor_alert_new_resources", "scriptmonitor_alert_new_malicious_scripts", "scriptmonitor_alert_new_malicious_url", "scriptmonitor_alert_new_malicious_hosts", "scriptmonitor_alert_new_code_change_detections", "scriptmonitor_alert_new_max_length_resource_url", "tunnel_health_event", "block_notification_new_block", "block_notification_review_timeout", "block_notification_block_removed", "incident_alert", "bgp_hijack_notification", "workers_uptime", "maintenance_event_notification", "real_origin_monitoring", "secondary_dns_all_secondaries_failing", "secondary_dns_zone_validation_warning", "secondary_dns_zone_successfully_updated"]})
    policy_name: Optional[str] = Field(default=None, description="Name for the alert policy (defaults to 'NoClick - {alert_type}')")
    cf_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    cf_policy_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


class CloudflareAuditLogTriggerConfig(PollTriggerConfigBase):
    """Trigger workflow on new Cloudflare audit log entries"""
    operation: Literal["cloudflare_audit_log"] = Field(default="cloudflare_audit_log", title="On New Audit Log Entry", json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On New Audit Log Entry", "ui:hidden": True})
    action_type_filter: Optional[str] = Field(default=None, description="Filter by action type e.g. add, delete, update")
    zone_name_filter: Optional[str] = Field(default=None, description="Filter by zone name")
    actor_email_filter: Optional[str] = Field(default=None, description="Filter by actor email")


# ─── Zone Management (additional) Config Models ───────────────────────────────


class CloudflareCreateZoneConfig(BaseModel):
    """Create a new zone (domain) in an account"""

    operation: Literal["create_zone"] = Field(
        default="create_zone",
        title="Create Zone",
        json_schema_extra={"x-creates-resource": True, "x-resource-type": "cloudflare_zone", "x-resource-id-path": "result.id", 
            "x-category": "Zones",
            "x-is-trigger": False,
            "x-display-name": "Create Zone",
            "ui:hidden": True,
        },
    )
    zone_name: str = Field(description="Domain name e.g. example.com")
    jump_start: Optional[str] = Field(
        default="true",
        description="Auto-scan for DNS records",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareDeleteZoneConfig(BaseModel):
    """Delete a zone from an account"""

    operation: Literal["delete_zone"] = Field(
        default="delete_zone",
        title="Delete Zone",
        json_schema_extra={
            "x-category": "Zones",
            "x-is-trigger": False,
            "x-display-name": "Delete Zone",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID to delete", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareEditZoneConfig(BaseModel):
    """Edit zone properties"""

    operation: Literal["edit_zone"] = Field(
        default="edit_zone",
        title="Edit Zone",
        json_schema_extra={
            "x-category": "Zones",
            "x-is-trigger": False,
            "x-display-name": "Edit Zone",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    paused: Optional[str] = Field(
        default=None,
        description="Pause Cloudflare on zone",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    vanity_name_servers: Optional[str] = Field(
        default=None,
        description="Comma-separated custom nameservers",
    )


class CloudflareZoneActivationCheckConfig(BaseModel):
    """Trigger a zone activation check"""

    operation: Literal["zone_activation_check"] = Field(
        default="zone_activation_check",
        title="Zone Activation Check",
        json_schema_extra={
            "x-category": "Zones",
            "x-is-trigger": False,
            "x-display-name": "Zone Activation Check",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


# ─── Rules Lists / Bulk Redirects Config Models ───────────────────────────────


class CloudflareListRulesListsConfig(BaseModel):
    """List all rules lists in an account"""

    operation: Literal["list_rules_lists"] = Field(
        default="list_rules_lists",
        title="List Rules Lists",
        json_schema_extra={
            "x-category": "Rules Lists",
            "x-is-trigger": False,
            "x-display-name": "List Rules Lists",
            "ui:hidden": True,
        },
    )
    per_page: Optional[int] = Field(default=None, description="Number of results per page")


class CloudflareCreateRulesListConfig(BaseModel):
    """Create a new rules list"""

    operation: Literal["create_rules_list"] = Field(
        default="create_rules_list",
        title="Create Rules List",
        json_schema_extra={
            "x-category": "Rules Lists",
            "x-is-trigger": False,
            "x-display-name": "Create Rules List",
            "ui:hidden": True,
        },
    )
    list_name: str = Field(description="Name for the rules list")
    list_kind: str = Field(
        description="Type of list",
        json_schema_extra={
            "enum": ["ip", "redirect", "asn", "hostname"],
            "x-enum-searchable": True,
        },
    )
    description: Optional[str] = Field(default=None, description="Optional description for the list")


class CloudflareGetRulesListConfig(BaseModel):
    """Get details of a specific rules list"""

    operation: Literal["get_rules_list"] = Field(
        default="get_rules_list",
        title="Get Rules List",
        json_schema_extra={
            "x-category": "Rules Lists",
            "x-is-trigger": False,
            "x-display-name": "Get Rules List",
            "ui:hidden": True,
        },
    )
    list_id: str = Field(description="The rules list ID")


class CloudflareUpdateRulesListConfig(BaseModel):
    """Update a rules list description"""

    operation: Literal["update_rules_list"] = Field(
        default="update_rules_list",
        title="Update Rules List",
        json_schema_extra={
            "x-category": "Rules Lists",
            "x-is-trigger": False,
            "x-display-name": "Update Rules List",
            "ui:hidden": True,
        },
    )
    list_id: str = Field(description="The rules list ID")
    description: str = Field(description="New description for the list")


class CloudflareDeleteRulesListConfig(BaseModel):
    """Delete a rules list"""

    operation: Literal["delete_rules_list"] = Field(
        default="delete_rules_list",
        title="Delete Rules List",
        json_schema_extra={
            "x-category": "Rules Lists",
            "x-is-trigger": False,
            "x-display-name": "Delete Rules List",
            "ui:hidden": True,
        },
    )
    list_id: str = Field(description="The rules list ID to delete")


class CloudflareListRulesListItemsConfig(BaseModel):
    """List items in a rules list"""

    operation: Literal["list_rules_list_items"] = Field(
        default="list_rules_list_items",
        title="List Rules List Items",
        json_schema_extra={
            "x-category": "Rules Lists",
            "x-is-trigger": False,
            "x-display-name": "List Rules List Items",
            "ui:hidden": True,
        },
    )
    list_id: str = Field(description="The rules list ID")
    cursor: Optional[str] = Field(default=None, description="Pagination cursor")
    per_page: Optional[int] = Field(default=25, description="Number of results per page")


class CloudflareCreateRulesListItemsConfig(BaseModel):
    """Add items to a rules list"""

    operation: Literal["create_rules_list_items"] = Field(
        default="create_rules_list_items",
        title="Create Rules List Items",
        json_schema_extra={
            "x-category": "Rules Lists",
            "x-is-trigger": False,
            "x-display-name": "Create Rules List Items",
            "ui:hidden": True,
        },
    )
    list_id: str = Field(description="The rules list ID")
    items_json: str = Field(
        description='JSON array of items. For IP lists: [{"ip": "1.2.3.4", "comment": "label"}]. For redirect lists: [{"redirect": {"source_url": "...", "target_url": "...", "status_code": 301}}]. For ASN: [{"asn": 12345}]. For hostname: [{"hostname": {"url_hostname": "example.com"}}]'
    )


class CloudflareReplaceRulesListItemsConfig(BaseModel):
    """Replace all items in a rules list"""

    operation: Literal["replace_rules_list_items"] = Field(
        default="replace_rules_list_items",
        title="Replace Rules List Items",
        json_schema_extra={
            "x-category": "Rules Lists",
            "x-is-trigger": False,
            "x-display-name": "Replace Rules List Items",
            "ui:hidden": True,
        },
    )
    list_id: str = Field(description="The rules list ID")
    items_json: str = Field(
        description="JSON array replacing ALL items in the list"
    )


class CloudflareDeleteRulesListItemsConfig(BaseModel):
    """Delete specific items from a rules list"""

    operation: Literal["delete_rules_list_items"] = Field(
        default="delete_rules_list_items",
        title="Delete Rules List Items",
        json_schema_extra={
            "x-category": "Rules Lists",
            "x-is-trigger": False,
            "x-display-name": "Delete Rules List Items",
            "ui:hidden": True,
        },
    )
    list_id: str = Field(description="The rules list ID")
    item_ids: str = Field(description="Comma-separated item IDs to delete")


class CloudflareGetRulesListOperationConfig(BaseModel):
    """Get the status of a bulk rules list operation"""

    operation: Literal["get_rules_list_operation"] = Field(
        default="get_rules_list_operation",
        title="Get Rules List Operation",
        json_schema_extra={
            "x-category": "Rules Lists",
            "x-is-trigger": False,
            "x-display-name": "Get Rules List Operation",
            "ui:hidden": True,
        },
    )
    operation_id: str = Field(description="Bulk operation ID from create/replace/delete items operations")


class CloudflareListWorkerVersionsConfig(BaseModel):
    """List versions of a Worker script"""

    operation: Literal["list_worker_versions"] = Field(
        default="list_worker_versions",
        title="List Worker Versions",
        json_schema_extra={
            "x-category": "Workers",
            "x-is-trigger": False,
            "x-display-name": "List Worker Versions",
            "ui:hidden": True,
        },
    )
    script_name: str = Field(description="The Worker script name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "worker_script_name",
            "placeholder": "Select a Worker script...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    per_page: Optional[int] = Field(default=10, description="Number of versions per page")
    deployable_only: Optional[str] = Field(
        default="false",
        description="Only list versions eligible for deployment",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareUploadWorkerVersionConfig(BaseModel):
    """Upload a new version of a Worker script"""

    operation: Literal["upload_worker_version"] = Field(
        default="upload_worker_version",
        title="Upload Worker Version",
        json_schema_extra={
            "x-category": "Workers",
            "x-is-trigger": False,
            "x-display-name": "Upload Worker Version",
            "ui:hidden": True,
        },
    )
    script_name: str = Field(description="The Worker script name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "worker_script_name",
            "placeholder": "Select a Worker script...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    script_content: str = Field(
        description="JavaScript code for new version",
        json_schema_extra={"ui:widget": "code_editor"},
    )
    version_message: Optional[str] = Field(default=None, description="Description of this version")


class CloudflareGetWorkerVersionConfig(BaseModel):
    """Get a specific version of a Worker script"""

    operation: Literal["get_worker_version"] = Field(
        default="get_worker_version",
        title="Get Worker Version",
        json_schema_extra={
            "x-category": "Workers",
            "x-is-trigger": False,
            "x-display-name": "Get Worker Version",
            "ui:hidden": True,
        },
    )
    script_name: str = Field(description="The Worker script name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "worker_script_name",
            "placeholder": "Select a Worker script...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    version_id: str = Field(description="The version ID")


class CloudflareListWorkerDeploymentsConfig(BaseModel):
    """List deployments for a Worker script"""

    operation: Literal["list_worker_deployments"] = Field(
        default="list_worker_deployments",
        title="List Worker Deployments",
        json_schema_extra={
            "x-category": "Workers",
            "x-is-trigger": False,
            "x-display-name": "List Worker Deployments",
            "ui:hidden": True,
        },
    )
    script_name: str = Field(description="The Worker script name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "worker_script_name",
            "placeholder": "Select a Worker script...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    per_page: Optional[int] = Field(default=10, description="Number of deployments per page")


class CloudflareCreateWorkerDeploymentConfig(BaseModel):
    """Create a new deployment for a Worker script"""

    operation: Literal["create_worker_deployment"] = Field(
        default="create_worker_deployment",
        title="Create Worker Deployment",
        json_schema_extra={
            "x-category": "Workers",
            "x-is-trigger": False,
            "x-display-name": "Create Worker Deployment",
            "ui:hidden": True,
        },
    )
    script_name: str = Field(description="The Worker script name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "worker_script_name",
            "placeholder": "Select a Worker script...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    version_id: str = Field(description="Version ID to deploy")
    percentage: Optional[int] = Field(default=100, description="Traffic percentage for this version (1-100)")
    strategy: Optional[str] = Field(
        default="percentage",
        description="Deployment strategy",
        json_schema_extra={"enum": ["percentage"], "x-enum-searchable": True},
    )


class CloudflareGetWorkerDeploymentConfig(BaseModel):
    """Get a specific deployment for a Worker script"""

    operation: Literal["get_worker_deployment"] = Field(
        default="get_worker_deployment",
        title="Get Worker Deployment",
        json_schema_extra={
            "x-category": "Workers",
            "x-is-trigger": False,
            "x-display-name": "Get Worker Deployment",
            "ui:hidden": True,
        },
    )
    script_name: str = Field(description="The Worker script name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "worker_script_name",
            "placeholder": "Select a Worker script...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    deployment_id: str = Field(description="The deployment ID")


class CloudflareListWorkerTailsConfig(BaseModel):
    """List active tails for a Worker script"""

    operation: Literal["list_worker_tails"] = Field(
        default="list_worker_tails",
        title="List Worker Tails",
        json_schema_extra={
            "x-category": "Workers",
            "x-is-trigger": False,
            "x-display-name": "List Worker Tails",
            "ui:hidden": True,
        },
    )
    script_name: str = Field(description="The Worker script name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "worker_script_name",
            "placeholder": "Select a Worker script...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareStartWorkerTailConfig(BaseModel):
    """Start a tail session for a Worker script to stream live logs"""

    operation: Literal["start_worker_tail"] = Field(
        default="start_worker_tail",
        title="Start Worker Tail",
        json_schema_extra={
            "x-category": "Workers",
            "x-is-trigger": False,
            "x-display-name": "Start Worker Tail",
            "ui:hidden": True,
        },
    )
    script_name: str = Field(description="The Worker script name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "worker_script_name",
            "placeholder": "Select a Worker script...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareDeleteWorkerTailConfig(BaseModel):
    """Delete an active tail session for a Worker script"""

    operation: Literal["delete_worker_tail"] = Field(
        default="delete_worker_tail",
        title="Delete Worker Tail",
        json_schema_extra={
            "x-category": "Workers",
            "x-is-trigger": False,
            "x-display-name": "Delete Worker Tail",
            "ui:hidden": True,
        },
    )
    script_name: str = Field(description="The Worker script name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "worker_script_name",
            "placeholder": "Select a Worker script...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    tail_id: str = Field(description="The tail session ID to delete")


# ─── AI Gateway Config Models ──────────────────────────────────────────────────


class CloudflareListAIGatewaysConfig(BaseModel):
    """List AI Gateways in an account"""

    operation: Literal["list_ai_gateways"] = Field(
        default="list_ai_gateways",
        title="List Ai Gateways",
        json_schema_extra={
            "x-category": "AI Gateway",
            "x-is-trigger": False,
            "x-display-name": "List Ai Gateways",
            "ui:hidden": True,
        },
    )
    page: Optional[int] = Field(default=None, description="Page number for pagination")
    per_page: Optional[int] = Field(default=20, description="Results per page")
    name_filter: Optional[str] = Field(default=None, description="Filter by gateway name")


class CloudflareCreateAIGatewayConfig(BaseModel):
    """Create a new AI Gateway"""

    operation: Literal["create_ai_gateway"] = Field(
        default="create_ai_gateway",
        title="Create Ai Gateway",
        json_schema_extra={"x-creates-resource": True, "x-resource-type": "cloudflare_ai_gateway", "x-resource-id-path": "result.id", 
            "x-category": "AI Gateway",
            "x-is-trigger": False,
            "x-display-name": "Create Ai Gateway",
            "ui:hidden": True,
        },
    )
    gateway_name: str = Field(description="Human-readable name for the gateway")
    slug: str = Field(description="URL-safe identifier e.g. my-gateway")
    collect_logs: Optional[str] = Field(
        default="true",
        description="Whether to collect logs for requests",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    cache_enabled: Optional[str] = Field(
        default="false",
        description="Enable caching of AI responses",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    rate_limiting_limit: Optional[int] = Field(
        default=None, description="Max requests per interval"
    )
    rate_limiting_interval: Optional[int] = Field(
        default=None, description="Rate limit window in seconds"
    )


class CloudflareGetAIGatewayConfig(BaseModel):
    """Get details for an AI Gateway"""

    operation: Literal["get_ai_gateway"] = Field(
        default="get_ai_gateway",
        title="Get Ai Gateway",
        json_schema_extra={
            "x-category": "AI Gateway",
            "x-is-trigger": False,
            "x-display-name": "Get Ai Gateway",
            "ui:hidden": True,
        },
    )
    gateway_id: str = Field(description="The AI Gateway ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "gateway_id",
            "placeholder": "Select an AI Gateway...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareUpdateAIGatewayConfig(BaseModel):
    """Update an existing AI Gateway"""

    operation: Literal["update_ai_gateway"] = Field(
        default="update_ai_gateway",
        title="Update Ai Gateway",
        json_schema_extra={
            "x-category": "AI Gateway",
            "x-is-trigger": False,
            "x-display-name": "Update Ai Gateway",
            "ui:hidden": True,
        },
    )
    gateway_id: str = Field(description="The AI Gateway ID to update", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "gateway_id",
            "placeholder": "Select an AI Gateway...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    gateway_name: Optional[str] = Field(default=None, description="New gateway name")
    collect_logs: Optional[str] = Field(
        default=None,
        description="Whether to collect logs for requests",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    cache_enabled: Optional[str] = Field(
        default=None,
        description="Enable caching of AI responses",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    rate_limiting_limit: Optional[int] = Field(
        default=None, description="Max requests per interval"
    )
    rate_limiting_interval: Optional[int] = Field(
        default=None, description="Rate limit window in seconds"
    )


class CloudflareDeleteAIGatewayConfig(BaseModel):
    """Delete an AI Gateway"""

    operation: Literal["delete_ai_gateway"] = Field(
        default="delete_ai_gateway",
        title="Delete Ai Gateway",
        json_schema_extra={
            "x-category": "AI Gateway",
            "x-is-trigger": False,
            "x-display-name": "Delete Ai Gateway",
            "ui:hidden": True,
        },
    )
    gateway_id: str = Field(description="The AI Gateway ID to delete", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "gateway_id",
            "placeholder": "Select an AI Gateway...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareListAIGatewayLogsConfig(BaseModel):
    """List logs for an AI Gateway"""

    operation: Literal["list_ai_gateway_logs"] = Field(
        default="list_ai_gateway_logs",
        title="List Ai Gateway Logs",
        json_schema_extra={
            "x-category": "AI Gateway",
            "x-is-trigger": False,
            "x-display-name": "List Ai Gateway Logs",
            "ui:hidden": True,
        },
    )
    gateway_id: str = Field(description="The AI Gateway ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "gateway_id",
            "placeholder": "Select an AI Gateway...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    page: Optional[int] = Field(default=1, description="Page number for pagination")
    per_page: Optional[int] = Field(default=25, description="Results per page")
    start_date: Optional[str] = Field(default=None, description="ISO 8601 start date")
    end_date: Optional[str] = Field(default=None, description="ISO 8601 end date")
    search: Optional[str] = Field(
        default=None, description="Search request/response content"
    )
    model: Optional[str] = Field(
        default=None, description="Filter by model e.g. gpt-4"
    )
    provider: Optional[str] = Field(
        default=None, description="Filter by provider e.g. openai"
    )
    success_only: Optional[str] = Field(
        default=None,
        description="Filter to successful requests only",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareGetAIGatewayLogConfig(BaseModel):
    """Get a specific AI Gateway log entry"""

    operation: Literal["get_ai_gateway_log"] = Field(
        default="get_ai_gateway_log",
        title="Get Ai Gateway Log",
        json_schema_extra={
            "x-category": "AI Gateway",
            "x-is-trigger": False,
            "x-display-name": "Get Ai Gateway Log",
            "ui:hidden": True,
        },
    )
    gateway_id: str = Field(description="The AI Gateway ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "gateway_id",
            "placeholder": "Select an AI Gateway...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    log_id: str = Field(description="The log entry ID")


class CloudflareDeleteAIGatewayLogsConfig(BaseModel):
    """Delete logs for an AI Gateway"""

    operation: Literal["delete_ai_gateway_logs"] = Field(
        default="delete_ai_gateway_logs",
        title="Delete Ai Gateway Logs",
        json_schema_extra={
            "x-category": "AI Gateway",
            "x-is-trigger": False,
            "x-display-name": "Delete Ai Gateway Logs",
            "ui:hidden": True,
        },
    )
    gateway_id: str = Field(description="The AI Gateway ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "gateway_id",
            "placeholder": "Select an AI Gateway...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    start_date: Optional[str] = Field(
        default=None, description="ISO 8601 start date for logs to delete"
    )
    end_date: Optional[str] = Field(
        default=None, description="ISO 8601 end date for logs to delete"
    )


class CloudflareGetAIGatewayLogRequestConfig(BaseModel):
    """Get the request body for an AI Gateway log entry"""

    operation: Literal["get_ai_gateway_log_request"] = Field(
        default="get_ai_gateway_log_request",
        title="Get Ai Gateway Log Request",
        json_schema_extra={
            "x-category": "AI Gateway",
            "x-is-trigger": False,
            "x-display-name": "Get Ai Gateway Log Request",
            "ui:hidden": True,
        },
    )
    gateway_id: str = Field(description="The AI Gateway ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "gateway_id",
            "placeholder": "Select an AI Gateway...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    log_id: str = Field(description="The log entry ID")


class CloudflareGetAIGatewayLogResponseConfig(BaseModel):
    """Get the response body for an AI Gateway log entry"""

    operation: Literal["get_ai_gateway_log_response"] = Field(
        default="get_ai_gateway_log_response",
        title="Get Ai Gateway Log Response",
        json_schema_extra={
            "x-category": "AI Gateway",
            "x-is-trigger": False,
            "x-display-name": "Get Ai Gateway Log Response",
            "ui:hidden": True,
        },
    )
    gateway_id: str = Field(description="The AI Gateway ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "gateway_id",
            "placeholder": "Select an AI Gateway...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    log_id: str = Field(description="The log entry ID")


class CloudflareListAIGatewayDatasetsConfig(BaseModel):
    """List datasets for an AI Gateway"""

    operation: Literal["list_ai_gateway_datasets"] = Field(
        default="list_ai_gateway_datasets",
        title="List Ai Gateway Datasets",
        json_schema_extra={
            "x-category": "AI Gateway",
            "x-is-trigger": False,
            "x-display-name": "List Ai Gateway Datasets",
            "ui:hidden": True,
        },
    )
    gateway_id: str = Field(description="The AI Gateway ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "gateway_id",
            "placeholder": "Select an AI Gateway...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    page: Optional[int] = Field(default=None, description="Page number for pagination")
    per_page: Optional[int] = Field(default=20, description="Results per page")


class CloudflareCreateAIGatewayDatasetConfig(BaseModel):
    """Create a dataset from AI Gateway logs"""

    operation: Literal["create_ai_gateway_dataset"] = Field(
        default="create_ai_gateway_dataset",
        title="Create Ai Gateway Dataset",
        json_schema_extra={
            "x-category": "AI Gateway",
            "x-is-trigger": False,
            "x-display-name": "Create Ai Gateway Dataset",
            "ui:hidden": True,
        },
    )
    gateway_id: str = Field(description="The AI Gateway ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "gateway_id",
            "placeholder": "Select an AI Gateway...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    dataset_name: str = Field(description="Name for the new dataset")
    log_ids: Optional[str] = Field(
        default=None, description="Comma-separated log IDs to include"
    )
    filters_json: Optional[str] = Field(
        default=None, description="JSON filter object to select logs"
    )


class CloudflareDeleteAIGatewayDatasetConfig(BaseModel):
    """Delete an AI Gateway dataset"""

    operation: Literal["delete_ai_gateway_dataset"] = Field(
        default="delete_ai_gateway_dataset",
        title="Delete Ai Gateway Dataset",
        json_schema_extra={
            "x-category": "AI Gateway",
            "x-is-trigger": False,
            "x-display-name": "Delete Ai Gateway Dataset",
            "ui:hidden": True,
        },
    )
    gateway_id: str = Field(description="The AI Gateway ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "gateway_id",
            "placeholder": "Select an AI Gateway...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    dataset_id: str = Field(description="The dataset ID to delete")


class CloudflareListImageVariantsConfig(BaseModel):
    """List all image variants for an account"""

    operation: Literal["list_image_variants"] = Field(
        default="list_image_variants",
        title="List Image Variants",
        json_schema_extra={
            "x-category": "Images",
            "x-is-trigger": False,
            "x-display-name": "List Image Variants",
            "ui:hidden": True,
        },
    )


class CloudflareCreateImageVariantConfig(BaseModel):
    """Create a new image variant"""

    operation: Literal["create_image_variant"] = Field(
        default="create_image_variant",
        title="Create Image Variant",
        json_schema_extra={
            "x-category": "Images",
            "x-is-trigger": False,
            "x-display-name": "Create Image Variant",
            "ui:hidden": True,
        },
    )
    variant_id: str = Field(description="Variant name e.g. thumbnail")
    fit: str = Field(
        description="Resizing behavior when the image is larger than the variant dimensions",
        json_schema_extra={
            "enum": ["scale-down", "contain", "cover", "crop", "pad"],
            "x-enum-searchable": True,
        },
    )
    width: Optional[int] = Field(default=None, description="Max width in pixels")
    height: Optional[int] = Field(default=None, description="Max height in pixels")
    metadata: Optional[str] = Field(
        default="none",
        description="What EXIF metadata to preserve in transformed images",
        json_schema_extra={
            "enum": ["keep", "copyright", "none"],
            "x-enum-searchable": True,
        },
    )
    never_require_signed_urls: Optional[str] = Field(
        default="false",
        description="Whether signed URLs are never required for this variant",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareGetImageVariantConfig(BaseModel):
    """Get details for a specific image variant"""

    operation: Literal["get_image_variant"] = Field(
        default="get_image_variant",
        title="Get Image Variant",
        json_schema_extra={
            "x-category": "Images",
            "x-is-trigger": False,
            "x-display-name": "Get Image Variant",
            "ui:hidden": True,
        },
    )
    variant_id: str = Field(description="The variant name to retrieve")


class CloudflareUpdateImageVariantConfig(BaseModel):
    """Update an existing image variant"""

    operation: Literal["update_image_variant"] = Field(
        default="update_image_variant",
        title="Update Image Variant",
        json_schema_extra={
            "x-category": "Images",
            "x-is-trigger": False,
            "x-display-name": "Update Image Variant",
            "ui:hidden": True,
        },
    )
    variant_id: str = Field(description="The variant name to update")
    fit: Optional[str] = Field(
        default=None,
        description="Resizing behavior when the image is larger than the variant dimensions",
        json_schema_extra={
            "enum": ["scale-down", "contain", "cover", "crop", "pad"],
            "x-enum-searchable": True,
        },
    )
    width: Optional[int] = Field(default=None, description="Max width in pixels")
    height: Optional[int] = Field(default=None, description="Max height in pixels")
    metadata: Optional[str] = Field(
        default=None,
        description="What EXIF metadata to preserve in transformed images",
        json_schema_extra={
            "enum": ["keep", "copyright", "none"],
            "x-enum-searchable": True,
        },
    )


class CloudflareDeleteImageVariantConfig(BaseModel):
    """Delete an image variant"""

    operation: Literal["delete_image_variant"] = Field(
        default="delete_image_variant",
        title="Delete Image Variant",
        json_schema_extra={
            "x-category": "Images",
            "x-is-trigger": False,
            "x-display-name": "Delete Image Variant",
            "ui:hidden": True,
        },
    )
    variant_id: str = Field(description="The variant name to delete")


class CloudflareListImageSigningKeysConfig(BaseModel):
    """List all image signing keys for an account"""

    operation: Literal["list_image_signing_keys"] = Field(
        default="list_image_signing_keys",
        title="List Image Signing Keys",
        json_schema_extra={
            "x-category": "Images",
            "x-is-trigger": False,
            "x-display-name": "List Image Signing Keys",
            "ui:hidden": True,
        },
    )


class CloudflareCreateImageSigningKeyConfig(BaseModel):
    """Create a named image signing key"""

    operation: Literal["create_image_signing_key"] = Field(
        default="create_image_signing_key",
        title="Create Image Signing Key",
        json_schema_extra={
            "x-category": "Images",
            "x-is-trigger": False,
            "x-display-name": "Create Image Signing Key",
            "ui:hidden": True,
        },
    )
    key_name: str = Field(description="Name for the signing key")


class CloudflareDeleteImageSigningKeyConfig(BaseModel):
    """Delete a named image signing key"""

    operation: Literal["delete_image_signing_key"] = Field(
        default="delete_image_signing_key",
        title="Delete Image Signing Key",
        json_schema_extra={
            "x-category": "Images",
            "x-is-trigger": False,
            "x-display-name": "Delete Image Signing Key",
            "ui:hidden": True,
        },
    )
    key_name: str = Field(description="Name of the signing key to delete")


class CloudflareUpdateImageMetadataConfig(BaseModel):
    """Update metadata or signed URL requirement for an image"""

    operation: Literal["update_image_metadata"] = Field(
        default="update_image_metadata",
        title="Update Image Metadata",
        json_schema_extra={
            "x-category": "Images",
            "x-is-trigger": False,
            "x-display-name": "Update Image Metadata",
            "ui:hidden": True,
        },
    )
    image_id: str = Field(description="The image ID to update")
    metadata_json: Optional[str] = Field(
        default=None,
        description="JSON object of custom metadata key-value pairs",
    )
    require_signed_urls: Optional[str] = Field(
        default=None,
        description="Whether this image requires a signed URL to access",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareListD1TablesConfig(BaseModel):
    """List all tables in a D1 database"""

    operation: Literal["list_d1_tables"] = Field(
        default="list_d1_tables",
        title="List D1 Tables",
        json_schema_extra={
            "x-category": "D1 Database",
            "x-is-trigger": False,
            "x-display-name": "List D1 Tables",
            "ui:hidden": True,
        },
    )
    database_id: str = Field(description="The D1 database ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "database_id",
            "placeholder": "Select a D1 database...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareImportD1DataConfig(BaseModel):
    """Import SQL data into a D1 database"""

    operation: Literal["import_d1_data"] = Field(
        default="import_d1_data",
        title="Import D1 Data",
        json_schema_extra={
            "x-category": "D1 Database",
            "x-is-trigger": False,
            "x-display-name": "Import D1 Data",
            "ui:hidden": True,
        },
    )
    database_id: str = Field(description="The D1 database ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "database_id",
            "placeholder": "Select a D1 database...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    sql_content: str = Field(
        description="SQL dump content to import e.g. INSERT INTO table VALUES (...)"
    )
    init_import: Optional[str] = Field(
        default="true",
        description="Whether to initialize the import process",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareGetD1ImportStatusConfig(BaseModel):
    """Get the current import status of a D1 database"""

    operation: Literal["get_d1_database_import_status"] = Field(
        default="get_d1_database_import_status",
        title="Get D1 Database Import Status",
        json_schema_extra={
            "x-category": "D1 Database",
            "x-is-trigger": False,
            "x-display-name": "Get D1 Database Import Status",
            "ui:hidden": True,
        },
    )
    database_id: str = Field(description="The D1 database ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "database_id",
            "placeholder": "Select a D1 database...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareExecuteD1RawQueryConfig(BaseModel):
    """Execute a SQL query in raw array-format mode against a D1 database"""

    operation: Literal["execute_d1_raw_query"] = Field(
        default="execute_d1_raw_query",
        title="Execute D1 Raw Query",
        json_schema_extra={
            "x-category": "D1 Database",
            "x-is-trigger": False,
            "x-display-name": "Execute D1 Raw Query",
            "ui:hidden": True,
        },
    )
    database_id: str = Field(description="The D1 database ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "database_id",
            "placeholder": "Select a D1 database...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    sql: str = Field(
        description="SQL query to execute in raw mode",
        json_schema_extra={"ui:widget": "code_editor"},
    )
    params_json: Optional[str] = Field(
        default=None,
        description="JSON array of parameters e.g. [1, 'text']",
    )


class CloudflareGetGatewayConfigurationConfig(BaseModel):
    """Get Zero Trust Gateway configuration"""

    operation: Literal["get_gateway_configuration"] = Field(
        default="get_gateway_configuration",
        title="Get Gateway Configuration",
        json_schema_extra={
            "x-category": "Zero Trust Gateway",
            "x-is-trigger": False,
            "x-display-name": "Get Gateway Configuration",
            "ui:hidden": True,
        },
    )


class CloudflareUpdateGatewayConfigurationConfig(BaseModel):
    """Update Zero Trust Gateway configuration"""

    operation: Literal["update_gateway_configuration"] = Field(
        default="update_gateway_configuration",
        title="Update Gateway Configuration",
        json_schema_extra={
            "x-category": "Zero Trust Gateway",
            "x-is-trigger": False,
            "x-display-name": "Update Gateway Configuration",
            "ui:hidden": True,
        },
    )
    settings_json: str = Field(
        description="JSON object of gateway settings e.g. {block_page: {enabled: true, name: 'Block Page'}}"
    )


class CloudflareListGatewayRulesConfig(BaseModel):
    """List Zero Trust Gateway firewall rules"""

    operation: Literal["list_gateway_rules"] = Field(
        default="list_gateway_rules",
        title="List Gateway Rules",
        json_schema_extra={
            "x-category": "Zero Trust Gateway",
            "x-is-trigger": False,
            "x-display-name": "List Gateway Rules",
            "ui:hidden": True,
        },
    )
    action_filter: Optional[str] = Field(
        default=None,
        description="Filter by rule action",
        json_schema_extra={
            "enum": [
                "allow", "block", "safesearch", "ytrestricted", "on", "off",
                "scan", "noscan", "isolate", "noisolate", "override",
                "l4_override", "egress", "audit_ssh", "resolve",
            ],
            "x-enum-searchable": True,
        },
    )
    per_page: Optional[int] = Field(default=25, description="Results per page")
    page: Optional[int] = Field(default=1, description="Page number")


class CloudflareCreateGatewayRuleConfig(BaseModel):
    """Create a Zero Trust Gateway firewall rule"""

    operation: Literal["create_gateway_rule"] = Field(
        default="create_gateway_rule",
        title="Create Gateway Rule",
        json_schema_extra={
            "x-category": "Zero Trust Gateway",
            "x-is-trigger": False,
            "x-display-name": "Create Gateway Rule",
            "ui:hidden": True,
        },
    )
    rule_name: str = Field(description="Name of the gateway rule")
    action: str = Field(
        description="Action to take when rule matches",
        json_schema_extra={
            "enum": [
                "allow", "block", "safesearch", "ytrestricted", "override",
                "isolate", "noisolate", "audit_ssh", "resolve",
            ],
            "x-enum-searchable": True,
        },
    )
    enabled: Optional[str] = Field(
        default="true",
        description="Whether the rule is enabled",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    traffic: Optional[str] = Field(
        default=None,
        description='Traffic filter expression e.g. http.request.uri.path == "/api/"',
    )
    identity: Optional[str] = Field(
        default=None, description="Identity filter expression"
    )
    description: Optional[str] = Field(
        default=None, description="Description of the rule"
    )


class CloudflareGetGatewayRuleConfig(BaseModel):
    """Get a Zero Trust Gateway firewall rule"""

    operation: Literal["get_gateway_rule"] = Field(
        default="get_gateway_rule",
        title="Get Gateway Rule",
        json_schema_extra={
            "x-category": "Zero Trust Gateway",
            "x-is-trigger": False,
            "x-display-name": "Get Gateway Rule",
            "ui:hidden": True,
        },
    )
    rule_id: str = Field(description="ID of the gateway rule")


class CloudflareUpdateGatewayRuleConfig(BaseModel):
    """Update a Zero Trust Gateway firewall rule"""

    operation: Literal["update_gateway_rule"] = Field(
        default="update_gateway_rule",
        title="Update Gateway Rule",
        json_schema_extra={
            "x-category": "Zero Trust Gateway",
            "x-is-trigger": False,
            "x-display-name": "Update Gateway Rule",
            "ui:hidden": True,
        },
    )
    rule_id: str = Field(description="ID of the gateway rule")
    rule_name: Optional[str] = Field(default=None, description="New name of the rule")
    action: Optional[str] = Field(
        default=None,
        description="Action to take when rule matches",
        json_schema_extra={
            "enum": [
                "allow", "block", "safesearch", "ytrestricted", "override",
                "isolate", "noisolate", "audit_ssh", "resolve",
            ],
            "x-enum-searchable": True,
        },
    )
    enabled: Optional[str] = Field(
        default=None,
        description="Whether the rule is enabled",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    traffic: Optional[str] = Field(
        default=None, description="Traffic filter expression"
    )
    identity: Optional[str] = Field(
        default=None, description="Identity filter expression"
    )
    description: Optional[str] = Field(
        default=None, description="Description of the rule"
    )


class CloudflareDeleteGatewayRuleConfig(BaseModel):
    """Delete a Zero Trust Gateway firewall rule"""

    operation: Literal["delete_gateway_rule"] = Field(
        default="delete_gateway_rule",
        title="Delete Gateway Rule",
        json_schema_extra={
            "x-category": "Zero Trust Gateway",
            "x-is-trigger": False,
            "x-display-name": "Delete Gateway Rule",
            "ui:hidden": True,
        },
    )
    rule_id: str = Field(description="ID of the gateway rule to delete")


class CloudflareListGatewayListsConfig(BaseModel):
    """List Zero Trust Gateway lists"""

    operation: Literal["list_gateway_lists"] = Field(
        default="list_gateway_lists",
        title="List Gateway Lists",
        json_schema_extra={
            "x-category": "Zero Trust Gateway",
            "x-is-trigger": False,
            "x-display-name": "List Gateway Lists",
            "ui:hidden": True,
        },
    )
    list_type_filter: Optional[str] = Field(
        default=None,
        description="Filter by list type",
        json_schema_extra={
            "enum": ["DOMAIN", "HOST", "IP", "URL", "SUBNET"],
            "x-enum-searchable": True,
        },
    )


class CloudflareCreateGatewayListConfig(BaseModel):
    """Create a Zero Trust Gateway list"""

    operation: Literal["create_gateway_list"] = Field(
        default="create_gateway_list",
        title="Create Gateway List",
        json_schema_extra={
            "x-category": "Zero Trust Gateway",
            "x-is-trigger": False,
            "x-display-name": "Create Gateway List",
            "ui:hidden": True,
        },
    )
    list_name: str = Field(description="Name of the gateway list")
    list_type: str = Field(
        description="Type of items in the list",
        json_schema_extra={
            "enum": ["DOMAIN", "HOST", "IP", "URL", "SUBNET"],
            "x-enum-searchable": True,
        },
    )
    description: Optional[str] = Field(
        default=None, description="Description of the list"
    )
    items_json: Optional[str] = Field(
        default=None,
        description='JSON array of items e.g. [{"value": "example.com"}] for domains or [{"value": "1.2.3.4"}] for IPs',
    )


class CloudflareGetGatewayListConfig(BaseModel):
    """Get a Zero Trust Gateway list"""

    operation: Literal["get_gateway_list"] = Field(
        default="get_gateway_list",
        title="Get Gateway List",
        json_schema_extra={
            "x-category": "Zero Trust Gateway",
            "x-is-trigger": False,
            "x-display-name": "Get Gateway List",
            "ui:hidden": True,
        },
    )
    list_id: str = Field(description="ID of the gateway list")


class CloudflareUpdateGatewayListConfig(BaseModel):
    """Update (append/remove items from) a Zero Trust Gateway list"""

    operation: Literal["update_gateway_list"] = Field(
        default="update_gateway_list",
        title="Update Gateway List",
        json_schema_extra={
            "x-category": "Zero Trust Gateway",
            "x-is-trigger": False,
            "x-display-name": "Update Gateway List",
            "ui:hidden": True,
        },
    )
    list_id: str = Field(description="ID of the gateway list")
    append_items_json: Optional[str] = Field(
        default=None,
        description='JSON array to add e.g. [{"value": "newsite.com"}]',
    )
    remove_values: Optional[str] = Field(
        default=None,
        description="Comma-separated values to remove",
    )


class CloudflareDeleteGatewayListConfig(BaseModel):
    """Delete a Zero Trust Gateway list"""

    operation: Literal["delete_gateway_list"] = Field(
        default="delete_gateway_list",
        title="Delete Gateway List",
        json_schema_extra={
            "x-category": "Zero Trust Gateway",
            "x-is-trigger": False,
            "x-display-name": "Delete Gateway List",
            "ui:hidden": True,
        },
    )
    list_id: str = Field(description="ID of the gateway list to delete")


class CloudflareListGatewayListItemsConfig(BaseModel):
    """List items in a Zero Trust Gateway list"""

    operation: Literal["list_gateway_list_items"] = Field(
        default="list_gateway_list_items",
        title="List Gateway List Items",
        json_schema_extra={
            "x-category": "Zero Trust Gateway",
            "x-is-trigger": False,
            "x-display-name": "List Gateway List Items",
            "ui:hidden": True,
        },
    )
    list_id: str = Field(description="ID of the gateway list")
    per_page: Optional[int] = Field(default=25, description="Results per page")
    page: Optional[int] = Field(default=1, description="Page number")


class CloudflareListGatewayLocationsConfig(BaseModel):
    """List Zero Trust Gateway locations"""

    operation: Literal["list_gateway_locations"] = Field(
        default="list_gateway_locations",
        title="List Gateway Locations",
        json_schema_extra={
            "x-category": "Zero Trust Gateway",
            "x-is-trigger": False,
            "x-display-name": "List Gateway Locations",
            "ui:hidden": True,
        },
    )


class CloudflareCreateGatewayLocationConfig(BaseModel):
    """Create a Zero Trust Gateway location"""

    operation: Literal["create_gateway_location"] = Field(
        default="create_gateway_location",
        title="Create Gateway Location",
        json_schema_extra={
            "x-category": "Zero Trust Gateway",
            "x-is-trigger": False,
            "x-display-name": "Create Gateway Location",
            "ui:hidden": True,
        },
    )
    location_name: str = Field(description="Name of the gateway location")
    client_default: Optional[str] = Field(
        default="false",
        description="Set as default DNS location",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    ecs_support: Optional[str] = Field(
        default="false",
        description="Enable ECS support for split horizon DNS",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareGetGatewayLocationConfig(BaseModel):
    """Get a Zero Trust Gateway location"""

    operation: Literal["get_gateway_location"] = Field(
        default="get_gateway_location",
        title="Get Gateway Location",
        json_schema_extra={
            "x-category": "Zero Trust Gateway",
            "x-is-trigger": False,
            "x-display-name": "Get Gateway Location",
            "ui:hidden": True,
        },
    )
    location_id: str = Field(description="ID of the gateway location")


class CloudflareDeleteGatewayLocationConfig(BaseModel):
    """Delete a Zero Trust Gateway location"""

    operation: Literal["delete_gateway_location"] = Field(
        default="delete_gateway_location",
        title="Delete Gateway Location",
        json_schema_extra={
            "x-category": "Zero Trust Gateway",
            "x-is-trigger": False,
            "x-display-name": "Delete Gateway Location",
            "ui:hidden": True,
        },
    )
    location_id: str = Field(description="ID of the gateway location to delete")


class CloudflareGetPageShieldSettingsConfig(BaseModel):
    """Get Page Shield settings for a zone"""

    operation: Literal["get_page_shield_settings"] = Field(
        default="get_page_shield_settings",
        title="Get Page Shield Settings",
        json_schema_extra={
            "x-category": "Page Shield",
            "x-is-trigger": False,
            "x-display-name": "Get Page Shield Settings",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID to get Page Shield settings for", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareUpdatePageShieldSettingsConfig(BaseModel):
    """Update Page Shield settings for a zone"""

    operation: Literal["update_page_shield_settings"] = Field(
        default="update_page_shield_settings",
        title="Update Page Shield Settings",
        json_schema_extra={
            "x-category": "Page Shield",
            "x-is-trigger": False,
            "x-display-name": "Update Page Shield Settings",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID to update Page Shield settings for", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    enabled: Optional[str] = Field(
        default=None,
        description="Enable or disable Page Shield",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    use_cf_endpoint: Optional[str] = Field(
        default=None,
        description="Use Cloudflare as CSP reporting endpoint",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareListPageShieldScriptsConfig(BaseModel):
    """List Page Shield scripts detected for a zone"""

    operation: Literal["list_page_shield_scripts"] = Field(
        default="list_page_shield_scripts",
        title="List Page Shield Scripts",
        json_schema_extra={
            "x-category": "Page Shield",
            "x-is-trigger": False,
            "x-display-name": "List Page Shield Scripts",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID to list Page Shield scripts for", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    page: Optional[int] = Field(default=1, description="Page number of results")
    per_page: Optional[int] = Field(default=15, description="Number of results per page")
    status: Optional[str] = Field(
        default=None,
        description="Filter by script status",
        json_schema_extra={"enum": ["active", "infrequent"], "x-enum-searchable": True},
    )


class CloudflareGetPageShieldScriptConfig(BaseModel):
    """Get details for a specific Page Shield script"""

    operation: Literal["get_page_shield_script"] = Field(
        default="get_page_shield_script",
        title="Get Page Shield Script",
        json_schema_extra={
            "x-category": "Page Shield",
            "x-is-trigger": False,
            "x-display-name": "Get Page Shield Script",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    script_id: str = Field(description="The Page Shield script ID")


class CloudflareListPageShieldConnectionsConfig(BaseModel):
    """List Page Shield connections detected for a zone"""

    operation: Literal["list_page_shield_connections"] = Field(
        default="list_page_shield_connections",
        title="List Page Shield Connections",
        json_schema_extra={
            "x-category": "Page Shield",
            "x-is-trigger": False,
            "x-display-name": "List Page Shield Connections",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID to list Page Shield connections for", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    page: Optional[int] = Field(default=1, description="Page number of results")
    per_page: Optional[int] = Field(default=15, description="Number of results per page")


class CloudflareGetPageShieldConnectionConfig(BaseModel):
    """Get details for a specific Page Shield connection"""

    operation: Literal["get_page_shield_connection"] = Field(
        default="get_page_shield_connection",
        title="Get Page Shield Connection",
        json_schema_extra={
            "x-category": "Page Shield",
            "x-is-trigger": False,
            "x-display-name": "Get Page Shield Connection",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    connection_id: str = Field(description="The Page Shield connection ID")


class CloudflareListPageShieldPoliciesConfig(BaseModel):
    """List Page Shield CSP policies for a zone"""

    operation: Literal["list_page_shield_policies"] = Field(
        default="list_page_shield_policies",
        title="List Page Shield Policies",
        json_schema_extra={
            "x-category": "Page Shield",
            "x-is-trigger": False,
            "x-display-name": "List Page Shield Policies",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID to list Page Shield policies for", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareCreatePageShieldPolicyConfig(BaseModel):
    """Create a Page Shield CSP policy for a zone"""

    operation: Literal["create_page_shield_policy"] = Field(
        default="create_page_shield_policy",
        title="Create Page Shield Policy",
        json_schema_extra={
            "x-category": "Page Shield",
            "x-is-trigger": False,
            "x-display-name": "Create Page Shield Policy",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID to create the policy for", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    action: str = Field(
        description="Policy action",
        json_schema_extra={"enum": ["allow", "log"], "x-enum-searchable": True},
    )
    expression: str = Field(description="CSP policy expression")
    value: str = Field(description="Policy value e.g. script-src example.com")
    description: Optional[str] = Field(default=None, description="Optional description for the policy")
    enabled: Optional[str] = Field(
        default="true",
        description="Enable or disable the policy",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareDeletePageShieldPolicyConfig(BaseModel):
    """Delete a Page Shield CSP policy"""

    operation: Literal["delete_page_shield_policy"] = Field(
        default="delete_page_shield_policy",
        title="Delete Page Shield Policy",
        json_schema_extra={
            "x-category": "Page Shield",
            "x-is-trigger": False,
            "x-display-name": "Delete Page Shield Policy",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    policy_id: str = Field(description="The Page Shield policy ID to delete")


# ─── Cache Reserve & Argo Config Models ────────────────────────────────────────


class CloudflareGetCacheReserveConfig(BaseModel):
    """Get Cache Reserve setting for a zone"""

    operation: Literal["get_cache_reserve"] = Field(
        default="get_cache_reserve",
        title="Get Cache Reserve",
        json_schema_extra={
            "x-category": "Cache",
            "x-is-trigger": False,
            "x-display-name": "Get Cache Reserve",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID to get Cache Reserve setting for", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareUpdateCacheReserveConfig(BaseModel):
    """Update Cache Reserve setting for a zone"""

    operation: Literal["update_cache_reserve"] = Field(
        default="update_cache_reserve",
        title="Update Cache Reserve",
        json_schema_extra={
            "x-category": "Cache",
            "x-is-trigger": False,
            "x-display-name": "Update Cache Reserve",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID to update Cache Reserve setting for", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    cache_reserve_enabled: str = Field(
        description="Enable or disable Cache Reserve",
        json_schema_extra={"enum": ["on", "off"], "x-enum-searchable": True},
    )


class CloudflareGetArgoSmartRoutingConfig(BaseModel):
    """Get Argo Smart Routing setting for a zone"""

    operation: Literal["get_argo_smart_routing"] = Field(
        default="get_argo_smart_routing",
        title="Get Argo Smart Routing",
        json_schema_extra={
            "x-category": "Cache",
            "x-is-trigger": False,
            "x-display-name": "Get Argo Smart Routing",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID to get Argo Smart Routing setting for", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareUpdateArgoSmartRoutingConfig(BaseModel):
    """Update Argo Smart Routing setting for a zone"""

    operation: Literal["update_argo_smart_routing"] = Field(
        default="update_argo_smart_routing",
        title="Update Argo Smart Routing",
        json_schema_extra={
            "x-category": "Cache",
            "x-is-trigger": False,
            "x-display-name": "Update Argo Smart Routing",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID to update Argo Smart Routing for", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    smart_routing_enabled: str = Field(
        description="Enable or disable Argo Smart Routing",
        json_schema_extra={"enum": ["on", "off"], "x-enum-searchable": True},
    )


class CloudflareGetTieredCachingConfig(BaseModel):
    """Get Argo Tiered Caching setting for a zone"""

    operation: Literal["get_tiered_caching"] = Field(
        default="get_tiered_caching",
        title="Get Tiered Caching",
        json_schema_extra={
            "x-category": "Cache",
            "x-is-trigger": False,
            "x-display-name": "Get Tiered Caching",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID to get Tiered Caching setting for", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareUpdateTieredCachingConfig(BaseModel):
    """Update Argo Tiered Caching setting for a zone"""

    operation: Literal["update_tiered_caching"] = Field(
        default="update_tiered_caching",
        title="Update Tiered Caching",
        json_schema_extra={
            "x-category": "Cache",
            "x-is-trigger": False,
            "x-display-name": "Update Tiered Caching",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID to update Tiered Caching for", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    tiered_caching_enabled: str = Field(
        description="Enable or disable Argo Tiered Caching",
        json_schema_extra={"enum": ["on", "off"], "x-enum-searchable": True},
    )


class CloudflarePurgeCacheEverythingConfig(BaseModel):
    """Purge all cached content for a zone"""

    operation: Literal["purge_cache_everything"] = Field(
        default="purge_cache_everything",
        title="Purge Cache Everything",
        json_schema_extra={
            "x-category": "Cache",
            "x-is-trigger": False,
            "x-display-name": "Purge Cache Everything",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID to purge all cached content for", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareGetZoneSettingsAllConfig(BaseModel):
    """Get all zone settings in a single call"""

    operation: Literal["get_zone_settings_all"] = Field(
        default="get_zone_settings_all",
        title="Get Zone Settings All",
        json_schema_extra={
            "x-category": "Cache",
            "x-is-trigger": False,
            "x-display-name": "Get Zone Settings All",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID to get all settings for", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareGetR2CORSPolicyConfig(BaseModel):
    """Get CORS policy for an R2 bucket"""

    operation: Literal["get_r2_cors_policy"] = Field(
        default="get_r2_cors_policy",
        title="Get R2 CORS Policy",
        json_schema_extra={
            "x-category": "R2 Bucket",
            "x-is-trigger": False,
            "x-display-name": "Get R2 CORS Policy",
            "ui:hidden": True,
        },
    )
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflarePutR2CORSPolicyConfig(BaseModel):
    """Set CORS policy for an R2 bucket"""

    operation: Literal["put_r2_cors_policy"] = Field(
        default="put_r2_cors_policy",
        title="Put R2 CORS Policy",
        json_schema_extra={
            "x-category": "R2 Bucket",
            "x-is-trigger": False,
            "x-display-name": "Put R2 CORS Policy",
            "ui:hidden": True,
        },
    )
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    cors_rules_json: str = Field(
        description='JSON array of CORS rules e.g. [{"allowedOrigins": ["https://example.com"], "allowedMethods": ["GET","PUT"], "allowedHeaders": ["*"]}]'
    )


class CloudflareDeleteR2CORSPolicyConfig(BaseModel):
    """Delete CORS policy for an R2 bucket"""

    operation: Literal["delete_r2_cors_policy"] = Field(
        default="delete_r2_cors_policy",
        title="Delete R2 CORS Policy",
        json_schema_extra={
            "x-category": "R2 Bucket",
            "x-is-trigger": False,
            "x-display-name": "Delete R2 CORS Policy",
            "ui:hidden": True,
        },
    )
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareGetR2LifecycleRulesConfig(BaseModel):
    """Get lifecycle rules for an R2 bucket"""

    operation: Literal["get_r2_lifecycle_rules"] = Field(
        default="get_r2_lifecycle_rules",
        title="Get R2 Lifecycle Rules",
        json_schema_extra={
            "x-category": "R2 Bucket",
            "x-is-trigger": False,
            "x-display-name": "Get R2 Lifecycle Rules",
            "ui:hidden": True,
        },
    )
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflarePutR2LifecycleRulesConfig(BaseModel):
    """Set lifecycle rules for an R2 bucket"""

    operation: Literal["put_r2_lifecycle_rules"] = Field(
        default="put_r2_lifecycle_rules",
        title="Put R2 Lifecycle Rules",
        json_schema_extra={
            "x-category": "R2 Bucket",
            "x-is-trigger": False,
            "x-display-name": "Put R2 Lifecycle Rules",
            "ui:hidden": True,
        },
    )
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    lifecycle_rules_json: str = Field(
        description='JSON array of lifecycle rules e.g. [{"id": "expire-old", "status": "enabled", "expiration": {"days": 30}}]'
    )


class CloudflareDeleteR2LifecycleRulesConfig(BaseModel):
    """Delete all lifecycle rules for an R2 bucket"""

    operation: Literal["delete_r2_lifecycle_rules"] = Field(
        default="delete_r2_lifecycle_rules",
        title="Delete R2 Lifecycle Rules",
        json_schema_extra={
            "x-category": "R2 Bucket",
            "x-is-trigger": False,
            "x-display-name": "Delete R2 Lifecycle Rules",
            "ui:hidden": True,
        },
    )
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareListR2CustomDomainsConfig(BaseModel):
    """List custom domains for an R2 bucket"""

    operation: Literal["list_r2_custom_domains"] = Field(
        default="list_r2_custom_domains",
        title="List R2 Custom Domains",
        json_schema_extra={
            "x-category": "R2 Bucket",
            "x-is-trigger": False,
            "x-display-name": "List R2 Custom Domains",
            "ui:hidden": True,
        },
    )
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareCreateR2CustomDomainConfig(BaseModel):
    """Add a custom domain to an R2 bucket"""

    operation: Literal["create_r2_custom_domain"] = Field(
        default="create_r2_custom_domain",
        title="Create R2 Custom Domain",
        json_schema_extra={
            "x-category": "R2 Bucket",
            "x-is-trigger": False,
            "x-display-name": "Create R2 Custom Domain",
            "ui:hidden": True,
        },
    )
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    custom_domain: str = Field(description="Custom domain e.g. files.example.com")
    zone_id: Optional[str] = Field(default=None, description="Zone ID for the custom domain")
    enabled: Optional[str] = Field(
        default="true",
        description="Whether to enable the custom domain",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareUpdateR2CustomDomainConfig(BaseModel):
    """Update a custom domain on an R2 bucket"""

    operation: Literal["update_r2_custom_domain"] = Field(
        default="update_r2_custom_domain",
        title="Update R2 Custom Domain",
        json_schema_extra={
            "x-category": "R2 Bucket",
            "x-is-trigger": False,
            "x-display-name": "Update R2 Custom Domain",
            "ui:hidden": True,
        },
    )
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    custom_domain: str = Field(description="The custom domain to update")
    enabled: Optional[str] = Field(
        default=None,
        description="Whether to enable the custom domain",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    min_tls: Optional[str] = Field(
        default="1.2",
        description="Minimum TLS version",
        json_schema_extra={"enum": ["1.0", "1.2", "1.3"], "x-enum-searchable": True},
    )


class CloudflareDeleteR2CustomDomainConfig(BaseModel):
    """Remove a custom domain from an R2 bucket"""

    operation: Literal["delete_r2_custom_domain"] = Field(
        default="delete_r2_custom_domain",
        title="Delete R2 Custom Domain",
        json_schema_extra={
            "x-category": "R2 Bucket",
            "x-is-trigger": False,
            "x-display-name": "Delete R2 Custom Domain",
            "ui:hidden": True,
        },
    )
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    custom_domain: str = Field(description="The custom domain to remove")


class CloudflareGetR2ManagedDomainConfig(BaseModel):
    """Get managed r2.dev domain public access status for an R2 bucket"""

    operation: Literal["get_r2_managed_domain"] = Field(
        default="get_r2_managed_domain",
        title="Get R2 Managed Domain",
        json_schema_extra={
            "x-category": "R2 Bucket",
            "x-is-trigger": False,
            "x-display-name": "Get R2 Managed Domain",
            "ui:hidden": True,
        },
    )
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareUpdateR2ManagedDomainConfig(BaseModel):
    """Enable or disable public access via the r2.dev subdomain"""

    operation: Literal["update_r2_managed_domain"] = Field(
        default="update_r2_managed_domain",
        title="Update R2 Managed Domain",
        json_schema_extra={
            "x-category": "R2 Bucket",
            "x-is-trigger": False,
            "x-display-name": "Update R2 Managed Domain",
            "ui:hidden": True,
        },
    )
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    public_access_enabled: str = Field(
        description="Enable public access via r2.dev subdomain",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareGetR2BucketDetailsConfig(BaseModel):
    """Get R2 bucket metadata including storage class and location hint"""

    operation: Literal["get_r2_bucket_details"] = Field(
        default="get_r2_bucket_details",
        title="Get R2 Bucket Details",
        json_schema_extra={
            "x-category": "R2 Bucket",
            "x-is-trigger": False,
            "x-display-name": "Get R2 Bucket Details",
            "ui:hidden": True,
        },
    )
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareUpdateR2BucketConfig(BaseModel):
    """Update R2 bucket settings such as storage class"""

    operation: Literal["update_r2_bucket"] = Field(
        default="update_r2_bucket",
        title="Update R2 Bucket",
        json_schema_extra={
            "x-category": "R2 Bucket",
            "x-is-trigger": False,
            "x-display-name": "Update R2 Bucket",
            "ui:hidden": True,
        },
    )
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    storage_class: Optional[str] = Field(
        default=None,
        description="Change storage class",
        json_schema_extra={
            "enum": ["Standard", "InfrequentAccess"],
            "x-enum-searchable": True,
        },
    )


class CloudflareQueueMessageTriggerConfig(PollTriggerConfigBase):
    """Trigger when new messages arrive in a Cloudflare Queue"""

    operation: Literal["cloudflare_queue_message"] = Field(
        default="cloudflare_queue_message",
        title="On Queue Message",
        json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Queue Message", "ui:hidden": True},
    )
    queue_id: str = Field(description="Queue ID to poll for messages", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "queue_id",
            "placeholder": "Select a Queue...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    batch_size: Optional[int] = Field(default=10, description="Number of messages to pull per poll (1-100)")
    visibility_timeout_ms: Optional[int] = Field(default=30000, description="Visibility timeout in milliseconds")


class CloudflarePagesDeployTriggerConfig(PollTriggerConfigBase):
    """Trigger when a new Cloudflare Pages deployment is created"""

    operation: Literal["cloudflare_pages_deploy"] = Field(
        default="cloudflare_pages_deploy",
        title="On Pages Deployment",
        json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Pages Deployment", "ui:hidden": True},
    )
    project_name: str = Field(description="Pages project name to watch for deployments", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "project_name",
            "placeholder": "Select a Pages project...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    environment_filter: Optional[str] = Field(
        default=None,
        description="Only trigger for deployments to this environment",
        json_schema_extra={"enum": ["production", "preview"], "x-enum-searchable": True},
    )


class CloudflareR2NewObjectTriggerConfig(PollTriggerConfigBase):
    """Trigger when a new object appears in an R2 bucket"""

    operation: Literal["cloudflare_r2_new_object"] = Field(
        default="cloudflare_r2_new_object",
        title="On New R2 Object",
        json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On New R2 Object", "ui:hidden": True},
    )
    account_id: str = Field(description="Your Cloudflare Account ID", json_schema_extra={"ui:loadValue": True})
    bucket_name: str = Field(description="R2 bucket name to watch for new objects", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    r2_access_key_id: str = Field(description="R2 API Token Access Key ID from R2 > Manage API Tokens", json_schema_extra={"ui:widget": "password"})
    r2_secret_access_key: str = Field(description="R2 API Token Secret Access Key", json_schema_extra={"ui:widget": "password"})
    key_prefix: Optional[str] = Field(default=None, description="Only trigger for objects with this prefix")


class CloudflareDNSChangeTriggerConfig(PollTriggerConfigBase):
    """Trigger when DNS records in a zone are added or modified"""

    operation: Literal["cloudflare_dns_change"] = Field(
        default="cloudflare_dns_change",
        title="On DNS Record Change",
        json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On DNS Record Change", "ui:hidden": True},
    )
    zone_id: str = Field(description="Zone ID to watch for DNS record changes", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    record_type_filter: Optional[str] = Field(default=None, description="Only trigger for specific record type e.g. A, CNAME")


class CloudflareHealthCheckStatusTriggerConfig(PollTriggerConfigBase):
    """Trigger when a Cloudflare health check changes status"""

    operation: Literal["cloudflare_health_check_status"] = Field(
        default="cloudflare_health_check_status",
        title="On Health Check Status Change",
        json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Health Check Status Change", "ui:hidden": True},
    )
    zone_id: str = Field(description="Zone ID containing the health checks to monitor", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    healthcheck_id: Optional[str] = Field(default=None, description="Specific health check ID to watch, or leave empty to watch all")


class CloudflareStreamEventTriggerConfig(WebhookTriggerConfigBase):
    """Trigger when a Stream video event occurs"""

    operation: Literal["cloudflare_stream_event"] = Field(
        default="cloudflare_stream_event",
        title="On Stream Video Event",
        json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Stream Video Event", "ui:hidden": True},
    )
    webhook_url: Optional[str] = Field(default=None, json_schema_extra={"ui:widget": "webhook", "ui:loadValue": True})
    event_types: Optional[str] = Field(
        default=None,
        description="Comma-separated event types to match: video-uploaded,video-encoding-completed,video-encoding-failed,live-input-connected,live-input-disconnected. Leave empty to receive all events.",
    )


# ─── Access Identity Providers Config Models ──────────────────────────────────


class CloudflareListIdentityProvidersConfig(BaseModel):
    """List all Access identity providers in an account"""

    operation: Literal["list_identity_providers"] = Field(
        default="list_identity_providers",
        title="List Identity Providers",
        json_schema_extra={
            "x-category": "Access",
            "x-is-trigger": False,
            "x-display-name": "List Identity Providers",
            "ui:hidden": True,
        },
    )


class CloudflareGetIdentityProviderConfig(BaseModel):
    """Get a specific Access identity provider"""

    operation: Literal["get_identity_provider"] = Field(
        default="get_identity_provider",
        title="Get Identity Provider",
        json_schema_extra={
            "x-category": "Access",
            "x-is-trigger": False,
            "x-display-name": "Get Identity Provider",
            "ui:hidden": True,
        },
    )
    idp_id: str = Field(description="The identity provider UUID")


class CloudflareCreateIdentityProviderConfig(BaseModel):
    """Create an Access identity provider"""

    operation: Literal["create_identity_provider"] = Field(
        default="create_identity_provider",
        title="Create Identity Provider",
        json_schema_extra={
            "x-category": "Access",
            "x-is-trigger": False,
            "x-display-name": "Create Identity Provider",
            "ui:hidden": True,
        },
    )
    idp_name: str = Field(description="Display name for the identity provider")
    idp_type: str = Field(
        description="Identity provider type",
        json_schema_extra={
            "enum": [
                "azureAD", "centrify", "facebook", "github", "google",
                "google-apps", "linkedin", "oidc", "okta", "onelogin",
                "pingone", "saml", "yandex", "onetimepin",
            ],
            "x-enum-searchable": True,
        },
    )
    idp_config_json: str = Field(
        description="JSON configuration for the IdP. For GitHub: {client_id, client_secret}. For Google: {client_id, client_secret}. For SAML: {sso_target_url, idp_public_cert, issuer_url}. For OIDC: {client_id, client_secret, auth_url, token_url, certs_url, scopes}",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 4},
    )


class CloudflareUpdateIdentityProviderConfig(BaseModel):
    """Update an Access identity provider"""

    operation: Literal["update_identity_provider"] = Field(
        default="update_identity_provider",
        title="Update Identity Provider",
        json_schema_extra={
            "x-category": "Access",
            "x-is-trigger": False,
            "x-display-name": "Update Identity Provider",
            "ui:hidden": True,
        },
    )
    idp_id: str = Field(description="The identity provider UUID to update")
    idp_name: Optional[str] = Field(default=None, description="Display name for the identity provider")
    idp_type: Optional[str] = Field(
        default=None,
        description="Identity provider type",
        json_schema_extra={
            "enum": [
                "azureAD", "centrify", "facebook", "github", "google",
                "google-apps", "linkedin", "oidc", "okta", "onelogin",
                "pingone", "saml", "yandex", "onetimepin",
            ],
            "x-enum-searchable": True,
        },
    )
    idp_config_json: Optional[str] = Field(
        default=None,
        description="JSON configuration for the IdP.",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 4},
    )


class CloudflareDeleteIdentityProviderConfig(BaseModel):
    """Delete an Access identity provider"""

    operation: Literal["delete_identity_provider"] = Field(
        default="delete_identity_provider",
        title="Delete Identity Provider",
        json_schema_extra={
            "x-category": "Access",
            "x-is-trigger": False,
            "x-display-name": "Delete Identity Provider",
            "ui:hidden": True,
        },
    )
    idp_id: str = Field(description="The identity provider UUID to delete")


# ─── Access Users & Sessions Config Models ────────────────────────────────────


class CloudflareListAccessUsersConfig(BaseModel):
    """List Access users for an account"""

    operation: Literal["list_access_users"] = Field(
        default="list_access_users",
        title="List Access Users",
        json_schema_extra={
            "x-category": "Access",
            "x-is-trigger": False,
            "x-display-name": "List Access Users",
            "ui:hidden": True,
        },
    )
    email_filter: Optional[str] = Field(default=None, description="Filter by email address")
    per_page: Optional[int] = Field(default=25, description="Number of results per page")


class CloudflareGetAccessUserConfig(BaseModel):
    """Get a specific Access user"""

    operation: Literal["get_access_user"] = Field(
        default="get_access_user",
        title="Get Access User",
        json_schema_extra={
            "x-category": "Access",
            "x-is-trigger": False,
            "x-display-name": "Get Access User",
            "ui:hidden": True,
        },
    )
    user_id: str = Field(description="The Access user UUID")


class CloudflareListAccessUserSessionsConfig(BaseModel):
    """List active sessions for an Access user"""

    operation: Literal["list_access_user_sessions"] = Field(
        default="list_access_user_sessions",
        title="List Access User Sessions",
        json_schema_extra={
            "x-category": "Access",
            "x-is-trigger": False,
            "x-display-name": "List Access User Sessions",
            "ui:hidden": True,
        },
    )
    user_id: str = Field(description="The Access user UUID")


class CloudflareRevokeAccessUserSessionConfig(BaseModel):
    """Revoke all active Access sessions for a user by email"""

    operation: Literal["revoke_access_user_session"] = Field(
        default="revoke_access_user_session",
        title="Revoke Access User Session",
        json_schema_extra={
            "x-category": "Access",
            "x-is-trigger": False,
            "x-display-name": "Revoke Access User Session",
            "ui:hidden": True,
        },
    )
    email: str = Field(description="Email of user to revoke all active sessions for")


# ─── Access Organization Config Models ────────────────────────────────────────


class CloudflareGetAccessOrganizationConfig(BaseModel):
    """Get the Access organization settings"""

    operation: Literal["get_access_organization"] = Field(
        default="get_access_organization",
        title="Get Access Organization",
        json_schema_extra={
            "x-category": "Access",
            "x-is-trigger": False,
            "x-display-name": "Get Access Organization",
            "ui:hidden": True,
        },
    )


class CloudflareUpdateAccessOrganizationConfig(BaseModel):
    """Update the Access organization settings"""

    operation: Literal["update_access_organization"] = Field(
        default="update_access_organization",
        title="Update Access Organization",
        json_schema_extra={
            "x-category": "Access",
            "x-is-trigger": False,
            "x-display-name": "Update Access Organization",
            "ui:hidden": True,
        },
    )
    org_name: Optional[str] = Field(default=None, description="Organization display name")
    session_duration: Optional[str] = Field(default=None, description="Session duration e.g. 24h")
    is_ui_read_only: Optional[str] = Field(
        default=None,
        description="Make UI read-only for non-admin users",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareCreateAccessKeyRotationConfig(BaseModel):
    """Rotate the Access JWT signing key"""

    operation: Literal["create_access_key_rotation"] = Field(
        default="create_access_key_rotation",
        title="Rotate Access Signing Key",
        json_schema_extra={
            "x-category": "Access",
            "x-is-trigger": False,
            "x-display-name": "Rotate Access Signing Key",
            "ui:hidden": True,
        },
    )


# ─── Secondary DNS Config Models ──────────────────────────────────────────────


class CloudflareGetSecondaryDNSConfigConfig(BaseModel):
    """Get secondary DNS configuration for a zone"""

    operation: Literal["get_secondary_dns_config"] = Field(
        default="get_secondary_dns_config",
        title="Get Secondary DNS Config",
        json_schema_extra={
            "x-category": "DNS",
            "x-is-trigger": False,
            "x-display-name": "Get Secondary DNS Config",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(
        description="Get secondary DNS configuration - whether zone is primary or secondary, AXFR peers"
    )


class CloudflareUpdateSecondaryDNSConfigConfig(BaseModel):
    """Update secondary DNS configuration for a zone"""

    operation: Literal["update_secondary_dns_config"] = Field(
        default="update_secondary_dns_config",
        title="Update Secondary DNS Config",
        json_schema_extra={
            "x-category": "DNS",
            "x-is-trigger": False,
            "x-display-name": "Update Secondary DNS Config",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    config_json: str = Field(
        description='JSON secondary DNS config. For primary zone: {"peers": [{"id": "peer-id"}]}. For secondary: {"primary_nameserver": {"name": "ns1.example.com"}, "tsig": {"id": "tsig-id"}}',
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 4},
    )


class CloudflareListSecondaryDNSPeersConfig(BaseModel):
    """List secondary DNS peers for an account"""

    operation: Literal["list_secondary_dns_peers"] = Field(
        default="list_secondary_dns_peers",
        title="List Secondary DNS Peers",
        json_schema_extra={
            "x-category": "DNS",
            "x-is-trigger": False,
            "x-display-name": "List Secondary DNS Peers",
            "ui:hidden": True,
        },
    )


class CloudflareCreateSecondaryDNSPeerConfig(BaseModel):
    """Create a secondary DNS peer"""

    operation: Literal["create_secondary_dns_peer"] = Field(
        default="create_secondary_dns_peer",
        title="Create Secondary DNS Peer",
        json_schema_extra={
            "x-category": "DNS",
            "x-is-trigger": False,
            "x-display-name": "Create Secondary DNS Peer",
            "ui:hidden": True,
        },
    )
    peer_name: str = Field(description="Name of the peer nameserver")
    peer_ip: str = Field(description="IP address of the peer nameserver")
    port: Optional[int] = Field(default=53, description="Port for zone transfers (default 53)")
    ixfr_enabled: Optional[str] = Field(
        default="false",
        description="Enable IXFR for incremental zone transfers",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareGetSecondaryDNSPeerConfig(BaseModel):
    """Get a secondary DNS peer"""

    operation: Literal["get_secondary_dns_peer"] = Field(
        default="get_secondary_dns_peer",
        title="Get Secondary DNS Peer",
        json_schema_extra={
            "x-category": "DNS",
            "x-is-trigger": False,
            "x-display-name": "Get Secondary DNS Peer",
            "ui:hidden": True,
        },
    )
    peer_id: str = Field(description="The secondary DNS peer ID")


class CloudflareUpdateSecondaryDNSPeerConfig(BaseModel):
    """Update a secondary DNS peer"""

    operation: Literal["update_secondary_dns_peer"] = Field(
        default="update_secondary_dns_peer",
        title="Update Secondary DNS Peer",
        json_schema_extra={
            "x-category": "DNS",
            "x-is-trigger": False,
            "x-display-name": "Update Secondary DNS Peer",
            "ui:hidden": True,
        },
    )
    peer_id: str = Field(description="The secondary DNS peer ID")
    peer_name: Optional[str] = Field(default=None, description="Name of the peer nameserver")
    peer_ip: Optional[str] = Field(default=None, description="IP address of the peer nameserver")
    port: Optional[int] = Field(default=None, description="Port for zone transfers")
    ixfr_enabled: Optional[str] = Field(
        default=None,
        description="Enable IXFR for incremental zone transfers",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareDeleteSecondaryDNSPeerConfig(BaseModel):
    """Delete a secondary DNS peer"""

    operation: Literal["delete_secondary_dns_peer"] = Field(
        default="delete_secondary_dns_peer",
        title="Delete Secondary DNS Peer",
        json_schema_extra={
            "x-category": "DNS",
            "x-is-trigger": False,
            "x-display-name": "Delete Secondary DNS Peer",
            "ui:hidden": True,
        },
    )
    peer_id: str = Field(description="The secondary DNS peer ID to delete")


# ─── Workers Analytics Engine Config Models ────────────────────────────────────


class CloudflareQueryAnalyticsEngineConfig(BaseModel):
    """Query Workers Analytics Engine with SQL"""

    operation: Literal["query_analytics_engine"] = Field(
        default="query_analytics_engine",
        title="Query Analytics Engine",
        json_schema_extra={
            "x-category": "Workers",
            "x-is-trigger": False,
            "x-display-name": "Query Analytics Engine",
            "ui:hidden": True,
        },
    )
    sql_query: str = Field(
        description="SQL query for Workers Analytics Engine e.g. SELECT blob1, count() FROM my_dataset GROUP BY blob1 LIMIT 10",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 4},
    )
    dataset_name: Optional[str] = Field(
        default=None,
        description="Dataset name hint (also specify in SQL)",
    )


# ─── Regional Tiered Cache Config Models ──────────────────────────────────────


class CloudflareGetRegionalTieredCacheConfig(BaseModel):
    """Get regional tiered cache setting for a zone"""

    operation: Literal["get_regional_tiered_cache"] = Field(
        default="get_regional_tiered_cache",
        title="Get Regional Tiered Cache",
        json_schema_extra={
            "x-category": "Zone",
            "x-is-trigger": False,
            "x-display-name": "Get Regional Tiered Cache",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareUpdateRegionalTieredCacheConfig(BaseModel):
    """Enable or disable regional tiered cache for a zone"""

    operation: Literal["update_regional_tiered_cache"] = Field(
        default="update_regional_tiered_cache",
        title="Update Regional Tiered Cache",
        json_schema_extra={
            "x-category": "Zone",
            "x-is-trigger": False,
            "x-display-name": "Update Regional Tiered Cache",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    enabled: str = Field(
        description="Enable or disable regional tiered cache",
        json_schema_extra={"enum": ["on", "off"], "x-enum-searchable": True},
    )


# ─── Vectorize Extended Config Models ─────────────────────────────────────────


class CloudflareGetVectorizeIndexInfoConfig(BaseModel):
    """Get Vectorize index stats and info"""

    operation: Literal["get_vectorize_index_info"] = Field(
        default="get_vectorize_index_info",
        title="Get Vectorize Index Info",
        json_schema_extra={
            "x-category": "Vectorize",
            "x-is-trigger": False,
            "x-display-name": "Get Vectorize Index Info",
            "ui:hidden": True,
        },
    )
    index_name: str = Field(description="The Vectorize index name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "index_name",
            "placeholder": "Select a Vectorize index...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareListVectorizeMetadataIndexesConfig(BaseModel):
    """List metadata indexes for a Vectorize index"""

    operation: Literal["list_vectorize_metadata_indexes"] = Field(
        default="list_vectorize_metadata_indexes",
        title="List Vectorize Metadata Indexes",
        json_schema_extra={
            "x-category": "Vectorize",
            "x-is-trigger": False,
            "x-display-name": "List Vectorize Metadata Indexes",
            "ui:hidden": True,
        },
    )
    index_name: str = Field(description="The Vectorize index name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "index_name",
            "placeholder": "Select a Vectorize index...",
            "searchable": True,
            "allow_custom": True,
        }
    })


class CloudflareCreateVectorizeMetadataIndexConfig(BaseModel):
    """Create a metadata index for a Vectorize index"""

    operation: Literal["create_vectorize_metadata_index"] = Field(
        default="create_vectorize_metadata_index",
        title="Create Vectorize Metadata Index",
        json_schema_extra={
            "x-category": "Vectorize",
            "x-is-trigger": False,
            "x-display-name": "Create Vectorize Metadata Index",
            "ui:hidden": True,
        },
    )
    index_name: str = Field(description="The Vectorize index name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "index_name",
            "placeholder": "Select a Vectorize index...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    property_name: str = Field(description="Metadata property to index for filtering")
    index_type: str = Field(
        description="Type of the metadata index",
        json_schema_extra={"enum": ["number", "string"], "x-enum-searchable": True},
    )


class CloudflareDeleteVectorizeMetadataIndexConfig(BaseModel):
    """Delete a metadata index from a Vectorize index"""

    operation: Literal["delete_vectorize_metadata_index"] = Field(
        default="delete_vectorize_metadata_index",
        title="Delete Vectorize Metadata Index",
        json_schema_extra={
            "x-category": "Vectorize",
            "x-is-trigger": False,
            "x-display-name": "Delete Vectorize Metadata Index",
            "ui:hidden": True,
        },
    )
    index_name: str = Field(description="The Vectorize index name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "index_name",
            "placeholder": "Select a Vectorize index...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    property_name: str = Field(description="Metadata property name to remove from indexing")


class CloudflareGetVectorizeVectorsByIdsConfig(BaseModel):
    """Retrieve vectors by their IDs from a Vectorize index"""

    operation: Literal["get_vectorize_vectors_by_ids"] = Field(
        default="get_vectorize_vectors_by_ids",
        title="Get Vectorize Vectors By IDs",
        json_schema_extra={
            "x-category": "Vectorize",
            "x-is-trigger": False,
            "x-display-name": "Get Vectorize Vectors By IDs",
            "ui:hidden": True,
        },
    )
    index_name: str = Field(description="The Vectorize index name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "index_name",
            "placeholder": "Select a Vectorize index...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    vector_ids: str = Field(description="Comma-separated vector IDs to retrieve")


class CloudflareGetFontsSettingsConfig(BaseModel):
    """Get Cloudflare Fonts settings for a zone"""

    operation: Literal["get_fonts_settings"] = Field(
        default="get_fonts_settings",
        title="Get Fonts Settings",
        json_schema_extra={
            "x-category": "Fonts",
            "x-is-trigger": False,
            "x-display-name": "Get Fonts Settings",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareUpdateFontsSettingsConfig(BaseModel):
    """Update Cloudflare Fonts settings for a zone"""

    operation: Literal["update_fonts_settings"] = Field(
        default="update_fonts_settings",
        title="Update Fonts Settings",
        json_schema_extra={
            "x-category": "Fonts",
            "x-is-trigger": False,
            "x-display-name": "Update Fonts Settings",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    fonts_enabled: str = Field(
        default="on",
        description="Replace Google Fonts with Cloudflare Fonts",
        json_schema_extra={"enum": ["on", "off"], "x-enum-searchable": True},
    )


class CloudflareGetNELSettingsConfig(BaseModel):
    """Get Network Error Logging settings for a zone"""

    operation: Literal["get_nel_settings"] = Field(
        default="get_nel_settings",
        title="Get NEL Settings",
        json_schema_extra={
            "x-category": "Security",
            "x-is-trigger": False,
            "x-display-name": "Get NEL Settings",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareUpdateNELSettingsConfig(BaseModel):
    """Update Network Error Logging settings for a zone"""

    operation: Literal["update_nel_settings"] = Field(
        default="update_nel_settings",
        title="Update NEL Settings",
        json_schema_extra={
            "x-category": "Security",
            "x-is-trigger": False,
            "x-display-name": "Update NEL Settings",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    nel_enabled: Optional[str] = Field(
        default=None,
        description="Enable or disable Network Error Logging",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


class CloudflareGetAPIShieldSettingsConfig(BaseModel):
    """Get API Shield configuration for a zone"""

    operation: Literal["get_api_shield_settings"] = Field(
        default="get_api_shield_settings",
        title="Get API Shield Settings",
        json_schema_extra={
            "x-category": "API Shield",
            "x-is-trigger": False,
            "x-display-name": "Get API Shield Settings",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareUpdateAPIShieldSettingsConfig(BaseModel):
    """Update API Shield configuration for a zone"""

    operation: Literal["update_api_shield_settings"] = Field(
        default="update_api_shield_settings",
        title="Update API Shield Settings",
        json_schema_extra={
            "x-category": "API Shield",
            "x-is-trigger": False,
            "x-display-name": "Update API Shield Settings",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    auth_header_name: Optional[str] = Field(
        default=None,
        description="Header used for auth ID e.g. Authorization, X-API-Key",
    )
    auth_header_type: Optional[str] = Field(
        default="header",
        description="Type of the auth ID characteristic",
        json_schema_extra={
            "enum": ["header", "jwt", "session_cookie"],
            "x-enum-searchable": True,
        },
    )


class CloudflareListAPIShieldEndpointsConfig(BaseModel):
    """List API Shield endpoints (operations) for a zone"""

    operation: Literal["list_api_shield_endpoints"] = Field(
        default="list_api_shield_endpoints",
        title="List API Shield Endpoints",
        json_schema_extra={
            "x-category": "API Shield",
            "x-is-trigger": False,
            "x-display-name": "List API Shield Endpoints",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    host_filter: Optional[str] = Field(
        default=None, description="Filter by host"
    )
    per_page: Optional[int] = Field(default=25, description="Number of results per page")


class CloudflareCreateAPIShieldEndpointConfig(BaseModel):
    """Create an API Shield endpoint (operation) for a zone"""

    operation: Literal["create_api_shield_endpoint"] = Field(
        default="create_api_shield_endpoint",
        title="Create API Shield Endpoint",
        json_schema_extra={
            "x-category": "API Shield",
            "x-is-trigger": False,
            "x-display-name": "Create API Shield Endpoint",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    method: str = Field(
        description="HTTP method of the endpoint",
        json_schema_extra={
            "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
            "x-enum-searchable": True,
        },
    )
    host: str = Field(description="e.g. api.example.com")
    endpoint: str = Field(description="URL path e.g. /users/{id}")


class CloudflareGetWAFPackageConfig(BaseModel):
    """Get a specific WAF package for a zone"""

    operation: Literal["get_waf_package"] = Field(
        default="get_waf_package",
        title="Get WAF Package",
        json_schema_extra={
            "x-category": "WAF",
            "x-is-trigger": False,
            "x-display-name": "Get WAF Package",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    package_id: str = Field(description="The WAF package ID")


class CloudflareListWAFPackageRuleGroupsConfig(BaseModel):
    """List rule groups in a WAF package"""

    operation: Literal["list_waf_package_rule_groups"] = Field(
        default="list_waf_package_rule_groups",
        title="List WAF Package Rule Groups",
        json_schema_extra={
            "x-category": "WAF",
            "x-is-trigger": False,
            "x-display-name": "List WAF Package Rule Groups",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    package_id: str = Field(description="The WAF package ID")
    per_page: Optional[int] = Field(default=50, description="Number of results per page")


class CloudflareListWAFPackageRulesConfig(BaseModel):
    """List rules in a WAF package"""

    operation: Literal["list_waf_package_rules"] = Field(
        default="list_waf_package_rules",
        title="List WAF Package Rules",
        json_schema_extra={
            "x-category": "WAF",
            "x-is-trigger": False,
            "x-display-name": "List WAF Package Rules",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    package_id: str = Field(description="The WAF package ID")
    per_page: Optional[int] = Field(default=50, description="Number of results per page")


class CloudflareUpdateWAFRuleConfig(BaseModel):
    """Update the mode of a WAF rule"""

    operation: Literal["update_waf_rule"] = Field(
        default="update_waf_rule",
        title="Update WAF Rule",
        json_schema_extra={
            "x-category": "WAF",
            "x-is-trigger": False,
            "x-display-name": "Update WAF Rule",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    package_id: str = Field(description="The WAF package ID")
    rule_id: str = Field(description="The WAF rule ID")
    mode: str = Field(
        description="Mode to set for the WAF rule",
        json_schema_extra={
            "enum": ["on", "off", "default", "block", "challenge", "simulate", "disable"],
            "x-enum-searchable": True,
        },
    )


class CloudflareGetEarlyHintsSettingConfig(BaseModel):
    """Get Early Hints setting for a zone"""

    operation: Literal["get_early_hints_setting"] = Field(
        default="get_early_hints_setting",
        title="Get Early Hints Setting",
        json_schema_extra={
            "x-category": "Zone",
            "x-is-trigger": False,
            "x-display-name": "Get Early Hints Setting",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareUpdateEarlyHintsSettingConfig(BaseModel):
    """Update Early Hints setting for a zone"""

    operation: Literal["update_early_hints_setting"] = Field(
        default="update_early_hints_setting",
        title="Update Early Hints Setting",
        json_schema_extra={
            "x-category": "Zone",
            "x-is-trigger": False,
            "x-display-name": "Update Early Hints Setting",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    enabled: str = Field(
        default="on",
        description="Enable or disable Early Hints",
        json_schema_extra={"enum": ["on", "off"], "x-enum-searchable": True},
    )


class CloudflareGetHTTP3SettingConfig(BaseModel):
    """Get HTTP/3 setting for a zone"""

    operation: Literal["get_http3_setting"] = Field(
        default="get_http3_setting",
        title="Get HTTP/3 Setting",
        json_schema_extra={
            "x-category": "Zone",
            "x-is-trigger": False,
            "x-display-name": "Get HTTP/3 Setting",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareUpdateHTTP3SettingConfig(BaseModel):
    """Update HTTP/3 setting for a zone"""

    operation: Literal["update_http3_setting"] = Field(
        default="update_http3_setting",
        title="Update HTTP/3 Setting",
        json_schema_extra={
            "x-category": "Zone",
            "x-is-trigger": False,
            "x-display-name": "Update HTTP/3 Setting",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    enabled: str = Field(
        default="on",
        description="Enable or disable HTTP/3",
        json_schema_extra={"enum": ["on", "off"], "x-enum-searchable": True},
    )


class CloudflareGetBrotliSettingConfig(BaseModel):
    """Get Brotli compression setting for a zone"""

    operation: Literal["get_brotli_setting"] = Field(
        default="get_brotli_setting",
        title="Get Brotli Setting",
        json_schema_extra={
            "x-category": "Zone",
            "x-is-trigger": False,
            "x-display-name": "Get Brotli Setting",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })


class CloudflareUpdateBrotliSettingConfig(BaseModel):
    """Update Brotli compression setting for a zone"""

    operation: Literal["update_brotli_setting"] = Field(
        default="update_brotli_setting",
        title="Update Brotli Setting",
        json_schema_extra={
            "x-category": "Zone",
            "x-is-trigger": False,
            "x-display-name": "Update Brotli Setting",
            "ui:hidden": True,
        },
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    enabled: str = Field(
        default="on",
        description="Enable or disable Brotli compression",
        json_schema_extra={"enum": ["on", "off"], "x-enum-searchable": True},
    )


# ─── R2 and Queue Trigger Extensions ──────────────────────────────────────────


class CloudflareR2ObjectEventTriggerConfig(PollTriggerConfigBase):
    """Trigger: fires when R2 bucket object events arrive in a Cloudflare Queue"""

    operation: Literal["cloudflare_r2_object_event"] = Field(
        default="cloudflare_r2_object_event",
        title="On R2 Object Event (via Queue)",
        json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On R2 Object Event (via Queue)", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Your Cloudflare Account ID", json_schema_extra={"ui:hidden": True})
    queue_id: str = Field(description="Queue ID receiving R2 event notifications. Set up the bucket's event notification rules in the Cloudflare dashboard first.", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "queue_id",
            "placeholder": "Select a Queue...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    bucket_name_filter: Optional[str] = Field(default=None, description="Only trigger for events from this R2 bucket name (leave blank to match all buckets in the queue)")
    event_type_filter: Optional[str] = Field(
        default=None,
        description="Filter by R2 event action type",
        json_schema_extra={
            "enum": ["PutObject", "CopyObject", "DeleteObject", "CompleteMultipartUpload", "LifecycleDeletion"],
            "x-enum-searchable": True,
        },
    )
    key_prefix_filter: Optional[str] = Field(default=None, description="Only trigger for object keys starting with this prefix (e.g. uploads/)")
    batch_size: Optional[int] = Field(default=10, description="Number of queue messages to pull per poll (1-100)")


class CloudflareQueueDeliveryEventTriggerConfig(PollTriggerConfigBase):
    """Trigger: polls a Cloudflare Queue for messages and emits each batch"""

    operation: Literal["cloudflare_queue_delivery_event"] = Field(
        default="cloudflare_queue_delivery_event",
        title="On Queue Delivery Event",
        json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Queue Delivery Event", "ui:hidden": True},
    )
    queue_id: str = Field(description="Queue ID to poll for delivery events", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "queue_id",
            "placeholder": "Select a Queue...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    batch_size: Optional[int] = Field(default=10, description="Number of messages to pull per poll batch (1-100)")
    visibility_timeout_ms: Optional[int] = Field(default=30000, description="Visibility timeout in milliseconds")
    body_contains_filter: Optional[str] = Field(default=None, description="Only emit messages whose body (JSON-serialized) contains this string")


class CloudflareDDoSAlertTriggerConfig(WebhookTriggerConfigBase):
    """Trigger: fires when Cloudflare detects a DDoS attack (L4 or L7)"""

    operation: Literal["cloudflare_ddos_alert"] = Field(
        default="cloudflare_ddos_alert",
        title="On DDoS Attack Alert",
        json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On DDoS Attack Alert", "ui:hidden": True},
    )
    webhook_url: Optional[str] = Field(default=None, json_schema_extra={"ui:widget": "webhook", "ui:loadValue": True})
    ddos_layer: str = Field(
        description="DDoS protection layer to monitor",
        json_schema_extra={"enum": ["dos_attack_l7", "dos_attack_l4"], "enumNames": ["L7 (HTTP)", "L4 (Network)"], "x-enum-searchable": True},
    )
    policy_name: Optional[str] = Field(default=None, description="Name for the Cloudflare alert policy (defaults to 'NoClick - DDoS {layer}')")
    cf_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    cf_policy_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


class CloudflareSSLAlertTriggerConfig(WebhookTriggerConfigBase):
    """Trigger: fires when an SSL/TLS certificate event occurs (expiry, renewal, issuance failure)"""

    operation: Literal["cloudflare_ssl_alert"] = Field(
        default="cloudflare_ssl_alert",
        title="On SSL/TLS Certificate Alert",
        json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On SSL/TLS Certificate Alert", "ui:hidden": True},
    )
    webhook_url: Optional[str] = Field(default=None, json_schema_extra={"ui:widget": "webhook", "ui:loadValue": True})
    ssl_alert_type: str = Field(
        description="SSL/TLS certificate event type to monitor",
        json_schema_extra={
            "enum": [
                "universal_ssl_event_type", "advanced_certificate_alert", "dedicated_ssl_certificate_event_type",
                "custom_ssl_certificate_event_type", "mtls_certificate_store_certificate_expiration_type",
                "hostname_aop_custom_certificate_expiration_type", "zone_aop_custom_certificate_expiration_type",
            ],
            "enumNames": [
                "Universal SSL (expiry/issuance)", "Advanced Certificate (expiry/renewal)",
                "Dedicated SSL Certificate event", "Custom SSL Certificate event",
                "mTLS Certificate Store expiration", "Hostname AOP custom certificate expiration",
                "Zone AOP custom certificate expiration",
            ],
            "x-enum-searchable": True,
        },
    )
    policy_name: Optional[str] = Field(default=None, description="Name for the Cloudflare alert policy")
    cf_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    cf_policy_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


class CloudflareTunnelAlertTriggerConfig(WebhookTriggerConfigBase):
    """Trigger: fires when a Cloudflare Tunnel changes health status or is created/deleted"""

    operation: Literal["cloudflare_tunnel_alert"] = Field(
        default="cloudflare_tunnel_alert",
        title="On Tunnel Health/Event Alert",
        json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Tunnel Health/Event Alert", "ui:hidden": True},
    )
    webhook_url: Optional[str] = Field(default=None, json_schema_extra={"ui:widget": "webhook", "ui:loadValue": True})
    tunnel_alert_type: str = Field(
        description="Tunnel alert type to monitor",
        json_schema_extra={
            "enum": ["tunnel_health_event", "tunnel_update_event"],
            "enumNames": ["Tunnel health change", "Tunnel created/deleted"],
            "x-enum-searchable": True,
        },
    )
    policy_name: Optional[str] = Field(default=None, description="Name for the Cloudflare alert policy")
    cf_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    cf_policy_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


class CloudflareWorkerAlertTriggerConfig(WebhookTriggerConfigBase):
    """Trigger: fires when a Cloudflare Worker exceeds error rate thresholds or usage limits"""

    operation: Literal["cloudflare_worker_alert"] = Field(
        default="cloudflare_worker_alert",
        title="On Workers Error/Usage Alert",
        json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Workers Error/Usage Alert", "ui:hidden": True},
    )
    webhook_url: Optional[str] = Field(default=None, json_schema_extra={"ui:widget": "webhook", "ui:loadValue": True})
    worker_alert_type: str = Field(
        description="Worker alert type to monitor",
        json_schema_extra={
            "enum": [
                "http_alert_edge_error", "http_alert_origin_error", "advanced_http_alert_error",
                "traffic_anomalies_alert", "billing_usage_alert", "failing_logpush_job_disabled_alert",
            ],
            "enumNames": [
                "HTTP edge error rate", "HTTP origin error rate", "Advanced HTTP error rate",
                "Traffic anomaly", "Billing / usage-based alert", "Logpush job disabled",
            ],
            "x-enum-searchable": True,
        },
    )
    policy_name: Optional[str] = Field(default=None, description="Name for the Cloudflare alert policy")
    cf_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    cf_policy_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


class CloudflareLoadBalancerAlertTriggerConfig(WebhookTriggerConfigBase):
    """Trigger: fires when a Cloudflare Load Balancer pool health changes or is enabled/disabled."""

    operation: Literal["cloudflare_load_balancer_alert"] = Field(
        default="cloudflare_load_balancer_alert",
        title="On Load Balancer Health Change",
        json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Load Balancer Health Change", "ui:hidden": True},
    )
    webhook_url: Optional[str] = Field(default=None, json_schema_extra={"ui:widget": "webhook", "ui:loadValue": True})
    lb_alert_type: str = Field(
        description="Load balancer alert type to monitor",
        json_schema_extra={
            "enum": ["load_balancing_health_alert", "load_balancing_pool_enablement_alert"],
            "enumNames": ["Pool health change", "Pool enabled/disabled"],
            "x-enum-searchable": True,
        },
    )
    policy_name: Optional[str] = Field(default=None, description="Name for the Cloudflare alert policy")
    cf_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    cf_policy_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


class CloudflareWaitingRoomAlertTriggerConfig(WebhookTriggerConfigBase):
    """Trigger: fires when a Cloudflare Waiting Room is activated or deactivated."""

    operation: Literal["cloudflare_waiting_room_alert"] = Field(
        default="cloudflare_waiting_room_alert",
        title="On Waiting Room Event",
        json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Waiting Room Event", "ui:hidden": True},
    )
    webhook_url: Optional[str] = Field(default=None, json_schema_extra={"ui:widget": "webhook", "ui:loadValue": True})
    waiting_room_alert_type: str = Field(
        description="Waiting room alert type to monitor",
        json_schema_extra={
            "enum": ["waiting_room_events_alert"],
            "enumNames": ["Waiting room activated/deactivated"],
            "x-enum-searchable": True,
        },
    )
    policy_name: Optional[str] = Field(default=None, description="Name for the Cloudflare alert policy")
    cf_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    cf_policy_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


class CloudflarePageShieldAlertTriggerConfig(WebhookTriggerConfigBase):
    """Trigger: fires when Cloudflare Page Shield detects a malicious script or URL."""

    operation: Literal["cloudflare_page_shield_alert"] = Field(
        default="cloudflare_page_shield_alert",
        title="On Page Shield Alert",
        json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Page Shield Alert", "ui:hidden": True},
    )
    webhook_url: Optional[str] = Field(default=None, json_schema_extra={"ui:widget": "webhook", "ui:loadValue": True})
    page_shield_alert_type: str = Field(
        description="Page Shield / Script Monitor alert type to monitor",
        json_schema_extra={
            "enum": [
                "scriptmonitor_alert_new_malicious_scripts",
                "scriptmonitor_alert_new_malicious_url",
                "scriptmonitor_alert_new_malicious_hosts",
                "scriptmonitor_alert_new_hosts",
                "scriptmonitor_alert_new_resources",
                "scriptmonitor_alert_new_code_change_detections",
                "scriptmonitor_alert_new_max_length_resource_url",
            ],
            "enumNames": [
                "New malicious script", "New malicious URL", "New malicious host",
                "New script host", "New resource detected", "Code change detected",
                "New max-length resource URL",
            ],
            "x-enum-searchable": True,
        },
    )
    policy_name: Optional[str] = Field(default=None, description="Name for the Cloudflare alert policy")
    cf_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    cf_policy_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


class CloudflareZeroTrustAlertTriggerConfig(WebhookTriggerConfigBase):
    """Trigger: fires on Zero Trust Gateway activity log, blocked request, or Access custom pages events."""

    operation: Literal["cloudflare_zero_trust_alert"] = Field(
        default="cloudflare_zero_trust_alert",
        title="On Zero Trust Gateway Alert",
        json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Zero Trust Gateway Alert", "ui:hidden": True},
    )
    webhook_url: Optional[str] = Field(default=None, json_schema_extra={"ui:widget": "webhook", "ui:loadValue": True})
    zt_alert_type: str = Field(
        description="Zero Trust alert type to monitor",
        json_schema_extra={
            "enum": ["gateway_activity_log_alert", "gateway_blocked_request_alert", "access_custom_pages_alert"],
            "enumNames": ["Gateway activity log", "Gateway blocked request", "Access custom pages event"],
            "x-enum-searchable": True,
        },
    )
    policy_name: Optional[str] = Field(default=None, description="Name for the Cloudflare alert policy")
    cf_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    cf_policy_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


class CloudflareEmailRoutingAlertTriggerConfig(WebhookTriggerConfigBase):
    """Trigger: fires when a Cloudflare Email Routing incident occurs."""

    operation: Literal["cloudflare_email_routing_alert"] = Field(
        default="cloudflare_email_routing_alert",
        title="On Email Routing Incident",
        json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Email Routing Incident", "ui:hidden": True},
    )
    webhook_url: Optional[str] = Field(default=None, json_schema_extra={"ui:widget": "webhook", "ui:loadValue": True})
    email_alert_type: str = Field(
        description="Email routing alert type to monitor",
        json_schema_extra={
            "enum": ["email_routing_incident_alerts"],
            "enumNames": ["Email routing incident"],
            "x-enum-searchable": True,
        },
    )
    policy_name: Optional[str] = Field(default=None, description="Name for the Cloudflare alert policy")
    cf_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    cf_policy_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


class CloudflareMagicTransitAlertTriggerConfig(WebhookTriggerConfigBase):
    """Trigger: fires on Magic Transit / Magic WAN tunnel health changes or BGP hijack detection."""

    operation: Literal["cloudflare_magic_transit_alert"] = Field(
        default="cloudflare_magic_transit_alert",
        title="On Magic Transit / BGP Alert",
        json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Magic Transit / BGP Alert", "ui:hidden": True},
    )
    webhook_url: Optional[str] = Field(default=None, json_schema_extra={"ui:widget": "webhook", "ui:loadValue": True})
    mt_alert_type: str = Field(
        description="Magic Transit / BGP alert type to monitor",
        json_schema_extra={
            "enum": ["bgp_hijack_notification", "magic_transit_health_alert", "magic_tunnel_health_alert"],
            "enumNames": ["BGP hijack detected", "Magic Transit tunnel health", "Magic WAN tunnel health"],
            "x-enum-searchable": True,
        },
    )
    policy_name: Optional[str] = Field(default=None, description="Name for the Cloudflare alert policy")
    cf_webhook_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})
    cf_policy_id: Optional[str] = Field(default=None, json_schema_extra={"ui:hidden": True})


class CloudflareWorkerDeployedTriggerConfig(PollTriggerConfigBase):
    """Trigger: fires when a Workers script is deployed (new version / etag detected)."""

    operation: Literal["cloudflare_worker_deployed"] = Field(
        default="cloudflare_worker_deployed",
        title="On Workers Script Deployed",
        json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On Workers Script Deployed", "ui:hidden": True},
    )
    script_name_filter: Optional[str] = Field(
        default=None,
        description="Only trigger for this specific worker script name. Leave blank for any script.",
    )


class CloudflareD1NewRowsTriggerConfig(PollTriggerConfigBase):
    """Trigger: fires when new rows appear in a D1 database table."""

    operation: Literal["cloudflare_d1_new_rows"] = Field(
        default="cloudflare_d1_new_rows",
        title="On New D1 Database Rows",
        json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On New D1 Database Rows", "ui:hidden": True},
    )
    database_id: str = Field(description="D1 database ID to query")
    query: str = Field(
        default="SELECT * FROM {table} ORDER BY rowid DESC LIMIT 100",
        description="SQL query to detect new rows. Use {table} as a placeholder for the table name.",
    )
    table_name: Optional[str] = Field(default=None, description="Table name to substitute into the query template")


class CloudflareKVKeyUpdatedTriggerConfig(PollTriggerConfigBase):
    """Trigger: fires when keys are added or updated in a KV namespace."""

    operation: Literal["cloudflare_kv_key_updated"] = Field(
        default="cloudflare_kv_key_updated",
        title="On KV Namespace Key Updated",
        json_schema_extra={"x-category": "Triggers", "x-is-trigger": True, "x-display-name": "On KV Namespace Key Updated", "ui:hidden": True},
    )
    namespace_id: str = Field(description="KV namespace ID to monitor")
    prefix: Optional[str] = Field(default=None, description="Only monitor keys with this prefix")


# ─── Main Node Config Union ────────────────────────────────────────────────────


# ===== Restored implemented operation families (Intel, Magic Transit, Calls,
# Analytics Engine SQL, Log Explorer/Logpull/CMB, Addressing/BYOIP, Radar AI,
# URL Scanner, Bot Management, Workers AI, R2 Event Notifications) =====
class CloudflareGetIntelASNConfig(BaseModel):
    """Get overview and subnet list for an Autonomous System Number"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["get_intel_asn"] = Field(
        default="get_intel_asn",
        title="Get ASN Overview",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "Get ASN Overview", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    asn: str = Field(description="The Autonomous System Number to look up")

class CloudflareGetIntelASNSubnetsConfig(BaseModel):
    """Get all subnets associated with an ASN"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["get_intel_asn_subnets"] = Field(
        default="get_intel_asn_subnets",
        title="Get ASN Subnets",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "Get ASN Subnets", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    asn: str = Field(description="The Autonomous System Number to retrieve subnets for")

class CloudflareGetIntelDNSConfig(BaseModel):
    """Perform a passive DNS lookup by IP address"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["get_intel_dns"] = Field(
        default="get_intel_dns",
        title="Passive DNS Lookup",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "Passive DNS Lookup", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    ipv4: Optional[str] = Field(default=None, description="IPv4 address to look up")
    page: Optional[str] = Field(default=None, description="Page number for pagination")
    per_page: Optional[str] = Field(default=None, description="Number of results per page")

class CloudflareGetIntelDomainConfig(BaseModel):
    """Get security details, threat categories, and statistics for a domain"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["get_intel_domain"] = Field(
        default="get_intel_domain",
        title="Get Domain Intelligence",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "Get Domain Intelligence", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    domain: str = Field(description="The domain to retrieve intelligence for")
    skip_dns: Optional[str] = Field(
        default=None,
        description="Skip DNS resolution in the lookup",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    skip_ranking: Optional[str] = Field(
        default=None,
        description="Skip popularity ranking data",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )

class CloudflareGetIntelDomainBulkConfig(BaseModel):
    """Get intelligence details for multiple domains in a single request"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["get_intel_domain_bulk"] = Field(
        default="get_intel_domain_bulk",
        title="Bulk Domain Intelligence",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "Bulk Domain Intelligence", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    domain: str = Field(description="Comma-separated list of domains to look up")
    include_ranking: Optional[str] = Field(
        default=None,
        description="Include popularity ranking data",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )

class CloudflareGetIntelDomainHistoryConfig(BaseModel):
    """Get historical categorizations for a domain over time"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["get_intel_domain_history"] = Field(
        default="get_intel_domain_history",
        title="Get Domain History",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "Get Domain History", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    domain: str = Field(description="The domain to retrieve historical categorization data for")

class CloudflareGetIntelIPConfig(BaseModel):
    """Get geolocation, ASN, infrastructure type, and threat categories for an IP"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["get_intel_ip"] = Field(
        default="get_intel_ip",
        title="Get IP Intelligence",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "Get IP Intelligence", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    ipv4: Optional[str] = Field(default=None, description="IPv4 address to look up")
    ipv6: Optional[str] = Field(default=None, description="IPv6 address to look up")

class CloudflareGetIntelWHOISConfig(BaseModel):
    """Get WHOIS registration data and nameserver information for a domain"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["get_intel_whois"] = Field(
        default="get_intel_whois",
        title="WHOIS Lookup",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "WHOIS Lookup", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    domain: str = Field(description="The domain to retrieve WHOIS data for")

class CloudflareCreateIntelMiscategorizationConfig(BaseModel):
    """Submit a request to change the category of a domain or IP address"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["create_intel_miscategorization"] = Field(
        default="create_intel_miscategorization",
        title="Submit Miscategorization",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "Submit Miscategorization", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    indicator_type: str = Field(
        description="Type of indicator being reported",
        json_schema_extra={"enum": ["domain", "ip"], "enumNames": ["Domain", "IP Address"], "x-enum-searchable": True},
    )
    url: Optional[str] = Field(default=None, description="The domain URL to recategorize")
    ip: Optional[str] = Field(default=None, description="The IP address to recategorize")
    content_adds: Optional[str] = Field(default=None, description="Comma-separated category IDs to add as content categories")
    content_removes: Optional[str] = Field(default=None, description="Comma-separated category IDs to remove from content categories")
    security_adds: Optional[str] = Field(default=None, description="Comma-separated category IDs to add as security categories")
    security_removes: Optional[str] = Field(default=None, description="Comma-separated category IDs to remove from security categories")

class CloudflareListIntelIndicatorFeedsConfig(BaseModel):
    """List all custom threat intelligence indicator feeds accessible to the account"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["list_intel_indicator_feeds"] = Field(
        default="list_intel_indicator_feeds",
        title="List Indicator Feeds",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "List Indicator Feeds", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})

class CloudflareGetIntelIndicatorFeedConfig(BaseModel):
    """Get metadata and upload status for a specific indicator feed"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["get_intel_indicator_feed"] = Field(
        default="get_intel_indicator_feed",
        title="Get Indicator Feed",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "Get Indicator Feed", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    feed_id: str = Field(description="The indicator feed ID")

class CloudflareCreateIntelIndicatorFeedConfig(BaseModel):
    """Create a new custom threat intelligence indicator feed"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["create_intel_indicator_feed"] = Field(
        default="create_intel_indicator_feed",
        title="Create Indicator Feed",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "Create Indicator Feed", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    name: str = Field(description="Name for the new indicator feed")
    description: Optional[str] = Field(default=None, description="Description of the indicator feed")

class CloudflareUpdateIntelIndicatorFeedConfig(BaseModel):
    """Update metadata for an existing indicator feed"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["update_intel_indicator_feed"] = Field(
        default="update_intel_indicator_feed",
        title="Update Indicator Feed",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "Update Indicator Feed", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    feed_id: str = Field(description="The indicator feed ID to update")
    name: Optional[str] = Field(default=None, description="New name for the feed")
    description: Optional[str] = Field(default=None, description="New description for the feed")
    is_attributable: Optional[str] = Field(
        default=None,
        description="Whether the feed is attributable",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    is_downloadable: Optional[str] = Field(
        default=None,
        description="Whether the feed data can be downloaded",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    is_public: Optional[str] = Field(
        default=None,
        description="Whether the feed is publicly accessible",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )

class CloudflareGetIntelIndicatorFeedDataConfig(BaseModel):
    """Retrieve the raw data entries from an indicator feed"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["get_intel_indicator_feed_data"] = Field(
        default="get_intel_indicator_feed_data",
        title="Get Indicator Feed Data",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "Get Indicator Feed Data", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    feed_id: str = Field(description="The indicator feed ID")

class CloudflareListIntelFeedPermissionsConfig(BaseModel):
    """List all access permissions for indicator feeds"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["list_intel_feed_permissions"] = Field(
        default="list_intel_feed_permissions",
        title="List Feed Permissions",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "List Feed Permissions", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})

class CloudflareAddIntelFeedPermissionConfig(BaseModel):
    """Grant another account access to an indicator feed"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["add_intel_feed_permission"] = Field(
        default="add_intel_feed_permission",
        title="Add Feed Permission",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "Add Feed Permission", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    feed_id: str = Field(description="The indicator feed ID to grant access to")
    account_tag: str = Field(description="The account tag (ID) of the account to grant access")

class CloudflareRemoveIntelFeedPermissionConfig(BaseModel):
    """Revoke an account's access to an indicator feed"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["remove_intel_feed_permission"] = Field(
        default="remove_intel_feed_permission",
        title="Remove Feed Permission",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "Remove Feed Permission", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    feed_id: str = Field(description="The indicator feed ID to revoke access from")
    account_tag: str = Field(description="The account tag (ID) of the account to revoke access from")

class CloudflareListIntelSinkholesConfig(BaseModel):
    """List all sinkholes configured for malicious traffic redirection"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["list_intel_sinkholes"] = Field(
        default="list_intel_sinkholes",
        title="List Sinkholes",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "List Sinkholes", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})

class CloudflareListAttackSurfaceIssueTypesConfig(BaseModel):
    """List all available Security Center issue categories for attack surface reporting"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["list_attack_surface_issue_types"] = Field(
        default="list_attack_surface_issue_types",
        title="List Attack Surface Issue Types",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "List Attack Surface Issue Types", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})

class CloudflareListAttackSurfaceIssuesConfig(BaseModel):
    """List all active security issues identified in the attack surface report"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["list_attack_surface_issues"] = Field(
        default="list_attack_surface_issues",
        title="List Attack Surface Issues",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "List Attack Surface Issues", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    dismissed: Optional[str] = Field(
        default=None,
        description="Filter by dismissed status",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    issue_class: Optional[str] = Field(default=None, description="Filter by issue class")
    issue_type: Optional[str] = Field(default=None, description="Filter by issue type")
    severity: Optional[str] = Field(
        default=None,
        description="Filter by severity level",
        json_schema_extra={"enum": ["low", "medium", "high", "critical"], "enumNames": ["Low", "Medium", "High", "Critical"], "x-enum-searchable": True},
    )
    product: Optional[str] = Field(default=None, description="Filter by Cloudflare product")
    subject: Optional[str] = Field(default=None, description="Filter by subject (e.g. hostname or IP)")
    page: Optional[str] = Field(default=None, description="Page number for pagination")
    per_page: Optional[str] = Field(default=None, description="Number of results per page")

class CloudflareGetAttackSurfaceIssuesBySeverityConfig(BaseModel):
    """Get attack surface issue counts aggregated by severity level"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["get_attack_surface_issues_by_severity"] = Field(
        default="get_attack_surface_issues_by_severity",
        title="Get Issues by Severity",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "Get Issues by Severity", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    dismissed: Optional[str] = Field(
        default=None,
        description="Filter by dismissed status",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    issue_class: Optional[str] = Field(default=None, description="Filter by issue class")
    issue_type: Optional[str] = Field(default=None, description="Filter by issue type")
    product: Optional[str] = Field(default=None, description="Filter by Cloudflare product")
    subject: Optional[str] = Field(default=None, description="Filter by subject")

class CloudflareGetAttackSurfaceIssuesByTypeConfig(BaseModel):
    """Get attack surface issue counts aggregated by issue type"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["get_attack_surface_issues_by_type"] = Field(
        default="get_attack_surface_issues_by_type",
        title="Get Issues by Type",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "Get Issues by Type", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    dismissed: Optional[str] = Field(
        default=None,
        description="Filter by dismissed status",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    issue_class: Optional[str] = Field(default=None, description="Filter by issue class")
    severity: Optional[str] = Field(
        default=None,
        description="Filter by severity level",
        json_schema_extra={"enum": ["low", "medium", "high", "critical"], "enumNames": ["Low", "Medium", "High", "Critical"], "x-enum-searchable": True},
    )
    product: Optional[str] = Field(default=None, description="Filter by Cloudflare product")
    subject: Optional[str] = Field(default=None, description="Filter by subject")

class CloudflareDismissAttackSurfaceIssueConfig(BaseModel):
    """Dismiss or restore a Security Center issue in the attack surface report"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["dismiss_attack_surface_issue"] = Field(
        default="dismiss_attack_surface_issue",
        title="Dismiss Attack Surface Issue",
        json_schema_extra={"x-category": "Intel", "x-is-trigger": False, "x-display-name": "Dismiss Attack Surface Issue", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    issue_id: str = Field(description="The issue ID to dismiss or restore")
    dismiss: Optional[str] = Field(
        default="true",
        description="Set to true to dismiss, false to restore",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


# ─── Magic Transit Config Models ───────────────────────────────────────────────

class CloudflareListMagicGRETunnelsConfig(BaseModel):
    """List all GRE tunnels for a Magic Transit account"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["list_magic_gre_tunnels"] = Field(
        default="list_magic_gre_tunnels",
        title="List GRE Tunnels",
        json_schema_extra={"x-category": "Magic Transit", "x-is-trigger": False, "x-display-name": "List GRE Tunnels", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID (uses credential account_id if not provided)")

class CloudflareGetMagicGRETunnelConfig(BaseModel):
    """Get details for a specific Magic Transit GRE tunnel"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["get_magic_gre_tunnel"] = Field(
        default="get_magic_gre_tunnel",
        title="Get GRE Tunnel",
        json_schema_extra={"x-category": "Magic Transit", "x-is-trigger": False, "x-display-name": "Get GRE Tunnel", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID (uses credential account_id if not provided)")
    gre_tunnel_id: str = Field(description="GRE tunnel identifier")

class CloudflareCreateMagicGRETunnelConfig(BaseModel):
    """Create a new Magic Transit GRE tunnel"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["create_magic_gre_tunnel"] = Field(
        default="create_magic_gre_tunnel",
        title="Create GRE Tunnel",
        json_schema_extra={"x-category": "Magic Transit", "x-is-trigger": False, "x-display-name": "Create GRE Tunnel", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID (uses credential account_id if not provided)")
    name: str = Field(description="Tunnel name (max 15 characters, no spaces or special characters)")
    cloudflare_gre_endpoint: str = Field(description="IP address assigned to the Cloudflare side of the GRE tunnel")
    customer_gre_endpoint: str = Field(description="IP address assigned to the customer side of the GRE tunnel")
    interface_address: str = Field(description="A /31 CIDR prefix from a private IP range (e.g. 10.0.0.0/31)")
    description: Optional[str] = Field(default=None, description="Optional description for the tunnel")
    mtu: Optional[str] = Field(default=None, description="Maximum Transmission Unit in bytes (minimum 576)")
    ttl: Optional[str] = Field(default=None, description="Time To Live in hops")

class CloudflareUpdateMagicGRETunnelConfig(BaseModel):
    """Update an existing Magic Transit GRE tunnel"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["update_magic_gre_tunnel"] = Field(
        default="update_magic_gre_tunnel",
        title="Update GRE Tunnel",
        json_schema_extra={"x-category": "Magic Transit", "x-is-trigger": False, "x-display-name": "Update GRE Tunnel", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID (uses credential account_id if not provided)")
    gre_tunnel_id: str = Field(description="GRE tunnel identifier")
    name: str = Field(description="Tunnel name (max 15 characters, no spaces or special characters)")
    cloudflare_gre_endpoint: str = Field(description="IP address assigned to the Cloudflare side of the GRE tunnel")
    customer_gre_endpoint: str = Field(description="IP address assigned to the customer side of the GRE tunnel")
    interface_address: str = Field(description="A /31 CIDR prefix from a private IP range (e.g. 10.0.0.0/31)")
    description: Optional[str] = Field(default=None, description="Optional description for the tunnel")
    mtu: Optional[str] = Field(default=None, description="Maximum Transmission Unit in bytes (minimum 576)")
    ttl: Optional[str] = Field(default=None, description="Time To Live in hops")

class CloudflareDeleteMagicGRETunnelConfig(BaseModel):
    """Delete a Magic Transit GRE tunnel"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["delete_magic_gre_tunnel"] = Field(
        default="delete_magic_gre_tunnel",
        title="Delete GRE Tunnel",
        json_schema_extra={"x-category": "Magic Transit", "x-is-trigger": False, "x-display-name": "Delete GRE Tunnel", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID (uses credential account_id if not provided)")
    gre_tunnel_id: str = Field(description="GRE tunnel identifier to delete")

class CloudflareListMagicCFInterconnectsConfig(BaseModel):
    """List all Cloudflare network interconnects for Magic Transit"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["list_magic_cf_interconnects"] = Field(
        default="list_magic_cf_interconnects",
        title="List CF Interconnects",
        json_schema_extra={"x-category": "Magic Transit", "x-is-trigger": False, "x-display-name": "List CF Interconnects", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID (uses credential account_id if not provided)")

class CloudflareGetMagicCFInterconnectConfig(BaseModel):
    """Get details for a specific Cloudflare network interconnect"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["get_magic_cf_interconnect"] = Field(
        default="get_magic_cf_interconnect",
        title="Get CF Interconnect",
        json_schema_extra={"x-category": "Magic Transit", "x-is-trigger": False, "x-display-name": "Get CF Interconnect", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID (uses credential account_id if not provided)")
    cf_interconnect_id: str = Field(description="CF Interconnect identifier")

class CloudflareUpdateMagicCFInterconnectConfig(BaseModel):
    """Update a single Cloudflare network interconnect for Magic Transit"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["update_magic_cf_interconnect"] = Field(
        default="update_magic_cf_interconnect",
        title="Update CF Interconnect",
        json_schema_extra={"x-category": "Magic Transit", "x-is-trigger": False, "x-display-name": "Update CF Interconnect", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID (uses credential account_id if not provided)")
    cf_interconnect_id: str = Field(description="CF Interconnect identifier")
    name: Optional[str] = Field(default=None, description="Interconnect name (cannot share a name with other tunnels)")
    description: Optional[str] = Field(default=None, description="Optional description for the interconnect")
    interface_address: Optional[str] = Field(default=None, description="IPv4 address in /31 CIDR notation from a private range")
    mtu: Optional[str] = Field(default=None, description="Maximum Transmission Unit in bytes (minimum 576)")

class CloudflareListMagicAppsConfig(BaseModel):
    """List all Magic Transit apps for an account"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["list_magic_apps"] = Field(
        default="list_magic_apps",
        title="List Magic Transit Apps",
        json_schema_extra={"x-category": "Magic Transit", "x-is-trigger": False, "x-display-name": "List Magic Transit Apps", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID (uses credential account_id if not provided)")

class CloudflareCreateMagicAppConfig(BaseModel):
    """Create a new Magic Transit app for traffic routing decisions"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["create_magic_app"] = Field(
        default="create_magic_app",
        title="Create Magic Transit App",
        json_schema_extra={"x-category": "Magic Transit", "x-is-trigger": False, "x-display-name": "Create Magic Transit App", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID (uses credential account_id if not provided)")
    name: str = Field(description="Display name for the app")
    type: str = Field(description="Category of the app")
    hostnames: Optional[str] = Field(default=None, description="Comma-separated FQDNs to associate with traffic decisions")
    ip_subnets: Optional[str] = Field(default=None, description="Comma-separated IPv4 CIDR blocks to associate with traffic decisions")
    source_subnets: Optional[str] = Field(default=None, description="Comma-separated IPv4 CIDR source blocks for traffic decisions")

class CloudflareUpdateMagicAppConfig(BaseModel):
    """Update an existing Magic Transit app"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["update_magic_app"] = Field(
        default="update_magic_app",
        title="Update Magic Transit App",
        json_schema_extra={"x-category": "Magic Transit", "x-is-trigger": False, "x-display-name": "Update Magic Transit App", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID (uses credential account_id if not provided)")
    account_app_id: str = Field(description="Magic Transit app identifier")
    name: Optional[str] = Field(default=None, description="Display name for the app")
    type: Optional[str] = Field(default=None, description="Category of the app")
    hostnames: Optional[str] = Field(default=None, description="Comma-separated FQDNs to associate with traffic decisions")
    ip_subnets: Optional[str] = Field(default=None, description="Comma-separated IPv4 CIDR blocks to associate with traffic decisions")
    source_subnets: Optional[str] = Field(default=None, description="Comma-separated IPv4 CIDR source blocks for traffic decisions")

class CloudflareDeleteMagicAppConfig(BaseModel):
    """Delete a Magic Transit app"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["delete_magic_app"] = Field(
        default="delete_magic_app",
        title="Delete Magic Transit App",
        json_schema_extra={"x-category": "Magic Transit", "x-is-trigger": False, "x-display-name": "Delete Magic Transit App", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID (uses credential account_id if not provided)")
    account_app_id: str = Field(description="Magic Transit app identifier to delete")


# ─── Calls Config Models ───────────────────────────────────────────────────────

class CloudflareListCallsAppsConfig(BaseModel):
    """List all Cloudflare Calls SFU apps for an account"""

    operation: Literal["list_calls_apps"] = Field(
        default="list_calls_apps",
        title="List Calls Apps",
        json_schema_extra={"x-category": "Calls", "x-is-trigger": False, "x-display-name": "List Calls Apps", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})

class CloudflareGetCallsAppConfig(BaseModel):
    """Retrieve details for a specific Cloudflare Calls SFU app"""

    operation: Literal["get_calls_app"] = Field(
        default="get_calls_app",
        title="Get Calls App",
        json_schema_extra={"x-category": "Calls", "x-is-trigger": False, "x-display-name": "Get Calls App", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    app_id: str = Field(description="The SFU app UID")

class CloudflareCreateCallsAppConfig(BaseModel):
    """Create a new Cloudflare Calls SFU app and obtain its bearer secret"""

    operation: Literal["create_calls_app"] = Field(
        default="create_calls_app",
        title="Create Calls App",
        json_schema_extra={"x-category": "Calls", "x-is-trigger": False, "x-display-name": "Create Calls App", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    name: Optional[str] = Field(default=None, description="A human-readable name for the SFU app")

class CloudflareUpdateCallsAppConfig(BaseModel):
    """Update the details of an existing Cloudflare Calls SFU app"""

    operation: Literal["update_calls_app"] = Field(
        default="update_calls_app",
        title="Update Calls App",
        json_schema_extra={"x-category": "Calls", "x-is-trigger": False, "x-display-name": "Update Calls App", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    app_id: str = Field(description="The SFU app UID")
    name: Optional[str] = Field(default=None, description="New name for the SFU app")

class CloudflareDeleteCallsAppConfig(BaseModel):
    """Delete a Cloudflare Calls SFU app"""

    operation: Literal["delete_calls_app"] = Field(
        default="delete_calls_app",
        title="Delete Calls App",
        json_schema_extra={"x-category": "Calls", "x-is-trigger": False, "x-display-name": "Delete Calls App", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    app_id: str = Field(description="The SFU app UID to delete")

class CloudflareListCallsTurnKeysConfig(BaseModel):
    """List all Cloudflare Calls TURN keys for an account"""

    operation: Literal["list_calls_turn_keys"] = Field(
        default="list_calls_turn_keys",
        title="List Calls Turn Keys",
        json_schema_extra={"x-category": "Calls", "x-is-trigger": False, "x-display-name": "List Calls TURN Keys", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})

class CloudflareGetCallsTurnKeyConfig(BaseModel):
    """Retrieve details for a specific Cloudflare Calls TURN key"""

    operation: Literal["get_calls_turn_key"] = Field(
        default="get_calls_turn_key",
        title="Get Calls Turn Key",
        json_schema_extra={"x-category": "Calls", "x-is-trigger": False, "x-display-name": "Get Calls TURN Key", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    key_id: str = Field(description="The TURN key UID")

class CloudflareCreateCallsTurnKeyConfig(BaseModel):
    """Create a new Cloudflare Calls TURN key and obtain its bearer token"""

    operation: Literal["create_calls_turn_key"] = Field(
        default="create_calls_turn_key",
        title="Create Calls Turn Key",
        json_schema_extra={"x-category": "Calls", "x-is-trigger": False, "x-display-name": "Create Calls TURN Key", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    name: Optional[str] = Field(default=None, description="A human-readable name for the TURN key")

class CloudflareUpdateCallsTurnKeyConfig(BaseModel):
    """Update the details of an existing Cloudflare Calls TURN key"""

    operation: Literal["update_calls_turn_key"] = Field(
        default="update_calls_turn_key",
        title="Update Calls Turn Key",
        json_schema_extra={"x-category": "Calls", "x-is-trigger": False, "x-display-name": "Update Calls TURN Key", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    key_id: str = Field(description="The TURN key UID")
    name: Optional[str] = Field(default=None, description="New name for the TURN key")

class CloudflareDeleteCallsTurnKeyConfig(BaseModel):
    """Delete a Cloudflare Calls TURN key"""

    operation: Literal["delete_calls_turn_key"] = Field(
        default="delete_calls_turn_key",
        title="Delete Calls Turn Key",
        json_schema_extra={"x-category": "Calls", "x-is-trigger": False, "x-display-name": "Delete Calls TURN Key", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    key_id: str = Field(description="The TURN key UID to delete")


# ─── Analytics Engine SQL API Config Models ────────────────────────────────────

_ANALYTICS_ENGINE_FORMAT_EXTRA = {
    "enum": ["JSON", "JSONEachRow", "TabSeparated"],
    "enumNames": ["JSON", "JSONEachRow (one object per line)", "TabSeparated"],
    "x-enum-searchable": True,
}

class CloudflareListAnalyticsEngineDatasetsConfig(BaseModel):
    """List all Analytics Engine datasets (tables) in the account using SHOW TABLES"""

    operation: Literal["list_analytics_engine_datasets"] = Field(
        default="list_analytics_engine_datasets",
        title="List Analytics Engine Datasets",
        json_schema_extra={"x-category": "Analytics Engine SQL API", "x-is-trigger": False, "x-display-name": "List Analytics Engine Datasets", "ui:hidden": True},
    )
    format: Optional[str] = Field(default=None, description="Output format for the result", json_schema_extra=_ANALYTICS_ENGINE_FORMAT_EXTRA)

class CloudflareGetAnalyticsEngineDatasetSchemaConfig(BaseModel):
    """Get the column schema of an Analytics Engine dataset by querying a single row"""

    operation: Literal["get_analytics_engine_dataset_schema"] = Field(
        default="get_analytics_engine_dataset_schema",
        title="Get Analytics Engine Dataset Schema",
        json_schema_extra={"x-category": "Analytics Engine SQL API", "x-is-trigger": False, "x-display-name": "Get Analytics Engine Dataset Schema", "ui:hidden": True},
    )
    dataset_name: str = Field(description="Name of the dataset to inspect")
    format: Optional[str] = Field(default=None, description="Output format for the result", json_schema_extra=_ANALYTICS_ENGINE_FORMAT_EXTRA)

class CloudflareQueryAnalyticsEngineAggregatedConfig(BaseModel):
    """Run an aggregation query on an Analytics Engine dataset with grouping, filtering, and time range support"""

    operation: Literal["query_analytics_engine_aggregated"] = Field(
        default="query_analytics_engine_aggregated",
        title="Query Analytics Engine Aggregated",
        json_schema_extra={"x-category": "Analytics Engine SQL API", "x-is-trigger": False, "x-display-name": "Query Analytics Engine Aggregated", "ui:hidden": True},
    )
    dataset_name: str = Field(description="Name of the Analytics Engine dataset to query")
    select_columns: str = Field(description="Comma-separated columns or expressions to select e.g. blob1, count() AS cnt, sum(double1) AS total")
    group_by: Optional[str] = Field(default=None, description="Comma-separated columns to group by e.g. blob1, blob2")
    where: Optional[str] = Field(default=None, description="WHERE clause condition e.g. blob1 = 'production' AND double1 > 0")
    order_by: Optional[str] = Field(default=None, description="ORDER BY clause e.g. cnt DESC")
    limit: Optional[str] = Field(default=None, description="Maximum number of rows to return (default 100)")
    start_time: Optional[str] = Field(default=None, description="Filter events after this timestamp (ISO 8601) e.g. 2024-01-01T00:00:00Z")
    end_time: Optional[str] = Field(default=None, description="Filter events before this timestamp (ISO 8601) e.g. 2024-01-31T23:59:59Z")
    format: Optional[str] = Field(default=None, description="Output format for the result", json_schema_extra=_ANALYTICS_ENGINE_FORMAT_EXTRA)

class CloudflareQueryAnalyticsEngineTimeseriesConfig(BaseModel):
    """Query Analytics Engine data grouped by time intervals for time-series analysis"""

    operation: Literal["query_analytics_engine_timeseries"] = Field(
        default="query_analytics_engine_timeseries",
        title="Query Analytics Engine Time Series",
        json_schema_extra={"x-category": "Analytics Engine SQL API", "x-is-trigger": False, "x-display-name": "Query Analytics Engine Time Series", "ui:hidden": True},
    )
    dataset_name: str = Field(description="Name of the Analytics Engine dataset to query")
    metric_expression: str = Field(description="Aggregate metric expression e.g. count() AS requests, sum(double1) AS total_bytes")
    interval: Optional[str] = Field(default=None, description="Time bucket expression for grouping e.g. toStartOfHour(timestamp) or toStartOfDay(timestamp)")
    where: Optional[str] = Field(default=None, description="Optional WHERE clause to filter data before aggregation")
    start_time: Optional[str] = Field(default=None, description="Start of time range (ISO 8601)")
    end_time: Optional[str] = Field(default=None, description="End of time range (ISO 8601)")
    limit: Optional[str] = Field(default=None, description="Maximum number of time buckets to return (default 100)")
    format: Optional[str] = Field(default=None, description="Output format for the result", json_schema_extra=_ANALYTICS_ENGINE_FORMAT_EXTRA)

class CloudflareQueryAnalyticsEngineRawConfig(BaseModel):
    """Query raw (non-aggregated) events from an Analytics Engine dataset with optional filtering"""

    operation: Literal["query_analytics_engine_raw"] = Field(
        default="query_analytics_engine_raw",
        title="Query Analytics Engine Raw Events",
        json_schema_extra={"x-category": "Analytics Engine SQL API", "x-is-trigger": False, "x-display-name": "Query Analytics Engine Raw Events", "ui:hidden": True},
    )
    dataset_name: str = Field(description="Name of the Analytics Engine dataset")
    columns: Optional[str] = Field(default=None, description="Columns to return (default: *) e.g. timestamp, index1, blob1, double1")
    where: Optional[str] = Field(default=None, description="WHERE clause to filter events e.g. index1 = 'us-east-1'")
    order_by: Optional[str] = Field(default=None, description="ORDER BY clause e.g. timestamp DESC")
    limit: Optional[str] = Field(default=None, description="Maximum number of rows to return (default 100)")
    start_time: Optional[str] = Field(default=None, description="Filter events after this timestamp (ISO 8601)")
    end_time: Optional[str] = Field(default=None, description="Filter events before this timestamp (ISO 8601)")
    format: Optional[str] = Field(default=None, description="Output format for the result", json_schema_extra=_ANALYTICS_ENGINE_FORMAT_EXTRA)

class CloudflareGetAnalyticsEngineEventCountConfig(BaseModel):
    """Count events in an Analytics Engine dataset, optionally filtered by time range and conditions"""

    operation: Literal["get_analytics_engine_event_count"] = Field(
        default="get_analytics_engine_event_count",
        title="Get Analytics Engine Event Count",
        json_schema_extra={"x-category": "Analytics Engine SQL API", "x-is-trigger": False, "x-display-name": "Get Analytics Engine Event Count", "ui:hidden": True},
    )
    dataset_name: str = Field(description="Name of the Analytics Engine dataset")
    where: Optional[str] = Field(default=None, description="Optional WHERE clause to filter events before counting")
    start_time: Optional[str] = Field(default=None, description="Count events after this timestamp (ISO 8601)")
    end_time: Optional[str] = Field(default=None, description="Count events before this timestamp (ISO 8601)")
    format: Optional[str] = Field(default=None, description="Output format for the result", json_schema_extra=_ANALYTICS_ENGINE_FORMAT_EXTRA)

class CloudflareListAnalyticsEngineTimezonesConfig(BaseModel):
    """List all supported timezones available in the Analytics Engine SQL environment"""

    operation: Literal["list_analytics_engine_timezones"] = Field(
        default="list_analytics_engine_timezones",
        title="List Analytics Engine Timezones",
        json_schema_extra={"x-category": "Analytics Engine SQL API", "x-is-trigger": False, "x-display-name": "List Analytics Engine Timezones", "ui:hidden": True},
    )
    format: Optional[str] = Field(default=None, description="Output format for the result", json_schema_extra=_ANALYTICS_ENGINE_FORMAT_EXTRA)

class CloudflareQueryAnalyticsEngineTopValuesConfig(BaseModel):
    """Find the top N values of a blob (string) column by event count in an Analytics Engine dataset"""

    operation: Literal["query_analytics_engine_top_values"] = Field(
        default="query_analytics_engine_top_values",
        title="Query Analytics Engine Top Values",
        json_schema_extra={"x-category": "Analytics Engine SQL API", "x-is-trigger": False, "x-display-name": "Query Analytics Engine Top Values", "ui:hidden": True},
    )
    dataset_name: str = Field(description="Name of the Analytics Engine dataset")
    column: str = Field(description="Blob column to rank by event count e.g. blob1, blob2, index1")
    limit: Optional[str] = Field(default=None, description="Number of top values to return (default 10)")
    where: Optional[str] = Field(default=None, description="Optional WHERE clause to filter events before ranking")
    start_time: Optional[str] = Field(default=None, description="Filter events after this timestamp (ISO 8601)")
    end_time: Optional[str] = Field(default=None, description="Filter events before this timestamp (ISO 8601)")
    format: Optional[str] = Field(default=None, description="Output format for the result", json_schema_extra=_ANALYTICS_ENGINE_FORMAT_EXTRA)

class CloudflareQueryAnalyticsEngineWeightedAvgConfig(BaseModel):
    """Compute a sampling-corrected weighted average of a double column in an Analytics Engine dataset"""

    operation: Literal["query_analytics_engine_weighted_avg"] = Field(
        default="query_analytics_engine_weighted_avg",
        title="Query Analytics Engine Weighted Average",
        json_schema_extra={"x-category": "Analytics Engine SQL API", "x-is-trigger": False, "x-display-name": "Query Analytics Engine Weighted Average", "ui:hidden": True},
    )
    dataset_name: str = Field(description="Name of the Analytics Engine dataset")
    value_column: str = Field(description="Double column to compute weighted average of e.g. double1, double2")
    group_by: Optional[str] = Field(default=None, description="Comma-separated columns to group by for per-group averages e.g. blob1")
    where: Optional[str] = Field(default=None, description="Optional WHERE clause to filter events")
    start_time: Optional[str] = Field(default=None, description="Filter events after this timestamp (ISO 8601)")
    end_time: Optional[str] = Field(default=None, description="Filter events before this timestamp (ISO 8601)")
    limit: Optional[str] = Field(default=None, description="Maximum number of rows to return (default 100)")
    format: Optional[str] = Field(default=None, description="Output format for the result", json_schema_extra=_ANALYTICS_ENGINE_FORMAT_EXTRA)


# ─── Log Explorer Config Models ────────────────────────────────────────────────

class CloudflareQueryLogExplorerSQLConfig(BaseModel):
    """Execute a SQL query against Log Explorer account or zone datasets"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["query_log_explorer_sql"] = Field(
        default="query_log_explorer_sql",
        title="Query Log Explorer (SQL)",
        json_schema_extra={"x-category": "Log Explorer", "x-is-trigger": False, "x-display-name": "Query Log Explorer (SQL)", "ui:hidden": True},
    )
    sql_query: str = Field(
        description="SQL query to run against Log Explorer datasets, e.g. SELECT * FROM http_requests WHERE date = '2024-01-15' LIMIT 100",
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 4},
    )
    account_id: Optional[str] = Field(default=None, description="Account ID to scope the query (mutually exclusive with zone_id)")
    zone_id: Optional[str] = Field(default=None, description="Zone ID to scope the query (mutually exclusive with account_id)")

class CloudflareListLogExplorerDatasetsConfig(BaseModel):
    """List all configured Log Explorer datasets for an account or zone"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["list_log_explorer_datasets"] = Field(
        default="list_log_explorer_datasets",
        title="List Log Explorer Datasets",
        json_schema_extra={"x-category": "Log Explorer", "x-is-trigger": False, "x-display-name": "List Log Explorer Datasets", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Account ID (mutually exclusive with zone_id)")
    zone_id: Optional[str] = Field(default=None, description="Zone ID (mutually exclusive with account_id)")
    include_zones: Optional[str] = Field(
        default=None,
        description="Set to 'true' to include zone-scoped datasets belonging to this account",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )

class CloudflareGetLogExplorerDatasetConfig(BaseModel):
    """Fetch a single Log Explorer dataset including its field configuration"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["get_log_explorer_dataset"] = Field(
        default="get_log_explorer_dataset",
        title="Get Log Explorer Dataset",
        json_schema_extra={"x-category": "Log Explorer", "x-is-trigger": False, "x-display-name": "Get Log Explorer Dataset", "ui:hidden": True},
    )
    dataset_id: str = Field(description="The dataset ID to retrieve")
    account_id: Optional[str] = Field(default=None, description="Account ID (mutually exclusive with zone_id)")
    zone_id: Optional[str] = Field(default=None, description="Zone ID (mutually exclusive with account_id)")

class CloudflareCreateLogExplorerDatasetConfig(BaseModel):
    """Create a new Log Explorer dataset"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["create_log_explorer_dataset"] = Field(
        default="create_log_explorer_dataset",
        title="Create Log Explorer Dataset",
        json_schema_extra={"x-category": "Log Explorer", "x-is-trigger": False, "x-display-name": "Create Log Explorer Dataset", "ui:hidden": True},
    )
    dataset: str = Field(
        description="Dataset type name to create, e.g. 'http_requests' or 'access_requests'",
        json_schema_extra={
            "enum": ["http_requests", "access_requests", "nel_reports", "spectrum_events", "network_analytics_logs", "dns_logs", "gateway_dns", "gateway_http", "gateway_network", "zero_trust_network_sessions"],
            "enumNames": ["HTTP Requests", "Access Requests", "NEL Reports", "Spectrum Events", "Network Analytics", "DNS Logs", "Gateway DNS", "Gateway HTTP", "Gateway Network", "Zero Trust Network Sessions"],
            "x-enum-searchable": True,
        },
    )
    account_id: Optional[str] = Field(default=None, description="Account ID (mutually exclusive with zone_id)")
    zone_id: Optional[str] = Field(default=None, description="Zone ID (mutually exclusive with account_id)")
    fields: Optional[str] = Field(
        default=None,
        description='JSON array of field objects with "name" and "enabled" keys, e.g. [{"name":"clientip","enabled":true}]. Omit to ingest all fields.',
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 3},
    )

class CloudflareUpdateLogExplorerDatasetConfig(BaseModel):
    """Update a Log Explorer dataset's enabled state and field configuration"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["update_log_explorer_dataset"] = Field(
        default="update_log_explorer_dataset",
        title="Update Log Explorer Dataset",
        json_schema_extra={"x-category": "Log Explorer", "x-is-trigger": False, "x-display-name": "Update Log Explorer Dataset", "ui:hidden": True},
    )
    dataset_id: str = Field(description="The dataset ID to update")
    enabled: str = Field(
        description="Whether to enable or disable log ingest for this dataset",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Enabled", "Disabled"], "x-enum-searchable": True},
    )
    account_id: Optional[str] = Field(default=None, description="Account ID (mutually exclusive with zone_id)")
    zone_id: Optional[str] = Field(default=None, description="Zone ID (mutually exclusive with account_id)")
    fields: Optional[str] = Field(
        default=None,
        description='JSON array of field objects with "name" and "enabled" keys to update field configuration',
        json_schema_extra={"ui:widget": "textarea", "ui:rows": 3},
    )

class CloudflareListLogExplorerAvailableDatasetsConfig(BaseModel):
    """List all dataset types available to create for this account or zone, including schemas"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["list_log_explorer_available_datasets"] = Field(
        default="list_log_explorer_available_datasets",
        title="List Available Log Explorer Dataset Types",
        json_schema_extra={"x-category": "Log Explorer", "x-is-trigger": False, "x-display-name": "List Available Log Explorer Dataset Types", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Account ID (mutually exclusive with zone_id)")
    zone_id: Optional[str] = Field(default=None, description="Zone ID (mutually exclusive with account_id)")

class CloudflareGetLogpullLogsConfig(BaseModel):
    """Retrieve edge HTTP request logs for a zone within a time window via Logpull API"""

    operation: Literal["get_logpull_logs"] = Field(
        default="get_logpull_logs",
        title="Get Logpull Logs (Received)",
        json_schema_extra={"x-category": "Log Explorer", "x-is-trigger": False, "x-display-name": "Get Logpull Logs (Received)", "ui:hidden": True},
    )
    zone_id: str = Field(description="The zone ID to retrieve logs for", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    start: str = Field(description="Inclusive start timestamp in RFC 3339 (e.g. 2024-01-15T00:00:00Z) or Unix format")
    end: str = Field(description="Exclusive end timestamp in RFC 3339 or Unix format. Must be at least 5 minutes before now; max 1-hour span from start.")
    fields: Optional[str] = Field(default=None, description="Comma-separated list of field names to return, e.g. 'ClientIP,RayID,EdgeResponseStatus'")
    count: Optional[str] = Field(default=None, description="Return up to this many results (integer > 0)")
    sample: Optional[str] = Field(default=None, description="Return a random sample fraction of records, e.g. '0.1' for 10%")
    timestamps: Optional[str] = Field(
        default=None,
        description="Timestamp format for the response",
        json_schema_extra={"enum": ["unix", "unixnano", "rfc3339"], "enumNames": ["Unix seconds", "Unix nanoseconds", "RFC 3339"], "x-enum-searchable": True},
    )

class CloudflareGetLogpullFieldsConfig(BaseModel):
    """List all available log fields for the Logpull API with their descriptions"""

    operation: Literal["get_logpull_fields"] = Field(
        default="get_logpull_fields",
        title="List Logpull Fields",
        json_schema_extra={"x-category": "Log Explorer", "x-is-trigger": False, "x-display-name": "List Logpull Fields", "ui:hidden": True},
    )
    zone_id: str = Field(description="The zone ID to list available log fields for", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })

class CloudflareGetLogpullRayIDConfig(BaseModel):
    """Look up log records for a specific Ray ID"""

    operation: Literal["get_logpull_rayid"] = Field(
        default="get_logpull_rayid",
        title="Get Logs by Ray ID",
        json_schema_extra={"x-category": "Log Explorer", "x-is-trigger": False, "x-display-name": "Get Logs by Ray ID", "ui:hidden": True},
    )
    zone_id: str = Field(description="The zone ID to search logs in", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    ray_id: str = Field(description="The Ray ID to look up log records for")
    fields: Optional[str] = Field(default=None, description="Comma-separated list of field names to return")
    timestamps: Optional[str] = Field(
        default=None,
        description="Timestamp format for the response",
        json_schema_extra={"enum": ["unix", "unixnano", "rfc3339"], "enumNames": ["Unix seconds", "Unix nanoseconds", "RFC 3339"], "x-enum-searchable": True},
    )

class CloudflareGetLogRetentionFlagConfig(BaseModel):
    """Get the log retention flag for the Logpull API for a zone"""

    operation: Literal["get_log_retention_flag"] = Field(
        default="get_log_retention_flag",
        title="Get Log Retention Flag",
        json_schema_extra={"x-category": "Log Explorer", "x-is-trigger": False, "x-display-name": "Get Log Retention Flag", "ui:hidden": True},
    )
    zone_id: str = Field(description="The zone ID to get the log retention flag for", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })

class CloudflareUpdateLogRetentionFlagConfig(BaseModel):
    """Enable or disable log retention for the Logpull API for a zone"""

    operation: Literal["update_log_retention_flag"] = Field(
        default="update_log_retention_flag",
        title="Update Log Retention Flag",
        json_schema_extra={"x-category": "Log Explorer", "x-is-trigger": False, "x-display-name": "Update Log Retention Flag", "ui:hidden": True},
    )
    zone_id: str = Field(description="The zone ID to update the log retention flag for", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    flag: str = Field(
        description="Whether to enable log retention for the Logpull API",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Enabled", "Disabled"], "x-enum-searchable": True},
    )

class CloudflareGetCMBConfigConfig(BaseModel):
    """Get the Cloudflare Managed Buckets (CMB) log control configuration for an account"""

    operation: Literal["get_cmb_config"] = Field(
        default="get_cmb_config",
        title="Get CMB Config",
        json_schema_extra={"x-category": "Log Explorer", "x-is-trigger": False, "x-display-name": "Get CMB Config", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The account ID to get CMB config for", json_schema_extra={"ui:hidden": True})

class CloudflareUpdateCMBConfigConfig(BaseModel):
    """Update the Cloudflare Managed Buckets (CMB) log control configuration"""

    operation: Literal["update_cmb_config"] = Field(
        default="update_cmb_config",
        title="Update CMB Config",
        json_schema_extra={"x-category": "Log Explorer", "x-is-trigger": False, "x-display-name": "Update CMB Config", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The account ID to update CMB config for", json_schema_extra={"ui:hidden": True})
    regions: Optional[str] = Field(default=None, description="Name of the region for CMB log storage")
    allow_out_of_region_access: Optional[str] = Field(
        default=None,
        description="Whether to allow out-of-region access to CMB logs",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Allow", "Deny"], "x-enum-searchable": True},
    )

class CloudflareDeleteCMBConfigConfig(BaseModel):
    """Delete the Cloudflare Managed Buckets (CMB) log control configuration for an account"""

    operation: Literal["delete_cmb_config"] = Field(
        default="delete_cmb_config",
        title="Delete CMB Config",
        json_schema_extra={"x-category": "Log Explorer", "x-is-trigger": False, "x-display-name": "Delete CMB Config", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="The account ID to delete CMB config for", json_schema_extra={"ui:hidden": True})


# ─── Addressing / BYOIP Config Models ─────────────────────────────────────────

class CloudflareListIPPrefixesConfig(BaseModel):
    """List all BYOIP prefixes for the account"""

    operation: Literal["list_ip_prefixes"] = Field(
        default="list_ip_prefixes",
        title="List IP Prefixes",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "List IP Prefixes", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})

class CloudflareGetIPPrefixConfig(BaseModel):
    """Retrieve details of a specific BYOIP prefix"""

    operation: Literal["get_ip_prefix"] = Field(
        default="get_ip_prefix",
        title="Get IP Prefix",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Get IP Prefix", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    prefix_id: str = Field(description="BYOIP prefix ID")

class CloudflareCreateIPPrefixConfig(BaseModel):
    """Add a new BYOIP prefix to the account"""

    operation: Literal["create_ip_prefix"] = Field(
        default="create_ip_prefix",
        title="Create IP Prefix",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Create IP Prefix", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    asn: str = Field(description="Autonomous System Number (ASN) for the prefix")
    cidr: str = Field(description="IP prefix in CIDR notation (e.g. 192.0.2.0/24)")
    loa_document_id: Optional[str] = Field(default=None, description="ID of the Letter of Authorization document")
    description: Optional[str] = Field(default=None, description="Description of the prefix")

class CloudflareUpdateIPPrefixConfig(BaseModel):
    """Update the description of a BYOIP prefix"""

    operation: Literal["update_ip_prefix"] = Field(
        default="update_ip_prefix",
        title="Update IP Prefix",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Update IP Prefix", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    prefix_id: str = Field(description="BYOIP prefix ID")
    description: str = Field(description="New description for the prefix")

class CloudflareDeleteIPPrefixConfig(BaseModel):
    """Delete an unapproved BYOIP prefix from the account"""

    operation: Literal["delete_ip_prefix"] = Field(
        default="delete_ip_prefix",
        title="Delete IP Prefix",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Delete IP Prefix", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    prefix_id: str = Field(description="BYOIP prefix ID to delete")

class CloudflareGetBGPAdvertisementStatusConfig(BaseModel):
    """Get the current BGP advertisement status for an IP prefix"""

    operation: Literal["get_bgp_prefix_advertisement_status"] = Field(
        default="get_bgp_prefix_advertisement_status",
        title="Get BGP Advertisement Status",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Get BGP Advertisement Status", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    prefix_id: str = Field(description="BYOIP prefix ID")

class CloudflareUpdateBGPAdvertisementConfig(BaseModel):
    """Advertise or withdraw a BYOIP prefix via BGP"""

    operation: Literal["update_bgp_prefix_advertisement"] = Field(
        default="update_bgp_prefix_advertisement",
        title="Update BGP Advertisement Status",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Update BGP Advertisement Status", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    prefix_id: str = Field(description="BYOIP prefix ID")
    advertised: str = Field(
        description="Whether to advertise (true) or withdraw (false) the prefix",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Advertise", "Withdraw"], "x-enum-searchable": True},
    )

class CloudflareListBGPPrefixesConfig(BaseModel):
    """List BGP sub-prefixes for a BYOIP prefix"""

    operation: Literal["list_bgp_prefixes"] = Field(
        default="list_bgp_prefixes",
        title="List BGP Prefixes",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "List BGP Prefixes", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    prefix_id: str = Field(description="Parent BYOIP prefix ID")

class CloudflareUpdateBGPPrefixConfig(BaseModel):
    """Update settings for a specific BGP prefix (on-demand advertisement, ASN prepend)"""

    operation: Literal["update_bgp_prefix"] = Field(
        default="update_bgp_prefix",
        title="Update BGP Prefix",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Update BGP Prefix", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    prefix_id: str = Field(description="Parent BYOIP prefix ID")
    bgp_prefix_id: str = Field(description="BGP prefix ID to update")
    on_demand_enabled: Optional[str] = Field(
        default=None,
        description="Enable on-demand advertisement (true/false)",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Enable", "Disable"], "x-enum-searchable": True},
    )
    asn_prepend_count: Optional[str] = Field(
        default=None,
        description="Number of times to prepend ASN (0-5)",
        json_schema_extra={"enum": ["0", "1", "2", "3", "4", "5"], "x-enum-searchable": True},
    )

class CloudflareListPrefixServiceBindingsConfig(BaseModel):
    """List all service bindings for a BYOIP prefix"""

    operation: Literal["list_prefix_service_bindings"] = Field(
        default="list_prefix_service_bindings",
        title="List Prefix Service Bindings",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "List Prefix Service Bindings", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    prefix_id: str = Field(description="BYOIP prefix ID")

class CloudflareCreatePrefixServiceBindingConfig(BaseModel):
    """Create a binding to route prefix traffic to a Cloudflare service (e.g. Magic Transit)"""

    operation: Literal["create_prefix_service_binding"] = Field(
        default="create_prefix_service_binding",
        title="Create Prefix Service Binding",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Create Prefix Service Binding", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    prefix_id: str = Field(description="BYOIP prefix ID")
    cidr: str = Field(description="CIDR range to bind (sub-range of the prefix)")
    service_id: str = Field(description="ID of the Cloudflare service to bind to")

class CloudflareGetPrefixServiceBindingConfig(BaseModel):
    """Get a specific service binding for a BYOIP prefix"""

    operation: Literal["get_prefix_service_binding"] = Field(
        default="get_prefix_service_binding",
        title="Get Prefix Service Binding",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Get Prefix Service Binding", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    prefix_id: str = Field(description="BYOIP prefix ID")
    binding_id: str = Field(description="The service binding ID")

class CloudflareDeletePrefixServiceBindingConfig(BaseModel):
    """Remove a service binding from a BYOIP prefix"""

    operation: Literal["delete_prefix_service_binding"] = Field(
        default="delete_prefix_service_binding",
        title="Delete Prefix Service Binding",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Delete Prefix Service Binding", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    prefix_id: str = Field(description="BYOIP prefix ID")
    binding_id: str = Field(description="Service binding ID to delete")

class CloudflareListPrefixDelegationsConfig(BaseModel):
    """List all delegations for a BYOIP prefix"""

    operation: Literal["list_prefix_delegations"] = Field(
        default="list_prefix_delegations",
        title="List Prefix Delegations",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "List Prefix Delegations", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    prefix_id: str = Field(description="BYOIP prefix ID")

class CloudflareCreatePrefixDelegationConfig(BaseModel):
    """Delegate a sub-prefix to another Cloudflare account"""

    operation: Literal["create_prefix_delegation"] = Field(
        default="create_prefix_delegation",
        title="Create Prefix Delegation",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Create Prefix Delegation", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    prefix_id: str = Field(description="BYOIP prefix ID")
    cidr: str = Field(description="CIDR range to delegate")
    delegated_account_id: str = Field(description="ID of the account to delegate the sub-prefix to")

class CloudflareDeletePrefixDelegationConfig(BaseModel):
    """Remove a delegation from a BYOIP prefix"""

    operation: Literal["delete_prefix_delegation"] = Field(
        default="delete_prefix_delegation",
        title="Delete Prefix Delegation",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Delete Prefix Delegation", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    prefix_id: str = Field(description="BYOIP prefix ID")
    delegation_id: str = Field(description="Delegation ID to delete")

class CloudflareListAddressMapsConfig(BaseModel):
    """List all address maps for the account"""

    operation: Literal["list_address_maps"] = Field(
        default="list_address_maps",
        title="List Address Maps",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "List Address Maps", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})

class CloudflareGetAddressMapConfig(BaseModel):
    """Retrieve details of a specific address map"""

    operation: Literal["get_address_map"] = Field(
        default="get_address_map",
        title="Get Address Map",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Get Address Map", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    address_map_id: str = Field(description="Address map ID")

class CloudflareCreateAddressMapConfig(BaseModel):
    """Create a new address map to assign IPv4/IPv6 addresses to zones or accounts"""

    operation: Literal["create_address_map"] = Field(
        default="create_address_map",
        title="Create Address Map",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Create Address Map", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    description: Optional[str] = Field(default=None, description="Human-readable description of the address map")
    default_sni: Optional[str] = Field(default=None, description="Default SNI hostname for TLS connections")
    enabled: Optional[str] = Field(
        default=None,
        description="Whether the address map is enabled",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Enabled", "Disabled"], "x-enum-searchable": True},
    )

class CloudflareUpdateAddressMapConfig(BaseModel):
    """Modify properties of an existing address map"""

    operation: Literal["update_address_map"] = Field(
        default="update_address_map",
        title="Update Address Map",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Update Address Map", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    address_map_id: str = Field(description="Address map ID to update")
    description: Optional[str] = Field(default=None, description="Updated description")
    default_sni: Optional[str] = Field(default=None, description="Updated default SNI hostname")
    enabled: Optional[str] = Field(
        default=None,
        description="Enable or disable the address map",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Enabled", "Disabled"], "x-enum-searchable": True},
    )

class CloudflareDeleteAddressMapConfig(BaseModel):
    """Delete an address map"""

    operation: Literal["delete_address_map"] = Field(
        default="delete_address_map",
        title="Delete Address Map",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Delete Address Map", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    address_map_id: str = Field(description="Address map ID to delete")

class CloudflareAddIPToAddressMapConfig(BaseModel):
    """Add an IP address to an address map"""

    operation: Literal["add_ip_to_address_map"] = Field(
        default="add_ip_to_address_map",
        title="Add IP to Address Map",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Add IP to Address Map", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    address_map_id: str = Field(description="Address map ID")
    ip_address: str = Field(description="IPv4 or IPv6 address to add to the map")

class CloudflareRemoveIPFromAddressMapConfig(BaseModel):
    """Remove an IP address from an address map"""

    operation: Literal["remove_ip_from_address_map"] = Field(
        default="remove_ip_from_address_map",
        title="Remove IP from Address Map",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Remove IP from Address Map", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    address_map_id: str = Field(description="Address map ID")
    ip_address: str = Field(description="IPv4 or IPv6 address to remove")

class CloudflareAddZoneToAddressMapConfig(BaseModel):
    """Add a zone as a member of an address map"""

    operation: Literal["add_zone_to_address_map"] = Field(
        default="add_zone_to_address_map",
        title="Add Zone to Address Map",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Add Zone to Address Map", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    address_map_id: str = Field(description="Address map ID")
    zone_id: str = Field(description="Zone ID to add to the address map", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })

class CloudflareRemoveZoneFromAddressMapConfig(BaseModel):
    """Remove a zone from an address map"""

    operation: Literal["remove_zone_from_address_map"] = Field(
        default="remove_zone_from_address_map",
        title="Remove Zone from Address Map",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Remove Zone from Address Map", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    address_map_id: str = Field(description="Address map ID")
    zone_id: str = Field(description="Zone ID to remove from the address map", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })

class CloudflareListRegionalHostnamesConfig(BaseModel):
    """List all regional hostnames configured for a zone"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "paid", "x-tier-label": "Paid"})
    operation: Literal["list_regional_hostnames"] = Field(
        default="list_regional_hostnames",
        title="List Regional Hostnames",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "List Regional Hostnames", "ui:hidden": True},
    )
    zone_id: str = Field(description="Zone ID to list regional hostnames for", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })

class CloudflareGetRegionalHostnameConfig(BaseModel):
    """Fetch the regional routing configuration for a specific hostname"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "paid", "x-tier-label": "Paid"})
    operation: Literal["get_regional_hostname"] = Field(
        default="get_regional_hostname",
        title="Get Regional Hostname",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Get Regional Hostname", "ui:hidden": True},
    )
    zone_id: str = Field(description="Zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    hostname: str = Field(description="DNS hostname to retrieve regional config for")

class CloudflareCreateRegionalHostnameConfig(BaseModel):
    """Create a new regional hostname to restrict DNS resolution to a geographic region"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "paid", "x-tier-label": "Paid"})
    operation: Literal["create_regional_hostname"] = Field(
        default="create_regional_hostname",
        title="Create Regional Hostname",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Create Regional Hostname", "ui:hidden": True},
    )
    zone_id: str = Field(description="Zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    hostname: str = Field(description="DNS hostname to assign a region to")
    region_key: str = Field(description="Region key identifier (e.g. 'eu' for Europe)")
    routing: Optional[str] = Field(default=None, description="Routing method to use for this regional hostname")

class CloudflareUpdateRegionalHostnameConfig(BaseModel):
    """Update the region assignment for a regional hostname"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "paid", "x-tier-label": "Paid"})
    operation: Literal["update_regional_hostname"] = Field(
        default="update_regional_hostname",
        title="Update Regional Hostname",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Update Regional Hostname", "ui:hidden": True},
    )
    zone_id: str = Field(description="Zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    hostname: str = Field(description="DNS hostname whose region to update")
    region_key: str = Field(description="New region key identifier")

class CloudflareDeleteRegionalHostnameConfig(BaseModel):
    """Remove the regional routing configuration for a hostname"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "paid", "x-tier-label": "Paid"})
    operation: Literal["delete_regional_hostname"] = Field(
        default="delete_regional_hostname",
        title="Delete Regional Hostname",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Delete Regional Hostname", "ui:hidden": True},
    )
    zone_id: str = Field(description="Zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    hostname: str = Field(description="DNS hostname to remove regional config from")

class CloudflareListRegionalHostnameRegionsConfig(BaseModel):
    """List all available geographic regions for regional hostname assignment"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "paid", "x-tier-label": "Paid"})
    operation: Literal["list_regional_hostname_regions"] = Field(
        default="list_regional_hostname_regions",
        title="List Regional Hostname Regions",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "List Regional Hostname Regions", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})

class CloudflareListAddressingServicesConfig(BaseModel):
    """List available Cloudflare network services that prefixes can be bound to"""

    operation: Literal["list_addressing_services"] = Field(
        default="list_addressing_services",
        title="List Addressing Services",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "List Addressing Services", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})

class CloudflareUploadLOADocumentConfig(BaseModel):
    """Upload a Letter of Authorization (LOA) PDF document for BYOIP prefix ownership verification"""

    operation: Literal["upload_loa_document"] = Field(
        default="upload_loa_document",
        title="Upload LOA Document",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Upload LOA Document", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    loa_document: str = Field(description="Base64-encoded PDF content of the LOA document")

class CloudflareDownloadLOADocumentConfig(BaseModel):
    """Download a previously uploaded Letter of Authorization document"""

    operation: Literal["download_loa_document"] = Field(
        default="download_loa_document",
        title="Download LOA Document",
        json_schema_extra={"x-category": "Addressing / BYOIP", "x-is-trigger": False, "x-display-name": "Download LOA Document", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Cloudflare account ID", json_schema_extra={"ui:hidden": True})
    loa_document_id: str = Field(description="LOA document ID to download")


# ─── Radar AI Config Models ────────────────────────────────────────────────────

_RADAR_DATE_RANGE_EXTRA = {
    "enum": ["1d", "7d", "14d", "28d", "12w", "24w", "52w", "1dcontrol", "7dcontrol", "28dcontrol"],
    "enumNames": ["1 Day", "7 Days", "14 Days", "28 Days", "12 Weeks", "24 Weeks", "52 Weeks", "1 Day Control", "7 Days Control", "28 Days Control"],
    "x-enum-searchable": True,
}
_RADAR_FORMAT_EXTRA = {"enum": ["JSON", "CSV"], "enumNames": ["JSON", "CSV"], "x-enum-searchable": True}
_RADAR_AGG_INTERVAL_EXTRA = {"enum": ["15m", "1h", "1d", "1w"], "enumNames": ["15 Minutes", "1 Hour", "1 Day", "1 Week"], "x-enum-searchable": True}

class CloudflareGetRadarAIInferenceSummaryByModelConfig(BaseModel):
    """Retrieve aggregated Workers AI inference counts grouped by model"""

    operation: Literal["get_radar_ai_inference_summary_by_model"] = Field(
        default="get_radar_ai_inference_summary_by_model",
        title="Get Radar AI Inference Summary by Model",
        json_schema_extra={"x-category": "Radar AI", "x-is-trigger": False, "x-display-name": "Get Radar AI Inference Summary by Model", "ui:hidden": True},
    )
    date_range: Optional[str] = Field(default=None, description="Shorthand date range filter", json_schema_extra=_RADAR_DATE_RANGE_EXTRA)
    date_start: Optional[str] = Field(default=None, description="Start of date range (ISO 8601)")
    date_end: Optional[str] = Field(default=None, description="End of date range (ISO 8601)")
    limit_per_group: Optional[str] = Field(default=None, description="Maximum number of groups to return; excess items are grouped under 'other'")
    format: Optional[str] = Field(default=None, description="Response format", json_schema_extra=_RADAR_FORMAT_EXTRA)

class CloudflareGetRadarAIInferenceSummaryByTaskConfig(BaseModel):
    """Retrieve aggregated Workers AI inference counts grouped by task type"""

    operation: Literal["get_radar_ai_inference_summary_by_task"] = Field(
        default="get_radar_ai_inference_summary_by_task",
        title="Get Radar AI Inference Summary by Task",
        json_schema_extra={"x-category": "Radar AI", "x-is-trigger": False, "x-display-name": "Get Radar AI Inference Summary by Task", "ui:hidden": True},
    )
    date_range: Optional[str] = Field(default=None, description="Shorthand date range filter", json_schema_extra=_RADAR_DATE_RANGE_EXTRA)
    date_start: Optional[str] = Field(default=None, description="Start of date range (ISO 8601)")
    date_end: Optional[str] = Field(default=None, description="End of date range (ISO 8601)")
    limit_per_group: Optional[str] = Field(default=None, description="Maximum number of groups to return; excess items are grouped under 'other'")
    format: Optional[str] = Field(default=None, description="Response format", json_schema_extra=_RADAR_FORMAT_EXTRA)

class CloudflareGetRadarAIInferenceTimeseriesByModelConfig(BaseModel):
    """Retrieve Workers AI inference distribution over time grouped by model"""

    operation: Literal["get_radar_ai_inference_timeseries_by_model"] = Field(
        default="get_radar_ai_inference_timeseries_by_model",
        title="Get Radar AI Inference Timeseries by Model",
        json_schema_extra={"x-category": "Radar AI", "x-is-trigger": False, "x-display-name": "Get Radar AI Inference Timeseries by Model", "ui:hidden": True},
    )
    agg_interval: Optional[str] = Field(default=None, description="Aggregation interval for timeseries data", json_schema_extra=_RADAR_AGG_INTERVAL_EXTRA)
    date_range: Optional[str] = Field(default=None, description="Shorthand date range filter", json_schema_extra=_RADAR_DATE_RANGE_EXTRA)
    date_start: Optional[str] = Field(default=None, description="Start of date range (ISO 8601)")
    date_end: Optional[str] = Field(default=None, description="End of date range (ISO 8601)")
    limit_per_group: Optional[str] = Field(default=None, description="Maximum number of groups to return")
    format: Optional[str] = Field(default=None, description="Response format", json_schema_extra=_RADAR_FORMAT_EXTRA)

class CloudflareGetRadarAIInferenceTimeseriesByTaskConfig(BaseModel):
    """Retrieve Workers AI inference distribution over time grouped by task type"""

    operation: Literal["get_radar_ai_inference_timeseries_by_task"] = Field(
        default="get_radar_ai_inference_timeseries_by_task",
        title="Get Radar AI Inference Timeseries by Task",
        json_schema_extra={"x-category": "Radar AI", "x-is-trigger": False, "x-display-name": "Get Radar AI Inference Timeseries by Task", "ui:hidden": True},
    )
    agg_interval: Optional[str] = Field(default=None, description="Aggregation interval for timeseries data", json_schema_extra=_RADAR_AGG_INTERVAL_EXTRA)
    date_range: Optional[str] = Field(default=None, description="Shorthand date range filter", json_schema_extra=_RADAR_DATE_RANGE_EXTRA)
    date_start: Optional[str] = Field(default=None, description="Start of date range (ISO 8601)")
    date_end: Optional[str] = Field(default=None, description="End of date range (ISO 8601)")
    limit_per_group: Optional[str] = Field(default=None, description="Maximum number of groups to return")
    format: Optional[str] = Field(default=None, description="Response format", json_schema_extra=_RADAR_FORMAT_EXTRA)


_RADAR_BOTS_DIM_EXTRA = {
    "enum": ["USER_AGENT", "CRAWL_PURPOSE", "INDUSTRY", "VERTICAL", "CONTENT_TYPE", "RESPONSE_STATUS", "RESPONSE_STATUS_CATEGORY"],
    "enumNames": ["User Agent", "Crawl Purpose", "Industry", "Vertical", "Content Type", "Response Status", "Response Status Category"],
    "x-enum-searchable": True,
}

class CloudflareGetRadarAIBotsSummaryConfig(BaseModel):
    """Retrieve aggregated summary of AI bot HTTP requests grouped by a specified dimension"""

    operation: Literal["get_radar_ai_bots_summary"] = Field(
        default="get_radar_ai_bots_summary",
        title="Get Radar AI Bots Summary",
        json_schema_extra={"x-category": "Radar AI", "x-is-trigger": False, "x-display-name": "Get Radar AI Bots Summary", "ui:hidden": True},
    )
    dimension: str = Field(description="Dimension to group by", json_schema_extra=_RADAR_BOTS_DIM_EXTRA)
    date_range: Optional[str] = Field(default=None, description="Shorthand date range filter", json_schema_extra=_RADAR_DATE_RANGE_EXTRA)
    date_start: Optional[str] = Field(default=None, description="Start of date range (ISO 8601)")
    date_end: Optional[str] = Field(default=None, description="End of date range (ISO 8601)")
    user_agent: Optional[str] = Field(default=None, description="Filter by AI bot user agent name (e.g. GPTBot, ClaudeBot)")
    crawl_purpose: Optional[str] = Field(default=None, description="Filter by crawl purpose (e.g. AI, Search)")
    industry: Optional[str] = Field(default=None, description="Filter by industry category")
    limit_per_group: Optional[str] = Field(default=None, description="Maximum number of groups to return")
    format: Optional[str] = Field(default=None, description="Response format", json_schema_extra=_RADAR_FORMAT_EXTRA)

class CloudflareGetRadarAIBotsSummaryByUserAgentConfig(BaseModel):
    """Retrieve the distribution of AI bot traffic grouped by user agent"""

    operation: Literal["get_radar_ai_bots_summary_by_user_agent"] = Field(
        default="get_radar_ai_bots_summary_by_user_agent",
        title="Get Radar AI Bots Summary by User Agent",
        json_schema_extra={"x-category": "Radar AI", "x-is-trigger": False, "x-display-name": "Get Radar AI Bots Summary by User Agent", "ui:hidden": True},
    )
    date_range: Optional[str] = Field(default=None, description="Shorthand date range filter", json_schema_extra=_RADAR_DATE_RANGE_EXTRA)
    date_start: Optional[str] = Field(default=None, description="Start of date range (ISO 8601)")
    date_end: Optional[str] = Field(default=None, description="End of date range (ISO 8601)")
    asn: Optional[str] = Field(default=None, description="Filter by Autonomous System Number (e.g. AS15169)")
    continent: Optional[str] = Field(default=None, description="Filter by continent code (e.g. EU, NA, AS, SA, AF, OC)")
    location: Optional[str] = Field(default=None, description="Filter by two-letter ISO country code (e.g. US, DE, GB)")
    limit_per_group: Optional[str] = Field(default=None, description="Maximum number of groups to return")
    format: Optional[str] = Field(default=None, description="Response format", json_schema_extra=_RADAR_FORMAT_EXTRA)

class CloudflareGetRadarAIBotsTimeseriesConfig(BaseModel):
    """Retrieve AI bot HTTP request volume over time"""

    operation: Literal["get_radar_ai_bots_timeseries"] = Field(
        default="get_radar_ai_bots_timeseries",
        title="Get Radar AI Bots Timeseries",
        json_schema_extra={"x-category": "Radar AI", "x-is-trigger": False, "x-display-name": "Get Radar AI Bots Timeseries", "ui:hidden": True},
    )
    agg_interval: Optional[str] = Field(default=None, description="Aggregation interval", json_schema_extra=_RADAR_AGG_INTERVAL_EXTRA)
    date_range: Optional[str] = Field(default=None, description="Shorthand date range filter", json_schema_extra=_RADAR_DATE_RANGE_EXTRA)
    date_start: Optional[str] = Field(default=None, description="Start of date range (ISO 8601)")
    date_end: Optional[str] = Field(default=None, description="End of date range (ISO 8601)")
    user_agent: Optional[str] = Field(default=None, description="Filter by AI bot user agent name")
    crawl_purpose: Optional[str] = Field(default=None, description="Filter by crawl purpose")
    industry: Optional[str] = Field(default=None, description="Filter by industry category")
    asn: Optional[str] = Field(default=None, description="Filter by Autonomous System Number")
    continent: Optional[str] = Field(default=None, description="Filter by continent code")
    location: Optional[str] = Field(default=None, description="Filter by two-letter ISO country code")
    format: Optional[str] = Field(default=None, description="Response format", json_schema_extra=_RADAR_FORMAT_EXTRA)

class CloudflareGetRadarAIBotsTimeseriesGroupsConfig(BaseModel):
    """Retrieve AI bot HTTP request distribution grouped by the specified dimension over time"""

    operation: Literal["get_radar_ai_bots_timeseries_groups"] = Field(
        default="get_radar_ai_bots_timeseries_groups",
        title="Get Radar AI Bots Timeseries Groups",
        json_schema_extra={"x-category": "Radar AI", "x-is-trigger": False, "x-display-name": "Get Radar AI Bots Timeseries Groups", "ui:hidden": True},
    )
    dimension: str = Field(description="Dimension to group by", json_schema_extra=_RADAR_BOTS_DIM_EXTRA)
    agg_interval: Optional[str] = Field(default=None, description="Aggregation interval", json_schema_extra=_RADAR_AGG_INTERVAL_EXTRA)
    normalization: Optional[str] = Field(
        default=None,
        description="Normalization method for timeseries values",
        json_schema_extra={"enum": ["PERCENTAGE", "MIN0_MAX", "PERCENTAGE_CHANGE"], "enumNames": ["Percentage", "Min-Max Normalized", "Percentage Change"], "x-enum-searchable": True},
    )
    date_range: Optional[str] = Field(default=None, description="Shorthand date range filter", json_schema_extra=_RADAR_DATE_RANGE_EXTRA)
    date_start: Optional[str] = Field(default=None, description="Start of date range (ISO 8601)")
    date_end: Optional[str] = Field(default=None, description="End of date range (ISO 8601)")
    user_agent: Optional[str] = Field(default=None, description="Filter by AI bot user agent name")
    crawl_purpose: Optional[str] = Field(default=None, description="Filter by crawl purpose")
    industry: Optional[str] = Field(default=None, description="Filter by industry category")
    limit_per_group: Optional[str] = Field(default=None, description="Maximum number of groups to return")
    format: Optional[str] = Field(default=None, description="Response format", json_schema_extra=_RADAR_FORMAT_EXTRA)

class CloudflareGetRadarAIBotsTimeseriesByUserAgentConfig(BaseModel):
    """Retrieve AI bot request distribution grouped by user agent over time"""

    operation: Literal["get_radar_ai_bots_timeseries_by_user_agent"] = Field(
        default="get_radar_ai_bots_timeseries_by_user_agent",
        title="Get Radar AI Bots Timeseries by User Agent",
        json_schema_extra={"x-category": "Radar AI", "x-is-trigger": False, "x-display-name": "Get Radar AI Bots Timeseries by User Agent", "ui:hidden": True},
    )
    agg_interval: Optional[str] = Field(default=None, description="Aggregation interval", json_schema_extra=_RADAR_AGG_INTERVAL_EXTRA)
    date_range: Optional[str] = Field(default=None, description="Shorthand date range filter", json_schema_extra=_RADAR_DATE_RANGE_EXTRA)
    date_start: Optional[str] = Field(default=None, description="Start of date range (ISO 8601)")
    date_end: Optional[str] = Field(default=None, description="End of date range (ISO 8601)")
    asn: Optional[str] = Field(default=None, description="Filter by Autonomous System Number")
    continent: Optional[str] = Field(default=None, description="Filter by continent code")
    location: Optional[str] = Field(default=None, description="Filter by two-letter ISO country code")
    limit_per_group: Optional[str] = Field(default=None, description="Maximum number of groups to return")
    format: Optional[str] = Field(default=None, description="Response format", json_schema_extra=_RADAR_FORMAT_EXTRA)

class CloudflareGetRadarAIBotsSummaryByCrawlPurposeConfig(BaseModel):
    """Retrieve the distribution of AI bot traffic grouped by crawl purpose"""

    operation: Literal["get_radar_ai_bots_summary_by_crawl_purpose"] = Field(
        default="get_radar_ai_bots_summary_by_crawl_purpose",
        title="Get Radar AI Bots Summary by Crawl Purpose",
        json_schema_extra={"x-category": "Radar AI", "x-is-trigger": False, "x-display-name": "Get Radar AI Bots Summary by Crawl Purpose", "ui:hidden": True},
    )
    date_range: Optional[str] = Field(default=None, description="Shorthand date range filter", json_schema_extra=_RADAR_DATE_RANGE_EXTRA)
    date_start: Optional[str] = Field(default=None, description="Start of date range (ISO 8601)")
    date_end: Optional[str] = Field(default=None, description="End of date range (ISO 8601)")
    user_agent: Optional[str] = Field(default=None, description="Filter by AI bot user agent name")
    asn: Optional[str] = Field(default=None, description="Filter by Autonomous System Number")
    location: Optional[str] = Field(default=None, description="Filter by two-letter ISO country code")
    limit_per_group: Optional[str] = Field(default=None, description="Maximum number of groups to return")
    format: Optional[str] = Field(default=None, description="Response format", json_schema_extra=_RADAR_FORMAT_EXTRA)

class CloudflareGetRadarAIBotsSummaryByIndustryConfig(BaseModel):
    """Retrieve the distribution of AI bot traffic grouped by industry sector"""

    operation: Literal["get_radar_ai_bots_summary_by_industry"] = Field(
        default="get_radar_ai_bots_summary_by_industry",
        title="Get Radar AI Bots Summary by Industry",
        json_schema_extra={"x-category": "Radar AI", "x-is-trigger": False, "x-display-name": "Get Radar AI Bots Summary by Industry", "ui:hidden": True},
    )
    date_range: Optional[str] = Field(default=None, description="Shorthand date range filter", json_schema_extra=_RADAR_DATE_RANGE_EXTRA)
    date_start: Optional[str] = Field(default=None, description="Start of date range (ISO 8601)")
    date_end: Optional[str] = Field(default=None, description="End of date range (ISO 8601)")
    user_agent: Optional[str] = Field(default=None, description="Filter by AI bot user agent name")
    crawl_purpose: Optional[str] = Field(default=None, description="Filter by crawl purpose")
    asn: Optional[str] = Field(default=None, description="Filter by Autonomous System Number")
    location: Optional[str] = Field(default=None, description="Filter by two-letter ISO country code")
    limit_per_group: Optional[str] = Field(default=None, description="Maximum number of groups to return")
    format: Optional[str] = Field(default=None, description="Response format", json_schema_extra=_RADAR_FORMAT_EXTRA)


# ─── URL Scanner Config Models ─────────────────────────────────────────────────

class CloudflareSubmitUrlScanConfig(BaseModel):
    """Submit a URL for scanning"""

    operation: Literal["submit_url_scan"] = Field(
        default="submit_url_scan",
        title="Submit URL Scan",
        json_schema_extra={"x-category": "URL Scanner", "x-is-trigger": False, "x-display-name": "Submit URL Scan", "ui:hidden": True},
    )
    url: str = Field(description="The URL to scan")
    visibility: Optional[str] = Field(
        default=None,
        description="Scan visibility: Public or Unlisted",
        json_schema_extra={"enum": ["Public", "Unlisted"], "x-enum-searchable": True},
    )
    screenshots_resolutions: Optional[str] = Field(
        default=None,
        description="Comma-separated device types for screenshots: desktop, mobile, tablet",
        json_schema_extra={"ui:placeholder": "desktop,mobile,tablet"},
    )
    country: Optional[str] = Field(default=None, description="ISO country code for geo-egress location (e.g. US, GB, FR)", json_schema_extra={"ui:placeholder": "US"})
    custom_agent: Optional[str] = Field(default=None, description="Custom User-Agent string for the scan")
    referer: Optional[str] = Field(default=None, description="HTTP Referer header value")

class CloudflareBulkSubmitUrlScansConfig(BaseModel):
    """Bulk submit up to 100 URLs for scanning"""

    operation: Literal["bulk_submit_url_scans"] = Field(
        default="bulk_submit_url_scans",
        title="Bulk Submit URL Scans",
        json_schema_extra={"x-category": "URL Scanner", "x-is-trigger": False, "x-display-name": "Bulk Submit URL Scans", "ui:hidden": True},
    )
    urls: str = Field(
        description="Newline-separated list of URLs to scan (up to 100)",
        json_schema_extra={"ui:widget": "code_editor", "ui:placeholder": "https://example.com\nhttps://example.org", "ui:rows": 6},
    )
    visibility: Optional[str] = Field(
        default=None,
        description="Scan visibility for all submitted URLs: Public or Unlisted",
        json_schema_extra={"enum": ["Public", "Unlisted"], "x-enum-searchable": True},
    )
    country: Optional[str] = Field(default=None, description="ISO country code for geo-egress location", json_schema_extra={"ui:placeholder": "US"})

class CloudflareGetUrlScanConfig(BaseModel):
    """Retrieve the full report for a completed URL scan"""

    operation: Literal["get_url_scan"] = Field(
        default="get_url_scan",
        title="Get URL Scan Result",
        json_schema_extra={"x-category": "URL Scanner", "x-is-trigger": False, "x-display-name": "Get URL Scan Result", "ui:hidden": True},
    )
    scan_id: str = Field(description="The UUID of the scan to retrieve")

class CloudflareSearchUrlScansConfig(BaseModel):
    """Search completed URL scans using ElasticSearch Query syntax"""

    operation: Literal["search_url_scans"] = Field(
        default="search_url_scans",
        title="Search URL Scans",
        json_schema_extra={"x-category": "URL Scanner", "x-is-trigger": False, "x-display-name": "Search URL Scans", "ui:hidden": True},
    )
    query: Optional[str] = Field(default=None, description='ElasticSearch query string (e.g. page.domain:"example.com", verdicts.malicious:true, apikey:me)', json_schema_extra={"ui:placeholder": 'page.domain:"example.com"'})
    size: Optional[str] = Field(default=None, description="Maximum number of results to return")

class CloudflareGetUrlScanHarConfig(BaseModel):
    """Retrieve the HAR file for a completed URL scan"""

    operation: Literal["get_url_scan_har"] = Field(
        default="get_url_scan_har",
        title="Get URL Scan HAR",
        json_schema_extra={"x-category": "URL Scanner", "x-is-trigger": False, "x-display-name": "Get URL Scan HAR", "ui:hidden": True},
    )
    scan_id: str = Field(description="The UUID of the scan")

class CloudflareGetUrlScanScreenshotConfig(BaseModel):
    """Retrieve the screenshot captured during a URL scan"""

    operation: Literal["get_url_scan_screenshot"] = Field(
        default="get_url_scan_screenshot",
        title="Get URL Scan Screenshot",
        json_schema_extra={"x-category": "URL Scanner", "x-is-trigger": False, "x-display-name": "Get URL Scan Screenshot", "ui:hidden": True},
    )
    scan_id: str = Field(description="The UUID of the scan")
    resolution: Optional[str] = Field(
        default=None,
        description="Device resolution for the screenshot",
        json_schema_extra={"enum": ["desktop", "mobile", "tablet"], "enumNames": ["Desktop", "Mobile", "Tablet"], "x-enum-searchable": True},
    )

class CloudflareGetUrlScanDomConfig(BaseModel):
    """Retrieve the DOM content as rendered by Chrome during a URL scan"""

    operation: Literal["get_url_scan_dom"] = Field(
        default="get_url_scan_dom",
        title="Get URL Scan DOM",
        json_schema_extra={"x-category": "URL Scanner", "x-is-trigger": False, "x-display-name": "Get URL Scan DOM", "ui:hidden": True},
    )
    scan_id: str = Field(description="The UUID of the scan")


# ─── Bot Management Extensions ─────────────────────────────────────────────────

class CloudflareGetBotManagementAnalyticsConfig(BaseModel):
    """Retrieve bot analytics and feedback reports containing request score distributions for a zone"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["get_bot_management_analytics"] = Field(
        default="get_bot_management_analytics",
        title="Get Bot Analytics",
        json_schema_extra={"x-category": "Bot Management", "x-is-trigger": False, "x-display-name": "Get Bot Analytics", "ui:hidden": True},
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })

class CloudflareListBotFeedbackReportsConfig(BaseModel):
    """List all previously submitted bot feedback reports for a zone"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["list_bot_feedback_reports"] = Field(
        default="list_bot_feedback_reports",
        title="List Bot Feedback Reports",
        json_schema_extra={"x-category": "Bot Management", "x-is-trigger": False, "x-display-name": "List Bot Feedback Reports", "ui:hidden": True},
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })

class CloudflareSubmitBotFeedbackConfig(BaseModel):
    """Submit a feedback report about misclassified bot traffic using a wirefilter expression"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["submit_bot_feedback"] = Field(
        default="submit_bot_feedback",
        title="Submit Bot Feedback",
        json_schema_extra={"x-category": "Bot Management", "x-is-trigger": False, "x-display-name": "Submit Bot Feedback", "ui:hidden": True},
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    feedback_type: str = Field(
        description="Type of misclassification",
        json_schema_extra={"enum": ["false_positive", "false_negative"], "x-enum-searchable": True},
    )
    expression: str = Field(description="Wirefilter expression identifying the affected traffic")
    description: str = Field(description="Description of the misclassified traffic pattern")
    requests: Optional[int] = Field(default=None, description="Total number of requests in the sample")
    first_request_seen_at: Optional[str] = Field(default=None, description="ISO 8601 timestamp of the first affected request")
    last_request_seen_at: Optional[str] = Field(default=None, description="ISO 8601 timestamp of the last affected request")

class CloudflareGetBotScoreThresholdsConfig(BaseModel):
    """Retrieve current bot score action thresholds for a zone"""

    operation: Literal["get_bot_score_thresholds"] = Field(
        default="get_bot_score_thresholds",
        title="Get Score Thresholds",
        json_schema_extra={"x-category": "Bot Management", "x-is-trigger": False, "x-display-name": "Get Score Thresholds", "ui:hidden": True},
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })

class CloudflareUpdateBotScoreThresholdsConfig(BaseModel):
    """Update bot score action thresholds for Super Bot Fight Mode"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "paid", "x-tier-label": "Paid"})
    operation: Literal["update_bot_score_thresholds"] = Field(
        default="update_bot_score_thresholds",
        title="Update Score Thresholds",
        json_schema_extra={"x-category": "Bot Management", "x-is-trigger": False, "x-display-name": "Update Score Thresholds", "ui:hidden": True},
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    sbfm_definitely_automated: Optional[str] = Field(
        default=None,
        description="Action for traffic Cloudflare is certain is automated",
        json_schema_extra={"enum": ["allow", "block", "managed_challenge"], "x-enum-searchable": True},
    )
    sbfm_likely_automated: Optional[str] = Field(
        default=None,
        description="Action for traffic Cloudflare believes is likely automated",
        json_schema_extra={"enum": ["allow", "block", "managed_challenge"], "x-enum-searchable": True},
    )
    sbfm_verified_bots: Optional[str] = Field(
        default=None,
        description="Action for known good verified bots",
        json_schema_extra={"enum": ["allow", "block"], "x-enum-searchable": True},
    )
    sbfm_static_resource_protection: Optional[str] = Field(
        default=None,
        description="Enable protection for static resources like images and scripts",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    optimize_wordpress: Optional[str] = Field(
        default=None,
        description="Enable WordPress-specific optimizations for bot protection",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    ai_bots_protection: Optional[str] = Field(
        default=None,
        description="Protection level for AI scrapers and crawlers",
        json_schema_extra={"enum": ["block", "disabled", "only_on_ad_pages"], "x-enum-searchable": True},
    )
    content_bots_protection: Optional[str] = Field(
        default=None,
        description="Block low-score automated traffic targeting content",
        json_schema_extra={"enum": ["block", "disabled"], "x-enum-searchable": True},
    )
    crawler_protection: Optional[str] = Field(
        default=None,
        description="Enable link maze crawler punishment system",
        json_schema_extra={"enum": ["enabled", "disabled"], "x-enum-searchable": True},
    )

class CloudflareConfigureJavascriptDetectionConfig(BaseModel):
    """Configure JavaScript-based bot detection settings"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "enterprise", "x-tier-label": "Enterprise"})
    operation: Literal["configure_javascript_detection"] = Field(
        default="configure_javascript_detection",
        title="Configure JavaScript Detection",
        json_schema_extra={"x-category": "Bot Management", "x-is-trigger": False, "x-display-name": "Configure JavaScript Detection", "ui:hidden": True},
    )
    zone_id: str = Field(description="The zone ID", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "zone_id",
            "placeholder": "Select a zone...",
            "searchable": True,
            "allow_custom": True,
            "custom_placeholder": "Or paste Zone ID",
        }
    })
    enable_js: str = Field(
        description="Enable or disable JavaScript-based bot detection injection",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    bm_cookie_enabled: Optional[str] = Field(
        default=None,
        description="Enable the __cf_bm bot management cookie (Enterprise only)",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )
    suppress_session_score: Optional[str] = Field(
        default=None,
        description="Suppress session score aggregation from bot management responses",
        json_schema_extra={"enum": ["true", "false"], "x-enum-searchable": True},
    )


# ─── Workers AI Extensions ─────────────────────────────────────────────────────

class CloudflareAITextGenerationConfig(BaseModel):
    """Generate text using a Workers AI language model with structured message input"""

    operation: Literal["run_ai_text_generation"] = Field(
        default="run_ai_text_generation",
        title="Text Generation",
        json_schema_extra={"x-category": "Workers AI", "x-is-trigger": False, "x-display-name": "Text Generation", "ui:hidden": True},
    )
    model_name: str = Field(
        default="@cf/meta/llama-3.1-8b-instruct",
        description="Text generation model to use",
        json_schema_extra={
            "enum": [
                "@cf/meta/llama-3.1-8b-instruct", "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
                "@cf/meta/llama-3.2-1b-instruct", "@cf/meta/llama-3.2-3b-instruct",
                "@cf/meta/llama-3.2-11b-vision-instruct", "@cf/mistral/mistral-7b-instruct-v0.1",
                "@cf/google/gemma-7b-it", "@cf/microsoft/phi-2",
                "@cf/qwen/qwen1.5-14b-chat-awq", "@cf/tinyllama/tinyllama-1.1b-chat-v1.0",
            ],
            "x-enum-searchable": True,
        },
    )
    prompt: Optional[str] = Field(default=None, description="Text prompt for the model", json_schema_extra={"ui:widget": "textarea", "ui:rows": 3})
    system_prompt: Optional[str] = Field(default=None, description="System prompt to guide the model behavior", json_schema_extra={"ui:widget": "textarea", "ui:rows": 2})
    max_tokens: Optional[int] = Field(default=None, description="Maximum number of tokens to generate")
    temperature: Optional[float] = Field(default=None, description="Sampling temperature (0.0 = deterministic, 1.0 = most random)")
    stream: Optional[str] = Field(
        default="false",
        description="Whether to stream the response tokens",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )

class CloudflareAITextToImageConfig(BaseModel):
    """Generate an image from a text prompt using a Cloudflare diffusion model"""

    operation: Literal["run_ai_text_to_image"] = Field(
        default="run_ai_text_to_image",
        title="Text to Image",
        json_schema_extra={"x-category": "Workers AI", "x-is-trigger": False, "x-display-name": "Text to Image", "ui:hidden": True},
    )
    model_name: str = Field(
        default="@cf/stabilityai/stable-diffusion-xl-base-1.0",
        description="Text-to-image diffusion model to use",
        json_schema_extra={
            "enum": [
                "@cf/stabilityai/stable-diffusion-xl-base-1.0", "@cf/bytedance/stable-diffusion-xl-lightning",
                "@cf/lykon/dreamshaper-8-lcm", "@cf/runwayml/stable-diffusion-v1-5-img2img",
            ],
            "x-enum-searchable": True,
        },
    )
    prompt: str = Field(description="Text description of the image to generate", json_schema_extra={"ui:widget": "textarea", "ui:rows": 3})
    negative_prompt: Optional[str] = Field(default=None, description="Elements to exclude from the generated image")
    width: Optional[int] = Field(default=None, description="Output image width in pixels (default 1024)")
    height: Optional[int] = Field(default=None, description="Output image height in pixels (default 1024)")
    num_steps: Optional[int] = Field(default=None, description="Number of diffusion steps")
    guidance: Optional[float] = Field(default=None, description="Guidance scale")
    seed: Optional[int] = Field(default=None, description="Random seed for reproducible image generation")

class CloudflareAISpeechToTextConfig(BaseModel):
    """Transcribe audio to text using Whisper or another Workers AI ASR model"""

    operation: Literal["run_ai_speech_to_text"] = Field(
        default="run_ai_speech_to_text",
        title="Speech to Text (ASR)",
        json_schema_extra={"x-category": "Workers AI", "x-is-trigger": False, "x-display-name": "Speech to Text (ASR)", "ui:hidden": True},
    )
    model_name: str = Field(
        default="@cf/openai/whisper",
        description="Automatic speech recognition model to use",
        json_schema_extra={"enum": ["@cf/openai/whisper", "@cf/openai/whisper-large-v3-turbo"], "x-enum-searchable": True},
    )
    audio_url: str = Field(description="URL of the audio file to transcribe (MP3, WAV, OGG, FLAC supported)")
    source_lang: Optional[str] = Field(default=None, description="Source language code of the audio (e.g. en, fr, es — auto-detected if omitted)")
    target_lang: Optional[str] = Field(default=None, description="Target language for translation output (omit to transcribe only)")

class CloudflareAITranslationConfig(BaseModel):
    """Translate text between languages using a Workers AI translation model"""

    operation: Literal["run_ai_translation"] = Field(
        default="run_ai_translation",
        title="Translation",
        json_schema_extra={"x-category": "Workers AI", "x-is-trigger": False, "x-display-name": "Translation", "ui:hidden": True},
    )
    model_name: str = Field(
        default="@cf/meta/m2m100-1.2b",
        description="Translation model to use",
        json_schema_extra={"enum": ["@cf/meta/m2m100-1.2b"], "x-enum-searchable": True},
    )
    text: str = Field(description="Text to translate", json_schema_extra={"ui:widget": "textarea", "ui:rows": 3})
    target_lang: str = Field(description="Target language code (e.g. es, fr, de, zh, ar, pt)")
    source_lang: Optional[str] = Field(default=None, description="Source language code (auto-detected if not provided)")

class CloudflareAISummarizationConfig(BaseModel):
    """Summarize long text into a concise overview using a Workers AI model"""

    operation: Literal["run_ai_summarization"] = Field(
        default="run_ai_summarization",
        title="Summarization",
        json_schema_extra={"x-category": "Workers AI", "x-is-trigger": False, "x-display-name": "Summarization", "ui:hidden": True},
    )
    model_name: str = Field(
        default="@cf/facebook/bart-large-cnn",
        description="Summarization model to use",
        json_schema_extra={"enum": ["@cf/facebook/bart-large-cnn"], "x-enum-searchable": True},
    )
    input_text: str = Field(description="Text to summarize", json_schema_extra={"ui:widget": "textarea", "ui:rows": 5})
    max_length: Optional[int] = Field(default=None, description="Maximum length of the generated summary in tokens")

class CloudflareAITextEmbeddingsConfig(BaseModel):
    """Generate vector embeddings for text using a Workers AI embedding model"""

    operation: Literal["run_ai_text_embeddings"] = Field(
        default="run_ai_text_embeddings",
        title="Text Embeddings",
        json_schema_extra={"x-category": "Workers AI", "x-is-trigger": False, "x-display-name": "Text Embeddings", "ui:hidden": True},
    )
    model_name: str = Field(
        default="@cf/baai/bge-base-en-v1.5",
        description="Embeddings model to use",
        json_schema_extra={
            "enum": ["@cf/baai/bge-small-en-v1.5", "@cf/baai/bge-base-en-v1.5", "@cf/baai/bge-large-en-v1.5", "@cf/baai/bge-m3"],
            "x-enum-searchable": True,
        },
    )
    text: str = Field(description='Text to embed. For multiple texts provide a JSON array: ["text1", "text2"]', json_schema_extra={"ui:widget": "textarea", "ui:rows": 3})

class CloudflareAIImageClassificationConfig(BaseModel):
    """Classify an image into categories using a Workers AI vision model"""

    operation: Literal["run_ai_image_classification"] = Field(
        default="run_ai_image_classification",
        title="Image Classification",
        json_schema_extra={"x-category": "Workers AI", "x-is-trigger": False, "x-display-name": "Image Classification", "ui:hidden": True},
    )
    model_name: str = Field(
        default="@cf/microsoft/resnet-50",
        description="Image classification model to use",
        json_schema_extra={"enum": ["@cf/microsoft/resnet-50"], "x-enum-searchable": True},
    )
    image_url: str = Field(description="URL of the image to classify (JPEG, PNG, WEBP supported)")

class CloudflareAIObjectDetectionConfig(BaseModel):
    """Detect and locate objects within an image using a Workers AI model"""

    operation: Literal["run_ai_object_detection"] = Field(
        default="run_ai_object_detection",
        title="Object Detection",
        json_schema_extra={"x-category": "Workers AI", "x-is-trigger": False, "x-display-name": "Object Detection", "ui:hidden": True},
    )
    model_name: str = Field(
        default="@cf/facebook/detr-resnet-50",
        description="Object detection model to use",
        json_schema_extra={"enum": ["@cf/facebook/detr-resnet-50"], "x-enum-searchable": True},
    )
    image_url: str = Field(description="URL of the image to analyze for objects")

class CloudflareGetAIModelSchemaConfig(BaseModel):
    """Get the JSON schema definition for a Workers AI model's inputs and outputs"""

    operation: Literal["get_ai_model_schema"] = Field(
        default="get_ai_model_schema",
        title="Get Model Schema",
        json_schema_extra={"x-category": "Workers AI", "x-is-trigger": False, "x-display-name": "Get Model Schema", "ui:hidden": True},
    )
    model_name: str = Field(
        description="Model identifier to retrieve the schema for",
        json_schema_extra={
            "enum": [
                "@cf/meta/llama-3.1-8b-instruct", "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
                "@cf/stabilityai/stable-diffusion-xl-base-1.0", "@cf/openai/whisper",
                "@cf/meta/m2m100-1.2b", "@cf/baai/bge-base-en-v1.5",
                "@cf/facebook/detr-resnet-50", "@cf/microsoft/resnet-50",
                "@cf/facebook/bart-large-cnn", "@cf/huggingface/distilbert-sst-2-int8",
            ],
            "x-enum-searchable": True,
        },
    )

class CloudflareListAIFinetunesConfig(BaseModel):
    """List all fine-tuning jobs for the account"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "beta", "x-tier-label": "Beta"})
    operation: Literal["list_ai_finetunes"] = Field(
        default="list_ai_finetunes",
        title="List Fine-Tunes",
        json_schema_extra={"x-category": "Workers AI", "x-is-trigger": False, "x-display-name": "List Fine-Tunes", "ui:hidden": True},
    )

class CloudflareCreateAIFinetuneConfig(BaseModel):
    """Start a new fine-tuning job to customize a Workers AI model"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "beta", "x-tier-label": "Beta"})
    operation: Literal["create_ai_finetune"] = Field(
        default="create_ai_finetune",
        title="Create Fine-Tune",
        json_schema_extra={"x-category": "Workers AI", "x-is-trigger": False, "x-display-name": "Create Fine-Tune", "ui:hidden": True},
    )
    model: str = Field(description="Base Workers AI model to fine-tune (e.g. @cf/meta/llama-3.1-8b-instruct)")
    name: str = Field(description="Name for this fine-tuning job")
    description: Optional[str] = Field(default=None, description="Description of the fine-tuning job and its purpose")
    public: Optional[str] = Field(
        default="false",
        description="Whether to make the fine-tuned model publicly available",
        json_schema_extra={"enum": ["true", "false"], "enumNames": ["Yes", "No"], "x-enum-searchable": True},
    )

class CloudflareListPublicAIFinetunesConfig(BaseModel):
    """Find publicly available fine-tuned Workers AI models"""

    model_config = ConfigDict(json_schema_extra={"x-requires-tier": "beta", "x-tier-label": "Beta"})
    operation: Literal["list_public_ai_finetunes"] = Field(
        default="list_public_ai_finetunes",
        title="List Public Fine-Tunes",
        json_schema_extra={"x-category": "Workers AI", "x-is-trigger": False, "x-display-name": "List Public Fine-Tunes", "ui:hidden": True},
    )
    search: Optional[str] = Field(default=None, description="Search public fine-tunes by name or description")
    page: Optional[int] = Field(default=None, description="Page number for paginated results")
    per_page: Optional[int] = Field(default=None, description="Number of results per page (max 100)")

class CloudflareConvertFileToMarkdownConfig(BaseModel):
    """Convert a document or file to markdown format using Workers AI"""

    operation: Literal["convert_file_to_markdown"] = Field(
        default="convert_file_to_markdown",
        title="Convert File to Markdown",
        json_schema_extra={"x-category": "Workers AI", "x-is-trigger": False, "x-display-name": "Convert File to Markdown", "ui:hidden": True},
    )
    file_url: str = Field(description="URL of the file to convert to markdown (PDF, DOCX, HTML, etc.)")
    file_name: Optional[str] = Field(default=None, description="Original filename — helps with format detection (e.g. document.pdf)")

class CloudflareListAIAuthorsConfig(BaseModel):
    """Search for AI model authors and organizations on Workers AI"""

    operation: Literal["list_ai_authors"] = Field(
        default="list_ai_authors",
        title="Search AI Authors",
        json_schema_extra={"x-category": "Workers AI", "x-is-trigger": False, "x-display-name": "Search AI Authors", "ui:hidden": True},
    )
    search: Optional[str] = Field(default=None, description="Search term to filter authors by name (e.g. meta, openai, mistral)")

class CloudflareListAITasksConfig(BaseModel):
    """Search and list AI task types supported by Workers AI"""

    operation: Literal["list_ai_tasks"] = Field(
        default="list_ai_tasks",
        title="Search AI Task Types",
        json_schema_extra={"x-category": "Workers AI", "x-is-trigger": False, "x-display-name": "Search AI Task Types", "ui:hidden": True},
    )
    search: Optional[str] = Field(default=None, description="Search term to filter task types (e.g. generation, embeddings)")


# ─── R2 Event Notification Management Config Models ────────────────────────────

class CloudflareGetR2EventNotificationConfigConfig(BaseModel):
    """List all event notification rules configured for an R2 bucket across all queues"""

    operation: Literal["get_r2_event_notification_config"] = Field(
        default="get_r2_event_notification_config",
        title="Get R2 Event Notification Config",
        json_schema_extra={"x-category": "R2 Event Notifications", "x-is-trigger": False, "x-display-name": "Get R2 Event Notification Config", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Your Cloudflare Account ID", json_schema_extra={"ui:hidden": True})
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    jurisdiction: Optional[str] = Field(
        default=None,
        description="R2 jurisdiction scope",
        json_schema_extra={"enum": ["default", "eu", "fedramp"], "x-enum-searchable": True},
    )

class CloudflareGetR2EventNotificationQueueRulesConfig(BaseModel):
    """Get event notification rules for a specific queue within an R2 bucket"""

    operation: Literal["get_r2_event_notification_queue_rules"] = Field(
        default="get_r2_event_notification_queue_rules",
        title="Get R2 Event Notification Queue Rules",
        json_schema_extra={"x-category": "R2 Event Notifications", "x-is-trigger": False, "x-display-name": "Get R2 Event Notification Queue Rules", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Your Cloudflare Account ID", json_schema_extra={"ui:hidden": True})
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    queue_id: str = Field(description="The Queue ID to get notification rules for", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "queue_id",
            "placeholder": "Select a Queue...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    jurisdiction: Optional[str] = Field(
        default=None,
        description="R2 jurisdiction scope",
        json_schema_extra={"enum": ["default", "eu", "fedramp"], "x-enum-searchable": True},
    )

class CloudflarePutR2EventNotificationRulesConfig(BaseModel):
    """Create or update event notification rules for a queue on an R2 bucket"""

    operation: Literal["put_r2_event_notification_rules"] = Field(
        default="put_r2_event_notification_rules",
        title="Create/Update R2 Event Notification Rules",
        json_schema_extra={"x-category": "R2 Event Notifications", "x-is-trigger": False, "x-display-name": "Create/Update R2 Event Notification Rules", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Your Cloudflare Account ID", json_schema_extra={"ui:hidden": True})
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    queue_id: str = Field(description="The Queue ID that will receive event notifications", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "queue_id",
            "placeholder": "Select a Queue...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    actions: str = Field(
        description="Comma-separated event actions to capture (PutObject, CopyObject, DeleteObject, CompleteMultipartUpload, LifecycleDeletion)",
        json_schema_extra={
            "enum": [
                "PutObject", "CopyObject", "DeleteObject", "CompleteMultipartUpload", "LifecycleDeletion",
                "PutObject,CopyObject,CompleteMultipartUpload",
                "DeleteObject,LifecycleDeletion",
                "PutObject,CopyObject,CompleteMultipartUpload,DeleteObject,LifecycleDeletion",
            ],
            "x-enum-searchable": True,
        },
    )
    prefix: Optional[str] = Field(default=None, description="Object key prefix filter (e.g. uploads/)")
    suffix: Optional[str] = Field(default=None, description="Object key suffix filter (e.g. .jpg)")
    description: Optional[str] = Field(default=None, description="Human-readable label for this notification rule")
    jurisdiction: Optional[str] = Field(
        default=None,
        description="R2 jurisdiction scope",
        json_schema_extra={"enum": ["default", "eu", "fedramp"], "x-enum-searchable": True},
    )

class CloudflareDeleteR2EventNotificationRulesConfig(BaseModel):
    """Remove all event notification rules for a specific queue from an R2 bucket"""

    operation: Literal["delete_r2_event_notification_rules"] = Field(
        default="delete_r2_event_notification_rules",
        title="Delete R2 Event Notification Rules",
        json_schema_extra={"x-category": "R2 Event Notifications", "x-is-trigger": False, "x-display-name": "Delete R2 Event Notification Rules", "ui:hidden": True},
    )
    account_id: Optional[str] = Field(default=None, description="Your Cloudflare Account ID", json_schema_extra={"ui:hidden": True})
    bucket_name: str = Field(description="The R2 bucket name", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "bucket_name",
            "placeholder": "Select an R2 bucket...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    queue_id: str = Field(description="The Queue ID whose notification rules should be deleted", json_schema_extra={
        "x-dynamic-options": {
            "field_name": "queue_id",
            "placeholder": "Select a Queue...",
            "searchable": True,
            "allow_custom": True,
        }
    })
    jurisdiction: Optional[str] = Field(
        default=None,
        description="R2 jurisdiction scope",
        json_schema_extra={"enum": ["default", "eu", "fedramp"], "x-enum-searchable": True},
    )


# ─── R2 and Queue Trigger Extensions ──────────────────────────────────────────

CloudflareConfig = Union[
    # DNS
    CloudflareListDNSRecordsConfig,
    CloudflareCreateDNSRecordConfig,
    CloudflareGetDNSRecordConfig,
    CloudflareUpdateDNSRecordConfig,
    CloudflareDeleteDNSRecordConfig,
    # Zones
    CloudflareListZonesConfig,
    CloudflareGetZoneConfig,
    CloudflareGetZoneSettingsConfig,
    CloudflareUpdateZoneSettingConfig,
    CloudflarePurgeZoneCacheConfig,
    # Workers
    CloudflareListWorkersConfig,
    CloudflareGetWorkerConfig,
    CloudflareUploadWorkerConfig,
    CloudflareDeleteWorkerConfig,
    CloudflareListWorkerRoutesConfig,
    CloudflareCreateWorkerRouteConfig,
    CloudflareDeleteWorkerRouteConfig,
    # Workers KV
    CloudflareListKVNamespacesConfig,
    CloudflareCreateKVNamespaceConfig,
    CloudflareDeleteKVNamespaceConfig,
    CloudflareListKVKeysConfig,
    CloudflareReadKVValueConfig,
    CloudflareWriteKVValueConfig,
    CloudflareDeleteKVValueConfig,
    CloudflareBulkWriteKVConfig,
    # D1 Database
    CloudflareListD1DatabasesConfig,
    CloudflareGetD1DatabaseConfig,
    CloudflareCreateD1DatabaseConfig,
    CloudflareDeleteD1DatabaseConfig,
    CloudflareQueryD1DatabaseConfig,
    CloudflareExportD1DatabaseConfig,
    # R2 Storage
    CloudflareListR2BucketsConfig,
    CloudflareGetR2BucketConfig,
    CloudflareCreateR2BucketConfig,
    CloudflareDeleteR2BucketConfig,
    # Pages
    CloudflareListPagesProjectsConfig,
    CloudflareGetPagesProjectConfig,
    CloudflareDeletePagesProjectConfig,
    CloudflareListPagesDeploymentsConfig,
    CloudflareGetPagesDeploymentConfig,
    CloudflareDeletePagesDeploymentConfig,
    # Stream
    CloudflareListStreamVideosConfig,
    CloudflareGetStreamVideoConfig,
    CloudflareDeleteStreamVideoConfig,
    CloudflareGetStreamVideoEmbedConfig,
    CloudflareListStreamLiveInputsConfig,
    CloudflareCreateStreamLiveInputConfig,
    CloudflareDeleteStreamLiveInputConfig,
    # Stream Extended
    CloudflareCreateStreamUploadUrlConfig,
    CloudflareCreateStreamSignedUrlConfig,
    CloudflareListStreamSigningKeysConfig,
    CloudflareCreateStreamSigningKeyConfig,
    CloudflareDeleteStreamSigningKeyConfig,
    CloudflareListStreamCaptionsConfig,
    CloudflareUploadStreamCaptionConfig,
    CloudflareDeleteStreamCaptionConfig,
    CloudflareListStreamWatermarksConfig,
    CloudflareCreateStreamWatermarkConfig,
    CloudflareGetStreamWatermarkConfig,
    CloudflareDeleteStreamWatermarkConfig,
    CloudflareListStreamAudioTracksConfig,
    CloudflareAddStreamAudioTrackConfig,
    CloudflareEditStreamAudioTrackConfig,
    CloudflareDeleteStreamAudioTrackConfig,
    CloudflareUpdateStreamVideoConfig,
    # Images
    CloudflareListImagesConfig,
    CloudflareGetImageConfig,
    CloudflareDeleteImageConfig,
    CloudflareGetImagesStatsConfig,
    CloudflareCreateImageDirectUploadConfig,
    # Firewall / WAF
    CloudflareListFirewallRulesConfig,
    CloudflareCreateFirewallRuleConfig,
    CloudflareDeleteFirewallRuleConfig,
    CloudflareListWAFPackagesConfig,
    # Access (Zero Trust)
    CloudflareListAccessApplicationsConfig,
    CloudflareGetAccessApplicationConfig,
    CloudflareCreateAccessApplicationConfig,
    CloudflareDeleteAccessApplicationConfig,
    CloudflareListAccessPoliciesConfig,
    # Tunnels
    CloudflareListTunnelsConfig,
    CloudflareGetTunnelConfig,
    CloudflareCreateTunnelConfig,
    CloudflareDeleteTunnelConfig,
    CloudflareGetTunnelTokenConfig,
    # Email Routing
    CloudflareGetEmailRoutingConfig,
    CloudflareListEmailRoutingRulesConfig,
    CloudflareCreateEmailRoutingRuleConfig,
    CloudflareDeleteEmailRoutingRuleConfig,
    CloudflareListEmailRoutingAddressesConfig,
    # Queues
    CloudflareListQueuesConfig,
    CloudflareGetQueueConfig,
    CloudflareCreateQueueConfig,
    CloudflareDeleteQueueConfig,
    CloudflareSendQueueMessageConfig,
    CloudflarePullQueueMessagesConfig,
    # Workers AI
    CloudflareRunAIModelConfig,
    CloudflareListAIModelsConfig,
    # Vectorize
    CloudflareListVectorizeIndexesConfig,
    CloudflareGetVectorizeIndexConfig,
    CloudflareCreateVectorizeIndexConfig,
    CloudflareDeleteVectorizeIndexConfig,
    CloudflareUpsertVectorsConfig,
    CloudflareQueryVectorsConfig,
    CloudflareDeleteVectorsConfig,
    # Load Balancing
    CloudflareListLoadBalancersConfig,
    CloudflareGetLoadBalancerConfig,
    CloudflareCreateLoadBalancerConfig,
    CloudflareDeleteLoadBalancerConfig,
    CloudflareListLBPoolsConfig,
    CloudflareCreateLBPoolConfig,
    # SSL / TLS
    CloudflareGetSSLSettingsConfig,
    CloudflareListSSLCertificatesConfig,
    # Analytics
    CloudflareGetZoneAnalyticsConfig,
    # Workers - Secrets
    CloudflareListWorkerSecretsConfig,
    CloudflarePutWorkerSecretConfig,
    CloudflareDeleteWorkerSecretConfig,
    CloudflareBulkUpsertWorkerSecretsConfig,
    # Workers - Cron Triggers
    CloudflareGetWorkerCronTriggersConfig,
    CloudflareUpdateWorkerCronTriggersConfig,
    # Workers - Durable Objects
    CloudflareListDurableObjectNamespacesConfig,
    CloudflareListDurableObjectsConfig,
    # Workers - Routes
    CloudflareUpdateWorkerRouteConfig,
    # Pipelines
    CloudflareListPipelinesConfig,
    CloudflareGetPipelineConfig,
    CloudflareCreatePipelineConfig,
    CloudflareUpdatePipelineConfig,
    CloudflareDeletePipelineConfig,
    # Secrets Store
    CloudflareListSecretsStoresConfig,
    CloudflareCreateSecretsStoreConfig,
    CloudflareDeleteSecretsStoreConfig,
    CloudflareListStoreSecretsConfig,
    CloudflareGetStoreSecretConfig,
    CloudflareCreateStoreSecretConfig,
    CloudflareUpdateStoreSecretConfig,
    CloudflareDeleteStoreSecretConfig,
    # Rulesets - Zone
    CloudflareListZoneRulesetsConfig,
    CloudflareGetZoneRulesetConfig,
    CloudflareCreateZoneRulesetConfig,
    CloudflareUpdateZoneRulesetConfig,
    CloudflareDeleteZoneRulesetConfig,
    CloudflareGetZoneRulesetPhaseConfig,
    CloudflareUpdateZoneRulesetPhaseConfig,
    CloudflareCreateZoneRulesetRuleConfig,
    CloudflareDeleteZoneRulesetRuleConfig,
    # Rulesets - Account
    CloudflareListAccountRulesetsConfig,
    CloudflareGetAccountRulesetConfig,
    # Page Rules
    CloudflareListPageRulesConfig,
    CloudflareGetPageRuleConfig,
    CloudflareCreatePageRuleConfig,
    CloudflareUpdatePageRuleConfig,
    CloudflareDeletePageRuleConfig,
    # Rate Limiting
    CloudflareListRateLimitsConfig,
    CloudflareGetRateLimitConfig,
    CloudflareCreateRateLimitConfig,
    CloudflareUpdateRateLimitConfig,
    CloudflareDeleteRateLimitConfig,
    # Custom Hostnames
    CloudflareListCustomHostnamesConfig,
    CloudflareGetCustomHostnameConfig,
    CloudflareCreateCustomHostnameConfig,
    CloudflareUpdateCustomHostnameConfig,
    CloudflareDeleteCustomHostnameConfig,
    # Waiting Rooms
    CloudflareListWaitingRoomsConfig,
    CloudflareGetWaitingRoomConfig,
    CloudflareCreateWaitingRoomConfig,
    CloudflareUpdateWaitingRoomConfig,
    CloudflareDeleteWaitingRoomConfig,
    CloudflareGetWaitingRoomStatusConfig,
    CloudflareListWaitingRoomEventsConfig,
    CloudflareCreateWaitingRoomEventConfig,
    # Logpush
    CloudflareListAccountLogpushJobsConfig,
    CloudflareGetLogpushJobConfig,
    CloudflareCreateLogpushJobConfig,
    CloudflareUpdateLogpushJobConfig,
    CloudflareDeleteLogpushJobConfig,
    CloudflareListZoneLogpushJobsConfig,
    CloudflareCreateZoneLogpushJobConfig,
    CloudflareDeleteZoneLogpushJobConfig,
    # Audit Logs
    CloudflareListAuditLogsConfig,
    # Notifications / Alerting
    CloudflareListAvailableAlertsConfig,
    CloudflareListAlertPoliciesConfig,
    CloudflareGetAlertPolicyConfig,
    CloudflareCreateAlertPolicyConfig,
    CloudflareUpdateAlertPolicyConfig,
    CloudflareDeleteAlertPolicyConfig,
    CloudflareListNotificationWebhooksConfig,
    CloudflareCreateNotificationWebhookConfig,
    CloudflareUpdateNotificationWebhookConfig,
    CloudflareDeleteNotificationWebhookConfig,
    CloudflareGetNotificationHistoryConfig,
    # Health Checks
    CloudflareListHealthChecksConfig,
    CloudflareGetHealthCheckConfig,
    CloudflareCreateHealthCheckConfig,
    CloudflareUpdateHealthCheckConfig,
    CloudflareDeleteHealthCheckConfig,
    # Spectrum
    CloudflareListSpectrumAppsConfig,
    CloudflareGetSpectrumAppConfig,
    CloudflareCreateSpectrumAppConfig,
    CloudflareUpdateSpectrumAppConfig,
    CloudflareDeleteSpectrumAppConfig,
    # Snippets
    CloudflareListSnippetsConfig,
    CloudflareGetSnippetConfig,
    CloudflarePutSnippetConfig,
    CloudflareDeleteSnippetConfig,
    CloudflareListSnippetRulesConfig,
    # Zaraz
    CloudflareGetZarazConfigConfig,
    CloudflareUpdateZarazConfigConfig,
    CloudflarePublishZarazConfigConfig,
    # Bot Management
    CloudflareGetBotManagementConfig,
    CloudflareUpdateBotManagementConfig,
    # Speed Observatory
    CloudflareListObservatoryPagesConfig,
    CloudflareListPageSpeedTestsConfig,
    CloudflareCreatePageSpeedTestConfig,
    CloudflareDeletePageSpeedTestsConfig,
    CloudflareGetSpeedTestScheduleConfig,
    # Web Analytics
    CloudflareListWebAnalyticsSitesConfig,
    CloudflareCreateWebAnalyticsSiteConfig,
    CloudflareGetWebAnalyticsSiteConfig,
    CloudflareDeleteWebAnalyticsSiteConfig,
    # Account Members
    CloudflareListAccountMembersConfig,
    CloudflareGetAccountMemberConfig,
    CloudflareAddAccountMemberConfig,
    CloudflareUpdateAccountMemberConfig,
    CloudflareRemoveAccountMemberConfig,
    CloudflareListAccountRolesConfig,
    # Zero Trust - Tunnel Routes / Virtual Networks
    CloudflareListTunnelRoutesConfig,
    CloudflareCreateTunnelRouteConfig,
    CloudflareUpdateTunnelRouteConfig,
    CloudflareDeleteTunnelRouteConfig,
    CloudflareListVirtualNetworksConfig,
    CloudflareCreateVirtualNetworkConfig,
    CloudflareGetVirtualNetworkConfig,
    CloudflareUpdateVirtualNetworkConfig,
    CloudflareDeleteVirtualNetworkConfig,
    # Load Balancer Extensions
    CloudflareUpdateLoadBalancerConfig,
    CloudflareGetLBPoolConfig,
    CloudflareUpdateLBPoolConfig,
    CloudflareDeleteLBPoolConfig,
    CloudflareListLBMonitorsConfig,
    CloudflareGetLBMonitorConfig,
    CloudflareCreateLBMonitorConfig,
    CloudflareDeleteLBMonitorConfig,
    CloudflareGetLBPoolHealthConfig,
    # Access Extensions
    CloudflareCreateAccessPolicyConfig,
    CloudflareUpdateAccessPolicyConfig,
    CloudflareDeleteAccessPolicyConfig,
    CloudflareGetAccessPolicyConfig,
    CloudflareListAccessGroupsConfig,
    CloudflareGetAccessGroupConfig,
    CloudflareCreateAccessGroupConfig,
    CloudflareUpdateAccessGroupConfig,
    CloudflareDeleteAccessGroupConfig,
    CloudflareListAccessServiceTokensConfig,
    CloudflareCreateAccessServiceTokenConfig,
    CloudflareRefreshAccessServiceTokenConfig,
    CloudflareDeleteAccessServiceTokenConfig,
    # Tunnel Extensions
    CloudflareUpdateTunnelConfig,
    CloudflareGetTunnelConfigurationConfig,
    CloudflarePutTunnelConfigurationConfig,
    CloudflareListTunnelConnectionsConfig,
    # Email Routing Extensions
    CloudflareEnableEmailRoutingConfig,
    CloudflareDisableEmailRoutingConfig,
    CloudflareCreateEmailRoutingDestinationConfig,
    CloudflareDeleteEmailRoutingDestinationConfig,
    # Queue Extensions
    CloudflareUpdateQueueConfig,
    CloudflareAcknowledgeQueueMessagesConfig,
    CloudflareListQueueConsumersConfig,
    CloudflareCreateQueueConsumerConfig,
    CloudflareDeleteQueueConsumerConfig,
    # SSL / TLS Extensions
    CloudflareUpdateZoneSSLSettingsConfig,
    CloudflareUploadSSLCertificateConfig,
    CloudflareDeleteSSLCertificateConfig,
    # Pages Extensions
    CloudflareCreatePagesProjectConfig,
    CloudflareRetryPagesDeploymentConfig,
    # DNS Extensions
    CloudflareExportDNSRecordsConfig,
    CloudflareGetDNSSECConfig,
    CloudflareUpdateDNSSECConfig,
    # R2 Object Operations
    CloudflareListR2ObjectsConfig,
    CloudflareGetR2ObjectConfig,
    CloudflarePutR2ObjectConfig,
    CloudflareDeleteR2ObjectConfig,
    CloudflareGetR2PresignedUrlConfig,
    # Triggers
    CloudflareAlertTriggerConfig,
    CloudflareAuditLogTriggerConfig,
    # Zone Management extended
    CloudflareCreateZoneConfig,
    CloudflareDeleteZoneConfig,
    CloudflareEditZoneConfig,
    CloudflareZoneActivationCheckConfig,
    # Rules Lists
    CloudflareListRulesListsConfig,
    CloudflareCreateRulesListConfig,
    CloudflareGetRulesListConfig,
    CloudflareUpdateRulesListConfig,
    CloudflareDeleteRulesListConfig,
    CloudflareListRulesListItemsConfig,
    CloudflareCreateRulesListItemsConfig,
    CloudflareReplaceRulesListItemsConfig,
    CloudflareDeleteRulesListItemsConfig,
    CloudflareGetRulesListOperationConfig,
    # Worker Versions & Deployments & Tails
    CloudflareListWorkerVersionsConfig,
    CloudflareUploadWorkerVersionConfig,
    CloudflareGetWorkerVersionConfig,
    CloudflareListWorkerDeploymentsConfig,
    CloudflareCreateWorkerDeploymentConfig,
    CloudflareGetWorkerDeploymentConfig,
    CloudflareListWorkerTailsConfig,
    CloudflareStartWorkerTailConfig,
    CloudflareDeleteWorkerTailConfig,
    # AI Gateway
    CloudflareListAIGatewaysConfig,
    CloudflareCreateAIGatewayConfig,
    CloudflareGetAIGatewayConfig,
    CloudflareUpdateAIGatewayConfig,
    CloudflareDeleteAIGatewayConfig,
    CloudflareListAIGatewayLogsConfig,
    CloudflareGetAIGatewayLogConfig,
    CloudflareDeleteAIGatewayLogsConfig,
    CloudflareGetAIGatewayLogRequestConfig,
    CloudflareGetAIGatewayLogResponseConfig,
    CloudflareListAIGatewayDatasetsConfig,
    CloudflareCreateAIGatewayDatasetConfig,
    CloudflareDeleteAIGatewayDatasetConfig,
    # Images extended
    CloudflareListImageVariantsConfig,
    CloudflareCreateImageVariantConfig,
    CloudflareGetImageVariantConfig,
    CloudflareUpdateImageVariantConfig,
    CloudflareDeleteImageVariantConfig,
    CloudflareListImageSigningKeysConfig,
    CloudflareCreateImageSigningKeyConfig,
    CloudflareDeleteImageSigningKeyConfig,
    CloudflareUpdateImageMetadataConfig,
    # D1 extended
    CloudflareListD1TablesConfig,
    CloudflareImportD1DataConfig,
    CloudflareGetD1ImportStatusConfig,
    CloudflareExecuteD1RawQueryConfig,
    # Zero Trust Gateway
    CloudflareGetGatewayConfigurationConfig,
    CloudflareUpdateGatewayConfigurationConfig,
    CloudflareListGatewayRulesConfig,
    CloudflareCreateGatewayRuleConfig,
    CloudflareGetGatewayRuleConfig,
    CloudflareUpdateGatewayRuleConfig,
    CloudflareDeleteGatewayRuleConfig,
    CloudflareListGatewayListsConfig,
    CloudflareCreateGatewayListConfig,
    CloudflareGetGatewayListConfig,
    CloudflareUpdateGatewayListConfig,
    CloudflareDeleteGatewayListConfig,
    CloudflareListGatewayListItemsConfig,
    CloudflareListGatewayLocationsConfig,
    CloudflareCreateGatewayLocationConfig,
    CloudflareGetGatewayLocationConfig,
    CloudflareDeleteGatewayLocationConfig,
    # Page Shield
    CloudflareGetPageShieldSettingsConfig,
    CloudflareUpdatePageShieldSettingsConfig,
    CloudflareListPageShieldScriptsConfig,
    CloudflareGetPageShieldScriptConfig,
    CloudflareListPageShieldConnectionsConfig,
    CloudflareGetPageShieldConnectionConfig,
    CloudflareListPageShieldPoliciesConfig,
    CloudflareCreatePageShieldPolicyConfig,
    CloudflareDeletePageShieldPolicyConfig,
    # Cache extended
    CloudflareGetCacheReserveConfig,
    CloudflareUpdateCacheReserveConfig,
    CloudflareGetArgoSmartRoutingConfig,
    CloudflareUpdateArgoSmartRoutingConfig,
    CloudflareGetTieredCachingConfig,
    CloudflareUpdateTieredCachingConfig,
    CloudflarePurgeCacheEverythingConfig,
    CloudflareGetZoneSettingsAllConfig,
    # R2 extended
    CloudflareGetR2CORSPolicyConfig,
    CloudflarePutR2CORSPolicyConfig,
    CloudflareDeleteR2CORSPolicyConfig,
    CloudflareGetR2LifecycleRulesConfig,
    CloudflarePutR2LifecycleRulesConfig,
    CloudflareDeleteR2LifecycleRulesConfig,
    CloudflareListR2CustomDomainsConfig,
    CloudflareCreateR2CustomDomainConfig,
    CloudflareUpdateR2CustomDomainConfig,
    CloudflareDeleteR2CustomDomainConfig,
    CloudflareGetR2ManagedDomainConfig,
    CloudflareUpdateR2ManagedDomainConfig,
    CloudflareGetR2BucketDetailsConfig,
    CloudflareUpdateR2BucketConfig,
    # Poll Triggers
    CloudflareQueueMessageTriggerConfig,
    CloudflarePagesDeployTriggerConfig,
    CloudflareR2NewObjectTriggerConfig,
    CloudflareDNSChangeTriggerConfig,
    CloudflareHealthCheckStatusTriggerConfig,
    # Webhook Trigger
    CloudflareStreamEventTriggerConfig,
    # Access
    CloudflareListIdentityProvidersConfig,
    CloudflareGetIdentityProviderConfig,
    CloudflareCreateIdentityProviderConfig,
    CloudflareUpdateIdentityProviderConfig,
    CloudflareDeleteIdentityProviderConfig,
    CloudflareListAccessUsersConfig,
    CloudflareGetAccessUserConfig,
    CloudflareListAccessUserSessionsConfig,
    CloudflareRevokeAccessUserSessionConfig,
    CloudflareGetAccessOrganizationConfig,
    CloudflareUpdateAccessOrganizationConfig,
    CloudflareCreateAccessKeyRotationConfig,
    # Secondary DNS
    CloudflareGetSecondaryDNSConfigConfig,
    CloudflareUpdateSecondaryDNSConfigConfig,
    CloudflareListSecondaryDNSPeersConfig,
    CloudflareCreateSecondaryDNSPeerConfig,
    CloudflareGetSecondaryDNSPeerConfig,
    CloudflareUpdateSecondaryDNSPeerConfig,
    CloudflareDeleteSecondaryDNSPeerConfig,
    # Analytics Engine
    CloudflareQueryAnalyticsEngineConfig,
    # Regional Tiered Cache
    CloudflareGetRegionalTieredCacheConfig,
    CloudflareUpdateRegionalTieredCacheConfig,
    # Vectorize extended
    CloudflareGetVectorizeIndexInfoConfig,
    CloudflareListVectorizeMetadataIndexesConfig,
    CloudflareCreateVectorizeMetadataIndexConfig,
    CloudflareDeleteVectorizeMetadataIndexConfig,
    CloudflareGetVectorizeVectorsByIdsConfig,
    # Fonts
    CloudflareGetFontsSettingsConfig,
    CloudflareUpdateFontsSettingsConfig,
    # NEL
    CloudflareGetNELSettingsConfig,
    CloudflareUpdateNELSettingsConfig,
    # API Shield
    CloudflareGetAPIShieldSettingsConfig,
    CloudflareUpdateAPIShieldSettingsConfig,
    CloudflareListAPIShieldEndpointsConfig,
    CloudflareCreateAPIShieldEndpointConfig,
    # WAF extended
    CloudflareGetWAFPackageConfig,
    CloudflareListWAFPackageRuleGroupsConfig,
    CloudflareListWAFPackageRulesConfig,
    CloudflareUpdateWAFRuleConfig,
    # Early Hints
    CloudflareGetEarlyHintsSettingConfig,
    CloudflareUpdateEarlyHintsSettingConfig,
    # HTTP/3
    CloudflareGetHTTP3SettingConfig,
    CloudflareUpdateHTTP3SettingConfig,
    # Brotli
    CloudflareGetBrotliSettingConfig,
    CloudflareUpdateBrotliSettingConfig,
    # Intel
    CloudflareAddIntelFeedPermissionConfig,
    CloudflareCreateIntelIndicatorFeedConfig,
    CloudflareCreateIntelMiscategorizationConfig,
    CloudflareDismissAttackSurfaceIssueConfig,
    CloudflareGetAttackSurfaceIssuesBySeverityConfig,
    CloudflareGetAttackSurfaceIssuesByTypeConfig,
    CloudflareGetIntelASNConfig,
    CloudflareGetIntelASNSubnetsConfig,
    CloudflareGetIntelDNSConfig,
    CloudflareGetIntelDomainConfig,
    CloudflareGetIntelDomainBulkConfig,
    CloudflareGetIntelDomainHistoryConfig,
    CloudflareGetIntelIndicatorFeedConfig,
    CloudflareGetIntelIndicatorFeedDataConfig,
    CloudflareGetIntelIPConfig,
    CloudflareGetIntelWHOISConfig,
    CloudflareListAttackSurfaceIssueTypesConfig,
    CloudflareListAttackSurfaceIssuesConfig,
    CloudflareListIntelFeedPermissionsConfig,
    CloudflareListIntelIndicatorFeedsConfig,
    CloudflareListIntelSinkholesConfig,
    CloudflareRemoveIntelFeedPermissionConfig,
    CloudflareUpdateIntelIndicatorFeedConfig,
    # Magic Transit
    CloudflareCreateMagicAppConfig,
    CloudflareCreateMagicGRETunnelConfig,
    CloudflareDeleteMagicAppConfig,
    CloudflareDeleteMagicGRETunnelConfig,
    CloudflareGetMagicCFInterconnectConfig,
    CloudflareGetMagicGRETunnelConfig,
    CloudflareListMagicAppsConfig,
    CloudflareListMagicCFInterconnectsConfig,
    CloudflareListMagicGRETunnelsConfig,
    CloudflareUpdateMagicAppConfig,
    CloudflareUpdateMagicCFInterconnectConfig,
    CloudflareUpdateMagicGRETunnelConfig,
    # Calls
    CloudflareCreateCallsAppConfig,
    CloudflareCreateCallsTurnKeyConfig,
    CloudflareDeleteCallsAppConfig,
    CloudflareDeleteCallsTurnKeyConfig,
    CloudflareGetCallsAppConfig,
    CloudflareGetCallsTurnKeyConfig,
    CloudflareListCallsAppsConfig,
    CloudflareListCallsTurnKeysConfig,
    CloudflareUpdateCallsAppConfig,
    CloudflareUpdateCallsTurnKeyConfig,
    # Analytics Engine SQL API extensions
    CloudflareGetAnalyticsEngineDatasetSchemaConfig,
    CloudflareGetAnalyticsEngineEventCountConfig,
    CloudflareListAnalyticsEngineDatasetsConfig,
    CloudflareListAnalyticsEngineTimezonesConfig,
    CloudflareQueryAnalyticsEngineAggregatedConfig,
    CloudflareQueryAnalyticsEngineRawConfig,
    CloudflareQueryAnalyticsEngineTimeseriesConfig,
    CloudflareQueryAnalyticsEngineTopValuesConfig,
    CloudflareQueryAnalyticsEngineWeightedAvgConfig,
    # Log Explorer
    CloudflareCreateLogExplorerDatasetConfig,
    CloudflareDeleteCMBConfigConfig,
    CloudflareGetCMBConfigConfig,
    CloudflareGetLogExplorerDatasetConfig,
    CloudflareGetLogRetentionFlagConfig,
    CloudflareGetLogpullFieldsConfig,
    CloudflareGetLogpullLogsConfig,
    CloudflareGetLogpullRayIDConfig,
    CloudflareListLogExplorerAvailableDatasetsConfig,
    CloudflareListLogExplorerDatasetsConfig,
    CloudflareQueryLogExplorerSQLConfig,
    CloudflareUpdateCMBConfigConfig,
    CloudflareUpdateLogExplorerDatasetConfig,
    CloudflareUpdateLogRetentionFlagConfig,
    # Addressing / BYOIP
    CloudflareAddIPToAddressMapConfig,
    CloudflareAddZoneToAddressMapConfig,
    CloudflareCreateAddressMapConfig,
    CloudflareCreateIPPrefixConfig,
    CloudflareCreatePrefixDelegationConfig,
    CloudflareCreatePrefixServiceBindingConfig,
    CloudflareCreateRegionalHostnameConfig,
    CloudflareDeleteAddressMapConfig,
    CloudflareDeleteIPPrefixConfig,
    CloudflareDeletePrefixDelegationConfig,
    CloudflareDeletePrefixServiceBindingConfig,
    CloudflareDeleteRegionalHostnameConfig,
    CloudflareDownloadLOADocumentConfig,
    CloudflareGetAddressMapConfig,
    CloudflareGetBGPAdvertisementStatusConfig,
    CloudflareGetIPPrefixConfig,
    CloudflareGetPrefixServiceBindingConfig,
    CloudflareGetRegionalHostnameConfig,
    CloudflareListAddressMapsConfig,
    CloudflareListAddressingServicesConfig,
    CloudflareListBGPPrefixesConfig,
    CloudflareListIPPrefixesConfig,
    CloudflareListPrefixDelegationsConfig,
    CloudflareListPrefixServiceBindingsConfig,
    CloudflareListRegionalHostnameRegionsConfig,
    CloudflareListRegionalHostnamesConfig,
    CloudflareRemoveIPFromAddressMapConfig,
    CloudflareRemoveZoneFromAddressMapConfig,
    CloudflareUpdateAddressMapConfig,
    CloudflareUpdateBGPPrefixConfig,
    CloudflareUpdateBGPAdvertisementConfig,
    CloudflareUpdateIPPrefixConfig,
    CloudflareUpdateRegionalHostnameConfig,
    CloudflareUploadLOADocumentConfig,
    # Radar AI
    CloudflareGetRadarAIBotsSummaryConfig,
    CloudflareGetRadarAIBotsSummaryByCrawlPurposeConfig,
    CloudflareGetRadarAIBotsSummaryByIndustryConfig,
    CloudflareGetRadarAIBotsSummaryByUserAgentConfig,
    CloudflareGetRadarAIBotsTimeseriesConfig,
    CloudflareGetRadarAIBotsTimeseriesByUserAgentConfig,
    CloudflareGetRadarAIBotsTimeseriesGroupsConfig,
    CloudflareGetRadarAIInferenceSummaryByModelConfig,
    CloudflareGetRadarAIInferenceSummaryByTaskConfig,
    CloudflareGetRadarAIInferenceTimeseriesByModelConfig,
    CloudflareGetRadarAIInferenceTimeseriesByTaskConfig,
    # URL Scanner
    CloudflareGetUrlScanConfig,
    CloudflareGetUrlScanDomConfig,
    CloudflareGetUrlScanHarConfig,
    CloudflareGetUrlScanScreenshotConfig,
    CloudflareBulkSubmitUrlScansConfig,
    CloudflareSearchUrlScansConfig,
    CloudflareSubmitUrlScanConfig,
    # Bot Management extensions
    CloudflareGetBotManagementAnalyticsConfig,
    CloudflareGetBotScoreThresholdsConfig,
    CloudflareUpdateBotScoreThresholdsConfig,
    CloudflareConfigureJavascriptDetectionConfig,
    CloudflareListBotFeedbackReportsConfig,
    CloudflareSubmitBotFeedbackConfig,
    # Workers AI extensions
    CloudflareCreateAIFinetuneConfig,
    CloudflareGetAIModelSchemaConfig,
    CloudflareListAIAuthorsConfig,
    CloudflareListAIFinetunesConfig,
    CloudflareListAITasksConfig,
    CloudflareListPublicAIFinetunesConfig,
    CloudflareAIImageClassificationConfig,
    CloudflareAIObjectDetectionConfig,
    CloudflareAISpeechToTextConfig,
    CloudflareAISummarizationConfig,
    CloudflareAITextEmbeddingsConfig,
    CloudflareAITextGenerationConfig,
    CloudflareAITextToImageConfig,
    CloudflareAITranslationConfig,
    CloudflareConvertFileToMarkdownConfig,
    # R2 Event Notifications
    CloudflareDeleteR2EventNotificationRulesConfig,
    CloudflareGetR2EventNotificationConfigConfig,
    CloudflareGetR2EventNotificationQueueRulesConfig,
    CloudflarePutR2EventNotificationRulesConfig,
    # Additional Triggers
    CloudflareR2ObjectEventTriggerConfig,
    CloudflareQueueDeliveryEventTriggerConfig,
    CloudflareDDoSAlertTriggerConfig,
    CloudflareSSLAlertTriggerConfig,
    CloudflareTunnelAlertTriggerConfig,
    CloudflareWorkerAlertTriggerConfig,
    CloudflareLoadBalancerAlertTriggerConfig,
    CloudflareWaitingRoomAlertTriggerConfig,
    CloudflarePageShieldAlertTriggerConfig,
    CloudflareZeroTrustAlertTriggerConfig,
    CloudflareEmailRoutingAlertTriggerConfig,
    CloudflareMagicTransitAlertTriggerConfig,
    CloudflareWorkerDeployedTriggerConfig,
    CloudflareD1NewRowsTriggerConfig,
    CloudflareKVKeyUpdatedTriggerConfig,
]


class CloudflareNodeConfig(NodeConfig[CloudflareConfig, CloudflareCredential]):
    """Full configuration for the Cloudflare node including credentials."""

    pass


# ─── Node Implementation ────────────────────────────────────────────────────────


class CloudflareNode(ExternalWebhookTriggerMixin, ScheduledPollTriggerMixin, WorkflowNode):
    """Cloudflare automation node supporting DNS, Workers, KV, D1, R2, Pages, and more."""

    edit_examples = [
        "Create a DNS A record pointing to api.example.com",
        "List files in the backup bucket on R2 storage",
        "Upload a new image to the CDN cache bucket",
        "Purge all files matching example.com/* from cache",
        "Update KV namespace to store latest deploy version",
        "Deploy a Worker script to handle API rate limiting",
        "Create a new zone and configure email routing",
    ]

    scope_registry = CLOUDFLARE_SCOPES
    connection_evidence = ConnectionEvidence(
        operation="list_zones",
        noun="domains",
    )

    @classmethod
    def get_config_model(cls):
        return CloudflareNodeConfig

    # Inline "Create new <resource>" builder affordances: map each resource-picker
    # dropdown field to the resource its create op produces. Stamped as an
    # x-resource-type sibling of x-dynamic-options in get_config_schema below;
    # the create ops carry the matching x-resource-type + x-resource-id-path.
    _DROPDOWN_RESOURCE_TYPES: Dict[str, str] = {
        "zone_id": "cloudflare_zone",
        "namespace_id": "cloudflare_kv_namespace",
        "database_id": "cloudflare_d1_database",
        "bucket_name": "cloudflare_r2_bucket",
        "queue_id": "cloudflare_queue",
        "project_name": "cloudflare_pages_project",
        "tunnel_id": "cloudflare_tunnel",
        "gateway_id": "cloudflare_ai_gateway",
        "index_name": "cloudflare_vectorize_index",
        "pipeline_id": "cloudflare_pipeline",
        "lb_id": "cloudflare_load_balancer",
        "pool_id": "cloudflare_lb_pool",
        "health_check_id": "cloudflare_health_check",
        "access_app_id": "cloudflare_access_application",
        "worker_script_name": "cloudflare_worker_script",
    }

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Stamp x-resource-type onto resource-picker dropdowns (keyed by the
        dropdown's field_name) so a create op and its picker share a resource
        type — the builder's inline create-resource affordance pairs on that."""
        schema = super().get_config_schema()

        def walk(node):
            if isinstance(node, dict):
                props = node.get("properties")
                if isinstance(props, dict):
                    for fschema in props.values():
                        if isinstance(fschema, dict):
                            dyn = fschema.get("x-dynamic-options")
                            if isinstance(dyn, dict):
                                rt = cls._DROPDOWN_RESOURCE_TYPES.get(dyn.get("field_name"))
                                if rt and "x-resource-type" not in fschema:
                                    fschema["x-resource-type"] = rt
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(schema)
        return schema

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        """Refresh an expiring Cloudflare OAuth token at load time (dropdowns, trigger registration)."""
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.cloudflare_oauth import refresh_access_token

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=refresh_access_token,
            provider="cloudflare",
        )

    @classmethod
    async def load_field_value(
        cls,
        field_name: str,
        user_id: str,
        workflow_id,
        node_id: str,
        pool,
        context=None,
        credential_ids=None,
    ) -> Dict[str, Any]:
        if field_name == "webhook_url":
            from utils.webhook_manager import WebhookManager
            webhook_data = await WebhookManager.get_or_create_webhook(
                pool=pool,
                user_id=user_id,
                workflow_id=workflow_id,
                node_id=node_id,
            )
            return {
                "values": {
                    "webhook_id": webhook_data.get("webhook_id"),
                    "webhook_url": webhook_data.get("webhook_url"),
                    "relay_connected": webhook_data.get("relay_connected"),
                    "is_production": webhook_data.get("is_production"),
                }
            }
        if field_name == "account_id":
            existing = (context or {}).get("account_id") or ""
            if existing:
                return {"value": existing}
            if credential_ids:
                from utils.credential_loader import load_credential
                for cred_id in credential_ids.values():
                    if not cred_id:
                        continue
                    try:
                        cred_data = await load_credential(pool, user_id, str(cred_id))
                        if cred_data is None:
                            continue
                        account_id = cred_data.get("account_id")
                        if account_id:
                            return {"value": account_id}
                        # Fallback: fetch directly from CF API using the stored access/api token
                        access_token = (
                            cred_data.get("access_token")
                            or cred_data.get("api_token")
                            or cred_data.get("api_key")
                        )
                        if access_token:
                            import httpx as _httpx
                            async with _httpx.AsyncClient(timeout=10) as _hc:
                                _resp = await _hc.get(
                                    "https://api.cloudflare.com/client/v4/accounts",
                                    headers={"Authorization": f"Bearer {access_token}"},
                                    params={"per_page": 1},
                                )
                                if _resp.status_code == 200:
                                    _accounts = _resp.json().get("result", [])
                                    if _accounts:
                                        return {"value": _accounts[0]["id"]}
                    except Exception:
                        continue
            return {"value": ""}
        return {"value": None}

    @classmethod
    async def load_field_options(
        cls,
        field_name: str,
        credential_data: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        page_token: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Load dynamic dropdown options for Cloudflare resource fields."""
        # Resolve auth token and account_id from credential_data
        token = (
            credential_data.get("access_token")
            or credential_data.get("api_token")
            or credential_data.get("api_key")
        )
        if not token:
            return {"options": []}

        credential_type = credential_data.get("credential_type", "cloudflare_api_token")
        if credential_type == "cloudflare_api_key":
            headers = {
                "X-Auth-Key": token,
                "X-Auth-Email": credential_data.get("email", ""),
                "Content-Type": "application/json",
            }
        else:
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

        account_id = credential_data.get("account_id", "")
        ctx = context or {}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:

                if field_name == "zone_id":
                    params: Dict[str, Any] = {"per_page": 50}
                    if search:
                        params["name"] = search
                    r = await client.get(f"{BASE_URL}/zones", headers=headers, params=params)
                    r.raise_for_status()
                    zones = r.json().get("result") or []
                    return {"options": [{"label": z["name"], "value": z["id"]} for z in zones]}

                if field_name == "worker_script_name":
                    if not account_id:
                        return {"options": []}
                    r = await client.get(f"{BASE_URL}/accounts/{account_id}/workers/scripts", headers=headers)
                    r.raise_for_status()
                    scripts = r.json().get("result") or []
                    return {"options": [{"label": s["id"], "value": s["id"]} for s in scripts]}

                if field_name == "namespace_id":
                    if not account_id:
                        return {"options": []}
                    r = await client.get(
                        f"{BASE_URL}/accounts/{account_id}/storage/kv/namespaces",
                        headers=headers,
                        params={"per_page": 100},
                    )
                    r.raise_for_status()
                    namespaces = r.json().get("result") or []
                    return {"options": [{"label": ns["title"], "value": ns["id"]} for ns in namespaces]}

                if field_name == "database_id":
                    if not account_id:
                        return {"options": []}
                    r = await client.get(
                        f"{BASE_URL}/accounts/{account_id}/d1/database",
                        headers=headers,
                        params={"per_page": 100},
                    )
                    r.raise_for_status()
                    dbs = r.json().get("result") or []
                    return {"options": [{"label": db["name"], "value": db["uuid"]} for db in dbs]}

                if field_name == "bucket_name":
                    if not account_id:
                        return {"options": []}
                    r = await client.get(
                        f"{BASE_URL}/accounts/{account_id}/r2/buckets",
                        headers=headers,
                    )
                    r.raise_for_status()
                    buckets = (r.json().get("result") or {}).get("buckets") or []
                    return {"options": [{"label": b["name"], "value": b["name"]} for b in buckets]}

                if field_name == "queue_id":
                    if not account_id:
                        return {"options": []}
                    r = await client.get(
                        f"{BASE_URL}/accounts/{account_id}/queues",
                        headers=headers,
                        params={"per_page": 100},
                    )
                    r.raise_for_status()
                    queues = r.json().get("result") or []
                    return {"options": [{"label": q["queue_name"], "value": q["queue_id"]} for q in queues]}

                if field_name == "project_name":
                    if not account_id:
                        return {"options": []}
                    r = await client.get(
                        f"{BASE_URL}/accounts/{account_id}/pages/projects",
                        headers=headers,
                    )
                    r.raise_for_status()
                    projects = r.json().get("result") or []
                    return {"options": [{"label": p["name"], "value": p["name"]} for p in projects]}

                if field_name == "tunnel_id":
                    if not account_id:
                        return {"options": []}
                    r = await client.get(
                        f"{BASE_URL}/accounts/{account_id}/cfd_tunnel",
                        headers=headers,
                        params={"per_page": 50, "is_deleted": "false"},
                    )
                    r.raise_for_status()
                    tunnels = r.json().get("result") or []
                    return {"options": [{"label": f"{t['name']} ({t['id']})", "value": t["id"]} for t in tunnels]}

                if field_name in ("gateway_slug", "gateway_id"):
                    if not account_id:
                        return {"options": []}
                    r = await client.get(
                        f"{BASE_URL}/accounts/{account_id}/ai-gateway/gateways",
                        headers=headers,
                        params={"per_page": 50},
                    )
                    r.raise_for_status()
                    gateways = r.json().get("result") or []
                    return {"options": [{"label": g["name"], "value": g["id"]} for g in gateways]}

                if field_name == "index_name":
                    if not account_id:
                        return {"options": []}
                    r = await client.get(
                        f"{BASE_URL}/accounts/{account_id}/vectorize/v2/indexes",
                        headers=headers,
                    )
                    r.raise_for_status()
                    indexes = r.json().get("result") or []
                    return {"options": [{"label": i["name"], "value": i["name"]} for i in indexes]}

                if field_name in ("pipeline_name", "pipeline_id"):
                    if not account_id:
                        return {"options": []}
                    r = await client.get(
                        f"{BASE_URL}/accounts/{account_id}/pipelines",
                        headers=headers,
                    )
                    r.raise_for_status()
                    pipelines = r.json().get("result") or []
                    return {"options": [{"label": p["name"], "value": p["id"]} for p in pipelines]}

                if field_name == "store_id":
                    if not account_id:
                        return {"options": []}
                    r = await client.get(
                        f"{BASE_URL}/accounts/{account_id}/secrets-store/stores",
                        headers=headers,
                    )
                    r.raise_for_status()
                    stores = r.json().get("result") or []
                    return {"options": [{"label": s["name"], "value": s["id"]} for s in stores]}

                if field_name == "access_app_id":
                    if not account_id:
                        return {"options": []}
                    r = await client.get(
                        f"{BASE_URL}/accounts/{account_id}/access/apps",
                        headers=headers,
                    )
                    r.raise_for_status()
                    apps = r.json().get("result") or []
                    return {"options": [{"label": a["name"], "value": a["id"]} for a in apps]}

                if field_name == "health_check_id":
                    zone_id = ctx.get("zone_id")
                    if not zone_id:
                        return {"options": []}
                    r = await client.get(
                        f"{BASE_URL}/zones/{zone_id}/healthchecks",
                        headers=headers,
                    )
                    r.raise_for_status()
                    hcs = r.json().get("result") or []
                    return {"options": [{"label": hc["name"], "value": hc["id"]} for hc in hcs]}

                if field_name == "lb_id":
                    zone_id = ctx.get("zone_id")
                    if not zone_id:
                        return {"options": []}
                    r = await client.get(
                        f"{BASE_URL}/zones/{zone_id}/load_balancers",
                        headers=headers,
                    )
                    r.raise_for_status()
                    lbs = r.json().get("result") or []
                    return {"options": [{"label": lb["name"], "value": lb["id"]} for lb in lbs]}

                if field_name == "pool_id":
                    if not account_id:
                        return {"options": []}
                    r = await client.get(
                        f"{BASE_URL}/accounts/{account_id}/load_balancers/pools",
                        headers=headers,
                    )
                    r.raise_for_status()
                    pools = r.json().get("result") or []
                    return {"options": [{"label": p["name"], "value": p["id"]} for p in pools]}

                if field_name == "workers_ai_model":
                    if not account_id:
                        return {"options": []}
                    params = {"per_page": 100}
                    if search:
                        params["search"] = search
                    r = await client.get(
                        f"{BASE_URL}/accounts/{account_id}/ai/models/search",
                        headers=headers,
                        params=params,
                    )
                    r.raise_for_status()
                    models = r.json().get("result") or []
                    return {"options": [{"label": m["name"], "value": m["name"]} for m in models]}

        except Exception as _e:
            import httpx as _httpx
            if isinstance(_e, _httpx.HTTPStatusError) and _e.response.status_code in (400, 403, 404):
                logger.warning("load_field_options[%s]: %s %s", field_name, _e.response.status_code, _e.response.url)
            else:
                logger.exception("load_field_options failed for field_name=%s", field_name)

        return {"options": []}

    async def _ensure_fresh_token(self, credentials: CloudflareCredential) -> None:
        """Refresh an expired Cloudflare OAuth token in place. API tokens are long-lived."""
        if not isinstance(credentials, CloudflareOAuthCredential):
            return
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.cloudflare_oauth import refresh_access_token

        cred_dict = credentials.model_dump()
        await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=refresh_access_token,
            provider="cloudflare",
        )
        credentials.access_token = cred_dict["access_token"]

    def _get_headers(self, credentials: CloudflareCredential) -> Dict[str, str]:
        """Build authentication headers from credential type."""
        if isinstance(credentials, CloudflareOAuthCredential):
            return {
                "Authorization": f"Bearer {credentials.access_token}",
                "Content-Type": "application/json",
            }
        elif credentials.credential_type == "cloudflare_api_token":
            return {
                "Authorization": f"Bearer {credentials.api_token}",
                "Content-Type": "application/json",
            }
        else:
            return {
                "X-Auth-Key": credentials.api_key,
                "X-Auth-Email": credentials.email,
                "Content-Type": "application/json",
            }

    def _load_credentials(self, creds: Any) -> Optional["CloudflareCredential"]:
        """Return creds if it is a valid CloudflareCredential, else None."""
        if isinstance(creds, (CloudflareAPITokenCredential, CloudflareOAuthCredential)):
            return creds
        return None

    def _get_account_id(self, credentials: CloudflareCredential) -> Optional[str]:
        """Extract account_id from credentials if provided."""
        return getattr(credentials, "account_id", None)

    async def _resolve_account_id(self, credentials: CloudflareCredential) -> str:
        """Return account_id from credentials, auto-fetching for OAuth if not yet stored."""
        account_id = self._get_account_id(credentials)
        if account_id:
            return account_id
        if isinstance(credentials, CloudflareOAuthCredential):
            # Legacy OAuth credential minted before account_id was stored — fetch on demand.
            result = await self._request("GET", "/accounts", credentials, params={"per_page": 1})
            if result.get("status") == "success":
                accounts = result.get("result") or []
                if accounts:
                    account_id = accounts[0]["id"]
                    credentials.account_id = account_id  # cache for remainder of this execution
                    return account_id
        raise ValueError("account_id is required in credentials for this operation")

    async def _request(
        self,
        method: str,
        path: str,
        credentials: CloudflareCredential,
        *,
        params: Optional[Dict] = None,
        json: Optional[Any] = None,
        data: Optional[Any] = None,
        files: Optional[Any] = None,
        content_type_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Make an authenticated Cloudflare API request."""
        await self._ensure_fresh_token(credentials)
        headers = self._get_headers(credentials)
        if content_type_override:
            headers["Content-Type"] = content_type_override
        elif files is not None:
            # Let httpx set the multipart Content-Type + boundary itself.
            headers.pop("Content-Type", None)

        url = f"{BASE_URL}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(
                method,
                url,
                headers=headers,
                params={k: v for k, v in (params or {}).items() if v is not None},
                json=json,
                content=data,
                files=files,
            )

        try:
            result = response.json()
        except Exception:
            result = {"success": response.status_code < 300, "result": response.text}

        if not result.get("success", response.status_code < 300):
            errors = result.get("errors", [])
            error_msg = (
                "; ".join(e.get("message", str(e)) for e in errors)
                if errors
                else response.text
            )
            return {
                "status": "error",
                "error": error_msg,
                "status_code": response.status_code,
            }

        return {
            "status": "success",
            "result": result.get("result"),
            "result_info": result.get("result_info"),
        }

    async def _cf_request(
        self,
        method: str,
        path_or_url: str,
        credentials: CloudflareCredential,
        *,
        params: Optional[Dict] = None,
        json: Optional[Any] = None,
        data: Optional[Any] = None,
        content_type_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Like _request but accepts either a bare path or a full BASE_URL-prefixed URL."""
        path = path_or_url[len(BASE_URL):] if path_or_url.startswith(BASE_URL) else path_or_url
        return await self._request(method, path, credentials, params=params, json=json, data=data, content_type_override=content_type_override)

    # ── DNS ─────────────────────────────────────────────────────────────────────

    async def _list_dns_records(
        self, config: CloudflareListDNSRecordsConfig, creds: CloudflareCredential
    ) -> Dict:
        params = {}
        if config.record_type:
            params["type"] = config.record_type
        if config.name:
            params["name"] = config.name
        result = await self._request(
            "GET", f"/zones/{config.zone_id}/dns_records", creds, params=params
        )
        if result["status"] == "success":
            result["action"] = "list_dns_records"
        return result

    async def _create_dns_record(
        self, config: CloudflareCreateDNSRecordConfig, creds: CloudflareCredential
    ) -> Dict:
        import json as _json

        body = {
            "type": config.record_type,
            "name": config.name,
            "content": config.content,
            "ttl": config.ttl,
            "proxied": config.proxied == "true",
        }
        if config.priority is not None:
            body["priority"] = config.priority
        result = await self._request(
            "POST", f"/zones/{config.zone_id}/dns_records", creds, json=body
        )
        if result["status"] == "success":
            result["action"] = "create_dns_record"
        return result

    async def _get_dns_record(
        self, config: CloudflareGetDNSRecordConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"/zones/{config.zone_id}/dns_records/{config.record_id}", creds
        )
        if result["status"] == "success":
            result["action"] = "get_dns_record"
        return result

    async def _update_dns_record(
        self, config: CloudflareUpdateDNSRecordConfig, creds: CloudflareCredential
    ) -> Dict:
        body = {}
        if config.record_type:
            body["type"] = config.record_type
        if config.name:
            body["name"] = config.name
        if config.content:
            body["content"] = config.content
        if config.ttl is not None:
            body["ttl"] = config.ttl
        if config.proxied is not None:
            body["proxied"] = config.proxied == "true"
        result = await self._request(
            "PATCH",
            f"/zones/{config.zone_id}/dns_records/{config.record_id}",
            creds,
            json=body,
        )
        if result["status"] == "success":
            result["action"] = "update_dns_record"
        return result

    async def _delete_dns_record(
        self, config: CloudflareDeleteDNSRecordConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "DELETE", f"/zones/{config.zone_id}/dns_records/{config.record_id}", creds
        )
        if result["status"] == "success":
            result["action"] = "delete_dns_record"
        return result

    # ── Zones ───────────────────────────────────────────────────────────────────

    async def _list_zones(
        self, config: CloudflareListZonesConfig, creds: CloudflareCredential
    ) -> Dict:
        params = {}
        if config.name:
            params["name"] = config.name
        if config.status:
            params["status"] = config.status
        result = await self._request("GET", "/zones", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_zones"
        return result

    async def _get_zone(
        self, config: CloudflareGetZoneConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request("GET", f"/zones/{config.zone_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_zone"
        return result

    async def _get_zone_settings(
        self, config: CloudflareGetZoneSettingsConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request("GET", f"/zones/{config.zone_id}/settings", creds)
        if result["status"] == "success":
            result["action"] = "get_zone_settings"
        return result

    async def _update_zone_setting(
        self, config: CloudflareUpdateZoneSettingConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "PATCH",
            f"/zones/{config.zone_id}/settings/{config.setting_id}",
            creds,
            json={"value": config.value},
        )
        if result["status"] == "success":
            result["action"] = "update_zone_setting"
        return result

    async def _purge_cache(
        self, config: CloudflarePurgeZoneCacheConfig, creds: CloudflareCredential
    ) -> Dict:
        body: Dict[str, Any] = {}
        if config.purge_all == "true":
            body["purge_everything"] = True
        else:
            if config.files:
                body["files"] = [f.strip() for f in config.files.split(",")]
            if config.tags:
                body["tags"] = [t.strip() for t in config.tags.split(",")]
            if config.hosts:
                body["hosts"] = [h.strip() for h in config.hosts.split(",")]
        result = await self._request(
            "POST", f"/zones/{config.zone_id}/purge_cache", creds, json=body
        )
        if result["status"] == "success":
            result["action"] = "purge_zone_cache"
        return result

    # ── Workers ─────────────────────────────────────────────────────────────────

    async def _account_path(self, creds: CloudflareCredential) -> str:
        acct_id = await self._resolve_account_id(creds)
        return f"/accounts/{acct_id}"

    async def _list_workers(
        self, config: CloudflareListWorkersConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/workers/scripts", creds
        )
        if result["status"] == "success":
            result["action"] = "list_workers"
        return result

    async def _get_worker(
        self, config: CloudflareGetWorkerConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET",
            f"{await self._account_path(creds)}/workers/scripts/{config.script_name}",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "get_worker"
        return result

    async def _upload_worker(
        self, config: CloudflareUploadWorkerConfig, creds: CloudflareCredential
    ) -> Dict:
        headers = self._get_headers(creds)
        headers["Content-Type"] = "application/javascript"
        url = f"{BASE_URL}{await self._account_path(creds)}/workers/scripts/{config.script_name}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.put(
                url,
                headers=headers,
                content=config.script_content.encode(),
            )
        try:
            result_data = response.json()
        except Exception:
            result_data = {
                "success": response.status_code < 300,
                "result": response.text,
            }

        if not result_data.get("success", response.status_code < 300):
            errors = result_data.get("errors", [])
            error_msg = (
                "; ".join(e.get("message", str(e)) for e in errors)
                if errors
                else response.text
            )
            return {
                "status": "error",
                "error": error_msg,
                "status_code": response.status_code,
            }

        return {
            "status": "success",
            "action": "upload_worker_script",
            "result": result_data.get("result"),
        }

    async def _delete_worker(
        self, config: CloudflareDeleteWorkerConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "DELETE",
            f"{await self._account_path(creds)}/workers/scripts/{config.script_name}",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "delete_worker"
        return result

    async def _list_worker_routes(
        self, config: CloudflareListWorkerRoutesConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"/zones/{config.zone_id}/workers/routes", creds
        )
        if result["status"] == "success":
            result["action"] = "list_worker_routes"
        return result

    async def _create_worker_route(
        self, config: CloudflareCreateWorkerRouteConfig, creds: CloudflareCredential
    ) -> Dict:
        body: Dict[str, Any] = {"pattern": config.pattern}
        if config.script_name:
            body["script"] = config.script_name
        result = await self._request(
            "POST", f"/zones/{config.zone_id}/workers/routes", creds, json=body
        )
        if result["status"] == "success":
            result["action"] = "create_worker_route"
        return result

    async def _delete_worker_route(
        self, config: CloudflareDeleteWorkerRouteConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "DELETE", f"/zones/{config.zone_id}/workers/routes/{config.route_id}", creds
        )
        if result["status"] == "success":
            result["action"] = "delete_worker_route"
        return result

    # ── Workers KV ──────────────────────────────────────────────────────────────

    async def _list_kv_namespaces(
        self, config: CloudflareListKVNamespacesConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/storage/kv/namespaces", creds
        )
        if result["status"] == "success":
            result["action"] = "list_kv_namespaces"
        return result

    async def _create_kv_namespace(
        self, config: CloudflareCreateKVNamespaceConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "POST",
            f"{await self._account_path(creds)}/storage/kv/namespaces",
            creds,
            json={"title": config.title},
        )
        if result["status"] == "success":
            result["action"] = "create_kv_namespace"
        return result

    async def _delete_kv_namespace(
        self, config: CloudflareDeleteKVNamespaceConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "DELETE",
            f"{await self._account_path(creds)}/storage/kv/namespaces/{config.namespace_id}",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "delete_kv_namespace"
        return result

    async def _list_kv_keys(
        self, config: CloudflareListKVKeysConfig, creds: CloudflareCredential
    ) -> Dict:
        params = {}
        if config.prefix:
            params["prefix"] = config.prefix
        if config.limit:
            params["limit"] = config.limit
        if config.cursor:
            params["cursor"] = config.cursor
        result = await self._request(
            "GET",
            f"{await self._account_path(creds)}/storage/kv/namespaces/{config.namespace_id}/keys",
            creds,
            params=params,
        )
        if result["status"] == "success":
            result["action"] = "list_kv_keys"
        return result

    async def _read_kv_value(
        self, config: CloudflareReadKVValueConfig, creds: CloudflareCredential
    ) -> Dict:
        headers = self._get_headers(creds)
        url = f"{BASE_URL}{await self._account_path(creds)}/storage/kv/namespaces/{config.namespace_id}/values/{config.key_name}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers)
        if response.status_code >= 400:
            return {
                "status": "error",
                "error": response.text,
                "status_code": response.status_code,
            }
        return {"status": "success", "action": "read_kv_value", "value": response.text}

    async def _write_kv_value(
        self, config: CloudflareWriteKVValueConfig, creds: CloudflareCredential
    ) -> Dict:
        params = {}
        if config.expiration_ttl:
            params["expiration_ttl"] = config.expiration_ttl
        headers = self._get_headers(creds)
        headers["Content-Type"] = "text/plain"
        url = f"{BASE_URL}{await self._account_path(creds)}/storage/kv/namespaces/{config.namespace_id}/values/{config.key_name}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.put(
                url, headers=headers, params=params, content=config.value.encode()
            )
        try:
            result_data = response.json()
        except Exception:
            result_data = {"success": response.status_code < 300}
        if not result_data.get("success", response.status_code < 300):
            return {
                "status": "error",
                "error": response.text,
                "status_code": response.status_code,
            }
        return {"status": "success", "action": "write_kv_value"}

    async def _delete_kv_value(
        self, config: CloudflareDeleteKVValueConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "DELETE",
            f"{await self._account_path(creds)}/storage/kv/namespaces/{config.namespace_id}/values/{config.key_name}",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "delete_kv_value"
        return result

    async def _bulk_write_kv(
        self, config: CloudflareBulkWriteKVConfig, creds: CloudflareCredential
    ) -> Dict:
        import json as _json

        try:
            pairs = _json.loads(config.pairs)
        except Exception as e:
            return {"status": "error", "error": f"Invalid JSON for pairs: {e}"}
        result = await self._request(
            "PUT",
            f"{await self._account_path(creds)}/storage/kv/namespaces/{config.namespace_id}/bulk",
            creds,
            json=pairs,
        )
        if result["status"] == "success":
            result["action"] = "bulk_write_kv_pairs"
        return result

    # ── D1 Database ──────────────────────────────────────────────────────────────

    async def _list_d1_databases(
        self, config: CloudflareListD1DatabasesConfig, creds: CloudflareCredential
    ) -> Dict:
        params = {}
        if config.name:
            params["name"] = config.name
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/d1/database", creds, params=params
        )
        if result["status"] == "success":
            result["action"] = "list_d1_databases"
        return result

    async def _get_d1_database(
        self, config: CloudflareGetD1DatabaseConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET",
            f"{await self._account_path(creds)}/d1/database/{config.database_id}",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "get_d1_database"
        return result

    async def _create_d1_database(
        self, config: CloudflareCreateD1DatabaseConfig, creds: CloudflareCredential
    ) -> Dict:
        body: Dict[str, Any] = {"name": config.name}
        if config.location:
            body["primary_location_hint"] = config.location
        result = await self._request(
            "POST", f"{await self._account_path(creds)}/d1/database", creds, json=body
        )
        if result["status"] == "success":
            result["action"] = "create_d1_database"
        return result

    async def _delete_d1_database(
        self, config: CloudflareDeleteD1DatabaseConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "DELETE",
            f"{await self._account_path(creds)}/d1/database/{config.database_id}",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "delete_d1_database"
        return result

    async def _query_d1_database(
        self, config: CloudflareQueryD1DatabaseConfig, creds: CloudflareCredential
    ) -> Dict:
        import json as _json

        body: Dict[str, Any] = {"sql": config.sql}
        if config.params:
            try:
                body["params"] = _json.loads(config.params)
            except Exception as e:
                return {"status": "error", "error": f"Invalid JSON for params: {e}"}
        result = await self._request(
            "POST",
            f"{await self._account_path(creds)}/d1/database/{config.database_id}/query",
            creds,
            json=body,
        )
        if result["status"] == "success":
            result["action"] = "execute_d1_sql_query"
        return result

    async def _export_d1_database(
        self, config: CloudflareExportD1DatabaseConfig, creds: CloudflareCredential
    ) -> Dict:
        body: Dict[str, Any] = {
            "output_format": config.output_format,
            "dump_options": {},
        }
        result = await self._request(
            "POST",
            f"{await self._account_path(creds)}/d1/database/{config.database_id}/export",
            creds,
            json=body,
        )
        if result["status"] == "success":
            result["action"] = "export_d1_database_as_sql"
        return result

    # ── R2 Storage ───────────────────────────────────────────────────────────────

    async def _list_r2_buckets(
        self, config: CloudflareListR2BucketsConfig, creds: CloudflareCredential
    ) -> Dict:
        params = {}
        if config.name_contains:
            params["name_contains"] = config.name_contains
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/r2/buckets", creds, params=params
        )
        if result["status"] == "success":
            result["action"] = "list_r2_buckets"
        return result

    async def _get_r2_bucket(
        self, config: CloudflareGetR2BucketConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/r2/buckets/{config.bucket_name}", creds
        )
        if result["status"] == "success":
            result["action"] = "get_r2_bucket"
        return result

    async def _create_r2_bucket(
        self, config: CloudflareCreateR2BucketConfig, creds: CloudflareCredential
    ) -> Dict:
        body: Dict[str, Any] = {"name": config.bucket_name}
        if config.location_hint:
            body["locationHint"] = config.location_hint
        if config.storage_class:
            body["storageClass"] = config.storage_class
        result = await self._request(
            "POST", f"{await self._account_path(creds)}/r2/buckets", creds, json=body
        )
        if result["status"] == "success":
            result["action"] = "create_r2_bucket"
        return result

    async def _delete_r2_bucket(
        self, config: CloudflareDeleteR2BucketConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "DELETE",
            f"{await self._account_path(creds)}/r2/buckets/{config.bucket_name}",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "delete_r2_bucket"
        return result


    # ── Pages ────────────────────────────────────────────────────────────────────

    async def _list_pages_projects(
        self, config: CloudflareListPagesProjectsConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/pages/projects", creds
        )
        if result["status"] == "success":
            result["action"] = "list_pages_projects"
        return result

    async def _get_pages_project(
        self, config: CloudflareGetPagesProjectConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET",
            f"{await self._account_path(creds)}/pages/projects/{config.project_name}",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "get_pages_project"
        return result

    async def _delete_pages_project(
        self, config: CloudflareDeletePagesProjectConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "DELETE",
            f"{await self._account_path(creds)}/pages/projects/{config.project_name}",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "delete_pages_project"
        return result

    async def _list_pages_deployments(
        self, config: CloudflareListPagesDeploymentsConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET",
            f"{await self._account_path(creds)}/pages/projects/{config.project_name}/deployments",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "list_pages_deployments"
        return result

    async def _get_pages_deployment(
        self, config: CloudflareGetPagesDeploymentConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET",
            f"{await self._account_path(creds)}/pages/projects/{config.project_name}/deployments/{config.deployment_id}",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "get_pages_deployment"
        return result

    async def _delete_pages_deployment(
        self, config: CloudflareDeletePagesDeploymentConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "DELETE",
            f"{await self._account_path(creds)}/pages/projects/{config.project_name}/deployments/{config.deployment_id}",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "delete_pages_deployment"
        return result

    # ── Stream ───────────────────────────────────────────────────────────────────

    async def _list_stream_videos(
        self, config: CloudflareListStreamVideosConfig, creds: CloudflareCredential
    ) -> Dict:
        params = {}
        if config.search:
            params["search"] = config.search
        if config.status:
            params["status"] = config.status
        if config.limit:
            params["limit"] = config.limit
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/stream", creds, params=params
        )
        if result["status"] == "success":
            result["action"] = "list_stream_videos"
        return result

    async def _get_stream_video(
        self, config: CloudflareGetStreamVideoConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/stream/{config.video_id}", creds
        )
        if result["status"] == "success":
            result["action"] = "get_stream_video"
        return result

    async def _delete_stream_video(
        self, config: CloudflareDeleteStreamVideoConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "DELETE", f"{await self._account_path(creds)}/stream/{config.video_id}", creds
        )
        if result["status"] == "success":
            result["action"] = "delete_stream_video"
        return result

    async def _get_stream_embed(
        self, config: CloudflareGetStreamVideoEmbedConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/stream/{config.video_id}/embed", creds
        )
        if result["status"] == "success":
            result["action"] = "get_stream_video_embed_code"
        return result

    async def _list_stream_live_inputs(
        self, config: CloudflareListStreamLiveInputsConfig, creds: CloudflareCredential
    ) -> Dict:
        params = {}
        if config.include_counts == "true":
            params["include_counts"] = "true"
        result = await self._request(
            "GET",
            f"{await self._account_path(creds)}/stream/live_inputs",
            creds,
            params=params,
        )
        if result["status"] == "success":
            result["action"] = "list_stream_live_inputs"
        return result

    async def _create_stream_live_input(
        self, config: CloudflareCreateStreamLiveInputConfig, creds: CloudflareCredential
    ) -> Dict:
        body: Dict[str, Any] = {"recording": {"mode": config.recording_mode}}
        if config.name:
            body["meta"] = {"name": config.name}
        result = await self._request(
            "POST", f"{await self._account_path(creds)}/stream/live_inputs", creds, json=body
        )
        if result["status"] == "success":
            result["action"] = "create_stream_live_input"
        return result

    async def _delete_stream_live_input(
        self, config: CloudflareDeleteStreamLiveInputConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "DELETE",
            f"{await self._account_path(creds)}/stream/live_inputs/{config.live_input_id}",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "delete_stream_live_input"
        return result

    # ── Stream Extended ──────────────────────────────────────────────────────────

    async def _create_stream_upload_url(
        self, config: CloudflareCreateStreamUploadUrlConfig, creds: CloudflareCredential
    ) -> Dict:
        body: Dict[str, Any] = {
            "maxDurationSeconds": config.max_duration_seconds or 3600,
            "requireSignedURLs": config.require_signed_urls == "true",
            "allowedOrigins": [o.strip() for o in config.allowed_origins.split(",") if config.allowed_origins] if config.allowed_origins else [],
        }
        if config.video_url:
            body["url"] = config.video_url
        result = await self._request(
            "POST", f"{await self._account_path(creds)}/stream", creds, json=body
        )
        if result["status"] == "success":
            result["action"] = "create_stream_upload_url"
        return result

    async def _create_stream_signed_url(
        self, config: CloudflareCreateStreamSignedUrlConfig, creds: CloudflareCredential
    ) -> Dict:
        import time as _time
        body: Dict[str, Any] = {
            "exp": int(_time.time()) + (config.expiry_seconds or 3600),
        }
        result = await self._request(
            "POST",
            f"{await self._account_path(creds)}/stream/{config.video_id}/token",
            creds,
            json=body,
        )
        if result["status"] == "success":
            result["action"] = "create_stream_signed_url"
        return result

    async def _list_stream_signing_keys(
        self, config: CloudflareListStreamSigningKeysConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/stream/keys", creds
        )
        if result["status"] == "success":
            result["action"] = "list_stream_signing_keys"
        return result

    async def _create_stream_signing_key(
        self, config: CloudflareCreateStreamSigningKeyConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "POST", f"{await self._account_path(creds)}/stream/keys", creds, json={}
        )
        if result["status"] == "success":
            result["action"] = "create_stream_signing_key"
        return result

    async def _delete_stream_signing_key(
        self, config: CloudflareDeleteStreamSigningKeyConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "DELETE", f"{await self._account_path(creds)}/stream/keys/{config.key_id}", creds
        )
        if result["status"] == "success":
            result["action"] = "delete_stream_signing_key"
        return result

    async def _list_stream_captions(
        self, config: CloudflareListStreamCaptionsConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET",
            f"{await self._account_path(creds)}/stream/{config.video_id}/captions",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "list_stream_captions"
        return result

    async def _upload_stream_caption(
        self, config: CloudflareUploadStreamCaptionConfig, creds: CloudflareCredential
    ) -> Dict:
        await self._ensure_fresh_token(creds)
        headers = self._get_headers(creds)
        headers["Content-Type"] = "text/vtt"
        url = f"{BASE_URL}{await self._account_path(creds)}/stream/{config.video_id}/captions/{config.language}"
        async with httpx.AsyncClient(timeout=30.0) as c:
            resp = await c.put(url, headers=headers, content=config.caption_content.encode())
        if resp.status_code < 300:
            try:
                data = resp.json()
            except Exception:
                data = {"result": resp.text}
            return {"status": "success", "action": "upload_stream_caption", "result": data.get("result", data)}
        return {"status": "error", "error": resp.text, "status_code": resp.status_code}

    async def _delete_stream_caption(
        self, config: CloudflareDeleteStreamCaptionConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "DELETE",
            f"{await self._account_path(creds)}/stream/{config.video_id}/captions/{config.language}",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "delete_stream_caption"
        return result

    async def _list_stream_watermarks(
        self, config: CloudflareListStreamWatermarksConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/stream/watermarks", creds
        )
        if result["status"] == "success":
            result["action"] = "list_stream_watermarks"
        return result

    async def _create_stream_watermark(
        self, config: CloudflareCreateStreamWatermarkConfig, creds: CloudflareCredential
    ) -> Dict:
        body: Dict[str, Any] = {"url": config.watermark_url}
        if config.name:
            body["name"] = config.name
        if config.opacity is not None:
            body["opacity"] = config.opacity
        if config.padding is not None:
            body["padding"] = config.padding
        if config.scale is not None:
            body["scale"] = config.scale
        if config.position:
            body["position"] = config.position
        result = await self._request(
            "POST", f"{await self._account_path(creds)}/stream/watermarks", creds, json=body
        )
        if result["status"] == "success":
            result["action"] = "create_stream_watermark"
        return result

    async def _get_stream_watermark(
        self, config: CloudflareGetStreamWatermarkConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET",
            f"{await self._account_path(creds)}/stream/watermarks/{config.watermark_uid}",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "get_stream_watermark"
        return result

    async def _delete_stream_watermark(
        self, config: CloudflareDeleteStreamWatermarkConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "DELETE",
            f"{await self._account_path(creds)}/stream/watermarks/{config.watermark_uid}",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "delete_stream_watermark"
        return result

    async def _list_stream_audio_tracks(
        self, config: CloudflareListStreamAudioTracksConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET",
            f"{await self._account_path(creds)}/stream/{config.video_id}/audio",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "list_stream_audio_tracks"
        return result

    async def _add_stream_audio_track(
        self, config: CloudflareAddStreamAudioTrackConfig, creds: CloudflareCredential
    ) -> Dict:
        body: Dict[str, Any] = {"url": config.audio_url, "label": config.track_label}
        result = await self._request(
            "POST",
            f"{await self._account_path(creds)}/stream/{config.video_id}/audio/copy",
            creds,
            json=body,
        )
        if result["status"] == "success":
            result["action"] = "add_stream_audio_track"
        return result

    async def _edit_stream_audio_track(
        self, config: CloudflareEditStreamAudioTrackConfig, creds: CloudflareCredential
    ) -> Dict:
        body: Dict[str, Any] = {}
        if config.track_label:
            body["label"] = config.track_label
        if config.is_default is not None:
            body["default"] = config.is_default == "true"
        result = await self._request(
            "PATCH",
            f"{await self._account_path(creds)}/stream/{config.video_id}/audio/{config.audio_id}",
            creds,
            json=body,
        )
        if result["status"] == "success":
            result["action"] = "edit_stream_audio_track"
        return result

    async def _delete_stream_audio_track(
        self, config: CloudflareDeleteStreamAudioTrackConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "DELETE",
            f"{await self._account_path(creds)}/stream/{config.video_id}/audio/{config.audio_id}",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "delete_stream_audio_track"
        return result

    async def _update_stream_video(
        self, config: CloudflareUpdateStreamVideoConfig, creds: CloudflareCredential
    ) -> Dict:
        body: Dict[str, Any] = {}
        if config.require_signed_urls is not None:
            body["requireSignedURLs"] = config.require_signed_urls == "true"
        if config.allowed_origins:
            body["allowedOrigins"] = [o.strip() for o in config.allowed_origins.split(",")]
        if config.scheduled_deletion:
            body["scheduledDeletion"] = config.scheduled_deletion
        result = await self._request(
            "PATCH",
            f"{await self._account_path(creds)}/stream/{config.video_id}",
            creds,
            json=body,
        )
        if result["status"] == "success":
            result["action"] = "update_stream_video"
        return result

    # ── Images ───────────────────────────────────────────────────────────────────

    async def _list_images(
        self, config: CloudflareListImagesConfig, creds: CloudflareCredential
    ) -> Dict:
        params = {"page": config.page, "per_page": config.per_page}
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/images/v1", creds, params=params
        )
        if result["status"] == "success":
            result["action"] = "list_images"
        return result

    async def _get_image(
        self, config: CloudflareGetImageConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/images/v1/{config.image_id}", creds
        )
        if result["status"] == "success":
            result["action"] = "get_image"
        return result

    async def _delete_image(
        self, config: CloudflareDeleteImageConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "DELETE", f"{await self._account_path(creds)}/images/v1/{config.image_id}", creds
        )
        if result["status"] == "success":
            result["action"] = "delete_image"
        return result

    async def _get_images_stats(
        self, config: CloudflareGetImagesStatsConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/images/v1/stats", creds
        )
        if result["status"] == "success":
            result["action"] = "get_image_usage_statistics"
        return result

    async def _create_image_direct_upload(
        self,
        config: CloudflareCreateImageDirectUploadConfig,
        creds: CloudflareCredential,
    ) -> Dict:
        # Cloudflare Images v2 direct_upload requires multipart/form-data (it
        # 415s on a JSON body: "Must be uploaded as a form"). Send the fields as
        # multipart form fields via httpx's (None, value) tuple form.
        files: Dict[str, Any] = {
            "requireSignedURLs": (
                None,
                "true" if config.require_signed_urls == "true" else "false",
            )
        }
        if config.metadata:
            files["metadata"] = (None, config.metadata)
        result = await self._request(
            "POST",
            f"{await self._account_path(creds)}/images/v2/direct_upload",
            creds,
            files=files,
        )
        if result["status"] == "success":
            result["action"] = "create_image_direct_upload_url"
        return result

    # ── Firewall / WAF ──────────────────────────────────────────────────────────

    async def _list_firewall_rules(
        self, config: CloudflareListFirewallRulesConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"/zones/{config.zone_id}/firewall/rules", creds
        )
        if result["status"] == "success":
            result["action"] = "list_firewall_rules"
        return result

    async def _create_firewall_rule(
        self, config: CloudflareCreateFirewallRuleConfig, creds: CloudflareCredential
    ) -> Dict:
        body: Dict[str, Any] = {
            "filter": {"expression": config.expression},
            "action": config.rule_action,
            "paused": config.paused == "true",
        }
        if config.description:
            body["description"] = config.description
        if config.priority is not None:
            body["priority"] = config.priority
        result = await self._request(
            "POST", f"/zones/{config.zone_id}/firewall/rules", creds, json=[body]
        )
        if result["status"] == "success":
            result["action"] = "create_firewall_rule"
        return result

    async def _delete_firewall_rule(
        self, config: CloudflareDeleteFirewallRuleConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "DELETE", f"/zones/{config.zone_id}/firewall/rules/{config.rule_id}", creds
        )
        if result["status"] == "success":
            result["action"] = "delete_firewall_rule"
        return result

    async def _list_waf_packages(
        self, config: CloudflareListWAFPackagesConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"/zones/{config.zone_id}/firewall/waf/packages", creds
        )
        if result["status"] == "success":
            result["action"] = "list_zone_waf_packages"
        return result

    # ── Access (Zero Trust) ──────────────────────────────────────────────────────

    async def _list_access_applications(
        self,
        config: CloudflareListAccessApplicationsConfig,
        creds: CloudflareCredential,
    ) -> Dict:
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/access/apps", creds
        )
        if result["status"] == "success":
            result["action"] = "list_access_applications"
        return result

    async def _get_access_application(
        self, config: CloudflareGetAccessApplicationConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/access/apps/{config.app_id}", creds
        )
        if result["status"] == "success":
            result["action"] = "get_access_application"
        return result

    async def _create_access_application(
        self,
        config: CloudflareCreateAccessApplicationConfig,
        creds: CloudflareCredential,
    ) -> Dict:
        body: Dict[str, Any] = {
            "name": config.name,
            "domain": config.domain,
            "session_duration": config.session_duration,
            "type": config.app_type,
        }
        result = await self._request(
            "POST", f"{await self._account_path(creds)}/access/apps", creds, json=body
        )
        if result["status"] == "success":
            result["action"] = "create_access_application"
        return result

    async def _delete_access_application(
        self,
        config: CloudflareDeleteAccessApplicationConfig,
        creds: CloudflareCredential,
    ) -> Dict:
        result = await self._request(
            "DELETE", f"{await self._account_path(creds)}/access/apps/{config.app_id}", creds
        )
        if result["status"] == "success":
            result["action"] = "delete_access_application"
        return result

    async def _list_access_policies(
        self, config: CloudflareListAccessPoliciesConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET",
            f"{await self._account_path(creds)}/access/apps/{config.app_id}/policies",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "list_access_application_policies"
        return result

    # ── Tunnels ──────────────────────────────────────────────────────────────────

    async def _list_tunnels(
        self, config: CloudflareListTunnelsConfig, creds: CloudflareCredential
    ) -> Dict:
        params = {"is_deleted": config.is_deleted}
        if config.name:
            params["name"] = config.name
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/cfd_tunnel", creds, params=params
        )
        if result["status"] == "success":
            result["action"] = "list_tunnels"
        return result

    async def _get_tunnel(
        self, config: CloudflareGetTunnelConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/cfd_tunnel/{config.tunnel_id}", creds
        )
        if result["status"] == "success":
            result["action"] = "get_tunnel"
        return result

    async def _create_tunnel(
        self, config: CloudflareCreateTunnelConfig, creds: CloudflareCredential
    ) -> Dict:
        body: Dict[str, Any] = {"name": config.name, "config_src": "cloudflare"}
        if config.tunnel_secret:
            body["tunnel_secret"] = config.tunnel_secret
        result = await self._request(
            "POST", f"{await self._account_path(creds)}/cfd_tunnel", creds, json=body
        )
        if result["status"] == "success":
            result["action"] = "create_tunnel"
        return result

    async def _delete_tunnel(
        self, config: CloudflareDeleteTunnelConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "DELETE",
            f"{await self._account_path(creds)}/cfd_tunnel/{config.tunnel_id}",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "delete_tunnel"
        return result

    async def _get_tunnel_token(
        self, config: CloudflareGetTunnelTokenConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET",
            f"{await self._account_path(creds)}/cfd_tunnel/{config.tunnel_id}/token",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "get_tunnel_token"
        return result

    # ── Email Routing ─────────────────────────────────────────────────────────────

    async def _get_email_routing(
        self, config: CloudflareGetEmailRoutingConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"/zones/{config.zone_id}/email/routing", creds
        )
        if result["status"] == "success":
            result["action"] = "get_email_routing_settings"
        return result

    async def _list_email_routing_rules(
        self, config: CloudflareListEmailRoutingRulesConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"/zones/{config.zone_id}/email/routing/rules", creds
        )
        if result["status"] == "success":
            result["action"] = "list_email_routing_rules"
        return result

    async def _create_email_routing_rule(
        self,
        config: CloudflareCreateEmailRoutingRuleConfig,
        creds: CloudflareCredential,
    ) -> Dict:
        import json as _json

        try:
            matchers = _json.loads(config.matchers)
            actions = _json.loads(config.actions)
        except Exception as e:
            return {"status": "error", "error": f"Invalid JSON: {e}"}
        body: Dict[str, Any] = {
            "name": config.name,
            "matchers": matchers,
            "actions": actions,
            "enabled": config.enabled == "true",
        }
        result = await self._request(
            "POST", f"/zones/{config.zone_id}/email/routing/rules", creds, json=body
        )
        if result["status"] == "success":
            result["action"] = "create_email_routing_rule"
        return result

    async def _delete_email_routing_rule(
        self,
        config: CloudflareDeleteEmailRoutingRuleConfig,
        creds: CloudflareCredential,
    ) -> Dict:
        result = await self._request(
            "DELETE",
            f"/zones/{config.zone_id}/email/routing/rules/{config.rule_id}",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "delete_email_routing_rule"
        return result

    async def _list_email_routing_addresses(
        self,
        config: CloudflareListEmailRoutingAddressesConfig,
        creds: CloudflareCredential,
    ) -> Dict:
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/email/routing/addresses", creds
        )
        if result["status"] == "success":
            result["action"] = "list_email_routing_destination_addresses"
        return result

    # ── Queues ────────────────────────────────────────────────────────────────────

    async def _list_queues(
        self, config: CloudflareListQueuesConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/queues", creds
        )
        if result["status"] == "success":
            result["action"] = "list_queues"
        return result

    async def _get_queue(
        self, config: CloudflareGetQueueConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/queues/{config.queue_id}", creds
        )
        if result["status"] == "success":
            result["action"] = "get_queue"
        return result

    async def _create_queue(
        self, config: CloudflareCreateQueueConfig, creds: CloudflareCredential
    ) -> Dict:
        body: Dict[str, Any] = {"queue_name": config.queue_name}
        if config.delivery_type:
            body["settings"] = {"delivery_type": config.delivery_type}
        result = await self._request(
            "POST",
            f"{await self._account_path(creds)}/queues",
            creds,
            json=body,
        )
        if result["status"] == "success":
            result["action"] = "create_queue"
        return result

    async def _delete_queue(
        self, config: CloudflareDeleteQueueConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "DELETE", f"{await self._account_path(creds)}/queues/{config.queue_id}", creds
        )
        if result["status"] == "success":
            result["action"] = "delete_queue"
        return result

    async def _send_queue_message(
        self, config: CloudflareSendQueueMessageConfig, creds: CloudflareCredential
    ) -> Dict:
        import json as _json
        body_value: Any = config.body
        if config.content_type == "json":
            try:
                body_value = _json.loads(config.body)
            except Exception:
                pass  # pass raw string if not valid JSON
        payload: Dict[str, Any] = {"body": body_value, "content_type": config.content_type or "text"}
        if config.delay_seconds is not None:
            payload["delay_seconds"] = config.delay_seconds
        result = await self._request(
            "POST",
            f"{await self._account_path(creds)}/queues/{config.queue_id}/messages",
            creds,
            json=payload,
        )
        if result["status"] == "success":
            result["action"] = "send_queue_message"
        return result

    async def _pull_queue_messages(
        self, config: CloudflarePullQueueMessagesConfig, creds: CloudflareCredential
    ) -> Dict:
        body: Dict[str, Any] = {"batch_size": config.batch_size}
        if config.visibility_timeout_ms is not None:
            body["visibility_timeout_ms"] = config.visibility_timeout_ms
        result = await self._request(
            "POST",
            f"{await self._account_path(creds)}/queues/{config.queue_id}/messages/pull",
            creds,
            json=body,
        )
        if result["status"] == "success":
            result["action"] = "pull_queue_messages"
        return result

    # ── Workers AI ────────────────────────────────────────────────────────────────

    async def _run_ai_model(
        self, config: CloudflareRunAIModelConfig, creds: CloudflareCredential
    ) -> Dict:
        import json as _json

        try:
            input_data = _json.loads(config.input_data)
        except Exception as e:
            return {"status": "error", "error": f"Invalid JSON for input_data: {e}"}
        result = await self._request(
            "POST",
            f"{await self._account_path(creds)}/ai/run/{config.model_name}",
            creds,
            json=input_data,
        )
        if result["status"] == "success":
            result["action"] = "run_workers_ai_inference"
        return result

    async def _list_ai_models(
        self, config: CloudflareListAIModelsConfig, creds: CloudflareCredential
    ) -> Dict:
        params = {}
        if config.search:
            params["search"] = config.search
        if config.task:
            params["task"] = config.task
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/ai/models/search", creds, params=params
        )
        if result["status"] == "success":
            result["action"] = "list_workers_ai_models"
        return result

    # ── Vectorize ─────────────────────────────────────────────────────────────────

    async def _list_vectorize_indexes(
        self, config: CloudflareListVectorizeIndexesConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/vectorize/v2/indexes", creds
        )
        if result["status"] == "success":
            result["action"] = "list_vectorize_indexes"
        return result

    async def _get_vectorize_index(
        self, config: CloudflareGetVectorizeIndexConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET",
            f"{await self._account_path(creds)}/vectorize/v2/indexes/{config.index_name}",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "get_vectorize_index"
        return result

    async def _create_vectorize_index(
        self, config: CloudflareCreateVectorizeIndexConfig, creds: CloudflareCredential
    ) -> Dict:
        body = {
            "name": config.name,
            "config": {"dimensions": config.dimensions, "metric": config.metric},
        }
        result = await self._request(
            "POST",
            f"{await self._account_path(creds)}/vectorize/v2/indexes",
            creds,
            json=body,
        )
        if result["status"] == "success":
            result["action"] = "create_vectorize_index"
        return result

    async def _delete_vectorize_index(
        self, config: CloudflareDeleteVectorizeIndexConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "DELETE",
            f"{await self._account_path(creds)}/vectorize/v2/indexes/{config.index_name}",
            creds,
        )
        if result["status"] == "success":
            result["action"] = "delete_vectorize_index"
        return result

    async def _upsert_vectors(
        self, config: CloudflareUpsertVectorsConfig, creds: CloudflareCredential
    ) -> Dict:
        import json as _json

        try:
            vectors = _json.loads(config.vectors)
        except Exception as e:
            return {"status": "error", "error": f"Invalid JSON for vectors: {e}"}
        # Vectorize upsert uses NDJSON format
        ndjson_lines = "\n".join(_json.dumps(v) for v in vectors)
        headers = self._get_headers(creds)
        headers["Content-Type"] = "application/x-ndjson"
        url = f"{BASE_URL}{await self._account_path(creds)}/vectorize/v2/indexes/{config.index_name}/upsert"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url, headers=headers, content=ndjson_lines.encode()
            )
        try:
            result_data = response.json()
        except Exception:
            result_data = {
                "success": response.status_code < 300,
                "result": response.text,
            }
        if not result_data.get("success", response.status_code < 300):
            errors = result_data.get("errors", [])
            error_msg = (
                "; ".join(e.get("message", str(e)) for e in errors)
                if errors
                else response.text
            )
            return {
                "status": "error",
                "error": error_msg,
                "status_code": response.status_code,
            }
        return {
            "status": "success",
            "action": "upsert_vectors_to_index",
            "result": result_data.get("result"),
        }

    async def _query_vectors(
        self, config: CloudflareQueryVectorsConfig, creds: CloudflareCredential
    ) -> Dict:
        import json as _json

        try:
            query_vector = _json.loads(config.query_vector)
        except Exception as e:
            return {"status": "error", "error": f"Invalid JSON for query_vector: {e}"}
        body: Dict[str, Any] = {
            "vector": query_vector,
            "topK": config.top_k,
            "returnValues": config.return_values == "true",
            "returnMetadata": config.return_metadata == "true"
            if config.return_metadata
            else True,
        }
        result = await self._request(
            "POST",
            f"{await self._account_path(creds)}/vectorize/v2/indexes/{config.index_name}/query",
            creds,
            json=body,
        )
        if result["status"] == "success":
            result["action"] = "query_vectorize_index"
        return result

    async def _delete_vectors(
        self, config: CloudflareDeleteVectorsConfig, creds: CloudflareCredential
    ) -> Dict:
        ids = [v.strip() for v in config.vector_ids.split(",")]
        result = await self._request(
            "POST",
            f"{await self._account_path(creds)}/vectorize/v2/indexes/{config.index_name}/delete_by_ids",
            creds,
            json={"ids": ids},
        )
        if result["status"] == "success":
            result["action"] = "delete_vectors_from_index"
        return result

    # ── Load Balancing ────────────────────────────────────────────────────────────

    async def _list_load_balancers(
        self, config: CloudflareListLoadBalancersConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"/zones/{config.zone_id}/load_balancers", creds
        )
        if result["status"] == "success":
            result["action"] = "list_load_balancers"
        return result

    async def _get_load_balancer(
        self, config: CloudflareGetLoadBalancerConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"/zones/{config.zone_id}/load_balancers/{config.lb_id}", creds
        )
        if result["status"] == "success":
            result["action"] = "get_load_balancer"
        return result

    async def _create_load_balancer(
        self, config: CloudflareCreateLoadBalancerConfig, creds: CloudflareCredential
    ) -> Dict:
        import json as _json

        try:
            default_pools = _json.loads(config.default_pools)
        except Exception as e:
            return {"status": "error", "error": f"Invalid JSON for default_pools: {e}"}
        body: Dict[str, Any] = {
            "name": config.name,
            "default_pools": default_pools,
            "fallback_pool": config.fallback_pool,
            "proxied": config.proxied == "true",
            "ttl": config.ttl,
        }
        result = await self._request(
            "POST", f"/zones/{config.zone_id}/load_balancers", creds, json=body
        )
        if result["status"] == "success":
            result["action"] = "create_load_balancer"
        return result

    async def _delete_load_balancer(
        self, config: CloudflareDeleteLoadBalancerConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "DELETE", f"/zones/{config.zone_id}/load_balancers/{config.lb_id}", creds
        )
        if result["status"] == "success":
            result["action"] = "delete_load_balancer"
        return result

    async def _list_lb_pools(
        self, config: CloudflareListLBPoolsConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"{await self._account_path(creds)}/load_balancers/pools", creds
        )
        if result["status"] == "success":
            result["action"] = "list_load_balancer_pools"
        return result

    async def _create_lb_pool(
        self, config: CloudflareCreateLBPoolConfig, creds: CloudflareCredential
    ) -> Dict:
        import json as _json

        try:
            origins = _json.loads(config.origins)
        except Exception as e:
            return {"status": "error", "error": f"Invalid JSON for origins: {e}"}
        body: Dict[str, Any] = {
            "name": config.name,
            "origins": origins,
            "enabled": config.enabled == "true",
        }
        if config.description:
            body["description"] = config.description
        result = await self._request(
            "POST",
            f"{await self._account_path(creds)}/load_balancers/pools",
            creds,
            json=body,
        )
        if result["status"] == "success":
            result["action"] = "create_load_balancer_pool"
        return result

    # ── SSL / TLS ─────────────────────────────────────────────────────────────────

    async def _get_ssl_settings(
        self, config: CloudflareGetSSLSettingsConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"/zones/{config.zone_id}/settings/ssl", creds
        )
        if result["status"] == "success":
            result["action"] = "get_zone_ssl_settings"
        return result

    async def _list_ssl_certificates(
        self, config: CloudflareListSSLCertificatesConfig, creds: CloudflareCredential
    ) -> Dict:
        result = await self._request(
            "GET", f"/zones/{config.zone_id}/ssl/certificate_packs", creds
        )
        if result["status"] == "success":
            result["action"] = "list_zone_ssl_certificates"
        return result

    # ── Analytics ─────────────────────────────────────────────────────────────────

    async def _get_zone_analytics(
        self, config: CloudflareGetZoneAnalyticsConfig, creds: CloudflareCredential
    ) -> Dict:
        params: Dict[str, Any] = {"continuous": config.continuous == "true"}
        if config.since:
            params["since"] = config.since
        if config.until:
            params["until"] = config.until
        result = await self._request(
            "GET", f"/zones/{config.zone_id}/analytics/dashboard", creds, params=params
        )
        if result["status"] == "success":
            result["action"] = "get_zone_analytics"
        return result



    # ── Worker Secrets ────────────────────────────────────────────────────────────

    async def _list_worker_secrets(self, config: CloudflareListWorkerSecretsConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/workers/scripts/{config.script_name}/secrets", creds)
        if result["status"] == "success":
            result["action"] = "list_worker_secrets"
        return result

    async def _put_worker_secret(self, config: CloudflarePutWorkerSecretConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"name": config.secret_name, "text": config.secret_value, "type": config.secret_type or "secret_text"}
        result = await self._cf_request("PUT", f"{await self._account_path(creds)}/workers/scripts/{config.script_name}/secrets", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "put_worker_secret"
        return result

    async def _delete_worker_secret(self, config: CloudflareDeleteWorkerSecretConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{await self._account_path(creds)}/workers/scripts/{config.script_name}/secrets/{config.secret_name}", creds)
        if result["status"] == "success":
            result["action"] = "delete_worker_secret"
        return result

    async def _bulk_upsert_worker_secrets(self, config: CloudflareBulkUpsertWorkerSecretsConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        secrets = _json.loads(config.secrets_json)
        result = await self._cf_request("PUT", f"{await self._account_path(creds)}/workers/scripts/{config.script_name}/secrets", creds, json=secrets)
        if result["status"] == "success":
            result["action"] = "bulk_upsert_worker_secrets"
        return result

    # ── Worker Cron Triggers ──────────────────────────────────────────────────────

    async def _get_worker_cron_triggers(self, config: CloudflareGetWorkerCronTriggersConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/workers/scripts/{config.script_name}/schedules", creds)
        if result["status"] == "success":
            result["action"] = "get_worker_cron_triggers"
        return result

    async def _update_worker_cron_triggers(self, config: CloudflareUpdateWorkerCronTriggersConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        crons = _json.loads(config.crons)
        payload = [{"cron": c} for c in crons]
        result = await self._cf_request("PUT", f"{await self._account_path(creds)}/workers/scripts/{config.script_name}/schedules", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_worker_cron_triggers"
        return result

    # ── Durable Objects ───────────────────────────────────────────────────────────

    async def _list_durable_object_namespaces(self, config: CloudflareListDurableObjectNamespacesConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/workers/durable_objects/namespaces", creds)
        if result["status"] == "success":
            result["action"] = "list_durable_object_namespaces"
        return result

    async def _list_durable_objects(self, config: CloudflareListDurableObjectsConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {"limit": config.limit}
        if config.cursor:
            params["cursor"] = config.cursor
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/workers/durable_objects/namespaces/{config.namespace_id}/objects", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_durable_objects"
        return result

    # ── Worker Routes ─────────────────────────────────────────────────────────────

    async def _update_worker_route(self, config: CloudflareUpdateWorkerRouteConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {}
        if config.pattern is not None:
            payload["pattern"] = config.pattern
        if config.script_name is not None:
            payload["script"] = config.script_name
        result = await self._cf_request("PUT", f"{BASE_URL}/zones/{config.zone_id}/workers/routes/{config.route_id}", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_worker_route"
        return result

    # ── Pipelines ─────────────────────────────────────────────────────────────────

    async def _list_pipelines(self, config: CloudflareListPipelinesConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {}
        if config.page:
            params["page"] = config.page
        if config.per_page:
            params["per_page"] = config.per_page
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/pipelines", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_pipelines"
        return result

    async def _get_pipeline(self, config: CloudflareGetPipelineConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/pipelines/{config.pipeline_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_pipeline"
        return result

    async def _create_pipeline(self, config: CloudflareCreatePipelineConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        if config.config_json:
            payload = _json.loads(config.config_json)
        else:
            payload = {"name": config.pipeline_name, "source": [{"type": config.source_type or "http"}], "destination": {"type": config.dest_type or "r2"}}
        result = await self._cf_request("POST", f"{await self._account_path(creds)}/pipelines", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_pipeline"
        return result

    async def _update_pipeline(self, config: CloudflareUpdatePipelineConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        payload = _json.loads(config.config_json)
        result = await self._cf_request("PUT", f"{await self._account_path(creds)}/pipelines/{config.pipeline_id}", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_pipeline"
        return result

    async def _delete_pipeline(self, config: CloudflareDeletePipelineConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{await self._account_path(creds)}/pipelines/{config.pipeline_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_pipeline"
        return result

    # ── Secrets Store ─────────────────────────────────────────────────────────────

    async def _list_secrets_stores(self, config: CloudflareListSecretsStoresConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {}
        if config.page:
            params["page"] = config.page
        if config.per_page:
            params["per_page"] = config.per_page
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/secrets_store/stores", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_secrets_stores"
        return result

    async def _create_secrets_store(self, config: CloudflareCreateSecretsStoreConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("POST", f"{await self._account_path(creds)}/secrets_store/stores", creds, json={"name": config.store_name})
        if result["status"] == "success":
            result["action"] = "create_secrets_store"
        return result

    async def _delete_secrets_store(self, config: CloudflareDeleteSecretsStoreConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{await self._account_path(creds)}/secrets_store/stores/{config.store_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_secrets_store"
        return result

    async def _list_store_secrets(self, config: CloudflareListStoreSecretsConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {}
        if config.page:
            params["page"] = config.page
        if config.per_page:
            params["per_page"] = config.per_page
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/secrets_store/stores/{config.store_id}/secrets", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_store_secrets"
        return result

    async def _get_store_secret(self, config: CloudflareGetStoreSecretConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/secrets_store/stores/{config.store_id}/secrets/{config.secret_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_store_secret"
        return result

    async def _create_store_secret(self, config: CloudflareCreateStoreSecretConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"name": config.secret_name, "value": config.secret_value}
        if config.secret_scopes:
            payload["scopes"] = [s.strip() for s in config.secret_scopes.split(",")]
        result = await self._cf_request("POST", f"{await self._account_path(creds)}/secrets_store/stores/{config.store_id}/secrets", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_store_secret"
        return result

    async def _update_store_secret(self, config: CloudflareUpdateStoreSecretConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {}
        if config.secret_value is not None:
            payload["value"] = config.secret_value
        if config.secret_scopes is not None:
            payload["scopes"] = [s.strip() for s in config.secret_scopes.split(",")]
        result = await self._cf_request("PATCH", f"{await self._account_path(creds)}/secrets_store/stores/{config.store_id}/secrets/{config.secret_id}", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_store_secret"
        return result

    async def _delete_store_secret(self, config: CloudflareDeleteStoreSecretConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{await self._account_path(creds)}/secrets_store/stores/{config.store_id}/secrets/{config.secret_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_store_secret"
        return result

    # ── Rulesets ──────────────────────────────────────────────────────────────────

    async def _list_zone_rulesets(self, config: CloudflareListZoneRulesetsConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/rulesets", creds)
        if result["status"] == "success":
            result["action"] = "list_zone_rulesets"
        return result

    async def _get_zone_ruleset(self, config: CloudflareGetZoneRulesetConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/rulesets/{config.ruleset_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_zone_ruleset"
        return result

    async def _create_zone_ruleset(self, config: CloudflareCreateZoneRulesetConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        payload: Dict[str, Any] = {"name": config.ruleset_name, "kind": config.kind, "phase": config.phase}
        if config.description:
            payload["description"] = config.description
        if config.rules_json:
            payload["rules"] = _json.loads(config.rules_json)
        result = await self._cf_request("POST", f"{BASE_URL}/zones/{config.zone_id}/rulesets", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_zone_ruleset"
        return result

    async def _update_zone_ruleset(self, config: CloudflareUpdateZoneRulesetConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        payload: Dict[str, Any] = {}
        if config.ruleset_name:
            payload["name"] = config.ruleset_name
        if config.description is not None:
            payload["description"] = config.description
        if config.rules_json:
            payload["rules"] = _json.loads(config.rules_json)
        result = await self._cf_request("PUT", f"{BASE_URL}/zones/{config.zone_id}/rulesets/{config.ruleset_id}", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_zone_ruleset"
        return result

    async def _delete_zone_ruleset(self, config: CloudflareDeleteZoneRulesetConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{BASE_URL}/zones/{config.zone_id}/rulesets/{config.ruleset_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_zone_ruleset"
        return result

    async def _get_zone_ruleset_phase(self, config: CloudflareGetZoneRulesetPhaseConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/rulesets/phases/{config.phase}/entrypoint", creds)
        if result["status"] == "success":
            result["action"] = "get_zone_ruleset_phase"
        return result

    async def _update_zone_ruleset_phase(self, config: CloudflareUpdateZoneRulesetPhaseConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        payload = {"rules": _json.loads(config.rules_json)}
        result = await self._cf_request("PUT", f"{BASE_URL}/zones/{config.zone_id}/rulesets/phases/{config.phase}/entrypoint", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_zone_ruleset_phase"
        return result

    async def _create_zone_ruleset_rule(self, config: CloudflareCreateZoneRulesetRuleConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"action": config.action, "expression": config.expression, "enabled": config.enabled != "false"}
        if config.description:
            payload["description"] = config.description
        result = await self._cf_request("POST", f"{BASE_URL}/zones/{config.zone_id}/rulesets/{config.ruleset_id}/rules", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_zone_ruleset_rule"
        return result

    async def _delete_zone_ruleset_rule(self, config: CloudflareDeleteZoneRulesetRuleConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{BASE_URL}/zones/{config.zone_id}/rulesets/{config.ruleset_id}/rules/{config.rule_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_zone_ruleset_rule"
        return result

    async def _list_account_rulesets(self, config: CloudflareListAccountRulesetsConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/rulesets", creds)
        if result["status"] == "success":
            result["action"] = "list_account_rulesets"
        return result

    async def _get_account_ruleset(self, config: CloudflareGetAccountRulesetConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/rulesets/{config.ruleset_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_account_ruleset"
        return result

    # ── Page Rules ────────────────────────────────────────────────────────────────

    async def _list_page_rules(self, config: CloudflareListPageRulesConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {}
        if config.status:
            params["status"] = config.status
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/pagerules", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_page_rules"
        return result

    async def _get_page_rule(self, config: CloudflareGetPageRuleConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/pagerules/{config.pagerule_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_page_rule"
        return result

    async def _create_page_rule(self, config: CloudflareCreatePageRuleConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        payload: Dict[str, Any] = {"targets": [{"target": "url", "constraint": {"operator": "matches", "value": config.url_pattern}}], "actions": _json.loads(config.actions_json), "status": config.status or "active"}
        if config.priority is not None:
            payload["priority"] = config.priority
        result = await self._cf_request("POST", f"{BASE_URL}/zones/{config.zone_id}/pagerules", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_page_rule"
        return result

    async def _update_page_rule(self, config: CloudflareUpdatePageRuleConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        payload: Dict[str, Any] = {}
        if config.url_pattern:
            payload["targets"] = [{"target": "url", "constraint": {"operator": "matches", "value": config.url_pattern}}]
        if config.actions_json:
            payload["actions"] = _json.loads(config.actions_json)
        if config.status:
            payload["status"] = config.status
        if config.priority is not None:
            payload["priority"] = config.priority
        result = await self._cf_request("PATCH", f"{BASE_URL}/zones/{config.zone_id}/pagerules/{config.pagerule_id}", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_page_rule"
        return result

    async def _delete_page_rule(self, config: CloudflareDeletePageRuleConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{BASE_URL}/zones/{config.zone_id}/pagerules/{config.pagerule_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_page_rule"
        return result

    # ── Rate Limiting ─────────────────────────────────────────────────────────────

    async def _list_rate_limits(self, config: CloudflareListRateLimitsConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {"page": config.page or 1, "per_page": config.per_page or 20}
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/rate_limits", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_rate_limits"
        return result

    async def _get_rate_limit(self, config: CloudflareGetRateLimitConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/rate_limits/{config.rate_limit_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_rate_limit"
        return result

    async def _create_rate_limit(self, config: CloudflareCreateRateLimitConfig, creds: CloudflareCredential) -> Dict:
        action_payload: Dict[str, Any] = {"mode": config.action_mode}
        if config.ban_duration is not None:
            action_payload["response"] = {"content_type": "text/plain", "body": "This request has been rate-limited."}
            action_payload["timeout"] = config.ban_duration
        payload: Dict[str, Any] = {"match": {"request": {"url_pattern": config.url_pattern}}, "threshold": config.threshold, "period": config.period, "action": action_payload}
        if config.request_methods:
            payload["match"]["request"]["methods"] = [m.strip() for m in config.request_methods.split(",")]
        result = await self._cf_request("POST", f"{BASE_URL}/zones/{config.zone_id}/rate_limits", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_rate_limit"
        return result

    async def _update_rate_limit(self, config: CloudflareUpdateRateLimitConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {}
        if config.url_pattern:
            payload["match"] = {"request": {"url_pattern": config.url_pattern}}
        if config.threshold is not None:
            payload["threshold"] = config.threshold
        if config.period is not None:
            payload["period"] = config.period
        if config.action_mode:
            action_payload: Dict[str, Any] = {"mode": config.action_mode}
            if config.ban_duration is not None:
                action_payload["timeout"] = config.ban_duration
            payload["action"] = action_payload
        result = await self._cf_request("PUT", f"{BASE_URL}/zones/{config.zone_id}/rate_limits/{config.rate_limit_id}", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_rate_limit"
        return result

    async def _delete_rate_limit(self, config: CloudflareDeleteRateLimitConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{BASE_URL}/zones/{config.zone_id}/rate_limits/{config.rate_limit_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_rate_limit"
        return result

    # ── Custom Hostnames ──────────────────────────────────────────────────────────

    async def _list_custom_hostnames(self, config: CloudflareListCustomHostnamesConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {"page": config.page or 1, "per_page": config.per_page or 20}
        if config.hostname_filter:
            params["hostname"] = config.hostname_filter
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/custom_hostnames", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_custom_hostnames"
        return result

    async def _get_custom_hostname(self, config: CloudflareGetCustomHostnameConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/custom_hostnames/{config.custom_hostname_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_custom_hostname"
        return result

    async def _create_custom_hostname(self, config: CloudflareCreateCustomHostnameConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        payload: Dict[str, Any] = {"hostname": config.hostname, "ssl": {"method": config.ssl_method or "http", "type": config.ssl_type or "dv"}}
        if config.custom_metadata_json:
            payload["custom_metadata"] = _json.loads(config.custom_metadata_json)
        result = await self._cf_request("POST", f"{BASE_URL}/zones/{config.zone_id}/custom_hostnames", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_custom_hostname"
        return result

    async def _update_custom_hostname(self, config: CloudflareUpdateCustomHostnameConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        payload: Dict[str, Any] = {}
        if config.ssl_method:
            payload["ssl"] = {"method": config.ssl_method}
        if config.custom_metadata_json:
            payload["custom_metadata"] = _json.loads(config.custom_metadata_json)
        result = await self._cf_request("PATCH", f"{BASE_URL}/zones/{config.zone_id}/custom_hostnames/{config.custom_hostname_id}", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_custom_hostname"
        return result

    async def _delete_custom_hostname(self, config: CloudflareDeleteCustomHostnameConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{BASE_URL}/zones/{config.zone_id}/custom_hostnames/{config.custom_hostname_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_custom_hostname"
        return result

    # ── Waiting Rooms ─────────────────────────────────────────────────────────────

    async def _list_waiting_rooms(self, config: CloudflareListWaitingRoomsConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {"page": config.page or 1, "per_page": config.per_page or 25}
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/waiting_rooms", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_waiting_rooms"
        return result

    async def _get_waiting_room(self, config: CloudflareGetWaitingRoomConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/waiting_rooms/{config.waiting_room_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_waiting_room"
        return result

    async def _create_waiting_room(self, config: CloudflareCreateWaitingRoomConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"name": config.name, "host": config.host, "path": config.path or "/", "total_active_users": config.total_active_users, "new_users_per_minute": config.new_users_per_minute, "session_duration": config.session_duration or 5, "queue_all": config.queue_all == "true"}
        if config.custom_page_html:
            payload["custom_page_html"] = config.custom_page_html
        result = await self._cf_request("POST", f"{BASE_URL}/zones/{config.zone_id}/waiting_rooms", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_waiting_room"
        return result

    async def _update_waiting_room(self, config: CloudflareUpdateWaitingRoomConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {}
        if config.name:
            payload["name"] = config.name
        if config.host:
            payload["host"] = config.host
        if config.path is not None:
            payload["path"] = config.path
        if config.total_active_users is not None:
            payload["total_active_users"] = config.total_active_users
        if config.new_users_per_minute is not None:
            payload["new_users_per_minute"] = config.new_users_per_minute
        if config.session_duration is not None:
            payload["session_duration"] = config.session_duration
        if config.queue_all is not None:
            payload["queue_all"] = config.queue_all == "true"
        if config.custom_page_html is not None:
            payload["custom_page_html"] = config.custom_page_html
        result = await self._cf_request("PATCH", f"{BASE_URL}/zones/{config.zone_id}/waiting_rooms/{config.waiting_room_id}", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_waiting_room"
        return result

    async def _delete_waiting_room(self, config: CloudflareDeleteWaitingRoomConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{BASE_URL}/zones/{config.zone_id}/waiting_rooms/{config.waiting_room_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_waiting_room"
        return result

    async def _get_waiting_room_status(self, config: CloudflareGetWaitingRoomStatusConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/waiting_rooms/{config.waiting_room_id}/status", creds)
        if result["status"] == "success":
            result["action"] = "get_waiting_room_status"
        return result

    async def _list_waiting_room_events(self, config: CloudflareListWaitingRoomEventsConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/waiting_rooms/{config.waiting_room_id}/events", creds)
        if result["status"] == "success":
            result["action"] = "list_waiting_room_events"
        return result

    async def _create_waiting_room_event(self, config: CloudflareCreateWaitingRoomEventConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"name": config.event_name, "event_start_time": config.event_start_time, "event_end_time": config.event_end_time}
        if config.new_users_per_minute is not None:
            payload["new_users_per_minute"] = config.new_users_per_minute
        if config.total_active_users is not None:
            payload["total_active_users"] = config.total_active_users
        result = await self._cf_request("POST", f"{BASE_URL}/zones/{config.zone_id}/waiting_rooms/{config.waiting_room_id}/events", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_waiting_room_event"
        return result

    # ── Logpush ───────────────────────────────────────────────────────────────────

    async def _list_account_logpush_jobs(self, config: CloudflareListAccountLogpushJobsConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/logpush/jobs", creds)
        if result["status"] == "success":
            result["action"] = "list_account_logpush_jobs"
        return result

    async def _get_logpush_job(self, config: CloudflareGetLogpushJobConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/logpush/jobs/{config.job_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_logpush_job"
        return result

    async def _create_logpush_job(self, config: CloudflareCreateLogpushJobConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"name": config.job_name, "destination_conf": config.destination_conf, "dataset": config.dataset, "enabled": config.enabled != "false", "frequency": config.frequency or "high"}
        if config.logpull_options:
            payload["logpull_options"] = config.logpull_options
        result = await self._cf_request("POST", f"{await self._account_path(creds)}/logpush/jobs", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_logpush_job"
        return result

    async def _update_logpush_job(self, config: CloudflareUpdateLogpushJobConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {}
        if config.destination_conf:
            payload["destination_conf"] = config.destination_conf
        if config.enabled is not None:
            payload["enabled"] = config.enabled != "false"
        if config.frequency:
            payload["frequency"] = config.frequency
        if config.logpull_options:
            payload["logpull_options"] = config.logpull_options
        result = await self._cf_request("PUT", f"{await self._account_path(creds)}/logpush/jobs/{config.job_id}", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_logpush_job"
        return result

    async def _delete_logpush_job(self, config: CloudflareDeleteLogpushJobConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{await self._account_path(creds)}/logpush/jobs/{config.job_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_logpush_job"
        return result

    async def _list_zone_logpush_jobs(self, config: CloudflareListZoneLogpushJobsConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/logpush/jobs", creds)
        if result["status"] == "success":
            result["action"] = "list_zone_logpush_jobs"
        return result

    async def _create_zone_logpush_job(self, config: CloudflareCreateZoneLogpushJobConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"name": config.job_name, "destination_conf": config.destination_conf, "dataset": config.dataset, "enabled": config.enabled != "false"}
        if config.logpull_options:
            payload["logpull_options"] = config.logpull_options
        result = await self._cf_request("POST", f"{BASE_URL}/zones/{config.zone_id}/logpush/jobs", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_zone_logpush_job"
        return result

    async def _delete_zone_logpush_job(self, config: CloudflareDeleteZoneLogpushJobConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{BASE_URL}/zones/{config.zone_id}/logpush/jobs/{config.job_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_zone_logpush_job"
        return result

    # ── Audit Logs ────────────────────────────────────────────────────────────────

    async def _list_audit_logs(self, config: CloudflareListAuditLogsConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {"direction": config.direction or "desc", "per_page": config.per_page or 25}
        if config.since:
            params["since"] = config.since
        if config.before:
            params["before"] = config.before
        if config.action_type:
            params["action.type"] = config.action_type
        if config.actor_email:
            params["actor.email"] = config.actor_email
        if config.zone_name:
            params["zone.name"] = config.zone_name
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/audit_logs", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_audit_logs"
        return result

    # ── Notifications / Alerting ──────────────────────────────────────────────────

    async def _list_available_alerts(self, config: CloudflareListAvailableAlertsConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/alerting/v3/available_alerts", creds)
        if result["status"] == "success":
            result["action"] = "list_available_alerts"
        return result

    async def _list_alert_policies(self, config: CloudflareListAlertPoliciesConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/alerting/v3/policies", creds)
        if result["status"] == "success":
            result["action"] = "list_alert_policies"
        return result

    async def _get_alert_policy(self, config: CloudflareGetAlertPolicyConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/alerting/v3/policies/{config.policy_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_alert_policy"
        return result

    async def _create_alert_policy(self, config: CloudflareCreateAlertPolicyConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        payload: Dict[str, Any] = {"name": config.policy_name, "alert_type": config.alert_type, "enabled": config.enabled != "false", "mechanisms": {}}
        if config.webhook_ids:
            payload["mechanisms"]["webhooks"] = [{"id": wid.strip()} for wid in config.webhook_ids.split(",")]
        if config.email_addresses:
            payload["mechanisms"]["email"] = [{"id": e.strip()} for e in config.email_addresses.split(",")]
        if config.filters_json:
            payload["filters"] = _json.loads(config.filters_json)
        result = await self._cf_request("POST", f"{await self._account_path(creds)}/alerting/v3/policies", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_alert_policy"
        return result

    async def _update_alert_policy(self, config: CloudflareUpdateAlertPolicyConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        payload: Dict[str, Any] = {}
        if config.policy_name:
            payload["name"] = config.policy_name
        if config.alert_type:
            payload["alert_type"] = config.alert_type
        if config.enabled is not None:
            payload["enabled"] = config.enabled != "false"
        if config.webhook_ids:
            payload.setdefault("mechanisms", {})["webhooks"] = [{"id": wid.strip()} for wid in config.webhook_ids.split(",")]
        if config.email_addresses:
            payload.setdefault("mechanisms", {})["email"] = [{"id": e.strip()} for e in config.email_addresses.split(",")]
        if config.filters_json:
            payload["filters"] = _json.loads(config.filters_json)
        result = await self._cf_request("PUT", f"{await self._account_path(creds)}/alerting/v3/policies/{config.policy_id}", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_alert_policy"
        return result

    async def _delete_alert_policy(self, config: CloudflareDeleteAlertPolicyConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{await self._account_path(creds)}/alerting/v3/policies/{config.policy_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_alert_policy"
        return result

    async def _list_notification_webhooks(self, config: CloudflareListNotificationWebhooksConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/alerting/v3/destinations/webhooks", creds)
        if result["status"] == "success":
            result["action"] = "list_notification_webhooks"
        return result

    async def _create_notification_webhook(self, config: CloudflareCreateNotificationWebhookConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"name": config.webhook_name, "url": config.webhook_url}
        if config.webhook_secret:
            payload["secret"] = config.webhook_secret
        result = await self._cf_request("POST", f"{await self._account_path(creds)}/alerting/v3/destinations/webhooks", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_notification_webhook"
        return result

    async def _update_notification_webhook(self, config: CloudflareUpdateNotificationWebhookConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {}
        if config.webhook_name:
            payload["name"] = config.webhook_name
        if config.webhook_url:
            payload["url"] = config.webhook_url
        if config.webhook_secret:
            payload["secret"] = config.webhook_secret
        result = await self._cf_request("PUT", f"{await self._account_path(creds)}/alerting/v3/destinations/webhooks/{config.webhook_id}", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_notification_webhook"
        return result

    async def _delete_notification_webhook(self, config: CloudflareDeleteNotificationWebhookConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{await self._account_path(creds)}/alerting/v3/destinations/webhooks/{config.webhook_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_notification_webhook"
        return result

    async def _get_notification_history(self, config: CloudflareGetNotificationHistoryConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {"per_page": config.per_page or 25}
        if config.since:
            params["since"] = config.since
        if config.before:
            params["before"] = config.before
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/alerting/v3/history", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_notification_history"
        return result

    # ── Health Checks ─────────────────────────────────────────────────────────────

    async def _list_health_checks(self, config: CloudflareListHealthChecksConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/healthchecks", creds)
        if result["status"] == "success":
            result["action"] = "list_health_checks"
        return result

    async def _get_health_check(self, config: CloudflareGetHealthCheckConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/healthchecks/{config.healthcheck_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_health_check"
        return result

    async def _create_health_check(self, config: CloudflareCreateHealthCheckConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"name": config.check_name, "address": config.address, "type": config.check_type, "path": config.path or "/", "interval": config.interval or 60, "retries": config.retries or 2, "timeout": config.timeout or 5}
        if config.port is not None:
            payload["port"] = config.port
        if config.method:
            payload["http_config"] = {"method": config.method, "expected_codes": config.expected_codes or "2xx"}
        if config.check_regions:
            payload["check_regions"] = [r.strip() for r in config.check_regions.split(",")]
        if config.description:
            payload["description"] = config.description
        result = await self._cf_request("POST", f"{BASE_URL}/zones/{config.zone_id}/healthchecks", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_health_check"
        return result

    async def _update_health_check(self, config: CloudflareUpdateHealthCheckConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {}
        if config.check_name:
            payload["name"] = config.check_name
        if config.address:
            payload["address"] = config.address
        if config.check_type:
            payload["type"] = config.check_type
        if config.path is not None:
            payload["path"] = config.path
        if config.port is not None:
            payload["port"] = config.port
        if config.method:
            payload["http_config"] = {"method": config.method}
            if config.expected_codes:
                payload["http_config"]["expected_codes"] = config.expected_codes
        if config.interval is not None:
            payload["interval"] = config.interval
        if config.retries is not None:
            payload["retries"] = config.retries
        if config.timeout is not None:
            payload["timeout"] = config.timeout
        result = await self._cf_request("PATCH", f"{BASE_URL}/zones/{config.zone_id}/healthchecks/{config.healthcheck_id}", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_health_check"
        return result

    async def _delete_health_check(self, config: CloudflareDeleteHealthCheckConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{BASE_URL}/zones/{config.zone_id}/healthchecks/{config.healthcheck_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_health_check"
        return result

    # ── Spectrum ──────────────────────────────────────────────────────────────────

    async def _list_spectrum_apps(self, config: CloudflareListSpectrumAppsConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {"page": config.page or 1, "per_page": config.per_page or 20}
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/spectrum/apps", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_spectrum_apps"
        return result

    async def _get_spectrum_app(self, config: CloudflareGetSpectrumAppConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/spectrum/apps/{config.app_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_spectrum_app"
        return result

    async def _create_spectrum_app(self, config: CloudflareCreateSpectrumAppConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"protocol": config.protocol, "dns": {"type": "CNAME", "name": config.dns_name}, "tls": config.tls or "off"}
        if config.origin_direct:
            payload["origin_direct"] = [config.origin_direct]
        elif config.origin_dns_name:
            payload["origin_dns"] = {"name": config.origin_dns_name}
            if config.origin_port:
                payload["origin_port"] = config.origin_port
        if config.ip_firewall is not None:
            payload["ip_firewall"] = config.ip_firewall == "true"
        result = await self._cf_request("POST", f"{BASE_URL}/zones/{config.zone_id}/spectrum/apps", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_spectrum_app"
        return result

    async def _update_spectrum_app(self, config: CloudflareUpdateSpectrumAppConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {}
        if config.protocol:
            payload["protocol"] = config.protocol
        if config.dns_name:
            payload["dns"] = {"type": "CNAME", "name": config.dns_name}
        if config.origin_direct:
            payload["origin_direct"] = [config.origin_direct]
        if config.origin_port is not None:
            payload["origin_port"] = config.origin_port
        if config.ip_firewall is not None:
            payload["ip_firewall"] = config.ip_firewall == "true"
        if config.tls:
            payload["tls"] = config.tls
        result = await self._cf_request("PUT", f"{BASE_URL}/zones/{config.zone_id}/spectrum/apps/{config.app_id}", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_spectrum_app"
        return result

    async def _delete_spectrum_app(self, config: CloudflareDeleteSpectrumAppConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{BASE_URL}/zones/{config.zone_id}/spectrum/apps/{config.app_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_spectrum_app"
        return result

    # ── Snippets ──────────────────────────────────────────────────────────────────

    async def _list_snippets(self, config: CloudflareListSnippetsConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/snippets", creds)
        if result["status"] == "success":
            result["action"] = "list_snippets"
        return result

    async def _get_snippet(self, config: CloudflareGetSnippetConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/snippets/{config.snippet_name}", creds)
        if result["status"] == "success":
            result["action"] = "get_snippet"
        return result

    async def _put_snippet(self, config: CloudflarePutSnippetConfig, creds: CloudflareCredential) -> Dict:
        import httpx as _httpx
        await self._ensure_fresh_token(creds)
        headers = {k: v for k, v in self._get_headers(creds).items() if k != "Content-Type"}
        files = {"files": ("index.js", config.snippet_code.encode(), "application/javascript"), "metadata": (None, '{"main_module": "index.js"}', "application/json")}
        async with _httpx.AsyncClient() as client:
            resp = await client.put(f"{BASE_URL}/zones/{config.zone_id}/snippets/{config.snippet_name}", headers=headers, files=files, timeout=30)
        data = resp.json()
        if not data.get("success"):
            return {"status": "error", "error": str(data.get("errors", data))}
        return {"status": "success", "action": "put_snippet", "data": data.get("result")}

    async def _delete_snippet(self, config: CloudflareDeleteSnippetConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{BASE_URL}/zones/{config.zone_id}/snippets/{config.snippet_name}", creds)
        if result["status"] == "success":
            result["action"] = "delete_snippet"
        return result

    async def _list_snippet_rules(self, config: CloudflareListSnippetRulesConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/snippets/snippet_rules", creds)
        if result["status"] == "success":
            result["action"] = "list_snippet_rules"
        return result

    # ── Zaraz ─────────────────────────────────────────────────────────────────────

    async def _get_zaraz_config(self, config: CloudflareGetZarazConfigConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/settings/zaraz/config", creds)
        if result["status"] == "success":
            result["action"] = "get_zaraz_config"
        return result

    async def _update_zaraz_config(self, config: CloudflareUpdateZarazConfigConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        payload = _json.loads(config.config_json)
        result = await self._cf_request("PUT", f"{BASE_URL}/zones/{config.zone_id}/settings/zaraz/config", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_zaraz_config"
        return result

    async def _publish_zaraz_config(self, config: CloudflarePublishZarazConfigConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {}
        if config.description:
            payload["description"] = config.description
        result = await self._cf_request("POST", f"{BASE_URL}/zones/{config.zone_id}/settings/zaraz/publish", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "publish_zaraz_config"
        return result

    # ── Bot Management ────────────────────────────────────────────────────────────

    async def _get_bot_management(self, config: CloudflareGetBotManagementConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/bot_management", creds)
        if result["status"] == "success":
            result["action"] = "get_bot_management"
        return result

    async def _update_bot_management(self, config: CloudflareUpdateBotManagementConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {}
        if config.enable_js is not None:
            payload["enable_js"] = config.enable_js == "true"
        if config.fight_mode is not None:
            payload["fight_mode"] = config.fight_mode == "true"
        if config.suppress_session_score is not None:
            payload["suppress_session_score"] = config.suppress_session_score == "true"
        if config.auto_update_model is not None:
            payload["auto_update_model"] = config.auto_update_model == "true"
        result = await self._cf_request("PUT", f"{BASE_URL}/zones/{config.zone_id}/bot_management", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_bot_management"
        return result

    # ── Speed Observatory ─────────────────────────────────────────────────────────

    async def _list_observatory_pages(self, config: CloudflareListObservatoryPagesConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {"region": config.region or "us-central1"}
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/speed_api/pages", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_observatory_pages"
        return result

    async def _list_page_speed_tests(self, config: CloudflareListPageSpeedTestsConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {"region": config.region or "us-central1", "url": config.page_url, "per_page": config.per_page or 20}
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/speed_api/pages/{urllib.parse.quote(config.page_url, safe='')}/tests", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_page_speed_tests"
        return result

    async def _create_page_speed_test(self, config: CloudflareCreatePageSpeedTestConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"region": config.region or "us-central1"}
        result = await self._cf_request("POST", f"{BASE_URL}/zones/{config.zone_id}/speed_api/pages/{urllib.parse.quote(config.page_url, safe='')}/tests", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_page_speed_test"
        return result

    async def _delete_page_speed_tests(self, config: CloudflareDeletePageSpeedTestsConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {"region": config.region or "us-central1"}
        result = await self._cf_request("DELETE", f"{BASE_URL}/zones/{config.zone_id}/speed_api/pages/{urllib.parse.quote(config.page_url, safe='')}/tests", creds, params=params)
        if result["status"] == "success":
            result["action"] = "delete_page_speed_tests"
        return result

    async def _get_speed_test_schedule(self, config: CloudflareGetSpeedTestScheduleConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {"region": config.region or "us-central1"}
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/speed_api/schedule/{urllib.parse.quote(config.page_url, safe='')}", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_speed_test_schedule"
        return result

    # ── Web Analytics ─────────────────────────────────────────────────────────────

    async def _list_web_analytics_sites(self, config: CloudflareListWebAnalyticsSitesConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {"per_page": config.per_page or 25, "page": config.page or 1}
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/rum/site_info/list", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_web_analytics_sites"
        return result

    async def _create_web_analytics_site(self, config: CloudflareCreateWebAnalyticsSiteConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"host": config.host, "auto_install": config.auto_install == "true"}
        if config.zone_tag:
            payload["zone_tag"] = config.zone_tag
        result = await self._cf_request("POST", f"{await self._account_path(creds)}/rum/site_info", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_web_analytics_site"
        return result

    async def _get_web_analytics_site(self, config: CloudflareGetWebAnalyticsSiteConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/rum/site_info/{config.site_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_web_analytics_site"
        return result

    async def _delete_web_analytics_site(self, config: CloudflareDeleteWebAnalyticsSiteConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{await self._account_path(creds)}/rum/site_info/{config.site_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_web_analytics_site"
        return result


    # ── Account Members ───────────────────────────────────────────────────────────

    async def _list_account_members(self, config: CloudflareListAccountMembersConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {"page": config.page or 1, "per_page": config.per_page or 20}
        if config.status:
            params["status"] = config.status
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/members", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_account_members"
        return result

    async def _get_account_member(self, config: CloudflareGetAccountMemberConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/members/{config.member_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_account_member"
        return result

    async def _add_account_member(self, config: CloudflareAddAccountMemberConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"email": config.email, "roles": [{"id": r.strip()} for r in config.role_ids.split(",")], "status": config.status or "pending"}
        result = await self._cf_request("POST", f"{await self._account_path(creds)}/members", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "add_account_member"
        return result

    async def _update_account_member(self, config: CloudflareUpdateAccountMemberConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"roles": [{"id": r.strip()} for r in config.role_ids.split(",")]}
        result = await self._cf_request("PUT", f"{await self._account_path(creds)}/members/{config.member_id}", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_account_member"
        return result

    async def _remove_account_member(self, config: CloudflareRemoveAccountMemberConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{await self._account_path(creds)}/members/{config.member_id}", creds)
        if result["status"] == "success":
            result["action"] = "remove_account_member"
        return result

    async def _list_account_roles(self, config: CloudflareListAccountRolesConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/roles", creds)
        if result["status"] == "success":
            result["action"] = "list_account_roles"
        return result

    # ── Tunnel Routes / Virtual Networks ──────────────────────────────────────────

    async def _list_tunnel_routes(self, config: CloudflareListTunnelRoutesConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {"per_page": config.per_page or 25}
        if config.tunnel_id:
            params["tunnel_id"] = config.tunnel_id
        if config.virtual_network_id:
            params["virtual_network_id"] = config.virtual_network_id
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/teamnet/routes", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_tunnel_routes"
        return result

    async def _create_tunnel_route(self, config: CloudflareCreateTunnelRouteConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"network": config.network_cidr, "tunnel_id": config.tunnel_id}
        if config.virtual_network_id:
            payload["virtual_network_id"] = config.virtual_network_id
        if config.comment:
            payload["comment"] = config.comment
        result = await self._cf_request("POST", f"{await self._account_path(creds)}/teamnet/routes", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_tunnel_route"
        return result

    async def _update_tunnel_route(self, config: CloudflareUpdateTunnelRouteConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {}
        if config.tunnel_id:
            payload["tunnel_id"] = config.tunnel_id
        if config.virtual_network_id:
            payload["virtual_network_id"] = config.virtual_network_id
        if config.comment is not None:
            payload["comment"] = config.comment
        result = await self._cf_request("PATCH", f"{await self._account_path(creds)}/teamnet/routes/network/{urllib.parse.quote(config.network_cidr, safe='')}", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_tunnel_route"
        return result

    async def _delete_tunnel_route(self, config: CloudflareDeleteTunnelRouteConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{await self._account_path(creds)}/teamnet/routes/network/{urllib.parse.quote(config.network_cidr, safe='')}", creds)
        if result["status"] == "success":
            result["action"] = "delete_tunnel_route"
        return result

    async def _list_virtual_networks(self, config: CloudflareListVirtualNetworksConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {}
        if config.is_default_network is not None:
            params["is_default_network"] = config.is_default_network == "true"
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/teamnet/virtual_networks", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_virtual_networks"
        return result

    async def _create_virtual_network(self, config: CloudflareCreateVirtualNetworkConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"name": config.vnet_name, "is_default_network": config.is_default_network == "true"}
        if config.comment:
            payload["comment"] = config.comment
        result = await self._cf_request("POST", f"{await self._account_path(creds)}/teamnet/virtual_networks", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_virtual_network"
        return result

    async def _get_virtual_network(self, config: CloudflareGetVirtualNetworkConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/teamnet/virtual_networks/{config.virtual_network_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_virtual_network"
        return result

    async def _update_virtual_network(self, config: CloudflareUpdateVirtualNetworkConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {}
        if config.vnet_name:
            payload["name"] = config.vnet_name
        if config.is_default_network is not None:
            payload["is_default_network"] = config.is_default_network == "true"
        if config.comment is not None:
            payload["comment"] = config.comment
        result = await self._cf_request("PATCH", f"{await self._account_path(creds)}/teamnet/virtual_networks/{config.virtual_network_id}", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_virtual_network"
        return result

    async def _delete_virtual_network(self, config: CloudflareDeleteVirtualNetworkConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{await self._account_path(creds)}/teamnet/virtual_networks/{config.virtual_network_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_virtual_network"
        return result

    # ── Load Balancer Extensions ──────────────────────────────────────────────────

    async def _update_load_balancer(self, config: CloudflareUpdateLoadBalancerConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {}
        if config.lb_name:
            payload["name"] = config.lb_name
        if config.fallback_pool:
            payload["fallback_pool"] = config.fallback_pool
        if config.default_pools:
            payload["default_pools"] = [p.strip() for p in config.default_pools.split(",")]
        if config.proxied is not None:
            payload["proxied"] = config.proxied == "true"
        if config.session_affinity:
            payload["session_affinity"] = config.session_affinity
        if config.ttl is not None:
            payload["ttl"] = config.ttl
        if config.description:
            payload["description"] = config.description
        result = await self._cf_request("PATCH", f"{BASE_URL}/zones/{config.zone_id}/load_balancers/{config.lb_id}", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_load_balancer"
        return result

    async def _get_load_balancer_pool(self, config: CloudflareGetLBPoolConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/load_balancers/pools/{config.pool_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_load_balancer_pool"
        return result

    async def _update_load_balancer_pool(self, config: CloudflareUpdateLBPoolConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        payload: Dict[str, Any] = {}
        if config.pool_name:
            payload["name"] = config.pool_name
        if config.origins_json:
            payload["origins"] = _json.loads(config.origins_json)
        if config.monitor:
            payload["monitor"] = config.monitor
        if config.description:
            payload["description"] = config.description
        if config.enabled is not None:
            payload["enabled"] = config.enabled == "true"
        if config.minimum_origins is not None:
            payload["minimum_origins"] = config.minimum_origins
        if config.notification_email:
            payload["notification_email"] = config.notification_email
        result = await self._cf_request("PATCH", f"{await self._account_path(creds)}/load_balancers/pools/{config.pool_id}", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_load_balancer_pool"
        return result

    async def _delete_load_balancer_pool(self, config: CloudflareDeleteLBPoolConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{await self._account_path(creds)}/load_balancers/pools/{config.pool_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_load_balancer_pool"
        return result

    async def _list_load_balancer_monitors(self, config: CloudflareListLBMonitorsConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/load_balancers/monitors", creds)
        if result["status"] == "success":
            result["action"] = "list_load_balancer_monitors"
        return result

    async def _get_load_balancer_monitor(self, config: CloudflareGetLBMonitorConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/load_balancers/monitors/{config.monitor_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_load_balancer_monitor"
        return result

    async def _create_load_balancer_monitor(self, config: CloudflareCreateLBMonitorConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"type": config.monitor_type, "timeout": config.timeout or 5, "interval": config.interval or 60, "retries": config.retries or 2}
        if config.expected_codes:
            payload["expected_codes"] = config.expected_codes
        if config.method:
            payload["method"] = config.method
        if config.path:
            payload["path"] = config.path
        if config.description:
            payload["description"] = config.description
        if config.port is not None:
            payload["port"] = config.port
        result = await self._cf_request("POST", f"{await self._account_path(creds)}/load_balancers/monitors", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_load_balancer_monitor"
        return result

    async def _delete_load_balancer_monitor(self, config: CloudflareDeleteLBMonitorConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{await self._account_path(creds)}/load_balancers/monitors/{config.monitor_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_load_balancer_monitor"
        return result

    async def _get_load_balancer_pool_health(self, config: CloudflareGetLBPoolHealthConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/load_balancers/pools/{config.pool_id}/health", creds)
        if result["status"] == "success":
            result["action"] = "get_load_balancer_pool_health"
        return result

    # ── Access Extensions ─────────────────────────────────────────────────────────

    async def _create_access_policy(self, config: CloudflareCreateAccessPolicyConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        payload: Dict[str, Any] = {"name": config.policy_name, "decision": config.decision, "include": _json.loads(config.include_json)}
        if config.exclude_json:
            payload["exclude"] = _json.loads(config.exclude_json)
        if config.require_json:
            payload["require"] = _json.loads(config.require_json)
        if config.precedence is not None:
            payload["precedence"] = config.precedence
        if config.session_duration:
            payload["session_duration"] = config.session_duration
        result = await self._cf_request("POST", f"{await self._account_path(creds)}/access/apps/{config.app_id}/policies", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_access_policy"
        return result

    async def _update_access_policy(self, config: CloudflareUpdateAccessPolicyConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        payload: Dict[str, Any] = {}
        if config.policy_name:
            payload["name"] = config.policy_name
        if config.decision:
            payload["decision"] = config.decision
        if config.include_json:
            payload["include"] = _json.loads(config.include_json)
        if config.exclude_json:
            payload["exclude"] = _json.loads(config.exclude_json)
        if config.require_json:
            payload["require"] = _json.loads(config.require_json)
        if config.precedence is not None:
            payload["precedence"] = config.precedence
        result = await self._cf_request("PUT", f"{await self._account_path(creds)}/access/apps/{config.app_id}/policies/{config.policy_id}", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_access_policy"
        return result

    async def _delete_access_policy(self, config: CloudflareDeleteAccessPolicyConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{await self._account_path(creds)}/access/apps/{config.app_id}/policies/{config.policy_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_access_policy"
        return result

    async def _get_access_policy(self, config: CloudflareGetAccessPolicyConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/access/apps/{config.app_id}/policies/{config.policy_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_access_policy"
        return result

    async def _list_access_groups(self, config: CloudflareListAccessGroupsConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {"page": config.page or 1, "per_page": config.per_page or 25}
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/access/groups", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_access_groups"
        return result

    async def _get_access_group(self, config: CloudflareGetAccessGroupConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/access/groups/{config.group_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_access_group"
        return result

    async def _create_access_group(self, config: CloudflareCreateAccessGroupConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        payload: Dict[str, Any] = {"name": config.group_name, "include": _json.loads(config.include_json)}
        if config.exclude_json:
            payload["exclude"] = _json.loads(config.exclude_json)
        if config.require_json:
            payload["require"] = _json.loads(config.require_json)
        result = await self._cf_request("POST", f"{await self._account_path(creds)}/access/groups", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_access_group"
        return result

    async def _update_access_group(self, config: CloudflareUpdateAccessGroupConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        payload: Dict[str, Any] = {}
        if config.group_name:
            payload["name"] = config.group_name
        if config.include_json:
            payload["include"] = _json.loads(config.include_json)
        if config.exclude_json:
            payload["exclude"] = _json.loads(config.exclude_json)
        if config.require_json:
            payload["require"] = _json.loads(config.require_json)
        result = await self._cf_request("PUT", f"{await self._account_path(creds)}/access/groups/{config.group_id}", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_access_group"
        return result

    async def _delete_access_group(self, config: CloudflareDeleteAccessGroupConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{await self._account_path(creds)}/access/groups/{config.group_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_access_group"
        return result

    async def _list_access_service_tokens(self, config: CloudflareListAccessServiceTokensConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/access/service_tokens", creds)
        if result["status"] == "success":
            result["action"] = "list_access_service_tokens"
        return result

    async def _create_access_service_token(self, config: CloudflareCreateAccessServiceTokenConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"name": config.token_name}
        if config.duration:
            payload["duration"] = config.duration
        result = await self._cf_request("POST", f"{await self._account_path(creds)}/access/service_tokens", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_access_service_token"
        return result

    async def _refresh_access_service_token(self, config: CloudflareRefreshAccessServiceTokenConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("POST", f"{await self._account_path(creds)}/access/service_tokens/{config.token_id}/refresh", creds, json={})
        if result["status"] == "success":
            result["action"] = "refresh_access_service_token"
        return result

    async def _delete_access_service_token(self, config: CloudflareDeleteAccessServiceTokenConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{await self._account_path(creds)}/access/service_tokens/{config.token_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_access_service_token"
        return result

    # ── Tunnel Extensions ─────────────────────────────────────────────────────────

    async def _update_tunnel(self, config: CloudflareUpdateTunnelConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {}
        if config.tunnel_name:
            payload["name"] = config.tunnel_name
        if config.tunnel_secret:
            payload["tunnel_secret"] = config.tunnel_secret
        result = await self._cf_request("PATCH", f"{await self._account_path(creds)}/cfd_tunnel/{config.tunnel_id}", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "update_tunnel"
        return result

    async def _get_tunnel_configuration(self, config: CloudflareGetTunnelConfigurationConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/cfd_tunnel/{config.tunnel_id}/configurations", creds)
        if result["status"] == "success":
            result["action"] = "get_tunnel_configuration"
        return result

    async def _put_tunnel_configuration(self, config: CloudflarePutTunnelConfigurationConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        ingress = _json.loads(config.ingress_json)
        payload: Dict[str, Any] = {"config": {"ingress": ingress, "warp-routing": {"enabled": config.warp_routing_enabled == "true"}}}
        result = await self._cf_request("PUT", f"{await self._account_path(creds)}/cfd_tunnel/{config.tunnel_id}/configurations", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "put_tunnel_configuration"
        return result

    async def _list_tunnel_connections(self, config: CloudflareListTunnelConnectionsConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/cfd_tunnel/{config.tunnel_id}/connections", creds)
        if result["status"] == "success":
            result["action"] = "list_tunnel_connections"
        return result

    # ── Email Routing Extensions ──────────────────────────────────────────────────

    async def _enable_email_routing(self, config: CloudflareEnableEmailRoutingConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("POST", f"{BASE_URL}/zones/{config.zone_id}/email/routing/enable", creds, json={})
        if result["status"] == "success":
            result["action"] = "enable_email_routing"
        return result

    async def _disable_email_routing(self, config: CloudflareDisableEmailRoutingConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("POST", f"{BASE_URL}/zones/{config.zone_id}/email/routing/disable", creds, json={})
        if result["status"] == "success":
            result["action"] = "disable_email_routing"
        return result

    async def _create_email_routing_destination(self, config: CloudflareCreateEmailRoutingDestinationConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"email": config.destination_email}
        result = await self._cf_request("POST", f"{BASE_URL}/zones/{config.zone_id}/email/routing/addresses", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_email_routing_destination"
        return result

    async def _delete_email_routing_destination(self, config: CloudflareDeleteEmailRoutingDestinationConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{BASE_URL}/zones/{config.zone_id}/email/routing/addresses/{config.address_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_email_routing_destination"
        return result

    # ── Queue Extensions ──────────────────────────────────────────────────────────

    async def _update_queue(self, config: CloudflareUpdateQueueConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("PUT", f"{await self._account_path(creds)}/queues/{config.queue_id}", creds, json={"queue_name": config.new_queue_name})
        if result["status"] == "success":
            result["action"] = "update_queue"
        return result

    async def _acknowledge_queue_messages(self, config: CloudflareAcknowledgeQueueMessagesConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"acks": [{"lease_id": lid.strip()} for lid in config.lease_ids.split(",")]}
        if config.retry_lease_ids:
            retry_params: Dict[str, Any] = {}
            if config.retry_delay_seconds is not None:
                retry_params["delay_seconds"] = config.retry_delay_seconds
            payload["retries"] = [dict({"lease_id": lid.strip()}, **retry_params) for lid in config.retry_lease_ids.split(",")]
        result = await self._cf_request("POST", f"{await self._account_path(creds)}/queues/{config.queue_id}/messages/ack", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "acknowledge_queue_messages"
        return result

    async def _list_queue_consumers(self, config: CloudflareListQueueConsumersConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{await self._account_path(creds)}/queues/{config.queue_id}/consumers", creds)
        if result["status"] == "success":
            result["action"] = "list_queue_consumers"
        return result

    async def _create_queue_consumer(self, config: CloudflareCreateQueueConsumerConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"script_name": config.script_name, "settings": {"batch_size": config.batch_size or 10, "max_retries": config.max_retries or 3, "max_wait_time_ms": config.max_wait_time_ms or 5000}}
        result = await self._cf_request("POST", f"{await self._account_path(creds)}/queues/{config.queue_id}/consumers", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_queue_consumer"
        return result

    async def _delete_queue_consumer(self, config: CloudflareDeleteQueueConsumerConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{await self._account_path(creds)}/queues/{config.queue_id}/consumers/{config.consumer_name}", creds)
        if result["status"] == "success":
            result["action"] = "delete_queue_consumer"
        return result

    # ── SSL / TLS Extensions ──────────────────────────────────────────────────────

    async def _update_zone_ssl_settings(self, config: CloudflareUpdateZoneSSLSettingsConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("PATCH", f"{BASE_URL}/zones/{config.zone_id}/settings/ssl", creds, json={"value": config.ssl_mode})
        if result["status"] == "success":
            result["action"] = "update_zone_ssl_settings"
        return result

    async def _upload_ssl_certificate(self, config: CloudflareUploadSSLCertificateConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"certificate": config.certificate, "private_key": config.private_key, "bundle_method": config.bundle_method or "ubiquitous"}
        result = await self._cf_request("POST", f"{BASE_URL}/zones/{config.zone_id}/custom_certificates", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "upload_ssl_certificate"
        return result

    async def _delete_ssl_certificate(self, config: CloudflareDeleteSSLCertificateConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("DELETE", f"{BASE_URL}/zones/{config.zone_id}/custom_certificates/{config.certificate_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_ssl_certificate"
        return result

    # ── Pages Extensions ──────────────────────────────────────────────────────────

    async def _create_pages_project(self, config: CloudflareCreatePagesProjectConfig, creds: CloudflareCredential) -> Dict:
        payload: Dict[str, Any] = {"name": config.project_name, "production_branch": config.production_branch or "main"}
        if config.build_command or config.destination_dir:
            payload["build_config"] = {}
            if config.build_command:
                payload["build_config"]["build_command"] = config.build_command
            if config.destination_dir:
                payload["build_config"]["destination_dir"] = config.destination_dir
        result = await self._cf_request("POST", f"{await self._account_path(creds)}/pages/projects", creds, json=payload)
        if result["status"] == "success":
            result["action"] = "create_pages_project"
        return result

    async def _retry_pages_deployment(self, config: CloudflareRetryPagesDeploymentConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("POST", f"{await self._account_path(creds)}/pages/projects/{config.project_name}/deployments/{config.deployment_id}/retry", creds, json={})
        if result["status"] == "success":
            result["action"] = "retry_pages_deployment"
        return result

    # ── DNS Extensions ────────────────────────────────────────────────────────────

    async def _export_dns_records(self, config: CloudflareExportDNSRecordsConfig, creds: CloudflareCredential) -> Dict:
        await self._ensure_fresh_token(creds)
        headers = self._get_headers(creds)
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{BASE_URL}/zones/{config.zone_id}/dns_records/export", headers=headers, timeout=30)
        if resp.status_code != 200:
            return {"status": "error", "error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
        return {"status": "success", "action": "export_dns_records", "data": resp.text}

    async def _get_dnssec(self, config: CloudflareGetDNSSECConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("GET", f"{BASE_URL}/zones/{config.zone_id}/dnssec", creds)
        if result["status"] == "success":
            result["action"] = "get_dnssec"
        return result

    async def _update_dnssec(self, config: CloudflareUpdateDNSSECConfig, creds: CloudflareCredential) -> Dict:
        result = await self._cf_request("PATCH", f"{BASE_URL}/zones/{config.zone_id}/dnssec", creds, json={"status": config.dnssec_status})
        if result["status"] == "success":
            result["action"] = "update_dnssec"
        return result

    # ── R2 Object Operations ──────────────────────────────────────────────────────

    async def _list_r2_objects(self, config: CloudflareListR2ObjectsConfig, creds: CloudflareCredential) -> Dict:
        import asyncio, boto3  # type: ignore
        def _do_list():
            s3 = boto3.client("s3", endpoint_url=_r2_endpoint_url(config.account_id), aws_access_key_id=config.r2_access_key_id, aws_secret_access_key=config.r2_secret_access_key, region_name="auto")
            kwargs: Dict[str, Any] = {"Bucket": config.bucket_name, "MaxKeys": config.max_keys or 1000}
            if config.prefix:
                kwargs["Prefix"] = config.prefix
            resp = s3.list_objects_v2(**kwargs)
            return [{"key": o["Key"], "size": o["Size"], "last_modified": o["LastModified"].isoformat()} for o in resp.get("Contents", [])]
        objects = await asyncio.to_thread(_do_list)
        return {"status": "success", "action": "list_r2_objects", "data": objects}

    async def _get_r2_object(self, config: CloudflareGetR2ObjectConfig, creds: CloudflareCredential) -> Dict:
        import asyncio, boto3  # type: ignore
        def _do_get():
            s3 = boto3.client("s3", endpoint_url=_r2_endpoint_url(config.account_id), aws_access_key_id=config.r2_access_key_id, aws_secret_access_key=config.r2_secret_access_key, region_name="auto")
            resp = s3.get_object(Bucket=config.bucket_name, Key=config.object_key)
            body = resp["Body"].read()
            content_type = resp.get("ContentType", "application/octet-stream")
            try:
                return {"content": body.decode("utf-8"), "content_type": content_type, "is_binary": False}
            except UnicodeDecodeError:
                import base64
                return {"content": base64.b64encode(body).decode(), "content_type": content_type, "is_binary": True}
        data = await asyncio.to_thread(_do_get)
        return {"status": "success", "action": "get_r2_object", "data": data}

    async def _put_r2_object(self, config: CloudflarePutR2ObjectConfig, creds: CloudflareCredential) -> Dict:
        import asyncio, boto3  # type: ignore
        def _do_put():
            s3 = boto3.client("s3", endpoint_url=_r2_endpoint_url(config.account_id), aws_access_key_id=config.r2_access_key_id, aws_secret_access_key=config.r2_secret_access_key, region_name="auto")
            if config.is_base64 == "true":
                import base64
                body = base64.b64decode(config.content)
            else:
                body = config.content.encode("utf-8")
            s3.put_object(Bucket=config.bucket_name, Key=config.object_key, Body=body, ContentType=config.content_type or "text/plain")
        await asyncio.to_thread(_do_put)
        return {"status": "success", "action": "put_r2_object", "data": {"bucket": config.bucket_name, "key": config.object_key}}

    async def _delete_r2_object(self, config: CloudflareDeleteR2ObjectConfig, creds: CloudflareCredential) -> Dict:
        import asyncio, boto3  # type: ignore
        def _do_delete():
            s3 = boto3.client("s3", endpoint_url=_r2_endpoint_url(config.account_id), aws_access_key_id=config.r2_access_key_id, aws_secret_access_key=config.r2_secret_access_key, region_name="auto")
            s3.delete_object(Bucket=config.bucket_name, Key=config.object_key)
        await asyncio.to_thread(_do_delete)
        return {"status": "success", "action": "delete_r2_object", "data": {"bucket": config.bucket_name, "key": config.object_key}}

    async def _get_r2_presigned_url(self, config: CloudflareGetR2PresignedUrlConfig, creds: CloudflareCredential) -> Dict:
        import asyncio, boto3  # type: ignore
        def _do_presign():
            s3 = boto3.client("s3", endpoint_url=_r2_endpoint_url(config.account_id), aws_access_key_id=config.r2_access_key_id, aws_secret_access_key=config.r2_secret_access_key, region_name="auto")
            op = config.operation_type or "get_object"
            method_map = {"get_object": "get_object", "put_object": "put_object"}
            url = s3.generate_presigned_url(method_map[op], Params={"Bucket": config.bucket_name, "Key": config.object_key}, ExpiresIn=config.expiry_seconds or 3600)
            return url
        url = await asyncio.to_thread(_do_presign)
        return {"status": "success", "action": "get_r2_presigned_url", "data": {"url": url, "expires_in": config.expiry_seconds or 3600}}

    # ── Alert Trigger (ExternalWebhookTriggerMixin) ────────────────────────────────

    def _get_webhook_secret(self, config_obj: Any) -> Optional[str]:
        """Return the stored webhook secret for signature verification."""
        if hasattr(config_obj, "webhook_secret"):
            return config_obj.webhook_secret
        return None

    @classmethod
    async def _cf_api(cls, method: str, path: str, credential: Dict[str, Any], *, json: Any = None) -> Dict[str, Any]:
        """Minimal classmethod HTTP helper for webhook register/unregister paths."""
        import httpx as _httpx
        token = credential.get("access_token") or credential.get("api_token") or credential.get("api_key")
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if credential.get("access_token") or credential.get("api_token"):
            headers["Authorization"] = f"Bearer {token}"
        else:
            headers["X-Auth-Key"] = credential.get("api_key", "")
            headers["X-Auth-Email"] = credential.get("email", "")
        url = f"{BASE_URL}{path}"
        async with _httpx.AsyncClient(timeout=30.0) as hc:
            resp = await hc.request(method, url, headers=headers, json=json)
        try:
            data = resp.json()
        except Exception:
            data = {}
        if resp.status_code >= 400:
            errors = data.get("errors") or []
            msg = errors[0].get("message", resp.text) if errors else resp.text
            return {"status": "error", "error": msg}
        return {"status": "success", "result": data.get("result", data)}

    @classmethod
    def registration_fingerprint_fields(cls, config):
        # Config fields the provider-side registration depends on — feed the
        # reconciler's fingerprint so edits here re-register (declarative:
        # the node never sequences teardown/re-register).
        return {
            "alert_type": (config or {}).get("alert_type"),
            "policy_name": (config or {}).get("policy_name"),
            "ddos_layer": (config or {}).get("ddos_layer"),
            "email_alert_type": (config or {}).get("email_alert_type"),
            "lb_alert_type": (config or {}).get("lb_alert_type"),
            "mt_alert_type": (config or {}).get("mt_alert_type"),
            "page_shield_alert_type": (config or {}).get("page_shield_alert_type"),
            "ssl_alert_type": (config or {}).get("ssl_alert_type"),
            "tunnel_alert_type": (config or {}).get("tunnel_alert_type"),
            "waiting_room_alert_type": (config or {}).get("waiting_room_alert_type"),
            "worker_alert_type": (config or {}).get("worker_alert_type"),
            "zt_alert_type": (config or {}).get("zt_alert_type"),
        }

    @classmethod
    async def _register_external_webhook(
        cls, *, webhook_url: str, credential: Dict[str, Any], config: Dict[str, Any], node_id: str
    ) -> Dict[str, Any]:
        """Register a Cloudflare Notifications webhook + policy (alert trigger) or Stream webhook."""
        credential = credential or {}
        config = config or {}
        operation = config.get("operation", "")
        account_id = credential.get("account_id")
        if not account_id:
            # Legacy credential without stored account_id — fetch it
            result = await cls._cf_api("GET", "/accounts", credential)
            accounts = result.get("result") or []
            if accounts:
                account_id = accounts[0]["id"]
        if not account_id:
            raise ValueError("account_id is required in Cloudflare credential for trigger registration")
        acct_path = f"/accounts/{account_id}"

        if operation == "cloudflare_stream_event":
            wh_secret = _secrets.token_hex(32)
            resp = await cls._cf_api("POST", f"{acct_path}/stream/webhook", credential, json={"notificationUrl": webhook_url, "secret": wh_secret})
            if resp.get("status") != "success":
                raise ValueError(f"Failed to register Cloudflare Stream webhook: {resp.get('error')}")
            return {"webhook_secret": wh_secret}

        # Alert-type triggers
        alert_type = (
            config.get("alert_type")
            or config.get("ddos_layer")
            or config.get("ssl_alert_type")
            or config.get("tunnel_alert_type")
            or config.get("worker_alert_type")
            or config.get("lb_alert_type")
            or config.get("waiting_room_alert_type")
            or config.get("page_shield_alert_type")
            or config.get("zt_alert_type")
            or config.get("email_alert_type")
            or config.get("mt_alert_type")
        )
        if not alert_type:
            raise ValueError(f"No alert type found in config for operation '{operation}'")
        policy_label = config.get("policy_name") or alert_type
        wh_secret = _secrets.token_hex(32)
        wh_resp = await cls._cf_api("POST", f"{acct_path}/alerting/v3/destinations/webhooks", credential, json={"name": f"NoClick-{policy_label}", "url": webhook_url, "secret": wh_secret})
        if wh_resp.get("status") != "success":
            raise ValueError(f"Failed to register Cloudflare notification webhook: {wh_resp.get('error')}")
        cf_webhook_id = wh_resp["result"]["id"]
        policy_payload: Dict[str, Any] = {"name": config.get("policy_name") or f"NoClick - {alert_type}", "alert_type": alert_type, "enabled": True, "mechanisms": {"webhooks": [{"id": cf_webhook_id}]}}
        policy_resp = await cls._cf_api("POST", f"{acct_path}/alerting/v3/policies", credential, json=policy_payload)
        if policy_resp.get("status") != "success":
            await cls._cf_api("DELETE", f"{acct_path}/alerting/v3/destinations/webhooks/{cf_webhook_id}", credential)
            raise ValueError(f"Failed to create Cloudflare alert policy: {policy_resp.get('error')}")
        cf_policy_id = policy_resp["result"]["id"]
        return {"cf_webhook_id": cf_webhook_id, "cf_policy_id": cf_policy_id, "webhook_secret": wh_secret}

    @classmethod
    async def _unregister_external_webhook(
        cls, *, credential: Optional[Dict[str, Any]], config: Dict[str, Any], node_id: str
    ) -> None:
        """Remove the Cloudflare webhook registration for alert or Stream triggers."""
        credential = credential or {}
        config = config or {}
        operation = config.get("operation", "")
        account_id = credential.get("account_id")
        if not account_id:
            return

        acct_path = f"/accounts/{account_id}"
        if operation == "cloudflare_stream_event":
            await cls._cf_api("DELETE", f"{acct_path}/stream/webhook", credential)
            return

        if config.get("cf_policy_id"):
            await cls._cf_api("DELETE", f"{acct_path}/alerting/v3/policies/{config['cf_policy_id']}", credential)
        if config.get("cf_webhook_id"):
            await cls._cf_api("DELETE", f"{acct_path}/alerting/v3/destinations/webhooks/{config['cf_webhook_id']}", credential)

    @classmethod
    def verify_webhook_signature(
        cls, body: bytes, headers: Dict[str, str], config: Dict[str, Any]
    ) -> bool:
        """Verify HMAC signature from Cloudflare webhook (Notifications or Stream).

        The receiver calls this on the CLASS with the node's config dict — there
        is no instance — so the secret is read from the config blob, not
        ``self.config``. ``signing_secret`` is the framework's key; the legacy
        ``webhook_secret`` is still read for nodes registered before then.
        """
        import base64, hashlib

        cfg = config or {}
        stored = cfg.get("signing_secret") or cfg.get("webhook_secret") or ""
        if not stored:
            return True  # no secret stored → the unguessable URL is the capability
        if cfg.get("operation") == "cloudflare_stream_event":
            # Stream uses X-Webhook-Signature: time=...,sig1=...
            token = headers.get("x-webhook-signature") or ""
            sig1_part = next((p.split("=", 1)[1] for p in token.split(",") if p.startswith("sig1=")), "")
            time_part = next((p.split("=", 1)[1] for p in token.split(",") if p.startswith("time=")), "")
            msg = f"{time_part}.{body.decode('utf-8', errors='replace')}"
            expected = hmac.new(stored.encode(), msg.encode(), hashlib.sha256).hexdigest()
            return hmac.compare_digest(expected, sig1_part)
        # Every alert family (generic/DDoS/SSL/tunnel/worker/LB/…) is delivered
        # with X-Cloudflare-Security-Token: base64 HMAC-SHA256 of the raw body.
        token = headers.get("x-cloudflare-security-token") or ""
        sig = base64.b64encode(hmac.new(stored.encode(), body, hashlib.sha256).digest()).decode()
        return hmac.compare_digest(sig, token)

    # ── Webhook trigger execute handlers (manual-run / trigger payload delivery) ──

    async def _handle_alert_trigger(self, config: Any, creds: Any) -> Dict[str, Any]:
        """Return trigger payload when a Cloudflare alert webhook fires (or a placeholder on manual run)."""
        node_config_data = (self.node_data or {}).get("config", {})
        trigger_payload = node_config_data.get("_triggerPayload")
        if trigger_payload:
            return {"status": "success", "action": "cloudflare_alert", "data": trigger_payload}
        return {"status": "success", "action": "cloudflare_alert", "message": "Waiting for Cloudflare alert webhook"}

    async def _handle_stream_event_trigger(self, config: Any, creds: Any) -> Dict[str, Any]:
        """Return trigger payload when a Cloudflare Stream event webhook fires."""
        node_config_data = (self.node_data or {}).get("config", {})
        trigger_payload = node_config_data.get("_triggerPayload")
        if trigger_payload:
            return {"status": "success", "action": "cloudflare_stream_event", "data": trigger_payload}
        return {"status": "success", "action": "cloudflare_stream_event", "message": "Waiting for Cloudflare Stream event webhook"}

    async def _handle_ddos_alert_trigger(self, config: Any, creds: Any) -> Dict[str, Any]:
        """Return trigger payload when a Cloudflare DDoS alert fires."""
        node_config_data = (self.node_data or {}).get("config", {})
        trigger_payload = node_config_data.get("_triggerPayload")
        if trigger_payload:
            return {"status": "success", "action": "cloudflare_ddos_alert", "data": trigger_payload}
        return {"status": "success", "action": "cloudflare_ddos_alert", "message": "Waiting for Cloudflare DDoS alert webhook"}

    async def _handle_ssl_alert_trigger(self, config: Any, creds: Any) -> Dict[str, Any]:
        """Return trigger payload when a Cloudflare SSL/TLS certificate alert fires."""
        node_config_data = (self.node_data or {}).get("config", {})
        trigger_payload = node_config_data.get("_triggerPayload")
        if trigger_payload:
            return {"status": "success", "action": "cloudflare_ssl_alert", "data": trigger_payload}
        return {"status": "success", "action": "cloudflare_ssl_alert", "message": "Waiting for Cloudflare SSL/TLS alert webhook"}

    async def _handle_tunnel_alert_trigger(self, config: Any, creds: Any) -> Dict[str, Any]:
        """Return trigger payload when a Cloudflare Tunnel health/event alert fires."""
        node_config_data = (self.node_data or {}).get("config", {})
        trigger_payload = node_config_data.get("_triggerPayload")
        if trigger_payload:
            return {"status": "success", "action": "cloudflare_tunnel_alert", "data": trigger_payload}
        return {"status": "success", "action": "cloudflare_tunnel_alert", "message": "Waiting for Cloudflare Tunnel alert webhook"}

    async def _handle_worker_alert_trigger(self, config: Any, creds: Any) -> Dict[str, Any]:
        """Return trigger payload when a Cloudflare Workers error/usage alert fires."""
        node_config_data = (self.node_data or {}).get("config", {})
        trigger_payload = node_config_data.get("_triggerPayload")
        if trigger_payload:
            return {"status": "success", "action": "cloudflare_worker_alert", "data": trigger_payload}
        return {"status": "success", "action": "cloudflare_worker_alert", "message": "Waiting for Cloudflare Workers alert webhook"}

    async def _handle_load_balancer_alert_trigger(self, config: Any, creds: Any) -> Dict[str, Any]:
        """Return trigger payload when a Cloudflare Load Balancer pool health/enablement alert fires."""
        node_config_data = (self.node_data or {}).get("config", {})
        trigger_payload = node_config_data.get("_triggerPayload")
        if trigger_payload:
            return {"status": "success", "action": "cloudflare_load_balancer_alert", "data": trigger_payload}
        return {"status": "success", "action": "cloudflare_load_balancer_alert", "message": "Waiting for Cloudflare Load Balancer alert webhook"}

    async def _handle_waiting_room_alert_trigger(self, config: Any, creds: Any) -> Dict[str, Any]:
        """Return trigger payload when a Cloudflare Waiting Room event alert fires."""
        node_config_data = (self.node_data or {}).get("config", {})
        trigger_payload = node_config_data.get("_triggerPayload")
        if trigger_payload:
            return {"status": "success", "action": "cloudflare_waiting_room_alert", "data": trigger_payload}
        return {"status": "success", "action": "cloudflare_waiting_room_alert", "message": "Waiting for Cloudflare Waiting Room alert webhook"}

    async def _handle_page_shield_alert_trigger(self, config: Any, creds: Any) -> Dict[str, Any]:
        """Return trigger payload when a Cloudflare Page Shield malicious script/URL alert fires."""
        node_config_data = (self.node_data or {}).get("config", {})
        trigger_payload = node_config_data.get("_triggerPayload")
        if trigger_payload:
            return {"status": "success", "action": "cloudflare_page_shield_alert", "data": trigger_payload}
        return {"status": "success", "action": "cloudflare_page_shield_alert", "message": "Waiting for Cloudflare Page Shield alert webhook"}

    async def _handle_zero_trust_alert_trigger(self, config: Any, creds: Any) -> Dict[str, Any]:
        """Return trigger payload when a Cloudflare Zero Trust Gateway alert fires."""
        node_config_data = (self.node_data or {}).get("config", {})
        trigger_payload = node_config_data.get("_triggerPayload")
        if trigger_payload:
            return {"status": "success", "action": "cloudflare_zero_trust_alert", "data": trigger_payload}
        return {"status": "success", "action": "cloudflare_zero_trust_alert", "message": "Waiting for Cloudflare Zero Trust Gateway alert webhook"}

    async def _handle_email_routing_alert_trigger(self, config: Any, creds: Any) -> Dict[str, Any]:
        """Return trigger payload when a Cloudflare Email Routing incident alert fires."""
        node_config_data = (self.node_data or {}).get("config", {})
        trigger_payload = node_config_data.get("_triggerPayload")
        if trigger_payload:
            return {"status": "success", "action": "cloudflare_email_routing_alert", "data": trigger_payload}
        return {"status": "success", "action": "cloudflare_email_routing_alert", "message": "Waiting for Cloudflare Email Routing alert webhook"}

    async def _handle_magic_transit_alert_trigger(self, config: Any, creds: Any) -> Dict[str, Any]:
        """Return trigger payload when a Cloudflare Magic Transit / BGP alert fires."""
        node_config_data = (self.node_data or {}).get("config", {})
        trigger_payload = node_config_data.get("_triggerPayload")
        if trigger_payload:
            return {"status": "success", "action": "cloudflare_magic_transit_alert", "data": trigger_payload}
        return {"status": "success", "action": "cloudflare_magic_transit_alert", "message": "Waiting for Cloudflare Magic Transit / BGP alert webhook"}

    # ── Poll Trigger handlers for newer trigger types ──────────────────────────────

    async def _trigger_r2_object_event(self, _config=None, _creds=None) -> Dict[str, Any]:
        """Poll a Cloudflare Queue for R2 object event notifications."""
        node_config = self.config
        if node_config is None or not isinstance(node_config, CloudflareNodeConfig):
            return {"status": "success", "result": [], "action": "cloudflare_r2_object_event"}
        config = node_config.config
        creds = node_config.credentials
        if not isinstance(config, CloudflareR2ObjectEventTriggerConfig):
            return {"status": "success", "result": [], "action": "cloudflare_r2_object_event"}
        credentials = self._load_credentials(creds)
        if credentials is None:
            return {"status": "success", "result": [], "action": "cloudflare_r2_object_event"}
        body: Dict[str, Any] = {"batch_size": config.batch_size or 10}
        result = await self._request("POST", f"{await self._account_path(credentials)}/queues/{config.queue_id}/messages/pull", credentials, json=body)
        if result.get("status") != "success":
            return {"status": "success", "result": [], "action": "cloudflare_r2_object_event"}
        messages = result.get("result", {}).get("messages") or []
        if not isinstance(messages, list):
            return []
        events = []
        for msg in messages:
            body_data = msg.get("body", {})
            if isinstance(body_data, str):
                try:
                    body_data = json.loads(body_data)
                except Exception:
                    pass
            bucket = body_data.get("bucket") if isinstance(body_data, dict) else None
            action = body_data.get("action") if isinstance(body_data, dict) else None
            key = body_data.get("key") if isinstance(body_data, dict) else None
            if config.bucket_name_filter and bucket != config.bucket_name_filter:
                continue
            if config.event_type_filter and action != config.event_type_filter:
                continue
            if config.key_prefix_filter and (not key or not key.startswith(config.key_prefix_filter)):
                continue
            events.append(msg)
        events = await self._filter_unseen(events, lambda x: x.get("id"))
        return {"status": "success", "result": events, "action": "cloudflare_r2_object_event"}

    async def _trigger_queue_delivery_event(self, _config=None, _creds=None) -> Dict[str, Any]:
        """Poll a Cloudflare Queue for delivery events."""
        node_config = self.config
        if node_config is None or not isinstance(node_config, CloudflareNodeConfig):
            return {"status": "success", "result": [], "action": "cloudflare_queue_delivery_event"}
        config = node_config.config
        creds = node_config.credentials
        if not isinstance(config, CloudflareQueueDeliveryEventTriggerConfig):
            return {"status": "success", "result": [], "action": "cloudflare_queue_delivery_event"}
        credentials = self._load_credentials(creds)
        if credentials is None:
            return {"status": "success", "result": [], "action": "cloudflare_queue_delivery_event"}
        body: Dict[str, Any] = {"batch_size": config.batch_size or 10, "visibility_timeout_ms": config.visibility_timeout_ms or 30000}
        result = await self._request("POST", f"{await self._account_path(credentials)}/queues/{config.queue_id}/messages/pull", credentials, json=body)
        if result.get("status") != "success":
            return {"status": "success", "result": [], "action": "cloudflare_queue_delivery_event"}
        messages = result.get("result", {}).get("messages") or []
        if not isinstance(messages, list):
            return []
        if config.body_contains_filter:
            messages = [m for m in messages if config.body_contains_filter in json.dumps(m.get("body", ""))]
        messages = await self._filter_unseen(messages, lambda x: x.get("id"))
        return {"status": "success", "result": messages, "action": "cloudflare_queue_delivery_event"}

    async def _trigger_worker_deployed(self, _config=None, _creds=None) -> Dict[str, Any]:
        """Poll Workers scripts list and fire when a new etag (deployment) is detected."""
        node_config = self.config
        if not isinstance(node_config, CloudflareNodeConfig):
            return {"status": "error", "error": "No config"}
        config = node_config.config
        if not isinstance(config, CloudflareWorkerDeployedTriggerConfig):
            return {"status": "error", "error": "Wrong config type"}
        credentials = self._load_credentials(node_config.credentials)
        if credentials is None:
            return {"status": "error", "error": "No credentials"}
        acct_path = await self._account_path(credentials)
        result = await self._cf_request("GET", f"{acct_path}/workers/scripts", credentials)
        scripts = result.get("result") or []
        if config.script_name_filter:
            scripts = [s for s in scripts if s.get("id") == config.script_name_filter]
        scripts = await self._filter_unseen(scripts, lambda s: f"{s.get('id')}:{s.get('etag', '')}")
        return {"status": "success", "result": scripts, "action": "cloudflare_worker_deployed"}

    async def _trigger_d1_new_rows(self, _config=None, _creds=None) -> Dict[str, Any]:
        """Poll a D1 database with a configurable SQL query and fire on new rows."""
        node_config = self.config
        if not isinstance(node_config, CloudflareNodeConfig):
            return {"status": "error", "error": "No config"}
        config = node_config.config
        if not isinstance(config, CloudflareD1NewRowsTriggerConfig):
            return {"status": "error", "error": "Wrong config type"}
        credentials = self._load_credentials(node_config.credentials)
        if credentials is None:
            return {"status": "error", "error": "No credentials"}
        acct_path = await self._account_path(credentials)
        sql = config.query
        if config.table_name:
            sql = sql.replace("{table}", config.table_name)
        result = await self._cf_request(
            "POST",
            f"{acct_path}/d1/database/{config.database_id}/query",
            credentials,
            json={"sql": sql},
        )
        rows = (((result.get("result") or [{}])[0]).get("results")) or []
        rows = await self._filter_unseen(rows, lambda r: str(r))
        return {"status": "success", "result": rows, "action": "cloudflare_d1_new_rows"}

    async def _trigger_kv_key_updated(self, _config=None, _creds=None) -> Dict[str, Any]:
        """Poll a KV namespace keys list and fire when keys are added or their expiration changes."""
        node_config = self.config
        if not isinstance(node_config, CloudflareNodeConfig):
            return {"status": "error", "error": "No config"}
        config = node_config.config
        if not isinstance(config, CloudflareKVKeyUpdatedTriggerConfig):
            return {"status": "error", "error": "Wrong config type"}
        credentials = self._load_credentials(node_config.credentials)
        if credentials is None:
            return {"status": "error", "error": "No credentials"}
        acct_path = await self._account_path(credentials)
        params: Dict[str, Any] = {}
        if config.prefix:
            params["prefix"] = config.prefix
        result = await self._cf_request(
            "GET",
            f"{acct_path}/storage/kv/namespaces/{config.namespace_id}/keys",
            credentials,
            params=params,
        )
        keys = result.get("result") or []
        keys = await self._filter_unseen(keys, lambda k: f"{k.get('name')}:{k.get('expiration', '')}")
        return {"status": "success", "result": keys, "action": "cloudflare_kv_key_updated"}

    # ── Audit Log Poll Trigger (ScheduledPollTriggerMixin) ─────────────────────────

    async def _poll_audit_logs(self, _config=None, _creds=None) -> Dict[str, Any]:
        """Poll Cloudflare audit logs for new entries."""
        node_config = self.config
        if node_config is None or not isinstance(node_config, CloudflareNodeConfig):
            return {"status": "success", "result": [], "action": "cloudflare_audit_log"}
        config = node_config.config
        creds = node_config.credentials
        if not isinstance(config, CloudflareAuditLogTriggerConfig):
            return {"status": "success", "result": [], "action": "cloudflare_audit_log"}
        credentials = self._load_credentials(creds)
        if credentials is None:
            return {"status": "success", "result": [], "action": "cloudflare_audit_log"}
        params: Dict[str, Any] = {"direction": "asc", "per_page": 100}
        if config.action_type_filter:
            params["action.type"] = config.action_type_filter
        if config.zone_name_filter:
            params["zone.name"] = config.zone_name_filter
        if config.actor_email_filter:
            params["actor.email"] = config.actor_email_filter
        result = await self._cf_request("GET", f"{await self._account_path(credentials)}/audit_logs", credentials, params=params)
        if result.get("status") != "success":
            return {"status": "success", "result": [], "action": "cloudflare_audit_log"}
        entries = result.get("result") or []
        if not isinstance(entries, list):
            return {"status": "success", "result": [], "action": "cloudflare_audit_log"}
        entries = await self._filter_unseen(entries, lambda x: x.get("id"))
        return {"status": "success", "result": entries, "action": "cloudflare_audit_log"}

    # ── Zone Management (extended) handlers ───────────────────────────────────────

    async def _create_zone(self, config: CloudflareCreateZoneConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = {"name": config.zone_name, "jump_start": config.jump_start == "true", "account": {"id": await self._resolve_account_id(creds)}}
        result = await self._request("POST", "/zones", creds, json=body)
        if result["status"] == "success":
            result["action"] = "create_zone"
        return result

    async def _delete_zone(self, config: CloudflareDeleteZoneConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("DELETE", f"/zones/{config.zone_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_zone"
        return result

    async def _edit_zone(self, config: CloudflareEditZoneConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = {}
        if config.paused is not None:
            body["paused"] = config.paused == "true"
        if config.vanity_name_servers:
            body["vanity_name_servers"] = [s.strip() for s in config.vanity_name_servers.split(",") if s.strip()]
        result = await self._request("PATCH", f"/zones/{config.zone_id}", creds, json=body)
        if result["status"] == "success":
            result["action"] = "edit_zone"
        return result

    async def _zone_activation_check(self, config: CloudflareZoneActivationCheckConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("PUT", f"/zones/{config.zone_id}/activation_check", creds)
        if result["status"] == "success":
            result["action"] = "zone_activation_check"
        return result

    # ── Rules Lists handlers ──────────────────────────────────────────────────────

    async def _list_rules_lists(self, config: CloudflareListRulesListsConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {}
        if config.per_page:
            params["per_page"] = config.per_page
        result = await self._request("GET", f"{await self._account_path(creds)}/rules/lists", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_rules_lists"
        return result

    async def _create_rules_list(self, config: CloudflareCreateRulesListConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = {"name": config.list_name, "kind": config.list_kind}
        if config.description:
            body["description"] = config.description
        result = await self._request("POST", f"{await self._account_path(creds)}/rules/lists", creds, json=body)
        if result["status"] == "success":
            result["action"] = "create_rules_list"
        return result

    async def _get_rules_list(self, config: CloudflareGetRulesListConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/rules/lists/{config.list_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_rules_list"
        return result

    async def _update_rules_list(self, config: CloudflareUpdateRulesListConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = {"description": config.description}
        result = await self._request("PUT", f"{await self._account_path(creds)}/rules/lists/{config.list_id}", creds, json=body)
        if result["status"] == "success":
            result["action"] = "update_rules_list"
        return result

    async def _delete_rules_list(self, config: CloudflareDeleteRulesListConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("DELETE", f"{await self._account_path(creds)}/rules/lists/{config.list_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_rules_list"
        return result

    async def _list_rules_list_items(self, config: CloudflareListRulesListItemsConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {}
        if config.cursor:
            params["cursor"] = config.cursor
        if config.per_page:
            params["per_page"] = config.per_page
        result = await self._request("GET", f"{await self._account_path(creds)}/rules/lists/{config.list_id}/items", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_rules_list_items"
        return result

    async def _create_rules_list_items(self, config: CloudflareCreateRulesListItemsConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        items = _json.loads(config.items_json)
        result = await self._request("POST", f"{await self._account_path(creds)}/rules/lists/{config.list_id}/items", creds, json=items)
        if result["status"] == "success":
            result["action"] = "create_rules_list_items"
        return result

    async def _replace_rules_list_items(self, config: CloudflareReplaceRulesListItemsConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        items = _json.loads(config.items_json)
        result = await self._request("PUT", f"{await self._account_path(creds)}/rules/lists/{config.list_id}/items", creds, json=items)
        if result["status"] == "success":
            result["action"] = "replace_rules_list_items"
        return result

    async def _delete_rules_list_items(self, config: CloudflareDeleteRulesListItemsConfig, creds: CloudflareCredential) -> Dict:
        ids = [{"id": i.strip()} for i in config.item_ids.split(",") if i.strip()]
        result = await self._request("DELETE", f"{await self._account_path(creds)}/rules/lists/{config.list_id}/items", creds, json={"items": ids})
        if result["status"] == "success":
            result["action"] = "delete_rules_list_items"
        return result

    async def _get_rules_list_operation(self, config: CloudflareGetRulesListOperationConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/rules/lists/bulk_operations/{config.operation_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_rules_list_operation"
        return result

    # ── Worker Versions & Deployments & Tails handlers ───────────────────────────

    async def _list_worker_versions(self, config: CloudflareListWorkerVersionsConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {}
        if config.per_page:
            params["per_page"] = config.per_page
        if config.deployable_only == "true":
            params["deployable_only"] = "true"
        result = await self._request("GET", f"{await self._account_path(creds)}/workers/scripts/{config.script_name}/versions", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_worker_versions"
        return result

    async def _upload_worker_version(self, config: CloudflareUploadWorkerVersionConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = {"<files>": config.script_content}
        if config.version_message:
            body["metadata"] = {"message": config.version_message}
        result = await self._request("POST", f"{await self._account_path(creds)}/workers/scripts/{config.script_name}/versions", creds, json={"script": config.script_content, "metadata": {"message": config.version_message or ""}})
        if result["status"] == "success":
            result["action"] = "upload_worker_version"
        return result

    async def _get_worker_version(self, config: CloudflareGetWorkerVersionConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/workers/scripts/{config.script_name}/versions/{config.version_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_worker_version"
        return result

    async def _list_worker_deployments(self, config: CloudflareListWorkerDeploymentsConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {}
        if config.per_page:
            params["per_page"] = config.per_page
        result = await self._request("GET", f"{await self._account_path(creds)}/workers/scripts/{config.script_name}/deployments", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_worker_deployments"
        return result

    async def _create_worker_deployment(self, config: CloudflareCreateWorkerDeploymentConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = {"strategy": config.strategy or "percentage", "versions": [{"version_id": config.version_id, "percentage": config.percentage or 100}]}
        result = await self._request("POST", f"{await self._account_path(creds)}/workers/scripts/{config.script_name}/deployments", creds, json=body)
        if result["status"] == "success":
            result["action"] = "create_worker_deployment"
        return result

    async def _get_worker_deployment(self, config: CloudflareGetWorkerDeploymentConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/workers/scripts/{config.script_name}/deployments/{config.deployment_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_worker_deployment"
        return result

    async def _list_worker_tails(self, config: CloudflareListWorkerTailsConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/workers/scripts/{config.script_name}/tails", creds)
        if result["status"] == "success":
            result["action"] = "list_worker_tails"
        return result

    async def _start_worker_tail(self, config: CloudflareStartWorkerTailConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("POST", f"{await self._account_path(creds)}/workers/scripts/{config.script_name}/tails", creds, json={})
        if result["status"] == "success":
            result["action"] = "start_worker_tail"
        return result

    async def _delete_worker_tail(self, config: CloudflareDeleteWorkerTailConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("DELETE", f"{await self._account_path(creds)}/workers/scripts/{config.script_name}/tails/{config.tail_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_worker_tail"
        return result

    # ── AI Gateway handlers ───────────────────────────────────────────────────────

    async def _list_ai_gateways(self, config: CloudflareListAIGatewaysConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {}
        if config.page:
            params["page"] = config.page
        if config.per_page:
            params["per_page"] = config.per_page
        if config.name_filter:
            params["name"] = config.name_filter
        result = await self._request("GET", f"{await self._account_path(creds)}/ai-gateway/gateways", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_ai_gateways"
        return result

    async def _create_ai_gateway(self, config: CloudflareCreateAIGatewayConfig, creds: CloudflareCredential) -> Dict:
        # Cloudflare's POST /ai-gateway/gateways requires a FLAT schema keyed on
        # `id` (the slug) with all of these fields present — cache_ttl and the
        # rate_limiting_* numbers are mandatory (it rejects a nested
        # rate_limiting object or missing numbers with "Expected number,
        # received nan"). Defaults: caching off (ttl 0) unless cache_enabled.
        body: Dict[str, Any] = {
            "id": config.slug,
            "collect_logs": config.collect_logs != "false",
            "cache_invalidate_on_update": False,
            "cache_ttl": 3600 if config.cache_enabled == "true" else 0,
            "rate_limiting_interval": config.rate_limiting_interval or 0,
            "rate_limiting_limit": config.rate_limiting_limit or 0,
            "rate_limiting_technique": "fixed",
        }
        result = await self._request("POST", f"{await self._account_path(creds)}/ai-gateway/gateways", creds, json=body)
        if result["status"] == "success":
            result["action"] = "create_ai_gateway"
        return result

    async def _get_ai_gateway(self, config: CloudflareGetAIGatewayConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/ai-gateway/gateways/{config.gateway_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_ai_gateway"
        return result

    async def _update_ai_gateway(self, config: CloudflareUpdateAIGatewayConfig, creds: CloudflareCredential) -> Dict:
        base = f"{await self._account_path(creds)}/ai-gateway/gateways/{config.gateway_id}"
        # Cloudflare's PUT is a full replace requiring the complete flat schema
        # (a partial or nested rate_limiting body is rejected), so fetch the
        # current gateway and overlay only the fields the user changed.
        current = await self._request("GET", base, creds)
        if current["status"] != "success":
            return current
        cur = current.get("result") or {}
        body: Dict[str, Any] = {
            "id": config.gateway_id,
            "cache_invalidate_on_update": cur.get("cache_invalidate_on_update", False),
            "cache_ttl": cur.get("cache_ttl", 0),
            "collect_logs": cur.get("collect_logs", True),
            "rate_limiting_interval": cur.get("rate_limiting_interval", 0),
            "rate_limiting_limit": cur.get("rate_limiting_limit", 0),
            "rate_limiting_technique": cur.get("rate_limiting_technique", "fixed"),
        }
        if config.collect_logs is not None:
            body["collect_logs"] = config.collect_logs != "false"
        if config.cache_enabled is not None:
            body["cache_ttl"] = 3600 if config.cache_enabled == "true" else 0
        if config.rate_limiting_limit is not None:
            body["rate_limiting_limit"] = config.rate_limiting_limit
        if config.rate_limiting_interval is not None:
            body["rate_limiting_interval"] = config.rate_limiting_interval
        result = await self._request("PUT", base, creds, json=body)
        if result["status"] == "success":
            result["action"] = "update_ai_gateway"
        return result

    async def _delete_ai_gateway(self, config: CloudflareDeleteAIGatewayConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("DELETE", f"{await self._account_path(creds)}/ai-gateway/gateways/{config.gateway_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_ai_gateway"
        return result

    async def _list_ai_gateway_logs(self, config: CloudflareListAIGatewayLogsConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {}
        if config.page:
            params["page"] = config.page
        if config.per_page:
            params["per_page"] = config.per_page
        if config.start_date:
            params["start_date"] = config.start_date
        if config.end_date:
            params["end_date"] = config.end_date
        if config.search:
            params["search"] = config.search
        if config.model:
            params["model"] = config.model
        if config.provider:
            params["provider"] = config.provider
        if config.success_only is not None:
            params["success"] = config.success_only == "true"
        result = await self._request("GET", f"{await self._account_path(creds)}/ai-gateway/gateways/{config.gateway_id}/logs", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_ai_gateway_logs"
        return result

    async def _get_ai_gateway_log(self, config: CloudflareGetAIGatewayLogConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/ai-gateway/gateways/{config.gateway_id}/logs/{config.log_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_ai_gateway_log"
        return result

    async def _delete_ai_gateway_logs(self, config: CloudflareDeleteAIGatewayLogsConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {}
        if config.start_date:
            params["start_date"] = config.start_date
        if config.end_date:
            params["end_date"] = config.end_date
        result = await self._request("DELETE", f"{await self._account_path(creds)}/ai-gateway/gateways/{config.gateway_id}/logs", creds, params=params)
        if result["status"] == "success":
            result["action"] = "delete_ai_gateway_logs"
        return result

    async def _get_ai_gateway_log_request(self, config: CloudflareGetAIGatewayLogRequestConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/ai-gateway/gateways/{config.gateway_id}/logs/{config.log_id}/request", creds)
        if result["status"] == "success":
            result["action"] = "get_ai_gateway_log_request"
        return result

    async def _get_ai_gateway_log_response(self, config: CloudflareGetAIGatewayLogResponseConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/ai-gateway/gateways/{config.gateway_id}/logs/{config.log_id}/response", creds)
        if result["status"] == "success":
            result["action"] = "get_ai_gateway_log_response"
        return result

    async def _list_ai_gateway_datasets(self, config: CloudflareListAIGatewayDatasetsConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {}
        if config.page:
            params["page"] = config.page
        if config.per_page:
            params["per_page"] = config.per_page
        result = await self._request("GET", f"{await self._account_path(creds)}/ai-gateway/gateways/{config.gateway_id}/datasets", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_ai_gateway_datasets"
        return result

    async def _create_ai_gateway_dataset(self, config: CloudflareCreateAIGatewayDatasetConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        body: Dict[str, Any] = {"name": config.dataset_name}
        if config.log_ids:
            body["log_ids"] = [i.strip() for i in config.log_ids.split(",") if i.strip()]
        if config.filters_json:
            body["filters"] = _json.loads(config.filters_json)
        result = await self._request("POST", f"{await self._account_path(creds)}/ai-gateway/gateways/{config.gateway_id}/datasets", creds, json=body)
        if result["status"] == "success":
            result["action"] = "create_ai_gateway_dataset"
        return result

    async def _delete_ai_gateway_dataset(self, config: CloudflareDeleteAIGatewayDatasetConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("DELETE", f"{await self._account_path(creds)}/ai-gateway/gateways/{config.gateway_id}/datasets/{config.dataset_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_ai_gateway_dataset"
        return result

    # ── Images extended handlers ──────────────────────────────────────────────────

    async def _list_image_variants(self, config: CloudflareListImageVariantsConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/images/v1/variants", creds)
        if result["status"] == "success":
            result["action"] = "list_image_variants"
        return result

    async def _create_image_variant(self, config: CloudflareCreateImageVariantConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = {"id": config.variant_id, "options": {"fit": config.fit, "metadata": config.metadata or "none", "never_require_signed_urls": config.never_require_signed_urls == "true"}}
        if config.width:
            body["options"]["width"] = config.width
        if config.height:
            body["options"]["height"] = config.height
        result = await self._request("POST", f"{await self._account_path(creds)}/images/v1/variants", creds, json=body)
        if result["status"] == "success":
            result["action"] = "create_image_variant"
        return result

    async def _get_image_variant(self, config: CloudflareGetImageVariantConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/images/v1/variants/{config.variant_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_image_variant"
        return result

    async def _update_image_variant(self, config: CloudflareUpdateImageVariantConfig, creds: CloudflareCredential) -> Dict:
        options: Dict[str, Any] = {}
        if config.fit:
            options["fit"] = config.fit
        if config.width:
            options["width"] = config.width
        if config.height:
            options["height"] = config.height
        if config.metadata:
            options["metadata"] = config.metadata
        result = await self._request("PATCH", f"{await self._account_path(creds)}/images/v1/variants/{config.variant_id}", creds, json={"options": options})
        if result["status"] == "success":
            result["action"] = "update_image_variant"
        return result

    async def _delete_image_variant(self, config: CloudflareDeleteImageVariantConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("DELETE", f"{await self._account_path(creds)}/images/v1/variants/{config.variant_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_image_variant"
        return result

    async def _list_image_signing_keys(self, config: CloudflareListImageSigningKeysConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/images/v1/keys", creds)
        if result["status"] == "success":
            result["action"] = "list_image_signing_keys"
        return result

    async def _create_image_signing_key(self, config: CloudflareCreateImageSigningKeyConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("PUT", f"{await self._account_path(creds)}/images/v1/keys/{config.key_name}", creds)
        if result["status"] == "success":
            result["action"] = "create_image_signing_key"
        return result

    async def _delete_image_signing_key(self, config: CloudflareDeleteImageSigningKeyConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("DELETE", f"{await self._account_path(creds)}/images/v1/keys/{config.key_name}", creds)
        if result["status"] == "success":
            result["action"] = "delete_image_signing_key"
        return result

    async def _update_image_metadata(self, config: CloudflareUpdateImageMetadataConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        body: Dict[str, Any] = {}
        if config.metadata_json:
            body["metadata"] = _json.loads(config.metadata_json)
        if config.require_signed_urls is not None:
            body["requireSignedURLs"] = config.require_signed_urls == "true"
        result = await self._request("PATCH", f"{await self._account_path(creds)}/images/v1/{config.image_id}", creds, json=body)
        if result["status"] == "success":
            result["action"] = "update_image_metadata"
        return result

    # ── D1 extended handlers ──────────────────────────────────────────────────────

    async def _list_d1_tables(self, config: CloudflareListD1TablesConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("POST", f"{await self._account_path(creds)}/d1/database/{config.database_id}/query", creds, json={"sql": "SELECT name FROM sqlite_master WHERE type='table'"})
        if result["status"] == "success":
            result["action"] = "list_d1_tables"
        return result

    async def _import_d1_data(self, config: CloudflareImportD1DataConfig, creds: CloudflareCredential) -> Dict:
        # Cloudflare D1 import uses multipart/form-data with the SQL file
        # We approximate via the query endpoint for compatibility
        result = await self._request("POST", f"{await self._account_path(creds)}/d1/database/{config.database_id}/import", creds, json={"sql": config.sql_content, "init": config.init_import == "true"})
        if result["status"] == "success":
            result["action"] = "import_d1_data"
        return result

    async def _get_d1_import_status(self, config: CloudflareGetD1ImportStatusConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/d1/database/{config.database_id}/import", creds)
        if result["status"] == "success":
            result["action"] = "get_d1_database_import_status"
        return result

    async def _execute_d1_raw_query(self, config: CloudflareExecuteD1RawQueryConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        body: Dict[str, Any] = {"sql": config.sql}
        if config.params_json:
            body["params"] = _json.loads(config.params_json)
        result = await self._request("POST", f"{await self._account_path(creds)}/d1/database/{config.database_id}/raw", creds, json=body)
        if result["status"] == "success":
            result["action"] = "execute_d1_raw_query"
        return result

    # ── Zero Trust Gateway handlers ───────────────────────────────────────────────

    async def _get_gateway_configuration(self, config: CloudflareGetGatewayConfigurationConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/gateway/configuration", creds)
        if result["status"] == "success":
            result["action"] = "get_gateway_configuration"
        return result

    async def _update_gateway_configuration(self, config: CloudflareUpdateGatewayConfigurationConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        body = _json.loads(config.settings_json)
        result = await self._request("PUT", f"{await self._account_path(creds)}/gateway/configuration", creds, json=body)
        if result["status"] == "success":
            result["action"] = "update_gateway_configuration"
        return result

    async def _list_gateway_rules(self, config: CloudflareListGatewayRulesConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {}
        if config.action_filter:
            params["action"] = config.action_filter
        if config.per_page:
            params["per_page"] = config.per_page
        if config.page:
            params["page"] = config.page
        result = await self._request("GET", f"{await self._account_path(creds)}/gateway/rules", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_gateway_rules"
        return result

    async def _create_gateway_rule(self, config: CloudflareCreateGatewayRuleConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = {"name": config.rule_name, "action": config.action, "enabled": config.enabled != "false"}
        if config.traffic:
            body["traffic"] = config.traffic
        if config.identity:
            body["identity"] = config.identity
        if config.description:
            body["description"] = config.description
        result = await self._request("POST", f"{await self._account_path(creds)}/gateway/rules", creds, json=body)
        if result["status"] == "success":
            result["action"] = "create_gateway_rule"
        return result

    async def _get_gateway_rule(self, config: CloudflareGetGatewayRuleConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/gateway/rules/{config.rule_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_gateway_rule"
        return result

    async def _update_gateway_rule(self, config: CloudflareUpdateGatewayRuleConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = {}
        if config.rule_name is not None:
            body["name"] = config.rule_name
        if config.action is not None:
            body["action"] = config.action
        if config.enabled is not None:
            body["enabled"] = config.enabled != "false"
        if config.traffic is not None:
            body["traffic"] = config.traffic
        if config.identity is not None:
            body["identity"] = config.identity
        if config.description is not None:
            body["description"] = config.description
        result = await self._request("PUT", f"{await self._account_path(creds)}/gateway/rules/{config.rule_id}", creds, json=body)
        if result["status"] == "success":
            result["action"] = "update_gateway_rule"
        return result

    async def _delete_gateway_rule(self, config: CloudflareDeleteGatewayRuleConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("DELETE", f"{await self._account_path(creds)}/gateway/rules/{config.rule_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_gateway_rule"
        return result

    async def _list_gateway_lists(self, config: CloudflareListGatewayListsConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {}
        if config.list_type_filter:
            params["type"] = config.list_type_filter
        result = await self._request("GET", f"{await self._account_path(creds)}/gateway/lists", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_gateway_lists"
        return result

    async def _create_gateway_list(self, config: CloudflareCreateGatewayListConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        body: Dict[str, Any] = {"name": config.list_name, "type": config.list_type}
        if config.description:
            body["description"] = config.description
        if config.items_json:
            body["items"] = _json.loads(config.items_json)
        result = await self._request("POST", f"{await self._account_path(creds)}/gateway/lists", creds, json=body)
        if result["status"] == "success":
            result["action"] = "create_gateway_list"
        return result

    async def _get_gateway_list(self, config: CloudflareGetGatewayListConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/gateway/lists/{config.list_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_gateway_list"
        return result

    async def _update_gateway_list(self, config: CloudflareUpdateGatewayListConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        body: Dict[str, Any] = {}
        if config.append_items_json:
            body["append"] = _json.loads(config.append_items_json)
        if config.remove_values:
            body["remove"] = [{"value": v.strip()} for v in config.remove_values.split(",") if v.strip()]
        result = await self._request("PATCH", f"{await self._account_path(creds)}/gateway/lists/{config.list_id}", creds, json=body)
        if result["status"] == "success":
            result["action"] = "update_gateway_list"
        return result

    async def _delete_gateway_list(self, config: CloudflareDeleteGatewayListConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("DELETE", f"{await self._account_path(creds)}/gateway/lists/{config.list_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_gateway_list"
        return result

    async def _list_gateway_list_items(self, config: CloudflareListGatewayListItemsConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {}
        if config.per_page:
            params["per_page"] = config.per_page
        if config.page:
            params["page"] = config.page
        result = await self._request("GET", f"{await self._account_path(creds)}/gateway/lists/{config.list_id}/items", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_gateway_list_items"
        return result

    async def _list_gateway_locations(self, config: CloudflareListGatewayLocationsConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/gateway/locations", creds)
        if result["status"] == "success":
            result["action"] = "list_gateway_locations"
        return result

    async def _create_gateway_location(self, config: CloudflareCreateGatewayLocationConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = {"name": config.location_name, "client_default": config.client_default == "true", "ecs_support": config.ecs_support == "true"}
        result = await self._request("POST", f"{await self._account_path(creds)}/gateway/locations", creds, json=body)
        if result["status"] == "success":
            result["action"] = "create_gateway_location"
        return result

    async def _get_gateway_location(self, config: CloudflareGetGatewayLocationConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/gateway/locations/{config.location_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_gateway_location"
        return result

    async def _delete_gateway_location(self, config: CloudflareDeleteGatewayLocationConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("DELETE", f"{await self._account_path(creds)}/gateway/locations/{config.location_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_gateway_location"
        return result

    # ── Page Shield handlers ──────────────────────────────────────────────────────

    async def _get_page_shield_settings(self, config: CloudflareGetPageShieldSettingsConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"/zones/{config.zone_id}/page_shield", creds)
        if result["status"] == "success":
            result["action"] = "get_page_shield_settings"
        return result

    async def _update_page_shield_settings(self, config: CloudflareUpdatePageShieldSettingsConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = {}
        if config.enabled is not None:
            body["enabled"] = config.enabled != "false"
        if config.use_cf_endpoint is not None:
            body["use_cloudflare_reporting_endpoint"] = config.use_cf_endpoint != "false"
        result = await self._request("PUT", f"/zones/{config.zone_id}/page_shield", creds, json=body)
        if result["status"] == "success":
            result["action"] = "update_page_shield_settings"
        return result

    async def _list_page_shield_scripts(self, config: CloudflareListPageShieldScriptsConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {"page": config.page or 1, "per_page": config.per_page or 15}
        if config.status:
            params["status"] = config.status
        result = await self._request("GET", f"/zones/{config.zone_id}/page_shield/scripts", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_page_shield_scripts"
        return result

    async def _get_page_shield_script(self, config: CloudflareGetPageShieldScriptConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"/zones/{config.zone_id}/page_shield/scripts/{config.script_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_page_shield_script"
        return result

    async def _list_page_shield_connections(self, config: CloudflareListPageShieldConnectionsConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {"page": config.page or 1, "per_page": config.per_page or 15}
        result = await self._request("GET", f"/zones/{config.zone_id}/page_shield/connections", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_page_shield_connections"
        return result

    async def _get_page_shield_connection(self, config: CloudflareGetPageShieldConnectionConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"/zones/{config.zone_id}/page_shield/connections/{config.connection_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_page_shield_connection"
        return result

    async def _list_page_shield_policies(self, config: CloudflareListPageShieldPoliciesConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"/zones/{config.zone_id}/page_shield/policies", creds)
        if result["status"] == "success":
            result["action"] = "list_page_shield_policies"
        return result

    async def _create_page_shield_policy(self, config: CloudflareCreatePageShieldPolicyConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = {"action": config.action, "expression": config.expression, "value": config.value, "enabled": config.enabled != "false"}
        if config.description:
            body["description"] = config.description
        result = await self._request("POST", f"/zones/{config.zone_id}/page_shield/policies", creds, json=body)
        if result["status"] == "success":
            result["action"] = "create_page_shield_policy"
        return result

    async def _delete_page_shield_policy(self, config: CloudflareDeletePageShieldPolicyConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("DELETE", f"/zones/{config.zone_id}/page_shield/policies/{config.policy_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_page_shield_policy"
        return result

    # ── Cache extended handlers ───────────────────────────────────────────────────

    async def _get_cache_reserve(self, config: CloudflareGetCacheReserveConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"/zones/{config.zone_id}/cache/cache_reserve", creds)
        if result["status"] == "success":
            result["action"] = "get_cache_reserve"
        return result

    async def _update_cache_reserve(self, config: CloudflareUpdateCacheReserveConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("PATCH", f"/zones/{config.zone_id}/cache/cache_reserve", creds, json={"value": config.cache_reserve_enabled})
        if result["status"] == "success":
            result["action"] = "update_cache_reserve"
        return result

    async def _get_argo_smart_routing(self, config: CloudflareGetArgoSmartRoutingConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"/zones/{config.zone_id}/argo/smart_routing", creds)
        if result["status"] == "success":
            result["action"] = "get_argo_smart_routing"
        return result

    async def _update_argo_smart_routing(self, config: CloudflareUpdateArgoSmartRoutingConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("PATCH", f"/zones/{config.zone_id}/argo/smart_routing", creds, json={"value": config.smart_routing_enabled})
        if result["status"] == "success":
            result["action"] = "update_argo_smart_routing"
        return result

    async def _get_tiered_caching(self, config: CloudflareGetTieredCachingConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"/zones/{config.zone_id}/argo/tiered_caching", creds)
        if result["status"] == "success":
            result["action"] = "get_tiered_caching"
        return result

    async def _update_tiered_caching(self, config: CloudflareUpdateTieredCachingConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("PATCH", f"/zones/{config.zone_id}/argo/tiered_caching", creds, json={"value": config.tiered_caching_enabled})
        if result["status"] == "success":
            result["action"] = "update_tiered_caching"
        return result

    async def _purge_cache_everything(self, config: CloudflarePurgeCacheEverythingConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("POST", f"/zones/{config.zone_id}/purge_cache", creds, json={"purge_everything": True})
        if result["status"] == "success":
            result["action"] = "purge_cache_everything"
        return result

    async def _get_zone_settings_all(self, config: CloudflareGetZoneSettingsAllConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"/zones/{config.zone_id}/settings", creds)
        if result["status"] == "success":
            result["action"] = "get_zone_settings_all"
        return result

    # ── R2 extended handlers ──────────────────────────────────────────────────────

    async def _get_r2_cors_policy(self, config: CloudflareGetR2CORSPolicyConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/r2/buckets/{config.bucket_name}/cors", creds)
        if result["status"] == "success":
            result["action"] = "get_r2_cors_policy"
        return result

    async def _put_r2_cors_policy(self, config: CloudflarePutR2CORSPolicyConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        rules = _json.loads(config.cors_rules_json)
        result = await self._request("PUT", f"{await self._account_path(creds)}/r2/buckets/{config.bucket_name}/cors", creds, json={"rules": rules})
        if result["status"] == "success":
            result["action"] = "put_r2_cors_policy"
        return result

    async def _delete_r2_cors_policy(self, config: CloudflareDeleteR2CORSPolicyConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("DELETE", f"{await self._account_path(creds)}/r2/buckets/{config.bucket_name}/cors", creds)
        if result["status"] == "success":
            result["action"] = "delete_r2_cors_policy"
        return result

    async def _get_r2_lifecycle_rules(self, config: CloudflareGetR2LifecycleRulesConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/r2/buckets/{config.bucket_name}/lifecycle", creds)
        if result["status"] == "success":
            result["action"] = "get_r2_lifecycle_rules"
        return result

    async def _put_r2_lifecycle_rules(self, config: CloudflarePutR2LifecycleRulesConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        rules = _json.loads(config.lifecycle_rules_json)
        result = await self._request("PUT", f"{await self._account_path(creds)}/r2/buckets/{config.bucket_name}/lifecycle", creds, json={"rules": rules})
        if result["status"] == "success":
            result["action"] = "put_r2_lifecycle_rules"
        return result

    async def _delete_r2_lifecycle_rules(self, config: CloudflareDeleteR2LifecycleRulesConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("DELETE", f"{await self._account_path(creds)}/r2/buckets/{config.bucket_name}/lifecycle", creds)
        if result["status"] == "success":
            result["action"] = "delete_r2_lifecycle_rules"
        return result

    async def _list_r2_custom_domains(self, config: CloudflareListR2CustomDomainsConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/r2/buckets/{config.bucket_name}/domains/custom", creds)
        if result["status"] == "success":
            result["action"] = "list_r2_custom_domains"
        return result

    async def _create_r2_custom_domain(self, config: CloudflareCreateR2CustomDomainConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = {"domain": config.custom_domain, "enabled": config.enabled != "false"}
        if config.zone_id:
            body["zoneId"] = config.zone_id
        result = await self._request("POST", f"{await self._account_path(creds)}/r2/buckets/{config.bucket_name}/domains/custom", creds, json=body)
        if result["status"] == "success":
            result["action"] = "create_r2_custom_domain"
        return result

    async def _update_r2_custom_domain(self, config: CloudflareUpdateR2CustomDomainConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = {}
        if config.enabled is not None:
            body["enabled"] = config.enabled != "false"
        if config.min_tls:
            body["minTLS"] = config.min_tls
        result = await self._request("PUT", f"{await self._account_path(creds)}/r2/buckets/{config.bucket_name}/domains/custom/{config.custom_domain}", creds, json=body)
        if result["status"] == "success":
            result["action"] = "update_r2_custom_domain"
        return result

    async def _delete_r2_custom_domain(self, config: CloudflareDeleteR2CustomDomainConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("DELETE", f"{await self._account_path(creds)}/r2/buckets/{config.bucket_name}/domains/custom/{config.custom_domain}", creds)
        if result["status"] == "success":
            result["action"] = "delete_r2_custom_domain"
        return result

    async def _get_r2_managed_domain(self, config: CloudflareGetR2ManagedDomainConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/r2/buckets/{config.bucket_name}/domains/managed", creds)
        if result["status"] == "success":
            result["action"] = "get_r2_managed_domain"
        return result

    async def _update_r2_managed_domain(self, config: CloudflareUpdateR2ManagedDomainConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("PUT", f"{await self._account_path(creds)}/r2/buckets/{config.bucket_name}/domains/managed", creds, json={"enabled": config.public_access_enabled == "true"})
        if result["status"] == "success":
            result["action"] = "update_r2_managed_domain"
        return result

    async def _get_r2_bucket_details(self, config: CloudflareGetR2BucketDetailsConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/r2/buckets/{config.bucket_name}", creds)
        if result["status"] == "success":
            result["action"] = "get_r2_bucket_details"
        return result

    async def _update_r2_bucket(self, config: CloudflareUpdateR2BucketConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = {}
        if config.storage_class:
            body["storageClass"] = config.storage_class
        result = await self._request("PATCH", f"{await self._account_path(creds)}/r2/buckets/{config.bucket_name}", creds, json=body)
        if result["status"] == "success":
            result["action"] = "update_r2_bucket"
        return result

    # ── Poll Trigger handlers ─────────────────────────────────────────────────────

    async def _trigger_queue_message(self, _config=None, _creds=None) -> Dict[str, Any]:
        """Poll a Cloudflare Queue for new messages."""
        node_config = self.config
        if node_config is None or not isinstance(node_config, CloudflareNodeConfig):
            return {"status": "success", "result": [], "action": "cloudflare_queue_message"}
        config = node_config.config
        creds = node_config.credentials
        if not isinstance(config, CloudflareQueueMessageTriggerConfig):
            return {"status": "success", "result": [], "action": "cloudflare_queue_message"}
        credentials = self._load_credentials(creds)
        if credentials is None:
            return {"status": "success", "result": [], "action": "cloudflare_queue_message"}
        body: Dict[str, Any] = {"batch_size": config.batch_size or 10, "visibility_timeout_ms": config.visibility_timeout_ms or 30000}
        result = await self._request("POST", f"{await self._account_path(credentials)}/queues/{config.queue_id}/messages/pull", credentials, json=body)
        if result.get("status") != "success":
            return {"status": "success", "result": [], "action": "cloudflare_queue_message"}
        messages = result.get("result", {}).get("messages") or []
        if not isinstance(messages, list):
            return {"status": "success", "result": [], "action": "cloudflare_queue_message"}
        items = await self._filter_unseen(messages, lambda x: x.get("id"))
        return {"status": "success", "result": items, "action": "cloudflare_queue_message"}

    async def _trigger_pages_deploy(self, _config=None, _creds=None) -> Dict[str, Any]:
        """Poll Cloudflare Pages for new deployments."""
        node_config = self.config
        if node_config is None or not isinstance(node_config, CloudflareNodeConfig):
            return {"status": "success", "result": [], "action": "cloudflare_pages_deploy"}
        config = node_config.config
        creds = node_config.credentials
        if not isinstance(config, CloudflarePagesDeployTriggerConfig):
            return {"status": "success", "result": [], "action": "cloudflare_pages_deploy"}
        credentials = self._load_credentials(creds)
        if credentials is None:
            return {"status": "success", "result": [], "action": "cloudflare_pages_deploy"}
        params: Dict[str, Any] = {"per_page": 25}
        if config.environment_filter:
            params["env"] = config.environment_filter
        result = await self._request("GET", f"{await self._account_path(credentials)}/pages/projects/{config.project_name}/deployments", credentials, params=params)
        if result.get("status") != "success":
            return {"status": "success", "result": [], "action": "cloudflare_pages_deploy"}
        deployments = result.get("result") or []
        if not isinstance(deployments, list):
            return {"status": "success", "result": [], "action": "cloudflare_pages_deploy"}
        items = await self._filter_unseen(deployments, lambda x: x.get("id"))
        return {"status": "success", "result": items, "action": "cloudflare_pages_deploy"}

    async def _trigger_r2_new_object(self, _config=None, _creds=None) -> Dict[str, Any]:
        """Poll R2 bucket for new objects using S3-compatible API."""
        node_config = self.config
        if node_config is None or not isinstance(node_config, CloudflareNodeConfig):
            return {"status": "success", "result": [], "action": "cloudflare_r2_new_object"}
        config = node_config.config
        if not isinstance(config, CloudflareR2NewObjectTriggerConfig):
            return {"status": "success", "result": [], "action": "cloudflare_r2_new_object"}
        try:
            import boto3
            from botocore.config import Config as BotoConfig
        except ImportError:
            logger.error("[CloudflareNode] boto3 not available for R2 trigger polling")
            return {"status": "success", "result": [], "action": "cloudflare_r2_new_object"}
        try:
            client = boto3.client(
                "s3",
                endpoint_url=_r2_endpoint_url(config.account_id),
                aws_access_key_id=config.r2_access_key_id,
                aws_secret_access_key=config.r2_secret_access_key,
                config=BotoConfig(signature_version="s3v4"),
            )
            kwargs: Dict[str, Any] = {"Bucket": config.bucket_name, "MaxKeys": 100}
            if config.key_prefix:
                kwargs["Prefix"] = config.key_prefix
            response = client.list_objects_v2(**kwargs)
            objects = response.get("Contents") or []
        except Exception as exc:
            logger.warning("[CloudflareNode] R2 poll trigger failed: %s", exc)
            return {"status": "success", "result": [], "action": "cloudflare_r2_new_object"}
        raw = [{"key": o["Key"], "size": o.get("Size"), "last_modified": o.get("LastModified", "").isoformat() if o.get("LastModified") else None, "etag": o.get("ETag", "").strip('"')} for o in objects]
        items = await self._filter_unseen(raw, lambda item: item["key"])
        return {"status": "success", "result": items, "action": "cloudflare_r2_new_object"}

    async def _trigger_dns_change(self, _config=None, _creds=None) -> Dict[str, Any]:
        """Poll DNS records for changes (additions/modifications)."""
        node_config = self.config
        if node_config is None or not isinstance(node_config, CloudflareNodeConfig):
            return {"status": "success", "result": [], "action": "cloudflare_dns_change"}
        config = node_config.config
        creds = node_config.credentials
        if not isinstance(config, CloudflareDNSChangeTriggerConfig):
            return {"status": "success", "result": [], "action": "cloudflare_dns_change"}
        credentials = self._load_credentials(creds)
        if credentials is None:
            return {"status": "success", "result": [], "action": "cloudflare_dns_change"}
        params: Dict[str, Any] = {"per_page": 100}
        if config.record_type_filter:
            params["type"] = config.record_type_filter
        result = await self._request("GET", f"/zones/{config.zone_id}/dns_records", credentials, params=params)
        if result.get("status") != "success":
            return {"status": "success", "result": [], "action": "cloudflare_dns_change"}
        records = result.get("result") or []
        if not isinstance(records, list):
            return {"status": "success", "result": [], "action": "cloudflare_dns_change"}
        items = await self._filter_unseen(records, lambda r: f"{r.get('id')}:{r.get('modified_on', '')}")
        return {"status": "success", "result": items, "action": "cloudflare_dns_change"}

    async def _trigger_health_check_status(self, _config=None, _creds=None) -> Dict[str, Any]:
        """Poll health checks for status changes."""
        node_config = self.config
        if node_config is None or not isinstance(node_config, CloudflareNodeConfig):
            return {"status": "success", "result": [], "action": "cloudflare_health_check_status"}
        config = node_config.config
        creds = node_config.credentials
        if not isinstance(config, CloudflareHealthCheckStatusTriggerConfig):
            return {"status": "success", "result": [], "action": "cloudflare_health_check_status"}
        credentials = self._load_credentials(creds)
        if credentials is None:
            return {"status": "success", "result": [], "action": "cloudflare_health_check_status"}
        if config.healthcheck_id:
            result = await self._request("GET", f"/zones/{config.zone_id}/healthchecks/{config.healthcheck_id}", credentials)
            checks = [result.get("result", {})] if result.get("status") == "success" else []
        else:
            result = await self._request("GET", f"/zones/{config.zone_id}/healthchecks", credentials)
            checks = result.get("result") or [] if result.get("status") == "success" else []
        if not isinstance(checks, list):
            return {"status": "success", "result": [], "action": "cloudflare_health_check_status"}
        items = await self._filter_unseen(checks, lambda hc: f"{hc.get('id')}:{hc.get('status', '')}")
        return {"status": "success", "result": items, "action": "cloudflare_health_check_status"}

    # ── Access handlers ───────────────────────────────────────────────────────────

    async def _list_identity_providers(self, config: CloudflareListIdentityProvidersConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/access/identity_providers", creds)
        if result["status"] == "success":
            result["action"] = "list_identity_providers"
        return result

    async def _get_identity_provider(self, config: CloudflareGetIdentityProviderConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/access/identity_providers/{config.idp_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_identity_provider"
        return result

    async def _create_identity_provider(self, config: CloudflareCreateIdentityProviderConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        body: Dict[str, Any] = {"name": config.idp_name, "type": config.idp_type, "config": _json.loads(config.idp_config_json)}
        result = await self._request("POST", f"{await self._account_path(creds)}/access/identity_providers", creds, json=body)
        if result["status"] == "success":
            result["action"] = "create_identity_provider"
        return result

    async def _update_identity_provider(self, config: CloudflareUpdateIdentityProviderConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        body: Dict[str, Any] = {}
        if config.idp_name is not None:
            body["name"] = config.idp_name
        if config.idp_type is not None:
            body["type"] = config.idp_type
        if config.idp_config_json:
            body["config"] = _json.loads(config.idp_config_json)
        result = await self._request("PUT", f"{await self._account_path(creds)}/access/identity_providers/{config.idp_id}", creds, json=body)
        if result["status"] == "success":
            result["action"] = "update_identity_provider"
        return result

    async def _delete_identity_provider(self, config: CloudflareDeleteIdentityProviderConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("DELETE", f"{await self._account_path(creds)}/access/identity_providers/{config.idp_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_identity_provider"
        return result

    async def _list_access_users(self, config: CloudflareListAccessUsersConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {}
        if config.email_filter:
            params["email"] = config.email_filter
        if config.per_page:
            params["per_page"] = config.per_page
        result = await self._request("GET", f"{await self._account_path(creds)}/access/users", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_access_users"
        return result

    async def _get_access_user(self, config: CloudflareGetAccessUserConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/access/users/{config.user_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_access_user"
        return result

    async def _list_access_user_sessions(self, config: CloudflareListAccessUserSessionsConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/access/users/{config.user_id}/active_sessions", creds)
        if result["status"] == "success":
            result["action"] = "list_access_user_sessions"
        return result

    async def _revoke_access_user_session(self, config: CloudflareRevokeAccessUserSessionConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("POST", f"{await self._account_path(creds)}/access/organizations/revoke_user", creds, json={"email": config.email})
        if result["status"] == "success":
            result["action"] = "revoke_access_user_session"
        return result

    async def _get_access_organization(self, config: CloudflareGetAccessOrganizationConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/access/organizations", creds)
        if result["status"] == "success":
            result["action"] = "get_access_organization"
        return result

    async def _update_access_organization(self, config: CloudflareUpdateAccessOrganizationConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = {}
        if config.org_name is not None:
            body["name"] = config.org_name
        if config.session_duration is not None:
            body["session_duration"] = config.session_duration
        if config.is_ui_read_only is not None:
            body["is_ui_read_only"] = config.is_ui_read_only == "true"
        result = await self._request("PUT", f"{await self._account_path(creds)}/access/organizations", creds, json=body)
        if result["status"] == "success":
            result["action"] = "update_access_organization"
        return result

    async def _create_access_key_rotation(self, config: CloudflareCreateAccessKeyRotationConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("POST", f"{await self._account_path(creds)}/access/keys/rotate", creds, json={})
        if result["status"] == "success":
            result["action"] = "create_access_key_rotation"
        return result

    # ── Secondary DNS handlers ────────────────────────────────────────────────────

    async def _get_secondary_dns_config(self, config: CloudflareGetSecondaryDNSConfigConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"/zones/{config.zone_id}/secondary_dns/incoming", creds)
        if result["status"] == "success":
            result["action"] = "get_secondary_dns_config"
        return result

    async def _update_secondary_dns_config(self, config: CloudflareUpdateSecondaryDNSConfigConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        body = _json.loads(config.config_json)
        result = await self._request("PUT", f"/zones/{config.zone_id}/secondary_dns/incoming", creds, json=body)
        if result["status"] == "success":
            result["action"] = "update_secondary_dns_config"
        return result

    async def _list_secondary_dns_peers(self, config: CloudflareListSecondaryDNSPeersConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/secondary_dns/peers", creds)
        if result["status"] == "success":
            result["action"] = "list_secondary_dns_peers"
        return result

    async def _create_secondary_dns_peer(self, config: CloudflareCreateSecondaryDNSPeerConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = {"name": config.peer_name, "ip": config.peer_ip, "port": config.port or 53, "ixfr_enable": config.ixfr_enabled == "true"}
        result = await self._request("POST", f"{await self._account_path(creds)}/secondary_dns/peers", creds, json=body)
        if result["status"] == "success":
            result["action"] = "create_secondary_dns_peer"
        return result

    async def _get_secondary_dns_peer(self, config: CloudflareGetSecondaryDNSPeerConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/secondary_dns/peers/{config.peer_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_secondary_dns_peer"
        return result

    async def _update_secondary_dns_peer(self, config: CloudflareUpdateSecondaryDNSPeerConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = {}
        if config.peer_name is not None:
            body["name"] = config.peer_name
        if config.peer_ip is not None:
            body["ip"] = config.peer_ip
        if config.port is not None:
            body["port"] = config.port
        if config.ixfr_enabled is not None:
            body["ixfr_enable"] = config.ixfr_enabled == "true"
        result = await self._request("PUT", f"{await self._account_path(creds)}/secondary_dns/peers/{config.peer_id}", creds, json=body)
        if result["status"] == "success":
            result["action"] = "update_secondary_dns_peer"
        return result

    async def _delete_secondary_dns_peer(self, config: CloudflareDeleteSecondaryDNSPeerConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("DELETE", f"{await self._account_path(creds)}/secondary_dns/peers/{config.peer_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_secondary_dns_peer"
        return result

    # ── Analytics Engine handlers ─────────────────────────────────────────────────

    async def _query_analytics_engine(self, config: CloudflareQueryAnalyticsEngineConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {"query": config.sql_query}
        result = await self._request("GET", f"{await self._account_path(creds)}/analytics_engine/sql", creds, params=params)
        if result["status"] == "success":
            result["action"] = "query_analytics_engine"
        return result

    # ── Regional Tiered Cache handlers ────────────────────────────────────────────

    async def _get_regional_tiered_cache(self, config: CloudflareGetRegionalTieredCacheConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"/zones/{config.zone_id}/cache/regional_tiered_cache", creds)
        if result["status"] == "success":
            result["action"] = "get_regional_tiered_cache"
        return result

    async def _update_regional_tiered_cache(self, config: CloudflareUpdateRegionalTieredCacheConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("PATCH", f"/zones/{config.zone_id}/cache/regional_tiered_cache", creds, json={"value": config.enabled})
        if result["status"] == "success":
            result["action"] = "update_regional_tiered_cache"
        return result

    # ── Vectorize extended handlers ───────────────────────────────────────────────

    async def _get_vectorize_index_info(self, config: CloudflareGetVectorizeIndexInfoConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/vectorize/v2/indexes/{config.index_name}/info", creds)
        if result["status"] == "success":
            result["action"] = "get_vectorize_index_info"
        return result

    async def _list_vectorize_metadata_indexes(self, config: CloudflareListVectorizeMetadataIndexesConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"{await self._account_path(creds)}/vectorize/v2/indexes/{config.index_name}/metadata_index/list", creds)
        if result["status"] == "success":
            result["action"] = "list_vectorize_metadata_indexes"
        return result

    async def _create_vectorize_metadata_index(self, config: CloudflareCreateVectorizeMetadataIndexConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = {"propertyName": config.property_name, "indexType": config.index_type}
        result = await self._request("POST", f"{await self._account_path(creds)}/vectorize/v2/indexes/{config.index_name}/metadata_index/create", creds, json=body)
        if result["status"] == "success":
            result["action"] = "create_vectorize_metadata_index"
        return result

    async def _delete_vectorize_metadata_index(self, config: CloudflareDeleteVectorizeMetadataIndexConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = {"propertyName": config.property_name}
        result = await self._request("POST", f"{await self._account_path(creds)}/vectorize/v2/indexes/{config.index_name}/metadata_index/delete", creds, json=body)
        if result["status"] == "success":
            result["action"] = "delete_vectorize_metadata_index"
        return result

    async def _get_vectorize_vectors_by_ids(self, config: CloudflareGetVectorizeVectorsByIdsConfig, creds: CloudflareCredential) -> Dict:
        ids = [i.strip() for i in config.vector_ids.split(",") if i.strip()]
        result = await self._request("POST", f"{await self._account_path(creds)}/vectorize/v2/indexes/{config.index_name}/get_by_ids", creds, json={"ids": ids})
        if result["status"] == "success":
            result["action"] = "get_vectorize_vectors_by_ids"
        return result

    # ── Fonts handlers ────────────────────────────────────────────────────────────

    async def _get_fonts_settings(self, config: CloudflareGetFontsSettingsConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"/zones/{config.zone_id}/settings/fonts", creds)
        if result["status"] == "success":
            result["action"] = "get_fonts_settings"
        return result

    async def _update_fonts_settings(self, config: CloudflareUpdateFontsSettingsConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("PATCH", f"/zones/{config.zone_id}/settings/fonts", creds, json={"value": config.fonts_enabled})
        if result["status"] == "success":
            result["action"] = "update_fonts_settings"
        return result

    # ── NEL handlers ──────────────────────────────────────────────────────────────

    async def _get_nel_settings(self, config: CloudflareGetNELSettingsConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"/zones/{config.zone_id}/settings/nel", creds)
        if result["status"] == "success":
            result["action"] = "get_nel_settings"
        return result

    async def _update_nel_settings(self, config: CloudflareUpdateNELSettingsConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = {}
        if config.nel_enabled is not None:
            body["value"] = {"enabled": config.nel_enabled != "false"}
        result = await self._request("PATCH", f"/zones/{config.zone_id}/settings/nel", creds, json=body)
        if result["status"] == "success":
            result["action"] = "update_nel_settings"
        return result

    # ── API Shield handlers ───────────────────────────────────────────────────────

    async def _get_api_shield_settings(self, config: CloudflareGetAPIShieldSettingsConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"/zones/{config.zone_id}/api_gateway/configuration", creds)
        if result["status"] == "success":
            result["action"] = "get_api_shield_settings"
        return result

    async def _update_api_shield_settings(self, config: CloudflareUpdateAPIShieldSettingsConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = {}
        if config.auth_header_name:
            body["auth_id_characteristics"] = [{"name": config.auth_header_name, "type": config.auth_header_type or "header"}]
        result = await self._request("PUT", f"/zones/{config.zone_id}/api_gateway/configuration", creds, json=body)
        if result["status"] == "success":
            result["action"] = "update_api_shield_settings"
        return result

    async def _list_api_shield_endpoints(self, config: CloudflareListAPIShieldEndpointsConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {"per_page": config.per_page or 25}
        if config.host_filter:
            params["host"] = config.host_filter
        result = await self._request("GET", f"/zones/{config.zone_id}/api_gateway/operations", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_api_shield_endpoints"
        return result

    async def _create_api_shield_endpoint(self, config: CloudflareCreateAPIShieldEndpointConfig, creds: CloudflareCredential) -> Dict:
        body: Dict[str, Any] = [{"method": config.method, "host": config.host, "endpoint": config.endpoint}]
        result = await self._request("POST", f"/zones/{config.zone_id}/api_gateway/operations", creds, json=body)
        if result["status"] == "success":
            result["action"] = "create_api_shield_endpoint"
        return result

    # ── WAF extended handlers ─────────────────────────────────────────────────────

    async def _get_waf_package(self, config: CloudflareGetWAFPackageConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"/zones/{config.zone_id}/firewall/waf/packages/{config.package_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_waf_package"
        return result

    async def _list_waf_package_rule_groups(self, config: CloudflareListWAFPackageRuleGroupsConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {"per_page": config.per_page or 50}
        result = await self._request("GET", f"/zones/{config.zone_id}/firewall/waf/packages/{config.package_id}/groups", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_waf_package_rule_groups"
        return result

    async def _list_waf_package_rules(self, config: CloudflareListWAFPackageRulesConfig, creds: CloudflareCredential) -> Dict:
        params: Dict[str, Any] = {"per_page": config.per_page or 50}
        result = await self._request("GET", f"/zones/{config.zone_id}/firewall/waf/packages/{config.package_id}/rules", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_waf_package_rules"
        return result

    async def _update_waf_rule(self, config: CloudflareUpdateWAFRuleConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("PATCH", f"/zones/{config.zone_id}/firewall/waf/packages/{config.package_id}/rules/{config.rule_id}", creds, json={"mode": config.mode})
        if result["status"] == "success":
            result["action"] = "update_waf_rule"
        return result

    # ── Early Hints / HTTP3 / Brotli handlers ────────────────────────────────────

    async def _get_early_hints_setting(self, config: CloudflareGetEarlyHintsSettingConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"/zones/{config.zone_id}/settings/early_hints", creds)
        if result["status"] == "success":
            result["action"] = "get_early_hints_setting"
        return result

    async def _update_early_hints_setting(self, config: CloudflareUpdateEarlyHintsSettingConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("PATCH", f"/zones/{config.zone_id}/settings/early_hints", creds, json={"value": config.enabled})
        if result["status"] == "success":
            result["action"] = "update_early_hints_setting"
        return result

    async def _get_http3_setting(self, config: CloudflareGetHTTP3SettingConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"/zones/{config.zone_id}/settings/http3", creds)
        if result["status"] == "success":
            result["action"] = "get_http3_setting"
        return result

    async def _update_http3_setting(self, config: CloudflareUpdateHTTP3SettingConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("PATCH", f"/zones/{config.zone_id}/settings/http3", creds, json={"value": config.enabled})
        if result["status"] == "success":
            result["action"] = "update_http3_setting"
        return result

    async def _get_brotli_setting(self, config: CloudflareGetBrotliSettingConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("GET", f"/zones/{config.zone_id}/settings/brotli", creds)
        if result["status"] == "success":
            result["action"] = "get_brotli_setting"
        return result

    async def _update_brotli_setting(self, config: CloudflareUpdateBrotliSettingConfig, creds: CloudflareCredential) -> Dict:
        result = await self._request("PATCH", f"/zones/{config.zone_id}/settings/brotli", creds, json={"value": config.enabled})
        if result["status"] == "success":
            result["action"] = "update_brotli_setting"
        return result

    # ── Main Execute Dispatcher ───────────────────────────────────────────────────


    # ===================================================================
    # Restored operation-family handlers (Intel, Addressing/BYOIP, Magic
    # Transit, Calls, Radar AI, URL Scanner, Bot Management, Workers AI,
    # Analytics Engine SQL, Log Explorer/Logpull/CMB, R2 Event Notif.)
    # ===================================================================

    # ── Intel / Security Center ──
    async def _add_intel_feed_permission(self, config: CloudflareAddIntelFeedPermissionConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body: Dict[str, Any] = {}
        if config.account_tag is not None:
            body['account_tag'] = config.account_tag
        if config.feed_id is not None:
            body['feed_id'] = int(config.feed_id)
        result = await self._request("PUT", base + "/intel/indicator-feeds/permissions/add", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "add_intel_feed_permission"
        return result

    async def _create_intel_indicator_feed(self, config: CloudflareCreateIntelIndicatorFeedConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body: Dict[str, Any] = {}
        if config.name is not None:
            body['name'] = config.name
        if config.description is not None:
            body['description'] = config.description
        result = await self._request("POST", base + "/intel/indicator-feeds", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "create_intel_indicator_feed"
        return result

    async def _create_intel_miscategorization(self, config: CloudflareCreateIntelMiscategorizationConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body: Dict = {}
        itype = config.indicator_type
        if itype == "ip":
            itype = "ipv6" if (config.ip and ":" in config.ip) else "ipv4"
        body["indicator_type"] = itype
        if config.url is not None:
            body["url"] = config.url
        if config.ip is not None:
            body["ip"] = config.ip
        for field in ("content_adds", "content_removes", "security_adds", "security_removes"):
            raw = getattr(config, field)
            if raw:
                body[field] = [int(x.strip()) for x in raw.split(",") if x.strip()]
        result = await self._request("POST", base + "/intel/miscategorization", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "create_intel_miscategorization"
        return result

    async def _dismiss_attack_surface_issue(self, config: CloudflareDismissAttackSurfaceIssueConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body: Dict[str, Any] = {}
        if config.dismiss is not None:
            body['dismiss'] = (config.dismiss == "true")
        result = await self._request("PUT", base + f"/intel/attack-surface-report/issues/{config.issue_id}/dismiss", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "dismiss_attack_surface_issue"
        return result

    async def _get_attack_surface_issues_by_severity(self, config: CloudflareGetAttackSurfaceIssuesBySeverityConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        params: Dict[str, Any] = {}
        if config.dismissed is not None:
            params['dismissed'] = config.dismissed
        if config.issue_class is not None:
            params['issue_class'] = config.issue_class
        if config.issue_type is not None:
            params['issue_type'] = config.issue_type
        if config.product is not None:
            params['product'] = config.product
        if config.subject is not None:
            params['subject'] = config.subject
        result = await self._request("GET", base + "/intel/attack-surface-report/issues/severity", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_attack_surface_issues_by_severity"
        return result

    async def _get_attack_surface_issues_by_type(self, config: CloudflareGetAttackSurfaceIssuesByTypeConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        params: Dict[str, Any] = {}
        if config.dismissed is not None:
            params['dismissed'] = config.dismissed
        if config.issue_class is not None:
            params['issue_class'] = config.issue_class
        if config.severity is not None:
            params['severity'] = config.severity
        if config.product is not None:
            params['product'] = config.product
        if config.subject is not None:
            params['subject'] = config.subject
        result = await self._request("GET", base + "/intel/attack-surface-report/issues/type", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_attack_surface_issues_by_type"
        return result

    async def _get_intel_asn(self, config: CloudflareGetIntelASNConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + f"/intel/asn/{config.asn}", creds)
        if result["status"] == "success":
            result["action"] = "get_intel_asn"
        return result

    async def _get_intel_asn_subnets(self, config: CloudflareGetIntelASNSubnetsConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + f"/intel/asn/{config.asn}/subnets", creds)
        if result["status"] == "success":
            result["action"] = "get_intel_asn_subnets"
        return result

    async def _get_intel_dns(self, config: CloudflareGetIntelDNSConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        params: Dict[str, Any] = {}
        if config.ipv4 is not None:
            params['ipv4'] = config.ipv4
        if config.page is not None:
            params['page'] = config.page
        if config.per_page is not None:
            params['per_page'] = config.per_page
        result = await self._request("GET", base + "/intel/dns", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_intel_dns"
        return result

    async def _get_intel_domain(self, config: CloudflareGetIntelDomainConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        params: Dict[str, Any] = {}
        if config.domain is not None:
            params['domain'] = config.domain
        if config.skip_dns is not None:
            params['skip_dns'] = config.skip_dns
        if config.skip_ranking is not None:
            params['skip_ranking'] = config.skip_ranking
        result = await self._request("GET", base + "/intel/domain", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_intel_domain"
        return result

    async def _get_intel_domain_bulk(self, config: CloudflareGetIntelDomainBulkConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        params: Dict = {"domain": [d.strip() for d in config.domain.split(",") if d.strip()]}
        if config.include_ranking is not None:
            params["include_ranking"] = config.include_ranking
        result = await self._request("GET", base + "/intel/domain/bulk", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_intel_domain_bulk"
        return result

    async def _get_intel_domain_history(self, config: CloudflareGetIntelDomainHistoryConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        params: Dict[str, Any] = {}
        if config.domain is not None:
            params['domain'] = config.domain
        result = await self._request("GET", base + "/intel/domain-history", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_intel_domain_history"
        return result

    async def _get_intel_indicator_feed(self, config: CloudflareGetIntelIndicatorFeedConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + f"/intel/indicator-feeds/{config.feed_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_intel_indicator_feed"
        return result

    async def _get_intel_indicator_feed_data(self, config: CloudflareGetIntelIndicatorFeedDataConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + f"/intel/indicator-feeds/{config.feed_id}/data", creds)
        if result["status"] == "success":
            result["action"] = "get_intel_indicator_feed_data"
        return result

    async def _get_intel_ip(self, config: CloudflareGetIntelIPConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        params: Dict[str, Any] = {}
        if config.ipv4 is not None:
            params['ipv4'] = config.ipv4
        if config.ipv6 is not None:
            params['ipv6'] = config.ipv6
        result = await self._request("GET", base + "/intel/ip", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_intel_ip"
        return result

    async def _get_intel_whois(self, config: CloudflareGetIntelWHOISConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        params: Dict[str, Any] = {}
        if config.domain is not None:
            params['domain'] = config.domain
        result = await self._request("GET", base + "/intel/whois", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_intel_whois"
        return result

    async def _list_attack_surface_issue_types(self, config: CloudflareListAttackSurfaceIssueTypesConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + "/intel/attack-surface-report/issue-types", creds)
        if result["status"] == "success":
            result["action"] = "list_attack_surface_issue_types"
        return result

    async def _list_attack_surface_issues(self, config: CloudflareListAttackSurfaceIssuesConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        params: Dict[str, Any] = {}
        if config.dismissed is not None:
            params['dismissed'] = config.dismissed
        if config.issue_class is not None:
            params['issue_class'] = config.issue_class
        if config.issue_type is not None:
            params['issue_type'] = config.issue_type
        if config.severity is not None:
            params['severity'] = config.severity
        if config.product is not None:
            params['product'] = config.product
        if config.subject is not None:
            params['subject'] = config.subject
        if config.page is not None:
            params['page'] = config.page
        if config.per_page is not None:
            params['per_page'] = config.per_page
        result = await self._request("GET", base + "/intel/attack-surface-report/issues", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_attack_surface_issues"
        return result

    async def _list_intel_feed_permissions(self, config: CloudflareListIntelFeedPermissionsConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + "/intel/indicator-feeds/permissions/view", creds)
        if result["status"] == "success":
            result["action"] = "list_intel_feed_permissions"
        return result

    async def _list_intel_indicator_feeds(self, config: CloudflareListIntelIndicatorFeedsConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + "/intel/indicator-feeds", creds)
        if result["status"] == "success":
            result["action"] = "list_intel_indicator_feeds"
        return result

    async def _list_intel_sinkholes(self, config: CloudflareListIntelSinkholesConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + "/intel/sinkholes", creds)
        if result["status"] == "success":
            result["action"] = "list_intel_sinkholes"
        return result

    async def _remove_intel_feed_permission(self, config: CloudflareRemoveIntelFeedPermissionConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body: Dict[str, Any] = {}
        if config.account_tag is not None:
            body['account_tag'] = config.account_tag
        if config.feed_id is not None:
            body['feed_id'] = int(config.feed_id)
        result = await self._request("PUT", base + "/intel/indicator-feeds/permissions/remove", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "remove_intel_feed_permission"
        return result

    async def _update_intel_indicator_feed(self, config: CloudflareUpdateIntelIndicatorFeedConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body: Dict = {}
        if config.name is not None:
            body["name"] = config.name
        if config.description is not None:
            body["description"] = config.description
        for field in ("is_attributable", "is_downloadable", "is_public"):
            raw = getattr(config, field)
            if raw is not None:
                body[field] = (raw == "true")
        result = await self._request("PUT", base + f"/intel/indicator-feeds/{config.feed_id}", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "update_intel_indicator_feed"
        return result

    # ── Addressing / BYOIP ──
    async def _add_ip_to_address_map(self, config: CloudflareAddIPToAddressMapConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("PUT", base + f"/addressing/address_maps/{config.address_map_id}/ips/{config.ip_address}", creds)
        if result["status"] == "success":
            result["action"] = "add_ip_to_address_map"
        return result

    async def _add_zone_to_address_map(self, config: CloudflareAddZoneToAddressMapConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("PUT", base + f"/addressing/address_maps/{config.address_map_id}/zones/{config.zone_id}", creds)
        if result["status"] == "success":
            result["action"] = "add_zone_to_address_map"
        return result

    async def _create_address_map(self, config: CloudflareCreateAddressMapConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body: Dict[str, Any] = {}
        if config.description is not None:
            body['description'] = config.description
        if config.default_sni is not None:
            body['default_sni'] = config.default_sni
        if config.enabled is not None:
            body['enabled'] = (config.enabled == "true")
        result = await self._request("POST", base + "/addressing/address_maps", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "create_address_map"
        return result

    async def _create_ip_prefix(self, config: CloudflareCreateIPPrefixConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body: Dict[str, Any] = {}
        if config.asn is not None:
            body['asn'] = int(config.asn)
        if config.cidr is not None:
            body['cidr'] = config.cidr
        if config.loa_document_id is not None:
            body['loa_document_id'] = config.loa_document_id
        if config.description is not None:
            body['description'] = config.description
        result = await self._request("POST", base + "/addressing/prefixes", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "create_ip_prefix"
        return result

    async def _create_prefix_delegation(self, config: CloudflareCreatePrefixDelegationConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body: Dict[str, Any] = {}
        if config.cidr is not None:
            body['cidr'] = config.cidr
        if config.delegated_account_id is not None:
            body['delegated_account_id'] = config.delegated_account_id
        result = await self._request("POST", base + f"/addressing/prefixes/{config.prefix_id}/delegations", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "create_prefix_delegation"
        return result

    async def _create_prefix_service_binding(self, config: CloudflareCreatePrefixServiceBindingConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body: Dict[str, Any] = {}
        if config.cidr is not None:
            body['cidr'] = config.cidr
        if config.service_id is not None:
            body['service_id'] = config.service_id
        result = await self._request("POST", base + f"/addressing/prefixes/{config.prefix_id}/bindings", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "create_prefix_service_binding"
        return result

    async def _create_regional_hostname(self, config: CloudflareCreateRegionalHostnameConfig, creds: CloudflareCredential) -> Dict:
        base = f"/zones/{config.zone_id}"
        body: Dict[str, Any] = {}
        if config.hostname is not None:
            body['hostname'] = config.hostname
        if config.region_key is not None:
            body['region_key'] = config.region_key
        if config.routing is not None:
            body['routing'] = config.routing
        result = await self._request("POST", base + "/addressing/regional_hostnames", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "create_regional_hostname"
        return result

    async def _delete_address_map(self, config: CloudflareDeleteAddressMapConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("DELETE", base + f"/addressing/address_maps/{config.address_map_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_address_map"
        return result

    async def _delete_ip_prefix(self, config: CloudflareDeleteIPPrefixConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("DELETE", base + f"/addressing/prefixes/{config.prefix_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_ip_prefix"
        return result

    async def _delete_prefix_delegation(self, config: CloudflareDeletePrefixDelegationConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("DELETE", base + f"/addressing/prefixes/{config.prefix_id}/delegations/{config.delegation_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_prefix_delegation"
        return result

    async def _delete_prefix_service_binding(self, config: CloudflareDeletePrefixServiceBindingConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("DELETE", base + f"/addressing/prefixes/{config.prefix_id}/bindings/{config.binding_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_prefix_service_binding"
        return result

    async def _delete_regional_hostname(self, config: CloudflareDeleteRegionalHostnameConfig, creds: CloudflareCredential) -> Dict:
        base = f"/zones/{config.zone_id}"
        result = await self._request("DELETE", base + f"/addressing/regional_hostnames/{config.hostname}", creds)
        if result["status"] == "success":
            result["action"] = "delete_regional_hostname"
        return result

    async def _download_loa_document(self, config: CloudflareDownloadLOADocumentConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + f"/addressing/loa_documents/{config.loa_document_id}/download", creds)
        if result["status"] == "success":
            result["action"] = "download_loa_document"
        return result

    async def _get_address_map(self, config: CloudflareGetAddressMapConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + f"/addressing/address_maps/{config.address_map_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_address_map"
        return result

    async def _get_bgp_prefix_advertisement_status(self, config: CloudflareGetBGPAdvertisementStatusConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + f"/addressing/prefixes/{config.prefix_id}/bgp/status", creds)
        if result["status"] == "success":
            result["action"] = "get_bgp_prefix_advertisement_status"
        return result

    async def _get_ip_prefix(self, config: CloudflareGetIPPrefixConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + f"/addressing/prefixes/{config.prefix_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_ip_prefix"
        return result

    async def _get_prefix_service_binding(self, config: CloudflareGetPrefixServiceBindingConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + f"/addressing/prefixes/{config.prefix_id}/bindings/{config.binding_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_prefix_service_binding"
        return result

    async def _get_regional_hostname(self, config: CloudflareGetRegionalHostnameConfig, creds: CloudflareCredential) -> Dict:
        base = f"/zones/{config.zone_id}"
        result = await self._request("GET", base + f"/addressing/regional_hostnames/{config.hostname}", creds)
        if result["status"] == "success":
            result["action"] = "get_regional_hostname"
        return result

    async def _list_address_maps(self, config: CloudflareListAddressMapsConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + "/addressing/address_maps", creds)
        if result["status"] == "success":
            result["action"] = "list_address_maps"
        return result

    async def _list_addressing_services(self, config: CloudflareListAddressingServicesConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + "/addressing/services", creds)
        if result["status"] == "success":
            result["action"] = "list_addressing_services"
        return result

    async def _list_bgp_prefixes(self, config: CloudflareListBGPPrefixesConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + f"/addressing/prefixes/{config.prefix_id}/bgp/prefixes", creds)
        if result["status"] == "success":
            result["action"] = "list_bgp_prefixes"
        return result

    async def _list_ip_prefixes(self, config: CloudflareListIPPrefixesConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + "/addressing/prefixes", creds)
        if result["status"] == "success":
            result["action"] = "list_ip_prefixes"
        return result

    async def _list_prefix_delegations(self, config: CloudflareListPrefixDelegationsConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + f"/addressing/prefixes/{config.prefix_id}/delegations", creds)
        if result["status"] == "success":
            result["action"] = "list_prefix_delegations"
        return result

    async def _list_prefix_service_bindings(self, config: CloudflareListPrefixServiceBindingsConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + f"/addressing/prefixes/{config.prefix_id}/bindings", creds)
        if result["status"] == "success":
            result["action"] = "list_prefix_service_bindings"
        return result

    async def _list_regional_hostname_regions(self, config: CloudflareListRegionalHostnameRegionsConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + "/addressing/regional_hostnames/regions", creds)
        if result["status"] == "success":
            result["action"] = "list_regional_hostname_regions"
        return result

    async def _list_regional_hostnames(self, config: CloudflareListRegionalHostnamesConfig, creds: CloudflareCredential) -> Dict:
        base = f"/zones/{config.zone_id}"
        result = await self._request("GET", base + "/addressing/regional_hostnames", creds)
        if result["status"] == "success":
            result["action"] = "list_regional_hostnames"
        return result

    async def _remove_ip_from_address_map(self, config: CloudflareRemoveIPFromAddressMapConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("DELETE", base + f"/addressing/address_maps/{config.address_map_id}/ips/{config.ip_address}", creds)
        if result["status"] == "success":
            result["action"] = "remove_ip_from_address_map"
        return result

    async def _remove_zone_from_address_map(self, config: CloudflareRemoveZoneFromAddressMapConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("DELETE", base + f"/addressing/address_maps/{config.address_map_id}/zones/{config.zone_id}", creds)
        if result["status"] == "success":
            result["action"] = "remove_zone_from_address_map"
        return result

    async def _update_address_map(self, config: CloudflareUpdateAddressMapConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body: Dict[str, Any] = {}
        if config.description is not None:
            body['description'] = config.description
        if config.default_sni is not None:
            body['default_sni'] = config.default_sni
        if config.enabled is not None:
            body['enabled'] = (config.enabled == "true")
        result = await self._request("PATCH", base + f"/addressing/address_maps/{config.address_map_id}", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "update_address_map"
        return result

    async def _update_bgp_prefix(self, config: CloudflareUpdateBGPPrefixConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body: Dict = {}
        if config.asn_prepend_count is not None:
            body["asn_prepend_count"] = int(config.asn_prepend_count)
        if config.on_demand_enabled is not None:
            body["on_demand"] = {"advertised": config.on_demand_enabled == "true"}
        result = await self._request(
            "PATCH",
            base + f"/addressing/prefixes/{config.prefix_id}/bgp/prefixes/{config.bgp_prefix_id}",
            creds,
            json=body or None,
        )
        if result["status"] == "success":
            result["action"] = "update_bgp_prefix"
        return result

    async def _update_bgp_prefix_advertisement(self, config: CloudflareUpdateBGPAdvertisementConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body: Dict[str, Any] = {}
        if config.advertised is not None:
            body['advertised'] = (config.advertised == "true")
        result = await self._request("PATCH", base + f"/addressing/prefixes/{config.prefix_id}/bgp/status", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "update_bgp_prefix_advertisement"
        return result

    async def _update_ip_prefix(self, config: CloudflareUpdateIPPrefixConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body: Dict[str, Any] = {}
        if config.description is not None:
            body['description'] = config.description
        result = await self._request("PATCH", base + f"/addressing/prefixes/{config.prefix_id}", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "update_ip_prefix"
        return result

    async def _update_regional_hostname(self, config: CloudflareUpdateRegionalHostnameConfig, creds: CloudflareCredential) -> Dict:
        base = f"/zones/{config.zone_id}"
        body: Dict[str, Any] = {}
        if config.region_key is not None:
            body['region_key'] = config.region_key
        result = await self._request("PATCH", base + f"/addressing/regional_hostnames/{config.hostname}", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "update_regional_hostname"
        return result

    async def _upload_loa_document(self, config: CloudflareUploadLOADocumentConfig, creds: CloudflareCredential) -> Dict:
        import base64
        base = await self._account_path(creds)
        pdf_bytes = base64.b64decode(config.loa_document)
        files = {"loa_document": ("loa.pdf", pdf_bytes, "application/pdf")}
        result = await self._request(
            "POST",
            base + "/addressing/loa_documents",
            creds,
            files=files,
        )
        if result["status"] == "success":
            result["action"] = "upload_loa_document"
        return result

    # ── Magic Transit ──
    async def _create_magic_app(self, config: CloudflareCreateMagicAppConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body = {"name": config.name, "type": config.type}
        if config.hostnames:
            body["hostnames"] = [h.strip() for h in config.hostnames.split(",") if h.strip()]
        if config.ip_subnets:
            body["ip_subnets"] = [s.strip() for s in config.ip_subnets.split(",") if s.strip()]
        if config.source_subnets:
            body["source_subnets"] = [s.strip() for s in config.source_subnets.split(",") if s.strip()]
        result = await self._request("POST", base + "/magic/apps", creds, json=body)
        if result["status"] == "success":
            result["action"] = "create_magic_app"
        return result

    async def _create_magic_gre_tunnel(self, config: CloudflareCreateMagicGRETunnelConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body = {
            "name": config.name,
            "cloudflare_gre_endpoint": config.cloudflare_gre_endpoint,
            "customer_gre_endpoint": config.customer_gre_endpoint,
            "interface_address": config.interface_address,
        }
        if config.description is not None:
            body["description"] = config.description
        if config.mtu is not None:
            body["mtu"] = int(config.mtu)
        if config.ttl is not None:
            body["ttl"] = int(config.ttl)
        result = await self._request("POST", base + "/magic/gre_tunnels", creds, json=body)
        if result["status"] == "success":
            result["action"] = "create_magic_gre_tunnel"
        return result

    async def _delete_magic_app(self, config: CloudflareDeleteMagicAppConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("DELETE", base + f"/magic/apps/{config.account_app_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_magic_app"
        return result

    async def _delete_magic_gre_tunnel(self, config: CloudflareDeleteMagicGRETunnelConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("DELETE", base + f"/magic/gre_tunnels/{config.gre_tunnel_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_magic_gre_tunnel"
        return result

    async def _get_magic_cf_interconnect(self, config: CloudflareGetMagicCFInterconnectConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + f"/magic/cf_interconnects/{config.cf_interconnect_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_magic_cf_interconnect"
        return result

    async def _get_magic_gre_tunnel(self, config: CloudflareGetMagicGRETunnelConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + f"/magic/gre_tunnels/{config.gre_tunnel_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_magic_gre_tunnel"
        return result

    async def _list_magic_apps(self, config: CloudflareListMagicAppsConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + "/magic/apps", creds)
        if result["status"] == "success":
            result["action"] = "list_magic_apps"
        return result

    async def _list_magic_cf_interconnects(self, config: CloudflareListMagicCFInterconnectsConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + "/magic/cf_interconnects", creds)
        if result["status"] == "success":
            result["action"] = "list_magic_cf_interconnects"
        return result

    async def _list_magic_gre_tunnels(self, config: CloudflareListMagicGRETunnelsConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + "/magic/gre_tunnels", creds)
        if result["status"] == "success":
            result["action"] = "list_magic_gre_tunnels"
        return result

    async def _update_magic_app(self, config: CloudflareUpdateMagicAppConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body = {}
        if config.name is not None:
            body["name"] = config.name
        if config.type is not None:
            body["type"] = config.type
        if config.hostnames:
            body["hostnames"] = [h.strip() for h in config.hostnames.split(",") if h.strip()]
        if config.ip_subnets:
            body["ip_subnets"] = [s.strip() for s in config.ip_subnets.split(",") if s.strip()]
        if config.source_subnets:
            body["source_subnets"] = [s.strip() for s in config.source_subnets.split(",") if s.strip()]
        result = await self._request("PATCH", base + f"/magic/apps/{config.account_app_id}", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "update_magic_app"
        return result

    async def _update_magic_cf_interconnect(self, config: CloudflareUpdateMagicCFInterconnectConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body = {}
        if config.name is not None:
            body["name"] = config.name
        if config.description is not None:
            body["description"] = config.description
        if config.interface_address is not None:
            body["interface_address"] = config.interface_address
        if config.mtu is not None:
            body["mtu"] = int(config.mtu)
        result = await self._request("PUT", base + f"/magic/cf_interconnects/{config.cf_interconnect_id}", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "update_magic_cf_interconnect"
        return result

    async def _update_magic_gre_tunnel(self, config: CloudflareUpdateMagicGRETunnelConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body = {
            "name": config.name,
            "cloudflare_gre_endpoint": config.cloudflare_gre_endpoint,
            "customer_gre_endpoint": config.customer_gre_endpoint,
            "interface_address": config.interface_address,
        }
        if config.description is not None:
            body["description"] = config.description
        if config.mtu is not None:
            body["mtu"] = int(config.mtu)
        if config.ttl is not None:
            body["ttl"] = int(config.ttl)
        result = await self._request("PUT", base + f"/magic/gre_tunnels/{config.gre_tunnel_id}", creds, json=body)
        if result["status"] == "success":
            result["action"] = "update_magic_gre_tunnel"
        return result

    # ── Calls / Realtime ──
    async def _create_calls_app(self, config: CloudflareCreateCallsAppConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body: Dict[str, Any] = {}
        if config.name is not None:
            body['name'] = config.name
        result = await self._request("POST", base + "/calls/apps", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "create_calls_app"
        return result

    async def _create_calls_turn_key(self, config: CloudflareCreateCallsTurnKeyConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body: Dict[str, Any] = {}
        if config.name is not None:
            body['name'] = config.name
        result = await self._request("POST", base + "/calls/turn_keys", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "create_calls_turn_key"
        return result

    async def _delete_calls_app(self, config: CloudflareDeleteCallsAppConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("DELETE", base + f"/calls/apps/{config.app_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_calls_app"
        return result

    async def _delete_calls_turn_key(self, config: CloudflareDeleteCallsTurnKeyConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("DELETE", base + f"/calls/turn_keys/{config.key_id}", creds)
        if result["status"] == "success":
            result["action"] = "delete_calls_turn_key"
        return result

    async def _get_calls_app(self, config: CloudflareGetCallsAppConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + f"/calls/apps/{config.app_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_calls_app"
        return result

    async def _get_calls_turn_key(self, config: CloudflareGetCallsTurnKeyConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + f"/calls/turn_keys/{config.key_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_calls_turn_key"
        return result

    async def _list_calls_apps(self, config: CloudflareListCallsAppsConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + "/calls/apps", creds)
        if result["status"] == "success":
            result["action"] = "list_calls_apps"
        return result

    async def _list_calls_turn_keys(self, config: CloudflareListCallsTurnKeysConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + "/calls/turn_keys", creds)
        if result["status"] == "success":
            result["action"] = "list_calls_turn_keys"
        return result

    async def _update_calls_app(self, config: CloudflareUpdateCallsAppConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body: Dict[str, Any] = {}
        if config.name is not None:
            body['name'] = config.name
        result = await self._request("PUT", base + f"/calls/apps/{config.app_id}", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "update_calls_app"
        return result

    async def _update_calls_turn_key(self, config: CloudflareUpdateCallsTurnKeyConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body: Dict[str, Any] = {}
        if config.name is not None:
            body['name'] = config.name
        result = await self._request("PUT", base + f"/calls/turn_keys/{config.key_id}", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "update_calls_turn_key"
        return result

    # ── Radar AI ──
    async def _get_radar_ai_bots_summary(self, config: CloudflareGetRadarAIBotsSummaryConfig, creds: CloudflareCredential) -> Dict:
        base = ""
        params: Dict[str, Any] = {}
        if config.date_range is not None:
            params['dateRange'] = config.date_range
        if config.date_start is not None:
            params['dateStart'] = config.date_start
        if config.date_end is not None:
            params['dateEnd'] = config.date_end
        if config.user_agent is not None:
            params['userAgent'] = config.user_agent
        if config.crawl_purpose is not None:
            params['crawlPurpose'] = config.crawl_purpose
        if config.industry is not None:
            params['industry'] = config.industry
        if config.limit_per_group is not None:
            params['limitPerGroup'] = config.limit_per_group
        if config.format is not None:
            params['format'] = config.format
        result = await self._request("GET", base + f"/radar/ai/bots/summary/{config.dimension.lower()}", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_radar_ai_bots_summary"
        return result

    async def _get_radar_ai_bots_summary_by_crawl_purpose(self, config: CloudflareGetRadarAIBotsSummaryByCrawlPurposeConfig, creds: CloudflareCredential) -> Dict:
        base = ""
        params: Dict[str, Any] = {}
        if config.date_range is not None:
            params['dateRange'] = config.date_range
        if config.date_start is not None:
            params['dateStart'] = config.date_start
        if config.date_end is not None:
            params['dateEnd'] = config.date_end
        if config.user_agent is not None:
            params['userAgent'] = config.user_agent
        if config.asn is not None:
            params['asn'] = config.asn
        if config.location is not None:
            params['location'] = config.location
        if config.limit_per_group is not None:
            params['limitPerGroup'] = config.limit_per_group
        if config.format is not None:
            params['format'] = config.format
        result = await self._request("GET", base + "/radar/ai/bots/summary/crawl_purpose", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_radar_ai_bots_summary_by_crawl_purpose"
        return result

    async def _get_radar_ai_bots_summary_by_industry(self, config: CloudflareGetRadarAIBotsSummaryByIndustryConfig, creds: CloudflareCredential) -> Dict:
        base = ""
        params: Dict[str, Any] = {}
        if config.date_range is not None:
            params['dateRange'] = config.date_range
        if config.date_start is not None:
            params['dateStart'] = config.date_start
        if config.date_end is not None:
            params['dateEnd'] = config.date_end
        if config.user_agent is not None:
            params['userAgent'] = config.user_agent
        if config.crawl_purpose is not None:
            params['crawlPurpose'] = config.crawl_purpose
        if config.asn is not None:
            params['asn'] = config.asn
        if config.location is not None:
            params['location'] = config.location
        if config.limit_per_group is not None:
            params['limitPerGroup'] = config.limit_per_group
        if config.format is not None:
            params['format'] = config.format
        result = await self._request("GET", base + "/radar/ai/bots/summary/industry", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_radar_ai_bots_summary_by_industry"
        return result

    async def _get_radar_ai_bots_summary_by_user_agent(self, config: CloudflareGetRadarAIBotsSummaryByUserAgentConfig, creds: CloudflareCredential) -> Dict:
        base = ""
        params: Dict[str, Any] = {}
        if config.date_range is not None:
            params['dateRange'] = config.date_range
        if config.date_start is not None:
            params['dateStart'] = config.date_start
        if config.date_end is not None:
            params['dateEnd'] = config.date_end
        if config.asn is not None:
            params['asn'] = config.asn
        if config.continent is not None:
            params['continent'] = config.continent
        if config.location is not None:
            params['location'] = config.location
        if config.limit_per_group is not None:
            params['limitPerGroup'] = config.limit_per_group
        if config.format is not None:
            params['format'] = config.format
        result = await self._request("GET", base + "/radar/ai/bots/summary/user_agent", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_radar_ai_bots_summary_by_user_agent"
        return result

    async def _get_radar_ai_bots_timeseries(self, config: CloudflareGetRadarAIBotsTimeseriesConfig, creds: CloudflareCredential) -> Dict:
        base = ""
        params: Dict[str, Any] = {}
        if config.agg_interval is not None:
            params['aggInterval'] = config.agg_interval
        if config.date_range is not None:
            params['dateRange'] = config.date_range
        if config.date_start is not None:
            params['dateStart'] = config.date_start
        if config.date_end is not None:
            params['dateEnd'] = config.date_end
        if config.user_agent is not None:
            params['userAgent'] = config.user_agent
        if config.crawl_purpose is not None:
            params['crawlPurpose'] = config.crawl_purpose
        if config.industry is not None:
            params['industry'] = config.industry
        if config.asn is not None:
            params['asn'] = config.asn
        if config.continent is not None:
            params['continent'] = config.continent
        if config.location is not None:
            params['location'] = config.location
        if config.format is not None:
            params['format'] = config.format
        result = await self._request("GET", base + "/radar/ai/bots/timeseries", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_radar_ai_bots_timeseries"
        return result

    async def _get_radar_ai_bots_timeseries_by_user_agent(self, config: CloudflareGetRadarAIBotsTimeseriesByUserAgentConfig, creds: CloudflareCredential) -> Dict:
        base = ""
        params: Dict[str, Any] = {}
        if config.agg_interval is not None:
            params['aggInterval'] = config.agg_interval
        if config.date_range is not None:
            params['dateRange'] = config.date_range
        if config.date_start is not None:
            params['dateStart'] = config.date_start
        if config.date_end is not None:
            params['dateEnd'] = config.date_end
        if config.asn is not None:
            params['asn'] = config.asn
        if config.continent is not None:
            params['continent'] = config.continent
        if config.location is not None:
            params['location'] = config.location
        if config.limit_per_group is not None:
            params['limitPerGroup'] = config.limit_per_group
        if config.format is not None:
            params['format'] = config.format
        result = await self._request("GET", base + "/radar/ai/bots/timeseries_groups/user_agent", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_radar_ai_bots_timeseries_by_user_agent"
        return result

    async def _get_radar_ai_bots_timeseries_groups(self, config: CloudflareGetRadarAIBotsTimeseriesGroupsConfig, creds: CloudflareCredential) -> Dict:
        base = ""
        params: Dict[str, Any] = {}
        if config.agg_interval is not None:
            params['aggInterval'] = config.agg_interval
        if config.normalization is not None:
            params['normalization'] = config.normalization
        if config.date_range is not None:
            params['dateRange'] = config.date_range
        if config.date_start is not None:
            params['dateStart'] = config.date_start
        if config.date_end is not None:
            params['dateEnd'] = config.date_end
        if config.user_agent is not None:
            params['userAgent'] = config.user_agent
        if config.crawl_purpose is not None:
            params['crawlPurpose'] = config.crawl_purpose
        if config.industry is not None:
            params['industry'] = config.industry
        if config.limit_per_group is not None:
            params['limitPerGroup'] = config.limit_per_group
        if config.format is not None:
            params['format'] = config.format
        result = await self._request("GET", base + f"/radar/ai/bots/timeseries_groups/{config.dimension.lower()}", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_radar_ai_bots_timeseries_groups"
        return result

    async def _get_radar_ai_inference_summary_by_model(self, config: CloudflareGetRadarAIInferenceSummaryByModelConfig, creds: CloudflareCredential) -> Dict:
        base = ""
        params: Dict[str, Any] = {}
        if config.date_range is not None:
            params['dateRange'] = config.date_range
        if config.date_start is not None:
            params['dateStart'] = config.date_start
        if config.date_end is not None:
            params['dateEnd'] = config.date_end
        if config.limit_per_group is not None:
            params['limitPerGroup'] = config.limit_per_group
        if config.format is not None:
            params['format'] = config.format
        result = await self._request("GET", base + "/radar/ai/inference/summary/model", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_radar_ai_inference_summary_by_model"
        return result

    async def _get_radar_ai_inference_summary_by_task(self, config: CloudflareGetRadarAIInferenceSummaryByTaskConfig, creds: CloudflareCredential) -> Dict:
        base = ""
        params: Dict[str, Any] = {}
        if config.date_range is not None:
            params['dateRange'] = config.date_range
        if config.date_start is not None:
            params['dateStart'] = config.date_start
        if config.date_end is not None:
            params['dateEnd'] = config.date_end
        if config.limit_per_group is not None:
            params['limitPerGroup'] = config.limit_per_group
        if config.format is not None:
            params['format'] = config.format
        result = await self._request("GET", base + "/radar/ai/inference/summary/task", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_radar_ai_inference_summary_by_task"
        return result

    async def _get_radar_ai_inference_timeseries_by_model(self, config: CloudflareGetRadarAIInferenceTimeseriesByModelConfig, creds: CloudflareCredential) -> Dict:
        base = ""
        params: Dict[str, Any] = {}
        if config.agg_interval is not None:
            params['aggInterval'] = config.agg_interval
        if config.date_range is not None:
            params['dateRange'] = config.date_range
        if config.date_start is not None:
            params['dateStart'] = config.date_start
        if config.date_end is not None:
            params['dateEnd'] = config.date_end
        if config.limit_per_group is not None:
            params['limitPerGroup'] = config.limit_per_group
        if config.format is not None:
            params['format'] = config.format
        result = await self._request("GET", base + "/radar/ai/inference/timeseries_groups/model", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_radar_ai_inference_timeseries_by_model"
        return result

    async def _get_radar_ai_inference_timeseries_by_task(self, config: CloudflareGetRadarAIInferenceTimeseriesByTaskConfig, creds: CloudflareCredential) -> Dict:
        base = ""
        params: Dict[str, Any] = {}
        if config.agg_interval is not None:
            params['aggInterval'] = config.agg_interval
        if config.date_range is not None:
            params['dateRange'] = config.date_range
        if config.date_start is not None:
            params['dateStart'] = config.date_start
        if config.date_end is not None:
            params['dateEnd'] = config.date_end
        if config.limit_per_group is not None:
            params['limitPerGroup'] = config.limit_per_group
        if config.format is not None:
            params['format'] = config.format
        result = await self._request("GET", base + "/radar/ai/inference/timeseries_groups/task", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_radar_ai_inference_timeseries_by_task"
        return result

    # ── URL Scanner ──
    async def _get_url_scan(self, config: CloudflareGetUrlScanConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + f"/urlscanner/v2/result/{config.scan_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_url_scan"
        return result

    async def _get_url_scan_dom(self, config: CloudflareGetUrlScanDomConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + f"/urlscanner/v2/dom/{config.scan_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_url_scan_dom"
        return result

    async def _get_url_scan_har(self, config: CloudflareGetUrlScanHarConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + f"/urlscanner/v2/har/{config.scan_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_url_scan_har"
        return result

    async def _get_url_scan_screenshot(self, config: CloudflareGetUrlScanScreenshotConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        params: Dict[str, Any] = {}
        if config.resolution is not None:
            params['resolution'] = config.resolution
        result = await self._request("GET", base + f"/urlscanner/v2/screenshots/{config.scan_id}.png", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_url_scan_screenshot"
        return result

    async def _bulk_submit_url_scans(self, config: CloudflareBulkSubmitUrlScansConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        scans = []
        for line in config.urls.splitlines():
            u = line.strip()
            if not u:
                continue
            item = {"url": u}
            if config.visibility:
                item["visibility"] = config.visibility
            if config.country:
                item["country"] = config.country
            scans.append(item)
        result = await self._request("POST", base + "/urlscanner/v2/bulk", creds, json=scans)
        if result["status"] == "success":
            result["action"] = "bulk_submit_url_scans"
        return result

    async def _search_url_scans(self, config: CloudflareSearchUrlScansConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        params: Dict[str, Any] = {}
        if config.query is not None:
            params['q'] = config.query
        if config.size is not None:
            params['size'] = config.size
        result = await self._request("GET", base + "/urlscanner/v2/search", creds, params=params)
        if result["status"] == "success":
            result["action"] = "search_url_scans"
        return result

    async def _submit_url_scan(self, config: CloudflareSubmitUrlScanConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body = {"url": config.url}
        if config.visibility:
            body["visibility"] = config.visibility
        if config.screenshots_resolutions:
            body["screenshotsResolutions"] = [r.strip() for r in config.screenshots_resolutions.split(",") if r.strip()]
        if config.country:
            body["country"] = config.country
        if config.custom_agent:
            body["customagent"] = config.custom_agent
        if config.referer:
            body["referer"] = config.referer
        result = await self._request("POST", base + "/urlscanner/v2/scan", creds, json=body)
        if result["status"] == "success":
            result["action"] = "submit_url_scan"
        return result

    # ── Bot Management ──
    async def _get_bot_management_analytics(self, config: CloudflareGetBotManagementAnalyticsConfig, creds: CloudflareCredential) -> Dict:
        base = f"/zones/{config.zone_id}"
        result = await self._request("GET", base + "/bot_management/feedback", creds)
        if result["status"] == "success":
            result["action"] = "get_bot_management_analytics"
        return result

    async def _get_bot_score_thresholds(self, config: CloudflareGetBotScoreThresholdsConfig, creds: CloudflareCredential) -> Dict:
        base = f"/zones/{config.zone_id}"
        result = await self._request("GET", base + "/bot_management", creds)
        if result["status"] == "success":
            result["action"] = "get_bot_score_thresholds"
        return result

    async def _update_bot_score_thresholds(self, config: CloudflareUpdateBotScoreThresholdsConfig, creds: CloudflareCredential) -> Dict:
        base = f"/zones/{config.zone_id}"
        body = {}
        for f in ("sbfm_definitely_automated", "sbfm_likely_automated", "sbfm_verified_bots", "ai_bots_protection", "content_bots_protection", "crawler_protection"):
            v = getattr(config, f)
            if v is not None:
                body[f] = v
        for f in ("sbfm_static_resource_protection", "optimize_wordpress"):
            v = getattr(config, f)
            if v is not None:
                body[f] = (v == "true")
        result = await self._request("PUT", base + "/bot_management", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "update_bot_score_thresholds"
        return result

    async def _configure_javascript_detection(self, config: CloudflareConfigureJavascriptDetectionConfig, creds: CloudflareCredential) -> Dict:
        base = f"/zones/{config.zone_id}"
        body = {"enable_js": (config.enable_js == "true")}
        if config.bm_cookie_enabled is not None:
            body["bm_cookie_enabled"] = (config.bm_cookie_enabled == "true")
        if config.suppress_session_score is not None:
            body["suppress_session_score"] = (config.suppress_session_score == "true")
        result = await self._request("PUT", base + "/bot_management", creds, json=body)
        if result["status"] == "success":
            result["action"] = "configure_javascript_detection"
        return result

    async def _list_bot_feedback_reports(self, config: CloudflareListBotFeedbackReportsConfig, creds: CloudflareCredential) -> Dict:
        base = f"/zones/{config.zone_id}"
        result = await self._request("GET", base + "/bot_management/feedback", creds)
        if result["status"] == "success":
            result["action"] = "list_bot_feedback_reports"
        return result

    async def _submit_bot_feedback(self, config: CloudflareSubmitBotFeedbackConfig, creds: CloudflareCredential) -> Dict:
        base = f"/zones/{config.zone_id}"
        body = {
            "type": config.feedback_type,
            "expression": config.expression,
            "description": config.description,
        }
        if config.requests is not None:
            body["requests"] = int(config.requests)
        if config.first_request_seen_at is not None:
            body["first_request_seen_at"] = config.first_request_seen_at
        if config.last_request_seen_at is not None:
            body["last_request_seen_at"] = config.last_request_seen_at
        result = await self._request("POST", base + "/bot_management/feedback", creds, json=body)
        if result["status"] == "success":
            result["action"] = "submit_bot_feedback"
        return result

    # ── Workers AI ──
    async def _create_ai_finetune(self, config: CloudflareCreateAIFinetuneConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body: Dict[str, Any] = {}
        if config.model is not None:
            body['model'] = config.model
        if config.name is not None:
            body['name'] = config.name
        if config.description is not None:
            body['description'] = config.description
        if config.public is not None:
            body['public'] = (config.public == "true")
        result = await self._request("POST", base + "/ai/finetunes", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "create_ai_finetune"
        return result

    async def _get_ai_model_schema(self, config: CloudflareGetAIModelSchemaConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        params: Dict[str, Any] = {}
        if config.model_name is not None:
            params['model'] = config.model_name
        result = await self._request("GET", base + "/ai/models/schema", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_ai_model_schema"
        return result

    async def _list_ai_authors(self, config: CloudflareListAIAuthorsConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        params: Dict[str, Any] = {}
        if config.search is not None:
            params['search'] = config.search
        result = await self._request("GET", base + "/ai/authors/search", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_ai_authors"
        return result

    async def _list_ai_finetunes(self, config: CloudflareListAIFinetunesConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + "/ai/finetunes", creds)
        if result["status"] == "success":
            result["action"] = "list_ai_finetunes"
        return result

    async def _list_ai_tasks(self, config: CloudflareListAITasksConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        params: Dict[str, Any] = {}
        if config.search is not None:
            params['search'] = config.search
        result = await self._request("GET", base + "/ai/tasks/search", creds, params=params)
        if result["status"] == "success":
            result["action"] = "list_ai_tasks"
        return result

    async def _list_public_ai_finetunes(self, config: CloudflareListPublicAIFinetunesConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        params = {}
        if config.per_page is not None:
            params["limit"] = int(config.per_page)
        if config.page is not None and config.per_page is not None:
            params["offset"] = (int(config.page) - 1) * int(config.per_page)
        elif config.page is not None:
            params["offset"] = int(config.page)
        result = await self._request("GET", base + "/ai/finetunes/public", creds, params=params or None)
        if result["status"] == "success":
            result["action"] = "list_public_ai_finetunes"
        return result

    async def _run_ai_image_classification(self, config: CloudflareAIImageClassificationConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        async with guarded_async_client(timeout=60) as client:
            resp = await client.get(config.image_url)
            resp.raise_for_status()
            image_bytes = resp.content
        result = await self._request("POST", base + f"/ai/run/{config.model_name}", creds, data=image_bytes)
        if result["status"] == "success":
            result["action"] = "run_ai_image_classification"
        return result

    async def _run_ai_object_detection(self, config: CloudflareAIObjectDetectionConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        async with guarded_async_client(timeout=60) as client:
            resp = await client.get(config.image_url)
            resp.raise_for_status()
            image_bytes = resp.content
        result = await self._request("POST", base + f"/ai/run/{config.model_name}", creds, data=image_bytes)
        if result["status"] == "success":
            result["action"] = "run_ai_object_detection"
        return result

    async def _run_ai_speech_to_text(self, config: CloudflareAISpeechToTextConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        async with guarded_async_client(timeout=120) as client:
            resp = await client.get(config.audio_url)
            resp.raise_for_status()
            audio_bytes = resp.content
        result = await self._request("POST", base + f"/ai/run/{config.model_name}", creds, data=audio_bytes)
        if result["status"] == "success":
            result["action"] = "run_ai_speech_to_text"
        return result

    async def _run_ai_summarization(self, config: CloudflareAISummarizationConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body: Dict[str, Any] = {}
        if config.input_text is not None:
            body['input_text'] = config.input_text
        if config.max_length is not None:
            body['max_length'] = int(config.max_length)
        result = await self._request("POST", base + f"/ai/run/{config.model_name}", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "run_ai_summarization"
        return result

    async def _run_ai_text_embeddings(self, config: CloudflareAITextEmbeddingsConfig, creds: CloudflareCredential) -> Dict:
        import json as _json
        base = await self._account_path(creds)
        raw = config.text
        try:
            parsed = _json.loads(raw)
            text_val = parsed if isinstance(parsed, list) else raw
        except (ValueError, TypeError):
            text_val = raw
        result = await self._request("POST", base + f"/ai/run/{config.model_name}", creds, json={"text": text_val})
        if result["status"] == "success":
            result["action"] = "run_ai_text_embeddings"
        return result

    async def _run_ai_text_generation(self, config: CloudflareAITextGenerationConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body = {}
        if config.system_prompt:
            messages = [{"role": "system", "content": config.system_prompt}]
            if config.prompt:
                messages.append({"role": "user", "content": config.prompt})
            body["messages"] = messages
        elif config.prompt:
            body["prompt"] = config.prompt
        if config.max_tokens is not None:
            body["max_tokens"] = int(config.max_tokens)
        if config.temperature is not None:
            body["temperature"] = float(config.temperature)
        if config.stream is not None:
            body["stream"] = (config.stream == "true")
        result = await self._request("POST", base + f"/ai/run/{config.model_name}", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "run_ai_text_generation"
        return result

    async def _run_ai_text_to_image(self, config: CloudflareAITextToImageConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body: Dict[str, Any] = {}
        if config.prompt is not None:
            body['prompt'] = config.prompt
        if config.negative_prompt is not None:
            body['negative_prompt'] = config.negative_prompt
        if config.width is not None:
            body['width'] = int(config.width)
        if config.height is not None:
            body['height'] = int(config.height)
        if config.num_steps is not None:
            body['num_steps'] = int(config.num_steps)
        if config.guidance is not None:
            body['guidance'] = float(config.guidance)
        if config.seed is not None:
            body['seed'] = int(config.seed)
        result = await self._request("POST", base + f"/ai/run/{config.model_name}", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "run_ai_text_to_image"
        return result

    async def _run_ai_translation(self, config: CloudflareAITranslationConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body: Dict[str, Any] = {}
        if config.text is not None:
            body['text'] = config.text
        if config.target_lang is not None:
            body['target_lang'] = config.target_lang
        if config.source_lang is not None:
            body['source_lang'] = config.source_lang
        result = await self._request("POST", base + f"/ai/run/{config.model_name}", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "run_ai_translation"
        return result

    async def _convert_file_to_markdown(self, config: CloudflareConvertFileToMarkdownConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        async with guarded_async_client(timeout=120) as client:
            resp = await client.get(config.file_url)
            resp.raise_for_status()
            file_bytes = resp.content
        filename = config.file_name or config.file_url.split("?")[0].rstrip("/").split("/")[-1] or "file"
        files = {"files": (filename, file_bytes)}
        result = await self._request("POST", base + "/ai/tomarkdown", creds, files=files)
        if result["status"] == "success":
            result["action"] = "convert_file_to_markdown"
        return result

    # ── Analytics Engine SQL ──
    async def _get_analytics_engine_dataset_schema(self, config: CloudflareGetAnalyticsEngineDatasetSchemaConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        sql = f"SELECT * FROM {config.dataset_name} LIMIT 1"
        if config.format:
            sql += f" FORMAT {config.format}"
        result = await self._request("POST", base + "/analytics_engine/sql", creds, data=sql)
        if result["status"] == "success":
            result["action"] = "get_analytics_engine_dataset_schema"
        return result

    async def _get_analytics_engine_event_count(self, config: CloudflareGetAnalyticsEngineEventCountConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        conditions = []
        if config.where:
            conditions.append(f"({config.where})")
        if config.start_time:
            conditions.append(f"timestamp >= toDateTime('{config.start_time}')")
        if config.end_time:
            conditions.append(f"timestamp <= toDateTime('{config.end_time}')")
        sql = f"SELECT sum(_sample_interval) AS event_count FROM {config.dataset_name}"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        if config.format:
            sql += f" FORMAT {config.format}"
        result = await self._request("POST", base + "/analytics_engine/sql", creds, data=sql)
        if result["status"] == "success":
            result["action"] = "get_analytics_engine_event_count"
        return result

    async def _list_analytics_engine_datasets(self, config: CloudflareListAnalyticsEngineDatasetsConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        sql = "SHOW TABLES"
        if config.format:
            sql += f" FORMAT {config.format}"
        result = await self._request("POST", base + "/analytics_engine/sql", creds, data=sql)
        if result["status"] == "success":
            result["action"] = "list_analytics_engine_datasets"
        return result

    async def _list_analytics_engine_timezones(self, config: CloudflareListAnalyticsEngineTimezonesConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        sql = "SHOW TIMEZONES"
        if config.format:
            sql += f" FORMAT {config.format}"
        result = await self._request("POST", base + "/analytics_engine/sql", creds, data=sql)
        if result["status"] == "success":
            result["action"] = "list_analytics_engine_timezones"
        return result

    async def _query_analytics_engine_aggregated(self, config: CloudflareQueryAnalyticsEngineAggregatedConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        sql = f"SELECT {config.select_columns} FROM {config.dataset_name}"
        conditions = []
        if config.where:
            conditions.append(f"({config.where})")
        if config.start_time:
            conditions.append(f"timestamp >= toDateTime('{config.start_time}')")
        if config.end_time:
            conditions.append(f"timestamp <= toDateTime('{config.end_time}')")
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        if config.group_by:
            sql += f" GROUP BY {config.group_by}"
        if config.order_by:
            sql += f" ORDER BY {config.order_by}"
        sql += f" LIMIT {int(config.limit) if config.limit else 100}"
        if config.format:
            sql += f" FORMAT {config.format}"
        result = await self._request("POST", base + "/analytics_engine/sql", creds, data=sql)
        if result["status"] == "success":
            result["action"] = "query_analytics_engine_aggregated"
        return result

    async def _query_analytics_engine_raw(self, config: CloudflareQueryAnalyticsEngineRawConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        columns = config.columns or "*"
        sql = f"SELECT {columns} FROM {config.dataset_name}"
        conditions = []
        if config.where:
            conditions.append(f"({config.where})")
        if config.start_time:
            conditions.append(f"timestamp >= toDateTime('{config.start_time}')")
        if config.end_time:
            conditions.append(f"timestamp <= toDateTime('{config.end_time}')")
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        if config.order_by:
            sql += f" ORDER BY {config.order_by}"
        sql += f" LIMIT {int(config.limit) if config.limit else 100}"
        if config.format:
            sql += f" FORMAT {config.format}"
        result = await self._request("POST", base + "/analytics_engine/sql", creds, data=sql)
        if result["status"] == "success":
            result["action"] = "query_analytics_engine_raw"
        return result

    async def _query_analytics_engine_timeseries(self, config: CloudflareQueryAnalyticsEngineTimeseriesConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        bucket = config.interval or "toStartOfHour(timestamp)"
        sql = f"SELECT {bucket} AS time_bucket, {config.metric_expression} FROM {config.dataset_name}"
        conditions = []
        if config.where:
            conditions.append(f"({config.where})")
        if config.start_time:
            conditions.append(f"timestamp >= toDateTime('{config.start_time}')")
        if config.end_time:
            conditions.append(f"timestamp <= toDateTime('{config.end_time}')")
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " GROUP BY time_bucket ORDER BY time_bucket"
        sql += f" LIMIT {int(config.limit) if config.limit else 100}"
        if config.format:
            sql += f" FORMAT {config.format}"
        result = await self._request("POST", base + "/analytics_engine/sql", creds, data=sql)
        if result["status"] == "success":
            result["action"] = "query_analytics_engine_timeseries"
        return result

    async def _query_analytics_engine_top_values(self, config: CloudflareQueryAnalyticsEngineTopValuesConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        sql = f"SELECT {config.column} AS value, sum(_sample_interval) AS event_count FROM {config.dataset_name}"
        conditions = []
        if config.where:
            conditions.append(f"({config.where})")
        if config.start_time:
            conditions.append(f"timestamp >= toDateTime('{config.start_time}')")
        if config.end_time:
            conditions.append(f"timestamp <= toDateTime('{config.end_time}')")
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += f" GROUP BY {config.column} ORDER BY event_count DESC"
        sql += f" LIMIT {int(config.limit) if config.limit else 10}"
        if config.format:
            sql += f" FORMAT {config.format}"
        result = await self._request("POST", base + "/analytics_engine/sql", creds, data=sql)
        if result["status"] == "success":
            result["action"] = "query_analytics_engine_top_values"
        return result

    async def _query_analytics_engine_weighted_avg(self, config: CloudflareQueryAnalyticsEngineWeightedAvgConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        avg_expr = f"sum(_sample_interval * {config.value_column}) / sum(_sample_interval) AS weighted_avg"
        select = f"{config.group_by}, {avg_expr}" if config.group_by else avg_expr
        sql = f"SELECT {select} FROM {config.dataset_name}"
        conditions = []
        if config.where:
            conditions.append(f"({config.where})")
        if config.start_time:
            conditions.append(f"timestamp >= toDateTime('{config.start_time}')")
        if config.end_time:
            conditions.append(f"timestamp <= toDateTime('{config.end_time}')")
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        if config.group_by:
            sql += f" GROUP BY {config.group_by}"
        sql += f" LIMIT {int(config.limit) if config.limit else 100}"
        if config.format:
            sql += f" FORMAT {config.format}"
        result = await self._request("POST", base + "/analytics_engine/sql", creds, data=sql)
        if result["status"] == "success":
            result["action"] = "query_analytics_engine_weighted_avg"
        return result

    # ── Log Explorer / Logpull / CMB ──
    async def _create_log_explorer_dataset(self, config: CloudflareCreateLogExplorerDatasetConfig, creds: CloudflareCredential) -> Dict:
        if config.zone_id:
            base = f"/zones/{config.zone_id}"
        else:
            base = await self._account_path(creds)
        body = {"dataset": config.dataset}
        if config.fields:
            body["fields"] = json.loads(config.fields)
        result = await self._request("POST", base + "/logs/explorer/datasets", creds, json=body)
        if result["status"] == "success":
            result["action"] = "create_log_explorer_dataset"
        return result

    async def _delete_cmb_config(self, config: CloudflareDeleteCMBConfigConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("DELETE", base + "/logs/control/cmb/config", creds)
        if result["status"] == "success":
            result["action"] = "delete_cmb_config"
        return result

    async def _get_cmb_config(self, config: CloudflareGetCMBConfigConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        result = await self._request("GET", base + "/logs/control/cmb/config", creds)
        if result["status"] == "success":
            result["action"] = "get_cmb_config"
        return result

    async def _get_log_explorer_dataset(self, config: CloudflareGetLogExplorerDatasetConfig, creds: CloudflareCredential) -> Dict:
        if config.zone_id:
            base = f"/zones/{config.zone_id}"
        else:
            base = await self._account_path(creds)
        result = await self._request("GET", base + f"/logs/explorer/datasets/{config.dataset_id}", creds)
        if result["status"] == "success":
            result["action"] = "get_log_explorer_dataset"
        return result

    async def _get_log_retention_flag(self, config: CloudflareGetLogRetentionFlagConfig, creds: CloudflareCredential) -> Dict:
        base = f"/zones/{config.zone_id}"
        result = await self._request("GET", base + "/logs/control/retention/flag", creds)
        if result["status"] == "success":
            result["action"] = "get_log_retention_flag"
        return result

    async def _get_logpull_fields(self, config: CloudflareGetLogpullFieldsConfig, creds: CloudflareCredential) -> Dict:
        base = f"/zones/{config.zone_id}"
        result = await self._request("GET", base + "/logs/received/fields", creds)
        if result["status"] == "success":
            result["action"] = "get_logpull_fields"
        return result

    async def _get_logpull_logs(self, config: CloudflareGetLogpullLogsConfig, creds: CloudflareCredential) -> Dict:
        base = f"/zones/{config.zone_id}"
        params: Dict[str, Any] = {}
        if config.start is not None:
            params['start'] = config.start
        if config.end is not None:
            params['end'] = config.end
        if config.fields is not None:
            params['fields'] = config.fields
        if config.count is not None:
            params['count'] = config.count
        if config.sample is not None:
            params['sample'] = config.sample
        if config.timestamps is not None:
            params['timestamps'] = config.timestamps
        result = await self._request("GET", base + "/logs/received", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_logpull_logs"
        return result

    async def _get_logpull_rayid(self, config: CloudflareGetLogpullRayIDConfig, creds: CloudflareCredential) -> Dict:
        base = f"/zones/{config.zone_id}"
        params: Dict[str, Any] = {}
        if config.fields is not None:
            params['fields'] = config.fields
        if config.timestamps is not None:
            params['timestamps'] = config.timestamps
        result = await self._request("GET", base + f"/logs/rayids/{config.ray_id}", creds, params=params)
        if result["status"] == "success":
            result["action"] = "get_logpull_rayid"
        return result

    async def _list_log_explorer_available_datasets(self, config: CloudflareListLogExplorerAvailableDatasetsConfig, creds: CloudflareCredential) -> Dict:
        if config.zone_id:
            base = f"/zones/{config.zone_id}"
        else:
            base = await self._account_path(creds)
        result = await self._request("GET", base + "/logs/explorer/datasets/available", creds)
        if result["status"] == "success":
            result["action"] = "list_log_explorer_available_datasets"
        return result

    async def _list_log_explorer_datasets(self, config: CloudflareListLogExplorerDatasetsConfig, creds: CloudflareCredential) -> Dict:
        if config.zone_id:
            base = f"/zones/{config.zone_id}"
        else:
            base = await self._account_path(creds)
        params = {}
        if config.include_zones is not None and config.include_zones != "":
            params["include_zones"] = config.include_zones == "true"
        result = await self._request("GET", base + "/logs/explorer/datasets", creds, params=params or None)
        if result["status"] == "success":
            result["action"] = "list_log_explorer_datasets"
        return result

    async def _query_log_explorer_sql(self, config: CloudflareQueryLogExplorerSQLConfig, creds: CloudflareCredential) -> Dict:
        if config.zone_id:
            base = f"/zones/{config.zone_id}"
        else:
            base = await self._account_path(creds)
        params = {"query": config.sql_query}
        result = await self._request("GET", base + "/logs/explorer/query/sql", creds, params=params)
        if result["status"] == "success":
            result["action"] = "query_log_explorer_sql"
        return result

    async def _update_cmb_config(self, config: CloudflareUpdateCMBConfigConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        body = {}
        if config.regions is not None and config.regions != "":
            body["regions"] = config.regions
        if config.allow_out_of_region_access is not None and config.allow_out_of_region_access != "":
            body["allow_out_of_region_access"] = config.allow_out_of_region_access == "true"
        result = await self._request("POST", base + "/logs/control/cmb/config", creds, json=body)
        if result["status"] == "success":
            result["action"] = "update_cmb_config"
        return result

    async def _update_log_explorer_dataset(self, config: CloudflareUpdateLogExplorerDatasetConfig, creds: CloudflareCredential) -> Dict:
        if config.zone_id:
            base = f"/zones/{config.zone_id}"
        else:
            base = await self._account_path(creds)
        body = {"enabled": config.enabled == "true"}
        if config.fields:
            body["fields"] = json.loads(config.fields)
        result = await self._request("PUT", base + f"/logs/explorer/datasets/{config.dataset_id}", creds, json=body)
        if result["status"] == "success":
            result["action"] = "update_log_explorer_dataset"
        return result

    async def _update_log_retention_flag(self, config: CloudflareUpdateLogRetentionFlagConfig, creds: CloudflareCredential) -> Dict:
        base = f"/zones/{config.zone_id}"
        body: Dict[str, Any] = {}
        if config.flag is not None:
            body['flag'] = (config.flag == "true")
        result = await self._request("POST", base + "/logs/control/retention/flag", creds, json=body or None)
        if result["status"] == "success":
            result["action"] = "update_log_retention_flag"
        return result

    # ── R2 Event Notifications ──
    async def _delete_r2_event_notification_rules(self, config: CloudflareDeleteR2EventNotificationRulesConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        path = f"{base}/event_notifications/r2/{config.bucket_name}/configuration/queues/{config.queue_id}"
        await self._ensure_fresh_token(creds)
        headers = self._get_headers(creds)
        if config.jurisdiction and config.jurisdiction != "default":
            headers["cf-r2-jurisdiction"] = config.jurisdiction
        url = f"{BASE_URL}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request("DELETE", url, headers=headers)
        try:
            data = response.json()
        except Exception:
            data = {"success": response.status_code < 300, "result": response.text}
        if not data.get("success", response.status_code < 300):
            errors = data.get("errors", [])
            error_msg = "; ".join(e.get("message", str(e)) for e in errors) if errors else response.text
            return {"status": "error", "error": error_msg, "status_code": response.status_code}
        result = {"status": "success", "result": data.get("result"), "result_info": data.get("result_info")}
        result["action"] = "delete_r2_event_notification_rules"
        return result

    async def _get_r2_event_notification_config(self, config: CloudflareGetR2EventNotificationConfigConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        path = f"{base}/event_notifications/r2/{config.bucket_name}/configuration"
        await self._ensure_fresh_token(creds)
        headers = self._get_headers(creds)
        if config.jurisdiction and config.jurisdiction != "default":
            headers["cf-r2-jurisdiction"] = config.jurisdiction
        url = f"{BASE_URL}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request("GET", url, headers=headers)
        try:
            data = response.json()
        except Exception:
            data = {"success": response.status_code < 300, "result": response.text}
        if not data.get("success", response.status_code < 300):
            errors = data.get("errors", [])
            error_msg = "; ".join(e.get("message", str(e)) for e in errors) if errors else response.text
            return {"status": "error", "error": error_msg, "status_code": response.status_code}
        result = {"status": "success", "result": data.get("result"), "result_info": data.get("result_info")}
        result["action"] = "get_r2_event_notification_config"
        return result

    async def _get_r2_event_notification_queue_rules(self, config: CloudflareGetR2EventNotificationQueueRulesConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        path = f"{base}/event_notifications/r2/{config.bucket_name}/configuration/queues/{config.queue_id}"
        await self._ensure_fresh_token(creds)
        headers = self._get_headers(creds)
        if config.jurisdiction and config.jurisdiction != "default":
            headers["cf-r2-jurisdiction"] = config.jurisdiction
        url = f"{BASE_URL}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request("GET", url, headers=headers)
        try:
            data = response.json()
        except Exception:
            data = {"success": response.status_code < 300, "result": response.text}
        if not data.get("success", response.status_code < 300):
            errors = data.get("errors", [])
            error_msg = "; ".join(e.get("message", str(e)) for e in errors) if errors else response.text
            return {"status": "error", "error": error_msg, "status_code": response.status_code}
        result = {"status": "success", "result": data.get("result"), "result_info": data.get("result_info")}
        result["action"] = "get_r2_event_notification_queue_rules"
        return result

    async def _put_r2_event_notification_rules(self, config: CloudflarePutR2EventNotificationRulesConfig, creds: CloudflareCredential) -> Dict:
        base = await self._account_path(creds)
        path = f"{base}/event_notifications/r2/{config.bucket_name}/configuration/queues/{config.queue_id}"
        rule = {"actions": [a.strip() for a in config.actions.split(",") if a.strip()]}
        if config.prefix:
            rule["prefix"] = config.prefix
        if config.suffix:
            rule["suffix"] = config.suffix
        if config.description:
            rule["description"] = config.description
        body = {"rules": [rule]}
        await self._ensure_fresh_token(creds)
        headers = self._get_headers(creds)
        if config.jurisdiction and config.jurisdiction != "default":
            headers["cf-r2-jurisdiction"] = config.jurisdiction
        url = f"{BASE_URL}{path}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request("PUT", url, headers=headers, json=body)
        try:
            data = response.json()
        except Exception:
            data = {"success": response.status_code < 300, "result": response.text}
        if not data.get("success", response.status_code < 300):
            errors = data.get("errors", [])
            error_msg = "; ".join(e.get("message", str(e)) for e in errors) if errors else response.text
            return {"status": "error", "error": error_msg, "status_code": response.status_code}
        result = {"status": "success", "result": data.get("result"), "result_info": data.get("result_info")}
        result["action"] = "put_r2_event_notification_rules"
        return result

    async def execute(self, inputs: Dict) -> Dict[str, Any]:
        start = time.time()
        try:
            node_config = self.config
            if node_config is None or not isinstance(node_config, CloudflareNodeConfig):
                return {"status": "error", "error": "No configuration provided"}

            config = node_config.config
            credentials = node_config.credentials

            if not credentials:
                return {
                    "status": "error",
                    "error": "Credentials are required. Please add your Cloudflare API Token in the node's Credentials tab.",
                }

            action = config.operation
            dispatch = {
                # DNS
                "list_dns_records": self._list_dns_records,
                "create_dns_record": self._create_dns_record,
                "get_dns_record": self._get_dns_record,
                "update_dns_record": self._update_dns_record,
                "delete_dns_record": self._delete_dns_record,
                # Zones
                "list_zones": self._list_zones,
                "get_zone": self._get_zone,
                "get_zone_settings": self._get_zone_settings,
                "update_zone_setting": self._update_zone_setting,
                "purge_zone_cache": self._purge_cache,
                # Workers
                "list_workers": self._list_workers,
                "get_worker": self._get_worker,
                "upload_worker_script": self._upload_worker,
                "delete_worker": self._delete_worker,
                "list_worker_routes": self._list_worker_routes,
                "create_worker_route": self._create_worker_route,
                "delete_worker_route": self._delete_worker_route,
                # Workers KV
                "list_kv_namespaces": self._list_kv_namespaces,
                "create_kv_namespace": self._create_kv_namespace,
                "delete_kv_namespace": self._delete_kv_namespace,
                "list_kv_keys": self._list_kv_keys,
                "read_kv_value": self._read_kv_value,
                "write_kv_value": self._write_kv_value,
                "delete_kv_value": self._delete_kv_value,
                "bulk_write_kv_pairs": self._bulk_write_kv,
                # D1
                "list_d1_databases": self._list_d1_databases,
                "get_d1_database": self._get_d1_database,
                "create_d1_database": self._create_d1_database,
                "delete_d1_database": self._delete_d1_database,
                "execute_d1_sql_query": self._query_d1_database,
                "export_d1_database_as_sql": self._export_d1_database,
                # R2
                "list_r2_buckets": self._list_r2_buckets,
                "get_r2_bucket": self._get_r2_bucket,
                "create_r2_bucket": self._create_r2_bucket,
                "delete_r2_bucket": self._delete_r2_bucket,
                # Pages
                "list_pages_projects": self._list_pages_projects,
                "get_pages_project": self._get_pages_project,
                "delete_pages_project": self._delete_pages_project,
                "list_pages_deployments": self._list_pages_deployments,
                "get_pages_deployment": self._get_pages_deployment,
                "delete_pages_deployment": self._delete_pages_deployment,
                # Stream
                "list_stream_videos": self._list_stream_videos,
                "get_stream_video": self._get_stream_video,
                "delete_stream_video": self._delete_stream_video,
                "get_stream_video_embed_code": self._get_stream_embed,
                "list_stream_live_inputs": self._list_stream_live_inputs,
                "create_stream_live_input": self._create_stream_live_input,
                "delete_stream_live_input": self._delete_stream_live_input,
                # Stream Extended
                "create_stream_upload_url": self._create_stream_upload_url,
                "create_stream_signed_url": self._create_stream_signed_url,
                "list_stream_signing_keys": self._list_stream_signing_keys,
                "create_stream_signing_key": self._create_stream_signing_key,
                "delete_stream_signing_key": self._delete_stream_signing_key,
                "list_stream_captions": self._list_stream_captions,
                "upload_stream_caption": self._upload_stream_caption,
                "delete_stream_caption": self._delete_stream_caption,
                "list_stream_watermarks": self._list_stream_watermarks,
                "create_stream_watermark": self._create_stream_watermark,
                "get_stream_watermark": self._get_stream_watermark,
                "delete_stream_watermark": self._delete_stream_watermark,
                "list_stream_audio_tracks": self._list_stream_audio_tracks,
                "add_stream_audio_track": self._add_stream_audio_track,
                "edit_stream_audio_track": self._edit_stream_audio_track,
                "delete_stream_audio_track": self._delete_stream_audio_track,
                "update_stream_video": self._update_stream_video,
                # Images
                "list_images": self._list_images,
                "get_image": self._get_image,
                "delete_image": self._delete_image,
                "get_image_usage_statistics": self._get_images_stats,
                "create_image_direct_upload_url": self._create_image_direct_upload,
                # Firewall / WAF
                "list_firewall_rules": self._list_firewall_rules,
                "create_firewall_rule": self._create_firewall_rule,
                "delete_firewall_rule": self._delete_firewall_rule,
                "list_zone_waf_packages": self._list_waf_packages,
                # Access
                "list_access_applications": self._list_access_applications,
                "get_access_application": self._get_access_application,
                "create_access_application": self._create_access_application,
                "delete_access_application": self._delete_access_application,
                "list_access_application_policies": self._list_access_policies,
                # Tunnels
                "list_tunnels": self._list_tunnels,
                "get_tunnel": self._get_tunnel,
                "create_tunnel": self._create_tunnel,
                "delete_tunnel": self._delete_tunnel,
                "get_tunnel_token": self._get_tunnel_token,
                # Email Routing
                "get_email_routing_settings": self._get_email_routing,
                "list_email_routing_rules": self._list_email_routing_rules,
                "create_email_routing_rule": self._create_email_routing_rule,
                "delete_email_routing_rule": self._delete_email_routing_rule,
                "list_email_routing_destination_addresses": self._list_email_routing_addresses,
                # Queues
                "list_queues": self._list_queues,
                "get_queue": self._get_queue,
                "create_queue": self._create_queue,
                "delete_queue": self._delete_queue,
                "send_queue_message": self._send_queue_message,
                "pull_queue_messages": self._pull_queue_messages,
                # Workers AI
                "run_workers_ai_inference": self._run_ai_model,
                "list_workers_ai_models": self._list_ai_models,
                # Vectorize
                "list_vectorize_indexes": self._list_vectorize_indexes,
                "get_vectorize_index": self._get_vectorize_index,
                "create_vectorize_index": self._create_vectorize_index,
                "delete_vectorize_index": self._delete_vectorize_index,
                "upsert_vectors_to_index": self._upsert_vectors,
                "query_vectorize_index": self._query_vectors,
                "delete_vectors_from_index": self._delete_vectors,
                # Load Balancing
                "list_load_balancers": self._list_load_balancers,
                "get_load_balancer": self._get_load_balancer,
                "create_load_balancer": self._create_load_balancer,
                "delete_load_balancer": self._delete_load_balancer,
                "list_load_balancer_pools": self._list_lb_pools,
                "create_load_balancer_pool": self._create_lb_pool,
                # SSL / TLS
                "get_zone_ssl_settings": self._get_ssl_settings,
                "list_zone_ssl_certificates": self._list_ssl_certificates,
                # Analytics
                "get_zone_analytics": self._get_zone_analytics,
                # Workers - Secrets
                "list_worker_secrets": self._list_worker_secrets,
                "put_worker_secret": self._put_worker_secret,
                "delete_worker_secret": self._delete_worker_secret,
                "bulk_upsert_worker_secrets": self._bulk_upsert_worker_secrets,
                # Workers - Cron Triggers
                "get_worker_cron_triggers": self._get_worker_cron_triggers,
                "update_worker_cron_triggers": self._update_worker_cron_triggers,
                # Workers - Durable Objects
                "list_durable_object_namespaces": self._list_durable_object_namespaces,
                "list_durable_objects": self._list_durable_objects,
                # Workers - Routes
                "update_worker_route": self._update_worker_route,
                # Pipelines
                "list_pipelines": self._list_pipelines,
                "get_pipeline": self._get_pipeline,
                "create_pipeline": self._create_pipeline,
                "update_pipeline": self._update_pipeline,
                "delete_pipeline": self._delete_pipeline,
                # Secrets Store
                "list_secrets_stores": self._list_secrets_stores,
                "create_secrets_store": self._create_secrets_store,
                "delete_secrets_store": self._delete_secrets_store,
                "list_store_secrets": self._list_store_secrets,
                "get_store_secret": self._get_store_secret,
                "create_store_secret": self._create_store_secret,
                "update_store_secret": self._update_store_secret,
                "delete_store_secret": self._delete_store_secret,
                # Rulesets - Zone
                "list_zone_rulesets": self._list_zone_rulesets,
                "get_zone_ruleset": self._get_zone_ruleset,
                "create_zone_ruleset": self._create_zone_ruleset,
                "update_zone_ruleset": self._update_zone_ruleset,
                "delete_zone_ruleset": self._delete_zone_ruleset,
                "get_zone_ruleset_phase": self._get_zone_ruleset_phase,
                "update_zone_ruleset_phase": self._update_zone_ruleset_phase,
                "create_zone_ruleset_rule": self._create_zone_ruleset_rule,
                "delete_zone_ruleset_rule": self._delete_zone_ruleset_rule,
                # Rulesets - Account
                "list_account_rulesets": self._list_account_rulesets,
                "get_account_ruleset": self._get_account_ruleset,
                # Page Rules
                "list_page_rules": self._list_page_rules,
                "get_page_rule": self._get_page_rule,
                "create_page_rule": self._create_page_rule,
                "update_page_rule": self._update_page_rule,
                "delete_page_rule": self._delete_page_rule,
                # Rate Limiting
                "list_rate_limits": self._list_rate_limits,
                "get_rate_limit": self._get_rate_limit,
                "create_rate_limit": self._create_rate_limit,
                "update_rate_limit": self._update_rate_limit,
                "delete_rate_limit": self._delete_rate_limit,
                # Custom Hostnames
                "list_custom_hostnames": self._list_custom_hostnames,
                "get_custom_hostname": self._get_custom_hostname,
                "create_custom_hostname": self._create_custom_hostname,
                "update_custom_hostname": self._update_custom_hostname,
                "delete_custom_hostname": self._delete_custom_hostname,
                # Waiting Rooms
                "list_waiting_rooms": self._list_waiting_rooms,
                "get_waiting_room": self._get_waiting_room,
                "create_waiting_room": self._create_waiting_room,
                "update_waiting_room": self._update_waiting_room,
                "delete_waiting_room": self._delete_waiting_room,
                "get_waiting_room_status": self._get_waiting_room_status,
                "list_waiting_room_events": self._list_waiting_room_events,
                "create_waiting_room_event": self._create_waiting_room_event,
                # Logpush
                "list_account_logpush_jobs": self._list_account_logpush_jobs,
                "get_logpush_job": self._get_logpush_job,
                "create_logpush_job": self._create_logpush_job,
                "update_logpush_job": self._update_logpush_job,
                "delete_logpush_job": self._delete_logpush_job,
                "list_zone_logpush_jobs": self._list_zone_logpush_jobs,
                "create_zone_logpush_job": self._create_zone_logpush_job,
                "delete_zone_logpush_job": self._delete_zone_logpush_job,
                # Audit Logs
                "list_audit_logs": self._list_audit_logs,
                # Notifications / Alerting
                "list_available_alerts": self._list_available_alerts,
                "list_alert_policies": self._list_alert_policies,
                "get_alert_policy": self._get_alert_policy,
                "create_alert_policy": self._create_alert_policy,
                "update_alert_policy": self._update_alert_policy,
                "delete_alert_policy": self._delete_alert_policy,
                "list_notification_webhooks": self._list_notification_webhooks,
                "create_notification_webhook": self._create_notification_webhook,
                "update_notification_webhook": self._update_notification_webhook,
                "delete_notification_webhook": self._delete_notification_webhook,
                "get_notification_history": self._get_notification_history,
                # Health Checks
                "list_health_checks": self._list_health_checks,
                "get_health_check": self._get_health_check,
                "create_health_check": self._create_health_check,
                "update_health_check": self._update_health_check,
                "delete_health_check": self._delete_health_check,
                # Spectrum
                "list_spectrum_apps": self._list_spectrum_apps,
                "get_spectrum_app": self._get_spectrum_app,
                "create_spectrum_app": self._create_spectrum_app,
                "update_spectrum_app": self._update_spectrum_app,
                "delete_spectrum_app": self._delete_spectrum_app,
                # Snippets
                "list_snippets": self._list_snippets,
                "get_snippet": self._get_snippet,
                "put_snippet": self._put_snippet,
                "delete_snippet": self._delete_snippet,
                "list_snippet_rules": self._list_snippet_rules,
                # Zaraz
                "get_zaraz_config": self._get_zaraz_config,
                "update_zaraz_config": self._update_zaraz_config,
                "publish_zaraz_config": self._publish_zaraz_config,
                # Bot Management
                "get_bot_management": self._get_bot_management,
                "update_bot_management": self._update_bot_management,
                # Speed Observatory
                "list_observatory_pages": self._list_observatory_pages,
                "list_page_speed_tests": self._list_page_speed_tests,
                "create_page_speed_test": self._create_page_speed_test,
                "delete_page_speed_tests": self._delete_page_speed_tests,
                "get_speed_test_schedule": self._get_speed_test_schedule,
                # Web Analytics
                "list_web_analytics_sites": self._list_web_analytics_sites,
                "create_web_analytics_site": self._create_web_analytics_site,
                "get_web_analytics_site": self._get_web_analytics_site,
                "delete_web_analytics_site": self._delete_web_analytics_site,
                # Account Members
                "list_account_members": self._list_account_members,
                "get_account_member": self._get_account_member,
                "add_account_member": self._add_account_member,
                "update_account_member": self._update_account_member,
                "remove_account_member": self._remove_account_member,
                "list_account_roles": self._list_account_roles,
                # Tunnel Routes / Virtual Networks
                "list_tunnel_routes": self._list_tunnel_routes,
                "create_tunnel_route": self._create_tunnel_route,
                "update_tunnel_route": self._update_tunnel_route,
                "delete_tunnel_route": self._delete_tunnel_route,
                "list_virtual_networks": self._list_virtual_networks,
                "create_virtual_network": self._create_virtual_network,
                "get_virtual_network": self._get_virtual_network,
                "update_virtual_network": self._update_virtual_network,
                "delete_virtual_network": self._delete_virtual_network,
                # Load Balancer Extensions
                "update_load_balancer": self._update_load_balancer,
                "get_load_balancer_pool": self._get_load_balancer_pool,
                "update_load_balancer_pool": self._update_load_balancer_pool,
                "delete_load_balancer_pool": self._delete_load_balancer_pool,
                "list_load_balancer_monitors": self._list_load_balancer_monitors,
                "get_load_balancer_monitor": self._get_load_balancer_monitor,
                "create_load_balancer_monitor": self._create_load_balancer_monitor,
                "delete_load_balancer_monitor": self._delete_load_balancer_monitor,
                "get_load_balancer_pool_health": self._get_load_balancer_pool_health,
                # Access Extensions
                "create_access_policy": self._create_access_policy,
                "update_access_policy": self._update_access_policy,
                "delete_access_policy": self._delete_access_policy,
                "get_access_policy": self._get_access_policy,
                "list_access_groups": self._list_access_groups,
                "get_access_group": self._get_access_group,
                "create_access_group": self._create_access_group,
                "update_access_group": self._update_access_group,
                "delete_access_group": self._delete_access_group,
                "list_access_service_tokens": self._list_access_service_tokens,
                "create_access_service_token": self._create_access_service_token,
                "refresh_access_service_token": self._refresh_access_service_token,
                "delete_access_service_token": self._delete_access_service_token,
                # Tunnel Extensions
                "update_tunnel": self._update_tunnel,
                "get_tunnel_configuration": self._get_tunnel_configuration,
                "put_tunnel_configuration": self._put_tunnel_configuration,
                "list_tunnel_connections": self._list_tunnel_connections,
                # Email Routing Extensions
                "enable_email_routing": self._enable_email_routing,
                "disable_email_routing": self._disable_email_routing,
                "create_email_routing_destination": self._create_email_routing_destination,
                "delete_email_routing_destination": self._delete_email_routing_destination,
                # Queue Extensions
                "update_queue": self._update_queue,
                "acknowledge_queue_messages": self._acknowledge_queue_messages,
                "list_queue_consumers": self._list_queue_consumers,
                "create_queue_consumer": self._create_queue_consumer,
                "delete_queue_consumer": self._delete_queue_consumer,
                # SSL / TLS Extensions
                "update_zone_ssl_settings": self._update_zone_ssl_settings,
                "upload_ssl_certificate": self._upload_ssl_certificate,
                "delete_ssl_certificate": self._delete_ssl_certificate,
                # Pages Extensions
                "create_pages_project": self._create_pages_project,
                "retry_pages_deployment": self._retry_pages_deployment,
                # DNS Extensions
                "export_dns_records": self._export_dns_records,
                "get_dnssec": self._get_dnssec,
                "update_dnssec": self._update_dnssec,
                # R2 Object Operations
                "list_r2_objects": self._list_r2_objects,
                "get_r2_object": self._get_r2_object,
                "put_r2_object": self._put_r2_object,
                "delete_r2_object": self._delete_r2_object,
                "get_r2_presigned_url": self._get_r2_presigned_url,
                # Webhook Triggers
                "cloudflare_alert": self._handle_alert_trigger,
                "cloudflare_stream_event": self._handle_stream_event_trigger,
                "cloudflare_ddos_alert": self._handle_ddos_alert_trigger,
                "cloudflare_ssl_alert": self._handle_ssl_alert_trigger,
                "cloudflare_tunnel_alert": self._handle_tunnel_alert_trigger,
                "cloudflare_worker_alert": self._handle_worker_alert_trigger,
                "cloudflare_load_balancer_alert": self._handle_load_balancer_alert_trigger,
                "cloudflare_waiting_room_alert": self._handle_waiting_room_alert_trigger,
                "cloudflare_page_shield_alert": self._handle_page_shield_alert_trigger,
                "cloudflare_zero_trust_alert": self._handle_zero_trust_alert_trigger,
                "cloudflare_email_routing_alert": self._handle_email_routing_alert_trigger,
                "cloudflare_magic_transit_alert": self._handle_magic_transit_alert_trigger,
                # Poll Triggers
                "cloudflare_audit_log": self._poll_audit_logs,
                "cloudflare_r2_object_event": self._trigger_r2_object_event,
                "cloudflare_queue_delivery_event": self._trigger_queue_delivery_event,
                "cloudflare_worker_deployed": self._trigger_worker_deployed,
                "cloudflare_d1_new_rows": self._trigger_d1_new_rows,
                "cloudflare_kv_key_updated": self._trigger_kv_key_updated,
                # Zone Management extended
                "create_zone": self._create_zone,
                "delete_zone": self._delete_zone,
                "edit_zone": self._edit_zone,
                "zone_activation_check": self._zone_activation_check,
                # Rules Lists
                "list_rules_lists": self._list_rules_lists,
                "create_rules_list": self._create_rules_list,
                "get_rules_list": self._get_rules_list,
                "update_rules_list": self._update_rules_list,
                "delete_rules_list": self._delete_rules_list,
                "list_rules_list_items": self._list_rules_list_items,
                "create_rules_list_items": self._create_rules_list_items,
                "replace_rules_list_items": self._replace_rules_list_items,
                "delete_rules_list_items": self._delete_rules_list_items,
                "get_rules_list_operation": self._get_rules_list_operation,
                # Worker Versions & Deployments & Tails
                "list_worker_versions": self._list_worker_versions,
                "upload_worker_version": self._upload_worker_version,
                "get_worker_version": self._get_worker_version,
                "list_worker_deployments": self._list_worker_deployments,
                "create_worker_deployment": self._create_worker_deployment,
                "get_worker_deployment": self._get_worker_deployment,
                "list_worker_tails": self._list_worker_tails,
                "start_worker_tail": self._start_worker_tail,
                "delete_worker_tail": self._delete_worker_tail,
                # AI Gateway
                "list_ai_gateways": self._list_ai_gateways,
                "create_ai_gateway": self._create_ai_gateway,
                "get_ai_gateway": self._get_ai_gateway,
                "update_ai_gateway": self._update_ai_gateway,
                "delete_ai_gateway": self._delete_ai_gateway,
                "list_ai_gateway_logs": self._list_ai_gateway_logs,
                "get_ai_gateway_log": self._get_ai_gateway_log,
                "delete_ai_gateway_logs": self._delete_ai_gateway_logs,
                "get_ai_gateway_log_request": self._get_ai_gateway_log_request,
                "get_ai_gateway_log_response": self._get_ai_gateway_log_response,
                "list_ai_gateway_datasets": self._list_ai_gateway_datasets,
                "create_ai_gateway_dataset": self._create_ai_gateway_dataset,
                "delete_ai_gateway_dataset": self._delete_ai_gateway_dataset,
                # Images extended
                "list_image_variants": self._list_image_variants,
                "create_image_variant": self._create_image_variant,
                "get_image_variant": self._get_image_variant,
                "update_image_variant": self._update_image_variant,
                "delete_image_variant": self._delete_image_variant,
                "list_image_signing_keys": self._list_image_signing_keys,
                "create_image_signing_key": self._create_image_signing_key,
                "delete_image_signing_key": self._delete_image_signing_key,
                "update_image_metadata": self._update_image_metadata,
                # D1 extended
                "list_d1_tables": self._list_d1_tables,
                "import_d1_data": self._import_d1_data,
                "get_d1_database_import_status": self._get_d1_import_status,
                "execute_d1_raw_query": self._execute_d1_raw_query,
                # Zero Trust Gateway
                "get_gateway_configuration": self._get_gateway_configuration,
                "update_gateway_configuration": self._update_gateway_configuration,
                "list_gateway_rules": self._list_gateway_rules,
                "create_gateway_rule": self._create_gateway_rule,
                "get_gateway_rule": self._get_gateway_rule,
                "update_gateway_rule": self._update_gateway_rule,
                "delete_gateway_rule": self._delete_gateway_rule,
                "list_gateway_lists": self._list_gateway_lists,
                "create_gateway_list": self._create_gateway_list,
                "get_gateway_list": self._get_gateway_list,
                "update_gateway_list": self._update_gateway_list,
                "delete_gateway_list": self._delete_gateway_list,
                "list_gateway_list_items": self._list_gateway_list_items,
                "list_gateway_locations": self._list_gateway_locations,
                "create_gateway_location": self._create_gateway_location,
                "get_gateway_location": self._get_gateway_location,
                "delete_gateway_location": self._delete_gateway_location,
                # Page Shield
                "get_page_shield_settings": self._get_page_shield_settings,
                "update_page_shield_settings": self._update_page_shield_settings,
                "list_page_shield_scripts": self._list_page_shield_scripts,
                "get_page_shield_script": self._get_page_shield_script,
                "list_page_shield_connections": self._list_page_shield_connections,
                "get_page_shield_connection": self._get_page_shield_connection,
                "list_page_shield_policies": self._list_page_shield_policies,
                "create_page_shield_policy": self._create_page_shield_policy,
                "delete_page_shield_policy": self._delete_page_shield_policy,
                # Cache extended
                "get_cache_reserve": self._get_cache_reserve,
                "update_cache_reserve": self._update_cache_reserve,
                "get_argo_smart_routing": self._get_argo_smart_routing,
                "update_argo_smart_routing": self._update_argo_smart_routing,
                "get_tiered_caching": self._get_tiered_caching,
                "update_tiered_caching": self._update_tiered_caching,
                "purge_cache_everything": self._purge_cache_everything,
                "get_zone_settings_all": self._get_zone_settings_all,
                # R2 extended
                "get_r2_cors_policy": self._get_r2_cors_policy,
                "put_r2_cors_policy": self._put_r2_cors_policy,
                "delete_r2_cors_policy": self._delete_r2_cors_policy,
                "get_r2_lifecycle_rules": self._get_r2_lifecycle_rules,
                "put_r2_lifecycle_rules": self._put_r2_lifecycle_rules,
                "delete_r2_lifecycle_rules": self._delete_r2_lifecycle_rules,
                "list_r2_custom_domains": self._list_r2_custom_domains,
                "create_r2_custom_domain": self._create_r2_custom_domain,
                "update_r2_custom_domain": self._update_r2_custom_domain,
                "delete_r2_custom_domain": self._delete_r2_custom_domain,
                "get_r2_managed_domain": self._get_r2_managed_domain,
                "update_r2_managed_domain": self._update_r2_managed_domain,
                "get_r2_bucket_details": self._get_r2_bucket_details,
                "update_r2_bucket": self._update_r2_bucket,
                # Poll Triggers (dispatched as no-arg callables)
                "cloudflare_queue_message": self._trigger_queue_message,
                "cloudflare_pages_deploy": self._trigger_pages_deploy,
                "cloudflare_r2_new_object": self._trigger_r2_new_object,
                "cloudflare_dns_change": self._trigger_dns_change,
                "cloudflare_health_check_status": self._trigger_health_check_status,
                "cloudflare_worker_deployed": self._trigger_worker_deployed,
                "cloudflare_d1_new_rows": self._trigger_d1_new_rows,
                "cloudflare_kv_key_updated": self._trigger_kv_key_updated,
                # Access
                "list_identity_providers": self._list_identity_providers,
                "get_identity_provider": self._get_identity_provider,
                "create_identity_provider": self._create_identity_provider,
                "update_identity_provider": self._update_identity_provider,
                "delete_identity_provider": self._delete_identity_provider,
                "list_access_users": self._list_access_users,
                "get_access_user": self._get_access_user,
                "list_access_user_sessions": self._list_access_user_sessions,
                "revoke_access_user_session": self._revoke_access_user_session,
                "get_access_organization": self._get_access_organization,
                "update_access_organization": self._update_access_organization,
                "create_access_key_rotation": self._create_access_key_rotation,
                # Secondary DNS
                "get_secondary_dns_config": self._get_secondary_dns_config,
                "update_secondary_dns_config": self._update_secondary_dns_config,
                "list_secondary_dns_peers": self._list_secondary_dns_peers,
                "create_secondary_dns_peer": self._create_secondary_dns_peer,
                "get_secondary_dns_peer": self._get_secondary_dns_peer,
                "update_secondary_dns_peer": self._update_secondary_dns_peer,
                "delete_secondary_dns_peer": self._delete_secondary_dns_peer,
                # Analytics Engine
                "query_analytics_engine": self._query_analytics_engine,
                # Regional Tiered Cache
                "get_regional_tiered_cache": self._get_regional_tiered_cache,
                "update_regional_tiered_cache": self._update_regional_tiered_cache,
                # Vectorize extended
                "get_vectorize_index_info": self._get_vectorize_index_info,
                "list_vectorize_metadata_indexes": self._list_vectorize_metadata_indexes,
                "create_vectorize_metadata_index": self._create_vectorize_metadata_index,
                "delete_vectorize_metadata_index": self._delete_vectorize_metadata_index,
                "get_vectorize_vectors_by_ids": self._get_vectorize_vectors_by_ids,
                # Fonts
                "get_fonts_settings": self._get_fonts_settings,
                "update_fonts_settings": self._update_fonts_settings,
                # NEL
                "get_nel_settings": self._get_nel_settings,
                "update_nel_settings": self._update_nel_settings,
                # API Shield
                "get_api_shield_settings": self._get_api_shield_settings,
                "update_api_shield_settings": self._update_api_shield_settings,
                "list_api_shield_endpoints": self._list_api_shield_endpoints,
                "create_api_shield_endpoint": self._create_api_shield_endpoint,
                # WAF extended
                "get_waf_package": self._get_waf_package,
                "list_waf_package_rule_groups": self._list_waf_package_rule_groups,
                "list_waf_package_rules": self._list_waf_package_rules,
                "update_waf_rule": self._update_waf_rule,
                # Early Hints
                "get_early_hints_setting": self._get_early_hints_setting,
                "update_early_hints_setting": self._update_early_hints_setting,
                # HTTP/3
                "get_http3_setting": self._get_http3_setting,
                "update_http3_setting": self._update_http3_setting,
                # Brotli
                "get_brotli_setting": self._get_brotli_setting,
                "update_brotli_setting": self._update_brotli_setting,

                # ── Restored implemented families ──
                # Intel / Security Center
                "add_intel_feed_permission": self._add_intel_feed_permission,
                "create_intel_indicator_feed": self._create_intel_indicator_feed,
                "create_intel_miscategorization": self._create_intel_miscategorization,
                "dismiss_attack_surface_issue": self._dismiss_attack_surface_issue,
                "get_attack_surface_issues_by_severity": self._get_attack_surface_issues_by_severity,
                "get_attack_surface_issues_by_type": self._get_attack_surface_issues_by_type,
                "get_intel_asn": self._get_intel_asn,
                "get_intel_asn_subnets": self._get_intel_asn_subnets,
                "get_intel_dns": self._get_intel_dns,
                "get_intel_domain": self._get_intel_domain,
                "get_intel_domain_bulk": self._get_intel_domain_bulk,
                "get_intel_domain_history": self._get_intel_domain_history,
                "get_intel_indicator_feed": self._get_intel_indicator_feed,
                "get_intel_indicator_feed_data": self._get_intel_indicator_feed_data,
                "get_intel_ip": self._get_intel_ip,
                "get_intel_whois": self._get_intel_whois,
                "list_attack_surface_issue_types": self._list_attack_surface_issue_types,
                "list_attack_surface_issues": self._list_attack_surface_issues,
                "list_intel_feed_permissions": self._list_intel_feed_permissions,
                "list_intel_indicator_feeds": self._list_intel_indicator_feeds,
                "list_intel_sinkholes": self._list_intel_sinkholes,
                "remove_intel_feed_permission": self._remove_intel_feed_permission,
                "update_intel_indicator_feed": self._update_intel_indicator_feed,
                # Addressing / BYOIP
                "add_ip_to_address_map": self._add_ip_to_address_map,
                "add_zone_to_address_map": self._add_zone_to_address_map,
                "create_address_map": self._create_address_map,
                "create_ip_prefix": self._create_ip_prefix,
                "create_prefix_delegation": self._create_prefix_delegation,
                "create_prefix_service_binding": self._create_prefix_service_binding,
                "create_regional_hostname": self._create_regional_hostname,
                "delete_address_map": self._delete_address_map,
                "delete_ip_prefix": self._delete_ip_prefix,
                "delete_prefix_delegation": self._delete_prefix_delegation,
                "delete_prefix_service_binding": self._delete_prefix_service_binding,
                "delete_regional_hostname": self._delete_regional_hostname,
                "download_loa_document": self._download_loa_document,
                "get_address_map": self._get_address_map,
                "get_bgp_prefix_advertisement_status": self._get_bgp_prefix_advertisement_status,
                "get_ip_prefix": self._get_ip_prefix,
                "get_prefix_service_binding": self._get_prefix_service_binding,
                "get_regional_hostname": self._get_regional_hostname,
                "list_address_maps": self._list_address_maps,
                "list_addressing_services": self._list_addressing_services,
                "list_bgp_prefixes": self._list_bgp_prefixes,
                "list_ip_prefixes": self._list_ip_prefixes,
                "list_prefix_delegations": self._list_prefix_delegations,
                "list_prefix_service_bindings": self._list_prefix_service_bindings,
                "list_regional_hostname_regions": self._list_regional_hostname_regions,
                "list_regional_hostnames": self._list_regional_hostnames,
                "remove_ip_from_address_map": self._remove_ip_from_address_map,
                "remove_zone_from_address_map": self._remove_zone_from_address_map,
                "update_address_map": self._update_address_map,
                "update_bgp_prefix": self._update_bgp_prefix,
                "update_bgp_prefix_advertisement": self._update_bgp_prefix_advertisement,
                "update_ip_prefix": self._update_ip_prefix,
                "update_regional_hostname": self._update_regional_hostname,
                "upload_loa_document": self._upload_loa_document,
                # Magic Transit
                "create_magic_app": self._create_magic_app,
                "create_magic_gre_tunnel": self._create_magic_gre_tunnel,
                "delete_magic_app": self._delete_magic_app,
                "delete_magic_gre_tunnel": self._delete_magic_gre_tunnel,
                "get_magic_cf_interconnect": self._get_magic_cf_interconnect,
                "get_magic_gre_tunnel": self._get_magic_gre_tunnel,
                "list_magic_apps": self._list_magic_apps,
                "list_magic_cf_interconnects": self._list_magic_cf_interconnects,
                "list_magic_gre_tunnels": self._list_magic_gre_tunnels,
                "update_magic_app": self._update_magic_app,
                "update_magic_cf_interconnect": self._update_magic_cf_interconnect,
                "update_magic_gre_tunnel": self._update_magic_gre_tunnel,
                # Calls / Realtime
                "create_calls_app": self._create_calls_app,
                "create_calls_turn_key": self._create_calls_turn_key,
                "delete_calls_app": self._delete_calls_app,
                "delete_calls_turn_key": self._delete_calls_turn_key,
                "get_calls_app": self._get_calls_app,
                "get_calls_turn_key": self._get_calls_turn_key,
                "list_calls_apps": self._list_calls_apps,
                "list_calls_turn_keys": self._list_calls_turn_keys,
                "update_calls_app": self._update_calls_app,
                "update_calls_turn_key": self._update_calls_turn_key,
                # Radar AI
                "get_radar_ai_bots_summary": self._get_radar_ai_bots_summary,
                "get_radar_ai_bots_summary_by_crawl_purpose": self._get_radar_ai_bots_summary_by_crawl_purpose,
                "get_radar_ai_bots_summary_by_industry": self._get_radar_ai_bots_summary_by_industry,
                "get_radar_ai_bots_summary_by_user_agent": self._get_radar_ai_bots_summary_by_user_agent,
                "get_radar_ai_bots_timeseries": self._get_radar_ai_bots_timeseries,
                "get_radar_ai_bots_timeseries_by_user_agent": self._get_radar_ai_bots_timeseries_by_user_agent,
                "get_radar_ai_bots_timeseries_groups": self._get_radar_ai_bots_timeseries_groups,
                "get_radar_ai_inference_summary_by_model": self._get_radar_ai_inference_summary_by_model,
                "get_radar_ai_inference_summary_by_task": self._get_radar_ai_inference_summary_by_task,
                "get_radar_ai_inference_timeseries_by_model": self._get_radar_ai_inference_timeseries_by_model,
                "get_radar_ai_inference_timeseries_by_task": self._get_radar_ai_inference_timeseries_by_task,
                # URL Scanner
                "get_url_scan": self._get_url_scan,
                "get_url_scan_dom": self._get_url_scan_dom,
                "get_url_scan_har": self._get_url_scan_har,
                "get_url_scan_screenshot": self._get_url_scan_screenshot,
                "bulk_submit_url_scans": self._bulk_submit_url_scans,
                "search_url_scans": self._search_url_scans,
                "submit_url_scan": self._submit_url_scan,
                # Bot Management
                "get_bot_management_analytics": self._get_bot_management_analytics,
                "get_bot_score_thresholds": self._get_bot_score_thresholds,
                "update_bot_score_thresholds": self._update_bot_score_thresholds,
                "configure_javascript_detection": self._configure_javascript_detection,
                "list_bot_feedback_reports": self._list_bot_feedback_reports,
                "submit_bot_feedback": self._submit_bot_feedback,
                # Workers AI
                "create_ai_finetune": self._create_ai_finetune,
                "get_ai_model_schema": self._get_ai_model_schema,
                "list_ai_authors": self._list_ai_authors,
                "list_ai_finetunes": self._list_ai_finetunes,
                "list_ai_tasks": self._list_ai_tasks,
                "list_public_ai_finetunes": self._list_public_ai_finetunes,
                "run_ai_image_classification": self._run_ai_image_classification,
                "run_ai_object_detection": self._run_ai_object_detection,
                "run_ai_speech_to_text": self._run_ai_speech_to_text,
                "run_ai_summarization": self._run_ai_summarization,
                "run_ai_text_embeddings": self._run_ai_text_embeddings,
                "run_ai_text_generation": self._run_ai_text_generation,
                "run_ai_text_to_image": self._run_ai_text_to_image,
                "run_ai_translation": self._run_ai_translation,
                "convert_file_to_markdown": self._convert_file_to_markdown,
                # Analytics Engine SQL
                "get_analytics_engine_dataset_schema": self._get_analytics_engine_dataset_schema,
                "get_analytics_engine_event_count": self._get_analytics_engine_event_count,
                "list_analytics_engine_datasets": self._list_analytics_engine_datasets,
                "list_analytics_engine_timezones": self._list_analytics_engine_timezones,
                "query_analytics_engine_aggregated": self._query_analytics_engine_aggregated,
                "query_analytics_engine_raw": self._query_analytics_engine_raw,
                "query_analytics_engine_timeseries": self._query_analytics_engine_timeseries,
                "query_analytics_engine_top_values": self._query_analytics_engine_top_values,
                "query_analytics_engine_weighted_avg": self._query_analytics_engine_weighted_avg,
                # Log Explorer / Logpull / CMB
                "create_log_explorer_dataset": self._create_log_explorer_dataset,
                "delete_cmb_config": self._delete_cmb_config,
                "get_cmb_config": self._get_cmb_config,
                "get_log_explorer_dataset": self._get_log_explorer_dataset,
                "get_log_retention_flag": self._get_log_retention_flag,
                "get_logpull_fields": self._get_logpull_fields,
                "get_logpull_logs": self._get_logpull_logs,
                "get_logpull_rayid": self._get_logpull_rayid,
                "list_log_explorer_available_datasets": self._list_log_explorer_available_datasets,
                "list_log_explorer_datasets": self._list_log_explorer_datasets,
                "query_log_explorer_sql": self._query_log_explorer_sql,
                "update_cmb_config": self._update_cmb_config,
                "update_log_explorer_dataset": self._update_log_explorer_dataset,
                "update_log_retention_flag": self._update_log_retention_flag,
                # R2 Event Notifications
                "delete_r2_event_notification_rules": self._delete_r2_event_notification_rules,
                "get_r2_event_notification_config": self._get_r2_event_notification_config,
                "get_r2_event_notification_queue_rules": self._get_r2_event_notification_queue_rules,
                "put_r2_event_notification_rules": self._put_r2_event_notification_rules,
            }

            handler = dispatch.get(action)
            if not handler:
                return {"status": "error", "error": f"Unknown action: {action}"}

            result = await handler(config, credentials)
            result["elapsed_ms"] = round((time.time() - start) * 1000, 1)
            return result

        except ValueError as e:
            return {"status": "error", "error": str(e)}
        except Exception as e:
            logger.exception(f"[CloudflareNode] Unexpected error: {e}")
            return {"status": "error", "error": str(e)}
