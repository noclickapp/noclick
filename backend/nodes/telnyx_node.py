"""Telnyx API v2 messaging, phone numbers and account reads.

Each operation makes exactly one provider request; lists return one page with
Telnyx pagination metadata. Write acknowledgements do not imply delivery.
"""
from typing import Annotated, Literal, Union
from uuid import UUID
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE = "https://api.telnyx.com/v2"

class TelnyxAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Telnyx API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://portal.telnyx.com/#/app/api-keys",
        "x-credential-instructions": "Paste a Telnyx API v2 key from Mission Control. The key is sent as a Bearer token to api.telnyx.com. Phone-number reads verify access; messaging requires an enabled messaging profile and an authorized sender."})
    credential_type: Literal["telnyx_api_key"] = Field("telnyx_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class _Page(_Input):
    page_number: int = Field(1, ge=1, description="Telnyx page[number]; lists return one page.")
    page_size: int = Field(20, ge=1, le=100, description="Telnyx page[size].")

class _Resource(_Input):
    id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="Telnyx resource ID, not a phone number or URL.")

class _UUIDResource(_Input):
    id: UUID = Field(..., description="Telnyx resource UUID.")

class SendMessage(_Input):
    operation: Literal["send_message"] = Field("send_message", title="Send Message", json_schema_extra={"ui:hidden": True})
    from_number: str = Field(..., pattern=r"^\+[1-9][0-9]{6,14}$", description="Authorized E.164 sender.")
    to: str = Field(..., pattern=r"^\+[1-9][0-9]{6,14}$")
    text: str = Field(..., min_length=1, max_length=10000)
    messaging_profile_id: str | None = None
    media_urls: list[str] | None = Field(None, max_length=10, description="Public media URLs for MMS.")
    type: Literal["SMS", "MMS"] = "SMS"

class GetMessage(_UUIDResource):
    operation: Literal["get_message"] = Field("get_message", title="Get Message", json_schema_extra={"ui:hidden": True})

class CancelMessage(_UUIDResource):
    operation: Literal["cancel_message"] = Field("cancel_message", title="Cancel Message", json_schema_extra={"ui:hidden": True})

class ListMessagingProfiles(_Page):
    operation: Literal["list_messaging_profiles"] = Field("list_messaging_profiles", title="List Messaging Profiles", json_schema_extra={"ui:hidden": True})

class GetMessagingProfile(_UUIDResource):
    operation: Literal["get_messaging_profile"] = Field("get_messaging_profile", title="Get Messaging Profile", json_schema_extra={"ui:hidden": True})

