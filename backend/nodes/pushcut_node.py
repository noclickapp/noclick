"""Pushcut's published v1 API, including the two documented v2 read routes.

One operation per provider route. Requests are never retried: notifications,
shortcuts and online-action registrations can have irreversible side effects.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.pushcut.io"
CREDENTIAL_TYPE = "pushcut_api_key"


class PushcutApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Pushcut API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.pushcut.io/webapi",
            "x-credential-instructions": "In the Pushcut app, open Account and manage API Keys. Paste an API key here. NoClick sends it in the API-Key header to api.pushcut.io. Listing your devices verifies the connection. Dynamic notification content and widget updates require Pushcut Pro; Automation Server features may require an additional subscription.",
        })
    credential_type: Literal["pushcut_api_key"] = Field("pushcut_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste a Pushcut API key")
        value = clean_secret(value, field_name="API Key", key=True)
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste an API key without the API-Key header")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def _name(value):
    if not isinstance(value, str) or not value.strip() or value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Provide a nonempty Pushcut name or ID without control characters")
    return value


class ListDevices(_Config):
    operation: Literal["list_devices"] = "list_devices"


class ListNotifications(_Config):
    operation: Literal["list_notifications"] = "list_notifications"


class URLHeader(_Config):
    key: str
    value: str


class URLBackgroundOptions(_Config):
    httpMethod: Literal["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"] | None = None
    httpContentType: str | None = None
    httpBody: str | None = None
    httpHeader: list[URLHeader] | None = None


class DefaultNotificationAction(_Config):
    # Provider support docs explicitly do not require a name for defaultAction.
    name: str | None = None
    input: str | None = None
    url: str | None = None
    homekit: str | None = None
    runOnServer: bool | None = None
    online: str | None = None
    shortcut: str | None = None
    urlBackgroundOptions: URLBackgroundOptions | None = None


class NotificationAction(DefaultNotificationAction):
    name: str = Field(..., min_length=1)
    keepNotification: bool | None = None


class SendNotification(_Config):
    """Send or schedule a defined notification; omitted fields retain its app defaults."""
    operation: Literal["send_notification"] = "send_notification"
    notification_name: str = Field(..., min_length=1, max_length=512, title="Notification Name")
    text: str | None = None
    title: str | None = None
    input: str | None = None
    id: str | None = Field(None, description="Reuse an ID to replace an existing notification on a device.")
    devices: list[str] | None = None
    image: str | None = None
    imageData: str | None = Field(None, description="Base64-encoded notification image; overrides image.")
    sound: Literal["none", "vibrateOnly", "system", "subtle", "question", "jobDone", "problem", "loud", "lasers"] | None = None
    actions: list[NotificationAction] | None = None
    defaultAction: DefaultNotificationAction | None = None
    threadId: str | None = None
    interruptionLevel: Literal["active", "passive", "timeSensitive"] | None = None
    delay: str | None = Field(None, description="For example 10s, 15m or 6h.")
    scheduleTimestamp: float | None = Field(None, description="Unix timestamp in milliseconds.")
    _notification = field_validator("notification_name")(_name)

    @model_validator(mode="after")
    def scheduling(self):
        if self.scheduleTimestamp is not None and (self.delay is not None or self.interruptionLevel is not None):
            raise ValueError("Use scheduleTimestamp separately from delay or interruptionLevel")
        return self


class CancelNotification(_Config):
    operation: Literal["cancel_notification"] = "cancel_notification"
    notification_id: str = Field(..., min_length=1, max_length=512)
    devices: str | None = Field(None, description="Comma-separated device names; omit for all devices.")
    onlyScheduled: bool | None = Field(None, description="Cancel only scheduled notifications when true.")
    _notification = field_validator("notification_id")(_name)


class ListSubscriptions(_Config):
    operation: Literal["list_subscriptions"] = "list_subscriptions"


class CreateSubscription(_Config):
    """Register an online action webhook; does not start a NoClick trigger listener."""
    operation: Literal["create_subscription"] = "create_subscription"
    actionName: str = Field(..., min_length=1, max_length=512)
    url: str = Field(..., min_length=1, description="Webhook URL Pushcut will call when this online action is executed.")
    isLocalUrl: bool | None = Field(None, description="Have the device call this webhook on its local network.")

    @field_validator("url")
    @classmethod
    def webhook(cls, value):
        from urllib.parse import urlsplit
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in value):
            raise ValueError("Provide an HTTP or HTTPS webhook URL")
        return value


class DeleteSubscription(_Config):
    operation: Literal["delete_subscription"] = "delete_subscription"
    subscription_id: str = Field(..., min_length=1, max_length=512)
    _subscription = field_validator("subscription_id")(_name)


class ExecuteAction(_Config):
    """Execute exactly one Shortcut or HomeKit scene on an Automation Server."""
    operation: Literal["execute_action"] = "execute_action"
    shortcut: str | None = None
    homekit: str | None = None
    input: str | None = None
    serverId: str | None = None
    timeout: str | None = Field(None, description="Timeout in seconds or nowait. NoClick waits up to 60 seconds for HTTP.")
    delay: str | None = None
    identifier: str | None = Field(None, description="Identifier used to overwrite or cancel a delayed execution.")

    @model_validator(mode="after")
    def target(self):
        if bool(self.shortcut) == bool(self.homekit):
            raise ValueError("Specify exactly one shortcut or HomeKit scene")
        return self


class CancelExecution(_Config):
    operation: Literal["cancel_execution"] = "cancel_execution"
    identifier: str = Field(..., min_length=1, max_length=512)


class UploadImage(_Config):
    operation: Literal["upload_image"] = "upload_image"
    image_name: str = Field(..., min_length=1, max_length=512)
    base64Image: str = Field(..., min_length=1, max_length=14_000_000, description="Base64-encoded PNG, JPEG or GIF image, without a data URL prefix.")
    _image = field_validator("image_name")(_name)



class MoveImage(_Config):
    operation: Literal["move_image"] = "move_image"
    image_name: str = Field(..., min_length=1, max_length=512)
    destination: str = Field(..., min_length=1, max_length=512)
    _names = field_validator("image_name", "destination")(_name)

    @model_validator(mode="after")
    def different(self):
        if self.image_name == self.destination:
            raise ValueError("The destination must differ from the original image name")
        return self


class ListWidgets(_Config):
    operation: Literal["list_widgets"] = "list_widgets"


class WidgetTapAction(_Config):
    action: Literal["openPushcut", "runShortcut", "openURL", "runHomeKitScene", "runIntegration"]
    viewName: Literal["notifications", "triggers", "widgets", "tunnel", "account", "runServer"] | None = None
    shortcutName: str | None = None
    shortcutInput: str | None = None
    shouldRunOnServer: bool | None = None
    url: str | None = None
    sceneName: str | None = None
    triggerIdentifier: str | None = None

    @model_validator(mode="after")
    def target(self):
        key = {"runShortcut": "shortcutName", "openURL": "url", "runHomeKitScene": "sceneName", "runIntegration": "triggerIdentifier"}.get(self.action)
        if key and not getattr(self, key):
            raise ValueError("Provide " + key + " for the selected tap action")
        return self


class UpdateWidget(_Config):
    operation: Literal["update_widget"] = "update_widget"
    widget_name: str = Field(..., min_length=1, max_length=512)
    content: str | None = Field(None, description="An existing widget design name.")
    inputs: dict[str, str] | None = None
    devices: list[str] | None = None
    onTap: WidgetTapAction | None = None
    _widget = field_validator("widget_name")(_name)

    @model_validator(mode="after")
    def change(self):
        if all(getattr(self, key) is None for key in ("content", "inputs", "devices", "onTap")):
            raise ValueError("Include at least one of content, inputs, devices or onTap")
        return self


class ListWidgetDesigns(_Config):
    operation: Literal["list_widget_designs"] = "list_widget_designs"


class GetWidgetDesign(_Config):
    operation: Literal["get_widget_design"] = "get_widget_design"
    design_id: str = Field(..., min_length=1, max_length=512)
    _design = field_validator("design_id")(_name)


class ListServers(_Config):
    operation: Literal["list_servers"] = "list_servers"


class ListLoggedNotifications(_Config):
    operation: Literal["list_logged_notifications"] = "list_logged_notifications"


Operation = Annotated[Union[ListDevices, ListNotifications, SendNotification, CancelNotification,
    ListSubscriptions, CreateSubscription, DeleteSubscription, ExecuteAction, CancelExecution,
    UploadImage, MoveImage, ListWidgets, UpdateWidget, ListWidgetDesigns, GetWidgetDesign,
    ListServers, ListLoggedNotifications], Field(discriminator="operation")]


class PushcutConfig(NodeConfig[Operation, PushcutApiKeyCredential]):
    pass


# method, path, path-parameter field, API version. Overrides come from each
# operation's servers declaration in the pinned provider contract.
ROUTES = {
    "list_devices": ("GET", "/devices", None, "v1"),
    "list_notifications": ("GET", "/notifications", None, "v1"),
    "send_notification": ("POST", "/notifications/{notification_name}", "notification_name", "v1"),
    "cancel_notification": ("DELETE", "/submittedNotifications/{notification_id}", "notification_id", "v1"),
    "list_subscriptions": ("GET", "/subscriptions", None, "v1"),
    "create_subscription": ("POST", "/subscriptions", None, "v1"),
    "delete_subscription": ("DELETE", "/subscriptions/{subscription_id}", "subscription_id", "v1"),
    "execute_action": ("POST", "/execute", None, "v1"),
    "cancel_execution": ("POST", "/cancelExecution", None, "v1"),
    "upload_image": ("PUT", "/images/{image_name}", "image_name", "v1"),
    "move_image": ("POST", "/images/{image_name}/move", "image_name", "v1"),
    "list_widgets": ("GET", "/widgets", None, "v1"),
    "update_widget": ("POST", "/widgets/{widget_name}", "widget_name", "v1"),
    "list_widget_designs": ("GET", "/widgetDesigns", None, "v1"),
    "get_widget_design": ("GET", "/widgetDesigns/{design_id}", "design_id", "v1"),
    "list_servers": ("GET", "/servers", None, "v2"),
    "list_logged_notifications": ("GET", "/loggedNotifications", None, "v2"),
}


class PushcutNode(WorkflowNode):
    integration_type = "automation-pushcut"
    connection_evidence = ConnectionEvidence(operation="list_devices", noun="devices", label_keys=("id",))

    @classmethod
    def get_config_model(cls):
        return PushcutConfig

    @classmethod
    def validate_config(cls, config_data):
        raw_credential = config_data.get("credentials")
        if isinstance(raw_credential, dict) and raw_credential.get("credential_type", CREDENTIAL_TYPE) != CREDENTIAL_TYPE:
            return {"valid": False, "errors": ["Attach a Pushcut API key credential"], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    def parse_config(cls, config_data):
        raw_credential = config_data.get("credentials")
        if isinstance(raw_credential, dict) and raw_credential.get("credential_type", CREDENTIAL_TYPE) != CREDENTIAL_TYPE:
            raise ValueError("Attach a Pushcut API key credential")
        parsed = super().parse_config(config_data)
        # Empty dynamic text intentionally clears an app-defined value. The
        # shared config cleanup treats empty editor fields as unset elsewhere.
        raw = config_data.get("config", config_data)
        if isinstance(parsed.config, SendNotification) and isinstance(raw, dict):
            for field in ("text", "title", "input"):
                if raw.get(field) == "":
                    setattr(parsed.config, field, "")
        return parsed

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Pushcut API key")
        op = self.config.config
        method, path, path_field, version = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        if path_field:
            path = path.format(**{path_field: quote(values.pop(path_field), safe="")})
        params, body = None, None
        if op.operation in {"execute_action", "cancel_execution", "cancel_notification"}:
            params = values
        elif method in {"POST", "PUT"}:
            body = values
        key = self.config.credentials.api_key
        # Fixed provider origin, no redirects, no environment proxies or retries.
        async with guarded_async_client(timeout=60, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE + "/" + version + path,
                headers={"API-Key": key, "Accept": "application/json"}, params=params,
                **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            try:
                raw = response.json()
                message = raw.get("error") or raw.get("message") if isinstance(raw, dict) else None
            except ValueError:
                message = None
            message = message if isinstance(message, str) else "Pushcut returned HTTP " + str(response.status_code)
            # Preserve the provider rejection for connection evidence, without secrets.
            raise ValueError("Pushcut HTTP " + str(response.status_code) + ": " + message.replace(key, "[redacted]")[:1000])
        if len(response.content) > 20_000_000:
            raise ValueError("Pushcut response exceeds 20 MB; check the provider before retrying a write")
        result = {"status": "success", "operation": op.operation, "http_status": response.status_code}
        if response.content:
            mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if mime == "application/json" or mime.endswith("+json"):
                data = response.json()
                if method == "GET" and op.operation != "get_widget_design" and not isinstance(data, list):
                    raise ValueError("Expected a Pushcut list response")
                required_identifier = {"send_notification": "id", "create_subscription": "id", "move_image": "name"}.get(op.operation)
                if required_identifier and (not isinstance(data, dict) or not isinstance(data.get(required_identifier), str)):
                    raise ValueError("Pushcut acknowledgement is missing its identifier; check the provider before retrying")
                if op.operation in {"get_widget_design", "update_widget"} and not isinstance(data, dict):
                    raise ValueError("Expected a Pushcut object response")
                result["items" if isinstance(data, list) else "data"] = data
            elif op.operation == "execute_action":
                result["file"] = BinaryOutput(response.content, mime or "application/octet-stream", "pushcut-result")
            else:
                raise ValueError("Expected a Pushcut JSON response; check the provider before retrying a write")
        elif method == "GET" or op.operation in {"send_notification", "create_subscription", "move_image", "update_widget"}:
            raise ValueError("Expected a Pushcut JSON response")
        # An acknowledgement does not prove delivery, Shortcut completion or device sync.
        if method != "GET":
            result["provider_acknowledged"] = True
        await self.emit(result)
        return result
