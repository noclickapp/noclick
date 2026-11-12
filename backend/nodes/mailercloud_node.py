"""Mailercloud Marketing API v1 operations (https://apidoc.mailercloud.com)."""
from __future__ import annotations

import re
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://cloudapi.mailercloud.com/v1"


class MailercloudAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Mailercloud API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.mailercloud.com/account/api-integrations",
            "x-credential-instructions": "In Mailercloud, open Account → API Integrations and create an API key. Paste the key here without an Authorization or Bearer prefix. NoClick checks your account details before saving.",
        })
    credential_type: Literal["mailercloud_api_key"] = Field("mailercloud_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key without a header or prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifier(cls, value, info):
        if info.field_name.endswith("_id") and isinstance(value, str):
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value) and not (info.field_name == "contact_id" and re.fullmatch(r"[^\s/@]+@[^\s/@]+\.[^\s/@]+", value)):
                raise ValueError("Use the encrypted Mailercloud resource ID")
        return value


class _Page(_Input):
    page: int = Field(1, ge=1, description="One page per execution; increment this to fetch the next page.")
    limit: int = Field(10, ge=10, le=100)


class _ContactFields(_Input):
    first_name: Optional[str] = Field(None, max_length=25)
    middle_name: Optional[str] = Field(None, max_length=25)
    last_name: Optional[str] = Field(None, max_length=25)
    city: Optional[str] = Field(None, max_length=100)
    country: Optional[str] = Field(None, max_length=50)
    company_name: Optional[str] = Field(None, max_length=150)
    department: Optional[str] = Field(None, min_length=1, max_length=100)
    industry: Optional[str] = Field(None, max_length=100)
    job_title: Optional[str] = Field(None, max_length=100)
    lead_source: Optional[str] = Field(None, max_length=50)
    phone: Optional[str] = Field(None, min_length=1, max_length=25)
    salary: Optional[int] = None
    state: Optional[str] = Field(None, max_length=100)
    postal_code: Optional[str] = Field(None, max_length=25)
    contact_type: Optional[Literal["active", "bounce", "abuse", "unsubscribe", "suppressed", "spam complaints"]] = None
    tracking_consent: Optional[Literal["granted", "denied", "unknown"]] = Field(None,
        description="Set open-tracking consent only when explicitly supplied by the contact.")
    tags: Optional[list[str]] = None


class GetAccount(_Input):
    """Read the account name, email and plan."""
    operation: Literal["get_account"] = Field("get_account", json_schema_extra={"ui:hidden": True})


class CreateContact(_ContactFields):
    """Create a contact in a list."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=3, max_length=200)
    list_id: str


class UpsertContact(_ContactFields):
    """Create or update a contact by email."""
    operation: Literal["upsert_contact"] = Field("upsert_contact", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=3, max_length=200)
    list_id: str


class UpdateContact(_ContactFields):
    """Update selected contact fields; omitted fields are unchanged."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact_id: str


class GetContact(_Input):
    """Read contact details."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    contact_id: str


class DeleteContact(_Input):
    """Delete a contact."""
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})
    contact_id: str


class ListContacts(_Page):
    """Read one page of contacts in a list."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    list_id: str
    search: Optional[str] = None


class CreateList(_Input):
    """Create a normal contact list."""
    operation: Literal["create_list"] = Field("create_list", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9._ -]+$")
    list_type: Literal[1] = 1


class UpdateList(_Input):
    """Rename a contact list."""
    operation: Literal["update_list"] = Field("update_list", json_schema_extra={"ui:hidden": True})
    list_id: str
    name: str = Field(..., min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9._ -]+$")


class GetList(_Input):
    """Read list details and contact counts."""
    operation: Literal["get_list"] = Field("get_list", json_schema_extra={"ui:hidden": True})
    list_id: str


class DeleteList(_Input):
    """Delete a contact list."""
    operation: Literal["delete_list"] = Field("delete_list", json_schema_extra={"ui:hidden": True})
    list_id: str


class ListLists(_Page):
    """Search one page of normal lists."""
    operation: Literal["list_lists"] = Field("list_lists", json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, le=3, description="The pinned v1 contract limits this endpoint to page 3.")
    list_type: Literal[1] = 1
    search_name: Optional[str] = Field(None, min_length=1)
    sort_field: Optional[Literal["name", "contact_count", "open_percentage"]] = None
    sort_order: Optional[Literal["asc", "desc"]] = None


class CreateTag(_Input):
    """Create a contact tag."""
    operation: Literal["create_tag"] = Field("create_tag", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=100)


class UpdateTag(_Input):
    """Rename a tag."""
    operation: Literal["update_tag"] = Field("update_tag", json_schema_extra={"ui:hidden": True})
    tag_id: str
    name: str = Field(..., min_length=1, max_length=100)


class DeleteTag(_Input):
    """Delete a tag."""
    operation: Literal["delete_tag"] = Field("delete_tag", json_schema_extra={"ui:hidden": True})
    tag_id: str


class ListTags(_Page):
    """Search one page of contact tags."""
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"ui:hidden": True})
    search: Optional[str] = None


class ListCampaigns(_Page):
    """Search one page of campaigns."""
    operation: Literal["list_campaigns"] = Field("list_campaigns", json_schema_extra={"ui:hidden": True})
    search: Optional[str] = Field(None, min_length=1)
    sender_email: Optional[str] = Field(None, min_length=1)
    status: Optional[Literal["Processing", "Queued", "Sending", "Paused", "Finished", "Aborted", "Duplicate", "Draft", "Scheduled", "Rescheduled", "Failed"]] = None


class GetCampaign(_Input):
    """Read a campaign and its statistics."""
    operation: Literal["get_campaign"] = Field("get_campaign", json_schema_extra={"ui:hidden": True})
    campaign_id: str


