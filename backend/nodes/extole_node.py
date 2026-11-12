"""Typed Extole client-scoped REST operations; no consumer authentication or token minting."""
from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
from contextvars import ContextVar
import json
import logging
import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from nodes.core.base import ConfigValidationError, NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

API_ORIGIN = "https://api.extole.io"
EVENT_ORIGIN = "https://events.extole.io"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
Id = Annotated[StrictStr, Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_-]+$")]
Text = Annotated[StrictStr, Field(min_length=1, max_length=512)]
DataName = Annotated[StrictStr, Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_.:-]+$")]
Limit = Annotated[StrictInt, Field(ge=1, le=100)]
Offset = Annotated[StrictInt, Field(ge=0, le=1000000)]
CampaignState = Literal["ARCHIVED", "ENDED", "LIVE", "NOT_LAUNCHED", "PAUSED", "STOPPED"]
ReportFormat = Literal["CSV", "HEADLESS_CSV", "HEADLESS_PSV", "JSON", "JSONL", "PSV", "XLSX"]
SERVER_SCOPES = {"BACKEND", "CLIENT_ADMIN", "CLIENT_SUPERUSER", "USER_SUPPORT", "CAMPAIGN_EDIT", "CLIENT_REPORT_DOWNLOAD"}

# Lookup query values and bearer headers are private. Filter transport logs in
# this task only, preserving other requests and normal application logging.
_PRIVATE_HTTP = ContextVar("extole_private_http", default=False)


class _PrivateTransportLog(logging.Filter):
    def filter(self, record):
        return not _PRIVATE_HTTP.get()


_TRANSPORT_LOG_FILTER = _PrivateTransportLog()


@contextmanager
def private_transport_logs():
    for name in ("httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"):
        logger = logging.getLogger(name)
        if _TRANSPORT_LOG_FILTER not in logger.filters:
            logger.addFilter(_TRANSPORT_LOG_FILTER)
    token = _PRIVATE_HTTP.set(True)
    try:
        yield
    finally:
        _PRIVATE_HTTP.reset(token)


def bounded_json(value):
    try:
        encoded = json.dumps(value, allow_nan=False, separators=(",", ":"))
    except (ValueError, TypeError):
        raise ValueError("Use finite JSON values") from None
    if len(encoded.encode("utf-8")) > 32768:
        raise ValueError("Metadata must fit within 32 KiB")
    return value


def utc_expiry(value):
    if value is None:
        return value
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise ValueError("Expiry must be an ISO timestamp with a timezone") from None
    if parsed.tzinfo is None:
        raise ValueError("Expiry must include a timezone")
    return value


class ExtoleAccessTokenCredential(BaseModel):
    credential_type: Literal["extole_access_token"] = Field("extole_access_token", json_schema_extra={"ui:hidden": True})
    access_token: Annotated[StrictStr, Field(min_length=1, max_length=8192)] = Field(
        ..., title="Access Token", repr=False, json_schema_extra={"ui:widget": "password"})
    expected_client_id: Optional[Id] = Field(None, title="Expected Client ID",
        description="Optional tenant binding, checked against the protected current-token endpoint.")
    expires_at: Optional[StrictStr] = Field(None, title="Actual Token Expiry",
        description="Supply the actual expiry for a short-lived token; omit for a managed long-lived token.")
    model_config = ConfigDict(title="Extole Access Token", extra="ignore",
        json_schema_extra={"x-credential-url": "https://docs.extole.com/api-reference/getting-started/authentication-overview"})
    _expiry = field_validator("expires_at")(utc_expiry)

    @field_validator("access_token")
    @classmethod
    def header_token(cls, value):
        if value.strip() != value or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Access token must be a single nonempty header value")
        return value


class ExtoleInput(BaseModel):
    # Native canvas metadata (for example agent_tool_operations) remains in
    # node_data; only these typed domain fields can enter a provider request.
    model_config = ConfigDict(extra="ignore")


class PageInput(ExtoleInput):
    limit: Limit = 25
    offset: Offset = 0


class ParticipantInput(ExtoleInput):
    person_id: Id = Field(..., title="Participant ID", json_schema_extra={
        "x-resource-type": "extole_person",
        "x-dynamic-options": {"field_name": "person_id", "searchable": True}})


class ParticipantPageInput(ParticipantInput):
    limit: Limit = 25
    offset: Offset = 0


class ParticipantDataInput(ParticipantInput):
    name: DataName = Field(..., title="Data Name", json_schema_extra={
        "x-dynamic-options": {"field_name": "data_name", "depends_on": "person_id"}})


