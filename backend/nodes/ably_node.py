"""Ably Pub/Sub, presence, push, and application operations over its REST API."""

import json
import re
import time
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote, urljoin

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field, create_model

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence


API_BASE = "https://rest.ably.io"
# Operation definitions from the Ably REST reference linked by each action.
OPERATIONS: dict[str, dict[str, Any]] = {
    operation["name"]: operation
    for operation in [
        {
            "name": "publish_message",
            "label": "Publish message",
            "category": "Messages",
            "method": "POST",
            "path": "/channels/{channelId}/messages",
            "docs": "https://ably.com/docs/api/rest-api#publish",
            "body_required": True,
        },
        {
            "name": "get_message_history",
            "label": "Get message history",
            "category": "Messages",
            "method": "GET",
            "path": "/channels/{channelId}/messages",
            "docs": "https://ably.com/docs/api/rest-api#message-history",
            "body_required": False,
        },
        {
            "name": "get_message",
            "label": "Get message",
            "category": "Messages",
            "method": "GET",
            "path": "/channels/{channelId}/messages/{serial}",
            "docs": "https://ably.com/docs/api/rest-api#get-message",
            "body_required": False,
        },
        {
            "name": "update_message",
            "label": "Update or delete message",
            "category": "Messages",
            "method": "PATCH",
            "path": "/channels/{channelId}/messages/{serial}",
            "docs": "https://ably.com/docs/api/rest-api#update-message",
            "body_required": True,
        },
        {
            "name": "get_message_versions",
            "label": "Get message versions",
            "category": "Messages",
            "method": "GET",
            "path": "/channels/{channelId}/messages/{serial}/versions",
            "docs": "https://ably.com/docs/api/rest-api#message-versions",
            "body_required": False,
        },
        {
            "name": "get_channel",
            "label": "Get channel details",
            "category": "Channels",
            "method": "GET",
            "path": "/channels/{channelId}",
            "docs": "https://ably.com/docs/api/rest-api#metadata-rest",
            "body_required": False,
        },
        {
            "name": "list_channels",
            "label": "List active channels",
            "category": "Channels",
            "method": "GET",
            "path": "/channels",
            "docs": "https://ably.com/docs/api/rest-api#enumeration-rest",
            "body_required": False,
        },
        {
            "name": "publish_annotation",
            "label": "Publish message annotation",
            "category": "Annotations",
            "method": "POST",
            "path": "/channels/{channelId}/messages/{messageSerial}/annotations",
            "docs": "https://ably.com/docs/api/rest-api#annotations-publish",
            "body_required": True,
        },
        {
            "name": "list_annotations",
            "label": "List message annotations",
            "category": "Annotations",
            "method": "GET",
            "path": "/channels/{channelId}/messages/{messageSerial}/annotations",
            "docs": "https://ably.com/docs/api/rest-api#annotations-list",
            "body_required": False,
        },
        {
            "name": "get_annotation_client_summary",
            "label": "Get annotation client summary",
            "category": "Annotations",
            "method": "GET",
            "path": "/channels/{channelId}/messages/{messageSerial}/client-summary",
            "docs": "https://ably.com/docs/api/rest-api#annotations-client-summary",
            "body_required": False,
        },
        {
            "name": "get_presence",
            "label": "Get channel presence",
            "category": "Presence",
            "method": "GET",
            "path": "/channels/{channelId}/presence",
            "docs": "https://ably.com/docs/api/rest-api#presence",
            "body_required": False,
        },
        {
            "name": "get_presence_history",
            "label": "Get channel presence history",
            "category": "Presence",
            "method": "GET",
            "path": "/channels/{channelId}/presence/history",
            "docs": "https://ably.com/docs/api/rest-api#presence-history",
            "body_required": False,
        },
        {
            "name": "register_push_device",
            "label": "Register push device",
            "category": "Push devices",
            "method": "POST",
            "path": "/push/deviceRegistrations",
            "docs": "https://ably.com/docs/api/rest-api#post-device-registration",
            "body_required": True,
        },
        {
            "name": "replace_push_device",
            "label": "Replace push device",
            "category": "Push devices",
            "method": "PUT",
            "path": "/push/deviceRegistrations/{deviceId}",
            "docs": "https://ably.com/docs/api/rest-api#put-device-registration",
            "body_required": True,
        },
        {
            "name": "patch_push_device",
            "label": "Patch push device",
            "category": "Push devices",
            "method": "PATCH",
            "path": "/push/deviceRegistrations/{deviceId}",
            "docs": "https://ably.com/docs/api/rest-api#patch-device-registration",
            "body_required": True,
        },
        {
            "name": "get_push_device",
            "label": "Get push device",
            "category": "Push devices",
            "method": "GET",
            "path": "/push/deviceRegistrations/{deviceId}",
            "docs": "https://ably.com/docs/api/rest-api#get-device-registration",
            "body_required": False,
        },
        {
            "name": "list_push_devices",
            "label": "List push devices",
            "category": "Push devices",
            "method": "GET",
            "path": "/push/deviceRegistrations",
            "docs": "https://ably.com/docs/api/rest-api#list-device-registrations",
            "body_required": False,
        },
        {
            "name": "reset_push_device_token",
            "label": "Reset push device update token",
            "category": "Push devices",
            "method": "POST",
            "path": "/push/deviceRegistrations/{deviceId}/resetUpdateToken",
            "docs": "https://ably.com/docs/api/rest-api#reset-update-token",
            "body_required": False,
        },
        {
            "name": "unregister_push_device",
            "label": "Unregister push device",
            "category": "Push devices",
            "method": "DELETE",
            "path": "/push/deviceRegistrations/{deviceId}",
            "docs": "https://ably.com/docs/api/rest-api#delete-device-registration",
            "body_required": False,
        },
        {
            "name": "unregister_push_devices",
            "label": "Unregister matching push devices",
            "category": "Push devices",
            "method": "DELETE",
            "path": "/push/deviceRegistrations",
            "docs": "https://ably.com/docs/api/rest-api#delete-device-registrations",
            "body_required": False,
        },
        {
            "name": "subscribe_push_channel",
            "label": "Subscribe push channel",
            "category": "Push subscriptions",
            "method": "POST",
            "path": "/push/channelSubscriptions",
            "docs": "https://ably.com/docs/api/rest-api#post-channel-subscription",
            "body_required": True,
        },
        {
            "name": "unsubscribe_push_channels",
            "label": "Unsubscribe push channels",
            "category": "Push subscriptions",
            "method": "DELETE",
            "path": "/push/channelSubscriptions",
            "docs": "https://ably.com/docs/api/rest-api#delete-channel-subscription",
            "body_required": False,
        },
        {
            "name": "list_push_subscriptions",
            "label": "List push channel subscriptions",
            "category": "Push subscriptions",
            "method": "GET",
            "path": "/push/channelSubscriptions",
            "docs": "https://ably.com/docs/api/rest-api#list-channel-subscriptions",
            "body_required": False,
        },
        {
            "name": "list_push_channels",
            "label": "List push channels",
            "category": "Push subscriptions",
            "method": "GET",
            "path": "/push/channels",
            "docs": "https://ably.com/docs/api/rest-api#list-channels",
            "body_required": False,
        },
        {
            "name": "publish_push_notification",
            "label": "Publish push notification",
            "category": "Push notifications",
            "method": "POST",
            "path": "/push/publish",
            "docs": "https://ably.com/docs/api/rest-api#push-publish",
            "body_required": True,
        },
        {
            "name": "publish_batch_push_notifications",
            "label": "Publish batch push notifications",
            "category": "Push notifications",
            "method": "POST",
            "path": "/push/batch/publish",
            "docs": "https://ably.com/docs/api/rest-api#push-publish-batch",
            "body_required": True,
        },
        {
            "name": "request_access_token",
            "label": "Request access token",
            "category": "Authentication",
            "method": "POST",
            "path": "/keys/{keyName}/requestToken",
            "docs": "https://ably.com/docs/api/rest-api#request-token",
            "body_required": True,
        },
        {
            "name": "revoke_tokens",
            "label": "Revoke access tokens",
            "category": "Authentication",
            "method": "POST",
            "path": "/keys/{keyName}/revokeTokens",
            "docs": "https://ably.com/docs/api/rest-api#revoke-tokens",
            "body_required": True,
        },
        {
            "name": "get_stats",
            "label": "Get application statistics",
            "category": "Application",
            "method": "GET",
            "path": "/stats",
            "docs": "https://ably.com/docs/api/rest-api#stats",
            "body_required": False,
        },
        {
            "name": "batch_publish",
            "label": "Publish messages to multiple channels",
            "category": "Batch",
            "method": "POST",
            "path": "/messages",
            "docs": "https://ably.com/docs/api/rest-api#batch-publish",
            "body_required": True,
        },
        {
            "name": "batch_presence",
            "label": "Get presence on multiple channels",
            "category": "Batch",
            "method": "GET",
            "path": "/presence",
            "docs": "https://ably.com/docs/api/rest-api#batch-presence",
            "body_required": False,
        },
        {
            "name": "get_time",
            "label": "Get Ably service time",
            "category": "Utilities",
            "method": "GET",
            "path": "/time",
            "docs": "https://ably.com/docs/api/rest-api#time",
            "body_required": False,
        },
    ]
}
PATH_VARIABLE_RE = re.compile(r"\{([A-Za-z][A-Za-z0-9]*)\}")
LINK_RE = re.compile(r'<([^>]+)>;\s*rel="(first|current|next)"')


