"""Sauce Labs Real Device Access API v2 (Open Beta).

Contract: https://raw.githubusercontent.com/saucelabs/real-device-api/main/open_api_specification.yaml
Username/access-key Basic authentication, fixed regional hosts, one HTTP request
per operation. Session and installation acknowledgements preserve provider state;
starting a session or Appium server does not imply it is ready for testing.
"""
from __future__ import annotations

import base64
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class SauceLabsAccessKeyCredential(BaseModel):
    model_config = ConfigDict(title="Sauce Labs Access Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.saucelabs.com/user-settings",
            "x-credential-instructions": "Copy your username and access key from Account > User Settings and choose your account's data center. Real Device Access API v2 is an open beta; ask your Sauce Labs representative to enable access. Connection testing reads your device sessions."
        })
    credential_type: Literal["saucelabs_access_key"] = Field("saucelabs_access_key", json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, max_length=256, title="Username")
    access_key: str = Field(..., min_length=1, max_length=4096, title="Access key", json_schema_extra={"ui:widget": "password"})
    region: Literal["us-west-1", "eu-central-1", "us-east-4"] = Field("us-west-1", title="Data center")

    @field_validator("username")
    @classmethod
    def username_value(cls, value):
        value = value.strip()
        if not value or ":" in value or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the Sauce Labs username without spaces or a colon")
        return value

    @field_validator("access_key")
    @classmethod
    def key_value(cls, value):
        value = clean_secret(value, field_name="Access key")
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste the access key without whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Session(_Input):
    session_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="Device session ID returned by Create Session or List Sessions.")


class ListDevices(_Input):
    """List device descriptors available to your account."""
    operation: Literal["list_devices"] = "list_devices"
    device_id: str | None = Field(None, max_length=512, description="Device descriptor or name filter; supports regex.")


class ListDeviceStatus(_Input):
    """Read live device availability; public devices have aggregated states."""
    operation: Literal["list_device_status"] = "list_device_status"
    state: Literal["AVAILABLE", "IN_USE", "CLEANING", "REBOOTING", "MAINTENANCE", "OFFLINE"] | None = None
    private_only: bool | None = None
    device_name: str | None = Field(None, max_length=512)


class CreateSession(_Input):
    """Allocate a device; poll Get Session until ACTIVE before interacting. Uses your device quota."""
    operation: Literal["create_session"] = "create_session"
    device_name: str = Field(..., min_length=1, max_length=512, description="Device descriptor or name (regex supported).")
    os: Literal["android", "ios"] | None = None
    session_duration: str = Field("PT1H", pattern=r"^PT(?:(?:[1-9]|1[0-9]|2[0-3])H(?:[0-5]?[0-9]M)?|[1-5]?[0-9]M|24H)$", description="ISO-8601 duration up to 24 hours. Provider may close sessions over 6 hours early.")
    tunnel_name: str | None = Field(None, min_length=1, max_length=256)
    tunnel_owner: str | None = Field(None, min_length=1, max_length=256)


class ListSessions(_Input):
    """Read pending, active and recently closed sessions for the authenticated account."""
    operation: Literal["list_sessions"] = "list_sessions"
    state: Literal["PENDING", "CREATING", "ACTIVE", "CLOSING", "CLOSED", "ERRORED"] | None = None
    device_name: str | None = Field(None, max_length=512)


class GetSession(_Session):
    operation: Literal["get_session"] = "get_session"


class CloseSession(_Session):
    """Release a device session; CLOSING is an acknowledgement, not completed cleanup."""
    operation: Literal["close_session"] = "close_session"
    reboot_device: bool = Field(False, description="Reboot after release; private devices only.")


class ExecuteShellCommand(_Session):
    """Execute a short Android adb shell command without the adb shell prefix."""
    operation: Literal["execute_shell_command"] = "execute_shell_command"
    command: str = Field(..., min_length=1, max_length=8192)


