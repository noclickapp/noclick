"""
Pydantic models for client-to-server socket events.
These models define the expected structure of data sent from frontend to backend,
enabling type validation and automatic TypeScript generation.

A more appropriate name would just be request_events.py since the source of the request
can now be frontend or API given the addition of sandboxes.
"""
from typing import ClassVar, Optional, List, Dict, Any, Union, Literal
from pydantic import BaseModel, Field, ConfigDict
from wss.sender.schema import ContentItem


# Base class for client events with TypeScript type generation support
class ClientEventBase(BaseModel):
    """Base class for client events with optional request correlation"""
    model_config = ConfigDict(extra='allow')  # Allow extra fields (e.g., _user_id injected by sandbox)

    request_id: Optional[str] = Field(None, description="UUID for request/response correlation")

    # Class variable to indicate if this request expects a response
    # Defaults to True for backward compatibility, override to False for one-way events
    expects_response: ClassVar[bool] = True

    # Class variable to indicate if this event should be available in user app templates
    # Defaults to False (internal only), override to True for public APIs
    available_in_template: ClassVar[bool] = False
    
    @classmethod
    def get_typescript_type(cls) -> str:
        """Override this to specify custom TypeScript type for the event data.
        Return None to use the default interface name.
        """
        return None


# Chat Events
class ChatMessageContext(BaseModel):
    """Context information sent with each chat message to ensure accurate workspace targeting."""
    app_id: Optional[str] = Field(None, description="Current app ID the user is viewing/editing")
    app_name: Optional[str] = Field(None, description="Current app name for display purposes")
    workflow_id: Optional[str] = Field(None, description="Active workflow ID — stamped on the conversation row so the sidebar can later auto-restore the latest conversation per workflow")


class ChatMessageRequest(ClientEventBase):
    """Request sent when user sends a chat message"""
    event_name: ClassVar[str] = "chat:message"
    expects_response: ClassVar[bool] = False  # One-way event

    conversation_id: Optional[str] = Field(
        None,
        description="Conversation session ID for associating messages with specific conversation context"
    )
    content: List[ContentItem] = Field(..., description="Sequence-sensitive content items")
    model: str = Field(..., description="Model to use for this request (e.g., 'gpt-4o', 'claude-3-sonnet')")
    env: Optional[Dict[str, str]] = Field(None, description="Environment variables for model configuration (e.g., API keys)")
    context: Optional[ChatMessageContext] = Field(None, description="Message context including current app info for accurate cwd targeting")


# YJS Sync Events
class YjsSyncRequest(ClientEventBase):
    """YJS synchronization data"""
    event_name: ClassVar[str] = "yjs:sync"
    expects_response: ClassVar[bool] = False  # One-way event
    
    data: bytes = Field(..., description="YJS sync binary data")
    
    @classmethod
    def get_typescript_type(cls) -> str:
        """Can be sent as Uint8Array or number array"""
        return "Uint8Array | number[]"
    
    @classmethod
    def model_validate(cls, obj):
        """Custom parser to handle Uint8Array from frontend"""
        if isinstance(obj, list):
            # Direct array of numbers
            return cls(data=bytes(obj))
        elif isinstance(obj, bytes):
            # Direct bytes
            return cls(data=obj)
        elif isinstance(obj, dict) and isinstance(obj.get('data'), list):
            # Object with data field as array
            obj['data'] = bytes(obj['data'])
            return super().model_validate(obj)
        elif isinstance(obj, dict) and isinstance(obj.get('data'), bytes):
            # Object with data field as bytes
            return super().model_validate(obj)
        else:
            # Fallback
            return super().model_validate(obj)
# Agent Operation Events
class AgentRunCommandRequest(ClientEventBase):
    """Request from agent runtime to execute a command in sandbox"""
    event_name: ClassVar[str] = "agent:run:command"
    command: str = Field(..., description="Bash command to execute")
    cwd: Optional[str] = Field(None, description="Working directory for the command")
    timeout: Optional[int] = Field(None, description="Command timeout in seconds")


class AgentSetCwdRequest(ClientEventBase):
    """Request to update the agent's working directory"""
    event_name: ClassVar[str] = "agent:set:cwd"
    path: str = Field(..., description="Absolute path within the mounted workspace")
    conversation_id: Optional[str] = Field(None, description="Conversation ID to target specific agent (defaults to sid)")
    app_id: Optional[str] = Field(None, description="App ID if working within an app context")
    app_name: Optional[str] = Field(None, description="App name if working within an app context")
    expects_response: ClassVar[bool] = False


class AgentPauseRequest(ClientEventBase):
    """Request to pause the active agent session"""
    event_name: ClassVar[str] = "agent:pause"
    conversation_id: Optional[str] = Field(None, description="Conversation ID to target specific agent (defaults to sid)")
    expects_response: ClassVar[bool] = False


# Conversation Management Events
class ListConversationsRequest(ClientEventBase):
    """Request to list all available conversation sessions"""
    event_name: ClassVar[str] = "conversations:list"


class ResumeConversationRequest(ClientEventBase):
    """Request to resume a specific conversation session"""
    event_name: ClassVar[str] = "conversation:resume"
    session_id: str = Field(..., description="Session ID to resume")


class DeleteConversationRequest(ClientEventBase):
    """Request to delete a conversation and all its data"""
    event_name: ClassVar[str] = "conversation:delete"
    conversation_id: str = Field(..., description="Conversation ID to delete")
    expects_response: ClassVar[bool] = True


class ListConversationsForAgentRequest(ClientEventBase):
    """List every conversation owned by the current user that's scoped to a
    specific agent node (workflow_id + node_id). Powers the per-agent chat
    history list in the Interface-tab AgentChatBlock."""
    event_name: ClassVar[str] = "conversation:list_for_agent"
    workflow_id: str = Field(..., description="UUID of the workflow containing the agent")
    node_id: str = Field(..., description="Node id of the agent within the workflow")
    expects_response: ClassVar[bool] = True


class GetLatestConversationForWorkflowRequest(ClientEventBase):
    """Request the most-recently-active conversation tied to a given workflow.

    Used by the sidebar on workflow open to decide between auto-restoring the
    last conversation (when the current sidebar is empty) and offering a
    "Resume previous" pill (when it isn't).
    """
    event_name: ClassVar[str] = "conversation:get_latest_for_workflow"
    workflow_id: str = Field(..., description="UUID of the workflow whose latest conversation to fetch")
    expects_response: ClassVar[bool] = True


class AgentReadFileRequest(ClientEventBase):
    """Request from agent runtime to read a file in sandbox"""
    event_name: ClassVar[str] = "agent:read:file"
    path: str = Field(..., description="File path to read")


class AgentWriteFileRequest(ClientEventBase):
    """Request from agent runtime to write a file in sandbox"""
    event_name: ClassVar[str] = "agent:write:file"
    path: str = Field(..., description="File path to write")
    content: str = Field(..., description="Content to write to the file")


class AgentEditFileRequest(ClientEventBase):
    """Request from agent runtime to edit a file using OHEditor in sandbox"""
    event_name: ClassVar[str] = "agent:edit:file"
    path: str = Field(..., description="File path to edit")
    command: str = Field(..., description="Editor command (view, create, str_replace, etc.)")
    file_text: Optional[str] = Field(None, description="Full file text for create command")
    old_str: Optional[str] = Field(None, description="String to replace for str_replace command")
    new_str: Optional[str] = Field(None, description="Replacement string for str_replace command")
    insert_line: Optional[int] = Field(None, description="Line number for insert command")
    view_range: Optional[List[int]] = Field(None, description="Line range for view command")


class AgentListFilesRequest(ClientEventBase):
    """Request from agent runtime to list files in sandbox"""
    event_name: ClassVar[str] = "agent:list:files"
    path: Optional[str] = Field(None, description="Directory path to list (defaults to workspace root)")


class AgentCopyToRequest(ClientEventBase):
    """Request from agent runtime to copy files to sandbox"""
    event_name: ClassVar[str] = "agent:copy:to"
    content: str = Field(..., description="Base64 encoded file content")
    dest_path: str = Field(..., description="Destination path in sandbox")
    recursive: bool = Field(False, description="Whether to extract as directory (if content is zip)")


class AgentCopyFromRequest(ClientEventBase):
    """Request from agent runtime to copy files from sandbox"""
    event_name: ClassVar[str] = "agent:copy:from"
    path: str = Field(..., description="Path in sandbox to copy from")

# Authentication Events
class UpdateAuthRequest(ClientEventBase):
    """Request to update authentication when the access token refreshes"""
    event_name: ClassVar[str] = "update_auth"
    expects_response: ClassVar[bool] = True  # Expects confirmation response

    token: str = Field(..., description="Refreshed Supabase access token (JWT)")

# Onboarding Events
class OnboardingSubmitRequest(ClientEventBase):
    """Request to submit onboarding questionnaire responses"""
    event_name: ClassVar[str] = "onboarding:submit"

    responses: Dict[str, Any] = Field(..., description="User's questionnaire responses as key-value pairs")
    version: int = Field(default=1, description="Questionnaire version for tracking schema changes")


class OnboardingSkipRequest(ClientEventBase):
    """Persist an onboarding skip server-side (scaffold / agent-SEO arrivals).

    Writes a `user_onboarding_responses` row so the `onboarding_completed` JWT
    claim flips true durably — otherwise these users defer onboarding only via a
    session-only sessionStorage flag and get re-prompted on the next dashboard
    remount. Mirrors the invite-join path's server-side onboarding write.
    """
    event_name: ClassVar[str] = "onboarding:skip"

    source: str = Field(default="scaffold", description="What deferred onboarding (e.g. 'scaffold')")


class OnboardingCompletionGetRequest(ClientEventBase):
    """Request to get user's onboarding completion state"""
    event_name: ClassVar[str] = "onboarding:completion:get"


class OnboardingCompletionUpdateRequest(ClientEventBase):
    """Request to update user's onboarding completion state"""
    event_name: ClassVar[str] = "onboarding:completion:update"

    data: Dict[str, Any] = Field(..., description="Partial update to merge with existing completion data")


# Notification preference events (system alert emails: run failures, credits, digest)
class NotificationPrefsGetRequest(ClientEventBase):
    """Request the user's notification email preferences"""
    event_name: ClassVar[str] = "notifications:prefs:get"


class NotificationPrefsUpdateRequest(ClientEventBase):
    """Update one or more notification email categories (partial merge)"""
    event_name: ClassVar[str] = "notifications:prefs:update"

    prefs: Dict[str, bool] = Field(..., description="Category → enabled, e.g. {'run_failure': false}")


# Instance OAuth app configuration (self-hosted: one OAuth client per provider)
class InstanceOAuthListRequest(ClientEventBase):
    """List the providers this instance has an OAuth app configured for"""
    event_name: ClassVar[str] = "instance_oauth:list"


class InstanceOAuthSetRequest(ClientEventBase):
    """Store one provider's OAuth app (client id, and optionally its secret)"""
    event_name: ClassVar[str] = "instance_oauth:set"

    provider: str = Field(..., description="Provider key, e.g. 'linear'")
    client_id: str = Field(..., min_length=1, description="OAuth app client id")
    client_secret: Optional[str] = Field(
        None, description="OAuth app client secret; omit to leave a stored one unchanged")


class InstanceOAuthDeleteRequest(ClientEventBase):
    """Forget one provider's OAuth app"""
    event_name: ClassVar[str] = "instance_oauth:delete"

    provider: str = Field(..., description="Provider key, e.g. 'linear'")


class InstanceKeysListRequest(ClientEventBase):
    """List the model-provider keys this instance has stored server-side"""
    event_name: ClassVar[str] = "instance_keys:list"


class InstanceKeysSetRequest(ClientEventBase):
    """Store one server-side provider key (e.g. OPENROUTER_API_KEY)"""
    event_name: ClassVar[str] = "instance_keys:set"

    env_var: str = Field(..., description="Environment variable name the key is read from")
    value: str = Field(..., min_length=1, description="The key")


class InstanceSmtpSetRequest(ClientEventBase):
    """Store the instance's outbound mail server after checking a login against it"""
    event_name: ClassVar[str] = "instance_smtp:set"

    host: str = Field(..., min_length=1, description="SMTP host")
    port: int = Field(587, ge=1, le=65535, description="SMTP port (587 STARTTLS, 465 TLS)")
    username: str = Field("", description="Login user; blank for an open relay")
    password: str = Field("", description="Login password")
    from_email: str = Field(..., min_length=3, description="Sender, e.g. NoClick <noclick@yourdomain.com>")


class InstanceKeysDeleteRequest(ClientEventBase):
    """Forget one server-side provider key"""
    event_name: ClassVar[str] = "instance_keys:delete"

    env_var: str = Field(..., description="Environment variable name")


# Feedback events (in-app navbar feedback / bug report button)
class SubmitFeedbackRequest(ClientEventBase):
    """Request to submit a piece of user feedback or a bug report"""
    event_name: ClassVar[str] = "feedback:submit"

    message: str = Field(..., description="The feedback text the user typed")
    feedback_type: Literal["bug", "idea", "general"] = Field(
        default="general", description="Feedback category: bug report, idea, or general"
    )
    page_url: Optional[str] = Field(None, description="URL the user was on when submitting, for context")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Optional client context (user agent, etc.)")


# Credentials Events
class CredentialCreateRequest(ClientEventBase):
    """Request to create a new encrypted credential"""
    event_name: ClassVar[str] = "credential:create"

    name: str = Field(..., description="Human-readable name for the credential")
    credential_type: str = Field(..., description="Type: 'oauth', 'api_key', 'database', 'third_party'")
    credential_data: Dict[str, Any] = Field(..., description="Credential data to be encrypted")
    metadata: Optional[Dict[str, Any]] = Field({}, description="Optional metadata (provider, service URL, etc.)")


