"""CompanyCam Public API v1 operations using a personal access token.

Each action makes one documented request and returns the provider's data and
pagination metadata without automatically repeating writes or following URLs.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.companycam.com/public_api/v1"
TOKEN_DOCS = "https://help.companycam.com/en/articles/14724612-creating-access-tokens-and-application-keys"
ResourceID = Annotated[str, Field(pattern=r"^[1-9][0-9]*$", max_length=32)]


class CompanycamPersonalAccessToken(BaseModel):
    model_config = ConfigDict(
        title="Companycam Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": TOKEN_DOCS,
            "x-credential-instructions": "In CompanyCam on the web, open Integrations > Access Tokens > New Personal Access Token. Choose Read & Write for create and update actions, then copy the token. Paste only the token, without Bearer. Tokens expire according to the expiration you choose; replace an expired token here.",
        },
    )
    credential_type: Literal["companycam_personal_access_token"] = Field(
        "companycam_personal_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=4096, title="Personal access token",
                              repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste only the personal access token, without Bearer")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    limit: int = Field(50, ge=1, le=100, description="Maximum records in this page.")
    after: str | None = Field(None, max_length=4096, description="Cursor from the previous response's meta; leave blank for the first page.")


class GetCurrentUser(_Input):
    """Read the user who owns the token."""
    operation: Literal["get_current_user"] = "get_current_user"


class GetCurrentCompany(_Input):
    """Read the token's company."""
    operation: Literal["get_current_company"] = "get_current_company"


class ListProjects(_Page):
    """List one page of projects."""
    operation: Literal["list_projects"] = "list_projects"
    archived: Literal["true", "false"] | None = None


class _Project(_Input):
    project_id: ResourceID = Field(..., title="Project ID")


class GetProject(_Project):
    """Read a project by ID."""
    operation: Literal["get_project"] = "get_project"


class CreateProject(_Input):
    """Create a project with its required address. CompanyCam may return an existing matching project."""
    operation: Literal["create_project"] = "create_project"
    name: str = Field(..., min_length=1, max_length=1000)
    street_address_1: str = Field(..., min_length=1, max_length=1000)
    city: str = Field(..., min_length=1, max_length=200)
    state: str = Field(..., min_length=1, max_length=200)
    postal_code: str = Field(..., min_length=1, max_length=100)
    country: str = Field(..., min_length=1, max_length=200)
    customer_id: ResourceID | None = None


class UpdateProject(_Project):
    """Rename a project."""
    operation: Literal["update_project"] = "update_project"
    name: str = Field(..., min_length=1, max_length=1000)


class ArchiveProject(_Project):
    """Archive a project."""
    operation: Literal["archive_project"] = "archive_project"


class UnarchiveProject(_Project):
    """Unarchive a project."""
    operation: Literal["unarchive_project"] = "unarchive_project"


class ListProjectPhotos(_Page, _Project):
    """List one page of project photo metadata and image URLs."""
    operation: Literal["list_project_photos"] = "list_project_photos"


class _Photo(_Input):
    photo_id: ResourceID = Field(..., title="Photo ID")


class GetPhoto(_Photo):
    """Read a photo's metadata and image URLs without downloading it."""
    operation: Literal["get_photo"] = "get_photo"


class ListProjectComments(_Project):
    """List comments on a project."""
    operation: Literal["list_project_comments"] = "list_project_comments"


class CreateProjectComment(_Project):
    """Add a comment to a project."""
    operation: Literal["create_project_comment"] = "create_project_comment"
    content: str = Field(..., min_length=1, max_length=100000)


class ListPhotoComments(_Photo):
    """List comments on a photo."""
    operation: Literal["list_photo_comments"] = "list_photo_comments"


class CreatePhotoComment(_Photo):
    """Add a comment to a photo."""
    operation: Literal["create_photo_comment"] = "create_photo_comment"
    content: str = Field(..., min_length=1, max_length=100000)


class ListTags(_Input):
    """List the company's tags."""
    operation: Literal["list_tags"] = "list_tags"
    limit: int = Field(50, ge=1, le=100)


class CreateTag(_Input):
    """Create a tag or return the tag with the same display value."""
    operation: Literal["create_tag"] = "create_tag"
    display_value: str = Field(..., min_length=1, max_length=1000)


class ListCustomers(_Input):
    """List or search customers by the documented q filter."""
    operation: Literal["list_customers"] = "list_customers"
    q: str | None = Field(None, max_length=1000)


