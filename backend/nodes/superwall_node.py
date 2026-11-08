"""Native Superwall v2 organization/project metadata and aggregate chart reads.

Supplied organization keys stay in a Bearer header at the fixed public API root.
Safe projections enforce the supplied project restrictions and omit returned credentials/URLs.
"""
from datetime import date, datetime
import json
import math
import re
from typing import Annotated, Literal, Optional, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import normalize_search
from nodes.core.oauth_scopes import Enforcement, ScopeRegistry, ScopeRequirement

FAMILY = "superwall_organization_api_key"
NODE_TYPE = "automation-superwall"
ROOT = "https://api.superwall.com"
READ_SCOPES = {"projects:read", "applications:read", "products:read", "entitlements:read", "charts:read", "access:read"}
OPS = ("check_connection", "get_organization", "list_projects", "get_project", "list_applications", "get_application",
       "list_products", "get_product", "list_entitlements", "get_entitlement", "get_chart_definitions", "query_chart_data")
REQUIRED = {op: {"projects:read"} for op in OPS}
for _op in ("list_applications", "get_application", "get_chart_definitions", "query_chart_data"): REQUIRED[_op].add("applications:read")
for _op in ("list_products", "get_product"): REQUIRED[_op].add("products:read")
for _op in ("list_entitlements", "get_entitlement"): REQUIRED[_op].add("entitlements:read")
for _op in ("get_chart_definitions", "query_chart_data"): REQUIRED[_op].add("charts:read")
# The OAS does not assign a precise scope to organization metadata. The provider
# remains authoritative; this node does not invent a scope grant from that route.
PRESETS = Literal["last_24_hours", "today", "yesterday", "last_7_days", "last_30_days", "last_90_days"]


def resource_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
        raise ValueError("Enter a Superwall resource ID without a URL, path or whitespace")
    return value


def strict_json(value):
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result: raise ValueError("Duplicate JSON key")
            result[key] = item
        return result
    def constant(_): raise ValueError("Nonfinite JSON value")
    try: return json.loads(value, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, TypeError, UnicodeError): raise ValueError("Use valid bounded JSON") from None


def granted_projects(value):
    if not isinstance(value, str) or len(value) > 15000: raise ValueError("Enter approved project IDs as a JSON string array")
    raw = strict_json(value)
    if not isinstance(raw, list) or not 1 <= len(raw) <= 50: raise ValueError("Approve one to 50 projects")
    result = [resource_id(item) for item in raw]
    if len(set(result)) != len(result): raise ValueError("Approve distinct project IDs")
    return result


def read_scopes(value):
    if not isinstance(value, str) or len(value) > 500: raise ValueError("Enter documented read scopes separated by spaces")
    result = value.split()
    if not result or not set(result) <= READ_SCOPES or len(set(result)) != len(result):
        raise ValueError("Use distinct documented Superwall read scopes")
    return set(result)


class SuperwallOrganizationAPIKeyCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="Superwall Organization API Key",
        json_schema_extra={"x-credential-instructions": "Enter an issued organization key, its organization ID, approved project IDs and documented read scopes. These saved restrictions narrow this node and do not establish vendor permissions.", "x-help-url": "https://superwall.com/docs/dashboard/dashboard-settings/overview-settings-access-controls"})
    credential_type: Literal["superwall_organization_api_key"] = Field(FAMILY, json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="Organization API Key", json_schema_extra={"ui:widget": "password", "ui:sensitive": True})
    organization_id: str = Field(..., title="Organization ID", description="The numeric organization ID returned with your projects. It is checked against the provider, not decoded from the key.")
    allowed_project_ids_json: str = Field(..., title="Approved Project IDs", description="JSON string array of existing projects allowed for this workflow. Maximum 50 is a NoClick limit.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})
    witness_project_id: str = Field(..., title="Connection Witness Project ID", description="One approved project for a protected read-only connection check.")
    read_scopes: str = Field("projects:read", title="Read Scopes", description="Space-separated issued read scopes. Saved labels constrain this node; the provider independently checks actual key scopes and project access.")
    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="Organization API Key")
        if not value or len(value) > 4096 or any(ord(c) < 33 or ord(c) > 126 for c in value): raise ValueError("Enter the issued key without a Bearer prefix or whitespace")
        return value
    @field_validator("organization_id")
    @classmethod
    def org(cls, value):
        if not re.fullmatch(r"[0-9]{1,18}", value) or int(value) < 1: raise ValueError("Enter a positive numeric organization ID")
        return str(int(value))
    @field_validator("allowed_project_ids_json")
    @classmethod
    def projects(cls, value):
        granted_projects(value)
        return value
    @field_validator("witness_project_id")
    @classmethod
    def witness(cls, value): return resource_id(value)
    @field_validator("read_scopes")
    @classmethod
    def scopes(cls, value):
        read_scopes(value)
        return value