class AblyApiKeyCredential(BaseModel):
    """A server-side Ably application API key (``appId.keyId:secret``)."""

    credential_type: Literal["ably_api_key"] = Field(
        "ably_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="Ably application API key",
        description="Full application key in appId.keyId:secret format.",
        json_schema_extra={"ui:widget": "password"},
    )

    model_config = ConfigDict(
        title="Ably API Key",
        json_schema_extra={
            "x-credential-url": "https://ably.com/dashboard",
            "x-credential-instructions": (
                "In the Ably dashboard, open your application and copy a server-side "
                "API key. Give it the capabilities needed by your workflow."
            ),
        },
    )


def _field_name(variable: str) -> str:
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", variable)
    return "path_" + words.lower()


def _make_config(name: str, operation: dict[str, Any]) -> type[BaseModel]:
    fields: dict[str, tuple[Any, Any]] = {}
    for variable in PATH_VARIABLE_RE.findall(operation["path"]):
        fields[_field_name(variable)] = (
            str,
            Field(..., title=variable, description=f"Ably {variable} for this action."),
        )
    if name == "batch_presence":
        fields["channels"] = (
            str,
            Field(
                ...,
                min_length=1,
                title="Channels",
                description="Comma-separated channel names required by the batch presence API.",
            ),
        )
    fields["query_json"] = (
        Optional[str],
        Field(
            None,
            title="Query parameters JSON",
            description=(
                "Optional query parameters from the linked Ably REST reference. "
                "Use a JSON object; arrays send repeated keys. For history, try "
                '{"limit":50,"direction":"backwards"}.'
            ),
            json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
        ),
    )
    if operation["body_required"]:
        fields["body_json"] = (
            str,
            Field(
                ...,
                title="Request body JSON",
                description=(
                    "JSON body documented for this Ably action. A channel publish "
                    'can use {"name":"event","data":{"value":1}}.'
                ),
                json_schema_extra={
                    "ui:widget": "code_editor",
                    "x-code-language": "json",
                },
            ),
        )
    return create_model(
        "Ably" + "".join(part.title() for part in name.split("_")) + "Config",
        __module__=__name__,
        operation=(
            Literal[name],
            Field(
                name,
                title=operation["label"],
                description=f"Ably REST reference: {operation['docs']}",
                json_schema_extra={
                    "const": name,
                    "ui:hidden": True,
                    "x-category": operation["category"],
                    "x-is-trigger": False,
                    "x-display-name": operation["label"],
                    "x-operation-docs-url": operation["docs"],
                },
            ),
        ),
        **fields,
    )


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
AblyConfig = Annotated[Union[tuple(CONFIG_MODELS.values())], Discriminator("operation")]


