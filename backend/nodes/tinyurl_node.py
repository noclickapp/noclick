"""TinyURL API v2 link management and analytics using a pasted bearer token.

Contract: https://tinyurl.com/openapi/v2.json (2.4.2). Each operation makes
one request; listing and analytics return the provider's page and metadata.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.tinyurl.com"


class TinyURLAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="TinyURL API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://tinyurl.com/app/settings/api",
            "x-credential-instructions": "Create an API token in TinyURL API Settings, then paste it here. Give it permission to read your links and perform the actions you need. NoClick sends it as a Bearer token to api.tinyurl.com. Analytics and editing features depend on your TinyURL plan.",
        })
    credential_type: Literal["tinyurl_api_token"] = Field("tinyurl_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API token without the Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, populate_by_name=True)


class _Link(_Input):
    domain: str = Field("tinyurl.com", max_length=253, description="TinyURL domain or your branded domain, without https://")
    alias: str = Field(..., min_length=1, max_length=30, description="The existing short link alias")

    @field_validator("domain", "alias")
    @classmethod
    def segment(cls, value):
        if not value or value in {".", ".."} or any(c.isspace() or c in "/\\?#" or ord(c) < 32 for c in value):
            raise ValueError("Use a single domain or alias without a URL or path")
        return value


class _URL(_Input):
    url: str = Field(..., min_length=1, description="The destination URL to shorten")

    @field_validator("url")
    @classmethod
    def destination(cls, value):
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname or any(ord(c) < 32 for c in value):
            raise ValueError("Use an absolute HTTP or HTTPS destination URL")
        return value


Tag = Annotated[str, Field(max_length=45)]


class TinyURLCreateConfig(_URL):
    """Shorten a destination URL, optionally choosing a domain, alias and tags."""
    operation: Literal["create_link"] = Field("create_link", json_schema_extra={"ui:hidden": True})
    domain: str = Field("tinyurl.com", max_length=253)
    alias: str | None = Field(None, min_length=5, max_length=30)
    tags: list[Tag] | None = None
    expires_at: str | None = Field(None, description="Expiration datetime; explicitly set null for no expiration")
    description: str | None = Field(None, min_length=3, max_length=1000)
    @field_validator("domain", "alias")
    @classmethod
    def segments(cls, value):
        return _Link.segment(value) if value is not None else value


class TinyURLUpdateConfig(_Link):
    """Change a link's alias, domain, tags, expiration or analytics setting."""
    operation: Literal["update_link"] = Field("update_link", json_schema_extra={"ui:hidden": True})
    new_domain: str | None = Field(None, min_length=1, max_length=253)
    new_alias: str | None = Field(None, min_length=1, max_length=30)
    new_stats: bool | None = None
    new_tags: list[Tag] | None = None
    new_expires_at: str | None = Field(None, description="Expiration datetime or duration; explicitly set null for no expiration")
    new_description: str | None = Field(None, min_length=3, max_length=1000)
    @field_validator("new_domain", "new_alias")
    @classmethod
    def new_segments(cls, value):
        return _Link.segment(value) if value is not None else value


class TinyURLChangeConfig(_Link, _URL):
    """Change the destination of an existing short link."""
    operation: Literal["change_destination"] = Field("change_destination", json_schema_extra={"ui:hidden": True})


class TinyURLGetConfig(_Link):
    """Read a short link and its destination and click metadata."""
    operation: Literal["get_link"] = Field("get_link", json_schema_extra={"ui:hidden": True})


class TinyURLDeleteConfig(_Link):
    """Delete an existing short link."""
    operation: Literal["delete_link"] = Field("delete_link", json_schema_extra={"ui:hidden": True})


class _List(_Input):
    type: Literal["available", "archived"] = "available"
    from_date: str | None = Field(None, alias="from", description="Only links created after this datetime")
    to: str | None = Field(None, description="Only links created before this datetime")
    search: str | None = Field(None, pattern=r"^(alias|tag):", description="Search using alias:custom-alias or tag:tag-name")


