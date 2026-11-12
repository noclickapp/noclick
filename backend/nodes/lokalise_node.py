"""Automate Lokalise's default-project API with a personal API token.

Each operation makes one documented request; pagination stays explicit so workflows
can inspect each page and provider write errors without silently retrying writes.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.lokalise.com/api2"


class LokaliseAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Lokalise API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.lokalise.com/reference/api-authentication",
            "x-credential-instructions": "In Lokalise, open your avatar > Profile settings > API tokens. Paste a personal API token. Choose read/write for writes; read-only tokens support reads. You need an admin role in each project you access. Listing your projects checks the connection, but does not verify write permissions.",
        })
    credential_type: Literal["lokalise_api_token"] = Field("lokalise_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, title="API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the token without the X-Api-Token header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page number; pagination is explicit, one page per run.")
    limit: int = Field(100, ge=1, le=500)


class _Project(_Input):
    project_id: str = Field(..., min_length=1, max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
        description="Default-project ID. Branch-qualified project IDs are not supported.")


class _ProjectPage(_Project, _Page):
    pass


class ListProjects(_Page):
    """List projects available to the token owner."""
    operation: Literal["list_projects"] = "list_projects"
    filter_names: str | None = None
    filter_team_id: int | None = Field(None, ge=1)


class GetProject(_Project):
    """Retrieve a project's settings and statistics."""
    operation: Literal["get_project"] = "get_project"


class Language(_Input):
    lang_iso: str = Field(..., min_length=1)
    custom_iso: str | None = None


class CreateProject(_Input):
    """Create a project in your current or chosen team."""
    operation: Literal["create_project"] = "create_project"
    name: str = Field(..., min_length=1)
    description: str | None = None
    team_id: int | None = Field(None, ge=1)
    languages: list[Language] | None = Field(None, min_length=1)
    base_lang_iso: str | None = None

    @model_validator(mode="after")
    def base_language(self):
        if self.base_lang_iso is not None and (not self.languages or self.base_lang_iso not in {
            lang.custom_iso or lang.lang_iso for lang in self.languages
        }):
            raise ValueError("The base language must be included in languages")
        return self


class UpdateProject(_Project):
    """Change project name and optional description."""
    operation: Literal["update_project"] = "update_project"
    name: str = Field(..., min_length=1)
    description: str | None = None


class ListKeys(_ProjectPage):
    """List and filter project keys; returns one page."""
    operation: Literal["list_keys"] = "list_keys"
    filter_keys: str | None = None
    filter_tags: str | None = None
    filter_key_ids: str | None = None


class KeyTranslation(_Input):
    language_iso: str = Field(..., min_length=1)
    translation: str


class Key(_Input):
    key_name: str = Field(..., min_length=1)
    platforms: list[Literal["android", "ios", "other", "web"]] = Field(..., min_length=1)
    description: str | None = None
    tags: list[str] | None = None
    translations: list[KeyTranslation] | None = None


class CreateKeys(_Project):
    """Create nonplural keys with optional translations and tags."""
    operation: Literal["create_keys"] = "create_keys"
    keys: list[Key] = Field(..., min_length=1, max_length=500)
    use_automations: bool | None = None


class _Key(_Project):
    key_id: int = Field(..., ge=1)


class GetKey(_Key):
    """Retrieve a key and its translations."""
    operation: Literal["get_key"] = "get_key"


class UpdateKey(_Key):
    """Update key metadata, tags, platforms or archive state."""
    operation: Literal["update_key"] = "update_key"
    key_name: str | None = Field(None, min_length=1)
    description: str | None = None
    platforms: list[Literal["android", "ios", "other", "web"]] | None = Field(None, min_length=1)
    tags: list[str] | None = None
    merge_tags: bool | None = None
    is_hidden: bool | None = None
    is_archived: bool | None = None

    @model_validator(mode="after")
    def changed_fields(self):
        if not self.model_dump(exclude_none=True, exclude={"operation", "project_id", "key_id"}):
            raise ValueError("Provide at least one key field to update")
        return self


class DeleteKey(_Key):
    """Delete one key and its translations permanently."""
    operation: Literal["delete_key"] = "delete_key"


class ListLanguages(_ProjectPage):
    """List the project's languages."""
    operation: Literal["list_languages"] = "list_languages"


class CreateLanguages(_Project):
    """Add languages to a project."""
    operation: Literal["create_languages"] = "create_languages"
    languages: list[Language] = Field(..., min_length=1)


class ListTranslations(_ProjectPage):
    """List translations, optionally restricted to a language or task."""
    operation: Literal["list_translations"] = "list_translations"
    filter_lang_id: int | None = Field(None, ge=1)
    filter_active_task_id: int | None = Field(None, ge=1)


class _Translation(_Project):
    translation_id: int = Field(..., ge=1)


class GetTranslation(_Translation):
    """Retrieve one translation."""
    operation: Literal["get_translation"] = "get_translation"


class UpdateTranslation(_Translation):
    """Update a nonplural translation and its review flags."""
    operation: Literal["update_translation"] = "update_translation"
    translation: str
    is_unverified: bool | None = None
    is_reviewed: bool | None = None
    custom_translation_status_ids: list[str] | None = None


class ListTasks(_ProjectPage):
    """List project translation tasks."""
    operation: Literal["list_tasks"] = "list_tasks"
    filter_title: str | None = None
    filter_statuses: str | None = None


