"""EmailListVerify Customer API operations. Contract: https://api.emaillistverify.com/api-doc-json."""
from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence

class EmaillistverifyApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="EmailListVerify API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://apps.emaillistverify.com/api",
        "x-credential-instructions": "Copy your API key from the API section of EmailListVerify and paste it here."})
    credential_type: Literal["emaillistverify_api_key"] = Field("emaillistverify_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API Key", json_schema_extra={"ui:widget": "password"})

class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

class VerifyEmailConfig(_Input):
    """Verify email deliverability."""
    operation: Literal["verify_email"] = Field("verify_email", title="Verify Email", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., json_schema_extra={'examples': ['john.smith@gmail.com']})

class VerifyEmailDetailedConfig(_Input):
    """Verify email deliverability."""
    operation: Literal["verify_email_detailed"] = Field("verify_email_detailed", title="Verify Email Detailed", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., json_schema_extra={'examples': ['john.smith@gmail.com']})

class CreateEmailJobConfig(_Input):
    """Create asynchronous job that verifies email deliverability."""
    operation: Literal["create_email_job"] = Field("create_email_job", title="Create Email Job", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., json_schema_extra={'examples': ['john.smith@gmail.com']})
    quality: Literal['standard', 'high'] = Field('standard', json_schema_extra={'examples': ['high']})

class GetEmailJobConfig(_Input):
    """Verify email deliverability."""
    operation: Literal["get_email_job"] = Field("get_email_job", title="Get Email Job", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, json_schema_extra={})

class FindContactConfig(_Input):
    """Search for email address of a contact."""
    operation: Literal["find_contact"] = Field("find_contact", title="Find Contact", json_schema_extra={"ui:hidden": True})
    firstName: str | None = Field(None, json_schema_extra={'examples': ['Adela']})
    lastName: str | None = Field(None, json_schema_extra={'examples': ['Franey']})
    domain: str = Field(..., json_schema_extra={'examples': ['connelycorp.com']})

class CheckDisposableConfig(_Input):
    """Verify if a domain is disposable."""
    operation: Literal["check_disposable"] = Field("check_disposable", title="Check Disposable", json_schema_extra={"ui:hidden": True})
    domain: str = Field(..., max_length=255, json_schema_extra={'examples': ['temporarydomain.net']})

class CheckBlacklistsConfig(_Input):
    """Check IP or domain against blacklists."""
    operation: Literal["check_blacklists"] = Field("check_blacklists", title="Check Blacklists", json_schema_extra={"ui:hidden": True})
    value: str = Field(..., max_length=255, json_schema_extra={'examples': ['172.75.233.15']})

class GetListProgressConfig(_Input):
    """Retrieve progress information of email list."""
    operation: Literal["get_list_progress"] = Field("get_list_progress", title="Get List Progress", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, json_schema_extra={})

class ReverifyListConfig(_Input):
    """Start Deep Scan of finished email list."""
    operation: Literal["reverify_list"] = Field("reverify_list", title="Reverify List", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, json_schema_extra={'examples': ['2200875']})

class DeleteListConfig(_Input):
    """Delete finished email list."""
    operation: Literal["delete_list"] = Field("delete_list", title="Delete List", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, json_schema_extra={'examples': ['2200875']})

class GetCreditsConfig(_Input):
    """Retrieve details regarding your available credits."""
    operation: Literal["get_credits"] = Field("get_credits", title="Get Credits", json_schema_extra={"ui:hidden": True})

class CreatePlacementTestConfig(_Input):
    """Create inbox placement test."""
    operation: Literal["create_placement_test"] = Field("create_placement_test", title="Create Placement Test", json_schema_extra={"ui:hidden": True})
    name: str | None = Field(None, min_length=5, json_schema_extra={'examples': ['Q1 2025 Campaign Test']})
    webhookUrl: str | None = Field(None, json_schema_extra={'examples': ['https://yourapp.com/webhooks/placement-test']})

