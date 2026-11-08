"""Accredible Credential API v1: certificates, groups and account resources.

Request envelopes follow the provider's published cURL examples. Pagination is
explicit: each operation makes one request and returns the provider's metadata.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client


class AccredibleCertificatesAPIKey(BaseModel):
    model_config = ConfigDict(
        title="Accredible Certificates API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://dashboard.accredible.com/",
            "x-credential-instructions": "Copy your API key from the Accredible Dashboard. Paste only the key, without Token token=. Choose the region where your account is hosted; use Sandbox only for a sandbox key. Account-wide keys access all departments; department keys access only their own resources.",
        },
    )
    credential_type: Literal["accredible_certificates_api_key"] = Field(
        "accredible_certificates_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096,
                         repr=False, json_schema_extra={"ui:widget": "password"})
    region: Literal["us", "eu", "sandbox"] = Field("us", title="Account Region")

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the Accredible API key, without its header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    page: int = Field(1, ge=1, title="Page")
    page_size: int = Field(50, ge=1, le=100, title="Page Size")


class _Certificate(_Input):
    certificate_id: str = Field(..., min_length=1, max_length=256, title="Credential ID",
                                description="Accredible credential ID or your own credential identifier.")


class _Group(_Input):
    group_id: int = Field(..., ge=1, title="Group ID")


class GetIssuer(_Input):
    """Read the issuer profile for the connected account."""
    operation: Literal["get_issuer"] = "get_issuer"


class GetCertificate(_Certificate):
    """View a certificate or badge and its recipient."""
    operation: Literal["get_credential"] = "get_credential"


class _CertificateFields(_Input):
    name: str | None = Field(None, title="Credential Name")
    description: str | None = None
    issued_on: date | None = Field(None, title="Issue Date")
    expired_on: date | None = Field(None, title="Expiry Date")
    custom_attributes: dict[str, str] | None = None
    meta_data: dict[str, str] | None = None
    recipient_name: str | None = None
    recipient_email: str | None = None
    recipient_id: str | None = None
    complete: bool | None = None
    approve: bool | None = Field(None, title="Publish Credential",
                                description="Publishing can notify the recipient and consume account credits.")


class CreateCertificate(_CertificateFields):
    """Issue a credential to a recipient in an existing group."""
    operation: Literal["create_credential"] = "create_credential"
    group_id: int = Field(..., ge=1, title="Group ID")
    recipient_name: str = Field(..., min_length=1, title="Recipient Name")
    recipient_email: str = Field(..., min_length=1, title="Recipient Email")
    private: bool | None = Field(None, title="Private Credential")


class UpdateCertificate(_CertificateFields, _Certificate):
    """Update recipient details, dates, attributes or publication status."""
    operation: Literal["update_credential"] = "update_credential"
    group_id: int | None = Field(None, ge=1, title="Move to Group ID")


class DeleteCertificate(_Certificate):
    """Permanently delete a credential."""
    operation: Literal["delete_credential"] = "delete_credential"


class ListCertificates(_Page):
    """Read one page of credentials, optionally filtered by group."""
    operation: Literal["list_credentials"] = "list_credentials"
    group_id: str | None = Field(None, title="Group ID or Name")


class SearchCertificates(_Page):
    """Find credentials by recipient, group or creation/update date."""
    operation: Literal["search_credentials"] = "search_credentials"
    group_id: str | None = Field(None, title="Group ID or Name")
    recipient_name: str | None = None
    recipient_email: str | None = None
    recipient_id: str | None = None
    license_id: str | None = None
    meta_data: dict[str, str] | None = None
    start_date: date | None = None
    end_date: date | None = None
    start_updated_date: date | None = None
    end_updated_date: date | None = None


class GetCredentialAnalytics(_Certificate):
    """Read view and engagement analytics for a credential."""
    operation: Literal["get_credential_analytics"] = "get_credential_analytics"


class _GroupFields(_Input):
    name: str | None = Field(None, min_length=1, title="Internal Group Name")
    course_name: str | None = Field(None, min_length=1, title="Course Name")
    course_description: str | None = Field(None, min_length=1, title="Course Description")
    course_link: str | None = None
    certificate_design_id: int | None = Field(None, ge=1)
    badge_design_id: int | None = Field(None, ge=1)
    department_id: int | None = Field(None, ge=1)
    learning_outcomes: list[str] | None = None
    meta_data: dict[str, str] | None = None
    attach_pdf: bool | None = None
    allow_duplicate_credentials: bool | None = None
    auto_expiry: int | None = Field(None, ge=1)
    auto_expiry_unit: Literal["years", "months"] | None = None
    generate_private_credential: bool | None = None


class CreateGroup(_GroupFields):
    """Create an achievement group for issuing certificates and badges."""
    operation: Literal["create_group"] = "create_group"
    name: str = Field(..., min_length=1, title="Internal Group Name")
    course_name: str = Field(..., min_length=1, title="Course Name")
    course_description: str = Field(..., min_length=1, title="Course Description")


class GetGroup(_Group):
    """Read a group's course information and design settings."""
    operation: Literal["get_group"] = "get_group"


