"""BugHerd's fixed API v2 read transport and safe response models.

Credentials use the standard non-rotating API-key path on staging.
Only documented metadata leaves are returned; capability URLs and keys are omitted.
"""
import json
from base64 import b64encode
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Annotated, Literal, Union

import httpx
from nodes.core.base import NodeConfig, WorkflowNode, runtime_config_view
from nodes.core.connection_evidence import ConnectionEvidence
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    TypeAdapter,
    field_validator,
    model_serializer,
    model_validator,
)
from utils.ssrf import guarded_async_client

FAMILY = "bugherd_api_key"
BASE_URL = "https://www.bugherd.com/api_v2"
MAX_BYTES = 8 * 1024 * 1024


class _Projection(BaseModel):
    model_config = ConfigDict(extra="ignore")


class User(_Projection):
    id: StrictInt = Field(ge=1)
    display_name: StrictStr | None = None
    email: StrictStr | None = None


class Organization(_Projection):
    id: StrictInt = Field(ge=1)
    name: StrictStr = Field(min_length=1, max_length=1000)


class Column(_Projection):
    id: StrictInt = Field(ge=1)
    project_id: StrictInt = Field(ge=1)
    name: StrictStr | None = None
    position: StrictInt | None = None
    tasks_count: StrictInt | None = None
    created_at: StrictStr | None = None
    updated_at: StrictStr | None = None


class Project(_Projection):
    id: StrictInt = Field(ge=1)
    name: StrictStr = Field(min_length=1, max_length=1000)
    created_at: StrictStr | None = None
    tasks: StrictBool | None = None
    is_active: StrictBool | None = None
    is_public: StrictBool | None = None
    has_custom_columns: StrictBool | None = None
    owner_name: StrictStr | None = None
    members: list[User] | None = Field(None, max_length=1000)
    guests: list[User] | None = Field(None, max_length=1000)
    columns: list[Column] | None = Field(None, max_length=1000)


class Task(_Projection):
    id: StrictInt = Field(ge=1)
    project_id: StrictInt = Field(ge=1)
    local_task_id: StrictInt | None = None
    title: StrictStr | None = None
    description: StrictStr | None = None
    status: StrictStr | None = None
    status_id: StrictInt | None = None
    priority: StrictStr | None = None
    priority_id: StrictInt | None = None
    created_at: StrictStr | None = None
    updated_at: StrictStr | None = None
    closed_at: StrictStr | None = None
    deleted_at: StrictStr | None = None
    due_at: StrictStr | None = None
    tag_names: list[StrictStr] | None = Field(None, max_length=256)
    external_id: StrictStr | None = None
    requester_id: StrictInt | None = None
    assigned_to_id: StrictInt | None = None
    column_id: StrictInt | None = None
    assignee_ids: list[StrictInt] | None = Field(None, max_length=1000)
    assigned_to: User | None = None
    requester: User | None = None
    updater: User | None = None
    assignees: list[User] | None = Field(None, max_length=1000)
    project_name: StrictStr | None = None


class Comment(_Projection):
    id: StrictInt = Field(ge=1)
    text: StrictStr | None = None
    created_at: StrictStr | None = None
    user_id: StrictInt | None = None
    is_private: StrictBool | None = None


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]").replace(
            b64encode(f"{key}:x".encode()).decode(), "[redacted]"
        )
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {name: _redact(item, key) for name, item in value.items()}
    return value


def projected(model, value, scope, *, project_id=None, resource_id=None):
    try:
        result = model.model_validate(value).model_dump(mode="json", exclude_unset=True)
    except Exception:
        raise ValueError("BugHerd returned malformed metadata.") from None
    if resource_id is not None and result["id"] != resource_id:
        raise ValueError("BugHerd returned a different resource than requested.")
    if project_id is not None and result.get("project_id") != project_id:
        raise ValueError("BugHerd returned metadata outside the requested project.")
    if model is Organization and (
        not result["name"].strip() or scope.credential["api_key"] in result["name"]
    ):
        raise ValueError("BugHerd returned an invalid organization witness.")
    if model is Project:
        for column in result.get("columns") or []:
            if column["project_id"] != result["id"]:
                raise ValueError("BugHerd returned a column outside its project.")
    return _redact(result, scope.credential["api_key"])


