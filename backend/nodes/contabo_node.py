"""Native Contabo compute metadata reads; supplied bearer tokens are never minted here."""
from __future__ import annotations

import json
import logging
import math
import re
from contextvars import ContextVar
from datetime import datetime
from typing import Annotated, Literal, Optional, Union
from uuid import uuid4

import httpx
from opentelemetry.instrumentation.utils import suppress_http_instrumentation
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_serializer
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

TYPE = "contabo_bearer"
API = "https://api.contabo.com"
MAX_BODY = 4 * 1024 * 1024
UNVERIFIED = "Contabo response could not be verified"
OPAQUE_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}"
OpaqueID = Annotated[StrictStr, Field(pattern="^" + OPAQUE_PATTERN + "$", min_length=1, max_length=128)]
InstanceID = Annotated[StrictInt, Field(ge=1, le=9223372036854775807)]
Page = Annotated[StrictInt, Field(ge=1, le=1000000)]
Size = Annotated[StrictInt, Field(ge=1, le=100)]
Text = Annotated[StrictStr, Field(max_length=255)]
def numeric_capacity(value):
    if type(value) not in (int, float) or value < 0 or type(value) is float and not math.isfinite(value):
        raise ValueError("Invalid numeric capacity")
    return value


Number = Annotated[Union[StrictInt, StrictFloat], BeforeValidator(numeric_capacity)]
State = Literal["provisioning", "uninstalled", "running", "stopped", "error", "installing", "unknown", "manual_provisioning", "product_not_available", "verification_required", "rescue", "pending_payment", "other", "reset_password"]


def token(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 16384 or any(ord(c) < 33 or ord(c) > 126 for c in value) or value.lower().startswith(("http:", "https:", "bearer ", "basic ")):
        raise ValueError("Supply the issued access token without a URL, whitespace or authentication prefix")
    return value


def witness_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) > 9223372036854775807:
        raise ValueError("Expected instance ID must be a canonical positive decimal ID")
    return value


