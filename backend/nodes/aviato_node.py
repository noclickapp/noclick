"""Aviato Data API v1: enrichment, prospect search and market-map generation.

One request per operation; pagination stays explicit and bulk lookup success
flags are preserved. API keys belong to a team and requests can spend credits.
Contract: https://docs.data.aviato.co/openapi.json (1.0.0).
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, Json, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://data.api.aviato.co"
CREDENTIAL_TYPE = "aviato_api_key"
Text = Annotated[str, Field(min_length=1, max_length=2048)]
JSON_EDITOR = {"ui:widget": "code_editor", "x-code-language": "json"}


class AviatoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Aviato API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://data.aviato.co/dashboard/teams",
            "x-credential-instructions": "Select your Aviato team, open API Keys, and create a key. Paste the key without the Bearer prefix. Enrichment, contact and search requests may spend your team's credits.",
            "x-help-url": "https://docs.data.aviato.co/intro/introduction-auth",
        })
    credential_type: Literal["aviato_api_key"] = Field("aviato_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, max_length=4096, title="API Key", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the Aviato API key without a header prefix or whitespace")
        return value


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class Company(Operation):
    lookup_value: Text = Field(..., description="Aviato company ID, website or LinkedIn URL, according to Lookup by.")
    lookup_by: Literal["id", "website", "linkedinURL", "linkedinID", "linkedinNumID", "crunchbaseID"] = "id"


class Person(Operation):
    lookup_value: Text = Field(..., description="Aviato person ID, LinkedIn URL or email, according to Lookup by.")
    lookup_by: Literal["id", "linkedinURL", "email", "linkedinID", "linkedinEntityId", "crunchbaseID"] = "id"


class CompanyDetails(Company):
    required_fields: list[Text] | None = Field(None, description="Require these top-level response fields to be nonempty, or return 404 without charging.")


class CompanyEnrich(CompanyDetails):
    preview: bool | None = Field(None, description="Only return identification information without charging a credit.")
    full: bool | None = Field(None, description="Include relational data such as funding and founders.")


class PersonEnrich(Person):
    preview: bool | None = Field(None, description="Only return identification information without charging a credit.")
    full: bool | None = Field(None, description="Include investments and founded companies.")
    required_fields: list[Text] | None = None


class CompanyPage(Company):
    page: int = Field(0, ge=0, description="Page number, starting at zero. Fetch one page per execution.")
    per_page: int = Field(25, ge=1, le=100)


class PersonPage(Person):
    page: int = Field(0, ge=0, description="Page number, starting at zero. Fetch one page per execution.")
    per_page: int = Field(25, ge=1, le=100)


class PersonContact(Person):
    email_type: Literal["personal", "work", "student"] | None = Field(None, description="Omit to return all email types.")


class CompanyLookup(Operation):
    id: Text | None = None
    website: Text | None = None
    linkedinURL: Text | None = None

    @model_validator(mode="after")
    def needs_lookup(self):
        if not (self.id or self.website or self.linkedinURL):
            raise ValueError("Supply a company id, website or linkedinURL for every lookup")
        return self


class PersonLookup(Operation):
    id: Text | None = None
    linkedinURL: Text | None = None
    email: Text | None = None

    @model_validator(mode="after")
    def needs_lookup(self):
        if not (self.id or self.linkedinURL or self.email):
            raise ValueError("Supply a person id, linkedinURL or email for every lookup")
        return self


class BulkCompany(Operation):
    lookups: Json[Annotated[list[CompanyLookup], Field(min_length=1, max_length=100)]] = Field(..., description="JSON array of company lookup objects (id, website or linkedinURL); at most 100.", json_schema_extra=JSON_EDITOR)
    required_fields: list[Text] | None = None


class BulkContact(Operation):
    lookups: Json[Annotated[list[PersonLookup], Field(min_length=1, max_length=20)]] = Field(..., description="JSON array of person lookup objects (id, linkedinURL or email); at most 20.", json_schema_extra=JSON_EDITOR)


class BulkPerson(BulkContact):
    preview: bool | None = None
    required_fields: list[Text] | None = None


class AviatoDSL(Operation):
    offset: int = Field(0, ge=0, le=10000)
    limit: int = Field(25, ge=1, le=250)
    sort: list[dict[str, Any]] = Field(default_factory=list)
    filters: list[dict[str, Any]] = Field(default_factory=list)
    nameQuery: Text | None = None


class Search(Operation):
    dsl: Json[AviatoDSL] = Field(..., description="Aviato DSL JSON: offset (0–10000), limit (1–250), sort and filters arrays; optional nameQuery. Returns one page. See https://docs.data.aviato.co/aviato-dsl/aviato-dsl-v-1", json_schema_extra=JSON_EDITOR)


class GenerateMap(Operation):
    company_id: Text = Field(..., description="Aviato company ID to generate a market map for. Returns mapID; use Get Market Map to retrieve the result.")


class GetMap(Operation):
    map_id: Text = Field(..., description="mapID returned by Generate Market Map.")


class AviatoGetBalanceConfig(Operation):
    """Get the credit balance for the team."""
    operation: Literal["get_balance"] = Field("get_balance", json_schema_extra={"ui:hidden": True})


class AviatoEnrichCompanyConfig(CompanyEnrich):
    """Get enriched details on a company"""
    operation: Literal["enrich_company"] = Field("enrich_company", json_schema_extra={"ui:hidden": True})


class AviatoGetCompanyFinancialsConfig(CompanyDetails):
    """Get a company's financial information, including the estimated annual revenue range. Returns 404 without charging when no category data is available."""
    operation: Literal["get_company_financials"] = Field("get_company_financials", json_schema_extra={"ui:hidden": True})


