"""Explicit Wild Apricot member operations against Public View API 9.08.0.

This is the member API, not the separate Admin API. Reads return one page;
writes can update the member profile or create/cancel/delete registrations.
Registration creation may send an invoice email as documented by the provider.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from nodes.oauth.wild_apricot_oauth import OAUTH_PROVIDER
from nodes.scopes.wild_apricot import WILD_APRICOT_SCOPES
from nodes.wild_apricot_operations import OPERATIONS
from utils.ssrf import guarded_async_client

BASE = "https://api.wildapricot.org/publicview/v1"
NODE_TYPE = "automation-wild-apricot"
Identifier = Annotated[int, Field(gt=0)]


class WildApricotOAuthCredential(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True, title="Wild Apricot OAuth", json_schema_extra={
        "x-credential-type": "oauth", "x-oauth-provider": "wild_apricot",
        "x-oauth-scopes": sorted(WILD_APRICOT_SCOPES.declared_scopes()),
        "x-credential-url": "https://gethelp.wildapricot.com/en/articles/180-authorizing-external-applications",
        "x-credential-instructions": "Sign in to your Wild Apricot organization. Access follows the member's permissions. An authorized application must allow single sign-on and trust the NoClick callback domain. These operations use the Member API, including profile and registration changes.",
    })
    credential_type: Literal["wild_apricot_oauth"] = Field("wild_apricot_oauth", json_schema_extra={"ui:hidden": True})
    access_token: str = Field(min_length=1, max_length=8192, repr=False, json_schema_extra={"ui:widget": "password"})
    refresh_token: str | None = Field(None, repr=False, json_schema_extra={"ui:widget": "password"})
    expires_at: str | None = None
    scope: str | None = None
    organization: str
    name: str | None = None

    @field_validator("organization")
    @classmethod
    def host(cls, value):
        return OAUTH_PROVIDER.context_fields["organization"].validate(value)

    @field_validator("access_token", "refresh_token")
    @classmethod
    def token(cls, value):
        if value is None:
            return value
        value = clean_secret(value, field_name="Token")
        if any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Use a token without whitespace or header prefixes")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def picker_metadata(cls, value):
        # The editor persists its chosen label and credential attachment next
        # to config fields. Neither is an API argument. Keep other extras strict.
        if isinstance(value, dict):
            return {k: v for k, v in value.items() if k not in {"account_id__label", "credentialIds"}}
        return value


class _Account(_Input):
    account_id: Identifier = Field(title="Account ID", json_schema_extra={"x-dynamic-options": {
        "field_name": "account_id", "allow_custom": True, "searchable": True,
        "placeholder": "Choose account", "custom_placeholder": "Enter account ID",
    }})


class _Page(_Account):
    top: int = Field(100, ge=1, le=100, description="Maximum records in this page ($top).")
    skip: int = Field(0, ge=0, description="Records to skip ($skip). Increment to fetch another page.")


class ListAccounts(_Input):
    operation: Literal["list_accounts"] = "list_accounts"


class GetAccount(_Account):
    operation: Literal["get_account"] = "get_account"


class ListContacts(_Page):
    operation: Literal["list_contacts"] = "list_contacts"
    simple_query: str | None = Field(None, max_length=1000, description="Contact search text.")
    select: str | None = Field(None, max_length=2000, description="Comma-separated API field names ($select).")


class GetContact(_Account):
    operation: Literal["get_contact"] = "get_contact"
    contact_id: Identifier


class GetMyContact(_Account):
    operation: Literal["get_my_contact"] = "get_my_contact"
    include_details: bool = True


class ContactFieldValue(_Input):
    FieldName: str = Field(min_length=1)
    SystemCode: str = Field(min_length=1)
    # The published CustomFieldValue description permits strings, numbers,
    # objects and arrays, despite its inconsistent Value.type = object.
    Value: Any = Field(description="Value matching the field definition returned by Wild Apricot.")


class UpdateMyContact(_Account):
    operation: Literal["update_my_contact"] = "update_my_contact"
    contact_id: Identifier = Field(description="Your current contact ID, returned by Get My Contact.")
    field_values: list[ContactFieldValue] = Field(min_length=1, max_length=100,
        description="Fields to update. The change applies to the signed-in member.")


class GetContactFields(_Account):
    operation: Literal["get_contact_fields"] = "get_contact_fields"
    show_section_dividers: bool = False


class ListMembershipLevels(_Account):
    operation: Literal["list_membership_levels"] = "list_membership_levels"


class ListEvents(_Page):
    operation: Literal["list_events"] = "list_events"
    filter: str | None = Field(None, max_length=2000, description="Documented $filter, for example IsUpcoming eq true.")


class GetEvent(_Account):
    operation: Literal["get_event"] = "get_event"
    event_id: Identifier


class ListRegistrations(_Page):
    operation: Literal["list_registrations"] = "list_registrations"
    event_id: Identifier | None = None
    is_upcoming: bool | None = None


class _Registration(_Account):
    registration_id: Identifier


class GetRegistration(_Registration):
    operation: Literal["get_registration"] = "get_registration"


class DeleteRegistration(_Registration):
    operation: Literal["delete_registration"] = "delete_registration"


class CancelRegistration(_Registration):
    operation: Literal["cancel_registration"] = "cancel_registration"


class _RegistrationFields(_Account):
    event_id: Identifier
    registration_type_id: Identifier
    registration_fields: list[ContactFieldValue] = Field(default_factory=list, max_length=100)
    show_to_public: bool = False
    for_wait_list: bool = False
    number_of_guests: int = Field(0, ge=0)
    registration_code: str | None = Field(None, max_length=200)


class CreateRegistration(_RegistrationFields):
    operation: Literal["create_registration"] = "create_registration"
    payment_method_type: str | None = Field(None, max_length=200,
        description="Provider payment method ID. When omitted, Wild Apricot sends an invoice email.")


class CalculateRegistrationCosts(_RegistrationFields):
    operation: Literal["calculate_registration_costs"] = "calculate_registration_costs"


class VerifyRegistrationCode(_Account):
    operation: Literal["verify_registration_code"] = "verify_registration_code"
    event_id: Identifier
    registration_type_id: Identifier
    code: str = Field(min_length=1, max_length=200)


class ListInvoices(_Page):
    operation: Literal["list_invoices"] = "list_invoices"
    open_balance_only: bool | None = None
    event_registration_id: Identifier | None = None


class ListPayments(_Page):
    operation: Literal["list_payments"] = "list_payments"


WildApricotOperation = Annotated[Union[
    ListAccounts, GetAccount, ListContacts, GetContact, GetMyContact, UpdateMyContact,
    GetContactFields, ListMembershipLevels, ListEvents, GetEvent, ListRegistrations,
    GetRegistration, CreateRegistration, DeleteRegistration, CalculateRegistrationCosts,
    VerifyRegistrationCode, CancelRegistration, ListInvoices, ListPayments,
], Field(discriminator="operation")]


class WildApricotConfig(NodeConfig[WildApricotOperation, WildApricotOAuthCredential]):
    pass


async def _request(token, method, path, *, params=None, body=None):
    # Only catalog paths reach this helper. Redirects cannot carry the bearer
    # credential to a different origin; no provider-returned links are followed.
    async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
        kwargs = {"headers": {"Authorization": f"Bearer {token}", "Accept": "application/json"}, "params": params}
        if body is not None:
            kwargs["json"] = body
        response = await client.request(method, BASE + path, **kwargs)
        response.raise_for_status()
        if len(response.content) > 4_000_000:
            raise ValueError("Wild Apricot response exceeds the page size limit")
        return response.json()


class WildApricotNode(WorkflowNode):
    integration_type = "automation-wild-apricot"
    scope_registry = WILD_APRICOT_SCOPES
    connection_evidence = ConnectionEvidence(field="account_id", noun="Wild Apricot accounts")

    @classmethod
    def get_config_model(cls):
        return WildApricotConfig

    @classmethod
    async def freshen_credential(cls, credential_data, *, pool=None, user_id=None, credential_id=None):
        from nodes.core.oauth_refresh import freshen_oauth_credential
        return await freshen_oauth_credential(
            credential_data, pool=pool, user_id=user_id, credential_id=credential_id,
            refresh=OAUTH_PROVIDER.bind_refresh(credential_data), provider="wild_apricot",
            additional_token_fields=OAUTH_PROVIDER.credential_fields,
        )

    @staticmethod
    async def _token(credential, *, user_id=None, credential_id=None, caller_path="execute"):
        from nodes.core.oauth_refresh import ensure_fresh_oauth_token
        return await ensure_fresh_oauth_token(
            credential=credential, user_id=user_id, credential_id=credential_id,
            refresh=OAUTH_PROVIDER.bind_refresh(credential), provider="wild_apricot",
            additional_token_fields=OAUTH_PROVIDER.credential_fields,
            caller_path=caller_path,
        )

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect your Wild Apricot organization")
        credential = self.config.credentials.model_dump()
        token = await self._token(credential, user_id=self.user_id,
            credential_id=(self.node_data or {}).get("credential_id"))
        self.config.credentials = WildApricotOAuthCredential.model_validate(credential)
        op = self.config.config
        method, path = OPERATIONS[op.operation]
        values = op.model_dump(exclude_none=True)
        for key in ("account_id", "contact_id", "event_id", "registration_id"):
            if "{" + key + "}" in path:
                path = path.replace("{" + key + "}", str(values[key]))
        params, body = {}, None
        if isinstance(op, _Page):
            params.update({"$top": op.top, "$skip": op.skip})
        query_fields = {
            "simple_query": "simpleQuery", "select": "$select", "filter": "$filter",
            "include_details": "includeDetails", "show_section_dividers": "showSectionDividers",
            "is_upcoming": "isUpcoming", "open_balance_only": "openBalanceOnly",
            "event_registration_id": "eventRegistrationId",
        }
        if method == "GET":
            params.update({wire: values[key] for key, wire in query_fields.items() if key in values})
            if isinstance(op, ListRegistrations) and op.event_id is not None:
                params["eventId"] = op.event_id
        if isinstance(op, UpdateMyContact):
            body = {"Id": op.contact_id, "FieldValues": [f.model_dump() for f in op.field_values]}
        elif isinstance(op, _RegistrationFields):
            names = {"event_id": "EventId", "registration_type_id": "RegistrationTypeId",
                "registration_fields": "RegistrationFields", "show_to_public": "ShowToPublic",
                "for_wait_list": "ForWaitList", "number_of_guests": "NumberOfGuests",
                "registration_code": "RegistrationCode", "payment_method_type": "PaymentMethodType"}
            body = {wire: values[key] for key, wire in names.items() if key in values}
        elif isinstance(op, VerifyRegistrationCode):
            body = {"eventId": op.event_id, "registrationTypeId": op.registration_type_id, "code": op.code}
        elif isinstance(op, CancelRegistration):
            body = op.registration_id
        data = await _request(token, method, path, params=params, body=body)
        # Preserve the contract's array/object/scalar responses, including false
        # and a newly-created registration's integer ID. Never reinterpret an
        # acknowledgment as a verified downstream effect or payment delivery.
        return {"operation": op.operation, "data": data}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, *, page_token=None, search=None):
        if field_name != "account_id":
            return []
        credential = WildApricotOAuthCredential.model_validate(credential_data).model_dump()
        token = await cls._token(credential, caller_path="dropdown")
        data = await _request(token, "GET", "/accounts")
        if not isinstance(data, list) or any(not isinstance(row, dict) or type(row.get("Id")) is not int or not isinstance(row.get("Name"), str) for row in data):
            raise ValueError("Wild Apricot returned an invalid account list")
        return [{"value": str(row["Id"]), "label": row["Name"]} for row in data
            if not search or search.casefold() in row["Name"].casefold()]
