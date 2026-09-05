"""
Typed response models for socket.io events.
These models provide type-safe responses that correspond to specific request types,
enabling full type checking from backend to frontend.
"""
from typing import List, Dict, Any, Optional, ClassVar
from pydantic import BaseModel, Field
from datetime import datetime


# Debug Operation Responses








# Workflow Operation Responses
class WorkflowInfo(BaseModel):
    """Workflow information structure"""
    id: str = Field(..., description="Workflow UUID")
    name: str = Field(..., description="Human-readable name for the workflow")
    description: str = Field("", description="Workflow description")
    workflow_data: Optional[Dict[str, Any]] = Field(None, description="Workflow configuration including nodes and edges. None when not included in response (e.g., metadata-only updates).")
    permissions: Dict[str, Any] = Field(
        {"public": [], "shared_with": {}},
        description="Access permissions for sharing"
    )
    created_at: str = Field(..., description="Creation timestamp in ISO format")
    updated_at: str = Field(..., description="Last update timestamp in ISO format")
    display_metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="UI display state: viewport (x,y,zoom), selectedNodeId, flowHelperView state"
    )
    folder_id: Optional[str] = Field(
        None,
        description="Folder UUID this workflow belongs to, or None for root-level workflows"
    )
    user_permission: Optional[str] = Field(
        None,
        description="Current user's permission level: 'owner', 'edit', 'view', or None if not set"
    )
    is_owner: Optional[bool] = Field(
        None,
        description="Whether the current user is the owner of this workflow"
    )
    owner_name: Optional[str] = Field(
        None,
        description="Display name of the workflow owner (only set for shared workflows, i.e. is_owner=False)"
    )
    settings: Optional[Dict[str, Any]] = Field(
        None,
        description="Workflow-level settings (e.g. min_required_balance)"
    )
    graph_version: Optional[int] = Field(
        None,
        description="Optimistic-concurrency version of the workflow blob. Bumped by a DB trigger on every blob change; clients echo it as expected_graph_version on workflow:update so stale snapshots lose cleanly instead of clobbering."
    )


class WorkflowListResponse(BaseModel):
    """Response for workflow:list request"""
    workflows: List[WorkflowInfo] = Field(..., description="List of user's workflows")
    hidden_shared_count: int = Field(0, description="Number of shared workflows hidden due to plan limit")
    subscription_tier: str = Field('free', description="Current context subscription tier (for limit messaging)")


class WorkflowGetResponse(BaseModel):
    """Response for workflow:get request"""
    workflow: WorkflowInfo = Field(..., description="Workflow details")
    # Per-node last-run status {node_id: {status, finishedAt (epoch ms), error}},
    # read from the CAS (cas_manifests, via node_outputs.latest_statuses). Returned
    # alongside the graph so the status chips render in the same paint instead of
    # popping in via a second round-trip.
    node_statuses: Dict[str, Any] = Field(default_factory=dict, description="Per-node last-run status keyed by node_id")


class WorkflowCreateResponse(BaseModel):
    """Response for workflow:create request"""
    success: bool = Field(..., description="Whether creation was successful")
    workflow: Optional[WorkflowInfo] = Field(None, description="Created workflow info")
    message: Optional[str] = Field(None, description="Success or error message")


class WorkflowUpdateResponse(BaseModel):
    """Response for workflow:update request"""
    success: bool = Field(..., description="Whether update was successful")
    workflow: Optional[WorkflowInfo] = Field(None, description="Updated workflow info")
    message: Optional[str] = Field(None, description="Success or error message")


class WorkflowDeleteResponse(BaseModel):
    """Response for workflow:delete request"""
    success: bool = Field(..., description="Whether deletion was successful")
    message: str = Field(..., description="Success or error message")
    workflow_id: Optional[str] = Field(None, description="UUID of the deleted workflow")


class WorkflowRestoreResponse(BaseModel):
    """Response for workflow:restore request"""
    success: bool = Field(..., description="Whether restore was successful")
    message: str = Field(..., description="Success or error message")
    workflow_id: Optional[str] = Field(None, description="UUID of the restored workflow")


class WorkflowTrashInfo(BaseModel):
    """Trashed workflow information for the trash view"""
    id: str = Field(..., description="Workflow UUID")
    name: str = Field(..., description="Workflow name")
    description: str = Field("", description="Workflow description")
    deleted_at: str = Field(..., description="Deletion timestamp in ISO format")
    days_remaining: int = Field(..., description="Days remaining before permanent deletion")


class WorkflowListTrashResponse(BaseModel):
    """Response for workflow:list_trash request"""
    workflows: List[WorkflowTrashInfo] = Field(..., description="List of trashed workflows")


class WorkflowPermanentDeleteResponse(BaseModel):
    """Response for workflow:permanent_delete request"""
    success: bool = Field(..., description="Whether permanent deletion was successful")
    message: str = Field(..., description="Success or error message")


# Workflow Execution Logging
class WorkflowExecutionInfo(BaseModel):
    """Workflow execution log information"""
    id: str = Field(..., description="Execution UUID")
    workflow_id: str = Field(..., description="Workflow UUID")
    user_id: str = Field(..., description="User UUID who triggered the execution")
    status: str = Field(..., description="Execution status: running, completed, error")
    started_at: str = Field(..., description="Execution start timestamp in ISO format")
    finished_at: Optional[str] = Field(None, description="Execution finish timestamp in ISO format")
    nodes_executed: int = Field(0, description="Number of nodes executed")
    error: Optional[str] = Field(None, description="Error message if execution failed")
    trigger_source: Optional[str] = Field(None, description="How the run was triggered: manual/webhook/cron/mcp/api")
    has_graph: bool = Field(False, description="Whether a graph snapshot exists for this run (replayable)")


class WorkflowExecutionListResponse(BaseModel):
    """Response for workflow:list_executions request"""
    executions: List[WorkflowExecutionInfo] = Field(..., description="List of workflow execution logs")
    next_cursor_started_at: Optional[str] = Field(
        None,
        description="started_at of the last row in this page. Pass back as "
                    "`cursor_started_at` to fetch the next page. Null when there "
                    "are no more rows beyond this page."
    )
    next_cursor_id: Optional[str] = Field(
        None,
        description="id of the last row in this page; pair with next_cursor_started_at."
    )


class WorkflowExecutionCountsResponse(BaseModel):
    """Response for workflow:get_execution_counts.

    Raw DB status counts (frontend maps to UI labels — e.g. 'completed' →
    'success', 'awaiting_*' → 'waiting'). Trigger counts use the raw
    trigger_source values defined by the table's CHECK constraint
    (manual/webhook/cron/mcp/api)."""
    total: int = Field(..., description="Total executions for this workflow.")
    by_status: Dict[str, int] = Field(..., description="DB-status → count for non-zero statuses.")
    by_trigger: Dict[str, int] = Field(..., description="trigger_source → count for non-zero triggers.")


class WorkflowNodeConfigSchemaResponse(BaseModel):
    """Response for workflow:node:get_config_schema request"""
    node_type: str = Field(..., description="Type of the node")
    config_schema: Dict[str, Any] = Field(..., description="Configuration schema for the node")


class WorkflowNodeValidateConfigResponse(BaseModel):
    """Response for workflow:node:validate_config request"""
    valid: bool = Field(..., description="Whether the config is valid")
    errors: List[str] = Field(default_factory=list, description="List of validation errors")
    satisfied_set: Optional[str] = Field(None, description="Name of the parameter set that was satisfied")


class FieldOption(BaseModel):
    """A single option for a dynamic dropdown field"""
    value: str = Field(..., description="The value to store when selected")
    label: str = Field(..., description="Display label for the option")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata about the option")


class WorkflowNodeLoadOptionsResponse(BaseModel):
    """Response for workflow:node:load_options request"""
    success: bool = Field(..., description="Whether options were loaded successfully")
    options: List[FieldOption] = Field(default_factory=list, description="List of options for the field")
    message: Optional[str] = Field(None, description="Error message if loading failed")
    next_page_token: Optional[str] = Field(None, description="Token for loading the next page (null if no more pages)")


class EvidenceSampleModel(BaseModel):
    """One recognisable item from the user's own account."""
    label: str = Field(..., description="What the user sees, in their own vocabulary (e.g. '#sales')")
    value: Optional[str] = Field(None, description="Settable into `answers_field`; null when the sample cannot answer a config field")


class CredentialTestConnectionResponse(BaseModel):
    """Response for credential:test_connection."""
    # Tri-state on purpose: null is "cannot judge" and must render as unverified,
    # never as broken. A timeout or an unexpected shape is not grounds for telling
    # someone their working credential is dead.
    reachable: Optional[bool] = Field(None, description="true = provider answered, false = provider rejected the credential, null = cannot judge")
    samples: List[EvidenceSampleModel] = Field(default_factory=list, description="Recognisable items from the account")
    noun: str = Field("items", description="The user's word for those items ('channels', 'repositories')")
    total: Optional[int] = Field(None, description="How many were found, when more than shown")
    account_label: Optional[str] = Field(None, description="The account itself, shown when there is nothing to list")
    answers_field: Optional[str] = Field(None, description="Config field these samples can fill; null when they answer nothing")
    proves: str = Field("account", description="'account' = data unique to this account; 'reachability' = only proves the key is accepted")
    error: Optional[str] = Field(None, description="The provider's verbatim refusal when reachable is false")