class AviatoGetCompanySocialMetricsConfig(CompanyDetails):
    """Get a company's social audience counts and growth metrics. Returns 404 without charging when no category data is available."""
    operation: Literal["get_company_social_metrics"] = Field("get_company_social_metrics", json_schema_extra={"ui:hidden": True})


class AviatoGetCompanyWebTrafficConfig(CompanyDetails):
    """Get a company's web traffic history, sources, and visitor geography. Returns 404 without charging when no category data is available."""
    operation: Literal["get_company_web_traffic"] = Field("get_company_web_traffic", json_schema_extra={"ui:hidden": True})


class AviatoGetCompanyLegalConfig(CompanyDetails):
    """Get a company's legal identifiers and registered name. Returns 404 without charging when no category data is available."""
    operation: Literal["get_company_legal"] = Field("get_company_legal", json_schema_extra={"ui:hidden": True})


class AviatoBulkEnrichCompaniesConfig(BulkCompany):
    """Get enriched details on multiple companies."""
    operation: Literal["bulk_enrich_companies"] = Field("bulk_enrich_companies", json_schema_extra={"ui:hidden": True})


class AviatoGetCompanyAcquisitionsConfig(CompanyPage):
    """Get the companies that have been acquired by the specified company."""
    operation: Literal["get_company_acquisitions"] = Field("get_company_acquisitions", json_schema_extra={"ui:hidden": True})


class AviatoGetCompanyFoundersConfig(CompanyPage):
    """Get the founders of the specified company."""
    operation: Literal["get_company_founders"] = Field("get_company_founders", json_schema_extra={"ui:hidden": True})


class AviatoGetCompanyInvestmentsConfig(CompanyPage):
    """Get a list of the investments made into the specified company."""
    operation: Literal["get_company_investments"] = Field("get_company_investments", json_schema_extra={"ui:hidden": True})


class AviatoGetCompanyFundingRoundsConfig(CompanyPage):
    """Get the funding rounds of the specified company."""
    operation: Literal["get_company_funding_rounds"] = Field("get_company_funding_rounds", json_schema_extra={"ui:hidden": True})


class AviatoGetCompanyEmployeesConfig(CompanyPage):
    """Get the employees of the specified company."""
    operation: Literal["get_company_employees"] = Field("get_company_employees", json_schema_extra={"ui:hidden": True})


class AviatoSearchCompaniesConfig(Search):
    """Search using the Aviato DSL. There is no application clause-count cap."""
    operation: Literal["search_companies"] = Field("search_companies", json_schema_extra={"ui:hidden": True})