def single(payload, envelope, model, scope, **bindings):
    if not isinstance(payload, dict) or envelope not in payload:
        raise ValueError("BugHerd returned an invalid response envelope.")
    return projected(model, payload[envelope], scope, **bindings)


def page(payload, envelope, model, scope, *, page_number=None, project_id=None):
    if not isinstance(payload, dict) or not isinstance(payload.get(envelope), list):
        raise ValueError("BugHerd returned an invalid list envelope.")
    rows = payload[envelope]
    if len(rows) > 100:
        raise ValueError("BugHerd list exceeds its documented 100-record bound.")
    total = None
    if "meta" in payload:
        meta = payload["meta"]
        if not isinstance(meta, dict):
            raise ValueError("BugHerd returned malformed pagination metadata.")
        if "count" in meta:
            total = meta["count"]
            if type(total) is not int or total < len(rows):
                raise ValueError("BugHerd returned an invalid record count.")
    data = [projected(model, row, scope, project_id=project_id) for row in rows]
    if len({row["id"] for row in data}) != len(data):
        raise ValueError("BugHerd returned duplicate records within one page.")
    # Empty pages are the documented terminator; a short nonempty page is not.
    paged = page_number is not None
    return {
        "data": data,
        "returned_count": len(data),
        "total_count": total,
        "page": page_number,
        "next_page": page_number + 1 if paged and data else None,
        "pagination_supported": paged,
        "complete": not data
        if paged
        else (total == len(data) if total is not None else None),
        "truncated": False
        if paged
        else (total > len(data) if total is not None else None),
    }


@dataclass
class RequestScope:
    credential: dict


def prepare(credential, validate):
    return RequestScope(validate(credential))


def retry_after(value):
    try:
        seconds = (
            int(value)
            if value.isdigit()
            else int(
                (
                    parsedate_to_datetime(value) - datetime.now(timezone.utc)
                ).total_seconds()
            )
        )
        return min(86400, max(0, seconds))
    except (ValueError, TypeError, AttributeError, OverflowError):
        return None


async def request(scope, path, params=None):
    # Paths come only from the native operation dispatch below, never caller URLs.
    if any(
        scope.credential["api_key"] in str(value) for value in (params or {}).values()
    ):
        raise ValueError("BugHerd API keys must not be included in query filters.")
    auth = b64encode(f"{scope.credential['api_key']}:x".encode("ascii")).decode("ascii")
    try:
        async with guarded_async_client(
            timeout=30, follow_redirects=False, trust_env=False
        ) as client:
            async with client.stream(
                "GET",
                BASE_URL + path,
                params=params or {},
                headers={
                    "Authorization": f"Basic {auth}",
                    "Accept": "application/json",
                },
            ) as response:
                if response.status_code in (401, 403):
                    raise ValueError(
                        "BugHerd authentication failed or access denied (401/403)."
                    )
                if response.status_code == 429:
                    delay = retry_after(response.headers.get("Retry-After", ""))
                    raise ValueError(
                        "BugHerd rate limit exceeded (429)."
                        + (
                            f" Retry after {delay} seconds."
                            if delay is not None
                            else ""
                        )
                    )
                if response.status_code != 200:
                    raise ValueError(
                        f"BugHerd read failed (HTTP {response.status_code})."
                    )
                media = (
                    response.headers.get("content-type", "")
                    .split(";", 1)[0]
                    .strip()
                    .lower()
                )
                if media != "application/json" and not media.endswith("+json"):
                    raise ValueError("BugHerd returned an unsupported response format.")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_BYTES:
                        raise ValueError(
                            "BugHerd response exceeds the native 8 MiB bound."
                        )
    except httpx.HTTPError:
        raise ValueError(
            "BugHerd read transport failed; retry explicitly after checking access."
        ) from None
    try:
        payload = json.loads(
            raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError())
        )
    except (ValueError, UnicodeError):
        raise ValueError("BugHerd returned malformed JSON.") from None
    if (
        not isinstance(payload, dict)
        or payload.get("error")
        or payload.get("errors")
        or payload.get("success") is False
    ):
        raise ValueError("BugHerd returned an unsuccessful response envelope.")
    return payload


