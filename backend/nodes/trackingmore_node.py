"""Native TrackingMore V4 courier and existing shipment-result read workflows."""
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

import base64
import hashlib
import json
import math
import re
from datetime import datetime

import httpx

ORIGIN = "https://api.trackingmore.com"
MAX_BODY = 2 * 1024 * 1024
STATUS = {"pending", "notfound", "transit", "pickup", "delivered", "expired", "undelivered", "exception", "inforeceived"}


class TrackingMoreAPIError(RuntimeError):
    def __init__(self, *, http_status=None, meta_code=None):
        super().__init__("TrackingMore rejected the read or returned an unverified V4 response.")
        self.http_status = http_status
        self.meta_code = meta_code
        self.retry_after_seconds = 120 if 429 in {http_status, meta_code} else None


def text(value, maximum=256, *, nonempty=False):
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value) or (nonempty and not value.strip()):
        raise ValueError("TrackingMore returned invalid bounded selected text.")
    return value


def courier_code(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", value):
        raise ValueError("Use a bounded courier code, without a URL or path.")
    return value


def tracking_number(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,99}", value) or value != value.strip():
        raise ValueError("Use one bounded tracking number, without a URL, comma or control character.")
    return value


def numbers(value):
    if not isinstance(value, str):
        raise ValueError("Supply a comma-separated list of existing tracking numbers.")
    rows = [tracking_number(part.strip()) for part in value.split(",")]
    if not 1 <= len(rows) <= 40 or len(set(rows)) != len(rows):
        raise ValueError("Supply 1–40 distinct existing tracking numbers.")
    return rows


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate JSON field.")
        result[key] = value
    return result


def nonfinite(_):
    raise ValueError("Non-finite JSON number.")


def bounded(value, depth=0):
    if depth > 14 or isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Unbounded JSON value.")
    if isinstance(value, (dict, list)):
        if len(value) > 3000:
            raise ValueError("Oversized JSON collection.")
        for child in value.values() if isinstance(value, dict) else value:
            bounded(child, depth + 1)


def parse_json(value):
    try:
        if not value or len(value) > MAX_BODY:
            raise ValueError()
        result = json.loads(value, object_pairs_hook=pairs, parse_constant=nonfinite)
        if not isinstance(result, dict):
            raise ValueError()
        bounded(result)
        return result
    except Exception:
        raise ValueError("TrackingMore returned invalid bounded JSON.") from None


def safe_selected(result, data):
    secret = data["api_key"]
    def walk(value):
        if isinstance(value, str) and (secret in value or json.dumps(secret)[1:-1] in value):
            raise ValueError("TrackingMore selected output contains credential material.")
        if isinstance(value, dict):
            for key, child in value.items():
                walk(key)
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(result)
    return result


async def request(data, method, path, *, params=None, body=None):
    if (method, path) not in {("GET", "/v4/couriers/all"), ("POST", "/v4/couriers/detect"), ("GET", "/v4/trackings/get")}:
        raise ValueError("Unsupported native TrackingMore V4 read.")
    if path == "/v4/trackings/get":
        if not isinstance(params, dict) or set(params) - {"tracking_numbers", "courier_code", "delivery_status", "items_amount", "pages_amount", "updated_date_min"} or not (params.get("tracking_numbers") or params.get("updated_date_min")):
            raise ValueError("Select existing tracking numbers with the native bounded filters.")
    elif params:
        raise ValueError("Provider pagination is not documented for courier discovery.")
    if path == "/v4/couriers/detect":
        if not isinstance(body, dict) or set(body) != {"tracking_number"}:
            raise ValueError("Courier detection accepts one tracking number only.")
    elif body is not None:
        raise ValueError("This native TrackingMore read has no request body.")
    safe_selected(params or {}, data)
    safe_selected(body or {}, data)
    encoded = json.dumps(body, allow_nan=False).encode() if body is not None else None
    headers = {"Tracking-Api-Key": data["api_key"], "Accept": "application/json", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, ORIGIN + path, params=params, content=encoded, headers=headers) as response:
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BODY:
                        raise TrackingMoreAPIError(http_status=response.status_code)
                    chunks.append(chunk)
                result = None
                if "application/json" in response.headers.get("content-type", "").lower():
                    try:
                        result = parse_json(b"".join(chunks))
                    except ValueError:
                        pass
                meta = result.get("meta") if isinstance(result, dict) else None
                code = meta.get("code") if isinstance(meta, dict) else None
                code = code if type(code) is int else None
                if response.status_code != 200 or code != 200 or not isinstance(result.get("data") if isinstance(result, dict) else None, list):
                    raise TrackingMoreAPIError(http_status=response.status_code, meta_code=code)
                return result["data"]
    except httpx.HTTPError:
        raise ValueError("The TrackingMore read result could not be verified. No request was automatically retried.") from None


def couriers(rows, data):
    if len(rows) > 3000:
        raise ValueError("The TrackingMore courier collection exceeds its local bound.")
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("TrackingMore returned an invalid courier.")
        selected = {"courier_code": courier_code(row.get("courier_code")), "courier_name": text(row.get("courier_name"), nonempty=True)}
        for key in ("courier_country_iso2", "courier_type", "default_language"):
            if row.get(key) is not None:
                selected[key] = text(row[key], 128)
        result.append(selected)
    if len({row["courier_code"] for row in result}) != len(result):
        raise ValueError("TrackingMore returned duplicate courier codes.")
    return safe_selected(result, data)


def shipments(rows, data, *, requested, code=None, status=None, checkpoint_limit=0):
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("TrackingMore returned an invalid existing shipment.")
        number, carrier = tracking_number(row.get("tracking_number")), courier_code(row.get("courier_code"))
        if (requested is not None and number not in requested) or code is not None and carrier != code:
            raise ValueError("TrackingMore returned a shipment outside the selected numbers or courier.")
        selected = {"id": text(row.get("id"), 128, nonempty=True), "tracking_number": number, "courier_code": carrier,
            "delivery_status": text(row.get("delivery_status"), 64, nonempty=True)}
        if status is not None and selected["delivery_status"] != status:
            raise ValueError("TrackingMore returned a shipment outside the selected delivery-status filter.")
        # Preserve provider strings; the official SDK does not establish UTC
        # offsets for every returned date, or boolean semantics for archived.
        for key in ("created_at", "update_at", "latest_checkpoint_time", "scheduled_delivery_date", "substatus", "origin_country", "destination_country"):
            if row.get(key) is not None:
                selected[key] = text(row[key], 128)
        if row.get("archived") is not None:
            value = row["archived"]
            selected["archived"] = value if type(value) is bool else text(value, 32)
        if "updating" in row:
            if type(row["updating"]) is not bool:
                raise ValueError("TrackingMore returned invalid updating metadata.")
            selected["updating"] = row["updating"]
        if checkpoint_limit:
            for key in ("origin_info", "destination_info"):
                info = row.get(key)
                if info is None:
                    continue
                if not isinstance(info, dict) or not isinstance(info.get("trackinfo"), list):
                    raise ValueError("TrackingMore returned invalid checkpoint metadata.")
                selected[key + "_checkpoints"] = []
                for checkpoint in info["trackinfo"][:checkpoint_limit]:
                    if not isinstance(checkpoint, dict):
                        raise ValueError("TrackingMore returned an invalid checkpoint.")
                    selected[key + "_checkpoints"].append({field: text(checkpoint[field], 128) for field in
                        ("checkpoint_date", "checkpoint_delivery_status", "checkpoint_delivery_substatus", "country_iso2") if checkpoint.get(field) is not None})
                selected[key + "_checkpoint_count"] = len(info["trackinfo"])
                selected[key + "_checkpoints_truncated"] = len(info["trackinfo"]) > checkpoint_limit
        result.append(selected)
    if len({row["id"] for row in result}) != len(result):
        raise ValueError("TrackingMore returned duplicate shipment IDs.")
    return safe_selected(result, data)


def binding(data, purpose, filters):
    record = {"key_hash": hashlib.sha256(data["api_key"].encode()).hexdigest(), "purpose": purpose, "filters": filters}
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def continuation(data, purpose, filters, position, snapshot=None):
    record = {"v": 1, "binding": binding(data, purpose, filters), "position": position, "snapshot": snapshot}
    return base64.urlsafe_b64encode(json.dumps(record, separators=(",", ":")).encode()).decode().rstrip("=")


def position(token, data, purpose, filters, *, maximum, snapshot=None):
    try:
        if not isinstance(token, str) or not 1 <= len(token) <= 512 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
            raise ValueError()
        record = json.loads(base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True), object_pairs_hook=pairs)
        if set(record) != {"v", "binding", "position", "snapshot"} or type(record["v"]) is not int or record["v"] != 1 or record["binding"] != binding(data, purpose, filters) or record["snapshot"] != snapshot or type(record["position"]) is not int or not 1 <= record["position"] <= maximum:
            raise ValueError()
        return record["position"]
    except Exception:
        raise ValueError("The TrackingMore continuation belongs to a different API key, query, purpose or collection. Start again.") from None