def credential(data):
    if not isinstance(data, dict) or data.get("credential_type") != FAMILY: raise ValueError("Connect a native Superwall organization API key")
    if any(key in data for key in ("access_token", "refresh_token", "base_url", "host", "cookie", "client_id")): raise ValueError("Use only the native Superwall organization-key form")
    try:
        now = SuperwallOrganizationAPIKeyCredential.model_validate(data).model_dump()
        if now["witness_project_id"] not in granted_projects(now["allowed_project_ids_json"]): raise ValueError("Unapproved witness")
        return now
    except ValueError: raise ValueError("Complete the native Superwall key, organization, project and read-scope form") from None


def require_scopes(now, operation):
    if operation not in REQUIRED or not REQUIRED[operation] <= read_scopes(now["read_scopes"]):
        raise ValueError("The saved read-scope restriction does not allow this Superwall operation")


def dynamic(name, parent=None):
    spec = {"field_name": name, "searchable": True, "allow_custom": True}
    if parent: spec["depends_on"] = parent
    return {"x-resource-type": "superwall_" + name.removesuffix("_id"), "x-dynamic-options": spec}


class NativeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class CheckConnection(NativeModel):
    operation: Literal["check_connection"] = "check_connection"


class GetOrganization(NativeModel):
    operation: Literal["get_organization"] = "get_organization"


class Paged(NativeModel):
    limit: int = Field(50, strict=True, ge=1, le=100, description="NoClick page-size bound; the OAS does not state the server maximum.")
    starting_after: Optional[str] = Field(None, description="Documented forward resource-ID cursor. Filters are repeated on every page.")
    max_pages: int = Field(1, strict=True, ge=1, le=3, description="NoClick request bound, not a vendor quota.")
    @field_validator("starting_after")
    @classmethod
    def cursor(cls, value): return resource_id(value) if value is not None else None


class ListProjects(Paged):
    operation: Literal["list_projects"] = "list_projects"
    archived: Optional[bool] = Field(None, strict=True)


class ProjectSelection(NativeModel):
    project_id: str = Field(..., title="Project", json_schema_extra=dynamic("project_id"))
    @field_validator("project_id")
    @classmethod
    def project(cls, value): return resource_id(value)


class GetProject(ProjectSelection):
    operation: Literal["get_project"] = "get_project"


class ListApplications(ProjectSelection):
    operation: Literal["list_applications"] = "list_applications"


class ApplicationSelection(ProjectSelection):
    application_id: str = Field(..., title="Application", json_schema_extra=dynamic("application_id", "project_id"))
    @field_validator("application_id")
    @classmethod
    def application(cls, value): return resource_id(value)


class GetApplication(ApplicationSelection):
    operation: Literal["get_application"] = "get_application"


class ListProducts(ProjectSelection, Paged):
    operation: Literal["list_products"] = "list_products"
    platform: Optional[Literal["ios", "android", "stripe", "promotional", "custom"]] = None


