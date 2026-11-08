"""Bouncer email, domain, batch, sampling and toxicity API operations."""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.usebouncer.com"


class BouncerAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Bouncer API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://app.usebouncer.com/",
        "x-credential-instructions": "In Bouncer, open API and generate an API key. Paste the key here. NoClick checks your available credits without spending verification credits.",
    })
    credential_type: Literal["bouncer_api_key"] = Field("bouncer_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header prefix or whitespace")
        return value


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetCredits(_Config):
    operation: Literal["get_credits"] = Field("get_credits", title="Get Available Credits", json_schema_extra={"ui:hidden": True})


class VerifyEmail(_Config):
    operation: Literal["verify_email"] = Field("verify_email", title="Verify Email", json_schema_extra={"ui:hidden": True})
    email: str = Field(..., min_length=1, description="Email address to verify; malformed addresses can be checked too.")
    timeout: int = Field(10, ge=1, description="Verification timeout in seconds.")


class _Emails(_Config):
    emails: list[str] = Field(..., min_length=1, max_length=100000, description="Email addresses to process. Verification and toxicity jobs consume Bouncer credits.")


class CreateBatch(_Emails):
    operation: Literal["create_batch"] = Field("create_batch", title="Create Verification Batch", json_schema_extra={"ui:hidden": True})
    callback: str | None = Field(None, description="Optional callback URL that Bouncer will POST when the batch completes.")


class _Batch(_Config):
    batch_id: str = Field(..., min_length=1, description="batchId returned by Create Verification Batch.")


class GetBatch(_Batch):
    operation: Literal["get_batch"] = Field("get_batch", title="Get Batch Status", json_schema_extra={"ui:hidden": True})
    with_stats: bool = Field(False, description="Include additional processing statistics.")


class DeleteBatch(_Batch):
    operation: Literal["delete_batch"] = Field("delete_batch", title="Delete Verification Batch", description="Permanently deletes the emails and results associated with this batch.", json_schema_extra={"ui:hidden": True})


class FinishBatch(_Batch):
    operation: Literal["finish_batch"] = Field("finish_batch", title="Finish Verification Batch", description="Stops remaining verification and returns unused credits. Poll status until completed before downloading results.", json_schema_extra={"ui:hidden": True})


class GetBatchResults(_Batch):
    operation: Literal["get_batch_results"] = Field("get_batch_results", title="Get Batch Results", json_schema_extra={"ui:hidden": True})
    download: Literal["all", "deliverable", "risky", "undeliverable", "unknown"] = "all"


class VerifyBatchSync(_Emails):
    operation: Literal["verify_batch_sync"] = Field("verify_batch_sync", title="Verify Emails Synchronously", json_schema_extra={"ui:hidden": True})


class CreateBatchSample(_Emails):
    operation: Literal["create_batch_sample"] = Field("create_batch_sample", title="Create Batch Sample", json_schema_extra={"ui:hidden": True})


class _Sample(_Config):
    sample_id: str = Field(..., min_length=1, description="ID returned by Create Batch Sample.")


class GetBatchSample(_Sample):
    operation: Literal["get_batch_sample"] = Field("get_batch_sample", title="Get Batch Sample Status", json_schema_extra={"ui:hidden": True})


class CreateToxicityList(_Emails):
    operation: Literal["create_toxicity_list"] = Field("create_toxicity_list", title="Create Toxicity List Job", json_schema_extra={"ui:hidden": True})


class _List(_Config):
    list_id: str = Field(..., min_length=1, description="ID returned by Create Toxicity List Job.")


class GetToxicityList(_List):
    operation: Literal["get_toxicity_list"] = Field("get_toxicity_list", title="Get Toxicity List Status", json_schema_extra={"ui:hidden": True})


class DeleteToxicityList(_List):
    operation: Literal["delete_toxicity_list"] = Field("delete_toxicity_list", title="Delete Toxicity List Job", description="Permanently deletes the toxicity list job.", json_schema_extra={"ui:hidden": True})


class GetToxicityResults(_List):
    operation: Literal["get_toxicity_results"] = Field("get_toxicity_results", title="Get Toxicity List Results", json_schema_extra={"ui:hidden": True})


class VerifyDomain(_Config):
    operation: Literal["verify_domain"] = Field("verify_domain", title="Verify Domain", json_schema_extra={"ui:hidden": True})
    domain: str = Field(..., min_length=1, description="Domain to verify, for example usebouncer.com.")