class UpdateGroup(_GroupFields, _Group):
    """Update group course information and issuance settings."""
    operation: Literal["update_group"] = "update_group"


class DeleteGroup(_Group):
    """Permanently delete a group."""
    operation: Literal["delete_group"] = "delete_group"


class SearchGroups(_Page):
    """Find account groups by name, course or department."""
    operation: Literal["search_groups"] = "search_groups"
    name: str | None = None
    course_name: str | None = None
    department_id: int | None = Field(None, ge=1)
    meta_data: dict[str, str] | None = None


class GetDesign(_Input):
    """View a certificate or badge design."""
    operation: Literal["get_design"] = "get_design"
    design_id: int = Field(..., ge=1, title="Design ID")


class SearchDesigns(_Input):
    """Find certificate or badge designs by kind and metadata."""
    operation: Literal["search_designs"] = "search_designs"
    kind: Literal["certificate", "badge"] | None = None
    meta_data: dict[str, str] | None = None


class SearchDepartments(_Page):
    """Find departments available to this API key."""
    operation: Literal["search_departments"] = "search_departments"
    meta_data: dict[str, str] | None = None


class SearchAttributeKeys(_Page):
    """Find custom attributes used in certificate and email templates."""
    operation: Literal["search_attribute_keys"] = "search_attribute_keys"
    name: str | None = None
    kind: Literal["text", "date", "email", "image"] | None = None
    department_id: int | None = Field(None, ge=1)


class ListAnalytics(_Page):
    """Read one page of credential engagement events."""
    operation: Literal["list_analytics"] = "list_analytics"
    start_date: date | None = None
    end_date: date | None = None
    group_id: int | None = Field(None, ge=1)
    department_id: int | None = Field(None, ge=1)


class ListSkillCategories(_Input):
    """Read available skill categories for group classification."""
    operation: Literal["list_skill_categories"] = "list_skill_categories"


AccredibleCertificatesConfig = Annotated[Union[
    GetIssuer, GetCertificate, CreateCertificate, UpdateCertificate, DeleteCertificate,
    ListCertificates, SearchCertificates, GetCredentialAnalytics, CreateGroup, GetGroup,
    UpdateGroup, DeleteGroup, SearchGroups, GetDesign, SearchDesigns, SearchDepartments,
    SearchAttributeKeys, ListAnalytics, ListSkillCategories,
], Field(discriminator="operation")]


class AccredibleCertificatesFullConfig(NodeConfig[AccredibleCertificatesConfig, AccredibleCertificatesAPIKey]):
    pass


