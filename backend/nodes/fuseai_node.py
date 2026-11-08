"""Fuse Business API v1: account, prospect lists, campaigns and enrichment.

Contract: https://docs.fuseai.com/openapi.json (1.0.0).
Each operation makes one request; pagination and async states are returned as supplied.
"""
from typing import Annotated, Literal, Optional, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.tryfuse.ai/api/v1"


class FuseaiAPITokenCredential(BaseModel):
    model_config = ConfigDict(
        title="Fuseai API Token",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://docs.fuseai.com/",
            "x-credential-instructions": "Paste your Fuse API token (af_…). NoClick sends it as the HTTP Basic username with an empty password. The account identity read verifies the token. Enrichment operations can spend Fuse credits.",
        },
    )
    credential_type: Literal["fuseai_api_token"] = Field(
        "fuseai_api_token", json_schema_extra={"ui:hidden": True}
    )
    api_token: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        title="API token",
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_token", mode="before")
    @classmethod
    def validate_token(cls, value):
        value = clean_secret(value, field_name="API token")
        if ":" in value or any(char.isspace() for char in value):
            raise ValueError("Paste only the API token, without a header or colon")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class FuseaiGetAccountConfig(_Input):
    """Get the token owner's identity."""

    operation: Literal["get_account"] = Field(
        "get_account", json_schema_extra={"ui:hidden": True}
    )


class FuseaiGetCreditsConfig(_Input):
    """Get the token owner's credit balance."""

    operation: Literal["get_credits"] = Field(
        "get_credits", json_schema_extra={"ui:hidden": True}
    )


class FuseaiListListsConfig(_Input):
    """List the token owner's prospect lists."""

    operation: Literal["list_lists"] = Field(
        "list_lists", json_schema_extra={"ui:hidden": True}
    )
    limit: int = Field(
        50,
        ge=1,
        le=1000,
        description="Page size: how many lists to return per page (1-1000, default 50).",
    )
    pageNum: int = Field(
        1,
        ge=1,
        description="1-based page number (default 1); lists are ordered newest-created first.",
    )
    entityType: Optional[Literal["contactList", "companyList"]] = Field(
        None,
        description="Restrict to one list kind: contactList (people) or companyList (companies); omit for both.",
    )
    search: Optional[str] = Field(
        None,
        min_length=1,
        max_length=200,
        description="Free text (1-200 characters), matched as a case-insensitive substring of the list name; every character is literal, so * and ? are not wildcards and no other field (folder, owner, description) is searched.",
    )


class FuseaiCreateListConfig(_Input):
    """Create a prospect list."""

    operation: Literal["create_list"] = Field(
        "create_list", json_schema_extra={"ui:hidden": True}
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="List name (1-255 characters, trimmed); must be unique in the workspace or the call answers 409 LIST_NAME_TAKEN.",
    )
    entityType: Literal["contactList", "companyList"] = Field(
        "contactList",
        description="Kind of list to create: contactList (people, default) or companyList (companies).",
    )


class FuseaiGetListConfig(_Input):
    """Get one list's metadata."""

    operation: Literal["get_list"] = Field(
        "get_list", json_schema_extra={"ui:hidden": True}
    )
    listId: str = Field(
        ...,
        pattern=r"^[a-fA-F0-9]{24}$",
        description="24-character hex id of the list (from GET /business/lists).",
    )
    include: Optional[Literal["columns"]] = Field(
        None,
        description="Set to columns to add the list's custom column definitions (id, name, type) to the response.",
    )


class FuseaiRenameListConfig(_Input):
    """Rename a prospect list."""

    operation: Literal["rename_list"] = Field(
        "rename_list", json_schema_extra={"ui:hidden": True}
    )
    listId: str = Field(
        ...,
        pattern=r"^[a-fA-F0-9]{24}$",
        description="24-character hex id of the list (from GET /business/lists).",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="New list name (1-255 characters, trimmed); must be unique in the workspace or the call answers 409 LIST_NAME_TAKEN.",
    )


class FuseaiDeleteListConfig(_Input):
    """Delete a list."""

    operation: Literal["delete_list"] = Field(
        "delete_list", json_schema_extra={"ui:hidden": True}
    )
    listId: str = Field(
        ...,
        pattern=r"^[a-fA-F0-9]{24}$",
        description="24-character hex id of the list (from GET /business/lists).",
    )


