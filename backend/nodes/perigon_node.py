"""Perigon news intelligence and organization-owned source groups/watchlists.

Contract: https://perigon.io/openapi.json, version 1.0.0.
Pagination is explicit and zero based; each execution makes exactly one request.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, hide_input_in_errors=True)


class PerigonApiKeyCredential(_Closed):
    model_config = ConfigDict(title="Perigon API Key", extra="forbid", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://perigon.io/docs/api/authentication",
        "x-credential-instructions": "Copy your API key from your Perigon account and paste it below. Your subscription controls available endpoints.",
    })
    credential_type: Literal["perigon_api_key"] = Field("perigon_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False, description="Paste your Perigon API key without the Bearer prefix.", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def clean_key(cls, value):
        value = value.strip()
        if not value or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste an API key without whitespace or a Bearer prefix")
        return value


class WatchlistPerson(_Closed):
    name: str | None = Field(None, title='Name')
    description: str | None = Field(None, title='Description')
    aliases: list[str] | None = Field(None, title='Aliases', json_schema_extra={"ui:widget": "list"})
    wikidataId: str | None = Field(None, title='Wikidata ID')
    query: str | None = Field(None, title='Query')


class WatchlistCompany(_Closed):
    name: str | None = Field(None, title='Name')
    description: str | None = Field(None, title='Description')
    id: str | None = Field(None, title='Id')
    domain: str | None = Field(None, title='Domain')
    aliases: list[str] | None = Field(None, title='Aliases', json_schema_extra={"ui:widget": "list"})
    query: str | None = Field(None, title='Query')


class SearchArticlesConfig(_Closed):
    operation: Literal['search_articles'] = Field('search_articles', title='All Articles', json_schema_extra={"ui:hidden": True})
    q: str | None = Field(None, title='Search Query')
    articleId: list[str] | None = Field(None, title='Article IDs', json_schema_extra={"ui:widget": "list"})
    clusterId: list[str] | None = Field(None, title='Story IDs', json_schema_extra={"ui:widget": "list"})
    sortBy: Literal['relevance', 'date', 'reverseDate', 'reverseAddDate', 'addDate', 'pubDate', 'refreshDate'] | None = Field(None, title='Sort By')
    page: int = Field(0, ge=0, le=10000, title='Page')
    size: int = Field(10, ge=0, le=1000, title='Size')
    from_: str | None = Field(None, alias='from', title='From')
    to: str | None = Field(None, title='To')
    source: list[str] | None = Field(None, title='Source', json_schema_extra={"ui:widget": "list"})
    sourceGroup: list[str] | None = Field(None, title='Source Group', json_schema_extra={"ui:widget": "list"})
    language: list[str] | None = Field(None, title='Language', json_schema_extra={"ui:widget": "list"})
    category: list[str] | None = Field(None, title='Category', json_schema_extra={"ui:widget": "list"})
    topic: list[str] | None = Field(None, title='Topic', json_schema_extra={"ui:widget": "list"})
    country: list[str] | None = Field(None, title='Country', json_schema_extra={"ui:widget": "list"})


class SearchStoriesConfig(_Closed):
    operation: Literal['search_stories'] = Field('search_stories', title='Stories', json_schema_extra={"ui:hidden": True})
    q: str | None = Field(None, title='Search Query')
    name: str | None = Field(None, title='Name')
    clusterId: list[str] | None = Field(None, title='Story IDs', json_schema_extra={"ui:widget": "list"})
    sortBy: Literal['createdAt', 'updatedAt', 'relevance', 'count', 'totalCount'] | None = Field(None, title='Sort By')
    page: int = Field(0, ge=0, le=10000, title='Page')
    size: int = Field(10, ge=0, le=100, title='Size')
    from_: str | None = Field(None, alias='from', title='From')
    to: str | None = Field(None, title='To')
    topic: list[str] | None = Field(None, title='Topic', json_schema_extra={"ui:widget": "list"})
    category: list[str] | None = Field(None, title='Category', json_schema_extra={"ui:widget": "list"})
    source: list[str] | None = Field(None, title='Source', json_schema_extra={"ui:widget": "list"})
    sourceGroup: list[str] | None = Field(None, title='Source Group', json_schema_extra={"ui:widget": "list"})
    country: list[str] | None = Field(None, title='Country', json_schema_extra={"ui:widget": "list"})


class SearchSourcesConfig(_Closed):
    operation: Literal['search_sources'] = Field('search_sources', title='Sources', json_schema_extra={"ui:hidden": True})
    domain: list[str] | None = Field(None, title='Domain', json_schema_extra={"ui:widget": "list"})
    name: str | None = Field(None, title='Name')
    sourceGroup: str | None = Field(None, title='Source Group')
    sortBy: Literal['globalRank', 'relevance', 'monthlyVisits', 'avgMonthlyPosts'] | None = Field(None, title='Sort By')
    page: int = Field(0, ge=0, le=10000, title='Page')
    size: int = Field(10, ge=1, le=100, title='Size')
    country: list[str] | None = Field(None, title='Country', json_schema_extra={"ui:widget": "list"})
    category: list[str] | None = Field(None, title='Category', json_schema_extra={"ui:widget": "list"})
    topic: list[str] | None = Field(None, title='Topic', json_schema_extra={"ui:widget": "list"})


class SearchCompaniesConfig(_Closed):
    operation: Literal['search_companies'] = Field('search_companies', title='Companies', json_schema_extra={"ui:hidden": True})
    id: list[str] | None = Field(None, title='Id', json_schema_extra={"ui:widget": "list"})
    domain: list[str] | None = Field(None, title='Domain', json_schema_extra={"ui:widget": "list"})
    country: list[str] | None = Field(None, title='Country', json_schema_extra={"ui:widget": "list"})
    q: str | None = Field(None, title='Search Query')
    name: str | None = Field(None, title='Name')
    size: int = Field(10, ge=1, le=100, title='Size')
    page: int = Field(0, ge=0, title='Page')


class SearchPeopleConfig(_Closed):
    operation: Literal['search_people'] = Field('search_people', title='People', json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, title='Name')
    page: int = Field(0, ge=0, title='Page')
    size: int = Field(10, ge=1, le=100, title='Size')


class SearchJournalistsConfig(_Closed):
    operation: Literal['search_journalists'] = Field('search_journalists', title='Journalists', json_schema_extra={"ui:hidden": True})
    id: list[str] | None = Field(None, title='Id', json_schema_extra={"ui:widget": "list"})
    q: str | None = Field(None, title='Search Query')
    name: str | None = Field(None, title='Name')
    sortBy: Literal['avgMonthlyPosts', 'linkedinConnections', 'linkedinFollowers'] | None = Field(None, title='Sort By')
    size: int = Field(10, ge=0, le=1000, title='Size')
    page: int = Field(0, ge=0, title='Page')
    source: list[str] | None = Field(None, title='Source', json_schema_extra={"ui:widget": "list"})
    topic: list[str] | None = Field(None, title='Topic', json_schema_extra={"ui:widget": "list"})
    category: list[str] | None = Field(None, title='Category', json_schema_extra={"ui:widget": "list"})
    country: list[str] | None = Field(None, title='Country', json_schema_extra={"ui:widget": "list"})


class SearchTopicsConfig(_Closed):
    operation: Literal['search_topics'] = Field('search_topics', title='Topics', json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, title='Name')
    category: str | None = Field(None, title='Category')
    page: int = Field(0, ge=0, title='Page')
    size: int = Field(10, ge=0, title='Size')


class GetLimitsConfig(_Closed):
    operation: Literal['get_limits'] = Field('get_limits', title='Limits', json_schema_extra={"ui:hidden": True})


class ListSourceGroupsConfig(_Closed):
    operation: Literal['list_source_groups'] = Field('list_source_groups', title='List source groups', json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, title='Name')
    domain: str | None = Field(None, title='Domain')
    sortBy: Literal['id', 'createdAt', 'updatedAt', 'name'] = Field('id', title='Sort By')
    page: int = Field(0, ge=0, description='Zero-based page number to retrieve. Defaults to 0.', title='Page')
    size: int = Field(10, ge=1, le=100, description='Number of results per page. Must be between 1 and 100; defaults to 10.', title='Size')
    sortOrder: Literal['asc', 'desc'] = Field('asc', description='Required direction used to sort results. Accepts asc or desc.', title='Sort Order')
    nulls: Literal['first', 'last'] | None = Field(None, description='Placement of null values in sorted results. Accepts first or last.', title='Nulls')


class CreateSourceGroupConfig(_Closed):
    operation: Literal['create_source_group'] = Field('create_source_group', title='Create source group', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., title='Name')
    displayName: str | None = Field(None, title='Display Name')
    description: str | None = Field(None, title='Description')
    domains: list[str] = Field(..., min_length=1, max_length=5000, title='Domains', json_schema_extra={"ui:widget": "list"})


class ResolveSourceGroupsConfig(_Closed):
    operation: Literal['resolve_source_groups'] = Field('resolve_source_groups', title='Resolve source groups', json_schema_extra={"ui:hidden": True})
    name: list[str] | None = Field(None, min_length=0, max_length=100, title='Name', json_schema_extra={"ui:widget": "list"})


class GetSourceGroupConfig(_Closed):
    operation: Literal['get_source_group'] = Field('get_source_group', title='Get source group', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., title='Id')


class UpdateSourceGroupConfig(_Closed):
    operation: Literal['update_source_group'] = Field('update_source_group', title='Update source group', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., title='Id')
    name: str | None = Field(None, description='Unique name for the source group within the organization', title='Name')
    displayName: str | None = Field(None, description='Display name for the source group', title='Display Name')
    description: str | None = Field(None, min_length=0, max_length=512, description='Description of the source group', title='Description')
    domains: list[str] | None = Field(None, min_length=1, max_length=5000, description='List of domains included in the source group', title='Domains', json_schema_extra={"ui:widget": "list"})


class DeleteSourceGroupConfig(_Closed):
    operation: Literal['delete_source_group'] = Field('delete_source_group', title='Delete source group', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., title='Id')


class ListWatchlistsConfig(_Closed):
    operation: Literal['list_watchlists'] = Field('list_watchlists', title='List watchlists', json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, title='Name')
    sortBy: Literal['id', 'createdAt', 'updatedAt', 'name'] = Field('id', title='Sort By')
    page: int = Field(0, ge=0, description='Zero-based page number to retrieve. Defaults to 0.', title='Page')
    size: int = Field(10, ge=1, le=100, description='Number of results per page. Must be between 1 and 100; defaults to 10.', title='Size')
    sortOrder: Literal['asc', 'desc'] = Field('asc', description='Required direction used to sort results. Accepts asc or desc.', title='Sort Order')
    nulls: Literal['first', 'last'] | None = Field(None, description='Placement of null values in sorted results. Accepts first or last.', title='Nulls')


class CreateWatchlistConfig(_Closed):
    operation: Literal['create_watchlist'] = Field('create_watchlist', title='Create watchlist', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, description='Unique name for the watchlist within the organization', title='Name')
    displayName: str | None = Field(None, description='Display name for the watchlist', title='Display Name')
    description: str | None = Field(None, description='Description of the watchlist', title='Description')
    people: list[WatchlistPerson] = Field(..., min_length=0, max_length=100, description='List of people to include in the watchlist', title='People', json_schema_extra={"ui:widget": "state_editor", 'placeholder': '[{"name": "Sam Altman", "wikidataId": "Q7411063"}]'})
    companies: list[WatchlistCompany] = Field(..., min_length=0, max_length=100, description='List of companies to include in the watchlist', title='Companies', json_schema_extra={"ui:widget": "state_editor", 'placeholder': '[{"name": "OpenAI", "domain": "openai.com"}]'})
    visible: bool | None = Field(None, description='Whether the watchlist is visible in the UI', title='Visible')


class ResolveWatchlistsConfig(_Closed):
    operation: Literal['resolve_watchlists'] = Field('resolve_watchlists', title='Resolve watchlists', json_schema_extra={"ui:hidden": True})
    name: list[str] | None = Field(None, min_length=0, max_length=100, title='Name', json_schema_extra={"ui:widget": "list"})


class GetWatchlistConfig(_Closed):
    operation: Literal['get_watchlist'] = Field('get_watchlist', title='Get watchlist', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., title='Id')


class UpdateWatchlistConfig(_Closed):
    operation: Literal['update_watchlist'] = Field('update_watchlist', title='Update watchlist', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., title='Id')
    name: str | None = Field(None, description='New name for the watchlist', title='Name')
    displayName: str | None = Field(None, description='New display name for the watchlist', title='Display Name')
    description: str | None = Field(None, description='New description for the watchlist', title='Description')
    people: list[WatchlistPerson] | None = Field(None, description='Updated list of people to include in the watchlist', title='People', json_schema_extra={"ui:widget": "state_editor", 'placeholder': '[{"name": "Sam Altman", "wikidataId": "Q7411063"}]'})
    companies: list[WatchlistCompany] | None = Field(None, description='Updated list of companies to include in the watchlist', title='Companies', json_schema_extra={"ui:widget": "state_editor", 'placeholder': '[{"name": "OpenAI", "domain": "openai.com"}]'})
    visible: bool | None = Field(None, description='Whether the watchlist is visible in the UI', title='Visible')


class DeleteWatchlistConfig(_Closed):
    operation: Literal['delete_watchlist'] = Field('delete_watchlist', title='Delete watchlist', json_schema_extra={"ui:hidden": True})
    id: int = Field(..., title='Id')


Operation = Annotated[Union[SearchArticlesConfig, SearchStoriesConfig, SearchSourcesConfig, SearchCompaniesConfig, SearchPeopleConfig, SearchJournalistsConfig, SearchTopicsConfig, GetLimitsConfig, ListSourceGroupsConfig, CreateSourceGroupConfig, ResolveSourceGroupsConfig, GetSourceGroupConfig, UpdateSourceGroupConfig, DeleteSourceGroupConfig, ListWatchlistsConfig, CreateWatchlistConfig, ResolveWatchlistsConfig, GetWatchlistConfig, UpdateWatchlistConfig, DeleteWatchlistConfig], Field(discriminator="operation")]


class PerigonNodeConfig(NodeConfig[Operation, PerigonApiKeyCredential]):
    pass


# (HTTP method, contract path, query fields, JSON body fields).
ROUTES = {'search_articles': ('GET',
                     '/v1/articles/all',
                     ['q',
                      'articleId',
                      'clusterId',
                      'sortBy',
                      'page',
                      'size',
                      'from',
                      'to',
                      'source',
                      'sourceGroup',
                      'language',
                      'category',
                      'topic',
                      'country'],
                     []),
 'search_stories': ('GET',
                    '/v1/stories/all',
                    ['q',
                     'name',
                     'clusterId',
                     'sortBy',
                     'page',
                     'size',
                     'from',
                     'to',
                     'topic',
                     'category',
                     'source',
                     'sourceGroup',
                     'country'],
                    []),
 'search_sources': ('GET',
                    '/v1/sources/all',
                    ['domain',
                     'name',
                     'sourceGroup',
                     'sortBy',
                     'page',
                     'size',
                     'country',
                     'category',
                     'topic'],
                    []),
 'search_companies': ('GET',
                      '/v1/companies/all',
                      ['id', 'domain', 'country', 'q', 'name', 'size', 'page'],
                      []),
 'search_people': ('GET', '/v1/people/all', ['name', 'page', 'size'], []),
 'search_journalists': ('GET',
                        '/v1/journalists/all',
                        ['id',
                         'q',
                         'name',
                         'sortBy',
                         'size',
                         'page',
                         'source',
                         'topic',
                         'category',
                         'country'],
                        []),
 'search_topics': ('GET', '/v1/topics/all', ['name', 'category', 'page', 'size'], []),
 'get_limits': ('GET', '/v1/limits', [], []),
 'list_source_groups': ('GET',
                        '/v1/api/sourceGroups',
                        ['name', 'domain', 'sortBy', 'page', 'size', 'sortOrder', 'nulls'],
                        []),
 'create_source_group': ('POST',
                         '/v1/api/sourceGroups',
                         [],
                         ['name', 'displayName', 'description', 'domains']),
 'resolve_source_groups': ('GET', '/v1/api/sourceGroups/resolve', ['name'], []),
 'get_source_group': ('GET', '/v1/api/sourceGroups/{id}', [], []),
 'update_source_group': ('PATCH',
                         '/v1/api/sourceGroups/{id}',
                         [],
                         ['name', 'displayName', 'description', 'domains']),
 'delete_source_group': ('DELETE', '/v1/api/sourceGroups/{id}', [], []),
 'list_watchlists': ('GET',
                     '/v1/api/watchlists',
                     ['name', 'sortBy', 'page', 'size', 'sortOrder', 'nulls'],
                     []),
 'create_watchlist': ('POST',
                      '/v1/api/watchlists',
                      [],
                      ['name', 'displayName', 'description', 'people', 'companies', 'visible']),
 'resolve_watchlists': ('GET', '/v1/api/watchlists/resolve', ['name'], []),
 'get_watchlist': ('GET', '/v1/api/watchlists/{id}', [], []),
 'update_watchlist': ('PATCH',
                      '/v1/api/watchlists/{id}',
                      [],
                      ['name', 'displayName', 'description', 'people', 'companies', 'visible']),
 'delete_watchlist': ('DELETE', '/v1/api/watchlists/{id}', [], [])}


class PerigonNode(WorkflowNode):
    integration_type = "automation-perigon"
    connection_evidence = ConnectionEvidence(noun="Perigon organization", identity_operation="get_limits", identity_keys=("organizationName",))

    @classmethod
    def get_config_model(cls):
        return PerigonNodeConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Perigon API key")
        config = self.config.config
        values = config.model_dump(by_alias=True, exclude_none=True)
        method, path, query_names, body_names = ROUTES[config.operation]
        if "{id}" in path:
            path = path.replace("{id}", str(values["id"]))
        # Repeated keys implement OpenAPI's form/explode array query encoding.
        params = [(name, str(item).lower() if isinstance(item, bool) else str(item))
                  for name in query_names if name in values
                  for item in (values[name] if isinstance(values[name], list) else [values[name]])]
        body = {name: values[name] for name in body_names if name in values}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, "https://api.perigon.io" + path,
                headers={"Authorization": "Bearer " + self.config.credentials.api_key, "Accept": "application/json"},
                params=params, **({"json": body} if body_names else {}))
        if response.status_code != 200:
            # Keep definitive provider rejection wording for the connect seam.
            message = "Perigon request failed"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"].replace(self.config.credentials.api_key, "[redacted]")[:1000]
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code, "error": message}
        if len(response.content) > 10_000_000 or "json" not in response.headers.get("content-type", ""):
            raise ValueError("Expected a bounded JSON response from Perigon")
        result = response.json()
        if not isinstance(result, dict) or "message" in result:
            raise ValueError("Perigon returned an incomplete response")
        result_key = "articles" if config.operation == "search_articles" else "results" if config.operation in {"search_stories", "search_sources", "search_companies", "search_people", "search_journalists"} else "data"
        if result_key not in result or not isinstance(result[result_key], (dict, list)):
            raise ValueError("Perigon response is missing its documented payload")
        if config.operation == "get_limits":
            if not isinstance(result["data"], dict):
                raise ValueError("Perigon limits data must be an object")
            return {"status": "success", **result["data"]}
        return {**result, "status": "success"}
