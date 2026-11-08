"""EchtPost v2 postcard automation using an account API key.

Contract: https://api.echtpost.de/v2/openapi.json (v2).
Each operation makes one request; list operations return one page and pagination
metadata. Writes are never retried automatically, since card creation spends credit.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.echtpost.de/v2"


class EchtpostAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Echtpost API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://my.echtpost.de",
            "x-credential-instructions": "Paste an EchtPost API key for server-to-server workflow automation. Use a sandbox key while testing; live card creation spends account credit. The key is sent only to api.echtpost.de, in X-Api-Key.",
        })
    credential_type: Literal["echtpost_api_key"] = Field("echtpost_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 for c in value):
            raise ValueError("Paste the API key without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class RecipientInput(_Input):
    first_name: str | None = Field(None)
    last_name: str = Field(...)
    title: str | None = Field(None)
    greeting_style: Literal['informal', 'formal', 'official', 'dear_first_name', 'dear_last_name', 'good_day_first_name', 'good_day_last_name', 'custom'] | None = Field(None)
    custom_salutation: str | None = Field(None)
    gender: str | None = Field(None)
    company_name: str | None = Field(None)
    department: str | None = Field(None)
    street: str = Field(...)
    zip: str = Field(...)
    city: str = Field(...)
    state_code: str | None = Field(None)
    country_code: str = Field(...)
    birthdate: date | None = Field(None)
    external_id: str | None = Field(None)


class Font(_Input):
    family: str | None = Field(None, description='Font slug. Allowed `architects_daughter`, `reenie_beanie`, `special_elite`.')
    size: int | None = Field(None, strict=True, description='Absolute font size. Valid ranges per family — `architects_daughter` 12..14, `reenie_beanie` 15..17, `special_elite` 11..13.')
    color: str | None = Field(None, description='`black`, `blue`, or a hex value.')
    line_height: float | None = Field(None)


class PreviewFitFont(_Input):
    family: str | None = Field(None, description='Font slug. Allowed `architects_daughter`, `reenie_beanie`, `special_elite`.')
    size: int | None = Field(None, strict=True, description='Absolute font size within the valid range for the chosen family.')


class Notification(_Input):
    type: Literal['after_sent', 'before_send'] = Field(..., description='`after_sent` mails `email` once the card is sent. `before_send` mails a reminder on `send_on`.')
    email: str = Field(...)
    send_on: date | None = Field(None, description='`before_send` only. Reminder date, on or before the send date. Defaults to the send date. Ignored for `after_sent`.')


class EchtpostGetAccountConfig(_Input):
    'Current account and API key metadata'
    operation: Literal['get_account'] = Field('get_account', json_schema_extra={"ui:hidden": True})


class EchtpostGetBalanceConfig(_Input):
    'Account balance and pricing'
    operation: Literal['get_balance'] = Field('get_balance', json_schema_extra={"ui:hidden": True})


class EchtpostListContactsConfig(_Input):
    'List contacts'
    operation: Literal['list_contacts'] = Field('list_contacts', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, strict=True)
    per_page: int = Field(100, ge=1, le=200, strict=True)
    country_code: str | None = Field(None)
    group_id: int | None = Field(None, strict=True)
    external_id: str | None = Field(None)
    search: str | None = Field(None)
    first_name: str | None = Field(None)
    last_name: str | None = Field(None)
    company_name: str | None = Field(None)
    street: str | None = Field(None)
    zip: str | None = Field(None)
    city: str | None = Field(None)
    sort: Literal['last_name', 'created_at', 'updated_at'] | None = Field(None)
    direction: Literal['asc', 'desc'] | None = Field(None)
    include: str | None = Field(None)


class EchtpostCreateContactConfig(_Input):
    'Create contact'
    operation: Literal['create_contact'] = Field('create_contact', json_schema_extra={"ui:hidden": True})
    first_name: str | None = Field(None)
    last_name: str = Field(...)
    title: str | None = Field(None)
    greeting_style: Literal['informal', 'formal', 'official', 'dear_first_name', 'dear_last_name', 'good_day_first_name', 'good_day_last_name', 'custom'] | None = Field(None)
    custom_salutation: str | None = Field(None)
    gender: str | None = Field(None)
    company_name: str | None = Field(None)
    department: str | None = Field(None)
    street: str = Field(...)
    zip: str = Field(...)
    city: str = Field(...)
    state_code: str | None = Field(None)
    country_code: str = Field(...)
    birthdate: date | None = Field(None)
    external_id: str | None = Field(None)
    group_ids: list[int] | None = Field(None)
    group_names: list[str] | None = Field(None)


class EchtpostGetContactConfig(_Input):
    'Show contact'
    operation: Literal['get_contact'] = Field('get_contact', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., strict=True)
    include: str | None = Field(None)


class EchtpostUpdateContactConfig(_Input):
    'Update contact'
    operation: Literal['update_contact'] = Field('update_contact', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., strict=True)
    include: str | None = Field(None)
    first_name: str | None = Field(None)
    last_name: str = Field(...)
    title: str | None = Field(None)
    greeting_style: Literal['informal', 'formal', 'official', 'dear_first_name', 'dear_last_name', 'good_day_first_name', 'good_day_last_name', 'custom'] | None = Field(None)
    custom_salutation: str | None = Field(None)
    gender: str | None = Field(None)
    company_name: str | None = Field(None)
    department: str | None = Field(None)
    street: str = Field(...)
    zip: str = Field(...)
    city: str = Field(...)
    state_code: str | None = Field(None)
    country_code: str = Field(...)
    birthdate: date | None = Field(None)
    external_id: str | None = Field(None)


class EchtpostDeleteContactConfig(_Input):
    'Delete contact'
    operation: Literal['delete_contact'] = Field('delete_contact', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., strict=True)
    include: str | None = Field(None)


class EchtpostListGroupsConfig(_Input):
    'List groups'
    operation: Literal['list_groups'] = Field('list_groups', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, strict=True)
    per_page: int = Field(100, ge=1, le=200, strict=True)
    sort: Literal['name', 'created_at', 'updated_at'] | None = Field(None)
    direction: Literal['asc', 'desc'] | None = Field(None)


class EchtpostCreateGroupConfig(_Input):
    'Create group'
    operation: Literal['create_group'] = Field('create_group', json_schema_extra={"ui:hidden": True})
    name: str = Field(...)
    external_id: str | None = Field(None)


class EchtpostGetGroupConfig(_Input):
    'Show group'
    operation: Literal['get_group'] = Field('get_group', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., strict=True)


class EchtpostUpdateGroupConfig(_Input):
    'Update group'
    operation: Literal['update_group'] = Field('update_group', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., strict=True)
    name: str | None = Field(None)
    external_id: str | None = Field(None)


class EchtpostDeleteGroupConfig(_Input):
    'Delete group'
    operation: Literal['delete_group'] = Field('delete_group', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., strict=True)


class EchtpostListTemplatesConfig(_Input):
    'List templates'
    operation: Literal['list_templates'] = Field('list_templates', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, strict=True)
    per_page: int = Field(100, ge=1, le=200, strict=True)


class EchtpostGetTemplateConfig(_Input):
    'Show template'
    operation: Literal['get_template'] = Field('get_template', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., strict=True)


class EchtpostListMotivesConfig(_Input):
    'List available motives'
    operation: Literal['list_motives'] = Field('list_motives', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, strict=True)
    per_page: int = Field(100, ge=1, le=200, strict=True)
    search: str | None = Field(None)
    temporary: Literal['true', 'false'] | None = Field(None)
    sort: Literal['name', 'created_at'] | None = Field(None)
    direction: Literal['asc', 'desc'] | None = Field(None)


class EchtpostGetMotiveConfig(_Input):
    'Show motive'
    operation: Literal['get_motive'] = Field('get_motive', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., strict=True)


class EchtpostListCardsConfig(_Input):
    'List cards'
    operation: Literal['list_cards'] = Field('list_cards', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, strict=True)
    per_page: int = Field(100, ge=1, le=200, strict=True)
    status: str | None = Field(None)
    deliver_at: date | None = Field(None)
    motive_id: int | None = Field(None, strict=True)
    sort: Literal['created_at', 'deliver_at'] | None = Field(None)
    direction: Literal['asc', 'desc'] | None = Field(None)


class EchtpostCreateCardConfig(_Input):
    'Create a card (custom)'
    operation: Literal['create_card'] = Field('create_card', json_schema_extra={"ui:hidden": True})
    motive_id: int = Field(..., strict=True)
    content: str | None = Field(None, description='Card text. Use {anrede} as a per-recipient salutation placeholder (casing ignored). Required when the motive has `content_available: true`; otherwise only blank or omitted text is accepted.')
    content_ps: str | None = Field(None, max_length=40, description='Optional P.S., printed as a single footer line. Non-empty values return 422 `not_available_for_motive` when the motive has `content_ps_available: false`.')
    content_vertical: str | None = Field(None, description="Optional vertical text. Non-empty values return 422 `not_available_for_motive` when the motive has `vertical_text_available: false`. A custom value requires the booked vertical text upgrade for the account, otherwise 422 `feature-not-available`. Your account's own stored vertical text and the EchtPost default are always accepted.")
    deliver_at: str | None = Field(None, description='Delivery date. Accepts: ISO 8601 date (`YYYY-MM-DD`), `today`, `asap` (alias for today), `tomorrow`, or `N-days-from-now` (e.g. `5-days-from-now`). A weekend or printer holiday moves to the next print date (see `move_to_next_print_date`). Must be at most 90 days in the future. Omitting this field schedules the card for the next available business day.')
    move_to_next_print_date: bool | None = Field(None, description="Set to `false` to get 422 `invalid-delivery-date` instead of moving a weekend or printer-holiday `deliver_at`. The response's `deliver_at` shows the date actually scheduled.")
    qr_code_url: str | None = Field(None)
    deduplicate_recipients: bool | None = Field(None)
    recipient_ids: list[int] | None = Field(None)
    group_ids: list[int] | None = Field(None)
    recipients: list[RecipientInput] | None = Field(None)
    font: Font | None = Field(None, description='Optional; defaults to architects_daughter at the middle allowed size. Color defaults to black when omitted.')
    notifications: list[Notification] | None = Field(None)
    simulate: Literal['insufficient_funds'] | None = Field(None, description='Sandbox only. Instead of creating the card, force a simulated error so API clients can test their error handling. `insufficient_funds` returns HTTP 402 with the normal insufficient-funds body. Ignored with a live key.')


class EchtpostCreateCardFromTemplateConfig(_Input):
    'Create a card from a template'
    operation: Literal['create_card_from_template'] = Field('create_card_from_template', json_schema_extra={"ui:hidden": True})
    template_id: int = Field(..., strict=True)
    use_default_vertical_text: bool = Field(False, description="Print the EchtPost default vertical text instead of inheriting the template text. Overrides Content Vertical when enabled.")
    content_vertical: str | None = Field(None, max_length=80, description="Vertical text on the back side for this card. Omit it or pass null to use the template's vertical text; an empty string prints the EchtPost default. A non-empty value returns 422 `not_available_for_motive` when the template's motive has `vertical_text_available: false`. A custom value requires the booked vertical text upgrade for the account, otherwise 422 `feature-not-available`. The template's vertical text follows the same rule; pass an empty string to print the EchtPost default instead.")
    deliver_at: str | None = Field(None, description='Delivery date. Accepts: ISO 8601 date (`YYYY-MM-DD`), `today`, `asap` (alias for today), `tomorrow`, or `N-days-from-now` (e.g. `5-days-from-now`). A weekend or printer holiday moves to the next print date (see `move_to_next_print_date`). Must be at most 90 days in the future. Omitting this field schedules the card for the next available business day.')
    move_to_next_print_date: bool | None = Field(None, description="Set to `false` to get 422 `invalid-delivery-date` instead of moving a weekend or printer-holiday `deliver_at`. The response's `deliver_at` shows the date actually scheduled.")
    recipient_ids: list[int] | None = Field(None)
    group_ids: list[int] | None = Field(None)
    recipients: list[RecipientInput] | None = Field(None)
    simulate: Literal['insufficient_funds'] | None = Field(None, description='Sandbox only. Instead of creating the card, force a simulated error so API clients can test their error handling. `insufficient_funds` returns HTTP 402 with the normal insufficient-funds body. Ignored with a live key.')


class EchtpostPreviewCardFitConfig(_Input):
    'Check whether card content fits at a given font'
    operation: Literal['preview_card_fit'] = Field('preview_card_fit', json_schema_extra={"ui:hidden": True})
    content: str = Field(..., description='Plain text in the same shape as POST /v2/cards content; use JSON line breaks (\\n) between paragraphs.')
    sample_greeting: str | None = Field(None, description='Optional greeting prefix to prepend for fit-check.')
    font: PreviewFitFont | None = Field(None)


class EchtpostGetCardConfig(_Input):
    'Show card'
    operation: Literal['get_card'] = Field('get_card', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(...)


class EchtpostCancelCardConfig(_Input):
    'Cancel card (async)'
    operation: Literal['cancel_card'] = Field('cancel_card', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(...)


EchtpostConfig = Annotated[Union[EchtpostGetAccountConfig, EchtpostGetBalanceConfig, EchtpostListContactsConfig, EchtpostCreateContactConfig, EchtpostGetContactConfig, EchtpostUpdateContactConfig, EchtpostDeleteContactConfig, EchtpostListGroupsConfig, EchtpostCreateGroupConfig, EchtpostGetGroupConfig, EchtpostUpdateGroupConfig, EchtpostDeleteGroupConfig, EchtpostListTemplatesConfig, EchtpostGetTemplateConfig, EchtpostListMotivesConfig, EchtpostGetMotiveConfig, EchtpostListCardsConfig, EchtpostCreateCardConfig, EchtpostCreateCardFromTemplateConfig, EchtpostPreviewCardFitConfig, EchtpostGetCardConfig, EchtpostCancelCardConfig], Field(discriminator="operation")]


class EchtpostFullConfig(NodeConfig[EchtpostConfig, EchtpostAPIKeyCredential]):
    pass


ROUTES = {'get_account': ['GET', '/me'], 'get_balance': ['GET', '/credits'], 'list_contacts': ['GET', '/contacts'], 'create_contact': ['POST', '/contacts'], 'get_contact': ['GET', '/contacts/{id}'], 'update_contact': ['PATCH', '/contacts/{id}'], 'delete_contact': ['DELETE', '/contacts/{id}'], 'list_groups': ['GET', '/groups'], 'create_group': ['POST', '/groups'], 'get_group': ['GET', '/groups/{id}'], 'update_group': ['PATCH', '/groups/{id}'], 'delete_group': ['DELETE', '/groups/{id}'], 'list_templates': ['GET', '/templates'], 'get_template': ['GET', '/templates/{id}'], 'list_motives': ['GET', '/motives'], 'get_motive': ['GET', '/motives/{id}'], 'list_cards': ['GET', '/cards'], 'create_card': ['POST', '/cards'], 'create_card_from_template': ['POST', '/cards/from_template'], 'preview_card_fit': ['POST', '/cards/preview_fit'], 'get_card': ['GET', '/cards/{id}'], 'cancel_card': ['DELETE', '/cards/{id}']}


class EchtpostNode(WorkflowNode):
    integration_type = "automation-echtpost"
    connection_evidence = ConnectionEvidence(noun="Echtpost account", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return EchtpostFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect an Echtpost API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        values.pop("operation")
        if config.operation == "create_card_from_template" and values.pop("use_default_vertical_text", False):
            values["content_vertical"] = ""
        if "{id}" in path:
            path = path.replace("{id}", str(values.pop("id")))
        headers = {"X-Api-Key": self.config.credentials.api_key, "Accept": "application/json"}
        # GET filters are query parameters. PATCH/DELETE include is a query
        # parameter too; all other write fields form the JSON request body.
        params = values if method == "GET" else {}
        if method != "GET" and "include" in values:
            params["include"] = values.pop("include")
        kwargs = {"params": params, "headers": headers}
        if method in {"POST", "PATCH"}:
            kwargs["json"] = values
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + path, **kwargs)
        if not 200 <= response.status_code < 300:
            # Preserve the provider's rejection for the shared connect seam;
            # remove the key if an upstream error ever echoes it.
            try:
                problem = response.json()
                message = problem.get("detail") or problem.get("title")
            except (ValueError, AttributeError):
                message = None
            message = str(message or "Echtpost request failed")[:2000]
            message = message.replace(self.config.credentials.api_key, "[redacted]")
            raise ValueError(f"Echtpost HTTP {response.status_code}: {message}")
        if response.status_code == 204:
            return {"success": True, "deleted": True}
        body = response.json()
        if config.operation.startswith("list_"):
            if not isinstance(body, list):
                raise ValueError("Expected an Echtpost array response")
            total_pages = response.headers.get("X-Total-Pages")
            return {"data": body, "page": config.page,
                "total_count": response.headers.get("X-Total-Count"),
                "total_pages": total_pages,
                "next_page": config.page + 1 if total_pages and config.page < int(total_pages) else None}
        if not isinstance(body, dict):
            raise ValueError("Expected an Echtpost object response")
        return body
