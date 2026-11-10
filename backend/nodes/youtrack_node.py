"""YouTrack issues and collaboration, pinned to JetBrains' REST OpenAPI 2026.4.

Permanent-token auth: https://www.jetbrains.com/help/youtrack/devportal/authentication-with-permanent-token.html
Polling: https://www.jetbrains.com/help/youtrack/devportal/resource-api-issues.html
"""
import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client, normalize_https_origin


def _server_url(value: str) -> str:
    parts = urlsplit(value.strip())
    origin = normalize_https_origin(f"{parts.scheme}://{parts.netloc}", field_name="YouTrack URL")
    # Server installations can live under a context path, e.g. /youtrack.
    path = parts.path.rstrip("/")
    if parts.query or parts.fragment or any(x in path for x in ("..", "%", "\\")):
        raise ValueError("Use your YouTrack HTTPS installation URL without query or fragment")
    if path.endswith("/api"):
        path = path[:-4]
    return origin + path


class YouTrackTokenCredential(BaseModel):
    model_config = ConfigDict(title="YouTrack Permanent Token", json_schema_extra={
        "x-credential-type": "api_key",
        "x-credential-url": "https://www.jetbrains.com/help/youtrack/cloud/manage-permanent-token.html",
        "x-credential-instructions": "Enter your YouTrack installation URL and a permanent token from your profile's Account Security tab. Select the YouTrack service scope; your account permissions control which issues you can read and change.",
    })
    credential_type: Literal["youtrack_token"] = Field("youtrack_token", json_schema_extra={"ui:hidden": True})
    server_url: str = Field(..., title="YouTrack URL", description="Your cloud or self-hosted HTTPS installation URL, for example https://example.youtrack.cloud")
    api_token: str = Field(..., min_length=1, title="Permanent Token", json_schema_extra={"ui:widget": "password"})

    @field_validator("server_url")
    @classmethod
    def validate_server_url(cls, value):
        return _server_url(value)

    @field_validator("api_token")
    @classmethod
    def validate_token(cls, value):
        value = clean_secret(value, field_name="Permanent Token", key=True)
        if not value or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Paste the permanent token without spaces")
        return value


@dataclass(frozen=True)
class Operation:
    label: str
    category: str
    method: str
    path: str
    fields: str = ""
    required: tuple[str, ...] = ()
    body: tuple[str, ...] = ()
    paged: bool = False
    search: bool = False


ISSUE_FIELDS = "id,idReadable,summary,description,created,updated,project(id,name,shortName),reporter(id,login),updater(id,login)"
COMMENT_FIELDS = "id,text,created,updated,author(id,login)"
PROJECT_FIELDS = "id,name,shortName"
TAG_FIELDS = "id,name"
WORK_FIELDS = "id,text,date,duration(minutes,presentation),author(id,login)"
OPERATIONS = {
    "list_issues": Operation("Search Issues", "Issues", "GET", "/issues", ISSUE_FIELDS, paged=True, search=True),
    "get_issue": Operation("Get Issue", "Issues", "GET", "/issues/{issue_id}", ISSUE_FIELDS),
    "create_issue": Operation("Create Issue", "Issues", "POST", "/issues", ISSUE_FIELDS, ("summary", "project_id"), ("summary", "description", "project_id")),
    "update_issue": Operation("Update Issue", "Issues", "POST", "/issues/{issue_id}", ISSUE_FIELDS, ("summary",), ("summary", "description")),
    "delete_issue": Operation("Delete Issue", "Issues", "DELETE", "/issues/{issue_id}"),
    "apply_command": Operation("Apply Command", "Issues", "POST", "/commands", "query,issues(id,idReadable)", ("issue_id", "command"), ("command", "issue_id", "comment")),
    "list_comments": Operation("List Comments", "Comments", "GET", "/issues/{issue_id}/comments", COMMENT_FIELDS, paged=True),
    "get_comment": Operation("Get Comment", "Comments", "GET", "/issues/{issue_id}/comments/{comment_id}", COMMENT_FIELDS),
    "add_comment": Operation("Add Comment", "Comments", "POST", "/issues/{issue_id}/comments", COMMENT_FIELDS, ("text",), ("text",)),
    "update_comment": Operation("Update Comment", "Comments", "POST", "/issues/{issue_id}/comments/{comment_id}", COMMENT_FIELDS, ("text",), ("text",)),
    "delete_comment": Operation("Delete Comment", "Comments", "DELETE", "/issues/{issue_id}/comments/{comment_id}"),
    "list_projects": Operation("List Projects", "Projects", "GET", "/admin/projects", PROJECT_FIELDS, paged=True),
    "get_project": Operation("Get Project", "Projects", "GET", "/admin/projects/{project_id}", PROJECT_FIELDS),
    "list_tags": Operation("List Tags", "Tags", "GET", "/tags", TAG_FIELDS, paged=True, search=True),
    "create_tag": Operation("Create Tag", "Tags", "POST", "/tags", TAG_FIELDS, ("name",), ("name",)),
    "list_issue_tags": Operation("List Issue Tags", "Tags", "GET", "/issues/{issue_id}/tags", TAG_FIELDS, paged=True),
    "add_issue_tag": Operation("Add Issue Tag", "Tags", "POST", "/issues/{issue_id}/tags", TAG_FIELDS, ("tag_id",), ("tag_id",)),
    "remove_issue_tag": Operation("Remove Issue Tag", "Tags", "DELETE", "/issues/{issue_id}/tags/{tag_id}"),
    "list_work_items": Operation("List Time Entries", "Time Tracking", "GET", "/issues/{issue_id}/timeTracking/workItems", WORK_FIELDS, paged=True),
    "get_work_item": Operation("Get Time Entry", "Time Tracking", "GET", "/issues/{issue_id}/timeTracking/workItems/{work_item_id}", WORK_FIELDS),
    "get_current_user": Operation("Get Current User", "Account", "GET", "/users/me", "id,login,fullName,email"),
}


