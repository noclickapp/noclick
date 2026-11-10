"""Ramp cards, transactions, reimbursements, and bills over the Developer API.

Contract: https://docs.ramp.com/openapi/developer-api.json (v1).
Authentication: pasted bearer access token; no client secret or token exchange.
Client-credentials tokens expire after 10 days; replace expired tokens manually.
Pagination is explicit: pass the start cursor from page.next for the next page.
Ramp supports signed webhooks separately; this node exposes REST operations only.
"""
from datetime import date as Date
import json
import time
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Discriminator, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement

RAMP_API_BASE = "https://api.ramp.com/developer/v1"


class RampAccessTokenCredential(BaseModel):
    credential_type: Literal["ramp_access_token"] = Field(
        "ramp_access_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ..., title="Access Token", min_length=1,
        description="Ramp Developer API bearer access token. Paste the token without the Bearer prefix.",
        json_schema_extra={"ui:widget": "password"},
    )
    model_config = ConfigDict(json_schema_extra={
        "x-credential-url": "https://docs.ramp.com/developer-api/v1/guides/getting-started",
        "x-credential-instructions": "Create a Ramp Developer API app and obtain an access token using client credentials. Include business:read, cards:read, cards:write, transactions:read, transactions:write, reimbursements:read, reimbursements:write, bills:read and bills:write for all operations. Paste only the access token. Client-credentials tokens expire after 10 days; obtain and paste a replacement when expired. Other token lifetimes follow expires_in.",
    })


def _operation(name: str, category: str) -> Any:
    return Field(name, title=name.replace("_", " ").title(), json_schema_extra={
        "const": name, "ui:hidden": True, "x-category": category,
        "x-display-name": name.replace("_", " ").title(), "x-is-trigger": False,
    })


class RampPageConfig(BaseModel):
    page_size: int = Field(20, ge=2, le=100, title="Page Size", description="Results per page, from 2 to 100.")
    start: Optional[str] = Field(None, title="Start Cursor", description="Use the start query value in the previous response's page.next URL.")


def _json_field(description: str, *, required: bool = False) -> Any:
    return Field(... if required else None, description=description,
                 json_schema_extra={"ui:widget": "textarea"})


class RampGetBusinessConfig(BaseModel):
    operation: Literal["get_business"] = _operation("get_business", "Account")


class RampListPhysicalCardsConfig(RampPageConfig):
    operation: Literal["list_physical_cards"] = _operation("list_physical_cards", "Cards")
    user_id: Optional[str] = Field(None, title="User Id")
    display_name: Optional[str] = Field(None, title="Display Name")


class RampGetPhysicalCardConfig(BaseModel):
    operation: Literal["get_physical_card"] = _operation("get_physical_card", "Cards")
    card_id: str = Field(..., title="Card Id", min_length=1, description="Ramp resource UUID.")


class RampCreatePhysicalCardConfig(BaseModel):
    operation: Literal["create_physical_card"] = _operation("create_physical_card", "Cards")
    user_id: str = Field(..., title="User ID", description="UUID of the employee receiving this card.")
    shipping_address: str = _json_field("JSON address object: address1, city, country, first_name, last_name, postal_code and state.", required=True)
    fund_id: Optional[str] = Field(None, title="Fund ID", description="Associate the card with this fund UUID.")


class RampUpdatePhysicalCardConfig(BaseModel):
    operation: Literal["update_physical_card"] = _operation("update_physical_card", "Cards")
    card_id: str = Field(..., title="Card Id", min_length=1, description="Ramp resource UUID.")
    display_name: str = Field(..., title="Display Name", min_length=1, description="New cosmetic card name.")


class RampSuspendPhysicalCardConfig(BaseModel):
    operation: Literal["suspend_physical_card"] = _operation("suspend_physical_card", "Cards")
    card_id: str = Field(..., title="Card Id", min_length=1, description="Ramp resource UUID.")


class RampUnsuspendPhysicalCardConfig(BaseModel):
    operation: Literal["unsuspend_physical_card"] = _operation("unsuspend_physical_card", "Cards")
    card_id: str = Field(..., title="Card Id", min_length=1, description="Ramp resource UUID.")


