"""Force24 API 1.3: one bounded provider request per operation.

Contract: https://api.data-crypt.com/api-docs/v1.3/swagger.json
A manually supplied bearer token is sent only to api.data-crypt.com. Contact
writes return the provider's per-record statuses, including failures, unchanged.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

NODE_TYPE = "automation-force24"
BASE = "https://api.data-crypt.com/api/v1.3"
DOCS = "https://api.data-crypt.com/index.html"
IntID = Annotated[int, Field(ge=1, le=2147483647)]
ListID = Annotated[str, Field(json_schema_extra={"format": "uuid"})]


class Force24AccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="Force24 Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": DOCS,
            "x-credential-instructions": "Paste an existing Force24 bearer access token, without the Bearer prefix. Force24 issues tokens using its documented client_credentials grant with scope api.Master. The master user can find API credentials under Settings > Applications. Tokens expire: replace this token when it expires. NoClick does not obtain or refresh it. The connection check reads your account's marketing lists; it does not verify every write permission.",
        })
    credential_type: Literal["force24_access_token"] = Field("force24_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access token", min_length=1, max_length=8192,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token", key=True)
        if any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the token without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("marketing_list_id", mode="before", check_fields=False)
    @classmethod
    def list_id(cls, value):
        if value is None:
            return value
        try:
            return str(UUID(value))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Use a marketing list UUID") from None


class _Page(_Input):
    skip: int = Field(0, ge=0, le=2147483647, description="Number of matching records to skip.")
    take: int = Field(100, ge=1, le=500, description="Return one page, up to 500 records.")
    descending: bool = False


class _Recents(_Input):
    from_version_number: int = Field(0, ge=0, le=9223372036854775807,
        description="Inclusive version. Continue with nextVersionNumber from the previous result.")
    count: int = Field(100, ge=0, le=1000)


class _Offset(_Input):
    offset: str = Field("first", max_length=64, pattern=r"^(first|last|next|[0-9]+)$",
        description="first, last, next, or a version number. Continue with the returned nextOffset converted to text.")
    count: int = Field(100, ge=0, le=1000)


class _Contact(_Input):
    contact_id: IntID


class _List(_Input):
    marketing_list_id: ListID


class _Campaign(_Input):
    campaign_id: IntID


class _ContactWrite(_Input):
    email_address: str = Field(..., min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$",
        description="Email address used for matching this contact.")
    external_id: str | None = Field(None, min_length=1, max_length=1000)
    source_key: str | None = Field(None, min_length=1, max_length=1000)
    fields_json: str = Field("{}", title="Contact fields JSON", max_length=100000,
        description="Force24 field names and values, for example the fields returned by List Contact Fields. Does not change consent unless you supply consent fields.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json", "contentMediaType": "application/json", "contentSchema": {"type": "object"}})
    fields: str | None = Field(None, min_length=1, max_length=4000, description="Optional comma-separated fields to return after the write.")

    @field_validator("fields_json", mode="before")
    @classmethod
    def json_object(cls, value):
        if isinstance(value, dict):
            value = json.dumps(value, allow_nan=False)
        try:
            obj = json.loads(value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            if not isinstance(obj, dict):
                raise ValueError()
        except (ValueError, TypeError, RecursionError):
            raise ValueError("Contact fields must be a JSON object") from None
        return value


class Force24ListRecentContacts(_Recents):
    """Read one page of recently created or updated contacts."""
    operation: Literal["list_recent_contacts"] = Field("list_recent_contacts", json_schema_extra={"ui:hidden": True})
    fields: str = Field("*", max_length=4000)
    marketing_list_id: ListID | None = None
    source_key: str | None = Field(None, max_length=1000)
    has_external_id: bool | None = None


class Force24GetContact(_Contact):
    """Read one contact by its numeric Force24 ID."""
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    fields: str = Field("*", max_length=4000)


class Force24FindContacts(_Input):
    """Find contacts by email address, with optional source and external ID filters."""
    operation: Literal["find_contacts"] = Field("find_contacts", json_schema_extra={"ui:hidden": True})
    email_address: str = Field(..., min_length=1, max_length=320)
    external_id: str | None = Field(None, max_length=1000)
    source_key: str | None = Field(None, max_length=1000)
    fields: str = Field("*", max_length=4000)


class Force24UpsertContact(_ContactWrite):
    """Upsert one contact by email; inspect the returned per-record status."""
    operation: Literal["upsert_contact"] = Field("upsert_contact", json_schema_extra={"ui:hidden": True})


class Force24CreateContact(_ContactWrite):
    """Create one contact by email; inspect the returned per-record status."""
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})


class Force24UpdateContact(_ContactWrite):
    """Update one contact by email; inspect the returned per-record status."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})