class CampaignInput(ExtoleInput):
    campaign_id: Id = Field(..., title="Campaign", json_schema_extra={
        "x-resource-type": "extole_campaign",
        "x-dynamic-options": {"field_name": "campaign_id"}})


class ReportInput(ExtoleInput):
    report_id: Id = Field(..., title="Report", json_schema_extra={
        "x-resource-type": "extole_report",
        "x-dynamic-options": {"field_name": "report_id"}})


class EventData(ExtoleInput):
    model_config = ConfigDict(extra="forbid")
    email: Optional[Text] = Field(None, title="Email")
    partner_user_id: Optional[Text] = None
    person_id: Optional[Annotated[StrictInt, Field(gt=0, le=9223372036854775807)]] = None
    event_time: Optional[StrictStr] = None
    properties: dict[DataName, JsonValue] = Field(default_factory=dict,
        description="Additional documented event data; named identity fields cannot be overridden.")
    _time = field_validator("event_time")(utc_expiry)

    @field_validator("properties")
    @classmethod
    def properties_bound(cls, value):
        if {"email", "partner_user_id", "person_id", "event_time"} & value.keys():
            raise ValueError("Use the typed identity and time fields")
        return bounded_json(value)


class EventInput(ExtoleInput):
    event_name: DataName
    data: Optional[EventData] = None
    event_time: Optional[StrictStr] = None
    _time = field_validator("event_time")(utc_expiry)

class ExtoleCheckConnectionConfig(ExtoleInput):
    operation: Literal["check_connection"] = Field("check_connection", title="Check Connection",
        json_schema_extra={"const":"check_connection","ui:hidden":True,"x-category":"Connection","x-is-trigger":False,"x-display-name":"Check Connection"})


class ExtoleSearchParticipantsConfig(PageInput):
    operation: Literal["search_participants"] = Field("search_participants", title="Search Participants",
        json_schema_extra={"const":"search_participants","ui:hidden":True,"x-category":"Participants","x-is-trigger":False,"x-display-name":"Search Participants"})
    identity_key_value: Optional[Text] = None
    person_keys: list[Text] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def criterion(self):
        if not self.identity_key_value and not self.person_keys:
            raise ValueError("Supply an identity value or person keys")
        if any(":" not in key or not all(key.split(":", 1)) for key in self.person_keys):
            raise ValueError("Person keys use name:value")
        return self


class ExtoleGetParticipantConfig(ParticipantInput):
    operation: Literal["get_participant"] = Field("get_participant", title="Get Participant",
        json_schema_extra={"const":"get_participant","ui:hidden":True,"x-category":"Participants","x-is-trigger":False,"x-display-name":"Get Participant"})


class ExtoleCreateParticipantConfig(ExtoleInput):
    operation: Literal["create_participant"] = Field("create_participant", title="Create Participant",
        json_schema_extra={"const":"create_participant","ui:hidden":True,"x-category":"Participants","x-is-trigger":False,"x-display-name":"Create Participant","x-creates-resource":True,"x-resource-type":"extole_person","x-resource-id-path":"data.id"})
    identity_key_value: Text


class ExtoleUpdateParticipantConfig(ParticipantInput):
    operation: Literal["update_participant"] = Field("update_participant", title="Update Participant",
        json_schema_extra={"const":"update_participant","ui:hidden":True,"x-category":"Participants","x-is-trigger":False,"x-display-name":"Update Participant"})
    identity_key_value: Text


class ExtoleListParticipantDataConfig(ParticipantPageInput):
    operation: Literal["list_participant_data"] = Field("list_participant_data", title="List Participant Data",
        json_schema_extra={"const":"list_participant_data","ui:hidden":True,"x-category":"Participant Data","x-is-trigger":False,"x-display-name":"List Participant Data"})


class ExtoleGetParticipantDataConfig(ParticipantDataInput):
    operation: Literal["get_participant_data"] = Field("get_participant_data", title="Get Participant Data",
        json_schema_extra={"const":"get_participant_data","ui:hidden":True,"x-category":"Participant Data","x-is-trigger":False,"x-display-name":"Get Participant Data"})


class ExtoleCreateParticipantDataConfig(ParticipantInput):
    operation: Literal["create_participant_data"] = Field("create_participant_data", title="Create Private Participant Data",
        json_schema_extra={"const":"create_participant_data","ui:hidden":True,"x-category":"Participant Data","x-is-trigger":False,"x-display-name":"Create Private Participant Data","x-creates-resource":True,"x-resource-type":"extole_person_data","x-resource-id-path":"data.id"})
    name: DataName
    value: dict[DataName, JsonValue]
    _bound = field_validator("value")(bounded_json)