class RampListVirtualCardsConfig(RampPageConfig):
    operation: Literal["list_virtual_cards"] = _operation("list_virtual_cards", "Cards")
    user_id: Optional[str] = Field(None, title="User Id")


class RampGetVirtualCardConfig(BaseModel):
    operation: Literal["get_virtual_card"] = _operation("get_virtual_card", "Cards")
    card_id: str = Field(..., title="Card Id", min_length=1, description="Ramp resource UUID.")


class RampListTransactionsConfig(RampPageConfig):
    operation: Literal["list_transactions"] = _operation("list_transactions", "Transactions")
    user_id: Optional[str] = Field(None, title="User Id")
    from_date: Optional[str] = Field(None, title="From Date")
    to_date: Optional[str] = Field(None, title="To Date")


class RampGetTransactionConfig(BaseModel):
    operation: Literal["get_transaction"] = _operation("get_transaction", "Transactions")
    transaction_id: str = Field(..., title="Transaction Id", min_length=1, description="Ramp resource UUID.")


class RampUpdateTransactionConfig(BaseModel):
    operation: Literal["update_transaction"] = _operation("update_transaction", "Transactions")
    transaction_id: str = Field(..., title="Transaction Id", min_length=1, description="Ramp resource UUID.")
    line_items: str = _json_field("JSON array of split line items: amount in minor units, memo, and accounting_field_selections. Use [] to unsplit.", required=True)


class RampListReimbursementsConfig(RampPageConfig):
    operation: Literal["list_reimbursements"] = _operation("list_reimbursements", "Reimbursements")
    user_id: Optional[str] = Field(None, title="User Id")
    from_date: Optional[str] = Field(None, title="From Date")
    to_date: Optional[str] = Field(None, title="To Date")


class RampGetReimbursementConfig(BaseModel):
    operation: Literal["get_reimbursement"] = _operation("get_reimbursement", "Reimbursements")
    reimbursement_id: str = Field(..., title="Reimbursement Id", min_length=1, description="Ramp resource UUID.")


class RampCreateMileageReimbursementConfig(BaseModel):
    operation: Literal["create_mileage_reimbursement"] = _operation("create_mileage_reimbursement", "Reimbursements")
    distance: float = Field(..., gt=0, title="Distance")
    reimbursee_id: str = Field(..., title="Reimbursee ID", description="UUID of the employee being reimbursed.")
    trip_date: Date = Field(..., title="Trip Date")
    distance_units: Literal["MILES", "KILOMETERS"] = Field("MILES", title="Distance Units")
    memo: Optional[str] = Field(None, title="Memo")
    start_location: Optional[str] = Field(None, title="Start Location")
    end_location: Optional[str] = Field(None, title="End Location")


class RampListBillsConfig(RampPageConfig):
    operation: Literal["list_bills"] = _operation("list_bills", "Bills")
    vendor_id: Optional[str] = Field(None, title="Vendor Id")
    invoice_number: Optional[str] = Field(None, title="Invoice Number")


class RampGetBillConfig(BaseModel):
    operation: Literal["get_bill"] = _operation("get_bill", "Bills")
    bill_id: str = Field(..., title="Bill Id", min_length=1, description="Ramp resource UUID.")


class RampCreateBillConfig(BaseModel):
    operation: Literal["create_bill"] = _operation("create_bill", "Bills")
    vendor_id: str = Field(..., title="Vendor ID", description="UUID of the bill vendor.")
    entity_id: str = Field(..., title="Entity ID", description="UUID of the associated business entity.")
    due_at: Date = Field(..., title="Due Date")
    issued_at: Date = Field(..., title="Issued Date")
    invoice_currency: str = Field("USD", title="Invoice Currency", description="Three-letter invoice currency code, such as USD.")
    invoice_number: str = Field(..., title="Invoice Number")
    line_items: str = _json_field("JSON array of bill line items: amount, memo and accounting_field_selections. Ramp bill amounts are decimal major currency units.", required=True)
    payment_method: Literal["ACH", "CARD", "CHECK", "DOMESTIC_WIRE", "INTERNATIONAL", "PAID_MANUALLY", "ONE_TIME_CARD", "ONE_TIME_CARD_DELIVERY", "LOCAL_BANK_TRANSFER", "SWIFT", "CRYPTO_WALLET_TRANSFER"] = Field(..., title="Payment Method")
    payment_details: Optional[str] = _json_field("JSON payment details matching payment_method. For ACH, source_bank_account_id and vendor_account_id; see Ramp's API reference.")
    vendor_contact_id: Optional[str] = Field(None, title="Vendor Contact ID")
    payment_date: Optional[Date] = Field(None, title="Payment Date")
    memo: Optional[str] = Field(None, title="Memo")


