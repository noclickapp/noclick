"""Native protected Planday portal/HR/scheduling reads with supplied Bearer.

No setup, OAuth callbacks, token exchange, special HR fields or write routes.
"""
from __future__ import annotations
import json
import logging
import re
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Annotated, Any, Literal, Optional, Union

import httpx
from opentelemetry.instrumentation.utils import suppress_http_instrumentation
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_serializer, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.credentials import resolve_credential_with_owner_fallback
from utils.ssrf import guarded_async_client

TYPE = "planday_access_token"
API = "https://openapi.planday.com"
AUTH_KEY = "_planday_authority"
CURRENT_ORGANIZATION = object()
MAX_BODY = 4 * 1024 * 1024
UNAVAILABLE = "Planday credential is unavailable or its current authority changed"
UNVERIFIED = "Planday response could not be verified"


def secret(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 16384 or any(c.isspace() or ord(c) < 33 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value) or value.lower().startswith(("http:", "https:", "bearer ", "basic ")):
        raise ValueError("Enter the issued value without a URL, whitespace or authentication prefix")
    return value


def calendar_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Use YYYY-MM-DD")
    date.fromisoformat(value)
    return value


def instant(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Use an ISO datetime with an explicit timezone")
    if datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
        raise ValueError("An explicit timezone is required")
    return value


ID = Annotated[StrictInt, Field(ge=1, le=9007199254740991)]
Offset = Annotated[StrictInt, Field(ge=0, le=2147483647)]
Limit = Annotated[StrictInt, Field(ge=1, le=50)]
Date = Annotated[StrictStr, BeforeValidator(calendar_date), Field(min_length=10, max_length=10)]
Instant = Annotated[StrictStr, BeforeValidator(instant), Field(max_length=64)]
Text = Annotated[StrictStr, Field(max_length=65536)]


class PlandayAccessTokenCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="Planday Access Token", json_schema_extra={
        "x-credential-type": "api_key", "x-credential-help-url": "https://developer.planday.com/gettingstarted/authorization/",
        "x-credential-instructions": "Supply an already issued access token and its exact client ID. Calls send X-ClientId and Authorization: Bearer to openapi.planday.com. Connection reads protected portal info; it proves a portal resource, not human identity or every permission. Reads require department:read, employeegroup:read, employee:read and shift:read where used. No app creation, consent, refresh exchange or generic OAuth callback is performed. Documented access lifetime is one hour; replace expired tokens through their issuing flow.",
    })
    credential_type: Literal["planday_access_token"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    client_id: Annotated[StrictStr, BeforeValidator(secret)] = Field(..., title="Client ID", repr=False, json_schema_extra={"ui:widget": "password"})
    access_token: Annotated[StrictStr, BeforeValidator(secret)] = Field(..., title="Access Token", repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: Optional[Instant] = Field(None, title="Access Token Expiry", description="Optional exact issuer expiry with timezone. An expired value prevents any API request; no expiry is invented from the time of entry.")
    expected_portal_id: Optional[Annotated[StrictStr, Field(pattern=r"^[1-9][0-9]{0,15}$", max_length=16)]] = Field(None, title="Expected Portal ID", description="Optional exact protected /portal/v1.0/info data.id, checked before accepting other operation results.")

    @model_serializer(mode="wrap")
    def connect_tag(self, handler):
        return {**handler(self), "credential_type": TYPE}


def credential(raw):
    if not isinstance(raw, dict) or raw.get("credential_type") != TYPE:
        raise ValueError("Planday requires its original supplied access-token credential")
    try:
        return PlandayAccessTokenCredential.model_validate(raw)
    except Exception:
        raise ValueError("Planday credential fields are invalid") from None


def raw_guard(data):
    if isinstance(data, dict) and data.get("credentials") is not None:
        raw = data["credentials"]
        if not isinstance(raw, dict) or raw.get("credential_type") != TYPE:
            raise ValueError("Planday credential type is not supported")


def op(value, title, description):
    return Field(value, title=title, description=description, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "Workforce Metadata", "x-is-trigger": False})


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class GetPortalInfo(Config):
    operation: Literal["get_portal_info"] = op("get_portal_info", "Get Portal Info", "Read actual protected portal ID, name, company name, country and timezone. Child portals and aliases are not traversed.")


class Page(Config):
    offset: Offset = Field(0, title="Offset", description="One provider offset page, maximum 2,147,483,647; no automatic traversal or snapshot guarantee.")
    limit: Limit = Field(50, title="Page Size", description="Local and HR maximum is 50. Scheduling allows more, but this node also limits it to 50.")


class ListDepartments(Page):
    operation: Literal["list_departments"] = op("list_departments", "List Departments", "Read one department metadata page; department:read.")


class GetDepartment(Config):
    operation: Literal["get_department"] = op("get_department", "Get Department", "Read exact department ID; department:read.")
    department_id: ID = Field(..., title="Department ID", description="Known exact ID or a current actor-bound picker result.", json_schema_extra={"x-dynamic-options": True})


class ListEmployeeGroups(Page):
    operation: Literal["list_employee_groups"] = op("list_employee_groups", "List Employee Groups", "Read one employee-group page; employeegroup:read.")


class GetEmployeeGroup(Config):
    operation: Literal["get_employee_group"] = op("get_employee_group", "Get Employee Group", "Read exact employee group ID; employeegroup:read.")
    employee_group_id: ID = Field(..., title="Employee Group ID", json_schema_extra={"x-dynamic-options": True})


class ListEmployees(Page):
    operation: Literal["list_employees"] = op("list_employees", "List Employee Metadata", "Read active employee IDs and department/group/type bindings, omitting personal and special fields; employee:read.")


class GetEmployee(Config):
    operation: Literal["get_employee"] = op("get_employee", "Get Employee Metadata", "Read exact employee ID and business profile only; no custom/special fields; employee:read.")
    employee_id: ID = Field(..., title="Employee ID", json_schema_extra={"x-dynamic-options": True})


class ListDepartmentEmployees(Config):
    operation: Literal["list_department_employees"] = op("list_department_employees", "List Department Employee IDs", "Read a protected department first, then its documented unpaged employee-ID relation; no pagination query is invented. Maximum 500 IDs accepted locally.")
    department_id: ID = Field(..., title="Department ID", json_schema_extra={"x-dynamic-options": True})


class ListShifts(Page):
    operation: Literal["list_shifts"] = op("list_shifts", "List Department Shift Metadata", "Read one department-scoped scheduling page within a required local date window, at most 31 inclusive days; shift:read. No punchclock details, comments or costs.")
    department_id: ID = Field(..., title="Department ID", json_schema_extra={"x-dynamic-options": True})
    date_from: Date = Field(..., title="From Date")
    date_to: Date = Field(..., title="To Date")

    @model_validator(mode="after")
    def bounded_dates(self):
        days = (date.fromisoformat(self.date_to) - date.fromisoformat(self.date_from)).days
        if not 0 <= days <= 30:
            raise ValueError("Choose a chronological window of at most 31 inclusive calendar days")
        return self


class GetShift(Config):
    operation: Literal["get_shift"] = op("get_shift", "Get Department Shift Metadata", "Read exact shift ID and independently verify returned department parent; shift:read.")
    department_id: ID = Field(..., title="Department ID", json_schema_extra={"x-dynamic-options": True})
    shift_id: ID = Field(..., title="Shift ID", description="Exact ID from List Department Shift Metadata; custom entry only.")


OPERATIONS = (GetPortalInfo, ListDepartments, GetDepartment, ListEmployeeGroups, GetEmployeeGroup, ListEmployees, GetEmployee, ListDepartmentEmployees, ListShifts, GetShift)
PlandayConfig = Annotated[Union[GetPortalInfo, ListDepartments, GetDepartment, ListEmployeeGroups, GetEmployeeGroup, ListEmployees, GetEmployee, ListDepartmentEmployees, ListShifts, GetShift], Field(discriminator="operation")]


class PlandayNodeConfig(NodeConfig[PlandayConfig, PlandayAccessTokenCredential]):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    node_type: Literal["automation-planday"] = "automation-planday"


@dataclass(eq=False)
class Authority:
    credential: PlandayAccessTokenCredential = field(repr=False)
    pool: Any = field(default=None, repr=False)
    user_id: Any = None
    credential_id: Any = None
    organization_id: Any = None
    workflow_id: Any = None
    anchor: Any = field(default=None, repr=False)
    resolve_organization: bool = False

    @classmethod
    async def create(cls, raw, *, pool=None, user_id=None, credential_id=None, organization_id=CURRENT_ORGANIZATION, workflow_id=None):
        shaped = credential(raw)
        if credential_id and not user_id:
            raise ValueError(UNAVAILABLE)
        current = cls(shaped, pool, user_id, credential_id, organization_id, workflow_id, resolve_organization=organization_id is CURRENT_ORGANIZATION)
        if credential_id:
            if pool is None:
                from utils.database_pool import get_native_pool
                current.pool = get_native_pool()
            if current.resolve_organization:
                current.organization_id = await current.current_organization()
            current.credential, current.anchor = await current.load()
        current.check_expiry()
        return current

    async def current_organization(self):
        from wss.handlers.workflow_handler import get_user_org_context
        async with self.pool.acquire() as conn:
            return await get_user_org_context(conn, self.user_id)

    async def load(self):
        # Staging's canonical resolver handles access and workflow fallback.
        # Its interface exposes credential values, not row/approval revisions.
        raw = await resolve_credential_with_owner_fallback(
            self.credential_id, self.user_id, self.pool,
            org_id=self.organization_id, workflow_id=self.workflow_id,
        )
        if not raw:
            raise ValueError(UNAVAILABLE)
        shaped = credential(raw)
        return shaped, shaped.model_dump()

    def check_expiry(self):
        expires = self.credential.expires_at
        if expires is not None and datetime.fromisoformat(expires.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            raise ValueError("Planday supplied access token has expired; replace it through its original issuing flow")

    async def require_current(self):
        self.check_expiry()
        if self.credential_id:
            if self.resolve_organization and await self.current_organization() != self.organization_id:
                raise ValueError(UNAVAILABLE)
            latest, anchor = await self.load()
            if latest != self.credential or anchor != self.anchor:
                raise ValueError(UNAVAILABLE)




_PRIVATE = ContextVar("planday_private_transport", default=False)


class _PrivateFilter(logging.Filter):
    def filter(self, record):
        if _PRIVATE.get():
            record.msg, record.args = "Planday transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_FILTER = _PrivateFilter()


class ApiError(ValueError):
    def __init__(self, status):
        self.status_code = status
        super().__init__(f"Planday returned HTTP {status}; inspect the current supplied token, client ID, resource access and provider limits")


class OutcomeUnverified(RuntimeError):
    pass


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result




async def request(auth, route, parameters=None):
    """Fixed host, closed GET routes, private scoped diagnostics, no retries."""
    if not re.fullmatch(r"portal/v1\.0/info|hr/v1\.0/(?:departments|employeegroups)(?:/[1-9][0-9]{0,15}(?:/employees)?)?|hr/v1\.0/employees(?:/[1-9][0-9]{0,15})?|scheduling/v1\.0/shifts(?:/[1-9][0-9]{0,15})?", route):
        raise ValueError("Unsupported Planday route")
    await auth.require_current()
    names = {"httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"}
    names |= {name for name in logging.Logger.manager.loggerDict if name.startswith(("httpx.", "httpcore."))}
    for name in names:
        logging.getLogger(name).addFilter(_FILTER)
    private = _PRIVATE.set(True)
    try:
        with suppress_http_instrumentation():
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                async with client.stream("GET", API + "/" + route, params=parameters, headers={"Accept": "application/json", "X-ClientId": auth.credential.client_id, "Authorization": "Bearer " + auth.credential.access_token}) as response:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        await auth.require_current()
                        raw.extend(chunk)
                        if len(raw) > MAX_BODY:
                            raise OutcomeUnverified("Planday response exceeds the local 4 MiB bound; narrow the documented filters")
                    await auth.require_current()
                    if response.status_code != 200:
                        raise ApiError(response.status_code)
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() not in {"application/json", "text/json", "text/plain"}:
                        raise OutcomeUnverified(UNVERIFIED)
                    try:
                        return json.loads(raw, object_pairs_hook=strict_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    except (ValueError, UnicodeError, RecursionError):
                        raise OutcomeUnverified(UNVERIFIED) from None
    except httpx.RequestError:
        await auth.require_current()
        raise OutcomeUnverified("Planday transport outcome is unverified") from None
    finally:
        _PRIVATE.reset(private)



class Response(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, hide_input_in_errors=True)


class Portal(Response):
    id: ID
    name: Text
    companyName: Text
    country: Optional[Text] = None
    timeZone: Optional[Text] = None


class Department(Response):
    id: ID
    name: Text
    number: Optional[Text] = None


class EmployeeGroup(Response):
    id: ID
    name: Text


class Employee(Response):
    id: ID
    departments: list[ID]
    employeeGroups: list[ID]
    primaryDepartmentId: Optional[ID] = None
    employeeTypeId: Optional[ID] = None
    jobTitle: Optional[Text] = None
    isDeactivated: Optional[StrictBool] = None


class Relation(Response):
    employeeId: ID


class Shift(Response):
    id: ID
    departmentId: Optional[ID]
    employeeId: Optional[ID] = None
    employeeGroupId: Optional[ID] = None
    positionId: Optional[ID] = None
    shiftTypeId: Optional[ID] = None
    date: Optional[Date] = None
    startDateTime: Optional[Instant] = None
    endDateTime: Optional[Instant] = None
    status: Literal["Open", "Assigned", "Approved", "ForSale", "Draft", "OnDuty", "PendingSwapAcceptance", "PendingApproval", "PunchclockStarted", "PunchclockFinished", "PunchclockApproved"]
    timeZone: Text


class Paging(Response):
    offset: Offset
    limit: Limit
    total: Annotated[StrictInt, Field(ge=0, le=9007199254740991)]


def projected(model, raw):
    try:
        return model.model_validate(raw).model_dump(exclude_unset=True)
    except Exception:
        raise OutcomeUnverified(UNVERIFIED) from None


def data(raw):
    if not isinstance(raw, dict) or "data" not in raw or raw["data"] is None:
        raise OutcomeUnverified(UNVERIFIED)
    return raw["data"]


def single(model, raw, expected=None):
    result = projected(model, data(raw))
    if expected is not None and result["id"] != expected:
        raise OutcomeUnverified("Planday returned a different resource ID")
    return result


def page(model, raw, cfg):
    records = data(raw)
    if not isinstance(records, list) or len(records) > cfg.limit:
        raise OutcomeUnverified(UNVERIFIED)
    result = [projected(model, item) for item in records]
    if len({item["id"] for item in result}) != len(result):
        raise OutcomeUnverified("Planday returned duplicate IDs in a page")
    raw_paging = raw.get("paging")
    paging = None if raw_paging is None else projected(Paging, raw_paging)
    if paging is not None and (paging["offset"] != cfg.offset or paging["limit"] != cfg.limit or (records and paging["total"] < cfg.offset + len(records))):
        raise OutcomeUnverified("Planday paging contradicts the requested page")
    candidate = cfg.offset + len(records)
    more = candidate < paging["total"] if paging is not None else None
    next_offset = candidate if candidate <= 2147483647 and records and (more is True or (more is None and len(records) == cfg.limit)) else None
    return {"data": result, "paging": paging, "continuation": {"more_results": more, "next_offset_candidate": next_offset, "snapshot_consistent": False}}


async def portal(auth):
    result = single(Portal, await request(auth, "portal/v1.0/info"))
    if auth.credential.expected_portal_id is not None and str(result["id"]) != auth.credential.expected_portal_id:
        raise OutcomeUnverified("Planday returned a different portal ID")
    return result


async def operate(auth, cfg):
    if isinstance(cfg, GetPortalInfo):
        return await portal(auth)
    if auth.credential.expected_portal_id is not None:
        await portal(auth)
    lists = {ListDepartments: ("hr/v1.0/departments", Department), ListEmployeeGroups: ("hr/v1.0/employeegroups", EmployeeGroup), ListEmployees: ("hr/v1.0/employees", Employee)}
    if type(cfg) in lists:
        route, model = lists[type(cfg)]
        return page(model, await request(auth, route, {"offset": cfg.offset, "limit": cfg.limit}), cfg)
    if isinstance(cfg, GetDepartment):
        return single(Department, await request(auth, f"hr/v1.0/departments/{cfg.department_id}"), cfg.department_id)
    if isinstance(cfg, GetEmployeeGroup):
        return single(EmployeeGroup, await request(auth, f"hr/v1.0/employeegroups/{cfg.employee_group_id}"), cfg.employee_group_id)
    if isinstance(cfg, GetEmployee):
        return single(Employee, await request(auth, f"hr/v1.0/employees/{cfg.employee_id}"), cfg.employee_id)
    if isinstance(cfg, ListDepartmentEmployees):
        parent = single(Department, await request(auth, f"hr/v1.0/departments/{cfg.department_id}"), cfg.department_id)
        records = data(await request(auth, f"hr/v1.0/departments/{cfg.department_id}/employees"))
        if not isinstance(records, list) or len(records) > 500:
            raise OutcomeUnverified("Planday department employee relation exceeds its local 500-ID bound or is malformed")
        result = [projected(Relation, item) for item in records]
        if len({item["employeeId"] for item in result}) != len(result):
            raise OutcomeUnverified("Planday returned duplicate employee IDs")
        return {"department": parent, "employees": result, "provider_paging": "unpaged_relation"}
    if isinstance(cfg, ListShifts):
        result = page(Shift, await request(auth, "scheduling/v1.0/shifts", {"offset": cfg.offset, "limit": cfg.limit, "departmentId": cfg.department_id, "from": cfg.date_from, "to": cfg.date_to}), cfg)
        if any(item["departmentId"] != cfg.department_id or item.get("date") is None or not cfg.date_from <= item["date"] <= cfg.date_to for item in result["data"]):
            raise OutcomeUnverified("Planday shift parent or date window did not match")
        return result
    if isinstance(cfg, GetShift):
        result = single(Shift, await request(auth, f"scheduling/v1.0/shifts/{cfg.shift_id}"), cfg.shift_id)
        if result["departmentId"] != cfg.department_id:
            raise OutcomeUnverified("Planday returned a different department parent")
        return result
    raise ValueError("Unsupported Planday operation")


class PlandayNode(WorkflowNode):
    integration_type = "automation-planday"
    connection_evidence = ConnectionEvidence(identity_operation="get_portal_info", noun="Planday portal", identity_keys=("companyName", "name", "id"), proves="account")

    @classmethod
    def get_config_model(cls):
        return PlandayNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw_guard(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        raw_guard(config_data)
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        auth = await Authority.create(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)
        return {**auth.credential.model_dump(), AUTH_KEY: auth}

    @classmethod
    async def validate_credential_access(cls, raw, *, validation_context=None):
        try:
            if validation_context is not None:
                await validation_context.revalidate()
                result = await validation_context.run_operation("get_portal_info", {})
                return (True, None) if result.get("status") == "success" else (None, UNVERIFIED)
            auth = await Authority.create(raw)
            await operate(auth, GetPortalInfo())
            return True, None
        except ApiError as error:
            return (False, str(error)) if error.status_code in (401, 403) else (None, str(error))
        except Exception:
            if validation_context is not None:
                await validation_context.revalidate()
            return None, UNVERIFIED

    async def execute(self, inputs):
        raw_guard(self.node_data)
        if not isinstance(self.config, PlandayNodeConfig) or self.config.credentials is None:
            raise ValueError("Planday client ID and supplied access token are required")
        auth = await Authority.create(self.config.credentials.model_dump(), pool=self.node_data.get("_approval_pool"), user_id=self.user_id, credential_id=self.node_data.get("credential_id"), organization_id=self.organization_id, workflow_id=self.workflow_id)
        data = await operate(auth, self.config.config)
        await auth.require_current()
        return {"status": "success", "operation": self.config.config.operation, "data": data}

    @classmethod
    async def load_field_options(cls, *, field_name, credential_data=None, context=None, page_token=None, search=None):
        # Only canonical freshening from a saved caller-bound row supplies this
        # private object. Browser-supplied dictionaries cannot construct it.
        context = context or {}
        auth = credential_data.get(AUTH_KEY) if isinstance(credential_data, dict) else None
        if not isinstance(auth, Authority) or not auth.credential_id or not auth.user_id or context.get("_user_id") != auth.user_id:
            raise ValueError("Planday pickers require a current saved credential authorized for this actor")
        configs = {"department_id": ListDepartments, "employee_group_id": ListEmployeeGroups, "employee_id": ListEmployees}
        if field_name not in configs:
            raise ValueError("Unsupported Planday picker")
        if page_token is None:
            offset = 0
        elif isinstance(page_token, str) and re.fullmatch(r"0|[1-9][0-9]{0,9}", page_token) and int(page_token) <= 2147483647:
            offset = int(page_token)
        else:
            raise ValueError("Planday picker token must be a bounded integer offset, not a URL")
        if search is not None and (not isinstance(search, str) or len(search) > 512 or any(ord(c) < 32 for c in search)):
            raise ValueError("Planday picker search is invalid")
        await auth.require_current()
        result = await operate(auth, configs[field_name](offset=offset, limit=50))
        options = [{"value": item["id"], "label": item.get("name") or f"Employee {item['id']}"} for item in result["data"]]
        if search:
            options = [item for item in options if search.casefold() in item["label"].casefold()]
        await auth.require_current()
        next_offset = result["continuation"]["next_offset_candidate"]
        return {"options": options, "next_page_token": None if next_offset is None else str(next_offset)}
