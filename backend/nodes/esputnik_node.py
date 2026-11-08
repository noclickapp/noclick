"""Native eSputnik/Yespo account, contact schema and reporting reads.

Only closed GET routes are available. Contact cards never stand in for
system suppression or consent.
"""
from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union

import httpx
from opentelemetry.instrumentation.utils import suppress_http_instrumentation
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_serializer, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.esputnik import ESPUTNIK_SCOPES

TYPE = "esputnik_api_key"
API = "https://esputnik.com/api/v1"
MAX_BODY = 4 * 1024 * 1024
UNVERIFIED = "eSputnik response could not be verified"


def secret(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 1024 or any(c.isspace() or ord(c) < 33 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value) or value.lower().startswith(("http:", "https:", "basic ", "bearer ")):
        raise ValueError("Paste the issued eSputnik API key without a URL or authentication prefix")
    return value


def validate_username(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or any(c == ":" or ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValueError("Enter a nonempty Basic username without a colon or control characters")
    return value


def clean_text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 512 or any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValueError("Enter nonempty text without control characters, at most 512 characters")
    return value


def path_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Enter the exact broadcast ID, without a URL, slash or query")
    return value


PositiveID = Annotated[StrictInt, Field(ge=1, le=9007199254740991)]
PageStart = Annotated[StrictInt, Field(ge=1, le=1000000)]
PageSize = Annotated[StrictInt, Field(ge=1, le=500)]
SearchText = Annotated[StrictStr, BeforeValidator(clean_text), Field(min_length=1, max_length=512)]
BroadcastID = Annotated[StrictStr, BeforeValidator(path_id), Field(min_length=1, max_length=128)]


class ESputnikAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Yespo API Key", extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-type": "api_key",
        "x-credential-help-url": "https://docs.esputnik.com/reference/getting-started-with-your-api",
        "x-credential-instructions": "Use an existing eSputnik/Yespo API key as the HTTP Basic password. Any username is accepted by the provider; the default is noclick. This is not your account password or an event Bearer token. Connection reads account/info and shows the returned organization name and user email; it does not prove contact/broadcast permissions, entitlement or subscription status.",
    })
    credential_type: Literal["esputnik_api_key"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    api_key: Annotated[StrictStr, BeforeValidator(secret)] = Field(..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"})
    username: Annotated[StrictStr, BeforeValidator(validate_username)] = Field("noclick", title="Basic Username", description="The provider accepts any value. This value is sent as the Basic username; the API key is its password.")
    expected_organisation_name: Optional[SearchText] = Field(None, title="Expected Organization Name", description="Optional exact name to match against account/info during connection and account reads. No organization ID is required.")

    @model_serializer(mode="wrap")
    def connect_tag(self, handler):
        # New manual forms omit hidden defaults; preserve the literal in shaped data.
        return {**handler(self), "credential_type": TYPE}


def credential(raw):
    if not isinstance(raw, dict) or raw.get("credential_type") != TYPE:
        raise ValueError("eSputnik requires its original API key credential type")
    try:
        return ESputnikAPIKeyCredential.model_validate(raw)
    except Exception:
        raise ValueError("eSputnik credential fields are invalid") from None


def raw_guard(data):
    if isinstance(data, dict) and data.get("credentials") is not None:
        raw = data["credentials"]
        if not isinstance(raw, dict) or raw.get("credential_type") != TYPE:
            raise ValueError("eSputnik credential type is not supported")


def op(value, title, description):
    return Field(value, title=title, description=description, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "Audience Reporting", "x-is-trigger": False, "x-keywords": ["Yespo", "eSputnik", "contacts", "broadcasts", "reporting"]})


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetAccountInfo(Config):
    operation: Literal["get_account_info"] = op("get_account_info", "Get Account Info", "Read the protected userEmail and organisationName witness. An orgId is included only if returned; this does not prove access to other operations.")


class GetAdditionalFields(Config):
    operation: Literal["get_additional_fields"] = op("get_additional_fields", "Get Contact Field Schema", "Read the documented additionalFieldsLists structure, including field keys, types, allowed values and validation metadata. No contact values are fetched.")


class ContactProjection(Config):
    include_personal_data: StrictBool = Field(False, title="Include Contact Details", description="Include names and email/SMS/Viber channel values. These are personal data; push tokens, device data, addresses and URLs are never returned.")
    include_additional_values: StrictBool = Field(False, title="Include Additional Field Values", description="Include documented field ID/string-value pairs. Custom field values can contain sensitive information.")


class SearchContacts(ContactProjection):
    operation: Literal["search_contacts"] = op("search_contacts", "Search Contacts", "Read one page from GET /contacts. At least one documented search condition is required locally; this operation does not perform a bulk contact export or establish suppression status.")
    external_customer_id: Optional[SearchText] = Field(None, title="External Customer ID")
    email: Optional[SearchText] = Field(None, title="Email")
    sms: Optional[SearchText] = Field(None, title="Phone Number")
    first_name: Optional[SearchText] = Field(None, title="First Name")
    last_name: Optional[SearchText] = Field(None, title="Last Name")
    start_index: PageStart = Field(1, title="Start Index", description="Provider numbering starts at 1. Local maximum is 1,000,000; pages are not a consistent snapshot.")
    max_rows: PageSize = Field(100, title="Maximum Rows", description="One page of 1–500 contact cards. No automatic page traversal.")

    @model_validator(mode="after")
    def search_condition(self):
        if not any(getattr(self, name) is not None for name in ("external_customer_id", "email", "sms", "first_name", "last_name")):
            raise ValueError("Supply at least one contact search condition")
        return self


class GetContact(ContactProjection):
    operation: Literal["get_contact"] = op("get_contact", "Get Contact", "Read an exact contact ID under the current API key. The card does not return global blacklist or full email subscription status.")
    contact_id: PositiveID = Field(..., title="Contact ID", description="Exact provider contact ID. Enter a known ID or copy it from Search Contacts; no invented segment or account ancestry is asserted.")


class ListBroadcasts(Config):
    operation: Literal["list_broadcasts"] = op("list_broadcasts", "List Broadcasts", "Read broadcast metadata, without fetching message content or changing delivery. Full pages indicate only that another page may exist.")
    start_index: PageStart = Field(1, title="Start Index", description="Provider numbering starts at 1. Local maximum is 1,000,000; incoming or changed broadcasts can shift pages.")
    max_rows: PageSize = Field(10, title="Maximum Rows", description="One page of 1–500 broadcasts. No automatic page traversal.")


class GetBroadcast(Config):
    operation: Literal["get_broadcast"] = op("get_broadcast", "Get Broadcast", "Read one exact broadcast metadata record. This does not fetch its message, recipients, content or delivery report.")
    broadcast_id: BroadcastID = Field(..., title="Broadcast ID", description="Exact string ID from List Broadcasts. Custom entry only; no unsupported picker or ancestry endpoint is invoked.")


OPERATIONS = (GetAccountInfo, GetAdditionalFields, SearchContacts, GetContact, ListBroadcasts, GetBroadcast)
ESputnikConfig = Annotated[Union[GetAccountInfo, GetAdditionalFields, SearchContacts, GetContact, ListBroadcasts, GetBroadcast], Field(discriminator="operation")]


class ESputnikNodeConfig(NodeConfig[ESputnikConfig, ESputnikAPIKeyCredential]):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    node_type: Literal["automation-esputnik"] = "automation-esputnik"


_PRIVATE = ContextVar("esputnik_private_transport", default=False)


class _PrivateFilter(logging.Filter):
    def filter(self, record):
        if _PRIVATE.get():
            record.msg, record.args = "eSputnik transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_FILTER = _PrivateFilter()


class ApiError(ValueError):
    def __init__(self, status):
        self.status_code = status
        super().__init__(f"eSputnik returned HTTP {status}; inspect the current API key, resource access and provider limits")


class OutcomeUnverified(RuntimeError):
    pass


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


async def request(auth, route, parameters=None):
    """Closed native GET routes; no arbitrary URLs, redirects or retries."""
    if route not in {"account/info", "additionalfields", "contacts", "broadcasts"} and not re.fullmatch(r"contact/[1-9][0-9]{0,15}|broadcast/[A-Za-z0-9_-]{1,128}", route):
        raise ValueError("Unsupported eSputnik route")
    names = {"httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"}
    names |= {name for name in logging.Logger.manager.loggerDict if name.startswith(("httpx.", "httpcore."))}
    for name in names:
        logging.getLogger(name).addFilter(_FILTER)
    private = _PRIVATE.set(True)
    try:
        with suppress_http_instrumentation():
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                async with client.stream("GET", API + "/" + route, params=parameters, auth=httpx.BasicAuth(auth.username, auth.api_key), headers={"Accept": "application/json"}) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_BODY:
                            raise OutcomeUnverified("eSputnik response exceeds the local 4 MiB bound; use a smaller page")
                    if response.status_code != 200:
                        raise ApiError(response.status_code)
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise OutcomeUnverified(UNVERIFIED)
                    try:
                        data = json.loads(raw, object_pairs_hook=strict_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    except (ValueError, UnicodeError, RecursionError):
                        raise OutcomeUnverified(UNVERIFIED) from None
                    return data, response.headers.get("TotalCount")
    except httpx.RequestError:
        raise OutcomeUnverified("eSputnik transport outcome is unverified") from None
    finally:
        _PRIVATE.reset(private)


class Response(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, strict=True)


def response_text(value):
    if not isinstance(value, str) or len(value) > 65536 or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValueError("Invalid response text")
    return value


def response_date(value):
    value = response_text(value)
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


ResponseText = Annotated[StrictStr, BeforeValidator(response_text), Field(max_length=65536)]
ResponseDate = Annotated[StrictStr, BeforeValidator(response_date), Field(max_length=64)]


class AccountInfo(Response):
    userEmail: SearchText
    organisationName: SearchText
    orgId: Optional[PositiveID] = None


class AllowedValues(Response):
    possibleValues: Optional[list[ResponseText]] = None
    minValue: Optional[StrictInt] = None
    maxValue: Optional[StrictInt] = None


class FieldDescription(Response):
    type: Optional[Literal["textfield", "combobox", "checkboxlist", "textarea", "date", "number", "datetime", "decimal", "tags"]] = None
    allowedValues: Optional[AllowedValues] = None
    required: Optional[StrictBool] = None
    readonly: Optional[StrictBool] = None


class AdditionalField(Response):
    id: PositiveID
    name: Optional[ResponseText] = None
    fieldKey: Optional[ResponseText] = None
    description: Optional[FieldDescription] = None


class FieldsList(Response):
    name: Optional[ResponseText] = None
    personalisationKey: Optional[ResponseText] = None
    additionalFields: list[AdditionalField]


class AdditionalFields(Response):
    additionalFieldsLists: list[FieldsList]


class ContactField(Response):
    id: PositiveID
    value: ResponseText


class ContactChannel(Response):
    type: ResponseText
    value: Optional[ResponseText] = None


class ContactGroup(Response):
    id: PositiveID
    name: Optional[ResponseText] = None
    type: Optional[ResponseText] = None


class ContactCard(Response):
    id: PositiveID
    addressBookId: Optional[PositiveID] = None
    firstName: Optional[ResponseText] = None
    lastName: Optional[ResponseText] = None
    channels: Optional[list[ContactChannel]] = None
    fields: Optional[list[ContactField]] = None
    externalCustomerId: Optional[ResponseText] = None
    languageCode: Optional[ResponseText] = None
    timeZone: Optional[ResponseText] = None
    marketId: Optional[ResponseText] = None
    groups: Optional[list[ContactGroup]] = None


class Broadcast(Response):
    broadcastId: BroadcastID
    title: Optional[ResponseText] = None
    messageId: Optional[ResponseText] = None
    groupId: Optional[ResponseText] = None
    startDate: Optional[ResponseDate] = None
    batchSize: Optional[Annotated[StrictInt, Field(ge=0, le=2147483647)]] = None
    batchIntervalUnit: Optional[Literal["MINUTE", "HOUR", "DAY", "MONTH"]] = None


def project(model, data):
    try:
        return model.model_validate(data).model_dump(exclude_unset=True)
    except Exception:
        raise OutcomeUnverified(UNVERIFIED) from None


def contact_card(raw, cfg, *, search=False):
    card = project(ContactCard, raw)
    # Search returns BaseContact, not all the single-contact fields.
    if search:
        card = {key: value for key, value in card.items() if key in {"id", "addressBookId", "firstName", "lastName", "channels", "fields"}}
    if not cfg.include_personal_data:
        for key in ("firstName", "lastName", "channels", "externalCustomerId"):
            card.pop(key, None)
    elif card.get("channels") is not None:
        card["channels"] = [channel for channel in card["channels"] if channel["type"] in ("email", "sms", "viber")]
    if not cfg.include_additional_values:
        card.pop("fields", None)
    return card


def page(data, cfg, *, total_header=None):
    if not isinstance(data, list) or len(data) > cfg.max_rows:
        raise OutcomeUnverified(UNVERIFIED)
    total = None
    if total_header is not None:
        if not re.fullmatch(r"[0-9]{1,16}", total_header) or int(total_header) > 9007199254740991:
            raise OutcomeUnverified("eSputnik TotalCount header could not be verified")
        total = int(total_header)
        if total < len(data):
            raise OutcomeUnverified("eSputnik TotalCount header contradicts this page")
    full = len(data) == cfg.max_rows
    next_index = cfg.start_index + len(data)
    more = (next_index <= total) if total is not None else None
    candidate = next_index if (more is True or (more is None and full)) and next_index <= 1000000 else None
    return {"start_index": cfg.start_index, "max_rows": cfg.max_rows, "returned": len(data), "total_count": total, "full_page": full, "more_results": more, "next_start_index_candidate": candidate, "local_index_bound_reached": candidate is None and (more is True or (more is None and full)), "snapshot_consistent": False}


async def operate(auth, cfg):
    if isinstance(cfg, GetAccountInfo):
        raw, _ = await request(auth, "account/info")
        account = project(AccountInfo, raw)
        expected = auth.expected_organisation_name
        if expected is not None and account["organisationName"] != expected:
            raise OutcomeUnverified("eSputnik returned a different organization than the expected witness")
        return account
    if isinstance(cfg, GetAdditionalFields):
        raw, _ = await request(auth, "additionalfields")
        return project(AdditionalFields, raw)
    if isinstance(cfg, SearchContacts):
        parameters = {"startindex": cfg.start_index, "maxrows": cfg.max_rows}
        for source, target in (("external_customer_id", "externalCustomerId"), ("email", "email"), ("sms", "sms"), ("first_name", "firstname"), ("last_name", "lastname")):
            if getattr(cfg, source) is not None:
                parameters[target] = getattr(cfg, source)
        raw, total = await request(auth, "contacts", parameters)
        pagination = page(raw, cfg, total_header=total)
        records = [contact_card(item, cfg, search=True) for item in raw]
        if len({item["id"] for item in records}) != len(records):
            raise OutcomeUnverified("eSputnik returned duplicate contact IDs in one page")
        return {"contacts": records, "pagination": pagination, "suppression_status": "not_provided"}
    if isinstance(cfg, GetContact):
        raw, _ = await request(auth, f"contact/{cfg.contact_id}")
        card = contact_card(raw, cfg)
        if card["id"] != cfg.contact_id:
            raise OutcomeUnverified("eSputnik returned a different contact ID")
        return {"contact": card, "suppression_status": "not_provided"}
    if isinstance(cfg, ListBroadcasts):
        raw, _ = await request(auth, "broadcasts", {"startindex": cfg.start_index, "maxrows": cfg.max_rows})
        pagination = page(raw, cfg)
        records = [project(Broadcast, item) for item in raw]
        if len({item["broadcastId"] for item in records}) != len(records):
            raise OutcomeUnverified("eSputnik returned duplicate broadcast IDs in one page")
        return {"broadcasts": records, "pagination": pagination}
    if isinstance(cfg, GetBroadcast):
        raw, _ = await request(auth, "broadcast/" + cfg.broadcast_id)
        record = project(Broadcast, raw)
        if record["broadcastId"] != cfg.broadcast_id:
            raise OutcomeUnverified("eSputnik returned a different broadcast ID")
        return record
    raise ValueError("Unsupported eSputnik operation")


class ESputnikNode(WorkflowNode):
    integration_type = "automation-esputnik"
    scope_registry = ESPUTNIK_SCOPES
    connection_evidence = ConnectionEvidence(identity_operation="get_account_info", noun="eSputnik account", identity_keys=("organisationName", "userEmail"), proves="account")

    @classmethod
    def get_config_model(cls):
        return ESputnikNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw_guard(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        if isinstance(config_data, dict):
            try:
                raw_guard(config_data)
            except ValueError as error:
                return {"valid": False, "errors": [str(error)], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    async def validate_credential_access(cls, raw):
        try:
            await operate(credential(raw), GetAccountInfo())
            return True, None
        except ApiError as error:
            return (False, str(error)) if error.status_code in (401, 403) else (None, str(error))
        except Exception:
            return None, UNVERIFIED

    async def execute(self, inputs):
        raw_guard(self.node_data)
        if not isinstance(self.config, ESputnikNodeConfig) or self.config.credentials is None:
            raise ValueError("eSputnik API key credentials are required")
        auth = self.config.credentials
        data = await operate(auth, self.config.config)
        return {"status": "success", "operation": self.config.config.operation, "data": data}
