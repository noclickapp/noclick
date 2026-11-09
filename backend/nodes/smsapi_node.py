"""SMSAPI bearer-token integration against panel/contacts OpenAPI 1.0.0.

One operation makes one request. Lists return one provider page. SMS acceptance
means queued, never delivered; writes are never automatically retried.
"""
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.smsapi.com"

class SMSAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="SMSAPI API Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.smsapi.com/docs/#authentication",
            "x-credential-instructions": "Paste a token generated in the SMSAPI Customer Portal under API Settings → OAuth Tokens. Enable profile, sms, sms_sender and contacts access for the operations you use. NoClick sends it as a Bearer header only to api.smsapi.com. The profile read checks the account; write permissions remain subject to your token grants.",
        })
    credential_type: Literal["smsapi_api_token"] = Field("smsapi_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the token, without a Bearer prefix")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class _ContactId(_Input):
    contact_id: str = Field(..., pattern=r"^[0-9a-fA-F]{24}$", description="SMSAPI contact Object ID.")

class _GroupId(_Input):
    group_id: str = Field(..., pattern=r"^[0-9a-fA-F]{24}$", description="SMSAPI group Object ID.")

class _TemplateId(_Input):
    template_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.-]+$")

class _ContactFields(_Input):
    phone_number: Optional[str] = Field(None, pattern=r"^[0-9]{8,16}$")
    email: Optional[str] = Field(None, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    first_name: Optional[str] = Field(None, max_length=200)
    last_name: Optional[str] = Field(None, max_length=200)
    gender: Optional[Literal["undefined", "male", "female"]] = None
    description: Optional[str] = Field(None, max_length=2000)
    city: Optional[str] = Field(None, max_length=200)
    source: Optional[str] = Field(None, max_length=500)

class _GroupFields(_Input):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    idx: Optional[str] = Field(None, max_length=200)
    contact_expire_after: Optional[int] = Field(None, ge=0, description="Contact expiry in days.")

class _TemplateFields(_Input):
    name: str = Field(..., min_length=1, max_length=200)
    template: str = Field(..., min_length=1, max_length=918)
    normalize: bool = False


class SMSAPIGetProfileConfig(_Input):
    """Get profile."""
    operation: Literal["get_profile"] = Field("get_profile", json_schema_extra={"ui:hidden": True})


class SMSAPISendSmsConfig(_Input):
    """Send sms."""
    operation: Literal["send_sms"] = Field("send_sms", json_schema_extra={"ui:hidden": True})
    to: str = Field(..., pattern=r"^[0-9]{8,16}(?:,[0-9]{8,16}){0,99}$", description="Up to 100 comma-separated recipient numbers, including country codes.")
    message: str = Field(..., min_length=1, max_length=918, description="Provider charges per SMS part; Unicode reduces the per-part character limit.")
    sender: Optional[str] = Field(None, min_length=1, max_length=16, description="An approved sender name; defaults to the provider's Test sender.")
    test: bool = Field(False, description="Validate without sending or charging.")
    normalize: bool = False
    idx: Optional[str] = Field(None, max_length=255, description="Custom callback reference; check_idx prevents duplicate sends for this reference within 24 hours.")
    check_idx: bool = False
    max_parts: int = Field(6, ge=1, le=6)


class SMSAPIListSendernamesConfig(_Input):
    """List sendernames."""
    operation: Literal["list_sendernames"] = Field("list_sendernames", json_schema_extra={"ui:hidden": True})


class SMSAPIGetSendernameConfig(_Input):
    """Get sendername."""
    operation: Literal["get_sendername"] = Field("get_sendername", json_schema_extra={"ui:hidden": True})
    sender: str = Field(..., min_length=1, max_length=16)


class SMSAPIListTemplatesConfig(_Input):
    """List templates."""
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})


class SMSAPICreateTemplateConfig(_TemplateFields):
    """Create template."""
    operation: Literal["create_template"] = Field("create_template", json_schema_extra={"ui:hidden": True})


class SMSAPIGetTemplateConfig(_TemplateId):
    """Get template."""
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})


class SMSAPIUpdateTemplateConfig(_TemplateId, _TemplateFields):
    """Update template."""
    operation: Literal["update_template"] = Field("update_template", json_schema_extra={"ui:hidden": True})


class SMSAPIDeleteTemplateConfig(_TemplateId):
    """Delete template."""
    operation: Literal["delete_template"] = Field("delete_template", json_schema_extra={"ui:hidden": True})


