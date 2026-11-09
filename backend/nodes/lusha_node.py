"""Lusha API v3: prospecting, enrichment, reusable tables and account usage.

Contract: https://docs.lusha.com/openapi.json (SHA-256 pinned in test fixture).
Each operation makes exactly one request. Provider billing, async enrichment jobs
and pagination remain in the returned data; callers explicitly request later pages.
"""
from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Union, get_args, get_origin
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}
BASE_URL = "https://api.lusha.com"


class LushaAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Lusha API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://dashboard.lusha.com/enrich/api",
            "x-credential-instructions": "Generate an API key in Lusha's API dashboard and paste it here. Your plan must permit the requested endpoints. Enrichment, prospecting and table exports may consume credits."})
    credential_type: Literal["lusha_api_key"] = Field("lusha_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def decode_editor(cls, values):
        # The editor sends JSON text; expressions and API callers can send native JSON.
        if not isinstance(values, dict):
            return values
        values = dict(values)
        if "operation" in cls.model_fields:
            values.pop("credentialIds", None)
        for name, field in cls.model_fields.items():
            annotation = field.annotation
            types = (annotation, *get_args(annotation))
            structured = any(get_origin(t) in (list, dict) or isinstance(t, type) and issubclass(t, BaseModel) for t in types)
            if structured and isinstance(values.get(name), str):
                try:
                    values[name] = json.loads(values[name])
                except ValueError:
                    raise ValueError("Enter valid JSON for " + name) from None
        return values


class LushaContactSearchItem(_Input):
    clientReferenceId: str | None = Field(None)
    id: str | None = Field(None)
    linkedinUrl: str | None = Field(None)
    email: str | None = Field(None, min_length=3, max_length=320)
    firstName: str | None = Field(None)
    lastName: str | None = Field(None)
    companyName: str | None = Field(None)
    companyDomain: str | None = Field(None)


class LushaSearchOptions(_Input):
    includePartialProfiles: bool | None = Field(None, description='Include partial profiles in results')


class LushaContactSignalsDto(_Input):
    types: list[Literal['allSignals', 'promotion', 'companyChange']] = Field(..., json_schema_extra=JSON_EDITOR)
    startDate: str | None = Field(None)
    maxResultsPerSignal: int | None = Field(None, ge=1, le=100)


class LushaCompanySearchItem(_Input):
    clientReferenceId: str | None = Field(None)
    id: str | None = Field(None)
    name: str | None = Field(None)
    domain: str | None = Field(None)


class LushaCompanySignalsDto(_Input):
    types: list[Literal['allSignals', 'linkedinActivityIntent', 'websiteTrafficDecrease', 'websiteTrafficIncrease', 'itSpendIncrease', 'itSpendDecrease', 'linkedinFollowersIncrease', 'linkedinFollowersDecrease', 'surgeInHiring', 'headcountIncrease1m', 'headcountIncrease3m', 'headcountIncrease6m', 'headcountIncrease12m', 'headcountDecrease1m', 'headcountDecrease3m', 'headcountDecrease6m', 'headcountDecrease12m', 'surgeInHiringByDepartment', 'surgeInHiringByLocation', 'riskNews', 'commercialActivityNews', 'corporateStrategyNews', 'financialEventsNews', 'peopleNews', 'marketIntelligenceNews', 'productActivityNews']] = Field(..., json_schema_extra=JSON_EDITOR)
    startDate: str | None = Field(None)
    maxResultsPerSignal: int | None = Field(None, ge=1, le=100)


class LushaPaginationRequest(_Input):
    page: int = Field(0, ge=0, le=1000)
    size: int = Field(25, ge=10, le=100)


class LushaLocation(_Input):
    city: str | None = Field(None)
    state: str | None = Field(None)
    country: str | None = Field(None)
    continent: str | None = Field(None)
    countryGrouping: str | None = Field(None)
    region: str | None = Field(None)
    countryIso2: str | None = Field(None)


class LushaContactFilterCriteriaSignals(_Input):
    types: list[Literal['allSignals', 'promotion', 'companyChange']] | None = Field(None, json_schema_extra=JSON_EDITOR)
    startDate: str | None = Field(None)


class LushaContactFilterCriteriaEducation(_Input):
    degrees: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    fieldsOfStudy: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    schools: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    startYearGte: int | None = Field(None)
    graduationYearLte: int | None = Field(None)


class LushaContactFilterCriteriaScore(_Input):
    minScore: int | None = Field(None, ge=0, le=100)
    maxScore: int | None = Field(None, ge=0, le=100)


class LushaContactFilterCriteriaGeographicDetailsItem(_Input):
    country: str | None = Field(None)
    zipcode: str | None = Field(None)
    distance: int | None = Field(None, description='Radius in miles.')


class LushaContactFilterCriteria(_Input):
    names: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    jobTitles: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    jobTitlesExactMatch: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    normalizedJobTitles: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    searchText: str | None = Field(None, max_length=200)
    countries: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    locations: list[LushaLocation] | None = Field(None, json_schema_extra=JSON_EDITOR)
    seniorityIds: list[int] | None = Field(None, json_schema_extra=JSON_EDITOR)
    departments: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    linkedinUrls: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    existingDataPoints: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    signals: LushaContactFilterCriteriaSignals | None = Field(None, json_schema_extra=JSON_EDITOR)
    emails: list[str] | None = Field(None, description='Personal data - no catalog.', json_schema_extra=JSON_EDITOR)
    previousEmails: list[str] | None = Field(None, description='Personal data - no catalog.', json_schema_extra=JSON_EDITOR)
    previousJobTitle: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    skills: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    certifications: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    awards: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    ids: list[str] | None = Field(None, description="Encrypted contact id from a prior search's `results[].id`.", json_schema_extra=JSON_EDITOR)
    existingDataPointsCondition: Literal['or', 'and'] | None = Field(None, description='Pairs with `existingDataPoints`.')
    jobChangedAfterDate: str | None = Field(None, description='Refinement-only - must be paired with a base filter (e.g. `jobTitles`).')
    jobChangedLastViewDate: str | None = Field(None, description='Refinement-only - must be paired with a base filter.')
    education: LushaContactFilterCriteriaEducation | None = Field(None, description='Refinement-only - must be paired with a base filter.', json_schema_extra=JSON_EDITOR)
    score: LushaContactFilterCriteriaScore | None = Field(None, description='Refinement-only - must be paired with a base filter. Raw 0–100 contact score. Distinct from the `confidence` band ("A+"/"A") returned on enriched contacts, which is derived from this score (e.g. `A+` when score > 75).\n', json_schema_extra=JSON_EDITOR)
    geographicDetails: list[LushaContactFilterCriteriaGeographicDetailsItem] | None = Field(None, json_schema_extra=JSON_EDITOR)


class LushaProspectingContactFiltersContacts(_Input):
    include: LushaContactFilterCriteria | None = Field(None, json_schema_extra=JSON_EDITOR)
    exclude: LushaContactFilterCriteria | None = Field(None, json_schema_extra=JSON_EDITOR)


class LushaRange(_Input):
    min: int | None = Field(None, ge=0)
    max: int | None = Field(None)


class LushaCompanyFilterCriteriaFundingRangesItem(_Input):
    coverage: Literal['last_funding', 'any_round', 'total_funds', 'last_round'] | None = Field(None)
    min: int | None = Field(None)
    max: int | None = Field(None)


class LushaCompanyFilterCriteriaFundingDate(_Input):
    coverage: Literal['last_funding', 'any_round', 'total_funds', 'last_round'] | None = Field(None)
    date: str | None = Field(None)


class LushaCompanyFilterCriteriaFundingRoundsItem(_Input):
    coverage: Literal['last_funding', 'any_round', 'total_funds', 'last_round'] | None = Field(None)
    round: Literal['pre_seed', 'seed', 'series_a', 'series_b', 'series_c', 'series_d', 'series_e', 'series_f', 'series_g', 'series_h', 'other'] | None = Field(None)


class LushaCompanyFilterCriteriaFundingNamesItem(_Input):
    coverage: Literal['last_funding', 'any_round', 'total_funds', 'last_round'] | None = Field(None)
    name: Literal['angel', 'venture', 'private_equity', 'crowdfunding', 'grant', 'debt_financing', 'other'] | None = Field(None)


class LushaCompanyFilterCriteriaFunding(_Input):
    isIpo: bool | None = Field(None)
    ranges: list[LushaCompanyFilterCriteriaFundingRangesItem] | None = Field(None, json_schema_extra=JSON_EDITOR)
    date: LushaCompanyFilterCriteriaFundingDate | None = Field(None, json_schema_extra=JSON_EDITOR)
    rounds: list[LushaCompanyFilterCriteriaFundingRoundsItem] | None = Field(None, json_schema_extra=JSON_EDITOR)
    names: list[LushaCompanyFilterCriteriaFundingNamesItem] | None = Field(None, json_schema_extra=JSON_EDITOR)
    investors: list[str] | None = Field(None, description='Free text. Accepted but not currently applied downstream.', json_schema_extra=JSON_EDITOR)
    types: list[str] | None = Field(None, description='Legacy free text. Accepted but not currently applied downstream.', json_schema_extra=JSON_EDITOR)


class LushaCompanyFilterCriteriaFoundedYearItem(_Input):
    min: int | None = Field(None)
    max: int | None = Field(None)


class LushaCompanyFilterCriteriaGeographicDetailsItem(_Input):
    country: str | None = Field(None)
    zipcode: str | None = Field(None)
    distance: int | None = Field(None, description='Radius in miles.')


class LushaCompanyFilterCriteriaLocationsZipcodesItem(_Input):
    countryIso2: str | None = Field(None)
    zipcode: str | None = Field(None)


class LushaCompanyFilterCriteriaHeadquarterZipcodesItem(_Input):
    countryIso2: str | None = Field(None)
    zipcode: str | None = Field(None)


class LushaCompanyFilterCriteria(_Input):
    names: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    domains: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    ids: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    locations: list[LushaLocation] | None = Field(None, json_schema_extra=JSON_EDITOR)
    sizes: list[LushaRange] | None = Field(None, json_schema_extra=JSON_EDITOR)
    revenues: list[LushaRange] | None = Field(None, json_schema_extra=JSON_EDITOR)
    technologies: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    technologiesCondition: Literal['or', 'and'] | None = Field(None)
    industriesLabels: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    mainIndustriesIds: list[int] | None = Field(None, json_schema_extra=JSON_EDITOR)
    subIndustriesIds: list[int] | None = Field(None, json_schema_extra=JSON_EDITOR)
    intentTopics: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    intentTopicsCondition: Literal['or', 'and'] | None = Field(None)
    intentMinScore: int | None = Field(None, ge=1, le=100)
    intentMaxScore: int | None = Field(None, ge=1, le=100)
    intentTopicsOperator: Literal['or', 'and', 'any', 'all'] | None = Field(None, description='Recommended over `intentTopicsCondition`. `any`/`all` are aliases for `or`/`and`. `intentTopicsCondition` is not deprecated and remains accepted.\n')
    topicCountThreshold: list[LushaRange] | None = Field(None, json_schema_extra=JSON_EDITOR)
    sicCodes: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    naicsCodes: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    funding: LushaCompanyFilterCriteriaFunding | None = Field(None, description='All funding sub-filters live under this single object. Every field is optional; combine any subset.\n', json_schema_extra=JSON_EDITOR)
    foundedYear: list[LushaCompanyFilterCriteriaFoundedYearItem] | None = Field(None, description='Filter by year the company was founded. Supports `min` (greater than or equal) and `max` (less than or equal) range operators.', json_schema_extra=JSON_EDITOR)
    businessModel: list[Literal['B2B', 'B2C', 'B2G']] | None = Field(None, description='Filter by business model. Accepted values: B2B, B2C, B2G.', json_schema_extra=JSON_EDITOR)
    companyType: list[Literal['Government', 'Private Company', 'Public Company', 'Educational', 'Non Profit', 'Self Employed']] | None = Field(None, description='Filter by company type. Accepted values: Government, Private Company, Public Company, Educational, Non Profit, Self Employed.', json_schema_extra=JSON_EDITOR)
    linkedinUrls: list[str] | None = Field(None, description='Filter by company LinkedIn URLs.', json_schema_extra=JSON_EDITOR)
    keywords: list[str] | None = Field(None, description='Filter by keywords associated with the company.', json_schema_extra=JSON_EDITOR)
    specialities: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    exactSpecialities: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    exactKeywords: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    keywordsSearchFields: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    previousCompanyDomains: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    previousCompanyNames: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    geographicDetails: list[LushaCompanyFilterCriteriaGeographicDetailsItem] | None = Field(None, json_schema_extra=JSON_EDITOR)
    locationsZipcodes: list[LushaCompanyFilterCriteriaLocationsZipcodesItem] | None = Field(None, json_schema_extra=JSON_EDITOR)
    headquarterZipcodes: list[LushaCompanyFilterCriteriaHeadquarterZipcodesItem] | None = Field(None, json_schema_extra=JSON_EDITOR)


class LushaProspectingContactFiltersCompanies(_Input):
    include: LushaCompanyFilterCriteria | None = Field(None, json_schema_extra=JSON_EDITOR)
    exclude: LushaCompanyFilterCriteria | None = Field(None, json_schema_extra=JSON_EDITOR)


class LushaProspectingContactFilters(_Input):
    contacts: LushaProspectingContactFiltersContacts | None = Field(None, json_schema_extra=JSON_EDITOR)
    companies: LushaProspectingContactFiltersCompanies | None = Field(None, json_schema_extra=JSON_EDITOR)


class LushaProspectingContactsConfigOptions(_Input):
    includePartialProfiles: bool = Field(True)
    excludeDnc: bool | None = Field(None)
    maxContactsPerCompany: int | None = Field(None, ge=1, le=20, description='Caps how many contacts are returned per company - not the page size. `pagination.size` still controls the page size. Accepts 1–20; omit for uncapped results.\n')


class LushaCompanyProspectingFiltersSignalsFilterByLocationItem(_Input):
    country: str | None = Field(None)
    state: str | None = Field(None)
    startDate: str | None = Field(None)


class LushaCompanyProspectingFiltersSignalsFilterByDepartmentItem(_Input):
    department: str = Field(...)
    startDate: str | None = Field(None)


class LushaCompanyProspectingFiltersSignals(_Input):
    types: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    startDate: str | None = Field(None)
    filterByLocation: list[LushaCompanyProspectingFiltersSignalsFilterByLocationItem] | None = Field(None, json_schema_extra=JSON_EDITOR)
    filterByDepartment: list[LushaCompanyProspectingFiltersSignalsFilterByDepartmentItem] | None = Field(None, json_schema_extra=JSON_EDITOR)
    filterByIntentCategory: list[str] | None = Field(None, description='Refines linkedinActivityIntent results by Bombora intent category. Applied only when linkedinActivityIntent is present in `types` (or selected via allSignals). Omit to match all categories. See GET /v3/companies/signals/filters/intentCategories for the full list of valid values.\n', json_schema_extra=JSON_EDITOR)


class LushaCompanyProspectingFiltersFoundedYearItem(_Input):
    min: int | None = Field(None)
    max: int | None = Field(None)


class LushaCompanyProspectingFiltersGeographicDetailsItem(_Input):
    country: str | None = Field(None)
    zipcode: str | None = Field(None)
    distance: int | None = Field(None, description='Radius in miles.')


class LushaCompanyProspectingFiltersLocationsZipcodesItem(_Input):
    countryIso2: str | None = Field(None)
    zipcode: str | None = Field(None)


class LushaCompanyProspectingFiltersHeadquarterZipcodesItem(_Input):
    countryIso2: str | None = Field(None)
    zipcode: str | None = Field(None)


class LushaCompanyProspectingFilters(_Input):
    names: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    domains: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    ids: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    searchText: str | None = Field(None, max_length=200)
    locations: list[LushaLocation] | None = Field(None, json_schema_extra=JSON_EDITOR)
    sizes: list[LushaRange] | None = Field(None, json_schema_extra=JSON_EDITOR)
    revenues: list[LushaRange] | None = Field(None, json_schema_extra=JSON_EDITOR)
    technologies: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    technologiesCondition: Literal['or', 'and'] | None = Field(None)
    mainIndustriesIds: list[int] | None = Field(None, json_schema_extra=JSON_EDITOR)
    subIndustriesIds: list[int] | None = Field(None, json_schema_extra=JSON_EDITOR)
    intentTopics: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    intentTopicsCondition: Literal['or', 'and'] | None = Field(None)
    intentMinScore: int | None = Field(None, ge=1, le=100)
    intentMaxScore: int | None = Field(None, ge=1, le=100)
    intentTopicsOperator: Literal['or', 'and', 'any', 'all'] | None = Field(None, description='Recommended over `intentTopicsCondition`. `any`/`all` are aliases for `or`/`and`. `intentTopicsCondition` is not deprecated and remains accepted.\n')
    topicCountThreshold: list[LushaRange] | None = Field(None, json_schema_extra=JSON_EDITOR)
    sicCodes: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    naicsCodes: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    signals: LushaCompanyProspectingFiltersSignals | None = Field(None, json_schema_extra=JSON_EDITOR)
    foundedYear: list[LushaCompanyProspectingFiltersFoundedYearItem] | None = Field(None, description='Filter by year the company was founded. Supports `min` (greater than or equal) and `max` (less than or equal) range operators.', json_schema_extra=JSON_EDITOR)
    businessModel: list[Literal['B2B', 'B2C', 'B2G']] | None = Field(None, description='Filter by business model. Accepted values: B2B, B2C, B2G.', json_schema_extra=JSON_EDITOR)
    companyType: list[Literal['Government', 'Private Company', 'Public Company', 'Educational', 'Non Profit', 'Self Employed']] | None = Field(None, description='Filter by company type. Accepted values: Government, Private Company, Public Company, Educational, Non Profit, Self Employed.', json_schema_extra=JSON_EDITOR)
    linkedinUrls: list[str] | None = Field(None, description='Filter by company LinkedIn URLs.', json_schema_extra=JSON_EDITOR)
    keywords: list[str] | None = Field(None, description='Filter by keywords associated with the company.', json_schema_extra=JSON_EDITOR)
    specialities: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    exactSpecialities: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    exactKeywords: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    keywordsSearchFields: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    previousCompanyDomains: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    previousCompanyNames: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    geographicDetails: list[LushaCompanyProspectingFiltersGeographicDetailsItem] | None = Field(None, json_schema_extra=JSON_EDITOR)
    locationsZipcodes: list[LushaCompanyProspectingFiltersLocationsZipcodesItem] | None = Field(None, json_schema_extra=JSON_EDITOR)
    headquarterZipcodes: list[LushaCompanyProspectingFiltersHeadquarterZipcodesItem] | None = Field(None, json_schema_extra=JSON_EDITOR)


class LushaProspectingCompaniesConfigFiltersCompanies(_Input):
    include: LushaCompanyProspectingFilters = Field(..., json_schema_extra=JSON_EDITOR)
    exclude: LushaCompanyProspectingFilters | None = Field(None, json_schema_extra=JSON_EDITOR)


class LushaContactsOnCompanySearchFilters(_Input):
    jobTitles: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    departments: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    seniorityIds: list[int] | None = Field(None, json_schema_extra=JSON_EDITOR)
    skills: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)
    locations: list[LushaLocation] | None = Field(None, json_schema_extra=JSON_EDITOR)
    existingDataPoints: list[str] | None = Field(None, json_schema_extra=JSON_EDITOR)