class AviatoEnrichPersonConfig(PersonEnrich):
    """Get enriched details on a person."""
    operation: Literal["enrich_person"] = Field("enrich_person", json_schema_extra={"ui:hidden": True})


class AviatoGetPersonContactInfoConfig(PersonContact):
    """Pull a person's contact info"""
    operation: Literal["get_person_contact_info"] = Field("get_person_contact_info", json_schema_extra={"ui:hidden": True})


class AviatoGetPersonEmailConfig(PersonContact):
    """Get a person's email addresses."""
    operation: Literal["get_person_email"] = Field("get_person_email", json_schema_extra={"ui:hidden": True})


class AviatoGetPersonPhoneConfig(Person):
    """Get a person's phone numbers."""
    operation: Literal["get_person_phone"] = Field("get_person_phone", json_schema_extra={"ui:hidden": True})


class AviatoBulkEnrichPeopleConfig(BulkPerson):
    """Get enriched details on multiple people at once. Max 20 at a time"""
    operation: Literal["bulk_enrich_people"] = Field("bulk_enrich_people", json_schema_extra={"ui:hidden": True})


class AviatoBulkGetContactInfoConfig(BulkContact):
    """Get contact info (emails, phones) for multiple people at once. Max 100 at a time. Only charges credits for people with contact data found."""
    operation: Literal["bulk_get_contact_info"] = Field("bulk_get_contact_info", json_schema_extra={"ui:hidden": True})


class AviatoSearchPeopleConfig(Search):
    """Search for people using the Aviato DSL. See the [DSL documentation](/aviato-dsl/aviato-dsl-v-1)."""
    operation: Literal["search_people"] = Field("search_people", json_schema_extra={"ui:hidden": True})


class AviatoGetPersonCompanyInvestmentsConfig(PersonPage):
    """Get the companies that a person has invested in, along with investment info."""
    operation: Literal["get_person_company_investments"] = Field("get_person_company_investments", json_schema_extra={"ui:hidden": True})


class AviatoGetPersonFundInvestmentsConfig(PersonPage):
    """Get the funds that a person has invested in."""
    operation: Literal["get_person_fund_investments"] = Field("get_person_fund_investments", json_schema_extra={"ui:hidden": True})


class AviatoGetPersonFoundedCompaniesConfig(PersonPage):
    """Get the companies that a person has founded."""
    operation: Literal["get_person_founded_companies"] = Field("get_person_founded_companies", json_schema_extra={"ui:hidden": True})


class AviatoGenerateMarketMapConfig(GenerateMap):
    """Start generating a market map to find similar companies. You can supply either both name and website, or alternatively, an Aviato company ID."""
    operation: Literal["generate_market_map"] = Field("generate_market_map", json_schema_extra={"ui:hidden": True})


class AviatoGetMarketMapConfig(GetMap):
    """Fetch the data for the generated market map."""
    operation: Literal["get_market_map"] = Field("get_market_map", json_schema_extra={"ui:hidden": True})


AviatoConfig = Annotated[Union[
    AviatoGetBalanceConfig,
    AviatoEnrichCompanyConfig,
    AviatoGetCompanyFinancialsConfig,
    AviatoGetCompanySocialMetricsConfig,
    AviatoGetCompanyWebTrafficConfig,
    AviatoGetCompanyLegalConfig,
    AviatoBulkEnrichCompaniesConfig,
    AviatoGetCompanyAcquisitionsConfig,
    AviatoGetCompanyFoundersConfig,
    AviatoGetCompanyInvestmentsConfig,
    AviatoGetCompanyFundingRoundsConfig,
    AviatoGetCompanyEmployeesConfig,
    AviatoSearchCompaniesConfig,
    AviatoEnrichPersonConfig,
    AviatoGetPersonContactInfoConfig,
    AviatoGetPersonEmailConfig,
    AviatoGetPersonPhoneConfig,
    AviatoBulkEnrichPeopleConfig,
    AviatoBulkGetContactInfoConfig,
    AviatoSearchPeopleConfig,
    AviatoGetPersonCompanyInvestmentsConfig,
    AviatoGetPersonFundInvestmentsConfig,
    AviatoGetPersonFoundedCompaniesConfig,
    AviatoGenerateMarketMapConfig,
    AviatoGetMarketMapConfig
], Field(discriminator="operation")]


