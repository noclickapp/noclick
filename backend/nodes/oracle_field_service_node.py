"""Oracle Field Service ofscCore/ofscMetadata/ofscCapacity, supplied application auth."""
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import base64
import hashlib
import hmac
import json
import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_serializer, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.credentials import resolve_credential_with_owner_fallback
from utils.ssrf import guarded_async_client

TYPES = {"oracle_field_service_basic", "oracle_field_service_bearer"}
MAX_BYTES = 2 * 1024 * 1024
OPERATIONS = {"list_resources", "get_resource", "list_resource_children", "list_activities", "get_activity", "create_nonscheduled_activity", "update_activity_reference", "delete_nonscheduled_activity", "list_activity_types", "get_activity_type", "list_resource_types", "list_properties", "get_property", "list_property_enumerations", "list_capacity_areas", "list_capacity_categories", "get_available_capacity"}
ID = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,18}$", max_length=19)]
ResourceID = Annotated[str, Field(min_length=1, max_length=32)]
Label = Annotated[str, Field(min_length=1, max_length=40)]
Snapshot = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
CORE = "/rest/ofscCore/v1"
META = "/rest/ofscMetadata/v1"
CATALOG = {
    "resource": (CORE + "/resources", "resourceId", ("resourceType", "status", "parentResourceId")),
    "activity": (CORE + "/activities", "activityId", ("resourceId", "activityType", "status", "date", "recordType", "apptNumber")),
    "activity_type": (META + "/activityTypes", "label", ("name", "groupLabel")),
    "resource_type": (META + "/resourceTypes", "label", ("name", "role")),
    "property": (META + "/properties", "label", ("name", "type", "entity", "gui")),
    "enumeration": (None, "label", ("name",)),
    "capacity_area": (META + "/capacityAreas", "label", ("name", "type", "status")),
    "capacity_category": (META + "/capacityCategories", "label", ("name",)),
}
RESOURCE_FIELDS = "resourceId,resourceType,status,parentResourceId"
ACTIVITY_FIELDS = "activityId,resourceId,activityType,status,date,recordType,apptNumber"


def path_label(value):
    # The public API accepts labels; reject path/query/control syntax locally.
    if not isinstance(value, str) or not 1 <= len(value) <= 255 or value in {".", ".."} or any(c in value for c in "/\\%?#,") or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Use one Field Service resource ID or metadata label")
    return value


def activity_id(value):
    if type(value) is int and 0 < value <= 9223372036854775807:
        return str(value)
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,18}", value) and int(value) <= 9223372036854775807:
        return value
    raise ValueError("Use a positive decimal Field Service activity ID")


