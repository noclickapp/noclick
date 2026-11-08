"""Zoho CRM V8 workflows for records and account metadata."""

import json
from typing import Any, Annotated, Literal, Union
from urllib.parse import quote

from utils.ssrf import guarded_async_client
from pydantic import BaseModel, ConfigDict, Discriminator, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.oauth.zoho_crm_oauth import OAUTH_PROVIDER, validate_api_domain
from nodes.scopes.zoho_crm import ZOHO_CRM_SCOPES


def _operation(name: str, label: str, category: str) -> Any:
    return Field(name, title=label, json_schema_extra={
        "const": name, "ui:hidden": True, "x-category": category,
        "x-is-trigger": False, "x-display-name": label,
    })


MODULE_OPTIONS = {"x-dynamic-options": {
    "field_name": "module", "placeholder": "Select a CRM module…",
    "searchable": True, "allow_custom": True, "custom_placeholder": "Or enter a module API name",
}}
JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class ZohoCRMOAuthCredential(BaseModel):
    credential_type: Literal["zoho_crm_oauth"] = Field("zoho_crm_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token")
    refresh_token: str = Field(..., title="Refresh Token")
    expires_at: str = Field(..., title="Token Expiry")
    api_domain: str = Field(..., title="Regional API Domain")
    accounts_server: str = Field(..., title="Regional Accounts Server")
    user_id: str | None = Field(None, title="User ID")
    user_name: str | None = Field(None, title="User Name")
    email: str | None = Field(None, title="Email")

    model_config = ConfigDict(json_schema_extra={
        "title": "Zoho CRM OAuth", "x-credential-type": "oauth", "x-oauth-provider": "zoho_crm",
        "x-oauth-scopes": ZOHO_CRM_SCOPES.declared_scopes(),
        "x-credential-url": "https://api-console.zoho.com/",
    })


class ListModules(BaseModel):
    operation: Literal["list_modules"] = _operation("list_modules", "List Modules", "Metadata")


class ListFields(BaseModel):
    operation: Literal["list_fields"] = _operation("list_fields", "List Module Fields", "Metadata")
    module: str = Field(..., title="Module", json_schema_extra=MODULE_OPTIONS)


class GetCurrentUser(BaseModel):
    operation: Literal["get_current_user"] = _operation("get_current_user", "Get Current User", "Account")


class ListRecords(BaseModel):
    operation: Literal["list_records"] = _operation("list_records", "List Records", "Records")
    module: str = Field(..., title="Module", json_schema_extra=MODULE_OPTIONS)
    fields: str = Field(..., title="Fields", description="Comma-separated field API names, up to 50")
    page: int = Field(1, ge=1, title="Page")
    per_page: int = Field(50, ge=1, le=200, title="Page Size")


class GetRecord(BaseModel):
    operation: Literal["get_record"] = _operation("get_record", "Get Record", "Records")
    module: str = Field(..., title="Module", json_schema_extra=MODULE_OPTIONS)
    record_id: str = Field(..., title="Record ID")


class SearchRecords(BaseModel):
    operation: Literal["search_records"] = _operation("search_records", "Search Records", "Records")
    module: str = Field(..., title="Module", json_schema_extra=MODULE_OPTIONS)
    search_by: Literal["email", "phone", "word", "criteria"] = Field("word", title="Search By")
    search_term: str = Field(..., title="Search Term", description="For criteria, use Zoho's (Field:equals:value) syntax")
    page: int = Field(1, ge=1, title="Page")
    per_page: int = Field(50, ge=1, le=200, title="Page Size")


class CreateRecord(BaseModel):
    operation: Literal["create_record"] = _operation("create_record", "Create Record", "Records")
    module: str = Field(..., title="Module", json_schema_extra=MODULE_OPTIONS)
    record_json: str = Field(..., title="Record Fields (JSON)", description="One object keyed by field API names", json_schema_extra=JSON_EDITOR)


class UpdateRecord(BaseModel):
    operation: Literal["update_record"] = _operation("update_record", "Update Record", "Records")
    module: str = Field(..., title="Module", json_schema_extra=MODULE_OPTIONS)
    record_id: str = Field(..., title="Record ID")
    record_json: str = Field(..., title="Fields to Update (JSON)", json_schema_extra=JSON_EDITOR)


class UpsertRecord(BaseModel):
    operation: Literal["upsert_record"] = _operation("upsert_record", "Upsert Record", "Records")
    module: str = Field(..., title="Module", json_schema_extra=MODULE_OPTIONS)
    record_json: str = Field(..., title="Record Fields (JSON)", json_schema_extra=JSON_EDITOR)
    duplicate_check_fields: str | None = Field(None, title="Duplicate Check Fields", description="Optional comma-separated field API names")


class DeleteRecord(BaseModel):
    operation: Literal["delete_record"] = _operation("delete_record", "Delete Record", "Records")
    module: str = Field(..., title="Module", json_schema_extra=MODULE_OPTIONS)
    record_id: str = Field(..., title="Record ID")


ZohoCRMConfig = Annotated[Union[
    ListModules, ListFields, GetCurrentUser, ListRecords, GetRecord,
    SearchRecords, CreateRecord, UpdateRecord, UpsertRecord, DeleteRecord,
], Discriminator("operation")]


