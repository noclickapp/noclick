"""Csvbox Sheets API 1.2.0 automation using a manually supplied API key pair.

Each action makes one documented request; PATCH preserves omitted fields and
uses the provider's named-item merge rules for JavaScript collections.
Contract: https://app.csvbox.io/docs?api-docs.json
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

NODE_TYPE = "automation-csvbox"
BASE = "https://api.csvbox.io/1.1/sheet"
METHODS = {
    "list_sheets": "GET", "get_sheet": "GET", "create_sheet": "POST",
    "update_sheet": "PUT", "patch_sheet": "PATCH", "rename_sheet": "PATCH",
    "set_sheet_columns": "PATCH", "set_destinations": "PATCH",
    "set_webhooks": "PATCH", "set_import_steps": "PATCH",
    "set_security_settings": "PATCH", "merge_virtual_columns": "PATCH",
    "merge_validation_functions": "PATCH", "merge_data_transforms": "PATCH",
    "set_pdf_metadata": "PATCH",
}


class CsvboxAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Csvbox API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.csvbox.io",
            "x-credential-instructions": "Paste your Csvbox API key and secret API key from your dashboard's API Credentials page. Both keys are required. NoClick verifies the pair by reading your sheets.",
        },
    )
    credential_type: Literal["csvbox_api_key"] = Field("csvbox_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})
    secret_api_key: str = Field(..., title="Secret API key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "secret_api_key", mode="before")
    @classmethod
    def key(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the API key as text")
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the key without a header or whitespace")
        return value


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, strict=True)

    @model_validator(mode="before")
    @classmethod
    def unset_optional_fields(cls, data):
        if not isinstance(data, dict):
            return data
        # Blank optional form fields mean omission; explicitly nullable API
        # settings such as page_limit still need to reach the provider as null.
        fields = {field.alias or name: field for name, field in cls.model_fields.items()}
        return {key: value for key, value in data.items()
                if value is not None or key not in fields or fields[key].is_required()
                or (fields[key].json_schema_extra or {}).get("x-csvbox-nullable")}


class CsvboxHeader(_Request):
    key: str = Field(..., description='---------------------------------------------------------\nHEADER OBJECT\n---------------------------------------------------------', examples=['Content-Type'])
    value: str = Field(..., examples=['application/json'])


class CsvboxWebhookImportComplete(_Request):
    url: str | None = Field(None, examples=['https://example.com/webhook'])
    send_copy: bool | None = Field(None, description='Send a copy of imported data to client', examples=[False])
    custom_headers: list[CsvboxHeader] | None = Field(None)


class CsvboxWebhook(_Request):
    import_complete: CsvboxWebhookImportComplete | None = Field(None)


class CsvboxDestinationsSettings(_Request):
    method: Literal['POST', 'PATCH'] | None = Field(None, examples=['POST'])
    url: str | None = Field(None, examples=['https://example.com/api/import'])
    post_data_format: Literal['JSON', 'FORM_DATA', 'XML'] | None = Field(None, examples=['JSON'])
    rows_per_chunk: int | None = Field(None, examples=[100])
    request_type: Literal['parallel', 'sequential'] | None = Field(None, examples=['parallel'])
    server_side_validation: bool | None = Field(None, examples=[True])
    allow_resubmit: Literal['all_rows', 'error_rows_only'] | None = Field(None, examples=['all_rows'])
    custom_headers: list[CsvboxHeader] | None = Field(None)


class CsvboxDestinations(_Request):
    type: Literal['webhook', 'testapi', 'none', 'xano'] | None = Field(None, examples=['webhook'])
    isActive: bool | None = Field(None, examples=[True])
    settings: CsvboxDestinationsSettings | None = Field(None)


class CsvboxListItemDependent(_Request):
    value: str | None = Field(None, examples=['mum'])
    display_label: str | None = Field(None, examples=['Mumbai'])


class CsvboxListItemChild(_Request):
    value: str | None = Field(None, examples=['mh'])
    display_label: str | None = Field(None, examples=['Maharashtra'])
    dependents: list[CsvboxListItemDependent] | None = Field(None)


class CsvboxListItem(_Request):
    value: str | None = Field(None, examples=['ind'])
    display_label: str | None = Field(None, examples=['India'])
    dependents: list[CsvboxListItemChild] | None = Field(None)


class CsvboxSheetColumnValidators(_Request):
    'Validators depend on the column type. See examples below for each type.'
    min_length: int | None = Field(None, description='[text] Minimum character length', examples=[2])
    max_length: int | None = Field(None, description='[text] Maximum character length', examples=[50])
    min_value: float | None = Field(None, description='[number, percentage] Minimum numeric value', examples=[1])
    max_value: float | None = Field(None, description='[number, percentage] Maximum numeric value', examples=[100])
    output: Literal['number', 'percent'] | None = Field(None, description='[percentage] Output format', examples=['number'])
    format: str | None = Field(None, description='[date] Date format e.g. YYYY-MM-DD | [time] Time format e.g. HH:mm:ss', examples=['YYYY-MM-DD'])
    custom: str | None = Field(None, description='[date, time] Custom format string, used when format is "custom"', examples=['DD/MM/YYYY'])
    multiple: list[str] | None = Field(None, description='[date, time] Accepted formats, used when format is "multiple"')
    expression: str | None = Field(None, description='[regex] Regular expression pattern', examples=['^\\d{10}$'])
    error_message: str | None = Field(None, description='[regex] Custom error message', examples=['Please enter a valid 10 digit phone number'])
    version: Literal['ipv4', 'ipv6'] | None = Field(None, description='[ip] IP version', examples=['ipv4'])
    country_code: str | None = Field(None, description='[phone_number] Country code e.g. IN, US', examples=['IN'])
    symbol: str | None = Field(None, description='[currency] Currency symbol', examples=['$'])
    require_symbol: bool | None = Field(None, description='[currency] Whether symbol is required', examples=[False])
    allow_space_after_symbol: bool | None = Field(None, description='[currency] Allow a space between the symbol and digits', examples=[False])
    symbol_after_digits: bool | None = Field(None, description='[currency] Place the symbol after the digits instead of before', examples=[False])
    allow_negatives: bool | None = Field(None, description='[currency] Allow negative values', examples=[True])
    parens_for_negatives: bool | None = Field(None, description='[currency] Show negative values in parentheses instead of a minus sign', examples=[False])
    negative_sign_before_digits: bool | None = Field(None, description='[currency] Place the negative sign before the digits', examples=[True])
    negative_sign_after_digits: bool | None = Field(None, description='[currency] Place the negative sign after the digits', examples=[False])
    thousands_separator: str | None = Field(None, description='[currency] Thousands separator character', examples=[','])
    decimal_separator: str | None = Field(None, description='[currency] Decimal separator character', examples=['.'])
    allow_decimal: bool | None = Field(None, description='[currency] Allow decimal values', examples=[True])
    require_decimal: bool | None = Field(None, description='[currency] Require a decimal portion', examples=[False])
    digits_after_decimal: int | None = Field(None, description='[currency] Number of digits allowed after the decimal separator', examples=[2])
    allow_space_after_digits: bool | None = Field(None, description='[currency] Allow a trailing space after the digits', examples=[False])
    values: Union[list[CsvboxListItem], list[str]] | None = Field(None, description='[list] Array of ListItem objects (with dependents) | [multiselect_list] Array of strings')
    case_sensitive: bool | None = Field(None, description='[list, multiselect_list] Case-sensitive matching', examples=[False])
    trim_whitespace: bool | None = Field(None, description='[list, dynamic_list, multiselect_list, multiselect_dynamic_list] Trim whitespace before matching', examples=[False])
    accept_list_values: bool | None = Field(None, description='[list] Accept values already present in the configured list without further validation', examples=[False])
    primary_column: str | None = Field(None, description='[dependent_list, dependent_dynamic_list] The column_name of the parent list column', examples=['col14'])
    source_url: str | None = Field(None, description='[dynamic_list] URL to fetch list options from', examples=['https://example.com/api/list-options'])
    request_method: Literal['GET', 'POST'] | None = Field(None, description='[dynamic_list] HTTP method', examples=['GET'])
    request_headers: list[CsvboxHeader] | None = Field(None, description='[dynamic_list] Custom request headers')
    custom_user_attributes: bool | None = Field(None, description='[dynamic_list] Include custom user attributes in request', examples=[True])
    other_values: bool | None = Field(None, description='[dynamic_list, multiselect_list] Allow values outside predefined list', examples=[False])
    delimiter: str | None = Field(None, description='[multiselect_list, multiselect_dynamic_list] Delimiter for multiple values', examples=[','])
    dml_source_url: str | None = Field(None, description='[multiselect_dynamic_list] URL to fetch list options from', examples=['https://example.com/api/multiselect-dynamic-options'])
    dml_request_method: Literal['GET', 'POST', 'PATCH'] | None = Field(None, description='[multiselect_dynamic_list] HTTP method', examples=['GET'])
    dml_request_headers: list[CsvboxHeader] | None = Field(None, description='[multiselect_dynamic_list] Custom request headers')
    dml_other_values: bool | None = Field(None, description='[multiselect_dynamic_list] Allow values outside predefined list', examples=[False])


class CsvboxSheetColumnMetadata(_Request):
    'Data transforms configured for this column, under the same metadata.transforms key POST/PUT/PATCH accept. An empty object when no transforms are configured.'
    transforms: dict[str, JsonValue] | None = Field(None)


class CsvboxSheetColumn(_Request):
    column_name: str = Field(..., examples=['email'])
    display_label: str | None = Field(None, examples=['Email'])
    info_hint: str | None = Field(None, examples=['Enter user email'])
    matching_keywords: str | None = Field(None, examples=['email,user_email'])
    type: Literal['text', 'number', 'email', 'date', 'time', 'boolean', 'regex', 'ip', 'url', 'credit_card', 'phone_number', 'currency', 'list', 'dependent_list', 'dynamic_list', 'dependent_dynamic_list', 'multiselect_list', 'multiselect_dynamic_list', 'percentage', 'iana_timezone', 'upc', 'uuid', 'domain', 'currency_code', 'country_code_a2', 'country_code_a3', 'imei', 'ean', 'json'] | None = Field(None, examples=['text'])
    default_value: str | None = Field(None, examples=[''])
    required: bool | None = Field(None, examples=[False])
    read_only: bool | None = Field(None, examples=[False])
    position: int | None = Field(None, ge=1, examples=[1])
    validators: CsvboxSheetColumnValidators | None = Field(None, description='Validators depend on the column type. See examples below for each type.')
    metadata: CsvboxSheetColumnMetadata | None = Field(None, description='Data transforms configured for this column, under the same metadata.transforms key POST/PUT/PATCH accept. An empty object when no transforms are configured.')


class CsvboxStepsFileUpload(_Request):
    types: list[str] | None = Field(None)
    title: str | None = Field(None, examples=['File Upload'])
    help: str | None = Field(None, examples=['Upload your CSV file'])
    sample_file_url: str | None = Field(None, examples=[''])
    size_mb: int | None = Field(None, examples=[200])
    validation_msg: str | None = Field(None, examples=['upto 200mb allowed'])
    copy_paste: bool | None = Field(None, examples=[True])
    copy_delimiter: str | None = Field(None, examples=['comma'])
    show_upload: bool | None = Field(None, examples=[True])
    worksheet_select: bool | None = Field(None, examples=[True])
    description_option: bool | None = Field(None, examples=[True])
    lang: str | None = Field(None, examples=['en'])
    excel_date_format: str | None = Field(None, examples=['custom'])
    excel_date_custom: str | None = Field(None, examples=['DD-MM-YYYY'])
    hide_cancel: bool | None = Field(None, examples=[False])
    split: bool | None = Field(None, description='Split large files into multiple imports', examples=[True])
    split_rows: int | None = Field(None, description='Rows per import when splitting (min 1)', examples=[1000])
    split_confirm: Literal['no', 'yes', 'no_if_no_errors'] | None = Field(None, description='User confirmation required after each import: no=0, yes=1, no_if_no_errors=2', examples=['no'])
    extract_types: list[Literal['pdf', 'docs', 'images']] | None = Field(None, description='Allowed document extraction types (mapped to .pdf/.doc/images)', examples=[['pdf', 'images']])
    page_limit: int | None = Field(None, description='Max pages allowed for extraction (null = no limit)', examples=[10], json_schema_extra={"x-csvbox-nullable": True})
    accept_raw_value: bool | None = Field(None, description='Skip data-type coercion and pass raw cell values through. Defaults to false, deliberately — see the repo\'s revert-accept-raw-values-default change; this is not a stale default to "fix".', examples=[False])
    skip_min_rows: int | None = Field(None, description='Skip extracted tables with fewer than this many rows (table extraction only)', examples=[2], json_schema_extra={"x-csvbox-nullable": True})
    skip_max_rows: int | None = Field(None, description='Skip extracted tables with more than this many rows (table extraction only)', examples=[1000], json_schema_extra={"x-csvbox-nullable": True})
    skip_min_cols: int | None = Field(None, description='Skip extracted tables with fewer than this many columns (table extraction only)', examples=[2], json_schema_extra={"x-csvbox-nullable": True})
    skip_max_cols: int | None = Field(None, description='Skip extracted tables with more than this many columns (table extraction only)', examples=[20], json_schema_extra={"x-csvbox-nullable": True})


class CsvboxStepsSelectHeader(_Request):
    skip: bool | None = Field(None, examples=[True])
    help: str | None = Field(None, examples=['Select header row'])
    default_row: str | None = Field(None, examples=['2'])
    encoding_option: bool | None = Field(None, examples=[True])
    encoding: Literal['utf-8', 'windows-1251', 'windows-1252', 'ibm866', 'iso-8859-2', 'iso-8859-3', 'iso-8859-4', 'iso-8859-5', 'iso-8859-6', 'iso-8859-7', 'iso-8859-8', 'iso-8859-8-i', 'iso-8859-10', 'iso-8859-13', 'iso-8859-14', 'iso-8859-15', 'iso-8859-16', 'koi8-r', 'koi8-u', 'macintosh', 'windows-874', 'windows-1250', 'windows-1253', 'windows-1254', 'windows-1255', 'windows-1256', 'windows-1257', 'windows-1258', 'gbk', 'gb18030', 'big5', 'euc-jp', 'shift-jis', 'euc-kr', 'utf-16be', 'utf-16le'] | None = Field(None, description='Accepted values: utf-8, windows-1251, windows-1252, ibm866, iso-8859-2, iso-8859-3, iso-8859-4, iso-8859-5, iso-8859-6, iso-8859-7, iso-8859-8, iso-8859-8-i, iso-8859-10, iso-8859-13, iso-8859-14, iso-8859-15, iso-8859-16, koi8-r, koi8-u, macintosh, windows-874, windows-1250, windows-1253, windows-1254, windows-1255, windows-1256, windows-1257, windows-1258, gbk, gb18030, big5, euc-jp, shift-jis, euc-kr, utf-16be, utf-16le. Values are case-insensitive and lowercased before storage.', examples=['windows-1252'])
    row_column_switch: bool | None = Field(None, examples=[False])


class CsvboxStepsMapColumns(_Request):
    skip: bool | None = Field(None, examples=[True])
    help: str | None = Field(None, examples=['Map columns'])
    mapping_mode: str | None = Field(None, examples=['template_fields'])
    bulk_cols_dd: bool | None = Field(None, examples=[False])
    accept_unmapped: bool | None = Field(None, examples=[True])
    accept_unmapped_select: bool | None = Field(None, examples=[True])
    allow_zero_template: bool | None = Field(None, examples=[True])
    ignore_cols: bool | None = Field(None, examples=[True])
    ignore_cols_default: bool | None = Field(None, examples=[True])
    user_keywords: bool | None = Field(None, examples=[False])


class CsvboxStepsVerifyData(_Request):
    skip: bool | None = Field(None, examples=[True])
    help: str | None = Field(None, examples=['Verify data'])
    row_display_mode: str | None = Field(None, examples=['invalid'])
    export_option: bool | None = Field(None, examples=[True])
    search_option: bool | None = Field(None, examples=[False])
    ai_transform: bool | None = Field(None, examples=[True])
    allow_new_rows: bool | None = Field(None, examples=[False])
    rows_display: int | None = Field(None, examples=[25])
    allow_invalid: bool | None = Field(None, examples=[True])
    invalid_confirmation: bool | None = Field(None, examples=[False])
    max_rows: int | None = Field(None, examples=[600])
    allow_upload_if_max: bool | None = Field(None, examples=[False])
    max_rows_msg: str | None = Field(None, examples=['maaaaaax'])
    min_rows: int | None = Field(None, examples=[2])
    min_rows_msg: str | None = Field(None, examples=['miiiiin'])


class CsvboxStepsResults(_Request):
    close_mode: str | None = Field(None, examples=['close_on_success'])
    redirect_url: str | None = Field(None, examples=[''])
    success_type: str | None = Field(None, examples=['static'])
    success_text: str | None = Field(None, examples=['Import successful'])
    success_method: str | None = Field(None, examples=['get'])
    success_url: str | None = Field(None, examples=[''])
    success_headers: list[CsvboxHeader] | None = Field(None, description='Custom headers sent with the success dynamic callback')
    failed_type: str | None = Field(None, examples=['static'])
    failed_text: str | None = Field(None, examples=['Failure'])
    failed_method: str | None = Field(None, examples=['get'])
    failed_url: str | None = Field(None, examples=[''])
    failed_headers: list[CsvboxHeader] | None = Field(None, description='Custom headers sent with the failure dynamic callback')
    show_resubmit: bool | None = Field(None, examples=[False])
    show_error_text: bool | None = Field(None, examples=[False])


class CsvboxSteps(_Request):
    file_upload: CsvboxStepsFileUpload | None = Field(None)
    select_header: CsvboxStepsSelectHeader | None = Field(None)
    map_columns: CsvboxStepsMapColumns | None = Field(None)
    verify_data: CsvboxStepsVerifyData | None = Field(None)
    results: CsvboxStepsResults | None = Field(None)


class CsvboxSecuritySettings(_Request):
    region: Literal['us', 'eu'] | None = Field(None, examples=['us'])
    domains: list[str] | None = Field(None)
    import_url_upload: bool | None = Field(None, examples=[True])
    s3_upload: bool | None = Field(None, examples=[True])


class CsvboxJsDependency(_Request):
    'A third-party script an item\'s `js_code` may use. The API never accepts raw HTML — send the URL and the server renders the <script src> tag. Migrating from the web UI: `js_dependency` markup is not a writable field. Full shape, all three fields, on any of the three collections: `"dependencies": [{"url": "https://cdn.jsdelivr.net/npm/dayjs@1.11.10/dayjs.min.js", "globals": ["dayjs"], "integrity": "sha384-…"}]`. Only `url` is required; `globals` is what makes the library\'s name callable from `js_code`, and `integrity` is optional. Up to 5 dependencies per item — send them as separate objects in the array, comma-separated, one per script. The server renders each as `<script src="…" integrity="…" crossorigin="anonymous"></script>`, in the order sent, so a library that must load before another goes first.'
    url: str = Field(..., max_length=512, description='HTTPS only. Host must be exactly cdn.jsdelivr.net, unpkg.com or cdnjs.cloudflare.com (no subdomains). Path must end in .js or .mjs. No query string, fragment, userinfo or port.', examples=['https://cdn.jsdelivr.net/npm/dayjs@1.11.10/dayjs.min.js'])
    globals: list[str] | None = Field(None, max_length=5, description='Names this script defines. Each is added to the allowed-identifier list for this item only — code referencing an undeclared global is rejected with js_disallowed_global. May not shadow a built-in or `csvbox`. Loading the script is not enough on its own: the code gate checks this list, so a name absent from it is refused whether or not the CDN would have defined it at runtime. Up to 5 names, each matching /^[A-Za-z_$][A-Za-z0-9_$]{0,63}$/.')
    integrity: str | None = Field(None, description="Optional Subresource Integrity digest: sha256-, sha384- or sha512- followed by base64. When sent it is rendered as the tag's integrity attribute, so the browser refuses the script if the file does not hash to it. Take the digest from the CDN's own copy button (jsDelivr and cdnjs both publish one) — a digest that does not match the exact file at that URL stops the library loading, and the failure shows up in the importer at runtime, not as a 422 here. Pin an exact version in the URL when you use it: a floating version resolves to a different file later and invalidates the digest.", examples=['sha384-abc123+/def456=='])


class CsvboxVirtualColumn(_Request):
    'A computed column. Max 20 per sheet. `column_name` must not collide with a real sheet column.'
    column_name: str = Field(..., max_length=190, examples=['full_name'])
    js_code: str | None = Field(None, max_length=32768, description='Function body receiving a single `csvbox` argument and returning the computed value. Required unless `_delete` is true, or a PATCH is updating an item that already exists — an omitted `js_code` then keeps the stored snippet. Sending an empty string, null or whitespace is refused with js_syntax_error: preservation is triggered by absence, not emptiness.', examples=["const a = csvbox.row['col1'] || ''; const b = csvbox.row['col2'] || ''; return (a + ' ' + b).trim();"])
    active: bool | None = Field(None, description='Defaults to true on API create — unlike the web UI, whose post-save toggle starts off.', examples=[True])
    dependencies: list[CsvboxJsDependency] | None = Field(None, max_length=5, description='Supported here as on every collection. Empty in this example because the snippet above needs only `csvbox` and built-ins — see the `check_date` validation function for a worked dependency. To use one here, send `[{"url": "https://cdn.jsdelivr.net/npm/dayjs@1.11.10/dayjs.min.js", "globals": ["dayjs"], "integrity": "sha384-…"}]`; `globals` and `integrity` are optional, and further scripts are further objects in the same array. See the JsDependency schema for the host allowlist and per-field rules.', examples=[[]])
    delete: bool | None = Field(None, alias='_delete', description='PATCH only. When true the item is deleted and every other field on it is ignored, including `js_code`.', examples=[False])


class CsvboxValidationFunction(_Request):
    'A custom validation rule. Max 10 per sheet.'
    function_name: str = Field(..., max_length=190, examples=['check_email'])
    scope: Literal['column', 'row'] | None = Field(None, description='`column` runs over whole columns via csvbox.column[...]; `row` runs per row via csvbox.row[...]. A column-scoped item must name at least one entry across `columns` and `dynamic_columns`. On a PATCH updating an existing item, `scope`, `columns` and `dynamic_columns` preserve as a GROUP: send none of the three and the stored scoping is kept; send any one and all three are taken from the request, so `columns` alone also clears `dynamic_columns`.', examples=['column'])
    columns: list[str] | None = Field(None, description='Sheet columns this function reads. Validated against the sheet as it stands AFTER this request, so one call may add a column and a function that uses it. A scope preserved by a PATCH that sent none of the three scope fields is written back as stored and is not re-checked.')
    dynamic_columns: list[str] | None = Field(None, description='Columns that only exist at import time and so cannot be checked against the sheet definition.')
    js_code: str | None = Field(None, max_length=32768, description='Function body receiving `csvbox` and returning an array of errors — empty means valid. Required unless `_delete` is true, or a PATCH is updating an item that already exists — an omitted `js_code` then keeps the stored snippet. Sending an empty string, null or whitespace is refused with js_syntax_error: preservation is triggered by absence, not emptiness.', examples=["const rows = csvbox.column['col4'] || []; const errs = []; for (let i = 0; i < rows.length; i++) { if (String(rows[i]).indexOf('@') === -1) { errs.push({ row_id: i + 1, column: 'col4', message: 'Not a valid email' }); } } return errs;"])
    active: bool | None = Field(None, examples=[True])
    dependencies: list[CsvboxJsDependency] | None = Field(None, max_length=5, description='Scripts this item\'s `js_code` may use. The `check_date` example below is the worked case: `[{"url": "https://cdn.jsdelivr.net/npm/dayjs@1.11.10/dayjs.min.js", "globals": ["dayjs"]}]`, plus an optional `integrity` digest per entry. Remove it and the same code is rejected with js_disallowed_global, which is the whole purpose of `globals`. Up to 5 entries, comma-separated in the array, loaded in the order sent.')
    delete: bool | None = Field(None, alias='_delete', description='PATCH only. See VirtualColumn._delete.', examples=[False])


class CsvboxDataTransform(_Request):
    'A transform that rewrites values in place. Max 10 per sheet.'
    transform_name: str = Field(..., max_length=190, examples=['uppercase_country'])
    scope: Literal['column', 'row'] | None = Field(None, examples=['column'])
    run_at: Literal['before_validation', 'after_validation'] | None = Field(None, description='When the transform runs relative to validation.', examples=['before_validation'])
    columns: list[str] | None = Field(None)
    dynamic_columns: list[str] | None = Field(None)
    js_code: str | None = Field(None, max_length=32768, description='Function body receiving `csvbox`, mutating it and returning it. Required unless `_delete` is true, or a PATCH is updating an item that already exists — an omitted `js_code` then keeps the stored snippet. Sending an empty string, null or whitespace is refused with js_syntax_error: preservation is triggered by absence, not emptiness.', examples=["for (let i = 0; i < csvbox.column['col1'].length; i++) { csvbox.column['col1'][i] = String(csvbox.column['col1'][i]).toUpperCase(); } return csvbox;"])
    active: bool | None = Field(None, examples=[True])
    dependencies: list[CsvboxJsDependency] | None = Field(None, max_length=5, description='Supported here as on every collection. Empty in this example because the snippet above needs only `csvbox` and built-ins — see the `check_date` validation function for a worked dependency. To use one here, send `[{"url": "https://cdn.jsdelivr.net/npm/dayjs@1.11.10/dayjs.min.js", "globals": ["dayjs"], "integrity": "sha384-…"}]`; `globals` and `integrity` are optional, and further scripts are further objects in the same array. See the JsDependency schema for the host allowlist and per-field rules.', examples=[[]])
    delete: bool | None = Field(None, alias='_delete', description='PATCH only. See VirtualColumn._delete.', examples=[False])


class CsvboxPdfMetadataField(_Request):
    'One metadata field to extract from an uploaded PDF/DOCX. Max 20 per sheet.'
    name: str = Field(..., max_length=100, description='Output key. For `source=native`/`document-kv` this also drives matching (see `source`); for `static`/`line-match` it is only the output key.', examples=['Invoice Number'])
    source: Literal['native', 'document-kv', 'static', 'line-match'] = Field(..., description="Where the value comes from. `native`: `name` is matched case-insensitively against the uploaded PDF/DOCX's own document properties (e.g. Author, Title, Subject, Keywords, CreationDate) — `value` is ignored. `document-kv`: `name` must match, after whitespace/trailing-punctuation normalization, the exact (case-sensitive) label text of a key-value pair detected on the document (e.g. a form field literally labeled `Invoice Number`) — `value` is ignored. `static`: `value` is returned verbatim. `line-match`: `value` is a search term — the document's extracted text is scanned line by line and whatever follows that term is returned (falling back to the next line if nothing follows it on the same line).", examples=['document-kv'])
    value: str | None = Field(None, description='Required when `source` is `static` (the literal to return) or `line-match` (the search term). Ignored for `native` and `document-kv`.', json_schema_extra={"x-csvbox-nullable": True})


class CsvboxSheetFields(_Request):
    title: str | None = Field(None, examples=['Updated Sheet'])
    webhooks: list[CsvboxWebhook] | None = Field(None, json_schema_extra={"ui:widget": "state_editor", "placeholder": '[]'})
    destinations: list[CsvboxDestinations] | None = Field(None, json_schema_extra={"ui:widget": "state_editor", "placeholder": '[]'})
    sheet_columns: list[CsvboxSheetColumn] | None = Field(None, json_schema_extra={"ui:widget": "state_editor", "placeholder": '[]'})
    steps: CsvboxSteps | None = Field(None, json_schema_extra={"ui:widget": "state_editor", "placeholder": '{}'})
    security_settings: CsvboxSecuritySettings | None = Field(None, json_schema_extra={"ui:widget": "state_editor", "placeholder": '{}'})
    virtual_columns: list[CsvboxVirtualColumn] | None = Field(None, max_length=20, description='PATCH MERGES: only the items you list are touched. Existing items you do not name are left alone — nothing is deleted implicitly. Sending [] is a no-op, not a clear. To remove one item send {"column_name": "old_one", "_delete": true}; every other field on a _delete item is ignored, so js_code is not required. It merges at FIELD level too: on an item that already exists every field you omit keeps its stored value, so {"function_name": "check_email", "active": false} disables that function without re-sending its code, columns or dependencies.', json_schema_extra={"ui:widget": "state_editor", "placeholder": '[]'})
    validation_functions: list[CsvboxValidationFunction] | None = Field(None, max_length=10, description='PATCH MERGES: unlisted items are untouched, [] is a no-op. Delete one with {"function_name": "old_one", "_delete": true}. Two functions are shown: `check_email` needs nothing beyond the built-ins, while `check_date` declares `dayjs` — remove that dependency and its code is rejected with js_disallowed_global. That entry omits the optional `integrity` field so this body can be sent unmodified; in your own sheet add `"integrity": "sha384-<digest published by the CDN>"` beside the `url`, and add further scripts as further comma-separated objects in the same array (5 max).', json_schema_extra={"ui:widget": "state_editor", "placeholder": '[]'})
    data_transforms: list[CsvboxDataTransform] | None = Field(None, max_length=10, description='PATCH MERGES: unlisted items are untouched, [] is a no-op. Delete one with {"transform_name": "old_one", "_delete": true}.', json_schema_extra={"ui:widget": "state_editor", "placeholder": '[]'})
    pdf_metadata_config: list[CsvboxPdfMetadataField] | None = Field(None, max_length=20, description='Fields to extract from an uploaded PDF/DOCX. Sending the key replaces the whole stored array; omitting it leaves any existing configuration untouched.', examples=[[{'name': 'Author', 'source': 'native'}, {'name': 'Invoice Number', 'source': 'document-kv'}, {'name': 'processed_by', 'source': 'static', 'value': 'AP Team'}, {'name': 'invoice_date', 'source': 'line-match', 'value': 'Invoice Date:'}]], json_schema_extra={"ui:widget": "state_editor", "placeholder": '[]'})

    @model_validator(mode="before")
    @classmethod
    def omit_unset_title(cls, data):
        # The runtime's union-wide string coercion sees Create Sheet's required
        # title too, so an unset optional title can arrive here as "".
        if isinstance(data, dict) and data.get("title") == "" and not cls.model_fields["title"].is_required():
            return {key: value for key, value in data.items() if key != "title"}
        return data


class _Sheet(_Request):
    sheet_license_key: str = Field(..., min_length=1, max_length=190,
        description="Sheet license key (slug) or numeric sheet ID from List Sheets.")

    @field_validator("sheet_license_key")
    @classmethod
    def sheet_key(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Use a single sheet ID or license key")
        return value


class CsvboxListSheetsConfig(_Request):
    """List one page of sheets owned by the API user; use page to continue."""
    operation: Literal["list_sheets"] = "list_sheets"
    page: int = Field(1, ge=1)
    per_page: int = Field(20, ge=1, le=100)


class CsvboxGetSheetConfig(_Sheet):
    """Read a sheet's columns, scripts and importer settings."""
    operation: Literal["get_sheet"] = "get_sheet"


