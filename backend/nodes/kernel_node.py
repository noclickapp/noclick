"""Kernel browser automation, pinned to the provider's OpenAPI 0.1.0 contract.

Each operation makes exactly one API call. Lists return one page and the
provider's continuation headers; invocation acceptance is not completion.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

API_URL = "https://api.onkernel.com"


class KernelApiKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Kernel API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dashboard.onkernel.com",
            "x-credential-instructions": "Create an API key in the Kernel dashboard and paste it here without the Bearer prefix. NoClick sends it only to api.onkernel.com. Access is limited by the key's organization or project scope.",
        },
    )
    credential_type: Literal["kernel_api_key"] = Field("kernel_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("browser_id", "profile_id", "proxy_id", "invocation_id", check_fields=False)
    @classmethod
    def resource_id(cls, value):
        if value is not None and (not value.strip() or value in {".", ".."} or len(value) > 255 or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError("Supply a nonempty Kernel resource ID or name without controls")
        return value


class _Page(_Input):
    limit: int = Field(20, ge=1, le=100, description="Maximum results in this page.")
    offset: int = Field(0, ge=0, description="Use next_offset from the preceding page with the same filters.")
    query: str | None = Field(None, description="Provider-side search; this operation returns one page.")


class GetAuthContext(_Input):
    operation: Literal["get_auth_context"] = Field("get_auth_context", title="Get Authentication Context")


class ListBrowsers(_Page):
    operation: Literal["list_browsers"] = Field("list_browsers", title="List Browser Sessions")
    status: Literal["active", "deleted", "all"] = "active"
    region: Literal["us-east", "us-west", "eu-west", "ap-southeast"] | None = None


class GetBrowser(_Input):
    operation: Literal["get_browser"] = Field("get_browser", title="Get Browser Session")
    browser_id: str = Field(..., title="Browser ID or Name", min_length=1)
    include_deleted: bool = False


class CreateBrowser(_Input):
    operation: Literal["create_browser"] = Field("create_browser", title="Create Browser Session")
    name: str | None = Field(None, min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9._-]{1,255}$")
    start_url: str | None = Field(None, description="URL to open. Navigation is best effort; session creation does not prove the page loaded.")
    timeout_seconds: int = Field(60, ge=10, le=259200, description="Inactivity timeout in seconds.")
    headless: bool = False
    stealth: bool = False
    region: Literal["us-east", "us-west", "eu-west", "ap-southeast"] | None = Field(None, description="Region selection requires a Start-Up or Enterprise plan.")
    profile_id: str | None = Field(None, description="Existing profile ID to load.")
    save_changes: bool = Field(False, description="Save session changes back to the selected profile when it ends.")
    proxy_id: str | None = Field(None, description="Existing proxy ID in the same project.")

    @model_validator(mode="after")
    def profile_required(self):
        if self.save_changes and not self.profile_id:
            raise ValueError("Select a profile before enabling Save Changes")
        return self


class UpdateBrowser(_Input):
    operation: Literal["update_browser"] = Field("update_browser", title="Update Browser Session")
    browser_id: str = Field(..., title="Browser ID or Name", min_length=1)
    name: str | None = Field(None, min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9._-]{1,255}$")
    start_url: str | None = Field(None, max_length=2048, description="Navigate after updating. Navigation is best effort.")

    @model_validator(mode="after")
    def change_required(self):
        if self.name is None and self.start_url is None:
            raise ValueError("Supply a new name or start URL")
        return self


class DeleteBrowser(_Input):
    operation: Literal["delete_browser"] = Field("delete_browser", title="Delete Browser Session")
    browser_id: str = Field(..., title="Browser ID or Name", min_length=1, description="Terminates this session.")


class ExecutePlaywright(_Input):
    operation: Literal["execute_playwright"] = Field("execute_playwright", title="Execute Playwright Code")
    browser_id: str = Field(..., title="Browser ID or Name", min_length=1)
    code: str = Field(..., min_length=1, description="JavaScript or TypeScript with page, context and browser available. Return a value to expose it as result.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "typescript"})
    timeout_sec: int = Field(60, ge=1, le=300)
    executor: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]{1,64}$", description="Calls with the same executor name share state and run sequentially.")


class ListProfiles(_Page):
    operation: Literal["list_profiles"] = Field("list_profiles", title="List Browser Profiles")
    name: str | None = Field(None, description="Exact profile name filter.")


class GetProfile(_Input):
    operation: Literal["get_profile"] = Field("get_profile", title="Get Browser Profile")
    profile_id: str = Field(..., title="Profile ID or Name", min_length=1)


class CreateProfile(_Input):
    operation: Literal["create_profile"] = Field("create_profile", title="Create Browser Profile")
    name: str | None = Field(None, description="Optional profile name, unique within the logical project.")


class RenameProfile(_Input):
    operation: Literal["rename_profile"] = Field("rename_profile", title="Rename Browser Profile")
    profile_id: str = Field(..., title="Profile ID or Name", min_length=1)
    name: str = Field(..., min_length=1, max_length=255)


class DeleteProfile(_Input):
    operation: Literal["delete_profile"] = Field("delete_profile", title="Delete Browser Profile")
    profile_id: str = Field(..., title="Profile ID or Name", min_length=1)


class ListProxies(_Page):
    operation: Literal["list_proxies"] = Field("list_proxies", title="List Proxies")
    name: str | None = None
    ip_address: str | None = Field(None, description="Exact primary exit IPv4 address of an ISP proxy.")


class GetProxy(_Input):
    operation: Literal["get_proxy"] = Field("get_proxy", title="Get Proxy")
    proxy_id: str = Field(..., title="Proxy ID or Name", min_length=1)


class DeleteProxy(_Input):
    operation: Literal["delete_proxy"] = Field("delete_proxy", title="Delete Proxy")
    proxy_id: str = Field(..., title="Proxy ID", min_length=1, description="Deletion requires the ID; name addressing is retrieval only.")


class ListApps(_Page):
    operation: Literal["list_apps"] = Field("list_apps", title="List Apps")
    app_name: str | None = None
    version: str | None = None


class ListInvocations(_Page):
    operation: Literal["list_invocations"] = Field("list_invocations", title="List Action Invocations")
    app_name: str | None = None
    action_name: str | None = None
    version: str | None = None
    deployment_id: str | None = None
    status: Literal["queued", "running", "succeeded", "failed"] | None = None
    since: str | None = Field(None, description="RFC timestamp or duration such as 5m.")


class InvokeAction(_Input):
    operation: Literal["invoke_action"] = Field("invoke_action", title="Invoke App Action")
    app_name: str = Field(..., min_length=1)
    version: str = Field("latest")
    action_name: str = Field(..., min_length=1)
    payload: str | None = Field(None, description="Input data as a JSON string, as required by Kernel.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    asynchronous: bool = Field(True, description="Queue the invocation and return its ID; use Get Action Invocation to inspect completion.")
    async_timeout_seconds: int = Field(900, ge=10, le=3600)

    @field_validator("payload")
    @classmethod
    def json_payload(cls, value):
        if value is not None:
            try:
                json.loads(value)
            except (ValueError, TypeError):
                raise ValueError("Payload must be a JSON-encoded string") from None
        return value


class GetInvocation(_Input):
    operation: Literal["get_invocation"] = Field("get_invocation", title="Get Action Invocation")
    invocation_id: str = Field(..., min_length=1)


KernelOperation = Annotated[Union[
    GetAuthContext, ListBrowsers, GetBrowser, CreateBrowser, UpdateBrowser, DeleteBrowser,
    ExecutePlaywright, ListProfiles, GetProfile, CreateProfile, RenameProfile, DeleteProfile,
    ListProxies, GetProxy, DeleteProxy, ListApps, ListInvocations, InvokeAction, GetInvocation,
], Field(discriminator="operation")]


class KernelNodeConfig(NodeConfig[KernelOperation, KernelApiKeyCredential]):
    model_config = ConfigDict(title="Kernel Node Configuration")


# A closed mapping: no user-supplied method, origin or route.
ROUTES = {
    "get_auth_context": ("GET", "/auth/context", None),
    "list_browsers": ("GET", "/browsers", None),
    "get_browser": ("GET", "/browsers/{id}", "browser_id"),
    "create_browser": ("POST", "/browsers", None),
    "update_browser": ("PATCH", "/browsers/{id}", "browser_id"),
    "delete_browser": ("DELETE", "/browsers/{id}", "browser_id"),
    "execute_playwright": ("POST", "/browsers/{id}/playwright/execute", "browser_id"),
    "list_profiles": ("GET", "/profiles", None),
    "get_profile": ("GET", "/profiles/{id}", "profile_id"),
    "create_profile": ("POST", "/profiles", None),
    "rename_profile": ("PATCH", "/profiles/{id}", "profile_id"),
    "delete_profile": ("DELETE", "/profiles/{id}", "profile_id"),
    "list_proxies": ("GET", "/proxies", None),
    "get_proxy": ("GET", "/proxies/{id}", "proxy_id"),
    "delete_proxy": ("DELETE", "/proxies/{id}", "proxy_id"),
    "list_apps": ("GET", "/apps", None),
    "list_invocations": ("GET", "/invocations", None),
    "invoke_action": ("POST", "/invocations", None),
    "get_invocation": ("GET", "/invocations/{id}", "invocation_id"),
}


class KernelNode(WorkflowNode):
    integration_type = "automation-kernel"
    connection_evidence = ConnectionEvidence(
        noun="browser profiles", operation="list_profiles", identity_operation="get_auth_context",
        identity_keys=("name",),
    )

    @classmethod
    def get_config_model(cls):
        return KernelNodeConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect a Kernel API key")
        operation = config.operation
        method, route, id_field = ROUTES[operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        if id_field:
            route = route.replace("{id}", quote(values.pop(id_field), safe=""))
        if operation == "create_browser":
            profile_id = values.pop("profile_id", None)
            save_changes = values.pop("save_changes")
            if profile_id:
                values["profile"] = {"id": profile_id, "save_changes": save_changes}
            proxy_id = values.pop("proxy_id", None)
            if proxy_id:
                values["proxy"] = {"id": proxy_id}
        if operation == "invoke_action":
            values["async"] = values.pop("asynchronous")
            if not values["async"]:
                values.pop("async_timeout_seconds", None)
        params = {k: ("true" if v is True else "false" if v is False else v) for k, v in values.items()} if method == "GET" else None
        body = values if method in {"POST", "PATCH"} else None
        timeout = config.timeout_sec + 30 if operation == "execute_playwright" else 300 if operation == "invoke_action" and not config.asynchronous else 60
        async with guarded_async_client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, API_URL + route,
                headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        # No retries: a timeout must never replay a browser action or invocation.
        response.raise_for_status()
        output = {"operation": operation, "http_status": response.status_code}
        if method == "DELETE":
            if response.status_code != 204:
                raise ValueError("Kernel did not acknowledge deletion with HTTP 204")
            return {**output, "acknowledged": True}
        if "application/json" not in response.headers.get("content-type", "").lower():
            raise ValueError("Kernel returned a non-JSON response")
        data = response.json()
        if operation.startswith("list_"):
            if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                raise ValueError("Kernel returned an invalid list response")
            more = response.headers.get("X-Has-More")
            if more is not None and more.lower() not in {"true", "false"}:
                raise ValueError("Kernel returned an invalid pagination header")
            next_offset = response.headers.get("X-Next-Offset")
            if more is not None and more.lower() == "true":
                if next_offset is None or not next_offset.isdecimal() or int(next_offset) <= config.offset:
                    raise ValueError("Kernel continuation did not advance")
                output.update(has_more=True, next_offset=int(next_offset))
            elif more is not None:
                output.update(has_more=False, next_offset=None)
            else:
                # Missing headers cannot prove this is the final page.
                output.update(has_more=None, next_offset=None)
        elif not isinstance(data, dict):
            raise ValueError("Kernel returned an invalid resource response")
        elif operation != "execute_playwright" and (data.get("error") or data.get("success") is False):
            raise ValueError("Kernel returned an error response")
        if operation == "get_auth_context":
            organization = data.get("organization")
            if not isinstance(organization, dict) or not organization.get("id") or not isinstance(data.get("principal"), dict):
                raise ValueError("Kernel authentication context lacks an organization or principal")
            return {**data, **output, "name": organization["id"]}
        if operation == "execute_playwright":
            if not isinstance(data.get("success"), bool):
                raise ValueError("Kernel execution response lacks success")
            output["success"] = data["success"]
        return {**output, "data": data}
