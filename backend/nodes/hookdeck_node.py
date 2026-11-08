"""Hookdeck Event Gateway API node.

The 2025-07-01 Admin API contract is published by Hookdeck at
https://api.hookdeck.com/2025-07-01/openapi.
"""

import time
from typing import Annotated, Any, Dict, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

API_BASE = "https://api.hookdeck.com/2025-07-01"


class HookdeckApiKeyCredential(BaseModel):
    credential_type: Literal["hookdeck_api_key"] = Field(
        "hookdeck_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(..., title="Project API Key", json_schema_extra={"ui:widget": "password"})

    model_config = ConfigDict(title="Hookdeck API Key", json_schema_extra={
        "x-credential-url": "https://dashboard.hookdeck.com/settings/project/secrets",
        "x-credential-instructions": "Create a project API key in Settings > Project > Secrets, then paste it here.",
    })


class ListPage(BaseModel):
    limit: Optional[int] = Field(100, ge=1, le=100, title="Limit")
    next: Optional[str] = Field(None, title="Next cursor")
    prev: Optional[str] = Field(None, title="Previous cursor")


class SourceFields(BaseModel):
    name: str = Field(..., min_length=1, max_length=155, pattern=r"^[A-Za-z0-9_-]+$", title="Source Name")
    description: Optional[str] = Field(None, max_length=500, title="Description")


class DestinationFields(BaseModel):
    name: str = Field(..., min_length=1, max_length=155, pattern=r"^[A-Za-z0-9_-]+$", title="Destination Name")
    destination_type: Literal["HTTP", "MOCK_API"] = Field("HTTP", title="Destination Type")
    url: Optional[str] = Field(None, title="HTTP URL", description="Required for HTTP destinations. Use HTTPS for public endpoints.")
    description: Optional[str] = Field(None, max_length=500, title="Description")


class ConnectionFields(BaseModel):
    source_id: str = Field(..., title="Source ID")
    destination_id: str = Field(..., title="Destination ID")
    name: Optional[str] = Field(None, max_length=155, pattern=r"^[A-Za-z0-9_-]+$", title="Connection Name")
    description: Optional[str] = Field(None, max_length=500, title="Description")


class IdField(BaseModel):
    id: str = Field(..., min_length=1, title="ID")


def operation_field(value: str, category: str, label: str):
    return Field(value, title=label, json_schema_extra={
        "ui:hidden": True, "x-category": category, "x-display-name": label, "x-is-trigger": False,
    })


class ListSources(ListPage):
    """List webhook sources with pagination and an optional name filter."""
    operation: Literal["list_sources"] = operation_field("list_sources", "Sources", "List Sources")
    name: Optional[str] = Field(None, title="Name Filter")


class GetSource(IdField):
    """Read a webhook source by ID, including its inbound URL."""
    operation: Literal["get_source"] = operation_field("get_source", "Sources", "Get Source")


class CreateSource(SourceFields):
    """Create a webhook source for inbound events."""
    operation: Literal["create_source"] = operation_field("create_source", "Sources", "Create Source")


class UpdateSource(IdField):
    """Rename or describe an existing source."""
    operation: Literal["update_source"] = operation_field("update_source", "Sources", "Update Source")
    name: Optional[str] = Field(None, max_length=155, pattern=r"^[A-Za-z0-9_-]+$", title="New Name")
    description: Optional[str] = Field(None, max_length=500, title="Description")


class DeleteSource(IdField):
    """Delete a webhook source by ID."""
    operation: Literal["delete_source"] = operation_field("delete_source", "Sources", "Delete Source")


class ListDestinations(ListPage):
    """List HTTP and mock destinations in the project."""
    operation: Literal["list_destinations"] = operation_field("list_destinations", "Destinations", "List Destinations")
    name: Optional[str] = Field(None, title="Name Filter")


class GetDestination(IdField):
    """Read a destination by ID."""
    operation: Literal["get_destination"] = operation_field("get_destination", "Destinations", "Get Destination")


class CreateDestination(DestinationFields):
    """Create an HTTP endpoint or mock destination."""
    operation: Literal["create_destination"] = operation_field("create_destination", "Destinations", "Create Destination")


class UpdateDestination(IdField):
    """Change a destination name, description, or HTTP URL."""
    operation: Literal["update_destination"] = operation_field("update_destination", "Destinations", "Update Destination")
    name: Optional[str] = Field(None, max_length=155, pattern=r"^[A-Za-z0-9_-]+$", title="New Name")
    url: Optional[str] = Field(None, title="HTTP URL")
    description: Optional[str] = Field(None, max_length=500, title="Description")


class DeleteDestination(IdField):
    """Delete a destination by ID."""
    operation: Literal["delete_destination"] = operation_field("delete_destination", "Destinations", "Delete Destination")


class ListConnections(ListPage):
    """List source-to-destination routes, optionally filtered by either end."""
    operation: Literal["list_connections"] = operation_field("list_connections", "Connections", "List Connections")
    source_id: Optional[str] = Field(None, title="Source ID Filter")
    destination_id: Optional[str] = Field(None, title="Destination ID Filter")


class GetConnection(IdField):
    """Read a connection and its routing details."""
    operation: Literal["get_connection"] = operation_field("get_connection", "Connections", "Get Connection")


class CreateConnection(ConnectionFields):
    """Connect an existing source to an existing destination."""
    operation: Literal["create_connection"] = operation_field("create_connection", "Connections", "Create Connection")


class UpdateConnection(IdField):
    """Rename or describe an existing connection."""
    operation: Literal["update_connection"] = operation_field("update_connection", "Connections", "Update Connection")
    name: Optional[str] = Field(None, max_length=155, pattern=r"^[A-Za-z0-9_-]+$", title="New Name")
    description: Optional[str] = Field(None, max_length=500, title="Description")


class DeleteConnection(IdField):
    """Delete a connection by ID."""
    operation: Literal["delete_connection"] = operation_field("delete_connection", "Connections", "Delete Connection")


class PauseConnection(IdField):
    """Pause delivery on a connection without deleting it."""
    operation: Literal["pause_connection"] = operation_field("pause_connection", "Connections", "Pause Connection")


class UnpauseConnection(IdField):
    """Resume delivery on a paused connection."""
    operation: Literal["unpause_connection"] = operation_field("unpause_connection", "Connections", "Unpause Connection")


class ListEvents(ListPage):
    """List events and delivery status for a source or destination."""
    operation: Literal["list_events"] = operation_field("list_events", "Events", "List Events")
    source_id: Optional[str] = Field(None, title="Source ID Filter")
    destination_id: Optional[str] = Field(None, title="Destination ID Filter")
    status: Optional[str] = Field(None, title="Status Filter")


class GetEvent(IdField):
    """Read an event and its delivery attempts."""
    operation: Literal["get_event"] = operation_field("get_event", "Events", "Get Event")


class RetryEvent(IdField):
    """Retry delivery of a failed event."""
    operation: Literal["retry_event"] = operation_field("retry_event", "Events", "Retry Event")


class CancelEvent(IdField):
    """Cancel pending delivery of an event."""
    operation: Literal["cancel_event"] = operation_field("cancel_event", "Events", "Cancel Event")


class ListRequests(ListPage):
    """List incoming webhook requests and ingestion status."""
    operation: Literal["list_requests"] = operation_field("list_requests", "Requests", "List Requests")
    source_id: Optional[str] = Field(None, title="Source ID Filter")
    status: Optional[str] = Field(None, title="Status Filter")


class GetRequest(IdField):
    """Read a specific incoming webhook request."""
    operation: Literal["get_request"] = operation_field("get_request", "Requests", "Get Request")


class ListIssues(ListPage):
    """List Hookdeck delivery and ingestion issues."""
    operation: Literal["list_issues"] = operation_field("list_issues", "Issues", "List Issues")
    status: Optional[str] = Field(None, title="Status Filter")


class GetIssue(IdField):
    """Read one delivery or ingestion issue."""
    operation: Literal["get_issue"] = operation_field("get_issue", "Issues", "Get Issue")


HookdeckConfig = Annotated[Union[
    ListSources, GetSource, CreateSource, UpdateSource, DeleteSource,
    ListDestinations, GetDestination, CreateDestination, UpdateDestination, DeleteDestination,
    ListConnections, GetConnection, CreateConnection, UpdateConnection, DeleteConnection,
    PauseConnection, UnpauseConnection, ListEvents, GetEvent, RetryEvent, CancelEvent,
    ListRequests, GetRequest, ListIssues, GetIssue,
], Discriminator("operation")]


class HookdeckNodeConfig(NodeConfig[HookdeckConfig, HookdeckApiKeyCredential]):
    pass


def _body(operation: BaseModel, *names: str) -> Dict[str, Any]:
    return {name: value for name in names if (value := getattr(operation, name, None)) is not None}


def _request_spec(operation: BaseModel) -> tuple[str, str, Optional[dict], Optional[dict]]:
    """Map typed canvas operations to Hookdeck's documented API routes."""
    name = operation.operation
    area = next((segment for segment in ("sources", "destinations", "connections", "events", "requests", "issues")
                 if name.endswith(segment[:-1]) or name.endswith(segment)), None)
    if area is None:
        raise ValueError(f"Unsupported Hookdeck operation: {name}")
    path = f"/{area}"
    if name.startswith("list_"):
        return "GET", path, _body(operation, "limit", "next", "prev", "name", "source_id", "destination_id", "status"), None
    if hasattr(operation, "id"):
        path += "/" + quote(operation.id, safe="")
    if name.startswith("get_"):
        return "GET", path, None, None
    if name.startswith("delete_"):
        return "DELETE", path, None, None
    if name.startswith("create_"):
        method = "POST"
        if area == "sources":
            body = _body(operation, "name", "description")
        elif area == "destinations":
            if operation.destination_type == "HTTP" and not operation.url:
                raise ValueError("HTTP destinations require a URL")
            body = _body(operation, "name", "description")
            body["type"] = operation.destination_type
            body["config"] = {"url": operation.url} if operation.destination_type == "HTTP" else {}
        else:
            body = _body(operation, "name", "description", "source_id", "destination_id")
        return method, path, None, body
    if name.startswith("update_"):
        body = _body(operation, "name", "description")
        if area == "destinations" and operation.url:
            body["config"] = {"url": operation.url}
        if not body:
            raise ValueError("Provide at least one field to update")
        return "PUT", path, None, body
    if name in ("pause_connection", "unpause_connection", "retry_event", "cancel_event"):
        suffix = name.split("_", 1)[0]
        return ("POST" if suffix == "retry" else "PUT"), f"{path}/{suffix}", None, None
    raise ValueError(f"Unsupported Hookdeck operation: {name}")


async def _hookdeck_request(method: str, path: str, api_key: str, *, params=None, body=None, action: str) -> Dict[str, Any]:
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(method, API_BASE + path,
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                params=params, json=body)
        elapsed = round((time.monotonic() - started) * 1000, 2)
        try:
            payload = response.json() if response.content else None
        except ValueError:
            payload = {"raw": response.text}
        if response.is_error:
            message = payload.get("message") or payload.get("error") if isinstance(payload, dict) else str(payload)
            return {"status": "error", "action": action, "status_code": response.status_code,
                    "error": str(message), "timing_ms": {"api_request": elapsed}}
        if action.startswith("list_") and isinstance(payload, dict) and "models" in payload:
            data = {"items": payload["models"], "count": payload.get("count"),
                    "pagination": payload.get("pagination")}
        else:
            data = payload if payload is not None else {"success": True}
        return {"status": "success", "action": action, "status_code": response.status_code,
                "data": data, "timing_ms": {"api_request": elapsed}}
    except httpx.TimeoutException:
        return {"status": "error", "action": action, "error": "Hookdeck request timed out", "status_code": 408}
    except httpx.HTTPError as exc:
        return {"status": "error", "action": action, "error": str(exc), "status_code": 502}


class HookdeckNode(WorkflowNode):
    integration_type = "automation-hookdeck"
    edit_examples = [
        "List recent Hookdeck events and their delivery status",
        "Create a webhook source and connect it to an HTTP destination",
        "Pause a Hookdeck connection while the downstream service is under maintenance",
    ]
    connection_evidence = ConnectionEvidence(
        operation="list_sources", noun="sources", label_keys=("name",), proves="account"
    )

    @classmethod
    def get_config_model(cls):
        return HookdeckNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        config = self.config
        if not isinstance(config, HookdeckNodeConfig):
            raise ValueError("Valid Hookdeck configuration is required")
        if not config.credentials or not config.credentials.api_key:
            raise ValueError("Add a Hookdeck project API key credential")
        operation = config.config
        try:
            method, path, params, body = _request_spec(operation)
        except ValueError as exc:
            return {"status": "error", "action": operation.operation, "error": str(exc), "status_code": 400}
        return await _hookdeck_request(method, path, config.credentials.api_key,
                                       params=params, body=body, action=operation.operation)