class FuseaiListRowsConfig(_Input):
    """List a list's contacts (with ids and column values)."""

    operation: Literal["list_rows"] = Field(
        "list_rows", json_schema_extra={"ui:hidden": True}
    )
    listId: str = Field(
        ...,
        pattern=r"^[a-fA-F0-9]{24}$",
        description="24-character hex id of the list (from GET /business/lists).",
    )
    limit: int = Field(
        100,
        ge=1,
        le=1000,
        description="Page size: how many rows to return per page (1-1000, default 100).",
    )
    pageNum: int = Field(1, ge=1, description="1-based page number (default 1).")


class FuseaiAddMembersConfig(_Input):
    """Add existing contacts to a list (by id)."""

    operation: Literal["add_members"] = Field(
        "add_members", json_schema_extra={"ui:hidden": True}
    )
    listId: str = Field(
        ...,
        pattern=r"^[a-fA-F0-9]{24}$",
        description="24-character hex id of the list (from GET /business/lists).",
    )
    contactIds: list[Annotated[str, Field(pattern=r"^[a-fA-F0-9]{24}$")]] = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Contact ids (24-character hex, 1-5000 per call) to add to or remove from the list; ids already in the list are ignored on add.",
    )


class FuseaiRemoveMembersConfig(_Input):
    """Remove contacts from a list."""

    operation: Literal["remove_members"] = Field(
        "remove_members", json_schema_extra={"ui:hidden": True}
    )
    listId: str = Field(
        ...,
        pattern=r"^[a-fA-F0-9]{24}$",
        description="24-character hex id of the list (from GET /business/lists).",
    )
    contactIds: list[Annotated[str, Field(pattern=r"^[a-fA-F0-9]{24}$")]] = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="Contact ids (24-character hex, 1-5000 per call) to add to or remove from the list; ids already in the list are ignored on add.",
    )


class FuseaiListColumnsConfig(_Input):
    """List a list's custom column definitions."""

    operation: Literal["list_columns"] = Field(
        "list_columns", json_schema_extra={"ui:hidden": True}
    )
    listId: str = Field(
        ...,
        pattern=r"^[a-fA-F0-9]{24}$",
        description="24-character hex id of the list (from GET /business/lists).",
    )


class FuseaiCreateColumnConfig(_Input):
    """Create a custom column on a list."""

    operation: Literal["create_column"] = Field(
        "create_column", json_schema_extra={"ui:hidden": True}
    )
    listId: str = Field(
        ...,
        pattern=r"^[a-fA-F0-9]{24}$",
        description="24-character hex id of the list (from GET /business/lists).",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Column name (1-100 characters); unique per list (case-insensitive) or the call answers 409 COLUMN_NAME_TAKEN.",
    )
    type: Literal["string", "number", "date", "boolean", "url"] = Field(
        "string",
        description="Value type the column stores: string (default), number, date, boolean or url (a {label, value} link).",
    )


class FuseaiDeleteColumnConfig(_Input):
    """Delete a custom column (its values go with it)."""

    operation: Literal["delete_column"] = Field(
        "delete_column", json_schema_extra={"ui:hidden": True}
    )
    listId: str = Field(
        ...,
        pattern=r"^[a-fA-F0-9]{24}$",
        description="24-character hex id of the list (from GET /business/lists).",
    )
    columnId: str = Field(
        ...,
        pattern=r"^[a-fA-F0-9]{24}$",
        description="24-character hex id of the custom column (from GET /business/lists/{listId}/columns).",
    )


