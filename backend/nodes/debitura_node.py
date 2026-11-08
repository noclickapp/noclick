"""Debitura Customer API v1: account-owned debt collection workflows.

Contract: https://docs.debitura.com/openapi/customer-api.json
API keys are for creditors managing their own accounts (not referral partners).
Each operation sends one request; list operations return a single provider page.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://customer-api.debitura.com"


class DebituraAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Debitura API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.debitura.com/CreditorApiKey",
            "x-credential-instructions": "In the Debitura Client Portal, open API Keys and generate a key for your own creditor account. Paste the key below. NoClick sends it in the XApiKey header and verifies it by reading your creditor profile. Referral partner tokens are not supported.",
        })
    credential_type: Literal["debitura_api_key"] = Field("debitura_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)

    @field_validator("date", "dueDate", check_fields=False)
    @classmethod
    def invoice_date(cls, value):
        if value is None:
            return value
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            raise ValueError("Use an ISO 8601 invoice date or date-time") from None
        if parsed.date() > date.today():
            raise ValueError("Invoice dates cannot be in the future")
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).isoformat()



class DebituraGetMeConfig(_Input):
    """Verifies the provided authentication and returns the current Creditor profile."""
    operation: Literal["get_me"] = Field("get_me", json_schema_extra={"ui:hidden": True})


class DebituraListCasesConfig(_Input):
    """List collection cases."""
    operation: Literal["list_cases"] = Field("list_cases", json_schema_extra={"ui:hidden": True})
    page: int | None = Field(1, ge=1)
    page_size: int | None = Field(10, ge=1, le=100)
    debtor_ids: list[UUID] | None = Field(None)
    ids: list[UUID] | None = Field(None)
    statuses: list[str] | None = Field(None)
    division_ids: list[UUID] | None = Field(None)
    sort: str | None = Field(None)


class Debtor(_Input):
    type: Literal["Company", "Private"] = Field(..., description='Debtor type. Valid values: "Company" or "Private" (case-insensitive)')
    name: str = Field(..., min_length=1, description="Debtor name (company name or person's full name)")
    contactPerson: str | None = Field(None, description='Contact person at the company (required for companies, not used for persons)')
    companyRegistrationNumber: str | None = Field(None, description='Company registration number (VAT number, CVR, org number, etc.)')
    address: str | None = Field(None, description='Street address')
    zipCode: str | None = Field(None, description='Postal/ZIP code')
    city: str | None = Field(None, description='City name')
    state: str | None = Field(None, description='State/region/province name')
    stateAlpha2: str | None = Field(None, description='US state: two-letter code (e.g., "CA"), ISO 3166-2 format (e.g., "US-CA"), or full name (e.g., "California")')
    countryAlpha2: str | None = Field(None, description='Country code (ISO 3166-1 alpha-2 format)')
    country: str | None = Field(None, description='Country name')
    email: str | None = Field(None, description='Email address for debtor contact')
    phone: str | None = Field(None, description='Phone number (include country code)')


class _ClaimInput(_Input):
    @model_validator(mode="after")
    def amount_mode(self):
        lines = getattr(self, "claimLines", None)
        amount = getattr(self, "amountToRecover", None)
        buckets = [getattr(self, field, None) for field in (
            "amountToRecoverOver6Months", "amountToRecoverOver12Months", "amountToRecoverOver24Months")]
        if lines:
            if amount not in (None, 0) or any(value is not None for value in buckets):
                raise ValueError("Use claimLines separately from amountToRecover and age buckets")
            if isinstance(self, PreviewCaseBody) and self.dueDate is not None:
                raise ValueError("Preview claimLines cannot be combined with dueDate")
        elif amount is None or amount <= 0:
            raise ValueError("Provide a positive amountToRecover or nonempty claimLines")
        if (buckets[1] is None) != (buckets[2] is None) or (buckets[0] is not None and buckets[1] is None):
            raise ValueError("Provide 12- and 24-month age buckets together; 6-month needs both")
        supplied = [value for value in buckets if value is not None]
        if supplied and (any(value < 0 for value in supplied) or supplied != sorted(supplied, reverse=True) or supplied[0] > amount):
            raise ValueError("Age buckets must be nonnegative and descend from the total amount")
        if isinstance(self, PreviewCaseBody) and self.dueDate is not None and supplied:
            raise ValueError("Preview dueDate cannot be combined with age buckets")
        return self


class ClaimLine(_Input):
    dueDate: str = Field(..., description='Payment deadline of this invoice.', json_schema_extra={'format': 'date-time'})
    amount: float = Field(..., gt=0, description='The outstanding balance on this invoice in the case currency — what the debtor still owes on it,')
    reference: str | None = Field(None, description='Optional: your own invoice number for this line. Used only to make validation errors readable')

    @field_validator("dueDate")
    @classmethod
    def earliest_claim_date(cls, value):
        if datetime.fromisoformat(value).date() < date(2000, 1, 1):
            raise ValueError("Claim-line due dates must be on or after 2000-01-01")
        return value


class CreateCaseBody(_ClaimInput):
    currencyCode: str = Field(..., min_length=3, max_length=3)
    date: str = Field(..., description='Invoice date; no future dates.', json_schema_extra={'format': 'date-time'})
    dueDate: str | None = Field(None, description='ISO 8601 date or date-time accepted by Debitura.')
    comments: str | None = Field(None, max_length=4000, description='Optional comments about the case, e.g. payment history or communication context.')
    claimDescription: str | None = Field(None, max_length=4000, description='Client provided description of the claim')
    creditorReference: str | None = Field(None, max_length=50)
    debtor: Debtor = Field(...)
    creditorDivisionId: UUID | None = Field(None)
    amountToRecover: float | None = Field(None, description='The TOTAL amount to recover for this case.')
    amountToRecoverOver6Months: float | None = Field(None, description='OPTIONAL - MULTI-INVOICE AGE BUCKET PRICING (PRICING ZONE 180-DAY THRESHOLD)')
    amountToRecoverOver12Months: float | None = Field(None, description='OPTIONAL - MULTI-INVOICE AGE BUCKET PRICING')
    amountToRecoverOver24Months: float | None = Field(None, description='OPTIONAL - MULTI-INVOICE AGE BUCKET PRICING')
    claimLines: list[ClaimLine] | None = Field(None, min_length=1, max_length=1000, description='OPTIONAL - the unpaid invoices making up this claim, one line per invoice, each carrying its')
    allowPendingContracts: bool | None = Field(None, description="When true, cases with unsigned contracts (SDCA/POA) are accepted in 'PendingContractSigning'")
    isTest: bool | None = Field(None, description='When true, creates a test case that IS persisted to the database but marked as test data.')
    tag: str | None = Field(None, max_length=100, description='Optional tag for scoped test data grouping (e.g. "suite-run-{uuid}").')
    assignedUserEmail: EmailStr | None = Field(None, max_length=320, description='Optional: Email address of the creditor team member to assign as the case owner.')
    returnUrl: str | None = Field(None, max_length=2048, description='Optional: URL the creditor user should land on after completing any')


class DebituraCreateCaseConfig(CreateCaseBody):
    """Create collection case."""
    operation: Literal["create_case"] = Field("create_case", json_schema_extra={"ui:hidden": True})
    idempotency_key: str | None = Field(None, min_length=1, max_length=255, description='Optional retry key. Reuse only with an identical request body.')


class PreviewDebtor(_Input):
    type: Literal["Company", "Private"] = Field(..., description='Debtor type. Valid values: "Company" or "Private"')
    countryAlpha2: str = Field(..., min_length=2, max_length=2, description='Country code (ISO 3166-1 alpha-2 format, e.g., "DK", "US", "PL")')
    stateAlpha2: str | None = Field(None, min_length=2, max_length=2, description='US state code (e.g., "CA", "NY")')


class PreviewCaseBody(_ClaimInput):
    amountToRecover: float | None = Field(None, description='The TOTAL amount to recover for this case.')
    currencyCode: str = Field(..., min_length=3, max_length=3, description='ISO 4217 currency code for the amount (e.g., "DKK", "EUR", "USD")')
    debtor: PreviewDebtor = Field(...)
    amountToRecoverOver6Months: float | None = Field(None, description='OPTIONAL - MULTI-INVOICE AGE BUCKET PRICING (PRICING ZONE 180-DAY THRESHOLD)')
    amountToRecoverOver12Months: float | None = Field(None, description='OPTIONAL - MULTI-INVOICE AGE BUCKET PRICING')
    amountToRecoverOver24Months: float | None = Field(None, description='OPTIONAL - MULTI-INVOICE AGE BUCKET PRICING')
    claimLines: list[ClaimLine] | None = Field(None, min_length=1, max_length=1000, description='OPTIONAL - the unpaid invoices making up this claim, one line per invoice, each carrying its')
    dueDate: str | None = Field(None, description='Optional invoice due date. Mutually exclusive with age bucket fields and with ClaimLines.')
    returnUrl: str | None = Field(None, max_length=2048, description='Optional: URL the creditor user should land on after completing any')


class DebituraPreviewCaseConfig(PreviewCaseBody):
    """Preview case eligibility and requirements."""
    operation: Literal["preview_case"] = Field("preview_case", json_schema_extra={"ui:hidden": True})


class DebituraGetCaseConfig(_Input):
    """Fetch case by ID."""
    operation: Literal["get_case"] = Field("get_case", json_schema_extra={"ui:hidden": True})
    case_id: UUID = Field(...)


class DebituraGetCaseByCreditorReferenceConfig(_Input):
    """Fetch case by creditor reference."""
    operation: Literal["get_case_by_creditor_reference"] = Field("get_case_by_creditor_reference", json_schema_extra={"ui:hidden": True})
    creditor_reference: str = Field(..., min_length=1, max_length=50)


class DebituraGetCaseTimelineConfig(_Input):
    """Fetch case timeline."""
    operation: Literal["get_case_timeline"] = Field("get_case_timeline", json_schema_extra={"ui:hidden": True})
    case_id: UUID = Field(...)


class DebituraListCaseChatsConfig(_Input):
    """Fetch case chats."""
    operation: Literal["list_case_chats"] = Field("list_case_chats", json_schema_extra={"ui:hidden": True})
    case_id: UUID = Field(...)


class ChatBody(_Input):
    message: str = Field(..., min_length=1, max_length=10000, description='The chat message content to send.')
    userId: UUID | None = Field(None, description='ID of the team member sending this message.')
    userEmail: EmailStr | None = Field(None, description='Email address of the team member sending this message.')

    @model_validator(mode="after")
    def sender(self):
        if not self.userEmail and not self.userId:
            raise ValueError("Provide a team member userEmail or userId from List Users")
        return self


class DebituraSendCaseChatConfig(ChatBody):
    """Send a chat message."""
    operation: Literal["send_case_chat"] = Field("send_case_chat", json_schema_extra={"ui:hidden": True})
    case_id: UUID = Field(...)


class DebituraListCasePaymentsConfig(_Input):
    """Fetch case payments."""
    operation: Literal["list_case_payments"] = Field("list_case_payments", json_schema_extra={"ui:hidden": True})
    case_id: UUID = Field(...)


class DebituraListCaseTasksConfig(_Input):
    """List tasks for a case."""
    operation: Literal["list_case_tasks"] = Field("list_case_tasks", json_schema_extra={"ui:hidden": True})
    case_id: UUID = Field(...)
    status: str | None = Field('Open')
    task_types: list[str] | None = Field(None)


class DebituraListCaseFilesConfig(_Input):
    """Get case files."""
    operation: Literal["list_case_files"] = Field("list_case_files", json_schema_extra={"ui:hidden": True})
    case_id: UUID = Field(...)


class DebituraGetContractStatusConfig(_Input):
    """Get debt collection contract status."""
    operation: Literal["get_contract_status"] = Field("get_contract_status", json_schema_extra={"ui:hidden": True})


class DebituraListCoverageConfig(_Input):
    """List all jurisdiction coverage."""
    operation: Literal["list_coverage"] = Field("list_coverage", json_schema_extra={"ui:hidden": True})


class EligibilityBody(_Input):
    countryAlpha2: str = Field(..., min_length=1, description='Debtor country (2-letter ISO code, e.g., "DK", "US", "DE")')
    stateAlpha2: str | None = Field(None, description='US state code for US debtors (e.g., "CA", "NY"). Required if CountryAlpha2 = "US"')
    debtorType: str = Field(..., min_length=1, description='Debtor type: "Company" or "Private"')
    amount: float = Field(..., ge=0.01, le=1.7976931348623157e+308, description='Amount to recover in specified currency')
    currencyCode: str = Field(..., min_length=1, description='Currency code (e.g., "USD", "EUR", "DKK")')


class DebituraCheckEligibilityConfig(EligibilityBody):
    """Check case eligibility and get assigned partner."""
    operation: Literal["check_eligibility"] = Field("check_eligibility", json_schema_extra={"ui:hidden": True})


class DebituraListDivisionsConfig(_Input):
    """List divisions for the authenticated creditor."""
    operation: Literal["list_divisions"] = Field("list_divisions", json_schema_extra={"ui:hidden": True})
    page: int | None = Field(1, ge=1)
    page_size: int | None = Field(10, ge=1, le=100)
    include_archived: bool | None = Field(False)


class DebituraGetDivisionConfig(_Input):
    """Get a single division by ID."""
    operation: Literal["get_division"] = Field("get_division", json_schema_extra={"ui:hidden": True})
    division_id: UUID = Field(...)


class DivisionBody(_Input):
    companyName: str = Field(..., min_length=0, max_length=200)
    registrationNumber: str | None = Field(None, min_length=0, max_length=50)
    address: str | None = Field(None)
    zipCode: str | None = Field(None, min_length=0, max_length=50)
    state: str | None = Field(None)
    city: str = Field(..., min_length=1)
    countryCode: str = Field(..., min_length=2, max_length=2)
    officeEmail: EmailStr | None = Field(None, min_length=0, max_length=250)
    officePhone: str | None = Field(None, min_length=0, max_length=50)


class DebituraCreateDivisionConfig(DivisionBody):
    """Create a new division."""
    operation: Literal["create_division"] = Field("create_division", json_schema_extra={"ui:hidden": True})
    idempotency_key: str | None = Field(None, min_length=1, max_length=255, description='Optional retry key. Reuse only with an identical request body.')


class DivisionUpdateBody(DivisionBody):
    """PUT replaces all fields; omitted optional fields are cleared by Debitura."""


class DebituraUpdateDivisionConfig(DivisionUpdateBody):
    """Update a division."""
    operation: Literal["update_division"] = Field("update_division", json_schema_extra={"ui:hidden": True})
    division_id: UUID = Field(...)


class DebituraArchiveDivisionConfig(_Input):
    """Archive a division."""
    operation: Literal["archive_division"] = Field("archive_division", json_schema_extra={"ui:hidden": True})
    division_id: UUID = Field(...)


class DebituraListPaymentsConfig(_Input):
    """List payments."""
    operation: Literal["list_payments"] = Field("list_payments", json_schema_extra={"ui:hidden": True})
    page: int | None = Field(1, ge=1)
    page_size: int | None = Field(10, ge=1, le=100)


class DebituraGetPaymentConfig(_Input):
    """Fetch payment by ID."""
    operation: Literal["get_payment"] = Field("get_payment", json_schema_extra={"ui:hidden": True})
    payment_id: UUID = Field(...)


class DebituraListTasksConfig(_Input):
    """List your open tasks."""
    operation: Literal["list_tasks"] = Field("list_tasks", json_schema_extra={"ui:hidden": True})
    status: str | None = Field('Open')
    task_types: list[str] | None = Field(None)
    page: int | None = Field(1, ge=1)
    page_size: int | None = Field(10, ge=1, le=100)


class DebituraListUsersConfig(_Input):
    """Lists team members belonging to the authenticated creditor."""
    operation: Literal["list_users"] = Field("list_users", json_schema_extra={"ui:hidden": True})
    page: int | None = Field(1, ge=1)
    page_size: int | None = Field(10, ge=1, le=100)


DebituraOperation = Annotated[Union[
    DebituraGetMeConfig,
    DebituraListCasesConfig,
    DebituraCreateCaseConfig,
    DebituraPreviewCaseConfig,
    DebituraGetCaseConfig,
    DebituraGetCaseByCreditorReferenceConfig,
    DebituraGetCaseTimelineConfig,
    DebituraListCaseChatsConfig,
    DebituraSendCaseChatConfig,
    DebituraListCasePaymentsConfig,
    DebituraListCaseTasksConfig,
    DebituraListCaseFilesConfig,
    DebituraGetContractStatusConfig,
    DebituraListCoverageConfig,
    DebituraCheckEligibilityConfig,
    DebituraListDivisionsConfig,
    DebituraGetDivisionConfig,
    DebituraCreateDivisionConfig,
    DebituraUpdateDivisionConfig,
    DebituraArchiveDivisionConfig,
    DebituraListPaymentsConfig,
    DebituraGetPaymentConfig,
    DebituraListTasksConfig,
    DebituraListUsersConfig
], Field(discriminator="operation")]


class DebituraFullConfig(NodeConfig[DebituraOperation, DebituraAPIKeyCredential]):
    pass


# Fixed contract routes; inputs can never change the API origin or method.
ROUTES = {
    'get_me': {'method': 'GET', 'path': '/me', 'path_fields': {}, 'query': {}, 'headers': {}, 'body': [], 'array': False, 'statuses': [200]},
    'list_cases': {'method': 'GET', 'path': '/cases', 'path_fields': {}, 'query': {'page': 'Page', 'page_size': 'PageSize', 'debtor_ids': 'DebtorIds', 'ids': 'Ids', 'statuses': 'Statuses', 'division_ids': 'DivisionIds', 'sort': 'Sort'}, 'headers': {}, 'body': [], 'array': False, 'statuses': [200]},
    'create_case': {'method': 'POST', 'path': '/cases', 'path_fields': {}, 'query': {}, 'headers': {'idempotency_key': 'Idempotency-Key'}, 'body': ['currencyCode', 'date', 'dueDate', 'comments', 'claimDescription', 'creditorReference', 'debtor', 'creditorDivisionId', 'amountToRecover', 'amountToRecoverOver6Months', 'amountToRecoverOver12Months', 'amountToRecoverOver24Months', 'claimLines', 'allowPendingContracts', 'isTest', 'tag', 'assignedUserEmail', 'returnUrl'], 'array': False, 'statuses': [200]},
    'preview_case': {'method': 'POST', 'path': '/cases/preview', 'path_fields': {}, 'query': {}, 'headers': {}, 'body': ['amountToRecover', 'currencyCode', 'debtor', 'amountToRecoverOver6Months', 'amountToRecoverOver12Months', 'amountToRecoverOver24Months', 'claimLines', 'dueDate', 'returnUrl'], 'array': False, 'statuses': [200]},
    'get_case': {'method': 'GET', 'path': '/cases/{id}', 'path_fields': {'case_id': 'id'}, 'query': {}, 'headers': {}, 'body': [], 'array': False, 'statuses': [200]},
    'get_case_by_creditor_reference': {'method': 'GET', 'path': '/cases/by-creditor-reference/{creditorReference}', 'path_fields': {'creditor_reference': 'creditorReference'}, 'query': {}, 'headers': {}, 'body': [], 'array': False, 'statuses': [200]},
    'get_case_timeline': {'method': 'GET', 'path': '/cases/{id}/timeline', 'path_fields': {'case_id': 'id'}, 'query': {}, 'headers': {}, 'body': [], 'array': False, 'statuses': [200]},
    'list_case_chats': {'method': 'GET', 'path': '/cases/{id}/chats', 'path_fields': {'case_id': 'id'}, 'query': {}, 'headers': {}, 'body': [], 'array': True, 'statuses': [200]},
    'send_case_chat': {'method': 'POST', 'path': '/cases/{id}/chats', 'path_fields': {'case_id': 'id'}, 'query': {}, 'headers': {}, 'body': ['message', 'userId', 'userEmail'], 'array': False, 'statuses': [200]},
    'list_case_payments': {'method': 'GET', 'path': '/cases/{id}/payments', 'path_fields': {'case_id': 'id'}, 'query': {}, 'headers': {}, 'body': [], 'array': True, 'statuses': [200]},
    'list_case_tasks': {'method': 'GET', 'path': '/cases/{id}/tasks', 'path_fields': {'case_id': 'id'}, 'query': {'status': 'status', 'task_types': 'type'}, 'headers': {}, 'body': [], 'array': True, 'statuses': [200]},
    'list_case_files': {'method': 'GET', 'path': '/cases/{id}/files', 'path_fields': {'case_id': 'id'}, 'query': {}, 'headers': {}, 'body': [], 'array': True, 'statuses': [200]},
    'get_contract_status': {'method': 'GET', 'path': '/contracts/debt-collection/status', 'path_fields': {}, 'query': {}, 'headers': {}, 'body': [], 'array': False, 'statuses': [200]},
    'list_coverage': {'method': 'GET', 'path': '/coverage', 'path_fields': {}, 'query': {}, 'headers': {}, 'body': [], 'array': True, 'statuses': [200]},
    'check_eligibility': {'method': 'POST', 'path': '/coverage/check-eligibility', 'path_fields': {}, 'query': {}, 'headers': {}, 'body': ['countryAlpha2', 'stateAlpha2', 'debtorType', 'amount', 'currencyCode'], 'array': False, 'statuses': [200]},
    'list_divisions': {'method': 'GET', 'path': '/divisions', 'path_fields': {}, 'query': {'page': 'page', 'page_size': 'pageSize', 'include_archived': 'includeArchived'}, 'headers': {}, 'body': [], 'array': False, 'statuses': [200]},
    'get_division': {'method': 'GET', 'path': '/divisions/{id}', 'path_fields': {'division_id': 'id'}, 'query': {}, 'headers': {}, 'body': [], 'array': False, 'statuses': [200]},
    'create_division': {'method': 'POST', 'path': '/divisions', 'path_fields': {}, 'query': {}, 'headers': {'idempotency_key': 'Idempotency-Key'}, 'body': ['companyName', 'registrationNumber', 'address', 'zipCode', 'state', 'city', 'countryCode', 'officeEmail', 'officePhone'], 'array': False, 'statuses': [201]},
    'update_division': {'method': 'PUT', 'path': '/divisions/{id}', 'path_fields': {'division_id': 'id'}, 'query': {}, 'headers': {}, 'body': ['companyName', 'registrationNumber', 'address', 'zipCode', 'state', 'city', 'countryCode', 'officeEmail', 'officePhone'], 'array': False, 'statuses': [200]},
    'archive_division': {'method': 'POST', 'path': '/divisions/{id}/archive', 'path_fields': {'division_id': 'id'}, 'query': {}, 'headers': {}, 'body': [], 'array': False, 'statuses': [200]},
    'list_payments': {'method': 'GET', 'path': '/Payments', 'path_fields': {}, 'query': {'page': 'Page', 'page_size': 'PageSize'}, 'headers': {}, 'body': [], 'array': False, 'statuses': [200]},
    'get_payment': {'method': 'GET', 'path': '/Payments/{id}', 'path_fields': {'payment_id': 'id'}, 'query': {}, 'headers': {}, 'body': [], 'array': False, 'statuses': [200]},
    'list_tasks': {'method': 'GET', 'path': '/tasks', 'path_fields': {}, 'query': {'status': 'status', 'task_types': 'type', 'page': 'Page', 'page_size': 'PageSize'}, 'headers': {}, 'body': [], 'array': False, 'statuses': [200]},
    'list_users': {'method': 'GET', 'path': '/users', 'path_fields': {}, 'query': {'page': 'Page', 'page_size': 'PageSize'}, 'headers': {}, 'body': [], 'array': False, 'statuses': [200]},
}


class DebituraNode(WorkflowNode):
    integration_type = "automation-debitura"
    connection_evidence = ConnectionEvidence(
        noun="creditor profile", identity_operation="get_me", identity_keys=("companyName", "officeEmail", "id"),
    )

    @classmethod
    def get_config_model(cls):
        return DebituraFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Debitura API key")
        config = self.config.config
        route = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        path = route["path"]
        for field, placeholder in route["path_fields"].items():
            value = str(values[field])
            if value in {".", ".."} or any(ord(c) < 32 for c in value):
                raise ValueError("Use a valid resource reference")
            path = path.replace("{" + placeholder + "}", quote(value, safe=""))
        params = []
        for field, wire in route["query"].items():
            value = values.get(field)
            if value is None:
                continue
            for item in value if isinstance(value, list) else [value]:
                params.append((wire, str(item).lower() if isinstance(item, bool) else str(item)))
        headers = {"XApiKey": self.config.credentials.api_key, "Accept": "application/json"}
        for field, wire in route["headers"].items():
            if values.get(field) is not None:
                if not values[field].strip() or any(ord(c) < 32 or ord(c) == 127 for c in values[field]):
                    raise ValueError("Use a nonempty idempotency key without control characters")
                headers[wire] = values[field]
        kwargs = {"params": params, "headers": headers}
        if route["body"]:
            kwargs["json"] = {key: values[key] for key in route["body"] if key in values}
        # No automatic mutation retries: callers can use the documented idempotency key.
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(route["method"], BASE_URL + path, **kwargs)
        except httpx.HTTPError:
            return {"status": "error", "error": "Debitura request could not be completed; inspect the case before retrying a write"}
        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError):
            data = None
        if response.status_code not in route["statuses"]:
            # Keep provider rejection wording for the connect seam, redacting the supplied secret.
            message = json.dumps(data, ensure_ascii=False) if data is not None else response.text
            message = message.replace(self.config.credentials.api_key, "[redacted]")[:4000]
            return {"status": "error", "http_status": response.status_code, "error": message or "Debitura rejected the request"}
        if not isinstance(data, list if route["array"] else dict):
            return {"status": "error", "http_status": response.status_code, "error": "Debitura returned an unexpected response shape"}
        if config.operation == "get_me" and ("companyName" not in data or not data.get("id")):
            return {"status": "error", "http_status": response.status_code, "error": "Debitura returned an incomplete creditor profile"}
        if isinstance(data, dict) and any(data.get(key) for key in ("error", "errors", "businessErrors", "validationErrors")):
            return {"status": "error", "http_status": response.status_code, "error": json.dumps(data).replace(self.config.credentials.api_key, "[redacted]")[:4000]}
        return {"status": "success", "http_status": response.status_code, "data": data}
