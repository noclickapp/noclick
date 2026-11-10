"""Rkvst (now DataTrails) asset provenance and evidence operations.

Each operation sends one request to the published Archivist API. A pasted
bearer token is supported without creating a provider sign-in or OAuth app.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, Json, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, Retirement, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://app.datatrails.ai"
FAMILY = "rkvst_bearer_token"
ID = r"^[a-zA-Z0-9][a-zA-Z0-9-]{0,127}$"


class RkvstBearerTokenCredential(BaseModel):
    model_config = ConfigDict(title="Rkvst Bearer Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.datatrails.ai/developers/api-reference/app-registrations-api/",
            "x-credential-instructions": "Paste an existing DataTrails (formerly Rkvst) bearer access token, without the Authorization header. Application tokens expire after one hour; replace the token when it expires. NoClick sends it only to app.datatrails.ai. Your application needs an access policy permitting the selected reads and writes. Listing assets shows resources visible to this token; it does not verify your personal identity or write permissions.",
        })
    credential_type: Literal["rkvst_bearer_token"] = Field("rkvst_bearer_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=16384, title="Bearer access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Bearer access token")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste only the bearer token, without a header")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Page(Input):
    page_size: int = Field(50, ge=1, le=100, description="Maximum requested results in this page.")
    page_token: str | None = Field(None, max_length=8192, description="Opaque next_page_token from the preceding result for the same query.")
    order_by: str | None = Field(None, max_length=1024, description="Provider ordering expression.")


class AssetId(Input):
    asset_id: str = Field(..., pattern=ID, description="Bare asset UUID, without assets/.")


class LocationId(Input):
    location_id: str = Field(..., pattern=ID, description="Bare location UUID, without locations/.")


class EventId(AssetId):
    event_id: str = Field(..., pattern=ID, description="Bare event UUID, without the resource path.")


class PolicyId(Input):
    policy_id: str = Field(..., pattern=ID, description="Bare access-policy UUID.")


class ListAssets(Page):
    """List the assets visible to the connected application, one page at a time."""
    operation: Literal["list_assets"] = Field("list_assets", json_schema_extra={"ui:hidden": True})
    tracked: Literal["TRACKED", "NOT_TRACKED"] | None = None
    confirmation_status: Literal["PENDING", "CONFIRMED", "FAILED"] | None = None


class GetAsset(AssetId):
    """Read an asset and its current attributes."""
    operation: Literal["get_asset"] = Field("get_asset", json_schema_extra={"ui:hidden": True})
    at_time: str | None = Field(None, max_length=128, description="Optional historical RFC3339 timestamp.")


class CreateAsset(Input):
    """Create an asset with provenance behaviours and application attributes."""
    operation: Literal["create_asset"] = Field("create_asset", json_schema_extra={"ui:hidden": True})
    behaviours: list[str] = Field(default_factory=lambda: ["RecordEvidence"], max_length=100, json_schema_extra={"ui:widget": "list"})
    attributes: Json[dict[str, str]] = Field(..., json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}, description="Attribute names and string values, for example arc_display_name and arc_display_type.")
    proof_mechanism: Literal["MERKLE_LOG", "SIMPLE_HASH"] = "MERKLE_LOG"
    public: StrictBool = Field(False, description="Public assets and all their events are visible to everyone.")


class ListEvents(Page):
    """List events on one asset, or use '-' to list events across visible assets."""
    operation: Literal["list_events"] = Field("list_events", json_schema_extra={"ui:hidden": True})
    asset_id: str = Field("-", pattern=r"^(?:-|[a-zA-Z0-9][a-zA-Z0-9-]{0,127})$")
    behaviour: str | None = Field(None, max_length=1024)
    event_operation: str | None = Field(None, max_length=1024, description="Filter on the provider's event operation, for example Record.")
    timestamp_accepted_since: str | None = Field(None, max_length=128)
    timestamp_accepted_before: str | None = Field(None, max_length=128)


class GetEvent(EventId):
    """Read one event under its asset."""
    operation: Literal["get_event"] = Field("get_event", json_schema_extra={"ui:hidden": True})


class CreateEvent(AssetId):
    """Record evidence and optionally update asset attributes in the same event."""
    operation: Literal["create_event"] = Field("create_event", json_schema_extra={"ui:hidden": True})
    behaviour: str = Field("RecordEvidence", max_length=1024)
    event_operation: str = Field("Record", max_length=1024, description="Provider event operation.")
    event_attributes: Json[dict[str, str]] = Field(..., json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}, description="Event attribute names and string values.")
    asset_attributes: Json[dict[str, str]] | None = Field(None, json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


class GetAssetPublicUrl(AssetId):
    """Get the provider's public-view URL without fetching that URL."""
    operation: Literal["get_asset_public_url"] = Field("get_asset_public_url", json_schema_extra={"ui:hidden": True})


