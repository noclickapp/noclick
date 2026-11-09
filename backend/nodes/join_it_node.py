"""Join It memberships, organization details and offline payment records.

Each action makes one request to the pinned v1 API. List results are a single
page, never an assertion that every membership/payment was fetched. Payment
writes record money already collected elsewhere; they do not charge a card.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.join_it_operations import OPERATIONS
from nodes.scopes.join_it import JOIN_IT_SCOPES
from utils.ssrf import guarded_async_client

BASE_URL = "https://app.joinitapi.com/api/v1/organizations/me"


class JoinItOAuthCredential(BaseModel):
    model_config = ConfigDict(
        title="Join It OAuth", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-type": "oauth",
            "x-oauth-provider": "join-it",
            "x-oauth-scopes": sorted(JOIN_IT_SCOPES.declared_scopes()),
            "x-credential-url": "https://docs.joinitapi.com/docs/authentication",
            "x-credential-instructions": "Connect your Join It organization. The instance administrator must request an application key from Join It and configure the client ID, secret and redirect URI. An existing permanent OAuth access token can also be supplied by hand. Reconnect if revoked; Join It documents no expiry or refresh-token flow.",
        },
    )
    credential_type: Literal["join_it_oauth"] = Field("join_it_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(..., min_length=1, max_length=8192, repr=False, title="Access token", json_schema_extra={"ui:widget": "password"})

    @field_validator("access_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Access token")
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Paste the access token without the Bearer prefix or whitespace")
        return value


class Fields(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


Text = Annotated[str, Field(min_length=1, max_length=1000)]
Email = Annotated[str, Field(min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")]


class MembershipFilters(Fields):
    status: str | None = Field(None, description="Comma-separated status codes: 50 prospective, 75 pending, 100 active, 300 expired, 350 canceled.")
    membership_type_ids: Text | None = Field(None, description="Comma-separated Membership Type IDs.")


class Page(Fields):
    page: int = Field(1, ge=1, description="One page per execution. Keep filters unchanged when advancing the page.")
    count: int = Field(50, ge=1, le=1000, description="Page size; see Join It's Pagination guide.")


class ListMemberships(MembershipFilters, Page):
    operation: Literal["list_memberships"] = "list_memberships"
    email: Email | None = None
    membership_id: Text | None = Field(None, description="Exact internal membership _id filter.")
    external_id: Text | None = None


class GetMembership(Fields):
    operation: Literal["get_membership"] = "get_membership"
    membership_id: Text = Field(..., description="Exact internal membership _id. Returns the provider's filtered collection.")


class FindMembershipsByEmail(MembershipFilters, Page):
    operation: Literal["find_memberships_by_email"] = "find_memberships_by_email"
    email: Email = Field(..., description="Exact email match, not a partial search.")


class CreateMembership(Fields):
    operation: Literal["create_membership"] = "create_membership"
    membership_type_id: Text
    email: Email
    first_name: Text | None = None
    last_name: Text | None = None


class ListInternalMemberships(Fields):
    operation: Literal["list_internal_memberships"] = "list_internal_memberships"
    membership_id: Text | None = Field(None, description="Optional exact _id; returns admin-only membership fields.")


class ListPayments(Page):
    operation: Literal["list_payments"] = "list_payments"
    payment_date_start: date | None = None
    payment_date_end: date | None = None

    @model_validator(mode="after")
    def date_order(self):
        if self.payment_date_start and self.payment_date_end and self.payment_date_start > self.payment_date_end:
            raise ValueError("Payment start date must be on or before the end date")
        return self


class RecordPayment(Fields):
    operation: Literal["record_payment"] = "record_payment"
    email: Email = Field(..., description="Email of an existing membership.")
    amount: int = Field(..., strict=True, gt=0, description="Amount already collected, in the smallest currency unit (100 = $1.00 USD). Records an offline payment; does not collect money.")


class ListMembershipTypes(Fields):
    operation: Literal["list_membership_types"] = "list_membership_types"


class GetOrganization(Fields):
    operation: Literal["get_organization"] = "get_organization"


class VerifyMembership(MembershipFilters):
    operation: Literal["verify_membership"] = "verify_membership"
    email: Email
    send_internal_email_when_verification_failed: bool = Field(False, description="Explicitly opt in to emailing organization owners when verification fails. Disabled by default.")


JoinItConfig = Annotated[Union[ListMemberships, GetMembership, FindMembershipsByEmail,
    CreateMembership, ListInternalMemberships, ListPayments, RecordPayment,
    ListMembershipTypes, GetOrganization, VerifyMembership], Field(discriminator="operation")]


class JoinItNodeConfig(NodeConfig[JoinItConfig, JoinItOAuthCredential]):
    pass


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {_redact(key, token): _redact(item, token) for key, item in value.items()}
    return value


class JoinItNode(WorkflowNode):
    integration_type = "automation-join-it"
    scope_registry = JOIN_IT_SCOPES
    connection_evidence = ConnectionEvidence(noun="Join It organization", identity_operation="get_organization")
    edit_examples = ["Find a Join It membership by email", "Create a Join It membership", "Record an offline membership payment"]

    @classmethod
    def get_config_model(cls):
        return JoinItNodeConfig

    async def execute(self, inputs):
        if not isinstance(self.config, JoinItNodeConfig) or self.config.credentials is None:
            raise ValueError("Connect a Join It organization")
        config, credential = self.config.config, self.config.credentials
        self.scope_registry.require(config.operation)
        method, path = OPERATIONS[config.operation]
        values = config.model_dump(mode="json", exclude_none=True, exclude={"operation"})
        if "membership_id" in values:
            values["_id"] = values.pop("membership_id")
        # This switch is documented as a boolean query value, not Python's 'False'.
        flag = "send_internal_email_when_verification_failed"
        if flag in values:
            values[flag] = "true" if values[flag] else "false"
        request = {"json": values} if config.operation == "record_payment" else {"params": values}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"Authorization": "Bearer " + credential.access_token, "Accept": "application/json"}, **request)
        except Exception:
            raise ValueError("Join It request did not complete; inspect write results before retrying") from None
        verification_miss = config.operation == "verify_membership" and response.status_code == 404
        if response.status_code != 200 and not verification_miss:
            message = _redact(response.text, credential.access_token)[:1000]
            raise ValueError(f"Join It API error {response.status_code}: {message}")
        if len(response.content) > 10_000_000:
            raise ValueError("Join It response exceeds the supported size")
        if not response.content and config.operation == "record_payment":
            data = None  # The pinned payment-write contract declares no response body.
        else:
            try:
                data = response.json()
            except ValueError:
                raise ValueError("Join It returned an invalid JSON response") from None
            if not isinstance(data, (dict, list)):
                raise ValueError("Join It returned an unexpected response shape")
            if isinstance(data, dict) and (any(data.get(k) for k in ("error", "errors")) or data.get("success") is False or data.get("status") in ("error", "failed")):
                raise ValueError("Join It rejected the request: " + str(_redact(data, credential.access_token))[:1000])
        if config.operation == "get_organization" and (not isinstance(data, dict) or not isinstance(data.get("name"), str) or not data["name"].strip()):
            raise ValueError("Join It organization identity could not be verified")
        if config.operation == "verify_membership":
            if not isinstance(data, dict) or type(data.get("verified")) is not bool or data["verified"] != (response.status_code == 200):
                raise ValueError("Join It membership verification response was not confirmed")
        result = {"status": "success", "operation": config.operation, "data": _redact(data, credential.access_token), "http_status": response.status_code}
        if isinstance(config, Page):
            # No automatic retries or extra requests; a full page may have a successor.
            result["pagination"] = {"page": config.page, "count": config.count, "next_page": config.page + 1 if isinstance(data, list) and len(data) == config.count else None}
        if method == "POST":
            result["write_acknowledged"] = True
            result["readback_verified"] = False
        await self.emit(result)
        return result
