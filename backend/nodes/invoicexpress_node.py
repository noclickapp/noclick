"""InvoiceXpress v2: typed invoice, client, item and payment actions.

Contract: https://docs.invoicexpress.com/_bundle/@v2/index.json?download (2.0.0).
Document dates are accounting dates, not creation/update cursors; no trigger is
claimed without a documented timestamp filter or webhook registration API.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class InvoiceXpressCredential(BaseModel):
    model_config = ConfigDict(title="InvoiceXpress API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.app.invoicexpress.com/users/api",
            "x-credential-instructions": "Copy your account name and API key from InvoiceXpress Settings → API. Enter only the account subdomain, without https:// or .app.invoicexpress.com.",
        })
    credential_type: Literal["invoicexpress_api_key"] = Field("invoicexpress_api_key", json_schema_extra={"ui:hidden": True})
    account_name: str = Field(..., title="Account name", min_length=1, max_length=63, pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$", description="The account subdomain in https://ACCOUNT_NAME.app.invoicexpress.com.")
    api_key: str = Field(..., title="API key", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("account_name", mode="before")
    @classmethod
    def account(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        return clean_secret(value, field_name="API key")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)

class ClientInputPreferredContact(_Input):
    name: str | None = Field(None, max_length=255, description='Contact-level name has no length validation, unlike the client-level `name` (max 100); the limit shown is the database default.', examples=['Bruce Norris'])
    email: str | None = Field(None, max_length=255, description='Contact-level email allows one character more than the client-level `email` (max 254).', examples=['email@invoicexpress.com'])
    phone: str | None = Field(None, max_length=255, description='Contact-level phone has no length validation, unlike the client-level `phone` (max 20); the limit shown is the database default.', examples=['213456789'])


class ClientInput(_Input):
    name: str = Field(..., max_length=100, examples=['Client Name'])
    code: str = Field(..., max_length=255, description='Maximum length is the database default, not an enforced business rule.', examples=['12345'])
    email: str | None = Field(None, max_length=254, examples=['foo@bar.com'])
    language: Literal['en', 'pt', 'es'] | None = Field(None, examples=['pt'])
    address: str | None = Field(None, description='No enforced character limit (text column).', examples=['Avenida da República, Lisboa'])
    city: str | None = Field(None, max_length=255, description='Maximum length is the database default, not an enforced business rule.', examples=['Lisboa'])
    postal_code: str | None = Field(None, max_length=255, description='Maximum length is the database default, not an enforced business rule.', examples=['1050-555'])
    country: str | None = Field(None, max_length=255, description='Maximum length is the database default, not an enforced business rule.', examples=['Portugal'])
    fiscal_id: str | None = Field(None, max_length=255, description='Maximum length is the database default, not an enforced business rule.', examples=['508025338'])
    website: str | None = Field(None, max_length=60, examples=['www.invoicexpress.com'])
    phone: str | None = Field(None, max_length=20, examples=['213456789'])
    fax: str | None = Field(None, max_length=20, examples=['213456788'])
    preferred_contact: ClientInputPreferredContact | None = Field(None, description='The preferred contact details.')
    observations: str | None = Field(None, description='No enforced character limit (text column).', examples=['Observations'])
    send_options: Literal['1', '2', '3'] | None = Field(None, examples=['1'])


class ItemInputTax(_Input):
    name: str | None = Field(None, examples=['IVA23'])


class ItemInput(_Input):
    name: str = Field(..., max_length=60, description='Item name. Values longer than 60 characters are rejected with HTTP 422 — they are not truncated.', examples=['Item name'])
    description: str | None = Field(None, max_length=200, description='Item description. Values longer than 200 characters are rejected with HTTP 422 — they are not truncated.', examples=['Item description'])
    unit_price: float = Field(..., examples=[9.99])
    unit: str | None = Field(None, description='One of: `hour`, `day`, `month`, `unit`, `service`, `tax`, `other`, `product`, `article`.', examples=['service'])
    tax: ItemInputTax | None = Field(None)


class DocumentClientRequest(_Input):
    id: int | None = Field(None, description='Internal client ID. Preferred way to identify an existing client — see schema description.', examples=[1310176])
    name: str | None = Field(None, max_length=100, examples=['Client A'])
    code: str | None = Field(None, max_length=255, description='Maximum length is the database default, not a business rule.', examples=['CLI-001'])
    email: str | None = Field(None, max_length=254, examples=['client@mail.com'])
    address: str | None = Field(None, description='No enforced character limit.', examples=['Street A'])
    city: str | None = Field(None, max_length=255, description='Maximum length is the database default, not a business rule.', examples=['Lisbon'])
    postal_code: str | None = Field(None, max_length=255, description='Maximum length is the database default, not a business rule.', examples=['1000-100'])
    fiscal_id: str | None = Field(None, max_length=255, description='Maximum length is the database default, not a business rule.', examples=['500999888'])
    country: str | None = Field(None, max_length=255, description='Maximum length is the database default, not a business rule.', examples=['Portugal'])
    website: str | None = Field(None, max_length=60, examples=['www.client-a.com'])
    phone: str | None = Field(None, max_length=20, examples=['912345678'])
    fax: str | None = Field(None, max_length=20, examples=['212345678'])
    observations: str | None = Field(None, description='No enforced character limit.', examples=['VIP Client'])


class InvoiceTaxRequest(_Input):
    name: str | None = Field(None, max_length=255, description='Maximum length is the database default, not a business rule.', examples=['IVA23'])
    value: float | None = Field(None, description='Tax rate (%). Alternative to `name`.', examples=[23])


class InvoiceItemRequest(_Input):
    name: str = Field(..., max_length=60, description='Maximum 60 characters. The V2 API silently truncates longer values to 60; the V3 API rejects them with 422.', examples=['Consulting'])
    description: str | None = Field(None, max_length=200, description='Maximum 200 characters and 20 lines. The V2 API silently truncates longer values to 200; the V3 API rejects them with 422.', examples=['IT Services'])
    unit_price: float = Field(..., examples=[50])
    quantity: float = Field(..., examples=[2])
    unit: str | None = Field(None, description='Not a length limit — constrained to a fixed set of unit values.', examples=['hour'])
    discount: float | None = Field(None, examples=[0])
    tax: InvoiceTaxRequest | None = Field(None)
    retention: float | None = Field(None, description='Item retention rate (%).', examples=[25])


class GlobalDiscountRequest(_Input):
    value_type: Literal['percentage', 'absolute'] | None = Field(None, examples=['percentage'])
    value: float | None = Field(None, examples=[10])


class InvoiceInputRawOwnerInvoice1(_Input):
    document_type: str | None = Field(None, examples=['FT'])
    document_serie: str | None = Field(None, examples=['A'])
    document_number: str | None = Field(None, examples=['123'])


class InvoiceInput(_Input):
    date: str | None = Field(None, description='dd/mm/yyyy', examples=['22/11/2025'])
    due_date: str | None = Field(None, description='dd/mm/yyyy. Defaults to `date` when omitted.', examples=['22/12/2025'])
    reference: str | None = Field(None, max_length=255, examples=['PO-999'])
    observations: str | None = Field(None, description='No enforced character limit.', examples=['Services rendered'])
    retention: str | None = Field(None, examples=['0'])
    tax_exemption: str | None = Field(None, max_length=255, description='Maximum length is the database default, not a business rule — the value is effectively an AT exemption code.', examples=['M00'])
    sequence_id: str | None = Field(None, examples=['123456'])
    manual_sequence_number: str | None = Field(None, max_length=255, description='Maximum length is the database default, not a business rule.')
    client: DocumentClientRequest | None = Field(None)
    items: list[InvoiceItemRequest] | None = Field(None)
    mb_reference: Literal['0', '1'] | None = Field(None, examples=['1'])
    owner_invoice_id: int | None = Field(None, examples=[1049])
    tax_exemption_reason: str | None = Field(None, max_length=210, description='Maximum 210 characters. Enforced by model validation — longer values are rejected with 422 even though the underlying column would accept more.', examples=['M00'])
    currency_code: str | None = Field(None, examples=['USD'])
    rate: str | None = Field(None, examples=['1.10'])
    plugin_id: str | None = Field(None, examples=['plugin_123'])
    global_discount: GlobalDiscountRequest | None = Field(None)
    proprietary_uid: str | None = Field(None, description='Idempotency key, same as the top-level `proprietary_uid`.', examples=['uuid-123'])
    tax_exemption_code: str | None = Field(None, description='Tax exemption code.', examples=['M07'])
    tax_exemption_message: str | None = Field(None, description='Tax exemption message.', examples=['Isento artigo 9.º do CIVA'])
    discount: float | None = Field(None, description='Document discount.', examples=[0])
    raw_owner_invoice: str | InvoiceInputRawOwnerInvoice1 | None = Field(None, description='Credit and debit notes only. Reference to an original document issued outside InvoiceXpress. Send a string, or an object with `document_type`, `document_serie` and `document_number`. Cannot be combined with `owner_invoice_id`.')


class EmailInputClient(_Input):
    email: str = Field(..., examples=['dest@mail.com'])
    save: Literal['0', '1'] = Field(..., examples=['1'])


class EmailInput(_Input):
    client: EmailInputClient = Field(...)
    subject: str | None = Field(None, examples=['Invoice'])
    body: str | None = Field(None, examples=['Attached.'])
    cc: str | None = Field(None, examples=['cc@mail.com'])
    bcc: str | None = Field(None, examples=['bcc@mail.com'])
    logo: Literal['0', '1'] | None = Field(None, examples=['1'])


class PaymentInput(_Input):
    amount: float = Field(..., examples=[10])
    payment_mechanism: Literal['TB', 'MB', 'CC'] | None = Field(None, examples=['TB'])
    note: str | None = Field(None, description="Stored in full on the receipt (observations). The copy on the client's treasury movement is truncated to 255 characters.", examples=['Transfer'])
    serie: str | None = Field(None)
    payment_date: str | None = Field(None, examples=['22/11/2025'])


class StateInput(_Input):
    state: Literal['finalized', 'deleted', 'canceled', 'settled', 'unsettled'] = Field(..., examples=['finalized'])
    message: str | None = Field(None, description='Cancellation reason. Required when `state` is `canceled`, otherwise the request fails with 422 `The cancellation reason is a required field`. No enforced character limit. English text shown; the message follows the account language.', examples=['Wrong value'])


class CreateInvoiceInput(InvoiceInput):
    date: str = Field(..., title="Invoice date", examples=["22/11/2025"], description="dd/mm/yyyy")
    items: list[InvoiceItemRequest] = Field(..., min_length=1)


class UpdateInvoiceInput(InvoiceInput):
    items: list[InvoiceItemRequest] = Field(..., min_length=1, description="Replaces the complete invoice items list.")


class _Page(_Input):
    page: int = Field(1, ge=1, title="Page")
    per_page: int = Field(30, ge=1, le=100, title="Results per page")


class _InvoiceId(_Input):
    document_id: int = Field(..., ge=1, title="Invoice ID", examples=[1050])


class _ClientId(_Input):
    client_id: int = Field(..., ge=1, title="Client ID", examples=[12345])


class _ItemId(_Input):
    item_id: int = Field(..., ge=1, title="Item ID", examples=[12345])


class ListInvoicesConfig(_Page):
    operation: Literal['list_invoices'] = Field('list_invoices', title='List Invoices', json_schema_extra={"ui:hidden": True})
    reference: str | None = Field(None, title="Reference")
    text: str | None = Field(None, title="Client or document text")


class GetInvoiceConfig(_InvoiceId):
    operation: Literal['get_invoice'] = Field('get_invoice', title='Get Invoice', json_schema_extra={"ui:hidden": True})


class CreateInvoiceConfig(_Input):
    operation: Literal['create_invoice'] = Field('create_invoice', title='Create Invoice', json_schema_extra={"ui:hidden": True})
    invoice: CreateInvoiceInput = Field(..., title='Invoice')


class UpdateInvoiceConfig(_InvoiceId):
    operation: Literal['update_invoice'] = Field('update_invoice', title='Update Invoice', json_schema_extra={"ui:hidden": True})
    invoice: UpdateInvoiceInput = Field(..., title='Invoice')


class ChangeInvoiceStateConfig(_InvoiceId):
    operation: Literal['change_invoice_state'] = Field('change_invoice_state', title='Change Invoice State', json_schema_extra={"ui:hidden": True})
    invoice: StateInput = Field(..., title='Invoice')


class SendInvoiceEmailConfig(_InvoiceId):
    operation: Literal['send_invoice_email'] = Field('send_invoice_email', title='Send Invoice Email', json_schema_extra={"ui:hidden": True})
    message: EmailInput = Field(..., title='Message')


class GeneratePdfConfig(_InvoiceId):
    operation: Literal['generate_pdf'] = Field('generate_pdf', title='Generate Document PDF', json_schema_extra={"ui:hidden": True})
    second_copy: bool = Field(False, title="Second copy", description="A 202 response means the PDF is still generating; request it again later.")


class GeneratePaymentConfig(_InvoiceId):
    operation: Literal['generate_payment'] = Field('generate_payment', title='Record Invoice Payment', json_schema_extra={"ui:hidden": True})
    partial_payment: PaymentInput = Field(..., title='Partial Payment')


class GetRelatedDocumentsConfig(_InvoiceId):
    operation: Literal['get_related_documents'] = Field('get_related_documents', title='Get Related Documents', json_schema_extra={"ui:hidden": True})


class ListClientsConfig(_Page):
    operation: Literal['list_clients'] = Field('list_clients', title='List Clients', json_schema_extra={"ui:hidden": True})


class GetClientConfig(_ClientId):
    operation: Literal['get_client'] = Field('get_client', title='Get Client', json_schema_extra={"ui:hidden": True})


class CreateClientConfig(_Input):
    operation: Literal['create_client'] = Field('create_client', title='Create Client', json_schema_extra={"ui:hidden": True})
    client: ClientInput = Field(..., title='Client')


class UpdateClientConfig(_ClientId):
    operation: Literal['update_client'] = Field('update_client', title='Update Client', json_schema_extra={"ui:hidden": True})
    client: ClientInput = Field(..., title='Client')


class FindClientByNameConfig(_Input):
    operation: Literal['find_client_by_name'] = Field('find_client_by_name', title='Find Client by Exact Name', json_schema_extra={"ui:hidden": True})
    client_name: str = Field(..., title='Client Name')


class FindClientByCodeConfig(_Input):
    operation: Literal['find_client_by_code'] = Field('find_client_by_code', title='Find Client by Code', json_schema_extra={"ui:hidden": True})
    client_code: str = Field(..., title='Client Code')


class ListItemsConfig(_Page):
    operation: Literal['list_items'] = Field('list_items', title='List Items', json_schema_extra={"ui:hidden": True})


class GetItemConfig(_ItemId):
    operation: Literal['get_item'] = Field('get_item', title='Get Item', json_schema_extra={"ui:hidden": True})


class CreateItemConfig(_Input):
    operation: Literal['create_item'] = Field('create_item', title='Create Item', json_schema_extra={"ui:hidden": True})
    item: ItemInput = Field(..., title='Item')


class UpdateItemConfig(_ItemId):
    operation: Literal['update_item'] = Field('update_item', title='Update Item', json_schema_extra={"ui:hidden": True})
    item: ItemInput = Field(..., title='Item')


class DeleteItemConfig(_ItemId):
    operation: Literal['delete_item'] = Field('delete_item', title='Delete Item', json_schema_extra={"ui:hidden": True})


class ListTaxesConfig(_Input):
    operation: Literal['list_taxes'] = Field('list_taxes', title='List Taxes', json_schema_extra={"ui:hidden": True})


class ListSequencesConfig(_Input):
    operation: Literal['list_sequences'] = Field('list_sequences', title='List Sequences', json_schema_extra={"ui:hidden": True})

Operation = Annotated[Union[ListInvoicesConfig, GetInvoiceConfig, CreateInvoiceConfig, UpdateInvoiceConfig, ChangeInvoiceStateConfig, SendInvoiceEmailConfig, GeneratePdfConfig, GeneratePaymentConfig, GetRelatedDocumentsConfig, ListClientsConfig, GetClientConfig, CreateClientConfig, UpdateClientConfig, FindClientByNameConfig, FindClientByCodeConfig, ListItemsConfig, GetItemConfig, CreateItemConfig, UpdateItemConfig, DeleteItemConfig, ListTaxesConfig, ListSequencesConfig], Field(discriminator="operation")]


class InvoiceXpressNodeConfig(NodeConfig[Operation, InvoiceXpressCredential]):
    pass


OPERATIONS = {
    'list_invoices': ('GET', '/invoices.json', None, 'invoices'),
    'get_invoice': ('GET', '/invoices/{document_id}.json', None, 'invoice'),
    'create_invoice': ('POST', '/invoices.json', 'invoice', 'invoice'),
    'update_invoice': ('PUT', '/invoices/{document_id}.json', 'invoice', 'invoice'),
    'change_invoice_state': ('PUT', '/invoices/{document_id}/change-state.json', 'invoice', 'invoice'),
    'send_invoice_email': ('PUT', '/invoices/{document_id}/email-document.json', 'message', None),
    'generate_pdf': ('GET', '/api/pdf/{document_id}.json', None, None),
    'generate_payment': ('POST', '/documents/{document_id}/partial_payments.json', 'partial_payment', None),
    'get_related_documents': ('GET', '/document/{document_id}/related_documents.json', None, None),
    'list_clients': ('GET', '/clients.json', None, 'clients'),
    'get_client': ('GET', '/clients/{client_id}.json', None, 'client'),
    'create_client': ('POST', '/clients.json', 'client', 'client'),
    'update_client': ('PUT', '/clients/{client_id}.json', 'client', None),
    'find_client_by_name': ('GET', '/clients/find-by-name.json', None, 'client'),
    'find_client_by_code': ('GET', '/clients/find-by-code.json', None, 'client'),
    'list_items': ('GET', '/items.json', None, 'items'),
    'get_item': ('GET', '/items/{item_id}.json', None, 'item'),
    'create_item': ('POST', '/items.json', 'item', 'item'),
    'update_item': ('PUT', '/items/{item_id}.json', 'item', None),
    'delete_item': ('DELETE', '/items/{item_id}.json', None, None),
    'list_taxes': ('GET', '/taxes.json', None, 'taxes'),
    'list_sequences': ('GET', '/sequences.json', None, 'sequences'),
}


class InvoiceXpressNode(WorkflowNode):
    integration_type = "automation-invoicexpress"
    connection_evidence = ConnectionEvidence(noun="clients", operation="list_clients")

    @classmethod
    def get_config_model(cls):
        return InvoiceXpressNodeConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect your InvoiceXpress account")
        config = self.config.config
        method, path, body_field, response_field = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for key in ("document_id", "client_id", "item_id"):
            if key in values:
                path = path.replace("{" + key + "}", str(values.pop(key)))
        body = {body_field: values.pop(body_field)} if body_field else None
        # Dates are provider-format strings, preserved without timezone conversion.
        if body_field == "invoice" and config.operation in {"create_invoice", "update_invoice"}:
            for key in ("date", "due_date"):
                if key in body["invoice"]:
                    try:
                        datetime.strptime(body["invoice"][key], "%d/%m/%Y")
                    except ValueError:
                        raise ValueError("Invoice dates must use dd/mm/yyyy") from None
        if config.operation == "change_invoice_state" and body["invoice"]["state"] == "canceled" and not body["invoice"].get("message"):
            raise ValueError("A cancellation reason is required")
        params = {"api_key": credential.api_key, **values}
        url = f"https://{credential.account_name}.app.invoicexpress.com{path}"
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, url, params=params,
                    headers={"Accept": "application/json"}, **({"json": body} if body is not None else {}))
        except httpx.HTTPError:
            # httpx exceptions contain the URL, including this provider's query credential.
            raise ValueError("InvoiceXpress request did not complete; check before retrying a write") from None
        if not 200 <= response.status_code < 300:
            # Only the provider's body, never response/request reprs or authenticated URLs.
            message = response.text[:2000].replace(credential.api_key, "[redacted]")
            raise ValueError(f"InvoiceXpress HTTP {response.status_code}: {message}")
        if not response.content:
            if response_field:
                raise ValueError("InvoiceXpress returned an empty read response")
            return {"status": "success", "action": config.operation}
        try:
            data = response.json()
        except ValueError:
            raise ValueError("InvoiceXpress returned a non-JSON response") from None
        if not isinstance(data, dict) or data.get("errors") or data.get("error"):
            raise ValueError("InvoiceXpress returned an invalid or error response")
        if response_field:
            value = data.get(response_field)
            expected = list if config.operation.startswith("list_") else dict
            if not isinstance(value, expected):
                raise ValueError("InvoiceXpress response is missing the requested resource")
        # Preserve provider resource wrappers and pagination; each list returns ONE page.
        return {"status": "success", "action": config.operation, **data}