class RehearsalRunResponse(BaseModel):
    """Response for rehearsal:run."""
    success: bool = Field(..., description="Whether the rehearsal completed")
    conversation_id: Optional[str] = Field(None, description="Conversation the staged run used; the trace streams under it")
    execution_id: Optional[str] = Field(None, description="Execution the rehearsal ran as")
    message: Optional[str] = Field(None, description="Why it could not run, when it could not")


class RehearsalLeadModel(BaseModel):
    """The staged message as the Test screen renders it. Display-only, and it
    must agree with the scenario's injected payload — showing one email while
    injecting another would make the screen a lie."""
    title: str = Field(..., description="Subject / channel / contact")
    meta: str = Field(..., description="One-line sender summary for terse surfaces")
    body: str = Field(..., description="The message text")
    author: Optional[str] = Field(None, description="Sender display name")
    handle: Optional[str] = Field(None, description="Sender address — email or phone")
    time: Optional[str] = Field(None, description="Staged arrival time, display only")


class RehearsalSituationModel(BaseModel):
    key: str = Field(..., description="Scenario slug to pass to rehearsal:run")
    name: str = Field(..., description="The situation's name ('Qualified lead')")
    lead: RehearsalLeadModel = Field(..., description="The staged message, for display")


class RehearsalTriggerModel(BaseModel):
    node_type: str = Field(..., description="Trigger node type the situations arrive through (e.g. 'automation-gmail')")
    operation: Optional[str] = Field(None, description="The node's selected trigger operation — the FE frames respond to it (a PR trigger renders a PR card)")
    situations: List[RehearsalSituationModel] = Field(default_factory=list)


class RehearsalScenariosResponse(BaseModel):
    """Response for rehearsal:scenarios."""
    success: bool = Field(...)
    triggers: List[RehearsalTriggerModel] = Field(default_factory=list, description="Rehearsable triggers present in this workflow's graph")
    message: Optional[str] = Field(None, description="Why listing failed, when it did")


class WorkflowNodeLoadValueResponse(BaseModel):
    """Response for workflow:node:load_value request - returns computed values for readonly fields"""
    success: bool = Field(..., description="Whether the value was loaded successfully")
    value: Optional[Any] = Field(None, description="The computed/generated value for the field")
    values: Optional[Dict[str, Any]] = Field(None, description="Multiple computed values (for fields that generate multiple related values)")
    message: Optional[str] = Field(None, description="Error message if loading failed")


class WorkflowCollabTokenResponse(BaseModel):
    """Response for workflow:collab_token request - JWT for workflow relay authentication"""
    success: bool = Field(..., description="Whether token generation was successful")
    token: Optional[str] = Field(None, description="JWT token for workflow relay authentication")
    expires_at: Optional[int] = Field(None, description="Token expiration timestamp (Unix epoch seconds)")
    message: Optional[str] = Field(None, description="Error message if generation failed")


# Workflow Folder Operation Responses
class FolderInfo(BaseModel):
    """Workflow folder information structure"""
    id: str = Field(..., description="Folder UUID")
    name: str = Field(..., description="Folder name")
    description: str = Field("", description="Folder description")
    parent_folder_id: Optional[str] = Field(None, description="Parent folder UUID (null for root)")
    path: str = Field(..., description="Materialized path (e.g., /uuid1/uuid2/)")
    depth: int = Field(..., description="Nesting depth (0 = root, max 10)")
    created_at: str = Field(..., description="Creation timestamp in ISO format")
    updated_at: str = Field(..., description="Update timestamp in ISO format")
    is_owner: bool = Field(..., description="Whether the current user owns this folder")
    owner_name: Optional[str] = Field(
        None,
        description="Display name of the folder owner (only set for shared folders, i.e. is_owner=False)"
    )
    workflow_count: int = Field(0, description="Number of workflows in this folder")
    children: List['FolderInfo'] = Field(default_factory=list, description="Child folders (for tree view)")


# Enable forward references for FolderInfo.children
FolderInfo.model_rebuild()


class FolderListResponse(BaseModel):
    """Response for workflow_folder:list request"""
    folders: List[FolderInfo] = Field(..., description="List of folders")


class FolderGetResponse(BaseModel):
    """Response for workflow_folder:get request"""
    folder: FolderInfo = Field(..., description="Folder details")


class FolderCreateResponse(BaseModel):
    """Response for workflow_folder:create request"""
    success: bool = Field(..., description="Whether creation was successful")
    folder: Optional[FolderInfo] = Field(None, description="Created folder info")
    message: Optional[str] = Field(None, description="Success or error message")


class FolderUpdateResponse(BaseModel):
    """Response for workflow_folder:update request"""
    success: bool = Field(..., description="Whether update was successful")
    folder: Optional[FolderInfo] = Field(None, description="Updated folder info")
    message: Optional[str] = Field(None, description="Success or error message")


class FolderDeleteResponse(BaseModel):
    """Response for workflow_folder:delete request"""
    success: bool = Field(..., description="Whether deletion was successful")
    message: str = Field(..., description="Success or error message")


class WorkflowMoveToFolderResponse(BaseModel):
    """Response for workflow_folder:move_workflow request."""
    success: bool
    workflow_id: str
    folder_id: Optional[str] = None
    message: Optional[str] = None


class FolderTreeResponse(BaseModel):
    """Response for workflow_folder:get_tree request"""
    folders: List[FolderInfo] = Field(..., description="Root-level folders with nested children")


class FolderPathResponse(BaseModel):
    """Response for workflow_folder:get_path request"""
    path: List[Dict[str, Any]] = Field(..., description="Breadcrumb path from root to target folder")


# Generic typed response wrapper
class TypedResponseEvent(BaseModel):
    """
    Generic typed response event that preserves type information.
    This is used internally to wrap typed responses before sending.
    """
    request_id: str = Field(..., description="Correlation ID from request")
    data: BaseModel = Field(..., description="Typed response data")
    error: Optional[str] = Field(None, description="Error message if failed")
    
    def to_response_event(self):
        """Convert to generic ResponseEvent for sending"""
        from .events import ResponseEvent
        return ResponseEvent(
            request_id=self.request_id,
            data=self.data.model_dump() if self.data else None,
            error=self.error
        )


# Credential Operation Responses
class CredentialInfo(BaseModel):
    """Credential information structure (without decrypted data)"""
    id: str = Field(..., description="Credential UUID")
    name: str = Field(..., description="Human-readable credential name")
    credential_type: str = Field(..., description="Type: 'oauth', 'api_key', 'database', 'third_party'")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Credential metadata")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")
    access_type: str = Field("owner", description="How the user accesses this credential: 'owner', 'shared', or 'shared_org'")
    organization_id: Optional[str] = Field(None, description="Organization this credential belongs to (null if personal)")
    shared_with_org: bool = Field(False, description="Whether this credential is shared with the current organization")
    over_cap: bool = Field(False, description="Whether this credential exceeds the plan's per-type cap")
    shared_by_email: Optional[str] = Field(None, description="Email of user who shared this credential (only for shared credentials)")
    shared_by_name: Optional[str] = Field(None, description="Display name of user who shared (only for shared credentials)")
    share_id: Optional[str] = Field(None, description="The resource_shares row ID linking this credential to the current user (only for shared credentials)")
    revoked_at: Optional[str] = Field(None, description="When this credential was revoked/disconnected (null = live). Revoked credentials cannot be loaded at run time — the UI must surface them as dead, not selectable-as-healthy")
    revoked_reason: Optional[str] = Field(None, description="Why the credential was revoked (e.g. user_revoked, provider_4xx auto-revoke)")
    connection_status: Optional[str] = Field(None, description="Provider-native session state for connection-backed credentials, in the provider's own words (WhatsApp: 'connected'/'scan_qr'/'failed'/'missing'; Discord: 'installed'/'removed'). Display only — judge connection_healthy, never this string. None = not applicable or state unknown")
    connection_healthy: Optional[bool] = Field(None, description="The verdict on connection_status: False = the provider session is dead and the credential cannot work as attached; True = live; None = not applicable or state unknown (never treated as dead)")
    connection_hint: Optional[str] = Field(None, description="How to repair a dead connection (present whenever connection_healthy is False), phrased for the owner: re-scan this same WhatsApp credential, reinstall the Discord bot, …")


class CredentialListResponse(BaseModel):
    """Response for credential:list request"""
    credentials: List[CredentialInfo] = Field(default_factory=list, description="List of credentials (without decrypted data)")
    hidden_shared_count: int = Field(0, description="Number of shared credentials hidden due to plan limit")
    subscription_tier: str = Field('free', description="Current context subscription tier (for limit messaging)")


class CredentialGetResponse(BaseModel):
    """Response for credential:get request (includes decrypted data)"""
    credential_id: str = Field(..., description="Credential UUID")
    name: str = Field(..., description="Human-readable credential name")
    credential_type: str = Field(..., description="Type: 'oauth', 'api_key', 'database', 'third_party'")
    credential_data: Dict[str, Any] = Field(..., description="Decrypted credential data")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Credential metadata")


class CredentialCreateResponse(BaseModel):
    """Response for credential:create request"""
    success: bool = Field(..., description="Whether creation was successful")
    credential: Optional[CredentialInfo] = Field(None, description="Created credential info")
    message: Optional[str] = Field(None, description="Success or error message")


class CredentialUpdateResponse(BaseModel):
    """Response for credential:update request"""
    success: bool = Field(..., description="Whether update was successful")
    credential: Optional[CredentialInfo] = Field(None, description="Updated credential info")
    message: Optional[str] = Field(None, description="Success or error message")


class CredentialAffectedWorkflow(BaseModel):
    """A workflow whose nodes reference a credential pending deletion."""
    workflow_id: str = Field(..., description="Workflow UUID")
    workflow_name: str = Field(..., description="Workflow display name")