async def execute_read(scope, config):
    org = single(
        await request(scope, "/organization.json"), "organization", Organization, scope
    )
    operation = config.operation
    result = {"organization": org}
    if operation == "get_organization":
        result["data"] = org
    elif operation == "list_projects":
        endpoint = "/projects/active.json" if config.active_only else "/projects.json"
        result.update(
            page(
                await request(scope, endpoint, {"page": config.page}),
                "projects",
                Project,
                scope,
                page_number=config.page,
            )
        )
    elif operation == "list_users":
        endpoint = {
            "all": "/users.json",
            "members": "/users/members.json",
            "clients": "/users/guests.json",
        }[config.kind]
        result.update(
            page(
                await request(scope, endpoint, {"page": config.page}),
                "users",
                User,
                scope,
                page_number=config.page,
            )
        )
    else:
        project_id = config.project_id
        prefix = f"/projects/{project_id}"
        project = single(
            await request(scope, prefix + ".json"),
            "project",
            Project,
            scope,
            resource_id=project_id,
        )
        result["project_id"] = project_id
        if operation == "get_project":
            result["data"] = project
        elif operation == "list_tasks":
            suffix = (
                "/tasks.json" if config.view == "all" else f"/tasks/{config.view}.json"
            )
            params = {"page": config.page}
            if config.view == "all":
                params.update(
                    config.model_dump(
                        mode="json",
                        include={
                            "status",
                            "priority",
                            "tag",
                            "assigned_to_id",
                            "external_id",
                            "created_since",
                            "updated_since",
                        },
                        exclude_none=True,
                    )
                )
            result.update(
                page(
                    await request(scope, prefix + suffix, params),
                    "tasks",
                    Task,
                    scope,
                    page_number=config.page,
                    project_id=project_id,
                )
            )
        elif operation in ("get_task", "list_comments"):
            task = single(
                await request(scope, prefix + f"/tasks/{config.task_id}.json"),
                "task",
                Task,
                scope,
                project_id=project_id,
                resource_id=config.task_id,
            )
            result["task_id"] = config.task_id
            if operation == "get_task":
                result["data"] = task
            else:
                # This endpoint has no documented page parameter, unlike tasks.
                result.update(
                    page(
                        await request(
                            scope, prefix + f"/tasks/{config.task_id}/comments.json"
                        ),
                        "comments",
                        Comment,
                        scope,
                    )
                )
        elif operation == "list_columns":
            result.update(
                page(
                    await request(scope, prefix + "/columns.json"),
                    "columns",
                    Column,
                    scope,
                    project_id=project_id,
                )
            )
        elif operation == "get_column":
            result["data"] = single(
                await request(scope, prefix + f"/columns/{config.column_id}.json"),
                "column",
                Column,
                scope,
                project_id=project_id,
                resource_id=config.column_id,
            )
        else:
            raise ValueError("Unsupported BugHerd read operation.")
    return result


class BugHerdApiKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="BugHerd API Key",
        extra="ignore",
        json_schema_extra={
            "x-credential-url": "https://www.bugherd.com",
            "x-credential-instructions": "Use your existing organization API key from Settings > General. No password, OAuth app or key issuance is needed here.",
        },
    )
    credential_type: Literal["bugherd_api_key"] = Field(
        "bugherd_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: StrictStr = Field(
        ..., title="API Key", json_schema_extra={"ui:widget": "password"}
    )

    @field_validator("api_key")
    @classmethod
    def validate_key(cls, value):
        if not 1 <= len(value) <= 512 or any(
            ord(c) < 33 or ord(c) > 126 or c == ":" for c in value
        ):
            raise ValueError("A header-safe BugHerd API key is required.")
        return value

    @model_serializer(mode="wrap")
    def serialize_with_type(self, handler):
        return {**handler(self), "credential_type": FAMILY}


