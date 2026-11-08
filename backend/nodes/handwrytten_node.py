"""Handwrytten v1 cards, recipients, templates and single-step orders.

Uses an existing session UID from the pinned v1 contract, never account passwords.
Each workflow action issues exactly one published API operation, without retries.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.handwrytten.com/v1"


class HandwryttenSessionToken(BaseModel):
    model_config = ConfigDict(title="Handwrytten Session Token", extra="forbid", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.handwrytten.com/api/sign-in-with-password/",
            "x-credential-instructions": "Paste an existing session UID token returned by Handwrytten /auth/authorization. This integration targets the published v1 API, which sends this token as uid in authenticated JSON requests. Do not paste your password or a v2 API key. Handwrytten recommends API keys for its newer v2 API; password sign-in is deprecated but remains supported. NoClick does not sign in, refresh, reset passwords or create accounts. Replace this token if the session expires.",
        })
    credential_type: Literal["handwrytten_session_token"] = Field("handwrytten_session_token", json_schema_extra={"ui:hidden": True})
    session_token: str = Field(..., min_length=1, max_length=4096, title="Session UID token", json_schema_extra={"ui:widget": "password"})

    @field_validator("session_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Session UID token")
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the session UID token")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def country_choice(self):
        for prefix in ("", "sender_", "recipient_"):
            if getattr(self, prefix + "country", None) is not None and getattr(self, prefix + "country_id", None) is not None:
                raise ValueError("Specify a country name or country ID, not both")
        if self.operation in {"update_return_address", "update_recipient", "update_template"}:
            if not self.model_dump(exclude_none=True, exclude={"operation", "id", "address_id", "template_id"}):
                raise ValueError("Provide at least one field to update")
        if self.operation == "send_card":
            for prefix in ("sender_", "recipient_"):
                country = getattr(self, prefix + "country", None)
                country_id = getattr(self, prefix + "country_id", None)
                needs_state = (country_id in {1, 2} or (country_id is None and country is None)
                    or (isinstance(country, str) and country.casefold() in {"united states", "usa", "us", "canada"}))
                if needs_state and not getattr(self, prefix + "state", None):
                    raise ValueError("A state or province is required for US and Canadian addresses")
        if self.operation == "create_custom_card":
            if self.type == "logo" and self.logo_id is None:
                raise ValueError("A logo ID is required for a logo header")
            if self.type == "text" and not self.header_text:
                raise ValueError("Header text is required for a text header")
        return self


class HandwryttenGetReturnAddressConfig(_Input):
    """gets the user's return address information."""
    operation: Literal["get_return_address"] = Field("get_return_address", json_schema_extra={"ui:hidden": True})

class HandwryttenUpdateReturnAddressConfig(_Input):
    """update the user's return address information."""
    operation: Literal["update_return_address"] = Field("update_return_address", json_schema_extra={"ui:hidden": True})
    address_id: int = Field(..., description='the address you are updating', ge=1, le=2147483647)
    name: str | None = Field(None, description='the name on the address', min_length=1, max_length=1000)
    business_name: str | None = Field(None, description='the optional business name on the address', min_length=1, max_length=1000)
    address1: str | None = Field(None, description='the first line of the address', min_length=1, max_length=1000)
    address2: str | None = Field(None, description='the second (optional) line of the address', min_length=1, max_length=1000)
    city: str | None = Field(None, description='the city of the address', min_length=1, max_length=1000)
    state: str | None = Field(None, description='the abbreviated state or province of the address', min_length=1, max_length=1000)
    zip: str | None = Field(None, description='the zip or postal code of the address', min_length=1, max_length=1000)
    country: str | None = Field(None, description='the name of the country of the address', min_length=1, max_length=1000)
    country_id: int | None = Field(None, description='the id of the country of the address. do not use with "country" parameter', ge=1, le=2147483647)