class LushaProspectingCompaniesConfigFiltersContacts(_Input):
    include: LushaContactsOnCompanySearchFilters | None = Field(None, description='Restricted contact-attribute filters usable within a company prospecting request.', json_schema_extra=JSON_EDITOR)
    exclude: LushaContactsOnCompanySearchFilters | None = Field(None, description='Restricted contact-attribute filters usable within a company prospecting request.', json_schema_extra=JSON_EDITOR)


class LushaProspectingCompaniesConfigFilters(_Input):
    companies: LushaProspectingCompaniesConfigFiltersCompanies = Field(..., json_schema_extra=JSON_EDITOR)
    contacts: LushaProspectingCompaniesConfigFiltersContacts | None = Field(None, json_schema_extra=JSON_EDITOR)


class LushaProspectingCompaniesConfigOptions(_Input):
    includePartialProfiles: bool = Field(False)


class LushaTableOwner(_Input):
    email: str = Field(..., min_length=3, max_length=320, description='Must resolve to an existing user on the account tied to your API key.')


class LushaSearchContactsConfig(_Input):
    """Search Contacts. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['search_contacts'] = Field('search_contacts', json_schema_extra={"ui:hidden": True})
    contacts: list[LushaContactSearchItem] = Field(..., min_length=1, max_length=100, json_schema_extra=JSON_EDITOR)
    options: LushaSearchOptions | None = Field(None, description='Additional options for search requests', json_schema_extra=JSON_EDITOR)
    signals: LushaContactSignalsDto | None = Field(None, json_schema_extra=JSON_EDITOR)


class LushaEnrichContactsConfig(_Input):
    """Enrich Contacts. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['enrich_contacts'] = Field('enrich_contacts', json_schema_extra={"ui:hidden": True})
    ids: list[str] = Field(..., min_length=1, max_length=100, json_schema_extra=JSON_EDITOR)
    reveal: list[Literal['emails', 'phones']] | None = Field(None, json_schema_extra=JSON_EDITOR)
    waterfallEnabled: bool = Field(True, description="Whether this call is allowed to fall through to your enabled\nthird-party providers when Lusha's own data has no match, for the fields\nrequested via `reveal`. Defaults to `true` whenever Data Waterfall is\nenabled on your account (Account > Waterfall) - pass `false` to opt this\nspecific call out. Has no effect if Data Waterfall or no providers are\nenabled on your account. Provider order isn't configurable - Lusha manages\nthat internally.\n`false` means Lusha data only. If Lusha does not have a requested field, the response sets `statusReason: WATERFALL_DISABLED`.\n")
    tableId: str | None = Field(None, description="Optional. If provided, these contacts are also added to this table (if not already present) and the revealed fields' columns are populated. See the Tables API.")


