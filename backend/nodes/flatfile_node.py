"""Flatfile Data Exchange API v1. Each operation performs one published request.

The published API requires X-Disable-Hooks: true on every request, including
record writes. These operations therefore do not invoke Flatfile hooks.
Contract: https://reference.flatfile.com/openapi.json (1.0.0).
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.x.flatfile.com/v1"


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class FlatfileApiKeyCredential(_Input):
    model_config = ConfigDict(title="Flatfile API Key", extra="forbid", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://reference.flatfile.com/overview/auth",
            "x-credential-instructions": "In Flatfile, open Options > Developer, select the environment, and copy its secret key. Use the secret key, not the publishable key."})
    credential_type: Literal["flatfile_api_key"] = Field("flatfile_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Secret Key", min_length=1, max_length=4096, repr=False,
        description="Paste the environment secret key without the Bearer prefix.", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def clean_key(cls, value):
        value = value.strip()
        if not value or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value) or value.startswith(("pk_", "http:", "https:")):
            raise ValueError("Paste a Flatfile secret key without a prefix or URL")
        return value


Identifier = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_-]+$")]
Name = Annotated[str, Field(min_length=1, max_length=1000)]


class _Page(_Input):
    page_size: int = Field(20, ge=1, le=1000, title="Page Size")
    page_number: int = Field(1, ge=1, title="Page Number", description="Read one page; increment this number to retrieve the next page.")


class _Space(_Input):
    space_id: Identifier = Field(..., title="Space ID")


class _Workbook(_Input):
    workbook_id: Identifier = Field(..., title="Workbook ID")


class _Sheet(_Input):
    sheet_id: Identifier = Field(..., title="Sheet ID")


class FlatfileField(_Input):
    type: Literal["string", "number", "boolean", "date", "string-list"] = Field("string", title="Field Type")
    key: Name = Field(..., title="Field Key")
    label: str | None = Field(None, title="Field Label")


class FlatfileSheetDefinition(_Input):
    name: Name = Field(..., title="Sheet Name")
    slug: str | None = Field(None, title="Sheet Slug")
    fields: list[FlatfileField] = Field(..., min_length=1, title="Fields")


class FlatfileCell(_Input):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)
    value: str | int | float | bool | list[str] = Field(..., title="Cell Value")


class FlatfileRecordUpdate(_Input):
    id: Identifier = Field(..., title="Record ID")
    values: dict[str, FlatfileCell] = Field(..., min_length=1, title="Values")


class FlatfileGetCurrentAccountConfig(_Input):
    operation: Literal["get_current_account"] = Field("get_current_account", title="Get Current Account", json_schema_extra={"ui:hidden": True})


class FlatfileListEnvironmentsConfig(_Page):
    operation: Literal["list_environments"] = Field("list_environments", title="List Environments", json_schema_extra={"ui:hidden": True})


class FlatfileListSpacesConfig(_Page):
    operation: Literal["list_spaces"] = Field("list_spaces", title="List Spaces", json_schema_extra={"ui:hidden": True})
    environment_id: Identifier | None = Field(None, title="Environment ID")
    search: str | None = Field(None, title="Search")
    archived: bool | None = Field(None, title="Include Archived")


class FlatfileGetSpaceConfig(_Space):
    operation: Literal["get_space"] = Field("get_space", title="Get Space", json_schema_extra={"ui:hidden": True})


class FlatfileCreateSpaceConfig(_Input):
    operation: Literal["create_space"] = Field("create_space", title="Create Space", description='Flatfile hooks are disabled as required by the published API.', json_schema_extra={"ui:hidden": True})
    name: Name = Field(..., title="Space Name")
    environment_id: Identifier | None = Field(None, title="Environment ID")
    namespace: str | None = Field(None, title="Namespace")


class FlatfileUpdateSpaceConfig(_Space):
    operation: Literal["update_space"] = Field("update_space", title="Update Space", description='Flatfile hooks are disabled as required by the published API.', json_schema_extra={"ui:hidden": True})
    name: Name = Field(..., title="Space Name")
    namespace: str | None = Field(None, title="Namespace")


class FlatfileDeleteSpaceConfig(_Space):
    operation: Literal["delete_space"] = Field("delete_space", title="Delete Space", description='Permanently delete the selected space. Flatfile hooks are disabled as required by the published API.', json_schema_extra={"ui:hidden": True})


class FlatfileListWorkbooksConfig(_Input):
    operation: Literal["list_workbooks"] = Field("list_workbooks", title="List Workbooks", json_schema_extra={"ui:hidden": True})
    space_id: Identifier | None = Field(None, title="Space ID")
    name: str | None = Field(None, title="Name Filter")
    include_sheets: bool = Field(True, title="Include Sheets")


class FlatfileGetWorkbookConfig(_Workbook):
    operation: Literal["get_workbook"] = Field("get_workbook", title="Get Workbook", json_schema_extra={"ui:hidden": True})


class FlatfileCreateWorkbookConfig(_Input):
    operation: Literal["create_workbook"] = Field("create_workbook", title="Create Workbook", description='Flatfile hooks are disabled as required by the published API.', json_schema_extra={"ui:hidden": True})
    name: Name = Field(..., title="Workbook Name")
    space_id: Identifier | None = Field(None, title="Space ID")
    environment_id: Identifier | None = Field(None, title="Environment ID")
    sheets: list[FlatfileSheetDefinition] | None = Field(None, title="Sheets")


class FlatfileUpdateWorkbookConfig(_Workbook):
    operation: Literal["update_workbook"] = Field("update_workbook", title="Update Workbook", description='Flatfile hooks are disabled as required by the published API.', json_schema_extra={"ui:hidden": True})
    name: Name = Field(..., title="Workbook Name")
    labels: list[str] | None = Field(None, title="Labels")


class FlatfileDeleteWorkbookConfig(_Workbook):
    operation: Literal["delete_workbook"] = Field("delete_workbook", title="Delete Workbook", description='Permanently delete the selected workbook. Flatfile hooks are disabled as required by the published API.', json_schema_extra={"ui:hidden": True})


class FlatfileListSheetsConfig(_Workbook):
    operation: Literal["list_sheets"] = Field("list_sheets", title="List Sheets", json_schema_extra={"ui:hidden": True})


class FlatfileGetSheetConfig(_Sheet):
    operation: Literal["get_sheet"] = Field("get_sheet", title="Get Sheet", json_schema_extra={"ui:hidden": True})


class FlatfileUpdateSheetConfig(_Sheet):
    operation: Literal["update_sheet"] = Field("update_sheet", title="Update Sheet", description='Flatfile hooks are disabled as required by the published API.', json_schema_extra={"ui:hidden": True})
    name: Name = Field(..., title="Sheet Name")
    slug: str | None = Field(None, title="Sheet Slug")


class FlatfileGetRecordCountsConfig(_Sheet):
    operation: Literal["get_record_counts"] = Field("get_record_counts", title="Get Record Counts", json_schema_extra={"ui:hidden": True})
    by_field: bool = Field(False, title="Counts By Field")


class FlatfileListRecordsConfig(_Sheet, _Page):
    operation: Literal["list_records"] = Field("list_records", title="List Records", json_schema_extra={"ui:hidden": True})
    filter: Literal["valid", "error", "all", "none"] | None = Field(None, title="Record Filter")
    search_value: str | None = Field(None, title="Search Value")
    search_field: str | None = Field(None, title="Search Field")
    include_messages: bool = Field(False, title="Include Validation Messages")


class FlatfileInsertRecordsConfig(_Sheet):
    operation: Literal["insert_records"] = Field("insert_records", title="Insert Records", description='Flatfile hooks are disabled as required by the published API.', json_schema_extra={"ui:hidden": True})
    records: list[dict[str, FlatfileCell]] = Field(..., min_length=1, max_length=1000, title="Records", description='Rows keyed by field key; each cell is {"value": "..."}. Flatfile hooks will not run.')


class FlatfileUpdateRecordsConfig(_Sheet):
    operation: Literal["update_records"] = Field("update_records", title="Update Records", description='Flatfile hooks are disabled as required by the published API.', json_schema_extra={"ui:hidden": True})
    records: list[FlatfileRecordUpdate] = Field(..., min_length=1, max_length=1000, title="Record Updates")


class FlatfileDeleteRecordsConfig(_Sheet):
    operation: Literal["delete_records"] = Field("delete_records", title="Delete Records", description='Flatfile hooks are disabled as required by the published API.', json_schema_extra={"ui:hidden": True})
    record_ids: list[Identifier] = Field(..., min_length=1, max_length=100, title="Record IDs", description="Only these explicit record IDs will be deleted.")


class FlatfileListFilesConfig(_Page):
    operation: Literal["list_files"] = Field("list_files", title="List Files", json_schema_extra={"ui:hidden": True})
    space_id: Identifier | None = Field(None, title="Space ID")


class FlatfileGetFileConfig(_Input):
    operation: Literal["get_file"] = Field("get_file", title="Get File", json_schema_extra={"ui:hidden": True})
    file_id: Identifier = Field(..., title="File ID")


class FlatfileListJobsConfig(_Page):
    operation: Literal["list_jobs"] = Field("list_jobs", title="List Jobs", json_schema_extra={"ui:hidden": True})
    space_id: Identifier | None = Field(None, title="Space ID")
    workbook_id: Identifier | None = Field(None, title="Workbook ID")
    file_id: Identifier | None = Field(None, title="File ID")


class FlatfileGetJobConfig(_Input):
    operation: Literal["get_job"] = Field("get_job", title="Get Job", json_schema_extra={"ui:hidden": True})
    job_id: Identifier = Field(..., title="Job ID")


FlatfileOperation = Annotated[Union[
    FlatfileGetCurrentAccountConfig,
    FlatfileListEnvironmentsConfig,
    FlatfileListSpacesConfig,
    FlatfileGetSpaceConfig,
    FlatfileCreateSpaceConfig,
    FlatfileUpdateSpaceConfig,
    FlatfileDeleteSpaceConfig,
    FlatfileListWorkbooksConfig,
    FlatfileGetWorkbookConfig,
    FlatfileCreateWorkbookConfig,
    FlatfileUpdateWorkbookConfig,
    FlatfileDeleteWorkbookConfig,
    FlatfileListSheetsConfig,
    FlatfileGetSheetConfig,
    FlatfileUpdateSheetConfig,
    FlatfileGetRecordCountsConfig,
    FlatfileListRecordsConfig,
    FlatfileInsertRecordsConfig,
    FlatfileUpdateRecordsConfig,
    FlatfileDeleteRecordsConfig,
    FlatfileListFilesConfig,
    FlatfileGetFileConfig,
    FlatfileListJobsConfig,
    FlatfileGetJobConfig
], Field(discriminator="operation")]


class FlatfileFullConfig(NodeConfig[FlatfileOperation, FlatfileApiKeyCredential]):
    pass


OPERATIONS = {'get_current_account': ('GET', '/accounts/current', [], [], False),
 'list_environments': ('GET', '/environments', [], ['page_size', 'page_number'], True),
 'list_spaces': ('GET',
                 '/spaces',
                 [],
                 ['page_size', 'page_number', 'environment_id', 'search', 'archived'],
                 True),
 'get_space': ('GET', '/spaces/{space_id}', [], [], False),
 'create_space': ('POST', '/spaces', ['name', 'environment_id', 'namespace'], [], False),
 'update_space': ('PATCH', '/spaces/{space_id}', ['name', 'namespace'], [], False),
 'delete_space': ('DELETE', '/spaces/{space_id}', [], [], False),
 'list_workbooks': ('GET', '/workbooks', [], ['space_id', 'name', 'include_sheets'], True),
 'get_workbook': ('GET', '/workbooks/{workbook_id}', [], [], False),
 'create_workbook': ('POST',
                     '/workbooks',
                     ['name', 'space_id', 'environment_id', 'sheets'],
                     [],
                     False),
 'update_workbook': ('PATCH', '/workbooks/{workbook_id}', ['name', 'labels'], [], False),
 'delete_workbook': ('DELETE', '/workbooks/{workbook_id}', [], [], False),
 'list_sheets': ('GET', '/sheets', [], ['workbook_id'], True),
 'get_sheet': ('GET', '/sheets/{sheet_id}', [], [], False),
 'update_sheet': ('PATCH', '/sheets/{sheet_id}', ['name', 'slug'], [], False),
 'get_record_counts': ('GET', '/sheets/{sheet_id}/counts', [], ['by_field'], False),
 'list_records': ('GET',
                  '/sheets/{sheet_id}/records',
                  [],
                  ['page_size',
                   'page_number',
                   'filter',
                   'search_value',
                   'search_field',
                   'include_messages'],
                  False),
 'insert_records': ('POST', '/sheets/{sheet_id}/records', ['records'], [], False),
 'update_records': ('PUT', '/sheets/{sheet_id}/records', ['records'], [], False),
 'delete_records': ('DELETE', '/sheets/{sheet_id}/records', [], ['record_ids'], False),
 'list_files': ('GET', '/files', [], ['page_size', 'page_number', 'space_id'], True),
 'get_file': ('GET', '/files/{file_id}', [], [], False),
 'list_jobs': ('GET',
               '/jobs',
               [],
               ['page_size', 'page_number', 'space_id', 'workbook_id', 'file_id'],
               True),
 'get_job': ('GET', '/jobs/{job_id}', [], [], False)}

WIRE_NAMES = {"space_id": "spaceId", "workbook_id": "workbookId", "environment_id": "environmentId",
    "file_id": "fileId", "page_size": "pageSize", "page_number": "pageNumber", "include_sheets": "includeSheets",
    "by_field": "byField", "search_value": "searchValue", "search_field": "searchField", "include_messages": "includeMessages", "record_ids": "ids"}


class FlatfileNode(WorkflowNode):
    integration_type = "automation-flatfile"
    connection_evidence = ConnectionEvidence(noun="spaces", operation="list_spaces", identity_operation="get_current_account")

    @classmethod
    def get_config_model(cls):
        return FlatfileFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Flatfile API key")
        config = self.config.config
        method, template, body_fields, query_fields, list_response = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True)
        path = template.format(**{key: quote(str(value), safe="") for key, value in values.items()})
        params = {}
        for key in query_fields:
            if key in values:
                value = values[key]
                params[WIRE_NAMES.get(key, key)] = ",".join(value) if key == "record_ids" else str(value).lower() if isinstance(value, bool) else value
        body = {WIRE_NAMES.get(key, key): values[key] for key in body_fields if key in values}
        if config.operation in {"insert_records", "update_records"}:
            body = values["records"]
        headers = {"Authorization": "Bearer " + self.config.credentials.api_key,
            "Accept": "application/json", "X-Disable-Hooks": "true"}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers, params=params,
                **({"json": body} if body_fields else {}))
        if response.status_code != 200:
            # Do not echo provider bodies, which may contain request secrets or data.
            raise ValueError(f"Flatfile request failed (HTTP {response.status_code})")
        if len(response.content) > 20_000_000:
            raise ValueError("Flatfile response exceeds 20 MB; request a smaller page")
        result = response.json()
        if not isinstance(result, dict) or "data" not in result or result.get("errors"):
            raise ValueError("Flatfile returned an incomplete response")
        data = result["data"]
        if not isinstance(data, list if list_response else dict):
            raise ValueError("Flatfile returned an unexpected data shape")
        if isinstance(data, dict) and data.get("success") is False:
            raise ValueError("Flatfile did not confirm the operation")
        if config.operation == "list_records" and not isinstance(data.get("records"), list):
            raise ValueError("Flatfile record response is missing records")
        output = {"status": "success", "operation": config.operation, "data": data}
        # Preserve provider pagination; a single page never claims a complete crawl.
        if "pagination" in result:
            output["pagination"] = result["pagination"]
        if "page_number" in values:
            output["page_number"] = values["page_number"]
            output["page_size"] = values["page_size"]
        return output
