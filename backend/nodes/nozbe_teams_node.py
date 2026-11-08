"""Nozbe Teams REST API. Contract: https://api4.nozbe.com/v1/api/openapi.yaml.

Paste the token created in the Nozbe app's API tokens screen, without a prefix.
Pagination is explicit: list operations return one page and a next offset hint.
"""
from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE = "https://api4.nozbe.com/v1/api"
ID = Annotated[str, Field(min_length=16, max_length=16, pattern=r"^[a-zA-Z0-9]{16}$")]
Name = Annotated[str, Field(min_length=1, max_length=255)]
ProjectID = Annotated[str, Field(max_length=16, pattern=r"^([a-zA-Z0-9]{16}|task_me)?$")]

class NozbeTeamsTokenCredential(BaseModel):
    model_config = ConfigDict(title="Nozbe Teams API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://files.nozbe.com/nt_api.pdf",
        "x-credential-instructions": "In Nozbe, open API tokens and create a token for your space, or a global token for all spaces. Paste it here without an Authorization prefix."})
    credential_type: Literal["nozbe_teams_api_token"] = Field("nozbe_teams_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, repr=False, title="API Token",
        description="The API token copied from Nozbe's API tokens screen.", json_schema_extra={"ui:widget": "password"})

class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class _Page(_Config):
    limit: int = Field(100, ge=1, le=10000, title="Page Size")
    offset: int = Field(0, ge=0, title="Offset", description="Number of records to skip; advance by the page size.")
    sort_by: str | None = Field(None, pattern=r"^[-a-z_,]*$", title="Sort By", description="Comma-separated fields, with - for descending order.")

class ListTeams(_Page):
    operation: Literal["list_teams"] = Field("list_teams", title="List Teams", json_schema_extra={"ui:hidden": True})

class GetTeam(_Config):
    operation: Literal["get_team"] = Field("get_team", title="Get Team", json_schema_extra={"ui:hidden": True})
    team_id: ID

class ListProjects(_Page):
    operation: Literal["list_projects"] = Field("list_projects", title="List Projects", json_schema_extra={"ui:hidden": True})
    team_id: ID | None = None

class GetProject(_Config):
    operation: Literal["get_project"] = Field("get_project", title="Get Project", json_schema_extra={"ui:hidden": True})
    project_id: ID

class ListTasks(_Page):
    operation: Literal["list_tasks"] = Field("list_tasks", title="List Tasks", json_schema_extra={"ui:hidden": True})
    project_id: ID | None = None

class GetTask(_Config):
    operation: Literal["get_task"] = Field("get_task", title="Get Task", json_schema_extra={"ui:hidden": True})
    task_id: ID

class CreateTask(_Config):
    operation: Literal["create_task"] = Field("create_task", title="Create Task", json_schema_extra={"ui:hidden": True})
    name: Name
    project_id: ProjectID = None
    responsible_id: ID | Literal["author"] | None = None
    due_at: int | None = None
    is_all_day: bool = None

class UpdateTask(_Config):
    operation: Literal["update_task"] = Field("update_task", title="Update Task", json_schema_extra={"ui:hidden": True})
    task_id: ID
    name: Name = None
    project_id: ProjectID = None
    responsible_id: ID | Literal["author"] | None = None
    due_at: int | None = None
    ended_at: int | None = None
    is_all_day: bool = None

class DeleteTask(_Config):
    operation: Literal["delete_task"] = Field("delete_task", title="Delete Task", json_schema_extra={"ui:hidden": True})
    task_id: ID

class ListComments(_Page):
    operation: Literal["list_comments"] = Field("list_comments", title="List Comments", json_schema_extra={"ui:hidden": True})
    task_id: ID | None = None

class GetComment(_Config):
    operation: Literal["get_comment"] = Field("get_comment", title="Get Comment", json_schema_extra={"ui:hidden": True})
    comment_id: ID

class CreateComment(_Config):
    operation: Literal["create_comment"] = Field("create_comment", title="Create Comment", json_schema_extra={"ui:hidden": True})
    task_id: ID
    body: str