class HandwryttenListRecipientsConfig(_Input):
    """list the addresses in the user's account."""
    operation: Literal["list_recipients"] = Field("list_recipients", json_schema_extra={"ui:hidden": True})

class HandwryttenCreateRecipientConfig(_Input):
    """add a new recipient address."""
    operation: Literal["create_recipient"] = Field("create_recipient", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., description='the name on the address', min_length=1, max_length=1000)
    business_name: str | None = Field(None, description='the optional business name on the address', min_length=1, max_length=1000)
    address1: str = Field(..., description='the first line of the address', min_length=1, max_length=1000)
    address2: str | None = Field(None, description='the second (optional) line of the address', min_length=1, max_length=1000)
    city: str = Field(..., description='the city of the address', min_length=1, max_length=1000)
    state: str | None = Field(None, description='the abbreviated state or province of the address', min_length=1, max_length=1000)
    zip: str = Field(..., description='the zip or postal code of the address', min_length=1, max_length=1000)
    country: str | None = Field(None, description='the name of the country of the address, or use country_id', min_length=1, max_length=1000)
    country_id: int | None = Field(None, description='the country id code of the recipient', ge=1, le=2147483647)

class HandwryttenUpdateRecipientConfig(_Input):
    """updates an existing new recipient address."""
    operation: Literal["update_recipient"] = Field("update_recipient", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., description='the id of the address to update', ge=1, le=2147483647)
    name: str | None = Field(None, description='the updated name on the address', min_length=1, max_length=1000)
    business_name: str | None = Field(None, description='the updated optional business name on the address', min_length=1, max_length=1000)
    address1: str | None = Field(None, description='the updated first line of the address', min_length=1, max_length=1000)
    address2: str | None = Field(None, description='the updated second (optional) line of the address', min_length=1, max_length=1000)
    city: str | None = Field(None, description='the updated city of the address', min_length=1, max_length=1000)
    state: str | None = Field(None, description='the updated abbreviated state or province of the address', min_length=1, max_length=1000)
    zip: str | None = Field(None, description='the updated zip or postal code of the address', min_length=1, max_length=1000)
    country: str | None = Field(None, description='the updated name of the country of the address, or use country_id', min_length=1, max_length=1000)
    country_id: int | None = Field(None, description='the country id of the address', ge=1, le=2147483647)

class HandwryttenDeleteRecipientConfig(_Input):
    """deletes an existing recipient address."""
    operation: Literal["delete_recipient"] = Field("delete_recipient", json_schema_extra={"ui:hidden": True})
    address_id: int = Field(..., description='the id of the address to delete', ge=1, le=2147483647)

class HandwryttenListFontsConfig(_Input):
    """Lists Handwryting styles available for use."""
    operation: Literal["list_fonts"] = Field("list_fonts", json_schema_extra={"ui:hidden": True})

class HandwryttenListCustomizerFontsConfig(_Input):
    """Lists fonts available for use with the card customizer."""
    operation: Literal["list_customizer_fonts"] = Field("list_customizer_fonts", json_schema_extra={"ui:hidden": True})

class HandwryttenListCardsConfig(_Input):
    """Lists information on cards."""
    operation: Literal["list_cards"] = Field("list_cards", json_schema_extra={"ui:hidden": True})
    category_id: int | None = Field(None, description='optional category id filter', ge=1, le=2147483647)

class HandwryttenGetCardConfig(_Input):
    """Provides full information on a specific card."""
    operation: Literal["get_card"] = Field("get_card", json_schema_extra={"ui:hidden": True})
    card_id: int = Field(..., description='the card id to view', ge=1, le=2147483647)

class HandwryttenListGiftCardsConfig(_Input):
    """Lists information on gift cards."""
    operation: Literal["list_gift_cards"] = Field("list_gift_cards", json_schema_extra={"ui:hidden": True})

class HandwryttenListTemplateCategoriesConfig(_Input):
    """List template categories."""
    operation: Literal["list_template_categories"] = Field("list_template_categories", json_schema_extra={"ui:hidden": True})

