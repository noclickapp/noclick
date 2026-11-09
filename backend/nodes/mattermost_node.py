"""Mattermost REST API v4: one documented endpoint per operation.

Personal access tokens retain the user's server permissions. Requests use the
public HTTPS deployment URL, including an optional deployment subpath, with
DNS/IP SSRF protection and no redirects or automatic mutation retries.
Contract: https://s3.amazonaws.com/api.mattermost.com/static/mattermost-openapi-v4.yaml
Token setup: https://docs.mattermost.com/developers/integrate/reference/personal-access-token
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class MattermostTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Mattermost Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.mattermost.com/developers/integrate/reference/personal-access-token",
            "x-credential-instructions": "Enter your public HTTPS Mattermost server URL (including its deployment subpath, if any) and paste a personal access token from Profile > Security > Personal Access Tokens. Your administrator must enable token creation. Use a non-admin account with access to the teams and channels you automate. NoClick checks the token by reading your current user profile; individual operations still require the corresponding server permissions.",
        },
    )
    credential_type: Literal["mattermost_token"] = Field("mattermost_token", json_schema_extra={"ui:hidden": True})
    server_url: str = Field(..., title="Server URL", description="Public HTTPS deployment URL, e.g. https://chat.example.com. Include a deployment subpath if used; omit /api/v4.")
    access_token: str = Field(..., min_length=1, max_length=4096, title="Personal access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("server_url", mode="before")
    @classmethod
    def server(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter your public HTTPS Mattermost deployment URL")
        value = value.strip().rstrip("/")
        try:
            p = urlsplit(value)
            port = p.port
        except ValueError:
            raise ValueError("Enter a valid HTTPS server URL") from None
        if (p.scheme != "https" or not p.hostname or "." not in p.hostname
                or p.username is not None or p.password is not None or p.query or p.fragment
                or port not in (None, 443) or not re.fullmatch(r"[A-Za-z0-9.-]+", p.hostname)
                or any(not re.fullmatch(r"[A-Za-z0-9_-]+", s) for s in p.path.split("/") if s)
                or "//" in p.path or p.path.endswith("/api/v4")):
            raise ValueError("Use a public HTTPS deployment URL without credentials, query, fragment or /api/v4")
        return "https://" + p.hostname.lower().rstrip(".") + p.path

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste a personal access token")
        value = clean_secret(value, field_name="Personal access token", key=True)
        if any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the token alone, without a Bearer prefix or whitespace")
        return value


Identifier = Annotated[str, Field(pattern=r"^[a-z0-9]{26}$", description="Mattermost 26-character resource ID.")]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(0, ge=0, le=100000, description="Zero-based page; this operation reads one page only.")
    per_page: int = Field(60, ge=1, le=200, description="Maximum results requested for this page.")

class GetCurrentUser(_Input):
    """Read the authenticated account to verify the connection."""
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={"ui:hidden": True})


class GetUser(_Input):
    """Read a user profile."""
    operation: Literal["get_user"] = Field("get_user", json_schema_extra={"ui:hidden": True})
    user_id: Identifier


class GetUserByUsername(_Input):
    """Find a user by their exact username."""
    operation: Literal["get_user_by_username"] = Field("get_user_by_username", json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9._-]+$")


class ListMyTeams(_Input):
    """List teams the authenticated user belongs to."""
    operation: Literal["list_my_teams"] = Field("list_my_teams", json_schema_extra={"ui:hidden": True})


class ListPublicChannels(_Page):
    """Read one page of public channels in a team."""
    operation: Literal["list_public_channels"] = Field("list_public_channels", json_schema_extra={"ui:hidden": True})
    team_id: Identifier


class ListMyChannels(_Input):
    """List the authenticated user’s channels in a team."""
    operation: Literal["list_my_channels"] = Field("list_my_channels", json_schema_extra={"ui:hidden": True})
    team_id: Identifier


class GetChannel(_Input):
    """Read a channel."""
    operation: Literal["get_channel"] = Field("get_channel", json_schema_extra={"ui:hidden": True})
    channel_id: Identifier


class CreateChannel(_Input):
    """Create a public or private channel."""
    operation: Literal["create_channel"] = Field("create_channel", json_schema_extra={"ui:hidden": True})
    team_id: Identifier
    name: str = Field(..., min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]+$")
    display_name: str = Field(..., min_length=1, max_length=64)
    type: Literal["O", "P"] = Field("O", title="Channel visibility", description="O: public; P: private.")
    purpose: str | None = Field(None, max_length=250)
    header: str | None = Field(None, max_length=1024)


class UpdateChannel(_Input):
    """Update only the supplied channel fields."""
    operation: Literal["update_channel"] = Field("update_channel", json_schema_extra={"ui:hidden": True})
    channel_id: Identifier
    display_name: str | None = Field(None, min_length=1, max_length=64)
    purpose: str | None = Field(None, max_length=250)
    header: str | None = Field(None, max_length=1024)

    @model_validator(mode="after")
    def changed(self):
        if all(getattr(self, k) is None for k in ("display_name", "purpose", "header")):
            raise ValueError("Supply a display name, purpose or header to update")
        return self


class CreateDirectChannel(_Input):
    """Create or retrieve the direct channel between two users."""
    operation: Literal["create_direct_channel"] = Field("create_direct_channel", json_schema_extra={"ui:hidden": True})
    first_user_id: Identifier
    second_user_id: Identifier



class ListChannelMembers(_Page):
    """Read one page of channel memberships."""
    operation: Literal["list_channel_members"] = Field("list_channel_members", json_schema_extra={"ui:hidden": True})
    channel_id: Identifier


class AddChannelMember(_Input):
    """Add one user to a channel."""
    operation: Literal["add_channel_member"] = Field("add_channel_member", json_schema_extra={"ui:hidden": True})
    channel_id: Identifier
    user_id: Identifier


class RemoveChannelMember(_Input):
    """Remove a user from a channel."""
    operation: Literal["remove_channel_member"] = Field("remove_channel_member", json_schema_extra={"ui:hidden": True})
    channel_id: Identifier
    user_id: Identifier


class ListPosts(_Page):
    """Read one page of messages in a channel, newest first."""
    operation: Literal["list_posts"] = Field("list_posts", json_schema_extra={"ui:hidden": True})
    channel_id: Identifier


class CreatePost(_Input):
    """Send a Markdown message or reply in a channel."""
    operation: Literal["create_post"] = Field("create_post", json_schema_extra={"ui:hidden": True})
    channel_id: Identifier
    message: str = Field(..., min_length=1, max_length=16383)
    root_id: Identifier | None = Field(None, description="Root message ID when replying to a thread.")
    file_ids: list[Identifier] | None = Field(None, max_length=5, description="IDs of files already uploaded to this server.")


class GetPost(_Input):
    """Read one message."""
    operation: Literal["get_post"] = Field("get_post", json_schema_extra={"ui:hidden": True})
    post_id: Identifier


class UpdatePost(_Input):
    """Patch the message text while preserving other fields."""
    operation: Literal["update_post"] = Field("update_post", json_schema_extra={"ui:hidden": True})
    post_id: Identifier
    message: str = Field(..., min_length=1, max_length=16383)


class DeletePost(_Input):
    """Delete a message (the server may retain it for compliance)."""
    operation: Literal["delete_post"] = Field("delete_post", json_schema_extra={"ui:hidden": True})
    post_id: Identifier


class GetThread(_Input):
    """Read a thread in one API response, with an optional continuation post."""
    operation: Literal["get_thread"] = Field("get_thread", json_schema_extra={"ui:hidden": True})
    post_id: Identifier
    per_page: int = Field(60, ge=1, le=200)
    from_post: Identifier | None = None
    direction: Literal["up", "down"] = "up"


class SearchPosts(_Page):
    """Search team messages; page controls require Elasticsearch on the server."""
    operation: Literal["search_posts"] = Field("search_posts", json_schema_extra={"ui:hidden": True})
    team_id: Identifier
    terms: str = Field(..., min_length=1, max_length=1000, description="Mattermost search syntax, e.g. in:town-square release")
    is_or_search: bool = False


class AddReaction(_Input):
    """React to a post as the supplied authenticated user ID."""
    operation: Literal["add_reaction"] = Field("add_reaction", json_schema_extra={"ui:hidden": True})
    user_id: Identifier
    post_id: Identifier
    emoji_name: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_+-]+$")


class RemoveReaction(_Input):
    """Remove the supplied user’s reaction (permissions apply)."""
    operation: Literal["remove_reaction"] = Field("remove_reaction", json_schema_extra={"ui:hidden": True})
    user_id: Identifier
    post_id: Identifier
    emoji_name: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_+-]+$")


class ListReactions(_Input):
    """List reactions on a post."""
    operation: Literal["list_reactions"] = Field("list_reactions", json_schema_extra={"ui:hidden": True})
    post_id: Identifier


class PinPost(_Input):
    """Pin a message to its channel."""
    operation: Literal["pin_post"] = Field("pin_post", json_schema_extra={"ui:hidden": True})
    post_id: Identifier


class UnpinPost(_Input):
    """Unpin a message from its channel."""
    operation: Literal["unpin_post"] = Field("unpin_post", json_schema_extra={"ui:hidden": True})
    post_id: Identifier


MattermostConfig = Annotated[Union[GetCurrentUser, GetUser, GetUserByUsername, ListMyTeams, ListPublicChannels, ListMyChannels, GetChannel, CreateChannel, UpdateChannel, CreateDirectChannel, ListChannelMembers, AddChannelMember, RemoveChannelMember, ListPosts, CreatePost, GetPost, UpdatePost, DeletePost, GetThread, SearchPosts, AddReaction, RemoveReaction, ListReactions, PinPost, UnpinPost], Field(discriminator="operation")]


class MattermostFullConfig(NodeConfig[MattermostConfig, MattermostTokenCredential]):
    pass


ROUTES = {'get_current_user': ('GET', '/users/me', [], 'object'),
 'get_user': ('GET', '/users/{user_id}', [], 'object'),
 'get_user_by_username': ('GET', '/users/username/{username}', [], 'object'),
 'list_my_teams': ('GET', '/users/me/teams', [], 'array'),
 'list_public_channels': ('GET', '/teams/{team_id}/channels', [], 'array'),
 'list_my_channels': ('GET', '/users/me/teams/{team_id}/channels', [], 'array'),
 'get_channel': ('GET', '/channels/{channel_id}', [], 'object'),
 'create_channel': ('POST',
                    '/channels',
                    ['team_id', 'name', 'display_name', 'type', 'purpose', 'header'],
                    'object'),
 'update_channel': ('PUT', '/channels/{channel_id}/patch', ['display_name', 'purpose', 'header'], 'object'),
 'create_direct_channel': ('POST', '/channels/direct', [], 'object'),
 'list_channel_members': ('GET', '/channels/{channel_id}/members', [], 'array'),
 'add_channel_member': ('POST', '/channels/{channel_id}/members', ['user_id'], 'member'),
 'remove_channel_member': ('DELETE', '/channels/{channel_id}/members/{user_id}', [], 'status'),
 'list_posts': ('GET', '/channels/{channel_id}/posts', [], 'posts'),
 'create_post': ('POST', '/posts', ['channel_id', 'message', 'root_id', 'file_ids'], 'object'),
 'get_post': ('GET', '/posts/{post_id}', [], 'object'),
 'update_post': ('PUT', '/posts/{post_id}/patch', ['message'], 'object'),
 'delete_post': ('DELETE', '/posts/{post_id}', [], 'status'),
 'get_thread': ('GET', '/posts/{post_id}/thread', [], 'posts'),
 'search_posts': ('POST',
                  '/teams/{team_id}/posts/search',
                  ['terms', 'is_or_search', 'page', 'per_page'],
                  'posts'),
 'add_reaction': ('POST', '/reactions', ['user_id', 'post_id', 'emoji_name'], 'reaction'),
 'remove_reaction': ('DELETE', '/users/{user_id}/posts/{post_id}/reactions/{emoji_name}', [], 'status'),
 'list_reactions': ('GET', '/posts/{post_id}/reactions', [], 'array'),
 'pin_post': ('POST', '/posts/{post_id}/pin', [], 'status'),
 'unpin_post': ('POST', '/posts/{post_id}/unpin', [], 'status')}


_SENSITIVE = {"password", "auth_data", "mfa_secret", "access_token", "token", "refresh_token"}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items() if k.lower() not in _SENSITIVE}
    return value


def _response_shape(payload, kind):
    if kind == "array":
        return isinstance(payload, list) and all(isinstance(row, dict) for row in payload)
    if not isinstance(payload, dict):
        return False
    if kind == "status":
        return isinstance(payload.get("status"), str) and payload["status"].lower() == "ok"
    if kind == "posts":
        return (isinstance(payload.get("order"), list) and isinstance(payload.get("posts"), dict)
                and all(isinstance(v, dict) for v in payload["posts"].values()))
    keys = ("user_id", "channel_id") if kind == "member" else ("user_id", "post_id", "emoji_name") if kind == "reaction" else ("id",)
    return all(isinstance(payload.get(k), str) and payload[k] for k in keys)


class MattermostNode(WorkflowNode):
    integration_type = "automation-mattermost"
    connection_evidence = ConnectionEvidence(
        noun="Mattermost account", identity_operation="get_current_user",
        label_keys=("username", "email", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return MattermostFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect your Mattermost server and personal access token")
        credential = self.config.credentials
        op = self.config.config
        values = op.model_dump(exclude_none=True)
        method, template, body_fields, kind = ROUTES[op.operation]
        # Every template field is bounded to a single safe path segment by its schema.
        path = template.format(**values)
        body = {key: values[key] for key in body_fields if key in values} if body_fields else None
        params = {}
        if isinstance(op, _Page) and method == "GET":
            params = {"page": op.page, "per_page": op.per_page}
        if isinstance(op, GetThread):
            params = {"perPage": op.per_page, "direction": op.direction}
            if op.from_post is not None:
                params["fromPost"] = op.from_post
        if isinstance(op, CreateDirectChannel):
            body = [op.first_user_id, op.second_user_id]
        url = credential.server_url + "/api/v4" + path
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(
                    method, url, params=params,
                    headers={"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"},
                    **({"json": body} if body is not None else {}),
                )
        except Exception:
            raise ValueError("Mattermost request could not be completed. For a write, inspect the server before retrying; its outcome may be unknown.") from None
        if len(response.content) > 10_000_000:
            raise ValueError("Mattermost response exceeds the supported size; request fewer results")
        if not 200 <= response.status_code < 300:
            message = "Mattermost returned HTTP " + str(response.status_code)
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"]
            except ValueError:
                pass
            output = {"status": "error", "http_status": response.status_code,
                      "message": _redact(message, credential.access_token),
                      "write_outcome": "unknown" if method != "GET" and response.status_code >= 500 else "not_confirmed"}
        else:
            try:
                if response.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
                    raise ValueError()
                payload = response.json()
                if not _response_shape(payload, kind):
                    raise ValueError()
                if isinstance(op, GetCurrentUser) and (not isinstance(payload.get("username"), str) or not payload["username"].strip()):
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValueError("Mattermost returned an unexpected response. For a write, inspect the server before retrying.") from None
            output = {"status": "success", "http_status": response.status_code,
                      "data": _redact(payload, credential.access_token)}
            if isinstance(op, _Page):
                output["page"] = op.page
                output["per_page"] = op.per_page
                output["single_page"] = True
                # Search can use different backends; its page controls are not a completeness guarantee.
                if kind == "array":
                    output["next_page"] = op.page + 1 if len(payload) >= op.per_page else None
        await self.emit(output)
        return output
