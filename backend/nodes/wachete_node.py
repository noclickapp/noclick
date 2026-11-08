"""Wachete v1 monitor, folder, history and notification operations.

Contract: https://api.wachete.com/swagger/v1/swagger.json
Bearer tokens come from the documented API-key login, not an OAuth flow.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.wachete.com/thirdparty/v1"


class WacheteTokenCredential(BaseModel):
    model_config = ConfigDict(title="Wachete API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.wachete.com/api",
            "x-credential-instructions": "Use the token returned by Wachete's API-key login (POST /thirdparty/v1/user/apilogin with the userId and apiKey from your Wachete profile). Paste only the returned token. Tokens expire: replace this credential's token when it expires. NoClick does not store your password or refresh the token.",
        })
    credential_type: Literal["wachete_api_token"] = Field("wachete_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", min_length=1, repr=False,
        json_schema_extra={"ui:widget": "password", "ui:help": "Paste the token from the API login response, without the Bearer prefix."})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Token")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste only the Wachete token without spaces or a Bearer prefix")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MonitorId(Input):
    monitor_id: str = Field(..., min_length=1, max_length=256, title="Monitor ID")


class FolderId(Input):
    folder_id: str = Field(..., min_length=1, max_length=256, title="Folder ID")


class TimeRange(Input):
    from_time: Optional[datetime] = Field(None, title="From", description="Inclusive ISO 8601 time.")
    to_time: Optional[datetime] = Field(None, title="To", description="ISO 8601 time.")
    count: Optional[int] = Field(None, ge=1, le=2147483647, title="Count")
    continuation_token: Optional[str] = Field(None, title="Continuation Token", description="Copy continuationToken from the previous response; one page is returned per run.")


class ListFolder(Input):
    """Read root or selected folder contents, one page at a time."""
    operation: Literal["list_folder_contents"] = "list_folder_contents"
    parent_id: Optional[str] = Field(None, title="Parent Folder ID", description="Omit for the account's root folder.")
    continuation_token: Optional[str] = None


class DeleteFolder(FolderId):
    """Delete a folder and every nested folder and monitor."""
    operation: Literal["delete_folder"] = "delete_folder"


class SaveFolder(Input):
    """Create a folder, or update it when a folder ID is supplied."""
    operation: Literal["save_folder"] = "save_folder"
    name: str = Field(..., min_length=1, title="Name")
    folder_id: Optional[str] = Field(None, title="Folder ID", description="Omit to create; supply to update.")
    parent_id: Optional[str] = Field(None, title="Parent Folder ID")


class MoveItems(Input):
    """Move the selected monitors and folders to a destination folder."""
    operation: Literal["move_items"] = "move_items"
    task_ids: list[str] = Field(default_factory=list, title="Monitor IDs")
    folder_ids: list[str] = Field(default_factory=list, title="Folder IDs")
    folder_id: Optional[str] = Field(None, title="Destination Folder ID", description="Omit for root.")

    @model_validator(mode="after")
    def selected(self):
        if not self.task_ids and not self.folder_ids:
            raise ValueError("Choose at least one monitor or folder to move")
        return self


class GetMonitor(MonitorId):
    """Read a monitor's definition and latest data."""
    operation: Literal["get_monitor"] = "get_monitor"


class DeleteMonitor(MonitorId):
    """Delete a monitor and its monitoring configuration."""
    operation: Literal["delete_monitor"] = "delete_monitor"


class SearchMonitors(Input):
    """Search monitors; Wachete returns at most 500 results."""
    operation: Literal["search_monitors"] = "search_monitors"
    query: Optional[str] = Field(None, title="Search Query", description="Wachete search syntax: https://www.wachete.com/faq#faq_search")


class ListPages(MonitorId):
    """Read the pages belonging to a portal/crawler monitor."""
    operation: Literal["list_monitor_pages"] = "list_monitor_pages"


class ListHistory(MonitorId, TimeRange):
    """Read one page of a monitor's content history."""
    operation: Literal["list_history"] = "list_history"
    return_diff: bool = Field(False, title="Return Diff")


class ListNotifications(TimeRange):
    """Read triggered notifications, newest first, optionally for one monitor."""
    operation: Literal["list_notifications"] = "list_notifications"
    task_id: Optional[str] = Field(None, title="Monitor ID")
    html: bool = Field(False, title="Include HTML")


class GetNotification(Input):
    """Read a notification's HTML content in its JSON response envelope."""
    operation: Literal["get_notification"] = "get_notification"
    alert_id: str = Field(..., min_length=1, title="Notification ID")