class TinyURLListConfig(_List):
    """Read the provider's list response for available or archived links."""
    operation: Literal["list_links"] = Field("list_links", json_schema_extra={"ui:hidden": True})


class TinyURLCountConfig(_List):
    """Count available or archived links, optionally filtered by date or search."""
    operation: Literal["count_links"] = Field("count_links", json_schema_extra={"ui:hidden": True})


class TinyURLArchiveConfig(_Link):
    """Toggle the archive state of an existing link (the provider endpoint toggles)."""
    operation: Literal["toggle_archive"] = Field("toggle_archive", json_schema_extra={"ui:hidden": True})


class TinyURLAnalyticsStatusConfig(_Link):
    """Enable or disable click analytics collection for a link."""
    operation: Literal["set_analytics_status"] = Field("set_analytics_status", json_schema_extra={"ui:hidden": True})
    enabled: bool


class TinyURLAnalyticsSharingConfig(_Link):
    """Make a link's analytics public or private."""
    operation: Literal["set_analytics_sharing"] = Field("set_analytics_sharing", json_schema_extra={"ui:hidden": True})
    public: bool


class _Analytics(_Input):
    from_date: str = Field(..., alias="from", min_length=1, description="Report start datetime, e.g. 2021-08-10T10:00:00-0800")
    to: str | None = Field(None, description="Report end datetime; omitted uses the current time")
    alias: str | None = Field(None, description="Filter by a full short link, e.g. tinyurl.com/myalias")
    tag: str | None = None

class TinyURLRawAnalyticsConfig(_Analytics):
    """Read raw click analytics logs."""
    operation: Literal["raw_analytics"] = Field("raw_analytics", json_schema_extra={"ui:hidden": True})


class TinyURLTimelineAnalyticsConfig(_Analytics):
    """Read click counts over time."""
    operation: Literal["timeline_analytics"] = Field("timeline_analytics", json_schema_extra={"ui:hidden": True})
    interval: Literal["minute", "hour", "day", "week", "month"] | None = None


class TinyURLGeneralAnalyticsConfig(_Analytics):
    """Read browser, operating system and device analytics."""
    operation: Literal["general_analytics"] = Field("general_analytics", json_schema_extra={"ui:hidden": True})


class TinyURLWeekdayAnalyticsConfig(_Analytics):
    """Read click popularity by weekday."""
    operation: Literal["weekday_analytics"] = Field("weekday_analytics", json_schema_extra={"ui:hidden": True})


class TinyURLHourAnalyticsConfig(_Analytics):
    """Read click popularity by hour."""
    operation: Literal["hour_analytics"] = Field("hour_analytics", json_schema_extra={"ui:hidden": True})


class TinyURLSourceAnalyticsConfig(_Analytics):
    """Read top traffic sources."""
    operation: Literal["source_analytics"] = Field("source_analytics", json_schema_extra={"ui:hidden": True})


class TinyURLLanguageAnalyticsConfig(_Analytics):
    """Read top visitor languages."""
    operation: Literal["language_analytics"] = Field("language_analytics", json_schema_extra={"ui:hidden": True})


class TinyURLLocationAnalyticsConfig(_Analytics):
    """Read visitor country or regional analytics."""
    operation: Literal["location_analytics"] = Field("location_analytics", json_schema_extra={"ui:hidden": True})
    region: str = Field("world", pattern=r"^(world|[A-Za-z]{2})$", description="world for countries, or a country ISO alpha-2 code")


