"""Teamwork Desk v2 ticket and customer operations.

Contract: https://contento-assets.s3.eu-west-1.amazonaws.com/oas/teamwork_docs/desk/reference/desk-api-v2.oas2.yml
Authentication: https://apidocs.teamwork.com/guides/desk/authentication
The API key belongs to a Desk user; permissions remain those of that user.
"""
from typing import Annotated, Literal, Optional, Union
import re

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret, https_origin
from utils.ssrf import guarded_async_client


class TeamworkDeskAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Teamwork Desk API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://apidocs.teamwork.com/guides/desk/getting-started-with-the-teamwork-desk-api",
            "x-credential-instructions": "In Teamwork Desk, open your avatar → View Profile → API Keys → Create an API key. Paste the key and your Teamwork site URL. Use the US or EU teamwork.com URL for your site.",
        },
    )
    credential_type: Literal["teamwork_desk_api_key"] = Field(
        "teamwork_desk_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        title="API key",
        json_schema_extra={"ui:widget": "password"},
    )
    site_url: str = Field(
        ...,
        title="Teamwork Desk site URL",
        description="For example https://acme.teamwork.com or https://acme.eu.teamwork.com; a pasted Desk page URL is accepted.",
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if not value or any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a Bearer prefix or whitespace")
        return value

    @field_validator("site_url", mode="before")
    @classmethod
    def site(cls, value):
        origin = https_origin(value, field_name="Teamwork Desk site URL")
        if not re.fullmatch(
            r"https://[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.eu)?\.teamwork\.com",
            origin,
        ):
            raise ValueError("Use your HTTPS US or EU teamwork.com site URL")
        return origin


class _Input(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)


class _List(_Input):
    page: int = Field(
        1,
        ge=1,
        le=100000,
        description="Read one page; increase page to continue. No automatic fetch of all pages.",
    )
    page_size: int = Field(
        20, ge=1, le=100, description="Maximum items requested with pageSize."
    )


class _Relationship(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int = Field(..., gt=0)


class _CustomerFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    firstName: Optional[str] = Field(None, max_length=500)
    lastName: Optional[str] = Field(None, max_length=500)
    email: Optional[str] = Field(None, max_length=500)
    phone: Optional[str] = Field(None, max_length=100)
    mobile: Optional[str] = Field(None, max_length=100)
    jobTitle: Optional[str] = Field(None, max_length=500)
    externalId: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=20000)
    company: Optional[_Relationship] = None

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("Supply at least one customer field")
        return self


class _TicketFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: Optional[str] = Field(None, min_length=1, max_length=1000)
    agent: Optional[_Relationship] = None
    inbox: Optional[_Relationship] = None
    status: Optional[_Relationship] = None
    priority: Optional[_Relationship] = None
    customer: Optional[_Relationship] = None
    tags: Optional[list[_Relationship]] = Field(None, max_length=100)

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("Supply at least one ticket field")
        return self


class _CompanyFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=500)
    details: Optional[str] = Field(None, max_length=20000)
    email: Optional[str] = Field(None, max_length=500)
    website: Optional[str] = Field(None, max_length=2000)
    industry: Optional[str] = Field(None, max_length=500)


class _TagFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=500)
    color: Optional[str] = Field(None, max_length=100)


class DeskListTickets(_List):
    operation: Literal["list_tickets"] = Field(
        "list_tickets", json_schema_extra={"ui:hidden": True}
    )


class DeskGetTicket(_Input):
    operation: Literal["get_ticket"] = Field(
        "get_ticket", json_schema_extra={"ui:hidden": True}
    )
    ticket_id: int = Field(..., gt=0, description="Teamwork Desk numeric ID")


class DeskCreateTicket(_Input):
    operation: Literal["create_ticket"] = Field(
        "create_ticket", json_schema_extra={"ui:hidden": True}
    )
    subject: str = Field(..., min_length=1, max_length=1000)
    message: str = Field(..., min_length=1, max_length=100000)
    customer: _Relationship = Field(..., description="Existing customer ID")
    inbox: _Relationship = Field(..., description="Destination inbox ID")
    agent: Optional[_Relationship] = None
    priority: Optional[_Relationship] = None
    status: Optional[_Relationship] = None
    notifyCustomer: bool = Field(
        False, description="Send the customer a notification for this ticket"
    )