class Alert(Input):
    type: Literal[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    value: Optional[str] = None


class NotificationEndpoint(Input):
    type: Literal[0, 1, 4, 8, 16, 32, 64, 92]
    value: str


class SaveMonitor(Input):
    """Create or replace a monitor definition with one PUT; supply its ID to update.

    Updating sends the supplied definition, not a patch. Include all settings
    you want to retain, including alerts and notification endpoints.
    """
    operation: Literal["save_monitor"] = "save_monitor"
    monitor_id: Optional[str] = Field(None, title="Monitor ID", description="Omit to create; supply to replace an existing definition.")
    name: str = Field(..., min_length=1, title="Name")
    url: str = Field(..., min_length=1, title="Page URL")
    xpath: str = Field("/", title="XPath")
    recurrence_in_seconds: int = Field(86400, ge=1, le=2147483647, title="Check Interval (Seconds)")
    folder_id: Optional[str] = Field(None, title="Folder ID")
    job_type: Literal[0, 1] = Field(0, title="Monitor Type", description="Contract enum: 0 = SinglePage, 1 = Portal.")
    dynamic_content: bool = Field(False, title="Render JavaScript")
    crawling_depth: int = Field(0, ge=0, le=3, title="Crawling Depth")
    alerts: Optional[list[Alert]] = Field(None, title="Alerts", description="Numeric AlertType values from the Wachete v1 contract.")
    notification_endpoints: Optional[list[NotificationEndpoint]] = Field(None, title="Notification Endpoints", description="Omit to use account defaults. Numeric MessagingServiceType values from the v1 contract.")
    note: Optional[str] = Field(None, title="Note")

    @field_validator("url")
    @classmethod
    def page_url(cls, value):
        if not value.startswith(("https://", "http://")):
            raise ValueError("Use an HTTP or HTTPS page URL")
        return value


Operation = Annotated[Union[ListFolder, DeleteFolder, SaveFolder, MoveItems,
    GetMonitor, DeleteMonitor, SearchMonitors, ListPages, ListHistory,
    ListNotifications, GetNotification, SaveMonitor], Field(discriminator="operation")]


class WacheteConfig(NodeConfig[Operation, WacheteTokenCredential]):
    pass


class WacheteNode(WorkflowNode):
    integration_type = "automation-wachete"
    connection_evidence = ConnectionEvidence(operation="list_folder_contents", noun="Wachete monitors and folders")

    @classmethod
    def get_config_model(cls):
        return WacheteConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Wachete API token")
        c = self.config.config
        op = c.operation
        params, body = {}, None
        method = "GET"
        if op == "list_folder_contents":
            path = "/folder/list"
            params = {"parentId": c.parent_id, "continuationToken": c.continuation_token}
        elif op == "save_folder":
            method, path = "POST", "/folder"
            body = {"id": c.folder_id, "name": c.name, "parentId": c.parent_id}
        elif op == "delete_folder":
            method, path = "DELETE", "/folder/" + quote(c.folder_id, safe="")
        elif op == "move_items":
            method, path = "POST", "/folder/move"
            body = {"taskIds": c.task_ids, "folderIds": c.folder_ids, "folderId": c.folder_id}
        elif op == "save_monitor":
            method, path = "PUT", "/task"
            body = {"id": c.monitor_id, "name": c.name, "url": c.url, "xPath": c.xpath,
                "recurrenceInSeconds": c.recurrence_in_seconds, "folderId": c.folder_id,
                "jobType": c.job_type, "dynamicContent": c.dynamic_content,
                "crawlingDepth": c.crawling_depth, "note": c.note,
                "alerts": [a.model_dump(exclude_none=True) for a in c.alerts] if c.alerts is not None else None,
                "notificationEndpoints": [e.model_dump() for e in c.notification_endpoints] if c.notification_endpoints is not None else None}
        elif op == "search_monitors":
            path, params = "/task/search", {"query": c.query}
        elif op in {"get_monitor", "delete_monitor", "list_monitor_pages"}:
            path = "/task/" + quote(c.monitor_id, safe="")
            if op == "delete_monitor": method = "DELETE"
            if op == "list_monitor_pages": path += "/pages"
        elif op == "get_notification":
            path = "/notification/" + quote(c.alert_id, safe="")
        elif op in {"list_history", "list_notifications"}:
            path = "/data/list/" + quote(c.monitor_id, safe="") if op == "list_history" else "/notification/list"
            params = {"from": c.from_time.isoformat() if c.from_time else None,
                "to": c.to_time.isoformat() if c.to_time else None,
                "count": c.count, "continuationToken": c.continuation_token}
            if op == "list_history": params["returnDiff"] = c.return_diff
            else: params.update({"taskId": c.task_id, "html": c.html})
        else:
            raise ValueError("Unsupported Wachete operation")
        params = {k: v for k, v in params.items() if v is not None}
        if body is not None: body = {k: v for k, v in body.items() if v is not None}
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + self.config.credentials.api_token, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if response.is_error:
            detail = response.text.replace(self.config.credentials.api_token, "[redacted]")
            raise httpx.HTTPStatusError(
                f"Wachete API error {response.status_code}: {detail}",
                request=response.request, response=response,
            )
        if response.is_redirect:
            raise ValueError("Wachete redirected the API request")
        if not response.content:
            if method in {"DELETE", "POST"} and op in {"delete_folder", "delete_monitor", "move_items"}:
                return {"status": "success", "operation": op}
            raise ValueError("Wachete returned an empty JSON response")
        data = response.json()
        if not isinstance(data, (dict, list)):
            raise ValueError("Wachete returned an unexpected JSON response")
        if isinstance(data, dict):
            return data
        return {"items": data}
