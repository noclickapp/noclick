"""
Pydantic models for type-safe socket.io events.
These models define the structure of all socket events emitted by the backend,
ensuring type safety and enabling automatic TypeScript generation for frontend
usage.
"""
from typing import ClassVar, Optional, Union, List, Dict, Any, Literal
from pydantic import BaseModel, Field, ConfigDict
from .schema import AgenticStep, ContentItem


# Response Events
class ResponseEvent(BaseModel):
    """Generic response event for correlated requests"""
    event_name: ClassVar[str] = "response"
    available_in_template: ClassVar[bool] = True  # Templates need this for database responses
    request_id: str = Field(..., description="Correlation ID from request")
    data: Any = Field(..., description="Response data")
    error: Optional[str] = Field(None, description="Error message if failed")


class ServerDataEvent(BaseModel):
    """Server-initiated data push event (no request correlation)"""
    event_name: ClassVar[str] = "server:data"
    data_type: str = Field(..., description="Type of data being pushed (e.g., 'databases', 'apps')")
    data: Any = Field(..., description="The data being pushed")
    error: Optional[str] = Field(None, description="Error message if failed")


class AgentStateEvent(BaseModel):
    """Event emitted when the agent's state changes (running, paused, etc.)."""
    event_name: ClassVar[str] = "agent:state"

    state: str = Field(..., description="New agent state")
    conversation_id: Optional[str] = Field(None, description="Conversation ID this state change applies to")
    reason: Optional[str] = Field(None, description="Optional reason for the state change")


# Chat Events
class RehearsalProgressEvent(BaseModel):
    """Live progress of a staged agent run.

    The rehearsal carries its own channel rather than borrowing the chat/
    workflow relay plumbing: a rehearsal can be watched from a surface that never
    opened the workflow (onboarding, a template preview), and those surfaces are
    not in the workflow's room, so room-routed events never reach them.

    Every frame is explicitly ``rehearsed`` — the UI must never have to infer
    whether what it is showing really happened.
    """
    event_name: ClassVar[str] = "rehearsal:progress"

    conversation_id: str = Field(..., description="The rehearsal this frame belongs to")
    kind: str = Field(..., description="'step' | 'thought' | 'done' | 'failed'")
    step_id: Optional[str] = Field(None, description="Stable id so a completed frame updates its in-progress row")
    tool: Optional[str] = Field(None, description="Tool the agent reached for, e.g. slack__send_message_to_channel")
    status: Optional[str] = Field(None, description="'in_progress' | 'completed' for a step frame")
    outbound: Optional[str] = Field(None, description="The message the agent actually composed for this call — what would have been posted or sent")
    args: Optional[Dict[str, Any]] = Field(None, description="What the agent called the tool with — real arguments, the agent's own judgment")
    result: Optional[Any] = Field(None, description="What the fabricated world answered — stand-in data, never live")
    reply: Optional[str] = Field(None, description="What the agent said, on the final frame")
    text: Optional[str] = Field(None, description="A slice of the agent's visible reasoning between tool calls, on a 'thought' frame")
    error: Optional[str] = Field(None, description="Why it stopped, when it did")
    rehearsed: bool = Field(True, description="Always true: the world was fabricated, only the agent was real")


class BuilderPromptProposal(BaseModel):
    """Structured prompt-builder approval card sent with a chat message."""

    prompt: str
    node_id: Optional[str] = None
    proposal_id: Optional[str] = None
    anchored_prompt: Optional[str] = None
    decision: Optional[Literal["approved", "dismissed"]] = None


