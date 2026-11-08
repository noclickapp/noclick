"""Honeybadger v3 account, project and error automation.

Contract: honeybadger-io/api-go openapi/bundled.yaml, version 3.0.0.
Each operation makes one request. Lists return one page and the provider's
pagination links without following arbitrary URLs; writes are never retried.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

NODE_TYPE = "automation-honeybadger"
Identifier = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")]


class HoneybadgerAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Honeybadger API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.honeybadger.io/api/v3/authentication/",
            "x-credential-instructions": "API v3 is in preview: ask Honeybadger support to enable API tokens for your account, then create a v3 API token and paste it here. v2 personal auth tokens and project ingestion keys do not work. Choose your account's region. Grant only the scopes needed: account:read, projects:read, projects:create, projects:write, faults:read, faults:write and deploys:read. Connection checks read the token's account ID; they do not verify every operation's permissions.",
        })
    credential_type: Literal["honeybadger_api_token"] = Field("honeybadger_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", json_schema_extra={"ui:widget": "password"})
    region: Literal["us", "eu"] = Field("us", title="Account region", description="Use the region where your Honeybadger account is hosted.")

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token", key=True)
        if any(c.isspace() for c in value) or value.lower().startswith("bearer "):
            raise ValueError("Paste only the API token, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)


class _Project(_Input):
    project_id: Identifier = Field(..., description="v3 project ID, from List projects (for example Xk9mZp).")


class _Fault(_Project):
    fault_id: Identifier = Field(..., description="Fault ID as a string, from List faults.")


class _Comment(_Fault):
    comment_id: Identifier


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page number; read links.next for the next page.")
    per_page: int = Field(25, ge=1, le=100)


class _Timeline(_Input):
    limit: int = Field(25, ge=1, le=100)
    before: str | None = Field(None, max_length=2000, description="Cursor from links.older; fetch older items.")
    after: str | None = Field(None, max_length=2000, description="Cursor from links.newer; fetch newer items.")

    @model_validator(mode="after")
    def one_direction(self):
        if self.before and self.after:
            raise ValueError("Choose either before or after")
        return self


class GetToken(_Input):
    """Read the token's account, project visibility and granted scopes."""
    operation: Literal["get_token"] = "get_token"


class GetAccount(_Input):
    """Read account details (account:read)."""
    operation: Literal["get_account"] = "get_account"


class GetAccountUsage(_Input):
    """Read account quota and consumption (account:read)."""
    operation: Literal["get_account_usage"] = "get_account_usage"


class ListProjects(_Page):
    """List accessible projects (projects:read), one page at a time."""
    operation: Literal["list_projects"] = "list_projects"
    name: str | None = Field(None, max_length=1000, description="Exact project name filter.")


class CreateProject(_Input):
    """Create a project (projects:create)."""
    operation: Literal["create_project"] = "create_project"
    name: str = Field(..., min_length=1, max_length=1000)
    language: str | None = Field(None, max_length=100)
    disable_email_notifications: StrictBool = Field(False, description="Switch off email notifications for members added with the new project.")


class GetProject(_Project):
    """Read a project (projects:read)."""
    operation: Literal["get_project"] = "get_project"


class UpdateProject(_Project):
    """Change supplied project settings (projects:write); omitted fields stay unchanged."""
    operation: Literal["update_project"] = "update_project"
    name: str | None = Field(None, min_length=1, max_length=1000)
    language: str | None = Field(None, max_length=100, description="Null clears the primary language.")
    resolve_errors_on_deploy: StrictBool | None = Field(None, description="Resolve open faults when a deploy is recorded. Null resets to true.")
    disable_public_links: StrictBool | None = Field(None, description="Disallow public fault links. Null resets to false.")


class GetProjectStats(_Project):
    """Read error and notice counts (projects:read)."""
    operation: Literal["get_project_stats"] = "get_project_stats"