class GetEventPublicUrl(EventId):
    """Get the provider's public-view event URL without following it."""
    operation: Literal["get_event_public_url"] = Field("get_event_public_url", json_schema_extra={"ui:hidden": True})


class ListLocations(Page):
    """List locations, optionally filtering their display name and description."""
    operation: Literal["list_locations"] = Field("list_locations", json_schema_extra={"ui:hidden": True})
    display_name: str | None = Field(None, max_length=128)
    description: str | None = Field(None, max_length=8096)


class GetLocation(LocationId):
    """Read a location by its UUID."""
    operation: Literal["get_location"] = Field("get_location", json_schema_extra={"ui:hidden": True})


class CreateLocation(Input):
    """Create a named geographic location for assets."""
    operation: Literal["create_location"] = Field("create_location", json_schema_extra={"ui:hidden": True})
    display_name: str = Field(..., min_length=1, max_length=128)
    description: str | None = Field(None, max_length=8096)
    latitude: float = Field(..., ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(..., ge=-180, le=180, allow_inf_nan=False)
    attributes: Json[dict[str, str]] | None = Field(None, json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})


class UpdateLocation(LocationId):
    """Patch supplied location fields using an explicit field mask."""
    operation: Literal["update_location"] = Field("update_location", json_schema_extra={"ui:hidden": True})
    display_name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = Field(None, max_length=8096)
    latitude: float | None = Field(None, ge=-90, le=90, allow_inf_nan=False)
    longitude: float | None = Field(None, ge=-180, le=180, allow_inf_nan=False)
    attributes: Json[dict[str, str]] | None = Field(None, json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

    @model_validator(mode="after")
    def changes(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "location_id"}):
            raise ValueError("Supply at least one location field to update")
        return self


class DeleteLocation(LocationId):
    """Delete a location; the response acknowledges the request only."""
    operation: Literal["delete_location"] = Field("delete_location", json_schema_extra={"ui:hidden": True})


class GetLocationPermissions(LocationId):
    """Read the subjects allowed to use this location."""
    operation: Literal["get_location_permissions"] = Field("get_location_permissions", json_schema_extra={"ui:hidden": True})


class ListAccessPolicies(Page):
    """List tenant access policies without changing access grants."""
    operation: Literal["list_access_policies"] = Field("list_access_policies", json_schema_extra={"ui:hidden": True})
    display_name: str | None = Field(None, max_length=128)
    description: str | None = Field(None, max_length=8096)


class GetAccessPolicy(PolicyId):
    """Read one access policy by UUID."""
    operation: Literal["get_access_policy"] = Field("get_access_policy", json_schema_extra={"ui:hidden": True})


class GetTenant(Input):
    """Read the current tenant's administrative details; requires tenant access."""
    operation: Literal["get_tenant"] = Field("get_tenant", json_schema_extra={"ui:hidden": True})


RkvstOperation = Annotated[Union[ListAssets, GetAsset, CreateAsset, ListEvents,
    GetEvent, CreateEvent, GetAssetPublicUrl, GetEventPublicUrl, ListLocations,
    GetLocation, CreateLocation, UpdateLocation, DeleteLocation,
    GetLocationPermissions, ListAccessPolicies, GetAccessPolicy, GetTenant], Field(discriminator="operation")]


