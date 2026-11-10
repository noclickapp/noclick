"""Kajabi Public API v1: contacts, tags, offer access, customers and purchases.

Official contract: https://github.com/Kajabi/public_api_docs/blob/main/openapi.yaml
Authentication: paste an existing Bearer access token. No OAuth redirect or token
issuance occurs here; replace the token when it expires. List operations return
one provider page, preserving links/meta so workflows can request the next page.
Kajabi also supports hooks; this node covers request/response operations only.
"""
from typing import Annotated, Any, Literal, Union
from urllib.parse import quote
import time

import httpx
from pydantic import BaseModel, ConfigDict, Field
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

API = "https://api.kajabi.com"
MEDIA_TYPE = "application/vnd.api+json"


class KajabiAccessTokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Kajabi Access Token",
        json_schema_extra={
            "x-credential-type": "kajabi_access_token",
            "x-credential-url": "https://developers.kajabi.com/api-reference/authentication/get-access-token",
            "x-credential-instructions": "In Kajabi Settings → API, create a User API Key with permissions for the operations you need. Exchange its client_id and client_secret using grant_type=client_credentials at POST https://api.kajabi.com/v1/oauth/token, then paste only the access_token here. Public API access must be enabled. Replace the token when it expires.",
        },
    )
    credential_type: Literal["kajabi_access_token"] = Field(
        "kajabi_access_token", json_schema_extra={"ui:hidden": True}
    )
    access_token: str = Field(
        ...,
        title="Access Token",
        min_length=1,
        repr=False,
        json_schema_extra={
            "ui:widget": "password",
            "ui:help": "Paste the access_token value without the Bearer prefix. Replace it when it expires.",
        },
    )


def operation_field(name: str, title: str, category: str, description: str):
    return Field(
        name,
        description=description,
        json_schema_extra={
            "const": name,
            "ui:hidden": True,
            "x-display-name": title,
            "x-category": category,
            "x-is-trigger": False,
        },
    )


class PageConfig(BaseModel):
    page_number: int = Field(
        1,
        ge=1,
        description="Page number. Returns one page; use the output links and meta to continue.",
    )
    page_size: int = Field(
        25, ge=1, description="Number of records requested per provider page."
    )
    sort: str | None = Field(
        None,
        description="Documented sort field, with a leading minus for descending order.",
    )


class SitePageConfig(PageConfig):
    site_id: str | None = Field(
        None,
        description="Filter by site ID. Required by Kajabi for contacts when the account has multiple sites.",
        json_schema_extra={"x-dynamic-options": {"field_name": "site_id"}},
    )


class PeoplePageConfig(SitePageConfig):
    search: str | None = Field(
        None, description="Search by name or email within the selected site."
    )


class ContactAttributes(BaseModel):
    name: str | None = None
    email: str | None = None
    phone_number: str | None = None
    business_number: str | None = None
    subscribed: bool | None = Field(
        None, description="Whether the contact is subscribed to marketing emails."
    )
    address_line_1: str | None = None
    address_line_2: str | None = None
    address_city: str | None = None
    address_state: str | None = None
    address_country: str | None = None
    address_zip: str | None = None
    custom_1: str | None = None
    custom_2: str | None = None
    custom_3: str | None = None


class ContactIDConfig(BaseModel):
    contact_id: str = Field(..., min_length=1, description="Kajabi contact ID.")


class TagIDsConfig(ContactIDConfig):
    tag_ids: list[str] = Field(
        ..., min_length=1, description="Contact tag IDs from List Tags."
    )


class OfferIDsConfig(ContactIDConfig):
    offer_ids: list[str] = Field(
        ..., min_length=1, description="Offer IDs from List Offers."
    )


class KajabiListSitesConfig(PageConfig):
    operation: Literal["list_sites"] = operation_field(
        "list_sites", "List Sites", "Sites", "List sites; returns one page."
    )


class KajabiListContactsConfig(PeoplePageConfig):
    operation: Literal["list_contacts"] = operation_field(
        "list_contacts", "List Contacts", "Contacts", "List contacts; returns one page."
    )


class KajabiGetContactConfig(ContactIDConfig):
    operation: Literal["get_contact"] = operation_field(
        "get_contact", "Get Contact", "Contacts", "Contact details"
    )


class KajabiCreateContactConfig(ContactAttributes):
    operation: Literal["create_contact"] = operation_field(
        "create_contact", "Create Contact", "Contacts", "Create a contact"
    )
    site_id: str = Field(
        ...,
        min_length=1,
        description="Site ID from List Sites.",
        json_schema_extra={"x-dynamic-options": {"field_name": "site_id"}},
    )
    name: str = Field(..., min_length=1, description="Contact name.")
    email: str = Field(..., min_length=1, description="Contact email address.")


