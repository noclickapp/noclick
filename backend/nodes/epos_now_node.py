"""Epos Now API v4 retail operations using a location-specific pasted API key.

Routes and body casing follow the provider's seven published OpenAPI documents.
The transaction trigger polls a bounded date window and baselines existing sales.
"""
from __future__ import annotations

import json

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StrictBool, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE_URL = "https://api.eposnowhq.com"
DOCS_URL = "https://developer.eposnowhq.com/Docs/v4/index"


class EposNowAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Epos Now API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://developer.eposnowhq.com/Docs/Api",
        "x-credential-instructions": "In the Epos Now Back Office, open App Store → API Device and copy its access key. Paste the key only, without Basic. NoClick sends Authorization: Basic followed by that key, without encoding it again. Keys are location specific; choose the API device for the location you want to automate.",
    })
    credential_type: Literal["epos_now_api_key"] = Field("epos_now_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the API key without Basic or whitespace")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def dates_in_order(self):
        if getattr(self, "start_date", None) and getattr(self, "end_date", None):
            if self.start_date > self.end_date:
                raise ValueError("End date must not be before start date")
        return self


def integer(title, *, required=True):
    return (int if required else Optional[int], Field(... if required else None, title=title, ge=1, le=2147483647))


def text(title, *, required=False, maximum=255, minimum=0, description=""):
    return (str if required else Optional[str], Field(... if required else None, title=title,
            min_length=max(minimum, 1 if required else 0), max_length=maximum, description=description))


def money(title):
    return (float, Field(..., title=title, allow_inf_nan=False))


PAGE = {"page": (int, Field(1, ge=1, le=1000000, description="One provider page. Advance the returned next_page until an empty page; no total is supplied."))}
CUSTOMER_FIELDS = {
    "forename": text("First name", required=True, maximum=50),
    "surname": text("Last name", maximum=50),
    "businessName": text("Business name", maximum=50),
    "emailAddress": (Optional[EmailStr], Field(None, title="Email address", max_length=50)),
    "contactNumber": (Optional[str], Field(None, title="Phone number", max_length=15, pattern=r"^[\+]?[0-9]*$")),
    "notes": text("Notes"),
    "referenceCode": text("Reference code", maximum=50, minimum=1),
}
PRODUCT_FIELDS = {
    "name": text("Product name", required=True, maximum=256),
    "description": text("Description", maximum=4000),
    "costPrice": money("Cost price"), "salePrice": money("Sale price"), "eatOutPrice": money("Eat out price"),
    "categoryId": integer("Category ID", required=False),
    "barcode": text("Barcode"), "sku": text("SKU", maximum=34, minimum=1),
    "brandId": integer("Brand ID", required=False), "supplierId": integer("Supplier ID", required=False),
    "sellOnWeb": (Optional[StrictBool], Field(None, title="Sell on web")),
    "sellOnTill": (Optional[StrictBool], Field(None, title="Sell on till")),
    "isCostPriceIncTax": (Optional[StrictBool], Field(None, title="Cost price includes tax")),
    "isSalePriceIncTax": (Optional[StrictBool], Field(None, title="Sale price includes tax")),
    "isEatOutPriceIncTax": (Optional[StrictBool], Field(None, title="Eat out price includes tax")),
}
DATE_FIELDS = {
    "start_date": (datetime, Field(..., title="Start date")),
    "end_date": (datetime, Field(..., title="End date")),
    "device_id": integer("Device ID", required=False),
    "status": (Optional[Literal[1, 7, 8]], Field(None, title="Transaction status", description="1 completed, 7 held, 8 ordered")),
    **PAGE,
}


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    category: str
    fields: dict
    query: tuple[str, ...] = ()
    body: tuple[str, ...] = ()
    array: bool = False
    replacement: bool = False


