"""Everflow portal metadata, aggregate reporting and channel management.

Fixed global REST origin. Network, Affiliate and Advertiser keys are separate
credential families. No tracking links, clicks, conversions, payouts or exports.
Primary contracts: https://developers.everflow.io/llms.txt (2026-10-06).
"""
from __future__ import annotations

import base64
import asyncio
import hashlib
import hmac
import json
import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from utils.credentials import resolve_credential_with_owner_fallback

CURRENT_ORGANIZATION = object()

BASE = "https://api.eflow.team/v1"
TYPES = {
    "everflow_network_api_key": "networks",
    "everflow_affiliate_api_key": "affiliates",
    "everflow_advertiser_api_key": "advertisers",
}


def _id(value):
    if type(value) is int and value > 0:
        return str(value)
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,19}", value):
        return value
    raise ValueError("A positive decimal resource ID is required")


def _text(value, maximum=500):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("A nonempty single-line value is required")
    return value


def _single_line(value):
    return _text(value)


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secret): _redact(item, secret) for key, item in value.items()}
    return value


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Key(_Closed):
    api_key: str = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})
    network_id: str = Field(..., title="Network ID", description="Expected network ID from your Everflow administrator. This binds resource results to this network.")

    @field_validator("network_id", mode="before")
    @classmethod
    def network(cls, value):
        return _id(value)

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str) or not 1 <= len(value) <= 4096 or not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("API key must be a nonempty ASCII header value")
        return value

    @model_validator(mode="before")
    @classmethod
    def shaped_default(cls, data):
        # Concrete manual credential shaping uses exclude_unset=True. The raw
        # node boundary independently checks the original external tag.
        if isinstance(data, dict) and "credential_type" not in data:
            return {**data, "credential_type": cls.model_fields["credential_type"].default}
        return data


