"""Enrich Layer v2: one authenticated GET per operation, with no automatic retries.

Contract: https://enrichlayer.com/docs/api/v2/openapi.json (1.0.0).
Enrichment and searches consume provider credits. Lists return a single page;
pass the documented cursor explicitly to continue. Provider URLs are data only.
The published v2/v3 contracts expose no record-writing operations.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from pydantic import field_validator
from utils.ssrf import guarded_async_client

API_BASE = "https://enrichlayer.com"
CREDENTIAL_TYPE = "enrich_layer_api_key"


class EnrichLayerAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Enrich Layer API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://enrichlayer.com/dashboard",
            "x-credential-instructions": "Open your Enrich Layer dashboard, copy your API key, and paste it here. NoClick sends it as a Bearer token. Connecting reads your credit balance for free; enrichment and search operations consume credits.",
        })
    credential_type: Literal["enrich_layer_api_key"] = Field("enrich_layer_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API key without the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class EnrichLayerGetPerson(_Input):
    """Cost: 1 credit / successful request. Get structured data of a Person Profile."""
    operation: Literal['get_person'] = Field('get_person', json_schema_extra={"ui:hidden": True})
    profile_url: str = Field(..., min_length=1, max_length=4096, description="The Profile URL from which you wish to extract.\nWe support both raw UTF-8 input and URL-encoded input. For example, `https://linkedin.com/in/rodríguez/` and `https://linkedin.com/in/rodr%C3%ADguez/` are both valid.\nWe don't support URLs with a hashed ID, e.g. `https://www.linkedin.com/in/ACwAAExzrQ0Bjqu...`\nInclude only one of: `profile_url`, `twitter_profile_url`, or `facebook_profile_url`.")
    twitter_profile_url: str | None = Field(None, min_length=1, max_length=4096, description='The Twitter/X Profile URL from which you wish to extract person profile\nURL should be in the format of `https://x.com/<public-identifier>`\nInclude only one of: `profile_url`, `twitter_profile_url`, or `facebook_profile_url`.')
    facebook_profile_url: str | None = Field(None, min_length=1, max_length=4096, description='The Facebook Profile URL from which you wish to extract person profile\nURL should be in the format of `https://facebook.com/<public-identifier>`\nInclude only one of: `profile_url`, `twitter_profile_url`, or `facebook_profile_url`.')
    extra: str | None = Field(None, min_length=1, max_length=4096, description='Enriches the Person Profile with extra details from external sources. Extra details include gender, birth date, industry and interests.\nThis parameter accepts the following values:\n- `exclude` (default value) - Does not provide extra data field.\n- `include` - Append extra data to the person profile object. Costs an extra `1` credit on top of the cost of the base endpoint (if data is available).')
    github_profile_id: str | None = Field(None, min_length=1, max_length=4096, description='Enriches the Person Profile with GitHub ID from external sources.\nThis parameter accepts the following values:\n- `exclude` (default value) - Does not provide GitHub ID data field.\n- `include` - Append GitHub ID data to the person profile object. Costs an extra `1` credit on top of the cost of the base endpoint (if data is available).')
    facebook_profile_id: str | None = Field(None, min_length=1, max_length=4096, description='Enriches the Person Profile with Facebook ID from external sources.\nThis parameter accepts the following values:\n- `exclude` (default value) - Does not provide Facebook ID data field.\n- `include` - Append Facebook ID data to the person profile object. Costs an extra `1` credit on top of the cost of the base endpoint (if data is available).')
    twitter_profile_id: str | None = Field(None, min_length=1, max_length=4096, description='Enriches the Person Profile with Twitter ID from external sources.\nThis parameter accepts the following values:\n- `exclude` (default value) - Does not provide Twitter ID data field.\n- `include` - Append Twitter ID data to the person profile object. Costs an extra `1` credit on top of the cost of the base endpoint (if data is available).')
    personal_contact_number: str | None = Field(None, min_length=1, max_length=4096, description='Enriches the Person Profile with personal numbers from external sources.\nThis parameter accepts the following values:\n- `exclude` (default value) - Does not provide personal numbers data field.\n- `include` - Append personal numbers data to the person profile object. Costs an extra `1` credit per personal number returned on top of the cost of the base endpoint (if data is available).')
    personal_email: str | None = Field(None, min_length=1, max_length=4096, description='Enriches the Person Profile with personal emails from external sources.\nThis parameter accepts the following values:\n- `exclude` (default value) - Does not provide personal emails data field.\n- `include` - Append personal emails data to the person profile object. Costs an extra `1` credit per email returned on top of the cost of the base endpoint (if data is available).')
    inferred_salary: str | None = Field(None, min_length=1, max_length=4096, description='Include inferred salary range from external sources.\nThis parameter accepts the following values:\n- `exclude` (default value) - Does not provide inferred salary data field.\n- `include` - Append inferred salary range data to the person profile object. Costs an extra `1` credit on top of the cost of the base endpoint (if data is available).')
    skills: str | None = Field(None, min_length=1, max_length=4096, description='Include skills data from external sources.\nSkills are no longer available as part of public data, but we will show skills for historic profiles, or where skills are inferred or sourced by other means. Expect limited coverage.\nThis parameter accepts the following values:\n- `exclude` (default value) - Does not provide skills data field.\n- `include` - Append skills data to the person profile object. No extra credit is charged for this parameter.')
    use_cache: str | None = Field(None, min_length=1, max_length=4096, description='`if-present` - Fetches profile from cache regardless of age of profile. If profile is not available in cache, API will attempt to source profile externally.\n`if-recent` (Default) - API will make a best effort to return a fresh profile no older than 29 days. Costs an extra `1` credit on top of the cost of the base endpoint.')
    fallback_to_cache: str | None = Field(None, min_length=1, max_length=4096, description='Tweaks the fallback behavior if an error arises from fetching a fresh profile.\nThis parameter accepts the following values:\n* `on-error` (default value) - Fallback to reading the profile from cache if an error arises.\n* `never` - Do not ever read profile from cache.')
    live_fetch: str | None = Field(None, min_length=1, max_length=4096, description='Tweak the behavior of the API to fetch the fresh profile.\nThis parameter accepts the following values:\n* `force` - Force the API to fetch the fresh profile. Costs an extra `9` credits on top of the cost of the base endpoint.\n* `default` (default value) - Do not force the API to fetch the fresh profile. Consider using `use_cache` instead.')

class EnrichLayerGetCompany(_Input):
    """Cost: 1 credit / successful request. Get structured data of a Company Profile."""
    operation: Literal['get_company'] = Field('get_company', json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, max_length=4096, description='URL Company Profile to crawl.')
    categories: str | None = Field(None, min_length=1, max_length=4096, description='Appends categories data of this company.\nDefault value is `"exclude"`. The other acceptable value is `"include"`, which will include these categories (if available) for `1` extra credit.')
    funding_data: str | None = Field(None, min_length=1, max_length=4096, description='Returns a list of funding rounds that this company has received.\nDefault value is `"exclude"`. The other acceptable value is `"include"`, which will include these categories (if available) for `1` extra credit.')
    exit_data: str | None = Field(None, min_length=1, max_length=4096, description='Returns a list of investment portfolio exits.\nDefault value is `"exclude"`. The other acceptable value is `"include"`, which will include these categories (if available) for `1` extra credit.')
    acquisitions: str | None = Field(None, min_length=1, max_length=4096, description='Provides further enriched data on acquisitions made by this company from external sources.\nDefault value is `"exclude"`. The other acceptable value is `"include"`, which will include these acquisition data (if available) for `1` extra credit.')
    extra: str | None = Field(None, min_length=1, max_length=4096, description='Enriches the Company Profile with extra details from external sources. Details include Crunchbase ranking, contact email, phone number, Facebook account, Twitter account, funding rounds and amount, IPO status, investor information, etc.\nDefault value is `"exclude"`. The other acceptable value is `"include"`, which will include these extra details (if available) for `1` extra credit.')
    use_cache: str | None = Field(None, min_length=1, max_length=4096, description='`if-present` - Fetches profile from cache regardless of age of profile. If profile is not available in cache, API will attempt to source profile externally.\n`if-recent` (Default) - API will make a best effort to return a fresh profile no older than 29 days. Costs an extra `1` credit on top of the cost of the base endpoint.')
    fallback_to_cache: str | None = Field(None, min_length=1, max_length=4096, description='Tweaks the fallback behavior if an error arises from fetching a fresh profile.\nThis parameter accepts the following values:\n* `on-error` (default value) - Fallback to reading the profile from cache if an error arises.\n* `never` - Do not ever read profile from cache.')
    live_fetch: str | None = Field(None, min_length=1, max_length=4096, description='Tweak the behavior of the API to fetch the fresh profile.\nThis parameter accepts the following values:\n* `force` - Force the API to fetch the fresh profile. Costs an extra `9` credits on top of the cost of the base endpoint.\n* `default` (default value) - Do not force the API to fetch the fresh profile. Consider using `use_cache` instead.')

class EnrichLayerGetSchool(_Input):
    """Cost: 1 credit / successful request. Get structured data of a School Profile."""
    operation: Literal['get_school'] = Field('get_school', json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, max_length=4096, description='URL of the School Profile to crawl.')
    use_cache: str | None = Field(None, min_length=1, max_length=4096, description='`if-present` The default behavior.Fetches profile from cache regardless of age of profile. If profile is not available in cache, API will attempt to source profile externally.\n`if-recent` API will make a best effort to return a fresh profile no older than 29 days.Costs an extra `1` credit on top of the cost of the base endpoint.')
    live_fetch: str | None = Field(None, min_length=1, max_length=4096, description='Tweak the behavior of the API to fetch the fresh profile.\nThis parameter accepts the following values:\n* `force` - Force the API to fetch the fresh profile. Costs an extra `9` credits on top of the cost of the base endpoint.\n* `default` (default value) - Do not force the API to fetch the fresh profile. Consider using `use_cache` instead.')

class EnrichLayerListEmployees(_Input):
    """Cost: 3 credits / employee returned. Get a list of employees of a Company."""
    operation: Literal['list_employees'] = Field('list_employees', json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, max_length=4096, description='URL of the Company Profile to target.')
    coy_name_match: str | None = Field(None, min_length=1, max_length=4096, description='Include profiles that match the company name. The Employee Listing Endpoint works by identifying individual profiles with work experience that provides an exact match to the Company Profile URL provided. Including this option also allows profiles with at least one work experience that exactly matches the specified company name to be included.\nThis parameter accepts the following values:\n* `include` (default value) - Include employees whose profiles match the company name.\n* `exclude` - Exclude employees by company name match.')
    use_cache: str | None = Field(None, min_length=1, max_length=4096, description='Define the freshness guarantee on the results returned.\nThis parameter accepts the following values:\n* `if-present` (default value) - Returns result as it is without any freshness guarantee\n* `if-recent` - Will make a best effort to return results of profiles no older than 29 days. Costs `1` extra credit per result on top of the base cost of the endpoint for users on the Growth or larger subscription. For all other users, it will cost `2` extra credits per result on top of the base cost of the endpoint.\n*Note: If `use_cache=if-recent`, `page_size` is limited to a value of `10` or smaller.*')
    country: str | None = Field(None, min_length=1, max_length=4096, description='Limit the result set to the country locality of the profile. For example, set the parameter of `country=us` if you only want profiles from the US. Or you can set the parameter to `country=us,sg` if you want employees from both the US and Singapore.\nThis parameter accepts a comma-separated case-insensitive values of [Alpha-2 ISO3166 country code](https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2).\nCosts an extra `3` credit per result returned.')
    enrich_profiles: str | None = Field(None, min_length=1, max_length=4096, description="Get the full profile of employees instead of only their profile urls.\nEach request respond with a streaming response of profiles.\nThe valid values are:\n* `skip` (default): lists employee's profile url\n* `enrich`: lists full profile of employees\nCalling this API endpoint with this parameter would add `1` credit per employee returned. Employee that is returned without enrichment won't incur any per employee cost.")
    boolean_role_search: str | None = Field(None, min_length=1, max_length=4096, description='Filter employees by their title using boolean search expression. This parameter will take precedence over `role_search` parameter if both are provided.\nThe default value of this parameter is `null`.\nThe value provided for this parameter must follow Boolean Search Syntax. It must not exceed 255 characters.\nThis parameter is **case-insensitive**; matching ignores capitalization in both the input and our data.\n(The base cost of calling this API endpoint with this parameter would be `10` credits. Each employee matched and returned would cost 3 extra credits.)')
    role_search: str | None = Field(None, min_length=1, max_length=4096, description="Use `boolean_role_search` instead.\nFilter employees by their title by matching the employee's title against a *regular expression*.\nThe default value of this parameter is `null`.\nThe accepted value for this parameter is a **case-insensitive** regular expression.\nThe provided regex patern must follow [Lucene Regular Expression Syntax](https://lucene.apache.org/core/9_0_0/core/org/apache/lucene/util/automaton/RegExp.html). The regular expression is anchored to the start and end of the provided pattern by default. You need to wrap your pattern accordingly if you want to perform a partial match.\n(The base cost of calling this API endpoint with this parameter would be `10` credits. Each employee matched and returned would cost 3 extra credits.)")
    page_size: str | None = Field(None, min_length=1, max_length=4096, description='Limit the maximum results returned per API call.\nThe default value of this parameter is `10`.\nAccepted values for this parameter is an integer ranging from `1` to `9999`.\nWhen `enrich_profiles=enrich`, this parameter accepts value ranging from `1` to `10` and the default value is `10`.')
    employment_status: str | None = Field(None, min_length=1, max_length=4096, description='Parameter to tell the API to return past or current employees.\nValid values are `current`, `past`, and `all`:\n* `current` (default) : lists current employees\n* `past` : lists past employees\n* `all` : lists current & past employees')
    sort_by: str | None = Field(None, min_length=1, max_length=4096, description='Sort employees by recency.\nValid values are:\n* `recently-joined` - Sort employees by their join date. The most recent employee is on the top of the list.\n* `recently-left` - Sort employees by their departure date. The most recent employee who had just left is on the top of this list.\n* `oldest` - Returns the oldest employees first. The oldest employee who had joined this company historically is on the top of this list.\n* `none` - The default value. Do not sort.\nIf this parameter is supplied with a value other than `none`, will add `50` credits to the base cost of the API endpoint regardless number of results returned. It will also add an additional cost of `10` credits per employee returned.')
    resolve_numeric_id: str | None = Field(None, min_length=1, max_length=4096, description='Enable support for Company Profile URLs with numerical IDs. \nThis parameter accepts the following values:\n- `false` (default value) - Will not resolve numerical IDs.\n- `true` - Enable support for Company Profile URLs with numerical IDs.  Costs an extra `2` credit on top of the base cost of the endpoint.')
    after: str | None = Field(None, min_length=1, max_length=4096, description='The cursor for fetching the next page of results.\nTake the value of the `after` query parameter from the `next_page` URL of the previous response.')

class EnrichLayerGetEmployeeCount(_Input):
    """Cost: 1 credit / successful request. Get the total number of employees of a company."""
    operation: Literal['get_employee_count'] = Field('get_employee_count', json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, max_length=4096, description='URL of the Company Profile to target.')
    coy_name_match: str | None = Field(None, min_length=1, max_length=4096, description='Include profiles that match the company name. The Employee Count Endpoint works by identifying individual profiles with work experience that provides an exact match to the Company Profile URL provided. Including this option also allows profiles with at least one work experience that exactly matches the specified company name to be included.\nThis parameter accepts the following values:\n* `include` (default value) - Include employees whose profiles match the company name.\n* `exclude` - Exclude employees by company name match.')
    at_date: str | None = Field(None, min_length=1, max_length=4096, description='Time travel back in time and fetch the employee count of a company at any particular date. This parameter takes an ISO8601 timestamp with the representation of "YYYY-MM-DD".\nCosts `1` extra credit on top of the base cost of the endpoint for users on the Growth or larger subscription. For all other users, it will cost `5` extra credits.')
    use_cache: str | None = Field(None, min_length=1, max_length=4096, description="`if-present`: The default behavior. Fetches data from cache regardless of age of profile.\n`if-recent`: API will make a best effort to return a fresh data no older than 29 days. Costs an extra 1 credit on top of the cost of the base endpoint.\n- Note: When `use_cache=if-recent`, the `estimated_employee_count` parameter must be included with a value of 'include'.")
    estimated_employee_count: str | None = Field(None, min_length=1, max_length=4096, description="Option to include a retrieved employee count value from the target company's profile.\nValid values are `include` and `exclude`:\n* `exclude` (default) : To exclude the retrieved employee count.\n* `include` : To include the retrieved employee count.\nCosts an extra `1` credit on top of the base cost of the endpoint.")
    employment_status: str | None = Field(None, min_length=1, max_length=4096, description='Parameter to tell the API to filter past or current employees.\nValid values are `current`, `past`, and `all`:\n* `current` (default) : count current employees\n* `past` : count past employees\n* `all` : count current & past employees')

class EnrichLayerLookupPerson(_Input):
    """Cost: 2 credits / successful request. Look up a person with a name and company information. Credits are charged by default even when no match is found; use `similarity_checks=skip` to avoid charges on null results."""
    operation: Literal['lookup_person'] = Field('lookup_person', json_schema_extra={"ui:hidden": True})
    company_domain: str = Field(..., min_length=1, max_length=4096, description='Company name or domain')
    first_name: str = Field(..., min_length=1, max_length=4096, description='First name of the user')
    similarity_checks: str | None = Field(None, min_length=1, max_length=4096, description='Controls whether the API endpoint performs similarity comparisons between the input parameters and the results or simply returns the closest match. For instance, if you are searching for a person named "Jane Smith", and the closest result we have is "Tom Garcia", our similarity checks will discard the obviously incorrect result and return `null` instead of a false positive.\nInclude similarity checks to eliminate false positives. However, be aware that this might yield fewer results as false positives are discarded. Credits will still be deducted even if we return `null`.\nYou can choose to skip similarity checks, in which case no credits will be charged if we return `null`.\nThis parameter accepts the following values:\n* `include` (default) - Perform similarity checks and discard false positives. Credits will be deducted even if we return null .\n* `skip` - Bypass similarity checks. No credits will be deducted if no results are returned.')
    enrich_profile: str | None = Field(None, min_length=1, max_length=4096, description='Enrich the result with a cached profile of the lookup result.\nThe valid values are:\n* `skip` (default): do not enrich the results with cached profile data\n* `enrich`: enriches the result with cached profile data\nCalling this API endpoint with this parameter would add 1 credit.\nIf you require fresh profile data, please chain this API call with the [People Profile Endpoint](/docs/api/v2/people-api/person-profile) with the `use_cache=if-recent` parameter.')
    location: str | None = Field(None, min_length=1, max_length=4096, description='The location of this user.\nName of country, city or state.')
    title: str | None = Field(None, min_length=1, max_length=4096, description='Title that user is holding at his/her current job')
    last_name: str | None = Field(None, min_length=1, max_length=4096, description='Last name of the user')

class EnrichLayerLookupCompany(_Input):
    """Cost: 2 credits / successful request. Resolve a Company Profile from company name, domain name, and location. Credits are charged on any 200 response, including when no matching company is found and the result contains a null value."""
    operation: Literal['lookup_company'] = Field('lookup_company', json_schema_extra={"ui:hidden": True})
    company_location: str | None = Field(None, min_length=1, max_length=4096, description='The location / region of company. ISO 3166-1 alpha-2 codes')
    company_domain: str = Field(..., min_length=1, max_length=4096, description='Company website or Company domain Requires either `company_domain` or `company_name`')
    company_name: str | None = Field(None, min_length=1, max_length=4096, description='Company Name Requires either `company_domain` or `company_name`')
    enrich_profile: str | None = Field(None, min_length=1, max_length=4096, description='Enrich the result with a cached profile of the lookup result.\nThe valid values are:\n* `skip` (default): do not enrich the results with cached profile data\n* `enrich`: enriches the result with cached profile data\nCalling this API endpoint with this parameter would add 1 credit.\nIf you require fresh profile data, please chain this API call with the [Company Profile Endpoint](/docs/api/v2/company-api/company-profile) with the `use_cache=if-recent` parameter.')

class EnrichLayerLookupRole(_Input):
    """Cost: 3 credits / successful request. Returns the profile of a person who most closely matches a specified role in a company. For instance, it can identify the "CTO" of "Apple". The endpoint returns a single result that represents the closest match. Credits are charged on any 200 response, including when no matching profile is found. For a detailed comparison, see the [Employee Search Endpoint](#company-api-employee-search-endpoint) or the [Person Search Endpoint](#search-api-person-search-endpoint)."""
    operation: Literal['lookup_role'] = Field('lookup_role', json_schema_extra={"ui:hidden": True})
    role: str = Field(..., min_length=1, max_length=4096, description='Role of the profile that you are looking up')
    company_name: str = Field(..., min_length=1, max_length=4096, description='Name of the company that you are searching for')
    enrich_profile: str | None = Field(None, min_length=1, max_length=4096, description='Enrich the result with a cached profile of the lookup result.\nThe valid values are:\n* `skip` (default): do not enrich the results with cached profile data\n* `enrich`: enriches the result with cached profile data\nCalling this API endpoint with this parameter would add 1 credit.\nIf you require fresh profile data, please chain this API call with the [Person Profile Endpoint](#people-api-person-profile-endpoint) with the `use_cache=if-recent` parameter.')

class EnrichLayerLookupCompanyId(_Input):
    """Cost: 0 credit / successful request. Look up the vanity ID of a company by its numeric ID."""
    operation: Literal['lookup_company_id'] = Field('lookup_company_id', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, max_length=4096, description="The company's internal, immutable numeric ID.")

class EnrichLayerSearchEmployees(_Input):
    """Cost: 10 credits / successful request. Search employees of a target company by their job title. This API endpoint is syntactic sugar for the `role_search` parameter under the [Employee Listing Endpoint](#company-api-employee-listing-endpoint). For a detailed comparison, see the [Role Lookup Endpoint](#people-api-role-lookup-endpoint) or the [Person Search Endpoint](#search-api-person-search-endpoint)."""
    operation: Literal['search_employees'] = Field('search_employees', json_schema_extra={"ui:hidden": True})
    company_profile_url: str = Field(..., min_length=1, max_length=4096, description='Profile URL of the target company.')
    keyword_boolean: str = Field(..., min_length=1, max_length=4096, description='Job title keyword to search for in Boolean Search Syntax format. This parameter will take precedence over `keyword_regex` parameter if both are provided.\nThe value provided for this parameter must not exceed 255 characters.\nThis parameter is **case-insensitive**; matching ignores capitalization in both the input and our data.')
    keyword_regex: str | None = Field(None, min_length=1, max_length=4096, description='Use `keyword_boolean` instead.\nJob title keyword to search for in regular expression format.\nThe accepted value for this parameter is a **case-insensitive** regular expression.')
    page_size: str | None = Field(None, min_length=1, max_length=4096, description='Tune the maximum results returned per API call. The default value of this parameter is `10`. Accepted values for this parameter is an integer ranging from `1` to `9999`. When `enrich_profiles=enrich`, this parameter accepts value ranging from `1` to `10` and the default value is `10`.')
    country: str | None = Field(None, min_length=1, max_length=4096, description='Limit the result set to the country locality of the profile. For example, set the parameter of `country=us` if you only want profiles from the US.\nThis parameter accepts a case-insensitive [Alpha-2 ISO3166 country code](https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2).\nCosts an extra `3` credit per result returned.')
    enrich_profiles: str | None = Field(None, min_length=1, max_length=4096, description="Get the full profile of employees instead of only their profile urls.\nEach request respond with a streaming response of profiles.\nThe valid values are:\n* `skip` (default): lists employee's profile url\n* `enrich`: lists full profile of employees\nCalling this API endpoint with this parameter would add `1` credit per employee returned.")
    resolve_numeric_id: str | None = Field(None, min_length=1, max_length=4096, description='Enable support for Company Profile URLs with numerical IDs.\nThis parameter accepts the following values:\n- `false` (default value) - Will not resolve numerical IDs.\n- `true` - Enable support for Company Profile URLs with numerical IDs.  Costs an extra `2` credit on top of the base cost of the endpoint.')

class EnrichLayerLookupEmail(_Input):
    """Cost: 3 credits / successful request. Resolve a person profile from an email address. Works with both personal and work email addresses. Credits are charged by default (`lookup_depth=deep`) even when no match is found; use `lookup_depth=superficial` to avoid charges on null results."""
    operation: Literal['lookup_email'] = Field('lookup_email', json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1, max_length=4096, description='Email address of the user you want to look up.')
    lookup_depth: str | None = Field(None, min_length=1, max_length=4096, description='This parameter describes the depth options for our API lookup function. This endpoint can execute either a superficial or a deep lookup.\nA **superficial lookup** involves comparing the provided email with entries in our database. This approach tends to yield fewer results and is typically less effective for work-related email addresses. However, it does not consume any credits if no results are returned.\nOn the other hand, a **deep lookup** extends beyond our database to utilize advanced heuristics and identify the individual associated with a given email. This method is particularly recommended for work emails.\nPlease note the following valid values for the depth of the lookup:\n* `superficial`: No credits are consumed if no results are found.\n* `deep` (default): Credits are used regardless of whether any results are returned.')
    enrich_profile: str | None = Field(None, min_length=1, max_length=4096, description='Enrich the result with a cached profile (if any).\nValid values are:\n* `skip` (default): do not enrich the results with cached profile data.\n* `enrich`: enriches the result with cached profile data. \nCalling this API endpoint with this parameter would add `1` additional credit.\nIf you require fresh profile data, please chain this API call with the `linkedin_profile_url` result with the [Person Profile Endpoint](#people-api-person-profile-endpoint) with the `use_cache=if-recent` parameter.')

class EnrichLayerLookupPhone(_Input):
    """Cost: 3 credits / successful request. No credits are charged when no social media profiles are found. Find social media profiles from a contact phone number."""
    operation: Literal['lookup_phone'] = Field('lookup_phone', json_schema_extra={"ui:hidden": True})
    phone_number: str = Field(..., min_length=1, max_length=4096, description='[E.164 formatted](/docs/guides/e164-phone-format) phone number of the person you want to identify social media profiles of.')

class EnrichLayerGetJob(_Input):
    """Cost: 2 credits / successful request. Get structured data of a Job Profile."""
    operation: Literal['get_job'] = Field('get_job', json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, max_length=4096, description='URL of the a Job Profile to target.\nThe [Job Search](/docs/api/v2/jobs-api/job-search) endpoint can be used to retrieve a job URL.')

class EnrichLayerSearchJobs(_Input):
    """Cost: 2 credits / successful request. List jobs posted by a company."""
    operation: Literal['search_jobs'] = Field('search_jobs', json_schema_extra={"ui:hidden": True})
    job_type: str | None = Field(None, min_length=1, max_length=4096, description='The nature of the job. It accepts the following 7 case-insensitive values only:\n- `full-time`\n- `part-time`\n- `contract`\n- `internship`\n- `temporary`\n- `volunteer`\n- `anything` (default)')
    experience_level: str | None = Field(None, min_length=1, max_length=4096, description='The experience level needed for the job. It accepts the following 6 case-insensitive values only:\n- `internship`\n- `entry_level`\n- `associate`\n- `mid_senior_level`\n- `director`\n- `anything` (default)')
    when: str | None = Field(None, min_length=1, max_length=4096, description='The time when the job is posted, It accepts the following case-insensitive values only:\n- `yesterday`\n- `past-week`\n- `past-month`\n- `anytime` (default)')
    flexibility: str | None = Field(None, min_length=1, max_length=4096, description='The flexibility of the job. It accepts the following 3 case insensitive values only:\n- `remote`\n- `on-site`\n- `hybrid`\n- `anything` (default)')
    geo_id: str | None = Field(None, min_length=1, max_length=4096, description='The `geo_id` of the location to search for. For example, `92000000` is the `geo_id` of world wide.')
    keyword: str | None = Field(None, min_length=1, max_length=4096, description='The keyword to search for.')
    search_id: str | None = Field(None, min_length=1, max_length=4096, description='The `search_id` of the company. You can get the `search_id` of a company via [Company Profile API](#company-api-company-profile-endpoint).')
    pagination: str | None = Field(None, min_length=1, max_length=4096, description='The token for fetching the next page of results.\nTake the value of the `pagination` query parameter from the `next_page_api_url` of the previous response.')

class EnrichLayerGetJobCount(_Input):
    """Cost: 2 credits / successful request. Count the number of jobs posted by a company."""
    operation: Literal['get_job_count'] = Field('get_job_count', json_schema_extra={"ui:hidden": True})
    job_type: str | None = Field(None, min_length=1, max_length=4096, description='The nature of the job. It accepts the following 7 case-insensitive values only:\n- `full-time`\n- `part-time`\n- `contract`\n- `internship`\n- `temporary`\n- `volunteer`\n- `anything` (default)')
    experience_level: str | None = Field(None, min_length=1, max_length=4096, description='The experience level needed for the job. It accepts the following 6 case-insensitive values only:\n- `internship`\n- `entry_level`\n- `associate`\n- `mid_senior_level`\n- `director`\n- `anything` (default)')
    when: str | None = Field(None, min_length=1, max_length=4096, description='The time when the job is posted, It accepts the following case-insensitive values only:\n- `yesterday`\n- `past-week`\n- `past-month`\n- `anytime` (default)')
    flexibility: str | None = Field(None, min_length=1, max_length=4096, description='The flexibility of the job. It accepts the following 3 case insensitive values only:\n- `remote`\n- `on-site`\n- `hybrid`\n- `anything` (default)')
    geo_id: str | None = Field(None, min_length=1, max_length=4096, description='The `geo_id` of the location to search for. For example, `92000000` is the `geo_id` of world wide.')
    keyword: str | None = Field(None, min_length=1, max_length=4096, description='The keyword to search for.')
    search_id: str | None = Field(None, min_length=1, max_length=4096, description='The `search_id` of the company. You can get the `search_id` of a company via [Company Profile API](#company-api-company-profile-endpoint).')

class EnrichLayerSearchCompanies(_Input):
    """Cost: 3 credits / Company URL. Search for companies that meet a set of criteria within our exhaustive dataset of company profiles."""
    operation: Literal['search_companies'] = Field('search_companies', json_schema_extra={"ui:hidden": True})
    country: str | None = Field(None, min_length=1, max_length=255, description='Filter companies with an office based in this country. This parameter accepts a case-insensitive [Alpha-2 ISO3166 country code](https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2).')
    region: str | None = Field(None, min_length=1, max_length=255, description='Filter companies with an office based in this region. A “region” in this context means “state,” “province,” or similar political division, depending on what country you’re querying.')
    city: str | None = Field(None, min_length=1, max_length=255, description='Filter companies based in cities matching the provided search expression.')
    name: str | None = Field(None, min_length=1, max_length=255, description='Filter companies with a name matching the provided search expression.')
    industry: str | None = Field(None, min_length=1, max_length=255, description="Filter companies belonging to an `industry` that matches the provided search expression. The `industry` attribute, found in a Company profile, describes the primary industry in which the company operates. The value of this attribute is an enumerator. [See the full list of possible values for this attribute](/docs/guides/industry-values).\nWe also infer a company's industry from various attributes. For example, the primary industry for `https://www.linkedin.com/company/apple` may be `Computers and Electronics Manufacturing`, but we may also classify it under `Software Development`.\nIf you want to filter by the primary industry only, please refer to the `primary_industry` parameter.")
    employee_count_max: str | None = Field(None, min_length=1, max_length=255, description='Filter companies with **at most** this many employees.')
    employee_count_min: str | None = Field(None, min_length=1, max_length=255, description='Filter companies with **at least** this many employees.')
    domain_name: str | None = Field(None, min_length=1, max_length=255, description='Filter companies with a domain name matching the provided search expression.')
    page_size: str | None = Field(None, min_length=1, max_length=255, description='Tune the maximum results returned per API call.\nThe default value of this parameter is 100.\nAccepted values for this parameter is an integer ranging from 1 to 100.\nWhen `enrich_profiles=enrich`, this parameter accepts value ranging from `1` to `10`.')
    enrich_profiles: str | None = Field(None, min_length=1, max_length=255, description="Get the company's complete profile data rather than just the URLs to their profiles.\nEach request respond with a streaming response of profiles.\nThe valid values are:\n- skip (default): lists company's profile url\n- enrich: include company's profile data in the list\nCalling this API endpoint with this parameter would add 1 credit per enriched result returned.")
    use_cache: str | None = Field(None, min_length=1, max_length=255, description='Define the freshness guarantee on the results returned.\nThis parameter accepts the following values: if-present (default value) - Returns result as it is without any freshness guarantee if-recent - Will make a best effort to return results of profiles no older than 29 days. Costs 1 extra credit per result on top of the base cost of the endpoint for users on the Growth or larger subscription. For all other users, it will cost 2 extra credits per result on top of the base cost of the endpoint.\nNote: If use_cache=if-recent, page_size is limited to a value of 10 or smaller.')
    next_token: str | None = Field(None, min_length=1, max_length=255, description='The token for fetching the next page of results.\nTake the value of the `next_token` query parameter from the `next_page` URL of the previous response.\nWhen this parameter is provided, the search query is restored from the token. Filter parameters are not applied to the search, but they must still be syntactically valid, otherwise the request fails with a 400; only `page_size`, `enrich_profiles` and `use_cache` are honored.')

class EnrichLayerSearchPeople(_Input):
    """Cost: 3 credits / Profile URL. Search for people who meet a set of criteria within our exhaustive dataset of people profiles."""
    operation: Literal['search_people'] = Field('search_people', json_schema_extra={"ui:hidden": True})
    country: str | None = Field(None, min_length=1, max_length=255, description='Filter people located in this country. This parameter accepts a case-insensitive [Alpha-2 ISO3166 country code](https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2).')
    first_name: str | None = Field(None, min_length=1, max_length=255, description='Filter people whose first names match the provided search expression.')
    last_name: str | None = Field(None, min_length=1, max_length=255, description='Filter people whose last names match the provided search expression.')
    current_role_title: str | None = Field(None, min_length=1, max_length=255, description="Filter people who are **currently** working as a role whose title matches the provided search expression. You'll be looking for profiles that show a person's current job. However, keep in mind that some of these profiles may not be up-to-date, which means you might sometimes see a person's old job instead of their current job.")
    current_company_profile_url: str | None = Field(None, min_length=1, max_length=255, description='Filter people who are **currently** working at a company represented by this Company Profile URL.\nDefault value of this parameter is `null`.')
    current_company_name: str | None = Field(None, min_length=1, max_length=255, description='Filter people who are **currently** working at a company whose name matches the provided search expression.')
    region: str | None = Field(None, min_length=1, max_length=255, description='Filter people located in a region matching the provided search expression. A “region” in this context means “state,” “province,” or similar political division, depending on what country you’re querying.')
    city: str | None = Field(None, min_length=1, max_length=255, description='Filter people located in a city matching the provided search expression.')
    skills: str | None = Field(None, min_length=1, max_length=255, description='Filter people whose skill fields match the provided search expression.')
    page_size: str | None = Field(None, min_length=1, max_length=255, description='Tune the maximum results returned per API call.\nThe default value of this parameter is `100`.\nAccepted values for this parameter is an integer ranging from `1` to `100`.\nWhen `enrich_profiles=enrich`, this parameter accepts value ranging from `1` to `10`.')
    enrich_profiles: str | None = Field(None, min_length=1, max_length=255, description="Get the person's complete profile data rather than just the URLs to their profiles.\nEach request respond with a streaming response of profiles.\nThe valid values are:\n* `skip` (default): lists person's profile url only\n* `enrich`: include person's profile data in the list\nCalling this API endpoint with this parameter would add `1` credit per enriched result returned. A profile returned without enrichment will not incur any per-profile charges.")
    use_cache: str | None = Field(None, min_length=1, max_length=255, description='Define the freshness guarantee on the results returned.\nThis parameter accepts the following values: if-present (default value) - Returns result as it is without any freshness guarantee if-recent - Will make a best effort to return results of profiles no older than 29 days. Costs 1 extra credit per result on top of the base cost of the endpoint for users on the Growth or larger subscription. For all other users, it will cost 2 extra credits per result on top of the base cost of the endpoint.\nNote: If use_cache=if-recent, page_size is limited to a value of 10 or smaller.')
    next_token: str | None = Field(None, min_length=1, max_length=255, description='The token for fetching the next page of results.\nTake the value of the `next_token` query parameter from the `next_page` URL of the previous response.\nWhen this parameter is provided, the search query is restored from the token. Filter parameters are not applied to the search, but they must still be syntactically valid, otherwise the request fails with a 400; only `page_size`, `enrich_profiles` and `use_cache` are honored.')

class EnrichLayerGetCreditBalance(_Input):
    """Cost: 0 credit / successful request. Get your current credit balance."""
    operation: Literal['get_credit_balance'] = Field('get_credit_balance', json_schema_extra={"ui:hidden": True})

class EnrichLayerCheckDisposableEmail(_Input):
    """Cost: 0 credit / successful request. Check whether an email address belongs to a disposable email service."""
    operation: Literal['check_disposable_email'] = Field('check_disposable_email', json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1, max_length=4096, description='Email address to check')

class EnrichLayerGetPersonalEmail(_Input):
    """Cost: 1 credit / email returned. Find personal email addresses associated with a given social media profile."""
    operation: Literal['get_personal_email'] = Field('get_personal_email', json_schema_extra={"ui:hidden": True})
    profile_url: str = Field(..., min_length=1, max_length=4096, description='The Profile URL from which you wish to extract personal email addresses. Include only one of: `profile_url`, `twitter_profile_url`, or `facebook_profile_url`.')
    twitter_profile_url: str | None = Field(None, min_length=1, max_length=4096, description='The Twitter/X Profile URL from which you wish to extract personal email addresses. Include only one of: `profile_url`, `twitter_profile_url`, or `facebook_profile_url`.')
    facebook_profile_url: str | None = Field(None, min_length=1, max_length=4096, description='The Facebook Profile URL from which you wish to extract personal email addresses. Include only one of: `profile_url`, `twitter_profile_url`, or `facebook_profile_url`.')
    email_validation: str | None = Field(None, min_length=1, max_length=4096, description='How to validate each email.\nTakes the following values:\n * `none` (default) - Do not perform email validation.\n * `fast` - Perform fast email validation (does not cost extra credit).\n * `precise` - Perform deliverability validation (costs 1 extra credit per email found).\n\nFor backward-compatibility these are also accepted:\n * `include` - Equivalent to `precise`\n * `exclude` - Equivalent to `none`')
    page_size: str | None = Field(None, min_length=1, max_length=4096, description="This controls the maximum number of emails returned per API call. It's useful for limiting credit consumption as the number of emails per identity can vary. The default value is `0`, meaning there's no limit to the number of returned results.")


# Enrich Layer's own MCP server: agents get its tools through a person's Enrich Layer sign-in.
EnrichLayerMcpCredential = mcp_credential("enrich_layer", "https://mcp.enrichlayer.com/mcp", app="Enrich Layer")
EnrichLayerCredential = Union[EnrichLayerAPIKeyCredential, EnrichLayerMcpCredential]


EnrichLayerOperation = Annotated[Union[
    EnrichLayerGetPerson,
    EnrichLayerGetCompany,
    EnrichLayerGetSchool,
    EnrichLayerListEmployees,
    EnrichLayerGetEmployeeCount,
    EnrichLayerLookupPerson,
    EnrichLayerLookupCompany,
    EnrichLayerLookupRole,
    EnrichLayerLookupCompanyId,
    EnrichLayerSearchEmployees,
    EnrichLayerLookupEmail,
    EnrichLayerLookupPhone,
    EnrichLayerGetJob,
    EnrichLayerSearchJobs,
    EnrichLayerGetJobCount,
    EnrichLayerSearchCompanies,
    EnrichLayerSearchPeople,
    EnrichLayerGetCreditBalance,
    EnrichLayerCheckDisposableEmail,
    EnrichLayerGetPersonalEmail
], Field(discriminator="operation")]


class EnrichLayerConfig(NodeConfig[EnrichLayerOperation, EnrichLayerCredential]):
    pass


ROUTES = {'get_person': '/api/v2/profile', 'get_company': '/api/v2/company', 'get_school': '/api/v2/school', 'list_employees': '/api/v2/company/employees/', 'get_employee_count': '/api/v2/company/employees/count', 'lookup_person': '/api/v2/profile/resolve', 'lookup_company': '/api/v2/company/resolve', 'lookup_role': '/api/v2/find/company/role/', 'lookup_company_id': '/api/v2/company/resolve-id', 'search_employees': '/api/v2/company/employee/search/', 'lookup_email': '/api/v2/profile/resolve/email', 'lookup_phone': '/api/v2/resolve/phone', 'get_job': '/api/v2/job', 'search_jobs': '/api/v2/company/job', 'get_job_count': '/api/v2/company/job/count', 'search_companies': '/api/v2/search/company', 'search_people': '/api/v2/search/person', 'get_credit_balance': '/api/v2/credit-balance', 'check_disposable_email': '/api/v2/disposable-email', 'get_personal_email': '/api/v2/contact-api/personal-email'}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, dict):
        return {_redact(k, key): _redact(v, key) for k, v in value.items()}
    return value