class ListFaults(_Project, _Page):
    """Search project faults (faults:read), one page at a time."""
    operation: Literal["list_faults"] = "list_faults"
    q: str | None = Field(None, max_length=2000, description="Honeybadger error search, e.g. environment:production is:unresolved.")
    order: Literal["recent", "frequent"] | None = None
    sort: Literal["asc", "desc"] | None = None
    created_after: float | None = Field(None, description="Unix timestamp in seconds.")
    occurred_after: float | None = Field(None, description="Unix timestamp in seconds.")
    occurred_before: float | None = Field(None, description="Unix timestamp in seconds.")


class GetFault(_Fault):
    """Read one fault (faults:read)."""
    operation: Literal["get_fault"] = "get_fault"


class UpdateFault(_Fault):
    """Resolve, ignore, tag or schedule resolution of a fault (faults:write)."""
    operation: Literal["update_fault"] = "update_fault"
    resolved: StrictBool | None = None
    ignored: StrictBool | None = None
    tags: list[str] | None = Field(None, max_length=100, description="Replace tags; [] clears them; null clears them.")
    resolve_on_deploy: StrictBool | None = Field(None, description="Resolve on the next deploy; ignored or resolved faults cannot have a pending resolution.")


class ListComments(_Fault, _Timeline):
    """Read fault comments (faults:read), one page at a time."""
    operation: Literal["list_comments"] = "list_comments"


class CreateComment(_Fault):
    """Add a fault comment (faults:write). @mentions notify project members."""
    operation: Literal["create_comment"] = "create_comment"
    body: str = Field(..., min_length=1, max_length=100000, title="Comment text")


class GetComment(_Comment):
    """Read one comment (faults:read)."""
    operation: Literal["get_comment"] = "get_comment"


class UpdateComment(_Comment):
    """Edit a comment (faults:write). @mentions notify project members."""
    operation: Literal["update_comment"] = "update_comment"
    body: str = Field(..., min_length=1, max_length=100000, title="Comment text")


class DeleteComment(_Comment):
    """Permanently delete a fault comment (faults:write)."""
    operation: Literal["delete_comment"] = "delete_comment"


class ListNotices(_Fault, _Timeline):
    """Read individual error occurrences (faults:read), one page at a time."""
    operation: Literal["list_notices"] = "list_notices"
    unmapped: StrictBool = False
    breadcrumbs: StrictBool = False


