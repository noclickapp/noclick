"""Amplemarket v1 API: fixed operations from the provider's published OpenAPI.

Contract: https://api.amplemarket.com/api-docs/v1/swagger.yaml (v1).
Webhook configuration is dashboard-only, so new calls use scheduled polling.
"""
from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal, Optional, Union
from urllib.parse import quote, urlsplit, parse_qs

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE_URL = "https://api.amplemarket.com"


class AmplemarketAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Amplemarket API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://docs.amplemarket.com/guides/quickstart",
            "x-credential-instructions": "In Amplemarket, open Settings > API, create an API key and paste it here. NoClick sends it as a Bearer token to api.amplemarket.com. The account details read verifies your account."})
    credential_type: Literal["amplemarket_api_key"] = Field("amplemarket_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key, without Bearer or whitespace")
        return value


class AmplemarketInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, populate_by_name=True)

    @field_validator("lead_list_id", "contact_id", "account_id", "task_id", "sequence_id", "user_id", "owner_id", "disposition_id", mode="before", check_fields=False)
    @classmethod
    def safe_identifier(cls, value, info):
        if value is not None and info.field_name.endswith("_id"):
            if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
                raise ValueError("Use a single Amplemarket resource ID")
        return value

class AmplemarketGetAccountInfoConfig(AmplemarketInput):
    'Get account details'
    operation: Literal['get_account_info'] = Field('get_account_info', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'Get account details', 'x-category': 'Account'})

class AmplemarketListUsersConfig(AmplemarketInput):
    'List users'
    operation: Literal['list_users'] = Field('list_users', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'List users', 'x-category': 'Users'})
    page_size: Optional[int] = Field(100, ge=1, le=100)
    page_after: Optional[str] = Field(None)
    page_before: Optional[str] = Field(None)
    status: Optional[str] = Field(None)
    role: Optional[str] = Field(None)
    email: Optional[str] = Field(None)

class AmplemarketFindPersonConfig(AmplemarketInput):
    'Single person enrichment'
    operation: Literal['find_person'] = Field('find_person', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'Single person enrichment', 'x-category': 'People'})
    email: Optional[str] = Field(None, json_schema_extra={'format': 'email'})
    linkedin_url: Optional[str] = Field(None)
    name: Optional[str] = Field(None)
    title: Optional[str] = Field(None)
    company_name: Optional[str] = Field(None)
    company_domain: Optional[str] = Field(None)
    reveal_email: Optional[bool] = Field(None)
    reveal_phone_numbers: Optional[bool] = Field(None)

    @model_validator(mode="after")
    def matching_identity(self):
        if not (self.email or self.linkedin_url or (self.name and (self.company_name or self.company_domain))):
            raise ValueError("Supply a matching email, LinkedIn URL, or documented name/company identity")
        return self

class AmplemarketFindCompanyConfig(AmplemarketInput):
    'Single company enrichment'
    operation: Literal['find_company'] = Field('find_company', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'Single company enrichment', 'x-category': 'Companies Enrichment'})
    domain: Optional[str] = Field(None)
    linkedin_url: Optional[str] = Field(None)

    @model_validator(mode="after")
    def matching_identity(self):
        if not (self.domain or self.linkedin_url):
            raise ValueError("Supply a matching email, LinkedIn URL, or documented name/company identity")
        return self

class AmplemarketListLeadListsConfig(AmplemarketInput):
    'List Lead Lists'
    operation: Literal['list_lead_lists'] = Field('list_lead_lists', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'List Lead Lists', 'x-category': 'Lead List'})
    page_size: Optional[int] = Field(100, ge=1, le=100)
    page_after: Optional[str] = Field(None)
    page_before: Optional[str] = Field(None)
    status: Optional[str] = Field(None)
    owner_id: Optional[str] = Field(None)
    owner_email: Optional[str] = Field(None)

class AmplemarketCreateLeadListConfigOptions(AmplemarketInput):
    reveal_phone_numbers: Optional[bool] = Field(None)
    validate_email: Optional[bool] = Field(None)
    enrich: Optional[bool] = Field(None)