class EnrichLayerNode(WorkflowNode):
    integration_type = "automation-enrich-layer"
    credential_provider_labels = {"enrich_layer": "Enrich Layer Account"}
    connection_evidence = ConnectionEvidence(operation="get_credit_balance", noun="account credit balance",
        label_keys=("name",), proves="account")
    edit_examples = ["Enrich a contact from a person profile", "Find employees at a company", "Alert me when Enrich Layer credits are low"]

    @classmethod
    def get_config_model(cls):
        return EnrichLayerConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect an Enrich Layer API key")
        op = self.config.config
        key = self.config.credentials.api_key
        params = op.model_dump(exclude={"operation"}, exclude_none=True)
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request("GET", API_BASE + ROUTES[op.operation],
                    headers={"Authorization": "Bearer " + key, "Accept": "application/json"}, params=params)
        except httpx.RequestError:
            return {"status": "error", "error": "Enrich Layer request could not be completed; check before retrying a credit-consuming request."}
        if len(response.content) > 10_000_000 or "json" not in response.headers.get("content-type", "").lower():
            return {"status": "error", "status_code": response.status_code, "error": "Expected a bounded JSON response from Enrich Layer"}
        try:
            payload = _redact(response.json(), key)
        except ValueError:
            return {"status": "error", "status_code": response.status_code, "error": "Enrich Layer returned invalid JSON"}
        if response.status_code != 200 or (isinstance(payload, dict) and ("error" in payload or "error_code" in payload)):
            result = {"status": "error", "status_code": response.status_code, "error": payload}
            if response.status_code == 429 and response.headers.get("retry-after"):
                result["retry_after"] = response.headers["retry-after"]
            return result
        if not isinstance(payload, dict):
            return {"status": "error", "error": "Expected an Enrich Layer response object"}
        result = {"status": "success", "action": op.operation, "data": payload, "status_code": 200}
        if op.operation == "get_credit_balance":
            balance = payload.get("credit_balance")
            if type(balance) is not int or balance < 0:
                return {"status": "error", "error": "Enrich Layer credit balance response was incomplete"}
            result["name"] = str(balance) + " credits remaining"
            result["items"] = [{"name": result["name"]}]
        return result
