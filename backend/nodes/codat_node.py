"""Codat Assess reports, using the provider's published Assess OpenAPI 1.0.

Webhook registration and read.completed payloads: Codat Platform API; signature:
https://docs.codat.io/using-the-api/webhooks/create-consumer
"""
import base64
import hashlib
import hmac
import json
import time
from typing import Annotated, Literal, Optional, Union
from uuid import UUID
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase

class CodatAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Assess API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.codat.io/developers/api-keys",
        "x-credential-instructions": "Paste your raw Codat API key (not the encoded Authorization header) and a company ID to verify report access."})
    credential_type: Literal["codat_api_key"] = Field("codat_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", json_schema_extra={"ui:widget": "password"})
    company_id: UUID = Field(..., title="Company ID", description="An existing company in your Codat account, used for the connection check.")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the raw API key without a header")
        return value

class CodatCheckConnectionConfig(BaseModel):
    operation: Literal["check_connection"] = Field("check_connection", title="Check report access")

class CodatGetDataIntegrityStatusConfig(BaseModel):
    operation: Literal["get_data_integrity_status"] = Field("get_data_integrity_status", title='Get data integrity status', json_schema_extra={"x-method-kind": 'read'})
    companyId: UUID = Field(..., title='companyId')
    dataType: Literal['banking-accounts', 'banking-transactions', 'bankAccounts', 'accountTransactions'] = Field(..., title='dataType')

class CodatGetDataIntegritySummariesConfig(BaseModel):
    operation: Literal["get_data_integrity_summaries"] = Field("get_data_integrity_summaries", title='Get data integrity summary', json_schema_extra={"x-method-kind": 'read'})
    companyId: UUID = Field(..., title='companyId')
    dataType: Literal['banking-accounts', 'banking-transactions', 'bankAccounts', 'accountTransactions'] = Field(..., title='dataType')
    query: Optional[str] = Field(None, title='query')

class CodatListDataTypeDataIntegrityDetailsConfig(BaseModel):
    operation: Literal["list_data_type_data_integrity_details"] = Field("list_data_type_data_integrity_details", title='List data type data integrity', json_schema_extra={"x-method-kind": 'read'})
    companyId: UUID = Field(..., title='companyId')
    dataType: Literal['banking-accounts', 'banking-transactions', 'bankAccounts', 'accountTransactions'] = Field(..., title='dataType')
    page: int = Field(1, title='page', ge=1)
    pageSize: int = Field(100, title='pageSize', ge=1, le=5000)
    query: Optional[str] = Field(None, title='query')
    orderBy: Optional[str] = Field(None, title='orderBy')

class CodatGetAccountsForEnhancedProfitAndLossConfig(BaseModel):
    operation: Literal["get_accounts_for_enhanced_profit_and_loss"] = Field("get_accounts_for_enhanced_profit_and_loss", title='Get enhanced profit and loss accounts', json_schema_extra={"x-method-kind": 'read'})
    companyId: UUID = Field(..., title='companyId')
    reportDate: str = Field(..., title='reportDate')
    numberOfPeriods: Optional[int] = Field(None, title='numberOfPeriods')

class CodatGetAccountsForEnhancedBalanceSheetConfig(BaseModel):
    operation: Literal["get_accounts_for_enhanced_balance_sheet"] = Field("get_accounts_for_enhanced_balance_sheet", title='Get enhanced balance sheet accounts', json_schema_extra={"x-method-kind": 'read'})
    companyId: UUID = Field(..., title='companyId')
    reportDate: str = Field(..., title='reportDate')
    numberOfPeriods: Optional[int] = Field(None, title='numberOfPeriods')

class CodatGetEnhancedInvoicesReportConfig(BaseModel):
    operation: Literal["get_enhanced_invoices_report"] = Field("get_enhanced_invoices_report", title='Get enhanced invoices report', json_schema_extra={"x-method-kind": 'read'})
    companyId: UUID = Field(..., title='companyId')
    page: int = Field(1, title='page', ge=1)
    pageSize: int = Field(100, title='pageSize', ge=1, le=5000)
    query: Optional[str] = Field(None, title='query')

