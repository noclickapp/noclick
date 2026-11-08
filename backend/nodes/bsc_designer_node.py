"""BSC Designer Online API 1.0, https://www.webbsc.com/v2/api-docs.

Each operation sends exactly one provider request. Writes are never retried.
Dates use the provider's documented yyyy-MM-dd wire format.
"""
from __future__ import annotations

from datetime import date as Date
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://www.webbsc.com"


class BscDesignerAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="BSC Designer API Token", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://bscdesigner.com/webbsc_manual/api.htm",
        "x-credential-instructions": "In BSC Designer, open Settings, then Integrations, then Add API Key. Paste the generated token here. NoClick sends it in the token header to www.webbsc.com. Connecting reads the scorecards owned by your account.",
    })
    credential_type: Literal["bsc_designer_api_token"] = Field("bsc_designer_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def validate_token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the API token without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)


class BscDesignerDocumentCreate(_Input):
    parentGroupId: int | None = Field(None, ge=0, description="Optional destination group ID; omit for the default location.")


class BscDesignerDocumentUpdate(_Input):
    alias: str | None = None
    description: str | None = None
    name: str | None = None
    sharedForPublic: bool | None = None
    sharedForRegRW: bool | None = None


class BscDesignerIndicatorUpdate(_Input):
    description: str | None = None
    indicatorType: Literal["LEADING", "LAGGING"] | None = None
    name: str | None = None


class BscDesignerValue(_Input):
    baseline: float | None = None
    max: float | None = None
    min: float | None = None
    target: float | None = None
    value: float | None = None


class BscDesignerIndicatorReference(_Input):
    guid: str = Field(..., min_length=1)


class BscDesignerBatchValue(BscDesignerValue):
    item: BscDesignerIndicatorReference


class BscDesignerBatchUpdate(_Input):
    values: list[BscDesignerBatchValue] = Field(..., min_length=1)


class BscDesignerBatchRead(_Input):
    guids: list[str] = Field(..., min_length=1)


class BscDesignerCustomValue(_Input):
    text: str | None = Field(None, description="Text field value; explicitly send null or an empty string to clear.")
    value: float | None = Field(None, description="Numeric field value; explicitly send null to clear.")


def _resource(value):
    if value in {".", ".."}:
        raise ValueError("Use a resource ID or alias, not a relative path segment")
    return value


Resource = Annotated[str, AfterValidator(_resource), Field(min_length=1, max_length=512, pattern=r"^[^/\\?#\s]+$")]


class BscDesignerListDocumentsConfig(_Input):
    """List owned scorecards."""
    operation: Literal["list_documents"] = Field("list_documents", json_schema_extra={"ui:hidden": True})


class BscDesignerGetDocumentConfig(_Input):
    """Get a scorecard."""
    operation: Literal["get_document"] = Field("get_document", json_schema_extra={"ui:hidden": True})
    document_id: Resource = Field(..., description="Scorecard document ID or alias.")


class BscDesignerCreateDocumentConfig(_Input):
    """Create an empty scorecard."""
    operation: Literal["create_document"] = Field("create_document", json_schema_extra={"ui:hidden": True})
    document: BscDesignerDocumentCreate


class BscDesignerUpdateDocumentConfig(_Input):
    """Update scorecard properties."""
    operation: Literal["update_document"] = Field("update_document", json_schema_extra={"ui:hidden": True})
    document_id: int = Field(..., ge=1, le=9223372036854775807, description="Numeric document ID.")
    document: BscDesignerDocumentUpdate


class BscDesignerDeleteDocumentConfig(_Input):
    """Delete a scorecard."""
    operation: Literal["delete_document"] = Field("delete_document", json_schema_extra={"ui:hidden": True})
    document_id: int = Field(..., ge=1, le=9223372036854775807, description="Numeric document ID.")


class BscDesignerGetDocumentTreeConfig(_Input):
    """Get the owned scorecard tree."""
    operation: Literal["get_document_tree"] = Field("get_document_tree", json_schema_extra={"ui:hidden": True})


class BscDesignerListIndicatorsConfig(_Input):
    """List indicators in a scorecard."""
    operation: Literal["list_indicators"] = Field("list_indicators", json_schema_extra={"ui:hidden": True})
    document_id: Resource = Field(..., description="Scorecard document ID or alias.")


class BscDesignerGetIndicatorTreeConfig(_Input):
    """Get the indicator hierarchy."""
    operation: Literal["get_indicator_tree"] = Field("get_indicator_tree", json_schema_extra={"ui:hidden": True})
    document_id: Resource = Field(..., description="Scorecard document ID or alias.")


class BscDesignerGetIndicatorConfig(_Input):
    """Get indicator properties."""
    operation: Literal["get_indicator"] = Field("get_indicator", json_schema_extra={"ui:hidden": True})
    document_id: Resource = Field(..., description="Scorecard document ID or alias.")
    indicator_guid: Resource = Field(..., description="Indicator GUID from the indicator list.")


class BscDesignerUpdateIndicatorConfig(_Input):
    """Update indicator properties."""
    operation: Literal["update_indicator"] = Field("update_indicator", json_schema_extra={"ui:hidden": True})
    document_id: Resource = Field(..., description="Scorecard document ID or alias.")
    indicator_guid: Resource = Field(..., description="Indicator GUID from the indicator list.")
    indicator: BscDesignerIndicatorUpdate


class BscDesignerGetIndicatorValueConfig(_Input):
    """Get one indicator value at a date."""
    operation: Literal["get_indicator_value"] = Field("get_indicator_value", json_schema_extra={"ui:hidden": True})
    document_id: Resource = Field(..., description="Scorecard document ID or alias.")
    indicator_guid: Resource = Field(..., description="Indicator GUID from the indicator list.")
    date: Date = Field(..., description="KPI date in yyyy-MM-dd format.")


class BscDesignerSetIndicatorValueConfig(_Input):
    """Set one indicator value at a date."""
    operation: Literal["set_indicator_value"] = Field("set_indicator_value", json_schema_extra={"ui:hidden": True})
    document_id: Resource = Field(..., description="Scorecard document ID or alias.")
    indicator_guid: Resource = Field(..., description="Indicator GUID from the indicator list.")
    date: Date = Field(..., description="KPI date in yyyy-MM-dd format.")
    data: BscDesignerValue


class BscDesignerGetAllValuesConfig(_Input):
    """Get all indicator values at a date."""
    operation: Literal["get_all_values"] = Field("get_all_values", json_schema_extra={"ui:hidden": True})
    document_id: Resource = Field(..., description="Scorecard document ID or alias.")
    date: Date = Field(..., description="KPI date in yyyy-MM-dd format.")


class BscDesignerGetSelectedValuesConfig(_Input):
    """Get selected indicator values at a date."""
    operation: Literal["get_selected_values"] = Field("get_selected_values", json_schema_extra={"ui:hidden": True})
    document_id: Resource = Field(..., description="Scorecard document ID or alias.")
    date: Date = Field(..., description="KPI date in yyyy-MM-dd format.")
    selection: BscDesignerBatchRead


class BscDesignerSetSelectedValuesConfig(_Input):
    """Set multiple indicator values at a date."""
    operation: Literal["set_selected_values"] = Field("set_selected_values", json_schema_extra={"ui:hidden": True})
    document_id: Resource = Field(..., description="Scorecard document ID or alias.")
    date: Date = Field(..., description="KPI date in yyyy-MM-dd format.")
    data: BscDesignerBatchUpdate


class BscDesignerListMapsConfig(_Input):
    """List scorecard strategy maps."""
    operation: Literal["list_maps"] = Field("list_maps", json_schema_extra={"ui:hidden": True})
    document_id: Resource = Field(..., description="Scorecard document ID or alias.")


class BscDesignerRefreshMapConfig(_Input):
    """Rerun the strategy map wizard."""
    operation: Literal["refresh_map"] = Field("refresh_map", json_schema_extra={"ui:hidden": True})
    document_id: Resource = Field(..., description="Scorecard document ID or alias.")
    map_id: Resource


class BscDesignerRefreshAllMapsConfig(_Input):
    """Rerun all strategy map wizards."""
    operation: Literal["refresh_all_maps"] = Field("refresh_all_maps", json_schema_extra={"ui:hidden": True})
    document_id: Resource = Field(..., description="Scorecard document ID or alias.")


class BscDesignerGetOrganizationConfig(_Input):
    """Get organization settings and strategy."""
    operation: Literal["get_organization"] = Field("get_organization", json_schema_extra={"ui:hidden": True})


class BscDesignerListCustomFieldsConfig(_Input):
    """List account custom field definitions."""
    operation: Literal["list_custom_fields"] = Field("list_custom_fields", json_schema_extra={"ui:hidden": True})


class BscDesignerListIndicatorCustomValuesConfig(_Input):
    """List filled custom values for an indicator."""
    operation: Literal["list_indicator_custom_values"] = Field("list_indicator_custom_values", json_schema_extra={"ui:hidden": True})
    document_id: Resource = Field(..., description="Scorecard document ID or alias.")
    indicator_guid: Resource = Field(..., description="Indicator GUID from the indicator list.")


class BscDesignerGetCustomValueConfig(_Input):
    """Get one indicator custom field value."""
    operation: Literal["get_custom_value"] = Field("get_custom_value", json_schema_extra={"ui:hidden": True})
    document_id: Resource = Field(..., description="Scorecard document ID or alias.")
    indicator_guid: Resource = Field(..., description="Indicator GUID from the indicator list.")
    custom_field_id: int = Field(..., ge=1, le=9223372036854775807)


class BscDesignerSetCustomValueConfig(_Input):
    """Set or clear an indicator custom field value."""
    operation: Literal["set_custom_value"] = Field("set_custom_value", json_schema_extra={"ui:hidden": True})
    document_id: Resource = Field(..., description="Scorecard document ID or alias.")
    indicator_guid: Resource = Field(..., description="Indicator GUID from the indicator list.")
    custom_field_id: int = Field(..., ge=1, le=9223372036854775807)
    data: BscDesignerCustomValue


BscDesignerConfig = Annotated[Union[
    BscDesignerListDocumentsConfig,
    BscDesignerGetDocumentConfig,
    BscDesignerCreateDocumentConfig,
    BscDesignerUpdateDocumentConfig,
    BscDesignerDeleteDocumentConfig,
    BscDesignerGetDocumentTreeConfig,
    BscDesignerListIndicatorsConfig,
    BscDesignerGetIndicatorTreeConfig,
    BscDesignerGetIndicatorConfig,
    BscDesignerUpdateIndicatorConfig,
    BscDesignerGetIndicatorValueConfig,
    BscDesignerSetIndicatorValueConfig,
    BscDesignerGetAllValuesConfig,
    BscDesignerGetSelectedValuesConfig,
    BscDesignerSetSelectedValuesConfig,
    BscDesignerListMapsConfig,
    BscDesignerRefreshMapConfig,
    BscDesignerRefreshAllMapsConfig,
    BscDesignerGetOrganizationConfig,
    BscDesignerListCustomFieldsConfig,
    BscDesignerListIndicatorCustomValuesConfig,
    BscDesignerGetCustomValueConfig,
    BscDesignerSetCustomValueConfig,
], Field(discriminator="operation")]


class BscDesignerFullConfig(NodeConfig[BscDesignerConfig, BscDesignerAPITokenCredential]):
    pass


OPERATIONS = {
    'list_documents': ('GET', '/rest/api/documents/list', None, 'object', (200,)),
    'get_document': ('GET', '/rest/api/documents/list/{document_id}', None, 'object', (200,)),
    'create_document': ('POST', '/rest/api/documents', 'document', 'object', (200, 201)),
    'update_document': ('PUT', '/rest/api/documents/list/{document_id}', 'document', 'object', (200, 201)),
    'delete_document': ('DELETE', '/rest/api/documents/list/{document_id}', None, 'empty', (200, 204)),
    'get_document_tree': ('GET', '/rest/api/documents/tree', None, 'object', (200,)),
    'list_indicators': ('GET', '/rest/api/document/{document_id}/kpi/list', None, 'object', (200,)),
    'get_indicator_tree': ('GET', '/rest/api/document/{document_id}/kpi/tree', None, 'object', (200,)),
    'get_indicator': ('GET', '/rest/api/document/{document_id}/kpi/{indicator_guid}', None, 'object', (200,)),
    'update_indicator': ('PUT', '/rest/api/document/{document_id}/kpi/{indicator_guid}', 'indicator', 'object', (200, 201)),
    'get_indicator_value': ('GET', '/rest/api/document/{document_id}/kpi/indicator/{indicator_guid}/value/{date}', None, 'object', (200,)),
    'set_indicator_value': ('POST', '/rest/api/document/{document_id}/kpi/indicator/{indicator_guid}/value/{date}', 'data', 'object', (200, 201)),
    'get_all_values': ('GET', '/rest/api/document/{document_id}/kpi/batch/all/get-value/{date}', None, 'object', (200,)),
    'get_selected_values': ('POST', '/rest/api/document/{document_id}/kpi/batch/get-value/{date}', 'selection', 'object', (200, 201)),
    'set_selected_values': ('POST', '/rest/api/document/{document_id}/kpi/batch/set-value/{date}', 'data', 'object', (200, 201)),
    'list_maps': ('GET', '/rest/api/document/{document_id}/maps', None, 'object', (200,)),
    'refresh_map': ('PUT', '/rest/api/document/{document_id}/maps/{map_id}/wizzards', None, 'empty', (200, 201)),
    'refresh_all_maps': ('PUT', '/rest/api/document/{document_id}/maps/all/wizzards', None, 'empty', (200, 201)),
    'get_organization': ('GET', '/rest/api/organization-info', None, 'object', (200,)),
    'list_custom_fields': ('GET', '/rest/api/custom-fields', None, 'array', (200,)),
    'list_indicator_custom_values': ('GET', '/rest/api/document/{document_id}/kpi/indicator/{indicator_guid}/custom-fields', None, 'array', (200,)),
    'get_custom_value': ('GET', '/rest/api/document/{document_id}/kpi/indicator/{indicator_guid}/custom-fields/{custom_field_id}', None, 'object', (200,)),
    'set_custom_value': ('PUT', '/rest/api/document/{document_id}/kpi/indicator/{indicator_guid}/custom-fields/{custom_field_id}', 'data', 'object', (200, 201)),
}


class BscDesignerNode(WorkflowNode):
    integration_type = "automation-bsc-designer"
    connection_evidence = ConnectionEvidence(noun="scorecards", operation="list_documents")

    @classmethod
    def get_config_model(cls):
        return BscDesignerFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a BSC Designer API token")
        method, path, body_field, kind, statuses = OPERATIONS[config.operation]
        for key, value in config.model_dump(mode="json").items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        body = getattr(config, body_field).model_dump(
            mode="json", exclude_unset=True, exclude_none=config.operation != "set_custom_value",
        ) if body_field else None
        if body_field and not body and config.operation != "create_document":
            raise ValueError("Supply at least one field to write")
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path,
                headers={"token": credential.api_token, "Accept": "application/json"},
                **({"json": body} if body is not None else {}))
        if response.status_code not in statuses:
            message = response.text.replace(credential.api_token, "[redacted]")[:2000]
            raise ValueError(f"BSC Designer HTTP {response.status_code}: {message}")
        if kind == "empty" or (response.status_code == 201 and not response.content):
            return {"acknowledged": True, "http_status": response.status_code}
        data = response.json()
        if (kind == "array" and (not isinstance(data, list) or any(not isinstance(item, dict) for item in data))) or (kind == "object" and not isinstance(data, dict)):
            raise ValueError("BSC Designer returned an unexpected response shape")
        if isinstance(data, dict) and (data.get("error") or data.get("errors")):
            raise ValueError("BSC Designer returned an error envelope")
        return {"data": data}
