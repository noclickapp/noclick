"""Sympla Public API v1.6.0: producer event, order, participant and check-in operations.

Contract: https://developers.sympla.com.br/api-docs (version 2.0.68).
Pagination is explicit: pass pagination.next_cursor as cursor to read another page.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.sympla.com.br/public"



class SymplaTokenCredential(BaseModel):
    model_config = ConfigDict(title="Sympla API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.sympla.com.br/docs#section/Autenticacao",
            "x-credential-instructions": "In Sympla, open Minha Conta > Integracoes and generate an API token. Paste the token here. NoClick sends it in the s_token header to the Sympla Public API.",
        })
    credential_type: Literal["sympla_api_token"] = Field("sympla_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        token = clean_secret(value, field_name="API token", key=True)
        if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in token):
            raise ValueError("Paste the API token without whitespace or control characters")
        return token


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)



class SymplaQrCode(_Input):
    itemId: str = Field(..., min_length=1)
    signature: str = Field(..., min_length=130, max_length=132)
    timestamp: int = Field(..., strict=True)
    version: float
    walletId: str = Field(..., min_length=1)



class SymplaListEventsConfig(_Input):
    """List events using the Sympla producer API."""
    operation: Literal["list_events"] = Field("list_events", json_schema_extra={"ui:hidden": True})
    published: Literal["published", "not_published", "all", "true", "false"] = Field('published')
    from_date: datetime | None = Field(None, description="ISO-8601 local time in the selected timezone, for example 2025-09-08T00:00:00.")
    timezone: str = Field('America/Sao_Paulo')
    sort: Literal["asc", "desc"] = Field('asc')
    field_sort: str | None = Field(None)
    page_size: int | None = Field(None, strict=True, ge=1, le=200)
    cursor: str | None = Field(None, max_length=8192)
    fields: str | None = Field(None, description="Fields to return. Omit to use provider defaults.")


class SymplaGetEventConfig(_Input):
    """Get event using the Sympla producer API."""
    operation: Literal["get_event"] = Field("get_event", json_schema_extra={"ui:hidden": True})
    event_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")
    timezone: str | None = Field(None)
    fields: str | None = Field(None, description="Fields to return. Omit to use provider defaults.")


class SymplaListOrdersConfig(_Input):
    """List orders using the Sympla producer API."""
    operation: Literal["list_orders"] = Field("list_orders", json_schema_extra={"ui:hidden": True})
    event_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")
    timezone: str | None = Field(None)
    from_date: datetime | None = Field(None, description="ISO-8601 local time in the selected timezone, for example 2025-09-08T00:00:00.")
    to_date: datetime | None = Field(None, description="ISO-8601 local time in the selected timezone, for example 2025-09-08T00:00:00.")
    fields: list[str] | None = Field(None, description="Fields to return. Omit to use provider defaults.")
    cancelled_filter: Literal["none", "include", "only"] | None = Field(None)
    buyer_email: str | None = Field(None)
    page_size: int | None = Field(None, strict=True, ge=1, le=200)
    cursor: str | None = Field(None, max_length=8192)
    field_sort: str | None = Field(None)
    sort: Literal["asc", "desc"] | None = Field(None)


class SymplaGetOrderConfig(_Input):
    """Get order using the Sympla producer API."""
    operation: Literal["get_order"] = Field("get_order", json_schema_extra={"ui:hidden": True})
    event_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")
    order_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")


class SymplaListOrderParticipantsConfig(_Input):
    """List order participants using the Sympla producer API."""
    operation: Literal["list_order_participants"] = Field("list_order_participants", json_schema_extra={"ui:hidden": True})
    event_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")
    order_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")
    fields: list[str] = Field(['ticket_number', 'first_name', 'email'], description="Fields to return for each participant.")
    timezone: str = Field('America/Sao_Paulo')
    cancelled_filter: Literal["none", "include", "only"] | None = Field(None)
    page_size: int | None = Field(None, strict=True, ge=1, le=500)
    cursor: str | None = Field(None, max_length=8192)
    field_sort: str | None = Field(None)
    sort: Literal["asc", "desc"] | None = Field(None)


class SymplaListParticipantsConfig(_Input):
    """List participants using the Sympla producer API."""
    operation: Literal["list_participants"] = Field("list_participants", json_schema_extra={"ui:hidden": True})
    event_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")
    cancelled_filter: Literal["none", "include", "only"] | None = Field(None)
    participant_email: str | None = Field(None)
    timezone: str | None = Field(None)
    from_date: datetime | None = Field(None, description="ISO-8601 local time in the selected timezone, for example 2025-09-08T00:00:00.")
    to_date: datetime | None = Field(None, description="ISO-8601 local time in the selected timezone, for example 2025-09-08T00:00:00.")
    fields: list[str] | None = Field(None, description="Fields to return. Omit to use provider defaults.")
    page_size: int | None = Field(None, strict=True, ge=1, le=500)
    cursor: str | None = Field(None, max_length=8192)
    field_sort: str | None = Field(None)
    sort: Literal["asc", "desc"] | None = Field(None)


class SymplaGetParticipantByTicketConfig(_Input):
    """Get participant by ticket using the Sympla producer API."""
    operation: Literal["get_participant_by_ticket"] = Field("get_participant_by_ticket", json_schema_extra={"ui:hidden": True})
    event_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")
    ticket_number: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")
    timezone: str | None = Field(None)
    fields: str | None = Field(None, description="Fields to return. Omit to use provider defaults.")


class SymplaCheckInByTicketConfig(_Input):
    """Check in by ticket using the Sympla producer API."""
    operation: Literal["check_in_by_ticket"] = Field("check_in_by_ticket", json_schema_extra={"ui:hidden": True})
    event_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")
    ticket_number: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")


class SymplaGetParticipantConfig(_Input):
    """Get participant using the Sympla producer API."""
    operation: Literal["get_participant"] = Field("get_participant", json_schema_extra={"ui:hidden": True})
    event_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")
    participant_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")
    timezone: str | None = Field(None)
    fields: str | None = Field(None, description="Fields to return. Omit to use provider defaults.")


class SymplaCheckInParticipantConfig(_Input):
    """Check in participant using the Sympla producer API."""
    operation: Literal["check_in_participant"] = Field("check_in_participant", json_schema_extra={"ui:hidden": True})
    event_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")
    participant_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")


class SymplaListPresentationsConfig(_Input):
    """List presentations using the Sympla producer API."""
    operation: Literal["list_presentations"] = Field("list_presentations", json_schema_extra={"ui:hidden": True})
    event_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")
    published: bool = Field(True)
    from_date: datetime | None = Field(None, description="ISO-8601 local time in the selected timezone, for example 2025-09-08T00:00:00.")
    timezone: str = Field('America/Sao_Paulo')
    sort: Literal["asc", "desc"] = Field('asc')
    field_sort: str | None = Field(None)
    filter_online_sector: bool | None = Field(None)
    page_size: int | None = Field(None, strict=True, ge=1, le=200)
    cursor: str | None = Field(None, max_length=8192)
    fields: str | None = Field(None, description="Fields to return. Omit to use provider defaults.")


class SymplaGetPresentationConfig(_Input):
    """Get presentation using the Sympla producer API."""
    operation: Literal["get_presentation"] = Field("get_presentation", json_schema_extra={"ui:hidden": True})
    event_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")
    presentation_id: int = Field(..., strict=True)
    timezone: str | None = Field(None)
    fields: str | None = Field(None, description="Fields to return. Omit to use provider defaults.")


class SymplaListPresentationOrdersConfig(_Input):
    """List presentation orders using the Sympla producer API."""
    operation: Literal["list_presentation_orders"] = Field("list_presentation_orders", json_schema_extra={"ui:hidden": True})
    event_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")
    presentation_id: int = Field(..., strict=True)
    cancelled_filter: Literal["none", "include", "only"] | None = Field(None)
    buyer_email: str | None = Field(None)
    timezone: str | None = Field(None)
    from_date: datetime | None = Field(None, description="ISO-8601 local time in the selected timezone, for example 2025-09-08T00:00:00.")
    to_date: datetime | None = Field(None, description="ISO-8601 local time in the selected timezone, for example 2025-09-08T00:00:00.")
    fields: list[str] | None = Field(None, description="Fields to return. Omit to use provider defaults.")
    page_size: int | None = Field(None, strict=True, ge=1, le=200)
    cursor: str | None = Field(None, max_length=8192)
    field_sort: str | None = Field(None)
    sort: Literal["asc", "desc"] | None = Field(None)


class SymplaListPresentationParticipantsConfig(_Input):
    """List presentation participants using the Sympla producer API."""
    operation: Literal["list_presentation_participants"] = Field("list_presentation_participants", json_schema_extra={"ui:hidden": True})
    event_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")
    presentation_id: int = Field(..., strict=True)
    cancelled_filter: Literal["none", "include", "only"] | None = Field(None)
    participant_email: str | None = Field(None)
    timezone: str | None = Field(None)
    from_date: datetime | None = Field(None, description="ISO-8601 local time in the selected timezone, for example 2025-09-08T00:00:00.")
    to_date: datetime | None = Field(None, description="ISO-8601 local time in the selected timezone, for example 2025-09-08T00:00:00.")
    fields: list[str] | None = Field(None, description="Fields to return. Omit to use provider defaults.")
    page_size: int | None = Field(None, strict=True, ge=1, le=500)
    cursor: str | None = Field(None, max_length=8192)
    field_sort: str | None = Field(None)
    sort: Literal["asc", "desc"] | None = Field(None)


class SymplaCheckInQrCodeConfig(_Input):
    """Check in qr code using the Sympla producer API."""
    operation: Literal["check_in_qr_code"] = Field("check_in_qr_code", json_schema_extra={"ui:hidden": True})
    event_id: str = Field(..., min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_-]+$")
    qr_code: SymplaQrCode = Field(..., description="The signed QR payload from the ticket; preserve its values.")


SymplaConfig = Annotated[Union[
    SymplaListEventsConfig,
    SymplaGetEventConfig,
    SymplaListOrdersConfig,
    SymplaGetOrderConfig,
    SymplaListOrderParticipantsConfig,
    SymplaListParticipantsConfig,
    SymplaGetParticipantByTicketConfig,
    SymplaCheckInByTicketConfig,
    SymplaGetParticipantConfig,
    SymplaCheckInParticipantConfig,
    SymplaListPresentationsConfig,
    SymplaGetPresentationConfig,
    SymplaListPresentationOrdersConfig,
    SymplaListPresentationParticipantsConfig,
    SymplaCheckInQrCodeConfig
], Field(discriminator="operation")]



class SymplaFullConfig(NodeConfig[SymplaConfig, SymplaTokenCredential]):
    pass


# One operation maps to one published contract endpoint.
ROUTES = {'list_events': ('GET',
                 '/v1.6.0/events',
                 {},
                 {'published': 'published',
                  'from_date': 'from',
                  'timezone': 'timezone',
                  'sort': 'sort',
                  'field_sort': 'field_sort',
                  'page_size': 'page_size',
                  'cursor': 'cursor',
                  'fields': 'fields'}),
 'get_event': ('GET',
               '/v1.6.0/events/{eventIdHash}',
               {'eventIdHash': 'event_id'},
               {'timezone': 'timezone', 'fields': 'fields'}),
 'list_orders': ('GET',
                 '/v1.6.0/events/{eventIdHash}/orders',
                 {'eventIdHash': 'event_id'},
                 {'timezone': 'timezone',
                  'from_date': 'from',
                  'to_date': 'to',
                  'fields': 'fields',
                  'cancelled_filter': 'cancelled_filter',
                  'buyer_email': 'buyer_email',
                  'page_size': 'page_size',
                  'cursor': 'cursor',
                  'field_sort': 'field_sort',
                  'sort': 'sort'}),
 'get_order': ('GET',
               '/v1.6.0/events/{eventIdHash}/orders/{orderSk}',
               {'eventIdHash': 'event_id', 'orderSk': 'order_id'},
               {}),
 'list_order_participants': ('GET',
                             '/v1.6.0/events/{eventIdHash}/orders/{orderSk}/participants',
                             {'eventIdHash': 'event_id', 'orderSk': 'order_id'},
                             {'fields': 'fields',
                              'timezone': 'timezone',
                              'cancelled_filter': 'cancelled_filter',
                              'page_size': 'page_size',
                              'cursor': 'cursor',
                              'field_sort': 'field_sort',
                              'sort': 'sort'}),
 'list_participants': ('GET',
                       '/v1.6.0/events/{eventIdHash}/participants',
                       {'eventIdHash': 'event_id'},
                       {'cancelled_filter': 'cancelled_filter',
                        'participant_email': 'participant_email',
                        'timezone': 'timezone',
                        'from_date': 'from',
                        'to_date': 'to',
                        'fields': 'fields',
                        'page_size': 'page_size',
                        'cursor': 'cursor',
                        'field_sort': 'field_sort',
                        'sort': 'sort'}),
 'get_participant_by_ticket': ('GET',
                               '/v1.6.0/events/{eventIdHash}/participants/ticketNumber/{ticketNumber}',
                               {'eventIdHash': 'event_id', 'ticketNumber': 'ticket_number'},
                               {'timezone': 'timezone', 'fields': 'fields'}),
 'check_in_by_ticket': ('POST',
                        '/v1.6.0/events/{eventIdHash}/participants/ticketNumber/{ticketNumber}/check-in',
                        {'eventIdHash': 'event_id', 'ticketNumber': 'ticket_number'},
                        {}),
 'get_participant': ('GET',
                     '/v1.6.0/events/{eventIdHash}/participants/{participantId}',
                     {'eventIdHash': 'event_id', 'participantId': 'participant_id'},
                     {'timezone': 'timezone', 'fields': 'fields'}),
 'check_in_participant': ('POST',
                          '/v1.6.0/events/{eventIdHash}/participants/{participantId}/check-in',
                          {'eventIdHash': 'event_id', 'participantId': 'participant_id'},
                          {}),
 'list_presentations': ('GET',
                        '/v1.6.0/events/{eventIdHash}/presentations',
                        {'eventIdHash': 'event_id'},
                        {'published': 'published',
                         'from_date': 'from',
                         'timezone': 'timezone',
                         'sort': 'sort',
                         'field_sort': 'field_sort',
                         'filter_online_sector': 'filter_online_sector',
                         'page_size': 'page_size',
                         'cursor': 'cursor',
                         'fields': 'fields'}),
 'get_presentation': ('GET',
                      '/v1.6.0/events/{eventIdHash}/presentations/{presentationId}',
                      {'eventIdHash': 'event_id', 'presentationId': 'presentation_id'},
                      {'timezone': 'timezone', 'fields': 'fields'}),
 'list_presentation_orders': ('GET',
                              '/v1.6.0/events/{eventIdHash}/presentations/{presentationId}/orders',
                              {'eventIdHash': 'event_id', 'presentationId': 'presentation_id'},
                              {'cancelled_filter': 'cancelled_filter',
                               'buyer_email': 'buyer_email',
                               'timezone': 'timezone',
                               'from_date': 'from',
                               'to_date': 'to',
                               'fields': 'fields',
                               'page_size': 'page_size',
                               'cursor': 'cursor',
                               'field_sort': 'field_sort',
                               'sort': 'sort'}),
 'list_presentation_participants': ('GET',
                                    '/v1.6.0/events/{eventIdHash}/presentations/{presentationId}/participants',
                                    {'eventIdHash': 'event_id',
                                     'presentationId': 'presentation_id'},
                                    {'cancelled_filter': 'cancelled_filter',
                                     'participant_email': 'participant_email',
                                     'timezone': 'timezone',
                                     'from_date': 'from',
                                     'to_date': 'to',
                                     'fields': 'fields',
                                     'page_size': 'page_size',
                                     'cursor': 'cursor',
                                     'field_sort': 'field_sort',
                                     'sort': 'sort'}),
 'check_in_qr_code': ('POST',
                      '/v1.6.0/events/{eventIdHash}/qrcode/check-in',
                      {'eventIdHash': 'event_id'},
                      {})}



class SymplaNode(WorkflowNode):
    integration_type = "automation-sympla"
    connection_evidence = ConnectionEvidence(noun="events", operation="list_events")

    @classmethod
    def get_config_model(cls):
        return SymplaFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Sympla API token")
        config = self.config.config
        method, path, path_fields, query_fields = ROUTES[config.operation]
        for wire, name in path_fields.items():
            path = path.replace("{" + wire + "}", quote(str(getattr(config, name)), safe=""))
        params = []
        for name, wire in query_fields.items():
            value = getattr(config, name)
            if value is None:
                continue
            for item in value if isinstance(value, list) else [value]:
                params.append((wire, str(item).lower() if isinstance(item, bool) else item.isoformat() if isinstance(item, datetime) else str(item)))
        kwargs = {"params": params, "headers": {"s_token": self.config.credentials.api_token, "Accept": "application/json"}}
        if config.operation == "check_in_qr_code":
            kwargs["json"] = config.qr_code.model_dump()
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, **kwargs)
        response.raise_for_status()
        if response.status_code == 204:
            return {"status": "success", "data": None, "http_status": 204}
        body = response.json()
        if isinstance(body, dict) and ("error" in body or "errors" in body):
            raise ValueError("Sympla returned an error envelope")
        if config.operation in {"get_event", "get_presentation"}:
            if not isinstance(body, dict):
                raise ValueError("Sympla detail response must be an object")
            return {"status": "success", "data": body}
        if not isinstance(body, dict) or "data" not in body:
            raise ValueError("Sympla response is missing its data envelope")
        data = body["data"]
        if config.operation.startswith("list_") and not isinstance(data, list):
            raise ValueError("Sympla list response must contain a data array")
        if not config.operation.startswith("list_") and not isinstance(data, dict):
            raise ValueError("Sympla detail response must contain a data object")
        return {**body, "status": "success"}