class CodatGetCommerceRevenueMetricsConfig(BaseModel):
    operation: Literal["get_commerce_revenue_metrics"] = Field("get_commerce_revenue_metrics", title='Get commerce revenue metrics', json_schema_extra={"x-method-kind": 'read'})
    companyId: UUID = Field(..., title='companyId')
    connectionId: UUID = Field(..., title='connectionId')
    reportDate: str = Field(..., title='reportDate')
    periodLength: int = Field(..., title='periodLength')
    numberOfPeriods: int = Field(..., title='numberOfPeriods')
    periodUnit: Literal['Day', 'Week', 'Month', 'Year'] = Field(..., title='periodUnit')
    includeDisplayNames: Optional[bool] = Field(None, title='includeDisplayNames')

class CodatGetCommerceOrdersMetricsConfig(BaseModel):
    operation: Literal["get_commerce_orders_metrics"] = Field("get_commerce_orders_metrics", title='Get orders report', json_schema_extra={"x-method-kind": 'read'})
    companyId: UUID = Field(..., title='companyId')
    connectionId: UUID = Field(..., title='connectionId')
    reportDate: str = Field(..., title='reportDate')
    periodLength: int = Field(..., title='periodLength')
    numberOfPeriods: int = Field(..., title='numberOfPeriods')
    periodUnit: Literal['Day', 'Week', 'Month', 'Year'] = Field(..., title='periodUnit')
    includeDisplayNames: Optional[bool] = Field(None, title='includeDisplayNames')

class CodatGetCommerceRefundsMetricsConfig(BaseModel):
    operation: Literal["get_commerce_refunds_metrics"] = Field("get_commerce_refunds_metrics", title='Get refunds report', json_schema_extra={"x-method-kind": 'read'})
    companyId: UUID = Field(..., title='companyId')
    connectionId: UUID = Field(..., title='connectionId')
    reportDate: str = Field(..., title='reportDate')
    periodLength: int = Field(..., title='periodLength')
    numberOfPeriods: int = Field(..., title='numberOfPeriods')
    periodUnit: Literal['Day', 'Week', 'Month', 'Year'] = Field(..., title='periodUnit')
    includeDisplayNames: Optional[bool] = Field(None, title='includeDisplayNames')

class CodatGetCommerceCustomerRetentionMetricsConfig(BaseModel):
    operation: Literal["get_commerce_customer_retention_metrics"] = Field("get_commerce_customer_retention_metrics", title='Get customer retention metrics', json_schema_extra={"x-method-kind": 'read'})
    companyId: UUID = Field(..., title='companyId')
    connectionId: UUID = Field(..., title='connectionId')
    reportDate: str = Field(..., title='reportDate')
    periodLength: int = Field(..., title='periodLength')
    numberOfPeriods: int = Field(..., title='numberOfPeriods')
    periodUnit: Literal['Day', 'Week', 'Month', 'Year'] = Field(..., title='periodUnit')
    includeDisplayNames: Optional[bool] = Field(None, title='includeDisplayNames')

class CodatGetCommerceLifetimeValueMetricsConfig(BaseModel):
    operation: Literal["get_commerce_lifetime_value_metrics"] = Field("get_commerce_lifetime_value_metrics", title='Get lifetime value metric', json_schema_extra={"x-method-kind": 'read'})
    companyId: UUID = Field(..., title='companyId')
    connectionId: UUID = Field(..., title='connectionId')
    reportDate: str = Field(..., title='reportDate')
    periodLength: int = Field(..., title='periodLength')
    numberOfPeriods: int = Field(..., title='numberOfPeriods')
    periodUnit: Literal['Day', 'Week', 'Month', 'Year'] = Field(..., title='periodUnit')
    includeDisplayNames: Optional[bool] = Field(None, title='includeDisplayNames')

class CodatGetAccountingMarketingMetricsConfig(BaseModel):
    operation: Literal["get_accounting_marketing_metrics"] = Field("get_accounting_marketing_metrics", title='Get marketing metrics report', json_schema_extra={"x-method-kind": 'read'})
    companyId: UUID = Field(..., title='companyId')
    connectionId: UUID = Field(..., title='connectionId')
    reportDate: str = Field(..., title='reportDate')
    periodLength: int = Field(..., title='periodLength')
    numberOfPeriods: int = Field(..., title='numberOfPeriods')
    periodUnit: Literal['Day', 'Week', 'Month', 'Year'] = Field(..., title='periodUnit')
    includeDisplayNames: Optional[bool] = Field(None, title='includeDisplayNames')
    showInputValues: Optional[bool] = Field(None, title='showInputValues')

