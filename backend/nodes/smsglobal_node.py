"""SMSGlobal REST v2: fixed routes, MAC authentication and scheduled message polls.

Contract: https://www.smsglobal.com/openapi.json (2.0.0).
MAC algorithm: https://www.smsglobal.com/rest-api/#authentication.
Post-backs have no standalone registration API; polls use the documented lists.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE = "https://api.smsglobal.com"
CREDENTIAL_TYPE = "smsglobal_api_key"


class SMSGlobalCredential(BaseModel):
    model_config = ConfigDict(title="SMSGlobal API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://mxt.smsglobal.com/integrations",
            "x-credential-instructions": "In your SMSGlobal MXT account, create a REST API key and secret. Paste both values here. NoClick signs requests with MAC SHA-256; these are not your MXT login details.",
        })
    credential_type: Literal["smsglobal_api_key"] = Field("smsglobal_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=512, title="API key", json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., min_length=1, max_length=512, title="API secret", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "api_secret", mode="before")
    @classmethod
    def secret(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if not re.fullmatch(r"[A-Za-z0-9_./+=-]+", value):
            raise ValueError("Paste the REST API value without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def date_format(cls, value, info):
        if info.field_name in {"start_date", "end_date", "scheduled_date_time", "expiry_date_time"} and value is not None:
            datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return value


class _Page(_Input):
    offset: int = Field(1, ge=1, le=9999, description="Pagination offset; SMSGlobal defaults to 1.")
    limit: int = Field(20, ge=1, le=1000)

    @model_validator(mode="after")
    def page_bound(self):
        if self.offset + self.limit > 10000:
            raise ValueError("Offset plus limit must not exceed 10000")
        return self


class _MessageFilters(_Page):
    start_date: str | None = Field(None, description="YYYY-MM-DD HH:MM:SS in the account timezone.")
    end_date: str | None = Field(None, description="YYYY-MM-DD HH:MM:SS in the account timezone.")
    destination: int | None = Field(None, ge=1)
    search: str | None = Field(None, max_length=1000)


class _ContactFields(_Input):
    given_name: str | None = Field(None, max_length=255)
    family_name: str | None = Field(None, max_length=255)
    display_name: str | None = Field(None, max_length=255)
    msisdn: str = Field(..., min_length=3, max_length=15, description="Mobile number in international format, digits only.")
    email_address: str | None = Field(None, max_length=320)


class _GroupFields(_Input):
    name: str = Field(..., min_length=1, max_length=100)
    keyword: str | None = Field(None, max_length=100)
    is_global: bool | None = None
    default_origin: str | None = Field(None, max_length=15)


class SMSGlobalSendSmsConfig(_Input):
    operation: Literal["send_sms"] = Field("send_sms", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Send Sms', 'x-category': 'Messages'})
    destination: str = Field(..., min_length=3, max_length=15, description="International mobile number, digits only.")
    message: str = Field(..., min_length=1, max_length=10000)
    origin: str | None = Field(None, min_length=3, max_length=15)
    shared_pool: str | None = None
    scheduled_date_time: str | None = Field(None, description="YYYY-MM-DD HH:MM:SS in UTC.")
    expiry_date_time: str | None = Field(None, description="YYYY-MM-DD HH:MM:SS in UTC.")
    campaign: str | None = None

    @model_validator(mode="after")
    def sender(self):
        if self.origin is not None and self.shared_pool is not None:
            raise ValueError("Choose either origin or shared pool")
        return self


class SMSGlobalListOutgoingMessagesConfig(_MessageFilters):
    operation: Literal["list_outgoing_messages"] = Field("list_outgoing_messages", json_schema_extra={'ui:hidden': True, 'x-display-name': 'List Outgoing Messages', 'x-category': 'Messages'})
    status: Literal["delivered", "sent", "scheduled", "noCredits", "invalidNumber", "undelivered"] | None = None
    source: int | None = Field(None, ge=1)


class SMSGlobalGetOutgoingMessageConfig(_Input):
    operation: Literal["get_outgoing_message"] = Field("get_outgoing_message", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Get Outgoing Message', 'x-category': 'Messages'})
    message_id: int = Field(..., ge=1)


class SMSGlobalDeleteScheduledMessageConfig(_Input):
    operation: Literal["delete_scheduled_message"] = Field("delete_scheduled_message", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Delete Scheduled Message', 'x-category': 'Messages'})
    message_id: int = Field(..., ge=1)


class SMSGlobalListIncomingMessagesConfig(_MessageFilters):
    operation: Literal["list_incoming_messages"] = Field("list_incoming_messages", json_schema_extra={'ui:hidden': True, 'x-display-name': 'List Incoming Messages', 'x-category': 'Messages'})
    origin: int | None = Field(None, ge=1)


class SMSGlobalGetIncomingMessageConfig(_Input):
    operation: Literal["get_incoming_message"] = Field("get_incoming_message", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Get Incoming Message', 'x-category': 'Messages'})
    message_id: int = Field(..., ge=1)


class SMSGlobalListGroupsConfig(_Page):
    operation: Literal["list_groups"] = Field("list_groups", json_schema_extra={'ui:hidden': True, 'x-display-name': 'List Groups', 'x-category': 'Groups'})


class SMSGlobalGetGroupConfig(_Input):
    operation: Literal["get_group"] = Field("get_group", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Get Group', 'x-category': 'Groups'})
    group_id: int = Field(..., ge=1)


class SMSGlobalCreateGroupConfig(_GroupFields):
    operation: Literal["create_group"] = Field("create_group", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Create Group', 'x-category': 'Groups'})


class SMSGlobalUpdateGroupConfig(_GroupFields):
    operation: Literal["update_group"] = Field("update_group", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Update Group', 'x-category': 'Groups'})
    group_id: int = Field(..., ge=1)


class SMSGlobalDeleteGroupConfig(_Input):
    operation: Literal["delete_group"] = Field("delete_group", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Delete Group', 'x-category': 'Groups'})
    group_id: int = Field(..., ge=1)


class SMSGlobalListContactsConfig(_Page):
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={'ui:hidden': True, 'x-display-name': 'List Contacts', 'x-category': 'Contacts'})
    group_id: int = Field(..., ge=1)
    sort: Literal["id", "-id", "msisdn", "-msisdn"] | None = None


class SMSGlobalGetContactConfig(_Input):
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Get Contact', 'x-category': 'Contacts'})
    contact_id: int = Field(..., ge=1)


class SMSGlobalCreateContactConfig(_ContactFields):
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Create Contact', 'x-category': 'Contacts'})
    group_id: int = Field(..., ge=1)


class SMSGlobalUpdateContactConfig(_ContactFields):
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Update Contact', 'x-category': 'Contacts'})
    contact_id: int = Field(..., ge=1)


class SMSGlobalDeleteContactConfig(_Input):
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Delete Contact', 'x-category': 'Contacts'})
    contact_id: int = Field(..., ge=1)


class SMSGlobalListOptOutsConfig(_Page):
    operation: Literal["list_opt_outs"] = Field("list_opt_outs", json_schema_extra={'ui:hidden': True, 'x-display-name': 'List Opt Outs', 'x-category': 'Opt Outs'})
    phone_number: int | None = Field(None, ge=1)


class SMSGlobalOptOutNumbersConfig(_Input):
    operation: Literal["opt_out_numbers"] = Field("opt_out_numbers", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Opt Out Numbers', 'x-category': 'Opt Outs'})
    optouts: list[str] = Field(..., min_length=1, max_length=1000, description="International mobile numbers to opt out.")


class SMSGlobalValidateOptOutsConfig(_Input):
    operation: Literal["validate_opt_outs"] = Field("validate_opt_outs", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Validate Opt Outs', 'x-category': 'Opt Outs'})
    optouts: list[str] = Field(..., min_length=1, max_length=1000)


class SMSGlobalOptInNumberConfig(_Input):
    operation: Literal["opt_in_number"] = Field("opt_in_number", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Opt In Number', 'x-category': 'Opt Outs'})
    number: int = Field(..., ge=1, description="International mobile number to remove from opt outs.")


class SMSGlobalGetContactDetailsConfig(_Input):
    operation: Literal["get_contact_details"] = Field("get_contact_details", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Get Contact Details', 'x-category': 'Account'})


class SMSGlobalGetCreditBalanceConfig(_Input):
    operation: Literal["get_credit_balance"] = Field("get_credit_balance", json_schema_extra={'ui:hidden': True, 'x-display-name': 'Get Credit Balance', 'x-category': 'Account'})


class SMSGlobalListDedicatedNumbersConfig(_Page):
    operation: Literal["list_dedicated_numbers"] = Field("list_dedicated_numbers", json_schema_extra={'ui:hidden': True, 'x-display-name': 'List Dedicated Numbers', 'x-category': 'Account'})


class SMSGlobalOnNewIncomingConfig(PollTriggerConfigBase):
    operation: Literal["on_new_incoming_message"] = Field("on_new_incoming_message", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Incoming Message"})
    start_date: str = Field(..., description="Only watch messages received since this YYYY-MM-DD HH:MM:SS in your SMSGlobal account timezone. Choose a recent date to keep the poll under 9999 records.")
    destination: int | None = Field(None, ge=1)
    origin: int | None = Field(None, ge=1)

    @field_validator("start_date")
    @classmethod
    def date(cls, value):
        datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return value


class SMSGlobalOnOutgoingStatusConfig(PollTriggerConfigBase):
    operation: Literal["on_new_or_updated_outgoing_message"] = Field("on_new_or_updated_outgoing_message", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New or Updated Outgoing Message"})
    start_date: str = Field(..., description="Watch messages created since this YYYY-MM-DD HH:MM:SS in your account timezone. Detects new messages and previously unseen statuses; narrow the date if more than 9999 messages match.")
    destination: int | None = Field(None, ge=1)
    source: int | None = Field(None, ge=1)

    @field_validator("start_date")
    @classmethod
    def date(cls, value):
        datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return value


SMSGlobalConfig = Annotated[Union[SMSGlobalSendSmsConfig, SMSGlobalListOutgoingMessagesConfig, SMSGlobalGetOutgoingMessageConfig, SMSGlobalDeleteScheduledMessageConfig, SMSGlobalListIncomingMessagesConfig, SMSGlobalGetIncomingMessageConfig, SMSGlobalListGroupsConfig, SMSGlobalGetGroupConfig, SMSGlobalCreateGroupConfig, SMSGlobalUpdateGroupConfig, SMSGlobalDeleteGroupConfig, SMSGlobalListContactsConfig, SMSGlobalGetContactConfig, SMSGlobalCreateContactConfig, SMSGlobalUpdateContactConfig, SMSGlobalDeleteContactConfig, SMSGlobalListOptOutsConfig, SMSGlobalOptOutNumbersConfig, SMSGlobalValidateOptOutsConfig, SMSGlobalOptInNumberConfig, SMSGlobalGetContactDetailsConfig, SMSGlobalGetCreditBalanceConfig, SMSGlobalListDedicatedNumbersConfig, SMSGlobalOnNewIncomingConfig, SMSGlobalOnOutgoingStatusConfig], Field(discriminator="operation")]


class SMSGlobalFullConfig(NodeConfig[SMSGlobalConfig, SMSGlobalCredential]):
    pass


ROUTES = {
    "send_sms": ('POST', '/v2/sms', {'destination': 'destination', 'message': 'message', 'origin': 'origin', 'shared_pool': 'sharedPool', 'scheduled_date_time': 'scheduledDateTime', 'expiry_date_time': 'expiryDateTime', 'campaign': 'campaign'}),
    "list_outgoing_messages": ('GET', '/v2/sms', {}),
    "get_outgoing_message": ('GET', '/v2/sms/{message_id}', {}),
    "delete_scheduled_message": ('DELETE', '/v2/sms/scheduled/{message_id}', {}),
    "list_incoming_messages": ('GET', '/v2/sms-incoming', {}),
    "get_incoming_message": ('GET', '/v2/sms-incoming/{message_id}', {}),
    "list_groups": ('GET', '/v2/group', {}),
    "get_group": ('GET', '/v2/group/{group_id}', {}),
    "create_group": ('POST', '/v2/group', {'name': 'name', 'keyword': 'keyword', 'is_global': 'isGlobal', 'default_origin': 'defaultOrigin'}),
    "update_group": ('PATCH', '/v2/group/{group_id}', {'name': 'name', 'keyword': 'keyword', 'is_global': 'isGlobal', 'default_origin': 'defaultOrigin'}),
    "delete_group": ('DELETE', '/v2/group/{group_id}', {}),
    "list_contacts": ('GET', '/v2/group/{group_id}/contacts', {}),
    "get_contact": ('GET', '/v2/contact/{contact_id}', {}),
    "create_contact": ('POST', '/v2/group/{group_id}/contact', {'given_name': 'givenName', 'family_name': 'familyName', 'display_name': 'displayName', 'msisdn': 'msisdn', 'email_address': 'emailAddress'}),
    "update_contact": ('PUT', '/v2/contact/{contact_id}', {'given_name': 'givenName', 'family_name': 'familyName', 'display_name': 'displayName', 'msisdn': 'msisdn', 'email_address': 'emailAddress'}),
    "delete_contact": ('DELETE', '/v2/contact/{contact_id}', {}),
    "list_opt_outs": ('GET', '/v2/opt-outs', {}),
    "opt_out_numbers": ('POST', '/v2/opt-outs', {'optouts': 'optouts'}),
    "validate_opt_outs": ('POST', '/v2/opt-outs/validate', {'optouts': 'optouts'}),
    "opt_in_number": ('DELETE', '/v2/opt-outs/{number}', {}),
    "get_contact_details": ('GET', '/v2/user/contact-details', {}),
    "get_credit_balance": ('GET', '/v2/user/credit-balance', {}),
    "list_dedicated_numbers": ('GET', '/v2/dedicated-number', {}),
}

QUERY_FIELDS = {"offset": "offset", "limit": "limit", "start_date": "startDate", "end_date": "endDate",
    "destination": "destination", "origin": "origin", "source": "source", "status": "status", "search": "search",
    "sort": "sort", "phone_number": "phoneNumber"}


def mac_header(credential, method, url, *, timestamp=None, nonce=None):
    """Sign the exact encoded path AND query being sent, with a final empty ext line."""
    timestamp = str(int(time.time())) if timestamp is None else str(timestamp)
    nonce = secrets.token_hex(16) if nonce is None else nonce
    message = f"{timestamp}\n{nonce}\n{method.upper()}\n{url.raw_path.decode('ascii')}\n{url.host}\n443\n\n"
    digest = base64.b64encode(hmac.new(credential.api_secret.encode(), message.encode(), hashlib.sha256).digest()).decode()
    return f'MAC id="{credential.api_key}", ts="{timestamp}", nonce="{nonce}", mac="{digest}"'


def _valid_message_id(value):
    # Official PHP SDK list fixtures use decimal strings; OpenAPI says integer.
    return (type(value) is int and value > 0) or (isinstance(value, str) and value.isascii() and value.isdecimal() and 0 < len(value) <= 30 and int(value) > 0)


class SMSGlobalNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-smsglobal"
    connection_evidence = ConnectionEvidence(noun="SMSGlobal account", identity_operation="get_contact_details", identity_keys=("name", "email"))

    @classmethod
    def get_config_model(cls):
        return SMSGlobalFullConfig

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect your SMSGlobal REST API key and secret")
        url = httpx.URL(BASE + path, params=params or {})
        headers = {"Accept": "application/json", "Authorization": mac_header(credential, method, url)}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, url, headers=headers, **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            # Keep provider rejection text for the shared connection verdict,
            # while preventing an upstream echo from exposing either secret.
            text = response.text[:2000]
            for value in (credential.api_key, credential.api_secret):
                text = text.replace(value, "[redacted]")
            raise ValueError(f"SMSGlobal HTTP {response.status_code}: {text}")
        if response.status_code == 204 or not response.content:
            return None
        try:
            data = response.json()
        except ValueError:
            raise ValueError("SMSGlobal returned invalid JSON") from None
        if not isinstance(data, (dict, list)):
            raise ValueError("SMSGlobal returned an unexpected JSON shape")
        return data

    async def _poll(self, config):
        incoming = config.operation == "on_new_incoming_message"
        path = "/v2/sms-incoming" if incoming else "/v2/sms"
        params = {wire: getattr(config, field) for field, wire in QUERY_FIELDS.items()
                  if field in type(config).model_fields and getattr(config, field) is not None}
        rows, seen, offset = [], set(), 1
        # All matching pages are read before changing the baseline. The API
        # caps offset+limit at 10000; never silently miss messages at that cap.
        for _ in range(20):
            limit = min(500, 10000 - offset)
            if limit <= 0:
                raise ValueError("SMSGlobal poll exceeds 9999 messages; choose a later start date")
            payload = await self._request("GET", path, params={**params, "offset": offset, "limit": limit})
            if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list):
                raise ValueError("SMSGlobal poll requires a messages list")
            total = payload.get("total")
            if total is not None and (type(total) is not int or total < 0 or total > 9999):
                raise ValueError("SMSGlobal poll total is invalid or exceeds 9999; narrow the start date")
            page = payload["messages"]
            if len(page) > limit or any(not isinstance(row, dict) or not _valid_message_id(row.get("id")) for row in page):
                raise ValueError("SMSGlobal poll message IDs are invalid")
            for row in page:
                if str(row["id"]) in seen:
                    raise ValueError("SMSGlobal repeats a message across pages; retry the poll")
                seen.add(str(row["id"]))
            rows.extend(page)
            if (total is not None and len(rows) >= total) or (total is None and len(page) < limit):
                break
            if not page:
                raise ValueError("SMSGlobal poll returned an incomplete page")
            offset += len(page)
        else:
            raise ValueError("SMSGlobal poll could not finish; narrow the start date")
        if not incoming and any(not isinstance(row.get("status"), str) for row in rows):
            raise ValueError("SMSGlobal outgoing poll requires each message status")
        fresh = await self._filter_unseen(rows, lambda row: str(row["id"]) if incoming else f'{row["id"]}:{row["status"]}')
        return {"status": "success", "event": config.operation, "messages": fresh, "new_message_count": len(fresh)}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("event") not in {"on_new_incoming_message", "on_new_or_updated_outgoing_message"}:
            return super().resolve_agent_event(output)
        messages = output.get("messages")
        if not isinstance(messages, list) or not messages:
            return None
        incoming = output["event"] == "on_new_incoming_message"
        lines = [f"{'Incoming SMS' if incoming else 'Outgoing SMS status'} from {row.get('origin', 'unknown sender')} to {row.get('destination', 'unknown recipient')}: {row.get('message', '')}"
                 f" (message id {row.get('id')}, outgoing id {row.get('outgoing_id')}, time {row.get('dateTime')})"
                 + (f"; status {row.get('status')}" if not incoming else "") for row in messages[:10]]
        return {"text": "SMSGlobal: " + str(len(messages)) + " new message event(s)\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        if not isinstance(self.config, SMSGlobalFullConfig) or self.config.credentials is None:
            raise ValueError("Connect SMSGlobal before running this operation")
        config = self.config.config
        if isinstance(config, (SMSGlobalOnNewIncomingConfig, SMSGlobalOnOutgoingStatusConfig)):
            return await self._poll(config)
        method, path, mapping = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        path = path.format(**values)
        params = {wire: values[field] for field, wire in QUERY_FIELDS.items() if field in values} if method == "GET" else None
        body = {wire: values[field] for field, wire in mapping.items() if field in values} if mapping else None
        if config.operation == "send_sms":
            body = {"messages": [body]}
        data = await self._request(method, path, params=params, body=body)
        return {"status": "success", "data": data}