class LushaSearchAndEnrichContactsConfig(_Input):
    """Search and Enrich Contacts. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['search_and_enrich_contacts'] = Field('search_and_enrich_contacts', json_schema_extra={"ui:hidden": True})
    contacts: list[LushaContactSearchItem] = Field(..., min_length=1, max_length=100, json_schema_extra=JSON_EDITOR)
    reveal: list[Literal['emails', 'phones']] | None = Field(None, json_schema_extra=JSON_EDITOR)
    options: LushaSearchOptions | None = Field(None, description='Additional options for search requests', json_schema_extra=JSON_EDITOR)


class LushaSearchCompaniesConfig(_Input):
    """Search Companies. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['search_companies'] = Field('search_companies', json_schema_extra={"ui:hidden": True})
    companies: list[LushaCompanySearchItem] = Field(..., min_length=1, max_length=100, json_schema_extra=JSON_EDITOR)
    options: LushaSearchOptions | None = Field(None, description='Additional options for search requests', json_schema_extra=JSON_EDITOR)
    signals: LushaCompanySignalsDto | None = Field(None, json_schema_extra=JSON_EDITOR)


class LushaEnrichCompaniesConfig(_Input):
    """Enrich Companies. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['enrich_companies'] = Field('enrich_companies', json_schema_extra={"ui:hidden": True})
    ids: list[str] = Field(..., min_length=1, max_length=100, description='Company IDs from search results (strings)', json_schema_extra=JSON_EDITOR)
    reveal: list[Literal['employeesByDepartment', 'employeesByLocation', 'employeesBySeniority', 'competitors', 'intent', 'estimatedAnnualItSpend', 'monthlyWebsiteTraffic', 'openJobsTotal', 'openJobsByDepartment', 'openJobsByLocation', 'openJobsBySeniority', 'directParent', 'ultimateParent']] | None = Field(None, description="Additional data fields to reveal. Each field is charged separately per result.\n- `employeesByDepartment` - breakdown of employees by department\n- `employeesByLocation` - breakdown of employees by country/state\n- `employeesBySeniority` - breakdown of employees by seniority level\n- `competitors` - list of competitor company IDs\n- `intent` - buyer intent topics\n- `estimatedAnnualItSpend` - estimated annual IT spend.\n- `monthlyWebsiteTraffic` - monthly website traffic and month-over-month change.\n- `openJobsTotal` - reveals the total open job count. In the response, this appears as the `total` field inside the `openJobs` object.\n- `openJobsByDepartment` - reveals open job counts broken down by department. In the response, this appears as the `byDepartment` field inside the `openJobs` object.\n- `openJobsByLocation` - reveals open job counts broken down by location. In the response, this appears as the `byLocation` field inside the `openJobs` object.\n- `openJobsBySeniority` - reveals open job counts broken down by seniority level. In the response, this appears as the `bySeniority` field inside the `openJobs` object.\n- `directParent` - the company's immediate parent in its ownership tree.\n- `ultimateParent` - the company at the top of its ownership tree.\n", json_schema_extra=JSON_EDITOR)
    tableId: str | None = Field(None, description="Optional. If provided, these companies are also added to this table (if not already present) and the revealed fields' columns are populated. See the Tables API.")


class LushaSearchAndEnrichCompaniesConfig(_Input):
    """Search and Enrich Companies. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['search_and_enrich_companies'] = Field('search_and_enrich_companies', json_schema_extra={"ui:hidden": True})
    companies: list[LushaCompanySearchItem] = Field(..., min_length=1, max_length=100, json_schema_extra=JSON_EDITOR)
    reveal: list[Literal['employeesByDepartment', 'employeesByLocation', 'employeesBySeniority', 'competitors', 'intent', 'estimatedAnnualItSpend', 'monthlyWebsiteTraffic', 'openJobsTotal', 'openJobsByDepartment', 'openJobsByLocation', 'openJobsBySeniority', 'directParent', 'ultimateParent']] | None = Field(None, description='Additional data fields to reveal, using the same tokens as Enrich Companies.\nEach field is charged separately per result. Premium fields are returned only\nwhen named here - omitting `reveal` returns base firmographics alone.\nSee [Enrich Companies](#operation/enrichCompanies) for what each token unlocks.\n', json_schema_extra=JSON_EDITOR)
    options: LushaSearchOptions | None = Field(None, description='Additional options for search requests', json_schema_extra=JSON_EDITOR)


