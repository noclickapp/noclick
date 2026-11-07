"""Native Oracle Fusion Cloud HCM metadata and date-effective location workflows.

Every request uses a supplied tenant-bound credential and a documented HCM path.
Worker reads are restricted to directory identifiers; employment and financial writes are excluded.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
from datetime import date
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, BeforeValidator, ConfigDict, Discriminator, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.dynamic_options import filter_options_by_search, normalize_search
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from utils.ssrf import SSRFError, allow_private_hosts, guarded_async_client

BASIC = "oracle_hcm_basic"
OAUTH = "oracle_hcm_oauth_token"
TYPES = (BASIC, OAUTH)
VERSION = "11.13.18.05"
MAX_BYTES = 2 * 1024 * 1024
MAX_OFFSET = 1000000


def tenant_url(value):
    if not isinstance(value, str) or re.search(r"[\x00-\x20\x7f]", value):
        raise ValueError("Use the HTTPS Oracle Fusion tenant URL supplied by your administrator")
    try:
        parts = urlsplit(value)
        label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
        if parts.scheme != "https" or parts.username or parts.password or parts.port is not None or parts.query or parts.fragment or parts.path not in ("", "/") or not re.fullmatch(rf"{label}\.fa\.{label}\.oraclecloud\.com", parts.netloc):
            raise ValueError()
        return "https://" + parts.netloc
    except ValueError:
        raise ValueError("Use a documented HTTPS <tenant>.fa.<region>.oraclecloud.com origin without a port or resource path") from None


def resource_key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,2048}", value):
        raise ValueError("Use the opaque resource key returned by the Oracle HCM collection; do not generate it from a surrogate ID")
    return value


def text_value(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError("Use nonempty text without control characters")
    return value.strip()


def iso_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError("Use an explicit YYYY-MM-DD effective date")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError("Use a valid YYYY-MM-DD effective date") from None
    return value


TenantURL = Annotated[str, BeforeValidator(tenant_url)]
ResourceKey = Annotated[str, BeforeValidator(resource_key)]
Text = Annotated[str, BeforeValidator(text_value)]
ISODate = Annotated[str, BeforeValidator(iso_date)]


class OracleHCMConnection(BaseModel):
    tenant_url: TenantURL = Field(..., title="Oracle Fusion Tenant URL", description="The exact Oracle Fusion SaaS origin from your administrator's welcome email, such as https://tenant.fa.us2.oraclecloud.com. ERP/CX resource paths and custom/self-hosted aliases are not accepted.")
    api_version: Literal["11.13.18.05"] = Field(..., title="HCM API Resource Version", description="Explicit documented HCM resource version. v1 resources require OAuth and are a separate contract; this node does not substitute v1 or latest aliases.")
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class OracleHCMBasicCredential(OracleHCMConnection):
    credential_type: Literal["oracle_hcm_basic"] = Field(BASIC, json_schema_extra={"ui:hidden": True})
    username: str = Field(..., min_length=1, max_length=254, repr=False, title="Oracle Service Username")
    password: str = Field(..., min_length=1, max_length=6000, repr=False, title="Oracle Service Password", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="Oracle HCM Basic Account", extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.oracle.com/en/cloud/saas/human-resources/farws/Quick_Start.html",
        "x-credential-instructions": "Use a supplied Oracle Cloud service username/password with the required HCM resource roles. Basic is supported over TLS for these 11.13.18.05 resources; it is not supported for v1. Do not paste a Basic header. NoClick does not provision users or infer roles.",
    })

    @model_validator(mode="before")
    @classmethod
    def manual_family(cls, value):
        if isinstance(value, dict) and value.get("access_token"):
            raise ValueError("Select one supplied HCM credential family")
        return {"credential_type": BASIC, **value} if isinstance(value, dict) else value

    @field_validator("username", "password")
    @classmethod
    def valid_basic(cls, value, info):
        if not value or re.search(r"[\x00-\x1f\x7f]", value) or info.field_name == "username" and (":" in value or value != value.strip()):
            raise ValueError("Supply valid Oracle service credentials without header prefixes or control characters")
        return value


class OracleHCMSuppliedOAuthCredential(OracleHCMConnection):
    credential_type: Literal["oracle_hcm_oauth_token"] = Field(OAUTH, json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=16000, repr=False, title="Issued Oracle OAuth Access Token", json_schema_extra={"ui:widget": "password"})
    model_config = ConfigDict(title="Oracle HCM Supplied OAuth Token", extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.oracle.com/en/cloud/saas/human-resources/farws/Quick_Start.html",
        "x-credential-instructions": "Supply an actual OAuth access token issued by the Oracle IAM confidential application configured for this exact Fusion tenant/resource audience. Paste the token only. Requested versus granted scope, role and audience remain issuer/provider authoritative; this manual family does not invent an OAuth popup, mint, refresh, client or broad grant.",
    })

    @model_validator(mode="before")
    @classmethod
    def manual_family(cls, value):
        if isinstance(value, dict) and (value.get("username") or value.get("password")):
            raise ValueError("Select one supplied HCM credential family")
        return {"credential_type": OAUTH, **value} if isinstance(value, dict) else value

    @field_validator("access_token", mode="before")
    @classmethod
    def issued_token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Supply the issued OAuth token only")
        value = clean_secret(value)
        if not value or re.search(r"[\x00-\x20\x7f]", value) or not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", value):
            raise ValueError("Supply the issued OAuth token without a Bearer prefix")
        return value


# Direct union branches keep the current credential UI consumers' $ref discovery.
# Raw parse/current-row/request paths still require an explicit valid family first.
OracleHCMCredential = Union[OracleHCMSuppliedOAuthCredential, OracleHCMBasicCredential]


def credential_value(raw, *, manual=False):
    if isinstance(raw, (OracleHCMBasicCredential, OracleHCMSuppliedOAuthCredential)):
        raw = raw.model_dump()
    if not isinstance(raw, dict):
        raise ValueError("Connect a typed Oracle HCM Basic or supplied OAuth credential")
    data = dict(raw)
    if manual and not data.get("credential_type"):
        if data.get("access_token") and not (data.get("username") or data.get("password")):
            data["credential_type"] = OAUTH
        elif data.get("username") and data.get("password") and not data.get("access_token"):
            data["credential_type"] = BASIC
    model = OracleHCMBasicCredential if data.get("credential_type") == BASIC else OracleHCMSuppliedOAuthCredential if data.get("credential_type") == OAUTH else None
    if model is None or data.get("credential_type") == BASIC and data.get("access_token") or data.get("credential_type") == OAUTH and (data.get("username") or data.get("password")):
        raise ValueError("Current Oracle HCM credential family is invalid or ambiguous")
    try:
        return model.model_validate(data)
    except ValueError:
        raise ValueError("Use a valid Oracle tenant, explicit supported HCM version and supplied credential") from None


def base_url(credential):
    return f"{credential.tenant_url}/hcmRestApi/resources/{credential.api_version}"


def picker(field):
    return {"x-resource-type": "oracle_hcm_" + field, "x-dynamic-options": {"field_name": field, "searchable": True, "allow_custom": True, "custom_placeholder": "Paste the collection's opaque resource key"}}


def operation_meta(name, category, effect=None):
    extra = {"x-display-name": name, "x-category": category, "x-is-trigger": False}
    if effect:
        extra["x-operation-effect"] = effect
    return ConfigDict(extra="forbid", hide_input_in_errors=True, json_schema_extra=extra)


def operation_field(value, label, category):
    extra = {"const": value, "ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False}
    if value == "create_location":
        extra.update({"x-creates-resource": True, "x-resource-type": "oracle_hcm_location_key", "x-resource-id-path": "data.resource_key"})
    return Field(value, title=label, json_schema_extra=extra)


class Page(BaseModel):
    offset: int = Field(0, strict=True, ge=0, le=MAX_OFFSET, title="Offset", description="One bounded provider page; no automatic drain.")
    limit: int = Field(50, strict=True, ge=1, le=100, title="Page Size", description="NoClick cap is 100. Oracle may return a smaller actual limit; the next offset uses the returned page size.")


class DatedPage(Page):
    effective_date: ISODate | None = Field(None, title="As-of Effective Date", description="Omit for the provider's current date.")


class ListJobs(DatedPage):
    operation: Literal["list_jobs"] = operation_field("list_jobs", "List jobs", "Organization metadata")
    model_config = operation_meta("List jobs", "Organization metadata")


class GetJob(BaseModel):
    operation: Literal["get_job"] = operation_field("get_job", "Get job", "Organization metadata")
    job_key: ResourceKey = Field(..., title="Job Resource Key", json_schema_extra=picker("job_key"))
    model_config = operation_meta("Get job", "Organization metadata")


class ListDepartments(Page):
    operation: Literal["list_departments"] = operation_field("list_departments", "List department lookup metadata", "Organization metadata")
    model_config = operation_meta("List department lookup metadata", "Organization metadata")


class ListOrganizations(DatedPage):
    operation: Literal["list_organizations"] = operation_field("list_organizations", "List HCM department organizations", "Organization metadata")
    model_config = operation_meta("List HCM department organizations", "Organization metadata")


class GetOrganization(BaseModel):
    operation: Literal["get_organization"] = operation_field("get_organization", "Get HCM department organization", "Organization metadata")
    organization_key: ResourceKey = Field(..., title="HCM Organization Resource Key", json_schema_extra=picker("organization_key"))
    model_config = operation_meta("Get HCM department organization", "Organization metadata")


class ListLocations(DatedPage):
    operation: Literal["list_locations"] = operation_field("list_locations", "List locations", "Locations")
    model_config = operation_meta("List locations", "Locations")


class LocationOperation(BaseModel):
    location_key: ResourceKey = Field(..., title="Location Resource Key", description="The composite hash from a returned self/canonical link; LocationId is not this key.", json_schema_extra=picker("location_key"))


class GetLocation(LocationOperation):
    operation: Literal["get_location"] = operation_field("get_location", "Get location", "Locations")
    model_config = operation_meta("Get location", "Locations")


class CreateLocation(BaseModel):
    operation: Literal["create_location"] = operation_field("create_location", "Create location", "Locations")
    location_code: Text = Field(..., max_length=120, title="Location Code")
    location_name: Text = Field(..., max_length=60, title="Location Name")
    set_id: int = Field(..., strict=True, ge=0, le=9223372036854775807, title="Reference Data Set ID")
    set_code: Text = Field(..., max_length=30, title="Reference Data Set Code", description="Both SetId and SetCode are required by the published schema; provider checks their relationship.")
    effective_start_date: ISODate = Field(..., title="Effective Start Date")
    effective_end_date: ISODate = Field(..., title="Effective End Date")
    description: Text | None = Field(None, max_length=240, title="Location Description")
    model_config = operation_meta("Create location", "Locations", "Creates a date-effective HCM location. Oracle postprocessing may take minutes; response and one readback are checked without polling, retries or upsert. No address, worker, inventory, shipping, payroll or money attributes are sent.")

    @model_validator(mode="after")
    def date_range(self):
        if self.effective_end_date < self.effective_start_date:
            raise ValueError("Effective end date must not precede the start date")
        return self


class UpdateLocation(LocationOperation):
    operation: Literal["update_location"] = operation_field("update_location", "Correct or update location metadata", "Locations")
    range_mode: Literal["CORRECTION", "UPDATE"] = Field(..., title="Date-effective Change Mode", description="CORRECTION changes the current physical row. UPDATE requires an explicit effective start date and can create a new physical row/key.")
    effective_start_date: ISODate | None = Field(None, title="Update Effective Start Date")
    location_name: Text | None = Field(None, max_length=60, title="Location Name")
    description: Text | None = Field(None, max_length=240, title="Location Description", description="Explicit null clears the nullable description; an omitted field is preserved.")
    model_config = operation_meta("Correct or update location metadata", "Locations", "PATCH with explicit Effective-Of mode; changes location metadata/history. Provider role and date constraints remain authoritative. One readback checks supplied values; no retries, polling or employment changes.")

    @model_validator(mode="after")
    def changes(self):
        if self.range_mode == "UPDATE" and not self.effective_start_date or self.range_mode == "CORRECTION" and self.effective_start_date is not None:
            raise ValueError("UPDATE needs an effective start date; CORRECTION must omit it")
        if not {"location_name", "description"}.intersection(self.model_fields_set):
            raise ValueError("Supply at least one location metadata field")
        if "location_name" in self.model_fields_set and self.location_name is None:
            raise ValueError("Only the nullable description can be explicitly cleared")
        return self


class DeleteLocation(LocationOperation):
    operation: Literal["delete_location_changes"] = operation_field("delete_location_changes", "Delete location changes", "Locations")
    confirm_delete_changes: Literal[True] = Field(..., title="Confirm deleting this location's changes")
    model_config = operation_meta("Delete location changes", "Locations", "DELETE with Effective-Of: RangeMode=DELETE_CHANGES. Bodyless 204 confirms the request, not absence of every historical/logical location row. This can remove location history; no retry or invented full-resource deletion claim.")

    @field_validator("confirm_delete_changes", mode="before")
    @classmethod
    def confirmed(cls, value):
        if value is not True:
            raise ValueError("Explicitly confirm deleting location changes")
        return value


class ListWorkers(Page):
    operation: Literal["list_worker_metadata"] = operation_field("list_worker_metadata", "List worker directory identifiers", "Worker metadata")
    model_config = operation_meta("List worker directory identifiers", "Worker metadata")


class GetWorker(BaseModel):
    operation: Literal["get_worker_metadata"] = operation_field("get_worker_metadata", "Get worker directory identifiers", "Worker metadata")
    worker_key: ResourceKey = Field(..., title="Worker Directory Resource Key", json_schema_extra=picker("worker_key"))
    model_config = operation_meta("Get worker directory identifiers", "Worker metadata")


OPERATIONS = (ListJobs, GetJob, ListDepartments, ListOrganizations, GetOrganization, ListLocations, GetLocation, CreateLocation, UpdateLocation, DeleteLocation, ListWorkers, GetWorker)
OracleHCMOperation = Annotated[Union[ListJobs, GetJob, ListDepartments, ListOrganizations, GetOrganization, ListLocations, GetLocation, CreateLocation, UpdateLocation, DeleteLocation, ListWorkers, GetWorker], Discriminator("operation")]


class OracleHCMNodeConfig(NodeConfig[OracleHCMOperation, OracleHCMCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ORACLE_HCM_SCOPES = ScopeRegistry("oracle_hcm", {cls.model_fields["operation"].default: ScopeRequirement((), credential_types=TYPES, note="Required Oracle HCM roles, IAM audience and actual OAuth grants remain provider authoritative; no scope or administrator role is inferred.") for cls in OPERATIONS})
RESOURCES = {
    "jobs": ("JobId", ("JobId", "JobCode", "Name", "ActiveStatus", "SetId", "EffectiveStartDate", "EffectiveEndDate")),
    "departmentsLov": ("OrganizationId", ("OrganizationId", "Name", "Title", "Status", "SetId", "SetCode", "SetName", "LocationId", "LocationCode", "LocationName", "EffectiveStartDate", "EffectiveEndDate")),
    "organizations": ("OrganizationId", ("OrganizationId", "Name", "OrganizationCode", "OrgCode", "Status", "LocationId", "EffectiveStartDate", "EffectiveEndDate")),
    "locationsV2": ("LocationId", ("LocationId", "LocationCode", "LocationName", "ActiveStatus", "SetId", "SetCode", "EffectiveStartDate", "EffectiveEndDate", "Description")),
    "publicWorkers": ("PersonId", ("PersonId", "PersonNumber")),
}
LIST_RESOURCES = {"list_jobs": "jobs", "list_departments": "departmentsLov", "list_organizations": "organizations", "list_locations": "locationsV2", "list_worker_metadata": "publicWorkers"}
GET_RESOURCES = {"get_job": ("jobs", "job_key"), "get_organization": ("organizations", "organization_key"), "get_location": ("locationsV2", "location_key"), "get_worker_metadata": ("publicWorkers", "worker_key")}
BODY_FIELDS = {"location_code": "LocationCode", "location_name": "LocationName", "set_id": "SetId", "set_code": "SetCode", "effective_start_date": "EffectiveStartDate", "effective_end_date": "EffectiveEndDate", "description": "Description"}


def finite_json(content):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    def decimal(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError()
        return number
    try:
        return json.loads(content, object_pairs_hook=pairs, parse_float=decimal, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError("Oracle HCM returned malformed or nonfinite JSON") from None


class OracleHCMAPIError(ValueError):
    def __init__(self, status, retry_after=None):
        self.http_status, self.retry_after = status, retry_after
        super().__init__(f"Oracle HCM HTTP {status}: request was not confirmed" + (f"; retry after {retry_after} seconds" if retry_after is not None else ""))


def auth_header(credential):
    return "Basic " + base64.b64encode((credential.username + ":" + credential.password).encode()).decode() if isinstance(credential, OracleHCMBasicCredential) else "Bearer " + credential.access_token


async def fetch(credential_data, operation, method, resource, key=None, *, params=None, body=None, effective_of=None):
    credential = credential_value(credential_data)
    ORACLE_HCM_SCOPES.enforce_credential_type(operation, credential.credential_type)
    if resource not in RESOURCES or resource == "departmentsLov" and key is not None:
        raise ValueError("Use a native Oracle HCM resource")
    key = resource_key(key) if key is not None else None
    allowed = method == "GET" and body is None and effective_of is None or resource == "locationsV2" and (operation == "create_location" and method == "POST" and key is None and effective_of is None or operation == "update_location" and method == "PATCH" and key is not None and re.fullmatch(r"RangeMode=CORRECTION|RangeStartDate=[0-9]{4}-[0-9]{2}-[0-9]{2};RangeMode=UPDATE", effective_of or "") or operation == "delete_location_changes" and method == "DELETE" and key is not None and body is None and effective_of == "RangeMode=DELETE_CHANGES")
    if not allowed or allow_private_hosts():
        raise ValueError("Use a native public Oracle HCM operation; private overrides and arbitrary routes are unsupported")
    route = "/" + resource + ("/" + key if key else "")
    expected = 201 if method == "POST" else 204 if method == "DELETE" else 200
    headers = {"Authorization": auth_header(credential), "Accept": "application/json", "Content-Type": "application/vnd.oracle.adf.resourceitem+json", "REST-Framework-Version": "4" if resource == "publicWorkers" else "5"}
    if effective_of:
        headers["Effective-Of"] = effective_of
    try:
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            async with client.stream(method, base_url(credential) + route, headers=headers, params=params, **({"json": body} if body is not None else {})) as response:
                if response.status_code != expected:
                    retry = response.headers.get("retry-after", "")
                    raise OracleHCMAPIError(response.status_code, int(retry) if re.fullmatch(r"[0-9]{1,6}", retry) else None)
                if expected == 204:
                    return None
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > MAX_BYTES:
                        raise ValueError("Oracle HCM response exceeds 2 MiB; no partial result accepted")
                    content.extend(chunk)
                media = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if media not in {"application/json", "application/vnd.oracle.adf.resourceitem+json", "application/vnd.oracle.adf.resourcecollection+json"}:
                    raise ValueError("Oracle HCM returned a non-JSON success response")
                raw = finite_json(bytes(content))
                if not isinstance(raw, dict) or any(key in raw for key in ("error", "errors", "o:errorDetails")):
                    raise ValueError("Oracle HCM did not return a native resource envelope")
                return raw
    except SSRFError:
        raise ValueError("Oracle HCM destination is not publicly reachable") from None
    except httpx.RequestError:
        raise ValueError("Oracle HCM request could not be completed; no automatic retry") from None


def safe_text(value, credential, maximum=2000):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > maximum or re.search(r"[\x00-\x1f\x7f]", value):
        raise ValueError("Oracle HCM returned invalid metadata text")
    secrets = [credential.username, credential.password] if isinstance(credential, OracleHCMBasicCredential) else [credential.access_token]
    secrets.append(auth_header(credential).split(" ", 1)[1])
    for secret in secrets:
        value = value.replace(secret, "[redacted]").replace(quote(secret, safe=""), "[redacted]")
    return re.sub(r"(?i)(?:access_token|password|authorization|client_secret)\s*[=:]\s*[^\s&]+", "[redacted]", value)


def key_from_links(raw, credential, resource, *, required=True):
    links = raw.get("links")
    if not isinstance(links, list):
        if not required:
            return None
        raise ValueError("Oracle HCM omitted the resource key links; no key is generated")
    found = set()
    prefix = urlsplit(base_url(credential)).path + "/" + resource + "/"
    for link in links:
        if not isinstance(link, dict):
            raise ValueError("Oracle HCM returned invalid resource links")
        if link.get("rel") not in {"self", "canonical"}:
            continue
        href = link.get("href")
        try:
            if not isinstance(href, str) or len(href) > 4096 or re.search(r"[\x00-\x20\x7f]", href):
                raise ValueError()
            parts = urlsplit(href)
            if parts.scheme != "https" or parts.netloc != urlsplit(credential.tenant_url).netloc or parts.query or parts.fragment or not parts.path.startswith(prefix):
                raise ValueError()
            found.add(resource_key(parts.path[len(prefix):]))
        except ValueError:
            raise ValueError("Oracle HCM resource link changed tenant, version or resource; no link followed") from None
    if len(found) != 1:
        if not required and not found:
            return None
        raise ValueError("Oracle HCM resource key is absent or ambiguous; no key is generated")
    return found.pop()


def project(raw, credential, resource, *, expected_key=None, expected_id=None):
    if not isinstance(raw, dict):
        raise ValueError("Oracle HCM returned invalid metadata")
    id_field, fields = RESOURCES[resource]
    identity = raw.get(id_field)
    if type(identity) is not int or not 1 <= identity <= 9223372036854775807 or expected_id is not None and str(identity) != str(expected_id):
        raise ValueError("Oracle HCM returned mismatched resource identity")
    data = {"id": str(identity)}
    for field in fields:
        if field not in raw:
            continue
        value = raw[field]
        if field.endswith("Id"):
            if value is not None and (type(value) is not int or not 0 <= value <= 9223372036854775807):
                raise ValueError("Oracle HCM returned an invalid metadata ID")
            data[field] = str(value) if value is not None else None
        else:
            data[field] = safe_text(value, credential)
    key = key_from_links(raw, credential, resource, required=resource != "departmentsLov")
    if expected_key is not None and key != expected_key:
        raise ValueError("Oracle HCM returned a different resource key")
    if key is not None:
        data["resource_key"] = key
    data["name"] = data.get("Name") or data.get("LocationName") or data.get("PersonNumber") or data["id"]
    return data


def query_params(resource):
    return {"fields": ",".join(RESOURCES[resource][1]), "links": "self,canonical"}


async def get_record(credential, operation, resource, key):
    return project(await fetch(credential, operation, "GET", resource, key, params=query_params(resource)), credential, resource, expected_key=key)


async def request_operation(credential_data, config):
    credential = credential_value(credential_data)
    operation = config.operation
    if operation in LIST_RESOURCES:
        resource = LIST_RESOURCES[operation]
        params = {**query_params(resource), "offset": config.offset, "limit": config.limit}
        if isinstance(config, DatedPage) and config.effective_date is not None:
            params["effectiveDate"] = config.effective_date
        raw = await fetch(credential, operation, "GET", resource, params=params)
        items, count, actual_limit, offset, more = (raw.get(key) for key in ("items", "count", "limit", "offset", "hasMore"))
        if not isinstance(items, list) or type(count) is not int or count != len(items) or type(actual_limit) is not int or not 1 <= actual_limit <= config.limit or len(items) > actual_limit or type(offset) is not int or offset != config.offset or type(more) is not bool or more and not items:
            raise ValueError("Oracle HCM returned inconsistent paging metadata")
        values = [project(item, credential, resource) for item in items]
        identities = [(item["id"], item.get("resource_key")) for item in values]
        if len(set(identities)) != len(identities):
            raise ValueError("Oracle HCM returned duplicate page metadata")
        next_offset = offset + actual_limit if more else None
        if next_offset is not None and next_offset > MAX_OFFSET:
            raise ValueError("Oracle HCM continuation exceeds the supported bound; narrow the owned scope")
        return {"data": {"items": values, "count": count, "offset": offset, "limit": actual_limit, "has_more": more, "next_offset": next_offset}}
    if operation in GET_RESOURCES:
        resource, field = GET_RESOURCES[operation]
        return {"data": await get_record(credential, operation, resource, getattr(config, field))}
    before = None
    if not isinstance(config, CreateLocation):
        before = await get_record(credential, operation, "locationsV2", config.location_key)
    if isinstance(config, DeleteLocation):
        await fetch(credential, operation, "DELETE", "locationsV2", config.location_key, effective_of="RangeMode=DELETE_CHANGES")
        return {"data": {"location_id": before["id"], "resource_key": config.location_key, "delete_changes_accepted": True, "http_status": 204, "logical_location_absence_verified": False}}
    selected = config.model_dump(include=set(BODY_FIELDS), exclude_unset=True)
    if isinstance(config, UpdateLocation):
        selected = {key: value for key, value in selected.items() if key in {"location_name", "description"}}
    body = {BODY_FIELDS[key]: value for key, value in selected.items()}
    serialized = json.dumps(body, ensure_ascii=False)
    secrets = [credential.username, credential.password] if isinstance(credential, OracleHCMBasicCredential) else [credential.access_token]
    if any(secret in serialized for secret in secrets):
        raise ValueError("Do not put this connection's credentials in location metadata")
    effective_of = None if isinstance(config, CreateLocation) else "RangeMode=CORRECTION" if config.range_mode == "CORRECTION" else f"RangeStartDate={config.effective_start_date};RangeMode=UPDATE"
    raw = await fetch(credential, operation, "POST" if isinstance(config, CreateLocation) else "PATCH", "locationsV2", None if isinstance(config, CreateLocation) else config.location_key, body=body, effective_of=effective_of)
    data = project(raw, credential, "locationsV2", expected_id=before["id"] if before else None)
    if any(raw.get(key) != value for key, value in body.items()):
        raise ValueError("Oracle HCM location change was not confirmed; postprocessing may still be running, no automatic retry")
    readback = await fetch(credential, operation, "GET", "locationsV2", data["resource_key"], params=query_params("locationsV2"))
    result = project(readback, credential, "locationsV2", expected_key=data["resource_key"], expected_id=data["id"])
    if any(readback.get(key) != value for key, value in body.items()):
        raise ValueError("Oracle HCM location readback did not confirm supplied fields; no retry or recreation")
    return {"data": result}


class OracleHCMNode(WorkflowNode):
    integration_type = "automation-oracle-hcm"
    credential_provider_labels = {"oracle_hcm": "Oracle Fusion Cloud HCM"}
    scope_registry = ORACLE_HCM_SCOPES
    connection_evidence = ConnectionEvidence(operation="list_departments", noun="HCM department metadata", proves="reachability")
    edit_examples = ["List Oracle HCM jobs and department metadata", "Get an Oracle HCM location using its returned resource key", "Create a location in a supplied reference data set"]

    @classmethod
    def get_config_model(cls):
        return OracleHCMNodeConfig

    @classmethod
    def _require_raw(cls, raw):
        if not isinstance(raw, dict) or not isinstance(raw.get("config"), dict):
            raise ValueError("Use a native Oracle HCM configuration")
        credential_value(raw.get("credentials"))
        controls = {"url", "base_url", "endpoint", "headers", "method", "body", "params", "username", "password", "access_token", "filter", "q", "finder", "expand", "dependency", "fields", "payroll", "bank", "tax", "benefits", "worker_changes"}
        if controls.intersection(raw) or controls.intersection(raw["config"]):
            raise ValueError("Use typed HCM fields; arbitrary API and worker/financial controls are unsupported")

    @classmethod
    def parse_config(cls, config_data):
        cls._require_raw(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._require_raw(config_data)
        except ValueError:
            return {"valid": False, "errors": ["Use native HCM fields and a typed tenant-bound credential"], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        # Both families are supplied credentials; staging resolves saved access
        # before this hook. No OAuth connect or refresh flow is implied.
        return credential_value(credential_data, manual=not credential_id).model_dump()

    @classmethod
    async def validate_credential_access(cls, credential_data, **kwargs):
        try:
            credential_value(credential_data)
        except ValueError:
            return {"valid": False, "error": "Connect a typed Oracle HCM tenant-bound credential"}
        return {"valid": None, "error": "Run HCM department metadata evidence to verify reachability; it does not prove a personal identity or write privileges"}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        models = {"job_key": ListJobs, "organization_key": ListOrganizations, "location_key": ListLocations, "worker_key": ListWorkers}
        if field_name not in models:
            return {"options": [], "next_page_token": None}
        credential = credential_value(credential_data, manual=True)
        if search is not None and (not isinstance(search, str) or len(search) > 200 or re.search(r"[\x00-\x1f\x7f]", search)):
            raise ValueError("Use bounded picker search text")
        context = context if isinstance(context, dict) else {}
        if any(key in context for key in ("_tenant_url", "_api_version", "_credential_type", "_effective_date")):
            raise ValueError("Use native public picker scope fields")
        effective_date = iso_date(context["effective_date"]) if context.get("effective_date") is not None and field_name != "worker_key" else None
        query = normalize_search(search)
        binding = [credential.model_dump(), field_name, effective_date, query]
        prefix = hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24] + ":"
        offset = 0
        if page_token is not None:
            if not isinstance(page_token, str) or not page_token.startswith(prefix) or not re.fullmatch(r"0|[1-9][0-9]{0,6}", page_token[len(prefix):]) or int(page_token[len(prefix):]) > MAX_OFFSET:
                raise ValueError("Picker continuation changed current credential, tenant, version, date, field or search")
            offset = int(page_token[len(prefix):])
        config = models[field_name](offset=offset, limit=100, **({"effective_date": effective_date} if field_name != "worker_key" else {}))
        data = (await request_operation(credential, config))["data"]
        options = [{"value": item["resource_key"], "label": item["name"], "metadata": {"id": item["id"]}} for item in data["items"]]
        return {"options": filter_options_by_search(options, query), "next_page_token": prefix + str(data["next_offset"]) if data["next_offset"] is not None else None}

    async def execute(self, inputs: dict[str, Any]):
        if not isinstance(self.config, OracleHCMNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a typed Oracle HCM credential")
        # Executors may supply an already validated config without frontend data.
        # Still inspect supplied raw data so ignored wrapper fields cannot bypass
        # the native-operation boundary.
        self._require_raw(self.node_data or self.config.model_dump(exclude_unset=True))
        credential = self.config.credentials.model_dump()
        if (self.node_data or {}).get("credential_id"):
            from utils.credentials import resolve_credential_with_owner_fallback
            credential = await resolve_credential_with_owner_fallback(
                self.node_data["credential_id"], self.user_id,
                self.node_data.get("_approval_pool"), org_id=self.organization_id,
                workflow_id=self.workflow_id,
            )
            if not credential:
                raise ValueError("Oracle HCM credential unavailable, revoked or access denied")
        credential = await self.freshen_credential(credential, credential_id=(self.node_data or {}).get("credential_id"))
        return {"status": "success", "action": self.config.config.operation, **await request_operation(credential, self.config.config)}