class DeskUpdateTicket(_Input):
    operation: Literal["update_ticket"] = Field(
        "update_ticket", json_schema_extra={"ui:hidden": True}
    )
    ticket_id: int = Field(..., gt=0, description="Teamwork Desk numeric ID")
    ticket: _TicketFields = Field(...)


class DeskListCustomers(_List):
    operation: Literal["list_customers"] = Field(
        "list_customers", json_schema_extra={"ui:hidden": True}
    )


class DeskGetCustomer(_Input):
    operation: Literal["get_customer"] = Field(
        "get_customer", json_schema_extra={"ui:hidden": True}
    )
    customer_id: int = Field(..., gt=0, description="Teamwork Desk numeric ID")


class DeskCreateCustomer(_Input):
    operation: Literal["create_customer"] = Field(
        "create_customer", json_schema_extra={"ui:hidden": True}
    )
    customer: _CustomerFields = Field(...)


class DeskUpdateCustomer(_Input):
    operation: Literal["update_customer"] = Field(
        "update_customer", json_schema_extra={"ui:hidden": True}
    )
    customer_id: int = Field(..., gt=0, description="Teamwork Desk numeric ID")
    customer: _CustomerFields = Field(...)


class DeskListCompanies(_List):
    operation: Literal["list_companies"] = Field(
        "list_companies", json_schema_extra={"ui:hidden": True}
    )


class DeskGetCompany(_Input):
    operation: Literal["get_company"] = Field(
        "get_company", json_schema_extra={"ui:hidden": True}
    )
    company_id: int = Field(..., gt=0, description="Teamwork Desk numeric ID")


class DeskCreateCompany(_Input):
    operation: Literal["create_company"] = Field(
        "create_company", json_schema_extra={"ui:hidden": True}
    )
    company: _CompanyFields = Field(...)


class DeskUpdateCompany(_Input):
    operation: Literal["update_company"] = Field(
        "update_company", json_schema_extra={"ui:hidden": True}
    )
    company_id: int = Field(..., gt=0, description="Teamwork Desk numeric ID")
    company: _CompanyFields = Field(...)


class DeskListTags(_List):
    operation: Literal["list_tags"] = Field(
        "list_tags", json_schema_extra={"ui:hidden": True}
    )


class DeskGetTag(_Input):
    operation: Literal["get_tag"] = Field(
        "get_tag", json_schema_extra={"ui:hidden": True}
    )
    tag_id: int = Field(..., gt=0, description="Teamwork Desk numeric ID")


class DeskCreateTag(_Input):
    operation: Literal["create_tag"] = Field(
        "create_tag", json_schema_extra={"ui:hidden": True}
    )
    tag: _TagFields = Field(...)


class DeskUpdateTag(_Input):
    operation: Literal["update_tag"] = Field(
        "update_tag", json_schema_extra={"ui:hidden": True}
    )
    tag_id: int = Field(..., gt=0, description="Teamwork Desk numeric ID")
    tag: _TagFields = Field(...)


class DeskSearchTickets(_List):
    operation: Literal["search_tickets"] = Field(
        "search_tickets", json_schema_extra={"ui:hidden": True}
    )
    search: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Search subject, body, customer name and email",
    )
    exact: Optional[bool] = None
    inboxes: Optional[list[Annotated[int, Field(gt=0)]]] = Field(None, max_length=100)
    statuses: Optional[list[Annotated[int, Field(gt=0)]]] = Field(None, max_length=100)
    agents: Optional[list[Annotated[int, Field(gt=0)]]] = Field(None, max_length=100)
    customers: Optional[list[Annotated[int, Field(gt=0)]]] = Field(None, max_length=100)
    tags: Optional[list[Annotated[int, Field(gt=0)]]] = Field(None, max_length=100)


class DeskListMessages(_List):
    operation: Literal["list_messages"] = Field(
        "list_messages", json_schema_extra={"ui:hidden": True}
    )
    ticket_id: int = Field(..., gt=0, description="Teamwork Desk numeric ID")


class DeskReplyToTicket(_Input):
    operation: Literal["reply_to_ticket"] = Field(
        "reply_to_ticket", json_schema_extra={"ui:hidden": True}
    )
    ticket_id: int = Field(..., gt=0, description="Teamwork Desk numeric ID")
    message: str = Field(..., min_length=1, max_length=100000)
    isDraft: bool = Field(False, description="Save as draft instead of sending a reply")


