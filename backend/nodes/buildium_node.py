"""Buildium v1 metadata and bounded internal note/category maintenance."""
import base64
import httpx
from contextvars import ContextVar
from datetime import date
import hashlib
import json
import logging
import re
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Discriminator, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import normalize_search, filter_options_by_search
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from utils.ssrf import assert_exact_url_origin

ORIGIN = "https://api.buildium.com"
FAMILY = "buildium_api_key"
NODE_TYPE = "automation-buildium"
MAX_BYTES = 2 * 1024 * 1024
OPS = ("check_connection", "list_properties", "get_property", "list_units", "get_unit", "list_tenants", "get_tenant", "list_listing_contacts", "get_listing_contact", "list_work_orders", "get_work_order", "list_tasks", "get_task", "list_task_categories", "get_task_category", "list_property_notes", "get_property_note", "create_property_note", "update_property_note", "create_task_category", "rename_task_category")
_ORG_OMITTED = object()
_PRIVATE = ContextVar("buildium_private_transport", default=False)


def identifier(value):
    if type(value) is int and 0 < value <= 2147483647:
        return str(value)
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,9}", value) and int(value) <= 2147483647:
        return value
    raise ValueError("Use a positive Buildium Int32 ID")


def plain_text(value, limit=200, *, empty=False, multiline=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()) or any(ord(c) < 32 and not (multiline and c in "\n\r\t") for c in value):
        raise ValueError("Use bounded plain text without unsupported control characters")
    return value


def clean_key(value):
    if not isinstance(value, str):
        raise ValueError("Use genuine string Buildium API credentials")
    value = clean_secret(value, field_name="Buildium API credential")
    if len(value) > 4096 or not re.fullmatch(r"[!-~]+", value):
        raise ValueError("Use genuine Buildium API credentials without whitespace")
    return value


class BuildiumAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Buildium API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developer.buildium.com/#section/Getting-Started/API-Keys",
        "x-credential-instructions": "Supply the client ID and secret of an existing account-level Buildium Open API key. The official API requires Premium and administrator API setup; your account's entitlement and current key permissions must be confirmed separately. This node does not enable the API, change permissions or rotate keys.",
    })
    credential_type: Literal["buildium_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., title="API Client ID", json_schema_extra={"ui:widget": "password", "ui:sensitive": True})
    client_secret: str = Field(..., title="API Client Secret", json_schema_extra={"ui:widget": "password", "ui:sensitive": True})
    _keys = field_validator("client_id", "client_secret", mode="before")(clean_key)


def credential(data):
    try:
        if not isinstance(data, dict) or data.get("credential_type") != FAMILY:
            raise ValueError()
        if any(data.get(k) not in (None, "") for k in ("api_key", "token", "access_token", "refresh_token", "password", "username", "base_url")):
            raise ValueError()
        return BuildiumAPIKeyCredential.model_validate(data).model_dump()
    except Exception:
        raise ValueError("Buildium requires its native account API client-ID/secret credential") from None


def resource(kind, parent=None):
    dynamic = {"field_name": kind+"_id", "searchable": True, "allow_custom": True}
    if parent:
        dynamic["depends_on"] = parent
    return {"x-resource-type": "buildium_"+kind, "x-dynamic-options": dynamic}


class _Operation(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    @field_validator("property_id", "unit_id", "tenant_id", "listing_contact_id", "work_order_id", "task_id", "task_category_id", "note_id", mode="before", check_fields=False)
    @classmethod
    def ids(cls, value):
        return None if value is None else identifier(value)


class _Page(_Operation):
    offset: int = Field(0, strict=True, ge=0, le=2147483647, title="Offset")
    limit: int = Field(50, strict=True, ge=1, le=1000, title="Results per Page")


class CheckConnection(_Operation):
    operation: Literal["check_connection"] = Field("check_connection", title="Check Property API Access")


class ListProperties(_Page):
    operation: Literal["list_properties"] = Field("list_properties", title="List Rental Property Metadata")
    status: Optional[Literal["Active", "InActive"]] = Field(None, title="Property Status")


class GetProperty(_Operation):
    operation: Literal["get_property"] = Field("get_property", title="Get Rental Property Metadata")
    property_id: str = Field(..., title="Rental Property", json_schema_extra=resource("property"))


class ListUnits(_Page):
    operation: Literal["list_units"] = Field("list_units", title="List Units in Rental Property")
    property_id: str = Field(..., title="Rental Property", json_schema_extra=resource("property"))


class GetUnit(GetProperty):
    operation: Literal["get_unit"] = Field("get_unit", title="Get Unit Metadata")
    unit_id: str = Field(..., title="Unit", json_schema_extra=resource("unit", "property_id"))


class ListTenants(_Page):
    operation: Literal["list_tenants"] = Field("list_tenants", title="List Tenant Metadata")


class GetTenant(_Operation):
    operation: Literal["get_tenant"] = Field("get_tenant", title="Get Tenant Metadata")
    tenant_id: str = Field(..., title="Tenant", json_schema_extra=resource("tenant"))


class ListListingContacts(_Page):
    operation: Literal["list_listing_contacts"] = Field("list_listing_contacts", title="List Listing Contact Metadata")


class GetListingContact(_Operation):
    operation: Literal["get_listing_contact"] = Field("get_listing_contact", title="Get Listing Contact Metadata")
    listing_contact_id: str = Field(..., title="Listing Contact", json_schema_extra=resource("listing_contact"))


class ListWorkOrders(_Page):
    operation: Literal["list_work_orders"] = Field("list_work_orders", title="List Work Order Metadata")


class GetWorkOrder(_Operation):
    operation: Literal["get_work_order"] = Field("get_work_order", title="Get Work Order Metadata")
    work_order_id: str = Field(..., title="Work Order", json_schema_extra=resource("work_order"))


class ListTasks(_Page):
    operation: Literal["list_tasks"] = Field("list_tasks", title="List Task Metadata")
    title: str = Field("", max_length=200, title="Task Title Contains")
    updated_from: Optional[str] = Field(None, title="Updated From", json_schema_extra={"ui:widget": "date"})
    updated_to: Optional[str] = Field(None, title="Updated To", json_schema_extra={"ui:widget": "date"})
    _title = field_validator("title", mode="before")(lambda v: plain_text(v, empty=True))
    @field_validator("updated_from", "updated_to", mode="before")
    @classmethod
    def dates(cls, value):
        if value is None:
            return None
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Use a YYYY-MM-DD date")
        date.fromisoformat(value)
        return value
    @model_validator(mode="after")
    def ordered_dates(self):
        if self.updated_from and self.updated_to and self.updated_from > self.updated_to:
            raise ValueError("Updated From must not be after Updated To")
        return self


class GetTask(_Operation):
    operation: Literal["get_task"] = Field("get_task", title="Get Task Metadata")
    task_id: str = Field(..., title="Task", json_schema_extra=resource("task"))


class ListTaskCategories(_Page):
    operation: Literal["list_task_categories"] = Field("list_task_categories", title="List Task Categories")


class GetTaskCategory(_Operation):
    operation: Literal["get_task_category"] = Field("get_task_category", title="Get Task Category")
    task_category_id: str = Field(..., title="Task Category", json_schema_extra=resource("task_category"))


class ListPropertyNotes(_Page):
    operation: Literal["list_property_notes"] = Field("list_property_notes", title="List Property Note Metadata")
    property_id: str = Field(..., title="Rental Property", json_schema_extra=resource("property"))


class GetPropertyNote(GetProperty):
    operation: Literal["get_property_note"] = Field("get_property_note", title="Get Property Note Metadata")
    note_id: str = Field(..., title="Property Note", json_schema_extra=resource("note", "property_id"))


class CreatePropertyNote(GetProperty):
    operation: Literal["create_property_note"] = Field("create_property_note", title="Create Property Note", description="Writes an internal property note. Account automations and staff may observe this change.")
    note: str = Field(..., min_length=1, max_length=65535, title="Note", json_schema_extra={"ui:widget": "textarea", "ui:sensitive": True})
    _note = field_validator("note", mode="before")(lambda v: plain_text(v, 65535, multiline=True))


class UpdatePropertyNote(GetPropertyNote):
    operation: Literal["update_property_note"] = Field("update_property_note", title="Replace Property Note", description="Replaces the complete note contents; inspect the existing note before choosing this change.")
    note: str = Field(..., min_length=1, max_length=65535, title="Replacement Note", json_schema_extra={"ui:widget": "textarea", "ui:sensitive": True})
    _note = field_validator("note", mode="before")(lambda v: plain_text(v, 65535, multiline=True))


class CreateTaskCategory(_Operation):
    operation: Literal["create_task_category"] = Field("create_task_category", title="Create Task Category")
    name: str = Field(..., min_length=1, max_length=200, title="Category Name")
    _name = field_validator("name", mode="before")(plain_text)


class RenameTaskCategory(GetTaskCategory):
    operation: Literal["rename_task_category"] = Field("rename_task_category", title="Rename Custom Task Category", description="Changes the name used on tasks. System categories are refused.")
    name: str = Field(..., min_length=1, max_length=200, title="New Category Name")
    _name = field_validator("name", mode="before")(plain_text)


BuildiumOperation = Annotated[Union[CheckConnection, ListProperties, GetProperty, ListUnits, GetUnit, ListTenants, GetTenant, ListListingContacts, GetListingContact, ListWorkOrders, GetWorkOrder, ListTasks, GetTask, ListTaskCategories, GetTaskCategory, ListPropertyNotes, GetPropertyNote, CreatePropertyNote, UpdatePropertyNote, CreateTaskCategory, RenameTaskCategory], Discriminator("operation")]


class BuildiumNodeConfig(NodeConfig[BuildiumOperation, BuildiumAPIKeyCredential]):
    pass


async def current_credential(data):
    return credential(data)


class _Privacy(logging.Filter):
    def filter(self, record):
        if _PRIVATE.get() and (record.name in {"httpx", "httpcore"} or record.name.startswith(("httpx.", "httpcore."))):
            record.msg, record.args = "Buildium private transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_FILTER = _Privacy()
def _install_privacy():
    names = {"httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"}
    names.update(n for n in logging.Logger.manager.loggerDict if n.startswith(("httpx.", "httpcore.")))
    for name in names:
        logging.getLogger(name).addFilter(_FILTER)
    for handler in logging.getLogger().handlers:
        handler.addFilter(_FILTER)


class BuildiumHTTPError(RuntimeError):
    def __init__(self, status):
        self.status_code = status
        super().__init__(f"Buildium request did not complete (HTTP {status}); inspect changes before retrying")


def _json(content):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError()
            out[key] = value
        return out
    try:
        return json.loads(content, object_pairs_hook=pairs, parse_constant=lambda _v: (_ for _ in ()).throw(ValueError()))
    except Exception:
        raise RuntimeError("Buildium returned invalid JSON") from None


async def request(data, method, path, *, params=None, body=None, status=200):
    shaped = await current_credential(data)
    if not re.fullmatch(r"/v1/(rentals(?:/units(?:/listingcontacts)?)?|leases/tenants|workorders|tasks(?:/categories)?)(/[1-9][0-9]*)?(?:/notes(?:/[1-9][0-9]*)?)?", path):
        raise ValueError("Unsupported native Buildium route")
    async def exact(req):
        assert_exact_url_origin(str(req.url), ORIGIN)
        if req.url.path != path:
            raise ValueError("Buildium transport route changed")
    content, headers = bytearray(), {}
    marker = _PRIVATE.set(True)
    _install_privacy()
    try:
        async with httpx.AsyncClient(timeout=20, trust_env=False, follow_redirects=False, event_hooks={"request": [exact]}) as client:
            async with client.stream(method, ORIGIN+path, params=params, json=body, headers={"Accept": "application/json", "x-buildium-client-id": shaped["client_id"], "x-buildium-client-secret": shaped["client_secret"]}) as response:
                if response.status_code != status:
                    raise BuildiumHTTPError(response.status_code)
                headers = dict(response.headers)
                async for part in response.aiter_bytes():
                    content.extend(part)
                    if len(content) > MAX_BYTES:
                        raise RuntimeError("Buildium response exceeded its local byte bound")
    except BuildiumHTTPError:
        raise
    except Exception:
        raise RuntimeError("Buildium transport did not complete; inspect changes before retrying") from None
    finally:
        _PRIVATE.reset(marker)
    await current_credential(data)
    return _json(content), headers


SAFE_FIELDS = {
    "property": ("Name", "NumberUnits", "IsActive", "YearBuilt", "RentalType", "RentalSubType"),
    "unit": ("PropertyId", "BuildingName", "UnitNumber", "UnitBedrooms", "UnitBathrooms", "UnitSize", "IsUnitListed", "IsUnitOccupied"),
    "tenant": ("FirstName", "LastName", "CreatedDateTime"),
    "listing_contact": ("Name",),
    "work_order": ("Title", "DueDate", "Priority", "Status"),
    "task": ("Title", "TaskType", "TaskStatus", "Priority", "DueDate", "CreatedDateTime", "LastUpdatedDateTime", "UnitId"),
    "task_category": ("Name", "IsSystemCategory"),
    "note": (),
}


def project(raw, kind):
    if not isinstance(raw, dict):
        raise RuntimeError("Buildium returned an invalid metadata record")
    try:
        out = {"id": identifier(raw.get("Id"))}
        for key in SAFE_FIELDS[kind]:
            value = raw.get(key)
            if value is None:
                continue
            if key.endswith("Id"):
                value = identifier(value)
            elif not isinstance(value, (str, int, bool)) or isinstance(value, str) and len(value) > 65535:
                raise ValueError()
            out[key] = value
        if kind == "task" and raw.get("Property") is not None:
            p = raw["Property"]
            if not isinstance(p, dict) or p.get("Type") not in {"Rental", "Association"}:
                raise ValueError()
            out["property_id"], out["property_type"] = identifier(p.get("Id")), p["Type"]
        if kind == "work_order" and raw.get("Task") is not None:
            out["task_id"] = identifier(raw["Task"].get("Id"))
        if kind == "note" and raw.get("LastUpdatedByUser") is not None:
            user = raw["LastUpdatedByUser"]
            out["updated_by_user_id"] = identifier(user.get("Id"))
            if user.get("UpdatedDateTime") is not None:
                out["updated_at"] = plain_text(user["UpdatedDateTime"], 100)
        if kind == "task_category" and raw.get("SubCategories") is not None:
            if not isinstance(raw["SubCategories"], list) or len(raw["SubCategories"]) > 1000:
                raise ValueError()
            out["subcategory_count"] = len(raw["SubCategories"])
        return out
    except Exception:
        raise RuntimeError("Buildium returned invalid metadata fields") from None


PATHS = {"property": "/v1/rentals", "unit": "/v1/rentals/units", "tenant": "/v1/leases/tenants", "listing_contact": "/v1/rentals/units/listingcontacts", "work_order": "/v1/workorders", "task": "/v1/tasks", "task_category": "/v1/tasks/categories"}


async def get_raw(data, kind, rid, property_id=None):
    path = f"/v1/rentals/{property_id}/notes" if kind == "note" else PATHS[kind]
    raw, _ = await request(data, "GET", path+"/"+rid)
    if project(raw, kind)["id"] != rid:
        raise RuntimeError("Buildium record did not witness the selected ID")
    return raw


def paginated(raw, headers, kind, offset, limit):
    total = headers.get("x-total-count")
    if not isinstance(raw, list) or len(raw) > limit or not isinstance(total, str) or not re.fullmatch(r"0|[1-9][0-9]{0,9}", total):
        raise RuntimeError("Buildium returned an invalid paginated collection")
    total = int(total)
    if total > 2147483647 or (raw and offset+len(raw) > total) or (not raw and offset < total):
        raise RuntimeError("Buildium pagination count did not match the current page")
    rows = [project(row, kind) for row in raw]
    if len({r["id"] for r in rows}) != len(rows):
        raise RuntimeError("Buildium returned duplicate record IDs")
    return {"records": rows, "total_count": total, "offset": offset, "next_offset": offset+len(raw) if raw and offset+len(raw) < total else None}


async def records(data, cfg):
    op = cfg["operation"]
    if op not in OPS:
        raise ValueError("Unsupported Buildium operation")
    if op == "check_connection":
        raw, headers = await request(data, "GET", PATHS["property"], params={"offset": 0, "limit": 1})
        paginated(raw, headers, "property", 0, 1)
        return {"reachable": True, "proves": "reachability", "identity_verified": False}
    list_kinds = {"list_properties": "property", "list_units": "unit", "list_tenants": "tenant", "list_listing_contacts": "listing_contact", "list_work_orders": "work_order", "list_tasks": "task", "list_task_categories": "task_category", "list_property_notes": "note"}
    get_kinds = {"get_property": "property", "get_unit": "unit", "get_tenant": "tenant", "get_listing_contact": "listing_contact", "get_work_order": "work_order", "get_task": "task", "get_task_category": "task_category", "get_property_note": "note"}
    parent = cfg.get("property_id")
    if op in {"list_units", "get_unit", "list_property_notes", "get_property_note", "create_property_note", "update_property_note"}:
        await get_raw(data, "property", parent)
    if op in list_kinds:
        kind = list_kinds[op]
        params = {"offset": cfg["offset"], "limit": cfg["limit"]}
        path = PATHS.get(kind, f"/v1/rentals/{parent}/notes")
        if kind == "unit":
            params["propertyids"] = [int(parent)]
        if op == "list_properties" and cfg.get("status"):
            params["status"] = cfg["status"]
        if op == "list_tasks":
            for source, target in (("title", "tasktitle"), ("updated_from", "lastupdatedfrom"), ("updated_to", "lastupdatedto")):
                if cfg.get(source):
                    params[target] = cfg[source]
        raw, headers = await request(data, "GET", path, params=params)
        output = paginated(raw, headers, kind, cfg["offset"], cfg["limit"])
        if kind == "unit" and any(row.get("PropertyId") != parent for row in output["records"]):
            raise RuntimeError("Buildium unit belongs to another rental property")
        if kind == "note":
            output["property_id"] = parent
        return output
    if op in get_kinds:
        kind = get_kinds[op]
        row = project(await get_raw(data, kind, cfg[kind+"_id"], parent), kind)
        if kind == "unit" and row.get("PropertyId") != parent:
            raise RuntimeError("Buildium unit belongs to another rental property")
        if kind == "note":
            row["property_id"] = parent
        return {"record": row}
    note_op = op in {"create_property_note", "update_property_note"}
    kind = "note" if note_op else "task_category"
    create = op in {"create_property_note", "create_task_category"}
    path = f"/v1/rentals/{parent}/notes" if note_op else PATHS[kind]
    rid = None if create else cfg[kind+"_id"]
    if not create:
        before = await get_raw(data, kind, rid, parent)
        if kind == "task_category" and before.get("IsSystemCategory") is not False:
            raise ValueError("Buildium system or unclassified task categories cannot be renamed")
    key, wanted = ("Note", cfg["note"]) if note_op else ("Name", cfg["name"])
    # These documented PUT schemas contain only the complete Note or Name field.
    raw, _ = await request(data, "POST" if create else "PUT", path if create else path+"/"+rid, body={key: wanted}, status=201 if create else 200)
    wrote = project(raw, kind)
    if not create and wrote["id"] != rid:
        raise RuntimeError("Buildium update did not witness the selected ID; inspect before retrying")
    rid = wrote["id"]
    after = await get_raw(data, kind, rid, parent)
    if after.get(key) != wanted:
        raise RuntimeError("Buildium maintenance readback did not match; inspect before retrying")
    out = project(after, kind)
    if note_op:
        out["property_id"] = parent
    return {"record": out, "readback_verified": True}


class BuildiumNode(WorkflowNode):
    integration_type = "automation-buildium"
    scope_registry = ScopeRegistry(provider="buildium", enforcement=Enforcement.STRICT, requirements={op: ScopeRequirement(scopes=(), credential_types=(FAMILY,)) for op in OPS})
    connection_evidence = ConnectionEvidence(field="property_id", noun="rental properties", operation="check_connection")
    edit_examples = ["List rental properties and their units", "Read task and work order metadata", "Add an internal property note", "Rename a custom task category"]
    @classmethod
    def get_config_model(cls):
        return BuildiumNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None:
            credential(config_data["credentials"])
        return super().parse_config(config_data)
    @classmethod
    def validate_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try:
                credential(config_data["credentials"])
            except ValueError:
                return {"valid": False, "errors": ["Connect a native Buildium account API key"], "satisfied_set": None}
        return super().validate_config(config_data)
    @classmethod
    async def validate_credential_access(cls, credential_data, **kwargs):
        try:
            result = await records(credential(credential_data), {"operation": "check_connection"})
            return {"valid": result["reachable"], "proves": "reachability", "identity_verified": False}
        except (ValueError, RuntimeError):
            return {"valid": False, "error": "Buildium property API access could not be verified"}
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        fields = {"property_id": "list_properties", "unit_id": "list_units", "tenant_id": "list_tenants", "listing_contact_id": "list_listing_contacts", "work_order_id": "list_work_orders", "task_id": "list_tasks", "task_category_id": "list_task_categories", "note_id": "list_property_notes"}
        if field_name not in fields:
            raise ValueError("Unsupported Buildium picker")
        parent = identifier((context or {}).get("property_id")) if field_name in {"unit_id", "note_id"} else None
        search = normalize_search(search) or ""
        plain_text(search, empty=True)
        current = await current_credential(credential_data)
        scope = hashlib.sha256(json.dumps({"credential": current, "field": field_name, "parent": parent, "search": search}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        offset = 0
        if page_token is not None:
            try:
                if not isinstance(page_token, str) or len(page_token) > 512:
                    raise ValueError()
                cursor = _json(base64.urlsafe_b64decode(page_token+"="*((-len(page_token))%4)))
                if set(cursor) != {"scope", "offset"} or cursor["scope"] != scope or type(cursor["offset"]) is not int or not 0 < cursor["offset"] <= 2147483647:
                    raise ValueError()
                offset = cursor["offset"]
            except Exception:
                raise ValueError("Buildium picker cursor does not match current key, field, parent and search") from None
        args = {"operation": fields[field_name], "offset": offset, "limit": 50}
        if parent:
            args["property_id"] = parent
        if field_name == "task_id":
            args["title"] = search
        result = await records(credential_data, args)
        options = []
        for row in result["records"]:
            label = row.get("Name") or row.get("UnitNumber") or row.get("Title") or " ".join(filter(None, [row.get("FirstName"), row.get("LastName")])) or row["id"]
            options.append({"value": row["id"], "label": label})
        options = filter_options_by_search(options, search)
        next_offset = result["next_offset"]
        token = None if next_offset is None else base64.urlsafe_b64encode(json.dumps({"scope": scope, "offset": next_offset}, separators=(",", ":")).encode()).decode().rstrip("=")
        return {"options": options, "next_page_token": token}
    async def execute(self, inputs):
        if not isinstance(self.config, BuildiumNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a native Buildium account API key")
        data = self.config.credentials.model_dump()
        return await records(data, self.config.config.model_dump())
