"""Linkly v1.3: one published API operation per workflow operation.

Lists return one page and preserve the provider's pagination metadata. Writes
are sent once, without automatic retries. API keys use the documented query auth.
Contract: https://api.linklyhq.com/api/openapi
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, unquote, urlsplit

import re

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class LinklyAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Linkly API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://linklyhq.com/support/api",
            "x-credential-instructions": "In Linkly, open Settings, then Account Settings, and copy your API key here. NoClick uses it to list your workspaces and access the workspace you select in each operation.",
        },
    )
    credential_type: Literal["linkly_api_key"] = Field(
        "linkly_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API key",
        min_length=1,
        max_length=4096,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Paste only the API key")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator(
        "workspace_id",
        "domain_id",
        "id",
        "link_id",
        "hook_id",
        mode="before",
        check_fields=False,
    )
    @classmethod
    def path_values(cls, value, info):
        if (
            info.field_name in {"workspace_id", "domain_id", "id", "link_id"}
            and value is not None
        ):
            if isinstance(value, bool) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,128}", str(value)
            ):
                raise ValueError("Use a Linkly resource ID")
        if info.field_name == "hook_id" and value is not None:
            # The published parameter example is already URL-encoded. Accept
            # that or a pasted webhook URL, encoding exactly once at dispatch.
            value = unquote(value) if "://" not in value else value
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("Paste the webhook URL or its URL-encoded form")
        return value


class LinklyRedirectRule(_Input):
    matches: str | None = Field(None, min_length=1, max_length=10000)
    percentage: int | None = Field(None)
    url: str | None = Field(None, min_length=1, max_length=10000)
    what: str | None = Field(None, min_length=1, max_length=10000)


class LinklyLinkFilter(_Input):
    domain: str | None = Field(None, min_length=1, max_length=10000)
    slug: str | None = Field(None, min_length=1, max_length=10000)
    utm_campaign: str | None = Field(None, min_length=1, max_length=10000)
    utm_content: str | None = Field(None, min_length=1, max_length=10000)
    utm_medium: str | None = Field(None, min_length=1, max_length=10000)
    utm_source: str | None = Field(None, min_length=1, max_length=10000)
    utm_term: str | None = Field(None, min_length=1, max_length=10000)


class LinklyListConversionsConfig(_Input):
    "List conversions; pass since, then the last conversion ID as after while has_more is true."
    operation: Literal["list_conversions"] = Field(
        "list_conversions", json_schema_extra={"ui:hidden": True}
    )
    workspace_id: str = Field(
        ...,
        description="The ID of the workspace. Required when authenticating with an API key. Omit it with an OAuth token, which is bound to one workspace.",
        examples=["42"],
        min_length=1,
        max_length=10000,
    )
    limit: int | None = Field(
        None,
        description="Maximum conversions to return (1–1000, default 100)",
        examples=[100],
        ge=1,
        le=1000,
    )
    after: str | None = Field(
        None,
        description="Return conversions recorded after this conversion `id`, oldest first. Use the `id` of the last conversion on the previous page.",
        examples=["01KYPH20SEJY4HQSCPMWW60QE0"],
        min_length=1,
        max_length=10000,
    )
    since: str | None = Field(
        None,
        description="Return conversions Linkly recorded at or after this time, oldest first. An ISO 8601 date (`2026-07-29`) or date-time (`2026-07-29T10:30:00Z`); a date-time without an offset is read as UTC.",
        examples=["2026-07-29T10:30:00Z"],
        min_length=1,
        max_length=10000,
    )


class LinklyCreateConversionConfig(_Input):
    "Report a conversion; an unattributed 202 response is discarded, not stored. Preserve attributed and event_id from the response."
    operation: Literal["create_conversion"] = Field(
        "create_conversion", json_schema_extra={"ui:hidden": True}
    )
    workspace_id: str = Field(
        ...,
        description="The ID of the workspace. Required when authenticating with an API key. Omit it with an OAuth token, which is bound to one workspace.",
        examples=["42"],
        min_length=1,
        max_length=10000,
    )
    amount_cents: int | None = Field(
        None,
        description="Value in the smallest currency unit. May be negative to record a refund or chargeback, which nets against earlier revenue.",
        examples=[4999],
    )
    country: str | None = Field(
        None,
        description="Two-letter country code for the conversion. Inferred for browser-side calls; supply it explicitly from a server-side integration, where the connecting address is your own infrastructure rather than the customer's.",
        examples=["US"],
        min_length=1,
        max_length=10000,
    )
    currency: str | None = Field(
        None,
        description="ISO 4217 currency code. Defaults to USD.",
        examples=["USD"],
        min_length=1,
        max_length=10000,
    )
    event_id: str | None = Field(
        None,
        description="Your identifier for this event. Used as an idempotency key — reporting the same value twice will not create a second conversion. Applies to any event type, not just purchases.",
        examples=["shopify-1234"],
        min_length=1,
        max_length=10000,
    )
    event_name: str = Field(
        ...,
        description="What happened, e.g. `purchase`, `signup`, `trial_started`",
        examples=["purchase"],
        min_length=1,
        max_length=10000,
    )
    event_type: Literal["lead", "sale", "custom"] | None = Field(
        None,
        description="Coarse type driving the funnel. `lead` establishes customer identity, `sale` records revenue. Defaults to `custom`.",
        examples=["sale"],
    )
    external_id: str | None = Field(
        None,
        description="Your identifier for the customer. Send it on every event: it is what links a later server-side sale back to the click that produced the signup.",
        examples=["customer-42"],
        min_length=1,
        max_length=10000,
    )
    linkly_cid: str | None = Field(
        None,
        description="The attribution token captured from the landing page URL. Omit if unavailable — the conversion is then recorded without a link attribution.",
        examples=["2on1Y.01KYPGEEPJSPR3S564QRBDGA1W"],
        min_length=1,
        max_length=10000,
    )
    metadata: dict[str, Any] | None = Field(
        None,
        description="Arbitrary JSON, up to 10,000 bytes encoded.",
        examples=[{"sku": "ABC-123"}],
    )
    occurred_at: str | None = Field(
        None,
        description="When the conversion happened. Defaults to now.",
        examples=["2026-07-29T10:30:00Z"],
        min_length=1,
        max_length=10000,
    )
    visitor_ip: str | None = Field(
        None,
        description="The end customer's IP, when your server has it. Omit unless you do — for server-side calls Linkly otherwise records the connecting address as your server, not the customer, and excludes it from geographic reporting. Sending this asserts you have a lawful basis to share it. Never returned by the API.",
        examples=["203.0.113.42"],
        min_length=1,
        max_length=10000,
    )


class LinklyGetWorkspaceLinkConfig(_Input):
    "Get link details"
    operation: Literal["get_workspace_link"] = Field(
        "get_workspace_link", json_schema_extra={"ui:hidden": True}
    )
    id: int = Field(..., description="The id of the Link", examples=[24])


class LinklyListLinkWebhooksConfig(_Input):
    "List webhooks for a link"
    operation: Literal["list_link_webhooks"] = Field(
        "list_link_webhooks", json_schema_extra={"ui:hidden": True}
    )
    link_id: int = Field(..., description="The ID of the link", examples=[12345])


class LinklySubscribeWebhookToLinkConfig(_Input):
    "Subscribe webhook to a link"
    operation: Literal["subscribe_webhook_to_link"] = Field(
        "subscribe_webhook_to_link", json_schema_extra={"ui:hidden": True}
    )
    link_id: int = Field(
        ..., description="The ID of the link to subscribe to", examples=[12345]
    )
    url: str = Field(
        ...,
        description="The webhook URL to receive click notifications",
        examples=["https://hooks.zapier.com/hooks/catch/123456/abcdef/"],
        min_length=1,
        max_length=10000,
    )


class LinklyUnsubscribeWebhookFromLinkConfig(_Input):
    "Unsubscribe webhook from a link"
    operation: Literal["unsubscribe_webhook_from_link"] = Field(
        "unsubscribe_webhook_from_link", json_schema_extra={"ui:hidden": True}
    )
    link_id: int = Field(..., description="The ID of the link", examples=[12345])
    hook_id: str = Field(
        ...,
        description="The webhook URL (URL-encoded)",
        examples=["https%3A%2F%2Fhooks.example.com%2Fabc123"],
        min_length=1,
        max_length=10000,
    )


class LinklyGetClicksConfig(_Input):
    "Get click analytics"
    operation: Literal["get_clicks"] = Field(
        "get_clicks", json_schema_extra={"ui:hidden": True}
    )
    workspace_id: str = Field(
        ...,
        description="The id of the Workspace",
        examples=["42"],
        min_length=1,
        max_length=10000,
    )
    link_id: str | None = Field(
        None,
        description="The id of a single Link",
        examples=["24"],
        min_length=1,
        max_length=10000,
    )
    link_ids: str | None = Field(
        None,
        description="Filter clicks by multiple links. Provide a hyphen-separated list of link IDs.",
        examples=["24-25-26"],
        min_length=1,
        max_length=10000,
    )
    start: str | None = Field(
        None,
        description="The start date for the date range (format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ)",
        min_length=1,
        max_length=10000,
    )
    end: str | None = Field(
        None,
        description="The end date for the date range (format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ)",
        min_length=1,
        max_length=10000,
    )
    country: str | None = Field(
        None,
        description="Filter clicks by country using ISO 3166-1 alpha-2 country code e.g US",
        min_length=1,
        max_length=10000,
    )
    browser: str | None = Field(
        None,
        description="Filter clicks by browser name e.g Chrome, Firefox, Safari",
        min_length=1,
        max_length=10000,
    )
    platform: str | None = Field(
        None,
        description="Filter clicks by platform/operating system e.g Windows, Mac, iOS, Android",
        min_length=1,
        max_length=10000,
    )
    referer: str | None = Field(
        None,
        description="Filter clicks by referrer domain",
        min_length=1,
        max_length=10000,
    )
    isp: str | None = Field(
        None,
        description="Filter clicks by Internet Service Provider name",
        min_length=1,
        max_length=10000,
    )
    bots: bool | None = Field(
        None,
        description="Set to false to exclude bot clicks from the results",
        examples=["false"],
    )
    unique: bool | None = Field(
        None,
        description="Set to true to only include unique clicks in the results",
        examples=["false"],
    )
    format: Literal["json"] = Field(
        "json", description="Return structured JSON analytics.", examples=["json"]
    )
    pivot: Literal["link_id"] | None = Field(
        None,
        description="Return data as a matrix. When pivot=link_id, returns dates as rows and links as columns. CSV/TSV includes header rows for name, full_url, and id.",
        examples=["link_id"],
    )
    timezone: str | None = Field(
        None,
        description="The timezone to use for date/time calculations",
        examples=["America/New_York"],
        min_length=1,
        max_length=10000,
    )
    frequency: Literal["day", "hour"] = Field(
        "day",
        description="The frequency of data points in the response. Available options are 'day' (default) or 'hour'.",
    )


class LinklyGetClickCountersConfig(_Input):
    "Get click counts grouped by dimension; only the top 10,000 groups are returned, while total includes all groups."
    operation: Literal["get_click_counters"] = Field(
        "get_click_counters", json_schema_extra={"ui:hidden": True}
    )
    workspace_id: str = Field(
        ...,
        description="The id of the Workspace",
        examples=["42"],
        min_length=1,
        max_length=10000,
    )
    counter: Literal[
        "country",
        "city",
        "region",
        "platform",
        "destination",
        "referer",
        "bot_name",
        "isp",
        "link_id",
        "remote_ip",
        "top_params",
        "ad_network",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "utm_term",
    ] = Field(
        ...,
        description="The dimension to group clicks by. Options: country, city, region, platform, destination, referer, bot_name, isp, link_id, remote_ip, top_params, ad_network, and the UTM dimensions utm_source, utm_medium, utm_campaign, utm_content, utm_term. Any other value returns 400. For `link_id` each `value` is the full Link object rather than a string; for `top_params` each item also carries a `key` (the parameter name).",
    )
    link_id: str | None = Field(
        None,
        description="The id of a single Link",
        examples=["24"],
        min_length=1,
        max_length=10000,
    )
    link_ids: str | None = Field(
        None,
        description="Hyphen-separated list of Link IDs",
        examples=["24-25-26"],
        min_length=1,
        max_length=10000,
    )
    start: str | None = Field(
        None,
        description="The start date for the date range (format: YYYY-MM-DD)",
        min_length=1,
        max_length=10000,
    )
    end: str | None = Field(
        None,
        description="The end date for the date range (format: YYYY-MM-DD)",
        min_length=1,
        max_length=10000,
    )
    country: str | None = Field(
        None,
        description="Filter by country using ISO 3166-1 alpha-2 country code",
        min_length=1,
        max_length=10000,
    )
    bots: bool | None = Field(
        None,
        description="Set to false to exclude bot clicks from the results",
        examples=["false"],
    )
    unique: bool | None = Field(
        None, description="Set to true to only count unique clicks", examples=["false"]
    )
    format: Literal["json"] = Field(
        "json", description="Return structured JSON analytics.", examples=["json"]
    )


class LinklyListDomainsConfig(_Input):
    "List domains"
    operation: Literal["list_domains"] = Field(
        "list_domains", json_schema_extra={"ui:hidden": True}
    )
    workspace_id: str = Field(
        ...,
        description="The id of the Workspace",
        examples=["42"],
        min_length=1,
        max_length=10000,
    )


class LinklyCreateDomainInWorkspaceConfig(_Input):
    "Create domain in workspace"
    operation: Literal["create_domain_in_workspace"] = Field(
        "create_domain_in_workspace", json_schema_extra={"ui:hidden": True}
    )
    workspace_id: str = Field(
        ...,
        description="The id of the Workspace",
        examples=["42"],
        min_length=1,
        max_length=10000,
    )
    name: str = Field(
        ...,
        description="Domain name (e.g., links.example.com)",
        min_length=1,
        max_length=10000,
    )


class LinklyDeleteDomainConfig(_Input):
    "Delete a domain"
    operation: Literal["delete_domain"] = Field(
        "delete_domain", json_schema_extra={"ui:hidden": True}
    )
    workspace_id: str = Field(
        ...,
        description="The id of the Workspace",
        examples=["42"],
        min_length=1,
        max_length=10000,
    )
    domain_id: str = Field(
        ...,
        description="The id of the Domain",
        examples=["103"],
        min_length=1,
        max_length=10000,
    )


class LinklyUpdateDomainFaviconConfig(_Input):
    "Update domain favicon"
    operation: Literal["update_domain_favicon"] = Field(
        "update_domain_favicon", json_schema_extra={"ui:hidden": True}
    )
    workspace_id: str = Field(
        ...,
        description="The id of the Workspace",
        examples=["42"],
        min_length=1,
        max_length=10000,
    )
    id: str = Field(
        ...,
        description="The id of the Domain",
        examples=["103"],
        min_length=1,
        max_length=10000,
    )
    favicon_url: str | None = Field(
        None, description="URL to favicon image", min_length=1, max_length=10000
    )


class LinklyDeleteLinksConfig(_Input):
    "Delete links"
    operation: Literal["delete_links"] = Field(
        "delete_links", json_schema_extra={"ui:hidden": True}
    )
    workspace_id: str = Field(
        ...,
        description="The id of the Workspace",
        examples=["42"],
        min_length=1,
        max_length=10000,
    )
    ids: list[int] = Field(..., min_length=1, max_length=1000)


class LinklyCreateOrUpdateWorkspaceLinkConfig(_Input):
    "Create or update a link"
    operation: Literal["create_or_update_workspace_link"] = Field(
        "create_or_update_workspace_link", json_schema_extra={"ui:hidden": True}
    )
    workspace_id: str = Field(
        ...,
        description="The id of the Workspace",
        examples=["42"],
        min_length=1,
        max_length=10000,
    )
    fb_pixel_id: str | None = Field(
        None, description="Facebook Pixel ID", min_length=1, max_length=10000
    )
    tiktok_pixel_id: str | None = Field(
        None, description="TikTok Pixel ID", min_length=1, max_length=10000
    )
    hide_referrer: bool | None = Field(
        None, description="Hide referrer from destination"
    )
    expiry_datetime: str | None = Field(
        None, description="Link expiration date/time", min_length=1, max_length=10000
    )
    expiry_destination: str | None = Field(
        None, description="Redirect URL after expiry", min_length=1, max_length=10000
    )
    rules: list[LinklyRedirectRule] | None = Field(None, description="Redirect rules")
    domain_id: int | None = Field(
        None, description="Domain ID (alternative to domain name)"
    )
    cloaking: bool | None = Field(None, description="Enable link cloaking")
    linkify_words: str | None = Field(
        None, description="Words to linkify", min_length=1, max_length=10000
    )
    sticky_rotator: bool | None = Field(
        None,
        description="Rotator links only: send a returning visitor to the same destination as last time, remembered in a cookie for 30 days. Not available on privacy-mode links; turning privacy mode on switches it off.",
    )
    og_description: str | None = Field(
        None, description="Open Graph description", min_length=1, max_length=10000
    )
    skip_social_crawler_tracking: bool | None = Field(
        None, description="Skip tracking social media crawlers"
    )
    body_tags: str | None = Field(
        None, description="Custom HTML tags for body", min_length=1, max_length=10000
    )
    og_title: str | None = Field(
        None, description="Open Graph title", min_length=1, max_length=10000
    )
    note: str | None = Field(
        None, description="Private note about this link", min_length=1, max_length=10000
    )
    name: str | None = Field(
        None, description="Nickname for the link", min_length=1, max_length=10000
    )
    id: int | None = Field(
        None, description="Link ID (include to update existing link)"
    )
    gtm_id: str | None = Field(
        None, description="Google Tag Manager ID", min_length=1, max_length=10000
    )
    og_image: str | None = Field(
        None, description="Open Graph image URL", min_length=1, max_length=10000
    )
    block_bots: bool | None = Field(None, description="Block bot traffic")
    utm_content: str | None = Field(None, min_length=1, max_length=10000)
    enabled: bool | None = Field(None, description="Whether the link is active")
    privacy_mode: bool | None = Field(
        None,
        description="Record clicks without personal data (no IP, location, network, user agent, referrer or query parameters; click times kept to the hour). Turning it on also clears tracking pixels, custom scripts, conversion tracking, webhooks and click notifications on the link, and click webhooks stop firing for it. Paid plans only.",
    )
    url: str = Field(
        ..., description="The destination URL", min_length=1, max_length=10000
    )
    replacements: str | None = Field(
        None, description="URL parameter replacements", min_length=1, max_length=10000
    )
    qr_styles: dict[str, Any] | None = Field(
        None, description="QR code styling options"
    )
    webhooks: list[str] | None = Field(None, description="Webhook URLs")
    expiry_clicks: int | None = Field(
        None, description="Expire link after this many clicks"
    )
    public_analytics: bool | None = Field(
        None, description="Make analytics publicly accessible"
    )
    utm_source: str | None = Field(None, min_length=1, max_length=10000)
    slug: str | None = Field(
        None,
        description="Custom slug (must start with /)",
        min_length=1,
        max_length=10000,
    )
    domain: str | None = Field(
        None,
        description="Custom domain (without trailing /)",
        min_length=1,
        max_length=10000,
    )
    forward_params: bool | None = Field(
        None, description="Forward query parameters to destination"
    )
    utm_medium: str | None = Field(None, min_length=1, max_length=10000)
    head_tags: str | None = Field(
        None, description="Custom HTML tags for head", min_length=1, max_length=10000
    )
    ga4_tag_id: str | None = Field(
        None, description="Google Analytics 4 Tag ID", min_length=1, max_length=10000
    )
    utm_term: str | None = Field(None, min_length=1, max_length=10000)
    utm_campaign: str | None = Field(None, min_length=1, max_length=10000)


class LinklyExportLinksConfig(_Input):
    "Export links"
    operation: Literal["export_links"] = Field(
        "export_links", json_schema_extra={"ui:hidden": True}
    )
    workspace_id: str = Field(
        ...,
        description="The id of the Workspace",
        examples=["42"],
        min_length=1,
        max_length=10000,
    )
    format: Literal["json"] = Field(
        "json", description="Export format", examples=["json"]
    )
    search: str | None = Field(
        None,
        description="Search query to filter links",
        examples=["campaign"],
        min_length=1,
        max_length=10000,
    )


class LinklyRestoreLinksConfig(_Input):
    "Restore links"
    operation: Literal["restore_links"] = Field(
        "restore_links", json_schema_extra={"ui:hidden": True}
    )
    workspace_id: str = Field(
        ...,
        description="The id of the Workspace",
        examples=["42"],
        min_length=1,
        max_length=10000,
    )
    ids: list[int] = Field(..., min_length=1, max_length=1000)


class LinklyDeleteLinkConfig(_Input):
    "Delete a single link"
    operation: Literal["delete_link"] = Field(
        "delete_link", json_schema_extra={"ui:hidden": True}
    )
    workspace_id: str = Field(
        ...,
        description="The id of the Workspace",
        examples=["42"],
        min_length=1,
        max_length=10000,
    )
    id: int = Field(..., description="The id of the Link", examples=[24])


class LinklyListLinksConfig(_Input):
    "List links"
    operation: Literal["list_links"] = Field(
        "list_links", json_schema_extra={"ui:hidden": True}
    )
    workspace_id: str = Field(
        ...,
        description="The id of the Workspace",
        examples=["42"],
        min_length=1,
        max_length=10000,
    )
    search: str | None = Field(
        None,
        description="The search query",
        examples=["test"],
        min_length=1,
        max_length=10000,
    )
    page: int = Field(1, description="Page", ge=1)
    page_size: int = Field(1000, description="Number of links to return", ge=1, le=1000)
    sort_by: str | None = Field(
        None,
        description="Sort by field. Accepts any link column, plus the computed click aggregates: `clicks_total`, `clicks_today`, `clicks_previous_day`, `clicks_thirty_days`, `human_clicks_total`, `human_clicks_thirty_days`, `human_clicks_today`, `human_clicks_previous_day`.",
        min_length=1,
        max_length=10000,
    )
    sort_dir: str | None = Field(
        None, description="Sort direction", min_length=1, max_length=10000
    )
    filter: LinklyLinkFilter | None = Field(
        None,
        description="Filter links by exact field match. Composable — multiple filters are ANDed. e.g. filter[utm_campaign]=summer_sale&filter[utm_source]=newsletter",
    )
    deleted: bool = Field(
        False, description="Return soft-deleted (trashed) links instead of active ones"
    )


class LinklyListWorkspaceWebhooksConfig(_Input):
    "List webhooks for a workspace"
    operation: Literal["list_workspace_webhooks"] = Field(
        "list_workspace_webhooks", json_schema_extra={"ui:hidden": True}
    )
    workspace_id: int = Field(..., description="The ID of the workspace", examples=[42])


class LinklySubscribeWebhookToWorkspaceConfig(_Input):
    "Subscribe webhook to a workspace"
    operation: Literal["subscribe_webhook_to_workspace"] = Field(
        "subscribe_webhook_to_workspace", json_schema_extra={"ui:hidden": True}
    )
    workspace_id: int = Field(
        ..., description="The ID of the workspace to subscribe to", examples=[42]
    )
    url: str = Field(
        ...,
        description="The webhook URL to receive click notifications",
        examples=["https://hooks.zapier.com/hooks/catch/123456/abcdef/"],
        min_length=1,
        max_length=10000,
    )


class LinklyUnsubscribeWebhookFromWorkspaceConfig(_Input):
    "Unsubscribe webhook from a workspace"
    operation: Literal["unsubscribe_webhook_from_workspace"] = Field(
        "unsubscribe_webhook_from_workspace", json_schema_extra={"ui:hidden": True}
    )
    workspace_id: int = Field(..., description="The ID of the workspace", examples=[42])
    hook_id: str = Field(
        ...,
        description="The webhook URL (URL-encoded)",
        examples=["https%3A%2F%2Fhooks.example.com%2Fabc123"],
        min_length=1,
        max_length=10000,
    )


class LinklyListWorkspacesConfig(_Input):
    "List user workspaces"
    operation: Literal["list_workspaces"] = Field(
        "list_workspaces", json_schema_extra={"ui:hidden": True}
    )


LinklyConfig = Annotated[
    Union[
        LinklyListConversionsConfig,
        LinklyCreateConversionConfig,
        LinklyGetWorkspaceLinkConfig,
        LinklyListLinkWebhooksConfig,
        LinklySubscribeWebhookToLinkConfig,
        LinklyUnsubscribeWebhookFromLinkConfig,
        LinklyGetClicksConfig,
        LinklyGetClickCountersConfig,
        LinklyListDomainsConfig,
        LinklyCreateDomainInWorkspaceConfig,
        LinklyDeleteDomainConfig,
        LinklyUpdateDomainFaviconConfig,
        LinklyDeleteLinksConfig,
        LinklyCreateOrUpdateWorkspaceLinkConfig,
        LinklyExportLinksConfig,
        LinklyRestoreLinksConfig,
        LinklyDeleteLinkConfig,
        LinklyListLinksConfig,
        LinklyListWorkspaceWebhooksConfig,
        LinklySubscribeWebhookToWorkspaceConfig,
        LinklyUnsubscribeWebhookFromWorkspaceConfig,
        LinklyListWorkspacesConfig,
    ],
    Field(discriminator="operation"),
]

ROUTES = {
    "list_conversions": (
        "GET",
        "/api/v1/conversions",
        [],
        ["workspace_id", "limit", "after", "since"],
        [],
    ),
    "create_conversion": (
        "POST",
        "/api/v1/conversions",
        [],
        ["workspace_id"],
        [
            "amount_cents",
            "country",
            "currency",
            "event_id",
            "event_name",
            "event_type",
            "external_id",
            "linkly_cid",
            "metadata",
            "occurred_at",
            "visitor_ip",
        ],
    ),
    "get_workspace_link": ("GET", "/api/v1/get_link/{id}", ["id"], [], []),
    "list_link_webhooks": (
        "GET",
        "/api/v1/link/{link_id}/webhooks",
        ["link_id"],
        [],
        [],
    ),
    "subscribe_webhook_to_link": (
        "POST",
        "/api/v1/link/{link_id}/webhooks",
        ["link_id"],
        [],
        ["url"],
    ),
    "unsubscribe_webhook_from_link": (
        "DELETE",
        "/api/v1/link/{link_id}/webhooks/{hook_id}",
        ["link_id", "hook_id"],
        [],
        [],
    ),
    "get_clicks": (
        "GET",
        "/api/v1/workspace/{workspace_id}/clicks",
        ["workspace_id"],
        [
            "link_id",
            "link_ids",
            "start",
            "end",
            "country",
            "browser",
            "platform",
            "referer",
            "isp",
            "bots",
            "unique",
            "format",
            "pivot",
            "timezone",
            "frequency",
        ],
        [],
    ),
    "get_click_counters": (
        "GET",
        "/api/v1/workspace/{workspace_id}/clicks/counters/{counter}",
        ["workspace_id", "counter"],
        ["link_id", "link_ids", "start", "end", "country", "bots", "unique", "format"],
        [],
    ),
    "list_domains": (
        "GET",
        "/api/v1/workspace/{workspace_id}/domains",
        ["workspace_id"],
        [],
        [],
    ),
    "create_domain_in_workspace": (
        "POST",
        "/api/v1/workspace/{workspace_id}/domains",
        ["workspace_id"],
        [],
        ["name"],
    ),
    "delete_domain": (
        "DELETE",
        "/api/v1/workspace/{workspace_id}/domains/{domain_id}",
        ["workspace_id", "domain_id"],
        [],
        [],
    ),
    "update_domain_favicon": (
        "PATCH",
        "/api/v1/workspace/{workspace_id}/domains/{id}/favicon",
        ["workspace_id", "id"],
        [],
        ["favicon_url"],
    ),
    "delete_links": (
        "DELETE",
        "/api/v1/workspace/{workspace_id}/links",
        ["workspace_id"],
        [],
        ["ids"],
    ),
    "create_or_update_workspace_link": (
        "POST",
        "/api/v1/workspace/{workspace_id}/links",
        ["workspace_id"],
        [],
        [
            "fb_pixel_id",
            "tiktok_pixel_id",
            "hide_referrer",
            "expiry_datetime",
            "expiry_destination",
            "rules",
            "domain_id",
            "cloaking",
            "linkify_words",
            "sticky_rotator",
            "og_description",
            "skip_social_crawler_tracking",
            "body_tags",
            "og_title",
            "note",
            "name",
            "id",
            "gtm_id",
            "og_image",
            "block_bots",
            "utm_content",
            "enabled",
            "privacy_mode",
            "url",
            "replacements",
            "qr_styles",
            "webhooks",
            "expiry_clicks",
            "public_analytics",
            "utm_source",
            "slug",
            "domain",
            "forward_params",
            "utm_medium",
            "head_tags",
            "ga4_tag_id",
            "utm_term",
            "utm_campaign",
        ],
    ),
    "export_links": (
        "GET",
        "/api/v1/workspace/{workspace_id}/links/export",
        ["workspace_id"],
        ["format", "search"],
        [],
    ),
    "restore_links": (
        "POST",
        "/api/v1/workspace/{workspace_id}/links/restore",
        ["workspace_id"],
        [],
        ["ids"],
    ),
    "delete_link": (
        "DELETE",
        "/api/v1/workspace/{workspace_id}/links/{id}",
        ["workspace_id", "id"],
        [],
        [],
    ),
    "list_links": (
        "GET",
        "/api/v1/workspace/{workspace_id}/list_links",
        ["workspace_id"],
        ["search", "page", "page_size", "sort_by", "sort_dir", "filter", "deleted"],
        [],
    ),
    "list_workspace_webhooks": (
        "GET",
        "/api/v1/workspace/{workspace_id}/webhooks",
        ["workspace_id"],
        [],
        [],
    ),
    "subscribe_webhook_to_workspace": (
        "POST",
        "/api/v1/workspace/{workspace_id}/webhooks",
        ["workspace_id"],
        [],
        ["url"],
    ),
    "unsubscribe_webhook_from_workspace": (
        "DELETE",
        "/api/v1/workspace/{workspace_id}/webhooks/{hook_id}",
        ["workspace_id", "hook_id"],
        [],
        [],
    ),
    "list_workspaces": ("GET", "/api/v1/workspaces", [], [], []),
}


NULLABLE_LINK_FIELDS = {
    "utm_source",
    "utm_term",
    "og_description",
    "og_image",
    "expiry_destination",
    "note",
    "domain",
    "linkify_words",
    "tiktok_pixel_id",
    "expiry_datetime",
    "slug",
    "name",
    "qr_styles",
    "head_tags",
    "utm_content",
    "og_title",
    "utm_campaign",
    "utm_medium",
    "expiry_clicks",
    "fb_pixel_id",
    "body_tags",
    "replacements",
    "gtm_id",
    "ga4_tag_id",
}


class LinklyFullConfig(NodeConfig[LinklyConfig, LinklyAPIKeyCredential]):
    pass


class LinklyNode(WorkflowNode):
    integration_type = "automation-linkly"
    connection_evidence = ConnectionEvidence(
        operation="list_workspaces", noun="workspaces"
    )

    @classmethod
    def get_config_model(cls):
        return LinklyFullConfig

    async def execute(self, input_data):
        credential = self.config.credentials
        if credential is None:
            return {"status": "error", "error": "Connect a Linkly API key"}
        op = self.config.config
        method, template, path_fields, query_fields, body_fields = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, mode="json")
        path = template
        for name in path_fields:
            path = path.replace("{" + name + "}", quote(str(values[name]), safe=""))
        params = {"api_key": credential.api_key}
        for name in query_fields:
            if name not in values:
                continue
            value = values[name]
            if isinstance(value, dict):
                params.update(
                    {
                        name + "[" + key + "]": str(item)
                        for key, item in value.items()
                        if item is not None
                    }
                )
            else:
                params[name] = str(value).lower() if isinstance(value, bool) else value
        body = {name: values[name] for name in body_fields if name in values}
        if op.operation == "create_or_update_workspace_link":
            for name in NULLABLE_LINK_FIELDS & op.model_fields_set:
                if getattr(op, name) is None:
                    body[name] = None
        try:
            async with guarded_async_client(
                timeout=30, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    method,
                    "https://api.linklyhq.com" + path,
                    params=params,
                    headers={"Accept": "application/json"},
                    **({"json": body} if body_fields else {}),
                )
        except httpx.HTTPError:
            return {
                "status": "error",
                "error": "Linkly request could not be completed; inspect writes before retrying",
            }
        if len(response.content) > 20_000_000:
            return {"status": "error", "error": "Linkly response exceeds 20 MB"}
        try:
            data = response.json()
        except ValueError:
            if 200 <= response.status_code < 300:
                return {
                    "status": "error",
                    "error": "Linkly returned an unexpected non-JSON response",
                }
            data = response.text
        if not 200 <= response.status_code < 300:
            # Preserve provider rejection text for the connection verdict, without the key.
            message = str(data).replace(credential.api_key, "[redacted]")
            return {
                "status": "error",
                "http_status": response.status_code,
                "error": message[:2000],
            }
        if isinstance(data, dict) and data.get("error"):
            return {
                "status": "error",
                "error": str(data["error"]).replace(credential.api_key, "[redacted]")[
                    :2000
                ],
            }
        return {"status": "success", "http_status": response.status_code, "data": data}
