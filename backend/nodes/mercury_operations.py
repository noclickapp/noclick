"""Mercury API v1 operation models, transcribed from the pinned 1.0.0 contract.

Wire names intentionally match Mercury. One config always maps to one endpoint;
lists return one page and preserve Mercury's cursors. No automatic write retries.
Contract: https://dash.readme.com/api/v1/api-registry/pd514mw5i9i82
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal, NewType, Union
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


# Keep same-named nullable fields in other operations out of text coercion.
MercuryText = NewType("MercuryText", str)


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class CreateRecipientAddress(_Closed):
    address1: str = Field(..., title='Address1')
    address2: str | None = Field(None, title='Address2')
    city: str = Field(..., title='City')
    postalCode: str = Field(..., title='Postal Code')
    state: Literal['AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'DC', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY'] | None = Field(None, title='State')

class CreateRecipientCheckinfo(_Closed):
    address: CreateRecipientCheckinfoAddress = Field(..., description='Mailing address for sending a physical check.', title='Address')

class CreateRecipientCheckinfoAddress(_Closed):
    address1: str = Field(..., title='Address1')
    address2: str | None = Field(None, title='Address2')
    city: str = Field(..., title='City')
    country: str = Field(..., title='Country')
    postalCode: str = Field(..., title='Postal Code')
    region: str = Field(..., title='Region')

class CreateRecipientDomesticwireroutinginfo(_Closed):
    accountNumber: str = Field(..., description='The account number of the bank account to use for domestic wire payments.', title='Account Number')
    address: CreateRecipientDomesticwireroutinginfoAddress = Field(..., description="The address of the bank account to use for domestic wire payments. This has to be the recipient's legal address.", title='Address')
    routingNumber: str = Field(..., description='The routing number of the bank account to use for domestic wire payments.', title='Routing Number')

class CreateRecipientDomesticwireroutinginfoAddress(_Closed):
    address1: str = Field(..., title='Address1')
    address2: str | None = Field(None, title='Address2')
    city: str = Field(..., title='City')
    country: str = Field(..., title='Country')
    postalCode: str = Field(..., title='Postal Code')
    region: str = Field(..., title='Region')

class CreateRecipientElectronicroutinginfo(_Closed):
    accountNumber: str = Field(..., description='The account number of the bank account to use for ACH payments.', title='Account Number')
    address: CreateRecipientElectronicroutinginfoAddress = Field(..., description="The address of the bank account to use for ACH payments. This has to be the recipient's legal address.", title='Address')
    electronicAccountType: Literal['businessChecking', 'businessSavings', 'personalChecking', 'personalSavings', 'businessGeneralLedger', 'personalGeneralLedger', 'businessLoan', 'personalLoan'] = Field(..., description='The type of bank account to use for ACH payments.', title='Electronic Account Type')
    routingNumber: str = Field(..., description='The routing number of the bank account to use for ACH payments.', title='Routing Number')

class CreateRecipientElectronicroutinginfoAddress(_Closed):
    address1: str = Field(..., title='Address1')
    address2: str | None = Field(None, title='Address2')
    city: str = Field(..., title='City')
    country: str = Field(..., title='Country')
    postalCode: str = Field(..., title='Postal Code')
    region: str = Field(..., title='Region')

class CreateRecipientRealtimepaymentroutinginfo(_Closed):
    accountNumber: str = Field(..., description='The account number of the bank account to use for real-time payments.', title='Account Number')
    address: CreateRecipientRealtimepaymentroutinginfoAddress = Field(..., description='The address of the bank account to use for real-time payments.', title='Address')
    routingNumber: str = Field(..., description='The routing number of the bank account to use for real-time payments.', title='Routing Number')

class CreateRecipientRealtimepaymentroutinginfoAddress(_Closed):
    address1: str = Field(..., title='Address1')
    address2: str | None = Field(None, title='Address2')
    city: str = Field(..., title='City')
    country: str = Field(..., title='Country')
    postalCode: str = Field(..., title='Postal Code')
    region: str = Field(..., title='Region')

class UpdateRecipientAddress(_Closed):
    address1: str = Field(..., title='Address1')
    address2: str | None = Field(None, title='Address2')
    city: str = Field(..., title='City')
    postalCode: str = Field(..., title='Postal Code')
    state: Literal['AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'DC', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY'] | None = Field(None, title='State')

class UpdateRecipientCheckinfo(_Closed):
    address: UpdateRecipientCheckinfoAddress = Field(..., description='Mailing address for sending a physical check.', title='Address')

class UpdateRecipientCheckinfoAddress(_Closed):
    address1: str = Field(..., title='Address1')
    address2: str | None = Field(None, title='Address2')
    city: str = Field(..., title='City')
    country: str = Field(..., title='Country')
    postalCode: str = Field(..., title='Postal Code')
    region: str = Field(..., title='Region')

class UpdateRecipientDomesticwireroutinginfo(_Closed):
    accountNumber: str = Field(..., description='The account number of the bank account to use for domestic wire payments.', title='Account Number')
    address: UpdateRecipientDomesticwireroutinginfoAddress = Field(..., description="The address of the bank account to use for domestic wire payments. This has to be the recipient's legal address.", title='Address')
    routingNumber: str = Field(..., description='The routing number of the bank account to use for domestic wire payments.', title='Routing Number')

class UpdateRecipientDomesticwireroutinginfoAddress(_Closed):
    address1: str = Field(..., title='Address1')
    address2: str | None = Field(None, title='Address2')
    city: str = Field(..., title='City')
    country: str = Field(..., title='Country')
    postalCode: str = Field(..., title='Postal Code')
    region: str = Field(..., title='Region')

class UpdateRecipientElectronicroutinginfo(_Closed):
    accountNumber: str = Field(..., description='The account number of the bank account to use for ACH payments.', title='Account Number')
    address: UpdateRecipientElectronicroutinginfoAddress = Field(..., description="The address of the bank account to use for ACH payments. This has to be the recipient's legal address.", title='Address')
    electronicAccountType: Literal['businessChecking', 'businessSavings', 'personalChecking', 'personalSavings', 'businessGeneralLedger', 'personalGeneralLedger', 'businessLoan', 'personalLoan'] = Field(..., description='The type of bank account to use for ACH payments.', title='Electronic Account Type')
    routingNumber: str = Field(..., description='The routing number of the bank account to use for ACH payments.', title='Routing Number')

class UpdateRecipientElectronicroutinginfoAddress(_Closed):
    address1: str = Field(..., title='Address1')
    address2: str | None = Field(None, title='Address2')
    city: str = Field(..., title='City')
    country: str = Field(..., title='Country')
    postalCode: str = Field(..., title='Postal Code')
    region: str = Field(..., title='Region')

class UpdateRecipientRealtimepaymentroutinginfo(_Closed):
    accountNumber: str = Field(..., description='The account number of the bank account to use for real-time payments.', title='Account Number')
    address: UpdateRecipientRealtimepaymentroutinginfoAddress = Field(..., description='The address of the bank account to use for real-time payments.', title='Address')
    routingNumber: str = Field(..., description='The routing number of the bank account to use for real-time payments.', title='Routing Number')

class UpdateRecipientRealtimepaymentroutinginfoAddress(_Closed):
    address1: str = Field(..., title='Address1')
    address2: str | None = Field(None, title='Address2')
    city: str = Field(..., title='City')
    country: str = Field(..., title='Country')
    postalCode: str = Field(..., title='Postal Code')
    region: str = Field(..., title='Region')

class SendMoneyPurpose(_Closed):
    simple: SendMoneyPurposeSimple | None = Field(None, title='Simple')

class SendMoneyPurposeSimple(_Closed):
    additionalInfo: str = Field(None, description='Additional information. Required for: Vendor (vendor name), Contractor (contractor name), Other (payment description). Optional for Subsidiary (subsidiary name). Not accepted for any other categories.', title='Additional Info')
    category: Literal['employee', 'landlord', 'vendor', 'contractor', 'subsidiary', 'transferToMyExternalAccount', 'familyMemberOrFriend', 'forGoodsOrServices', 'angelInvestment', 'savingsOrInvestments', 'expenses', 'travel', 'other'] = Field(..., description='Payment category.', title='Category')

class CreateCustomerAddress(_Closed):
    address1: str = Field(..., description='Primary street address line.', title='Address1')
    address2: str | None = Field(None, description='Secondary street address line (optional).', title='Address2')
    city: str = Field(..., description='City name.', title='City')
    country: str = Field(..., description='Two-letter country code (ISO 3166-1 alpha-2).', title='Country')
    name: str = Field(..., description='The mailing name of the address.', title='Name')
    postalCode: str = Field(..., description='Postal or ZIP code.', title='Postal Code')
    region: str = Field(..., description='Either a two-letter US state code i.e. "CA" for California or a free-form identification of a particular region worldwide.', title='Region')

class UpdateCustomerAddress(_Closed):
    address1: str = Field(..., description='Primary street address line.', title='Address1')
    address2: str | None = Field(None, description='Secondary street address line (optional).', title='Address2')
    city: str = Field(..., description='City name.', title='City')
    country: str = Field(..., description='Two-letter country code (ISO 3166-1 alpha-2).', title='Country')
    name: str = Field(..., description='The mailing name of the address.', title='Name')
    postalCode: str = Field(..., description='Postal or ZIP code.', title='Postal Code')
    region: str = Field(..., description='Either a two-letter US state code i.e. "CA" for California or a free-form identification of a particular region worldwide.', title='Region')

class CreateInvoiceLineitemsItem(_Closed):
    name: str = Field(..., description='the name of the line item', title='Name')
    quantity: float = Field(..., description='the quantity of this item', title='Quantity')
    salesTaxRate: float | None = Field(None, description='the sales tax applied to this item', title='Sales Tax Rate')
    unitPrice: float = Field(..., description='the price of one unit of the item before sales tax', title='Unit Price', multiple_of=0.01)

class UpdateInvoiceLineitemsItem(_Closed):
    name: str = Field(..., description='the name of the line item', title='Name')
    quantity: float = Field(..., description='the quantity of this item', title='Quantity')
    salesTaxRate: float | None = Field(None, description='the sales tax applied to this item', title='Sales Tax Rate')
    unitPrice: float = Field(..., description='the price of one unit of the item before sales tax', title='Unit Price', multiple_of=0.01)

class ListAccounts(_Closed):
    'Retrieve a paginated list of accounts. Supports cursor-based pagination with limit, order, start_after, and end_before query parameters.'
    limit: int = Field(100, description='Maximum number of results to return. Allowed range: 1 to 1000. Defaults to 1000', title='Limit', ge=1, le=1000)
    order: Literal['asc', 'desc'] = Field('asc', description="Sort order. Can be 'asc' or 'desc'. Defaults to 'asc'", title='Order')
    start_after: UUID | None = Field(None, description='The ID of the account to start the page after (exclusive). When provided, results will begin with the account immediately following this ID. Use this for standard forward pagination to get the next page of results. Cannot be combined with end_before.', title='Start After')
    end_before: UUID | None = Field(None, description='The ID of the account to end the page before (exclusive). When provided, results will end just before this ID and work backwards. Use this for reverse pagination or to retrieve previous pages. Cannot be combined with start_after.', title='End Before')
    operation: Literal['list_accounts'] = Field('list_accounts', title='Get all accounts', json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def one_cursor(self):
        if sum(getattr(self, k, None) is not None for k in ("start_at", "start_after", "end_before")) > 1:
            raise ValueError("Use only one pagination cursor")
        return self

class GetAccount(_Closed):
    'Get account by ID'
    accountId: UUID = Field(..., description='ID for a Mercury account.', title='Account ID')
    operation: Literal['get_account'] = Field('get_account', title='Get account by ID', json_schema_extra={"ui:hidden": True})

class ListTransactions(_Closed):
    'Retrieve a paginated list of all transactions across all accounts. Supports advanced filtering by date ranges, status, categories, and cursor-based pagination.'
    status: list[Literal['pending', 'sent', 'cancelled', 'failed', 'reversed', 'blocked']] | None = Field(None, title='Status')
    search: str | None = Field(None, description='Search term to look for in transaction descriptions, notes, recipient memos, and counterparty names.', title='Search')
    start: str | None = Field(None, description='Earliest createdAt date to filter for. If not provided, it defaults to the date of your first transaction. Format: YYYY-MM-DD or an ISO 8601 string. Please note that your Mercury transactions on your Dashboard might have their postedAt date displayed, as opposed to createdAt', title='Start')
    end: str | None = Field(None, description='Latest createdAt date to filter for. If it’s not provided, it defaults to current day. Format: YYYY-MM-DD or an ISO 8601 string. Please note that your Mercury transactions on your Dashboard might have their postedAt date displayed, as opposed to createdAt', title='End')
    postedStart: str | None = Field(None, description='Earliest postedAt date to filter for. Format: YYYY-MM-DD or an ISO 8601 string', title='Posted Start')
    postedEnd: str | None = Field(None, description='Latest postedAt date to filter for. Format: YYYY-MM-DD or an ISO 8601 string', title='Posted End')
    accountId: list[UUID] | None = Field(None, title='Account ID')
    cardId: list[str] | None = Field(None, title='Card ID')
    mercuryCategory: str | None = Field(None, description='Name of mercuryCategory you want to filter on. Merchant Type in the UI.', title='Mercury Category')
    categoryId: str | None = Field(None, description='UUID of a custom category. Can be returned from /categories endpoint.', title='Category ID')
    start_at: str | None = Field(None, description='The ID of the resource to start the page at (inclusive). When provided, results will begin with and include the resource with this ID. Use this to retrieve a specific page when you know the exact starting point. Cannot be combined with start_after or end_before.', title='Start At')
    start_after: UUID | None = Field(None, description='The ID of the transaction to start the page after (exclusive). When provided, results will begin with the transaction immediately following this ID. Use this for standard forward pagination to get the next page of results. Cannot be combined with end_before.', title='Start After')
    end_before: UUID | None = Field(None, description='The ID of the transaction to end the page before (exclusive). When provided, results will end just before this ID and work backwards. Use this for reverse pagination or to retrieve previous pages. Cannot be combined with start_after.', title='End Before')
    limit: int = Field(100, description='Maximum number of results to return. Allowed range: 1 to 1000. Defaults to 1000', title='Limit', ge=1, le=1000)
    order: Literal['asc', 'desc'] = Field('asc', description="Sort order. Can be 'asc' or 'desc'. Defaults to 'asc'", title='Order')
    operation: Literal['list_transactions'] = Field('list_transactions', title='List all transactions', json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def one_cursor(self):
        if sum(getattr(self, k, None) is not None for k in ("start_at", "start_after", "end_before")) > 1:
            raise ValueError("Use only one pagination cursor")
        return self

class ListAccountTransactions(_Closed):
    'Retrieve a paginated list of transactions for a specific account. Supports filtering by date range, status, and search terms.'
    accountId: UUID = Field(..., description='ID for a Mercury account.', title='Account ID')
    limit: int = Field(100, description='Maximum number of results to return. Allowed range: 1 to 1000. Defaults to 1000', title='Limit', ge=1, le=1000)
    start: str | None = Field(None, description='Earliest date to filter transactions. If not provided, defaults to 30 days before the current date. Format: YYYY-MM-DD or ISO 8601 string', title='Start')
    end: str | None = Field(None, description='Latest date to filter transactions. If not provided, defaults to the current date. Format: YYYY-MM-DD or ISO 8601 string', title='End')
    search: str | None = Field(None, description='Search term to filter transactions by description, note, recipient memo, or counterparty name', title='Search')
    status: Literal['pending', 'sent', 'cancelled', 'failed', 'reversed', 'blocked'] | None = Field(None, title='Status')
    offset: int | None = Field(None, description='Number of results to skip for pagination', title='Offset', ge=0)
    order: Literal['asc', 'desc'] = Field('desc', description="Sort order. Can be 'asc' or 'desc'. Defaults to 'desc'", title='Order')
    requestId: UUID | None = Field(None, description='ID returned from /account/:id/request-send-money', title='Request ID')
    mercuryCategory: str | None = Field(None, description='Name of mercuryCategory you want to filter on. Merchant Type in the UI.', title='Mercury Category')
    categoryId: UUID | None = Field(None, description='UUID of a custom category. Can be returned from /categories endpoint.', title='Category ID')
    operation: Literal['list_account_transactions'] = Field('list_account_transactions', title='List account transactions', json_schema_extra={"ui:hidden": True})

class GetTransaction(_Closed):
    'Retrieve a single transaction by its ID. Returns full transaction details including attachments, check images, and related metadata.'
    transactionId: UUID = Field(..., description='ID for this transaction', title='Transaction ID')
    operation: Literal['get_transaction'] = Field('get_transaction', title='Get a transaction by ID', json_schema_extra={"ui:hidden": True})

class UpdateTransaction(_Closed):
    'Update the note and/or category of an existing transaction. Use null values to clear existing data.'
    transactionId: UUID = Field(..., description='ID for this transaction', title='Transaction ID')
    categoryId: UUID | None = Field(None, description="How to update the transaction's category. Omit field to keep current, send null to clear, send ID to set.", title='Category ID')
    note: str | None = Field(None, description="How to update the transaction's note. Omit field to keep current, send null/empty to clear, send text to set.", title='Note')
    operation: Literal['update_transaction'] = Field('update_transaction', title='Update transaction metadata', json_schema_extra={"ui:hidden": True})

class ListRecipients(_Closed):
    'Retrieve a paginated list of all recipients. Use cursor parameters (start_after, end_before) for pagination.'
    limit: int = Field(100, description='Maximum number of results to return. Allowed range: 1 to 1000. Defaults to 1000', title='Limit', ge=1, le=1000)
    start_after: UUID | None = Field(None, description='The ID of the recipient to start the page after (exclusive). When provided, results will begin with the recipient immediately following this ID. Use this for standard forward pagination to get the next page of results. Cannot be combined with end_before.', title='Start After')
    end_before: UUID | None = Field(None, description='The ID of the recipient to end the page before (exclusive). When provided, results will end just before this ID and work backwards. Use this for reverse pagination or to retrieve previous pages. Cannot be combined with start_after.', title='End Before')
    order: Literal['asc', 'desc'] = Field('asc', description="Sort order. Can be 'asc' or 'desc'. Defaults to 'asc'", title='Order')
    operation: Literal['list_recipients'] = Field('list_recipients', title='Get all recipients', json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def one_cursor(self):
        if sum(getattr(self, k, None) is not None for k in ("start_at", "start_after", "end_before")) > 1:
            raise ValueError("Use only one pagination cursor")
        return self

class GetRecipient(_Closed):
    'Retrieve details of a specific recipient by ID'
    recipientId: UUID = Field(..., description='ID for a Mercury account.', title='Recipient ID')
    operation: Literal['get_recipient'] = Field('get_recipient', title='Get recipient by ID', json_schema_extra={"ui:hidden": True})

class CreateRecipient(_Closed):
    'Create a new recipient for making payments'
    address: CreateRecipientAddress = Field(None, description='Deprecated. Use checkInfo instead.', title='Address')
    checkInfo: CreateRecipientCheckinfo = Field(None, description='Information needed to send a physical check.', title='Check Info')
    contactEmail: str = Field(None, description='Contact email address of the recipient', title='Contact Email')
    domesticWireRoutingInfo: CreateRecipientDomesticwireroutinginfo = Field(None, description='Information needed to send a domestic wire.', title='Domestic Wire Routing Info')
    electronicRoutingInfo: CreateRecipientElectronicroutinginfo = Field(None, description='Information needed to send an ACH.', title='Electronic Routing Info')
    emails: list[str] = Field(..., title='Emails')
    name: str = Field(..., title='Name')
    nickname: str = Field(None, title='Nickname')
    realTimePaymentRoutingInfo: CreateRecipientRealtimepaymentroutinginfo = Field(None, description='Information needed to send a real-time payment.', title='Real Time Payment Routing Info')
    operation: Literal['create_recipient'] = Field('create_recipient', title='Add a new recipient', json_schema_extra={"ui:hidden": True})

class UpdateRecipient(_Closed):
    "Update an existing recipient's information"
    recipientId: UUID = Field(..., description='ID for a Mercury account.', title='Recipient ID')
    address: UpdateRecipientAddress = Field(None, description='Deprecated. Use checkInfo instead.', title='Address')
    checkInfo: UpdateRecipientCheckinfo = Field(None, description='Information needed to send a check.', title='Check Info')
    contactEmail: str = Field(None, description='Contact email address of the recipient', title='Contact Email')
    domesticWireRoutingInfo: UpdateRecipientDomesticwireroutinginfo = Field(None, description='Information needed to send a domestic wire.', title='Domestic Wire Routing Info')
    electronicRoutingInfo: UpdateRecipientElectronicroutinginfo = Field(None, description='Information needed to send an ACH.', title='Electronic Routing Info')
    emails: list[str] = Field(None, title='Emails')
    name: str = Field(None, title='Name')
    nickname: str = Field(None, title='Nickname')
    realTimePaymentRoutingInfo: UpdateRecipientRealtimepaymentroutinginfo = Field(None, description='Information needed to send a real-time payment.', title='Real Time Payment Routing Info')
    operation: Literal['update_recipient'] = Field('update_recipient', title='Edit information about a specific recipient', json_schema_extra={"ui:hidden": True})

class DeleteRecipient(_Closed):
    'Delete a specific recipient by ID. Fails if the recipient is blocked by scheduled payments, pending approvals, or active ACH authorizations.'
    recipientId: UUID = Field(..., description='ID for a Mercury account.', title='Recipient ID')
    operation: Literal['delete_recipient'] = Field('delete_recipient', title='Delete a recipient', json_schema_extra={"ui:hidden": True})

class SendMoney(_Closed):
    'Send money from an account to a recipient. Creates a transaction that will be processed immediately or may require approval.'
    accountId: UUID = Field(..., description='ID for a Mercury account.', title='Account ID')
    amount: float = Field(..., description='Amount of USD you want to send, must be a positive number.', title='Amount', ge=0.01)
    externalMemo: str = Field(None, description='Optional external memo', title='External Memo')
    idempotencyKey: str = Field(..., description='Unique string identifying the transaction', title='Idempotency Key')
    note: MercuryText = Field(None, description='Optional note', title='Note')
    paymentMethod: Literal['ach', 'check', 'domesticWire', 'realTimePayment'] = Field(..., description='If domesticWire is used, then the purpose field is required.', title='Payment Method')
    purpose: SendMoneyPurpose = Field(None, description="Purpose of payment with category and optional additional info. Required when paymentMethod is 'domesticWire'.", title='Purpose')
    recipientId: UUID = Field(..., description='Recipient ID from the /recipients endpoint.', title='Recipient ID')
    operation: Literal['send_money'] = Field('send_money', title='Send money to a recipient', json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def wire_purpose(self):
        if self.paymentMethod == "domesticWire" and self.purpose is None:
            raise ValueError("Domestic wires require a payment purpose")
        return self

class CreateTransfer(_Closed):
    'Transfer funds between two accounts within the same organization. Supports transfers between depository accounts (checking/savings), from a depository account to a treasury/investment account, and from a treasury/investment account to a depository account. Creates paired debit and credit transactions.'
    amount: float = Field(..., description='A positive dollar amount with at least 1 cent.', title='Amount', ge=0.01)
    destinationAccountId: UUID = Field(..., description='ID for a Mercury account.', title='Destination Account ID')
    idempotencyKey: str = Field(..., title='Idempotency Key')
    note: str | None = Field(None, title='Note')
    sourceAccountId: UUID = Field(..., description='ID for a Mercury account.', title='Source Account ID')
    operation: Literal['create_transfer'] = Field('create_transfer', title='Create an internal transfer', json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def different_accounts(self):
        if self.sourceAccountId == self.destinationAccountId:
            raise ValueError("Choose different source and destination accounts")
        return self

class ListCustomers(_Closed):
    'Retrieve a paginated list of customers. Supports cursor-based pagination with limit, order, start_after, and end_before query parameters.'
    limit: int = Field(100, description='Maximum number of results to return. Allowed range: 1 to 1000. Defaults to 1000', title='Limit', ge=1, le=1000)
    start_after: UUID | None = Field(None, description='The ID of the customer to start the page after (exclusive). When provided, results will begin with the customer immediately following this ID. Use this for standard forward pagination to get the next page of results. Cannot be combined with end_before.', title='Start After')
    end_before: UUID | None = Field(None, description='The ID of the customer to end the page before (exclusive). When provided, results will end just before this ID and work backwards. Use this for reverse pagination or to retrieve previous pages. Cannot be combined with start_after.', title='End Before')
    order: Literal['asc', 'desc'] = Field('asc', description="Sort order. Can be 'asc' or 'desc'. Defaults to 'asc'", title='Order')
    operation: Literal['list_customers'] = Field('list_customers', title='List all customers', json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def one_cursor(self):
        if sum(getattr(self, k, None) is not None for k in ("start_at", "start_after", "end_before")) > 1:
            raise ValueError("Use only one pagination cursor")
        return self

class GetCustomer(_Closed):
    'Retrieve details of a specific customer by their ID'
    customerId: UUID = Field(..., description='The customer who will receive the invoice. Use the /api/v1/ar/customers endpoint to list your customers and find the corresponding id, or create a new customer first.', title='Customer ID')
    operation: Literal['get_customer'] = Field('get_customer', title='Get a customer', json_schema_extra={"ui:hidden": True})

class CreateCustomer(_Closed):
    'Create a new customer for the organization'
    address: CreateCustomerAddress | None = Field(None, description='The address for the customer.', title='Address')
    email: str = Field(..., description='The email address for the customer.', title='Email')
    name: str = Field(..., description='The name of the customer.', title='Name')
    operation: Literal['create_customer'] = Field('create_customer', title='Create a customer', json_schema_extra={"ui:hidden": True})

class UpdateCustomer(_Closed):
    'Update an existing customer'
    customerId: UUID = Field(..., description='The customer who will receive the invoice. Use the /api/v1/ar/customers endpoint to list your customers and find the corresponding id, or create a new customer first.', title='Customer ID')
    address: UpdateCustomerAddress | None = Field(None, description='The address for the customer.', title='Address')
    email: str = Field(..., description='The email address for the customer.', title='Email')
    name: str = Field(..., description='The name of the customer.', title='Name')
    resendOpenInvoices: bool = Field(..., description='Open invoices for the customer will be resent with updated data\n when this is true.', title='Resend Open Invoices')
    operation: Literal['update_customer'] = Field('update_customer', title='Update a customer', json_schema_extra={"ui:hidden": True})

class DeleteCustomer(_Closed):
    'Delete a customer. This action cannot be undone.'
    customerId: UUID = Field(..., description='The customer who will receive the invoice. Use the /api/v1/ar/customers endpoint to list your customers and find the corresponding id, or create a new customer first.', title='Customer ID')
    operation: Literal['delete_customer'] = Field('delete_customer', title='Delete a customer', json_schema_extra={"ui:hidden": True})

class ListInvoices(_Closed):
    'Retrieve a paginated list of invoices. Supports cursor-based pagination with limit, order, start_after, and end_before query parameters.'
    limit: int = Field(100, description='Maximum number of results to return. Allowed range: 1 to 1000. Defaults to 1000', title='Limit', ge=1, le=1000)
    order: Literal['asc', 'desc'] = Field('asc', description="Sort order. Can be 'asc' or 'desc'. Defaults to 'asc'", title='Order')
    start_after: UUID | None = Field(None, description='The ID of the invoice to start the page after (exclusive). When provided, results will begin with the invoice immediately following this ID. Use this for standard forward pagination to get the next page of results. Cannot be combined with end_before.', title='Start After')
    end_before: UUID | None = Field(None, description='The ID of the invoice to end the page before (exclusive). When provided, results will end just before this ID and work backwards. Use this for reverse pagination or to retrieve previous pages. Cannot be combined with start_after.', title='End Before')
    operation: Literal['list_invoices'] = Field('list_invoices', title='List all invoices', json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def one_cursor(self):
        if sum(getattr(self, k, None) is not None for k in ("start_at", "start_after", "end_before")) > 1:
            raise ValueError("Use only one pagination cursor")
        return self

class GetInvoice(_Closed):
    'Retrieve details of an invoice by its ID'
    invoiceId: UUID = Field(..., description='ID for the invoice.', title='Invoice ID')
    operation: Literal['get_invoice'] = Field('get_invoice', title='Get an invoice', json_schema_extra={"ui:hidden": True})

class CreateInvoice(_Closed):
    'Create a new invoice for the organization'
    achDebitEnabled: bool = Field(..., description='Whether or not the invoice can be paid via ACH debit.', title='Ach Debit Enabled')
    ccEmails: list[str] = Field(..., description='Emails to be CCed on invoice notifications/reminders.', title='Cc Emails')
    creditCardEnabled: bool = Field(..., description='Whether or not the invoice can be paid via credit card. Requires Stripe to be setup for the Mercury account.', title='Credit Card Enabled')
    currencyCode: str | None = Field(None, description='ISO 4217 currency code for the invoice. Defaults to USD if not provided.', title='Currency Code')
    customerId: UUID = Field(..., description='Id of the customer the invoice was sent to.', title='Customer ID')
    destinationAccountId: UUID = Field(..., description='The Mercury account where invoice payments will be deposited. Use the /api/v1/accounts endpoint to list your accounts and find the corresponding id. Only checking and savings accounts are supported.', title='Destination Account ID')
    dueDate: date = Field(..., description='The due date the invoice should be paid by. YYYY-MM-DD', title='Due Date')
    internalNote: str | None = Field(None, description='Internal note for the invoice, visible by users in the organization but not visible to payers.', title='Internal Note')
    invoiceDate: date = Field(..., description='The date of the invoice, set by the invoice creator and likely to be context specific to the type of transaction. For example, it could be a date a service was performed. YYYY-MM-DD', title='Invoice Date')
    invoiceNumber: str | None = Field(None, description='The payer facing invoice number/identifier.', title='Invoice Number')
    lineItems: list[CreateInvoiceLineitemsItem] = Field(..., description='The line items for the invoice', title='Line Items')
    payerMemo: str | None = Field(None, description='Memo for the payer of the invoice.', title='Payer Memo')
    poNumber: str | None = Field(None, description='Purchase order number for the invoice, if applicable.', title='Po Number')
    sendEmailOption: Literal['DontSend', 'SendNow'] | None = Field('DontSend', description='Rules for emailing the new invoice to payers. Can be "DontSend" to skip sending or "SendNow" to send immediately. If omitted, defaults to sending immediately.', title='Send Email Option')
    servicePeriodEndDate: date | None = Field(None, description='The end date for the service period this invoice covers, if applicable. YYYY-MM-DD', title='Service Period End Date')
    servicePeriodStartDate: date | None = Field(None, description='The start date for the service period this invoice covers, if applicable. YYYY-MM-DD', title='Service Period Start Date')
    useRealAccountNumber: bool = Field(..., description='Whether or not the invoice payment instructions will show the real account and routing number for the destination account or use virtual account numbers instead. Virtual accounts are safer and are preferred in most cases.', title='Use Real Account Number')
    operation: Literal['create_invoice'] = Field('create_invoice', title='Create an invoice', json_schema_extra={"ui:hidden": True})

class UpdateInvoice(_Closed):
    'Update an existing invoice'
    invoiceId: UUID = Field(..., description='ID for the invoice.', title='Invoice ID')
    achDebitEnabled: bool = Field(..., description='Whether or not the invoice can be paid via ACH debit.', title='Ach Debit Enabled')
    ccEmails: list[str] = Field(..., description='List of emails to be CCed on notifications/reminders.', title='Cc Emails')
    creditCardEnabled: bool = Field(..., description='Whether or not the invoice can be paid via credit card. Requires Stripe to be setup for the Mercury account.', title='Credit Card Enabled')
    dueDate: date = Field(..., description='The date the invoice should be paid by. YYYY-MM-DD', title='Due Date')
    internalNote: str | None = Field(None, description='Internal note for the invoice, visible by users in the organization but not visible to payers.', title='Internal Note')
    invoiceDate: date = Field(..., description='The date of the invoice, set by the invoice creator. Does not have to be the day the invoice was created. It can be business specific i.e. service/sale date. YYYY-MM-DD', title='Invoice Date')
    invoiceNumber: MercuryText = Field(..., description='The invoice number.', title='Invoice Number')
    lineItems: list[UpdateInvoiceLineitemsItem] = Field(..., description='The line items for the invoice', title='Line Items')
    payerMemo: str | None = Field(None, description='Memo for the payer of the invoice.', title='Payer Memo')
    poNumber: str | None = Field(None, description='The purchase order number for the invoice if applicable.', title='Po Number')
    servicePeriodEndDate: date | None = Field(None, description='The end date for the service period this invoice covers, if applicable. YYYY-MM-DD', title='Service Period End Date')
    servicePeriodStartDate: date | None = Field(None, description='The start date for the service period this invoice covers, if applicable. YYYY-MM-DD', title='Service Period Start Date')
    useRealAccountNumber: bool = Field(..., description='Whether or not the invoice payment instructions will show the real account and routing number for the destination account or use virtual account numbers instead.', title='Use Real Account Number')
    operation: Literal['update_invoice'] = Field('update_invoice', title='Update an invoice', json_schema_extra={"ui:hidden": True})

class CancelInvoice(_Closed):
    'Cancel an invoice. This action cannot be undone.'
    invoiceId: UUID = Field(..., description='ID for the invoice.', title='Invoice ID')
    operation: Literal['cancel_invoice'] = Field('cancel_invoice', title='Cancel an invoice', json_schema_extra={"ui:hidden": True})

class ListAccountStatements(_Closed):
    'Retrieve a paginated list of monthly statements for a depository account. For IO credit accounts, use getCreditAccountStatements. Supports cursor-based pagination with limit, order, start_after, and end_before query parameters, as well as date range filtering with start and end parameters.'
    accountId: UUID = Field(..., description='ID for a Mercury account.', title='Account ID')
    limit: int = Field(100, description='Maximum number of results to return. Allowed range: 1 to 1000. Defaults to 1000', title='Limit', ge=1, le=1000)
    order: Literal['asc', 'desc'] = Field('desc', description="Sort order. Can be 'asc' or 'desc'. Defaults to 'desc'", title='Order')
    start_after: UUID | None = Field(None, description='The ID of the statement to start the page after (exclusive). When provided, results will begin with the statement immediately following this ID. Use this for standard forward pagination to get the next page of results. Cannot be combined with end_before.', title='Start After')
    end_before: UUID | None = Field(None, description='The ID of the statement to end the page before (exclusive). When provided, results will end just before this ID and work backwards. Use this for reverse pagination or to retrieve previous pages. Cannot be combined with start_after.', title='End Before')
    start: str | None = Field(None, description='Filter statements where the period start date is on or after this date. Format: YYYY-MM-DD', title='Start')
    end: str | None = Field(None, description='Filter statements where the period start date is on or before this date. If the date is in the future, defaults to the current date. Format: YYYY-MM-DD', title='End')
    operation: Literal['list_account_statements'] = Field('list_account_statements', title='Get account statements', json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def one_cursor(self):
        if sum(getattr(self, k, None) is not None for k in ("start_at", "start_after", "end_before")) > 1:
            raise ValueError("Use only one pagination cursor")
        return self

class GetOrganization(_Closed):
    'Retrieve information about your organization including EIN, legal business name, and DBAs.'
    operation: Literal['get_organization'] = Field('get_organization', title='Get organization information', json_schema_extra={"ui:hidden": True})

Operation = Annotated[Union[ListAccounts, GetAccount, ListTransactions, ListAccountTransactions, GetTransaction, UpdateTransaction, ListRecipients, GetRecipient, CreateRecipient, UpdateRecipient, DeleteRecipient, SendMoney, CreateTransfer, ListCustomers, GetCustomer, CreateCustomer, UpdateCustomer, DeleteCustomer, ListInvoices, GetInvoice, CreateInvoice, UpdateInvoice, CancelInvoice, ListAccountStatements, GetOrganization], Field(discriminator="operation")]

ROUTES = {'list_accounts': {'method': 'GET',
                   'path': '/accounts',
                   'path_fields': [],
                   'query_fields': ['limit', 'order', 'start_after', 'end_before'],
                   'body_fields': [],
                   'statuses': [200]},
 'get_account': {'method': 'GET',
                 'path': '/account/{accountId}',
                 'path_fields': ['accountId'],
                 'query_fields': [],
                 'body_fields': [],
                 'statuses': [200]},
 'list_transactions': {'method': 'GET',
                       'path': '/transactions',
                       'path_fields': [],
                       'query_fields': ['status',
                                        'search',
                                        'start',
                                        'end',
                                        'postedStart',
                                        'postedEnd',
                                        'accountId',
                                        'cardId',
                                        'mercuryCategory',
                                        'categoryId',
                                        'start_at',
                                        'start_after',
                                        'end_before',
                                        'limit',
                                        'order'],
                       'body_fields': [],
                       'statuses': [200]},
 'list_account_transactions': {'method': 'GET',
                               'path': '/account/{accountId}/transactions',
                               'path_fields': ['accountId'],
                               'query_fields': ['limit',
                                                'start',
                                                'end',
                                                'search',
                                                'status',
                                                'offset',
                                                'order',
                                                'requestId',
                                                'mercuryCategory',
                                                'categoryId'],
                               'body_fields': [],
                               'statuses': [200]},
 'get_transaction': {'method': 'GET',
                     'path': '/transaction/{transactionId}',
                     'path_fields': ['transactionId'],
                     'query_fields': [],
                     'body_fields': [],
                     'statuses': [200]},
 'update_transaction': {'method': 'PATCH',
                        'path': '/transaction/{transactionId}',
                        'path_fields': ['transactionId'],
                        'query_fields': [],
                        'body_fields': ['categoryId', 'note'],
                        'statuses': [200]},
 'list_recipients': {'method': 'GET',
                     'path': '/recipients',
                     'path_fields': [],
                     'query_fields': ['limit', 'start_after', 'end_before', 'order'],
                     'body_fields': [],
                     'statuses': [200]},
 'get_recipient': {'method': 'GET',
                   'path': '/recipient/{recipientId}',
                   'path_fields': ['recipientId'],
                   'query_fields': [],
                   'body_fields': [],
                   'statuses': [200]},
 'create_recipient': {'method': 'POST',
                      'path': '/recipients',
                      'path_fields': [],
                      'query_fields': [],
                      'body_fields': ['address',
                                      'checkInfo',
                                      'contactEmail',
                                      'domesticWireRoutingInfo',
                                      'electronicRoutingInfo',
                                      'emails',
                                      'name',
                                      'nickname',
                                      'realTimePaymentRoutingInfo'],
                      'statuses': [200]},
 'update_recipient': {'method': 'POST',
                      'path': '/recipient/{recipientId}',
                      'path_fields': ['recipientId'],
                      'query_fields': [],
                      'body_fields': ['address',
                                      'checkInfo',
                                      'contactEmail',
                                      'domesticWireRoutingInfo',
                                      'electronicRoutingInfo',
                                      'emails',
                                      'name',
                                      'nickname',
                                      'realTimePaymentRoutingInfo'],
                      'statuses': [200]},
 'delete_recipient': {'method': 'DELETE',
                      'path': '/recipient/{recipientId}',
                      'path_fields': ['recipientId'],
                      'query_fields': [],
                      'body_fields': [],
                      'statuses': [204]},
 'send_money': {'method': 'POST',
                'path': '/account/{accountId}/transactions',
                'path_fields': ['accountId'],
                'query_fields': [],
                'body_fields': ['amount',
                                'externalMemo',
                                'idempotencyKey',
                                'note',
                                'paymentMethod',
                                'purpose',
                                'recipientId'],
                'statuses': [200]},
 'create_transfer': {'method': 'POST',
                     'path': '/transfer',
                     'path_fields': [],
                     'query_fields': [],
                     'body_fields': ['amount',
                                     'destinationAccountId',
                                     'idempotencyKey',
                                     'note',
                                     'sourceAccountId'],
                     'statuses': [200]},
 'list_customers': {'method': 'GET',
                    'path': '/ar/customers',
                    'path_fields': [],
                    'query_fields': ['limit', 'start_after', 'end_before', 'order'],
                    'body_fields': [],
                    'statuses': [200]},
 'get_customer': {'method': 'GET',
                  'path': '/ar/customers/{customerId}',
                  'path_fields': ['customerId'],
                  'query_fields': [],
                  'body_fields': [],
                  'statuses': [200]},
 'create_customer': {'method': 'POST',
                     'path': '/ar/customers',
                     'path_fields': [],
                     'query_fields': [],
                     'body_fields': ['address', 'email', 'name'],
                     'statuses': [200]},
 'update_customer': {'method': 'POST',
                     'path': '/ar/customers/{customerId}',
                     'path_fields': ['customerId'],
                     'query_fields': [],
                     'body_fields': ['address', 'email', 'name', 'resendOpenInvoices'],
                     'statuses': [200]},
 'delete_customer': {'method': 'DELETE',
                     'path': '/ar/customers/{customerId}',
                     'path_fields': ['customerId'],
                     'query_fields': [],
                     'body_fields': [],
                     'statuses': [200]},
 'list_invoices': {'method': 'GET',
                   'path': '/ar/invoices',
                   'path_fields': [],
                   'query_fields': ['limit', 'order', 'start_after', 'end_before'],
                   'body_fields': [],
                   'statuses': [200]},
 'get_invoice': {'method': 'GET',
                 'path': '/ar/invoices/{invoiceId}',
                 'path_fields': ['invoiceId'],
                 'query_fields': [],
                 'body_fields': [],
                 'statuses': [200]},
 'create_invoice': {'method': 'POST',
                    'path': '/ar/invoices',
                    'path_fields': [],
                    'query_fields': [],
                    'body_fields': ['achDebitEnabled',
                                    'ccEmails',
                                    'creditCardEnabled',
                                    'currencyCode',
                                    'customerId',
                                    'destinationAccountId',
                                    'dueDate',
                                    'internalNote',
                                    'invoiceDate',
                                    'invoiceNumber',
                                    'lineItems',
                                    'payerMemo',
                                    'poNumber',
                                    'sendEmailOption',
                                    'servicePeriodEndDate',
                                    'servicePeriodStartDate',
                                    'useRealAccountNumber'],
                    'statuses': [200]},
 'update_invoice': {'method': 'POST',
                    'path': '/ar/invoices/{invoiceId}',
                    'path_fields': ['invoiceId'],
                    'query_fields': [],
                    'body_fields': ['achDebitEnabled',
                                    'ccEmails',
                                    'creditCardEnabled',
                                    'dueDate',
                                    'internalNote',
                                    'invoiceDate',
                                    'invoiceNumber',
                                    'lineItems',
                                    'payerMemo',
                                    'poNumber',
                                    'servicePeriodEndDate',
                                    'servicePeriodStartDate',
                                    'useRealAccountNumber'],
                    'statuses': [200]},
 'cancel_invoice': {'method': 'POST',
                    'path': '/ar/invoices/{invoiceId}/cancel',
                    'path_fields': ['invoiceId'],
                    'query_fields': [],
                    'body_fields': [],
                    'statuses': [200]},
 'list_account_statements': {'method': 'GET',
                             'path': '/account/{accountId}/statements',
                             'path_fields': ['accountId'],
                             'query_fields': ['limit',
                                              'order',
                                              'start_after',
                                              'end_before',
                                              'start',
                                              'end'],
                             'body_fields': [],
                             'statuses': [200]},
 'get_organization': {'method': 'GET',
                      'path': '/organization',
                      'path_fields': [],
                      'query_fields': [],
                      'body_fields': [],
                      'statuses': [200]}}

for _model in list(globals().values()):
    if isinstance(_model, type) and issubclass(_model, _Closed):
        _model.model_rebuild()
