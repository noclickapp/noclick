"""MaintainX REST API v1: one documented request per operation.

API keys are pasted by the user. Lists return one page and its opaque cursor;
continuation URLs are never followed and writes are never retried automatically.
"""
from __future__ import annotations

import hashlib
import hmac
import time

from typing import Annotated, Literal, Union

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.getmaintainx.com/v1"
ResourceID = Annotated[int, Field(ge=1)]
Text = Annotated[str, Field(min_length=1, max_length=1000)]
Priority = Literal["NONE", "LOW", "MEDIUM", "HIGH"]
WorkOrderStatus = Literal["OPEN", "IN_PROGRESS", "ON_HOLD", "DONE", "CANCELED"]


class MaintainxApiKey(BaseModel):
    model_config = ConfigDict(
        title="Maintainx API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.getmaintainx.com/settings/integrations/apiKeys",
            "x-credential-instructions": "In MaintainX, open Settings > Integrations > API Keys and generate a key for your user. API access requires Premium or Enterprise. Paste only the key, without Bearer. For a multi-organization key, enter the organization ID to use for list and create operations; record IDs on other operations are global IDs.",
        },
    )
    credential_type: Literal["maintainx_api_key"] = Field(
        "maintainx_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API key",
        min_length=1,
        max_length=4096,
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )
    organization_id: ResourceID | None = Field(
        None,
        title="Organization ID",
        description="Required for multi-organization keys when listing or creating records.",
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste only the API key, without Bearer or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Update(_Input):
    @model_validator(mode="after")
    def changes(self):
        path = ROUTES[self.operation][1]
        changes = {
            key: value
            for key, value in self.model_dump(exclude_none=True).items()
            if key != "operation" and "{" + key + "}" not in path
        }
        if not changes:
            raise ValueError("Supply at least one field to update")
        return self


class _Page(_Input):
    limit: int = Field(100, ge=1, le=200, description="Maximum records in this page.")
    cursor: str | None = Field(
        None,
        max_length=4096,
        description="Opaque nextCursor from the previous page. Leave blank for the first page.",
    )


class Assignee(_Input):
    type: Literal["USER", "TEAM"]
    id: int | str = Field(..., description="Team ID, user ID, or user email address.")


class _WorkOrderFields(_Input):
    description: str | None = Field(None, max_length=100000)
    priority: Priority | None = None
    asset_id: ResourceID | None = None
    location_id: ResourceID | None = None
    assignees: list[Assignee] | None = Field(None, max_length=200)
    due_date: AwareDatetime | None = None
    start_date: AwareDatetime | None = Field(
        None, description="Only valid when due_date is set."
    )
    estimated_time: int | None = Field(
        None, ge=0, description="Estimated duration in seconds."
    )
    external_id: str | None = Field(None, max_length=255)
    categories: list[str] | None = Field(None, max_length=200)


class _NamedFields(_Input):
    description: str | None = Field(None, max_length=100000)
    external_id: str | None = Field(None, max_length=255)


class _AssetFields(_NamedFields):
    location_id: ResourceID | None = None
    parent_id: ResourceID | None = None
    barcode: str | None = Field(None, max_length=1000)
    serial_number: str | None = Field(None, max_length=1000)
    team_ids: list[ResourceID] | None = Field(None, max_length=200)


class _LocationFields(_NamedFields):
    address: str | None = Field(None, max_length=1000)
    barcode: str | None = Field(None, max_length=1000)
    parent_id: ResourceID | None = None


class _PartFields(_NamedFields):
    area: str | None = Field(None, max_length=1000)
    unit_cost: int | None = Field(None, ge=0, description="Cost in cents.")
    available_quantity: int | None = None
    minimum_quantity: int | None = Field(None, ge=0)
    location_id: ResourceID | None = None
    barcode: str | None = Field(None, max_length=1000)


class _WorkRequestFields(_Input):
    description: str | None = Field(None, max_length=100000)
    priority: Priority | None = None
    asset_id: ResourceID | None = None
    location_id: ResourceID | None = None
    approver_team_id: ResourceID | None = None
    external_id: str | None = Field(None, max_length=255)


class ListOrganizations(_Page):
    """List organizations accessible to the API key."""

    operation: Literal["list_organizations"] = "list_organizations"


class ListWorkOrders(_Page):
    """List one page of work orders with optional filters."""

    operation: Literal["list_work_orders"] = "list_work_orders"
    title: Text | None = None
    statuses: list[WorkOrderStatus] | None = Field(None, max_length=5)
    priorities: list[Priority] | None = Field(None, max_length=4)
    assets: list[ResourceID] | None = Field(None, max_length=200)
    locations: list[ResourceID] | None = Field(None, max_length=200)


class GetWorkOrder(_Input):
    """Read a work order by its global ID."""

    operation: Literal["get_work_order"] = "get_work_order"
    work_order_id: ResourceID


class CreateWorkOrder(_WorkOrderFields):
    """Create a work order; returns its new ID."""

    operation: Literal["create_work_order"] = "create_work_order"
    title: Text


class UpdateWorkOrder(_WorkOrderFields, _Update):
    """Update supplied work order fields; assignees replace the assignment list."""

    operation: Literal["update_work_order"] = "update_work_order"
    work_order_id: ResourceID
    title: Text | None = None


class UpdateWorkOrderStatus(_Input):
    """Change the work order status."""

    operation: Literal["update_work_order_status"] = "update_work_order_status"
    work_order_id: ResourceID
    status: WorkOrderStatus


class CreateWorkOrderComment(_Input):
    """Add a comment to a work order."""

    operation: Literal["create_work_order_comment"] = "create_work_order_comment"
    work_order_id: ResourceID
    content: str = Field(..., min_length=1, max_length=100000)


class ListWorkOrderComments(_Page):
    """List one page of work order comments."""

    operation: Literal["list_work_order_comments"] = "list_work_order_comments"
    work_order_id: ResourceID


class ListAssets(_Page):
    """List one page of assets."""

    operation: Literal["list_assets"] = "list_assets"


class GetAsset(_Input):
    """Read a asset by its global ID."""

    operation: Literal["get_asset"] = "get_asset"
    asset_id: ResourceID


class CreateAsset(_AssetFields):
    """Create a asset; returns its new ID."""

    operation: Literal["create_asset"] = "create_asset"
    name: Text


class UpdateAsset(_AssetFields, _Update):
    """Update a asset, sending only supplied fields."""

    operation: Literal["update_asset"] = "update_asset"
    asset_id: ResourceID
    name: Text | None = None


class ListLocations(_Page):
    """List one page of locations."""

    operation: Literal["list_locations"] = "list_locations"
    name: Text | None = None


class GetLocation(_Input):
    """Read a location by its global ID."""

    operation: Literal["get_location"] = "get_location"
    location_id: ResourceID


class CreateLocation(_LocationFields):
    """Create a location; returns its new ID."""

    operation: Literal["create_location"] = "create_location"
    name: Text


class UpdateLocation(_LocationFields, _Update):
    """Update a location, sending only supplied fields."""

    operation: Literal["update_location"] = "update_location"
    location_id: ResourceID
    name: Text | None = None


class ListParts(_Page):
    """List one page of parts."""

    operation: Literal["list_parts"] = "list_parts"


class GetPart(_Input):
    """Read a part by its global ID."""

    operation: Literal["get_part"] = "get_part"
    part_id: ResourceID


class CreatePart(_PartFields):
    """Create a part; returns its new ID."""

    operation: Literal["create_part"] = "create_part"
    name: Text


class UpdatePart(_PartFields, _Update):
    """Update a part, sending only supplied fields."""

    operation: Literal["update_part"] = "update_part"
    part_id: ResourceID
    name: Text | None = None


class ListWorkRequests(_Page):
    """List one page of work requests."""

    operation: Literal["list_work_requests"] = "list_work_requests"
    title: Text | None = None


class GetWorkRequest(_Input):
    """Read a work request by its global ID."""

    operation: Literal["get_work_request"] = "get_work_request"
    work_request_id: ResourceID


class CreateWorkRequest(_WorkRequestFields):
    """Submit a work request; returns its new ID."""

    operation: Literal["create_work_request"] = "create_work_request"
    title: Text


class ListUsers(_Page):
    """List one page of users."""

    operation: Literal["list_users"] = "list_users"


class ListTeams(_Page):
    """List one page of teams."""

    operation: Literal["list_teams"] = "list_teams"


# Subscription types and event fields: https://api.getmaintainx.com/v1/openapi.json
WEBHOOK_EVENTS = {
    "NEW_WORK_ORDER": ("Work order created", "workOrderId", "work order"),
    "WORK_ORDER_CHANGE": ("Work order updated", "workOrderId", "work order"),
    "WORK_ORDER_STATUS_CHANGE": ("Work order status changed", "workOrderId", "work order"),
    "NEW_WORK_REQUEST": ("Work request created", "workRequestId", "work request"),
    "NEW_COMMENT_ON_WORK_ORDER": ("Work order comment added", "workOrderId", "work order"),
    "ASSET_CHANGE": ("Asset updated", "assetId", "asset"),
    "PART_QUANTITY_CHANGE": ("Part quantity changed", "partId", "part"),
}


class OnMaintainxEvent(WebhookTriggerConfigBase):
    """Start a workflow or agent when a selected MaintainX event occurs."""

    operation: Literal["on_event"] = Field(
        "on_event", json_schema_extra={"x-is-trigger": True, "x-category": "Triggers",
                                      "x-display-name": "On MaintainX Event", "ui:hidden": True})
    event_type: Literal[*WEBHOOK_EVENTS] = Field(
        "NEW_WORK_ORDER", title="Event",
        json_schema_extra={"enumNames": [value[0] for value in WEBHOOK_EVENTS.values()]})
    webhook_url: str | None = Field(
        None, title="Webhook URL", description="Registered with MaintainX automatically.",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


MaintainxOperation = Annotated[
    Union[
        OnMaintainxEvent,
        ListOrganizations,
        ListWorkOrders,
        GetWorkOrder,
        CreateWorkOrder,
        UpdateWorkOrder,
        UpdateWorkOrderStatus,
        CreateWorkOrderComment,
        ListWorkOrderComments,
        ListAssets,
        GetAsset,
        CreateAsset,
        UpdateAsset,
        ListLocations,
        GetLocation,
        CreateLocation,
        UpdateLocation,
        ListParts,
        GetPart,
        CreatePart,
        UpdatePart,
        ListWorkRequests,
        GetWorkRequest,
        CreateWorkRequest,
        ListUsers,
        ListTeams,
    ],
    Field(discriminator="operation"),
]


class MaintainxConfig(NodeConfig[MaintainxOperation, MaintainxApiKey]):
    model_config = ConfigDict(title="MaintainX Configuration")


ROUTES = {
    "list_organizations": ("GET", "/organizations", "organizations"),
    "list_work_orders": ("GET", "/workorders", "workOrders"),
    "get_work_order": ("GET", "/workorders/{work_order_id}", "workOrder"),
    "create_work_order": ("POST", "/workorders", "id"),
    "update_work_order": ("PATCH", "/workorders/{work_order_id}", "workOrder"),
    "update_work_order_status": (
        "PATCH",
        "/workorders/{work_order_id}/status",
        "workOrder",
    ),
    "create_work_order_comment": ("POST", "/workorders/{work_order_id}/comments", "id"),
    "list_work_order_comments": (
        "GET",
        "/workorders/{work_order_id}/comments",
        "comments",
    ),
    "list_assets": ("GET", "/assets", "assets"),
    "get_asset": ("GET", "/assets/{asset_id}", "asset"),
    "create_asset": ("POST", "/assets", "id"),
    "update_asset": ("PATCH", "/assets/{asset_id}", "asset"),
    "list_locations": ("GET", "/locations", "locations"),
    "get_location": ("GET", "/locations/{location_id}", "location"),
    "create_location": ("POST", "/locations", "id"),
    "update_location": ("PATCH", "/locations/{location_id}", "location"),
    "list_parts": ("GET", "/parts", "parts"),
    "get_part": ("GET", "/parts/{part_id}", "part"),
    "create_part": ("POST", "/parts", "id"),
    "update_part": ("PATCH", "/parts/{part_id}", "part"),
    "list_work_requests": ("GET", "/workrequests", "workRequests"),
    "get_work_request": ("GET", "/workrequests/{work_request_id}", "workRequest"),
    "create_work_request": ("POST", "/workrequests", "id"),
    "list_users": ("GET", "/users", "users"),
    "list_teams": ("GET", "/teams", "teams"),
}

WIRE_NAMES = {
    "asset_id": "assetId",
    "location_id": "locationId",
    "parent_id": "parentId",
    "team_ids": "teamIds",
    "serial_number": "serialNumber",
    "unit_cost": "unitCost",
    "available_quantity": "availableQuantity",
    "minimum_quantity": "minimumQuantity",
    "external_id": "externalId",
    "due_date": "dueDate",
    "start_date": "startDate",
    "estimated_time": "estimatedTime",
    "approver_team_id": "approverTeamId",
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class MaintainxNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-maintainx"
    connection_evidence = ConnectionEvidence(
        operation="list_organizations", noun="organizations"
    )

    @classmethod
    def get_config_model(cls):
        return MaintainxConfig

    @classmethod
    async def _webhook_request(cls, credential, method, path, body=None):
        auth = MaintainxApiKey.model_validate(credential)
        headers = {"Authorization": "Bearer " + auth.api_key, "Accept": "application/json"}
        if auth.organization_id:
            headers["x-organization-id"] = str(auth.organization_id)
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers,
                                            **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            raise ValueError(f"MaintainX webhook request failed (HTTP {response.status_code})")
        return response.json() if response.content else {}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = (config or {}).get("event_type", "NEW_WORK_ORDER")
        if event not in WEBHOOK_EVENTS:
            raise ValueError("Choose a supported MaintainX event")
        if len(webhook_url) > 512:
            raise ValueError("MaintainX webhook URLs must be at most 512 characters")
        body = {"type": event, "url": webhook_url}
        if event in {"NEW_WORK_ORDER", "WORK_ORDER_CHANGE", "WORK_ORDER_STATUS_CHANGE", "ASSET_CHANGE"}:
            body["options"] = {"serializeEntity": True}
        data = await cls._webhook_request(credential, "POST", "/subscriptions", body)
        subscription_id = data.get("id")
        if not isinstance(subscription_id, int) or isinstance(subscription_id, bool) or subscription_id < 1:
            raise ValueError("MaintainX did not return a subscription ID")
        try:
            if data.get("status") != "VALID":
                raise ValueError("MaintainX subscription needs approval; contact MaintainX support")
            secret = data.get("secret")
            if not secret:
                secret = (await cls._webhook_request(
                    credential, "GET", f"/subscriptions/{subscription_id}/secret")).get("secret")
            if not isinstance(secret, str) or not secret:
                raise ValueError("MaintainX did not return a signing secret")
        except Exception:
            await cls._webhook_request(credential, "DELETE", f"/subscriptions/{subscription_id}")
            raise
        return {"external_webhook_id": str(subscription_id), "signing_secret": secret}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        subscription_id = (config or {}).get("external_webhook_id")
        if not subscription_id or not credential:
            return
        subscription_id = int(subscription_id)
        if subscription_id < 1:
            raise ValueError("Invalid MaintainX subscription ID")
        await cls._webhook_request(credential, "DELETE", f"/subscriptions/{subscription_id}")

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": (config or {}).get("event_type", "NEW_WORK_ORDER")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # https://help.getmaintainx.com/build/webhooks#verify-a-webhook-signature
        secret = (config or {}).get("signing_secret")
        if not isinstance(secret, str) or not secret:
            return False
        header = next((v for k, v in headers.items()
                       if k.lower() == "x-maintainx-webhook-body-signature"), "")
        if not isinstance(header, str):
            return False
        fields = [field.strip().split("=", 1) for field in header.split(",")]
        timestamps = [v for k, v in fields if k == "t"] if all(len(f) == 2 for f in fields) else []
        if len(timestamps) != 1 or not timestamps[0].isascii() or not timestamps[0].isdigit():
            return False
        timestamp = timestamps[0]
        if len(timestamp) > 12 or abs(time.time() - int(timestamp)) > 300:
            return False
        expected = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        return any(hmac.compare_digest(v, expected) for k, v in fields if k == "v1" and v.isascii())

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return ((config or {}).get("operation") == "on_event"
                and payload.get("eventType") == (config or {}).get("event_type", "NEW_WORK_ORDER"))

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("eventType") not in WEBHOOK_EVENTS:
            return super().resolve_agent_event(output)
        event = output["eventType"]
        label, id_field, noun = WEBHOOK_EVENTS[event]
        rid = output.get(id_field)
        org = output.get("orgId")
        lines = [f"MaintainX: {label} — {noun} {rid}",
                 f"Organization: {org}. At: {output.get('occurredAt')}."]
        if event in {"NEW_WORK_ORDER", "WORK_ORDER_CHANGE", "WORK_ORDER_STATUS_CHANGE", "PART_QUANTITY_CHANGE"}:
            user = output.get("userId")
            if user is not None:
                lines.append(f"By user {user}.")
            elif event != "PART_QUANTITY_CHANGE":
                lines.append("System-initiated event.")
        if event in {"NEW_WORK_ORDER", "WORK_ORDER_CHANGE", "WORK_ORDER_STATUS_CHANGE"}:
            record = output.get("newWorkOrder") or {}
            if record.get("title"):
                lines.append(f"Title: {record['title']}")
            if record.get("description"):
                lines.append(str(record["description"])[:3000])
        if event == "WORK_ORDER_STATUS_CHANGE":
            lines.append(f"Status: {output.get('oldStatus')} → {output.get('newStatus')}.")
        if event == "NEW_COMMENT_ON_WORK_ORDER":
            lines.append(f"Comment ({output.get('type')}): {str(output.get('comment') or '')[:3000]}")
            if output.get("url"):
                lines.append(f"Attachment (expires in 60 minutes): {output['url']}")
        if event == "ASSET_CHANGE":
            record = output.get("newAsset") or {}
            if record.get("name"):
                lines.append(f"Name: {record['name']}")
            if record.get("description"):
                lines.append(str(record["description"])[:3000])
        if event == "PART_QUANTITY_CHANGE":
            lines.append(f"Quantity change: {output.get('quantityDiff')} units.")
            for field, label in (("oldQuantity", "Previous quantity"), ("newQuantity", "Current quantity")):
                if output.get(field) is not None:
                    lines.append(f"{label}: {output[field]}.")
        lines.append(f"To act: use get_{noun.replace(' ', '_')} with {noun.replace(' ', '_')}_id={rid} (organization {org}).")
        return {"text": "\n".join(lines), "title": f"{label}: {rid}",
                "conversation_key": f"maintainx:{org}:{noun.replace(' ', '_')}:{rid}"}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a MaintainX API key")
        config = self.config.config
        credential = self.config.credentials
        if isinstance(config, OnMaintainxEvent):
            return self.no_event_output(config.operation)
        method, path, key = ROUTES[config.operation]
        values = config.model_dump(
            mode="json", exclude={"operation"}, exclude_none=True
        )
        for name in tuple(values):
            if "{" + name + "}" in path:
                path = path.replace("{" + name + "}", str(values.pop(name)))
        if values.get("start_date") and not values.get("due_date"):
            raise ValueError("Set due_date when start_date is supplied")
        values = {WIRE_NAMES.get(k, k): v for k, v in values.items()}
        headers = {
            "Authorization": "Bearer " + credential.api_key,
            "Accept": "application/json",
        }
        # The published contract scopes list/create calls with this header.
        # Individual records use globally unique IDs, not sequential IDs.
        if (
            credential.organization_id
            and "{" not in ROUTES[config.operation][1]
            and config.operation != "list_organizations"
        ):
            headers["x-organization-id"] = str(credential.organization_id)
        kwargs = {"params": values} if method == "GET" else {"json": values}
        async with guarded_async_client(
            timeout=30, follow_redirects=False, trust_env=False
        ) as client:
            response = await client.request(
                method, BASE_URL + path, headers=headers, **kwargs
            )
        if not 200 <= response.status_code < 300:
            detail = response.text.replace(credential.api_key, "[redacted]")[:2000]
            raise ValueError(
                f"MaintainX rejected the request (HTTP {response.status_code}): {detail}"
            )
        try:
            body = response.json()
        except ValueError:
            raise ValueError("MaintainX returned a non-JSON response") from None
        if not isinstance(body, dict) or body.get("error") or body.get("errors"):
            raise ValueError("MaintainX returned an invalid response envelope")
        if config.operation.startswith("list_"):
            if not isinstance(body.get(key), list) or any(
                not isinstance(row, dict) for row in body[key]
            ):
                raise ValueError("MaintainX returned an invalid resource list")
            if (
                "nextCursor" not in body
                or body["nextCursor"] is not None
                and not isinstance(body["nextCursor"], str)
            ):
                raise ValueError("MaintainX returned invalid pagination metadata")
            # The URL is data only. The caller supplies nextCursor on a later run.
            result = {
                "status": "success",
                "items": body[key],
                "next_cursor": body["nextCursor"],
                "has_more": body["nextCursor"] is not None,
                "data": body,
            }
        else:
            value = body.get(key)
            if key == "id":
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError("MaintainX did not return the created record ID")
            elif not isinstance(value, dict):
                raise ValueError("MaintainX returned an invalid resource response")
            result = {"status": "success", "data": body}
        return _redact(result, credential.api_key)
