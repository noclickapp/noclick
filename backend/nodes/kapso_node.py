"""Kapso WhatsApp Meta Proxy v24.0 operations using a project API key.

Contract: https://docs.kapso.ai/api/meta/whatsapp/openapi-whatsapp.yaml (1.0.0).
Lists return one provider page, including its paging object for continuation.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.kapso.ai/meta/whatsapp/v24.0"


class KapsoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Kapso API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.kapso.ai/integrations",
            "x-credential-instructions": "Create a project API key in Kapso under Integrations > API keys. Paste the key and your WhatsApp Business Account ID. NoClick verifies access by listing that account's phone numbers.",
        })
    credential_type: Literal["kapso_api_key"] = Field("kapso_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})
    business_account_id: str = Field(..., min_length=1, title="Business account ID", pattern=r"^[0-9]+$")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        return clean_secret(value, field_name="API key")


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def path_ids(cls, value, info):
        if info.field_name in {"phone_number_id", "message_id", "conversation_id", "wa_id", "template_id", "flow_id"} and value is not None:
            if not isinstance(value, str) or not value.strip() or value in {".", ".."} or any(c in value for c in "/\\?#"):
                raise ValueError("Paste a single Kapso resource ID")
        return value

    @model_validator(mode="after")
    def compatible_filters(self):
        if getattr(self, "before", None) and getattr(self, "after", None):
            raise ValueError("Choose either before or after, not both")
        if getattr(self, "assigned_user_id", None) and getattr(self, "unassigned", False):
            raise ValueError("Choose an assignee or unassigned conversations")
        return self


class KapsoListMessagesConfig(_Operation):
    """List messages."""
    operation: Literal["list_messages"] = Field("list_messages", json_schema_extra={"ui:hidden": True})
    phone_number_id: str = Field(..., min_length=1, description='WhatsApp Business Phone Number ID')
    conversation_id: str | None = Field(None, description='Filter by conversation ID')
    direction: Literal['inbound', 'outbound'] | None = Field(None, description='Filter by message direction')
    status: Literal['pending', 'sent', 'delivered', 'read', 'failed'] | None = Field(None, description='Filter by message status')
    since: datetime | None = Field(None, description='Filter messages created on or after this time (ISO 8601)')
    until: datetime | None = Field(None, description='Filter messages created on or before this time (ISO 8601)')
    limit: int | None = Field(20, ge=1, le=100, description='Maximum number of results per page (default 20, max 100)')
    before: str | None = Field(None, description='Cursor for previous page (Base64 encoded)')
    after: str | None = Field(None, description='Cursor for next page (Base64 encoded)')
    fields: str | None = Field(None, description='Filter response fields. Use `kapso()` to include Kapso-specific extensions.\n\nExample: `fields=kapso(direction,status,processing_status)`\n')


class KapsoSendTextConfig(_Operation):
    """Send a message."""
    operation: Literal["send_text"] = Field("send_text", json_schema_extra={"ui:hidden": True})
    phone_number_id: str = Field(..., min_length=1, description='WhatsApp Business Phone Number ID')
    to: str = Field(..., min_length=1, description="Recipient phone number or group ID")
    text: str = Field(..., min_length=1, max_length=4096, description="Message text; requires an open customer service window")


class KapsoSendTemplateConfig(_Operation):
    """Send an approved WhatsApp template with optional component parameters."""
    operation: Literal["send_template"] = Field("send_template", json_schema_extra={"ui:hidden": True})
    phone_number_id: str = Field(..., min_length=1)
    to: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, description="Approved template name")
    language: str = Field(..., min_length=1, description="Template language code, for example en_US")
    components: list[dict] | None = Field(None, description="Template header, body or button parameter components")


class KapsoGetMessageConfig(_Operation):
    """Get message by ID."""
    operation: Literal["get_message"] = Field("get_message", json_schema_extra={"ui:hidden": True})
    phone_number_id: str = Field(..., min_length=1, description='WhatsApp Business Phone Number ID')
    message_id: str = Field(..., min_length=1, description='WhatsApp message ID')
    fields: str | None = Field(None, description='Filter response fields. Use `kapso()` to include Kapso-specific extensions.\n\nExample: `fields=kapso(direction,status,processing_status)`\n')


class KapsoListConversationsConfig(_Operation):
    """List conversations."""
    operation: Literal["list_conversations"] = Field("list_conversations", json_schema_extra={"ui:hidden": True})
    phone_number_id: str = Field(..., min_length=1, description='WhatsApp Business Phone Number ID')
    status: Literal['active', 'ended'] | None = Field(None, description='Filter by conversation status')
    assigned_user_id: UUID | None = Field(None, description='Filter by active assignee user ID (must be a project member)')
    unassigned: bool | None = Field(None, description='Filter conversations with no active assignment. Cannot be combined with `assigned_user_id`.')
    last_active_since: datetime | None = Field(None, description='Filter conversations active on or after this time (ISO 8601)')
    last_active_until: datetime | None = Field(None, description='Filter conversations active on or before this time (ISO 8601)')
    phone_number: str | None = Field(None, description='Filter by contact phone number')
    limit: int | None = Field(20, ge=1, le=100, description='Maximum number of results per page (default 20, max 100)')
    before: str | None = Field(None, description='Cursor for previous page (Base64 encoded)')
    after: str | None = Field(None, description='Cursor for next page (Base64 encoded)')
    fields: str | None = Field(None, description='Filter response fields. Use `kapso()` to include Kapso-specific extensions.')


class KapsoGetConversationConfig(_Operation):
    """Get conversation details."""
    operation: Literal["get_conversation"] = Field("get_conversation", json_schema_extra={"ui:hidden": True})
    phone_number_id: str = Field(..., min_length=1, description='WhatsApp Business Phone Number ID')
    conversation_id: str = Field(..., min_length=1, description='Conversation ID')
    fields: str | None = Field(None, description='Filter response fields. Use `kapso()` to include Kapso-specific extensions.')


class KapsoListContactsConfig(_Operation):
    """List contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    phone_number_id: str = Field(..., min_length=1, description='WhatsApp Business Phone Number ID')
    wa_id: str | None = Field(None, description='Filter by WhatsApp ID (phone number)')
    customer_id: str | None = Field(None, description='Filter by associated customer ID')
    has_customer: bool | None = Field(None, description='Filter by customer association (true/false)')
    limit: int | None = Field(20, ge=1, le=100, description='Maximum number of results per page (default 20, max 100)')
    before: str | None = Field(None, description='Cursor for previous page (Base64 encoded)')
    after: str | None = Field(None, description='Cursor for next page (Base64 encoded)')
    fields: str | None = Field(None, description='Filter response fields. Use `kapso()` to include Kapso-specific extensions.')


