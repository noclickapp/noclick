"""Fulcrum REST v2 organization-scoped forms and field records.

Native operations retain staging credential loading, form ancestry and exact
record PATCH semantics. Tokens stay in headers; no SQL or generic request exists.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
from typing import Annotated, Any, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

API_ROOT = "https://api.fulcrumapp.com/api/v2"
HIDDEN = {"ui:hidden": True}


def _uuid(value):
    try:
        if not isinstance(value, str):
            raise ValueError()
        return str(UUID(value))
    except (ValueError, AttributeError):
        raise ValueError("Enter a Fulcrum resource UUID.") from None


def _field_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Use a Fulcrum field key from the selected form.")
    return value


def _bounded_json(value):
    count = [0]
    def visit(item, depth=0):
        count[0] += 1
        if count[0] > 10000 or depth > 10:
            raise ValueError("Fulcrum field data exceeds the nested value limit.")
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float and math.isfinite(item):
            return
        if isinstance(item, list) and len(item) <= 1000:
            for child in item:
                visit(child, depth + 1)
            return
        if isinstance(item, dict) and len(item) <= 1000 and all(isinstance(key, str) and len(key) <= 256 for key in item):
            for child in item.values():
                visit(child, depth + 1)
            return
        raise ValueError("Use bounded JSON field data with finite numbers.")
    visit(value)
    if len(json.dumps(value, allow_nan=False).encode()) > 400000:
        raise ValueError("Fulcrum field data exceeds the size limit.")
    return value


class FulcrumAPITokenCredential(BaseModel):
    credential_type: Literal["fulcrum_api_token"] = Field("fulcrum_api_token", json_schema_extra=HIDDEN)
    api_token: str = Field(..., min_length=1, max_length=4096, title="API Token",
        description="Token for one Fulcrum US organization. Developer Pack/API entitlement and current user permissions are required.",
        json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="Fulcrum API Token", extra="ignore", json_schema_extra={
        "x-credential-url": "https://web.fulcrumapp.com/settings/api"})

    @field_validator("api_token")
    @classmethod
    def token_value(cls, value):
        value = clean_secret(value)
        if not value or re.search(r"[\x00-\x20\x7f]", value):
            raise ValueError("Use a nonempty Fulcrum API token without whitespace.")
        return value


def _credential(data):
    if not isinstance(data, dict) or data.get("credential_type") != "fulcrum_api_token":
        raise ValueError("Use a current Fulcrum API-token connection.")
    try:
        shaped = FulcrumAPITokenCredential.model_validate({key: data[key] for key in
            FulcrumAPITokenCredential.model_fields if key in data}).model_dump(mode="json")
    except Exception:
        raise ValueError("Fulcrum credential fields are invalid.") from None
    return {**data, **shaped}


def _selector(field, parent=None):
    dynamic = {"field_name": field, "searchable": True, "allow_custom": True}
    if parent:
        dynamic["depends_on"] = parent
    resource = field.removesuffix("_id")
    return {"x-dynamic-options": dynamic, "x-resource-type": "fulcrum_" + resource}


class FulcrumOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FulcrumPage(FulcrumOperation):
    per_page: int = Field(25, ge=1, le=100, description="Local safety cap; Fulcrum's larger default is never used.")
    page: int = Field(1, ge=1, le=100000)
    page_token: Optional[str] = Field(None, max_length=4096)


class FulcrumForm(FulcrumOperation):
    form_id: str = Field(..., title="Form", json_schema_extra=_selector("form_id"))
    _validate_form = field_validator("form_id", mode="before")(_uuid)


class FulcrumRecord(FulcrumForm):
    record_id: str = Field(..., title="Record in Form", json_schema_extra=_selector("record_id", "form_id"))
    _validate_record = field_validator("record_id", mode="before")(_uuid)


class FulcrumProject(FulcrumOperation):
    project_id: str = Field(..., title="Project", json_schema_extra=_selector("project_id"))
    _validate_project = field_validator("project_id", mode="before")(_uuid)


class FulcrumChoiceList(FulcrumOperation):
    choice_list_id: str = Field(..., title="Choice List", json_schema_extra=_selector("choice_list_id"))
    _validate_list = field_validator("choice_list_id", mode="before")(_uuid)


class FulcrumListFormsConfig(FulcrumPage):
    operation: Literal["list_forms"] = Field("list_forms", json_schema_extra={"x-display-name": "List Forms", "x-category": "Forms"})
    status: Literal["active", "inactive", "all"] = "active"


class FulcrumGetFormConfig(FulcrumForm):
    operation: Literal["get_form"] = Field("get_form", json_schema_extra={"x-display-name": "Get Form", "x-category": "Forms"})


class FulcrumFormFieldsConfig(FulcrumForm):
    operation: Literal["get_form_fields"] = Field("get_form_fields", json_schema_extra={"x-display-name": "Get Form Fields", "x-category": "Forms"})


class FulcrumListRecordsConfig(FulcrumForm, FulcrumPage):
    operation: Literal["list_records"] = Field("list_records", json_schema_extra={"x-display-name": "List Records", "x-category": "Records"})
    project_id: Optional[str] = Field(None, title="Project", json_schema_extra=_selector("project_id"))
    newest_first: bool = True
    updated_since: Optional[int] = Field(None, ge=0, le=253402300799, description="Unix epoch seconds, as documented in Records API.")
    updated_before: Optional[int] = Field(None, ge=0, le=253402300799)
    _validate_project = field_validator("project_id", mode="before")(lambda value: _uuid(value) if value is not None else None)

    @model_validator(mode="after")
    def date_order(self):
        if self.updated_since is not None and self.updated_before is not None and self.updated_since >= self.updated_before:
            raise ValueError("Updated since must precede updated before.")
        return self


class FulcrumGetRecordConfig(FulcrumRecord):
    operation: Literal["get_record"] = Field("get_record", json_schema_extra={"x-display-name": "Get Record", "x-category": "Records"})


class FulcrumRecordControls(FulcrumOperation):
    skip_workflows: bool = Field(True, title="Skip App Workflows",
        description="Send documented X-SkipWorkflows. False permits existing form workflows to run.")
    skip_webhooks: bool = Field(True, title="Skip App Webhooks",
        description="Send documented X-SkipWebhooks. False permits existing form webhooks to run.")


class FulcrumCreateRecordConfig(FulcrumForm, FulcrumRecordControls):
    operation: Literal["create_record"] = Field("create_record", json_schema_extra={"x-display-name": "Create Record", "x-category": "Records"})
    form_values: dict[str, Any] = Field(..., description="Current form field keys and complete documented field values.")
    latitude: float = Field(..., ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(..., ge=-180, le=180, allow_inf_nan=False)
    status: Optional[str] = Field(None, max_length=500)
    project_id: Optional[str] = Field(None, title="Project", json_schema_extra=_selector("project_id"))
    _validate_values = field_validator("form_values")(_bounded_json)
    _validate_project = field_validator("project_id", mode="before")(lambda value: _uuid(value) if value is not None else None)


class FulcrumUpdateRecordConfig(FulcrumRecord, FulcrumRecordControls):
    operation: Literal["update_record"] = Field("update_record", json_schema_extra={"x-display-name": "Update Record", "x-category": "Records"})
    form_values: Optional[dict[str, Any]] = Field(None,
        description="PATCH changes only supplied top-level field keys. Object fields are complete replacements. Repeatables are refused.")
    latitude: Optional[float] = Field(None, ge=-90, le=90, allow_inf_nan=False)
    longitude: Optional[float] = Field(None, ge=-180, le=180, allow_inf_nan=False)
    status: Optional[str] = Field(None, max_length=500)
    project_id: Optional[str] = Field(None, title="Project", json_schema_extra=_selector("project_id"))
    _validate_values = field_validator("form_values")(lambda value: _bounded_json(value) if value is not None else None)
    _validate_project = field_validator("project_id", mode="before")(lambda value: _uuid(value) if value is not None else None)

    @model_validator(mode="after")
    def changes(self):
        changed = self.model_fields_set & {"form_values", "latitude", "longitude", "status", "project_id"}
        if not changed:
            raise ValueError("Supply at least one record change.")
        if bool("latitude" in changed) != bool("longitude" in changed):
            raise ValueError("Supply latitude and longitude together.")
        if self.form_values is None and "form_values" in changed:
            raise ValueError("Clear individual field values with null, not the entire form_values map.")
        return self


class FulcrumSetRecordFieldConfig(FulcrumRecord, FulcrumRecordControls):
    operation: Literal["set_record_field"] = Field("set_record_field", json_schema_extra={"x-display-name": "Set Record Field", "x-category": "Records"})
    field_key: str = Field(..., title="Form Field", json_schema_extra=_selector("field_key", "form_id"))
    value: Any = Field(..., description="Complete field value. Null clears it; a complex value replaces the whole field.")
    _validate_key = field_validator("field_key")(_field_key)
    _validate_value = field_validator("value")(_bounded_json)


class FulcrumDeleteRecordConfig(FulcrumRecord, FulcrumRecordControls):
    operation: Literal["delete_record"] = Field("delete_record", json_schema_extra={"x-display-name": "Delete Record", "x-category": "Records"})


class FulcrumRecordHistoryConfig(FulcrumRecord):
    operation: Literal["get_record_history"] = Field("get_record_history", json_schema_extra={"x-display-name": "Get Record History", "x-category": "Records"})


class FulcrumListProjectsConfig(FulcrumPage):
    operation: Literal["list_projects"] = Field("list_projects", json_schema_extra={"x-display-name": "List Projects", "x-category": "Projects"})


class FulcrumGetProjectConfig(FulcrumProject):
    operation: Literal["get_project"] = Field("get_project", json_schema_extra={"x-display-name": "Get Project", "x-category": "Projects"})


class FulcrumMetadata(FulcrumOperation):
    name: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = Field(None, max_length=10000)

    @field_validator("name")
    @classmethod
    def name_value(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Name cannot be blank.")
        return value


class FulcrumCreateProjectConfig(FulcrumMetadata):
    operation: Literal["create_project"] = Field("create_project", json_schema_extra={"x-display-name": "Create Project", "x-category": "Projects"})
    name: str = Field(..., min_length=1, max_length=500)


class FulcrumUpdateProjectConfig(FulcrumProject, FulcrumMetadata):
    operation: Literal["update_project"] = Field("update_project", json_schema_extra={"x-display-name": "Update Project", "x-category": "Projects"})

    @model_validator(mode="after")
    def changes(self):
        if not (self.model_fields_set & {"name", "description"}):
            raise ValueError("Supply a project metadata change.")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("Project name cannot be cleared.")
        return self


class FulcrumDeleteProjectConfig(FulcrumProject):
    operation: Literal["delete_project"] = Field("delete_project", json_schema_extra={"x-display-name": "Delete Project", "x-category": "Projects"})


class FulcrumListChoicesConfig(FulcrumPage):
    operation: Literal["list_choice_lists"] = Field("list_choice_lists", json_schema_extra={"x-display-name": "List Choice Lists", "x-category": "Choice Lists"})


class FulcrumGetChoicesConfig(FulcrumChoiceList):
    operation: Literal["get_choice_list"] = Field("get_choice_list", json_schema_extra={"x-display-name": "Get Choice List", "x-category": "Choice Lists"})


class FulcrumChoice(BaseModel):
    label: str = Field(..., min_length=1, max_length=1000)
    value: str = Field(..., max_length=1000)
    model_config = ConfigDict(extra="forbid")


class FulcrumCreateChoicesConfig(FulcrumMetadata):
    operation: Literal["create_choice_list"] = Field("create_choice_list", json_schema_extra={"x-display-name": "Create Choice List", "x-category": "Choice Lists"})
    name: str = Field(..., min_length=1, max_length=500)
    choices: list[FulcrumChoice] = Field(..., max_length=1000)


class FulcrumUpdateChoicesConfig(FulcrumChoiceList, FulcrumMetadata):
    operation: Literal["update_choice_list"] = Field("update_choice_list", json_schema_extra={"x-display-name": "Update Choice List", "x-category": "Choice Lists"})
    choices: Optional[list[FulcrumChoice]] = Field(None, max_length=1000, description="Complete replacement choices; empty list clears the list.")

    @model_validator(mode="after")
    def changes(self):
        if not (self.model_fields_set & {"name", "description", "choices"}):
            raise ValueError("Supply a choice-list change.")
        if "name" in self.model_fields_set and self.name is None or "choices" in self.model_fields_set and self.choices is None:
            raise ValueError("Choice-list name and choices cannot be null.")
        return self


class FulcrumDeleteChoicesConfig(FulcrumChoiceList):
    operation: Literal["delete_choice_list"] = Field("delete_choice_list", json_schema_extra={"x-display-name": "Delete Choice List", "x-category": "Choice Lists"})


FulcrumConfig = Annotated[Union[FulcrumListFormsConfig, FulcrumGetFormConfig, FulcrumFormFieldsConfig,
    FulcrumListRecordsConfig, FulcrumGetRecordConfig, FulcrumCreateRecordConfig, FulcrumUpdateRecordConfig,
    FulcrumSetRecordFieldConfig, FulcrumDeleteRecordConfig, FulcrumRecordHistoryConfig, FulcrumListProjectsConfig,
    FulcrumGetProjectConfig, FulcrumCreateProjectConfig, FulcrumUpdateProjectConfig, FulcrumDeleteProjectConfig,
    FulcrumListChoicesConfig, FulcrumGetChoicesConfig, FulcrumCreateChoicesConfig, FulcrumUpdateChoicesConfig,
    FulcrumDeleteChoicesConfig], Field(discriminator="operation")]


class FulcrumNodeConfig(NodeConfig[FulcrumConfig, FulcrumAPITokenCredential]):
    pass


async def _request(data, method, path, *, params=None, body=None, controls=None, statuses=(200,)):
    data = _credential(data)
    if not re.fullmatch(r"/(?:forms|records|projects|choice_lists)(?:/[0-9a-f-]{36})?(?:/history)?\.json", path):
        raise ValueError("Unsupported Fulcrum resource path.")
    headers = {"X-ApiToken": data["api_token"], "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if controls is not None:
        headers.update({"X-SkipWorkflows": str(controls.skip_workflows).lower(),
            "X-SkipWebhooks": str(controls.skip_webhooks).lower()})
    try:
        async with guarded_async_client( timeout=20.0, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, API_ROOT + path, headers=headers, params=params, json=body)
    except Exception:
        raise RuntimeError("Fulcrum request could not complete.") from None
    if response.status_code not in statuses:
        messages = {401: "Fulcrum authentication is unverified; check the organization token.",
            403: "Fulcrum access is unverified; check current permissions and API entitlement.",
            404: "Fulcrum resource is unavailable in the token's organization.",
            422: "Fulcrum rejected the form field values or required properties.",
            429: "Fulcrum rate limit reached; retry later. No request was automatically retried."}
        raise RuntimeError(messages.get(response.status_code, "Fulcrum returned an unexpected status."))
    if response.status_code == 204 or not response.content:
        return {}, response.status_code
    if len(response.content) > 2000000:
        raise RuntimeError("Fulcrum metadata response exceeded the size limit.")
    try:
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError()
    except Exception:
        raise RuntimeError("Fulcrum returned malformed resource JSON.") from None
    if payload.get("success") is False or payload.get("status") == "error" or any(
            key in payload and payload[key] not in (None, "", [], {}) for key in ("error", "errors")):
        raise RuntimeError("Fulcrum returned an error envelope; resource access is unverified.")
    return payload, response.status_code


def _project(item, kind, form_id=None):
    if not isinstance(item, dict):
        raise RuntimeError("Fulcrum returned malformed resource metadata.")
    fields = {
        "form": ("id", "name", "description", "version", "record_count", "created_at", "updated_at", "status"),
        "record": ("id", "form_id", "project_id", "version", "latitude", "longitude", "status", "form_values", "created_at", "updated_at", "client_created_at", "client_updated_at"),
        "project": ("id", "name", "description", "status", "customer", "external_job_id", "start_date", "end_date", "record_count", "form_count", "created_at", "updated_at"),
        "choice_list": ("id", "name", "description", "version", "choices", "created_at", "updated_at"),
    }[kind]
    out = {key: item[key] for key in fields if key in item}
    out["id"] = _uuid(item.get("id"))
    for key in ("name", "description", "status", "customer", "external_job_id", "start_date", "end_date", "created_at", "updated_at", "client_created_at", "client_updated_at"):
        if key in out and out[key] is not None and not isinstance(out[key], str):
            raise RuntimeError("Fulcrum returned invalid scalar metadata.")
    for key in ("version", "record_count", "form_count"):
        if key in out and out[key] is not None and (type(out[key]) is not int or out[key] < 0):
            raise RuntimeError("Fulcrum returned invalid numeric metadata.")
    if kind == "record":
        out["form_id"] = _uuid(item.get("form_id"))
        if form_id is not None and out["form_id"] != form_id:
            raise RuntimeError("Fulcrum returned a record from another form.")
        if out.get("project_id") is not None:
            out["project_id"] = _uuid(out["project_id"])
        if "form_values" in out and not isinstance(out["form_values"], dict):
            raise RuntimeError("Fulcrum returned an invalid field value map.")
        for key, limit in (("latitude", 90), ("longitude", 180)):
            if key in out and out[key] is not None and (type(out[key]) not in (int, float)
                    or not math.isfinite(out[key]) or abs(out[key]) > limit):
                raise RuntimeError("Fulcrum returned invalid record coordinates.")
    if kind == "choice_list" and "choices" in out and not isinstance(out["choices"], list):
        raise RuntimeError("Fulcrum returned invalid choice-list metadata.")
    _bounded_json(out)
    return out


async def _one(data, kind, identity, *, form_id=None, full=False):
    plural = "choice_lists" if kind == "choice_list" else kind + "s"
    payload, _ = await _request(data, "GET", "/" + plural + "/" + identity + ".json",
        params={"schema": "true"} if kind == "form" else None)
    raw = payload.get(kind)
    item = _project(raw, kind, form_id)
    if item["id"] != identity:
        raise RuntimeError("Fulcrum returned an unexpected resource ID.")
    return raw if full else item


def _form_fields(form):
    rows, seen = [], set()
    def walk(elements, section=(), depth=0):
        if not isinstance(elements, list) or len(elements) > 1000 or depth > 10:
            raise RuntimeError("Fulcrum form schema exceeds the field limit.")
        for element in elements:
            if not isinstance(element, dict):
                raise RuntimeError("Fulcrum returned malformed field metadata.")
            if element.get("type") == "Section":
                walk(element.get("elements"), section + (str(element.get("label", "")),), depth + 1)
                continue
            key = _field_key(element.get("key"))
            if key in seen or len(rows) >= 1000:
                raise RuntimeError("Fulcrum returned duplicate or excessive field keys.")
            seen.add(key)
            row = {name: element[name] for name in ("key", "label", "type", "description", "required", "read_only", "hidden", "numeric", "choice_list_id") if name in element}
            row["section"] = list(section)
            row["repeatable"] = isinstance(element.get("elements"), list)
            rows.append(row)
    walk(form.get("elements"))
    _bounded_json(rows)
    return rows


def _validate_values(values, form, *, partial=False):
    fields = {row["key"]: row for row in _form_fields(form)}
    for key in values:
        _field_key(key)
        field = fields.get(key)
        if field is None:
            raise ValueError("A field key does not belong to the selected current form.")
        if field.get("read_only") or field.get("type") == "CalculatedField":
            raise ValueError("Read-only or calculated form fields cannot be written.")
        if partial and field["repeatable"]:
            raise ValueError("PATCH cannot safely update repeatable child records; use a complete record workflow.")
    return _bounded_json(values)


def _cursor(data, path, params, search, *, token=None, page=None):
    anchor = {"v": 1, "path": path, "parameters": params, "search": search}
    key = hashlib.sha256(data["api_token"].encode()).digest()
    if token is not None:
        try:
            if not isinstance(token, str) or len(token) > 4096:
                raise ValueError()
            encoded, signature = token.split(".")
            expected = hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, signature):
                raise ValueError()
            payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
            current = payload.pop("page")
            if payload != anchor or type(current) is not int or not 1 <= current <= 100000:
                raise ValueError()
            return current
        except Exception:
            raise ValueError("Fulcrum page token does not match this connection, form and search.") from None
    encoded = base64.urlsafe_b64encode(json.dumps({**anchor, "page": page}, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")
    return encoded + "." + hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest()


async def _page(data, collection, config, *, parameters=None, search=None, title_keys=()):
    params = {"per_page": config.per_page, **(parameters or {})}
    path = "/" + collection + ".json"
    current = _cursor(data, path, params, search, token=config.page_token) if config.page_token else config.page
    payload, _ = await _request(data, "GET", path, params={**params, "page": current})
    rows = payload.get(collection)
    if not isinstance(rows, list) or len(rows) > config.per_page:
        raise RuntimeError("Fulcrum returned an invalid bounded resource page.")
    if "current_page" in payload and (type(payload["current_page"]) is not int or payload["current_page"] != current):
        raise RuntimeError("Fulcrum returned a mismatched page.")
    reported_pages, total = payload.get("total_pages"), payload.get("total_count")
    if reported_pages is not None and (type(reported_pages) is not int or not 0 <= reported_pages <= 100000):
        raise RuntimeError("Fulcrum returned invalid pagination metadata.")
    if total is not None and (type(total) is not int or not 0 <= total <= 10000000):
        raise RuntimeError("Fulcrum returned an invalid resource count.")
    more = current < reported_pages if reported_pages is not None else len(rows) == config.per_page
    kind = "choice_list" if collection == "choice_lists" else collection.removesuffix("s")
    items = [_project(row, kind, params.get("form_id")) for row in rows]
    if kind == "record" and title_keys:
        for item in items:
            values = item.get("form_values", {})
            title = " · ".join(str(values[key]) for key in title_keys[:10]
                if key in values and type(values[key]) in (str, int, float, bool))[:500]
            item["label"] = title or item["id"]
    if search:
        items = [item for item in items if search.casefold() in str(item.get("name") or item.get("label") or item.get("id")).casefold()]
    return {"items": items, "page": current, "per_page": config.per_page, "total_count": total,
        "next_page_token": _cursor(data, path, params, search, page=current + 1) if more and current < 100000 else None,
        "snapshot": False}


class FulcrumNode(WorkflowNode):
    integration_type = "automation-fulcrum"
    workflow_credential_refresh = True
    connection_evidence = ConnectionEvidence(operation="list_forms", operation_arguments={"per_page": 5},
        noun="forms", label_keys=("name",), identity_keys=(), proves="account")

    @classmethod
    def get_config_model(cls):
        return FulcrumNodeConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # Staging loads saved credentials before this hook. Organization API
        # tokens do not expire automatically and have no OAuth refresh flow.
        return _credential(credential_data)

    @classmethod
    async def validate_credential_access(cls, credential_data, **kwargs):
        data = _credential(credential_data)
        await _page(data, "forms", FulcrumListFormsConfig(per_page=1),
            parameters={"schema": "false", "type": "organization", "status": "active"})
        return {"valid": True}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        data = _credential(credential_data)
        search = search.strip() if isinstance(search, str) and search.strip() else None
        if search and len(search) > 200:
            raise ValueError("Fulcrum selector search exceeds the limit.")
        config = FulcrumPage(per_page=50, page_token=page_token)
        if field_name in {"record_id", "field_key"}:
            if field_name == "field_key" and page_token:
                raise ValueError("Form fields are a bounded single-page selector.")
            form_id = _uuid((context or {}).get("form_id"))
            form = await _one(data, "form", form_id, full=True)
            if field_name == "field_key":
                rows = [row for row in _form_fields(form) if not row.get("read_only") and row.get("type") != "CalculatedField" and not row["repeatable"]]
                if search:
                    rows = [row for row in rows if search.casefold() in (str(row.get("label")) + " " + row["key"]).casefold()]
                return {"options": [{"value": row["key"], "label": row.get("label") or row["key"]} for row in rows], "next_page_token": None}
            keys = form.get("title_field_keys", [])
            if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
                raise RuntimeError("Fulcrum returned invalid form title metadata.")
            result = await _page(data, "records", config, parameters={"form_id": form_id, "newest_first": "true"}, search=search, title_keys=keys)
        elif field_name in {"form_id", "project_id", "choice_list_id"}:
            collection = {"form_id": "forms", "project_id": "projects", "choice_list_id": "choice_lists"}[field_name]
            result = await _page(data, collection, config,
                parameters={"schema": "false", "type": "organization", "status": "active"} if collection == "forms" else None, search=search)
        else:
            raise ValueError("Unsupported Fulcrum selector.")
        return {"options": [{"value": row["id"], "label": row.get("name") or row.get("label") or row["id"]} for row in result["items"]],
            "next_page_token": result["next_page_token"]}

    async def execute(self, inputs):
        if not isinstance(self.config, FulcrumNodeConfig) or not self.config.credentials:
            raise ValueError("Fulcrum configuration and a connection are required.")
        c = self.config.config
        raw = self.config.credentials.model_dump(mode="json")
        credential_id = (self.node_data or {}).get("credential_id")
        if credential_id:
            from utils.credentials import resolve_credential_with_owner_fallback
            from utils.database_pool import get_native_pool
            raw = await resolve_credential_with_owner_fallback(
                credential_id=credential_id, user_id=self.user_id,
                pool=getattr(self, "_approval_pool", None) or get_native_pool(),
                org_id=getattr(self, "organization_id", None), workflow_id=self.workflow_id)
            if raw is None:
                raise ValueError("Fulcrum saved connection is unavailable.")
        data = await self.freshen_credential(raw)
        op = c.operation
        if op in {"list_forms", "list_projects", "list_choice_lists"}:
            collection = op.removeprefix("list_")
            return await _page(data, collection, c, parameters={"schema": "false", "type": "organization", "status": c.status} if collection == "forms" else None)
        if op in {"get_form", "get_form_fields"}:
            form = await _one(data, "form", c.form_id, full=True)
            return {"form": _project(form, "form")} if op == "get_form" else {"form_id": c.form_id, "fields": _form_fields(form)}
        if op == "list_records":
            await _one(data, "form", c.form_id)
            params = c.model_dump(exclude={"operation", "per_page", "page", "page_token"}, exclude_none=True)
            params["newest_first"] = str(c.newest_first).lower()
            if c.project_id:
                await _one(data, "project", c.project_id)
            return await _page(data, "records", c, parameters=params)
        if op in {"get_record", "get_record_history", "create_record", "update_record", "set_record_field", "delete_record"}:
            form = await _one(data, "form", c.form_id, full=True)
            if op != "create_record":
                existing = await _one(data, "record", c.record_id, form_id=c.form_id)
            if op == "get_record":
                return {"record": existing}
            if op == "get_record_history":
                payload, _ = await _request(data, "GET", "/records/" + c.record_id + "/history.json")
                rows = payload.get("records")
                if not isinstance(rows, list) or len(rows) > 1000:
                    raise RuntimeError("Fulcrum record history exceeded its bounded version limit.")
                projected = [_project(row, "record", c.form_id) for row in rows]
                if any(row["id"] != c.record_id for row in projected):
                    raise RuntimeError("Fulcrum returned history for another record.")
                for raw, item in zip(rows, projected):
                    for key in ("history_id", "history_change_type", "history_created_at"):
                        if key in raw:
                            if not isinstance(raw[key], str) or len(raw[key]) > 500:
                                raise RuntimeError("Fulcrum returned invalid history metadata.")
                            item[key] = raw[key]
                return {"records": projected, "complete": None}
            if op == "delete_record":
                payload, status = await _request(data, "DELETE", "/records/" + c.record_id + ".json", controls=c)
                deleted = _project(payload["record"], "record", c.form_id) if "record" in payload else None
                if deleted is not None and deleted["id"] != c.record_id:
                    raise RuntimeError("Fulcrum returned an unexpected deleted record.")
                return {"deleted": True, "record_id": c.record_id, "http_status": status}
            if op == "set_record_field":
                values = _validate_values({c.field_key: c.value}, form, partial=True)
                body = {"form_values": values}
            else:
                body = c.model_dump(exclude={"operation", "record_id", "skip_workflows", "skip_webhooks"}, exclude_unset=True)
                if op == "update_record":
                    body.pop("form_id", None)
                if "form_values" in body:
                    _validate_values(body["form_values"], form, partial=op == "update_record")
                if body.get("project_id"):
                    await _one(data, "project", body["project_id"])
            path = "/records.json" if op == "create_record" else "/records/" + c.record_id + ".json"
            payload, status = await _request(data, "POST" if op == "create_record" else "PATCH", path, body={"record": body}, controls=c)
            record = _project(payload.get("record"), "record", c.form_id)
            if op != "create_record" and record["id"] != c.record_id:
                raise RuntimeError("Fulcrum returned an unexpected updated record.")
            return {"record": record, "http_status": status}
        kind = "choice_list" if "choice_list" in op else "project"
        identity = getattr(c, kind + "_id", None)
        if op == "get_" + kind:
            return {kind: await _one(data, kind, identity)}
        plural = "choice_lists" if kind == "choice_list" else "projects"
        if op.startswith("delete_"):
            await _one(data, kind, identity)
            _, status = await _request(data, "DELETE", "/" + plural + "/" + identity + ".json",
                statuses=(200, 204) if kind == "project" else (200,))
            return {"deleted": True, kind + "_id": identity, "http_status": status}
        if op.startswith("update_"):
            # PUT endpoints require complete writable metadata; merge only the
            # supported writable properties from the current resource.
            current = await _one(data, kind, identity, full=True)
            fields = ("name", "description", "choices") if kind == "choice_list" else (
                "name", "description", "status", "customer", "external_job_id", "start_date", "end_date", "project_manager_id")
            body = {key: current[key] for key in fields if key in current}
            body.update(c.model_dump(exclude={"operation", kind + "_id"}, exclude_unset=True))
            _bounded_json(body)
            if "name" not in body or kind == "choice_list" and "choices" not in body:
                raise RuntimeError("Fulcrum current writable metadata is incomplete.")
            _, status = await _request(data, "PUT", "/" + plural + "/" + identity + ".json", body={kind: body})
            readback = await _one(data, kind, identity, full=True)
            if any(readback.get(key) != value for key, value in body.items()):
                raise RuntimeError("Fulcrum metadata update could not be confirmed by the current readback.")
            return {kind: _project(readback, kind), "http_status": status}
        body = c.model_dump(exclude={"operation"}, exclude_none=True)
        payload, status = await _request(data, "POST", "/" + plural + ".json", body={kind: body}, statuses=(200, 201))
        if payload and kind not in payload:
            raise RuntimeError("Fulcrum create response has an unexpected resource envelope.")
        item = _project(payload[kind], kind) if kind in payload else None
        return {"created": True, kind: item, "http_status": status}
