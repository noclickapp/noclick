"""Clearout v2 email verification, discovery, bulk job management and account reads.

Contract: https://openapi.gitbook.com/o/OFXJzrq0w7UPFwDGIM0a/spec/co-openapi-bundle-19.yaml
No automatic retries: verification/discovery can consume credits and timeouts may leave work running.
"""
from typing import Annotated, Literal, Union, Optional
from pydantic import BaseModel, ConfigDict, Field
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.vendor_mcp import mcp_credential
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client


class ClearoutCredential(BaseModel):
    model_config = ConfigDict(title="Clearout API Token")
    credential_type: Literal["clearout_api_token"] = "clearout_api_token"
    api_token: str = Field(..., min_length=1, json_schema_extra={
        "ui:widget": "password", "x-credential-url": "https://app.clearout.io/api",
        "x-credential-instructions": "In Clearout, open API and create an API token. Paste the token here.",
        "ui:help": "Paste your Clearout API token without the Bearer prefix."})


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClearoutVerifyEmail(_Input):
    """Instant Verify."""
    operation: Literal["verify_email"] = Field("verify_email", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1)
    timeout: Optional[int] = Field(130000, ge=1000, le=180000, description="Provider timeout in milliseconds. Timed out work may continue in the background.")

class ClearoutGetVerificationStatus(_Input):
    """Bulk Verify Progress Status."""
    operation: Literal["get_verification_status"] = Field("get_verification_status", json_schema_extra={"ui:hidden": True})
    list_id: str = Field(..., min_length=1)

class ClearoutRemoveVerificationList(_Input):
    """Bulk Verify Result Removal."""
    operation: Literal["remove_verification_list"] = Field("remove_verification_list", json_schema_extra={"ui:hidden": True})
    list_id: str = Field(..., min_length=1)
    ignore_result: Optional[bool] = Field(False)

class ClearoutCancelVerification(_Input):
    """Bulk Verify Cancel."""
    operation: Literal["cancel_verification"] = Field("cancel_verification", json_schema_extra={"ui:hidden": True})
    list_id: str = Field(..., min_length=1)

class ClearoutListVerifications(_Input):
    """Get Email Verifier List."""
    operation: Literal["list_verifications"] = Field("list_verifications", json_schema_extra={"ui:hidden": True})
    limit: Optional[int] = Field(10, ge=1, le=100)
    start_after: Optional[str] = Field(None, min_length=1)

class ClearoutVerifyCatchall(_Input):
    """Catch-All Verify."""
    operation: Literal["verify_catchall"] = Field("verify_catchall", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1)
    timeout: Optional[int] = Field(None, description="Provider timeout in milliseconds. Timed out work may continue in the background.")

class ClearoutVerifyDisposable(_Input):
    """Disposable Account Verify."""
    operation: Literal["verify_disposable"] = Field("verify_disposable", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1)
    timeout: Optional[int] = Field(None, description="Provider timeout in milliseconds. Timed out work may continue in the background.")

class ClearoutVerifyBusiness(_Input):
    """Business Account Verify."""
    operation: Literal["verify_business"] = Field("verify_business", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1)
    timeout: Optional[int] = Field(None, description="Provider timeout in milliseconds. Timed out work may continue in the background.")

class ClearoutVerifyFree(_Input):
    """Free Account Verify."""
    operation: Literal["verify_free"] = Field("verify_free", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1)
    timeout: Optional[int] = Field(None, description="Provider timeout in milliseconds. Timed out work may continue in the background.")

class ClearoutVerifyRole(_Input):
    """Role Account Verify."""
    operation: Literal["verify_role"] = Field("verify_role", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1)
    timeout: Optional[int] = Field(None, description="Provider timeout in milliseconds. Timed out work may continue in the background.")

class ClearoutVerifyGibberish(_Input):
    """Gibberish Account Verify."""
    operation: Literal["verify_gibberish"] = Field("verify_gibberish", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1)
    timeout: Optional[int] = Field(None, description="Provider timeout in milliseconds. Timed out work may continue in the background.")

