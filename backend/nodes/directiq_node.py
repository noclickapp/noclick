"""DirectIQ resource API v2: one published endpoint per operation.

API contracts: https://rest.directiq.com/{core,contacts}/swagger/v2/swagger.json.
List operations return one page, preserving has_more and next_page_token.
"""
from __future__ import annotations
from datetime import date
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.directiq.com"

class DirectIQAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="DirectIQ API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://rest.directiq.com/core/index.html",
        "x-credential-instructions": "Paste your DirectIQ API key. NoClick sends it in the X-API-Key header to api.directiq.com. Connecting reads your contact lists. List operations return one page; pass next_page_token to continue. Deleting a list starts a background deletion and may also delete contacts that belong to no other list."})
    credential_type: Literal["directiq_api_key"] = Field("directiq_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without a header prefix")
        return value

class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class ListContacts(Input):
    """List contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=100)
    page_token: str | None = Field(None)
    status: Literal['active', 'awaiting_activation', 'passive', 'manually_disabled', 'unsubscribed', 'spam_complaint', 'bounced'] | None = Field(None)
    email: str | None = Field(None)


class CountContacts(Input):
    """Count contacts."""
    operation: Literal["count_contacts"] = Field("count_contacts", json_schema_extra={"ui:hidden": True})
    created_from: date | None = Field(None)
    created_to: date | None = Field(None)


class UpdateContact(Input):
    """Update a contact."""
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)
    email: str | None = Field(None, max_length=100)
    first_name: str | None = Field(None, max_length=50)
    last_name: str | None = Field(None, max_length=50)
    status: Literal['active', 'awaiting_activation', 'passive', 'manually_disabled', 'unsubscribed', 'spam_complaint', 'bounced'] | None = Field(None)



class DeleteContact(Input):
    """Delete a contact."""
    operation: Literal["delete_contact"] = Field("delete_contact", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)


class ListContactActivity(Input):
    """List a contact's activity."""
    operation: Literal["list_contact_activity"] = Field("list_contact_activity", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)
    limit: int | None = Field(None, ge=1, le=100)
    page_token: str | None = Field(None)
    type: Literal['created', 'updated', 'deleted', 'added_to_list', 'removed_from_list', 'added_to_tag', 'removed_from_tag', 'sent_email', 'opened_email', 'clicked_link', 'soft_bounced', 'hard_bounced', 'activated', 'passive', 'awaiting_activation', 'manually_disabled', 'unsubscribed', 'spam_complaint'] | None = Field(None)
    occurred_from: date | None = Field(None)
    occurred_to: date | None = Field(None)


class AddContactNote(Input):
    """Add a note."""
    operation: Literal["add_contact_note"] = Field("add_contact_note", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)
    note: str = Field(..., min_length=1, max_length=500)


class UpdateContactNote(Input):
    """Update a note."""
    operation: Literal["update_contact_note"] = Field("update_contact_note", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)
    note_id: int = Field(..., ge=1)
    note: str = Field(..., min_length=1, max_length=500)


class DeleteContactNote(Input):
    """Delete a note."""
    operation: Literal["delete_contact_note"] = Field("delete_contact_note", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)
    note_id: int = Field(..., ge=1)


class ListLists(Input):
    """List lists."""
    operation: Literal["list_lists"] = Field("list_lists", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=100)
    page_token: str | None = Field(None)


class CreateList(Input):
    """Create a list."""
    operation: Literal["create_list"] = Field("create_list", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=200)


class GetList(Input):
    """Retrieve a list."""
    operation: Literal["get_list"] = Field("get_list", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)


class DeleteList(Input):
    """Delete a list. Returns an acknowledgement; deletion completes in the background."""
    operation: Literal["delete_list"] = Field("delete_list", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)


class ListListContacts(Input):
    """List the contacts of a list."""
    operation: Literal["list_list_contacts"] = Field("list_list_contacts", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)
    limit: int | None = Field(None, ge=1, le=100)
    page_token: str | None = Field(None)
    status: Literal['active', 'awaiting_activation', 'passive', 'manually_disabled', 'unsubscribed', 'spam_complaint', 'bounced'] | None = Field(None)


