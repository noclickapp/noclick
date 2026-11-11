"""Open States API v3 (published OpenAPI 2021.11.12).

Public legislative data, read-only; API keys authenticate access, not ownership.
Contract: https://v3.openstates.org/openapi.json
Authentication: https://github.com/openstates/documentation/blob/main/docs/api-v3/index.md
"""
from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.poll_trigger import PollTriggerConfigBase, ScheduledPollTriggerMixin

BASE_URL = "https://v3.openstates.org"


class OpenStatesAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Open States API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://open.pluralpolicy.com/accounts/profile/",
        "x-credential-instructions": "Copy your activated Open States API key from your profile and paste it here.",
    })
    credential_type: Literal["openstates_api_key"] = Field("openstates_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def clean_key(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste an API key without whitespace")
        return value


class _ReadConfig(BaseModel):
    @field_validator("include", "id", "identifier", "subject", mode="before", check_fields=False)
    @classmethod
    def parse_arrays(cls, value, info):
        annotation = cls.model_fields[info.field_name].annotation
        if "list[" in str(annotation) and isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                raise ValueError("Enter a JSON array of strings") from None
        return value


def _operation(name, title, category):
    return Field(name, title=title, json_schema_extra={
        "ui:hidden": True, "x-is-trigger": False, "x-display-name": title, "x-category": category,
    })


class OpenStatesSearchBillsConfig(_ReadConfig):
    operation: Literal['search_bills'] = _operation('search_bills', 'Search Bills', 'Bills')
    jurisdiction: str | None = Field(None, description='Filter by jurisdiction name or ID.')
    session: str | None = Field(None, description='Filter by session identifier.')
    chamber: str | None = Field(None, description='Filter by chamber of origination.')
    identifier: list[str] = Field([], description='Filter to only include bills with this identifier.')
    classification: str | None = Field(None, description='Filter by classification, e.g. bill or resolution')
    subject: list[str] = Field([], description='Filter by one or more subjects.')
    updated_since: str | None = Field(None, description='Filter to only include bills with updates since a given date.')
    created_since: str | None = Field(None, description='Filter to only include bills created since a given date.')
    action_since: str | None = Field(None, description='Filter to only include bills with an action since a given date.')
    sort: Literal['updated_asc', 'updated_desc', 'first_action_asc', 'first_action_desc', 'latest_action_asc', 'latest_action_desc'] = Field('updated_desc', description='Desired sort order for bill results.')
    sponsor: str | None = Field(None, description='Filter to only include bills sponsored by a given name or person ID.')
    sponsor_classification: str | None = Field(None, description='Filter matched sponsors to only include particular types of sponsorships.')
    q: str | None = Field(None, description='Filter by full text search term.')
    include: list[Literal['sponsorships', 'abstracts', 'other_titles', 'other_identifiers', 'actions', 'sources', 'documents', 'versions', 'votes', 'related_bills']] = Field([], description='Additional information to include in response.')
    page: int = Field(1, description='Page', ge=1, le=100000)
    per_page: int = Field(10, description='Per page', ge=1, le=20)

class OpenStatesGetBillByIdConfig(_ReadConfig):
    operation: Literal['get_bill_by_id'] = _operation('get_bill_by_id', 'Get Bill by Open States ID', 'Bills')
    openstates_bill_id: str = Field(..., description='Openstates bill id', min_length=1)
    include: list[Literal['sponsorships', 'abstracts', 'other_titles', 'other_identifiers', 'actions', 'sources', 'documents', 'versions', 'votes', 'related_bills']] = Field([], description='Include')

class OpenStatesGetBillConfig(_ReadConfig):
    operation: Literal['get_bill'] = _operation('get_bill', 'Get Bill by Jurisdiction and Session', 'Bills')
    jurisdiction: str = Field(..., description='Jurisdiction', min_length=1)
    session: str = Field(..., description='Session', min_length=1)
    bill_id: str = Field(..., description='Bill id', min_length=1)
    include: list[Literal['sponsorships', 'abstracts', 'other_titles', 'other_identifiers', 'actions', 'sources', 'documents', 'versions', 'votes', 'related_bills']] = Field([], description='Include')

