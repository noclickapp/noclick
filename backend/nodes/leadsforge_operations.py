"""Leadsforge Public API 1.0 request models and one-request operation catalog.

Source: https://api.leadsforge.ai/public/swagger/doc.json
"""
from __future__ import annotations
from typing import Annotated, Any, Literal, Union
from pydantic import BaseModel, ConfigDict, Field


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class LeadsforgeIncludeExcludeFilter(_Input):
    exclude: list[str] | None = Field(None)
    include: list[str] | None = Field(None)


class LeadsforgeMinMaxFilter(_Input):
    max: int | None = Field(None, strict=True)
    min: int | None = Field(None, strict=True)


class LeadsforgeIncludeExcludeAllFilter(_Input):
    exclude: list[str] | None = Field(None)
    include: list[str] | None = Field(None)
    matchAll: bool | None = Field(None, strict=True)


class LeadsforgeAnyAllFilter(_Input):
    all: list[str] | None = Field(None)
    any: list[str] | None = Field(None)


class LeadsforgeJobTitleFilter(_Input):
    exactMatch: bool | None = Field(None, strict=True)
    exclude: list[str] | None = Field(None)
    include: list[str] | None = Field(None)


class LeadsforgeLanguageFilter(_Input):
    exclude: list[str] | None = Field(None)
    include: list[str] | None = Field(None)
    primaryOnly: bool | None = Field(None, strict=True)


class LeadsforgePersonSearchFilters(_Input):
    companyBusinessModels: LeadsforgeIncludeExcludeFilter | None = Field(None)
    companyDomains: LeadsforgeIncludeExcludeFilter | None = Field(None)
    companyEmployeeNumberRange: LeadsforgeMinMaxFilter | None = Field(None)
    companyFoundedYearRange: LeadsforgeMinMaxFilter | None = Field(None)
    companyFundingRounds: LeadsforgeIncludeExcludeFilter | None = Field(None)
    companyIDs: LeadsforgeIncludeExcludeFilter | None = Field(None)
    companyIndustries: LeadsforgeIncludeExcludeFilter | None = Field(None)
    companyKeywords: LeadsforgeIncludeExcludeAllFilter | None = Field(None)
    companyLocations: LeadsforgeIncludeExcludeFilter | None = Field(None)
    companyNames: LeadsforgeIncludeExcludeFilter | None = Field(None)
    companyNiches: LeadsforgeIncludeExcludeFilter | None = Field(None)
    companyRequired: bool | None = Field(None, strict=True)
    companyRevenueRanges: list[Literal['very_small', 'small_lower', 'small_upper', 'lower_mid_sized', 'mid_sized_lower', 'mid_sized_upper', 'large_lower', 'large_upper', 'enterprise_lower', 'enterprise_upper', 'global_giants_lower', 'global_giants_upper', 'super_enterprises']] | None = Field(None)
    companyTechnologies: LeadsforgeAnyAllFilter | None = Field(None)
    companyTypes: LeadsforgeIncludeExcludeFilter | None = Field(None)
    companyYearsInBusinessRange: LeadsforgeMinMaxFilter | None = Field(None)
    leadDepartments: LeadsforgeIncludeExcludeFilter | None = Field(None)
    leadIDs: LeadsforgeIncludeExcludeFilter | None = Field(None)
    leadJobTitles: LeadsforgeJobTitleFilter | None = Field(None)
    leadLanguages: LeadsforgeLanguageFilter | None = Field(None)
    leadLocations: LeadsforgeIncludeExcludeFilter | None = Field(None)
    leadSeniorities: LeadsforgeIncludeExcludeFilter | None = Field(None)
    leadTenure: LeadsforgeMinMaxFilter | None = Field(None)
    maxContactsPerCompany: int | None = Field(None, ge=0, le=100, strict=True)


class LeadsforgeSyncEnrichmentRequest(_Input):
    company: str | None = Field(None, examples=['Salesforge'])
    companyDomain: str | None = Field(None, examples=['salesforge.ai'])
    externalID: str | None = Field(None, max_length=128, examples=['crm-contact-42'])
    firstName: str | None = Field(None, examples=['John'])
    lastName: str | None = Field(None, examples=['Doe'])
    linkedinURL: str | None = Field(None, examples=['https://www.linkedin.com/in/john-doe'])
    personID: str | None = Field(None, examples=['p_abc123'])


