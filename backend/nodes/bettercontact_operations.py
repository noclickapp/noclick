"""Typed BetterContact request shapes from the published v2 contract. No credentials in bodies."""
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class NewLeadsEnrichmentDataItem(RequestModel):
    first_name: str = Field(..., description='First name of the contact.')
    last_name: str = Field(..., description='Last name of the contact.')
    company: str | None = Field(None, description='Company name. Provide either `company` or `company_domain`. `company_domain` gives better results.')
    company_domain: str | None = Field(None, description='Company domain. Provide either `company` or `company_domain`.')
    linkedin_url: str | None = Field(None, description='Public LinkedIn profile URL. Strongly recommended when `enrich_phone_number` is `true`, and required for `enrich_profile`.')
    custom_fields: dict[str, Any] | None = Field(None, description='Any data you want echoed back in the response, such as a CRM record id. Keys are free-form; `uuid` and `list_name` below are only an example.\n\nSent as an object, returned as an array of `{ name, value, position }` entries.')


class NewLeadsEnrichment(RequestModel):
    data: list[NewLeadsEnrichmentDataItem] = Field(..., min_length=1, max_length=100, description='Leads to enrich. Between 1 and 100 per call. Sending more than 100 is rejected with `400`.')
    enrich_email_address: bool = Field(True, description='Enrich the work email address. When `enrich_email_address`, `enrich_phone_number` and `enrich_profile` are all omitted or `false`, email enrichment is applied by default.', strict=True)
    enrich_phone_number: bool = Field(False, description='Enrich the mobile phone number. Requires the phone add-on on your plan, otherwise the call is rejected with `402`. Provide `linkedin_url` for best results.', strict=True)
    enrich_profile: bool = Field(False, description='Enrich the full LinkedIn profile of the contact (headline, seniority, location, current company). Requires `linkedin_url`.', strict=True)
    verify_catch_all: bool = Field(False, description='Run the extra catch-all verification layer. When enabled, `contact_email_address_status` returns `catch_all_safe` / `catch_all_not_safe` instead of `catch_all`. Requires the catch-all add-on on your plan, otherwise the call is rejected with `402`.', strict=True)
    webhook: str | None = Field(None, description='URL that receives the full result payload as soon as the whole batch is done. Recommended over polling. See [Webhooks](/api-reference/webhooks).')
    push_contact_individually: bool = Field(False, description='When `true`, each lead is pushed to `contact_webhook` as soon as it is enriched, instead of waiting for the whole batch. Useful for batches of 100.', strict=True)
    contact_webhook: str | None = Field(None, description='URL that receives one payload per lead. Only used when `push_contact_individually` is `true`.')
    process_flow: str | None = Field(None, description='Identifier of the process flow to use for this enrichment. Only for accounts subscribed to the process flow add-on.')
    timeout_seconds: int | None = Field(None, ge=1, description='Maximum time the waterfall is allowed to run before the request is terminated with whatever has been found. Defaults to the timeout configured on your account.', strict=True)


class CompanyDomainFilter(RequestModel):
    include: list[str] | None = Field(None, description='Company domains that must match.')
    exclude: list[str] | None = Field(None, description='Company domains that must NOT match.')


class CompanyLinkedinUrlFilter(RequestModel):
    include: list[str] | None = Field(None, description='Company LinkedIn page URLs that must match. Normalised server-side, so both the full URL and the slug are accepted.')
    exclude: list[str] | None = Field(None, description='Company LinkedIn page URLs that must NOT match.')


class CompanyIndustryFilter(RequestModel):
    include: list[str] | None = Field(None, description='Company industries that must match. Must be exact values from the predefined list, see [Taxonomies - Industries](/api-reference/taxonomies#industries).')
    exclude: list[str] | None = Field(None, description='Company industries that must NOT match. Same accepted values as `include`.')


class CompanyHqLocationFilter(RequestModel):
    include: list[str] | None = Field(None, description='HQ locations that must match. Accepts country names (e.g. "United States"), and also states or cities.')
    exclude: list[str] | None = Field(None, description='HQ locations that must NOT match. Same format as `include`.')