class KajabiUpdateContactConfig(ContactAttributes):
    operation: Literal["update_contact"] = operation_field(
        "update_contact", "Update Contact", "Contacts", "Update contact"
    )
    contact_id: str = Field(..., min_length=1, description="Contact ID to update.")
    external_user_id: str | None = Field(
        None, description="Supported only for a contact with a related customer."
    )


class KajabiListTagsConfig(SitePageConfig):
    operation: Literal["list_tags"] = operation_field(
        "list_tags", "List Tags", "Tags", "List contact tags; returns one page."
    )
    name_contains: str | None = Field(
        None, description="Filter tag names containing this text."
    )


class KajabiListContactTagsConfig(ContactIDConfig):
    operation: Literal["list_contact_tags"] = operation_field(
        "list_contact_tags",
        "List Contact Tags",
        "Contacts",
        "List contact's tags; returns one page.",
    )


class KajabiAddContactTagsConfig(TagIDsConfig):
    operation: Literal["add_contact_tags"] = operation_field(
        "add_contact_tags", "Add Contact Tags", "Contacts", "Add tag to contact"
    )


class KajabiRemoveContactTagsConfig(TagIDsConfig):
    operation: Literal["remove_contact_tags"] = operation_field(
        "remove_contact_tags",
        "Remove Contact Tags",
        "Contacts",
        "Remove tag from contact",
    )


class KajabiReplaceContactTagsConfig(ContactIDConfig):
    operation: Literal["replace_contact_tags"] = operation_field(
        "replace_contact_tags",
        "Replace Contact Tags",
        "Contacts",
        "Replace tags for contact; replaces the entire relationship set.",
    )
    tag_ids: list[str] = Field(
        ...,
        description="Complete replacement tag IDs. An empty list removes every tag.",
    )


class KajabiListOffersConfig(SitePageConfig):
    operation: Literal["list_offers"] = operation_field(
        "list_offers", "List Offers", "Offer Access", "List offers; returns one page."
    )
    title_contains: str | None = Field(
        None, description="Filter offer titles containing this text."
    )
    published: bool | None = Field(
        None,
        description="Filter by publish state; omit for drafts and published offers.",
    )


class KajabiGetOfferConfig(BaseModel):
    operation: Literal["get_offer"] = operation_field(
        "get_offer", "Get Offer", "Offer Access", "Offer details"
    )
    offer_id: str = Field(..., min_length=1, description="Kajabi offer id.")


class KajabiListContactOffersConfig(ContactIDConfig):
    operation: Literal["list_contact_offers"] = operation_field(
        "list_contact_offers",
        "List Contact Offers",
        "Offer Access",
        "List contact's offers; returns one page.",
    )


class KajabiGrantOffersConfig(OfferIDsConfig):
    operation: Literal["grant_offers"] = operation_field(
        "grant_offers", "Grant Offers", "Offer Access", "Grant offer to contact"
    )
    send_customer_welcome_email: bool = Field(
        True,
        description="Kajabi sends a welcome email by default when granting access; choose No to suppress it.",
    )


class KajabiRevokeOffersConfig(OfferIDsConfig):
    operation: Literal["revoke_offers"] = operation_field(
        "revoke_offers",
        "Revoke Offers",
        "Offer Access",
        "Revoke offer from contact; deactivates associated product memberships.",
    )


class KajabiReplaceContactOffersConfig(ContactIDConfig):
    operation: Literal["replace_contact_offers"] = operation_field(
        "replace_contact_offers",
        "Replace Contact Offers",
        "Offer Access",
        "Replace offers for contact; replaces the entire relationship set.",
    )
    offer_ids: list[str] = Field(
        ...,
        description="Complete replacement offer IDs. An empty list revokes all offer access.",
    )


class KajabiListCustomersConfig(PeoplePageConfig):
    operation: Literal["list_customers"] = operation_field(
        "list_customers",
        "List Customers",
        "Customers",
        "List customers; returns one page.",
    )


class KajabiGetCustomerConfig(BaseModel):
    operation: Literal["get_customer"] = operation_field(
        "get_customer", "Get Customer", "Customers", "Customer details"
    )
    customer_id: str = Field(..., min_length=1, description="Kajabi customer id.")


class KajabiListPurchasesConfig(SitePageConfig):
    operation: Literal["list_purchases"] = operation_field(
        "list_purchases",
        "List Purchases",
        "Purchases",
        "List purchases; returns one page.",
    )
    customer_id: str | None = Field(
        None, description="Filter purchases by customer ID."
    )
    active: bool | None = Field(None, description="Filter by active purchase state.")