class ZohoCRMNodeConfig(NodeConfig[ZohoCRMConfig, ZohoCRMOAuthCredential]):
    pass


def _record_object(raw: str) -> dict:
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise ValueError("Record fields must be valid JSON") from exc
    if not isinstance(value, dict) or not value:
        raise ValueError("Record fields must be a non-empty JSON object")
    return value


class ZohoCRMNode(WorkflowNode):
    integration_type = "automation-zoho-crm"
    connection_evidence = ConnectionEvidence(operation="list_modules", noun="CRM modules", identity_operation="get_current_user")
    scope_registry = ZOHO_CRM_SCOPES
    edit_examples = [
        "Find a Zoho CRM contact by email", "Create a lead in Zoho CRM",
        "Update a Zoho CRM deal", "List Zoho CRM modules and fields",
    ]

    @classmethod
    def get_config_model(cls):
        return ZohoCRMNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        if not credential_data:
            return credential_data
        refresh = OAUTH_PROVIDER.bind_refresh(credential_data)
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=refresh, additional_token_fields=OAUTH_PROVIDER.credential_fields, provider="zoho_crm")

    @classmethod
    async def load_field_options(
        cls, field_name: str, credential_data: dict, context=None,
        page_token=None, search=None,
    ) -> list[dict]:
        if field_name != "module":
            return []
        await cls.freshen_credential(credential_data)
        payload = await cls._request(credential_data, "GET", "/settings/modules")
        options = [{"value": item["api_name"], "label": item.get("module_name") or item["api_name"]}
                   for item in payload.get("modules", []) if item.get("api_name")]
        if search:
            query = search.casefold()
            options = [option for option in options if query in option["label"].casefold()
                       or query in option["value"].casefold()]
        return options

    @staticmethod
    async def _request(credential: dict, method: str, path: str, *, params=None, body=None) -> dict:
        base = validate_api_domain(credential["api_domain"])
        async with guarded_async_client(timeout=45) as client:
            response = await client.request(
                method, f"{base}/crm/v8{path}", params=params, json=body,
                headers={"Authorization": f"Zoho-oauthtoken {credential['access_token']}"},
            )
        if response.status_code == 204:
            return {"data": [], "info": {"count": 0}}
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError(f"Zoho CRM API error {response.status_code}: invalid response") from exc
        if response.is_error or payload.get("code") not in (None, "SUCCESS"):
            raise ValueError(f"Zoho CRM API error {response.status_code}: {payload.get('message') or payload.get('code') or 'request failed'}")
        failures = [row for row in payload.get("data", []) if isinstance(row, dict) and row.get("status") == "error"]
        if failures:
            failed = failures[0]
            raise ValueError(f"Zoho CRM record error: {failed.get('message') or failed.get('code') or 'request failed'}")
        return payload

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, ZohoCRMNodeConfig):
            raise ValueError("Zoho CRM configuration required")
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Zoho CRM account")
        auth = credential.model_dump()
        await self.freshen_credential(auth, user_id=self.user_id,
                                      credential_id=(self.node_data or {}).get("credential_id"))
        op = self.config.config
        name = op.operation
        self.scope_registry.require(name)
        method, path, params, body = "GET", "", None, None
        if isinstance(op, ListModules):
            path = "/settings/modules"
        elif isinstance(op, ListFields):
            path, params = "/settings/fields", {"module": op.module}
        elif isinstance(op, GetCurrentUser):
            path, params = "/users", {"type": "CurrentUser"}
        elif isinstance(op, ListRecords):
            path = f"/{quote(op.module, safe='')}"
            params = {"fields": op.fields, "page": op.page, "per_page": op.per_page}
        elif isinstance(op, GetRecord):
            path = f"/{quote(op.module, safe='')}/{quote(op.record_id, safe='')}"
        elif isinstance(op, SearchRecords):
            path = f"/{quote(op.module, safe='')}/search"
            params = {op.search_by: op.search_term, "page": op.page, "per_page": op.per_page}
        elif isinstance(op, CreateRecord):
            method, path = "POST", f"/{quote(op.module, safe='')}"
            body = {"data": [_record_object(op.record_json)]}
        elif isinstance(op, UpdateRecord):
            method, path = "PUT", f"/{quote(op.module, safe='')}/{quote(op.record_id, safe='')}"
            body = {"data": [_record_object(op.record_json)]}
        elif isinstance(op, UpsertRecord):
            method, path = "POST", f"/{quote(op.module, safe='')}/upsert"
            body = {"data": [_record_object(op.record_json)]}
            if op.duplicate_check_fields:
                body["duplicate_check_fields"] = [field.strip() for field in op.duplicate_check_fields.split(",") if field.strip()]
        elif isinstance(op, DeleteRecord):
            method, path = "DELETE", f"/{quote(op.module, safe='')}/{quote(op.record_id, safe='')}"
        else:
            raise ValueError(f"Unsupported Zoho CRM operation: {name}")
        payload = await self._request(auth, method, path, params=params, body=body)
        return {"status": "success", "operation": name, "data": payload}
