"""Padlet v1 API, pinned to https://padlet.com/openapi.json (version 1.0).

Public API keys belong to a paid individual user. Organization operations need
organization administrator access. Roster polling observes membership, not the
moment a user joined: signupDate is the user's Padlet account creation date.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE = "https://api.padlet.dev/v1"
MEDIA = "application/vnd.api+json"


class PadletAPIKey(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True, title="Padlet API Key", json_schema_extra={
        "x-credential-url": "https://padlet.com/dashboard/settings/developer",
        "x-credential-instructions": "Paste the API key from your personal account's Developer settings. A paid Padlet plan is required. Use the public API key, rather than the Zapier API key. Board operations require administrator access; organization reads require organization access.",
    })
    credential_type: Literal["padlet_1_api_key"] = Field("padlet_1_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        return clean_secret(value, field_name="API key")


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetCurrentUser(Input):
    operation: Literal["get_current_user"] = Field("get_current_user", title="Get Current User")
    include: str = Field("boards,organizations", description="Related resources: boards,organizations.")


class GetBoard(Input):
    operation: Literal["get_board"] = Field("get_board", title="Get Board and Posts")
    board_id: str = Field(..., min_length=16, max_length=22, pattern=r"^[A-Za-z0-9_-]+$")
    include: str = Field("posts,sections,comments", description="Related resources to include.")


class AttachmentPoll(Input):
    question: str | None = None
    choices: list[str] | None = None


class CanvasProps(Input):
    left: int | None = None
    top: int | None = None
    width: int | None = None


class MapProps(Input):
    latitude: float | None = None
    longitude: float | None = None
    locationName: str | None = None


class ManualSortPosition(Input):
    previousPostId: str | None = Field(None, min_length=16, max_length=22)


class Attachment(Input):
    url: str | None = Field(None, json_schema_extra={"format": "uri"})
    caption: str | None = None
    previewImageUrl: str | None = None
    embedCode: str | None = None
    poll: AttachmentPoll | None = None

    @field_validator("url")
    @classmethod
    def public_url(cls, value):
        if value is not None and (urlsplit(value).scheme not in {"http", "https"} or not urlsplit(value).netloc):
            raise ValueError("Use an absolute HTTP or HTTPS attachment URL")
        return value


class CreatePost(Input):
    operation: Literal["create_post"] = Field("create_post", title="Create Post")
    board_id: str = Field(..., min_length=16, max_length=22, pattern=r"^[A-Za-z0-9_-]+$")
    subject: str | None = Field(None, max_length=500)
    body: str | None = Field(None, max_length=10000)
    attachment: Attachment | None = None
    section_id: str | None = Field(None, min_length=16, max_length=22)
    color: Literal["red", "orange", "green", "blue", "purple"] | None = None
    status: Literal["approved", "pending_moderation", "scheduled"] | None = None
    custom_fields: dict[str, Any] | None = None
    canvas_props: CanvasProps | None = None
    map_props: MapProps | None = None
    manual_sort_position: ManualSortPosition | None = None


class GetAttachmentData(Input):
    operation: Literal["get_post_attachment_data"] = Field("get_post_attachment_data", title="Get Post Attachment Data")
    post_id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")


class GetOrganization(Input):
    operation: Literal["get_organization"] = Field("get_organization", title="Get Organization and Members")
    org_id: str = Field(..., min_length=16, max_length=22, pattern=r"^[A-Za-z0-9_-]+$")
    include: Literal["users"] = "users"


class GetUserBoards(Input):
    operation: Literal["get_user_boards"] = Field("get_user_boards", title="Get User's Organization Boards")
    org_id: str = Field(..., min_length=16, max_length=22, pattern=r"^[A-Za-z0-9_-]+$")
    user_id: str = Field(..., min_length=16, max_length=22, pattern=r"^[A-Za-z0-9_-]+$")
    include: Literal["boards"] = "boards"


class CreateReaction(Input):
    operation: Literal["create_reaction"] = Field("create_reaction", title="Create Reaction")
    post_id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    value: int
    reaction_type: Literal["like", "star", "grade", "vote"] | None = None


class CreateComment(Input):
    operation: Literal["create_comment"] = Field("create_comment", title="Create Comment")
    post_id: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    html_content: str = Field(..., min_length=1, max_length=10000)
    attachment_url: str | None = Field(None, json_schema_extra={"format": "uri"})


    @field_validator("attachment_url")
    @classmethod
    def public_url(cls, value):
        return Attachment.public_url(value)


class CreateAIRecipeBoard(Input):
    operation: Literal["create_ai_recipe_board"] = Field("create_ai_recipe_board", title="Create AI Recipe Board")
    board_creation_instructions: str = Field(..., min_length=1, max_length=2000)
    role: str = Field(..., min_length=1)
    workspace_id: str | None = None


class GetAIRecipeBoardStatus(Input):
    operation: Literal["get_ai_recipe_board_status"] = Field("get_ai_recipe_board_status", title="Get AI Recipe Board Status")
    status_key: str = Field(..., min_length=1, pattern=r"^[A-Za-z0-9_-]+$")


class DateRange(Input):
    from_date: str | None = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")
    to_date: str | None = Field(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")

    @model_validator(mode="after")
    def dates(self):
        if bool(self.from_date) != bool(self.to_date):
            raise ValueError("Supply both from_date and to_date, or neither")
        return self


MetricName = Literal["memberCount", "newMemberCount", "padletCount", "postCount", "commentCount", "reactionCount", "wallEngagementMinutes", "visitorCount", "peerInteractionCount", "attachmentCountByCategory", "scannedItemCount", "scannedItemCountByType", "avgScanTimeMs", "flaggedItemCount", "flaggedItemCountByCategory", "moderationCatchRatePercent", "topPadlets", "topUsers", "topMedia", "subscription"]
Role = Literal["owner", "admin", "maker", "teacher", "student", "contributor", "guest", "anonymous", "all"]
Activity = Literal["active", "inactive", "invited", "joined", "all"]


class Metric(Input):
    name: MetricName
    status: Activity | list[Activity] | None = None
    userType: Role | list[Role] | None = None
    sortBy: Literal["posts", "visitors", "padlets"] | list[Literal["posts", "visitors", "padlets"]] | None = None
    mediaType: Literal["video", "audio"] | list[Literal["video", "audio"]] | None = None


class ReadOrganizationAnalytics(DateRange):
    operation: Literal["read_organization_analytics"] = Field("read_organization_analytics", title="Read Organization Analytics")
    org_id: str = Field(..., min_length=16, max_length=22, pattern=r"^[A-Za-z0-9_-]+$")
    metrics: list[Metric] = Field(..., min_length=1, max_length=25)
    dimensions: list[Literal["month"]] | None = None


class ReadOrganizationUsers(DateRange):
    operation: Literal["read_organization_users"] = Field("read_organization_users", title="Read Organization Analytics Users")
    org_id: str = Field(..., min_length=16, max_length=22, pattern=r"^[A-Za-z0-9_-]+$")
    status: list[Literal["active", "inactive"]] | None = None
    user_type: list[Literal["admin", "maker", "teacher", "student", "contributor", "guest"]] | None = None
    q: str | None = None
    sort: Literal["name", "email", "userType", "signupDate", "lastActivityDate", "padlets", "posts", "comments", "reactions"] = "name"
    order: Literal["asc", "desc"] = "asc"
    page: int = Field(1, ge=1)
    per_page: int = Field(25, ge=1, le=100)


class OnNewOrganizationUser(PollTriggerConfigBase):
    operation: Literal["on_new_organization_user"] = Field("on_new_organization_user", title="On New Organization User", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Organization User",
    })
    org_id: str = Field(..., min_length=16, max_length=22, pattern=r"^[A-Za-z0-9_-]+$", description="Organization whose recent Padlet signups to watch. Requires organization analytics access.")
    limit: int = Field(25, ge=1, le=100, title="Recent signup window", description="Watch the first page ordered by Padlet account signup date, newest first. The first poll establishes a baseline. Signup date is account creation, not organization join time: existing accounts joining can fall outside this window. More than this many new signups between polls can be missed. One request per poll stays within the documented 60 requests/hour limit with the default five-minute schedule.")


PadletConfig = Annotated[Union[GetCurrentUser, GetBoard, CreatePost, GetAttachmentData, GetOrganization, GetUserBoards, CreateReaction, CreateComment, CreateAIRecipeBoard, GetAIRecipeBoardStatus, ReadOrganizationAnalytics, ReadOrganizationUsers, OnNewOrganizationUser], Field(discriminator="operation")]


class PadletNodeConfig(NodeConfig[PadletConfig, PadletAPIKey]):
    pass


class PadletNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-padlet-1"
    connection_evidence = ConnectionEvidence(noun="Padlet account", identity_operation="get_current_user", identity_keys=("fullName", "username"))

    @classmethod
    def get_config_model(cls):
        return PadletNodeConfig

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Padlet API key")
        headers = {"X-Api-Key": credential.api_key, "Accept": MEDIA}
        if body is not None:
            headers["Content-Type"] = MEDIA
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, headers=headers, params=params, json=body)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("Padlet returned an unexpected document")
        if "errors" in result and result["errors"]:
            raise ValueError(str(result["errors"]))
        return result

    @staticmethod
    def _params(config):
        mapping = {"from_date": "from", "to_date": "to", "per_page": "perPage", "user_type": "userType[]", "status": "status[]"}
        return {mapping.get(k, k): v for k, v in config.model_dump(exclude_none=True).items() if k not in {"operation", "org_id"}}

    async def _poll_users(self, config):
        result = await self._request("GET", "/organizations/" + quote(config.org_id, safe="") + "/analytics/users", params={"sort": "signupDate", "order": "desc", "page": 1, "perPage": config.limit})
        meta = result.get("meta", {})
        if meta.get("status") != "ready" or meta.get("errors") or meta.get("pending"):
            raise ValueError("Padlet organization roster is not ready; retry on the next poll")
        rows = result.get("data")
        if not isinstance(rows, list) or len(rows) > config.limit or meta.get("page") != 1:
            raise ValueError("Padlet returned an invalid recent-signup page")
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or row.get("type") != "organizationAnalyticsUser" or not isinstance(row.get("id"), str) or not row["id"] or not isinstance(row.get("attributes"), dict):
                raise ValueError("Padlet roster contains an invalid user")
            if row["id"] in seen:
                raise ValueError("Padlet roster contains duplicate users")
            seen.add(row["id"])
        fresh = await self._filter_unseen(rows, lambda row: row["id"])
        return {"users": fresh, "new_user_count": len(fresh), "org_id": config.org_id}

    @classmethod
    def resolve_agent_event(cls, output):
        if "users" not in output:
            return super().resolve_agent_event(output)
        users = output["users"]
        if not users:
            return None
        names = [user["attributes"].get("name") or user["attributes"].get("username") or user["id"] for user in users]
        lines = [f"Newly observed Padlet users in organization {output['org_id']}: {', '.join(names)}"]
        for user in users:
            attrs = user["attributes"]
            lines.append(f"User {user['id']}: {attrs.get('email') or ''}; role {attrs.get('userType') or ''}; Padlet signup date {attrs.get('signupDate') or 'unknown'}.")
        lines.append(f"To act: get_user_boards with org_id={output['org_id']} and a user_id above. Signup date is account creation, not organization join time.")
        return {"text": "\n".join(lines), "conversation_key": str(output["org_id"]), "title": "New Padlet organization users"}

    async def execute(self, inputs):
        c = self.config.config
        if isinstance(c, OnNewOrganizationUser):
            return await self._poll_users(c)
        enc = lambda value: quote(value, safe="")
        params = None
        body = None
        method = "GET"
        if isinstance(c, GetCurrentUser):
            path, params = "/me", {"include": c.include}
        elif isinstance(c, GetBoard):
            path, params = f"/boards/{enc(c.board_id)}", {"include": c.include}
        elif isinstance(c, GetAttachmentData):
            path = f"/posts/{enc(c.post_id)}/attachmentData"
        elif isinstance(c, GetOrganization):
            path, params = f"/organizations/{enc(c.org_id)}", {"include": c.include}
        elif isinstance(c, GetUserBoards):
            path, params = f"/organizations/{enc(c.org_id)}/users/{enc(c.user_id)}", {"include": c.include}
        elif isinstance(c, CreatePost):
            method, path = "POST", f"/boards/{enc(c.board_id)}/posts"
            content = {k: v for k, v in c.model_dump(exclude_none=True).items() if k in {"subject", "body", "attachment"}}
            attrs = {"content": content}
            for local, wire in {"color": "color", "status": "status", "custom_fields": "customFields", "canvas_props": "canvasProps", "map_props": "mapProps", "manual_sort_position": "manualSortPosition"}.items():
                value = getattr(c, local)
                if value is not None:
                    attrs[wire] = value.model_dump(exclude_none=True) if isinstance(value, BaseModel) else value
            data = {"type": "post", "attributes": attrs}
            if c.section_id:
                # The relationship type is readOnly; the documented write sends only id.
                data["relationships"] = {"section": {"data": {"id": c.section_id}}}
            body = {"data": data}
        elif isinstance(c, CreateReaction):
            method, path = "POST", f"/posts/{enc(c.post_id)}/reactions"
            attrs = {"value": c.value}
            if c.reaction_type is not None:
                attrs["reactionType"] = c.reaction_type
            body = {"data": {"type": "reaction", "attributes": attrs}}
        elif isinstance(c, CreateComment):
            method, path = "POST", f"/posts/{enc(c.post_id)}/comments"
            attrs = {"htmlContent": c.html_content}
            if c.attachment_url:
                attrs["attachment"] = {"url": c.attachment_url}
            body = {"data": {"type": "comment", "attributes": attrs}}
        elif isinstance(c, CreateAIRecipeBoard):
            method, path = "POST", "/ai-recipe-boards"
            attrs = {"boardCreationInstructions": c.board_creation_instructions, "role": c.role}
            if c.workspace_id:
                attrs["workspaceId"] = c.workspace_id
            body = {"data": {"type": "ai_recipe_board", "attributes": attrs}}
        elif isinstance(c, GetAIRecipeBoardStatus):
            path = f"/ai-recipe-boards/status/{enc(c.status_key)}"
        elif isinstance(c, ReadOrganizationAnalytics):
            method, path = "POST", f"/organizations/{enc(c.org_id)}/analytics"
            body = self._params(c)
        elif isinstance(c, ReadOrganizationUsers):
            path, params = f"/organizations/{enc(c.org_id)}/analytics/users", self._params(c)
        else:
            raise ValueError("Unsupported Padlet operation")
        return await self._request(method, path, params=params, body=body)
