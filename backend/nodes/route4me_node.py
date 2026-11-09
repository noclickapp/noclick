"""Route4Me v5 address-book, fleet and territory automation.

Each operation sends one request to the provider's published v5 contract;
API keys are supplied by the person connecting the account.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://wh.route4me.com/modules/api/v5.0"


class Route4MeAPIKey(BaseModel):
    model_config = ConfigDict(title="Route4Me API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://route4me.io/docs/#authentication",
            "x-credential-instructions": "Copy your Route4Me API key from My Account > API. Paste only the key. NoClick sends it as the api_key query parameter to wh.route4me.com. Connecting reads one page of your address book; individual operations need the corresponding account features and permissions.",
        })
    credential_type: Literal["route4me_api_key"] = Field("route4me_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header or spaces")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListAddresses(Input):
    """Read one address-book page. Use next_page to continue with the same filters."""
    operation: Literal["list_addresses"] = "list_addresses"
    page: int = Field(1, ge=1, le=1000000)
    per_page: int = Field(30, ge=1, le=100)
    query: str | None = Field(None, max_length=1000)
    display: Literal["all", "routed", "unrouted"] = "all"


class GetAddress(Input):
    operation: Literal["get_address"] = "get_address"
    address_id: int = Field(..., gt=0)


class AddressFields(Input):
    address_1: str = Field(..., min_length=1, max_length=2000)
    cached_lat: float = Field(..., ge=-90, le=90, allow_inf_nan=False)
    cached_lng: float = Field(..., ge=-180, le=180, allow_inf_nan=False)
    address_alias: str | None = Field(None, max_length=1000)
    address_2: str | None = Field(None, max_length=2000)
    address_city: str | None = Field(None, max_length=500)
    address_state_id: str | None = Field(None, max_length=100)
    address_country_id: str | None = Field(None, max_length=100)
    address_zip: str | None = Field(None, max_length=100)
    first_name: str | None = Field(None, max_length=500)
    last_name: str | None = Field(None, max_length=500)
    address_email: str | None = Field(None, max_length=500)
    address_phone_number: str | None = Field(None, max_length=100)
    service_time: float | None = Field(None, ge=0, allow_inf_nan=False)


class CreateAddress(AddressFields):
    operation: Literal["create_address"] = "create_address"


class UpdateAddress(AddressFields):
    """Update an address, supplying the address and coordinates required by v5."""
    operation: Literal["update_address"] = "update_address"
    address_id: int = Field(..., gt=0)


class DeleteAddresses(Input):
    """Delete exactly the supplied address IDs; a 202 response only acknowledges a queued job."""
    operation: Literal["delete_addresses"] = "delete_addresses"
    address_ids: list[Annotated[int, Field(gt=0)]] = Field(..., min_length=1, max_length=100)


class GetAddressCustomFields(Input):
    operation: Literal["get_address_custom_fields"] = "get_address_custom_fields"


class GetAddressClusters(Input):
    operation: Literal["get_address_clusters"] = "get_address_clusters"
    display: Literal["all", "routed", "unrouted"] = "all"
    query: str | None = Field(None, max_length=1000)


class ListVehicles(Input):
    """Read one explicit fleet page; no automatic traversal is performed."""
    operation: Literal["list_vehicles"] = "list_vehicles"
    page: int = Field(1, ge=1, le=1000000)
    per_page: int = Field(30, ge=1, le=100)
    search_query: str | None = Field(None, max_length=1000)


class VehicleID(Input):
    vehicle_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class GetVehicle(VehicleID):
    operation: Literal["get_vehicle"] = "get_vehicle"


class VehicleFields(Input):
    vehicle_alias: str = Field(..., min_length=1, max_length=500)
    vehicle_vin: str | None = Field(None, max_length=100)
    vehicle_license_plate: str | None = Field(None, max_length=100)
    vehicle_make: str | None = Field(None, max_length=100)
    vehicle_model: str | None = Field(None, max_length=100)
    vehicle_model_year: int | None = Field(None, ge=1900, le=2200)
    is_operational: bool | None = None
    fuel_type: Literal["unleaded 87", "unleaded 89", "unleaded 91", "unleaded 93", "diesel", "electric", "hybrid"] | None = None


class CreateVehicle(VehicleFields):
    operation: Literal["create_vehicle"] = "create_vehicle"


class UpdateVehicle(VehicleFields, VehicleID):
    operation: Literal["update_vehicle"] = "update_vehicle"


class DeleteVehicle(VehicleID):
    operation: Literal["delete_vehicle"] = "delete_vehicle"


class ListTerritories(Input):
    operation: Literal["list_territories"] = "list_territories"
    addresses_count: bool = False
    orders_count: bool = False


class TerritoryID(Input):
    territory_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class GetTerritory(TerritoryID):
    operation: Literal["get_territory"] = "get_territory"


class TerritoryFields(Input):
    """Polygon vertices as latitude,longitude strings, in the provider's order."""
    territory_name: str = Field(..., min_length=1, max_length=500)
    territory_color: str = Field("000000", pattern=r"^[0-9A-Fa-f]{6}$")
    vertices: list[Annotated[str, Field(pattern=r"^-?\d{1,2}(?:\.\d{1,6})?,-?\d{1,3}(?:\.\d{1,6})?$")]] = Field(..., min_length=3, max_length=1000,
        description="Polygon vertices, each a latitude,longitude string.")

    @field_validator("vertices")
    @classmethod
    def coordinates(cls, values):
        for value in values:
            if not re.fullmatch(r"-?\d+(?:\.\d+)?,-?\d+(?:\.\d+)?", value):
                raise ValueError("Use latitude,longitude for every vertex")
            lat, lng = map(float, value.split(","))
            if not -90 <= lat <= 90 or not -180 <= lng <= 180:
                raise ValueError("Vertex coordinates are out of range")
        return values