class LushaProspectingContactsConfig(_Input):
    """Prospecting Contacts. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['prospecting_contacts'] = Field('prospecting_contacts', json_schema_extra={"ui:hidden": True})
    pagination: LushaPaginationRequest = Field(..., json_schema_extra=JSON_EDITOR)
    filters: LushaProspectingContactFilters = Field(..., json_schema_extra=JSON_EDITOR)
    tableId: str | None = Field(None, description='Optional. If provided, results are also persisted to this table. See the Tables API.')
    options: LushaProspectingContactsConfigOptions | None = Field(None, json_schema_extra=JSON_EDITOR)


class LushaProspectingCompaniesConfig(_Input):
    """Prospecting Companies. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['prospecting_companies'] = Field('prospecting_companies', json_schema_extra={"ui:hidden": True})
    pagination: LushaPaginationRequest = Field(..., json_schema_extra=JSON_EDITOR)
    filters: LushaProspectingCompaniesConfigFilters = Field(..., description='`filters.contacts` cannot be combined with company `searchText`, `signals`, `intent`, or `technologies` on the same request - doing so returns `400` (contact filters are never silently ignored).\n', json_schema_extra=JSON_EDITOR)
    tableId: str | None = Field(None, description='Optional. If provided, results are also persisted to this table. See the Tables API.')
    options: LushaProspectingCompaniesConfigOptions | None = Field(None, json_schema_extra=JSON_EDITOR)