class OpenUrl(_Session):
    """Open a URL or iOS deep link on an ACTIVE device; Android uses Chrome."""
    operation: Literal["open_url"] = "open_url"
    url: str = Field(..., min_length=1, max_length=8192)


class InstallApp(_Session):
    """Start a background app installation; poll List App Installations for completion."""
    operation: Literal["install_app"] = "install_app"
    app: str = Field(..., min_length=1, max_length=4096, description="Sauce App Storage reference, e.g. storage:filename=myapp.apk.")
    enable_instrumentation: bool = Field(True, description="Includes iOS re-signing; recommended by Sauce Labs.")
    launch_after_install: bool = False


class ListAppInstallations(_Session):
    operation: Literal["list_app_installations"] = "list_app_installations"


class UninstallApp(_Session):
    """Uninstall the specified iOS bundle or Android package from this device."""
    operation: Literal["uninstall_app"] = "uninstall_app"
    platform: Literal["android", "ios"] = "android"
    app_id: str = Field(..., min_length=1, max_length=512, description="Android package name or iOS bundle identifier.")


class ApplySettings(_Session):
    """Change orientation and optional Android locale/animations during an ACTIVE session."""
    operation: Literal["apply_settings"] = "apply_settings"
    orientation: Literal["PORTRAIT", "LANDSCAPE"]
    locale: str | None = Field(None, max_length=64, description="Android only, e.g. en_US.")
    animations: bool | None = Field(None, description="Android only.")


class TakeScreenshot(_Session):
    operation: Literal["take_screenshot"] = "take_screenshot"


class StartAppium(_Session):
    """Start the hosted Appium server for this device session."""
    operation: Literal["start_appium"] = "start_appium"
    appium_version: str = Field("latest", max_length=64)


class GetAppium(_Session):
    operation: Literal["get_appium"] = "get_appium"


SauceLabsConfig = Annotated[Union[ListDevices, ListDeviceStatus, CreateSession, ListSessions,
    GetSession, CloseSession, ExecuteShellCommand, OpenUrl, InstallApp, ListAppInstallations,
    UninstallApp, ApplySettings, TakeScreenshot, StartAppium, GetAppium], Field(discriminator="operation")]


class SauceLabsFullConfig(NodeConfig[SauceLabsConfig, SauceLabsAccessKeyCredential]):
    pass


# Each entry corresponds to exactly one operation in the pinned v2 contract.
ROUTES = {
    "list_devices": ("GET", "/devices"),
    "list_device_status": ("GET", "/devices/status"),
    "create_session": ("POST", "/sessions"),
    "list_sessions": ("GET", "/sessions"),
    "get_session": ("GET", "/sessions/{session_id}"),
    "close_session": ("DELETE", "/sessions/{session_id}"),
    "execute_shell_command": ("POST", "/sessions/{session_id}/device/executeShellCommand"),
    "open_url": ("POST", "/sessions/{session_id}/device/openUrl"),
    "install_app": ("POST", "/sessions/{session_id}/device/installApp"),
    "list_app_installations": ("POST", "/sessions/{session_id}/device/listAppInstallations"),
    "uninstall_app": ("POST", "/sessions/{session_id}/device/uninstallApp"),
    "apply_settings": ("POST", "/sessions/{session_id}/device/applySettings"),
    "take_screenshot": ("POST", "/sessions/{session_id}/device/takeScreenshot"),
    "start_appium": ("POST", "/sessions/{session_id}/appiumserver"),
    "get_appium": ("GET", "/sessions/{session_id}/appiumserver"),
}
QUERY = {
    "list_devices": {"device_id": "deviceId"},
    "list_device_status": {"state": "state", "private_only": "privateOnly", "device_name": "deviceName"},
    "list_sessions": {"state": "state", "device_name": "deviceName"},
    "close_session": {"reboot_device": "rebootDevice"},
}
BODY = {
    "execute_shell_command": {"command": "adbShellCommand"},
    "open_url": {"url": "url"},
    "install_app": {"app": "app", "enable_instrumentation": "enableInstrumentation", "launch_after_install": "launchAfterInstall"},
    "apply_settings": {"orientation": "orientation", "locale": "locale", "animations": "animations"},
    "start_appium": {"appium_version": "appiumVersion"},
}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {_redact(key, secrets): _redact(item, secrets) for key, item in value.items()
                if key.lower().replace("_", "").replace("-", "") not in {"accesskey", "password", "authorization", "token", "accesstoken"}}
    return value