class ChatMessageEvent(BaseModel):
    """
    Event emitted for chat messages including AI responses and component generation.
    
    This event is used for all AI agent responses and component generation in the chat interface.
    """
    event_name: ClassVar[str] = "chat:message"

    conversation_id: Optional[str] = Field(
        None,
        description="Conversation session ID for associating messages with specific conversation context"
    )
    status: Optional[str] = Field(
        None,
        description="Status of the message like 'Thinking', 'Generating Component'. Only displayed if message is None or empty"
    )
    message: Optional[str] = Field(
        None,
        description="Text to add to the response. Streamable - multiple events can be sent and text will be concatenated"
    )
    component: Optional[Union[bool, str]] = Field(
        None,
        description="Component to render. False=no component expected, True=show skeleton loader, str=render component code"
    )
    props: Optional[Dict[str, Any]] = Field(
        None,
        description="Props for the component being sent"
    )
    import_map: Optional[Dict[str, str]] = Field(
        None,
        description="Dictionary of imports for the component"
    )
    finished: bool = Field(
        False,
        description="Whether message is finished. User can only send new messages after this is True"
    )
    agentic_steps: Optional[List[AgenticStep]] = Field(
        None,
        description="Steps in agentic workflow for multi-step operations"
    )
    model: Optional[str] = Field(
        None,
        description="The LLM model being used for this response"
    )
    content: Optional[List[ContentItem]] = Field(
        None,
        description="Structured content with text and images. Used when the message contains mixed media"
    )
    builder_prompt: Optional[BuilderPromptProposal] = Field(
        None,
        description="Approval card for the agent's prompt_builder tool (interactive chats "
                    "only): {prompt, node_id, proposal_id}. The chat renders approve/dismiss; "
                    "approving opens the builder sidebar and submits the prompt. Standalone "
                    "frame — no message text, no streaming implications."
    )


# The live tool-step stream is emitted from TWO places into one transcript —
# the in-process SDK run loop and registered CLI runners. Frame
# construction lives here so a label change or argument redaction can never
# apply to one emitter and miss the other.
TOOL_STEP_TEXT_CHARS = 500


def tool_call_step_text(tool_name: str, arguments: Any) -> str:
    """The in_progress row label for a tool call."""
    import json

    args_text = json.dumps(arguments, default=str) if arguments else ""
    return f"Calling {tool_name}({args_text})"


def tool_step_event(
    step_id: str, text: str, status: str, conversation_id: Optional[str] = None
) -> ChatMessageEvent:
    """One id-keyed AgenticStep frame (in_progress → completed updates the same
    row in place on the frontend). Text is bounded — completed frames carry a
    result preview, and full payloads live in tool_call_events anyway."""
    return ChatMessageEvent(
        conversation_id=conversation_id,
        message=None,
        finished=False,
        agentic_steps=[AgenticStep(id=step_id, text=str(text)[:TOOL_STEP_TEXT_CHARS], status=status)],
    )


class ChatTranscriptionEvent(BaseModel):
    """Event emitted when voice transcription is received"""
    event_name: ClassVar[str] = "chat:transcription"
    
    transcription: str = Field(..., description="Transcribed text from voice input")


class CreditsExhaustedEvent(BaseModel):
    """Event emitted when the user's credit pool is too low to run a cost-bearing operation.

    Emitted by the agent BillingHooks pre-call balance check (for agent runs) and
    by the per-node pre-flight checks in the image/imagen/kling/video node handlers
    when check_credit_balance returns a value below the minimum.
    Account-level usage surfaces may listen for this event and surface its
    message. Some runners raise the same policy failure as an error instead.
    """
    event_name: ClassVar[str] = "credits:exhausted"

    credits_remaining: float = Field(..., description="User's credit balance remaining this month")
    credits_required: float = Field(default=0.20, description="Minimum credits required for this operation")
    message: str = Field(
        default="Not enough credits to run this. Check your instance policy or connect your own provider credentials.",
        description="Message to display to user",
    )
    organization_id: Optional[str] = Field(None, description="Organization ID if the run was on behalf of an org")


# YJS Events
class YjsSyncEvent(BaseModel):
    """Event for YJS synchronization"""
    event_name: ClassVar[str] = "yjs:sync"
    
    data: bytes = Field(..., description="YJS sync binary data")
    
    def model_dump(self, **kwargs) -> list:
        """Override to return list of integers for Socket.IO transmission"""
        _ = kwargs  # Unused but required for interface compatibility
        return list(self.data)


# Conversation Management Events
class ConversationResumeEvent(BaseModel):
    """Event emitted with full chat history when conversation is resumed"""
    event_name: ClassVar[str] = "conversation:resume"

    request_id: Optional[str] = Field(None, description="Request ID for profiling correlation")
    session_id: str = Field(..., description="Session ID of the resumed conversation")
    messages: List[Dict[str, Any]] = Field(..., description="List of chat messages with role and content")
    agentic_steps: Optional[List[Dict[str, Any]]] = Field(None, description="Reconstructed agentic steps for the conversation")