class RampUpdateBillConfig(BaseModel):
    operation: Literal["update_bill"] = _operation("update_bill", "Bills")
    bill_id: str = Field(..., title="Bill Id", min_length=1, description="Ramp resource UUID.")
    memo: str = Field(..., title="Memo", description="Replacement bill memo.")
    due_at: Optional[Date] = Field(None, title="Due Date")


class RampDeleteBillConfig(BaseModel):
    operation: Literal["delete_bill"] = _operation("delete_bill", "Bills")
    bill_id: str = Field(..., title="Bill Id", min_length=1, description="Ramp resource UUID.")


RampConfig = Annotated[Union[
    RampGetBusinessConfig,
    RampListPhysicalCardsConfig,
    RampGetPhysicalCardConfig,
    RampCreatePhysicalCardConfig,
    RampUpdatePhysicalCardConfig,
    RampSuspendPhysicalCardConfig,
    RampUnsuspendPhysicalCardConfig,
    RampListVirtualCardsConfig,
    RampGetVirtualCardConfig,
    RampListTransactionsConfig,
    RampGetTransactionConfig,
    RampUpdateTransactionConfig,
    RampListReimbursementsConfig,
    RampGetReimbursementConfig,
    RampCreateMileageReimbursementConfig,
    RampListBillsConfig,
    RampGetBillConfig,
    RampCreateBillConfig,
    RampUpdateBillConfig,
    RampDeleteBillConfig,
], Discriminator("operation")]


class RampNodeConfig(NodeConfig[RampConfig, RampAccessTokenCredential]):
    pass


# Scopes copied from each operation in the pinned official OpenAPI contract.
RAMP_SCOPES = ScopeRegistry("ramp", {
    "get_business": ScopeRequirement(('business:read',)),
    "list_physical_cards": ScopeRequirement(('cards:read',)),
    "get_physical_card": ScopeRequirement(('cards:read',)),
    "create_physical_card": ScopeRequirement(('cards:write',)),
    "update_physical_card": ScopeRequirement(('cards:write',)),
    "suspend_physical_card": ScopeRequirement(('cards:write',)),
    "unsuspend_physical_card": ScopeRequirement(('cards:write',)),
    "list_virtual_cards": ScopeRequirement(('cards:read',)),
    "get_virtual_card": ScopeRequirement(('cards:read',)),
    "list_transactions": ScopeRequirement(('transactions:read',)),
    "get_transaction": ScopeRequirement(('transactions:read',)),
    "update_transaction": ScopeRequirement(('transactions:write',)),
    "list_reimbursements": ScopeRequirement(('reimbursements:read',)),
    "get_reimbursement": ScopeRequirement(('reimbursements:read',)),
    "create_mileage_reimbursement": ScopeRequirement(('reimbursements:write',)),
    "list_bills": ScopeRequirement(('bills:read',)),
    "get_bill": ScopeRequirement(('bills:read',)),
    "create_bill": ScopeRequirement(('bills:write',)),
    "update_bill": ScopeRequirement(('bills:write',)),
    "delete_bill": ScopeRequirement(('bills:write',)),
})

OPERATIONS = {
    "get_business": ('GET', '/business'),
    "list_physical_cards": ('GET', '/cards/physical'),
    "get_physical_card": ('GET', '/cards/physical/{card_id}'),
    "create_physical_card": ('POST', '/cards/physical'),
    "update_physical_card": ('PATCH', '/cards/physical/{card_id}'),
    "suspend_physical_card": ('POST', '/cards/physical/{card_id}/suspension'),
    "unsuspend_physical_card": ('DELETE', '/cards/physical/{card_id}/suspension'),
    "list_virtual_cards": ('GET', '/cards/virtual'),
    "get_virtual_card": ('GET', '/cards/virtual/{card_id}'),
    "list_transactions": ('GET', '/transactions'),
    "get_transaction": ('GET', '/transactions/{transaction_id}'),
    "update_transaction": ('PATCH', '/transactions/{transaction_id}'),
    "list_reimbursements": ('GET', '/reimbursements'),
    "get_reimbursement": ('GET', '/reimbursements/{reimbursement_id}'),
    "create_mileage_reimbursement": ('POST', '/reimbursements/mileage'),
    "list_bills": ('GET', '/bills'),
    "get_bill": ('GET', '/bills/{bill_id}'),
    "create_bill": ('POST', '/bills'),
    "update_bill": ('PATCH', '/bills/{bill_id}'),
    "delete_bill": ('DELETE', '/bills/{bill_id}'),
}


