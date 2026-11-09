"""Sidetracker operations from its published v1 OpenAPI contract.

Requests stay on the fixed provider origin and return one provider response per
operation. Endpoints without documented write payloads are deliberately omitted.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.sidetracker.io"


class SidetrackerTokenCredential(BaseModel):
    model_config = ConfigDict(title="Sidetracker API Token", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://app.sidetracker.io/api/schema",
            "x-credential-instructions": "Paste your Sidetracker API token without the Token prefix. NoClick sends it only to app.sidetracker.io. The connection check reads your account's lists.",
        })
    credential_type: Literal["sidetracker_api_token"] = Field("sidetracker_api_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., title="API Token", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without a prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def path_segment(cls, value, info):
        if info.field_name.endswith("_id") and value in (".", ".."):
            raise ValueError("Use a resource ID, not a relative path")
        return value


class SidetrackerListListsConfig(_Input):
    operation: Literal['list_lists'] = Field('list_lists', title='Retrieve all lists', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, le=1000000, description='The page number to retrieve.')
    page_size: int = Field(100, ge=1, le=500, description='The number of items per page.')

class SidetrackerGetListConfig(_Input):
    operation: Literal['get_list'] = Field('get_list', title='Retrieve list by id', json_schema_extra={"ui:hidden": True})
    unique_id: str = Field(..., title='Unique Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")

class SidetrackerCreateListConfig(_Input):
    operation: Literal['create_list'] = Field('create_list', title='Create a list', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., title="List Name", min_length=1, max_length=255)
    description: str | None = Field(None, min_length=1, title="Description")
    preset: Literal["tracking", "checks"] = Field(..., title="Preset")
    columns: list[str] = Field(..., title="Columns", min_length=1,
        description="Column names allowed by the selected preset, as listed in the Sidetracker API contract.")

    @field_validator("columns")
    @classmethod
    def nonempty_columns(cls, value):
        if any(not column for column in value):
            raise ValueError("Column names must not be empty")
        return value

    @model_validator(mode="after")
    def preset_columns(self):
        tracking = set("SessionID DomainName DomainID Name Description SalesStatus FirstName LastName RegistrationNumber VATNumber IBAN AddressLine1 AddressLine2 HouseNumber Suffix City StateProvinceRegion PostalCode Country PhoneNumber Website Email DateTime Date Time TrackData MetaData IpAddress Browser Device CurrentPage Referrer ReferrerParams EntryPoint Message LastNote ConversionLabel CampaignName CampaignID AdGroupName AdGroupID Keyword KeywordMatchType AdName AdDevice AdNetwork SubjectID Revenue OrderNumber EventKey EventValue EventDescription EventElementType TriggerID EventID Journey ReferrerLabel".split())
        allowed = tracking if self.preset == "tracking" else {"CheckID", "PageURL", "TriggerID", "EventID", "Message"}
        if set(self.columns) - allowed:
            raise ValueError("Columns must belong to the selected Sidetracker preset")
        return self

class SidetrackerDeleteListConfig(_Input):
    operation: Literal['delete_list'] = Field('delete_list', title='Delete list by id', json_schema_extra={"ui:hidden": True})
    unique_id: str = Field(..., title='Unique Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")

class SidetrackerGetRowConfig(_Input):
    operation: Literal['get_row'] = Field('get_row', title='Get row from list', json_schema_extra={"ui:hidden": True})
    row_id: str = Field(..., title='Row Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")
    unique_id: str = Field(..., title='Unique Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")

class SidetrackerDeleteRowConfig(_Input):
    operation: Literal['delete_row'] = Field('delete_row', title='Delete row from list', json_schema_extra={"ui:hidden": True})
    row_id: str = Field(..., title='Row Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")
    unique_id: str = Field(..., title='Unique Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")

class SidetrackerDeleteRowBySessionConfig(_Input):
    operation: Literal['delete_row_by_session'] = Field('delete_row_by_session', title='Delete row from list by session id', json_schema_extra={"ui:hidden": True})
    session_id: str = Field(..., title='Session Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")
    unique_id: str = Field(..., title='Unique Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")

class SidetrackerListConversionsConfig(_Input):
    operation: Literal['list_conversions'] = Field('list_conversions', title='Retrieve converted sessions', json_schema_extra={"ui:hidden": True})
    attribution: str | None = Field(None, max_length=4096, description='`0` to omit the attribution block. On by default, which caps `page_size` at 100.')
    converted: str | None = Field(None, max_length=4096, description='`yes` or `no` -- whether the session has revenue recorded against it.')
    daterange: str | None = Field(None, max_length=4096, description='Range over the conversion date, e.g. `2026-08-01 to 2026-08-20`.')
    domain_id: str | None = Field(None, max_length=4096, description='Limit to one tracked domain (its unique id). Faster than the account-wide list.')
    include_hidden: str | None = Field(None, max_length=4096, description='`1` to also return SPAM, which is hidden by default.')
    label: list[str] | None = Field(None, description='Repeatable. Referrer label name.')
    lookback: str | None = Field(None, max_length=4096, description='Attribution window in days: `30`, `60`, `90` (default) or `all`.')
    model: str | None = Field(None, max_length=4096, description='Attribution model: `last_click` (default), `first_click`, `linear`, `position_based`, `time_decay`.')
    order: str | None = Field(None, max_length=4096, description='`converted_at` (default) or `id`. Use `id` to page through the whole list.')
    page: int = Field(1, ge=1, le=1000000, description='The page number to retrieve.')
    page_size: int = Field(100, ge=1, le=500, description='Items per page. Clamped to 500, or 100 when attribution is on.')
    sales_status: list[str] | None = Field(None, description="Repeatable. Stored status names, e.g. `CUSTOMER`. Repeated values are OR'd; unknown ones are ignored.")
    search: str | None = Field(None, max_length=4096, description='Free text over name, session id and the Google Ads campaign behind the session (campaign, ad group, keyword, ad, device, network). Also `meta:<key>`, `data:<key>` and `status:<STATUS>`.')
    tab: str | None = Field(None, max_length=4096, description='`all` (default), `inbox` for unarchived sessions, or `archived`.')
    tag: list[str] | None = Field(None, description='Repeatable. Tag name.')
    updated_since: str | None = Field(None, max_length=4096, description='ISO 8601. Only sessions changed at or after this moment, for incremental syncing.')

class SidetrackerGetSessionConfig(_Input):
    operation: Literal['get_session'] = Field('get_session', title='Retrieve tracker session by id', json_schema_extra={"ui:hidden": True})
    session_id: str = Field(..., title='Session Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")

class SidetrackerDeleteSessionConfig(_Input):
    operation: Literal['delete_session'] = Field('delete_session', title='Delete tracker session by id', json_schema_extra={"ui:hidden": True})
    session_id: str = Field(..., title='Session Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")

class SidetrackerGetNoteConfig(_Input):
    operation: Literal['get_note'] = Field('get_note', title='Retrieve tracker note by id', json_schema_extra={"ui:hidden": True})
    note_id: str = Field(..., title='Note Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")
    session_id: str = Field(..., title='Session Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")

class SidetrackerDeleteNoteConfig(_Input):
    operation: Literal['delete_note'] = Field('delete_note', title='Delete a note', json_schema_extra={"ui:hidden": True})
    note_id: str = Field(..., title='Note Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")
    session_id: str = Field(..., title='Session Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")

class SidetrackerListNotesConfig(_Input):
    operation: Literal['list_notes'] = Field('list_notes', title='Retrieve all notes for tracker', json_schema_extra={"ui:hidden": True})
    session_id: str = Field(..., title='Session Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")

class SidetrackerGetVisitConfig(_Input):
    operation: Literal['get_visit'] = Field('get_visit', title='Retrieve session visit by id', json_schema_extra={"ui:hidden": True})
    session_id: str = Field(..., title='Session Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")
    unique_id: str = Field(..., title='Unique Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")

class SidetrackerDeleteVisitConfig(_Input):
    operation: Literal['delete_visit'] = Field('delete_visit', title='Delete session visit by id', json_schema_extra={"ui:hidden": True})
    session_id: str = Field(..., title='Session Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")
    unique_id: str = Field(..., title='Unique Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")

class SidetrackerListVisitsConfig(_Input):
    operation: Literal['list_visits'] = Field('list_visits', title='Retrieve all visits for a session', json_schema_extra={"ui:hidden": True})
    page: int = Field(1, ge=1, le=1000000, description='The page number to retrieve.')
    page_size: int = Field(100, ge=1, le=500, description='The number of items per page.')
    session_id: str = Field(..., title='Session Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")

class SidetrackerListSessionsConfig(_Input):
    operation: Literal['list_sessions'] = Field('list_sessions', title='Retrieve all sessions for domain tracker', json_schema_extra={"ui:hidden": True})
    domain_id: str = Field(..., title='Domain Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")
    page: int = Field(1, ge=1, le=1000000, description='The page number to retrieve.')
    page_size: int = Field(100, ge=1, le=500, description='The number of items per page.')

class SidetrackerExecuteTriggerConfig(_Input):
    operation: Literal['execute_trigger'] = Field('execute_trigger', title='Execute a trigger', json_schema_extra={"ui:hidden": True})
    session_id: str = Field(..., title='Session Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")
    unique_id: str = Field(..., title='Unique Id', min_length=1, max_length=512, pattern=r"^[^\x00-\x20\x7f]+$")

class SidetrackerGetAccountConfig(_Input):
    operation: Literal['get_account'] = Field('get_account', title='Get Account', json_schema_extra={"ui:hidden": True})


SidetrackerConfig = Annotated[Union[
    SidetrackerListListsConfig,
    SidetrackerGetListConfig,
    SidetrackerCreateListConfig,
    SidetrackerDeleteListConfig,
    SidetrackerGetRowConfig,
    SidetrackerDeleteRowConfig,
    SidetrackerDeleteRowBySessionConfig,
    SidetrackerListConversionsConfig,
    SidetrackerGetSessionConfig,
    SidetrackerDeleteSessionConfig,
    SidetrackerGetNoteConfig,
    SidetrackerDeleteNoteConfig,
    SidetrackerListNotesConfig,
    SidetrackerGetVisitConfig,
    SidetrackerDeleteVisitConfig,
    SidetrackerListVisitsConfig,
    SidetrackerListSessionsConfig,
    SidetrackerExecuteTriggerConfig,
    SidetrackerGetAccountConfig
], Field(discriminator="operation")]


class SidetrackerFullConfig(NodeConfig[SidetrackerConfig, SidetrackerTokenCredential]):
    pass


ROUTES = {'list_lists': ('GET', '/api/lists', 200),
 'get_list': ('GET', '/api/lists/{unique_id}', 200),
 'create_list': ('POST', '/api/lists/create', 201),
 'delete_list': ('DELETE', '/api/lists/{unique_id}/delete', 204),
 'get_row': ('GET', '/api/lists/{unique_id}/get/row/{row_id}', 200),
 'delete_row': ('DELETE', '/api/lists/{unique_id}/delete/row/{row_id}', 204),
 'delete_row_by_session': ('DELETE', '/api/lists/{unique_id}/delete/row/session/{session_id}', 204),
 'list_conversions': ('GET', '/api/tracking/conversions', 200),
 'get_session': ('GET', '/api/tracking/session/{session_id}/get', 200),
 'delete_session': ('DELETE', '/api/tracking/session/{session_id}/delete', 204),
 'get_note': ('GET', '/api/tracking/session/{session_id}/note/{note_id}/get', 200),
 'delete_note': ('DELETE', '/api/tracking/session/{session_id}/note/{note_id}/delete', 204),
 'list_notes': ('GET', '/api/tracking/session/{session_id}/notes', 200),
 'get_visit': ('GET', '/api/tracking/session/{session_id}/visit/{unique_id}/get', 200),
 'delete_visit': ('DELETE', '/api/tracking/session/{session_id}/visit/{unique_id}/delete', 204),
 'list_visits': ('GET', '/api/tracking/session/{session_id}/visits', 200),
 'list_sessions': ('GET', '/api/tracking/sessions/{domain_id}', 200),
 'execute_trigger': ('POST', '/api/triggers/{session_id}/execute/{unique_id}', 200),
 'get_account': ('GET', '/api/zapier_api/me', 200)}


class SidetrackerNode(WorkflowNode):
    integration_type = "automation-sidetracker"
    connection_evidence = ConnectionEvidence(noun="Sidetracker lists", operation="list_lists", label_keys=("name", "id", "unique_id"))

    @classmethod
    def get_config_model(cls):
        return SidetrackerFullConfig

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if not self.config.credentials:
            raise ValueError("Connect a Sidetracker API token")
        config = self.config.config
        method, path, expected_status = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        for name in tuple(values):
            marker = "{" + name + "}"
            if marker in path:
                path = path.replace(marker, quote(str(values.pop(name)), safe=""))
        kwargs = {"params": values}
        if config.operation == "create_list":
            # The contract requires preset in both the query and JSON schema.
            kwargs = {"params": {"preset": config.preset}, "json": values}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path,
                headers={"Authorization": "Token " + self.config.credentials.api_token, "Accept": "application/json"},
                **kwargs)
        response.raise_for_status()
        if response.status_code != expected_status:
            raise ValueError("Sidetracker returned an unexpected HTTP status")
        if response.status_code == 204 or not response.content:
            body = None
        else:
            body = response.json()
            if isinstance(body, dict) and (body.get("error") or body.get("status") in ("error", "failed")):
                raise ValueError("Sidetracker returned an error response")
        return {"status": "success", "operation": config.operation, "data": body,
            "http_status": response.status_code}
