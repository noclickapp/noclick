"""Lead Prosper API v2: campaign traffic controls, leads, clients and reporting.

Wire contract: https://api.leadprosper.io/public/docs/openapi-v2.json
Authentication is an account API token; the API defines no per-endpoint scopes.
New-lead polling reads the documented newest-first, date-filtered lead list.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StrictBool, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.leadprosper.io/public"
CREDENTIAL_TYPE = "lead_prosper_api_token"


class LeadProsperAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Lead Prosper API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.leadprosper.io/public/docs",
            "x-credential-instructions": "In Lead Prosper, open Settings → API and copy an account API token. Paste only the token. NoClick sends it as a Bearer header to api.leadprosper.io. Campaign reads verify access; write permissions depend on the token owner's role.",
        })
    credential_type: Literal["lead_prosper_api_token"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the API token, without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="after")
    def constraints(self):
        if hasattr(self, "start_date"):
            try:
                start = datetime.fromisoformat(self.start_date)
                end = datetime.fromisoformat(self.end_date)
                if start > end:
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValueError("Use an ordered date window in YYYY-MM-DD or YYYY-MM-DD HH:MM:SS format") from None
        if self.operation == "update_campaign" and self.name is None and self.public_name is None:
            raise ValueError("Provide a campaign name or public name to change")
        if self.operation == "set_caps" and not any(getattr(self, k) is not None for k in CAP_FIELDS):
            raise ValueError("Provide at least one cap; zero means unlimited")
        if self.operation in {"list_caps", "list_filters"} and self.target is not None and self.scope is None:
            raise ValueError("A target requires its scope")
        if self.operation == "list_filters" and self.scope == "global" and self.target is not None:
            raise ValueError("Global filters do not take a target")
        return self


class LeadProsperListCampaignsConfig(_Input):
    """List campaigns."""
    operation: Literal['list_campaigns'] = Field('list_campaigns', title='List campaigns', json_schema_extra={'ui:hidden': True, 'x-display-name': 'List campaigns', 'x-is-trigger': False, 'x-method-kind': 'read'})
    view: Optional[Literal['short', 'basic', 'full']] = Field(None, title='View', description="How much of each campaign to return: a preset of `select`. Not with `select`.\n\n| `view` | Returns |\n|---|---|\n| `short` | `id`, `name`, `public_name`, `campaign_type`, `setup_complete`. For finding a campaign by name. |\n| `basic` (default) | `short`, plus `distribution` and `fields`; each supplier's `id`, `name`, `position`, `client`, `paused`, `test_mode`, `api_specs_url` and `pricing_summary`; each buyer's `id`, `name`, `position`, `client`, `paused`, `delivery.type`, `weight`, `weight_share`, `buyer_group_id` and `pricing_summary`. |\n| `full` | everything: also `settings`, each supplier's and buyer's `pricing` in the shape the update takes, a supplier's `bidding`, and a buyer's whole `delivery`. |")
    setup: Optional[Literal['complete', 'incomplete', 'all']] = Field(None, title='Setup', description='Which campaigns to list, by `setup_complete`: `complete`, those with at least one supplier and one buyer; `incomplete`, those still missing one; `all`, both. Defaults to `complete`.')
    name_contains: Optional[str] = Field(None, title='Name Contains', description='Only campaigns whose name or public name contains this text. Case-insensitive.', min_length=1, max_length=4096)
    buyers: Optional[Literal['active', 'all']] = Field(None, title='Buyers', description='Which buyers to include. `active`, the default, leaves out buyers that are paused, because a paused buyer is not receiving leads; `all` includes them. Suppliers are unaffected either way - they always appear, with their own `paused` flag. Ignored under `view=short`, which carries no buyers at all.')
    limit: Optional[int] = Field(None, title='Limit', description='Campaigns per page. 100 is also the ceiling, so this can only ask for a smaller page.', le=100)
    search_after: Optional[str] = Field(None, title='Search After', description='The `search_after` value from the previous page. Omit for the first page.', min_length=1, max_length=4096)

class LeadProsperGetCampaignConfig(_Input):
    """Get a campaign."""
    operation: Literal['get_campaign'] = Field('get_campaign', title='Get a campaign', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Get a campaign', 'x-is-trigger': False, 'x-method-kind': 'read'})
    id: int = Field(..., title='Id', description='Campaign id.', ge=1)
    view: Optional[Literal['short', 'basic', 'full']] = Field(None, title='View', description="How much of each campaign to return: a preset of `select`. Not with `select`.\n\n| `view` | Returns |\n|---|---|\n| `short` | `id`, `name`, `public_name`, `campaign_type`, `setup_complete`. For finding a campaign by name. |\n| `basic` (default) | `short`, plus `distribution` and `fields`; each supplier's `id`, `name`, `position`, `client`, `paused`, `test_mode`, `api_specs_url` and `pricing_summary`; each buyer's `id`, `name`, `position`, `client`, `paused`, `delivery.type`, `weight`, `weight_share`, `buyer_group_id` and `pricing_summary`. |\n| `full` | everything: also `settings`, each supplier's and buyer's `pricing` in the shape the update takes, a supplier's `bidding`, and a buyer's whole `delivery`. |")
    buyers: Optional[Literal['active', 'all']] = Field(None, title='Buyers', description='Which buyers to include: `active` (the default) leaves out paused buyers, `all` includes them.')

class LeadProsperCreateCampaignConfig(_Input):
    """Create a campaign."""
    operation: Literal['create_campaign'] = Field('create_campaign', title='Create a campaign', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Create a campaign', 'x-is-trigger': False, 'x-method-kind': 'write'})
    name: str = Field(..., title='Name', description="The campaign's name.", min_length=1, max_length=100)
    public_name: Optional[str] = Field(None, title='Public Name', description='The name shown to suppliers. `name` when left out.', min_length=1, max_length=150)
    campaign_type: Literal['direct_post', 'ping_post_exchange', 'one_to_one'] = Field(..., title='Campaign Type', description='How the campaign takes leads.')

class LeadProsperUpdateCampaignConfig(_Input):
    """Update a campaign."""
    operation: Literal['update_campaign'] = Field('update_campaign', title='Update a campaign', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Update a campaign', 'x-is-trigger': False, 'x-method-kind': 'write'})
    campaign: int = Field(..., title='Campaign', description='Campaign id.', ge=1)
    name: Optional[str] = Field(None, title='Name', description="The campaign's name.", min_length=1, max_length=100)
    public_name: Optional[str] = Field(None, title='Public Name', description='The name shown to suppliers. `null` clears it, and `name` is shown.', min_length=1, max_length=150)

class LeadProsperPauseBuyerConfig(_Input):
    """Pause a buyer."""
    operation: Literal['pause_buyer'] = Field('pause_buyer', title='Pause a buyer', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Pause a buyer', 'x-is-trigger': False, 'x-method-kind': 'write'})
    campaign: int = Field(..., title='Campaign', description='Campaign id.', ge=1)
    buyer: int = Field(..., title='Buyer', description='Buyer id.', ge=1)

class LeadProsperResumeBuyerConfig(_Input):
    """Resume a buyer."""
    operation: Literal['resume_buyer'] = Field('resume_buyer', title='Resume a buyer', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Resume a buyer', 'x-is-trigger': False, 'x-method-kind': 'write'})
    campaign: int = Field(..., title='Campaign', description='Campaign id.', ge=1)
    buyer: int = Field(..., title='Buyer', description='Buyer id.', ge=1)

class LeadProsperPauseSupplierConfig(_Input):
    """Pause a supplier."""
    operation: Literal['pause_supplier'] = Field('pause_supplier', title='Pause a supplier', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Pause a supplier', 'x-is-trigger': False, 'x-method-kind': 'write'})
    campaign: int = Field(..., title='Campaign', description='Campaign id.', ge=1)
    supplier: int = Field(..., title='Supplier', description='Supplier id.', ge=1)

class LeadProsperResumeSupplierConfig(_Input):
    """Resume a supplier."""
    operation: Literal['resume_supplier'] = Field('resume_supplier', title='Resume a supplier', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Resume a supplier', 'x-is-trigger': False, 'x-method-kind': 'write'})
    campaign: int = Field(..., title='Campaign', description='Campaign id.', ge=1)
    supplier: int = Field(..., title='Supplier', description='Supplier id.', ge=1)

class LeadProsperListCapsConfig(_Input):
    """Read caps."""
    operation: Literal['list_caps'] = Field('list_caps', title='Read caps', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Read caps', 'x-is-trigger': False, 'x-method-kind': 'read'})
    campaign: int = Field(..., title='Campaign', description='Campaign id.', ge=1)
    scope: Optional[Literal['suppliers', 'buyers']] = Field(None, title='Scope', description='`suppliers` or `buyers`. Omit to cover both.')
    target: Optional[int] = Field(None, title='Target', description='One supplier or buyer id. Omit to cover all of them within the scope.', ge=1)
    limit: Optional[int] = Field(None, title='Limit', description='Entries per page.', le=250)
    search_after: Optional[str] = Field(None, title='Search After', description='The `search_after` value from the previous page. Omit for the first page.', min_length=1, max_length=4096)

class LeadProsperSetCapsConfig(_Input):
    """Set caps."""
    operation: Literal['set_caps'] = Field('set_caps', title='Set caps', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Set caps', 'x-is-trigger': False, 'x-method-kind': 'write'})
    campaign: int = Field(..., title='Campaign', description='Campaign id.', ge=1)
    scope: Literal['suppliers', 'buyers'] = Field(..., title='Scope', description='`suppliers` or `buyers`.')
    target: int = Field(..., title='Target', description='The supplier or buyer id.', ge=1)
    leads_day: Optional[int] = Field(None, ge=0, title='Day leads cap', description="Zero means unlimited; omitted windows stay unchanged.")
    leads_week: Optional[int] = Field(None, ge=0, title='Week leads cap', description="Zero means unlimited; omitted windows stay unchanged.")
    leads_month: Optional[int] = Field(None, ge=0, title='Month leads cap', description="Zero means unlimited; omitted windows stay unchanged.")
    leads_total: Optional[int] = Field(None, ge=0, title='Total leads cap', description="Zero means unlimited; omitted windows stay unchanged.")
    budget_day: Optional[float] = Field(None, ge=0, title='Day budget cap', description="Zero means unlimited; omitted windows stay unchanged.")
    budget_week: Optional[float] = Field(None, ge=0, title='Week budget cap', description="Zero means unlimited; omitted windows stay unchanged.")
    budget_month: Optional[float] = Field(None, ge=0, title='Month budget cap', description="Zero means unlimited; omitted windows stay unchanged.")
    budget_total: Optional[float] = Field(None, ge=0, title='Total budget cap', description="Zero means unlimited; omitted windows stay unchanged.")

class LeadProsperListFiltersConfig(_Input):
    """List filters."""
    operation: Literal['list_filters'] = Field('list_filters', title='List filters', json_schema_extra={'ui:hidden': True, 'x-display-name': 'List filters', 'x-is-trigger': False, 'x-method-kind': 'read'})
    campaign: int = Field(..., title='Campaign', description='Campaign id.', ge=1)
    scope: Optional[Literal['suppliers', 'buyers', 'buyer_groups', 'global']] = Field(None, title='Scope', description='`suppliers`, `buyers`, `buyer_groups` or `global`. Omit to cover every scope.')
    target: Optional[int] = Field(None, title='Target', description='One supplier or buyer id, or on `buyer_groups` one buyer group id. Omit to cover all of them within the scope.', ge=1)
    limit: Optional[int] = Field(None, title='Limit', description='Entries per page.', le=250)
    search_after: Optional[str] = Field(None, title='Search After', description='The `search_after` value from the previous page. Omit for the first page.', min_length=1, max_length=4096)

class LeadProsperPauseFilterConfig(_Input):
    """Pause a filter."""
    operation: Literal['pause_filter'] = Field('pause_filter', title='Pause a filter', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Pause a filter', 'x-is-trigger': False, 'x-method-kind': 'write'})
    filter: int = Field(..., title='Filter', description='Filter id. Globally unique.', ge=1)

class LeadProsperResumeFilterConfig(_Input):
    """Resume a filter."""
    operation: Literal['resume_filter'] = Field('resume_filter', title='Resume a filter', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Resume a filter', 'x-is-trigger': False, 'x-method-kind': 'write'})
    filter: int = Field(..., title='Filter', description='Filter id. Globally unique.', ge=1)

class LeadProsperListLeadsConfig(_Input):
    """List leads."""
    operation: Literal['list_leads'] = Field('list_leads', title='List leads', json_schema_extra={'ui:hidden': True, 'x-display-name': 'List leads', 'x-is-trigger': False, 'x-method-kind': 'read'})
    campaign: int = Field(..., title='Campaign', description='Campaign id.', ge=1)
    start_date: str = Field(..., title='Start Date', description='Start of the window, `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`.', min_length=1, max_length=4096)
    end_date: str = Field(..., title='End Date', description='End of the window, inclusive.', min_length=1, max_length=4096)
    timezone: Optional[str] = Field(None, title='Timezone', description='IANA timezone the window is read in. Defaults to UTC.', min_length=1, max_length=4096)
    status: Optional[Literal['accepted', 'duplicated', 'error']] = Field(None, title='Status', description='Only leads with this outcome.')
    supplier: Optional[int] = Field(None, title='Supplier', description='Only leads from this supplier.', ge=1)
    buyer: Optional[int] = Field(None, title='Buyer', description='Only leads that reached this buyer. Excludes test leads, so it cannot be combined with `test=true`.', ge=1)
    select: Optional[str] = Field(None, title='Select', description='Return only these `lead_data` fields, comma-separated - e.g. `email,state`. Everything else about a lead is always returned. Omit for all fields.', min_length=1, max_length=4096)
    limit: Optional[int] = Field(None, title='Limit', description='Leads per page, up to 500. Default 100. Page with `search_after` rather than raising this.', ge=1, le=500)
    test: Optional[StrictBool] = Field(None, title='Test', description='Only test leads, or only live ones.')
    search_after: Optional[int] = Field(None, title="Search After", description="Paste the decimal cursor from the previous lead page; sent as the documented integer query parameter.", ge=0)

class LeadProsperGetLeadConfig(_Input):
    """Get a lead."""
    operation: Literal['get_lead'] = Field('get_lead', title='Get a lead', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Get a lead', 'x-is-trigger': False, 'x-method-kind': 'read'})
    id: str = Field(..., title='Lead ID', description='Lead id.', min_length=1, max_length=4096, pattern=r'^[A-Za-z0-9_-]+$')

class LeadProsperReturnLeadConfig(_Input):
    """Return a lead."""
    operation: Literal['return_lead'] = Field('return_lead', title='Return a lead', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Return a lead', 'x-is-trigger': False, 'x-method-kind': 'write'})
    lead_id: str = Field(..., title='Lead Id', description='The lead to return.', min_length=1, max_length=4096)
    reason: str = Field(..., title='Reason', description='Why it is being returned.', min_length=1, max_length=4096)
    portal_refund: Optional[StrictBool] = Field(None, title='Portal Refund', description='Also refund the buyer in the portal.')

class LeadProsperListClientsConfig(_Input):
    """List clients."""
    operation: Literal['list_clients'] = Field('list_clients', title='List clients', json_schema_extra={'ui:hidden': True, 'x-display-name': 'List clients', 'x-is-trigger': False, 'x-method-kind': 'read'})
    email: Optional[str] = Field(None, title='Email', description='An email address, matched exactly.', min_length=1, max_length=4096)
    phone: Optional[str] = Field(None, title='Phone', description='A phone number, exactly as stored.', min_length=1, max_length=4096)
    search_after: Optional[str] = Field(None, title='Search After', description='The `search_after` value from the previous page. Omit for the first page.', min_length=1, max_length=4096)
    include_deleted: Optional[StrictBool] = Field(None, title='Include Deleted', description='Include clients that have been deleted.')

class LeadProsperCreateClientConfig(_Input):
    """Create a client."""
    operation: Literal['create_client'] = Field('create_client', title='Create a client', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Create a client', 'x-is-trigger': False, 'x-method-kind': 'write'})
    company: str = Field(..., title='Company', min_length=1, max_length=255)
    email: Optional[EmailStr] = Field(None, title='Email', description='Unique within the account.')
    first_name: Optional[str] = Field(None, title='First Name', min_length=1, max_length=255)
    last_name: Optional[str] = Field(None, title='Last Name', min_length=1, max_length=255)
    phone: Optional[str] = Field(None, title='Phone', description='Stored as given.', min_length=10, max_length=15)

class LeadProsperCampaignStatisticsConfig(_Input):
    """Campaign statistics."""
    operation: Literal['campaign_statistics'] = Field('campaign_statistics', title='Campaign statistics', json_schema_extra={'ui:hidden': True, 'x-display-name': 'Campaign statistics', 'x-is-trigger': False, 'x-method-kind': 'read'})
    start_date: str = Field(..., title='Start Date', description='Start of the window, `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`. Within the last 2 years.', min_length=1, max_length=4096)
    end_date: str = Field(..., title='End Date', description='End of the window, inclusive.', min_length=1, max_length=4096)
    timezone: Optional[str] = Field(None, title='Timezone', description='IANA timezone the window is read in. Defaults to UTC.', min_length=1, max_length=4096)
    group: Optional[Literal['hour', 'day', 'week', 'month']] = Field(None, title='Group', description='Bucket size for the breakdown. `hour` only for a window of up to 7 days.')

CAP_FIELDS = ('leads_day', 'leads_week', 'leads_month', 'leads_total', 'budget_day', 'budget_week', 'budget_month', 'budget_total')

OPERATIONS = {'list_campaigns': {'method': 'GET',
                    'path': '/v2/campaigns',
                    'query': ('view', 'setup', 'name_contains', 'buyers', 'limit', 'search_after'),
                    'body': (),
                    'provider_operation': 'listCampaigns'},
 'get_campaign': {'method': 'GET',
                  'path': '/v2/campaigns/{id}',
                  'query': ('view', 'buyers'),
                  'body': (),
                  'provider_operation': 'getCampaign'},
 'create_campaign': {'method': 'POST',
                     'path': '/v2/campaigns',
                     'query': (),
                     'body': ('name', 'public_name', 'campaign_type'),
                     'provider_operation': 'createCampaign'},
 'update_campaign': {'method': 'PATCH',
                     'path': '/v2/campaigns/{campaign}',
                     'query': (),
                     'body': ('name', 'public_name'),
                     'provider_operation': 'updateCampaign'},
 'pause_buyer': {'method': 'GET',
                 'path': '/v2/campaigns/{campaign}/buyer/{buyer}/pause',
                 'query': (),
                 'body': (),
                 'provider_operation': 'pauseBuyer'},
 'resume_buyer': {'method': 'GET',
                  'path': '/v2/campaigns/{campaign}/buyer/{buyer}/resume',
                  'query': (),
                  'body': (),
                  'provider_operation': 'resumeBuyer'},
 'pause_supplier': {'method': 'GET',
                    'path': '/v2/campaigns/{campaign}/supplier/{supplier}/pause',
                    'query': (),
                    'body': (),
                    'provider_operation': 'pauseSupplier'},
 'resume_supplier': {'method': 'GET',
                     'path': '/v2/campaigns/{campaign}/supplier/{supplier}/resume',
                     'query': (),
                     'body': (),
                     'provider_operation': 'resumeSupplier'},
 'list_caps': {'method': 'GET',
               'path': '/v2/campaigns/{campaign}/caps/{scope}/{target}',
               'query': ('limit', 'search_after'),
               'body': (),
               'provider_operation': 'listCaps'},
 'set_caps': {'method': 'PATCH',
              'path': '/v2/campaigns/{campaign}/caps/{scope}/{target}',
              'query': (),
              'body': (),
              'provider_operation': 'updateCaps'},
 'list_filters': {'method': 'GET',
                  'path': '/v2/campaigns/{campaign}/filters/{scope}/{target}',
                  'query': ('limit', 'search_after'),
                  'body': (),
                  'provider_operation': 'listFilters'},
 'pause_filter': {'method': 'POST',
                  'path': '/v2/filters/{filter}/pause',
                  'query': (),
                  'body': (),
                  'provider_operation': 'pauseFilter'},
 'resume_filter': {'method': 'POST',
                   'path': '/v2/filters/{filter}/resume',
                   'query': (),
                   'body': (),
                   'provider_operation': 'resumeFilter'},
 'list_leads': {'method': 'GET',
                'path': '/v2/leads',
                'query': ('campaign',
                          'start_date',
                          'end_date',
                          'timezone',
                          'status',
                          'supplier',
                          'buyer',
                          'select',
                          'limit',
                          'test',
                          'search_after'),
                'body': (),
                'provider_operation': 'listLeads_v2'},
 'get_lead': {'method': 'GET',
              'path': '/v2/lead/{id}',
              'query': (),
              'body': (),
              'provider_operation': 'getLead_v2'},
 'return_lead': {'method': 'POST',
                 'path': '/v2/lead/return',
                 'query': (),
                 'body': ('lead_id', 'reason', 'portal_refund'),
                 'provider_operation': 'returnLead_v2'},
 'list_clients': {'method': 'GET',
                  'path': '/v2/clients',
                  'query': ('email', 'phone', 'search_after', 'include_deleted'),
                  'body': (),
                  'provider_operation': 'listClients_v2'},
 'create_client': {'method': 'POST',
                   'path': '/v2/clients',
                   'query': (),
                   'body': ('company', 'email', 'first_name', 'last_name', 'phone'),
                   'provider_operation': 'createClient_v2'},
 'campaign_statistics': {'method': 'GET',
                         'path': '/v2/stats',
                         'query': ('start_date', 'end_date', 'timezone', 'group'),
                         'body': (),
                         'provider_operation': 'stats_v2'}}


class LeadProsperOnNewLeadConfig(PollTriggerConfigBase):
    operation: Literal["on_new_lead"] = Field("on_new_lead", title="On New Lead (Latest 500)", json_schema_extra={
        "ui:hidden": True, "x-display-name": "On New Lead (Latest 500)", "x-is-trigger": True, "x-category": "Triggers"})
    campaign: int = Field(..., ge=1, title="Campaign ID")
    lookback_hours: int = Field(48, ge=1, le=168, title="Look back (hours)",
        description="Monitor up to the latest 500 leads per poll in a rolling UTC window; already seen IDs are suppressed. Choose a window longer than the schedule interval and an interval short enough for campaign volume. The output includes the continuation cursor for further reads.")


LeadProsperConfig = Annotated[Union[LeadProsperListCampaignsConfig, LeadProsperGetCampaignConfig, LeadProsperCreateCampaignConfig, LeadProsperUpdateCampaignConfig, LeadProsperPauseBuyerConfig, LeadProsperResumeBuyerConfig, LeadProsperPauseSupplierConfig, LeadProsperResumeSupplierConfig, LeadProsperListCapsConfig, LeadProsperSetCapsConfig, LeadProsperListFiltersConfig, LeadProsperPauseFilterConfig, LeadProsperResumeFilterConfig, LeadProsperListLeadsConfig, LeadProsperGetLeadConfig, LeadProsperReturnLeadConfig, LeadProsperListClientsConfig, LeadProsperCreateClientConfig, LeadProsperCampaignStatisticsConfig, LeadProsperOnNewLeadConfig], Field(discriminator="operation")]


class LeadProsperNodeConfig(NodeConfig[LeadProsperConfig, LeadProsperAPITokenCredential]):
    pass


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(v, token) for v in value]
    if isinstance(value, dict):
        return {k: _redact(v, token) for k, v in value.items()}
    return value


class LeadProsperNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-lead-prosper"
    connection_evidence = ConnectionEvidence(operation="list_campaigns", noun="campaigns", label_keys=("name", "id"))
    edit_examples = ["Pause a Lead Prosper buyer", "Set a buyer's daily lead cap", "Return a Lead Prosper lead", "Watch a campaign for new leads"]

    @classmethod
    def get_config_model(cls):
        return LeadProsperNodeConfig

    @staticmethod
    async def _request(token, method, path, *, params=None, body=None):
        try:
            async with guarded_async_client(timeout=45, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, params=params, json=body,
                    headers={"Authorization": "Bearer " + token, "Accept": "application/json"})
        except httpx.RequestError:
            raise ValueError("Lead Prosper request did not complete; inspect any traffic-control change before retrying") from None
        try:
            payload = response.json()
        except ValueError:
            raise ValueError("Lead Prosper returned a non-JSON response") from None
        if not 200 <= response.status_code < 300 or (isinstance(payload, dict) and "status" in payload and payload["status"] == "error"):
            message = payload.get("message") if isinstance(payload, dict) else None
            raise ValueError(_redact(f"Lead Prosper API {response.status_code}: {message or 'request refused'}", token))
        if not isinstance(payload, (dict, list)):
            raise ValueError("Lead Prosper returned an unexpected response")
        return payload

    @classmethod
    async def _perform(cls, token, config):
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = spec["path"]
        for name in type(config).model_fields:
            marker = "{" + name + "}"
            if marker in path:
                value = values.get(name)
                path = path.replace("/" + marker, "" if value is None else "/" + quote(str(value), safe=""))
        params = {key: values[key] for key in spec["query"] if key in values}
        # httpx emits lowercase JSON-style boolean query values.
        body = {key: values[key] for key in spec["body"] if key in values}
        if config.operation == "set_caps":
            for kind in ("leads", "budget"):
                windows = {w: values[f"{kind}_{w}"] for w in ("day", "week", "month", "total") if f"{kind}_{w}" in values}
                if windows:
                    body[kind] = windows
        return await cls._request(token, spec["method"], path, params=params or None, body=body or None)

    async def _poll(self, token, config):
        now = datetime.now(timezone.utc)
        params = {"campaign": config.campaign, "start_date": (now - timedelta(hours=config.lookback_hours)).strftime("%Y-%m-%d %H:%M:%S"),
            "end_date": now.strftime("%Y-%m-%d %H:%M:%S"), "timezone": "UTC", "limit": 500}
        payload = await self._request(token, "GET", "/v2/leads", params=params)
        leads = payload.get("leads") if isinstance(payload, dict) else None
        if not isinstance(leads, list) or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] for row in leads):
            raise ValueError("Lead Prosper returned an invalid leads page")
        # A bounded newest-first snapshot, as disclosed in the trigger's label and help.
        # Never infer an end of history from a short page: the provider's own
        # example has two leads and a continuation cursor.
        fresh = await self._filter_unseen(leads, lambda lead: lead["id"])
        return {"leads": fresh, "new_lead_count": len(fresh),
            "search_after": payload.get("search_after"), "snapshot_limit": 500}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("new_lead_count")) if config.get("operation") == "on_new_lead" else True

    @classmethod
    def resolve_agent_event(cls, output):
        leads = output.get("leads") if isinstance(output, dict) else None
        if not isinstance(leads, list):
            return super().resolve_agent_event(output)
        if not leads:
            return None
        lines = []
        for lead in leads[:10]:
            person = lead.get("lead_data") or {}
            who = " ".join(str(person.get(k) or "") for k in ("first_name", "last_name")).strip() or "A lead"
            contact = person.get("email") or person.get("phone") or "No contact details"
            lines.append(f"- {who}: {contact}; campaign {lead.get('campaign_name') or 'Unnamed'} (ID {lead.get('campaign_id')}); status {lead.get('status')}; lead ID {lead['id']}")
        return {"text": f"Lead Prosper: {len(leads)} new lead(s).\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Lead Prosper API token")
        token, config = self.config.credentials.api_token, self.config.config
        if isinstance(config, LeadProsperOnNewLeadConfig):
            output = await self._poll(token, config)
        else:
            response = await self._perform(token, config)
            data = response.get("data", response) if isinstance(response, dict) else response
            output = {"status": "success", "data": data}
            if config.operation == "list_campaigns":
                rows = data.get("campaigns") if isinstance(data, dict) else None
                if not isinstance(rows, list):
                    raise ValueError("Lead Prosper returned an invalid campaigns page")
                output["items"] = rows
            if isinstance(data, dict) and "search_after" in data:
                output["search_after"] = data["search_after"]
        output = _redact(output, token)
        await self.emit(output)
        return output