def local_courier_page(rows, data, *, purpose, limit, search="", token=None):
    search = text(search, 100)
    rows = sorted((row for row in rows if search.casefold() in row["courier_name"].casefold() or search.casefold() in row["courier_code"].casefold()), key=lambda row: row["courier_code"])
    snapshot = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    filters = {"limit": limit, "search": search}
    offset = position(token, data, purpose, filters, maximum=len(rows)-1, snapshot=snapshot) if token else 0
    if offset % limit:
        raise ValueError("Invalid local courier continuation offset.")
    end = offset + limit
    return {"items": rows[offset:end], "total": len(rows), "has_more": end < len(rows),
        "next_page_token": continuation(data, purpose, filters, end, snapshot) if end < len(rows) else None,
        "pagination_mode": "local slice of re-fetched complete courier catalog; no provider cursor"}



class TrackingMoreAPIKeyCredential(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, title="TrackingMore API Key", json_schema_extra={
        "x-credential-url": "https://www.trackingmore.com/docs/trackingmore/",
        "x-credential-instructions": "Supply an existing authorized TrackingMore V4 API key. It is sent only in Tracking-Api-Key, not the retired V2 header or URL. Courier discovery proves protected reachability, not your tenant or human identity. Existing shipment reads and polling require shipments already registered in your account; this node never registers a tracking or performs a paid real-time probe. Actual access, plan and quotas remain subject to your account.",
    })
    credential_type: Literal["trackingmore_api_key"] = Field("trackingmore_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=8, max_length=4096, title="API Key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        if any(ord(c) < 33 or ord(c) > 126 for c in value) or "://" in value or value.startswith("Bearer"):
            raise ValueError("Supply the issued API key without a prefix, URL or whitespace.")
        return value


def credential_shape(data):
    try:
        return TrackingMoreAPIKeyCredential.model_validate(data).model_dump()
    except Exception:
        raise ValueError("The current TrackingMore V4 API-key credential is invalid.") from None


def operation(value, label, category):
    return Field(value, json_schema_extra={"ui:hidden": True, "x-display-name": label, "x-category": category, "x-is-trigger": False})


class OperationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ListCouriers(OperationConfig):
    operation: Literal["list_couriers"] = operation("list_couriers", "List Supported Couriers", "Couriers")
    limit: int = Field(25, ge=1, le=100, strict=True, title="Local Page Size")
    search: str = Field("", max_length=100, title="Courier Name or Code Contains")
    page_token: str | None = Field(None, max_length=512, title="Local Continuation", description="Re-fetches and compares the complete catalog; no provider paging is invented.")


class DetectCouriers(OperationConfig):
    operation: Literal["detect_couriers"] = operation("detect_couriers", "Detect Possible Couriers", "Couriers")
    tracking_number: str = Field(..., title="Tracking Number", description="Read-semantic detection only; no shipment is registered and no match is automatically selected.")

    @field_validator("tracking_number")
    @classmethod
    def number(cls, value):
        return tracking_number(value)


class ShipmentProjection(OperationConfig):
    checkpoint_limit: int = Field(0, ge=0, le=50, strict=True, title="Checkpoints per Origin/Destination", description="0 omits checkpoints. Selected checkpoints include date/status/country only; names, addresses, contact details and free-form event text stay omitted.")


class CourierSelection(ShipmentProjection):
    courier_code: str | None = Field(None, title="Courier", json_schema_extra={"x-dynamic-options": {"field_name": "courier_code", "searchable": True, "allow_custom": True}})

    @field_validator("courier_code")
    @classmethod
    def code(cls, value):
        return courier_code(value) if value is not None else None


class GetTrackingResult(CourierSelection):
    operation: Literal["get_tracking_result"] = operation("get_tracking_result", "Get One Existing Shipment Result", "Existing Shipments")
    tracking_number: str = Field(..., title="Existing Tracking Number")
    courier_code: str = Field(..., title="Courier", json_schema_extra={"x-dynamic-options": {"field_name": "courier_code", "searchable": True, "allow_custom": True}})

    @field_validator("tracking_number")
    @classmethod
    def number(cls, value):
        return tracking_number(value)


class GetTrackingResults(CourierSelection):
    operation: Literal["get_tracking_results"] = operation("get_tracking_results", "Get Selected Existing Shipment Results", "Existing Shipments")
    tracking_numbers: str = Field(..., max_length=4040, title="Existing Tracking Numbers", description="1–40 distinct comma-separated tracking numbers; unrestricted account exports are not offered.", json_schema_extra={"ui:widget": "textarea"})
    delivery_status: Literal["pending", "notfound", "transit", "pickup", "delivered", "expired", "undelivered", "exception", "inforeceived"] | None = Field(None, title="Delivery Status")
    items_amount: int = Field(100, ge=1, le=200, strict=True, title="Native Items per Page")
    pages_amount: int = Field(1, ge=1, le=1000, strict=True, title="Native Page Number", description="The exact V4 parameter is pages_amount. No total or has_more contract is documented.")
    page_token: str | None = Field(None, max_length=512, title="Bound Next-Page Candidate", description="For full native pages only. Same API key and query required; the candidate does not prove another page exists.")

    @field_validator("tracking_numbers")
    @classmethod
    def numbers(cls, value):
        return ",".join(numbers(value))


class OnNewOrUpdatedShipment(PollTriggerConfigBase):
    operation: Literal["on_new_or_updated_shipment"] = Field("on_new_or_updated_shipment", json_schema_extra={
        "ui:hidden": True, "x-category": "Triggers", "x-is-trigger": True,
        "x-display-name": "On New or Updated Shipment",
    })
    updated_date_min: str = Field(..., title="Updated Since", description="Update-time window, for example 2022-09-10T10:40:34+08:00. Use a recent time; TrackingMore retains 180 days.",
        pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\+[0-9]{2}:[0-9]{2}$")
    courier_code: str | None = Field(None, title="Courier", json_schema_extra={"x-dynamic-options": {"field_name": "courier_code", "searchable": True, "allow_custom": True}})

    @field_validator("updated_date_min")
    @classmethod
    def timestamp(cls, value):
        datetime.fromisoformat(value)
        return value

    @field_validator("courier_code")
    @classmethod
    def courier(cls, value):
        return courier_code(value) if value is not None else None


TrackingMoreConfig = Annotated[Union[ListCouriers, DetectCouriers, GetTrackingResult, GetTrackingResults, OnNewOrUpdatedShipment], Field(discriminator="operation")]


class TrackingMoreFullConfig(NodeConfig):
    model_config = ConfigDict(hide_input_in_errors=True)
    credentials: TrackingMoreAPIKeyCredential | None = None
    config: TrackingMoreConfig


class TrackingMoreNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-trackingmore"
    connection_evidence = ConnectionEvidence(operation="list_couriers", noun="supported couriers", proves="reachability", label_keys=("courier_name", "courier_code"))

    @classmethod
    def get_config_model(cls):
        return TrackingMoreFullConfig

    @classmethod
    async def validate_credential_access(cls, credential_data, *, validation_context=None):
        if validation_context is None:
            return {"valid": None, "proves": "reachability", "account_label": None}
        result = await validation_context.run_operation("list_couriers")
        return {"valid": True if result.get("status") == "success" else None, "proves": "reachability", "account_label": None}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None):
        if field_name != "courier_code":
            return {"options": [], "next_page_token": None}
        credential_data = credential_shape(credential_data)
        rows = couriers(await request(credential_data, "GET", "/v4/couriers/all"), credential_data)
        context = context or {}
        page = local_courier_page(rows, credential_data, purpose="picker-courier_code", limit=50, search=context.get("search") or "", token=context.get("page_token"))
        return {"options": [{"value": row["courier_code"], "label": row["courier_name"]} for row in page["items"]], "next_page_token": page["next_page_token"], "pagination_mode": page["pagination_mode"]}

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") == "on_new_or_updated_shipment":
            return bool(output.get("new_shipment_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict) or output.get("operation") != "on_new_or_updated_shipment":
            return super().resolve_agent_event(output)
        items = output.get("shipments") or []
        if not items:
            return None
        lines = ["TrackingMore shipment updates:"]
        for item in items:
            lines.append(f"{item['courier_code']} shipment {item['tracking_number']}: {item['delivery_status']} (updated {item['update_at']}; id={item['id']}).")
            lines.append(f"To read details: get_tracking_result tracking_number={item['tracking_number']} courier_code={item['courier_code']}.")
        return {"text": "\n".join(lines), "title": "TrackingMore shipment updates",
                "conversation_key": str(items[0]["id"]) if len(items) == 1 else "trackingmore-shipments"}

    async def _poll_shipments(self, data, cfg):
        items = []
        for page in range(1, 21):
            params = {"updated_date_min": cfg.updated_date_min, "items_amount": 100, "pages_amount": page}
            if cfg.courier_code:
                params["courier_code"] = cfg.courier_code
            rows = await request(data, "GET", "/v4/trackings/get", params=params)
            if len(rows) > 100:
                raise ValueError("TrackingMore exceeded the requested page size")
            selected = shipments(rows, data, requested=None, code=cfg.courier_code)
            for item in selected:
                text(item.get("update_at"), 128, nonempty=True)
            items.extend(selected)
            if len(rows) < 100:
                break
        else:
            raise ValueError("Shipment window reached the 2,000-item limit; choose a recent Updated Since time or a courier")
        fresh = await self._filter_unseen(items, lambda item: json.dumps([item["id"], item["update_at"], item["delivery_status"]]))
        return {"status": "success", "operation": cfg.operation, "shipments": fresh, "new_shipment_count": len(fresh)}

    async def execute(self, inputs):
        try:
            if not isinstance(self.config, TrackingMoreFullConfig) or self.config.credentials is None:
                raise ValueError("Select the native TrackingMore V4 API-key credential and operation.")
            cfg = self.config.config
            data = credential_shape(self.config.credentials.model_dump())
            if isinstance(cfg, OnNewOrUpdatedShipment):
                return await self._poll_shipments(data, cfg)
            if isinstance(cfg, (ListCouriers, DetectCouriers)):
                method, path, body = ("GET", "/v4/couriers/all", None) if isinstance(cfg, ListCouriers) else ("POST", "/v4/couriers/detect", {"tracking_number": cfg.tracking_number})
                rows = couriers(await request(data, method, path, body=body), data)
                result = local_courier_page(rows, data, purpose=cfg.operation, limit=cfg.limit, search=cfg.search, token=cfg.page_token) if isinstance(cfg, ListCouriers) else {
                    "matches": rows, "match_count": len(rows), "ordering": "provider order retained; no courier automatically chosen", "shipment_registered": False}
            else:
                requested = [cfg.tracking_number] if isinstance(cfg, GetTrackingResult) else numbers(cfg.tracking_numbers)
                filters = {"tracking_numbers": ",".join(requested), "items_amount": 100 if isinstance(cfg, GetTrackingResult) else cfg.items_amount}
                if cfg.courier_code:
                    filters["courier_code"] = cfg.courier_code
                page = 1
                if isinstance(cfg, GetTrackingResults):
                    if cfg.delivery_status:
                        filters["delivery_status"] = cfg.delivery_status
                    page = position(cfg.page_token, data, cfg.operation, {**filters, "projection": cfg.checkpoint_limit, "starting_page": cfg.pages_amount}, maximum=1000) if cfg.page_token else cfg.pages_amount
                rows = await request(data, "GET", "/v4/trackings/get", params={**filters, "pages_amount": page})
                if len(rows) > filters["items_amount"]:
                    raise ValueError("TrackingMore returned more shipments than the selected native page bound.")
                items = shipments(rows, data, requested=requested, code=cfg.courier_code,
                    status=cfg.delivery_status if isinstance(cfg, GetTrackingResults) else None, checkpoint_limit=cfg.checkpoint_limit)
                if isinstance(cfg, GetTrackingResult):
                    if len(items) != 1:
                        raise ValueError("Exactly one matching existing shipment is required; this node will not register a missing shipment.")
                    result = {"shipment": items[0], "proves": "selected shipment access; no tenant or principal identity"}
                else:
                    query = {**filters, "projection": cfg.checkpoint_limit, "starting_page": cfg.pages_amount}
                    result = {"items": items, "page": page, "items_amount": cfg.items_amount, "count": len(items), "has_more": None,
                        "next_page_token": continuation(data, cfg.operation, query, page + 1) if len(rows) == cfg.items_amount and page < 1000 else None,
                        "pagination_mode": "native pages_amount/items_amount; full-page next candidate only, provider total/has_more unknown"}
            return {"status": "success", "operation": cfg.operation, "data": safe_selected(result, data)}
        except Exception as exc:
            retry = getattr(exc, "retry_after_seconds", None)
            return {"status": "error", "error": str(exc) if isinstance(exc, (ValueError, TrackingMoreAPIError)) else "The native TrackingMore read could not be verified.",
                "status_code": getattr(exc, "http_status", None), "meta_code": getattr(exc, "meta_code", None), "retry_after_seconds": retry,
                "_halt_downstream": retry is not None, "automatically_retried": False}