class SMSAPIListContactsConfig(_Input):
    """List contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    limit: int = Field(50, ge=1, le=1000, description="One page only; increase offset for another page.")
    offset: int = Field(0, ge=0, le=10000000)
    q: Optional[str] = Field(None, max_length=500)
    order_by: Optional[Literal["first_name", "last_name", "date_updated", "date_created"]] = None


class SMSAPICreateContactConfig(_ContactFields):
    """Create contact."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    phone_number: str = Field(..., pattern=r"^[0-9]{8,16}$")
    email: str = Field(..., max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class SMSAPIGetContactConfig(_ContactId):
    """Get contact."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})


class SMSAPIUpdateContactConfig(_ContactId, _ContactFields):
    """Update contact."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    @model_validator(mode="after")
    def change(self):
        if not any(getattr(self, f) is not None for f in _ContactFields.model_fields):
            raise ValueError("Provide at least one contact field to update")
        return self


class SMSAPIDeleteContactConfig(_ContactId):
    """Delete contact."""
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})


class SMSAPIListGroupsConfig(_Input):
    """List groups."""
    operation: Literal["list_groups"] = Field("list_groups", json_schema_extra={"ui:hidden": True})


class SMSAPICreateGroupConfig(_GroupFields):
    """Create group."""
    operation: Literal["create_group"] = Field("create_group", json_schema_extra={"ui:hidden": True})


class SMSAPIGetGroupConfig(_GroupId):
    """Get group."""
    operation: Literal["get_group"] = Field("get_group", json_schema_extra={"ui:hidden": True})


class SMSAPIUpdateGroupConfig(_GroupId, _GroupFields):
    """Update group."""
    operation: Literal["update_group"] = Field("update_group", json_schema_extra={"ui:hidden": True})


class SMSAPIDeleteGroupConfig(_GroupId):
    """Delete group."""
    operation: Literal["delete_group"] = Field("delete_group", json_schema_extra={"ui:hidden": True})
    delete_contacts: bool = Field(False, description="Also delete contacts assigned to the group; defaults to keeping them.")


class SMSAPIAddContactToGroupConfig(_GroupId, _ContactId):
    """Add contact to group."""
    operation: Literal["add_contact_to_group"] = Field("add_contact_to_group", json_schema_extra={"ui:hidden": True})


class SMSAPIGetGroupMemberConfig(_GroupId, _ContactId):
    """Get group member."""
    operation: Literal["get_group_member"] = Field("get_group_member", json_schema_extra={"ui:hidden": True})


class SMSAPIRemoveContactFromGroupConfig(_GroupId, _ContactId):
    """Remove contact from group."""
    operation: Literal["remove_contact_from_group"] = Field("remove_contact_from_group", json_schema_extra={"ui:hidden": True})


SMSAPIConfig = Annotated[Union[
    SMSAPIGetProfileConfig,
    SMSAPISendSmsConfig,
    SMSAPIListSendernamesConfig,
    SMSAPIGetSendernameConfig,
    SMSAPIListTemplatesConfig,
    SMSAPICreateTemplateConfig,
    SMSAPIGetTemplateConfig,
    SMSAPIUpdateTemplateConfig,
    SMSAPIDeleteTemplateConfig,
    SMSAPIListContactsConfig,
    SMSAPICreateContactConfig,
    SMSAPIGetContactConfig,
    SMSAPIUpdateContactConfig,
    SMSAPIDeleteContactConfig,
    SMSAPIListGroupsConfig,
    SMSAPICreateGroupConfig,
    SMSAPIGetGroupConfig,
    SMSAPIUpdateGroupConfig,
    SMSAPIDeleteGroupConfig,
    SMSAPIAddContactToGroupConfig,
    SMSAPIGetGroupMemberConfig,
    SMSAPIRemoveContactFromGroupConfig
], Field(discriminator="operation")]

class SMSAPINodeConfig(NodeConfig[SMSAPIConfig, SMSAPITokenCredential]):
    pass