class Force24DeleteContact(_Contact):
    """Delete a contact from Force24."""
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})


class Force24ListMarketingLists(_Page):
    """Read one page of this account's marketing lists."""
    operation: Literal["list_marketing_lists"] = Field("list_marketing_lists", json_schema_extra={"ui:hidden": True})
    keyword: str | None = Field(None, min_length=1, max_length=1000)
    include_test_lists: bool = False
    sort_by_field: Literal["name", "dateCreated", "activeContacts", "totalContacts"] = "name"


class Force24GetMarketingList(_List):
    """Read a marketing list's details."""
    operation: Literal["get_marketing_list"] = Field("get_marketing_list", json_schema_extra={"ui:hidden": True})


class Force24CreateMarketingList(_Input):
    """Create a named marketing list."""
    operation: Literal["create_marketing_list"] = Field("create_marketing_list", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=1000)
    lock_status: Literal["readWrite", "read"] = "readWrite"


class Force24UpdateMarketingList(_List):
    """Change a marketing list's name or test flag."""
    operation: Literal["update_marketing_list"] = Field("update_marketing_list", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=1, max_length=1000)
    is_test: bool | None = None

    @model_validator(mode="after")
    def nonempty_patch(self):
        if self.name is None and self.is_test is None:
            raise ValueError("Supply a name or test flag to update")
        return self


class Force24DeleteMarketingList(_List):
    """Delete a marketing list."""
    operation: Literal["delete_marketing_list"] = Field("delete_marketing_list", json_schema_extra={"ui:hidden": True})


class Force24AddContactToList(_List, _Contact):
    """Add one contact to a marketing list."""
    operation: Literal["add_contact_to_list"] = Field("add_contact_to_list", json_schema_extra={"ui:hidden": True})


class Force24RemoveContactFromList(_List, _Contact):
    """Remove one contact from a marketing list."""
    operation: Literal["remove_contact_from_list"] = Field("remove_contact_from_list", json_schema_extra={"ui:hidden": True})


class Force24ListContactFields(_Input):
    """Read contact field names and types for mapping contact writes."""
    operation: Literal["list_contact_fields"] = Field("list_contact_fields", json_schema_extra={"ui:hidden": True})


class Force24ListEmailCampaigns(_Page):
    """Read one page of email campaigns."""
    operation: Literal["list_email_campaigns"] = Field("list_email_campaigns", json_schema_extra={"ui:hidden": True})
    sort_by_field: Literal["createdOn", "lastModifiedOn"] = "createdOn"


class Force24GetEmailCampaign(_Campaign):
    """Read an email campaign's details."""
    operation: Literal["get_email_campaign"] = Field("get_email_campaign", json_schema_extra={"ui:hidden": True})