class LushaCreateContactsTableConfig(_Input):
    """Create Contacts Table. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['create_contacts_table'] = Field('create_contacts_table', json_schema_extra={"ui:hidden": True})
    name: str = Field(...)
    visibility: Literal['private', 'shared'] = Field('private')
    owner: LushaTableOwner = Field(..., description='Identifies the user acting on the table, and resolves to a user on your account. Required on every table-route call when authenticating with an API key (there is no signed-in user) - omitting it returns `400`. Optional for OAuth/token callers, since the caller is already identified by the token; still accepted if you want to act on behalf of another owner.\n', json_schema_extra=JSON_EDITOR)
    ids: list[str] | None = Field(None, description='Optional initial entity IDs to seed the table with.', json_schema_extra=JSON_EDITOR)


class LushaListContactsTablesConfig(_Input):
    """List Contacts Tables. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['list_contacts_tables'] = Field('list_contacts_tables', json_schema_extra={"ui:hidden": True})
    owner: LushaTableOwner = Field(..., description='Identifies the user acting on the table, and resolves to a user on your account. Required on every table-route call when authenticating with an API key (there is no signed-in user) - omitting it returns `400`. Optional for OAuth/token callers, since the caller is already identified by the token; still accepted if you want to act on behalf of another owner.\n', json_schema_extra=JSON_EDITOR)
    page: int = Field(0, ge=0, le=100)
    size: int = Field(100)
    name: str | None = Field(None, description='Optional filter - matches tables whose name contains this text.')
    status: Literal['active', 'archived'] | None = Field(None, description='`deleted` is not a filterable status.')