class ImportContacts(Input):
    """Import one contact into a list, optionally updating existing names.

    Use workflow iteration for multiple contacts. The API receives a singleton contacts array.
    """
    operation: Literal["import_contacts"] = Field("import_contacts", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description="Destination contact list ID.")
    email: str = Field(..., min_length=1, max_length=100)
    first_name: str | None = Field(None, max_length=50)
    last_name: str | None = Field(None, max_length=50)
    update_existing: bool = Field(False, description="Update names for an existing contact; otherwise only add it to the list.")


class ListCampaigns(Input):
    """List campaigns."""
    operation: Literal["list_campaigns"] = Field("list_campaigns", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=100)
    page_token: str | None = Field(None)


class GetCampaign(Input):
    """Retrieve a campaign."""
    operation: Literal["get_campaign"] = Field("get_campaign", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)


class ListCampaignReport(Input):
    """List a campaign report."""
    operation: Literal["list_campaign_report"] = Field("list_campaign_report", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)
    type: Literal['recipients', 'opens', 'clicks', 'bounces', 'unsubscribes', 'spam_complaints'] = Field(..., description='What `GET /v2/campaigns/{id}/reports` lists.')
    limit: int | None = Field(None, ge=1, le=100)
    page_token: str | None = Field(None)
    email: str | None = Field(None)
    link: str | None = Field(None)
    domain: str | None = Field(None)
    bounce_type: Literal['hard', 'soft'] | None = Field(None)


class GetCampaignBreakdown(Input):
    """Count a campaign's opens or clicks."""
    operation: Literal["get_campaign_breakdown"] = Field("get_campaign_breakdown", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)
    by: Literal['domain', 'link', 'mail_client', 'device', 'country'] = Field(..., description='The detail `GET /v2/campaigns/{id}/reports/breakdown` groups by.')
    type: Literal['opens', 'clicks'] | None = Field(None, description='What `GET /v2/campaigns/{id}/reports/breakdown` counts.')
    limit: int | None = Field(None, ge=1, le=100)


class CreateTag(Input):
    """Create a tag."""
    operation: Literal["create_tag"] = Field("create_tag", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=50)


class ListTemplates(Input):
    """List templates."""
    operation: Literal["list_templates"] = Field("list_templates", json_schema_extra={"ui:hidden": True})
    limit: int | None = Field(None, ge=1, le=100)
    page_token: str | None = Field(None)


class CreateTemplate(Input):
    """Create a template."""
    operation: Literal["create_template"] = Field("create_template", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=200)
    subject: str = Field(..., min_length=1, max_length=300)
    html: str = Field(..., min_length=1, description='The HTML body, as made in the HTML editor.')


class GetTemplate(Input):
    """Retrieve a template."""
    operation: Literal["get_template"] = Field("get_template", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)


class AddTemplateTag(Input):
    """Add a tag to a template."""
    operation: Literal["add_template_tag"] = Field("add_template_tag", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=50, description="The tag's name; created when the account has no tag with this name.")


Operation = Annotated[Union[ListContacts, CountContacts, UpdateContact, DeleteContact, ListContactActivity, AddContactNote, UpdateContactNote, DeleteContactNote, ListLists, CreateList, GetList, DeleteList, ListListContacts, ImportContacts, ListCampaigns, GetCampaign, ListCampaignReport, GetCampaignBreakdown, CreateTag, ListTemplates, CreateTemplate, GetTemplate, AddTemplateTag], Field(discriminator="operation")]

class DirectIQConfig(NodeConfig[Operation, DirectIQAPIKeyCredential]):
    pass

