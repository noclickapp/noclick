"""Airwallex Client API 2026-08-21: account reads and explicit payout writes."""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret


class AirwallexAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Airwallex API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.airwallex.com/docs/developer-tools/api/manage-api-keys",
            "x-credential-instructions": "In Airwallex Settings > Developer > API keys, copy your client ID and API key. Grant the read and write permissions your operations need. Choose the matching production or sandbox environment. NoClick obtains a short-lived access token for each run; connecting reads your global accounts and does not prove write permissions.",
        })
    credential_type: Literal["airwallex_api_key"] = Field("airwallex_api_key", json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., min_length=1, title="Client ID", json_schema_extra={"ui:widget": "password"})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})
    environment: Literal["production", "sandbox"] = Field("production", title="Environment")

    account_id: str | None = Field(None, title="Target account ID", pattern=r"^[A-Za-z0-9_-]+$", description="Required when a scoped API key covers multiple accounts. Sent as x-login-as during token creation.")

    @field_validator("client_id", "api_key", mode="before")
    @classmethod
    def secret(cls, value, info):
        value = clean_secret(value, field_name=info.field_name)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the value without whitespace or a header")
        return value


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class NumberPage(Input):
    page_num: int = Field(0, ge=0, description="Zero-based page number; this operation returns one page.")
    page_size: int = Field(100, ge=1, le=100, description="Maximum records in this page.")


class CursorPage(Input):
    page: str | None = Field(None, description="Opaque page_after or page_before from the preceding response.")
    page_size: int = Field(100, ge=1, le=100)


class ListBalances(Input):
    operation: Literal["list_balances"] = "list_balances"
    account_type: str = "cash"


class BalanceHistory(NumberPage):
    operation: Literal["list_balance_history"] = "list_balance_history"
    currency: str | None = None
    from_post_at: str | None = None
    to_post_at: str | None = None


class ListTransactions(NumberPage):
    operation: Literal["list_financial_transactions"] = "list_financial_transactions"
    currency: str | None = None
    from_created_at: str | None = None
    to_created_at: str | None = None
    status: str | None = None
    source_id: str | None = None


class Resource(Input):
    id: str = Field(..., min_length=1, max_length=200, description="Airwallex resource ID.")

    @field_validator("id")
    @classmethod
    def identifier(cls, value):
        if value in {".", ".."} or any(c in value for c in "/\\?#") or any(c.isspace() for c in value):
            raise ValueError("Use a single Airwallex resource ID")
        return value


class UUIDResource(Resource):
    @field_validator("id")
    @classmethod
    def uuid_identifier(cls, value):
        return str(UUID(value))


class GetTransaction(Resource):
    operation: Literal["get_financial_transaction"] = "get_financial_transaction"


class ListBeneficiaries(NumberPage):
    operation: Literal["list_beneficiaries"] = "list_beneficiaries"
    name: str | None = None
    company_name: str | None = None
    bank_account_number: str | None = None


class GetBeneficiary(UUIDResource):
    operation: Literal["get_beneficiary"] = "get_beneficiary"


class BankDetails(Input):
    account_currency: str = Field(..., pattern=r"^[A-Z]{3}$")
    account_name: str = Field(..., min_length=1)
    bank_country_code: str = Field(..., pattern=r"^[A-Z]{2}$")
    account_number: str | None = None
    iban: str | None = None
    swift_code: str | None = None
    account_routing_type1: str | None = None
    account_routing_value1: str | None = None
    bank_name: str | None = None


class Address(Input):
    city: str | None = None
    country_code: str = Field(..., pattern=r"^[A-Z]{2}$")
    postcode: str | None = None
    state: str | None = None
    street_address: str | None = None


class Beneficiary(Input):
    entity_type: Literal["COMPANY", "PERSONAL"]
    bank_details: BankDetails
    company_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    address: Address | None = None


class CreateBeneficiary(Input):
    operation: Literal["create_beneficiary"] = "create_beneficiary"
    beneficiary: Beneficiary
    transfer_methods: list[Literal["LOCAL", "SWIFT"]] = Field(..., min_length=1)
    nickname: str | None = None


class DeleteBeneficiary(UUIDResource):
    operation: Literal["delete_beneficiary"] = "delete_beneficiary"


class ListTransfers(CursorPage):
    operation: Literal["list_transfers"] = "list_transfers"
    beneficiary_id: str | None = None
    status: str | None = None
    transfer_currency: str | None = None
    from_created_at: str | None = None
    to_created_at: str | None = None


class GetTransfer(UUIDResource):
    operation: Literal["get_transfer"] = "get_transfer"


class TransferInput(Input):
    beneficiary_id: str = Field(..., description="ID of an existing beneficiary.")
    request_id: str = Field(..., min_length=1, description="Unique idempotency identifier. Reuse it when retrying the same transfer.")
    transfer_amount: str = Field(..., pattern=r"^[0-9]+(?:\.[0-9]+)?$", description="Amount in major currency units, as a decimal string.")
    transfer_currency: str = Field(..., pattern=r"^[A-Z]{3}$")
    source_currency: str = Field(..., pattern=r"^[A-Z]{3}$")
    reason: str = Field(..., min_length=1, description="Provider-supported transfer reason, for example travel.")
    reference: str = Field(..., min_length=1, description="Reference shown to the recipient.")
    transfer_method: Literal["LOCAL", "SWIFT"]
    transfer_date: str | None = Field(None, description="Scheduled date, YYYY-MM-DD.")
    swift_charge_option: Literal["SHARED", "PAYER"] | None = None

    @field_validator("beneficiary_id")
    @classmethod
    def beneficiary_uuid(cls, value):
        return str(UUID(value))