class ContaboBearerCredential(BaseModel):
    model_config = ConfigDict(title="Contabo Bearer Token", extra="ignore", hide_input_in_errors=True, json_schema_extra={
        "x-credential-help-url": "https://api.contabo.com/",
        "x-credential-instructions": "Supply an existing Contabo access token authorized for the required compute GETs. Contabo's documented password grant uses four separate credentials; this node does not exchange, refresh or mint tokens. Replace an expired token manually. Connection reads protected instance metadata and proves scoped resource reachability, not principal/customer identity. The optional expected instance is an existing resource witness.",
    })
    credential_type: Literal["contabo_bearer"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    access_token: Annotated[StrictStr, BeforeValidator(token)] = Field(..., title="Access Token", repr=False, json_schema_extra={"ui:widget": "password"})
    expected_instance_id: Optional[Annotated[StrictStr, BeforeValidator(witness_id), Field(pattern=r"^[1-9][0-9]{0,18}$", min_length=1, max_length=19)]] = Field(None, title="Expected Instance ID", description="Optional exact existing instance ID as decimal text. Every operation independently verifies this resource; no customer or tenant identity is inferred.")

    @model_serializer(mode="wrap")
    def connect_tag(self, handler):
        return {**handler(self), "credential_type": TYPE}


def credential(raw):
    if not isinstance(raw, dict) or raw.get("credential_type") != TYPE:
        raise ValueError("Contabo requires its original supplied Bearer credential")
    try:
        return ContaboBearerCredential.model_validate(raw)
    except Exception:
        raise ValueError("Contabo credential fields are invalid") from None


def raw_guard(data):
    if isinstance(data, dict) and data.get("credentials") is not None:
        raw = data["credentials"]
        if not isinstance(raw, dict) or raw.get("credential_type") != TYPE:
            raise ValueError("Contabo credential type is not supported")


def op(value, title, description):
    return Field(value, title=title, description=description, json_schema_extra={"const": value, "ui:hidden": True, "x-display-name": title, "x-category": "Cloud Metadata", "x-is-trigger": False})


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    include_names: StrictBool = Field(False, title="Include Resource Names", description="Opt in to instance display names, image and snapshot names. Internal host names, IPs, customer IDs, URLs, notes, credentials and configuration are always omitted.")


class Paging(Config):
    page: Page = Field(1, title="Page", description="Documented one-based page; this node reads one page without following returned links. Local maximum is 1,000,000.")
    page_size: Size = Field(20, title="Page Size", description="Sent as the documented size query. Local bound is 1–100; no undocumented provider cap is claimed.")


class ListInstances(Paging):
    operation: Literal["list_instances"] = op("list_instances", "List Instance Metadata", "Read one protected instance page with IDs, states, time, capacity, region and OS metadata.")


class GetInstance(Config):
    operation: Literal["get_instance"] = op("get_instance", "Get Instance Metadata", "Read the exact protected numeric instance ID and verify the singleton data array.")
    instance_id: InstanceID = Field(..., title="Instance ID", description="Existing positive numeric instance ID. Enter it explicitly; strings, fractions and booleans are refused.")


class ListImages(Paging):
    operation: Literal["list_images"] = op("list_images", "List Image Metadata", "Read one image page with IDs, format, sizes, OS/version and standard/custom flags. No source URLs or error text.")


class GetImage(Config):
    operation: Literal["get_image"] = op("get_image", "Get Image Metadata", "Read the exact existing image ID and verify the singleton data array.")
    image_id: OpaqueID = Field(..., title="Image ID", description="Existing image ID; the saved-credential picker uses numeric pages and custom entry remains available.", json_schema_extra={"x-dynamic-options": {"allow_custom": True}})


class ListSnapshots(Paging):
    operation: Literal["list_snapshots"] = op("list_snapshots", "List Instance Snapshot Metadata", "First verify the exact parent instance, then read one page whose snapshots all match that parent.")
    instance_id: InstanceID = Field(..., title="Instance ID", description="Explicit existing numeric parent. No cross-instance lookup or control operation.")


class GetSnapshot(Config):
    operation: Literal["get_snapshot"] = op("get_snapshot", "Get Instance Snapshot Metadata", "Verify the instance parent and exact snapshot ID; metadata only, no restore or download.")
    instance_id: InstanceID = Field(..., title="Instance ID", description="Explicit existing positive numeric parent.")
    snapshot_id: OpaqueID = Field(..., title="Snapshot ID", description="Explicit existing snapshot ID such as snap1628603855. This integration does not infer ancestry from its text.")


class ImageStats(Config):
    operation: Literal["image_stats"] = op("image_stats", "Get Custom Image Capacity", "Read documented currentImagesCount and total/used/free image MB only; no customer or tenant fields.")


OPERATIONS = (ListInstances, GetInstance, ListImages, GetImage, ListSnapshots, GetSnapshot, ImageStats)
ContaboConfig = Annotated[Union[ListInstances, GetInstance, ListImages, GetImage, ListSnapshots, GetSnapshot, ImageStats], Field(discriminator="operation")]


class ContaboNodeConfig(NodeConfig[ContaboConfig, ContaboBearerCredential]):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    node_type: Literal["automation-contabo"] = "automation-contabo"

_PRIVATE = ContextVar("contabo_private_transport", default=False)


class _PrivateFilter(logging.Filter):
    def filter(self, record):
        if _PRIVATE.get():
            record.msg, record.args = "Contabo transport activity", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return True


_FILTER = _PrivateFilter()


class ApiError(ValueError):
    def __init__(self, status):
        self.status_code = status
        meaning = "access token is invalid or expired" if status == 401 else "required metadata read permission is absent" if status == 403 else "request outcome is not successful"
        super().__init__(f"Contabo returned HTTP {status}: {meaning}")


class OutcomeUnverified(RuntimeError):
    pass


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


async def request(auth, route, params=None):
    if not re.fullmatch(r"/v1/compute/(?:instances(?:/[1-9][0-9]{0,18}(?:/snapshots(?:/" + OPAQUE_PATTERN + r")?)?)?|images(?:/(?:stats|" + OPAQUE_PATTERN + r"))?)", route):
        raise ValueError("Unsupported Contabo metadata route")
    params = params or {}
    if set(params) - {"page", "size"} or any(type(value) is not int or not 1 <= value <= (100 if name == "size" else 1000000) for name, value in params.items()):
        raise ValueError("Contabo paging arguments are invalid")
    names = {"httpx", "httpcore", "httpcore.connection", "httpcore.http11", "httpcore.http2", "httpcore.proxy"}
    names |= {name for name in logging.Logger.manager.loggerDict if name.startswith(("httpx.", "httpcore."))}
    for name in names:
        logging.getLogger(name).addFilter(_FILTER)
    private = _PRIVATE.set(True)
    try:
        with suppress_http_instrumentation():
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                req = client.build_request("GET", API + route, params=params, headers={"Authorization": "Bearer " + auth.access_token, "Accept": "application/json", "x-request-id": str(uuid4())})
                response = await client.send(req, stream=True)
                try:
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > MAX_BODY:
                            raise OutcomeUnverified("Contabo response exceeds the local 4 MiB bound; no partial output")
                    if response.status_code != 200:
                        raise ApiError(response.status_code)
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise OutcomeUnverified(UNVERIFIED)
                    try:
                        return json.loads(raw, object_pairs_hook=strict_object, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    except (ValueError, UnicodeError, RecursionError):
                        raise OutcomeUnverified(UNVERIFIED) from None
                finally:
                    await response.aclose()
    except httpx.RequestError:
        raise OutcomeUnverified("Contabo transport outcome is unverified") from None
    finally:
        _PRIVATE.reset(private)


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})", value):
        raise ValueError("Invalid resource time")
    if datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is None:
        raise ValueError("Resource time must have an offset")
    return value