class OpenStatesSearchPeopleConfig(_ReadConfig):
    operation: Literal['search_people'] = _operation('search_people', 'Search People', 'People')
    jurisdiction: str | None = Field(None, description='Filter by jurisdiction name or id.')
    name: str | None = Field(None, description='Filter by name, case-insensitive match.')
    id: list[str] = Field([], description='Filter by id, can be specified multiple times for multiple people.')
    org_classification: Literal['legislature', 'executive', 'lower', 'upper', 'government'] | None = Field(None, description='Filter by current role.')
    district: str | None = Field(None, description='Filter by district name.')
    include: list[Literal['other_names', 'other_identifiers', 'links', 'sources', 'offices']] = Field([], description='Additional information to include in response.')
    page: int = Field(1, description='Page', ge=1, le=100000)
    per_page: int = Field(10, description='Per page', ge=1, le=50)

class OpenStatesFindLegislatorsConfig(_ReadConfig):
    operation: Literal['find_legislators'] = _operation('find_legislators', 'Find Legislators by Location', 'People')
    lat: float = Field(..., description='Latitude of point.', ge=-90, le=90)
    lng: float = Field(..., description='Longitude of point.', ge=-180, le=180)
    include: list[Literal['other_names', 'other_identifiers', 'links', 'sources', 'offices']] = Field([], description='Additional information to include in the response.')

class OpenStatesListJurisdictionsConfig(_ReadConfig):
    operation: Literal['list_jurisdictions'] = _operation('list_jurisdictions', 'List Jurisdictions', 'Jurisdictions')
    classification: Literal['state', 'municipality', 'country'] | None = Field(None, description='Filter returned jurisdictions by type.')
    include: list[Literal['organizations', 'legislative_sessions', 'latest_runs']] = Field([], description='Additional information to include in response.')
    page: int = Field(1, description='Page', ge=1, le=100000)
    per_page: int = Field(52, description='Per page', ge=1, le=52)

class OpenStatesGetJurisdictionConfig(_ReadConfig):
    operation: Literal['get_jurisdiction'] = _operation('get_jurisdiction', 'Get Jurisdiction', 'Jurisdictions')
    jurisdiction_id: str = Field(..., description='Jurisdiction id', min_length=1)
    include: list[Literal['organizations', 'legislative_sessions', 'latest_runs']] = Field([], description='Additional includes for the Jurisdiction response.')

class OpenStatesListCommitteesConfig(_ReadConfig):
    operation: Literal['list_committees'] = _operation('list_committees', 'List Committees', 'Committees')
    jurisdiction: str | None = Field(None, description='Filter by jurisdiction name or ID.')
    classification: Literal['committee', 'subcommittee'] | None = Field(None, description='Classification')
    parent: str | None = Field(None, description='ocd-organization ID of parent committee.')
    chamber: Literal['legislature', 'executive', 'lower', 'upper', 'government'] | None = Field(None, description='Chamber of committee, generally upper or lower.')
    include: list[Literal['memberships', 'links', 'sources']] = Field([], description='Additional includes for the Committee response.')
    page: int = Field(1, description='Page', ge=1, le=100000)
    per_page: int = Field(20, description='Per page', ge=1, le=20)

class OpenStatesGetCommitteeConfig(_ReadConfig):
    operation: Literal['get_committee'] = _operation('get_committee', 'Get Committee', 'Committees')
    committee_id: str = Field(..., description='Committee id', min_length=1)
    include: list[Literal['memberships', 'links', 'sources']] = Field([], description='Additional includes for the Committee response.')

class OpenStatesListEventsConfig(_ReadConfig):
    operation: Literal['list_events'] = _operation('list_events', 'List Legislative Events', 'Events')
    jurisdiction: str | None = Field(None, description='Filter by jurisdiction name or ID.')
    deleted: bool = Field(False, description='Return events marked as deleted?')
    before: str | None = Field(None, description='Limit results to those starting before a given datetime.')
    after: str | None = Field(None, description='Limit results to those starting before a given datetime.')
    require_bills: bool = Field(False, description='Limit results to events with associated bills.')
    include: list[Literal['links', 'sources', 'media', 'documents', 'participants', 'agenda']] = Field([], description='Additional includes for the Event response.')
    page: int = Field(1, description='Page', ge=1, le=100000)
    per_page: int = Field(20, description='Per page', ge=1, le=20)