class ConversationListEvent(BaseModel):
    """Event emitted with list of available conversation sessions"""
    event_name: ClassVar[str] = "conversations:list"

    request_id: Optional[str] = Field(None, description="Request ID for profiling correlation")
    conversations: List[Dict[str, Any]] = Field(..., description="List of conversation metadata including session_id, last_modified, message_count")


# ── Active-generation events ─────────────────────────────────────────────
#
# These power the per-event push contract that the FE activeGenStore + relay
# live-generation mirror consume. Every active builder run emits exactly one
# `started`, zero-or-more deltas (text_chunk / status / graph_event /
# edit_step), and exactly one `terminal`. The relay holds an in-memory mirror
# keyed on generation_id; on viewer-WS connect it sends `live_gens_snapshot`
# so a freshly-mounted FE (refresh, second tab, second device) catches up
# without polling.
#
# Identity: generation_id is the primary key. workflow_id is an index so
# the FE can answer "what's active for the workflow I'm viewing." A single
# workflow may have multiple concurrent gens (multi-agent future).


class ActiveGenStartedEvent(BaseModel):
    """A builder run just kicked off — register a fresh active gen."""
    event_name: ClassVar[str] = "active_gen:started"

    gen_id: str = Field(..., description="Globally unique generation id")
    workflow_id: Optional[str] = Field(None, description="Workflow this run targets (None for headless / list-workflows flows)")
    conversation_id: str = Field(..., description="Conversation row this run is writing to")
    prompt: str = Field("", description="The user message that kicked off this run")
    started_at: float = Field(..., description="Wall-clock seconds since epoch (FE uses this to order multi-gen displays)")
    # Echoes the originating ChatMessageRequest.request_id so the FE can join
    # this gen's lifecycle (started → text_chunk → terminal) back to the
    # send-side timestamp and report exact user-perceived latency.
    request_id: Optional[str] = Field(None, description="Echoes the originating client request's request_id for FE latency correlation")


class ActiveGenTextChunkEvent(BaseModel):
    """A delta of brain text. FE appends to the gen's accumulated text."""
    event_name: ClassVar[str] = "active_gen:text_chunk"

    gen_id: str = Field(..., description="Generation this delta belongs to")
    delta: str = Field(..., description="Text fragment to append")
    request_id: Optional[str] = Field(None, description="Echoes the originating client request's request_id for FE latency correlation")


class ActiveGenStatusEvent(BaseModel):
    """A status update (e.g. 'Modifying workflow', 'Searching credentials')."""
    event_name: ClassVar[str] = "active_gen:status"

    gen_id: str = Field(..., description="Generation this status belongs to")
    status: str = Field(..., description="Human-readable status text")


class ActiveGenTokenProgressEvent(BaseModel):
    """Heuristic running "tokens processed" count for the live builder counter.

    Ephemeral anti-stall signal, NOT a billing commitment. Counts OUTPUT tokens
    only (input is consumed upfront in one shot and would spike the curve), so
    the value stays on the same scale as the streaming chars/4 heuristic and
    climbs smoothly. `total_tokens` is an ABSOLUTE cumulative value (real output
    total of finished phases + the chars/4 heuristic for the in-flight stream),
    not a delta — the FE overwrites rather than accumulating, so a dropped frame
    self-heals on the next tick. Reconciled to the real output total at each
    phase boundary (brain end, node drafting end).
    """
    event_name: ClassVar[str] = "active_gen:token_progress"

    gen_id: str = Field(..., description="Generation this count belongs to")
    total_tokens: int = Field(..., description="Cumulative heuristic tokens processed so far (absolute, not a delta)")


class ActiveGenGraphEventEvent(BaseModel):
    """A graph-mutation event (node_added, node_updated, edge_added, etc.).

    The full event payload is forwarded as-is so the FE renderer doesn't
    need to know the BE event taxonomy.
    """
    event_name: ClassVar[str] = "active_gen:graph_event"

    gen_id: str = Field(..., description="Generation this event belongs to")
    event: Dict[str, Any] = Field(..., description="The graph event payload (type + node/edge fields)")


class ActiveGenEditStepEvent(BaseModel):
    """A reasoning-log entry for the expandable EditStepsView."""
    event_name: ClassVar[str] = "active_gen:edit_step"

    gen_id: str = Field(..., description="Generation this step belongs to")
    step: str = Field(..., description="Reasoning-log line")