class KajabiGetPurchaseConfig(BaseModel):
    operation: Literal["get_purchase"] = operation_field(
        "get_purchase", "Get Purchase", "Purchases", "Purchase details"
    )
    purchase_id: str = Field(..., min_length=1, description="Kajabi purchase id.")


KajabiConfig = Annotated[
    Union[
        KajabiListSitesConfig,
        KajabiListContactsConfig,
        KajabiGetContactConfig,
        KajabiCreateContactConfig,
        KajabiUpdateContactConfig,
        KajabiListTagsConfig,
        KajabiListContactTagsConfig,
        KajabiAddContactTagsConfig,
        KajabiRemoveContactTagsConfig,
        KajabiReplaceContactTagsConfig,
        KajabiListOffersConfig,
        KajabiGetOfferConfig,
        KajabiListContactOffersConfig,
        KajabiGrantOffersConfig,
        KajabiRevokeOffersConfig,
        KajabiReplaceContactOffersConfig,
        KajabiListCustomersConfig,
        KajabiGetCustomerConfig,
        KajabiListPurchasesConfig,
        KajabiGetPurchaseConfig,
    ],
    Field(discriminator="operation"),
]


class KajabiNodeConfig(NodeConfig[KajabiConfig, KajabiAccessTokenCredential]):
    pass


ROUTES = {
    "list_sites": ("GET", "/v1/sites"),
    "list_contacts": ("GET", "/v1/contacts"),
    "get_contact": ("GET", "/v1/contacts/{id}"),
    "create_contact": ("POST", "/v1/contacts"),
    "update_contact": ("PATCH", "/v1/contacts/{id}"),
    "list_tags": ("GET", "/v1/contact_tags"),
    "list_contact_tags": ("GET", "/v1/contacts/{contact_id}/relationships/tags"),
    "add_contact_tags": ("POST", "/v1/contacts/{contact_id}/relationships/tags"),
    "remove_contact_tags": ("DELETE", "/v1/contacts/{contact_id}/relationships/tags"),
    "replace_contact_tags": ("PATCH", "/v1/contacts/{contact_id}/relationships/tags"),
    "list_offers": ("GET", "/v1/offers"),
    "get_offer": ("GET", "/v1/offers/{id}"),
    "list_contact_offers": ("GET", "/v1/contacts/{contact_id}/relationships/offers"),
    "grant_offers": ("POST", "/v1/contacts/{contact_id}/relationships/offers"),
    "revoke_offers": ("DELETE", "/v1/contacts/{contact_id}/relationships/offers"),
    "replace_contact_offers": (
        "PATCH",
        "/v1/contacts/{contact_id}/relationships/offers",
    ),
    "list_customers": ("GET", "/v1/customers"),
    "get_customer": ("GET", "/v1/customers/{id}"),
    "list_purchases": ("GET", "/v1/purchases"),
    "get_purchase": ("GET", "/v1/purchases/{id}"),
}