OPERATIONS = {
    "list_customers": Operation("GET", "/api/v4/Customer", "Customers", PAGE, ("page",), array=True),
    "get_customer": Operation("GET", "/api/v4/Customer/{id}", "Customers", {"id": integer("Customer ID")}),
    "find_customers_by_email": Operation("GET", "/api/v4/Customer/GetByEmail", "Customers", {"email": text("Email", required=True, maximum=50), **PAGE}, ("email", "page"), array=True),
    "create_customer": Operation("POST", "/api/v4/Customer", "Customers", CUSTOMER_FIELDS, body=tuple(CUSTOMER_FIELDS), array=True),
    "update_customer": Operation("PUT", "/api/v4/Customer", "Customers", {"id": integer("Customer ID"), **{k:v for k,v in CUSTOMER_FIELDS.items() if k != "referenceCode"}}, body=("id",) + tuple(k for k in CUSTOMER_FIELDS if k != "referenceCode"), array=True, replacement=True),
    "list_products": Operation("GET", "/api/v4/Product", "Products", PAGE, ("page",), array=True),
    "get_product": Operation("GET", "/api/v4/Product/{id}", "Products", {"id": integer("Product ID")}),
    "create_product": Operation("POST", "/api/v4/Product", "Products", PRODUCT_FIELDS, body=tuple(PRODUCT_FIELDS), array=True),
    "update_product": Operation("PUT", "/api/v4/Product", "Products", {"id": integer("Product ID"), **PRODUCT_FIELDS}, body=("id",) + tuple(PRODUCT_FIELDS), array=True, replacement=True),
    "list_categories": Operation("GET", "/api/v4/Category", "Products", PAGE, ("page",), array=True),
    "get_category": Operation("GET", "/api/v4/Category/{id}", "Products", {"id": integer("Category ID")}),
    "create_category": Operation("POST", "/api/v4/Category", "Products", {"name": text("Category name", required=True, maximum=50), "description": text("Description", maximum=100), "parentId": integer("Parent category ID", required=False)}, body=("name", "description", "parentId"), array=True),
    "list_product_stock": Operation("GET", "/api/v4/ProductStock", "Inventory", PAGE, ("page",), array=True),
    "get_product_stock": Operation("GET", "/api/v4/ProductStock/Product/{productId}/Location/{locationId}", "Inventory", {"productId": integer("Product ID"), "locationId": integer("Location ID")}),
    "list_locations": Operation("GET", "/api/v4/Location", "Locations", PAGE, ("page",), array=True),
    "get_location": Operation("GET", "/api/v4/Location/{id}", "Locations", {"id": integer("Location ID")}),
    "list_transactions": Operation("GET", "/api/v4/Transaction", "Sales", {**PAGE, "status": DATE_FIELDS["status"]}, ("page", "status"), array=True),
    "list_transactions_by_date": Operation("GET", "/api/v4/Transaction/GetByDate", "Sales", DATE_FIELDS, tuple(DATE_FIELDS), array=True),
    "get_transaction_by_reference": Operation("GET", "/api/v4/Transaction/ReferenceCode/{referenceCode}", "Sales", {"referenceCode": text("Reference code", required=True, maximum=50)}),
    "list_end_of_days": Operation("GET", "/api/v4/EndOfDay", "Sales", PAGE, ("page",), array=True),
}


def _make_config(name, op):
    label = name.replace("_", " ").title()
    model = create_model("EposNow" + label.replace(" ", "") + "Config", __base__=Input, __module__=__name__,
        operation=(Literal[name], Field(name, title=label, json_schema_extra={"ui:hidden": True,
            "x-display-name": label, "x-category": op.category, "x-is-trigger": False})), **op.fields)
    if op.replacement:
        model.__doc__ = "Full replacement: Epos Now resets omitted optional properties to their defaults. Supply all values you want to retain."
    return model


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


class EposNowOnNewTransactionConfig(PollTriggerConfigBase):
    operation: Literal["on_new_transaction"] = Field("on_new_transaction", json_schema_extra={
        "ui:hidden": True, "x-display-name": "On New Transaction", "x-category": "Triggers", "x-is-trigger": True})
    lookback_hours: int = Field(24, ge=1, le=168, description="Poll transactions dated within this rolling window. The first poll baselines existing IDs; later polls emit previously unseen IDs. Transactions backdated beyond this window are not detected.")
    device_id: Optional[int] = Field(None, title="Device ID", ge=1, le=2147483647)
    status: Optional[Literal[1, 7, 8]] = Field(None, title="Transaction status", description="1 completed, 7 held, 8 ordered")


EposNowConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + (EposNowOnNewTransactionConfig,)], Field(discriminator="operation")]


class EposNowNodeConfig(NodeConfig[EposNowConfig, EposNowAPIKeyCredential]):
    pass


class EposNowNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-epos-now"
    connection_evidence = ConnectionEvidence(operation="list_locations", noun="locations", label_keys=("name", "id"))
    edit_examples = ["Create a customer in Epos Now", "Look up stock for this product and location", "Run when a new transaction appears"]

    @classmethod
    def get_config_model(cls):
        return EposNowNodeConfig

    @staticmethod
    async def _request(api_key, method, path, *, params=None, body=None):
        headers = {"Authorization": "Basic " + api_key, "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path, params=params, json=body, headers=headers)
        except httpx.RequestError:
            raise ValueError("Epos Now did not return a response; the outcome of a write is unknown. Inspect the account before retrying.") from None
        if not 200 <= response.status_code < 300:
            detail = response.text[:1000].replace(api_key, "[redacted]")
            raise ValueError(f"Epos Now HTTP {response.status_code}: {detail}")
        try:
            data = response.json()
            if isinstance(data, dict) and (data.get("error") or data.get("errors")):
                raise ValueError("Epos Now returned an error envelope; inspect writes before retrying")
            return data
        except json.JSONDecodeError:
            raise ValueError("Epos Now returned an invalid JSON response; inspect writes before retrying") from None

    @classmethod
    async def validate_credential_access(cls, credential_data):
        credential = EposNowAPIKeyCredential.model_validate(credential_data)
        try:
            result = await cls._request(credential.api_key, "GET", "/api/v4/Location", params={"page": 1})
        except ValueError as exc:
            message = str(exc)
            rejected = message.startswith(("Epos Now HTTP 401:", "Epos Now HTTP 403:"))
            return {"valid": False if rejected else None, "identity_verified": False, "message": message}
        if not isinstance(result, list):
            return {"valid": None, "identity_verified": False, "message": "Epos Now returned an unexpected location list"}
        return {"valid": True, "identity_verified": False, "message": "Epos Now accepted this device key for reading locations"}

    async def _poll_transactions(self, credential, config):
        end = datetime.now(timezone.utc)
        params = {"startDate": (end - timedelta(hours=config.lookback_hours)).isoformat(), "endDate": end.isoformat()}
        if config.device_id is not None:
            params["deviceId"] = config.device_id
        if config.status is not None:
            params["status"] = config.status
        rows = []
        seen_pages = set()
        for page in range(1, 52):
            data = await self._request(credential.api_key, "GET", "/api/v4/Transaction/GetByDate", params={**params, "page": page})
            if not isinstance(data, list) or any(not isinstance(row, dict) or type(row.get("id")) is not int for row in data):
                raise ValueError("Epos Now returned a transaction page without usable IDs")
            if not data:
                break
            fingerprint = tuple(row["id"] for row in data)
            if fingerprint in seen_pages:
                raise ValueError("Epos Now repeated a transaction page; poll state was not advanced")
            seen_pages.add(fingerprint)
            rows.extend(data)
            if len(rows) > 10000:
                raise ValueError("More than 10000 transactions; narrow the device, status or lookback window")
            # Official v4 docs: Transaction/GetByDate has 200 response items per page.
            if len(data) < 200:
                break
        else:
            raise ValueError("More than 50 transaction pages; narrow the device, status or lookback window")
        fresh = await self._filter_unseen(rows, lambda row: str(row["id"]))
        return {"status": "success", "operation": config.operation, "transactions": fresh, "new_transaction_count": len(fresh)}

    @classmethod
    def resolve_agent_event(cls, output):
        rows = output.get("transactions") if isinstance(output, dict) else None
        if not isinstance(rows, list) or not rows:
            return None
        lines = [f"- Transaction {row.get('id')}, customer {row.get('customerId')}, device {row.get('deviceId')}, at {row.get('dateTime')}: total {row.get('totalAmount')}, status {row.get('statusId')}" for row in rows[:10]]
        return {"text": f"Epos Now: {len(rows)} new transaction(s) in the watched location.\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs: dict[str, Any]):
        if not isinstance(self.config, EposNowNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect an Epos Now API device key")
        credential, config = self.config.credentials, self.config.config
        if isinstance(config, EposNowOnNewTransactionConfig):
            return await self._poll_transactions(credential, config)
        spec = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path = spec.path
        for key, value in values.items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        query_names = {"start_date": "startDate", "end_date": "endDate", "device_id": "deviceId"}
        params = {query_names.get(key, key): values[key] for key in spec.query if key in values}
        body = [{key: values[key] for key in spec.body if key in values}] if spec.body else None
        data = await self._request(credential.api_key, spec.method, path, params=params or None, body=body)
        if (spec.array and (not isinstance(data, list) or any(not isinstance(row, dict) for row in data))) or (not spec.array and not isinstance(data, dict)):
            raise ValueError("Epos Now returned an unexpected resource response; inspect writes before retrying")
        result = {"status": "success", "operation": config.operation, "data": data}
        if spec.method == "GET" and "page" in spec.query:
            result["next_page"] = config.page + 1 if data else None
        return result