class CompanyTechnologiesFilter(RequestModel):
    include: list[str] | None = Field(None, description='Technologies that must match. Must be exact values from the predefined list, see [Taxonomies - Technologies](/api-reference/taxonomies#technologies).')
    exclude: list[str] | None = Field(None, description='Technologies that must NOT match. Same accepted values as `include`.')


class CompanyKeywordsFilter(RequestModel):
    include: list[str] | None = Field(None, description='Free-text keywords searched across the company profile.')
    exclude: list[str] | None = Field(None, description='Keywords that must NOT appear.')


class CompanyDescriptionFilter(RequestModel):
    include: list[str] | None = Field(None, description='Free-text phrases searched in the company description.')
    exclude: list[str] | None = Field(None, description='Phrases that must NOT appear in the company description.')


class RevenueRangesFilter(RequestModel):
    include: list[str] | None = Field(None, description='Revenue brackets that must match. Must be exact values from the predefined list, see [Taxonomies - Revenue ranges](/api-reference/taxonomies#revenue-ranges).')
    exclude: list[str] | None = Field(None, description='Revenue brackets that must NOT match.')


class FundingRoundNamesFilter(RequestModel):
    include: list[str] | None = Field(None, description='Last funding round names that must match. Must be exact values from the predefined list, see [Taxonomies - Funding round names](/api-reference/taxonomies#funding-round-names).')
    exclude: list[str] | None = Field(None, description='Last funding round names that must NOT match.')


class RangeFilter(RequestModel):
    gte: Any | None = Field(None, description='Greater than or equal to.')
    lte: Any | None = Field(None, description='Lower than or equal to.')


class JobPostingFilter(RequestModel):
    include: list[str] | None = Field(None, description="Values that must match on the company's active job postings.")
    exclude: list[str] | None = Field(None, description="Values that must NOT match on the company's active job postings.")


class FilterObject(RequestModel):
    include: list[str] | None = Field(None, description='Values that must match.')
    exclude: list[str] | None = Field(None, description='Values that must NOT match.')


class JobTitleFilter(FilterObject):
    exact_match: bool = Field(False, strict=True, description="Match include titles exactly instead of by substring.")


class SeniorityFilter(RequestModel):
    include: list[str] | None = Field(None, description='Seniority levels that must match. Must be exact values from the predefined list, see [Taxonomies - Seniority levels](/api-reference/taxonomies#seniority-levels).')
    exclude: list[str] | None = Field(None, description='Seniority levels that must NOT match.')


class LeadDepartmentFilter(RequestModel):
    include: list[str] | None = Field(None, description='Lead departments that must match. Must be exact values from the predefined list, see [Taxonomies - Departments](/api-reference/taxonomies#departments).')
    exclude: list[str] | None = Field(None, description='Lead departments that must NOT match.')


class LeadFunctionFilter(RequestModel):
    include: list[str] | None = Field(None, description='Lead functions that must match. Uses the same accepted values and the same underlying field as `lead_department`, see [Taxonomies - Functions](/api-reference/taxonomies#functions).')
    exclude: list[str] | None = Field(None, description='Lead functions that must NOT match.')