class CreateTerritory(TerritoryFields):
    operation: Literal["create_territory"] = "create_territory"


class UpdateTerritory(TerritoryFields, TerritoryID):
    operation: Literal["update_territory"] = "update_territory"


class DeleteTerritory(TerritoryID):
    operation: Literal["delete_territory"] = "delete_territory"


Operations = Annotated[Union[ListAddresses, GetAddress, CreateAddress, UpdateAddress,
    DeleteAddresses, GetAddressCustomFields, GetAddressClusters, ListVehicles,
    GetVehicle, CreateVehicle, UpdateVehicle, DeleteVehicle, ListTerritories,
    GetTerritory, CreateTerritory, UpdateTerritory, DeleteTerritory], Field(discriminator="operation")]


class Route4MeConfig(NodeConfig[Operations, Route4MeAPIKey]):
    pass


def request_for(op):
    """Return the single fixed contract operation and its typed parameters."""
    values = op.model_dump(exclude={"operation"}, exclude_none=True)
    action = op.operation
    if action == "list_addresses":
        return "GET", "/addresses/index/pagination", values, None
    if action == "get_address":
        return "GET", "/addresses/show", values, None
    if action == "get_address_custom_fields":
        return "GET", "/addresses/custom-fields", {}, None
    if action == "get_address_clusters":
        return "GET", "/addresses/index/clustering", values, None
    if action == "create_address":
        return "POST", "/addresses", {}, values
    if action == "update_address":
        return "PUT", "/addresses/" + str(values.pop("address_id")), {}, values
    if action == "delete_addresses":
        return "DELETE", "/addresses/delete", {}, values
    if action == "list_vehicles":
        return "GET", "/vehicles/paginate", values, None
    if action in {"get_vehicle", "update_vehicle", "delete_vehicle"}:
        path = "/vehicles/" + quote(values.pop("vehicle_id"), safe="")
        return {"get_vehicle": "GET", "update_vehicle": "PATCH", "delete_vehicle": "DELETE"}[action], path, {}, values if action == "update_vehicle" else None
    if action == "create_vehicle":
        return "POST", "/vehicles", {}, values
    if action == "list_territories":
        return "GET", "/territories", values, None
    if action in {"get_territory", "delete_territory"}:
        path = "/territories/" + quote(values["territory_id"], safe="")
        return "GET" if action == "get_territory" else "DELETE", path, {}, None
    if action in {"create_territory", "update_territory"}:
        identifier = values.pop("territory_id", None)
        values["territory"] = {"type": "poly", "data": values.pop("vertices")}
        return ("POST" if identifier is None else "PUT"), "/territories" + ("/" + quote(identifier, safe="") if identifier is not None else ""), {}, values
    raise ValueError("Unknown Route4Me operation")