class CredentialDeleteResponse(BaseModel):
    """Response for credential:delete request"""
    success: bool = Field(..., description="Whether deletion was successful")
    message: str = Field(..., description="Success or error message")
    credential_id: Optional[str] = Field(None, description="UUID of the deleted credential")
    deleted: bool = Field(True, description="False on a dry run — nothing was deleted")
    affected_workflows: List[CredentialAffectedWorkflow] = Field(
        default_factory=list,
        description="Workflows referencing this credential (populated on dry runs)",
    )


# Credential Request Responses (request credentials from external users)
class CredentialRequestInfo(BaseModel):
    """Credential request information"""
    id: str = Field(..., description="Request UUID")
    target_email: str = Field(..., description="Email the request was sent to")
    credential_type: str = Field(..., description="Credential type requested")
    message: Optional[str] = Field(None, description="Optional message from requester")
    status: str = Field(..., description="pending, fulfilled, expired, or cancelled")
    credential_id: Optional[str] = Field(None, description="Credential UUID if fulfilled")
    expires_at: Optional[str] = Field(None, description="Expiration timestamp")
    created_at: str = Field(..., description="Creation timestamp")
    fulfilled_at: Optional[str] = Field(None, description="Fulfillment timestamp")


class CredentialRequestCreateResponse(BaseModel):
    """Response for credential:request:create"""
    success: bool
    request: Optional[CredentialRequestInfo] = None
    provide_url: Optional[str] = Field(None, description="Shareable link the recipient uses to provide the credential")
    message: Optional[str] = None


class CredentialRequestListResponse(BaseModel):
    """Response for credential:request:list"""
    requests: List[CredentialRequestInfo] = Field(default_factory=list)


class CredentialRequestCancelResponse(BaseModel):
    """Response for credential:request:cancel"""
    success: bool
    message: str