class OpenStatesGetEventConfig(_ReadConfig):
    operation: Literal['get_event'] = _operation('get_event', 'Get Legislative Event', 'Events')
    event_id: str = Field(..., description='Event id', min_length=1)
    include: list[Literal['links', 'sources', 'media', 'documents', 'participants', 'agenda']] = Field([], description='Additional includes for the Event response.')


class OpenStatesOnBillUpdatedConfig(PollTriggerConfigBase):
    model_config = ConfigDict(json_schema_extra={"x-requires-webhook": True})
    operation: Literal["on_bill_updated"] = Field("on_bill_updated", title="On New or Updated Bill", json_schema_extra={
        "ui:hidden": True, "x-is-trigger": True, "x-category": "Triggers", "x-display-name": "On New or Updated Bill",
    })
    jurisdiction: str = Field(..., min_length=1, description="Jurisdiction name or ID to monitor.")
    session: str | None = Field(None, description="Optional legislative session identifier.")
    updated_since: str | None = Field(None, description="Only monitor bills updated since this fixed date (ISO 8601).")

OpenStatesConfig = Annotated[Union[OpenStatesSearchBillsConfig, OpenStatesGetBillByIdConfig, OpenStatesGetBillConfig, OpenStatesSearchPeopleConfig, OpenStatesFindLegislatorsConfig, OpenStatesListJurisdictionsConfig, OpenStatesGetJurisdictionConfig, OpenStatesListCommitteesConfig, OpenStatesGetCommitteeConfig, OpenStatesListEventsConfig, OpenStatesGetEventConfig, OpenStatesOnBillUpdatedConfig], Field(discriminator="operation")]


class OpenStatesNodeConfig(NodeConfig[OpenStatesConfig, OpenStatesAPIKeyCredential]):
    pass


# Page-size ceilings are documented by the provider pagination implementations:
# https://github.com/openstates/api-v3/tree/main/api
ROUTES = {'search_bills': ('/bills',
                  (),
                  ('jurisdiction',
                   'session',
                   'chamber',
                   'identifier',
                   'classification',
                   'subject',
                   'updated_since',
                   'created_since',
                   'action_since',
                   'sort',
                   'sponsor',
                   'sponsor_classification',
                   'q',
                   'include',
                   'page',
                   'per_page')),
 'get_bill_by_id': ('/bills/ocd-bill/{openstates_bill_id}', ('openstates_bill_id',), ('include',)),
 'get_bill': ('/bills/{jurisdiction}/{session}/{bill_id}',
              ('jurisdiction', 'session', 'bill_id'),
              ('include',)),
 'search_people': ('/people',
                   (),
                   ('jurisdiction',
                    'name',
                    'id',
                    'org_classification',
                    'district',
                    'include',
                    'page',
                    'per_page')),
 'find_legislators': ('/people.geo', (), ('lat', 'lng', 'include')),
 'list_jurisdictions': ('/jurisdictions', (), ('classification', 'include', 'page', 'per_page')),
 'get_jurisdiction': ('/jurisdictions/{jurisdiction_id}', ('jurisdiction_id',), ('include',)),
 'list_committees': ('/committees',
                     (),
                     ('jurisdiction',
                      'classification',
                      'parent',
                      'chamber',
                      'include',
                      'page',
                      'per_page')),
 'get_committee': ('/committees/{committee_id}', ('committee_id',), ('include',)),
 'list_events': ('/events',
                 (),
                 ('jurisdiction',
                  'deleted',
                  'before',
                  'after',
                  'require_bills',
                  'include',
                  'page',
                  'per_page')),
 'get_event': ('/events/{event_id}', ('event_id',), ('include',))}


