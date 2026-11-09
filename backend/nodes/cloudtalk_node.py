"""CloudTalk API 1.7: explicit public-contact and core telephony operations.

Contract: https://help.cloudtalk.io/api-reference/openapi.json
All requests use pasted Access Key ID/Secret HTTP Basic credentials. A call or
SMS acknowledgement is not proof of connection or delivery. No automatic retries.
"""
from __future__ import annotations

import base64
import re
from datetime import datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

CREDENTIAL_TYPE = "cloudtalk_api_key"
PUBLIC = "https://api.cloudtalk.io/v1"
CORE = "https://my.cloudtalk.io/api"
ANALYTICS = "https://analytics-api.cloudtalk.io/api"


class CloudTalkAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="CloudTalk API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dashboard.cloudtalk.io/menu/account/settings/API-keys",
            "x-credential-instructions": "In CloudTalk, open Account → Settings → API Keys. Paste the API Access Key ID and Access Key Secret. An administrator can generate these keys. NoClick uses HTTP Basic authentication and reads your account's agents to check the connection.",
        })
    credential_type: Literal["cloudtalk_api_key"] = Field("cloudtalk_api_key", json_schema_extra={"ui:hidden": True})
    access_key_id: str = Field(..., min_length=1, max_length=4096, title="Access Key ID", json_schema_extra={"ui:widget": "password"})
    access_key_secret: str = Field(..., min_length=1, max_length=4096, title="Access Key Secret", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_key_id", "access_key_secret", mode="before")
    @classmethod
    def clean(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if any(c.isspace() for c in value) or ":" in value:
            raise ValueError("Paste the key value without whitespace or a Basic header")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
Phone = Annotated[str, Field(pattern=r"^\+[1-9][0-9]{6,14}$")]


class CursorPage(Input):
    limit: int = Field(20, ge=1, le=100)
    cursor: str | None = Field(None, max_length=4096, description="Pass pagination.next unchanged with the same filters. Read one page per execution.")


class ListContacts(CursorPage):
    operation: Literal["list_contacts"] = "list_contacts"
    search: str | None = Field(None, min_length=2, max_length=200)
    tagIds: str | None = Field(None, description="1 to 20 comma-separated contact tag IDs.")
    type: Literal["contact", "lead"] | None = None
    updatedSince: datetime | None = None
    customField: str | None = Field(None, min_length=1, max_length=255)
    customFieldValue: str | None = Field(None, min_length=1)

    @field_validator("tagIds")
    @classmethod
    def tags(cls, value):
        if value is not None and (not re.fullmatch(r"[A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+){0,19}", value)):
            raise ValueError("Use 1 to 20 comma-separated tag IDs")
        return value

    @model_validator(mode="after")
    def filters(self):
        if (self.customField is None) != (self.customFieldValue is None):
            raise ValueError("Supply both customField and customFieldValue")
        if self.search and self.customField:
            raise ValueError("Custom-field matching cannot be combined with search")
        return self


class ContactFields(Input):
    title: str | None = Field(None, max_length=255)
    company: str | None = Field(None, max_length=100)
    industry: str | None = Field(None, max_length=100)
    website: str | None = Field(None, max_length=100)
    address: str | None = Field(None, max_length=255)
    city: str | None = Field(None, max_length=255)
    state: str | None = Field(None, max_length=255)
    zip: str | None = Field(None, max_length=15)
    countryCode: str | None = Field(None, pattern=r"^[A-Z]{2}$")
    phones: list[Phone] | None = Field(None, max_length=20, description="Replaces the whole phone list on update; [] clears it.")
    emails: list[str] | None = Field(None, max_length=20, description="Replaces the whole email list on update; [] clears it.")
    favoriteUserId: Identifier | None = None

    @field_validator("emails")
    @classmethod
    def emails_valid(cls, value):
        if value is not None and any(not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) for email in value):
            raise ValueError("Use valid email addresses")
        return value


class CreateContact(ContactFields):
    operation: Literal["create_contact"] = "create_contact"
    name: str = Field(..., min_length=1, max_length=150)
    type: Literal["contact", "lead"] = "contact"
    tagIds: list[Identifier] | None = Field(None, max_length=50)
    customFields: dict[str, Annotated[str, Field(max_length=255)]] | None = Field(None, max_length=100)
    matchBy: Literal["none", "phone", "email", "emailOrPhone"] = Field("none", description="Matching can update an existing contact instead of creating one.")
    idempotency_key: str | None = Field(None, min_length=1, max_length=255, description="Optional Idempotency-Key header. Reuse the same key only for an identical create request.")

    @model_validator(mode="after")
    def match_fields(self):
        if self.matchBy == "phone" and not self.phones or self.matchBy == "email" and not self.emails or self.matchBy == "emailOrPhone" and not (self.phones or self.emails):
            raise ValueError("Provide the phone or email required by matchBy")
        return self


class ContactID(Input):
    contact_id: Identifier


class GetContact(ContactID):
    operation: Literal["get_contact"] = "get_contact"


class UpdateContact(ContactFields, ContactID):
    operation: Literal["update_contact"] = "update_contact"
    name: str | None = Field(None, min_length=1, max_length=150)
    type: Literal["contact"] | None = None
    customFields: dict[str, Annotated[str, Field(max_length=255)] | None] | None = Field(None, max_length=100, description="Merge by key; null removes a key.")
    clear_fields: list[Literal["title", "company", "industry", "website", "address", "city", "state", "zip", "favoriteUserId"]] = Field(default_factory=list, description="Explicitly clear nullable fields. Other unset fields stay unchanged.")

    @model_validator(mode="after")
    def nonempty(self):
        names = set(type(self).model_fields) - {"operation", "contact_id", "clear_fields"}
        if not self.clear_fields and not any(getattr(self, key) is not None for key in names):
            raise ValueError("Provide at least one changed field or clear_fields")
        if any(getattr(self, key) is not None for key in self.clear_fields):
            raise ValueError("Do not set and clear the same field")
        return self


class DeleteContact(ContactID):
    operation: Literal["delete_contact"] = "delete_contact"


class AddContactTags(ContactID):
    operation: Literal["add_contact_tags"] = "add_contact_tags"
    tagIds: list[Identifier] = Field(..., min_length=1, max_length=50)


class RemoveContactTags(ContactID):
    operation: Literal["remove_contact_tags"] = "remove_contact_tags"
    tagIds: list[Identifier] = Field(..., min_length=1, max_length=50)


class ListContactTags(CursorPage):
    operation: Literal["list_contact_tags"] = "list_contact_tags"
    search: str | None = Field(None, min_length=1, max_length=60)


class CreateContactTag(Input):
    operation: Literal["create_contact_tag"] = "create_contact_tag"
    name: str = Field(..., min_length=1, max_length=60)


class RenameContactTag(Input):
    operation: Literal["rename_contact_tag"] = "rename_contact_tag"
    tag_id: Identifier
    name: str = Field(..., min_length=1, max_length=60)


class DeleteContactTag(Input):
    operation: Literal["delete_contact_tag"] = "delete_contact_tag"
    tag_id: Identifier = Field(..., description="Deleting a tag also removes it from contacts and automation targeting. This cannot be undone.")


class ListContactFields(CursorPage):
    operation: Literal["list_contact_fields"] = "list_contact_fields"


class Page(Input):
    limit: int = Field(100, ge=1, le=1000)
    page: int = Field(1, ge=1, description="Read one page; pass next_page to continue.")


class ListAgents(Page):
    operation: Literal["list_agents"] = "list_agents"
    id: int | None = Field(None, ge=1)
    associated_number: Phone | None = None


class ListGroups(Page):
    operation: Literal["list_groups"] = "list_groups"


class ListNumbers(Page):
    operation: Literal["list_numbers"] = "list_numbers"
    id: int | None = Field(None, ge=1)
    country_code: int | None = Field(None, ge=1)
    area_code: int | None = Field(None, ge=1)
    connected_to: Literal[0, 1, 2, 3] | None = None
    is_free: Literal[0, 1] | None = None


class ListNotes(Page):
    operation: Literal["list_notes"] = "list_notes"
    contact_id: int | None = Field(None, ge=1)
    user_id: int | None = Field(None, ge=1)
    keyword: str | None = None


class AddNote(Input):
    operation: Literal["add_note"] = "add_note"
    contact_id: int = Field(..., ge=1)
    note: str = Field(..., min_length=1)
    user_id: int | None = Field(None, ge=1)


class ListCalls(Page):
    operation: Literal["list_calls"] = "list_calls"
    public_internal: str | None = None
    public_external: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    contact_id: int | None = Field(None, ge=1)
    user_id: int | None = Field(None, ge=1)
    agent_extension: int | None = Field(None, ge=1)
    type: Literal["incoming", "outgoing", "internal"] | None = None
    status: Literal["missed", "answered"] | None = None
    tag_id: int | None = Field(None, ge=1)
    call_id: int | None = Field(None, ge=1)


class GetCall(Input):
    operation: Literal["get_call"] = "get_call"
    call_id: int = Field(..., ge=1)


class SendSMS(Input):
    operation: Literal["send_sms"] = "send_sms"
    recipient: Phone
    sender: Phone
    message: str = Field(..., min_length=1, description="One SMS to one recipient; acceptance does not confirm delivery.")
    country_code: str | None = None


class MakeCall(Input):
    operation: Literal["make_call"] = "make_call"
    agent_id: int = Field(..., ge=1)
    callee_number: Phone = Field(..., description="Calls the agent first, then this number. Acknowledgement does not confirm the callee answered.")


CloudTalkConfig = Annotated[Union[ListContacts, CreateContact, GetContact, UpdateContact, DeleteContact,
    AddContactTags, RemoveContactTags, ListContactTags, CreateContactTag, RenameContactTag, DeleteContactTag,
    ListContactFields, ListAgents, ListGroups, ListNumbers, ListNotes, AddNote, ListCalls, GetCall, SendSMS, MakeCall],
    Field(discriminator="operation")]


class CloudTalkFullConfig(NodeConfig[CloudTalkConfig, CloudTalkAPIKeyCredential]):
    pass


# Each operation has exactly one published API operation. Servers are selected
# per operation as in the contract, never from user input or a response URL.
OPERATIONS = {
    "list_contacts": ("GET", PUBLIC, "/contacts"),
    "create_contact": ("POST", PUBLIC, "/contacts"),
    "get_contact": ("GET", PUBLIC, "/contacts/{contact_id}"),
    "update_contact": ("PATCH", PUBLIC, "/contacts/{contact_id}"),
    "delete_contact": ("DELETE", PUBLIC, "/contacts/{contact_id}"),
    "add_contact_tags": ("POST", PUBLIC, "/contacts/{contact_id}/tags"),
    "remove_contact_tags": ("DELETE", PUBLIC, "/contacts/{contact_id}/tags"),
    "list_contact_tags": ("GET", PUBLIC, "/contact-tags"),
    "create_contact_tag": ("POST", PUBLIC, "/contact-tags"),
    "rename_contact_tag": ("PATCH", PUBLIC, "/contact-tags/{tag_id}"),
    "delete_contact_tag": ("DELETE", PUBLIC, "/contact-tags/{tag_id}"),
    "list_contact_fields": ("GET", PUBLIC, "/contact-fields"),
    "list_agents": ("GET", CORE, "/agents/index.json"),
    "list_groups": ("GET", CORE, "/groups/index.json"),
    "list_numbers": ("GET", CORE, "/numbers/index.json"),
    "list_notes": ("GET", CORE, "/notes/index.json"),
    "add_note": ("PUT", CORE, "/notes/add/{contact_id}.json"),
    "list_calls": ("GET", CORE, "/calls/index.json"),
    "get_call": ("GET", ANALYTICS, "/calls/{call_id}"),
    "send_sms": ("POST", CORE, "/sms/send.json"),
    "make_call": ("POST", CORE, "/calls/create.json"),
}
WRAPPERS = {"list_agents": ("Agent",), "list_groups": ("Group", "Groups"), "list_numbers": ("CallNumber",), "list_notes": ("ContactNote",)}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secrets) for key, item in value.items()}
    return value


