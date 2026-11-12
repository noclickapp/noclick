"""Kiwify public API v1: explicit operations from the provider's contract.

Uses a manually supplied bearer token and account ID. Tokens are obtained with
client credentials outside NoClick and must be replaced when they expire.
Official reference: https://docs.kiwify.com.br/api-reference/general
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.kiwify_operations import KIWIFY_OPERATIONS
from nodes.scopes.kiwify import KIWIFY_SCOPES
from utils.ssrf import guarded_async_client

BASE_URL = "https://public-api.kiwify.com/v1"


class KiwifyTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Kiwify Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.kiwify.com.br/api-reference/general",
            "x-oauth-scopes": KIWIFY_SCOPES.declared_scopes(),
            "x-credential-instructions": "In Kiwify, open Apps > API and create an API key with stats permission for the connection check and the permissions needed by your operations. Copy the account ID. Use the documented /oauth/token client-credentials request to obtain an access token, then paste that token here without the Bearer prefix. Replace it when it expires; NoClick does not renew it.",
        },
    )
    credential_type: Literal["kiwify_access_token"] = Field("kiwify_access_token", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, title="Access token", json_schema_extra={"ui:widget": "password"})
    account_id: str = Field(..., min_length=1, title="Account ID", description="Copy from Apps > API beside your API key.")

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if any(c.isspace() for c in value) or not value.isascii():
            raise ValueError("Paste the access token without a header or whitespace")
        return value

    @field_validator("account_id", mode="before")
    @classmethod
    def account(cls, value):
        if not isinstance(value, str):
            raise ValueError("Copy the Kiwify account ID")
        value = value.strip()
        if not value or len(value) > 200 or not all(c.isascii() and (c.isalnum() or c in "_-") for c in value):
            raise ValueError("Copy the Kiwify account ID, not a URL")
        return value


class KiwifyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def date_ranges(self):
        for start, end, paired in (("start_date", "end_date", False), ("created_start", "created_end", True)):
            a, b = getattr(self, start, None), getattr(self, end, None)
            if paired and bool(a) != bool(b):
                raise ValueError("Provide both created_start and created_end")
            if a is not None and b is not None:
                span = (date.fromisoformat(b) - date.fromisoformat(a)).days
                if span < 0:
                    raise ValueError("End date must not precede start date")
                if (self.operation == "list_sales" or paired) and span > 90:
                    raise ValueError("This date range must be no more than 90 days")
        return self


class KiwifyGetAccountDetailsConfig(KiwifyInput):
    """Get account details. Requires stats permission."""
    operation: Literal['get_account_details'] = Field('get_account_details', title='Get account details', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get account details', "x-category": 'Account'})


class KiwifyListProductsConfig(KiwifyInput):
    """List products. Requires products permission."""
    operation: Literal['list_products'] = Field('list_products', title='List products', json_schema_extra={"ui:hidden": True, "x-display-name": 'List products', "x-category": 'Products'})
    page_size: int = Field(10, ge=1, le=100)
    page_number: int = Field(1, ge=1, le=1000000)


class KiwifyGetProductConfig(KiwifyInput):
    """Get product. Requires products permission."""
    operation: Literal['get_product'] = Field('get_product', title='Get product', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get product', "x-category": 'Products'})
    product_id: str = Field(..., min_length=1)


class KiwifyListSalesConfig(KiwifyInput):
    """List sales. Requires sales permission."""
    operation: Literal['list_sales'] = Field('list_sales', title='List sales', json_schema_extra={"ui:hidden": True, "x-display-name": 'List sales', "x-category": 'Sales'})
    status: Literal['approved', 'authorized', 'chargedback', 'paid', 'pending', 'pending_refund', 'processing', 'refunded', 'refund_requested', 'refused', 'waiting_payment'] | None = Field(None)
    view_full_sale_details: bool | None = Field(None)
    payment_method: Literal['boleto', 'credit_card', 'pix'] | None = Field(None)
    product_id: str | None = Field(None)
    affiliate_id: str | None = Field(None)
    page_size: int = Field(10, ge=1, le=100)
    page_number: int = Field(1, ge=1, le=1000000)
    start_date: str = Field(..., description='YYYY-MM-DD', min_length=1)
    end_date: str = Field(..., description='YYYY-MM-DD', min_length=1)
    updated_at_start_date: str | None = Field(None, description='YYYY-MM-DD')
    updated_at_end_date: str | None = Field(None, description='YYYY-MM-DD')


class KiwifyGetSaleConfig(KiwifyInput):
    """Get sale. Requires sales permission."""
    operation: Literal['get_sale'] = Field('get_sale', title='Get sale', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get sale', "x-category": 'Sales'})
    sale_id: str = Field(..., min_length=1)


class KiwifyRefundSaleConfig(KiwifyInput):
    """Refund sale. Requires sales_refund permission."""
    operation: Literal['refund_sale'] = Field('refund_sale', title='Refund sale', json_schema_extra={"ui:hidden": True, "x-display-name": 'Refund sale', "x-category": 'Sales'})
    sale_id: str = Field(..., min_length=1)
    pixKey: str | None = Field(None)


class KiwifyGetSalesStatsConfig(KiwifyInput):
    """Get sales stats. Requires stats permission."""
    operation: Literal['get_sales_stats'] = Field('get_sales_stats', title='Get sales stats', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get sales stats', "x-category": 'Sales'})
    product_id: str | None = Field(None)
    start_date: str | None = Field(None, description='YYYY-MM-DD')
    end_date: str | None = Field(None, description='YYYY-MM-DD')


class KiwifyGetBalanceConfig(KiwifyInput):
    """Get balance. Requires financial permission."""
    operation: Literal['get_balance'] = Field('get_balance', title='Get balance', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get balance', "x-category": 'Finance'})


class KiwifyGetLegalEntityBalanceConfig(KiwifyInput):
    """Get legal entity balance. Requires financial permission."""
    operation: Literal['get_legal_entity_balance'] = Field('get_legal_entity_balance', title='Get legal entity balance', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get legal entity balance', "x-category": 'Finance'})
    legal_entity_id: str = Field(..., min_length=1)


class KiwifyListPayoutsConfig(KiwifyInput):
    """List payouts. Requires financial permission."""
    operation: Literal['list_payouts'] = Field('list_payouts', title='List payouts', json_schema_extra={"ui:hidden": True, "x-display-name": 'List payouts', "x-category": 'Finance'})
    legal_entity_id: str | None = Field(None)
    page_size: int = Field(10, ge=1, le=100)
    page_number: int = Field(1, ge=1, le=1000000)


class KiwifyGetPayoutConfig(KiwifyInput):
    """Get payout. Requires financial permission."""
    operation: Literal['get_payout'] = Field('get_payout', title='Get payout', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get payout', "x-category": 'Finance'})
    payout_id: str = Field(..., min_length=1)


class KiwifyListAffiliatesConfig(KiwifyInput):
    """List affiliates. Requires affiliates permission."""
    operation: Literal['list_affiliates'] = Field('list_affiliates', title='List affiliates', json_schema_extra={"ui:hidden": True, "x-display-name": 'List affiliates', "x-category": 'Affiliates'})
    page_size: int = Field(10, ge=1, le=100)
    page_number: int = Field(1, ge=1, le=1000000)
    status: str | None = Field(None)
    product_id: str | None = Field(None)
    search: str | None = Field(None)


class KiwifyGetAffiliateConfig(KiwifyInput):
    """Get affiliate. Requires affiliates permission."""
    operation: Literal['get_affiliate'] = Field('get_affiliate', title='Get affiliate', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get affiliate', "x-category": 'Affiliates'})
    affiliate_id: str = Field(..., min_length=1)


class KiwifyUpdateAffiliateConfig(KiwifyInput):
    """Update affiliate. Requires affiliates permission."""
    operation: Literal['update_affiliate'] = Field('update_affiliate', title='Update affiliate', json_schema_extra={"ui:hidden": True, "x-display-name": 'Update affiliate', "x-category": 'Affiliates'})
    affiliate_id: str = Field(..., min_length=1)
    commission: float | None = Field(None, ge=0)
    status: Literal['active', 'blocked', 'refused'] | None = Field(None)


class KiwifyListWebhooksConfig(KiwifyInput):
    """List webhooks. Requires webhooks permission."""
    operation: Literal['list_webhooks'] = Field('list_webhooks', title='List webhooks', json_schema_extra={"ui:hidden": True, "x-display-name": 'List webhooks', "x-category": 'Webhooks'})
    page_size: int = Field(10, ge=1, le=100)
    page_number: int = Field(1, ge=1, le=1000000)
    product_id: str | None = Field(None)
    search: str | None = Field(None)


class KiwifyCreateWebhookConfig(KiwifyInput):
    """Create webhook. Requires webhooks permission."""
    operation: Literal['create_webhook'] = Field('create_webhook', title='Create webhook', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create webhook', "x-category": 'Webhooks'})
    name: str = Field(...)
    url: str = Field(..., description="Webhook destination URL; sent to Kiwify, never fetched by NoClick.")
    products: str = Field(...)
    triggers: list[Literal['boleto_gerado', 'pix_gerado', 'carrinho_abandonado', 'compra_recusada', 'compra_aprovada', 'compra_reembolsada', 'chargeback', 'subscription_canceled', 'subscription_late', 'subscription_renewed']] = Field(...)
    webhook_token: str | None = Field(None, json_schema_extra={"ui:widget": "password"})


class KiwifyGetWebhookConfig(KiwifyInput):
    """Get webhook. Requires webhooks permission."""
    operation: Literal['get_webhook'] = Field('get_webhook', title='Get webhook', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get webhook', "x-category": 'Webhooks'})
    webhook_id: str = Field(..., min_length=1)


class KiwifyUpdateWebhookConfig(KiwifyInput):
    """Update webhook. Requires webhooks permission."""
    operation: Literal['update_webhook'] = Field('update_webhook', title='Update webhook', json_schema_extra={"ui:hidden": True, "x-display-name": 'Update webhook', "x-category": 'Webhooks'})
    webhook_id: str = Field(..., min_length=1)
    name: str | None = Field(None)
    url: str | None = Field(None, description="Webhook destination URL; sent to Kiwify, never fetched by NoClick.")
    products: str | None = Field(None)
    triggers: list[Literal['boleto_gerado', 'pix_gerado', 'carrinho_abandonado', 'compra_recusada', 'compra_aprovada', 'compra_reembolsada', 'chargeback', 'subscription_canceled', 'subscription_late', 'subscription_renewed']] | None = Field(None)
    webhook_token: str | None = Field(None, json_schema_extra={"ui:widget": "password"})


class KiwifyDeleteWebhookConfig(KiwifyInput):
    """Delete webhook. Requires webhooks permission."""
    operation: Literal['delete_webhook'] = Field('delete_webhook', title='Delete webhook', json_schema_extra={"ui:hidden": True, "x-display-name": 'Delete webhook', "x-category": 'Webhooks'})
    webhook_id: str = Field(..., min_length=1)


class KiwifyListEventParticipantsConfig(KiwifyInput):
    """List event participants. Requires events permission."""
    operation: Literal['list_event_participants'] = Field('list_event_participants', title='List event participants', json_schema_extra={"ui:hidden": True, "x-display-name": 'List event participants', "x-category": 'Events'})
    product_id: str = Field(..., min_length=1)
    checked_in: bool | None = Field(None)
    page_size: int = Field(10, ge=1, le=100)
    page_number: int = Field(1, ge=1, le=1000000)
    created_at_start_date: str | None = Field(None, description='YYYY-MM-DD')
    created_at_end_date: str | None = Field(None, description='YYYY-MM-DD')
    updated_at_start_date: str | None = Field(None, description='YYYY-MM-DD')
    updated_at_end_date: str | None = Field(None, description='YYYY-MM-DD')
    external_id: str | None = Field(None)
    batch_id: str | None = Field(None)
    phone: str | None = Field(None)
    cpf: str | None = Field(None)
    order_id: str | None = Field(None)


class KiwifyListScheduledInstallmentsConfig(KiwifyInput):
    """List scheduled installments. Requires scheduled_installments permission."""
    operation: Literal['list_scheduled_installments'] = Field('list_scheduled_installments', title='List scheduled installments', json_schema_extra={"ui:hidden": True, "x-display-name": 'List scheduled installments', "x-category": 'Installments'})
    page_size: int = Field(10, ge=1, le=100, description='Quantidade de itens por página (máximo 100).')
    page_number: int = Field(1, ge=1, le=1000000, description='Número da página.')
    created_start: str | None = Field(None, description='Data inicial (YYYY-MM-DD), fuso America/Sao_Paulo. Exige created_end.')
    created_end: str | None = Field(None, description='Data final (YYYY-MM-DD), fuso America/Sao_Paulo. Exige created_start.')
    product_id: str | None = Field(None, description='Filtra por produto.')
    offer_id: str | None = Field(None, description='Filtra por oferta.')
    payment_method: list[Literal['pix', 'boleto', 'credit_card']] | None = Field(None, description='Filtra por método de pagamento.')
    status: list[Literal['active', 'overdue', 'settled', 'paused', 'cancelled']] | None = Field(None, description='Filtra por status do plano.')
    customer: str | None = Field(None, description='Filtra por nome ou e-mail do cliente.')


class KiwifyGetScheduledInstallmentConfig(KiwifyInput):
    """Get scheduled installment. Requires scheduled_installments permission."""
    operation: Literal['get_scheduled_installment'] = Field('get_scheduled_installment', title='Get scheduled installment', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get scheduled installment', "x-category": 'Installments'})
    scheduled_installment_id: str = Field(..., min_length=1)


# Kiwify's own MCP server: agents get its tools through a person's Kiwify sign-in.
KiwifyMcpCredential = mcp_credential("kiwify", "https://mcp.kiwify.com/mcp", app="Kiwify")
KiwifyCredential = Union[KiwifyTokenCredential, KiwifyMcpCredential]


KiwifyConfig = Annotated[Union[
    KiwifyGetAccountDetailsConfig,
    KiwifyListProductsConfig,
    KiwifyGetProductConfig,
    KiwifyListSalesConfig,
    KiwifyGetSaleConfig,
    KiwifyRefundSaleConfig,
    KiwifyGetSalesStatsConfig,
    KiwifyGetBalanceConfig,
    KiwifyGetLegalEntityBalanceConfig,
    KiwifyListPayoutsConfig,
    KiwifyGetPayoutConfig,
    KiwifyListAffiliatesConfig,
    KiwifyGetAffiliateConfig,
    KiwifyUpdateAffiliateConfig,
    KiwifyListWebhooksConfig,
    KiwifyCreateWebhookConfig,
    KiwifyGetWebhookConfig,
    KiwifyUpdateWebhookConfig,
    KiwifyDeleteWebhookConfig,
    KiwifyListEventParticipantsConfig,
    KiwifyListScheduledInstallmentsConfig,
    KiwifyGetScheduledInstallmentConfig
], Field(discriminator="operation")]


class KiwifyNodeConfig(NodeConfig[KiwifyConfig, KiwifyCredential]):
    """Kiwify operation and pasted account credential."""


def _redact(value, secrets):
    if isinstance(value, dict):
        return {k: _redact(v, secrets) for k, v in value.items() if k.lower() not in {"token", "access_token", "client_secret", "authorization"}}
    if isinstance(value, list):
        return [_redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
    return value


class KiwifyNode(WorkflowNode):
    integration_type = "automation-kiwify"
    credential_provider_labels = {"kiwify": "Kiwify Account"}
    scope_registry = KIWIFY_SCOPES
    connection_evidence = ConnectionEvidence(
        noun="Kiwify account", identity_operation="get_account_details",
        identity_keys=("company_name", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return KiwifyNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Kiwify access token and account ID")
        config, credential = self.config.config, self.config.credentials
        spec = KIWIFY_OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = spec["path"]
        for parameter, field in spec["path_fields"].items():
            value = values[field]
            if value in {".", ".."} or any(c in value for c in "/?#\\") or any(ord(c) < 32 for c in value):
                raise ValueError("Use a single Kiwify resource ID")
            path = path.replace("{" + parameter + "}", quote(value, safe=""))
        params = {key: (str(values[key]).lower() if isinstance(values[key], bool) else values[key])
                  for key in spec["query_fields"] if key in values}
        body = {target: values[field] for field, target in spec["body_fields"].items() if field in values}
        if config.operation == "update_affiliate" and not body:
            raise ValueError("Provide commission or status to update")
        headers = {"Authorization": "Bearer " + credential.access_token,
                   "x-kiwify-account-id": credential.account_id, "Accept": "application/json"}
        secrets = [credential.access_token, getattr(config, "webhook_token", None)]
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(spec["method"], BASE_URL + path, headers=headers,
                                                params=params, **({"json": body} if spec["body_fields"] else {}))
        except httpx.RequestError:
            # A mutation may have reached Kiwify. Do not automatically retry it.
            raise ValueError("Kiwify request did not return a response; inspect the account before retrying a write") from None
        if not 200 <= response.status_code < 300:
            try:
                error = response.json()
                message = error.get("message") or error.get("error") if isinstance(error, dict) else None
            except ValueError:
                message = None
            output = {"status": "error", "http_status": response.status_code,
                      "message": _redact(str(message or "Kiwify rejected the request"), secrets)}
        elif response.status_code == 204:
            output = {"status": "success", "http_status": 204, "deleted_id": values.get("webhook_id")}
        else:
            if len(response.content) > 10_000_000:
                raise ValueError("Kiwify response is too large")
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Kiwify returned an invalid JSON response") from None
            if not isinstance(data, dict) or data.get("error"):
                raise ValueError("Kiwify returned an unexpected response")
            # Preserve provider envelopes, including participant data.participants,
            # pagination and installment detail structures. One call is one page.
            output = {"status": "success", "data": _redact(data, secrets), "http_status": response.status_code}
        await self.emit(output)
        return output
