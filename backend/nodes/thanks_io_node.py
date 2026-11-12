"""thanks.io v2 account automation. Contract: https://docs.thanks.io/api-reference/openapi.json.

Every operation makes exactly one request. Provider links are returned, never followed.
"""
from __future__ import annotations
from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.thanks.io/api/v2"


class ThanksIoApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Thanks Io API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://dashboard.thanks.io/app/settings/api-access",
        "x-credential-instructions": "In thanks.io, open Settings → API Access. Create and copy an API key, then paste it here to connect your account. NoClick sends it as a bearer token to api.thanks.io.",
    })
    credential_type: Literal["thanks_io_api_key"] = Field("thanks_io_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste only the API key, without the Bearer prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


# thanks.io's own MCP server: agents get its tools through a person's thanks.io sign-in.
ThanksIoMcpCredential = mcp_credential("thanks_io", "https://mcp.thanks.io/mcp", app="thanks.io")
ThanksIoCredential = Union[ThanksIoApiKeyCredential, ThanksIoMcpCredential]


Id = Annotated[int, Field(ge=1)]
Text = Annotated[str, Field(min_length=1, max_length=20000)]


class ListMailingLists(Input):
    """List one page of account mailing lists with provider pagination metadata."""
    operation: Literal["list_mailing_lists"] = "list_mailing_lists"
    items_per_page: int = Field(25, ge=1, le=100)


class CreateMailingList(Input):
    operation: Literal["create_mailing_list"] = "create_mailing_list"
    description: Text
    sub_account_id: Id | None = None
    qrcode_url: str | None = None


class GetMailingList(Input):
    operation: Literal["get_mailing_list"] = "get_mailing_list"
    mailing_list_id: Id


class DeleteMailingList(GetMailingList):
    operation: Literal["delete_mailing_list"] = "delete_mailing_list"


class ListRecipients(GetMailingList):
    """Bounded recipient listing; updated_since filters changed recipients."""
    operation: Literal["list_recipients"] = "list_recipients"
    limit: int = Field(1000, ge=1, le=10000)
    updated_since: str | None = Field(None, description="Provider timestamp, e.g. 2020-04-06 01:55:50")


class AddressFields(Input):
    name: str | None = None
    company: str | None = None
    address: str | None = None
    address2: str | None = None
    city: str | None = None
    province: str | None = None
    postal_code: str | None = None
    country: str | None = None
    email: str | None = None
    phone: str | None = None
    dob: str | None = None
    anniversary: str | None = None
    custom1: str | None = None
    custom2: str | None = None
    custom3: str | None = None
    custom4: str | None = None
    custom5: str | None = None
    custom6: str | None = None
    custom7: str | None = None
    custom8: str | None = None
    custom9: str | None = None
    custom10: str | None = None


class CreateRecipient(AddressFields):
    """Add to a mailing list; existing campaigns may send mail. Email-only lookup may incur a fee."""
    operation: Literal["create_recipient"] = "create_recipient"
    mailing_list_id: Id

    @model_validator(mode="after")
    def destination(self):
        if not (self.address and self.address.strip()) and not (self.email and self.email.strip()):
            raise ValueError("Provide a mailing address or email address")
        return self


class GetRecipient(Input):
    operation: Literal["get_recipient"] = "get_recipient"
    recipient_id: Id


class UpdateRecipient(AddressFields):
    operation: Literal["update_recipient"] = "update_recipient"
    recipient_id: Id
    mailing_list_id: Id | None = None

    @model_validator(mode="after")
    def changes(self):
        if not self.model_dump(exclude={"operation", "recipient_id"}, exclude_none=True):
            raise ValueError("Provide at least one recipient field to update")
        return self


class DeleteRecipient(GetRecipient):
    operation: Literal["delete_recipient"] = "delete_recipient"


class ListImageTemplates(Input):
    operation: Literal["list_image_templates"] = "list_image_templates"
    items_per_page: int = Field(25, ge=1, le=100)
    sub_account_id: Id | None = None
    type: Literal["postcard", "postcard6x9", "postcard6x11", "letter", "windowlessletter", "notecard", "giftcard", "magnacard"] | None = None


class ListMessageTemplates(ListImageTemplates):
    operation: Literal["list_message_templates"] = "list_message_templates"


class GetMessageTemplate(Input):
    operation: Literal["get_message_template"] = "get_message_template"
    message_template_id: Id


class CreateMessageTemplate(Input):
    operation: Literal["create_message_template"] = "create_message_template"
    name: Text
    content: Text
    type: Literal["postcard", "postcard6x9", "postcard6x11", "letter", "windowlessletter", "notecard", "magnacard"] = "postcard"
    handwriting_style_id: Id | None = None
    font_color: str | None = None
    handwriting_realism: bool | None = None
    sub_account_id: Id | None = None


class UpdateMessageTemplate(Input):
    operation: Literal["update_message_template"] = "update_message_template"
    message_template_id: Id
    name: Text | None = None
    content: Text | None = None
    handwriting_style_id: Id | None = None
    font_color: str | None = None
    handwriting_realism: bool | None = None

    @model_validator(mode="after")
    def changes(self):
        if not self.model_dump(exclude={"operation", "message_template_id"}, exclude_none=True):
            raise ValueError("Provide at least one template field to update")
        return self


class DeleteMessageTemplate(GetMessageTemplate):
    operation: Literal["delete_message_template"] = "delete_message_template"


class PostcardFields(Input):
    mailing_list_ids: list[Id] = Field(..., min_length=1, max_length=100, description="Mailing lists to target; sending creates a paid direct-mail order.")
    size: Literal["4x6", "6x9", "6x11"] = "4x6"
    creative_id: Id | None = Field(None, description="Saved creative; replaces image and message settings.")
    image_template_id: Id | None = None
    front_image_url: str | None = None
    message: Text | None = None
    message_template_id: Id | None = None
    handwriting_style_id: Id | None = None
    handwriting_color: Literal["blue", "black", "green", "purple", "red"] | None = None
    handwriting_realism: bool | None = None
    sub_account: Id | None = None
    qrcode_url: str | None = None
    postage_class: Literal["first_class", "standard"] | None = None
    return_name: str | None = None
    return_address: str | None = None
    return_address2: str | None = None
    return_city: str | None = None
    return_state: str | None = None
    return_postal_code: str | None = None
    metadata: dict | None = None

    @model_validator(mode="after")
    def creative(self):
        if self.creative_id is None:
            if not (self.image_template_id or self.front_image_url):
                raise ValueError("Choose a creative, image template or front image URL")
            if not (self.message_template_id or self.message):
                raise ValueError("Provide a message or message template")
        return self


class SendPostcard(PostcardFields):
    """Submit a paid postcard order, or generate previews when preview is true."""
    operation: Literal["send_postcard"] = "send_postcard"
    preview: bool = Field(False, description="True generates preview images without placing an order.")


class EstimatePostcard(PostcardFields):
    """Estimate costs without charging, printing, mailing or creating an order."""
    operation: Literal["estimate_postcard"] = "estimate_postcard"


class ListOrders(ListImageTemplates):
    operation: Literal["list_orders"] = "list_orders"
    creative_id: Id | None = None
    campaign: Id | None = None


class TrackOrder(Input):
    operation: Literal["track_order"] = "track_order"
    order_id: Id


class ListOrderItems(TrackOrder):
    operation: Literal["list_order_items"] = "list_order_items"
    per_page: int = Field(50, ge=1, le=100)
    page: int = Field(1, ge=1)


class CancelOrder(TrackOrder):
    """Request cancellation and credit refund; only Reviewing orders can be cancelled."""
    operation: Literal["cancel_order"] = "cancel_order"


ThanksIoConfig = Annotated[Union[ListMailingLists, CreateMailingList, GetMailingList, DeleteMailingList,
    ListRecipients, CreateRecipient, GetRecipient, UpdateRecipient, DeleteRecipient, ListImageTemplates,
    ListMessageTemplates, CreateMessageTemplate, GetMessageTemplate, UpdateMessageTemplate, DeleteMessageTemplate,
    SendPostcard, EstimatePostcard, ListOrders, TrackOrder, ListOrderItems, CancelOrder], Field(discriminator="operation")]


class ThanksIoNodeConfig(NodeConfig[ThanksIoConfig, ThanksIoCredential]):
    pass


# Explicit one-operation-to-one-endpoint mapping, without arbitrary requests.
ROUTES = {
    "list_mailing_lists": ("GET", "/mailing-lists/", None),
    "create_mailing_list": ("POST", "/mailing-lists/", None),
    "get_mailing_list": ("GET", "/mailing-lists/{mailing_list_id}", "mailing_list_id"),
    "delete_mailing_list": ("DELETE", "/mailing-lists/{mailing_list_id}", "mailing_list_id"),
    "list_recipients": ("GET", "/mailing-lists-utils/recipients/{mailing_list_id}", "mailing_list_id"),
    "create_recipient": ("POST", "/recipients", None),
    "get_recipient": ("GET", "/recipients/{recipient_id}", "recipient_id"),
    "update_recipient": ("PUT", "/recipients/{recipient_id}", "recipient_id"),
    "delete_recipient": ("DELETE", "/recipients/{recipient_id}", "recipient_id"),
    "list_image_templates": ("GET", "/image-templates/", None),
    "list_message_templates": ("GET", "/message-templates/", None),
    "create_message_template": ("POST", "/message-templates/", None),
    "get_message_template": ("GET", "/message-templates/{message_template_id}", "message_template_id"),
    "update_message_template": ("PATCH", "/message-templates/{message_template_id}", "message_template_id"),
    "delete_message_template": ("DELETE", "/message-templates/{message_template_id}", "message_template_id"),
    "send_postcard": ("POST", "/send/postcard", None),
    "estimate_postcard": ("POST", "/estimate/postcard", None),
    "list_orders": ("GET", "/orders/list", None),
    "track_order": ("GET", "/orders/{order_id}/track", "order_id"),
    "list_order_items": ("GET", "/orders/{order_id}/items", "order_id"),
    "cancel_order": ("PUT", "/orders/{order_id}/cancel", "order_id"),
}


def _redact(value, token):
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()
                if k.lower() not in {"api_key", "access_token", "refresh_token", "authorization"}}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value.replace(token, "[redacted]") if isinstance(value, str) else value