class HandwryttenListTemplatesConfig(_Input):
    """List template categories."""
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})
    category_id: int | None = Field(None, description='optional category to filter the templates', ge=1, le=2147483647)

class HandwryttenGetTemplateConfig(_Input):
    """Get all info on a template."""
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})
    template_id: int = Field(..., description='the ID of the template to view', ge=1, le=2147483647)

class HandwryttenCreateTemplateConfig(_Input):
    """Creates a New Template in the User’s Account."""
    operation: Literal["create_template"] = Field("create_template", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., description='the new name of the template', min_length=1, max_length=1000)
    message: str = Field(..., description='message', min_length=1, max_length=10000)

class HandwryttenUpdateTemplateConfig(_Input):
    """Updates an Existing Template in the User’s Account."""
    operation: Literal["update_template"] = Field("update_template", json_schema_extra={"ui:hidden": True})
    template_id: int = Field(..., description='the ID of the template to update', ge=1, le=2147483647)
    name: str | None = Field(None, description='the new name of the template', min_length=1, max_length=1000)
    message: str | None = Field(None, description='message', min_length=1, max_length=10000)

class HandwryttenDeleteTemplateConfig(_Input):
    """Deletes a users template."""
    operation: Literal["delete_template"] = Field("delete_template", json_schema_extra={"ui:hidden": True})
    template_id: int = Field(..., description='the ID of the template to delete', ge=1, le=2147483647)

class HandwryttenListCountriesConfig(_Input):
    """list_countries."""
    operation: Literal["list_countries"] = Field("list_countries", json_schema_extra={"ui:hidden": True})

class HandwryttenSendCardConfig(_Input):
    """Send and pay for a physical handwritten card using a saved payment method. No automatic retries."""
    operation: Literal["send_card"] = Field("send_card", json_schema_extra={"ui:hidden": True})
    card_id: int = Field(..., description='the id of the card you want to send', ge=1, le=2147483647)
    denomination_id: int | None = Field(None, description='Optional. Use if sending a gift card', ge=1, le=2147483647)
    message: str = Field(..., description="the full message body. Use '\\n' for new lines", min_length=1, max_length=10000)
    font_label: str = Field(..., description="the colloquial name of the font, such as 'Fancy Jenna' or 'Casual David'", min_length=1, max_length=1000)
    sender_name: str = Field(..., description='the name on the return address', min_length=1, max_length=1000)
    sender_business_name: str | None = Field(None, description='the second line of the return address. Optional.', min_length=1, max_length=1000)
    sender_address1: str = Field(..., description='the first address line of the return address', min_length=1, max_length=1000)
    sender_address2: str | None = Field(None, description='the second line of the address, such as suite, apartment, building, etc. Optional', min_length=1, max_length=1000)
    sender_city: str = Field(..., description='the city of the sender, to appear in the return address', min_length=1, max_length=1000)
    sender_state: str | None = Field(None, description='the ABBREVIATED state or province of the sender. This is required for US and Canada addresses and optional for all other countries', min_length=1, max_length=1000)
    sender_zip: str = Field(..., description='The postal code or zip code of the sender.', min_length=1, max_length=1000)
    sender_country: str | None = Field(None, description='the country of the recipient. Optional and defaults to usa', min_length=1, max_length=1000)
    sender_country_id: int | None = Field(None, description='alternate way to specify country. Optional and defaults to 1', ge=1, le=2147483647)
    recipient_name: str = Field(..., description='the name on the recipient address', min_length=1, max_length=1000)
    recipient_business_name: str | None = Field(None, description='the second line of the recipient address. Optional.', min_length=1, max_length=1000)
    recipient_address1: str = Field(..., description='the first address line of the return address', min_length=1, max_length=1000)
    recipient_address2: str | None = Field(None, description='the second line of the address, such as suite, apartment, building, etc. Optional', min_length=1, max_length=1000)
    recipient_city: str = Field(..., description='the city of the recipient, to appear in the address', min_length=1, max_length=1000)
    recipient_state: str | None = Field(None, description='the ABBREVIATED state or province of the recipient. This is required for US and Canada addresses and optional for all other countries', min_length=1, max_length=1000)
    recipient_zip: str = Field(..., description='the zip code or postal code of the recipient', min_length=1, max_length=1000)
    recipient_country: str | None = Field(None, description='the country of the recipient. Optional and defaults to usa', min_length=1, max_length=1000)
    recipient_country_id: int | None = Field(None, description='alternate way to specify country. Optional and defaults to 1', ge=1, le=2147483647)
    credit_card_id: int = Field(..., description="the credit card id to charge for the order. Currently this is required, even for invoiced accounts, it just won't be charged.", ge=1, le=2147483647)

