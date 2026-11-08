"""ZoomInfo GTM v1 prospect data and audience automation.

Search filters use the provider's named attributes; NoClick builds JSON:API
resource envelopes. Enrichment is explicit and can consume ZoomInfo credits.
Pages are returned individually, including the provider's links and metadata.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.oauth.zoominfo_oauth import OAUTH_PROVIDER
from nodes.scopes.zoominfo import ZOOMINFO_SCOPES
from nodes.zoominfo_operations import ZOOMINFO_OPERATIONS, OUTPUT_FIELDS
from utils.ssrf import guarded_async_client

BASE = "https://api.zoominfo.com/gtm"
MEDIA = "application/vnd.api+json"


def _object(raw):
    try:
        value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError):
        raise ValueError("Use a JSON object with ZoomInfo filter attributes") from None
    if not isinstance(value, dict) or not value:
        raise ValueError("Supply at least one ZoomInfo search filter")
    return value


class ZoomInfoOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Zoominfo OAuth", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "zoominfo",
        "x-oauth-scopes": ZOOMINFO_SCOPES.declared_scopes(),
        "x-credential-url": "https://docs.gtm.ai/docs/standard-app",
    })
    credential_type: Literal["zoominfo_oauth"] = Field("zoominfo_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field(..., repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: str = Field(..., title="Token expiry")

    @field_validator("access_token", "refresh_token", mode="before")
    @classmethod
    def secret(cls, value):
        return clean_secret(value, field_name="OAuth token")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def check_values(self):
        if hasattr(self, "filters"):
            filters = _object(self.filters)
            if self.operation == "search_intent" and (not isinstance(filters.get("topics"), list) or not filters["topics"]):
                raise ValueError("Intent search requires a nonempty topics array")
        for name in ("audience_id", "upload_id"):
            if hasattr(self, name):
                value = getattr(self, name)
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}", value):
                    raise ValueError("Use a single ZoomInfo resource ID")
        if hasattr(self, "records") and any(len(row) != len(self.fields) for row in self.records):
            raise ValueError("Every member record must match the fields in order")
        return self


def _model(name, spec):
    fields = {"operation": (Literal[name], Field(name, json_schema_extra={"ui:hidden": True, "x-display-name": name.replace("_", " ").title()}))}
    kind = spec["kind"]
    if kind == "search":
        fields.update(
            filters=(str, Field(..., max_length=100000, title="Search filters (JSON)", description="ZoomInfo attributes, for example " + json.dumps(spec["example"]) + ". See " + spec["source"], json_schema_extra={"ui:widget": "textarea"})),
            page_number=(int, Field(1, ge=1)),
            page_size=(int, Field(25, ge=1, le=100)),
        )
        if spec["sort"]:
            fields["sort"] = (str | None, Field(None, max_length=200, description="Provider field name; prefix with - for descending order."))
    if kind == "enrich":
        contact = name == "enrich_contacts"
        fields["record_ids"] = (list[Annotated[int, Field(gt=0)]], Field(..., min_length=1, max_length=25, description="ZoomInfo person IDs." if contact else "ZoomInfo company IDs."))
        fields["output_fields"] = (list[Literal[tuple(OUTPUT_FIELDS[name])]], Field(..., min_length=1, max_length=100, description="Use Lookup Enrich Fields to choose entitled output fields. Each returned new record can consume a credit."))
    if kind == "lookup":
        choices = ("company", "contact", "scoop", "news", "intent")
        if name == "lookup_enrich_fields":
            choices += ("technology", "hashtag", "orgChart", "corporate-hierarchy")
        fields["entity"] = (Literal[choices], Field(...))
        fields["field_type"] = (Literal["input", "output"], Field("input"))
    if "{audienceId}" in spec["path"]:
        fields["audience_id"] = (str, Field(..., title="Audience ID"))
    if "{uploadId}" in spec["path"]:
        fields["upload_id"] = (str, Field(..., title="Upload ID"))
    if kind == "list":
        fields["page_size"] = (int, Field(25, ge=1, le=100))
        fields["page_token"] = (str | None, Field(None, max_length=8192, description="Use the provider's continuation token for the next page."))
    if kind in {"create", "update"}:
        fields["name"] = (str, Field(..., min_length=1, max_length=500, title="Audience name"))
    if kind == "create":
        fields["audience_type"] = (Literal["B2B", "B2C"], Field("B2B"))
    if kind == "upload":
        fields["upload_operation"] = (Literal["ADD", "DELETE"], Field(..., description="Add or remove these audience members."))
        fields["fields"] = (list[Literal["ziCompanyId", "ziPersonId", "firstName", "lastName", "emailAddress", "companyName", "companyUrl"]], Field(..., min_length=1, max_length=7))
        fields["records"] = (list[list[str]], Field(..., min_length=1, max_length=10000, description="Member rows, in the exact order of fields."))
    return create_model("ZoomInfo" + "".join(p.title() for p in name.split("_")) + "Config", __base__=_Input, __doc__=name.replace("_", " ").title() + ". " + spec["source"], **fields)


ZOOMINFO_CONFIGS = {name: _model(name, spec) for name, spec in ZOOMINFO_OPERATIONS.items()}
ZoomInfoConfig = Annotated[Union[tuple(ZOOMINFO_CONFIGS.values())], Field(discriminator="operation")]


class ZoomInfoNodeConfig(NodeConfig[ZoomInfoConfig, ZoomInfoOAuthCredential]):
    pass


class ZoomInfoNode(WorkflowNode):
    integration_type = "automation-zoominfo"
    scope_registry = ZOOMINFO_SCOPES
    connection_evidence = ConnectionEvidence(operation="get_usage", noun="ZoomInfo account usage and limits")

    @classmethod
    def get_config_model(cls):
        return ZoomInfoNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=OAUTH_PROVIDER.refresh, provider="zoominfo")

    async def execute(self, inputs):
        if not isinstance(self.config, ZoomInfoNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a ZoomInfo account")
        cfg = self.config.config
        spec = ZOOMINFO_OPERATIONS[cfg.operation]
        kind = spec["kind"]
        path = spec["path"]
        for field, param in (("audience_id", "audienceId"), ("upload_id", "uploadId")):
            if hasattr(cfg, field):
                path = path.replace("{" + param + "}", quote(getattr(cfg, field), safe=""))
        query = {}
        body = None
        if kind == "search":
            query = {"page[number]": cfg.page_number, "page[size]": cfg.page_size}
            if getattr(cfg, "sort", None):
                query["sort"] = cfg.sort
            body = {"data": {"type": spec["resource"], "attributes": _object(cfg.filters)}}
        elif kind == "enrich":
            key, identifier = ("matchPersonInput", "personId") if cfg.operation == "enrich_contacts" else ("matchCompanyInput", "companyId")
            body = {"data": {"type": spec["resource"], "attributes": {key: [{identifier: i} for i in cfg.record_ids], "outputFields": cfg.output_fields}}}
        elif kind == "lookup":
            query = {"filter[entity]": cfg.entity, "filter[fieldType]": cfg.field_type}
        elif kind == "list":
            query = {"pageSize": cfg.page_size}
            if cfg.page_token:
                query["pageToken"] = cfg.page_token
        elif kind in {"create", "update"}:
            resource = {"type": "Audience", "attributes": {"name": cfg.name}}
            if kind == "create":
                resource["attributes"]["type"] = cfg.audience_type
            else:
                resource["id"] = cfg.audience_id
            body = {"data": resource}
        elif kind == "upload":
            body = {"data": {"type": "AudienceUpload", "attributes": {"operationType": cfg.upload_operation, "fields": cfg.fields, "records": cfg.records}}}
        credentials = self.config.credentials.model_dump()
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        token = await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=credentials, refresh=OAUTH_PROVIDER.refresh, provider="zoominfo", caller_path="execute")
        self.config.credentials = ZoomInfoOAuthCredential.model_validate(credentials)
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(spec["method"], BASE + path, params=query,
                    **({"json": body} if body is not None else {}),
                    headers={"Authorization": "Bearer " + token, "Accept": MEDIA, "Content-Type": MEDIA})
            if not 200 <= response.status_code < 300:
                message = f"ZoomInfo returned HTTP {response.status_code}"
                if response.status_code in {401, 403}:
                    try:
                        error = response.json()
                        details = [e.get("detail") for e in error.get("errors", []) if isinstance(e, dict)]
                        text = "; ".join(d for d in details if isinstance(d, str))
                        if text:
                            message = text[:2000]
                            for secret in (token, credentials.get("refresh_token")):
                                if secret:
                                    message = message.replace(secret, "[redacted]")
                    except (ValueError, AttributeError, TypeError):
                        pass
                return {"status": "error", "http_status": response.status_code, "error": message}
            if response.status_code == 204:
                return {"status": "success", "operation": cfg.operation, "http_status": 204}
            if len(response.content) > 10_000_000:
                raise ValueError("ZoomInfo response exceeds the JSON limit")
            if response.headers.get("content-type", "").split(";", 1)[0].lower() not in {MEDIA, "application/json"}:
                raise ValueError("Expected a ZoomInfo JSON response")
            payload = response.json()
            if not isinstance(payload, dict) or "errors" in payload or "data" not in payload or not isinstance(payload["data"], (dict, list)):
                raise ValueError("ZoomInfo returned an unexpected JSON:API response")
            if kind == "usage" and (not isinstance(payload["data"], list) or not payload["data"] or any(not isinstance(r, dict) or not isinstance(r.get("id"), str) or not r["id"] or r.get("type") != "UserUsage" or not isinstance(r.get("attributes"), dict) or not isinstance(r["attributes"].get("usage"), list) for r in payload["data"])):
                raise ValueError("ZoomInfo returned no account usage evidence")
            return {"status": "success", "operation": cfg.operation, "http_status": response.status_code, **{key: payload[key] for key in ("data", "links", "meta") if key in payload}}
        except (httpx.HTTPError, ValueError):
            return {"status": "error", "error": "ZoomInfo request could not be confirmed"}
