"""GTmetrix REST API 2.0: tests, reports, monitored pages and tags.

Contract: https://gtmetrix.com/api/gtmetrix-openapi-v2.0.json
Guide: https://gtmetrix.com/api/docs/2.0/
Each operation makes one API request; paginated reads return one page.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://gtmetrix.com/api/2.0"
CREDENTIAL_TYPE = "gtmetrix_api_key"
MEDIA_TYPE = "application/vnd.api+json"


class GTmetrixAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Gtmetrix API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://gtmetrix.com/api/docs/2.0/",
            "x-credential-instructions": "Paste your API key from GTmetrix API Details or Account Settings. NoClick sends it as the Basic username with a blank password. Test and retest operations spend GTmetrix API credits; plan and team-role restrictions apply."})
    credential_type: Literal["gtmetrix_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if ":" in value or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError("Paste the API key without a Basic prefix or colon")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("test_id", "report_slug", "page_id", "tag_id", "location", "browser", check_fields=False)
    @classmethod
    def identifier(cls, value):
        if value is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
            raise ValueError("Paste a single GTmetrix resource ID")
        return value


class _Paged(_Input):
    page_size: int = Field(50, ge=1, le=500, title="Page size")
    page_number: int = Field(1, ge=1, title="Page number", description="One page is returned. Increment to read the next page; provider links and metadata are preserved.")


class _Page(_Input):
    page_id: str = Field(..., min_length=1, title="Page ID")


class _Report(_Input):
    report_slug: str = Field(..., min_length=1, title="Report slug")


class _Tag(_Input):
    tag_id: str = Field(..., min_length=1, title="Tag ID")


class _TagAttributes(_Input):
    name: str | None = Field(None, min_length=1, max_length=45, title="Tag name")
    description: str | None = Field(None, title="Description")
    color: str | None = Field(None, pattern=r"^[A-Fa-f0-9]{6}$", title="Color", description="Six hex digits without #.")


class _TagPages(_Tag):
    page_ids: list[str] = Field(..., min_length=1, max_length=500, title="Page IDs")

    @field_validator("page_ids")
    @classmethod
    def pages(cls, value):
        if len(set(value)) != len(value) or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", v) for v in value):
            raise ValueError("Use unique GTmetrix page IDs")
        return value


class GTmetrixStartTestConfig(_Input):
    """Queue a performance test. This spends GTmetrix API credits."""
    operation: Literal["start_test"] = Field("start_test", json_schema_extra={"ui:hidden": True})
    url: str = Field(..., title="Page URL", description="Absolute HTTP or HTTPS URL to test.")
    location: str | None = Field(None, title="Location ID")
    browser: str | None = Field(None, title="Browser ID")
    report: Literal["lighthouse", "legacy", "lighthouse,legacy", "none"] = "lighthouse"
    retention: Literal[1, 6, 12, 24] = Field(1, description="Retention in months; longer retention costs extra credits.")
    adblock: bool = False
    video: bool = Field(False, description="Record video, costing extra credits.")
    stop_onload: bool = False
    throttle: str | None = Field(None, pattern=r"^\d+/\d+/\d+$", description="Download/upload Kbps/latency ms.")
    simulate_device: str | None = Field(None, title="Simulated device ID")

    @field_validator("url")
    @classmethod
    def page_url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Use an absolute HTTP or HTTPS page URL without credentials")
        return value


class GTmetrixListTestsConfig(_Paged):
    """Read one page of tests."""
    operation: Literal["list_tests"] = Field("list_tests", json_schema_extra={"ui:hidden": True})
    source: Literal["api", "on-demand", "monitored", "any"] | None = None
    state: Literal["queued", "started", "completed", "error"] | None = None


class GTmetrixGetTestConfig(_Input):
    """Read a test state and its report link."""
    operation: Literal["get_test"] = Field("get_test", json_schema_extra={"ui:hidden": True})
    test_id: str = Field(..., min_length=1, title="Test ID")


class GTmetrixGetReportConfig(_Report):
    """Read a performance report."""
    operation: Literal["get_report"] = Field("get_report", json_schema_extra={"ui:hidden": True})


class GTmetrixDeleteReportConfig(_Report):
    """Permanently delete a report."""
    operation: Literal["delete_report"] = Field("delete_report", json_schema_extra={"ui:hidden": True})


class GTmetrixRetestReportConfig(_Report):
    """Queue a new test using report settings; spends API credits."""
    operation: Literal["retest_report"] = Field("retest_report", json_schema_extra={"ui:hidden": True})


class GTmetrixListPagesConfig(_Paged):
    """Read one page of account pages."""
    operation: Literal["list_pages"] = Field("list_pages", json_schema_extra={"ui:hidden": True})


class GTmetrixGetPageConfig(_Page):
    """Read a page and monitoring settings."""
    operation: Literal["get_page"] = Field("get_page", json_schema_extra={"ui:hidden": True})


class GTmetrixDeletePageConfig(_Page):
    """Delete a page and its associated reports."""
    operation: Literal["delete_page"] = Field("delete_page", json_schema_extra={"ui:hidden": True})


class GTmetrixRetestPageConfig(_Page):
    """Queue a page retest; spends API credits."""
    operation: Literal["retest_page"] = Field("retest_page", json_schema_extra={"ui:hidden": True})


class GTmetrixUpdatePageMonitoringConfig(_Page):
    """Enable, change or disable recurring performance monitoring."""
    operation: Literal["update_page_monitoring"] = Field("update_page_monitoring", json_schema_extra={"ui:hidden": True})
    frequency: Literal["none", "no", "hourly", "daily", "weekly", "monthly"] = Field(..., description="none disables monitoring; enabling monitoring uses the account allowance.")


class GTmetrixListPageReportsConfig(_Page, _Paged):
    """Read one page of reports belonging to a page."""
    operation: Literal["list_page_reports"] = Field("list_page_reports", json_schema_extra={"ui:hidden": True})


class GTmetrixGetLatestPageReportConfig(_Page):
    """Read the latest performance report for a page."""
    operation: Literal["get_latest_page_report"] = Field("get_latest_page_report", json_schema_extra={"ui:hidden": True})


class GTmetrixListPageAlertEventsConfig(_Page, _Paged):
    """Read one page of performance alert events."""
    operation: Literal["list_page_alert_events"] = Field("list_page_alert_events", json_schema_extra={"ui:hidden": True})


class GTmetrixListTagsConfig(_Input):
    """List account page tags."""
    operation: Literal["list_tags"] = Field("list_tags", json_schema_extra={"ui:hidden": True})


class GTmetrixCreateTagConfig(_TagAttributes):
    """Create a page tag."""
    operation: Literal["create_tag"] = Field("create_tag", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, max_length=45, title="Tag name")


class GTmetrixGetTagConfig(_Tag):
    """Read a page tag."""
    operation: Literal["get_tag"] = Field("get_tag", json_schema_extra={"ui:hidden": True})


class GTmetrixUpdateTagConfig(_Tag, _TagAttributes):
    """Update supplied tag attributes."""
    operation: Literal["update_tag"] = Field("update_tag", json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def changes(self):
        if all(getattr(self, k) is None for k in ("name", "description", "color")):
            raise ValueError("Supply at least one tag attribute")
        return self


class GTmetrixDeleteTagConfig(_Tag):
    """Delete a page tag."""
    operation: Literal["delete_tag"] = Field("delete_tag", json_schema_extra={"ui:hidden": True})


class GTmetrixAttachTagPagesConfig(_TagPages):
    """Attach pages to a tag."""
    operation: Literal["attach_tag_pages"] = Field("attach_tag_pages", json_schema_extra={"ui:hidden": True})


class GTmetrixDetachTagPagesConfig(_TagPages):
    """Detach pages from a tag."""
    operation: Literal["detach_tag_pages"] = Field("detach_tag_pages", json_schema_extra={"ui:hidden": True})


class GTmetrixListLocationsConfig(_Input):
    """List available test locations."""
    operation: Literal["list_locations"] = Field("list_locations", json_schema_extra={"ui:hidden": True})


class GTmetrixListBrowsersConfig(_Input):
    """List available test browsers."""
    operation: Literal["list_browsers"] = Field("list_browsers", json_schema_extra={"ui:hidden": True})


class GTmetrixListSimulatedDevicesConfig(_Input):
    """List simulated device presets."""
    operation: Literal["list_simulated_devices"] = Field("list_simulated_devices", json_schema_extra={"ui:hidden": True})


class GTmetrixGetAccountStatusConfig(_Input):
    """Read API credits and plan access; the API-key ID is omitted."""
    operation: Literal["get_account_status"] = Field("get_account_status", json_schema_extra={"ui:hidden": True})


# GTmetrix's own MCP server: agents get its tools through a person's GTmetrix sign-in.
GtmetrixMcpCredential = mcp_credential("gtmetrix", "https://gtmetrix.com/mcp", app="GTmetrix")
GTmetrixCredential = Union[GTmetrixAPIKeyCredential, GtmetrixMcpCredential]


GTmetrixConfig = Annotated[Union[
    GTmetrixStartTestConfig,
    GTmetrixListTestsConfig,
    GTmetrixGetTestConfig,
    GTmetrixGetReportConfig,
    GTmetrixDeleteReportConfig,
    GTmetrixRetestReportConfig,
    GTmetrixListPagesConfig,
    GTmetrixGetPageConfig,
    GTmetrixDeletePageConfig,
    GTmetrixRetestPageConfig,
    GTmetrixUpdatePageMonitoringConfig,
    GTmetrixListPageReportsConfig,
    GTmetrixGetLatestPageReportConfig,
    GTmetrixListPageAlertEventsConfig,
    GTmetrixListTagsConfig,
    GTmetrixCreateTagConfig,
    GTmetrixGetTagConfig,
    GTmetrixUpdateTagConfig,
    GTmetrixDeleteTagConfig,
    GTmetrixAttachTagPagesConfig,
    GTmetrixDetachTagPagesConfig,
    GTmetrixListLocationsConfig,
    GTmetrixListBrowsersConfig,
    GTmetrixListSimulatedDevicesConfig,
    GTmetrixGetAccountStatusConfig
], Field(discriminator="operation")]


class GTmetrixFullConfig(NodeConfig[GTmetrixConfig, GTmetrixCredential]):
    pass


ROUTES = {'start_test': ('POST', '/tests'), 'list_tests': ('GET', '/tests'), 'get_test': ('GET', '/tests/{test_id}'), 'get_report': ('GET', '/reports/{report_slug}'), 'delete_report': ('DELETE', '/reports/{report_slug}'), 'retest_report': ('POST', '/reports/{report_slug}/retest'), 'list_pages': ('GET', '/pages'), 'get_page': ('GET', '/pages/{page_id}'), 'delete_page': ('DELETE', '/pages/{page_id}'), 'retest_page': ('POST', '/pages/{page_id}/retest'), 'update_page_monitoring': ('POST', '/pages/{page_id}/performance_monitor'), 'list_page_reports': ('GET', '/pages/{page_id}/reports'), 'get_latest_page_report': ('GET', '/pages/{page_id}/latest-report'), 'list_page_alert_events': ('GET', '/pages/{page_id}/performance_alert_events'), 'list_tags': ('GET', '/page_tags'), 'create_tag': ('POST', '/page_tags'), 'get_tag': ('GET', '/page_tags/{tag_id}'), 'update_tag': ('POST', '/page_tags/{tag_id}'), 'delete_tag': ('DELETE', '/page_tags/{tag_id}'), 'attach_tag_pages': ('POST', '/page_tags/{tag_id}/attach'), 'detach_tag_pages': ('POST', '/page_tags/{tag_id}/detach'), 'list_locations': ('GET', '/locations'), 'list_browsers': ('GET', '/browsers'), 'list_simulated_devices': ('GET', '/simulated-devices'), 'get_account_status': ('GET', '/status')}


def _redact(value, secret):
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items() if k not in {"api_key", "httpauth_password", "cookies"}}
    if isinstance(value, list):
        return [_redact(v, secret) for v in value]
    return value.replace(secret, "[redacted]") if isinstance(value, str) else value


class GTmetrixNode(WorkflowNode):
    integration_type = "automation-gtmetrix"
    credential_provider_labels = {"gtmetrix": "GTmetrix Account"}
    connection_evidence = ConnectionEvidence(noun="GTmetrix pages", operation="list_pages", label_keys=("url", "id"))

    @classmethod
    def get_config_model(cls):
        return GTmetrixFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a GTmetrix API key")
        credential = self.config.credentials
        op = self.config.config
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        for name in ("test_id", "report_slug", "page_id", "tag_id"):
            if "{" + name + "}" in path:
                path = path.replace("{" + name + "}", quote(values[name], safe=""))
        params = {}
        if isinstance(op, _Paged):
            params = {"page[size]": op.page_size, "page[number]": op.page_number}
        if op.operation == "list_tests":
            params.update({"filter[" + k + "]": values[k] for k in ("source", "state") if k in values})
        body = None
        if op.operation == "start_test":
            attrs = {k: v for k, v in values.items() if k != "operation"}
            for key in ("adblock", "video", "stop_onload"):
                attrs[key] = int(attrs[key])
            body = {"data": {"type": "test", "attributes": attrs}}
        elif op.operation == "update_page_monitoring":
            body = {"data": {"type": "performance_monitor", "attributes": {"frequency": op.frequency}}}
        elif op.operation in {"create_tag", "update_tag"}:
            body = {"data": {"type": "tag", "attributes": {k: values[k] for k in ("name", "description", "color") if k in values}}}
        elif op.operation in {"attach_tag_pages", "detach_tag_pages"}:
            body = {"page_ids": op.page_ids}
        headers = {"Accept": MEDIA_TYPE}
        if body is not None:
            headers["Content-Type"] = MEDIA_TYPE
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, headers=headers,
                auth=httpx.BasicAuth(credential.api_key, ""), params=params,
                **({"json": body} if body is not None else {}))
        if response.status_code not in {200, 201, 202}:
            # Preserve provider rejection text for manual-connect evidence.
            try:
                error = response.json()
                details = "; ".join(str(e.get("detail") or e.get("title") or "Request failed") for e in error.get("errors", []) if isinstance(e, dict))
            except (ValueError, AttributeError):
                details = "GTmetrix did not return a successful JSON response"
            return {"status": "error", "http_status": response.status_code,
                "error": _redact(details or "GTmetrix request failed", credential.api_key)}
        media = response.headers.get("content-type", "").split(";", 1)[0].lower().strip()
        if media not in {MEDIA_TYPE, "application/json"}:
            raise ValueError("Expected JSON from GTmetrix")
        result = response.json()
        if not isinstance(result, dict) or "errors" in result or not isinstance(result.get("data"), (dict, list)):
            raise ValueError("GTmetrix returned an unexpected JSON:API response")
        # /status returns the API key as data.id, even if it differs from the submitted key.
        if op.operation == "get_account_status":
            result["data"].pop("id", None)
        output = {"status": "success", "http_status": response.status_code, **result}
        if isinstance(result["data"], list):
            output["items"] = [{"id": row.get("id"), **row.get("attributes", {})} for row in result["data"] if isinstance(row, dict)]
            output["has_more"] = bool(result.get("links", {}).get("next"))
            if isinstance(op, _Paged):
                output["page_number"] = op.page_number
                output["next_page_number"] = op.page_number + 1 if output["has_more"] else None
        return _redact(output, credential.api_key)
