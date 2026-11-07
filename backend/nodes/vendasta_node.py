"""Native Vendasta CRM record, relationship and field-schema workflows.

Only documented fixed-environment CRM methods are exposed. Saved credentials
validate the supplied namespace and field grants before each request.
"""
import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import normalize_search
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement
from utils.ssrf import guarded_async_client

FAMILY = "vendasta_access_token"
NODE_TYPE = "automation-vendasta"
ROOTS = {"prod": "https://prod.apigateway.co/grpc", "demo": "https://demo.apigateway.co/grpc"}
KINDS = {"contact": "Contact", "company": "Company", "opportunity": "Opportunity"}
DEFAULT_FIELDS = "standard__first_name,standard__last_name,standard__company_name,standard__opportunity_name"
SECRET_NAME = re.compile(r"password|secret|token|credential|api.?key|authorization", re.I)
ZERO_DATE = "0001-01-01T00:00:00Z"


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}", value):
        raise ValueError("Use a native Vendasta namespace, record or field ID")
    return value


def csv_ids(value):
    if not isinstance(value, str):
        raise ValueError("Use comma-separated native field IDs")
    items = [identifier(item.strip()) for item in value.split(",") if item.strip()]
    if len(items) > 30 or len(set(items)) != len(items) or any(SECRET_NAME.search(v) for v in items):
        raise ValueError("Use at most 30 distinct non-secret metadata field IDs")
    return items


def instant(value):
    if not isinstance(value, str):
        raise ValueError("Use the issuer's explicit token expiration")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Use a token expiration with timezone") from None
    if parsed.tzinfo is None:
        raise ValueError("Use a token expiration with timezone")
    return parsed


class VendastaAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="Vendasta Access Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-instructions": "Enter an issued OAuth2 access token and its issuer-reported expiry/scopes. Choose its environment and one authorized CRM namespace. NoClick does not mint or renew this supplied token. CRM API access may require Trusted Tester entitlement.",
                           "x-credential-url": "https://developers.vendasta.com/getting-started/authorization/"})
    credential_type: Literal["vendasta_access_token"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=8192, title="Access Token", json_schema_extra={"ui:widget": "password", "ui:sensitive": True})
    environment: Literal["prod", "demo"] = Field(..., title="Environment")
    namespace: str = Field(..., title="CRM Namespace", description="Partner ID or account group ID authorized for this token.")
    expires_at: str = Field(..., title="Token Expiration", description="Issuer-reported ISO timestamp with timezone; this is not inferred from the token.")
    scope: str = Field(..., title="Granted Scopes", description="Exact space-separated scopes returned by the issuer.")
    read_fields_csv: str = Field(DEFAULT_FIELDS, title="Readable Metadata Fields", description="Explicit comma-separated field IDs or external IDs whose values may appear in outputs.")
    write_fields_csv: str = Field(DEFAULT_FIELDS + ",standard__opportunity_pipeline_id", title="Writable Metadata Fields", description="Explicit field IDs or external IDs allowed for record metadata mutations.")
    @field_validator("namespace")
    @classmethod
    def native_namespace(cls, value): return identifier(value)
    @field_validator("access_token")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access Token")
        if not re.fullmatch(r"[A-Za-z0-9._~+/-]+={0,2}", value):
            raise ValueError("Use the supplied Bearer token value without its header prefix")
        return value
    @field_validator("expires_at")
    @classmethod
    def expiry(cls, value):
        instant(value)
        return value
    @field_validator("scope")
    @classmethod
    def scopes(cls, value):
        if not isinstance(value, str) or not value.strip() or any(not re.fullmatch(r"[A-Za-z0-9._:-]+", s) for s in value.split()):
            raise ValueError("Enter the issuer-reported scopes")
        return " ".join(dict.fromkeys(value.split()))
    @field_validator("read_fields_csv", "write_fields_csv")
    @classmethod
    def grants(cls, value):
        csv_ids(value)
        return value