class FuseaiListCampaignsConfig(_Input):
    """List the token owner's campaigns with headline analytics."""

    operation: Literal["list_campaigns"] = Field(
        "list_campaigns", json_schema_extra={"ui:hidden": True}
    )
    limit: int = Field(25, ge=1, le=100, description="Page size, 1-100 (default 25).")
    pageNum: int = Field(1, ge=1, description="1-based page number (default 1).")
    search: Optional[str] = Field(
        None,
        min_length=1,
        max_length=200,
        description="Free text matched case-insensitively against the campaign name only (1-200 characters); any string is accepted. The value reaches the store as a regular expression rather than a literal, so metacharacters such as ( ) [ ] + * ? | are interpreted — send plain words, or escape them. A term that matches no campaign returns an empty page, not an error.",
    )
    type: Optional[Literal["ai-generated", "manual"]] = Field(
        None,
        description="Restrict to ai-generated or manual campaigns — the same values a campaign's `type` reports.",
    )
    status: Optional[
        Literal[
            "active",
            "initializing",
            "initialization_failed",
            "stopped",
            "paused_manual",
        ]
    ] = Field(
        None,
        description="Restrict to one status: initializing (draft, not yet approved), active (approved and sending), stopped (stopped via /stop or deleted), paused_manual (paused by the app), initialization_failed (AI initialization failed; see initializationError).",
    )


class FuseaiGetCampaignConfig(_Input):
    """Get a campaign's status."""

    operation: Literal["get_campaign"] = Field(
        "get_campaign", json_schema_extra={"ui:hidden": True}
    )
    campaignId: str = Field(
        ...,
        pattern=r"^[a-fA-F0-9]{24}$",
        description="The campaign's id (24-character hex ObjectId), as returned by POST /business/campaigns or as the campaignId of a GET /business/campaigns row.",
    )


class FuseaiStopCampaignConfig(_Input):
    """Stop an active campaign (approve re-activates it)."""

    operation: Literal["stop_campaign"] = Field(
        "stop_campaign", json_schema_extra={"ui:hidden": True}
    )
    campaignId: str = Field(
        ...,
        pattern=r"^[a-fA-F0-9]{24}$",
        description="The campaign's id (24-character hex ObjectId), as returned by POST /business/campaigns or as the campaignId of a GET /business/campaigns row.",
    )


class FuseaiDuplicateCampaignConfig(_Input):
    """Copy a campaign as a fresh draft."""

    operation: Literal["duplicate_campaign"] = Field(
        "duplicate_campaign", json_schema_extra={"ui:hidden": True}
    )
    campaignId: str = Field(
        ...,
        pattern=r"^[a-fA-F0-9]{24}$",
        description="The campaign's id (24-character hex ObjectId), as returned by POST /business/campaigns or as the campaignId of a GET /business/campaigns row.",
    )


class FuseaiListCampaignStepsConfig(_Input):
    """List a campaign's sequence steps."""

    operation: Literal["list_campaign_steps"] = Field(
        "list_campaign_steps", json_schema_extra={"ui:hidden": True}
    )
    campaignId: str = Field(
        ...,
        pattern=r"^[a-fA-F0-9]{24}$",
        description="The campaign's id (24-character hex ObjectId), as returned by POST /business/campaigns or as the campaignId of a GET /business/campaigns row.",
    )


class FuseaiListCampaignLeadsConfig(_Input):
    """The campaign's leads with their per-step state."""

    operation: Literal["list_campaign_leads"] = Field(
        "list_campaign_leads", json_schema_extra={"ui:hidden": True}
    )
    campaignId: str = Field(
        ...,
        pattern=r"^[a-fA-F0-9]{24}$",
        description="The campaign's id (24-character hex ObjectId), as returned by POST /business/campaigns or as the campaignId of a GET /business/campaigns row.",
    )
    limit: int = Field(25, ge=1, le=100, description="Page size, 1-100 (default 25).")
    pageNum: int = Field(1, ge=1, description="1-based page number (default 1).")
    search: Optional[str] = Field(
        None,
        min_length=1,
        max_length=200,
        description="Free text matched case-insensitively against the lead's full name or their company name (1-200 characters); any string is accepted, and regex metacharacters are escaped for you, so it behaves as a literal substring match. A term that matches no lead returns an empty page, not an error.",
    )


class FuseaiGetJobConfig(_Input):
    """Poll any async job."""

    operation: Literal["get_job"] = Field(
        "get_job", json_schema_extra={"ui:hidden": True}
    )
    jobId: str = Field(
        ...,
        pattern=r"^[a-fA-F0-9]{24}$",
        description="24-character hex id of an async job, as returned with the 202 that started it (POST /business/lists/{listId}/export).",
    )


class FuseaiFindPersonEmailConfig(_Input):
    """Find a person's email."""

    operation: Literal["find_person_email"] = Field(
        "find_person_email", json_schema_extra={"ui:hidden": True}
    )
    linkedinUrl: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        description="The person's LinkedIn profile, e.g. `https://www.linkedin.com/in/jane-doe`: the most precise way to name them.",
    )