def secret_value(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Supply a valid Field Service application credential")
    return value


class Credential(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, json_schema_extra={"x-credential-url": "https://docs.oracle.com/en/cloud/saas/field-service/cxfsc/OFSC_Authenticate_and_Authorize.html"})
    instance_name: str = Field(..., min_length=1, max_length=63, pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", repr=False, title="Deployment Host Label", description="The exact environment label before .fs.ocs.oraclecloud.com. HTTPS only; deprecated etadirect hosts and Fusion IAM endpoints are not supported.")
    service_variant: Literal["oracle_field_service"] = Field("oracle_field_service", title="Service", description="Confirm Oracle Field Service on the service About page. This credential does not establish Oracle Fusion IAM authority.", json_schema_extra={"ui:hidden": True})

    @model_serializer(mode="wrap")
    def canonical(self, handler):
        return {**handler(self), "credential_type": self.credential_type, "service_variant": self.service_variant}


class OracleFieldServiceBasicCredential(Credential):
    model_config = ConfigDict(title="Oracle Field Service Basic")
    credential_type: Literal["oracle_field_service_basic"] = Field("oracle_field_service_basic", json_schema_extra={"ui:hidden": True})
    auth_instance_name: str = Field(..., min_length=1, max_length=256, repr=False, title="Authentication Instance Name", description="The exact INSTANCE_NAME or alternate instance name from your service console. It can differ from the deployment label; their relationship must be verified by the owner.")
    client_id: str = Field(..., min_length=1, max_length=256, repr=False, title="Registered Application Client ID")
    client_secret: str = Field(..., min_length=1, max_length=4096, repr=False, title="Registered Application Client Secret", json_schema_extra={"ui:widget": "password"})
    _secret = field_validator("client_secret")(secret_value)

    @field_validator("auth_instance_name", "client_id")
    @classmethod
    def basic_components(cls, value):
        secret_value(value)
        if any(c.isspace() or c in ":@" for c in value):
            raise ValueError("Use the exact registered application and instance names")
        return value


class OracleFieldServiceBearerCredential(Credential):
    model_config = ConfigDict(title="Oracle Field Service Bearer Token")
    credential_type: Literal["oracle_field_service_bearer"] = Field("oracle_field_service_bearer", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=4096, repr=False, title="Supplied OAuth Bearer Token", description="A token issued for this deployment/application by the documented Field Service token service. No automatic mint, JWT assertion or refresh is performed.", json_schema_extra={"ui:widget": "password"})
    expires_at: datetime | None = Field(None, repr=False, title="Actual Token Expiry", description="Supply the actual timezone-qualified expiry if known. The sample expires_in=3600 is not assumed. Without this, expiration is known only when the provider rejects the token.")

    @field_validator("access_token")
    @classmethod
    def bearer_text(cls, value):
        secret_value(value)
        if any(c.isspace() for c in value):
            raise ValueError("Supply one Field Service bearer token")
        return value

    @field_validator("expires_at")
    @classmethod
    def aware_expiry(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Field Service expiry must include a timezone")
        return value


Credentials = Union[OracleFieldServiceBasicCredential, OracleFieldServiceBearerCredential]


def guard(data):
    if not isinstance(data, dict) or data.get("credential_type") not in TYPES:
        raise ValueError("Connect a typed Oracle Field Service application credential")
    model = OracleFieldServiceBasicCredential if data["credential_type"] == "oracle_field_service_basic" else OracleFieldServiceBearerCredential
    try:
        return model.model_validate({k: v for k, v in data.items() if k not in {"_ofsc_reader", "token_version", "updated_at"}})
    except ValueError:
        raise ValueError("Oracle Field Service credential is invalid; reconnect it") from None


def authority(value):
    grant = (value.auth_instance_name, value.client_id, value.client_secret) if isinstance(value, OracleFieldServiceBasicCredential) else (value.access_token, value.expires_at.isoformat() if value.expires_at else None)
    return value.credential_type, value.service_variant, value.instance_name, *grant


async def current(credential_id, user_id, organization_id=None, workflow_id=None, *, pool=None):
    if not user_id:
        raise ValueError("Stored Field Service credentials require a caller")
    data = await resolve_credential_with_owner_fallback(
        credential_id, user_id, pool, org_id=organization_id, workflow_id=workflow_id
    )
    if data is None:
        raise ValueError("Field Service credential is unavailable or revoked")
    return guard(data)


@dataclass(repr=False)
class Reader:
    credential_id: Any
    user_id: Any
    organization_id: Any = None
    workflow_id: Any = None
    pool: Any = None
    anchor: Any = field(default=None, repr=False)
    expected: Any = field(default=None, repr=False)

    async def read(self):
        value = await current(self.credential_id, self.user_id, self.organization_id, self.workflow_id, pool=self.pool)
        if self.expected is not None and authority(value) != self.expected:
            raise ValueError("Field Service cached credential changed; reload it")
        binding = authority(value)
        if self.anchor is not None and self.anchor != binding:
            raise ValueError("Field Service saved credential changed during this call; inspect before retrying")
        self.anchor = binding
        return value


def op(value, title, category):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": category, "x-is-trigger": False})


def resource(name, parent=None):
    options = {"field_name": name, "searchable": True, "allow_custom": True}
    if parent:
        options["depends_on"] = parent
    return {"x-resource-type": "oracle_field_service_" + name.removesuffix("_id").removesuffix("_label"), "x-dynamic-options": options}


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    _activity = field_validator("activity_id", mode="before", check_fields=False)(activity_id)
    _labels = field_validator("resource_id", "activity_type_label", "property_label", "capacity_area_label", mode="before", check_fields=False)(path_label)


class Page(Input):
    offset: StrictInt = Field(0, ge=0, le=1000000, title="Offset")
    limit: StrictInt = Field(50, ge=1, le=100, title="Page Size", description="Returns one page; the local maximum is 100, including the activity endpoint whose provider maximum is larger.")


class Resource(Input):
    resource_id: ResourceID = Field(..., title="Resource", description="Exact external resource ID. Resource names and personal contact details are not returned.", json_schema_extra=resource("resource_id"))


class Activity(Resource):
    activity_id: ID = Field(..., title="Activity", json_schema_extra=resource("activity_id", "resource_id"))


class ListResources(Page):
    operation: Literal["list_resources"] = op("list_resources", "List Resource Metadata", "Resources")


class GetResource(Resource):
    operation: Literal["get_resource"] = op("get_resource", "Get Resource Metadata", "Resources")


class ListChildren(Resource, Page):
    operation: Literal["list_resource_children"] = op("list_resource_children", "List Child Resource Metadata", "Resources")


class ListActivities(Resource, Page):
    operation: Literal["list_activities"] = op("list_activities", "List Activity Metadata", "Activities")
    date_from: date | None = Field(None, title="From Date", description="Omit both dates to retrieve only non-scheduled activities. Descendant resources are always excluded.")
    date_to: date | None = Field(None, title="To Date")
    status: Literal["pending", "started", "suspended", "cancelled", "completed", "notdone", "enroute"] | None = Field(None, title="Status")

    @model_validator(mode="after")
    def dates(self):
        if (self.date_from is None) != (self.date_to is None) or self.date_from and not 0 <= (self.date_to - self.date_from).days <= 31:
            raise ValueError("Supply both dates in an ordered range of at most 31 days")
        return self


class GetActivity(Activity):
    operation: Literal["get_activity"] = op("get_activity", "Get Activity Metadata", "Activities")


class CreateActivity(Resource):
    operation: Literal["create_nonscheduled_activity"] = op("create_nonscheduled_activity", "Create Non-Scheduled Bucket Activity", "Activities")
    activity_type_label: Label = Field(..., title="Activity Type", json_schema_extra=resource("activity_type_label"))
    appointment_reference: str = Field(..., min_length=1, max_length=40, repr=False, title="Appointment Reference", description="A unique owner-selected integration reference (apptNumber). No customer data, date, technician assignment or route position is sent. Site rules may still run.")


class UpdateActivity(Activity):
    operation: Literal["update_activity_reference"] = op("update_activity_reference", "Update Bucket Activity Reference", "Activities")
    appointment_reference: str = Field(..., min_length=1, max_length=40, repr=False, title="New Appointment Reference")
    expected_snapshot: Snapshot = Field(..., title="Expected Metadata Snapshot", description="From Get Activity Metadata. A local precondition, not an atomic provider write condition.")


class DeleteActivity(Activity):
    operation: Literal["delete_nonscheduled_activity"] = op("delete_nonscheduled_activity", "Delete Non-Scheduled Bucket Activity", "Activities")
    expected_snapshot: Snapshot = Field(..., title="Expected Metadata Snapshot")
    expected_reference: str = Field(..., min_length=1, max_length=40, repr=False, title="Expected Appointment Reference", description="Only pending regular non-scheduled bucket activities with this reference are accepted. Oracle additionally checks its delete conditions; deletion is not cancellation.")


class ListActivityTypes(Page):
    operation: Literal["list_activity_types"] = op("list_activity_types", "List Activity Types", "Metadata")


class GetActivityType(Input):
    operation: Literal["get_activity_type"] = op("get_activity_type", "Get Activity Type", "Metadata")
    activity_type_label: Label = Field(..., title="Activity Type", json_schema_extra=resource("activity_type_label"))


class ListResourceTypes(Page):
    operation: Literal["list_resource_types"] = op("list_resource_types", "List Resource Types", "Metadata")


class ListProperties(Page):
    operation: Literal["list_properties"] = op("list_properties", "List Property Definitions", "Metadata")
    entity: Literal["activity", "resource"] = Field("activity", title="Property Entity")


class Property(Input):
    entity: Literal["activity", "resource"] = Field("activity", title="Property Entity")
    property_label: Label = Field(..., title="Property", json_schema_extra=resource("property_label", "entity"))


class GetProperty(Property):
    operation: Literal["get_property"] = op("get_property", "Get Property Definition", "Metadata")


class ListEnumerations(Property, Page):
    operation: Literal["list_property_enumerations"] = op("list_property_enumerations", "List Property Enumeration Values", "Metadata")


class ListCapacityAreas(Input):
    operation: Literal["list_capacity_areas"] = op("list_capacity_areas", "List Capacity Area Metadata", "Capacity")


class ListCapacityCategories(Page):
    operation: Literal["list_capacity_categories"] = op("list_capacity_categories", "List Capacity Categories", "Capacity")


class GetCapacity(Input):
    operation: Literal["get_available_capacity"] = op("get_available_capacity", "Get Available Capacity", "Capacity")
    capacity_area_label: Label = Field(..., title="Capacity Area", json_schema_extra=resource("capacity_area_label"))
    dates: list[date] = Field(..., min_length=1, max_length=31, title="Dates", description="Explicit dates; this reads working-calendar and estimated available capacity without changing quota or booking.")

    @field_validator("dates")
    @classmethod
    def unique_dates(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Choose distinct capacity dates")
        return value


Config = Annotated[Union[ListResources, GetResource, ListChildren, ListActivities, GetActivity, CreateActivity, UpdateActivity, DeleteActivity, ListActivityTypes, GetActivityType, ListResourceTypes, ListProperties, GetProperty, ListEnumerations, ListCapacityAreas, ListCapacityCategories, GetCapacity], Field(discriminator="operation")]


class OracleFieldServiceNodeConfig(NodeConfig[Config, Credentials]):
    model_config = ConfigDict(hide_input_in_errors=True)


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def reject_number(_value):
    raise ValueError("Non-finite JSON number")


async def request(value, method, path, *, params=None, body=None, reader=None, missing=False):
    fixed_get = {entry[0] for entry in CATALOG.values() if entry[0]} | {"/rest/ofscCapacity/v1/capacity"}
    dynamic_get = re.fullmatch(r"/rest/ofscCore/v1/(?:resources/[^/]+(?:/children)?|activities/[1-9][0-9]*)|/rest/ofscMetadata/v1/(?:activityTypes/[^/]+|properties/[^/]+(?:/enumerationList)?|capacityAreas/[^/]+)", path)
    allowed = method == "GET" and (path in fixed_get or dynamic_get)
    allowed = allowed or method == "POST" and path == CORE + "/activities" or method in {"PATCH", "DELETE"} and re.fullmatch(r"/rest/ofscCore/v1/activities/[1-9][0-9]*", path)
    if not allowed:
        raise ValueError("Unsupported Field Service route")
    if reader:
        value = await reader.read()
    if isinstance(value, OracleFieldServiceBearerCredential) and value.expires_at and value.expires_at <= datetime.now(timezone.utc):
        raise ValueError("Field Service bearer token expired; reconnect explicitly")
    token = "Basic " + base64.b64encode((value.client_id + "@" + value.auth_instance_name + ":" + value.client_secret).encode()).decode() if isinstance(value, OracleFieldServiceBasicCredential) else "Bearer " + value.access_token
    headers = {"Authorization": token, "Accept": "application/json", "Cache-Control": "no-store"}
    if body is not None:
        if len(json.dumps(body, allow_nan=False).encode()) > MAX_BYTES:
            raise ValueError("Field Service request exceeded the local size limit")
        headers["Content-Type"] = "application/json"
    expected = 201 if method == "POST" else 204 if method == "DELETE" else 200
    try:
        async with guarded_async_client(timeout=12, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, "https://" + value.instance_name + ".fs.ocs.oraclecloud.com" + path, params=params, json=body, headers=headers) as response:
                status = response.status_code
                if status != expected and not (missing and method == "GET" and status == 404):
                    hint = "application/token and instance" if status == 401 else "application API permissions and resource visibility" if status == 403 else "rate/concurrency limits; retry manually" if status == 429 else "resource contract or service availability"
                    raise ValueError(f"Field Service request failed (HTTP {status}); check {hint}")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise ValueError("Field Service response exceeded the 2 MiB local limit")
                if status not in {204, 404} and response.headers.get("content-type", "").split(";", 1)[0].strip().lower() not in {"application/json", "application/schema+json"}:
                    raise ValueError("Field Service returned an unexpected response format")
    except httpx.HTTPError:
        raise ValueError("Field Service connection failed; inspect before retrying") from None
    if reader:
        await reader.read()
    if status == 404:
        return None
    if status == 204:
        if data:
            raise ValueError("Field Service returned an unexpected delete body; inspect before retrying")
        return {"deletion_accepted": True}
    try:
        return json.loads(data, object_pairs_hook=unique_json, parse_constant=reject_number)
    except (ValueError, UnicodeError):
        raise ValueError("Malformed Field Service JSON response") from None


def record(payload, kind, expected=None, parent=None):
    if not isinstance(payload, dict):
        raise ValueError("Unexpected Field Service metadata envelope")
    _, id_key, texts = CATALOG[kind]
    identifier = activity_id(payload.get(id_key)) if kind == "activity" else path_label(payload.get(id_key))
    if expected is not None and identifier != expected:
        raise ValueError("Field Service returned a different resource")
    result = {"id": identifier}
    for key in texts:
        item = payload.get(key)
        if item is not None and (not isinstance(item, str) or len(item) > 4096):
            raise ValueError("Malformed Field Service metadata")
        result[key] = item
    if kind == "resource" and len(identifier) > 32 or kind not in {"resource", "activity", "enumeration"} and len(identifier) > 40:
        raise ValueError("Field Service returned an invalid metadata identifier")
    if kind == "activity":
        if parent is not None and result["resourceId"] != parent:
            raise ValueError("Field Service activity belongs to a different resource")
        if result["resourceId"] is not None:
            path_label(result["resourceId"])
    if kind == "resource" and parent is not None and result["parentResourceId"] != parent:
        raise ValueError("Field Service returned a child from a different parent")
    if kind == "property" and parent is not None and result["entity"] != parent:
        raise ValueError("Field Service property belongs to a different entity")
    if kind in {"activity_type", "resource_type", "enumeration", "capacity_category"}:
        active = payload.get("active")
        if active is not None and type(active) is not bool:
            raise ValueError("Malformed Field Service active flag")
        result["active"] = active
    if kind == "activity_type":
        features = payload.get("features", {})
        if not isinstance(features, dict) or any(type(v) is not bool for v in features.values()):
            raise ValueError("Malformed Field Service activity type features")
        result["features"] = {k: features.get(k) for k in ("allowCreationInBuckets", "allowNonScheduled", "isSegmentingEnabled", "isTeamworkAvailable")}
    # No personal resource names, customer addresses, custom property values,
    # images, file links or provider-controlled URLs escape this projection.
    return result


def page_record(payload, kind, offset, limit, parent=None):
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list) or len(payload["items"]) > limit:
        raise ValueError("Unexpected Field Service page envelope")
    for key, expected in (("offset", offset), ("limit", limit)):
        if key in payload and (type(payload[key]) is not int or payload[key] != expected):
            raise ValueError("Field Service returned different paging parameters")
    rows = [record(row, kind, parent=parent) for row in payload["items"]]
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("Field Service page repeated an ID")
    total = payload.get("totalResults")
    if total is not None and (type(total) is not int or total < 0):
        raise ValueError("Malformed Field Service page total")
    if "hasMore" in payload:
        if type(payload["hasMore"]) is not bool:
            raise ValueError("Malformed Field Service continuation flag")
        more = payload["hasMore"]
    elif kind == "activity":
        more = False  # The activity contract explicitly makes absent hasMore terminal.
    else:
        # Older documented envelopes omit hasMore/counts. A full page requires
        # another read, rather than claiming the visible inventory is complete.
        more = offset + len(rows) < total if total is not None else len(rows) == limit
    if more and not rows:
        raise ValueError("Field Service continuation did not advance")
    return {"items": rows, "count": len(rows), "offset": offset, "limit": limit, "total_results": total, "has_more": more, "next_offset": offset + len(rows) if more else None}


def snapshot(item):
    return hashlib.sha256(json.dumps(item, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def continuation(value, scope, offset):
    raw = json.dumps({"scope": snapshot(scope), "offset": offset}, sort_keys=True, separators=(",", ":"))
    return raw + "." + hmac.new(json.dumps(authority(value)).encode(), raw.encode(), hashlib.sha256).hexdigest()


def read_continuation(token, value, scope):
    if token is None:
        return 0
    try:
        if not isinstance(token, str) or not 1 <= len(token) <= 4096:
            raise ValueError()
        raw, _signature = token.rsplit(".", 1)
        saved = json.loads(raw)
        if saved["scope"] != snapshot(scope) or type(saved["offset"]) is not int or not 1 <= saved["offset"] <= 1000000 or not hmac.compare_digest(token, continuation(value, scope, saved["offset"])):
            raise ValueError()
        return saved["offset"]
    except (ValueError, KeyError, TypeError):
        raise ValueError("Field Service continuation does not match this tenant, grant, resource and search") from None


class OracleFieldServiceNode(WorkflowNode):
    integration_type = "automation-oracle-field-service"
    credential_provider_labels = {"oracle_field_service": "Oracle Field Service"}
    connection_evidence = ConnectionEvidence(operation="list_resources", noun="visible resources", proves="reachability", label_keys=("id",))

    @classmethod
    def get_config_model(cls):
        return OracleFieldServiceNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        if isinstance(config_data, dict) and config_data.get("credentials"):
            config_data = {**config_data, "credentials": guard(config_data["credentials"]).model_dump()}
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        if isinstance(config_data, dict) and config_data.get("credentials"):
            try:
                config_data = {**config_data, "credentials": guard(config_data["credentials"]).model_dump()}
            except ValueError as error:
                return {"valid": False, "errors": [str(error)], "satisfied_set": None}
        return super().validate_config(config_data)

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        return await cls._load_credential(credential_data, pool=pool, user_id=user_id, credential_id=credential_id)

    @classmethod
    async def _load_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None, workflow_id=None, organization_id=None):
        value = guard(credential_data)
        if credential_id:
            reader = Reader(credential_id, user_id, organization_id, workflow_id, pool, expected=authority(value))
            value = await reader.read()
            return {**value.model_dump(), "_ofsc_reader": reader}
        return value.model_dump()

    @staticmethod
    async def _get(value, kind, identifier, reader, parent=None):
        params = {"fields": RESOURCE_FIELDS} if kind == "resource" else {"fields": "label,name,type,status"} if kind == "capacity_area" else {"language": "en-US"} if kind != "activity" else None
        return record(await request(value, "GET", CATALOG[kind][0] + "/" + quote(identifier, safe=""), params=params, reader=reader), kind, identifier, parent)

    @classmethod
    async def _list(cls, value, kind, offset, limit, reader, parent=None, dates=None, status=None):
        params = {"offset": offset, "limit": limit}
        path = CATALOG[kind][0]
        if kind == "resource":
            params["fields"] = RESOURCE_FIELDS
            if parent:
                await cls._get(value, "resource", parent, reader)
                path += "/" + quote(parent, safe="") + "/children"
        elif kind == "activity":
            await cls._get(value, "resource", parent, reader)
            params.update(resources=parent, includeChildren="none", includeNonScheduled="true", fields=ACTIVITY_FIELDS)
            if dates:
                params.update(dateFrom=dates[0].isoformat(), dateTo=dates[1].isoformat())
            if status:
                params["q"] = "status=='" + status + "'"
        elif kind == "enumeration":
            entity, label = parent
            prop = await cls._get(value, "property", label, reader, entity)
            if prop["type"] != "enumeration":
                raise ValueError("Select an enumeration property")
            path = META + "/properties/" + quote(label, safe="") + "/enumerationList"
            params["language"] = "en-US"
        else:
            params["language"] = "en-US"
            if kind == "property":
                params["entity"] = parent
        return page_record(await request(value, "GET", path, params=params, reader=reader), kind, offset, limit, parent if kind in {"resource", "activity", "property"} else None)

    @staticmethod
    async def _areas(value, reader):
        payload = await request(value, "GET", META + "/capacityAreas", params={"fields": "label,name,type,status"}, reader=reader)
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list) or len(payload["items"]) > 1000:
            raise ValueError("Unexpected or oversized Field Service capacity area inventory")
        items = [record(row, "capacity_area") for row in payload["items"]]
        if len({item["id"] for item in items}) != len(items):
            raise ValueError("Field Service repeated a capacity area")
        return {"items": items, "count": len(items)}

    @classmethod
    async def _bucket(cls, value, identifier, reader):
        item = await cls._get(value, "resource", identifier, reader)
        if item["status"] != "active" or not item["resourceType"]:
            raise ValueError("Select an active Field Service bucket")
        # No by-label resourceType endpoint is documented: bounded full lookup.
        for offset in range(0, 1000, 100):
            page = await cls._list(value, "resource_type", offset, 100, reader)
            match = next((row for row in page["items"] if row["id"] == item["resourceType"]), None)
            if match:
                if match["role"] != "bucket" or match["active"] is not True:
                    raise ValueError("Activity writes require an active bucket, not a technician")
                return
            if not page["has_more"]:
                break
        raise ValueError("Bucket resource type could not be verified within 1000 types")

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        lookup = {"resource_id": "resource", "activity_id": "activity", "activity_type_label": "activity_type", "property_label": "property", "capacity_area_label": "capacity_area"}
        if field_name not in lookup:
            return {"options": [], "next_page_token": None}
        value, context = guard(credential_data), context or {}
        reader = credential_data.get("_ofsc_reader")
        kind = lookup[field_name]
        search = search or ""
        if not isinstance(search, str) or len(search) > 256 or any(ord(c) < 32 for c in search):
            raise ValueError("Use up to 256 characters of metadata search text")
        parent = path_label(context.get("resource_id")) if kind == "activity" else context.get("entity", "activity") if kind == "property" else None
        if kind == "property" and parent not in {"activity", "resource"}:
            raise ValueError("Select the activity or resource property entity")
        scope = {"kind": kind, "parent": parent, "search": search, "limit": 50, "mode": "nonscheduled" if kind == "activity" else "metadata"}
        offset = read_continuation(page_token, value, scope)
        if kind == "capacity_area":
            if offset:
                raise ValueError("Capacity area inventory has no documented pagination")
            page = await cls._areas(value, reader)
            page["has_more"] = False
        else:
            page = await cls._list(value, kind, offset, 50, reader, parent)
        items = [item for item in page["items"] if search.casefold() in ((item.get("name") or "") + " " + item["id"]).casefold()]
        return {"options": [{"value": item["id"], "label": (item.get("name") or kind.replace("_", " ").title()) + " · " + item["id"]} for item in items], "next_page_token": continuation(value, scope, page["next_offset"]) if page["has_more"] else None}

    async def execute(self, input_data):
        cfg = self.config.config
        raw = self.node_data.get("credentials") or (self.config.credentials.model_dump() if self.config.credentials is not None else None)
        data = await self._load_credential(raw, credential_id=self.node_data.get("credential_id"), user_id=self.user_id, workflow_id=self.workflow_id, organization_id=self.organization_id, pool=self.node_data.get("_approval_pool"))
        value, reader = guard(data), data.get("_ofsc_reader")
        operation = cfg.operation
        list_kinds = {"list_resources": "resource", "list_resource_children": "resource", "list_activities": "activity", "list_activity_types": "activity_type", "list_resource_types": "resource_type", "list_properties": "property", "list_property_enumerations": "enumeration", "list_capacity_categories": "capacity_category"}
        if operation in list_kinds:
            parent = cfg.resource_id if operation in {"list_resource_children", "list_activities"} else cfg.entity if operation == "list_properties" else (cfg.entity, cfg.property_label) if operation == "list_property_enumerations" else None
            dates = (cfg.date_from, cfg.date_to) if operation == "list_activities" and cfg.date_from else None
            return await self._list(value, list_kinds[operation], cfg.offset, cfg.limit, reader, parent, dates, getattr(cfg, "status", None))
        if operation == "list_capacity_areas":
            return await self._areas(value, reader)
        if operation == "get_resource":
            return await self._get(value, "resource", cfg.resource_id, reader)
        if operation == "get_activity_type":
            return await self._get(value, "activity_type", cfg.activity_type_label, reader)
        if operation == "get_property":
            return await self._get(value, "property", cfg.property_label, reader, cfg.entity)
        if operation == "get_available_capacity":
            area = await self._get(value, "capacity_area", cfg.capacity_area_label, reader)
            payload = await request(value, "GET", "/rest/ofscCapacity/v1/capacity", params={"areas": area["id"], "dates": ",".join(d.isoformat() for d in cfg.dates), "aggregateResults": "false", "fields": "area.calendar.count,area.calendar.minutes,area.available.count,area.available.minutes", "availableTimeIntervals": "all", "calendarTimeIntervals": "all"}, reader=reader)
            return capacity_record(payload, area["id"], {d.isoformat() for d in cfg.dates})
        if operation == "create_nonscheduled_activity":
            await self._bucket(value, cfg.resource_id, reader)
            activity_type = await self._get(value, "activity_type", cfg.activity_type_label, reader)
            features = activity_type["features"]
            if activity_type["active"] is not True or features["allowCreationInBuckets"] is not True or features["allowNonScheduled"] is not True or features["isSegmentingEnabled"] is not False or features["isTeamworkAvailable"] is not False:
                raise ValueError("Select an active regular type allowing non-scheduled bucket activities")
            body = {"resourceId": cfg.resource_id, "activityType": cfg.activity_type_label, "apptNumber": cfg.appointment_reference}
            created = record(await request(value, "POST", CORE + "/activities", body=body, reader=reader), "activity", parent=cfg.resource_id)
            result = await self._get(value, "activity", created["id"], reader, cfg.resource_id)
            check_nonscheduled(result)
            if result["activityType"] != cfg.activity_type_label or result["apptNumber"] != cfg.appointment_reference:
                raise ValueError("Activity created but readback differs; inspect before retrying")
            return {**result, "snapshot": snapshot(result), "created": True}
        original = await self._get(value, "activity", cfg.activity_id, reader, cfg.resource_id)
        if operation == "get_activity":
            return {**original, "snapshot": snapshot(original)}
        check_nonscheduled(original)
        await self._bucket(value, cfg.resource_id, reader)
        if snapshot(original) != cfg.expected_snapshot:
            raise ValueError("Activity metadata changed; read it again before writing")
        if operation == "update_activity_reference":
            updated = record(await request(value, "PATCH", CORE + "/activities/" + cfg.activity_id, body={"apptNumber": cfg.appointment_reference}, reader=reader), "activity", cfg.activity_id, cfg.resource_id)
            result = await self._get(value, "activity", updated["id"], reader, cfg.resource_id)
            check_nonscheduled(result)
            if result["apptNumber"] != cfg.appointment_reference:
                raise ValueError("Activity reference readback differs; inspect before retrying")
            return {**result, "snapshot": snapshot(result), "updated": True}
        if operation == "delete_nonscheduled_activity":
            if original["apptNumber"] != cfg.expected_reference:
                raise ValueError("Activity reference does not match the disposable record")
            await request(value, "DELETE", CORE + "/activities/" + cfg.activity_id, reader=reader)
            remaining = await request(value, "GET", CORE + "/activities/" + cfg.activity_id, reader=reader, missing=True)
            if remaining is not None:
                record(remaining, "activity", cfg.activity_id, cfg.resource_id)
                raise ValueError("Delete accepted but activity is still visible; inspect before retrying")
            return {"id": cfg.activity_id, "resource_id": cfg.resource_id, "deletion_accepted": True, "absence_observed": True, "absence_status": 404}
        raise ValueError("Unsupported Field Service operation")


def check_nonscheduled(item):
    if item["status"] != "pending" or item["date"] is not None or item["recordType"] != "regular":
        raise ValueError("Activity writes require a pending regular non-scheduled bucket record")


def capacity_record(payload, area, dates):
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list) or len(payload["items"]) > len(dates):
        raise ValueError("Unexpected Field Service capacity envelope")
    result, seen = [], set()
    for item in payload["items"]:
        if not isinstance(item, dict) or item.get("date") not in dates or item["date"] in seen or not isinstance(item.get("areas"), list):
            raise ValueError("Field Service capacity returned a different or repeated date")
        seen.add(item["date"])
        areas = []
        for entry in item["areas"]:
            if not isinstance(entry, dict) or entry.get("label") != area or areas:
                raise ValueError("Field Service capacity belongs to a different or repeated area")
            projected = {"label": area}
            for key in ("calendar", "available"):
                groups = entry.get(key, [])
                if not isinstance(groups, list) or len(groups) > 1:
                    raise ValueError("Malformed Field Service capacity interval")
                projected[key] = []
                for group in groups:
                    if not isinstance(group, dict):
                        raise ValueError("Malformed Field Service capacity interval")
                    metrics = {}
                    for metric in ("count", "minutes"):
                        numbers = group.get(metric, [])
                        if not isinstance(numbers, list) or len(numbers) > 1 or any(type(n) is not int for n in numbers):
                            raise ValueError("Malformed Field Service capacity metric")
                        metrics[metric] = numbers
                    projected[key].append(metrics)
            areas.append(projected)
        result.append({"date": item["date"], "areas": areas})
    return {"items": result, "count": len(result), "requested_dates": sorted(dates), "capacity_area_label": area}