class AmplemarketCreateLeadListConfigLeadsitem(AmplemarketInput):
    model_config = ConfigDict(extra="allow", hide_input_in_errors=True)
    linkedin_url: Optional[str] = Field(None)
    email: Optional[str] = Field(None, json_schema_extra={'format': 'email'})
    title: Optional[str] = Field(None)
    company_name: Optional[str] = Field(None)
    company_domain: Optional[str] = Field(None)
    phone_numbers: Optional[list[str]] = Field(None)
    context: Optional[dict[str, Any]] = Field(None, description='Additional custom fields to store on the lead. These fields are flattened into the lead data fields.')

class AmplemarketCreateLeadListConfig(AmplemarketInput):
    'Create Lead List'
    operation: Literal['create_lead_list'] = Field('create_lead_list', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'Create Lead List', 'x-category': 'Lead List'})
    name: Optional[str] = Field(None)
    shared: bool = Field(...)
    visible: Optional[bool] = Field(None)
    owner: str = Field(..., json_schema_extra={'format': 'email'})
    type: Literal['linkedin', 'email', 'titles_and_company'] = Field(...)
    options: Optional[AmplemarketCreateLeadListConfigOptions] = Field(None)
    leads: list[AmplemarketCreateLeadListConfigLeadsitem] = Field(..., description='You may send up to 10000 leads at a time.', max_length=10000)

class AmplemarketGetLeadListConfig(AmplemarketInput):
    'Retrieve Lead List'
    operation: Literal['get_lead_list'] = Field('get_lead_list', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'Retrieve Lead List', 'x-category': 'Lead List'})
    lead_list_id: str = Field(..., min_length=1, max_length=200)
    page_size: Optional[int] = Field(100, ge=1, le=100)
    page_after: Optional[str] = Field(None)
    page_before: Optional[str] = Field(None)

class AmplemarketAddLeadsToListConfigLeadsitem(AmplemarketInput):
    model_config = ConfigDict(extra="allow", hide_input_in_errors=True)
    linkedin_url: Optional[str] = Field(None)
    email: Optional[str] = Field(None, json_schema_extra={'format': 'email'})
    title: Optional[str] = Field(None)
    company_name: Optional[str] = Field(None)
    company_domain: Optional[str] = Field(None)
    phone_numbers: Optional[list[str]] = Field(None)
    context: Optional[dict[str, Any]] = Field(None, description='Additional custom fields to store on the lead. These fields are flattened into the lead data fields.')

class AmplemarketAddLeadsToListConfig(AmplemarketInput):
    'Add Leads to a List'
    operation: Literal['add_leads_to_list'] = Field('add_leads_to_list', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'Add Leads to a List', 'x-category': 'Lead List'})
    lead_list_id: str = Field(..., min_length=1, max_length=200)
    type: Optional[Literal['linkedin', 'email', 'titles_and_company']] = Field(None)
    leads: list[AmplemarketAddLeadsToListConfigLeadsitem] = Field(..., description='You can add up to 10,000 leads at a time. However, each Lead List can have a maximum of 60,000 leads. When approaching this limit, new leads will be added partially until the limit is reached. When the limit is hit, a 409 HTTP status code will be returned. Enriching, email validation, and reveal settings are inherited from the Lead List settings. If credits are spent, those will be deducted from the admin user of the account.', max_length=10000)

class AmplemarketListContactsConfig(AmplemarketInput):
    'Retrieve contacts'
    operation: Literal['list_contacts'] = Field('list_contacts', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'Retrieve contacts', 'x-category': 'Contacts'})
    name: Optional[str] = Field(None)
    account_id: Optional[str] = Field(None, json_schema_extra={'format': 'uuid'})
    ids: Optional[list[str]] = Field(None, max_length=20)

class AmplemarketCreateContactConfigPhoneNumbersitem(AmplemarketInput):
    number: Optional[str] = Field(None, description='Phone number in raw or international format')
    kind: Optional[Literal['mobile', 'office', 'phone', 'landline', 'voip', 'direct', 'fax']] = Field(None, description='Phone number kind')
    type: Optional[Literal['mobile', 'office', 'phone', 'landline', 'voip', 'direct', 'fax']] = Field(None, description='Alias for kind')

