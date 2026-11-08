"""HITL.sh review loops and requests, from the published v1 contract.

The prose API examples use /v1/api for resources and /v1/test for identity.
Each operation issues one fixed request; writes are never retried automatically.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.hitl.sh/v1"


class HitlAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Hitl API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://my.hitl.sh",
        "x-credential-instructions": "In your Hitl dashboard, open Settings → API Keys, create a key, and paste it here without the Bearer prefix. NoClick sends it only to api.hitl.sh."
    })
    credential_type: Literal["hitl_api_key"] = Field("hitl_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without the Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


ID = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{24}$", description="24-character Hitl resource ID")]


class ListLoops(_Input):
    """List loops belonging to the authenticated user."""
    operation: Literal["list_loops"] = Field("list_loops", json_schema_extra={"ui:hidden": True})


class GetLoop(_Input):
    """Get one loop and its current details."""
    operation: Literal["get_loop"] = Field("get_loop", json_schema_extra={"ui:hidden": True})
    loop_id: ID


class CreateLoop(_Input):
    """Create a loop with an invite code and join URL."""
    operation: Literal["create_loop"] = Field("create_loop", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=100)
    icon: str = Field(..., min_length=1, description="Hitl icon identifier, e.g. shield-check")
    description: str | None = Field(None, max_length=500)


class UpdateLoop(_Input):
    """Update a loop you created."""
    operation: Literal["update_loop"] = Field("update_loop", json_schema_extra={"ui:hidden": True})
    loop_id: ID
    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    icon: str | None = Field(None, min_length=1)

    @model_validator(mode="after")
    def changed(self):
        if all(getattr(self, f) is None for f in ("name", "description", "icon")):
            raise ValueError("Provide a name, description or icon to update")
        return self


class DeleteLoop(_Input):
    """Permanently delete a loop and its associated data."""
    operation: Literal["delete_loop"] = Field("delete_loop", json_schema_extra={"ui:hidden": True})
    loop_id: ID


class ListLoopMembers(_Input):
    """List members and their membership status."""
    operation: Literal["list_loop_members"] = Field("list_loop_members", json_schema_extra={"ui:hidden": True})
    loop_id: ID


class RemoveLoopMember(_Input):
    """Remove a member from a loop you created."""
    operation: Literal["remove_loop_member"] = Field("remove_loop_member", json_schema_extra={"ui:hidden": True})
    loop_id: ID
    user_id: ID


class TestAPIKey(_Input):
    """Read the key's account identity, permissions and rate limits."""
    operation: Literal["test_api_key"] = Field("test_api_key", json_schema_extra={"ui:hidden": True})


class ListRequests(_Input):
    """List requests created by your API key."""
    operation: Literal["list_requests"] = Field("list_requests", json_schema_extra={"ui:hidden": True})


class GetRequest(_Input):
    """Read a request's status and reviewer response without waiting or polling."""
    operation: Literal["get_request"] = Field("get_request", json_schema_extra={"ui:hidden": True})
    request_id: ID


class CancelRequest(_Input):
    """Cancel a request that has not completed."""
    operation: Literal["cancel_request"] = Field("cancel_request", json_schema_extra={"ui:hidden": True})
    request_id: ID


class AddFeedback(_Input):
    """Add feedback to a completed request."""
    operation: Literal["add_feedback"] = Field("add_feedback", json_schema_extra={"ui:hidden": True})
    request_id: ID
    feedback: dict[str, Any] = Field(..., description="Feedback JSON, e.g. rating and comment")


class ListLoopRequests(_Input):
    """List requests within one loop."""
    operation: Literal["list_loop_requests"] = Field("list_loop_requests", json_schema_extra={"ui:hidden": True})
    loop_id: ID