class GetTask(_Project):
    """Retrieve task status, assignees and progress."""
    operation: Literal["get_task"] = "get_task"
    task_id: int = Field(..., ge=1)


class ListComments(_ProjectPage):
    """List comments across a project."""
    operation: Literal["list_comments"] = "list_comments"


class Comment(_Input):
    comment: str = Field(..., min_length=1)


class CreateComments(_Key):
    """Add one or more comments to a key."""
    operation: Literal["create_comments"] = "create_comments"
    comments: list[Comment] = Field(..., min_length=1)


class ListTeams(_Page):
    """List teams available to the token owner."""
    operation: Literal["list_teams"] = "list_teams"


# Lokalise's own MCP server: agents get its tools through a person's Lokalise sign-in.
LokaliseMcpCredential = mcp_credential("lokalise", "https://mcp.lokalise.com/mcp/project-management", app="Lokalise")
LokaliseCredential = Union[LokaliseAPITokenCredential, LokaliseMcpCredential]


LokaliseConfig = Annotated[Union[
    ListProjects, GetProject, CreateProject, UpdateProject,
    ListKeys, CreateKeys, GetKey, UpdateKey, DeleteKey,
    ListLanguages, CreateLanguages, ListTranslations, GetTranslation, UpdateTranslation,
    ListTasks, GetTask, ListComments, CreateComments, ListTeams,
], Field(discriminator="operation")]


class LokaliseNodeConfig(NodeConfig[LokaliseConfig, LokaliseCredential]):
    pass


# Fixed routes keep each operation tied to a single published contract operation.
ROUTES = {
    "list_projects": ("GET", "/projects", "projects"),
    "get_project": ("GET", "/projects/{project_id}", None),
    "create_project": ("POST", "/projects", None),
    "update_project": ("PUT", "/projects/{project_id}", None),
    "list_keys": ("GET", "/projects/{project_id}/keys", "keys"),
    "create_keys": ("POST", "/projects/{project_id}/keys", None),
    "get_key": ("GET", "/projects/{project_id}/keys/{key_id}", None),
    "update_key": ("PUT", "/projects/{project_id}/keys/{key_id}", None),
    "delete_key": ("DELETE", "/projects/{project_id}/keys/{key_id}", None),
    "list_languages": ("GET", "/projects/{project_id}/languages", "languages"),
    "create_languages": ("POST", "/projects/{project_id}/languages", None),
    "list_translations": ("GET", "/projects/{project_id}/translations", "translations"),
    "get_translation": ("GET", "/projects/{project_id}/translations/{translation_id}", None),
    "update_translation": ("PUT", "/projects/{project_id}/translations/{translation_id}", None),
    "list_tasks": ("GET", "/projects/{project_id}/tasks", "tasks"),
    "get_task": ("GET", "/projects/{project_id}/tasks/{task_id}", None),
    "list_comments": ("GET", "/projects/{project_id}/comments", "comments"),
    "create_comments": ("POST", "/projects/{project_id}/keys/{key_id}/comments", None),
    "list_teams": ("GET", "/teams", "teams"),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(key, token): _redact(item, token) for key, item in value.items()}
    return value


def _check_credential_family(config_data):
    credentials = config_data.get("credentials")
    if isinstance(credentials, dict) and credentials.get("credential_type", "lokalise_api_token") != "lokalise_api_token":
        raise ValueError("Connect a Lokalise API token")


class LokaliseNode(WorkflowNode):
    integration_type = "automation-lokalise"
    credential_provider_labels = {"lokalise": "Lokalise Account"}
    connection_evidence = ConnectionEvidence(noun="projects", operation="list_projects", label_keys=("name", "project_id"))

    @classmethod
    def get_config_model(cls):
        return LokaliseNodeConfig

    @classmethod
    def validate_config(cls, config_data):
        try:
            _check_credential_family(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    def parse_config(cls, config_data):
        _check_credential_family(config_data)
        return super().parse_config(config_data)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Lokalise API token")
        op = self.config.config
        token = self.config.credentials.api_token
        method, route, collection = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for key in tuple(values):
            if "{" + key + "}" in route:
                route = route.replace("{" + key + "}", str(values.pop(key)))
        kwargs = {"params": values} if method == "GET" else {"json": values} if method != "DELETE" else {}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + route,
                    headers={"X-Api-Token": token, "Accept": "application/json"}, **kwargs)
        except httpx.HTTPError:
            raise ValueError("Lokalise request did not complete; inspect the resource before retrying a write") from None
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Lokalise returned a non-JSON response") from None
        payload = _redact(payload, token)
        if not isinstance(payload, dict):
            raise ValueError("Lokalise returned an invalid response object")
        if not 200 <= response.status_code < 300 or payload.get("error") or payload.get("errors"):
            output = {"status": "error", "http_status": response.status_code,
                "error": payload.get("error") or payload.get("errors") or payload,
                "response": payload}
        else:
            data = payload
            if collection is not None:
                data = payload.get(collection)
                if not isinstance(data, list):
                    raise ValueError("Lokalise returned an invalid collection")
            output = {"status": "success", "http_status": response.status_code,
                "data": data, "response": payload}
            if isinstance(op, _Page):
                output["pagination"] = {"page": op.page, "limit": op.limit,
                    "total_count": response.headers.get("X-Pagination-Total-Count"),
                    "page_count": response.headers.get("X-Pagination-Page-Count"),
                    "next_page": op.page + 1 if len(data) == op.limit else None}
        await self.emit(output)
        return output