class LushaGetContactsTableConfig(_Input):
    """Get Contacts Table. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['get_contacts_table'] = Field('get_contacts_table', json_schema_extra={"ui:hidden": True})
    table_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    email: str = Field(..., min_length=3, max_length=320)


class LushaUpdateContactsTableConfig(_Input):
    """Update Contacts Table. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['update_contacts_table'] = Field('update_contacts_table', json_schema_extra={"ui:hidden": True})
    table_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    name: str | None = Field(None)
    visibility: Literal['private', 'shared'] | None = Field(None)
    archived: bool | None = Field(None, description='Set `true` to archive the table (hides it from default List Tables results), `false` to restore it.')
    owner: LushaTableOwner = Field(..., description='Identifies the user acting on the table, and resolves to a user on your account. Required on every table-route call when authenticating with an API key (there is no signed-in user) - omitting it returns `400`. Optional for OAuth/token callers, since the caller is already identified by the token; still accepted if you want to act on behalf of another owner.\n', json_schema_extra=JSON_EDITOR)


class LushaDeleteContactsTableConfig(_Input):
    """Delete Contacts Table. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['delete_contacts_table'] = Field('delete_contacts_table', json_schema_extra={"ui:hidden": True})
    table_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    email: str = Field(..., min_length=3, max_length=320)


class LushaGetContactsTableEntitiesConfig(_Input):
    """Get Contacts Table Entities. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['get_contacts_table_entities'] = Field('get_contacts_table_entities', json_schema_extra={"ui:hidden": True})
    table_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    email: str = Field(..., min_length=3, max_length=320)
    page: int = Field(0, le=100)
    size: int = Field(100)


class LushaAddContactsTableEntitiesConfig(_Input):
    """Add Entities to Contacts Table. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['add_contacts_table_entities'] = Field('add_contacts_table_entities', json_schema_extra={"ui:hidden": True})
    table_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    entityIds: list[str] = Field(..., max_length=500, description='Lusha IDs as strings - `personId` for contacts, `lushaCompanyId` for companies. Accepts either the encrypted token (`v{N}.…`, as returned by Search/Enrich/Get Entities) or the legacy numeric ID. An ID that is neither a valid token nor numeric returns `400`.\n', json_schema_extra=JSON_EDITOR)
    companyIds: list[str] | None = Field(None, description='Contacts tables only. One `lushaCompanyId` per contact (encrypted token or numeric), index-aligned with `entityIds`, to help pair company-level enrichment to the right company for each contact. Ignored on companies tables.\n', json_schema_extra=JSON_EDITOR)
    owner: LushaTableOwner = Field(..., description='Identifies the user acting on the table, and resolves to a user on your account. Required on every table-route call when authenticating with an API key (there is no signed-in user) - omitting it returns `400`. Optional for OAuth/token callers, since the caller is already identified by the token; still accepted if you want to act on behalf of another owner.\n', json_schema_extra=JSON_EDITOR)


class LushaRemoveContactsTableEntitiesConfig(_Input):
    """Remove Entities from Contacts Table. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['remove_contacts_table_entities'] = Field('remove_contacts_table_entities', json_schema_extra={"ui:hidden": True})
    table_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    entityIds: list[str] = Field(..., description='Accepts either the encrypted token (`v{N}.…`, as returned by Get Entities) or the legacy numeric ID. Unresolved IDs are echoed back in `invalidIds` in the exact form you sent them.\n', json_schema_extra=JSON_EDITOR)
    owner: LushaTableOwner = Field(..., description='Identifies the user acting on the table, and resolves to a user on your account. Required on every table-route call when authenticating with an API key (there is no signed-in user) - omitting it returns `400`. Optional for OAuth/token callers, since the caller is already identified by the token; still accepted if you want to act on behalf of another owner.\n', json_schema_extra=JSON_EDITOR)


class LushaCreateCompaniesTableConfig(_Input):
    """Create Companies Table. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['create_companies_table'] = Field('create_companies_table', json_schema_extra={"ui:hidden": True})
    name: str = Field(...)
    visibility: Literal['private', 'shared'] = Field('private')
    owner: LushaTableOwner = Field(..., description='Identifies the user acting on the table, and resolves to a user on your account. Required on every table-route call when authenticating with an API key (there is no signed-in user) - omitting it returns `400`. Optional for OAuth/token callers, since the caller is already identified by the token; still accepted if you want to act on behalf of another owner.\n', json_schema_extra=JSON_EDITOR)
    ids: list[str] | None = Field(None, description='Optional initial entity IDs to seed the table with.', json_schema_extra=JSON_EDITOR)


class LushaListCompaniesTablesConfig(_Input):
    """List Companies Tables. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['list_companies_tables'] = Field('list_companies_tables', json_schema_extra={"ui:hidden": True})
    owner: LushaTableOwner = Field(..., description='Identifies the user acting on the table, and resolves to a user on your account. Required on every table-route call when authenticating with an API key (there is no signed-in user) - omitting it returns `400`. Optional for OAuth/token callers, since the caller is already identified by the token; still accepted if you want to act on behalf of another owner.\n', json_schema_extra=JSON_EDITOR)
    page: int = Field(0, ge=0, le=100)
    size: int = Field(100)
    name: str | None = Field(None, description='Optional filter - matches tables whose name contains this text.')
    status: Literal['active', 'archived'] | None = Field(None, description='`deleted` is not a filterable status.')


