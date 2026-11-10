"""Gotify REST API 2.1.0 (server v3.1.1), using a manually supplied client token.

Contract: https://raw.githubusercontent.com/gotify/server/v3.1.1/docs/spec.json
Message history is newest first (database/message.go); `since` pages backwards,
not forwards. Polling snapshots at most 4,000 retained messages, failing before
advancing state if the history exceeds that bound. Deleted messages cannot fire.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client


class GotifyClientToken(BaseModel):
    model_config = ConfigDict(title="Gotify Client Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://gotify.net/docs/api-docs",
            "x-credential-instructions": "Enter your public HTTPS Gotify server URL and an existing client token (not an application token). Obtain a client token with POST /client using the Gotify API. NoClick checks access by listing your applications. Some administrative actions require session elevation on Gotify 3. Sending a message requires an application ID owned by your account.",
        })
    credential_type: Literal["gotify_client_token"] = Field("gotify_client_token", json_schema_extra={"ui:hidden": True})
    server_url: str = Field(..., title="Server URL", description="Public HTTPS server URL, including a reverse-proxy path prefix if used.")
    client_token: str = Field(..., min_length=1, max_length=4096, title="Client token", json_schema_extra={"ui:widget": "password"})

    @field_validator("server_url")
    @classmethod
    def server(cls, value):
        value = value.strip().rstrip("/")
        try:
            parts = urlsplit(value)
            port = parts.port
        except ValueError:
            raise ValueError("Enter a public HTTPS Gotify server URL") from None
        if (parts.scheme != "https" or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.query or parts.fragment
                or "\\" in value or any(c.isspace() or ord(c) < 32 for c in value)
                or any(p in {".", ".."} for p in parts.path.split("/"))
                or "%" in parts.path):
            raise ValueError("Enter an HTTPS server URL without login details, query or fragment")
        return urlunsplit(("https", ("[" + parts.hostname.lower() + "]" if ":" in parts.hostname else parts.hostname.lower()) + (f":{port}" if port else ""), parts.path, "", ""))

    @field_validator("client_token")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Client token", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the client token without a header or spaces")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Page(_Input):
    limit: int = Field(100, ge=1, le=200, description="Maximum messages in this page.")
    since: int | None = Field(None, ge=0, description="Return IDs LESS than this value: this fetches older messages, not newer ones. Use paging.since from a prior page.")


class _ApplicationId(_Input):
    application_id: int = Field(..., ge=1, title="Application ID")


class _ApplicationBody(_Input):
    name: str = Field(..., min_length=1, title="Application name")
    description: str | None = None
    defaultPriority: int | None = Field(None, title="Default priority")
    sortKey: str | None = Field(None, title="Sort key", description="Gotify fractional indexing key.")


class _ApplicationUpdate(_ApplicationBody, _ApplicationId):
    pass


class _ApplicationPage(_Page, _ApplicationId):
    pass


class _SendMessage(_Input):
    appid: int = Field(..., ge=1, title="Application ID", description="An application owned by the client token's account; required for client-token authentication.")
    message: str = Field(..., min_length=1, description="Message text; Markdown is supported.")
    title: str | None = None
    priority: int | None = None
    extras: dict[str, Any] | None = Field(None, description="Gotify message extras, sent as JSON.")


class _MessageId(_Input):
    message_id: int = Field(..., ge=1)


class _ClientId(_Input):
    client_id: int = Field(..., ge=1)


class _ClientBody(_Input):
    name: str = Field(..., min_length=1, title="Client name")
    expiresAfterInactivitySeconds: int | None = Field(None, ge=0, title="Expire after inactivity (seconds)", description="0 means never expire.")


class _ClientUpdate(_ClientBody, _ClientId):
    pass


class _PluginId(_Input):
    plugin_id: int = Field(..., ge=1)


# Every action is one contract operation, including the poll's underlying GET.
# operation -> method, route, config base, path parameter, body fields, shape
OPERATIONS = {
    "send_message": ("POST", "/message", _SendMessage, None, ("appid", "message", "title", "priority", "extras"), "object"),
    "list_messages": ("GET", "/message", _Page, None, (), "messages"),
    "delete_message": ("DELETE", "/message/{id}", _MessageId, "message_id", (), "empty"),
    "delete_all_messages": ("DELETE", "/message", _Input, None, (), "empty"),
    "list_applications": ("GET", "/application", _Input, None, (), "array"),
    "create_application": ("POST", "/application", _ApplicationBody, None, ("name", "description", "defaultPriority", "sortKey"), "object"),
    "update_application": ("PUT", "/application/{id}", _ApplicationUpdate, "application_id", ("name", "description", "defaultPriority", "sortKey"), "object"),
    "delete_application": ("DELETE", "/application/{id}", _ApplicationId, "application_id", (), "empty"),
    "remove_application_image": ("DELETE", "/application/{id}/image", _ApplicationId, "application_id", (), "empty"),
    "list_application_messages": ("GET", "/application/{id}/message", _ApplicationPage, "application_id", (), "messages"),
    "delete_application_messages": ("DELETE", "/application/{id}/message", _ApplicationId, "application_id", (), "empty"),
    "list_clients": ("GET", "/client", _Input, None, (), "array"),
    "create_client": ("POST", "/client", _ClientBody, None, ("name", "expiresAfterInactivitySeconds"), "object"),
    "update_client": ("PUT", "/client/{id}", _ClientUpdate, "client_id", ("name", "expiresAfterInactivitySeconds"), "object"),
    "delete_client": ("DELETE", "/client/{id}", _ClientId, "client_id", (), "empty"),
    "list_plugins": ("GET", "/plugin", _Input, None, (), "array"),
    "get_current_user": ("GET", "/current/user", _Input, None, (), "object"),
    "enable_plugin": ("POST", "/plugin/{id}/enable", _PluginId, "plugin_id", (), "empty"),
    "disable_plugin": ("POST", "/plugin/{id}/disable", _PluginId, "plugin_id", (), "empty"),
}

CONFIG_MODELS = {}
for _name, (_method, _route, _base, _path, _body, _shape) in OPERATIONS.items():
    _model_name = "Gotify" + "".join(word.title() for word in _name.split("_")) + "Config"
    _model = create_model(_model_name, __base__=_base, __module__=__name__,
        operation=(Literal[_name], Field(_name, title=_name.replace("_", " ").title(),
            json_schema_extra={"ui:hidden": True})))
    CONFIG_MODELS[_name] = _model
    globals()[_model_name] = _model


class GotifyOnNewMessageConfig(PollTriggerConfigBase):
    """Poll retained message history; first run baselines. Requires at most 4,000 retained messages. Messages deleted between polls cannot fire."""
    operation: Literal["on_new_message"] = Field("on_new_message", title="On New Message",
        json_schema_extra={"ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True})


GotifyConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (GotifyOnNewMessageConfig,)], Field(discriminator="operation")]


class GotifyNodeConfig(NodeConfig[GotifyConfig, GotifyClientToken]):
    pass


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()}
    return value


class GotifyNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-gotify"
    connection_evidence = ConnectionEvidence(noun="applications", operation="list_applications", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return GotifyNodeConfig

    @staticmethod
    async def _request(credential, method, route, *, params=None, body=None, shape="object"):
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False) as client:
                response = await client.request(method, credential.server_url + route,
                    headers={"X-Gotify-Key": credential.client_token, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
        except Exception:
            raise ValueError("Gotify request could not be completed; inspect the server before retrying a write") from None
        if not 200 <= response.status_code < 300:
            try:
                error = response.json()
                text = error.get("errorDescription") or error.get("error") if isinstance(error, dict) else None
            except Exception:
                text = None
            text = _redact(str(text), credential.client_token)[:1000] if text else "Request rejected"
            raise ValueError(f"Gotify HTTP {response.status_code}: {text}")
        if shape == "empty":
            return {"acknowledged": True}
        try:
            result = response.json()
        except Exception:
            raise ValueError("Gotify returned an unexpected non-JSON response") from None
        if (shape == "array" and (not isinstance(result, list) or any(not isinstance(row, dict) for row in result))
                or shape in {"object", "messages"} and not isinstance(result, dict)):
            raise ValueError("Gotify returned an unexpected response shape")
        if shape == "messages":
            if not isinstance(result.get("messages"), list) or not isinstance(result.get("paging"), dict):
                raise ValueError("Gotify returned an invalid message page")
            for row in result["messages"]:
                if (not isinstance(row, dict) or type(row.get("id")) is not int
                        or type(row.get("appid")) is not int or not isinstance(row.get("message"), str)
                        or not isinstance(row.get("date"), str)):
                    raise ValueError("Gotify returned an invalid message")
        # Existing credentials never escape, including if echoed in an error or message.
        # Newly issued application/client tokens are deliberately returned by create operations.
        return _redact(result, credential.client_token)

    async def _poll(self, credential):
        messages, since, seen = [], None, set()
        for _ in range(20):
            params = {"limit": 200}
            if since is not None:
                params["since"] = since
            page = await self._request(credential, "GET", "/message", params=params, shape="messages")
            rows = page["messages"]
            if len(rows) > 200:
                raise ValueError("Gotify exceeded the requested page limit")
            for row in rows:
                if row["id"] in seen or since is not None and row["id"] >= since:
                    raise ValueError("Gotify message pagination did not advance")
                seen.add(row["id"])
            messages.extend(rows)
            if len(rows) < 200 or not page["paging"].get("next"):
                break
            since = min(row["id"] for row in rows)
        else:
            raise ValueError("Gotify history exceeds 4,000 messages; reduce retained history before enabling this trigger")
        fresh = await self._filter_unseen(sorted(messages, key=lambda row: row["id"]), lambda row: str(row["id"]))
        return {"messages": fresh, "new_message_count": len(fresh)}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Gotify client token")
        config, credential = self.config.config, self.config.credentials
        if config.operation == "on_new_message":
            return await self._poll(credential)
        method, route, _, path_field, fields, shape = OPERATIONS[config.operation]
        if path_field:
            route = route.replace("{id}", str(getattr(config, path_field)))
        body = {key: getattr(config, key) for key in fields if getattr(config, key) is not None} if fields else None
        params = {key: getattr(config, key) for key in ("limit", "since") if getattr(config, key, None) is not None}
        data = await self._request(credential, method, route, params=params or None, body=body, shape=shape)
        # Token-bearing list responses are useful metadata, not a credential-export API.
        if config.operation in {"list_applications", "list_clients", "list_plugins"}:
            data = [{k: v for k, v in row.items() if k != "token"} for row in data]
        return {"status": "success", "data": data}

    @classmethod
    def resolve_agent_event(cls, output):
        messages = output.get("messages") if isinstance(output, dict) else None
        if not isinstance(messages, list):
            return super().resolve_agent_event(output)
        if not messages:
            return None
        lines = [f"- Application {row['appid']} sent {row.get('title') or 'a notification'} at {row['date']}: {row['message']} (message ID {row['id']})" for row in messages[:10]]
        if len(messages) > 10:
            lines.append(f"- {len(messages) - 10} more messages are in the trigger output")
        return {"text": f"Gotify received {len(messages)} new message(s):\n" + "\n".join(lines), "conversation_key": None}