class ExtoleUpdateParticipantDataConfig(ParticipantDataInput):
    operation: Literal["update_participant_data"] = Field("update_participant_data", title="Update Participant Data",
        json_schema_extra={"const":"update_participant_data","ui:hidden":True,"x-category":"Participant Data","x-is-trigger":False,"x-display-name":"Update Participant Data"})
    value: dict[DataName, JsonValue]
    _bound = field_validator("value")(bounded_json)


class ExtoleDeleteParticipantDataConfig(ParticipantDataInput):
    operation: Literal["delete_participant_data"] = Field("delete_participant_data", title="Delete Participant Data",
        json_schema_extra={"const":"delete_participant_data","ui:hidden":True,"x-category":"Participant Data","x-is-trigger":False,"x-display-name":"Delete Participant Data"})


class ExtoleListReferralsConfig(ParticipantPageInput):
    operation: Literal["list_referral_relationships"] = Field("list_referral_relationships", title="List Referral Relationships",
        json_schema_extra={"const":"list_referral_relationships","ui:hidden":True,"x-category":"Referrals","x-is-trigger":False,"x-display-name":"List Referral Relationships"})
    my_roles: list[Literal["ADVOCATE", "FRIEND"]] = Field(default_factory=list, max_length=2)
    exclude_anonymous: StrictBool = False
    include_duplicate_identities: StrictBool = False
    include_self_referrals: StrictBool = False


class ExtoleListJourneysConfig(ParticipantPageInput):
    operation: Literal["list_participant_journeys"] = Field("list_participant_journeys", title="List Participant Journeys",
        json_schema_extra={"const":"list_participant_journeys","ui:hidden":True,"x-category":"Participants","x-is-trigger":False,"x-display-name":"List Participant Journeys"})


class ExtoleListCampaignsConfig(ExtoleInput):
    operation: Literal["list_campaign_summaries"] = Field("list_campaign_summaries", title="List Campaign Summaries",
        json_schema_extra={"const":"list_campaign_summaries","ui:hidden":True,"x-category":"Campaigns","x-is-trigger":False,"x-display-name":"List Campaign Summaries"})
    states: list[CampaignState] = Field(default_factory=list, max_length=6)
    tags: list[Text] = Field(default_factory=list, max_length=20)
    include_archived: StrictBool = False


class ExtoleGetCampaignSummaryConfig(CampaignInput):
    operation: Literal["get_campaign_summary"] = Field("get_campaign_summary", title="Get Campaign Summary",
        json_schema_extra={"const":"get_campaign_summary","ui:hidden":True,"x-category":"Campaigns","x-is-trigger":False,"x-display-name":"Get Campaign Summary"})


class ExtoleGetCampaignMetadataConfig(CampaignInput):
    operation: Literal["get_campaign_metadata"] = Field("get_campaign_metadata", title="Get Campaign Metadata",
        json_schema_extra={"const":"get_campaign_metadata","ui:hidden":True,"x-category":"Campaigns","x-is-trigger":False,"x-display-name":"Get Campaign Metadata"})


class ExtoleCreateCampaignDraftConfig(ExtoleInput):
    operation: Literal["create_campaign_draft"] = Field("create_campaign_draft", title="Create Campaign Draft",
        json_schema_extra={"const":"create_campaign_draft","ui:hidden":True,"x-category":"Campaigns","x-is-trigger":False,"x-display-name":"Create Campaign Draft","x-creates-resource":True,"x-resource-type":"extole_campaign","x-resource-id-path":"data.campaign_id"})
    name: Text
    tags: list[Text] = Field(default_factory=list, max_length=20)
    description: Optional[Annotated[StrictStr, Field(max_length=4096)]] = None


class ExtoleUpdateCampaignMetadataConfig(CampaignInput):
    operation: Literal["update_campaign_metadata"] = Field("update_campaign_metadata", title="Update Campaign Metadata",
        json_schema_extra={"const":"update_campaign_metadata","ui:hidden":True,"x-category":"Campaigns","x-is-trigger":False,"x-display-name":"Update Campaign Metadata"})
    name: Optional[Text] = None
    description: Optional[Annotated[StrictStr, Field(max_length=4096)]] = None
    tags: Optional[list[Text]] = Field(None, max_length=20)

    @model_validator(mode="after")
    def changes(self):
        if not {"name", "description", "tags"} & self.model_fields_set:
            raise ValueError("Supply a metadata change")
        return self


class ExtoleDeleteCampaignDraftConfig(CampaignInput):
    operation: Literal["delete_campaign_draft"] = Field("delete_campaign_draft", title="Delete Campaign Draft",
        json_schema_extra={"const":"delete_campaign_draft","ui:hidden":True,"x-category":"Campaigns","x-is-trigger":False,"x-display-name":"Delete Campaign Draft"})


