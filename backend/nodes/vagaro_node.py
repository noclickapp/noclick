"""Native Vagaro Enterprise Business API regional metadata and profile updates.

Issued client tokens stay server-side and expire before any provider I/O.
Only closed documented routes are exposed; booking and calendar writes are held.
"""
import json
import math
import re
from datetime import date, datetime, timezone
from typing import Annotated, Literal, Union
from urllib.parse import parse_qs, quote, urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Discriminator, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import guarded_async_client

BASE = "https://api.vagaro.com"
MAX_BYTES = 2 * 1024 * 1024
Scope = Literal["read access", "write access", "write employee"]


def _now():
    return datetime.now(timezone.utc)


def _expiry(value):
    if not isinstance(value, str) or len(value) > 40 or not re.search(r"(?:Z|[+-]\d{2}:\d{2})$", value):
        raise ValueError("Use the actual ISO token expiry with timezone")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Use a valid ISO token expiry") from None


def _text(value, maximum=256):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Use nonempty bounded text")
    return value


def _id(value):
    _text(value)
    if value in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9._~+=-]+", value):
        raise ValueError("Use the returned opaque Vagaro record ID")
    return value


RecordID = Annotated[str, Field(min_length=1, max_length=256), AfterValidator(_id)]
Name = Annotated[str, Field(min_length=1, max_length=100), AfterValidator(lambda value: _text(value, 100))]


def _op(name, label, category):
    return Field(name, json_schema_extra={"const": name, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})


