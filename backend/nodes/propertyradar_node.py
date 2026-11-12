"""PropertyRadar API 5.3.1.0: fixed property, list and account operations.

Contract: https://developers.propertyradar.com/_spec/api.yaml
Token setup: https://developers.propertyradar.com/ (Getting started).
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE = "https://api.propertyradar.com"


class PropertyRadarTokenCredential(BaseModel):
    model_config = ConfigDict(title="PropertyRadar API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.propertyradar.com/",
            "x-credential-instructions": "In PropertyRadar Account Settings, open Integrations and reveal your API token. Paste the token here. API access must be enabled on your account.",
        })
    credential_type: Literal["propertyradar_api_token"] = Field("propertyradar_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, title="API token", json_schema_extra={"ui:widget": "password"})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _ListID(_Input):
    list_id: int = Field(..., gt=0, description="PropertyRadar ListID.")


class _Property(_Input):
    radar_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$", description="PropertyRadar RadarID.")
    purchase: Literal[0, 1] = Field(0, description="0 previews cost; 1 purchases records and incurs non-refundable provider charges.")


class Criterion(_Input):
    name: str = Field(..., min_length=1, description="A documented PropertyRadar criterion, such as State, ZipFive or RadarID.")
    value: Union[str, list[Any], dict[str, Any]] = Field(..., description="Criterion value in the provider's Criteria format. See https://developers.propertyradar.com/criteria")


class ListLists(_Input):
    """Read the account's lists, with a bounded result limit."""
    operation: Literal["list_lists"] = "list_lists"
    limit: int = Field(100, ge=1, le=1000)
    list_type: Literal["dynamic", "static", "import"] | None = None
    group_name: str | None = None


class CreateList(_Input):
    """Create a static list or a dynamic list with criteria."""
    operation: Literal["create_list"] = "create_list"
    list_name: str = Field(..., min_length=1, max_length=50)
    list_type: Literal["static", "dynamic"] = "static"
    criteria: list[Criterion] | None = Field(None, min_length=1, max_length=500)
    group_name: str | None = None
    is_monitored: Literal[0, 1] = 0

    @model_validator(mode="after")
    def criteria_for_type(self):
        if self.list_type == "dynamic" and not self.criteria:
            raise ValueError("Dynamic lists require criteria")
        if self.list_type == "static" and self.criteria is not None:
            raise ValueError("Static lists do not accept criteria")
        return self


class GetList(_ListID):
    """Read one list's details."""
    operation: Literal["get_list"] = "get_list"


class UpdateList(_ListID):
    """Update only the supplied list attributes."""
    operation: Literal["update_list"] = "update_list"
    list_name: str | None = Field(None, min_length=1, max_length=50)
    is_monitored: Literal[0, 1] | None = None
    display_order: int | None = None

    @model_validator(mode="after")
    def changed(self):
        if all(getattr(self, k) is None for k in ("list_name", "is_monitored", "display_order")):
            raise ValueError("Supply at least one list attribute")
        return self


class DeleteList(_ListID):
    """Delete the selected list."""
    operation: Literal["delete_list"] = "delete_list"


class ListItems(_ListID):
    """Read a page of items saved in a list."""
    operation: Literal["list_items"] = "list_items"
    start: int = Field(0, ge=0)
    limit: int = Field(100, ge=1, le=1000)
    status_level: int | None = Field(None, ge=1, le=9)
    added_since: str | None = None


class AddItems(_ListID):
    """Add properties matching criteria to a static list; use RadarID criteria for selected IDs."""
    operation: Literal["add_items"] = "add_items"
    criteria: list[Criterion] = Field(..., min_length=1, max_length=500)


