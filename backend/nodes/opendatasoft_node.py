"""Opendatasoft Explore v2.1: documented catalog reads and file exports.

The provider contract is read-only. Public data establishes reachability, not
account identity. Actions use one fixed-host GET; polling paginates the catalog.
"""
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.binary_output import BinaryOutput
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE = "https://data.opendatasoft.com/api/explore/v2.1"


class OpendatasoftAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Opendatasoft API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://data.opendatasoft.com/account/api-keys/",
            "x-credential-instructions": "Create an API key in your Opendatasoft account and paste it here. NoClick sends it as the documented apikey query parameter to data.opendatasoft.com. Public catalog reads prove reachability, not account identity.",
        })
    credential_type: Literal["opendatasoft_api_key"] = Field("opendatasoft_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("dataset_id", "record_id", check_fields=False)
    @classmethod
    def identifier(cls, value):
        if value in {".", ".."} or any(ord(c) < 32 for c in value):
            raise ValueError("Use a dataset or record identifier")
        return value


class ListDatasets(_Input):
    """Query catalog datasets."""
    operation: Literal["list_datasets"] = Field("list_datasets", json_schema_extra={"ui:hidden": True})
    select: Optional[str] = Field(None, min_length=1, max_length=4096, description="ODSQL expression; see the Opendatasoft Explore API documentation.")
    where: Optional[str] = Field(None, min_length=1, max_length=4096, description="ODSQL expression; see the Opendatasoft Explore API documentation.")
    order_by: Optional[str] = Field(None, min_length=1, max_length=4096, description="ODSQL expression; see the Opendatasoft Explore API documentation.")
    limit: int = Field(10, ge=-1, le=100)
    offset: int = Field(0, ge=0, le=10000, description="Zero-based page offset. Repeat with a higher offset to read subsequent pages.")
    refine: Optional[str] = Field(None, min_length=1, max_length=4096)
    exclude: Optional[str] = Field(None, min_length=1, max_length=4096)
    lang: Optional[Literal['en', 'fr', 'nl', 'pt', 'it', 'ar', 'de', 'es', 'ca', 'eu', 'sv']] = Field(None, min_length=1, max_length=4096)
    timezone: Optional[str] = Field(None, min_length=1, max_length=4096)
    group_by: Optional[str] = Field(None, min_length=1, max_length=4096, description="ODSQL expression; see the Opendatasoft Explore API documentation.")
    include_links: Optional[bool] = Field(None)
    include_app_metas: Optional[bool] = Field(None)


class ListCatalogExportFormats(_Input):
    """List export formats."""
    operation: Literal["list_catalog_export_formats"] = Field("list_catalog_export_formats", json_schema_extra={"ui:hidden": True})


class ListCatalogFacets(_Input):
    """List facet values."""
    operation: Literal["list_catalog_facets"] = Field("list_catalog_facets", json_schema_extra={"ui:hidden": True})
    facet: Optional[str] = Field(None, min_length=1, max_length=4096)
    refine: Optional[str] = Field(None, min_length=1, max_length=4096)
    exclude: Optional[str] = Field(None, min_length=1, max_length=4096)
    where: Optional[str] = Field(None, min_length=1, max_length=4096, description="ODSQL expression; see the Opendatasoft Explore API documentation.")
    timezone: Optional[str] = Field(None, min_length=1, max_length=4096)


class ListRecords(_Input):
    """Query dataset records."""
    operation: Literal["list_records"] = Field("list_records", json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., min_length=1, max_length=4096)
    select: Optional[str] = Field(None, min_length=1, max_length=4096, description="ODSQL expression; see the Opendatasoft Explore API documentation.")
    where: Optional[str] = Field(None, min_length=1, max_length=4096, description="ODSQL expression; see the Opendatasoft Explore API documentation.")
    group_by: Optional[str] = Field(None, min_length=1, max_length=4096, description="ODSQL expression; see the Opendatasoft Explore API documentation.")
    order_by: Optional[str] = Field(None, min_length=1, max_length=4096, description="ODSQL expression; see the Opendatasoft Explore API documentation.")
    limit: int = Field(10, ge=-1, le=100)
    offset: int = Field(0, ge=0, le=10000, description="Zero-based page offset. Repeat with a higher offset to read subsequent pages.")
    refine: Optional[str] = Field(None, min_length=1, max_length=4096)
    exclude: Optional[str] = Field(None, min_length=1, max_length=4096)
    lang: Optional[Literal['en', 'fr', 'nl', 'pt', 'it', 'ar', 'de', 'es', 'ca', 'eu', 'sv']] = Field(None, min_length=1, max_length=4096)
    timezone: Optional[str] = Field(None, min_length=1, max_length=4096)
    include_links: Optional[bool] = Field(None)
    include_app_metas: Optional[bool] = Field(None)


class ListDatasetExportFormats(_Input):
    """List export formats."""
    operation: Literal["list_dataset_export_formats"] = Field("list_dataset_export_formats", json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., min_length=1, max_length=4096)


class GetDataset(_Input):
    """Show dataset information."""
    operation: Literal["get_dataset"] = Field("get_dataset", json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., min_length=1, max_length=4096)
    select: Optional[str] = Field(None, min_length=1, max_length=4096, description="ODSQL expression; see the Opendatasoft Explore API documentation.")
    lang: Optional[Literal['en', 'fr', 'nl', 'pt', 'it', 'ar', 'de', 'es', 'ca', 'eu', 'sv']] = Field(None, min_length=1, max_length=4096)
    timezone: Optional[str] = Field(None, min_length=1, max_length=4096)
    include_links: Optional[bool] = Field(None)
    include_app_metas: Optional[bool] = Field(None)


class ListRecordFacets(_Input):
    """List dataset facets."""
    operation: Literal["list_record_facets"] = Field("list_record_facets", json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., min_length=1, max_length=4096)
    where: Optional[str] = Field(None, min_length=1, max_length=4096, description="ODSQL expression; see the Opendatasoft Explore API documentation.")
    refine: Optional[str] = Field(None, min_length=1, max_length=4096)
    exclude: Optional[str] = Field(None, min_length=1, max_length=4096)
    facet: Optional[str] = Field(None, min_length=1, max_length=4096)
    lang: Optional[Literal['en', 'fr', 'nl', 'pt', 'it', 'ar', 'de', 'es', 'ca', 'eu', 'sv']] = Field(None, min_length=1, max_length=4096)
    timezone: Optional[str] = Field(None, min_length=1, max_length=4096)


class ListAttachments(_Input):
    """List dataset attachments."""
    operation: Literal["list_attachments"] = Field("list_attachments", json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., min_length=1, max_length=4096)


class GetRecord(_Input):
    """Read a dataset record."""
    operation: Literal["get_record"] = Field("get_record", json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., min_length=1, max_length=4096)
    record_id: str = Field(..., min_length=1, max_length=4096)
    select: Optional[str] = Field(None, min_length=1, max_length=4096, description="ODSQL expression; see the Opendatasoft Explore API documentation.")
    lang: Optional[Literal['en', 'fr', 'nl', 'pt', 'it', 'ar', 'de', 'es', 'ca', 'eu', 'sv']] = Field(None, min_length=1, max_length=4096)
    timezone: Optional[str] = Field(None, min_length=1, max_length=4096)


class ExportCatalogCsv(_Input):
    """Export a catalog in CSV."""
    operation: Literal["export_catalog_csv"] = Field("export_catalog_csv", json_schema_extra={"ui:hidden": True})
    delimiter: Optional[Literal[';', ',', '\t', '|']] = Field(None, min_length=1, max_length=4096)
    list_separator: Optional[str] = Field(None, min_length=1, max_length=4096)
    quote_all: Optional[bool] = Field(None)
    with_bom: Optional[bool] = Field(None)


class ExportRecordsCsv(_Input):
    """Export a dataset in CSV."""
    operation: Literal["export_records_csv"] = Field("export_records_csv", json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., min_length=1, max_length=4096)
    delimiter: Optional[Literal[';', ',', '\t', '|']] = Field(None, min_length=1, max_length=4096)
    list_separator: Optional[str] = Field(None, min_length=1, max_length=4096)
    quote_all: Optional[bool] = Field(None)
    with_bom: Optional[bool] = Field(None)


class ExportRecordsParquet(_Input):
    """Export a dataset in Parquet."""
    operation: Literal["export_records_parquet"] = Field("export_records_parquet", json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., min_length=1, max_length=4096)
    parquet_compression: Optional[Literal['snappy', 'zstd']] = Field(None, min_length=1, max_length=4096)


class ExportRecordsGpx(_Input):
    """Export a dataset in GPX."""
    operation: Literal["export_records_gpx"] = Field("export_records_gpx", json_schema_extra={"ui:hidden": True})
    dataset_id: str = Field(..., min_length=1, max_length=4096)
    name_field: Optional[str] = Field(None, min_length=1, max_length=4096)
    description_field_list: Optional[str] = Field(None, min_length=1, max_length=4096)
    use_extension: Optional[bool] = Field(None)


class OnDatasetUpdated(PollTriggerConfigBase):
    """Watch all catalog datasets; first poll baselines, later changes emit."""
    operation: Literal["on_dataset_updated"] = Field("on_dataset_updated", title="On New or Updated Dataset",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": True,
                           "x-display-name": "On New or Updated Dataset"})
    where: Optional[str] = Field(None, min_length=1, max_length=4096, description="ODSQL catalog filter.")