class UpdateComment(_Config):
    operation: Literal["update_comment"] = Field("update_comment", title="Update Comment", json_schema_extra={"ui:hidden": True})
    comment_id: ID
    body: str
    is_pinned: bool | None = None

class DeleteComment(_Config):
    operation: Literal["delete_comment"] = Field("delete_comment", title="Delete Comment", json_schema_extra={"ui:hidden": True})
    comment_id: ID

class ListTags(_Page):
    operation: Literal["list_tags"] = Field("list_tags", title="List Tags", json_schema_extra={"ui:hidden": True})
    task_id: ID | None = None
    name: str | None = None

class GetTag(_Config):
    operation: Literal["get_tag"] = Field("get_tag", title="Get Tag", json_schema_extra={"ui:hidden": True})
    tag_id: ID

class CreateTag(_Config):
    operation: Literal["create_tag"] = Field("create_tag", title="Create Tag", json_schema_extra={"ui:hidden": True})
    name: Name
    team_id: ID | None = None

class UpdateTag(_Config):
    operation: Literal["update_tag"] = Field("update_tag", title="Update Tag", json_schema_extra={"ui:hidden": True})
    tag_id: ID
    name: Name

Operation = Annotated[Union[ListTeams, GetTeam, ListProjects, GetProject, ListTasks, GetTask, CreateTask, UpdateTask, DeleteTask, ListComments, GetComment, CreateComment, UpdateComment, DeleteComment, ListTags, GetTag, CreateTag, UpdateTag], Field(discriminator="operation")]

class NozbeTeamsConfig(NodeConfig[Operation, NozbeTeamsTokenCredential]):
    pass

ROUTES = {'list_teams': ('GET', '/teams'), 'get_team': ('GET', '/teams/{team_id}'), 'list_projects': ('GET', '/projects'), 'get_project': ('GET', '/projects/{project_id}'), 'list_tasks': ('GET', '/tasks'), 'get_task': ('GET', '/tasks/{task_id}'), 'create_task': ('POST', '/tasks'), 'update_task': ('PUT', '/tasks/{task_id}'), 'delete_task': ('DELETE', '/tasks/{task_id}'), 'list_comments': ('GET', '/comments'), 'get_comment': ('GET', '/comments/{comment_id}'), 'create_comment': ('POST', '/comments'), 'update_comment': ('PUT', '/comments/{comment_id}'), 'delete_comment': ('DELETE', '/comments/{comment_id}'), 'list_tags': ('GET', '/tags'), 'get_tag': ('GET', '/tags/{tag_id}'), 'create_tag': ('POST', '/tags'), 'update_tag': ('PUT', '/tags/{tag_id}')}

class NozbeTeamsNode(WorkflowNode):
    integration_type = "automation-nozbe-teams"
    connection_evidence = ConnectionEvidence(noun="Nozbe spaces", operation="list_teams")

    @classmethod
    def get_config_model(cls):
        return NozbeTeamsConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Nozbe Teams API token")
        cfg = self.config.config
        method, template = ROUTES[cfg.operation]
        values = cfg.model_dump(exclude_unset=True)
        values.pop("operation", None)
        path = template
        for key in tuple(values):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(values.pop(key), safe=""))
        params, body = None, None
        if method == "GET":
            if cfg.operation.startswith("list_"):
                values.update(limit=cfg.limit, offset=cfg.offset)
                if "sort_by" in values:
                    values["sortBy"] = values.pop("sort_by")
                params = {k: v for k, v in values.items() if v is not None}
        elif method in {"POST", "PUT"}:
            body = values
            if method == "PUT" and not body:
                raise ValueError("Supply at least one field to update")
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": self.config.credentials.api_token, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            return {"status": "error", "http_status": response.status_code,
                "error": response.text[:1000]}
        if method == "DELETE" and not response.content:
            return {"status": "success", "data": None}
        data = response.json()
        if cfg.operation.startswith("list_"):
            if not isinstance(data, list):
                raise ValueError("Nozbe returned an invalid list")
            return {"status": "success", "items": data,
                "next_offset": cfg.offset + cfg.limit if len(data) == cfg.limit else None}
        if not isinstance(data, dict):
            raise ValueError("Nozbe returned an invalid record")
        return {"status": "success", "data": data}
