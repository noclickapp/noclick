"""MyCRM JSON:API v1 operations using an issued, manually supplied bearer token.

Contract: loanmarket/mycrm-api-sample, MyCrmSampleClient/swagger.json.
Service URLs and adviser context are issued by LMG; tokens expire and must be
replaced. This credential is not an interactive OAuth authorization-code flow.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union

import httpx
from pydantic import AwareDatetime, AfterValidator, BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client, normalize_https_origin

NODE_TYPE = "automation-mycrm-leads"
MEDIA = "application/vnd.api+json"
ID = Annotated[str, Field(pattern=r"^[1-9]\d*$", max_length=20)]
Text = Annotated[str, Field(min_length=1, max_length=100)]


def _path_id(value):
    if int(value) > 2147483647:
        raise ValueError("Use an ID within the API's int32 range")
    return value


PathID = Annotated[str, Field(pattern=r"^[1-9]\d*$", max_length=10), AfterValidator(_path_id)]


class MyCRMLeadsAccessToken(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="MyCRM Leads Access Token",
        json_schema_extra={
            "x-credential-url": "https://api-docs.mycrm.io/guides/integrate/oauth/",
            "x-credential-instructions": "Use the API base URL and adviser contact ID issued by LMG. Paste an existing access_token obtained with your issued client ID, client secret and approved scopes using MyCRM's client_credentials flow. Leads-only credentials are available in MyCRM Profile Management → API Access Management; other operations require additional access from LMG. Tokens expire: replace the token here when it expires. NoClick does not exchange or refresh tokens. The API base URL must be the issued HTTPS origin before /jsonapi. Listing contacts proves contact-search access; leads-only credentials may save as unverified or be rejected if they lack that access.",
        })
    credential_type: Literal["mycrm_leads_access_token"] = Field("mycrm_leads_access_token", json_schema_extra={"ui:hidden": True})
    api_base_url: str = Field(..., title="API base URL", description="Issued HTTPS origin, without /jsonapi; service URLs differ by environment.")
    access_token: str = Field(..., min_length=1, max_length=16384, title="Access token", json_schema_extra={"ui:widget": "password"})
    adviser_contact_id: ID = Field(..., title="Adviser contact ID", description="The UserId context supplied with your API access, not a client contact ID.")

    @field_validator("api_base_url", mode="before")
    @classmethod
    def origin(cls, value):
        return normalize_https_origin(value, field_name="API base URL")

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token", key=True)
        if not value or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste only the access token, without Bearer or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ContactFields(_Input):
    firstName: Text | None = None
    lastName: Text | None = None
    preferredName: Annotated[str, Field(max_length=200)] | None = None
    email: Text | None = None
    mobile: Text | None = None
    homePhone: Text | None = None
    businessPhone: Text | None = None
    hasMarketingConsent: bool | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set:
            raise ValueError("Supply at least one contact field")
        return self


class LeadFields(_Input):
    firstName: Text
    lastName: Text
    email: Text
    mobile: Text | None = None
    dealName: Annotated[str, Field(max_length=200)] | None = None
    noteTitle: Annotated[str, Field(max_length=2000)] | None = None
    noteDetails: Annotated[str, Field(max_length=20000)] | None = None
    utmSource: Text | None = None
    utmMedium: Text | None = None
    utmCampaign: Text | None = None
    externalReference: Annotated[str, Field(max_length=255)] | None = None
    externalIntegration: Text | None = None
    sendNotification: bool | None = None


class LeadContact(_Input):
    firstName: Text
    lastName: Text
    email: Text
    mobile: Text | None = None


class StructuredLeadFields(_Input):
    contacts: Annotated[list[LeadContact], Field(min_length=1, max_length=10)]
    dealName: Annotated[str, Field(max_length=200)] | None = None
    noteTitle: Annotated[str, Field(max_length=2000)] | None = None
    noteDetails: Annotated[str, Field(max_length=20000)] | None = None
    utmSource: Text | None = None
    utmCampaign: Text | None = None
    externalReference: Annotated[str, Field(max_length=255)] | None = None
    externalIntegration: Text | None = None
    sendNotification: bool | None = None


class DealFields(_Input):
    name: Annotated[str, Field(min_length=1, max_length=200)]


class TaskFields(_Input):
    title: Annotated[str, Field(min_length=1, max_length=2000)]
    detail: Annotated[str, Field(max_length=20000)] | None = None
    progress: Literal["Completed", "InProgress", "NotRequired", "NotStarted", "OnHold"] | None = None
    priority: Literal["Critical", "High", "Medium", "Normal"] | None = None
    dueDate: AwareDatetime | None = None


class TaskUpdateFields(TaskFields):
    title: Annotated[str, Field(min_length=1, max_length=2000)] | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set:
            raise ValueError("Supply at least one task field")
        return self


class NoteFields(_Input):
    title: Annotated[str, Field(min_length=1, max_length=2000)]
    detail: Annotated[str, Field(min_length=1, max_length=20000)]


# Every public operation is exactly one published OpenAPI method/path.
OPERATIONS = {
    "create_lead": ("POST", "leads", "Lead_Post", LeadFields),
    "get_lead": ("GET", "leads", "Lead_Get", None),
    "create_structured_lead": ("POST", "structured-leads", "StructuredLead_Post", StructuredLeadFields),
    "get_structured_lead": ("GET", "structured-leads", "StructuredLead_Get", None),
    "list_contacts": ("GET", "contacts", "Contacts_Get", None),
    "get_contact": ("GET", "contacts", "Contact_Get", None),
    "create_contact": ("POST", "contacts", "Contact_Post", ContactFields),
    "update_contact": ("PATCH", "contacts", "Contact_Patch", ContactFields),
    "list_contact_groups": ("GET", "contact-groups", "ContactGroups_Get", None),
    "get_contact_group": ("GET", "contact-groups", "ContactGroup_Get", None),
    "list_advisers": ("GET", "advisers", "Advisers_Get", None),
    "get_adviser": ("GET", "advisers", "Adviser_Get", None),
    "list_deals": ("GET", "deals", "Deals_Get", None),
    "get_deal": ("GET", "deals", "Deal_Get", None),
    "update_deal": ("PATCH", "deals", "Deal_Patch", DealFields),
    "get_task": ("GET", "tasks", "Task_Get", None),
    "create_task": ("POST", "tasks", "Task_Post", TaskFields),
    "update_task": ("PATCH", "tasks", "Task_Patch", TaskUpdateFields),
    "get_deal_note": ("GET", "deal-notes", "DealNote_Get", None),
    "create_deal_note": ("POST", "deal-notes", "DealNote_Post", NoteFields),
}


def _config(name, spec):
    method, kind, contract_id, attributes = spec
    fields = {"operation": (Literal[name], Field(name, json_schema_extra={
        "ui:hidden": True, "x-display-name": name.replace("_", " ").title(), "x-contract-operation": contract_id}))}
    if name.startswith("list_"):
        fields.update(page_number=(int, Field(1, ge=1, le=10000)), page_size=(int, Field(10, ge=1, le=100)))
    if name.startswith("get_") or method == "PATCH":
        fields["resource_id"] = (PathID, Field(..., title="Resource ID"))
    if attributes:
        fields["attributes"] = (attributes, Field(..., title="Fields to write"))
    if name == "create_contact":
        fields["contact_group_id"] = (ID, Field(..., title="Contact group ID"))
    if name == "create_deal_note":
        fields["deal_id"] = (ID, Field(..., title="Deal ID"))
    if name == "create_task":
        fields["assignee_id"] = (ID, Field(..., title="Assignee adviser ID"))
        fields["deal_id"] = (ID, Field(..., title="Residential deal ID"))
    return create_model("MyCRM" + name.title().replace("_", "") + "Config", __base__=_Input, **fields)


MODELS = {name: _config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in MODELS.values()})


MyCRMConfig = Annotated[Union[tuple(MODELS.values())], Field(discriminator="operation")]


class MyCRMFullConfig(NodeConfig[MyCRMConfig, MyCRMLeadsAccessToken]):
    pass


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value


class MyCRMLeadsNode(WorkflowNode):
    integration_type = "automation-mycrm-leads"
    connection_evidence = ConnectionEvidence(operation="list_contacts", noun="contacts")

    @classmethod
    def get_config_model(cls):
        return MyCRMFullConfig

    async def _request(self, method, kind, *, identifier=None, params=None, body=None):
        credential = self.config.credentials
        headers = {"Authorization": "Bearer " + credential.access_token, "UserId": credential.adviser_contact_id, "Accept": MEDIA}
        kwargs = {"params": params or {}}
        if body is not None:
            headers["Content-Type"] = MEDIA
            kwargs["json"] = body
        url = credential.api_base_url + "/jsonapi/" + kind + ("/" + identifier if identifier else "")
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, url, headers=headers, **kwargs)
        except httpx.RequestError:
            raise ValueError("MyCRM request failed; inspect any write before retrying") from None
        if response.status_code != (201 if method == "POST" else 200):
            message = "MyCRM returned HTTP " + str(response.status_code)
            try:
                errors = response.json().get("errors", [])
                details = [str(e.get("detail") or e.get("title"))[:1000] for e in errors[:5] if isinstance(e, dict) and (e.get("detail") or e.get("title"))]
                if details:
                    message += ": " + "; ".join(details)
            except (ValueError, TypeError, AttributeError):
                pass
            raise ValueError(_redact(message, credential.access_token))
        if len(response.content) > 5_000_000 or response.headers.get("Content-Type", "").split(";", 1)[0].lower() not in {MEDIA, "application/json"}:
            raise ValueError("MyCRM returned an unexpected JSON response; inspect any write before retrying")
        payload = response.json()
        if not isinstance(payload, dict) or "errors" in payload or "data" not in payload:
            raise ValueError("MyCRM did not confirm the operation")
        return _redact(payload, credential.access_token)

    @staticmethod
    def _record(row, kind, identifier=None):
        if not isinstance(row, dict) or row.get("type") != kind or not isinstance(row.get("id"), str) or not re.fullmatch(r"[1-9]\d*", row["id"]):
            raise ValueError("MyCRM returned an unexpected resource")
        if identifier is not None and row["id"] != identifier:
            raise ValueError("MyCRM returned a different resource; inspect any write before retrying")
        return row

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a MyCRM Leads access token")
        op = self.config.config
        method, kind, _, _ = OPERATIONS[op.operation]
        identifier = getattr(op, "resource_id", None)
        params = {"page[number]": op.page_number, "page[size]": op.page_size} if op.operation.startswith("list_") else {}
        body = None
        if method in {"POST", "PATCH"}:
            data = {"type": kind, "attributes": op.attributes.model_dump(mode="json", exclude_unset=True)}
            if identifier:
                data["id"] = identifier
            relations = {}
            if op.operation == "create_contact":
                relations["contactGroup"] = {"data": {"type": "contact-groups", "id": op.contact_group_id}}
            if op.operation in {"create_deal_note", "create_task"}:
                relations["deal" if kind == "deal-notes" else "residentialDeal"] = {"data": {"type": "deals", "id": op.deal_id}}
            if op.operation == "create_task":
                relations["assignee"] = {"data": {"type": "advisers", "id": op.assignee_id}}
            if relations:
                data["relationships"] = relations
            body = {"data": data}
        payload = await self._request(method, kind, identifier=identifier, params=params, body=body)
        result = {"status": "success", "operation": op.operation}
        if op.operation.startswith("list_"):
            if not isinstance(payload["data"], list) or len(payload["data"]) > op.page_size:
                raise ValueError("MyCRM returned an unexpected page")
            result["items"] = [self._record(row, kind) for row in payload["data"]]
            # Never follow provider URLs. Expose the next numbered page for the
            # caller; a full page without links is conservatively incomplete.
            links = payload.get("links")
            more = bool(links.get("next")) if isinstance(links, dict) and "next" in links else len(result["items"]) == op.page_size
            result.update(has_more=more, next_page_number=op.page_number + 1 if more else None)
        else:
            result["item"] = self._record(payload["data"], kind, identifier)
        await self.emit(result)
        return result

