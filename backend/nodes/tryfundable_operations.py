"""Typed Tryfundable v2 request models, transcribed from the published contract.

Keep discovery filters in their documented sections; collection requests return
one page, and identifier lookups require exactly one provider identifier.
Source: https://docs.tryfundable.ai/openapi.json (version 2.0.0).
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, ClassVar, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, AwareDatetime, Field, StrictBool, StrictInt, model_validator


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    identifier_fields: ClassVar[tuple[str, ...]] = ()

    @model_validator(mode="after")
    def check_identifiers_and_dates(self):
        if self.identifier_fields and sum(getattr(self, key) is not None for key in self.identifier_fields) != 1:
            raise ValueError("Supply exactly one identifier for this lookup")
        for lower, upper in (("start_date", "end_date"), ("date_start", "date_end"), ("created_start", "created_end")):
            start, end = getattr(self, lower, None), getattr(self, upper, None)
            if start is not None and end is not None and start > end:
                raise ValueError("Start must be on or before end")
        if hasattr(self, "alert_ids"):
            ids = self.alert_ids.split(",")
            if not 1 <= len(ids) <= 10:
                raise ValueError("Supply one to ten alert UUIDs")
            for value in ids:
                UUID(value)
        return self


class TryfundableSearchDealsConfigIdentifiers(_Input):
    deal_ids: list[UUID] | None = Field(None, description='Deal UUIDs', examples=[['550e8400-e29b-41d4-a716-446655440000']])


class TryfundableSearchDealsConfigDealFinancingTypesItem(_Input):
    type: Literal['SERIES_A', 'SERIES_B', 'SERIES_C', 'SERIES_D', 'SERIES_E', 'SERIES_F', 'SERIES_G', 'SERIES_H', 'SERIES_I', 'SERIES_J', 'SERIES_K', 'SERIES_L', 'SERIES_M', 'SEED', 'SAFE', 'CONVERTIBLE_NOTE', 'EQUITY', 'PREFERRED', 'SECONDARY_MARKET', 'DEBT_FINANCING', 'GRANT', 'NON_EQUITY_ASSISTANCE', 'CROWDFUNDING', 'INITIAL_COIN_OFFERING', 'FUNDING_ROUND'] = Field(...)
    pre: StrictBool = Field(False, description='Pre-round modifier (e.g., Pre-Seed, Pre-Series A)')
    extension: StrictBool = Field(False, description='Extension round modifier')


class TryfundableSearchDealsConfigDeal(_Input):
    financing_types: list[TryfundableSearchDealsConfigDealFinancingTypesItem] | None = Field(None, description='Financing types with optional modifiers (pre, extension)', examples=[[{'type': 'SEED', 'pre': True}, {'type': 'SERIES_A'}]])
    size_min: float | None = Field(None, ge=0, description='Minimum deal size (USD)', examples=[1000000])
    size_max: float | None = Field(None, ge=0, description='Maximum deal size (USD)', examples=[100000000])
    date_start: date | None = Field(None, description='Filter deals announced after this date (ISO 8601)', examples=['2024-01-01'])
    date_end: date | None = Field(None, description='Filter deals announced before this date (ISO 8601)', examples=['2024-12-31'])
    created_start: date | None = Field(None, description='Filter deals added to the system after this date (ISO 8601)', examples=['2024-01-01'])
    created_end: date | None = Field(None, description='Filter deals added to the system before this date (ISO 8601)', examples=['2024-12-31'])


class TryfundableSearchDealsConfigCompany(_Input):
    company_ids: list[UUID] | None = Field(None, description='Company UUIDs - filter deals by specific companies', examples=[['550e8400-e29b-41d4-a716-446655440001']])
    locations: list[str] | None = Field(None, description='Location permalinks. Use /location/search to find permalinks. A value that is not an exact permalink is silently ignored (returns zero results, no error).', examples=[['san-francisco-california', 'california']])
    industries: list[str] | None = Field(None, description='Industry permalinks. Use /industry/search to find permalinks. A value that is not an exact permalink is silently ignored (returns zero results, no error).', examples=[['artificial-intelligence', 'fintech-e067']])
    super_categories: list[str] | None = Field(None, description='Super category permalinks (automatically includes related industries). Use /industry/search to find permalinks. A value that is not an exact permalink is silently ignored (returns zero results, no error).', examples=[['artificial-intelligence-e551']])
    employee_count: list[Literal['1-10', '11-50', '51-100', '101-250', '251-500', '501-1000', '1001-5000', '5001-10000', '10001+']] | None = Field(None, description='Employee count ranges. Valid: 1-10, 11-50, 51-100, 101-250, 251-500, 501-1000, 1001-5000, 5001-10000, 10001+', examples=[['1-10', '11-50']])
    ipo_status: list[Literal['public', 'private']] | None = Field(None, description='IPO status filter. Valid: public, private', examples=[['private']])
    total_raised_min: float | None = Field(None, ge=0, description='Minimum total raised (USD)', examples=[10000000])
    total_raised_max: float | None = Field(None, ge=0, description='Maximum total raised (USD)', examples=[500000000])


class TryfundableSearchDealsConfigInvestors(_Input):
    investor_ids: list[UUID] | None = Field(None, description='Investor UUIDs (firms)', examples=[['c5a3f6ac-f6c9-4686-aa6e-12aeb7419b82']])
    people_ids: list[UUID] | None = Field(None, description='Person UUIDs — matches deals where any of these people participated as an\n**angel investor** OR as a **lead partner** of an investing firm.\nResolve via `/people/{id}`.\n', examples=[['b3e9c7d1-2f4a-4d5e-9c1b-7a8f3e2d1c6a']])


class TryfundableSearchDealsConfig(_Input):
    'Use this endpoint when the requested result is a set of funding rounds, or when\ndeal criteria must match any historical round rather than only each company\'s\nlatest round. It supports round-level analysis across the full deal history.\n\nFor most company-sourcing requests, prefer `POST /companies`: it returns company\nmetadata together with the full latest deal. Its `latest_deal` filters apply only\nto each company\'s most recent round. For example, use `/companies` for "find AI\ncompanies in San Francisco whose latest round was Seed," but use `/deals` for\n"analyze every Seed round announced last year."\n\nDeal records contain full round details, but related companies and investors are\nidentified by IDs instead of full entity profiles. Use `GET /company?id=...` to\nretrieve company metadata and `GET /deals/{id}/investors` to retrieve the full\ninvestor lineup for a returned deal.\n\n## Request Body Structure\nSend a JSON body with up to 4 filter sections plus pagination/sort at the top level:\n- `identifiers` - Look up specific deals by UUID\n- `deal` - Filter by deal attributes (financing type, size, date)\n- `company` - Filter by company attributes (location, industry, size)\n- `investors` - Filter by investor participation (firms or people, by UUID)\n'
    operation: Literal['search_deals'] = Field('search_deals', title='Search Deals', json_schema_extra={"ui:hidden": True})
    identifiers: TryfundableSearchDealsConfigIdentifiers | None = Field(None, description='Look up specific deals by identifier')
    deal: TryfundableSearchDealsConfigDeal | None = Field(None, description='Deal attribute filters')
    company: TryfundableSearchDealsConfigCompany | None = Field(None, description='Company attribute filters')
    investors: TryfundableSearchDealsConfigInvestors | None = Field(None, description='Filter by investor participation (firms or people)')
    page: StrictInt = Field(0, ge=0, description='Page number (0-based)')
    page_size: StrictInt = Field(10, ge=1, le=500, description='Number of results per page')
    sort_by: Literal['most_recent_deal', 'oldest_deal', 'largest_raise', 'smallest_raise'] = Field('most_recent_deal', description='Sort order for results')


class TryfundableGetDealConfig(_Input):
    'Use this endpoint when a deal UUID is already known and full details for that one\nfunding round are required. The response identifies related entities by ID rather\nthan embedding their full profiles. Use `GET /company?id=...` for company metadata\nand `GET /deals/{id}/investors` for the complete investor lineup.\n'
    operation: Literal['get_deal'] = Field('get_deal', title='Get Deal', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., description='Unique identifier for the deal (UUID format)', examples=['4b20cafe-c22b-441a-8378-53436e1d9edf'])


class TryfundableGetDealInvestorsConfig(_Input):
    'Use this endpoint after identifying a deal when investor IDs in the deal record\nneed to be resolved into the complete investor lineup. It returns firm investors,\nassociated people, angel investors, lead status, and profile links for one deal.\n\nDo not use this endpoint to discover investors across many deals. Use\n`POST /investors` when the desired result is a list of firms, or `POST /people`\nwith investor filters when the desired result is individual investors.\n'
    operation: Literal['get_deal_investors'] = Field('get_deal_investors', title='Get Deal Investors', json_schema_extra={"ui:hidden": True})
    id: UUID = Field(..., description='Unique identifier for the deal (UUID format)', examples=['4b20cafe-c22b-441a-8378-53436e1d9edf'])


class TryfundableGetCompanyConfig(_Input):
    'Use this endpoint when one company is already identified and its full profile and\nlatest funding round are required. Prefer a domain or LinkedIn URL when available;\nthey can be passed directly here without calling `/company/search` first.\n\nUse `/company/search` for fuzzy company-name resolution or an uncertain identifier.\nUse `POST /companies` to discover or batch-retrieve multiple companies.\n\nProvide ONE of the following query parameters to identify the company:\n- `id` - Company UUID\n- `domain` - Company domain or full URL (e.g., "stripe.com" or "https://stripe.com")\n- `linkedin` - LinkedIn company URL\n- `crunchbase` - Crunchbase organization URL\n\nThe response includes the company\'s latest funding round details with participating investors.\n'
    identifier_fields = ('id', 'domain', 'linkedin', 'crunchbase')
    operation: Literal['get_company'] = Field('get_company', title='Get Company', json_schema_extra={"ui:hidden": True})
    id: UUID | None = Field(None, description='Company UUID', examples=['550e8400-e29b-41d4-a716-446655440000'])
    domain: str | None = Field(None, min_length=1, description='Company domain or full URL (e.g., "stripe.com" or "https://stripe.com") — URLs are automatically parsed to extract the domain', examples=['stripe.com'])
    linkedin: str | None = Field(None, min_length=1, description='LinkedIn company URL', examples=['https://linkedin.com/company/stripe'])
    crunchbase: str | None = Field(None, min_length=1, description='Crunchbase organization URL', examples=['https://crunchbase.com/organization/stripe'])


class TryfundableGetCompanyDealsConfig(_Input):
    'Use this endpoint when a company is already identified and its complete funding\nhistory is required. Prefer a domain or LinkedIn URL when available; it can be\npassed directly without first calling `/company/search`.\n\nThis route retrieves history for one identified company. Use `POST /deals` instead\nto discover rounds across the market with deal, company, or investor filters.\n\nProvide ONE of the following query parameters to identify the company:\n- `id` - Company UUID\n- `domain` - Company domain or full URL (e.g., "stripe.com" or "https://stripe.com")\n- `linkedin` - LinkedIn company URL\n- `crunchbase` - Crunchbase organization URL\n\nThe response includes the company\'s deals with pagination. If the identifier matches multiple companies, deals from all matches are returned.\n'
    identifier_fields = ('id', 'domain', 'linkedin', 'crunchbase')
    operation: Literal['get_company_deals'] = Field('get_company_deals', title='Get Company Deals', json_schema_extra={"ui:hidden": True})
    id: UUID | None = Field(None, description='Company UUID', examples=['550e8400-e29b-41d4-a716-446655440000'])
    domain: str | None = Field(None, min_length=1, description='Company domain or full URL (e.g., "stripe.com" or "https://stripe.com") — URLs are automatically parsed to extract the domain', examples=['stripe.com'])
    linkedin: str | None = Field(None, min_length=1, description='LinkedIn company URL', examples=['https://linkedin.com/company/stripe'])
    crunchbase: str | None = Field(None, min_length=1, description='Crunchbase organization URL', examples=['https://crunchbase.com/organization/stripe'])
    page: StrictInt = Field(0, ge=0, description='Page number (0-based)', examples=[0])
    page_size: StrictInt = Field(10, ge=1, le=500, description='Number of results per page (1-500)', examples=[10])


class TryfundableSearchCompanyConfig(_Input):
    'Use this endpoint primarily to resolve a fuzzy company name or an uncertain\nidentifier into matching company records. If a reliable domain or LinkedIn URL is\nalready available, skip this search and pass it directly to `GET /company` for one\nfull profile or to `POST /companies` for a batch lookup.\n\nExactly one parameter must be provided.\n\n**Search types:**\n- `name` — Fuzzy name search with relevance scoring\n- `domain` — Company domain or full URL\n- `linkedin` — LinkedIn company URL\n- `crunchbase` — Crunchbase organization URL\n\nExamples:\n- `?linkedin=https://linkedin.com/company/stripe`\n- `?crunchbase=https://crunchbase.com/organization/notion`\n'
    identifier_fields = ('name', 'domain', 'linkedin', 'crunchbase')
    operation: Literal['search_company'] = Field('search_company', title='Search Company', json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=1, description='Fuzzy search by company name', examples=['stripe'])
    domain: str | None = Field(None, min_length=1, description='Company domain or full URL (e.g., "stripe.com" or "https://stripe.com") — URLs are automatically parsed to extract the domain', examples=['stripe.com'])
    linkedin: str | None = Field(None, min_length=1, description='LinkedIn company URL', examples=['https://linkedin.com/company/stripe'])
    crunchbase: str | None = Field(None, min_length=1, description='Crunchbase organization URL', examples=['https://crunchbase.com/organization/notion'])


class TryfundableSearchCompaniesConfigIdentifiers(_Input):
    ids: list[UUID] | None = Field(None, description='Company UUIDs', examples=[['97ae048e-77bc-471b-821a-f9decb373689']])
    domains: list[str] | None = Field(None, description='Company domains (max 100)', examples=[['stripe.com', 'airbnb.com']])
    linkedin_urls: list[str] | None = Field(None, description='LinkedIn company URLs (max 100)', examples=[['https://linkedin.com/company/stripe', 'https://linkedin.com/company/airbnb']])
    crunchbase_urls: list[str] | None = Field(None, description='Crunchbase organization URLs (max 100)', examples=[['https://crunchbase.com/organization/stripe', 'https://crunchbase.com/organization/airbnb']])


class TryfundableSearchCompaniesConfigCompany(_Input):
    search_query: str | None = Field(None, min_length=1, description='AI-powered semantic search — a flexible replacement for an industry tag. First use /industry/search and apply an `industries` or `super_categories` filter when the taxonomy contains the intended category. Use semantic search only for a niche industry or specific product type the taxonomy cannot express, describing what the company does — its product, technology, or business model (e.g. "AI-powered medical imaging diagnostics" or "vertical SaaS for dental practices"). Do NOT use it for other attributes like stage, location, funding, or employee count — apply those with the dedicated filter fields instead. Results include a similarity score, are sorted by relevance, and are capped at 150 semantic matches.', examples=['AI-powered medical imaging diagnostics software'])
    min_relevance: float | None = Field(None, ge=0, le=1, description='Minimum similarity threshold (0-1). Only applies with search_query.', examples=[0.5])
    locations: list[str] | None = Field(None, description='Location permalinks. Use /location/search to find permalinks. A value that is not an exact permalink is silently ignored (returns zero results, no error).', examples=[['san-francisco-california', 'california']])
    industries: list[str] | None = Field(None, description='Industry permalinks. Use /industry/search to find permalinks. A value that is not an exact permalink is silently ignored (returns zero results, no error).', examples=[['artificial-intelligence', 'fintech-e067']])
    super_categories: list[str] | None = Field(None, description='Super category permalinks (automatically includes related industries). Use /industry/search to find permalinks. A value that is not an exact permalink is silently ignored (returns zero results, no error).', examples=[['artificial-intelligence-e551']])
    employee_count: list[Literal['1-10', '11-50', '51-100', '101-250', '251-500', '501-1000', '1001-5000', '5001-10000', '10001+']] | None = Field(None, description='Employee count ranges. Valid: 1-10, 11-50, 51-100, 101-250, 251-500, 501-1000, 1001-5000, 5001-10000, 10001+', examples=[['1-10', '11-50']])
    ipo_status: list[Literal['public', 'private']] | None = Field(None, description='IPO status filter. Valid: public, private', examples=[['private']])
    total_raised_min: float | None = Field(None, ge=0, description='Minimum total raised (USD)', examples=[10000000])
    total_raised_max: float | None = Field(None, ge=0, description='Maximum total raised (USD)', examples=[500000000])


class TryfundableSearchCompaniesConfigLatestDealFinancingTypesItem(_Input):
    type: Literal['SERIES_A', 'SERIES_B', 'SERIES_C', 'SERIES_D', 'SERIES_E', 'SERIES_F', 'SERIES_G', 'SERIES_H', 'SERIES_I', 'SERIES_J', 'SERIES_K', 'SERIES_L', 'SERIES_M', 'SEED', 'SAFE', 'CONVERTIBLE_NOTE', 'EQUITY', 'PREFERRED', 'SECONDARY_MARKET', 'DEBT_FINANCING', 'GRANT', 'NON_EQUITY_ASSISTANCE', 'CROWDFUNDING', 'INITIAL_COIN_OFFERING', 'FUNDING_ROUND'] = Field(...)
    pre: StrictBool = Field(False, description='Pre-round modifier (e.g., Pre-Seed, Pre-Series A)')
    extension: StrictBool = Field(False, description='Extension round modifier')


class TryfundableSearchCompaniesConfigLatestDeal(_Input):
    financing_types: list[TryfundableSearchCompaniesConfigLatestDealFinancingTypesItem] | None = Field(None, description='Financing types with optional modifiers (pre, extension)', examples=[[{'type': 'SEED', 'pre': True}, {'type': 'SERIES_A'}]])
    size_min: float | None = Field(None, ge=0, description='Minimum deal size (USD)', examples=[1000000])
    size_max: float | None = Field(None, ge=0, description='Maximum deal size (USD)', examples=[100000000])
    date_start: date | None = Field(None, description='Latest deal after this date (ISO 8601)', examples=['2024-01-01'])
    date_end: date | None = Field(None, description='Latest deal before this date (ISO 8601)', examples=['2024-12-31'])
    created_start: date | None = Field(None, description='Latest deal record added to the system on or after this date (ISO 8601). Filters by ingestion date (`created_at`), not the announcement date — useful for finding rounds newly added to Fundable.', examples=['2024-01-01'])
    created_end: date | None = Field(None, description='Latest deal record added to the system on or before this date (ISO 8601). Filters by ingestion date (`created_at`), not the announcement date.', examples=['2024-12-31'])
    investor_ids: list[UUID] | None = Field(None, description='Filter by investors who participated in the latest deal only', examples=[['c5a3f6ac-f6c9-4686-aa6e-12aeb7419b82']])


class TryfundableSearchCompaniesConfigInvestors(_Input):
    investor_ids: list[UUID] | None = Field(None, description='Investor UUIDs — matches companies where these investors participated in any round ever', examples=[['c5a3f6ac-f6c9-4686-aa6e-12aeb7419b82']])
    people_ids: list[UUID] | None = Field(None, description='Person UUIDs — matches companies where any of these people participated in any round\nas an **angel investor** OR as a **lead partner** of an investing firm.\nResolve via `/people/{id}`.\n', examples=[['b3e9c7d1-2f4a-4d5e-9c1b-7a8f3e2d1c6a']])


class TryfundableSearchCompaniesConfig(_Input):
    'Use this endpoint by default for company sourcing and discovery. It returns company\nmetadata such as name and domain together with the full details of each company\'s\nlatest funding round.\n\nFilters inside `latest_deal` apply only to the company\'s most recent round. Use\n`POST /deals` instead when deal criteria must match any round in a company\'s history.\nFor example, `/companies` is appropriate for "find AI companies in San Francisco\nwhose latest round was Seed"; `/deals` is appropriate for "analyze all Seed rounds\nannounced last year," regardless of whether Seed is now the company\'s latest round.\n\nFilters inside `investors` can match investor participation across all rounds.\n\n## Request Body Structure\nSend a JSON body with up to 4 filter sections plus pagination/sort at the top level:\n- `identifiers` - Look up specific companies by UUID, domain, LinkedIn, or Crunchbase\n- `company` - Filter by company attributes (search, location, industry, size, etc.)\n- `latest_deal` - Filter by latest funding round attributes (type, size, date, investors)\n- `investors` - Filter by investors (firms or people) across all rounds\n'
    operation: Literal['search_companies'] = Field('search_companies', title='Search Companies', json_schema_extra={"ui:hidden": True})
    identifiers: TryfundableSearchCompaniesConfigIdentifiers | None = Field(None, description='Look up specific companies by identifier')
    company: TryfundableSearchCompaniesConfigCompany | None = Field(None, description='Company attribute filters')
    latest_deal: TryfundableSearchCompaniesConfigLatestDeal | None = Field(None, description='Latest funding round filters')
    investors: TryfundableSearchCompaniesConfigInvestors | None = Field(None, description='Filter by investors (firms or people) across all funding rounds')
    page: StrictInt = Field(0, ge=0, description='Page number (0-based)')
    page_size: StrictInt = Field(10, ge=1, le=500, description='Number of results per page')
    sort_by: Literal['most_recent_raise', 'oldest_raise', 'most_recent_founded', 'oldest_founded', 'largest_valuation', 'smallest_valuation', 'largest_total_raise', 'smallest_total_raise', 'most_funding_rounds', 'most_investors'] = Field('most_recent_raise', description='Sort order. Ignored when search_query is provided (sorted by relevance).')


class TryfundableListInvestorsConfigIdentifiers(_Input):
    ids: list[UUID] | None = Field(None, description='Investor UUIDs', examples=[['c5a3f6ac-f6c9-4686-aa6e-12aeb7419b82']])
    domains: list[str] | None = Field(None, description='Investor domains (max 100)', examples=[['sequoiacap.com', 'a16z.com']])
    linkedin_urls: list[str] | None = Field(None, description='Investor LinkedIn URLs (max 100)', examples=[['https://linkedin.com/company/sequoia-capital', 'https://linkedin.com/company/andreessen-horowitz']])
    crunchbase_urls: list[str] | None = Field(None, description='Investor Crunchbase URLs (max 100)', examples=[['https://crunchbase.com/organization/sequoia-capital', 'https://crunchbase.com/organization/andreessen-horowitz']])


class TryfundableListInvestorsConfigInvestor(_Input):
    locations: list[str] | None = Field(None, description='Investor HQ location permalinks. Use /location/search to find permalinks. A value that is not an exact permalink is silently ignored (returns zero results, no error).', examples=[['san-francisco-california', 'menlo-park-california']])
    employee_count: list[Literal['1-10', '11-50', '51-100', '101-250', '251-500', '501-1000', '1001-5000', '5001-10000', '10001+']] | None = Field(None, description='Investor firm employee count ranges', examples=[['11-50', '51-100']])


class TryfundableListInvestorsConfigCompanyInvestmentsFinancingTypesItem(_Input):
    type: Literal['SERIES_A', 'SERIES_B', 'SERIES_C', 'SERIES_D', 'SERIES_E', 'SERIES_F', 'SERIES_G', 'SERIES_H', 'SERIES_I', 'SERIES_J', 'SERIES_K', 'SERIES_L', 'SERIES_M', 'SEED', 'SAFE', 'CONVERTIBLE_NOTE', 'EQUITY', 'PREFERRED', 'SECONDARY_MARKET', 'DEBT_FINANCING', 'GRANT', 'NON_EQUITY_ASSISTANCE', 'CROWDFUNDING', 'INITIAL_COIN_OFFERING', 'FUNDING_ROUND'] = Field(...)
    pre: StrictBool = Field(False, description='Pre-round modifier (e.g., Pre-Seed, Pre-Series A)')
    extension: StrictBool = Field(False, description='Extension round modifier')


class TryfundableListInvestorsConfigCompanyInvestments(_Input):
    company_ids: list[UUID] | None = Field(None, description='Portfolio company UUIDs', examples=[['97ae048e-77bc-471b-821a-f9decb373689']])
    search_query: str | None = Field(None, min_length=1, description='AI-powered semantic search matched against each investor\'s\nportfolio companies — a flexible replacement for an industry tag.\nFirst use /industry/search and apply an `industries` or\n`super_categories` filter when the taxonomy contains the intended\ncategory. Use semantic search only for a niche industry or specific\nproduct type the taxonomy cannot express, describing what those\ncompanies do — their product, technology, or business model (e.g.\n"climate-focused carbon capture hardware"). Do NOT use it for other\nattributes like stage, location, or funding — apply those with the\ndedicated `company_investments` and `investor` filter fields instead.\nResults are ranked by portfolio relevance and capped at 150 semantic\nmatches.\n', examples=['climate-focused carbon capture hardware'])
    min_relevance: float | None = Field(None, ge=0, le=1, description='Minimum relevance score threshold (0–1) for the portfolio-based\nsemantic search. Only applies when `search_query` is provided.\nInvestors whose portfolio match score falls below this threshold\nare excluded. Defaults to 0 (return all results).\n', examples=[0.5])
    locations: list[str] | None = Field(None, description='Portfolio company location permalinks. Use /location/search to find permalinks. A value that is not an exact permalink is silently ignored (returns zero results, no error).', examples=[['san-francisco-california']])
    industries: list[str] | None = Field(None, description='Portfolio company industry permalinks. Use /industry/search to find permalinks. A value that is not an exact permalink is silently ignored (returns zero results, no error).', examples=[['artificial-intelligence', 'fintech-e067']])
    super_categories: list[str] | None = Field(None, description='Broad industry super-category permalinks. Use /industry/search to find permalinks. A value that is not an exact permalink is silently ignored (returns zero results, no error).', examples=[['financial-services-d7b6']])
    employee_count: list[Literal['1-10', '11-50', '51-100', '101-250', '251-500', '501-1000', '1001-5000', '5001-10000', '10001+']] | None = Field(None, description='Portfolio company employee count ranges', examples=[['11-50', '51-100']])
    ipo_status: list[Literal['public', 'private']] | None = Field(None, description='Portfolio company IPO status', examples=[['private']])
    total_raised_min: float | None = Field(None, ge=0, description='Minimum total raised by portfolio companies (USD)', examples=[10000000])
    total_raised_max: float | None = Field(None, ge=0, description='Maximum total raised by portfolio companies (USD)', examples=[500000000])
    financing_types: list[TryfundableListInvestorsConfigCompanyInvestmentsFinancingTypesItem] | None = Field(None, description='Financing types with optional modifiers (pre, extension)', examples=[[{'type': 'SERIES_A'}, {'type': 'SERIES_B'}]])
    deal_size_min: float | None = Field(None, ge=0, description='Minimum deal size (USD)', examples=[1000000])
    deal_size_max: float | None = Field(None, ge=0, description='Maximum deal size (USD)', examples=[100000000])
    deal_start_date: date | None = Field(None, description='Filter deals on or after this date (ISO 8601)', examples=['2023-01-01'])
    deal_end_date: date | None = Field(None, description='Filter deals on or before this date (ISO 8601)', examples=['2024-12-31'])
    only_lead_deals: StrictBool = Field(False, description='When true, only count deals where investor was lead')
    min_matching_deals: StrictInt | None = Field(None, ge=1, description='Minimum number of deals matching the portfolio filters', examples=[3])


class TryfundableListInvestorsConfig(_Input):
    'Use this endpoint when the requested result is a list of investor firms. Filters\nunder `company_investments` identify qualifying portfolio companies and deals, then\nreturn the firms that participated in those deals. For example, use this route to\nfind San Francisco-based investors that participated in a Seed round during the\nlast year.\n\nUse `POST /people` with investor filters instead when the desired result is an\nindividual angel investor or lead partner attached to a firm. Use `POST /deals`\nwhen the desired result is the matching funding rounds themselves.\n\n## Request Body Structure\nSend a JSON body with up to 3 filter sections plus pagination/sort at the top level:\n- `identifiers` - Look up specific investors by UUID, domain, LinkedIn, or Crunchbase\n- `investor` - Filter by investor entity attributes (location, employee count)\n- `company_investments` - Filter by portfolio (industries, deal characteristics, etc.). Supports semantic search via `search_query` + `min_relevance`.\n\nWhen `company_investments` filters are active, `filtered_deal_count` is the number\nof deals that matched those filters and `filtered_lead_count` is the number of those\nmatched deals the investor led.\n'
    operation: Literal['list_investors'] = Field('list_investors', title='List Investors', json_schema_extra={"ui:hidden": True})
    identifiers: TryfundableListInvestorsConfigIdentifiers | None = Field(None, description="Investor lookup filters (OR'd together)")
    investor: TryfundableListInvestorsConfigInvestor | None = Field(None, description='Investor entity-level filters')
    company_investments: TryfundableListInvestorsConfigCompanyInvestments | None = Field(None, description='Portfolio filters (filter by companies the investor has invested in)')
    page: StrictInt = Field(0, ge=0, description='Page number (0-based)')
    page_size: StrictInt = Field(10, ge=1, le=500, description='Number of results per page (max 500)')
    sort_by: Literal['most_recent_deal', 'recent_deals', 'deals_led_ltm', 'total_deals', 'matching_deals'] = Field('most_recent_deal', description='Sort order for results.\n- **most_recent_deal** — Date of most recent investment (newest first)\n- **recent_deals** — Deals in last 12 months (highest first)\n- **deals_led_ltm** — Lead deals in last 12 months (highest first)\n- **total_deals** — All-time deal count (highest first)\n- **matching_deals** — Deals matching portfolio filters (highest first)\n')


class TryfundableGetInvestorConfig(_Input):
    'Use this endpoint when one investor firm is already identified and its full profile,\nstatistics, and portfolio summary are required. Prefer a domain or LinkedIn URL when\navailable; it can be passed directly without calling `/investor/search` first.\n\nUse `/investor/search` for fuzzy firm-name resolution or an uncertain identifier.\nUse `POST /investors` to discover or batch-retrieve multiple investor firms.\n\nProvide ONE of the following query parameters to identify the investor:\n- `id` - Investor UUID\n- `domain` - Investor domain or full URL (e.g., "sequoiacap.com" or "https://sequoiacap.com")\n- `linkedin` - LinkedIn company URL\n- `crunchbase` - Crunchbase organization URL\n\nThe response includes the investor\'s statistics, portfolio summary, and profile links.\n'
    identifier_fields = ('id', 'domain', 'linkedin', 'crunchbase')
    operation: Literal['get_investor'] = Field('get_investor', title='Get Investor', json_schema_extra={"ui:hidden": True})
    id: UUID | None = Field(None, description='Investor UUID', examples=['550e8400-e29b-41d4-a716-446655440000'])
    domain: str | None = Field(None, min_length=1, description='Investor domain or full URL (e.g., "sequoiacap.com" or "https://sequoiacap.com") — URLs are automatically parsed to extract the domain', examples=['sequoiacap.com'])
    linkedin: str | None = Field(None, min_length=1, description='LinkedIn company URL', examples=['https://linkedin.com/company/sequoia-capital'])
    crunchbase: str | None = Field(None, min_length=1, description='Crunchbase organization URL', examples=['https://crunchbase.com/organization/sequoia-capital'])


class TryfundableGetInvestorDealsConfig(_Input):
    'Use this endpoint when an investor firm is already identified and its complete deal\nhistory is required. Prefer a domain or LinkedIn URL when available; it can be passed\ndirectly without calling `/investor/search` first.\n\nUse `POST /investors` instead to discover firms from investment criteria, or\n`POST /deals` when the desired result is a filtered list of funding rounds.\n\nProvide ONE of the following query parameters to identify the investor:\n- `id` - Investor UUID\n- `domain` - Investor domain or full URL (e.g., "sequoiacap.com" or "https://sequoiacap.com")\n- `linkedin` - LinkedIn company URL\n- `crunchbase` - Crunchbase organization URL\n\nThe response includes the investor\'s deals with pagination. If the identifier matches multiple investors (e.g., a16z has multiple firms), deals from all matches are returned together.\n'
    identifier_fields = ('id', 'domain', 'linkedin', 'crunchbase')
    operation: Literal['get_investor_deals'] = Field('get_investor_deals', title='Get Investor Deals', json_schema_extra={"ui:hidden": True})
    id: UUID | None = Field(None, description='Investor UUID', examples=['550e8400-e29b-41d4-a716-446655440000'])
    domain: str | None = Field(None, min_length=1, description='Investor domain or full URL (e.g., "sequoiacap.com" or "https://sequoiacap.com") — URLs are automatically parsed to extract the domain', examples=['sequoiacap.com'])
    linkedin: str | None = Field(None, min_length=1, description='LinkedIn company URL', examples=['https://linkedin.com/company/sequoia-capital'])
    crunchbase: str | None = Field(None, min_length=1, description='Crunchbase organization URL', examples=['https://crunchbase.com/organization/sequoia-capital'])
    page: StrictInt = Field(0, ge=0, description='Page number (0-based)', examples=[0])
    page_size: StrictInt = Field(10, ge=1, le=500, description='Number of results per page (1-500)', examples=[10])


class TryfundableSearchInvestorsConfig(_Input):
    'Use this endpoint primarily to resolve a fuzzy investor-firm name or an uncertain\nidentifier. If a reliable domain or LinkedIn URL is already available, skip this\nsearch and pass it directly to `GET /investor` for one full profile or to\n`POST /investors` for a batch lookup.\n\nExactly one parameter must be provided.\n\n**Search types:**\n- `name` — Fuzzy name search with relevance scoring\n- `domain` — Investor domain or full URL\n- `linkedin` — LinkedIn company URL\n- `crunchbase` — Crunchbase organization URL\n\nIdentifier lookups (`domain`, `linkedin`, `crunchbase`) return `relevance_score: 1`.\nExamples:\n- `?linkedin=https://linkedin.com/company/sequoia-capital`\n- `?crunchbase=https://crunchbase.com/organization/sequoia-capital`\n'
    identifier_fields = ('name', 'domain', 'linkedin', 'crunchbase')
    operation: Literal['search_investors'] = Field('search_investors', title='Search Investors', json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=1, description='Investor name (fuzzy search with relevance scoring)', examples=['sequoia'])
    domain: str | None = Field(None, min_length=1, description='Investor domain or full URL (e.g., "sequoiacap.com" or "https://sequoiacap.com") — URLs are automatically parsed to extract the domain', examples=['sequoiacap.com'])
    linkedin: str | None = Field(None, min_length=1, description='LinkedIn company URL', examples=['https://linkedin.com/company/sequoia-capital'])
    crunchbase: str | None = Field(None, min_length=1, description='Crunchbase organization URL', examples=['https://crunchbase.com/organization/sequoia-capital'])


class TryfundableSearchPeopleConfigIdentifiers(_Input):
    ids: list[UUID] | None = Field(None, description='Person UUIDs', examples=[['550e8400-e29b-41d4-a716-446655440000']])
    linkedin_urls: list[str] | None = Field(None, description='LinkedIn person URLs (max 100)', examples=[['https://linkedin.com/in/jane-doe-12345', 'https://linkedin.com/in/john-smith']])
    crunchbase_urls: list[str] | None = Field(None, description='Crunchbase person URLs (max 100)', examples=[['https://crunchbase.com/person/jane-doe', 'https://www.crunchbase.com/person/john-smith']])
    twitter_urls: list[str] | None = Field(None, description='Twitter/X URLs (max 100)', examples=[['https://x.com/janedoe', 'https://x.com/johnsmith']])


class TryfundableSearchPeopleConfigPerson(_Input):
    roles: list[Literal['founder', 'ceo', 'key_person']] | None = Field(None, description="Person's role at their current employer", examples=[['founder', 'ceo']])
    contact_types: list[Literal['linkedin', 'email', 'phone', 'twitter']] | None = Field(None, description='Available contact info on the person', examples=[['email', 'linkedin']])
    job_titles: list[str] | None = Field(None, description='Normalized job-title keys', examples=[['ceo', 'cto', 'vp-engineering']])
    education_schools: list[str] | None = Field(None, description='Education institution IDs', examples=[['stanford-university', 'mit']])
    linkedin_companies: list[str] | None = Field(None, description='Filter by previous/current employer LinkedIn company IDs', examples=[['google', 'meta']])


class TryfundableSearchPeopleConfigCompanyLatestDealFinancingTypesItem(_Input):
    type: Literal['SERIES_A', 'SERIES_B', 'SERIES_C', 'SERIES_D', 'SERIES_E', 'SERIES_F', 'SERIES_G', 'SERIES_H', 'SERIES_I', 'SERIES_J', 'SERIES_K', 'SERIES_L', 'SERIES_M', 'SEED', 'SAFE', 'CONVERTIBLE_NOTE', 'EQUITY', 'PREFERRED', 'SECONDARY_MARKET', 'DEBT_FINANCING', 'GRANT', 'NON_EQUITY_ASSISTANCE', 'CROWDFUNDING', 'INITIAL_COIN_OFFERING', 'FUNDING_ROUND'] = Field(...)
    pre: StrictBool = Field(False)
    extension: StrictBool = Field(False)


class TryfundableSearchPeopleConfigCompanyLatestDeal(_Input):
    financing_types: list[TryfundableSearchPeopleConfigCompanyLatestDealFinancingTypesItem] | None = Field(None, description='Financing types with optional modifiers (pre, extension)', examples=[[{'type': 'SEED', 'pre': True}, {'type': 'SERIES_A'}]])
    size_min: float | None = Field(None, ge=0, description='Minimum latest-deal size (USD)', examples=[1000000])
    size_max: float | None = Field(None, ge=0, description='Maximum latest-deal size (USD)', examples=[50000000])
    date_start: date | None = Field(None, examples=['2024-01-01'])
    date_end: date | None = Field(None, examples=['2024-12-31'])
    investor_ids: list[UUID] | None = Field(None, description='Filter to deals where these investor UUIDs participated', examples=[['770e8400-e29b-41d4-a716-446655440000']])
    investor_locations: list[str] | None = Field(None, description="Filter to deals with investors HQ'd in these locations", examples=[['san-francisco-california']])


class TryfundableSearchPeopleConfigCompany(_Input):
    search_query: str | None = Field(None, min_length=1, description='AI-powered semantic search against the person\'s current employer — a flexible replacement for an industry tag. First use /industry/search and apply an `industries` or `super_categories` filter when the taxonomy contains the intended category. Use semantic search only for a niche industry or product type the taxonomy cannot express, describing what that company does — its product, technology, or business model (e.g. "climate tech carbon accounting software"). Do NOT use it for stage, location, or funding — apply dedicated filters instead. Results are ordered by relevance and capped at 150 semantic matches.', examples=['climate tech carbon accounting software'])
    min_relevance: float | None = Field(None, ge=0, le=1, description='Minimum similarity threshold (0-1). Only applies with search_query.', examples=[0.5])
    ids: list[UUID] | None = Field(None, description='Filter by current-employer UUIDs', examples=[['660e8400-e29b-41d4-a716-446655440000']])
    locations: list[str] | None = Field(None, description='Location permalinks. Use /location/search to find permalinks. A value that is not an exact permalink is silently ignored (returns zero results, no error).', examples=[['san-francisco-california', 'new-york-new-york']])
    industries: list[str] | None = Field(None, description='Industry permalinks. Use /industry/search to find permalinks. A value that is not an exact permalink is silently ignored (returns zero results, no error).', examples=[['artificial-intelligence', 'fintech-e067']])
    super_categories: list[str] | None = Field(None, description='Super category permalinks (auto-includes related industries). Use /industry/search to find permalinks. A value that is not an exact permalink is silently ignored (returns zero results, no error).', examples=[['financial-services-d7b6']])
    employee_count: list[Literal['1-10', '11-50', '51-100', '101-250', '251-500', '501-1000', '1001-5000', '5001-10000', '10001+']] | None = Field(None, description='Current-employer headcount ranges', examples=[['11-50', '51-100']])
    ipo_status: list[Literal['public', 'private', 'acquired', 'delisted']] | None = Field(None, description='Current-employer IPO status', examples=[['private']])
    total_raised_min: float | None = Field(None, ge=0, description='Minimum total raised by current employer (USD)', examples=[1000000])
    total_raised_max: float | None = Field(None, ge=0, description='Maximum total raised by current employer (USD)', examples=[100000000])
    investor_people_ids: list[UUID] | None = Field(None, description='Person UUIDs — filter to people whose current employer has ever raised\nfrom any of these people as an **angel investor** OR as a **lead partner**\nof an investing firm. Resolve via `/people/{id}`.\n', examples=[['b3e9c7d1-2f4a-4d5e-9c1b-7a8f3e2d1c6a']])
    latest_deal: TryfundableSearchPeopleConfigCompanyLatestDeal | None = Field(None, description="Nested. Filters on the current employer's most recent funding round.")


class TryfundableSearchPeopleConfigInvestorDealsFinancingTypesItem(_Input):
    type: Literal['SERIES_A', 'SERIES_B', 'SERIES_C', 'SERIES_D', 'SERIES_E', 'SERIES_F', 'SERIES_G', 'SERIES_H', 'SERIES_I', 'SERIES_J', 'SERIES_K', 'SERIES_L', 'SERIES_M', 'SEED', 'SAFE', 'CONVERTIBLE_NOTE', 'EQUITY', 'PREFERRED', 'SECONDARY_MARKET', 'DEBT_FINANCING', 'GRANT', 'NON_EQUITY_ASSISTANCE', 'CROWDFUNDING', 'INITIAL_COIN_OFFERING', 'FUNDING_ROUND'] = Field(...)
    pre: StrictBool = Field(False)
    extension: StrictBool = Field(False)


class TryfundableSearchPeopleConfigInvestorDeals(_Input):
    search_query: str | None = Field(None, min_length=1, description='AI-powered semantic search against the person\'s portfolio companies — a flexible replacement for an industry tag. First use /industry/search and apply an `industries` or `super_categories` filter when the taxonomy contains the intended category. Use semantic search only for a niche industry or product type the taxonomy cannot express, describing what those companies do (e.g. "AI infrastructure for model training"). Do NOT use it for stage, location, or funding — apply dedicated filters instead. Results are ordered by relevance and capped at 150 semantic matches.', examples=['AI infrastructure for model training'])
    min_relevance: float | None = Field(None, ge=0, le=1, description='Minimum similarity threshold (0-1). Only applies with search_query.', examples=[0.5])
    investment_type: Literal['all', 'angel', 'institutional'] = Field('all', description='Filter by whether the person invests as an angel, under a firm, or both', examples=['angel'])
    only_lead_deals: StrictBool = Field(False, description='Only count deals where the person/firm was a lead investor')
    min_matching_deals: StrictInt | None = Field(None, ge=1, description='Require at least this many deals to match the deal filters', examples=[3])
    financing_types: list[TryfundableSearchPeopleConfigInvestorDealsFinancingTypesItem] | None = Field(None, description="Financing types for the person's investment activity")
    size_min: float | None = Field(None, ge=0, description="Minimum deal size (USD) for the person's deal activity", examples=[500000])
    size_max: float | None = Field(None, ge=0, description="Maximum deal size (USD) for the person's deal activity", examples=[10000000])
    date_start: date | None = Field(None, examples=['2023-01-01'])
    date_end: date | None = Field(None, examples=['2024-12-31'])
    industries: list[str] | None = Field(None, description='Portfolio company industry permalinks', examples=[['artificial-intelligence']])
    super_categories: list[str] | None = Field(None, description='Portfolio company super-category permalinks')
    portfolio_locations: list[str] | None = Field(None, description='Portfolio company location permalinks')
    portfolio_employee_count: list[Literal['1-10', '11-50', '51-100', '101-250', '251-500', '501-1000', '1001-5000', '5001-10000', '10001+']] | None = Field(None, description='Portfolio company headcount ranges')
    ipo_status: list[Literal['public', 'private']] | None = Field(None, description='Portfolio company IPO status')
    total_raised_min: float | None = Field(None, ge=0, description='Minimum total raised by the portfolio company (USD)', examples=[1000000])
    total_raised_max: float | None = Field(None, ge=0, description='Maximum total raised by the portfolio company (USD)')


class TryfundableSearchPeopleConfigInvestor(_Input):
    ids: list[UUID] | None = Field(None, description='Firm (parent investor) UUIDs', examples=[['c5a3f6ac-f6c9-4686-aa6e-12aeb7419b82']])
    domains: list[str] | None = Field(None, description='Firm domains (max 100)', examples=[['sequoiacap.com', 'a16z.com']])
    linkedin_urls: list[str] | None = Field(None, description='Firm LinkedIn URLs (max 100)', examples=[['https://linkedin.com/company/sequoia-capital']])
    crunchbase_urls: list[str] | None = Field(None, description='Firm Crunchbase URLs (max 100)', examples=[['https://crunchbase.com/organization/sequoia-capital']])
    permalinks: list[str] | None = Field(None, description='Fundable firm permalinks (max 100)', examples=[['sequoia-capital', 'andreessen-horowitz']])
    locations: list[str] | None = Field(None, description='Firm HQ location permalinks', examples=[['menlo-park-california']])
    employee_count: list[Literal['1-10', '11-50', '51-100', '101-250', '251-500', '501-1000', '1001-5000', '5001-10000', '10001+']] | None = Field(None, description='Firm headcount ranges')
    deals: TryfundableSearchPeopleConfigInvestorDeals | None = Field(None, description='Nested. Combined deal-activity and portfolio-company filters. Includes:\ndeal-level controls (`investment_type`, `min_matching_deals`, `only_lead_deals`),\nround-level filters (`financing_types`, `size_min/max`, `date_start/end`), and\nportfolio-company attributes (`industries`, `super_categories`,\n`portfolio_locations`, `portfolio_employee_count`, `ipo_status`,\n`total_raised_min/max`, plus semantic `search_query` / `min_relevance`).\n')


class TryfundableSearchPeopleConfig(_Input):
    "Use this endpoint when the requested result is a list of people.\n\nWith `person_type: company`, it returns founders, executives, or employees based on\ntheir current employer. Filters under `company.latest_deal` apply only to that\nemployer's latest funding round, like `POST /companies`; funding information is used\nfor filtering but is not included in the returned person record. For example, use\nthis mode to find founders of AI companies in San Francisco whose latest round was\nSeries A.\n\nWith `person_type: investor`, it applies investment and portfolio filters in the same\nway that `POST /investors` does, but returns individual angel investors or lead\npartners attached to their firms rather than firm records. Use `POST /investors`\nwhen the desired result is firms, and `POST /deals` when it is funding rounds.\n\n## Request Body Structure\nSend a JSON body with up to 4 filter sections plus pagination/sort at the top level:\n- `identifiers` - Look up specific people by UUID, LinkedIn, Crunchbase, or Twitter\n- `person` - Filter by person attributes (role, contact info, job title, education, prior employers)\n- `company` - Filter by current employer attributes (industry, location, funding, IPO status, etc.)\n- `investor` - Filter by investor activity (firm, deal characteristics, portfolio companies)\n"
    operation: Literal['search_people'] = Field('search_people', title='Search People', json_schema_extra={"ui:hidden": True})
    person_type: Literal['company', 'investor', 'any'] = Field('any', description='Restrict results to one population. `company` returns only people with a\ncurrent employer (founders, executives, employees). `investor` returns only\npeople who invest. `any` (default) returns the union — anyone matching the\nother filter blocks regardless of population.\n', examples=['company'])
    identifiers: TryfundableSearchPeopleConfigIdentifiers | None = Field(None, description='Look up specific people by identifier')
    person: TryfundableSearchPeopleConfigPerson | None = Field(None, description='Person attribute filters')
    company: TryfundableSearchPeopleConfigCompany | None = Field(None, description='Current-employer attribute filters. Setting any field implicitly requires the person to have a current employer.')
    investor: TryfundableSearchPeopleConfigInvestor | None = Field(None, description="Filters on the investor entity (firm) and on the person's deal activity.\nSetting any field (including any nested `deals.*` field) implicitly requires\nthe person to be an investor.\n")
    page: StrictInt = Field(0, ge=0, description='Page number (0-based)')
    page_size: StrictInt = Field(10, ge=1, le=500, description='Number of results per page (max 500)')
    sort_by: Literal['most_recent_deal_date', 'total_raised', 'latest_deal_size', 'name', 'total_deal_count', 'deal_count_last_12_months', 'lead_deal_count', 'lead_deal_count_last_12_months', 'filtered_deal_count'] = Field('most_recent_deal_date', description='Sort order. All values are universally accepted — non-applicable values (e.g. `lead_deal_count`\nwhen no investor filter is set) resolve to 0 / null via COALESCE and naturally sort to the bottom (DESC).\nIgnored when `company.search_query` or `investor.deals.search_query` is set (results are then\nordered by semantic relevance).\n')


class TryfundableGetPersonConfig(_Input):
    'Use this endpoint when one person is already identified and their full profile is\nrequired. Prefer a LinkedIn URL when available; it can be passed directly without\ncalling `/person/search` first.\n\nUse `/person/search` for fuzzy name resolution or an uncertain identifier. Use\n`POST /people` to discover or batch-retrieve multiple people.\n\nProvide ONE of the following query parameters to identify the person:\n- `id` - Person UUID\n- `linkedin` - LinkedIn person URL\n- `crunchbase` - Crunchbase person URL\n- `twitter` - Twitter/X URL\n\nReturns the same constant unified shape as the list endpoint, with **full**\nemployment and education history (no per-section limit).\n'
    identifier_fields = ('id', 'linkedin', 'crunchbase', 'twitter')
    operation: Literal['get_person'] = Field('get_person', title='Get Person', json_schema_extra={"ui:hidden": True})
    id: UUID | None = Field(None, description='Person UUID', examples=['550e8400-e29b-41d4-a716-446655440000'])
    linkedin: str | None = Field(None, min_length=1, description='LinkedIn person URL', examples=['https://www.linkedin.com/in/eladgil/'])
    crunchbase: str | None = Field(None, min_length=1, description='Crunchbase person URL', examples=['https://crunchbase.com/person/jane-doe'])
    twitter: str | None = Field(None, min_length=1, description='Twitter/X URL', examples=['https://x.com/janedoe'])


class TryfundableUnlockPersonEmailConfig(_Input):
    'Use this endpoint only when a verified email is explicitly required for an identified\nperson. Return a verified email for a person identified by UUID, LinkedIn, Crunchbase,\nor Twitter/X. Provide one identifier. If multiple identifiers are supplied, the\nendpoint uses the first non-empty value in this order: `id`, `linkedin`,\n`crunchbase`, `twitter`.\n\nA newly created unlock costs 5 credits. Repeating the request for an email the\nsame user already unlocked costs 0 credits. Unlock ownership persists across API\nkeys belonging to that account. Provider attribution is internal and is not returned.\n\nAvailable on non-trial Pro+, Enterprise, and API plans.\n'
    identifier_fields = ('id', 'linkedin', 'crunchbase', 'twitter')
    operation: Literal['unlock_person_email'] = Field('unlock_person_email', title='Unlock Person Email', json_schema_extra={"ui:hidden": True})
    id: UUID | None = Field(None, description='Fundable person UUID', examples=['550e8400-e29b-41d4-a716-446655440000'])
    linkedin: str | None = Field(None, min_length=1, description='LinkedIn person URL, slug, or supported normalized identifier', examples=['https://www.linkedin.com/in/eladgil/'])
    crunchbase: str | None = Field(None, min_length=1, description='Crunchbase person URL or supported normalized identifier', examples=['https://www.crunchbase.com/person/jane-doe'])
    twitter: str | None = Field(None, min_length=1, description='Twitter/X URL or handle', examples=['https://x.com/janedoe'])


class TryfundableUnlockPersonPhoneConfig(_Input):
    'Use this endpoint only when a verified phone number is explicitly required for an identified\nperson. Return a verified phone number for a person identified by UUID, LinkedIn, Crunchbase,\nor Twitter/X. Provide one identifier. If multiple identifiers are supplied, the\nendpoint uses the first non-empty value in this order: `id`, `linkedin`,\n`crunchbase`, `twitter`.\n\nA newly created unlock costs 5 credits. Repeating the request for a phone number the\nsame account already unlocked costs 0 credits. Unlock ownership persists across API\nkeys belonging to that account. Provider attribution is internal and is not returned.\n\nAvailable on non-trial Pro+, Enterprise, and API plans.\n'
    identifier_fields = ('id', 'linkedin', 'crunchbase', 'twitter')
    operation: Literal['unlock_person_phone'] = Field('unlock_person_phone', title='Unlock Person Phone', json_schema_extra={"ui:hidden": True})
    id: UUID | None = Field(None, description='Fundable person UUID', examples=['550e8400-e29b-41d4-a716-446655440000'])
    linkedin: str | None = Field(None, min_length=1, description='LinkedIn person URL, slug, or supported normalized identifier', examples=['https://www.linkedin.com/in/eladgil/'])
    crunchbase: str | None = Field(None, min_length=1, description='Crunchbase person URL or supported normalized identifier', examples=['https://www.crunchbase.com/person/jane-doe'])
    twitter: str | None = Field(None, min_length=1, description='Twitter/X URL or handle', examples=['https://x.com/janedoe'])


class TryfundableGetPersonDealsConfig(_Input):
    "Use this endpoint when a person is already identified and their investment history\nis required. It returns deals the person joined as an angel plus lead or firm deals.\nPrefer a LinkedIn URL when available; it can be passed directly without first calling\n`/person/search`.\n\nProvide ONE of the following query parameters to identify the person:\n- `id` - Person UUID\n- `linkedin` - LinkedIn person URL\n- `crunchbase` - Crunchbase person URL\n- `twitter` - Twitter/X URL\n\nThe response includes the person's investment deals with pagination.\n"
    identifier_fields = ('id', 'linkedin', 'crunchbase', 'twitter')
    operation: Literal['get_person_deals'] = Field('get_person_deals', title='Get Person Deals', json_schema_extra={"ui:hidden": True})
    id: UUID | None = Field(None, description='Person UUID', examples=['550e8400-e29b-41d4-a716-446655440000'])
    linkedin: str | None = Field(None, min_length=1, description='LinkedIn person URL', examples=['https://www.linkedin.com/in/eladgil/'])
    crunchbase: str | None = Field(None, min_length=1, description='Crunchbase person URL', examples=['https://crunchbase.com/person/jane-doe'])
    twitter: str | None = Field(None, min_length=1, description='Twitter/X URL', examples=['https://x.com/janedoe'])
    page: StrictInt = Field(0, ge=0, description='Page number (0-based)', examples=[0])
    page_size: StrictInt = Field(10, ge=1, le=500, description='Number of results per page (1-500)', examples=[10])


class TryfundableSearchPersonConfig(_Input):
    'Use this endpoint primarily to resolve a fuzzy person name or uncertain identifier.\nIf a reliable LinkedIn URL is already available, skip this search and pass it directly\nto `GET /person` for one full profile or to `POST /people` for a batch lookup.\n\nExactly one parameter must be provided.\n\n**Search types:**\n- `name` — Fuzzy name search across both investors AND non-investor people (founders, employees). Returns up to 10 results.\n- `id` — Person UUID lookup (returns 0 or 1)\n- `linkedin` — LinkedIn person URL or slug\n- `crunchbase` — Crunchbase person URL or slug\n- `twitter` — Twitter/X URL or handle\n\n`person_type` on each result indicates which pool the row came from\n(`investor` wins when a person is in both). For full person detail, use `/person`.\n'
    identifier_fields = ('name', 'id', 'linkedin', 'crunchbase', 'twitter')
    operation: Literal['search_person'] = Field('search_person', title='Search Person', json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=1, description='Fuzzy search by person name', examples=['jane doe'])
    id: UUID | None = Field(None, description='Person UUID', examples=['550e8400-e29b-41d4-a716-446655440000'])
    linkedin: str | None = Field(None, min_length=1, description='LinkedIn person URL', examples=['https://www.linkedin.com/in/eladgil/'])
    crunchbase: str | None = Field(None, min_length=1, description='Crunchbase person URL', examples=['https://crunchbase.com/person/jane-doe'])
    twitter: str | None = Field(None, min_length=1, description='Twitter/X URL', examples=['https://x.com/janedoe'])
    person_type: Literal['investor', 'company'] | None = Field(None, description="Optional filter restricting results to one pool. `investor` keeps only\npeople tracked as investors/angels; `company` keeps only non-investor\npeople (founders, CEOs, employees). Omit to search both. Applies to\nboth name and identifier modes — identifier lookups return empty if\nthe resolved person doesn't match the requested type.\n", examples=['investor'])


class TryfundableGetAlertsConfig(_Input):
    'Retrieve saved alert data including all deals that matched the alert criteria within the specified date range.\nResults include a flattened array of deals sorted by date (newest first) with duplicates removed.\n\nAvailable on Pro+ and Enterprise plans. This endpoint does not consume credits.\n\n**Multiple Alerts Support:**\n- Query multiple alerts in a single request (up to 10)\n- Each alert returns its own flattened deals array\n- Different alerts can have different frequencies (e.g., one daily, one weekly)\n- Successful requests report `credits_used: 0`, regardless of deal count\n\n**Important Notes:**\n- All alert_ids must belong to alerts you have access to\n- Deals are flattened from all time periods and sorted by date DESC (newest first)\n- Duplicate deals are automatically removed\n- Each deal includes AI-generated reasoning for why it matched the alert criteria\n- Deal structure is simplified with flattened company information for easier integration\n'
    operation: Literal['get_alerts'] = Field('get_alerts', title='Get Alerts', json_schema_extra={"ui:hidden": True})
    alert_ids: str = Field(..., min_length=1, description='Comma-separated list of alert UUIDs (up to 10 alerts per request).\nAll alerts must be associated with your API key\'s account.\nExample: "uuid1,uuid2,uuid3"\n', examples=['550e8400-e29b-41d4-a716-446655440000,660e8400-e29b-41d4-a716-446655440001'])
    start_date: AwareDatetime = Field(..., description='Start date for the alert data range (ISO 8601 format).\nResults will include deals from this date onwards.\n', examples=['2024-01-01T00:00:00.000Z'])
    end_date: AwareDatetime = Field(..., description='End date for the alert data range (ISO 8601 format).\nResults will include deals up to and including this date.\n\n**Note:** All dates are processed in UTC timezone. Deals are grouped into time periods based on UTC date boundaries.\n', examples=['2024-12-31T23:59:59.999Z'])


class TryfundableListAlertConfigurationsConfig(_Input):
    'Retrieve all alert configurations for the authenticated user (identified by API key).\nReturns configuration metadata including filters, frequency, and descriptions.\n\nAvailable on Pro+ and Enterprise plans. This endpoint does not consume credits.\n\n**Important Notes:**\n- This endpoint does NOT consume usage credits (actualUsageCount: 0)\n- Returns only configuration metadata, not deal data\n- Does not require any query parameters - user is identified by API key\n- All configurations for the authenticated user are returned (no pagination)\n\n**Authentication:**\n- User identity is automatically determined from the API key\n- No email or user_id parameter needed\n\n**Use Cases:**\n- Look up what alerts are configured for the authenticated user\n- Retrieve alert filter settings for external integrations\n- Audit alert configurations programmatically\n'
    operation: Literal['list_alert_configurations'] = Field('list_alert_configurations', title='List Alert Configurations', json_schema_extra={"ui:hidden": True})


class TryfundableSearchLocationsConfig(_Input):
    "Use this endpoint to resolve a human-readable city, state, country, or region into\nthe exact permalink required by location filters on discovery endpoints. Agents\nshould not guess permalinks. Select the result that matches the user's intended\ngeography, then pass its permalink to the relevant filter.\n\nThe `name` parameter is required; `type` is optional.\n\n**Search types:**\n- `name` — Fuzzy name search with relevance scoring (required)\n- `type` — Optional filter by location type: `CITY`, `STATE`, `REGION`, or `COUNTRY`\n- `location_type` — Alias for `type`\n\nExamples:\n- `?name=san francisco`\n- `?name=california&type=STATE`\n"
    operation: Literal['search_locations'] = Field('search_locations', title='Search Locations', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, description='Location name to search for', examples=['san francisco'])
    type: Literal['CITY', 'STATE', 'REGION', 'COUNTRY'] | None = Field(None, description='Filter by specific location type', examples=['CITY'])
    location_type: Literal['CITY', 'STATE', 'REGION', 'COUNTRY'] | None = Field(None, description="Alias for 'type' parameter", examples=['CITY'])


class TryfundableSearchIndustriesConfig(_Input):
    'Use this endpoint before semantic search to resolve a human-readable category into\nan exact `INDUSTRY` or `SUPER_CATEGORY` permalink. Agents should not guess permalinks.\nIf the taxonomy has an appropriate result, use its permalink in the structured\nindustry filter. Use `search_query` only when the requested niche is not represented\nby the taxonomy.\n\nThe `name` parameter is required; `type` is optional.\n\n**Search types:**\n- `name` — Fuzzy name search with relevance scoring (required)\n- `type` — Optional filter by industry type: `INDUSTRY` or `SUPER_CATEGORY`\n- `industry_type` — Alias for `type`\n\nExamples:\n- `?name=artificial intelligence`\n- `?name=fintech&type=INDUSTRY`\n'
    operation: Literal['search_industries'] = Field('search_industries', title='Search Industries', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, description='Industry name to search for', examples=['artificial intelligence'])
    type: Literal['INDUSTRY', 'SUPER_CATEGORY'] | None = Field(None, description='Filter by specific industry type', examples=['INDUSTRY'])
    industry_type: Literal['INDUSTRY', 'SUPER_CATEGORY'] | None = Field(None, description="Alias for 'type' parameter", examples=['INDUSTRY'])

TryfundableConfig = Annotated[Union[
    TryfundableSearchDealsConfig,
    TryfundableGetDealConfig,
    TryfundableGetDealInvestorsConfig,
    TryfundableGetCompanyConfig,
    TryfundableGetCompanyDealsConfig,
    TryfundableSearchCompanyConfig,
    TryfundableSearchCompaniesConfig,
    TryfundableListInvestorsConfig,
    TryfundableGetInvestorConfig,
    TryfundableGetInvestorDealsConfig,
    TryfundableSearchInvestorsConfig,
    TryfundableSearchPeopleConfig,
    TryfundableGetPersonConfig,
    TryfundableUnlockPersonEmailConfig,
    TryfundableUnlockPersonPhoneConfig,
    TryfundableGetPersonDealsConfig,
    TryfundableSearchPersonConfig,
    TryfundableGetAlertsConfig,
    TryfundableListAlertConfigurationsConfig,
    TryfundableSearchLocationsConfig,
    TryfundableSearchIndustriesConfig,
], Field(discriminator="operation")]

ROUTES = {'search_deals': ('POST', '/deals'), 'get_deal': ('GET', '/deals/{id}'), 'get_deal_investors': ('GET', '/deals/{id}/investors'), 'get_company': ('GET', '/company'), 'get_company_deals': ('GET', '/company/deals'), 'search_company': ('GET', '/company/search'), 'search_companies': ('POST', '/companies'), 'list_investors': ('POST', '/investors'), 'get_investor': ('GET', '/investor'), 'get_investor_deals': ('GET', '/investor/deals'), 'search_investors': ('GET', '/investor/search'), 'search_people': ('POST', '/people'), 'get_person': ('GET', '/person'), 'unlock_person_email': ('GET', '/person/email'), 'unlock_person_phone': ('GET', '/person/phone'), 'get_person_deals': ('GET', '/person/deals'), 'search_person': ('GET', '/person/search'), 'get_alerts': ('GET', '/alerts'), 'list_alert_configurations': ('GET', '/alerts/configurations'), 'search_locations': ('GET', '/location/search'), 'search_industries': ('GET', '/industry/search')}