def _json_value(value: str, expected: type, field: str) -> Any:
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{field} must contain valid JSON") from exc
    if not isinstance(parsed, expected):
        raise ValueError(f"{field} must be a JSON {expected.__name__}")
    if expected is list and any(not isinstance(item, dict) for item in parsed):
        raise ValueError(f"{field} must contain JSON objects")
    return parsed


class RampNode(WorkflowNode):
    integration_type = "automation-ramp"
    credential_provider_labels = {"ramp": "Ramp Account"}
    auto_select_credential = False
    scope_registry = RAMP_SCOPES
    connection_evidence = ConnectionEvidence(identity_operation="get_business", noun="business", identity_keys=("business_name_legal", "business_name_on_card"))

    @classmethod
    def get_config_model(cls):
        return RampNodeConfig

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.config, RampNodeConfig):
            raise ValueError("Ramp configuration is required")
        if not self.config.credentials:
            raise ValueError("Connect a Ramp access token first")
        config = self.config.config
        operation = config.operation
        method, path = OPERATIONS[operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for key in ("card_id", "transaction_id", "reimbursement_id", "bill_id"):
            if key in values:
                # IDs are single path segments; never let a configured value change the endpoint.
                value = values.pop(key)
                if any(char in value for char in "/?#") or value in (".", ".."):
                    raise ValueError(f"{key} must be a Ramp resource ID")
                path = path.replace("{" + key + "}", quote(value, safe=""))
        params = values if method == "GET" else None
        body = values if method in ("POST", "PATCH") and values else None
        if body:
            for key, expected in (("shipping_address", dict), ("line_items", list), ("payment_details", dict)):
                if key in body:
                    body[key] = _json_value(body[key], expected, key)
            if "payment_details" in body:
                # Ramp discriminates the nested payment schema separately from the bill.
                body["payment_details"]["payment_method"] = body["payment_method"]
        started = time.perf_counter()
        result = {"action": operation, "timing_ms": {}}
        token = self.config.credentials.access_token
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method, RAMP_API_BASE + path,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    params=params, json=body,
                )
            result["status_code"] = response.status_code
            if not response.is_success:
                # Preserve provider wording for credential rejection, but never echo the token.
                message = response.text.replace(token, "[redacted]")
                return {**result, "status": "error", "error": message or f"Ramp HTTP {response.status_code}"}
            if response.status_code == 204:
                return {**result, "status": "success", "data": {"success": True}}
            try:
                data = response.json()
            except ValueError:
                return {**result, "status": "error", "error": "Ramp returned invalid JSON"}
            if not isinstance(data, dict) or any(data.get(k) for k in ("error", "errors")):
                return {**result, "status": "error", "error": "Ramp returned an invalid response"}
            if operation == "get_business" and not (
                isinstance(data.get("id"), str) and data["id"].strip()
                and isinstance(data.get("business_name_legal"), str) and data["business_name_legal"].strip()
            ):
                return {**result, "status": "error", "error": "Ramp returned an invalid business response"}
            if operation.startswith("list_") and not (
                isinstance(data.get("data"), list) and isinstance(data.get("page"), dict)
                and all(isinstance(row, dict) for row in data["data"])
            ):
                return {**result, "status": "error", "error": "Ramp returned an invalid page response"}
            return {**result, "status": "success", "data": data}
        except httpx.TimeoutException:
            return {**result, "status": "error", "error": "Ramp request timed out"}
        except httpx.RequestError:
            return {**result, "status": "error", "error": "Could not reach the Ramp API"}
        finally:
            result["timing_ms"]["api_request"] = round((time.perf_counter() - started) * 1000, 2)