def redact(value, key):
    if isinstance(value, dict):
        return {k: redact(v, key) for k, v in value.items() if k.lower() not in {"api_key", "access_token", "authorization"}}
    if isinstance(value, list):
        return [redact(v, key) for v in value]
    return value.replace(key, "[redacted]") if isinstance(value, str) else value


class Route4MeNode(WorkflowNode):
    integration_type = "automation-route4me"
    connection_evidence = ConnectionEvidence(noun="address-book contacts", operation="list_addresses",
        label_keys=("address_alias", "address_1", "address_id"))

    @classmethod
    def get_config_model(cls):
        return Route4MeConfig

    async def execute(self, inputs):
        if self.config.credentials is None:
            raise ValueError("Connect a Route4Me API key")
        op = self.config.config
        key = self.config.credentials.api_key
        method, path, params, body = request_for(op)
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}
        params["api_key"] = key
        writing = method != "GET"
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"Accept": "application/json"}, **({"json": body} if body is not None else {}))
        except Exception:
            # Query-authenticated URLs and transport exception text can contain the key.
            raise ValueError("Route4Me request could not be completed" + ("; inspect the account before retrying this write" if writing else "")) from None
        if not 200 <= response.status_code < 300:
            message = "Route4Me rejected the request"
            try:
                error = response.json()
                if isinstance(error, dict):
                    detail = error.get("message") or error.get("error") or error.get("errors")
                    if detail:
                        message = str(detail)[:2000]
            except (ValueError, TypeError):
                pass
            output = {"status": "error", "success": False, "http_status": response.status_code,
                "message": message}
        else:
            if len(response.content) > 5_000_000:
                raise ValueError("Route4Me returned more than 5 MB; narrow the request")
            if response.content:
                try:
                    data = response.json()
                except (ValueError, TypeError):
                    raise ValueError("Route4Me returned invalid JSON; inspect the account before retrying a write") from None
                if not isinstance(data, (dict, list)):
                    raise ValueError("Route4Me returned an unexpected response shape")
            else:
                data = None
            failure = isinstance(data, dict) and (data.get("status") is False or data.get("success") is False or bool(data.get("error")) or bool(data.get("errors")))
            output = {"status": "error" if failure else "success", "success": not failure,
                "http_status": response.status_code, "data": data,
                "queued": response.status_code == 202}
            if isinstance(data, dict) and isinstance(data.get("results"), list):
                output["items"] = data["results"]
            if isinstance(op, ListAddresses) and isinstance(data, dict):
                current, last = data.get("current_page"), data.get("last_page")
                output["next_page"] = current + 1 if type(current) is int and type(last) is int and current < last else None
            if isinstance(op, ListVehicles):
                output["page"] = op.page
                output["per_page"] = op.per_page
                output["pagination_note"] = "Use the provider pagination metadata to continue; this operation reads one page."
            if writing:
                output["write_acknowledged"] = not failure
                output["readback_verified"] = False
        output = redact(output, key)
        await self.emit(output)
        return output
