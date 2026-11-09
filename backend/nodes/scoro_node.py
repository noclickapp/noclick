"""Scoro API v4 contacts, work and sales operations.

Official contract: https://api.scoro.com/api/v4/reference/openapi (version 4).
Each action makes exactly one request. List operations return one page, with an
explicit continuation; nested task time entries are unpaginated. Writes send
only supplied values, preserve false/zero, and never retry creates implicitly.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Annotated, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    create_model,
    field_validator,
    model_validator,
)

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.oauth.scoro_oauth import COMPANY_ACCOUNT, OAUTH_PROVIDER, SITE_HOST
from nodes.scopes.scoro import SCORO_SCOPES
from nodes.scoro_operations import SCORO_OPERATIONS
from utils.ssrf import guarded_async_client


class ScoroOAuthCredential(BaseModel):
    model_config = ConfigDict(
        title="Scoro OAuth",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "scoro",
            "x-oauth-scopes": SCORO_SCOPES.declared_scopes(),
            "x-credential-url": "https://developers.scoro.com/login",
            "x-credential-instructions": "Connect your Scoro site with OAuth, or paste an existing v4 access token and its site host. Copy the string company account ID from Settings > Integrations > API; it is not a CRM company ID. Refresh token and expiry are optional when connecting an existing access token.",
        },
    )
    credential_type: Literal["scoro_oauth"] = Field(
        "scoro_oauth", json_schema_extra={"ui:hidden": True}
    )
    site_host: str = Field(
        ..., title="Scoro site host", description="For example acme.scoro.com"
    )
    company_account_id: str = Field(
        ...,
        title="Company account ID",
        description="String account ID from Settings > Integrations > API",
    )
    access_token: str = Field(
        ...,
        min_length=1,
        title="Access token",
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )
    refresh_token: str | None = Field(
        None,
        title="Refresh token",
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )
    expires_at: str | None = Field(
        None, title="Token expiry", description="ISO 8601 expiry returned by OAuth"
    )

    @field_validator("site_host", mode="before")
    @classmethod
    def host(cls, value):
        return SITE_HOST.validate(value)

    @field_validator("company_account_id", mode="before")
    @classmethod
    def account(cls, value):
        return COMPANY_ACCOUNT.validate(value)

    @field_validator("access_token", "refresh_token")
    @classmethod
    def token(cls, value):
        if value is None:
            return None
        value = clean_secret(value, field_name="Token", key=True)
        if not value or any(c.isspace() for c in value):
            raise ValueError("Paste the token without a Bearer prefix or whitespace")
        return value


def picker(entity):
    return {
        "x-dynamic-options": {
            "field_name": entity + "_id",
            "searchable": False,
            "allow_custom": True,
        }
    }


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class _Page(_Input):
    page: int = Field(
        1, ge=1, description="Page number; use next_page from the previous result"
    )
    per_page: int = Field(
        20, ge=1, le=100, description="Items per page, sent as perPage"
    )
    sort: str | None = Field(
        None,
        description="Up to three documented sort keys, comma-separated; prefix - for descending",
    )
    filters_json: str | None = Field(
        None,
        title="Filters (JSON)",
        description='Documented filters object, for example {"modifiedDateTime":{"from":"2026-01-01T00:00:00Z"}}',
        json_schema_extra={"ui:widget": "textarea"},
    )


class _Write(_Input):
    custom_fields_json: str | None = Field(
        None, title="Custom fields (JSON)", json_schema_extra={"ui:widget": "textarea"}
    )

    @model_validator(mode="after")
    def nonempty_update(self):
        values = self.model_dump(exclude_none=True)
        if values.get("operation", "").startswith("update_"):
            keys = set(values) - {
                "operation",
                values["operation"].removeprefix("update_") + "_id",
            }
            if not keys:
                raise ValueError("Supply at least one field to update")
        return self


class _Company(_Write):
    company_name: str | None = None
    registration_code: str | None = None
    tax_code: str | None = None
    comments: str | None = None
    manager_id: int | None = None
    is_client: bool | None = None
    is_supplier: bool | None = None
    means_of_contact_json: str | None = Field(
        None,
        title="Contact methods (JSON)",
        json_schema_extra={"ui:widget": "textarea"},
    )


class _Person(_Write):
    first_name: str | None = None
    last_name: str | None = None
    job_title: str | None = None
    comments: str | None = None
    manager_id: int | None = None
    means_of_contact_json: str | None = Field(
        None,
        title="Contact methods (JSON)",
        json_schema_extra={"ui:widget": "textarea"},
    )
    related_company_ids_json: str | None = Field(
        None,
        title="Related company IDs (JSON)",
        description="Replaces all company relations; send the complete array",
        json_schema_extra={"ui:widget": "textarea"},
    )


class _Project(_Write):
    name: str | None = None
    description: str | None = None
    company_id: int | None = Field(None, json_schema_extra=picker("company"))
    manager_id: int | None = None
    status: str | None = None
    start_date: date | None = None
    due_date: date | None = None
    budget_type: Literal["simple", "advanced", "quote"] | None = None
    revenue_calc_model: Literal["fixed_fee", "tm_capped", "tm_not_capped"] | None = None
    project_type: Literal["regular", "retainer", "internal"] | None = None


class _Task(_Write):
    name: str | None = None
    description: str | None = None
    project_id: int | None = Field(None, json_schema_extra=picker("project"))
    company_id: int | None = Field(None, json_schema_extra=picker("company"))
    responsible_user_id: int | None = None
    priority_id: Literal[1, 2, 3] | None = None
    start_date: date | None = None
    due_date_time: datetime | None = None
    duration_planned: int | None = Field(None, ge=0, description="Seconds")
    is_done: bool | None = None
    status: str | None = None

    @field_validator("due_date_time")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Include a timezone offset")
        return value


class _Sales(_Write):
    client_id: int = Field(
        ..., ge=1, description="Client company ID", json_schema_extra=picker("company")
    )
    date: date
    description: str | None = None
    currency: str | None = Field(None, min_length=3, max_length=3)
    project_id: int | None = Field(None, json_schema_extra=picker("project"))
    lines_json: str | None = Field(
        None,
        title="Line items (JSON)",
        description="Array of documented line items: productId, description, price, quantity. Scoro calculates totals.",
        json_schema_extra={"ui:widget": "textarea"},
    )


class _TimeEntry(_Input):
    duration: int = Field(
        ...,
        ge=0,
        description="Duration in seconds, rounded to the nearest minute by Scoro",
    )
    description: str | None = None
    user_id: int | None = None
    start_date_time: datetime | None = None
    billable_time_type: Literal["billable", "non_billable", "custom"] | None = None

    @field_validator("start_date_time")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Include a timezone offset")
        return value


_WRITES = {
    "company": _Company,
    "person": _Person,
    "project": _Project,
    "task": _Task,
    "quote": _Sales,
    "invoice": _Sales,
    "time_entry": _TimeEntry,
}
_REQUIRED = {
    "company": {"company_name": (str, Field(..., min_length=1))},
    "person": {"first_name": (str, Field(..., min_length=1))},
    "project": {
        "name": (str, Field(..., min_length=1)),
        "company_id": (int, Field(..., ge=1, json_schema_extra=picker("company"))),
    },
    "task": {"name": (str, Field(..., min_length=1))},
}


def _model(name, spec):
    title = name.replace("_", " ").title()
    fields = {
        "operation": (
            Literal[name],
            Field(
                name,
                title=title,
                json_schema_extra={
                    "ui:hidden": True,
                    "x-display-name": title,
                    "x-category": spec["category"],
                },
            ),
        )
    }
    base = _Input
    if spec["method"] in {"POST", "PATCH"}:
        base = _WRITES[spec["entity"]]
        if name.startswith("create_"):
            fields.update(_REQUIRED.get(spec["entity"], {}))
    elif name.startswith("list_") and spec["entity"] != "time_entry":
        base = _Page
    if "{id}" in spec["path"] or "{taskId}" in spec["path"]:
        entity = "task" if spec["entity"] == "time_entry" else spec["entity"]
        fields[entity + "_id"] = (
            int,
            Field(..., ge=1, json_schema_extra=picker(entity)),
        )
    return create_model(
        "Scoro" + title.replace(" ", "") + "Config",
        __base__=base,
        __doc__=title,
        **fields,
    )


SCORO_CONFIGS = {name: _model(name, spec) for name, spec in SCORO_OPERATIONS.items()}
ScoroConfig = Annotated[
    Union[tuple(SCORO_CONFIGS.values())], Field(discriminator="operation")
]


class ScoroNodeConfig(NodeConfig[ScoroConfig, ScoroOAuthCredential]):
    """Scoro operation and tenant-bound credential."""


def _camel(name):
    head, *tail = name.split("_")
    return head + "".join(word.title() for word in tail)


def _json(raw, kind):
    value = json.loads(raw)
    if not isinstance(value, kind):
        raise ValueError("Use a JSON " + ("array" if kind is list else "object"))
    return value


def _filter_pairs(value, prefix="filters"):
    if isinstance(value, dict):
        for key, child in value.items():
            if not key or any(c in key for c in "[]"):
                raise ValueError("Filter keys must be property names without brackets")
            yield from _filter_pairs(child, f"{prefix}[{key}]")
    elif isinstance(value, list):
        for child in value:
            yield from _filter_pairs(child, prefix + "[]")
    elif value is not None:
        yield prefix, str(value).lower() if isinstance(value, bool) else str(value)


class ScoroNode(WorkflowNode):
    integration_type = "automation-scoro"
    scope_registry = SCORO_SCOPES
    connection_evidence = ConnectionEvidence(
        field="company_id",
        noun="companies",
        identity_operation="get_current_user",
        identity_keys=("firstName", "email"),
    )

    @classmethod
    def get_config_model(cls):
        return ScoroNodeConfig

    @classmethod
    async def freshen_credential(
        cls, credential_data, *, pool=None, user_id=None, credential_id=None
    ):
        from nodes.core.oauth_refresh import freshen_oauth_credential

        return await freshen_oauth_credential(
            credential_data,
            pool=pool,
            user_id=user_id,
            credential_id=credential_id,
            refresh=OAUTH_PROVIDER.bind_refresh(credential_data),
            additional_token_fields=OAUTH_PROVIDER.credential_fields,
            provider="scoro",
        )

    @classmethod
    async def load_field_options(
        cls,
        field_name,
        credential_data=None,
        context=None,
        page_token=None,
        search=None,
    ):
        resources = {
            "company_id": ("list_companies", "companyName"),
            "person_id": ("list_persons", "firstName"),
            "project_id": ("list_projects", "name"),
            "task_id": ("list_tasks", "name"),
            "quote_id": ("list_quotes", "number"),
            "invoice_id": ("list_invoices", "number"),
        }
        if field_name not in resources:
            raise ValueError("Unknown Scoro choice field")
        if search:
            raise ValueError("Scoro choices do not support free text search")
        operation, label = resources[field_name]
        page = int(page_token) if page_token is not None else 1
        node = cls(
            node_id="scoro-options",
            node_type=cls.integration_type,
            node_data={},
            config=ScoroNodeConfig.model_validate(
                {
                    "config": {"operation": operation, "page": page, "per_page": 100},
                    "credentials": credential_data,
                }
            ),
        )
        result = await node.execute({})
        return {
            "options": [
                {"value": str(row["id"]), "label": str(row.get(label) or row["id"])}
                for row in result["data"]
            ],
            "next_page_token": str(result["next_page"])
            if result.get("next_page")
            else None,
        }

    async def execute(self, inputs):
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token

        if not isinstance(self.config, ScoroNodeConfig) or not self.config.credentials:
            raise ValueError("Connect a Scoro account")
        credential = self.config.credentials
        context = OAUTH_PROVIDER.validate_context(
            {key: getattr(credential, key) for key in OAUTH_PROVIDER.context_fields}
        )
        config = self.config.config
        operation = config.operation
        spec = SCORO_OPERATIONS[operation]
        self.scope_registry.require(operation)
        values = config.model_dump(mode="json", exclude_none=True)
        path = spec["path"]
        path_key = (
            "task_id" if spec["entity"] == "time_entry" else spec["entity"] + "_id"
        )
        if "{" in path:
            path = path.replace(
                "{taskId}" if spec["entity"] == "time_entry" else "{id}",
                str(values.pop(path_key)),
            )
        values.pop("operation")
        params = []
        body = None
        if isinstance(config, _Page):
            params = [("page", config.page), ("perPage", config.per_page)]
            if config.sort:
                params.append(("sort", config.sort))
            if config.filters_json:
                params.extend(_filter_pairs(_json(config.filters_json, dict)))
        elif spec["method"] in {"POST", "PATCH"}:
            body = {}
            for key, value in values.items():
                if key.endswith("_json"):
                    name = key[:-5]
                    value = _json(
                        value,
                        list if name in {"lines", "related_company_ids"} else dict,
                    )
                else:
                    name = key
                body[_camel(name)] = value
            if not body:
                raise ValueError("Supply at least one field to write")
        cred_dict = credential.model_dump()
        token = await ensure_fresh_oauth_token(
            credential_id=(self.node_data or {}).get("credential_id"),
            user_id=self.user_id,
            credential=cred_dict,
            refresh=OAUTH_PROVIDER.bind_refresh(cred_dict),
            additional_token_fields=OAUTH_PROVIDER.credential_fields,
            provider="scoro",
            caller_path="execute",
        )
        for key in ("access_token", "refresh_token", "expires_at"):
            setattr(credential, key, cred_dict.get(key))
        async with guarded_async_client(
            timeout=30, follow_redirects=False, trust_env=False
        ) as client:
            response = await client.request(
                spec["method"],
                f"https://{context['site_host']}{path}",
                params=params,
                **({"json": body} if body is not None else {}),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Scoro-Company-Account": context["company_account_id"],
                    "Accept": "application/json",
                },
            )
        if response.status_code >= 300:
            raise ValueError(
                f"Scoro API error (HTTP {response.status_code}): {response.text}"
            )
        payload = response.json() if response.content else None
        result = {"status": "success", "action": operation, "data": payload}
        if isinstance(config, _Page):
            if not isinstance(payload, list):
                raise ValueError("Scoro returned an unexpected list response")
            result["next_page"] = (
                config.page + 1 if len(payload) == config.per_page else None
            )
        return result
