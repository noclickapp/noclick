"""TOPdesk Incident Management API 4.2.10, using an operator application token.

Contract: https://developers.topdesk.com/swagger/incident_specification_4.2.10.yaml
Authentication: https://developers.topdesk.com/tutorial.html#authentication
Polls baseline existing incidents and fail before advancing state if pagination
exceeds 5,000 incidents; use a FIQL query to narrow larger installations.
"""
from __future__ import annotations

import base64
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret, https_origin
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client


class TOPdeskCredential(BaseModel):
    model_config = ConfigDict(title="TOPDESK Application Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.topdesk.com/tutorial.html#authentication",
            "x-credential-instructions": "Enter your public HTTPS TOPdesk URL, operator login name and application token from My settings > Application tokens (Application passwords on older versions). Give the operator REST API and incident read permissions, plus write permissions for the actions you use. Use the application token as the password, not your account password. Connection checks read your incidents.",
        })
    credential_type: Literal["topdesk_application_token"] = Field("topdesk_application_token", json_schema_extra={"ui:hidden": True})
    base_url: str = Field(..., title="TOPdesk URL", min_length=1, description="For example https://example.topdesk.net. Public HTTPS self-hosted installations are also supported.")
    username: str = Field(..., title="Operator Login Name", min_length=1, max_length=255)
    application_token: str = Field(..., title="Application Token", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("base_url", mode="before")
    @classmethod
    def origin(cls, value):
        origin = https_origin(value, field_name="TOPdesk URL")
        if urlsplit(origin).scheme != "https" or urlsplit(origin).port not in {None, 443}:
            raise ValueError("Use a public HTTPS TOPdesk URL on port 443")
        return origin

    @field_validator("username", "application_token", mode="before")
    @classmethod
    def auth_text(cls, value, info):
        if not isinstance(value, str):
            raise ValueError("Enter text")
        value = value.strip()
        if info.field_name == "application_token":
            value = clean_secret(value, field_name="Application token", key=True)
        if any(ord(c) < 32 or ord(c) == 127 for c in value) or (info.field_name == "username" and ":" in value):
            raise ValueError("Use a value without control characters or a username colon")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Incident(_Input):
    incident_id: str = Field(..., title="Incident ID", json_schema_extra={"format": "uuid"})

    @field_validator("incident_id")
    @classmethod
    def incident_uuid(cls, value):
        return str(UUID(value))


class ListIncidents(_Input):
    operation: Literal["list_incidents"] = Field("list_incidents", json_schema_extra={"ui:hidden": True})
    page_start: int = Field(0, ge=0)
    page_size: int = Field(100, ge=1, le=1000)
    query: str | None = Field(None, max_length=4000, description="TOPdesk FIQL query. See https://developers.topdesk.com/tutorial.html#query")
    sort: str = Field("creationDate:desc", max_length=500)
    include_archived: bool = Field(False, description="Include partial and archived incidents (API all parameter).")


class GetIncident(_Incident):
    operation: Literal["get_incident"] = Field("get_incident", json_schema_extra={"ui:hidden": True})


class GetIncidentByNumber(_Input):
    operation: Literal["get_incident_by_number"] = Field("get_incident_by_number", json_schema_extra={"ui:hidden": True})
    number: str = Field(..., min_length=1, max_length=100, description="Incident number, for example I 1501 001.")


class _IncidentFields(_Input):
    brief_description: str | None = Field(None, max_length=80)
    request: str | None = Field(None, max_length=100000, description="Request text; TOPdesk's documented formatting is supported.")
    action: str | None = Field(None, max_length=100000, description="Add an action to the incident progress trail.")
    action_invisible_for_caller: bool | None = None
    caller_id: str | None = Field(None, json_schema_extra={"format": "uuid"})
    category_id: str | None = Field(None, json_schema_extra={"format": "uuid"})
    subcategory_id: str | None = Field(None, json_schema_extra={"format": "uuid"})
    operator_id: str | None = Field(None, json_schema_extra={"format": "uuid"})
    operator_group_id: str | None = Field(None, json_schema_extra={"format": "uuid"})
    processing_status_id: str | None = Field(None, json_schema_extra={"format": "uuid"})
    priority_id: str | None = Field(None, json_schema_extra={"format": "uuid"})
    impact_id: str | None = Field(None, json_schema_extra={"format": "uuid"})
    urgency_id: str | None = Field(None, json_schema_extra={"format": "uuid"})
    call_type_id: str | None = Field(None, json_schema_extra={"format": "uuid"})
    entry_type_id: str | None = Field(None, json_schema_extra={"format": "uuid"})
    closure_code_id: str | None = Field(None, json_schema_extra={"format": "uuid"})
    external_number: str | None = Field(None, max_length=60)
    on_hold: bool | None = None
    completed: bool | None = None
    closed: bool | None = None

    @field_validator("caller_id", "category_id", "subcategory_id", "operator_id", "operator_group_id",
                     "processing_status_id", "priority_id", "impact_id", "urgency_id", "call_type_id", "entry_type_id", "closure_code_id")
    @classmethod
    def reference_uuid(cls, value):
        return str(UUID(value)) if value is not None else None


class CreateIncident(_IncidentFields):
    operation: Literal["create_incident"] = Field("create_incident", json_schema_extra={"ui:hidden": True})
    brief_description: str = Field(..., min_length=1, max_length=80)
    caller_id: str = Field(..., description="ID of a registered caller with the Caller checkbox enabled.", json_schema_extra={"format": "uuid"})
    status: Literal["firstLine", "secondLine"] = "firstLine"


class UpdateIncident(_Incident, _IncidentFields):
    operation: Literal["update_incident"] = Field("update_incident", json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def changes(self):
        if not any(getattr(self, key) is not None for key in _IncidentFields.model_fields):
            raise ValueError("Supply at least one incident field to update")
        return self


class ArchiveIncident(_Incident):
    operation: Literal["archive_incident"] = Field("archive_incident", json_schema_extra={"ui:hidden": True})
    reason_name: str = Field(..., min_length=1, max_length=255, description="Existing archiving reason name.")


class UnarchiveIncident(_Incident):
    operation: Literal["unarchive_incident"] = Field("unarchive_incident", json_schema_extra={"ui:hidden": True})
    unarchive_partials: bool = True


class _Trail(_Incident):
    start: int = Field(0, ge=0)
    page_size: int = Field(10, ge=1, le=10)


class ListActions(_Trail):
    operation: Literal["list_actions"] = Field("list_actions", json_schema_extra={"ui:hidden": True})


class ListRequests(_Trail):
    operation: Literal["list_requests"] = Field("list_requests", json_schema_extra={"ui:hidden": True})


class ListProgressTrail(_Trail):
    operation: Literal["list_progress_trail"] = Field("list_progress_trail", json_schema_extra={"ui:hidden": True})


class ListTimeSpent(_Incident):
    operation: Literal["list_time_spent"] = Field("list_time_spent", json_schema_extra={"ui:hidden": True})


class RegisterTimeSpent(_Incident):
    operation: Literal["register_time_spent"] = Field("register_time_spent", json_schema_extra={"ui:hidden": True})
    time_spent: int = Field(..., description="Minutes; negative values correct time already registered. Total time must stay nonnegative.")
    notes: str | None = Field(None, max_length=250)


class ListCategories(_Input):
    operation: Literal["list_categories"] = Field("list_categories", json_schema_extra={"ui:hidden": True})


class ListSubcategories(_Input):
    operation: Literal["list_subcategories"] = Field("list_subcategories", json_schema_extra={"ui:hidden": True})


class ListStatuses(_Input):
    operation: Literal["list_statuses"] = Field("list_statuses", json_schema_extra={"ui:hidden": True})


class ListPriorities(_Input):
    operation: Literal["list_priorities"] = Field("list_priorities", json_schema_extra={"ui:hidden": True})


class ListUrgencies(_Input):
    operation: Literal["list_urgencies"] = Field("list_urgencies", json_schema_extra={"ui:hidden": True})


class ListImpacts(_Input):
    operation: Literal["list_impacts"] = Field("list_impacts", json_schema_extra={"ui:hidden": True})


class ListCallTypes(_Input):
    operation: Literal["list_call_types"] = Field("list_call_types", json_schema_extra={"ui:hidden": True})


class ListEntryTypes(_Input):
    operation: Literal["list_entry_types"] = Field("list_entry_types", json_schema_extra={"ui:hidden": True})


class _Lookup(_Input):
    page_start: int = Field(0, ge=0)
    page_size: int = Field(100, ge=1, le=1000)
    name: str | None = Field(None, max_length=255)


class ListOperators(_Lookup):
    operation: Literal["list_operators"] = Field("list_operators", json_schema_extra={"ui:hidden": True})


class ListOperatorGroups(_Lookup):
    operation: Literal["list_operator_groups"] = Field("list_operator_groups", json_schema_extra={"ui:hidden": True})


class _Poll(PollTriggerConfigBase):
    query: str | None = Field(None, max_length=4000, description="FIQL filter restricting monitored incidents. Maximum 5,000 matching incidents; narrow larger scopes.")


class OnNewIncident(_Poll):
    operation: Literal["on_new_incident"] = Field("on_new_incident", title="On New Incident", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})


class OnUpdatedIncident(_Poll):
    operation: Literal["on_updated_incident"] = Field("on_updated_incident", title="On New or Updated Incident", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})


