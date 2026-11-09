"""Figma file, comment, library, dev-resource and webhook operations.

Every endpoint here is documented at https://developers.figma.com/docs/rest-api/.
Figma does not allow public OAuth apps to enumerate folders, so file operations
take a file key from its URL rather than presenting a misleading file picker.
"""

import hmac
import json
import secrets

from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.scopes.figma import FIGMA_SCOPES
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase


def _op(name: str, label: str, category: str, **extra: Any) -> Any:
    return Field(name, title=label, json_schema_extra={
        "const": name, "ui:hidden": True, "x-category": category,
        "x-is-trigger": False, "x-display-name": label, **extra,
    })


def _file_key() -> Any:
    return Field(..., title="File Key", description="From a Figma URL: figma.com/design/FILE_KEY/name")


class FigmaOAuthCredential(BaseModel):
    credential_type: Literal["figma_oauth"] = Field("figma_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token")
    refresh_token: Optional[str] = Field(None, title="Refresh Token")
    expires_at: Optional[str] = Field(None, title="Token Expiry")
    user_id: Optional[str] = Field(None, title="User ID")
    model_config = ConfigDict(json_schema_extra={
        "title": "Figma OAuth", "x-credential-type": "oauth", "x-oauth-provider": "figma",
        "x-oauth-scopes": FIGMA_SCOPES.declared_scopes(),
        "x-credential-url": "https://www.figma.com/developers/apps",
    })


class FigmaPATCredential(BaseModel):
    """Personal access token for accounts that cannot use the public OAuth app yet."""

    credential_type: Literal["figma_pat"] = Field("figma_pat", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Personal Access Token", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(json_schema_extra={
        "title": "Figma Personal Access Token",
        "x-credential-url": "https://www.figma.com/settings",
    })


FigmaCredential = Union[FigmaOAuthCredential, FigmaPATCredential]


class GetCurrentUser(BaseModel):
    """Identify the connected Figma user."""
    operation: Literal["get_current_user"] = _op("get_current_user", "Get Current User", "Account")


class GetFile(BaseModel):
    """Read a file document and its layers, optionally at a version or depth."""
    operation: Literal["get_file"] = _op("get_file", "Get File", "Files")
    file_key: str = _file_key()
    depth: Optional[int] = Field(None, ge=1, title="Maximum Tree Depth")
    version: Optional[str] = Field(None, title="Version ID")
    branch_data: bool = Field(False, title="Include Branches")


class GetFileMetadata(BaseModel):
    """Read a file name, URL, thumbnail and recent editor without its layers."""
    operation: Literal["get_file_metadata"] = _op("get_file_metadata", "Get File Metadata", "Files")
    file_key: str = _file_key()


class GetFileNodes(BaseModel):
    """Read selected nodes and their child layers from a file."""
    operation: Literal["get_file_nodes"] = _op("get_file_nodes", "Get File Nodes", "Files")
    file_key: str = _file_key()
    node_ids: str = Field(..., title="Node IDs", description="Comma-separated IDs, for example 1:2,1:3")
    depth: Optional[int] = Field(None, ge=1, title="Maximum Tree Depth")


class RenderImages(BaseModel):
    """Get temporary rendered image URLs for selected nodes."""
    operation: Literal["render_images"] = _op("render_images", "Render Node Images", "Images")
    file_key: str = _file_key()
    node_ids: str = Field(..., title="Node IDs", description="Comma-separated IDs to render")
    format: Literal["png", "jpg", "svg", "pdf"] = Field("png", title="Format")
    scale: float = Field(1, ge=0.01, le=4, title="Scale")


class GetImageFills(BaseModel):
    """Get temporary download URLs for images used as layer fills."""
    operation: Literal["get_image_fills"] = _op("get_image_fills", "Get Image Fills", "Images")
    file_key: str = _file_key()


class ListVersions(BaseModel):
    """List a file’s version history."""
    operation: Literal["list_versions"] = _op("list_versions", "List File Versions", "Files")
    file_key: str = _file_key()


class ListComments(BaseModel):
    """Read comments in a design file."""
    operation: Literal["list_comments"] = _op("list_comments", "List Comments", "Comments")
    file_key: str = _file_key()
    as_md: bool = Field(False, title="Return Markdown")


class CreateComment(BaseModel):
    """Post a comment or reply on a design file."""
    operation: Literal["create_comment"] = _op("create_comment", "Create Comment", "Comments", **{
        "x-creates-resource": True, "x-resource-type": "figma_comment", "x-resource-id-path": "data.id",
    })
    file_key: str = _file_key()
    message: str = Field(..., min_length=1, title="Comment", json_schema_extra={"ui:widget": "textarea"})
    comment_id: Optional[str] = Field(None, title="Reply To Comment ID")