class CsvboxCreateSheetConfig(CsvboxSheetFields):
    """Create a sheet importer. Every supplied script item is created."""
    operation: Literal["create_sheet"] = "create_sheet"
    title: str = Field(..., min_length=1, examples=["Customer Import"])


class CsvboxUpdateSheetConfig(CsvboxSheetFields, _Sheet):
    """PUT updates supplied fields. Supplied script collections replace stored collections: omitted items are deleted, and [] clears the collection."""
    operation: Literal["update_sheet"] = "update_sheet"


class CsvboxPatchSheetConfig(CsvboxSheetFields, _Sheet):
    """PATCH changes only supplied fields. Script collections merge named items; [] is a no-op and _delete removes a named item."""
    operation: Literal["patch_sheet"] = "patch_sheet"


class CsvboxRenameSheetConfig(_Sheet):
    """Change only the sheet title."""
    operation: Literal["rename_sheet"] = "rename_sheet"
    title: str = Field(..., min_length=1, examples=["Updated Sheet"])


class CsvboxSetColumnsConfig(_Sheet):
    """Set the sheet's column definitions and built-in validation rules."""
    operation: Literal["set_sheet_columns"] = "set_sheet_columns"
    sheet_columns: list[CsvboxSheetColumn] = Field(..., json_schema_extra={"ui:widget": "state_editor", "placeholder": '[]'})