TinyURLConfig = Annotated[Union[
    TinyURLCreateConfig,
    TinyURLUpdateConfig,
    TinyURLChangeConfig,
    TinyURLGetConfig,
    TinyURLDeleteConfig,
    TinyURLListConfig,
    TinyURLCountConfig,
    TinyURLArchiveConfig,
    TinyURLAnalyticsStatusConfig,
    TinyURLAnalyticsSharingConfig,
    TinyURLRawAnalyticsConfig,
    TinyURLTimelineAnalyticsConfig,
    TinyURLGeneralAnalyticsConfig,
    TinyURLWeekdayAnalyticsConfig,
    TinyURLHourAnalyticsConfig,
    TinyURLSourceAnalyticsConfig,
    TinyURLLanguageAnalyticsConfig,
    TinyURLLocationAnalyticsConfig
], Field(discriminator="operation")]


class TinyURLFullConfig(NodeConfig[TinyURLConfig, TinyURLAPITokenCredential]):
    pass


ROUTES = {
    "create_link": ("POST", "/create"),
    "update_link": ("PATCH", "/update"),
    "change_destination": ("PATCH", "/change"),
    "get_link": ("GET", "/alias/{domain}/{alias}"),
    "delete_link": ("DELETE", "/alias/{domain}/{alias}"),
    "list_links": ("GET", "/urls/{type}"),
    "count_links": ("GET", "/urls/{type}/count"),
    "toggle_archive": ("PATCH", "/archive"),
    "set_analytics_status": ("PATCH", "/analytics/status"),
    "set_analytics_sharing": ("PATCH", "/analytics/sharing"),
    "raw_analytics": ("GET", "/analytics/raw/json"),
    "timeline_analytics": ("GET", "/analytics/timeline"),
    "general_analytics": ("GET", "/analytics/general"),
    "weekday_analytics": ("GET", "/analytics/popularity/weekday"),
    "hour_analytics": ("GET", "/analytics/popularity/hour"),
    "source_analytics": ("GET", "/analytics/sources/top"),
    "language_analytics": ("GET", "/analytics/languages/top"),
    "location_analytics": ("GET", "/analytics/location/{region}"),
}


class TinyURLNode(WorkflowNode):
    integration_type = "automation-tinyurl"
    connection_evidence = ConnectionEvidence(noun="short links", operation="list_links")

    @classmethod
    def get_config_model(cls):
        return TinyURLFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a TinyURL API token")
        method, path = ROUTES[config.operation]
        values = config.model_dump(by_alias=True, exclude_unset=True)
        # Required domain/type defaults still belong on the wire.
        for key in ("domain", "alias", "type", "region"):
            if hasattr(config, key) and getattr(config, key) is not None:
                values[key] = getattr(config, key)
        values.pop("operation", None)
        for key in tuple(values):
            marker = "{" + key + "}"
            if marker in path:
                path = path.replace(marker, quote(str(values.pop(key)), safe=""))
        if method == "GET":
            values = {k: v for k, v in values.items() if v is not None}
        else:
            # Null is meaningful only on explicitly nullable write fields.
            nullable = {"expires_at", "description", "new_expires_at", "new_description"}
            values = {k: v for k, v in values.items() if v is not None or k in nullable}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"},
                **({"params": values} if method == "GET" else {"json": values} if method != "DELETE" else {}))
        if not 200 <= response.status_code < 300:
            # Retain rejection text for the connection verdict, redacting the token.
            message = "TinyURL request failed"
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = str(error.get("errors") or error.get("message") or message)
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code,
                "error": message.replace(credential.api_token, "[redacted]")[:2000]}
        if len(response.content) > 10_000_000:
            raise ValueError("TinyURL response exceeds 10 MB; narrow the report filters")
        body = response.json()
        if not isinstance(body, dict) or "data" not in body:
            raise ValueError("TinyURL returned an unexpected JSON envelope")
        if body.get("code", 0) != 0 or body.get("errors"):
            return {"status": "error", "http_status": response.status_code,
                "error": str(body.get("errors") or "TinyURL reported an operation error").replace(credential.api_token, "[redacted]")[:2000]}
        return {**body, "status": "success"}
