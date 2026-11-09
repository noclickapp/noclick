"""Zoho Creator v2.1 record, metadata and bulk-job operations.

Provider contract: https://creator.zoho.com/api/v2.1/downloadOAS (version 2.0).
Each operation makes exactly one API request. Lists return one page, preserving
provider fields, partial record results, more_records and the record cursor.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.oauth.zoho_creator_oauth import OAUTH_PROVIDER, validate_accounts_server, validate_api_domain
from nodes.scopes.zoho_creator import ZOHO_CREATOR_SCOPES
from utils.ssrf import guarded_async_client


class ZohoCreatorOAuthCredential(BaseModel):
    model_config = ConfigDict(title="Zoho Creator OAuth", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "oauth", "x-oauth-provider": "zoho_creator",
            "x-oauth-scopes": sorted(ZOHO_CREATOR_SCOPES.declared_scopes()),
            "x-credential-url": "https://api-console.zoho.com/",
            "x-credential-instructions": "Sign in with Zoho to grant access to Creator apps and records. For a manual connection, supply an existing OAuth access token and its refresh token, expiry, accounts server and API domain. Mutations run the app's associated workflows by default.",
        })
    credential_type: Literal["zoho_creator_oauth"] = Field("zoho_creator_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, title="Access token", repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: str = Field(..., min_length=1, title="Refresh token", repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: str = Field(..., title="Token expiry", description="ISO 8601 UTC timestamp at which the access token expires.")
    accounts_server: str = Field(..., title="Accounts server", description="Regional Zoho accounts origin, such as https://accounts.zoho.com.")
    api_domain: str = Field(..., title="API domain", description="api_domain from the token response, such as https://www.zohoapis.com.")
    _accounts = field_validator("accounts_server")(validate_accounts_server)
    _api = field_validator("api_domain")(validate_api_domain)


def segment(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", value):
        raise ValueError("Use a single Zoho Creator link name or ID, without slashes or URL encoding")
    return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def identifiers(cls, value, info):
        if info.field_name in {"account_owner_name", "app_link_name", "form_link_name", "report_link_name", "record_id", "job_id"}:
            return segment(value)
        return value

    @model_validator(mode="after")
    def custom_fields(self):
        if getattr(self, "field_config", None) == "custom" and not getattr(self, "fields", None):
            raise ValueError("Custom field selection requires fields")
        return self


def identifier(title):
    return (str, Field(..., min_length=1, max_length=255, title=title))


OWNER = {"account_owner_name": identifier("Account owner / workspace name")}
APP = {**OWNER, "app_link_name": identifier("Application link name")}
FORM = {**APP, "form_link_name": identifier("Form link name")}
REPORT = {**APP, "report_link_name": identifier("Report link name")}
RECORD = {**REPORT, "record_id": identifier("Record ID")}
JOB = {"job_id": identifier("Bulk job ID")}
CRITERIA = (str, Field(..., min_length=1, max_length=10000, title="Filter criteria", description='Zoho criteria, for example Email == "jason@zylker.com". Required for mutations; these affect up to 200 matching records.'))
DATA = (dict[str, Any], Field(..., min_length=1, title="Record fields", description="JSON object mapping field link names to values."))
SELECT = {
    "field_config": (Literal["quick_view", "detail_view", "custom", "all"] | None, Field(None, title="Field selection")),
    "fields": (list[str] | None, Field(None, min_length=1, title="Field link names", description="Used with custom field selection.")),
}


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    label: str
    fields: dict[str, tuple[Any, Any]]
    category: str
    body_keys: tuple[str, ...] = ()
    query_keys: tuple[str, ...] = ()


OPS = {
    "list_applications": Operation("GET", "/meta/applications", "List Applications", {}, "Applications"),
    "list_workspace_applications": Operation("GET", "/meta/{account_owner_name}/applications", "List Workspace Applications", OWNER, "Applications"),
    "list_forms": Operation("GET", "/meta/{account_owner_name}/{app_link_name}/forms", "List Forms", APP, "Metadata"),
    "list_reports": Operation("GET", "/meta/{account_owner_name}/{app_link_name}/reports", "List Reports", APP, "Metadata"),
    "list_pages": Operation("GET", "/meta/{account_owner_name}/{app_link_name}/pages", "List Pages", APP, "Metadata"),
    "list_sections": Operation("GET", "/meta/{account_owner_name}/{app_link_name}/sections", "List Sections", APP, "Metadata"),
    "list_fields": Operation("GET", "/meta/{account_owner_name}/{app_link_name}/form/{form_link_name}/fields", "List Form Fields", FORM, "Metadata"),
    "list_records": Operation("GET", "/data/{account_owner_name}/{app_link_name}/report/{report_link_name}", "List or Search Records", {
        **REPORT, **SELECT,
        "criteria": (str | None, Field(None, max_length=10000, title="Filter criteria")),
        "max_records": (Literal[200, 500, 1000], Field(200, title="Page size")),
        "record_cursor": (str | None, Field(None, max_length=4096, title="Record cursor", description="Use the returned record_cursor with the same report and filters for the next page.")),
    }, "Records", query_keys=("criteria", "max_records", "field_config", "fields")),
    "get_record": Operation("GET", "/data/{account_owner_name}/{app_link_name}/report/{report_link_name}/{record_id}", "Get Record", {**RECORD, **SELECT}, "Records", query_keys=("field_config", "fields")),
    "add_records": Operation("POST", "/data/{account_owner_name}/{app_link_name}/form/{form_link_name}", "Add Records", {
        **FORM, "data": (list[dict[str, Any]], Field(..., min_length=1, max_length=200, title="Records", description="Array of JSON objects keyed by field link name. Associated workflows run by default.")),
    }, "Records", body_keys=("data",)),
    "update_record": Operation("PATCH", "/data/{account_owner_name}/{app_link_name}/report/{report_link_name}/{record_id}", "Update Record", {**RECORD, "data": DATA}, "Records", body_keys=("data",)),
    "update_records": Operation("PATCH", "/data/{account_owner_name}/{app_link_name}/report/{report_link_name}", "Update Matching Records", {
        **REPORT, "criteria": CRITERIA, "data": DATA,
        "process_until_limit": (bool, Field(False, title="Process first 200 matches", description="When enabled, update the first 200 matches and inspect more_records before continuing.")),
    }, "Records", body_keys=("data", "criteria"), query_keys=("process_until_limit",)),
    "delete_record": Operation("DELETE", "/data/{account_owner_name}/{app_link_name}/report/{report_link_name}/{record_id}", "Delete Record", RECORD, "Records"),
    "delete_records": Operation("DELETE", "/data/{account_owner_name}/{app_link_name}/report/{report_link_name}", "Delete Matching Records", {
        **REPORT, "criteria": CRITERIA,
        "process_until_limit": (bool, Field(False, title="Process first 200 matches")),
    }, "Records", body_keys=("criteria",), query_keys=("process_until_limit",)),
    "create_bulk_read": Operation("POST", "/bulk/{account_owner_name}/{app_link_name}/report/{report_link_name}/read", "Create Bulk Read Job", {
        **REPORT,
        "criteria": (str | None, Field(None, max_length=10000, title="Filter criteria")),
        "fields": (list[str] | None, Field(None, min_length=1, title="Field link names")),
        "max_records": (int, Field(100000, ge=100000, le=200000, title="Maximum export records")),
    }, "Bulk Jobs", body_keys=("criteria", "fields", "max_records")),
    "get_bulk_read": Operation("GET", "/bulk/{account_owner_name}/{app_link_name}/report/{report_link_name}/read/{job_id}", "Get Bulk Read Job", {**REPORT, **JOB}, "Bulk Jobs"),
    "get_bulk_insert": Operation("GET", "/bulk/{account_owner_name}/{app_link_name}/form/{form_link_name}/insert/{job_id}", "Get Bulk Insert Job", {**FORM, **JOB}, "Bulk Jobs"),

}

OP_MODELS = {
    name: create_model("ZohoCreator" + "".join(w.title() for w in name.split("_")) + "Config", __base__=_Input,
        operation=(Literal[name], Field(name, title=spec.label, json_schema_extra={
            "ui:hidden": True, "x-operation-category": spec.category,
            "x-operation-kind": "read" if spec.method == "GET" else "write",
        })), **spec.fields)
    for name, spec in OPS.items()
}
OperationConfig = Annotated[Union[tuple(OP_MODELS.values())], Field(discriminator="operation")]


class ZohoCreatorConfig(NodeConfig[OperationConfig, ZohoCreatorOAuthCredential]):
    pass


async def creator_request(credential, method, path, *, params=None, body=None, record_cursor=None):
    origin = validate_api_domain(credential["api_domain"])
    headers = {"Authorization": "Bearer " + credential["access_token"], "Accept": "application/json"}
    if record_cursor:
        if any(ord(c) < 32 or ord(c) == 127 for c in record_cursor):
            raise ValueError("Record cursor must not contain control characters")
        headers["record_cursor"] = record_cursor
    async with guarded_async_client(timeout=30, follow_redirects=False) as client:
        response = await client.request(method, origin + "/creator/v2.1" + path,
            headers=headers, params=params, json=body)
    try:
        data = response.json()
    except ValueError:
        raise ValueError(f"Zoho Creator returned an unexpected non-JSON response (HTTP {response.status_code})") from None
    if not isinstance(data, dict):
        raise ValueError("Zoho Creator returned an unexpected response shape")
    if not 200 <= response.status_code < 300 or data.get("code") != 3000 or data.get("error"):
        message = str(data.get("message") or data.get("error") or f"Zoho Creator returned HTTP {response.status_code}, code {data.get('code')}")
        for key in ("access_token", "refresh_token"):
            if credential.get(key): message = message.replace(credential[key], "[redacted]")
        raise ValueError(message)
    # Per-record failures remain visible; an accepted batch is not proof that every row succeeded.
    return {"http_status": response.status_code, "data": data, "record_cursor": response.headers.get("record_cursor")}


class ZohoCreatorNode(WorkflowNode):
    integration_type = "automation-zoho-creator"
    scope_registry = ZOHO_CREATOR_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_applications", noun="applications",
        label_keys=("application_name", "link_name"))
    edit_examples = ["Add records to a Zoho Creator form", "Find Zoho Creator records", "Update a Zoho Creator record"]

    @classmethod
    def get_config_model(cls):
        return ZohoCreatorConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        return await freshen_oauth_credential(credential_data, pool=pool, user_id=user_id,
            credential_id=credential_id, refresh=OAUTH_PROVIDER.bind_refresh(credential_data),
            additional_token_fields=OAUTH_PROVIDER.credential_fields, provider="zoho_creator")

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Zoho Creator account")
        credential = self.config.credentials.model_dump()
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        await ensure_fresh_oauth_token(credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id, credential=credential, refresh=OAUTH_PROVIDER.bind_refresh(credential),
            additional_token_fields=OAUTH_PROVIDER.credential_fields,
            provider="zoho_creator", caller_path="execute")
        config = self.config.config
        spec = OPS[config.operation]
        values = config.model_dump(exclude_none=True)
        path = spec.path
        for key in re.findall(r"\{([^}]+)\}", path):
            path = path.replace("{" + key + "}", quote(segment(values[key]), safe=""))
        params = {key: values[key] for key in spec.query_keys if key in values}
        if "fields" in params:
            params["fields"] = ",".join(segment(field) for field in params["fields"])
        body = {key: values[key] for key in spec.body_keys if key in values}
        if config.operation == "create_bulk_read":
            body = {"query": body}
        result = await creator_request(credential, spec.method, path, params=params or None,
            body=body or None, record_cursor=values.get("record_cursor"))
        return {"operation": config.operation, **result}