class GetProduct(ProjectSelection):
    operation: Literal["get_product"] = "get_product"
    product_id: str = Field(..., title="Product", json_schema_extra=dynamic("product_id", "project_id"))
    @field_validator("product_id")
    @classmethod
    def product(cls, value): return resource_id(value)


class ListEntitlements(ProjectSelection, Paged):
    operation: Literal["list_entitlements"] = "list_entitlements"


class GetEntitlement(ProjectSelection):
    operation: Literal["get_entitlement"] = "get_entitlement"
    entitlement_id: str = Field(..., title="Entitlement Definition", json_schema_extra=dynamic("entitlement_id", "project_id"))
    @field_validator("entitlement_id")
    @classmethod
    def entitlement(cls, value): return resource_id(value)


class GetChartDefinitions(ApplicationSelection):
    operation: Literal["get_chart_definitions"] = "get_chart_definitions"


class QueryChartData(ApplicationSelection):
    operation: Literal["query_chart_data"] = "query_chart_data"
    chart_key: str = Field(..., title="Chart Definition", json_schema_extra=dynamic("chart_key", "application_id"))
    date_preset: PRESETS = "last_7_days"
    max_data_points: int = Field(100, strict=True, ge=1, le=1000, description="NoClick requested bound. An aggregate chart does not prove a complete raw dataset.")
    @field_validator("chart_key")
    @classmethod
    def chart(cls, value): return resource_id(value)


Operation = Annotated[Union[CheckConnection, GetOrganization, ListProjects, GetProject, ListApplications, GetApplication,
    ListProducts, GetProduct, ListEntitlements, GetEntitlement, GetChartDefinitions, QueryChartData], Field(discriminator="operation")]