class AmplemarketCreateContactConfig(AmplemarketInput):
    'Create contact'
    operation: Literal['create_contact'] = Field('create_contact', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'Create contact', 'x-category': 'Contacts'})
    email: str = Field(..., description='Contact email')
    first_name: Optional[str] = Field(None, description='Contact first name')
    last_name: Optional[str] = Field(None, description='Contact last name')
    title: Optional[str] = Field(None, description='Contact job title')
    city: Optional[str] = Field(None, description='Contact city')
    state: Optional[str] = Field(None, description='Contact state or region')
    country: Optional[str] = Field(None, description='Contact country')
    industry: Optional[str] = Field(None, description='Contact industry')
    linkedin_url: Optional[str] = Field(None, description='Contact LinkedIn profile URL', json_schema_extra={'format': 'uri'})
    owner_email: Optional[str] = Field(None, description='Email of the Amplemarket user that should own the contact')
    account_id: Optional[str] = Field(None, description='Prospect Hub account public ID to associate to the contact', json_schema_extra={'format': 'uuid'})
    crm_account_id: Optional[str] = Field(None, description='CRM account identifier used to resolve the Prospect Hub account association')
    company_domain: Optional[str] = Field(None, description='Company domain used to resolve the Prospect Hub account association')
    company_name: Optional[str] = Field(None, description='Company name used as a fallback to resolve the Prospect Hub account association')
    phone_numbers: Optional[list[AmplemarketCreateContactConfigPhoneNumbersitem]] = Field(None, description='Phone numbers to attach to the contact as user-uploaded numbers')

class AmplemarketGetContactConfig(AmplemarketInput):
    'Retrieve contact'
    operation: Literal['get_contact'] = Field('get_contact', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'Retrieve contact', 'x-category': 'Contacts'})
    contact_id: str = Field(..., min_length=1, max_length=200)

class AmplemarketGetContactByEmailConfig(AmplemarketInput):
    'Retrieve contact by email'
    operation: Literal['get_contact_by_email'] = Field('get_contact_by_email', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'Retrieve contact by email', 'x-category': 'Contacts'})
    email: str = Field(..., min_length=1, max_length=320)

class AmplemarketListAccountsConfig(AmplemarketInput):
    'List Accounts'
    operation: Literal['list_accounts'] = Field('list_accounts', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'List Accounts', 'x-category': 'Account'})
    name: Optional[str] = Field(None)
    domain: Optional[str] = Field(None)
    owner_email: Optional[str] = Field(None)
    tags: Optional[list[str]] = Field(None)
    page_after: Optional[str] = Field(None)
    page_size: Optional[int] = Field(100, ge=1, le=100)

class AmplemarketGetAccountConfig(AmplemarketInput):
    'Retrieve Account'
    operation: Literal['get_account'] = Field('get_account', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'Retrieve Account', 'x-category': 'Account'})
    account_id: str = Field(..., min_length=1, max_length=200)

class AmplemarketListSequencesConfig(AmplemarketInput):
    'List Sequences'
    operation: Literal['list_sequences'] = Field('list_sequences', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'List Sequences', 'x-category': 'Sequences'})
    page_size: Optional[int] = Field(100, ge=1, le=100)
    page_after: Optional[str] = Field(None)
    page_before: Optional[str] = Field(None)
    status: Optional[str] = Field(None)
    created_by_user_id: Optional[str] = Field(None)
    created_by_user_email: Optional[str] = Field(None)
    name: Optional[str] = Field(None)

class AmplemarketAddLeadsToSequenceConfigLeadsitemRouting(AmplemarketInput):
    salesforce_account_id: Optional[str] = Field(None, description='Salesforce Account ID to use for account association.\n\n> **Notes**\n> - When provided, Amplemarket treats this as the authoritative account and uses it instead of domain-based account matching.\n> - If a matching contact already exists under another account, Amplemarket re-associates it to the provided Salesforce account using its standard CRM behavior.\n> - If omitted, null, or empty, Amplemarket falls back to the default account matching behavior.\n')

