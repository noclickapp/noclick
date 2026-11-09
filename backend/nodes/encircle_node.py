"""Encircle Public API 1.7.0 claim workflows using a pasted bearer token.

Contract: https://api.encircleapp.com/openapi_v3.json
Each operation makes one request. Paginated reads return the provider cursor;
no automatic retries of writes or traversal of response URLs is performed.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://api.encircleapp.com"


class EncircleTokenCredential(BaseModel):
    model_config = ConfigDict(title="Encircle Bearer Token", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://encircleapp.zendesk.com/hc/en-us/articles/360051960511-Bearer-Token",
            "x-credential-instructions": "Create a bearer token in Encircle and paste only the token here, without the Bearer prefix. The token's organization access controls which claims you can read and change."})
    credential_type: Literal["encircle_token"] = Field("encircle_token", json_schema_extra={"ui:hidden": True})
    api_token: str = Field(..., min_length=1, max_length=4096, title="Bearer token", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_token", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="Bearer token")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste only the bearer token, without a header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class _Page(_Input):
    order: Literal["newest", "oldest"] = "newest"
    limit: int = Field(50, ge=1, le=100)
    after: str | None = Field(None, max_length=8192, description="Opaque cursor.after returned by the previous page; omit for the first page")


class _ClaimFields(_Input):
    type_of_loss: str | None = Field(None, max_length=10000)
    locale: Literal["fr", "da", "es", "en"] | None = Field(None, description='A [BCP47](https://tools.ietf.org/html/bcp47#section-2.1)\n`language` tag without any subtags.\n\nEncircle currently only supports a subset of the languages of\nthe world, the allowed values are expected to expand in the\nfuture.')
    adjuster_name: str | None = Field(None, max_length=10000)
    assignment_identifier: str | None = Field(None, max_length=10000, description='Empty strings get coerced to null')
    cat_code: str | None = Field(None, max_length=10000)
    contents_estimate: int | None = Field(None, description='Represents a monetary amount as an integer in hundredths of\na dollar. For example, `550` would represent `$5.50`.')
    contractor_identifier: str | None = Field(None, max_length=10000, description='Empty strings get coerced to null')
    date_claim_created: date | None = Field(None, description='A [RFC 3339](https://tools.ietf.org/html/rfc3339#section-5.6)\ncompliant `full-date` string.')
    date_of_loss: date | None = Field(None, description='A [RFC 3339](https://tools.ietf.org/html/rfc3339#section-5.6)\ncompliant `full-date` string.\n\nThe provided date MUST be in the past.')
    default_depreciation: float | None = Field(None, ge=0.0, le=1.0, description='Represents a percentage value like sales tax or depreciation.\n\nMust be a number greater or equal to 0.\n\nFor example, `0.05` represents `5%`.')
    emergency_estimate: int | None = Field(None, description='Represents a monetary amount as an integer in hundredths of\na dollar. For example, `550` would represent `$5.50`.')
    full_address: str | None = Field(None, max_length=10000)
    insurer_identifier: str | None = Field(None, max_length=10000, description='Empty strings get coerced to null')
    loss_details: str | None = Field(None, max_length=10000)
    max_depreciation: float | None = Field(None, ge=0.0, le=1.0, description='Represents a percentage value like sales tax or depreciation.\n\nMust be a number greater or equal to 0.\n\nFor example, `0.05` represents `5%`.')
    policyholder_email_address: str | None = Field(None, max_length=10000)
    policyholder_name: str | None = Field(None, max_length=10000)
    policyholder_phone_number: str | None = Field(None, max_length=10000)
    project_manager_name: str | None = Field(None, max_length=10000)
    repair_estimate: int | None = Field(None, description='Represents a monetary amount as an integer in hundredths of\na dollar. For example, `550` would represent `$5.50`.')
    sales_tax: float | None = Field(None, ge=0.0, description='Represents a percentage value like sales tax or depreciation.\n\nMust be a number greater or equal to 0.\n\nFor example, `0.05` represents `5%`.')
    broker_or_agent_name: str | None = Field(None, max_length=10000)
    insurance_company_name: str | None = Field(None, max_length=10000)
    policy_number: str | None = Field(None, max_length=10000)

    @field_validator("date_of_loss")
    @classmethod
    def past_loss(cls, value):
        if value is not None and value >= date.today():
            raise ValueError("Date of loss must be in the past")
        return value


class EncircleListOrganizations(_Input):
    """Find organizations."""
    operation: Literal["list_organizations"] = "list_organizations"


class EncircleListBrands(_Input):
    """Find an organization's brands."""
    operation: Literal["list_brands"] = "list_brands"
    organization_id: str = Field(..., pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class EncircleGetUser(_Input):
    """Get a user by their email address."""
    operation: Literal["get_user"] = "get_user"
    email_address: str = Field(..., min_length=1, max_length=320)


class EncircleCreateClaim(_ClaimFields):
    """Create a property claim."""
    operation: Literal["create_claim"] = "create_claim"
    organization_id: str = Field(..., pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
    brand_id: int = Field(..., ge=1)


class EncircleListClaims(_Page):
    """Find property claims."""
    operation: Literal["list_claims"] = "list_claims"
    assignment_identifier: str | None = Field(None, max_length=10000)
    contractor_identifier: str | None = Field(None, max_length=10000)
    insurer_identifier: str | None = Field(None, max_length=10000)
    policyholder_name: str | None = Field(None, max_length=10000)


class EncircleGetClaim(_Input):
    """Get a property claim by ID."""
    operation: Literal["get_claim"] = "get_claim"
    property_claim_id: int = Field(..., ge=1)


class EncircleUpdateClaim(_ClaimFields):
    """Update a property claim."""
    operation: Literal["update_claim"] = "update_claim"
    property_claim_id: int = Field(..., ge=1)

    @model_validator(mode="after")
    def nonempty_update(self):
        if not any(getattr(self, key) is not None for key in ['type_of_loss', 'locale', 'adjuster_name', 'assignment_identifier', 'cat_code', 'contents_estimate', 'contractor_identifier', 'date_claim_created', 'date_of_loss', 'default_depreciation', 'emergency_estimate', 'full_address', 'insurer_identifier', 'loss_details', 'max_depreciation', 'policyholder_email_address', 'policyholder_name', 'policyholder_phone_number', 'project_manager_name', 'repair_estimate', 'sales_tax', 'broker_or_agent_name', 'insurance_company_name', 'policy_number']):
            raise ValueError("Supply at least one field to update")
        return self


class EncircleAssignUser(_Input):
    """Assign a user to a property claim."""
    operation: Literal["assign_user"] = "assign_user"
    property_claim_id: int = Field(..., ge=1)
    id: str = Field(..., min_length=1, max_length=320, title="User email address", description="Assignment grants this user access to the claim; unassignment removes it")


class EncircleListAssignments(_Input):
    """Find users assigned to a property claim."""
    operation: Literal["list_assignments"] = "list_assignments"
    property_claim_id: int = Field(..., ge=1)


class EncircleUnassignUser(_Input):
    """Unassign a user from a property claim."""
    operation: Literal["unassign_user"] = "unassign_user"
    property_claim_id: int = Field(..., ge=1)
    id: str = Field(..., min_length=1, max_length=320, title="User email address", description="Assignment grants this user access to the claim; unassignment removes it")


class EncircleCreateClaimNote(_Input):
    """Create a note."""
    operation: Literal["create_claim_note"] = "create_claim_note"
    property_claim_id: int = Field(..., ge=1)
    text: str = Field(..., min_length=1, max_length=100000, description="Note contents as Markdown. Creates a text-only note; a title can be added with Update Note.")


class EncircleListClaimNotes(_Page):
    """Find notes."""
    operation: Literal["list_claim_notes"] = "list_claim_notes"
    property_claim_id: int = Field(..., ge=1)


class EncircleGetClaimNote(_Input):
    """Get a note by ID."""
    operation: Literal["get_claim_note"] = "get_claim_note"
    property_claim_id: int = Field(..., ge=1)
    note_id: int = Field(..., ge=1)


class EncircleUpdateClaimNote(_Input):
    """Update a note."""
    operation: Literal["update_claim_note"] = "update_claim_note"
    property_claim_id: int = Field(..., ge=1)
    note_id: int = Field(..., ge=1)
    title: str | None = Field(None, max_length=10000)
    text: str | None = Field(None, max_length=100000, description="Markdown contents")

    @model_validator(mode="after")
    def nonempty_update(self):
        if not any(getattr(self, key) is not None for key in ['title', 'text']):
            raise ValueError("Supply at least one field to update")
        return self


class EncircleCreateStructure(_Input):
    """Create a structure."""
    operation: Literal["create_structure"] = "create_structure"
    property_claim_id: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=10000)


class EncircleListStructures(_Page):
    """Find structures."""
    operation: Literal["list_structures"] = "list_structures"
    property_claim_id: int = Field(..., ge=1)


class EncircleCreateRoom(_Input):
    """Create a room."""
    operation: Literal["create_room"] = "create_room"
    property_claim_id: int = Field(..., ge=1)
    structure_id: int = Field(..., ge=1)
    name: str = Field(..., min_length=1, max_length=10000)


class EncircleListRooms(_Page):
    """Find rooms."""
    operation: Literal["list_rooms"] = "list_rooms"
    property_claim_id: int = Field(..., ge=1)
    structure_id: int = Field(..., ge=1)


class EncircleCreateRoomNote(_Input):
    """Create a note."""
    operation: Literal["create_room_note"] = "create_room_note"
    property_claim_id: int = Field(..., ge=1)
    structure_id: int = Field(..., ge=1)
    room_id: int = Field(..., ge=1)
    text: str = Field(..., min_length=1, max_length=100000, description="Note contents as Markdown. Creates a text-only note; a title can be added with Update Note.")


class EncircleListRoomNotes(_Page):
    """Find notes."""
    operation: Literal["list_room_notes"] = "list_room_notes"
    property_claim_id: int = Field(..., ge=1)
    structure_id: int = Field(..., ge=1)
    room_id: int = Field(..., ge=1)


class EncircleGetRoomNote(_Input):
    """Get a note by ID."""
    operation: Literal["get_room_note"] = "get_room_note"
    property_claim_id: int = Field(..., ge=1)
    structure_id: int = Field(..., ge=1)
    room_id: int = Field(..., ge=1)
    note_id: int = Field(..., ge=1)


class EncircleUpdateRoomNote(_Input):
    """Update a note."""
    operation: Literal["update_room_note"] = "update_room_note"
    property_claim_id: int = Field(..., ge=1)
    structure_id: int = Field(..., ge=1)
    room_id: int = Field(..., ge=1)
    note_id: int = Field(..., ge=1)
    title: str | None = Field(None, max_length=10000)
    text: str | None = Field(None, max_length=100000, description="Markdown contents")

    @model_validator(mode="after")
    def nonempty_update(self):
        if not any(getattr(self, key) is not None for key in ['title', 'text']):
            raise ValueError("Supply at least one field to update")
        return self


EncircleConfig = Annotated[Union[
    EncircleListOrganizations,
    EncircleListBrands,
    EncircleGetUser,
    EncircleCreateClaim,
    EncircleListClaims,
    EncircleGetClaim,
    EncircleUpdateClaim,
    EncircleAssignUser,
    EncircleListAssignments,
    EncircleUnassignUser,
    EncircleCreateClaimNote,
    EncircleListClaimNotes,
    EncircleGetClaimNote,
    EncircleUpdateClaimNote,
    EncircleCreateStructure,
    EncircleListStructures,
    EncircleCreateRoom,
    EncircleListRooms,
    EncircleCreateRoomNote,
    EncircleListRoomNotes,
    EncircleGetRoomNote,
    EncircleUpdateRoomNote
], Field(discriminator="operation")]


class EncircleFullConfig(NodeConfig[EncircleConfig, EncircleTokenCredential]):
    pass


# Explicit request allowlist; paths and wire field names follow the pinned API contract.
ROUTES = {'list_organizations': ('GET', '/v1/organizations', [], [], []),
 'list_brands': ('GET', '/v1/organizations/{organization_id}/brands', ['organization_id'], [], []),
 'get_user': ('GET', '/v1/users/{email_address}', ['email_address'], [], []),
 'create_claim': ('POST',
                  '/v1/property_claims',
                  [],
                  [],
                  ['organization_id',
                   'brand_id',
                   'type_of_loss',
                   'locale',
                   'adjuster_name',
                   'assignment_identifier',
                   'cat_code',
                   'contents_estimate',
                   'contractor_identifier',
                   'date_claim_created',
                   'date_of_loss',
                   'default_depreciation',
                   'emergency_estimate',
                   'full_address',
                   'insurer_identifier',
                   'loss_details',
                   'max_depreciation',
                   'policyholder_email_address',
                   'policyholder_name',
                   'policyholder_phone_number',
                   'project_manager_name',
                   'repair_estimate',
                   'sales_tax',
                   'broker_or_agent_name',
                   'insurance_company_name',
                   'policy_number']),
 'list_claims': ('GET',
                 '/v1/property_claims',
                 [],
                 ['assignment_identifier',
                  'contractor_identifier',
                  'insurer_identifier',
                  'policyholder_name',
                  'order',
                  'limit',
                  'after'],
                 []),
 'get_claim': ('GET', '/v1/property_claims/{property_claim_id}', ['property_claim_id'], [], []),
 'update_claim': ('PATCH',
                  '/v1/property_claims/{property_claim_id}',
                  ['property_claim_id'],
                  [],
                  ['type_of_loss',
                   'locale',
                   'adjuster_name',
                   'assignment_identifier',
                   'cat_code',
                   'contents_estimate',
                   'contractor_identifier',
                   'date_claim_created',
                   'date_of_loss',
                   'default_depreciation',
                   'emergency_estimate',
                   'full_address',
                   'insurer_identifier',
                   'loss_details',
                   'max_depreciation',
                   'policyholder_email_address',
                   'policyholder_name',
                   'policyholder_phone_number',
                   'project_manager_name',
                   'repair_estimate',
                   'sales_tax',
                   'broker_or_agent_name',
                   'insurance_company_name',
                   'policy_number']),
 'assign_user': ('POST',
                 '/v1/property_claims/{property_claim_id}/assignments',
                 ['property_claim_id'],
                 [],
                 ['id']),
 'list_assignments': ('GET',
                      '/v1/property_claims/{property_claim_id}/assignments',
                      ['property_claim_id'],
                      [],
                      []),
 'unassign_user': ('DELETE',
                   '/v1/property_claims/{property_claim_id}/assignments',
                   ['property_claim_id'],
                   [],
                   ['id']),
 'create_claim_note': ('POST',
                       '/v2/property_claims/{property_claim_id}/notes',
                       ['property_claim_id'],
                       [],
                       ['text']),
 'list_claim_notes': ('GET',
                      '/v2/property_claims/{property_claim_id}/notes',
                      ['property_claim_id'],
                      ['order', 'limit', 'after'],
                      []),
 'get_claim_note': ('GET',
                    '/v2/property_claims/{property_claim_id}/notes/{note_id}',
                    ['property_claim_id', 'note_id'],
                    [],
                    []),
 'update_claim_note': ('PATCH',
                       '/v2/property_claims/{property_claim_id}/notes/{note_id}',
                       ['property_claim_id', 'note_id'],
                       [],
                       ['title', 'text']),
 'create_structure': ('POST',
                      '/v1/property_claims/{property_claim_id}/structures',
                      ['property_claim_id'],
                      [],
                      ['name']),
 'list_structures': ('GET',
                     '/v1/property_claims/{property_claim_id}/structures',
                     ['property_claim_id'],
                     ['order', 'limit', 'after'],
                     []),
 'create_room': ('POST',
                 '/v1/property_claims/{property_claim_id}/structures/{structure_id}/rooms',
                 ['property_claim_id', 'structure_id'],
                 [],
                 ['name']),
 'list_rooms': ('GET',
                '/v1/property_claims/{property_claim_id}/structures/{structure_id}/rooms',
                ['property_claim_id', 'structure_id'],
                ['order', 'limit', 'after'],
                []),
 'create_room_note': ('POST',
                      '/v2/property_claims/{property_claim_id}/structures/{structure_id}/rooms/{room_id}/notes',
                      ['property_claim_id', 'structure_id', 'room_id'],
                      [],
                      ['text']),
 'list_room_notes': ('GET',
                     '/v2/property_claims/{property_claim_id}/structures/{structure_id}/rooms/{room_id}/notes',
                     ['property_claim_id', 'structure_id', 'room_id'],
                     ['order', 'limit', 'after'],
                     []),
 'get_room_note': ('GET',
                   '/v2/property_claims/{property_claim_id}/structures/{structure_id}/rooms/{room_id}/notes/{note_id}',
                   ['property_claim_id', 'structure_id', 'room_id', 'note_id'],
                   [],
                   []),
 'update_room_note': ('PATCH',
                      '/v2/property_claims/{property_claim_id}/structures/{structure_id}/rooms/{room_id}/notes/{note_id}',
                      ['property_claim_id', 'structure_id', 'room_id', 'note_id'],
                      [],
                      ['title', 'text'])}


class EncircleNode(WorkflowNode):
    integration_type = "automation-encircle"
    connection_evidence = ConnectionEvidence(noun="organizations", operation="list_organizations")

    @classmethod
    def get_config_model(cls):
        return EncircleFullConfig

    async def execute(self, context):
        if not self.config.credentials:
            raise ValueError("Connect an Encircle bearer token")
        config = self.config.config
        method, path, path_fields, query_fields, body_fields = ROUTES[config.operation]
        values = config.model_dump(mode="json", exclude_none=True)
        for name in path_fields:
            path = path.replace("{" + name + "}", quote(str(values[name]), safe=""))
        params = {name: values[name] for name in query_fields if name in values}
        body = {name: values[name] for name in body_fields if name in values}
        headers = {"Authorization": "Bearer " + self.config.credentials.api_token,
                   "Accept": "application/json", "X-Encircle-Attribution": "NoClick"}
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.request(method, BASE + path, params=params,
                                            headers=headers, **({"json": body} if body_fields else {}))
        if not 200 <= response.status_code < 300:
            # Keep the provider's rejection text available to the common connect seam.
            detail = response.text[:2000].replace(self.config.credentials.api_token, "[redacted]")
            raise ValueError(f"Encircle API {response.status_code}: {detail}")
        if not response.content:
            raise ValueError("Encircle returned an empty response")
        data = response.json()
        if not isinstance(data, dict) or "error" in data or "errors" in data:
            raise ValueError("Encircle returned an unexpected response")
        if config.operation.startswith("list_"):
            if not isinstance(data.get("list"), list):
                raise ValueError("Encircle did not return a list")
            cursor = data.get("cursor")
            if cursor is not None and not isinstance(cursor, dict):
                raise ValueError("Encircle returned an invalid cursor")
            return {"status": "success", "items": data["list"], "cursor": cursor,
                    "next_after": cursor.get("after") if cursor else None}
        if "id" not in data:
            raise ValueError("Encircle did not return the requested resource")
        return {"status": "success", "data": data}
