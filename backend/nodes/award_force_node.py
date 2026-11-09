"""Award Force v2.3 entries, people and judging automation.

Each action issues one documented request; lists return one page without following
provider URLs. Regional hosts and the versioned media type are fixed by the contract.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

ACCEPT = "application/vnd.Creative Force.v2.3+json"
Slug = Annotated[str, Field(pattern=r"^[A-Za-z]{8}$")]


class AwardForceAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Award Force API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.awardforce.com/api-reference/openapi-v2_3.yaml",
            "x-credential-instructions": "Paste your Award Force API key and select the region hosting your account. NoClick verifies the connection by reading the account associated with the key.",
        })
    credential_type: Literal["award_force_api_key"] = Field("award_force_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, repr=False, title="API key", json_schema_extra={"ui:widget": "password"})
    region: Literal["us", "eu", "au", "ca", "hk"] = Field("us", title="Account region")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page number, starting at 1. Only this page is fetched.")
    per_page: int = Field(10, ge=1, le=100, title="Results per page")


class _EntryValues(_Input):
    title: str | None = None
    category: Slug | None = None
    chapter: Slug | None = None
    entrant: Slug | None = None
    status: Literal["submitted", "in_progress", "resubmission_required", "resubmitted"] | None = None
    moderation_status: Literal["approved", "undecided", "rejected"] | None = None
    entry_fields_json: str | None = Field(None, title="Entry fields (JSON)", description="JSON object mapping eight-letter field slugs to values.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

    @field_validator("entry_fields_json")
    @classmethod
    def fields_json(cls, value):
        if value is None:
            return value
        parsed = json.loads(value)
        import re
        if not isinstance(parsed, dict) or any(not re.fullmatch(r"[A-Za-z]{8}", k) for k in parsed):
            raise ValueError("Entry fields must be an object keyed by eight-letter field slugs")
        return value


class GetAccount(_Input):
    operation: Literal['get_account'] = Field('get_account', title='Get account', json_schema_extra={"ui:hidden": True})



class ListEntries(_Page):
    operation: Literal['list_entries'] = Field('list_entries', title='List entries', json_schema_extra={"ui:hidden": True})
    entrant: str | None = Field(None, description='Filter by entrant slug.')
    status: Literal['submitted', 'in_progress', 'resubmission_required', 'resubmitted'] | None = Field(None, description='Filter by entry status.')
    title: str | None = Field(None, description='Filter by full or partial entry name.')
    updated_at: str | None = Field(None, description='Filter by update timestamp.\nSupported values:\n* `[before]=YYYY-MM-DDTHH:MM:SSZ`\n* `[after]=YYYY-MM-DDTHH:MM:SSZ`\n* `[on]=YYYY-MM-DDTHH:MM:SSZ`\n* `[between]=[YYYY-MM-DDTHH:MM:SSZ,YYYY-MM-DDTHH:MM:SSZ]`')
    category: str | None = Field(None, description='Filter by category slug.')
    chapter: str | None = Field(None, description='Filter by chapter slug.')
    season: str | None = Field(None, description='Filter by season slug.\nUse `all` to show all seasons.')
    tag: str | None = Field(None, description='Filter by tag.')


class GetEntry(_Input):
    operation: Literal['get_entry'] = Field('get_entry', title='Get entry', json_schema_extra={"ui:hidden": True})
    entry_slug: Slug


class ListUsers(_Page):
    operation: Literal['list_users'] = Field('list_users', title='List users', json_schema_extra={"ui:hidden": True})



class ListCategories(_Page):
    operation: Literal['list_categories'] = Field('list_categories', title='List categories', json_schema_extra={"ui:hidden": True})
    status: Literal['active', 'inactive'] | None = Field(None, description='Filter by status.')
    chapter: str | None = Field(None, description='Filter by chapter slug.')
    season: str | None = Field(None, description='Filter by season slug.\nUse `all` to show all seasons.')


class GetCategory(_Input):
    operation: Literal['get_category'] = Field('get_category', title='Get category', json_schema_extra={"ui:hidden": True})
    category_slug: Slug


class ListSeasons(_Page):
    operation: Literal['list_seasons'] = Field('list_seasons', title='List seasons', json_schema_extra={"ui:hidden": True})



class GetSeason(_Input):
    operation: Literal['get_season'] = Field('get_season', title='Get season', json_schema_extra={"ui:hidden": True})
    season_slug: Slug


class ListRounds(_Page):
    operation: Literal['list_rounds'] = Field('list_rounds', title='List rounds', json_schema_extra={"ui:hidden": True})
    season: str | None = Field(None, description='Filter by season slug.\nUse `all` to show all seasons.')


class GetRound(_Input):
    operation: Literal['get_round'] = Field('get_round', title='Get round', json_schema_extra={"ui:hidden": True})
    round_slug: Slug


class ListScoreSets(_Page):
    operation: Literal['list_score_sets'] = Field('list_score_sets', title='List score sets', json_schema_extra={"ui:hidden": True})
    season: str | None = Field(None, description='Filter by season slug.\nUse `all` to show all seasons.')


class GetScoreSet(_Input):
    operation: Literal['get_score_set'] = Field('get_score_set', title='Get score set', json_schema_extra={"ui:hidden": True})
    score_set_slug: Slug


class ListAssignments(_Page):
    operation: Literal['list_assignments'] = Field('list_assignments', title='List assignments', json_schema_extra={"ui:hidden": True})
    status: Literal['none', 'in_progress', 'complete', 'abstained'] | None = Field(None, description='Filter by assignment status.')
    category: str | None = Field(None, description='Filter by category slug.')
    chapter: str | None = Field(None, description='Filter by chapter slug.')
    judge: str | None = Field(None, description='Filter by judge slug.')
    score_set: str | None = Field(None, description='Filter by score set slug.')
    season: str | None = Field(None, description='Filter by season slug.\nUse `all` to show all seasons.')
    tag: str | None = Field(None, description='Filter by tag.')


class GetAssignment(_Input):
    operation: Literal['get_assignment'] = Field('get_assignment', title='Get assignment', json_schema_extra={"ui:hidden": True})
    assignment_slug: str = Field(..., pattern=r"^[A-Za-z0-9]{24}[JR]$")


class CreateEntry(_EntryValues):
    operation: Literal['create_entry'] = Field('create_entry', title='Create entry', json_schema_extra={"ui:hidden": True})
    category: Slug
    entrant: Slug
    season: Slug
    title: str = Field(..., min_length=1)
    status: Literal["submitted", "in_progress", "resubmission_required"] | None = None
    form: Slug | None = None


class UpdateEntry(_EntryValues):
    operation: Literal['update_entry'] = Field('update_entry', title='Update entry', json_schema_extra={"ui:hidden": True})
    entry_slug: Slug

    @model_validator(mode="after")
    def has_change(self):
        if not any(getattr(self, key) is not None for key in ('category', 'chapter', 'entrant', 'title', 'status', 'moderation_status', 'entry_fields_json')):
            raise ValueError("Supply at least one field to update")
        return self


class DeleteEntry(_Input):
    operation: Literal['delete_entry'] = Field('delete_entry', title='Delete entry', json_schema_extra={"ui:hidden": True})
    entry_slug: Slug


def _tags(value):
    if value in {".", ".."} or not any(tag.strip() for tag in value.split(",")):
        raise ValueError("Supply at least one tag; dot path segments are not allowed")
    return value


class TagEntry(_Input):
    operation: Literal['tag_entry'] = Field('tag_entry', title='Tag entry', json_schema_extra={"ui:hidden": True})
    entry_slug: Slug
    tags: str = Field(..., min_length=1, pattern=r"^[^/\\?#\x00-\x1f]+$", description="Comma-separated tags; commas separate tags, and slashes are not allowed.")
    _validate_tags = field_validator("tags")(_tags)


class UntagEntry(_Input):
    operation: Literal['untag_entry'] = Field('untag_entry', title='Untag entry', json_schema_extra={"ui:hidden": True})
    entry_slug: Slug
    tags: str = Field(..., min_length=1, pattern=r"^[^/\\?#\x00-\x1f]+$", description="Comma-separated tags; commas separate tags, and slashes are not allowed.")
    _validate_tags = field_validator("tags")(_tags)


class UpdateEntryTitle(_Input):
    operation: Literal['update_entry_title'] = Field('update_entry_title', title='Update entry title', json_schema_extra={"ui:hidden": True})
    entry_slug: Slug
    title: str = Field(..., max_length=255)


class UpdateEntryField(_Input):
    operation: Literal['update_entry_field'] = Field('update_entry_field', title='Update entry field', json_schema_extra={"ui:hidden": True})
    entry_slug: Slug
    field_slug: Slug
    value_json: str = Field(..., title="Field value (JSON)", description="A JSON value matching the target field type, such as a quoted string, number or array.", json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"})

    @field_validator("value_json")
    @classmethod
    def valid_json(cls, value):
        json.loads(value)
        return value


class UpdateUser(_Input):
    operation: Literal['update_user'] = Field('update_user', title='Update user', json_schema_extra={"ui:hidden": True})
    user_slug: Slug
    first_name: str | None = None
    last_name: str | None = None

    @model_validator(mode="after")
    def has_change(self):
        if not any(getattr(self, key) is not None for key in ('first_name', 'last_name')):
            raise ValueError("Supply at least one field to update")
        return self


class CreateAssignment(_Input):
    operation: Literal['create_assignment'] = Field('create_assignment', title='Create assignment', json_schema_extra={"ui:hidden": True})
    score_set: Slug
    entries: str = Field(..., pattern=r"^[A-Za-z]{8}(?:,[A-Za-z]{8})*$", description="Comma-separated eight-letter slugs, without spaces.")
    judges: str = Field(..., pattern=r"^[A-Za-z]{8}(?:,[A-Za-z]{8})*$", description="Comma-separated eight-letter slugs, without spaces.")
    rounds: str = Field(..., pattern=r"^[A-Za-z]{8}(?:,[A-Za-z]{8})*$", description="Comma-separated eight-letter slugs, without spaces.")


class DeleteAssignment(_Input):
    operation: Literal['delete_assignment'] = Field('delete_assignment', title='Delete assignment', json_schema_extra={"ui:hidden": True})
    assignment_slug: str = Field(..., pattern=r"^[A-Za-z0-9]{24}[JR]$")


Operation = Annotated[Union[GetAccount, ListEntries, GetEntry, ListUsers, ListCategories, GetCategory, ListSeasons, GetSeason, ListRounds, GetRound, ListScoreSets, GetScoreSet, ListAssignments, GetAssignment, CreateEntry, UpdateEntry, DeleteEntry, TagEntry, UntagEntry, UpdateEntryTitle, UpdateEntryField, UpdateUser, CreateAssignment, DeleteAssignment], Field(discriminator="operation")]


class AwardForceConfig(NodeConfig[Operation, AwardForceAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


OPERATIONS = {'get_account': {'method': 'GET',
                 'path': '/account',
                 'expected': 200,
                 'query': [],
                 'body': [],
                 'convert': {}},
 'list_entries': {'method': 'GET',
                  'path': '/entry',
                  'expected': 200,
                  'query': ['page',
                            'per_page',
                            'entrant',
                            'status',
                            'title',
                            'updated_at',
                            'category',
                            'chapter',
                            'season',
                            'tag'],
                  'body': [],
                  'convert': {}},
 'get_entry': {'method': 'GET',
               'path': '/entry/{entry_slug}',
               'expected': 200,
               'query': [],
               'body': [],
               'convert': {}},
 'list_users': {'method': 'GET',
                'path': '/user',
                'expected': 200,
                'query': ['page', 'per_page'],
                'body': [],
                'convert': {}},
 'list_categories': {'method': 'GET',
                     'path': '/category',
                     'expected': 200,
                     'query': ['page', 'per_page', 'status', 'chapter', 'season'],
                     'body': [],
                     'convert': {}},
 'get_category': {'method': 'GET',
                  'path': '/category/{category_slug}',
                  'expected': 200,
                  'query': [],
                  'body': [],
                  'convert': {}},
 'list_seasons': {'method': 'GET',
                  'path': '/season',
                  'expected': 200,
                  'query': ['page', 'per_page'],
                  'body': [],
                  'convert': {}},
 'get_season': {'method': 'GET',
                'path': '/season/{season_slug}',
                'expected': 200,
                'query': [],
                'body': [],
                'convert': {}},
 'list_rounds': {'method': 'GET',
                 'path': '/round',
                 'expected': 200,
                 'query': ['page', 'per_page', 'season'],
                 'body': [],
                 'convert': {}},
 'get_round': {'method': 'GET',
               'path': '/round/{round_slug}',
               'expected': 200,
               'query': [],
               'body': [],
               'convert': {}},
 'list_score_sets': {'method': 'GET',
                     'path': '/score-set',
                     'expected': 200,
                     'query': ['page', 'per_page', 'season'],
                     'body': [],
                     'convert': {}},
 'get_score_set': {'method': 'GET',
                   'path': '/score-set/{score_set_slug}',
                   'expected': 200,
                   'query': [],
                   'body': [],
                   'convert': {}},
 'list_assignments': {'method': 'GET',
                      'path': '/assignment',
                      'expected': 200,
                      'query': ['page',
                                'per_page',
                                'status',
                                'category',
                                'chapter',
                                'judge',
                                'score_set',
                                'season',
                                'tag'],
                      'body': [],
                      'convert': {}},
 'get_assignment': {'method': 'GET',
                    'path': '/assignment/{assignment_slug}',
                    'expected': 200,
                    'query': [],
                    'body': [],
                    'convert': {}},
 'create_entry': {'method': 'POST',
                  'path': '/entry',
                  'expected': 201,
                  'query': [],
                  'body': ['category',
                           'chapter',
                           'entrant',
                           'season',
                           'title',
                           'form',
                           'status',
                           'moderation_status',
                           'entry_fields_json'],
                  'convert': {'entry_fields_json': 'entry_fields'}},
 'update_entry': {'method': 'PUT',
                  'path': '/entry/{entry_slug}',
                  'expected': 200,
                  'query': [],
                  'body': ['category',
                           'chapter',
                           'entrant',
                           'title',
                           'status',
                           'moderation_status',
                           'entry_fields_json'],
                  'convert': {'entry_fields_json': 'entry_fields'}},
 'delete_entry': {'method': 'DELETE',
                  'path': '/entry/{entry_slug}',
                  'expected': 204,
                  'query': [],
                  'body': [],
                  'convert': {}},
 'tag_entry': {'method': 'PUT',
               'path': '/entry/{entry_slug}/tag/{tags}',
               'expected': 201,
               'query': [],
               'body': [],
               'convert': {}},
 'untag_entry': {'method': 'DELETE',
                 'path': '/entry/{entry_slug}/tag/{tags}',
                 'expected': 201,
                 'query': [],
                 'body': [],
                 'convert': {}},
 'update_entry_title': {'method': 'PUT',
                        'path': '/entry/{entry_slug}/update-title',
                        'expected': 200,
                        'query': [],
                        'body': ['title'],
                        'convert': {}},
 'update_entry_field': {'method': 'PUT',
                        'path': '/entry/{entry_slug}/update-field/{field_slug}',
                        'expected': 200,
                        'query': [],
                        'body': ['value_json'],
                        'convert': {'value_json': 'value'}},
 'update_user': {'method': 'PUT',
                 'path': '/user/{user_slug}',
                 'expected': 200,
                 'query': [],
                 'body': ['first_name', 'last_name'],
                 'convert': {}},
 'create_assignment': {'method': 'POST',
                       'path': '/assignment',
                       'expected': 202,
                       'query': [],
                       'body': ['score_set', 'entries', 'judges', 'rounds'],
                       'convert': {'entries': 'split', 'judges': 'split', 'rounds': 'split'}},
 'delete_assignment': {'method': 'DELETE',
                       'path': '/assignment/{assignment_slug}',
                       'expected': 204,
                       'query': [],
                       'body': [],
                       'convert': {}}}


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(x, secret) for x in value]
    if isinstance(value, dict):
        return {k: _redact(v, secret) for k, v in value.items()}
    return value


class AwardForceNode(WorkflowNode):
    integration_type = "automation-award-force"
    connection_evidence = ConnectionEvidence(noun="account", identity_operation="get_account")

    @classmethod
    def get_config_model(cls):
        return AwardForceConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an Award Force API key")
        credential = self.config.credentials
        config = self.config.config
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True)
        path = spec["path"]
        for key, value in values.items():
            path = path.replace("{" + key + "}", quote(str(value), safe=""))
        params = {key: values[key] for key in spec["query"] if key in values}
        body = {}
        for key in spec["body"]:
            if key not in values:
                continue
            value = values[key]
            target = spec["convert"].get(key, key)
            if target == "split":
                value, target = value.split(","), key
            elif key.endswith("_json"):
                value = json.loads(value)
            body[target] = value
        method = spec["method"]
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, f"https://api.{credential.region}.cr4ce.com" + path,
                    headers={"x-api-key": credential.api_key, "Accept": ACCEPT}, params=params,
                    **({"json": body} if spec["body"] else {}))
            if response.status_code != spec["expected"]:
                # Preserve provider rejection text for the connect seam, with the key redacted.
                return await self._finish({"status": "error", "status_code": response.status_code,
                    "message": response.text[:2000], "write_outcome": "unverified" if method != "GET" else None}, credential.api_key)
            if response.status_code in {202, 204}:
                result = {"accepted": True} if response.status_code == 202 else {"deleted": True}
            else:
                payload = response.json()
                if not isinstance(payload, dict) or payload.get("error") or payload.get("errors"):
                    raise ValueError("Unexpected Award Force response")
                if config.operation.startswith("list_"):
                    if not isinstance(payload.get("data"), list):
                        raise ValueError("Award Force did not return a resource list")
                    # Never follow API-returned URLs: advance the bounded page parameter only.
                    current, last = payload.get("current_page"), payload.get("last_page")
                    next_page = current + 1 if type(current) is int and type(last) is int and current < last else None
                    result = {"data": payload["data"], "pagination": {k: v for k, v in payload.items() if k != "data"},
                        "next_page": next_page, "has_more": next_page is not None}
                else:
                    result = {"data": payload}
            return await self._finish({"status": "success", "status_code": response.status_code, **result}, credential.api_key)
        except (httpx.HTTPError, ValueError):
            return await self._finish({"status": "error", "message": "Award Force response could not be verified",
                "write_outcome": "unverified" if method != "GET" else None}, credential.api_key)

    async def _finish(self, output, secret):
        output = _redact(output, secret)
        await self.emit(output)
        return output
