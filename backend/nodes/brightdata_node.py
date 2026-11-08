"""Bright Data SERP, scraper jobs and dataset snapshot automation.

Contract: Bright Data's published SERP, scraper and DCA OpenAPI documents,
version 1.0.0. API keys are sent only to the fixed api.brightdata.com origin.
Each operation makes one API request; mutations are never retried or polled.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.brightdata.com"


class BrightdataAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Bright Data API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://brightdata.com/cp/setting/users",
            "x-credential-instructions": "Paste your Bright Data API key from Account settings → Users and API keys. Give it access to the scrapers and datasets your workflow uses. NoClick checks the connection by listing your account's scrapers.",
        })
    credential_type: Literal["brightdata_api_key"] = Field("brightdata_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API key, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def safe_identifiers(cls, value, info):
        if info.field_name.endswith("_id") and value is not None:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,255}", value):
                raise ValueError("Use a single Bright Data resource ID")
        return value


class BrightdataSearchSerpConfig(_Input):
    """Run a search engine request using your SERP zone. Usage is billed by Bright Data."""
    operation: Literal["search_serp"] = Field("search_serp", json_schema_extra={"ui:hidden": True})
    zone: str = Field(..., min_length=1, description="SERP zone name from Bright Data's control panel.")
    url: str = Field(..., description="Full search engine URL, for example https://www.google.com/search?q=pizza.")
    format: Literal["json", "raw"] = "json"
    country: str | None = Field(None, pattern=r"^[a-z]{2}$")
    asynchronous: bool = Field(False, description="Return an async response ID; fetch it with Get SERP response.")

    @field_validator("url")
    @classmethod
    def target_url(cls, value):
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Use a full public HTTP or HTTPS search URL")
        return value


class BrightdataGetSerpResponseConfig(_Input):
    """Fetch the result of an asynchronous SERP request."""
    operation: Literal["get_serp_response"] = Field("get_serp_response", json_schema_extra={"ui:hidden": True})
    response_id: str = Field(..., min_length=1)


class BrightdataListDatasetsConfig(_Input):
    """List the datasets available from Bright Data."""
    operation: Literal["list_datasets"] = Field("list_datasets", json_schema_extra={"ui:hidden": True})


class BrightdataListDatasetSnapshotsConfig(_Input):
    """List dataset snapshot metadata, optionally filtered by dataset or view."""
    operation: Literal["list_dataset_snapshots"] = Field("list_dataset_snapshots", json_schema_extra={"ui:hidden": True})
    dataset_id: str | None = None
    view_id: str | None = None
    status: Literal["canceled", "scheduled", "collecting", "digesting", "validating", "building", "delivering", "pending_discovery_input", "pending_pdp_input", "pending_developer_review", "pending_owner_review", "queued_for_developer_review", "ready", "failed", "rolling_back"] | None = None


class BrightdataGetDatasetSnapshotConfig(_Input):
    """Get a dataset snapshot’s metadata."""
    operation: Literal["get_dataset_snapshot"] = Field("get_dataset_snapshot", json_schema_extra={"ui:hidden": True})
    snapshot_id: str = Field(..., min_length=1, description="Snapshot ID returned by Bright Data.")


class BrightdataListDatasetSnapshotPartsConfig(_Input):
    """Count dataset download parts using the same format and batch size as the download."""
    operation: Literal["list_dataset_snapshot_parts"] = Field("list_dataset_snapshot_parts", json_schema_extra={"ui:hidden": True})
    snapshot_id: str = Field(..., min_length=1, description="Snapshot ID returned by Bright Data.")
    format: Literal["json", "ndjson", "jsonl", "csv"] = "json"
    batch_size: int | None = Field(None, ge=1000)


class BrightdataListDatasetViewsConfig(_Input):
    """List the account’s saved dataset views."""
    operation: Literal["list_dataset_views"] = Field("list_dataset_views", json_schema_extra={"ui:hidden": True})


class BrightdataListScrapersConfig(_Input):
    """List scrapers configured on the connected account, with their input schemas."""
    operation: Literal["list_scrapers"] = Field("list_scrapers", json_schema_extra={"ui:hidden": True})
    dataset_id: str | None = None
    domain: str | None = None


class BrightdataTriggerScrapeConfig(_Input):
    """Start a scraper job and return its snapshot ID. Bright Data bills the collection; this operation does not wait for completion."""
    operation: Literal["trigger_scrape"] = Field("trigger_scrape", json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., min_length=1, description="Scraper dataset ID from Bright Data.")
    inputs: str = Field(..., description="JSON array of input objects matching this scraper's input schema.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    include_errors: bool | None = None
    custom_output_fields: str | None = Field(None, description="Output columns separated by |.")
    limit_per_input: int | None = Field(None, ge=1)

    @field_validator("inputs")
    @classmethod
    def input_array(cls, value):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            raise ValueError("Enter a JSON array of scraper input objects") from None
        if not isinstance(parsed, list) or not parsed or any(not isinstance(row, dict) for row in parsed):
            raise ValueError("Enter a nonempty JSON array of scraper input objects")
        return value


class BrightdataGetScrapeProgressConfig(_Input):
    """Check whether a scraper snapshot is starting, running, ready, failed or canceled."""
    operation: Literal["get_scrape_progress"] = Field("get_scrape_progress", json_schema_extra={"ui:hidden": True})
    snapshot_id: str = Field(..., min_length=1, description="Snapshot ID returned by Bright Data.")


class BrightdataDownloadScrapeSnapshotConfig(_Input):
    """Download collected records as JSON data or an NDJSON/CSV file. Use a ready snapshot; large snapshots can be downloaded in parts."""
    operation: Literal["download_scrape_snapshot"] = Field("download_scrape_snapshot", json_schema_extra={"ui:hidden": True})
    snapshot_id: str = Field(..., min_length=1, description="Snapshot ID returned by Bright Data.")
    format: Literal["json", "ndjson", "jsonl", "csv"] = "json"
    batch_size: int | None = Field(None, ge=1000)
    part: int | None = Field(None, ge=1)


class BrightdataListScrapeSnapshotsConfig(_Input):
    """List one page of scraper snapshots. Increase skip by limit to retrieve the next page."""
    operation: Literal["list_scrape_snapshots"] = Field("list_scrape_snapshots", json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., min_length=1, description="Scraper dataset ID from Bright Data.")
    status: Literal["starting", "running", "ready", "failed", "canceled"] | None = None
    skip: int = Field(0, ge=0)
    limit: int = Field(100, ge=1, le=5000)
    from_date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    to_date: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class BrightdataGetScrapeLogConfig(_Input):
    """Retrieve the collection logs for a scraper snapshot."""
    operation: Literal["get_scrape_log"] = Field("get_scrape_log", json_schema_extra={"ui:hidden": True})
    snapshot_id: str = Field(..., min_length=1, description="Snapshot ID returned by Bright Data.")


class BrightdataListScrapeSnapshotPartsConfig(_Input):
    """Count the download parts for a scraper snapshot."""
    operation: Literal["list_scrape_snapshot_parts"] = Field("list_scrape_snapshot_parts", json_schema_extra={"ui:hidden": True})
    snapshot_id: str = Field(..., min_length=1, description="Snapshot ID returned by Bright Data.")
    format: Literal["json", "ndjson", "jsonl", "csv"] = "json"
    batch_size: int | None = Field(None, ge=1000)


class BrightdataGetScrapeInputConfig(_Input):
    """Download the original scraper inputs as a CSV file."""
    operation: Literal["get_scrape_input"] = Field("get_scrape_input", json_schema_extra={"ui:hidden": True})
    snapshot_id: str = Field(..., min_length=1, description="Snapshot ID returned by Bright Data.")


class BrightdataPauseScrapeConfig(_Input):
    """Pause a running collection."""
    operation: Literal["pause_scrape"] = Field("pause_scrape", json_schema_extra={"ui:hidden": True})
    snapshot_id: str = Field(..., min_length=1, description="Snapshot ID returned by Bright Data.")


class BrightdataResumeScrapeConfig(_Input):
    """Resume a paused collection."""
    operation: Literal["resume_scrape"] = Field("resume_scrape", json_schema_extra={"ui:hidden": True})
    snapshot_id: str = Field(..., min_length=1, description="Snapshot ID returned by Bright Data.")


class BrightdataCancelScrapeConfig(_Input):
    """Cancel a running collection."""
    operation: Literal["cancel_scrape"] = Field("cancel_scrape", json_schema_extra={"ui:hidden": True})
    snapshot_id: str = Field(..., min_length=1, description="Snapshot ID returned by Bright Data.")


class BrightdataRerunScrapeConfig(_Input):
    """Rerun a previous collection using its stored inputs. Bright Data bills the new collection."""
    operation: Literal["rerun_scrape"] = Field("rerun_scrape", json_schema_extra={"ui:hidden": True})
    snapshot_id: str = Field(..., min_length=1, description="Snapshot ID returned by Bright Data.")


class BrightdataGetDeliveryStatusConfig(_Input):
    """Check a delivery job’s status and delivered files."""
    operation: Literal["get_delivery_status"] = Field("get_delivery_status", json_schema_extra={"ui:hidden": True})
    delivery_id: str = Field(..., min_length=1)


BrightdataOperation = Annotated[Union[
    BrightdataSearchSerpConfig,
    BrightdataGetSerpResponseConfig,
    BrightdataListDatasetsConfig,
    BrightdataListDatasetSnapshotsConfig,
    BrightdataGetDatasetSnapshotConfig,
    BrightdataListDatasetSnapshotPartsConfig,
    BrightdataListDatasetViewsConfig,
    BrightdataListScrapersConfig,
    BrightdataTriggerScrapeConfig,
    BrightdataGetScrapeProgressConfig,
    BrightdataDownloadScrapeSnapshotConfig,
    BrightdataListScrapeSnapshotsConfig,
    BrightdataGetScrapeLogConfig,
    BrightdataListScrapeSnapshotPartsConfig,
    BrightdataGetScrapeInputConfig,
    BrightdataPauseScrapeConfig,
    BrightdataResumeScrapeConfig,
    BrightdataCancelScrapeConfig,
    BrightdataRerunScrapeConfig,
    BrightdataGetDeliveryStatusConfig,
], Field(discriminator="operation")]


class BrightdataNodeConfig(NodeConfig[BrightdataOperation, BrightdataAPIKeyCredential]):
    pass


ROUTES = {
    "search_serp": ("POST", "/request"),
    "get_serp_response": ("GET", "/response"),
    "list_datasets": ("GET", "/datasets/list"),
    "list_dataset_snapshots": ("GET", "/datasets/snapshots"),
    "get_dataset_snapshot": ("GET", "/datasets/snapshots/{id}"),
    "list_dataset_snapshot_parts": ("GET", "/datasets/snapshots/{id}/parts"),
    "list_dataset_views": ("GET", "/datasets/views"),
    "list_scrapers": ("GET", "/datasets/v3/scrapers"),
    "trigger_scrape": ("POST", "/datasets/v3/trigger"),
    "get_scrape_progress": ("GET", "/datasets/v3/progress/{snapshot_id}"),
    "download_scrape_snapshot": ("GET", "/datasets/v3/snapshot/{snapshot_id}"),
    "list_scrape_snapshots": ("GET", "/datasets/v3/snapshots"),
    "get_scrape_log": ("GET", "/datasets/v3/log/{snapshot_id}"),
    "list_scrape_snapshot_parts": ("GET", "/datasets/v3/snapshot/{snapshot_id}/parts"),
    "get_scrape_input": ("GET", "/datasets/v3/snapshot/{snapshot_id}/input"),
    "pause_scrape": ("POST", "/datasets/v3/snapshot/{snapshot_id}/pause"),
    "resume_scrape": ("POST", "/datasets/v3/snapshot/{snapshot_id}/resume"),
    "cancel_scrape": ("POST", "/datasets/v3/snapshot/{snapshot_id}/cancel"),
    "rerun_scrape": ("POST", "/datasets/v3/snapshot/{snapshot_id}/rerun"),
    "get_delivery_status": ("GET", "/datasets/v3/delivery/{delivery_id}"),
}


class BrightdataNode(WorkflowNode):
    integration_type = "automation-brightdata"
    connection_evidence = ConnectionEvidence(operation="list_scrapers", noun="scrapers", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return BrightdataNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Bright Data API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, path = ROUTES[config.operation]
        params = config.model_dump(exclude_none=True, exclude={"operation"})
        for placeholder in ("snapshot_id", "id", "delivery_id"):
            if "{" + placeholder + "}" in path:
                field = "snapshot_id" if placeholder == "id" else placeholder
                path = path.replace("{" + placeholder + "}", quote(params.pop(field), safe=""))
        body = None
        if config.operation == "search_serp":
            asynchronous = params.pop("asynchronous")
            body, params = params, {"async": asynchronous}
        elif config.operation == "trigger_scrape":
            body = json.loads(params.pop("inputs"))
        params = {name: str(value).lower() if isinstance(value, bool) else value for name, value in params.items()}
        try:
            async with guarded_async_client(timeout=120, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json, text/plain, text/csv, text/html"},
                    **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            # No retries: a failed transport may still have started a paid job.
            return {"status": "error", "error": "Bright Data request did not complete; check the provider before retrying a collection", "operation": config.operation}
        if not 200 <= response.status_code < 300:
            message = response.text.replace(key, "[redacted]")[:2000]
            return {"status": "error", "error": message or "Bright Data rejected the request", "http_status": response.status_code, "operation": config.operation}
        output = {"status": "success", "operation": config.operation, "http_status": response.status_code}
        if response.headers.get("x-response-id"):
            output["response_id"] = response.headers["x-response-id"]
        if config.operation == "get_scrape_input" or (config.operation == "download_scrape_snapshot" and config.format != "json"):
            extension = "csv" if config.operation == "get_scrape_input" else config.format
            output["file"] = BinaryOutput(data=response.content,
                content_type="text/csv" if extension == "csv" else "application/x-ndjson",
                filename=f"{config.snapshot_id}.{extension}")
        else:
            try:
                data = response.json()
            except ValueError:
                data = response.text
            if isinstance(data, dict) and "id" not in data and "snapshot_id" not in data and (data.get("error") or data.get("validation_errors")):
                return {"status": "error", "error": json.dumps(data).replace(key, "[redacted]"), "http_status": response.status_code, "operation": config.operation}
            output["data"] = data
        return output