class LushaGetCompaniesTableConfig(_Input):
    """Get Companies Table. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['get_companies_table'] = Field('get_companies_table', json_schema_extra={"ui:hidden": True})
    table_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    email: str = Field(..., min_length=3, max_length=320)


class LushaUpdateCompaniesTableConfig(_Input):
    """Update Companies Table. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['update_companies_table'] = Field('update_companies_table', json_schema_extra={"ui:hidden": True})
    table_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    name: str | None = Field(None)
    visibility: Literal['private', 'shared'] | None = Field(None)
    archived: bool | None = Field(None, description='Set `true` to archive the table (hides it from default List Tables results), `false` to restore it.')
    owner: LushaTableOwner = Field(..., description='Identifies the user acting on the table, and resolves to a user on your account. Required on every table-route call when authenticating with an API key (there is no signed-in user) - omitting it returns `400`. Optional for OAuth/token callers, since the caller is already identified by the token; still accepted if you want to act on behalf of another owner.\n', json_schema_extra=JSON_EDITOR)


class LushaDeleteCompaniesTableConfig(_Input):
    """Delete Companies Table. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['delete_companies_table'] = Field('delete_companies_table', json_schema_extra={"ui:hidden": True})
    table_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    email: str = Field(..., min_length=3, max_length=320)


class LushaGetCompaniesTableEntitiesConfig(_Input):
    """Get Companies Table Entities. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['get_companies_table_entities'] = Field('get_companies_table_entities', json_schema_extra={"ui:hidden": True})
    table_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    email: str = Field(..., min_length=3, max_length=320)
    page: int = Field(0, le=100)
    size: int = Field(100)