class LeadsforgePersonInput(_Input):
    company: str | None = Field(None, examples=['Salesforge'])
    companyDomain: str | None = Field(None, examples=['salesforge.ai'])
    externalID: str | None = Field(None, max_length=128, examples=['crm-contact-42'])
    firstName: str | None = Field(None, examples=['John'])
    lastName: str | None = Field(None, examples=['Doe'])
    linkedinURL: str | None = Field(None, examples=['https://www.linkedin.com/in/john-doe'])


class LeadsforgeStartCompanyFollowersSearchRequest(_Input):
    clientRequestID: str | None = Field(None, max_length=128, examples=['req_12345'])
    countries: list[str] | None = Field(None, examples=[['United States', 'Germany']])
    departments: list[str] | None = Field(None, examples=[['Engineering', 'Marketing']])
    jobTitles: list[str] | None = Field(None, examples=[['Software Engineer', 'Product Manager']])
    levels: list[str] | None = Field(None, examples=[['Senior', 'Director']])
    limit: int = Field(..., ge=1, le=50000, strict=True, examples=[500])
    linkedinUrl: str = Field(..., examples=['https://www.linkedin.com/company/salesforgeai'])
    metros: list[str] | None = Field(None, examples=[['San Francisco Bay Area', 'London Area', ' United Kingdom']])
    states: list[str] | None = Field(None, examples=[['California', 'Bavaria']])
    webhookURL: str | None = Field(None, examples=['https://example.com/webhooks/followers'])


class LeadsforgeCompanyLookalikesLocation(_Input):
    id: str = Field(...)
    type: Literal['region', 'country'] = Field(...)


class LeadsforgeLookalikesSearchRequest(_Input):
    categories: list[str] | None = Field(None)
    domains: list[str] = Field(..., min_length=1, max_length=10)
    employeeRanges: list[str] | None = Field(None)
    fundingStages: list[str] | None = Field(None)
    locations: list[LeadsforgeCompanyLookalikesLocation] | None = Field(None)
    page: int | None = Field(None, ge=1, strict=True)
    pageSize: int | None = Field(None, ge=1, le=100, strict=True)


class LeadsforgeStartMapsDiscoverySearchRequest(_Input):
    categories: list[str] = Field(..., min_length=1, max_length=100, description='Categories are OR-combined. Recommended values: GET /maps-discovery/filters/categories; free text is accepted too.', examples=[['Dentist', 'Dental Clinic']])
    clientRequestID: str | None = Field(None, max_length=128, examples=['req_12345'])
    language: str | None = Field(None, max_length=10, examples=['en'])
    lat: float | None = Field(None, ge=-90, le=90, strict=True, examples=[40.758])
    limit: int = Field(..., ge=1, le=5000, strict=True, examples=[200])
    lng: float | None = Field(None, ge=-180, le=180, strict=True, examples=[-73.9855])
    radiusKm: float = Field(..., le=500, strict=True, examples=[5])
    webhookURL: str | None = Field(None, examples=['https://example.com/webhooks/maps-search'])


class LeadsforgeStartSalesNavSearchRequest(_Input):
    enrichEmail: bool | None = Field(None, strict=True, examples=[True])
    enrichFirstN: int | None = Field(None, ge=1, strict=True, examples=[50])
    enrichPhone: bool | None = Field(None, strict=True, examples=[False])
    limit: int | None = Field(None, ge=1, le=2500, strict=True, examples=[500])
    salesnavUrl: str = Field(..., examples=['https://www.linkedin.com/sales/search/people?keywords=cto'])
    webhookURL: str | None = Field(None, examples=['https://example.com/webhooks/salesnav'])


class LeadsforgeSalesNavTotalCountRequest(_Input):
    salesnavUrl: str = Field(..., examples=['https://www.linkedin.com/sales/search/people?keywords=cto'])