class DeskListInboxes(_List):
    operation: Literal["list_inboxes"] = Field(
        "list_inboxes", json_schema_extra={"ui:hidden": True}
    )


class DeskGetInbox(_Input):
    operation: Literal["get_inbox"] = Field(
        "get_inbox", json_schema_extra={"ui:hidden": True}
    )
    inbox_id: int = Field(..., gt=0, description="Teamwork Desk numeric ID")


class DeskListUsers(_List):
    operation: Literal["list_users"] = Field(
        "list_users", json_schema_extra={"ui:hidden": True}
    )


class DeskListTicketStatuses(_List):
    operation: Literal["list_ticket_statuses"] = Field(
        "list_ticket_statuses", json_schema_extra={"ui:hidden": True}
    )


class DeskListTicketPriorities(_List):
    operation: Literal["list_ticket_priorities"] = Field(
        "list_ticket_priorities", json_schema_extra={"ui:hidden": True}
    )


DeskOperation = Annotated[
    Union[
        DeskListTickets,
        DeskGetTicket,
        DeskCreateTicket,
        DeskUpdateTicket,
        DeskListCustomers,
        DeskGetCustomer,
        DeskCreateCustomer,
        DeskUpdateCustomer,
        DeskListCompanies,
        DeskGetCompany,
        DeskCreateCompany,
        DeskUpdateCompany,
        DeskListTags,
        DeskGetTag,
        DeskCreateTag,
        DeskUpdateTag,
        DeskSearchTickets,
        DeskListMessages,
        DeskReplyToTicket,
        DeskListInboxes,
        DeskGetInbox,
        DeskListUsers,
        DeskListTicketStatuses,
        DeskListTicketPriorities,
    ],
    Field(discriminator="operation"),
]


class TeamworkDeskConfig(NodeConfig[DeskOperation, TeamworkDeskAPIKeyCredential]):
    pass


OPERATIONS = {
    "search_tickets": {
        "method": "GET",
        "path": "/v2/search/tickets.json",
        "envelope": "tickets",
        "body": None,
    },
    "list_tickets": {
        "method": "GET",
        "path": "/v2/tickets.json",
        "envelope": "tickets",
        "body": None,
    },
    "get_ticket": {
        "method": "GET",
        "path": "/v2/tickets/{ticket_id}.json",
        "envelope": "ticket",
        "body": None,
    },
    "create_ticket": {
        "method": "POST",
        "path": "/v2/tickets.json",
        "envelope": "ticket",
        "body": "flat",
    },
    "update_ticket": {
        "method": "PATCH",
        "path": "/v2/tickets/{ticket_id}.json",
        "envelope": "ticket",
        "body": "ticket",
    },
    "list_customers": {
        "method": "GET",
        "path": "/v2/customers.json",
        "envelope": "customers",
        "body": None,
    },
    "get_customer": {
        "method": "GET",
        "path": "/v2/customers/{customer_id}.json",
        "envelope": "customer",
        "body": None,
    },
    "create_customer": {
        "method": "POST",
        "path": "/v2/customers.json",
        "envelope": "customer",
        "body": "customer",
    },
    "update_customer": {
        "method": "PATCH",
        "path": "/v2/customers/{customer_id}.json",
        "envelope": "customer",
        "body": "customer",
    },
    "list_companies": {
        "method": "GET",
        "path": "/v2/companies.json",
        "envelope": "companies",
        "body": None,
    },
    "get_company": {
        "method": "GET",
        "path": "/v2/companies/{company_id}.json",
        "envelope": "company",
        "body": None,
    },
    "create_company": {
        "method": "POST",
        "path": "/v2/companies.json",
        "envelope": "company",
        "body": "flat_company",
    },
    "update_company": {
        "method": "PATCH",
        "path": "/v2/companies/{company_id}.json",
        "envelope": "company",
        "body": "company",
    },
    "list_tags": {
        "method": "GET",
        "path": "/v2/tags.json",
        "envelope": "tags",
        "body": None,
    },
    "get_tag": {
        "method": "GET",
        "path": "/v2/tags/{tag_id}.json",
        "envelope": "tag",
        "body": None,
    },
    "create_tag": {
        "method": "POST",
        "path": "/v2/tags.json",
        "envelope": "tag",
        "body": "tag",
    },
    "update_tag": {
        "method": "PATCH",
        "path": "/v2/tags/{tag_id}.json",
        "envelope": "tag",
        "body": "tag",
    },
    "list_messages": {
        "method": "GET",
        "path": "/v2/tickets/{ticket_id}/messages.json",
        "envelope": "messages",
        "body": None,
    },
    "reply_to_ticket": {
        "method": "POST",
        "path": "/v2/tickets/{ticket_id}/messages.json",
        "envelope": "ticket",
        "body": "flat",
    },
    "list_inboxes": {
        "method": "GET",
        "path": "/v2/inboxes.json",
        "envelope": "inboxes",
        "body": None,
    },
    "get_inbox": {
        "method": "GET",
        "path": "/v2/inboxes/{inbox_id}.json",
        "envelope": "inbox",
        "body": None,
    },
    "list_users": {
        "method": "GET",
        "path": "/v2/users.json",
        "envelope": "users",
        "body": None,
    },
    "list_ticket_statuses": {
        "method": "GET",
        "path": "/v2/ticketstatuses.json",
        "envelope": "ticketstatuses",
        "body": None,
    },
    "list_ticket_priorities": {
        "method": "GET",
        "path": "/v2/ticketpriorities.json",
        "envelope": "ticketpriorities",
        "body": None,
    },
}