class LeadFinderFilters(RequestModel):
    company: CompanyDomainFilter | None = Field(None)
    company_linkedin_url: CompanyLinkedinUrlFilter | None = Field(None)
    company_industry: CompanyIndustryFilter | None = Field(None)
    company_hq_location: CompanyHqLocationFilter | None = Field(None)
    company_technologies: CompanyTechnologiesFilter | None = Field(None)
    company_keywords: CompanyKeywordsFilter | None = Field(None)
    company_description: CompanyDescriptionFilter | None = Field(None)
    company_headcount_min: int | None = Field(None, description='Minimum employee count. Converted server-side into the overlapping company size ranges listed in [Taxonomies - Company size ranges](/api-reference/taxonomies#company-size-ranges).', strict=True)
    company_headcount_max: int | None = Field(None, description='Maximum employee count. Converted server-side into the overlapping company size ranges listed in [Taxonomies - Company size ranges](/api-reference/taxonomies#company-size-ranges).', strict=True)
    revenue_ranges: RevenueRangesFilter | None = Field(None)
    last_funding_round_names: FundingRoundNamesFilter | None = Field(None)
    last_funding_date_range: RangeFilter | None = Field(None, description='Date of the last funding round, as `YYYY-MM-DD` strings.')
    last_amount_raised_usd: RangeFilter | None = Field(None, description='Amount raised in the last round, in USD.')
    total_amount_raised_usd: RangeFilter | None = Field(None, description='Total amount raised to date, in USD.')
    is_b2b: bool | None = Field(None, description='Restrict to companies selling to businesses. `false` is a meaningful value and is sent as-is.', strict=True)
    is_b2c: bool | None = Field(None, description='Restrict to companies selling to consumers. `false` is a meaningful value and is sent as-is.', strict=True)
    is_public: bool | None = Field(None, description='Restrict to publicly traded companies.', strict=True)
    job_post_titles: JobPostingFilter | None = Field(None, description='Job titles the company is currently hiring for.')
    job_posting_countries: JobPostingFilter | None = Field(None, description='Countries the company is currently hiring in.')
    job_posting_locations: JobPostingFilter | None = Field(None, description='Cities or regions the company is currently hiring in.')
    limit_per_company: int | None = Field(None, ge=1, le=100, description='Caps how many leads are returned per company. Useful to spread results across accounts instead of returning a whole org chart. Maximum 100.', strict=True)
    lead_fullname: FilterObject | None = Field(None)
    lead_linkedin_url: FilterObject | None = Field(None)
    lead_job_title: JobTitleFilter | None = Field(None)
    lead_seniority: SeniorityFilter | None = Field(None)
    lead_department: LeadDepartmentFilter | None = Field(None)
    lead_function: LeadFunctionFilter | None = Field(None)
    lead_skills: FilterObject | None = Field(None)
    lead_location: FilterObject | None = Field(None)


class LeadFinderRequest(RequestModel):
    filters: LeadFinderFilters = Field(...)
    limit: int | None = Field(None, ge=1, le=200, description='Number of leads to return for this request, between 1 and 200. Use it together with `offset` to paginate. Mutually exclusive with `max_leads`: when `limit` is set, `max_leads` is ignored.', strict=True)
    offset: int = Field(0, ge=0, description='Zero-based number of leads to skip before returning matches. Only taken into account when `limit` is set.\n\nTo walk through results, keep `limit` constant and increase `offset` by `limit` on each call: `0`, then `100`, then `200`, and so on. The total number of matching leads is returned as `summary.leads_found`.', strict=True)
    max_leads: int = Field(100, ge=1, le=200, description='Number of leads to return when you do not paginate. Between 1 and 200, defaults to 100. Ignored when `limit` is set.', strict=True)
    webhook: str | None = Field(None, description='URL that receives the results as soon as the search is done, removing the need to poll. See [Webhooks](/api-reference/webhooks).')
    enrich_email_address: bool = Field(False, description='When `true`, every lead found is also run through the waterfall email enrichment before the results are returned. This consumes enrichment credits on top of the search, and the request stays in `processing` until enrichment is done.', strict=True)
    enrich_phone_number: bool = Field(False, description='When `true`, every lead found is also run through the waterfall mobile phone enrichment before the results are returned. This consumes enrichment credits on top of the search. Requires the phone add-on on your plan.', strict=True)


class CompanyFinderIncludeFilter(RequestModel):
    include: list[str] | None = Field(None, description='Values that must match.')