class LeadsforgePersonSearchRequest(_Input):
    companyBusinessModels: LeadsforgeIncludeExcludeFilter | None = Field(None)
    companyDomains: LeadsforgeIncludeExcludeFilter | None = Field(None)
    companyEmployeeNumberRange: LeadsforgeMinMaxFilter | None = Field(None)
    companyFoundedYearRange: LeadsforgeMinMaxFilter | None = Field(None)
    companyFundingRounds: LeadsforgeIncludeExcludeFilter | None = Field(None)
    companyIDs: LeadsforgeIncludeExcludeFilter | None = Field(None)
    companyIndustries: LeadsforgeIncludeExcludeFilter | None = Field(None)
    companyKeywords: LeadsforgeIncludeExcludeAllFilter | None = Field(None)
    companyLocations: LeadsforgeIncludeExcludeFilter | None = Field(None)
    companyNames: LeadsforgeIncludeExcludeFilter | None = Field(None)
    companyNiches: LeadsforgeIncludeExcludeFilter | None = Field(None)
    companyRequired: bool | None = Field(None, strict=True)
    companyRevenueRanges: list[Literal['very_small', 'small_lower', 'small_upper', 'lower_mid_sized', 'mid_sized_lower', 'mid_sized_upper', 'large_lower', 'large_upper', 'enterprise_lower', 'enterprise_upper', 'global_giants_lower', 'global_giants_upper', 'super_enterprises']] | None = Field(None)
    companyTechnologies: LeadsforgeAnyAllFilter | None = Field(None)
    companyTypes: LeadsforgeIncludeExcludeFilter | None = Field(None)
    companyYearsInBusinessRange: LeadsforgeMinMaxFilter | None = Field(None)
    leadDepartments: LeadsforgeIncludeExcludeFilter | None = Field(None)
    leadIDs: LeadsforgeIncludeExcludeFilter | None = Field(None)
    leadJobTitles: LeadsforgeJobTitleFilter | None = Field(None)
    leadLanguages: LeadsforgeLanguageFilter | None = Field(None)
    leadLocations: LeadsforgeIncludeExcludeFilter | None = Field(None)
    leadSeniorities: LeadsforgeIncludeExcludeFilter | None = Field(None)
    leadTenure: LeadsforgeMinMaxFilter | None = Field(None)
    limit: int | None = Field(None, ge=1, le=2000, strict=True)
    maxContactsPerCompany: int | None = Field(None, ge=0, le=100, strict=True)


class LeadsforgeStartEnrichmentRequest(_Input):
    clientRequestID: str | None = Field(None, max_length=128, examples=['my-request-123'])
    people: list[LeadsforgePersonInput] | None = Field(None, min_length=1, max_length=500)
    personIDs: list[str] | None = Field(None, min_length=1, max_length=500, examples=[['p_abc123', 'p_def456']])
    saveToList: bool | None = Field(None, strict=True, examples=[False])
    webhookURL: str | None = Field(None, examples=['https://example.com/webhook'])


class LeadsforgeLookalikesPreviewRequest(_Input):
    categories: list[str] | None = Field(None)
    domains: list[str] = Field(..., min_length=1, max_length=10)
    employeeRanges: list[str] | None = Field(None)
    fundingStages: list[str] | None = Field(None)
    locations: list[LeadsforgeCompanyLookalikesLocation] | None = Field(None)


class LeadsforgeGetBalanceConfig(_Input):
    """Get credit balance."""
    operation: Literal['get_balance'] = Field('get_balance', json_schema_extra={"ui:hidden": True})


class LeadsforgeSearchPeopleConfig(_Input):
    """Search."""
    operation: Literal['search_people'] = Field('search_people', json_schema_extra={"ui:hidden": True})
    cursor: str | None = Field(None, description='Cursor')
    request: LeadsforgePersonSearchRequest = Field(...)


class LeadsforgeCountPeopleConfig(_Input):
    """Count search results."""
    operation: Literal['count_people'] = Field('count_people', json_schema_extra={"ui:hidden": True})
    request: LeadsforgePersonSearchFilters = Field(...)


class LeadsforgeFindEmailConfig(_Input):
    """Find email (synchronous)."""
    operation: Literal['find_email'] = Field('find_email', json_schema_extra={"ui:hidden": True})
    request: LeadsforgeSyncEnrichmentRequest = Field(...)


class LeadsforgeFindPhoneConfig(_Input):
    """Find phone number (synchronous)."""
    operation: Literal['find_phone'] = Field('find_phone', json_schema_extra={"ui:hidden": True})
    request: LeadsforgeSyncEnrichmentRequest = Field(...)


class LeadsforgeFindEmailsConfig(_Input):
    """Find emails."""
    operation: Literal['find_emails'] = Field('find_emails', json_schema_extra={"ui:hidden": True})
    idempotency_key: str | None = Field(None, max_length=256, description="Reuse the same key only when retrying the same job; use a new key for a new search.")
    request: LeadsforgeStartEnrichmentRequest = Field(...)


class LeadsforgeFindPhonesConfig(_Input):
    """Find phone numbers."""
    operation: Literal['find_phones'] = Field('find_phones', json_schema_extra={"ui:hidden": True})
    idempotency_key: str | None = Field(None, max_length=256, description="Reuse the same key only when retrying the same job; use a new key for a new search.")
    request: LeadsforgeStartEnrichmentRequest = Field(...)