class HandwryttenCreateCustomCardConfig(_Input):
    """Create a new custom card."""
    operation: Literal["create_custom_card"] = Field("create_custom_card", json_schema_extra={"ui:hidden": True})
    card_id: int = Field(..., description='the card id of the card template you\'re starting with. You can find this by logging into Handwrytten, clicking "customize" next to any customizable card, and pulling the card ID from the end of the URL', ge=1, le=2147483647)
    name: str = Field(..., description='the name of the new card', min_length=1, max_length=1000)
    type: Literal["logo", "text"] = Field(..., description='Defines the top of the back of the card. Set to either "logo" or "text".')
    logo_id: int | None = Field(None, description='Optional. If setting "type" to "logo", set the id of the logo here.', ge=1, le=2147483647)
    header_align: Literal["left", "center", "right"] | None = Field(None, description='set to "left", "center", or "right" to align the header appropriately')
    header_text: str | None = Field(None, description='text in the header, if type is set to "text"', min_length=1, max_length=10000)
    header_font_id: int | None = Field(None, description='font ID of the text in the header, found by using ListFontForCustomizer', ge=1, le=2147483647)
    header_font_size: int | None = Field(None, description='font size of the text in the header of the card', ge=1, le=2147483647)
    header_auto_size: bool | None = Field(None, description='if set to true, the header will be maximized to fill the header area')
    footer_text: str | None = Field(None, description='optional text for the footer of the customizable card', min_length=1, max_length=10000)
    footer_align: Literal["left", "center", "right"] | None = Field(None, description='set to "left", "center", or "right" to align the footer appropriately')
    footer_font_id: int | None = Field(None, description='font ID of the text in the footer, found by using ListFontForCustomizer', ge=1, le=2147483647)
    footer_font_size: int | None = Field(None, description='Font size of the text in the footer', ge=1, le=2147483647)
    logo_size_percent: int | None = Field(None, description='set to the desired scaling of the logo on the header', ge=1, le=1000)
    cover_id: int | None = Field(None, description='the id of the image you want to use for the "cover". The cover is the large image on the front of the flat card.', ge=1, le=2147483647)
    cover_size_percent: int | None = Field(None, description='the size of the image to use as the cover.', ge=1, le=1000)

HandwryttenOperation = Annotated[Union[
    HandwryttenGetReturnAddressConfig,
    HandwryttenUpdateReturnAddressConfig,
    HandwryttenListRecipientsConfig,
    HandwryttenCreateRecipientConfig,
    HandwryttenUpdateRecipientConfig,
    HandwryttenDeleteRecipientConfig,
    HandwryttenListFontsConfig,
    HandwryttenListCustomizerFontsConfig,
    HandwryttenListCardsConfig,
    HandwryttenGetCardConfig,
    HandwryttenListGiftCardsConfig,
    HandwryttenListTemplateCategoriesConfig,
    HandwryttenListTemplatesConfig,
    HandwryttenGetTemplateConfig,
    HandwryttenCreateTemplateConfig,
    HandwryttenUpdateTemplateConfig,
    HandwryttenDeleteTemplateConfig,
    HandwryttenListCountriesConfig,
    HandwryttenSendCardConfig,
    HandwryttenCreateCustomCardConfig
], Field(discriminator="operation")]


