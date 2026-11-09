"""Xama Hub's published v0.1 API, using a user-supplied bearer token.

Contract: https://apidocs.xamatech.com/openapi/bombpot.yaml
Token acquisition: https://apidocs.xamatech.com/guides/authentication/
Each operation makes one request. Lists return one page, never claim all records.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client, SSRFError

BASE = "https://xamahub.xamatech.com"
TYPE = "xama_hub_bearer_token"


class XamaHubBearerTokenCredential(BaseModel):
    model_config = ConfigDict(title="Xama Hub Bearer Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://platform.xamatech.com/portal/hub/settings/apps/open-api",
            "x-credential-instructions": "Obtain an access token using your Open API Application ID and Secret as described in Xama's authentication guide. Paste the access_token without the Bearer prefix. Tokens expire; replace this token when Xama rejects it. Tenant ID is your Xama Hub client identifier, different from the OAuth Application ID.",
            "x-help-url": "https://apidocs.xamatech.com/guides/authentication/",
        })
    credential_type: Literal["xama_hub_bearer_token"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    tenant_id: str = Field(..., title="Tenant ID", min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")
    access_token: str = Field(..., title="Access Token", min_length=1, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token")
    @classmethod
    def token(cls, value):
        if any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the access token without whitespace or the Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Page(_Input):
    page: int = Field(1, ge=1, description="Page number, starting at 1.")
    page_size: int = Field(100, ge=1, le=100, title="Page Size")


class _Account(_Input):
    account_id: str = Field(..., title="Account ID", min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")


class _Contact(_Account):
    contact_id: str = Field(..., title="Contact ID", min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")


class _Person(_Input):
    first_name: str = Field(..., min_length=1, title="First Name")
    last_name: str = Field(..., min_length=1, title="Last Name")
    email: str = Field(..., title="Email", json_schema_extra={"format": "email"})
    middle_name: str | None = None
    phone: str | None = None
    date_of_birth: date | None = Field(None, title="Date of Birth")

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        import re
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address")
        return value


class GetClient(_Input):
    operation: Literal["get_client"] = Field("get_client", title="Get Tenant Client", json_schema_extra={"ui:hidden": True})


class ListAccounts(_Page):
    operation: Literal["list_accounts"] = Field("list_accounts", title="List Accounts", json_schema_extra={"ui:hidden": True})


class GetAccount(_Account):
    operation: Literal["get_account"] = Field("get_account", title="Get Account", json_schema_extra={"ui:hidden": True})


class CreateAccount(_Person):
    operation: Literal["create_account"] = Field("create_account", title="Create Account", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1, title="Account Name")
    account_type: Literal["COMPANY", "INDIVIDUAL", "UNKNOWN"] = Field(..., title="Account Type")
    reg_number: str | None = Field(None, title="Company Registration Number")
    suppress_notifications: bool = Field(False, description="Ask Xama to suppress creation notifications.")


class PatchAccount(_Account):
    operation: Literal["patch_account"] = Field("patch_account", title="Set Account Status", json_schema_extra={"ui:hidden": True})
    status: Literal["ACTIVE", "ARCHIVED"] = Field(..., title="Status")
    archived_at: date | None = None


class ListContacts(_Page):
    operation: Literal["list_contacts"] = Field("list_contacts", title="List Tenant Contacts", json_schema_extra={"ui:hidden": True})


class ListAccountContacts(_Account, _Page):
    operation: Literal["list_account_contacts"] = Field("list_account_contacts", title="List Account Contacts", json_schema_extra={"ui:hidden": True})


class GetContact(_Contact):
    operation: Literal["get_contact"] = Field("get_contact", title="Get Contact", json_schema_extra={"ui:hidden": True})


class CreateContact(_Account, _Person):
    operation: Literal["create_contact"] = Field("create_contact", title="Create Contact", json_schema_extra={"ui:hidden": True})
    suppress_notifications: bool = Field(False, description="Ask Xama to suppress creation notifications.")


class ReplaceContact(_Contact, _Person):
    operation: Literal["replace_contact"] = Field("replace_contact", title="Replace Contact", description="Full replacement. Omitted optional contact details may be cleared by Xama.", json_schema_extra={"ui:hidden": True})


class PatchContact(_Contact):
    operation: Literal["patch_contact"] = Field("patch_contact", title="Set Contact Status", json_schema_extra={"ui:hidden": True})
    status: Literal["ACTIVE", "ARCHIVED"] = Field(..., title="Status")
    archived_at: date | None = None


class DeleteContact(_Contact):
    operation: Literal["delete_contact"] = Field("delete_contact", title="Delete Contact", description="Deletes the contact in Xama Hub.", json_schema_extra={"ui:hidden": True})


class GetAmlReport(_Contact):
    operation: Literal["get_aml_report"] = Field("get_aml_report", title="Get AML Report", json_schema_extra={"ui:hidden": True})


class InitiateAmlReport(_Contact):
    operation: Literal["initiate_aml_report"] = Field("initiate_aml_report", title="Initiate AML Report", description="Starts an AML lookup; may consume Xama credits. Completion is asynchronous.", json_schema_extra={"ui:hidden": True})
    trigger_lookup: bool = Field(True, title="Trigger Lookup")


class GetOnboardingReport(_Contact):
    operation: Literal["get_onboarding_report"] = Field("get_onboarding_report", title="Get Onboarding Report", json_schema_extra={"ui:hidden": True})


class InitiateOnboardingReport(_Contact):
    operation: Literal["initiate_onboarding_report"] = Field("initiate_onboarding_report", title="Initiate Onboarding Report", description="Starts onboarding using Xama's configured defaults; may email the contact and consume credits. Completion is asynchronous.", json_schema_extra={"ui:hidden": True})
    trigger_lookup: bool = Field(True, title="Trigger Lookup")


class CancelOnboardingReport(_Contact):
    operation: Literal["cancel_onboarding_report"] = Field("cancel_onboarding_report", title="Cancel Onboarding Report", json_schema_extra={"ui:hidden": True})


class ListRiskAssessments(_Account, _Page):
    operation: Literal["list_risk_assessments"] = Field("list_risk_assessments", title="List Risk Assessments", json_schema_extra={"ui:hidden": True})


class GetRiskAssessment(_Account):
    operation: Literal["get_risk_assessment"] = Field("get_risk_assessment", title="Get Risk Assessment", json_schema_extra={"ui:hidden": True})
    risk_assessment_id: str = Field(..., title="Risk Assessment ID", min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")
    with_data: bool = Field(True, title="Include Related Data")


class CreateRiskAssessment(_Account):
    operation: Literal["create_risk_assessment"] = Field("create_risk_assessment", title="Create Risk Assessment", description="Creates an assessment in progress. Xama requires a known account type and no other open assessment.", json_schema_extra={"ui:hidden": True})
    template_id: str | None = Field(None, title="Questionnaire Template ID")
    risk_level: Literal["LOW", "NORMAL", "HIGH"] | None = None
    notes: str | None = None
    prepared_by: str | None = None


class ListDocuments(_Page):
    operation: Literal["list_documents"] = Field("list_documents", title="List Tenant Documents", json_schema_extra={"ui:hidden": True})


Operation = Annotated[Union[GetClient, ListAccounts, GetAccount, CreateAccount, PatchAccount,
    ListContacts, ListAccountContacts, GetContact, CreateContact, ReplaceContact, PatchContact,
    DeleteContact, GetAmlReport, InitiateAmlReport, GetOnboardingReport, InitiateOnboardingReport,
    CancelOnboardingReport, ListRiskAssessments, GetRiskAssessment, CreateRiskAssessment, ListDocuments],
    Field(discriminator="operation")]


class XamaHubConfig(NodeConfig[Operation, XamaHubBearerTokenCredential]):
    pass


ROOT = "/api/clients/{tenant_id}"
ACCOUNT = ROOT + "/accounts/{account_id}"
CONTACT = ACCOUNT + "/contacts/{contact_id}"
# Fixed one-to-one mapping to operations in the pinned provider contract.
OPERATIONS = {
    "get_client": ("GET", ROOT, 200),
    "list_accounts": ("GET", ROOT + "/accounts", 200),
    "get_account": ("GET", ACCOUNT, 200),
    "create_account": ("POST", ROOT + "/accounts", 201),
    "patch_account": ("PATCH", ACCOUNT, 204),
    "list_contacts": ("GET", ROOT + "/contacts", 200),
    "list_account_contacts": ("GET", ACCOUNT + "/contacts", 200),
    "get_contact": ("GET", CONTACT, 200),
    "create_contact": ("POST", ACCOUNT + "/contacts", 201),
    "replace_contact": ("PUT", CONTACT, 204),
    "patch_contact": ("PATCH", CONTACT, 204),
    "delete_contact": ("DELETE", CONTACT, 204),
    "get_aml_report": ("GET", CONTACT + "/reports/aml", 200),
    "initiate_aml_report": ("PUT", CONTACT + "/reports/aml", 204),
    "get_onboarding_report": ("GET", CONTACT + "/reports/onboarding", 200),
    "initiate_onboarding_report": ("PUT", CONTACT + "/reports/onboarding", 204),
    "cancel_onboarding_report": ("DELETE", CONTACT + "/reports/onboarding", 204),
    "list_risk_assessments": ("GET", ACCOUNT + "/risk-assessments", 200),
    "get_risk_assessment": ("GET", ACCOUNT + "/risk-assessments/{risk_assessment_id}", 200),
    "create_risk_assessment": ("POST", ACCOUNT + "/risk-assessments", 201),
    "list_documents": ("GET", ROOT + "/documents", 200),
}
PERSON_FIELDS = {"first_name", "last_name", "middle_name", "email", "phone", "date_of_birth"}


class XamaHubNode(WorkflowNode):
    integration_type = "automation-xama-hub"
    connection_evidence = ConnectionEvidence(noun="accounts", operation="list_accounts", label_keys=("name", "id"))

    @classmethod
    def get_config_model(cls):
        return XamaHubConfig

    async def execute(self, inputs):
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a Xama Hub bearer token and tenant ID")
        config = self.config.config
        op = config.operation
        method, template, expected = OPERATIONS[op]
        values = config.model_dump(mode="json", exclude_none=True)
        path = template.format(**{k: quote(v, safe="") for k, v in
            {"tenant_id": credential.tenant_id, **{k: v for k, v in values.items() if k.endswith("_id")}}.items()})
        params = {}
        if isinstance(config, _Page):
            params.update(page=config.page, page_size=config.page_size)
        if op == "get_risk_assessment":
            params["with_data"] = str(config.with_data).lower()
        body = None
        if op in {"create_contact", "replace_contact", "create_account"}:
            person = {k: v for k, v in values.items() if k in PERSON_FIELDS}
            body = {"name": config.name, "type": config.account_type, "primary_contact": person} if op == "create_account" else person
            if op == "create_account" and config.reg_number is not None:
                body["reg_number"] = config.reg_number
            if op == "replace_contact":
                body["id"] = config.contact_id
        elif op in {"patch_account", "patch_contact"}:
            body = {k: values[k] for k in ("status", "archived_at") if k in values}
        elif op.startswith("initiate_"):
            body = {"trigger_lookup": config.trigger_lookup}
        elif op == "create_risk_assessment":
            body = {"status": "IN_PROGRESS", **{k: values[k] for k in ("template_id", "risk_level", "notes", "prepared_by") if k in values}}
        output = {"operation": op}
        try:
            headers = {"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"}
            if "suppress_notifications" in values:
                headers["X-Suppress-Notifications"] = str(config.suppress_notifications).lower()
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers=headers,
                    **({"json": body} if body is not None else {}))
            if response.status_code != expected:
                # Preserve provider rejection text for connection evidence, redact credentials.
                message = "Xama Hub returned HTTP " + str(response.status_code)
                try:
                    problem = response.json()
                    if isinstance(problem, dict):
                        detail = problem.get("detail") or problem.get("message") or problem.get("title")
                        if isinstance(detail, str):
                            message = detail.replace(credential.access_token, "[redacted]")[:2000]
                except ValueError:
                    pass
                return {**output, "status": "error", "http_status": response.status_code, "error": message}
            if expected == 204:
                return {**output, "status": "success", "accepted": True}
            if len(response.content) > 10_000_000:
                raise ValueError("Response is too large")
            data = response.json()
            if not isinstance(data, dict) or data.get("error") or (isinstance(data.get("status"), int) and data["status"] >= 400):
                raise ValueError("Unexpected response envelope")
            if isinstance(config, _Page):
                items = data.get("items")
                if not isinstance(items, list) or any(not isinstance(x, dict) for x in items):
                    raise ValueError("Expected a page of items")
                # Keep provider metadata. A full last page without totals cannot prove exhaustion.
                totals = data.get("total_pages")
                has_more = config.page < totals if type(totals) is int else (None if len(items) >= config.page_size else False)
                return {**output, "status": "success", **data, "has_more": has_more,
                    "next_page": config.page + 1 if has_more is not False else None, "page_only": True}
            return {**output, "status": "success", "item": data}
        except (httpx.HTTPError, SSRFError, ValueError):
            return {**output, "status": "error", "error": "Xama Hub request could not be confirmed; inspect before retrying a write"}