BouncerConfig = Annotated[Union[GetCredits, VerifyEmail, CreateBatch, GetBatch, DeleteBatch,
    FinishBatch, GetBatchResults, VerifyBatchSync, CreateBatchSample, GetBatchSample,
    CreateToxicityList, GetToxicityList, DeleteToxicityList, GetToxicityResults, VerifyDomain], Field(discriminator="operation")]


class BouncerFullConfig(NodeConfig[BouncerConfig, BouncerAPIKeyCredential]):
    pass


# One native operation per published method/path. Job operations do not poll or retry writes.
ROUTES = {
    "get_credits": ("GET", "/v1.1/credits"),
    "verify_email": ("GET", "/v1.1/email/verify"),
    "create_batch": ("POST", "/v1.1/email/verify/batch"),
    "get_batch": ("GET", "/v1.1/email/verify/batch/{batch_id}"),
    "delete_batch": ("DELETE", "/v1.1/email/verify/batch/{batch_id}"),
    "finish_batch": ("POST", "/v1.1/email/verify/batch/{batch_id}/finish"),
    "get_batch_results": ("GET", "/v1.1/email/verify/batch/{batch_id}/download"),
    "verify_batch_sync": ("POST", "/v1.1/email/verify/batch/sync"),
    "create_batch_sample": ("POST", "/v1/email/verify/batch/sample"),
    "get_batch_sample": ("GET", "/v1/email/verify/batch/sample/{sample_id}"),
    "create_toxicity_list": ("POST", "/v1/toxicity/list"),
    "get_toxicity_list": ("GET", "/v1/toxicity/list/{list_id}"),
    "delete_toxicity_list": ("DELETE", "/v1/toxicity/list/{list_id}"),
    "get_toxicity_results": ("GET", "/v1/toxicity/list/{list_id}/data"),
    "verify_domain": ("GET", "/v1.1/domain"),
}


class BouncerNode(WorkflowNode):
    integration_type = "automation-bouncer"
    connection_evidence = ConnectionEvidence(operation="get_credits", noun="available Bouncer credits")

    @classmethod
    def get_config_model(cls):
        return BouncerFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Bouncer API key")
        op = self.config.config
        method, path = ROUTES[op.operation]
        values = op.model_dump(exclude_none=True)
        for name in ("batch_id", "sample_id", "list_id"):
            if name in values:
                identifier = values[name]
                if identifier in {".", ".."} or any(c in identifier for c in "/\\?#"):
                    raise ValueError("Use a single Bouncer resource ID")
                path = path.replace("{" + name + "}", quote(identifier, safe=""))
        params = {}
        if isinstance(op, VerifyEmail):
            params = {"email": op.email, "timeout": op.timeout}
        elif isinstance(op, GetBatch):
            params = {"with-stats": str(op.with_stats).lower()}
        elif isinstance(op, GetBatchResults):
            params = {"download": op.download}
        elif isinstance(op, VerifyDomain):
            params = {"domain": op.domain}
        elif isinstance(op, CreateBatch) and op.callback:
            params = {"callback": op.callback}
        kwargs = {}
        if isinstance(op, _Emails):
            # The published batch/toxicity schemas say string but their examples send arrays.
            kwargs["json"] = [{"email": email} for email in op.emails] if isinstance(op, (CreateBatch, CreateBatchSample)) else op.emails
        async with guarded_async_client(timeout=120, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE_URL + path, params=params,
                headers={"x-api-key": self.config.credentials.api_key, "Accept": "application/json"}, **kwargs)
        response.raise_for_status()
        if response.is_redirect:
            raise ValueError("Bouncer redirected the request")
        body = response.json()
        if isinstance(body, dict) and body.get("error"):
            message = str(body.get("message") or body["error"]).replace(self.config.credentials.api_key, "[redacted]")
            raise ValueError(message)
        is_array = isinstance(op, (GetBatchResults, VerifyBatchSync, GetToxicityResults))
        if not isinstance(body, list if is_array else dict):
            raise ValueError("Unexpected Bouncer response shape")
        if isinstance(op, GetCredits) and (type(body.get("credits")) is not int or body["credits"] < 0):
            raise ValueError("Bouncer did not return available credits")
        evidence = {"items": [{"name": f"{body['credits']} available credits"}]} if isinstance(op, GetCredits) else {}
        return {"status": "success", "operation": op.operation, "data": body, "http_status": response.status_code, **evidence}