class AviatoFullConfig(NodeConfig[AviatoConfig, AviatoAPIKeyCredential]):
    pass


ROUTES = {
    "get_balance": ('GET', '/billing/balance'),
    "enrich_company": ('GET', '/company/enrich'),
    "get_company_financials": ('GET', '/company/financials'),
    "get_company_social_metrics": ('GET', '/company/social-metrics'),
    "get_company_web_traffic": ('GET', '/company/web-traffic'),
    "get_company_legal": ('GET', '/company/legal'),
    "bulk_enrich_companies": ('POST', '/company/bulk-enrich'),
    "get_company_acquisitions": ('GET', '/company/acquisitions'),
    "get_company_founders": ('GET', '/company/founders'),
    "get_company_investments": ('GET', '/company/investments'),
    "get_company_funding_rounds": ('GET', '/company/funding-rounds'),
    "get_company_employees": ('GET', '/company/employees'),
    "search_companies": ('POST', '/company/search'),
    "enrich_person": ('GET', '/person/enrich'),
    "get_person_contact_info": ('GET', '/person/contact-info'),
    "get_person_email": ('GET', '/person/email'),
    "get_person_phone": ('GET', '/person/phone'),
    "bulk_enrich_people": ('POST', '/person/bulk/enrich'),
    "bulk_get_contact_info": ('POST', '/person/bulk/contact-info'),
    "search_people": ('POST', '/person/search'),
    "get_person_company_investments": ('GET', '/person/investments/companies'),
    "get_person_fund_investments": ('GET', '/person/investments/funds'),
    "get_person_founded_companies": ('GET', '/person/founded-companies'),
    "generate_market_map": ('POST', '/marketmap/generate'),
    "get_market_map": ('GET', '/marketmap/get'),
}


class AviatoNode(WorkflowNode):
    integration_type = "automation-aviato"
    connection_evidence = ConnectionEvidence(operation="get_balance", noun="team credit balance", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return AviatoFullConfig

    async def execute(self, inputs):
        config = self.config
        if not config.credentials:
            raise ValueError("Connect an Aviato API Key")
        op = config.config
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude={"operation"}, exclude_none=True)
        if "lookup_value" in values:
            value = values.pop("lookup_value")
            selector = values.pop("lookup_by")
            values[selector] = value
        for native, wire in (("per_page", "perPage"), ("required_fields", "require"), ("email_type", "type"), ("company_id", "id"), ("map_id", "id")):
            if native in values:
                values[wire] = values.pop(native)
        # JSON query arrays use repeated keys (OpenAPI form/explode=true).
        params = [(key, str(item).lower() if isinstance(item, bool) else item)
                  for key, value in values.items()
                  for item in (value if isinstance(value, list) else [value])] if method == "GET" else None
        headers = {"Authorization": "Bearer " + config.credentials.api_key, "Accept": "application/json"}
        async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers,
                params=params, **({"json": values} if method == "POST" else {}))
        if response.status_code != 200:
            # Keep a provider rejection useful to the shared connect seam, but
            # never include a key echoed by a provider or proxy in an error.
            message = "Aviato request failed"
            try:
                payload = response.json()
                if isinstance(payload, dict) and isinstance(payload.get("message"), str):
                    message = payload["message"][:1000].replace(config.credentials.api_key, "[redacted]")
            except ValueError:
                pass
            raise ValueError(f"Aviato HTTP {response.status_code}: {message}")
        mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if mime != "application/json" or len(response.content) > 10_000_000:
            raise ValueError("Expected bounded JSON from Aviato")
        data = response.json()
        if not isinstance(data, (dict, list)) or isinstance(data, dict) and (data.get("error") or data.get("errors")):
            raise ValueError("Aviato returned an unexpected response or error envelope")
        if op.operation == "get_balance" and (not isinstance(data, dict) or type(data.get("balance")) not in (int, float)):
            raise ValueError("Aviato did not return a team credit balance")
        if op.operation == "generate_market_map" and (not isinstance(data, dict) or not isinstance(data.get("mapID"), str) or not data["mapID"]):
            raise ValueError("Aviato did not return a market map ID")
        return {"status": "success", "data": data}
