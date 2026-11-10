"""Nextdoor Publish API v1. One workflow operation makes one provider request.

Contract: https://developer.nextdoor.com/reference/me-1 and linked Publish API
pages. Access requires approval from Nextdoor's Partnerships team.
"""
from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from nodes.scopes.nextdoor import NEXTDOOR_SCOPES

BASE = "https://nextdoor.com/external/api/partner/v1"


class NextdoorOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Nextdoor Account", json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "nextdoor",
        "x-oauth-scopes": NEXTDOOR_SCOPES.declared_scopes(),
        "x-credential-url": "https://developer.nextdoor.com/reference/applying-for-access",
        "x-credential-instructions": "Connect a Nextdoor account through an approved Publish API application. Agency boundaries require an agency account. Ads Manager tokens are for a different API.",
    })
    credential_type: Literal["nextdoor_oauth"] = Field("nextdoor_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", json_schema_extra={"ui:widget": "password"})
    refresh_token: Optional[str] = Field(None, title="Refresh Token", json_schema_extra={"ui:widget": "password"})
    expires_at: Optional[str] = Field(None, title="Token Expiry")


class GetAccount(BaseModel):
    operation: Literal["get_account"] = Field("get_account", title="Get Current Account")


class ListProfiles(BaseModel):
    operation: Literal["list_profiles"] = Field("list_profiles", title="List Account Profiles")


class ListPosts(BaseModel):
    operation: Literal["list_posts"] = Field("list_posts", title="Get Your Posts")
    secure_profile_id: Optional[str] = Field(None, title="Profile ID")


class NextdoorPollConfig(PollTriggerConfigBase):
    secure_profile_id: Optional[str] = Field(None, title="Profile ID", description="Omit for your primary profile. Nextdoor's recent-post feed does not support business or entity page profiles.")


class OnNewPost(NextdoorPollConfig):
    operation: Literal["on_new_post"] = Field("on_new_post", title="On New Post", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Post", "ui:hidden": True,
    })


class OnNewComment(NextdoorPollConfig):
    operation: Literal["on_new_comment"] = Field("on_new_comment", title="On New Comment", description="Watch comments and replies on your recent posts. Older posts outside Nextdoor's feed are not monitored.", json_schema_extra={
        "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New Comment", "ui:hidden": True,
    })


class PostFields(BaseModel):
    body_text: str = Field(..., min_length=1, max_length=8192, title="Post Text")
    hashtag: Optional[str] = Field(None, pattern=r"^\S+$", title="Hashtag")
    media_attachments: Optional[list[str]] = Field(None, max_length=10, title="Public Media URLs")
    lat: Optional[float] = Field(None, ge=-90, le=90, title="Latitude")
    lon: Optional[float] = Field(None, ge=-180, le=180, title="Longitude")
    smartlink_url: Optional[str] = Field(None, title="Link Preview URL")


class CreatePost(PostFields):
    operation: Literal["create_post"] = Field("create_post", title="Create Post")
    secure_profile_id: Optional[str] = Field(None, title="Profile ID", description="Select an id returned by List Account Profiles, or omit for the primary profile.")


class Listing(BaseModel):
    title: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    price: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1)
    image_attachments: list[str] = Field(..., min_length=1, max_length=10)


class CreateListing(BaseModel):
    operation: Literal["create_listing"] = Field("create_listing", title="Create For Sale or Free Listing")
    fsf: Listing = Field(..., title="Listing")
    body_text: str = Field(..., min_length=1, max_length=8192, title="Post Text")
    hashtag: Optional[str] = Field(None, pattern=r"^\S+$")
    smartlink_url: Optional[str] = None


class SetListingSold(BaseModel):
    operation: Literal["set_listing_sold"] = Field("set_listing_sold", title="Set Listing Sold Status")
    classified_id: str = Field(..., min_length=1, title="Classified ID")
    sold: bool = Field(..., title="Sold")