class ClearoutGetAvailableCredits(_Input):
    """Get Available Credits."""
    operation: Literal["get_available_credits"] = Field("get_available_credits", json_schema_extra={"ui:hidden": True})

class ClearoutFindEmail(_Input):
    """Instant Email Finder."""
    operation: Literal["find_email"] = Field("find_email", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    domain: str = Field(..., min_length=1)
    timeout: Optional[int] = Field(30000, le=180000, description="Provider timeout in milliseconds. Timed out work may continue in the background.")
    queue: Optional[bool] = Field(True)

class ClearoutGetFinderStatus(_Input):
    """Instant Email Finder Status."""
    operation: Literal["get_finder_status"] = Field("get_finder_status", json_schema_extra={"ui:hidden": True})
    qid: str = Field(..., min_length=1)

class ClearoutGetBulkFinderStatus(_Input):
    """Bulk Email Finder Progress Status."""
    operation: Literal["get_bulk_finder_status"] = Field("get_bulk_finder_status", json_schema_extra={"ui:hidden": True})
    list_id: str = Field(..., min_length=1)

class ClearoutRemoveFinderList(_Input):
    """Bulk Email Finder Removal."""
    operation: Literal["remove_finder_list"] = Field("remove_finder_list", json_schema_extra={"ui:hidden": True})
    list_id: str = Field(..., min_length=1)
    ignore_result: Optional[bool] = Field(False)

class ClearoutCancelFinder(_Input):
    """Bulk Finder Cancel."""
    operation: Literal["cancel_finder"] = Field("cancel_finder", json_schema_extra={"ui:hidden": True})
    list_id: str = Field(..., min_length=1)

class ClearoutListFinderJobs(_Input):
    """Get Email Finder List."""
    operation: Literal["list_finder_jobs"] = Field("list_finder_jobs", json_schema_extra={"ui:hidden": True})
    limit: int = Field(..., ge=1, le=100)
    start_after: Optional[str] = Field(None, min_length=1)

class ClearoutFindCompanyDomains(_Input):
    """Find Domains for Company."""
    operation: Literal["find_company_domains"] = Field("find_company_domains", json_schema_extra={"ui:hidden": True})
    query: str = Field(..., min_length=1)

class ClearoutFindMx(_Input):
    """Find MX."""
    operation: Literal["find_mx"] = Field("find_mx", json_schema_extra={"ui:hidden": True})
    domain: str = Field(..., min_length=1)
    timeout: Optional[float] = Field(90000, description="Provider timeout in milliseconds. Timed out work may continue in the background.")

class ClearoutFindWhois(_Input):
    """Find Whois."""
    operation: Literal["find_whois"] = Field("find_whois", json_schema_extra={"ui:hidden": True})
    domain: str = Field(..., min_length=1)
    timeout: Optional[float] = Field(90000, description="Provider timeout in milliseconds. Timed out work may continue in the background.")

class ClearoutValidateName(_Input):
    """Name validate."""
    operation: Literal["validate_name"] = Field("validate_name", json_schema_extra={"ui:hidden": True})
    name: str = Field(..., min_length=1)
    timeout: Optional[int] = Field(8000, ge=1000, le=10000, description="Provider timeout in milliseconds. Timed out work may continue in the background.")

class ClearoutGetPlans(_Input):
    """Get Plans and Addons."""
    operation: Literal["get_plans"] = Field("get_plans", json_schema_extra={"ui:hidden": True})

class ClearoutGetCredits(_Input):
    """Get Remaining Credits."""
    operation: Literal["get_credits"] = Field("get_credits", json_schema_extra={"ui:hidden": True})

class ClearoutGetLimits(_Input):
    """Get Service Limits."""
    operation: Literal["get_limits"] = Field("get_limits", json_schema_extra={"ui:hidden": True})


# Clearout's own MCP server: agents get its tools through a person's Clearout sign-in.
ClearoutMcpCredential = mcp_credential("clearout", "https://mcp.clearout.io/mcp", app="Clearout")


ClearoutConfig = Annotated[Union[ClearoutVerifyEmail, ClearoutGetVerificationStatus, ClearoutRemoveVerificationList, ClearoutCancelVerification, ClearoutListVerifications, ClearoutVerifyCatchall, ClearoutVerifyDisposable, ClearoutVerifyBusiness, ClearoutVerifyFree, ClearoutVerifyRole, ClearoutVerifyGibberish, ClearoutGetAvailableCredits, ClearoutFindEmail, ClearoutGetFinderStatus, ClearoutGetBulkFinderStatus, ClearoutRemoveFinderList, ClearoutCancelFinder, ClearoutListFinderJobs, ClearoutFindCompanyDomains, ClearoutFindMx, ClearoutFindWhois, ClearoutValidateName, ClearoutGetPlans, ClearoutGetCredits, ClearoutGetLimits], Field(discriminator="operation")]


class ClearoutFullConfig(NodeConfig[ClearoutConfig, Union[ClearoutCredential, ClearoutMcpCredential]]):
    pass


ROUTES = {'verify_email': ('POST', '/email_verify/instant'), 'get_verification_status': ('GET', '/email_verify/bulk/progress_status'), 'remove_verification_list': ('POST', '/email_verify/list/remove'), 'cancel_verification': ('POST', '/email_verify/list/cancel'), 'list_verifications': ('POST', '/email_verify/list'), 'verify_catchall': ('POST', '/email/verify/catchall'), 'verify_disposable': ('POST', '/email/verify/disposable'), 'verify_business': ('POST', '/email/verify/business'), 'verify_free': ('POST', '/email/verify/free'), 'verify_role': ('POST', '/email/verify/role'), 'verify_gibberish': ('POST', '/email/verify/gibberish'), 'get_available_credits': ('GET', '/email_verify/getcredits'), 'find_email': ('POST', '/email_finder/instant'), 'get_finder_status': ('GET', '/email_finder/instant/queue_status'), 'get_bulk_finder_status': ('GET', '/email_finder/bulk/progress_status'), 'remove_finder_list': ('POST', '/email_finder/list/remove'), 'cancel_finder': ('POST', '/email_finder/list/cancel'), 'list_finder_jobs': ('POST', '/email_finder/list'), 'find_company_domains': ('GET', '/public/companies/autocomplete'), 'find_mx': ('POST', '/domain/resolve/mx'), 'find_whois': ('POST', '/domain/resolve/whois'), 'validate_name': ('POST', '/name/validate'), 'get_plans': ('GET', '/account/myplans'), 'get_credits': ('GET', '/account/credits'), 'get_limits': ('GET', '/account/limits')}


class ClearoutNode(WorkflowNode):
    integration_type = "automation-clearout"
    credential_provider_labels = {"clearout": "Clearout Account"}
    connection_evidence = ConnectionEvidence(operation="get_credits", noun="Clearout account credits")

    @classmethod
    def get_config_model(cls):
        return ClearoutFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Clearout API token")
        config = self.config.config
        method, path = ROUTES[config.operation]
        payload = config.model_dump(exclude={"operation"}, exclude_none=True)
        async with guarded_async_client(timeout=200, follow_redirects=False, trust_env=False) as client:
            base = "https://api.clearout.io" if config.operation == "find_company_domains" else "https://api.clearout.io/v2"
            response = await client.request(method, base + path,
                headers={"Authorization": "Bearer " + self.config.credentials.api_token,
                         "Accept": "application/json"},
                **({"params": payload} if method == "GET" else {"json": payload}))
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = {"message": "Clearout returned HTTP " + str(response.status_code)}
            return {"status": "error", "http_status": response.status_code, "error": body}
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Clearout returned an unexpected response")
        return body