class TeamworkDeskNode(WorkflowNode):
    integration_type = "automation-teamwork-desk"
    connection_evidence = ConnectionEvidence(
        noun="inboxes", operation="list_inboxes", label_keys=("name", "id")
    )

    @classmethod
    def get_config_model(cls):
        return TeamworkDeskConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Teamwork Desk API key")
        credential = TeamworkDeskAPIKeyCredential.model_validate(
            self.config.credentials.model_dump()
        )
        config = self.config.config
        spec = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        path = spec["path"]
        for field in re.findall(r"\{([^}]+)\}", path):
            path = path.replace("{" + field + "}", str(values.pop(field)))
        params = None
        if isinstance(config, _List):
            params = {"page": values.pop("page"), "pageSize": values.pop("page_size")}
        if isinstance(config, DeskSearchTickets):
            params.update(
                {
                    key: ",".join(map(str, value)) if isinstance(value, list) else value
                    for key, value in values.items()
                    if value != []
                }
            )
        body = None
        if spec["body"] == "flat":
            body = values
        elif spec["body"] == "flat_company":
            body = values["company"]
        elif spec["body"]:
            body = {spec["body"]: values[spec["body"]]}
        request = {"json": body} if body is not None else {}
        try:
            async with guarded_async_client(
                timeout=30, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.request(
                    spec["method"],
                    credential.site_url + "/desk/api" + path,
                    headers={
                        "Authorization": "Bearer " + credential.api_key,
                        "Accept": "application/json",
                    },
                    params=params,
                    **request,
                )
        except httpx.RequestError:
            if spec["method"] != "GET":
                raise ValueError(
                    "Teamwork Desk write outcome is unknown; inspect Desk before retrying"
                ) from None
            raise ValueError("Teamwork Desk could not be reached") from None
        if not 200 <= response.status_code < 300:
            message = response.text[:1000].replace(credential.api_key, "[redacted]")
            raise ValueError(f"Teamwork Desk API {response.status_code}: {message}")
        try:
            data = response.json()
        except ValueError:
            raise ValueError(
                "Teamwork Desk returned an unexpected non-JSON response"
            ) from None
        if not isinstance(data, dict) or data.get("errors") or data.get("error"):
            raise ValueError(
                "Teamwork Desk returned an error or unexpected response envelope"
            )
        resource = data.get(spec["envelope"])
        if isinstance(config, _List):
            if not isinstance(resource, list) or any(
                not isinstance(item, dict) for item in resource
            ):
                raise ValueError("Teamwork Desk returned an unexpected list envelope")
        elif not isinstance(resource, dict):
            raise ValueError(
                "Teamwork Desk did not return the requested resource; write outcome may be unverified"
            )
        # Keep the provider's resource and pagination envelopes. A successful
        # write is the API acknowledgement, not an independent readback proof.
        output = {
            "status": "success",
            "operation": config.operation,
            "data": data,
            spec["envelope"]: resource,
            "http_status": response.status_code,
        }
        if isinstance(config, _List):
            output["items"] = resource
            output["pagination"] = data.get("pagination") or data.get("meta", {}).get(
                "page"
            )
        else:
            output["write_acknowledged"] = spec["method"] != "GET"
        await self.emit(output)
        return output