class FuseaiVerifyEmailConfig(_Input):
    """Verify an email address."""

    operation: Literal["verify_email"] = Field(
        "verify_email", json_schema_extra={"ui:hidden": True}
    )
    email: str = Field(
        ..., max_length=320, description="The address to check, e.g. `jane@stripe.com`."
    )


class FuseaiResolveCompanyConfig(_Input):
    """Find a company's domain, LinkedIn page and logo (free)."""

    operation: Literal["resolve_company"] = Field(
        "resolve_company", json_schema_extra={"ui:hidden": True}
    )
    domain: str = Field(
        ...,
        min_length=1,
        max_length=253,
        description="The company's website domain, e.g. `stripe.com`; a full URL such as `https://www.stripe.com/about` is reduced to its domain.",
    )


FuseaiConfig = Annotated[
    Union[
        FuseaiGetAccountConfig,
        FuseaiGetCreditsConfig,
        FuseaiListListsConfig,
        FuseaiCreateListConfig,
        FuseaiGetListConfig,
        FuseaiRenameListConfig,
        FuseaiDeleteListConfig,
        FuseaiListRowsConfig,
        FuseaiAddMembersConfig,
        FuseaiRemoveMembersConfig,
        FuseaiListColumnsConfig,
        FuseaiCreateColumnConfig,
        FuseaiDeleteColumnConfig,
        FuseaiListCampaignsConfig,
        FuseaiGetCampaignConfig,
        FuseaiStopCampaignConfig,
        FuseaiDuplicateCampaignConfig,
        FuseaiListCampaignStepsConfig,
        FuseaiListCampaignLeadsConfig,
        FuseaiGetJobConfig,
        FuseaiFindPersonEmailConfig,
        FuseaiVerifyEmailConfig,
        FuseaiResolveCompanyConfig,
    ],
    Field(discriminator="operation"),
]


class FuseaiFullConfig(NodeConfig[FuseaiConfig, FuseaiAPITokenCredential]):
    pass


# method, path, path fields, query fields, JSON fields, success status, response keys
OPERATIONS = {
    "get_account": ("GET", "/business/me", (), (), (), 200, ("user",)),
    "get_credits": ("GET", "/business/credits", (), (), (), 200, ("balance",)),
    "list_lists": (
        "GET",
        "/business/lists",
        (),
        ("limit", "pageNum", "entityType", "search"),
        (),
        200,
        ("data", "pagination"),
    ),
    "create_list": (
        "POST",
        "/business/lists",
        (),
        (),
        ("name", "entityType"),
        201,
        ("list",),
    ),
    "get_list": (
        "GET",
        "/business/lists/{listId}",
        ("listId",),
        ("include",),
        (),
        200,
        ("list",),
    ),
    "rename_list": (
        "PATCH",
        "/business/lists/{listId}",
        ("listId",),
        (),
        ("name",),
        200,
        ("list",),
    ),
    "delete_list": ("DELETE", "/business/lists/{listId}", ("listId",), (), (), 204, ()),
    "list_rows": (
        "GET",
        "/business/lists/{listId}/rows",
        ("listId",),
        ("limit", "pageNum"),
        (),
        200,
        ("entityType", "data", "pagination"),
    ),
    "add_members": (
        "POST",
        "/business/lists/{listId}/members",
        ("listId",),
        (),
        ("contactIds",),
        200,
        ("submittedCount", "addedCount"),
    ),
    "remove_members": (
        "DELETE",
        "/business/lists/{listId}/members",
        ("listId",),
        (),
        ("contactIds",),
        200,
        ("submittedCount",),
    ),
    "list_columns": (
        "GET",
        "/business/lists/{listId}/columns",
        ("listId",),
        (),
        (),
        200,
        ("columns",),
    ),
    "create_column": (
        "POST",
        "/business/lists/{listId}/columns",
        ("listId",),
        (),
        ("name", "type"),
        201,
        ("column",),
    ),
    "delete_column": (
        "DELETE",
        "/business/lists/{listId}/columns/{columnId}",
        ("listId", "columnId"),
        (),
        (),
        204,
        (),
    ),
    "list_campaigns": (
        "GET",
        "/business/campaigns",
        (),
        ("limit", "pageNum", "search", "type", "status"),
        (),
        200,
        ("campaigns", "pagination"),
    ),
    "get_campaign": (
        "GET",
        "/business/campaigns/{campaignId}",
        ("campaignId",),
        (),
        (),
        200,
        ("campaign",),
    ),
    "stop_campaign": (
        "POST",
        "/business/campaigns/{campaignId}/stop",
        ("campaignId",),
        (),
        (),
        200,
        ("campaign",),
    ),
    "duplicate_campaign": (
        "POST",
        "/business/campaigns/{campaignId}/duplicate",
        ("campaignId",),
        (),
        (),
        201,
        ("campaign",),
    ),
    "list_campaign_steps": (
        "GET",
        "/business/campaigns/{campaignId}/steps",
        ("campaignId",),
        (),
        (),
        200,
        ("steps",),
    ),
    "list_campaign_leads": (
        "GET",
        "/business/campaigns/{campaignId}/leads",
        ("campaignId",),
        ("limit", "pageNum", "search"),
        (),
        200,
        ("leads", "pagination"),
    ),
    "get_job": ("GET", "/business/jobs/{jobId}", ("jobId",), (), (), 200, ("job",)),
    "find_person_email": (
        "POST",
        "/business/data/people/email",
        (),
        (),
        ("linkedinUrl",),
        200,
        ("status", "email", "linkedinUrl", "creditsCharged"),
    ),
    "verify_email": (
        "POST",
        "/business/data/emails/verify",
        (),
        (),
        ("email",),
        200,
        ("email", "status", "creditsCharged"),
    ),
    "resolve_company": (
        "POST",
        "/business/data/companies/resolve",
        (),
        (),
        ("domain",),
        200,
        ("status", "company", "creditsCharged"),
    ),
}


