"""SimpleLocalize project API: one documented request per operation.

Translation reads return one page, including provider pagination metadata.
Writes report the provider's acknowledgement; they do not imply publication.
Contract: https://api.simplelocalize.io/openapi/docs
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.simplelocalize.io"
CREDENTIAL_TYPE = "simple_localize_api_key"


class SimpleLocalizeAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="SimpleLocalize API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://simplelocalize.io/docs/api/get-started/",
            "x-credential-instructions": "Paste the project API key from Settings > Credentials > API Key. NoClick sends it in X-SimpleLocalize-Token. Use a project API key, not an account personal token. Customer translations require the provider's Business plan.",
        })
    credential_type: Literal["simple_localize_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Project API key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Project API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the project API key without a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def path_segment(cls, value, info):
        if info.field_name in {"language_key", "customer_key", "tag_name"}:
            if value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("Use a single resource key without control characters")
        return value


class GetProject(_Input):
    operation: Literal["get_project"] = Field("get_project", title="Get Project Details", json_schema_extra={"ui:hidden": True})


class ListTranslations(_Input):
    operation: Literal["list_translations"] = Field("list_translations", title="List Translations", description="Returns one page with provider pagination metadata. Increment page for subsequent pages.", json_schema_extra={"ui:hidden": True})
    key: str | None = None
    namespace: str | None = None
    language: str | None = None
    text: str | None = Field(None, min_length=3, description="Contains search; provider limits results to 10.")
    query: str | None = Field(None, min_length=3, description="Search text or key; provider limits results to 10.")
    text_status: Literal["EMPTY", "NOT_EMPTY"] | None = None
    customer_id: str | None = Field(None, description="Customer key; Business plan only.")
    base_only: bool | None = Field(None, strict=True)
    review_status: Literal["REVIEWED", "NOT_REVIEWED"] | None = None
    page: int = Field(0, ge=0, strict=True)
    size: int = Field(100, ge=1, le=2500, strict=True)
    sort_by: Literal["lastModifiedAt"] | None = None
    sort_order: Literal["asc", "desc"] = "desc"
    version: Literal["REVIEWED"] | None = Field(None, description="Last reviewed version, or empty text when absent.")


class UpdateTranslation(_Input):
    operation: Literal["update_translation"] = Field("update_translation", title="Update Translation", description="The key and language must exist. If review status is omitted, the provider marks the translation NOT_REVIEWED.", json_schema_extra={"ui:hidden": True})
    key: str = Field(..., min_length=1)
    language: str = Field(..., min_length=1)
    text: str = Field(..., max_length=30000, json_schema_extra={"ui:widget": "textarea"})
    namespace: str | None = None
    customer_id: str | None = Field(None, description="Customer key; Business plan only.")
    review_status: Literal["REVIEWED", "NOT_REVIEWED"] | None = None


class ListTranslationKeys(_Input):
    operation: Literal["list_translation_keys"] = Field("list_translation_keys", title="List Translation Keys", description="Returns all keys without metadata; provider does not paginate this endpoint.", json_schema_extra={"ui:hidden": True})
    id: str | None = Field(None, title="Filter by key ID")


class _KeyMetadata(_Input):
    description: str | None = Field(None, max_length=500)
    code_description: str | None = Field(None, max_length=500)
    characters_limit: int | None = Field(None, strict=True)
    lock: bool | None = Field(None, strict=True)
    deprecated: bool | None = Field(None, strict=True)
    tags: list[str] | None = Field(None, max_length=5)
    attributes: dict | None = None


class CreateTranslationKey(_KeyMetadata):
    operation: Literal["create_translation_key"] = Field("create_translation_key", title="Create Translation Key", json_schema_extra={"ui:hidden": True})
    key: str = Field(..., min_length=1, max_length=500)
    namespace: str | None = Field(None, max_length=128)


class _Key(_Input):
    key: str = Field(..., min_length=1, max_length=500)
    namespace: str | None = Field(None, max_length=128)


class UpdateTranslationKey(_KeyMetadata, _Key):
    operation: Literal["update_translation_key"] = Field("update_translation_key", title="Update Translation Key", description="Key and namespace identify the original key; new key and new namespace rename it.", json_schema_extra={"ui:hidden": True})
    new_key: str | None = Field(None, min_length=1, max_length=500)
    new_namespace: str | None = Field(None, max_length=128)


class DeleteTranslationKey(_Key):
    operation: Literal["delete_translation_key"] = Field("delete_translation_key", title="Delete Translation Key", description="Deletes the key and its translations.", json_schema_extra={"ui:hidden": True})


class ListLanguages(_Input):
    operation: Literal["list_languages"] = Field("list_languages", title="List Project Languages", json_schema_extra={"ui:hidden": True})


class _Language(_Input):
    language_key: str = Field(..., min_length=1, max_length=20, title="Existing language key")


class GetLanguage(_Language):
    operation: Literal["get_language"] = Field("get_language", title="Get Language", json_schema_extra={"ui:hidden": True})


class CreateLanguage(_Input):
    operation: Literal["create_language"] = Field("create_language", title="Create Language", json_schema_extra={"ui:hidden": True})
    key: str = Field(..., min_length=1, max_length=20)
    name: str | None = Field(None, max_length=200)


class UpdateLanguage(_Language):
    operation: Literal["update_language"] = Field("update_language", title="Update Language", json_schema_extra={"ui:hidden": True})
    key: str | None = Field(None, min_length=1, max_length=20, title="New language key")
    name: str | None = Field(None, max_length=200)


class DeleteLanguage(_Language):
    operation: Literal["delete_language"] = Field("delete_language", title="Delete Language", description="Also removes all translations for this language.", json_schema_extra={"ui:hidden": True})


class ListTags(_Input):
    operation: Literal["list_tags"] = Field("list_tags", title="List Tags", json_schema_extra={"ui:hidden": True})


class _TagFields(_Input):
    name: str | None = Field(None, min_length=2, max_length=16, pattern=r"^[A-Za-z0-9\s_.-]+$")
    color: str | None = Field(None, pattern=r"^[0-9A-Fa-f]{6}$", description="Six hexadecimal digits without #.")


class CreateTag(_TagFields):
    operation: Literal["create_tag"] = Field("create_tag", title="Create Tag", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=2, max_length=16, pattern=r"^[A-Za-z0-9\s_.-]+$")


class _Tag(_Input):
    tag_name: str = Field(..., min_length=2, max_length=16, pattern=r"^[A-Za-z0-9\s_.-]+$", title="Existing tag name")


class UpdateTag(_Tag, _TagFields):
    operation: Literal["update_tag"] = Field("update_tag", title="Update Tag", json_schema_extra={"ui:hidden": True})


class DeleteTag(_Tag):
    operation: Literal["delete_tag"] = Field("delete_tag", title="Delete Tag", json_schema_extra={"ui:hidden": True})


class ListCustomers(_Input):
    operation: Literal["list_customers"] = Field("list_customers", title="List Customers", json_schema_extra={"ui:hidden": True})


class _Customer(_Input):
    customer_key: str = Field(..., min_length=1, max_length=40, title="Existing customer key")


class GetCustomer(_Customer):
    operation: Literal["get_customer"] = Field("get_customer", title="Get Customer", json_schema_extra={"ui:hidden": True})


class _CustomerFields(_Input):
    display_name: str | None = Field(None, max_length=32)
    description: str | None = Field(None, max_length=255)


class CreateCustomer(_CustomerFields):
    operation: Literal["create_customer"] = Field("create_customer", title="Create Customer", json_schema_extra={"ui:hidden": True})
    key: str = Field(..., min_length=1, max_length=40)


class UpdateCustomer(_Customer, _CustomerFields):
    operation: Literal["update_customer"] = Field("update_customer", title="Update Customer", json_schema_extra={"ui:hidden": True})
    key: str | None = Field(None, min_length=1, max_length=40, title="New customer key")


class DeleteCustomer(_Customer):
    operation: Literal["delete_customer"] = Field("delete_customer", title="Delete Customer", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[GetProject, ListTranslations, UpdateTranslation, ListTranslationKeys,
    CreateTranslationKey, UpdateTranslationKey, DeleteTranslationKey, ListLanguages, GetLanguage,
    CreateLanguage, UpdateLanguage, DeleteLanguage, ListTags, CreateTag, UpdateTag, DeleteTag,
    ListCustomers, GetCustomer, CreateCustomer, UpdateCustomer, DeleteCustomer], Field(discriminator="operation")]


class SimpleLocalizeConfig(NodeConfig[Operation, SimpleLocalizeAPIKeyCredential]):
    pass


# operation -> method, contract route, query fields, response kind.
ROUTES = {
    "get_project": ("GET", "/api/v2/project", (), "object"),
    "list_translations": ("GET", "/api/v2/translations", ("key", "namespace", "language", "text", "query", "text_status", "customer_id", "base_only", "review_status", "page", "size", "sort_by", "sort_order", "version"), "translations"),
    "update_translation": ("PATCH", "/api/v2/translations", (), "ack"),
    "list_translation_keys": ("GET", "/api/v2/translation-keys/list", ("id",), "list"),
    "create_translation_key": ("POST", "/api/v1/translation-keys", (), "ack"),
    "update_translation_key": ("PATCH", "/api/v1/translation-keys", ("key", "namespace"), "ack"),
    "delete_translation_key": ("DELETE", "/api/v1/translation-keys", ("key", "namespace"), "ack"),
    "list_languages": ("GET", "/api/v1/languages", (), "list"),
    "get_language": ("GET", "/api/v1/languages/{language_key}", (), "object"),
    "create_language": ("POST", "/api/v1/languages", (), "object"),
    "update_language": ("PATCH", "/api/v1/languages/{language_key}", (), "object"),
    "delete_language": ("DELETE", "/api/v1/languages/{language_key}", (), "ack"),
    "list_tags": ("GET", "/api/v1/tags", (), "list"),
    "create_tag": ("POST", "/api/v1/tags", (), "ack"),
    "update_tag": ("PATCH", "/api/v1/tags/{tag_name}", (), "ack"),
    "delete_tag": ("DELETE", "/api/v1/tags/{tag_name}", (), "ack"),
    "list_customers": ("GET", "/api/v1/customers", (), "list"),
    "get_customer": ("GET", "/api/v1/customers/{customer_key}", (), "object"),
    "create_customer": ("POST", "/api/v1/customers", (), "object"),
    "update_customer": ("PATCH", "/api/v1/customers/{customer_key}", (), "object"),
    "delete_customer": ("DELETE", "/api/v1/customers/{customer_key}", (), "ack"),
}
WIRE_NAMES = {"text_status": "textStatus", "customer_id": "customerId", "base_only": "baseOnly",
    "review_status": "reviewStatus", "sort_by": "sortBy", "sort_order": "sortOrder",
    "code_description": "codeDescription", "characters_limit": "charactersLimit",
    "display_name": "displayName", "new_key": "key", "new_namespace": "namespace"}


def _request_parts(op):
    method, template, query_fields, kind = ROUTES[op.operation]
    fields = op.model_dump(exclude_none=True, exclude={"operation"})
    path = template.format(**{key: quote(fields.pop(key), safe="") for key in re.findall(r"{([^}]+)}", template)})
    params = {WIRE_NAMES.get(key, key): fields.pop(key) for key in query_fields if key in fields}
    params = {key: str(value).lower() if isinstance(value, bool) else value for key, value in params.items()}
    body = {WIRE_NAMES.get(key, key): value for key, value in fields.items()}
    if method == "PATCH" and not body:
        raise ValueError("Provide at least one field to update")
    return method, path, params, body if method in {"POST", "PATCH"} else None, kind


def _redact(value, token):
    if isinstance(value, dict):
        return {str(k).replace(token, "[redacted]"): _redact(v, token) for k, v in value.items() if k.lower() not in {"apikey", "api_key", "authorization", "x-simplelocalize-token"}}
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    return value.replace(token, "[redacted]") if isinstance(value, str) else value


class SimpleLocalizeNode(WorkflowNode):
    integration_type = "automation-simple-localize"
    connection_evidence = ConnectionEvidence(identity_operation="get_project", noun="project", identity_keys=("name", "projectToken"))

    @classmethod
    def get_config_model(cls):
        return SimpleLocalizeConfig

    @classmethod
    def parse_config(cls, config_data):
        credential = config_data.get("credentials")
        if isinstance(credential, dict) and credential.get("credential_type", CREDENTIAL_TYPE) != CREDENTIAL_TYPE:
            raise ValueError("Connect a SimpleLocalize project API key")
        return super().parse_config(config_data)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a SimpleLocalize project API key")
        op = self.config.config
        token = self.config.credentials.api_key
        method, path, params, body, kind = _request_parts(op)
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"X-SimpleLocalize-Token": token, "Accept": "application/json"},
                    params=params, **({"json": body} if body is not None else {}))
            if response.status_code != 200:
                message = "SimpleLocalize request failed"
                try:
                    error = response.json()
                    if isinstance(error, dict) and isinstance(error.get("msg"), str):
                        message = error["msg"]
                except ValueError:
                    pass
                result = {"status": "error", "http_status": response.status_code, "message": message}
            else:
                payload = None
                if response.content.strip():
                    if len(response.content) > 20_000_000 or "json" not in response.headers.get("content-type", "").lower():
                        raise ValueError("Expected bounded JSON")
                    payload = response.json()
                    if not isinstance(payload, dict) or payload.get("error") or payload.get("errors") or payload.get("success") is False:
                        raise ValueError("Unexpected response envelope")
                    if "status" in payload and payload["status"] != 200:
                        message = payload.get("msg")
                        result = {"status": "error", "http_status": 200, "message": message if isinstance(message, str) else "SimpleLocalize reported an error"}
                        result = _redact(result, token)
                        await self.emit(result)
                        return result
                if kind == "ack":
                    result = {"status": "success", "acknowledged": True, "http_status": 200}
                else:
                    data = payload.get("data") if isinstance(payload, dict) else None
                    if kind == "list":
                        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
                            raise ValueError("Expected a resource list")
                    elif kind == "translations":
                        # The published guide returns a data array; OpenAPI also
                        # describes a nested paged object. Keep either intact.
                        if not isinstance(data, (dict, list)) or (isinstance(data, list) and any(not isinstance(row, dict) for row in data)):
                            raise ValueError("Expected translation data")
                    elif not isinstance(data, dict):
                        raise ValueError("Expected a resource object")
                    if op.operation == "get_project" and (not isinstance(data.get("name"), str) or not data["name"].strip()):
                        raise ValueError("Expected a named project")
                    result = {"status": "success", "http_status": 200, "data": data}
                    if kind == "translations" and "pageDetails" in payload:
                        result["pageDetails"] = payload["pageDetails"]
        except httpx.HTTPError:
            result = {"status": "error", "message": "SimpleLocalize request did not complete; inspect the resource before retrying a write"}
        except ValueError:
            result = {"status": "error", "message": "SimpleLocalize returned an unexpected response; inspect the resource before retrying a write"}
        result = _redact({"operation": op.operation, **result}, token)
        await self.emit(result)
        return result