OpendatasoftConfig = Annotated[Union[OnDatasetUpdated, ListDatasets, ListCatalogExportFormats, ListCatalogFacets, ListRecords, ListDatasetExportFormats, GetDataset, ListRecordFacets, ListAttachments, GetRecord, ExportCatalogCsv, ExportRecordsCsv, ExportRecordsParquet, ExportRecordsGpx], Field(discriminator="operation")]


class OpendatasoftFullConfig(NodeConfig[OpendatasoftConfig, OpendatasoftAPIKeyCredential]):
    pass


ROUTES = {'list_datasets': '/catalog/datasets', 'list_catalog_export_formats': '/catalog/exports', 'list_catalog_facets': '/catalog/facets', 'list_records': '/catalog/datasets/{dataset_id}/records', 'list_dataset_export_formats': '/catalog/datasets/{dataset_id}/exports', 'get_dataset': '/catalog/datasets/{dataset_id}', 'list_record_facets': '/catalog/datasets/{dataset_id}/facets', 'list_attachments': '/catalog/datasets/{dataset_id}/attachments', 'get_record': '/catalog/datasets/{dataset_id}/records/{record_id}', 'export_catalog_csv': '/catalog/exports/csv', 'export_records_csv': '/catalog/datasets/{dataset_id}/exports/csv', 'export_records_parquet': '/catalog/datasets/{dataset_id}/exports/parquet', 'export_records_gpx': '/catalog/datasets/{dataset_id}/exports/gpx'}
EXPORTS = {
    "export_catalog_csv": ("text/csv", "csv"),
    "export_records_csv": ("text/csv", "csv"),
    "export_records_parquet": ("application/octet-stream", "parquet"),
    "export_records_gpx": ("application/gpx+xml", "gpx"),
}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]").replace(quote(secret, safe=""), "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(k, secret): _redact(v, secret) for k, v in value.items()}
    return value


class OpendatasoftNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-opendatasoft"
    connection_evidence = ConnectionEvidence(operation="list_datasets", noun="Opendatasoft datasets", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return OpendatasoftFullConfig

    async def execute(self, inputs):
        cfg, credential = self.config.config, self.config.credentials
        if credential is None:
            raise ValueError("Attach an Opendatasoft API key")
        if isinstance(cfg, OnDatasetUpdated):
            return await self._poll_datasets(credential, cfg)
        return await self._read(cfg, credential)

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_dataset_count")) if config.get("operation") == "on_dataset_updated" else True

    async def _poll_datasets(self, credential, cfg):
        datasets = []
        for offset in range(0, 10000, 100):
            result = await self._read(ListDatasets(limit=100, offset=offset,
                order_by="modified desc", where=cfg.where), credential)
            if result.get("status") != "success":
                return result
            payload = result["data"]
            rows = payload["results"]
            total = payload.get("total_count")
            if not isinstance(total, int) or total < 0 or total >= 10000:
                raise ValueError("Catalog polling requires fewer than 10000 datasets; narrow the ODSQL filter")
            for row in rows:
                if not isinstance(row, dict) or not row.get("dataset_id") or not row.get("metas", {}).get("default", {}).get("modified"):
                    raise ValueError("Catalog polling requires dataset IDs and metas.default.modified timestamps")
            datasets.extend(rows)
            if offset + len(rows) >= total:
                break
            if not rows:
                raise ValueError("Catalog pagination ended before total_count")
        else:
            raise ValueError("Catalog polling exceeded the supported pagination range")
        fresh = await self._filter_unseen(datasets,
            lambda row: row["dataset_id"] + ":" + row["metas"]["default"]["modified"])
        return {"status": "success", "datasets": fresh, "new_dataset_count": len(fresh)}

    async def _read(self, cfg, credential):
        values = cfg.model_dump(exclude_none=True, exclude={"operation"})
        path = ROUTES[cfg.operation]
        for field in ("dataset_id", "record_id"):
            if field in values:
                path = path.replace("{" + field + "}", quote(values.pop(field), safe=""))
        params = {key: str(value).lower() if isinstance(value, bool) else value for key, value in values.items()}
        params["apikey"] = credential.api_key
        exported = EXPORTS.get(cfg.operation)
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request("GET", BASE + path, params=params,
                    headers={"Accept": exported[0] if exported else "application/json"})
        except httpx.HTTPError:
            # HTTP errors embed the URL, which contains the query credential.
            raise ValueError("Opendatasoft request failed") from None
        if response.status_code != 200:
            return {"status": "error", "http_status": response.status_code,
                "error": _redact(response.text, credential.api_key)}
        if exported:
            mime = response.headers.get("content-type", "").split(";", 1)[0].strip()
            if not mime or mime == "text/html":
                raise ValueError("Opendatasoft did not return an export file")
            return {"status": "success", "file": BinaryOutput(response.content, mime, "opendatasoft-export." + exported[1])}
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Opendatasoft returned invalid JSON") from None
        if not isinstance(payload, dict):
            raise ValueError("Opendatasoft returned an invalid JSON envelope")
        if "error" in payload or "error_code" in payload:
            return {"status": "error", "error": _redact(payload, credential.api_key)}
        collection = {
            "list_datasets": "results", "list_records": "results",
            "list_catalog_export_formats": "links", "list_dataset_export_formats": "links",
            "list_catalog_facets": "facets", "list_record_facets": "facets", "list_attachments": "attachments",
        }.get(cfg.operation)
        if collection and not isinstance(payload.get(collection), list):
            raise ValueError("Opendatasoft omitted the expected collection")
        return {"status": "success", "data": _redact(payload, credential.api_key)}
