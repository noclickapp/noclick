"""Redirect Pizza REST API v1.1.0: one documented endpoint per operation."""
from __future__ import annotations
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

class RedirectPizzaCredential(BaseModel):
    model_config = ConfigDict(title="Redirect Pizza API Token", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://redirect.pizza/dashboard/api",
            "x-credential-instructions": "In Redirect Pizza, open More → API and create an API token with access to the operations you need. Paste the token here. NoClick uses Bearer authentication; listing redirects checks the connection."})
    credential_type: Literal["redirect_pizza_api_token"] = Field("redirect_pizza_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="API token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if any(c.isspace() for c in value):
            raise ValueError("Paste only the API token, without the Bearer prefix")
        return value

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class ListRedirects(_Input):
    operation: Literal['list_redirects'] = Field('list_redirects', title='List all redirects', json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, ge=1, description='The page number to return.')
    per_page: int | None = Field(None, ge=1, le=100, description='The number of redirects returned. Max 100')
    query: str | None = Field(None, description='Search and filter query. Free text matches sources and destinations. Filters use `key:value` tokens, e.g. `status:paused`, `tag:marketing`, `type:permanent`, `type:temporary`, `type:permanent:308`, `created_before:2026-01-01`, `created_after:2026-01-01`, `source:old.example.com`, `destination:example.org`, `redirect:123`.')

class CreateRedirect(_Input):
    operation: Literal['create_redirect'] = Field('create_redirect', title='Create a redirect', json_schema_extra={"ui:hidden": True})
    sources: list[str] = Field(..., min_length=1, description="URLs to be redirected ('from' URLs)")
    destination: str = Field(..., min_length=1, description='Destination URL or conditional destinations. Either a string (e.g. \'https://example.org\') or an array of expression/url objects. Example:\n[\n  {"expression": "country==\'US\'", "url": "https://us.example.org"},\n  {"expression": "country==\'NL\'", "url": "https://nl.example.org"}\n]')
    redirect_type: Literal['permanent', 'temporary', 'permanent:308', 'temporary:307', 'frame', 'meta-refresh'] = Field(..., min_length=1, description='Type of redirect')
    uri_forwarding: bool | None = Field(None, description='Whether the path should be forwarded')
    keep_query_string: bool | None = Field(None, description='Whether the query string should be forwarded')
    tracking: bool | None = Field(None, description='Whether analytics information should be collected')
    tags: list[str] | None = Field(None, description='Tags categorising this redirect. May also be a comma-separated string.')
    notes: str | None = Field(None, description='Notes about the redirect')
    merge: bool | None = Field(None, description='Whether to merge the new redirect with an existing redirect if they have the same destination')
    upsert: bool | None = Field(None, description='When enabled, if any of the provided source URLs already exist on a redirect, that redirect will be updated instead of creating a new one. Existing sources on that redirect are kept and only new sources are added; omitted sources are not deleted. If the provided sources match more than one existing redirect, the request will fail with an error. Useful for automated syncing without needing to track redirect IDs.')

class GetRedirect(_Input):
    operation: Literal['get_redirect'] = Field('get_redirect', title='Retrieve a redirect', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description='ID of the redirect to retrieve')

class UpdateRedirect(_Input):
    operation: Literal['update_redirect'] = Field('update_redirect', title='Update a redirect', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description='ID of the redirect to retrieve')
    sources: list[str] = Field(..., min_length=1, description="URLs to be redirected, i.e. the 'from' URLs")
    destination: str = Field(..., min_length=1, description='Destination URL or conditional destinations. Either a string (e.g. \'https://example.org\') or an array of expression/url objects. Example:\n[\n  {"expression": "country==\'US\'", "url": "https://us.example.org"},\n  {"expression": "country==\'NL\'", "url": "https://nl.example.org"}\n]')
    redirect_type: Literal['permanent', 'temporary', 'permanent:308', 'temporary:307', 'frame', 'meta-refresh'] = Field(..., min_length=1, description='The type of redirect to use')
    uri_forwarding: bool | None = Field(None, description='Whether the path should be forwarded to the destination')
    keep_query_string: bool | None = Field(None, description='Whether the query string should be forwarded to the destination URL')
    tracking: bool | None = Field(None, description='Whether analytical information should be collected')
    tags: list[str] | None = Field(None, description='Used to categorize redirects. May be an array or a comma-separated string')
    notes: str | None = Field(None, description='Notes about the redirect')

class DeleteRedirect(_Input):
    operation: Literal['delete_redirect'] = Field('delete_redirect', title='Delete redirect', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description='ID of the redirect to retrieve')

class PauseRedirect(_Input):
    operation: Literal['pause_redirect'] = Field('pause_redirect', title='Pause a redirect', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description='ID of the redirect to pause')

class ResumeRedirect(_Input):
    operation: Literal['resume_redirect'] = Field('resume_redirect', title='Resume a redirect', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description='ID of the redirect to resume')

class PauseSource(_Input):
    operation: Literal['pause_source'] = Field('pause_source', title='Pause a source URL', json_schema_extra={"ui:hidden": True})
    redirect_id: int = Field(..., ge=1, description='ID of the redirect')
    source_id: int = Field(..., ge=1, description='ID of the source to pause')

class ResumeSource(_Input):
    operation: Literal['resume_source'] = Field('resume_source', title='Resume a source URL', json_schema_extra={"ui:hidden": True})
    redirect_id: int = Field(..., ge=1, description='ID of the redirect')
    source_id: int = Field(..., ge=1, description='ID of the source to resume')

class ListEmailForwards(_Input):
    operation: Literal['list_email_forwards'] = Field('list_email_forwards', title='List all email forwards', json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, ge=1, description='The page number to return.')
    per_page: int | None = Field(None, ge=1, le=100, description='The number of email forwards returned. Max 100')

class CreateEmailForward(_Input):
    operation: Literal['create_email_forward'] = Field('create_email_forward', title='Create an email forward', json_schema_extra={"ui:hidden": True})
    alias: str = Field(..., min_length=1, description="The alias part (before the '@'). Use '*' to create a catch-all email forward.")
    domain: str = Field(..., min_length=1, description='Domain of the email forward. Must be a domain you own and can manage DNS for.')
    destination: str = Field(..., min_length=1, description='Destination email address where the email will be forwarded to.')

class GetEmailForward(_Input):
    operation: Literal['get_email_forward'] = Field('get_email_forward', title='Retrieve an email forward', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description='ID of the email forward to retrieve')

class UpdateEmailForward(_Input):
    operation: Literal['update_email_forward'] = Field('update_email_forward', title='Update an email forward', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description='ID of the email forward to retrieve')
    destination: str = Field(..., min_length=1, description='Destination email address where the email will be forwarded to.')

class DeleteEmailForward(_Input):
    operation: Literal['delete_email_forward'] = Field('delete_email_forward', title='Delete an email forward', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description='ID of the email forward to retrieve')

class ListEmailForwardLogs(_Input):
    operation: Literal['list_email_forward_logs'] = Field('list_email_forward_logs', title='List email forward logs', json_schema_extra={"ui:hidden": True})
    start: str | None = Field(None, description='Start date for filtering logs. Format: `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`.')
    end: str | None = Field(None, description='End date for filtering logs. Format: `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`.')
    query: str | None = Field(None, description='Query string to filter logs. For example: `forward:sales@example.com domain:example.com`.')
    cursor: str | None = Field(None, description='Cursor string for pagination.')
    per_page: int | None = Field(None, ge=1, le=100, description='Number of logs to return. Max is 1,000.')

class GetTotalHits(_Input):
    operation: Literal['get_total_hits'] = Field('get_total_hits', title='Get total hits', json_schema_extra={"ui:hidden": True})
    start: str | None = Field(None, description='Start date for filtering hits. Format: `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`. Must be before `end`.')
    end: str | None = Field(None, description='End date for filtering hits. Format: `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`. Must be after `start`.')
    query: str | None = Field(None, description='Optional query filter, e.g., `redirect:1234567890` to filter by redirect ID.')

class GetTimeSeries(_Input):
    operation: Literal['get_time_series'] = Field('get_time_series', title='Get time series data', json_schema_extra={"ui:hidden": True})
    start: str | None = Field(None, description='Start date for the graph. Format: `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`. Must be before `end`.')
    end: str | None = Field(None, description='End date for the graph. Format: `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`. Must be after `start`.')
    query: str | None = Field(None, description='Optional query filter, e.g., `redirect:1234567890` to filter by redirect ID.')

class GetDimensions(_Input):
    operation: Literal['get_dimensions'] = Field('get_dimensions', title='Get dimensions data', json_schema_extra={"ui:hidden": True})
    dimension: Literal["redirects", "sources", "countries", "referers", "referer-hosts", "traffic-types", "schemes", "device-types", "full-urls"] = Field(..., description='The dimension to retrieve. Must be one of: `redirects`, `sources`, `countries`, `referers`, `referer-hosts`, `traffic-types`, `schemes`, `device-types`, `full-urls`.')
    start: str | None = Field(None, description='Start date for filtering. Format: `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`. Must be before `end`.')
    end: str | None = Field(None, description='End date for filtering. Format: `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`. Must be after `start`.')
    query: str | None = Field(None, description='Optional query filter, e.g., `redirect:1234567890` to filter by redirect ID.')
    page: int | None = Field(None, ge=1, description='The page number to return.')
    per_page: int | None = Field(None, ge=1, le=100, description='The number of results returned. Default 10. Max 100')

class ListRawHits(_Input):
    operation: Literal['list_raw_hits'] = Field('list_raw_hits', title='List all raw hits', json_schema_extra={"ui:hidden": True})
    start: str | None = Field(None, description='Start date for filtering hits. Format: `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`. Must be before `end`.')
    end: str | None = Field(None, description='End date for filtering hits. Format: `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS`. Must be after `start`.')
    query: str | None = Field(None, description='Query string to filter hits. For example: `redirect:1234567890`.')
    cursor: str | None = Field(None, description='Cursor string for pagination (base64-encoded).')
    per_page: int | None = Field(None, ge=1, le=20000, description='Number of hits to return. Max is 20,000.')

class ListDomains(_Input):
    operation: Literal['list_domains'] = Field('list_domains', title='List all domains', json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, ge=1, description='The page number to return.')
    per_page: int | None = Field(None, ge=1, le=100, description='The number of domains returned. Max 100')
    query: str | None = Field(None, description='Search and filter query. Free text matches FQDNs. Filters use `key:value` tokens, e.g. `status:verified`, `status:unverified`, `tag:marketing`.')

class GetDomain(_Input):
    operation: Literal['get_domain'] = Field('get_domain', title='Retrieve a domain', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description='ID of the domain to retrieve')

class DeleteDomain(_Input):
    operation: Literal['delete_domain'] = Field('delete_domain', title='Delete a domain', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description='ID of the domain to retrieve')

class CheckDns(_Input):
    operation: Literal['check_dns'] = Field('check_dns', title='Check DNS Propagation', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1, description='ID of the domain to check')

class GetTeam(_Input):
    operation: Literal['get_team'] = Field('get_team', title='Get team details', json_schema_extra={"ui:hidden": True})

class ListTeamMembers(_Input):
    operation: Literal['list_team_members'] = Field('list_team_members', title='List team members', json_schema_extra={"ui:hidden": True})
    page: int | None = Field(None, ge=1, description='The page number to return.')
    per_page: int | None = Field(None, ge=1, le=100, description='The number of users returned. Max 100')

Operation = Annotated[Union[ListRedirects, CreateRedirect, GetRedirect, UpdateRedirect, DeleteRedirect, PauseRedirect, ResumeRedirect, PauseSource, ResumeSource, ListEmailForwards, CreateEmailForward, GetEmailForward, UpdateEmailForward, DeleteEmailForward, ListEmailForwardLogs, GetTotalHits, GetTimeSeries, GetDimensions, ListRawHits, ListDomains, GetDomain, DeleteDomain, CheckDns, GetTeam, ListTeamMembers], Field(discriminator="operation")]

class RedirectPizzaNodeConfig(NodeConfig[Operation, RedirectPizzaCredential]):
    pass

ROUTES = {'list_redirects': ('GET', '/api/v1/redirects', [], ['page', 'per_page', 'query'], []),
 'create_redirect': ('POST',
                     '/api/v1/redirects',
                     [],
                     [],
                     ['sources',
                      'destination',
                      'redirect_type',
                      'uri_forwarding',
                      'keep_query_string',
                      'tracking',
                      'tags',
                      'notes',
                      'merge',
                      'upsert']),
 'get_redirect': ('GET', '/api/v1/redirects/{id}', ['id'], [], []),
 'update_redirect': ('PUT',
                     '/api/v1/redirects/{id}',
                     ['id'],
                     [],
                     ['sources',
                      'destination',
                      'redirect_type',
                      'uri_forwarding',
                      'keep_query_string',
                      'tracking',
                      'tags',
                      'notes']),
 'delete_redirect': ('DELETE', '/api/v1/redirects/{id}', ['id'], [], []),
 'pause_redirect': ('POST', '/api/v1/redirects/{id}/pause', ['id'], [], []),
 'resume_redirect': ('POST', '/api/v1/redirects/{id}/resume', ['id'], [], []),
 'pause_source': ('POST',
                  '/api/v1/redirects/{redirect_id}/sources/{source_id}/pause',
                  ['redirect_id', 'source_id'],
                  [],
                  []),
 'resume_source': ('POST',
                   '/api/v1/redirects/{redirect_id}/sources/{source_id}/resume',
                   ['redirect_id', 'source_id'],
                   [],
                   []),
 'list_email_forwards': ('GET', '/api/v1/email-forwards', [], ['page', 'per_page'], []),
 'create_email_forward': ('POST',
                          '/api/v1/email-forwards',
                          [],
                          [],
                          ['alias', 'domain', 'destination']),
 'get_email_forward': ('GET', '/api/v1/email-forwards/{id}', ['id'], [], []),
 'update_email_forward': ('PUT', '/api/v1/email-forwards/{id}', ['id'], [], ['destination']),
 'delete_email_forward': ('DELETE', '/api/v1/email-forwards/{id}', ['id'], [], []),
 'list_email_forward_logs': ('GET',
                             '/api/v1/email-forwards/logs',
                             [],
                             ['start', 'end', 'query', 'cursor', 'per_page'],
                             []),
 'get_total_hits': ('GET', '/api/v1/analytics/hits', [], ['start', 'end', 'query'], []),
 'get_time_series': ('GET', '/api/v1/analytics/time-series', [], ['start', 'end', 'query'], []),
 'get_dimensions': ('GET',
                    '/api/v1/analytics/dimensions/{dimension}',
                    ['dimension'],
                    ['start', 'end', 'query', 'page', 'per_page'],
                    []),
 'list_raw_hits': ('GET',
                   '/api/v1/analytics/raw',
                   [],
                   ['start', 'end', 'query', 'cursor', 'per_page'],
                   []),
 'list_domains': ('GET', '/api/v1/domains', [], ['page', 'per_page', 'query'], []),
 'get_domain': ('GET', '/api/v1/domains/{id}', ['id'], [], []),
 'delete_domain': ('DELETE', '/api/v1/domains/{id}', ['id'], [], []),
 'check_dns': ('POST', '/api/v1/domains/{id}/check-dns', ['id'], [], []),
 'get_team': ('GET', '/api/v1/team', [], [], []),
 'list_team_members': ('GET', '/api/v1/users', [], ['page', 'per_page'], [])}

class RedirectPizzaNode(WorkflowNode):
    integration_type = "automation-redirect-pizza"
    connection_evidence = ConnectionEvidence(operation="list_redirects", noun="redirects", label_keys=("destination", "id"))

    @classmethod
    def get_config_model(cls):
        return RedirectPizzaNodeConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Redirect Pizza API token")
        method, route, path_fields, query_fields, body_fields = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        for field in path_fields:
            route = route.replace("{" + field + "}", str(values[field]))
        params = {key: values[key] for key in query_fields if key in values}
        body = {key: values[key] for key in body_fields if key in values}
        async with guarded_async_client() as client:
            response = await client.request(method, "https://redirect.pizza" + route,
                headers={"Authorization": "Bearer " + credential.api_token, "Accept": "application/json"},
                params=params, **({"json": body} if body_fields else {}), timeout=30)
        if response.is_error:
            # Preserve the provider's error for connection evidence, redacting the token.
            message = response.text.replace(credential.api_token, "[redacted]")
            raise ValueError(f"Redirect Pizza HTTP {response.status_code}: {message}")
        if response.status_code == 204:
            result = {"success": True}
        else:
            result = response.json()
            if not isinstance(result, dict) or result.get("error") or result.get("errors"):
                raise ValueError("Redirect Pizza returned an unexpected response")
        await self.emit(result)
        return result