class CsvboxSetDestinationsConfig(_Sheet):
    """Configure the destination receiving imported rows."""
    operation: Literal["set_destinations"] = "set_destinations"
    destinations: list[CsvboxDestinations] = Field(..., json_schema_extra={"ui:widget": "state_editor", "placeholder": '[]'})


class CsvboxSetWebhooksConfig(_Sheet):
    """Configure the import-completion webhook."""
    operation: Literal["set_webhooks"] = "set_webhooks"
    webhooks: list[CsvboxWebhook] = Field(..., json_schema_extra={"ui:widget": "state_editor", "placeholder": '[]'})


class CsvboxSetStepsConfig(_Sheet):
    """Configure upload, mapping, verification and result-screen settings."""
    operation: Literal["set_import_steps"] = "set_import_steps"
    steps: CsvboxSteps = Field(..., json_schema_extra={"ui:widget": "state_editor", "placeholder": '{}'})


class CsvboxSetSecurityConfig(_Sheet):
    """Configure region, allowed domains and upload security settings."""
    operation: Literal["set_security_settings"] = "set_security_settings"
    security_settings: CsvboxSecuritySettings = Field(..., json_schema_extra={"ui:widget": "state_editor", "placeholder": '{}'})


class CsvboxMergeVirtualColumnsConfig(_Sheet):
    """Merge computed columns by column_name; _delete removes one and [] is a no-op."""
    operation: Literal["merge_virtual_columns"] = "merge_virtual_columns"
    virtual_columns: list[CsvboxVirtualColumn] = Field(..., max_length=20, json_schema_extra={"ui:widget": "state_editor", "placeholder": '[]'})