def credential(data):
    if not isinstance(data, dict) or data.get("credential_type") != FAMILY:
        raise ValueError("Connect a native Vendasta supplied access token")
    if any(k in data for k in ("api_key", "refresh_token", "client_secret", "private_key", "base_url", "host")):
        raise ValueError("Use only the native supplied-token credential form")
    value = VendastaAccessTokenCredential.model_validate(data).model_dump()
    if instant(value["expires_at"]) <= datetime.now(timezone.utc):
        raise ValueError("Vendasta supplied access token expired; enter a newly issued token")
    return value


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ListRecords(Config):
    page_size: int = Field(100, ge=1, le=1000)
    cursor: Optional[str] = Field(None, max_length=4096)
    max_pages: int = Field(1, ge=1, le=5, description="Bounded pages; incomplete results retain has_more and next_cursor.")
    search: Optional[str] = Field(None, max_length=300)
    filters_json: Optional[str] = Field(None, max_length=10000, json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}, description="Optional typed filtersV2 FilterGroup JSON. The entire query is repeated on every page.")
    sort_json: Optional[str] = Field(None, max_length=2000, json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"}, description="Optional array of fieldId/sortDirection objects; use actual fieldId for sorting.")


class GetRecord(Config):
    record_id: str = Field(..., json_schema_extra={"x-resource-type": "vendasta_record", "x-dynamic-options": {"field_name": "record_id", "depends_on": ["operation"], "searchable": True, "allow_custom": True}})
    @field_validator("record_id")
    @classmethod
    def native_record(cls, value): return identifier(value)


class WriteRecord(Config):
    fields_json: str = Field(..., max_length=50000, title="Metadata Fields JSON", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
        description="Array of native FieldValue objects with fieldId and one typed value. Fields must be in the saved write allowlist and current nonfinancial writable schema.")
    effects_confirmed: bool = Field(..., strict=True, description="Changes may trigger existing CRM automations. Creation cannot be safely deduplicated by idempotencyId.")
    @field_validator("effects_confirmed")
    @classmethod
    def confirmed(cls, value):
        if value is not True: raise ValueError("Confirm the record mutation effects")
        return value


class UpdateRecord(WriteRecord, GetRecord):
    pass


class ChangeState(GetRecord):
    effects_confirmed: bool = Field(..., strict=True, description="Confirm soft deletion or restoration; soft deletion does not erase data.")
    @field_validator("effects_confirmed")
    @classmethod
    def confirmed(cls, value):
        if value is not True: raise ValueError("Confirm the soft-delete or restore effects")
        return value


class ListContacts(ListRecords):
    operation: Literal["list_contacts"] = "list_contacts"

class GetContact(GetRecord):
    operation: Literal["get_contact"] = "get_contact"

class CreateContact(WriteRecord):
    operation: Literal["create_contact"] = "create_contact"

class UpdateContact(UpdateRecord):
    operation: Literal["update_contact"] = "update_contact"

class SoftDeleteContact(ChangeState):
    operation: Literal["soft_delete_contact"] = "soft_delete_contact"

class RestoreContact(ChangeState):
    operation: Literal["restore_contact"] = "restore_contact"

class ListCompanies(ListRecords):
    operation: Literal["list_companies"] = "list_companies"

class GetCompany(GetRecord):
    operation: Literal["get_company"] = "get_company"

class CreateCompany(WriteRecord):
    operation: Literal["create_company"] = "create_company"

class UpdateCompany(UpdateRecord):
    operation: Literal["update_company"] = "update_company"

class SoftDeleteCompany(ChangeState):
    operation: Literal["soft_delete_company"] = "soft_delete_company"

class RestoreCompany(ChangeState):
    operation: Literal["restore_company"] = "restore_company"

class ListOpportunities(ListRecords):
    operation: Literal["list_opportunities"] = "list_opportunities"

class GetOpportunity(GetRecord):
    operation: Literal["get_opportunity"] = "get_opportunity"

class CreateOpportunity(WriteRecord):
    operation: Literal["create_opportunity"] = "create_opportunity"

class UpdateOpportunity(UpdateRecord):
    operation: Literal["update_opportunity"] = "update_opportunity"

class SoftDeleteOpportunity(ChangeState):
    operation: Literal["soft_delete_opportunity"] = "soft_delete_opportunity"

class RestoreOpportunity(ChangeState):
    operation: Literal["restore_opportunity"] = "restore_opportunity"


class CheckConnection(Config):
    operation: Literal["check_connection"] = "check_connection"


class ListFieldSchemas(Config):
    operation: Literal["list_field_schemas"] = "list_field_schemas"
    object_type: Literal["Contact", "Company", "Opportunity"] = "Contact"
    page_size: int = Field(100, ge=1, le=1000)
    cursor: Optional[str] = Field(None, max_length=4096)
    max_pages: int = Field(1, ge=1, le=5)
    search: Optional[str] = Field(None, max_length=300)


class GetFieldSchema(Config):
    operation: Literal["get_field_schema"] = "get_field_schema"
    object_type: Literal["Contact", "Company", "Opportunity"] = "Contact"
    field_id: str = Field(..., json_schema_extra={"x-resource-type": "vendasta_field", "x-dynamic-options": {"field_name": "field_id", "depends_on": ["object_type"], "searchable": True, "allow_custom": True}})


class ListFieldOptions(GetFieldSchema):
    operation: Literal["list_field_options"] = "list_field_options"
    page_size: int = Field(100, ge=1, le=1000)
    search: Optional[str] = Field(None, max_length=300)


class ListAssociations(Config):
    operation: Literal["list_associations"] = "list_associations"
    association_type: Literal["Contact-Company", "Company-Company", "Company-Opportunity", "Contact-Opportunity"]
    from_id: str = Field(..., title="Source Record ID")
    to_id: Optional[str] = Field(None, title="Optional Target Record ID")
    page_size: int = Field(100, ge=1, le=1000)
    cursor: Optional[str] = Field(None, max_length=4096)
    max_pages: int = Field(1, ge=1, le=5)


class GetAssociation(Config):
    operation: Literal["get_association"] = "get_association"
    association_id: str
    association_type: Literal["Contact-Company", "Company-Company", "Company-Opportunity", "Contact-Opportunity"]
    from_id: str
    to_id: str


class ListPipelines(Config):
    operation: Literal["list_pipelines"] = "list_pipelines"
    object_type: Literal["Contact", "Company", "Opportunity"] = "Opportunity"


class GetPipeline(Config):
    operation: Literal["get_pipeline"] = "get_pipeline"
    pipeline_id: str
    object_type: Literal["Contact", "Company", "Opportunity"] = "Opportunity"


Operation = Annotated[Union[ListContacts, GetContact, CreateContact, UpdateContact, SoftDeleteContact, RestoreContact, ListCompanies, GetCompany, CreateCompany, UpdateCompany, SoftDeleteCompany, RestoreCompany, ListOpportunities, GetOpportunity, CreateOpportunity, UpdateOpportunity, SoftDeleteOpportunity, RestoreOpportunity, CheckConnection, ListFieldSchemas, GetFieldSchema, ListFieldOptions, ListAssociations, GetAssociation, ListPipelines, GetPipeline], Field(discriminator="operation")]
OPS = tuple(TypeAdapter(Operation).json_schema()["discriminator"]["mapping"])


class VendastaNodeConfig(NodeConfig[Operation, VendastaAccessTokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class FieldValue(Config):
    fieldId: str
    stringValue: Optional[str] = Field(None, max_length=4000)
    booleanValue: Optional[bool] = Field(None, strict=True)
    integerValue: Optional[str] = Field(None, pattern=r"^-?[0-9]+$")
    stringValues: Optional[dict[str, list[str]]] = None
    @model_validator(mode="after")
    def one_value(self):
        identifier(self.fieldId)
        if sum(getattr(self, k) is not None for k in ("stringValue", "booleanValue", "integerValue", "stringValues")) != 1:
            raise ValueError("Each metadata field needs one native typed value")
        if self.stringValues is not None and (set(self.stringValues) != {"values"} or len(self.stringValues["values"]) > 30 or any(len(v) > 500 for v in self.stringValues["values"])):
            raise ValueError("Use a bounded native string list")
        return self


class FilterValue(Config):
    string: Optional[str] = Field(None, max_length=300)
    integer: Optional[str] = Field(None, pattern=r"^-?[0-9]+$")
    boolean: Optional[bool] = Field(None, strict=True)
    @model_validator(mode="after")
    def one_value(self):
        if sum(getattr(self, k) is not None for k in ("string", "integer", "boolean")) != 1:
            raise ValueError("Use exactly one native filter value")
        return self


class Filter(Config):
    fieldId: str
    operator: Literal["FILTER_OPERATOR_IS", "FILTER_OPERATOR_IS_NOT", "FILTER_OPERATOR_CONTAINS", "FILTER_OPERATOR_IS_EMPTY", "FILTER_OPERATOR_IS_NOT_EMPTY"]
    values: list[FilterValue] = Field(default_factory=list, max_length=10)


class FilterGroup(Config):
    operator: Literal["FILTER_GROUP_OPERATOR_AND", "FILTER_GROUP_OPERATOR_OR"]
    filters: list[Filter] = Field(..., min_length=1, max_length=10)


class SortBy(Config):
    fieldId: str
    sortDirection: Literal["SORT_DIRECTION_ASCENDING", "SORT_DIRECTION_DESCENDING"]


def strict_json(value):
    def unique_pairs(pairs):
        out = {}
        for k, v in pairs:
            if k in out: raise ValueError("Vendasta JSON has duplicate keys")
            out[k] = v
        return out
    def bad_constant(_): raise ValueError("Vendasta JSON contains a nonfinite value")
    try:
        return json.loads(value, object_pairs_hook=unique_pairs, parse_constant=bad_constant)
    except (ValueError, TypeError):
        raise ValueError("Use valid bounded native JSON") from None


async def current_credential(data):
    # Staging resolves saved credentials before dispatch. Supplied access tokens
    # have no refresh flow; validate issuer expiry on every request instead.
    return credential(data)


def scope_for(service, action):
    if service == "field-schema": return "crm.schema:read"
    if service == "pipeline": return "crm.opportunity:read"
    read = action in {"list", "get-multi", "field-options"}
    return "crm." + service + (":read" if read else "")


def require_scope(data, service, action):
    held = set(data["scope"].split())
    needed = scope_for(service, action)
    if service == "pipeline" and held & {"crm", "crm.contact", "crm.contact:read", "crm.company", "crm.company:read", "crm.opportunity", "crm.opportunity:read"}:
        return
    if not ({"crm", needed, needed.removesuffix(":read")} & held):
        raise ValueError("Vendasta token's supplied scopes do not cover this CRM method")


async def request(data, service, action, body):
    allowed = {**{k: {"list", "get-multi", "create", "update", "delete", "restore", "field-options"} for k in KINDS},
               "field-schema": {"list", "get-multi"}, "association": {"list", "get-multi"}, "pipeline": {"list", "get-multi"}}
    if service not in allowed or action not in allowed[service]:
        raise ValueError("Use a declared native Vendasta method")
    now = await current_credential(data)
    require_scope(now, service, action)
    sent_body = deepcopy(body)
    namespace = sent_body.get("listOptions", {}).get("namespace") if service == "pipeline" and action == "list" else sent_body.get("namespace")
    if namespace != now["namespace"]:
        raise ValueError("Vendasta request must retain the saved namespace")
    url = ROOTS[now["environment"]] + "/v1/crm/" + service + "/" + action
    async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
        async with client.stream("POST", url, headers={"Authorization": "Bearer " + now["access_token"], "Accept": "application/json"}, json=sent_body) as response:
            await current_credential(data)
            status = response.status_code
            if status != 200:
                if status in {400, 401, 403, 404, 409, 422}:
                    raise ValueError(f"Vendasta refused the CRM request (HTTP {status})")
                raise RuntimeError(f"Vendasta CRM request did not complete (HTTP {status}); no automatic retry")
            if "application/json" not in response.headers.get("content-type", "").lower():
                raise RuntimeError("Vendasta returned an unexpected response type")
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 2_000_000:
                    raise RuntimeError("Vendasta response exceeds the native metadata limit")
            await current_credential(data)
    raw = strict_json(bytes(content))
    if not isinstance(raw, dict) or any(k in raw for k in ("code", "error", "message", "details")):
        raise RuntimeError("Vendasta returned an unverified CRM response envelope")
    return raw


def rows(raw, key, limit=1000):
    value = raw.get(key)
    if not isinstance(value, list) or len(value) > limit or any(not isinstance(v, dict) for v in value):
        raise RuntimeError("Vendasta returned an unverified collection")
    return value


def paging(raw):
    meta = raw.get("pagingMetadata")
    if not isinstance(meta, dict) or type(meta.get("hasMore")) is not bool:
        raise RuntimeError("Vendasta pagination is unverified")
    cursor = meta.get("nextCursor")
    if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 4096):
        raise RuntimeError("Vendasta cursor is unverified")
    if meta["hasMore"] and not cursor:
        raise RuntimeError("Vendasta has more rows without a usable cursor")
    return {"has_more": meta["hasMore"], "next_cursor": cursor if meta["hasMore"] else None}


def projected_record(item, now):
    record_id = identifier(item.get("crmObjectId"))
    if item.get("namespace") not in {None, "", now["namespace"]}:
        raise ValueError("Vendasta returned a record from another namespace")
    output = {"crmObjectId": record_id}
    for key in ("ownerId", "created", "updated", "deleted"):
        if key in item:
            if not isinstance(item[key], str) or len(item[key]) > 200:
                raise RuntimeError("Vendasta record metadata is unverified")
            output[key] = item[key]
    allowed = set(csv_ids(now["read_fields_csv"]))
    projected = []
    for f in item.get("fields", []):
        if not isinstance(f, dict): raise RuntimeError("Vendasta field value is unverified")
        if f.get("fieldId") not in allowed and f.get("externalId") not in allowed: continue
        if SECRET_NAME.search(str(f.get("externalId", ""))): continue
        clean = FieldValue.model_validate({k: deepcopy(v) for k, v in f.items() if k in {"fieldId", "stringValue", "booleanValue", "integerValue", "stringValues"}}).model_dump(exclude_none=True)
        if f.get("externalId"): clean["externalId"] = identifier(f["externalId"])
        if len(json.dumps(clean)) > 5000: raise RuntimeError("Vendasta metadata field is oversized")
        projected.append(clean)
    output["fields"] = projected
    return output


def projected_schema(item, kind):
    if item.get("crmObjectType") != kind:
        raise ValueError("Vendasta field schema type differs")
    identifier(item.get("fieldId"))
    return {k: deepcopy(v) for k, v in item.items() if k in {"fieldId", "externalId", "fieldName", "fieldType", "crmObjectType", "readonly", "skipAutomation", "namespace"}}


def active(item):
    value = item.get("deleted")
    if value is None or value == "" or value == ZERO_DATE:
        return True
    instant(value)
    return False


async def get_record(data, kind, record_id, *, include_deleted=False, field_ids=None):
    now = await current_credential(data)
    body = {"namespace": now["namespace"], "crmObjectIds": [identifier(record_id)]}
    if include_deleted:
        body["projectionFilters"] = [{"filterType": "PROJECTION_FILTER_TYPE_INCLUDE_DELETED"}]
    if field_ids:
        body["fieldMask"] = {"paths": ["fields." + identifier(v) for v in field_ids]}
    raw = await request(data, kind, "get-multi", body)
    result = rows(raw, "crmObjects", 1)
    if len(result) != 1 or result[0].get("crmObjectId") != record_id:
        raise ValueError("Vendasta scoped record was not found")
    projected_record(result[0], now)
    return result[0]


async def walk(data, service, body, key, pages, page_size):
    found, seen, seen_cursor = [], set(), set()
    for _ in range(pages):
        raw = await request(data, service, "list", body)
        batch = rows(raw, key, page_size)
        if service == "association" and raw.get("statusCode") != ["200"] * len(batch):
            raise RuntimeError("Vendasta association per-record statuses are unverified")
        state = paging(raw)
        for item in batch:
            marker = item.get("crmObjectId") or item.get("fieldId") or item.get("associationId")
            if not isinstance(marker, str) or marker in seen:
                raise RuntimeError("Vendasta list returned missing or repeated IDs")
            seen.add(marker); found.append(item)
        if not state["has_more"]: break
        if state["next_cursor"] in seen_cursor or state["next_cursor"] == body.get("pagingOptions", {}).get("cursor"):
            raise RuntimeError("Vendasta list repeated its cursor")
        seen_cursor.add(state["next_cursor"])
        body = deepcopy(body)
        body.setdefault("pagingOptions", {})["cursor"] = state["next_cursor"]
    return found, state


async def field_schemas(data, kind, ids):
    now = await current_credential(data)
    raw = await request(data, "field-schema", "get-multi", {"namespace": now["namespace"], "crmObjectType": KINDS[kind], "fieldId": ids})
    values = rows(raw, "fieldSchemas", len(ids))
    if len(values) != len(ids):
        raise RuntimeError("Vendasta field-schema positional response differs")
    for expected, row in zip(ids, values):
        if row.get("fieldId") != expected:
            raise ValueError("Vendasta field schema is missing or differs; select its native fieldId")
        projected_schema(row, KINDS[kind])
        if SECRET_NAME.search(str(row.get("externalId", "")) + str(row.get("fieldName", ""))):
            raise ValueError("Vendasta secret fields are excluded")
    return values


async def writable_fields(data, kind, encoded):
    value = strict_json(encoded)
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise ValueError("Use 1–20 native metadata field values")
    fields = TypeAdapter(list[FieldValue]).validate_python(value)
    ids = [f.fieldId for f in fields]
    if len(set(ids)) != len(ids): raise ValueError("Metadata fields must be distinct")
    now = await current_credential(data)
    schemas = await field_schemas(data, kind, ids)
    allowed = set(csv_ids(now["write_fields_csv"]))
    expected = {"FIELD_TYPE_STRING": "stringValue", "FIELD_TYPE_EMAIL": "stringValue", "FIELD_TYPE_PHONE": "stringValue",
                "FIELD_TYPE_DROPDOWN": "stringValue", "FIELD_TYPE_BOOLEAN": "booleanValue",
                "FIELD_TYPE_INTEGER": "integerValue", "FIELD_TYPE_TAG": "stringValues", "FIELD_TYPE_STRING_LIST": "stringValues"}
    for f, schema in zip(fields, schemas):
        if f.fieldId not in allowed and schema.get("externalId") not in allowed:
            raise ValueError("Vendasta metadata field is outside the saved write grant")
        if schema.get("readonly", False) is not False or schema.get("fieldType") not in expected or getattr(f, expected[schema["fieldType"]]) is None:
            raise ValueError("Use a current writable nonfinancial metadata field with its documented type")
    return [f.model_dump(exclude_none=True) for f in fields], schemas


async def pipeline(data, pipeline_id, kind):
    now = await current_credential(data)
    raw = await request(data, "pipeline", "get-multi", {"namespace": now["namespace"], "pipelineIds": [identifier(pipeline_id)]})
    values = rows(raw, "pipelines", 1)
    if len(values) != 1 or values[0].get("pipelineId") != pipeline_id or values[0].get("namespace") != now["namespace"] or values[0].get("objectType") != KINDS[kind]:
        raise ValueError("Vendasta pipeline namespace or object type differs")
    return values[0]


def common(now):
    return {"status": "success", "read_completed": True, "identity_verified": False,
            "namespace": now["namespace"], "environment": now["environment"]}


async def records(data, arguments):
    cfg = TypeAdapter(Operation).validate_python(arguments).model_dump()
    now = await current_credential(data)
    op = cfg["operation"]
    out = common(now)
    if op in {"check_connection", "list_field_schemas"}:
        kind = cfg.get("object_type", "Contact")
        body = {"namespace": now["namespace"], "crmObjectType": kind, "pagingOptions": {"pageSize": str(cfg.get("page_size", 100))}}
        if cfg.get("cursor"): body["pagingOptions"]["cursor"] = cfg["cursor"]
        if cfg.get("search"): body["searchTerm"] = cfg["search"]
        batch, state = await walk(data, "field-schema", body, "fieldSchemas", cfg.get("max_pages", 1), cfg.get("page_size", 100))
        return {**out, "records": [projected_schema(v, kind) for v in batch], **state}
    if op in {"get_field_schema", "list_field_options"}:
        kind = next(k for k, v in KINDS.items() if v == cfg["object_type"])
        selected = (await field_schemas(data, kind, [identifier(cfg["field_id"])]))[0]
        if op == "get_field_schema": return {**out, "record": projected_schema(selected, cfg["object_type"])}
        require_scope(now, kind, "field-options")
        raw = await request(data, kind, "field-options", {"namespace": now["namespace"], "fieldId": selected["fieldId"],
            "pageSize": str(cfg["page_size"]), "searchTerm": cfg["search"] or ""})
        options = raw.get("options")
        if not isinstance(options, list) or len(options) > cfg["page_size"] or any(not isinstance(v, str) or len(v) > 1000 for v in options):
            raise RuntimeError("Vendasta field options are unverified")
        return {**out, "options": options, "has_more": None, "next_cursor": None}
    if op in {"list_pipelines", "get_pipeline"}:
        kind = next(k for k, v in KINDS.items() if v == cfg["object_type"])
        if op == "get_pipeline": values = [await pipeline(data, cfg["pipeline_id"], kind)]
        else:
            raw = await request(data, "pipeline", "list", {"listOptions": {"namespace": now["namespace"], "objectType": cfg["object_type"]}})
            values = rows(raw, "pipelines")
            if any(v.get("namespace") != now["namespace"] or v.get("objectType") != cfg["object_type"] for v in values):
                raise ValueError("Vendasta pipeline scope differs")
        for value in values:
            identifier(value.get("pipelineId"))
            if not isinstance(value.get("name"), str) or len(value["name"]) > 1000:
                raise RuntimeError("Vendasta pipeline metadata is unverified")
        return {**out, "records": [{k: v[k] for k in ("pipelineId", "name", "namespace", "objectType") if k in v} for v in values], "has_more": False}
    if op in {"list_associations", "get_association"}:
        source, target = cfg["association_type"].split("-")
        from_kind, to_kind = source.lower(), target.lower()
        await get_record(data, from_kind, cfg["from_id"])
        if cfg.get("to_id"): await get_record(data, to_kind, cfg["to_id"])
        if op == "get_association":
            raw = await request(data, "association", "get-multi", {"namespace": now["namespace"], "associationIds": [identifier(cfg["association_id"])]})
            batch, state = rows(raw, "associations", 1), {}
            if raw.get("statusCode") != ["200"] or len(batch) != 1 or batch[0].get("associationId") != cfg["association_id"]:
                raise ValueError("Vendasta association was not returned with per-ID success")
        else:
            filters = [{"fieldId": "association_type", "operator": "FILTER_OPERATOR_IS", "values": [{"string": cfg["association_type"]}]},
                       {"fieldId": "from_id", "operator": "FILTER_OPERATOR_IS", "values": [{"string": cfg["from_id"]}]}]
            if cfg.get("to_id"): filters.append({"fieldId": "to_id", "operator": "FILTER_OPERATOR_IS", "values": [{"string": cfg["to_id"]}]})
            body = {"namespace": now["namespace"], "filtersV2": {"operator": "FILTER_GROUP_OPERATOR_AND", "filters": filters},
                    "pagingOptions": {"pageSize": str(cfg["page_size"])}}
            if cfg.get("cursor"): body["pagingOptions"]["cursor"] = cfg["cursor"]
            batch, state = await walk(data, "association", body, "associations", cfg["max_pages"], cfg["page_size"])
        for row in batch:
            if row.get("associationType") != cfg["association_type"] or row.get("fromId") != cfg["from_id"] or cfg.get("to_id") and row.get("toId") != cfg["to_id"] or not active(row):
                raise ValueError("Vendasta association ancestry or deletion state differs")
            await get_record(data, to_kind, identifier(row.get("toId")))
        return {**out, "records": [{k: row[k] for k in ("associationId", "associationType", "fromId", "toId") if k in row} for row in batch], **state}
    suffix = op.split("_")[-1]
    kind = {"contacts": "contact", "contact": "contact", "companies": "company", "company": "company", "opportunities": "opportunity", "opportunity": "opportunity"}[suffix]
    if op.startswith("list_"):
        body = {"namespace": now["namespace"], "pagingOptions": {"pageSize": str(cfg["page_size"])}}
        if cfg["cursor"]: body["pagingOptions"]["cursor"] = cfg["cursor"]
        if cfg["search"]: body["search"] = {"searchTerm": cfg["search"]}
        if cfg["filters_json"]: body["filtersV2"] = FilterGroup.model_validate(strict_json(cfg["filters_json"])).model_dump(exclude_none=True)
        if cfg["sort_json"]:
            sorts = TypeAdapter(list[SortBy]).validate_python(strict_json(cfg["sort_json"]))
            if len(sorts) > 5: raise ValueError("Use at most five native sort fields")
            body["sortBy"] = [v.model_dump() for v in sorts]
        batch, state = await walk(data, kind, body, "crmObjects", cfg["max_pages"], cfg["page_size"])
        return {**out, "records": [projected_record(v, now) for v in batch], **state}
    if op.startswith("get_"):
        item = await get_record(data, kind, cfg["record_id"], field_ids=csv_ids(now["read_fields_csv"]))
        return {**out, "record": projected_record(item, now)}
    creating = op.startswith("create_")
    restoring = op.startswith("restore_")
    item = None if creating else await get_record(data, kind, cfg["record_id"], include_deleted=restoring)
    if item is not None and active(item) is restoring:
        raise ValueError("Vendasta record has the wrong soft-delete state")
    if op.startswith(("soft_delete_", "restore_")):
        action = "restore" if restoring else "delete"
        raw = await request(data, kind, action, {"namespace": now["namespace"], "crmObjectId": cfg["record_id"]})
        if raw != {}: raise RuntimeError("Vendasta state change returned an unexpected receipt; do not retry")
        checked = await get_record(data, kind, cfg["record_id"], include_deleted=True)
        if active(checked) is not restoring:
            raise RuntimeError("Vendasta soft-delete/restore state readback differs; do not retry")
        return {**out, "mutation_completed": True, "soft_deleted": not restoring, "permanently_erased": False, "record": projected_record(checked, now)}
    fields, schemas = await writable_fields(data, kind, cfg["fields_json"])
    external = {s.get("externalId"): f for f, s in zip(fields, schemas)}
    if creating:
        required = {"contact": {"standard__first_name", "standard__last_name", "standard__email"},
                    "company": {"standard__company_name"}, "opportunity": {"standard__opportunity_name"}}
        if not any(isinstance(external.get(k, {}).get("stringValue"), str) and external[k]["stringValue"].strip() for k in required[kind]):
            raise ValueError("Supply the documented descriptive field for this new record")
        if kind == "opportunity":
            pid = external.get("standard__opportunity_pipeline_id", {}).get("stringValue")
            if not pid: raise ValueError("Select the opportunity's native pipeline field")
            await pipeline(data, pid, kind)
    obj = {"fields": fields}
    body = {"namespace": now["namespace"], "crmObject": obj}
    if not creating:
        obj["crmObjectId"] = cfg["record_id"]
        body["fieldMask"] = {"paths": ["fields." + f["fieldId"] for f in fields]}
    raw = await request(data, kind, "create" if creating else "update", body)
    if creating:
        record_id = identifier(raw.get("crmObjectId"))
    else:
        if raw != {}: raise RuntimeError("Vendasta update returned an unexpected receipt; do not retry")
        record_id = cfg["record_id"]
    try:
        checked = await get_record(data, kind, record_id, field_ids=[f["fieldId"] for f in fields])
        returned = {f.get("fieldId"): f for f in checked.get("fields", []) if isinstance(f, dict)}
        if any(any(returned.get(f["fieldId"], {}).get(k) != v for k, v in f.items()) for f in fields):
            raise RuntimeError("Vendasta metadata readback differs")
    except Exception:
        return {"status": "error", "mutation_accepted": True, "record_id": record_id,
                "readback_completed": False, "error": "Vendasta readback is unverified; retain the record ID and do not retry automatically"}
    return {**out, "mutation_completed": True, "record": projected_record(checked, now), "record_id": record_id}


class VendastaNode(WorkflowNode):
    integration_type = "automation-vendasta"
    connection_evidence = ConnectionEvidence(operation="check_connection", noun="Vendasta CRM field schemas",
        label_keys=("fieldName", "fieldId"), identity_keys=(), proves="reachability")
    scope_registry = ScopeRegistry(provider="vendasta", enforcement=Enforcement.STRICT, requirements={
        op: ScopeRequirement(scopes=(), credential_types=(FAMILY,), note="Supplied issuer scopes are checked per actual CRM method, including read/write alternatives.")
        for op in OPS})
    edit_examples = ["Read scoped CRM contacts, companies and opportunity metadata", "Update explicitly granted fields using the current namespace schema", "Inspect directional record associations"]
    @classmethod
    def get_config_model(cls): return VendastaNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None: credential(config_data["credentials"])
        return super().parse_config(config_data)
    @classmethod
    def validate_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: credential(config_data["credentials"])
            except ValueError: return {"valid": False, "errors": ["Connect a current native Vendasta supplied token"], "satisfied_set": None}
        return super().validate_config(config_data)
    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return credential(credential_data)
    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        ctx = context or {}
        if field_name not in {"record_id", "field_id"}:
            return {"options": [], "has_more": False, "next_page_token": None}
        operation = ctx.get("operation", "")
        if field_name == "field_id":
            args = {"operation": "list_field_schemas", "object_type": ctx.get("object_type", "Contact"), "search": normalize_search(search)}
            key = "fieldId"
        else:
            suffix = operation.split("_")[-1]
            plural = {"contact": "contacts", "company": "companies", "opportunity": "opportunities"}.get(suffix)
            if plural is None: raise ValueError("Select the native record operation before its picker")
            args, key = {"operation": "list_" + plural, "search": normalize_search(search)}, "crmObjectId"
        now = await current_credential(credential_data)
        digest = hashlib.sha256(json.dumps({"args": args, "namespace": now["namespace"], "environment": now["environment"]}, sort_keys=True).encode()).hexdigest()
        if page_token:
            try:
                token = strict_json(base64.urlsafe_b64decode(page_token + "=" * (-len(page_token) % 4)))
            except Exception:
                raise ValueError("Use the native Vendasta picker cursor") from None
            if not isinstance(token, dict) or set(token) != {"query", "cursor"} or token["query"] != digest or not isinstance(token["cursor"], str):
                raise ValueError("Vendasta picker cursor belongs to a different query or namespace")
            args["cursor"] = token["cursor"]
        result = await records(credential_data, args)
        options = [{"value": row[key], "label": row.get("fieldName") or row[key]} for row in result["records"]]
        nxt = base64.urlsafe_b64encode(json.dumps({"query": digest, "cursor": result["next_cursor"]}).encode()).decode().rstrip("=") if result["has_more"] else None
        await current_credential(credential_data)
        return {"options": options, "has_more": result["has_more"], "next_page_token": nxt}
    async def execute(self, inputs: dict) -> dict:
        supplied = self.node_data.get("credentials")
        if supplied is None and self.config.credentials is not None:
            supplied = self.config.credentials.model_dump()
        data = await self.freshen_credential(supplied)
        return await records(data, self.config.config.model_dump())
