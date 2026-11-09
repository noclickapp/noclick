"""Systeme.io Public API v1 contacts, marketing and course enrollment operations."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.systeme.io"
PositiveID = Annotated[int, Field(ge=1)]
Locale = Literal["en", "fr", "es", "it", "pt", "de", "nl", "ru", "jp", "tr", "ar", "zh", "sv", "ro", "cs", "hu", "sk", "dk", "id", "pl", "el", "sr", "hi", "no", "th", "sq", "sl", "ua"]


class SystemeioAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="systeme.io API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developer.systeme.io/reference/api",
        "x-credential-instructions": "In systeme.io profile settings, open Public API keys and generate a key. Paste it here without a header prefix. NoClick sends it as X-API-Key to api.systeme.io. Connection verification reads your contacts; it does not verify every write permission.",
    })
    credential_type: Literal["systemeio_api_key"] = Field("systemeio_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(100, ge=10, le=100, description="Number of results in this page; 10 to 100.")
    starting_after: PositiveID | None = Field(None, description="Use next_starting_after from the previous page with the same filters and order.")
    order: Literal["asc", "desc"] = "desc"


class ListContacts(_Page):
    operation: Literal["list_contacts"] = "list_contacts"
    email: str | None = Field(None, description="Exact contact email filter.")
    tags: str | None = Field(None, pattern=r"^[1-9][0-9]*(,[1-9][0-9]*)*$", description="Comma-separated tag IDs; matches all tags.")
    bounced: bool | None = None
    unsubscribed: bool | None = None
    needs_confirmation: bool | None = None
    registered_before: datetime | None = None
    registered_after: datetime | None = None


class _Contact(_Input):
    contact_id: PositiveID


class GetContact(_Contact):
    operation: Literal["get_contact"] = "get_contact"


class DeleteContact(_Contact):
    """Request deletion; the provider may retain contact data for several days."""
    operation: Literal["delete_contact"] = "delete_contact"


class ContactField(_Input):
    slug: str = Field(..., min_length=1, description="Contact field slug, e.g. first_name or country (two-letter ISO code).")
    value: str | None = Field(..., description="Field value; null clears it.")


class CreateContact(_Input):
    operation: Literal["create_contact"] = "create_contact"
    email: str = Field(..., min_length=3, description="Email address of the new contact.")
    locale: Locale | None = None
    fields: list[ContactField] | None = None


class UpdateContact(_Contact):
    operation: Literal["update_contact"] = "update_contact"
    locale: Locale | None = None
    fields: list[ContactField] | None = None

    @model_validator(mode="after")
    def update_present(self):
        if self.locale is None and self.fields is None:
            raise ValueError("Supply a locale or contact fields to update")
        return self


class AssignTag(_Contact):
    operation: Literal["assign_tag"] = "assign_tag"
    tag_id: PositiveID


class RemoveTag(_Contact):
    operation: Literal["remove_tag"] = "remove_tag"
    tag_id: PositiveID


class ListTags(_Page):
    operation: Literal["list_tags"] = "list_tags"
    query: str | None = None


class _Tag(_Input):
    tag_id: PositiveID


class GetTag(_Tag):
    operation: Literal["get_tag"] = "get_tag"


class CreateTag(_Input):
    operation: Literal["create_tag"] = "create_tag"
    name: str = Field(..., min_length=1, max_length=64)


class UpdateTag(_Tag):
    operation: Literal["update_tag"] = "update_tag"
    name: str = Field(..., min_length=1, max_length=64)


class DeleteTag(_Tag):
    operation: Literal["delete_tag"] = "delete_tag"


class ListCampaigns(_Page):
    operation: Literal["list_campaigns"] = "list_campaigns"
    query: str | None = None


class GetCampaign(_Input):
    operation: Literal["get_campaign"] = "get_campaign"
    campaign_id: PositiveID


class ListCampaignSteps(_Input):
    operation: Literal["list_campaign_steps"] = "list_campaign_steps"
    campaign_id: PositiveID


class ListCourses(_Page):
    operation: Literal["list_courses"] = "list_courses"
    active: bool | None = None
    query: str | None = None


class GetCourse(_Input):
    operation: Literal["get_course"] = "get_course"
    course_id: PositiveID


class EnrollContact(_Input):
    operation: Literal["enroll_contact"] = "enroll_contact"
    course_id: PositiveID
    contact_id: PositiveID
    access_type: Literal["partial_access", "full_access", "dripping_content", "partial_dripping_access"] = Field(..., description="Course access granted to this contact.")
    modules: list[PositiveID] | None = Field(None, description="Required module IDs for partial access types.")

    @model_validator(mode="after")
    def partial_modules(self):
        if self.access_type in {"partial_access", "partial_dripping_access"} and not self.modules:
            raise ValueError("Partial access requires module IDs")
        return self


class ListEnrollments(_Page):
    operation: Literal["list_enrollments"] = "list_enrollments"
    course: PositiveID | None = None
    contact: PositiveID | None = None


class DeleteEnrollment(_Input):
    operation: Literal["delete_enrollment"] = "delete_enrollment"
    enrollment_id: PositiveID


SystemeioOperation = Annotated[Union[
    ListContacts, GetContact, CreateContact, UpdateContact, DeleteContact, AssignTag, RemoveTag,
    ListTags, GetTag, CreateTag, UpdateTag, DeleteTag, ListCampaigns, GetCampaign, ListCampaignSteps,
    ListCourses, GetCourse, EnrollContact, ListEnrollments, DeleteEnrollment,
], Field(discriminator="operation")]


class SystemeioConfig(NodeConfig[SystemeioOperation, SystemeioAPIKeyCredential]):
    pass


# Each operation issues exactly one request from the published v1 contract.
ROUTES = {
    "list_contacts": ("GET", "/api/contacts"),
    "get_contact": ("GET", "/api/contacts/{contact_id}"),
    "create_contact": ("POST", "/api/contacts"),
    "update_contact": ("PATCH", "/api/contacts/{contact_id}"),
    "delete_contact": ("DELETE", "/api/contacts/{contact_id}"),
    "assign_tag": ("POST", "/api/contacts/{contact_id}/tags"),
    "remove_tag": ("DELETE", "/api/contacts/{contact_id}/tags/{tag_id}"),
    "list_tags": ("GET", "/api/tags"),
    "get_tag": ("GET", "/api/tags/{tag_id}"),
    "create_tag": ("POST", "/api/tags"),
    "update_tag": ("PUT", "/api/tags/{tag_id}"),
    "delete_tag": ("DELETE", "/api/tags/{tag_id}"),
    "list_campaigns": ("GET", "/api/mailing/campaigns"),
    "get_campaign": ("GET", "/api/mailing/campaigns/{campaign_id}"),
    "list_campaign_steps": ("GET", "/api/mailing/campaigns/{campaign_id}/steps"),
    "list_courses": ("GET", "/api/school/courses"),
    "get_course": ("GET", "/api/school/courses/{course_id}"),
    "enroll_contact": ("POST", "/api/school/courses/{course_id}/enrollments"),
    "list_enrollments": ("GET", "/api/school/enrollments"),
    "delete_enrollment": ("DELETE", "/api/school/enrollments/{enrollment_id}"),
}
WIRE_NAMES = {"starting_after": "startingAfter", "needs_confirmation": "needsConfirmation",
              "registered_before": "registeredBefore", "registered_after": "registeredAfter",
              "contact_id": "contactId", "tag_id": "tagId", "access_type": "accessType"}


class SystemeioNode(WorkflowNode):
    integration_type = "automation-systemeio"
    connection_evidence = ConnectionEvidence(noun="contacts", operation="list_contacts", label_keys=("email", "id"))

    @classmethod
    def get_config_model(cls):
        return SystemeioConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a systeme.io API key")
        op = self.config.config
        method, template = ROUTES[op.operation]
        values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = template.format(**values)
        data = {WIRE_NAMES.get(k, k): v for k, v in values.items() if "{" + k + "}" not in template}
        headers = {"X-API-Key": self.config.credentials.api_key, "Accept": "application/json"}
        kwargs = {"params": data} if method == "GET" else {}
        if method in {"POST", "PUT", "PATCH"}:
            # Keep null field values: the merge-patch contract uses them to clear data.
            if isinstance(op, (CreateContact, UpdateContact)) and op.fields is not None:
                data["fields"] = [field.model_dump() for field in op.fields]
            headers["Content-Type"] = "application/merge-patch+json" if method == "PATCH" else "application/json"
            kwargs["json"] = data
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers, **kwargs)
        response.raise_for_status()
        expected = 204 if method == "DELETE" or isinstance(op, AssignTag) else 201 if method == "POST" else 200
        if response.status_code != expected:
            raise ValueError(f"Unexpected systeme.io status {response.status_code}; inspect the result before retrying a write")
        if response.status_code == 204:
            result = {"success": True, "http_status": 204}
        else:
            payload = response.json()
            if not isinstance(payload, (dict, list)):
                raise ValueError("Unexpected systeme.io JSON response")
            # Never expose a reflected credential in provider data.
            payload = _redact(payload, self.config.credentials.api_key)
            result = {"data": payload, "http_status": response.status_code}
            if isinstance(op, _Page):
                if not isinstance(payload, dict) or not isinstance(payload.get("items"), list) or type(payload.get("hasMore")) is not bool:
                    raise ValueError("Invalid systeme.io collection response")
                items, more = payload["items"], payload["hasMore"]
                cursor = items[-1].get("id") if more and items and isinstance(items[-1], dict) else None
                if more and (type(cursor) is not int or cursor < 1 or cursor == op.starting_after):
                    raise ValueError("Systeme.io returned an invalid or nonadvancing cursor")
                result = {"items": items, "has_more": more, "next_starting_after": cursor, "http_status": response.status_code}
        await self.emit(result)
        return result


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value