class ActiveGenTerminalEvent(BaseModel):
    """A run reached a terminal state — drop from the active map and patch
    the FE's persisted view with the freshly-committed events array.

    `committed_messages` carries the full updated conversations.events for
    `committed_conversation_id` so the FE can swap its persisted view in
    the same frame the gen evicts — no flicker, no refetch round-trip.
    """
    event_name: ClassVar[str] = "active_gen:terminal"

    gen_id: str = Field(..., description="Generation that just terminated")
    outcome: str = Field(..., description="One of: complete, paused, cancelled, failed, interrupted")
    committed_conversation_id: Optional[str] = Field(None, description="Conversation that received the committed turn")
    committed_messages: List[Dict[str, Any]] = Field(default_factory=list, description="Full conversations.events array post-commit")
    error: Optional[str] = Field(None, description="Error message when outcome=failed")
    request_id: Optional[str] = Field(None, description="Echoes the originating client request's request_id for FE latency correlation")


class ActiveGenSnapshotEvent(BaseModel):
    """Sent by the event relay on viewer connect — the full set of active
    gens for the user. The FE replaces its local activeGenStore with this
    snapshot, then continues consuming deltas live.
    """
    event_name: ClassVar[str] = "active_gen:snapshot"

    gens: List[Dict[str, Any]] = Field(default_factory=list, description="ActiveGeneration[] — full state of each in-flight run")


class LatestConversationForWorkflowEvent(BaseModel):
    """Response for conversation:get_latest_for_workflow.

    `conversation_id` is null when no conversation has been linked to the
    workflow yet. `has_user_messages` lets the FE decide between auto-restore
    (no current sidebar activity) and offering a pill. `active_generation_id`
    + `has_pending_ask` lets the FE rehydrate an in-flight builder ask without
    a separate round-trip.
    """
    event_name: ClassVar[str] = "conversation:latest_for_workflow"

    request_id: Optional[str] = Field(None, description="Request ID for correlation")
    workflow_id: str = Field(..., description="Workflow ID this lookup was for")
    conversation_id: Optional[str] = Field(None, description="Latest conversation ID for the workflow, or null")
    has_user_messages: bool = Field(False, description="Whether the conversation has any user-authored messages")
    active_generation_id: Optional[str] = Field(None, description="ID of an active builder generation tied to this conversation, if any")
    has_pending_ask: bool = Field(False, description="Whether the active generation is waiting on user input")


# Cache Valtio Events
class CacheValtioStateEvent(BaseModel):
    """Initial state restoration event sent on connection"""
    event_name: ClassVar[str] = "cache_valtio:state"
    
    state_update: List[int] = Field(..., description="YJS encoded state update as byte array")
    cache_timestamp: int = Field(..., description="Unix timestamp in milliseconds when cache was created")

    def model_dump(self, **kwargs):
        """Override to return dict with state_update and timestamp"""
        return {
            'state_update': self.state_update,
            'cache_timestamp': self.cache_timestamp
        }


# Error Events
class ErrorEvent(BaseModel):
    """Generic error event"""
    event_name: ClassVar[str] = "error"

    type: str = Field(..., description="Error type (e.g., 'rate_limit')")
    message: str = Field(..., description="Error message")
    request_id: Optional[str] = Field(None, description="Original request_id for correlating with pending callbacks")


class WorkflowNameGeneratedEvent(BaseModel):
    """Background-generated name for a newly created workflow."""
    event_name: ClassVar[str] = "workflow:name_generated"

    workflow_id: str
    name: str
    description: str



# Usage Dashboard Events
class UsageDataEvent(BaseModel):
    """Event emitted with aggregated usage data for dashboard visualization"""
    event_name: ClassVar[str] = "usage:data"

    request_id: Optional[str] = Field(None, description="Request ID for correlation")
    total_cost: float = Field(..., description="Total credits consumed for the queried period (handler converts $→credits at the wire boundary)")
    usage_by_type: Dict[str, float] = Field(..., description="Credits breakdown by usage type (ai_usage, ai_builder, api_usage, etc.)")
    usage_by_subtype: Dict[str, float] = Field(..., description="Credits breakdown by specific models/instances")
    time_series: List[Dict[str, Any]] = Field(..., description="Time series data for charting (date, credit totals, breakdown)")
    current_balance: float = Field(..., description="User's current balance (legacy $ pool; preserved for compatibility, dashboard now shows credit pool from useCreditUsage)")
    period_start: Optional[str] = Field(None, description="Start of the queried period (ISO format)")
    period_end: Optional[str] = Field(None, description="End of the queried period (ISO format)")
    error: Optional[str] = Field(None, description="Error message if failed")


