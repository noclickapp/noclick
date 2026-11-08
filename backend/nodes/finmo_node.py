"""Finmo API v1.5.1: fixed operations backed by the publisher's Postman collection.

Lists return exactly one page. Payment creation is never retried automatically;
provider acceptance does not mean settlement or beneficiary receipt.
"""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.finmo.net/v1"


class FinmoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Finmo API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://dashboard.finmo.net",
        "x-credential-instructions": "Paste your Finmo access key and secret key from the developer settings in your Finmo dashboard. Use keys for the production API. NoClick verifies access by reading your wallets. Payment creation can move money; Finmo controls the permissions on these keys.",
    })
    credential_type: Literal["finmo_api_key"] = Field("finmo_api_key", json_schema_extra={"ui:hidden": True})
    access_key: str = Field(..., title="Access key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    secret_key: str = Field(..., title="Secret key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("access_key", "secret_key", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="Finmo key")
        if ":" in value or any(c.isspace() for c in value):
            raise ValueError("Paste the key alone, without a Basic header or whitespace")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def path_identifiers(cls, value, info):
        if info.field_name in {"customer_id", "payin_id", "payout_id", "refund_id", "wallet_id", "transaction_id", "wallet_transaction_id"} and value is not None:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
                raise ValueError("Use a single Finmo resource ID")
        return value

class FinmoCreatePayinBodyAdvancedRedirectUrl(_Config):
    cancelled_url: str | None = None
    completed_url: str | None = None
    expired_url: str | None = None
    failed_url: str | None = None

class FinmoCreatePayinBody(_Config):
    advanced_redirect_url: FinmoCreatePayinBodyAdvancedRedirectUrl | None = None
    amount: float = Field(..., description="Documented Finmo request field")
    credit_wallet_id: str | None = None
    currency: str = Field(..., description="Documented Finmo request field")
    customer_id: str | None = None
    description: str | None = None
    expire_at: str | None = None
    fees_wallet_id: str | None = None
    metadata: dict[str, Any] | None = None
    organization_reference_id: str | None = None
    payin_method_name: str = Field(..., description="Documented Finmo request field")
    payin_method_param: dict[str, Any] | None = None
    payin_type: str | None = None
    receipt_email: str | None = None
    redirect_url: str | None = None
    webhook_url: str | None = None

class FinmoCreatePayinConfig(_Config):
    """Create Payin. Finmo acceptance is returned verbatim."""
    operation: Literal["create_payin"] = Field("create_payin", json_schema_extra={"ui:hidden": True})
    body: FinmoCreatePayinBody = Field(..., description="Finmo request body; method-specific fields come from Finmo method requirements.")

class FinmoListPayinsConfig(_Config):
    """List All Payins. Returns one page; use page to continue."""
    operation: Literal["list_payins"] = Field("list_payins", json_schema_extra={"ui:hidden": True})
    status: str | None = Field(None, description='List transactions by Payin Status (PENDING, COMPLETED, EXPIRED, CANCELLED, CREATED & FAILED)')
    created_at: str | None = Field(None, description='YYYY-MM-DD (UTC date). If you wish to search based on local time then use start_time and end_time fields')
    customer_id: str | None = Field(None, description='List transactions for a specific customer_id')
    credit_wallet_id: str | None = Field(None, description="List transactions for a specific wallet_id. If you don't provide the wallet_id, it will fetch all transaction from the Organization Payin wallet")
    payin_method_name: str | None = Field(None, description='Payin method name')
    start_time: str | None = Field(None, description='EPOCH timestamp')
    end_time: str | None = Field(None, description='EPOCH timestamp')
    limit: int = Field(10, ge=1, le=100, description='Max number of transactions per page. Default is 10 transactions per page')
    page: int = Field(1, ge=1, le=1000000, description='The page number to return. If unspecified, the first page is returned')

class FinmoGetPayinConfig(_Config):
    """Retrieve Payin. Finmo acceptance is returned verbatim."""
    operation: Literal["get_payin"] = Field("get_payin", json_schema_extra={"ui:hidden": True})
    payin_id: str = Field(..., min_length=1, max_length=200, description="Finmo resource ID")

class FinmoCancelPayinConfig(_Config):
    """Cancel payin. Finmo acceptance is returned verbatim."""
    operation: Literal["cancel_payin"] = Field("cancel_payin", json_schema_extra={"ui:hidden": True})
    payin_id: str = Field(..., min_length=1, max_length=200, description="Finmo resource ID")

class FinmoCreateRefundBody(_Config):
    payin_id: str = Field(..., description="Documented Finmo request field")

class FinmoCreateRefundConfig(_Config):
    """Create Refund. Finmo acceptance is returned verbatim."""
    operation: Literal["create_refund"] = Field("create_refund", json_schema_extra={"ui:hidden": True})
    body: FinmoCreateRefundBody = Field(..., description="Finmo request body; method-specific fields come from Finmo method requirements.")

class FinmoListRefundsConfig(_Config):
    """List all Refunds. Returns one page; use page to continue."""
    operation: Literal["list_refunds"] = Field("list_refunds", json_schema_extra={"ui:hidden": True})
    status: str | None = Field(None, description='List refunds by their status (PENDING, COMPLETED & FAILED)')
    payin_id: str | None = Field(None, description='List all refunds with the original Payin_id')
    amount: str | None = Field(None, description='Max number of transactions per page. Default is 10 transactions per page')
    created_at: str | None = Field(None, description='YYYY-MM-DD (UTC date). If you wish to search based on local time then use start_time and end_time fields')
    start_time: str | None = Field(None, description='EPOCH timestamp')
    end_time: str | None = Field(None, description='EPOCH timestamp')
    limit: int = Field(10, ge=1, le=100, description='Max number of transactions per page. Default is 10 transactions per page')
    page: int = Field(1, ge=1, le=1000000, description='The page number to return. If unspecified, the first page is returned')

class FinmoGetRefundConfig(_Config):
    """Retrieve Refund by ID. Finmo acceptance is returned verbatim."""
    operation: Literal["get_refund"] = Field("get_refund", json_schema_extra={"ui:hidden": True})
    refund_id: str = Field(..., min_length=1, max_length=200, description="Finmo resource ID")

class FinmoCreatePayoutBodyPayoutControls(_Config):
    is_beneficiary_name_match_enabled: bool | None = None
    is_payout_on_name_mismatch_allowed: bool | None = None

class FinmoCreatePayoutBody(_Config):
    beneficiary_amount: float = Field(..., description="Documented Finmo request field")
    beneficiary_currency: str = Field(..., description="Documented Finmo request field")
    debit_wallet_id: str = Field(..., description="Documented Finmo request field")
    description: str | None = None
    fees_wallet_id: str | None = None
    fx_rate_id: str | None = None
    metadata: dict[str, Any] | None = None
    organization_reference_id: str | None = None
    payout_beneficiary_id: str | None = None
    payout_sender_id: str | None = None
    payout_sender_param: dict[str, Any] | None = None
    payout_beneficiary_param: dict[str, Any] | None = None
    payout_controls: FinmoCreatePayoutBodyPayoutControls | None = None
    payout_method_name: str = Field(..., description="Documented Finmo request field")
    payout_method_param: dict[str, Any] | None = None
    payout_reference: str | None = None
    purpose_code: str | None = None
    receipt_email: str | None = None
    sender_amount: float | None = None
    sender_country: str | None = None
    sender_currency: str | None = None
    webhook_url: str | None = None

class FinmoCreatePayoutConfig(_Config):
    """Create Payout. Finmo acceptance is returned verbatim."""
    operation: Literal["create_payout"] = Field("create_payout", json_schema_extra={"ui:hidden": True})
    body: FinmoCreatePayoutBody = Field(..., description="Finmo request body; method-specific fields come from Finmo method requirements.")

class FinmoListPayoutsConfig(_Config):
    """List all Payouts. Returns one page; use page to continue."""
    operation: Literal["list_payouts"] = Field("list_payouts", json_schema_extra={"ui:hidden": True})
    limit: int = Field(10, ge=1, le=100, description='Max number of transactions per page. Default is 10 transactions per page')
    page: int = Field(1, ge=1, le=1000000, description='The page number to return. If unspecified, the first page is returned')
    status: str | None = Field(None, description='List transactions by Payout Status (PENDING, COMPLETED, FAILED)')
    payout_method_name: str | None = Field(None, description='Payout method name')
    created_at: str | None = Field(None, description='YYYY-MM-DD (UTC date). If you wish to search based on local time then use start_time and end_time fields')
    start_time: str | None = Field(None, description='EPOCH timestamp')
    end_time: str | None = Field(None, description='EPOCH timestamp')

class FinmoGetPayoutConfig(_Config):
    """Retrieve Payout. Finmo acceptance is returned verbatim."""
    operation: Literal["get_payout"] = Field("get_payout", json_schema_extra={"ui:hidden": True})
    payout_id: str = Field(..., min_length=1, max_length=200, description="Finmo resource ID")

class FinmoCreateCustomerBodyIndividual(_Config):
    address_city: str | None = None
    address_country: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    address_state: str | None = None
    address_zip_code: str | None = None
    country_of_residence: str | None = None
    dob: str | None = None
    email: str | None = None
    first_name: str | None = None
    identification_custom_type: str | None = None
    identification_type: str | None = None
    identification_value: str | None = None
    last_name: str | None = None
    nationality: str | None = None
    organization_reference_id: str | None = None
    phone_country_code: str | None = None
    phone_number: str | None = None
    identification_document_id: str | None = None
    address_proof_document_id: str | None = None

class FinmoCreateCustomerBodyAuthorizedUser(_Config):
    address_city: str | None = None
    address_country: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    address_state: str | None = None
    address_zip_code: str | None = None
    country_of_residence: str | None = None
    dob: str | None = None
    email: str | None = None
    first_name: str | None = None
    identification_custom_type: str | None = None
    identification_type: str | None = None
    identification_value: str | None = None
    last_name: str | None = None
    nationality: str | None = None
    phone_country_code: str | None = None
    phone_number: str | None = None
    identification_document_id: str | None = None
    address_proof_document_id: str | None = None

class FinmoCreateCustomerBodyCompany(_Config):
    address_city: str | None = None
    address_country: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    address_state: str | None = None
    address_zip_code: str | None = None
    email: str | None = None
    incorporation_country: str | None = None
    name: str | None = None
    organization_reference_id: str | None = None
    phone_country_code: str | None = None
    phone_number: str | None = None
    registration_number: str | None = None
    incorporation_certificate_id: str | None = None
    address_proof_document_id: str | None = None

class FinmoCreateCustomerBody(_Config):
    description: str | None = None
    account_usage_purpose: str | None = None
    individual: FinmoCreateCustomerBodyIndividual | None = None
    authorized_user: FinmoCreateCustomerBodyAuthorizedUser | None = None
    company: FinmoCreateCustomerBodyCompany | None = None
    metadata: dict[str, Any] | None = None
    type: Literal["individual", "company"] = Field(..., description="Documented Finmo request field")

class FinmoCreateCustomerConfig(_Config):
    """New Customer. Finmo acceptance is returned verbatim."""
    operation: Literal["create_customer"] = Field("create_customer", json_schema_extra={"ui:hidden": True})
    body: FinmoCreateCustomerBody = Field(..., description="Finmo request body; method-specific fields come from Finmo method requirements.")

class FinmoListCustomersConfig(_Config):
    """Get All Customers. Returns one page; use page to continue."""
    operation: Literal["list_customers"] = Field("list_customers", json_schema_extra={"ui:hidden": True})
    type: str | None = Field(None, description='type of customer - individual or company')
    created_at: str | None = Field(None, description='YYYY-MM-DD (UTC date). If you wish to search based on local time then use start_time and end_time fields')
    include_deleted: bool | None = Field(None, description='Include deleted customers')
    start_time: str | None = Field(None, description='EPOCH timestamp')
    end_time: str | None = Field(None, description='EPOCH timestamp')
    limit: int = Field(10, ge=1, le=100, description='Max number of transaction record per page. Default is 10 transactions per page')
    page: int = Field(1, ge=1, le=1000000, description='The page number to return. If unspecified, the first page is returned')

class FinmoUpdateCustomerBodyIndividual(_Config):
    address_city: str | None = None
    address_country: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    address_state: str | None = None
    address_zip_code: str | None = None
    country_of_residence: str | None = None
    dob: str | None = None
    email: str | None = None
    first_name: str | None = None
    identification_custom_type: str | None = None
    identification_type: str | None = None
    identification_value: str | None = None
    last_name: str | None = None
    nationality: str | None = None
    organization_reference_id: str | None = None
    phone_country_code: str | None = None
    phone_number: str | None = None
    identification_document_id: str | None = None
    address_proof_document_id: str | None = None

class FinmoUpdateCustomerBodyCompanyAuthorizedUser(_Config):
    address_city: str | None = None
    address_country: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    address_state: str | None = None
    address_zip_code: str | None = None
    country_of_residence: str | None = None
    dob: str | None = None
    email: str | None = None
    first_name: str | None = None
    identification_custom_type: str | None = None
    identification_type: str | None = None
    identification_value: str | None = None
    last_name: str | None = None
    nationality: str | None = None
    phone_country_code: str | None = None
    phone_number: str | None = None
    identification_document_id: str | None = None
    address_proof_document_id: str | None = None

class FinmoUpdateCustomerBodyCompany(_Config):
    address_city: str | None = None
    address_country: str | None = None
    address_line1: str | None = None
    address_line2: str | None = None
    address_state: str | None = None
    address_zip_code: str | None = None
    email: str | None = None
    incorporation_country: str | None = None
    name: str | None = None
    organization_reference_id: str | None = None
    phone_country_code: str | None = None
    phone_number: str | None = None
    registration_number: str | None = None
    incorporation_certificate_document_id: str | None = None
    address_proof_document_id: str | None = None
    incorporation_date: str | None = None
    authorized_user: FinmoUpdateCustomerBodyCompanyAuthorizedUser | None = None

class FinmoUpdateCustomerBody(_Config):
    currency: str | None = None
    description: str | None = None
    account_usage_purpose: str | None = None
    is_enabled: bool | None = None
    individual: FinmoUpdateCustomerBodyIndividual | None = None
    company: FinmoUpdateCustomerBodyCompany | None = None
    metadata: dict[str, Any] | None = None
    type: Literal["individual", "company"] | None = None

class FinmoUpdateCustomerConfig(_Config):
    """Update Customer. Finmo acceptance is returned verbatim."""
    operation: Literal["update_customer"] = Field("update_customer", json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, max_length=200, description="Finmo resource ID")
    body: FinmoUpdateCustomerBody = Field(..., description="Finmo request body; method-specific fields come from Finmo method requirements.")

class FinmoDisableCustomerConfig(_Config):
    """Disable Customer. Finmo acceptance is returned verbatim."""
    operation: Literal["disable_customer"] = Field("disable_customer", json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, max_length=200, description="Finmo resource ID")

class FinmoEnableCustomerConfig(_Config):
    """Enable Customer. Finmo acceptance is returned verbatim."""
    operation: Literal["enable_customer"] = Field("enable_customer", json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, max_length=200, description="Finmo resource ID")

class FinmoGetCustomerConfig(_Config):
    """Get Customer by ID. Finmo acceptance is returned verbatim."""
    operation: Literal["get_customer"] = Field("get_customer", json_schema_extra={"ui:hidden": True})
    customer_id: str = Field(..., min_length=1, max_length=200, description="Finmo resource ID")
    include_deleted: bool | None = Field(None, description='Include deleted customer')

class FinmoListWalletsConfig(_Config):
    """Get All Wallets. Returns one page; use page to continue."""
    operation: Literal["list_wallets"] = Field("list_wallets", json_schema_extra={"ui:hidden": True})
    category: str | None = Field(None, description='Filter your wallets by type of wallet. Supported values are payin, payout, fees, general.\nNote: general category wallets are classified as customer wallet')
    created_at: str | None = Field(None, description='YYYY-MM-DD (UTC date). If you wish to search based on local time then use start_time and end_time fields')
    start_time: str | None = Field(None, description='EPOCH timestamp')
    end_time: str | None = Field(None, description='EPOCH timestamp')
    limit: int = Field(10, ge=1, le=100, description='Max number of transaction record per page. Default is 10 transactions per page')
    page: int = Field(1, ge=1, le=1000000, description='The page number to return. If unspecified, the first page is returned')
    customer_id: str | None = Field(None, description='Customer reference id (use this to return all the wallets for a customer)')

class FinmoGetWalletConfig(_Config):
    """Get Wallet by ID. Finmo acceptance is returned verbatim."""
    operation: Literal["get_wallet"] = Field("get_wallet", json_schema_extra={"ui:hidden": True})
    wallet_id: str = Field(..., min_length=1, max_length=200, description="Finmo resource ID")

class FinmoListWalletTransactionsConfig(_Config):
    """Get All Wallet Transaction. Returns one page; use page to continue."""
    operation: Literal["list_wallet_transactions"] = Field("list_wallet_transactions", json_schema_extra={"ui:hidden": True})
    customer_id: str | None = Field(None, description='Fetch all wallet transactions by Customer_id')
    wallet_id: str | None = Field(None, description='Fetch all wallet transactions by wallet_id. You can pass the wallet_id of Payin, Payout, Fee or Customer wallet')
    type: str | None = Field(None, description='Type of Wallet Transaction (Debit, Credit, Reserve, Release)')
    event_type: str | None = Field(None, description='Event Type (PAYIN, PAYOUT, REFUND, VIRTUAL_ACCOUNT)')
    tag: str | None = Field(None, description='Tag (FEES). This will fetch all fee transactions')
    created_at: str | None = Field(None, description='YYYY-MM-DD (UTC date). If you wish to search based on local time then use start_time and end_time fields')
    start_time: str | None = Field(None, description='EPOCH timestamp')
    end_time: str | None = Field(None, description='EPOCH timestamp')
    limit: int = Field(10, ge=1, le=100, description='Max number of transaction record per page. Default is 10 transactions per page')
    page: int = Field(1, ge=1, le=1000000, description='The page number to return. If unspecified, the first page is returned')

class FinmoGetWalletTransactionConfig(_Config):
    """Get Wallet Transaction by ID. Finmo acceptance is returned verbatim."""
    operation: Literal["get_wallet_transaction"] = Field("get_wallet_transaction", json_schema_extra={"ui:hidden": True})
    wallet_transaction_id: str = Field(..., min_length=1, max_length=200, description="Finmo resource ID")

class FinmoListTransactionsConfig(_Config):
    """Get All Transaction. Returns one page; use page to continue."""
    operation: Literal["list_transactions"] = Field("list_transactions", json_schema_extra={"ui:hidden": True})
    customer_id: str | None = Field(None, description='Fetch all wallet transactions by Customer_id')
    event_type: str | None = Field(None, description='Event Type (PAYIN, PAYOUT, REFUND, VA_PAYIN etc.)')
    is_settled: bool | None = Field(None, description='Settlement status (true or false)')
    is_reconciled: bool | None = Field(None, description='Finmo reconciliation status (true or false)')
    created_at: str | None = Field(None, description='UTC date. If you need to use local time then use start_time and end_time fields')
    start_time: str | None = Field(None, description='EPOCH Timestamp')
    end_time: str | None = Field(None, description='EPOCH Timestamp')
    limit: int = Field(10, ge=1, le=100, description='Max number of transaction record per page. Default is 10 transactions per page')
    page: int = Field(1, ge=1, le=1000000, description='The page number to return. If unspecified, the first page is returned')

class FinmoGetTransactionConfig(_Config):
    """Get Transaction by ID. Finmo acceptance is returned verbatim."""
    operation: Literal["get_transaction"] = Field("get_transaction", json_schema_extra={"ui:hidden": True})
    transaction_id: str = Field(..., min_length=1, max_length=200, description="Finmo resource ID")

FinmoConfig = Annotated[Union[
    FinmoCreatePayinConfig,
    FinmoListPayinsConfig,
    FinmoGetPayinConfig,
    FinmoCancelPayinConfig,
    FinmoCreateRefundConfig,
    FinmoListRefundsConfig,
    FinmoGetRefundConfig,
    FinmoCreatePayoutConfig,
    FinmoListPayoutsConfig,
    FinmoGetPayoutConfig,
    FinmoCreateCustomerConfig,
    FinmoListCustomersConfig,
    FinmoUpdateCustomerConfig,
    FinmoDisableCustomerConfig,
    FinmoEnableCustomerConfig,
    FinmoGetCustomerConfig,
    FinmoListWalletsConfig,
    FinmoGetWalletConfig,
    FinmoListWalletTransactionsConfig,
    FinmoGetWalletTransactionConfig,
    FinmoListTransactionsConfig,
    FinmoGetTransactionConfig,
], Field(discriminator="operation")]


class FinmoFullConfig(NodeConfig[FinmoConfig, FinmoAPIKeyCredential]):
    pass


ROUTES = {'create_payin': ('POST', '/payin', []), 'list_payins': ('GET', '/payin', ['status', 'created_at', 'customer_id', 'credit_wallet_id', 'payin_method_name', 'start_time', 'end_time', 'limit', 'page']), 'get_payin': ('GET', '/payin/{payin_id}', []), 'cancel_payin': ('PATCH', '/payin/cancel/{payin_id}', []), 'create_refund': ('POST', '/refund', []), 'list_refunds': ('GET', '/refund', ['status', 'payin_id', 'amount', 'created_at', 'start_time', 'end_time', 'limit', 'page']), 'get_refund': ('GET', '/refund/{refund_id}', []), 'create_payout': ('POST', '/payout', []), 'list_payouts': ('GET', '/payout', ['limit', 'page', 'status', 'payout_method_name', 'created_at', 'start_time', 'end_time']), 'get_payout': ('GET', '/payout/{payout_id}', []), 'create_customer': ('POST', '/customer', []), 'list_customers': ('GET', '/customer', ['type', 'created_at', 'include_deleted', 'start_time', 'end_time', 'limit', 'page']), 'update_customer': ('PATCH', '/customer/{customer_id}', []), 'disable_customer': ('PATCH', '/customer/{customer_id}/disable', []), 'enable_customer': ('PATCH', '/customer/{customer_id}/enable', []), 'get_customer': ('GET', '/customer/{customer_id}', ['include_deleted']), 'list_wallets': ('GET', '/wallet', ['category', 'created_at', 'start_time', 'end_time', 'limit', 'page', 'customer_id']), 'get_wallet': ('GET', '/wallet/{wallet_id}', []), 'list_wallet_transactions': ('GET', '/wallet-transaction', ['customer_id', 'wallet_id', 'type', 'event_type', 'tag', 'created_at', 'start_time', 'end_time', 'limit', 'page']), 'get_wallet_transaction': ('GET', '/wallet-transaction/{wallet_transaction_id}', []), 'list_transactions': ('GET', '/transaction', ['customer_id', 'event_type', 'is_settled', 'is_reconciled', 'created_at', 'start_time', 'end_time', 'limit', 'page']), 'get_transaction': ('GET', '/transaction/{transaction_id}', [])}


class FinmoNode(WorkflowNode):
    integration_type = "automation-finmo"
    connection_evidence = ConnectionEvidence(
        noun="wallets", operation="list_wallets", label_keys=("description", "wallet_id"),
    )

    @classmethod
    def get_config_model(cls):
        return FinmoFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Finmo API key")
        config = self.config.config
        credential = self.config.credentials
        method, template, query_fields = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        path = template
        for key in re.findall(r"\{([^{}]+)\}", template):
            path = path.replace("{" + key + "}", quote(values[key], safe=""))
        params = {k: str(values[k]).lower() if isinstance(values[k], bool) else values[k]
                  for k in query_fields if k in values}
        accept = "application/json" if config.operation in {
            "list_payins", "get_payin", "cancel_payin", "create_refund", "list_refunds", "get_refund",
        } else "application/json; charset=utf-8"
        kwargs = {"params": params, "headers": {"Accept": accept},
                  "auth": httpx.BasicAuth(credential.access_key, credential.secret_key)}
        if "body" in values:
            kwargs["json"] = values["body"]
        # No retries: a disconnected payment request may already have been accepted.
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, **kwargs)
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Finmo returned an unexpected non-JSON response") from None
        if response.status_code >= 300 or response.status_code < 200 or not isinstance(body, dict) or body.get("success") is not True:
            message = body.get("message") or body.get("error") or body.get("status_text") if isinstance(body, dict) else None
            text = message if isinstance(message, str) else "Finmo did not confirm the request"
            for secret in (credential.access_key, credential.secret_key):
                text = text.replace(secret, "[redacted]")
            result = {"status": "error", "success": False, "message": text, "http_status": response.status_code}
        else:
            if "data" not in body or not isinstance(body["data"], (dict, list)):
                raise ValueError("Finmo returned an unexpected data envelope")
            result = {"status": "success", "success": True, "data": body["data"],
                      "request_id": body.get("request_id"), "http_status": response.status_code}
            if config.operation.startswith("list_"):
                # The collection does not define a consistent pagination envelope.
                # Do not claim completeness or guess a next page from response size.
                result.update(page=config.page, limit=config.limit, complete=False)
        await self.emit(result)
        return result
