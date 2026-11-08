"""Laposta v2 lists, subscribers, custom fields, campaigns and reports.

Each operation makes exactly one request to the official API. API contract:
https://docs.laposta.org/openapi.json (1.0.0). List reads are account evidence.
"""
from __future__ import annotations

import ipaddress
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, AfterValidator, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE = "https://api.laposta.nl/v2"
CREDENTIAL_TYPE = "laposta_api_key"


def _resource_id(value: str) -> str:
    # IDs may also be subscriber email addresses, which Laposta accepts.
    if not value or len(value) > 254 or any(c.isspace() or c in "/\\?#%" or ord(c) < 32 for c in value) or value in {".", ".."}:
        raise ValueError("Paste a single Laposta resource ID or subscriber email address")
    return value


def _email(value: str) -> str:
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value) or len(value) > 254:
        raise ValueError("Enter an email address")
    return value


ResourceID = Annotated[str, AfterValidator(_resource_id)]
Email = Annotated[str, AfterValidator(_email)]


class LapostaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Laposta API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.laposta.org/hoe-kom-ik-aan-een-api-sleutel",
            "x-credential-instructions": "In Laposta, open Koppelingen and create an API key. Copy it while it is visible and paste it here. NoClick sends it as the Basic authentication username with an empty password to api.laposta.nl."
        })
    credential_type: Literal["laposta_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if ":" in value or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Paste only the API key, without the Basic prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class LapostaListListsConfig(_Input):
    """List lists."""
    operation: Literal["list_lists"] = Field("list_lists", title="List Lists", json_schema_extra={"ui:hidden": True})


class LapostaGetListConfig(_Input):
    """Get list."""
    operation: Literal["get_list"] = Field("get_list", title="Get List", json_schema_extra={"ui:hidden": True})
    list_id: ResourceID


class LapostaCreateListConfig(_Input):
    """Create list."""
    operation: Literal["create_list"] = Field("create_list", title="Create List", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=500)
    remarks: str | None = Field(None, max_length=10000)
    locked: bool = False


class LapostaUpdateListConfig(_Input):
    """Update list."""
    operation: Literal["update_list"] = Field("update_list", title="Update List", json_schema_extra={"ui:hidden": True})
    list_id: ResourceID
    name: str = Field(..., min_length=1, max_length=500)
    remarks: str | None = Field(None, max_length=10000)


class LapostaDeleteListConfig(_Input):
    """Permanently delete the list and its subscribers."""
    operation: Literal["delete_list"] = Field("delete_list", title="Delete List", json_schema_extra={"ui:hidden": True})
    list_id: ResourceID


class LapostaListMembersConfig(_Input):
    """List members."""
    operation: Literal["list_members"] = Field("list_members", title="List Members", json_schema_extra={"ui:hidden": True})
    list_id: ResourceID
    state: Literal["active", "deleted"] | None = None


class LapostaGetMemberConfig(_Input):
    """Get member."""
    operation: Literal["get_member"] = Field("get_member", title="Get Member", json_schema_extra={"ui:hidden": True})
    list_id: ResourceID
    member_id: ResourceID


class LapostaCreateMemberConfig(_Input):
    """Add a subscriber. List double opt-in and notification settings apply."""
    operation: Literal["create_member"] = Field("create_member", title="Create Member", json_schema_extra={"ui:hidden": True})
    list_id: ResourceID
    email: Email
    ip: str = Field(..., description="IP address of the subscriber who signed up, not the server.")
    source_url: str | None = Field(None, max_length=2048)
    custom_fields: dict[str, str | int | float | list[str]] | None = Field(None, description="Keys are field custom_name values; arrays support multiple selections and labels.")

    @field_validator("ip")
    @classmethod
    def signup_ip(cls, value):
        return str(ipaddress.ip_address(value))


class LapostaUpdateMemberConfig(_Input):
    """Update member."""
    operation: Literal["update_member"] = Field("update_member", title="Update Member", json_schema_extra={"ui:hidden": True})
    list_id: ResourceID
    member_id: ResourceID
    email: Email | None = None
    custom_fields: dict[str, str | int | float | list[str]] | None = None


class LapostaDeleteMemberConfig(_Input):
    """Permanently remove a subscriber from the selected list."""
    operation: Literal["delete_member"] = Field("delete_member", title="Delete Member", json_schema_extra={"ui:hidden": True})
    list_id: ResourceID
    member_id: ResourceID


class LapostaListFieldsConfig(_Input):
    """List fields."""
    operation: Literal["list_fields"] = Field("list_fields", title="List Fields", json_schema_extra={"ui:hidden": True})
    list_id: ResourceID


class LapostaGetFieldConfig(_Input):
    """Get field."""
    operation: Literal["get_field"] = Field("get_field", title="Get Field", json_schema_extra={"ui:hidden": True})
    list_id: ResourceID
    field_id: ResourceID


class LapostaCreateFieldConfig(_Input):
    """Create field."""
    operation: Literal["create_field"] = Field("create_field", title="Create Field", json_schema_extra={"ui:hidden": True})
    list_id: ResourceID
    name: str = Field(..., min_length=1, max_length=500)
    datatype: Literal["text", "numeric", "date"] = Field("text", description="Create a scalar custom field.")
    required: bool = False
    in_form: bool = True
    in_list: bool = True
    defaultvalue: str | None = None


class LapostaUpdateFieldConfig(_Input):
    """Update field."""
    operation: Literal["update_field"] = Field("update_field", title="Update Field", json_schema_extra={"ui:hidden": True})
    list_id: ResourceID
    field_id: ResourceID
    name: str = Field(..., min_length=1, max_length=500)
    required: bool = Field(..., description="Whether this custom field is required.")


class LapostaDeleteFieldConfig(_Input):
    """Delete field."""
    operation: Literal["delete_field"] = Field("delete_field", title="Delete Field", json_schema_extra={"ui:hidden": True})
    list_id: ResourceID
    field_id: ResourceID


class LapostaListCampaignsConfig(_Input):
    """List campaigns."""
    operation: Literal["list_campaigns"] = Field("list_campaigns", title="List Campaigns", json_schema_extra={"ui:hidden": True})


class LapostaGetCampaignConfig(_Input):
    """Get campaign."""
    operation: Literal["get_campaign"] = Field("get_campaign", title="Get Campaign", json_schema_extra={"ui:hidden": True})
    campaign_id: ResourceID


class LapostaUpdateCampaignConfig(_Input):
    """Update campaign."""
    operation: Literal["update_campaign"] = Field("update_campaign", title="Update Campaign", json_schema_extra={"ui:hidden": True})
    campaign_id: ResourceID
    name: str = Field(..., min_length=1, max_length=500)
    subject: str | None = Field(None, max_length=1000)
    reply_to: Email | None = None


class LapostaDeleteCampaignConfig(_Input):
    """Delete campaign."""
    operation: Literal["delete_campaign"] = Field("delete_campaign", title="Delete Campaign", json_schema_extra={"ui:hidden": True})
    campaign_id: ResourceID


class LapostaGetCampaignContentConfig(_Input):
    """Get campaign content."""
    operation: Literal["get_campaign_content"] = Field("get_campaign_content", title="Get Campaign Content", json_schema_extra={"ui:hidden": True})
    campaign_id: ResourceID


class LapostaSetCampaignContentConfig(_Input):
    """Replace campaign HTML. Does not send or schedule the campaign."""
    operation: Literal["set_campaign_content"] = Field("set_campaign_content", title="Set Campaign Content", json_schema_extra={"ui:hidden": True})
    campaign_id: ResourceID
    html: str = Field(..., min_length=1, max_length=500000, json_schema_extra={"ui:widget": "textarea"})
    inline_css: bool = False


class LapostaListReportsConfig(_Input):
    """List reports."""
    operation: Literal["list_reports"] = Field("list_reports", title="List Reports", json_schema_extra={"ui:hidden": True})


class LapostaGetReportConfig(_Input):
    """Get report."""
    operation: Literal["get_report"] = Field("get_report", title="Get Report", json_schema_extra={"ui:hidden": True})
    campaign_id: ResourceID


LapostaConfig = Annotated[Union[
    LapostaListListsConfig,
    LapostaGetListConfig,
    LapostaCreateListConfig,
    LapostaUpdateListConfig,
    LapostaDeleteListConfig,
    LapostaListMembersConfig,
    LapostaGetMemberConfig,
    LapostaCreateMemberConfig,
    LapostaUpdateMemberConfig,
    LapostaDeleteMemberConfig,
    LapostaListFieldsConfig,
    LapostaGetFieldConfig,
    LapostaCreateFieldConfig,
    LapostaUpdateFieldConfig,
    LapostaDeleteFieldConfig,
    LapostaListCampaignsConfig,
    LapostaGetCampaignConfig,
    LapostaUpdateCampaignConfig,
    LapostaDeleteCampaignConfig,
    LapostaGetCampaignContentConfig,
    LapostaSetCampaignContentConfig,
    LapostaListReportsConfig,
    LapostaGetReportConfig
], Field(discriminator="operation")]


class LapostaFullConfig(NodeConfig[LapostaConfig, LapostaAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# operation -> method, route template, query fields, response envelope
ROUTES = {
    "list_lists": ('GET', '/list', (), 'list'),
    "get_list": ('GET', '/list/{list_id}', (), 'list'),
    "create_list": ('POST', '/list', (), 'list'),
    "update_list": ('POST', '/list/{list_id}', (), 'list'),
    "delete_list": ('DELETE', '/list/{list_id}', (), 'list'),
    "list_members": ('GET', '/member', ('list_id', 'state'), 'member'),
    "get_member": ('GET', '/member/{member_id}', ('list_id',), 'member'),
    "create_member": ('POST', '/member', (), 'member'),
    "update_member": ('POST', '/member/{member_id}', (), 'member'),
    "delete_member": ('DELETE', '/member/{member_id}', ('list_id',), 'member'),
    "list_fields": ('GET', '/field', ('list_id',), 'field'),
    "get_field": ('GET', '/field/{field_id}', ('list_id',), 'field'),
    "create_field": ('POST', '/field', (), 'field'),
    "update_field": ('POST', '/field/{field_id}', (), 'field'),
    "delete_field": ('DELETE', '/field/{field_id}', ('list_id',), 'field'),
    "list_campaigns": ('GET', '/campaign', (), 'campaign'),
    "get_campaign": ('GET', '/campaign/{campaign_id}', (), 'campaign'),
    "update_campaign": ('POST', '/campaign/{campaign_id}', (), 'campaign'),
    "delete_campaign": ('DELETE', '/campaign/{campaign_id}', (), 'campaign'),
    "get_campaign_content": ('GET', '/campaign/{campaign_id}/content', (), 'campaign'),
    "set_campaign_content": ('POST', '/campaign/{campaign_id}/content', (), 'campaign'),
    "list_reports": ('GET', '/report', (), 'report'),
    "get_report": ('GET', '/report/{campaign_id}', (), 'report'),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class LapostaNode(WorkflowNode):
    integration_type = "automation-laposta"
    connection_evidence = ConnectionEvidence(noun="lists", operation="list_lists", label_keys=("name", "list_id"))

    @classmethod
    def get_config_model(cls):
        return LapostaFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Laposta API key")
        config, credential = self.config.config, self.config.credentials
        method, template, query_fields, envelope = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = template
        for name in re.findall(r"\{([^}]+)\}", template):
            path = path.replace("{" + name + "}", quote(values.pop(name), safe=""))
        params = {k: values.pop(k) for k in query_fields if k in values}
        expected = 201 if method == "POST" and "{" not in template else 200
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    auth=httpx.BasicAuth(credential.api_key, ""), headers={"Accept": "application/json"},
                    **({"json": values} if method == "POST" else {}))
            if response.status_code != expected:
                message = "Laposta did not confirm the request"
                try:
                    error = response.json()
                    if isinstance(error, dict):
                        error = error.get("error", error)
                        if isinstance(error, dict) and isinstance(error.get("message"), str):
                            message = error["message"][:1000]
                except ValueError:
                    pass
                return _redact({"status": "error", "error": message, "http_status": response.status_code,
                    "operation": config.operation}, credential.api_key)
            if len(response.content) > 10_000_000 or response.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
                raise ValueError("Unexpected Laposta representation")
            body = response.json()
            if not isinstance(body, dict) or "error" in body or "errors" in body:
                raise ValueError("Invalid Laposta response")
            if config.operation.startswith("list_"):
                rows = body.get("data")
                if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get(envelope), dict) for row in rows):
                    raise ValueError("Invalid Laposta list response")
                result = {"items": [row[envelope] for row in rows]}
            else:
                if not isinstance(body.get(envelope), dict):
                    raise ValueError("Invalid Laposta resource response")
                result = {envelope: body[envelope]}
            return _redact({"status": "success", "operation": config.operation, **result}, credential.api_key)
        except (ValueError, httpx.HTTPError, SSRFError):
            return {"status": "error", "operation": config.operation,
                "error": "Laposta request could not be verified; inspect the provider before retrying a write"}
