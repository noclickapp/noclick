"""RepairShopr v1 customer, ticket and sales automation.

Each typed operation makes one documented request. Pasted API tokens stay in
Bearer headers; the tenant is restricted to RepairShopr's HTTPS subdomains.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret, https_origin
from utils.ssrf import guarded_async_client


class RepairshoprAPITokenCredential(BaseModel):
    model_config = ConfigDict(title="Repairshopr API Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api-docs.repairshopr.com/",
            "x-credential-instructions": "In RepairShopr, open your user profile and copy an API key with permissions for your workflow. Paste the key and your account subdomain below. NoClick sends the key as a Bearer token and checks the current user and customers to verify the connection.",
        })
    credential_type: Literal["repairshopr_api_token"] = Field("repairshopr_api_token", json_schema_extra={"ui:hidden": True})
    subdomain: str = Field(..., title="Account subdomain", description="The part before .repairshopr.com in your account URL. You can also paste the full account URL.")
    api_token: str = Field(..., title="API token", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("subdomain", mode="before")
    @classmethod
    def tenant(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste your RepairShopr account subdomain")
        value = value.strip().lower()
        if "." in value or "://" in value or "/" in value:
            origin = https_origin(value, field_name="Account URL")
            match = re.fullmatch(r"https://([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)\.repairshopr\.com", origin)
            if not match:
                raise ValueError("Use your HTTPS account URL on repairshopr.com")
            value = match.group(1)
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
            raise ValueError("Use a single RepairShopr account subdomain")
        return value

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API token", key=True)
        if not value or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API token without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def update_fields(self):
        if getattr(self, "operation", "").startswith("update_"):
            values = self.model_dump(exclude_none=True, exclude={"operation", "id"})
            if not values:
                raise ValueError("Provide at least one field to update")
        return self


class _Page(_Input):
    page: int = Field(1, ge=1, le=1000000, description="One provider page. Increment to read the next page; output preserves the provider's pagination metadata.")


class RepairshoprGetCurrentUserConfig(_Input):
    operation: Literal["get_current_user"] = Field("get_current_user", json_schema_extra={"ui:hidden": True})


class RepairshoprListCustomersConfig(_Page):
    operation: Literal["list_customers"] = Field("list_customers", json_schema_extra={"ui:hidden": True})
    query: str | None = None
    email: str | None = None


class RepairshoprGetCustomerConfig(_Input):
    operation: Literal["get_customer"] = Field("get_customer", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)


class RepairshoprCreateCustomerConfig(_Input):
    operation: Literal["create_customer"] = Field("create_customer", json_schema_extra={"ui:hidden": True})
    firstname: str = Field(..., min_length=1, max_length=10000)
    lastname: str | None = None
    business_name: str | None = None
    email: str | None = None
    phone: str | None = None
    mobile: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    notes: str | None = None


class RepairshoprUpdateCustomerConfig(_Input):
    operation: Literal["update_customer"] = Field("update_customer", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)
    firstname: str | None = None
    lastname: str | None = None
    business_name: str | None = None
    email: str | None = None
    phone: str | None = None
    mobile: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    notes: str | None = None


class RepairshoprListTicketsConfig(_Page):
    operation: Literal["list_tickets"] = Field("list_tickets", json_schema_extra={"ui:hidden": True})
    customer_id: int | None = Field(None, ge=1)
    status: str | None = None
    query: str | None = None
    user_id: int | None = Field(None, ge=1)


class RepairshoprGetTicketConfig(_Input):
    operation: Literal["get_ticket"] = Field("get_ticket", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)


class RepairshoprCreateTicketConfig(_Input):
    operation: Literal["create_ticket"] = Field("create_ticket", json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., ge=1)
    subject: str = Field(..., min_length=1, max_length=10000)
    status: str | None = None
    problem_type: str | None = None
    user_id: int | None = Field(None, ge=1)
    contact_id: int | None = Field(None, ge=1)
    priority: str | None = None


class RepairshoprUpdateTicketConfig(_Input):
    operation: Literal["update_ticket"] = Field("update_ticket", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)
    customer_id: int | None = Field(None, ge=1)
    subject: str | None = None
    status: str | None = None
    problem_type: str | None = None
    user_id: int | None = Field(None, ge=1)
    contact_id: int | None = Field(None, ge=1)
    priority: str | None = None


class RepairshoprListContactsConfig(_Page):
    operation: Literal["list_contacts"] = Field("list_contacts", json_schema_extra={"ui:hidden": True})
    customer_id: int | None = Field(None, ge=1)


class RepairshoprGetContactConfig(_Input):
    operation: Literal["get_contact"] = Field("get_contact", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)


class RepairshoprCreateContactConfig(_Input):
    operation: Literal["create_contact"] = Field("create_contact", json_schema_extra={"ui:hidden": True})
    customer_id: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=10000)
    email: str | None = None
    phone: str | None = None
    mobile: str | None = None
    notes: str | None = None


class RepairshoprUpdateContactConfig(_Input):
    operation: Literal["update_contact"] = Field("update_contact", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)
    customer_id: int | None = Field(None, ge=1)
    name: str = Field(..., min_length=1, max_length=10000)
    email: str | None = None
    phone: str | None = None
    mobile: str | None = None
    notes: str | None = None


class RepairshoprListLeadsConfig(_Page):
    operation: Literal["list_leads"] = Field("list_leads", json_schema_extra={"ui:hidden": True})
    query: str | None = None


class RepairshoprGetLeadConfig(_Input):
    operation: Literal["get_lead"] = Field("get_lead", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)


class RepairshoprCreateLeadConfig(_Input):
    operation: Literal["create_lead"] = Field("create_lead", json_schema_extra={"ui:hidden": True})
    first_name: str = Field(..., min_length=1, max_length=10000)
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    business_name: str | None = None
    ticket_subject: str | None = None
    ticket_description: str | None = None
    status: str | None = None
    customer_id: int | None = Field(None, ge=1)


class RepairshoprUpdateLeadConfig(_Input):
    operation: Literal["update_lead"] = Field("update_lead", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = None
    business_name: str | None = None
    ticket_subject: str | None = None
    ticket_description: str | None = None
    status: str | None = None
    customer_id: int | None = Field(None, ge=1)


class RepairshoprListInvoicesConfig(_Page):
    operation: Literal["list_invoices"] = Field("list_invoices", json_schema_extra={"ui:hidden": True})
    paid: bool | None = None
    unpaid: bool | None = None
    ticket_id: int | None = Field(None, ge=1)


class RepairshoprGetInvoiceConfig(_Input):
    operation: Literal["get_invoice"] = Field("get_invoice", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)


class RepairshoprListEstimatesConfig(_Page):
    operation: Literal["list_estimates"] = Field("list_estimates", json_schema_extra={"ui:hidden": True})
    customer_id: int | None = Field(None, ge=1)
    status: str | None = None


class RepairshoprGetEstimateConfig(_Input):
    operation: Literal["get_estimate"] = Field("get_estimate", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)


class RepairshoprListProductsConfig(_Page):
    operation: Literal["list_products"] = Field("list_products", json_schema_extra={"ui:hidden": True})
    query: str | None = None
    sku: str | None = None
    name: str | None = None


class RepairshoprGetProductConfig(_Input):
    operation: Literal["get_product"] = Field("get_product", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)


class RepairshoprListTicketCommentsConfig(_Page):
    operation: Literal["list_ticket_comments"] = Field("list_ticket_comments", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)


class RepairshoprAddTicketCommentConfig(_Input):
    operation: Literal["add_ticket_comment"] = Field("add_ticket_comment", json_schema_extra={"ui:hidden": True})
    id: int = Field(..., ge=1)
    body: str = Field(..., min_length=1, max_length=10000)
    subject: str | None = None
    hidden: bool = True
    do_not_email: bool = True


RepairshoprOperation = Annotated[Union[
    RepairshoprGetCurrentUserConfig,
    RepairshoprListCustomersConfig,
    RepairshoprGetCustomerConfig,
    RepairshoprCreateCustomerConfig,
    RepairshoprUpdateCustomerConfig,
    RepairshoprListTicketsConfig,
    RepairshoprGetTicketConfig,
    RepairshoprCreateTicketConfig,
    RepairshoprUpdateTicketConfig,
    RepairshoprListContactsConfig,
    RepairshoprGetContactConfig,
    RepairshoprCreateContactConfig,
    RepairshoprUpdateContactConfig,
    RepairshoprListLeadsConfig,
    RepairshoprGetLeadConfig,
    RepairshoprCreateLeadConfig,
    RepairshoprUpdateLeadConfig,
    RepairshoprListInvoicesConfig,
    RepairshoprGetInvoiceConfig,
    RepairshoprListEstimatesConfig,
    RepairshoprGetEstimateConfig,
    RepairshoprListProductsConfig,
    RepairshoprGetProductConfig,
    RepairshoprListTicketCommentsConfig,
    RepairshoprAddTicketCommentConfig
], Field(discriminator="operation")]


class RepairshoprFullConfig(NodeConfig[RepairshoprOperation, RepairshoprAPITokenCredential]):
    pass


ROUTES = {
    'get_current_user': ('GET', '/me'),
    'list_customers': ('GET', '/customers'),
    'get_customer': ('GET', '/customers/{id}'),
    'create_customer': ('POST', '/customers'),
    'update_customer': ('PUT', '/customers/{id}'),
    'list_tickets': ('GET', '/tickets'),
    'get_ticket': ('GET', '/tickets/{id}'),
    'create_ticket': ('POST', '/tickets'),
    'update_ticket': ('PUT', '/tickets/{id}'),
    'list_contacts': ('GET', '/contacts'),
    'get_contact': ('GET', '/contacts/{id}'),
    'create_contact': ('POST', '/contacts'),
    'update_contact': ('PUT', '/contacts/{id}'),
    'list_leads': ('GET', '/leads'),
    'get_lead': ('GET', '/leads/{id}'),
    'create_lead': ('POST', '/leads'),
    'update_lead': ('PUT', '/leads/{id}'),
    'list_invoices': ('GET', '/invoices'),
    'get_invoice': ('GET', '/invoices/{id}'),
    'list_estimates': ('GET', '/estimates'),
    'get_estimate': ('GET', '/estimates/{id}'),
    'list_products': ('GET', '/products'),
    'get_product': ('GET', '/products/{id}'),
    'list_ticket_comments': ('GET', '/tickets/{id}/comments'),
    'add_ticket_comment': ('POST', '/tickets/{id}/comment'),
}


class RepairshoprNode(WorkflowNode):
    integration_type = "automation-repairshopr"
    connection_evidence = ConnectionEvidence(noun="customers", operation="list_customers",
        identity_operation="get_current_user", label_keys=("fullname", "business_name", "email", "id"), identity_keys=("user_name", "user_email"))

    @classmethod
    def get_config_model(cls):
        return RepairshoprFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a RepairShopr API token")
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        if "{id}" in path:
            path = path.replace("{id}", str(values.pop("id")))
        if method != "GET" and not values:
            raise ValueError("Provide at least one field to update")
        # Only the typed fields above can reach the provider. Never accept an
        # arbitrary URL, HTTP method, query or request body from workflow input.
        kwargs = {"params": values} if method == "GET" else {"json": values}
        async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method,
                f"https://{credential.subdomain}.repairshopr.com/api/v1{path}",
                headers={"Authorization": f"Bearer {credential.api_token}", "Accept": "application/json"},
                **kwargs)
        if not 200 <= response.status_code < 300:
            # Preserve the provider's rejection for the connect verdict, while
            # ensuring a provider that echoes request headers cannot leak a key.
            message = response.text[:4000].replace(credential.api_token, "[redacted]")
            raise ValueError(f"RepairShopr HTTP {response.status_code}: {message}")
        if len(response.content) > 10000000 or "json" not in response.headers.get("content-type", "").lower():
            raise ValueError("RepairShopr returned an unexpected response; expected bounded JSON")
        data = response.json()
        if not isinstance(data, (dict, list)):
            raise ValueError("RepairShopr returned an unexpected JSON shape")
        if isinstance(data, dict) and (data.get("success") is False or data.get("error") or data.get("errors")):
            raise ValueError(str(data).replace(credential.api_token, "[redacted]")[:4000])
        if not isinstance(data, dict):
            raise ValueError("RepairShopr response is missing its documented object envelope")
        operation = config.operation
        if operation == "get_current_user":
            if not isinstance(data.get("user_id"), int) or not isinstance(data.get("user_name"), str):
                raise ValueError("RepairShopr response is missing the current user identity")
        elif operation.startswith("list_"):
            key = "comments" if operation == "list_ticket_comments" else operation.removeprefix("list_")
            if not isinstance(data.get(key), list):
                raise ValueError("RepairShopr response is missing the requested collection")
        else:
            key = "comment" if operation == "add_ticket_comment" else operation.split("_", 1)[1]
            record = data if key == "contact" else data.get(key)
            if not isinstance(record, dict) or not isinstance(record.get("id"), int):
                raise ValueError("RepairShopr response is missing the requested record")
        return {"status": "success", "data": data}