class ExtoleListReportTypesConfig(PageInput):
    operation: Literal["list_report_types"] = Field("list_report_types", title="List Report Types",
        json_schema_extra={"const":"list_report_types","ui:hidden":True,"x-category":"Reports","x-is-trigger":False,"x-display-name":"List Report Types"})
    search_query: Optional[Text] = None


class ExtoleListReportsConfig(PageInput):
    operation: Literal["list_reports"] = Field("list_reports", title="List Reports",
        json_schema_extra={"const":"list_reports","ui:hidden":True,"x-category":"Reports","x-is-trigger":False,"x-display-name":"List Reports"})
    report_type_name: Optional[Text] = None


class ExtoleGetReportConfig(ReportInput):
    operation: Literal["get_report"] = Field("get_report", title="Get Report Metadata",
        json_schema_extra={"const":"get_report","ui:hidden":True,"x-category":"Reports","x-is-trigger":False,"x-display-name":"Get Report Metadata"})


class ExtoleCreateReportConfig(ExtoleInput):
    operation: Literal["create_report"] = Field("create_report", title="Request Report",
        json_schema_extra={"const":"create_report","ui:hidden":True,"x-category":"Reports","x-is-trigger":False,"x-display-name":"Request Report","x-creates-resource":True,"x-resource-type":"extole_report","x-resource-id-path":"data.report_id"})
    name: Text
    report_type: Text = Field(..., title="Report Type", json_schema_extra={
        "x-dynamic-options": {"field_name": "report_type"}})
    parameters: dict[DataName, StrictStr] = Field(default_factory=dict)
    display_name: Optional[Text] = None
    formats: Optional[list[ReportFormat]] = Field(None, max_length=7)
    tags: Optional[list[Text]] = Field(None, max_length=20)
    _bound = field_validator("parameters")(bounded_json)


class ExtoleUpdateReportConfig(ReportInput):
    operation: Literal["update_report"] = Field("update_report", title="Update Report Metadata",
        json_schema_extra={"const":"update_report","ui:hidden":True,"x-category":"Reports","x-is-trigger":False,"x-display-name":"Update Report Metadata"})
    display_name: Optional[Text] = None
    tags: Optional[list[Text]] = Field(None, max_length=20)

    @model_validator(mode="after")
    def changes(self):
        if not {"display_name", "tags"} & self.model_fields_set:
            raise ValueError("Supply a metadata change")
        if any(getattr(self, key) is None for key in self.model_fields_set if key != "operation"):
            raise ValueError("Report metadata does not accept null")
        return self


class ExtoleDeleteReportConfig(ReportInput):
    operation: Literal["delete_report"] = Field("delete_report", title="Delete Report",
        json_schema_extra={"const":"delete_report","ui:hidden":True,"x-category":"Reports","x-is-trigger":False,"x-display-name":"Delete Report"})


class ExtoleGetOptOutStatusConfig(ExtoleInput):
    operation: Literal["get_opt_out_status"] = Field("get_opt_out_status", title="Get Opt-Out Status",
        json_schema_extra={"const":"get_opt_out_status","ui:hidden":True,"x-category":"Consent","x-is-trigger":False,"x-display-name":"Get Opt-Out Status"})
    email: Text


class ExtoleSubmitEventConfig(EventInput):
    operation: Literal["submit_event"] = Field("submit_event", title="Submit Event",
        json_schema_extra={"const":"submit_event","ui:hidden":True,"x-category":"Events","x-is-trigger":False,"x-display-name":"Submit Event"})


class ExtoleSubmitAsyncEventConfig(EventInput):
    operation: Literal["submit_async_event"] = Field("submit_async_event", title="Submit Async Event",
        json_schema_extra={"const":"submit_async_event","ui:hidden":True,"x-category":"Events","x-is-trigger":False,"x-display-name":"Submit Async Event"})


# Extole's own MCP server: agents get its tools through a person's Extole sign-in.
ExtoleMcpCredential = mcp_credential("extole", "https://mcp.extole.com", app="Extole")
ExtoleCredential = Union[ExtoleAccessTokenCredential, ExtoleMcpCredential]


