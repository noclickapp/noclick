"""RepairDesk v2 purchase orders, goods received notes and status metadata.

The v2 API accepts store-issued API tokens as Bearer credentials, not legacy
query API keys. The published v2 contract has no webhook registration API.
Polls baseline existing records and compare documented metadata on later runs.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin, poll_scope

BASE_URL = "https://api.repairdesk.co/api/web/v2"


class RepairDeskAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="RepairDesk API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api-docs.repairdesk.co/",
            "x-credential-instructions": "Create an API token in RepairDesk Settings → Store → API Access → API Tokens. Grant Purchase Orders View for reads and polls, and Purchase Orders Update for status writes (Delete for deletion). Paste the token itself. Legacy store API keys are not accepted by v2. Tokens act on their issuing store unless an operation selects another store in the same business. Replace expired tokens in RepairDesk.",
        })
    credential_type: Literal["repairdesk_api_key"] = Field("repairdesk_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Token", min_length=1, max_length=8192,
        repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="RepairDesk API token", key=True)
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the issued token without Bearer or whitespace")
        return value


def _op(name, label, category="Purchase Orders", trigger=False):
    return Field(name, json_schema_extra={"const": name, "ui:hidden": True,
        "x-display-name": label, "x-category": category, "x-is-trigger": trigger})


class _Store(BaseModel):
    store_id: int | None = Field(None, strict=True, ge=1, title="Store ID",
        description="Omit for the token's store. Another store must belong to the same business.")


class _Filters(_Store):
    supplier: int | None = Field(None, strict=True, ge=1, title="Supplier ID")
    order_id: str | None = Field(None, max_length=255, title="PO Number Contains")
    status: list[str] | None = Field(None, max_length=25, title="PO Status Names")
    payment_status: Literal["paid", "partial paid", "unpaid"] | None = None
    product_name: str | None = Field(None, max_length=255)
    product_id: int | None = Field(None, strict=True, ge=1)
    manufacturer: int | None = Field(None, strict=True, ge=1)
    order_dates: list[date] | None = Field(None, min_length=2, max_length=2,
        description="Two store-calendar dates: start then end, inclusive.")

    @field_validator("order_dates")
    @classmethod
    def date_range(cls, value):
        if value is not None and value[0] > value[1]:
            raise ValueError("Start date must precede end date")
        return value


class ListPurchaseOrders(_Filters):
    operation: Literal["list_purchase_orders"] = _op("list_purchase_orders", "List Purchase Orders")
    page: int = Field(1, strict=True, ge=1)
    pagesize: int = Field(25, strict=True, ge=1, le=100)
    sort_column: Literal["id", "order_id", "order_date", "status", "total", "amount_paid", "due_amount", "vendor_name", "creator_name"] = "id"
    sort_order: Literal["ASC", "DESC"] = "DESC"


class GetPurchaseOrderStats(_Filters):
    operation: Literal["get_purchase_order_stats"] = _op("get_purchase_order_stats", "Get Purchase Order Totals")


class ListSupplierPurchaseOrders(_Store):
    operation: Literal["list_supplier_purchase_orders"] = _op("list_supplier_purchase_orders", "List Supplier Open Purchase Orders")
    supplier_id: int = Field(..., strict=True, ge=1, title="Supplier ID")


class ListPurchaseOrderStatuses(_Store):
    operation: Literal["list_purchase_order_statuses"] = _op("list_purchase_order_statuses", "List Purchase Order Statuses")
    page: int = Field(1, strict=True, ge=1)
    pagesize: int = Field(25, strict=True, ge=1, le=100)
    search: str | None = Field(None, max_length=100)


class _Status(_Store):
    status_name: str = Field(..., min_length=1, max_length=100, title="Status Name")
    color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$", title="Hex Color")

    @field_validator("status_name")
    @classmethod
    def name(cls, value):
        if not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Use a nonblank status name without control characters")
        return value


class CreatePurchaseOrderStatus(_Status):
    operation: Literal["create_purchase_order_status"] = _op("create_purchase_order_status", "Create Purchase Order Status")


class UpdatePurchaseOrderStatus(_Status):
    operation: Literal["update_purchase_order_status"] = _op("update_purchase_order_status", "Update Purchase Order Status")
    status_id: int = Field(..., strict=True, ge=1, description="Custom status ID; built-in status 0 cannot be edited.")


class DeletePurchaseOrderStatus(_Store):
    operation: Literal["delete_purchase_order_status"] = _op("delete_purchase_order_status", "Delete Purchase Order Status")
    status_id: int = Field(..., strict=True, ge=1, description="Custom status ID; built-in status 0 cannot be deleted.")


class GetPurchaseOrderSettings(_Store):
    operation: Literal["get_purchase_order_settings"] = _op("get_purchase_order_settings", "Get Purchase Order Settings")


class _GrnFilters(_Store):
    supplier: int | None = Field(None, strict=True, ge=1, title="Supplier ID")
    grn_id: str | None = Field(None, max_length=255, title="GRN Number Contains")
    po_id: str | None = Field(None, max_length=255, title="PO Number Contains")
    pb_id: str | None = Field(None, max_length=255, title="Purchase Bill Number Contains")
    grn_created_dates: list[date] | None = Field(None, min_length=2, max_length=2,
        description="Two received dates in store time: start then end, inclusive.")

    @field_validator("grn_created_dates")
    @classmethod
    def date_range(cls, value):
        if value is not None and value[0] > value[1]:
            raise ValueError("Start date must precede end date")
        return value


class ListGoodsReceivedNotes(_GrnFilters):
    operation: Literal["list_goods_received_notes"] = _op("list_goods_received_notes", "List Goods Received Notes", "Goods Received Notes")
    page: int = Field(1, strict=True, ge=1)
    pagesize: int = Field(25, strict=True, ge=1, le=100)
    sort_column: Literal["grn_id", "po_id", "pb_id", "created_date", "amount"] = "created_date"
    sort_order: Literal["ASC", "DESC"] = "DESC"


class GetGrnMetadata(_Store):
    operation: Literal["get_grn_metadata"] = _op("get_grn_metadata", "List GRN Suppliers", "Goods Received Notes")


class OnPurchaseOrderChanged(PollTriggerConfigBase, _Filters):
    operation: Literal["on_new_or_updated_purchase_order"] = _op("on_new_or_updated_purchase_order", "On New or Updated Purchase Order", "Triggers", True)
    window_size: int = Field(100, strict=True, ge=1, le=100,
        description="Watch the newest 100 matching purchase orders by order date (or a smaller window). First poll baselines existing metadata. Later polls emit new or changed records still in this window; older orders and intermediate changes between polls are not observed. Use date/supplier filters to choose the watched scope.")


class OnGrnChanged(PollTriggerConfigBase, _GrnFilters):
    operation: Literal["on_new_or_updated_goods_received_note"] = _op("on_new_or_updated_goods_received_note", "On New or Updated Goods Received Note", "Triggers", True)
    window_size: int = Field(100, strict=True, ge=1, le=100,
        description="Watch the newest 100 matching GRNs by received date (or a smaller window). First poll baselines existing metadata. Later polls emit new or changed records still in this window; older GRNs and intermediate changes between polls are not observed.")


RepairDeskOperation = Annotated[Union[ListPurchaseOrders, GetPurchaseOrderStats,
    ListSupplierPurchaseOrders, ListPurchaseOrderStatuses, CreatePurchaseOrderStatus,
    UpdatePurchaseOrderStatus, DeletePurchaseOrderStatus, GetPurchaseOrderSettings,
    ListGoodsReceivedNotes, GetGrnMetadata, OnPurchaseOrderChanged, OnGrnChanged], Field(discriminator="operation")]


class RepairDeskNodeConfig(NodeConfig[RepairDeskOperation, RepairDeskAPIKeyCredential]):
    pass


# Only documented metadata contributes to a poll revision; additive provider
# fields do not turn every existing record into a spurious update.
PO_FIELDS = ("id", "order_id", "order_date", "status", "payment_status", "total",
    "amount_paid", "due_amount", "vendor", "vendor_name", "creator_name", "notes",
    "tracking", "quantity", "received_qty", "pending_qty", "product_names", "grn_ids",
    "pb_order_id", "is_purchase_bill", "is_marketplace", "is_current_store", "store_name")
GRN_FIELDS = ("id", "order_id", "po_id", "po_order_id", "vendor", "received_by",
    "employee_id", "subtotal", "total_tax", "total", "shipping_cost", "notes",
    "received_date", "date", "pb_id", "pb_createdate", "pb_createdby", "names")


def _page(data):
    if not isinstance(data, dict) or not isinstance(data.get("records"), list):
        raise ValueError("RepairDesk did not return a records page")
    if len(data["records"]) > 100 or any(not isinstance(r, dict) for r in data["records"]):
        raise ValueError("RepairDesk returned an invalid or oversized records page")
    if type(data.get("nextPage")) is not int or data["nextPage"] < 0:
        raise ValueError("RepairDesk did not return its documented nextPage")
    return data["records"], data["nextPage"]


class RepairDeskNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-repairdesk"
    connection_evidence = ConnectionEvidence(operation="list_purchase_order_statuses", noun="purchase order statuses", label_keys=("status_name",))
    edit_examples = ["List RepairDesk purchase orders", "Watch for new or changed goods received notes", "Create a purchase order status"]

    @classmethod
    def get_config_model(cls):
        return RepairDeskNodeConfig

    @staticmethod
    async def _request(credential, method, path, *, params=None, body=None, store_id=None):
        headers = {"Accept": "application/json", "Authorization": f"Bearer {credential.api_key}"}
        if store_id is not None:
            headers["storeId"] = str(store_id)
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers, params=params, json=body)
        if not 200 <= response.status_code < 300:
            # Provider bodies may echo secrets or request content. Keep the
            # status needed by connection evidence without returning raw text.
            raise ValueError(f"RepairDesk API error (HTTP {response.status_code}); check token permissions and selected store")
        if len(response.content) > 2 * 1024 * 1024:
            raise ValueError("RepairDesk response exceeded 2 MiB")
        payload = response.json()
        if (not isinstance(payload, dict) or type(payload.get("statusCode")) is not int
                or payload["statusCode"] != response.status_code or "data" not in payload):
            raise ValueError("RepairDesk returned an unsupported statusCode/data envelope")
        if credential.api_key in json.dumps(payload, ensure_ascii=False):
            raise ValueError("RepairDesk response unexpectedly contained the credential")
        return payload["data"]

    @staticmethod
    def _query(config):
        values = config.model_dump(mode="json", exclude_none=True)
        allowed = ("page", "pagesize", "sort_column", "sort_order", "supplier", "order_id",
            "payment_status", "product_name", "product_id", "manufacturer", "search",
            "grn_id", "po_id", "pb_id")
        params = {k: values[k] for k in allowed if k in values}
        for name in ("status", "order_dates", "grn_created_dates"):
            if values.get(name) is not None:
                params[name + "[]"] = values[name]
        return params

    async def _poll(self, credential, config):
        is_po = isinstance(config, OnPurchaseOrderChanged)
        path = "/purchase-orders" if is_po else "/grn"
        params = self._query(config)
        params.update({"pagesize": config.window_size, "page": 1,
            "sort_column": "order_date" if is_po else "created_date", "sort_order": "DESC"})
        data = await self._request(credential, "GET", path, params=params, store_id=config.store_id)
        records, next_page = _page(data)
        if len(records) > config.window_size:
            raise ValueError("RepairDesk returned more records than the poll window")
        fields = PO_FIELDS if is_po else GRN_FIELDS
        projected = []
        for record in records:
            if type(record.get("id")) is not int or record["id"] <= 0:
                raise ValueError("RepairDesk poll record has no positive numeric ID")
            projected.append({k: record[k] for k in fields if k in record})
        if len({r["id"] for r in projected}) != len(projected):
            raise ValueError("RepairDesk poll returned duplicate record IDs")
        def revision(record):
            digest = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            return f"{record['id']}:{digest}"
        fresh = await self._filter_unseen(projected, revision)
        return {"status": "success", "operation": config.operation, "data": fresh,
            "event_count": len(fresh), "store_id": config.store_id, "more_records_outside_window": bool(next_page)}

    async def _filter_unseen(self, items, id_fn):
        """Poll-family CAS/baseline semantics with the latest revision per ID.

        Unlike an append-only event set, keeping one revision per record also
        emits a change that reverts to a previously observed value (A→B→A).
        """
        scope = poll_scope(type(self), self.config.config.model_dump(mode="json"))
        baseline_only = getattr(self, "_poll_baseline_only", False)
        def mutate(state):
            first = "seen_ids" not in state
            rebaseline = state.get("scope") is not None and state["scope"] != scope
            previous = {v.split(":", 1)[0]: v for v in state.get("seen_ids", [])}
            current = {str(item["id"]): id_fn(item) for item in items}
            if baseline_only and not first and not rebaseline:
                return None, []
            fresh = [] if first or rebaseline else [item for item in items if previous.get(str(item["id"])) != current[str(item["id"])]]
            retained = {} if first or rebaseline else {k: v for k, v in previous.items() if k not in current}
            retained.update(current)
            next_state = {"seen_ids": list(retained.values())[-10000:], "scope": scope}
            if next_state == state:
                return None, fresh
            return next_state, fresh
        fresh = await self._update_node_state(mutate, skip_result=[])
        self._poll_emitted_count = len(fresh)
        return fresh

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation", "").startswith("on_new_or_updated_"):
            return bool(output.get("event_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        operation = output.get("operation", "") if isinstance(output, dict) else ""
        if not operation.startswith("on_new_or_updated_"):
            return super().resolve_agent_event(output)
        records = output.get("data")
        if not isinstance(records, list) or not records:
            return None
        po = operation == "on_new_or_updated_purchase_order"
        label = "purchase order" if po else "goods received note"
        lines = [f"RepairDesk: {len(records)} new or changed {label}(s)."]
        for record in records[:10]:
            lines.append(f"- {record.get('order_id') or label} (id {record['id']}), "
                + (f"supplier {record.get('vendor_name') or record.get('vendor')}, creator {record.get('creator_name')}, status {record.get('status')}, payment {record.get('payment_status')}, ordered {record.get('order_date')}."
                   if po else f"PO {record.get('po_order_id')} (id {record.get('po_id')}), supplier {record.get('vendor')}, received by {record.get('received_by')}, received {record.get('received_date')}.")
                + f" Total {record.get('total')}. Notes: {record.get('notes') or '(none)'}." )
        if len(records) > 10:
            lines.append(f"Plus {len(records) - 10} more records in the workflow output.")
        lines.append("Use list_purchase_orders or list_goods_received_notes with the PO/GRN number to read current details.")
        return {"text": "\n".join(lines), "conversation_key": f"repairdesk:{label}:{records[0]['id']}" if len(records) == 1 else None}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, RepairDeskNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a RepairDesk API token")
        credential, config = self.config.credentials, self.config.config
        if isinstance(config, (OnPurchaseOrderChanged, OnGrnChanged)):
            return await self._poll(credential, config)
        operation = config.operation
        routes = {
            "list_purchase_orders": ("GET", "/purchase-orders"),
            "get_purchase_order_stats": ("GET", "/purchase-orders/stats"),
            "list_supplier_purchase_orders": ("GET", f"/purchase-orders/special-part/{getattr(config, 'supplier_id', '')}"),
            "list_purchase_order_statuses": ("GET", "/purchase-orders/statuses"),
            "create_purchase_order_status": ("POST", "/purchase-orders/statuses"),
            "update_purchase_order_status": ("PATCH", f"/purchase-orders/statuses/{getattr(config, 'status_id', '')}"),
            "delete_purchase_order_status": ("DELETE", f"/purchase-orders/statuses/{getattr(config, 'status_id', '')}"),
            "get_purchase_order_settings": ("GET", "/purchase-orders/configs"),
            "list_goods_received_notes": ("GET", "/grn"),
            "get_grn_metadata": ("GET", "/grn/metadata"),
        }
        method, path = routes[operation]
        body = None
        if method in {"POST", "PATCH"}:
            body = {k: v for k, v in config.model_dump(exclude_none=True).items() if k in {"status_name", "color"}}
        data = await self._request(credential, method, path, params=self._query(config), body=body, store_id=config.store_id)
        if operation in {"list_purchase_orders", "list_goods_received_notes", "list_purchase_order_statuses"}:
            rows, next_page = _page(data)
            return {"status": "success", "operation": operation, "data": rows, "pagination": {k: v for k, v in data.items() if k != "records"}, "next_page_token": str(next_page) if next_page else None}
        return {"status": "success", "operation": operation, "data": data}