class AblyNodeConfig(NodeConfig[AblyConfig, AblyApiKeyCredential]):
    model_config = ConfigDict(json_schema_extra={"x-agent-tool-provider": True})


def _json_value(raw: str, field: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} must be valid JSON") from exc


def _query_params(raw: Optional[str]) -> list[tuple[str, Any]]:
    if not raw:
        return []
    values = _json_value(raw, "Query parameters")
    if not isinstance(values, dict):
        raise ValueError("Query parameters must be a JSON object")
    params = []
    for key, value in values.items():
        if not isinstance(key, str) or not key:
            raise ValueError("Query parameter names must be nonempty strings")
        if isinstance(value, dict):
            raise ValueError("Query parameter values must be scalars or arrays")
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, (dict, list)):
                raise ValueError("Query parameter arrays must contain scalar values")
            if item is not None:
                params.append((key, item))
    return params


class AblyNode(WorkflowNode):
    """Run one documented Ably REST action with a server-side application key."""

    integration_type = "automation-ably"

    connection_evidence = ConnectionEvidence(
        operation="list_channels",
        operation_arguments={"query_json": '{"by":"id","limit":5}'},
        noun="active channels",
        proves="account",
    )
    edit_examples = [
        "Publish an Ably channel message",
        "Read Ably message history",
        "Check Ably channel presence",
        "Send an Ably push notification",
    ]

    @classmethod
    def get_config_model(cls):
        return AblyNodeConfig

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, AblyNodeConfig):
            raise ValueError("Ably configuration required")
        credential = self.config.credentials
        if credential is None or not credential.api_key.strip():
            raise ValueError("Connect an Ably application API key")
        key_name, separator, secret = credential.api_key.partition(":")
        if not separator or not key_name or not secret:
            raise ValueError("Ably API key must have appId.keyId:secret format")

        config = self.config.config
        operation = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = operation["path"]
        for variable in PATH_VARIABLE_RE.findall(path):
            value = values.pop(_field_name(variable))
            if not value:
                raise ValueError(f"Ably {variable} is required")
            path = path.replace("{" + variable + "}", quote(str(value), safe=""))
        if "{" in path or "}" in path:
            raise ValueError("Unsupported Ably API path template")

        params = _query_params(values.pop("query_json", None))
        if config.operation == "batch_presence":
            if any(key == "channels" for key, _ in params):
                raise ValueError("Set batch presence channels in the Channels field")
            params.append(("channels", values.pop("channels")))
        body_raw = values.pop("body_json", None)
        body = _json_value(body_raw, "Request body") if body_raw else None
        if operation["body_required"] and body is None:
            raise ValueError("Request body JSON is required")

        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            response = await client.request(
                operation["method"],
                API_BASE + path,
                auth=httpx.BasicAuth(key_name, secret),
                headers={"Accept": "application/json"},
                params=params or None,
                json=body,
            )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        if response.is_error or response.is_redirect:
            raise ValueError(
                f"Ably API error {response.status_code}: {response.text[:350]}"
            )
        if not response.content:
            data: Any = {"ok": True}
        else:
            try:
                data = response.json()
            except ValueError:
                data = {"text": response.text[:1000]}
        if isinstance(data, list):
            data = {
                "items": [
                    item if isinstance(item, dict) else {"value": item} for item in data
                ]
            }

        pagination = {
            relation: urljoin(str(response.url), href)
            for href, relation in LINK_RE.findall(response.headers.get("Link", ""))
        }
        result = {
            "status": "success",
            "operation": config.operation,
            "status_code": response.status_code,
            "data": data,
            "timing_ms": {"api_request": elapsed_ms},
        }
        if pagination:
            result["pagination"] = pagination
        return result