class RemoveItem(_ListID):
    """Remove one property from the selected list."""
    operation: Literal["remove_item"] = "remove_item"
    radar_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class SearchProperties(_Input):
    """Search properties by criteria with explicit purchase and pagination controls."""
    operation: Literal["search_properties"] = "search_properties"
    criteria: list[Criterion] = Field(..., min_length=1, max_length=500)
    purchase: Literal[0, 1] = Field(0, description="0 previews cost; 1 purchases records and incurs non-refundable provider charges.")
    limit: int = Field(100, ge=1, le=500)
    start: int = Field(0, ge=0)
    page_token: str | None = Field(None, description="Provider PageToken returned by a previous search; pass it unchanged.")


class GetProperty(_Property):
    """Read a property by RadarID, or preview its cost."""
    operation: Literal["get_property"] = "get_property"


class GetOwners(_Property):
    """Read the owners of a property, or preview its cost."""
    operation: Literal["get_owners"] = "get_owners"


class GetTransactions(_Property):
    """Read a property's transaction history, or preview its cost."""
    operation: Literal["get_transactions"] = "get_transactions"
    limit: int = Field(100, ge=1, le=500)


class GetComparableSales(_Property):
    """Read comparable sales, or preview their cost."""
    operation: Literal["get_comparable_sales"] = "get_comparable_sales"
    limit: int = Field(10, ge=1, le=100)


class GetComparableListings(_Property):
    """Read comparable listings, or preview their cost."""
    operation: Literal["get_comparable_listings"] = "get_comparable_listings"
    limit: int = Field(10, ge=1, le=100)


class GetParcels(_Property):
    """Read parcel boundaries, or preview their cost."""
    operation: Literal["get_parcels"] = "get_parcels"


class ListMembers(_Input):
    """Read members of the connected account."""
    operation: Literal["list_members"] = "list_members"


class ListStatuses(_Input):
    """Read the connected account's status labels in menu format."""
    operation: Literal["list_statuses"] = "list_statuses"


class GetAutomation(_ListID):
    """Read the selected list's automation configuration."""
    operation: Literal["get_automation"] = "get_automation"


class ListWebhooks(_Input):
    """Read a page of registered webhooks, excluding their secrets."""
    operation: Literal["list_webhooks"] = "list_webhooks"
    start: int = Field(0, ge=0)
    limit: int = Field(100, ge=1, le=1000)


class DeleteWebhook(_Input):
    """Delete the selected registered webhook."""
    operation: Literal["delete_webhook"] = "delete_webhook"
    webhook_id: int = Field(..., gt=0)


# PropertyRadar's own MCP server: agents get its tools through a person's PropertyRadar sign-in.
PropertyradarMcpCredential = mcp_credential("propertyradar", "https://mcp.propertyradar.com/", app="PropertyRadar")
PropertyRadarCredential = Union[PropertyRadarTokenCredential, PropertyradarMcpCredential]


PropertyRadarOperation = Annotated[Union[
    ListLists, CreateList, GetList, UpdateList, DeleteList, ListItems, AddItems,
    RemoveItem, SearchProperties, GetProperty, GetOwners, GetTransactions,
    GetComparableSales, GetComparableListings, GetParcels, ListMembers,
    ListStatuses, GetAutomation, ListWebhooks, DeleteWebhook,
], Field(discriminator="operation")]


class PropertyRadarConfig(NodeConfig[PropertyRadarOperation, PropertyRadarCredential]):
    pass