ROUTES = {'get_profile': ('GET', '/profile', ()), 'send_sms': ('POST', '/sms.do', ()), 'list_sendernames': ('GET', '/sms/sendernames', ()), 'get_sendername': ('GET', '/sms/sendernames/{sender}', ()), 'list_templates': ('GET', '/sms/templates', ()), 'create_template': ('POST', '/sms/templates', ()), 'get_template': ('GET', '/sms/templates/{template_id}', ()), 'update_template': ('PUT', '/sms/templates/{template_id}', ()), 'delete_template': ('DELETE', '/sms/templates/{template_id}', ()), 'list_contacts': ('GET', '/contacts', ('limit', 'offset', 'q', 'order_by')), 'create_contact': ('POST', '/contacts', ()), 'get_contact': ('GET', '/contacts/{contact_id}', ()), 'update_contact': ('PUT', '/contacts/{contact_id}', ()), 'delete_contact': ('DELETE', '/contacts/{contact_id}', ()), 'list_groups': ('GET', '/contacts/groups', ()), 'create_group': ('POST', '/contacts/groups', ()), 'get_group': ('GET', '/contacts/groups/{group_id}', ()), 'update_group': ('PUT', '/contacts/groups/{group_id}', ()), 'delete_group': ('DELETE', '/contacts/groups/{group_id}', ()), 'add_contact_to_group': ('PUT', '/contacts/groups/{group_id}/members/{contact_id}', ()), 'get_group_member': ('GET', '/contacts/groups/{group_id}/members/{contact_id}', ()), 'remove_contact_from_group': ('DELETE', '/contacts/groups/{group_id}/members/{contact_id}', ())}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    return value


class SMSAPINode(WorkflowNode):
    integration_type = "automation-smsapi"
    connection_evidence = ConnectionEvidence(noun="SMSAPI account", identity_operation="get_profile",
        identity_keys=("name", "username", "email"))

    @classmethod
    def get_config_model(cls):
        return SMSAPINodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an SMSAPI API token")
        config = self.config.config
        token = self.config.credentials.api_token
        method, route, query_fields = ROUTES[config.operation]
        values = config.model_dump(exclude={"operation"}, exclude_none=True)
        for name in tuple(values):
            marker = "{" + name + "}"
            if marker in route:
                if str(values[name]) in {".", ".."}:
                    raise ValueError("Use an SMSAPI resource ID or sender name, not a path segment")
                route = route.replace(marker, quote(str(values.pop(name)), safe=""))
        params = {name: values.pop(name) for name in query_fields if name in values}
        if config.operation == "send_sms":
            if "sender" in values:
                values["from"] = values.pop("sender")
            values.update(format="json", encoding="utf-8")
            for name in ("test", "normalize", "check_idx"):
                values[name] = int(values[name])
        form = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in values.items()}
        kwargs = {"params": params}
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        if method != "GET" and (form or config.operation == "delete_group"):
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            kwargs["data"] = form
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + route, headers=headers, **kwargs)
        except httpx.TransportError:
            raise ValueError("SMSAPI request did not complete" +
                ("; the write outcome is unknown, inspect before retrying" if method != "GET" else "")) from None
        if not 200 <= response.status_code < 300:
            raise ValueError(f"SMSAPI HTTP {response.status_code}: " + response.text.replace(token, "[redacted]")[:1000])
        if len(response.content) > 10000000:
            raise ValueError("SMSAPI response exceeds the supported JSON size")
        body = None
        if response.status_code not in {202, 204}:
            try:
                body = response.json()
            except ValueError:
                raise ValueError("SMSAPI returned invalid JSON; inspect writes before retrying") from None
            if not isinstance(body, dict):
                raise ValueError("SMSAPI returned an unexpected JSON shape")
            if "error" in body or body.get("errors"):
                raise ValueError("SMSAPI: " + str(_redact(body, token))[:1000])
            if config.operation.startswith("list_"):
                if not isinstance(body.get("collection"), list) or type(body.get("size")) is not int:
                    raise ValueError("SMSAPI returned an invalid collection")
            elif config.operation == "get_profile":
                if not all(isinstance(body.get(k), str) and body[k] for k in ("name", "username", "email")):
                    raise ValueError("SMSAPI account identity is missing")
            elif config.operation == "send_sms":
                if type(body.get("count")) is not int or not isinstance(body.get("list"), list):
                    raise ValueError("SMSAPI did not confirm message acceptance; inspect before retrying")
        output = {"status": "success", "data": body, "http_status": response.status_code}
        if config.operation.startswith("list_"):
            output["complete"] = config.operation != "list_contacts"
            if config.operation == "list_contacts":
                output["next_offset"] = config.offset + len(body["collection"]) if len(body["collection"]) == config.limit else None
        if config.operation == "send_sms":
            output.update(delivery_verified=False, test=config.test)
        if response.status_code == 202:
            output.update(accepted=True, completion_verified=False)
        output = _redact(output, token)
        await self.emit(output)
        return output