class CompanyFinderFilters(RequestModel):
    company: CompanyFinderIncludeFilter | None = Field(None, description='Company domains, in lowercase: the match is case-sensitive, so `HUBSPOT.COM` finds nothing. A leading `http://`, `https://` or `www.` is stripped, but a path is not: pass `acme.com`, not `https://acme.com/about`.')
    company_linkedin_url: CompanyFinderIncludeFilter | None = Field(None, description='Company LinkedIn page URLs.')
    company_industry: CompanyFinderIncludeFilter | None = Field(None, description='Industries. Must be exact values from [Taxonomies - Industries](/api-reference/taxonomies#industries).')
    company_hq_location: CompanyFinderIncludeFilter | None = Field(None, description='Matched against the full headquarters address, so a city, a state or a country all work.')
    company_technologies: CompanyFinderIncludeFilter | None = Field(None, description='Technologies the company uses. Must be exact values from [Taxonomies - Technologies](/api-reference/taxonomies#technologies).')
    company_keywords: CompanyFinderIncludeFilter | None = Field(None, description='Keywords or phrases matched against the company profile. Matched the same way as `company_description`.')
    company_description: CompanyFinderIncludeFilter | None = Field(None, description='Phrases matched against the company profile. Matched the same way as `company_keywords`.')
    company_headcount_min: int | None = Field(None, ge=0, description='Minimum number of employees, inclusive. Mapped onto the size buckets of [Taxonomies - Company size ranges](/api-reference/taxonomies#company-size-ranges): every bucket that overlaps your range is kept, so `60` still returns companies from the `51-200` bucket.', strict=True)
    company_headcount_max: int | None = Field(None, ge=0, description='Maximum number of employees, inclusive. Mapped onto size buckets the same way as `company_headcount_min`.', strict=True)
    is_b2b: bool | None = Field(None, description='`true` keeps companies that sell to businesses. Omit the field when you do not want to filter on it.', strict=True)
    is_b2c: bool | None = Field(None, description='`true` keeps companies that sell to consumers. Omit the field when you do not want to filter on it.', strict=True)
    is_public: bool | None = Field(None, description='`true` keeps publicly listed companies. Omit the field when you do not want to filter on it.', strict=True)
    revenue_ranges: CompanyFinderIncludeFilter | None = Field(None, description='Revenue brackets. Must be exact values from [Taxonomies - Revenue ranges](/api-reference/taxonomies#revenue-ranges).')
    last_funding_round_names: CompanyFinderIncludeFilter | None = Field(None, description='Name of the latest funding round. Must be exact values from [Taxonomies - Funding round names](/api-reference/taxonomies#funding-round-names).')
    last_funding_date_range: RangeFilter | None = Field(None, description='Date of the last funding round, as `YYYY-MM-DD` strings.')
    last_amount_raised_usd: RangeFilter | None = Field(None, description='Amount raised in the last round, in USD, as integers.')
    total_amount_raised_usd: RangeFilter | None = Field(None, description='Total amount raised, in USD, as integers.')
    job_post_titles: CompanyFinderIncludeFilter | None = Field(None, description='Job titles the company is currently hiring for.')
    job_posting_countries: CompanyFinderIncludeFilter | None = Field(None, description='Countries the company is currently hiring in.')
    job_posting_locations: CompanyFinderIncludeFilter | None = Field(None, description='Cities or regions the company is currently hiring in.')


class CompanyFinderRequest(RequestModel):
    filters: CompanyFinderFilters = Field(...)
    limit: int = Field(100, ge=1, le=200, description='Number of companies to return for this page, between 1 and 200. Defaults to 100. A value above 200 is refused with `422`; `0`, a negative number or a non-numeric value falls back to the default.', strict=True)
    offset: int = Field(0, ge=0, description='Zero-based number of matches to skip. A negative value is treated as `0`.\n\nTo walk through results, keep `limit` constant and increase `offset` by `limit` on each call. The total number of matching companies is returned as `summary.companies_found`.', strict=True)


class EnrichCompanyRequest(RequestModel):
    company_domain: str | None = Field(None, description='Company website or domain.')
    company_linkedin_url: str | None = Field(None, description='Company LinkedIn page URL.')
