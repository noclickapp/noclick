"""Get The Referral v2: API-key referral, contact, sales rep and payment operations.

Contract: https://getthereferral.stoplight.io/ (published v2 OpenAPI).
Each operation issues one request; list operations return one page and its pagination.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://restapi.getthereferral.com/v2"


class GetTheReferralAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Get The Referral API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://getthereferral.stoplight.io/",
            "x-credential-instructions": "Paste your Get The Referral v2 API key. NoClick sends it as a Bearer token to restapi.getthereferral.com. Ask your Get The Referral administrator for a key scoped to your company. Contacts require Referral Boost access.",
        })
    credential_type: Literal["get_the_referral_api_key"] = Field("get_the_referral_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(char.isspace() for char in value) or not value.isascii():
            raise ValueError("Paste the API key without the Bearer prefix")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ListAdvocatesConfig(_Operation):
    'List Advocates'
    operation: Literal['list_advocates'] = Field('list_advocates', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, description='The page to be returned', ge=1)
    email: str | None = Field(None, description='Search for advocates that contain this value in their email address')
    firstname: str | None = Field(None, description='Search for advocates that contain this value in their first name')
    lastname: str | None = Field(None, description='Search for advocates that contain this value in their last name')
    phone: str | None = Field(None, description='Search for advocates that contain this value in their phone number')
    street1: str | None = Field(None, description='Search for advocates that contain this value in the first line of their street')
    street2: str | None = Field(None, description='Search for advocates that contain this value in the second line of their street')
    city: str | None = Field(None, description='Search for advocates that contain this value in their city')
    state: str | None = Field(None, description='Search for advocates that contain this value in their state')
    zip: str | None = Field(None, description='Search for advocates that contain this value in their zip or postal code')
    mlm_code: str | None = Field(None, description='Search for advocates that contain this value in their referral code')
    xtrm_pat_user_id: int | None = Field(None, description='Search for advocates that contain this value in their XTRM user ID')
    email_verified: Literal[0, 1] | None = Field(None, description='Return all advocates with verified email addresses. 0: Return all advocates without verified email addresses')
    added_on: str | None = Field(None, description='Search for advocates that contain this value in their added on timestamp')
    search: str | None = Field(None, description='Search for advocates that contain this value in any of the available search parameters')
    page_size: int = Field(50, description='The number of results to return per page', ge=1, le=250)
    sort_by: str = Field('added_on', description='The column or field to sort results by')
    sort_descending: bool = Field(False, description='Sort in descending alphabetical or numeric order')
    added_after: str | None = Field(None, description='Search for leads that were submitted after a certain timestamp. Accepts most date/time formats, including relative strings like "yesterday".', json_schema_extra={"format": "date-time"})
    added_before: str | None = Field(None, description='Search for leads that were submitted before a certain timestamp. Accepts most date/time formats, including relative strings like "yesterday".', json_schema_extra={"format": "date-time"})
    updated_after: str | None = Field(None, description='Search for leads that have been updated since a certain timestamp. Accepts most date/time formats, including relative strings like "yesterday".', json_schema_extra={"format": "date-time"})
    updated_before: str | None = Field(None, description='Search for leads that have not been updated since a certain timestamp. Accepts most date/time formats, including relative strings like "yesterday".', json_schema_extra={"format": "date-time"})

class CreateAdvocateConfig(_Operation):
    'Create Advocate'
    operation: Literal['create_advocate'] = Field('create_advocate', json_schema_extra={"ui:hidden": True})
    sales_rep_id: int | None = Field(None, description='The user ID of the sales rep that this advocate should be associated with. Falls back to salesrepemail if not provided.')
    salesrepemail: str | None = Field(None, description='The email address of the sales rep that this advocate should be associated with. Defaults to house sales rep if not provided. Not used if sales_rep_id is provided.')
    email: str = Field(..., min_length=1)
    firstname: str = Field(..., min_length=1)
    lastname: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1, json_schema_extra={"ui:widget": "password"})
    country_code: str | None = Field(None, description='Default: empty')
    phone: str | None = Field(None, description='(XXX) XXX-XXXX\nDefault: empty')
    street1: str | None = Field(None, description='Default: empty')
    street2: str | None = Field(None, description='Default: empty')
    city: str | None = Field(None, description='Default: empty')
    state: str | None = Field(None, description='The state, region or province of the advocates address. US states should be two-letter ANSI abbreviations.\nDefault: empty')
    zip: str | None = Field(None, description='The zip or postal code of the advocates address.\nDefault: empty')
    parent_advocate_id: int | None = Field(None, description='The user id of the advocate that this new advocate should be signed up under. This is for MLM configurations only and can be used instead of refer_code.\nDefault: none')
    refer_code: str | None = Field(None, description='The referral code of the advocate that this new advocate should be signed up under. This is for MLM configurations only and can be used instead of parent_advocate_id.\nDefault: none')
    xtrm_user_id: str | None = Field(None, description='XTRM user ID.\nDefault: New account generated')
    company_cam_project_id: str | None = Field(None, description='Default: empty')
    installer: str | None = Field(None)

class GetAdvocateConfig(_Operation):
    'Get Advocate'
    operation: Literal['get_advocate'] = Field('get_advocate', json_schema_extra={"ui:hidden": True})
    advocate_id: int = Field(..., description='ID of the advocate to fetch')

class UpdateAdvocateConfig(_Operation):
    'Update Advocate'
    operation: Literal['update_advocate'] = Field('update_advocate', json_schema_extra={"ui:hidden": True})
    advocate_id: int = Field(..., description='ID of the advocate to fetch')
    firstname: str | None = Field(None)
    lastname: str | None = Field(None)
    phone: str | None = Field(None, description='(XXX) XXX-XXXX')
    street1: str | None = Field(None)
    street2: str | None = Field(None)
    city: str | None = Field(None)
    state: str | None = Field(None, description='The state, region or province of the advocates address. US states should be two letter abbreviations.')
    zip: str | None = Field(None, description='The zip or postal code of the advocates address.')
    company_cam_id: str | None = Field(None, description='The CompanyCam project ID to associate with the advocate.')
    installer: str | None = Field(None)

class ListLeadsConfig(_Operation):
    'List Leads'
    operation: Literal['list_leads'] = Field('list_leads', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, description='The page to be returned', ge=1)
    page_size: int = Field(50, description='The number of results to return per page', ge=1, le=250)
    sort_by: str = Field('added_on', description='The column or field to sort results by')
    sort_descending: bool = Field(False, description='Sort in descending alphabetical or numeric order')
    status: int | None = Field(None, description='Search for leads with currently in a specific status', ge=1, le=5)
    email: str | None = Field(None, description='Search for leads that contain this value in their email address')
    firstname: str | None = Field(None, description='Search for leads that contain this value in their first name')
    lastname: str | None = Field(None, description='Search for leads that contain this value in their last name')
    phone: str | None = Field(None, description='Search for leads that contain this value in their phone number')
    street1: str | None = Field(None, description='Search for leads that contain this value in the first line of their street')
    street2: str | None = Field(None, description='Search for leads that contain this value in the second line of their street')
    city: str | None = Field(None, description='Search for leads that contain this value in their city')
    state: str | None = Field(None, description='Search for leads that contain this value in their state')
    zip: str | None = Field(None, description='Search for leads that contain this value in their zip or postal code')
    time_to_contact: str | None = Field(None, description='Search for leads that contain this value in their time to contact')
    added_on: str | None = Field(None, description='Search for leads that contain this value in their added on timestamp')
    search: str | None = Field(None, description='Search for leads that contain this value in any of the available search parameters')
    added_after: str | None = Field(None, description='Search for leads that were submitted after a certain timestamp. Accepts most date/time formats, including relative strings like "yesterday". This parameter is in open beta testing.', json_schema_extra={"format": "date-time"})
    added_before: str | None = Field(None, description='Search for leads that were submitted before a certain timestamp. Accepts most date/time formats, including relative strings like "yesterday". This parameter is in open beta testing.', json_schema_extra={"format": "date-time"})
    updated_after: str | None = Field(None, description='Search for leads that have been updated since a certain timestamp. Accepts most date/time formats, including relative strings like "yesterday". This parameter is in open beta testing.', json_schema_extra={"format": "date-time"})
    updated_before: str | None = Field(None, description='Search for leads that have not been updated since a certain timestamp. Accepts most date/time formats, including relative strings like "yesterday". This parameter is in open beta testing.', json_schema_extra={"format": "date-time"})

class CreateLeadConfig(_Operation):
    'Create Lead'
    operation: Literal['create_lead'] = Field('create_lead', json_schema_extra={"ui:hidden": True})
    advocate_id: int = Field(..., description='The user ID of the advocate that is submitting the lead.')
    product_id: int = Field(..., description='The ID of the product that the lead should be submitted under.')
    email: str = Field(..., description='The email address of the lead.', min_length=1)
    firstname: str | None = Field(None, description='The first name of the lead.\nDefault: empty')
    lastname: str | None = Field(None, description='The last name of the lead.\nDefault: empty')
    phone: str | None = Field(None, description='Default: empty')
    street1: str | None = Field(None, description='Default: empty')
    street2: str | None = Field(None, description='Default: empty')
    state: str | None = Field(None, description='Default: empty')
    city: str | None = Field(None, description='Default: empty')
    zip: str | None = Field(None, description='Default: empty')
    time_to_contact: str | None = Field(None, description='String of text indicating when the lead would preferred to be contacted (e.g. "Afternoon", or "8 AM - 12 PM").\nDefault: empty')
    crm_lead_id: str | None = Field(None, description='The ID that coresponds to this lead in an external system such as a CRM.\nDefault: empty')
    is_lead_from_crm: bool | None = Field(None, description='If the lead is coming from the CRM, mark as TRUE to ensure that the lead does not get pushed to the CRM again.\nDefault: `false`')
    note: str | None = Field(None, description='Default: empty')

class GetLeadConfig(_Operation):
    'Get Lead'
    operation: Literal['get_lead'] = Field('get_lead', json_schema_extra={"ui:hidden": True})
    lead_id: str = Field(..., min_length=1, pattern=r'^[A-Za-z0-9_-]+$')

class UpdateLeadConfig(_Operation):
    'Update Lead'
    operation: Literal['update_lead'] = Field('update_lead', json_schema_extra={"ui:hidden": True})
    lead_id: str = Field(..., min_length=1, pattern=r'^[A-Za-z0-9_-]+$')
    status_id: int | None = Field(None, description='Valid status_id are \nDefault Label | Status Value\n---------|----------\n Unverified | 1\n Working | 5\n Verified | 2\n Sold | 3\n Closed | 4\n Ineligible | 6', ge=1, le=5)
    email: str | None = Field(None, description='The email address of the lead.')
    firstname: str | None = Field(None, description='The first name of the lead.')
    lastname: str | None = Field(None, description='The last name of the lead.')
    phone: str | None = Field(None, description='The phone number of the lead.')
    street1: str | None = Field(None)
    street2: str | None = Field(None)
    city: str | None = Field(None)
    state: str | None = Field(None)
    zip: str | None = Field(None)

class ListContactsConfig(_Operation):
    'List Contacts'
    operation: Literal['list_contacts'] = Field('list_contacts', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, description='The page to be returned', ge=1)
    email: str | None = Field(None, description='Search for contacts that contain this value in their email address')
    firstname: str | None = Field(None, description='Search for contacts that contain this value in their first name')
    lastname: str | None = Field(None, description='Search for contacts that contain this value in their last name')
    phone: str | None = Field(None, description='Search for contacts that contain this value in their phone number')
    street1: str | None = Field(None, description='Search for contacts that contain this value in the first line of their street')
    street2: str | None = Field(None, description='Search for contacts that contain this value in the second line of their street')
    city: str | None = Field(None, description='Search for contacts that contain this value in their city')
    state: str | None = Field(None, description='Search for contacts that contain this value in their state')
    zip: str | None = Field(None, description='Search for contacts that contain this value in their zip or postal code')
    added_before: str | None = Field(None, description='Search for contacts added before a given time')
    search: str | None = Field(None, description='Search for contacts that contain this value in any of the available search parameters')
    page_size: int = Field(50, description='The number of results to return per page', ge=1, le=250)
    sort_by: str = Field('added_on', description='The column or field to sort results by')
    sort_decending: bool = Field(False, description='Sort in descending alphabetical or numeric order')
    salesrep_id: int | None = Field(None, description='Search by associated Sales Rep')
    added_after: str | None = Field(None, description='Search for contacts added after a given time')

class CreateContactConfig(_Operation):
    'Create Contact'
    operation: Literal['create_contact'] = Field('create_contact', json_schema_extra={"ui:hidden": True})
    salesrep_id: int | None = Field(None, description='The user ID of the sales rep that this contact should be assigned to.')
    firstname: str = Field(..., min_length=1)
    lastname: str = Field(..., min_length=1)
    email: str = Field(..., min_length=1)
    phone: str | None = Field(None, description='(XXX) XXX-XXXX')
    street1: str | None = Field(None)
    street2: str | None = Field(None)
    city: str | None = Field(None)
    state: str | None = Field(None, description='The state, region or province of the sales reps address. US states should be two-letter ANSI abbreviations.')
    zip: str | None = Field(None, description='The zip or postal code of the sales reps address.')

class GetContactConfig(_Operation):
    'Get Contact'
    operation: Literal['get_contact'] = Field('get_contact', json_schema_extra={"ui:hidden": True})
    contact_id: str = Field(..., min_length=1, pattern=r'^[A-Za-z0-9_-]+$')

class UpdateContactConfig(_Operation):
    'Update Contact'
    operation: Literal['update_contact'] = Field('update_contact', json_schema_extra={"ui:hidden": True})
    contact_id: str = Field(..., min_length=1, pattern=r'^[A-Za-z0-9_-]+$')
    firstname: str | None = Field(None)
    lastname: str | None = Field(None)
    phone: str | None = Field(None, description='(XXX) XXX-XXXX')
    street1: str | None = Field(None)
    street2: str | None = Field(None)
    city: str | None = Field(None)
    state: str | None = Field(None, description='The state, region or province of the sales reps address. US states should be two-letter ANSI abbreviations.')
    zip: str | None = Field(None, description='The zip or postal code of the sales reps address.')
    email: str | None = Field(None)
    salesrep_id: int | None = Field(None)
    is_active: bool | None = Field(None)

class DeleteContactConfig(_Operation):
    'Delete Contact'
    operation: Literal['delete_contact'] = Field('delete_contact', json_schema_extra={"ui:hidden": True})
    contact_id: str = Field(..., min_length=1, pattern=r'^[A-Za-z0-9_-]+$')

class ListSalesRepsConfig(_Operation):
    'List Sales Reps'
    operation: Literal['list_sales_reps'] = Field('list_sales_reps', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, description='The page to be returned', ge=1)
    email: str | None = Field(None, description='Search for sales reps that contain this value in their email address')
    firstname: str | None = Field(None, description='Search for sales reps that contain this value in their first name')
    lastname: str | None = Field(None, description='Search for sales reps that contain this value in their last name')
    phone: str | None = Field(None, description='Search for sales reps that contain this value in their phone number')
    street1: str | None = Field(None, description='Search for sales reps that contain this value in the first line of their street')
    street2: str | None = Field(None, description='Search for sales reps that contain this value in the second line of their street')
    city: str | None = Field(None, description='Search for sales reps that contain this value in their city')
    state: str | None = Field(None, description='Search for sales reps that contain this value in their state')
    zip: str | None = Field(None, description='Search for sales reps that contain this value in their zip or postal code')
    email_verified: Literal[0, 1] | None = Field(None, description='Return all sales reps with verified email addresses. 0: Return all advocates without verified email addresses')
    added_on: str | None = Field(None, description='Search for sales reps that contain this value in their added on timestamp')
    search: str | None = Field(None, description='Search for sales reps that contain this value in any of the available search parameters')
    page_size: int = Field(50, description='The number of results to return per page', ge=1, le=250)
    sort_by: str = Field('added_on', description='The column or field to sort results by')
    sort_decending: bool = Field(False, description='Sort in descending alphabetical or numeric order')

class CreateSalesRepConfig(_Operation):
    'Create Sales Rep'
    operation: Literal['create_sales_rep'] = Field('create_sales_rep', json_schema_extra={"ui:hidden": True})
    sales_manager_id: int | None = Field(None, description='The user ID of the sales manager that this sales rep should be assigned to. Defaults to House Sales rep if available and sales_manager_email is not set.')
    sales_manager_email: str | None = Field(None, description='Alternative to sales_manager_id.  Defaults to House Sales rep if available and sales_manager_id is not set.')
    firstname: str = Field(..., min_length=1)
    lastname: str = Field(..., min_length=1)
    email: str = Field(..., min_length=1)
    phone: str = Field(..., description='(XXX) XXX-XXXX', min_length=1)
    password: str = Field(..., min_length=1, json_schema_extra={"ui:widget": "password"})
    street1: str | None = Field(None)
    street2: str | None = Field(None)
    city: str | None = Field(None)
    state: str | None = Field(None, description='The state, region or province of the sales reps address. US states should be two-letter ANSI abbreviations.')
    zip: str | None = Field(None, description='The zip or postal code of the sales reps address.')

class GetSalesRepConfig(_Operation):
    'Get Sales Rep'
    operation: Literal['get_sales_rep'] = Field('get_sales_rep', json_schema_extra={"ui:hidden": True})
    sales_rep_id: str = Field(..., min_length=1, pattern=r'^[A-Za-z0-9_-]+$')

class UpdateSalesRepConfig(_Operation):
    'Update Sales Rep'
    operation: Literal['update_sales_rep'] = Field('update_sales_rep', json_schema_extra={"ui:hidden": True})
    sales_rep_id: str = Field(..., min_length=1, pattern=r'^[A-Za-z0-9_-]+$')
    firstname: str | None = Field(None)
    lastname: str | None = Field(None)
    phone: str | None = Field(None, description='(XXX) XXX-XXXX')
    street1: str | None = Field(None)
    street2: str | None = Field(None)
    city: str | None = Field(None)
    state: str | None = Field(None, description='The state, region or province of the sales reps address. US states should be two-letter ANSI abbreviations.')
    zip: str | None = Field(None, description='The zip or postal code of the sales reps address.')

class UpdateLeadStatusConfig(_Operation):
    'Update Lead Status'
    operation: Literal['update_lead_status'] = Field('update_lead_status', json_schema_extra={"ui:hidden": True})
    lead_id: str = Field(..., description='The GTR or external id for the lead. This could come from the CRM but must be mapped to a lead in the GTR Advocator Dashboard.', min_length=1)
    lead_status: str = Field(..., description='The mapped status key or the default numeric identifier (1-5) of the status that the lead should be updated to. To use keys, they must first be mapped by a Get The Referral Integration Engineer.\n**Sold** referrals can not be updated to **Closed** or **Working**. **Closed** referrals cannot be updated to **Working**.\nDefault Label | Numeric Identifier\n---------|----------\n Unverified | 1\n Working | 5\n Verified | 2\n Sold | 3\n Closed/Lost | 4\n Ineligible | 6', min_length=1)
    amount: float | None = Field(None, description='The total value of the sale.', ge=0)
    job_id: str | None = Field(None)
    install_date: str | None = Field(None, json_schema_extra={"format": "date-time"})

class ListPendingPaymentsConfig(_Operation):
    'Get Pending Payments'
    operation: Literal['list_pending_payments'] = Field('list_pending_payments', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, description='The page to be returned.', ge=1)
    page_size: int = Field(50, description='The number of results to return per page', ge=1, le=250)
    search: str | None = Field(None, description='Search for files that contain this value in any of the available search parameters')
    sort_by: str = Field('created_at', description='The column or field to sort results by')
    sort_descending: bool = Field(False, description='Sort in descending alphabetical or numeric order')

class ListPaidPaymentsConfig(_Operation):
    'Get Paid Payments'
    operation: Literal['list_paid_payments'] = Field('list_paid_payments', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, description='The page to be returned', ge=1)
    page_size: int = Field(50, description='The number of results to return per page', ge=1, le=250)
    search: str | None = Field(None, description='Search for files that contain this value in any of the available search parameters')
    sort_by: str = Field('created_at', description='The column or field to sort results by')
    sort_descending: bool = Field(False, description='Sort in descending alphabetical or numeric order')

class ListWalletTransactionsConfig(_Operation):
    'Get XTRM Transactions'
    operation: Literal['list_wallet_transactions'] = Field('list_wallet_transactions', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, description='The page to be returned', ge=1)
    page_size: int = Field(50, description='The number of results to return per page', ge=1, le=250)
    start_date: str | None = Field(None, description='mm-dd-yyyy')
    end_date: str | None = Field(None, description='mm-dd-yyyy')
    transaction_type: Literal['all', 'credit', 'debit'] | None = Field(None, description='Transaction direction')


GetTheReferralConfig = Annotated[Union[
    ListAdvocatesConfig,
    CreateAdvocateConfig,
    GetAdvocateConfig,
    UpdateAdvocateConfig,
    ListLeadsConfig,
    CreateLeadConfig,
    GetLeadConfig,
    UpdateLeadConfig,
    ListContactsConfig,
    CreateContactConfig,
    GetContactConfig,
    UpdateContactConfig,
    DeleteContactConfig,
    ListSalesRepsConfig,
    CreateSalesRepConfig,
    GetSalesRepConfig,
    UpdateSalesRepConfig,
    UpdateLeadStatusConfig,
    ListPendingPaymentsConfig,
    ListPaidPaymentsConfig,
    ListWalletTransactionsConfig
], Field(discriminator="operation")]


class GetTheReferralFullConfig(NodeConfig[GetTheReferralConfig, GetTheReferralAPIKeyCredential]):
    pass


# method, path, query fields, body fields, collection key, response shape
ROUTES = {'list_advocates': ('GET',
                    '/advocates',
                    ('page',
                     'email',
                     'firstname',
                     'lastname',
                     'phone',
                     'street1',
                     'street2',
                     'city',
                     'state',
                     'zip',
                     'mlm_code',
                     'xtrm_pat_user_id',
                     'email_verified',
                     'added_on',
                     'search',
                     'page_size',
                     'sort_by',
                     'sort_descending',
                     'added_after',
                     'added_before',
                     'updated_after',
                     'updated_before'),
                    (),
                    'advocates',
                    'object'),
 'create_advocate': ('POST',
                     '/advocates',
                     (),
                     ('sales_rep_id',
                      'salesrepemail',
                      'email',
                      'firstname',
                      'lastname',
                      'password',
                      'country_code',
                      'phone',
                      'street1',
                      'street2',
                      'city',
                      'state',
                      'zip',
                      'parent_advocate_id',
                      'refer_code',
                      'xtrm_user_id',
                      'company_cam_project_id',
                      'installer'),
                     None,
                     'array'),
 'get_advocate': ('GET', '/advocates/{advocate_id}', (), (), None, 'array'),
 'update_advocate': ('PATCH',
                     '/advocates/{advocate_id}',
                     (),
                     ('firstname',
                      'lastname',
                      'phone',
                      'street1',
                      'street2',
                      'city',
                      'state',
                      'zip',
                      'company_cam_id',
                      'installer'),
                     None,
                     'array'),
 'list_leads': ('GET',
                '/leads',
                ('page',
                 'page_size',
                 'sort_by',
                 'sort_descending',
                 'status',
                 'email',
                 'firstname',
                 'lastname',
                 'phone',
                 'street1',
                 'street2',
                 'city',
                 'state',
                 'zip',
                 'time_to_contact',
                 'added_on',
                 'search',
                 'added_after',
                 'added_before',
                 'updated_after',
                 'updated_before'),
                (),
                'leads',
                'object'),
 'create_lead': ('POST',
                 '/leads',
                 (),
                 ('advocate_id',
                  'product_id',
                  'email',
                  'firstname',
                  'lastname',
                  'phone',
                  'street1',
                  'street2',
                  'state',
                  'city',
                  'zip',
                  'time_to_contact',
                  'crm_lead_id',
                  'is_lead_from_crm',
                  'note'),
                 None,
                 'array'),
 'get_lead': ('GET', '/leads/{lead_id}', (), (), None, 'array'),
 'update_lead': ('PATCH',
                 '/leads/{lead_id}',
                 (),
                 ('status_id',
                  'email',
                  'firstname',
                  'lastname',
                  'phone',
                  'street1',
                  'street2',
                  'city',
                  'state',
                  'zip'),
                 None,
                 'array'),
 'list_contacts': ('GET',
                   '/contacts',
                   ('page',
                    'email',
                    'firstname',
                    'lastname',
                    'phone',
                    'street1',
                    'street2',
                    'city',
                    'state',
                    'zip',
                    'added_before',
                    'search',
                    'page_size',
                    'sort_by',
                    'sort_decending',
                    'salesrep_id',
                    'added_after'),
                   (),
                   'contacts',
                   'object'),
 'create_contact': ('POST',
                    '/contacts',
                    (),
                    ('salesrep_id',
                     'firstname',
                     'lastname',
                     'email',
                     'phone',
                     'street1',
                     'street2',
                     'city',
                     'state',
                     'zip'),
                    None,
                    'array'),
 'get_contact': ('GET', '/contacts/{contact_id}', (), (), None, 'array'),
 'update_contact': ('PATCH',
                    '/contacts/{contact_id}',
                    (),
                    ('firstname',
                     'lastname',
                     'phone',
                     'street1',
                     'street2',
                     'city',
                     'state',
                     'zip',
                     'email',
                     'salesrep_id',
                     'is_active'),
                    None,
                    'array'),
 'delete_contact': ('DELETE', '/contacts/{contact_id}', (), (), None, 'empty'),
 'list_sales_reps': ('GET',
                     '/salesreps',
                     ('page',
                      'email',
                      'firstname',
                      'lastname',
                      'phone',
                      'street1',
                      'street2',
                      'city',
                      'state',
                      'zip',
                      'email_verified',
                      'added_on',
                      'search',
                      'page_size',
                      'sort_by',
                      'sort_decending'),
                     (),
                     'salesreps',
                     'object'),
 'create_sales_rep': ('POST',
                      '/salesreps',
                      (),
                      ('sales_manager_id',
                       'sales_manager_email',
                       'firstname',
                       'lastname',
                       'email',
                       'phone',
                       'password',
                       'street1',
                       'street2',
                       'city',
                       'state',
                       'zip'),
                      None,
                      'array'),
 'get_sales_rep': ('GET', '/salesreps/{sales_rep_id}', (), (), None, 'array'),
 'update_sales_rep': ('PATCH',
                      '/salesreps/{sales_rep_id}',
                      (),
                      ('firstname', 'lastname', 'phone', 'street1', 'street2', 'city', 'state', 'zip'),
                      None,
                      'array'),
 'update_lead_status': ('POST',
                        '/leads/updateStatus',
                        (),
                        ('lead_id', 'lead_status', 'amount', 'job_id', 'install_date'),
                        None,
                        'object'),
 'list_pending_payments': ('GET',
                           '/payments/pending',
                           ('page', 'page_size', 'search', 'sort_by', 'sort_descending'),
                           (),
                           'advocates',
                           'object'),
 'list_paid_payments': ('GET',
                        '/payments/paid',
                        ('page', 'page_size', 'search', 'sort_by', 'sort_descending'),
                        (),
                        'advocates',
                        'object'),
 'list_wallet_transactions': ('GET',
                              '/payments/xtrm',
                              ('page', 'page_size', 'start_date', 'end_date', 'transaction_type'),
                              (),
                              'transactions',
                              'object')}


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secrets) for key, item in value.items()
                if key.lower() not in {"password", "api_key", "authorization", "access_token"}}
    return value


class GetTheReferralNode(WorkflowNode):
    integration_type = "automation-get-the-referral"
    connection_evidence = ConnectionEvidence(
        noun="advocates", operation="list_advocates", label_keys=("email", "firstname", "id"))

    @classmethod
    def get_config_model(cls):
        return GetTheReferralFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Get The Referral API key")
        op = self.config.config
        method, path, query_fields, body_fields, collection, shape = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True, exclude={"operation"})
        for field in re.findall(r"\{([^}]+)\}", path):
            path = path.replace("{" + field + "}", quote(str(values.pop(field)), safe=""))
        query = {key: str(values[key]).lower() if isinstance(values[key], bool) else values[key]
                 for key in query_fields if key in values}
        body = {key: values[key] for key in body_fields if key in values}
        if method == "PATCH" and not body:
            raise ValueError("Provide at least one field to update")
        key = self.config.credentials.api_key
        secrets = (key, values.get("password"))
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
                    params=query, **({"json": body} if body_fields else {}))
            if response.status_code != 200:
                return {"status": "error", "http_status": response.status_code,
                        "error": _redact(response.text, secrets)}
            if shape == "empty":
                return {"status": "success", "http_status": 200, "deletion_acknowledged": True}
            data = response.json()
            if isinstance(data, dict) and (data.get("error") or data.get("errors") or data.get("success") is False):
                return {"status": "error", "error": _redact(data, secrets), "http_status": 200}
            if shape == "array" and not isinstance(data, list):
                raise ValueError("Expected a resource array")
            if shape == "object" and not isinstance(data, dict):
                raise ValueError("Expected a response object")
            if collection:
                if not isinstance(data.get(collection), list):
                    raise ValueError("Expected the documented collection")
                return {"status": "success", "data": _redact(data[collection], secrets),
                        "pagination": _redact(data.get("pagination"), secrets)}
            return {"status": "success", "data": _redact(data, secrets)}
        except (httpx.HTTPError, ValueError):
            return {"status": "error", "error": "Get The Referral request failed or returned an unexpected response; inspect the provider before retrying a write"}
