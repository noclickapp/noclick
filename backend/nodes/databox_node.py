"""Databox v2 API operations. Contract: https://developers.databox.com/docs/api/api.databox.com

Each operation performs one documented request; lists return one explicit page.
Dataset ingestion acknowledges submission, not completion of asynchronous ingestion.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import SSRFError, guarded_async_client

BASE_URL = "https://api.databox.com"


class DataboxAPIKey(BaseModel):
    model_config = ConfigDict(
        title="Databox API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.databox.com/docs/api/authentication",
            "x-credential-instructions": "Create an API key in Account Management > Profile > Password & Security (admin access required), then paste it here. NoClick sends it in the x-api-key header to api.databox.com and verifies it by reading your profile. Use a key with access to the resources your workflow needs.",
        },
    )
    credential_type: Literal["databox_api_key"] = Field(
        "databox_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"}
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        return clean_secret(value)


class _Config(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class _AccountConfig(_Config):
    account_id: int | None = Field(
        None,
        title="Account ID",
        description="Optional managed account to act on; omit to use the API key's organization.",
    )


class _PageConfig(_AccountConfig):
    page: int = Field(
        0, ge=0, description="Zero-based page number. Each run returns one page."
    )
    page_size: int = Field(25, ge=1, le=100)
    search: str | None = Field(None, min_length=1)


class DatasetColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., min_length=1)
    dataType: Literal["datetime", "number", "string"]


class DateRange(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_date: date = Field(..., alias="from")
    to: date
    granularity: Literal[
        "daily", "weekly", "monthly", "quarterly", "yearly", "allTime"
    ] = "daily"

    @model_validator(mode="after")
    def ordered(self):
        if self.from_date > self.to:
            raise ValueError("Date range start must be on or before its end")
        return self


class DataboxGetProfile(_Config):
    """Get profile."""

    operation: Literal["get_profile"] = Field(
        "get_profile", json_schema_extra={"ui:hidden": True}
    )


class DataboxGetOrganization(_AccountConfig):
    """Get organization."""

    operation: Literal["get_organization"] = Field(
        "get_organization", json_schema_extra={"ui:hidden": True}
    )


class DataboxListAccounts(_PageConfig):
    """List accounts."""

    operation: Literal["list_accounts"] = Field(
        "list_accounts", json_schema_extra={"ui:hidden": True}
    )


class DataboxListDashboards(_PageConfig):
    """List dashboards."""

    operation: Literal["list_dashboards"] = Field(
        "list_dashboards", json_schema_extra={"ui:hidden": True}
    )


class DataboxRenameDashboard(_AccountConfig):
    """Rename dashboard."""

    operation: Literal["rename_dashboard"] = Field(
        "rename_dashboard", json_schema_extra={"ui:hidden": True}
    )
    dashboard_id: int
    name: str = Field(..., min_length=1, max_length=65, pattern=r"^[^\x00-\x1f\x7f]+$")


class DataboxGetDashboardMetrics(_AccountConfig):
    """Get dashboard metrics."""

    operation: Literal["get_dashboard_metrics"] = Field(
        "get_dashboard_metrics", json_schema_extra={"ui:hidden": True}
    )
    dashboard_id: int


class DataboxListDataSources(_PageConfig):
    """List data sources."""

    operation: Literal["list_data_sources"] = Field(
        "list_data_sources", json_schema_extra={"ui:hidden": True}
    )


class DataboxGetDataSource(_AccountConfig):
    """Get data source."""

    operation: Literal["get_data_source"] = Field(
        "get_data_source", json_schema_extra={"ui:hidden": True}
    )
    data_source_id: int


class DataboxRenameDataSource(_AccountConfig):
    """Rename data source."""

    operation: Literal["rename_data_source"] = Field(
        "rename_data_source", json_schema_extra={"ui:hidden": True}
    )
    data_source_id: int
    name: str = Field(..., min_length=1)


class DataboxListDatasets(_PageConfig):
    """List datasets."""

    operation: Literal["list_datasets"] = Field(
        "list_datasets", json_schema_extra={"ui:hidden": True}
    )
    data_source_id: int | None = None


class DataboxGetDataset(_AccountConfig):
    """Get dataset."""

    operation: Literal["get_dataset"] = Field(
        "get_dataset", json_schema_extra={"ui:hidden": True}
    )
    dataset_id: int


class DataboxCreateDataset(_AccountConfig):
    """Create dataset."""

    operation: Literal["create_dataset"] = Field(
        "create_dataset", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(..., min_length=1)
    data_source_id: int
    columns: list[DatasetColumn] = Field(
        ..., description="Column definitions for the dataset schema."
    )
    primary_key: list[str] | None = None
    idempotency_key: str | None = Field(
        None, min_length=1, max_length=255, pattern=r"^[ -~]+$"
    )


class DataboxRenameDataset(_AccountConfig):
    """Rename dataset."""

    operation: Literal["rename_dataset"] = Field(
        "rename_dataset", json_schema_extra={"ui:hidden": True}
    )
    dataset_id: int
    name: str = Field(..., min_length=1)


class DataboxGetDatasetData(_AccountConfig):
    """Get dataset data."""

    operation: Literal["get_dataset_data"] = Field(
        "get_dataset_data", json_schema_extra={"ui:hidden": True}
    )
    dataset_id: int
    page: int = Field(0, ge=0)
    page_size: int = Field(200, ge=1, le=1000)
    sort_by: str | None = None
    sort_order: Literal["asc", "desc"] = "asc"


class DataboxIngestDatasetData(_AccountConfig):
    """Ingest dataset data."""

    operation: Literal["ingest_dataset_data"] = Field(
        "ingest_dataset_data", json_schema_extra={"ui:hidden": True}
    )
    dataset_id: int
    records: list[dict[str, Any]] = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="Records keyed by dataset column ID. Submission is asynchronous.",
    )
    idempotency_key: str | None = Field(
        None, min_length=1, max_length=255, pattern=r"^[ -~]+$"
    )


class DataboxGetDatasetSchema(_AccountConfig):
    """Get dataset schema."""

    operation: Literal["get_dataset_schema"] = Field(
        "get_dataset_schema", json_schema_extra={"ui:hidden": True}
    )
    dataset_id: int


class DataboxListDatasetIngestions(_AccountConfig):
    """List dataset ingestions."""

    operation: Literal["list_dataset_ingestions"] = Field(
        "list_dataset_ingestions", json_schema_extra={"ui:hidden": True}
    )
    dataset_id: int
    page: int = Field(0, ge=0)
    page_size: int = Field(25, ge=1, le=100)


class DataboxGetDatasetIngestion(_AccountConfig):
    """Get dataset ingestion."""

    operation: Literal["get_dataset_ingestion"] = Field(
        "get_dataset_ingestion", json_schema_extra={"ui:hidden": True}
    )
    dataset_id: int
    ingestion_id: UUID


class DataboxListMetrics(_PageConfig):
    """List metrics."""

    operation: Literal["list_metrics"] = Field(
        "list_metrics", json_schema_extra={"ui:hidden": True}
    )
    source_id: int | None = None


class DataboxGetMetric(_AccountConfig):
    """Get metric."""

    operation: Literal["get_metric"] = Field(
        "get_metric", json_schema_extra={"ui:hidden": True}
    )
    metric_id: str = Field(..., min_length=1)


class DataboxRenameMetric(_AccountConfig):
    """Rename metric."""

    operation: Literal["rename_metric"] = Field(
        "rename_metric", json_schema_extra={"ui:hidden": True}
    )
    metric_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)


class DataboxGetMetricData(_AccountConfig):
    """Get metric data."""

    operation: Literal["get_metric_data"] = Field(
        "get_metric_data", json_schema_extra={"ui:hidden": True}
    )
    metric_id: str = Field(..., min_length=1)
    date_range: DateRange
    source_id: int | None = None
    dimension_ids: list[str] | None = None


# Databox's own MCP server: agents get its tools through a person's Databox sign-in.
DataboxMcpCredential = mcp_credential("databox", "https://mcp.databox.com/mcp", app="Databox")
DataboxCredential = Union[DataboxAPIKey, DataboxMcpCredential]


DataboxConfig = Annotated[
    Union[
        DataboxGetProfile,
        DataboxGetOrganization,
        DataboxListAccounts,
        DataboxListDashboards,
        DataboxRenameDashboard,
        DataboxGetDashboardMetrics,
        DataboxListDataSources,
        DataboxGetDataSource,
        DataboxRenameDataSource,
        DataboxListDatasets,
        DataboxGetDataset,
        DataboxCreateDataset,
        DataboxRenameDataset,
        DataboxGetDatasetData,
        DataboxIngestDatasetData,
        DataboxGetDatasetSchema,
        DataboxListDatasetIngestions,
        DataboxGetDatasetIngestion,
        DataboxListMetrics,
        DataboxGetMetric,
        DataboxRenameMetric,
        DataboxGetMetricData,
    ],
    Field(discriminator="operation"),
]


class DataboxFullConfig(NodeConfig[DataboxConfig, DataboxCredential]):
    pass


ROUTES = {
    "get_profile": ("GET", "/v2/profile", []),
    "get_organization": ("GET", "/v2/organization", []),
    "list_accounts": ("GET", "/v2/accounts", []),
    "list_dashboards": ("GET", "/v2/dashboards", []),
    "rename_dashboard": ("PATCH", "/v2/dashboards/{dashboard_id}", ["name"]),
    "get_dashboard_metrics": ("GET", "/v2/dashboards/{dashboard_id}/metrics", []),
    "list_data_sources": ("GET", "/v2/data-sources", []),
    "get_data_source": ("GET", "/v2/data-sources/{data_source_id}", []),
    "rename_data_source": ("PATCH", "/v2/data-sources/{data_source_id}", ["name"]),
    "list_datasets": ("GET", "/v2/datasets", []),
    "get_dataset": ("GET", "/v2/datasets/{dataset_id}", []),
    "create_dataset": (
        "POST",
        "/v2/datasets",
        ["name", "data_source_id", "columns", "primary_key"],
    ),
    "rename_dataset": ("PATCH", "/v2/datasets/{dataset_id}", ["name"]),
    "get_dataset_data": ("GET", "/v2/datasets/{dataset_id}/data", []),
    "ingest_dataset_data": ("POST", "/v2/datasets/{dataset_id}/data", ["records"]),
    "get_dataset_schema": ("GET", "/v2/datasets/{dataset_id}/schema", []),
    "list_dataset_ingestions": ("GET", "/v2/datasets/{dataset_id}/ingestions", []),
    "get_dataset_ingestion": (
        "GET",
        "/v2/datasets/{dataset_id}/ingestions/{ingestion_id}",
        [],
    ),
    "list_metrics": ("GET", "/v2/metrics", []),
    "get_metric": ("GET", "/v2/metrics/{metric_id}", []),
    "rename_metric": ("PATCH", "/v2/metrics/{metric_id}", ["name"]),
    "get_metric_data": (
        "POST",
        "/v2/metrics/{metric_id}/data",
        ["date_range", "source_id", "dimension_ids"],
    ),
}

WIRE_NAMES = {
    "page_size": "pageSize",
    "sort_by": "sortBy",
    "sort_order": "sortOrder",
    "data_source_id": "dataSourceId",
    "source_id": "sourceId",
    "columns": "schema",
    "primary_key": "primaryKey",
    "date_range": "dateRange",
    "dimension_ids": "dimensionIds",
}


class DataboxNode(WorkflowNode):
    integration_type = "automation-databox"
    credential_provider_labels = {"databox": "Databox Account"}
    connection_evidence = ConnectionEvidence(
        noun="Databox profile", identity_operation="get_profile"
    )

    @classmethod
    def get_config_model(cls):
        return DataboxFullConfig

    async def execute(self, inputs):
        if (
            not isinstance(self.config, DataboxFullConfig)
            or not self.config.credentials
        ):
            raise ValueError("Connect a Databox API key")
        config = self.config.config
        method, route, body_fields = ROUTES[config.operation]
        values = config.model_dump(mode="json", by_alias=True, exclude_none=True)
        path_fields = set()
        for field in (
            "dashboard_id",
            "data_source_id",
            "dataset_id",
            "metric_id",
            "ingestion_id",
        ):
            if "{" + field + "}" in route:
                route = route.replace(
                    "{" + field + "}", quote(str(values[field]), safe="")
                )
                path_fields.add(field)
        headers = {
            "x-api-key": self.config.credentials.api_key,
            "Accept": "application/json",
        }
        if "account_id" in values and config.operation != "list_accounts":
            headers["x-account-id"] = str(values["account_id"])
        if "idempotency_key" in values:
            headers["Idempotency-Key"] = values["idempotency_key"]
        body = (
            {WIRE_NAMES.get(k, k): values[k] for k in body_fields if k in values}
            if body_fields
            else None
        )
        params = {
            WIRE_NAMES.get(k, k): v
            for k, v in values.items()
            if k
            not in path_fields
            | set(body_fields)
            | {"operation", "account_id", "idempotency_key"}
        }
        output = {"operation": config.operation}
        try:
            async with guarded_async_client(
                timeout=30, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    method,
                    BASE_URL + route,
                    headers=headers,
                    params=params,
                    **({"json": body} if body is not None else {}),
                )
            if len(response.content) > 10_000_000:
                raise ValueError("Databox response exceeds the response limit")
            payload = response.json()
            if (
                not 200 <= response.status_code < 300
                or not isinstance(payload, dict)
                or payload.get("status") == "error"
                or payload.get("errors")
            ):
                message = (
                    payload.get("message") or payload.get("error")
                    if isinstance(payload, dict)
                    else None
                )
                if isinstance(payload, dict) and isinstance(
                    payload.get("errors"), list
                ):
                    messages = [
                        error["message"]
                        for error in payload["errors"]
                        if isinstance(error, dict)
                        and isinstance(error.get("message"), str)
                    ]
                    if messages:
                        message = "; ".join(messages)
                if not isinstance(message, str):
                    message = "Databox did not confirm this request"
                return {
                    **output,
                    "status": "error",
                    "http_status": response.status_code,
                    "error": message.replace(
                        self.config.credentials.api_key, "[redacted]"
                    )[:2000],
                }
            if (
                payload.get("status") != "success"
                or "data" not in payload
                or not isinstance(payload["data"], (dict, list))
            ):
                raise ValueError("Databox response envelope is incomplete")
            result = {
                **output,
                "status": "success",
                "data": payload["data"],
                "http_status": response.status_code,
            }
            data = payload["data"]
            if isinstance(data, dict) and "pagination" in data:
                pagination = data["pagination"]
                if not isinstance(pagination, dict) or any(
                    type(pagination.get(k)) is not int
                    for k in ("page", "pageSize", "totalItems")
                ):
                    raise ValueError("Databox pagination is incomplete")
                page, size, total = (
                    pagination[k] for k in ("page", "pageSize", "totalItems")
                )
                if page < 0 or size <= 0 or total < 0:
                    raise ValueError("Databox pagination is invalid")
                result["next_page"] = page + 1 if (page + 1) * size < total else None
            if config.operation == "ingest_dataset_data":
                result["ingestion_completed"] = False
            # Avoid accidental credential echoes without altering provider data types.
            return json.loads(
                json.dumps(result).replace(
                    self.config.credentials.api_key, "[redacted]"
                )
            )
        except (ValueError, httpx.HTTPError, SSRFError):
            return {
                **output,
                "status": "error",
                "error": "Databox returned an invalid response or the request could not be completed; inspect writes before retrying",
            }
