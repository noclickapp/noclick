"""Aimtell v1.1 sites, campaigns, segments and subscriber automation.

Each action makes one request to the pinned public API; queued push requests
are acknowledgements, and provider authentication tokens never enter outputs.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.aimtell.com"


class AimtellAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Aimtell API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.aimtell.com/api-reference/introduction",
            "x-credential-instructions": "In the Aimtell dashboard, open Settings > API Key. Paste your API key. NoClick sends it in the X-Authorization-Api-Key header to api.aimtell.com and reads your websites to check the connection.",
        })
    credential_type: Literal["aimtell_api_key"] = Field("aimtell_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Site(_Input):
    site_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[0-9]+$", description="Aimtell website ID.")


class _Campaign(_Input):
    campaign_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[0-9]+$")


class _Segment(_Input):
    segment_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[0-9]+$")


class GetUser(_Input):
    operation: Literal["get_user"] = "get_user"


class ListSites(_Input):
    operation: Literal["list_sites"] = "list_sites"
    limit: int = Field(100, ge=1, le=1000)
    skip: int = Field(0, ge=0)
    load: str | None = Field(None, description="Additional information, such as subscriber_count.")


class GetSite(_Site):
    operation: Literal["get_site"] = "get_site"


class ListVariables(_Site):
    operation: Literal["list_variables"] = "list_variables"


class UpsertVariable(_Site):
    operation: Literal["upsert_variable"] = "upsert_variable"
    name: str = Field(..., min_length=1)
    value: str


class DeleteVariable(_Site):
    operation: Literal["delete_variable"] = "delete_variable"
    name: str = Field(..., min_length=1)


class SendPush(_Input):
    """Queue one push for an explicit audience; delivery is not verified."""
    operation: Literal["send_push"] = "send_push"
    site_id: int = Field(..., ge=1)
    title: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)
    link: str = Field(..., min_length=1)
    subscriber_uids: list[str] | None = Field(None, min_length=1)
    segment_id: int | None = Field(None, ge=1)
    alias: str | None = Field(None, pattern=r"^(user|email)==.+$")
    push_ttl: int = Field(604800, ge=0)
    auto_hide: int | None = Field(None, ge=0, le=255)
    collapse_key: str | None = None
    custom_icon: str | None = None
    custom_image: str | None = None

    @model_validator(mode="after")
    def audience(self):
        if sum(v is not None for v in (self.subscriber_uids, self.segment_id, self.alias)) != 1:
            raise ValueError("Choose exactly one audience: subscriber UIDs, segment ID or alias")
        return self


class CreateCampaign(_Site):
    operation: Literal["create_campaign"] = "create_campaign"
    name: str = Field(..., min_length=1)
    title: str | None = None
    body: str | None = None
    link: str | None = None
    segments: str | None = None
    status: Literal["1"] = Field("1", description="Creates a draft campaign. Schedule it in Aimtell.")


class GetCampaign(_Campaign):
    operation: Literal["get_campaign"] = "get_campaign"
    load: str | None = None


class UpdateCampaign(_Campaign):
    operation: Literal["update_campaign"] = "update_campaign"
    name: str | None = None
    title: str | None = None
    body: str | None = None
    link: str | None = None
    segments: str | None = None

    @model_validator(mode="after")
    def changes(self):
        if all(getattr(self, k) is None for k in ("name", "title", "body", "link", "segments")):
            raise ValueError("Supply a campaign field to update")
        return self


class DeleteCampaign(_Campaign):
    operation: Literal["delete_campaign"] = "delete_campaign"


class ListCampaigns(_Site):
    operation: Literal["list_campaigns"] = "list_campaigns"
    limit: int = Field(100, ge=1, le=1000)
    skip: int = Field(0, ge=0)


class GetCampaignClicks(_Campaign):
    operation: Literal["get_campaign_clicks"] = "get_campaign_clicks"


class GetCampaignResults(_Campaign):
    operation: Literal["get_campaign_results"] = "get_campaign_results"
    start_date: str = Field(..., min_length=1, description="Start date in the format accepted by Aimtell.")
    end_date: str = Field(..., min_length=1, description="End date in the format accepted by Aimtell.")
    include_shared: Literal[0, 1] = 0


class ListSegments(_Site):
    operation: Literal["list_segments"] = "list_segments"


class GetSegment(_Segment):
    operation: Literal["get_segment"] = "get_segment"


class CreateSegment(_Site):
    operation: Literal["create_segment"] = "create_segment"
    name: str = Field(..., min_length=1)
    definition: str = Field(..., min_length=1, description="Aimtell segment definition, for example region==California.")


class UpdateSegment(_Segment):
    operation: Literal["update_segment"] = "update_segment"
    name: str | None = None
    definition: str | None = None

    @model_validator(mode="after")
    def changes(self):
        if self.name is None and self.definition is None:
            raise ValueError("Supply a segment field to update")
        return self


class DeleteSegment(_Segment):
    operation: Literal["delete_segment"] = "delete_segment"


class ListSubscribers(_Input):
    operation: Literal["list_subscribers"] = "list_subscribers"
    site_id: int = Field(..., ge=1)
    limit: int = Field(100, ge=1, le=1000)
    skip: int = Field(0, ge=0)
    include: Literal["attributes", "notifications", "attributes,notifications"] | None = None
    segment_id: int | None = Field(None, ge=1)
    subscriber_id: str | None = None


AimtellConfig = Annotated[Union[
    GetUser, ListSites, GetSite, ListVariables, UpsertVariable, DeleteVariable,
    SendPush, CreateCampaign, GetCampaign, UpdateCampaign, DeleteCampaign,
    ListCampaigns, GetCampaignClicks, GetCampaignResults, ListSegments,
    GetSegment, CreateSegment, UpdateSegment, DeleteSegment, ListSubscribers,
], Field(discriminator="operation")]


class AimtellFullConfig(NodeConfig[AimtellConfig, AimtellAPIKeyCredential]):
    pass


# method, path, path config field, body fields, query fields. Each row names one
# operation in Aimtell's five published v1.1 OpenAPI documents.
ROUTES = {
    "get_user": ("GET", "/prod/user/", None, (), ()),
    "list_sites": ("GET", "/prod/sites/", None, (), ("limit", "skip", "load")),
    "get_site": ("GET", "/prod/site/{id}", "site_id", (), ()),
    "list_variables": ("GET", "/prod/site/variables/{id}", "site_id", (), ()),
    "upsert_variable": ("POST", "/prod/site/variables/{id}", "site_id", ("name", "value"), ()),
    "delete_variable": ("DELETE", "/prod/site/variables/{id}", "site_id", ("name",), ()),
    "send_push": ("POST", "/prod/push/", None, ("site_id", "title", "body", "link", "subscriber_uids", "segment_id", "alias", "push_ttl", "auto_hide", "collapse_key", "custom_icon", "custom_image"), ()),
    "create_campaign": ("POST", "/prod/campaigns/", None, ("site_id", "name", "title", "body", "link", "segments", "status"), ()),
    "get_campaign": ("GET", "/prod/campaign/{id}", "campaign_id", (), ("load",)),
    "update_campaign": ("PUT", "/prod/campaign/{id}", "campaign_id", ("name", "title", "body", "link", "segments"), ()),
    "delete_campaign": ("DELETE", "/prod/campaign/{id}", "campaign_id", (), ()),
    "list_campaigns": ("GET", "/prod/campaigns/{id}", "site_id", (), ("limit", "skip")),
    "get_campaign_clicks": ("GET", "/prod/campaign/{id}/clicks", "campaign_id", (), ()),
    "get_campaign_results": ("GET", "/prod/campaign/{id}/results", "campaign_id", (), ("start_date", "end_date", "include_shared")),
    "list_segments": ("GET", "/prod/segments/{id}", "site_id", (), ()),
    "get_segment": ("GET", "/prod/segment/{id}", "segment_id", (), ()),
    "create_segment": ("POST", "/prod/segments/", None, ("site_id", "name", "definition"), ()),
    "update_segment": ("PUT", "/prod/segment/{id}", "segment_id", ("name", "definition"), ()),
    "delete_segment": ("DELETE", "/prod/segment/{id}", "segment_id", (), ()),
    "list_subscribers": ("GET", "/prod/subscribers/{id}", "site_id", (), ("limit", "skip", "include", "segment_id", "subscriber_id")),
}
WIRE_NAMES = {"site_id": "idSite", "segment_id": "segmentId", "subscriber_id": "subscriberId",
    "start_date": "startDate", "end_date": "endDate", "include_shared": "includeShared",
    "custom_icon": "customIcon", "custom_image": "customImage"}
LIST_OPERATIONS = {"list_sites", "list_variables", "list_campaigns", "get_campaign_clicks", "list_segments"}
SECRET_KEYS = {"auth_token", "api_key", "access_token", "refresh_token", "password", "secret"}


def _redact(value, token):
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items() if k.lower() not in SECRET_KEYS}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    return value


class AimtellNode(WorkflowNode):
    integration_type = "automation-aimtell"
    connection_evidence = ConnectionEvidence(noun="websites", operation="list_sites", identity_operation="get_user", identity_keys=("username", "first_name", "uid"))

    @classmethod
    def get_config_model(cls):
        return AimtellFullConfig

    async def execute(self, inputs):
        config = self.config
        if not isinstance(config, AimtellFullConfig) or not config.credentials:
            raise ValueError("Attach an Aimtell API key")
        op, credential = config.config, config.credentials
        method, path, path_field, body_fields, query_fields = ROUTES[op.operation]
        if path_field:
            path = path.replace("{id}", quote(str(getattr(op, path_field)), safe=""))
        def fields(names):
            return {WIRE_NAMES.get(k, k): getattr(op, k) for k in names if getattr(op, k) is not None}
        kwargs = {"params": fields(query_fields)}
        if body_fields:
            kwargs["json"] = fields(body_fields)
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"X-Authorization-Api-Key": credential.api_key, "Accept": "application/json"}, **kwargs)
            if len(response.content) > 5_000_000:
                raise ValueError("Aimtell response exceeded 5 MB; request a smaller page")
            mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if mime != "application/json":
                raise ValueError("Expected an Aimtell JSON response")
            payload = response.json()
            error = isinstance(payload, dict) and (payload.get("result") == "error" or payload.get("error"))
            if not 200 <= response.status_code < 300 or error or payload is False:
                message = payload.get("message", "Aimtell request rejected") if isinstance(payload, dict) else "Aimtell request rejected"
                return {"status": "error", "error": _redact(str(message), credential.api_key), "http_status": response.status_code}
            if op.operation in LIST_OPERATIONS:
                if not isinstance(payload, list):
                    raise ValueError("Expected an Aimtell resource list")
            elif op.operation in {"upsert_variable", "delete_variable"}:
                if payload is not True:
                    raise ValueError("Expected Aimtell to acknowledge the custom variable change")
            elif not isinstance(payload, dict):
                raise ValueError("Expected an Aimtell response object")
            if method != "GET" and op.operation not in {"upsert_variable", "delete_variable"}:
                if payload.get("result") != "success":
                    raise ValueError("Aimtell did not acknowledge the change")
            if op.operation == "send_push" and not payload.get("objectId"):
                raise ValueError("Aimtell did not return a queued push ID")
            result = {"status": "success", "data": _redact(payload, credential.api_key), "http_status": response.status_code}
            if op.operation == "send_push":
                result.update(queued=True, delivery_verified=False)
            if op.operation in {"list_sites", "list_campaigns", "list_subscribers"}:
                rows = payload.get("subscribers") if isinstance(payload, dict) else payload
                if not isinstance(rows, list):
                    raise ValueError("Expected an Aimtell subscriber list")
                # Offset pagination is explicit. A full page may have a successor;
                # a short page is terminal, without silently crawling more pages.
                result["next_skip"] = op.skip + len(rows) if len(rows) >= op.limit else None
            return result
        except httpx.HTTPError:
            return {"status": "error", "error": "Aimtell request could not be completed; inspect writes before retrying"}