class UsageEventUpdateEvent(BaseModel):
    """Event emitted when a new usage event occurs in real-time"""
    event_name: ClassVar[str] = "usage:event"

    usage_type: str = Field(..., description="Type of usage (ai_usage, ai_builder, api_usage, cpu_usage, gpu_usage)")
    usage_subtype: str = Field(..., description="Specific subtype (model name, instance type, etc.)")
    total_cost: float = Field(..., description="Credits consumed by this usage event (handler converts $→credits at the wire boundary; $ never leaves the backend)")
    quantity: float = Field(..., description="Amount used (tokens, hours, etc.)")
    unit_type: str = Field(..., description="Unit of measurement (tokens, cpu_hours, etc.)")
    # Vestigial — the legacy $ pool was frozen in Phase 2.1 and the live
    # usage tracker no longer computes a balance to send. Kept as an
    # optional field for FE wire-compat (older listeners may still read it)
    # but defaulted to 0 so callers don't have to pass it. Required-ness
    # used to crash the emit silently inside start_background_task: the
    # validation error was caught and logged, but the chip stayed stale.
    current_balance: float = Field(0.0, description="DEPRECATED — legacy $ pool was retired in Phase 2.1; always 0")
    user_resource: bool = Field(..., description="Whether this was a user-provided resource")
    timestamp: Optional[float] = Field(None, description="Unix timestamp when event occurred")
    organization_id: Optional[str] = Field(None, description="Org workspace this event belongs to; null means personal")
    # The user whose credit pool this charge actually drew on. Under "organization attribution policy"
    # an org run is billed to the org OWNER, not the running member — so this is
    # the usage-event row's user_id (= billing entity), which differs from the
    # socket recipient for org members. Clients deduct a live event iff this
    # matches the pool they're currently displaying.
    billing_user_id: Optional[str] = Field(None, description="User whose credit pool was charged (org owner under the configured attribution policy)")


# Debug Events
# Workflow Execution Events
# These events support dual-delivery: when triggered via MCP (OAuth), they're sent to both
# the MCP client AND the frontend for real-time UI updates.
class WorkflowNodeStateEvent(BaseModel):
    """Event emitted when a workflow node changes state (idle/running/completed/error/skipped)"""
    event_name: ClassVar[str] = "workflow:node:state"
    available_in_template: ClassVar[bool] = True
    mcp_config: ClassVar[dict] = {
        "notify_frontend": True,
        "frontend_event_name": "workflow:node:state"
    }

    workflow_id: str = Field(..., description="Workflow UUID containing the node")
    node_id: str = Field(..., description="ID of the node")
    node_type: str = Field(..., description="Type of the node (e.g., 'automation-telegram', 'agent')")
    state: str = Field(..., description="Node state: 'idle', 'running', 'completed', 'error', 'skipped'")
    error: Optional[str] = Field(None, description="Error message if state is 'error'")
    execution_id: Optional[str] = Field(None, description="Execution UUID for state tracking across sessions")
    error_action: Optional[Dict[str, str]] = Field(
        None,
        description=(
            "The one thing the user can do about this error, for the UI to "
            "render as a button: {type, label, url?}. type is "
            "'open_credentials' (open this node's Credentials tab) or "
            "'open_url'. Absent when nothing useful can be clicked — a "
            "provider outage or rate limit is waited out, not acted on."
        ),
    )


class WorkflowNodeOutputEvent(BaseModel):
    """Event emitted when a workflow node produces output. One emit per
    execution: carries the canonical, final, structured output of the node.
    Streaming progress goes through WorkflowNodeProgressEvent instead."""
    event_name: ClassVar[str] = "workflow:node:output"
    available_in_template: ClassVar[bool] = True
    mcp_config: ClassVar[dict] = {
        "notify_frontend": True,
        "frontend_event_name": "workflow:node:output"
    }

    workflow_id: str = Field(..., description="Workflow UUID containing the node")
    node_id: str = Field(..., description="ID of the node producing output")
    node_type: str = Field(..., description="Type of the node")
    output: Dict[str, Any] = Field(..., description="Output data with arbitrary metadata from the node")