class KajabiNode(WorkflowNode):
    integration_type = "automation-kajabi"
    credential_provider_labels = {"kajabi": "Kajabi Account"}
    connection_evidence = ConnectionEvidence(field="site_id", noun="sites")
    edit_examples = [
        "Create a Kajabi contact and add a tag",
        "Grant an offer to a contact without a welcome email",
        "Sync Kajabi purchases and customers to my CRM",
    ]

    @classmethod
    def get_config_model(cls):
        return KajabiNodeConfig

    @classmethod
    async def load_field_options(
        cls, field_name, credential_data, context=None, page_token=None, search=None
    ):
        if field_name != "site_id":
            return {"options": []}
        config = KajabiNodeConfig(
            config=KajabiListSitesConfig(page_number=int(page_token or 1)),
            credentials=credential_data,
        )
        result = await cls(
            node_id="kajabi-sites",
            node_type="automation-kajabi",
            node_data={},
            config=config,
        ).execute({})
        if result["status"] != "success":
            return result
        options = []
        for site in result["data"]:
            attributes = site.get("attributes")
            title = attributes.get("title") if isinstance(attributes, dict) else None
            if (
                site.get("type") != "sites"
                or not isinstance(title, str)
                or not title.strip()
            ):
                return {
                    "status": "error",
                    "error": "Kajabi returned an invalid site response",
                }
            if not search or search.casefold() in title.casefold():
                options.append({"label": title, "value": site["id"]})
        # Do not follow arbitrary links; the next page is requested on the fixed API origin.
        next_page = (
            str(config.config.page_number + 1)
            if result.get("links", {}).get("next")
            else None
        )
        return {"options": options, "next_page_token": next_page}

    async def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        if not self.config or not self.config.credentials:
            raise ValueError("Add a Kajabi access token to continue.")
        c = self.config.config
        action = c.operation
        method, path = ROUTES[action]
        if "{contact_id}" in path:
            path = path.replace("{contact_id}", quote(c.contact_id, safe=""))
        elif "{id}" in path:
            id_field = {
                "get_contact": "contact_id",
                "update_contact": "contact_id",
                "get_offer": "offer_id",
                "get_customer": "customer_id",
                "get_purchase": "purchase_id",
            }[action]
            path = path.replace("{id}", quote(getattr(c, id_field), safe=""))
        params = {}
        if isinstance(c, PageConfig):
            params = {"page[number]": c.page_number, "page[size]": c.page_size}
            if c.sort:
                params["sort"] = c.sort
        for field, query in (
            ("site_id", "filter[site_id]"),
            ("search", "filter[search]"),
            ("name_contains", "filter[name_cont]"),
            ("title_contains", "filter[title_cont]"),
            ("published", "filter[published]"),
            ("customer_id", "filter[customer_id]"),
            ("active", "filter[active]"),
        ):
            value = getattr(c, field, None)
            if (
                method == "GET"
                and "relationships" not in path
                and action.startswith("list_")
                and value is not None
                and value != ""
            ):
                params[query] = str(value).lower() if isinstance(value, bool) else value
        body = None
        if action in ("create_contact", "update_contact"):
            attributes = {
                k: v
                for k, v in c.model_dump(exclude_none=True).items()
                if k in ContactAttributes.model_fields or k == "external_user_id"
            }
            if not attributes:
                raise ValueError("Provide at least one contact attribute to update.")
            data = {"type": "contacts", "attributes": attributes}
            if action == "create_contact":
                data["relationships"] = {
                    "site": {"data": {"type": "sites", "id": c.site_id}}
                }
            else:
                data["id"] = c.contact_id
            body = {"data": data}
        elif method != "GET" and "relationships" in path:
            resource_type = "contact_tags" if path.endswith("/tags") else "offers"
            ids = c.tag_ids if resource_type == "contact_tags" else c.offer_ids
            if any(not value.strip() for value in ids):
                raise ValueError("Relationship IDs must not be blank.")
            body = {"data": [{"type": resource_type, "id": value} for value in ids]}
            if action == "grant_offers":
                body["meta"] = {
                    "send_customer_welcome_email": c.send_customer_welcome_email
                }
        headers = {
            "Authorization": f"Bearer {self.config.credentials.access_token}",
            "Accept": MEDIA_TYPE,
        }
        kwargs = {"params": params}
        if body is not None:
            headers["Content-Type"] = MEDIA_TYPE
            kwargs["json"] = body
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.request(
                    method, API + path, headers=headers, **kwargs
                )
            try:
                payload = response.json()
            except ValueError:
                return self._error(
                    action,
                    "Kajabi returned a non-JSON response",
                    response.status_code,
                    start,
                )
            if response.status_code >= 400 or (
                isinstance(payload, dict) and payload.get("errors")
            ):
                # JSON:API error titles/details are the provider's own words.
                errors = payload.get("errors", []) if isinstance(payload, dict) else []
                message = "; ".join(
                    str(e.get("detail") or e.get("title") or e)
                    for e in errors
                    if isinstance(e, dict)
                )
                return self._error(
                    action,
                    message or f"Kajabi request failed ({response.status_code})",
                    response.status_code,
                    start,
                )
            many = action.startswith("list_") or "relationships" in path
            data = payload.get("data") if isinstance(payload, dict) else None
            rows = data if isinstance(data, list) else [data]
            if (
                (many and not isinstance(data, list))
                or (not many and not isinstance(data, dict))
                or any(
                    not isinstance(row, dict)
                    or not isinstance(row.get("id"), str)
                    or not row["id"]
                    or not isinstance(row.get("type"), str)
                    or not row["type"]
                    for row in rows
                )
            ):
                return self._error(
                    action,
                    "Kajabi returned an invalid resource response",
                    response.status_code,
                    start,
                )
            return {
                "status": "success",
                "action": action,
                "data": data,
                **{
                    k: payload[k] for k in ("links", "meta", "included") if k in payload
                },
                "status_code": response.status_code,
                "timing_ms": {"total": round((time.perf_counter() - start) * 1000, 2)},
            }
        except httpx.RequestError:
            return self._error(
                action, "Unable to reach Kajabi. Try again.", None, start
            )

    @staticmethod
    def _error(action, message, status_code, start):
        return {
            "status": "error",
            "action": action,
            "error": message,
            "status_code": status_code,
            "timing_ms": {"total": round((time.perf_counter() - start) * 1000, 2)},
        }
