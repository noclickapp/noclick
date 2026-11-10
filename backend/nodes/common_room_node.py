"""Common Room API v2. Contract: https://api.commonroom.io/docs/api-v2.json (2.0.0)."""
from __future__ import annotations
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictFloat, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE = "https://api.commonroom.io/api/v2"

class CommonRoomAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Common Room API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://app.commonroom.io/",
            "x-credential-instructions": "In Common Room, open Settings → API tokens and create a New Token as a room Admin. Paste the token here. Enable read/write scopes for the actions you use; listing segments verifies the connection."})
    credential_type: Literal["common_room_api_token"] = Field("common_room_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, title="API token", json_schema_extra={"ui:widget": "password"})

class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore")

class StringFieldValue(BaseModel):
    type: Literal["string"] = "string"
    value: str

class URLFieldValue(BaseModel):
    type: Literal["url"] = "url"
    value: str = Field(..., pattern=r"^https?://[^\s]+$")

class IntFieldValue(BaseModel):
    type: Literal["int"] = "int"
    value: StrictInt

class NumberFieldValue(BaseModel):
    type: Literal["number"] = "number"
    value: Union[StrictInt, StrictFloat]

class DateFieldValue(BaseModel):
    type: Literal["date"] = "date"
    value: AwareDatetime

class BooleanFieldValue(BaseModel):
    type: Literal["boolean"] = "boolean"
    value: StrictBool

class CustomFieldUpdate(BaseModel):
    customFieldId: str = Field(..., pattern=r"^cf_[0-9]+$")
    customFieldValue: Annotated[Union[StringFieldValue, URLFieldValue, IntFieldValue, NumberFieldValue, DateFieldValue, BooleanFieldValue], Field(discriminator="type")]

class _Bulk(_Input):
    segmentId: Optional[str] = Field(None, pattern=r"^s_[0-9]+$")
    tagIdsToAdd: Optional[list[Annotated[str, Field(pattern=r"^l_[0-9]+$")]]] = Field(None, max_length=25)
    tagIdsToRemove: Optional[list[Annotated[str, Field(pattern=r"^l_[0-9]+$")]]] = Field(None, max_length=25)
    customFields: Optional[list[CustomFieldUpdate]] = Field(None, min_length=1)

    @model_validator(mode="after")
    def requires_change(self):
        if not any([self.segmentId, self.tagIdsToAdd, self.tagIdsToRemove, self.customFields]):
            raise ValueError("Provide a segment, tags to add/remove, or custom field updates")
        return self

class CommonRoomListContactsConfig(_Input):
    """List contacts."""
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Contacts", json_schema_extra={"ui:hidden": True})
    limit: int = Field(50, ge=1, le=1000, description='The maximum number of contacts to return per page')
    cursor: Optional[str] = Field(None, description='Pagination cursor from a previous response')
    sort: str = Field('id', description='Field to sort results by. One of: `id`, `latest_activity`, `name`,')
    direction: Literal['asc', 'desc'] = Field('asc', description='Sort direction')
    cols: Optional[str] = Field(None, description='Comma-separated list of additional columns to include in the response.')
    organizationId: Optional[str] = Field(None, description='Filter contacts by prefixed organization ID (format `o_<number>`)')
    segmentId: Optional[str] = Field(None, description='Filter contacts by segment ID (e.g. s_123456)')


class CommonRoomGetContactConfig(_Input):
    """Get a contact by ID."""
    operation: Literal["get_contact"] = Field("get_contact", title="Get Contact", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., pattern=r"^c_[0-9]+$", description='The prefixed contact ID (format `c_<number>`)')
    cols: Optional[str] = Field(None, description='Comma-separated list of additional columns to include in the response.')


class CommonRoomListOrganizationsConfig(_Input):
    """List organizations."""
    operation: Literal["list_organizations"] = Field("list_organizations", title="List Organizations", json_schema_extra={"ui:hidden": True})
    limit: int = Field(50, ge=1, le=1000, description='The maximum number of organizations to return per page')
    cursor: Optional[str] = Field(None, description='Pagination cursor from a previous response')
    sort: str = Field('id', description='Field to sort results by. One of: `id`, `member_count`,')
    direction: Literal['asc', 'desc'] = Field('asc', description='Sort direction')
    cols: Optional[str] = Field(None, description='Comma-separated list of additional columns to include in the response.')
    name: Optional[str] = Field(None, description='Filter organizations by exact name match')
    primaryDomain: Optional[str] = Field(None, description='Filter organizations by primary domain (exact match)')


class CommonRoomGetOrganizationConfig(_Input):
    """Get an organization by ID."""
    operation: Literal["get_organization"] = Field("get_organization", title="Get Organization", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., pattern=r"^o_[0-9]+$", description='The prefixed organization ID (format `o_<number>`)')
    cols: Optional[str] = Field(None, description='Comma-separated list of additional columns to include in the response.')


class CommonRoomListActivitiesConfig(_Input):
    """List activities."""
    operation: Literal["list_activities"] = Field("list_activities", title="List Activities", json_schema_extra={"ui:hidden": True})
    limit: int = Field(50, ge=1, le=1000, description='The maximum number of activities to return per page')
    cursor: Optional[str] = Field(None, description='Pagination cursor from a previous response')
    sort: Literal['id', 'activityTime'] = Field('activityTime', description='Field to sort results by.')
    direction: Literal['asc', 'desc'] = Field('asc', description='Sort direction')
    cols: Optional[str] = Field(None, description='Comma-separated list of additional columns to include in the response.')
    contactId: Optional[str] = Field(None, description='Filter activities by prefixed contact ID (format `c_<number>`)')
    organizationId: Optional[str] = Field(None, description='Filter activities by prefixed organization ID (format `o_<number>`)')
    startDate: Optional[AwareDatetime] = Field(None, description='Only return activities occurring at or after this ISO-8601 datetime')
    endDate: Optional[AwareDatetime] = Field(None, description='Only return activities occurring at or before this ISO-8601 datetime')


class CommonRoomGetActivityConfig(_Input):
    """Get an activity by ID."""
    operation: Literal["get_activity"] = Field("get_activity", title="Get Activity", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., pattern=r"^a_[0-9]+$", description='The prefixed activity ID (format `a_<number>`)')
    cols: Optional[str] = Field(None, description='Comma-separated list of additional columns to include in the response.')


class CommonRoomListSegmentsConfig(_Input):
    """List segments."""
    operation: Literal["list_segments"] = Field("list_segments", title="List Segments", json_schema_extra={"ui:hidden": True})
    limit: int = Field(50, ge=1, le=1000, description='The maximum number of segments to return per page')
    cursor: Optional[str] = Field(None, description='Pagination cursor from a previous response')
    cols: Optional[str] = Field(None, description='Comma-separated list of additional columns to include in the response.')
    query: Optional[str] = Field(None, description='Filter segments by name (substring match)')


class CommonRoomGetSegmentConfig(_Input):
    """Get a segment by ID."""
    operation: Literal["get_segment"] = Field("get_segment", title="Get Segment", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., pattern=r"^s_[0-9]+$", description='The prefixed segment ID (format `s_<number>`)')
    cols: Optional[str] = Field(None, description='Comma-separated list of additional columns to include in the response.')


class CommonRoomListTagsConfig(_Input):
    """List tags."""
    operation: Literal["list_tags"] = Field("list_tags", title="List Tags", json_schema_extra={"ui:hidden": True})
    limit: int = Field(50, ge=1, le=1000, description='The maximum number of tags to return per page')
    cursor: Optional[str] = Field(None, description='Pagination cursor from a previous response')
    query: Optional[str] = Field(None, description='Filter tags by a case-insensitive substring of their name')
    entityType: Optional[Literal['contact', 'organization', 'activity', 'object']] = Field(None, description='Filter tags by the type of entity they can be applied to')


class CommonRoomGetTagConfig(_Input):
    """Get a tag by ID."""
    operation: Literal["get_tag"] = Field("get_tag", title="Get Tag", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., pattern=r"^l_[0-9]+$", description='The prefixed tag ID (format `l_<number>`)')


class CommonRoomListObjectsConfig(_Input):
    """List custom objects."""
    operation: Literal["list_objects"] = Field("list_objects", title="List Objects", json_schema_extra={"ui:hidden": True})
    limit: int = Field(50, ge=1, le=1000, description='The maximum number of objects to return per page')
    cursor: Optional[str] = Field(None, description='Pagination cursor from a previous response')
    sort: Literal['id', 'name'] = Field('id', description='Field to sort results by')
    direction: Literal['asc', 'desc'] = Field('asc', description='Sort direction')
    objectTypeId: str = Field(..., description='Filter objects by prefixed object type ID (format `cot_<number>`)')
    segmentId: Optional[str] = Field(None, description='Filter objects by prefixed segment ID (format `s_<number>`)')
    cols: Optional[str] = Field(None, description='Comma-separated list of additional columns to include in the response.')


class CommonRoomGetObjectConfig(_Input):
    """Get a custom object by ID."""
    operation: Literal["get_object"] = Field("get_object", title="Get Object", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., pattern=r"^co_[0-9]+$", description='The prefixed custom object ID (format `co_<number>`)')
    cols: Optional[str] = Field(None, description='Comma-separated list of additional columns to include in the response.')


class CommonRoomGetMeConfig(_Input):
    """Get current user info."""
    operation: Literal["get_me"] = Field("get_me", title="Get Me", json_schema_extra={"ui:hidden": True})


class CommonRoomListCustomFieldsConfig(_Input):
    """List custom fields."""
    operation: Literal["list_custom_fields"] = Field("list_custom_fields", title="List Custom Fields", json_schema_extra={"ui:hidden": True})
    entityType: Optional[str] = Field(None, description='Filter fields by entity type. Valid values: `contact`, `organization`,')


class CommonRoomListLeadScoresConfig(_Input):
    """List lead score definitions."""
    operation: Literal["list_lead_scores"] = Field("list_lead_scores", title="List Lead Scores", json_schema_extra={"ui:hidden": True})


class CommonRoomListObjectTypesConfig(_Input):
    """List object types."""
    operation: Literal["list_object_types"] = Field("list_object_types", title="List Object Types", json_schema_extra={"ui:hidden": True})


class CommonRoomCreateSegmentConfig(_Input):
    """Create a segment."""
    operation: Literal["create_segment"] = Field("create_segment", title="Create Segment", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    entityType: Literal["contact", "organization", "object"] = "contact"
    objectTypeId: Optional[str] = Field(None, pattern=r"^cot_[0-9]+$")

    @model_validator(mode="after")
    def object_type_required(self):
        if self.entityType == "object" and not self.objectTypeId:
            raise ValueError("Object segments require objectTypeId")
        return self


class CommonRoomRenameSegmentConfig(_Input):
    """Rename a segment."""
    operation: Literal["rename_segment"] = Field("rename_segment", title="Rename Segment", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., pattern=r"^s_[0-9]+$", description='The prefixed segment ID (format `s_<number>`)')
    name: str = Field(..., min_length=1, max_length=500)


class CommonRoomUpdateContactsConfig(_Bulk):
    """Update many contacts."""
    operation: Literal["update_contacts"] = Field("update_contacts", title="Update Contacts", json_schema_extra={"ui:hidden": True})
    contactIds: list[Annotated[str, Field(pattern=r"^c_[0-9]+$")]] = Field(..., min_length=1, max_length=100)


class CommonRoomUpdateOrganizationsConfig(_Bulk):
    """Update many organizations."""
    operation: Literal["update_organizations"] = Field("update_organizations", title="Update Organizations", json_schema_extra={"ui:hidden": True})
    organizationIds: list[Annotated[str, Field(pattern=r"^o_[0-9]+$")]] = Field(..., min_length=1, max_length=100)


class CommonRoomUpdateObjectsConfig(_Bulk):
    """Update many custom objects."""
    operation: Literal["update_objects"] = Field("update_objects", title="Update Objects", json_schema_extra={"ui:hidden": True})
    objectIds: list[Annotated[str, Field(pattern=r"^co_[0-9]+$")]] = Field(..., min_length=1, max_length=100)


class CommonRoomOnNewActivityConfig(PollTriggerConfigBase):
    operation: Literal["on_new_activity"] = Field("on_new_activity", title="On New Activity", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Activity"})
    contactId: Optional[str] = Field(None, pattern=r"^c_[0-9]+$")
    organizationId: Optional[str] = Field(None, pattern=r"^o_[0-9]+$")
    startDate: Optional[AwareDatetime] = Field(None, description="Only watch activities at or after this ISO 8601 time. The initial poll establishes a baseline.")

CommonRoomConfig = Annotated[Union[CommonRoomListContactsConfig, CommonRoomGetContactConfig, CommonRoomListOrganizationsConfig, CommonRoomGetOrganizationConfig, CommonRoomListActivitiesConfig, CommonRoomGetActivityConfig, CommonRoomListSegmentsConfig, CommonRoomGetSegmentConfig, CommonRoomListTagsConfig, CommonRoomGetTagConfig, CommonRoomListObjectsConfig, CommonRoomGetObjectConfig, CommonRoomGetMeConfig, CommonRoomListCustomFieldsConfig, CommonRoomListLeadScoresConfig, CommonRoomListObjectTypesConfig, CommonRoomCreateSegmentConfig, CommonRoomRenameSegmentConfig, CommonRoomUpdateContactsConfig, CommonRoomUpdateOrganizationsConfig, CommonRoomUpdateObjectsConfig, CommonRoomOnNewActivityConfig], Field(discriminator="operation")]

class CommonRoomNodeConfig(NodeConfig[CommonRoomConfig, CommonRoomAPITokenCredential]):
    pass

ROUTES = {'list_contacts': ('GET',
                   '/contacts',
                   ['limit', 'cursor', 'sort', 'direction', 'cols', 'organizationId', 'segmentId']),
 'get_contact': ('GET', '/contacts/{id}', ['cols']),
 'list_organizations': ('GET',
                        '/organizations',
                        ['limit', 'cursor', 'sort', 'direction', 'cols', 'name', 'primaryDomain']),
 'get_organization': ('GET', '/organizations/{id}', ['cols']),
 'list_activities': ('GET',
                     '/activities',
                     ['limit',
                      'cursor',
                      'sort',
                      'direction',
                      'cols',
                      'contactId',
                      'organizationId',
                      'startDate',
                      'endDate']),
 'get_activity': ('GET', '/activities/{id}', ['cols']),
 'list_segments': ('GET', '/segments', ['limit', 'cursor', 'cols', 'query']),
 'get_segment': ('GET', '/segments/{id}', ['cols']),
 'list_tags': ('GET', '/tags', ['limit', 'cursor', 'query', 'entityType']),
 'get_tag': ('GET', '/tags/{id}', []),
 'list_objects': ('GET',
                  '/objects',
                  ['limit', 'cursor', 'sort', 'direction', 'objectTypeId', 'segmentId', 'cols']),
 'get_object': ('GET', '/objects/{id}', ['cols']),
 'get_me': ('GET', '/me', []),
 'list_custom_fields': ('GET', '/custom-fields', ['entityType']),
 'list_lead_scores': ('GET', '/lead-scores', []),
 'list_object_types': ('GET', '/object-types', []),
 'create_segment': ('POST', '/segments', []),
 'rename_segment': ('PATCH', '/segments/{id}', []),
 'update_contacts': ('POST', '/contacts/bulk', []),
 'update_organizations': ('POST', '/organizations/bulk', []),
 'update_objects': ('POST', '/objects/bulk', [])}

class CommonRoomNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-common-room"
    connection_evidence = ConnectionEvidence(noun="segments", operation="list_segments", identity_operation="get_me")

    @classmethod
    def get_config_model(cls):
        return CommonRoomNodeConfig

    @staticmethod
    async def _request(token, method, path, *, params=None, body=None):
        async with guarded_async_client(timeout=45, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, params=params, json=body,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
        if not 200 <= response.status_code < 300:
            try:
                payload = response.json()
                detail = payload.get("message") or payload.get("error") or payload.get("status")
            except (ValueError, AttributeError):
                detail = "Request failed"
            raise ValueError(f"Common Room API {response.status_code}: {str(detail).replace(token, '[redacted]')}")
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise ValueError("Common Room did not confirm the request")
        return payload

    async def execute(self, inputs):
        if not isinstance(self.config, CommonRoomNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Common Room API token")
        config = self.config.config
        token = self.config.credentials.api_token
        if isinstance(config, CommonRoomOnNewActivityConfig):
            return await self._poll(token, config)
        method, path, query = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if "{id}" in path:
            path = path.replace("{id}", quote(values.pop("id"), safe=""))
        params = {key: values.pop(key) for key in query if key in values}
        return await self._request(token, method, path, params=params, body=values or None)

    async def _poll(self, token, config):
        params = config.model_dump(mode="json", exclude_none=True,
            include={"contactId", "organizationId", "startDate"})
        params.update({"limit": 1000, "sort": "activityTime", "direction": "desc",
            "cols": "contactId,content,providerId,providerName,url"})
        rows, cursors = [], set()
        for _ in range(10):
            payload = await self._request(token, "GET", "/activities", params=params)
            page = payload.get("data")
            if not isinstance(page, list) or any(not isinstance(row, dict) or not all(k in row for k in ("id", "type", "activityTime")) for row in page):
                raise ValueError("Common Room returned an invalid activities page")
            rows.extend(page)
            cursor = payload.get("meta", {}).get("nextCursor")
            if cursor is None:
                break
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise ValueError("Common Room returned a nonadvancing cursor")
            cursors.add(cursor)
            params["cursor"] = cursor
        else:
            raise ValueError("More than 10,000 activities match; narrow contact, organization or start time")
        fresh = await self._filter_unseen(rows, lambda row: row["id"])
        return {"activities": fresh, "new_activity_count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_activity_count")) if config.get("operation") == "on_new_activity" else True

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or "activities" not in output:
            return super().resolve_agent_event(output)
        rows = output["activities"]
        if not rows:
            return None
        lines = []
        for row in rows[:20]:
            lines.append(f"- {row.get('contactId') or 'A contact'}: {row['type']} at {row['activityTime']} on {row.get('providerName') or 'Common Room'}; {row.get('content') or ''} (activity {row['id']}, provider {row.get('providerId') or 'unknown'}). {row.get('url') or ''}")
        return {"text": f"Common Room: {len(rows)} new activities\n" + "\n".join(lines), "conversation_key": None}