class WorkflowNodeProgressEvent(BaseModel):
    """Live in-flight activity from a workflow node — separate from the
    canonical WorkflowNodeOutputEvent.

    Why a separate event: previously, agent_node streamed chunks via
    WorkflowNodeOutputEvent with type='chat_message', and per-node summary
    emits (Jira's ``{"action": "list_boards", "count": 2}``) also rode the
    canonical output channel. Both fought the final
    ``{type:'agent', status:'completed'}`` emit for ownership of
    node.data.output, so a late chunk or summary could overwrite the
    canonical with a partial snippet.

    The progress slot is structurally race-free: progress writes here,
    the canonical output writes to node.data.output and clears
    node.data.progress. The two writers don't share storage.

    Two payload modes — exactly one of ``append`` or ``snapshot`` per
    event:
      - ``append``: text fragment from a streaming source. The frontend
        concatenates it to ``node.data.progress.text``.
      - ``snapshot``: structured payload from a one-shot
        ``self.emit({...})`` call (e.g. ``{"action": "list_boards",
        "count": 2}``). The frontend replaces ``node.data.progress.snapshot``.
    """
    event_name: ClassVar[str] = "workflow:node:progress"
    available_in_template: ClassVar[bool] = True
    mcp_config: ClassVar[dict] = {
        "notify_frontend": True,
        "frontend_event_name": "workflow:node:progress"
    }

    workflow_id: str = Field(..., description="Workflow UUID containing the node")
    node_id: str = Field(..., description="ID of the node producing progress")
    node_type: str = Field(..., description="Type of the node")
    append: Optional[str] = Field(None, description="Text fragment to append to node.data.progress.text. Set for streaming sources (agent text deltas).")
    snapshot: Optional[Dict[str, Any]] = Field(None, description="Structured one-shot payload that replaces node.data.progress.snapshot. Set by self.emit({...}) callers.")


class WorkflowStartedEvent(BaseModel):
    """Event emitted when workflow execution starts"""
    event_name: ClassVar[str] = "workflow:started"
    available_in_template: ClassVar[bool] = True
    mcp_config: ClassVar[dict] = {
        "notify_frontend": True,
        "frontend_event_name": "workflow:started"
    }

    execution_id: str = Field(..., description="Execution UUID for this workflow run")
    workflow_id: str = Field(..., description="Workflow UUID being executed")
    background: bool = Field(
        False,
        description="True when the run was triggered by an interface component fetching its own data "
                    "(echoed from WorkflowExecuteRequest). The client uses this to keep the run out of "
                    "the global Run/Stop button state."
    )
    resumed: bool = Field(
        False,
        description="True when this 'started' is the resumption of a run that was suspended on a "
                    "delay or approval node. The client updates the existing run's log line in place "
                    "rather than treating it as a new run."
    )


class WorkflowCompleteEvent(BaseModel):
    """Event emitted when entire workflow execution completes"""
    event_name: ClassVar[str] = "workflow:complete"
    available_in_template: ClassVar[bool] = True
    mcp_config: ClassVar[dict] = {
        "notify_frontend": True,
        "frontend_event_name": "workflow:complete"
    }

    execution_id: str = Field(..., description="Execution UUID for this workflow run")
    workflow_id: str = Field(..., description="Workflow UUID that was executed")
    success: bool = Field(..., description="Whether workflow completed successfully")
    nodes_executed: int = Field(..., description="Number of nodes executed")
    duration: float = Field(..., description="Total execution time in seconds")
    error: Optional[str] = Field(None, description="Error message if workflow failed")
    suspended: bool = Field(
        False,
        description="True when the run did not finish but paused on a delay or approval "
                    "node. The client shows the run as 'Waiting' rather than completed."
    )
class StateChangedEvent(BaseModel):
    """Event emitted when a workflow's persistent state is modified (for cross-client sync)"""
    event_name: ClassVar[str] = "state:changed"

    key: str = Field(..., description="State key that was changed")
    value: Any = Field(None, description="New value (None if deleted)")