class SuperwallNodeConfig(NodeConfig[Operation, SuperwallOrganizationAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class Projection(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)


class Identified(Projection):
    id: str
    @field_validator("id")
    @classmethod
    def identifier(cls, value): return resource_id(value)


class Application(Identified):
    project_id: Optional[str]
    name: str
    platform: Literal["ios", "android", "flutter", "react_native", "web", "promotional", "webapp"]
    created_at: str
    updated_at: str
    integrated: bool
    globally_disabled: bool
    slug: str
    archived_at: Optional[str]
    bundle_id: Optional[str]


class Project(Identified):
    object: Literal["project"]
    name: str
    organization_id: int
    applications: list[Application] = Field(max_length=500)
    created_at: str
    updated_at: str
    archived: bool


class Organization(Projection):
    object: Literal["organization"]
    id: int
    name: str
    can_manage: bool = Field(exclude=True)


class Product(Identified):
    object: Literal["product"]
    project_id: str
    application_id: str
    identifier: str
    name: Optional[str]
    platform: Literal["ios", "android", "stripe", "promotional", "custom"]
    store: Optional[Literal["app_store", "play_store", "custom"]]
    entitlements: list[str] = Field(max_length=1000)
    created_at: str
    updated_at: str
    @field_validator("entitlements")
    @classmethod
    def references(cls, value): return [resource_id(item) for item in value]


class Entitlement(Identified):
    object: Literal["entitlement"]
    project_id: str
    application_id: str
    identifier: str
    name: Optional[str]
    products: list[str] = Field(max_length=1000)
    created_at: str
    updated_at: str
    @field_validator("products")
    @classmethod
    def references(cls, value): return [resource_id(item) for item in value]


class Listed(Projection):
    object: Literal["list"]
    url: str
    has_more: bool
    data: list[dict] = Field(max_length=100)


class Axis(Projection):
    key: str
    name: str
    value_type: Literal["number", "percentage", "currency", "date", "string"]


class ChartType(Projection):
    key: str
    name: str
    x_axis: str
    y_axis: str
    date_dimension: Literal["purchaseDate", "installDate", "firstPurchaseDate", "tsDate", "mrrDate"]


class ChartDefinitions(Projection):
    object: Literal["chart_definitions"]
    x_axis: list[Axis] = Field(max_length=200)
    y_axis: list[Axis] = Field(max_length=200)
    chart_types: list[ChartType] = Field(max_length=200)
    # Arbitrary returned filters, include fields and enriched values are omitted.


class Series(Projection):
    key: Optional[str]
    breakdown: str = Field(exclude=True)


class ChartValue(Projection):
    y: float
    @field_validator("y")
    @classmethod
    def finite(cls, value):
        if not math.isfinite(value): raise ValueError("Use a finite chart value")
        return value


class ChartPoint(Projection):
    x: str
    incomplete: bool
    values: dict[str, ChartValue] = Field(max_length=100)
    @field_validator("x")
    @classmethod
    def date_axis(cls, value):
        if len(value) > 100: raise ValueError("Use a bounded date-axis value")
        # A native privacy restriction: expose only parseable dates on a date axis.
        try: date.fromisoformat(value)
        except ValueError: datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class ChartData(Projection):
    object: Literal["chart_data"]
    data: list[ChartPoint] = Field(max_length=1000)
    series: list[Series] = Field(max_length=100)
    x_axis: Axis
    y_axis: Axis


async def current_credential(data):
    # Staging resolves saved credentials before execute and picker calls. Native
    # organization keys do not expire or require a provider refresh operation.
    return credential(data)


async def request(data, path, *, params=None, body=None):
    now = await current_credential(data)
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            async with client.stream("POST" if body is not None else "GET", ROOT + path,
                headers={"Authorization": "Bearer " + now["api_key"], "Accept": "application/json", **({"Content-Type": "application/json"} if body is not None else {})},
                params=params, **({"json": body} if body is not None else {})) as response:
                await current_credential(data)
                status = response.status_code
                if status in {400, 401, 403, 404}: raise ValueError(f"Superwall refused the metadata read (HTTP {status})")
                if status != 200: raise RuntimeError(f"Superwall metadata read did not complete (HTTP {status}); no automatic retry")
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json": raise RuntimeError("Superwall returned an unexpected response type")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 2_000_000: raise RuntimeError("Superwall response exceeds the native metadata limit")
                await current_credential(data)
    except httpx.HTTPError: raise RuntimeError("Superwall metadata transport did not complete; no automatic retry") from None
    try: return strict_json(bytes(content))
    except ValueError: raise RuntimeError("Superwall returned invalid JSON") from None


def typed(model, raw):
    try: return model.model_validate(raw)
    except ValueError: raise RuntimeError("Superwall returned unverified metadata") from None


def verify_project(now, row, selected=None):
    if row.organization_id != int(now["organization_id"]) or row.id not in granted_projects(now["allowed_project_ids_json"]) or (selected is not None and row.id != selected):
        raise RuntimeError("Superwall project does not match the saved organization/project scope")
    ids = [app.id for app in row.applications]
    if len(set(ids)) != len(ids) or any(app.project_id not in {None, row.id} for app in row.applications):
        raise RuntimeError("Superwall returned repeated or foreign applications")
    return row


async def project_witness(data, selected, operation):
    now = await current_credential(data)
    require_scopes(now, operation)
    selected = resource_id(selected)
    if selected not in granted_projects(now["allowed_project_ids_json"]): raise ValueError("Project is outside the saved approved-project list")
    row = typed(Project, await request(data, "/v2/projects/" + selected))
    verify_project(now, row, selected)
    await current_credential(data)
    return row


def child_member(row, project):
    apps = {app.id for app in project.applications if app.project_id == project.id}
    if row.project_id != project.id or row.application_id not in apps:
        raise RuntimeError("Superwall child resource does not belong to the witnessed project/application")
    return row


def project_output(row):
    result = row.model_dump()
    for app in result["applications"]: app["project_link_verified"] = app["project_id"] == row.id
    return result


async def application_witness(data, project, selected):
    now = await current_credential(data)
    selected = resource_id(selected)
    if not any(app.id == selected and app.project_id == project.id for app in project.applications):
        raise ValueError("Application is outside the witnessed project")
    row = typed(Application, await request(data, "/v2/projects/applications/" + selected, params={"organization_id": now["organization_id"]}))
    if row.id != selected or row.project_id != project.id: raise RuntimeError("Superwall application does not match its project witness")
    await current_credential(data)
    return row


async def list_metadata(data, cfg, project=None):
    now = await current_credential(data)
    require_scopes(now, cfg.operation)
    kind, path, model = {"list_projects": ("projects", "/v2/projects", Project), "list_products": ("products", "/v2/products", Product),
                         "list_entitlements": ("entitlements", "/v2/entitlements", Entitlement)}[cfg.operation]
    params = {"limit": str(cfg.limit), **({"organization_id": now["organization_id"]} if kind == "projects" else {"project_id": project.id})}
    if kind == "projects" and cfg.archived is not None: params["archived"] = "true" if cfg.archived else "false"
    if kind == "products" and cfg.platform is not None: params["platform"] = cfg.platform
    cursor = cfg.starting_after
    if kind == "projects" and cursor is not None and cursor not in granted_projects(now["allowed_project_ids_json"]):
        raise ValueError("Project cursor is outside the approved-project list")
    rows, seen, cursors = [], set(), set()
    if cursor: cursors.add(cursor)
    for index in range(cfg.max_pages):
        page = typed(Listed, await request(data, path, params={**params, **({"starting_after": cursor} if cursor else {})}))
        if page.url != path or len(page.data) > cfg.limit or (page.has_more and not page.data): raise RuntimeError("Superwall returned an unverified list envelope or empty continuation")
        for raw in page.data:
            row = typed(model, raw)
            if kind == "projects": verify_project(now, row)
            else: child_member(row, project)
            if row.id in seen or row.id in cursors: raise RuntimeError("Superwall repeated a resource/cursor; completion is unverified")
            seen.add(row.id)
            rows.append(project_output(row) if kind == "projects" else row.model_dump())
        cursor = rows[-1]["id"] if page.has_more else None
        if cursor:
            if cursor in cursors: raise RuntimeError("Superwall cursor did not advance")
            cursors.add(cursor)
        await current_credential(data)
        if not page.has_more: break
    return {"status": "success", "object": "list", "data": rows, "has_more": page.has_more,
            "next_starting_after": cursor, "pages_read": index + 1,
            "complete_from_first_page": cfg.starting_after is None and not page.has_more, "identity_verified": False}


async def chart_definitions(data, app):
    result = typed(ChartDefinitions, await request(data, "/v2/charts/definitions", params={"application_id": app.id}))
    for rows in (result.x_axis, result.y_axis, result.chart_types):
        keys = [row.key for row in rows]
        if len(set(keys)) != len(keys): raise RuntimeError("Superwall returned repeated chart definitions")
    await current_credential(data)
    return result


async def query_chart(data, cfg, app):
    definitions = await chart_definitions(data, app)
    chosen = [row for row in definitions.chart_types if row.key == cfg.chart_key]
    if len(chosen) != 1: raise ValueError("Select an actual chart definition for this application")
    selected = chosen[0]
    axes = [row for row in definitions.x_axis if row.key == selected.x_axis]
    values = [row for row in definitions.y_axis if row.key == selected.y_axis]
    if len(axes) != 1 or axes[0].value_type != "date" or len(values) != 1 or values[0].value_type not in {"number", "percentage", "currency"}:
        raise ValueError("Select a documented aggregate chart with a date axis")
    result = typed(ChartData, await request(data, "/v2/charts/data", body={"application_id": app.id, "x_axis": selected.x_axis,
        "y_axis": selected.y_axis, "date_filter": {"dimension": selected.date_dimension, "preset": cfg.date_preset},
        "date_interval": "day", "breakdown": None, "max_data_points": cfg.max_data_points}))
    if result.x_axis.key != selected.x_axis or result.x_axis.value_type != "date" or result.y_axis.key != selected.y_axis or result.y_axis.value_type != values[0].value_type or len(result.data) > cfg.max_data_points:
        raise RuntimeError("Superwall chart response does not match the selected aggregate/date contract")
    known = [row.key for row in result.series if row.key is not None]
    if len(set(known)) != len(known): raise RuntimeError("Superwall returned repeated chart series")
    nullable = any(row.key is None for row in result.series)
    keys = []
    mapping_verified = True
    # Series identifiers/enriched_data/filter values can contain sensitive strings.
    # Output only numeric values with ordinal series positions, never those labels.
    points = []
    for point in result.data:
        for key in point.values:
            if key not in known:
                if not nullable: raise RuntimeError("Superwall returned unknown chart series")
                mapping_verified = False  # The OAS does not define null-key encoding.
            if key not in keys: keys.append(key)
        if len(keys) > 100: raise RuntimeError("Superwall chart exceeds the native series bound")
        points.append({"x": point.x, "incomplete": point.incomplete,
            "values": [{"series_ordinal": keys.index(key), "y": value.y} for key, value in point.values.items()]})
    await current_credential(data)
    return {"status": "success", "object": "chart_data", "data": points,
        "x_axis": result.x_axis.model_dump(), "y_axis": result.y_axis.model_dump(), "series_count": len(keys), "series_mapping_verified": mapping_verified,
        "contains_incomplete": any(point["incomplete"] for point in points), "completion_verified": False, "identity_verified": False}


class SuperwallNode(WorkflowNode):
    integration_type = "automation-superwall"
    connection_evidence = ConnectionEvidence(operation="check_connection", noun="Superwall project witness",
        label_keys=("name", "id"), identity_keys=(), proves="reachability")
    scope_registry = ScopeRegistry(provider="superwall", enforcement=Enforcement.STRICT,
        requirements={op: ScopeRequirement(scopes=tuple(sorted(REQUIRED[op])), credential_types=(FAMILY,),
            note="Documented organization-key read scope names; saved labels narrow this node, while provider scopes/project access remain authoritative.") for op in OPS})
    edit_examples = ["Read products and entitlement definitions for an approved project", "Query an application's aggregate chart with a bounded date range"]
    @classmethod
    def get_config_model(cls): return SuperwallNodeConfig
    @classmethod
    def parse_config(cls, config_data):
        if config_data.get("credentials") is not None: credential(config_data["credentials"])
        return super().parse_config(config_data)
    @classmethod
    def validate_config(cls, config_data):
        if config_data.get("credentials") is not None:
            try: credential(config_data["credentials"])
            except ValueError: return {"valid": False, "errors": ["Complete the native Superwall credential form"], "satisfied_set": None}
        return super().validate_config(config_data)
    @classmethod
    async def validate_credential_access(cls, data):
        try:
            now = credential(data)
            await project_witness(now, now["witness_project_id"], "check_connection")
        except ValueError:
            return {"valid": False, "error": "Superwall refused project-witness access"}
        except Exception:
            return {"valid": None, "error": "Superwall project-witness access could not be judged"}
        return {"valid": True, "proves": "reachability", "identity_verified": False}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        context = context if isinstance(context, dict) else {}
        now = await current_credential(credential_data)
        if field_name == "project_id":
            if page_token: raise ValueError("Saved Superwall projects have no paging cursor")
            options = [{"value": item, "label": item} for item in granted_projects(now["allowed_project_ids_json"])]
            more, token = False, None
        elif field_name in {"application_id", "product_id", "entitlement_id", "chart_key"}:
            operation = {"application_id": "list_applications", "product_id": "list_products", "entitlement_id": "list_entitlements", "chart_key": "get_chart_definitions"}[field_name]
            project = await project_witness(credential_data, context.get("project_id"), operation)
            if field_name == "application_id":
                if page_token: raise ValueError("Project applications have no documented paging cursor")
                options = [{"value": app.id, "label": app.name or app.id} for app in project.applications if app.project_id == project.id]
                more, token = False, None
            elif field_name == "chart_key":
                if page_token: raise ValueError("Chart definitions have no documented paging cursor")
                app = await application_witness(credential_data, project, context.get("application_id"))
                defs = await chart_definitions(credential_data, app)
                options = [{"value": row.key, "label": row.name or row.key} for row in defs.chart_types]
                more, token = False, None
            else:
                model = ListProducts if field_name == "product_id" else ListEntitlements
                result = await list_metadata(credential_data, model(project_id=project.id, starting_after=page_token, max_pages=1), project)
                options = [{"value": row["id"], "label": row["name"] or row["identifier"]} for row in result["data"]]
                more, token = result["has_more"], result["next_starting_after"]
        else: return {"options": [], "has_more": False, "next_page_token": None}
        term = (normalize_search(search) or "").casefold()
        if term: options = [row for row in options if term in (row["label"] + " " + row["value"]).casefold()]
        await current_credential(credential_data)
        return {"options": options, "has_more": more, "next_page_token": token}
    async def execute(self, inputs: dict) -> dict:
        supplied = self.node_data.get("credentials")
        if "credentials" not in self.node_data and self.config.credentials is not None:
            supplied = self.config.credentials.model_dump()
        data = credential(supplied)
        cfg = self.config.config
        now = await current_credential(data)
        require_scopes(now, cfg.operation)
        if isinstance(cfg, ListProjects): return await list_metadata(data, cfg)
        project = await project_witness(data, now["witness_project_id"] if isinstance(cfg, (CheckConnection, GetOrganization)) else cfg.project_id, cfg.operation)
        if isinstance(cfg, CheckConnection): return {"status": "success", "witness_verified": True, "projects": [project_output(project)], "identity_verified": False}
        if isinstance(cfg, GetOrganization):
            row = typed(Organization, await request(data, "/v2/organizations/" + now["organization_id"]))
            if row.id != int(now["organization_id"]): raise RuntimeError("Superwall returned a foreign organization")
            await current_credential(data)
            return {"status": "success", "organization": row.model_dump(), "identity_verified": False}
        if isinstance(cfg, GetProject): return {"status": "success", "project": project_output(project), "identity_verified": False}
        if isinstance(cfg, ListApplications): return {"status": "success", "applications": project_output(project)["applications"], "has_more": False, "identity_verified": False}
        if isinstance(cfg, (ListProducts, ListEntitlements)): return await list_metadata(data, cfg, project)
        if isinstance(cfg, (GetProduct, GetEntitlement)):
            model, kind, selected = (Product, "products", cfg.product_id) if isinstance(cfg, GetProduct) else (Entitlement, "entitlements", cfg.entitlement_id)
            row = child_member(typed(model, await request(data, "/v2/" + kind + "/" + selected)), project)
            if row.id != selected: raise RuntimeError("Superwall returned an unexpected resource ID")
            await current_credential(data)
            return {"status": "success", "data": row.model_dump(), "identity_verified": False}
        app = await application_witness(data, project, cfg.application_id)
        if isinstance(cfg, GetApplication): return {"status": "success", "application": app.model_dump(), "identity_verified": False}
        if isinstance(cfg, GetChartDefinitions): return {"status": "success", **(await chart_definitions(data, app)).model_dump(), "identity_verified": False}
        if isinstance(cfg, QueryChartData): return await query_chart(data, cfg, app)
        raise ValueError("Use a native Superwall metadata read")