class GetPlacementTestConfig(_Input):
    """Get placement test results."""
    operation: Literal["get_placement_test"] = Field("get_placement_test", title="Get Placement Test", json_schema_extra={"ui:hidden": True})
    code: str = Field(..., min_length=1, json_schema_extra={'examples': ['ELV-A1B2C3D4E5']})

class GetFileInfoConfig(_Input):
    """Retrieve progress information of email list."""
    operation: Literal["get_file_info"] = Field("get_file_info", title="Get File Info", json_schema_extra={"ui:hidden": True})
    id: str = Field(..., json_schema_extra={'examples': ['2200875']})

Operation = Annotated[Union[VerifyEmailConfig, VerifyEmailDetailedConfig, CreateEmailJobConfig, GetEmailJobConfig, FindContactConfig, CheckDisposableConfig, CheckBlacklistsConfig, GetListProgressConfig, ReverifyListConfig, DeleteListConfig, GetCreditsConfig, CreatePlacementTestConfig, GetPlacementTestConfig, GetFileInfoConfig], Field(discriminator="operation")]

class EmaillistverifyConfig(NodeConfig[Operation, EmaillistverifyApiKeyCredential]):
    pass

ROUTES = {'verify_email': ('GET', '/api/verifyEmail', ['email'], [], []), 'verify_email_detailed': ('GET', '/api/verifyEmailDetailed', ['email'], [], []), 'create_email_job': ('POST', '/api/emailJobs', [], [], ['email', 'quality']), 'get_email_job': ('GET', '/api/emailJobs/{id}', [], ['id'], []), 'find_contact': ('POST', '/api/findContact', [], [], ['firstName', 'lastName', 'domain']), 'check_disposable': ('POST', '/api/checkDisposable', ['domain'], [], []), 'check_blacklists': ('POST', '/api/checkBlacklists', [], [], ['value']), 'get_list_progress': ('GET', '/api/maillists/{id}/progress', [], ['id'], []), 'reverify_list': ('POST', '/api/maillists/{id}/reverify', [], ['id'], []), 'delete_list': ('DELETE', '/api/maillists/{id}', [], ['id'], []), 'get_credits': ('GET', '/api/credits', [], [], []), 'create_placement_test': ('POST', '/api/inboxPlacementTests', [], [], ['name', 'webhookUrl']), 'get_placement_test': ('GET', '/api/inboxPlacementTests/{code}', [], ['code'], []), 'get_file_info': ('GET', '/api/getApiFileInfo', ['id'], [], [])}

class EmaillistverifyNode(WorkflowNode):
    integration_type = "automation-emaillistverify"
    connection_evidence = ConnectionEvidence(operation="get_credits", noun="credits")

    @classmethod
    def get_config_model(cls):
        return EmaillistverifyConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect an EmailListVerify API key")
        config = self.config.config
        method, path, query_fields, path_fields, body_fields = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True)
        for name in path_fields:
            path = path.replace("{" + name + "}", quote(values[name], safe=""))
        params = {name: values[name] for name in query_fields if name in values}
        kwargs = {"params": params}
        if body_fields:
            kwargs["json"] = {name: values[name] for name in body_fields if name in values}
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.request(method, "https://api.emaillistverify.com" + path,
                headers={"x-api-key": self.config.credentials.api_key}, **kwargs)
        if not 200 <= response.status_code < 300:
            try:
                message = response.json().get("message", "EmailListVerify request failed")
            except (ValueError, AttributeError):
                message = "EmailListVerify request failed"
            return {"status": "error", "http_status": response.status_code,
                "error": str(message).replace(self.config.credentials.api_key, "[redacted]")}
        if not response.content:
            data = None
        elif "json" in response.headers.get("content-type", ""):
            data = response.json()
        else:
            data = response.text
        if config.operation == "verify_email" and data == "error_credit":
            return {"status": "error", "error": "error_credit"}
        return {"status": "success", "data": data}
