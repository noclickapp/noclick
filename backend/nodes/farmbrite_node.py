"""Farmbrite v1 actions and scheduled change detection.

Contract: https://developers.farmbrite.com/openapi.json (1.0.0).
The API's overview documents page/limit and sorting/filtering for list reads.
Polls scan at most 2,000 records, failing before advancing state if truncated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, StrictBool, create_model, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.farmbrite.com/v1"


class FarmbriteTokenCredential(BaseModel):
    model_config = ConfigDict(title="Farmbrite Personal Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.farmbrite.com/#section/Authentication",
            "x-credential-instructions": "In Farmbrite, open your user profile and copy the API Key. Paste it here without the Bearer prefix. The token inherits your user's role and permissions. Farmbrite recommends a separate integration user. NoClick checks access by reading your tasks.",
        })
    credential_type: Literal["farmbrite_token"] = Field("farmbrite_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="Personal access token",
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Personal access token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API Key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("end_time", check_fields=False)
    @classmethod
    def valid_due_time(cls, value):
        if value is not None:
            try:
                datetime.strptime(value, "%Y-%m-%d %H:%M")
            except ValueError:
                raise ValueError("Use a real due date and time in YYYY-MM-DD HH:MM format") from None
        return value

    @model_validator(mode="after")
    def valid_write(self):
        values = self.model_dump(exclude_none=True)
        action = values.get("operation", "")
        if action.startswith(("create_", "update_")):
            op = OPERATIONS[action]
            if not any(k in values for k in op.body):
                raise ValueError("Provide at least one field to write")
        if action in {"create_animal", "update_animal"}:
            if values.get("status") in {"Butchered", "Culled", "Deceased"} and not values.get("death_date"):
                raise ValueError("This livestock status requires a death date")
            if values.get("status") == "Sold" and not values.get("sale_date"):
                raise ValueError("Sold livestock requires a sale date")
        if action in {"create_task", "update_task"}:
            if bool(values.get("reference_type")) != bool(values.get("reference_id")):
                raise ValueError("Provide both reference type and reference ID")
        return self


Text = Annotated[str, Field(max_length=10000)]
Name = Annotated[str, Field(min_length=1, max_length=500)]
Identifier = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_. -]*$")]
AnimalStatus = Literal["Active", "Butchered", "Culled", "Deceased", "Dry", "Lactating", "Lost", "Off Farm", "Quarantined", "Reference", "Sick", "Sold", "Weaning", "Archived"]
OrderStatus = Literal["Approved", "Cancelled", "Complete", "Delivered", "Draft", "In Progress", "On Hold", "Ordered", "Packing", "Pending Approval", "Picking", "Ready", "Shipped"]
ContactType = Literal["Auditor", "Breeder", "Buyer", "Certifier", "Contact", "Consultant", "Contractor", "Customer", "Donor", "Employee", "Purchaser", "Supplier", "Vendor", "Veterinarian", "Wholesale Customer"]
Number = Annotated[float, Field(allow_inf_nan=False, ge=0)]


class ChecklistItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    assignee: str | None = None
    done: StrictBool | None = None


class ContactAddress(BaseModel):
    model_config = ConfigDict(extra="forbid")
    country: Annotated[str, Field(pattern=r"^[A-Za-z]{2}$")] | None = None
    street: Text | None = None
    city: Name | None = None
    state: Name | None = None
    postal: Name | None = None


class OrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: Name
    price: Number
    qty: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    product_id: Identifier | None = None


class ExistingOrderItem(OrderItem):
    id: Identifier = Field(..., description="Existing order item ID from the order response.")


TASK_FIELDS = {
    "title": Name, "description": Text, "assigned_to_id": Name,
    "end_time": Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")],
    "status": Name, "complete": StrictBool, "priority": Annotated[int, Field(ge=1, le=5)],
    "hours_spent": Number, "checklist": list[ChecklistItem],
    "reference_type": Literal["animal", "equipment", "plant", "location", "planting"],
    "reference_id": Identifier,
}
CONTACT_FIELDS = {
    "type": ContactType, "first_name": Name, "last_name": Name, "email": Name,
    "phone": Text, "cell": Text, "company": Text, "description": Text,
    "label": Text, "address": ContactAddress, "tax_exempt": StrictBool,
}
ANIMAL_FIELDS = {
    "type": Name, "status": AnimalStatus, "name": Name, "tag_number": Text,
    "electronic_id": Text, "gender": Literal["Male", "Female"], "breed": Text,
    "birth_date": date, "description": Text, "weight": Number, "death_date": date,
    "sale_date": date,
}
ORDER_FIELDS = {
    "status": OrderStatus, "payment_status": Literal["Due", "Paid", "Cancelled"],
    "contact_id": Identifier, "email": Name, "first_name": Name, "last_name": Name,
    "phone": Text, "payment_method": Literal["Credit Card", "Cash", "Check", "Other"],
    "message": Text, "note": Text, "memo": Text, "po_number": Text,
    "order_date": date, "due_date": date, "delivery_amount": Number,
    "order_items": Annotated[list[OrderItem], Field(min_length=1, max_length=100)],
}


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    body: dict[str, Any] | None = None
    required: tuple[str, ...] = ()


OPERATIONS: dict[str, Operation] = {}
for resource, singular, fields, required, verbs in (
    ("tasks", "task", TASK_FIELDS, ("title",), ("list", "get", "create", "update", "delete")),
    ("contacts", "contact", CONTACT_FIELDS, (), ("list", "get", "create", "update", "delete")),
    ("animals", "animal", ANIMAL_FIELDS, ("type", "status"), ("list", "get", "create", "update")),
    ("orders", "order", ORDER_FIELDS, ("status", "payment_status"), ("list", "get", "create", "update")),
    ("products", "product", {}, (), ("list", "get")),
    ("crops", "crop", {}, (), ("list", "get")),
):
    for verb in verbs:
        name = verb + "_" + (resource if verb == "list" else singular)
        path = "/" + resource + ("/{" + singular + "_id}" if verb in {"get", "update", "delete"} else "")
        OPERATIONS[name] = Operation(
            {"list": "GET", "get": "GET", "create": "POST", "update": "PUT", "delete": "DELETE"}[verb],
            path, fields if verb in {"create", "update"} else {}, required if verb == "create" else (),
        )


def _make_config(name, op):
    label = name.replace("_", " ").title()
    fields = {"operation": (Literal[name], Field(name, title=label, json_schema_extra={
        "ui:hidden": True, "x-display-name": label, "x-is-trigger": False,
        "x-category": op.path.split("/")[1].title(),
    }))}
    for key in re.findall(r"{(\w+)}", op.path):
        fields[key] = (Identifier, Field(..., title=key.replace("_", " ").title()))
    if name.startswith("list_"):
        fields.update({
            "page": (int, Field(1, ge=1, le=1000000)),
            "limit": (int, Field(25, ge=1, le=100)),
            "updated_since": (datetime | None, Field(None, description="Filter updated_at greater than or equal to this time. Uses Farmbrite's documented gte filter.")),
        })
        if name == "list_animals":
            fields["status"] = (Name | None, Field(None, description="Farmbrite lists active animal statuses by default. Set a status such as Sold or Deceased to read other animals."))
    for key, kind in op.body.items():
        if name == "update_order" and key == "order_items":
            kind = Annotated[list[ExistingOrderItem], Field(min_length=1, max_length=100)]
        fields[key] = (kind if key in op.required else kind | None,
            Field(... if key in op.required else None, title=key.replace("_", " ").title()))
    return create_model("Farmbrite" + "".join(part.title() for part in name.split("_")) + "Config",
        __base__=_Input, __module__=__name__, **fields)


CONFIG_MODELS = {name: _make_config(name, op) for name, op in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})


def _poll_config(name, label):
    fields = {}
    if name == "on_animal_changed":
        fields["status"] = (Name | None, Field(None, description="Farmbrite watches active animal statuses by default. Set a status such as Sold or Deceased to watch other animals. Changing this filter establishes a new baseline."))
    return create_model("Farmbrite" + "".join(part.title() for part in name.split("_")) + "Config",
        __base__=PollTriggerConfigBase, __module__=__name__,
        operation=(Literal[name], Field(name, title=label, description="Watch changes by scanning up to 2,000 records sorted by updated_at. Existing records form the initial baseline. A truncated scan fails without advancing the baseline.",
            json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": label})), **fields)


TRIGGERS = {"on_task_changed": "tasks", "on_animal_changed": "animals", "on_crop_changed": "crops"}
POLL_MODELS = {name: _poll_config(name, "New or Updated " + {"tasks": "Task", "animals": "Animal", "crops": "Crop Planting"}[resource])
    for name, resource in TRIGGERS.items()}
globals().update({model.__name__: model for model in POLL_MODELS.values()})
FarmbriteConfig = Annotated[Union[tuple(CONFIG_MODELS.values()) + tuple(POLL_MODELS.values())], Field(discriminator="operation")]


class FarmbriteNodeConfig(NodeConfig[FarmbriteConfig, FarmbriteTokenCredential]):
    pass


class FarmbriteNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-farmbrite"
    connection_evidence = ConnectionEvidence(operation="list_tasks", noun="tasks", label_keys=("title", "id"))
    edit_examples = ["Create a Farmbrite task", "Find livestock updated this week", "Watch for new crop plantings"]

    @classmethod
    def get_config_model(cls):
        return FarmbriteNodeConfig

    @staticmethod
    async def _request(token, method, path, *, params=None, body=None):
        # Fixed origin, encoded single-segment IDs, no redirects or write retries.
        async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                params=params, **({"json": body} if body is not None else {}))
        if response.status_code >= 300:
            # Never reflect request headers or an upstream echo of the secret.
            message = response.text.replace(token, "[redacted]")[:2000]
            raise ValueError(f"Farmbrite HTTP {response.status_code}: {message}")
        if response.status_code == 204 or not response.content:
            return {"http_status": response.status_code}
        try:
            result = response.json()
        except (ValueError, TypeError):
            raise ValueError("Farmbrite returned an invalid JSON response") from None
        if method == "GET" and not isinstance(result, dict):
            raise ValueError("Farmbrite returned an unexpected response shape")
        # Write responses have no schema or example in the published contract.
        # Preserve their JSON acknowledgement without inventing resource fields.
        if isinstance(result, dict) and result.get("success") is False:
            raise ValueError("Farmbrite: " + str(result.get("message", "Request failed")).replace(token, "[redacted]"))
        return result

    @staticmethod
    def _rows(result):
        rows = result.get("data") if isinstance(result, dict) else None
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("Farmbrite list response must contain a data array")
        return rows

    async def _poll(self, token, config):
        operation = config.operation
        rows, seen_ids = [], set()
        for page in range(1, 21):
            params = {"page": page, "limit": 100, "sort_by": "updated_at", "sort_dir": "desc"}
            if operation == "on_animal_changed" and config.status is not None:
                params["status"] = config.status
            result = await self._request(token, "GET", "/" + TRIGGERS[operation],
                params=params)
            batch = self._rows(result)
            for row in batch:
                if not isinstance(row.get("id"), str) or not row["id"] or not isinstance(row.get("updated_at"), str) or not row["updated_at"]:
                    raise ValueError("Farmbrite change detection requires id and updated_at")
                if row["id"] in seen_ids:
                    raise ValueError("Farmbrite pagination repeated a record; baseline unchanged")
                seen_ids.add(row["id"])
            rows.extend(batch)
            total_pages = result.get("total_pages")
            if total_pages is not None:
                if type(total_pages) is not int or total_pages < 0:
                    raise ValueError("Farmbrite returned invalid pagination")
                if page >= total_pages:
                    break
            elif len(batch) < 100:
                break
        else:
            raise ValueError("Farmbrite poll exceeds 2,000 records; baseline unchanged")
        fresh = await self._filter_unseen(rows, lambda row: row["id"] + ":" + row["updated_at"])
        return {"operation": operation, "data": fresh, "change_count": len(fresh)}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Farmbrite personal access token")
        token = self.config.credentials.api_token
        config = self.config.config
        name = config.operation
        if name in TRIGGERS:
            output = await self._poll(token, config)
        else:
            op = OPERATIONS[name]
            values = config.model_dump(mode="json", exclude_none=True)
            path = op.path
            for key in re.findall(r"{(\w+)}", path):
                path = path.replace("{" + key + "}", quote(values[key], safe=""))
            params = None
            if name.startswith("list_"):
                params = {"page": config.page, "limit": config.limit}
                if config.updated_since is not None:
                    params["updated_at"] = "gte:" + config.updated_since.strftime("%Y-%m-%d %H:%M:%S")
                if name == "list_animals" and config.status is not None:
                    params["status"] = config.status
            body = {key: values[key] for key in op.body if key in values} if op.body else None
            result = await self._request(token, op.method, path, params=params, body=body)
            if name.startswith("list_"):
                self._rows(result)
                # Keep the provider's pagination rather than presenting a single page as all records.
                output = {"operation": name, **result, "requested_page": config.page, "requested_limit": config.limit}
            else:
                output = {"operation": name, "data": result}
        await self.emit(output)
        return output

    @classmethod
    def resolve_agent_event(cls, output):
        operation = output.get("operation")
        if operation not in TRIGGERS:
            return super().resolve_agent_event(output)
        rows = output.get("data", [])
        if not rows:
            return None
        lines = []
        for row in rows[:20]:
            if operation == "on_task_changed":
                detail = f"{row.get('title', '')}: {row.get('description', '')}; status {row.get('status', '')}; assigned to {row.get('assigned_to_id', '')}"
            elif operation == "on_animal_changed":
                detail = f"{row.get('name', '')}; tag {row.get('tag_number', '')}; {row.get('type', '')}; status {row.get('status', '')}"
            else:
                detail = f"Plant {row.get('plant_id', '')} in grow location {row.get('plot_id', '')}; stage {row.get('growth_stage', '')}; quantity {row.get('qty', '')}"
            lines.append(f"- {detail} (id {row['id']}, updated {row['updated_at']})")
        return {"text": f"Farmbrite: {len(rows)} new or updated {TRIGGERS[operation]}.\n" + "\n".join(lines), "conversation_key": None}