class CloudTalkNode(WorkflowNode):
    integration_type = "automation-cloudtalk"
    connection_evidence = ConnectionEvidence(noun="CloudTalk agents", operation="list_agents", label_keys=("email", "name", "firstname", "id"))

    @classmethod
    def get_config_model(cls):
        return CloudTalkFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a CloudTalk API key")
        op = self.config.config
        credential = self.config.credentials
        method, base, template = OPERATIONS[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = template
        for key in ("contact_id", "tag_id", "call_id"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        headers = {"Accept": "application/json"}
        auth = httpx.BasicAuth(credential.access_key_id, credential.access_key_secret)
        auth_value = base64.b64encode((credential.access_key_id + ":" + credential.access_key_secret).encode()).decode()
        secrets = (credential.access_key_secret, credential.access_key_id, auth_value)
        idempotency = values.pop("idempotency_key", None)
        if idempotency:
            headers["Idempotency-Key"] = idempotency
        if isinstance(op, UpdateContact):
            clear = values.pop("clear_fields")
            values.update({name: None for name in clear})
            # exclude_none on the outer model must not drop explicit custom-field removals.
            if op.customFields is not None:
                values["customFields"] = op.customFields
        query = method == "GET" or isinstance(op, RemoveContactTags)
        if isinstance(op, RemoveContactTags):
            values["tagIds"] = ",".join(values["tagIds"])
        kwargs = {"params": values} if query else {"json": values} if values else {}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, base + path, headers=headers, auth=auth, **kwargs)
        except httpx.HTTPError:
            suffix = "; the write outcome is unknown, inspect CloudTalk before retrying" if method != "GET" else ""
            raise ValueError("CloudTalk request did not complete" + suffix) from None
        if not 200 <= response.status_code < 300:
            message = "CloudTalk request rejected"
            try:
                error = response.json()
                detail = error.get("responseData", error.get("error", {}))
                if isinstance(detail, dict) and isinstance(detail.get("message"), str):
                    message = detail["message"][:500]
            except (ValueError, AttributeError):
                pass
            raise ValueError(_redact(f"CloudTalk HTTP {response.status_code}: {message}", secrets))
        expected = {204} if isinstance(op, (DeleteContact, DeleteContactTag)) else {200, 201} if isinstance(op, (CreateContact, CreateContactTag)) else {201} if isinstance(op, AddNote) else {200}
        if response.status_code not in expected:
            raise ValueError("CloudTalk returned an unexpected success status; inspect writes before retrying")
        if response.status_code == 204:
            result = {"data": None, "deletion_acknowledged": True}
        else:
            try:
                if len(response.content) > 10_000_000:
                    raise ValueError("Response too large")
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Expected an object")
                envelope = payload.get("responseData", payload)
                if not isinstance(envelope, dict):
                    raise ValueError("Expected responseData object")
            except ValueError:
                raise ValueError("CloudTalk returned an unexpected JSON response; inspect writes before retrying") from None
            if envelope.get("success") is False or envelope.get("success") == "false" or (isinstance(envelope.get("status"), int) and envelope["status"] >= 400) or "error" in payload:
                message = envelope.get("message") or envelope.get("data") or "CloudTalk reported an error"
                raise ValueError(_redact(str(message)[:500], secrets))
            if op.operation.startswith("list_"):
                rows = envelope.get("data")
                if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                    raise ValueError("CloudTalk returned an invalid list envelope")
                for wrapper in WRAPPERS.get(op.operation, ()):
                    rows = [row.get(wrapper, row) for row in rows]
                if any(not isinstance(row, dict) for row in rows):
                    raise ValueError("CloudTalk returned an invalid resource")
                result = {"data": rows}
                if base == PUBLIC:
                    pagination = envelope.get("pagination")
                    if not isinstance(pagination, dict) or (pagination.get("next") is not None and not isinstance(pagination["next"], str)):
                        raise ValueError("CloudTalk returned invalid cursor pagination")
                    result.update(pagination=pagination, next_cursor=pagination.get("next"))
                else:
                    page_count = envelope.get("pageCount")
                    page_number = envelope.get("pageNumber")
                    if type(page_count) is not int or type(page_number) is not int:
                        raise ValueError("CloudTalk returned invalid page pagination")
                    result.update(pagination={key: envelope.get(key) for key in ("itemsCount", "pageCount", "pageNumber", "limit")},
                        next_page=page_number + 1 if page_number < page_count else None)
            else:
                result = {"data": envelope}
            if isinstance(op, SendSMS) and envelope.get("success") not in (True, "true"):
                raise ValueError("CloudTalk did not acknowledge the SMS; inspect before retrying")
            if isinstance(op, MakeCall) and envelope.get("status") != 200:
                raise ValueError("CloudTalk did not acknowledge the call; inspect before retrying")
            if isinstance(op, (SendSMS, MakeCall)):
                result.update(request_acknowledged=True, delivery_verified=False)
        output = _redact({"status": "success", "operation": op.operation, "http_status": response.status_code, **result}, secrets)
        await self.emit(output)
        return output