class EverflowNetworkApiKeyCredential(_Key):
    credential_type: Literal["everflow_network_api_key"] = Field("everflow_network_api_key", json_schema_extra={"ui:hidden": True})
    model_config = ConfigDict(title="Everflow Network API Key", extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://developers.everflow.io/user-guide/authentication"})


class EverflowAffiliateApiKeyCredential(_Key):
    credential_type: Literal["everflow_affiliate_api_key"] = Field("everflow_affiliate_api_key", json_schema_extra={"ui:hidden": True})
    model_config = ConfigDict(title="Everflow Affiliate API Key", extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://developers.everflow.io/user-guide/authentication"})


class EverflowAdvertiserApiKeyCredential(_Key):
    credential_type: Literal["everflow_advertiser_api_key"] = Field("everflow_advertiser_api_key", json_schema_extra={"ui:hidden": True})
    model_config = ConfigDict(title="Everflow Advertiser API Key", extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://developers.everflow.io/user-guide/authentication"})


# Flat anyOf is the current credential form/selection schema contract. Raw tags
# are checked before parsing, so the union cannot retag a foreign credential.
Credentials = Union[EverflowNetworkApiKeyCredential, EverflowAffiliateApiKeyCredential, EverflowAdvertiserApiKeyCredential]


def credential(data):
    if not isinstance(data, dict) or data.get("credential_type") not in TYPES:
        raise ValueError("An explicit supported Everflow credential type is required")
    fields = {key: data[key] for key in ("credential_type", "api_key", "network_id") if key in data}
    try:
        parsed = TypeAdapter(Credentials).validate_python(fields)
    except Exception:
        raise ValueError("Everflow credential is invalid") from None
    return {"credential_type": parsed.credential_type, "api_key": parsed.api_key, "network_id": parsed.network_id}


class CheckConnection(_Closed):
    operation: Literal["check_connection"] = Field("check_connection", title="Check Connection", json_schema_extra={"ui:hidden": True})


class GetNetwork(_Closed):
    operation: Literal["get_network"] = Field("get_network", title="Get Network", description="Network and Affiliate keys only. Returns network metadata, not API-key user identity.", json_schema_extra={"ui:hidden": True})


class _Paged(_Closed):
    page_size: int = Field(50, ge=1, le=200, strict=True, title="Page Size")
    page_token: str | None = Field(None, title="Next Page Token", description="Use only a continuation returned by this operation with the same credential and filters.")
    search: str | None = Field(None, max_length=200, title="Name Search")

    @field_validator("search")
    @classmethod
    def clean_search(cls, value):
        return _text(value, 200) if value is not None else None


class ListOffers(_Paged):
    operation: Literal["list_offers"] = Field("list_offers", title="List Offers", json_schema_extra={"ui:hidden": True})


class GetOffer(_Closed):
    operation: Literal["get_offer"] = Field("get_offer", title="Get Offer", json_schema_extra={"ui:hidden": True})
    offer_id: str = Field(..., title="Offer", json_schema_extra={"x-options-source": "dynamic", "x-options-depends-on": []})

    _identifier = field_validator("offer_id", mode="before")(_id)


class ListAffiliates(_Paged):
    operation: Literal["list_affiliates"] = Field("list_affiliates", title="List Affiliates", json_schema_extra={"ui:hidden": True})


class GetAffiliate(_Closed):
    operation: Literal["get_affiliate"] = Field("get_affiliate", title="Get Affiliate", json_schema_extra={"ui:hidden": True})
    affiliate_id: str = Field(..., title="Affiliate", json_schema_extra={"x-options-source": "dynamic"})
    _identifier = field_validator("affiliate_id", mode="before")(_id)


class ListAdvertisers(_Paged):
    operation: Literal["list_advertisers"] = Field("list_advertisers", title="List Advertisers", json_schema_extra={"ui:hidden": True})


class GetAdvertiser(_Closed):
    operation: Literal["get_advertiser"] = Field("get_advertiser", title="Get Advertiser", json_schema_extra={"ui:hidden": True})
    advertiser_id: str = Field(..., title="Advertiser", json_schema_extra={"x-options-source": "dynamic"})
    _identifier = field_validator("advertiser_id", mode="before")(_id)


class ListCampaigns(_Closed):
    operation: Literal["list_campaigns"] = Field("list_campaigns", title="List Smart Links", description="Safe campaign metadata; no tracking or redirect URLs.", json_schema_extra={"ui:hidden": True})


class GetCampaign(_Closed):
    operation: Literal["get_campaign"] = Field("get_campaign", title="Get Smart Link", json_schema_extra={"ui:hidden": True})
    campaign_id: str = Field(..., title="Smart Link", json_schema_extra={"x-options-source": "dynamic"})
    _identifier = field_validator("campaign_id", mode="before")(_id)


class ListTrackingDomains(_Closed):
    operation: Literal["list_tracking_domains"] = Field("list_tracking_domains", title="List Tracking Domains", json_schema_extra={"ui:hidden": True})


class GetTrackingDomain(_Closed):
    operation: Literal["get_tracking_domain"] = Field("get_tracking_domain", title="Get Tracking Domain", json_schema_extra={"ui:hidden": True})
    tracking_domain_id: str = Field(..., title="Tracking Domain", json_schema_extra={"x-options-source": "dynamic"})
    _identifier = field_validator("tracking_domain_id", mode="before")(_id)


class ListChannels(_Closed):
    operation: Literal["list_channels"] = Field("list_channels", title="List Channels", json_schema_extra={"ui:hidden": True})


class GetChannel(_Closed):
    operation: Literal["get_channel"] = Field("get_channel", title="Get Channel", json_schema_extra={"ui:hidden": True})
    channel_id: str = Field(..., title="Channel", json_schema_extra={"x-options-source": "dynamic"})
    _identifier = field_validator("channel_id", mode="before")(_id)


class _ChannelValues(_Closed):
    name: str = Field(..., title="Name", min_length=1, max_length=200)
    status: Literal["active", "inactive"] = Field("inactive", title="Channel Status")
    _name = field_validator("name")(_single_line)


class CreateChannel(_ChannelValues):
    operation: Literal["create_channel"] = Field("create_channel", title="Create Channel", json_schema_extra={"ui:hidden": True})


class UpdateChannel(_ChannelValues):
    operation: Literal["update_channel"] = Field("update_channel", title="Replace Channel", description="PUT replaces channel values. Supply both name and status.", json_schema_extra={"ui:hidden": True})
    status: Literal["active", "inactive"] = Field(..., title="Channel Status")
    channel_id: str = Field(..., title="Channel", json_schema_extra={"x-options-source": "dynamic"})
    expected_name: str = Field(..., title="Current Name", min_length=1, max_length=200, description="Must match the current channel before replacement.")
    _identifier = field_validator("channel_id", mode="before")(_id)
    _expected = field_validator("expected_name")(_single_line)


class DeleteChannel(_Closed):
    operation: Literal["delete_channel"] = Field("delete_channel", title="Delete Channel", json_schema_extra={"ui:hidden": True})
    channel_id: str = Field(..., title="Channel", json_schema_extra={"x-options-source": "dynamic"})
    expected_name: str = Field(..., title="Current Name", min_length=1, max_length=200)
    _identifier = field_validator("channel_id", mode="before")(_id)
    _expected = field_validator("expected_name")(_single_line)


class _Report(_Closed):
    from_date: str = Field(..., title="From Date", description="YYYY-MM-DD in the requested reporting timezone.")
    to_date: str = Field(..., title="To Date", description="YYYY-MM-DD; range cannot exceed 367 days.")
    timezone_id: str = Field(..., title="Timezone", json_schema_extra={"x-options-source": "dynamic"})
    currency_id: str = Field(..., title="Currency", json_schema_extra={"x-options-source": "dynamic"})
    offer_id: str | None = Field(None, title="Offer Filter", json_schema_extra={"x-options-source": "dynamic"})
    affiliate_id: str | None = Field(None, title="Affiliate Filter", json_schema_extra={"x-options-source": "dynamic"})
    advertiser_id: str | None = Field(None, title="Advertiser Filter", json_schema_extra={"x-options-source": "dynamic"})

    @field_validator("offer_id", "affiliate_id", "advertiser_id", mode="before")
    @classmethod
    def identifier(cls, value):
        return _id(value) if value is not None else None

    _zone = field_validator("timezone_id", mode="before")(_id)

    @field_validator("currency_id")
    @classmethod
    def currency_code(cls, value):
        if not re.fullmatch(r"[A-Z]{3}", value):
            raise ValueError("An uppercase ISO currency code is required")
        return value

    @model_validator(mode="after")
    def dates(self):
        try:
            start, end = date.fromisoformat(self.from_date), date.fromisoformat(self.to_date)
        except (ValueError, TypeError):
            raise ValueError("Report dates must be YYYY-MM-DD") from None
        if start.isoformat() != self.from_date or end.isoformat() != self.to_date or not 0 <= (end-start).days <= 367:
            raise ValueError("Report dates must be ordered and at most 367 days apart")
        return self


class GetReport(_Report):
    operation: Literal["get_report"] = Field("get_report", title="Get Aggregate Report", json_schema_extra={"ui:hidden": True})
    group_by: Literal["offer", "affiliate", "advertiser", "campaign"] = Field("offer", title="Group By")
    campaign_data_only: bool = Field(False, strict=True, title="Campaign Data Only")


class GetReportSummary(_Report):
    operation: Literal["get_report_summary"] = Field("get_report_summary", title="Get Report Summary", description="Provider summary totals, never a sum of potentially incomplete table rows.", json_schema_extra={"ui:hidden": True})


class ListCurrencies(_Closed):
    operation: Literal["list_currencies"] = Field("list_currencies", title="List Currencies", json_schema_extra={"ui:hidden": True})


class ListTimezones(_Closed):
    operation: Literal["list_timezones"] = Field("list_timezones", title="List Timezones", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[CheckConnection, GetNetwork, ListOffers, GetOffer, ListAffiliates, GetAffiliate, ListAdvertisers, GetAdvertiser, ListCampaigns, GetCampaign, ListTrackingDomains, GetTrackingDomain, ListChannels, GetChannel, CreateChannel, UpdateChannel, DeleteChannel, GetReport, GetReportSummary, ListCurrencies, ListTimezones], Field(discriminator="operation")]


class EverflowNodeConfig(NodeConfig[Operation, Credentials]):
    model_config = ConfigDict(hide_input_in_errors=True)


class ProviderError(ValueError):
    def __init__(self, status=None, message="Everflow response could not be verified"):
        self.status = status
        super().__init__(message)


class Session:
    def __init__(self, data):
        self.data = credential(data)
        self.store = None
        self.anchor = None
        self.validation_row = None
        self.acknowledgement = None
        self.write_attempted = False

    @classmethod
    async def saved(cls, data, *, pool, user_id, credential_id, organization_id=CURRENT_ORGANIZATION, workflow_id=None):
        session = cls(data)
        if pool is None:
            from utils.database_pool import get_native_pool
            pool = get_native_pool()
        session.store = (pool, user_id, credential_id, organization_id, workflow_id)
        session.anchor = await session._saved_state()
        return session

    async def _saved_state(self):
        pool, user_id, credential_id, organization_id, workflow_id = self.store
        async with pool.acquire() as conn:
            if organization_id is CURRENT_ORGANIZATION:
                from repositories.organization import OrgRepo
                organization_id = await OrgRepo(pool).get_primary_org_id(conn, user_id)
            row = await conn.fetchrow("""
                SELECT c.owner_id, c.credential_type, c.token_version,
                       c.updated_at, c.revoked_at, c.approval_revision
                FROM credentials c WHERE c.id = $1::uuid
            """, credential_id)
        if (row is None or row["credential_type"] != self.data["credential_type"]
                or row["revoked_at"] is not None
                or type(row["token_version"]) is not int or row["token_version"] < 1):
            raise ValueError("Everflow credential is unavailable or access denied")
        data = await resolve_credential_with_owner_fallback(
            credential_id, user_id, pool, org_id=organization_id, workflow_id=workflow_id,
        )
        if credential(data) != self.data:
            raise ValueError("Everflow credential changed before the request")
        return tuple(row[key] for key in (
            "owner_id", "credential_type", "token_version", "updated_at",
            "revoked_at", "approval_revision",
        )) + (organization_id,)

    async def current(self):
        if self.store is not None and await self._saved_state() != self.anchor:
            raise ValueError("Everflow credential authority changed; retry after checking the result")

    async def request(self, method, route, *, params=None, body=None, write=False, absent=False):
        try:
            return await asyncio.wait_for(self._request(method, route, params=params, body=body, write=write, absent=absent), timeout=25)
        except TimeoutError:
            raise ProviderError(None, "Everflow request deadline exceeded; inspect writes before retrying") from None

    async def _request(self, method, route, *, params=None, body=None, write=False, absent=False):
        if not re.fullmatch(r"/(?:networks|affiliates|advertisers|meta)(?:/[A-Za-z0-9_-]+)*", route):
            raise ValueError("Unsupported Everflow route")
        await self.current()
        if write:
            self.write_attempted = True
        try:
            async with httpx.AsyncClient(verify=True, trust_env=False, follow_redirects=False, timeout=httpx.Timeout(20.0)) as client:
                async with client.stream(method, BASE + route, headers={"X-Eflow-API-Key": self.data["api_key"], "Accept": "application/json"}, params=params, json=body) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 2 * 1024 * 1024:
                            raise ProviderError(response.status_code, "Everflow response exceeds the supported size")
                    status = response.status_code
                    if write and 200 <= status < 300:
                        self.acknowledgement = {"http_status": status}
                    await self.current()
                    if absent and status == 404:
                        return None
                    try:
                        payload = json.loads(raw, parse_float=Decimal, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    except (ValueError, TypeError, UnicodeError):
                        raise ProviderError(status, "Everflow returned an unsupported JSON response") from None
                    if status != 200 or not isinstance(payload, dict):
                        error = payload.get("error", payload.get("Error")) if isinstance(payload, dict) else None
                        # Provider text can echo credentials, URLs or private data.
                        known = {"Out of realm", "No authentication method found", "Unable to authenticate request", "Invalid parameters.", "Can't find entry in the database"}
                        message = error if isinstance(error, str) and error in known else "Everflow request was rejected or could not be verified"
                        raise ProviderError(status, message)
                    if payload.get("error") is not None or payload.get("Error") is not None:
                        raise ProviderError(status, "Everflow returned an error in a successful HTTP response")
                    return payload
        except (httpx.HTTPError, OSError):
            raise ProviderError(None, "Everflow request outcome is unknown; inspect writes before retrying") from None

    async def bind_network(self):
        portal = TYPES[self.data["credential_type"]]
        if portal == "advertisers":
            # No undocumented advertiser identity endpoint or inferred first-row identity.
            return None
        row = await self.request("GET", "/networks" if portal == "networks" else "/affiliates/network")
        if _id(row.get("network_id")) != self.data["network_id"]:
            raise ValueError("Everflow key belongs to a different network")
        return _project(row, "network", self.data["network_id"])


IDS = {"offer": "network_offer_id", "affiliate": "network_affiliate_id", "advertiser": "network_advertiser_id", "campaign": "network_campaign_id", "tracking_domain": "network_tracking_domain_id", "channel": "network_channel_id", "network": "network_id"}
FIELDS = {
    "network": ("name", "displayed_name", "account_status", "timezone_id", "currency_id", "time_created", "time_saved"),
    "offer": ("name", "offer_status", "visibility", "currency_id", "network_advertiser_id", "network_offer_group_id", "time_created", "time_saved"),
    "affiliate": ("name", "account_status", "default_currency_id", "time_created", "time_saved"),
    "advertiser": ("name", "account_status", "default_currency_id", "reporting_timezone_id", "time_created", "time_saved"),
    "campaign": ("campaign_name", "campaign_status", "network_tracking_domain_id", "is_use_secure_link", "redirect_routing_type", "is_open_to_affiliates", "time_created", "time_saved"),
    "tracking_domain": ("url", "domain_status", "is_primary_domain", "is_ssl_enabled", "ownership", "time_created", "time_saved"),
    "channel": ("name", "status", "time_created", "time_saved"),
}


def _project(row, kind, network, expected=None):
    if not isinstance(row, dict) or _id(row.get("network_id")) != network:
        raise ValueError("Everflow resource network does not match the credential")
    identifier = _id(row.get(IDS[kind]))
    if expected is not None and identifier != expected:
        raise ValueError("Everflow returned a different resource")
    out = {IDS[kind]: identifier, "network_id": network}
    for key in FIELDS[kind]:
        value = row.get(key)
        if value is None:
            continue
        if key == "url":
            # Documented tracking-domain host only; never URLs, credentials or links.
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9.-]{1,253}", value) and "." in value:
                out["hostname"] = value
        elif key.endswith("_id") and key not in {"currency_id", "default_currency_id"}:
            if value == 0 and type(value) is int:
                out[key] = "0"
            else:
                out[key] = _id(value)
        elif isinstance(value, str):
            out[key] = _text(value)
        elif type(value) in (int, bool):
            out[key] = value
        else:
            raise ValueError("Everflow resource metadata has an unsupported shape")
    return out


def _token(session, scope, page):
    raw = json.dumps({"scope": scope, "page": page}, sort_keys=True, separators=(",", ":")).encode()
    mac = hmac.new(session.data["api_key"].encode(), raw, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw + mac).decode().rstrip("=")


def _page(session, scope, token):
    if token is None:
        return 1
    try:
        if not isinstance(token, str) or len(token) > 4096:
            raise ValueError()
        decoded = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        raw, signature = decoded[:-32], decoded[-32:]
        if not hmac.compare_digest(signature, hmac.new(session.data["api_key"].encode(), raw, hashlib.sha256).digest()):
            raise ValueError()
        result = json.loads(raw)
        if result["scope"] != scope or type(result["page"]) is not int or not 2 <= result["page"] <= 100000:
            raise ValueError()
        return result["page"]
    except Exception:
        raise ValueError("Everflow continuation does not match this credential, operation or filters") from None


COUNTS = {"imp", "total_click", "unique_click", "invalid_click", "duplicate_click", "gross_click", "cv", "invalid_cv_scrub", "view_through_cv", "total_cv", "event", "on_hold_conversion_count", "public_events"}
AMOUNTS = {"avg_sale_value", "cpa", "cpc", "cpm", "ctr", "cvr", "epc", "event_revenue", "evr", "gross_sales", "margin", "media_buying_cost", "on_hold_potential_payout", "on_hold_potential_revenue", "payout", "profit", "revenue", "roas", "rpa", "rpc", "rpm"}


def _metrics(data):
    if not isinstance(data, dict) or not (COUNTS | AMOUNTS).intersection(data):
        raise ValueError("Everflow report metrics are missing")
    out = {}
    for key in COUNTS | AMOUNTS:
        if key not in data:
            continue
        value = data[key]
        if key in COUNTS:
            if type(value) is not int or value < 0:
                raise ValueError("Everflow report count is invalid")
            out[key] = value
        else:
            if type(value) not in (int, Decimal) or not Decimal(value).is_finite():
                raise ValueError("Everflow report decimal is invalid")
            out[key] = str(value)
    return out


class EverflowNode(WorkflowNode):
    integration_type = "automation-everflow"
    credential_provider_labels = {"everflow": "Everflow"}
    connection_evidence = ConnectionEvidence(noun="offers", operation="check_connection", proves="reachability", label_keys=("name",))
    edit_examples = ["List offers visible to this key", "Show last week's offer report", "Create an inactive reporting channel"]

    @classmethod
    def get_config_model(cls):
        return EverflowNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        if not isinstance(config_data, dict):
            raise ValueError("Everflow configuration is required")
        raw = config_data.get("credentials")
        if raw is not None:
            shaped = credential(raw)  # Before inherited reconciliation can retag a foreign blob.
            config_data = {**config_data, "credentials": shaped}
        try:
            return TypeAdapter(EverflowNodeConfig).validate_python(runtime_config_view(config_data, EverflowNodeConfig))
        except Exception:
            raise ValueError("Everflow configuration or credential is invalid") from None

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        data = credential(credential_data)
        if credential_id:
            session = await Session.saved(data, pool=pool, user_id=user_id, credential_id=credential_id)
            return {**data, "_everflow_session": session}
        return data

    @classmethod
    async def validate_credential_access(cls, credential_data, *, validation_context=None):
        data = credential(credential_data)
        try:
            if validation_context is not None:
                result = await validation_context.run_operation("check_connection")
                valid = True if result.get("status") == "success" else False if result.get("http_status") in {401, 403} else None
            else:
                await cls._perform(Session(data), CheckConnection())
                valid = True
        except ProviderError as exc:
            valid = False if exc.status in {401, 403} else None
        except ValueError:
            valid = None
        return {"valid": valid, "identity_verified": False, "message": "Key accepted for offer reads" if valid else "Everflow access could not be established"}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Everflow credential")
        data = credential(self.config.credentials.model_dump())
        session = self.node_data.get("credentials", {}).get("_everflow_session")
        if session is not None:
            if not isinstance(session, Session) or session.data != data:
                raise ValueError("Everflow current credential context is invalid")
        elif self.node_data.get("credential_id"):
            session = await Session.saved(data, pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data["credential_id"], organization_id=self.organization_id, workflow_id=self.workflow_id)
        else:
            session = Session(data)
        try:
            result = await self._perform(session, self.config.config)
            await session.current()
            output = {"status": "success", "success": True, "action": self.config.config.operation, **result}
        except Exception as exc:
            if session.acknowledgement is not None or (session.write_attempted and (not isinstance(exc, ProviderError) or exc.status is None or exc.status >= 500)):
                output = {"status": "unknown", "success": False, "action": self.config.config.operation, "acknowledgement": session.acknowledgement, "channel_id": getattr(self.config.config, "channel_id", None), "message": "Everflow write outcome could not be verified. Inspect the channel before retrying."}
            elif isinstance(exc, ProviderError):
                output = {"status": "error", "success": False, "http_status": exc.status, "status_code": exc.status, "message": str(exc)}
            else:
                raise ValueError("Everflow response or current credential authority could not be verified") from None
        output = _redact(output, data["api_key"])
        await self.emit(output)
        return output

    @classmethod
    async def _perform(cls, session, op):
        name = op.operation
        portal = TYPES[session.data["credential_type"]]
        if name not in {"check_connection", "list_offers", "get_offer", "list_currencies", "list_timezones", "get_network"} and portal != "networks":
            raise ValueError("This operation requires an Everflow Network API key")
        network = await session.bind_network()
        if name == "get_network":
            if network is None:
                raise ValueError("Advertiser network identity is not documented for this operation")
            return {"data": network, "identity_verified": False}
        if name == "check_connection":
            result = await cls._list(session, "offer", ListOffers(page_size=5))
            return {**result, "identity_verified": False, "proof": "reachability", "message": "Key accepted for offer reads; this does not prove all Network permissions or API-key user identity"}
        if name in {"list_offers", "list_affiliates", "list_advertisers"}:
            return await cls._list(session, {"list_offers": "offer", "list_affiliates": "affiliate", "list_advertisers": "advertiser"}[name], op)
        if name in {"get_offer", "get_affiliate", "get_advertiser", "get_campaign", "get_tracking_domain", "get_channel"}:
            kind = name[4:]
            identifier = getattr(op, "tracking_domain_id" if kind == "tracking_domain" else kind + "_id")
            return {"data": await cls._get(session, kind, identifier)}
        if name in {"list_campaigns", "list_tracking_domains", "list_channels"}:
            kind, route, key = {"list_campaigns": ("campaign", "/networks/campaigns", "campaigns"), "list_tracking_domains": ("tracking_domain", "/networks/domains/tracking", "domains"), "list_channels": ("channel", "/networks/channels", "channels")}[name]
            rows = await session.request("GET", route)
            items = cls._rows(rows, key)
            return {"data": {key: [_project(row, kind, session.data["network_id"]) for row in items]}, "pagination": {"kind": "unpaginated", "count": len(items)}}
        if name in {"list_currencies", "list_timezones"}:
            kind = name[5:]
            rows = cls._rows(await session.request("GET", "/meta/" + kind), kind)
            selected = []
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("Everflow metadata row is invalid")
                if kind == "currencies":
                    code = row.get("currency_id")
                    if not isinstance(code, str) or not re.fullmatch(r"[A-Z]{3}", code):
                        raise ValueError("Everflow currency is invalid")
                    selected.append({"currency_id": code, "name": _text(row.get("name")), "symbol": _text(row.get("symbol"))})
                else:
                    selected.append({"timezone_id": _id(row.get("timezone_id")), "timezone_name": _text(row.get("timezone_name")), "timezone": _text(row.get("timezone")), "utc_offset": _text(row.get("utc_offset"))})
            return {"data": {kind: selected}, "proof": "static_metadata"}
        if name in {"create_channel", "update_channel", "delete_channel"}:
            route = "/networks/channels"
            identifier = None if name == "create_channel" else op.channel_id
            if identifier:
                current = await cls._get(session, "channel", identifier)
                if current.get("name") != op.expected_name:
                    raise ValueError("Current channel name differs; refresh before changing it")
                route += "/" + identifier
            method = {"create_channel": "POST", "update_channel": "PUT", "delete_channel": "DELETE"}[name]
            body = None if name == "delete_channel" else {"name": op.name, "status": op.status}
            response = await session.request(method, route, body=body, write=True)
            if name == "delete_channel":
                if response.get("result") is not True:
                    raise ValueError("Everflow deletion was not acknowledged")
                session.acknowledgement.update({"channel_id": identifier, "result": True})
                remaining = await session.request("GET", route, absent=True)
                if remaining is not None:
                    raise ValueError("Everflow channel still exists")
                return {"data": {"channel_id": identifier, "deleted": True, "absence_verified": True}, "acknowledgement": session.acknowledgement}
            row = _project(response, "channel", session.data["network_id"], identifier)
            session.acknowledgement["channel_id"] = row["network_channel_id"]
            verified = await cls._get(session, "channel", row["network_channel_id"])
            if verified.get("name") != op.name or verified.get("status") != op.status:
                raise ValueError("Everflow channel readback differs from the requested values")
            return {"data": verified, "readback_verified": True, "acknowledgement": session.acknowledgement}
        if name in {"get_report", "get_report_summary"}:
            body = {"from": op.from_date, "to": op.to_date, "timezone_id": int(op.timezone_id), "currency_id": op.currency_id}
            filters = []
            for kind in ("offer", "affiliate", "advertiser"):
                identifier = getattr(op, kind + "_id")
                if identifier:
                    await cls._get(session, kind, identifier)
                    filters.append({"resource_type": kind, "filter_id_value": identifier})
            if filters:
                body["query"] = {"filters": filters}
            if name == "get_report":
                body["columns"] = [{"column": op.group_by}]
                if op.campaign_data_only:
                    body.setdefault("query", {})["settings"] = {"campaign_data_only": True}
            result = await session.request("POST", "/networks/reporting/entity/" + ("table" if name == "get_report" else "summary"), body=body)
            if name == "get_report_summary":
                return {"data": {"metrics": _metrics(result), "currency_id": op.currency_id, "amount_units": "full_currency_units", "from": op.from_date, "to": op.to_date, "timezone_id": op.timezone_id}}
            rows = cls._rows(result, "table", maximum=10000)
            projected = []
            for row in rows:
                columns = row.get("columns") if isinstance(row, dict) else None
                allowed_columns = {op.group_by, "advertiser"} if op.group_by == "offer" else {op.group_by}
                if not isinstance(columns, list) or not 1 <= len(columns) <= len(allowed_columns):
                    raise ValueError("Everflow report dimensions are invalid")
                dimensions = []
                seen = set()
                for column in columns:
                    if not isinstance(column, dict) or column.get("column_type") not in allowed_columns or column["column_type"] in seen:
                        raise ValueError("Everflow report grouping differs")
                    identifier = column.get("id")
                    if not isinstance(identifier, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,19})", identifier):
                        raise ValueError("Everflow report entity ID is invalid")
                    seen.add(column["column_type"])
                    dimensions.append({"column_type": column["column_type"], "id": identifier, "label": _text(column.get("label"))})
                if op.group_by not in seen:
                    raise ValueError("Everflow report requested grouping is missing")
                projected.append({"columns": dimensions, "reporting": _metrics(row.get("reporting"))})
            incomplete = result.get("incomplete_results")
            if incomplete is not None and type(incomplete) is not bool:
                raise ValueError("Everflow report completeness flag is invalid")
            return {"data": {"table": projected, "incomplete_results": incomplete, "currency_id": op.currency_id, "amount_units": "full_currency_units", "from": op.from_date, "to": op.to_date, "timezone_id": op.timezone_id}, "pagination": {"kind": "unpaginated", "count": len(rows), "complete": None if incomplete is None else not incomplete}}
        raise ValueError("Unsupported Everflow operation")

    @staticmethod
    def _rows(data, key, maximum=10000):
        rows = data.get(key)
        if not isinstance(rows, list) or len(rows) > maximum:
            raise ValueError("Everflow resource envelope is invalid")
        return rows

    @classmethod
    async def _get(cls, session, kind, identifier):
        portal = TYPES[session.data["credential_type"]]
        route = {"offer": "/" + portal + "/offers/", "affiliate": "/networks/affiliates/", "advertiser": "/networks/advertisers/", "campaign": "/networks/campaigns/", "tracking_domain": "/networks/domains/tracking/", "channel": "/networks/channels/"}[kind]
        return _project(await session.request("GET", route + _id(identifier)), kind, session.data["network_id"], identifier)

    @classmethod
    async def _list(cls, session, kind, op):
        portal = TYPES[session.data["credential_type"]]
        key = kind + "s"
        if portal == "advertisers":
            if op.search or op.page_token:
                raise ValueError("Advertiser offer search and continuation are not documented")
            result = await session.request("GET", "/advertisers/offers", params={"page": 1, "page_size": op.page_size})
            rows = cls._rows(result, "offers", maximum=op.page_size)
            return {"data": {"offers": [_project(row, "offer", session.data["network_id"]) for row in rows]}, "pagination": {"page": 1, "page_size": op.page_size, "complete": None, "next_page_token": None, "message": "Advertiser specification omits a continuation envelope; this is one bounded page"}}
        route = "/" + portal + "/" + kind + "stable"
        scope = {"credential_type": session.data["credential_type"], "network_id": session.data["network_id"], "route": route, "page_size": op.page_size, "search": op.search}
        page = _page(session, scope, op.page_token)
        body = {"search_terms": [{"search_type": "name", "value": op.search}] if op.search else [], "filters": {}}
        result = await session.request("POST", route, params={"page": page, "page_size": op.page_size}, body=body)
        rows = cls._rows(result, key, maximum=op.page_size)
        paging = result.get("paging")
        if not isinstance(paging, dict) or any(type(paging.get(field)) is not int for field in ("page", "page_size", "total_count")) or paging["page"] != page or paging["page_size"] != op.page_size or paging["total_count"] < 0:
            raise ValueError("Everflow paging metadata is invalid")
        offset = (page-1) * op.page_size
        if offset + len(rows) > paging["total_count"] or (not rows and offset < paging["total_count"]):
            raise ValueError("Everflow paging totals contradict this page")
        more = offset + len(rows) < paging["total_count"]
        if more and len(rows) != op.page_size:
            raise ValueError("Everflow returned a short nonterminal page")
        return {"data": {key: [_project(row, kind, session.data["network_id"]) for row in rows]}, "pagination": {**paging, "next_page_token": _token(session, scope, page+1) if more else None}}

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None, page_token=None, search=None):
        kinds = {"offer_id": "offer", "affiliate_id": "affiliate", "advertiser_id": "advertiser", "campaign_id": "campaign", "tracking_domain_id": "tracking_domain", "channel_id": "channel", "currency_id": "currencies", "timezone_id": "timezones"}
        if field_name not in kinds:
            raise ValueError("Unsupported Everflow picker")
        data = credential(credential_data)
        session = credential_data.get("_everflow_session") if isinstance(credential_data, dict) else None
        if session is None:
            session = Session(data)
        elif not isinstance(session, Session) or session.data != data:
            raise ValueError("Everflow current picker context is invalid")
        kind = kinds[field_name]
        if kind not in {"offer", "currencies", "timezones"} and TYPES[data["credential_type"]] != "networks":
            raise ValueError("This picker requires a Network API key")
        await session.bind_network()
        if kind in {"offer", "affiliate", "advertiser"}:
            model = {"offer": ListOffers, "affiliate": ListAffiliates, "advertiser": ListAdvertisers}[kind]
            result = await cls._list(session, kind, model(page_size=50, page_token=page_token, search=search))
            rows = result["data"][kind + "s"]
            next_token = result["pagination"].get("next_page_token")
        else:
            if page_token:
                raise ValueError("This Everflow metadata list is unpaginated")
            model = {"campaign": ListCampaigns, "tracking_domain": ListTrackingDomains, "channel": ListChannels, "currencies": ListCurrencies, "timezones": ListTimezones}[kind]
            result = await cls._perform(session, model())
            rows = next(iter(result["data"].values()))
            next_token = None
        key = IDS.get(kind, "currency_id" if kind == "currencies" else "timezone_id")
        label_keys = ("name", "campaign_name", "hostname", "timezone_name", key)
        options = [{"value": str(row[key]), "label": next(str(row[label]) for label in label_keys if row.get(label) is not None)} for row in rows]
        if search and kind not in {"offer", "affiliate", "advertiser"}:
            options = [row for row in options if search.casefold() in row["label"].casefold()]
        await session.current()
        return _redact({"options": options, "next_page_token": next_token}, data["api_key"])
