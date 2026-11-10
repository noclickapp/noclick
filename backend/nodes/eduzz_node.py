"""Eduzz sales, subscriptions and learning operations.

Wire contract: https://developers.eduzz.com/api/openapi (2.0.0).
Application bearer tokens: https://developers.eduzz.com/docs/api/app-token.
Webhook signatures: https://developers.eduzz.com/docs/webhook/security.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.webhook_trigger import ExternalWebhookTriggerMixin, WebhookTriggerConfigBase
from nodes.scopes.eduzz import EDUZZ_SCOPES

BASE_URL = "https://api.eduzz.com"
CREDENTIAL_TYPE = "eduzz_access_token"
WEBHOOK_EVENTS = (
    "myeduzz.invoice_paid", "myeduzz.invoice_refunded", "myeduzz.invoice_canceled",
    "myeduzz.contract_created", "myeduzz.contract_updated",
)


class EduzzAccessTokenCredential(BaseModel):
    model_config = ConfigDict(title="Eduzz Access Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://console.eduzz.com",
            "x-credential-instructions": "Paste an existing application access token for your Eduzz account, without the Bearer prefix. Create an app and enable the permissions needed by your actions in the Eduzz Developer Console. Application authentication is documented at https://developers.eduzz.com/docs/api/app-token. Personal test tokens are for development only. Webhook triggers also need webhook_read and webhook_write permissions.",
        })
    credential_type: Literal["eduzz_access_token"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., title="Access Token", min_length=1, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access Token")
        if len(value) > 8192 or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the access token without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def valid_datetime(cls, value, info):
        if info.field_name in {"startDate", "endDate", "expiredAt"} and value is not None:
            if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", value):
                raise ValueError("Use a UTC timestamp such as 2025-01-22T00:00:00Z")
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value


class EduzzGetAccountConfig(_Input):
    """Retorna dados do usuário logado."""
    operation: Literal['get_account'] = Field('get_account', title='Get Account', json_schema_extra={"ui:hidden": True})


class EduzzListSalesConfig(_Input):
    """Obtém uma lista detalhada de vendas com base nos filtros fornecidos"""
    operation: Literal['list_sales'] = Field('list_sales', title='List Sales', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, title='page', description='Página atual')
    itemsPerPage: int = Field(20, ge=1, le=100, title='itemsPerPage', description='Número de itens por página')
    startDate: str = Field(..., min_length=1, title='startDate', description='Data de início das vendas Use a UTC timestamp, for example 2025-01-22T00:00:00Z.', json_schema_extra={"format": "date-time"})
    endDate: str = Field(..., min_length=1, title='endDate', description='Data de término das vendas Use a UTC timestamp, for example 2025-01-22T00:00:00Z.', json_schema_extra={"format": "date-time"})
    referenceDate: Literal['dueDate', 'paidAt', 'createdAt', 'updatedAt'] | None = Field(None, title='referenceDate', description='Campo de data de referência para consultar as vendas')
    contractId: float | None = Field(None, title='contractId', description='Id do contrato')
    status: Literal['open', 'processing', 'paid', 'canceled', 'waitingRefund', 'refunded', 'duplicated', 'expired', 'recovering', 'waitingPayment', 'scheduled', 'negotiated'] | None = Field(None, title='status', description='Status da venda')
    productId: float | None = Field(None, title='productId', description='Id do produto')
    affiliateId: float | None = Field(None, title='affiliateId', description='Id do afiliado')
    buyerEmail: str | None = Field(None, title='buyerEmail', description='Email do comprador')
    buyerDocument: str | None = Field(None, title='buyerDocument', description='CPF ou CNPJ do comprador')


class EduzzGetSaleConfig(_Input):
    """Obtém detalhes de uma venda específica"""
    operation: Literal['get_sale'] = Field('get_sale', title='Get Sale', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, title='Sale ID', description='Id da venda que se deseja obter os detalhes')


class EduzzListProductsConfig(_Input):
    """Listagem de todos os produtos do produtor"""
    operation: Literal['list_products'] = Field('list_products', title='List Products', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, title='page', description='Página atual')
    itemsPerPage: int = Field(20, ge=1, le=100, title='itemsPerPage', description='Número de itens por página')


class EduzzGetProductConfig(_Input):
    """Obtém os detalhes de um produto específico"""
    operation: Literal['get_product'] = Field('get_product', title='Get Product', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, title='Product ID', description='Id do produto que se deseja obter os detalhes')


class EduzzListCustomersConfig(_Input):
    """Listagem de todos os compradores com base nos filtros fornecidos."""
    operation: Literal['list_customers'] = Field('list_customers', title='List Customers', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, title='page', description='Página atual')
    itemsPerPage: int = Field(20, ge=1, le=100, title='itemsPerPage', description='Número de itens por página')
    order: Literal['asc', 'desc'] | None = Field(None, title='order', description='Ordenação dos resultados (ascendente ou descendente)')
    startDate: str | None = Field(None, title='startDate', description='Data de início do período Use a UTC timestamp, for example 2025-01-22T00:00:00Z.', json_schema_extra={"format": "date-time"})
    endDate: str | None = Field(None, title='endDate', description='Data de término do período Use a UTC timestamp, for example 2025-01-22T00:00:00Z.', json_schema_extra={"format": "date-time"})


class EduzzGetCustomerConfig(_Input):
    """Obtém detalhes de um comprador"""
    operation: Literal['get_customer'] = Field('get_customer', title='Get Customer', json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1, title='email', description='E-mail do comprador que se deseja obter os detalhes')


class EduzzListSubscriptionsConfig(_Input):
    """Obtém os detalhes das assinaturas por intervalo de data"""
    operation: Literal['list_subscriptions'] = Field('list_subscriptions', title='List Subscriptions', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, title='page', description='Página atual')
    itemsPerPage: int = Field(20, ge=1, le=100, title='itemsPerPage', description='Quantidade de itens por página')
    startDate: str | None = Field(None, title='startDate', description='Data de início do intervalo de busca (inclusive) Use a UTC timestamp, for example 2025-01-22T00:00:00Z.', json_schema_extra={"format": "date-time"})
    endDate: str | None = Field(None, title='endDate', description='Data de término do intervalo de busca (inclusive) Use a UTC timestamp, for example 2025-01-22T00:00:00Z.', json_schema_extra={"format": "date-time"})
    filterBy: Literal['creation', 'update'] | None = Field(None, title='filterBy', description='Filtra os resultados por tipo de alteração (criação ou atualização)')


class EduzzGetSubscriptionConfig(_Input):
    """Obtém os detalhes de uma assinatura por id"""
    operation: Literal['get_subscription'] = Field('get_subscription', title='Get Subscription', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, title='Subscription ID', description='Id da assinatura')


class EduzzListSubscriptionInvoicesConfig(_Input):
    """Obtém as faturas de uma assinatura."""
    operation: Literal['list_subscription_invoices'] = Field('list_subscription_invoices', title='List Subscription Invoices', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, title='Subscription ID', description='Id da assinatura')


class EduzzCancelSubscriptionsConfig(_Input):
    """Realiza o cancelamento em massa de contratos."""
    operation: Literal['cancel_subscriptions'] = Field('cancel_subscriptions', title='Cancel Subscriptions', json_schema_extra={"ui:hidden": True})
    subscriptions: list[str] = Field(..., min_length=1, title='Subscriptions', description='Subscription IDs to cancel.', json_schema_extra={"ui:widget": "list"})
    cancelReason: str | None = Field(None, title='cancelReason', description='Motivo do cancelamento.')


class EduzzReactivateSubscriptionConfig(_Input):
    """Realiza a reativação de um contrato"""
    operation: Literal['reactivate_subscription'] = Field('reactivate_subscription', title='Reactivate Subscription', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, title='Subscription ID', description='Id da assinatura')


class EduzzChangeSubscriptionBillingDayConfig(_Input):
    """Modifica o dia de cobrança de uma assinatura específica."""
    operation: Literal['change_subscription_billing_day'] = Field('change_subscription_billing_day', title='Change Subscription Billing Day', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, title='Subscription ID', description='Id da assinatura')
    dueDateDay: Literal['1', '5', '10', '15', '20', '25'] = Field(..., title='dueDateDay', description='Dia do vencimento a ser alterado no contrato.')
    motive: Literal['Solicitação do cliente', 'Negociação comercial', 'Reorganização financeira do cliente', 'Mudança no método de pagamento', 'Problemas com a data atual de pagamento'] = Field(..., title='motive', description='Motivo da alteração do dia do vencimento.')


class EduzzListStudentsConfig(_Input):
    """Listar alunos"""
    operation: Literal['list_students'] = Field('list_students', title='List Students', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, title='page', description='Página atual')
    itemsPerPage: int = Field(20, ge=1, le=100, title='itemsPerPage', description='Número de itens por página')
    id: str | None = Field(None, title='ID', description='Id do aluno')
    email: str | None = Field(None, title='email', description='Email do aluno')


class EduzzGetStudentConfig(_Input):
    """Perfil do aluno"""
    operation: Literal['get_student'] = Field('get_student', title='Get Student', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, title='Student ID', description='Id do aluno')


class EduzzListStudentEnrollmentsConfig(_Input):
    """Lista matrículas do aluno"""
    operation: Literal['list_student_enrollments'] = Field('list_student_enrollments', title='List Student Enrollments', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, title='Student ID', description='Id do aluno')
    page: int = Field(1, ge=1, title='page', description='Página atual')
    itemsPerPage: int = Field(20, ge=1, le=100, title='itemsPerPage', description='Número de itens por página')


class EduzzBlockEnrollmentConfig(_Input):
    """Bloqueia o aluno"""
    operation: Literal['block_enrollment'] = Field('block_enrollment', title='Block Enrollment', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, title='Enrollment ID', description='Id da matrícula')


class EduzzExtendEnrollmentAccessConfig(_Input):
    """Estende o acesso do aluno"""
    operation: Literal['extend_enrollment_access'] = Field('extend_enrollment_access', title='Extend Enrollment Access', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, title='Enrollment ID', description='Id da matrícula')
    expiredAt: str = Field(..., min_length=1, title='expiredAt', description='Nova data de expiração Use a UTC timestamp, for example 2025-01-22T00:00:00Z.', json_schema_extra={"format": "date-time"})


class EduzzListSchoolsConfig(_Input):
    """Listar minhas escolas"""
    operation: Literal['list_schools'] = Field('list_schools', title='List Schools', json_schema_extra={"ui:hidden": True})
    sort: str | None = Field(None, title='sort', description='Ordenação dos itens podendo ter várias ordenações, seguindo o seguinte padrão: campo:ordenação Ex.: name:asc,url:desc')


class EduzzCreateSchoolStudentConfig(_Input):
    """Cria um novo aluno em uma escola."""
    operation: Literal['create_school_student'] = Field('create_school_student', title='Create School Student', json_schema_extra={"ui:hidden": True})
    teamId: str = Field(..., min_length=1, title='teamId', description='Id da escola')
    name: str = Field(..., min_length=1, title='name', description='Nome do aluno')
    email: str = Field(..., min_length=1, title='email', description='Email do aluno')
    phone: str = Field(..., min_length=1, title='phone', description='Telefone do aluno')
    document: str = Field(..., min_length=1, title='document', description='CPF do aluno')
    tags: list[str] = Field(..., title='Tags', description='Student tags.', json_schema_extra={"ui:widget": "list"})


class EduzzOnEventConfig(WebhookTriggerConfigBase):
    operation: Literal["on_event"] = Field("on_event", title="On Eduzz Event",
        json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers"})
    event_type: Literal[*WEBHOOK_EVENTS] = Field("myeduzz.invoice_paid", title="Event",
        description="Invoice paid, refunded or canceled, or subscription created or updated.")
    webhook_url: str | None = Field(None, title="Webhook URL",
        json_schema_extra={"ui:widget": "webhook", "ui:copyable": True, "ui:loadValue": True})

EduzzOperation = Annotated[Union[EduzzGetAccountConfig, EduzzListSalesConfig, EduzzGetSaleConfig, EduzzListProductsConfig, EduzzGetProductConfig, EduzzListCustomersConfig, EduzzGetCustomerConfig, EduzzListSubscriptionsConfig, EduzzGetSubscriptionConfig, EduzzListSubscriptionInvoicesConfig, EduzzCancelSubscriptionsConfig, EduzzReactivateSubscriptionConfig, EduzzChangeSubscriptionBillingDayConfig, EduzzListStudentsConfig, EduzzGetStudentConfig, EduzzListStudentEnrollmentsConfig, EduzzBlockEnrollmentConfig, EduzzExtendEnrollmentAccessConfig, EduzzListSchoolsConfig, EduzzCreateSchoolStudentConfig, EduzzOnEventConfig], Field(discriminator="operation")]


class EduzzNodeConfig(NodeConfig[EduzzOperation, EduzzAccessTokenCredential]):
    pass


OPERATIONS = {'get_account': {'method': 'GET',
                 'path': '/accounts/v1/me',
                 'query': (),
                 'body': (),
                 'contract_operation': 'getaccountsv1me'},
 'list_sales': {'method': 'GET',
                'path': '/myeduzz/v1/sales',
                'query': ('page',
                          'itemsPerPage',
                          'startDate',
                          'endDate',
                          'referenceDate',
                          'contractId',
                          'status',
                          'productId',
                          'affiliateId',
                          'buyerEmail',
                          'buyerDocument'),
                'body': (),
                'contract_operation': 'getmyeduzzv1sales'},
 'get_sale': {'method': 'GET',
              'path': '/myeduzz/v1/sales/:id',
              'query': (),
              'body': (),
              'contract_operation': 'getmyeduzzv1salesid'},
 'list_products': {'method': 'GET',
                   'path': '/myeduzz/v1/products',
                   'query': ('page', 'itemsPerPage'),
                   'body': (),
                   'contract_operation': 'getmyeduzzv1products'},
 'get_product': {'method': 'GET',
                 'path': '/myeduzz/v1/products/:id',
                 'query': (),
                 'body': (),
                 'contract_operation': 'getmyeduzzv1productsid'},
 'list_customers': {'method': 'GET',
                    'path': '/myeduzz/v1/customers',
                    'query': ('page', 'itemsPerPage', 'order', 'startDate', 'endDate'),
                    'body': (),
                    'contract_operation': 'getmyeduzzv1customers'},
 'get_customer': {'method': 'GET',
                  'path': '/myeduzz/v1/customers/:email',
                  'query': (),
                  'body': (),
                  'contract_operation': 'getmyeduzzv1customersemail'},
 'list_subscriptions': {'method': 'GET',
                        'path': '/myeduzz/v1/subscriptions',
                        'query': ('page', 'itemsPerPage', 'startDate', 'endDate', 'filterBy'),
                        'body': (),
                        'contract_operation': 'getmyeduzzv1subscriptions'},
 'get_subscription': {'method': 'GET',
                      'path': '/myeduzz/v1/subscriptions/:id',
                      'query': (),
                      'body': (),
                      'contract_operation': 'getmyeduzzv1subscriptionsid'},
 'list_subscription_invoices': {'method': 'GET',
                                'path': '/myeduzz/v1/subscriptions/:id/invoices',
                                'query': (),
                                'body': (),
                                'contract_operation': 'getmyeduzzv1subscriptionsidinvoices'},
 'cancel_subscriptions': {'method': 'POST',
                          'path': '/myeduzz/v1/subscriptions/bulk-cancel',
                          'query': (),
                          'body': ('subscriptions', 'cancelReason'),
                          'contract_operation': 'postmyeduzzv1subscriptionsbulkcancel'},
 'reactivate_subscription': {'method': 'POST',
                             'path': '/myeduzz/v1/subscriptions/:id/reactivate',
                             'query': (),
                             'body': (),
                             'contract_operation': 'postmyeduzzv1subscriptionsidreactivate'},
 'change_subscription_billing_day': {'method': 'PUT',
                                     'path': '/myeduzz/v1/subscriptions/:id/recurring-date',
                                     'query': (),
                                     'body': ('dueDateDay', 'motive'),
                                     'contract_operation': 'putmyeduzzv1subscriptionsidrecurringdate'},
 'list_students': {'method': 'GET',
                   'path': '/nutror/v1/students',
                   'query': ('page', 'itemsPerPage', 'id', 'email'),
                   'body': (),
                   'contract_operation': 'getnutrorv1students'},
 'get_student': {'method': 'GET',
                 'path': '/nutror/v1/students/:id',
                 'query': (),
                 'body': (),
                 'contract_operation': 'getnutrorv1studentsid'},
 'list_student_enrollments': {'method': 'GET',
                              'path': '/nutror/v1/students/:id/enrollments',
                              'query': ('page', 'itemsPerPage'),
                              'body': (),
                              'contract_operation': 'getnutrorv1studentsidenrollments'},
 'block_enrollment': {'method': 'PUT',
                      'path': '/nutror/v1/enrollments/:id/block',
                      'query': (),
                      'body': (),
                      'contract_operation': 'putnutrorv1enrollmentsidblock'},
 'extend_enrollment_access': {'method': 'PUT',
                              'path': '/nutror/v1/enrollments/:id/extend-access',
                              'query': (),
                              'body': ('expiredAt',),
                              'contract_operation': 'putnutrorv1enrollmentsidextendaccess'},
 'list_schools': {'method': 'GET',
                  'path': '/alpaclass/v1/producer/teams',
                  'query': ('sort',),
                  'body': (),
                  'contract_operation': 'getalpaclassv1producerteams'},
 'create_school_student': {'method': 'POST',
                           'path': '/alpaclass/v1/producer/teams/:teamId/students',
                           'query': (),
                           'body': ('name', 'email', 'phone', 'document', 'tags'),
                           'contract_operation': 'postalpaclassv1producerteamsteamIdstudents'}}


def _path(template, values):
    for key in re.findall(r":([A-Za-z][A-Za-z0-9]*)", template):
        value = str(values.pop(key))
        if value in {".", ".."}:
            raise ValueError("Use an Eduzz resource ID")
        template = template.replace(":" + key, quote(value, safe=""))
    return template


class EduzzNode(ExternalWebhookTriggerMixin, WorkflowNode):
    integration_type = "automation-eduzz"
    connection_evidence = ConnectionEvidence(operation="get_account", identity_operation="get_account", noun="account")
    scope_registry = EDUZZ_SCOPES
    edit_examples = ["Find paid Eduzz sales", "Cancel Eduzz subscriptions", "Extend a student's course access", "When an Eduzz invoice is paid"]

    @classmethod
    def get_config_model(cls):
        return EduzzNodeConfig

    @staticmethod
    async def _request(token, method, path, *, params=None, body=None):
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers, params=params,
                **({"json": body} if body is not None else {}))
        if not 200 <= response.status_code < 300:
            try:
                error = response.json()
                message = error.get("message") or error.get("error") if isinstance(error, dict) else str(error)
            except ValueError:
                message = "Request rejected"
            raise ValueError(f"Eduzz API {response.status_code}: {str(message or 'Request rejected').replace(token, '[redacted]')[:1000]}")
        return response.json() if response.content else None

    async def execute(self, inputs):
        if not isinstance(self.config, EduzzNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect an Eduzz access token")
        op = self.config.config
        if isinstance(op, EduzzOnEventConfig):
            return self.no_event_output(op.operation)
        self.scope_registry.require(op.operation)
        spec = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        path = _path(spec["path"], values)
        params = {key: values[key] for key in spec["query"] if key in values}
        body = {key: values[key] for key in spec["body"] if key in values}
        data = await self._request(self.config.credentials.access_token, spec["method"], path,
            params=params or None, body=body if spec["body"] else None)
        result = {"status": "success", "operation": op.operation, "data": data}
        await self.emit(result)
        return result

    @classmethod
    def registration_fingerprint_fields(cls, config):
        return {"event_type": (config or {}).get("event_type", "myeduzz.invoice_paid")}

    @classmethod
    async def _register_external_webhook(cls, *, webhook_url, credential, config, node_id):
        event = (config or {}).get("event_type", "myeduzz.invoice_paid")
        if event not in WEBHOOK_EVENTS:
            raise ValueError("Choose a supported Eduzz event")
        token = EduzzAccessTokenCredential.model_validate(credential).access_token
        cls.scope_registry.require("get_webhook_secret")
        secret = await cls._request(token, "GET", "/webhook/v1/secret")
        if not isinstance(secret, dict) or not secret.get("secret"):
            raise ValueError("Eduzz did not return the application's webhook signing secret")
        cls.scope_registry.require("on_event")
        subscription = await cls._request(token, "POST", "/webhook/v1/subscription",
            body={"name": f"NoClick {node_id}", "url": webhook_url, "events": [{"name": event}], "filters": []})
        if not isinstance(subscription, dict) or not subscription.get("id"):
            raise ValueError("Eduzz did not return a webhook subscription ID")
        sid = str(subscription["id"])
        try:
            # New subscriptions are disabled in the documented creation response.
            cls.scope_registry.require("activate_webhook")
            await cls._request(token, "POST", "/webhook/v1/subscription/" + quote(sid, safe="") + "/status",
                body={"status": "active"})
        except Exception:
            cls.scope_registry.require("delete_webhook")
            await cls._request(token, "DELETE", "/webhook/v1/subscription/" + quote(sid, safe=""))
            raise
        return {"external_webhook_id": sid, "signing_secret": secret["secret"]}

    @classmethod
    async def _unregister_external_webhook(cls, *, credential, config, node_id):
        sid = (config or {}).get("external_webhook_id")
        if not sid:
            return
        if not credential:
            raise ValueError("Eduzz credentials are required to remove this webhook subscription")
        token = EduzzAccessTokenCredential.model_validate(credential).access_token
        cls.scope_registry.require("delete_webhook")
        await cls._request(token, "DELETE", "/webhook/v1/subscription/" + quote(str(sid), safe=""))

    @classmethod
    def verify_webhook_signature(cls, body: bytes, headers: dict[str, str], config: dict[str, Any]) -> bool:
        secret = (config or {}).get("signing_secret")
        signature = next((v for k, v in headers.items() if k.lower() == "x-signature"), "")
        if not isinstance(secret, str) or not secret or not isinstance(signature, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", signature):
            return False
        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature.lower())

    @classmethod
    def handle_webhook_handshake(cls, body, headers, config=None):
        """Eduzz pings during activation, before registration state is saved.

        https://developers.eduzz.com/docs/webhook/ping requires a 2xx reply
        without running the workflow. Business deliveries still require HMAC.
        """
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError):
            return None
        if isinstance(payload, dict) and payload.get("event") == "ping":
            return {}
        return None

    @classmethod
    def filter_trigger_payload(cls, payload, config):
        event = payload.get("event")
        expected = (config or {}).get("event_type", "myeduzz.invoice_paid")
        return event in WEBHOOK_EVENTS and event == expected

    @classmethod
    def resolve_agent_event(cls, output):
        if not isinstance(output, dict):
            return None
        event = output.get("event")
        if event not in WEBHOOK_EVENTS:
            return None
        data = output.get("data")
        if not isinstance(data, dict):
            return None
        if event.startswith("myeduzz.contract_"):
            account = data.get("customer") or {}
            record = data.get("contract") or {}
            products = data.get("products") or []
            location = "MyEduzz subscription"
        else:
            account = data.get("buyer") or {}
            record = data
            products = data.get("items") or []
            location = "MyEduzz invoice"
        identifier = record.get("id")
        who = account.get("name") or account.get("email") or "Customer"
        lines = [f"Eduzz {event}: {who}", f"{location} ID: {identifier}"]
        if account.get("email"):
            lines.append(f"Customer email: {account['email']}")
        if record.get("status"):
            lines.append(f"Status: {record['status']}")
        names = [str(row["name"]) for row in products if isinstance(row, dict) and row.get("name")]
        if names:
            lines.append("Products: " + ", ".join(names))
        if output.get("id"):
            lines.append(f"Delivery ID: {output['id']}")
        lines.append("Use get_subscription with this ID." if event.startswith("myeduzz.contract_") else "Use get_sale with this ID.")
        return {"text": "\n".join(lines)[:6000], "conversation_key": str(identifier or output.get("id") or event),
            "title": f"{location} {identifier}: {who}"[:200]}
