"""Zulip REST operations using a user's email and API key.

Each operation makes one request. Message history returns one anchor window;
callers choose the next anchor explicitly. Mutations are never retried.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class ZulipAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Zulip API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://zulip.com/api/api-keys",
        "x-credential-instructions": "In Zulip, open Personal settings > Account & privacy and copy your API key. Paste the email that owns that key and your organization's HTTPS URL. Bot email and API key pairs also work, subject to the bot's permissions. NoClick uses HTTP Basic authentication and reads your subscribed channels to check the connection.",
    })
    credential_type: Literal["zulip_api_key"] = Field("zulip_api_key", json_schema_extra={"ui:hidden": True})
    server_url: str = Field(..., title="Zulip server URL", description="Organization origin, e.g. https://example.zulipchat.com. Public HTTPS self-hosted servers are supported.")
    email: str = Field(..., min_length=3, max_length=254, title="Account email")
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("server_url", mode="before")
    @classmethod
    def server(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your organization's HTTPS origin")
        value = value.strip().rstrip("/")
        try:
            parts = urlsplit(value)
            host = parts.hostname or ""
            if (parts.scheme != "https" or parts.username is not None or parts.password is not None
                    or parts.port not in {None, 443} or parts.path or parts.query or parts.fragment
                    or len(host) > 253 or "." not in host or host.endswith(".")
                    or not all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in host.split("."))
                    or all(c.isdigit() or c == "." for c in host)):
                raise ValueError()
        except ValueError:
            raise ValueError("Use a public HTTPS organization origin without a path, query or credentials") from None
        return "https://" + host.lower()

    @field_validator("email", mode="before")
    @classmethod
    def account_email(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"[^\s:@]+@[^\s:@]+\.[^\s:@]+", value.strip()):
            raise ValueError("Paste the email that owns the API key")
        return value.strip()

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without whitespace")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


Identifier = Annotated[int, Field(gt=0, strict=True)]
Text = Annotated[str, Field(min_length=1, max_length=10000)]
Content = Annotated[str, Field(min_length=1, max_length=100000)]


class GetOwnUser(_Config):
    """Read the account authenticated by the API key."""
    operation: Literal["get_own_user"] = "get_own_user"


class ListUsers(_Config):
    """List users visible to this account."""
    operation: Literal["list_users"] = "list_users"


class GetUser(_Config):
    """Read one user by numeric ID."""
    operation: Literal["get_user"] = "get_user"
    user_id: Identifier


class ListChannels(_Config):
    """List accessible public and subscribed channels."""
    operation: Literal["list_channels"] = "list_channels"


class ListSubscriptions(_Config):
    """List the current account's subscribed channels."""
    operation: Literal["list_subscriptions"] = "list_subscriptions"


class ListTopics(_Config):
    """List topics in a channel accessible to the current account."""
    operation: Literal["list_topics"] = "list_topics"
    stream_id: Identifier = Field(..., title="Channel ID")


class Narrow(_Config):
    operator: Text = Field(..., description="Zulip narrow operator, e.g. channel, topic, sender or search.")
    operand: Text


class GetMessages(_Config):
    """Read one message window; use first/last returned IDs as later anchors."""
    operation: Literal["get_messages"] = "get_messages"
    anchor: Union[Identifier, Literal["newest", "oldest", "first_unread"]] = "newest"
    num_before: int = Field(100, ge=0, le=1000)
    num_after: int = Field(0, ge=0, le=1000)
    narrow: list[Narrow] = Field(default_factory=list, max_length=20)


class GetMessage(_Config):
    """Read a single message visible to the account."""
    operation: Literal["get_message"] = "get_message"
    message_id: Identifier


class SendMessage(_Config):
    """Send a channel or direct message. Server permissions and length limits apply."""
    operation: Literal["send_message"] = "send_message"
    type: Literal["direct", "channel"] = Field("direct", title="Message type")
    to: Union[Identifier, Text, list[Identifier], list[Text]] = Field(..., description="Channel name/ID, or a list of user IDs or API email addresses for direct messages.")
    content: Content
    topic: Text | None = Field(None, description="Required for a channel message.")

    @model_validator(mode="after")
    def destination(self):
        if self.type == "channel" and (isinstance(self.to, list) or self.topic is None):
            raise ValueError("A channel message needs one channel and a topic")
        if self.type == "direct" and (not isinstance(self.to, list) or not self.to or len(self.to) > 100):
            raise ValueError("A direct message needs a nonempty list of at most 100 users")
        return self


class UpdateMessage(_Config):
    """Edit only this message's content, without moving messages or topics."""
    operation: Literal["update_message"] = "update_message"
    message_id: Identifier
    content: Content


class DeleteMessage(_Config):
    """Delete a message when the account and organization permit it."""
    operation: Literal["delete_message"] = "delete_message"
    message_id: Identifier


class AddReaction(_Config):
    """Add the account's emoji reaction."""
    operation: Literal["add_reaction"] = "add_reaction"
    message_id: Identifier
    emoji_name: Text


class RemoveReaction(_Config):
    """Remove the account's emoji reaction."""
    operation: Literal["remove_reaction"] = "remove_reaction"
    message_id: Identifier
    emoji_name: Text


class Subscription(_Config):
    name: Text
    description: str | None = Field(None, max_length=10000)


class Subscribe(_Config):
    """Subscribe yourself to channels, creating missing channels if permitted."""
    operation: Literal["subscribe"] = "subscribe"
    subscriptions: list[Subscription] = Field(..., min_length=1, max_length=100)


class Unsubscribe(_Config):
    """Unsubscribe yourself from the named channels."""
    operation: Literal["unsubscribe"] = "unsubscribe"
    subscriptions: list[Text] = Field(..., min_length=1, max_length=100)