class GetCustomer(_Input):
    """Read a customer by ID."""
    operation: Literal["get_customer"] = "get_customer"
    customer_id: ResourceID = Field(..., title="Customer ID")


class CreateCustomer(_Input):
    """Create a customer with optional contact details."""
    operation: Literal["create_customer"] = "create_customer"
    name: str = Field(..., min_length=1, max_length=1000)
    email: str | None = Field(None, max_length=1000)
    phone_number: str | None = Field(None, max_length=100)
    notes: str | None = Field(None, max_length=100000)


class ListUsers(_Page):
    """List one page of company users."""
    operation: Literal["list_users"] = "list_users"
    status: Literal["active", "invited"] | None = None


CompanycamOperation = Annotated[Union[
    GetCurrentUser, GetCurrentCompany, ListProjects, GetProject, CreateProject,
    UpdateProject, ArchiveProject, UnarchiveProject, ListProjectPhotos, GetPhoto,
    ListProjectComments, CreateProjectComment, ListPhotoComments, CreatePhotoComment,
    ListTags, CreateTag, ListCustomers, GetCustomer, CreateCustomer, ListUsers,
], Field(discriminator="operation")]


class CompanycamConfig(NodeConfig[CompanycamOperation, CompanycamPersonalAccessToken]):
    model_config = ConfigDict(title="CompanyCam Node Configuration")


# Paths and body envelopes are from the pinned CompanyCam Public API v1 contract.
ROUTES = {
    "get_current_user": ("GET", "/users/current", None),
    "get_current_company": ("GET", "/companies/current", None),
    "list_projects": ("GET", "/projects", None),
    "get_project": ("GET", "/projects/{project_id}", None),
    "create_project": ("POST", "/projects", "project"),
    "update_project": ("PATCH", "/projects/{project_id}", "project"),
    "archive_project": ("PATCH", "/projects/{project_id}/archive", None),
    "unarchive_project": ("PATCH", "/projects/{project_id}/unarchive", None),
    "list_project_photos": ("GET", "/projects/{project_id}/photos", None),
    "get_photo": ("GET", "/photos/{photo_id}", None),
    "list_project_comments": ("GET", "/projects/{project_id}/comments", None),
    "create_project_comment": ("POST", "/projects/{project_id}/comments", "comment"),
    "list_photo_comments": ("GET", "/photos/{photo_id}/comments", None),
    "create_photo_comment": ("POST", "/photos/{photo_id}/comments", "comment"),
    "list_tags": ("GET", "/tags", None),
    "create_tag": ("POST", "/tags", "tag"),
    "list_customers": ("GET", "/customers", None),
    "get_customer": ("GET", "/customers/{customer_id}", None),
    "create_customer": ("POST", "/customers", "customer"),
    "list_users": ("GET", "/users", None),
}


class CompanycamNode(WorkflowNode):
    integration_type = "automation-companycam"
    credential_provider_labels = {"companycam": "CompanyCam"}
    connection_evidence = ConnectionEvidence(identity_operation="get_current_company", noun="company")

    @classmethod
    def get_config_model(cls):
        return CompanycamConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a CompanyCam personal access token")
        op = self.config.config
        method, path, envelope = ROUTES[op.operation]
        values = op.model_dump(exclude={"operation"}, exclude_none=True)
        for name in tuple(values):
            if "{" + name + "}" in path:
                path = path.replace("{" + name + "}", values.pop(name))
        token = self.config.credentials.access_token
        kwargs = {"params": values} if method == "GET" else {"json": {envelope: values} if envelope else {}}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, headers={
                "Authorization": "Bearer " + token, "Accept": "application/json",
            }, **kwargs)
        try:
            body = response.json()
        except ValueError:
            raise ValueError(f"CompanyCam returned non-JSON (HTTP {response.status_code})") from None
        if not isinstance(body, dict):
            raise ValueError("CompanyCam returned an invalid response envelope")
        if not 200 <= response.status_code < 300 or body.get("errors"):
            import json
            detail = json.dumps(body.get("errors", []), ensure_ascii=True).replace(token, "[redacted]")[:2000]
            raise ValueError(f"CompanyCam rejected the request (HTTP {response.status_code}): {detail}")
        expected = list if op.operation.startswith("list_") else dict
        if not isinstance(body.get("data"), expected) or not isinstance(body.get("meta"), dict):
            raise ValueError("CompanyCam returned unexpected data or pagination metadata")
        return {"status": "success", "data": body["data"], "meta": body["meta"]}