class AmplemarketAddLeadsToSequenceConfigLeadsitemOverrides(AmplemarketInput):
    ignore_recently_contacted: Optional[bool] = Field(None, description='Whether we should override recently contacted checks')
    ignore_exclusion_list: Optional[bool] = Field(None, description='Whether we should override exclusion list ')
    ignore_duplicate_leads_in_other_draft_sequences: Optional[bool] = Field(None, description='Whether we should allow leads present in other draft sequences')
    ignore_duplicate_leads_in_other_active_sequences: Optional[bool] = Field(None, description='Whether we should allow leads present in other active sequences')

class AmplemarketAddLeadsToSequenceConfigLeadsitem(AmplemarketInput):
    email: Optional[str] = Field(None, json_schema_extra={'format': 'email'})
    linkedin_url: Optional[str] = Field(None, json_schema_extra={'format': 'uri'})
    data: Optional[dict[str, Optional[str]]] = Field(None, description='Additional lead data fields')
    routing: Optional[AmplemarketAddLeadsToSequenceConfigLeadsitemRouting] = Field(None, description='Account routing options')
    overrides: Optional[AmplemarketAddLeadsToSequenceConfigLeadsitemOverrides] = Field(None)

class AmplemarketAddLeadsToSequenceConfigSettings(AmplemarketInput):
    leads_distribution: Optional[Literal['sequence_senders', 'custom_mailboxes']] = Field(None)
    mailboxes: Optional[list[str]] = Field(None, description='Mailboxes to choose from when distributing with custom_mailboxes')

class AmplemarketAddLeadsToSequenceConfig(AmplemarketInput):
    'Add leads'
    operation: Literal['add_leads_to_sequence'] = Field('add_leads_to_sequence', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'Add leads', 'x-category': 'Sequences'})
    sequence_id: str = Field(..., min_length=1, max_length=200)
    leads: list[AmplemarketAddLeadsToSequenceConfigLeadsitem] = Field(..., description='Leads to be added to the sequence')
    settings: Optional[AmplemarketAddLeadsToSequenceConfigSettings] = Field(None)

class AmplemarketListTasksConfig(AmplemarketInput):
    'List tasks'
    operation: Literal['list_tasks'] = Field('list_tasks', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'List tasks', 'x-category': 'Tasks'})
    page_size: Optional[int] = Field(100, ge=1, le=100)
    page_after: Optional[str] = Field(None)
    page_before: Optional[str] = Field(None)
    automatic: Optional[bool] = Field(None)
    type: Optional[str] = Field(None)
    status: Optional[str] = Field(None)
    contact_local_time_from: Optional[int] = Field(None, ge=0, le=23)
    contact_local_time_to: Optional[int] = Field(None, ge=0, le=23)
    message_opens: Optional[int] = Field(None, ge=0)
    keyword: Optional[str] = Field(None)
    sequence_key: Optional[str] = Field(None)
    user_id: str = Field(...)

class AmplemarketCompleteTaskConfig(AmplemarketInput):
    'Complete task'
    operation: Literal['complete_task'] = Field('complete_task', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'Complete task', 'x-category': 'Tasks'})
    task_id: str = Field(..., min_length=1, max_length=200)
    set_lead_to_completed: Optional[bool] = Field(False)

class AmplemarketSkipTaskConfig(AmplemarketInput):
    'Skip task'
    operation: Literal['skip_task'] = Field('skip_task', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'Skip task', 'x-category': 'Tasks'})
    task_id: str = Field(..., min_length=1, max_length=200)

class AmplemarketListExcludedEmailsConfig(AmplemarketInput):
    'List excluded emails'
    operation: Literal['list_excluded_emails'] = Field('list_excluded_emails', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'List excluded emails', 'x-category': 'Exclusion lists'})
    page_size: Optional[int] = Field(100, ge=1, le=100)
    page_after: Optional[str] = Field(None)
    page_before: Optional[str] = Field(None)
    filter_email: Optional[str] = Field(None)

class AmplemarketCreateEmailExclusionsConfigExcludedEmailsitem(AmplemarketInput):
    email: Optional[str] = Field(None)