# MCP Workflow Events (Backend → Frontend bidirectional requests)
class WorkflowMCPRequestEvent(BaseModel):
    """
    Backend request for frontend workflow data or mutation.

    This enables bidirectional communication where the backend MCP handler
    can request data from the frontend (e.g., selected node, node outputs)
    or request mutations (e.g., add node, remove node).

    The frontend responds with a 'workflow:mcp:response' event containing
    the same request_id for correlation.
    """
    event_name: ClassVar[str] = "workflow:mcp:request"

    request_id: str = Field(..., description="Correlation ID for response matching")
    request_type: str = Field(..., description="Type of request: 'get_state', 'get_selected', 'get_output', 'get_input', 'add_node', 'remove_node'")
    params: Dict[str, Any] = Field(default_factory=dict, description="Request-specific parameters (e.g., node_id, node_type, config)")


# Share Notification Events
class ShareNotificationEvent(BaseModel):
    """
    Event emitted when a resource is shared with a user.

    This is a push notification sent to the target user (via Event Relay if needed)
    when someone shares a workflow or database with them directly (1:1 email share).
    Not sent for org-wide shares to avoid notification spam.
    """
    event_name: ClassVar[str] = "share:notification"

    resource_type: str = Field(..., description="Type of resource shared (workflow, database)")
    resource_id: str = Field(..., description="UUID of the shared resource")
    resource_name: str = Field(..., description="Name of the shared resource")
    permission: str = Field(..., description="Permission level granted (view, edit)")
    shared_by_email: str = Field(..., description="Email of the user who shared")
    shared_by_name: Optional[str] = Field(None, description="Display name of the user who shared")
    share_id: str = Field(..., description="UUID of the share for navigation")


# Approval Feed Events
class ApprovalRequestCreatedEvent(BaseModel):
    """Event emitted when an approval node creates a pending request."""
    event_name: ClassVar[str] = "approval:request:created"

    approval_id: str = Field(..., description="UUID of the approval_requests row — same id carried by ApprovalRequestResolvedEvent, so the FE can correlate created → resolved without inventing its own id")
    workflow_id: str = Field(..., description="Workflow UUID containing the approval node")
    execution_id: str = Field(..., description="Execution UUID that is now paused")
    node_id: str = Field(..., description="ID of the approval node")
    title: str = Field("", description="Short title for the approval card")
    fields: List[Dict[str, Any]] = Field(default_factory=list, description="Form field definitions")
    values: Dict[str, Any] = Field(default_factory=dict, description="Resolved form field values")


class ActivityLogCreatedEvent(BaseModel):
    """Event emitted when a log node writes an activity entry."""
    event_name: ClassVar[str] = "activity:log:created"

    workflow_id: str = Field(..., description="Workflow UUID")
    execution_id: str = Field(..., description="Execution UUID")
    node_id: str = Field(..., description="ID of the log node")
    message: str = Field(..., description="Log message")
    level: str = Field("info", description="Log level: info, success, warning, error")


class ApprovalRequestResolvedEvent(BaseModel):
    """Event emitted when a human approves or rejects an approval request."""
    event_name: ClassVar[str] = "approval:request:resolved"

    approval_id: str = Field(..., description="UUID of the resolved approval request")
    workflow_id: str = Field(..., description="Workflow UUID")
    status: str = Field(..., description="Decision: 'approved' or 'rejected'")
    decided_by: str = Field(..., description="User ID of the person who decided")


class MCPBuilderEvent(BaseModel):
    """Canvas-update event sent to all of a user's connected frontends.

    Carries an ``event_type`` ("node_updated", "node_start", "edge_added", …)
    plus an opaque ``data`` payload — the FE's useMCPBuilderEvents hook routes
    each event_type through its renderer. Used by mcp_server's update_workflow
    flow AND by the runtime auto-extend path (see utils/workflow_node_writeback)
    to push runtime config mutations live to collaborators.
    """
    event_name: ClassVar[str] = "mcp:builder_event"

    workflow_id: str = Field(..., description="UUID of the workflow being mutated")
    event_type: str = Field(..., description="Builder event variant (e.g. 'node_updated')")
    data: Dict[str, Any] = Field(default_factory=dict, description="Per-event payload (nodeId, config, …)")