class DeleteComment(BaseModel):
    """Delete a comment you authored."""
    operation: Literal["delete_comment"] = _op("delete_comment", "Delete Comment", "Comments")
    file_key: str = _file_key()
    comment_id: str = Field(..., title="Comment ID")


class ListReactions(BaseModel):
    """List emoji reactions on a comment."""
    operation: Literal["list_reactions"] = _op("list_reactions", "List Comment Reactions", "Comments")
    file_key: str = _file_key()
    comment_id: str = Field(..., title="Comment ID")
    cursor: Optional[str] = Field(None, title="Page Cursor")


class AddReaction(BaseModel):
    """Add an emoji reaction to a comment."""
    operation: Literal["add_reaction"] = _op("add_reaction", "Add Comment Reaction", "Comments")
    file_key: str = _file_key()
    comment_id: str = Field(..., title="Comment ID")
    emoji: str = Field(..., title="Emoji Shortcode", description="For example :heart: or :+1:")


class DeleteReaction(BaseModel):
    """Remove your emoji reaction from a comment."""
    operation: Literal["delete_reaction"] = _op("delete_reaction", "Delete Comment Reaction", "Comments")
    file_key: str = _file_key()
    comment_id: str = Field(..., title="Comment ID")
    emoji: str = Field(..., title="Emoji Shortcode")


class ListFileComponents(BaseModel):
    """List published components in a file library."""
    operation: Literal["list_file_components"] = _op("list_file_components", "List File Components", "Library")
    file_key: str = _file_key()


class ListFileComponentSets(BaseModel):
    """List published component sets in a file library."""
    operation: Literal["list_file_component_sets"] = _op("list_file_component_sets", "List File Component Sets", "Library")
    file_key: str = _file_key()


class ListFileStyles(BaseModel):
    """List published styles in a file library."""
    operation: Literal["list_file_styles"] = _op("list_file_styles", "List File Styles", "Library")
    file_key: str = _file_key()


class ListDevResources(BaseModel):
    """Read links attached to nodes in Dev Mode."""
    operation: Literal["list_dev_resources"] = _op("list_dev_resources", "List Dev Resources", "Dev Resources")
    file_key: str = _file_key()
    node_ids: Optional[str] = Field(None, title="Node IDs")


class CreateDevResource(BaseModel):
    """Attach a URL to a file node as a Dev Mode resource."""
    operation: Literal["create_dev_resource"] = _op("create_dev_resource", "Create Dev Resource", "Dev Resources", **{
        "x-creates-resource": True, "x-resource-type": "figma_dev_resource", "x-resource-id-path": "data.links_created.0.id",
    })
    file_key: str = _file_key()
    node_id: str = Field(..., title="Node ID")
    name: str = Field(..., title="Name")
    url: str = Field(..., title="Resource URL")


class UpdateDevResource(BaseModel):
    """Rename or change the URL of a Dev Mode resource."""
    operation: Literal["update_dev_resource"] = _op("update_dev_resource", "Update Dev Resource", "Dev Resources")
    resource_id: str = Field(..., title="Dev Resource ID")
    name: Optional[str] = Field(None, title="New Name")
    url: Optional[str] = Field(None, title="New URL")


class DeleteDevResource(BaseModel):
    """Remove a Dev Mode resource from a file."""
    operation: Literal["delete_dev_resource"] = _op("delete_dev_resource", "Delete Dev Resource", "Dev Resources")
    file_key: str = _file_key()
    resource_id: str = Field(..., title="Dev Resource ID")


class ListWebhooks(BaseModel):
    """List webhooks attached to a file, project or team."""
    operation: Literal["list_webhooks"] = _op("list_webhooks", "List Webhooks", "Webhooks")
    context: Literal["team", "project", "file"] = Field(..., title="Context")
    context_id: str = Field(..., title="Context ID")


class GetWebhook(BaseModel):
    """Read a webhook subscription and its status."""
    operation: Literal["get_webhook"] = _op("get_webhook", "Get Webhook", "Webhooks")
    webhook_id: str = Field(..., title="Webhook ID")


WebhookEvent = Literal[
    "FILE_UPDATE", "FILE_DELETE", "FILE_VERSION_UPDATE", "LIBRARY_PUBLISH",
    "FILE_COMMENT", "DEV_MODE_STATUS_UPDATE", "PING",
]


