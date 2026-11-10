"""JSM Operations alerts, pinned to Atlassian's published Operations v1 API.

Basic auth uses the user's Atlassian email/API token and cloud instance ID.
Reads return one page, retaining provider pagination. Asynchronous writes return
accepted/requestId, never claim completion; get_request_status checks processing.
New alerts are polled in creation order. Premium Webhook integrations exist,
but the published API leaves outgoing action types/mappings integration-specific
without a Webhook registration example, so this node uses the fully specified
listAlerts polling contract rather than guessing forwarding rules.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE = "https://api.atlassian.com/jsm/ops/api"


class JiraServiceManagementAlertTokenCredential(BaseModel):
    model_config = ConfigDict(title="Jira Service Management Alert API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://id.atlassian.com/manage-profile/security/api-tokens",
            "x-credential-instructions": "Paste your Atlassian account email, API token without scopes, and Jira Cloud ID. Find the Cloud ID at https://YOUR-SITE.atlassian.net/_edge/tenant_info (cloudId). Your account needs permission to view or manage Operations alerts. Requests go to api.atlassian.com only.",
        })
    credential_type: Literal["jira_service_management_alert_ca_token"] = Field(
        "jira_service_management_alert_ca_token", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., title="Atlassian Account Email", min_length=3)
    api_token: str = Field(..., title="API Token", min_length=1,
                           json_schema_extra={"ui:widget": "password"})
    cloud_id: str = Field(..., title="Cloud ID", min_length=1,
                          description="The cloudId for your Jira Cloud instance, not the site URL.")

    @field_validator("cloud_id")
    @classmethod
    def cloud(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
            raise ValueError("Paste the Cloud ID from your site's tenant_info page")
        return value

    @field_validator("email")
    @classmethod
    def account_email(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[^\s:@]+@[^\s:@]+\.[^\s:@]+", value):
            raise ValueError("Enter the email of the account that created the API token")
        return value

    @field_validator("api_token")
    @classmethod
    def token(cls, value: str) -> str:
        value = clean_secret(value, field_name="API Token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API token without an authorization header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Alert(_Input):
    alert_id: str = Field(..., title="Alert ID", min_length=1, max_length=512)


class _Cursor(_Alert):
    size: int = Field(20, title="Page Size", ge=1, le=100)
    after: Optional[str] = Field(None, title="After Cursor", description="Use the cursor from the previous page's links.")


def _operation(name: str, title: str, category: str = "Alerts", trigger: bool = False):
    return Field(name, title=title, json_schema_extra={"ui:hidden": True,
        "x-display-name": title, "x-category": category, "x-is-trigger": trigger})


class ListAlerts(_Input):
    operation: Literal["list_alerts"] = _operation("list_alerts", "List Alerts")
    size: int = Field(20, ge=1, le=100, title="Page Size")
    offset: int = Field(0, ge=0, le=19999, title="Offset")
    sort: Literal["createdAt", "insertedAt", "lastOccurredAt", "priority"] = Field("insertedAt", title="Sort By")
    order: Literal["asc", "desc"] = Field("desc", title="Order")
    query: Optional[str] = Field(None, title="Search Query")
    from_time: Optional[int] = Field(None, title="From Timestamp", ge=0, le=2147483647,
                                   description="Provider's integer date-time filter (from).")
    to_time: Optional[int] = Field(None, title="To Timestamp", ge=0, le=2147483647,
                                 description="Provider's integer date-time filter (to).")

    @model_validator(mode="after")
    def page_bounds(self):
        if self.offset + self.size >= 20000:
            raise ValueError("Offset plus page size must be below 20000")
        if self.from_time is not None and self.to_time is not None and self.from_time > self.to_time:
            raise ValueError("From must be before To")
        return self


class GetAlert(_Alert):
    operation: Literal["get_alert"] = _operation("get_alert", "Get Alert")


class GetAlertByAlias(_Input):
    operation: Literal["get_alert_by_alias"] = _operation("get_alert_by_alias", "Get Alert by Alias")
    alias: str = Field(..., title="Alias", min_length=1, max_length=512)


class CreateAlert(_Input):
    operation: Literal["create_alert"] = _operation("create_alert", "Create Alert")
    message: str = Field(..., title="Message", min_length=1, max_length=130)
    description: Optional[str] = Field(None, title="Description", max_length=15000)
    alias: Optional[str] = Field(None, title="Alias", max_length=512, description="Deduplication key.")
    priority: Literal["P1", "P2", "P3", "P4", "P5"] = Field("P3", title="Priority")
    entity: Optional[str] = Field(None, title="Entity", max_length=512)
    source: Optional[str] = Field(None, title="Source", max_length=100)
    note: Optional[str] = Field(None, title="Note", max_length=25000)


class AssignAlert(_Alert):
    operation: Literal["assign_alert"] = _operation("assign_alert", "Assign Alert")
    account_id: str = Field(..., title="Assignee Account ID", min_length=1)


class AddTags(_Alert):
    operation: Literal["add_tags"] = _operation("add_tags", "Add Tags")
    tags: str = Field(..., title="Tags", min_length=1, description="Comma-separated tags to add.")

    @field_validator("tags")
    @classmethod
    def nonempty_tags(cls, value):
        if not any(t.strip() for t in value.split(",")):
            raise ValueError("Provide at least one tag")
        return value


class SnoozeAlert(_Alert):
    operation: Literal["snooze_alert"] = _operation("snooze_alert", "Snooze Alert")
    end_time: str = Field(..., title="Snooze Until", description="ISO 8601 date and time with timezone.",
                          json_schema_extra={"format": "date-time"})

    @field_validator("end_time")
    @classmethod
    def timestamp(cls, value):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError("Include a timezone")
        return value


class ListNotes(_Cursor):
    operation: Literal["list_notes"] = _operation("list_notes", "List Alert Notes", "Notes")


class AddNote(_Alert):
    operation: Literal["add_note"] = _operation("add_note", "Add Alert Note", "Notes")
    note: str = Field(..., title="Note", min_length=1)


class UpdateNote(_Alert):
    operation: Literal["update_note"] = _operation("update_note", "Update Alert Note", "Notes")
    note_id: str = Field(..., title="Note ID", min_length=1)
    note: str = Field(..., title="Note", min_length=1)


class DeleteNote(_Alert):
    operation: Literal["delete_note"] = _operation("delete_note", "Delete Alert Note", "Notes")
    note_id: str = Field(..., title="Note ID", min_length=1)


class UpdatePriority(_Alert):
    operation: Literal["update_priority"] = _operation("update_priority", "Update Alert Priority")
    priority: Literal["P1", "P2", "P3", "P4", "P5"] = Field(..., title="Priority")


class UpdateMessage(_Alert):
    operation: Literal["update_message"] = _operation("update_message", "Update Alert Message")
    message: str = Field(..., title="Message", min_length=1, max_length=130)


class UpdateDescription(_Alert):
    operation: Literal["update_description"] = _operation("update_description", "Update Alert Description")
    description: str = Field(..., title="Description", max_length=15000)


class GetRequestStatus(_Input):
    operation: Literal["get_request_status"] = _operation("get_request_status", "Get Alert Request Status")
    request_id: str = Field(..., title="Request ID", min_length=1,
                            description="The requestId returned by an accepted asynchronous alert write.")


class ListLogs(_Cursor):
    operation: Literal["list_logs"] = _operation("list_logs", "List Alert Logs")


class OnNewAlert(PollTriggerConfigBase):
    operation: Literal["on_new_alert"] = _operation("on_new_alert", "On New Alert", "Triggers", True)
    query: Optional[str] = Field(None, title="Search Query",
        description="Optional alert search. Limit the scope to fewer than 10000 alerts. Existing alerts form a baseline; only new IDs fire. Alerts created and deleted between polls cannot be detected.")


class DeleteAlert(_Alert):
    operation: Literal["delete_alert"] = _operation("delete_alert", "Delete Alert")


class AcknowledgeAlert(_Alert):
    operation: Literal["acknowledge_alert"] = _operation("acknowledge_alert", "Acknowledge Alert")


class UnacknowledgeAlert(_Alert):
    operation: Literal["unacknowledge_alert"] = _operation("unacknowledge_alert", "Unacknowledge Alert")


class CloseAlert(_Alert):
    operation: Literal["close_alert"] = _operation("close_alert", "Close Alert")


AlertConfig = Annotated[Union[
    ListAlerts, GetAlert, GetAlertByAlias, CreateAlert, DeleteAlert,
    AcknowledgeAlert, UnacknowledgeAlert, CloseAlert, AssignAlert, AddTags,
    SnoozeAlert, ListNotes, AddNote, UpdateNote, DeleteNote, UpdatePriority,
    UpdateMessage, UpdateDescription, GetRequestStatus, ListLogs, OnNewAlert,
], Discriminator("operation")]


class JiraServiceManagementAlertNodeConfig(NodeConfig[AlertConfig, JiraServiceManagementAlertTokenCredential]):
    pass


# Each operation calls exactly one operation from the pinned Operations contract.
# Poll pagination repeats listAlerts; no implicit write retries or readbacks.
OPERATIONS = {
    "list_alerts": ("GET", "/alerts"),
    "get_alert": ("GET", "/alerts/{alert_id}"),
    "get_alert_by_alias": ("GET", "/alerts/alias"),
    "create_alert": ("POST", "/alerts"),
    "delete_alert": ("DELETE", "/alerts/{alert_id}"),
    "acknowledge_alert": ("POST", "/alerts/{alert_id}/acknowledge"),
    "unacknowledge_alert": ("POST", "/alerts/{alert_id}/unacknowledge"),
    "close_alert": ("POST", "/alerts/{alert_id}/close"),
    "assign_alert": ("POST", "/alerts/{alert_id}/assign"),
    "add_tags": ("POST", "/alerts/{alert_id}/tags"),
    "snooze_alert": ("POST", "/alerts/{alert_id}/snooze"),
    "list_notes": ("GET", "/alerts/{alert_id}/notes"),
    "add_note": ("POST", "/alerts/{alert_id}/notes"),
    "update_note": ("PATCH", "/alerts/{alert_id}/notes/{note_id}"),
    "delete_note": ("DELETE", "/alerts/{alert_id}/notes/{note_id}"),
    "update_priority": ("PATCH", "/alerts/{alert_id}/priority"),
    "update_message": ("PATCH", "/alerts/{alert_id}/message"),
    "update_description": ("PATCH", "/alerts/{alert_id}/description"),
    "get_request_status": ("GET", "/alerts/requests/{request_id}"),
    "list_logs": ("GET", "/alerts/{alert_id}/logs"),
    "on_new_alert": ("GET", "/alerts"),
}
_BODY = {
    "create_alert": {k: k for k in ("message", "description", "alias", "priority", "entity", "source", "note")},
    "assign_alert": {"account_id": "accountId"},
    "snooze_alert": {"end_time": "endTime"},
    "add_note": {"note": "note"}, "update_note": {"note": "note"},
    "update_priority": {"priority": "priority"},
    "update_message": {"message": "message"},
    "update_description": {"description": "description"},
}


async def _request(credential, operation, values):
    method, route = OPERATIONS[operation]
    path_fields = re.findall(r"\{([^}]+)\}", route)
    for field in path_fields:
        route = route.replace("{" + field + "}", quote(str(values[field]), safe=""))
    params = {}
    if method == "GET":
        params = {{"from_time": "from", "to_time": "to"}.get(k, k): v
                  for k, v in values.items()
                  if k not in path_fields and k != "operation" and v is not None}
    body = {wire: values[k] for k, wire in _BODY.get(operation, {}).items() if values.get(k) is not None}
    if operation == "add_tags":
        body = {"tags": [t.strip() for t in values["tags"].split(",") if t.strip()]}
    kwargs = {"params": params}
    if body:
        kwargs["json"] = body
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            response = await client.request(method, BASE + "/" + quote(credential.cloud_id, safe="") + "/v1" + route,
                auth=httpx.BasicAuth(credential.email, credential.api_token),
                headers={"Accept": "application/json"}, **kwargs)
    except httpx.TimeoutException:
        raise ValueError("Jira Service Management Alert request timed out; inspect write status before retrying") from None
    except httpx.RequestError:
        raise ValueError("Could not reach Jira Service Management Alert; inspect write status before retrying") from None
    if not 200 <= response.status_code < 300:
        # Do not return provider bodies/exception strings that might echo secrets.
        raise ValueError(f"Jira Service Management Alert API returned HTTP {response.status_code}")
    if response.status_code == 204:
        return {"status": "success", "status_code": 204, "action": operation, "data": {}}
    try:
        data = response.json()
    except ValueError:
        raise ValueError("Jira Service Management Alert returned invalid JSON") from None
    if not isinstance(data, dict) or not data:
        raise ValueError("Jira Service Management Alert returned an invalid response")
    if operation in {"list_alerts", "on_new_alert", "list_notes", "list_logs"}:
        if not isinstance(data.get("values"), list) or any(not isinstance(row, dict) for row in data["values"]):
            raise ValueError("Jira Service Management Alert returned an invalid page")
    if operation == "on_new_alert" and any(not isinstance(row.get("id"), str) or not row["id"] for row in data["values"]):
        raise ValueError("Jira Service Management Alert returned an alert without an ID")
    accepted = "requestId" in data
    return {"status": "accepted" if accepted else "success", "status_code": response.status_code,
            "action": operation, "data": data, **({"completed": False, "request_id": data["requestId"]} if accepted else {})}


class JiraServiceManagementAlertNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-jira-service-management-alert-ca"
    connection_evidence = ConnectionEvidence(operation="list_alerts", noun="alerts")
    edit_examples = ["Create a high priority alert", "Acknowledge an alert", "Add a note to an alert",
                     "Close an alert", "Watch for new Operations alerts"]

    @classmethod
    def get_config_model(cls):
        return JiraServiceManagementAlertNodeConfig

    @classmethod
    def should_propagate_output(cls, output: dict[str, Any], config: dict[str, Any]) -> bool:
        return bool(output.get("new_alert_count")) if config.get("operation") == "on_new_alert" else True

    @classmethod
    def resolve_agent_event(cls, output: dict[str, Any]) -> Optional[dict[str, Any]]:
        alerts = output.get("alerts")
        if not isinstance(alerts, list):
            return super().resolve_agent_event(output)
        if not alerts:
            return None
        lines = [f"- {a.get('message') or 'New alert'} (ID {a['id']}, priority {a.get('priority') or 'unspecified'}, status {a.get('status') or 'unspecified'}); source: {a.get('source') or 'unspecified'}; entity: {a.get('entity') or 'unspecified'}; owner: {a.get('owner') or 'unassigned'}"
                 for a in alerts[:20]]
        if len(alerts) > 20:
            lines.append(f"- {len(alerts) - 20} more alerts are available in the output")
        return {"text": f"Jira Service Management Operations: {len(alerts)} new alert(s):\n" + "\n".join(lines),
                "conversation_key": None}

    async def _poll_new_alerts(self, credential, config):
        alerts = []
        for offset in range(0, 10000, 100):
            result = await _request(credential, "on_new_alert", {
                "size": 100, "offset": offset, "sort": "createdAt", "order": "desc", "query": config.query})
            page = result["data"]["values"]
            alerts.extend(page)
            if len(page) < 100:
                break
        else:
            raise ValueError("Alert scope reached 10000 items; narrow the search query before polling")
        # Refuse an ambiguous repeated/overlapping page before touching poll state.
        if len({a["id"] for a in alerts}) != len(alerts):
            raise ValueError("Alert pages overlap; retry the next poll")
        fresh = await self._filter_unseen(alerts, lambda a: a["id"])
        return {"action": "on_new_alert", "alerts": fresh, "new_alert_count": len(fresh)}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, JiraServiceManagementAlertNodeConfig):
            raise ValueError("Jira Service Management Alert configuration is required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect your Jira Service Management Alert account")
        config = self.config.config
        if isinstance(config, OnNewAlert):
            return await self._poll_new_alerts(credential, config)
        return await _request(credential, config.operation, config.model_dump(exclude_none=True))