ROUTES = {
    'list_contacts': ('GET', '/v2/contacts', ['limit', 'page_token', 'status', 'email'], [], [200]),
    'count_contacts': ('GET', '/v2/contacts/count', ['created_from', 'created_to'], [], [200]),
    'update_contact': ('PATCH', '/v2/contacts/{id}', ['id'], ['email', 'first_name', 'last_name', 'status'], [200]),
    'delete_contact': ('DELETE', '/v2/contacts/{id}', ['id'], [], [204]),
    'list_contact_activity': ('GET', '/v2/contacts/{id}/activity', ['id', 'limit', 'page_token', 'type', 'occurred_from', 'occurred_to'], [], [200]),
    'add_contact_note': ('POST', '/v2/contacts/{id}/notes', ['id'], ['note'], [201]),
    'update_contact_note': ('PATCH', '/v2/contacts/{id}/notes/{note_id}', ['id', 'note_id'], ['note'], [200]),
    'delete_contact_note': ('DELETE', '/v2/contacts/{id}/notes/{note_id}', ['id', 'note_id'], [], [204]),
    'list_lists': ('GET', '/v2/lists', ['limit', 'page_token'], [], [200]),
    'create_list': ('POST', '/v2/lists', [], ['name'], [201, 200]),
    'get_list': ('GET', '/v2/lists/{id}', ['id'], [], [200]),
    'delete_list': ('DELETE', '/v2/lists/{id}', ['id'], [], [202]),
    'list_list_contacts': ('GET', '/v2/lists/{id}/contacts', ['id', 'limit', 'page_token', 'status'], [], [200]),
    'import_contacts': ('POST', '/v2/lists/{id}/import', ['id'], ['contacts', 'tags', 'update_existing'], [200]),
    'list_campaigns': ('GET', '/v2/campaigns', ['limit', 'page_token'], [], [200]),
    'get_campaign': ('GET', '/v2/campaigns/{id}', ['id'], [], [200]),
    'list_campaign_report': ('GET', '/v2/campaigns/{id}/reports', ['id', 'type', 'limit', 'page_token', 'email', 'link', 'domain', 'bounce_type'], [], [200]),
    'get_campaign_breakdown': ('GET', '/v2/campaigns/{id}/reports/breakdown', ['id', 'by', 'type', 'limit'], [], [200]),
    'create_tag': ('POST', '/v2/tags', [], ['name'], [201, 200]),
    'list_templates': ('GET', '/v2/templates', ['limit', 'page_token'], [], [200]),
    'create_template': ('POST', '/v2/templates', [], ['name', 'subject', 'html'], [201]),
    'get_template': ('GET', '/v2/templates/{id}', ['id'], [], [200]),
    'add_template_tag': ('POST', '/v2/templates/{id}/tags', ['id'], ['name'], [200]),
}


def request_parts(op):
    method, path, parameters, fields, accepted = ROUTES[op.operation]
    values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
    query = {}
    for name in parameters:
        if "{" + name + "}" in path:
            path = path.replace("{" + name + "}", str(values[name]))
        elif name in values:
            query[name] = values[name]
    body = None
    if fields:
        body = {}
        for name in fields:
            if name in values:
                body[name] = values[name]
    if op.operation == "import_contacts":
        body = {"contacts": [{key: values[key] for key in ("email", "first_name", "last_name") if key in values}],
            "update_existing": op.update_existing}
    return method, path, query, body, accepted

class DirectIQNode(WorkflowNode):
    integration_type = "automation-directiq"
    connection_evidence = ConnectionEvidence(operation="list_lists", noun="DirectIQ contact lists")

    @classmethod
    def get_config_model(cls):
        return DirectIQConfig

    async def execute(self, inputs):
        if self.config.credentials is None:
            raise ValueError("Connect a DirectIQ API key")
        op = self.config.config
        method, path, params, body, accepted = request_parts(op)
        token = self.config.credentials.api_key
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, params=params or None, json=body,
                headers={"X-API-Key": token, "Accept": "application/json"})
        if response.status_code not in accepted:
            message = "DirectIQ request failed"
            try:
                problem = response.json()
                if isinstance(problem, dict):
                    message = str(problem.get("detail") or problem.get("title") or message)
            except ValueError:
                pass
            output = {"status": "error", "http_status": response.status_code,
                "message": message.replace(token, "[redacted]")}
        elif response.status_code in {202, 204} and not response.content:
            output = {"status": "success", "operation": op.operation, "http_status": response.status_code,
                "acknowledged": True, "completed": response.status_code == 204}
        else:
            try:
                payload = response.json()
            except (ValueError, UnicodeError):
                raise ValueError("DirectIQ returned a non-JSON response") from None
            if not isinstance(payload, dict) or not payload or "title" in payload and "status" in payload:
                raise ValueError("DirectIQ returned an unexpected response")
            if method == "GET" and "limit" in ROUTES[op.operation][2]:
                if not isinstance(payload.get("data"), (list, type(None))) or "data" not in payload or not isinstance(payload.get("has_more"), bool):
                    raise ValueError("DirectIQ did not return a resource page")
            output = {"status": "success", "operation": op.operation, "http_status": response.status_code, "data": payload}
        await self.emit(output)
        return output