class AmplemarketCreateEmailExclusionsConfig(AmplemarketInput):
    'Create email exclusions'
    operation: Literal['create_email_exclusions'] = Field('create_email_exclusions', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'Create email exclusions', 'x-category': 'Exclusion lists'})
    excluded_emails: list[AmplemarketCreateEmailExclusionsConfigExcludedEmailsitem] = Field(...)

class AmplemarketDeleteEmailExclusionsConfigExcludedEmailsitem(AmplemarketInput):
    email: Optional[str] = Field(None)

class AmplemarketDeleteEmailExclusionsConfig(AmplemarketInput):
    'Delete email exclusions'
    operation: Literal['delete_email_exclusions'] = Field('delete_email_exclusions', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'Delete email exclusions', 'x-category': 'Exclusion lists'})
    excluded_emails: list[AmplemarketDeleteEmailExclusionsConfigExcludedEmailsitem] = Field(...)

class AmplemarketListCallsConfig(AmplemarketInput):
    'List calls'
    operation: Literal['list_calls'] = Field('list_calls', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'List calls', 'x-category': 'Calls'})
    page_size: Optional[int] = Field(100, ge=1, le=100)
    page_after: Optional[str] = Field(None)
    page_before: Optional[str] = Field(None)
    user_id: Optional[str] = Field(None)
    from_number: Optional[str] = Field(None)
    to_number: Optional[str] = Field(None)
    direction: Optional[Literal['incoming', 'outgoing']] = Field(None)
    start_date_from: Optional[str] = Field(None)
    start_date_to: Optional[str] = Field(None)

class AmplemarketLogCallConfig(AmplemarketInput):
    'Log call'
    operation: Literal['log_call'] = Field('log_call', json_schema_extra={'ui:hidden': True, 'x-is-trigger': False, 'x-display-name': 'Log call', 'x-category': 'Calls'})
    from_number: str = Field(..., alias='from', description='The phone number that initiated the call')
    to_number: str = Field(..., alias='to', description='The phone number that received the call')
    duration: int = Field(..., description='The duration of the call in seconds')
    answered: bool = Field(..., description='A boolean indicating whether the call was answered')
    human: bool = Field(..., description='A boolean indicating whether a human answered the call or if it was detected as a machine/voicemail')
    transcription: Optional[str] = Field(None, description="The text representation of the call's audio, if available")
    recording_url: Optional[str] = Field(None, description='URL of the call recording. Amplemarket stores the URL and does not download the recording.')
    disposition_id: Optional[str] = Field(None, description='Call disposition ID. If the given disposition has its action set to "complete", the specified task will be marked as completed, along with the associated sequence lead.', json_schema_extra={'format': 'uuid'})
    task_id: str = Field(..., json_schema_extra={'format': 'uuid'})
    user_id: str = Field(..., json_schema_extra={'format': 'uuid'})

class AmplemarketOnNewCallConfig(PollTriggerConfigBase):
    operation: Literal["on_new_call"] = Field("on_new_call", json_schema_extra={"ui:hidden": True, "x-is-trigger": True, "x-display-name": "On New Call", "x-category": "Triggers"})
    user_id: Optional[str] = Field(None, description="Only watch calls for this user ID")
    start_date_from: Optional[str] = Field(None, description="Optional ISO 8601 lower bound. Polls newest-first calls; disconnected calls are omitted by Amplemarket.")


AmplemarketConfig = Annotated[Union[AmplemarketGetAccountInfoConfig, AmplemarketListUsersConfig, AmplemarketFindPersonConfig, AmplemarketFindCompanyConfig, AmplemarketListLeadListsConfig, AmplemarketCreateLeadListConfig, AmplemarketGetLeadListConfig, AmplemarketAddLeadsToListConfig, AmplemarketListContactsConfig, AmplemarketCreateContactConfig, AmplemarketGetContactConfig, AmplemarketGetContactByEmailConfig, AmplemarketListAccountsConfig, AmplemarketGetAccountConfig, AmplemarketListSequencesConfig, AmplemarketAddLeadsToSequenceConfig, AmplemarketListTasksConfig, AmplemarketCompleteTaskConfig, AmplemarketSkipTaskConfig, AmplemarketListExcludedEmailsConfig, AmplemarketCreateEmailExclusionsConfig, AmplemarketDeleteEmailExclusionsConfig, AmplemarketListCallsConfig, AmplemarketLogCallConfig, AmplemarketOnNewCallConfig], Field(discriminator="operation")]