class LushaAddCompaniesTableEntitiesConfig(_Input):
    """Add Entities to Companies Table. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['add_companies_table_entities'] = Field('add_companies_table_entities', json_schema_extra={"ui:hidden": True})
    table_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    entityIds: list[str] = Field(..., max_length=500, description='Lusha IDs as strings - `personId` for contacts, `lushaCompanyId` for companies. Accepts either the encrypted token (`v{N}.…`, as returned by Search/Enrich/Get Entities) or the legacy numeric ID. An ID that is neither a valid token nor numeric returns `400`.\n', json_schema_extra=JSON_EDITOR)
    companyIds: list[str] | None = Field(None, description='Contacts tables only. One `lushaCompanyId` per contact (encrypted token or numeric), index-aligned with `entityIds`, to help pair company-level enrichment to the right company for each contact. Ignored on companies tables.\n', json_schema_extra=JSON_EDITOR)
    owner: LushaTableOwner = Field(..., description='Identifies the user acting on the table, and resolves to a user on your account. Required on every table-route call when authenticating with an API key (there is no signed-in user) - omitting it returns `400`. Optional for OAuth/token callers, since the caller is already identified by the token; still accepted if you want to act on behalf of another owner.\n', json_schema_extra=JSON_EDITOR)


class LushaRemoveCompaniesTableEntitiesConfig(_Input):
    """Remove Entities from Companies Table. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['remove_companies_table_entities'] = Field('remove_companies_table_entities', json_schema_extra={"ui:hidden": True})
    table_id: str = Field(..., min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    entityIds: list[str] = Field(..., description='Accepts either the encrypted token (`v{N}.…`, as returned by Get Entities) or the legacy numeric ID. Unresolved IDs are echoed back in `invalidIds` in the exact form you sent them.\n', json_schema_extra=JSON_EDITOR)
    owner: LushaTableOwner = Field(..., description='Identifies the user acting on the table, and resolves to a user on your account. Required on every table-route call when authenticating with an API key (there is no signed-in user) - omitting it returns `400`. Optional for OAuth/token callers, since the caller is already identified by the token; still accepted if you want to act on behalf of another owner.\n', json_schema_extra=JSON_EDITOR)


class LushaGetAccountUsageConfig(_Input):
    """Get Account Usage. One provider request; billing and pagination are returned unchanged."""
    operation: Literal['get_account_usage'] = Field('get_account_usage', json_schema_extra={"ui:hidden": True})


LushaConfig = Annotated[Union[LushaSearchContactsConfig, LushaEnrichContactsConfig, LushaSearchAndEnrichContactsConfig, LushaSearchCompaniesConfig, LushaEnrichCompaniesConfig, LushaSearchAndEnrichCompaniesConfig, LushaProspectingContactsConfig, LushaProspectingCompaniesConfig, LushaCreateContactsTableConfig, LushaListContactsTablesConfig, LushaGetContactsTableConfig, LushaUpdateContactsTableConfig, LushaDeleteContactsTableConfig, LushaGetContactsTableEntitiesConfig, LushaAddContactsTableEntitiesConfig, LushaRemoveContactsTableEntitiesConfig, LushaCreateCompaniesTableConfig, LushaListCompaniesTablesConfig, LushaGetCompaniesTableConfig, LushaUpdateCompaniesTableConfig, LushaDeleteCompaniesTableConfig, LushaGetCompaniesTableEntitiesConfig, LushaAddCompaniesTableEntitiesConfig, LushaRemoveCompaniesTableEntitiesConfig, LushaGetAccountUsageConfig], Field(discriminator="operation")]


class LushaFullConfig(NodeConfig[LushaConfig, LushaAPIKeyCredential]):
    pass


OPERATIONS = {'search_contacts': ('POST', '/v3/contacts/search', [], ['contacts', 'options', 'signals'], [200]),
 'enrich_contacts': ('POST',
                     '/v3/contacts/enrich',
                     [],
                     ['ids', 'reveal', 'waterfallEnabled', 'tableId'],
                     [200]),
 'search_and_enrich_contacts': ('POST',
                                '/v3/contacts/search-and-enrich',
                                [],
                                ['contacts', 'reveal', 'options'],
                                [200]),
 'search_companies': ('POST',
                      '/v3/companies/search',
                      [],
                      ['companies', 'options', 'signals'],
                      [200]),
 'enrich_companies': ('POST', '/v3/companies/enrich', [], ['ids', 'reveal', 'tableId'], [200]),
 'search_and_enrich_companies': ('POST',
                                 '/v3/companies/search-and-enrich',
                                 [],
                                 ['companies', 'reveal', 'options'],
                                 [200]),
 'prospecting_contacts': ('POST',
                          '/v3/contacts/prospecting',
                          [],
                          ['pagination', 'filters', 'tableId', 'options'],
                          [200]),
 'prospecting_companies': ('POST',
                           '/v3/companies/prospecting',
                           [],
                           ['pagination', 'filters', 'tableId', 'options'],
                           [200]),
 'create_contacts_table': ('POST',
                           '/v3/contacts/tables',
                           [],
                           ['name', 'visibility', 'owner', 'ids'],
                           [201]),
 'list_contacts_tables': ('POST',
                          '/v3/contacts/tables/list',
                          [],
                          ['owner', 'page', 'size', 'name', 'status'],
                          [200]),
 'get_contacts_table': ('GET', '/v3/contacts/tables/{table_id}', ['email'], [], [200]),
 'update_contacts_table': ('PATCH',
                           '/v3/contacts/tables/{table_id}',
                           [],
                           ['name', 'visibility', 'archived', 'owner'],
                           [200]),
 'delete_contacts_table': ('DELETE', '/v3/contacts/tables/{table_id}', ['email'], [], [200]),
 'get_contacts_table_entities': ('GET',
                                 '/v3/contacts/tables/{table_id}/entities',
                                 ['email', 'page', 'size'],
                                 [],
                                 [200]),
 'add_contacts_table_entities': ('POST',
                                 '/v3/contacts/tables/{table_id}/entities',
                                 [],
                                 ['entityIds', 'companyIds', 'owner'],
                                 [200]),
 'remove_contacts_table_entities': ('DELETE',
                                    '/v3/contacts/tables/{table_id}/entities',
                                    [],
                                    ['entityIds', 'owner'],
                                    [200]),
 'create_companies_table': ('POST',
                            '/v3/companies/tables',
                            [],
                            ['name', 'visibility', 'owner', 'ids'],
                            [201]),
 'list_companies_tables': ('POST',
                           '/v3/companies/tables/list',
                           [],
                           ['owner', 'page', 'size', 'name', 'status'],
                           [200]),
 'get_companies_table': ('GET', '/v3/companies/tables/{table_id}', ['email'], [], [200]),
 'update_companies_table': ('PATCH',
                            '/v3/companies/tables/{table_id}',
                            [],
                            ['name', 'visibility', 'archived', 'owner'],
                            [200]),
 'delete_companies_table': ('DELETE', '/v3/companies/tables/{table_id}', ['email'], [], [200]),
 'get_companies_table_entities': ('GET',
                                  '/v3/companies/tables/{table_id}/entities',
                                  ['email', 'page', 'size'],
                                  [],
                                  [200]),
 'add_companies_table_entities': ('POST',
                                  '/v3/companies/tables/{table_id}/entities',
                                  [],
                                  ['entityIds', 'companyIds', 'owner'],
                                  [200]),
 'remove_companies_table_entities': ('DELETE',
                                     '/v3/companies/tables/{table_id}/entities',
                                     [],
                                     ['entityIds', 'owner'],
                                     [200]),
 'get_account_usage': ('GET', '/v3/account/usage', [], [], [200])}


class LushaNode(WorkflowNode):
    integration_type = "automation-lusha"
    connection_evidence = ConnectionEvidence(operation="get_account_usage", noun="Lusha account usage")

    @classmethod
    def get_config_model(cls):
        return LushaFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Lusha API key")
        config = self.config.config
        method, path, query_fields, body_fields, success_codes = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        if "table_id" in values:
            path = path.replace("{table_id}", quote(values["table_id"], safe=""))
        params = {key: values[key] for key in query_fields if key in values}
        payload = {key: values[key] for key in body_fields if key in values}
        kwargs = {"params": params, "headers": {"api_key": self.config.credentials.api_key, "Accept": "application/json"}}
        if body_fields:
            kwargs["json"] = payload
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, **kwargs)
        if response.status_code not in success_codes:
            # Preserve a provider rejection for the connect seam, redacting the key.
            message = "Lusha returned HTTP " + str(response.status_code)
            try:
                error = response.json()
                if isinstance(error, dict):
                    detail = error.get("message") or error.get("error")
                    if isinstance(detail, str):
                        message = detail[:2000]
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code,
                "error": message.replace(self.config.credentials.api_key, "[redacted]")}
        if len(response.content) > 10_000_000:
            raise ValueError("Lusha response exceeds the supported JSON size")
        body = response.json()
        if not isinstance(body, dict) or body.get("error") or body.get("errors"):
            raise ValueError("Lusha returned an invalid or failed response")
        return {"status": "success", "operation": config.operation, "data": body}