class HandwryttenFullConfig(NodeConfig[HandwryttenOperation, HandwryttenSessionToken]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {'get_return_address': ('POST', '/profile/address'), 'update_return_address': ('POST', '/profile/updateAddress'), 'list_recipients': ('POST', '/profile/recipientsList'), 'create_recipient': ('POST', '/profile/profileAddRecipient'), 'update_recipient': ('POST', '/profile/updateRecipient'), 'delete_recipient': ('POST', '/profile/deleteRecipient'), 'list_fonts': ('GET', '/fonts/list'), 'list_customizer_fonts': ('GET', '/fonts/listForCustomizer'), 'list_cards': ('POST', '/cards/list'), 'get_card': ('POST', '/cards/view'), 'list_gift_cards': ('GET', '/giftCards/view'), 'list_template_categories': ('POST', '/templateCategories/list'), 'list_templates': ('POST', '/templates/list'), 'get_template': ('POST', '/templates/view'), 'create_template': ('POST', '/templates/create'), 'update_template': ('POST', '/templates/update'), 'delete_template': ('POST', '/templates/delete'), 'list_countries': ('GET', '/countries/list'), 'send_card': ('POST', '/orders/singleStepOrder'), 'create_custom_card': ('POST', '/cards/createCustomCard')}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(key, token): _redact(item, token) for key, item in value.items()
                if key.lower() not in {"uid", "session_token", "password", "authorization"}}
    return value


class HandwryttenNode(WorkflowNode):
    integration_type = "automation-handwrytten"
    connection_evidence = ConnectionEvidence(noun="recipient addresses", operation="list_recipients")

    @classmethod
    def get_config_model(cls):
        return HandwryttenFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Handwrytten session UID token")
        op = self.config.config
        token = self.config.credentials.session_token
        method, path = ROUTES[op.operation]
        body = op.model_dump(exclude={"operation"}, exclude_none=True)
        if method == "POST":
            body["uid"] = token
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Accept": "application/json"}, **({"json": body} if method == "POST" else {}))
        except (httpx.TimeoutException, httpx.TransportError):
            raise ValueError("Handwrytten request did not complete; inspect the account before retrying a write") from None
        if not 200 <= response.status_code < 300:
            # Do not expose request bodies, token echoes or HTML from error pages.
            message = "Handwrytten HTTP " + str(response.status_code)
            try:
                error = response.json()
                if isinstance(error, dict):
                    detail = error.get("error") or error.get("message")
                    if isinstance(detail, str):
                        message += ": " + _redact(detail[:2000], token)
            except ValueError:
                pass
            raise ValueError(message)
        if len(response.content) > 5_000_000 or response.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
            raise ValueError("Handwrytten returned an unexpected JSON response; inspect before retrying a write")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Handwrytten returned invalid JSON; inspect before retrying a write") from None
        if not isinstance(data, (dict, list)):
            raise ValueError("Handwrytten returned an unexpected response shape")
        if isinstance(data, dict):
            if data.get("error") or data.get("errors") or data.get("success") is False or str(data.get("status", "")).lower() in {"error", "failed", "failure"} or (isinstance(data.get("httpCode"), int) and data["httpCode"] >= 400):
                message = data.get("error") or data.get("message") or "Handwrytten rejected the request"
                raise ValueError(_redact(str(message)[:2000], token))
        list_operation = op.operation.startswith("list_") or op.operation in {"create_template", "update_template"}
        if list_operation:
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise ValueError("Handwrytten returned an unexpected list response")
        elif not isinstance(data, dict):
            raise ValueError("Handwrytten returned an unexpected object response")
        output = {"status": "success", "operation": op.operation, "data": _redact(data, token)}
        await self.emit(output)
        return output