class ListCampaignOpens(_Page):
    """Read one page of campaign opens."""
    operation: Literal["list_campaign_opens"] = Field("list_campaign_opens", json_schema_extra={"ui:hidden": True})
    campaign_id: str


class ListCampaignClicks(_Page):
    """Read one page of campaign clicks."""
    operation: Literal["list_campaign_clicks"] = Field("list_campaign_clicks", json_schema_extra={"ui:hidden": True})
    campaign_id: str


class ListSenders(_Page):
    """Read one page of account senders."""
    operation: Literal["list_senders"] = Field("list_senders", json_schema_extra={"ui:hidden": True})
    search: Optional[str] = Field(None, max_length=255)
    sort_field: Optional[Literal["sender_email", "sender_name", "created_date"]] = None
    sort_order: Optional[Literal["asc", "desc"]] = None


# Mailercloud's own MCP server: agents get its tools through a person's Mailercloud sign-in.
MailercloudMcpCredential = mcp_credential("mailercloud", "https://mcp.mailercloud.com/mcp", app="Mailercloud")
MailercloudCredential = Union[MailercloudAPIKeyCredential, MailercloudMcpCredential]


MailercloudConfig = Annotated[Union[
    GetAccount,
    CreateContact,
    UpsertContact,
    UpdateContact,
    GetContact,
    DeleteContact,
    ListContacts,
    CreateList,
    UpdateList,
    GetList,
    DeleteList,
    ListLists,
    CreateTag,
    UpdateTag,
    DeleteTag,
    ListTags,
    ListCampaigns,
    GetCampaign,
    ListCampaignOpens,
    ListCampaignClicks,
    ListSenders
], Field(discriminator="operation")]


class MailercloudFullConfig(NodeConfig[MailercloudConfig, MailercloudCredential]):
    pass


ROUTES = {
    "get_account": ("GET", "/client/plan", None),
    "create_contact": ("POST", "/contacts", None),
    "upsert_contact": ("POST", "/contacts/upsert", None),
    "update_contact": ("PUT", "/contacts/{id}", 'contact_id'),
    "get_contact": ("GET", "/contacts/{id}", 'contact_id'),
    "delete_contact": ("DELETE", "/contacts/{id}", 'contact_id'),
    "list_contacts": ("POST", "/contact/search/{id}", 'list_id'),
    "create_list": ("POST", "/list", None),
    "update_list": ("PATCH", "/list/{id}", 'list_id'),
    "get_list": ("GET", "/list/{id}", 'list_id'),
    "delete_list": ("DELETE", "/list/{id}", 'list_id'),
    "list_lists": ("POST", "/lists/search", None),
    "create_tag": ("POST", "/tags", None),
    "update_tag": ("PUT", "/tags/{id}", 'tag_id'),
    "delete_tag": ("DELETE", "/tags/{id}", 'tag_id'),
    "list_tags": ("POST", "/tags/search", None),
    "list_campaigns": ("POST", "/campaign/list", None),
    "get_campaign": ("GET", "/campaign/{id}", 'campaign_id'),
    "list_campaign_opens": ("POST", "/campaign/{id}/opens", 'campaign_id'),
    "list_campaign_clicks": ("POST", "/campaign/{id}/clicks", 'campaign_id'),
    "list_senders": ("POST", "/senders/search", None),
}


class MailercloudNode(WorkflowNode):
    integration_type = "automation-mailercloud"
    credential_provider_labels = {"mailercloud": "Mailercloud Account"}
    connection_evidence = ConnectionEvidence(noun="Mailercloud account", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return MailercloudFullConfig

    async def execute(self, input_data):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Mailercloud API key")
        op = self.config.config
        method, path, id_field = ROUTES[op.operation]
        if id_field:
            path = path.replace("{id}", quote(getattr(op, id_field), safe=""))
        body = op.model_dump(exclude_none=True, exclude={"operation", *([id_field] if id_field else [])})
        # These two unusual requirements are explicit in the publisher's v1 contract.
        options = {"json": body} if method in {"POST", "PUT", "PATCH"} or op.operation == "get_contact" else {}
        if op.operation == "update_list":
            options["params"] = {"id": op.list_id}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": credential.api_key, "Accept": "application/json", "Content-Type": "application/json"},
                    **options)
        except httpx.HTTPError:
            return {"status": "error", "error": "Mailercloud request could not be completed"}
        if response.status_code == 204:
            return {"status": "success", "http_status": 204}
        try:
            payload = response.json()
        except ValueError:
            return {"status": "error", "http_status": response.status_code,
                "error": "Mailercloud returned an unexpected non-JSON response"}
        # A provider may return an error envelope with HTTP 200.
        if not 200 <= response.status_code < 300 or (isinstance(payload, dict) and (payload.get("error") or payload.get("errors"))):
            message = payload.get("errors") or payload.get("error") or payload.get("message") if isinstance(payload, dict) else None
            return {"status": "error", "http_status": response.status_code,
                "error": str(message or "Mailercloud rejected the request").replace(credential.api_key, "[redacted]")}
        if not isinstance(payload, (dict, list)) and not (op.operation == "delete_list" and isinstance(payload, str)):
            return {"status": "error", "http_status": response.status_code, "error": "Unexpected Mailercloud JSON shape"}
        if op.operation == "get_account" and (not isinstance(payload, dict) or not isinstance(payload.get("data"), dict)
                or not any(isinstance(payload["data"].get(k), str) and payload["data"][k].strip() for k in ("name", "email"))):
            return {"status": "error", "error": "Mailercloud account identity was missing"}
        return {"status": "success", "http_status": response.status_code, "data": payload}
