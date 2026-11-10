"""LambdaTest (now TestMu AI) Screenshots v1, pinned to official OpenAPI 1.0.1.

Each action makes one documented request. No implicit retries of test creation.
Callbacks are configurable destinations, not authenticated NoClick triggers.
"""
from __future__ import annotations

import base64
import json
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

DOCS = "https://www.testmuai.com/support/docs/automated-screenshot-api-for-cross-browser-testing/"
SERVERS = {
    "us": "https://api.lambdatest.com/screenshots/v1",
    "eu": "https://eu-api.lambdatest.com/screenshots/v1",
}


class LambdaTestCredential(BaseModel):
    model_config = ConfigDict(title="LambdaTest Access Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://accounts.lambdatest.com/detail/profile",
            "x-credential-instructions": "Copy your username and access key from your LambdaTest (TestMu AI) dashboard's key icon or Account Settings. Screenshot API requires a premium plan. Choose the region that holds your account. NoClick reads your saved login profile names to check the connection.",
        })
    credential_type: Literal["lambdatest_access_key"] = Field("lambdatest_access_key", json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, title="Username")
    access_key: str = Field(..., min_length=1, title="Access key", json_schema_extra={"ui:widget": "password"})
    region: Literal["us", "eu"] = Field("us", title="Region", json_schema_extra={"enumNames": ["US", "EU"]})

    @field_validator("username", "access_key", mode="before")
    @classmethod
    def credential_text(cls, value, info):
        if not isinstance(value, str):
            raise ValueError("Paste your username or access key")
        value = value.strip()
        if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Credentials must not contain control characters")
        if info.field_name == "username" and ":" in value:
            raise ValueError("Paste the username without a colon")
        return clean_secret(value, field_name="Access key") if info.field_name == "access_key" else value


class ListBrowsers(BaseModel):
    """Get supported operating systems and browser versions."""
    operation: Literal["list_browsers"] = "list_browsers"
    os: Optional[str] = Field(None, description="Optional operating system filter, e.g. windows 10.")


class ListDevices(BaseModel):
    """Get supported mobile operating systems and devices."""
    operation: Literal["list_devices"] = "list_devices"
    os: Optional[str] = Field(None, description="Optional operating system filter, e.g. ios 12.0.")


class ListResolutions(BaseModel):
    """Get available Mac and Windows screen resolutions."""
    operation: Literal["list_resolutions"] = "list_resolutions"


class ListProfiles(BaseModel):
    """Get saved login profiles; stored passwords are redacted from output."""
    operation: Literal["list_profiles"] = "list_profiles"


class ListLocations(BaseModel):
    """Get available geolocation country codes and names."""
    operation: Literal["list_locations"] = "list_locations"


class TestID(BaseModel):
    test_id: str = Field(..., min_length=1, max_length=200, description="Screenshot test ID returned by Start Screenshot Test.")

    @field_validator("test_id")
    @classmethod
    def valid_id(cls, value):
        if value in {".", ".."} or any(c in value for c in "/\\?#") or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Use a single screenshot test ID")
        return value


class GetScreenshots(TestID):
    """Get a screenshot test's status and individual image URLs."""
    operation: Literal["get_screenshots"] = "get_screenshots"


class GetScreenshotZip(TestID):
    """Get the ZIP download URL; does not download the archive."""
    operation: Literal["get_screenshot_zip"] = "get_screenshot_zip"


class StopScreenshotTest(TestID):
    """Stop a running screenshot test; completed tests return 404."""
    operation: Literal["stop_screenshot_test"] = "stop_screenshot_test"


