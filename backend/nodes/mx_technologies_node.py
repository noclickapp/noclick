"""MX Platform API v20260929: client-scoped financial data and user management.

Each operation makes one request. Lists return one page and MX pagination;
callers explicitly choose subsequent pages. Writes are never retried.
Contract: https://docs.mx.com/openapi/platform-api/v20260929.yaml
"""
from __future__ import annotations

import base64
from datetime import date as ISODate
from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

CREDENTIAL_TYPE = "mx_technologies_api_key"
VERSION = "v20260929"
BASES = {"integration": "https://int-api.mx.com", "production": "https://api.mx.com"}


class MxTechnologiesApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="MX Technologies API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://dashboard.mx.com/",
            "x-credential-instructions": "Copy your MX client ID and API key from the MX dashboard. Select the environment that issued the key. NoClick uses HTTP Basic authentication with this pair."})
    credential_type: Literal["mx_technologies_api_key"] = Field(CREDENTIAL_TYPE, json_schema_extra={"ui:hidden": True})
    client_id: str = Field(..., min_length=1, title="Client ID", json_schema_extra={"ui:widget": "password"}, repr=False)
    api_key: str = Field(..., min_length=1, title="API Key", json_schema_extra={"ui:widget": "password"}, repr=False)
    environment: Literal["integration", "production"] = Field("integration", title="Environment")

    @field_validator("client_id", "api_key", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="MX credential")
        if not value or len(value) > 4096 or any(c.isspace() or c == ":" for c in value):
            raise ValueError("Paste the credential value without a header, colon or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def identifiers(cls, value, info):
        if info.field_name in {"user_identifier", "member_identifier", "user_guid", "account_guid", "transaction_guid"}:
            if not value or value in {".", ".."} or len(value) > 256 or any(ord(c) < 32 for c in value):
                raise ValueError("A nonempty MX resource identifier is required")
        return value


class _Page(_Input):
    page: int = Field(1, ge=1, title="Page")
    records_per_page: int = Field(25, ge=10, le=1000, title="Records Per Page")


class _User(_Input):
    user_identifier: str = Field(..., min_length=1, description="MX user GUID or your partner-defined user ID.")


class _UserPage(_User, _Page):
    pass


class _Member(_User):
    member_identifier: str = Field(..., min_length=1, description="MX member GUID or partner-defined member ID.")


class _MemberPage(_Member, _Page):
    pass


class _Account(_Input):
    user_guid: str = Field(..., min_length=1, title="User GUID")
    account_guid: str = Field(..., min_length=1, title="Account GUID")


class _Transaction(_Input):
    user_guid: str = Field(..., min_length=1, title="User GUID")
    transaction_guid: str = Field(..., min_length=1, title="Transaction GUID")


class _UserWrite(_Input):
    email: str | None = None
    id: str | None = Field(None, title="Partner User ID")
    is_disabled: bool | None = None
    metadata: str | None = Field(None, description="MX stores metadata as a string, including JSON encoded as a string.")

    @model_validator(mode="after")
    def nonempty(self):
        if not any(getattr(self, f) is not None for f in ("email", "id", "is_disabled", "metadata")):
            raise ValueError("Supply at least one user field")
        return self


class _TransactionPage(_UserPage):
    from_date: ISODate | None = Field(None, description="Inclusive start date (YYYY-MM-DD).")
    to_date: ISODate | None = Field(None, description="Inclusive end date (YYYY-MM-DD).")


class ListUsers(_Page):
    """List users using the MX Platform API."""
    operation: Literal["list_users"] = Field("list_users", title="List Users", json_schema_extra={"ui:hidden": True})


class CreateUser(_UserWrite):
    """Create user using the MX Platform API."""
    operation: Literal["create_user"] = Field("create_user", title="Create User", json_schema_extra={"ui:hidden": True})


class ReadUser(_User):
    """Read user using the MX Platform API."""
    operation: Literal["read_user"] = Field("read_user", title="Read User", json_schema_extra={"ui:hidden": True})


class UpdateUser(_User, _UserWrite):
    """Update user using the MX Platform API."""
    operation: Literal["update_user"] = Field("update_user", title="Update User", json_schema_extra={"ui:hidden": True})


class DeleteUser(_User):
    """Delete user using the MX Platform API."""
    operation: Literal["delete_user"] = Field("delete_user", title="Delete User", json_schema_extra={"ui:hidden": True})


class ListMembers(_UserPage):
    """List members using the MX Platform API."""
    operation: Literal["list_members"] = Field("list_members", title="List Members", json_schema_extra={"ui:hidden": True})


class ReadMember(_Member):
    """Read member using the MX Platform API."""
    operation: Literal["read_member"] = Field("read_member", title="Read Member", json_schema_extra={"ui:hidden": True})


class DeleteMember(_Member):
    """Delete member using the MX Platform API."""
    operation: Literal["delete_member"] = Field("delete_member", title="Delete Member", json_schema_extra={"ui:hidden": True})


class ReadMemberStatus(_Member):
    """Read member status using the MX Platform API."""
    operation: Literal["read_member_status"] = Field("read_member_status", title="Read Member Status", json_schema_extra={"ui:hidden": True})


class AggregateMember(_Member):
    """Aggregate member using the MX Platform API."""
    operation: Literal["aggregate_member"] = Field("aggregate_member", title="Aggregate Member", json_schema_extra={"ui:hidden": True})


class ListAccounts(_UserPage):
    """List accounts using the MX Platform API."""
    operation: Literal["list_accounts"] = Field("list_accounts", title="List Accounts", json_schema_extra={"ui:hidden": True})


class ReadAccount(_Account):
    """Read account using the MX Platform API."""
    operation: Literal["read_account"] = Field("read_account", title="Read Account", json_schema_extra={"ui:hidden": True})


class ListMemberAccounts(_MemberPage):
    """List member accounts using the MX Platform API."""
    operation: Literal["list_member_accounts"] = Field("list_member_accounts", title="List Member Accounts", json_schema_extra={"ui:hidden": True})


class ListTransactions(_TransactionPage):
    """List transactions using the MX Platform API."""
    operation: Literal["list_transactions"] = Field("list_transactions", title="List Transactions", json_schema_extra={"ui:hidden": True})


class ListAccountTransactions(_TransactionPage):
    """List account transactions using the MX Platform API."""
    operation: Literal["list_account_transactions"] = Field("list_account_transactions", title="List Account Transactions", json_schema_extra={"ui:hidden": True})
    account_guid: str = Field(..., min_length=1, title="Account GUID")


class ReadTransaction(_Transaction):
    """Read transaction using the MX Platform API."""
    operation: Literal["read_transaction"] = Field("read_transaction", title="Read Transaction", json_schema_extra={"ui:hidden": True})


class UpdateTransaction(_Transaction):
    """Update transaction using the MX Platform API."""
    operation: Literal["update_transaction"] = Field("update_transaction", title="Update Transaction", json_schema_extra={"ui:hidden": True})
    date: ISODate | None = None
    description: str | None = None
    memo: str | None = None
    category_guid: str | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not any(getattr(self, f) is not None for f in ("date", "description", "memo", "category_guid")):
            raise ValueError("Supply at least one transaction field")
        return self


class CreateManualTransaction(_User):
    """Create manual transaction using the MX Platform API."""
    operation: Literal["create_manual_transaction"] = Field("create_manual_transaction", title="Create Manual Transaction", json_schema_extra={"ui:hidden": True})
    account_guid: str = Field(..., min_length=1, title="Account GUID")
    amount: float = Field(..., allow_inf_nan=False)
    date: ISODate
    description: str = Field(..., min_length=1)
    type: Literal["CREDIT", "DEBIT"]
    category_guid: str | None = None
    currency_code: str | None = Field(None, min_length=3, max_length=3)
    memo: str | None = None


class ListInstitutions(_Page):
    """List institutions using the MX Platform API."""
    operation: Literal["list_institutions"] = Field("list_institutions", title="List Institutions", json_schema_extra={"ui:hidden": True})
    name: str | None = None
    iso_country_code: str | None = None


Operation = Annotated[Union[ListUsers, CreateUser, ReadUser, UpdateUser, DeleteUser, ListMembers, ReadMember, DeleteMember, ReadMemberStatus, AggregateMember, ListAccounts, ReadAccount, ListMemberAccounts, ListTransactions, ListAccountTransactions, ReadTransaction, UpdateTransaction, CreateManualTransaction, ListInstitutions], Field(discriminator="operation")]


class MxTechnologiesNodeConfig(NodeConfig[Operation, MxTechnologiesApiKeyCredential]):
    pass


ROUTES = {
    "list_users": ('GET', '/users', None),
    "create_user": ('POST', '/users', 'user'),
    "read_user": ('GET', '/users/{user_identifier}', None),
    "update_user": ('PUT', '/users/{user_identifier}', 'user'),
    "delete_user": ('DELETE', '/users/{user_identifier}', None),
    "list_members": ('GET', '/users/{user_identifier}/members', None),
    "read_member": ('GET', '/users/{user_identifier}/members/{member_identifier}', None),
    "delete_member": ('DELETE', '/users/{user_identifier}/members/{member_identifier}', None),
    "read_member_status": ('GET', '/users/{user_identifier}/members/{member_identifier}/status', None),
    "aggregate_member": ('POST', '/users/{user_identifier}/members/{member_identifier}/aggregate', None),
    "list_accounts": ('GET', '/users/{user_identifier}/accounts', None),
    "read_account": ('GET', '/users/{user_guid}/accounts/{account_guid}', None),
    "list_member_accounts": ('GET', '/users/{user_identifier}/members/{member_identifier}/accounts', None),
    "list_transactions": ('GET', '/users/{user_identifier}/transactions', None),
    "list_account_transactions": ('GET', '/users/{user_identifier}/accounts/{account_guid}/transactions', None),
    "read_transaction": ('GET', '/users/{user_guid}/transactions/{transaction_guid}', None),
    "update_transaction": ('PUT', '/users/{user_guid}/transactions/{transaction_guid}', 'transaction'),
    "create_manual_transaction": ('POST', '/users/{user_identifier}/accounts/{account_guid}/transactions', 'transaction'),
    "list_institutions": ('GET', '/institutions', None),
}


class MxTechnologiesNode(WorkflowNode):
    integration_type = "automation-mx-technologies"
    connection_evidence = ConnectionEvidence(operation="list_users", noun="users", label_keys=("email", "id", "guid"))

    @classmethod
    def get_config_model(cls):
        return MxTechnologiesNodeConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect an MX Technologies client ID and API key")
        credential = self.config.credentials
        config = self.config.config
        method, template, envelope = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        path_fields = [part[1:-1] for part in template.split("/") if part.startswith("{")]
        route = template.format(**{key: quote(values.pop(key), safe="") for key in path_fields})
        auth = base64.b64encode((credential.client_id + ":" + credential.api_key).encode()).decode()
        headers = {"Authorization": "Basic " + auth, "Accept": "application/json", "Accept-Version": VERSION}
        kwargs = {"params": values} if method == "GET" else {"json": {envelope: values}} if envelope else {}
        async with guarded_async_client(timeout=30.0, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASES[credential.environment] + route, headers=headers, **kwargs)
        if not 200 <= response.status_code < 300:
            message = response.text[:2000]
            for secret in (credential.client_id, credential.api_key, auth):
                message = message.replace(secret, "[redacted]")
            raise ValueError(f"MX API error (HTTP {response.status_code}): {message}")
        if response.status_code == 204:
            result = {"success": True, "http_status": 204}
        else:
            try:
                result = response.json()
            except ValueError:
                raise ValueError("MX returned an invalid JSON response") from None
            if not isinstance(result, dict) or result.get("error") or result.get("errors"):
                raise ValueError("MX returned an unexpected response envelope")
        await self.emit(result)
        return result