Operation = Annotated[Union[ListIncidents, GetIncident, GetIncidentByNumber, CreateIncident, UpdateIncident,
    ArchiveIncident, UnarchiveIncident, ListActions, ListRequests, ListProgressTrail, ListTimeSpent, RegisterTimeSpent,
    ListCategories, ListSubcategories, ListStatuses, ListPriorities, ListUrgencies, ListImpacts, ListCallTypes,
    ListEntryTypes, ListOperators, ListOperatorGroups, OnNewIncident, OnUpdatedIncident], Field(discriminator="operation")]


class TOPdeskNodeConfig(NodeConfig[Operation, TOPdeskCredential]):
    pass


_WIRE = {
    "brief_description": "briefDescription", "action_invisible_for_caller": "actionInvisibleForCaller",
    "external_number": "externalNumber", "on_hold": "onHold", "caller_id": "callerLookup",
    "category_id": "category", "subcategory_id": "subcategory", "operator_id": "operator",
    "operator_group_id": "operatorGroup", "processing_status_id": "processingStatus", "priority_id": "priority",
    "impact_id": "impact", "urgency_id": "urgency", "call_type_id": "callType", "entry_type_id": "entryType",
    "closure_code_id": "closureCode",
}
_CATALOG = {"list_categories": "categories", "list_subcategories": "subcategories", "list_statuses": "statuses",
    "list_priorities": "priorities", "list_urgencies": "urgencies", "list_impacts": "impacts",
    "list_call_types": "call_types", "list_entry_types": "entry_types"}


class TOPdeskNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-topdesk"
    connection_evidence = ConnectionEvidence(operation="list_incidents", noun="incidents", label_keys=("briefDescription", "number", "id"))

    @classmethod
    def get_config_model(cls):
        return TOPdeskNodeConfig

    async def _request(self, method, path, *, params=None, body=None, progress=False):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a TOPdesk operator account")
        auth = base64.b64encode((credential.username + ":" + credential.application_token).encode()).decode()
        headers = {"Authorization": "Basic " + auth, "Accept": "application/x.topdesk-collection-progress-trail-v4+json" if progress else "application/json"}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, credential.base_url + "/tas/api" + path,
                params=params, json=body, headers=headers)
        response.raise_for_status()
        if response.status_code not in {200, 201, 204, 206}:
            raise ValueError("Unexpected TOPdesk response status")
        if response.status_code == 204:
            return [], False
        return response.json(), response.status_code == 206

    @staticmethod
    def _items(data):
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise ValueError("Expected a TOPdesk list of records")
        return data

    async def _poll(self, config):
        updated = config.operation == "on_updated_incident"
        date = "modificationDate" if updated else "creationDate"
        items = []
        for start in range(0, 5000, 100):
            params = {"pageStart": start, "pageSize": 100, "sort": date + ":desc,id:desc", "dateFormat": "iso8601", "all": "true"}
            if config.query:
                params["query"] = config.query
            data, more = await self._request("GET", "/incidents", params=params)
            rows = self._items(data)
            items.extend(rows)
            if not more:
                break
            if not rows:
                raise ValueError("TOPdesk returned an empty partial page")
        else:
            raise ValueError("More than 5,000 TOPdesk incidents match; narrow the trigger's FIQL query")
        for item in items:
            if not item.get("id") or not item.get(date):
                raise ValueError("TOPdesk poll requires incident IDs and timestamps")
        fresh = await self._filter_unseen(items, lambda row: str(row["id"]) + (":" + str(row[date]) if updated else ""))
        return {"operation": config.operation, "incidents": fresh, "new_incident_count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_incident_count")) if config.get("operation") in {"on_new_incident", "on_updated_incident"} else True

    @classmethod
    def resolve_agent_event(cls, output):
        incidents = output.get("incidents") if isinstance(output, dict) else None
        if not isinstance(incidents, list):
            return super().resolve_agent_event(output)
        if not incidents:
            return None
        lines = []
        for incident in incidents[:10]:
            caller = incident.get("caller") or {}
            who = caller.get("dynamicName") or caller.get("email") or "Unknown caller"
            lines.append(f"- {incident.get('number') or incident['id']}: {incident.get('briefDescription') or 'Incident'}; caller {who}; request: {incident.get('request') or '(no request text)'}; incident ID {incident['id']}")
        change = "new or updated" if output.get("operation") == "on_updated_incident" else "new"
        return {"text": f"TOPdesk: {len(incidents)} {change} incident(s) in your monitored incident queue:\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        config = self.config.config
        op = config.operation
        if isinstance(config, _Poll):
            return await self._poll(config)
        method, path, params, body = "GET", "/incidents", {}, None
        is_list = False
        if isinstance(config, ListIncidents):
            params = {"pageStart": config.page_start, "pageSize": config.page_size, "sort": config.sort,
                "dateFormat": "iso8601", "all": str(config.include_archived).lower()}
            if config.query:
                params["query"] = config.query
            is_list = True
        elif op in _CATALOG:
            path += "/" + _CATALOG[op]
            is_list = True
        elif isinstance(config, _Lookup):
            path += "/" + ("operators" if op == "list_operators" else "operatorgroups") + "/lookup"
            params = {"pageStart": config.page_start, "pageSize": config.page_size}
            if config.name:
                params["name"] = config.name
            is_list = True
        elif isinstance(config, GetIncidentByNumber):
            path += "/number/" + quote(config.number, safe="")
        elif isinstance(config, CreateIncident):
            method = "POST"
        else:
            path += "/id/" + quote(config.incident_id, safe="")
            if isinstance(config, UpdateIncident):
                method = "PATCH"
            elif isinstance(config, ArchiveIncident):
                method, path, body = "PUT", path + "/archive", {"name": config.reason_name}
            elif isinstance(config, UnarchiveIncident):
                method, path = "PUT", path + "/unarchive"
                params = {"unarchive_partials": str(config.unarchive_partials).lower()}
            elif isinstance(config, _Trail):
                path += "/" + {"list_actions": "actions", "list_requests": "requests", "list_progress_trail": "progresstrail"}[op]
                params = {"start": config.start, "page_size": config.page_size}
                is_list = True
            elif isinstance(config, (ListTimeSpent, RegisterTimeSpent)):
                path += "/timespent"
                is_list = isinstance(config, ListTimeSpent)
                if not is_list:
                    method, body = "POST", {"timeSpent": config.time_spent}
                    if config.notes is not None:
                        body["notes"] = config.notes
        if isinstance(config, (CreateIncident, UpdateIncident)):
            values = config.model_dump(exclude_none=True, exclude={"operation", "incident_id"})
            body = {_WIRE.get(key, key): {"id": value} if key.endswith("_id") else value for key, value in values.items()}
        data, more = await self._request(method, path, params=params, body=body, progress=isinstance(config, ListProgressTrail))
        if is_list:
            rows = self._items(data.get("results") if isinstance(config, _Lookup) and isinstance(data, dict) else data)
            # Lookup endpoints do not expose a continuation flag; a full page
            # is conservatively considered potentially incomplete.
            if isinstance(config, _Lookup):
                more = len(rows) >= config.page_size
            offset = getattr(config, "page_start", getattr(config, "start", None))
            return {"items": rows, "has_more": more, "next_offset": offset + len(rows) if more and offset is not None else None}
        if not isinstance(data, dict):
            raise ValueError("Expected a TOPdesk record")
        return {"data": data}