ExtoleOperation = Annotated[Union[
    ExtoleCheckConnectionConfig,
    ExtoleSearchParticipantsConfig,
    ExtoleGetParticipantConfig,
    ExtoleCreateParticipantConfig,
    ExtoleUpdateParticipantConfig,
    ExtoleListParticipantDataConfig,
    ExtoleGetParticipantDataConfig,
    ExtoleCreateParticipantDataConfig,
    ExtoleUpdateParticipantDataConfig,
    ExtoleDeleteParticipantDataConfig,
    ExtoleListReferralsConfig,
    ExtoleListJourneysConfig,
    ExtoleListCampaignsConfig,
    ExtoleGetCampaignSummaryConfig,
    ExtoleGetCampaignMetadataConfig,
    ExtoleCreateCampaignDraftConfig,
    ExtoleUpdateCampaignMetadataConfig,
    ExtoleDeleteCampaignDraftConfig,
    ExtoleListReportTypesConfig,
    ExtoleListReportsConfig,
    ExtoleGetReportConfig,
    ExtoleCreateReportConfig,
    ExtoleUpdateReportConfig,
    ExtoleDeleteReportConfig,
    ExtoleGetOptOutStatusConfig,
    ExtoleSubmitEventConfig,
    ExtoleSubmitAsyncEventConfig,
], Field(discriminator="operation")]


class ExtoleNodeConfig(NodeConfig[ExtoleOperation, ExtoleCredential]):
    pass

class Projected(BaseModel):
    model_config = ConfigDict(extra="ignore")


class TokenMetadata(Projected):
    client_id: Id
    type: Literal["MANAGED", "RESOURCE", "USER"]
    scopes: list[StrictStr]
    expires_in: Optional[StrictInt] = None


class ParticipantMetadata(Projected):
    id: Id
    version: StrictStr


class DataMetadata(Projected):
    id: Id
    name: DataName
    scope: Literal["CLIENT", "PRIVATE", "PUBLIC"]
    created_date: Optional[StrictStr] = None
    updated_date: Optional[StrictStr] = None


class CampaignMetadata(Projected):
    campaign_id: Id
    name: StrictStr
    state: CampaignState
    is_published: StrictBool
    tags: list[StrictStr]
    version: Optional[StrictInt] = None
    updated_date: Optional[StrictStr] = None
    description: Optional[StrictStr] = None


class ReferralMetadata(Projected):
    id: Id
    person_id: Id
    other_person_id: Id
    my_role: Literal["ADVOCATE", "FRIEND"]
    campaign_id: Optional[StrictStr] = None
    created_date: Optional[StrictStr] = None


class JourneyMetadata(Projected):
    id: Id
    campaign_id: Id
    name: StrictStr
    created_date: Optional[StrictStr] = None
    updated_date: Optional[StrictStr] = None


class ReportMetadata(Projected):
    report_id: Id
    name: StrictStr
    report_type: StrictStr
    display_name: StrictStr
    completed_date: Optional[StrictStr]
    formats: list[ReportFormat]
    tags: list[StrictStr]


class ReportTypeMetadata(Projected):
    name: StrictStr
    display_name: StrictStr
    type: Literal["CONFIGURED", "DASHBOARD", "SPARK", "SQL"]
    description: Optional[StrictStr] = None
    formats: list[ReportFormat]


class AsyncEventReceipt(Projected):
    event_id: Id


class EventReceipt(AsyncEventReceipt):
    person_id: Id


class ExtoleHTTPError(ValueError):
    def __init__(self, status):
        self.status = status
        message = (f"Extole refused the request (HTTP {status})." if status in {400, 401, 403, 404, 415}
                   else f"Extole request did not complete (HTTP {status}); saved credential validity is unverified.")
        super().__init__(message)


def raw_family(data):
    if isinstance(data, BaseModel):
        data = data.model_dump()
    if not isinstance(data, dict):
        raise ValueError("Connect an Extole client access token")
    if "credential_type" in data and data["credential_type"] != "extole_access_token":
        raise ValueError("Credential type is not supported by Extole")
    return data


def shaped_credential(data):
    try:
        return ExtoleAccessTokenCredential.model_validate(raw_family(data))
    except Exception:
        raise ValueError("Extole credential type or shape is invalid") from None


def projected(model, raw):
    if not isinstance(raw, dict):
        raise ValueError("Extole returned malformed metadata")
    try:
        return model.model_validate(raw).model_dump(exclude_unset=True)
    except Exception:
        raise ValueError("Extole returned malformed metadata") from None


def projected_list(model, raw):
    if not isinstance(raw, list) or len(raw) > 1000:
        raise ValueError("Extole returned malformed or excessive metadata")
    return [projected(model, item) for item in raw]


def path_id(value):
    return quote(value, safe="")


def safe_label(value):
    return re.sub(r"[\x00-\x1f\x7f]", "", str(value))[:120]


