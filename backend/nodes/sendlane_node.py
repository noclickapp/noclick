"""Sendlane v2 contact, audience and campaign operations using a personal API token."""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.sendlane.com/v2"


class SendlaneAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Sendlane API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://sendlane.stoplight.io/docs/api-documentation",
            "x-credential-instructions": "Create an API token in Sendlane's API settings and paste it here without the Bearer prefix. NoClick uses it to read your lists and perform the operations you select.",
        })
    credential_type: Literal["sendlane_api_token"] = Field("sendlane_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the API token as text")
        value = clean_secret(value, field_name="API token", key=True)
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Pagination(_Input):
    page: int = Field(1, ge=1, description="Page of results to return.")
    limit: int = Field(10, ge=1, description="Maximum number of results.")


class _ListID(_Input):
    list_id: int = Field(..., ge=1, title="List ID")


class _ContactID(_Input):
    contact_id: int = Field(..., ge=1, title="Contact ID")


class _TagID(_Input):
    tag_id: int = Field(..., ge=1, title="Tag ID")


class _Name(_Input):
    name: str = Field(..., min_length=1, max_length=1000)


class _ListBody(_Name):
    description: str | None = Field(None, max_length=10000)


class ListLists(_Pagination):
    operation: Literal["list_lists"] = "list_lists"


class GetList(_ListID):
    operation: Literal["get_list"] = "get_list"


class CreateList(_ListBody):
    operation: Literal["create_list"] = "create_list"


class UpdateList(_ListBody, _ListID):
    operation: Literal["update_list"] = "update_list"


class ListContacts(_Input):
    """Read one provider page; returned links and metadata describe continuation."""
    operation: Literal["list_contacts"] = "list_contacts"


class GetContact(_ContactID):
    operation: Literal["get_contact"] = "get_contact"


class DeleteContact(_ContactID):
    """Permanently delete a contact from the account."""
    operation: Literal["delete_contact"] = "delete_contact"


class ListListContacts(_ListID):
    operation: Literal["list_list_contacts"] = "list_list_contacts"


class AddListContact(_ListID):
    """Create or add a contact to a list; consent must reflect the person's permission."""
    operation: Literal["add_list_contact"] = "add_list_contact"
    email: str = Field(..., min_length=3, max_length=254)
    first_name: str | None = Field(None, min_length=1, max_length=500)
    last_name: str | None = Field(None, min_length=1, max_length=500)
    phone: str | None = Field(None, min_length=1, max_length=50)
    email_consent: bool = Field(False, strict=True, description="Set true only with permission to receive email marketing.")
    tag_ids: list[Annotated[int, Field(ge=1)]] | None = Field(None, max_length=100)

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value


class RemoveListContact(_ListID, _ContactID):
    """Remove the contact from the selected list."""
    operation: Literal["remove_list_contact"] = "remove_list_contact"


class ListTags(_Input):
    operation: Literal["list_tags"] = "list_tags"


class GetTag(_TagID):
    operation: Literal["get_tag"] = "get_tag"


class CreateTag(_Name):
    operation: Literal["create_tag"] = "create_tag"


class UpdateTag(_Name, _TagID):
    operation: Literal["update_tag"] = "update_tag"


class DeleteTag(_TagID):
    operation: Literal["delete_tag"] = "delete_tag"


class ListContactTags(_ContactID):
    operation: Literal["list_contact_tags"] = "list_contact_tags"


class AddContactTags(_ContactID):
    operation: Literal["add_contact_tags"] = "add_contact_tags"
    tag_ids: list[Annotated[int, Field(ge=1)]] = Field(..., min_length=1, max_length=100)


class RemoveContactTag(_ContactID, _TagID):
    operation: Literal["remove_contact_tag"] = "remove_contact_tag"


class ListCustomFields(_Pagination):
    operation: Literal["list_custom_fields"] = "list_custom_fields"


class CreateCustomField(_Name):
    operation: Literal["create_custom_field"] = "create_custom_field"
    type: str = Field(..., min_length=1, max_length=100, description="Sendlane custom field type.")


class UpdateCustomField(_Name):
    operation: Literal["update_custom_field"] = "update_custom_field"
    custom_field_id: int = Field(..., ge=1)
    type: str | None = Field(None, min_length=1, max_length=100)


class ListCampaigns(_Input):
    operation: Literal["list_campaigns"] = "list_campaigns"


class GetCampaign(_Input):
    operation: Literal["get_campaign"] = "get_campaign"
    campaign_id: int = Field(..., ge=1)