class LeadsforgeFindLinkedinProfilesConfig(_Input):
    """Find linkedin profiles."""
    operation: Literal['find_linkedin_profiles'] = Field('find_linkedin_profiles', json_schema_extra={"ui:hidden": True})
    idempotency_key: str | None = Field(None, max_length=256, description="Reuse the same key only when retrying the same job; use a new key for a new search.")
    request: LeadsforgeStartEnrichmentRequest = Field(...)


class LeadsforgeListEnrichmentJobsConfig(_Input):
    """List enrichment jobs."""
    operation: Literal['list_enrichment_jobs'] = Field('list_enrichment_jobs', json_schema_extra={"ui:hidden": True})
    offset: int | None = Field(None, ge=0, strict=True, description='Offset')
    limit: int = Field(50, ge=1, le=100, strict=True, description='Page size (max 100)')
    status: Literal['in_progress', 'completed', 'failed'] | None = Field(None, description='Filter by status')
    channel: Literal['email', 'phone', 'linkedin'] | None = Field(None, description='Filter by channel')
    clientRequestID: str | None = Field(None, description='Filter by your clientRequestID')
    from_time: str | None = Field(None, description='Created-at lower bound (RFC3339)', alias='from')
    to_time: str | None = Field(None, description='Created-at upper bound (RFC3339)', alias='to')


