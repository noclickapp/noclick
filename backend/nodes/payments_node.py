"""GOV.UK Pay public API v1: service-key payments, refunds and agreements.

Contract: govuk-pay/pay-publicapi openapi/publicapi_spec.json, version 1.0.3.
Webhook creation is admin-tool-only; new payments use the scheduled poll family.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE_URL = "https://publicapi.payments.service.gov.uk"


class PaymentsAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="GOV.UK Pay API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://docs.payments.service.gov.uk/api_reference/#authentication",
        "x-credential-instructions": "In the GOV.UK Pay admin tool, select your service, then Settings, Developers, API keys. Paste an API key for that service. Use a test-service key to test payments. NoClick sends it as a bearer token; the payments read proves access to the service, not your personal identity.",
    })
    credential_type: Literal["payments_api_key"] = Field("payments_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def clean_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class PaymentsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def valid_values(cls, value, info):
        if info.field_name in {"payment_id", "agreement_id", "refund_id"} and value is not None:
            import re
            if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
                raise ValueError("Use a single GOV.UK Pay resource ID")
        if info.field_name in {"from_date", "to_date"} and value is not None:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        if info.field_name in {"from_settled_date", "to_settled_date"} and value is not None:
            datetime.strptime(value, "%Y-%m-%d")
        return value


class PaymentsSearchAgreementsConfig(PaymentsInput):
    operation: Literal['search_agreements'] = Field('search_agreements', json_schema_extra={"ui:hidden": True, "x-display-name": 'Search agreements for recurring payments', "x-is-trigger": False})
    reference: Optional[str] = Field(None)
    status: Optional[Literal['created', 'active', 'cancelled', 'inactive']] = Field(None)
    page: int = Field(1, ge=1)
    display_size: int = Field(100, ge=1, le=500)


class PaymentsCreateAgreementConfig(PaymentsInput):
    operation: Literal['create_agreement'] = Field('create_agreement', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create an agreement for recurring payments', "x-is-trigger": False})
    description: str = Field(..., min_length=1, max_length=255, description='A human-readable description of the purpose of the agreement for recurring payments. We’ll show the description to your user when they make their first payment to activate this agreement. Limited to 255 characters.')
    reference: str = Field(..., min_length=1, max_length=255, description='Associate a reference with this agreement to help you identify it. Limited to 255 characters.')
    user_identifier: str = Field(..., min_length=1, max_length=255, description='Associate an identifier with the user who will enter into this agreement with your service.user_identifier is not unique – multiple agreements can have identical user_identifier values.You should not include personal data in user_identifier.')


class PaymentsGetAgreementConfig(PaymentsInput):
    operation: Literal['get_agreement'] = Field('get_agreement', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get information about a single agreement for recurring payments', "x-is-trigger": False})
    agreement_id: str = Field(...)


class PaymentsCancelAgreementConfig(PaymentsInput):
    operation: Literal['cancel_agreement'] = Field('cancel_agreement', json_schema_extra={"ui:hidden": True, "x-display-name": 'Cancel an agreement for recurring payments', "x-is-trigger": False})
    agreement_id: str = Field(...)


class PaymentsSearchDisputesConfig(PaymentsInput):
    operation: Literal['search_disputes'] = Field('search_disputes', json_schema_extra={"ui:hidden": True, "x-display-name": 'Search disputes', "x-is-trigger": False})
    from_date: Optional[str] = Field(None)
    to_date: Optional[str] = Field(None)
    from_settled_date: Optional[str] = Field(None)
    to_settled_date: Optional[str] = Field(None)
    status: Optional[Literal['needs_response', 'under_review', 'lost', 'won']] = Field(None)
    page: int = Field(1, ge=1)
    display_size: int = Field(100, ge=1, le=500)


class PaymentsSearchPaymentsConfig(PaymentsInput):
    operation: Literal['search_payments'] = Field('search_payments', json_schema_extra={"ui:hidden": True, "x-display-name": 'Search payments', "x-is-trigger": False})
    reference: Optional[str] = Field(None)
    email: Optional[str] = Field(None)
    state: Optional[Literal['created', 'started', 'submitted', 'success', 'failed', 'cancelled', 'error']] = Field(None)
    card_brand: Optional[str] = Field(None)
    from_date: Optional[str] = Field(None)
    to_date: Optional[str] = Field(None)
    page: int = Field(1, ge=1)
    display_size: int = Field(100, ge=1, le=500)
    cardholder_name: Optional[str] = Field(None)
    first_digits_card_number: Optional[str] = Field(None)
    last_digits_card_number: Optional[str] = Field(None)
    from_settled_date: Optional[str] = Field(None)
    to_settled_date: Optional[str] = Field(None)
    agreement_id: Optional[str] = Field(None)


class PaymentsCreatePaymentConfig(PaymentsInput):
    operation: Literal['create_payment'] = Field('create_payment', json_schema_extra={"ui:hidden": True, "x-display-name": 'Create a payment', "x-is-trigger": False})
    idempotency_key: Optional[str] = Field(None, pattern='^$|^[a-zA-Z0-9-]+$')
    amount: int = Field(..., ge=0, le=10000000, description='Sets the amount the user will pay, in pence.')
    delayed_capture: Optional[bool] = Field(None, description='You can use this parameter to [delay taking a payment from the paying user’s bank account](https://docs.payments.service.gov.uk/delayed_capture/#delay-taking-a-payment). For example, you might want to do your own anti-fraud checks on payments, or check that users are eligible for your service. Defaults to `false`.')
    description: str = Field(..., min_length=0, max_length=255, description='A human-readable description of the payment you’re creating. Paying users see this description on the payment pages. Service staff see the description in the GOV.UK Pay admin tool')
    email: Optional[str] = Field(None, description='email')
    language: Optional[Literal['en', 'cy']] = Field(None, description='[Sets the language of the user’s payment page](https://docs.payments.service.gov.uk/optional_features/welsh_language) with an ISO-6391 Alpha-2 code of a supported language.')
    reference: str = Field(..., min_length=0, max_length=255, description='Associate a reference with this payment. `reference` is not unique - multiple payments can have identical `reference` values.')
    return_url: str = Field(..., min_length=0, max_length=2000, description='The URL [the paying user is directed to after their payment journey on GOV.UK Pay ends](https://docs.payments.service.gov.uk/making_payments/#choose-the-return-url-and-match-your-users-to-payments).')


class PaymentsGetPaymentConfig(PaymentsInput):
    operation: Literal['get_payment'] = Field('get_payment', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get information about a single payment', "x-is-trigger": False})
    payment_id: str = Field(...)


class PaymentsCancelPaymentConfig(PaymentsInput):
    operation: Literal['cancel_payment'] = Field('cancel_payment', json_schema_extra={"ui:hidden": True, "x-display-name": 'Cancel payment', "x-is-trigger": False})
    payment_id: str = Field(...)


class PaymentsCapturePaymentConfig(PaymentsInput):
    operation: Literal['capture_payment'] = Field('capture_payment', json_schema_extra={"ui:hidden": True, "x-display-name": 'Take a delayed payment', "x-is-trigger": False})
    payment_id: str = Field(...)


class PaymentsGetPaymentEventsConfig(PaymentsInput):
    operation: Literal['get_payment_events'] = Field('get_payment_events', json_schema_extra={"ui:hidden": True, "x-display-name": "Get a payment's events", "x-is-trigger": False})
    payment_id: str = Field(...)


class PaymentsListPaymentRefundsConfig(PaymentsInput):
    operation: Literal['list_payment_refunds'] = Field('list_payment_refunds', json_schema_extra={"ui:hidden": True, "x-display-name": 'Get information about a payment’s refunds', "x-is-trigger": False})
    payment_id: str = Field(...)


class PaymentsCreateRefundConfig(PaymentsInput):
    operation: Literal['create_refund'] = Field('create_refund', json_schema_extra={"ui:hidden": True, "x-display-name": 'Refund a payment', "x-is-trigger": False})
    payment_id: str = Field(...)
    amount: int = Field(..., ge=1, le=10000000, description='The amount you want to [refund to your user](https://docs.payments.service.gov.uk/refunding_payments/) in pence.')
    refund_amount_available: int = Field(..., ge=1, le=10000000, description='Amount in pence. Total amount still available before issuing the refund')


class PaymentsGetRefundConfig(PaymentsInput):
    operation: Literal['get_refund'] = Field('get_refund', json_schema_extra={"ui:hidden": True, "x-display-name": 'Check the status of a refund', "x-is-trigger": False})
    payment_id: str = Field(...)
    refund_id: str = Field(...)


class PaymentsSearchRefundsConfig(PaymentsInput):
    operation: Literal['search_refunds'] = Field('search_refunds', json_schema_extra={"ui:hidden": True, "x-display-name": 'Search refunds', "x-is-trigger": False})
    from_date: Optional[str] = Field(None)
    to_date: Optional[str] = Field(None)
    from_settled_date: Optional[str] = Field(None)
    to_settled_date: Optional[str] = Field(None)
    page: int = Field(1, ge=1)
    display_size: int = Field(100, ge=1, le=500)


OPERATIONS = {'search_agreements': {'method': 'GET',
                       'path': '/v1/agreements',
                       'path_fields': {},
                       'query': ['reference', 'status', 'page', 'display_size'],
                       'body': [],
                       'headers': []},
 'create_agreement': {'method': 'POST',
                      'path': '/v1/agreements',
                      'path_fields': {},
                      'query': [],
                      'body': ['description', 'reference', 'user_identifier'],
                      'headers': []},
 'get_agreement': {'method': 'GET',
                   'path': '/v1/agreements/{agreementId}',
                   'path_fields': {'agreementId': 'agreement_id'},
                   'query': [],
                   'body': [],
                   'headers': []},
 'cancel_agreement': {'method': 'POST',
                      'path': '/v1/agreements/{agreementId}/cancel',
                      'path_fields': {'agreementId': 'agreement_id'},
                      'query': [],
                      'body': [],
                      'headers': []},
 'search_disputes': {'method': 'GET',
                     'path': '/v1/disputes',
                     'path_fields': {},
                     'query': ['from_date',
                               'to_date',
                               'from_settled_date',
                               'to_settled_date',
                               'status',
                               'page',
                               'display_size'],
                     'body': [],
                     'headers': []},
 'search_payments': {'method': 'GET',
                     'path': '/v1/payments',
                     'path_fields': {},
                     'query': ['reference',
                               'email',
                               'state',
                               'card_brand',
                               'from_date',
                               'to_date',
                               'page',
                               'display_size',
                               'cardholder_name',
                               'first_digits_card_number',
                               'last_digits_card_number',
                               'from_settled_date',
                               'to_settled_date',
                               'agreement_id'],
                     'body': [],
                     'headers': []},
 'create_payment': {'method': 'POST',
                    'path': '/v1/payments',
                    'path_fields': {},
                    'query': [],
                    'body': ['amount',
                             'delayed_capture',
                             'description',
                             'email',
                             'language',
                             'reference',
                             'return_url'],
                    'headers': ['idempotency_key']},
 'get_payment': {'method': 'GET',
                 'path': '/v1/payments/{paymentId}',
                 'path_fields': {'paymentId': 'payment_id'},
                 'query': [],
                 'body': [],
                 'headers': []},
 'cancel_payment': {'method': 'POST',
                    'path': '/v1/payments/{paymentId}/cancel',
                    'path_fields': {'paymentId': 'payment_id'},
                    'query': [],
                    'body': [],
                    'headers': []},
 'capture_payment': {'method': 'POST',
                     'path': '/v1/payments/{paymentId}/capture',
                     'path_fields': {'paymentId': 'payment_id'},
                     'query': [],
                     'body': [],
                     'headers': []},
 'get_payment_events': {'method': 'GET',
                        'path': '/v1/payments/{paymentId}/events',
                        'path_fields': {'paymentId': 'payment_id'},
                        'query': [],
                        'body': [],
                        'headers': []},
 'list_payment_refunds': {'method': 'GET',
                          'path': '/v1/payments/{paymentId}/refunds',
                          'path_fields': {'paymentId': 'payment_id'},
                          'query': [],
                          'body': [],
                          'headers': []},
 'create_refund': {'method': 'POST',
                   'path': '/v1/payments/{paymentId}/refunds',
                   'path_fields': {'paymentId': 'payment_id'},
                   'query': [],
                   'body': ['amount', 'refund_amount_available'],
                   'headers': []},
 'get_refund': {'method': 'GET',
                'path': '/v1/payments/{paymentId}/refunds/{refundId}',
                'path_fields': {'paymentId': 'payment_id', 'refundId': 'refund_id'},
                'query': [],
                'body': [],
                'headers': []},
 'search_refunds': {'method': 'GET',
                    'path': '/v1/refunds',
                    'path_fields': {},
                    'query': ['from_date',
                              'to_date',
                              'from_settled_date',
                              'to_settled_date',
                              'page',
                              'display_size'],
                    'body': [],
                    'headers': []}}

class PaymentsOnNewPaymentConfig(PollTriggerConfigBase):
    operation: Literal["on_new_payment"] = Field("on_new_payment", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-display-name": "On New Payment", "x-category": "Triggers"})
    from_date: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", description="Monitor payments created on or after this UTC time. Defaults to a rolling 24-hour window. Existing payments are baselined when armed.")


PaymentsConfig = Annotated[Union[PaymentsSearchAgreementsConfig, PaymentsCreateAgreementConfig, PaymentsGetAgreementConfig, PaymentsCancelAgreementConfig, PaymentsSearchDisputesConfig, PaymentsSearchPaymentsConfig, PaymentsCreatePaymentConfig, PaymentsGetPaymentConfig, PaymentsCancelPaymentConfig, PaymentsCapturePaymentConfig, PaymentsGetPaymentEventsConfig, PaymentsListPaymentRefundsConfig, PaymentsCreateRefundConfig, PaymentsGetRefundConfig, PaymentsSearchRefundsConfig, PaymentsOnNewPaymentConfig], Field(discriminator="operation")]

class PaymentsNodeConfig(NodeConfig[PaymentsConfig, PaymentsAPIKeyCredential]):
    pass


class PaymentsNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-payments"
    connection_evidence = ConnectionEvidence(operation="search_payments", noun="payments", label_keys=("reference", "description", "payment_id"))
    edit_examples = ["Create a GOV.UK Pay payment", "Refund a payment", "Find payments by reference", "Watch for new payments"]

    @classmethod
    def get_config_model(cls):
        return PaymentsNodeConfig

    @staticmethod
    async def _request(api_key, method, path, *, params=None, body=None, headers=None):
        request_headers = {"Authorization": "Bearer " + api_key, "Accept": "application/json", **(headers or {})}
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, headers=request_headers, params=params, **({"json": body} if body is not None else {}))
        if response.is_error:
            raise ValueError(f"GOV.UK Pay HTTP {response.status_code}: " + response.text.replace(api_key, "[redacted]")[:1000])
        if response.status_code == 204:
            return {"status": "success", "http_status": 204}
        if not 200 <= response.status_code < 300:
            raise ValueError(f"Unexpected GOV.UK Pay HTTP {response.status_code}")
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("GOV.UK Pay returned an invalid JSON object")
        return data

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a GOV.UK Pay API key")
        config = self.config.config
        key = self.config.credentials.api_key
        if isinstance(config, PaymentsOnNewPaymentConfig):
            since = config.from_date or (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            items = []
            # Never advance a partial baseline: require a complete bounded window.
            for page in range(1, 21):
                result = await self._request(key, "GET", "/v1/payments", params={"from_date": since, "page": page, "display_size": 500})
                rows = result.get("results")
                if not isinstance(rows, list) or any(not isinstance(row, dict) or not row.get("payment_id") for row in rows):
                    raise ValueError("GOV.UK Pay payment search did not return payment IDs")
                items.extend(rows)
                if len(rows) < 500:
                    break
                if page == 20:
                    raise ValueError("More than 10,000 payments in the poll window; set a narrower from date")
            fresh = await self._filter_unseen(items, lambda row: str(row["payment_id"]))
            return {"payments": fresh, "new_payment_count": len(fresh)}
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True)
        path = spec["path"]
        for wire, name in spec["path_fields"].items():
            path = path.replace("{" + wire + "}", quote(str(values[name]), safe=""))
        params = {name: values[name] for name in spec["query"] if name in values}
        body = {name: values[name] for name in spec["body"] if name in values} if spec["body"] else None
        headers = {"Idempotency-Key": values["idempotency_key"]} if "idempotency_key" in values else None
        return await self._request(key, spec["method"], path, params=params or None, body=body, headers=headers)

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_payment_count")) if config.get("operation") == "on_new_payment" else True

    @classmethod
    def resolve_agent_event(cls, output):
        payments = output.get("payments", [])
        if not payments:
            return None
        import json
        return {"text": f"{len(payments)} new payment(s) were created in GOV.UK Pay. "
                "Use payment_id to inspect or refund a payment. Details: " + json.dumps(payments, ensure_ascii=False),
                "title": "New GOV.UK Pay payments"}