class ExtoleNode(WorkflowNode):
    integration_type = "automation-extole"
    credential_provider_labels = {"extole": "Extole Account"}
    connection_evidence = ConnectionEvidence(
        identity_operation="check_connection", noun="client", identity_keys=("client_id",), proves="account")

    @classmethod
    def get_config_model(cls):
        return ExtoleNodeConfig

    @classmethod
    def _guard_raw(cls, data):
        credentials = data.get("credentials") if isinstance(data, dict) else None
        if credentials is not None:
            raw_family(credentials)

    @classmethod
    def parse_config(cls, config_data):
        try:
            cls._guard_raw(config_data)
        except ValueError:
            raise ConfigValidationError("Credential type is not supported by Extole") from None
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._guard_raw(config_data)
        except ValueError:
            return {"valid": False, "errors": ["Credential type is not supported by Extole"], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None,
                                credential_id=None):
        # Staging resolves and admits stored credentials before execution and
        # option loading. Extole uses a supplied token, with no refresh flow.
        credential = shaped_credential(credential_data)
        if credential.expires_at:
            expiry = datetime.fromisoformat(credential.expires_at.replace("Z", "+00:00"))
            if expiry <= datetime.now(timezone.utc):
                raise ValueError("Extole access token has expired; supply a current token")
        return credential.model_dump()

    async def _current(self):
        self._guard_raw(self.node_data)
        if self.config.credentials is None:
            raise ValueError("Connect an Extole client access token")
        return shaped_credential(await self.freshen_credential(self.config.credentials.model_dump()))

    @classmethod
    def _token_metadata(cls, raw, credential):
        result = projected(TokenMetadata, raw)
        if not SERVER_SCOPES.intersection(result["scopes"]):
            raise ValueError("Use a client-scoped server token, not a consumer token")
        if result.get("expires_in") is not None and result["expires_in"] <= 0:
            raise ValueError("Extole returned an expired token")
        if credential.expected_client_id and result["client_id"] != credential.expected_client_id:
            raise ValueError("Extole token belongs to a different client")
        return result

    @classmethod
    async def _request(cls, credential, method, path, *, query=None, body=None, events=False):
        origin = EVENT_ORIGIN if events else API_ORIGIN
        try:
            with private_transport_logs():
                return await cls._request_private(credential, method, origin + path, query=query, body=body)
        except ExtoleHTTPError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("Extole returned malformed JSON") from None
        except (httpx.RequestError, httpx.InvalidURL, ValueError):
            # Guard/transport exceptions can quote private lookup query values.
            raise ValueError("Extole request did not complete; saved credential validity is unverified") from None

    @classmethod
    async def _request_private(cls, credential, method, url, *, query=None, body=None):
        async with guarded_async_client(trust_env=False,
                                        follow_redirects=False, timeout=20.0) as client:
            async with client.stream(method, url, params=query,
                json=body, headers={"Authorization": f"Bearer {credential.access_token}",
                                    "Accept": "application/json"}) as response:
                if response.status_code != 200:
                    raise ExtoleHTTPError(response.status_code)
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type != "application/json":
                    raise ValueError("Extole returned an unexpected content type")
                chunks = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_RESPONSE_BYTES:
                        raise ValueError("Extole response exceeded the metadata size limit")
                    chunks.append(chunk)
        return json.loads(b"".join(chunks))

    async def _call(self, method, path, *, query=None, body=None, events=False):
        credential = await self._current()
        if credential.expected_client_id and path != "/v4/tokens":
            meta = await self._request(credential, "GET", "/v4/tokens")
            self._token_metadata(meta, credential)
            latest = await self._current()
            if latest.model_dump() != credential.model_dump():
                raise ValueError("Extole credential changed during the client check; retry")
        return await self._request(credential, method, path, query=query, body=body, events=events)

    async def execute(self, input_data):
        self._guard_raw(self.node_data)
        config = self._config.config
        op = config.operation
        query = None
        body = None
        method = "GET"
        events = False
        result_model = None
        is_list = False
        if op == "check_connection":
            credential = await self._current()
            raw = await self._request(credential, "GET", "/v4/tokens")
            data = self._token_metadata(raw, credential)
            if (await self._current()).model_dump() != credential.model_dump():
                raise ValueError("Extole credential changed during the connection check; retry")
            return {"operation": op, "http_status": 200, "data": data}
        if op == "search_participants":
            path = "/v5/persons"
            query = {"limit": config.limit, "offset": config.offset}
            if config.identity_key_value:
                query["identity_key_value"] = config.identity_key_value
            if config.person_keys:
                query["person_keys"] = config.person_keys
            result_model, is_list = ParticipantMetadata, True
        elif op == "create_participant":
            path, method = "/v5/persons", "POST"
            body = {"identity_key_value": config.identity_key_value}
            result_model = ParticipantMetadata
        elif op in {"get_participant", "update_participant"}:
            path = "/v5/persons/" + path_id(config.person_id)
            if op == "update_participant":
                method, body = "PUT", {"identity_key_value": config.identity_key_value}
            result_model = ParticipantMetadata
        elif op in {"list_participant_data", "create_participant_data",
                    "get_participant_data", "update_participant_data", "delete_participant_data"}:
            path = "/v5/persons/" + path_id(config.person_id) + "/data"
            if op == "list_participant_data":
                query = {"limit": config.limit, "offset": config.offset}
            elif op == "create_participant_data":
                method = "POST"
                body = {"name": config.name, "value": config.value, "scope": "PRIVATE"}
            else:
                path += "/" + path_id(config.name)
                if op == "update_participant_data":
                    method, body = "PUT", {"value": config.value}
                elif op == "delete_participant_data":
                    method = "DELETE"
            result_model = DataMetadata
        elif op in {"list_referral_relationships", "list_participant_journeys"}:
            suffix = "/relationships" if op == "list_referral_relationships" else "/journeys"
            path = "/v5/persons/" + path_id(config.person_id) + suffix
            query = {"limit": config.limit, "offset": config.offset}
            if op == "list_referral_relationships":
                query.update({key: str(getattr(config, key)).lower() for key in (
                    "exclude_anonymous", "include_duplicate_identities", "include_self_referrals")})
                if config.my_roles:
                    query["my_roles"] = config.my_roles
            result_model = ReferralMetadata if op == "list_referral_relationships" else JourneyMetadata
            is_list = True
        elif op == "list_campaign_summaries":
            path = "/v2/campaign-summaries"
            query = {"include_archived": str(config.include_archived).lower()}
            if config.states:
                query["states"] = config.states
            if config.tags:
                query["tags"] = config.tags
            result_model, is_list = CampaignMetadata, True
        elif op in {"get_campaign_summary", "get_campaign_metadata", "update_campaign_metadata", "delete_campaign_draft"}:
            path = ("/v2/campaign-summaries/" if op == "get_campaign_summary" else "/v2/campaigns/") + path_id(config.campaign_id)
            if op in {"update_campaign_metadata", "delete_campaign_draft"}:
                before = projected(CampaignMetadata, await self._call("GET", path))
                if before["campaign_id"] != config.campaign_id:
                    raise ValueError("Extole returned a different campaign")
                if before["is_published"] or before["state"] != "NOT_LAUNCHED":
                    raise ValueError("This operation requires an unpublished, not-launched campaign")
                if op == "delete_campaign_draft":
                    method = "DELETE"
                else:
                    method = "PUT"
                    body = config.model_dump(include={"name", "description", "tags"}, exclude_unset=True)
            result_model = CampaignMetadata
        elif op == "create_campaign_draft":
            path, method = "/v2/campaigns", "POST"
            body = {"name": config.name, "tags": config.tags}
            if "description" in config.model_fields_set:
                body["description"] = config.description
            result_model = CampaignMetadata
        elif op == "list_report_types":
            path = "/v6/report-types"
            query = {"limit": config.limit, "offset": config.offset}
            if config.search_query:
                query["search_query"] = config.search_query
            result_model, is_list = ReportTypeMetadata, True
        elif op == "list_reports":
            path = "/v4/reports"
            query = {"limit": str(config.limit), "offset": str(config.offset)}
            if config.report_type_name:
                query["report_type_name"] = config.report_type_name
            result_model, is_list = ReportMetadata, True
        elif op == "create_report":
            path, method = "/v4/reports", "POST"
            body = config.model_dump(exclude={"operation"}, exclude_unset=True)
            body.update({"name": config.name, "report_type": config.report_type, "parameters": config.parameters})
            result_model = ReportMetadata
        elif op in {"get_report", "update_report", "delete_report"}:
            path = "/v4/reports/" + path_id(config.report_id)
            if op == "update_report":
                method = "PUT"
                body = config.model_dump(include={"display_name", "tags"}, exclude_unset=True)
            elif op == "delete_report":
                method = "DELETE"
            result_model = ReportMetadata
        elif op == "get_opt_out_status":
            path, query = "/v4/optouts", {"email": config.email}
        elif op in {"submit_event", "submit_async_event"}:
            path = "/v6/events" if op == "submit_event" else "/v6/async-events"
            method, events = "POST", True
            body = {"event_name": config.event_name}
            if config.event_time is not None:
                body["event_time"] = config.event_time
            if config.data is not None:
                body["data"] = config.data.model_dump(exclude={"properties"}, exclude_none=True)
                body["data"].update(config.data.properties)
            bounded_json(body)
        else:
            raise ValueError("Unsupported Extole operation")

        raw = await self._call(method, path, query=query, body=body, events=events)
        if op == "list_participant_data":
            if not isinstance(raw, dict) or len(raw) > 100:
                raise ValueError("Extole returned malformed participant data metadata")
            data = {}
            for name, item in raw.items():
                row = projected(DataMetadata, item)
                if name != row["name"]:
                    raise ValueError("Extole participant data name does not match its map key")
                data[name] = row
        elif op == "get_opt_out_status":
            if (not isinstance(raw, dict) or raw.get("email") != config.email
                    or type(raw.get("optout")) is not bool):
                raise ValueError("Extole returned malformed or mismatched consent metadata")
            data = {"optout": raw["optout"]}
        elif events:
            data = projected(EventReceipt if op == "submit_event" else AsyncEventReceipt, raw)
            data.update({"receipt_stage": "queued" if op == "submit_async_event" else "person_identified",
                         "reward_completion": "unknown", "notification_completion": "unknown"})
        else:
            data = projected_list(result_model, raw) if is_list else projected(result_model, raw)
        if op in {"get_participant", "update_participant"} and data["id"] != config.person_id:
            raise ValueError("Extole returned a different participant")
        if op in {"get_participant_data", "update_participant_data", "delete_participant_data"} and data["name"] != config.name:
            raise ValueError("Extole returned a different participant data parameter")
        if op == "list_referral_relationships" and any(row["person_id"] != config.person_id for row in data):
            raise ValueError("Extole returned relationships for a different participant")
        if op in {"get_campaign_summary", "get_campaign_metadata", "update_campaign_metadata", "delete_campaign_draft"} and data["campaign_id"] != config.campaign_id:
            raise ValueError("Extole returned a different campaign")
        if op == "create_campaign_draft" and (data["is_published"] or data["state"] != "NOT_LAUNCHED"):
            raise ValueError("Extole did not return an unpublished campaign")
        if op in {"get_report", "update_report", "delete_report"} and data["report_id"] != config.report_id:
            raise ValueError("Extole returned a different report")
        result = {"operation": op, "http_status": 200, "data": data}
        if op == "create_report":
            result["execution"] = "asynchronous"
            result["readback_operation"] = "get_report"
        if hasattr(config, "limit") and (is_list or op == "list_participant_data"):
            if len(data) > config.limit:
                raise ValueError("Extole returned more than the requested metadata page")
            # Full pages are inconclusive: no total or invented completion claim.
            result["pagination"] = {"limit": config.limit, "offset": config.offset,
                                    "next_offset": config.offset + config.limit if len(data) == config.limit else None}
        return result

    @classmethod
    async def load_field_options(cls, field_name, credential_data=None, context=None,
                                 page_token=None, search=None):
        context = context or {}
        if page_token is not None and (not isinstance(page_token, str)
                or not re.fullmatch(r"0|[1-9][0-9]{0,6}", page_token)
                or int(page_token) > 1000000):
            raise ValueError("Invalid Extole metadata page")
        offset = int(page_token or "0")
        args = {}
        if field_name == "campaign_id":
            if page_token is not None:
                raise ValueError("Campaign summaries do not advertise pagination")
            operation, key, label = "list_campaign_summaries", "campaign_id", "name"
        elif field_name == "report_id":
            operation, key, label = "list_reports", "report_id", "display_name"
            args = {"limit": 25, "offset": offset}
        elif field_name == "report_type":
            operation, key, label = "list_report_types", "name", "display_name"
            args = {"limit": 25, "offset": offset}
            if search:
                args["search_query"] = search
        elif field_name == "person_id":
            if not search:
                return {"options": [], "next_page_token": None}
            operation, key, label = "search_participants", "id", "id"
            args = {"identity_key_value": search, "limit": 25, "offset": offset}
        elif field_name == "data_name":
            if not context.get("person_id"):
                raise ValueError("Select an explicit participant before its data parameter")
            operation, key, label = "list_participant_data", "name", "name"
            args = {"person_id": context["person_id"], "limit": 25, "offset": offset}
        else:
            return {"options": [], "next_page_token": None}
        # Staging resolves credentials before invoking option loaders.
        parsed = cls.parse_config({"config": {"operation": operation, **args},
                                   "credentials": credential_data})
        node = cls("extole-options", "automation-extole", {"credentials": credential_data}, config=parsed)
        result = await node.execute({})
        rows = list(result["data"].values()) if isinstance(result["data"], dict) else result["data"]
        options = [{"value": row[key], "label": safe_label(row[label])} for row in rows
                   if not search or field_name in {"person_id", "report_type"}
                   or search.casefold() in row[label].casefold()]
        next_offset = result.get("pagination", {}).get("next_offset")
        return {"options": options, "next_page_token": str(next_offset) if next_offset is not None else None}