class CredentialListRequest(ClientEventBase):
    """Request to list all credentials owned by the current user"""
    event_name: ClassVar[str] = "credential:list"


class CredentialGetRequest(ClientEventBase):
    """Request to get a specific credential by ID (returns decrypted data)"""
    event_name: ClassVar[str] = "credential:get"

    credential_id: str = Field(..., description="UUID of the credential to retrieve")


class CredentialDisplayInfoRequest(ClientEventBase):
    """Request display-only metadata (name, type, owner) for the credentials a
    workflow's nodes reference. Gated by workflow access — returns NO secret and
    grants NO access; lets collaborators see the name + owner of credentials the
    flow uses (which are resolved as the owner at execution)."""
    event_name: ClassVar[str] = "credential:display_info"

    workflow_id: str = Field(..., description="Workflow whose node credentials to describe")


class CredentialAuthorizeForWorkflowRequest(ClientEventBase):
    """Fired when the OWNER explicitly selects a credential on a node, to authorize it
    for run-as-owner resolution on this workflow. Owner-gated server-side: a
    collaborator's call is a no-op (they can't introduce an owner credential). This is
    the trustworthy authorization signal for the collaborative frontend — credentialIds
    in the blob/autosave aren't trusted because a collaborator can inject them via the
    presence channel."""
    event_name: ClassVar[str] = "credential:authorize_for_workflow"

    workflow_id: str = Field(..., description="Workflow the credential is being authorized for")
    credential_id: str = Field(..., description="The credential the owner just placed on a node")


class CredentialUpdateRequest(ClientEventBase):
    """Request to update a credential"""
    event_name: ClassVar[str] = "credential:update"

    credential_id: str = Field(..., description="UUID of the credential to update")
    name: Optional[str] = Field(None, description="New name for the credential")
    credential_data: Optional[Dict[str, Any]] = Field(None, description="New credential data to be encrypted")
    metadata: Optional[Dict[str, Any]] = Field(None, description="New metadata")


class CredentialDeleteRequest(ClientEventBase):
    """Request to delete a credential"""
    event_name: ClassVar[str] = "credential:delete"

    credential_id: str = Field(..., description="UUID of the credential to delete")
    confirm: bool = Field(
        False,
        description=(
            "False = dry run: return the workflows referencing this credential "
            "without deleting. True = deregister dependent trigger webhooks and delete."
        ),
    )


# Credential Request Events (request credentials from external users)
class CredentialRequestCreateRequest(ClientEventBase):
    """Request to create a credential request and send email to target"""
    event_name: ClassVar[str] = "credential:request:create"

    target_email: str = Field("", description="Email of the person to request credentials from. Empty for a shareable copy-link request (no email is sent).")
    credential_type: str = Field(..., description="Credential type to request (e.g. 'google_sheets_oauth', 'openai_api_key')")
    message: Optional[str] = Field(None, description="Optional message to include in the request email")
    frontend_url: Optional[str] = Field(None, description="Frontend URL for constructing the provision link")


class CredentialRequestListRequest(ClientEventBase):
    """Request to list all outgoing credential requests for the current user"""
    event_name: ClassVar[str] = "credential:request:list"


class CredentialRequestCancelRequest(ClientEventBase):
    """Request to cancel a pending credential request"""
    event_name: ClassVar[str] = "credential:request:cancel"

    credential_request_id: str = Field(..., description="UUID of the credential request to cancel")


class CredentialValidateAccessRequest(ClientEventBase):
    """Post-connect API access validation for credentials that require it (e.g. GBP)."""
    event_name: ClassVar[str] = "credential:validate_access"

    credential_id: str = Field(..., description="UUID of the newly created credential to validate")
    node_type: str = Field(..., description="Node type to look up the validate_credential_access classmethod")


# Usage Dashboard Events
class UsageDataRequest(ClientEventBase):
    """Request to fetch usage data with optional filters"""
    event_name: ClassVar[str] = "usage:data"

    start_date: Optional[str] = Field(None, description="Start date filter (ISO format)")
    end_date: Optional[str] = Field(None, description="End date filter (ISO format)")
    usage_type: Optional[str] = Field(None, description="Filter by usage type (ai_usage, cpu_usage, gpu_usage)")
    usage_subtype: Optional[str] = Field(None, description="Filter by specific model or instance type")
    group_by: str = Field("day", description="Group by: day, week, month, type, subtype")
    limit: Optional[int] = Field(100, description="Limit number of results")
    organization_id: Optional[str] = Field(None, description="Organization workspace to scope to; omit/null for personal (events with organization_id IS NULL)")


class UsageLogsRequest(ClientEventBase):
    """Request to fetch recent usage log entries"""
    event_name: ClassVar[str] = "usage:logs"

    limit: int = Field(20, description="Number of recent log entries to fetch")
    usage_type: Optional[str] = Field(None, description="Filter by usage type category (ai_builder / ai_usage / api_usage / cpu_usage / gpu_usage)")
    search: Optional[str] = Field(None, description="Case-insensitive substring filter on usage_subtype (model/service name)")
    before: Optional[str] = Field(None, description="Pagination cursor: return events strictly older than this ISO timestamp (the last row of the previous page)")
    organization_id: Optional[str] = Field(None, description="Organization workspace to scope to; omit/null for personal (events with organization_id IS NULL)")


# Debug Events
# Trigger Tests Events (internal only — dev Debug tab + 12h scheduled worker)
# Analytics Events (internal team only)
# Workflow Events
class WorkflowCreateRequest(ClientEventBase):
    """Request to create a new workflow"""
    event_name: ClassVar[str] = "workflow:create"

    name: str = Field(..., description="Human-readable name for the workflow")
    description: Optional[str] = Field("", description="Description of what the workflow does")
    workflow_data: Optional[Dict[str, Any]] = Field(
        {},
        description="Workflow configuration including nodes, edges, and settings"
    )
    permissions: Optional[Dict[str, Any]] = Field(
        {"public": [], "shared_with": {}},
        description="Access permissions: {public: ['VIEW', 'EXECUTE'], shared_with: {user_id: ['VIEW', 'EDIT']}}"
    )
    visibility: Optional[str] = Field(
        None,
        description="Resource visibility: 'personal' (private to user) or 'organization' (shared with org). Defaults to personal."
    )
    organization_permission: Optional[str] = Field(
        None,
        description="Permission level for org members when visibility='organization': 'view' or 'edit'. Defaults to 'edit'."
    )
    folder_id: Optional[str] = Field(
        None,
        description="Folder UUID to create workflow in (null for root level)"
    )


class WorkflowListRequest(ClientEventBase):
    """Request to list all workflows owned by the current user"""
    event_name: ClassVar[str] = "workflow:list"

    folder_id: Optional[str] = Field(
        None,
        description="Folder UUID to filter by (null for root level only)"
    )
    scope_org_id: Optional[str] = Field(
        None,
        description="Explicit org scope: '' = personal, '<uuid>' = that org, "
                    "null = use the active (is_primary) context. The browser sends "
                    "its own scope so the response can't be mismatched by the "
                    "org-switch race."
    )


class WorkflowGetRequest(ClientEventBase):
    """Request to get a specific workflow by ID"""
    event_name: ClassVar[str] = "workflow:get"

    workflow_id: str = Field(..., description="UUID of the workflow to retrieve")


class WorkflowNodeSetConfigRequest(ClientEventBase):
    """Request to update a single node's config fields (merge semantics)."""
    event_name: ClassVar[str] = "workflow:node:set_config"

    workflow_id: str = Field(..., description="UUID of the workflow")
    node_id: str = Field(..., description="ID of the node to update")
    config: Dict[str, Any] = Field(..., description="Config fields to merge into existing node config")


class WorkflowNodeGetConfigRequest(ClientEventBase):
    """Get a single node's config fields."""
    event_name: ClassVar[str] = "workflow:node:get_config"

    workflow_id: str = Field(..., description="UUID of the workflow")
    node_id: str = Field(..., description="ID of the node")


class WorkflowUpdateRequest(ClientEventBase):
    """Request to update a workflow's data or metadata"""
    event_name: ClassVar[str] = "workflow:update"

    workflow_id: str = Field(..., description="UUID of the workflow to update")
    name: Optional[str] = Field(None, description="New name for the workflow")
    description: Optional[str] = Field(None, description="New description for the workflow")
    workflow_data: Optional[Dict[str, Any]] = Field(
        None,
        description="Updated workflow configuration (nodes, edges, settings)"
    )
    permissions: Optional[Dict[str, Any]] = Field(
        None,
        description="Updated access permissions"
    )
    display_metadata: Optional[Dict[str, Any]] = Field(
        None,
        description="UI display state: viewport (x,y,zoom), selectedNodeId, flowHelperView state"
    )
    settings: Optional[Dict[str, Any]] = Field(
        None,
        description="Workflow-level settings (e.g. min_required_balance). Merged with existing settings on update."
    )
    deleted_node_ids: Optional[List[str]] = Field(
        None,
        description="IDs of nodes that were deleted since last update. Used to cleanup cron schedules."
    )
    expected_graph_version: Optional[int] = Field(
        None,
        description="CAS guard for workflow_data writes: the graph_version this client loaded. When set and the server's version differs, the write is rejected and the response carries conflict=true plus the current blob + version so the client can rebase. Omitted (None) = unconditional write (metadata-only updates, MCP/builder writers)."
    )


class WorkflowDeleteRequest(ClientEventBase):
    """Request to delete a workflow"""
    event_name: ClassVar[str] = "workflow:delete"

    workflow_id: str = Field(..., description="UUID of the workflow to delete")


class WorkflowRestoreRequest(ClientEventBase):
    """Request to restore a soft-deleted workflow from trash"""
    event_name: ClassVar[str] = "workflow:restore"

    workflow_id: str = Field(..., description="UUID of the workflow to restore from trash")


class WorkflowListTrashRequest(ClientEventBase):
    """Request to list all soft-deleted (trashed) workflows"""
    event_name: ClassVar[str] = "workflow:list_trash"


class WorkflowPermanentDeleteRequest(ClientEventBase):
    """Request to permanently delete a trashed workflow"""
    event_name: ClassVar[str] = "workflow:permanent_delete"

    workflow_id: str = Field(..., description="UUID of the trashed workflow to permanently delete")


class WorkflowExecuteRequest(ClientEventBase):
    """Request to execute a workflow.

    For frontend use: provide nodes and edges directly.
    For template/app use: omit nodes/edges to fetch from DB, optionally provide inputs.
    """
    event_name: ClassVar[str] = "workflow:execute"
    expects_response: ClassVar[bool] = False  # Execution updates sent via events
    available_in_template: ClassVar[bool] = True  # Expose to user app templates

    workflow_id: str = Field(..., description="UUID of the workflow being executed")
    trigger_source: Optional[str] = Field(
        None,
        description="How the run was kicked off: manual | webhook | cron | mcp | api. "
                    "Persisted on the execution row (defaults to 'manual')."
    )
    nodes: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Workflow nodes to execute. If not provided, fetched from database."
    )
    edges: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Connections between nodes. If not provided, fetched from database."
    )
    replay_nodes: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Full workflow nodes to snapshot for execution-log replay. Execution still uses nodes."
    )
    replay_edges: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Full workflow edges to snapshot for execution-log replay. Execution still uses edges."
    )
    start_node_id: Optional[str] = Field(
        None,
        description="Optional starting node ID. If provided, only executes nodes reachable from this node. "
                    "Used by webhooks to specify the trigger node. If not provided, executes all nodes."
    )
    inputs: Optional[Dict[str, Any]] = Field(
        None,
        description="Input data to inject into the workflow. Injected into start_node_id if provided, "
                    "otherwise into auto-detected trigger node or first node with no predecessors."
    )
    conversation_id: Optional[str] = Field(
        None,
        description="Conversation ID for agent memory persistence (workflow chat only). "
                    "When set, agent nodes use this for conversation history."
    )
    config_overrides: Optional[Dict[str, Dict[str, Any]]] = Field(
        None,
        description="Per-node config overrides keyed by node ID. Merged into node config before execution. "
                    "Used by SDK clients to set dynamic parameters (for example an agent message)."
    )
    forward_only: Optional[bool] = Field(
        None,
        description="When True with start_node_id, only execute the start node and its downstream nodes "
                    "(no predecessors). Used by 'Run from here' when no upstream references are detected."
    )
    background: Optional[bool] = Field(
        False,
        description="When True, this run was triggered by an interface component fetching its own data "
                    "(via the @noclick/sdk), not by an explicit user 'Run'. Background runs are echoed "
                    "back on workflow:started so the client can keep them out of the global run indicator."
    )