class OpenStatesNode(ScheduledPollTriggerMixin, WorkflowNode):
    integration_type = "automation-openstates"
    connection_evidence = ConnectionEvidence(
        noun="public jurisdictions", operation="list_jurisdictions", proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return OpenStatesNodeConfig

    @staticmethod
    async def _request(api_key: str, path: str, params: dict[str, Any]):
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request("GET", BASE_URL + path, params=params,
                headers={"X-API-KEY": api_key, "Accept": "application/json"})
        if response.is_error or response.is_redirect:
            try:
                detail = response.json().get("detail", "Request failed")
            except (ValueError, AttributeError):
                detail = "Request failed"
            # Preserve the provider's authentication verdict for manual connect.
            detail = str(detail).replace(api_key, "[redacted]")
            raise ValueError(f"Open States API {response.status_code}: {detail}")
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Open States returned an invalid JSON object")
        return body

    @staticmethod
    def _page(body):
        rows, pagination = body.get("results"), body.get("pagination")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows) or not isinstance(pagination, dict):
            raise ValueError("Open States returned an invalid list response")
        page, max_page = pagination.get("page"), pagination.get("max_page")
        if type(page) is not int or type(max_page) is not int or page < 1 or max_page < page:
            raise ValueError("Open States returned invalid pagination")
        return rows, pagination

    async def _poll_bills(self, api_key, config):
        params = {"jurisdiction": config.jurisdiction, "sort": "updated_desc", "per_page": 20}
        if config.session is not None:
            params["session"] = config.session
        if config.updated_since is not None:
            params["updated_since"] = config.updated_since
        bills = []
        for page in range(1, 51):
            body = await self._request(api_key, "/bills", {**params, "page": page})
            rows, pagination = self._page(body)
            if pagination["page"] != page:
                raise ValueError("Open States pagination did not advance")
            bills.extend(rows)
            if page >= pagination["max_page"]:
                break
        else:
            raise ValueError("More than 1,000 bills in this scope; choose a session or a later Updated Since date")
        for bill in bills:
            if not isinstance(bill.get("id"), str) or not bill["id"] or not isinstance(bill.get("updated_at"), str) or not bill["updated_at"]:
                raise ValueError("A polled bill is missing its ID or update timestamp")
        fresh = await self._filter_unseen(bills, lambda bill: bill["id"] + ":" + bill["updated_at"])
        return {"bills": fresh, "bill_count": len(fresh)}

    @classmethod
    def should_propagate_output(cls, output, config):
        return bool(output.get("bill_count")) if config.get("operation") == "on_bill_updated" else True

    @classmethod
    def resolve_agent_event(cls, output):
        bills = output.get("bills") if isinstance(output, dict) else None
        if not isinstance(bills, list):
            return super().resolve_agent_event(output)
        if not bills:
            return None
        lines = [f"- {bill.get('identifier')}: {bill.get('title')} in {bill.get('session')} "
                 f"({bill.get('id')}, updated {bill.get('updated_at')}) {bill.get('openstates_url')}" for bill in bills[:20]]
        return {"text": f"Open States: {len(bills)} new or updated bill(s):\n" + "\n".join(lines), "conversation_key": None}

    async def execute(self, inputs):
        if not isinstance(self.config, OpenStatesNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect an Open States API key")
        config, key = self.config.config, self.config.credentials.api_key
        if isinstance(config, OpenStatesOnBillUpdatedConfig):
            return await self._poll_bills(key, config)
        path, path_fields, query_fields = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        for field in path_fields:
            value = values[field]
            if field == "openstates_bill_id" and value.startswith("ocd-bill/"):
                value = value.removeprefix("ocd-bill/")
            path = path.replace("{" + field + "}", quote(value, safe=""))
        body = await self._request(key, path, {field: values[field] for field in query_fields if field in values})
        if "results" in body or "pagination" in body:
            rows, pagination = self._page(body)
            return {"results": rows, "pagination": pagination,
                    "next_page": pagination["page"] + 1 if pagination["page"] < pagination["max_page"] else None}
        return body