class CodatGenerateExcelReportConfig(BaseModel):
    operation: Literal["generate_excel_report"] = Field("generate_excel_report", title='Generate Excel report', json_schema_extra={"x-method-kind": 'write'})
    companyId: UUID = Field(..., title='companyId')
    reportType: Literal['assess', 'audit', 'enhancedFinancials', 'enhancedInvoices'] = Field(..., title='reportType')

class CodatGetExcelReportGenerationStatusConfig(BaseModel):
    operation: Literal["get_excel_report_generation_status"] = Field("get_excel_report_generation_status", title='Get Excel report status', json_schema_extra={"x-method-kind": 'read'})
    companyId: UUID = Field(..., title='companyId')
    reportType: Literal['assess', 'audit', 'enhancedFinancials', 'enhancedInvoices'] = Field(..., title='reportType')

class CodatGenerateLoanTransactionsConfig(BaseModel):
    operation: Literal["generate_loan_transactions"] = Field("generate_loan_transactions", title='Generate loan transactions report', json_schema_extra={"x-method-kind": 'write'})
    companyId: UUID = Field(..., title='companyId')
    sourceType: Literal['banking', 'commerce', 'accounting'] = Field(..., title='sourceType')

class CodatListLoanTransactionsConfig(BaseModel):
    operation: Literal["list_loan_transactions"] = Field("list_loan_transactions", title='List loan transactions', json_schema_extra={"x-method-kind": 'read'})
    companyId: UUID = Field(..., title='companyId')
    sourceType: Literal['banking', 'commerce', 'accounting'] = Field(..., title='sourceType')

class CodatGenerateLoanSummaryConfig(BaseModel):
    operation: Literal["generate_loan_summary"] = Field("generate_loan_summary", title='Generate loan summaries report', json_schema_extra={"x-method-kind": 'write'})
    companyId: UUID = Field(..., title='companyId')
    sourceType: Literal['banking', 'commerce', 'accounting'] = Field(..., title='sourceType')

class CodatGetLoanSummaryConfig(BaseModel):
    operation: Literal["get_loan_summary"] = Field("get_loan_summary", title='Get loan summaries', json_schema_extra={"x-method-kind": 'read'})
    companyId: UUID = Field(..., title='companyId')
    sourceType: Literal['banking', 'commerce', 'accounting'] = Field(..., title='sourceType')

class CodatOnReadCompletedConfig(WebhookTriggerConfigBase):
    operation: Literal["on_read_completed"] = Field("on_read_completed", title="On financial data read completed", json_schema_extra={"x-is-trigger": True, "x-category": "Triggers"})
    event_type: Literal["read.completed", "read.completed.initial"] = Field("read.completed", title="Event type")
    webhook_url: Optional[str] = Field(None, title="Webhook URL", json_schema_extra={"ui:widget": "webhook", "ui:loadValue": True, "ui:copyable": True})
    signing_secret: Optional[str] = Field(None, title="Webhook signing secret", description="After registering, open this endpoint in Codat Portal > Webhooks > Configure consumer and copy its signing secret here. The API does not return it. Deliveries are refused until supplied.", json_schema_extra={"ui:widget": "password"})