class WorkflowExecutionListRequest(ClientEventBase):
    """Request a (filtered, paginated) page of execution logs for a workflow.

    Pagination is cursor-based via ``(started_at, id)`` — stable in the face of
    new executions landing while the user pages through old ones. Filters and
    search hit the same indexed path (idx_workflow_executions_workflow_started),
    so each page costs ~one index-range probe regardless of total table size."""
    event_name: ClassVar[str] = "workflow:list_executions"

    workflow_id: str = Field(..., description="UUID of the workflow to get execution logs for")
    limit: Optional[int] = Field(50, description="Page size (1..200; default 50)")
    cursor_started_at: Optional[str] = Field(
        None,
        description="ISO timestamp from the LAST row of the previous page. "
                    "Next page returns rows strictly older than this (with id as tiebreak)."
    )
    cursor_id: Optional[str] = Field(
        None,
        description="UUID from the last row of the previous page; tiebreaker when "
                    "two executions share started_at down to the microsecond."
    )
    status: Optional[List[str]] = Field(
        None,
        description="Raw DB status values to include (e.g. ['completed', 'error']). "
                    "Null = all statuses. The frontend maps UI status labels "
                    "(success/error/running/waiting) → DB values."
    )
    trigger_source: Optional[List[str]] = Field(
        None,
        description="Raw trigger_source values to include (e.g. ['cron','webhook']). "
                    "Null/empty = any trigger."
    )
    search: Optional[str] = Field(
        None,
        description="Case-insensitive substring match against the execution's "
                    "error column (the only meaningful text column on the row — "
                    "the 'Processed N nodes' fallback message is computed, not stored)."
    )


class WorkflowExecutionCountsRequest(ClientEventBase):
    """Request the per-status / per-trigger / total counts for a workflow's
    executions. One round-trip — single GROUPING SETS query against the new
    INCLUDE index does this as an Index-Only Scan (no heap I/O at prod scale)."""
    event_name: ClassVar[str] = "workflow:get_execution_counts"

    workflow_id: str = Field(..., description="UUID of the workflow")


class WorkflowExecutionDetailRequest(ClientEventBase):
    """Request the full detail of one past execution: the graph snapshot + per-node
    status/error metadata for the read-only replay (node outputs fetched lazily)."""
    event_name: ClassVar[str] = "workflow:get_execution_detail"

    workflow_id: str = Field(..., description="UUID of the workflow")
    execution_id: str = Field(..., description="UUID of the execution to inspect")


class WorkflowNodeOutputRequest(ClientEventBase):
    """Request one node's reassembled output for a past execution (lazy, on click)."""
    event_name: ClassVar[str] = "workflow:get_node_output"

    workflow_id: str = Field(..., description="UUID of the workflow")
    execution_id: str = Field(..., description="UUID of the execution")
    node_id: str = Field(..., description="Node whose output to reassemble")


class WorkflowCollabTokenRequest(ClientEventBase):
    """Request to get a JWT token for workflow relay collaborative presence.

    Returns a short-lived JWT that can be used to authenticate with the
    configured workflow relay for real-time collaboration.
    """
    event_name: ClassVar[str] = "workflow:collab_token"

    workflow_id: str = Field(..., description="UUID of the workflow to get collaboration token for")


class WorkflowNodeConfigSchemaRequest(ClientEventBase):
    """Request to get config schema for a node type"""
    event_name: ClassVar[str] = "workflow:node:get_config_schema"

    node_type: str = Field(..., description="Type of the node (e.g., 'automation-telegram', 'agent')")


class WorkflowNodeValidateConfigRequest(ClientEventBase):
    """Request to validate a node's configuration"""
    event_name: ClassVar[str] = "workflow:node:validate_config"

    node_type: str = Field(..., description="Type of the node")
    config_data: Dict[str, Any] = Field(..., description="Configuration data to validate")


class WorkflowNodeEvaluateExpressionRequest(ClientEventBase):
    """Evaluate a single inline expression against connected nodes' sample outputs
    for a live editor preview. Stateless: the client sends the data it already has."""
    event_name: ClassVar[str] = "workflow:node:evaluate_expression"

    expression: str = Field(..., description="The inner JS expression to evaluate (without the surrounding {{ }})")
    sample_outputs: Dict[str, Any] = Field(default_factory=dict, description="Connected nodes' last/sample outputs keyed by node id (include the reserved 'vars')")
    workflow_nodes: Optional[List[Dict[str, Any]]] = Field(default=None, description="Workflow nodes (id + data.label) so $('Node Label') resolves like at runtime")
    primary_input: Optional[Any] = Field(default=None, description="The $json value — the single direct upstream node's output")


class WorkflowNodeLoadOptionsRequest(ClientEventBase):
    """Request to load dynamic options for a node field (e.g., list of spreadsheets)"""
    event_name: ClassVar[str] = "workflow:node:load_options"

    node_type: str = Field(..., description="Type of the node (e.g., 'automation-google-sheets')")
    field_name: str = Field(..., description="Name of the field needing options (e.g., 'spreadsheet_id')")
    # Optional — some fields don't require a user credential (e.g. the LLM
    # agent's model dropdown, which lists models from a static + OpenRouter
    # catalog the BE owns). The handler already accepts a missing credential
    # via `if request.credential_id:`; this just stops Pydantic from
    # rejecting the request with a 'string_type' error before it gets there.
    credential_id: Optional[str] = Field(default=None, description="UUID of the credential to use for API calls; null when the field's source doesn't require user credentials")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Additional context (e.g., selected spreadsheet for listing worksheets)")
    page_token: Optional[str] = Field(default=None, description="Token for loading next page of options (pagination)")
    search: Optional[str] = Field(default=None, description="User-typed search term to narrow options. Nodes whose upstream API supports a native query parameter pass it through; nodes without server-side search paginate up to a safety cap and case-insensitive substring filter on label/value.")


class CredentialTestConnectionRequest(ClientEventBase):
    """Ask a provider to prove a credential works, in terms a human recognises.

    Answers "is this really connected?" with the user's own channels or repos
    rather than a tick, and — when the probe went through a config field's own
    options loader — returns values that can fill that field directly, so the
    proof doubles as the picker.
    """
    event_name: ClassVar[str] = "credential:test_connection"

    node_type: str = Field(..., description="Type of the node whose credential is being proven (e.g. 'automation-slack')")
    credential_id: str = Field(..., description="UUID of the credential to prove")
    organization_id: Optional[str] = Field(default=None, description="Organization the work is billed to, when the node is org-scoped")
    workflow_id: Optional[str] = Field(default=None, description="Workflow the credential is attached to, for the owner-fallback resolution")


class RehearsalScenariosRequest(ClientEventBase):
    """List the staged situations this workflow can rehearse.

    Derived from the saved graph: a situation is offered only when the workflow
    contains a trigger node of the type its payload is shaped for, so the Test
    screen's pickers are real controls fed by real data — never a menu of runs
    that would fail on click.
    """
    event_name: ClassVar[str] = "rehearsal:scenarios"

    workflow_id: str = Field(..., description="Workflow whose rehearsable situations are being listed")


class RehearsalRunRequest(ClientEventBase):
    """Run this workflow's agent for real against a fabricated world.

    Nothing outward happens: every tool call is answered by a mock session, so
    no credential is resolved and no provider request is made. It demonstrates
    behaviour and proves nothing about connectivity — that is what
    credential:test_connection is for, and the UI must not conflate them.
    """
    event_name: ClassVar[str] = "rehearsal:run"

    workflow_id: str = Field(..., description="Workflow whose agent is being rehearsed")
    scenario: str = Field("sales-inbound-lead", description="Slug of the staged situation to run against")
    lead_patch: Optional[Dict[str, str]] = Field(
        None,
        description="Builder edits to the staged message, in lead terms "
                    "(title/body/author/handle). Applied to the provider payload "
                    "server-side so the edited event is what actually runs.",
    )


class WorkflowNodeLoadValueRequest(ClientEventBase):
    """Request to load a computed/generated value for a node field (e.g., webhook URL)"""
    event_name: ClassVar[str] = "workflow:node:load_value"

    node_type: str = Field(..., description="Type of the node (e.g., 'trigger-webhook')")
    field_name: str = Field(..., description="Name of the field to compute (e.g., 'webhook_url')")
    workflow_id: str = Field(..., description="UUID of the workflow containing the node")
    node_id: str = Field(..., description="ID of the node in the workflow")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Additional context for value computation")
    credential_ids: Optional[Dict[str, str]] = Field(default=None, description="Map of credential_type -> credential_id for API calls (e.g., telegram_bot_token -> uuid)")


class WorkflowClearNodeStateRequest(ClientEventBase):
    """Request to clear persistent state for a workflow node (e.g., State Manager, RSS seen items)"""
    event_name: ClassVar[str] = "workflow:clear_node_state"

    workflow_id: str = Field(..., description="UUID of the workflow containing the node")
    node_id: str = Field(..., description="ID of the node whose state should be cleared")

class WorkflowSaveNodeStateRequest(ClientEventBase):
    """Save persistent state for a workflow node (used by the SDK state.set)"""
    event_name: ClassVar[str] = "workflow:save_node_state"

    workflow_id: str = Field(..., description="UUID of the workflow containing the node")
    node_id: str = Field(..., description="ID of the node whose state should be saved")
    values: dict = Field(..., description="The form values to persist")


class WorkflowLoadNodeStateRequest(ClientEventBase):
    """Load persistent state for a workflow node"""
    event_name: ClassVar[str] = "workflow:load_node_state"

    workflow_id: str = Field(..., description="UUID of the workflow containing the node")
    node_id: str = Field(..., description="ID of the node whose state should be loaded")


class WorkflowStateGetRequest(ClientEventBase):
    """Get a state value by key, auto-resolving the state-manager node."""
    event_name: ClassVar[str] = "workflow:state:get"

    workflow_id: str = Field(..., description="UUID of the workflow")
    key: str = Field(..., description="State key to read")
    node_id: Optional[str] = Field(None, description="Explicit state-manager node ID (auto-detected if omitted)")


class WorkflowStateSetRequest(ClientEventBase):
    """Set a state value by key, auto-resolving the state-manager node."""
    event_name: ClassVar[str] = "workflow:state:set"

    workflow_id: str = Field(..., description="UUID of the workflow")
    key: str = Field(..., description="State key to write")
    # Optional with a None default: a null (or omitted) value means "delete the key".
    # Required would reject the delete path, where serializers drop the null value.
    value: Any = Field(None, description="Value to store; null/omitted deletes the key")
    node_id: Optional[str] = Field(None, description="Explicit state-manager node ID (auto-detected if omitted)")


class WorkflowStateKeysRequest(ClientEventBase):
    """List all state keys."""
    event_name: ClassVar[str] = "workflow:state:keys"

    workflow_id: str = Field(..., description="UUID of the workflow")
    node_id: Optional[str] = Field(None, description="Explicit state-manager node ID")

# Google OAuth Events
class GoogleOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "google:oauth:exchange"

    code: str = Field(..., description="Authorization code from Google OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    credential_name: str = Field(..., description="Human-readable name for the credential")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")
    custom_client_id: Optional[str] = Field(None, description="BYOO OAuth client ID")
    custom_client_secret: Optional[str] = Field(None, description="BYOO OAuth client secret")


class GoogleOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired OAuth token"""
    event_name: ClassVar[str] = "google:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class GoogleOAuthValidateRequest(ClientEventBase):
    """Validate if an OAuth token is still valid"""
    event_name: ClassVar[str] = "google:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Airtable OAuth Events
class AirtableOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential (uses PKCE)"""
    event_name: ClassVar[str] = "airtable:oauth:exchange"

    code: str = Field(..., description="Authorization code from Airtable OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    code_verifier: str = Field(..., description="PKCE code verifier used during authorization")
    credential_name: str = Field(..., description="Human-readable name for the credential")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")


class AirtableOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Airtable OAuth token"""
    event_name: ClassVar[str] = "airtable:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class AirtableOAuthValidateRequest(ClientEventBase):
    """Validate if an Airtable OAuth token is still valid"""
    event_name: ClassVar[str] = "airtable:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Stripe OAuth Events
class StripeOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential (no PKCE)"""
    event_name: ClassVar[str] = "stripe:oauth:exchange"

    code: str = Field(..., description="Authorization code from Stripe Connect OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")


class StripeOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Stripe OAuth token"""
    event_name: ClassVar[str] = "stripe:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class StripeOAuthValidateRequest(ClientEventBase):
    """Validate if a Stripe OAuth token is still valid"""
    event_name: ClassVar[str] = "stripe:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# GitHub OAuth Events
class GithubOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "github:oauth:exchange"

    code: str = Field(..., description="Authorization code from GitHub OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    credential_name: str = Field(..., description="Human-readable name for the credential")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")


class GithubOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired GitHub OAuth token (only if expiring tokens enabled)"""
    event_name: ClassVar[str] = "github:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class GithubOAuthValidateRequest(ClientEventBase):
    """Validate if a GitHub OAuth token is still valid"""
    event_name: ClassVar[str] = "github:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Salesforce OAuth Events
class SalesforceOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "salesforce:oauth:exchange"

    code: str = Field(..., description="Authorization code from Salesforce OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    credential_name: str = Field(..., description="Human-readable name for the credential")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")
    is_sandbox: bool = Field(False, description="Whether this is a Salesforce sandbox org")
    code_verifier: Optional[str] = Field(None, description="PKCE code verifier for token exchange")


class SalesforceOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Salesforce OAuth token"""
    event_name: ClassVar[str] = "salesforce:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class SalesforceOAuthValidateRequest(ClientEventBase):
    """Validate if a Salesforce OAuth token is still valid"""
    event_name: ClassVar[str] = "salesforce:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Canva OAuth Events
class CanvaOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential (uses PKCE)"""
    event_name: ClassVar[str] = "canva:oauth:exchange"

    code: str = Field(..., description="Authorization code from Canva OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    code_verifier: str = Field(..., description="PKCE code verifier used during authorization")
    credential_name: str = Field(..., description="Human-readable name for the credential")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")


class CanvaOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Canva OAuth token"""
    event_name: ClassVar[str] = "canva:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class CanvaOAuthValidateRequest(ClientEventBase):
    """Validate if a Canva OAuth token is still valid"""
    event_name: ClassVar[str] = "canva:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# HubSpot OAuth Events
class HubSpotOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "hubspot:oauth:exchange"

    code: str = Field(..., description="Authorization code from HubSpot OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    credential_name: str = Field(..., description="Human-readable name for the credential")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")


class HubSpotOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired HubSpot OAuth token"""
    event_name: ClassVar[str] = "hubspot:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class HubSpotOAuthValidateRequest(ClientEventBase):
    """Validate if a HubSpot OAuth token is still valid"""
    event_name: ClassVar[str] = "hubspot:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Mailchimp OAuth Events
class MailchimpOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "mailchimp:oauth:exchange"

    code: str = Field(..., description="Authorization code from Mailchimp OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    credential_name: str = Field(..., description="Human-readable name for the credential")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")


# Typeform OAuth Events
class TypeformOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "typeform:oauth:exchange"

    code: str = Field(..., description="Authorization code from Typeform OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    credential_name: str = Field(..., description="Human-readable name for the credential")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")


# Fathom OAuth Events
class FathomOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential."""
    event_name: ClassVar[str] = "fathom:oauth:exchange"

    code: str = Field(..., description="Authorization code from Fathom OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    credential_name: str = Field(..., description="Human-readable name for the credential")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")


class FathomOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Fathom OAuth token."""
    event_name: ClassVar[str] = "fathom:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class FathomOAuthValidateRequest(ClientEventBase):
    """Validate if a Fathom OAuth token is still valid."""
    event_name: ClassVar[str] = "fathom:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Supabase OAuth Events
class SupabaseOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential (uses PKCE).
    No project_url needed — backend lists projects after token exchange."""
    event_name: ClassVar[str] = "supabase:oauth:exchange"

    code: str = Field(..., description="Authorization code from Supabase OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    code_verifier: str = Field(..., description="PKCE code verifier used during authorization")
    credential_name: str = Field(..., description="Human-readable name for the credential")


class SupabaseOAuthSelectProjectRequest(ClientEventBase):
    """Select a specific project after the user is shown a project list."""
    event_name: ClassVar[str] = "supabase:oauth:select_project"

    project_ref: str = Field(..., description="The project ref (ID) the user selected")
    pending_id: str = Field(..., description="Opaque identifier returned with needs_project_selection")


class SupabaseOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Supabase OAuth token"""
    event_name: ClassVar[str] = "supabase:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class SupabaseOAuthValidateRequest(ClientEventBase):
    """Validate if a Supabase OAuth token is still valid"""
    event_name: ClassVar[str] = "supabase:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Shopify OAuth Events
class ShopifyOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "shopify:oauth:exchange"

    code: str = Field(..., description="Authorization code from Shopify OAuth callback")
    shop: str = Field(..., description="Shop name (e.g., 'my-store' from 'my-store.myshopify.com')")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    credential_name: str = Field(..., description="Human-readable name for the credential")
    scopes: Optional[str] = Field(None, description="OAuth scopes that were requested (comma-separated)")
    custom_client_id: Optional[str] = Field(None, description="Optional custom OAuth app client ID")
    custom_client_secret: Optional[str] = Field(None, description="Optional custom OAuth app client secret")


class ShopifyOAuthRefreshRequest(ClientEventBase):
    """Refresh an expiring Shopify offline access token"""
    event_name: ClassVar[str] = "shopify:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class ShopifyOAuthValidateRequest(ClientEventBase):
    """Validate if a Shopify OAuth token is still valid"""
    event_name: ClassVar[str] = "shopify:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# PagerDuty OAuth Events
class PagerDutyOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "pagerduty:oauth:exchange"

    code: str = Field(..., description="Authorization code from PagerDuty OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")


class PagerDutyOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired PagerDuty OAuth token"""
    event_name: ClassVar[str] = "pagerduty:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class PagerDutyOAuthValidateRequest(ClientEventBase):
    """Validate if a PagerDuty OAuth token is still valid"""
    event_name: ClassVar[str] = "pagerduty:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Linear OAuth Events
class LinearOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "linear:oauth:exchange"

    code: str = Field(..., description="Authorization code from Linear OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")


class LinearOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Linear OAuth token (rarely needed, tokens last 10 years)"""
    event_name: ClassVar[str] = "linear:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class LinearOAuthValidateRequest(ClientEventBase):
    """Validate if a Linear OAuth token is still valid"""
    event_name: ClassVar[str] = "linear:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Threads OAuth Events
class ThreadsOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "threads:oauth:exchange"

    code: str = Field(..., description="Authorization code from Threads OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")


class ThreadsOAuthRefreshRequest(ClientEventBase):
    """Refresh a long-lived Threads OAuth token"""
    event_name: ClassVar[str] = "threads:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class ThreadsOAuthValidateRequest(ClientEventBase):
    """Validate if a Threads OAuth token is still valid"""
    event_name: ClassVar[str] = "threads:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Instagram Login OAuth Events (Instagram API with Instagram Login)
class InstagramLoginOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "instagram_login:oauth:exchange"

    code: str = Field(..., description="Authorization code from Instagram Login OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")


class InstagramLoginOAuthRefreshRequest(ClientEventBase):
    """Refresh a long-lived Instagram Login OAuth token"""
    event_name: ClassVar[str] = "instagram_login:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class InstagramLoginOAuthValidateRequest(ClientEventBase):
    """Validate if an Instagram Login OAuth token is still valid"""
    event_name: ClassVar[str] = "instagram_login:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Facebook Pages OAuth Events
class FacebookPagesOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth code for a Facebook (Pages) credential"""
    event_name: ClassVar[str] = "facebook_pages:oauth:exchange"

    code: str = Field(..., description="Authorization code from Facebook OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")


class FacebookPagesOAuthRefreshRequest(ClientEventBase):
    """Refresh a Facebook Pages OAuth token"""
    event_name: ClassVar[str] = "facebook_pages:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class FacebookPagesOAuthValidateRequest(ClientEventBase):
    """Validate a Facebook Pages OAuth token"""
    event_name: ClassVar[str] = "facebook_pages:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Meta OAuth Events
class MetaOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "meta:oauth:exchange"

    code: str = Field(..., description="Authorization code from Meta OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")


class MetaOAuthRefreshRequest(ClientEventBase):
    """Refresh a long-lived Meta OAuth token"""
    event_name: ClassVar[str] = "meta:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class MetaOAuthValidateRequest(ClientEventBase):
    """Validate if a Meta OAuth token is still valid"""
    event_name: ClassVar[str] = "meta:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Box OAuth Events
class BoxOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "box:oauth:exchange"

    code: str = Field(..., description="Authorization code from Box OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")


class BoxOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Box OAuth token (access tokens expire after ~60 minutes)"""
    event_name: ClassVar[str] = "box:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class BoxOAuthValidateRequest(ClientEventBase):
    """Validate if a Box OAuth token is still valid"""
    event_name: ClassVar[str] = "box:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Monday OAuth Events
class MondayOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "monday:oauth:exchange"

    code: str = Field(..., description="Authorization code from monday OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")


class MondayOAuthRefreshRequest(ClientEventBase):
    """Refresh a monday OAuth token (used when an app is configured with rotation)"""
    event_name: ClassVar[str] = "monday:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class MondayOAuthValidateRequest(ClientEventBase):
    """Validate if a monday OAuth token is still valid"""
    event_name: ClassVar[str] = "monday:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# LinkedIn OAuth Events
class LinkedInOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "linkedin:oauth:exchange"

    code: str = Field(..., description="Authorization code from LinkedIn OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization (must match)")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")


class LinkedInOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired LinkedIn OAuth token"""
    event_name: ClassVar[str] = "linkedin:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class LinkedInOAuthValidateRequest(ClientEventBase):
    """Validate if a LinkedIn OAuth token is still valid"""
    event_name: ClassVar[str] = "linkedin:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Atlassian OAuth Events (for Jira)
class AtlassianOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as Jira credential"""
    event_name: ClassVar[str] = "atlassian:oauth:exchange"

    code: str = Field(..., description="Authorization code from Atlassian OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    credential_name: str = Field(..., description="Human-readable name for the credential")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")
    jira_site: Optional[str] = Field(None, description="Requested Jira site URL or subdomain")



class AtlassianOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Atlassian/Jira OAuth token"""
    event_name: ClassVar[str] = "atlassian:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")



class AtlassianOAuthValidateRequest(ClientEventBase):
    """Validate if an Atlassian/Jira OAuth token is still valid"""
    event_name: ClassVar[str] = "atlassian:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")



# Discord OAuth Events
class DiscordOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "discord:oauth:exchange"

    code: str = Field(..., description="Authorization code from Discord OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    credential_name: str = Field(..., description="Human-readable name for the credential")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")


class DiscordOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Discord OAuth token"""
    event_name: ClassVar[str] = "discord:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class DiscordOAuthValidateRequest(ClientEventBase):
    """Validate if a Discord OAuth token is still valid"""
    event_name: ClassVar[str] = "discord:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Dropbox OAuth Events
class DropboxOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "dropbox:oauth:exchange"

    code: str = Field(..., description="Authorization code from Dropbox OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    credential_name: str = Field(..., description="Human-readable name for the credential")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")


class DropboxOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Dropbox OAuth token"""
    event_name: ClassVar[str] = "dropbox:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class DropboxOAuthValidateRequest(ClientEventBase):
    """Validate if a Dropbox OAuth token is still valid"""
    event_name: ClassVar[str] = "dropbox:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Facebook OAuth Events (for Instagram)
class FacebookOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential (Instagram via Facebook)"""
    event_name: ClassVar[str] = "facebook:oauth:exchange"

    code: str = Field(..., description="Authorization code from Facebook OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    credential_name: str = Field(..., description="Human-readable name for the credential")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")
    selected_instagram_user_id: Optional[str] = Field(
        None,
        description="When multiple accounts exist, the instagram_user_id the user selected"
    )
    pending_selection_key: Optional[str] = Field(
        None,
        description="Opaque key returned in a needs_selection response; reuse to complete selection"
    )


class FacebookOAuthRefreshRequest(ClientEventBase):
    """Refresh a Facebook/Instagram OAuth token (long-lived tokens last 60 days)"""
    event_name: ClassVar[str] = "facebook:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class FacebookOAuthValidateRequest(ClientEventBase):
    """Validate if a Facebook/Instagram OAuth token is still valid"""
    event_name: ClassVar[str] = "facebook:oauth:validate"
    credential_id: str = Field(..., description="UUID of the credential to validate")


# Linear OAuth Events
class LinearOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "linear:oauth:exchange"

    code: str = Field(..., description="Authorization code from Linear OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")


class LinearOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Linear OAuth token (rarely needed, tokens last 10 years)"""
    event_name: ClassVar[str] = "linear:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class LinearOAuthValidateRequest(ClientEventBase):
    """Validate if a Linear OAuth token is still valid"""
    event_name: ClassVar[str] = "linear:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Asana OAuth Events
class AsanaOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "asana:oauth:exchange"

    code: str = Field(..., description="Authorization code from Asana OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")


class AsanaOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Asana OAuth token (access tokens expire after 1 hour)"""
    event_name: ClassVar[str] = "asana:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class AsanaOAuthValidateRequest(ClientEventBase):
    """Validate if an Asana OAuth token is still valid"""
    event_name: ClassVar[str] = "asana:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Attio OAuth Events
class AttioOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "attio:oauth:exchange"

    code: str = Field(..., description="Authorization code from Attio OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")


class AttioOAuthRefreshRequest(ClientEventBase):
    """Refresh an Attio OAuth token (tokens are long-lived; rarely needed)"""
    event_name: ClassVar[str] = "attio:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class AttioOAuthValidateRequest(ClientEventBase):
    """Validate if an Attio OAuth token is still valid"""
    event_name: ClassVar[str] = "attio:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Intercom OAuth Events
class IntercomOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "intercom:oauth:exchange"

    code: str = Field(..., description="Authorization code from Intercom OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    region: str = Field("us", description="Data residency region for the workspace (us/eu/au)")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes the app was granted")


class IntercomOAuthRefreshRequest(ClientEventBase):
    """Refresh an Intercom OAuth token (no-op: Intercom tokens are long-lived)"""
    event_name: ClassVar[str] = "intercom:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class IntercomOAuthValidateRequest(ClientEventBase):
    """Validate if an Intercom OAuth credential is still valid"""
    event_name: ClassVar[str] = "intercom:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Webflow OAuth Events
class WebflowOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "webflow:oauth:exchange"

    code: str = Field(..., description="Authorization code from Webflow OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")


class WebflowOAuthRefreshRequest(ClientEventBase):
    """Refresh a Webflow OAuth token (Webflow tokens are non-expiring; no-op)"""
    event_name: ClassVar[str] = "webflow:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class WebflowOAuthValidateRequest(ClientEventBase):
    """Validate if a Webflow OAuth token is still valid"""
    event_name: ClassVar[str] = "webflow:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# QuickBooks OAuth Events
class QuickBooksOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "quickbooks:oauth:exchange"

    code: str = Field(..., description="Authorization code from QuickBooks OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    realm_id: str = Field(..., description="QuickBooks company (realm) ID returned at OAuth time")
    is_sandbox: bool = Field(default=False, description="Whether to use the QuickBooks sandbox host")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")
    client_id: Optional[str] = Field(None, description="Optional custom Intuit OAuth client ID")
    client_secret: Optional[str] = Field(None, description="Optional custom Intuit OAuth client secret")


class QuickBooksOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired QuickBooks OAuth token (access tokens expire after 1 hour)"""
    event_name: ClassVar[str] = "quickbooks:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class QuickBooksOAuthValidateRequest(ClientEventBase):
    """Validate if a QuickBooks OAuth token is still valid"""
    event_name: ClassVar[str] = "quickbooks:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Calendly OAuth Events
class CalendlyOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "calendly:oauth:exchange"

    code: str = Field(..., description="Authorization code from Calendly OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")


class CalendlyOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Calendly OAuth token (access tokens expire after ~2 hours)"""
    event_name: ClassVar[str] = "calendly:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class CalendlyOAuthValidateRequest(ClientEventBase):
    """Validate if a Calendly OAuth token is still valid"""
    event_name: ClassVar[str] = "calendly:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Sentry OAuth Events
class SentryOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "sentry:oauth:exchange"

    code: str = Field(..., description="Authorization code from Sentry OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")


class SentryOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Sentry OAuth token"""
    event_name: ClassVar[str] = "sentry:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class SentryOAuthValidateRequest(ClientEventBase):
    """Validate if a Sentry OAuth token is still valid"""
    event_name: ClassVar[str] = "sentry:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# PostHog OAuth Events
class PostHogOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code (+ PKCE verifier) for tokens and store as credential"""
    event_name: ClassVar[str] = "posthog:oauth:exchange"

    code: str = Field(..., description="Authorization code from PostHog OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    code_verifier: str = Field(..., description="PKCE code verifier generated at authorize time")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")


class PostHogOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired PostHog OAuth token (access tokens last ~10h; refresh rotates)"""
    event_name: ClassVar[str] = "posthog:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class PostHogOAuthValidateRequest(ClientEventBase):
    """Validate if a PostHog OAuth token is still valid"""
    event_name: ClassVar[str] = "posthog:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# LinkedIn OAuth Events
class LinkedInOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "linkedin:oauth:exchange"

    code: str = Field(..., description="Authorization code from LinkedIn OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization (must match)")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")


class LinkedInOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired LinkedIn OAuth token"""
    event_name: ClassVar[str] = "linkedin:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class LinkedInOAuthValidateRequest(ClientEventBase):
    """Validate if a LinkedIn OAuth token is still valid"""
    event_name: ClassVar[str] = "linkedin:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Cal.com OAuth Events
class CalComOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "calcom:oauth:exchange"

    code: str = Field(..., description="Authorization code from Cal.com OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")


class CalComOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Cal.com OAuth token (30-minute access tokens)"""
    event_name: ClassVar[str] = "calcom:oauth:refresh"
# Zoom OAuth Events
class ZoomOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "zoom:oauth:exchange"

    code: str = Field(..., description="Authorization code from Zoom OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization (must match)")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")


class ZoomOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Zoom OAuth token (access tokens expire after 1 hour)"""
    event_name: ClassVar[str] = "zoom:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


# Zendesk OAuth Events
class ZendeskOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "zendesk:oauth:exchange"

    code: str = Field(..., description="Authorization code from Zendesk OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    subdomain: str = Field(..., description="Zendesk subdomain that scopes the OAuth host")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")


class ZendeskOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Zendesk OAuth token"""
    event_name: ClassVar[str] = "zendesk:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


# BambooHR OAuth Events (subdomain-scoped, like Zendesk)
class BambooHROAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "bamboohr:oauth:exchange"

    code: str = Field(..., description="Authorization code from BambooHR OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    subdomain: str = Field(..., description="BambooHR company subdomain that scopes the OAuth host")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")


class BambooHROAuthRefreshRequest(ClientEventBase):
    """Refresh an expired BambooHR OAuth token"""
    event_name: ClassVar[str] = "bamboohr:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class BambooHROAuthValidateRequest(ClientEventBase):
    """Validate if a BambooHR OAuth token is still valid"""
    event_name: ClassVar[str] = "bamboohr:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Klaviyo OAuth Events (PKCE)
class KlaviyoOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential (uses PKCE)"""
    event_name: ClassVar[str] = "klaviyo:oauth:exchange"

    code: str = Field(..., description="Authorization code from Klaviyo OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    code_verifier: str = Field(..., description="PKCE code verifier used during authorization")
    credential_name: str = Field(..., description="Human-readable name for the credential")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")


class KlaviyoOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Klaviyo OAuth token"""
    event_name: ClassVar[str] = "klaviyo:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class KlaviyoOAuthValidateRequest(ClientEventBase):
    """Validate if a Klaviyo OAuth token is still valid"""
    event_name: ClassVar[str] = "klaviyo:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# ClickUp OAuth Events
class ClickUpOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "clickup:oauth:exchange"

    code: str = Field(..., description="Authorization code from ClickUp OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes (ClickUp has none)")


class ClickUpOAuthRefreshRequest(ClientEventBase):
    """Refresh a ClickUp OAuth token (ClickUp tokens do not expire; no-op parity)"""
    event_name: ClassVar[str] = "clickup:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class CalComOAuthValidateRequest(ClientEventBase):
    """Validate if a Cal.com OAuth token is still valid"""
    event_name: ClassVar[str] = "calcom:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


class ClickUpOAuthValidateRequest(ClientEventBase):
    """Validate if a ClickUp OAuth token is still valid"""
    event_name: ClassVar[str] = "clickup:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


class ZendeskOAuthValidateRequest(ClientEventBase):
    """Validate if a Zendesk OAuth token is still valid"""
    event_name: ClassVar[str] = "zendesk:oauth:validate"
class ZoomOAuthValidateRequest(ClientEventBase):
    """Validate if a Zoom OAuth token is still valid"""
    event_name: ClassVar[str] = "zoom:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Apollo OAuth Events
class ApolloOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "apollo:oauth:exchange"

    code: str = Field(..., description="Authorization code from Apollo OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization (must match)")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")


class ApolloOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Apollo OAuth token"""
    event_name: ClassVar[str] = "apollo:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class ApolloOAuthValidateRequest(ClientEventBase):
    """Validate if an Apollo OAuth token is still valid"""
    event_name: ClassVar[str] = "apollo:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Microsoft OAuth Events
class MicrosoftOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "microsoft:oauth:exchange"

    code: str = Field(..., description="Authorization code from Microsoft OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    credential_name: str = Field(..., description="Human-readable name for the credential")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")


class MicrosoftOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Microsoft OAuth token"""
    event_name: ClassVar[str] = "microsoft:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class MicrosoftOAuthValidateRequest(ClientEventBase):
    """Validate if a Microsoft OAuth token is still valid"""
    event_name: ClassVar[str] = "microsoft:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Notion OAuth Events
class NotionOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "notion:oauth:exchange"

    code: str = Field(..., description="Authorization code from Notion OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    credential_name: str = Field(..., description="Human-readable name for the credential")


class NotionOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Notion OAuth token"""
    event_name: ClassVar[str] = "notion:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class NotionOAuthValidateRequest(ClientEventBase):
    """Validate if a Notion OAuth token is still valid"""
    event_name: ClassVar[str] = "notion:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# GitLab OAuth Events
class GitLabOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "gitlab:oauth:exchange"

    code: str = Field(..., description="Authorization code from GitLab OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")


class GitLabOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired GitLab OAuth token (access tokens expire after 2 hours)"""
    event_name: ClassVar[str] = "gitlab:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class GitLabOAuthValidateRequest(ClientEventBase):
    """Validate if a GitLab OAuth token is still valid"""
    event_name: ClassVar[str] = "gitlab:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Reddit OAuth Events
class RedditOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "reddit:oauth:exchange"

    code: str = Field(..., description="Authorization code from Reddit OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    credential_name: str = Field(..., description="Human-readable name for the credential")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")


class RedditOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Reddit OAuth token"""
    event_name: ClassVar[str] = "reddit:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class RedditOAuthValidateRequest(ClientEventBase):
    """Validate if a Reddit OAuth token is still valid"""
    event_name: ClassVar[str] = "reddit:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Salesforce OAuth Events
class SalesforceOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "salesforce:oauth:exchange"

    code: str = Field(..., description="Authorization code from Salesforce OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    credential_name: str = Field(..., description="Human-readable name for the credential")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")
    is_sandbox: bool = Field(False, description="Whether this is a Salesforce sandbox org")
    code_verifier: Optional[str] = Field(None, description="PKCE code verifier for token exchange")


class SalesforceOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Salesforce OAuth token"""
    event_name: ClassVar[str] = "salesforce:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class SalesforceOAuthValidateRequest(ClientEventBase):
    """Validate if a Salesforce OAuth token is still valid"""
    event_name: ClassVar[str] = "salesforce:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Slack OAuth Events
class SlackOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "slack:oauth:exchange"

    code: str = Field(..., description="Authorization code from Slack OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    credential_name: str = Field("Slack", description="Human-readable name for the credential")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")
    client_id: Optional[str] = Field(None, description="Custom client ID (for user's own Slack app)")
    client_secret: Optional[str] = Field(None, description="Custom client secret (for user's own Slack app)")


class SlackOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Slack OAuth token"""
    event_name: ClassVar[str] = "slack:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")
    client_id: Optional[str] = Field(None, description="Custom client ID (if not stored in credential)")
    client_secret: Optional[str] = Field(None, description="Custom client secret (if not stored in credential)")


class SlackOAuthValidateRequest(ClientEventBase):
    """Validate if a Slack OAuth token is still valid"""
    event_name: ClassVar[str] = "slack:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Twitter OAuth Events
class TwitterOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "twitter:oauth:exchange"

    code: str = Field(..., description="Authorization code from Twitter OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    code_verifier: str = Field(..., description="PKCE code verifier for Twitter OAuth")
    credential_name: str = Field(..., description="Human-readable name for the credential")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")


class TwitterOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Twitter OAuth token"""
    event_name: ClassVar[str] = "twitter:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class TwitterOAuthValidateRequest(ClientEventBase):
    """Validate if a Twitter OAuth token is still valid"""
    event_name: ClassVar[str] = "twitter:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# WordPress OAuth Events
class WordPressOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "wordpress:oauth:exchange"

    code: str = Field(..., description="Authorization code from WordPress.com OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    credential_name: str = Field(..., description="Human-readable name for the credential")
    site_id: Optional[str] = Field(None, description="WordPress.com site ID or domain")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")


class WordPressOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired WordPress OAuth token"""
    event_name: ClassVar[str] = "wordpress:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class WordPressOAuthValidateRequest(ClientEventBase):
    """Validate if a WordPress OAuth token is still valid"""
    event_name: ClassVar[str] = "wordpress:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# TikTok OAuth Events
class TikTokOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "tiktok:oauth:exchange"

    code: str = Field(..., description="Authorization code from TikTok OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    credential_name: str = Field(..., description="Human-readable name for the credential")
    scopes: List[str] = Field(..., description="OAuth scopes that were requested")


class TikTokOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired TikTok OAuth token"""
    event_name: ClassVar[str] = "tiktok:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class TikTokOAuthValidateRequest(ClientEventBase):
    """Validate if a TikTok OAuth token is still valid"""
    event_name: ClassVar[str] = "tiktok:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Workflow Execution Events (definition moved to line 598 with workflow_id field)


# Saved Output Events - for managing reusable mock/test data
class SavedOutputCreateRequest(ClientEventBase):
    """Request to save output data for reuse"""
    event_name: ClassVar[str] = "saved_output:create"

    node_type: str = Field(..., description="Type of the node (e.g., 'automation-telegram', 'agent')")
    name: str = Field(..., description="User-provided readable name for this saved output")
    output: Dict[str, Any] = Field(..., description="The output data to save")
    visibility: str = Field("user", description="Visibility level: 'user', 'organization', or 'public'")


class SavedOutputListRequest(ClientEventBase):
    """Request to list saved outputs for a specific node type"""
    event_name: ClassVar[str] = "saved_output:list"

    node_type: str = Field(..., description="Type of the node to get saved outputs for")


class SavedOutputGetRequest(ClientEventBase):
    """Request to get a specific saved output by ID"""
    event_name: ClassVar[str] = "saved_output:get"

    saved_output_id: str = Field(..., description="UUID of the saved output to retrieve")


class SavedOutputUpdateRequest(ClientEventBase):
    """Request to update a saved output's name or visibility"""
    event_name: ClassVar[str] = "saved_output:update"

    saved_output_id: str = Field(..., description="UUID of the saved output to update")
    name: Optional[str] = Field(None, description="New name for the saved output")
    visibility: Optional[str] = Field(None, description="New visibility level")


class SavedOutputDeleteRequest(ClientEventBase):
    """Request to delete a saved output"""
    event_name: ClassVar[str] = "saved_output:delete"

    saved_output_id: str = Field(..., description="UUID of the saved output to delete")


# Resource Sharing Events - for sharing workflows, databases, credentials, and saved outputs
class ShareCreateRequest(ClientEventBase):
    """Request to share a resource with a user (by email), organization, or make public"""
    event_name: ClassVar[str] = "share:create"

    resource_type: Literal["workflow", "workflow_folder", "database", "credential", "saved_output", "skill"] = Field(..., description="Type of resource being shared")
    resource_id: str = Field(..., description="UUID of the resource to share")
    target_type: Literal["user", "organization", "public"] = Field(..., description="Share with a user, organization, or make publicly accessible")
    target_email: Optional[str] = Field(None, description="Email of user to share with (required if target_type='user')")
    target_org_id: Optional[str] = Field(None, description="Organization ID to share with (required if target_type='organization')")
    permission: Literal["view", "edit"] = Field("view", description="Permission level to grant (public shares are always 'view')")


class ShareListRequest(ClientEventBase):
    """Request to list all shares for a resource"""
    event_name: ClassVar[str] = "share:list"

    resource_type: Literal["workflow", "workflow_folder", "database", "credential", "saved_output", "skill"] = Field(..., description="Type of resource")
    resource_id: str = Field(..., description="UUID of the resource")


class ShareUpdateRequest(ClientEventBase):
    """Request to update a share's permission"""
    event_name: ClassVar[str] = "share:update"

    share_id: str = Field(..., description="UUID of the share to update")
    permission: Literal["view", "edit"] = Field(..., description="New permission level")


class ShareDeleteRequest(ClientEventBase):
    """Request to remove a share"""
    event_name: ClassVar[str] = "share:delete"

    share_id: str = Field(..., description="UUID of the share to delete")


class ShareLeaveRequest(ClientEventBase):
    """Request for the current user to drop their OWN access to a resource shared
    with them (self-service unshare). Unlike share:delete this needs no share_id
    and no manage-shares permission — you can always remove your own access."""
    event_name: ClassVar[str] = "share:leave"

    resource_type: Literal["workflow", "workflow_folder", "database", "credential", "saved_output", "skill"] = Field(..., description="Type of shared resource to leave")
    resource_id: str = Field(..., description="UUID of the resource to remove the caller's own share for")


class ShareListSharedWithMeRequest(ClientEventBase):
    """Request to list resources shared with the current user"""
    event_name: ClassVar[str] = "share:list_shared_with_me"

    resource_type: Optional[Literal["workflow", "workflow_folder", "database", "credential", "saved_output", "skill"]] = Field(None, description="Filter by resource type (optional)")


class ShareInviteLinkRequest(ClientEventBase):
    """Request to mint (or fetch the existing) shareable collaboration invite link for a workflow.

    Owner-only and personal-workflow-only. Returns a durable token; anyone who
    opens /i/<token> and authenticates is added as an 'edit' collaborator on the
    SAME workflow (not a fork)."""
    event_name: ClassVar[str] = "share:invite_link"

    workflow_id: str = Field(..., description="UUID of the workflow to create/fetch an invite link for")


class ShareInviteAcceptRequest(ClientEventBase):
    """Request to redeem a workflow invite link, granting the current user
    collaborator access to the linked workflow."""
    event_name: ClassVar[str] = "share:invite_accept"

    token: str = Field(..., description="Invite link token to redeem")


# Shared agent link events — public capability-URL chat pages (/a/{link_id}).
# Manage events are owner-only; visitor events run on restricted share-scope
# sessions and deliberately carry NO workflow/node/link ids (all resolved from
# the socket session so a visitor cannot re-point their session).
class AgentShareGetOrCreateRequest(ClientEventBase):
    """Mint (or fetch) the shareable public chat link for an agent node.
    Owner-only: the link bills the owner's credits and exposes the agent's
    tools (owner credentials) to anyone with the URL."""
    event_name: ClassVar[str] = "agent_share:get_or_create"

    workflow_id: str = Field(..., description="UUID of the workflow containing the agent node")
    node_id: str = Field(..., description="Node id of the agent within the workflow")


class AgentShareRotateRequest(ClientEventBase):
    """Replace the capability URL for an agent node's share link. The old
    link 404s immediately. Owner-only."""
    event_name: ClassVar[str] = "agent_share:rotate"

    workflow_id: str = Field(..., description="UUID of the workflow containing the agent node")
    node_id: str = Field(..., description="Node id of the agent within the workflow")


class AgentShareSetActiveRequest(ClientEventBase):
    """Enable/disable an agent share link without changing the URL. Owner-only."""
    event_name: ClassVar[str] = "agent_share:set_active"

    workflow_id: str = Field(..., description="UUID of the workflow containing the agent node")
    node_id: str = Field(..., description="Node id of the agent within the workflow")
    is_active: bool = Field(..., description="Whether the link should accept visitors")


class RunShareCreateRequest(ClientEventBase):
    """Mint a public read-only link (/r/{id}) for a finished Test Run. The
    snapshot is the render bundle the sharer watched — a static page, nothing
    executes and nothing bills. Owner-only, matching the other public share
    capabilities."""
    event_name: ClassVar[str] = "run_share:create"

    workflow_id: str = Field(..., description="UUID of the workflow the run belongs to")
    title: str = Field("", description="Display title (the situation's name)", max_length=200)
    snapshot: Dict[str, Any] = Field(..., description="Finished-run render bundle (display fields only)")


class AgentWorkspaceListRequest(ClientEventBase):
    """List the files on an agent conversation's persistent workspace volume
    (the chat's file view). Requires workflow access — the same audience the
    agent chat itself serves. Response carries per-file signed streaming URLs."""
    event_name: ClassVar[str] = "agent_workspace:list"

    workflow_id: str = Field(..., description="UUID of the workflow containing the agent node")
    node_id: str = Field(..., description="Node id of the agent within the workflow")
    conversation_key: Optional[str] = Field(
        None, description="Conversation key whose workspace volume to list"
    )


class AgentWorkspaceDeleteRequest(ClientEventBase):
    """Delete one file from an agent conversation's workspace volume.
    Requires edit or owner access to the workflow."""
    event_name: ClassVar[str] = "agent_workspace:delete"

    workflow_id: str = Field(..., description="UUID of the workflow containing the agent node")
    node_id: str = Field(..., description="Node id of the agent within the workflow")
    conversation_key: Optional[str] = Field(
        None, description="Conversation key whose workspace volume to delete from"
    )
    path: str = Field(..., description="Volume-relative path of the file to delete")


class AgentBuilderDecisionRequest(ClientEventBase):
    """The user's approve/dismiss verdict on an agent's prompt_builder proposal
    card. Persisted as a conversation event so (a) the card's decided state
    restores across devices/reloads and (b) the agent is told the outcome on
    its next turn — without this the agent had no way to know the builder ran
    and answered from its stale 'awaiting approval' tool result (2026-07-19)."""
    event_name: ClassVar[str] = "agent:builder_decision"

    workflow_id: str = Field(..., description="UUID of the workflow containing the agent node")
    node_id: Optional[str] = Field(None, description="Node id of the agent that proposed the edit")
    conversation_id: str = Field(..., description="Conversation the proposal card lives in")
    proposal_id: str = Field(..., description="Server-minted id of the proposal being decided")
    decision: str = Field(..., description="'approved' or 'dismissed'")


class SharedAgentSendRequest(ClientEventBase):
    """Visitor chat message on a shared agent link (restricted session only).
    The response ack carries the conversation_id; the turn itself streams via
    chat:message / agent:state to the visitor's sid."""
    event_name: ClassVar[str] = "shared_agent:send"

    text: str = Field(..., min_length=1, max_length=8000, description="The visitor's chat message")
    chat_key: str = Field("main", pattern=r"^[a-zA-Z0-9_-]{1,32}$", description="Per-browser thread key; a fresh key starts a new conversation")


class SharedAgentResumeRequest(ClientEventBase):
    """Load the visitor's own conversation history on a shared agent link
    (restricted session only). The conversation is derived server-side from
    the session's share scope + chat_key — no other thread is reachable."""
    event_name: ClassVar[str] = "shared_agent:resume"

    chat_key: str = Field("main", pattern=r"^[a-zA-Z0-9_-]{1,32}$", description="Per-browser thread key")


class ResourceForkRequest(ClientEventBase):
    """
    Request to fork a resource (workflow or database) to a new location.
    Creates an independent copy that the user owns or has edit access to.
    """
    event_name: ClassVar[str] = "resource:fork"

    resource_type: Literal["workflow", "database"] = Field(..., description="Type of resource to fork")
    resource_id: str = Field(..., description="UUID of the resource to fork")
    destination_type: Literal["personal", "organization"] = Field(..., description="Where to create the fork")
    destination_org_id: Optional[str] = Field(None, description="Target organization ID (required if destination_type is 'organization')")
    new_name: Optional[str] = Field(None, description="Optional new name for the forked resource (defaults to 'Copy of {original}')")
    include_data: bool = Field(False, description="For databases: whether to copy the actual data rows (not just schema)")


# Workflow Template Events - for publishing workflows to the SEO-friendly template library
# MCP Workflow Events - for AI agents to build and control workflows
class WorkflowMCPResponseRequest(ClientEventBase):
    """
    Frontend response to backend MCP request.

    Sent by the frontend when responding to a 'workflow:mcp:request' event.
    Contains the requested data or mutation result with the same request_id
    for correlation.
    """
    event_name: ClassVar[str] = "workflow:mcp:response"
    expects_response: ClassVar[bool] = False  # This is itself a response

    request_id: str = Field(..., description="Correlation ID from the original request")
    data: Any = Field(None, description="Response data (workflow state, node info, mutation result)")
    error: Optional[str] = Field(None, description="Error message if request failed")


class WorkflowMCPSearchNodesRequest(ClientEventBase):
    """
    MCP tool request to search available workflow node types.

    Returns summaries of available nodes including type, label, description,
    available config types, and required credentials. Use get_node_config_schema
    to get the full JSON schema for a specific config type.
    """
    event_name: ClassVar[str] = "workflow:mcp:search_nodes"

    query: Optional[str] = Field(None, description="Search query to filter nodes (e.g., 'telegram', 'google')")


class WorkflowMCPGetNodeConfigSchemaRequest(ClientEventBase):
    """
    MCP tool request to get the full JSON schema for a specific node config type.

    Since workflow nodes can have multiple config types (union types), this
    returns the schema for a specific config variant.
    """
    event_name: ClassVar[str] = "workflow:mcp:get_node_config_schema"

    node_type: str = Field(..., description="Node type identifier (e.g., 'automation-telegram')")
    config_type: str = Field(..., description="Config type variant (e.g., 'send_message', 'receive_message')")


class WorkflowMCPGetSelectedNodeRequest(ClientEventBase):
    """MCP tool request to get the currently selected node in the workflow canvas"""
    event_name: ClassVar[str] = "workflow:mcp:get_selected_node"


class WorkflowMCPGetOpenWorkflowRequest(ClientEventBase):
    """
    MCP tool request to get the currently open workflow in the editor.

    Returns the workflow_id, nodes, edges, and running state of the currently
    open workflow. Returns null if no workflow is open.

    If include_configs is True, returns full node configs (useful for debugging/inspection).
    """
    event_name: ClassVar[str] = "workflow:mcp:get_open_workflow"

    include_configs: bool = Field(False, description="If true, include full node configurations in the response")


class WorkflowMCPGetNodeOutputRequest(ClientEventBase):
    """
    MCP tool request to get the execution output of a workflow node.

    This is a backend-only operation that reads from the database.
    Returns the node's output data or mockedOutput if set.
    """
    event_name: ClassVar[str] = "workflow:mcp:get_node_output"

    workflow_id: str = Field(..., description="UUID of the workflow")
    node_id: Optional[str] = Field(None, description="ID of the node to get output from. If not provided, uses the currently selected node.")


class WorkflowMCPGetNodeInputRequest(ClientEventBase):
    """
    MCP tool request to get the input data flowing into a workflow node.

    This is a backend-only operation that reads from the database.
    Returns outputs from all connected upstream nodes.
    """
    event_name: ClassVar[str] = "workflow:mcp:get_node_input"

    workflow_id: str = Field(..., description="UUID of the workflow")
    node_id: Optional[str] = Field(None, description="ID of the node to get input for. If not provided, uses the currently selected node.")


class WorkflowMCPRunWorkflowRequest(ClientEventBase):
    """
    MCP tool request to execute a workflow (backend-only, database-backed).

    Loads the workflow from the database and executes it without requiring
    a frontend connection. Returns immediately with execution_id.
    Use get_node_output() to wait for specific node results.
    """
    event_name: ClassVar[str] = "workflow:mcp:run_workflow"

    workflow_id: str = Field(..., description="UUID of the workflow to execute")


class WorkflowMCPCreateWorkflowRequest(ClientEventBase):
    """
    MCP tool request to create a new workflow and open it in the editor.

    If no workflow is currently open, this creates one and navigates to it.
    """
    event_name: ClassVar[str] = "workflow:mcp:create_workflow"

    name: str = Field(..., description="Name for the new workflow")
    description: str = Field(default="", description="Description of what the workflow does")
    folder_id: Optional[str] = Field(default=None, description="Folder UUID to create the workflow in (null for root)")


class WorkflowMCPOpenWorkflowRequest(ClientEventBase):
    """
    MCP tool request to open an existing workflow in the editor.

    Navigates the frontend to display the specified workflow.
    """
    event_name: ClassVar[str] = "workflow:mcp:open_workflow"

    workflow_id: str = Field(..., description="UUID of the workflow to open")


class WorkflowMCPListWorkflowsRequest(ClientEventBase):
    """
    MCP tool request to list available workflows.

    Returns workflows owned by the user, optionally filtered by search query.
    Optionally filter by folder_id to list workflows in a specific folder.
    """
    event_name: ClassVar[str] = "workflow:mcp:list_workflows"

    query: Optional[str] = Field(default=None, description="Optional search query to filter workflows by name or description")
    folder_id: Optional[str] = Field(default=None, description="Folder UUID to filter by. If provided, only returns workflows in that folder. Use empty string '' for root-level (unfiled) workflows only.")
    limit: int = Field(default=20, description="Maximum number of workflows to return")


class WorkflowMCPDeleteWorkflowRequest(ClientEventBase):
    """
    MCP tool request to delete a workflow.

    Permanently deletes the workflow and all its nodes/edges from the database.
    """
    event_name: ClassVar[str] = "workflow:mcp:delete_workflow"

    workflow_id: str = Field(..., description="UUID of the workflow to delete")


class WorkflowMCPUpdateWorkflowMetadataRequest(ClientEventBase):
    """
    MCP tool request to update a workflow's metadata (name and description).

    Only updates the specified fields; omitted fields remain unchanged.
    """
    event_name: ClassVar[str] = "workflow:mcp:update_workflow_metadata"

    workflow_id: str = Field(..., description="UUID of the workflow to update")
    name: Optional[str] = Field(default=None, description="New name for the workflow")
    description: Optional[str] = Field(default=None, description="New description for the workflow")


class WorkflowMCPListSavedOutputsRequest(ClientEventBase):
    """
    MCP tool request to list saved mock outputs for a node type.

    Returns saved outputs that can be used to mock node execution.
    """
    event_name: ClassVar[str] = "workflow:mcp:list_saved_outputs"

    node_type: str = Field(..., description="Node type to list saved outputs for (e.g., 'automation-telegram')")


class WorkflowMCPRunNodeRequest(ClientEventBase):
    """
    MCP tool request to execute a single node (backend-only, database-backed).

    Loads the workflow from the database and executes only the target node.
    Predecessor nodes must have output data available (from prior execution
    or mocked data) - they will be used as inputs to the target node.
    """
    event_name: ClassVar[str] = "workflow:mcp:run_node"

    workflow_id: str = Field(..., description="UUID of the workflow containing the node")
    node_id: Optional[str] = Field(None, description="ID of the node to execute. If not provided, uses the currently selected node.")


class WorkflowMCPGetExecutionStatusRequest(ClientEventBase):
    """
    MCP tool request to get the status of a workflow execution.

    Use this after run_workflow to check if execution completed successfully,
    failed with an error, or is still running.
    """
    event_name: ClassVar[str] = "workflow:mcp:get_execution_status"

    execution_id: Optional[str] = Field(None, description="UUID of the execution to check. If not provided, returns the latest execution for workflow_id.")
    workflow_id: Optional[str] = Field(None, description="UUID of the workflow. Required if execution_id is not provided.")


class WorkflowMCPListCredentialsRequest(ClientEventBase):
    """
    MCP tool request to list available credentials.

    Returns credentials the user has saved, optionally filtered by type.
    Useful for checking if required OAuth connections exist before configuring nodes.
    """
    event_name: ClassVar[str] = "workflow:mcp:list_credentials"

    credential_type: Optional[str] = Field(
        None,
        description="Filter by credential type (e.g., 'google_sheets_oauth', 'gmail_oauth'). If not provided, returns all credentials."
    )


class WorkflowMCPLoadFieldOptionsRequest(ClientEventBase):
    """
    MCP tool request to load dynamic options for a node configuration field.

    Use this to load options for fields like spreadsheet_id, sheet_name, etc.
    that are populated dynamically based on user's connected accounts.
    """
    event_name: ClassVar[str] = "workflow:mcp:load_field_options"

    node_type: str = Field(..., description="The node type (e.g., 'automation-google-sheets')")
    field_name: str = Field(..., description="The field to load options for (e.g., 'spreadsheet_id')")
    search_query: Optional[str] = Field(
        None,
        description="Optional search query to filter options by name/label"
    )
    depends_on: Optional[Dict[str, Any]] = Field(
        None,
        description="Values of fields this field depends on (e.g., {'spreadsheet_id': '...'} when loading sheet_name options)"
    )
    credential_id: Optional[str] = Field(
        None,
        description="Credential ID to use. If not provided, uses the first matching credential for the node type."
    )
    limit: int = Field(20, description="Maximum number of options to return")
    offset: int = Field(0, description="Offset for pagination")


class WorkflowMCPGetNodeConfigRequest(ClientEventBase):
    """
    MCP tool request to get a specific node's configuration by ID.

    This is a backend-only operation that reads from the database.
    Returns the full node data including config, position, and type.
    """
    event_name: ClassVar[str] = "workflow:mcp:get_node_config"

    workflow_id: str = Field(..., description="UUID of the workflow")
    node_id: str = Field(..., description="ID of the node to get config for")


class WorkflowMCPUpdateInterfaceRequest(ClientEventBase):
    """
    MCP tool request to update the interface layout of a workflow.

    Uses XML commands to position, resize, and arrange interface blocks on a 12-column grid.
    """
    event_name: ClassVar[str] = "workflow:mcp:update_interface"

    workflow_id: str = Field(..., description="UUID of the workflow")
    updates_xml: str = Field(..., description="XML commands for interface layout (set_block_layout, remove_block, auto_layout)")


# Workflow Checkpoint Events - for saving and restoring workflow versions
class WorkflowCheckpointCreateRequest(ClientEventBase):
    """Request to create a checkpoint/snapshot of the current workflow state"""
    event_name: ClassVar[str] = "workflow:checkpoint:create"

    workflow_id: str = Field(..., description="UUID of the workflow to checkpoint")
    name: str = Field(..., description="Human-readable name for this checkpoint")
    description: Optional[str] = Field("", description="Optional description of what changed")


class WorkflowCheckpointListRequest(ClientEventBase):
    """Request to list all checkpoints for a workflow"""
    event_name: ClassVar[str] = "workflow:checkpoint:list"

    workflow_id: str = Field(..., description="UUID of the workflow to get checkpoints for")


class WorkflowCheckpointRestoreRequest(ClientEventBase):
    """Request to restore a workflow to a specific checkpoint"""
    event_name: ClassVar[str] = "workflow:checkpoint:restore"

    workflow_id: str = Field(..., description="UUID of the workflow")
    checkpoint_id: str = Field(..., description="UUID of the checkpoint to restore")


class WorkflowCheckpointDeleteRequest(ClientEventBase):
    """Request to delete a checkpoint"""
    event_name: ClassVar[str] = "workflow:checkpoint:delete"

    checkpoint_id: str = Field(..., description="UUID of the checkpoint to delete")


# Workflow Builder Events - AI-powered workflow editing
class WorkflowBuilderEditRequest(ClientEventBase):
    """
    Request to edit (or build from scratch) a workflow with natural language
    instructions. Takes the current graph state and an edit prompt and runs
    the agentic builder's multi-turn brain loop against it.
    """
    event_name: ClassVar[str] = "workflow:builder:edit"

    current_graph: Dict[str, Any] = Field(..., description="Current graph state with nodes and edges")
    edit_prompt: str = Field(..., description="Natural language description of the edit to make")
    target_node_ids: Optional[List[str]] = Field(None, description="Specific node IDs to modify. If empty, LLM decides based on edit_prompt.")
    selected_node_id: Optional[str] = Field(None, description="Currently selected node ID for referential edits like 'remove this node'")
    generation_id: Optional[str] = Field(None, description="Optional generation ID for tracking.")
    model: Optional[str] = Field(None, description="LLM model for the builder brain. Falls back to the server-side builder default when unset.")
    conversation_id: Optional[str] = Field(None, description="Conversation ID for chat history persistence.")
    silent: bool = Field(False, description="When true, suppress conversational text and output only XML commands. Used by WorkflowCreator which has no chat UI.")
    user_context: Optional[Dict[str, Any]] = Field(None, description="Optional context about what the user is looking at (inner_tab, selected_node_id, has_workflow).")
    viewport_width: Optional[float] = Field(None, description="Visible canvas width in logical coords, used to shape the initial grid layout of unconnected nodes.")
    viewport_height: Optional[float] = Field(None, description="Visible canvas height in logical coords, used to shape the initial grid layout of unconnected nodes.")
    n8n_workflow: Optional[Dict[str, Any]] = Field(None, description="Raw n8n workflow JSON (as parsed from the user's paste). When present, the brain switches into n8n import mode and emits <add_node n8n_refs=\"...\"/> linking each NoClick node to its source n8n node(s).")
    edit_scope: Optional[Literal["node"]] = Field(None, description="When 'node', restrict the edit to selected_node_id only — the brain may only update_config/patch_config/set_credentials/disable/enable/mock/unmock that single node, and must not add or remove nodes/edges. Used by the FlowHelper Edit tab. Default (None) is unrestricted workflow edit.")


class ShareBuilderAskRequest(ClientEventBase):
    """Mint (or reuse) a public input-bridge link for the caller's builder run
    currently paused on an <ask/> — the drawer's share button. Anyone holding
    the returned /b/{id} URL can answer the questions / connect credentials
    without a NoClick account; submitting resumes the run as the caller."""
    event_name: ClassVar[str] = "workflow:builder:share_ask"

    conversation_id: str = Field(..., description="Builder conversation paused on the ask")
    ask_id: str = Field(..., description="The pending ask being shared")


class ListPendingBuilderRunsRequest(ClientEventBase):
    """
    List builder runs currently paused on an <ask/> for the current user.
    Used by the pending-runs indicator so a user can find and resume runs
    that paused days earlier (e.g., while they went to fetch API keys).
    """
    event_name: ClassVar[str] = "workflow:builder:list_pending"
    expects_response: ClassVar[bool] = True

    workflow_id: Optional[str] = Field(None, description="Scope results to this workflow. If omitted, returns all pending runs for the user.")


class WorkflowAutofillRequest(ClientEventBase):
    """
    AI-autofill a single node's operation and/or config fields.

    Triggered from the FlowHelperView config panel. Modes:
      - 'full':         node drafter (operation) + node drafter (all fields)
      - 'operation':    node drafter only — pick the best operation for the node's goal
      - 'fields':       node drafter only — fill all fields under the current operation
      - 'single_field': node drafter only, restricted to ``target_field``
    """
    event_name: ClassVar[str] = "workflow:builder:autofill"

    current_graph: Dict[str, Any] = Field(..., description="Current graph state with nodes and edges")
    node_id: str = Field(..., description="Node to autofill")
    mode: str = Field("full", description="Autofill mode: 'full' | 'operation' | 'fields' | 'single_field'")
    target_field: Optional[str] = Field(None, description="Field name to fill (required when mode='single_field')")
    user_prompt: Optional[str] = Field(None, description="Optional extra context — falls back to the node's goal/label")
    generation_id: Optional[str] = Field(None, description="Optional generation ID for streaming correlation")


class NodeOutputSchemaRequest(ClientEventBase):
    """
    Request to fetch the expected output schema for a node type and operation.

    Used by the workflow builder UI to show users what fields will be available
    from a node before they run it, enabling drag-and-drop configuration.
    """
    event_name: ClassVar[str] = "workflow:node:schema"

    node_type: str = Field(..., description="Node type, e.g., 'automation-google-sheets'")
    node_operation: str = Field(..., description="Operation within the node, e.g., 'get_rows', 'send_message'")


# Workflow Folder Events
class FolderCreateRequest(ClientEventBase):
    """Request to create a new workflow folder"""
    event_name: ClassVar[str] = "workflow_folder:create"

    name: str = Field(..., description="Folder name")
    description: Optional[str] = Field("", description="Folder description")
    parent_folder_id: Optional[str] = Field(None, description="Parent folder UUID (null for root)")


class FolderListRequest(ClientEventBase):
    """Request to list folders"""
    event_name: ClassVar[str] = "workflow_folder:list"

    parent_folder_id: Optional[str] = Field(None, description="Parent folder UUID to filter by (null for root)")
    include_workflows: bool = Field(True, description="Include workflow count in response")


class FolderGetRequest(ClientEventBase):
    """Request to get a specific folder"""
    event_name: ClassVar[str] = "workflow_folder:get"

    folder_id: str = Field(..., description="Folder UUID")


class FolderUpdateRequest(ClientEventBase):
    """Request to update a folder (rename or move)"""
    event_name: ClassVar[str] = "workflow_folder:update"

    folder_id: str = Field(..., description="Folder UUID")
    name: Optional[str] = Field(None, description="New folder name")
    description: Optional[str] = Field(None, description="New folder description")
    parent_folder_id: Optional[str] = Field(None, description="New parent folder UUID (to move folder)")


class FolderDeleteRequest(ClientEventBase):
    """Request to delete a folder"""
    event_name: ClassVar[str] = "workflow_folder:delete"

    folder_id: str = Field(..., description="Folder UUID")


class FolderGetTreeRequest(ClientEventBase):
    """Request to get complete folder tree for sidebar"""
    event_name: ClassVar[str] = "workflow_folder:get_tree"

    scope_org_id: Optional[str] = Field(
        None,
        description="Explicit org scope: '' = personal, '<uuid>' = that org, "
                    "null = use the active (is_primary) context. The browser sends "
                    "its own scope so the response can't be mismatched by the "
                    "org-switch race."
    )


class FolderGetPathRequest(ClientEventBase):
    """Request to get breadcrumb path for a folder"""
    event_name: ClassVar[str] = "workflow_folder:get_path"

    folder_id: str = Field(..., description="Folder UUID")


class WorkflowMoveToFolderRequest(ClientEventBase):
    """Request to move a workflow to a folder"""
    event_name: ClassVar[str] = "workflow_folder:move_workflow"

    workflow_id: str = Field(..., description="Workflow UUID")
    folder_id: Optional[str] = Field(None, description="Target folder UUID (null for root)")


# MCP Folder Events - exposed via MCP adapter for external tool access
class MCPFolderGetTreeRequest(ClientEventBase):
    """
    MCP tool request to get the complete folder tree.

    Returns all folders the user has access to in a hierarchical tree structure
    with workflow counts per folder.
    """
    event_name: ClassVar[str] = "workflow:mcp:get_folder_tree"




# MCP OAuth Events - for connecting to external MCP servers with OAuth
class MCPOAuthDiscoverRequest(ClientEventBase):
    """Discover OAuth requirements for an MCP server URL"""
    event_name: ClassVar[str] = "mcp:oauth:discover"

    server_url: str = Field(..., description="URL of the MCP server endpoint")


class MCPOAuthExchangeRequest(ClientEventBase):
    """Exchange authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "mcp:oauth:exchange"

    code: str = Field(..., description="Authorization code from OAuth callback")
    code_verifier: str = Field(..., description="PKCE code verifier")
    token_endpoint: str = Field(..., description="Token endpoint URL")
    client_id: str = Field(..., description="OAuth client ID")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization")
    resource_url: Optional[str] = Field(None, description="MCP server URL for resource indicator")
    server_url: str = Field(..., description="MCP server URL for credential naming")
    provider_name: Optional[str] = Field(None, description="Provider name for credential")
    credential_name: Optional[str] = Field(None, description="Custom credential name")


class MCPOAuthRegisterClientRequest(ClientEventBase):
    """Register a dynamic OAuth client with an MCP server"""
    event_name: ClassVar[str] = "mcp:oauth:register-client"

    registration_endpoint: str = Field(..., description="Client registration endpoint URL")
    client_name: str = Field(default="NoClick MCP Client", description="Name for the OAuth client")
    redirect_uris: List[str] = Field(..., description="Redirect URIs for the client")


# ============================================================================
# Workflow Resource Events
# ============================================================================

class ResourceCreateRequest(ClientEventBase):
    """Create a new workflow resource (dataset, file, image, etc.)"""
    event_name: ClassVar[str] = "resource:create"

    workflow_id: str = Field(..., description="UUID of the parent workflow")
    resource_type: str = Field(..., description="Type: dataset, file, image, video, audio, document")
    name: str = Field(..., description="Display name for the resource")
    node_id: Optional[str] = Field(None, description="Workflow node that produced this resource")
    mime_type: Optional[str] = Field(None, description="MIME type for blob resources")
    size_bytes: Optional[int] = Field(None, description="File size in bytes")
    storage_ref: Optional[str] = Field(None, description="R2 storage key (if already uploaded)")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Arbitrary metadata")


class ResourceListRequest(ClientEventBase):
    """List workflow resources with optional filters"""
    event_name: ClassVar[str] = "resource:list"

    workflow_id: Optional[str] = Field(None, description="Filter by workflow UUID")
    resource_type: Optional[str] = Field(None, description="Filter by resource type")
    limit: int = Field(50, description="Max results to return")
    offset: int = Field(0, description="Pagination offset")


class ResourceGetRequest(ClientEventBase):
    """Get a single workflow resource by ID"""
    event_name: ClassVar[str] = "resource:get"

    resource_id: str = Field(..., description="UUID of the resource")


class ResourceDeleteRequest(ClientEventBase):
    """Delete a workflow resource"""
    event_name: ClassVar[str] = "resource:delete"

    resource_id: str = Field(..., description="UUID of the resource to delete")


class ResourceUploadUrlRequest(ClientEventBase):
    """Get a presigned upload URL for a blob resource"""
    event_name: ClassVar[str] = "resource:upload_url"

    resource_id: str = Field(..., description="UUID of the resource")
    filename: str = Field(..., description="Original filename")
    content_type: str = Field("application/octet-stream", description="MIME type of the file")


class ResourceDownloadUrlRequest(ClientEventBase):
    """Get a presigned download URL for a blob resource"""
    event_name: ClassVar[str] = "resource:download_url"

    resource_id: str = Field(..., description="UUID of the resource")


class ResourceDatasetRowsRequest(ClientEventBase):
    """Get paginated rows from a dataset resource"""
    event_name: ClassVar[str] = "resource:dataset:rows"

    resource_id: str = Field(..., description="UUID of the dataset resource")
    limit: int = Field(100, description="Max rows to return")
    offset: int = Field(0, description="Pagination offset")


class ResourceDatasetAppendRequest(ClientEventBase):
    """Append rows to a dataset resource"""
    event_name: ClassVar[str] = "resource:dataset:append"

    resource_id: str = Field(..., description="UUID of the dataset resource")
    rows: List[Dict[str, Any]] = Field(..., description="List of row data dicts to append")


class ResourceDatasetUpdateRowRequest(ClientEventBase):
    """Update a single row in a dataset resource"""
    event_name: ClassVar[str] = "resource:dataset:update_row"

    resource_id: str = Field(..., description="UUID of the dataset resource")
    row_id: str = Field(..., description="UUID of the row to update")
    data: Dict[str, Any] = Field(..., description="New data for the row")


class ResourceDatasetDeleteRowsRequest(ClientEventBase):
    """Delete rows from a dataset resource"""
    event_name: ClassVar[str] = "resource:dataset:delete_rows"

    resource_id: str = Field(..., description="UUID of the dataset resource")
    row_ids: List[str] = Field(..., description="List of row UUIDs to delete")


class WorkflowGetNodeOutputsRequest(ClientEventBase):
    """Fetch node outputs from the dedicated outputs table (server-backed, not IndexedDB)."""
    event_name: ClassVar[str] = "workflow:get_node_outputs"

    workflow_id: str = Field(..., description="UUID of the workflow")
    execution_id: Optional[str] = Field(None, description="Specific execution ID. If None, returns latest.")
    node_ids: Optional[List[str]] = Field(None, description="Specific node IDs. If None, returns all.")


class WorkflowGetNodeOutputHistoryRequest(ClientEventBase):
    """Fetch historical outputs for a specific node across executions."""
    event_name: ClassVar[str] = "workflow:get_node_output_history"

    workflow_id: str = Field(..., description="UUID of the workflow")
    node_id: str = Field(..., description="Node ID to fetch history for")
    limit: int = Field(20, description="Max number of historical outputs to return")


# Codex Device Code Auth Events
class CodexDeviceCodeStartRequest(ClientEventBase):
    """Initiate the Codex device code OAuth flow to connect a ChatGPT account"""
    event_name: ClassVar[str] = "codex:auth:start"


class CodexDeviceCodePollRequest(ClientEventBase):
    """Poll the device code token endpoint to check if the user has approved"""
    event_name: ClassVar[str] = "codex:auth:poll"

    device_auth_id: str = Field(..., description="Device auth session ID from start response")
    user_code: str = Field(..., description="User code from start response")
    credential_name: Optional[str] = Field(None, description="Name for the credential if approved")










# Claude Code OAuth PKCE Auth Events
class ClaudeCodeAuthStartRequest(ClientEventBase):
    """Initiate the Claude Code OAuth PKCE flow"""
    event_name: ClassVar[str] = "claude-code:auth:start"

class ClaudeCodeAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens"""
    event_name: ClassVar[str] = "claude-code:auth:exchange"
    auth_session_id: str = Field(..., description="Session ID from start response")
    authorization_code: str = Field(..., description="Authorization code pasted by user")
    credential_name: Optional[str] = Field(None, description="Optional name for the credential")


# WhatsApp QR Code Auth Events
class WhatsAppQRStartRequest(ClientEventBase):
    """Initiate the WhatsApp QR code flow — creates a connection and returns QR code"""
    event_name: ClassVar[str] = "whatsapp:qr:start"

    reconnect_credential_id: Optional[str] = Field(
        None,
        description=(
            "Re-scan into this existing whatsapp_qr credential's connection "
            "instead of minting a new credential (dead-session recovery)"
        ),
    )


class WhatsAppQRStatusRequest(ClientEventBase):
    """Check WhatsApp QR scan status — polls connection and saves credential when connected"""
    event_name: ClassVar[str] = "whatsapp:qr:status"

    connection_id: str = Field(..., description="WAHooks connection ID from start response")
    credential_name: Optional[str] = Field(None, description="Name for the credential if connected")


# Approval Feed Events
class ApprovalListRequest(ClientEventBase):
    """List pending approval requests for the current user / org"""
    event_name: ClassVar[str] = "approval:list"


class ApprovalRespondRequest(ClientEventBase):
    """Approve or reject an approval request, resuming workflow execution"""
    event_name: ClassVar[str] = "approval:respond"

    approval_id: str = Field(..., description="UUID of the approval request")
    decision: str = Field(..., description="Decision: 'approved' or 'rejected'")
    values: Optional[Dict[str, Any]] = Field(None, description="Edited form field values (optional, overrides original values)")


# Activity Log Events
class ActivityListRequest(ClientEventBase):
    """List recent activity log entries for the current user / org"""
    event_name: ClassVar[str] = "activity:list"

    limit: int = Field(50, description="Maximum number of entries to return")


class ToolCallListRequest(ClientEventBase):
    """List recent agent tool-call events for the current user / org"""
    event_name: ClassVar[str] = "tool_calls:list"

    limit: int = Field(100, description="Maximum number of tool calls to return")


# ============================================================================
# Skill Events — agent-context skills (description + optional text + optional workflow)
# ============================================================================

class SkillListRequest(ClientEventBase):
    """List skills accessible to the caller (owned, org, shared, plus system for internal users)."""
    event_name: ClassVar[str] = "skill:list"


class SkillGetRequest(ClientEventBase):
    """Get a single skill including bodies. System skills 404 for non-internal users."""
    event_name: ClassVar[str] = "skill:get"

    skill_id: str = Field(..., description="UUID of the skill")


class SkillCreateRequest(ClientEventBase):
    """Create a new skill in the caller's active org. Set is_system only as an internal user."""
    event_name: ClassVar[str] = "skill:create"

    name: str = Field(..., description="Skill name")
    description: str = Field("", description="Few-sentence retrieval hint")
    body_text: Optional[str] = Field(None, description="Optional prose body")
    body_workflow: Optional[Dict[str, Any]] = Field(None, description="Optional workflow graph")
    display_metadata: Optional[Dict[str, Any]] = Field(None, description="Viewport / UI state for the workflow body")
    enabled: bool = Field(True, description="Owner-side default enabled flag")
    is_system: bool = Field(False, description="Mark as platform-maintained (internal users only)")


class SkillUpdateRequest(ClientEventBase):
    """Patch a skill. Omitted fields are left unchanged."""
    event_name: ClassVar[str] = "skill:update"

    skill_id: str = Field(..., description="UUID of the skill")
    name: Optional[str] = Field(None, description="New name")
    description: Optional[str] = Field(None, description="New description")
    body_text: Optional[str] = Field(None, description="New prose body — empty string clears it")
    enabled: Optional[bool] = Field(None, description="New enabled flag")


class SkillDeleteRequest(ClientEventBase):
    """Delete a skill (owner / staff only). Cascades skill_user_mutes."""
    event_name: ClassVar[str] = "skill:delete"

    skill_id: str = Field(..., description="UUID of the skill")


class SkillMuteRequest(ClientEventBase):
    """Mute or unmute a skill for the calling user. System skills cannot be muted."""
    event_name: ClassVar[str] = "skill:mute"

    skill_id: str = Field(..., description="UUID of the skill")
    muted: bool = Field(..., description="True to mute, false to unmute")


class SkillGetWorkflowRequest(ClientEventBase):
    """Fetch the workflow body + display metadata of a skill for FlowCanvas."""
    event_name: ClassVar[str] = "skill:get_workflow"

    skill_id: str = Field(..., description="UUID of the skill")


class SkillUpdateWorkflowRequest(ClientEventBase):
    """Save the workflow body and/or display metadata of a skill from FlowCanvas."""
    event_name: ClassVar[str] = "skill:update_workflow"

    skill_id: str = Field(..., description="UUID of the skill")
    body_workflow: Optional[Dict[str, Any]] = Field(None, description="Workflow graph (nodes/edges/etc).")
    display_metadata: Optional[Dict[str, Any]] = Field(None, description="Viewport / UI state for the workflow body")


# Parallel OAuth Events
class ParallelOAuthExchangeRequest(ClientEventBase):
    """Exchange Parallel OAuth authorization code for API key (PKCE flow)."""
    event_name: ClassVar[str] = "parallel:oauth:exchange"

    code: str = Field(..., description="Authorization code from Parallel OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    code_verifier: str = Field(..., description="PKCE code verifier used during authorization")
    credential_name: str = Field(..., description="Human-readable name for the credential")


class ParallelOAuthValidateRequest(ClientEventBase):
    """Validate if a stored Parallel API key is still active."""
    event_name: ClassVar[str] = "parallel:oauth:validate"
# Pipedrive OAuth Events
class PipedriveOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for tokens and store as credential"""
    event_name: ClassVar[str] = "pipedrive:oauth:exchange"

    code: str = Field(..., description="Authorization code from Pipedrive OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")


class PipedriveOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Pipedrive OAuth token (access tokens expire after 60 minutes)"""
    event_name: ClassVar[str] = "pipedrive:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class PipedriveOAuthValidateRequest(ClientEventBase):
    """Validate if a Pipedrive OAuth token is still valid"""
    event_name: ClassVar[str] = "pipedrive:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")


# Cloudflare OAuth Events
class CloudflareOAuthExchangeRequest(ClientEventBase):
    """Exchange OAuth authorization code for Cloudflare tokens and store as credential"""
    event_name: ClassVar[str] = "cloudflare:oauth:exchange"

    code: str = Field(..., description="Authorization code from Cloudflare OAuth callback")
    redirect_uri: str = Field(..., description="Redirect URI used in authorization request")
    scopes: List[str] = Field(default_factory=list, description="OAuth scopes that were requested")


class CloudflareOAuthRefreshRequest(ClientEventBase):
    """Refresh an expired Cloudflare OAuth access token"""
    event_name: ClassVar[str] = "cloudflare:oauth:refresh"

    credential_id: str = Field(..., description="UUID of the credential to refresh")


class CloudflareOAuthValidateRequest(ClientEventBase):
    """Validate if a Cloudflare OAuth token is still valid"""
    event_name: ClassVar[str] = "cloudflare:oauth:validate"

    credential_id: str = Field(..., description="UUID of the credential to validate")