class KapsoGetContactConfig(_Operation):
    """Get contact details."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    phone_number_id: str = Field(..., min_length=1, description='WhatsApp Business Phone Number ID')
    wa_id: str = Field(..., min_length=1, description='WhatsApp ID (phone number)')
    fields: str | None = Field(None, description='Filter response fields')


class KapsoListTemplatesConfig(_Operation):
    """List message templates."""
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, description='Filter by template name')
    status: Literal['APPROVED', 'PENDING', 'REJECTED'] | None = Field(None, description='Filter by template status')
    category: Literal['AUTHENTICATION', 'MARKETING', 'UTILITY'] | None = Field(None, description='Filter by template category')
    language: str | None = Field(None, description='Filter by language code')
    limit: int | None = Field(20, ge=1, le=100, description='Maximum number of results (default 20, max 100)')


class KapsoCreateTemplateConfig(_Operation):
    """Create or update message template."""
    operation: Literal["create_template"] = Field("create_template", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., pattern=r"^[a-z0-9_]+$")
    language: str = Field(..., min_length=1)
    category: Literal["AUTHENTICATION", "MARKETING", "UTILITY"]
    components: list[dict] = Field(..., min_length=1, description="WhatsApp template components, including a BODY component")
    parameter_format: Literal["NAMED", "POSITIONAL"] | None = None


class KapsoDeleteTemplateConfig(_Operation):
    """Delete message template."""
    operation: Literal["delete_template"] = Field("delete_template", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., description='Template name to delete (use this OR hsm_id)', min_length=1)


class KapsoGetTemplateConfig(_Operation):
    """Get message template by ID."""
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})
    template_id: str = Field(..., min_length=1, description='Template ID')
    fields: str | None = Field(None, description='Comma-separated list of fields to retrieve')


class KapsoGetBusinessProfileConfig(_Operation):
    """Get business profile."""
    operation: Literal["get_business_profile"] = Field("get_business_profile", json_schema_extra={"ui:hidden": True})
    phone_number_id: str = Field(..., min_length=1, description='WhatsApp Business Phone Number ID')
    fields: str | None = Field(None, description='Comma-separated list of fields to retrieve')


class KapsoUpdateBusinessProfileConfig(_Operation):
    """Update business profile."""
    operation: Literal["update_business_profile"] = Field("update_business_profile", json_schema_extra={"ui:hidden": True})
    phone_number_id: str = Field(..., min_length=1, description='WhatsApp Business Phone Number ID')
    about: str = Field(..., min_length=1, max_length=139, description="New WhatsApp Business About text")


class KapsoListBlockedUsersConfig(_Operation):
    """List blocked users."""
    operation: Literal["list_blocked_users"] = Field("list_blocked_users", json_schema_extra={"ui:hidden": True})
    phone_number_id: str = Field(..., min_length=1, description='WhatsApp Business Phone Number ID')


class KapsoBlockUsersConfig(_Operation):
    """Block users."""
    operation: Literal["block_users"] = Field("block_users", json_schema_extra={"ui:hidden": True})
    phone_number_id: str = Field(..., min_length=1, description='WhatsApp Business Phone Number ID')
    users: list[str] = Field(..., min_length=1, description="WhatsApp IDs (phone numbers) to block")


class KapsoUnblockUsersConfig(_Operation):
    """Unblock users."""
    operation: Literal["unblock_users"] = Field("unblock_users", json_schema_extra={"ui:hidden": True})
    phone_number_id: str = Field(..., min_length=1, description='WhatsApp Business Phone Number ID')
    users: list[str] = Field(..., min_length=1, description="WhatsApp IDs (phone numbers) to unblock")


class KapsoListFlowsConfig(_Operation):
    """List flows."""
    operation: Literal["list_flows"] = Field("list_flows", json_schema_extra={"ui:hidden": True})


class KapsoGetFlowConfig(_Operation):
    """Get flow details."""
    operation: Literal["get_flow"] = Field("get_flow", json_schema_extra={"ui:hidden": True})
    flow_id: str = Field(..., min_length=1, description='Flow ID')
    fields: str = Field(..., description='Comma-separated list of fields to retrieve.\n\nAvailable fields: id, name, status, categories, validation_errors, json_version, data_api_version, endpoint_uri, preview, whatsapp_business_account, application, health_status\n\nPreview can be invalidated: `preview.invalidate(true)`\n\nMetrics: `metric.name(ENDPOINT_REQUEST_COUNT).granularity(DAY).since(2024-01-28).until(2024-01-30)`\n')
    phone_number_id: str | None = Field(None, description='Required when accessing flow by ID (unless business_account_id provided)')


class KapsoListPhoneNumbersConfig(_Operation):
    """List phone numbers."""
    operation: Literal["list_phone_numbers"] = Field("list_phone_numbers", json_schema_extra={"ui:hidden": True})
    fields: str | None = Field(None, description='Comma-separated list of fields to retrieve.\n\nAvailable fields: id, verified_name, display_phone_number, quality_rating, code_verification_status, is_official_business_account, name_status, new_name_status, platform_type, throughput, account_mode, certificate, messaging_limit_tier\n')


class KapsoGetPhoneNumberConfig(_Operation):
    """Get phone number details."""
    operation: Literal["get_phone_number"] = Field("get_phone_number", json_schema_extra={"ui:hidden": True})
    phone_number_id: str = Field(..., min_length=1, description='WhatsApp Business Phone Number ID')
    fields: str | None = Field(None, description='Comma-separated list of fields to retrieve.\n\nAvailable fields: id, verified_name, display_phone_number, quality_rating, code_verification_status, is_official_business_account, name_status, new_name_status, platform_type, throughput, account_mode, certificate, messaging_limit_tier\n\nExample: `fields=id,verified_name,display_phone_number,quality_rating,throughput,messaging_limit_tier`\n')


KapsoConfig = Annotated[Union[
    KapsoListMessagesConfig,
    KapsoSendTextConfig,
    KapsoSendTemplateConfig,
    KapsoGetMessageConfig,
    KapsoListConversationsConfig,
    KapsoGetConversationConfig,
    KapsoListContactsConfig,
    KapsoGetContactConfig,
    KapsoListTemplatesConfig,
    KapsoCreateTemplateConfig,
    KapsoDeleteTemplateConfig,
    KapsoGetTemplateConfig,
    KapsoGetBusinessProfileConfig,
    KapsoUpdateBusinessProfileConfig,
    KapsoListBlockedUsersConfig,
    KapsoBlockUsersConfig,
    KapsoUnblockUsersConfig,
    KapsoListFlowsConfig,
    KapsoGetFlowConfig,
    KapsoListPhoneNumbersConfig,
    KapsoGetPhoneNumberConfig
], Field(discriminator="operation")]


class KapsoFullConfig(NodeConfig[KapsoConfig, KapsoAPIKeyCredential]):
    pass


ROUTES = {
    "send_template": ("POST", "/{phone_number_id}/messages"),
    "list_messages": ("GET", "/{phone_number_id}/messages"),
    "send_text": ("POST", "/{phone_number_id}/messages"),
    "get_message": ("GET", "/{phone_number_id}/messages/{message_id}"),
    "list_conversations": ("GET", "/{phone_number_id}/conversations"),
    "get_conversation": ("GET", "/{phone_number_id}/conversations/{conversation_id}"),
    "list_contacts": ("GET", "/{phone_number_id}/contacts"),
    "get_contact": ("GET", "/{phone_number_id}/contacts/{wa_id}"),
    "list_templates": ("GET", "/{business_account_id}/message_templates"),
    "create_template": ("POST", "/{business_account_id}/message_templates"),
    "delete_template": ("DELETE", "/{business_account_id}/message_templates"),
    "get_template": ("GET", "/{business_account_id}/message_templates/{template_id}"),
    "get_business_profile": ("GET", "/{phone_number_id}/whatsapp_business_profile"),
    "update_business_profile": ("POST", "/{phone_number_id}/whatsapp_business_profile"),
    "list_blocked_users": ("GET", "/{phone_number_id}/block_users"),
    "block_users": ("POST", "/{phone_number_id}/block_users"),
    "unblock_users": ("DELETE", "/{phone_number_id}/block_users"),
    "list_flows": ("GET", "/{business_account_id}/flows"),
    "get_flow": ("GET", "/{flow_id}"),
    "list_phone_numbers": ("GET", "/{business_account_id}/phone_numbers"),
    "get_phone_number": ("GET", "/{phone_number_id}"),
}
QUERY_FIELDS = {
    "send_template": [],
    "list_messages": ["conversation_id", "direction", "status", "since", "until", "limit", "before", "after", "fields"],
    "send_text": [],
    "get_message": ["fields"],
    "list_conversations": ["status", "assigned_user_id", "unassigned", "last_active_since", "last_active_until", "phone_number", "limit", "before", "after", "fields"],
    "get_conversation": ["fields"],
    "list_contacts": ["wa_id", "customer_id", "has_customer", "limit", "before", "after", "fields"],
    "get_contact": ["fields"],
    "list_templates": ["name", "status", "category", "language", "limit"],
    "create_template": ["hsm_id"],
    "delete_template": ["name", "hsm_id"],
    "get_template": ["fields"],
    "get_business_profile": ["fields"],
    "update_business_profile": [],
    "list_blocked_users": [],
    "block_users": [],
    "unblock_users": [],
    "list_flows": [],
    "get_flow": ["fields", "phone_number_id", "business_account_id"],
    "list_phone_numbers": ["fields"],
    "get_phone_number": ["fields"],
}


class KapsoNode(WorkflowNode):
    integration_type = "automation-kapso"
    connection_evidence = ConnectionEvidence(noun="phone numbers", operation="list_phone_numbers",
        label_keys=("verified_name", "display_phone_number", "id"))

    @classmethod
    def get_config_model(cls):
        return KapsoFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Kapso API key")
        credential = self.config.credentials
        op = self.config.config
        config = op.model_dump(mode="json", exclude_none=True)
        method, path = ROUTES[op.operation]
        ids = {**config, "business_account_id": credential.business_account_id}
        path = re.sub(r"\{([^}]+)\}", lambda match: quote(ids[match[1]], safe=""), path)
        params = {name: config[name] for name in QUERY_FIELDS[op.operation] if name in config}
        if op.operation == "get_flow":
            params["business_account_id"] = credential.business_account_id
        body = None
        if op.operation == "send_text":
            body = {"messaging_product": "whatsapp", "to": op.to, "type": "text", "text": {"body": op.text}}
        elif op.operation == "send_template":
            template = {"name": op.name, "language": {"code": op.language}}
            if op.components is not None:
                template["components"] = op.components
            body = {"messaging_product": "whatsapp", "to": op.to, "type": "template", "template": template}
        elif op.operation == "create_template":
            body = {name: config[name] for name in ("name", "language", "category", "components", "parameter_format") if name in config}
        elif op.operation == "update_business_profile":
            body = {"messaging_product": "whatsapp", "about": op.about}
        elif op.operation in {"block_users", "unblock_users"}:
            body = {"block_users": [{"user": user} for user in op.users]}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, params=params,
                **({"json": body} if body is not None else {}), headers={"X-API-Key": credential.api_key, "Accept": "application/json"})
        if not 200 <= response.status_code < 300:
            try:
                error = response.json()
            except ValueError:
                error = {"message": "Kapso returned a non-JSON error"}
            output = {"status": "error", "http_status": response.status_code, "error": error}
        else:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object from Kapso")
            if "error" in data:
                output = {"status": "error", "error": data["error"]}
            elif data.get("success") is False:
                output = {"status": "error", "error": data}
            else:
                if op.operation == "list_phone_numbers" and not isinstance(data.get("data"), list):
                    raise ValueError("Expected a phone-number list from Kapso")
                output = {"status": "success", "data": data}
        output = _redact(output, credential.api_key)
        await self.emit(output)
        return output


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items()}
    return value