class CsvboxMergeValidationFunctionsConfig(_Sheet):
    """Merge validators by function_name. Omitted code and scope fields are preserved on existing items; _delete removes one."""
    operation: Literal["merge_validation_functions"] = "merge_validation_functions"
    validation_functions: list[CsvboxValidationFunction] = Field(..., max_length=10, json_schema_extra={"ui:widget": "state_editor", "placeholder": '[]'})


class CsvboxMergeDataTransformsConfig(_Sheet):
    """Merge transforms by transform_name. Omitted fields are preserved on existing items; _delete removes one."""
    operation: Literal["merge_data_transforms"] = "merge_data_transforms"
    data_transforms: list[CsvboxDataTransform] = Field(..., max_length=10, json_schema_extra={"ui:widget": "state_editor", "placeholder": '[]'})


class CsvboxSetPdfMetadataConfig(_Sheet):
    """Replace the PDF/DOCX metadata extraction configuration; [] clears it."""
    operation: Literal["set_pdf_metadata"] = "set_pdf_metadata"
    pdf_metadata_config: list[CsvboxPdfMetadataField] = Field(..., max_length=20, json_schema_extra={"ui:widget": "state_editor", "placeholder": '[]'})


CsvboxConfig = Annotated[Union[
    CsvboxListSheetsConfig, CsvboxGetSheetConfig, CsvboxCreateSheetConfig,
    CsvboxUpdateSheetConfig, CsvboxPatchSheetConfig, CsvboxRenameSheetConfig,
    CsvboxSetColumnsConfig, CsvboxSetDestinationsConfig, CsvboxSetWebhooksConfig,
    CsvboxSetStepsConfig, CsvboxSetSecurityConfig, CsvboxMergeVirtualColumnsConfig,
    CsvboxMergeValidationFunctionsConfig, CsvboxMergeDataTransformsConfig,
    CsvboxSetPdfMetadataConfig,
], Field(discriminator="operation")]


