"""Talkable REST v2: site-scoped referral reporting and person metadata.

Contracts: https://www.talkable.com/api-docs/v2/openapi.yaml
Only the supplied site/key are used. No MCP, token minting, reward execution,
purchase/refund registration, invitations, consent changes or asset downloads.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

API_BASE = "https://www.talkable.com/api/v2"
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_COLLECTION = 2000


def _op(value: str, label: str, category: str) -> dict:
    return {"const": value, "ui:hidden": True, "x-display-name": label,
            "x-category": category, "x-is-trigger": False}


def _picker(field: str) -> dict:
    return {"x-resource-type": "talkable_campaign" if field == "campaign_id" else "talkable_asset",
            "x-dynamic-options": {"field_name": field, "searchable": True,
                                  "allow_custom": True}}


class TalkableApiKeyCredential(BaseModel):
    credential_type: Literal["talkable_api_key"] = Field("talkable_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
                         json_schema_extra={"ui:widget": "password"})
    site_slug: str = Field(..., title="Site ID", min_length=1, max_length=128,
                           description="Talkable Site ID from your dashboard, such as my-store. This scopes every request.")
    model_config = ConfigDict(title="Talkable API Key", hide_input_in_errors=True, extra="ignore", str_strip_whitespace=True,
                             json_schema_extra={"x-credential-url": "https://www.talkable.com/",
                                 "x-credential-instructions": "In Talkable Site Settings → API Integration, copy your API Key and Site ID. Use a REST API key, not an MCP credential."})

    @field_validator("api_key")
    @classmethod
    def key(cls, value: str) -> str:
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("API Key must be a single token")
        return value

    @field_validator("site_slug")
    @classmethod
    def site(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
            raise ValueError("Enter a Site ID, not a URL")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Limit(_Config):
    limit: int = Field(100, ge=1, le=100, title="Maximum Results",
                       description="Local output bound. These report endpoints do not document server pagination.")


class TalkableListCampaigns(_Limit):
    """List campaign metadata for the connected site. Does not activate campaigns."""
    operation: Literal["list_campaigns"] = Field("list_campaigns", json_schema_extra=_op("list_campaigns", "List Campaigns", "Campaigns"))


class _Person(_Config):
    person_slug: str = Field(..., min_length=1, max_length=320, title="Person Identifier",
                            description="Existing person's email, E.164 phone number, customer ID or username. No undocumented person-list API is used.")

    @field_validator("person_slug")
    @classmethod
    def identifier(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(c) < 32 or ord(c) == 127 for c in value) or value in {".", ".."}:
            raise ValueError("Enter a person identifier")
        return value


class TalkableGetPerson(_Person):
    """Find one person, returning selected profile and count fields."""
    operation: Literal["get_person"] = Field("get_person", json_schema_extra=_op("get_person", "Get Person", "People"))


class TalkableUpsertPersonMetadata(_Person):
    """Update first/last name and custom properties; creates a person if absent.

    Does not set subscription/consent, change contact identifiers, or issue a reward.
    Custom properties may affect merchant-defined segmentation; execution is a write.
    """
    operation: Literal["upsert_person_metadata"] = Field("upsert_person_metadata", json_schema_extra=_op("upsert_person_metadata", "Upsert Person Metadata", "People"))
    first_name: str | None = Field(None, max_length=200, title="First Name")
    last_name: str | None = Field(None, max_length=200, title="Last Name")
    custom_properties: dict[str, Union[str, bool, int, float]] | None = Field(None, title="Custom Properties",
        description="Up to 50 flat metadata values. Merchant-defined segments can use these values.")

    @model_validator(mode="after")
    def useful_metadata(self):
        if self.first_name is None and self.last_name is None and not self.custom_properties:
            raise ValueError("Provide at least one metadata field")
        if self.custom_properties is not None:
            if len(self.custom_properties) > 50:
                raise ValueError("At most 50 custom properties are supported")
            for key, value in self.custom_properties.items():
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", key):
                    raise ValueError("Custom property names must be short identifiers")
                if isinstance(value, str) and len(value) > 1000:
                    raise ValueError("Custom property values must be at most 1000 characters")
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError("Custom property numbers must be finite")
        return self


class TalkableListAdvocateReferrals(_Person, _Limit):
    """Read referrals where the person is the advocate. No referral approval."""
    operation: Literal["list_advocate_referrals"] = Field("list_advocate_referrals", json_schema_extra=_op("list_advocate_referrals", "List Advocate Referrals", "Referrals"))


class TalkableListFriendReferrals(_Person, _Limit):
    """Read referrals where the person is the friend. No referral approval."""
    operation: Literal["list_friend_referrals"] = Field("list_friend_referrals", json_schema_extra=_op("list_friend_referrals", "List Friend Referrals", "Referrals"))


class TalkableListPersonRewards(_Person, _Limit):
    """Read reward metadata and status, excluding coupon codes and redeemable URLs."""
    operation: Literal["list_person_rewards"] = Field("list_person_rewards", json_schema_extra=_op("list_person_rewards", "List Person Reward Metadata", "Reports"))


class TalkableListPersonShares(_Person, _Limit):
    """Read historical share metadata. Does not share or invite anybody."""
    operation: Literal["list_person_shares"] = Field("list_person_shares", json_schema_extra=_op("list_person_shares", "List Person Share Metadata", "Reports"))


class TalkableCalculateSharingRate(_Config):
    """Calculate the documented sharing_rate metric for a bounded date range."""
    operation: Literal["calculate_sharing_rate"] = Field("calculate_sharing_rate", json_schema_extra=_op("calculate_sharing_rate", "Calculate Sharing Rate", "Reports"))
    start_date: date = Field(..., title="Start Date")
    end_date: date = Field(..., title="End Date")
    campaign_id: int | None = Field(None, ge=1, title="Campaign", json_schema_extra=_picker("campaign_id"))
    exclude_qa_generated: bool = Field(True, title="Exclude QA Records")

    @model_validator(mode="after")
    def dates(self):
        if self.end_date < self.start_date or (self.end_date - self.start_date).days > 366:
            raise ValueError("Choose an ordered date range of at most 366 days")
        return self


class TalkableListTrafficSources(_Limit):
    """List reporting traffic-source identifiers for the connected site."""
    operation: Literal["list_traffic_sources"] = Field("list_traffic_sources", json_schema_extra=_op("list_traffic_sources", "List Traffic Sources", "Reports"))


class TalkableListAssets(_Config):
    """List asset metadata using documented page/per_page; excludes asset URLs."""
    operation: Literal["list_assets"] = Field("list_assets", json_schema_extra=_op("list_assets", "List Asset Metadata", "Assets"))
    page: int = Field(1, ge=1, le=10000, title="Page")
    per_page: int = Field(25, ge=1, le=100, title="Page Size")
    content_type: str | None = Field(None, min_length=1, max_length=100, title="Content Type", description="Optional MIME type or prefix, such as image or image/png.")


class TalkableGetAsset(_Config):
    """Read a selected asset's metadata, without downloading or exposing its URL."""
    operation: Literal["get_asset"] = Field("get_asset", json_schema_extra=_op("get_asset", "Get Asset Metadata", "Assets"))
    asset_id: int = Field(..., ge=1, title="Asset", json_schema_extra=_picker("asset_id"))


