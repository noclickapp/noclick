"""ZoomInfo GTM v1 prospect data and audience automation.

Search filters use the provider's named attributes; NoClick builds JSON:API
resource envelopes. Enrichment is explicit and can consume ZoomInfo credits.
Pages are returned individually, including the provider's links and metadata.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.oauth.zoominfo_oauth import OAUTH_PROVIDER
from nodes.scopes.zoominfo import ZOOMINFO_SCOPES
from nodes.zoominfo_operations import ZOOMINFO_OPERATIONS, ZOOMINFO_TRIGGERS, OUTPUT_FIELDS
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
            if self.operation in {"search_intent", "on_new_intent"} and (not isinstance(filters.get("topics"), list) or not filters["topics"]):
                raise ValueError("Intent search requires a nonempty topics array")
        for name in ("audience_id", "upload_id"):
            if hasattr(self, name):
                value = getattr(self, name)
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}", value):
                    raise ValueError("Use a single ZoomInfo resource ID")
        if hasattr(self, "records") and any(len(row) != len(self.fields) for row in self.records):
            raise ValueError("Every member record must match the fields in order")
        return self


class _PollInput(PollTriggerConfigBase, _Input):
    # Canvas metadata is ignored; the poll family hashes declared fields only.
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


def _model(name, spec):
    fields = {"operation": (Literal[name], Field(name, json_schema_extra={"ui:hidden": True, "x-display-name": name.replace("_", " ").title()}))}
    kind = spec["kind"]
    if kind in {"search", "poll"}:
        fields.update(
            filters=(str, Field(..., max_length=100000, title="Search filters (JSON)", description="ZoomInfo attributes, for example " + json.dumps(spec["example"]) + ". See " + spec["source"], json_schema_extra={"ui:widget": "textarea"})),
        )
        if kind == "search":
            fields["page_number"] = (int, Field(1, ge=1))
            fields["page_size"] = (int, Field(25, ge=1, le=100))
        if kind == "poll":
            fields["since"] = (date, Field(..., title="Monitor since", description="Earliest date to search (YYYY-MM-DD). Existing matches are baselined when armed; narrow the filters if more than 10,000 records match."))
        if kind == "search" and spec["sort"]:
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
    if kind == "poll":
        fields["operation"][1].json_schema_extra.update({
            "x-is-trigger": True, "x-category": "Triggers", "x-display-name": spec["label"],
        })
    return create_model("ZoomInfo" + "".join(p.title() for p in name.split("_")) + "Config", __base__=_PollInput if kind == "poll" else _Input, __doc__=name.replace("_", " ").title() + ". " + spec["source"], **fields)


ZOOMINFO_CONFIGS = {name: _model(name, spec) for name, spec in ZOOMINFO_OPERATIONS.items()}
ZoomInfoConfig = Annotated[Union[tuple(ZOOMINFO_CONFIGS.values())], Field(discriminator="operation")]


class ZoomInfoNodeConfig(NodeConfig[ZoomInfoConfig, ZoomInfoOAuthCredential]):
    pass


class ZoomInfoNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-zoominfo"
    scope_registry = ZOOMINFO_SCOPES
    connection_evidence = ConnectionEvidence(operation="get_usage", noun="ZoomInfo account usage and limits")

    @classmethod
    def get_config_model(cls):
        return ZoomInfoNodeConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") in ZOOMINFO_TRIGGERS:
            return bool(output.get("new_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        operation = output.get("operation")
        if operation not in ZOOMINFO_TRIGGERS:
            return super().resolve_agent_event(output)
        records = output.get("data", [])
        if not records:
            return None
        lines = []
        for record in records[:10]:
            attributes = record.get("attributes", {})
            company = attributes.get("company") or {}
            where = f"{company.get('name') or 'Company unspecified'} (company id {company.get('id') or 'unavailable'})"
            identifier = record["id"]
            if operation == "on_updated_contact":
                person = " ".join(str(attributes.get(k) or "") for k in ("firstName", "lastName")).strip()
                lines.append(f"- {person or 'Contact'} (contact id {identifier}), {attributes.get('jobTitle') or 'role unspecified'} at {where}; updated {attributes.get('lastUpdatedDate') or 'date unavailable'}")
            elif operation == "on_new_scoop":
                lines.append(f"- {where}: {attributes.get('description') or 'New scoop'} (scoop id {identifier}, published {attributes.get('publishedDate') or 'date unavailable'}) {attributes.get('link') or ''}")
            else:
                lines.append(f"- {where}: intent for {attributes.get('topic') or 'topic unspecified'}, score {attributes.get('signalScore')}, signal date {attributes.get('signalDate')} (intent id {identifier})")
        if len(records) > 10:
            lines.append(f"- … and {len(records) - 10} more; all records are in the trigger output")
        return {"text": f"ZoomInfo: {len(records)} {ZOOMINFO_TRIGGERS[operation]['label'].lower()} event(s):\n" + "\n".join(lines), "conversation_key": None}

    async def _poll(self, token, cfg, spec, credentials):
        attributes = _object(cfg.filters)
        attributes[spec["date_filter"]] = cfg.since.isoformat()
        body = {"data": {"type": spec["resource"], "attributes": attributes}}
        records = []
        for page in range(1, 101):
            query = {"page[number]": page, "page[size]": 100}
            if spec["sort"]:
                query["sort"] = spec["sort"]
            result = await self._request(token, cfg.operation, spec, spec["path"], query, body, credentials)
            if result.get("status") != "success":
                return result
            batch = result["data"]
            if not isinstance(batch, list) or any(not isinstance(r, dict) or not r.get("id") or not isinstance(r.get("attributes"), dict) for r in batch):
                return {"status": "error", "error": "ZoomInfo returned an unexpected search page"}
            records.extend(batch)
            total = (result.get("meta") or {}).get("totalResults")
            if not batch or (isinstance(total, int) and len(records) >= total) or (total is None and len(batch) < 100):
                break
        else:
            return {"status": "error", "error": "ZoomInfo monitoring exceeds 10,000 records; narrow the filters or monitor-since date"}
        def identity(record):
            identifier = str(record["id"])
            if cfg.operation == "on_updated_contact":
                # A new version of the same contact is a new event.
                identifier += ":" + str(record["attributes"].get("lastUpdatedDate") or "")
            return identifier
        unique = {identity(record): record for record in records}
        fresh = await self._filter_unseen(list(unique.values()), identity)
        return {"status": "success", "operation": cfg.operation, "data": fresh, "new_count": len(fresh)}

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
        if kind == "poll":
            return await self._poll(token, cfg, spec, credentials)
        return await self._request(token, cfg.operation, spec, path, query, body, credentials)

    async def _request(self, token, operation, spec, path, query, body, credentials):
        kind = spec["kind"]
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
                return {"status": "success", "operation": operation, "http_status": 204}
            if len(response.content) > 10_000_000:
                raise ValueError("ZoomInfo response exceeds the JSON limit")
            if response.headers.get("content-type", "").split(";", 1)[0].lower() not in {MEDIA, "application/json"}:
                raise ValueError("Expected a ZoomInfo JSON response")
            payload = response.json()
            if not isinstance(payload, dict) or "errors" in payload or "data" not in payload or not isinstance(payload["data"], (dict, list)):
                raise ValueError("ZoomInfo returned an unexpected JSON:API response")
            if kind == "usage" and (not isinstance(payload["data"], list) or not payload["data"] or any(not isinstance(r, dict) or not isinstance(r.get("id"), str) or not r["id"] or r.get("type") != "UserUsage" or not isinstance(r.get("attributes"), dict) or not isinstance(r["attributes"].get("usage"), list) for r in payload["data"])):
                raise ValueError("ZoomInfo returned no account usage evidence")
            return {"status": "success", "operation": operation, "http_status": response.status_code, **{key: payload[key] for key in ("data", "links", "meta") if key in payload}}
        except (httpx.HTTPError, ValueError):
            return {"status": "error", "error": "ZoomInfo request could not be confirmed"}