OPERATIONS = {'get_data_integrity_status': {'method': 'GET',
                               'path': '/data/companies/{companyId}/assess/dataTypes/{dataType}/dataIntegrity/status',
                               'query': []},
 'get_data_integrity_summaries': {'method': 'GET',
                                  'path': '/data/companies/{companyId}/assess/dataTypes/{dataType}/dataIntegrity/summaries',
                                  'query': ['query']},
 'list_data_type_data_integrity_details': {'method': 'GET',
                                           'path': '/data/companies/{companyId}/assess/dataTypes/{dataType}/dataIntegrity/details',
                                           'query': ['page',
                                                     'pageSize',
                                                     'query',
                                                     'orderBy']},
 'get_accounts_for_enhanced_profit_and_loss': {'method': 'GET',
                                               'path': '/companies/{companyId}/reports/enhancedProfitAndLoss/accounts',
                                               'query': ['reportDate',
                                                         'numberOfPeriods']},
 'get_accounts_for_enhanced_balance_sheet': {'method': 'GET',
                                             'path': '/companies/{companyId}/reports/enhancedBalanceSheet/accounts',
                                             'query': ['reportDate',
                                                       'numberOfPeriods']},
 'get_enhanced_invoices_report': {'method': 'GET',
                                  'path': '/companies/{companyId}/reports/enhancedInvoices',
                                  'query': ['page', 'pageSize', 'query']},
 'get_commerce_revenue_metrics': {'method': 'GET',
                                  'path': '/data/companies/{companyId}/connections/{connectionId}/assess/commerceMetrics/revenue',
                                  'query': ['reportDate',
                                            'periodLength',
                                            'numberOfPeriods',
                                            'periodUnit',
                                            'includeDisplayNames']},
 'get_commerce_orders_metrics': {'method': 'GET',
                                 'path': '/data/companies/{companyId}/connections/{connectionId}/assess/commerceMetrics/orders',
                                 'query': ['reportDate',
                                           'periodLength',
                                           'numberOfPeriods',
                                           'periodUnit',
                                           'includeDisplayNames']},
 'get_commerce_refunds_metrics': {'method': 'GET',
                                  'path': '/data/companies/{companyId}/connections/{connectionId}/assess/commerceMetrics/refunds',
                                  'query': ['reportDate',
                                            'periodLength',
                                            'numberOfPeriods',
                                            'periodUnit',
                                            'includeDisplayNames']},
 'get_commerce_customer_retention_metrics': {'method': 'GET',
                                             'path': '/data/companies/{companyId}/connections/{connectionId}/assess/commerceMetrics/customerRetention',
                                             'query': ['reportDate',
                                                       'periodLength',
                                                       'numberOfPeriods',
                                                       'periodUnit',
                                                       'includeDisplayNames']},
 'get_commerce_lifetime_value_metrics': {'method': 'GET',
                                         'path': '/data/companies/{companyId}/connections/{connectionId}/assess/commerceMetrics/lifetimeValue',
                                         'query': ['reportDate',
                                                   'periodLength',
                                                   'numberOfPeriods',
                                                   'periodUnit',
                                                   'includeDisplayNames']},
 'get_accounting_marketing_metrics': {'method': 'GET',
                                      'path': '/data/companies/{companyId}/connections/{connectionId}/assess/accountingMetrics/marketing',
                                      'query': ['reportDate',
                                                'periodLength',
                                                'numberOfPeriods',
                                                'periodUnit',
                                                'includeDisplayNames',
                                                'showInputValues']},
 'generate_excel_report': {'method': 'POST',
                           'path': '/data/companies/{companyId}/assess/excel',
                           'query': ['reportType']},
 'get_excel_report_generation_status': {'method': 'GET',
                                        'path': '/data/companies/{companyId}/assess/excel',
                                        'query': ['reportType']},
 'generate_loan_transactions': {'method': 'POST',
                                'path': '/companies/{companyId}/reports/liabilities/loans/transactions',
                                'query': ['sourceType']},
 'list_loan_transactions': {'method': 'GET',
                            'path': '/companies/{companyId}/reports/liabilities/loans/transactions',
                            'query': ['sourceType']},
 'generate_loan_summary': {'method': 'POST',
                           'path': '/companies/{companyId}/reports/liabilities/loans',
                           'query': ['sourceType']},
 'get_loan_summary': {'method': 'GET',
                      'path': '/companies/{companyId}/reports/liabilities/loans',
                      'query': ['sourceType']}}

CodatOperation = Annotated[Union[CodatGetDataIntegrityStatusConfig, CodatGetDataIntegritySummariesConfig, CodatListDataTypeDataIntegrityDetailsConfig, CodatGetAccountsForEnhancedProfitAndLossConfig, CodatGetAccountsForEnhancedBalanceSheetConfig, CodatGetEnhancedInvoicesReportConfig, CodatGetCommerceRevenueMetricsConfig, CodatGetCommerceOrdersMetricsConfig, CodatGetCommerceRefundsMetricsConfig, CodatGetCommerceCustomerRetentionMetricsConfig, CodatGetCommerceLifetimeValueMetricsConfig, CodatGetAccountingMarketingMetricsConfig, CodatGenerateExcelReportConfig, CodatGetExcelReportGenerationStatusConfig, CodatGenerateLoanTransactionsConfig, CodatListLoanTransactionsConfig, CodatGenerateLoanSummaryConfig, CodatGetLoanSummaryConfig, CodatCheckConnectionConfig, CodatOnReadCompletedConfig], Field(discriminator="operation")]

class CodatNodeConfig(NodeConfig[CodatOperation, CodatAPIKeyCredential]):
    pass

class CodatNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-codat"
    connection_evidence = ConnectionEvidence(operation="check_connection", noun="company report access", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return CodatNodeConfig

    @staticmethod
    async def _request(api_key, method, path, *, params=None, body=None):
        auth = "Basic " + base64.b64encode(api_key.encode()).decode()
        async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
            response = await client.request(method, "https://api.codat.io" + path, params=params, json=body,
                headers={"Authorization": auth, "Accept": "application/json"})
        if response.status_code >= 300:
            # Preserve provider rejection text for the connect verdict; never include request headers.
            detail = response.text[:1000].replace(api_key, "[redacted]").replace(auth, "[redacted]")
            raise ValueError(f"Assess API {response.status_code}: {detail}")
        return response.json() if response.content else {"accepted": True}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        key = CodatAPIKeyCredential.model_validate(credential).api_key
        event = CodatOnReadCompletedConfig.model_validate(config or {}).event_type
        result = await cls._request(key, "POST", "/webhooks", body={"url": webhook_url, "eventTypes": [event], "disabled": False})
        if not isinstance(result, dict) or not result.get("id"):
            raise ValueError("Codat did not return a webhook consumer ID")
        return {"external_webhook_id": str(UUID(result["id"]))}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        identifier = (config or {}).get("external_webhook_id")
        if identifier and credential:
            key = CodatAPIKeyCredential.model_validate(credential).api_key
            await cls._request(key, "DELETE", "/webhooks/" + str(UUID(str(identifier))))

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": (config or {}).get("event_type", "read.completed")}

    @classmethod
    def verify_webhook_signature(cls, body, headers, config):
        headers = {k.lower(): v for k, v in headers.items()}
        secret = (config or {}).get("signing_secret")
        timestamp = headers.get("webhook-timestamp", "")
        identifier = headers.get("webhook-id", "")
        if not secret or not identifier or len(timestamp) > 12 or not timestamp.isdigit() or abs(time.time() - int(timestamp)) > 300:
            return False
        try:
            key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
            if not key: return False
        except (ValueError, TypeError):
            return False
        message = identifier.encode() + b"." + timestamp.encode() + b"." + body
        expected = base64.b64encode(hmac.new(key, message, hashlib.sha256).digest()).decode()
        return any(hmac.compare_digest(part[3:], expected) for part in headers.get("webhook-signature", "").split() if part.startswith("v1,"))

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        return "eventType" in payload and payload["eventType"] == (config or {}).get("event_type", "read.completed")

    @classmethod
    def resolve_trigger_payload(cls, payload, config):
        if payload.get("eventType") != (config or {}).get("event_type", "read.completed"):
            return cls.no_event_output("on_read_completed", "Different event type")
        return payload

    @classmethod
    def resolve_agent_event(cls, output):
        event = output if isinstance(output, dict) else {}
        if event.get("eventType") not in {"read.completed", "read.completed.initial"}: return None
        payload = event.get("payload") or {}
        company = payload.get("referenceCompany") or {}
        types = payload.get("dataTypes") or []
        details = "; ".join(f"{row.get('dataType')}: {row.get('status')} (connection {row.get('connectionId')})" for row in types if isinstance(row, dict))
        return {"text": f"Codat financial data read completed for {company.get('name')} (company {company.get('id')}). {details}. Portal: {(company.get('links') or {}).get('portal')}. Event {event.get('id')}", "conversation_key": company.get("id")}

    async def execute(self, inputs):
        if not isinstance(self.config, CodatNodeConfig) or not self.config.credentials:
            raise ValueError("Connect an Assess API key")
        op = self.config.config
        key = self.config.credentials.api_key
        if isinstance(op, CodatOnReadCompletedConfig):
            event = inputs.get("body", inputs)
            if isinstance(event, str): event = json.loads(event)
            if not isinstance(event, dict) or event.get("eventType") != op.event_type:
                return {"status": "success", "data": {}, "ignored": True}
            return {"status": "success", "operation": op.operation, "data": event}
        if isinstance(op, CodatCheckConnectionConfig):
            path = f"/data/companies/{self.config.credentials.company_id}/assess/excel"
            data = await self._request(key, "GET", path, params={"reportType": "assess"})
        else:
            spec = OPERATIONS[op.operation]
            values = op.model_dump(mode="json", exclude_none=True, exclude={"operation"})
            path = spec["path"]
            for name, value in values.items():
                path = path.replace("{" + name + "}", quote(str(value), safe=""))
            params = {name: values[name] for name in spec["query"] if name in values}
            data = await self._request(key, spec["method"], path, params=params)
        return {"status": "success", "operation": op.operation, "data": data}