class SauceLabsNode(WorkflowNode):
    integration_type = "automation-saucelabs"
    connection_evidence = ConnectionEvidence(operation="list_sessions", noun="device sessions")

    @classmethod
    def get_config_model(cls):
        return SauceLabsFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Sauce Labs username and access key")
        op = self.config.config
        values = op.model_dump(exclude_none=True)
        method, template = ROUTES[op.operation]
        route = template.format(session_id=quote(values.get("session_id", ""), safe=""))
        url = f"https://api.{credential.region}.saucelabs.com/rdc/v2" + route
        auth = "Basic " + base64.b64encode(f"{credential.username}:{credential.access_key}".encode()).decode()
        secrets = (credential.access_key, auth, auth[6:])
        params = {target: str(values[source]).lower() if isinstance(values[source], bool) else values[source]
                  for source, target in QUERY.get(op.operation, {}).items() if source in values}
        kwargs = {"params": params}
        if op.operation in BODY:
            kwargs["json"] = {target: values[source] for source, target in BODY[op.operation].items() if source in values}
        elif op.operation == "create_session":
            if op.tunnel_owner and not op.tunnel_name:
                raise ValueError("A tunnel owner requires a tunnel name")
            configuration = {"sessionDuration": op.session_duration}
            if op.tunnel_name:
                configuration["tunnel"] = {"name": op.tunnel_name, **({"owner": op.tunnel_owner} if op.tunnel_owner else {})}
            kwargs["json"] = {"device": {"deviceName": op.device_name, **({"os": op.os} if op.os else {})}, "configuration": configuration}
        elif op.operation == "uninstall_app":
            kwargs["json"] = {"packageName" if op.platform == "android" else "bundleId": op.app_id}
        headers = {"Authorization": auth, "Accept": "image/png" if op.operation == "take_screenshot" else "application/json", "Content-Type": "application/json"}
        # Never retry a write automatically: a timeout can follow an accepted action.
        try:
            async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, url, headers=headers, **kwargs)
        except httpx.TransportError:
            raise ValueError("Sauce Labs did not confirm the request; inspect the device/session before retrying a write") from None
        if not 200 <= response.status_code < 300:
            return {"status": "error", "http_status": response.status_code,
                    "error": _redact(response.text[:2000], secrets) or "Sauce Labs rejected the request"}
        if len(response.content) > 20_000_000:
            raise ValueError("Sauce Labs response exceeds the 20 MB limit")
        mime = response.headers.get("content-type", "").split(";", 1)[0].lower().strip()
        if op.operation == "take_screenshot":
            if mime != "image/png" or not response.content.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Sauce Labs did not return a PNG screenshot")
            data = BinaryOutput(data=response.content, content_type="image/png", filename="saucelabs-screenshot.png")
        elif response.status_code == 204:
            data = None
        else:
            if mime != "application/json":
                raise ValueError("Sauce Labs did not return JSON")
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Sauce Labs returned invalid JSON") from None
            if not isinstance(data, (dict, list)):
                raise ValueError("Sauce Labs returned an unexpected response shape")
            if op.operation == "list_sessions" and (not isinstance(data, dict) or not isinstance(data.get("sessions"), list)):
                raise ValueError("Sauce Labs did not return device sessions")
            if isinstance(data, dict) and (data.get("type") == "about:blank" or data.get("errors")):
                return {"status": "error", "http_status": response.status_code, "error": _redact(str(data), secrets)}
            data = _redact(data, secrets)
        return {"status": "success", "http_status": response.status_code, "data": data}