class VagaroIssuedClientTokenCredential(BaseModel):
    model_config = ConfigDict(title="Vagaro Issued Client Token", extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://docs.vagaro.com/public/reference/generate-access-token"})
    credential_type: Literal["vagaro_issued_client_token"] = Field("vagaro_issued_client_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(repr=False, title="Issued Client Access Token", description="Token already issued by your Vagaro Developer Settings client credentials. Sent in the accessToken header, without a Bearer prefix. Client IDs/secrets and token minting are not collected by this node.", json_schema_extra={"ui:widget": "password"})
    region: str = Field(title="Exact Account Region", description="Use the region from your account subdomain, for example us04. The docs do not publish an exhaustive region enumeration; the fixed API host cannot be changed.")
    expires_at: str = Field(title="Actual Token Expiry", description="ISO date-time with timezone from actual issuance; the documented expires_in example is 3600 seconds. Replace the saved token when expired; no automatic renewal or replay.")
    granted_scopes: list[Scope] = Field(default_factory=lambda: ["read access"], min_length=1, max_length=3, title="Declared Issued Scopes", description="Exact comma-separated scope values requested when issuing this token, represented here as a list. Local declared metadata is checked, while provider authorization remains authoritative. Updates additionally need write access or write employee as documented.")

    @field_validator("access_token")
    @classmethod
    def header(cls, value):
        _text(value, 16384)
        if not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", value):
            raise ValueError("Use a header-safe issued token")
        return value

    @field_validator("region")
    @classmethod
    def region_path(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", value):
            raise ValueError("Use one exact account region path segment")
        return value

    @field_validator("expires_at")
    @classmethod
    def expiry(cls, value):
        _expiry(value)
        return value

    @field_validator("granted_scopes")
    @classmethod
    def scopes(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Use distinct issued scopes")
        return value


class ConfigBase(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Page(ConfigBase):
    page_number: int = Field(1, strict=True, ge=1, le=100000, title="Page Number", description="Documented one-based pageNumber; local upper bound 100,000.")
    page_size: int = Field(25, strict=True, ge=1, le=100, title="Page Size", description="Explicit pageSize avoids inconsistent example defaults; documented provider maximum is 100.")


class ListLocations(Page):
    operation: Literal["list_locations"] = _op("list_locations", "List Business Locations", "Locations")


class Business(ConfigBase):
    business_id: RecordID = Field(title="Business Location", json_schema_extra={"x-resource-type": "business", "x-dynamic-options": {"field_name": "business_id", "searchable": True, "allow_custom": True}})


class GetLocation(Business):
    operation: Literal["get_location"] = _op("get_location", "Get Business Location", "Locations")


class AccessLevels(Business):
    operation: Literal["get_access_levels"] = _op("get_access_levels", "Get Location Access Levels", "Locations")


class Customer(Business):
    customer_id: RecordID = Field(title="Existing Customer ID", description="Exact existing opaque ID. No customer enumeration endpoint is invented.")


class GetCustomer(Customer):
    operation: Literal["get_customer"] = _op("get_customer", "Get Customer Metadata", "Customers")
    include_contact_details: bool = Field(False, strict=True, title="Include Contact Details", description="Opt in to documented email/phone fields in the workflow output. Birthdays, addresses and financial balances are always omitted.")


class Employee(Business):
    service_provider_id: RecordID = Field(title="Existing Service Provider ID", description="Exact existing opaque employee ID; no employee enumeration endpoint is invented.")


class GetEmployee(Employee):
    operation: Literal["get_employee"] = _op("get_employee", "Get Employee Metadata", "Employees")
    include_contact_details: bool = Field(False, strict=True, title="Include Contact Details", description="Opt in to documented email/phone fields. Birthdays, addresses and employee card IDs are omitted.")


class GetAppointment(Business):
    operation: Literal["get_appointment"] = _op("get_appointment", "Get Appointment Metadata", "Appointments")
    appointment_id: RecordID = Field(title="Existing Appointment ID")


class CustomerAppointments(Customer, Page):
    operation: Literal["list_customer_appointments"] = _op("list_customer_appointments", "List Customer Appointment Metadata", "Appointments")
    page_size: int = Field(25, strict=True, ge=1, le=100, title="Page Size", description="Explicit documented pageSize; local maximum 100, while the appointment endpoint publishes no server maximum or continuation envelope.")
    order_by: Literal["asc", "desc"] = Field("asc", title="Start Time Order")


class PersonalTasks(Employee, Page):
    operation: Literal["list_personal_tasks"] = _op("list_personal_tasks", "List Personal Task Metadata", "Employees")
    start_date: str = Field(title="Local Start Date", description="Explicit local ISO date (YYYY-MM-DD); maps to documented startTime. No implicit today filter.")
    end_date: str = Field(title="Local End Date", description="Explicit local ISO date; local maximum range is 31 days.")

    @model_validator(mode="after")
    def range(self):
        try:
            start, end = date.fromisoformat(self.start_date), date.fromisoformat(self.end_date)
        except ValueError:
            raise ValueError("Use local ISO dates in YYYY-MM-DD format") from None
        if start.isoformat() != self.start_date or end.isoformat() != self.end_date or not 0 <= (end - start).days <= 31:
            raise ValueError("Use an ordered ISO date range of at most 31 days")
        return self


class Effects(ConfigBase):
    acknowledge_profile_effects: bool = Field(title="Accept Profile Changes", description="Updates persist and may affect public profiles or configured automation. Verify the resulting record with a separate read.")

    @field_validator("acknowledge_profile_effects", mode="before")
    @classmethod
    def acknowledge(cls, value):
        if value is not True:
            raise ValueError("Explicitly accept profile update effects")
        return value


class UpdateCustomer(Customer, Effects):
    operation: Literal["update_customer_profile"] = _op("update_customer_profile", "Update Customer Name or Tags", "Customers")
    customer_first_name: Name | None = Field(None, title="First Name")
    customer_last_name: Name | None = Field(None, title="Last Name")
    general_tags: list[Name] | None = Field(None, max_length=50, title="General Tags", description="Exact replacement tags. An explicit empty list clears tags; reminder/contact/booking preferences are not exposed.")

    @model_validator(mode="after")
    def changes(self):
        if self.customer_first_name is None and self.customer_last_name is None and self.general_tags is None:
            raise ValueError("Supply at least one profile change")
        if self.general_tags is not None and len(set(self.general_tags)) != len(self.general_tags):
            raise ValueError("Use distinct tags")
        return self


class UpdateEmployee(Employee, Effects):
    operation: Literal["update_employee_name"] = _op("update_employee_name", "Update Employee Name", "Employees")
    employee_first_name: Name | None = Field(None, title="First Name")
    employee_last_name: Name | None = Field(None, title="Last Name")

    @model_validator(mode="after")
    def changes(self):
        if self.employee_first_name is None and self.employee_last_name is None:
            raise ValueError("Supply at least one name change")
        return self


class UpdateLocation(Business, Effects):
    operation: Literal["update_location_name"] = _op("update_location_name", "Update Location Name or Alias", "Locations")
    business_name: Name | None = Field(None, title="Business Name")
    business_alias: Name | None = Field(None, title="Business Alias", description="The API documents alias updates for multi-location businesses; it has no effect on a single-location business.")

    @model_validator(mode="after")
    def changes(self):
        if self.business_name is None and self.business_alias is None:
            raise ValueError("Supply at least one name or alias change")
        return self


VagaroConfig = Annotated[Union[ListLocations, GetLocation, AccessLevels, GetCustomer, GetEmployee, GetAppointment, CustomerAppointments, PersonalTasks, UpdateCustomer, UpdateEmployee, UpdateLocation], Discriminator("operation")]


class VagaroNodeConfig(NodeConfig[VagaroConfig, VagaroIssuedClientTokenCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


class VagaroError(ValueError):
    def __init__(self, message, status_code=None, provider_status=None, uncertain=False):
        super().__init__(message)
        self.status_code, self.provider_status, self.uncertain = status_code, provider_status, uncertain


def _pairs(pairs):
    value = {}
    for key, child in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = child
    return value


def _finite(value, depth=0):
    if depth > 40 or isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Invalid JSON value")
    if isinstance(value, dict):
        for child in value.values():
            _finite(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _finite(child, depth + 1)


def _project(value, fields, id_key=None, expected=None):
    if not isinstance(value, dict):
        raise ValueError("Unverified record")
    result = {}
    for key, kind in fields.items():
        if key in value and value[key] is not None:
            if type(value[key]) is not kind or kind is str and len(value[key]) > 8192:
                raise ValueError("Unverified record field")
            result[key] = value[key]
    if id_key:
        identifier = _id(result.get(id_key))
        if expected is not None and identifier != expected:
            raise ValueError("Different record returned")
    return result


LOCATION = {**{key: str for key in ("businessId", "businessGroupId", "businessName", "businessAlias", "city", "regionCode", "countryCode", "createdDate")}, "listedOnVagaro": bool}
CUSTOMER = {key: str for key in ("customerId", "customerFirstName", "customerLastName", "city", "countryCode", "createdDate")}
EMPLOYEE = {**{key: str for key in ("serviceProviderId", "employeeFirstName", "employeeLastName", "businessGroupId", "startDate", "reportsTo", "employeeType", "createdDate")}, "isActive": bool}
APPOINTMENT = {key: str for key in ("appointmentId", "startTime", "endTime", "bookingStatus", "serviceTitle", "serviceId", "eventType", "customerId", "serviceProviderId", "serviceCategory", "createdDate")}
TASK = {**{key: str for key in ("personalTaskId", "personalTaskHexCode", "businessId", "serviceProviderId", "personalTaskName", "startTime", "endTime")}, "blockOnlineBooking": bool}


class BusinessSession:
    def __init__(self, credential):
        self.credential = credential

    def require(self, *scopes):
        if _expiry(self.credential.expires_at) <= _now():
            raise VagaroError("The issued Vagaro token expired; replace the saved credential")
        if any(scope not in self.credential.granted_scopes for scope in scopes):
            raise VagaroError("The declared token scopes do not include the documented operation scope")

    async def request(self, method, path, *, body=None, params=None, mutation=False):
        reads = {("POST", "locations"), ("GET", "merchants/access-levels"), ("POST", "customers"), ("POST", "employees"), ("POST", "appointments"), ("POST", "personal-tasks/retrieve")}
        if (method, path) not in reads and not (method == "PUT" and re.fullmatch(r"(?:locations|customers|employees)/[A-Za-z0-9._~%+=-]+", path)):
            raise VagaroError("Unsupported Vagaro route")
        mutation = method == "PUT"
        self.require("write access" if path.startswith("customers/") else "write employee" if mutation else "read access")
        status = provider_status = None
        try:
            async with guarded_async_client(trust_env=False, follow_redirects=False, timeout=20.0) as client:
                async with client.stream(method, f"{BASE}/{self.credential.region}/api/v2/{path}", json=body, params=params, headers={"accessToken": self.credential.access_token, "Accept": "application/json"}) as response:
                    status = response.status_code
                    if status != 200:
                        raise VagaroError("Vagaro rejected or did not verify the request", status, uncertain=mutation and (status >= 500 or status in {408, 429} or 200 <= status < 400))
                    payload = bytearray()
                    async for chunk in response.aiter_bytes():
                        payload.extend(chunk)
                        if len(payload) > MAX_BYTES:
                            raise ValueError("Metadata body limit")
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise ValueError("Unverified JSON type")
            value = json.loads(payload, object_pairs_hook=_pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
            _finite(value)
            if not isinstance(value, dict):
                raise ValueError("Unverified envelope")
            provider_status = value.get("status") if type(value.get("status")) is int else None
            if provider_status != 200 or type(value.get("responseCode")) is not int or value["responseCode"] != 1000:
                raise VagaroError("Vagaro returned an unsuccessful provider envelope", status, provider_status, mutation)
            if "data" not in value or value.get("error") or value.get("errors") or value.get("success") is False or value.get("executed") is False:
                raise ValueError("Refused or incomplete envelope")
            return value["data"], status
        except VagaroError:
            raise
        except Exception:
            raise VagaroError("Vagaro request or metadata could not be verified", status, provider_status, mutation) from None

    def redact(self, value):
        if isinstance(value, str):
            return value.replace(self.credential.access_token, "[redacted]")
        if isinstance(value, dict):
            return {self.redact(key): self.redact(child) for key, child in value.items()}
        if isinstance(value, list):
            return [self.redact(child) for child in value]
        return value


def _page(data, field, config, session, path, fields, id_key):
    if not isinstance(data, dict) or not isinstance(data.get(field), list) or len(data[field]) > config.page_size:
        raise ValueError("Unverified bounded page")
    rows = [_project(row, fields, id_key) for row in data[field]]
    next_page = data.get("nextPage")
    number = None
    if next_page not in (None, ""):
        if not isinstance(next_page, str) or len(next_page) > 2048:
            raise ValueError("Unverified continuation")
        url = urlsplit(next_page)
        query = parse_qs(url.query, keep_blank_values=True)
        if url.scheme != "https" or url.netloc != "api.vagaro.com" or url.path != f"/{session.credential.region}/api/v2/{path}" or url.fragment or set(query) != {"pageNumber", "pageSize"}:
            raise ValueError("Continuation scope changed")
        if any(len(values) != 1 for values in query.values()) or query["pageSize"] != [str(config.page_size)] or not re.fullmatch(r"[1-9]\d{0,5}", query["pageNumber"][0]):
            raise ValueError("Unverified continuation page")
        number = int(query["pageNumber"][0])
        if number != config.page_number + 1 or number > 100000 or not rows:
            raise ValueError("Nonadvancing or out-of-bound continuation")
    # Never fetch or return the provider URL; the opaque local token is just its verified page number.
    return {field: rows, "next_page_number": number, "snapshot_verified": False}


class VagaroNode(WorkflowNode):
    integration_type = "automation-vagaro"
    connection_evidence = ConnectionEvidence(operation="list_locations", operation_arguments={"page_size": 5}, noun="business locations", label_keys=("businessName", "businessAlias", "businessId"))
    scope_registry = ScopeRegistry("vagaro", {
        **{operation: ScopeRequirement(scopes=("read access",), credential_types=("vagaro_issued_client_token",)) for operation in ("list_locations", "get_location", "get_access_levels", "get_customer", "get_employee", "get_appointment", "list_customer_appointments", "list_personal_tasks")},
        "update_customer_profile": ScopeRequirement(scopes=("read access", "write access"), credential_types=("vagaro_issued_client_token",)),
        "update_employee_name": ScopeRequirement(scopes=("read access", "write employee"), credential_types=("vagaro_issued_client_token",)),
        # The official location-update contract explicitly says write employee.
        "update_location_name": ScopeRequirement(scopes=("read access", "write employee"), credential_types=("vagaro_issued_client_token",)),
    })

    @classmethod
    def get_config_model(cls):
        return VagaroNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        credential = config_data.get("credentials")
        if isinstance(credential, dict) and credential.get("credential_type") not in (None, "vagaro_issued_client_token"):
            raise ValueError("Use a current Vagaro issued client token")
        return super().parse_config(config_data)

    @classmethod
    async def validate_credential_access(cls, credential_data):
        credential = VagaroIssuedClientTokenCredential.model_validate(credential_data)
        node = cls(node_id="vagaro-credential-probe", node_type=cls.integration_type, node_data={},
                   config=VagaroNodeConfig(config=ListLocations(page_size=5), credentials=credential))
        result = await node.execute({})
        if result["status"] == "error":
            invalid = result.get("status_code") in {401, 403} or result.get("provider_status") in {401, 403}
            return {"valid": False if invalid else None, "name": None, "error": result["error"], "status_code": result.get("status_code")}
        rows = result["locations"]
        return {"valid": True, "name": rows[0].get("businessName") if rows else None}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        if field_name != "business_id":
            return {"options": [], "next_page_token": None}
        if page_token is not None and (not isinstance(page_token, str) or not re.fullmatch(r"[1-9]\d{0,5}", page_token)):
            raise ValueError("Use the returned page continuation")
        if credential_data.get("credential_type") not in (None, "vagaro_issued_client_token"):
            raise ValueError("Use a current Vagaro issued client token")
        config = ListLocations(page_number=int(page_token) if page_token else 1)
        session = BusinessSession(VagaroIssuedClientTokenCredential.model_validate(credential_data))
        data, _ = await session.request("POST", "locations", body={}, params={"pageNumber": config.page_number, "pageSize": config.page_size})
        page = _page(data, "locations", config, session, "locations", LOCATION, "businessId")
        options = [{"value": row["businessId"], "label": row.get("businessName") or row["businessId"]} for row in page["locations"] if not search or search.casefold() in (row.get("businessName") or row["businessId"]).casefold()]
        return session.redact({"options": options, "next_page_token": str(page["next_page_number"]) if page["next_page_number"] else None})

    async def execute(self, inputs):
        if not isinstance(self.config, VagaroNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a current Vagaro issued client token")
        config, session = self.config.config, BusinessSession(self.config.credentials)
        status, mutation_started = None, False
        try:
            session.require(*self.scope_registry.require(config.operation).scopes)
            if isinstance(config, ListLocations):
                data, status = await session.request("POST", "locations", body={}, params={"pageNumber": config.page_number, "pageSize": config.page_size})
                output = _page(data, "locations", config, session, "locations", LOCATION, "businessId")
            else:
                # The token's actual accessible location is read before parent-bound records or profile writes.
                data, status = await session.request("POST", "locations", body={"businessId": config.business_id}, params={"pageNumber": 1, "pageSize": 1})
                if not isinstance(data, dict) or not isinstance(data.get("locations"), list) or len(data["locations"]) != 1:
                    raise ValueError("Unverified business location")
                location = _project(data["locations"][0], LOCATION, "businessId", config.business_id)
                body = {"businessId": config.business_id}
                if isinstance(config, (GetCustomer, UpdateCustomer)):
                    data, status = await session.request("POST", "customers", body={**body, "customerId": config.customer_id})
                    fields = {**CUSTOMER, **({key: str for key in ("email", "mobilePhone", "dayPhone", "nightPhone")} if getattr(config, "include_contact_details", False) else {})}
                    output = _project(data, fields, "customerId", config.customer_id)
                    if "generalTags" in data:
                        if not isinstance(data["generalTags"], list) or len(data["generalTags"]) > 100 or any(not isinstance(tag, str) or len(tag) > 100 for tag in data["generalTags"]):
                            raise ValueError("Unverified customer tags")
                        output["generalTags"] = data["generalTags"]
                elif isinstance(config, (GetEmployee, UpdateEmployee, PersonalTasks)):
                    data, status = await session.request("POST", "employees", body={**body, "serviceProviderId": config.service_provider_id})
                    fields = {**EMPLOYEE, **({key: str for key in ("email", "phone")} if getattr(config, "include_contact_details", False) else {})}
                    output = _project(data, fields, "serviceProviderId", config.service_provider_id)
                    if isinstance(config, PersonalTasks):
                        data, status = await session.request("POST", "personal-tasks/retrieve", body={**body, "serviceProviderId": config.service_provider_id, "startTime": config.start_date, "endTime": config.end_date}, params={"pageNumber": config.page_number, "pageSize": config.page_size})
                        output = _page(data, "personalTasks", config, session, "personal-tasks/retrieve", TASK, "personalTaskId")
                        if any(row.get("businessId") != config.business_id or row.get("serviceProviderId") != config.service_provider_id for row in output["personalTasks"]):
                            raise ValueError("Different task parent returned")
                elif isinstance(config, (GetAppointment, CustomerAppointments)):
                    key, expected = ("appointmentId", config.appointment_id) if isinstance(config, GetAppointment) else ("customerId", config.customer_id)
                    number, size, order = (1, 1, "asc") if isinstance(config, GetAppointment) else (config.page_number, config.page_size, config.order_by)
                    data, status = await session.request("POST", "appointments", body={**body, key: expected}, params={"pageNumber": str(number), "pageSize": str(size), "orderBy": order})
                    if not isinstance(data, list) or len(data) > size or isinstance(config, GetAppointment) and len(data) != 1:
                        raise ValueError("Unverified bounded appointment result")
                    records = [_project(row, APPOINTMENT, "appointmentId") for row in data]
                    if any(row.get(key) != expected for row in records):
                        raise ValueError("Different appointment filter returned")
                    output = {"appointments": records, "next_page_number": number + 1 if isinstance(config, CustomerAppointments) and len(records) == size and number < 100000 else None, "continuation_verified": False, "snapshot_verified": False}
                elif isinstance(config, AccessLevels):
                    data, status = await session.request("GET", "merchants/access-levels", params=body)
                    if not isinstance(data, list) or len(data) > 1000:
                        raise ValueError("Unverified access-level list")
                    output = {"access_levels": [_project(row, {"accessLevelId": str, "accessLevelName": str, "isActive": bool}, "accessLevelId") for row in data]}
                else:
                    output = location
                if isinstance(config, Effects):
                    path = "customers/" + quote(config.customer_id, safe="") if isinstance(config, UpdateCustomer) else "employees/" + quote(config.service_provider_id, safe="") if isinstance(config, UpdateEmployee) else "locations/" + quote(config.business_id, safe="")
                    mapping = {"customer_first_name": "customerFirstName", "customer_last_name": "customerLastName", "general_tags": "generalTags"} if isinstance(config, UpdateCustomer) else {"employee_first_name": "employeeFirstName", "employee_last_name": "employeeLastName"} if isinstance(config, UpdateEmployee) else {"business_name": "businessName", "business_alias": "businessAlias"}
                    changes = {wire: getattr(config, key) for key, wire in mapping.items() if getattr(config, key) is not None}
                    mutation_started = True
                    accepted, status = await session.request("PUT", path, body=changes if isinstance(config, UpdateLocation) else {**body, **changes}, mutation=True)
                    if accepted != "":
                        raise ValueError("Unverified profile update acceptance")
                    output = {"businessId": config.business_id, "provider_acknowledged": True, "readback_verified": False, "status_code": status}
            return session.redact({"status": "success", **output})
        except VagaroError as error:
            return {"status": "error", "error": str(error), "status_code": error.status_code, "provider_status": error.provider_status, "uncertain_outcome": error.uncertain}
        except Exception:
            return {"status": "error", "error": "Vagaro returned unverified metadata", "status_code": status, "uncertain_outcome": mutation_started}