class GetNotice(_Input):
    """Read one notice including its breadcrumbs (faults:read)."""
    operation: Literal["get_notice"] = "get_notice"
    uuid: Annotated[str, Field(pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")]
    unmapped: StrictBool = False


class ListDeploys(_Project, _Timeline):
    """Read deployment history (deploys:read), one page at a time."""
    operation: Literal["list_deploys"] = "list_deploys"
    environment: str | None = Field(None, max_length=1000)
    local_username: str | None = Field(None, max_length=1000)


HoneybadgerConfig = Annotated[Union[GetToken, GetAccount, GetAccountUsage,
    ListProjects, CreateProject, GetProject, UpdateProject, GetProjectStats,
    ListFaults, GetFault, UpdateFault, ListComments, CreateComment, GetComment,
    UpdateComment, DeleteComment, ListNotices, GetNotice, ListDeploys], Field(discriminator="operation")]


class HoneybadgerNodeConfig(NodeConfig[HoneybadgerConfig, HoneybadgerAPITokenCredential]):
    pass


OPERATIONS = {
    "get_token": ("GET", "/token"),
    "get_account": ("GET", "/account"),
    "get_account_usage": ("GET", "/account/usage"),
    "list_projects": ("GET", "/projects"),
    "create_project": ("POST", "/projects"),
    "get_project": ("GET", "/projects/{project_id}"),
    "update_project": ("PATCH", "/projects/{project_id}"),
    "get_project_stats": ("GET", "/projects/{project_id}/stats"),
    "list_faults": ("GET", "/projects/{project_id}/faults"),
    "get_fault": ("GET", "/projects/{project_id}/faults/{fault_id}"),
    "update_fault": ("PATCH", "/projects/{project_id}/faults/{fault_id}"),
    "list_comments": ("GET", "/projects/{project_id}/faults/{fault_id}/comments"),
    "create_comment": ("POST", "/projects/{project_id}/faults/{fault_id}/comments"),
    "get_comment": ("GET", "/projects/{project_id}/faults/{fault_id}/comments/{comment_id}"),
    "update_comment": ("PATCH", "/projects/{project_id}/faults/{fault_id}/comments/{comment_id}"),
    "delete_comment": ("DELETE", "/projects/{project_id}/faults/{fault_id}/comments/{comment_id}"),
    "list_notices": ("GET", "/projects/{project_id}/faults/{fault_id}/notices"),
    "get_notice": ("GET", "/notices/{uuid}"),
    "list_deploys": ("GET", "/projects/{project_id}/deploys"),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key.replace(token, "[redacted]"): _redact(item, token) for key, item in value.items()}
    return value


class HoneybadgerNode(WorkflowNode):
    integration_type = "automation-honeybadger"
    connection_evidence = ConnectionEvidence(noun="Honeybadger account", identity_operation="get_token", identity_keys=("account_id",))
    edit_examples = ["Find unresolved production errors", "Resolve this fault", "Comment on the error after a rollback", "List recent deployments"]

    @classmethod
    def get_config_model(cls):
        return HoneybadgerNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Honeybadger v3 API token")
        credential = self.config.credentials
        op = self.config.config
        method, path = OPERATIONS[op.operation]
        values = op.model_dump(exclude={"operation"}, exclude_unset=True)
        # Defaults on list parameters are intentional and part of the request.
        for key in ("page", "per_page", "limit", "unmapped", "breadcrumbs", "disable_email_notifications"):
            if hasattr(op, key):
                values[key] = getattr(op, key)
        for field in ("project_id", "fault_id", "comment_id", "uuid"):
            if "{" + field + "}" in path:
                path = path.replace("{" + field + "}", quote(str(values.pop(field)), safe=""))
        if method in {"PATCH", "POST"}:
            # Null only has meaning for documented nullable fields. Optional
            # booleans on FaultInput are not nullable, so omit unset markers.
            if isinstance(op, UpdateFault):
                values = {key: value for key, value in values.items() if value is not None or key == "tags"}
            if isinstance(op, UpdateProject) and values.get("name", True) is None:
                values.pop("name")
            if not values:
                raise ValueError("Supply at least one field to update")
            params, body = None, values
        else:
            params = {key: str(value).lower() if isinstance(value, bool) else value for key, value in values.items() if value is not None}
            body = None
        origin = "https://eu-app.honeybadger.io" if credential.region == "eu" else "https://app.honeybadger.io"
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, origin + "/v3" + path,
                    headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            raise ValueError("Honeybadger request did not complete; inspect the provider before retrying a write") from None
        if response.status_code == 204 and method == "DELETE":
            result = {"status": "success", "operation": op.operation, "http_status": 204, "deletion_acknowledged": True}
        else:
            try:
                payload = response.json()
            except ValueError:
                raise ValueError(f"Honeybadger returned a non-JSON response (HTTP {response.status_code})") from None
            if response.status_code >= 300 or not isinstance(payload, dict) or "error" in payload:
                error = payload.get("error", {}) if isinstance(payload, dict) else {}
                message = error.get("message", "Request was not accepted") if isinstance(error, dict) else str(error)
                code = error.get("code") if isinstance(error, dict) else None
                raise ValueError(_redact(f"Honeybadger API error {response.status_code}: {message}" + (f" ({code})" if code else ""), credential.api_token))
            if "data" not in payload or not isinstance(payload["data"], (dict, list)):
                raise ValueError("Honeybadger response is missing its data object or array")
            if op.operation.startswith("list_") != isinstance(payload["data"], list):
                raise ValueError("Honeybadger response has an unexpected data shape")
            if op.operation == "get_token" and not isinstance(payload["data"].get("account_id"), str):
                raise ValueError("Honeybadger token response is missing the account ID")
            result = {**payload, "status": "success", "operation": op.operation, "http_status": response.status_code}
        result = _redact(result, credential.api_token)
        await self.emit(result)
        return result