TalkableOperation = Annotated[Union[TalkableListCampaigns, TalkableGetPerson, TalkableUpsertPersonMetadata,
    TalkableListAdvocateReferrals, TalkableListFriendReferrals, TalkableListPersonRewards,
    TalkableListPersonShares, TalkableCalculateSharingRate, TalkableListTrafficSources,
    TalkableListAssets, TalkableGetAsset], Field(discriminator="operation")]


class TalkableNodeConfig(NodeConfig[TalkableOperation, TalkableApiKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class TalkableFailure(Exception):
    """Static diagnostic: provider error text, identifiers, URLs and keys stay private."""
    def __init__(self, message: str, category: str, *, http_status: int | None = None):
        super().__init__(message)
        self.category = category
        self.http_status = http_status


def _credential(data: Any) -> TalkableApiKeyCredential:
    if not isinstance(data, dict) or data.get("credential_type") != "talkable_api_key":
        raise TalkableFailure("Talkable credential is unavailable or has the wrong type", "authority")
    try:
        return TalkableApiKeyCredential.model_validate(data)
    except Exception:
        raise TalkableFailure("Talkable credential fields are invalid", "authority") from None


async def _request(credential: TalkableApiKeyCredential, method: str, path: str, *, params=None, data=None):
    """Fixed first-party REST host; no redirects, ambient proxy, retries or raw errors."""
    query = dict(params or {})
    if method == "GET":
        query["site_slug"] = credential.site_slug
    body = {"site_slug": credential.site_slug, "data": data} if data is not None else None
    try:
        async with guarded_async_client(timeout=httpx.Timeout(25.0, connect=8.0), follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, API_BASE + path, params=query, json=body,
                headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"}) as response:
                status = response.status_code
                if status != 200:
                    category = ("authentication" if status == 401 else "permission" if status == 403 else
                                "rate_limit" if status == 429 else "unavailable" if status >= 500 else
                                "not_found" if status == 404 else "validation" if status in (400, 422) else "protocol")
                    raise TalkableFailure(f"Talkable request refused (HTTP {status})", category, http_status=status)
                if "application/json" not in response.headers.get("content-type", "").lower():
                    raise TalkableFailure("Talkable returned an unexpected content type", "protocol")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_BODY_BYTES:
                        raise TalkableFailure("Talkable response exceeds the bounded metadata limit", "response_limit")
                try:
                    payload = json.loads(content)
                except Exception:
                    raise TalkableFailure("Talkable returned invalid JSON", "protocol") from None
                if not isinstance(payload, dict) or payload.get("ok") is not True or "result" not in payload:
                    category = "provider_rejected" if isinstance(payload, dict) and payload.get("ok") is False else "protocol"
                    raise TalkableFailure("Talkable did not return a successful result", category, http_status=status)
                return payload["result"]
    except TalkableFailure:
        raise
    except Exception:
        raise TalkableFailure("Talkable request could not be completed", "transport") from None


FIELDS = {
    "campaigns": ("slug", "is_active", "appearance", "id", "name", "status", "origin_max_age", "origin_min_age"),
    "person": ("customer_id", "email", "first_name", "last_name", "username", "events_count"),
    "referrals": ("id", "campaign_id", "created_at", "updated_at", "status", "ad_rewarded", "qa_generated", "referred_subtotal", "track_method"),
    "rewards": ("id", "amount", "reason", "status", "incentive_type"),
    "shares": ("id", "shared_at", "channel_identifier", "type"),
    "traffic_sources": ("identifier",),
    "assets": ("id", "name", "content_type", "size", "width", "height", "created_at", "updated_at"),
}


def _project(row: Any, resource: str) -> dict:
    if not isinstance(row, dict):
        raise TalkableFailure("Talkable returned an unexpected record shape", "protocol")
    if resource not in {"person", "traffic_sources"} and (type(row.get("id")) is not int or row["id"] < 1):
        raise TalkableFailure("Talkable returned an invalid metadata ID", "protocol")
    if resource == "traffic_sources" and (not isinstance(row.get("identifier"), str) or not row["identifier"]):
        raise TalkableFailure("Talkable returned an invalid traffic source", "protocol")
    result = {}
    for key in FIELDS[resource]:
        if key not in row:
            continue
        value = row[key]
        if value is None or isinstance(value, (bool, int)) or (isinstance(value, str) and len(value) <= 1000) or (isinstance(value, float) and math.isfinite(value)):
            result[key] = value
        else:
            raise TalkableFailure("Talkable returned an unexpected field shape", "protocol")
    if resource == "person":
        for key in ("referral_counts", "reward_counts", "share_counts"):
            counts = row.get(key)
            if isinstance(counts, dict):
                result[key] = {name: value for name, value in counts.items()
                               if name in {"total", "approved", "pending"} and type(value) is int and value >= 0}
    return result


def _records(result: Any, resource: str) -> list:
    rows = result if resource == "traffic_sources" else result.get(resource) if isinstance(result, dict) else None
    if not isinstance(rows, list) or len(rows) > MAX_COLLECTION:
        raise TalkableFailure("Talkable returned an unexpected or oversized collection", "response_limit")
    return [_project(row, resource) for row in rows]


class TalkableNode(WorkflowNode):
    integration_type = "automation-talkable"
    connection_evidence = ConnectionEvidence(noun="campaigns", operation="list_campaigns",
        operation_arguments={"limit": 3}, label_keys=("name", "id"), proves="reachability")

    @classmethod
    def get_config_model(cls):
        return TalkableNodeConfig

    @classmethod
    async def validate_credential_access(cls, credential_data):
        credential = _credential(credential_data)
        _records(await _request(credential, "GET", "/campaigns"), "campaigns")
        return {"valid": True}

    async def _provider(self, credential, method, path, *, params=None, data=None):
        return await _request(credential, method, path, params=params, data=data)

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, *, page_token=None, search=None):
        credential = _credential(credential_data)
        if field_name not in {"campaign_id", "asset_id"}:
            return {"options": [], "next_page_token": None}
        try:
            if page_token is not None and not re.fullmatch(r"[1-9][0-9]{0,3}", str(page_token)):
                raise TalkableFailure("Invalid Talkable picker page", "validation")
            page = int(page_token or 1)
            if field_name == "campaign_id":
                rows = _records(await _request(credential, "GET", "/campaigns"), "campaigns")
                if search:
                    term = str(search).casefold()[:200]
                    rows = [r for r in rows if term in str(r.get("name", "")).casefold() or term == str(r.get("id", ""))]
                selected = rows[(page - 1) * 50:page * 50]
                next_page = str(page + 1) if len(rows) > page * 50 else None
            else:
                result = await _request(credential, "GET", "/assets", params={"page": page, "per_page": 50})
                rows = _records(result, "assets")
                if len(rows) > 50 or type(result.get("total")) is not int or result["total"] < 0:
                    raise TalkableFailure("Talkable asset pagination is invalid", "protocol")
                selected = rows
                next_page = str(page + 1) if rows and page * 50 < result["total"] and page < 9999 else None
                if search:
                    term = str(search).casefold()[:200]
                    selected = [r for r in selected if term in str(r.get("name", "")).casefold() or term == str(r.get("id", ""))]
            options = []
            for row in selected:
                if type(row.get("id")) is not int or row["id"] < 1:
                    raise TalkableFailure("Talkable picker returned an invalid ID", "protocol")
                options.append({"value": str(row["id"]), "label": str(row.get("name") or row["id"]),
                                "metadata": {"site_slug": credential.site_slug}})
            return {"options": options, "next_page_token": next_page}
        except TalkableFailure:
            raise
        except Exception:
            raise TalkableFailure("Talkable options could not be loaded", "protocol") from None

    async def execute(self, inputs):
        config = self.config.config
        try:
            # Staging's loaders resolve saved access before node construction.
            credential = self.config.credentials
            if credential is None:
                raise TalkableFailure("Connect a Talkable API Key and Site ID", "authority")
            operation = config.operation
            if operation == "list_campaigns":
                rows = _records(await self._provider(credential, "GET", "/campaigns"), "campaigns")
                return self._list_output(credential, "campaigns", rows, config.limit)
            if isinstance(config, _Person):
                path = "/people/" + quote(config.person_slug, safe="")
                if operation == "get_person" or operation == "upsert_person_metadata":
                    data = None
                    if operation == "upsert_person_metadata":
                        data = config.model_dump(include={"first_name", "last_name", "custom_properties"}, exclude_none=True)
                    result = await self._provider(credential, "PUT" if data is not None else "GET", path, data=data)
                    if not isinstance(result, dict) or "person" not in result:
                        raise TalkableFailure("Talkable did not return person metadata", "protocol")
                    return {"status": "success", "site_slug": credential.site_slug, "person": _project(result["person"], "person")}
                routes = {"list_advocate_referrals": ("referrals_as_advocate", "referrals"),
                          "list_friend_referrals": ("referrals_as_friend", "referrals"),
                          "list_person_rewards": ("rewards", "rewards"), "list_person_shares": ("shares_by", "shares")}
                suffix, resource = routes[operation]
                rows = _records(await self._provider(credential, "GET", path + "/" + suffix), resource)
                return self._list_output(credential, resource, rows, config.limit)
            if operation == "calculate_sharing_rate":
                params = {"start_date": config.start_date.strftime("%m/%d/%Y"), "end_date": config.end_date.strftime("%m/%d/%Y"),
                          "exclude_qa_generated": str(config.exclude_qa_generated).lower()}
                if config.campaign_id is not None:
                    params["campaign_ids[]"] = config.campaign_id
                result = await self._provider(credential, "GET", "/metrics/sharing_rate", params=params)
                if not isinstance(result, dict) or not {"plain", "formatted", "result_type"}.issubset(result):
                    raise TalkableFailure("Talkable metric result is invalid", "protocol")
                metric = {k: result[k] for k in ("plain", "formatted", "result_type")}
                if type(metric["plain"]) not in {int, float} or not math.isfinite(metric["plain"]) or not isinstance(metric["formatted"], str) or len(metric["formatted"]) > 200 or not isinstance(metric["result_type"], str):
                    raise TalkableFailure("Talkable metric fields are invalid", "protocol")
                return {"status": "success", "site_slug": credential.site_slug, "metric": "sharing_rate", "data": metric}
            if operation == "list_traffic_sources":
                rows = _records(await self._provider(credential, "GET", "/traffic_sources"), "traffic_sources")
                return self._list_output(credential, "traffic_sources", rows, config.limit)
            if operation == "list_assets":
                params = config.model_dump(include={"page", "per_page", "content_type"}, exclude_none=True)
                result = await self._provider(credential, "GET", "/assets", params=params)
                rows = _records(result, "assets")
                if len(rows) > config.per_page or type(result.get("total")) is not int or result["total"] < 0:
                    raise TalkableFailure("Talkable asset pagination is invalid", "protocol")
                next_page = config.page + 1 if rows and config.page * config.per_page < result["total"] and config.page < 10000 else None
                return {"status": "success", "site_slug": credential.site_slug, "assets": rows, "page": config.page,
                        "total": result["total"], "next_page": next_page}
            if operation == "get_asset":
                result = await self._provider(credential, "GET", "/assets/" + str(config.asset_id))
                if not isinstance(result, dict) or "asset" not in result:
                    raise TalkableFailure("Talkable did not return asset metadata", "protocol")
                return {"status": "success", "site_slug": credential.site_slug, "asset": _project(result["asset"], "assets")}
            raise TalkableFailure("Unsupported Talkable operation", "validation")
        except TalkableFailure as exc:
            return {"status": "error", "success": False, "error": str(exc), "category": exc.category,
                    "http_status": exc.http_status}

    @staticmethod
    def _list_output(credential, resource, rows, limit):
        # No invented continuation for unpaginated provider reports.
        return {"status": "success", "site_slug": credential.site_slug, resource: rows[:limit],
                "returned_count": min(len(rows), limit), "truncated": len(rows) > limit}