class ThanksIoNode(WorkflowNode):
    integration_type = "automation-thanks-io"
    credential_provider_labels = {"thanks_io": "thanks.io Account"}
    connection_evidence = ConnectionEvidence(noun="mailing lists", operation="list_mailing_lists", label_keys=("description", "id"))

    @classmethod
    def get_config_model(cls):
        return ThanksIoNodeConfig

    @staticmethod
    def _guard(config_data):
        credential = config_data.get("credentials")
        if credential is not None:
            if not isinstance(credential, dict):
                raise ValueError("Thanks Io credential data is invalid")
            if "credential_type" in credential and credential["credential_type"] != "thanks_io_api_key":
                raise ValueError("Attach a Thanks Io API key credential")

    @classmethod
    def parse_config(cls, config_data):
        cls._guard(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._guard(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Thanks Io API key")
        config, token = self.config.config, self.config.credentials.api_key
        method, route, path_field = ROUTES[config.operation]
        values = config.model_dump(exclude={"operation"}, exclude_none=True)
        if path_field:
            route = route.format(**{path_field: values.pop(path_field)})
        kwargs = {"params": values} if method == "GET" else {"json": values} if values else {}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + route,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
        except httpx.HTTPError:
            raise ValueError("Thanks Io request could not be confirmed; inspect orders before retrying a send") from None
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Thanks Io returned an unexpected non-JSON response") from None
        payload = _redact(payload, token)
        if not response.is_success:
            output = {"status": "error", "success": False, "http_status": response.status_code, "error": payload}
        else:
            if not isinstance(payload, dict):
                raise ValueError("Thanks Io returned an unexpected response shape")
            if payload.get("status") in ("failed", "error") or payload.get("errors"):
                output = {"status": "error", "success": False, "http_status": response.status_code, "error": payload}
            else:
                if config.operation.startswith("list_") and not isinstance(payload.get("data"), list):
                    raise ValueError("Thanks Io returned an unexpected list response shape")
                output = {"status": "success", "success": True, "http_status": response.status_code, "data": payload}
        await self.emit(output)
        return output
