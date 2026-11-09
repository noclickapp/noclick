"""Reddit Ads account, campaign, ad group, ad and performance automations.

Uses Reddit's existing OAuth sign-in with Ads-specific scopes. Each operation
makes one v3 contract request and returns its data and continuation unchanged.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.reddit_ads_operations import OPERATIONS
from nodes.scopes.reddit_ads import REDDIT_ADS_SCOPES
from utils.ssrf import guarded_async_client

BASE = "https://ads-api.reddit.com/api/v3"
DOCS = "https://ads-api.reddit.com/docs/v3/guides/quick-start/authenticate"
Status = Literal["ACTIVE", "ARCHIVED", "DELETED", "PAUSED"]
Objective = Literal["APP_INSTALLS", "BRAND_AWARENESS", "CATALOG_SALES", "CLICKS", "CONVERSIONS", "IMPRESSIONS", "LEAD_GENERATION", "SALES", "VIDEO_VIEWABLE_IMPRESSIONS"]
BidStrategy = Literal["BIDLESS", "MANUAL_BIDDING", "MAXIMIZE_VOLUME", "TARGET_CPX"]
BidType = Literal["CPC", "CPM", "CPV", "CPV6", "CPV15"]


class RedditAdsOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Reddit Ads OAuth", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "reddit",
        "x-oauth-scopes": REDDIT_ADS_SCOPES.declared_scopes(),
        "x-credential-url": DOCS,
        "x-credential-instructions": "Sign in with Reddit and grant advertising read and edit access. To connect by hand, paste the access token, refresh token and expiry obtained using your developer application.",
    })
    # The bespoke Reddit exchange stores reddit_oauth; keep that exact type.
    credential_type: Literal["reddit_oauth"] = Field("reddit_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, title="Access Token", repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field(..., min_length=1, title="Refresh Token", repr=False, description="OAuth refresh token supplied by sign-in or copied from your token response.", json_schema_extra={"ui:widget": "password"})
    expires_at: str = Field(..., title="Token Expiry", description="ISO 8601 token expiry, computed from expires_in. Sign-in supplies this automatically.")
    username: str | None = Field(None, title="Reddit Username")

    @field_validator("access_token", "refresh_token")
    @classmethod
    def token_value(cls, value):
        if value is not None and (not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value)):
            raise ValueError("Paste the token without a Bearer prefix or whitespace")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("ad_account_id", "business_id", "campaign_id", "ad_group_id", "ad_id", "post_id", mode="before", check_fields=False)
    @classmethod
    def identifiers(cls, value, info):
        if info.field_name.endswith("_id") and value is not None:
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value):
                raise ValueError("Use a Reddit resource ID without a URL or path")
        return value

    @model_validator(mode="after")
    def nonempty_patch(self):
        if self.operation.startswith("update_"):
            writable = self.model_dump(exclude_none=True, exclude={"operation", "campaign_id", "ad_group_id", "ad_id"})
            if not writable:
                raise ValueError("Choose at least one field to update")
        return self


def _f(annotation, default=..., **kwargs):
    return annotation, Field(default, **kwargs)


# Typed payload fields cover standard manual campaigns, groups and post-based ads.
# Optional fields are omitted rather than serialized as null in a PATCH.
NAME = _f(str, min_length=3, max_length=500, title="Name")
UPDATE = {
    "name": _f(str | None, None, min_length=3, max_length=500, title="Name"),
    "configured_status": _f(Status | None, None, title="Status", description="ACTIVE enables delivery; PAUSED stops delivery. ARCHIVED and DELETED change availability."),
}
CAMPAIGN = {"name": NAME, "configured_status": _f(Status, "PAUSED", title="Status"), "objective": _f(Objective, title="Objective"),
    "spend_cap": _f(int | None, None, ge=0, title="Spend Cap (microcurrency)")}
GROUP = {"name": NAME, "campaign_id": _f(str, title="Campaign ID"), "configured_status": _f(Status, "PAUSED", title="Status"),
    "bid_strategy": _f(BidStrategy, title="Bid Strategy"), "bid_type": _f(BidType, title="Bid Type"),
    "bid_value": _f(int | None, None, ge=0, title="Bid Value (microcurrency)"),
    "goal_type": _f(Literal["DAILY_SPEND", "LIFETIME_SPEND"] | None, None, title="Budget Type"),
    "goal_value": _f(int | None, None, ge=0, title="Budget (microcurrency)"),
    "start_time": _f(str | None, None, title="Start Time (ISO 8601)"), "end_time": _f(str | None, None, title="End Time (ISO 8601)"),
    "targeting": _f(dict[str, Any] | None, None, title="Targeting", description="Reddit v3 targeting object. Use the provider's documented targeting keys.")}
AD = {"name": NAME, "ad_group_id": _f(str, title="Ad Group ID"), "configured_status": _f(Status, "PAUSED", title="Status"),
    "post_id": _f(str, pattern=r"^t3_.*", title="Promoted Post ID"),
    "click_url": _f(str | None, None, max_length=5000, title="Click URL")}
REPORT = {"starts_at": _f(str, pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:00:00Z$", title="Report Start (UTC hour)"),
    "ends_at": _f(str, pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:00:00Z$", title="Report End (UTC hour)"),
    "fields": _f(list[str], min_length=1, title="Metrics", description="Reddit reporting field names such as IMPRESSIONS, CLICKS, SPEND and CPC."),
    "breakdowns": _f(list[str] | None, None, max_length=4, title="Breakdowns"),
    "filter": _f(str | None, None, title="Report Filter")}
PAYLOADS = {"create_campaign": CAMPAIGN, "update_campaign": {**UPDATE, "spend_cap": CAMPAIGN["spend_cap"]},
    "create_ad_group": GROUP, "update_ad_group": {**UPDATE, **{k: v for k, v in GROUP.items() if k not in {"name", "campaign_id", "configured_status", "bid_strategy", "bid_type", "goal_type"}}},
    "create_ad": AD, "update_ad": {**UPDATE, "click_url": AD["click_url"]}, "get_report": REPORT}
MODELS = []
for operation, (method, path, title, category) in OPERATIONS.items():
    fields = {"operation": _f(Literal[operation], operation, title=title, json_schema_extra={
        "ui:hidden": True, "x-display-name": title, "x-category": category, "x-is-trigger": False})}
    fields.update({key: _f(str, title=key.replace("_", " ").title()) for key in re.findall(r"{(\w+)}", path)})
    if "business_id" in fields:
        fields["business_id"] = _f(str, title="Business ID", pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
    fields.update(PAYLOADS.get(operation, {}))
    if operation.startswith("list_") or operation == "get_report":
        fields["page_size"] = _f(int, 100, ge=1, le=100, title="Page Size")
        fields["next_page_url"] = _f(str | None, None, title="Next Page URL", description="Copy pagination.next_url from the preceding response. Must target this same account and endpoint; the URL is followed unchanged.")
    if operation == "list_ad_groups":
        fields["campaign_id"] = _f(str | None, None, title="Filter by Campaign ID")
    model = create_model("RedditAds" + "".join(x.title() for x in operation.split("_")) + "Config", __base__=_Config, **fields)
    globals()[model.__name__] = model
    MODELS.append(model)

RedditAdsOperation = Annotated[Union[tuple(MODELS)], Field(discriminator="operation")]


class RedditAdsFullConfig(NodeConfig):
    model_config = ConfigDict(title="Reddit Ads Node Configuration")
    config: RedditAdsOperation
    credentials: RedditAdsOAuthCredential | None = None


class RedditAdsNode(WorkflowNode):
    integration_type = "automation-reddit-ads"
    credential_provider_labels = {"reddit": "Reddit Account"}
    scope_registry = REDDIT_ADS_SCOPES
    connection_evidence = ConnectionEvidence(noun="Reddit Ads account", identity_operation="get_me", identity_keys=("reddit_username", "email", "id"))

    @classmethod
    def get_config_model(cls):
        return RedditAdsFullConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        if not credential_data.get("refresh_token"):
            return credential_data
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.reddit_oauth import refresh_access_token
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="reddit")

    async def execute(self, inputs):
        if not isinstance(self.config, RedditAdsFullConfig) or not self.config.credentials:
            raise ValueError("Connect a Reddit account with adsread and adsedit access")
        credential = self.config.credentials
        token = credential.access_token
        if credential.refresh_token:
            from nodes.core.oauth_refresh import ensure_fresh_oauth_token
            from nodes.oauth.reddit_oauth import refresh_access_token
            blob = credential.model_dump()
            token = await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"),
                user_id=self.user_id, credential=blob, refresh=refresh_access_token, provider="reddit", caller_path="execute")
            for key in ("access_token", "refresh_token", "expires_at"):
                setattr(credential, key, blob.get(key))
        elif credential.expires_at:
            from nodes.oauth.reddit_oauth import is_token_expired
            if is_token_expired(credential.expires_at, buffer_minutes=0):
                raise ValueError("This pasted access token has expired; sign in again or paste a new token")
        config = self.config.config
        operation = config.operation
        method, path, _, _ = OPERATIONS[operation]
        values = config.model_dump(exclude_none=True, exclude={"operation", "page_size", "next_page_url"})
        path_fields = re.findall(r"{(\w+)}", path)
        for key in path_fields:
            path = path.replace("{" + key + "}", quote(values.pop(key), safe=""))
        url = BASE + path
        params = {"page.size": config.page_size} if hasattr(config, "page_size") else {}
        if operation == "list_ad_groups" and values.get("campaign_id"):
            params["campaign_id"] = values.pop("campaign_id")
        continuation = getattr(config, "next_page_url", None)
        if continuation:
            parsed = urlsplit(continuation)
            if (parsed.scheme != "https" or parsed.netloc != "ads-api.reddit.com" or parsed.path != "/api/v3" + path
                    or parsed.fragment or any(c.isspace() or ord(c) < 33 for c in continuation)):
                raise ValueError("Next page URL must be Reddit's URL for this same account and endpoint")
            url, params = continuation, None
        body = None
        if method in {"POST", "PATCH"}:
            if operation == "create_ad_group":
                values["type"] = "MANUAL"
            body = {"data": values}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, url, params=params, json=body, headers={
                "Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": "NoClick:reddit-ads:v1.0"})
        if not 200 <= response.status_code < 300:
            # Preserve provider JSON for connection rejection evidence; never include request credentials.
            try:
                error = response.json()
            except ValueError:
                error = None
            return {"status": "error", "http_status": response.status_code,
                "error": error if isinstance(error, dict) else "Reddit Ads request failed"}
        result = response.json()
        if not isinstance(result, dict) or "data" not in result or "error" in result or "errors" in result:
            raise ValueError("Reddit Ads returned an unexpected response envelope")
        return {**result, "status": "success"}