class AmplemarketNodeConfig(NodeConfig[AmplemarketConfig, AmplemarketAPIKeyCredential]):
    pass


OPERATIONS = {'get_account_info': {'method': 'GET',
                      'path': '/account-info',
                      'query': {},
                      'path_fields': {},
                      'body_fields': []},
 'list_users': {'method': 'GET',
                'path': '/users',
                'query': {'page_size': 'page[size]',
                          'page_after': 'page[after]',
                          'page_before': 'page[before]',
                          'status': 'status',
                          'role': 'role',
                          'email': 'email'},
                'path_fields': {},
                'body_fields': []},
 'find_person': {'method': 'GET',
                 'path': '/people/find',
                 'query': {'email': 'email',
                           'linkedin_url': 'linkedin_url',
                           'name': 'name',
                           'title': 'title',
                           'company_name': 'company_name',
                           'company_domain': 'company_domain',
                           'reveal_email': 'reveal_email',
                           'reveal_phone_numbers': 'reveal_phone_numbers'},
                 'path_fields': {},
                 'body_fields': []},
 'find_company': {'method': 'GET',
                  'path': '/companies/find',
                  'query': {'domain': 'domain', 'linkedin_url': 'linkedin_url'},
                  'path_fields': {},
                  'body_fields': []},
 'list_lead_lists': {'method': 'GET',
                     'path': '/lead-lists',
                     'query': {'page_size': 'page[size]',
                               'page_after': 'page[after]',
                               'page_before': 'page[before]',
                               'status': 'status',
                               'owner_id': 'owner_id',
                               'owner_email': 'owner_email'},
                     'path_fields': {},
                     'body_fields': []},
 'create_lead_list': {'method': 'POST',
                      'path': '/lead-lists',
                      'query': {},
                      'path_fields': {},
                      'body_fields': ['name', 'shared', 'visible', 'owner', 'type', 'options', 'leads']},
 'get_lead_list': {'method': 'GET',
                   'path': '/lead-lists/{id}',
                   'query': {'page_size': 'page[size]',
                             'page_after': 'page[after]',
                             'page_before': 'page[before]'},
                   'path_fields': {'lead_list_id': 'id'},
                   'body_fields': []},
 'add_leads_to_list': {'method': 'POST',
                       'path': '/lead-lists/{id}/leads',
                       'query': {},
                       'path_fields': {'lead_list_id': 'id'},
                       'body_fields': ['type', 'leads']},
 'list_contacts': {'method': 'GET',
                   'path': '/contacts',
                   'query': {'name': 'name', 'account_id': 'account_id', 'ids': 'ids[]'},
                   'path_fields': {},
                   'body_fields': []},
 'create_contact': {'method': 'POST',
                    'path': '/contacts',
                    'query': {},
                    'path_fields': {},
                    'body_fields': ['email',
                                    'first_name',
                                    'last_name',
                                    'title',
                                    'city',
                                    'state',
                                    'country',
                                    'industry',
                                    'linkedin_url',
                                    'owner_email',
                                    'account_id',
                                    'crm_account_id',
                                    'company_domain',
                                    'company_name',
                                    'phone_numbers']},
 'get_contact': {'method': 'GET',
                 'path': '/contacts/{id}',
                 'query': {},
                 'path_fields': {'contact_id': 'id'},
                 'body_fields': []},
 'get_contact_by_email': {'method': 'GET',
                          'path': '/contacts/email/{email}',
                          'query': {},
                          'path_fields': {'email': 'email'},
                          'body_fields': []},
 'list_accounts': {'method': 'GET',
                   'path': '/accounts',
                   'query': {'name': 'name',
                             'domain': 'domain',
                             'owner_email': 'owner_email',
                             'tags': 'tags[]',
                             'page_after': 'page[after]',
                             'page_size': 'page[size]'},
                   'path_fields': {},
                   'body_fields': []},
 'get_account': {'method': 'GET',
                 'path': '/accounts/{id}',
                 'query': {},
                 'path_fields': {'account_id': 'id'},
                 'body_fields': []},
 'list_sequences': {'method': 'GET',
                    'path': '/sequences',
                    'query': {'page_size': 'page[size]',
                              'page_after': 'page[after]',
                              'page_before': 'page[before]',
                              'status': 'status',
                              'created_by_user_id': 'created_by_user_id',
                              'created_by_user_email': 'created_by_user_email',
                              'name': 'name'},
                    'path_fields': {},
                    'body_fields': []},
 'add_leads_to_sequence': {'method': 'POST',
                           'path': '/sequences/{id}/leads',
                           'query': {},
                           'path_fields': {'sequence_id': 'id'},
                           'body_fields': ['leads', 'settings']},
 'list_tasks': {'method': 'GET',
                'path': '/tasks',
                'query': {'page_size': 'page[size]',
                          'page_after': 'page[after]',
                          'page_before': 'page[before]',
                          'automatic': 'automatic',
                          'type': 'type',
                          'status': 'status',
                          'contact_local_time_from': 'contact_local_time_from',
                          'contact_local_time_to': 'contact_local_time_to',
                          'message_opens': 'message_opens',
                          'keyword': 'keyword',
                          'sequence_key': 'sequence_key',
                          'user_id': 'user_id'},
                'path_fields': {},
                'body_fields': []},
 'complete_task': {'method': 'POST',
                   'path': '/tasks/{id}/complete',
                   'query': {},
                   'path_fields': {'task_id': 'id'},
                   'body_fields': ['set_lead_to_completed']},
 'skip_task': {'method': 'POST',
               'path': '/tasks/{id}/skip',
               'query': {},
               'path_fields': {'task_id': 'id'},
               'body_fields': []},
 'list_excluded_emails': {'method': 'GET',
                          'path': '/excluded-emails',
                          'query': {'page_size': 'page[size]',
                                    'page_after': 'page[after]',
                                    'page_before': 'page[before]',
                                    'filter_email': 'filter[email]'},
                          'path_fields': {},
                          'body_fields': []},
 'create_email_exclusions': {'method': 'POST',
                             'path': '/excluded-emails',
                             'query': {},
                             'path_fields': {},
                             'body_fields': ['excluded_emails']},
 'delete_email_exclusions': {'method': 'DELETE',
                             'path': '/excluded-emails',
                             'query': {},
                             'path_fields': {},
                             'body_fields': ['excluded_emails']},
 'list_calls': {'method': 'GET',
                'path': '/calls',
                'query': {'page_size': 'page[size]',
                          'page_after': 'page[after]',
                          'page_before': 'page[before]',
                          'user_id': 'user_id',
                          'from_number': 'from',
                          'to_number': 'to',
                          'direction': 'direction',
                          'start_date_from': 'start_date_from',
                          'start_date_to': 'start_date_to'},
                'path_fields': {},
                'body_fields': []},
 'log_call': {'method': 'POST',
              'path': '/calls',
              'query': {},
              'path_fields': {},
              'body_fields': ['from_number',
                              'to_number',
                              'duration',
                              'answered',
                              'human',
                              'transcription',
                              'recording_url',
                              'disposition_id',
                              'task_id',
                              'user_id']}}

class AmplemarketNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-amplemarket"
    connection_evidence = ConnectionEvidence(noun="Amplemarket account", identity_operation="get_account_info", identity_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return AmplemarketNodeConfig

    async def _request(self, method, path, *, params=None, body=None):
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect an Amplemarket API key")
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path, params=params,
                    json=body, headers={"Authorization": "Bearer " + credential.api_key, "Accept": "application/json"})
        except httpx.RequestError:
            raise ValueError("Amplemarket request could not be completed; check the provider before retrying writes") from None
        if not response.is_success:
            # Keep the provider's rejection words for the connect seam, without exposing the key.
            message = response.text.replace(credential.api_key, "[redacted]")[:1000]
            raise ValueError(f"Amplemarket HTTP {response.status_code}: {message}")
        if response.status_code == 204 or not response.content:
            return None
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Amplemarket returned an unreadable JSON response") from None
        if not isinstance(payload, (dict, list)):
            raise ValueError("Amplemarket returned an unexpected response shape")
        return payload

    @staticmethod
    def _next_cursor(payload, path):
        links = payload.get("_links", {})
        next_link = links.get("next") if isinstance(links, dict) else None
        if not next_link:
            return None
        href = next_link.get("href") if isinstance(next_link, dict) else None
        if not isinstance(href, str):
            raise ValueError("Amplemarket returned an invalid next page")
        url = urlsplit(href)
        if url.scheme not in ("", "https") or url.netloc not in ("", "api.amplemarket.com") or url.path != path or url.fragment:
            raise ValueError("Amplemarket returned an unexpected pagination destination")
        values = parse_qs(url.query).get("page[after]")
        if not values or len(values) != 1 or not values[0]:
            raise ValueError("Amplemarket next page has no forward cursor")
        return values[0]

    async def _poll_calls(self, config):
        params = {"page[size]": "100"}
        if config.user_id:
            params["user_id"] = config.user_id
        if config.start_date_from:
            params["start_date_from"] = config.start_date_from
        calls, seen_cursors = [], set()
        for _ in range(20):
            payload = await self._request("GET", "/calls", params=params)
            rows = payload.get("calls") if isinstance(payload, dict) else None
            if not isinstance(rows, list) or any(not isinstance(row, dict) or not row.get("id") for row in rows):
                raise ValueError("Amplemarket calls response has no identifiable calls")
            calls.extend(rows)
            cursor = self._next_cursor(payload, "/calls")
            if cursor is None:
                break
            if cursor in seen_cursors:
                raise ValueError("Amplemarket repeated a pagination cursor")
            seen_cursors.add(cursor)
            params["page[after]"] = cursor
        else:
            raise ValueError("More than 2,000 calls in this scope; choose a user or a later start date")
        fresh = await self._filter_unseen(calls, lambda row: str(row["id"]))
        return {"calls": fresh, "new_call_count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output, config):
        if config.get("operation") == "on_new_call":
            return bool(output.get("new_call_count"))
        return True

    @classmethod
    def resolve_agent_event(cls, output):
        calls = output.get("calls") if isinstance(output, dict) else None
        if not isinstance(calls, list):
            return super().resolve_agent_event(output)
        if not calls:
            return None
        lines = []
        for call in calls[:10]:
            lines.append(f"- {call.get('user_email') or call.get('user_id') or 'A user'} logged a {call.get('direction') or ''} call from {call.get('from')} to {call.get('to')} at {call.get('start_date')}; duration {call.get('duration')} seconds, answered {call.get('answered')}. Notes: {call.get('notes') or ''}. Call ID: {call.get('id')}; task ID: {call.get('task_id')}; recording: {call.get('recording_url') or 'unavailable'}")
        return {"text": f"Amplemarket: {len(calls)} new call(s)\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        config = self.config.config
        if isinstance(config, AmplemarketOnNewCallConfig):
            return await self._poll_calls(config)
        op = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True)
        path = op["path"]
        for field, marker in op["path_fields"].items():
            value = values[field]
            if marker == "id" and not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value):
                raise ValueError("Use a single Amplemarket resource ID")
            path = path.replace("{" + marker + "}", quote(value, safe=""))
        params = {}
        for field, wire in op["query"].items():
            if field in values:
                value = values[field]
                params[wire] = str(value).lower() if isinstance(value, bool) else value
        # Serialize nested Pydantic inputs with the API's original field names.
        body = json.loads(config.model_dump_json(include=set(op["body_fields"]), by_alias=True, exclude_none=True)) if op["body_fields"] else None
        payload = await self._request(op["method"], path, params=params or None, body=body)
        return {"status": "success", "data": payload}