class GetCampaignReport(_Input):
    operation: Literal["get_campaign_report"] = "get_campaign_report"
    campaign_id: int = Field(..., ge=1)


class ListSegments(_Input):
    operation: Literal["list_segments"] = "list_segments"


SendlaneConfig = Annotated[Union[
    ListLists, GetList, CreateList, UpdateList, ListContacts, GetContact,
    DeleteContact, ListListContacts, AddListContact, RemoveListContact,
    ListTags, GetTag, CreateTag, UpdateTag, DeleteTag, ListContactTags,
    AddContactTags, RemoveContactTag, ListCustomFields, CreateCustomField,
    UpdateCustomField, ListCampaigns, GetCampaign, GetCampaignReport, ListSegments,
], Field(discriminator="operation")]


class SendlaneFullConfig(NodeConfig[SendlaneConfig, SendlaneAPITokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


# Each entry maps exactly one node operation to one published v2 operation.
# Path fields never enter the JSON body. Only the two documented list endpoints
# accept page/limit; other reads preserve the provider's pagination envelope.
ROUTES = {
    "list_lists": ("GET", "/lists"),
    "get_list": ("GET", "/lists/{list_id}"),
    "create_list": ("POST", "/lists"),
    "update_list": ("PUT", "/lists/{list_id}"),
    "list_contacts": ("GET", "/contacts"),
    "get_contact": ("GET", "/contacts/{contact_id}"),
    "delete_contact": ("DELETE", "/contacts/{contact_id}"),
    "list_list_contacts": ("GET", "/lists/{list_id}/contacts"),
    "add_list_contact": ("POST", "/lists/{list_id}/contacts"),
    "remove_list_contact": ("DELETE", "/lists/{list_id}/contacts/{contact_id}"),
    "list_tags": ("GET", "/tags"),
    "get_tag": ("GET", "/tags/{tag_id}"),
    "create_tag": ("POST", "/tags"),
    "update_tag": ("PATCH", "/tags/{tag_id}"),
    "delete_tag": ("DELETE", "/tags/{tag_id}"),
    "list_contact_tags": ("GET", "/contacts/{contact_id}/tags"),
    "add_contact_tags": ("POST", "/contacts/{contact_id}/tags"),
    "remove_contact_tag": ("DELETE", "/contacts/{contact_id}/tags/{tag_id}"),
    "list_custom_fields": ("GET", "/custom-fields"),
    "create_custom_field": ("POST", "/custom-fields"),
    "update_custom_field": ("PATCH", "/custom-fields/{custom_field_id}"),
    "list_campaigns": ("GET", "/campaigns"),
    "get_campaign": ("GET", "/campaigns/{campaign_id}"),
    "get_campaign_report": ("GET", "/campaigns/{campaign_id}/report"),
    "list_segments": ("GET", "/segments"),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items()}
    return value


class SendlaneNode(WorkflowNode):
    integration_type = "automation-sendlane"
    connection_evidence = ConnectionEvidence(noun="Sendlane lists", operation="list_lists")

    @classmethod
    def get_config_model(cls):
        return SendlaneFullConfig

    async def execute(self, inputs):
        if not isinstance(self.config, SendlaneFullConfig) or not self.config.credentials:
            raise ValueError("Attach a Sendlane API token")
        config = self.config.config
        token = self.config.credentials.api_token
        method, template = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path_fields = re.findall(r"\{(\w+)\}", template)
        path = template.format(**{field: values.pop(field) for field in path_fields})
        kwargs = {}
        if method == "GET":
            if values:
                kwargs["params"] = values
        elif method in {"POST", "PUT", "PATCH"}:
            kwargs["json"] = {"contacts": [values]} if config.operation == "add_list_contact" else values
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
        if len(response.content) > 10_000_000:
            raise ValueError("Sendlane response exceeds the size limit")
        if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Expected a JSON response from Sendlane")
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Sendlane returned invalid JSON") from None
        if not isinstance(body, dict):
            raise ValueError("Sendlane returned an unexpected response envelope")
        if response.status_code >= 300 or body.get("error") or body.get("errors") or body.get("success") is False:
            message = body.get("message") or body.get("error") or "Sendlane rejected the request"
            return {"status": "error", "http_status": response.status_code, "error": _redact(message, token)}
        if response.status_code not in {200, 202} or "data" not in body:
            raise ValueError("Sendlane did not confirm the operation")
        return _redact({"status": "success", "operation": config.operation,
            "http_status": response.status_code, "accepted": response.status_code == 202,
            "data": body["data"], **{key: body[key] for key in ("links", "meta") if key in body}}, token)