class Force24GetEmailCampaignStats(_Campaign):
    """Read campaign statistics for an optional date range."""
    operation: Literal["get_email_campaign_stats"] = Field("get_email_campaign_stats", json_schema_extra={"ui:hidden": True})
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def date_order(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("End date must be on or after start date")
        return self


class Force24SendEmailCampaign(_Campaign, _Contact):
    """Send an API campaign to one contact. Force24 support must first enable API campaigns."""
    operation: Literal["send_email_campaign"] = Field("send_email_campaign", json_schema_extra={"ui:hidden": True})


class Force24ListEmailOpens(_Recents):
    """Read one page of email opens."""
    operation: Literal["list_email_opens"] = Field("list_email_opens", json_schema_extra={"ui:hidden": True})


class Force24ListEmailClicks(_Recents):
    """Read one page of email clicks."""
    operation: Literal["list_email_clicks"] = Field("list_email_clicks", json_schema_extra={"ui:hidden": True})


class Force24ListEmailUnsubscribes(_Recents):
    """Read one page of email unsubscribes."""
    operation: Literal["list_email_unsubscribes"] = Field("list_email_unsubscribes", json_schema_extra={"ui:hidden": True})


class Force24ListEmailBounces(_Recents):
    """Read one page of email bounces."""
    operation: Literal["list_email_bounces"] = Field("list_email_bounces", json_schema_extra={"ui:hidden": True})


class Force24ListSentEmails(_Offset):
    """Read one page of sent emails with a provider continuation offset."""
    operation: Literal["list_sent_emails"] = Field("list_sent_emails", json_schema_extra={"ui:hidden": True})


class Force24ListWebActivity(_Offset):
    """Read one page of website activity with a provider continuation offset."""
    operation: Literal["list_web_activity"] = Field("list_web_activity", json_schema_extra={"ui:hidden": True})


Force24Config = Annotated[Union[
    Force24ListRecentContacts, Force24GetContact, Force24FindContacts,
    Force24UpsertContact, Force24CreateContact, Force24UpdateContact, Force24DeleteContact,
    Force24ListMarketingLists, Force24GetMarketingList, Force24CreateMarketingList,
    Force24UpdateMarketingList, Force24DeleteMarketingList, Force24AddContactToList,
    Force24RemoveContactFromList, Force24ListContactFields, Force24ListEmailCampaigns,
    Force24GetEmailCampaign, Force24GetEmailCampaignStats, Force24SendEmailCampaign,
    Force24ListEmailOpens, Force24ListEmailClicks, Force24ListEmailUnsubscribes,
    Force24ListEmailBounces, Force24ListSentEmails, Force24ListWebActivity,
], Field(discriminator="operation")]


class Force24FullConfig(NodeConfig[Force24Config, Force24AccessTokenCredential]):
    pass


# Each entry is exactly one operation in the pinned 1.3 contract.
OPERATIONS = {
    "list_recent_contacts": ("GET", "/contacts/recents", "recents"),
    "get_contact": ("GET", "/contacts/{contact_id}", "object"),
    "find_contacts": ("GET", "/contacts/find", "array"),
    "upsert_contact": ("POST", "/contacts/upsert", "batch"),
    "create_contact": ("POST", "/contacts/create", "batch"),
    "update_contact": ("POST", "/contacts/update", "batch"),
    "delete_contact": ("DELETE", "/contacts/{contact_id}", "empty"),
    "list_marketing_lists": ("GET", "/marketing-lists", "page"),
    "get_marketing_list": ("GET", "/marketing-lists/{marketing_list_id}", "object"),
    "create_marketing_list": ("POST", "/marketing-lists", "object"),
    "update_marketing_list": ("PATCH", "/marketing-lists/{marketing_list_id}", "empty"),
    "delete_marketing_list": ("DELETE", "/marketing-lists/{marketing_list_id}", "empty"),
    "add_contact_to_list": ("POST", "/marketing-lists/{marketing_list_id}/contacts/{contact_id}/add", "empty"),
    "remove_contact_from_list": ("POST", "/marketing-lists/{marketing_list_id}/contacts/{contact_id}/remove", "empty"),
    "list_contact_fields": ("GET", "/schemas/contact/fields", "array"),
    "list_email_campaigns": ("GET", "/email/campaigns", "page"),
    "get_email_campaign": ("GET", "/email/campaigns/{campaign_id}", "object"),
    "get_email_campaign_stats": ("GET", "/email/campaigns/{campaign_id}/stats", "object"),
    "send_email_campaign": ("POST", "/email/campaigns/{campaign_id}/send-item", "empty"),
    "list_email_opens": ("GET", "/email/opens", "recents"),
    "list_email_clicks": ("GET", "/email/clicks", "recents"),
    "list_email_unsubscribes": ("GET", "/email/unsubscribes", "recents"),
    "list_email_bounces": ("GET", "/email/bounces", "recents"),
    "list_sent_emails": ("GET", "/email/sent-items", "offset"),
    "list_web_activity": ("GET", "/web-activity", "offset"),
}
QUERY_NAMES = {
    "from_version_number": "fromVersionNumber", "count": "count", "fields": "fields",
    "marketing_list_id": "marketingListId", "source_key": "sourceKey", "has_external_id": "hasExternalId",
    "email_address": "emailAddress", "external_id": "externalId", "keyword": "keyword",
    "include_test_lists": "includeTestLists", "skip": "skip", "take": "take",
    "sort_by_field": "sortByField", "descending": "descending", "start_date": "startDate",
    "end_date": "endDate", "offset": "offset",
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    return value


class Force24Node(WorkflowNode):
    integration_type = "automation-force24"
    connection_evidence = ConnectionEvidence(noun="marketing lists", operation="list_marketing_lists")

    @classmethod
    def get_config_model(cls):
        return Force24FullConfig

    async def execute(self, inputs):
        result = await self._perform(inputs)
        result.update(operation=self.config.config.operation, http_status=200)
        await self.emit(result)
        return result

    async def _perform(self, inputs):
        if not isinstance(self.config, Force24FullConfig) or not self.config.credentials:
            raise ValueError("Connect a Force24 access token")
        config = self.config.config
        values = config.model_dump(mode="json", exclude_none=True)
        method, path, shape = OPERATIONS[config.operation]
        path_values = {k: values[k] for k in ("contact_id", "marketing_list_id", "campaign_id") if "{" + k + "}" in path}
        path = path.format(**path_values)
        params = {QUERY_NAMES[k]: v for k, v in values.items() if k in QUERY_NAMES and k not in path_values} if method == "GET" else {}
        body = None
        if isinstance(config, _ContactWrite):
            item = {"emailAddress": config.email_address, "fields": json.loads(config.fields_json)}
            if config.external_id is not None:
                item["externalId"] = config.external_id
            body = {"items": [item]}
            if config.source_key is not None:
                body["sourceKey"] = config.source_key
            if config.fields is not None:
                body["fields"] = config.fields
        elif config.operation == "create_marketing_list":
            body = {"name": config.name, "lockStatus": config.lock_status}
        elif config.operation == "update_marketing_list":
            body = {k: v for k, v in (("name", config.name), ("isTest", config.is_test)) if v is not None}
        elif config.operation == "send_email_campaign":
            body = {"contactId": config.contact_id}
        token = self.config.credentials.access_token
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            raise ValueError("Force24 request did not complete; confirm the outcome before repeating a write") from None
        if len(response.content) > 4_000_000:
            raise ValueError("Force24 response exceeds the supported size")
        if response.status_code != 200:
            message = "Force24 returned HTTP " + str(response.status_code)
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = str(error.get("detail") or error.get("title") or error.get("message") or message)[:1000]
            except ValueError:
                pass
            raise ValueError(_redact(message, token))
        if shape == "empty":
            if response.content.strip():
                raise ValueError("Force24 returned an unexpected acknowledgement body; confirm the outcome before repeating a write")
            return {"status": "success", "acknowledged": True, "http_status": 200}
        media = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if media != "application/json":
            raise ValueError("Force24 returned an unsupported response type")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Force24 returned invalid JSON") from None
        if isinstance(data, dict) and (data.get("error") or data.get("errors") or data.get("success") is False):
            raise ValueError("Force24 returned an error envelope")
        data = _redact(data, token)
        if shape == "array":
            if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
                raise ValueError("Force24 returned an invalid collection")
            return {"status": "success", "items": data}
        if not isinstance(data, dict):
            raise ValueError("Force24 returned an invalid record")
        if shape == "object":
            return {"status": "success", "item": data}
        # Nullable items are documented. Preserve all provider pagination and
        # per-record outcomes, including statuses that report a rejected write.
        if data.get("items") is not None and (not isinstance(data["items"], list) or not all(isinstance(row, dict) for row in data["items"])):
            raise ValueError("Force24 returned invalid items")
        result = {"status": "success", "items": data.get("items") or [], "provider_result": data}
        if shape == "page":
            if type(data.get("moreItemsAvailable")) is not bool or type(data.get("totalCount")) is not int:
                raise ValueError("Force24 returned invalid page metadata")
            result.update(has_more=data["moreItemsAvailable"], next_skip=config.skip + len(result["items"]) if data["moreItemsAvailable"] else None)
        elif shape == "recents":
            cursor = data.get("nextVersionNumber")
            if cursor is not None and (type(cursor) is not int or cursor < 0):
                raise ValueError("Force24 returned an invalid version")
            result["next_version_number"] = cursor
        elif shape == "offset":
            cursor = data.get("nextOffset")
            if type(cursor) is not int or cursor < 0:
                raise ValueError("Force24 returned an invalid offset")
            result["next_offset"] = str(cursor)
        elif shape == "batch":
            result["note"] = "Request completed. Inspect each item's status, statusDetail and log for its outcome."
        return result