class CreateTransfer(TransferInput):
    operation: Literal["create_transfer"] = "create_transfer"


class ValidateTransfer(TransferInput):
    operation: Literal["validate_transfer"] = "validate_transfer"


class CancelTransfer(UUIDResource):
    operation: Literal["cancel_transfer"] = "cancel_transfer"


class ListGlobalAccounts(CursorPage):
    operation: Literal["list_global_accounts"] = "list_global_accounts"
    country_code: str | None = None
    nick_name: str | None = None
    status: str | None = None


class GetGlobalAccount(Resource):
    operation: Literal["get_global_account"] = "get_global_account"


class UpdateGlobalAccount(UUIDResource):
    operation: Literal["update_global_account"] = "update_global_account"
    nick_name: str = Field(..., min_length=1)


AirwallexConfig = Annotated[Union[ListBalances, BalanceHistory, ListTransactions,
    GetTransaction, ListBeneficiaries, GetBeneficiary, CreateBeneficiary,
    DeleteBeneficiary, ListTransfers, GetTransfer, CreateTransfer, ValidateTransfer,
    CancelTransfer, ListGlobalAccounts, GetGlobalAccount, UpdateGlobalAccount],
    Field(discriminator="operation")]


class AirwallexFullConfig(NodeConfig[AirwallexConfig, AirwallexAPIKeyCredential]):
    pass


# One provider operation per workflow operation; login is solely the authentication prerequisite.
ROUTES = {
    "list_balances": ("GET", "/balances/current"),
    "list_balance_history": ("GET", "/balances/history"),
    "list_financial_transactions": ("GET", "/financial_transactions"),
    "get_financial_transaction": ("GET", "/financial_transactions/{id}"),
    "list_beneficiaries": ("GET", "/beneficiaries"),
    "get_beneficiary": ("GET", "/beneficiaries/{id}"),
    "create_beneficiary": ("POST", "/beneficiaries/create"),
    "delete_beneficiary": ("POST", "/beneficiaries/{id}/delete"),
    "list_transfers": ("GET", "/transfers"),
    "get_transfer": ("GET", "/transfers/{id}"),
    "create_transfer": ("POST", "/transfers/create"),
    "validate_transfer": ("POST", "/transfers/validate"),
    "cancel_transfer": ("POST", "/transfers/{id}/cancel"),
    "list_global_accounts": ("GET", "/global_accounts"),
    "get_global_account": ("GET", "/global_accounts/{id}"),
    "update_global_account": ("POST", "/global_accounts/{id}/update"),
}


class AirwallexNode(WorkflowNode):
    integration_type = "automation-airwallex"
    connection_evidence = ConnectionEvidence(operation="list_global_accounts", noun="global accounts", label_keys=("nick_name", "account_name", "id"))

    @classmethod
    def get_config_model(cls):
        return AirwallexFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Airwallex API key")
        credential = self.config.credentials
        config = self.config.config
        base = {"production": "https://api.airwallex.com", "sandbox": "https://api.sandbox.airwallex.com"}[credential.environment] + "/api/v1"
        secrets = [credential.api_key, credential.client_id]

        def redact(value):
            if isinstance(value, str):
                for secret in secrets:
                    value = value.replace(secret, "[redacted]")
                return value
            if isinstance(value, dict):
                return {key: redact(item) for key, item in value.items()}
            if isinstance(value, list):
                return [redact(item) for item in value]
            return value

        def checked(response):
            if not 200 <= response.status_code < 300:
                # Preserve provider rejection wording for the credential-connect verdict.
                raise ValueError(redact(f"Airwallex HTTP {response.status_code}: {response.text}"))
            return response.json()

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            auth = await client.post(base + "/authentication/login", headers={
                "x-api-key": credential.api_key, "x-client-id": credential.client_id,
                "Content-Type": "application/json",
                **({"x-login-as": credential.account_id} if credential.account_id else {}),
            })
            login = checked(auth)
            token = login.get("token") if isinstance(login, dict) else None
            if not isinstance(token, str) or not token or any(c.isspace() for c in token):
                raise ValueError("Airwallex login did not return an access token")
            secrets.append(token)
            method, route = ROUTES[config.operation]
            fields = config.model_dump(exclude_none=True, exclude={"operation", "id"})
            route = route.replace("{id}", quote(getattr(config, "id", ""), safe=""))
            response = await client.request(method, base + route,
                headers={"Authorization": "Bearer " + token},
                **({"params": fields} if method == "GET" else {"json": fields} if fields else {}))
            body = checked(response)
            if config.operation == "list_balances":
                valid = isinstance(body, list)
            elif config.operation.startswith("list_"):
                valid = isinstance(body, dict) and isinstance(body.get("items"), list)
            elif config.operation == "delete_beneficiary":
                valid = isinstance(body, bool)
            elif config.operation == "validate_transfer":
                valid = isinstance(body, (dict, str))
            else:
                valid = isinstance(body, dict)
            if not valid:
                raise ValueError("Airwallex returned an unexpected response shape")
        return {"status": "success", "operation": config.operation, "data": redact(body)}