def _redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[redacted]")
    if isinstance(value, list):
        return [_redact(item, token) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, token) for key, item in value.items()}
    return value


class FuseaiNode(WorkflowNode):
    integration_type = "automation-fuseai"
    connection_evidence = ConnectionEvidence(
        noun="Fuseai account", identity_operation="get_account"
    )

    @classmethod
    def get_config_model(cls):
        return FuseaiFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Fuseai API token")
        config = self.config.config
        token = self.config.credentials.api_token
        (
            method,
            path,
            path_fields,
            query_fields,
            body_fields,
            expected_status,
            response_keys,
        ) = OPERATIONS[config.operation]
        values = config.model_dump(exclude_none=True)
        path = path.format(**{key: values[key] for key in path_fields})
        params = {key: values[key] for key in query_fields if key in values}
        body = {key: values[key] for key in body_fields if key in values}
        async with guarded_async_client(
            timeout=30.0, follow_redirects=False, trust_env=False
        ) as client:
            response = await client.request(
                method,
                BASE_URL + path,
                params=params,
                json=body if body_fields else None,
                auth=httpx.BasicAuth(token, ""),
                headers={"Accept": "application/json"},
            )
        if response.status_code != expected_status:
            # Error bodies can contain provider diagnostics. Preserve those words,
            # redact the token, and never report a failed write as successful.
            message = "Fuseai did not confirm the operation"
            try:
                error = response.json()
                if isinstance(error, dict):
                    detail = error.get("error") or error.get("message")
                    if isinstance(detail, dict):
                        detail = detail.get("message")
                    if isinstance(detail, str):
                        message = detail[:1000]
            except ValueError:
                pass
            return {
                "status": "error",
                "http_status": response.status_code,
                "error": _redact(message, token),
            }
        if expected_status == 204:
            return {"status": "success", "http_status": 204, "acknowledged": True}
        data = response.json()
        if (
            not isinstance(data, dict)
            or any(key not in data for key in response_keys)
            or "error" in data
        ):
            raise ValueError("Fuseai returned an unexpected response envelope")
        if config.operation == "get_account":
            user = data.get("user")
            if (
                not isinstance(user, dict)
                or not isinstance(user.get("id"), str)
                or not user["id"]
            ):
                raise ValueError("Fuseai returned no account identity")
        return {
            "status": "success",
            "http_status": response.status_code,
            "data": _redact(data, token),
        }