def integral_number(value):
    # OAS declares counters as number. Accept 1.0, never truncate 1.5 or coerce text.
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or value > 9223372036854775807 or int(value) != value:
        raise ValueError("Invalid numeric count")
    return int(value)


Count = Annotated[StrictInt, BeforeValidator(integral_number), Field(ge=0, le=9223372036854775807)]
Timestamp = Annotated[StrictStr, BeforeValidator(timestamp)]
StatusText = Annotated[StrictStr, Field(pattern=r"^[A-Za-z][A-Za-z _-]{0,63}$", max_length=64)]


class Response(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


def documented_ram(value):
    if isinstance(value, str) and re.fullmatch(r"(?:0|[1-9][0-9]{0,18})", value):
        return int(value)
    return value


class Instance(Response):
    instanceId: InstanceID
    status: State
    createdDate: Timestamp
    cpuCores: Annotated[StrictInt, Field(ge=0)]
    # The published retrieveInstance(s) example encodes RAM as decimal text.
    ramMb: Annotated[Number, BeforeValidator(documented_ram)]
    diskMb: Number
    osType: Text
    region: Text
    productType: Literal["hdd", "ssd", "vds", "nvme", "performance", "gpu"]
    imageId: Optional[OpaqueID] = None
    displayName: Optional[Text] = None


class Image(Response):
    imageId: OpaqueID
    status: StatusText
    creationDate: Timestamp
    lastModifiedDate: Timestamp
    sizeMb: Number
    uploadedSizeMb: Number
    osType: Text
    version: Text
    format: Literal["iso", "qcow2"]
    standardImage: StrictBool
    gpu: StrictBool
    name: Optional[Text] = None


class Snapshot(Response):
    snapshotId: OpaqueID
    instanceId: InstanceID
    createdDate: Timestamp
    autoDeleteDate: Timestamp
    imageId: OpaqueID
    name: Optional[Text] = None


class Statistics(Response):
    currentImagesCount: Count
    totalSizeMb: Number
    usedSizeMb: Number
    freeSizeMb: Number


class Pagination(Response):
    page: Annotated[Count, Field(ge=1)]
    size: Annotated[Count, Field(ge=1)]
    totalElements: Count
    totalPages: Count


RESOURCE = {Instance: "instance", Image: "image", Snapshot: "snapshot", Statistics: "image_capacity"}
IDS = {Instance: "instanceId", Image: "imageId", Snapshot: "snapshotId"}


def projected(model, raw, include_names=False, parent=None):
    if not isinstance(raw, dict):
        raise OutcomeUnverified(UNVERIFIED)
    selected = {name: raw[name] for name in model.model_fields if name in raw and (name not in {"name", "displayName"} or include_names)}
    try:
        result = model.model_validate(selected).model_dump(exclude_unset=True)
    except Exception:
        raise OutcomeUnverified(UNVERIFIED) from None
    if model is Snapshot and result["instanceId"] != parent:
        raise OutcomeUnverified("Contabo snapshot does not match the requested instance parent")
    result["resource_type"] = RESOURCE[model]
    return result


def records(model, raw, maximum, include_names=False, parent=None):
    if not isinstance(raw, dict) or any(name in raw for name in ("error", "errors", "message")) or not isinstance(raw.get("data"), list) or len(raw["data"]) > maximum:
        raise OutcomeUnverified("Contabo data must be a bounded array; no partial output")
    result = [projected(model, item, include_names, parent) for item in raw["data"]]
    if model in IDS and len({item[IDS[model]] for item in result}) != len(result):
        raise OutcomeUnverified("Contabo returned duplicate resource IDs")
    return result


def page_result(model, raw, cfg, parent=None):
    items = records(model, raw, cfg.page_size, cfg.include_names, parent)
    pagination = raw.get("_pagination")
    if not isinstance(pagination, dict):
        raise OutcomeUnverified("Contabo pagination metadata is missing")
    try:
        values = Pagination.model_validate({name: pagination[name] for name in Pagination.model_fields}).model_dump()
    except Exception:
        raise OutcomeUnverified("Contabo numeric pagination could not be verified") from None
    if values["page"] != cfg.page or values["size"] > cfg.page_size or len(items) > values["size"] or values["totalElements"] < len(items):
        raise OutcomeUnverified("Contabo returned inconsistent pagination")
    more = values["page"] < values["totalPages"]
    return {"items": items, "returned_count": len(items), "pagination": values, "has_more": more, "next_page": values["page"] + 1 if more else None, "snapshot_consistent": False}


async def exact_detail(auth, model, route, identifier, include_names=False, parent=None):
    items = records(model, await request(auth, route), 1, include_names, parent)
    if len(items) != 1 or items[0][IDS[model]] != identifier:
        raise OutcomeUnverified("Contabo returned a different or missing resource ID")
    return items[0]


async def operate(auth, cfg):
    expected = auth.expected_instance_id
    if expected is not None:
        await exact_detail(auth, Instance, f"/v1/compute/instances/{expected}", int(expected))
    if isinstance(cfg, (ListSnapshots, GetSnapshot)):
        await exact_detail(auth, Instance, f"/v1/compute/instances/{cfg.instance_id}", cfg.instance_id)
    if isinstance(cfg, ListInstances):
        model, route, parent = Instance, "/v1/compute/instances", None
    elif isinstance(cfg, ListImages):
        model, route, parent = Image, "/v1/compute/images", None
    elif isinstance(cfg, ListSnapshots):
        model, route, parent = Snapshot, f"/v1/compute/instances/{cfg.instance_id}/snapshots", cfg.instance_id
    elif isinstance(cfg, GetInstance):
        return await exact_detail(auth, Instance, f"/v1/compute/instances/{cfg.instance_id}", cfg.instance_id, cfg.include_names)
    elif isinstance(cfg, GetImage):
        if cfg.image_id == "stats":
            raise ValueError("Use the separate image capacity operation")
        return await exact_detail(auth, Image, f"/v1/compute/images/{cfg.image_id}", cfg.image_id, cfg.include_names)
    elif isinstance(cfg, GetSnapshot):
        return await exact_detail(auth, Snapshot, f"/v1/compute/instances/{cfg.instance_id}/snapshots/{cfg.snapshot_id}", cfg.snapshot_id, cfg.include_names, cfg.instance_id)
    elif isinstance(cfg, ImageStats):
        items = records(Statistics, await request(auth, "/v1/compute/images/stats"), 100)
        return {"items": items, "returned_count": len(items), "provider_paging": "not_documented", "snapshot_consistent": False}
    else:
        raise ValueError("Unsupported Contabo metadata operation")
    raw = await request(auth, route, {"page": cfg.page, "size": cfg.page_size})
    return page_result(model, raw, cfg, parent)


class ContaboNode(WorkflowNode):
    integration_type = "automation-contabo"
    connection_evidence = ConnectionEvidence(operation="list_instances", noun="accessible Contabo instances", label_keys=("instanceId",), proves="reachability")

    @classmethod
    def get_config_model(cls):
        return ContaboNodeConfig

    @classmethod
    def parse_config(cls, config_data):
        raw_guard(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        raw_guard(config_data)
        return super().validate_config(config_data)

    async def execute(self, inputs):
        raw_guard(self.node_data)
        if not isinstance(self.config, ContaboNodeConfig) or self.config.credentials is None:
            raise ValueError("Contabo supplied access token is required")
        auth = self.config.credentials
        result = await operate(auth, self.config.config)
        return {"status": "success", "operation": self.config.config.operation, "data": result}

    @classmethod
    async def load_field_options(cls, *, field_name, credential_data=None, context=None, page_token=None, search=None):
        auth = credential(credential_data)
        if field_name != "image_id":
            raise ValueError("Enter the explicit numeric instance or parent-bound snapshot ID")
        number = 1
        if page_token is not None:
            if not isinstance(page_token, str) or not re.fullmatch(r"[1-9][0-9]{0,6}", page_token) or int(page_token) > 1000000:
                raise ValueError("Contabo picker continuation must be a bounded canonical page number")
            number = int(page_token)
        if search is not None and (not isinstance(search, str) or len(search) > 512 or any(ord(c) < 32 for c in search)):
            raise ValueError("Contabo picker search is invalid")
        result = await operate(auth, ListImages(page=number, page_size=100))
        options = [{"value": item["imageId"], "label": item["imageId"]} for item in result["items"] if item["imageId"] != "stats"]
        if search:
            options = [item for item in options if search.casefold() in item["label"].casefold()]
        continuation = result["next_page"]
        if continuation is not None and continuation > 1000000:
            raise OutcomeUnverified("Contabo picker reached the local page bound; use an explicit resource ID")
        return {"options": options, "next_page_token": str(continuation) if continuation is not None else None}
