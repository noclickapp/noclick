"""Snitcher public API v1.0.0. Contract: https://app.snitcher.com/api/docs.

Each action makes one request. Paginated responses retain provider metadata;
contact email reveals consume Snitcher credits and are never retried here.
"""
from __future__ import annotations

from datetime import date as Date
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class SnitcherTokenCredential(BaseModel):
    model_config = ConfigDict(title="Snitcher Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.snitcher.com/api/docs",
            "x-credential-instructions": "Paste your Snitcher personal access token (PAT). NoClick sends it as a Bearer token to api.snitcher.com. Your profile is read to verify the connection.",
        })
    credential_type: Literal["snitcher_token"] = Field("snitcher_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=8192, title="Personal access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the token, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def documented_constraints(self):
        for name in self.model_fields_set:
            value = getattr(self, name)
            if value is None:
                continue
            if name in {"workspaceUuid", "organisationUuid", "contactUuid", "uuid", "organisation_uuid", "visitor_uuid", "segmentUuid"}:
                try:
                    UUID(value)
                except (ValueError, TypeError, AttributeError):
                    raise ValueError(f"{name} must be a UUID") from None
            if name in {"date", "date_from", "date_to"}:
                try:
                    Date.fromisoformat(value)
                    if len(value) != 10:
                        raise ValueError("Expected YYYY-MM-DD")
                except (ValueError, TypeError):
                    raise ValueError(f"{name} must be YYYY-MM-DD") from None
            if name == "key" and (not value or value in {".", ".."} or any(c in value for c in "/\\?#")):
                raise ValueError("Use one custom field key")
        start, end, day = (getattr(self, k, None) for k in ("date_from", "date_to", "date"))
        if day and (start or end):
            raise ValueError("Use date or date_from/date_to, not both")
        if start and end and start > end:
            raise ValueError("date_to must be on or after date_from")
        if self.operation == "list_sessions" and not (day or start):
            raise ValueError("Provide date or date_from for workspace sessions")
        if hasattr(self, "page") and self.page * self.size > 25000:
            raise ValueError("page times size must not exceed 25000; narrow the date range")
        if self.operation == "list_contacts" and not (self.domain or self.organisation_uuid):
            raise ValueError("Provide a domain or organisation_uuid for contact search")
        if hasattr(self, "custom_fields"):
            fields = self.custom_fields
            if not 1 <= len(fields) <= 50 or any(v is None or v == "" or v == [] for v in fields.values()):
                raise ValueError("Supply 1 to 50 non-empty custom field values; use Clear to remove a value")
        return self


class SnitcherFieldRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str
    config: dict[str, Any] | None = None


class SnitcherFieldOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(..., max_length=255)
    label: str = Field(..., max_length=255)
    color: str | None = Field(None, max_length=50)


class SnitcherGetContactCreditsConfig(_Input):
    """Get the workspace's contact reveal credit balance."""
    operation: Literal["get_contact_credits"] = Field("get_contact_credits", json_schema_extra={"ui:hidden": True})
    workspaceUuid: str = Field(..., description='UUID of the workspace')


class SnitcherListCustomFieldsConfig(_Input):
    """List custom field definitions."""
    operation: Literal["list_custom_fields"] = Field("list_custom_fields", json_schema_extra={"ui:hidden": True})
    workspaceUuid: str = Field(..., description='The UUID of the workspace')


class SnitcherCreateCustomFieldConfig(_Input):
    """Create a custom field definition."""
    operation: Literal["create_custom_field"] = Field("create_custom_field", json_schema_extra={"ui:hidden": True})
    workspaceUuid: str = Field(..., description='The UUID of the workspace')
    name: str = Field(..., max_length=255, description='The human-readable name of the field')
    type: str = Field(..., description='The data type of the field')
    key: str | None = Field(None, max_length=255, description='The machine-readable key. Must start with a lowercase letter and contain only lowercase letters, numbers, and underscores. Generated from the name when omitted.')
    description: str | None = Field(None, max_length=1000)
    visible_in_spotter: StrictBool | None = Field(None, description="Expose this field's values in the Spotter API response. Off by default: exposed values become readable on your website by any script that can access the Spotter response.")
    field_rules: list[SnitcherFieldRule] | None = Field(None)
    options: list[SnitcherFieldOption] | None = Field(None)


class SnitcherGetCustomFieldConfig(_Input):
    """Get a custom field definition."""
    operation: Literal["get_custom_field"] = Field("get_custom_field", json_schema_extra={"ui:hidden": True})
    workspaceUuid: str = Field(..., description='The UUID of the workspace')
    key: str = Field(..., description='The key of the custom field')


class SnitcherDeleteCustomFieldConfig(_Input):
    """Delete a custom field definition."""
    operation: Literal["delete_custom_field"] = Field("delete_custom_field", json_schema_extra={"ui:hidden": True})
    workspaceUuid: str = Field(..., description='The UUID of the workspace')
    key: str = Field(..., description='The key of the custom field')


class SnitcherUpdateCustomFieldConfig(_Input):
    """Update a custom field definition."""
    operation: Literal["update_custom_field"] = Field("update_custom_field", json_schema_extra={"ui:hidden": True})
    workspaceUuid: str = Field(..., description='The UUID of the workspace')
    key: str = Field(..., description='The key of the custom field')
    name: str | None = Field(None, max_length=255, description='The human-readable name of the field')
    description: str | None = Field(None, max_length=1000)
    visible_in_spotter: StrictBool | None = Field(None, description="Expose this field's values in the Spotter API response. Omitted or null leaves the current setting unchanged; exposed values become readable on your website by any script that can access the Spotter response.")
    field_rules: list[SnitcherFieldRule] | None = Field(None)
    options: list[SnitcherFieldOption] | None = Field(None)


class SnitcherListContactsConfig(_Input):
    """Get contacts for an organisation."""
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    workspaceUuid: str = Field(..., description='The UUID of the workspace')
    domain: str | None = Field(None, description='Either organisation_uuid or domain must be provided')
    organisation_uuid: str | None = Field(None, description='Either organisation_uuid or domain must be provided')
    page: StrictInt = Field(1, ge=1, description='The page number for pagination. page × size may not exceed 25,000 rows; narrow the listing with date_from and date_to instead of paging deeper.')
    size: StrictInt = Field(100, ge=1, le=1000, description='The number of organisations per page (1-1000)')


class SnitcherRevealContactEmailConfig(_Input):
    """Reveal an email for an organisation contact."""
    operation: Literal["reveal_contact_email"] = Field("reveal_contact_email", json_schema_extra={"ui:hidden": True})
    workspaceUuid: str = Field(..., description='The UUID of the workspace')
    contactUuid: str = Field(..., description='The UUID of the contact')


class SnitcherListOrganisationsConfig(_Input):
    """List organisations."""
    operation: Literal["list_organisations"] = Field("list_organisations", json_schema_extra={"ui:hidden": True})
    workspaceUuid: str = Field(..., description='The UUID of the workspace')
    segmentUuid: str | None = Field(None, description='Optional segment UUID for filtering organisations')
    page: StrictInt = Field(1, ge=1, description='The page number for pagination. page × size may not exceed 25,000 rows; narrow the listing with date_from and date_to instead of paging deeper.')
    size: StrictInt = Field(100, ge=1, le=1000, description='The number of organisations per page (1-1000)')
    date: str | None = Field(None, description='The specific date to filter organisations that visited that day.')
    date_from: str | None = Field(None, description='The start date for filtering organisations based on visits. Can only be used if `date` is not provided.')
    date_to: str | None = Field(None, description='The end date for filtering organisations based on visits. Can only be used if `date` is not provided.')
    name: str | None = Field(None, description='Filters organisations where the name contains the given string.')


class SnitcherGetOrganisationConfig(_Input):
    """Get an organisation."""
    operation: Literal["get_organisation"] = Field("get_organisation", json_schema_extra={"ui:hidden": True})
    workspaceUuid: str = Field(..., description='The UUID of the workspace')
    organisationUuid: str = Field(..., description='The UUID of the organisation')


class SnitcherAddOrganisationTagConfig(_Input):
    """Add a tag to an organisation."""
    operation: Literal["add_organisation_tag"] = Field("add_organisation_tag", json_schema_extra={"ui:hidden": True})
    workspaceUuid: str = Field(..., description='The UUID of the workspace')
    organisationUuid: str = Field(..., description='The UUID of the organisation')
    tag_name: str = Field(..., min_length=1, description='The name of the tag')


class SnitcherRemoveOrganisationTagConfig(_Input):
    """Remove a tag from an organisation."""
    operation: Literal["remove_organisation_tag"] = Field("remove_organisation_tag", json_schema_extra={"ui:hidden": True})
    workspaceUuid: str = Field(..., description='The UUID of the workspace')
    organisationUuid: str = Field(..., description='The UUID of the organisation')
    tag_name: str = Field(..., min_length=1, description='The name of the tag')


class SnitcherListOrganisationCustomFieldsConfig(_Input):
    """List custom field values for an organisation."""
    operation: Literal["list_organisation_custom_fields"] = Field("list_organisation_custom_fields", json_schema_extra={"ui:hidden": True})
    workspaceUuid: str = Field(..., description='The UUID of the workspace')
    organisationUuid: str = Field(..., description='The UUID of the organisation')


class SnitcherSetOrganisationCustomFieldsConfig(_Input):
    """Set multiple custom field values on an organisation."""
    operation: Literal["set_organisation_custom_fields"] = Field("set_organisation_custom_fields", json_schema_extra={"ui:hidden": True})
    workspaceUuid: str = Field(..., description='The UUID of the workspace')
    organisationUuid: str = Field(..., description='The UUID of the organisation')
    custom_fields: dict[str, Any] = Field(..., description='Map of field key to value (at most 50 keys per request). Unknown keys are created automatically, with their type inferred from the value. Every value must be non-empty — sending an empty array does not clear a multi-select; use the DELETE custom-fields/{key} endpoint to remove a value.')


class SnitcherSetOrganisationCustomFieldConfig(_Input):
    """Set a custom field value on an organisation."""
    operation: Literal["set_organisation_custom_field"] = Field("set_organisation_custom_field", json_schema_extra={"ui:hidden": True})
    workspaceUuid: str = Field(..., description='The UUID of the workspace')
    organisationUuid: str = Field(..., description='The UUID of the organisation')
    key: str = Field(..., description='The key of the custom field')
    value: Any = Field(..., description='The value to set for the field')


class SnitcherClearOrganisationCustomFieldConfig(_Input):
    """Clear a custom field value on an organisation."""
    operation: Literal["clear_organisation_custom_field"] = Field("clear_organisation_custom_field", json_schema_extra={"ui:hidden": True})
    workspaceUuid: str = Field(..., description='The UUID of the workspace')
    organisationUuid: str = Field(..., description='The UUID of the organisation')
    key: str = Field(..., description='The key of the custom field')


class SnitcherListSegmentsConfig(_Input):
    """List all segments in a workspace."""
    operation: Literal["list_segments"] = Field("list_segments", json_schema_extra={"ui:hidden": True})
    workspaceUuid: str = Field(..., description='The UUID of the workspace')


class SnitcherListSessionsConfig(_Input):
    """Overview of the sessions in a date range."""
    operation: Literal["list_sessions"] = Field("list_sessions", json_schema_extra={"ui:hidden": True})
    workspaceUuid: str = Field(..., description='The UUID of the workspace')
    segmentUuid: str | None = Field(None, description='Only include sessions matching this segment UUID')
    date: str | None = Field(None, description='The specific date to filter sessions. Cannot be used together with date_from/date_to. Either `date` or `date_from` must be provided.')
    date_from: str | None = Field(None, description='Start date for filtering sessions (inclusive). Required unless `date` is provided.')
    date_to: str | None = Field(None, description='End date for filtering sessions (inclusive). Defaults to the end of today when omitted.')
    url: str | None = Field(None, description='Filter sessions where the visited URL contains the given string.')
    referrer: str | None = Field(None, description='Filter sessions where the referrer contains the given string.')
    visitor_uuid: str | None = Field(None, description='Only include sessions of this visitor (client) ID — the `visitor_uuid` returned on every session, and the value the tracker sends as `anonymous_id`. Lets a client-side ID minted at conversion time be resolved back to the sessions, and therefore the organisation, it belongs to.')
    page: StrictInt = Field(1, ge=1, description='The page number for pagination. page × size may not exceed 25,000 rows; narrow the listing with date_from and date_to instead of paging deeper.')
    size: StrictInt = Field(100, ge=1, le=1000, description='Number of sessions per page (1-1000).')


class SnitcherListOrganisationSessionsConfig(_Input):
    """Overview of the sessions of an organisation."""
    operation: Literal["list_organisation_sessions"] = Field("list_organisation_sessions", json_schema_extra={"ui:hidden": True})
    workspaceUuid: str = Field(..., description='The UUID of the workspace')
    organisationUuid: str = Field(..., description='The UUID of the organisation')
    page: StrictInt = Field(1, ge=1, description='The page number for pagination. page × size may not exceed 25,000 rows; narrow the listing with date_from and date_to instead of paging deeper.')
    size: StrictInt = Field(100, ge=1, le=1000, description='The number of sessions per page (1-1000)')
    date: str | None = Field(None, description='The specific date to filter sessions.')
    date_from: str | None = Field(None, description='The start date for filtering sessions. Can only be used if `date` is not provided.')
    date_to: str | None = Field(None, description='The end date for filtering sessions. Can only be used if `date` is not provided.')
    url: str | None = Field(None, description='Filters sessions where the visited URL contains the given string.')
    referrer: str | None = Field(None, description='Filters sessions where the referrer contains the given string.')
    visitor_uuid: str | None = Field(None, description='Only include sessions of this visitor (client) ID — the `visitor_uuid` returned on every session, and the value the tracker sends as `anonymous_id`. Lets a client-side ID minted at conversion time be resolved back to the sessions, and therefore the organisation, it belongs to.')


class SnitcherGetProfileConfig(_Input):
    """Get the authenticated user's profile."""
    operation: Literal["get_profile"] = Field("get_profile", json_schema_extra={"ui:hidden": True})


class SnitcherListWorkspacesConfig(_Input):
    """Get the user's workspaces."""
    operation: Literal["list_workspaces"] = Field("list_workspaces", json_schema_extra={"ui:hidden": True})
    page: StrictInt = Field(1, ge=1, description='The page number for pagination. page × size may not exceed 25,000 rows; narrow the listing with date_from and date_to instead of paging deeper.')
    size: StrictInt = Field(100, ge=1, le=1000, description='The number of organisations per page (1-1000)')


class SnitcherCreateWorkspaceConfig(_Input):
    """Create a new workspace."""
    operation: Literal["create_workspace"] = Field("create_workspace", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1)


class SnitcherGetWorkspaceConfig(_Input):
    """Get details of a specific workspace."""
    operation: Literal["get_workspace"] = Field("get_workspace", json_schema_extra={"ui:hidden": True})
    uuid: str = Field(..., description='UUID of the workspace')


class SnitcherUpdateWorkspaceConfig(_Input):
    """Update workspace details."""
    operation: Literal["update_workspace"] = Field("update_workspace", json_schema_extra={"ui:hidden": True})
    uuid: str = Field(..., description='UUID of the workspace')
    usage_limit: StrictInt = Field(...)


class SnitcherCreateWorkspaceTagConfig(_Input):
    """Create a new tag for a workspace."""
    operation: Literal["create_workspace_tag"] = Field("create_workspace_tag", json_schema_extra={"ui:hidden": True})
    uuid: str = Field(..., description='UUID of the workspace')
    tag_name: str = Field(..., min_length=1, description='The name of the tag')


SnitcherConfig = Annotated[Union[
    SnitcherGetContactCreditsConfig,
    SnitcherListCustomFieldsConfig,
    SnitcherCreateCustomFieldConfig,
    SnitcherGetCustomFieldConfig,
    SnitcherDeleteCustomFieldConfig,
    SnitcherUpdateCustomFieldConfig,
    SnitcherListContactsConfig,
    SnitcherRevealContactEmailConfig,
    SnitcherListOrganisationsConfig,
    SnitcherGetOrganisationConfig,
    SnitcherAddOrganisationTagConfig,
    SnitcherRemoveOrganisationTagConfig,
    SnitcherListOrganisationCustomFieldsConfig,
    SnitcherSetOrganisationCustomFieldsConfig,
    SnitcherSetOrganisationCustomFieldConfig,
    SnitcherClearOrganisationCustomFieldConfig,
    SnitcherListSegmentsConfig,
    SnitcherListSessionsConfig,
    SnitcherListOrganisationSessionsConfig,
    SnitcherGetProfileConfig,
    SnitcherListWorkspacesConfig,
    SnitcherCreateWorkspaceConfig,
    SnitcherGetWorkspaceConfig,
    SnitcherUpdateWorkspaceConfig,
    SnitcherCreateWorkspaceTagConfig
], Field(discriminator="operation")]


class SnitcherFullConfig(NodeConfig[SnitcherConfig, SnitcherTokenCredential]):
    pass


# method, path, query fields, JSON body fields; no user-provided routes.
ROUTES = {'get_contact_credits': ('GET', '/v1/workspaces/{workspaceUuid}/contact-credits', [], []),
 'list_custom_fields': ('GET', '/v1/workspaces/{workspaceUuid}/custom-fields', [], []),
 'create_custom_field': ('POST',
                         '/v1/workspaces/{workspaceUuid}/custom-fields',
                         [],
                         ['name',
                          'type',
                          'key',
                          'description',
                          'visible_in_spotter',
                          'field_rules',
                          'options']),
 'get_custom_field': ('GET', '/v1/workspaces/{workspaceUuid}/custom-fields/{key}', [], []),
 'delete_custom_field': ('DELETE', '/v1/workspaces/{workspaceUuid}/custom-fields/{key}', [], []),
 'update_custom_field': ('PATCH',
                         '/v1/workspaces/{workspaceUuid}/custom-fields/{key}',
                         [],
                         ['name', 'description', 'visible_in_spotter', 'field_rules', 'options']),
 'list_contacts': ('GET',
                   '/v1/workspaces/{workspaceUuid}/contacts',
                   ['domain', 'organisation_uuid', 'page', 'size'],
                   []),
 'reveal_contact_email': ('PUT',
                          '/v1/workspaces/{workspaceUuid}/contacts/{contactUuid}/reveal-email',
                          [],
                          []),
 'list_organisations': ('GET',
                        '/v1/workspaces/{workspaceUuid}/organisations',
                        ['segmentUuid', 'page', 'size', 'date', 'date_from', 'date_to', 'name'],
                        []),
 'get_organisation': ('GET', '/v1/workspaces/{workspaceUuid}/organisations/{organisationUuid}', [], []),
 'add_organisation_tag': ('POST',
                          '/v1/workspaces/{workspaceUuid}/organisations/{organisationUuid}/tags',
                          [],
                          ['tag_name']),
 'remove_organisation_tag': ('DELETE',
                             '/v1/workspaces/{workspaceUuid}/organisations/{organisationUuid}/tags',
                             [],
                             ['tag_name']),
 'list_organisation_custom_fields': ('GET',
                                     '/v1/workspaces/{workspaceUuid}/organisations/{organisationUuid}/custom-fields',
                                     [],
                                     []),
 'set_organisation_custom_fields': ('PATCH',
                                    '/v1/workspaces/{workspaceUuid}/organisations/{organisationUuid}/custom-fields',
                                    [],
                                    ['custom_fields']),
 'set_organisation_custom_field': ('PUT',
                                   '/v1/workspaces/{workspaceUuid}/organisations/{organisationUuid}/custom-fields/{key}',
                                   [],
                                   ['value']),
 'clear_organisation_custom_field': ('DELETE',
                                     '/v1/workspaces/{workspaceUuid}/organisations/{organisationUuid}/custom-fields/{key}',
                                     [],
                                     []),
 'list_segments': ('GET', '/v1/workspaces/{workspaceUuid}/segments', [], []),
 'list_sessions': ('GET',
                   '/v1/workspaces/{workspaceUuid}/sessions',
                   ['segmentUuid',
                    'date',
                    'date_from',
                    'date_to',
                    'url',
                    'referrer',
                    'visitor_uuid',
                    'page',
                    'size'],
                   []),
 'list_organisation_sessions': ('GET',
                                '/v1/workspaces/{workspaceUuid}/organisations/{organisationUuid}/sessions',
                                ['page',
                                 'size',
                                 'date',
                                 'date_from',
                                 'date_to',
                                 'url',
                                 'referrer',
                                 'visitor_uuid'],
                                []),
 'get_profile': ('GET', '/v1/me', [], []),
 'list_workspaces': ('GET', '/v1/workspaces', ['page', 'size'], []),
 'create_workspace': ('POST', '/v1/workspaces', [], ['url']),
 'get_workspace': ('GET', '/v1/workspaces/{uuid}', [], []),
 'update_workspace': ('PATCH', '/v1/workspaces/{uuid}', [], ['usage_limit']),
 'create_workspace_tag': ('POST', '/v1/workspaces/{uuid}/tags', [], ['tag_name'])}


class SnitcherNode(WorkflowNode):
    integration_type = "automation-snitcher"
    connection_evidence = ConnectionEvidence(noun="Snitcher profile", identity_operation="get_profile")

    @classmethod
    def get_config_model(cls):
        return SnitcherFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Snitcher personal access token")
        op = self.config.config
        method, path, query_fields, body_fields = ROUTES[op.operation]
        values = op.model_dump(exclude_unset=True)
        for key in ("workspaceUuid", "organisationUuid", "contactUuid", "uuid", "key"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(getattr(op, key), safe=""))
        params = {key: getattr(op, key) for key in query_fields if getattr(op, key) is not None}
        body = {key: values[key] for key in body_fields if key in values}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, "https://api.snitcher.com" + path,
                    headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"},
                    params=params, **({"json": body} if body_fields else {}))
            if not 200 <= response.status_code < 300:
                message = "Snitcher request failed"
                try:
                    error = response.json()
                    if isinstance(error, dict) and isinstance(error.get("message"), str):
                        message = error["message"]
                except ValueError:
                    pass
                return {"status": "error", "http_status": response.status_code,
                    "error": message.replace(credential.api_token, "[redacted]")[:2000]}
            if response.status_code == 204:
                return {"status": "success", "operation": op.operation, "deleted": True}
            payload = response.json()
            if not isinstance(payload, (dict, list)):
                raise ValueError("Snitcher returned an unexpected JSON response")
            if isinstance(payload, dict) and (payload.get("success") is False or payload.get("errors")):
                message = payload.get("message", "Snitcher reported an error")
                return {"status": "error", "error": str(message).replace(credential.api_token, "[redacted]")[:2000]}
            # Preserve all documented envelopes, bare arrays and bare custom-field values.
            result = {**payload} if isinstance(payload, dict) else {"data": payload}
            result.update(status="success", operation=op.operation)
            if isinstance(result.get("current_page"), int) and isinstance(result.get("last_page"), int):
                more = result["current_page"] < result["last_page"]
                result.update(has_more=more, next_page=result["current_page"] + 1 if more else None)
            return result
        except httpx.HTTPError:
            return {"status": "error", "error": "Snitcher could not be reached; retry the operation"}
        except ValueError:
            return {"status": "error", "error": "Snitcher returned an invalid JSON response"}
