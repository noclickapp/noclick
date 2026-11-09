"""Reteno REST API, pinned to the provider's published OpenAPI 1.0 contract.

API keys are Basic passwords; any username is allowed by the official guide:
https://docs.reteno.com/reference/getting-started-with-your-api
Each operation makes exactly one request. A successful send/event is an API
acknowledgement, never a claim of delivery or asynchronous processing completion.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.reteno.com"
ID = Annotated[int, Field(gt=0, le=9223372036854775807)]
SegmentID = Annotated[int, Field(gt=0, le=2147483647)]
Text = Annotated[str, Field(min_length=1, max_length=10000)]


class RetenoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Reteno API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.reteno.com/reference/api-keys",
        "x-credential-instructions": "In Reteno, open your profile > Settings > API, create a key and paste it here. Select access rights for the operations you need; Full access to API includes the account-info connection check. NoClick sends the key as the Basic Auth password to api.reteno.com. No username is needed.",
    })
    credential_type: Literal["reteno_api_key"] = Field("reteno_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your Reteno API key as text")
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the key without a header or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Page(Input):
    startindex: int = Field(1, ge=1, le=2147483647, description="One-based index. One page per run; use next_startindex from the previous output.")
    maxrows: int = Field(100, ge=1, le=500, description="Maximum results in this page (up to 500).")


class GetAccountInfo(Input):
    operation: Literal["get_account_info"] = Field("get_account_info", json_schema_extra={"ui:hidden": True})


class SearchContacts(Page):
    operation: Literal["search_contacts"] = Field("search_contacts", json_schema_extra={"ui:hidden": True})
    external_customer_id: Text | None = Field(None, serialization_alias="externalCustomerId")
    email: Text | None = None
    sms: Text | None = None
    firstname: Text | None = None
    lastname: Text | None = None
    sort_by: Literal["contactId"] | None = Field(None, serialization_alias="sortBy", description="Only applies to searches without conditions.")


class ContactID(Input):
    contact_id: ID = Field(..., title="Contact ID")


class GetContact(ContactID):
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})


class ContactChannel(Input):
    type: Literal["email", "sms"] = Field(..., description="Writable email or SMS channel.")
    value: Text


class ContactField(Input):
    id: SegmentID
    value: str = Field(..., max_length=10000)


class ContactAddress(Input):
    region: Text | None = None
    town: Text | None = None
    address: Text | None = None
    postcode: Text | None = None
    country_code: str | None = Field(None, min_length=2, max_length=2, serialization_alias="countryCode")


class ContactData(Input):
    first_name: Text | None = Field(None, serialization_alias="firstName")
    last_name: Text | None = Field(None, serialization_alias="lastName")
    channels: list[ContactChannel] = Field(..., min_length=1, max_length=4, description="At least one email or SMS channel; at most two of each type.")
    external_customer_id: Text | None = Field(None, serialization_alias="externalCustomerId")
    language_code: Text | None = Field(None, serialization_alias="languageCode")
    time_zone: Text | None = Field(None, serialization_alias="timeZone")
    market_id: str | None = Field(None, min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$", serialization_alias="marketId")
    address: ContactAddress | None = None
    fields: list[ContactField] | None = Field(None, max_length=500)
    address_book_id: SegmentID | None = Field(None, serialization_alias="addressBookId")

    @model_validator(mode="after")
    def channel_counts(self):
        for kind in ("email", "sms"):
            if sum(c.type == kind for c in self.channels) > 2:
                raise ValueError("Reteno accepts at most two channels of each type")
        return self


class UpsertContact(Input):
    operation: Literal["upsert_contact"] = Field("upsert_contact", title="Add or Update Contact", json_schema_extra={"ui:hidden": True})
    contact: ContactData = Field(..., description="Create or update in real time. Omitted fields preserve existing values.")


class UpdateContact(ContactID):
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    contact: ContactData = Field(..., description="Updating a deleted contact restores it.")


class DeleteContact(ContactID):
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})
    erase: StrictBool = Field(False, description="True permanently erases profile, activity and tracking data; recovery is impossible.")


class ListSegments(Page):
    operation: Literal["list_segments"] = Field("list_segments", json_schema_extra={"ui:hidden": True})
    name: Text | None = None


class ListSegmentContacts(Page):
    operation: Literal["list_segment_contacts"] = Field("list_segment_contacts", json_schema_extra={"ui:hidden": True})
    segment_id: SegmentID
    order_by_ts: StrictBool = Field(False, serialization_alias="orderByTs")
    asc: StrictBool = True


class SegmentContacts(Input):
    segment_id: SegmentID
    contact_ids: list[ID] | None = Field(None, min_length=1, max_length=500, serialization_alias="contactIds")
    external_customer_ids: list[Text] | None = Field(None, min_length=1, max_length=500, serialization_alias="externalCustomerIds")

    @model_validator(mode="after")
    def selected_contacts(self):
        if not self.contact_ids and not self.external_customer_ids:
            raise ValueError("Select contacts explicitly; an empty detach would remove everyone from the segment")
        return self


class AttachContacts(SegmentContacts):
    operation: Literal["attach_contacts"] = Field("attach_contacts", title="Attach Contacts to Static Segment", json_schema_extra={"ui:hidden": True})


class DetachContacts(SegmentContacts):
    operation: Literal["detach_contacts"] = Field("detach_contacts", title="Detach Contacts from Static Segment", json_schema_extra={"ui:hidden": True})


class ListWorkflows(Page):
    operation: Literal["list_workflows"] = Field("list_workflows", json_schema_extra={"ui:hidden": True})
    name: Text | None = None


class ListEmailMessages(Page):
    operation: Literal["list_email_messages"] = Field("list_email_messages", json_schema_extra={"ui:hidden": True})
    search: str | None = Field(None, max_length=10000)


class MessageID(Input):
    message_id: SegmentID


class GetEmailMessage(MessageID):
    operation: Literal["get_email_message"] = Field("get_email_message", json_schema_extra={"ui:hidden": True})


class EmailContent(Input):
    name: Text
    sender: Text = Field(..., serialization_alias="from", description='Sender name and email, for example "John Smith" <John.Smith@example.com>.')
    subject: Text
    html_text: str = Field(..., min_length=1, max_length=1000000, serialization_alias="htmlText", title="HTML content")
    language_code: Text | None = Field(None, serialization_alias="languageCode")
    tags: list[Text] | None = Field(None, max_length=100)
    subscriptions_keys: list[Text] | None = Field(None, max_length=100, serialization_alias="subscriptionsKeys")
    template: StrictBool = False


class CreateEmailMessage(Input):
    operation: Literal["create_email_message"] = Field("create_email_message", json_schema_extra={"ui:hidden": True})
    message: EmailContent = Field(..., description="Save a base message or template; this operation does not send it.")


class UpdateEmailMessage(MessageID):
    operation: Literal["update_email_message"] = Field("update_email_message", json_schema_extra={"ui:hidden": True})
    message: EmailContent


class DeleteEmailMessage(MessageID):
    operation: Literal["delete_email_message"] = Field("delete_email_message", json_schema_extra={"ui:hidden": True})


class Recipient(Input):
    contact_id: ID | None = Field(None, serialization_alias="contactId")
    external_customer_id: Text | None = Field(None, serialization_alias="externalCustomerId")
    locator: Text | None = Field(None, description="Email address, phone number or push token for the selected message channel.")
    json_param: str | None = Field(None, max_length=20000, serialization_alias="jsonParam", description="JSON object encoded as text for dynamic message content.")
    external_request_id: Text | None = Field(None, serialization_alias="externalRequestId")
    language_code: Text | None = Field(None, serialization_alias="languageCode")

    @model_validator(mode="after")
    def identity(self):
        if sum(x is not None for x in (self.contact_id, self.external_customer_id, self.locator)) != 1:
            raise ValueError("Provide exactly one recipient identifier")
        if self.json_param is not None:
            try:
                value = json.loads(self.json_param)
            except ValueError:
                raise ValueError("Message parameters must be valid JSON") from None
            if not isinstance(value, dict):
                raise ValueError("Message parameters must encode an object")
        return self


class SendPreparedMessage(MessageID):
    operation: Literal["send_prepared_message"] = Field("send_prepared_message", json_schema_extra={"ui:hidden": True})
    recipients: list[Recipient] = Field(..., min_length=1, max_length=500, description="Explicit recipients; sending may create contacts.")
    email: StrictBool = Field(True, description="True for email; false for other channels.")
    from_name: Text | None = Field(None, serialization_alias="fromName")

    @model_validator(mode="after")
    def unique_recipients(self):
        rows = [r.model_dump_json() for r in self.recipients]
        if len(set(rows)) != len(rows):
            raise ValueError("Recipients must be unique")
        return self


class GenerateEvent(Input):
    operation: Literal["generate_event"] = Field("generate_event", title="Generate Event v3", json_schema_extra={"ui:hidden": True})
    event_type_key: str = Field(..., min_length=1, max_length=100, serialization_alias="eventTypeKey")
    params: dict[str, str] = Field(..., description="Contact identifier (externalCustomerId, email or phone) and event parameters. Values are strings in the pinned v3 contract.")

    @model_validator(mode="after")
    def event(self):
        if not any(self.params.get(k) for k in ("externalCustomerId", "email", "phone")):
            raise ValueError("Include a contact identifier in event params")
        if len(json.dumps(self.model_dump(by_alias=True, exclude={"operation"}), ensure_ascii=False).encode()) > 20000:
            raise ValueError("Event content must fit within 20 KB")
        return self


class ListSubscriptionCategories(Input):
    operation: Literal["list_subscription_categories"] = Field("list_subscription_categories", json_schema_extra={"ui:hidden": True})


class GetContactSubscriptions(ContactID):
    operation: Literal["get_contact_subscriptions"] = Field("get_contact_subscriptions", json_schema_extra={"ui:hidden": True})


class UpdateContactSubscriptions(ContactID):
    operation: Literal["update_contact_subscriptions"] = Field("update_contact_subscriptions", json_schema_extra={"ui:hidden": True})
    subscriptions: list[Text] = Field(..., max_length=500, description="Replacement subscription category keys. An empty list clears the contact's subscriptions.")


class GetAdditionalFields(Input):
    operation: Literal["get_additional_fields"] = Field("get_additional_fields", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[
    GetAccountInfo, SearchContacts, GetContact, UpsertContact, UpdateContact, DeleteContact,
    ListSegments, ListSegmentContacts, AttachContacts, DetachContacts, ListWorkflows,
    ListEmailMessages, GetEmailMessage, CreateEmailMessage, UpdateEmailMessage, DeleteEmailMessage,
    SendPreparedMessage, GenerateEvent, ListSubscriptionCategories, GetContactSubscriptions,
    UpdateContactSubscriptions, GetAdditionalFields,
], Field(discriminator="operation")]


class RetenoConfig(NodeConfig[Operation, RetenoAPIKeyCredential]):
    pass


# operation -> (method, pinned route, path argument, request body field)
ROUTES = {
    "get_account_info": ("GET", "/api/v1/account/info", None, None),
    "search_contacts": ("GET", "/api/v1/contacts", None, None),
    "get_contact": ("GET", "/api/v1/contact/{id}", "contact_id", None),
    "upsert_contact": ("POST", "/api/v1/contact", None, "contact"),
    "update_contact": ("PUT", "/api/v1/contact/{id}", "contact_id", "contact"),
    "delete_contact": ("DELETE", "/api/v1/contact/{id}", "contact_id", None),
    "list_segments": ("GET", "/api/v1/groups", None, None),
    "list_segment_contacts": ("GET", "/api/v1/group/{id}/contacts", "segment_id", None),
    "attach_contacts": ("POST", "/api/v1/group/{id}/contacts/attach", "segment_id", "self"),
    "detach_contacts": ("POST", "/api/v1/group/{id}/contacts/detach", "segment_id", "self"),
    "list_workflows": ("GET", "/api/v1/workflows", None, None),
    "list_email_messages": ("GET", "/api/v1/messages/email", None, None),
    "get_email_message": ("GET", "/api/v1/messages/email/{id}", "message_id", None),
    "create_email_message": ("POST", "/api/v1/messages/email", None, "message"),
    "update_email_message": ("PUT", "/api/v1/messages/email/{id}", "message_id", "message"),
    "delete_email_message": ("DELETE", "/api/v1/messages/email/{id}", "message_id", None),
    "send_prepared_message": ("POST", "/api/v1/message/{id}/smartsend", "message_id", "self"),
    "generate_event": ("POST", "/api/v3/event", None, "self"),
    "list_subscription_categories": ("GET", "/api/v1/subscriptions", None, None),
    "get_contact_subscriptions": ("GET", "/api/v1/contact/{id}/subscriptions", "contact_id", None),
    "update_contact_subscriptions": ("PUT", "/api/v1/contact/{id}/subscriptions", "contact_id", "self"),
    "get_additional_fields": ("GET", "/api/v1/additionalfields", None, None),
}


def request_parts(op):
    method, path, path_field, body_field = ROUTES[op.operation]
    if path_field:
        path = path.format(id=getattr(op, path_field))
    values = op.model_dump(mode="json", by_alias=True, exclude_none=True, exclude={"operation", *([path_field] if path_field else [])})
    if body_field:
        return method, path, {}, values if body_field == "self" else values[body_field]
    return method, path, {key: str(value).lower() if isinstance(value, bool) else value for key, value in values.items()}, None


def redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [redact(x, secrets) for x in value]
    if isinstance(value, dict):
        return {redact(k, secrets): redact(v, secrets) for k, v in value.items()}
    return value


class RetenoNode(WorkflowNode):
    integration_type = "automation-reteno"
    connection_evidence = ConnectionEvidence(noun="segments", operation="list_segments", identity_operation="get_account_info", identity_keys=("organisationName", "userEmail", "orgId"))

    @classmethod
    def get_config_model(cls):
        return RetenoConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Reteno API key")
        op = self.config.config
        key = self.config.credentials.api_key
        auth = httpx.BasicAuth("noclick", key)
        auth_header = next(auth.auth_flow(httpx.Request("GET", BASE))).headers["Authorization"]
        method, path, params, body = request_parts(op)
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, params=params, json=body,
                    auth=auth, headers={"Accept": "application/json; charset=UTF-8"})
        except httpx.HTTPError:
            raise ValueError("Reteno request did not complete; inspect the provider before retrying a write") from None
        if not 200 <= response.status_code < 300:
            message = redact(response.text[:2000], (key, auth_header))
            result = {"status": "error", "http_status": response.status_code, "message": message or "Reteno rejected the request"}
        else:
            if response.content:
                try:
                    data = response.json()
                except ValueError:
                    # Several mutation endpoints document a string acknowledgement.
                    if method == "GET" or isinstance(op, (UpsertContact, CreateEmailMessage, SendPreparedMessage)):
                        raise ValueError("Reteno returned an unexpected non-JSON response") from None
                    data = response.text
            else:
                data = None
            if isinstance(data, dict) and (data.get("error") or data.get("errors")):
                result = {"status": "error", "http_status": response.status_code, "message": redact(json.dumps(data), (key, auth_header))}
            else:
                if method == "GET" and not isinstance(data, list if isinstance(op, (Page, ListSubscriptionCategories)) else dict):
                    raise ValueError("Reteno returned an unexpected read response")
                result = {"status": "success", "data": redact(data, (key, auth_header)), "http_status": response.status_code}
                if isinstance(op, Page):
                    if not isinstance(data, list):
                        raise ValueError("Reteno returned an unexpected list response")
                    total = response.headers.get("TotalCount")
                    total_count = int(total) if total and total.isdigit() else None
                    # No invented completeness claim when the provider omits TotalCount.
                    has_more = op.startindex - 1 + len(data) < total_count if total_count is not None else (None if len(data) == op.maxrows else False)
                    result.update(total_count=total_count, has_more=has_more,
                        next_startindex=op.startindex + len(data) if data and has_more is not False else None)
                if method != "GET":
                    result["acknowledged"] = True
                if isinstance(op, (SendPreparedMessage, GenerateEvent)):
                    result["processing_verified"] = False
                if isinstance(op, SendPreparedMessage):
                    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                        raise ValueError("Reteno returned an unexpected send response; inspect before retrying")
                    result["recipient_errors"] = any(row.get("status") == "ERROR" for row in data["results"] if isinstance(row, dict))
                    if result["recipient_errors"]:
                        result["status"] = "error"
                        result["message"] = "Reteno reported recipient errors; inspect the per-recipient results before retrying"
        await self.emit(result)
        return result