class CsvboxFullConfig(NodeConfig[CsvboxConfig, CsvboxAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


def _redact(value, credential):
    if isinstance(value, str):
        for secret in (credential.api_key, credential.secret_api_key):
            value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, credential) for item in value]
    if isinstance(value, dict):
        return {_redact(k, credential): _redact(v, credential) for k, v in value.items()}
    return value


def _body(config):
    body = config.model_dump(by_alias=True, exclude_unset=True, exclude={"operation", "sheet_license_key"})
    if not body:
        raise ValueError("Supply at least one sheet field to change")
    for key in ("virtual_columns", "validation_functions", "data_transforms"):
        for item in body.get(key, []):
            if config.operation in {"create_sheet", "update_sheet"}:
                if item.get("_delete"):
                    raise ValueError("_delete is supported only by PATCH actions")
                if not item.get("js_code", "").strip():
                    raise ValueError("Created or replaced script items require js_code")
            if "js_code" in item and not item["js_code"].strip() and not item.get("_delete"):
                raise ValueError("Omit js_code to preserve it; an empty snippet is invalid")
    return body


class CsvboxNode(WorkflowNode):
    integration_type = "automation-csvbox"
    connection_evidence = ConnectionEvidence(noun="Csvbox sheets", operation="list_sheets")

    @classmethod
    def get_config_model(cls):
        return CsvboxFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect your Csvbox API key and secret API key")
        operation = config.operation
        method = METHODS[operation]
        url = BASE
        if hasattr(config, "sheet_license_key"):
            url += "/" + quote(config.sheet_license_key, safe="")
        kwargs = {}
        if operation == "list_sheets":
            kwargs["params"] = {"page": config.page, "per_page": config.per_page}
        elif method != "GET":
            kwargs["json"] = _body(config)
        headers = {
            "Accept": "application/json", "Content-Type": "application/json",
            "x-csvbox-api-key": credential.api_key,
            "x-csvbox-secret-api-key": credential.secret_api_key,
        }
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, url, headers=headers, **kwargs)
        except httpx.RequestError:
            return {"status": "error", "error": "Csvbox request could not be completed"}
        expected = 201 if operation == "create_sheet" else 200
        if len(response.content) > 8_000_000:
            return {"status": "error", "error": "Csvbox response exceeds the size limit", "status_code": response.status_code}
        try:
            body = response.json()
        except (ValueError, UnicodeDecodeError):
            return {"status": "error", "error": "Csvbox returned an unexpected non-JSON response", "status_code": response.status_code}
        failed = isinstance(body, dict) and any(word in str(body.get("status", "")).lower() for word in ("failed", "failure", "error"))
        if response.status_code != expected or not isinstance(body, dict) or body.get("errors") or body.get("error") or failed:
            message = (body.get("message") or body.get("error") or body.get("status")) if isinstance(body, dict) else None
            result = {"status": "error", "error": message if isinstance(message, str) else "Csvbox did not confirm the request", "status_code": response.status_code}
            if isinstance(body, dict) and body.get("errors"):
                result["errors"] = body["errors"]
            return _redact(result, credential)
        if operation == "list_sheets":
            if not isinstance(body.get("data"), list):
                raise ValueError("Csvbox returned an unexpected sheet list")
            result = {"status": "success", "data": body["data"], "links": body.get("links"), "meta": body.get("meta")}
        elif operation == "get_sheet":
            result = {"status": "success", "data": body}
        else:
            if not isinstance(body.get("data"), dict):
                raise ValueError("Csvbox returned an unexpected sheet write result")
            result = {"status": "success", "data": body["data"], "message": body.get("status")}
        return _redact(result, credential)