class ProfileResource(BaseModel):
    id: str = Field(..., min_length=1, title="Resource ID")
    secure_profile_id: Optional[str] = Field(None, title="Profile ID")


class CreateComment(ProfileResource):
    operation: Literal["create_comment"] = Field("create_comment", title="Create Comment or Reply")
    body_text: str = Field(..., min_length=1, title="Comment Text")
    media_attachments: Optional[list[str]] = Field(None, max_length=10)
    parent_comment_id: Optional[str] = Field(None, title="Parent Comment ID", description="Include to reply to a comment; id remains the post share ID.")


class EditComment(ProfileResource):
    operation: Literal["edit_comment"] = Field("edit_comment", title="Edit Comment")
    body_text: str = Field(..., min_length=1, title="Comment Text")


class DeleteComment(ProfileResource):
    operation: Literal["delete_comment"] = Field("delete_comment", title="Delete Comment")


class EditPost(ProfileResource):
    operation: Literal["edit_post"] = Field("edit_post", title="Edit Post")
    body_text: Optional[str] = Field(None, max_length=8192, title="Post Text")
    hashtag: Optional[str] = Field(None, pattern=r"^\S+$")
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lon: Optional[float] = Field(None, ge=-180, le=180)
    smartlink_url: Optional[str] = None


class DeletePost(ProfileResource):
    operation: Literal["delete_post"] = Field("delete_post", title="Delete Post")


class ListAgencyBoundaries(BaseModel):
    operation: Literal["list_agency_boundaries"] = Field("list_agency_boundaries", title="List Agency Boundaries")
    show_geometries: bool = Field(True, title="Include Geometries")
    enable_pagination: bool = Field(True, title="Enable Pagination")
    after: Optional[str] = Field(None, title="After Cursor", description="Use the cursor from the preceding response. One page per execution.")


class SetCommenting(BaseModel):
    operation: Literal["set_commenting"] = Field("set_commenting", title="Set Post Commenting")
    id: str = Field(..., min_length=1, title="Post ID")
    comment_status: bool = Field(..., title="Enable Comments")


NextdoorOperation = Annotated[Union[GetAccount, ListProfiles, ListPosts, CreatePost,
    CreateListing, SetListingSold, CreateComment, EditComment, DeleteComment, EditPost,
    DeletePost, ListAgencyBoundaries, SetCommenting, OnNewPost, OnNewComment], Field(discriminator="operation")]


class NextdoorConfig(NodeConfig[NextdoorOperation, NextdoorOAuthCredential]):
    pass


# Each entry corresponds to exactly one operation in the pinned share-api 1.0.
ROUTES = {
    "get_account": ("GET", "/me/", "query"),
    "list_profiles": ("GET", "/me/profiles", "query"),
    "list_posts": ("GET", "/post/", "query"),
    "create_post": ("POST", "/post/create/", "json"),
    "create_listing": ("POST", "/post/fsf/", "json"),
    "set_listing_sold": ("PUT", "/post/fsf/", "json"),
    "create_comment": ("POST", "/comment/", "json"),
    "edit_comment": ("PUT", "/comment/", "json"),
    "delete_comment": ("DELETE", "/comment/", "query"),
    "edit_post": ("PUT", "/post/", "json"),
    "delete_post": ("DELETE", "/post/", "query"),
    "list_agency_boundaries": ("GET", "/agency/boundary/", "query"),
    "set_commenting": ("POST", "/post/toggle_commenting/", "json"),
}


class NextdoorNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-nextdoor"
    scope_registry = NEXTDOOR_SCOPES
    connection_evidence = ConnectionEvidence(noun="Nextdoor account", identity_operation="get_account",
        identity_keys=("business_name", "agency_name", "first_name", "id"))

    @classmethod
    def get_config_model(cls):
        return NextdoorConfig

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") in ("on_new_post", "on_new_comment"):
            return bool(output.get("new_item_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        operation = output.get("operation")
        if operation not in ("on_new_post", "on_new_comment"):
            return super().resolve_agent_event(output)
        items = output["items"]
        if not items:
            return None
        lines = []
        for item in items:
            if operation == "on_new_post":
                lines.append(f"Post {item['id']} by {item.get('author_id')}: {item.get('title') or ''}\n{item.get('body') or ''}\n{item.get('url') or ''}")
            else:
                comment, post = item["comment"], item["post"]
                lines.append(f"Comment {comment['id']} by {comment.get('author_id') or 'unavailable author'} on post {post['id']} ({post.get('url') or ''}), parent comment {comment.get('parent_comment_id')}:\n{comment.get('body') or ''}")
        return {"text": f"Nextdoor: {len(items)} new {'post(s)' if operation == 'on_new_post' else 'comment(s) or replies'}:\n" + "\n".join(lines), "conversation_key": None}

    async def _poll_posts(self, body, operation):
        if not isinstance(body, dict) or not isinstance(body.get("posts"), list):
            raise ValueError("Expected Nextdoor's posts array")
        posts = body["posts"]
        if operation == "on_new_post":
            items = posts
            identify = lambda post: str(post["id"])
        else:
            items = []
            for post in posts:
                comments = post.get("comments", [])
                if not isinstance(comments, list):
                    raise ValueError("Expected Nextdoor's comments array")
                items.extend({"comment": comment, "post": post} for comment in comments)
            identify = lambda item: f"{item['post']['id']}:{item['comment']['id']}"
        fresh = await self._filter_unseen(items, identify)
        return {"status": "success", "operation": operation, "items": fresh, "new_item_count": len(fresh)}

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.nextdoor_oauth import refresh_access_token
        data = dict(credential_data)
        data["refresh_token"] = data.get("refresh_token") or data["access_token"]
        return await freshen_oauth_credential(data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=refresh_access_token, provider="nextdoor")

    async def execute(self, inputs):
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.nextdoor_oauth import refresh_access_token
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Nextdoor account")
        data = credential.model_dump()
        data["refresh_token"] = data.get("refresh_token") or data["access_token"]
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
            credential=data, refresh=refresh_access_token, provider="nextdoor",
            caller_path="execute")
        self.config.credentials = NextdoorOAuthCredential.model_validate(data)
        op = self.config.config
        is_poll = isinstance(op, NextdoorPollConfig)
        method, path, location = ROUTES["list_posts" if is_poll else op.operation]
        payload = ({"secure_profile_id": op.secure_profile_id} if op.secure_profile_id else {}) if is_poll else op.model_dump(exclude={"operation"}, exclude_none=True)
        if location == "query":
            # Arrays use repeated keys and boolean query values use JSON spelling.
            payload = {k: str(v).lower() if isinstance(v, bool) else v for k, v in payload.items()}
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                **({"params": payload} if location == "query" else {"json": payload}))
        if response.is_error or response.is_redirect:
            # Do not echo HTTPX exception URLs/headers or a body containing tokens.
            message = "Nextdoor request failed"
            try:
                error = response.json()
                if isinstance(error, dict):
                    message = str(error.get("message") or error.get("error_description") or error.get("error") or message)
            except ValueError:
                pass
            for secret in (token, data.get("refresh_token")):
                if secret:
                    message = message.replace(secret, "[redacted]")
            raise ValueError(f"Nextdoor HTTP {response.status_code}: {message[:1000]}")
        body = response.json() if response.content else {}
        if not isinstance(body, (dict, list, str)):
            raise ValueError("Expected a Nextdoor JSON object, array or string")
        if is_poll:
            return await self._poll_posts(body, op.operation)
        if isinstance(body, dict) and (body.get("error") or body.get("success") is False or body.get("result") in ("error", "failure")):
            raise ValueError("Nextdoor returned an error response")
        return {"status": "success", "operation": op.operation, "data": body}
