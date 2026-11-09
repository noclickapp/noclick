"""Circle Admin API v2 community administration.

Contract: https://api-headless.circle.so/api/admin/v2/swagger.yaml (v1).
Each operation makes exactly one request; list results retain Circle pagination.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.circle.so/api/admin/v2"
Id = Annotated[int, Field(gt=0)]
Text = Annotated[str, Field(min_length=1)]


class CircleAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Circle API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://api.circle.so/apis/admin-api",
        "x-credential-instructions": "In your Circle community, open Settings → Developers → Tokens and copy an Admin API token. Paste it without the Token prefix. Admin API access requires an eligible Circle plan (Business or above). NoClick reads your community details to check the connection.",
    })
    credential_type: Literal["circle_api_token"] = Field("circle_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Token")
        if not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without a header prefix or whitespace")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Config):
    page: int = Field(1, ge=1, description="Page to read. Use has_next_page in the returned data before advancing.")
    per_page: int = Field(20, ge=1, le=100)


class GetCommunity(_Config):
    """Read the community associated with the token."""
    operation: Literal["get_community"] = "get_community"


class ListMembers(_Page):
    operation: Literal["list_members"] = "list_members"
    status: Literal["active", "all", "inactive"] = "active"
    member_tag_ids: list[Id] | None = Field(None, description="Match any tag; sent as comma-separated IDs.")


class GetMember(_Config):
    operation: Literal["get_member"] = "get_member"
    id: Id = Field(..., title="Community Member ID")


class SearchMember(_Config):
    operation: Literal["search_member"] = "search_member"
    email: EmailStr


class CreateMember(_Config):
    """Add or invite a member. Circle may send invitation and welcome emails."""
    operation: Literal["create_member"] = "create_member"
    email: EmailStr
    name: Text | None = None
    headline: str | None = None
    skip_invitation: bool = Field(False, description="Skip invitation and welcome emails.")
    space_ids: list[Id] | None = None
    space_group_ids: list[Id] | None = None
    member_tag_ids: list[Id] | None = None
    community_member_profile_fields: dict[str, str] | None = None


class UpdateMember(_Config):
    """Update supplied fields; existing space memberships and tags are kept."""
    operation: Literal["update_member"] = "update_member"
    id: Id = Field(..., title="Community Member ID")
    name: Text | None = None
    headline: str | None = None
    is_flagged: bool | None = None
    space_ids: list[Id] | None = None
    space_group_ids: list[Id] | None = None
    member_tag_ids: list[Id] | None = None
    community_member_profile_fields: dict[str, str] | None = None

    @model_validator(mode="after")
    def changed(self):
        if not self.model_dump(exclude={"operation", "id"}, exclude_none=True):
            raise ValueError("Provide at least one member field to update")
        return self


class DeactivateMember(_Config):
    """Deactivate the membership; this is not permanent deletion."""
    operation: Literal["deactivate_member"] = "deactivate_member"
    id: Id = Field(..., title="Community Member ID")


class ListSpaces(_Page):
    operation: Literal["list_spaces"] = "list_spaces"
    sort: Literal["active", "oldest", "alphabetical", "likes", "latest_updated", "oldest_updated", "latest_profile_confirmed"] | None = None


class GetSpace(_Config):
    operation: Literal["get_space"] = "get_space"
    id: Id = Field(..., title="Space ID")


class ListSpaceMembers(_Page):
    operation: Literal["list_space_members"] = "list_space_members"
    space_id: Id
    status: Literal["active", "inactive", "all"] = "active"


class AddSpaceMember(_Config):
    operation: Literal["add_space_member"] = "add_space_member"
    space_id: Id
    email: EmailStr


class RemoveSpaceMember(_Config):
    operation: Literal["remove_space_member"] = "remove_space_member"
    space_id: Id
    email: EmailStr


class ListPosts(_Page):
    operation: Literal["list_posts"] = "list_posts"
    space_id: Id | None = None
    space_group_id: Id | None = None
    status: Literal["draft", "published", "scheduled", "all"] | None = None
    search_text: str | None = None
    sort: Literal["oldest", "latest", "alphabetical", "likes", "latest_updated", "oldest_updated"] | None = None


class GetPost(_Config):
    operation: Literal["get_post"] = "get_post"
    id: Id = Field(..., title="Post ID")


class CreatePost(_Config):
    """Create a basic post with optional plain text, converted to Tiptap JSON."""
    operation: Literal["create_post"] = "create_post"
    space_id: Id
    name: Text = Field(..., title="Post Title")
    text: str | None = Field(None, description="Plain text body; line breaks become paragraphs.")
    status: Literal["draft", "published"] = Field("published", description="Published posts can notify members.")
    skip_notifications: bool = Field(False, description="Suppress notifications for this request.")
    user_email: EmailStr | None = None
    topics: list[Id] | None = None


class UpdatePost(_Config):
    """Update title or Tiptap text. Circle ignores text for legacy non-Tiptap posts."""
    operation: Literal["update_post"] = "update_post"
    id: Id = Field(..., title="Post ID")
    name: Text | None = None
    text: str | None = Field(None, description="Replaces the Tiptap body; ignored by Circle on legacy posts.")
    is_comments_closed: bool | None = None
    is_pinned: bool | None = None
    topics: list[Id] | None = Field(None, description="Replaces all topics; an empty list clears them.")

    @model_validator(mode="after")
    def changed(self):
        if not self.model_dump(exclude={"operation", "id"}, exclude_none=True):
            raise ValueError("Provide at least one post field to update")
        return self


class DeletePost(_Config):
    operation: Literal["delete_post"] = "delete_post"
    id: Id = Field(..., title="Post ID")


class ListComments(_Page):
    operation: Literal["list_comments"] = "list_comments"
    space_id: Id | None = None
    post_id: Id | None = None
    search_text: str | None = None


class GetComment(_Config):
    operation: Literal["get_comment"] = "get_comment"
    id: Id = Field(..., title="Comment ID")


class CreateComment(_Config):
    operation: Literal["create_comment"] = "create_comment"
    post_id: Id
    body: Text = Field(..., description="Comment HTML.")
    parent_comment_id: Id | None = None
    skip_notifications: bool = Field(True, description="Suppress comment notifications.")
    user_email: EmailStr | None = None


class DeleteComment(_Config):
    operation: Literal["delete_comment"] = "delete_comment"
    id: Id = Field(..., title="Comment ID")


class ListMemberTags(_Page):
    operation: Literal["list_member_tags"] = "list_member_tags"
    name: str | None = None
    is_public: bool | None = None
    sort: Literal["oldest", "newest", "alphabetical", "alphabetical_desc"] | None = None


class CreateMemberTag(_Config):
    operation: Literal["create_member_tag"] = "create_member_tag"
    name: Text
    color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    is_public: bool = True
    display_format: Literal["label", "icon"] = "label"
    emoji: str | None = None

    @model_validator(mode="after")
    def icon(self):
        if self.display_format == "icon" and not self.emoji:
            raise ValueError("An icon tag requires an emoji")
        return self


class TagMember(_Config):
    operation: Literal["tag_member"] = "tag_member"
    member_tag_id: Id
    user_email: EmailStr


class UntagMember(_Config):
    operation: Literal["untag_member"] = "untag_member"
    member_tag_id: Id
    user_email: EmailStr


CircleConfig = Annotated[Union[
    GetCommunity, ListMembers, GetMember, SearchMember, CreateMember, UpdateMember,
    DeactivateMember, ListSpaces, GetSpace, ListSpaceMembers, AddSpaceMember,
    RemoveSpaceMember, ListPosts, GetPost, CreatePost, UpdatePost, DeletePost,
    ListComments, GetComment, CreateComment, DeleteComment, ListMemberTags,
    CreateMemberTag, TagMember, UntagMember,
], Field(discriminator="operation")]


class CircleFullConfig(NodeConfig[CircleConfig, CircleAPITokenCredential]):
    pass


ROUTES = {
    "get_community": ("GET", "/community"),
    "list_members": ("GET", "/community_members"),
    "get_member": ("GET", "/community_members/{id}"),
    "search_member": ("GET", "/community_members/search"),
    "create_member": ("POST", "/community_members"),
    "update_member": ("PUT", "/community_members/{id}"),
    "deactivate_member": ("DELETE", "/community_members/{id}"),
    "list_spaces": ("GET", "/spaces"),
    "get_space": ("GET", "/spaces/{id}"),
    "list_space_members": ("GET", "/space_members"),
    "add_space_member": ("POST", "/space_members"),
    "remove_space_member": ("DELETE", "/space_members"),
    "list_posts": ("GET", "/posts"),
    "get_post": ("GET", "/posts/{id}"),
    "create_post": ("POST", "/posts"),
    "update_post": ("PUT", "/posts/{id}"),
    "delete_post": ("DELETE", "/posts/{id}"),
    "list_comments": ("GET", "/comments"),
    "get_comment": ("GET", "/comments/{id}"),
    "create_comment": ("POST", "/comments"),
    "delete_comment": ("DELETE", "/comments/{id}"),
    "list_member_tags": ("GET", "/member_tags"),
    "create_member_tag": ("POST", "/member_tags"),
    "tag_member": ("POST", "/tagged_members"),
    "untag_member": ("DELETE", "/tagged_members"),
}


def _check_credential(config_data):
    credential = config_data.get("credentials")
    if isinstance(credential, dict) and credential.get("credential_type", "circle_api_token") != "circle_api_token":
        raise ValueError("Attach a Circle API token credential")


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, dict):
        return {_redact(k, token): _redact(v, token) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value


class CircleNode(WorkflowNode):
    integration_type = "automation-circle"
    connection_evidence = ConnectionEvidence(identity_operation="get_community", noun="Circle community")

    @classmethod
    def get_config_model(cls):
        return CircleFullConfig

    @classmethod
    def parse_config(cls, config_data):
        _check_credential(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            _check_credential(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Circle API token")
        token = self.config.credentials.api_token
        op = self.config.config
        method, path = ROUTES[op.operation]
        payload = op.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
        if "{id}" in path:
            path = path.replace("{id}", str(payload.pop("id")))
        if "text" in payload:
            text = payload.pop("text")
            payload["tiptap_body"] = {"body": {"type": "doc", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": line}] if line else []}
                for line in text.split("\n")
            ]}}
        kwargs = {}
        if method in {"GET", "DELETE"}:
            if "member_tag_ids" in payload:
                payload["member_tag_ids"] = ",".join(str(i) for i in payload["member_tag_ids"])
            kwargs["params"] = payload
        else:
            kwargs["json"] = payload
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Token " + token, "Accept": "application/json"}, **kwargs)
        if response.is_redirect:
            raise ValueError("Circle redirected the request")
        if "json" not in response.headers.get("Content-Type", "").lower():
            raise ValueError(f"Expected JSON from Circle (HTTP {response.status_code})")
        try:
            body = response.json()
        except ValueError:
            raise ValueError(f"Invalid JSON from Circle (HTTP {response.status_code})") from None
        body = _redact(body, token)
        if not isinstance(body, dict):
            raise ValueError("Unexpected Circle response shape")
        if not response.is_success or body.get("success") is False or body.get("error") or body.get("errors"):
            detail = body.get("message") or body.get("error") or body.get("errors") or body
            raise ValueError(f"HTTP {response.status_code}: {json.dumps(detail, ensure_ascii=False) if not isinstance(detail, str) else detail}")
        if isinstance(op, GetCommunity):
            if not body.get("id") or not isinstance(body.get("name"), str) or not body["name"].strip():
                raise ValueError("Circle did not return a community identity")
            return {"status": "success", "operation": op.operation, **{k: body[k] for k in ("id", "name", "slug") if k in body}}
        return {"status": "success", "operation": op.operation, "data": body}