class RenderMessage(_Config):
    """Render Zulip Markdown without sending a message."""
    operation: Literal["render_message"] = "render_message"
    content: Content


ZulipConfig = Annotated[Union[GetOwnUser, ListUsers, GetUser, ListChannels, ListSubscriptions,
    ListTopics, GetMessages, GetMessage, SendMessage, UpdateMessage, DeleteMessage,
    AddReaction, RemoveReaction, Subscribe, Unsubscribe, RenderMessage], Field(discriminator="operation")]


class ZulipNodeConfig(NodeConfig[ZulipConfig, ZulipAPIKeyCredential]):
    pass


# Fixed method/path pairs from the pinned Zulip OpenAPI contract.
ROUTES = {
    "get_own_user": ("GET", "/users/me"),
    "list_users": ("GET", "/users"),
    "get_user": ("GET", "/users/{user_id}"),
    "list_channels": ("GET", "/streams"),
    "list_subscriptions": ("GET", "/users/me/subscriptions"),
    "list_topics": ("GET", "/users/me/{stream_id}/topics"),
    "get_messages": ("GET", "/messages"),
    "get_message": ("GET", "/messages/{message_id}"),
    "send_message": ("POST", "/messages"),
    "update_message": ("PATCH", "/messages/{message_id}"),
    "delete_message": ("DELETE", "/messages/{message_id}"),
    "add_reaction": ("POST", "/messages/{message_id}/reactions"),
    "remove_reaction": ("DELETE", "/messages/{message_id}/reactions"),
    "subscribe": ("POST", "/users/me/subscriptions"),
    "unsubscribe": ("DELETE", "/users/me/subscriptions"),
    "render_message": ("POST", "/messages/render"),
}
RESULT_KEYS = {"list_users": "members", "get_user": "user", "list_channels": "streams",
    "list_subscriptions": "subscriptions", "list_topics": "topics", "get_messages": "messages", "get_message": "message"}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secret) for key, item in value.items() if key not in {"api_key", "password", "authorization"}}
    return value


class ZulipNode(WorkflowNode):
    integration_type = "automation-zulip"
    connection_evidence = ConnectionEvidence(noun="subscribed channels", operation="list_subscriptions",
        identity_operation="get_own_user", label_keys=("name", "stream_id"), identity_keys=("full_name", "email", "user_id"))

    @classmethod
    def get_config_model(cls):
        return ZulipNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Zulip email and API key")
        credential = self.config.credentials
        config = self.config.config
        operation = config.operation
        method, route = ROUTES[operation]
        values = config.model_dump(exclude={"operation"}, exclude_none=True)
        for name in ("user_id", "message_id", "stream_id"):
            if "{" + name + "}" in route:
                route = route.replace("{" + name + "}", str(values.pop(name)))
        # Zulip's form encoding uses JSON for structured and numeric parameters.
        values = {key: json.dumps(value, ensure_ascii=False, separators=(",", ":")) if key == "to" or isinstance(value, (dict, list, bool, int)) else value for key, value in values.items()}
        mutating = method != "GET" and operation != "render_message"
        status = None
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, credential.server_url + "/api/v1" + route,
                    auth=httpx.BasicAuth(credential.email, credential.api_key),
                    headers={"Accept": "application/json"},
                    **({"params": values} if method == "GET" else {"data": values} if values else {}))
            status = response.status_code
            try:
                body = response.json()
            except ValueError:
                raise ValueError("Zulip returned a non-JSON response; check the server URL") from None
            if not isinstance(body, dict):
                raise ValueError("Zulip returned an unexpected response")
            if status != 200 or body.get("result") != "success":
                message = body.get("msg")
                output = {"status": "unknown" if mutating and status >= 500 else "error", "success": False,
                    "operation": operation, "http_status": status,
                    "message": message if isinstance(message, str) and message else "Zulip did not confirm the request"}
            else:
                if body.get("ignored_parameters_unsupported"):
                    raise ValueError("Zulip ignored unsupported parameters; the requested result is unverified")
                if not isinstance(body.get("msg"), str):
                    raise ValueError("Zulip response is missing its acknowledgement message")
                if operation == "subscribe" and not all(isinstance(body.get(k), dict) for k in ("subscribed", "already_subscribed")):
                    raise ValueError("Zulip response is missing subscription results")
                if operation == "unsubscribe" and not all(isinstance(body.get(k), list) for k in ("removed", "not_removed")):
                    raise ValueError("Zulip response is missing unsubscription results")
                key = RESULT_KEYS.get(operation)
                if key and not isinstance(body.get(key), dict if operation in {"get_user", "get_message"} else list):
                    raise ValueError("Zulip response is missing the documented result")
                if operation == "get_own_user" and (type(body.get("user_id")) is not int or not isinstance(body.get("full_name"), str)):
                    raise ValueError("Zulip response is missing the account identity")
                if operation == "send_message" and type(body.get("id")) is not int:
                    raise ValueError("Zulip did not return the sent message ID")
                if operation == "render_message" and not isinstance(body.get("rendered"), str):
                    raise ValueError("Zulip did not return rendered content")
                output = {"status": "success", "success": True, "operation": operation,
                    "http_status": status, "data": body[key] if key else body,
                    "response": body, "write_acknowledged": mutating}
        except (httpx.HTTPError, ValueError) as exc:
            output = {"status": "unknown" if mutating else "error", "success": False,
                "operation": operation, "http_status": status,
                "message": str(exc) if isinstance(exc, ValueError) else "Zulip request failed; inspect before retrying a write"}
        output = _redact(output, credential.api_key)
        await self.emit(output)
        return output