# Each user-facing operation maps to exactly one published API operation.
ROUTES = {
    "list_lists": ("GET", "/v1/lists"),
    "create_list": ("POST", "/v1/lists"),
    "get_list": ("GET", "/v1/lists/{list_id}"),
    "update_list": ("PATCH", "/v1/lists/{list_id}"),
    "delete_list": ("DELETE", "/v1/lists/{list_id}"),
    "list_items": ("GET", "/v1/lists/{list_id}/items"),
    "add_items": ("PUT", "/v1/lists/{list_id}/items"),
    "remove_item": ("DELETE", "/v1/lists/{list_id}/items/{radar_id}"),
    "search_properties": ("POST", "/v1/properties"),
    "get_property": ("GET", "/v1/properties/{radar_id}"),
    "get_owners": ("GET", "/v1/properties/{radar_id}/persons"),
    "get_transactions": ("GET", "/v1/properties/{radar_id}/transactions"),
    "get_comparable_sales": ("GET", "/v1/properties/{radar_id}/comps/sales"),
    "get_comparable_listings": ("GET", "/v1/properties/{radar_id}/comps/forsale"),
    "get_parcels": ("GET", "/v1/properties/{radar_id}/parcels"),
    "list_members": ("GET", "/v1/accounts/members"),
    "list_statuses": ("GET", "/v1/accounts/preferences/statuses"),
    "get_automation": ("GET", "/v1/lists/{list_id}/automations"),
    "list_webhooks": ("GET", "/v1/integrations/webhooks"),
    "delete_webhook": ("DELETE", "/v1/integrations/webhooks/{webhook_id}"),
}
NAMES = {"limit": "Limit", "start": "Start", "purchase": "Purchase", "page_token": "PageToken",
    "list_type": "ListType", "group_name": "GroupName", "is_monitored": "isMonitored",
    "list_name": "ListName", "display_order": "DisplayOrder", "criteria": "Criteria",
    "status_level": "StatusLevel", "added_since": "AddedSince"}
MUTATION_OUTPUT = {"update_list": "updateCount", "delete_list": "deleteCount",
    "remove_item": "deleteCount", "delete_webhook": "deleteCount", "add_items": "updateCount"}


def _redact(value, token):
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items() if k.lower() not in {"secret", "authorization", "api_token", "access_token"}}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    return value


class PropertyRadarNode(WorkflowNode):
    integration_type = "automation-propertyradar"
    credential_provider_labels = {"propertyradar": "PropertyRadar Account"}
    connection_evidence = ConnectionEvidence(operation="list_lists", noun="PropertyRadar lists", label_keys=("ListName", "ListID"))

    @classmethod
    def get_config_model(cls):
        return PropertyRadarConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a PropertyRadar API token")
        op = self.config.config
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, mode="json")
        for key in ("list_id", "radar_id", "webhook_id"):
            if key in values:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        values.pop("operation")
        body, params = {}, {}
        body_fields = {
            "create_list": {"list_name", "list_type", "criteria", "group_name", "is_monitored"},
            "update_list": {"list_name", "is_monitored", "display_order"},
            "add_items": {"criteria"}, "search_properties": {"criteria"},
        }.get(op.operation, set())
        for key, value in values.items():
            (body if key in body_fields else params)[NAMES[key]] = value
        if op.operation == "list_webhooks":
            params["Fields"] = "WebhookID,HookUrl,WebhookName,ClientName"
        if op.operation == "list_statuses":
            params["Layout"] = "menu"
        token = self.config.credentials.api_token
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                params=params, **({"json": body} if body_fields else {}))
        if response.status_code != 200:
            # Preserve provider rejection text for the manual-connect evidence seam.
            message = response.text[:2000].replace(token, "[redacted]")
            return {"status": "error", "http_status": response.status_code, "error": f"PropertyRadar HTTP {response.status_code}: {message}"}
        data = response.json()
        if not isinstance(data, dict) or any(data.get(k) for k in ("error", "errors")):
            raise ValueError("PropertyRadar returned an error or an unexpected response")
        expected = MUTATION_OUTPUT.get(op.operation, "results")
        preview = getattr(op, "purchase", None) == 0
        if expected == "results":
            if "results" in data:
                if not isinstance(data["results"], list):
                    raise ValueError("PropertyRadar returned invalid results")
            elif not (preview and type(data.get("resultCount")) is int and data["resultCount"] >= 0):
                raise ValueError("PropertyRadar response is missing results or a preview count")
        elif expected not in data:
            raise ValueError("PropertyRadar response is missing " + expected)
        if expected != "results" and (type(data[expected]) is not int or data[expected] < 0):
            raise ValueError("PropertyRadar returned an invalid mutation count")
        return {"status": "success", "operation": op.operation, **_redact(data, token)}