class StartScreenshotTest(BaseModel):
    """Capture a URL across a chosen browser/device matrix."""
    operation: Literal["start_screenshot_test"] = "start_screenshot_test"
    url: str = Field(..., description="Full HTTP or HTTPS URL of the website to capture.")
    configs: dict[str, dict[str, list[str]]] = Field(..., min_length=1,
        description='OS-to-browser version matrix, e.g. {"windows 10":{"chrome":["76"]}}. Mobile OS entries use devices as the inner key.')
    defer_time: Optional[float] = Field(None, ge=0, description="Seconds to wait before capture.")
    email: Optional[bool] = Field(None, description="Email screenshot results when complete.")
    mac_res: Optional[str] = Field(None, description="Mac resolution from List Resolutions.")
    win_res: Optional[str] = Field(None, description="Windows resolution from List Resolutions.")
    tunnel: Optional[bool] = Field(None, description="Use an existing LambdaTest tunnel for a locally hosted site.")
    tunnel_identifier: Optional[str] = None
    username: Optional[str] = Field(None, title="Website username", description="Target website's HTTP Basic username, separate from the API account.")
    password: Optional[str] = Field(None, title="Website password", json_schema_extra={"ui:widget": "password"})
    callback_url: Optional[str] = Field(None, description="Optional destination for results (OpenAPI field callback_url).")
    smart_scroll: Optional[bool] = Field(None, description="Smart scroll, as shown in the provider's OpenAPI examples.")
    layout: Optional[Literal["portrait", "landscape"]] = None
    profile_id: Optional[str] = Field(None, description="Saved login profile name from List Profiles.")
    country_code: Optional[str] = Field(None, description="Country code from List Locations.")

    @field_validator("configs", mode="before")
    @classmethod
    def parse_matrix(cls, value):
        return json.loads(value) if isinstance(value, str) else value

    @field_validator("url", "callback_url")
    @classmethod
    def http_url(cls, value):
        if value is None:
            return value
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Use a full HTTP or HTTPS URL without embedded credentials")
        return value


LambdaTestConfig = Annotated[Union[
    StartScreenshotTest, GetScreenshots, GetScreenshotZip, StopScreenshotTest,
    ListBrowsers, ListDevices, ListResolutions, ListProfiles, ListLocations,
], Field(discriminator="operation")]


class LambdaTestNodeConfig(NodeConfig[LambdaTestConfig, LambdaTestCredential]):
    pass


ROUTES = {
    "start_screenshot_test": ("POST", "/"),
    "get_screenshots": ("GET", "/{test_id}"),
    "get_screenshot_zip": ("GET", "/{test_id}/zip"),
    "stop_screenshot_test": ("PUT", "/stop/{test_id}"),
    "list_browsers": ("GET", "/os-browsers"),
    "list_devices": ("GET", "/devices"),
    "list_resolutions": ("GET", "/resolutions"),
    "list_profiles": ("GET", "/profiles"),
    "list_locations": ("GET", "/locations"),
}


def _redact(value, secrets):
    if isinstance(value, dict):
        return {k: "[redacted]" if k.lower() in {"password", "access_key", "authorization"} else _redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
    return value


class LambdaTestNode(WorkflowNode):
    integration_type = "automation-lambdatest"
    connection_evidence = ConnectionEvidence(noun="saved login profiles", operation="list_profiles")

    @classmethod
    def get_config_model(cls):
        return LambdaTestNodeConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a LambdaTest username and access key")
        credential = self.config.credentials
        config = self.config.config
        method, path = ROUTES[config.operation]
        if isinstance(config, TestID):
            path = path.format(test_id=quote(config.test_id, safe=""))
        token = base64.b64encode(f"{credential.username}:{credential.access_key}".encode()).decode()
        params = {"os": config.os} if isinstance(config, (ListBrowsers, ListDevices)) and config.os else None
        body = config.model_dump(exclude={"operation"}, exclude_none=True) if isinstance(config, StartScreenshotTest) else None
        secrets = [credential.access_key, token, getattr(config, "password", None)]
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, SERVERS[credential.region] + path,
                    headers={"Authorization": "Basic " + token, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
        except httpx.RequestError:
            raise ValueError("LambdaTest request could not be confirmed; inspect the dashboard before retrying a write") from None
        try:
            data = response.json()
        except ValueError:
            raise ValueError(f"LambdaTest returned non-JSON (HTTP {response.status_code})") from None
        data = _redact(data, secrets)
        if response.status_code != 200:
            message = data.get("message", "Request rejected") if isinstance(data, dict) else "Request rejected"
            result = {"status": "error", "action": config.operation, "http_status": response.status_code, "error": message}
        elif not isinstance(data, dict):
            raise ValueError("LambdaTest returned an unexpected JSON shape")
        else:
            result = {"status": "success", "action": config.operation, "data": data}
            # The shared connection-evidence collector recognises an items list.
            if config.operation == "list_profiles":
                result["items"] = data.get("profiles", [])
        await self.emit(result)
        return result
