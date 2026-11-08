"""Harvey Vault, client/matter and Intake operations.

Contract: https://developers.harvey.ai/{vault,client_matters,intake}_api.json.
Each operation makes one API request. List operations return a single page,
including the provider's pagination metadata for explicit continuation.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union
from uuid import UUID
from urllib.parse import quote

from pydantic import (
    BaseModel,
    AwareDatetime,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class HarveyTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Harvey API Token",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.harvey.ai/api-reference/authentication"
        },
    )
    credential_type: Literal["harvey_api_token"] = Field(
        "harvey_api_token", json_schema_extra={"ui:hidden": True}
    )
    api_token: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        title="API Token",
        repr=False,
        description="Create a token in Harvey workspace settings → API Tokens. Paste it without the Bearer prefix. Enable Vault, Client Matters and Intake permissions for the operations you use.",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Token")
        if not value.isascii() or any(
            c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value
        ):
            raise ValueError(
                "Paste the API token without a header prefix or whitespace"
            )
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class HarveyClientInput(_Config):
    client_id: str = Field(
        ...,
        description="The firm's client identifier, the upsert key within the workspace. Not the Harvey client UUID that `GET /api/v1/client_matters` returns in its own `client_id` field. Empty after stripping, or over 128 characters, fails per row with `invalid_client_id`.",
        title="Client Id",
    )
    client_name: str | None = Field(
        None,
        description="Friendly label for the client. Over 256 characters fails per row with `invalid_client_name`.",
        title="Client Name",
    )


class HarveyMatterInput(_Config):
    client_id: str = Field(
        ...,
        description="The firm's client identifier as sent to `POST /api/v2/clients`. Not the Harvey client UUID that `GET /api/v1/client_matters` returns in its own `client_id` field. Must resolve to a live client; this endpoint never creates clients. Empty after stripping fails per row with `invalid_client_id`; an unknown client fails per row with `client_not_found`.",
        title="Client Id",
    )
    matter_id: str = Field(
        ...,
        description="The firm's matter identifier. `GET /api/v1/client_matters` returns this value as `matter_number`. Empty after stripping fails per row with `invalid_matter_id`.",
        title="Matter Id",
    )
    matter_name: str | None = Field(
        None,
        description="Matter label. Over 256 characters fails per row with `invalid_matter_name`.",
        title="Matter Name",
    )
    description: str | None = Field(
        None,
        description="Matter description. More than 200 characters after trimming whitespace fails per row with description_too_long.",
        title="Description",
    )
    allowed: bool | None = Field(
        None,
        description="Whether users can select the matter. Omit to leave the stored value unchanged; a new matter defaults to true. Sending `allowed` requires the disallowed-matters permission; without it the whole batch is 403. Must be a JSON boolean; null fails the whole request with `invalid_request`.",
        title="Allowed",
    )
    notice: str | None = Field(
        None,
        description="Selection notice shown to users when they pick the matter, at most 2000 characters after stripping. A longer value fails per row with `notice_too_long`. Omit to leave the stored notice unchanged. Send null or a blank string to clear it. A whitespace-only value clears and never fails. Requires the same client matters write permission as the route.",
        title="Notice",
    )


class HarveyMatterIdentifier(_Config):
    client_id: str = Field(
        ...,
        description="The firm's client identifier, the client_id used in v2 upserts. Not the Harvey client UUID.",
        title="Client Id",
    )
    matter_id: str = Field(
        ...,
        description="The firm's matter identifier, the matter_id used in v2 upserts. Not the Harvey matter UUID (harvey_id) or the full stored name.",
        title="Matter Id",
    )


class HarveyListProjectsConfig(_Config):
    "List Vault Projects and Knowledge Bases. https://developers.harvey.ai/api-reference/vault/list-vault-projects-and-knowledge-bases"
    operation: Literal["list_projects"] = Field(
        "list_projects", json_schema_extra={"ui:hidden": True}
    )
    page: int = Field(
        1, ge=1, description="Page number for pagination (default: 1)", title="Page"
    )
    per_page: int = Field(
        20,
        ge=1,
        le=100,
        description="Number of items per page (default: 20, max: 100)",
        title="Per Page",
    )
    name: str | None = Field(
        None,
        max_length=256,
        description="Case-insensitive substring match on project name.",
        title="Name",
    )
    is_knowledge_base: bool | None = Field(
        None,
        description="Filter by knowledge base flag. `true` returns only knowledge base projects, `false` excludes them, and omitting the parameter returns both.",
        title="Is Knowledge Base",
    )
    created_after: int | None = Field(
        None,
        description="Inclusive lower bound on project creation time, expressed as a UTC Unix epoch timestamp in seconds. Only projects with `created_at >= created_after` are returned. Must be strictly less than `created_before` when both are provided.",
        title="Created After",
    )
    created_before: int | None = Field(
        None,
        description="Exclusive upper bound on project creation time, expressed as a UTC Unix epoch timestamp in seconds. Only projects with `created_at < created_before` are returned.",
        title="Created Before",
    )
    sort_by: Literal["date", "name"] = Field(
        "date",
        description="Field to sort the results by. `date` sorts by the project's last content-update timestamp (the default ordering). `name` sorts alphabetically by project name.",
        title="Sort By",
    )
    sort_order: Literal["asc", "desc"] = Field(
        "desc", description="Sort direction to order results list.", title="Sort Order"
    )

    @model_validator(mode="after")
    def ordered_window(self):
        if (
            self.created_after is not None
            and self.created_before is not None
            and self.created_after >= self.created_before
        ):
            raise ValueError("The lower timestamp must precede the upper timestamp")
        return self


class HarveyListRecycledProjectsConfig(_Config):
    "List Vaults in the Recycle Bin. https://developers.harvey.ai/api-reference/vault/list-vaults-in-the-recycle-bin"
    operation: Literal["list_recycled_projects"] = Field(
        "list_recycled_projects", json_schema_extra={"ui:hidden": True}
    )
    search_text: str | None = Field(
        None,
        description="Case-insensitive substring filter on the vault name.",
        title="Search Text",
    )
    client_matter_id: UUID | None = Field(
        None,
        description="Restrict results to vaults associated with this client matter (the client matter UUID, not the human-readable matter number).",
        title="Client Matter Id",
    )


class HarveyGetProjectConfig(_Config):
    "Get Vault Project Metadata. https://developers.harvey.ai/api-reference/vault/get-vault-project-metadata"
    operation: Literal["get_project"] = Field(
        "get_project", json_schema_extra={"ui:hidden": True}
    )
    project_id: str = Field(..., description="The project ID.", title="Project Id")


class HarveyGetReviewTableConfig(_Config):
    "Get Review Table Metadata. https://developers.harvey.ai/api-reference/vault/get-review-table-metadata"
    operation: Literal["get_review_table"] = Field(
        "get_review_table", json_schema_extra={"ui:hidden": True}
    )
    review_table_id: int = Field(
        ...,
        description="The integer ID of the review table. Obtain this from the `review_table_ids` array in the Get Vault Project Metadata response.",
        title="Review Table Id",
    )


class HarveyGetFilesConfig(_Config):
    "Get File Details. https://developers.harvey.ai/api-reference/vault/get-file-details"
    operation: Literal["get_files"] = Field(
        "get_files", json_schema_extra={"ui:hidden": True}
    )
    file_ids: list[UUID] = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Comma-separated list of file IDs to retrieve details for.",
        title="File Ids",
    )


class HarveyGetReviewTableRowConfig(_Config):
    "Get Review Table Row Details. https://developers.harvey.ai/api-reference/vault/get-review-table-row-details"
    operation: Literal["get_review_table_row"] = Field(
        "get_review_table_row", json_schema_extra={"ui:hidden": True}
    )
    review_table_id: int = Field(
        ...,
        description="The review table ID (integer). This is the same value as `review_table_ids` entries returned by Get Vault Project Metadata and as `review_table_id` returned by Get Review Table Metadata.",
        title="Review Table Id",
    )
    file_id: UUID = Field(
        ...,
        description="The file ID corresponding to the row. A file that is part of a file group resolves to the group's row.",
        title="File Id",
    )


class HarveyAddReviewTableRowConfig(_Config):
    "Add Row to Review Table. https://developers.harvey.ai/api-reference/vault/add-row-to-review-table"
    operation: Literal["add_review_table_row"] = Field(
        "add_review_table_row", json_schema_extra={"ui:hidden": True}
    )
    review_table_id: int = Field(
        ...,
        description="The review table ID (integer). This is the same value as `review_table_ids` entries returned by Get Vault Project Metadata and as `review_table_id` returned by Get Review Table Metadata.",
        title="Review Table Id",
    )
    file_ids: list[UUID] = Field(
        ...,
        min_length=1,
        max_length=25,
        description="The IDs of the files to add. One file is added as its own row; two or more are grouped into a file group that occupies a single row. Every file must belong to the review table's Vault project, must have finished processing, and must not already have a row or group membership in the table. Duplicate IDs are rejected with `400`. Capped at 25 files per request by default; workspaces with a raised file-group limit may send more.",
        title="File Ids",
    )
    group_name: str | None = Field(
        None,
        description="Optional name for the file group created when two or more files are added. Defaults to the first file's name. Ignored for single-file requests.",
        title="Group Name",
    )


class HarveyListProjectFilesConfig(_Config):
    "List Files in a Vault Project. https://developers.harvey.ai/api-reference/vault/list-files-in-a-vault-project"
    operation: Literal["list_project_files"] = Field(
        "list_project_files", json_schema_extra={"ui:hidden": True}
    )
    project_id: UUID = Field(
        ...,
        description="The unique identifier of the vault project",
        title="Project Id",
    )
    cursor: str | None = Field(
        None,
        max_length=2048,
        description="Opaque pagination cursor returned in the previous response's `next_cursor` field. Omit on the first request.",
        title="Cursor",
    )
    limit: int = Field(
        20,
        ge=1,
        le=100,
        description="Maximum number of files to return per page.",
        title="Limit",
    )
    name: str | None = Field(
        None,
        max_length=256,
        description="Case-insensitive substring match on file name. `%` and `_` are treated as literals, not SQL `LIKE` wildcards.",
        title="Name",
    )
    content_type: list[str] | None = Field(
        None,
        max_length=20,
        description="Filter by MIME type. Repeat the query parameter to match any of multiple values (e.g. `?content_type=application/pdf&content_type=text/plain`). Up to 20 values, each at most 256 characters.",
        title="Content Type",
    )
    processing_status: list[
        Literal[
            "UPLOADED",
            "PROCESSING",
            "READY_TO_QUERY",
            "READY_TO_REVIEW",
            "RECOVERABLE_FAILURE",
            "UNRECOVERABLE_FAILURE",
        ]
    ] | None = Field(
        None,
        max_length=20,
        description="Filter by processing status. Repeat the query parameter to match any of multiple values. Accepted case-insensitively (`READY_TO_QUERY` and `ready_to_query` are equivalent). Internal-only statuses are rejected. Up to 20 values.",
        title="Processing Status",
    )
    uploaded_after: int | None = Field(
        None,
        description="Inclusive lower bound on the file's upload time, as a UTC Unix epoch timestamp in seconds. Must be strictly less than `uploaded_before` when both are provided.",
        title="Uploaded After",
    )
    uploaded_before: int | None = Field(
        None,
        description="Inclusive upper bound on the file's upload time, as a UTC Unix epoch timestamp in seconds.",
        title="Uploaded Before",
    )
    sort_by: Literal["name", "uploaded_at", "size"] = Field(
        "uploaded_at",
        description="Field to sort the results by. Accepted case-insensitively.",
        title="Sort By",
    )
    sort_order: Literal["asc", "desc"] = Field(
        "desc",
        description="Sort direction. Accepted case-insensitively. Results include the file `id` as a deterministic tiebreaker so cursor-paginated ordering is stable across pages.",
        title="Sort Order",
    )

    @model_validator(mode="after")
    def ordered_window(self):
        if (
            self.uploaded_after is not None
            and self.uploaded_before is not None
            and self.uploaded_after >= self.uploaded_before
        ):
            raise ValueError("The lower timestamp must precede the upper timestamp")
        return self


class HarveyListProjectUsersConfig(_Config):
    "List Project Users. https://developers.harvey.ai/api-reference/vault/list-project-users"
    operation: Literal["list_project_users"] = Field(
        "list_project_users", json_schema_extra={"ui:hidden": True}
    )
    project_id: UUID = Field(
        ...,
        description="The unique identifier of the Vault project",
        title="Project Id",
    )


class HarveyCreateProjectConfig(_Config):
    "Create a new Vault project. https://developers.harvey.ai/api-reference/vault/create-a-new-vault-project"
    operation: Literal["create_project"] = Field(
        "create_project", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(..., description="The name of the new project", title="Name")
    client_matter_id: UUID | None = Field(
        None,
        description="When set, associates the new project with this client matter. Use the client matter UUID (from Client Matters API responses), not the human-readable matter number.",
        title="Client Matter Id",
    )


class HarveySearchProjectConfig(_Config):
    "Semantic search over a vault project. https://developers.harvey.ai/api-reference/vault/semantic-search-over-a-vault-project"
    operation: Literal["search_project"] = Field(
        "search_project", json_schema_extra={"ui:hidden": True}
    )
    project_id: UUID = Field(
        ..., description="UUID of the vault project to search in", title="Project Id"
    )
    query: str = Field(
        ..., min_length=1, description="Natural language search query.", title="Query"
    )
    include_file_names: bool = Field(
        False,
        description="When true, each chunk in the response includes a file_name field (display name of the source file, or null if the file was deleted after indexing). Omit or set to false for backward compatibility.",
        title="Include File Names",
    )


class HarveyDeleteFileConfig(_Config):
    "Delete a file from a Vault project. https://developers.harvey.ai/api-reference/vault/delete-a-file-from-a-vault-project"
    operation: Literal["delete_file"] = Field(
        "delete_file", json_schema_extra={"ui:hidden": True}
    )
    file_id: UUID = Field(
        ..., description="The unique identifier of the file to delete", title="File Id"
    )


class HarveyDeleteProjectConfig(_Config):
    "Delete an entire vault project and all its contents. https://developers.harvey.ai/api-reference/vault/delete-an-entire-vault-project-and-all-its-contents"
    operation: Literal["delete_project"] = Field(
        "delete_project", json_schema_extra={"ui:hidden": True}
    )
    project_id: UUID = Field(
        ...,
        description="The unique identifier of the project to delete",
        title="Project Id",
    )


class HarveyGetClientMattersConfig(_Config):
    "Get Client Matters. https://developers.harvey.ai/api-reference/retrieve/get-client-matters"
    operation: Literal["get_client_matters"] = Field(
        "get_client_matters", json_schema_extra={"ui:hidden": True}
    )


class HarveyUpsertClientsConfig(_Config):
    "Upsert Clients. https://developers.harvey.ai/api-reference/upsert/upsert-clients"
    operation: Literal["upsert_clients"] = Field(
        "upsert_clients", json_schema_extra={"ui:hidden": True}
    )
    clients: list[HarveyClientInput] = Field(
        ..., min_length=1, max_length=10000, title="Clients"
    )


class HarveyDeleteClientsConfig(_Config):
    "Delete Clients. https://developers.harvey.ai/api-reference/delete/delete-clients"
    operation: Literal["delete_clients"] = Field(
        "delete_clients", json_schema_extra={"ui:hidden": True}
    )
    client_ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="The firm's client identifiers, the client_id values used in v2 upserts. Not client labels or Harvey client UUIDs. Surrounding whitespace is trimmed.",
        title="Client Ids",
    )


class HarveyUpsertMattersConfig(_Config):
    "Upsert Matters. https://developers.harvey.ai/api-reference/upsert/upsert-matters"
    operation: Literal["upsert_matters"] = Field(
        "upsert_matters", json_schema_extra={"ui:hidden": True}
    )
    matters: list[HarveyMatterInput] = Field(
        ..., min_length=1, max_length=10000, title="Matters"
    )


class HarveyDeleteMattersConfig(_Config):
    "Delete Matters. https://developers.harvey.ai/api-reference/delete/delete-matters"
    operation: Literal["delete_matters"] = Field(
        "delete_matters", json_schema_extra={"ui:hidden": True}
    )
    matters: list[HarveyMatterIdentifier] = Field(
        ..., min_length=1, max_length=10000, title="Matters"
    )


class HarveyCreateIntakeRequestConfig(_Config):
    "Create Request. https://developers.harvey.ai/api-reference/intake/create-request"
    operation: Literal["create_intake_request"] = Field(
        "create_intake_request", json_schema_extra={"ui:hidden": True}
    )
    idempotency_key: str = Field(
        ...,
        min_length=1,
        description="An identifier you choose for this request, unique within your workspace. A retry carrying a key Harvey has already accepted returns the original request with `200` instead of creating a second one. Must not be blank or whitespace only.",
        title="Idempotency Key",
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Short summary of what is being asked for. Surrounding whitespace is stripped, and the result must not be empty.",
        title="Title",
    )
    description: str | None = Field(
        None,
        max_length=10000,
        description="The full request, in as much detail as the reviewer needs.",
        title="Description",
    )


class HarveyListIntakeRequestsConfig(_Config):
    "List Requests. https://developers.harvey.ai/api-reference/intake/list-requests"
    operation: Literal["list_intake_requests"] = Field(
        "list_intake_requests", json_schema_extra={"ui:hidden": True}
    )
    limit: int = Field(
        20,
        ge=1,
        le=100,
        description="The page size. Values outside the range are clamped rather than rejected.",
        title="Limit",
    )
    cursor: str | None = Field(
        None,
        description="The `pagination.next_cursor` from the previous page. Send the same filters with it, since a cursor resumes only the list it was issued for.",
        title="Cursor",
    )
    status: list[
        Literal["TODO", "IN_PROGRESS", "READY_FOR_REVIEW", "DONE", "CANCELLED"]
    ] | None = Field(
        None,
        description="Returns only requests in one of these statuses. Repeat it for several, as in `status=TODO&status=IN_PROGRESS`. No other parameter may repeat.",
        title="Status",
    )
    created_after: AwareDatetime | None = Field(
        None,
        description="Returns only requests created at or after this time. The value must include a UTC offset.",
        title="Created After",
    )
    created_before: AwareDatetime | None = Field(
        None,
        description="Returns only requests created before this time. The value must include a UTC offset.",
        title="Created Before",
    )


class HarveyGetIntakeRequestConfig(_Config):
    "Get Request. https://developers.harvey.ai/api-reference/intake/get-request"
    operation: Literal["get_intake_request"] = Field(
        "get_intake_request", json_schema_extra={"ui:hidden": True}
    )
    request_id: UUID = Field(
        ...,
        description="The unique identifier of the intake request, as returned when it was submitted.",
        title="Request Id",
    )


class HarveyUpdateIntakeRequestConfig(_Config):
    "Update Request. https://developers.harvey.ai/api-reference/intake/update-request"
    operation: Literal["update_intake_request"] = Field(
        "update_intake_request", json_schema_extra={"ui:hidden": True}
    )
    request_id: UUID = Field(
        ...,
        description="The unique identifier of the intake request, as returned when it was submitted.",
        title="Request Id",
    )
    title: str | None = Field(
        None,
        min_length=1,
        max_length=255,
        description="The new title. Surrounding whitespace is removed, and it cannot be null or blank.",
        title="Title",
    )
    description: str | None = Field(
        None,
        max_length=10000,
        description="The new description as plain text. Send `null` to remove it.",
        title="Description",
    )
    status: Literal[
        "TODO", "IN_PROGRESS", "READY_FOR_REVIEW", "DONE", "CANCELLED"
    ] | None = Field(
        None, description="Lifecycle state of an intake request.", title="Status"
    )
    due_at: date | None = Field(
        None,
        description="The new due date as `YYYY-MM-DD`. Send `null` to remove it.",
        title="Due At",
    )

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set - {"operation", "request_id"}:
            raise ValueError("Provide at least one field to update")
        for name in ("title", "status"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class HarveyListIntakeCommentsConfig(_Config):
    "List Comments. https://developers.harvey.ai/api-reference/intake/list-comments"
    operation: Literal["list_intake_comments"] = Field(
        "list_intake_comments", json_schema_extra={"ui:hidden": True}
    )
    request_id: UUID = Field(
        ...,
        description="The unique identifier of the intake request, as returned when it was submitted.",
        title="Request Id",
    )
    limit: int = Field(
        20,
        ge=1,
        le=100,
        description="The page size. Values outside the range are clamped rather than rejected.",
        title="Limit",
    )
    cursor: str | None = Field(
        None,
        description="The `pagination.next_cursor` from the previous page of this request's comments.",
        title="Cursor",
    )


HarveyConfig = Annotated[
    Union[
        HarveyListProjectsConfig,
        HarveyListRecycledProjectsConfig,
        HarveyGetProjectConfig,
        HarveyGetReviewTableConfig,
        HarveyGetFilesConfig,
        HarveyGetReviewTableRowConfig,
        HarveyAddReviewTableRowConfig,
        HarveyListProjectFilesConfig,
        HarveyListProjectUsersConfig,
        HarveyCreateProjectConfig,
        HarveySearchProjectConfig,
        HarveyDeleteFileConfig,
        HarveyDeleteProjectConfig,
        HarveyGetClientMattersConfig,
        HarveyUpsertClientsConfig,
        HarveyDeleteClientsConfig,
        HarveyUpsertMattersConfig,
        HarveyDeleteMattersConfig,
        HarveyCreateIntakeRequestConfig,
        HarveyListIntakeRequestsConfig,
        HarveyGetIntakeRequestConfig,
        HarveyUpdateIntakeRequestConfig,
        HarveyListIntakeCommentsConfig,
    ],
    Field(discriminator="operation"),
]


class HarveyFullConfig(NodeConfig[HarveyConfig, HarveyTokenCredential]):
    pass


ROUTES = {
    "list_projects": {
        "method": "GET",
        "path": "/api/v1/vault/workspace/projects",
        "query": [
            "page",
            "per_page",
            "name",
            "is_knowledge_base",
            "created_after",
            "created_before",
            "sort_by",
            "sort_order",
        ],
        "csv": [],
        "body": [],
        "media": None,
        "success": [200],
    },
    "list_recycled_projects": {
        "method": "GET",
        "path": "/api/v1/vault/workspace/recycle_bin",
        "query": ["search_text", "client_matter_id"],
        "csv": [],
        "body": [],
        "media": None,
        "success": [200],
    },
    "get_project": {
        "method": "GET",
        "path": "/api/v1/vault/get_metadata/{project_id}",
        "query": [],
        "csv": [],
        "body": [],
        "media": None,
        "success": [201],
    },
    "get_review_table": {
        "method": "GET",
        "path": "/api/v1/vault/review_table/{review_table_id}",
        "query": [],
        "csv": [],
        "body": [],
        "media": None,
        "success": [200],
    },
    "get_files": {
        "method": "GET",
        "path": "/api/v1/vault/get_files",
        "query": ["file_ids"],
        "csv": ["file_ids"],
        "body": [],
        "media": None,
        "success": [200],
    },
    "get_review_table_row": {
        "method": "GET",
        "path": "/api/v1/vault/get_row/{review_table_id}/{file_id}",
        "query": [],
        "csv": [],
        "body": [],
        "media": None,
        "success": [200],
    },
    "add_review_table_row": {
        "method": "POST",
        "path": "/api/v1/vault/add_row/{review_table_id}",
        "query": [],
        "csv": [],
        "body": ["file_ids", "group_name"],
        "media": "application/json",
        "success": [200],
    },
    "list_project_files": {
        "method": "GET",
        "path": "/api/v1/vault/projects/{project_id}/files",
        "query": [
            "cursor",
            "limit",
            "name",
            "content_type",
            "processing_status",
            "uploaded_after",
            "uploaded_before",
            "sort_by",
            "sort_order",
        ],
        "csv": [],
        "body": [],
        "media": None,
        "success": [200],
    },
    "list_project_users": {
        "method": "GET",
        "path": "/api/v1/vault/projects/{project_id}/users",
        "query": [],
        "csv": [],
        "body": [],
        "media": None,
        "success": [200],
    },
    "create_project": {
        "method": "POST",
        "path": "/api/v1/vault/create_project",
        "query": [],
        "csv": [],
        "body": ["name", "client_matter_id"],
        "media": "multipart/form-data",
        "success": [200],
    },
    "search_project": {
        "method": "POST",
        "path": "/api/v1/vault/semantic_search",
        "query": [],
        "csv": [],
        "body": ["project_id", "query", "include_file_names"],
        "media": "application/json",
        "success": [200],
    },
    "delete_file": {
        "method": "DELETE",
        "path": "/api/v1/vault/delete_file/{file_id}",
        "query": [],
        "csv": [],
        "body": [],
        "media": None,
        "success": [200],
    },
    "delete_project": {
        "method": "DELETE",
        "path": "/api/v1/vault/delete_project/{project_id}",
        "query": [],
        "csv": [],
        "body": [],
        "media": None,
        "success": [200],
    },
    "get_client_matters": {
        "method": "GET",
        "path": "/api/v1/client_matters",
        "query": [],
        "csv": [],
        "body": [],
        "media": None,
        "success": [200],
    },
    "upsert_clients": {
        "method": "POST",
        "path": "/api/v2/clients",
        "query": [],
        "csv": [],
        "body": ["clients"],
        "media": "application/json",
        "success": [200],
    },
    "delete_clients": {
        "method": "DELETE",
        "path": "/api/v2/clients",
        "query": [],
        "csv": [],
        "body": ["client_ids"],
        "media": "application/json",
        "success": [200],
    },
    "upsert_matters": {
        "method": "POST",
        "path": "/api/v2/matters",
        "query": [],
        "csv": [],
        "body": ["matters"],
        "media": "application/json",
        "success": [200],
    },
    "delete_matters": {
        "method": "DELETE",
        "path": "/api/v2/matters",
        "query": [],
        "csv": [],
        "body": ["matters"],
        "media": "application/json",
        "success": [200],
    },
    "create_intake_request": {
        "method": "POST",
        "path": "/api/v1/intake/requests",
        "query": [],
        "csv": [],
        "body": ["idempotency_key", "title", "description"],
        "media": "multipart/form-data",
        "success": [200, 201],
    },
    "list_intake_requests": {
        "method": "GET",
        "path": "/api/v1/intake/requests",
        "query": ["limit", "cursor", "status", "created_after", "created_before"],
        "csv": [],
        "body": [],
        "media": None,
        "success": [200],
    },
    "get_intake_request": {
        "method": "GET",
        "path": "/api/v1/intake/requests/{request_id}",
        "query": [],
        "csv": [],
        "body": [],
        "media": None,
        "success": [200],
    },
    "update_intake_request": {
        "method": "PATCH",
        "path": "/api/v1/intake/requests/{request_id}",
        "query": [],
        "csv": [],
        "body": ["title", "description", "status", "due_at"],
        "media": "application/json",
        "success": [200],
    },
    "list_intake_comments": {
        "method": "GET",
        "path": "/api/v1/intake/requests/{request_id}/comments",
        "query": ["limit", "cursor"],
        "csv": [],
        "body": [],
        "media": None,
        "success": [200],
    },
}


class HarveyNode(WorkflowNode):
    integration_type = "automation-harvey"
    connection_evidence = ConnectionEvidence(
        operation="list_projects", noun="Harvey Vault projects"
    )

    @classmethod
    def get_config_model(cls):
        return HarveyFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Harvey API token")
        config = self.config.config
        route = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_unset=True)
        path = route["path"]
        for name in type(config).model_fields:
            if "{" + name + "}" in path:
                path = path.replace(
                    "{" + name + "}", quote(str(getattr(config, name)), safe="")
                )
        query_values = config.model_dump(mode="json")
        params = []
        for name in route["query"]:
            value = query_values[name]
            if value is None:
                continue
            if name in route["csv"]:
                value = ",".join(str(item) for item in value)
            for item in value if isinstance(value, list) else [value]:
                params.append(
                    (name, str(item).lower() if isinstance(item, bool) else str(item))
                )
        body = {name: values[name] for name in route["body"] if name in values}
        kwargs = {
            "params": params,
            "headers": {
                "Authorization": "Bearer " + self.config.credentials.api_token,
                "Accept": "application/json",
            },
        }
        if route["media"] == "application/json":
            kwargs["json"] = body
        elif route["media"] == "multipart/form-data":
            kwargs["files"] = [
                (
                    name,
                    (
                        None,
                        str(value).lower() if isinstance(value, bool) else str(value),
                    ),
                )
                for name, value in body.items()
                if value is not None
            ]
        async with guarded_async_client(
            timeout=60, follow_redirects=False, trust_env=False
        ) as client:
            response = await client.request(
                route["method"], "https://api.harvey.ai" + path, **kwargs
            )
        if response.status_code not in route["success"]:
            # Preserve provider rejections for connection verification. Never echo the token.
            message = response.text.replace(
                self.config.credentials.api_token, "[redacted]"
            )[:2000]
            raise ValueError(f"Harvey HTTP {response.status_code}: {message}")
        data = response.json() if response.content else None
        if data is not None and not isinstance(data, (dict, list)):
            raise ValueError("Harvey returned an unexpected JSON response")
        partial = isinstance(data, dict) and bool(
            data.get("errors") or data.get("failed")
        )
        projects = []
        if config.operation == "list_projects" and isinstance(data, dict):
            content = data.get("response", {}).get("content", {})
            if isinstance(content, dict):
                projects = content.get("projects", [])
        return {
            **({"items": projects} if config.operation == "list_projects" else {}),
            "status": "success",
            "operation": config.operation,
            "http_status": response.status_code,
            "data": data,
            "partial_failure": partial,
        }
