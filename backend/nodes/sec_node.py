"""SEC EDGAR 1.11.0: https://api.edgarfiling.sec.gov/ ."""
from __future__ import annotations
import json
import re
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.edgarfiling.sec.gov"
TYPE = "sec_api_tokens"
CIK = Annotated[str, Field(pattern=r"^[0-9]{10}$")]
ACCESSION = Annotated[str, Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")]
EMAIL = Annotated[str, Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")]


class SecAPITokensCredential(BaseModel):
    model_config = ConfigDict(title="Sec API Tokens", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://filermanagement.edgarfiling.sec.gov/",
            "x-credential-instructions": "Paste a filer API token supplied by your technical administrator, your user API token from Filer Management, and the 10-digit CIK of the account you manage. Filer-management writes require the appropriate account administrator role. NoClick sends both tokens to the production SEC EDGAR API; submission-status and system-status reads use only the filer token."})
    credential_type: Literal["sec_api_tokens"] = Field(TYPE, json_schema_extra={"ui:hidden": True})
    filer_api_token: str = Field(..., min_length=1, max_length=16384, title="Filer API Token", repr=False, json_schema_extra={"ui:widget": "password"})
    user_api_token: str = Field(..., min_length=1, max_length=16384, title="User API Token", repr=False, json_schema_extra={"ui:widget": "password"})
    cik: CIK = Field(..., title="Filer CIK", description="Your account's 10-digit Central Index Key, including leading zeroes.")

    @field_validator("filer_api_token", "user_api_token", mode="before")
    @classmethod
    def token(cls, value):
        if not isinstance(value, str):
            raise ValueError("Paste the API token")
        value = clean_secret(value, field_name="API token", key=True)
        if not re.fullmatch(r"[A-Za-z0-9_.~-]+", value):
            raise ValueError("Paste one token without a Bearer prefix or separator")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Filer(_Input):
    cik: CIK | None = Field(None, title="Filer CIK", description="Omit to use the connected account's CIK. An alternate CIK must authorize these tokens.")


class GetFilerAccount(_Filer):
    """View filer account information. CCC secrets are omitted."""
    operation: Literal["get_filer_account"] = "get_filer_account"


class ListDelegations(_Filer):
    """View delegations to and from the filer."""
    operation: Literal["list_delegations"] = "list_delegations"


class RequestDelegationInvitations(_Filer):
    """Request delegation invitations from the specified CIKs."""
    operation: Literal["request_delegation_invitations"] = "request_delegation_invitations"
    ciks: list[CIK] = Field(..., min_length=1, title="Filer CIKs")


class SendDelegationInvitations(_Filer):
    """Send delegation invitations to the specified CIKs."""
    operation: Literal["send_delegation_invitations"] = "send_delegation_invitations"
    ciks: list[CIK] = Field(..., min_length=1, title="Filer CIKs")


class ListIndividuals(_Filer):
    """View individuals associated with the filer."""
    operation: Literal["list_individuals"] = "list_individuals"


class EmailRole(_Input):
    email: EMAIL
    inAdminRole: bool = Field(False, title="Account Administrator")
    inTechAdminRole: bool = Field(False, title="Technical Administrator")
    inUserRole: bool = Field(True, title="User")


class IndividualRole(EmailRole):
    firstName: str = Field(..., min_length=1, title="First Name")
    middleName: str | None = Field(None, title="Middle Name")
    lastName: str = Field(..., min_length=1, title="Last Name")


class AddIndividuals(_Filer):
    """Invite individuals and assign their filer roles; SEC sends invitations."""
    operation: Literal["add_individuals"] = "add_individuals"
    individuals: list[IndividualRole] = Field(..., min_length=1)


class ChangeIndividualRoles(_Filer):
    """Change existing individuals' administrator and user roles."""
    operation: Literal["change_individual_roles"] = "change_individual_roles"
    individuals: list[EmailRole] = Field(..., min_length=1)


class RemoveIndividuals(_Filer):
    """Remove individuals from the filer's account."""
    operation: Literal["remove_individuals"] = "remove_individuals"
    emails: list[EMAIL] = Field(..., min_length=1)


class GetFilingCredentials(_Filer):
    """Verify whether these credentials can file for the CIK."""
    operation: Literal["get_filing_credentials"] = "get_filing_credentials"


class GetSystemStatus(_Input):
    """Check EDGAR operating status using the filer token."""
    operation: Literal["get_system_status"] = "get_system_status"


class GetSubmissionStatus(_Input):
    """Check one submission by its accession number."""
    operation: Literal["get_submission_status"] = "get_submission_status"
    accession_number: ACCESSION


class GetMultipleSubmissionStatuses(_Input):
    """Check up to 25 submission accession numbers in one request."""
    operation: Literal["get_multiple_submission_statuses"] = "get_multiple_submission_statuses"
    accession_numbers: list[ACCESSION] = Field(..., min_length=1, max_length=25)


Operation = Annotated[Union[GetFilerAccount, ListDelegations, RequestDelegationInvitations,
    SendDelegationInvitations, ListIndividuals, AddIndividuals, ChangeIndividualRoles,
    RemoveIndividuals, GetFilingCredentials, GetSystemStatus, GetSubmissionStatus,
    GetMultipleSubmissionStatuses], Field(discriminator="operation")]


class SecConfig(NodeConfig[Operation, SecAPITokensCredential]):
    pass


ROUTES = {
    "get_filer_account": ("GET", "/fm/{cik}"),
    "list_delegations": ("GET", "/fm/{cik}/delegations"),
    "request_delegation_invitations": ("POST", "/fm/{cik}/delegationRequests"),
    "send_delegation_invitations": ("POST", "/fm/{cik}/delegations"),
    "list_individuals": ("GET", "/fm/{cik}/individuals"),
    "add_individuals": ("POST", "/fm/{cik}/individuals"),
    "change_individual_roles": ("PUT", "/fm/{cik}/individuals"),
    "remove_individuals": ("DELETE", "/fm/{cik}/individuals"),
    "get_filing_credentials": ("GET", "/fm/{cik}/verify"),
    "get_system_status": ("GET", "/status"),
    "get_submission_status": ("GET", "/submission/{accessionNumber}/status"),
    "get_multiple_submission_statuses": ("POST", "/submission/status"),
}


def _redact(value, credential):
    if isinstance(value, dict):
        return {k: _redact(v, credential) for k, v in value.items() if k.lower() != "ccc"}
    if isinstance(value, list):
        return [_redact(v, credential) for v in value]
    if isinstance(value, str):
        for secret in (credential.filer_api_token, credential.user_api_token):
            value = value.replace(secret, "[redacted]")
    return value


class SecNode(WorkflowNode):
    integration_type = "automation-sec"
    connection_evidence = ConnectionEvidence(noun="filer accounts", operation="get_filer_account",
        label_keys=("entityName", "cik"))

    @classmethod
    def get_config_model(cls):
        return SecConfig

    async def execute(self, inputs):
        config, credential = self.config.config, self.config.credentials
        if credential is None:
            raise ValueError("Connect SEC API tokens and a filer CIK")
        operation = config.operation
        method, template = ROUTES[operation]
        cik = getattr(config, "cik", None) or credential.cik
        path = template.format(cik=cik, accessionNumber=getattr(config, "accession_number", ""))
        token = credential.filer_api_token
        if path.startswith("/fm/"):
            token += "," + credential.user_api_token
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        body = None
        if isinstance(config, (RequestDelegationInvitations, SendDelegationInvitations)):
            body = config.ciks
        elif isinstance(config, (AddIndividuals, ChangeIndividualRoles)):
            body = [item.model_dump(exclude_none=True) for item in config.individuals]
        elif isinstance(config, RemoveIndividuals):
            body = config.emails
        elif isinstance(config, GetMultipleSubmissionStatuses):
            body = {"accessionNumbers": config.accession_numbers}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            async with client.stream(method, BASE + path, headers=headers,
                    **({"json": body} if body is not None else {})) as response:
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 8 * 1024 * 1024:
                        raise ValueError("SEC response exceeds the supported size")
                if response.status_code == 204 and operation == "get_multiple_submission_statuses":
                    return {"status": "success", "data": {"responses": []}, "items": []}
                try:
                    data = json.loads(raw)
                except (ValueError, UnicodeError):
                    raise ValueError(f"SEC returned an unreadable response (HTTP {response.status_code})") from None
                data = _redact(data, credential)
                if response.status_code != 200:
                    return {"status": "error", "http_status": response.status_code, "error": data}
                if not isinstance(data, dict) or not data:
                    raise ValueError("SEC returned an unexpected response shape")
                messages = data.get("messages", [])
                if not isinstance(messages, list):
                    raise ValueError("SEC returned unexpected messages")
                if any(isinstance(message, dict) and message.get("type") == "ERROR" for message in messages):
                    return {"status": "error", "error": data}
                result = {"status": "success", "data": data}
                if operation == "get_filer_account":
                    if not isinstance(data.get("filerInfo"), list):
                        raise ValueError("SEC did not return filer account information")
                    result["items"] = data["filerInfo"]
                return result
