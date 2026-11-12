"""Crunchbase REST v4 lookup and search operations.

All operations read licensed Crunchbase data; POST searches do not mutate it.
Contract: https://data.crunchbase.com/openapi/firmographic.yaml (1.1.0),
plus financial packages for funding, investment and acquisition collections.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union
from uuid import UUID

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    Json,
    field_validator,
    model_validator,
)

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.crunchbase_operations import (
    FIELD_IDS,
    OrganizationField,
    PersonField,
    FundingRoundField,
    AcquisitionField,
    InvestmentField,
    FundField,
    IpoField,
    EventField,
    JobField,
    LocationField,
    PREDICATES,
    OrganizationFilterField,
    PersonFilterField,
    FundingRoundFilterField,
    AcquisitionFilterField,
    InvestmentFilterField,
    FundFilterField,
    IpoFilterField,
    EventFilterField,
    JobFilterField,
    LocationFilterField,
)
from utils.ssrf import guarded_async_client

BASE = "https://api.crunchbase.com/v4"
CREDENTIAL = "crunchbase_api_key"


class CrunchbaseAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Crunchbase API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://www.crunchbase.com/account/integrations",
            "x-credential-instructions": "Paste your provisioned Crunchbase REST API key. REST API access is licensed separately from an MCP seat. NoClick sends it in X-cb-user-key to api.crunchbase.com. Access to collections and fields depends on your package; connecting checks an organization lookup, not account identity or all collection permissions.",
        },
    )
    credential_type: Literal["crunchbase_api_key"] = Field(
        CREDENTIAL, json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        min_length=1,
        max_length=4096,
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without spaces or a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Lookup(_Input):
    entity_id: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Crunchbase UUID or permalink, such as crunchbase; paste only the identifier.",
    )

    @field_validator("entity_id")
    @classmethod
    def identifier(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,254}", value):
            raise ValueError("Use a single UUID or permalink")
        return value


class _Predicate(_Input):
    type: Literal["predicate"] = "predicate"
    field_id: str
    operator_id: Literal[
        "between",
        "blank",
        "contains",
        "domain_blank",
        "domain_eq",
        "domain_includes",
        "eq",
        "gt",
        "gte",
        "includes",
        "includes_all",
        "lt",
        "lte",
        "not_contains",
        "not_domain_eq",
        "not_domain_includes",
        "not_eq",
        "not_includes",
        "not_includes_all",
        "starts",
    ]
    values: list[str | float | bool] = Field(default_factory=list, max_length=200)


class _Order(_Input):
    field_id: str = Field(..., min_length=1, max_length=100)
    sort: Literal["asc", "desc"] = "asc"
    nulls: Literal["first", "last"] | None = None


class _Search(_Input):
    limit: int = Field(100, ge=1, le=1000, strict=True)
    after_id: UUID | None = Field(
        None,
        description="Last entity UUID from the previous page. Keep filters and ordering unchanged.",
    )
    before_id: UUID | None = Field(
        None,
        description="First entity UUID for the previous page; mutually exclusive with after_id.",
    )
    order: Json[list[_Order]] = Field(
        "[]",
        validate_default=True,
        description="JSON array of field_id and sort objects.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )

    @model_validator(mode="after")
    def valid_search(self):
        if self.after_id and self.before_id:
            raise ValueError("Use only one pagination direction")
        if len(self.query) > 25 or len(self.order) > 10:
            raise ValueError("Use at most 25 predicates and 10 sort fields")
        collection = ROUTES[self.operation][1]
        for predicate in self.query:
            if predicate.operator_id not in PREDICATES[collection][predicate.field_id]:
                raise ValueError(
                    "This operator is not documented for the selected search field"
                )
        for order in self.order:
            if order.field_id not in FIELD_IDS[collection]:
                raise ValueError(
                    "Choose a documented ordering field for this collection"
                )
        return self


class OrganizationLookup(_Lookup):
    operation: Literal["get_organization"] = Field(
        "get_organization",
        title="Get Organization",
        json_schema_extra={"ui:hidden": True},
    )
    field_ids: list[OrganizationField] = Field(
        default_factory=lambda: ["identifier"],
        min_length=1,
        max_length=100,
        description="Fields available across the published packages. Your license must allow them.",
    )


class OrganizationPredicate(_Predicate):
    field_id: OrganizationFilterField


class OrganizationSearch(_Search):
    operation: Literal["search_organizations"] = Field(
        "search_organizations",
        title="Search Organizations",
        json_schema_extra={"ui:hidden": True},
    )
    field_ids: list[OrganizationField] = Field(
        default_factory=lambda: ["identifier"], min_length=1, max_length=100
    )
    query: Json[list[OrganizationPredicate]] = Field(
        "[]",
        validate_default=True,
        description="AND-combined predicates. An empty list requests an unfiltered page.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class PersonLookup(_Lookup):
    operation: Literal["get_person"] = Field(
        "get_person", title="Get Person", json_schema_extra={"ui:hidden": True}
    )
    field_ids: list[PersonField] = Field(
        default_factory=lambda: ["identifier"],
        min_length=1,
        max_length=100,
        description="Fields available across the published packages. Your license must allow them.",
    )


class PersonPredicate(_Predicate):
    field_id: PersonFilterField


class PersonSearch(_Search):
    operation: Literal["search_people"] = Field(
        "search_people", title="Search People", json_schema_extra={"ui:hidden": True}
    )
    field_ids: list[PersonField] = Field(
        default_factory=lambda: ["identifier"], min_length=1, max_length=100
    )
    query: Json[list[PersonPredicate]] = Field(
        "[]",
        validate_default=True,
        description="AND-combined predicates. An empty list requests an unfiltered page.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class FundingRoundLookup(_Lookup):
    operation: Literal["get_funding_round"] = Field(
        "get_funding_round",
        title="Get FundingRound",
        json_schema_extra={"ui:hidden": True},
    )
    field_ids: list[FundingRoundField] = Field(
        default_factory=lambda: ["identifier"],
        min_length=1,
        max_length=100,
        description="Fields available across the published packages. Your license must allow them.",
    )


class FundingRoundPredicate(_Predicate):
    field_id: FundingRoundFilterField


class FundingRoundSearch(_Search):
    operation: Literal["search_funding_rounds"] = Field(
        "search_funding_rounds",
        title="Search Funding Rounds",
        json_schema_extra={"ui:hidden": True},
    )
    field_ids: list[FundingRoundField] = Field(
        default_factory=lambda: ["identifier"], min_length=1, max_length=100
    )
    query: Json[list[FundingRoundPredicate]] = Field(
        "[]",
        validate_default=True,
        description="AND-combined predicates. An empty list requests an unfiltered page.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class AcquisitionLookup(_Lookup):
    operation: Literal["get_acquisition"] = Field(
        "get_acquisition",
        title="Get Acquisition",
        json_schema_extra={"ui:hidden": True},
    )
    field_ids: list[AcquisitionField] = Field(
        default_factory=lambda: ["identifier"],
        min_length=1,
        max_length=100,
        description="Fields available across the published packages. Your license must allow them.",
    )


class AcquisitionPredicate(_Predicate):
    field_id: AcquisitionFilterField


class AcquisitionSearch(_Search):
    operation: Literal["search_acquisitions"] = Field(
        "search_acquisitions",
        title="Search Acquisitions",
        json_schema_extra={"ui:hidden": True},
    )
    field_ids: list[AcquisitionField] = Field(
        default_factory=lambda: ["identifier"], min_length=1, max_length=100
    )
    query: Json[list[AcquisitionPredicate]] = Field(
        "[]",
        validate_default=True,
        description="AND-combined predicates. An empty list requests an unfiltered page.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class InvestmentLookup(_Lookup):
    operation: Literal["get_investment"] = Field(
        "get_investment", title="Get Investment", json_schema_extra={"ui:hidden": True}
    )
    field_ids: list[InvestmentField] = Field(
        default_factory=lambda: ["identifier"],
        min_length=1,
        max_length=100,
        description="Fields available across the published packages. Your license must allow them.",
    )


class InvestmentPredicate(_Predicate):
    field_id: InvestmentFilterField


class InvestmentSearch(_Search):
    operation: Literal["search_investments"] = Field(
        "search_investments",
        title="Search Investments",
        json_schema_extra={"ui:hidden": True},
    )
    field_ids: list[InvestmentField] = Field(
        default_factory=lambda: ["identifier"], min_length=1, max_length=100
    )
    query: Json[list[InvestmentPredicate]] = Field(
        "[]",
        validate_default=True,
        description="AND-combined predicates. An empty list requests an unfiltered page.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class FundLookup(_Lookup):
    operation: Literal["get_fund"] = Field(
        "get_fund", title="Get Fund", json_schema_extra={"ui:hidden": True}
    )
    field_ids: list[FundField] = Field(
        default_factory=lambda: ["identifier"],
        min_length=1,
        max_length=100,
        description="Fields available across the published packages. Your license must allow them.",
    )


class FundPredicate(_Predicate):
    field_id: FundFilterField


class FundSearch(_Search):
    operation: Literal["search_funds"] = Field(
        "search_funds", title="Search Funds", json_schema_extra={"ui:hidden": True}
    )
    field_ids: list[FundField] = Field(
        default_factory=lambda: ["identifier"], min_length=1, max_length=100
    )
    query: Json[list[FundPredicate]] = Field(
        "[]",
        validate_default=True,
        description="AND-combined predicates. An empty list requests an unfiltered page.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class IpoLookup(_Lookup):
    operation: Literal["get_ipo"] = Field(
        "get_ipo", title="Get Ipo", json_schema_extra={"ui:hidden": True}
    )
    field_ids: list[IpoField] = Field(
        default_factory=lambda: ["identifier"],
        min_length=1,
        max_length=100,
        description="Fields available across the published packages. Your license must allow them.",
    )


class IpoPredicate(_Predicate):
    field_id: IpoFilterField


class IpoSearch(_Search):
    operation: Literal["search_ipos"] = Field(
        "search_ipos", title="Search Ipos", json_schema_extra={"ui:hidden": True}
    )
    field_ids: list[IpoField] = Field(
        default_factory=lambda: ["identifier"], min_length=1, max_length=100
    )
    query: Json[list[IpoPredicate]] = Field(
        "[]",
        validate_default=True,
        description="AND-combined predicates. An empty list requests an unfiltered page.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class EventLookup(_Lookup):
    operation: Literal["get_event"] = Field(
        "get_event", title="Get Event", json_schema_extra={"ui:hidden": True}
    )
    field_ids: list[EventField] = Field(
        default_factory=lambda: ["identifier"],
        min_length=1,
        max_length=100,
        description="Fields available across the published packages. Your license must allow them.",
    )


class EventPredicate(_Predicate):
    field_id: EventFilterField


class EventSearch(_Search):
    operation: Literal["search_events"] = Field(
        "search_events", title="Search Events", json_schema_extra={"ui:hidden": True}
    )
    field_ids: list[EventField] = Field(
        default_factory=lambda: ["identifier"], min_length=1, max_length=100
    )
    query: Json[list[EventPredicate]] = Field(
        "[]",
        validate_default=True,
        description="AND-combined predicates. An empty list requests an unfiltered page.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class JobLookup(_Lookup):
    operation: Literal["get_job"] = Field(
        "get_job", title="Get Job", json_schema_extra={"ui:hidden": True}
    )
    field_ids: list[JobField] = Field(
        default_factory=lambda: ["identifier"],
        min_length=1,
        max_length=100,
        description="Fields available across the published packages. Your license must allow them.",
    )


class JobPredicate(_Predicate):
    field_id: JobFilterField


class JobSearch(_Search):
    operation: Literal["search_jobs"] = Field(
        "search_jobs", title="Search Jobs", json_schema_extra={"ui:hidden": True}
    )
    field_ids: list[JobField] = Field(
        default_factory=lambda: ["identifier"], min_length=1, max_length=100
    )
    query: Json[list[JobPredicate]] = Field(
        "[]",
        validate_default=True,
        description="AND-combined predicates. An empty list requests an unfiltered page.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class LocationLookup(_Lookup):
    operation: Literal["get_location"] = Field(
        "get_location", title="Get Location", json_schema_extra={"ui:hidden": True}
    )
    field_ids: list[LocationField] = Field(
        default_factory=lambda: ["identifier"],
        min_length=1,
        max_length=100,
        description="Fields available across the published packages. Your license must allow them.",
    )


class LocationPredicate(_Predicate):
    field_id: LocationFilterField


class LocationSearch(_Search):
    operation: Literal["search_locations"] = Field(
        "search_locations",
        title="Search Locations",
        json_schema_extra={"ui:hidden": True},
    )
    field_ids: list[LocationField] = Field(
        default_factory=lambda: ["identifier"], min_length=1, max_length=100
    )
    query: Json[list[LocationPredicate]] = Field(
        "[]",
        validate_default=True,
        description="AND-combined predicates. An empty list requests an unfiltered page.",
        json_schema_extra={"ui:widget": "code_editor", "x-code-language": "json"},
    )


class Autocomplete(_Input):
    operation: Literal["autocomplete"] = Field(
        "autocomplete",
        title="Autocomplete Identifiers",
        json_schema_extra={"ui:hidden": True},
    )
    query: str = Field(..., min_length=1, max_length=1000)
    collection_ids: list[
        Literal[
            "organizations",
            "people",
            "events",
            "ipos",
            "jobs",
            "locations",
            "categories",
            "category_groups",
        ]
    ] = Field(default_factory=list)
    limit: int = Field(10, ge=1, le=25, strict=True)


# Crunchbase's own MCP server: agents get its tools through a person's Crunchbase sign-in.
CrunchbaseMcpCredential = mcp_credential("crunchbase", "https://mcp.crunchbase.com", app="Crunchbase")
CrunchbaseCredential = Union[CrunchbaseAPIKeyCredential, CrunchbaseMcpCredential]


ROUTES = {
    "get_organization": ("GET", "organizations"),
    "search_organizations": ("POST", "organizations"),
    "get_person": ("GET", "people"),
    "search_people": ("POST", "people"),
    "get_funding_round": ("GET", "funding_rounds"),
    "search_funding_rounds": ("POST", "funding_rounds"),
    "get_acquisition": ("GET", "acquisitions"),
    "search_acquisitions": ("POST", "acquisitions"),
    "get_investment": ("GET", "investments"),
    "search_investments": ("POST", "investments"),
    "get_fund": ("GET", "funds"),
    "search_funds": ("POST", "funds"),
    "get_ipo": ("GET", "ipos"),
    "search_ipos": ("POST", "ipos"),
    "get_event": ("GET", "events"),
    "search_events": ("POST", "events"),
    "get_job": ("GET", "jobs"),
    "search_jobs": ("POST", "jobs"),
    "get_location": ("GET", "locations"),
    "search_locations": ("POST", "locations"),
    "autocomplete": ("GET", "autocompletes"),
}

CrunchbaseConfig = Annotated[
    Union[
        OrganizationLookup,
        OrganizationSearch,
        PersonLookup,
        PersonSearch,
        FundingRoundLookup,
        FundingRoundSearch,
        AcquisitionLookup,
        AcquisitionSearch,
        InvestmentLookup,
        InvestmentSearch,
        FundLookup,
        FundSearch,
        IpoLookup,
        IpoSearch,
        EventLookup,
        EventSearch,
        JobLookup,
        JobSearch,
        LocationLookup,
        LocationSearch,
        Autocomplete,
    ],
    Field(discriminator="operation"),
]


class CrunchbaseFullConfig(NodeConfig[CrunchbaseConfig, CrunchbaseCredential]):
    @model_validator(mode="before")
    @classmethod
    def credential_family(cls, value):
        if isinstance(value, dict) and isinstance(value.get("credentials"), dict):
            tag = value["credentials"].get("credential_type", CREDENTIAL)
            if tag != CREDENTIAL:
                raise ValueError("Attach a Crunchbase API key credential")
        return value


def _redact(value, secret):
    if isinstance(value, str):
        return value.replace(secret, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, secret) for item in value]
    if isinstance(value, dict):
        return {_redact(str(k), secret): _redact(v, secret) for k, v in value.items()}
    return value


class CrunchbaseNode(WorkflowNode):
    integration_type = "automation-crunchbase"
    credential_provider_labels = {"crunchbase": "Crunchbase Account"}
    connection_evidence = ConnectionEvidence(
        noun="Crunchbase organization data",
        operation="get_organization",
        operation_arguments={"entity_id": "crunchbase"},
        proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return CrunchbaseFullConfig

    @classmethod
    def parse_config(cls, config_data):
        CrunchbaseFullConfig.credential_family(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            CrunchbaseFullConfig.credential_family(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Crunchbase API key")
        credential = self.config.credentials
        op = self.config.config
        method, collection = ROUTES[op.operation]
        params, body = {}, None
        if isinstance(op, Autocomplete):
            path = "/data/autocompletes"
            params = {"query": op.query, "limit": op.limit}
            if op.collection_ids:
                params["collection_ids"] = ",".join(op.collection_ids)
        elif isinstance(op, _Lookup):
            path = "/data/entities/" + collection + "/" + op.entity_id
            params = {"field_ids": ",".join(op.field_ids)}
        else:
            path = "/data/searches/" + collection
            body = op.model_dump(mode="json", exclude={"operation"}, exclude_none=True)
        try:
            async with guarded_async_client(
                timeout=30.0, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    method,
                    BASE + path,
                    headers={
                        "X-cb-user-key": credential.api_key,
                        "Accept": "application/json",
                    },
                    params=params,
                    **({"json": body} if body is not None else {}),
                )
        except httpx.RequestError:
            raise ValueError(
                "Crunchbase could not be reached; try again later"
            ) from None
        if not 200 <= response.status_code < 300:
            # Preserve the provider rejection for connection evidence, without URLs/keys.
            message = _redact(response.text[:2000], credential.api_key)
            output = {
                "status": "error",
                "success": False,
                "http_status": response.status_code,
                "message": message or "Crunchbase rejected the request",
            }
        else:
            try:
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError()
                if isinstance(op, _Lookup):
                    if "properties" in data and not isinstance(
                        data["properties"], dict
                    ):
                        raise ValueError()
                    output = {"data": data}
                else:
                    entities = data.get("entities")
                    if not isinstance(entities, list) or any(
                        not isinstance(row, dict) for row in entities
                    ):
                        raise ValueError()
                    output = {"data": data, "items": entities}
                    if isinstance(op, _Search):
                        # A full page can have a successor; never claim the whole collection is complete.
                        last = entities[-1].get("uuid") if entities else None
                        first = entities[0].get("uuid") if entities else None
                        output.update(
                            {
                                "next_after_id": last
                                if len(entities) == op.limit
                                else None,
                                "previous_before_id": first,
                                "page_size": len(entities),
                            }
                        )
                output.update(
                    {
                        "status": "success",
                        "success": True,
                        "http_status": response.status_code,
                        "identity_verified": False,
                    }
                )
                output = _redact(output, credential.api_key)
            except (ValueError, TypeError):
                raise ValueError(
                    "Crunchbase returned an unexpected JSON response"
                ) from None
        await self.emit(output)
        return output
