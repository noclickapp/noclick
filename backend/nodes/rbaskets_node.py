"""Request Baskets API v1.0.0: the eleven nondeprecated Swagger operations.

Contract: https://github.com/darklynx/request-baskets/blob/master/doc/api-swagger.yaml
Authorization is the raw basket token (or service master token), without Bearer.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://rbaskets.in"
METHODS = Literal["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "CONNECT", "OPTIONS", "TRACE"]


def basket_name(value):
    if isinstance(value, str):
        value = value.strip()
    if not isinstance(value, str) or not value.strip() or value in {".", ".."} or any(c in value for c in "/\\?#") or any(ord(c) < 32 for c in value):
        raise ValueError("Paste one basket name, without its URL or path")
    return value.strip()


class RBasketsTokenCredential(BaseModel):
    model_config = ConfigDict(title="Request Baskets Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://rbaskets.in",
            "x-credential-instructions": "Paste the token shown when you created your basket and its basket name. NoClick reads that basket's protected settings to check the token. Service statistics and listing baskets require a service master token; basket tokens authorize only their own basket. This integration connects to rbaskets.in.",
        })
    credential_type: Literal["rbaskets_token"] = Field("rbaskets_token", json_schema_extra={"ui:hidden": True})
    token: str = Field(..., title="Token", min_length=1, json_schema_extra={"ui:widget": "password"})
    basket_name: str = Field(..., title="Basket name", min_length=1)

    @field_validator("token", mode="before")
    @classmethod
    def check_token(cls, value):
        value = clean_secret(value, field_name="Token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the raw token without an Authorization prefix")
        return value

    @field_validator("basket_name", mode="before")
    @classmethod
    def check_name(cls, value):
        return basket_name(value)


class BasketInput(BaseModel):
    name: Optional[str] = Field(None, title="Basket name", description="Leave empty to use the basket in your connection.")

    @field_validator("name", mode="before")
    @classmethod
    def check_name(cls, value):
        return basket_name(value) if value is not None else None


class BasketSettings(BasketInput):
    forward_url: Optional[str] = Field(None, description="Forward incoming requests to this URL; an empty string disables forwarding.")
    disable_forwarding: bool = Field(False, description="Clear the forwarding URL. Overrides Forward URL when enabled.")
    proxy_response: Optional[bool] = Field(None, description="Return the forwarding destination's response to the original caller.")
    insecure_tls: Optional[bool] = Field(None, description="Disable certificate verification for forwarding. Enabling this has security implications.")
    expand_path: Optional[bool] = Field(None, description="Append the incoming request path to the forwarding URL.")
    capacity: Optional[int] = Field(None, ge=1, description="Maximum requests to retain; the service enforces its configured maximum.")


class GetVersion(BaseModel):
    """Read the service version and source commit."""
    operation: Literal["get_version"] = Field("get_version", json_schema_extra={"ui:hidden": True})


class GetStatistics(BaseModel):
    """Read basket and request statistics (requires a master token)."""
    operation: Literal["get_statistics"] = Field("get_statistics", json_schema_extra={"ui:hidden": True})
    max: int = Field(5, ge=1, le=1000, title="Maximum top baskets")


class ListBaskets(BaseModel):
    """List one page of basket names (requires a master token)."""
    operation: Literal["list_baskets"] = Field("list_baskets", json_schema_extra={"ui:hidden": True})
    max: int = Field(20, ge=1, le=1000, title="Page size")
    skip: int = Field(0, ge=0, title="Skip")
    q: Optional[str] = Field(None, title="Search")


class CreateBasket(BasketSettings):
    """Create a basket and return its generated management token. Save that token."""
    operation: Literal["create_basket"] = Field("create_basket", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., title="New basket name", min_length=1)


class GetBasket(BasketInput):
    """Read protected basket configuration; also verifies the connection."""
    operation: Literal["get_basket"] = Field("get_basket", json_schema_extra={"ui:hidden": True})


class UpdateBasket(BasketSettings):
    """Update basket capacity and request forwarding settings."""
    operation: Literal["update_basket"] = Field("update_basket", json_schema_extra={"ui:hidden": True})


class DeleteBasket(BasketInput):
    """Permanently delete a basket and all its collected requests."""
    operation: Literal["delete_basket"] = Field("delete_basket", json_schema_extra={"ui:hidden": True})


class GetResponse(BasketInput):
    """Read the response configured for an incoming HTTP method."""
    operation: Literal["get_response"] = Field("get_response", json_schema_extra={"ui:hidden": True})
    method: METHODS = Field("GET", title="Incoming request method")


class UpdateResponse(BasketInput):
    """Configure the response returned to requests with the selected HTTP method."""
    operation: Literal["update_response"] = Field("update_response", json_schema_extra={"ui:hidden": True})
    method: METHODS = Field("GET", title="Incoming request method")
    response_status: int = Field(200, ge=100, le=599, title="Response status")
    response_body: str = Field("", title="Response body")
    headers_json: str = Field("{}", title="Response headers", description='JSON object mapping header names to arrays of strings, e.g. {"Content-Type":["application/json"]}.', json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    is_template: bool = Field(False, description="Interpret the response body as a Go HTML template.")

    @field_validator("headers_json")
    @classmethod
    def check_headers(cls, value):
        try:
            headers = json.loads(value)
        except (TypeError, ValueError):
            raise ValueError("Headers must be a JSON object of string arrays") from None
        if not isinstance(headers, dict) or any(not isinstance(v, list) or any(not isinstance(item, str) for item in v) for v in headers.values()):
            raise ValueError("Headers must be a JSON object of string arrays")
        return value


class ListRequests(BasketInput):
    """Read one page of collected requests, optionally searching body, query or headers."""
    operation: Literal["list_requests"] = Field("list_requests", json_schema_extra={"ui:hidden": True})
    max: int = Field(20, ge=1, le=1000, title="Page size")
    skip: int = Field(0, ge=0, title="Skip")
    q: Optional[str] = Field(None, title="Search")
    search_in: Literal["any", "body", "query", "headers"] = Field("any", title="Search in")


class DeleteRequests(BasketInput):
    """Delete all requests collected by a basket, keeping the basket itself."""
    operation: Literal["delete_requests"] = Field("delete_requests", json_schema_extra={"ui:hidden": True})


RBasketsOperation = Annotated[Union[GetVersion, GetStatistics, ListBaskets, CreateBasket, GetBasket,
    UpdateBasket, DeleteBasket, GetResponse, UpdateResponse, ListRequests, DeleteRequests], Field(discriminator="operation")]


class RBasketsConfig(NodeConfig[RBasketsOperation, RBasketsTokenCredential]):
    pass


class RBasketsNode(WorkflowNode):
    integration_type = "automation-rbaskets"
    connection_evidence = ConnectionEvidence(operation="get_basket", noun="basket settings", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return RBasketsConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Request Baskets token first")
        op = self.config.config
        action = op.operation
        method, params, body = "GET", {}, None
        if action == "get_version":
            path = "/api/version"
        elif action == "get_statistics":
            path, params = "/api/stats", {"max": op.max}
        elif action == "list_baskets":
            path = "/api/baskets"
            params = op.model_dump(exclude={"operation"}, exclude_none=True)
        else:
            name = op.name or credential.basket_name
            path = "/api/baskets/" + quote(basket_name(name), safe="")
            if action in {"get_response", "update_response"}:
                path += "/responses/" + op.method
            elif action in {"list_requests", "delete_requests"}:
                path += "/requests"
            if action == "create_basket":
                method = "POST"
            elif action in {"update_basket", "update_response"}:
                method = "PUT"
            elif action in {"delete_basket", "delete_requests"}:
                method = "DELETE"
            if action in {"create_basket", "update_basket"}:
                body = op.model_dump(include={"forward_url", "proxy_response", "insecure_tls", "expand_path", "capacity"}, exclude_none=True)
                if op.disable_forwarding:
                    body["forward_url"] = ""
            elif action == "update_response":
                body = {"status": op.response_status, "headers": json.loads(op.headers_json), "body": op.response_body, "is_template": op.is_template}
            elif action == "list_requests":
                params = {"max": op.max, "skip": op.skip, "in": op.search_in}
                if op.q is not None:
                    params["q"] = op.q
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": credential.token, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        expected = {201} if action == "create_basket" else {204} if method in {"PUT", "DELETE"} else {200, 204} if action in {"list_baskets", "list_requests"} else {200}
        if response.status_code not in expected:
            # Error bodies may echo the submitted token or captured private data.
            # Preserve the status and documented rejection meaning without echoing it.
            reason = {401: "Invalid or missing token", 403: "Basket name is reserved or access is forbidden", 404: "No basket with such name", 409: "Basket already exists", 422: "Configuration is not valid"}.get(response.status_code, "Request Baskets rejected the request")
            return {"status": "error", "http_status": response.status_code, "error": reason}
        result = {"status": "success", "http_status": response.status_code}
        if response.status_code == 204:
            if action in {"list_baskets", "list_requests"}:
                result["data"] = {"names" if action == "list_baskets" else "requests": [], "has_more": False}
        else:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Expected a Request Baskets JSON object")
            if action == "create_basket" and (not isinstance(payload.get("token"), str) or not payload["token"]):
                raise ValueError("The service did not return the new basket token")
            if action in {"list_baskets", "list_requests"}:
                key = "names" if action == "list_baskets" else "requests"
                if not isinstance(payload.get(key), list) or type(payload.get("has_more")) is not bool:
                    raise ValueError("Expected a Request Baskets page with items and has_more")
                result["next_skip"] = op.skip + len(payload[key]) if payload["has_more"] else None
            result["data"] = payload
        return result