class _Config(BaseModel):
    model_config = ConfigDict(extra="ignore")

    @field_validator(
        "project_id",
        "task_id",
        "column_id",
        "assigned_to_id",
        check_fields=False,
        mode="before",
    )
    @classmethod
    def canonical_resource_id(cls, value):
        if (
            isinstance(value, str)
            and value.isascii()
            and value.isdigit()
            and str(int(value)) == value
        ):
            return int(value)
        return value


def _project():
    return Field(
        ...,
        ge=1,
        title="Project",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "project_id",
                "searchable": True,
                "allow_custom": True,
                "placeholder": "Select a project",
            }
        },
    )


class GetOrganization(_Config):
    operation: Literal["get_organization"] = Field(
        "get_organization", json_schema_extra={"const": "get_organization"}
    )


class ListProjects(_Config):
    operation: Literal["list_projects"] = Field(
        "list_projects", json_schema_extra={"const": "list_projects"}
    )
    active_only: StrictBool = False
    page: StrictInt = Field(
        1,
        ge=1,
        le=1000000,
        description="One page of at most 100 records. Continue until an empty page.",
    )


class GetProject(_Config):
    operation: Literal["get_project"] = Field(
        "get_project", json_schema_extra={"const": "get_project"}
    )
    project_id: StrictInt = _project()


class ListUsers(_Config):
    operation: Literal["list_users"] = Field(
        "list_users", json_schema_extra={"const": "list_users"}
    )
    kind: Literal["all", "members", "clients"] = "all"
    page: StrictInt = Field(1, ge=1, le=1000000)


class ListTasks(_Config):
    operation: Literal["list_tasks"] = Field(
        "list_tasks", json_schema_extra={"const": "list_tasks"}
    )
    project_id: StrictInt = _project()
    view: Literal["all", "feedback", "archive", "taskboard"] = "all"
    page: StrictInt = Field(1, ge=1, le=1000000)
    status: StrictStr | None = Field(
        None, max_length=200, description="Includes custom column names."
    )
    priority: Literal[
        "not set", "critical", "important", "normal", "minor"
    ] | None = None
    tag: StrictStr | None = Field(None, max_length=200)
    assigned_to_id: StrictInt | None = Field(None, ge=1)
    external_id: StrictStr | None = Field(None, max_length=500)
    created_since: StrictStr | None = None
    updated_since: StrictStr | None = None

    @field_validator("created_since", "updated_since")
    @classmethod
    def timestamp(cls, value):
        if value is not None:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValueError(
                    "Use an ISO 8601 timestamp with its timezone."
                ) from None
        return value

    @model_validator(mode="after")
    def filters_match_view(self):
        if self.view != "all" and any(
            getattr(self, field) is not None
            for field in (
                "status",
                "priority",
                "tag",
                "assigned_to_id",
                "external_id",
                "created_since",
                "updated_since",
            )
        ):
            raise ValueError("Task filters are documented only for the all-tasks view.")
        return self


class GetTask(_Config):
    operation: Literal["get_task"] = Field(
        "get_task", json_schema_extra={"const": "get_task"}
    )
    project_id: StrictInt = _project()
    task_id: StrictInt = Field(
        ...,
        ge=1,
        title="Task",
        description="Globally unique task ID, not the local task number.",
        json_schema_extra={
            "x-dynamic-options": {
                "field_name": "task_id",
                "depends_on": "project_id",
                "searchable": True,
                "allow_custom": True,
            }
        },
    )


class ListComments(GetTask):
    operation: Literal["list_comments"] = Field(
        "list_comments", json_schema_extra={"const": "list_comments"}
    )


class ListColumns(_Config):
    operation: Literal["list_columns"] = Field(
        "list_columns", json_schema_extra={"const": "list_columns"}
    )
    project_id: StrictInt = _project()