# Each operation has exactly one published contract operation.
ROUTES = {
    "get_issuer": ("GET", "/v1/issuer/details"),
    "get_credential": ("GET", "/v1/credentials/{certificate_id}"),
    "create_credential": ("POST", "/v1/credentials"),
    "update_credential": ("PUT", "/v1/credentials/{certificate_id}"),
    "delete_credential": ("DELETE", "/v1/credentials/{certificate_id}"),
    "list_credentials": ("GET", "/v1/all_credentials"),
    "search_credentials": ("POST", "/v1/credentials/search"),
    "get_credential_analytics": ("POST", "/v1/credentials/analytics/{certificate_id}"),
    "create_group": ("POST", "/v1/issuer/groups"),
    "get_group": ("GET", "/v1/issuer/groups/{group_id}"),
    "update_group": ("PUT", "/v1/issuer/groups/{group_id}"),
    "delete_group": ("DELETE", "/v1/issuer/groups/{group_id}"),
    "search_groups": ("POST", "/v1/issuer/groups/search"),
    "get_design": ("GET", "/v1/designs/{design_id}"),
    "search_designs": ("POST", "/v1/designs/search"),
    "search_departments": ("POST", "/v1/departments/search"),
    "search_attribute_keys": ("POST", "/v1/attribute_keys/search"),
    "list_analytics": ("GET", "/v1/analytics"),
    "list_skill_categories": ("GET", "/v1/skill_categories"),
}
BASES = {"us": "https://api.accredible.com", "eu": "https://eu.api.accredible.com",
         "sandbox": "https://sandbox.api.accredible.com"}


class AccredibleCertificatesNode(WorkflowNode):
    integration_type = "automation-accredible-certificates"
    connection_evidence = ConnectionEvidence(noun="Accredible groups", operation="search_groups",
                                             identity_operation="get_issuer")

    @classmethod
    def get_config_model(cls):
        return AccredibleCertificatesFullConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if not credential:
            raise ValueError("Connect an Accredible Certificates API key")
        config = self.config.config
        method, path = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        for key in ("certificate_id", "group_id", "design_id"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", quote(str(values.pop(key)), safe=""))
        if config.operation in {"create_credential", "update_credential"}:
            recipient = {key.removeprefix("recipient_"): values.pop(key)
                         for key in ("recipient_name", "recipient_email", "recipient_id") if key in values}
            if recipient:
                values["recipient"] = recipient
            values = {"credential": values}
        elif config.operation in {"create_group", "update_group"}:
            values = {"group": values}
        elif config.operation == "search_credentials":
            for key in ("recipient_name", "recipient_email", "recipient_id"):
                if key in values:
                    values[key.replace("recipient_", "recipient.")] = values.pop(key)
        kwargs = {"params": values} if method == "GET" else {"json": values} if method != "DELETE" else {}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASES[credential.region] + path,
                headers={"Authorization": "Token token=" + credential.api_key,
                         "Accept": "application/json"}, **kwargs)
        if not 200 <= response.status_code < 300:
            # Preserve provider rejection text for the manual connect verdict.
            message = response.text[:4000].replace(credential.api_key, "[redacted]")
            raise ValueError(f"Accredible HTTP {response.status_code}: {message}")
        if response.status_code == 204 or not response.content:
            return {"status": "success", "data": None, "http_status": response.status_code}
        data = response.json()
        if isinstance(data, dict) and (data.get("success") is False or data.get("error")):
            raise ValueError("Accredible: " + str(data).replace(credential.api_key, "[redacted]"))
        result = {"status": "success", "data": data, "http_status": response.status_code}
        if isinstance(data, dict):
            for key in ("credentials", "groups", "designs", "departments", "attribute_keys", "events", "skill_categories"):
                if isinstance(data.get(key), list):
                    result["items"] = data[key]
                    break
            if "meta" in data:
                result["meta"] = data["meta"]
            if config.operation == "get_issuer" and isinstance(data.get("issuer"), dict):
                result["name"] = data["issuer"].get("name")
        return result