class CreateWebhook(BaseModel):
    """Subscribe a URL to an event for a file, project or team."""
    operation: Literal["create_webhook"] = _op("create_webhook", "Create Webhook", "Webhooks", **{
        "x-creates-resource": True, "x-resource-type": "figma_webhook", "x-resource-id-path": "data.id",
    })
    event_type: WebhookEvent = Field(..., title="Event Type")
    context: Literal["team", "project", "file"] = Field(..., title="Context")
    context_id: str = Field(..., title="Context ID")
    endpoint: str = Field(..., title="Webhook URL")
    passcode: str = Field(..., title="Verification Passcode")
    description: Optional[str] = Field(None, title="Description")


class UpdateWebhook(BaseModel):
    """Change a webhook endpoint, event, passcode or status."""
    operation: Literal["update_webhook"] = _op("update_webhook", "Update Webhook", "Webhooks")
    webhook_id: str = Field(..., title="Webhook ID")
    event_type: Optional[WebhookEvent] = Field(None, title="Event Type")
    endpoint: Optional[str] = Field(None, title="Webhook URL")
    passcode: Optional[str] = Field(None, title="Verification Passcode")
    status: Optional[Literal["ACTIVE", "PAUSED"]] = Field(None, title="Status")
    description: Optional[str] = Field(None, title="Description")


class DeleteWebhook(BaseModel):
    """Remove a webhook subscription."""
    operation: Literal["delete_webhook"] = _op("delete_webhook", "Delete Webhook", "Webhooks")
    webhook_id: str = Field(..., title="Webhook ID")


class FigmaOnEventConfig(WebhookTriggerConfigBase):
    """Start when a design changes, a comment arrives, or a library is published.

    https://developers.figma.com/docs/rest-api/webhooks-events/
    """
    operation: Literal["on_event"] = _op("on_event", "On Figma Event", "Triggers", **{"x-is-trigger": True})
    event_type: Literal[
        "FILE_UPDATE", "FILE_DELETE", "FILE_VERSION_UPDATE", "FILE_COMMENT",
        "LIBRARY_PUBLISH", "DEV_MODE_STATUS_UPDATE",
    ] = Field("FILE_COMMENT", title="Event Type")
    context: Literal["file", "project", "team"] = Field("file", title="Context")
    context_id: str = Field(..., min_length=1, title="Context ID", description="File key, project ID, or team ID from its Figma URL")
    webhook_url: Optional[str] = Field(None, title="Webhook URL", description="Registered with Figma automatically",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})


FigmaConfig = Annotated[Union[
    GetCurrentUser, GetFile, GetFileMetadata, GetFileNodes, RenderImages,
    GetImageFills, ListVersions, ListComments, CreateComment, DeleteComment,
    ListReactions, AddReaction, DeleteReaction, ListFileComponents,
    ListFileComponentSets, ListFileStyles, ListDevResources, CreateDevResource,
    UpdateDevResource, DeleteDevResource, ListWebhooks, GetWebhook,
    CreateWebhook, UpdateWebhook, DeleteWebhook, FigmaOnEventConfig,
], Discriminator("operation")]


class FigmaNodeConfig(NodeConfig[FigmaConfig, FigmaCredential]):
    pass


class FigmaNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-figma"
    credential_provider_labels = {"figma": "Figma Account"}
    connection_evidence = ConnectionEvidence(
        operation="get_current_user", noun="account", identity_operation="get_current_user")
    scope_registry = FIGMA_SCOPES
    edit_examples = [
        "Read a Figma file", "Render a Figma frame", "Post a comment on a design",
        "Link a Jira issue as a Figma dev resource", "List design system components",
    ]

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        op = FigmaOnEventConfig.model_validate(config)
        token = credential.get("access_token")
        if not token:
            raise ValueError("Connect Figma before activating this trigger")
        passcode = secrets.token_urlsafe(32)
        data = await cls._request(token, "POST", "/v2/webhooks", body={
            "event_type": op.event_type, "context": op.context, "context_id": op.context_id,
            "endpoint": webhook_url, "passcode": passcode,
        }, personal_token=credential.get("credential_type") == "figma_pat")
        if not data.get("id"):
            raise ValueError("Figma did not return a webhook ID")
        return {"external_webhook_id": str(data["id"]), "signing_secret": passcode}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        webhook_id = (config or {}).get("external_webhook_id")
        if not webhook_id or not credential:
            return
        await cls._request(credential["access_token"], "DELETE",
            f"/v2/webhooks/{quote(str(webhook_id), safe='')}",
            personal_token=credential.get("credential_type") == "figma_pat")

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {key: (config or {}).get(key) for key in ("event_type", "context", "context_id")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        # Figma returns the registration passcode in the body; it does not sign it.
        secret = (config or {}).get("signing_secret")
        if not secret:
            return False
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            return False
        passcode = payload.get("passcode") if isinstance(payload, dict) else None
        return isinstance(passcode, str) and hmac.compare_digest(passcode.encode(), str(secret).encode())

    @classmethod
    async def handle_control_event(cls, payload, config, *, pool, workflow_id, node_id):
        return "Figma webhook connected" if payload.get("event_type") == "PING" else None

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return payload.get("event_type") == config.get("event_type", "FILE_COMMENT")

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        # The passcode authenticates delivery and must not become agent context.
        return {key: value for key, value in payload.items() if key not in ("passcode", "_webhook")}

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict):
            return None
        event = output["data"] if "data" in output and isinstance(output["data"], dict) else output
        kind = event.get("event_type")
        if kind not in ("FILE_UPDATE", "FILE_DELETE", "FILE_VERSION_UPDATE", "FILE_COMMENT", "LIBRARY_PUBLISH", "DEV_MODE_STATUS_UPDATE"):
            return None
        file_key = event.get("file_key")
        name = event.get("file_name") or file_key
        lines = [f"Figma {kind.replace('_', ' ').lower()}: {name}"]
        if kind != "FILE_UPDATE":
            actor = event.get("triggered_by") or {}
            if actor:
                lines.append(f"By: {actor.get('handle')} (user_id={actor.get('id')})")
        lines.extend([f"File: https://www.figma.com/file/{quote(str(file_key), safe='')}",
                      f"file_key={file_key}", f"At: {event.get('timestamp')}"])
        if kind == "FILE_COMMENT":
            content = "".join(part.get("text", "") if "text" in part else f"@{part['mention']}" for part in event.get("comment", []))
            lines.extend([f"Comment: {content}", f"comment_id={event.get('comment_id')}",
                          f"Reply with create_comment file_key={file_key} comment_id={event.get('comment_id')}."])
        elif kind == "FILE_VERSION_UPDATE":
            lines.extend([f"version_id={event.get('version_id')}", str(event.get("description") or "")])
        elif kind == "DEV_MODE_STATUS_UPDATE":
            lines.extend([f"node_id={event.get('node_id')}", f"Status: {event.get('status')}"])
        elif kind == "LIBRARY_PUBLISH":
            lines.append(str(event.get("description") or ""))
            for change in ("created", "modified", "deleted"):
                for asset in ("components", "styles", "variables"):
                    key = f"{change}_{asset}"
                    items = event.get(key) or []
                    if items:
                        lines.append(f"{key}: " + json.dumps(items, ensure_ascii=False))
        return {"text": "\n".join(lines), "conversation_key": str(file_key), "title": str(name)}

    @classmethod
    def get_config_model(cls):
        return FigmaNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        from nodes.oauth.figma_oauth import refresh_access_token
        if not credential_data.get("refresh_token"):
            return credential_data
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh_access_token, provider="figma")

    async def _token(self, credential: FigmaCredential) -> str:
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        from nodes.oauth.figma_oauth import refresh_access_token
        data = credential.model_dump()
        if isinstance(credential, FigmaOAuthCredential) and data.get("refresh_token"):
            await ensure_fresh_oauth_token(
                credential_id=(self.node_data or {}).get("credential_id"), user_id=self.user_id,
                credential=data, refresh=refresh_access_token, provider="figma", caller_path="execute")
        if isinstance(credential, FigmaOAuthCredential):
            for key in ("access_token", "refresh_token", "expires_at"):
                setattr(credential, key, data.get(key))
        return data["access_token"]

    @staticmethod
    async def _request(token: str, method: str, path: str, *, params=None, body=None,
                       personal_token: bool = False) -> Any:
        params = {key: value for key, value in (params or {}).items() if value is not None}
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.request(
                method, f"https://api.figma.com{path}", params=params, json=body,
                headers={"X-Figma-Token": token} if personal_token else
                {"Authorization": f"Bearer {token}"})
        if response.is_error:
            try:
                data = response.json()
                detail = data.get("message") or data.get("err") or data.get("error")
                if isinstance(detail, dict):
                    detail = detail.get("message")
            except (ValueError, AttributeError):
                detail = None
            raise ValueError(f"Figma API error {response.status_code}: {detail or 'request failed'}")
        return response.json() if response.content else {"ok": True}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, FigmaNodeConfig):
            raise ValueError("Figma configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Figma account")
        op = self.config.config
        name = op.operation
        self.scope_registry.require(name)
        if isinstance(op, FigmaOnEventConfig):
            return self.resolve_trigger_payload(inputs, op.model_dump())
        token = await self._token(credential)
        method, path, params, body = "GET", "", None, None
        file = f"/v1/files/{quote(op.file_key, safe='')}" if hasattr(op, "file_key") else ""
        comment_id = getattr(op, "comment_id", None)
        comment = f"{file}/comments/{quote(comment_id, safe='')}" if comment_id else ""
        webhook_id = getattr(op, "webhook_id", None)
        webhook = f"/v2/webhooks/{quote(webhook_id, safe='')}" if webhook_id else ""

        if isinstance(op, GetCurrentUser):
            path = "/v1/me"
        elif isinstance(op, GetFile):
            path, params = file, {"depth": op.depth, "version": op.version, "branch_data": str(op.branch_data).lower()}
        elif isinstance(op, GetFileMetadata):
            path = f"{file}/meta"
        elif isinstance(op, GetFileNodes):
            path, params = f"{file}/nodes", {"ids": op.node_ids, "depth": op.depth}
        elif isinstance(op, RenderImages):
            path, params = f"/v1/images/{quote(op.file_key, safe='')}", {
                "ids": op.node_ids, "format": op.format, "scale": op.scale}
        elif isinstance(op, GetImageFills):
            path = f"{file}/images"
        elif isinstance(op, ListVersions):
            path = f"{file}/versions"
        elif isinstance(op, ListComments):
            path, params = f"{file}/comments", {"as_md": str(op.as_md).lower()}
        elif isinstance(op, CreateComment):
            method, path, body = "POST", f"{file}/comments", {"message": op.message}
            if op.comment_id:
                body["comment_id"] = op.comment_id
        elif isinstance(op, DeleteComment):
            method, path = "DELETE", comment
        elif isinstance(op, ListReactions):
            path, params = f"{comment}/reactions", {"cursor": op.cursor}
        elif isinstance(op, AddReaction):
            method, path, body = "POST", f"{comment}/reactions", {"emoji": op.emoji}
        elif isinstance(op, DeleteReaction):
            method, path, params = "DELETE", f"{comment}/reactions", {"emoji": op.emoji}
        elif isinstance(op, ListFileComponents):
            path = f"{file}/components"
        elif isinstance(op, ListFileComponentSets):
            path = f"{file}/component_sets"
        elif isinstance(op, ListFileStyles):
            path = f"{file}/styles"
        elif isinstance(op, ListDevResources):
            path, params = f"{file}/dev_resources", {"node_ids": op.node_ids}
        elif isinstance(op, CreateDevResource):
            method, path, body = "POST", "/v1/dev_resources", {"dev_resources": [{
                "file_key": op.file_key, "node_id": op.node_id, "name": op.name, "url": op.url}]}
        elif isinstance(op, UpdateDevResource):
            item = op.model_dump(exclude={"operation", "resource_id"}, exclude_none=True)
            if not item:
                raise ValueError("Provide a name or URL to update")
            method, path, body = "PUT", "/v1/dev_resources", {"dev_resources": [{"id": op.resource_id, **item}]}
        elif isinstance(op, DeleteDevResource):
            method, path = "DELETE", f"{file}/dev_resources/{quote(op.resource_id, safe='')}"
        elif isinstance(op, ListWebhooks):
            path, params = "/v2/webhooks", {"context": op.context, "context_id": op.context_id}
        elif isinstance(op, GetWebhook):
            path = webhook
        elif isinstance(op, CreateWebhook):
            method, path = "POST", "/v2/webhooks"
            body = op.model_dump(exclude={"operation"}, exclude_none=True)
        elif isinstance(op, UpdateWebhook):
            body = op.model_dump(exclude={"operation", "webhook_id"}, exclude_none=True)
            if not body:
                raise ValueError("Provide a webhook field to update")
            method, path = "PUT", webhook
        elif isinstance(op, DeleteWebhook):
            method, path = "DELETE", webhook
        else:
            raise ValueError(f"Unsupported Figma operation: {name}")

        data = await self._request(
            token, method, path, params=params, body=body,
            personal_token=isinstance(credential, FigmaPATCredential))
        # Figma returns HTTP 200 even when dev-resource batches contain errors.
        if isinstance(op, (CreateDevResource, UpdateDevResource)) and data.get("errors"):
            raise ValueError(f"Figma dev resource errors: {data['errors']}")
        return {"status": "success", "operation": name, "data": data}
