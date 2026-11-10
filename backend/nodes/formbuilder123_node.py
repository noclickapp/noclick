"""123FormBuilder API v2: region-bound metadata and ordinary form/group edits."""
import base64
from contextvars import ContextVar
from datetime import datetime
import hashlib
import json
import logging
import re
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Discriminator, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import normalize_search, filter_options_by_search
from nodes.formbuilder123_authority import FormBuilder123CredentialsStore, CURRENT_ORGANIZATION
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from utils.ssrf import assert_exact_url_origin, guarded_async_client

HOSTS = {"us": "https://api.123formbuilder.com", "eu": "https://eu-api.123formbuilder.com"}
FAMILY = "123formbuilder_v2_token"
NODE_TYPE = "automation-123formbuilder"
MAX_BYTES = 2 * 1024 * 1024
OPS = ("check_connection", "list_forms", "get_form", "list_form_fields", "get_form_field", "list_submissions", "get_submission", "list_groups", "get_group", "list_group_forms", "list_users", "create_inactive_form", "rename_form", "move_form", "deactivate_form", "create_group", "rename_group")
_ORG_OMITTED = object()
_PRIVATE = ContextVar("123formbuilder_private_transport", default=False)


def identifier(value):
    if type(value) is int and 0 < value <= 9223372036854775807: return str(value)
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,18}", value) and int(value) <= 9223372036854775807: return value
    raise ValueError("Use a positive 123FormBuilder integer ID")


def text(value, limit=200, *, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()) or any(ord(c) < 32 for c in value):
        raise ValueError("Use bounded plain text without control characters")
    return value


def clean_token(value):
    if not isinstance(value, str): raise ValueError("Use a string API v2 token")
    value = clean_secret(value, field_name="123FormBuilder API v2 token")
    if len(value) > 8192 or not re.fullmatch(r"[!-~]+", value): raise ValueError("Use the genuine API v2 token without whitespace")
    return value