class RkvstNodeConfig(NodeConfig[RkvstOperation, RkvstBearerTokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items() if k.lower() not in {"client_secret", "access_token", "refresh_token", "secret", "private_key"}}
    return value


class RkvstNode(WorkflowNode):
    integration_type = "automation-rkvst"
    retired = Retirement(
        reason="DataTrails (formerly RKVST) was acquired by OnID in August 2025; datatrails.ai now redirects to onid.co and its API host app.datatrails.ai no longer resolves.",
        since="2026-11-10",
    )
    connection_evidence = ConnectionEvidence(noun="assets", operation="list_assets",
        label_keys=("attributes.arc_display_name", "identity"))

    @classmethod
    def get_config_model(cls):
        return RkvstNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Rkvst bearer token")
        op = self.config.config
        action = op.operation
        values = op.model_dump(exclude={"operation"}, exclude_none=True)
        params, body, method = {}, None, "GET"
        asset = quote(values.pop("asset_id", ""), safe="")
        event = quote(values.pop("event_id", ""), safe="")
        location = quote(values.pop("location_id", ""), safe="")
        policy = quote(values.pop("policy_id", ""), safe="")
        if action in {"list_assets", "create_asset"}:
            path = "/archivist/v2/assets"
        elif action in {"get_asset", "get_asset_public_url", "list_events", "create_event", "get_event", "get_event_public_url"}:
            path = "/archivist/v2/assets/" + asset
            if action in {"list_events", "create_event", "get_event", "get_event_public_url"}:
                path += "/events" + ("/" + event if event else "")
            if action.endswith("public_url"):
                path += ":publicurl"
        elif "location" in action:
            path = "/archivist/v2/locations" + ("/" + location if location else "")
            if action == "get_location_permissions":
                path += "/permissions"
        elif action in {"list_access_policies", "get_access_policy"}:
            path = "/archivist/iam/v1/access_policies" + ("/" + policy if policy else "")
        else:
            path = "/archivist/v1/tenancies/self"
        if action == "delete_location":
            method = "DELETE"
        elif action == "update_location":
            method, body = "PATCH", values
            params["mask"] = ",".join(values)
        elif action.startswith("create_"):
            method, body = "POST", values
        else:
            params = values
        if body is not None and "event_operation" in body:
            body["operation"] = body.pop("event_operation")
        if "event_operation" in params:
            params["operation"] = params.pop("event_operation")
        token = self.config.credentials.access_token
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params, json=body, headers=headers)
        except httpx.HTTPError:
            raise ValueError("Rkvst request did not complete; check the provider before retrying a write") from None
        if not 200 <= response.status_code < 300:
            # Preserve provider rejection text so the connect seam can judge it.
            message = _redact(response.text[:4000], token)
            output = {"status": "error", "status_code": response.status_code, "error": message,
                "message": message, "write_outcome": "unverified" if method != "GET" else None}
        else:
            if len(response.content) > 10_000_000:
                raise ValueError("Rkvst response exceeds the JSON size limit")
            try:
                data = response.json() if response.content else {}
            except ValueError:
                raise ValueError("Rkvst returned an unexpected JSON response; check writes before retrying") from None
            if not isinstance(data, dict) or "error" in data or "errors" in data:
                raise ValueError("Rkvst returned an unexpected response envelope")
            collection = {"list_assets": "assets", "list_events": "events", "list_locations": "locations", "list_access_policies": "access_policies"}.get(action)
            if collection:
                if not isinstance(data.get(collection, []), list):
                    raise ValueError("Rkvst returned an invalid result page")
                if not isinstance(data.get("next_page_token", ""), str):
                    raise ValueError("Rkvst returned an invalid page token")
            output = {"status": "success", "status_code": response.status_code, "data": data}
            if collection:
                output["items"] = data.get(collection, [])
                output["next_page_token"] = data.get("next_page_token") or None
                output["has_more"] = bool(output["next_page_token"])
                output["complete"] = not output["has_more"] and response.status_code != 206
            if method != "GET":
                output["write_acknowledged"] = True
                output["readback_verified"] = False
            output = _redact(output, token)
        await self.emit(output)
        return output