# Google OAuth Operation Responses
class GoogleOAuthExchangeResponse(BaseModel):
    """Response for google:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    credential_type: Optional[str] = Field(None, description="Credential type of the created Google credential")
    email: Optional[str] = Field(None, description="Google account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class GoogleOAuthRefreshResponse(BaseModel):
    """Response for google:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class GoogleOAuthValidateResponse(BaseModel):
    """Response for google:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    email: Optional[str] = Field(None, description="Google account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Airtable OAuth Operation Responses
class AirtableOAuthExchangeResponse(BaseModel):
    """Response for airtable:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    email: Optional[str] = Field(None, description="Airtable account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class AirtableOAuthRefreshResponse(BaseModel):
    """Response for airtable:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class AirtableOAuthValidateResponse(BaseModel):
    """Response for airtable:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    email: Optional[str] = Field(None, description="Airtable account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Stripe OAuth Operation Responses
class StripeOAuthExchangeResponse(BaseModel):
    """Response for stripe:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    email: Optional[str] = Field(None, description="Stripe account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class StripeOAuthRefreshResponse(BaseModel):
    """Response for stripe:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class StripeOAuthValidateResponse(BaseModel):
    """Response for stripe:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    email: Optional[str] = Field(None, description="Stripe account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# GitHub OAuth Operation Responses
class GithubOAuthExchangeResponse(BaseModel):
    """Response for github:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    login: Optional[str] = Field(None, description="GitHub username for display")
    email: Optional[str] = Field(None, description="GitHub account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class GithubOAuthRefreshResponse(BaseModel):
    """Response for github:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class GithubOAuthValidateResponse(BaseModel):
    """Response for github:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    login: Optional[str] = Field(None, description="GitHub username")
    email: Optional[str] = Field(None, description="GitHub account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Atlassian OAuth Operation Responses (for Jira)
class AtlassianOAuthExchangeResponse(BaseModel):
    """Response for atlassian:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    cloud_id: Optional[str] = Field(None, description="Atlassian Cloud ID")
    site_name: Optional[str] = Field(None, description="Jira site name for display")
    site_url: Optional[str] = Field(None, description="Jira site URL")
    available_sites: Optional[list[dict[str, str]]] = Field(None, description="Jira sites available to the Atlassian account when the requested site is inaccessible")
    message: Optional[str] = Field(None, description="Success or error message")


class AtlassianOAuthRefreshResponse(BaseModel):
    """Response for atlassian:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class AtlassianOAuthValidateResponse(BaseModel):
    """Response for atlassian:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    cloud_id: Optional[str] = Field(None, description="Atlassian Cloud ID")
    site_name: Optional[str] = Field(None, description="Jira site name")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Canva OAuth Operation Responses
class CanvaOAuthExchangeResponse(BaseModel):
    """Response for canva:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    display_name: Optional[str] = Field(None, description="Canva account display name")
    message: Optional[str] = Field(None, description="Success or error message")


class CanvaOAuthRefreshResponse(BaseModel):
    """Response for canva:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class CanvaOAuthValidateResponse(BaseModel):
    """Response for canva:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    display_name: Optional[str] = Field(None, description="Canva account display name")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Discord OAuth Operation Responses
class DiscordOAuthExchangeResponse(BaseModel):
    """Response for discord:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    username: Optional[str] = Field(None, description="Discord username for display")
    email: Optional[str] = Field(None, description="Discord account email for display")
    guild_id: Optional[str] = Field(None, description="Guild ID when bot was installed (bot install flow)")
    guild_name: Optional[str] = Field(None, description="Guild name when bot was installed (bot install flow)")
    message: Optional[str] = Field(None, description="Success or error message")


class DiscordOAuthRefreshResponse(BaseModel):
    """Response for discord:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class DiscordOAuthValidateResponse(BaseModel):
    """Response for discord:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    username: Optional[str] = Field(None, description="Discord username")
    email: Optional[str] = Field(None, description="Discord account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Dropbox OAuth Operation Responses
class DropboxOAuthExchangeResponse(BaseModel):
    """Response for dropbox:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    username: Optional[str] = Field(None, description="Dropbox username for display")
    email: Optional[str] = Field(None, description="Dropbox account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class DropboxOAuthRefreshResponse(BaseModel):
    """Response for dropbox:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class DropboxOAuthValidateResponse(BaseModel):
    """Response for dropbox:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    username: Optional[str] = Field(None, description="Dropbox username")
    email: Optional[str] = Field(None, description="Dropbox account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Facebook OAuth Operation Responses (for Instagram)
class FacebookOAuthExchangeResponse(BaseModel):
    """Response for facebook:oauth:exchange request (Instagram integration)"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    instagram_username: Optional[str] = Field(None, description="Instagram username for display")
    email: Optional[str] = Field(None, description="Facebook account email for display")
    message: Optional[str] = Field(None, description="Success or error message")
    needs_selection: bool = Field(False, description="True when multiple Instagram accounts found and user must select one")
    accounts: Optional[list] = Field(None, description="List of account dicts when needs_selection is True")
    pending_selection_key: Optional[str] = Field(None, description="Opaque key to pass back when completing account selection")


class FacebookOAuthRefreshResponse(BaseModel):
    """Response for facebook:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class FacebookOAuthValidateResponse(BaseModel):
    """Response for facebook:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 7 days")
    instagram_username: Optional[str] = Field(None, description="Instagram username")
    email: Optional[str] = Field(None, description="Facebook account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# PagerDuty OAuth Operation Responses
class PagerDutyOAuthExchangeResponse(BaseModel):
    """Response for pagerduty:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="PagerDuty user name for display")
    email: Optional[str] = Field(None, description="PagerDuty account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class PagerDutyOAuthRefreshResponse(BaseModel):
    """Response for pagerduty:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class PagerDutyOAuthValidateResponse(BaseModel):
    """Response for pagerduty:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    name: Optional[str] = Field(None, description="PagerDuty user name")
    email: Optional[str] = Field(None, description="PagerDuty account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Linear OAuth Operation Responses
class LinearOAuthExchangeResponse(BaseModel):
    """Response for linear:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="Linear user name for display")
    email: Optional[str] = Field(None, description="Linear account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class LinearOAuthRefreshResponse(BaseModel):
    """Response for linear:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class LinearOAuthValidateResponse(BaseModel):
    """Response for linear:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    name: Optional[str] = Field(None, description="Linear user name")
    email: Optional[str] = Field(None, description="Linear account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Threads OAuth Operation Responses
class ThreadsOAuthExchangeResponse(BaseModel):
    """Response for threads:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="Threads username for display")
    message: Optional[str] = Field(None, description="Success or error message")


class ThreadsOAuthRefreshResponse(BaseModel):
    """Response for threads:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class ThreadsOAuthValidateResponse(BaseModel):
    """Response for threads:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires soon")
    name: Optional[str] = Field(None, description="Threads username")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Instagram Login OAuth Operation Responses
class InstagramLoginOAuthExchangeResponse(BaseModel):
    """Response for instagram_login:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="Instagram username for display")
    message: Optional[str] = Field(None, description="Success or error message")


class InstagramLoginOAuthRefreshResponse(BaseModel):
    """Response for instagram_login:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class InstagramLoginOAuthValidateResponse(BaseModel):
    """Response for instagram_login:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires soon")
    name: Optional[str] = Field(None, description="Instagram username")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Facebook Pages OAuth Operation Responses
class FacebookPagesOAuthExchangeResponse(BaseModel):
    """Response for facebook_pages:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="Facebook user name for display")
    email: Optional[str] = Field(None, description="Facebook account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class FacebookPagesOAuthRefreshResponse(BaseModel):
    """Response for facebook_pages:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class FacebookPagesOAuthValidateResponse(BaseModel):
    """Response for facebook_pages:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if the token expires soon")
    name: Optional[str] = Field(None, description="Facebook user name")
    email: Optional[str] = Field(None, description="Facebook account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Meta OAuth Operation Responses
class MetaOAuthExchangeResponse(BaseModel):
    """Response for meta:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="Meta account name for display")
    email: Optional[str] = Field(None, description="Meta account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class MetaOAuthRefreshResponse(BaseModel):
    """Response for meta:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class MetaOAuthValidateResponse(BaseModel):
    """Response for meta:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires soon")
    name: Optional[str] = Field(None, description="Meta account name")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Attio OAuth Operation Responses
class AttioOAuthExchangeResponse(BaseModel):
    """Response for attio:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="Attio workspace name for display")
    message: Optional[str] = Field(None, description="Success or error message")


class AttioOAuthRefreshResponse(BaseModel):
    """Response for attio:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class AttioOAuthValidateResponse(BaseModel):
    """Response for attio:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    name: Optional[str] = Field(None, description="Attio workspace name")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Cal.com OAuth Operation Responses
class CalComOAuthExchangeResponse(BaseModel):
    """Response for calcom:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="Cal.com user name for display")
    email: Optional[str] = Field(None, description="Cal.com account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class CalComOAuthRefreshResponse(BaseModel):
    """Response for calcom:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class CalComOAuthValidateResponse(BaseModel):
    """Response for calcom:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    name: Optional[str] = Field(None, description="Cal.com user name")
    email: Optional[str] = Field(None, description="Cal.com account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Box OAuth Operation Responses
class BoxOAuthExchangeResponse(BaseModel):
    """Response for box:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="Box user name for display")
    email: Optional[str] = Field(None, description="Box account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class BoxOAuthRefreshResponse(BaseModel):
    """Response for box:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class BoxOAuthValidateResponse(BaseModel):
    """Response for box:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    name: Optional[str] = Field(None, description="Box user name")
    email: Optional[str] = Field(None, description="Box account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Asana OAuth Operation Responses
class AsanaOAuthExchangeResponse(BaseModel):
    """Response for asana:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="Asana user name for display")
    email: Optional[str] = Field(None, description="Asana account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class AsanaOAuthRefreshResponse(BaseModel):
    """Response for asana:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class AsanaOAuthValidateResponse(BaseModel):
    """Response for asana:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    name: Optional[str] = Field(None, description="Asana user name")
    email: Optional[str] = Field(None, description="Asana account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# ClickUp OAuth Operation Responses
class ClickUpOAuthExchangeResponse(BaseModel):
    """Response for clickup:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="ClickUp user name for display")
    email: Optional[str] = Field(None, description="ClickUp account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class ClickUpOAuthRefreshResponse(BaseModel):
    """Response for clickup:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class ClickUpOAuthValidateResponse(BaseModel):
    """Response for clickup:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    name: Optional[str] = Field(None, description="ClickUp user name")
    email: Optional[str] = Field(None, description="ClickUp account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# GitLab OAuth Operation Responses
class GitLabOAuthExchangeResponse(BaseModel):
    """Response for gitlab:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="GitLab user name for display")
    email: Optional[str] = Field(None, description="GitLab account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class GitLabOAuthRefreshResponse(BaseModel):
    """Response for gitlab:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class GitLabOAuthValidateResponse(BaseModel):
    """Response for gitlab:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    name: Optional[str] = Field(None, description="GitLab user name")
    email: Optional[str] = Field(None, description="GitLab account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Monday OAuth Operation Responses
class MondayOAuthExchangeResponse(BaseModel):
    """Response for monday:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="monday user name for display")
    email: Optional[str] = Field(None, description="monday account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class MondayOAuthRefreshResponse(BaseModel):
    """Response for monday:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class MondayOAuthValidateResponse(BaseModel):
    """Response for monday:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    name: Optional[str] = Field(None, description="monday user name")
    email: Optional[str] = Field(None, description="monday account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Intercom OAuth Operation Responses
class IntercomOAuthExchangeResponse(BaseModel):
    """Response for intercom:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="Intercom admin/workspace name for display")
    email: Optional[str] = Field(None, description="Intercom account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class IntercomOAuthRefreshResponse(BaseModel):
    """Response for intercom:oauth:refresh request (no-op: tokens never expire)"""
    success: bool = Field(..., description="Whether the refresh request succeeded")
    expires_at: Optional[str] = Field(None, description="Always None — Intercom tokens never expire")
    message: Optional[str] = Field(None, description="Success or error message")


class IntercomOAuthValidateResponse(BaseModel):
    """Response for intercom:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="Always False — Intercom tokens never expire")
    name: Optional[str] = Field(None, description="Intercom admin/workspace name")
    email: Optional[str] = Field(None, description="Intercom account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Webflow OAuth Operation Responses
class WebflowOAuthExchangeResponse(BaseModel):
    """Response for webflow:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="Webflow user name for display")
    email: Optional[str] = Field(None, description="Webflow account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class WebflowOAuthRefreshResponse(BaseModel):
    """Response for webflow:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class WebflowOAuthValidateResponse(BaseModel):
    """Response for webflow:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    name: Optional[str] = Field(None, description="Webflow user name")
    email: Optional[str] = Field(None, description="Webflow account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# QuickBooks OAuth Operation Responses
class QuickBooksOAuthExchangeResponse(BaseModel):
    """Response for quickbooks:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="QuickBooks user name for display")
    email: Optional[str] = Field(None, description="QuickBooks account email for display")
    realm_id: Optional[str] = Field(None, description="QuickBooks company (realm) ID")
    message: Optional[str] = Field(None, description="Success or error message")


class QuickBooksOAuthRefreshResponse(BaseModel):
    """Response for quickbooks:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class QuickBooksOAuthValidateResponse(BaseModel):
    """Response for quickbooks:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    name: Optional[str] = Field(None, description="QuickBooks user name")
    email: Optional[str] = Field(None, description="QuickBooks account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Calendly OAuth Operation Responses
class CalendlyOAuthExchangeResponse(BaseModel):
    """Response for calendly:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="Calendly user name for display")
    email: Optional[str] = Field(None, description="Calendly account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class CalendlyOAuthRefreshResponse(BaseModel):
    """Response for calendly:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class CalendlyOAuthValidateResponse(BaseModel):
    """Response for calendly:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    name: Optional[str] = Field(None, description="Calendly user name")
    email: Optional[str] = Field(None, description="Calendly account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Sentry OAuth Operation Responses
class SentryOAuthExchangeResponse(BaseModel):
    """Response for sentry:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="Sentry user name for display")
    email: Optional[str] = Field(None, description="Sentry account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class SentryOAuthRefreshResponse(BaseModel):
    """Response for sentry:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class SentryOAuthValidateResponse(BaseModel):
    """Response for sentry:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    name: Optional[str] = Field(None, description="Sentry user name")
    email: Optional[str] = Field(None, description="Sentry account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# PostHog OAuth Operation Responses
class PostHogOAuthExchangeResponse(BaseModel):
    """Response for posthog:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="PostHog user name for display")
    email: Optional[str] = Field(None, description="PostHog account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class PostHogOAuthRefreshResponse(BaseModel):
    """Response for posthog:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class PostHogOAuthValidateResponse(BaseModel):
    """Response for posthog:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    name: Optional[str] = Field(None, description="PostHog user name")
    email: Optional[str] = Field(None, description="PostHog account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# LinkedIn OAuth Operation Responses
class LinkedInOAuthExchangeResponse(BaseModel):
    """Response for linkedin:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    email: Optional[str] = Field(None, description="LinkedIn account email for display")
    name: Optional[str] = Field(None, description="LinkedIn display name")
    message: Optional[str] = Field(None, description="Success or error message")


class LinkedInOAuthRefreshResponse(BaseModel):
    """Response for linkedin:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class LinkedInOAuthValidateResponse(BaseModel):
    """Response for linkedin:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    email: Optional[str] = Field(None, description="LinkedIn account email")
    name: Optional[str] = Field(None, description="LinkedIn display name")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Zendesk OAuth Operation Responses
class ZendeskOAuthExchangeResponse(BaseModel):
    """Response for zendesk:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="Zendesk user name for display")
    email: Optional[str] = Field(None, description="Zendesk account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class BambooHROAuthExchangeResponse(BaseModel):
    """Response for bamboohr:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="BambooHR user name for display")
    email: Optional[str] = Field(None, description="BambooHR account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class BambooHROAuthRefreshResponse(BaseModel):
    """Response for bamboohr:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class BambooHROAuthValidateResponse(BaseModel):
    """Response for bamboohr:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    name: Optional[str] = Field(None, description="BambooHR user name")
    email: Optional[str] = Field(None, description="BambooHR account email")
    message: Optional[str] = Field(None, description="Success or error message")


class KlaviyoOAuthExchangeResponse(BaseModel):
    """Response for klaviyo:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    message: Optional[str] = Field(None, description="Success or error message")


class KlaviyoOAuthRefreshResponse(BaseModel):
    """Response for klaviyo:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class KlaviyoOAuthValidateResponse(BaseModel):
    """Response for klaviyo:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    name: Optional[str] = Field(None, description="Klaviyo account name")
    message: Optional[str] = Field(None, description="Success or error message")


class ZendeskOAuthRefreshResponse(BaseModel):
    """Response for zendesk:oauth:refresh request"""
# Zoom OAuth Operation Responses
class ZoomOAuthExchangeResponse(BaseModel):
    """Response for zoom:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="Zoom user name for display")
    email: Optional[str] = Field(None, description="Zoom account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class ZoomOAuthRefreshResponse(BaseModel):
    """Response for zoom:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class ZendeskOAuthValidateResponse(BaseModel):
    """Response for zendesk:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    name: Optional[str] = Field(None, description="Zendesk user name")
    email: Optional[str] = Field(None, description="Zendesk account email")
class ZoomOAuthValidateResponse(BaseModel):
    """Response for zoom:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    name: Optional[str] = Field(None, description="Zoom user name")
    email: Optional[str] = Field(None, description="Zoom account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Apollo OAuth Operation Responses
class ApolloOAuthExchangeResponse(BaseModel):
    """Response for apollo:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    email: Optional[str] = Field(None, description="Apollo account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class ApolloOAuthRefreshResponse(BaseModel):
    """Response for apollo:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class ApolloOAuthValidateResponse(BaseModel):
    """Response for apollo:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    email: Optional[str] = Field(None, description="Apollo account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Microsoft OAuth Operation Responses
class MicrosoftOAuthExchangeResponse(BaseModel):
    """Response for microsoft:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    email: Optional[str] = Field(None, description="Microsoft account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class MicrosoftOAuthRefreshResponse(BaseModel):
    """Response for microsoft:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class MicrosoftOAuthValidateResponse(BaseModel):
    """Response for microsoft:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    email: Optional[str] = Field(None, description="Microsoft account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Notion OAuth Operation Responses
class NotionOAuthExchangeResponse(BaseModel):
    """Response for notion:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    workspace_name: Optional[str] = Field(None, description="Notion workspace name for display")
    workspace_id: Optional[str] = Field(None, description="Notion workspace ID")
    message: Optional[str] = Field(None, description="Success or error message")


class NotionOAuthRefreshResponse(BaseModel):
    """Response for notion:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class NotionOAuthValidateResponse(BaseModel):
    """Response for notion:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    workspace_name: Optional[str] = Field(None, description="Notion workspace name")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Reddit OAuth Operation Responses
class RedditOAuthExchangeResponse(BaseModel):
    """Response for reddit:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    username: Optional[str] = Field(None, description="Reddit username for display")
    message: Optional[str] = Field(None, description="Success or error message")


class RedditOAuthRefreshResponse(BaseModel):
    """Response for reddit:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class RedditOAuthValidateResponse(BaseModel):
    """Response for reddit:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    username: Optional[str] = Field(None, description="Reddit username")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Salesforce OAuth Operation Responses
class SalesforceOAuthExchangeResponse(BaseModel):
    """Response for salesforce:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    username: Optional[str] = Field(None, description="Salesforce username for display")
    email: Optional[str] = Field(None, description="Salesforce account email for display")
    organization_id: Optional[str] = Field(None, description="Salesforce organization ID")
    instance_url: Optional[str] = Field(None, description="Salesforce instance URL")
    message: Optional[str] = Field(None, description="Success or error message")


class SalesforceOAuthRefreshResponse(BaseModel):
    """Response for salesforce:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class SalesforceOAuthValidateResponse(BaseModel):
    """Response for salesforce:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    username: Optional[str] = Field(None, description="Salesforce username")
    email: Optional[str] = Field(None, description="Salesforce account email")
    organization_id: Optional[str] = Field(None, description="Salesforce organization ID")
    instance_url: Optional[str] = Field(None, description="Salesforce instance URL")
    message: Optional[str] = Field(None, description="Validation details or error message")


# HubSpot OAuth Responses
class HubSpotOAuthExchangeResponse(BaseModel):
    """Response for hubspot:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    email: Optional[str] = Field(None, description="HubSpot account email for display")
    hub_id: Optional[str] = Field(None, description="HubSpot Hub ID")
    message: Optional[str] = Field(None, description="Success or error message")


class HubSpotOAuthRefreshResponse(BaseModel):
    """Response for hubspot:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class HubSpotOAuthValidateResponse(BaseModel):
    """Response for hubspot:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    hub_id: Optional[str] = Field(None, description="HubSpot Hub ID")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Mailchimp OAuth Operation Responses
class MailchimpOAuthExchangeResponse(BaseModel):
    """Response for mailchimp:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    email: Optional[str] = Field(None, description="Mailchimp account email for display")
    server_prefix: Optional[str] = Field(None, description="Mailchimp datacenter (e.g., 'us1')")
    message: Optional[str] = Field(None, description="Success or error message")


# Typeform OAuth Operation Responses
class TypeformOAuthExchangeResponse(BaseModel):
    """Response for typeform:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    message: Optional[str] = Field(None, description="Success or error message")


# Fathom OAuth Operation Responses
class FathomOAuthExchangeResponse(BaseModel):
    """Response for fathom:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    email: Optional[str] = Field(None, description="Fathom account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class FathomOAuthRefreshResponse(BaseModel):
    """Response for fathom:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class FathomOAuthValidateResponse(BaseModel):
    """Response for fathom:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    email: Optional[str] = Field(None, description="Fathom account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Supabase OAuth Operation Responses
class SupabaseOAuthExchangeResponse(BaseModel):
    """Response for supabase:oauth:exchange / refresh / validate / select_project requests"""
    success: bool = Field(..., description="Whether the operation was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created/updated credential")
    credential_name: Optional[str] = Field(None, description="Name of the credential")
    project_url: Optional[str] = Field(None, description="Supabase project URL")
    message: Optional[str] = Field(None, description="Success or error message")
    needs_project_selection: bool = Field(False, description="True when user must pick from multiple projects")
    projects: Optional[list] = Field(None, description="List of projects when needs_project_selection is True")
    pending_id: Optional[str] = Field(None, description="Opaque token for select_project follow-up")


# Shopify OAuth Operation Responses
class ShopifyOAuthExchangeResponse(BaseModel):
    """Response for shopify:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    shop_name: Optional[str] = Field(None, description="Shopify store name for display")
    email: Optional[str] = Field(None, description="Shopify account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class ShopifyOAuthRefreshResponse(BaseModel):
    """Response for shopify:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class ShopifyOAuthValidateResponse(BaseModel):
    """Response for shopify:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    shop_name: Optional[str] = Field(None, description="Shopify store name")
    email: Optional[str] = Field(None, description="Shopify account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Twitter OAuth Operation Responses
class TwitterOAuthExchangeResponse(BaseModel):
    """Response for twitter:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    username: Optional[str] = Field(None, description="Twitter username for display")
    message: Optional[str] = Field(None, description="Success or error message")


class TwitterOAuthRefreshResponse(BaseModel):
    """Response for twitter:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class TwitterOAuthValidateResponse(BaseModel):
    """Response for twitter:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    username: Optional[str] = Field(None, description="Twitter username")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Slack OAuth Operation Responses
class SlackOAuthExchangeResponse(BaseModel):
    """Response for slack:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    team_id: Optional[str] = Field(None, description="Slack workspace ID for display")
    team_name: Optional[str] = Field(None, description="Slack workspace name for display")
    message: Optional[str] = Field(None, description="Success or error message")


class SlackOAuthRefreshResponse(BaseModel):
    """Response for slack:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class SlackOAuthValidateResponse(BaseModel):
    """Response for slack:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    team_name: Optional[str] = Field(None, description="Slack workspace name")
    message: Optional[str] = Field(None, description="Validation details or error message")


# WordPress OAuth Operation Responses
class WordPressOAuthExchangeResponse(BaseModel):
    """Response for wordpress:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    email: Optional[str] = Field(None, description="WordPress.com account email for display")
    username: Optional[str] = Field(None, description="WordPress.com username for display")
    site_url: Optional[str] = Field(None, description="WordPress.com site URL for display")
    message: Optional[str] = Field(None, description="Success or error message")


class WordPressOAuthRefreshResponse(BaseModel):
    """Response for wordpress:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class WordPressOAuthValidateResponse(BaseModel):
    """Response for wordpress:oauth:validate request"""
    success: bool = Field(..., description="Whether validation was successful")
    is_valid: bool = Field(..., description="Whether the OAuth token is valid")
    message: Optional[str] = Field(None, description="Validation details or error message")


# TikTok OAuth Operation Responses
class TikTokOAuthExchangeResponse(BaseModel):
    """Response for tiktok:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    display_name: Optional[str] = Field(None, description="TikTok display name for the connected account")
    message: Optional[str] = Field(None, description="Success or error message")


class TikTokOAuthRefreshResponse(BaseModel):
    """Response for tiktok:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class TikTokOAuthValidateResponse(BaseModel):
    """Response for tiktok:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 60 minutes")
    display_name: Optional[str] = Field(None, description="TikTok display name for the connected account")
    message: Optional[str] = Field(None, description="Validation details or error message")


# Saved Output Responses - for managing reusable mock/test data
class SavedOutputInfo(BaseModel):
    """Information about a saved output"""
    id: str = Field(..., description="UUID of the saved output")
    user_id: str = Field(..., description="UUID of the owner")
    node_type: str = Field(..., description="Type of the node this output is for")
    name: str = Field(..., description="User-provided name for this saved output")
    output: Dict[str, Any] = Field(..., description="The saved output data")
    visibility: str = Field(..., description="Visibility level: 'user', 'organization', or 'public'")
    created_at: str = Field(..., description="Creation timestamp in ISO format")
    updated_at: str = Field(..., description="Last update timestamp in ISO format")


class SavedOutputListResponse(BaseModel):
    """Response for saved_output:list request"""
    saved_outputs: List[SavedOutputInfo] = Field(..., description="List of saved outputs")


class SavedOutputGetResponse(BaseModel):
    """Response for saved_output:get request"""
    saved_output: SavedOutputInfo = Field(..., description="Saved output details")


class SavedOutputCreateResponse(BaseModel):
    """Response for saved_output:create request"""
    success: bool = Field(..., description="Whether creation was successful")
    saved_output: Optional[SavedOutputInfo] = Field(None, description="Created saved output info")
    message: Optional[str] = Field(None, description="Success or error message")


class SavedOutputUpdateResponse(BaseModel):
    """Response for saved_output:update request"""
    success: bool = Field(..., description="Whether update was successful")
    saved_output: Optional[SavedOutputInfo] = Field(None, description="Updated saved output info")
    message: Optional[str] = Field(None, description="Success or error message")


class SavedOutputDeleteResponse(BaseModel):
    """Response for saved_output:delete request"""
    success: bool = Field(..., description="Whether deletion was successful")
    message: str = Field(..., description="Success or error message")
    saved_output_id: Optional[str] = Field(None, description="UUID of the deleted saved output")


# ============================================================================
# Resource Sharing Response Models
# ============================================================================

class ShareInfo(BaseModel):
    """Information about a resource share"""
    id: str = Field(..., description="UUID of the share")
    resource_type: str = Field(..., description="Type of resource (workflow, database)")
    resource_id: str = Field(..., description="UUID of the shared resource")
    target_type: str = Field(..., description="Share target type (user, organization, public)")
    target_user_id: Optional[str] = Field(None, description="UUID of target user (if user share)")
    target_email: Optional[str] = Field(None, description="Email of target user (for pending invites)")
    target_avatar_url: Optional[str] = Field(None, description="Avatar URL of target user (if user share)")
    target_org_id: Optional[str] = Field(None, description="UUID of target org (if org share)")
    target_org_name: Optional[str] = Field(None, description="Name of target org (for display)")
    target_org_icon_url: Optional[str] = Field(None, description="Icon URL of target org (if org share)")
    target_display_name: Optional[str] = Field(None, description="Display name of target (email, org name, or 'Anyone with the link')")
    permission: str = Field(..., description="Permission level (view, edit)")
    shared_by: str = Field(..., description="UUID of user who created the share")
    shared_by_email: Optional[str] = Field(None, description="Email of user who created the share")
    created_at: str = Field(..., description="Creation timestamp in ISO format")
    is_pending: bool = Field(False, description="True if share is for a user who hasn't signed up yet")
    public_url: Optional[str] = Field(None, description="Public share URL (if public share)")


class ShareCreateResponse(BaseModel):
    """Response for share:create request"""
    success: bool = Field(..., description="Whether share was created successfully")
    share: Optional[ShareInfo] = Field(None, description="Created share info")
    message: Optional[str] = Field(None, description="Success or error message")
    error: Optional[str] = Field(None, description="Error message if failed")


class ShareListResponse(BaseModel):
    """Response for share:list request"""
    shares: List[ShareInfo] = Field(default_factory=list, description="List of shares for the resource")
    error: Optional[str] = Field(None, description="Error message if failed")


class ShareUpdateResponse(BaseModel):
    """Response for share:update request"""
    success: bool = Field(..., description="Whether update was successful")
    share: Optional[ShareInfo] = Field(None, description="Updated share info")
    message: Optional[str] = Field(None, description="Success or error message")
    error: Optional[str] = Field(None, description="Error message if failed")


class ShareDeleteResponse(BaseModel):
    """Response for share:delete request"""
    success: bool = Field(..., description="Whether deletion was successful")
    message: str = Field("", description="Success or error message")
    share_id: Optional[str] = Field(None, description="UUID of the deleted share")
    error: Optional[str] = Field(None, description="Error message if failed")


class ShareLeaveResponse(BaseModel):
    """Response for share:leave request"""
    success: bool = Field(..., description="Whether the request was handled")
    resource_id: Optional[str] = Field(None, description="UUID of the resource the caller left")
    removed: bool = Field(False, description="True if a direct user-share row was actually deleted; False if the caller had no direct share (access came via an org/folder share, which this can't drop)")
    error: Optional[str] = Field(None, description="Error message if failed")


class ShareInviteLinkResponse(BaseModel):
    """Response for share:invite_link request"""
    success: bool = Field(..., description="Whether the invite link is available")
    token: Optional[str] = Field(None, description="Invite link token (carried in the /i/<token> URL)")
    url: Optional[str] = Field(None, description="Full shareable invite URL")
    permission: Optional[str] = Field(None, description="Permission granted on redemption (view, edit)")
    error: Optional[str] = Field(None, description="Error message if failed")


class ShareInviteAcceptResponse(BaseModel):
    """Response for share:invite_accept request"""
    success: bool = Field(..., description="Whether the invite was redeemed")
    workflow_id: Optional[str] = Field(None, description="UUID of the workflow the user now collaborates on")
    workflow_name: Optional[str] = Field(None, description="Name of the workflow (for display)")
    refresh_jwt: bool = Field(False, description="True when the joiner was onboarded by the redeem (frontend should refresh the session JWT so the onboarding_completed claim updates)")
    error: Optional[str] = Field(None, description="Error message if failed")


class AgentShareLinkResponse(BaseModel):
    """Response for the agent_share manage events (get_or_create / rotate /
    set_active): the current capability link for one agent node."""
    success: bool = Field(..., description="Whether the operation succeeded")
    link_id: Optional[str] = Field(None, description="Capability id (None when error is set)")
    url: Optional[str] = Field(None, description="Public chat page URL (/a/{link_id})")
    is_active: Optional[bool] = Field(None, description="Whether the link currently accepts visitors")
    error: Optional[str] = Field(None, description="Error message if failed")


class RunShareCreateResponse(BaseModel):
    """Response for run_share:create — the public read-only page for one
    finished Test Run."""
    success: bool = Field(..., description="Whether the link was minted")
    link_id: Optional[str] = Field(None, description="Capability id (None when error is set)")
    url: Optional[str] = Field(None, description="Public run page URL (/r/{link_id})")
    error: Optional[str] = Field(None, description="Error message if failed")


class SharedAgentAckResponse(BaseModel):
    """Ack for shared_agent:send — emitted before the agent turn runs; the
    turn itself streams via chat:message / agent:state on the visitor's sid."""
    accepted: bool = Field(..., description="Whether the turn was dispatched")
    conversation_id: Optional[str] = Field(None, description="Conversation id the streamed events will carry")
    error: Optional[str] = Field(None, description="link_inactive | busy | agent_unavailable")


class SharedAgentResumeResponse(BaseModel):
    """Response for shared_agent:resume — the visitor's own thread history."""
    conversation_id: Optional[str] = Field(None, description="Conversation id for the visitor's thread")
    messages: List[Dict[str, Any]] = Field(default_factory=list, description="Persisted chat events for the thread")
    error: Optional[str] = Field(None, description="link_inactive if the link no longer resolves")


class SharedResourceInfo(BaseModel):
    """Information about a resource shared with the current user"""
    resource_type: str = Field(..., description="Type of resource (workflow, database)")
    resource_id: str = Field(..., description="UUID of the resource")
    resource_name: str = Field(..., description="Name of the resource")
    resource_description: Optional[str] = Field(None, description="Description of the resource")
    permission: str = Field(..., description="Permission level (view, edit)")
    shared_by_email: str = Field(..., description="Email of user who shared the resource")
    shared_by_name: Optional[str] = Field(None, description="Display name of user who shared")
    shared_at: str = Field(..., description="When the resource was shared")
    # For organization location
    organization_id: Optional[str] = Field(None, description="Organization ID if resource is in an org")
    organization_name: Optional[str] = Field(None, description="Organization name for display")


class ShareListSharedWithMeResponse(BaseModel):
    """Response for share:list_shared_with_me request"""
    resources: List[SharedResourceInfo] = Field(default_factory=list, description="List of resources shared with user")
    error: Optional[str] = Field(None, description="Error message if failed")


class ForkedResourceInfo(BaseModel):
    """Information about a forked resource"""
    id: str = Field(..., description="UUID of the forked resource")
    name: str = Field(..., description="Name of the forked resource")
    resource_type: str = Field(..., description="Type of resource (workflow, database)")
    owner_id: Optional[str] = Field(None, description="Owner ID (for personal resources)")
    organization_id: Optional[str] = Field(None, description="Organization ID (for org resources)")
    forked_from_id: str = Field(..., description="UUID of the original resource")
    forked_from_name: str = Field(..., description="Name of the original resource")


class ResourceForkResponse(BaseModel):
    """Response for resource:fork request"""
    success: bool = Field(..., description="Whether fork was successful")
    forked_resource: Optional[ForkedResourceInfo] = Field(None, description="Info about the newly created fork")
    message: Optional[str] = Field(None, description="Success message")
    error: Optional[str] = Field(None, description="Error message if failed")


# ============================================================================
# Workflow Template Response Models (SEO-friendly template library)
# ============================================================================

















# ============================================================================
# Workflow MCP Response Models (with dual-delivery for real-time frontend updates)
# ============================================================================

class WorkflowMCPNodeInfo(BaseModel):
    """Information about a workflow node"""
    id: str = Field(..., description="Node ID")
    type: str = Field(..., description="Node type")
    position: Dict[str, float] = Field(..., description="Node position {x, y}")
    data: Dict[str, Any] = Field(default_factory=dict, description="Node data including config, output, etc.")


class WorkflowMCPDeleteWorkflowResponse(BaseModel):
    """Response for workflow:mcp:delete_workflow - dual-delivered to frontend"""
    mcp_config: ClassVar[dict] = {
        "notify_frontend": True,
        "frontend_event_name": "mcp:workflow:delete_workflow:response"
    }
    success: bool = Field(..., description="Whether the deletion succeeded")
    workflow_id: str = Field(..., description="ID of the deleted workflow")
    message: Optional[str] = Field(None, description="Status message or error")


class WorkflowMCPUpdateWorkflowMetadataResponse(BaseModel):
    """Response for workflow:mcp:update_workflow_metadata - dual-delivered to frontend"""
    mcp_config: ClassVar[dict] = {
        "notify_frontend": True,
        "frontend_event_name": "mcp:workflow:update_workflow_metadata:response"
    }
    success: bool = Field(..., description="Whether the update succeeded")
    workflow_id: str = Field(..., description="ID of the updated workflow")
    name: Optional[str] = Field(None, description="Updated name (if changed)")
    description: Optional[str] = Field(None, description="Updated description (if changed)")
    message: Optional[str] = Field(None, description="Status message or error")


class WorkflowMCPCreateWorkflowResponse(BaseModel):
    """Response for workflow:mcp:create_workflow - dual-delivered to frontend"""
    mcp_config: ClassVar[dict] = {
        "notify_frontend": True,
        "frontend_event_name": "mcp:workflow:create_workflow:response"
    }
    success: bool = Field(..., description="Whether the creation succeeded")
    workflow_id: str = Field(..., description="ID of the created workflow")
    name: str = Field(..., description="Name of the created workflow")
    description: Optional[str] = Field(None, description="Description of the created workflow")
    organization_id: Optional[str] = Field(None, description="Owning organization, if any")
    folder_id: Optional[str] = Field(None, description="Containing folder, if any")
    message: Optional[str] = Field(None, description="Status message or error")


class WorkflowMCPGetNodeConfigResponse(BaseModel):
    """Response for workflow:mcp:get_node_config"""
    success: bool = Field(..., description="Whether the request succeeded")
    workflow_id: str = Field(..., description="ID of the workflow")
    node_id: str = Field(..., description="ID of the node")
    node_type: Optional[str] = Field(None, description="Type of the node")
    position: Optional[Dict[str, float]] = Field(None, description="Node position {x, y}")
    config: Optional[Dict[str, Any]] = Field(None, description="Node configuration")
    message: Optional[str] = Field(None, description="Error message if failed")


class InterfaceBlockInfo(BaseModel):
    """Information about a single interface block on the grid"""
    id: str = Field(..., description="Block/node ID")
    type: str = Field(..., description="Block type (e.g. 'form', 'markdown')")
    x: int = Field(..., description="Grid column position")
    y: int = Field(..., description="Grid row position")
    w: int = Field(..., description="Width in grid columns")
    h: int = Field(..., description="Height in grid rows")
    minW: int = Field(2, description="Minimum width in grid columns")
    minH: int = Field(2, description="Minimum height in grid rows")


class WorkflowMCPUpdateInterfaceResponse(BaseModel):
    """Response for workflow:mcp:update_interface - dual-delivered to frontend"""
    mcp_config: ClassVar[dict] = {
        "notify_frontend": True,
        "frontend_event_name": "mcp:workflow:update_interface:response"
    }
    success: bool = Field(..., description="Whether the interface was updated successfully")
    workflow_id: str = Field(..., description="ID of the modified workflow")
    blocks: Optional[List[InterfaceBlockInfo]] = Field(None, description="Current interface blocks with positions")
    interface_state: Optional[Dict[str, Any]] = Field(None, description="Full interface state for frontend sync")
    message: Optional[str] = Field(None, description="Status message or error")


# ============================================================================
# Workflow Checkpoint Response Models
# ============================================================================

class CheckpointInfo(BaseModel):
    """Information about a workflow checkpoint"""
    id: str = Field(..., description="Checkpoint UUID")
    workflow_id: str = Field(..., description="Workflow UUID")
    name: str = Field(..., description="Human-readable checkpoint name")
    description: str = Field("", description="Optional description")
    created_at: str = Field(..., description="Creation timestamp in ISO format")


class WorkflowCheckpointListResponse(BaseModel):
    """Response for workflow:checkpoint:list request"""
    checkpoints: List[CheckpointInfo] = Field(default_factory=list, description="List of checkpoints")


class WorkflowCheckpointCreateResponse(BaseModel):
    """Response for workflow:checkpoint:create request"""
    success: bool = Field(..., description="Whether creation was successful")
    checkpoint: Optional[CheckpointInfo] = Field(None, description="Created checkpoint info")
    message: Optional[str] = Field(None, description="Success or error message")


class WorkflowCheckpointRestoreResponse(BaseModel):
    """Response for workflow:checkpoint:restore request"""
    success: bool = Field(..., description="Whether restore was successful")
    workflow: Optional[Dict[str, Any]] = Field(None, description="Restored workflow (nodes, edges)")
    message: Optional[str] = Field(None, description="Success or error message")


class WorkflowCheckpointDeleteResponse(BaseModel):
    """Response for workflow:checkpoint:delete request"""
    success: bool = Field(..., description="Whether deletion was successful")
    message: str = Field(..., description="Success or error message")
    checkpoint_id: Optional[str] = Field(None, description="UUID of the deleted checkpoint")


# ============================================================================
# MCP OAuth Response Models
# ============================================================================

class MCPOAuthDiscoverResponse(BaseModel):
    """Response for mcp:oauth:discover request"""
    success: bool = Field(True, description="Whether discovery was successful")
    requires_oauth: bool = Field(..., description="Whether the MCP server requires OAuth")
    provider_name: Optional[str] = Field(None, description="Name of the OAuth provider")
    authorization_endpoint: Optional[str] = Field(None, description="OAuth authorization endpoint URL")
    token_endpoint: Optional[str] = Field(None, description="OAuth token endpoint URL")
    scopes_supported: Optional[List[str]] = Field(None, description="Supported OAuth scopes")
    supports_dynamic_registration: bool = Field(False, description="Whether dynamic client registration is supported")
    registration_endpoint: Optional[str] = Field(None, description="Dynamic client registration endpoint")
    code_verifier: Optional[str] = Field(None, description="PKCE code verifier")
    code_challenge: Optional[str] = Field(None, description="PKCE code challenge")
    resource_url: Optional[str] = Field(None, description="Resource URL for token request")
    error: Optional[str] = Field(None, description="Error message if discovery failed")


class MCPOAuthExchangeResponse(BaseModel):
    """Response for mcp:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    provider_name: Optional[str] = Field(None, description="Provider name")
    message: Optional[str] = Field(None, description="Success or error message")


class MCPOAuthRegisterClientResponse(BaseModel):
    """Response for mcp:oauth:register-client request"""
    success: bool = Field(..., description="Whether client registration was successful")
    client_id: Optional[str] = Field(None, description="Registered OAuth client ID")
    message: Optional[str] = Field(None, description="Success or error message")


# ============================================================================
# Workflow Resource Response Models
# ============================================================================

class ResourceInfo(BaseModel):
    """Information about a workflow resource"""
    id: str = Field(..., description="Resource UUID")
    owner_id: str = Field(..., description="Owner user UUID")
    organization_id: Optional[str] = Field(None, description="Organization UUID if applicable")
    workflow_id: str = Field(..., description="Parent workflow UUID")
    node_id: Optional[str] = Field(None, description="Workflow node ID that produced this resource")
    resource_type: str = Field(..., description="Type: dataset, file, image, video, audio, document")
    name: str = Field(..., description="Display name")
    mime_type: Optional[str] = Field(None, description="MIME type for blob resources")
    size_bytes: int = Field(0, description="File size in bytes")
    storage_ref: Optional[str] = Field(None, description="R2 storage key for blobs")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary metadata")
    created_at: str = Field(..., description="Creation timestamp ISO string")
    updated_at: str = Field(..., description="Last update timestamp ISO string")


class ResourceCreateResponse(BaseModel):
    """Response for resource:create request"""
    success: bool = Field(..., description="Whether creation was successful")
    resource: Optional[ResourceInfo] = Field(None, description="Created resource info")


class ResourceListResponse(BaseModel):
    """Response for resource:list request"""
    resources: List[ResourceInfo] = Field(..., description="List of resources")


class ResourceGetResponse(BaseModel):
    """Response for resource:get request"""
    resource: ResourceInfo = Field(..., description="Resource details")


class ResourceDeleteResponse(BaseModel):
    """Response for resource:delete request"""
    success: bool = Field(..., description="Whether deletion was successful")
    message: str = Field(..., description="Success or error message")


class ResourceUploadUrlResponse(BaseModel):
    """Response for resource:upload_url request"""
    upload_url: str = Field(..., description="Presigned PUT URL")
    storage_ref: str = Field(..., description="R2 key for the uploaded file")


class ResourceDownloadUrlResponse(BaseModel):
    """Response for resource:download_url request"""
    download_url: str = Field(..., description="Presigned GET URL")


class DatasetRowInfo(BaseModel):
    """Information about a single dataset row"""
    id: str = Field(..., description="Row UUID")
    row_index: int = Field(..., description="Row index within the dataset")
    data: Dict[str, Any] = Field(..., description="Row data")
    created_at: str = Field(..., description="Creation timestamp ISO string")


class ResourceDatasetRowsResponse(BaseModel):
    """Response for resource:dataset:rows request"""
    rows: List[DatasetRowInfo] = Field(..., description="Dataset rows")
    total_count: int = Field(..., description="Total number of rows in the dataset")


class ResourceDatasetAppendResponse(BaseModel):
    """Response for resource:dataset:append request"""
    success: bool = Field(..., description="Whether append was successful")
    inserted_count: int = Field(..., description="Number of rows inserted")


class ResourceDatasetUpdateRowResponse(BaseModel):
    """Response for resource:dataset:update_row request"""
    success: bool = Field(..., description="Whether update was successful")


class ResourceDatasetDeleteRowsResponse(BaseModel):
    """Response for resource:dataset:delete_rows request"""
    success: bool = Field(..., description="Whether deletion was successful")
    deleted_count: int = Field(..., description="Number of rows deleted")


# Codex Device Code Auth Responses
class CodexDeviceCodeStartResponse(BaseModel):
    """Response for codex:auth:start — returns verification URL and user code"""
    success: bool = Field(..., description="Whether device code request was successful")
    verification_url: Optional[str] = Field(None, description="URL to open in browser for user to authorize")
    user_code: Optional[str] = Field(None, description="One-time code for the user to enter")
    device_auth_id: Optional[str] = Field(None, description="Device auth session ID for polling")
    interval: Optional[int] = Field(None, description="Polling interval in seconds")
    message: Optional[str] = Field(None, description="Success or error message")


class CodexDeviceCodePollResponse(BaseModel):
    """Response for codex:auth:poll — returns status of device code approval"""
    success: bool = Field(..., description="Whether the poll request itself succeeded")
    status: str = Field("pending", description="One of: pending, completed, error")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential (on completion)")
    credential_name: Optional[str] = Field(None, description="Name of the created credential (on completion)")
    message: Optional[str] = Field(None, description="Status or error message")










# Claude Code OAuth PKCE Auth Responses
class ClaudeCodeAuthStartResponse(BaseModel):
    """Response for claude-code:auth:start"""
    success: bool = Field(..., description="Whether the OAuth start was successful")
    auth_url: Optional[str] = Field(None, description="URL to open in browser for authentication")
    auth_session_id: Optional[str] = Field(None, description="Session ID for exchanging the code")
    message: Optional[str] = Field(None, description="Status or error message")


class ClaudeCodeAuthExchangeResponse(BaseModel):
    """Response for claude-code:auth:exchange"""
    success: bool = Field(..., description="Whether the code exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    message: Optional[str] = Field(None, description="Status or error message")


# WhatsApp QR Code Auth Responses
class WhatsAppQRStartResponse(BaseModel):
    """Response for whatsapp:qr:start — returns QR code for scanning"""
    success: bool = Field(..., description="Whether QR code generation was successful")
    connection_id: Optional[str] = Field(None, description="WAHooks connection ID")
    qr_code: Optional[str] = Field(None, description="Base64 encoded QR code PNG image")
    message: Optional[str] = Field(None, description="Status or error message")
    code: Optional[str] = Field(None, description="Machine-readable failure class, e.g. wahooks_key_missing")


class WhatsAppQRStatusResponse(BaseModel):
    """Response for whatsapp:qr:status — returns connection status"""
    success: bool = Field(..., description="Whether the status check succeeded")
    status: str = Field("pending", description="One of: pending, connected, error")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential (when connected)")
    credential_name: Optional[str] = Field(None, description="Name of the created credential (when connected)")
    phone_number: Optional[str] = Field(None, description="Connected phone number (when connected)")
    qr_code: Optional[str] = Field(None, description="New QR code if previous one expired")
    message: Optional[str] = Field(None, description="Status or error message")


# ============================================================================
# Skill Response Models
# ============================================================================

class SkillSummary(BaseModel):
    """Lightweight skill listing entry — body fields stripped for list views."""
    id: str = Field(..., description="Skill UUID")
    owner_id: Optional[str] = Field(None, description="Author user UUID (NULL for system skills)")
    organization_id: Optional[str] = Field(None, description="Owning org UUID (NULL for system skills)")
    is_system: bool = Field(False, description="Platform-maintained skill loaded for every builder call")
    name: str = Field(..., description="Skill name")
    description: str = Field("", description="Few-sentence retrieval hint")
    has_text: bool = Field(False, description="Whether body_text is non-empty")
    has_workflow: bool = Field(False, description="Whether body_workflow is non-empty")
    enabled: bool = Field(True, description="Owner-side default enabled flag")
    muted: bool = Field(False, description="Whether the calling user has muted this skill")
    created_at: str = Field(..., description="Creation timestamp ISO string")
    updated_at: str = Field(..., description="Last update timestamp ISO string")


class SkillDetail(BaseModel):
    """Full skill record including bodies."""
    id: str = Field(..., description="Skill UUID")
    owner_id: Optional[str] = Field(None, description="Author user UUID")
    organization_id: Optional[str] = Field(None, description="Owning org UUID")
    is_system: bool = Field(False, description="Platform-maintained skill")
    name: str = Field(..., description="Skill name")
    description: str = Field("", description="Few-sentence retrieval hint")
    body_text: Optional[str] = Field(None, description="Optional prose body")
    body_workflow: Optional[Dict[str, Any]] = Field(None, description="Optional workflow graph (same shape as workflows.workflow)")
    display_metadata: Dict[str, Any] = Field(default_factory=dict, description="Viewport / UI state for body_workflow")
    enabled: bool = Field(True, description="Owner-side default enabled flag")
    muted: bool = Field(False, description="Whether the calling user has muted this skill")
    created_at: str = Field(..., description="Creation timestamp ISO string")
    updated_at: str = Field(..., description="Last update timestamp ISO string")


class SkillListResponse(BaseModel):
    """Response for skill:list — buckets skills by relationship to the caller.

    The `system` field is omitted entirely for non-internal users (skills they
    can't see don't even appear as an empty bucket).
    """
    owned: List[SkillSummary] = Field(default_factory=list, description="Skills the caller authored or is in the org of")
    shared: List[SkillSummary] = Field(default_factory=list, description="Skills shared with the caller via resource_shares")
    system: Optional[List[SkillSummary]] = Field(None, description="Platform-maintained skills (internal users only)")


class SkillGetResponse(BaseModel):
    """Response for skill:get / skill:create — full skill detail."""
    skill: SkillDetail = Field(..., description="Skill record")


class SkillCreateResponse(BaseModel):
    """Response for skill:create."""
    success: bool = Field(..., description="Whether creation succeeded")
    skill: Optional[SkillDetail] = Field(None, description="Newly created skill")


class SkillUpdateResponse(BaseModel):
    """Response for skill:update."""
    success: bool = Field(..., description="Whether update succeeded")
    skill: Optional[SkillDetail] = Field(None, description="Updated skill")


class SkillDeleteResponse(BaseModel):
    """Response for skill:delete."""
    success: bool = Field(..., description="Whether deletion succeeded")
    message: str = Field("", description="Status or error message")


class SkillMuteResponse(BaseModel):
    """Response for skill:mute / skill:unmute."""
    success: bool = Field(..., description="Whether the mute state change succeeded")
    muted: bool = Field(..., description="Resulting mute state for this skill")


class SkillWorkflowResponse(BaseModel):
    """Response for skill:get_workflow — returns just the workflow body + display metadata."""
    skill_id: str = Field(..., description="Skill UUID")
    body_workflow: Optional[Dict[str, Any]] = Field(None, description="Workflow graph")
    display_metadata: Dict[str, Any] = Field(default_factory=dict, description="Viewport / UI state")


class SkillUpdateWorkflowResponse(BaseModel):
    """Response for skill:update_workflow."""
    success: bool = Field(..., description="Whether the workflow body was saved")


# Parallel OAuth Responses
class ParallelOAuthExchangeResponse(BaseModel):
    """Response for parallel:oauth:exchange."""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    message: Optional[str] = Field(None, description="Success or error message")


class ParallelOAuthValidateResponse(BaseModel):
    """Response for parallel:oauth:validate."""
    valid: bool = Field(..., description="Whether the API key is still active")
# Pipedrive OAuth Operation Responses
class PipedriveOAuthExchangeResponse(BaseModel):
    """Response for pipedrive:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    name: Optional[str] = Field(None, description="Pipedrive user name for display")
    email: Optional[str] = Field(None, description="Pipedrive account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class PipedriveOAuthRefreshResponse(BaseModel):
    """Response for pipedrive:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class PipedriveOAuthValidateResponse(BaseModel):
    """Response for pipedrive:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 5 minutes")
    name: Optional[str] = Field(None, description="Pipedrive user name")
    email: Optional[str] = Field(None, description="Pipedrive account email")
    message: Optional[str] = Field(None, description="Validation details or error message")


class CloudflareOAuthExchangeResponse(BaseModel):
    """Response for cloudflare:oauth:exchange request"""
    success: bool = Field(..., description="Whether token exchange was successful")
    credential_id: Optional[str] = Field(None, description="UUID of the created credential")
    credential_name: Optional[str] = Field(None, description="Name of the created credential")
    email: Optional[str] = Field(None, description="Cloudflare account email for display")
    message: Optional[str] = Field(None, description="Success or error message")


class CloudflareOAuthRefreshResponse(BaseModel):
    """Response for cloudflare:oauth:refresh request"""
    success: bool = Field(..., description="Whether token refresh was successful")
    expires_at: Optional[str] = Field(None, description="New token expiry time (ISO 8601)")
    message: Optional[str] = Field(None, description="Success or error message")


class CloudflareOAuthValidateResponse(BaseModel):
    """Response for cloudflare:oauth:validate request"""
    valid: bool = Field(..., description="Whether the OAuth token is valid")
    expires_soon: bool = Field(False, description="True if token expires within 1 hour")
    email: Optional[str] = Field(None, description="Cloudflare account email")
    message: Optional[str] = Field(None, description="Validation details or error message")