class FormBuilder123TokenCredential(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://www.123formbuilder.com/developer/api-v2-authentication/",
        "x-credential-instructions": "Supply an existing API v2 JWT from your 123FormBuilder account. Choose US for main-site accounts or EU for EU-site accounts. Token issuance uses the vendor's documented login endpoint; this node does not store passwords or guess token expiry. Reconnect with a current token when needed.",
    })
    credential_type: Literal["123formbuilder_v2_token"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    region: Literal["us", "eu"] = Field(..., title="Account Region", json_schema_extra={"enumNames": ["US", "EU"]})
    token: str = Field(..., title="API v2 Token", json_schema_extra={"ui:widget": "password", "ui:sensitive": True})
    _token = field_validator("token", mode="before")(clean_token)


def credential(data):
    try:
        if not isinstance(data, dict) or data.get("credential_type") != FAMILY: raise ValueError()
        if any(data.get(k) not in (None, "") for k in ("api_key", "password", "username", "email", "passhash", "access_token", "refresh_token", "base_url")): raise ValueError()
        return FormBuilder123TokenCredential.model_validate(data).model_dump()
    except Exception: raise ValueError("123FormBuilder requires its native regional API v2 token credential") from None


def resource(kind, parent=None):
    dynamic = {"field_name": kind+"_id", "searchable": True, "allow_custom": True}
    if parent: dynamic["depends_on"] = parent
    return {"x-resource-type": "123formbuilder_"+kind, "x-dynamic-options": dynamic}


class _Operation(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    @field_validator("form_id", "field_id", "submission_id", "group_id", "parent_id", "start_submission_id", mode="before", check_fields=False)
    @classmethod
    def ids(cls, value): return None if value is None else identifier(value)


class _Page(_Operation):
    page: int = Field(1, strict=True, ge=1, le=1000000, title="Page")
    per_page: int = Field(50, strict=True, ge=1, le=1000, title="Results per Page")


class CheckConnection(_Operation):
    operation: Literal["check_connection"] = Field("check_connection", title="Check Regional API Access")


class ListForms(_Page):
    operation: Literal["list_forms"] = Field("list_forms", title="List Forms")
    search: str = Field("", max_length=200, title="Form Name Search")
    _search = field_validator("search", mode="before")(lambda value: text(value, empty=True))


class GetForm(_Operation):
    operation: Literal["get_form"] = Field("get_form", title="Get Form Metadata")
    form_id: str = Field(..., title="Form", json_schema_extra=resource("form"))


class ListFormFields(GetForm):
    operation: Literal["list_form_fields"] = Field("list_form_fields", title="List Form Fields")


class GetFormField(GetForm):
    operation: Literal["get_form_field"] = Field("get_form_field", title="Get Field Metadata from Form")
    field_id: str = Field(..., title="Field", json_schema_extra=resource("field", "form_id"))


class ListSubmissions(_Page):
    operation: Literal["list_submissions"] = Field("list_submissions", title="List Submission Metadata")
    form_id: str = Field(..., title="Form", json_schema_extra=resource("form"))
    start_submission_id: Optional[str] = Field(None, title="Starting Submission ID")


class GetSubmission(GetForm):
    operation: Literal["get_submission"] = Field("get_submission", title="Get Submission Metadata")
    submission_id: str = Field(..., title="Submission", json_schema_extra=resource("submission", "form_id"))


class ListGroups(_Page):
    operation: Literal["list_groups"] = Field("list_groups", title="List Folders (Groups)")


class GetGroup(_Operation):
    operation: Literal["get_group"] = Field("get_group", title="Get Folder Metadata")
    group_id: str = Field(..., title="Folder", json_schema_extra=resource("group"))


class ListGroupForms(GetGroup):
    operation: Literal["list_group_forms"] = Field("list_group_forms", title="List Forms in Folder")


class ListUsers(_Page):
    operation: Literal["list_users"] = Field("list_users", title="List Account User Metadata")


class CreateInactiveForm(_Operation):
    operation: Literal["create_inactive_form"] = Field("create_inactive_form", title="Create Inactive Form")
    name: str = Field(..., max_length=200, title="Form Name")
    group_id: Optional[str] = Field(None, title="Folder (optional)", json_schema_extra=resource("group"))
    _name = field_validator("name", mode="before")(text)


class RenameForm(GetForm):
    operation: Literal["rename_form"] = Field("rename_form", title="Rename Form")
    name: str = Field(..., max_length=200, title="New Form Name")
    _name = field_validator("name", mode="before")(text)


class MoveForm(GetForm):
    operation: Literal["move_form"] = Field("move_form", title="Move Form into Folder")
    group_id: str = Field(..., title="Destination Folder", json_schema_extra=resource("group"))


class DeactivateForm(GetForm):
    operation: Literal["deactivate_form"] = Field("deactivate_form", title="Deactivate Form", description="Ordinary management change: stops form availability. Account automations may observe changes.")


class CreateGroup(_Operation):
    operation: Literal["create_group"] = Field("create_group", title="Create Folder (Group)")
    name: str = Field(..., max_length=200, title="Folder Name")
    parent_id: Optional[str] = Field(None, title="Parent Folder (optional)", json_schema_extra=resource("group"))
    _name = field_validator("name", mode="before")(text)


class RenameGroup(GetGroup):
    operation: Literal["rename_group"] = Field("rename_group", title="Rename Folder")
    name: str = Field(..., max_length=200, title="New Folder Name")
    _name = field_validator("name", mode="before")(text)


FormBuilder123Operation = Annotated[Union[CheckConnection, ListForms, GetForm, ListFormFields, GetFormField, ListSubmissions, GetSubmission, ListGroups, GetGroup, ListGroupForms, ListUsers, CreateInactiveForm, RenameForm, MoveForm, DeactivateForm, CreateGroup, RenameGroup], Discriminator("operation")]


class FormBuilder123NodeConfig(NodeConfig[FormBuilder123Operation, FormBuilder123TokenCredential]):
    pass


class _BoundCredential(dict):
    def __init__(self, data, store, snapshot):
        super().__init__(data)
        self["_123formbuilder_saved_authority_required"] = True
        self.store, self.snapshot = store, snapshot


_Store = FormBuilder123CredentialsStore

async def _load_current(store):
    try:
        raw = await store.load()
        stamp = raw.get("updated_at")
        if not isinstance(stamp, str) or datetime.fromisoformat(stamp).tzinfo is None or store.current is None: raise ValueError()
        return credential(raw), (store.current, stamp)
    except ValueError: raise ValueError("123FormBuilder saved token or current access changed; reload") from None
    except Exception: raise RuntimeError("123FormBuilder current credential authority could not be verified") from None


async def current_credential(data):
    shaped = credential(data)
    if not isinstance(data, _BoundCredential):
        if "_123formbuilder_saved_authority_required" in data: raise ValueError("123FormBuilder saved authority was lost; reload")
        return shaped
    now, snapshot = await _load_current(data.store)
    if data.get("_123formbuilder_saved_authority_required") is not True or now != shaped or snapshot != data.snapshot:
        raise ValueError("123FormBuilder region, token or current authority changed; reload")
    return now


class _Privacy(logging.Filter):
    def filter(self, record):
        if _PRIVATE.get() and (record.name in {"httpx", "httpcore"} or record.name.startswith(("httpx.", "httpcore."))):
            record.msg, record.args = "123FormBuilder private transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_FILTER = _Privacy()
def _install_privacy():
    names = {"httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"}
    names.update(n for n in logging.Logger.manager.loggerDict if n.startswith(("httpx.", "httpcore.")))
    for name in names: logging.getLogger(name).addFilter(_FILTER)
    for handler in logging.getLogger().handlers: handler.addFilter(_FILTER)


class FormBuilder123HTTPError(RuntimeError):
    def __init__(self, status):
        self.status_code = status
        super().__init__(f"123FormBuilder request did not complete (HTTP {status}); verify changes before retrying")


def _json(content):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out: raise ValueError()
            out[key] = value
        return out
    try: return json.loads(content, object_pairs_hook=pairs, parse_constant=lambda _v: (_ for _ in ()).throw(ValueError()))
    except Exception: raise RuntimeError("123FormBuilder returned invalid JSON") from None


async def request(data, method, path, *, params=None, body=None, status=200, token_in_body=False):
    shaped = await current_credential(data)
    origin = HOSTS[shaped["region"]]
    route = "/v2"+path
    if not re.fullmatch(r"/v2/(forms|groups|users)(/[1-9][0-9]*)?(/(fields|submissions|forms))?(/[1-9][0-9]*)?", route): raise ValueError("Unsupported native 123FormBuilder route")
    query, payload = dict(params or {}), dict(body or {})
    # Swagger formData parameters use form encoding; responses are JSON.
    (payload if token_in_body else query)["JWT"] = shaped["token"]
    async def exact(req):
        assert_exact_url_origin(str(req.url), origin)
        if req.url.path != route: raise ValueError("123FormBuilder transport route changed")
    content = bytearray()
    marker = _PRIVATE.set(True)
    _install_privacy()
    try:
        async with guarded_async_client(timeout=20, trust_env=False, follow_redirects=False, event_hooks={"request": [exact]}) as client:
            async with client.stream(method, origin+route, params=query, data=payload if method != "GET" else None, headers={"Accept": "application/json"}) as response:
                if response.status_code != status: raise FormBuilder123HTTPError(response.status_code)
                async for part in response.aiter_bytes():
                    content.extend(part)
                    if len(content) > MAX_BYTES: raise RuntimeError("123FormBuilder response exceeded its local byte bound")
    except FormBuilder123HTTPError: raise
    except Exception: raise RuntimeError("123FormBuilder private transport could not complete; verify changes before retrying") from None
    finally: _PRIVATE.reset(marker)
    await current_credential(data)
    result = _json(content)
    if not isinstance(result, dict) or "error" in result or type(result.get("status_code")) is not int or result["status_code"] != status:
        raise RuntimeError("123FormBuilder refused the operation or returned an invalid status envelope")
    return result


def project(row, kind):
    if not isinstance(row, dict): raise RuntimeError("123FormBuilder returned an invalid metadata record")
    out = {"id": identifier(row.get("id"))}
    if kind in {"form", "group", "field"} and "name" in row: out["name"] = text(row["name"], 1000, empty=True)
    id_fields = {"form": ("group_id", "user_id", "created_by"), "field": ("form_id",), "submission": ("form_id", "entry_id"), "group": ("parent_id",), "user": ("user_parent",)}[kind]
    for key in id_fields:
        if row.get(key) in (None, -1, 0): continue
        out[key] = identifier(row[key])
    fields = {"form": ("submissions_count", "submissions_count_month", "active"), "field": ("position", "type", "subtype", "required", "hidden"), "submission": ("deleted", "status", "approved"), "group": (), "user": ("admin", "allow_create_form", "allow_duplicate_form", "allow_delete_form")}[kind]
    for key in fields:
        if key not in row: continue
        if type(row[key]) is not int or row[key] < 0: raise RuntimeError("123FormBuilder returned invalid numeric metadata")
        out[key] = row[key]
    if kind == "submission" and "date" in row: out["date"] = text(row["date"], 100, empty=True)
    return out


def page(result, kind, requested_page, requested_size):
    rows = result.get("data")
    p = result.get("meta", {}).get("pagination") if isinstance(result.get("meta"), dict) else None
    if not isinstance(rows, list) or len(rows) > requested_size or not isinstance(p, dict): raise RuntimeError("123FormBuilder returned an invalid paginated envelope")
    values = [p.get(k) for k in ("total", "count", "per_page", "current_page", "total_pages")]
    if any(type(v) is not int or v < 0 for v in values) or p["count"] != len(rows) or p["per_page"] != requested_size or p["current_page"] != requested_page or p["total"] < len(rows):
        raise RuntimeError("123FormBuilder pagination metadata did not match the requested page")
    if p["total_pages"] < requested_page and not (p["total"] == 0 and not rows and p["total_pages"] == 0 and requested_page == 1): raise RuntimeError("123FormBuilder returned an invalid page range")
    records = [project(row, kind) for row in rows]
    if len({r["id"] for r in records}) != len(records): raise RuntimeError("123FormBuilder returned duplicate metadata IDs")
    return {"records": records, "pagination": {k: p[k] for k in ("total", "count", "per_page", "current_page", "total_pages")}, "next_page": requested_page+1 if requested_page < p["total_pages"] else None}


async def get_record(data, kind, rid):
    result = await request(data, "GET", "/"+{"form": "forms", "group": "groups"}[kind]+"/"+identifier(rid))
    row = project(result.get("data"), kind)
    if row["id"] != rid: raise RuntimeError("123FormBuilder metadata ID did not match the selected resource")
    return row


async def records(data, config):
    from pydantic import TypeAdapter
    cfg = TypeAdapter(FormBuilder123Operation).validate_python(config).model_dump()
    op = cfg["operation"]
    if op == "check_connection":
        result = await request(data, "GET", "/forms", params={"page": 1, "per_page": 1})
        page(result, "form", 1, 1)
        return {"reachable": True, "proves": "reachability", "identity_verified": False}
    lists = {"list_forms": ("/forms", "form"), "list_groups": ("/groups", "group"), "list_users": ("/users", "user")}
    if op in lists:
        path, kind = lists[op]
        params = {"page": cfg["page"], "per_page": cfg["per_page"]}
        if op == "list_forms" and cfg["search"]: params["search"] = cfg["search"]
        return page(await request(data, "GET", path, params=params), kind, cfg["page"], cfg["per_page"])
    if op in {"get_form", "get_group"}:
        kind = "form" if op == "get_form" else "group"
        return {"record": await get_record(data, kind, cfg[kind+"_id"])}
    if op in {"list_form_fields", "get_form_field", "list_submissions", "get_submission"}:
        fid = cfg["form_id"]
        await get_record(data, "form", fid)
        if op in {"list_form_fields", "get_form_field"}:
            result = (await request(data, "GET", "/forms/"+fid+"/fields")).get("data")
            if not isinstance(result, dict) or identifier(result.get("id")) != fid or not isinstance(result.get("controls"), dict): raise RuntimeError("123FormBuilder fields did not witness the selected form")
            rows = result["controls"].get("data")
            if not isinstance(rows, list) or len(rows) > 1000: raise RuntimeError("123FormBuilder returned an invalid field collection")
            projected = [project(row, "field") for row in rows]
            if any(row.get("form_id") != fid for row in projected) or len({r["id"] for r in projected}) != len(projected): raise RuntimeError("123FormBuilder fields belong to a different form or contain duplicate IDs")
            if op == "list_form_fields": return {"records": projected, "form_id": fid}
            matching = [row for row in projected if row["id"] == cfg["field_id"]]
            if len(matching) != 1: raise ValueError("The selected field is not in the current form")
            return {"record": matching[0]}
        path = "/forms/"+fid+"/submissions"
        if op == "get_submission":
            result = await request(data, "GET", path+"/"+cfg["submission_id"])
            rows = result.get("data")
            if not isinstance(rows, list) or len(rows) != 1: raise RuntimeError("123FormBuilder returned invalid single-submission data")
            row = project(rows[0], "submission")
            if row["id"] != cfg["submission_id"] or row.get("form_id") != fid: raise RuntimeError("123FormBuilder submission did not witness the selected form and ID")
            return {"record": row}
        params = {"page": cfg["page"], "per_page": cfg["per_page"]}
        if cfg["start_submission_id"] is not None: params["start_submission_id"] = int(cfg["start_submission_id"])
        output = page(await request(data, "GET", path, params=params), "submission", cfg["page"], cfg["per_page"])
        if any(row.get("form_id") != fid for row in output["records"]): raise RuntimeError("123FormBuilder submission belongs to another form")
        return output
    if op == "list_group_forms":
        gid = cfg["group_id"]
        await get_record(data, "group", gid)
        group = (await request(data, "GET", "/groups/"+gid+"/forms")).get("data")
        if not isinstance(group, dict) or identifier(group.get("id")) != gid or not isinstance(group.get("forms"), list) or len(group["forms"]) > 1000: raise RuntimeError("123FormBuilder returned invalid folder forms")
        rows = [project(row, "form") for row in group["forms"]]
        if any(row.get("group_id") != gid for row in rows) or len({r["id"] for r in rows}) != len(rows): raise RuntimeError("123FormBuilder forms belong to another folder or contain duplicate IDs")
        return {"records": rows, "group_id": gid}
    if op in {"create_inactive_form", "create_group"}:
        kind = "form" if op == "create_inactive_form" else "group"
        payload = {"name": cfg["name"]}
        parent_key = "group_id" if kind == "form" else "parent_id"
        if cfg.get(parent_key):
            await get_record(data, "group", cfg[parent_key])
            payload[parent_key] = int(cfg[parent_key])
        if kind == "form": payload["active"] = 3
        result = await request(data, "POST", "/"+("forms" if kind == "form" else "groups"), body=payload, status=201, token_in_body=True)
        created = project(result.get("data"), kind)
        row = await get_record(data, kind, created["id"])
        if row.get("name") != cfg["name"] or kind == "form" and row.get("active") != 3 or cfg.get(parent_key) and row.get(parent_key) != cfg[parent_key]: raise RuntimeError("123FormBuilder creation readback did not match; inspect before retrying")
        return {"record": row, "readback_verified": True}
    kind = "group" if op == "rename_group" else "form"
    rid = cfg[kind+"_id"]
    await get_record(data, kind, rid)
    payload = {"name": cfg["name"]} if op in {"rename_form", "rename_group"} else {"active": 3} if op == "deactivate_form" else {"group_id": int(cfg["group_id"])}
    if op == "move_form": await get_record(data, "group", cfg["group_id"])
    await request(data, "PUT", "/"+("forms" if kind == "form" else "groups")+"/"+rid, body=payload, token_in_body=kind == "group")
    row = await get_record(data, kind, rid)
    if any(row.get(k) != (str(v) if k.endswith("_id") else v) for k,v in payload.items()): raise RuntimeError("123FormBuilder management readback did not match; inspect before retrying")
    return {"record": row, "readback_verified": True}


class FormBuilder123Node(WorkflowNode):
    integration_type = "automation-123formbuilder"
    credential_provider_labels = {"123formbuilder": "123FormBuilder Account"}
    auto_select_credential = False
    workflow_credential_refresh = True
    scope_registry = ScopeRegistry(provider="123formbuilder", enforcement=Enforcement.STRICT, requirements={op: ScopeRequirement(scopes=(), credential_types=(FAMILY,)) for op in OPS})
    connection_evidence = ConnectionEvidence(field="form_id", noun="forms", operation="check_connection")
    edit_examples = ["List my forms and folders", "Read metadata for new submissions", "Create an inactive form", "Move a form into a folder"]
    @classmethod
    def get_config_model(cls): return FormBuilder123NodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None: credential(config_data["credentials"])
        return super().parse_config(config_data)
    @classmethod
    def validate_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: credential(config_data["credentials"])
            except ValueError: return {"valid": False, "errors": ["Connect a native 123FormBuilder API v2 token"], "satisfied_set": None}
        return super().validate_config(config_data)
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._freshen_saved_credential(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)

    @classmethod
    async def _freshen_saved_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None, workflow_id=None, organization_id=_ORG_OMITTED, require_owner=False):
        initial = credential(credential_data)
        if not credential_id:
            if "_123formbuilder_saved_authority_required" in credential_data: raise ValueError("123FormBuilder saved authority was lost; reload")
            return initial
        if not user_id: raise ValueError("123FormBuilder requires the current authorized principal")
        def validate(data):
            shaped = credential(data)
            if shaped != initial: raise ValueError("123FormBuilder saved region or token changed")
            return shaped
        store = _Store(pool, user_id, credential_id, credential_type=FAMILY, validate=validate,
            organization_id=CURRENT_ORGANIZATION if organization_id is _ORG_OMITTED else organization_id,
            workflow_id=workflow_id, require_owner=require_owner)
        current, snapshot = await _load_current(store)
        return _BoundCredential(current, store, snapshot)
    @classmethod
    async def validate_credential_access(cls, credential_data, *, validation_context=None):
        try: credential(credential_data)
        except ValueError: return {"valid": False, "error": "123FormBuilder credential shape is invalid"}
        # Staging's legacy hook receives only the decrypted blob, with no
        # trusted row/context. Connection evidence performs the native probe.
        return {"valid": None, "error": "Save and check current regional API access"}
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name not in {"form_id", "group_id", "field_id", "submission_id"}: raise ValueError("Unsupported 123FormBuilder picker")
        parent = identifier((context or {}).get("form_id")) if field_name in {"field_id", "submission_id"} else None
        query = normalize_search(search) or ""
        text(query, empty=True)
        shaped = await current_credential(credential_data)
        scope = hashlib.sha256(json.dumps({"credential": shaped, "field": field_name, "parent": parent, "search": query}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        number = 1
        if page_token is not None:
            try:
                if not isinstance(page_token, str) or len(page_token) > 512 or field_name == "field_id": raise ValueError()
                cursor = _json(base64.urlsafe_b64decode(page_token+"="*((-len(page_token))%4)))
                if set(cursor) != {"scope", "page"} or cursor["scope"] != scope or type(cursor["page"]) is not int or not 1 < cursor["page"] <= 1000000: raise ValueError()
                number = cursor["page"]
            except Exception: raise ValueError("123FormBuilder picker cursor does not match current region, token, field, form and search") from None
        operation = {"form_id": "list_forms", "group_id": "list_groups", "field_id": "list_form_fields", "submission_id": "list_submissions"}[field_name]
        args = {"operation": operation}
        if parent: args["form_id"] = parent
        if field_name != "field_id": args.update(page=number, per_page=50)
        if field_name == "form_id": args["search"] = query
        result = await records(credential_data, args)
        options = [{"value": r["id"], "label": r.get("name") or r["id"]} for r in result["records"]]
        options = filter_options_by_search(options, query) if field_name != "form_id" else options
        next_number = result.get("next_page")
        next_token = None if next_number is None else base64.urlsafe_b64encode(json.dumps({"scope": scope, "page": next_number}, separators=(",", ":")).encode()).decode().rstrip("=")
        return {"options": options, "next_page_token": next_token}
    async def execute(self, inputs):
        if not isinstance(self.config, FormBuilder123NodeConfig) or self.config.credentials is None: raise ValueError("Connect a native 123FormBuilder API v2 token")
        raw = (self.node_data or {}).get("credentials")
        data = await self._freshen_saved_credential(raw if raw is not None else self.config.credentials.model_dump(), pool=(self.node_data or {}).get("_approval_pool"), user_id=self.user_id,
            credential_id=(self.node_data or {}).get("credential_id"), workflow_id=self.workflow_id, organization_id=self.organization_id)
        return await records(data, self.config.config.model_dump())