class LeadsforgeGetEnrichmentJobConfig(_Input):
    """Get enrichment job."""
    operation: Literal['get_enrichment_job'] = Field('get_enrichment_job', json_schema_extra={"ui:hidden": True})
    jobID: str = Field(..., description='Job ID', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')


class LeadsforgeListEnrichmentResultsConfig(_Input):
    """List enrichment results."""
    operation: Literal['list_enrichment_results'] = Field('list_enrichment_results', json_schema_extra={"ui:hidden": True})
    jobID: str = Field(..., description='Job ID', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')
    offset: int | None = Field(None, ge=0, strict=True, description='Offset')
    limit: int = Field(50, ge=1, le=100, strict=True, description='Page size')


class LeadsforgeSearchCompanyFollowersConfig(_Input):
    """Search company followers."""
    operation: Literal['search_company_followers'] = Field('search_company_followers', json_schema_extra={"ui:hidden": True})
    idempotency_key: str | None = Field(None, max_length=256, description="Reuse the same key only when retrying the same job; use a new key for a new search.")
    request: LeadsforgeStartCompanyFollowersSearchRequest = Field(...)


class LeadsforgeListCompanyFollowerJobsConfig(_Input):
    """List company followers jobs."""
    operation: Literal['list_company_follower_jobs'] = Field('list_company_follower_jobs', json_schema_extra={"ui:hidden": True})
    offset: int | None = Field(None, ge=0, strict=True, description='Offset')
    limit: int = Field(50, ge=1, le=100, strict=True, description='Page size (max 100)')
    status: Literal['in_progress', 'completed', 'failed', 'no_results'] | None = Field(None, description='Filter by status')
    clientRequestID: str | None = Field(None, description='Filter by your clientRequestID')
    from_time: str | None = Field(None, description='Created-at lower bound (RFC3339)', alias='from')
    to_time: str | None = Field(None, description='Created-at upper bound (RFC3339)', alias='to')


class LeadsforgeGetCompanyFollowerJobConfig(_Input):
    """Get company followers job status."""
    operation: Literal['get_company_follower_job'] = Field('get_company_follower_job', json_schema_extra={"ui:hidden": True})
    jobID: str = Field(..., description='Job ID', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')


class LeadsforgeListCompanyFollowersConfig(_Input):
    """List company followers results."""
    operation: Literal['list_company_followers'] = Field('list_company_followers', json_schema_extra={"ui:hidden": True})
    jobID: str = Field(..., description='Job ID', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')
    offset: int | None = Field(None, ge=0, strict=True, description='Offset')
    limit: int = Field(50, ge=1, le=100, strict=True, description='Page size')


class LeadsforgePreviewLookalikesConfig(_Input):
    """Preview lookalike companies (free)."""
    operation: Literal['preview_lookalikes'] = Field('preview_lookalikes', json_schema_extra={"ui:hidden": True})
    request: LeadsforgeLookalikesPreviewRequest = Field(...)


class LeadsforgeSearchLookalikesConfig(_Input):
    """Search lookalike companies."""
    operation: Literal['search_lookalikes'] = Field('search_lookalikes', json_schema_extra={"ui:hidden": True})
    request: LeadsforgeLookalikesSearchRequest = Field(...)
    idempotency_key: str | None = Field(None, max_length=256, description="Reuse the same key only when retrying the same job; use a new key for a new search.")


class LeadsforgeSearchMapsConfig(_Input):
    """Search local businesses on Google Maps."""
    operation: Literal['search_maps'] = Field('search_maps', json_schema_extra={"ui:hidden": True})
    idempotency_key: str | None = Field(None, max_length=256, description="Reuse the same key only when retrying the same job; use a new key for a new search.")
    request: LeadsforgeStartMapsDiscoverySearchRequest = Field(...)


class LeadsforgeListMapsJobsConfig(_Input):
    """List maps search jobs."""
    operation: Literal['list_maps_jobs'] = Field('list_maps_jobs', json_schema_extra={"ui:hidden": True})
    offset: int | None = Field(None, ge=0, strict=True, description='Offset')
    limit: int = Field(50, ge=1, le=100, strict=True, description='Page size (max 100)')
    status: Literal['in_progress', 'completed', 'failed', 'no_results'] | None = Field(None, description='Filter by status')
    clientRequestID: str | None = Field(None, description='Filter by your clientRequestID')
    from_time: str | None = Field(None, description='Created-at lower bound (RFC3339)', alias='from')
    to_time: str | None = Field(None, description='Created-at upper bound (RFC3339)', alias='to')


class LeadsforgeGetMapsJobConfig(_Input):
    """Get maps search job status."""
    operation: Literal['get_maps_job'] = Field('get_maps_job', json_schema_extra={"ui:hidden": True})
    jobID: str = Field(..., description='Job ID', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')


class LeadsforgeListMapsResultsConfig(_Input):
    """List maps search results."""
    operation: Literal['list_maps_results'] = Field('list_maps_results', json_schema_extra={"ui:hidden": True})
    jobID: str = Field(..., description='Job ID', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')
    offset: int | None = Field(None, ge=0, strict=True, description='Offset (max 5000)')
    limit: int = Field(50, ge=1, le=200, strict=True, description='Page size (max 200, default 50)')


class LeadsforgeStartSalesnavJobConfig(_Input):
    """Scrape a LinkedIn Sales Navigator search."""
    operation: Literal['start_salesnav_job'] = Field('start_salesnav_job', json_schema_extra={"ui:hidden": True})
    idempotency_key: str | None = Field(None, max_length=256, description="Reuse the same key only when retrying the same job; use a new key for a new search.")
    request: LeadsforgeStartSalesNavSearchRequest = Field(...)


class LeadsforgeGetSalesnavJobConfig(_Input):
    """Get Sales Navigator scrape job status."""
    operation: Literal['get_salesnav_job'] = Field('get_salesnav_job', json_schema_extra={"ui:hidden": True})
    jobID: str = Field(..., description='Job ID', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')


class LeadsforgeCountSalesnavResultsConfig(_Input):
    """Count Sales Navigator search results (free)."""
    operation: Literal['count_salesnav_results'] = Field('count_salesnav_results', json_schema_extra={"ui:hidden": True})
    request: LeadsforgeSalesNavTotalCountRequest = Field(...)


LeadsforgeConfig = Annotated[Union[
    LeadsforgeGetBalanceConfig,
    LeadsforgeSearchPeopleConfig,
    LeadsforgeCountPeopleConfig,
    LeadsforgeFindEmailConfig,
    LeadsforgeFindPhoneConfig,
    LeadsforgeFindEmailsConfig,
    LeadsforgeFindPhonesConfig,
    LeadsforgeFindLinkedinProfilesConfig,
    LeadsforgeListEnrichmentJobsConfig,
    LeadsforgeGetEnrichmentJobConfig,
    LeadsforgeListEnrichmentResultsConfig,
    LeadsforgeSearchCompanyFollowersConfig,
    LeadsforgeListCompanyFollowerJobsConfig,
    LeadsforgeGetCompanyFollowerJobConfig,
    LeadsforgeListCompanyFollowersConfig,
    LeadsforgePreviewLookalikesConfig,
    LeadsforgeSearchLookalikesConfig,
    LeadsforgeSearchMapsConfig,
    LeadsforgeListMapsJobsConfig,
    LeadsforgeGetMapsJobConfig,
    LeadsforgeListMapsResultsConfig,
    LeadsforgeStartSalesnavJobConfig,
    LeadsforgeGetSalesnavJobConfig,
    LeadsforgeCountSalesnavResultsConfig
], Field(discriminator="operation")]

OPERATIONS = {'get_balance': {'method': 'GET',
                 'path': '/balance',
                 'query': [],
                 'body': False,
                 'idempotency': False},
 'search_people': {'method': 'POST',
                   'path': '/search',
                   'query': ['cursor'],
                   'body': True,
                   'idempotency': False},
 'count_people': {'method': 'POST',
                  'path': '/search/count',
                  'query': [],
                  'body': True,
                  'idempotency': False},
 'find_email': {'method': 'POST',
                'path': '/enrichment/email',
                'query': [],
                'body': True,
                'idempotency': False},
 'find_phone': {'method': 'POST',
                'path': '/enrichment/phone',
                'query': [],
                'body': True,
                'idempotency': False},
 'find_emails': {'method': 'POST',
                 'path': '/enrichment/emails',
                 'query': [],
                 'body': True,
                 'idempotency': True},
 'find_phones': {'method': 'POST',
                 'path': '/enrichment/phones',
                 'query': [],
                 'body': True,
                 'idempotency': True},
 'find_linkedin_profiles': {'method': 'POST',
                            'path': '/enrichment/linkedin',
                            'query': [],
                            'body': True,
                            'idempotency': True},
 'list_enrichment_jobs': {'method': 'GET',
                          'path': '/enrichment/jobs',
                          'query': ['offset',
                                    'limit',
                                    'status',
                                    'channel',
                                    'clientRequestID',
                                    'from',
                                    'to'],
                          'body': False,
                          'idempotency': False},
 'get_enrichment_job': {'method': 'GET',
                        'path': '/enrichment/jobs/{jobID}',
                        'query': [],
                        'body': False,
                        'idempotency': False},
 'list_enrichment_results': {'method': 'GET',
                             'path': '/enrichment/jobs/{jobID}/results',
                             'query': ['offset', 'limit'],
                             'body': False,
                             'idempotency': False},
 'search_company_followers': {'method': 'POST',
                              'path': '/company-followers/search',
                              'query': [],
                              'body': True,
                              'idempotency': True},
 'list_company_follower_jobs': {'method': 'GET',
                                'path': '/company-followers/jobs',
                                'query': ['offset',
                                          'limit',
                                          'status',
                                          'clientRequestID',
                                          'from',
                                          'to'],
                                'body': False,
                                'idempotency': False},
 'get_company_follower_job': {'method': 'GET',
                              'path': '/company-followers/jobs/{jobID}',
                              'query': [],
                              'body': False,
                              'idempotency': False},
 'list_company_followers': {'method': 'GET',
                            'path': '/company-followers/jobs/{jobID}/results',
                            'query': ['offset', 'limit'],
                            'body': False,
                            'idempotency': False},
 'preview_lookalikes': {'method': 'POST',
                        'path': '/lookalikes/preview',
                        'query': [],
                        'body': True,
                        'idempotency': False},
 'search_lookalikes': {'method': 'POST',
                       'path': '/lookalikes/search',
                       'query': [],
                       'body': True,
                       'idempotency': True},
 'search_maps': {'method': 'POST',
                 'path': '/maps-discovery/search',
                 'query': [],
                 'body': True,
                 'idempotency': True},
 'list_maps_jobs': {'method': 'GET',
                    'path': '/maps-discovery/jobs',
                    'query': ['offset', 'limit', 'status', 'clientRequestID', 'from', 'to'],
                    'body': False,
                    'idempotency': False},
 'get_maps_job': {'method': 'GET',
                  'path': '/maps-discovery/jobs/{jobID}',
                  'query': [],
                  'body': False,
                  'idempotency': False},
 'list_maps_results': {'method': 'GET',
                       'path': '/maps-discovery/jobs/{jobID}/results',
                       'query': ['offset', 'limit'],
                       'body': False,
                       'idempotency': False},
 'start_salesnav_job': {'method': 'POST',
                        'path': '/salesnav/jobs',
                        'query': [],
                        'body': True,
                        'idempotency': True},
 'get_salesnav_job': {'method': 'GET',
                      'path': '/salesnav/jobs/{jobID}',
                      'query': [],
                      'body': False,
                      'idempotency': False},
 'count_salesnav_results': {'method': 'POST',
                            'path': '/salesnav/total-count',
                            'query': [],
                            'body': True,
                            'idempotency': False}}