class CreateRequest(_Input):
    """Create a review request and notify active loop members."""
    operation: Literal["create_request"] = Field("create_request", json_schema_extra={"ui:hidden": True})
    loop_id: ID
    processing_type: Literal["time-sensitive", "deferred"] = "time-sensitive"
    type: Literal["markdown", "image"] = "markdown"
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    request_text: str = Field(..., min_length=1, max_length=2000)
    response_type: Literal["text", "single_select", "multi_select", "rating", "number", "boolean"]
    response_config: dict[str, Any] = Field(..., description="Response-type configuration JSON from Hitl's response types guide")
    default_response: Any = Field(..., description="JSON fallback value on timeout, such as a string, number, boolean, list or object")
    timeout_seconds: int | None = Field(None, ge=60, le=86400)
    image_url: str | None = Field(None, json_schema_extra={"format": "uri"})
    context: dict[str, Any] | None = None
    platform: Literal["n8n", "zapier", "web_portal", "api", "mobile", "webhook"] = "api"
    platform_version: str | None = None
    callback_url: str | None = Field(None, json_schema_extra={"format": "uri"})

    @field_validator("default_response")
    @classmethod
    def fallback_value(cls, value):
        if value is None:
            raise ValueError("Provide a JSON fallback value for the response type")
        return value

    @model_validator(mode="after")
    def dependent_fields(self):
        if self.processing_type == "time-sensitive" and self.timeout_seconds is None:
            raise ValueError("Time-sensitive requests require timeout_seconds")
        if self.type == "image" and not self.image_url:
            raise ValueError("Image requests require image_url")
        return self


HitlConfig = Annotated[Union[ListLoops, GetLoop, CreateLoop, UpdateLoop, DeleteLoop,
    ListLoopMembers, RemoveLoopMember, TestAPIKey, ListRequests, GetRequest,
    CancelRequest, AddFeedback, ListLoopRequests, CreateRequest], Field(discriminator="operation")]


class HitlFullConfig(NodeConfig[HitlConfig, HitlAPIKeyCredential]):
    pass


# One entry per published operation. The /api prefix is documented in endpoint
# pages; the published OpenAPI server URL omits it for resources.
ROUTES = {
    "list_loops": ("GET", "/api/loops"),
    "get_loop": ("GET", "/api/loops/{loop_id}"),
    "create_loop": ("POST", "/api/loops"),
    "update_loop": ("PUT", "/api/loops/{loop_id}"),
    "delete_loop": ("DELETE", "/api/loops/{loop_id}"),
    "list_loop_members": ("GET", "/api/loops/{loop_id}/members"),
    "remove_loop_member": ("DELETE", "/api/loops/{loop_id}/members/{user_id}"),
    "test_api_key": ("GET", "/test"),
    "list_requests": ("GET", "/api/requests"),
    "get_request": ("GET", "/api/requests/{request_id}"),
    "cancel_request": ("DELETE", "/api/requests/{request_id}"),
    "add_feedback": ("POST", "/api/requests/{request_id}/feedback"),
    "list_loop_requests": ("GET", "/api/loops/{loop_id}/requests"),
    "create_request": ("POST", "/api/loops/{loop_id}/requests"),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {str(k).replace(token, "[redacted]"): _redact(v, token) for k, v in value.items()}
    return value


class HitlNode(WorkflowNode):
    integration_type = "automation-hitl"
    connection_evidence = ConnectionEvidence(noun="loops", operation="list_loops", identity_operation="test_api_key")

    @classmethod
    def get_config_model(cls):
        return HitlFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Hitl API key")
        op = self.config.config
        token = self.config.credentials.api_key
        method, route = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        path = route.format(**values)
        body = {k: v for k, v in values.items() if k not in {"operation", "loop_id", "request_id", "user_id"}}
        kwargs = {"json": body} if method in {"POST", "PUT"} else {}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, **kwargs)
            expected = 201 if op.operation in {"create_loop", "create_request"} else 200
            if response.status_code != expected:
                message = "Hitl request failed"
                try:
                    error = response.json()
                    if isinstance(error, dict) and isinstance(error.get("msg"), str):
                        message = error["msg"][:1000]
                except ValueError:
                    pass
                output = {"status": "error", "error": message, "http_status": response.status_code}
            else:
                if len(response.content) > 5_000_000:
                    raise ValueError("Hitl JSON response is too large")
                result = response.json()
                if not isinstance(result, dict) or result.get("error") is not False or not isinstance(result.get("data"), dict):
                    raise ValueError("Hitl did not return a successful data envelope")
                data = result["data"].copy()
                # Return the documented QR URL instead of its inline base64 copy.
                data.pop("qr_code_base64", None)
                output = {"status": "success", "data": data, "http_status": response.status_code}
        except httpx.RequestError:
            raise ValueError("Hitl request could not complete; inspect write status before retrying") from None
        output = _redact(output, token)
        await self.emit(output)
        return output