def _make_config(name, spec):
    names = set(spec.required + spec.body)
    names.update(part.split("}")[0] for part in spec.path.split("{")[1:])
    required = set(spec.required) | {part.split("}")[0] for part in spec.path.split("{")[1:]}
    fields = {}
    for field in sorted(names):
        extra = {}
        if field in {"description", "text", "comment"}:
            extra = {"ui:widget": "textarea"}
        fields[field] = (str if field in required else str | None, Field(... if field in required else None,
            title=field.replace("_", " ").title(), min_length=1 if field in required else None, json_schema_extra=extra))
    if name == "update_issue":
        fields["clear_description"] = (bool, Field(False, title="Clear Description", description="Remove the issue description. Overrides Description when enabled."))
    if spec.paged:
        fields.update(limit=(int, Field(100, ge=1, le=100, title="Page Size")), offset=(int, Field(0, ge=0, title="Offset")))
    if spec.search:
        fields["query"] = (str | None, Field(None, title="Search Query", description="YouTrack search syntax, for example for: me #Unresolved"))
    return create_model("YouTrack" + "".join(s.title() for s in name.split("_")) + "Config", __module__=__name__,
        operation=(Literal[name], Field(name, title=spec.label, json_schema_extra={"const": name, "ui:hidden": True,
            "x-category": spec.category, "x-display-name": spec.label, "x-is-trigger": False})), **fields)


CONFIG_MODELS = {name: _make_config(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class YouTrackOnIssueChangedConfig(PollTriggerConfigBase):
    operation: Literal["on_issue_changed"] = Field("on_issue_changed", title="On New or Updated Issue", json_schema_extra={
        "const": "on_issue_changed", "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
        "x-display-name": "On New or Updated Issue"})
    query: str | None = Field(None, title="Search Query", description="Optional YouTrack search query to scope the issues watched. Existing matching issues form the initial baseline.")


YouTrackConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (YouTrackOnIssueChangedConfig,)], Discriminator("operation")]


class YouTrackNodeConfig(NodeConfig[YouTrackConfig, YouTrackTokenCredential]):
    pass


class YouTrackNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-youtrack"
    connection_evidence = ConnectionEvidence(operation="list_projects", noun="projects", identity_operation="get_current_user", identity_keys=("fullName", "login", "email"))
    # This integration uses a user-created permanent token, not OAuth. The
    # YouTrack service scope and the user's permissions govern all operations.
    edit_examples = ["Create a YouTrack issue", "Search my unresolved YouTrack issues", "Add a comment to a YouTrack issue", "Apply a command to assign or resolve an issue", "Watch for new or updated YouTrack issues"]

    @classmethod
    def get_config_model(cls):
        return YouTrackNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None):
        async with guarded_async_client(timeout=45, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, credential.server_url + "/api" + path,
                headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"}, params=params, json=body)
        if not 200 <= response.status_code < 300:
            try:
                payload = response.json()
                detail = payload.get("error_description") or payload.get("error") or "Request failed"
            except (ValueError, AttributeError):
                detail = "Request failed"
            raise ValueError(f"YouTrack API {response.status_code}: {str(detail).replace(credential.api_token, '[redacted]')}")
        return response.json() if response.content else None

    async def _poll_issues(self, credential, config):
        issues = []
        # Full, bounded pagination before touching the seen set prevents a
        # partial read from silently advancing the baseline.
        for offset in range(0, 10000, 100):
            params = {"fields": ISSUE_FIELDS, "$top": 100, "$skip": offset}
            if config.query:
                params["query"] = config.query
            page = await self._request(credential, "GET", "/issues", params=params)
            if not isinstance(page, list) or any(not isinstance(row, dict) or not row.get("id") or not isinstance(row.get("updated"), int) for row in page):
                raise ValueError("YouTrack returned issues without id or updated timestamp")
            issues.extend(page)
            if len(page) < 100:
                break
        else:
            raise ValueError("More than 10,000 matching YouTrack issues; narrow the trigger's search query")
        fresh = await self._filter_unseen(issues, lambda row: f"{row['id']}:{row['updated']}")
        return {"issues": fresh, "issue_count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("issue_count")) if config.get("operation") == "on_issue_changed" else True

    @classmethod
    def resolve_agent_event(cls, output):
        issues = output.get("issues")
        if not isinstance(issues, list):
            return super().resolve_agent_event(output)
        if not issues:
            return None
        lines = []
        for issue in issues:
            project = issue.get("project") or {}
            actor = issue.get("updater") or issue.get("reporter") or {}
            lines.append(f"{actor.get('login') or 'Someone'} created or updated {issue.get('idReadable') or issue['id']} in {project.get('name') or 'YouTrack'}: {issue.get('summary') or 'Untitled issue'}\n{issue.get('description') or ''}\nIssue id: {issue['id']}; project id: {project.get('id') or 'unknown'}")
        return {"text": "YouTrack issue changes:\n" + "\n\n".join(lines), "conversation_key": None}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect YouTrack with your installation URL and permanent token")
        config = self.config.config
        if isinstance(config, YouTrackOnIssueChangedConfig):
            return await self._poll_issues(credential, config)
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True)
        path = spec.path
        for part in spec.path.split("{")[1:]:
            field = part.split("}")[0]
            value = values[field]
            if value in {".", ".."}:
                raise ValueError("A resource ID cannot be a relative path")
            path = path.replace("{" + field + "}", quote(value, safe=""))
        params = {"fields": spec.fields} if spec.fields else {}
        if spec.paged:
            params.update({"$top": config.limit, "$skip": config.offset})
        if spec.search and config.query:
            params["query"] = config.query
        body = {key: values[key] for key in spec.body if key in values}
        if "project_id" in body:
            body["project"] = {"id": body.pop("project_id")}
        if config.operation == "apply_command":
            body["query"] = body.pop("command")
            issue_id = body.pop("issue_id")
            body["issues"] = [{"id" if re.fullmatch(r"[0-9]+-[0-9]+", issue_id) else "idReadable": issue_id}]
        if config.operation == "update_issue" and config.clear_description:
            body["description"] = ""
        if config.operation == "add_issue_tag":
            body["id"] = body.pop("tag_id")
        data = await self._request(credential, spec.method, path, params=params, body=body if spec.body else None)
        if spec.paged:
            if not isinstance(data, list):
                raise ValueError("YouTrack returned an invalid list response")
            return {"data": data, "next_offset": config.offset + len(data) if len(data) == config.limit else None}
        if spec.method == "DELETE":
            return {"deleted": True}
        if not isinstance(data, dict):
            raise ValueError("YouTrack returned an invalid object response")
        return {"data": data}