class GetColumn(ListColumns):
    operation: Literal["get_column"] = Field(
        "get_column", json_schema_extra={"const": "get_column"}
    )
    column_id: StrictInt = Field(..., ge=1)


BugHerdConfig = Annotated[
    Union[
        GetOrganization,
        ListProjects,
        GetProject,
        ListUsers,
        ListTasks,
        GetTask,
        ListComments,
        ListColumns,
        GetColumn,
    ],
    Field(discriminator="operation"),
]


class BugHerdFullConfig(NodeConfig[BugHerdConfig, BugHerdApiKeyCredential]):
    pass


class BugHerdNode(WorkflowNode):
    integration_type = "automation-bugherd"
    agent_tool_provider = True
    connection_evidence = ConnectionEvidence(
        noun="organization", identity_operation="get_organization"
    )

    @classmethod
    def get_config_model(cls):
        return BugHerdFullConfig

    @classmethod
    def validate_credential(cls, data):
        if not isinstance(data, dict) or data.get("credential_type", FAMILY) != FAMILY:
            raise ValueError("A BugHerd API-key credential is required.")
        try:
            return BugHerdApiKeyCredential.model_validate(data).model_dump(mode="json")
        except Exception:
            raise ValueError("BugHerd credential shape is invalid.") from None

    @classmethod
    def parse_config(cls, config_data):
        data = config_data
        if isinstance(data, dict) and data.get("credentials") is not None:
            cls.validate_credential(data["credentials"])
        try:
            return TypeAdapter(BugHerdFullConfig).validate_python(
                runtime_config_view(data, BugHerdFullConfig)
            )
        except Exception:
            raise ValueError("BugHerd configuration is invalid.") from None

    @classmethod
    async def load_field_options(
        cls, field_name, credential_data, context=None, page_token=None, search=None
    ):
        context = dict(context or {})
        if field_name not in ("project_id", "task_id"):
            raise ValueError("Unsupported BugHerd option field.")
        if page_token is not None and (
            not isinstance(page_token, str)
            or not page_token.isascii()
            or not page_token.isdigit()
            or str(int(page_token)) != page_token
        ):
            raise ValueError(
                "BugHerd page token must be a canonical positive page number."
            )
        number = int(page_token) if page_token is not None else 1
        config_data = {
            "operation": "list_projects"
            if field_name == "project_id"
            else "list_tasks",
            "page": number,
        }
        if field_name == "task_id":
            parent = context.get("project_id")
            if (
                isinstance(parent, str)
                and parent.isascii()
                and parent.isdigit()
                and str(int(parent)) == parent
            ):
                parent = int(parent)
            config_data["project_id"] = parent
        try:
            config = TypeAdapter(BugHerdConfig).validate_python(config_data)
        except Exception:
            raise ValueError(
                "BugHerd options require a valid page and explicit project parent."
            ) from None
        scope = prepare(credential_data, cls.validate_credential)
        result = await execute_read(scope, config)
        query = search.strip().casefold() if isinstance(search, str) else ""
        options = []
        for row in result["data"]:
            label = row.get("name") or row.get("title") or str(row["id"])
            if not query or query in label.casefold() or query in str(row["id"]):
                options.append(
                    {
                        "value": str(row["id"]),
                        "label": label,
                        "metadata": {
                            "organization_id": result["organization"]["id"],
                            **(
                                {"project_id": row["project_id"]}
                                if field_name == "task_id"
                                else {}
                            ),
                        },
                    }
                )
        return {
            "options": options,
            "next_page_token": str(result["next_page"])
            if result["next_page"] is not None
            else None,
        }

    async def execute(self, inputs):
        if not isinstance(self.config, BugHerdFullConfig):
            raise ValueError("BugHerd configuration is required.")
        if not self.config.credentials:
            raise ValueError("Connect a BugHerd API key in the credentials tab.")
        scope = prepare(
            self.config.credentials.model_dump(mode="json"), self.validate_credential
        )
        return await execute_read(scope, self.config.config)