class CreateMessagingProfile(_Input):
    operation: Literal["create_messaging_profile"] = Field("create_messaging_profile", title="Create Messaging Profile", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    whitelisted_destinations: list[str] = Field(..., min_length=1, description="ISO alpha-2 country codes such as US.")
    webhook_url: str | None = None

class UpdateMessagingProfile(_UUIDResource):
    operation: Literal["update_messaging_profile"] = Field("update_messaging_profile", title="Update Messaging Profile", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=255)
    enabled: bool | None = None
    webhook_url: str | None = None

class DeleteMessagingProfile(_UUIDResource):
    operation: Literal["delete_messaging_profile"] = Field("delete_messaging_profile", title="Delete Messaging Profile", json_schema_extra={"ui:hidden": True})

class ListPhoneNumbers(_Page):
    operation: Literal["list_phone_numbers"] = Field("list_phone_numbers", title="List Phone Numbers", json_schema_extra={"ui:hidden": True})

class GetPhoneNumber(_Resource):
    operation: Literal["get_phone_number"] = Field("get_phone_number", title="Get Phone Number", json_schema_extra={"ui:hidden": True})

class UpdatePhoneNumber(_Resource):
    operation: Literal["update_phone_number"] = Field("update_phone_number", title="Update Phone Number", json_schema_extra={"ui:hidden": True})
    customer_reference: str = Field(..., min_length=1, max_length=255)
    tags: list[str] | None = None
    connection_id: str | None = None

class GetPhoneNumberMessaging(_Resource):
    operation: Literal["get_phone_number_messaging"] = Field("get_phone_number_messaging", title="Get Phone Number Messaging", json_schema_extra={"ui:hidden": True})

class UpdatePhoneNumberMessaging(_Resource):
    operation: Literal["update_phone_number_messaging"] = Field("update_phone_number_messaging", title="Update Phone Number Messaging", json_schema_extra={"ui:hidden": True})
    messaging_profile_id: str = Field(..., min_length=1, description="Profile UUID to assign to this number.")
    tags: list[str] | None = None

class GetBalance(_Input):
    operation: Literal["get_balance"] = Field("get_balance", title="Get Balance", json_schema_extra={"ui:hidden": True})

class ListNumberOrders(_Page):
    operation: Literal["list_number_orders"] = Field("list_number_orders", title="List Number Orders", json_schema_extra={"ui:hidden": True})

class GetNumberOrder(_Resource):
    operation: Literal["get_number_order"] = Field("get_number_order", title="Get Number Order", json_schema_extra={"ui:hidden": True})

class UpdateNumberOrder(_Resource):
    operation: Literal["update_number_order"] = Field("update_number_order", title="Update Number Order", json_schema_extra={"ui:hidden": True})
    customer_reference: str = Field(..., min_length=1, max_length=255)

# Telnyx's own MCP server: agents get its tools through a person's Telnyx sign-in.
# It answers without a token too; its resource metadata names Telnyx's sign-in.
TelnyxMcpCredential = mcp_credential("telnyx", "https://api.telnyx.com/v2/mcp", app="Telnyx")
TelnyxCredential = Union[TelnyxAPIKeyCredential, TelnyxMcpCredential]


Operation = Annotated[Union[SendMessage, GetMessage, CancelMessage, ListMessagingProfiles, GetMessagingProfile, CreateMessagingProfile, UpdateMessagingProfile, DeleteMessagingProfile, ListPhoneNumbers, GetPhoneNumber, UpdatePhoneNumber, GetPhoneNumberMessaging, UpdatePhoneNumberMessaging, GetBalance, ListNumberOrders, GetNumberOrder, UpdateNumberOrder], Field(discriminator="operation")]

class TelnyxNodeConfig(NodeConfig[Operation, TelnyxCredential]):
    pass

ROUTES = {'send_message': ('POST',
                  '/messages',
                  ('from_number', 'to', 'text', 'messaging_profile_id', 'media_urls', 'type'),
                  {'from_number': 'from'}),
 'get_message': ('GET', '/messages/{id}', (), {}),
 'cancel_message': ('DELETE', '/messages/{id}', (), {}),
 'list_messaging_profiles': ('GET', '/messaging_profiles', (), {}),
 'get_messaging_profile': ('GET', '/messaging_profiles/{id}', (), {}),
 'create_messaging_profile': ('POST',
                              '/messaging_profiles',
                              ('name', 'whitelisted_destinations', 'webhook_url'),
                              {}),
 'update_messaging_profile': ('PATCH', '/messaging_profiles/{id}', ('name', 'enabled', 'webhook_url'), {}),
 'delete_messaging_profile': ('DELETE', '/messaging_profiles/{id}', (), {}),
 'list_phone_numbers': ('GET', '/phone_numbers', (), {}),
 'get_phone_number': ('GET', '/phone_numbers/{id}', (), {}),
 'update_phone_number': ('PATCH', '/phone_numbers/{id}', ('customer_reference', 'tags', 'connection_id'), {}),
 'get_phone_number_messaging': ('GET', '/phone_numbers/{id}/messaging', (), {}),
 'update_phone_number_messaging': ('PATCH',
                                   '/phone_numbers/{id}/messaging',
                                   ('messaging_profile_id', 'tags'),
                                   {}),
 'get_balance': ('GET', '/balance', (), {}),
 'list_number_orders': ('GET', '/number_orders', (), {}),
 'get_number_order': ('GET', '/number_orders/{number_order_id}', (), {}),
 'update_number_order': ('PATCH', '/number_orders/{number_order_id}', ('customer_reference',), {})}

def _sanitize(value, token):
    if isinstance(value, dict):
        return {k: _sanitize(v, token) for k, v in value.items() if k.lower() not in {"v1_secret", "api_key", "authorization", "secret"}}
    if isinstance(value, list):
        return [_sanitize(v, token) for v in value]
    return value.replace(token, "[redacted]") if isinstance(value, str) else value

class TelnyxNode(WorkflowNode):
    integration_type = "automation-telnyx"
    credential_provider_labels = {"telnyx": "Telnyx Account"}
    connection_evidence = ConnectionEvidence(noun="phone numbers", operation="list_phone_numbers", label_keys=("phone_number", "id"))

    @classmethod
    def get_config_model(cls):
        return TelnyxNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Telnyx API key")
        op = self.config.config
        token = self.config.credentials.api_key
        method, path, fields, aliases = ROUTES[op.operation]
        if isinstance(op, (_Resource, _UUIDResource)):
            path = path.replace("{id}", quote(str(op.id), safe="")).replace("{number_order_id}", quote(str(op.id), safe=""))
        params = {"page[number]": op.page_number, "page[size]": op.page_size} if isinstance(op, _Page) else None
        body = {aliases.get(k, k): getattr(op, k) for k in fields if getattr(op, k) is not None} if fields else None
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, params=params, **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            raise ValueError("Telnyx request could not be completed; inspect write status before retrying") from None
        if response.is_error or response.is_redirect:
            try:
                detail = _sanitize(response.json(), token)
            except ValueError:
                detail = "Telnyx returned a non-JSON error"
            result = {"status": "error", "success": False, "http_status": response.status_code, "message": detail}
        elif response.status_code == 204:
            result = {"status": "success", "http_status": 204, "acknowledged": True}
        else:
            try:
                payload = response.json()
            except ValueError:
                raise ValueError("Telnyx returned an unexpected non-JSON response") from None
            # Cancellation returns the message itself rather than a data envelope.
            if op.operation == "cancel_message" and isinstance(payload, dict) and "data" not in payload:
                payload = {"data": payload}
            if not isinstance(payload, dict) or "data" not in payload:
                raise ValueError("Telnyx returned an unexpected response envelope")
            result = {"status": "success", "http_status": response.status_code, **_sanitize(payload, token)}
        await self.emit(result)
        return result
