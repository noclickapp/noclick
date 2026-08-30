// Auto-generated from backend Pydantic models
// DO NOT EDIT MANUALLY - run 'npm run generate:types' instead
// Generated at: Sun Aug 30 13:29:34  2026
// Target: all

import { AgenticStep, ContentItem, ImageUrl } from './socket-schema.generated';

/* tslint:disable */
/* eslint-disable */
/**
/* This file was automatically generated from pydantic models by running pydantic2ts.
/* Do not modify it by hand - just update the pydantic models and then re-run the script
*/

/**
 * A reasoning-log entry for the expandable EditStepsView.
 */
export interface ActiveGenEditStepEvent {
  /**
   * Generation this step belongs to
   */
  gen_id: string;
  /**
   * Reasoning-log line
   */
  step: string;
}
/**
 * A graph-mutation event (node_added, node_updated, edge_added, etc.).
 *
 * The full event payload is forwarded as-is so the FE renderer doesn't
 * need to know the BE event taxonomy.
 */
export interface ActiveGenGraphEventEvent {
  /**
   * Generation this event belongs to
   */
  gen_id: string;
  /**
   * The graph event payload (type + node/edge fields)
   */
  event: {
    [k: string]: unknown;
  };
}
/**
 * Sent by the event relay on viewer connect — the full set of active
 * gens for the user. The FE replaces its local activeGenStore with this
 * snapshot, then continues consuming deltas live.
 */
export interface ActiveGenSnapshotEvent {
  /**
   * ActiveGeneration[] — full state of each in-flight run
   */
  gens?: {
    [k: string]: unknown;
  }[];
}
/**
 * A builder run just kicked off — register a fresh active gen.
 */
export interface ActiveGenStartedEvent {
  /**
   * Globally unique generation id
   */
  gen_id: string;
  /**
   * Workflow this run targets (None for headless / list-workflows flows)
   */
  workflow_id?: string | null;
  /**
   * Conversation row this run is writing to
   */
  conversation_id: string;
  /**
   * The user message that kicked off this run
   */
  prompt?: string;
  /**
   * Wall-clock seconds since epoch (FE uses this to order multi-gen displays)
   */
  started_at: number;
  /**
   * Echoes the originating client request's request_id for FE latency correlation
   */
  request_id?: string | null;
}
/**
 * A status update (e.g. 'Modifying workflow', 'Searching credentials').
 */
export interface ActiveGenStatusEvent {
  /**
   * Generation this status belongs to
   */
  gen_id: string;
  /**
   * Human-readable status text
   */
  status: string;
}
/**
 * A run reached a terminal state — drop from the active map and patch
 * the FE's persisted view with the freshly-committed events array.
 *
 * `committed_messages` carries the full updated conversations.events for
 * `committed_conversation_id` so the FE can swap its persisted view in
 * the same frame the gen evicts — no flicker, no refetch round-trip.
 */
export interface ActiveGenTerminalEvent {
  /**
   * Generation that just terminated
   */
  gen_id: string;
  /**
   * One of: complete, paused, cancelled, failed, interrupted
   */
  outcome: string;
  /**
   * Conversation that received the committed turn
   */
  committed_conversation_id?: string | null;
  /**
   * Full conversations.events array post-commit
   */
  committed_messages?: {
    [k: string]: unknown;
  }[];
  /**
   * Error message when outcome=failed
   */
  error?: string | null;
  /**
   * Machine-readable failure class when outcome=failed, e.g. provider_key_missing
   */
  error_code?: string | null;
  /**
   * Details for error_code — provider_key_missing carries env_var, provider, model
   */
  error_meta?: {
    [k: string]: unknown;
  } | null;
  /**
   * Echoes the originating client request's request_id for FE latency correlation
   */
  request_id?: string | null;
}
/**
 * A delta of brain text. FE appends to the gen's accumulated text.
 */
export interface ActiveGenTextChunkEvent {
  /**
   * Generation this delta belongs to
   */
  gen_id: string;
  /**
   * Text fragment to append
   */
  delta: string;
  /**
   * Echoes the originating client request's request_id for FE latency correlation
   */
  request_id?: string | null;
}
/**
 * Heuristic running "tokens processed" count for the live builder counter.
 *
 * Ephemeral anti-stall signal, NOT a billing commitment. Counts OUTPUT tokens
 * only (input is consumed upfront in one shot and would spike the curve), so
 * the value stays on the same scale as the streaming chars/4 heuristic and
 * climbs smoothly. `total_tokens` is an ABSOLUTE cumulative value (real output
 * total of finished phases + the chars/4 heuristic for the in-flight stream),
 * not a delta — the FE overwrites rather than accumulating, so a dropped frame
 * self-heals on the next tick. Reconciled to the real output total at each
 * phase boundary (brain end, node drafting end).
 */
export interface ActiveGenTokenProgressEvent {
  /**
   * Generation this count belongs to
   */
  gen_id: string;
  /**
   * Cumulative heuristic tokens processed so far (absolute, not a delta)
   */
  total_tokens: number;
}
/**
 * Event emitted when a log node writes an activity entry.
 */
export interface ActivityLogCreatedEvent {
  /**
   * Workflow UUID
   */
  workflow_id: string;
  /**
   * Execution UUID
   */
  execution_id: string;
  /**
   * ID of the log node
   */
  node_id: string;
  /**
   * Log message
   */
  message: string;
  /**
   * Log level: info, success, warning, error
   */
  level?: string;
}
/**
 * Event emitted when the agent's state changes (running, paused, etc.).
 */
export interface AgentStateEvent {
  /**
   * New agent state
   */
  state: string;
  /**
   * Conversation ID this state change applies to
   */
  conversation_id?: string | null;
  /**
   * Optional reason for the state change
   */
  reason?: string | null;
}
/**
 * Event emitted when an approval node creates a pending request.
 */
export interface ApprovalRequestCreatedEvent {
  /**
   * UUID of the approval_requests row — same id carried by ApprovalRequestResolvedEvent, so the FE can correlate created → resolved without inventing its own id
   */
  approval_id: string;
  /**
   * Workflow UUID containing the approval node
   */
  workflow_id: string;
  /**
   * Execution UUID that is now paused
   */
  execution_id: string;
  /**
   * ID of the approval node
   */
  node_id: string;
  /**
   * Short title for the approval card
   */
  title?: string;
  /**
   * Form field definitions
   */
  fields?: {
    [k: string]: unknown;
  }[];
  /**
   * Resolved form field values
   */
  values?: {
    [k: string]: unknown;
  };
}
/**
 * Event emitted when a human approves or rejects an approval request.
 */
export interface ApprovalRequestResolvedEvent {
  /**
   * UUID of the resolved approval request
   */
  approval_id: string;
  /**
   * Workflow UUID
   */
  workflow_id: string;
  /**
   * Decision: 'approved' or 'rejected'
   */
  status: string;
  /**
   * User ID of the person who decided
   */
  decided_by: string;
}
/**
 * Structured prompt-builder approval card sent with a chat message.
 */
export interface BuilderPromptProposal {
  prompt: string;
  node_id?: string | null;
  proposal_id?: string | null;
  anchored_prompt?: string | null;
  decision?: ("approved" | "dismissed") | null;
}
/**
 * Initial state restoration event sent on connection
 */
export interface CacheValtioStateEvent {
  /**
   * YJS encoded state update as byte array
   */
  state_update: number[];
  /**
   * Unix timestamp in milliseconds when cache was created
   */
  cache_timestamp: number;
}
/**
 * Event emitted for chat messages including AI responses and component generation.
 *
 * This event is used for all AI agent responses and component generation in the chat interface.
 */
export interface ChatMessageEvent {
  /**
   * Conversation session ID for associating messages with specific conversation context
   */
  conversation_id?: string | null;
  /**
   * Status of the message like 'Thinking', 'Generating Component'. Only displayed if message is None or empty
   */
  status?: string | null;
  /**
   * Text to add to the response. Streamable - multiple events can be sent and text will be concatenated
   */
  message?: string | null;
  /**
   * Component to render. False=no component expected, True=show skeleton loader, str=render component code
   */
  component?: boolean | string | null;
  /**
   * Props for the component being sent
   */
  props?: {
    [k: string]: unknown;
  } | null;
  /**
   * Dictionary of imports for the component
   */
  import_map?: {
    [k: string]: string;
  } | null;
  /**
   * Whether message is finished. User can only send new messages after this is True
   */
  finished?: boolean;
  /**
   * Steps in agentic workflow for multi-step operations
   */
  agentic_steps?: AgenticStep[] | null;
  /**
   * The LLM model being used for this response
   */
  model?: string | null;
  /**
   * Structured content with text and images. Used when the message contains mixed media
   */
  content?: ContentItem[] | null;
  /**
   * Approval card for the agent's prompt_builder tool (interactive chats only): {prompt, node_id, proposal_id}. The chat renders approve/dismiss; approving opens the builder sidebar and submits the prompt. Standalone frame — no message text, no streaming implications.
   */
  builder_prompt?: BuilderPromptProposal | null;
}
/**
 * Event emitted when voice transcription is received
 */
export interface ChatTranscriptionEvent {
  /**
   * Transcribed text from voice input
   */
  transcription: string;
}
/**
 * Event emitted with list of available conversation sessions
 */
export interface ConversationListEvent {
  /**
   * Request ID for profiling correlation
   */
  request_id?: string | null;
  /**
   * List of conversation metadata including session_id, last_modified, message_count
   */
  conversations: {
    [k: string]: unknown;
  }[];
}
/**
 * Event emitted with full chat history when conversation is resumed
 */
export interface ConversationResumeEvent {
  /**
   * Request ID for profiling correlation
   */
  request_id?: string | null;
  /**
   * Session ID of the resumed conversation
   */
  session_id: string;
  /**
   * List of chat messages with role and content
   */
  messages: {
    [k: string]: unknown;
  }[];
  /**
   * Reconstructed agentic steps for the conversation
   */
  agentic_steps?:
    | {
        [k: string]: unknown;
      }[]
    | null;
}
/**
 * Event emitted when the user's credit pool is too low to run a cost-bearing operation.
 *
 * Emitted by the agent BillingHooks pre-call balance check (for agent runs) and
 * by the per-node pre-flight checks in the image/imagen/kling/video node handlers
 * when check_credit_balance returns a value below the minimum.
 * Account-level usage surfaces may listen for this event and surface its
 * message. Some runners raise the same policy failure as an error instead.
 */
export interface CreditsExhaustedEvent {
  /**
   * User's credit balance remaining this month
   */
  credits_remaining: number;
  /**
   * Minimum credits required for this operation
   */
  credits_required?: number;
  /**
   * Message to display to user
   */
  message?: string;
  /**
   * Organization ID if the run was on behalf of an org
   */
  organization_id?: string | null;
}
/**
 * Generic error event
 */
export interface ErrorEvent {
  /**
   * Error type (e.g., 'rate_limit')
   */
  type: string;
  /**
   * Error message
   */
  message: string;
  /**
   * Original request_id for correlating with pending callbacks
   */
  request_id?: string | null;
}
/**
 * Response for conversation:get_latest_for_workflow.
 *
 * `conversation_id` is null when no conversation has been linked to the
 * workflow yet. `has_user_messages` lets the FE decide between auto-restore
 * (no current sidebar activity) and offering a pill. `active_generation_id`
 * + `has_pending_ask` lets the FE rehydrate an in-flight builder ask without
 * a separate round-trip.
 */
export interface LatestConversationForWorkflowEvent {
  /**
   * Request ID for correlation
   */
  request_id?: string | null;
  /**
   * Workflow ID this lookup was for
   */
  workflow_id: string;
  /**
   * Latest conversation ID for the workflow, or null
   */
  conversation_id?: string | null;
  /**
   * Whether the conversation has any user-authored messages
   */
  has_user_messages?: boolean;
  /**
   * ID of an active builder generation tied to this conversation, if any
   */
  active_generation_id?: string | null;
  /**
   * Whether the active generation is waiting on user input
   */
  has_pending_ask?: boolean;
}
/**
 * Canvas-update event sent to all of a user's connected frontends.
 *
 * Carries an ``event_type`` ("node_updated", "node_start", "edge_added", …)
 * plus an opaque ``data`` payload — the FE's useMCPBuilderEvents hook routes
 * each event_type through its renderer. Used by mcp_server's update_workflow
 * flow AND by the runtime auto-extend path (see utils/workflow_node_writeback)
 * to push runtime config mutations live to collaborators.
 */
export interface MCPBuilderEvent {
  /**
   * UUID of the workflow being mutated
   */
  workflow_id: string;
  /**
   * Builder event variant (e.g. 'node_updated')
   */
  event_type: string;
  /**
   * Per-event payload (nodeId, config, …)
   */
  data?: {
    [k: string]: unknown;
  };
}
/**
 * Live progress of a staged agent run.
 *
 * The rehearsal carries its own channel rather than borrowing the chat/
 * workflow relay plumbing: a rehearsal can be watched from a surface that never
 * opened the workflow (onboarding, a template preview), and those surfaces are
 * not in the workflow's room, so room-routed events never reach them.
 *
 * Every frame is explicitly ``rehearsed`` — the UI must never have to infer
 * whether what it is showing really happened.
 */
export interface RehearsalProgressEvent {
  /**
   * The rehearsal this frame belongs to
   */
  conversation_id: string;
  /**
   * 'step' | 'thought' | 'done' | 'failed'
   */
  kind: string;
  /**
   * Stable id so a completed frame updates its in-progress row
   */
  step_id?: string | null;
  /**
   * Tool the agent reached for, e.g. slack__send_message_to_channel
   */
  tool?: string | null;
  /**
   * 'in_progress' | 'completed' for a step frame
   */
  status?: string | null;
  /**
   * The message the agent actually composed for this call — what would have been posted or sent
   */
  outbound?: string | null;
  /**
   * What the agent called the tool with — real arguments, the agent's own judgment
   */
  args?: {
    [k: string]: unknown;
  } | null;
  result?: unknown;
  /**
   * What the agent said, on the final frame
   */
  reply?: string | null;
  /**
   * A slice of the agent's visible reasoning between tool calls, on a 'thought' frame
   */
  text?: string | null;
  /**
   * Why it stopped, when it did
   */
  error?: string | null;
  /**
   * Always true: the world was fabricated, only the agent was real
   */
  rehearsed?: boolean;
}
/**
 * Generic response event for correlated requests
 */
export interface ResponseEvent {
  /**
   * Correlation ID from request
   */
  request_id: string;
  /**
   * Response data
   */
  data: {
    [k: string]: unknown;
  };
  /**
   * Error message if failed
   */
  error?: string | null;
}
/**
 * Server-initiated data push event (no request correlation)
 */
export interface ServerDataEvent {
  /**
   * Type of data being pushed (e.g., 'databases', 'apps')
   */
  data_type: string;
  /**
   * The data being pushed
   */
  data: {
    [k: string]: unknown;
  };
  /**
   * Error message if failed
   */
  error?: string | null;
}
/**
 * Event emitted when a resource is shared with a user.
 *
 * This is a push notification sent to the target user (via Event Relay if needed)
 * when someone shares a workflow or database with them directly (1:1 email share).
 * Not sent for org-wide shares to avoid notification spam.
 */
export interface ShareNotificationEvent {
  /**
   * Type of resource shared (workflow, database)
   */
  resource_type: string;
  /**
   * UUID of the shared resource
   */
  resource_id: string;
  /**
   * Name of the shared resource
   */
  resource_name: string;
  /**
   * Permission level granted (view, edit)
   */
  permission: string;
  /**
   * Email of the user who shared
   */
  shared_by_email: string;
  /**
   * Display name of the user who shared
   */
  shared_by_name?: string | null;
  /**
   * UUID of the share for navigation
   */
  share_id: string;
}
/**
 * Event emitted when a workflow's persistent state is modified (for cross-client sync)
 */
export interface StateChangedEvent {
  /**
   * State key that was changed
   */
  key: string;
  /**
   * New value (None if deleted)
   */
  value?: {
    [k: string]: unknown;
  };
}
/**
 * Event emitted with aggregated usage data for dashboard visualization
 */
export interface UsageDataEvent {
  /**
   * Request ID for correlation
   */
  request_id?: string | null;
  /**
   * Total credits consumed for the queried period (handler converts $→credits at the wire boundary)
   */
  total_cost: number;
  /**
   * Credits breakdown by usage type (ai_usage, ai_builder, api_usage, etc.)
   */
  usage_by_type: {
    [k: string]: number;
  };
  /**
   * Credits breakdown by specific models/instances
   */
  usage_by_subtype: {
    [k: string]: number;
  };
  /**
   * Time series data for charting (date, credit totals, breakdown)
   */
  time_series: {
    [k: string]: unknown;
  }[];
  /**
   * User's current balance (legacy $ pool; preserved for compatibility, dashboard now shows credit pool from useCreditUsage)
   */
  current_balance: number;
  /**
   * Start of the queried period (ISO format)
   */
  period_start?: string | null;
  /**
   * End of the queried period (ISO format)
   */
  period_end?: string | null;
  /**
   * Error message if failed
   */
  error?: string | null;
}
/**
 * Event emitted when a new usage event occurs in real-time
 */
export interface UsageEventUpdateEvent {
  /**
   * Type of usage (ai_usage, ai_builder, api_usage, cpu_usage, gpu_usage)
   */
  usage_type: string;
  /**
   * Specific subtype (model name, instance type, etc.)
   */
  usage_subtype: string;
  /**
   * Credits consumed by this usage event (handler converts $→credits at the wire boundary; $ never leaves the backend)
   */
  total_cost: number;
  /**
   * Amount used (tokens, hours, etc.)
   */
  quantity: number;
  /**
   * Unit of measurement (tokens, cpu_hours, etc.)
   */
  unit_type: string;
  /**
   * DEPRECATED — legacy $ pool was retired in Phase 2.1; always 0
   */
  current_balance?: number;
  /**
   * Whether this was a user-provided resource
   */
  user_resource: boolean;
  /**
   * Unix timestamp when event occurred
   */
  timestamp?: number | null;
  /**
   * Org workspace this event belongs to; null means personal
   */
  organization_id?: string | null;
  /**
   * User whose credit pool was charged (org owner under the configured attribution policy)
   */
  billing_user_id?: string | null;
}
/**
 * Event emitted when entire workflow execution completes
 */
export interface WorkflowCompleteEvent {
  /**
   * Execution UUID for this workflow run
   */
  execution_id: string;
  /**
   * Workflow UUID that was executed
   */
  workflow_id: string;
  /**
   * Whether workflow completed successfully
   */
  success: boolean;
  /**
   * Number of nodes executed
   */
  nodes_executed: number;
  /**
   * Total execution time in seconds
   */
  duration: number;
  /**
   * Error message if workflow failed
   */
  error?: string | null;
  /**
   * True when the run did not finish but paused on a delay or approval node. The client shows the run as 'Waiting' rather than completed.
   */
  suspended?: boolean;
}
/**
 * Backend request for frontend workflow data or mutation.
 *
 * This enables bidirectional communication where the backend MCP handler
 * can request data from the frontend (e.g., selected node, node outputs)
 * or request mutations (e.g., add node, remove node).
 *
 * The frontend responds with a 'workflow:mcp:response' event containing
 * the same request_id for correlation.
 */
export interface WorkflowMCPRequestEvent {
  /**
   * Correlation ID for response matching
   */
  request_id: string;
  /**
   * Type of request: 'get_state', 'get_selected', 'get_output', 'get_input', 'add_node', 'remove_node'
   */
  request_type: string;
  /**
   * Request-specific parameters (e.g., node_id, node_type, config)
   */
  params?: {
    [k: string]: unknown;
  };
}
/**
 * Background-generated name for a newly created workflow.
 */
export interface WorkflowNameGeneratedEvent {
  workflow_id: string;
  name: string;
  description: string;
}
/**
 * Event emitted when a workflow node produces output. One emit per
 * execution: carries the canonical, final, structured output of the node.
 * Streaming progress goes through WorkflowNodeProgressEvent instead.
 */
export interface WorkflowNodeOutputEvent {
  /**
   * Workflow UUID containing the node
   */
  workflow_id: string;
  /**
   * ID of the node producing output
   */
  node_id: string;
  /**
   * Type of the node
   */
  node_type: string;
  /**
   * Output data with arbitrary metadata from the node
   */
  output: {
    [k: string]: unknown;
  };
}
/**
 * Live in-flight activity from a workflow node — separate from the
 * canonical WorkflowNodeOutputEvent.
 *
 * Why a separate event: previously, agent_node streamed chunks via
 * WorkflowNodeOutputEvent with type='chat_message', and per-node summary
 * emits (Jira's ``{"action": "list_boards", "count": 2}``) also rode the
 * canonical output channel. Both fought the final
 * ``{type:'agent', status:'completed'}`` emit for ownership of
 * node.data.output, so a late chunk or summary could overwrite the
 * canonical with a partial snippet.
 *
 * The progress slot is structurally race-free: progress writes here,
 * the canonical output writes to node.data.output and clears
 * node.data.progress. The two writers don't share storage.
 *
 * Two payload modes — exactly one of ``append`` or ``snapshot`` per
 * event:
 *   - ``append``: text fragment from a streaming source. The frontend
 *     concatenates it to ``node.data.progress.text``.
 *   - ``snapshot``: structured payload from a one-shot
 *     ``self.emit({...})`` call (e.g. ``{"action": "list_boards",
 *     "count": 2}``). The frontend replaces ``node.data.progress.snapshot``.
 */
export interface WorkflowNodeProgressEvent {
  /**
   * Workflow UUID containing the node
   */
  workflow_id: string;
  /**
   * ID of the node producing progress
   */
  node_id: string;
  /**
   * Type of the node
   */
  node_type: string;
  /**
   * Text fragment to append to node.data.progress.text. Set for streaming sources (agent text deltas).
   */
  append?: string | null;
  /**
   * Structured one-shot payload that replaces node.data.progress.snapshot. Set by self.emit({...}) callers.
   */
  snapshot?: {
    [k: string]: unknown;
  } | null;
}
/**
 * Event emitted when a workflow node changes state (idle/running/completed/error/skipped)
 */
export interface WorkflowNodeStateEvent {
  /**
   * Workflow UUID containing the node
   */
  workflow_id: string;
  /**
   * ID of the node
   */
  node_id: string;
  /**
   * Type of the node (e.g., 'automation-telegram', 'agent')
   */
  node_type: string;
  /**
   * Node state: 'idle', 'running', 'completed', 'error', 'skipped'
   */
  state: string;
  /**
   * Error message if state is 'error'
   */
  error?: string | null;
  /**
   * Execution UUID for state tracking across sessions
   */
  execution_id?: string | null;
  /**
   * The one thing the user can do about this error, for the UI to render as a button: {type, label, url?}. type is 'open_credentials' (open this node's Credentials tab) or 'open_url'. Absent when nothing useful can be clicked — a provider outage or rate limit is waited out, not acted on.
   */
  error_action?: {
    [k: string]: string;
  } | null;
}
/**
 * Event emitted when workflow execution starts
 */
export interface WorkflowStartedEvent {
  /**
   * Execution UUID for this workflow run
   */
  execution_id: string;
  /**
   * Workflow UUID being executed
   */
  workflow_id: string;
  /**
   * True when the run was triggered by an interface component fetching its own data (echoed from WorkflowExecuteRequest). The client uses this to keep the run out of the global Run/Stop button state.
   */
  background?: boolean;
  /**
   * True when this 'started' is the resumption of a run that was suspended on a delay or approval node. The client updates the existing run's log line in place rather than treating it as a new run.
   */
  resumed?: boolean;
}
/**
 * Event for YJS synchronization
 */
export interface YjsSyncEvent {
  /**
   * YJS sync binary data
   */
  data: string;
}

/* tslint:disable */
/* eslint-disable */
/**
/* This file was automatically generated from pydantic models by running pydantic2ts.
/* Do not modify it by hand - just update the pydantic models and then re-run the script
*/

/**
 * List recent activity log entries for the current user / org
 */
export interface ActivityListRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Maximum number of entries to return
   */
  limit?: number;
  [k: string]: unknown;
}
/**
 * The user's approve/dismiss verdict on an agent's prompt_builder proposal
 * card. Persisted as a conversation event so (a) the card's decided state
 * restores across devices/reloads and (b) the agent is told the outcome on
 * its next turn — without this the agent had no way to know the builder ran
 * and answered from its stale 'awaiting approval' tool result (2026-07-19).
 */
export interface AgentBuilderDecisionRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow containing the agent node
   */
  workflow_id: string;
  /**
   * Node id of the agent that proposed the edit
   */
  node_id?: string | null;
  /**
   * Conversation the proposal card lives in
   */
  conversation_id: string;
  /**
   * Server-minted id of the proposal being decided
   */
  proposal_id: string;
  /**
   * 'approved' or 'dismissed'
   */
  decision: string;
  [k: string]: unknown;
}
/**
 * Request from agent runtime to copy files from sandbox
 */
export interface AgentCopyFromRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Path in sandbox to copy from
   */
  path: string;
  [k: string]: unknown;
}
/**
 * Request from agent runtime to copy files to sandbox
 */
export interface AgentCopyToRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Base64 encoded file content
   */
  content: string;
  /**
   * Destination path in sandbox
   */
  dest_path: string;
  /**
   * Whether to extract as directory (if content is zip)
   */
  recursive?: boolean;
  [k: string]: unknown;
}
/**
 * Request from agent runtime to edit a file using OHEditor in sandbox
 */
export interface AgentEditFileRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * File path to edit
   */
  path: string;
  /**
   * Editor command (view, create, str_replace, etc.)
   */
  command: string;
  /**
   * Full file text for create command
   */
  file_text?: string | null;
  /**
   * String to replace for str_replace command
   */
  old_str?: string | null;
  /**
   * Replacement string for str_replace command
   */
  new_str?: string | null;
  /**
   * Line number for insert command
   */
  insert_line?: number | null;
  /**
   * Line range for view command
   */
  view_range?: number[] | null;
  [k: string]: unknown;
}
/**
 * Request from agent runtime to list files in sandbox
 */
export interface AgentListFilesRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Directory path to list (defaults to workspace root)
   */
  path?: string | null;
  [k: string]: unknown;
}
/**
 * Request to pause the active agent session
 */
export interface AgentPauseRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Conversation ID to target specific agent (defaults to sid)
   */
  conversation_id?: string | null;
  [k: string]: unknown;
}
/**
 * Request from agent runtime to read a file in sandbox
 */
export interface AgentReadFileRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * File path to read
   */
  path: string;
  [k: string]: unknown;
}
/**
 * Request from agent runtime to execute a command in sandbox
 */
export interface AgentRunCommandRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Bash command to execute
   */
  command: string;
  /**
   * Working directory for the command
   */
  cwd?: string | null;
  /**
   * Command timeout in seconds
   */
  timeout?: number | null;
  [k: string]: unknown;
}
/**
 * Request to update the agent's working directory
 */
export interface AgentSetCwdRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Absolute path within the mounted workspace
   */
  path: string;
  /**
   * Conversation ID to target specific agent (defaults to sid)
   */
  conversation_id?: string | null;
  /**
   * App ID if working within an app context
   */
  app_id?: string | null;
  /**
   * App name if working within an app context
   */
  app_name?: string | null;
  [k: string]: unknown;
}
/**
 * Mint (or fetch) the shareable public chat link for an agent node.
 * Owner-only: the link bills the owner's credits and exposes the agent's
 * tools (owner credentials) to anyone with the URL.
 */
export interface AgentShareGetOrCreateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow containing the agent node
   */
  workflow_id: string;
  /**
   * Node id of the agent within the workflow
   */
  node_id: string;
  [k: string]: unknown;
}
/**
 * Replace the capability URL for an agent node's share link. The old
 * link 404s immediately. Owner-only.
 */
export interface AgentShareRotateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow containing the agent node
   */
  workflow_id: string;
  /**
   * Node id of the agent within the workflow
   */
  node_id: string;
  [k: string]: unknown;
}
/**
 * Enable/disable an agent share link without changing the URL. Owner-only.
 */
export interface AgentShareSetActiveRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow containing the agent node
   */
  workflow_id: string;
  /**
   * Node id of the agent within the workflow
   */
  node_id: string;
  /**
   * Whether the link should accept visitors
   */
  is_active: boolean;
  [k: string]: unknown;
}
/**
 * Delete one file from an agent conversation's workspace volume.
 * Requires edit or owner access to the workflow.
 */
export interface AgentWorkspaceDeleteRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow containing the agent node
   */
  workflow_id: string;
  /**
   * Node id of the agent within the workflow
   */
  node_id: string;
  /**
   * Conversation key whose workspace volume to delete from
   */
  conversation_key?: string | null;
  /**
   * Volume-relative path of the file to delete
   */
  path: string;
  [k: string]: unknown;
}
/**
 * List the files on an agent conversation's persistent workspace volume
 * (the chat's file view). Requires workflow access — the same audience the
 * agent chat itself serves. Response carries per-file signed streaming URLs.
 */
export interface AgentWorkspaceListRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow containing the agent node
   */
  workflow_id: string;
  /**
   * Node id of the agent within the workflow
   */
  node_id: string;
  /**
   * Conversation key whose workspace volume to list
   */
  conversation_key?: string | null;
  [k: string]: unknown;
}
/**
 * Request from agent runtime to write a file in sandbox
 */
export interface AgentWriteFileRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * File path to write
   */
  path: string;
  /**
   * Content to write to the file
   */
  content: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential (uses PKCE)
 */
export interface AirtableOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Airtable OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * PKCE code verifier used during authorization
   */
  code_verifier: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired Airtable OAuth token
 */
export interface AirtableOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if an Airtable OAuth token is still valid
 */
export interface AirtableOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface ApolloOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Apollo OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization (must match)
   */
  redirect_uri: string;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired Apollo OAuth token
 */
export interface ApolloOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if an Apollo OAuth token is still valid
 */
export interface ApolloOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * List pending approval requests for the current user / org
 */
export interface ApprovalListRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  [k: string]: unknown;
}
/**
 * Approve or reject an approval request, resuming workflow execution
 */
export interface ApprovalRespondRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the approval request
   */
  approval_id: string;
  /**
   * Decision: 'approved' or 'rejected'
   */
  decision: string;
  /**
   * Edited form field values (optional, overrides original values)
   */
  values?: {
    [k: string]: unknown;
  } | null;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface AsanaOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Asana OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * OAuth scopes that were requested
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired Asana OAuth token (access tokens expire after 1 hour)
 */
export interface AsanaOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if an Asana OAuth token is still valid
 */
export interface AsanaOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as Jira credential
 */
export interface AtlassianOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Atlassian OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  /**
   * Requested Jira site URL or subdomain
   */
  jira_site?: string | null;
  [k: string]: unknown;
}
/**
 * Refresh an expired Atlassian/Jira OAuth token
 */
export interface AtlassianOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if an Atlassian/Jira OAuth token is still valid
 */
export interface AtlassianOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface AttioOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Attio OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * OAuth scopes that were requested
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh an Attio OAuth token (tokens are long-lived; rarely needed)
 */
export interface AttioOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if an Attio OAuth token is still valid
 */
export interface AttioOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface BambooHROAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from BambooHR OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * BambooHR company subdomain that scopes the OAuth host
   */
  subdomain: string;
  /**
   * OAuth scopes that were requested
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired BambooHR OAuth token
 */
export interface BambooHROAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a BambooHR OAuth token is still valid
 */
export interface BambooHROAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface BoxOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Box OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * OAuth scopes that were requested
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired Box OAuth token (access tokens expire after ~60 minutes)
 */
export interface BoxOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Box OAuth token is still valid
 */
export interface BoxOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface CalComOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Cal.com OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * OAuth scopes that were requested
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired Cal.com OAuth token (30-minute access tokens)
 */
export interface CalComOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  [k: string]: unknown;
}
/**
 * Validate if a Cal.com OAuth token is still valid
 */
export interface CalComOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface CalendlyOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Calendly OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * OAuth scopes that were requested
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired Calendly OAuth token (access tokens expire after ~2 hours)
 */
export interface CalendlyOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Calendly OAuth token is still valid
 */
export interface CalendlyOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential (uses PKCE)
 */
export interface CanvaOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Canva OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * PKCE code verifier used during authorization
   */
  code_verifier: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired Canva OAuth token
 */
export interface CanvaOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Canva OAuth token is still valid
 */
export interface CanvaOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Context information sent with each chat message to ensure accurate workspace targeting.
 */
export interface ChatMessageContext {
  /**
   * Current app ID the user is viewing/editing
   */
  app_id?: string | null;
  /**
   * Current app name for display purposes
   */
  app_name?: string | null;
  /**
   * Active workflow ID — stamped on the conversation row so the sidebar can later auto-restore the latest conversation per workflow
   */
  workflow_id?: string | null;
}
/**
 * Request sent when user sends a chat message
 */
export interface ChatMessageRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Conversation session ID for associating messages with specific conversation context
   */
  conversation_id?: string | null;
  /**
   * Sequence-sensitive content items
   */
  content: ContentItem[];
  /**
   * Model to use for this request (e.g., 'gpt-4o', 'claude-3-sonnet')
   */
  model: string;
  /**
   * Environment variables for model configuration (e.g., API keys)
   */
  env?: {
    [k: string]: string;
  } | null;
  /**
   * Message context including current app info for accurate cwd targeting
   */
  context?: ChatMessageContext | null;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens
 */
export interface ClaudeCodeAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Session ID from start response
   */
  auth_session_id: string;
  /**
   * Authorization code pasted by user
   */
  authorization_code: string;
  /**
   * Optional name for the credential
   */
  credential_name?: string | null;
  [k: string]: unknown;
}
/**
 * Initiate the Claude Code OAuth PKCE flow
 */
export interface ClaudeCodeAuthStartRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface ClickUpOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from ClickUp OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * OAuth scopes (ClickUp has none)
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh a ClickUp OAuth token (ClickUp tokens do not expire; no-op parity)
 */
export interface ClickUpOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a ClickUp OAuth token is still valid
 */
export interface ClickUpOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Base class for client events with optional request correlation
 */
export interface ClientEventBase {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for Cloudflare tokens and store as credential
 */
export interface CloudflareOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Cloudflare OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * OAuth scopes that were requested
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired Cloudflare OAuth access token
 */
export interface CloudflareOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Cloudflare OAuth token is still valid
 */
export interface CloudflareOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Poll the device code token endpoint to check if the user has approved
 */
export interface CodexDeviceCodePollRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Device auth session ID from start response
   */
  device_auth_id: string;
  /**
   * User code from start response
   */
  user_code: string;
  /**
   * Name for the credential if approved
   */
  credential_name?: string | null;
  [k: string]: unknown;
}
/**
 * Initiate the Codex device code OAuth flow to connect a ChatGPT account
 */
export interface CodexDeviceCodeStartRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  [k: string]: unknown;
}
/**
 * Fired when the OWNER explicitly selects a credential on a node, to authorize it
 * for run-as-owner resolution on this workflow. Owner-gated server-side: a
 * collaborator's call is a no-op (they can't introduce an owner credential). This is
 * the trustworthy authorization signal for the collaborative frontend — credentialIds
 * in the blob/autosave aren't trusted because a collaborator can inject them via the
 * presence channel.
 */
export interface CredentialAuthorizeForWorkflowRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Workflow the credential is being authorized for
   */
  workflow_id: string;
  /**
   * The credential the owner just placed on a node
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Request to create a new encrypted credential
 */
export interface CredentialCreateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Human-readable name for the credential
   */
  name: string;
  /**
   * Type: 'oauth', 'api_key', 'database', 'third_party'
   */
  credential_type: string;
  /**
   * Credential data to be encrypted
   */
  credential_data: {
    [k: string]: unknown;
  };
  /**
   * Optional metadata (provider, service URL, etc.)
   */
  metadata?: {
    [k: string]: unknown;
  } | null;
  [k: string]: unknown;
}
/**
 * Request to delete a credential
 */
export interface CredentialDeleteRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to delete
   */
  credential_id: string;
  /**
   * False = dry run: return the workflows referencing this credential without deleting. True = deregister dependent trigger webhooks and delete.
   */
  confirm?: boolean;
  [k: string]: unknown;
}
/**
 * Request display-only metadata (name, type, owner) for the credentials a
 * workflow's nodes reference. Gated by workflow access — returns NO secret and
 * grants NO access; lets collaborators see the name + owner of credentials the
 * flow uses (which are resolved as the owner at execution).
 */
export interface CredentialDisplayInfoRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Workflow whose node credentials to describe
   */
  workflow_id: string;
  [k: string]: unknown;
}
/**
 * Request to get a specific credential by ID (returns decrypted data)
 */
export interface CredentialGetRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to retrieve
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Request to list all credentials owned by the current user
 */
export interface CredentialListRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  [k: string]: unknown;
}
/**
 * Request to cancel a pending credential request
 */
export interface CredentialRequestCancelRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential request to cancel
   */
  credential_request_id: string;
  [k: string]: unknown;
}
/**
 * Request to create a credential request and send email to target
 */
export interface CredentialRequestCreateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Email of the person to request credentials from. Empty for a shareable copy-link request (no email is sent).
   */
  target_email?: string;
  /**
   * Credential type to request (e.g. 'google_sheets_oauth', 'openai_api_key')
   */
  credential_type: string;
  /**
   * Optional message to include in the request email
   */
  message?: string | null;
  /**
   * Frontend URL for constructing the provision link
   */
  frontend_url?: string | null;
  [k: string]: unknown;
}
/**
 * Request to list all outgoing credential requests for the current user
 */
export interface CredentialRequestListRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  [k: string]: unknown;
}
/**
 * Ask a provider to prove a credential works, in terms a human recognises.
 *
 * Answers "is this really connected?" with the user's own channels or repos
 * rather than a tick, and — when the probe went through a config field's own
 * options loader — returns values that can fill that field directly, so the
 * proof doubles as the picker.
 */
export interface CredentialTestConnectionRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Type of the node whose credential is being proven (e.g. 'automation-slack')
   */
  node_type: string;
  /**
   * UUID of the credential to prove
   */
  credential_id: string;
  /**
   * Organization the work is billed to, when the node is org-scoped
   */
  organization_id?: string | null;
  /**
   * Workflow the credential is attached to, for the owner-fallback resolution
   */
  workflow_id?: string | null;
  [k: string]: unknown;
}
/**
 * Request to update a credential
 */
export interface CredentialUpdateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to update
   */
  credential_id: string;
  /**
   * New name for the credential
   */
  name?: string | null;
  /**
   * New credential data to be encrypted
   */
  credential_data?: {
    [k: string]: unknown;
  } | null;
  /**
   * New metadata
   */
  metadata?: {
    [k: string]: unknown;
  } | null;
  [k: string]: unknown;
}
/**
 * Post-connect API access validation for credentials that require it (e.g. GBP).
 */
export interface CredentialValidateAccessRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the newly created credential to validate
   */
  credential_id: string;
  /**
   * Node type to look up the validate_credential_access classmethod
   */
  node_type: string;
  [k: string]: unknown;
}
/**
 * Request to delete a conversation and all its data
 */
export interface DeleteConversationRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Conversation ID to delete
   */
  conversation_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface DiscordOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Discord OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired Discord OAuth token
 */
export interface DiscordOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Discord OAuth token is still valid
 */
export interface DiscordOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface DropboxOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Dropbox OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired Dropbox OAuth token
 */
export interface DropboxOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Dropbox OAuth token is still valid
 */
export interface DropboxOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential (Instagram via Facebook)
 */
export interface FacebookOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Facebook OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  /**
   * When multiple accounts exist, the instagram_user_id the user selected
   */
  selected_instagram_user_id?: string | null;
  /**
   * Opaque key returned in a needs_selection response; reuse to complete selection
   */
  pending_selection_key?: string | null;
  [k: string]: unknown;
}
/**
 * Refresh a Facebook/Instagram OAuth token (long-lived tokens last 60 days)
 */
export interface FacebookOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Facebook/Instagram OAuth token is still valid
 */
export interface FacebookOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth code for a Facebook (Pages) credential
 */
export interface FacebookPagesOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Facebook OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * OAuth scopes that were requested
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh a Facebook Pages OAuth token
 */
export interface FacebookPagesOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate a Facebook Pages OAuth token
 */
export interface FacebookPagesOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential.
 */
export interface FathomOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Fathom OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired Fathom OAuth token.
 */
export interface FathomOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Fathom OAuth token is still valid.
 */
export interface FathomOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Request to create a new workflow folder
 */
export interface FolderCreateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Folder name
   */
  name: string;
  /**
   * Folder description
   */
  description?: string | null;
  /**
   * Parent folder UUID (null for root)
   */
  parent_folder_id?: string | null;
  [k: string]: unknown;
}
/**
 * Request to delete a folder
 */
export interface FolderDeleteRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Folder UUID
   */
  folder_id: string;
  [k: string]: unknown;
}
/**
 * Request to get breadcrumb path for a folder
 */
export interface FolderGetPathRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Folder UUID
   */
  folder_id: string;
  [k: string]: unknown;
}
/**
 * Request to get a specific folder
 */
export interface FolderGetRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Folder UUID
   */
  folder_id: string;
  [k: string]: unknown;
}
/**
 * Request to get complete folder tree for sidebar
 */
export interface FolderGetTreeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Explicit org scope: '' = personal, '<uuid>' = that org, null = use the active (is_primary) context. The browser sends its own scope so the response can't be mismatched by the org-switch race.
   */
  scope_org_id?: string | null;
  [k: string]: unknown;
}
/**
 * Request to list folders
 */
export interface FolderListRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Parent folder UUID to filter by (null for root)
   */
  parent_folder_id?: string | null;
  /**
   * Include workflow count in response
   */
  include_workflows?: boolean;
  [k: string]: unknown;
}
/**
 * Request to update a folder (rename or move)
 */
export interface FolderUpdateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Folder UUID
   */
  folder_id: string;
  /**
   * New folder name
   */
  name?: string | null;
  /**
   * New folder description
   */
  description?: string | null;
  /**
   * New parent folder UUID (to move folder)
   */
  parent_folder_id?: string | null;
  [k: string]: unknown;
}
/**
 * Request the most-recently-active conversation tied to a given workflow.
 *
 * Used by the sidebar on workflow open to decide between auto-restoring the
 * last conversation (when the current sidebar is empty) and offering a
 * "Resume previous" pill (when it isn't).
 */
export interface GetLatestConversationForWorkflowRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow whose latest conversation to fetch
   */
  workflow_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface GitLabOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from GitLab OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * OAuth scopes that were requested
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired GitLab OAuth token (access tokens expire after 2 hours)
 */
export interface GitLabOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a GitLab OAuth token is still valid
 */
export interface GitLabOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface GithubOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from GitHub OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired GitHub OAuth token (only if expiring tokens enabled)
 */
export interface GithubOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a GitHub OAuth token is still valid
 */
export interface GithubOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface GoogleOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Google OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  /**
   * BYOO OAuth client ID
   */
  custom_client_id?: string | null;
  /**
   * BYOO OAuth client secret
   */
  custom_client_secret?: string | null;
  [k: string]: unknown;
}
/**
 * Refresh an expired OAuth token
 */
export interface GoogleOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if an OAuth token is still valid
 */
export interface GoogleOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface HubSpotOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from HubSpot OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired HubSpot OAuth token
 */
export interface HubSpotOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a HubSpot OAuth token is still valid
 */
export interface HubSpotOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface InstagramLoginOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Instagram Login OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * OAuth scopes that were requested
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh a long-lived Instagram Login OAuth token
 */
export interface InstagramLoginOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if an Instagram Login OAuth token is still valid
 */
export interface InstagramLoginOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Forget one server-side provider key
 */
export interface InstanceKeysDeleteRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Environment variable name
   */
  env_var: string;
  [k: string]: unknown;
}
/**
 * List the model-provider keys this instance has stored server-side
 */
export interface InstanceKeysListRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  [k: string]: unknown;
}
/**
 * Store one server-side provider key (e.g. OPENROUTER_API_KEY)
 */
export interface InstanceKeysSetRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Environment variable name the key is read from
   */
  env_var: string;
  /**
   * The key
   */
  value: string;
  [k: string]: unknown;
}
/**
 * Forget one provider's OAuth app
 */
export interface InstanceOAuthDeleteRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Provider key, e.g. 'linear'
   */
  provider: string;
  [k: string]: unknown;
}
/**
 * List the providers this instance has an OAuth app configured for
 */
export interface InstanceOAuthListRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  [k: string]: unknown;
}
/**
 * Store one provider's OAuth app (client id, and optionally its secret)
 */
export interface InstanceOAuthSetRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Provider key, e.g. 'linear'
   */
  provider: string;
  /**
   * OAuth app client id
   */
  client_id: string;
  /**
   * OAuth app client secret; omit to leave a stored one unchanged
   */
  client_secret?: string | null;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface IntercomOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Intercom OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * Data residency region for the workspace (us/eu/au)
   */
  region?: string;
  /**
   * OAuth scopes the app was granted
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh an Intercom OAuth token (no-op: Intercom tokens are long-lived)
 */
export interface IntercomOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if an Intercom OAuth credential is still valid
 */
export interface IntercomOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential (uses PKCE)
 */
export interface KlaviyoOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Klaviyo OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * PKCE code verifier used during authorization
   */
  code_verifier: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  /**
   * OAuth scopes that were requested
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired Klaviyo OAuth token
 */
export interface KlaviyoOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Klaviyo OAuth token is still valid
 */
export interface KlaviyoOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface LinearOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Linear OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * OAuth scopes that were requested
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired Linear OAuth token (rarely needed, tokens last 10 years)
 */
export interface LinearOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Linear OAuth token is still valid
 */
export interface LinearOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface LinkedInOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from LinkedIn OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization (must match)
   */
  redirect_uri: string;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired LinkedIn OAuth token
 */
export interface LinkedInOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a LinkedIn OAuth token is still valid
 */
export interface LinkedInOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * List every conversation owned by the current user that's scoped to a
 * specific agent node (workflow_id + node_id). Powers the per-agent chat
 * history list in the Interface-tab AgentChatBlock.
 */
export interface ListConversationsForAgentRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow containing the agent
   */
  workflow_id: string;
  /**
   * Node id of the agent within the workflow
   */
  node_id: string;
  [k: string]: unknown;
}
/**
 * Request to list all available conversation sessions
 */
export interface ListConversationsRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  [k: string]: unknown;
}
/**
 * List builder runs currently paused on an <ask/> for the current user.
 * Used by the pending-runs indicator so a user can find and resume runs
 * that paused days earlier (e.g., while they went to fetch API keys).
 */
export interface ListPendingBuilderRunsRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Scope results to this workflow. If omitted, returns all pending runs for the user.
   */
  workflow_id?: string | null;
  [k: string]: unknown;
}
/**
 * MCP tool request to get the complete folder tree.
 *
 * Returns all folders the user has access to in a hierarchical tree structure
 * with workflow counts per folder.
 */
export interface MCPFolderGetTreeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  [k: string]: unknown;
}
/**
 * Discover OAuth requirements for an MCP server URL
 */
export interface MCPOAuthDiscoverRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * URL of the MCP server endpoint
   */
  server_url: string;
  [k: string]: unknown;
}
/**
 * Exchange authorization code for tokens and store as credential
 */
export interface MCPOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from OAuth callback
   */
  code: string;
  /**
   * PKCE code verifier
   */
  code_verifier: string;
  /**
   * Token endpoint URL
   */
  token_endpoint: string;
  /**
   * OAuth client ID
   */
  client_id: string;
  /**
   * Redirect URI used in authorization
   */
  redirect_uri: string;
  /**
   * MCP server URL for resource indicator
   */
  resource_url?: string | null;
  /**
   * MCP server URL for credential naming
   */
  server_url: string;
  /**
   * Provider name for credential
   */
  provider_name?: string | null;
  /**
   * Custom credential name
   */
  credential_name?: string | null;
  [k: string]: unknown;
}
/**
 * Register a dynamic OAuth client with an MCP server
 */
export interface MCPOAuthRegisterClientRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Client registration endpoint URL
   */
  registration_endpoint: string;
  /**
   * Name for the OAuth client
   */
  client_name?: string;
  /**
   * Redirect URIs for the client
   */
  redirect_uris: string[];
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface MailchimpOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Mailchimp OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface MetaOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Meta OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * OAuth scopes that were requested
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh a long-lived Meta OAuth token
 */
export interface MetaOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Meta OAuth token is still valid
 */
export interface MetaOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface MicrosoftOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Microsoft OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired Microsoft OAuth token
 */
export interface MicrosoftOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Microsoft OAuth token is still valid
 */
export interface MicrosoftOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface MondayOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from monday OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * OAuth scopes that were requested
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh a monday OAuth token (used when an app is configured with rotation)
 */
export interface MondayOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a monday OAuth token is still valid
 */
export interface MondayOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Request to fetch the expected output schema for a node type and operation.
 *
 * Used by the workflow builder UI to show users what fields will be available
 * from a node before they run it, enabling drag-and-drop configuration.
 */
export interface NodeOutputSchemaRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Node type, e.g., 'automation-google-sheets'
   */
  node_type: string;
  /**
   * Operation within the node, e.g., 'get_rows', 'send_message'
   */
  node_operation: string;
  [k: string]: unknown;
}
/**
 * Request the user's notification email preferences
 */
export interface NotificationPrefsGetRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  [k: string]: unknown;
}
/**
 * Update one or more notification email categories (partial merge)
 */
export interface NotificationPrefsUpdateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Category → enabled, e.g. {'run_failure': false}
   */
  prefs: {
    [k: string]: boolean;
  };
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface NotionOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Notion OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  [k: string]: unknown;
}
/**
 * Refresh an expired Notion OAuth token
 */
export interface NotionOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Notion OAuth token is still valid
 */
export interface NotionOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Request to get user's onboarding completion state
 */
export interface OnboardingCompletionGetRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  [k: string]: unknown;
}
/**
 * Request to update user's onboarding completion state
 */
export interface OnboardingCompletionUpdateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Partial update to merge with existing completion data
   */
  data: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
/**
 * Persist an onboarding skip server-side (scaffold / agent-SEO arrivals).
 *
 * Writes a `user_onboarding_responses` row so the `onboarding_completed` JWT
 * claim flips true durably — otherwise these users defer onboarding only via a
 * session-only sessionStorage flag and get re-prompted on the next dashboard
 * remount. Mirrors the invite-join path's server-side onboarding write.
 */
export interface OnboardingSkipRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * What deferred onboarding (e.g. 'scaffold')
   */
  source?: string;
  [k: string]: unknown;
}
/**
 * Request to submit onboarding questionnaire responses
 */
export interface OnboardingSubmitRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * User's questionnaire responses as key-value pairs
   */
  responses: {
    [k: string]: unknown;
  };
  /**
   * Questionnaire version for tracking schema changes
   */
  version?: number;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface PagerDutyOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from PagerDuty OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * OAuth scopes that were requested
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired PagerDuty OAuth token
 */
export interface PagerDutyOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a PagerDuty OAuth token is still valid
 */
export interface PagerDutyOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange Parallel OAuth authorization code for API key (PKCE flow).
 */
export interface ParallelOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Parallel OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * PKCE code verifier used during authorization
   */
  code_verifier: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  [k: string]: unknown;
}
/**
 * Validate if a stored Parallel API key is still active.
 */
export interface ParallelOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface PipedriveOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Pipedrive OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * OAuth scopes that were requested
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired Pipedrive OAuth token (access tokens expire after 60 minutes)
 */
export interface PipedriveOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Pipedrive OAuth token is still valid
 */
export interface PipedriveOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code (+ PKCE verifier) for tokens and store as credential
 */
export interface PostHogOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from PostHog OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * PKCE code verifier generated at authorize time
   */
  code_verifier: string;
  /**
   * OAuth scopes that were requested
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired PostHog OAuth token (access tokens last ~10h; refresh rotates)
 */
export interface PostHogOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a PostHog OAuth token is still valid
 */
export interface PostHogOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface QuickBooksOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from QuickBooks OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * QuickBooks company (realm) ID returned at OAuth time
   */
  realm_id: string;
  /**
   * Whether to use the QuickBooks sandbox host
   */
  is_sandbox?: boolean;
  /**
   * OAuth scopes that were requested
   */
  scopes?: string[];
  /**
   * Optional custom Intuit OAuth client ID
   */
  client_id?: string | null;
  /**
   * Optional custom Intuit OAuth client secret
   */
  client_secret?: string | null;
  [k: string]: unknown;
}
/**
 * Refresh an expired QuickBooks OAuth token (access tokens expire after 1 hour)
 */
export interface QuickBooksOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a QuickBooks OAuth token is still valid
 */
export interface QuickBooksOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface RedditOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Reddit OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired Reddit OAuth token
 */
export interface RedditOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Reddit OAuth token is still valid
 */
export interface RedditOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Run this workflow's agent for real against a fabricated world.
 *
 * Nothing outward happens: every tool call is answered by a mock session, so
 * no credential is resolved and no provider request is made. It demonstrates
 * behaviour and proves nothing about connectivity — that is what
 * credential:test_connection is for, and the UI must not conflate them.
 */
export interface RehearsalRunRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Workflow whose agent is being rehearsed
   */
  workflow_id: string;
  /**
   * Slug of the staged situation to run against
   */
  scenario?: string;
  /**
   * Builder edits to the staged message, in lead terms (title/body/author/handle). Applied to the provider payload server-side so the edited event is what actually runs.
   */
  lead_patch?: {
    [k: string]: string;
  } | null;
  [k: string]: unknown;
}
/**
 * List the staged situations this workflow can rehearse.
 *
 * Derived from the saved graph: a situation is offered only when the workflow
 * contains a trigger node of the type its payload is shaped for, so the Test
 * screen's pickers are real controls fed by real data — never a menu of runs
 * that would fail on click.
 */
export interface RehearsalScenariosRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Workflow whose rehearsable situations are being listed
   */
  workflow_id: string;
  [k: string]: unknown;
}
/**
 * Create a new workflow resource (dataset, file, image, etc.)
 */
export interface ResourceCreateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the parent workflow
   */
  workflow_id: string;
  /**
   * Type: dataset, file, image, video, audio, document
   */
  resource_type: string;
  /**
   * Display name for the resource
   */
  name: string;
  /**
   * Workflow node that produced this resource
   */
  node_id?: string | null;
  /**
   * MIME type for blob resources
   */
  mime_type?: string | null;
  /**
   * File size in bytes
   */
  size_bytes?: number | null;
  /**
   * R2 storage key (if already uploaded)
   */
  storage_ref?: string | null;
  /**
   * Arbitrary metadata
   */
  metadata?: {
    [k: string]: unknown;
  } | null;
  [k: string]: unknown;
}
/**
 * Append rows to a dataset resource
 */
export interface ResourceDatasetAppendRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the dataset resource
   */
  resource_id: string;
  /**
   * List of row data dicts to append
   */
  rows: {
    [k: string]: unknown;
  }[];
  [k: string]: unknown;
}
/**
 * Delete rows from a dataset resource
 */
export interface ResourceDatasetDeleteRowsRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the dataset resource
   */
  resource_id: string;
  /**
   * List of row UUIDs to delete
   */
  row_ids: string[];
  [k: string]: unknown;
}
/**
 * Get paginated rows from a dataset resource
 */
export interface ResourceDatasetRowsRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the dataset resource
   */
  resource_id: string;
  /**
   * Max rows to return
   */
  limit?: number;
  /**
   * Pagination offset
   */
  offset?: number;
  [k: string]: unknown;
}
/**
 * Update a single row in a dataset resource
 */
export interface ResourceDatasetUpdateRowRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the dataset resource
   */
  resource_id: string;
  /**
   * UUID of the row to update
   */
  row_id: string;
  /**
   * New data for the row
   */
  data: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
/**
 * Delete a workflow resource
 */
export interface ResourceDeleteRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the resource to delete
   */
  resource_id: string;
  [k: string]: unknown;
}
/**
 * Get a presigned download URL for a blob resource
 */
export interface ResourceDownloadUrlRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the resource
   */
  resource_id: string;
  [k: string]: unknown;
}
/**
 * Request to fork a resource (workflow or database) to a new location.
 * Creates an independent copy that the user owns or has edit access to.
 */
export interface ResourceForkRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Type of resource to fork
   */
  resource_type: "workflow" | "database";
  /**
   * UUID of the resource to fork
   */
  resource_id: string;
  /**
   * Where to create the fork
   */
  destination_type: "personal" | "organization";
  /**
   * Target organization ID (required if destination_type is 'organization')
   */
  destination_org_id?: string | null;
  /**
   * Optional new name for the forked resource (defaults to 'Copy of {original}')
   */
  new_name?: string | null;
  /**
   * For databases: whether to copy the actual data rows (not just schema)
   */
  include_data?: boolean;
  [k: string]: unknown;
}
/**
 * Get a single workflow resource by ID
 */
export interface ResourceGetRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the resource
   */
  resource_id: string;
  [k: string]: unknown;
}
/**
 * List workflow resources with optional filters
 */
export interface ResourceListRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Filter by workflow UUID
   */
  workflow_id?: string | null;
  /**
   * Filter by resource type
   */
  resource_type?: string | null;
  /**
   * Max results to return
   */
  limit?: number;
  /**
   * Pagination offset
   */
  offset?: number;
  [k: string]: unknown;
}
/**
 * Get a presigned upload URL for a blob resource
 */
export interface ResourceUploadUrlRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the resource
   */
  resource_id: string;
  /**
   * Original filename
   */
  filename: string;
  /**
   * MIME type of the file
   */
  content_type?: string;
  [k: string]: unknown;
}
/**
 * Request to resume a specific conversation session
 */
export interface ResumeConversationRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Session ID to resume
   */
  session_id: string;
  [k: string]: unknown;
}
/**
 * Mint a public read-only link (/r/{id}) for a finished Test Run. The
 * snapshot is the render bundle the sharer watched — a static page, nothing
 * executes and nothing bills. Owner-only, matching the other public share
 * capabilities.
 */
export interface RunShareCreateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow the run belongs to
   */
  workflow_id: string;
  /**
   * Display title (the situation's name)
   */
  title?: string;
  /**
   * Finished-run render bundle (display fields only)
   */
  snapshot: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface SalesforceOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Salesforce OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  /**
   * Whether this is a Salesforce sandbox org
   */
  is_sandbox?: boolean;
  /**
   * PKCE code verifier for token exchange
   */
  code_verifier?: string | null;
  [k: string]: unknown;
}
/**
 * Refresh an expired Salesforce OAuth token
 */
export interface SalesforceOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Salesforce OAuth token is still valid
 */
export interface SalesforceOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Request to save output data for reuse
 */
export interface SavedOutputCreateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Type of the node (e.g., 'automation-telegram', 'agent')
   */
  node_type: string;
  /**
   * User-provided readable name for this saved output
   */
  name: string;
  /**
   * The output data to save
   */
  output: {
    [k: string]: unknown;
  };
  /**
   * Visibility level: 'user', 'organization', or 'public'
   */
  visibility?: string;
  [k: string]: unknown;
}
/**
 * Request to delete a saved output
 */
export interface SavedOutputDeleteRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the saved output to delete
   */
  saved_output_id: string;
  [k: string]: unknown;
}
/**
 * Request to get a specific saved output by ID
 */
export interface SavedOutputGetRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the saved output to retrieve
   */
  saved_output_id: string;
  [k: string]: unknown;
}
/**
 * Request to list saved outputs for a specific node type
 */
export interface SavedOutputListRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Type of the node to get saved outputs for
   */
  node_type: string;
  [k: string]: unknown;
}
/**
 * Request to update a saved output's name or visibility
 */
export interface SavedOutputUpdateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the saved output to update
   */
  saved_output_id: string;
  /**
   * New name for the saved output
   */
  name?: string | null;
  /**
   * New visibility level
   */
  visibility?: string | null;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface SentryOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Sentry OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * OAuth scopes that were requested
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired Sentry OAuth token
 */
export interface SentryOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Sentry OAuth token is still valid
 */
export interface SentryOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Mint (or reuse) a public input-bridge link for the caller's builder run
 * currently paused on an <ask/> — the drawer's share button. Anyone holding
 * the returned /b/{id} URL can answer the questions / connect credentials
 * without a NoClick account; submitting resumes the run as the caller.
 */
export interface ShareBuilderAskRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Builder conversation paused on the ask
   */
  conversation_id: string;
  /**
   * The pending ask being shared
   */
  ask_id: string;
  [k: string]: unknown;
}
/**
 * Request to share a resource with a user (by email), organization, or make public
 */
export interface ShareCreateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Type of resource being shared
   */
  resource_type: "workflow" | "workflow_folder" | "database" | "credential" | "saved_output" | "skill";
  /**
   * UUID of the resource to share
   */
  resource_id: string;
  /**
   * Share with a user, organization, or make publicly accessible
   */
  target_type: "user" | "organization" | "public";
  /**
   * Email of user to share with (required if target_type='user')
   */
  target_email?: string | null;
  /**
   * Organization ID to share with (required if target_type='organization')
   */
  target_org_id?: string | null;
  /**
   * Permission level to grant (public shares are always 'view')
   */
  permission?: "view" | "edit";
  [k: string]: unknown;
}
/**
 * Request to remove a share
 */
export interface ShareDeleteRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the share to delete
   */
  share_id: string;
  [k: string]: unknown;
}
/**
 * Request to redeem a workflow invite link, granting the current user
 * collaborator access to the linked workflow.
 */
export interface ShareInviteAcceptRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Invite link token to redeem
   */
  token: string;
  [k: string]: unknown;
}
/**
 * Request to mint (or fetch the existing) shareable collaboration invite link for a workflow.
 *
 * Owner-only and personal-workflow-only. Returns a durable token; anyone who
 * opens /i/<token> and authenticates is added as an 'edit' collaborator on the
 * SAME workflow (not a fork).
 */
export interface ShareInviteLinkRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow to create/fetch an invite link for
   */
  workflow_id: string;
  [k: string]: unknown;
}
/**
 * Request for the current user to drop their OWN access to a resource shared
 * with them (self-service unshare). Unlike share:delete this needs no share_id
 * and no manage-shares permission — you can always remove your own access.
 */
export interface ShareLeaveRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Type of shared resource to leave
   */
  resource_type: "workflow" | "workflow_folder" | "database" | "credential" | "saved_output" | "skill";
  /**
   * UUID of the resource to remove the caller's own share for
   */
  resource_id: string;
  [k: string]: unknown;
}
/**
 * Request to list all shares for a resource
 */
export interface ShareListRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Type of resource
   */
  resource_type: "workflow" | "workflow_folder" | "database" | "credential" | "saved_output" | "skill";
  /**
   * UUID of the resource
   */
  resource_id: string;
  [k: string]: unknown;
}
/**
 * Request to list resources shared with the current user
 */
export interface ShareListSharedWithMeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Filter by resource type (optional)
   */
  resource_type?: ("workflow" | "workflow_folder" | "database" | "credential" | "saved_output" | "skill") | null;
  [k: string]: unknown;
}
/**
 * Request to update a share's permission
 */
export interface ShareUpdateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the share to update
   */
  share_id: string;
  /**
   * New permission level
   */
  permission: "view" | "edit";
  [k: string]: unknown;
}
/**
 * Load the visitor's own conversation history on a shared agent link
 * (restricted session only). The conversation is derived server-side from
 * the session's share scope + chat_key — no other thread is reachable.
 */
export interface SharedAgentResumeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Per-browser thread key
   */
  chat_key?: string;
  [k: string]: unknown;
}
/**
 * Visitor chat message on a shared agent link (restricted session only).
 * The response ack carries the conversation_id; the turn itself streams via
 * chat:message / agent:state to the visitor's sid.
 */
export interface SharedAgentSendRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * The visitor's chat message
   */
  text: string;
  /**
   * Per-browser thread key; a fresh key starts a new conversation
   */
  chat_key?: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface ShopifyOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Shopify OAuth callback
   */
  code: string;
  /**
   * Shop name (e.g., 'my-store' from 'my-store.myshopify.com')
   */
  shop: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  /**
   * OAuth scopes that were requested (comma-separated)
   */
  scopes?: string | null;
  /**
   * Optional custom OAuth app client ID
   */
  custom_client_id?: string | null;
  /**
   * Optional custom OAuth app client secret
   */
  custom_client_secret?: string | null;
  [k: string]: unknown;
}
/**
 * Refresh an expiring Shopify offline access token
 */
export interface ShopifyOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Shopify OAuth token is still valid
 */
export interface ShopifyOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Create a new skill in the caller's active org. Set is_system only as an internal user.
 */
export interface SkillCreateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Skill name
   */
  name: string;
  /**
   * Few-sentence retrieval hint
   */
  description?: string;
  /**
   * Optional prose body
   */
  body_text?: string | null;
  /**
   * Optional workflow graph
   */
  body_workflow?: {
    [k: string]: unknown;
  } | null;
  /**
   * Viewport / UI state for the workflow body
   */
  display_metadata?: {
    [k: string]: unknown;
  } | null;
  /**
   * Owner-side default enabled flag
   */
  enabled?: boolean;
  /**
   * Mark as platform-maintained (internal users only)
   */
  is_system?: boolean;
  [k: string]: unknown;
}
/**
 * Delete a skill (owner / staff only). Cascades skill_user_mutes.
 */
export interface SkillDeleteRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the skill
   */
  skill_id: string;
  [k: string]: unknown;
}
/**
 * Get a single skill including bodies. System skills 404 for non-internal users.
 */
export interface SkillGetRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the skill
   */
  skill_id: string;
  [k: string]: unknown;
}
/**
 * Fetch the workflow body + display metadata of a skill for FlowCanvas.
 */
export interface SkillGetWorkflowRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the skill
   */
  skill_id: string;
  [k: string]: unknown;
}
/**
 * List skills accessible to the caller (owned, org, shared, plus system for internal users).
 */
export interface SkillListRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  [k: string]: unknown;
}
/**
 * Mute or unmute a skill for the calling user. System skills cannot be muted.
 */
export interface SkillMuteRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the skill
   */
  skill_id: string;
  /**
   * True to mute, false to unmute
   */
  muted: boolean;
  [k: string]: unknown;
}
/**
 * Patch a skill. Omitted fields are left unchanged.
 */
export interface SkillUpdateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the skill
   */
  skill_id: string;
  /**
   * New name
   */
  name?: string | null;
  /**
   * New description
   */
  description?: string | null;
  /**
   * New prose body — empty string clears it
   */
  body_text?: string | null;
  /**
   * New enabled flag
   */
  enabled?: boolean | null;
  [k: string]: unknown;
}
/**
 * Save the workflow body and/or display metadata of a skill from FlowCanvas.
 */
export interface SkillUpdateWorkflowRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the skill
   */
  skill_id: string;
  /**
   * Workflow graph (nodes/edges/etc).
   */
  body_workflow?: {
    [k: string]: unknown;
  } | null;
  /**
   * Viewport / UI state for the workflow body
   */
  display_metadata?: {
    [k: string]: unknown;
  } | null;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface SlackOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Slack OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * Human-readable name for the credential
   */
  credential_name?: string;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  /**
   * Custom client ID (for user's own Slack app)
   */
  client_id?: string | null;
  /**
   * Custom client secret (for user's own Slack app)
   */
  client_secret?: string | null;
  [k: string]: unknown;
}
/**
 * Refresh an expired Slack OAuth token
 */
export interface SlackOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  /**
   * Custom client ID (if not stored in credential)
   */
  client_id?: string | null;
  /**
   * Custom client secret (if not stored in credential)
   */
  client_secret?: string | null;
  [k: string]: unknown;
}
/**
 * Validate if a Slack OAuth token is still valid
 */
export interface SlackOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential (no PKCE)
 */
export interface StripeOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Stripe Connect OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired Stripe OAuth token
 */
export interface StripeOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Stripe OAuth token is still valid
 */
export interface StripeOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Request to submit a piece of user feedback or a bug report
 */
export interface SubmitFeedbackRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * The feedback text the user typed
   */
  message: string;
  /**
   * Feedback category: bug report, idea, or general
   */
  feedback_type?: "bug" | "idea" | "general";
  /**
   * URL the user was on when submitting, for context
   */
  page_url?: string | null;
  /**
   * Optional client context (user agent, etc.)
   */
  metadata?: {
    [k: string]: unknown;
  } | null;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential (uses PKCE).
 * No project_url needed — backend lists projects after token exchange.
 */
export interface SupabaseOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Supabase OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * PKCE code verifier used during authorization
   */
  code_verifier: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  [k: string]: unknown;
}
/**
 * Refresh an expired Supabase OAuth token
 */
export interface SupabaseOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Select a specific project after the user is shown a project list.
 */
export interface SupabaseOAuthSelectProjectRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * The project ref (ID) the user selected
   */
  project_ref: string;
  /**
   * Opaque identifier returned with needs_project_selection
   */
  pending_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Supabase OAuth token is still valid
 */
export interface SupabaseOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface ThreadsOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Threads OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * OAuth scopes that were requested
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh a long-lived Threads OAuth token
 */
export interface ThreadsOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Threads OAuth token is still valid
 */
export interface ThreadsOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface TikTokOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from TikTok OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired TikTok OAuth token
 */
export interface TikTokOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a TikTok OAuth token is still valid
 */
export interface TikTokOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * List recent agent tool-call events for the current user / org
 */
export interface ToolCallListRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Maximum number of tool calls to return
   */
  limit?: number;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface TwitterOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Twitter OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * PKCE code verifier for Twitter OAuth
   */
  code_verifier: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired Twitter OAuth token
 */
export interface TwitterOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Twitter OAuth token is still valid
 */
export interface TwitterOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface TypeformOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Typeform OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  [k: string]: unknown;
}
/**
 * Request to update authentication when the access token refreshes
 */
export interface UpdateAuthRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Refreshed Supabase access token (JWT)
   */
  token: string;
  [k: string]: unknown;
}
/**
 * Request to fetch usage data with optional filters
 */
export interface UsageDataRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Start date filter (ISO format)
   */
  start_date?: string | null;
  /**
   * End date filter (ISO format)
   */
  end_date?: string | null;
  /**
   * Filter by usage type (ai_usage, cpu_usage, gpu_usage)
   */
  usage_type?: string | null;
  /**
   * Filter by specific model or instance type
   */
  usage_subtype?: string | null;
  /**
   * Group by: day, week, month, type, subtype
   */
  group_by?: string;
  /**
   * Limit number of results
   */
  limit?: number | null;
  /**
   * Organization workspace to scope to; omit/null for personal (events with organization_id IS NULL)
   */
  organization_id?: string | null;
  [k: string]: unknown;
}
/**
 * Request to fetch recent usage log entries
 */
export interface UsageLogsRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Number of recent log entries to fetch
   */
  limit?: number;
  /**
   * Filter by usage type category (ai_builder / ai_usage / api_usage / cpu_usage / gpu_usage)
   */
  usage_type?: string | null;
  /**
   * Case-insensitive substring filter on usage_subtype (model/service name)
   */
  search?: string | null;
  /**
   * Pagination cursor: return events strictly older than this ISO timestamp (the last row of the previous page)
   */
  before?: string | null;
  /**
   * Organization workspace to scope to; omit/null for personal (events with organization_id IS NULL)
   */
  organization_id?: string | null;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface WebflowOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Webflow OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * OAuth scopes that were requested
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh a Webflow OAuth token (Webflow tokens are non-expiring; no-op)
 */
export interface WebflowOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Webflow OAuth token is still valid
 */
export interface WebflowOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Initiate the WhatsApp QR code flow — creates a connection and returns QR code
 */
export interface WhatsAppQRStartRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Re-scan into this existing whatsapp_qr credential's connection instead of minting a new credential (dead-session recovery)
   */
  reconnect_credential_id?: string | null;
  [k: string]: unknown;
}
/**
 * Check WhatsApp QR scan status — polls connection and saves credential when connected
 */
export interface WhatsAppQRStatusRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * WAHooks connection ID from start response
   */
  connection_id: string;
  /**
   * Name for the credential if connected
   */
  credential_name?: string | null;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface WordPressOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from WordPress.com OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * Human-readable name for the credential
   */
  credential_name: string;
  /**
   * WordPress.com site ID or domain
   */
  site_id?: string | null;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired WordPress OAuth token
 */
export interface WordPressOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a WordPress OAuth token is still valid
 */
export interface WordPressOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * AI-autofill a single node's operation and/or config fields.
 *
 * Triggered from the FlowHelperView config panel. Modes:
 *   - 'full':         node drafter (operation) + node drafter (all fields)
 *   - 'operation':    node drafter only — pick the best operation for the node's goal
 *   - 'fields':       node drafter only — fill all fields under the current operation
 *   - 'single_field': node drafter only, restricted to ``target_field``
 */
export interface WorkflowAutofillRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Current graph state with nodes and edges
   */
  current_graph: {
    [k: string]: unknown;
  };
  /**
   * Node to autofill
   */
  node_id: string;
  /**
   * Autofill mode: 'full' | 'operation' | 'fields' | 'single_field'
   */
  mode?: string;
  /**
   * Field name to fill (required when mode='single_field')
   */
  target_field?: string | null;
  /**
   * Optional extra context — falls back to the node's goal/label
   */
  user_prompt?: string | null;
  /**
   * Optional generation ID for streaming correlation
   */
  generation_id?: string | null;
  [k: string]: unknown;
}
/**
 * Request to edit (or build from scratch) a workflow with natural language
 * instructions. Takes the current graph state and an edit prompt and runs
 * the agentic builder's multi-turn brain loop against it.
 */
export interface WorkflowBuilderEditRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Current graph state with nodes and edges
   */
  current_graph: {
    [k: string]: unknown;
  };
  /**
   * Natural language description of the edit to make
   */
  edit_prompt: string;
  /**
   * Specific node IDs to modify. If empty, LLM decides based on edit_prompt.
   */
  target_node_ids?: string[] | null;
  /**
   * Currently selected node ID for referential edits like 'remove this node'
   */
  selected_node_id?: string | null;
  /**
   * Optional generation ID for tracking.
   */
  generation_id?: string | null;
  /**
   * LLM model for the builder brain. Falls back to the server-side builder default when unset.
   */
  model?: string | null;
  /**
   * Conversation ID for chat history persistence.
   */
  conversation_id?: string | null;
  /**
   * When true, suppress conversational text and output only XML commands. Used by WorkflowCreator which has no chat UI.
   */
  silent?: boolean;
  /**
   * Optional context about what the user is looking at (inner_tab, selected_node_id, has_workflow).
   */
  user_context?: {
    [k: string]: unknown;
  } | null;
  /**
   * Visible canvas width in logical coords, used to shape the initial grid layout of unconnected nodes.
   */
  viewport_width?: number | null;
  /**
   * Visible canvas height in logical coords, used to shape the initial grid layout of unconnected nodes.
   */
  viewport_height?: number | null;
  /**
   * Raw n8n workflow JSON (as parsed from the user's paste). When present, the brain switches into n8n import mode and emits <add_node n8n_refs="..."/> linking each NoClick node to its source n8n node(s).
   */
  n8n_workflow?: {
    [k: string]: unknown;
  } | null;
  /**
   * When 'node', restrict the edit to selected_node_id only — the brain may only update_config/patch_config/set_credentials/disable/enable/mock/unmock that single node, and must not add or remove nodes/edges. Used by the FlowHelper Edit tab. Default (None) is unrestricted workflow edit.
   */
  edit_scope?: "node" | null;
  [k: string]: unknown;
}
/**
 * Request to create a checkpoint/snapshot of the current workflow state
 */
export interface WorkflowCheckpointCreateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow to checkpoint
   */
  workflow_id: string;
  /**
   * Human-readable name for this checkpoint
   */
  name: string;
  /**
   * Optional description of what changed
   */
  description?: string | null;
  [k: string]: unknown;
}
/**
 * Request to delete a checkpoint
 */
export interface WorkflowCheckpointDeleteRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the checkpoint to delete
   */
  checkpoint_id: string;
  [k: string]: unknown;
}
/**
 * Request to list all checkpoints for a workflow
 */
export interface WorkflowCheckpointListRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow to get checkpoints for
   */
  workflow_id: string;
  [k: string]: unknown;
}
/**
 * Request to restore a workflow to a specific checkpoint
 */
export interface WorkflowCheckpointRestoreRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow
   */
  workflow_id: string;
  /**
   * UUID of the checkpoint to restore
   */
  checkpoint_id: string;
  [k: string]: unknown;
}
/**
 * Request to clear persistent state for a workflow node (e.g., State Manager, RSS seen items)
 */
export interface WorkflowClearNodeStateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow containing the node
   */
  workflow_id: string;
  /**
   * ID of the node whose state should be cleared
   */
  node_id: string;
  [k: string]: unknown;
}
/**
 * Request to get a JWT token for workflow relay collaborative presence.
 *
 * Returns a short-lived JWT that can be used to authenticate with the
 * configured workflow relay for real-time collaboration.
 */
export interface WorkflowCollabTokenRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow to get collaboration token for
   */
  workflow_id: string;
  [k: string]: unknown;
}
/**
 * Request to create a new workflow
 */
export interface WorkflowCreateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Human-readable name for the workflow
   */
  name: string;
  /**
   * Description of what the workflow does
   */
  description?: string | null;
  /**
   * Workflow configuration including nodes, edges, and settings
   */
  workflow_data?: {
    [k: string]: unknown;
  } | null;
  /**
   * Access permissions: {public: ['VIEW', 'EXECUTE'], shared_with: {user_id: ['VIEW', 'EDIT']}}
   */
  permissions?: {
    [k: string]: unknown;
  } | null;
  /**
   * Resource visibility: 'personal' (private to user) or 'organization' (shared with org). Defaults to personal.
   */
  visibility?: string | null;
  /**
   * Permission level for org members when visibility='organization': 'view' or 'edit'. Defaults to 'edit'.
   */
  organization_permission?: string | null;
  /**
   * Folder UUID to create workflow in (null for root level)
   */
  folder_id?: string | null;
  [k: string]: unknown;
}
/**
 * Request to delete a workflow
 */
export interface WorkflowDeleteRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow to delete
   */
  workflow_id: string;
  [k: string]: unknown;
}
/**
 * Request to execute a workflow.
 *
 * For frontend use: provide nodes and edges directly.
 * For template/app use: omit nodes/edges to fetch from DB, optionally provide inputs.
 */
export interface WorkflowExecuteRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow being executed
   */
  workflow_id: string;
  /**
   * How the run was kicked off: manual | webhook | cron | mcp | api. Persisted on the execution row (defaults to 'manual').
   */
  trigger_source?: string | null;
  /**
   * Workflow nodes to execute. If not provided, fetched from database.
   */
  nodes?:
    | {
        [k: string]: unknown;
      }[]
    | null;
  /**
   * Connections between nodes. If not provided, fetched from database.
   */
  edges?:
    | {
        [k: string]: unknown;
      }[]
    | null;
  /**
   * Full workflow nodes to snapshot for execution-log replay. Execution still uses nodes.
   */
  replay_nodes?:
    | {
        [k: string]: unknown;
      }[]
    | null;
  /**
   * Full workflow edges to snapshot for execution-log replay. Execution still uses edges.
   */
  replay_edges?:
    | {
        [k: string]: unknown;
      }[]
    | null;
  /**
   * Optional starting node ID. If provided, only executes nodes reachable from this node. Used by webhooks to specify the trigger node. If not provided, executes all nodes.
   */
  start_node_id?: string | null;
  /**
   * Input data to inject into the workflow. Injected into start_node_id if provided, otherwise into auto-detected trigger node or first node with no predecessors.
   */
  inputs?: {
    [k: string]: unknown;
  } | null;
  /**
   * Conversation ID for agent memory persistence (workflow chat only). When set, agent nodes use this for conversation history.
   */
  conversation_id?: string | null;
  /**
   * Per-node config overrides keyed by node ID. Merged into node config before execution. Used by SDK clients to set dynamic parameters (for example an agent message).
   */
  config_overrides?: {
    [k: string]: {
      [k: string]: unknown;
    };
  } | null;
  /**
   * When True with start_node_id, only execute the start node and its downstream nodes (no predecessors). Used by 'Run from here' when no upstream references are detected.
   */
  forward_only?: boolean | null;
  /**
   * When True, this run was triggered by an interface component fetching its own data (via the @noclick/sdk), not by an explicit user 'Run'. Background runs are echoed back on workflow:started so the client can keep them out of the global run indicator.
   */
  background?: boolean | null;
  [k: string]: unknown;
}
/**
 * Request the per-status / per-trigger / total counts for a workflow's
 * executions. One round-trip — single GROUPING SETS query against the new
 * INCLUDE index does this as an Index-Only Scan (no heap I/O at prod scale).
 */
export interface WorkflowExecutionCountsRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow
   */
  workflow_id: string;
  [k: string]: unknown;
}
/**
 * Request the full detail of one past execution: the graph snapshot + per-node
 * status/error metadata for the read-only replay (node outputs fetched lazily).
 */
export interface WorkflowExecutionDetailRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow
   */
  workflow_id: string;
  /**
   * UUID of the execution to inspect
   */
  execution_id: string;
  [k: string]: unknown;
}
/**
 * Request a (filtered, paginated) page of execution logs for a workflow.
 *
 * Pagination is cursor-based via ``(started_at, id)`` — stable in the face of
 * new executions landing while the user pages through old ones. Filters and
 * search hit the same indexed path (idx_workflow_executions_workflow_started),
 * so each page costs ~one index-range probe regardless of total table size.
 */
export interface WorkflowExecutionListRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow to get execution logs for
   */
  workflow_id: string;
  /**
   * Page size (1..200; default 50)
   */
  limit?: number | null;
  /**
   * ISO timestamp from the LAST row of the previous page. Next page returns rows strictly older than this (with id as tiebreak).
   */
  cursor_started_at?: string | null;
  /**
   * UUID from the last row of the previous page; tiebreaker when two executions share started_at down to the microsecond.
   */
  cursor_id?: string | null;
  /**
   * Raw DB status values to include (e.g. ['completed', 'error']). Null = all statuses. The frontend maps UI status labels (success/error/running/waiting) → DB values.
   */
  status?: string[] | null;
  /**
   * Raw trigger_source values to include (e.g. ['cron','webhook']). Null/empty = any trigger.
   */
  trigger_source?: string[] | null;
  /**
   * Case-insensitive substring match against the execution's error column (the only meaningful text column on the row — the 'Processed N nodes' fallback message is computed, not stored).
   */
  search?: string | null;
  [k: string]: unknown;
}
/**
 * Fetch historical outputs for a specific node across executions.
 */
export interface WorkflowGetNodeOutputHistoryRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow
   */
  workflow_id: string;
  /**
   * Node ID to fetch history for
   */
  node_id: string;
  /**
   * Max number of historical outputs to return
   */
  limit?: number;
  [k: string]: unknown;
}
/**
 * Fetch node outputs from the dedicated outputs table (server-backed, not IndexedDB).
 */
export interface WorkflowGetNodeOutputsRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow
   */
  workflow_id: string;
  /**
   * Specific execution ID. If None, returns latest.
   */
  execution_id?: string | null;
  /**
   * Specific node IDs. If None, returns all.
   */
  node_ids?: string[] | null;
  [k: string]: unknown;
}
/**
 * Request to get a specific workflow by ID
 */
export interface WorkflowGetRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow to retrieve
   */
  workflow_id: string;
  [k: string]: unknown;
}
/**
 * Request to list all workflows owned by the current user
 */
export interface WorkflowListRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Folder UUID to filter by (null for root level only)
   */
  folder_id?: string | null;
  /**
   * Explicit org scope: '' = personal, '<uuid>' = that org, null = use the active (is_primary) context. The browser sends its own scope so the response can't be mismatched by the org-switch race.
   */
  scope_org_id?: string | null;
  [k: string]: unknown;
}
/**
 * Request to list all soft-deleted (trashed) workflows
 */
export interface WorkflowListTrashRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  [k: string]: unknown;
}
/**
 * Load persistent state for a workflow node
 */
export interface WorkflowLoadNodeStateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow containing the node
   */
  workflow_id: string;
  /**
   * ID of the node whose state should be loaded
   */
  node_id: string;
  [k: string]: unknown;
}
/**
 * MCP tool request to create a new workflow and open it in the editor.
 *
 * If no workflow is currently open, this creates one and navigates to it.
 */
export interface WorkflowMCPCreateWorkflowRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Name for the new workflow
   */
  name: string;
  /**
   * Description of what the workflow does
   */
  description?: string;
  /**
   * Folder UUID to create the workflow in (null for root)
   */
  folder_id?: string | null;
  [k: string]: unknown;
}
/**
 * MCP tool request to delete a workflow.
 *
 * Permanently deletes the workflow and all its nodes/edges from the database.
 */
export interface WorkflowMCPDeleteWorkflowRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow to delete
   */
  workflow_id: string;
  [k: string]: unknown;
}
/**
 * MCP tool request to get the status of a workflow execution.
 *
 * Use this after run_workflow to check if execution completed successfully,
 * failed with an error, or is still running.
 */
export interface WorkflowMCPGetExecutionStatusRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the execution to check. If not provided, returns the latest execution for workflow_id.
   */
  execution_id?: string | null;
  /**
   * UUID of the workflow. Required if execution_id is not provided.
   */
  workflow_id?: string | null;
  [k: string]: unknown;
}
/**
 * MCP tool request to get a specific node's configuration by ID.
 *
 * This is a backend-only operation that reads from the database.
 * Returns the full node data including config, position, and type.
 */
export interface WorkflowMCPGetNodeConfigRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow
   */
  workflow_id: string;
  /**
   * ID of the node to get config for
   */
  node_id: string;
  [k: string]: unknown;
}
/**
 * MCP tool request to get the full JSON schema for a specific node config type.
 *
 * Since workflow nodes can have multiple config types (union types), this
 * returns the schema for a specific config variant.
 */
export interface WorkflowMCPGetNodeConfigSchemaRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Node type identifier (e.g., 'automation-telegram')
   */
  node_type: string;
  /**
   * Config type variant (e.g., 'send_message', 'receive_message')
   */
  config_type: string;
  [k: string]: unknown;
}
/**
 * MCP tool request to get the input data flowing into a workflow node.
 *
 * This is a backend-only operation that reads from the database.
 * Returns outputs from all connected upstream nodes.
 */
export interface WorkflowMCPGetNodeInputRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow
   */
  workflow_id: string;
  /**
   * ID of the node to get input for. If not provided, uses the currently selected node.
   */
  node_id?: string | null;
  [k: string]: unknown;
}
/**
 * MCP tool request to get the execution output of a workflow node.
 *
 * This is a backend-only operation that reads from the database.
 * Returns the node's output data or mockedOutput if set.
 */
export interface WorkflowMCPGetNodeOutputRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow
   */
  workflow_id: string;
  /**
   * ID of the node to get output from. If not provided, uses the currently selected node.
   */
  node_id?: string | null;
  [k: string]: unknown;
}
/**
 * MCP tool request to get the currently open workflow in the editor.
 *
 * Returns the workflow_id, nodes, edges, and running state of the currently
 * open workflow. Returns null if no workflow is open.
 *
 * If include_configs is True, returns full node configs (useful for debugging/inspection).
 */
export interface WorkflowMCPGetOpenWorkflowRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * If true, include full node configurations in the response
   */
  include_configs?: boolean;
  [k: string]: unknown;
}
/**
 * MCP tool request to get the currently selected node in the workflow canvas
 */
export interface WorkflowMCPGetSelectedNodeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  [k: string]: unknown;
}
/**
 * MCP tool request to list available credentials.
 *
 * Returns credentials the user has saved, optionally filtered by type.
 * Useful for checking if required OAuth connections exist before configuring nodes.
 */
export interface WorkflowMCPListCredentialsRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Filter by credential type (e.g., 'google_sheets_oauth', 'gmail_oauth'). If not provided, returns all credentials.
   */
  credential_type?: string | null;
  [k: string]: unknown;
}
/**
 * MCP tool request to list saved mock outputs for a node type.
 *
 * Returns saved outputs that can be used to mock node execution.
 */
export interface WorkflowMCPListSavedOutputsRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Node type to list saved outputs for (e.g., 'automation-telegram')
   */
  node_type: string;
  [k: string]: unknown;
}
/**
 * MCP tool request to list available workflows.
 *
 * Returns workflows owned by the user, optionally filtered by search query.
 * Optionally filter by folder_id to list workflows in a specific folder.
 */
export interface WorkflowMCPListWorkflowsRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Optional search query to filter workflows by name or description
   */
  query?: string | null;
  /**
   * Folder UUID to filter by. If provided, only returns workflows in that folder. Use empty string '' for root-level (unfiled) workflows only.
   */
  folder_id?: string | null;
  /**
   * Maximum number of workflows to return
   */
  limit?: number;
  [k: string]: unknown;
}
/**
 * MCP tool request to load dynamic options for a node configuration field.
 *
 * Use this to load options for fields like spreadsheet_id, sheet_name, etc.
 * that are populated dynamically based on user's connected accounts.
 */
export interface WorkflowMCPLoadFieldOptionsRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * The node type (e.g., 'automation-google-sheets')
   */
  node_type: string;
  /**
   * The field to load options for (e.g., 'spreadsheet_id')
   */
  field_name: string;
  /**
   * Optional search query to filter options by name/label
   */
  search_query?: string | null;
  /**
   * Values of fields this field depends on (e.g., {'spreadsheet_id': '...'} when loading sheet_name options)
   */
  depends_on?: {
    [k: string]: unknown;
  } | null;
  /**
   * Credential ID to use. If not provided, uses the first matching credential for the node type.
   */
  credential_id?: string | null;
  /**
   * Maximum number of options to return
   */
  limit?: number;
  /**
   * Offset for pagination
   */
  offset?: number;
  [k: string]: unknown;
}
/**
 * MCP tool request to open an existing workflow in the editor.
 *
 * Navigates the frontend to display the specified workflow.
 */
export interface WorkflowMCPOpenWorkflowRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow to open
   */
  workflow_id: string;
  [k: string]: unknown;
}
/**
 * Frontend response to backend MCP request.
 *
 * Sent by the frontend when responding to a 'workflow:mcp:request' event.
 * Contains the requested data or mutation result with the same request_id
 * for correlation.
 */
export interface WorkflowMCPResponseRequest {
  /**
   * Correlation ID from the original request
   */
  request_id: string;
  /**
   * Response data (workflow state, node info, mutation result)
   */
  data?: {
    [k: string]: unknown;
  };
  /**
   * Error message if request failed
   */
  error?: string | null;
  [k: string]: unknown;
}
/**
 * MCP tool request to execute a single node (backend-only, database-backed).
 *
 * Loads the workflow from the database and executes only the target node.
 * Predecessor nodes must have output data available (from prior execution
 * or mocked data) - they will be used as inputs to the target node.
 */
export interface WorkflowMCPRunNodeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow containing the node
   */
  workflow_id: string;
  /**
   * ID of the node to execute. If not provided, uses the currently selected node.
   */
  node_id?: string | null;
  [k: string]: unknown;
}
/**
 * MCP tool request to execute a workflow (backend-only, database-backed).
 *
 * Loads the workflow from the database and executes it without requiring
 * a frontend connection. Returns immediately with execution_id.
 * Use get_node_output() to wait for specific node results.
 */
export interface WorkflowMCPRunWorkflowRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow to execute
   */
  workflow_id: string;
  [k: string]: unknown;
}
/**
 * MCP tool request to search available workflow node types.
 *
 * Returns summaries of available nodes including type, label, description,
 * available config types, and required credentials. Use get_node_config_schema
 * to get the full JSON schema for a specific config type.
 */
export interface WorkflowMCPSearchNodesRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Search query to filter nodes (e.g., 'telegram', 'google')
   */
  query?: string | null;
  [k: string]: unknown;
}
/**
 * MCP tool request to update the interface layout of a workflow.
 *
 * Uses XML commands to position, resize, and arrange interface blocks on a 12-column grid.
 */
export interface WorkflowMCPUpdateInterfaceRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow
   */
  workflow_id: string;
  /**
   * XML commands for interface layout (set_block_layout, remove_block, auto_layout)
   */
  updates_xml: string;
  [k: string]: unknown;
}
/**
 * MCP tool request to update a workflow's metadata (name and description).
 *
 * Only updates the specified fields; omitted fields remain unchanged.
 */
export interface WorkflowMCPUpdateWorkflowMetadataRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow to update
   */
  workflow_id: string;
  /**
   * New name for the workflow
   */
  name?: string | null;
  /**
   * New description for the workflow
   */
  description?: string | null;
  [k: string]: unknown;
}
/**
 * Request to move a workflow to a folder
 */
export interface WorkflowMoveToFolderRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Workflow UUID
   */
  workflow_id: string;
  /**
   * Target folder UUID (null for root)
   */
  folder_id?: string | null;
  [k: string]: unknown;
}
/**
 * Request to get config schema for a node type
 */
export interface WorkflowNodeConfigSchemaRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Type of the node (e.g., 'automation-telegram', 'agent')
   */
  node_type: string;
  [k: string]: unknown;
}
/**
 * Evaluate a single inline expression against connected nodes' sample outputs
 * for a live editor preview. Stateless: the client sends the data it already has.
 */
export interface WorkflowNodeEvaluateExpressionRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * The inner JS expression to evaluate (without the surrounding {{ }})
   */
  expression: string;
  /**
   * Connected nodes' last/sample outputs keyed by node id (include the reserved 'vars')
   */
  sample_outputs?: {
    [k: string]: unknown;
  };
  /**
   * Workflow nodes (id + data.label) so $('Node Label') resolves like at runtime
   */
  workflow_nodes?:
    | {
        [k: string]: unknown;
      }[]
    | null;
  primary_input?: unknown;
  [k: string]: unknown;
}
/**
 * Get a single node's config fields.
 */
export interface WorkflowNodeGetConfigRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow
   */
  workflow_id: string;
  /**
   * ID of the node
   */
  node_id: string;
  [k: string]: unknown;
}
/**
 * Request to load dynamic options for a node field (e.g., list of spreadsheets)
 */
export interface WorkflowNodeLoadOptionsRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Type of the node (e.g., 'automation-google-sheets')
   */
  node_type: string;
  /**
   * Name of the field needing options (e.g., 'spreadsheet_id')
   */
  field_name: string;
  /**
   * UUID of the credential to use for API calls; null when the field's source doesn't require user credentials
   */
  credential_id?: string | null;
  /**
   * Additional context (e.g., selected spreadsheet for listing worksheets)
   */
  context?: {
    [k: string]: unknown;
  } | null;
  /**
   * Token for loading next page of options (pagination)
   */
  page_token?: string | null;
  /**
   * User-typed search term to narrow options. Nodes whose upstream API supports a native query parameter pass it through; nodes without server-side search paginate up to a safety cap and case-insensitive substring filter on label/value.
   */
  search?: string | null;
  [k: string]: unknown;
}
/**
 * Request to load a computed/generated value for a node field (e.g., webhook URL)
 */
export interface WorkflowNodeLoadValueRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Type of the node (e.g., 'trigger-webhook')
   */
  node_type: string;
  /**
   * Name of the field to compute (e.g., 'webhook_url')
   */
  field_name: string;
  /**
   * UUID of the workflow containing the node
   */
  workflow_id: string;
  /**
   * ID of the node in the workflow
   */
  node_id: string;
  /**
   * Additional context for value computation
   */
  context?: {
    [k: string]: unknown;
  } | null;
  /**
   * Map of credential_type -> credential_id for API calls (e.g., telegram_bot_token -> uuid)
   */
  credential_ids?: {
    [k: string]: string;
  } | null;
  [k: string]: unknown;
}
/**
 * Request one node's reassembled output for a past execution (lazy, on click).
 */
export interface WorkflowNodeOutputRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow
   */
  workflow_id: string;
  /**
   * UUID of the execution
   */
  execution_id: string;
  /**
   * Node whose output to reassemble
   */
  node_id: string;
  [k: string]: unknown;
}
/**
 * Request to update a single node's config fields (merge semantics).
 */
export interface WorkflowNodeSetConfigRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow
   */
  workflow_id: string;
  /**
   * ID of the node to update
   */
  node_id: string;
  /**
   * Config fields to merge into existing node config
   */
  config: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
/**
 * Request to validate a node's configuration
 */
export interface WorkflowNodeValidateConfigRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Type of the node
   */
  node_type: string;
  /**
   * Configuration data to validate
   */
  config_data: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
/**
 * Request to permanently delete a trashed workflow
 */
export interface WorkflowPermanentDeleteRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the trashed workflow to permanently delete
   */
  workflow_id: string;
  [k: string]: unknown;
}
/**
 * Request to restore a soft-deleted workflow from trash
 */
export interface WorkflowRestoreRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow to restore from trash
   */
  workflow_id: string;
  [k: string]: unknown;
}
/**
 * Save persistent state for a workflow node (used by the SDK state.set)
 */
export interface WorkflowSaveNodeStateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow containing the node
   */
  workflow_id: string;
  /**
   * ID of the node whose state should be saved
   */
  node_id: string;
  /**
   * The form values to persist
   */
  values: {
    [k: string]: unknown;
  };
  [k: string]: unknown;
}
/**
 * Get a state value by key, auto-resolving the state-manager node.
 */
export interface WorkflowStateGetRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow
   */
  workflow_id: string;
  /**
   * State key to read
   */
  key: string;
  /**
   * Explicit state-manager node ID (auto-detected if omitted)
   */
  node_id?: string | null;
  [k: string]: unknown;
}
/**
 * List all state keys.
 */
export interface WorkflowStateKeysRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow
   */
  workflow_id: string;
  /**
   * Explicit state-manager node ID
   */
  node_id?: string | null;
  [k: string]: unknown;
}
/**
 * Set a state value by key, auto-resolving the state-manager node.
 */
export interface WorkflowStateSetRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow
   */
  workflow_id: string;
  /**
   * State key to write
   */
  key: string;
  /**
   * Value to store; null/omitted deletes the key
   */
  value?: {
    [k: string]: unknown;
  };
  /**
   * Explicit state-manager node ID (auto-detected if omitted)
   */
  node_id?: string | null;
  [k: string]: unknown;
}
/**
 * Request to update a workflow's data or metadata
 */
export interface WorkflowUpdateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the workflow to update
   */
  workflow_id: string;
  /**
   * New name for the workflow
   */
  name?: string | null;
  /**
   * New description for the workflow
   */
  description?: string | null;
  /**
   * Updated workflow configuration (nodes, edges, settings)
   */
  workflow_data?: {
    [k: string]: unknown;
  } | null;
  /**
   * Updated access permissions
   */
  permissions?: {
    [k: string]: unknown;
  } | null;
  /**
   * UI display state: viewport (x,y,zoom), selectedNodeId, flowHelperView state
   */
  display_metadata?: {
    [k: string]: unknown;
  } | null;
  /**
   * Workflow-level settings (e.g. min_required_balance). Merged with existing settings on update.
   */
  settings?: {
    [k: string]: unknown;
  } | null;
  /**
   * IDs of nodes that were deleted since last update. Used to cleanup cron schedules.
   */
  deleted_node_ids?: string[] | null;
  /**
   * CAS guard for workflow_data writes: the graph_version this client loaded. When set and the server's version differs, the write is rejected and the response carries conflict=true plus the current blob + version so the client can rebase. Omitted (None) = unconditional write (metadata-only updates, MCP/builder writers).
   */
  expected_graph_version?: number | null;
  [k: string]: unknown;
}
/**
 * YJS synchronization data
 */
export interface YjsSyncRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * YJS sync binary data
   */
  data: string;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface ZendeskOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Zendesk OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization request
   */
  redirect_uri: string;
  /**
   * Zendesk subdomain that scopes the OAuth host
   */
  subdomain: string;
  /**
   * OAuth scopes that were requested
   */
  scopes?: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired Zendesk OAuth token
 */
export interface ZendeskOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Zendesk OAuth token is still valid
 */
export interface ZendeskOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  [k: string]: unknown;
}
/**
 * Exchange OAuth authorization code for tokens and store as credential
 */
export interface ZoomOAuthExchangeRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * Authorization code from Zoom OAuth callback
   */
  code: string;
  /**
   * Redirect URI used in authorization (must match)
   */
  redirect_uri: string;
  /**
   * OAuth scopes that were requested
   */
  scopes: string[];
  [k: string]: unknown;
}
/**
 * Refresh an expired Zoom OAuth token (access tokens expire after 1 hour)
 */
export interface ZoomOAuthRefreshRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to refresh
   */
  credential_id: string;
  [k: string]: unknown;
}
/**
 * Validate if a Zoom OAuth token is still valid
 */
export interface ZoomOAuthValidateRequest {
  /**
   * UUID for request/response correlation
   */
  request_id?: string | null;
  /**
   * UUID of the credential to validate
   */
  credential_id: string;
  [k: string]: unknown;
}

/* tslint:disable */
/* eslint-disable */
/**
/* This file was automatically generated from pydantic models by running pydantic2ts.
/* Do not modify it by hand - just update the pydantic models and then re-run the script
*/

/**
 * Response for the agent_share manage events (get_or_create / rotate /
 * set_active): the current capability link for one agent node.
 */
export interface AgentShareLinkResponse {
  /**
   * Whether the operation succeeded
   */
  success: boolean;
  /**
   * Capability id (None when error is set)
   */
  link_id?: string | null;
  /**
   * Public chat page URL (/a/{link_id})
   */
  url?: string | null;
  /**
   * Whether the link currently accepts visitors
   */
  is_active?: boolean | null;
  /**
   * Error message if failed
   */
  error?: string | null;
}
/**
 * Response for airtable:oauth:exchange request
 */
export interface AirtableOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Airtable account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for airtable:oauth:refresh request
 */
export interface AirtableOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for airtable:oauth:validate request
 */
export interface AirtableOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Airtable account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for apollo:oauth:exchange request
 */
export interface ApolloOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Apollo account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for apollo:oauth:refresh request
 */
export interface ApolloOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for apollo:oauth:validate request
 */
export interface ApolloOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Apollo account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for asana:oauth:exchange request
 */
export interface AsanaOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Asana user name for display
   */
  name?: string | null;
  /**
   * Asana account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for asana:oauth:refresh request
 */
export interface AsanaOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for asana:oauth:validate request
 */
export interface AsanaOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Asana user name
   */
  name?: string | null;
  /**
   * Asana account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for atlassian:oauth:exchange request
 */
export interface AtlassianOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Atlassian Cloud ID
   */
  cloud_id?: string | null;
  /**
   * Jira site name for display
   */
  site_name?: string | null;
  /**
   * Jira site URL
   */
  site_url?: string | null;
  /**
   * Jira sites available to the Atlassian account when the requested site is inaccessible
   */
  available_sites?:
    | {
        [k: string]: string;
      }[]
    | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for atlassian:oauth:refresh request
 */
export interface AtlassianOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for atlassian:oauth:validate request
 */
export interface AtlassianOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Atlassian Cloud ID
   */
  cloud_id?: string | null;
  /**
   * Jira site name
   */
  site_name?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for attio:oauth:exchange request
 */
export interface AttioOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Attio workspace name for display
   */
  name?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for attio:oauth:refresh request
 */
export interface AttioOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for attio:oauth:validate request
 */
export interface AttioOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Attio workspace name
   */
  name?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for bamboohr:oauth:exchange request
 */
export interface BambooHROAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * BambooHR user name for display
   */
  name?: string | null;
  /**
   * BambooHR account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for bamboohr:oauth:refresh request
 */
export interface BambooHROAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for bamboohr:oauth:validate request
 */
export interface BambooHROAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * BambooHR user name
   */
  name?: string | null;
  /**
   * BambooHR account email
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for box:oauth:exchange request
 */
export interface BoxOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Box user name for display
   */
  name?: string | null;
  /**
   * Box account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for box:oauth:refresh request
 */
export interface BoxOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for box:oauth:validate request
 */
export interface BoxOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Box user name
   */
  name?: string | null;
  /**
   * Box account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for calcom:oauth:exchange request
 */
export interface CalComOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Cal.com user name for display
   */
  name?: string | null;
  /**
   * Cal.com account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for calcom:oauth:refresh request
 */
export interface CalComOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for calcom:oauth:validate request
 */
export interface CalComOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Cal.com user name
   */
  name?: string | null;
  /**
   * Cal.com account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for calendly:oauth:exchange request
 */
export interface CalendlyOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Calendly user name for display
   */
  name?: string | null;
  /**
   * Calendly account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for calendly:oauth:refresh request
 */
export interface CalendlyOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for calendly:oauth:validate request
 */
export interface CalendlyOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Calendly user name
   */
  name?: string | null;
  /**
   * Calendly account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for canva:oauth:exchange request
 */
export interface CanvaOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Canva account display name
   */
  display_name?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for canva:oauth:refresh request
 */
export interface CanvaOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for canva:oauth:validate request
 */
export interface CanvaOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Canva account display name
   */
  display_name?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Information about a workflow checkpoint
 */
export interface CheckpointInfo {
  /**
   * Checkpoint UUID
   */
  id: string;
  /**
   * Workflow UUID
   */
  workflow_id: string;
  /**
   * Human-readable checkpoint name
   */
  name: string;
  /**
   * Optional description
   */
  description?: string;
  /**
   * Creation timestamp in ISO format
   */
  created_at: string;
}
/**
 * Response for claude-code:auth:exchange
 */
export interface ClaudeCodeAuthExchangeResponse {
  /**
   * Whether the code exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Status or error message
   */
  message?: string | null;
}
/**
 * Response for claude-code:auth:start
 */
export interface ClaudeCodeAuthStartResponse {
  /**
   * Whether the OAuth start was successful
   */
  success: boolean;
  /**
   * URL to open in browser for authentication
   */
  auth_url?: string | null;
  /**
   * Session ID for exchanging the code
   */
  auth_session_id?: string | null;
  /**
   * Status or error message
   */
  message?: string | null;
}
/**
 * Response for clickup:oauth:exchange request
 */
export interface ClickUpOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * ClickUp user name for display
   */
  name?: string | null;
  /**
   * ClickUp account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for clickup:oauth:refresh request
 */
export interface ClickUpOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for clickup:oauth:validate request
 */
export interface ClickUpOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * ClickUp user name
   */
  name?: string | null;
  /**
   * ClickUp account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for cloudflare:oauth:exchange request
 */
export interface CloudflareOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Cloudflare account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for cloudflare:oauth:refresh request
 */
export interface CloudflareOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for cloudflare:oauth:validate request
 */
export interface CloudflareOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 1 hour
   */
  expires_soon?: boolean;
  /**
   * Cloudflare account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for codex:auth:poll — returns status of device code approval
 */
export interface CodexDeviceCodePollResponse {
  /**
   * Whether the poll request itself succeeded
   */
  success: boolean;
  /**
   * One of: pending, completed, error
   */
  status?: string;
  /**
   * UUID of the created credential (on completion)
   */
  credential_id?: string | null;
  /**
   * Name of the created credential (on completion)
   */
  credential_name?: string | null;
  /**
   * Status or error message
   */
  message?: string | null;
}
/**
 * Response for codex:auth:start — returns verification URL and user code
 */
export interface CodexDeviceCodeStartResponse {
  /**
   * Whether device code request was successful
   */
  success: boolean;
  /**
   * URL to open in browser for user to authorize
   */
  verification_url?: string | null;
  /**
   * One-time code for the user to enter
   */
  user_code?: string | null;
  /**
   * Device auth session ID for polling
   */
  device_auth_id?: string | null;
  /**
   * Polling interval in seconds
   */
  interval?: number | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * A workflow whose nodes reference a credential pending deletion.
 */
export interface CredentialAffectedWorkflow {
  /**
   * Workflow UUID
   */
  workflow_id: string;
  /**
   * Workflow display name
   */
  workflow_name: string;
}
/**
 * Response for credential:create request
 */
export interface CredentialCreateResponse {
  /**
   * Whether creation was successful
   */
  success: boolean;
  /**
   * Created credential info
   */
  credential?: CredentialInfo | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Credential information structure (without decrypted data)
 */
export interface CredentialInfo {
  /**
   * Credential UUID
   */
  id: string;
  /**
   * Human-readable credential name
   */
  name: string;
  /**
   * Type: 'oauth', 'api_key', 'database', 'third_party'
   */
  credential_type: string;
  /**
   * Credential metadata
   */
  metadata?: {
    [k: string]: unknown;
  };
  /**
   * Creation timestamp
   */
  created_at: string;
  /**
   * Last update timestamp
   */
  updated_at: string;
  /**
   * How the user accesses this credential: 'owner', 'shared', or 'shared_org'
   */
  access_type?: string;
  /**
   * Organization this credential belongs to (null if personal)
   */
  organization_id?: string | null;
  /**
   * Whether this credential is shared with the current organization
   */
  shared_with_org?: boolean;
  /**
   * Whether this credential exceeds the plan's per-type cap
   */
  over_cap?: boolean;
  /**
   * Email of user who shared this credential (only for shared credentials)
   */
  shared_by_email?: string | null;
  /**
   * Display name of user who shared (only for shared credentials)
   */
  shared_by_name?: string | null;
  /**
   * The resource_shares row ID linking this credential to the current user (only for shared credentials)
   */
  share_id?: string | null;
  /**
   * When this credential was revoked/disconnected (null = live). Revoked credentials cannot be loaded at run time — the UI must surface them as dead, not selectable-as-healthy
   */
  revoked_at?: string | null;
  /**
   * Why the credential was revoked (e.g. user_revoked, provider_4xx auto-revoke)
   */
  revoked_reason?: string | null;
  /**
   * Live provider session state for connection-backed credentials (whatsapp_qr): 'connected' = phone linked; any other value ('scan_qr', 'failed', 'stopped', 'missing') = the session is dead and needs a fresh QR scan. None = not applicable or state unknown
   */
  connection_status?: string | null;
}
/**
 * Response for credential:delete request
 */
export interface CredentialDeleteResponse {
  /**
   * Whether deletion was successful
   */
  success: boolean;
  /**
   * Success or error message
   */
  message: string;
  /**
   * UUID of the deleted credential
   */
  credential_id?: string | null;
  /**
   * False on a dry run — nothing was deleted
   */
  deleted?: boolean;
  /**
   * Workflows referencing this credential (populated on dry runs)
   */
  affected_workflows?: CredentialAffectedWorkflow[];
}
/**
 * Response for credential:get request (includes decrypted data)
 */
export interface CredentialGetResponse {
  /**
   * Credential UUID
   */
  credential_id: string;
  /**
   * Human-readable credential name
   */
  name: string;
  /**
   * Type: 'oauth', 'api_key', 'database', 'third_party'
   */
  credential_type: string;
  /**
   * Decrypted credential data
   */
  credential_data: {
    [k: string]: unknown;
  };
  /**
   * Credential metadata
   */
  metadata?: {
    [k: string]: unknown;
  };
}
/**
 * Response for credential:list request
 */
export interface CredentialListResponse {
  /**
   * List of credentials (without decrypted data)
   */
  credentials?: CredentialInfo[];
  /**
   * Number of shared credentials hidden due to plan limit
   */
  hidden_shared_count?: number;
  /**
   * Current context subscription tier (for limit messaging)
   */
  subscription_tier?: string;
}
/**
 * Response for credential:request:cancel
 */
export interface CredentialRequestCancelResponse {
  success: boolean;
  message: string;
}
/**
 * Response for credential:request:create
 */
export interface CredentialRequestCreateResponse {
  success: boolean;
  request?: CredentialRequestInfo | null;
  /**
   * Shareable link the recipient uses to provide the credential
   */
  provide_url?: string | null;
  message?: string | null;
}
/**
 * Credential request information
 */
export interface CredentialRequestInfo {
  /**
   * Request UUID
   */
  id: string;
  /**
   * Email the request was sent to
   */
  target_email: string;
  /**
   * Credential type requested
   */
  credential_type: string;
  /**
   * Optional message from requester
   */
  message?: string | null;
  /**
   * pending, fulfilled, expired, or cancelled
   */
  status: string;
  /**
   * Credential UUID if fulfilled
   */
  credential_id?: string | null;
  /**
   * Expiration timestamp
   */
  expires_at?: string | null;
  /**
   * Creation timestamp
   */
  created_at: string;
  /**
   * Fulfillment timestamp
   */
  fulfilled_at?: string | null;
}
/**
 * Response for credential:request:list
 */
export interface CredentialRequestListResponse {
  requests?: CredentialRequestInfo[];
}
/**
 * Response for credential:test_connection.
 */
export interface CredentialTestConnectionResponse {
  /**
   * true = provider answered, false = provider rejected the credential, null = cannot judge
   */
  reachable?: boolean | null;
  /**
   * Recognisable items from the account
   */
  samples?: EvidenceSampleModel[];
  /**
   * The user's word for those items ('channels', 'repositories')
   */
  noun?: string;
  /**
   * How many were found, when more than shown
   */
  total?: number | null;
  /**
   * The account itself, shown when there is nothing to list
   */
  account_label?: string | null;
  /**
   * Config field these samples can fill; null when they answer nothing
   */
  answers_field?: string | null;
  /**
   * 'account' = data unique to this account; 'reachability' = only proves the key is accepted
   */
  proves?: string;
  /**
   * The provider's verbatim refusal when reachable is false
   */
  error?: string | null;
}
/**
 * One recognisable item from the user's own account.
 */
export interface EvidenceSampleModel {
  /**
   * What the user sees, in their own vocabulary (e.g. '#sales')
   */
  label: string;
  /**
   * Settable into `answers_field`; null when the sample cannot answer a config field
   */
  value?: string | null;
}
/**
 * Response for credential:update request
 */
export interface CredentialUpdateResponse {
  /**
   * Whether update was successful
   */
  success: boolean;
  /**
   * Updated credential info
   */
  credential?: CredentialInfo | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Information about a single dataset row
 */
export interface DatasetRowInfo {
  /**
   * Row UUID
   */
  id: string;
  /**
   * Row index within the dataset
   */
  row_index: number;
  /**
   * Row data
   */
  data: {
    [k: string]: unknown;
  };
  /**
   * Creation timestamp ISO string
   */
  created_at: string;
}
/**
 * Response for discord:oauth:exchange request
 */
export interface DiscordOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Discord username for display
   */
  username?: string | null;
  /**
   * Discord account email for display
   */
  email?: string | null;
  /**
   * Guild ID when bot was installed (bot install flow)
   */
  guild_id?: string | null;
  /**
   * Guild name when bot was installed (bot install flow)
   */
  guild_name?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for discord:oauth:refresh request
 */
export interface DiscordOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for discord:oauth:validate request
 */
export interface DiscordOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Discord username
   */
  username?: string | null;
  /**
   * Discord account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for dropbox:oauth:exchange request
 */
export interface DropboxOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Dropbox username for display
   */
  username?: string | null;
  /**
   * Dropbox account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for dropbox:oauth:refresh request
 */
export interface DropboxOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for dropbox:oauth:validate request
 */
export interface DropboxOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Dropbox username
   */
  username?: string | null;
  /**
   * Dropbox account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for facebook:oauth:exchange request (Instagram integration)
 */
export interface FacebookOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Instagram username for display
   */
  instagram_username?: string | null;
  /**
   * Facebook account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
  /**
   * True when multiple Instagram accounts found and user must select one
   */
  needs_selection?: boolean;
  /**
   * List of account dicts when needs_selection is True
   */
  accounts?: unknown[] | null;
  /**
   * Opaque key to pass back when completing account selection
   */
  pending_selection_key?: string | null;
}
/**
 * Response for facebook:oauth:refresh request
 */
export interface FacebookOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for facebook:oauth:validate request
 */
export interface FacebookOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 7 days
   */
  expires_soon?: boolean;
  /**
   * Instagram username
   */
  instagram_username?: string | null;
  /**
   * Facebook account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for facebook_pages:oauth:exchange request
 */
export interface FacebookPagesOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Facebook user name for display
   */
  name?: string | null;
  /**
   * Facebook account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for facebook_pages:oauth:refresh request
 */
export interface FacebookPagesOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for facebook_pages:oauth:validate request
 */
export interface FacebookPagesOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if the token expires soon
   */
  expires_soon?: boolean;
  /**
   * Facebook user name
   */
  name?: string | null;
  /**
   * Facebook account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for fathom:oauth:exchange request
 */
export interface FathomOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Fathom account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for fathom:oauth:refresh request
 */
export interface FathomOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for fathom:oauth:validate request
 */
export interface FathomOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Fathom account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * A single option for a dynamic dropdown field
 */
export interface FieldOption {
  /**
   * The value to store when selected
   */
  value: string;
  /**
   * Display label for the option
   */
  label: string;
  /**
   * Additional metadata about the option
   */
  metadata?: {
    [k: string]: unknown;
  } | null;
}
/**
 * Response for workflow_folder:create request
 */
export interface FolderCreateResponse {
  /**
   * Whether creation was successful
   */
  success: boolean;
  /**
   * Created folder info
   */
  folder?: FolderInfo | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Workflow folder information structure
 */
export interface FolderInfo {
  /**
   * Folder UUID
   */
  id: string;
  /**
   * Folder name
   */
  name: string;
  /**
   * Folder description
   */
  description?: string;
  /**
   * Parent folder UUID (null for root)
   */
  parent_folder_id?: string | null;
  /**
   * Materialized path (e.g., /uuid1/uuid2/)
   */
  path: string;
  /**
   * Nesting depth (0 = root, max 10)
   */
  depth: number;
  /**
   * Creation timestamp in ISO format
   */
  created_at: string;
  /**
   * Update timestamp in ISO format
   */
  updated_at: string;
  /**
   * Whether the current user owns this folder
   */
  is_owner: boolean;
  /**
   * Display name of the folder owner (only set for shared folders, i.e. is_owner=False)
   */
  owner_name?: string | null;
  /**
   * Number of workflows in this folder
   */
  workflow_count?: number;
  /**
   * Child folders (for tree view)
   */
  children?: FolderInfo[];
}
/**
 * Response for workflow_folder:delete request
 */
export interface FolderDeleteResponse {
  /**
   * Whether deletion was successful
   */
  success: boolean;
  /**
   * Success or error message
   */
  message: string;
}
/**
 * Response for workflow_folder:get request
 */
export interface FolderGetResponse {
  folder: FolderInfo;
}
/**
 * Folder details
 */

/**
 * Response for workflow_folder:list request
 */
export interface FolderListResponse {
  /**
   * List of folders
   */
  folders: FolderInfo[];
}
/**
 * Response for workflow_folder:get_path request
 */
export interface FolderPathResponse {
  /**
   * Breadcrumb path from root to target folder
   */
  path: {
    [k: string]: unknown;
  }[];
}
/**
 * Response for workflow_folder:get_tree request
 */
export interface FolderTreeResponse {
  /**
   * Root-level folders with nested children
   */
  folders: FolderInfo[];
}
/**
 * Response for workflow_folder:update request
 */
export interface FolderUpdateResponse {
  /**
   * Whether update was successful
   */
  success: boolean;
  /**
   * Updated folder info
   */
  folder?: FolderInfo | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Information about a forked resource
 */
export interface ForkedResourceInfo {
  /**
   * UUID of the forked resource
   */
  id: string;
  /**
   * Name of the forked resource
   */
  name: string;
  /**
   * Type of resource (workflow, database)
   */
  resource_type: string;
  /**
   * Owner ID (for personal resources)
   */
  owner_id?: string | null;
  /**
   * Organization ID (for org resources)
   */
  organization_id?: string | null;
  /**
   * UUID of the original resource
   */
  forked_from_id: string;
  /**
   * Name of the original resource
   */
  forked_from_name: string;
}
/**
 * Response for gitlab:oauth:exchange request
 */
export interface GitLabOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * GitLab user name for display
   */
  name?: string | null;
  /**
   * GitLab account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for gitlab:oauth:refresh request
 */
export interface GitLabOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for gitlab:oauth:validate request
 */
export interface GitLabOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * GitLab user name
   */
  name?: string | null;
  /**
   * GitLab account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for github:oauth:exchange request
 */
export interface GithubOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * GitHub username for display
   */
  login?: string | null;
  /**
   * GitHub account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for github:oauth:refresh request
 */
export interface GithubOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for github:oauth:validate request
 */
export interface GithubOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * GitHub username
   */
  login?: string | null;
  /**
   * GitHub account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for google:oauth:exchange request
 */
export interface GoogleOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Credential type of the created Google credential
   */
  credential_type?: string | null;
  /**
   * Google account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for google:oauth:refresh request
 */
export interface GoogleOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for google:oauth:validate request
 */
export interface GoogleOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Google account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for hubspot:oauth:exchange request
 */
export interface HubSpotOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * HubSpot account email for display
   */
  email?: string | null;
  /**
   * HubSpot Hub ID
   */
  hub_id?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for hubspot:oauth:refresh request
 */
export interface HubSpotOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for hubspot:oauth:validate request
 */
export interface HubSpotOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * HubSpot Hub ID
   */
  hub_id?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for instagram_login:oauth:exchange request
 */
export interface InstagramLoginOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Instagram username for display
   */
  name?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for instagram_login:oauth:refresh request
 */
export interface InstagramLoginOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for instagram_login:oauth:validate request
 */
export interface InstagramLoginOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires soon
   */
  expires_soon?: boolean;
  /**
   * Instagram username
   */
  name?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for intercom:oauth:exchange request
 */
export interface IntercomOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Intercom admin/workspace name for display
   */
  name?: string | null;
  /**
   * Intercom account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for intercom:oauth:refresh request (no-op: tokens never expire)
 */
export interface IntercomOAuthRefreshResponse {
  /**
   * Whether the refresh request succeeded
   */
  success: boolean;
  /**
   * Always None — Intercom tokens never expire
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for intercom:oauth:validate request
 */
export interface IntercomOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * Always False — Intercom tokens never expire
   */
  expires_soon?: boolean;
  /**
   * Intercom admin/workspace name
   */
  name?: string | null;
  /**
   * Intercom account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Information about a single interface block on the grid
 */
export interface InterfaceBlockInfo {
  /**
   * Block/node ID
   */
  id: string;
  /**
   * Block type (e.g. 'form', 'markdown')
   */
  type: string;
  /**
   * Grid column position
   */
  x: number;
  /**
   * Grid row position
   */
  y: number;
  /**
   * Width in grid columns
   */
  w: number;
  /**
   * Height in grid rows
   */
  h: number;
  /**
   * Minimum width in grid columns
   */
  minW?: number;
  /**
   * Minimum height in grid rows
   */
  minH?: number;
}
/**
 * Response for klaviyo:oauth:exchange request
 */
export interface KlaviyoOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for klaviyo:oauth:refresh request
 */
export interface KlaviyoOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for klaviyo:oauth:validate request
 */
export interface KlaviyoOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Klaviyo account name
   */
  name?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for linear:oauth:exchange request
 */
export interface LinearOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Linear user name for display
   */
  name?: string | null;
  /**
   * Linear account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for linear:oauth:refresh request
 */
export interface LinearOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for linear:oauth:validate request
 */
export interface LinearOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Linear user name
   */
  name?: string | null;
  /**
   * Linear account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for linkedin:oauth:exchange request
 */
export interface LinkedInOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * LinkedIn account email for display
   */
  email?: string | null;
  /**
   * LinkedIn display name
   */
  name?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for linkedin:oauth:refresh request
 */
export interface LinkedInOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for linkedin:oauth:validate request
 */
export interface LinkedInOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * LinkedIn account email
   */
  email?: string | null;
  /**
   * LinkedIn display name
   */
  name?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for mcp:oauth:discover request
 */
export interface MCPOAuthDiscoverResponse {
  /**
   * Whether discovery was successful
   */
  success?: boolean;
  /**
   * Whether the MCP server requires OAuth
   */
  requires_oauth: boolean;
  /**
   * Name of the OAuth provider
   */
  provider_name?: string | null;
  /**
   * OAuth authorization endpoint URL
   */
  authorization_endpoint?: string | null;
  /**
   * OAuth token endpoint URL
   */
  token_endpoint?: string | null;
  /**
   * Supported OAuth scopes
   */
  scopes_supported?: string[] | null;
  /**
   * Whether dynamic client registration is supported
   */
  supports_dynamic_registration?: boolean;
  /**
   * Dynamic client registration endpoint
   */
  registration_endpoint?: string | null;
  /**
   * PKCE code verifier
   */
  code_verifier?: string | null;
  /**
   * PKCE code challenge
   */
  code_challenge?: string | null;
  /**
   * Resource URL for token request
   */
  resource_url?: string | null;
  /**
   * Error message if discovery failed
   */
  error?: string | null;
}
/**
 * Response for mcp:oauth:exchange request
 */
export interface MCPOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Provider name
   */
  provider_name?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for mcp:oauth:register-client request
 */
export interface MCPOAuthRegisterClientResponse {
  /**
   * Whether client registration was successful
   */
  success: boolean;
  /**
   * Registered OAuth client ID
   */
  client_id?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for mailchimp:oauth:exchange request
 */
export interface MailchimpOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Mailchimp account email for display
   */
  email?: string | null;
  /**
   * Mailchimp datacenter (e.g., 'us1')
   */
  server_prefix?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for meta:oauth:exchange request
 */
export interface MetaOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Meta account name for display
   */
  name?: string | null;
  /**
   * Meta account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for meta:oauth:refresh request
 */
export interface MetaOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for meta:oauth:validate request
 */
export interface MetaOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires soon
   */
  expires_soon?: boolean;
  /**
   * Meta account name
   */
  name?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for microsoft:oauth:exchange request
 */
export interface MicrosoftOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Microsoft account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for microsoft:oauth:refresh request
 */
export interface MicrosoftOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for microsoft:oauth:validate request
 */
export interface MicrosoftOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Microsoft account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for monday:oauth:exchange request
 */
export interface MondayOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * monday user name for display
   */
  name?: string | null;
  /**
   * monday account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for monday:oauth:refresh request
 */
export interface MondayOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for monday:oauth:validate request
 */
export interface MondayOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * monday user name
   */
  name?: string | null;
  /**
   * monday account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for notion:oauth:exchange request
 */
export interface NotionOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Notion workspace name for display
   */
  workspace_name?: string | null;
  /**
   * Notion workspace ID
   */
  workspace_id?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for notion:oauth:refresh request
 */
export interface NotionOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for notion:oauth:validate request
 */
export interface NotionOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Notion workspace name
   */
  workspace_name?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for pagerduty:oauth:exchange request
 */
export interface PagerDutyOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * PagerDuty user name for display
   */
  name?: string | null;
  /**
   * PagerDuty account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for pagerduty:oauth:refresh request
 */
export interface PagerDutyOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for pagerduty:oauth:validate request
 */
export interface PagerDutyOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * PagerDuty user name
   */
  name?: string | null;
  /**
   * PagerDuty account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for parallel:oauth:exchange.
 */
export interface ParallelOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for parallel:oauth:validate.
 */
export interface ParallelOAuthValidateResponse {
  /**
   * Whether the API key is still active
   */
  valid: boolean;
}
/**
 * Response for pipedrive:oauth:exchange request
 */
export interface PipedriveOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Pipedrive user name for display
   */
  name?: string | null;
  /**
   * Pipedrive account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for pipedrive:oauth:refresh request
 */
export interface PipedriveOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for pipedrive:oauth:validate request
 */
export interface PipedriveOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Pipedrive user name
   */
  name?: string | null;
  /**
   * Pipedrive account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for posthog:oauth:exchange request
 */
export interface PostHogOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * PostHog user name for display
   */
  name?: string | null;
  /**
   * PostHog account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for posthog:oauth:refresh request
 */
export interface PostHogOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for posthog:oauth:validate request
 */
export interface PostHogOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * PostHog user name
   */
  name?: string | null;
  /**
   * PostHog account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for quickbooks:oauth:exchange request
 */
export interface QuickBooksOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * QuickBooks user name for display
   */
  name?: string | null;
  /**
   * QuickBooks account email for display
   */
  email?: string | null;
  /**
   * QuickBooks company (realm) ID
   */
  realm_id?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for quickbooks:oauth:refresh request
 */
export interface QuickBooksOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for quickbooks:oauth:validate request
 */
export interface QuickBooksOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * QuickBooks user name
   */
  name?: string | null;
  /**
   * QuickBooks account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for reddit:oauth:exchange request
 */
export interface RedditOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Reddit username for display
   */
  username?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for reddit:oauth:refresh request
 */
export interface RedditOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for reddit:oauth:validate request
 */
export interface RedditOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Reddit username
   */
  username?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * The staged message as the Test screen renders it. Display-only, and it
 * must agree with the scenario's injected payload — showing one email while
 * injecting another would make the screen a lie.
 */
export interface RehearsalLeadModel {
  /**
   * Subject / channel / contact
   */
  title: string;
  /**
   * One-line sender summary for terse surfaces
   */
  meta: string;
  /**
   * The message text
   */
  body: string;
  /**
   * Sender display name
   */
  author?: string | null;
  /**
   * Sender address — email or phone
   */
  handle?: string | null;
  /**
   * Staged arrival time, display only
   */
  time?: string | null;
}
/**
 * Response for rehearsal:run.
 */
export interface RehearsalRunResponse {
  /**
   * Whether the rehearsal completed
   */
  success: boolean;
  /**
   * Conversation the staged run used; the trace streams under it
   */
  conversation_id?: string | null;
  /**
   * Execution the rehearsal ran as
   */
  execution_id?: string | null;
  /**
   * Why it could not run, when it could not
   */
  message?: string | null;
}
/**
 * Response for rehearsal:scenarios.
 */
export interface RehearsalScenariosResponse {
  success: boolean;
  /**
   * Rehearsable triggers present in this workflow's graph
   */
  triggers?: RehearsalTriggerModel[];
  /**
   * Why listing failed, when it did
   */
  message?: string | null;
}
export interface RehearsalTriggerModel {
  /**
   * Trigger node type the situations arrive through (e.g. 'automation-gmail')
   */
  node_type: string;
  /**
   * The node's selected trigger operation — the FE frames respond to it (a PR trigger renders a PR card)
   */
  operation?: string | null;
  situations?: RehearsalSituationModel[];
}
export interface RehearsalSituationModel {
  /**
   * Scenario slug to pass to rehearsal:run
   */
  key: string;
  /**
   * The situation's name ('Qualified lead')
   */
  name: string;
  lead: RehearsalLeadModel;
}
/**
 * The staged message, for display
 */

/**
 * Response for resource:create request
 */
export interface ResourceCreateResponse {
  /**
   * Whether creation was successful
   */
  success: boolean;
  /**
   * Created resource info
   */
  resource?: ResourceInfo | null;
}
/**
 * Information about a workflow resource
 */
export interface ResourceInfo {
  /**
   * Resource UUID
   */
  id: string;
  /**
   * Owner user UUID
   */
  owner_id: string;
  /**
   * Organization UUID if applicable
   */
  organization_id?: string | null;
  /**
   * Parent workflow UUID
   */
  workflow_id: string;
  /**
   * Workflow node ID that produced this resource
   */
  node_id?: string | null;
  /**
   * Type: dataset, file, image, video, audio, document
   */
  resource_type: string;
  /**
   * Display name
   */
  name: string;
  /**
   * MIME type for blob resources
   */
  mime_type?: string | null;
  /**
   * File size in bytes
   */
  size_bytes?: number;
  /**
   * R2 storage key for blobs
   */
  storage_ref?: string | null;
  /**
   * Arbitrary metadata
   */
  metadata?: {
    [k: string]: unknown;
  };
  /**
   * Creation timestamp ISO string
   */
  created_at: string;
  /**
   * Last update timestamp ISO string
   */
  updated_at: string;
}
/**
 * Response for resource:dataset:append request
 */
export interface ResourceDatasetAppendResponse {
  /**
   * Whether append was successful
   */
  success: boolean;
  /**
   * Number of rows inserted
   */
  inserted_count: number;
}
/**
 * Response for resource:dataset:delete_rows request
 */
export interface ResourceDatasetDeleteRowsResponse {
  /**
   * Whether deletion was successful
   */
  success: boolean;
  /**
   * Number of rows deleted
   */
  deleted_count: number;
}
/**
 * Response for resource:dataset:rows request
 */
export interface ResourceDatasetRowsResponse {
  /**
   * Dataset rows
   */
  rows: DatasetRowInfo[];
  /**
   * Total number of rows in the dataset
   */
  total_count: number;
}
/**
 * Response for resource:dataset:update_row request
 */
export interface ResourceDatasetUpdateRowResponse {
  /**
   * Whether update was successful
   */
  success: boolean;
}
/**
 * Response for resource:delete request
 */
export interface ResourceDeleteResponse {
  /**
   * Whether deletion was successful
   */
  success: boolean;
  /**
   * Success or error message
   */
  message: string;
}
/**
 * Response for resource:download_url request
 */
export interface ResourceDownloadUrlResponse {
  /**
   * Presigned GET URL
   */
  download_url: string;
}
/**
 * Response for resource:fork request
 */
export interface ResourceForkResponse {
  /**
   * Whether fork was successful
   */
  success: boolean;
  /**
   * Info about the newly created fork
   */
  forked_resource?: ForkedResourceInfo | null;
  /**
   * Success message
   */
  message?: string | null;
  /**
   * Error message if failed
   */
  error?: string | null;
}
/**
 * Response for resource:get request
 */
export interface ResourceGetResponse {
  resource: ResourceInfo1;
}
/**
 * Information about a workflow resource
 */
export interface ResourceInfo1 {
  /**
   * Resource UUID
   */
  id: string;
  /**
   * Owner user UUID
   */
  owner_id: string;
  /**
   * Organization UUID if applicable
   */
  organization_id?: string | null;
  /**
   * Parent workflow UUID
   */
  workflow_id: string;
  /**
   * Workflow node ID that produced this resource
   */
  node_id?: string | null;
  /**
   * Type: dataset, file, image, video, audio, document
   */
  resource_type: string;
  /**
   * Display name
   */
  name: string;
  /**
   * MIME type for blob resources
   */
  mime_type?: string | null;
  /**
   * File size in bytes
   */
  size_bytes?: number;
  /**
   * R2 storage key for blobs
   */
  storage_ref?: string | null;
  /**
   * Arbitrary metadata
   */
  metadata?: {
    [k: string]: unknown;
  };
  /**
   * Creation timestamp ISO string
   */
  created_at: string;
  /**
   * Last update timestamp ISO string
   */
  updated_at: string;
}
/**
 * Response for resource:list request
 */
export interface ResourceListResponse {
  /**
   * List of resources
   */
  resources: ResourceInfo[];
}
/**
 * Response for resource:upload_url request
 */
export interface ResourceUploadUrlResponse {
  /**
   * Presigned PUT URL
   */
  upload_url: string;
  /**
   * R2 key for the uploaded file
   */
  storage_ref: string;
}
/**
 * Response for run_share:create — the public read-only page for one
 * finished Test Run.
 */
export interface RunShareCreateResponse {
  /**
   * Whether the link was minted
   */
  success: boolean;
  /**
   * Capability id (None when error is set)
   */
  link_id?: string | null;
  /**
   * Public run page URL (/r/{link_id})
   */
  url?: string | null;
  /**
   * Error message if failed
   */
  error?: string | null;
}
/**
 * Response for salesforce:oauth:exchange request
 */
export interface SalesforceOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Salesforce username for display
   */
  username?: string | null;
  /**
   * Salesforce account email for display
   */
  email?: string | null;
  /**
   * Salesforce organization ID
   */
  organization_id?: string | null;
  /**
   * Salesforce instance URL
   */
  instance_url?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for salesforce:oauth:refresh request
 */
export interface SalesforceOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for salesforce:oauth:validate request
 */
export interface SalesforceOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Salesforce username
   */
  username?: string | null;
  /**
   * Salesforce account email
   */
  email?: string | null;
  /**
   * Salesforce organization ID
   */
  organization_id?: string | null;
  /**
   * Salesforce instance URL
   */
  instance_url?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for saved_output:create request
 */
export interface SavedOutputCreateResponse {
  /**
   * Whether creation was successful
   */
  success: boolean;
  /**
   * Created saved output info
   */
  saved_output?: SavedOutputInfo | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Information about a saved output
 */
export interface SavedOutputInfo {
  /**
   * UUID of the saved output
   */
  id: string;
  /**
   * UUID of the owner
   */
  user_id: string;
  /**
   * Type of the node this output is for
   */
  node_type: string;
  /**
   * User-provided name for this saved output
   */
  name: string;
  /**
   * The saved output data
   */
  output: {
    [k: string]: unknown;
  };
  /**
   * Visibility level: 'user', 'organization', or 'public'
   */
  visibility: string;
  /**
   * Creation timestamp in ISO format
   */
  created_at: string;
  /**
   * Last update timestamp in ISO format
   */
  updated_at: string;
}
/**
 * Response for saved_output:delete request
 */
export interface SavedOutputDeleteResponse {
  /**
   * Whether deletion was successful
   */
  success: boolean;
  /**
   * Success or error message
   */
  message: string;
  /**
   * UUID of the deleted saved output
   */
  saved_output_id?: string | null;
}
/**
 * Response for saved_output:get request
 */
export interface SavedOutputGetResponse {
  saved_output: SavedOutputInfo1;
}
/**
 * Information about a saved output
 */
export interface SavedOutputInfo1 {
  /**
   * UUID of the saved output
   */
  id: string;
  /**
   * UUID of the owner
   */
  user_id: string;
  /**
   * Type of the node this output is for
   */
  node_type: string;
  /**
   * User-provided name for this saved output
   */
  name: string;
  /**
   * The saved output data
   */
  output: {
    [k: string]: unknown;
  };
  /**
   * Visibility level: 'user', 'organization', or 'public'
   */
  visibility: string;
  /**
   * Creation timestamp in ISO format
   */
  created_at: string;
  /**
   * Last update timestamp in ISO format
   */
  updated_at: string;
}
/**
 * Response for saved_output:list request
 */
export interface SavedOutputListResponse {
  /**
   * List of saved outputs
   */
  saved_outputs: SavedOutputInfo[];
}
/**
 * Response for saved_output:update request
 */
export interface SavedOutputUpdateResponse {
  /**
   * Whether update was successful
   */
  success: boolean;
  /**
   * Updated saved output info
   */
  saved_output?: SavedOutputInfo | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for sentry:oauth:exchange request
 */
export interface SentryOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Sentry user name for display
   */
  name?: string | null;
  /**
   * Sentry account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for sentry:oauth:refresh request
 */
export interface SentryOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for sentry:oauth:validate request
 */
export interface SentryOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Sentry user name
   */
  name?: string | null;
  /**
   * Sentry account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for share:create request
 */
export interface ShareCreateResponse {
  /**
   * Whether share was created successfully
   */
  success: boolean;
  /**
   * Created share info
   */
  share?: ShareInfo | null;
  /**
   * Success or error message
   */
  message?: string | null;
  /**
   * Error message if failed
   */
  error?: string | null;
}
/**
 * Information about a resource share
 */
export interface ShareInfo {
  /**
   * UUID of the share
   */
  id: string;
  /**
   * Type of resource (workflow, database)
   */
  resource_type: string;
  /**
   * UUID of the shared resource
   */
  resource_id: string;
  /**
   * Share target type (user, organization, public)
   */
  target_type: string;
  /**
   * UUID of target user (if user share)
   */
  target_user_id?: string | null;
  /**
   * Email of target user (for pending invites)
   */
  target_email?: string | null;
  /**
   * Avatar URL of target user (if user share)
   */
  target_avatar_url?: string | null;
  /**
   * UUID of target org (if org share)
   */
  target_org_id?: string | null;
  /**
   * Name of target org (for display)
   */
  target_org_name?: string | null;
  /**
   * Icon URL of target org (if org share)
   */
  target_org_icon_url?: string | null;
  /**
   * Display name of target (email, org name, or 'Anyone with the link')
   */
  target_display_name?: string | null;
  /**
   * Permission level (view, edit)
   */
  permission: string;
  /**
   * UUID of user who created the share
   */
  shared_by: string;
  /**
   * Email of user who created the share
   */
  shared_by_email?: string | null;
  /**
   * Creation timestamp in ISO format
   */
  created_at: string;
  /**
   * True if share is for a user who hasn't signed up yet
   */
  is_pending?: boolean;
  /**
   * Public share URL (if public share)
   */
  public_url?: string | null;
}
/**
 * Response for share:delete request
 */
export interface ShareDeleteResponse {
  /**
   * Whether deletion was successful
   */
  success: boolean;
  /**
   * Success or error message
   */
  message?: string;
  /**
   * UUID of the deleted share
   */
  share_id?: string | null;
  /**
   * Error message if failed
   */
  error?: string | null;
}
/**
 * Response for share:invite_accept request
 */
export interface ShareInviteAcceptResponse {
  /**
   * Whether the invite was redeemed
   */
  success: boolean;
  /**
   * UUID of the workflow the user now collaborates on
   */
  workflow_id?: string | null;
  /**
   * Name of the workflow (for display)
   */
  workflow_name?: string | null;
  /**
   * True when the joiner was onboarded by the redeem (frontend should refresh the session JWT so the onboarding_completed claim updates)
   */
  refresh_jwt?: boolean;
  /**
   * Error message if failed
   */
  error?: string | null;
}
/**
 * Response for share:invite_link request
 */
export interface ShareInviteLinkResponse {
  /**
   * Whether the invite link is available
   */
  success: boolean;
  /**
   * Invite link token (carried in the /i/<token> URL)
   */
  token?: string | null;
  /**
   * Full shareable invite URL
   */
  url?: string | null;
  /**
   * Permission granted on redemption (view, edit)
   */
  permission?: string | null;
  /**
   * Error message if failed
   */
  error?: string | null;
}
/**
 * Response for share:leave request
 */
export interface ShareLeaveResponse {
  /**
   * Whether the request was handled
   */
  success: boolean;
  /**
   * UUID of the resource the caller left
   */
  resource_id?: string | null;
  /**
   * True if a direct user-share row was actually deleted; False if the caller had no direct share (access came via an org/folder share, which this can't drop)
   */
  removed?: boolean;
  /**
   * Error message if failed
   */
  error?: string | null;
}
/**
 * Response for share:list request
 */
export interface ShareListResponse {
  /**
   * List of shares for the resource
   */
  shares?: ShareInfo[];
  /**
   * Error message if failed
   */
  error?: string | null;
}
/**
 * Response for share:list_shared_with_me request
 */
export interface ShareListSharedWithMeResponse {
  /**
   * List of resources shared with user
   */
  resources?: SharedResourceInfo[];
  /**
   * Error message if failed
   */
  error?: string | null;
}
/**
 * Information about a resource shared with the current user
 */
export interface SharedResourceInfo {
  /**
   * Type of resource (workflow, database)
   */
  resource_type: string;
  /**
   * UUID of the resource
   */
  resource_id: string;
  /**
   * Name of the resource
   */
  resource_name: string;
  /**
   * Description of the resource
   */
  resource_description?: string | null;
  /**
   * Permission level (view, edit)
   */
  permission: string;
  /**
   * Email of user who shared the resource
   */
  shared_by_email: string;
  /**
   * Display name of user who shared
   */
  shared_by_name?: string | null;
  /**
   * When the resource was shared
   */
  shared_at: string;
  /**
   * Organization ID if resource is in an org
   */
  organization_id?: string | null;
  /**
   * Organization name for display
   */
  organization_name?: string | null;
}
/**
 * Response for share:update request
 */
export interface ShareUpdateResponse {
  /**
   * Whether update was successful
   */
  success: boolean;
  /**
   * Updated share info
   */
  share?: ShareInfo | null;
  /**
   * Success or error message
   */
  message?: string | null;
  /**
   * Error message if failed
   */
  error?: string | null;
}
/**
 * Ack for shared_agent:send — emitted before the agent turn runs; the
 * turn itself streams via chat:message / agent:state on the visitor's sid.
 */
export interface SharedAgentAckResponse {
  /**
   * Whether the turn was dispatched
   */
  accepted: boolean;
  /**
   * Conversation id the streamed events will carry
   */
  conversation_id?: string | null;
  /**
   * link_inactive | busy | agent_unavailable
   */
  error?: string | null;
}
/**
 * Response for shared_agent:resume — the visitor's own thread history.
 */
export interface SharedAgentResumeResponse {
  /**
   * Conversation id for the visitor's thread
   */
  conversation_id?: string | null;
  /**
   * Persisted chat events for the thread
   */
  messages?: {
    [k: string]: unknown;
  }[];
  /**
   * link_inactive if the link no longer resolves
   */
  error?: string | null;
}
/**
 * Response for shopify:oauth:exchange request
 */
export interface ShopifyOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Shopify store name for display
   */
  shop_name?: string | null;
  /**
   * Shopify account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for shopify:oauth:refresh request
 */
export interface ShopifyOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for shopify:oauth:validate request
 */
export interface ShopifyOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Shopify store name
   */
  shop_name?: string | null;
  /**
   * Shopify account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for skill:create.
 */
export interface SkillCreateResponse {
  /**
   * Whether creation succeeded
   */
  success: boolean;
  /**
   * Newly created skill
   */
  skill?: SkillDetail | null;
}
/**
 * Full skill record including bodies.
 */
export interface SkillDetail {
  /**
   * Skill UUID
   */
  id: string;
  /**
   * Author user UUID
   */
  owner_id?: string | null;
  /**
   * Owning org UUID
   */
  organization_id?: string | null;
  /**
   * Platform-maintained skill
   */
  is_system?: boolean;
  /**
   * Skill name
   */
  name: string;
  /**
   * Few-sentence retrieval hint
   */
  description?: string;
  /**
   * Optional prose body
   */
  body_text?: string | null;
  /**
   * Optional workflow graph (same shape as workflows.workflow)
   */
  body_workflow?: {
    [k: string]: unknown;
  } | null;
  /**
   * Viewport / UI state for body_workflow
   */
  display_metadata?: {
    [k: string]: unknown;
  };
  /**
   * Owner-side default enabled flag
   */
  enabled?: boolean;
  /**
   * Whether the calling user has muted this skill
   */
  muted?: boolean;
  /**
   * Creation timestamp ISO string
   */
  created_at: string;
  /**
   * Last update timestamp ISO string
   */
  updated_at: string;
}
/**
 * Response for skill:delete.
 */
export interface SkillDeleteResponse {
  /**
   * Whether deletion succeeded
   */
  success: boolean;
  /**
   * Status or error message
   */
  message?: string;
}
/**
 * Response for skill:get / skill:create — full skill detail.
 */
export interface SkillGetResponse {
  skill: SkillDetail1;
}
/**
 * Full skill record including bodies.
 */
export interface SkillDetail1 {
  /**
   * Skill UUID
   */
  id: string;
  /**
   * Author user UUID
   */
  owner_id?: string | null;
  /**
   * Owning org UUID
   */
  organization_id?: string | null;
  /**
   * Platform-maintained skill
   */
  is_system?: boolean;
  /**
   * Skill name
   */
  name: string;
  /**
   * Few-sentence retrieval hint
   */
  description?: string;
  /**
   * Optional prose body
   */
  body_text?: string | null;
  /**
   * Optional workflow graph (same shape as workflows.workflow)
   */
  body_workflow?: {
    [k: string]: unknown;
  } | null;
  /**
   * Viewport / UI state for body_workflow
   */
  display_metadata?: {
    [k: string]: unknown;
  };
  /**
   * Owner-side default enabled flag
   */
  enabled?: boolean;
  /**
   * Whether the calling user has muted this skill
   */
  muted?: boolean;
  /**
   * Creation timestamp ISO string
   */
  created_at: string;
  /**
   * Last update timestamp ISO string
   */
  updated_at: string;
}
/**
 * Response for skill:list — buckets skills by relationship to the caller.
 *
 * The `system` field is omitted entirely for non-internal users (skills they
 * can't see don't even appear as an empty bucket).
 */
export interface SkillListResponse {
  /**
   * Skills the caller authored or is in the org of
   */
  owned?: SkillSummary[];
  /**
   * Skills shared with the caller via resource_shares
   */
  shared?: SkillSummary[];
  /**
   * Platform-maintained skills (internal users only)
   */
  system?: SkillSummary[] | null;
}
/**
 * Lightweight skill listing entry — body fields stripped for list views.
 */
export interface SkillSummary {
  /**
   * Skill UUID
   */
  id: string;
  /**
   * Author user UUID (NULL for system skills)
   */
  owner_id?: string | null;
  /**
   * Owning org UUID (NULL for system skills)
   */
  organization_id?: string | null;
  /**
   * Platform-maintained skill loaded for every builder call
   */
  is_system?: boolean;
  /**
   * Skill name
   */
  name: string;
  /**
   * Few-sentence retrieval hint
   */
  description?: string;
  /**
   * Whether body_text is non-empty
   */
  has_text?: boolean;
  /**
   * Whether body_workflow is non-empty
   */
  has_workflow?: boolean;
  /**
   * Owner-side default enabled flag
   */
  enabled?: boolean;
  /**
   * Whether the calling user has muted this skill
   */
  muted?: boolean;
  /**
   * Creation timestamp ISO string
   */
  created_at: string;
  /**
   * Last update timestamp ISO string
   */
  updated_at: string;
}
/**
 * Response for skill:mute / skill:unmute.
 */
export interface SkillMuteResponse {
  /**
   * Whether the mute state change succeeded
   */
  success: boolean;
  /**
   * Resulting mute state for this skill
   */
  muted: boolean;
}
/**
 * Response for skill:update.
 */
export interface SkillUpdateResponse {
  /**
   * Whether update succeeded
   */
  success: boolean;
  /**
   * Updated skill
   */
  skill?: SkillDetail | null;
}
/**
 * Response for skill:update_workflow.
 */
export interface SkillUpdateWorkflowResponse {
  /**
   * Whether the workflow body was saved
   */
  success: boolean;
}
/**
 * Response for skill:get_workflow — returns just the workflow body + display metadata.
 */
export interface SkillWorkflowResponse {
  /**
   * Skill UUID
   */
  skill_id: string;
  /**
   * Workflow graph
   */
  body_workflow?: {
    [k: string]: unknown;
  } | null;
  /**
   * Viewport / UI state
   */
  display_metadata?: {
    [k: string]: unknown;
  };
}
/**
 * Response for slack:oauth:exchange request
 */
export interface SlackOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Slack workspace ID for display
   */
  team_id?: string | null;
  /**
   * Slack workspace name for display
   */
  team_name?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for slack:oauth:refresh request
 */
export interface SlackOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for slack:oauth:validate request
 */
export interface SlackOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Slack workspace name
   */
  team_name?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for stripe:oauth:exchange request
 */
export interface StripeOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Stripe account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for stripe:oauth:refresh request
 */
export interface StripeOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for stripe:oauth:validate request
 */
export interface StripeOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Stripe account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for supabase:oauth:exchange / refresh / validate / select_project requests
 */
export interface SupabaseOAuthExchangeResponse {
  /**
   * Whether the operation was successful
   */
  success: boolean;
  /**
   * UUID of the created/updated credential
   */
  credential_id?: string | null;
  /**
   * Name of the credential
   */
  credential_name?: string | null;
  /**
   * Supabase project URL
   */
  project_url?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
  /**
   * True when user must pick from multiple projects
   */
  needs_project_selection?: boolean;
  /**
   * List of projects when needs_project_selection is True
   */
  projects?: unknown[] | null;
  /**
   * Opaque token for select_project follow-up
   */
  pending_id?: string | null;
}
/**
 * Response for threads:oauth:exchange request
 */
export interface ThreadsOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Threads username for display
   */
  name?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for threads:oauth:refresh request
 */
export interface ThreadsOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for threads:oauth:validate request
 */
export interface ThreadsOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires soon
   */
  expires_soon?: boolean;
  /**
   * Threads username
   */
  name?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for tiktok:oauth:exchange request
 */
export interface TikTokOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * TikTok display name for the connected account
   */
  display_name?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for tiktok:oauth:refresh request
 */
export interface TikTokOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for tiktok:oauth:validate request
 */
export interface TikTokOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 60 minutes
   */
  expires_soon?: boolean;
  /**
   * TikTok display name for the connected account
   */
  display_name?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for twitter:oauth:exchange request
 */
export interface TwitterOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Twitter username for display
   */
  username?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for twitter:oauth:refresh request
 */
export interface TwitterOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for twitter:oauth:validate request
 */
export interface TwitterOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Twitter username
   */
  username?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Generic typed response event that preserves type information.
 * This is used internally to wrap typed responses before sending.
 */
export interface TypedResponseEvent {
  /**
   * Correlation ID from request
   */
  request_id: string;
  data: BaseModel;
  /**
   * Error message if failed
   */
  error?: string | null;
}
/**
 * Typed response data
 */
export interface BaseModel {
  [k: string]: unknown;
}
/**
 * Response for typeform:oauth:exchange request
 */
export interface TypeformOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for webflow:oauth:exchange request
 */
export interface WebflowOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Webflow user name for display
   */
  name?: string | null;
  /**
   * Webflow account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for webflow:oauth:refresh request
 */
export interface WebflowOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for webflow:oauth:validate request
 */
export interface WebflowOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Webflow user name
   */
  name?: string | null;
  /**
   * Webflow account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for whatsapp:qr:start — returns QR code for scanning
 */
export interface WhatsAppQRStartResponse {
  /**
   * Whether QR code generation was successful
   */
  success: boolean;
  /**
   * WAHooks connection ID
   */
  connection_id?: string | null;
  /**
   * Base64 encoded QR code PNG image
   */
  qr_code?: string | null;
  /**
   * Status or error message
   */
  message?: string | null;
  /**
   * Machine-readable failure class, e.g. wahooks_key_missing
   */
  code?: string | null;
}
/**
 * Response for whatsapp:qr:status — returns connection status
 */
export interface WhatsAppQRStatusResponse {
  /**
   * Whether the status check succeeded
   */
  success: boolean;
  /**
   * One of: pending, connected, error
   */
  status?: string;
  /**
   * UUID of the created credential (when connected)
   */
  credential_id?: string | null;
  /**
   * Name of the created credential (when connected)
   */
  credential_name?: string | null;
  /**
   * Connected phone number (when connected)
   */
  phone_number?: string | null;
  /**
   * New QR code if previous one expired
   */
  qr_code?: string | null;
  /**
   * Status or error message
   */
  message?: string | null;
}
/**
 * Response for wordpress:oauth:exchange request
 */
export interface WordPressOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * WordPress.com account email for display
   */
  email?: string | null;
  /**
   * WordPress.com username for display
   */
  username?: string | null;
  /**
   * WordPress.com site URL for display
   */
  site_url?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for wordpress:oauth:refresh request
 */
export interface WordPressOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for wordpress:oauth:validate request
 */
export interface WordPressOAuthValidateResponse {
  /**
   * Whether validation was successful
   */
  success: boolean;
  /**
   * Whether the OAuth token is valid
   */
  is_valid: boolean;
  /**
   * Validation details or error message
   */
  message?: string | null;
}
/**
 * Response for workflow:checkpoint:create request
 */
export interface WorkflowCheckpointCreateResponse {
  /**
   * Whether creation was successful
   */
  success: boolean;
  /**
   * Created checkpoint info
   */
  checkpoint?: CheckpointInfo | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for workflow:checkpoint:delete request
 */
export interface WorkflowCheckpointDeleteResponse {
  /**
   * Whether deletion was successful
   */
  success: boolean;
  /**
   * Success or error message
   */
  message: string;
  /**
   * UUID of the deleted checkpoint
   */
  checkpoint_id?: string | null;
}
/**
 * Response for workflow:checkpoint:list request
 */
export interface WorkflowCheckpointListResponse {
  /**
   * List of checkpoints
   */
  checkpoints?: CheckpointInfo[];
}
/**
 * Response for workflow:checkpoint:restore request
 */
export interface WorkflowCheckpointRestoreResponse {
  /**
   * Whether restore was successful
   */
  success: boolean;
  /**
   * Restored workflow (nodes, edges)
   */
  workflow?: {
    [k: string]: unknown;
  } | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for workflow:collab_token request - JWT for workflow relay authentication
 */
export interface WorkflowCollabTokenResponse {
  /**
   * Whether token generation was successful
   */
  success: boolean;
  /**
   * JWT token for workflow relay authentication
   */
  token?: string | null;
  /**
   * Token expiration timestamp (Unix epoch seconds)
   */
  expires_at?: number | null;
  /**
   * Error message if generation failed
   */
  message?: string | null;
}
/**
 * Response for workflow:create request
 */
export interface WorkflowCreateResponse {
  /**
   * Whether creation was successful
   */
  success: boolean;
  /**
   * Created workflow info
   */
  workflow?: WorkflowInfo | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Workflow information structure
 */
export interface WorkflowInfo {
  /**
   * Workflow UUID
   */
  id: string;
  /**
   * Human-readable name for the workflow
   */
  name: string;
  /**
   * Workflow description
   */
  description?: string;
  /**
   * Workflow configuration including nodes and edges. None when not included in response (e.g., metadata-only updates).
   */
  workflow_data?: {
    [k: string]: unknown;
  } | null;
  /**
   * Access permissions for sharing
   */
  permissions?: {
    [k: string]: unknown;
  };
  /**
   * Creation timestamp in ISO format
   */
  created_at: string;
  /**
   * Last update timestamp in ISO format
   */
  updated_at: string;
  /**
   * UI display state: viewport (x,y,zoom), selectedNodeId, flowHelperView state
   */
  display_metadata?: {
    [k: string]: unknown;
  } | null;
  /**
   * Folder UUID this workflow belongs to, or None for root-level workflows
   */
  folder_id?: string | null;
  /**
   * Current user's permission level: 'owner', 'edit', 'view', or None if not set
   */
  user_permission?: string | null;
  /**
   * Whether the current user is the owner of this workflow
   */
  is_owner?: boolean | null;
  /**
   * Display name of the workflow owner (only set for shared workflows, i.e. is_owner=False)
   */
  owner_name?: string | null;
  /**
   * Workflow-level settings (e.g. min_required_balance)
   */
  settings?: {
    [k: string]: unknown;
  } | null;
  /**
   * Optimistic-concurrency version of the workflow blob. Bumped by a DB trigger on every blob change; clients echo it as expected_graph_version on workflow:update so stale snapshots lose cleanly instead of clobbering.
   */
  graph_version?: number | null;
}
/**
 * Response for workflow:delete request
 */
export interface WorkflowDeleteResponse {
  /**
   * Whether deletion was successful
   */
  success: boolean;
  /**
   * Success or error message
   */
  message: string;
  /**
   * UUID of the deleted workflow
   */
  workflow_id?: string | null;
}
/**
 * Response for workflow:get_execution_counts.
 *
 * Raw DB status counts (frontend maps to UI labels — e.g. 'completed' →
 * 'success', 'awaiting_*' → 'waiting'). Trigger counts use the raw
 * trigger_source values defined by the table's CHECK constraint
 * (manual/webhook/cron/mcp/api).
 */
export interface WorkflowExecutionCountsResponse {
  /**
   * Total executions for this workflow.
   */
  total: number;
  /**
   * DB-status → count for non-zero statuses.
   */
  by_status: {
    [k: string]: number;
  };
  /**
   * trigger_source → count for non-zero triggers.
   */
  by_trigger: {
    [k: string]: number;
  };
}
/**
 * Workflow execution log information
 */
export interface WorkflowExecutionInfo {
  /**
   * Execution UUID
   */
  id: string;
  /**
   * Workflow UUID
   */
  workflow_id: string;
  /**
   * User UUID who triggered the execution
   */
  user_id: string;
  /**
   * Execution status: running, completed, error
   */
  status: string;
  /**
   * Execution start timestamp in ISO format
   */
  started_at: string;
  /**
   * Execution finish timestamp in ISO format
   */
  finished_at?: string | null;
  /**
   * Number of nodes executed
   */
  nodes_executed?: number;
  /**
   * Error message if execution failed
   */
  error?: string | null;
  /**
   * How the run was triggered: manual/webhook/cron/mcp/api
   */
  trigger_source?: string | null;
  /**
   * Whether a graph snapshot exists for this run (replayable)
   */
  has_graph?: boolean;
}
/**
 * Response for workflow:list_executions request
 */
export interface WorkflowExecutionListResponse {
  /**
   * List of workflow execution logs
   */
  executions: WorkflowExecutionInfo[];
  /**
   * started_at of the last row in this page. Pass back as `cursor_started_at` to fetch the next page. Null when there are no more rows beyond this page.
   */
  next_cursor_started_at?: string | null;
  /**
   * id of the last row in this page; pair with next_cursor_started_at.
   */
  next_cursor_id?: string | null;
}
/**
 * Response for workflow:get request
 */
export interface WorkflowGetResponse {
  workflow: WorkflowInfo1;
  /**
   * Per-node last-run status keyed by node_id
   */
  node_statuses?: {
    [k: string]: unknown;
  };
}
/**
 * Workflow information structure
 */
export interface WorkflowInfo1 {
  /**
   * Workflow UUID
   */
  id: string;
  /**
   * Human-readable name for the workflow
   */
  name: string;
  /**
   * Workflow description
   */
  description?: string;
  /**
   * Workflow configuration including nodes and edges. None when not included in response (e.g., metadata-only updates).
   */
  workflow_data?: {
    [k: string]: unknown;
  } | null;
  /**
   * Access permissions for sharing
   */
  permissions?: {
    [k: string]: unknown;
  };
  /**
   * Creation timestamp in ISO format
   */
  created_at: string;
  /**
   * Last update timestamp in ISO format
   */
  updated_at: string;
  /**
   * UI display state: viewport (x,y,zoom), selectedNodeId, flowHelperView state
   */
  display_metadata?: {
    [k: string]: unknown;
  } | null;
  /**
   * Folder UUID this workflow belongs to, or None for root-level workflows
   */
  folder_id?: string | null;
  /**
   * Current user's permission level: 'owner', 'edit', 'view', or None if not set
   */
  user_permission?: string | null;
  /**
   * Whether the current user is the owner of this workflow
   */
  is_owner?: boolean | null;
  /**
   * Display name of the workflow owner (only set for shared workflows, i.e. is_owner=False)
   */
  owner_name?: string | null;
  /**
   * Workflow-level settings (e.g. min_required_balance)
   */
  settings?: {
    [k: string]: unknown;
  } | null;
  /**
   * Optimistic-concurrency version of the workflow blob. Bumped by a DB trigger on every blob change; clients echo it as expected_graph_version on workflow:update so stale snapshots lose cleanly instead of clobbering.
   */
  graph_version?: number | null;
}
/**
 * Response for workflow:list request
 */
export interface WorkflowListResponse {
  /**
   * List of user's workflows
   */
  workflows: WorkflowInfo[];
  /**
   * Number of shared workflows hidden due to plan limit
   */
  hidden_shared_count?: number;
  /**
   * Current context subscription tier (for limit messaging)
   */
  subscription_tier?: string;
}
/**
 * Response for workflow:list_trash request
 */
export interface WorkflowListTrashResponse {
  /**
   * List of trashed workflows
   */
  workflows: WorkflowTrashInfo[];
}
/**
 * Trashed workflow information for the trash view
 */
export interface WorkflowTrashInfo {
  /**
   * Workflow UUID
   */
  id: string;
  /**
   * Workflow name
   */
  name: string;
  /**
   * Workflow description
   */
  description?: string;
  /**
   * Deletion timestamp in ISO format
   */
  deleted_at: string;
  /**
   * Days remaining before permanent deletion
   */
  days_remaining: number;
}
/**
 * Response for workflow:mcp:create_workflow - dual-delivered to frontend
 */
export interface WorkflowMCPCreateWorkflowResponse {
  /**
   * Whether the creation succeeded
   */
  success: boolean;
  /**
   * ID of the created workflow
   */
  workflow_id: string;
  /**
   * Name of the created workflow
   */
  name: string;
  /**
   * Description of the created workflow
   */
  description?: string | null;
  /**
   * Owning organization, if any
   */
  organization_id?: string | null;
  /**
   * Containing folder, if any
   */
  folder_id?: string | null;
  /**
   * Status message or error
   */
  message?: string | null;
}
/**
 * Response for workflow:mcp:delete_workflow - dual-delivered to frontend
 */
export interface WorkflowMCPDeleteWorkflowResponse {
  /**
   * Whether the deletion succeeded
   */
  success: boolean;
  /**
   * ID of the deleted workflow
   */
  workflow_id: string;
  /**
   * Status message or error
   */
  message?: string | null;
}
/**
 * Response for workflow:mcp:get_node_config
 */
export interface WorkflowMCPGetNodeConfigResponse {
  /**
   * Whether the request succeeded
   */
  success: boolean;
  /**
   * ID of the workflow
   */
  workflow_id: string;
  /**
   * ID of the node
   */
  node_id: string;
  /**
   * Type of the node
   */
  node_type?: string | null;
  /**
   * Node position {x, y}
   */
  position?: {
    [k: string]: number;
  } | null;
  /**
   * Node configuration
   */
  config?: {
    [k: string]: unknown;
  } | null;
  /**
   * Error message if failed
   */
  message?: string | null;
}
/**
 * Information about a workflow node
 */
export interface WorkflowMCPNodeInfo {
  /**
   * Node ID
   */
  id: string;
  /**
   * Node type
   */
  type: string;
  /**
   * Node position {x, y}
   */
  position: {
    [k: string]: number;
  };
  /**
   * Node data including config, output, etc.
   */
  data?: {
    [k: string]: unknown;
  };
}
/**
 * Response for workflow:mcp:update_interface - dual-delivered to frontend
 */
export interface WorkflowMCPUpdateInterfaceResponse {
  /**
   * Whether the interface was updated successfully
   */
  success: boolean;
  /**
   * ID of the modified workflow
   */
  workflow_id: string;
  /**
   * Current interface blocks with positions
   */
  blocks?: InterfaceBlockInfo[] | null;
  /**
   * Full interface state for frontend sync
   */
  interface_state?: {
    [k: string]: unknown;
  } | null;
  /**
   * Status message or error
   */
  message?: string | null;
}
/**
 * Response for workflow:mcp:update_workflow_metadata - dual-delivered to frontend
 */
export interface WorkflowMCPUpdateWorkflowMetadataResponse {
  /**
   * Whether the update succeeded
   */
  success: boolean;
  /**
   * ID of the updated workflow
   */
  workflow_id: string;
  /**
   * Updated name (if changed)
   */
  name?: string | null;
  /**
   * Updated description (if changed)
   */
  description?: string | null;
  /**
   * Status message or error
   */
  message?: string | null;
}
/**
 * Response for workflow_folder:move_workflow request.
 */
export interface WorkflowMoveToFolderResponse {
  success: boolean;
  workflow_id: string;
  folder_id?: string | null;
  message?: string | null;
}
/**
 * Response for workflow:node:get_config_schema request
 */
export interface WorkflowNodeConfigSchemaResponse {
  /**
   * Type of the node
   */
  node_type: string;
  /**
   * Configuration schema for the node
   */
  config_schema: {
    [k: string]: unknown;
  };
}
/**
 * Response for workflow:node:load_options request
 */
export interface WorkflowNodeLoadOptionsResponse {
  /**
   * Whether options were loaded successfully
   */
  success: boolean;
  /**
   * List of options for the field
   */
  options?: FieldOption[];
  /**
   * Error message if loading failed
   */
  message?: string | null;
  /**
   * Token for loading the next page (null if no more pages)
   */
  next_page_token?: string | null;
}
/**
 * Response for workflow:node:load_value request - returns computed values for readonly fields
 */
export interface WorkflowNodeLoadValueResponse {
  /**
   * Whether the value was loaded successfully
   */
  success: boolean;
  value?: unknown;
  /**
   * Multiple computed values (for fields that generate multiple related values)
   */
  values?: {
    [k: string]: unknown;
  } | null;
  /**
   * Error message if loading failed
   */
  message?: string | null;
}
/**
 * Response for workflow:node:validate_config request
 */
export interface WorkflowNodeValidateConfigResponse {
  /**
   * Whether the config is valid
   */
  valid: boolean;
  /**
   * List of validation errors
   */
  errors?: string[];
  /**
   * Name of the parameter set that was satisfied
   */
  satisfied_set?: string | null;
}
/**
 * Response for workflow:permanent_delete request
 */
export interface WorkflowPermanentDeleteResponse {
  /**
   * Whether permanent deletion was successful
   */
  success: boolean;
  /**
   * Success or error message
   */
  message: string;
}
/**
 * Response for workflow:restore request
 */
export interface WorkflowRestoreResponse {
  /**
   * Whether restore was successful
   */
  success: boolean;
  /**
   * Success or error message
   */
  message: string;
  /**
   * UUID of the restored workflow
   */
  workflow_id?: string | null;
}
/**
 * Response for workflow:update request
 */
export interface WorkflowUpdateResponse {
  /**
   * Whether update was successful
   */
  success: boolean;
  /**
   * Updated workflow info
   */
  workflow?: WorkflowInfo | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for zendesk:oauth:exchange request
 */
export interface ZendeskOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Zendesk user name for display
   */
  name?: string | null;
  /**
   * Zendesk account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for zendesk:oauth:refresh request
 */
export interface ZendeskOAuthRefreshResponse {}
/**
 * Response for zendesk:oauth:validate request
 */
export interface ZendeskOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Zendesk user name
   */
  name?: string | null;
  /**
   * Zendesk account email
   */
  email?: string | null;
}
/**
 * Response for zoom:oauth:exchange request
 */
export interface ZoomOAuthExchangeResponse {
  /**
   * Whether token exchange was successful
   */
  success: boolean;
  /**
   * UUID of the created credential
   */
  credential_id?: string | null;
  /**
   * Name of the created credential
   */
  credential_name?: string | null;
  /**
   * Zoom user name for display
   */
  name?: string | null;
  /**
   * Zoom account email for display
   */
  email?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for zoom:oauth:refresh request
 */
export interface ZoomOAuthRefreshResponse {
  /**
   * Whether token refresh was successful
   */
  success: boolean;
  /**
   * New token expiry time (ISO 8601)
   */
  expires_at?: string | null;
  /**
   * Success or error message
   */
  message?: string | null;
}
/**
 * Response for zoom:oauth:validate request
 */
export interface ZoomOAuthValidateResponse {
  /**
   * Whether the OAuth token is valid
   */
  valid: boolean;
  /**
   * True if token expires within 5 minutes
   */
  expires_soon?: boolean;
  /**
   * Zoom user name
   */
  name?: string | null;
  /**
   * Zoom account email
   */
  email?: string | null;
  /**
   * Validation details or error message
   */
  message?: string | null;
}

// Event name to type mappings for type-safe socket handling
export interface ServerToClientEvents {
  'active_gen:edit_step': (data: ActiveGenEditStepEvent) => void;
  'active_gen:graph_event': (data: ActiveGenGraphEventEvent) => void;
  'active_gen:snapshot': (data: ActiveGenSnapshotEvent) => void;
  'active_gen:started': (data: ActiveGenStartedEvent) => void;
  'active_gen:status': (data: ActiveGenStatusEvent) => void;
  'active_gen:terminal': (data: ActiveGenTerminalEvent) => void;
  'active_gen:text_chunk': (data: ActiveGenTextChunkEvent) => void;
  'active_gen:token_progress': (data: ActiveGenTokenProgressEvent) => void;
  'activity:log:created': (data: ActivityLogCreatedEvent) => void;
  'agent:state': (data: AgentStateEvent) => void;
  'approval:request:created': (data: ApprovalRequestCreatedEvent) => void;
  'approval:request:resolved': (data: ApprovalRequestResolvedEvent) => void;
  'cache_valtio:state': (data: CacheValtioStateEvent) => void;
  'chat:message': (data: ChatMessageEvent) => void;
  'chat:transcription': (data: ChatTranscriptionEvent) => void;
  'conversation:latest_for_workflow': (data: LatestConversationForWorkflowEvent) => void;
  'conversation:resume': (data: ConversationResumeEvent) => void;
  'conversations:list': (data: ConversationListEvent) => void;
  'credits:exhausted': (data: CreditsExhaustedEvent) => void;
  'error': (data: ErrorEvent) => void;
  'mcp:builder_event': (data: MCPBuilderEvent) => void;
  'mcp:workflow:create_workflow:response': (data: WorkflowMCPCreateWorkflowResponse) => void;  // MCP dual delivery
  'mcp:workflow:delete_workflow:response': (data: WorkflowMCPDeleteWorkflowResponse) => void;  // MCP dual delivery
  'mcp:workflow:update_interface:response': (data: WorkflowMCPUpdateInterfaceResponse) => void;  // MCP dual delivery
  'mcp:workflow:update_workflow_metadata:response': (data: WorkflowMCPUpdateWorkflowMetadataResponse) => void;  // MCP dual delivery
  'rehearsal:progress': (data: RehearsalProgressEvent) => void;
  'response': (data: ResponseEvent) => void;
  'server:data': (data: ServerDataEvent) => void;
  'share:notification': (data: ShareNotificationEvent) => void;
  'state:changed': (data: StateChangedEvent) => void;
  'usage:data': (data: UsageDataEvent) => void;
  'usage:event': (data: UsageEventUpdateEvent) => void;
  'workflow:complete': (data: WorkflowCompleteEvent) => void;
  'workflow:mcp:request': (data: WorkflowMCPRequestEvent) => void;
  'workflow:name_generated': (data: WorkflowNameGeneratedEvent) => void;
  'workflow:node:output': (data: WorkflowNodeOutputEvent) => void;
  'workflow:node:progress': (data: WorkflowNodeProgressEvent) => void;
  'workflow:node:state': (data: WorkflowNodeStateEvent) => void;
  'workflow:started': (data: WorkflowStartedEvent) => void;
  'yjs:sync': (data: number[]) => void;  // Special case: byte array
  '__chunk__': (data: { __chunk_id: string; __chunk_index: number; __chunk_total: number; __chunk_data: string }) => void;  // Internal: chunked message fragment
}

export interface ClientToServerEvents {
  'activity:list': (data: ActivityListRequest) => void;
  'agent:builder_decision': (data: AgentBuilderDecisionRequest) => void;
  'agent:copy:from': (data: AgentCopyFromRequest) => void;
  'agent:copy:to': (data: AgentCopyToRequest) => void;
  'agent:edit:file': (data: AgentEditFileRequest) => void;
  'agent:list:files': (data: AgentListFilesRequest) => void;
  'agent:pause': (data: AgentPauseRequest) => void;
  'agent:read:file': (data: AgentReadFileRequest) => void;
  'agent:run:command': (data: AgentRunCommandRequest) => void;
  'agent:set:cwd': (data: AgentSetCwdRequest) => void;
  'agent:write:file': (data: AgentWriteFileRequest) => void;
  'agent_share:get_or_create': (data: AgentShareGetOrCreateRequest) => void;
  'agent_share:rotate': (data: AgentShareRotateRequest) => void;
  'agent_share:set_active': (data: AgentShareSetActiveRequest) => void;
  'agent_workspace:delete': (data: AgentWorkspaceDeleteRequest) => void;
  'agent_workspace:list': (data: AgentWorkspaceListRequest) => void;
  'airtable:oauth:exchange': (data: AirtableOAuthExchangeRequest) => void;
  'airtable:oauth:refresh': (data: AirtableOAuthRefreshRequest) => void;
  'airtable:oauth:validate': (data: AirtableOAuthValidateRequest) => void;
  'apollo:oauth:exchange': (data: ApolloOAuthExchangeRequest) => void;
  'apollo:oauth:refresh': (data: ApolloOAuthRefreshRequest) => void;
  'apollo:oauth:validate': (data: ApolloOAuthValidateRequest) => void;
  'approval:list': (data: ApprovalListRequest) => void;
  'approval:respond': (data: ApprovalRespondRequest) => void;
  'asana:oauth:exchange': (data: AsanaOAuthExchangeRequest) => void;
  'asana:oauth:refresh': (data: AsanaOAuthRefreshRequest) => void;
  'asana:oauth:validate': (data: AsanaOAuthValidateRequest) => void;
  'atlassian:oauth:exchange': (data: AtlassianOAuthExchangeRequest) => void;
  'atlassian:oauth:refresh': (data: AtlassianOAuthRefreshRequest) => void;
  'atlassian:oauth:validate': (data: AtlassianOAuthValidateRequest) => void;
  'attio:oauth:exchange': (data: AttioOAuthExchangeRequest) => void;
  'attio:oauth:refresh': (data: AttioOAuthRefreshRequest) => void;
  'attio:oauth:validate': (data: AttioOAuthValidateRequest) => void;
  'bamboohr:oauth:exchange': (data: BambooHROAuthExchangeRequest) => void;
  'bamboohr:oauth:refresh': (data: BambooHROAuthRefreshRequest) => void;
  'bamboohr:oauth:validate': (data: BambooHROAuthValidateRequest) => void;
  'box:oauth:exchange': (data: BoxOAuthExchangeRequest) => void;
  'box:oauth:refresh': (data: BoxOAuthRefreshRequest) => void;
  'box:oauth:validate': (data: BoxOAuthValidateRequest) => void;
  'calcom:oauth:exchange': (data: CalComOAuthExchangeRequest) => void;
  'calcom:oauth:refresh': (data: CalComOAuthRefreshRequest) => void;
  'calcom:oauth:validate': (data: CalComOAuthValidateRequest) => void;
  'calendly:oauth:exchange': (data: CalendlyOAuthExchangeRequest) => void;
  'calendly:oauth:refresh': (data: CalendlyOAuthRefreshRequest) => void;
  'calendly:oauth:validate': (data: CalendlyOAuthValidateRequest) => void;
  'canva:oauth:exchange': (data: CanvaOAuthExchangeRequest) => void;
  'canva:oauth:refresh': (data: CanvaOAuthRefreshRequest) => void;
  'canva:oauth:validate': (data: CanvaOAuthValidateRequest) => void;
  'chat:message': (data: ChatMessageRequest) => void;
  'claude-code:auth:exchange': (data: ClaudeCodeAuthExchangeRequest) => void;
  'claude-code:auth:start': (data: ClaudeCodeAuthStartRequest) => void;
  'clickup:oauth:exchange': (data: ClickUpOAuthExchangeRequest) => void;
  'clickup:oauth:refresh': (data: ClickUpOAuthRefreshRequest) => void;
  'clickup:oauth:validate': (data: ClickUpOAuthValidateRequest) => void;
  'cloudflare:oauth:exchange': (data: CloudflareOAuthExchangeRequest) => void;
  'cloudflare:oauth:refresh': (data: CloudflareOAuthRefreshRequest) => void;
  'cloudflare:oauth:validate': (data: CloudflareOAuthValidateRequest) => void;
  'codex:auth:poll': (data: CodexDeviceCodePollRequest) => void;
  'codex:auth:start': (data: CodexDeviceCodeStartRequest) => void;
  'conversation:delete': (data: DeleteConversationRequest) => void;
  'conversation:get_latest_for_workflow': (data: GetLatestConversationForWorkflowRequest) => void;
  'conversation:list_for_agent': (data: ListConversationsForAgentRequest) => void;
  'conversation:resume': (data: ResumeConversationRequest) => void;
  'conversations:list': (data: ListConversationsRequest) => void;
  'credential:authorize_for_workflow': (data: CredentialAuthorizeForWorkflowRequest) => void;
  'credential:create': (data: CredentialCreateRequest) => void;
  'credential:delete': (data: CredentialDeleteRequest) => void;
  'credential:display_info': (data: CredentialDisplayInfoRequest) => void;
  'credential:get': (data: CredentialGetRequest) => void;
  'credential:list': (data: CredentialListRequest) => void;
  'credential:request:cancel': (data: CredentialRequestCancelRequest) => void;
  'credential:request:create': (data: CredentialRequestCreateRequest) => void;
  'credential:request:list': (data: CredentialRequestListRequest) => void;
  'credential:test_connection': (data: CredentialTestConnectionRequest) => void;
  'credential:update': (data: CredentialUpdateRequest) => void;
  'credential:validate_access': (data: CredentialValidateAccessRequest) => void;
  'discord:oauth:exchange': (data: DiscordOAuthExchangeRequest) => void;
  'discord:oauth:refresh': (data: DiscordOAuthRefreshRequest) => void;
  'discord:oauth:validate': (data: DiscordOAuthValidateRequest) => void;
  'dropbox:oauth:exchange': (data: DropboxOAuthExchangeRequest) => void;
  'dropbox:oauth:refresh': (data: DropboxOAuthRefreshRequest) => void;
  'dropbox:oauth:validate': (data: DropboxOAuthValidateRequest) => void;
  'facebook:oauth:exchange': (data: FacebookOAuthExchangeRequest) => void;
  'facebook:oauth:refresh': (data: FacebookOAuthRefreshRequest) => void;
  'facebook:oauth:validate': (data: FacebookOAuthValidateRequest) => void;
  'facebook_pages:oauth:exchange': (data: FacebookPagesOAuthExchangeRequest) => void;
  'facebook_pages:oauth:refresh': (data: FacebookPagesOAuthRefreshRequest) => void;
  'facebook_pages:oauth:validate': (data: FacebookPagesOAuthValidateRequest) => void;
  'fathom:oauth:exchange': (data: FathomOAuthExchangeRequest) => void;
  'fathom:oauth:refresh': (data: FathomOAuthRefreshRequest) => void;
  'fathom:oauth:validate': (data: FathomOAuthValidateRequest) => void;
  'feedback:submit': (data: SubmitFeedbackRequest) => void;
  'github:oauth:exchange': (data: GithubOAuthExchangeRequest) => void;
  'github:oauth:refresh': (data: GithubOAuthRefreshRequest) => void;
  'github:oauth:validate': (data: GithubOAuthValidateRequest) => void;
  'gitlab:oauth:exchange': (data: GitLabOAuthExchangeRequest) => void;
  'gitlab:oauth:refresh': (data: GitLabOAuthRefreshRequest) => void;
  'gitlab:oauth:validate': (data: GitLabOAuthValidateRequest) => void;
  'google:oauth:exchange': (data: GoogleOAuthExchangeRequest) => void;
  'google:oauth:refresh': (data: GoogleOAuthRefreshRequest) => void;
  'google:oauth:validate': (data: GoogleOAuthValidateRequest) => void;
  'hubspot:oauth:exchange': (data: HubSpotOAuthExchangeRequest) => void;
  'hubspot:oauth:refresh': (data: HubSpotOAuthRefreshRequest) => void;
  'hubspot:oauth:validate': (data: HubSpotOAuthValidateRequest) => void;
  'instagram_login:oauth:exchange': (data: InstagramLoginOAuthExchangeRequest) => void;
  'instagram_login:oauth:refresh': (data: InstagramLoginOAuthRefreshRequest) => void;
  'instagram_login:oauth:validate': (data: InstagramLoginOAuthValidateRequest) => void;
  'instance_keys:delete': (data: InstanceKeysDeleteRequest) => void;
  'instance_keys:list': (data: InstanceKeysListRequest) => void;
  'instance_keys:set': (data: InstanceKeysSetRequest) => void;
  'instance_oauth:delete': (data: InstanceOAuthDeleteRequest) => void;
  'instance_oauth:list': (data: InstanceOAuthListRequest) => void;
  'instance_oauth:set': (data: InstanceOAuthSetRequest) => void;
  'intercom:oauth:exchange': (data: IntercomOAuthExchangeRequest) => void;
  'intercom:oauth:refresh': (data: IntercomOAuthRefreshRequest) => void;
  'intercom:oauth:validate': (data: IntercomOAuthValidateRequest) => void;
  'klaviyo:oauth:exchange': (data: KlaviyoOAuthExchangeRequest) => void;
  'klaviyo:oauth:refresh': (data: KlaviyoOAuthRefreshRequest) => void;
  'klaviyo:oauth:validate': (data: KlaviyoOAuthValidateRequest) => void;
  'linear:oauth:exchange': (data: LinearOAuthExchangeRequest) => void;
  'linear:oauth:refresh': (data: LinearOAuthRefreshRequest) => void;
  'linear:oauth:validate': (data: LinearOAuthValidateRequest) => void;
  'linkedin:oauth:exchange': (data: LinkedInOAuthExchangeRequest) => void;
  'linkedin:oauth:refresh': (data: LinkedInOAuthRefreshRequest) => void;
  'linkedin:oauth:validate': (data: LinkedInOAuthValidateRequest) => void;
  'mailchimp:oauth:exchange': (data: MailchimpOAuthExchangeRequest) => void;
  'mcp:oauth:discover': (data: MCPOAuthDiscoverRequest) => void;
  'mcp:oauth:exchange': (data: MCPOAuthExchangeRequest) => void;
  'mcp:oauth:register-client': (data: MCPOAuthRegisterClientRequest) => void;
  'meta:oauth:exchange': (data: MetaOAuthExchangeRequest) => void;
  'meta:oauth:refresh': (data: MetaOAuthRefreshRequest) => void;
  'meta:oauth:validate': (data: MetaOAuthValidateRequest) => void;
  'microsoft:oauth:exchange': (data: MicrosoftOAuthExchangeRequest) => void;
  'microsoft:oauth:refresh': (data: MicrosoftOAuthRefreshRequest) => void;
  'microsoft:oauth:validate': (data: MicrosoftOAuthValidateRequest) => void;
  'monday:oauth:exchange': (data: MondayOAuthExchangeRequest) => void;
  'monday:oauth:refresh': (data: MondayOAuthRefreshRequest) => void;
  'monday:oauth:validate': (data: MondayOAuthValidateRequest) => void;
  'notifications:prefs:get': (data: NotificationPrefsGetRequest) => void;
  'notifications:prefs:update': (data: NotificationPrefsUpdateRequest) => void;
  'notion:oauth:exchange': (data: NotionOAuthExchangeRequest) => void;
  'notion:oauth:refresh': (data: NotionOAuthRefreshRequest) => void;
  'notion:oauth:validate': (data: NotionOAuthValidateRequest) => void;
  'onboarding:completion:get': (data: OnboardingCompletionGetRequest) => void;
  'onboarding:completion:update': (data: OnboardingCompletionUpdateRequest) => void;
  'onboarding:skip': (data: OnboardingSkipRequest) => void;
  'onboarding:submit': (data: OnboardingSubmitRequest) => void;
  'pagerduty:oauth:exchange': (data: PagerDutyOAuthExchangeRequest) => void;
  'pagerduty:oauth:refresh': (data: PagerDutyOAuthRefreshRequest) => void;
  'pagerduty:oauth:validate': (data: PagerDutyOAuthValidateRequest) => void;
  'parallel:oauth:exchange': (data: ParallelOAuthExchangeRequest) => void;
  'parallel:oauth:validate': (data: ParallelOAuthValidateRequest) => void;
  'pipedrive:oauth:exchange': (data: PipedriveOAuthExchangeRequest) => void;
  'pipedrive:oauth:refresh': (data: PipedriveOAuthRefreshRequest) => void;
  'pipedrive:oauth:validate': (data: PipedriveOAuthValidateRequest) => void;
  'posthog:oauth:exchange': (data: PostHogOAuthExchangeRequest) => void;
  'posthog:oauth:refresh': (data: PostHogOAuthRefreshRequest) => void;
  'posthog:oauth:validate': (data: PostHogOAuthValidateRequest) => void;
  'quickbooks:oauth:exchange': (data: QuickBooksOAuthExchangeRequest) => void;
  'quickbooks:oauth:refresh': (data: QuickBooksOAuthRefreshRequest) => void;
  'quickbooks:oauth:validate': (data: QuickBooksOAuthValidateRequest) => void;
  'reddit:oauth:exchange': (data: RedditOAuthExchangeRequest) => void;
  'reddit:oauth:refresh': (data: RedditOAuthRefreshRequest) => void;
  'reddit:oauth:validate': (data: RedditOAuthValidateRequest) => void;
  'rehearsal:run': (data: RehearsalRunRequest) => void;
  'rehearsal:scenarios': (data: RehearsalScenariosRequest) => void;
  'resource:create': (data: ResourceCreateRequest) => void;
  'resource:dataset:append': (data: ResourceDatasetAppendRequest) => void;
  'resource:dataset:delete_rows': (data: ResourceDatasetDeleteRowsRequest) => void;
  'resource:dataset:rows': (data: ResourceDatasetRowsRequest) => void;
  'resource:dataset:update_row': (data: ResourceDatasetUpdateRowRequest) => void;
  'resource:delete': (data: ResourceDeleteRequest) => void;
  'resource:download_url': (data: ResourceDownloadUrlRequest) => void;
  'resource:fork': (data: ResourceForkRequest) => void;
  'resource:get': (data: ResourceGetRequest) => void;
  'resource:list': (data: ResourceListRequest) => void;
  'resource:upload_url': (data: ResourceUploadUrlRequest) => void;
  'run_share:create': (data: RunShareCreateRequest) => void;
  'salesforce:oauth:exchange': (data: SalesforceOAuthExchangeRequest) => void;
  'salesforce:oauth:refresh': (data: SalesforceOAuthRefreshRequest) => void;
  'salesforce:oauth:validate': (data: SalesforceOAuthValidateRequest) => void;
  'saved_output:create': (data: SavedOutputCreateRequest) => void;
  'saved_output:delete': (data: SavedOutputDeleteRequest) => void;
  'saved_output:get': (data: SavedOutputGetRequest) => void;
  'saved_output:list': (data: SavedOutputListRequest) => void;
  'saved_output:update': (data: SavedOutputUpdateRequest) => void;
  'sentry:oauth:exchange': (data: SentryOAuthExchangeRequest) => void;
  'sentry:oauth:refresh': (data: SentryOAuthRefreshRequest) => void;
  'sentry:oauth:validate': (data: SentryOAuthValidateRequest) => void;
  'share:create': (data: ShareCreateRequest) => void;
  'share:delete': (data: ShareDeleteRequest) => void;
  'share:invite_accept': (data: ShareInviteAcceptRequest) => void;
  'share:invite_link': (data: ShareInviteLinkRequest) => void;
  'share:leave': (data: ShareLeaveRequest) => void;
  'share:list': (data: ShareListRequest) => void;
  'share:list_shared_with_me': (data: ShareListSharedWithMeRequest) => void;
  'share:update': (data: ShareUpdateRequest) => void;
  'shared_agent:resume': (data: SharedAgentResumeRequest) => void;
  'shared_agent:send': (data: SharedAgentSendRequest) => void;
  'shopify:oauth:exchange': (data: ShopifyOAuthExchangeRequest) => void;
  'shopify:oauth:refresh': (data: ShopifyOAuthRefreshRequest) => void;
  'shopify:oauth:validate': (data: ShopifyOAuthValidateRequest) => void;
  'skill:create': (data: SkillCreateRequest) => void;
  'skill:delete': (data: SkillDeleteRequest) => void;
  'skill:get': (data: SkillGetRequest) => void;
  'skill:get_workflow': (data: SkillGetWorkflowRequest) => void;
  'skill:list': (data: SkillListRequest) => void;
  'skill:mute': (data: SkillMuteRequest) => void;
  'skill:update': (data: SkillUpdateRequest) => void;
  'skill:update_workflow': (data: SkillUpdateWorkflowRequest) => void;
  'slack:oauth:exchange': (data: SlackOAuthExchangeRequest) => void;
  'slack:oauth:refresh': (data: SlackOAuthRefreshRequest) => void;
  'slack:oauth:validate': (data: SlackOAuthValidateRequest) => void;
  'stripe:oauth:exchange': (data: StripeOAuthExchangeRequest) => void;
  'stripe:oauth:refresh': (data: StripeOAuthRefreshRequest) => void;
  'stripe:oauth:validate': (data: StripeOAuthValidateRequest) => void;
  'supabase:oauth:exchange': (data: SupabaseOAuthExchangeRequest) => void;
  'supabase:oauth:refresh': (data: SupabaseOAuthRefreshRequest) => void;
  'supabase:oauth:select_project': (data: SupabaseOAuthSelectProjectRequest) => void;
  'supabase:oauth:validate': (data: SupabaseOAuthValidateRequest) => void;
  'threads:oauth:exchange': (data: ThreadsOAuthExchangeRequest) => void;
  'threads:oauth:refresh': (data: ThreadsOAuthRefreshRequest) => void;
  'threads:oauth:validate': (data: ThreadsOAuthValidateRequest) => void;
  'tiktok:oauth:exchange': (data: TikTokOAuthExchangeRequest) => void;
  'tiktok:oauth:refresh': (data: TikTokOAuthRefreshRequest) => void;
  'tiktok:oauth:validate': (data: TikTokOAuthValidateRequest) => void;
  'tool_calls:list': (data: ToolCallListRequest) => void;
  'twitter:oauth:exchange': (data: TwitterOAuthExchangeRequest) => void;
  'twitter:oauth:refresh': (data: TwitterOAuthRefreshRequest) => void;
  'twitter:oauth:validate': (data: TwitterOAuthValidateRequest) => void;
  'typeform:oauth:exchange': (data: TypeformOAuthExchangeRequest) => void;
  'update_auth': (data: UpdateAuthRequest) => void;
  'usage:data': (data: UsageDataRequest) => void;
  'usage:logs': (data: UsageLogsRequest) => void;
  'webflow:oauth:exchange': (data: WebflowOAuthExchangeRequest) => void;
  'webflow:oauth:refresh': (data: WebflowOAuthRefreshRequest) => void;
  'webflow:oauth:validate': (data: WebflowOAuthValidateRequest) => void;
  'whatsapp:qr:start': (data: WhatsAppQRStartRequest) => void;
  'whatsapp:qr:status': (data: WhatsAppQRStatusRequest) => void;
  'wordpress:oauth:exchange': (data: WordPressOAuthExchangeRequest) => void;
  'wordpress:oauth:refresh': (data: WordPressOAuthRefreshRequest) => void;
  'wordpress:oauth:validate': (data: WordPressOAuthValidateRequest) => void;
  'workflow:builder:autofill': (data: WorkflowAutofillRequest) => void;
  'workflow:builder:edit': (data: WorkflowBuilderEditRequest) => void;
  'workflow:builder:list_pending': (data: ListPendingBuilderRunsRequest) => void;
  'workflow:builder:share_ask': (data: ShareBuilderAskRequest) => void;
  'workflow:checkpoint:create': (data: WorkflowCheckpointCreateRequest) => void;
  'workflow:checkpoint:delete': (data: WorkflowCheckpointDeleteRequest) => void;
  'workflow:checkpoint:list': (data: WorkflowCheckpointListRequest) => void;
  'workflow:checkpoint:restore': (data: WorkflowCheckpointRestoreRequest) => void;
  'workflow:clear_node_state': (data: WorkflowClearNodeStateRequest) => void;
  'workflow:collab_token': (data: WorkflowCollabTokenRequest) => void;
  'workflow:create': (data: WorkflowCreateRequest) => void;
  'workflow:delete': (data: WorkflowDeleteRequest) => void;
  'workflow:execute': (data: WorkflowExecuteRequest) => void;
  'workflow:get': (data: WorkflowGetRequest) => void;
  'workflow:get_execution_counts': (data: WorkflowExecutionCountsRequest) => void;
  'workflow:get_execution_detail': (data: WorkflowExecutionDetailRequest) => void;
  'workflow:get_node_output': (data: WorkflowNodeOutputRequest) => void;
  'workflow:get_node_output_history': (data: WorkflowGetNodeOutputHistoryRequest) => void;
  'workflow:get_node_outputs': (data: WorkflowGetNodeOutputsRequest) => void;
  'workflow:list': (data: WorkflowListRequest) => void;
  'workflow:list_executions': (data: WorkflowExecutionListRequest) => void;
  'workflow:list_trash': (data: WorkflowListTrashRequest) => void;
  'workflow:load_node_state': (data: WorkflowLoadNodeStateRequest) => void;
  'workflow:mcp:create_workflow': (data: WorkflowMCPCreateWorkflowRequest) => void;
  'workflow:mcp:delete_workflow': (data: WorkflowMCPDeleteWorkflowRequest) => void;
  'workflow:mcp:get_execution_status': (data: WorkflowMCPGetExecutionStatusRequest) => void;
  'workflow:mcp:get_folder_tree': (data: MCPFolderGetTreeRequest) => void;
  'workflow:mcp:get_node_config': (data: WorkflowMCPGetNodeConfigRequest) => void;
  'workflow:mcp:get_node_config_schema': (data: WorkflowMCPGetNodeConfigSchemaRequest) => void;
  'workflow:mcp:get_node_input': (data: WorkflowMCPGetNodeInputRequest) => void;
  'workflow:mcp:get_node_output': (data: WorkflowMCPGetNodeOutputRequest) => void;
  'workflow:mcp:get_open_workflow': (data: WorkflowMCPGetOpenWorkflowRequest) => void;
  'workflow:mcp:get_selected_node': (data: WorkflowMCPGetSelectedNodeRequest) => void;
  'workflow:mcp:list_credentials': (data: WorkflowMCPListCredentialsRequest) => void;
  'workflow:mcp:list_saved_outputs': (data: WorkflowMCPListSavedOutputsRequest) => void;
  'workflow:mcp:list_workflows': (data: WorkflowMCPListWorkflowsRequest) => void;
  'workflow:mcp:load_field_options': (data: WorkflowMCPLoadFieldOptionsRequest) => void;
  'workflow:mcp:open_workflow': (data: WorkflowMCPOpenWorkflowRequest) => void;
  'workflow:mcp:response': (data: WorkflowMCPResponseRequest) => void;
  'workflow:mcp:run_node': (data: WorkflowMCPRunNodeRequest) => void;
  'workflow:mcp:run_workflow': (data: WorkflowMCPRunWorkflowRequest) => void;
  'workflow:mcp:search_nodes': (data: WorkflowMCPSearchNodesRequest) => void;
  'workflow:mcp:update_interface': (data: WorkflowMCPUpdateInterfaceRequest) => void;
  'workflow:mcp:update_workflow_metadata': (data: WorkflowMCPUpdateWorkflowMetadataRequest) => void;
  'workflow:node:evaluate_expression': (data: WorkflowNodeEvaluateExpressionRequest) => void;
  'workflow:node:get_config': (data: WorkflowNodeGetConfigRequest) => void;
  'workflow:node:get_config_schema': (data: WorkflowNodeConfigSchemaRequest) => void;
  'workflow:node:load_options': (data: WorkflowNodeLoadOptionsRequest) => void;
  'workflow:node:load_value': (data: WorkflowNodeLoadValueRequest) => void;
  'workflow:node:schema': (data: NodeOutputSchemaRequest) => void;
  'workflow:node:set_config': (data: WorkflowNodeSetConfigRequest) => void;
  'workflow:node:validate_config': (data: WorkflowNodeValidateConfigRequest) => void;
  'workflow:permanent_delete': (data: WorkflowPermanentDeleteRequest) => void;
  'workflow:restore': (data: WorkflowRestoreRequest) => void;
  'workflow:save_node_state': (data: WorkflowSaveNodeStateRequest) => void;
  'workflow:state:get': (data: WorkflowStateGetRequest) => void;
  'workflow:state:keys': (data: WorkflowStateKeysRequest) => void;
  'workflow:state:set': (data: WorkflowStateSetRequest) => void;
  'workflow:update': (data: WorkflowUpdateRequest) => void;
  'workflow_folder:create': (data: FolderCreateRequest) => void;
  'workflow_folder:delete': (data: FolderDeleteRequest) => void;
  'workflow_folder:get': (data: FolderGetRequest) => void;
  'workflow_folder:get_path': (data: FolderGetPathRequest) => void;
  'workflow_folder:get_tree': (data: FolderGetTreeRequest) => void;
  'workflow_folder:list': (data: FolderListRequest) => void;
  'workflow_folder:move_workflow': (data: WorkflowMoveToFolderRequest) => void;
  'workflow_folder:update': (data: FolderUpdateRequest) => void;
  'yjs:sync': (data: Uint8Array | number[]) => void;
  'zendesk:oauth:exchange': (data: ZendeskOAuthExchangeRequest) => void;
  'zendesk:oauth:refresh': (data: ZendeskOAuthRefreshRequest) => void;
  'zendesk:oauth:validate': (data: ZendeskOAuthValidateRequest) => void;
  'zoom:oauth:exchange': (data: ZoomOAuthExchangeRequest) => void;
  'zoom:oauth:refresh': (data: ZoomOAuthRefreshRequest) => void;
  'zoom:oauth:validate': (data: ZoomOAuthValidateRequest) => void;
  '__chunk__': (data: { __chunk_id: string; __chunk_index: number; __chunk_total: number; __chunk_data: string }) => void;  // Internal: chunked message fragment
}

// Mapping of request type names to their event names
export const ClientEventNames = {

  ActivityListRequest: 'activity:list',
  AgentBuilderDecisionRequest: 'agent:builder_decision',
  AgentCopyFromRequest: 'agent:copy:from',
  AgentCopyToRequest: 'agent:copy:to',
  AgentEditFileRequest: 'agent:edit:file',
  AgentListFilesRequest: 'agent:list:files',
  AgentPauseRequest: 'agent:pause',
  AgentReadFileRequest: 'agent:read:file',
  AgentRunCommandRequest: 'agent:run:command',
  AgentSetCwdRequest: 'agent:set:cwd',
  AgentShareGetOrCreateRequest: 'agent_share:get_or_create',
  AgentShareRotateRequest: 'agent_share:rotate',
  AgentShareSetActiveRequest: 'agent_share:set_active',
  AgentWorkspaceDeleteRequest: 'agent_workspace:delete',
  AgentWorkspaceListRequest: 'agent_workspace:list',
  AgentWriteFileRequest: 'agent:write:file',
  AirtableOAuthExchangeRequest: 'airtable:oauth:exchange',
  AirtableOAuthRefreshRequest: 'airtable:oauth:refresh',
  AirtableOAuthValidateRequest: 'airtable:oauth:validate',
  ApolloOAuthExchangeRequest: 'apollo:oauth:exchange',
  ApolloOAuthRefreshRequest: 'apollo:oauth:refresh',
  ApolloOAuthValidateRequest: 'apollo:oauth:validate',
  ApprovalListRequest: 'approval:list',
  ApprovalRespondRequest: 'approval:respond',
  AsanaOAuthExchangeRequest: 'asana:oauth:exchange',
  AsanaOAuthRefreshRequest: 'asana:oauth:refresh',
  AsanaOAuthValidateRequest: 'asana:oauth:validate',
  AtlassianOAuthExchangeRequest: 'atlassian:oauth:exchange',
  AtlassianOAuthRefreshRequest: 'atlassian:oauth:refresh',
  AtlassianOAuthValidateRequest: 'atlassian:oauth:validate',
  AttioOAuthExchangeRequest: 'attio:oauth:exchange',
  AttioOAuthRefreshRequest: 'attio:oauth:refresh',
  AttioOAuthValidateRequest: 'attio:oauth:validate',
  BambooHROAuthExchangeRequest: 'bamboohr:oauth:exchange',
  BambooHROAuthRefreshRequest: 'bamboohr:oauth:refresh',
  BambooHROAuthValidateRequest: 'bamboohr:oauth:validate',
  BoxOAuthExchangeRequest: 'box:oauth:exchange',
  BoxOAuthRefreshRequest: 'box:oauth:refresh',
  BoxOAuthValidateRequest: 'box:oauth:validate',
  CalComOAuthExchangeRequest: 'calcom:oauth:exchange',
  CalComOAuthRefreshRequest: 'calcom:oauth:refresh',
  CalComOAuthValidateRequest: 'calcom:oauth:validate',
  CalendlyOAuthExchangeRequest: 'calendly:oauth:exchange',
  CalendlyOAuthRefreshRequest: 'calendly:oauth:refresh',
  CalendlyOAuthValidateRequest: 'calendly:oauth:validate',
  CanvaOAuthExchangeRequest: 'canva:oauth:exchange',
  CanvaOAuthRefreshRequest: 'canva:oauth:refresh',
  CanvaOAuthValidateRequest: 'canva:oauth:validate',
  ChatMessageRequest: 'chat:message',
  ClaudeCodeAuthExchangeRequest: 'claude-code:auth:exchange',
  ClaudeCodeAuthStartRequest: 'claude-code:auth:start',
  ClickUpOAuthExchangeRequest: 'clickup:oauth:exchange',
  ClickUpOAuthRefreshRequest: 'clickup:oauth:refresh',
  ClickUpOAuthValidateRequest: 'clickup:oauth:validate',
  CloudflareOAuthExchangeRequest: 'cloudflare:oauth:exchange',
  CloudflareOAuthRefreshRequest: 'cloudflare:oauth:refresh',
  CloudflareOAuthValidateRequest: 'cloudflare:oauth:validate',
  CodexDeviceCodePollRequest: 'codex:auth:poll',
  CodexDeviceCodeStartRequest: 'codex:auth:start',
  CredentialAuthorizeForWorkflowRequest: 'credential:authorize_for_workflow',
  CredentialCreateRequest: 'credential:create',
  CredentialDeleteRequest: 'credential:delete',
  CredentialDisplayInfoRequest: 'credential:display_info',
  CredentialGetRequest: 'credential:get',
  CredentialListRequest: 'credential:list',
  CredentialRequestCancelRequest: 'credential:request:cancel',
  CredentialRequestCreateRequest: 'credential:request:create',
  CredentialRequestListRequest: 'credential:request:list',
  CredentialTestConnectionRequest: 'credential:test_connection',
  CredentialUpdateRequest: 'credential:update',
  CredentialValidateAccessRequest: 'credential:validate_access',
  DeleteConversationRequest: 'conversation:delete',
  DiscordOAuthExchangeRequest: 'discord:oauth:exchange',
  DiscordOAuthRefreshRequest: 'discord:oauth:refresh',
  DiscordOAuthValidateRequest: 'discord:oauth:validate',
  DropboxOAuthExchangeRequest: 'dropbox:oauth:exchange',
  DropboxOAuthRefreshRequest: 'dropbox:oauth:refresh',
  DropboxOAuthValidateRequest: 'dropbox:oauth:validate',
  FacebookOAuthExchangeRequest: 'facebook:oauth:exchange',
  FacebookOAuthRefreshRequest: 'facebook:oauth:refresh',
  FacebookOAuthValidateRequest: 'facebook:oauth:validate',
  FacebookPagesOAuthExchangeRequest: 'facebook_pages:oauth:exchange',
  FacebookPagesOAuthRefreshRequest: 'facebook_pages:oauth:refresh',
  FacebookPagesOAuthValidateRequest: 'facebook_pages:oauth:validate',
  FathomOAuthExchangeRequest: 'fathom:oauth:exchange',
  FathomOAuthRefreshRequest: 'fathom:oauth:refresh',
  FathomOAuthValidateRequest: 'fathom:oauth:validate',
  FolderCreateRequest: 'workflow_folder:create',
  FolderDeleteRequest: 'workflow_folder:delete',
  FolderGetPathRequest: 'workflow_folder:get_path',
  FolderGetRequest: 'workflow_folder:get',
  FolderGetTreeRequest: 'workflow_folder:get_tree',
  FolderListRequest: 'workflow_folder:list',
  FolderUpdateRequest: 'workflow_folder:update',
  GetLatestConversationForWorkflowRequest: 'conversation:get_latest_for_workflow',
  GitLabOAuthExchangeRequest: 'gitlab:oauth:exchange',
  GitLabOAuthRefreshRequest: 'gitlab:oauth:refresh',
  GitLabOAuthValidateRequest: 'gitlab:oauth:validate',
  GithubOAuthExchangeRequest: 'github:oauth:exchange',
  GithubOAuthRefreshRequest: 'github:oauth:refresh',
  GithubOAuthValidateRequest: 'github:oauth:validate',
  GoogleOAuthExchangeRequest: 'google:oauth:exchange',
  GoogleOAuthRefreshRequest: 'google:oauth:refresh',
  GoogleOAuthValidateRequest: 'google:oauth:validate',
  HubSpotOAuthExchangeRequest: 'hubspot:oauth:exchange',
  HubSpotOAuthRefreshRequest: 'hubspot:oauth:refresh',
  HubSpotOAuthValidateRequest: 'hubspot:oauth:validate',
  InstagramLoginOAuthExchangeRequest: 'instagram_login:oauth:exchange',
  InstagramLoginOAuthRefreshRequest: 'instagram_login:oauth:refresh',
  InstagramLoginOAuthValidateRequest: 'instagram_login:oauth:validate',
  InstanceKeysDeleteRequest: 'instance_keys:delete',
  InstanceKeysListRequest: 'instance_keys:list',
  InstanceKeysSetRequest: 'instance_keys:set',
  InstanceOAuthDeleteRequest: 'instance_oauth:delete',
  InstanceOAuthListRequest: 'instance_oauth:list',
  InstanceOAuthSetRequest: 'instance_oauth:set',
  IntercomOAuthExchangeRequest: 'intercom:oauth:exchange',
  IntercomOAuthRefreshRequest: 'intercom:oauth:refresh',
  IntercomOAuthValidateRequest: 'intercom:oauth:validate',
  KlaviyoOAuthExchangeRequest: 'klaviyo:oauth:exchange',
  KlaviyoOAuthRefreshRequest: 'klaviyo:oauth:refresh',
  KlaviyoOAuthValidateRequest: 'klaviyo:oauth:validate',
  LinearOAuthExchangeRequest: 'linear:oauth:exchange',
  LinearOAuthRefreshRequest: 'linear:oauth:refresh',
  LinearOAuthValidateRequest: 'linear:oauth:validate',
  LinkedInOAuthExchangeRequest: 'linkedin:oauth:exchange',
  LinkedInOAuthRefreshRequest: 'linkedin:oauth:refresh',
  LinkedInOAuthValidateRequest: 'linkedin:oauth:validate',
  ListConversationsForAgentRequest: 'conversation:list_for_agent',
  ListConversationsRequest: 'conversations:list',
  ListPendingBuilderRunsRequest: 'workflow:builder:list_pending',
  MCPFolderGetTreeRequest: 'workflow:mcp:get_folder_tree',
  MCPOAuthDiscoverRequest: 'mcp:oauth:discover',
  MCPOAuthExchangeRequest: 'mcp:oauth:exchange',
  MCPOAuthRegisterClientRequest: 'mcp:oauth:register-client',
  MailchimpOAuthExchangeRequest: 'mailchimp:oauth:exchange',
  MetaOAuthExchangeRequest: 'meta:oauth:exchange',
  MetaOAuthRefreshRequest: 'meta:oauth:refresh',
  MetaOAuthValidateRequest: 'meta:oauth:validate',
  MicrosoftOAuthExchangeRequest: 'microsoft:oauth:exchange',
  MicrosoftOAuthRefreshRequest: 'microsoft:oauth:refresh',
  MicrosoftOAuthValidateRequest: 'microsoft:oauth:validate',
  MondayOAuthExchangeRequest: 'monday:oauth:exchange',
  MondayOAuthRefreshRequest: 'monday:oauth:refresh',
  MondayOAuthValidateRequest: 'monday:oauth:validate',
  NodeOutputSchemaRequest: 'workflow:node:schema',
  NotificationPrefsGetRequest: 'notifications:prefs:get',
  NotificationPrefsUpdateRequest: 'notifications:prefs:update',
  NotionOAuthExchangeRequest: 'notion:oauth:exchange',
  NotionOAuthRefreshRequest: 'notion:oauth:refresh',
  NotionOAuthValidateRequest: 'notion:oauth:validate',
  OnboardingCompletionGetRequest: 'onboarding:completion:get',
  OnboardingCompletionUpdateRequest: 'onboarding:completion:update',
  OnboardingSkipRequest: 'onboarding:skip',
  OnboardingSubmitRequest: 'onboarding:submit',
  PagerDutyOAuthExchangeRequest: 'pagerduty:oauth:exchange',
  PagerDutyOAuthRefreshRequest: 'pagerduty:oauth:refresh',
  PagerDutyOAuthValidateRequest: 'pagerduty:oauth:validate',
  ParallelOAuthExchangeRequest: 'parallel:oauth:exchange',
  ParallelOAuthValidateRequest: 'parallel:oauth:validate',
  PipedriveOAuthExchangeRequest: 'pipedrive:oauth:exchange',
  PipedriveOAuthRefreshRequest: 'pipedrive:oauth:refresh',
  PipedriveOAuthValidateRequest: 'pipedrive:oauth:validate',
  PostHogOAuthExchangeRequest: 'posthog:oauth:exchange',
  PostHogOAuthRefreshRequest: 'posthog:oauth:refresh',
  PostHogOAuthValidateRequest: 'posthog:oauth:validate',
  QuickBooksOAuthExchangeRequest: 'quickbooks:oauth:exchange',
  QuickBooksOAuthRefreshRequest: 'quickbooks:oauth:refresh',
  QuickBooksOAuthValidateRequest: 'quickbooks:oauth:validate',
  RedditOAuthExchangeRequest: 'reddit:oauth:exchange',
  RedditOAuthRefreshRequest: 'reddit:oauth:refresh',
  RedditOAuthValidateRequest: 'reddit:oauth:validate',
  RehearsalRunRequest: 'rehearsal:run',
  RehearsalScenariosRequest: 'rehearsal:scenarios',
  ResourceCreateRequest: 'resource:create',
  ResourceDatasetAppendRequest: 'resource:dataset:append',
  ResourceDatasetDeleteRowsRequest: 'resource:dataset:delete_rows',
  ResourceDatasetRowsRequest: 'resource:dataset:rows',
  ResourceDatasetUpdateRowRequest: 'resource:dataset:update_row',
  ResourceDeleteRequest: 'resource:delete',
  ResourceDownloadUrlRequest: 'resource:download_url',
  ResourceForkRequest: 'resource:fork',
  ResourceGetRequest: 'resource:get',
  ResourceListRequest: 'resource:list',
  ResourceUploadUrlRequest: 'resource:upload_url',
  ResumeConversationRequest: 'conversation:resume',
  RunShareCreateRequest: 'run_share:create',
  SalesforceOAuthExchangeRequest: 'salesforce:oauth:exchange',
  SalesforceOAuthRefreshRequest: 'salesforce:oauth:refresh',
  SalesforceOAuthValidateRequest: 'salesforce:oauth:validate',
  SavedOutputCreateRequest: 'saved_output:create',
  SavedOutputDeleteRequest: 'saved_output:delete',
  SavedOutputGetRequest: 'saved_output:get',
  SavedOutputListRequest: 'saved_output:list',
  SavedOutputUpdateRequest: 'saved_output:update',
  SentryOAuthExchangeRequest: 'sentry:oauth:exchange',
  SentryOAuthRefreshRequest: 'sentry:oauth:refresh',
  SentryOAuthValidateRequest: 'sentry:oauth:validate',
  ShareBuilderAskRequest: 'workflow:builder:share_ask',
  ShareCreateRequest: 'share:create',
  ShareDeleteRequest: 'share:delete',
  ShareInviteAcceptRequest: 'share:invite_accept',
  ShareInviteLinkRequest: 'share:invite_link',
  ShareLeaveRequest: 'share:leave',
  ShareListRequest: 'share:list',
  ShareListSharedWithMeRequest: 'share:list_shared_with_me',
  ShareUpdateRequest: 'share:update',
  SharedAgentResumeRequest: 'shared_agent:resume',
  SharedAgentSendRequest: 'shared_agent:send',
  ShopifyOAuthExchangeRequest: 'shopify:oauth:exchange',
  ShopifyOAuthRefreshRequest: 'shopify:oauth:refresh',
  ShopifyOAuthValidateRequest: 'shopify:oauth:validate',
  SkillCreateRequest: 'skill:create',
  SkillDeleteRequest: 'skill:delete',
  SkillGetRequest: 'skill:get',
  SkillGetWorkflowRequest: 'skill:get_workflow',
  SkillListRequest: 'skill:list',
  SkillMuteRequest: 'skill:mute',
  SkillUpdateRequest: 'skill:update',
  SkillUpdateWorkflowRequest: 'skill:update_workflow',
  SlackOAuthExchangeRequest: 'slack:oauth:exchange',
  SlackOAuthRefreshRequest: 'slack:oauth:refresh',
  SlackOAuthValidateRequest: 'slack:oauth:validate',
  StripeOAuthExchangeRequest: 'stripe:oauth:exchange',
  StripeOAuthRefreshRequest: 'stripe:oauth:refresh',
  StripeOAuthValidateRequest: 'stripe:oauth:validate',
  SubmitFeedbackRequest: 'feedback:submit',
  SupabaseOAuthExchangeRequest: 'supabase:oauth:exchange',
  SupabaseOAuthRefreshRequest: 'supabase:oauth:refresh',
  SupabaseOAuthSelectProjectRequest: 'supabase:oauth:select_project',
  SupabaseOAuthValidateRequest: 'supabase:oauth:validate',
  ThreadsOAuthExchangeRequest: 'threads:oauth:exchange',
  ThreadsOAuthRefreshRequest: 'threads:oauth:refresh',
  ThreadsOAuthValidateRequest: 'threads:oauth:validate',
  TikTokOAuthExchangeRequest: 'tiktok:oauth:exchange',
  TikTokOAuthRefreshRequest: 'tiktok:oauth:refresh',
  TikTokOAuthValidateRequest: 'tiktok:oauth:validate',
  ToolCallListRequest: 'tool_calls:list',
  TwitterOAuthExchangeRequest: 'twitter:oauth:exchange',
  TwitterOAuthRefreshRequest: 'twitter:oauth:refresh',
  TwitterOAuthValidateRequest: 'twitter:oauth:validate',
  TypeformOAuthExchangeRequest: 'typeform:oauth:exchange',
  UpdateAuthRequest: 'update_auth',
  UsageDataRequest: 'usage:data',
  UsageLogsRequest: 'usage:logs',
  WebflowOAuthExchangeRequest: 'webflow:oauth:exchange',
  WebflowOAuthRefreshRequest: 'webflow:oauth:refresh',
  WebflowOAuthValidateRequest: 'webflow:oauth:validate',
  WhatsAppQRStartRequest: 'whatsapp:qr:start',
  WhatsAppQRStatusRequest: 'whatsapp:qr:status',
  WordPressOAuthExchangeRequest: 'wordpress:oauth:exchange',
  WordPressOAuthRefreshRequest: 'wordpress:oauth:refresh',
  WordPressOAuthValidateRequest: 'wordpress:oauth:validate',
  WorkflowAutofillRequest: 'workflow:builder:autofill',
  WorkflowBuilderEditRequest: 'workflow:builder:edit',
  WorkflowCheckpointCreateRequest: 'workflow:checkpoint:create',
  WorkflowCheckpointDeleteRequest: 'workflow:checkpoint:delete',
  WorkflowCheckpointListRequest: 'workflow:checkpoint:list',
  WorkflowCheckpointRestoreRequest: 'workflow:checkpoint:restore',
  WorkflowClearNodeStateRequest: 'workflow:clear_node_state',
  WorkflowCollabTokenRequest: 'workflow:collab_token',
  WorkflowCreateRequest: 'workflow:create',
  WorkflowDeleteRequest: 'workflow:delete',
  WorkflowExecuteRequest: 'workflow:execute',
  WorkflowExecutionCountsRequest: 'workflow:get_execution_counts',
  WorkflowExecutionDetailRequest: 'workflow:get_execution_detail',
  WorkflowExecutionListRequest: 'workflow:list_executions',
  WorkflowGetNodeOutputHistoryRequest: 'workflow:get_node_output_history',
  WorkflowGetNodeOutputsRequest: 'workflow:get_node_outputs',
  WorkflowGetRequest: 'workflow:get',
  WorkflowListRequest: 'workflow:list',
  WorkflowListTrashRequest: 'workflow:list_trash',
  WorkflowLoadNodeStateRequest: 'workflow:load_node_state',
  WorkflowMCPCreateWorkflowRequest: 'workflow:mcp:create_workflow',
  WorkflowMCPDeleteWorkflowRequest: 'workflow:mcp:delete_workflow',
  WorkflowMCPGetExecutionStatusRequest: 'workflow:mcp:get_execution_status',
  WorkflowMCPGetNodeConfigRequest: 'workflow:mcp:get_node_config',
  WorkflowMCPGetNodeConfigSchemaRequest: 'workflow:mcp:get_node_config_schema',
  WorkflowMCPGetNodeInputRequest: 'workflow:mcp:get_node_input',
  WorkflowMCPGetNodeOutputRequest: 'workflow:mcp:get_node_output',
  WorkflowMCPGetOpenWorkflowRequest: 'workflow:mcp:get_open_workflow',
  WorkflowMCPGetSelectedNodeRequest: 'workflow:mcp:get_selected_node',
  WorkflowMCPListCredentialsRequest: 'workflow:mcp:list_credentials',
  WorkflowMCPListSavedOutputsRequest: 'workflow:mcp:list_saved_outputs',
  WorkflowMCPListWorkflowsRequest: 'workflow:mcp:list_workflows',
  WorkflowMCPLoadFieldOptionsRequest: 'workflow:mcp:load_field_options',
  WorkflowMCPOpenWorkflowRequest: 'workflow:mcp:open_workflow',
  WorkflowMCPResponseRequest: 'workflow:mcp:response',
  WorkflowMCPRunNodeRequest: 'workflow:mcp:run_node',
  WorkflowMCPRunWorkflowRequest: 'workflow:mcp:run_workflow',
  WorkflowMCPSearchNodesRequest: 'workflow:mcp:search_nodes',
  WorkflowMCPUpdateInterfaceRequest: 'workflow:mcp:update_interface',
  WorkflowMCPUpdateWorkflowMetadataRequest: 'workflow:mcp:update_workflow_metadata',
  WorkflowMoveToFolderRequest: 'workflow_folder:move_workflow',
  WorkflowNodeConfigSchemaRequest: 'workflow:node:get_config_schema',
  WorkflowNodeEvaluateExpressionRequest: 'workflow:node:evaluate_expression',
  WorkflowNodeGetConfigRequest: 'workflow:node:get_config',
  WorkflowNodeLoadOptionsRequest: 'workflow:node:load_options',
  WorkflowNodeLoadValueRequest: 'workflow:node:load_value',
  WorkflowNodeOutputRequest: 'workflow:get_node_output',
  WorkflowNodeSetConfigRequest: 'workflow:node:set_config',
  WorkflowNodeValidateConfigRequest: 'workflow:node:validate_config',
  WorkflowPermanentDeleteRequest: 'workflow:permanent_delete',
  WorkflowRestoreRequest: 'workflow:restore',
  WorkflowSaveNodeStateRequest: 'workflow:save_node_state',
  WorkflowStateGetRequest: 'workflow:state:get',
  WorkflowStateKeysRequest: 'workflow:state:keys',
  WorkflowStateSetRequest: 'workflow:state:set',
  WorkflowUpdateRequest: 'workflow:update',
  YjsSyncRequest: 'yjs:sync',
  ZendeskOAuthExchangeRequest: 'zendesk:oauth:exchange',
  ZendeskOAuthRefreshRequest: 'zendesk:oauth:refresh',
  ZendeskOAuthValidateRequest: 'zendesk:oauth:validate',
  ZoomOAuthExchangeRequest: 'zoom:oauth:exchange',
  ZoomOAuthRefreshRequest: 'zoom:oauth:refresh',
  ZoomOAuthValidateRequest: 'zoom:oauth:validate'
} as const;

// Type for events with their names included
export type ClientEventWithName<T extends keyof typeof ClientEventNames> = {
  event_name: typeof ClientEventNames[T];
  data: T extends keyof ClientEventMap ? ClientEventMap[T] : never;
};

// Helper type to map event names to their data types (auto-generated)
interface ClientEventMap {
  ActivityListRequest: ActivityListRequest
  AgentBuilderDecisionRequest: AgentBuilderDecisionRequest
  AgentCopyFromRequest: AgentCopyFromRequest
  AgentCopyToRequest: AgentCopyToRequest
  AgentEditFileRequest: AgentEditFileRequest
  AgentListFilesRequest: AgentListFilesRequest
  AgentPauseRequest: AgentPauseRequest
  AgentReadFileRequest: AgentReadFileRequest
  AgentRunCommandRequest: AgentRunCommandRequest
  AgentSetCwdRequest: AgentSetCwdRequest
  AgentShareGetOrCreateRequest: AgentShareGetOrCreateRequest
  AgentShareRotateRequest: AgentShareRotateRequest
  AgentShareSetActiveRequest: AgentShareSetActiveRequest
  AgentWorkspaceDeleteRequest: AgentWorkspaceDeleteRequest
  AgentWorkspaceListRequest: AgentWorkspaceListRequest
  AgentWriteFileRequest: AgentWriteFileRequest
  AirtableOAuthExchangeRequest: AirtableOAuthExchangeRequest
  AirtableOAuthRefreshRequest: AirtableOAuthRefreshRequest
  AirtableOAuthValidateRequest: AirtableOAuthValidateRequest
  ApolloOAuthExchangeRequest: ApolloOAuthExchangeRequest
  ApolloOAuthRefreshRequest: ApolloOAuthRefreshRequest
  ApolloOAuthValidateRequest: ApolloOAuthValidateRequest
  ApprovalListRequest: ApprovalListRequest
  ApprovalRespondRequest: ApprovalRespondRequest
  AsanaOAuthExchangeRequest: AsanaOAuthExchangeRequest
  AsanaOAuthRefreshRequest: AsanaOAuthRefreshRequest
  AsanaOAuthValidateRequest: AsanaOAuthValidateRequest
  AtlassianOAuthExchangeRequest: AtlassianOAuthExchangeRequest
  AtlassianOAuthRefreshRequest: AtlassianOAuthRefreshRequest
  AtlassianOAuthValidateRequest: AtlassianOAuthValidateRequest
  AttioOAuthExchangeRequest: AttioOAuthExchangeRequest
  AttioOAuthRefreshRequest: AttioOAuthRefreshRequest
  AttioOAuthValidateRequest: AttioOAuthValidateRequest
  BambooHROAuthExchangeRequest: BambooHROAuthExchangeRequest
  BambooHROAuthRefreshRequest: BambooHROAuthRefreshRequest
  BambooHROAuthValidateRequest: BambooHROAuthValidateRequest
  BoxOAuthExchangeRequest: BoxOAuthExchangeRequest
  BoxOAuthRefreshRequest: BoxOAuthRefreshRequest
  BoxOAuthValidateRequest: BoxOAuthValidateRequest
  CalComOAuthExchangeRequest: CalComOAuthExchangeRequest
  CalComOAuthRefreshRequest: CalComOAuthRefreshRequest
  CalComOAuthValidateRequest: CalComOAuthValidateRequest
  CalendlyOAuthExchangeRequest: CalendlyOAuthExchangeRequest
  CalendlyOAuthRefreshRequest: CalendlyOAuthRefreshRequest
  CalendlyOAuthValidateRequest: CalendlyOAuthValidateRequest
  CanvaOAuthExchangeRequest: CanvaOAuthExchangeRequest
  CanvaOAuthRefreshRequest: CanvaOAuthRefreshRequest
  CanvaOAuthValidateRequest: CanvaOAuthValidateRequest
  ChatMessageRequest: ChatMessageRequest
  ClaudeCodeAuthExchangeRequest: ClaudeCodeAuthExchangeRequest
  ClaudeCodeAuthStartRequest: ClaudeCodeAuthStartRequest
  ClickUpOAuthExchangeRequest: ClickUpOAuthExchangeRequest
  ClickUpOAuthRefreshRequest: ClickUpOAuthRefreshRequest
  ClickUpOAuthValidateRequest: ClickUpOAuthValidateRequest
  CloudflareOAuthExchangeRequest: CloudflareOAuthExchangeRequest
  CloudflareOAuthRefreshRequest: CloudflareOAuthRefreshRequest
  CloudflareOAuthValidateRequest: CloudflareOAuthValidateRequest
  CodexDeviceCodePollRequest: CodexDeviceCodePollRequest
  CodexDeviceCodeStartRequest: CodexDeviceCodeStartRequest
  CredentialAuthorizeForWorkflowRequest: CredentialAuthorizeForWorkflowRequest
  CredentialCreateRequest: CredentialCreateRequest
  CredentialDeleteRequest: CredentialDeleteRequest
  CredentialDisplayInfoRequest: CredentialDisplayInfoRequest
  CredentialGetRequest: CredentialGetRequest
  CredentialListRequest: CredentialListRequest
  CredentialRequestCancelRequest: CredentialRequestCancelRequest
  CredentialRequestCreateRequest: CredentialRequestCreateRequest
  CredentialRequestListRequest: CredentialRequestListRequest
  CredentialTestConnectionRequest: CredentialTestConnectionRequest
  CredentialUpdateRequest: CredentialUpdateRequest
  CredentialValidateAccessRequest: CredentialValidateAccessRequest
  DeleteConversationRequest: DeleteConversationRequest
  DiscordOAuthExchangeRequest: DiscordOAuthExchangeRequest
  DiscordOAuthRefreshRequest: DiscordOAuthRefreshRequest
  DiscordOAuthValidateRequest: DiscordOAuthValidateRequest
  DropboxOAuthExchangeRequest: DropboxOAuthExchangeRequest
  DropboxOAuthRefreshRequest: DropboxOAuthRefreshRequest
  DropboxOAuthValidateRequest: DropboxOAuthValidateRequest
  FacebookOAuthExchangeRequest: FacebookOAuthExchangeRequest
  FacebookOAuthRefreshRequest: FacebookOAuthRefreshRequest
  FacebookOAuthValidateRequest: FacebookOAuthValidateRequest
  FacebookPagesOAuthExchangeRequest: FacebookPagesOAuthExchangeRequest
  FacebookPagesOAuthRefreshRequest: FacebookPagesOAuthRefreshRequest
  FacebookPagesOAuthValidateRequest: FacebookPagesOAuthValidateRequest
  FathomOAuthExchangeRequest: FathomOAuthExchangeRequest
  FathomOAuthRefreshRequest: FathomOAuthRefreshRequest
  FathomOAuthValidateRequest: FathomOAuthValidateRequest
  FolderCreateRequest: FolderCreateRequest
  FolderDeleteRequest: FolderDeleteRequest
  FolderGetPathRequest: FolderGetPathRequest
  FolderGetRequest: FolderGetRequest
  FolderGetTreeRequest: FolderGetTreeRequest
  FolderListRequest: FolderListRequest
  FolderUpdateRequest: FolderUpdateRequest
  GetLatestConversationForWorkflowRequest: GetLatestConversationForWorkflowRequest
  GitLabOAuthExchangeRequest: GitLabOAuthExchangeRequest
  GitLabOAuthRefreshRequest: GitLabOAuthRefreshRequest
  GitLabOAuthValidateRequest: GitLabOAuthValidateRequest
  GithubOAuthExchangeRequest: GithubOAuthExchangeRequest
  GithubOAuthRefreshRequest: GithubOAuthRefreshRequest
  GithubOAuthValidateRequest: GithubOAuthValidateRequest
  GoogleOAuthExchangeRequest: GoogleOAuthExchangeRequest
  GoogleOAuthRefreshRequest: GoogleOAuthRefreshRequest
  GoogleOAuthValidateRequest: GoogleOAuthValidateRequest
  HubSpotOAuthExchangeRequest: HubSpotOAuthExchangeRequest
  HubSpotOAuthRefreshRequest: HubSpotOAuthRefreshRequest
  HubSpotOAuthValidateRequest: HubSpotOAuthValidateRequest
  InstagramLoginOAuthExchangeRequest: InstagramLoginOAuthExchangeRequest
  InstagramLoginOAuthRefreshRequest: InstagramLoginOAuthRefreshRequest
  InstagramLoginOAuthValidateRequest: InstagramLoginOAuthValidateRequest
  InstanceKeysDeleteRequest: InstanceKeysDeleteRequest
  InstanceKeysListRequest: InstanceKeysListRequest
  InstanceKeysSetRequest: InstanceKeysSetRequest
  InstanceOAuthDeleteRequest: InstanceOAuthDeleteRequest
  InstanceOAuthListRequest: InstanceOAuthListRequest
  InstanceOAuthSetRequest: InstanceOAuthSetRequest
  IntercomOAuthExchangeRequest: IntercomOAuthExchangeRequest
  IntercomOAuthRefreshRequest: IntercomOAuthRefreshRequest
  IntercomOAuthValidateRequest: IntercomOAuthValidateRequest
  KlaviyoOAuthExchangeRequest: KlaviyoOAuthExchangeRequest
  KlaviyoOAuthRefreshRequest: KlaviyoOAuthRefreshRequest
  KlaviyoOAuthValidateRequest: KlaviyoOAuthValidateRequest
  LinearOAuthExchangeRequest: LinearOAuthExchangeRequest
  LinearOAuthRefreshRequest: LinearOAuthRefreshRequest
  LinearOAuthValidateRequest: LinearOAuthValidateRequest
  LinkedInOAuthExchangeRequest: LinkedInOAuthExchangeRequest
  LinkedInOAuthRefreshRequest: LinkedInOAuthRefreshRequest
  LinkedInOAuthValidateRequest: LinkedInOAuthValidateRequest
  ListConversationsForAgentRequest: ListConversationsForAgentRequest
  ListConversationsRequest: ListConversationsRequest
  ListPendingBuilderRunsRequest: ListPendingBuilderRunsRequest
  MCPFolderGetTreeRequest: MCPFolderGetTreeRequest
  MCPOAuthDiscoverRequest: MCPOAuthDiscoverRequest
  MCPOAuthExchangeRequest: MCPOAuthExchangeRequest
  MCPOAuthRegisterClientRequest: MCPOAuthRegisterClientRequest
  MailchimpOAuthExchangeRequest: MailchimpOAuthExchangeRequest
  MetaOAuthExchangeRequest: MetaOAuthExchangeRequest
  MetaOAuthRefreshRequest: MetaOAuthRefreshRequest
  MetaOAuthValidateRequest: MetaOAuthValidateRequest
  MicrosoftOAuthExchangeRequest: MicrosoftOAuthExchangeRequest
  MicrosoftOAuthRefreshRequest: MicrosoftOAuthRefreshRequest
  MicrosoftOAuthValidateRequest: MicrosoftOAuthValidateRequest
  MondayOAuthExchangeRequest: MondayOAuthExchangeRequest
  MondayOAuthRefreshRequest: MondayOAuthRefreshRequest
  MondayOAuthValidateRequest: MondayOAuthValidateRequest
  NodeOutputSchemaRequest: NodeOutputSchemaRequest
  NotificationPrefsGetRequest: NotificationPrefsGetRequest
  NotificationPrefsUpdateRequest: NotificationPrefsUpdateRequest
  NotionOAuthExchangeRequest: NotionOAuthExchangeRequest
  NotionOAuthRefreshRequest: NotionOAuthRefreshRequest
  NotionOAuthValidateRequest: NotionOAuthValidateRequest
  OnboardingCompletionGetRequest: OnboardingCompletionGetRequest
  OnboardingCompletionUpdateRequest: OnboardingCompletionUpdateRequest
  OnboardingSkipRequest: OnboardingSkipRequest
  OnboardingSubmitRequest: OnboardingSubmitRequest
  PagerDutyOAuthExchangeRequest: PagerDutyOAuthExchangeRequest
  PagerDutyOAuthRefreshRequest: PagerDutyOAuthRefreshRequest
  PagerDutyOAuthValidateRequest: PagerDutyOAuthValidateRequest
  ParallelOAuthExchangeRequest: ParallelOAuthExchangeRequest
  ParallelOAuthValidateRequest: ParallelOAuthValidateRequest
  PipedriveOAuthExchangeRequest: PipedriveOAuthExchangeRequest
  PipedriveOAuthRefreshRequest: PipedriveOAuthRefreshRequest
  PipedriveOAuthValidateRequest: PipedriveOAuthValidateRequest
  PostHogOAuthExchangeRequest: PostHogOAuthExchangeRequest
  PostHogOAuthRefreshRequest: PostHogOAuthRefreshRequest
  PostHogOAuthValidateRequest: PostHogOAuthValidateRequest
  QuickBooksOAuthExchangeRequest: QuickBooksOAuthExchangeRequest
  QuickBooksOAuthRefreshRequest: QuickBooksOAuthRefreshRequest
  QuickBooksOAuthValidateRequest: QuickBooksOAuthValidateRequest
  RedditOAuthExchangeRequest: RedditOAuthExchangeRequest
  RedditOAuthRefreshRequest: RedditOAuthRefreshRequest
  RedditOAuthValidateRequest: RedditOAuthValidateRequest
  RehearsalRunRequest: RehearsalRunRequest
  RehearsalScenariosRequest: RehearsalScenariosRequest
  ResourceCreateRequest: ResourceCreateRequest
  ResourceDatasetAppendRequest: ResourceDatasetAppendRequest
  ResourceDatasetDeleteRowsRequest: ResourceDatasetDeleteRowsRequest
  ResourceDatasetRowsRequest: ResourceDatasetRowsRequest
  ResourceDatasetUpdateRowRequest: ResourceDatasetUpdateRowRequest
  ResourceDeleteRequest: ResourceDeleteRequest
  ResourceDownloadUrlRequest: ResourceDownloadUrlRequest
  ResourceForkRequest: ResourceForkRequest
  ResourceGetRequest: ResourceGetRequest
  ResourceListRequest: ResourceListRequest
  ResourceUploadUrlRequest: ResourceUploadUrlRequest
  ResumeConversationRequest: ResumeConversationRequest
  RunShareCreateRequest: RunShareCreateRequest
  SalesforceOAuthExchangeRequest: SalesforceOAuthExchangeRequest
  SalesforceOAuthRefreshRequest: SalesforceOAuthRefreshRequest
  SalesforceOAuthValidateRequest: SalesforceOAuthValidateRequest
  SavedOutputCreateRequest: SavedOutputCreateRequest
  SavedOutputDeleteRequest: SavedOutputDeleteRequest
  SavedOutputGetRequest: SavedOutputGetRequest
  SavedOutputListRequest: SavedOutputListRequest
  SavedOutputUpdateRequest: SavedOutputUpdateRequest
  SentryOAuthExchangeRequest: SentryOAuthExchangeRequest
  SentryOAuthRefreshRequest: SentryOAuthRefreshRequest
  SentryOAuthValidateRequest: SentryOAuthValidateRequest
  ShareBuilderAskRequest: ShareBuilderAskRequest
  ShareCreateRequest: ShareCreateRequest
  ShareDeleteRequest: ShareDeleteRequest
  ShareInviteAcceptRequest: ShareInviteAcceptRequest
  ShareInviteLinkRequest: ShareInviteLinkRequest
  ShareLeaveRequest: ShareLeaveRequest
  ShareListRequest: ShareListRequest
  ShareListSharedWithMeRequest: ShareListSharedWithMeRequest
  ShareUpdateRequest: ShareUpdateRequest
  SharedAgentResumeRequest: SharedAgentResumeRequest
  SharedAgentSendRequest: SharedAgentSendRequest
  ShopifyOAuthExchangeRequest: ShopifyOAuthExchangeRequest
  ShopifyOAuthRefreshRequest: ShopifyOAuthRefreshRequest
  ShopifyOAuthValidateRequest: ShopifyOAuthValidateRequest
  SkillCreateRequest: SkillCreateRequest
  SkillDeleteRequest: SkillDeleteRequest
  SkillGetRequest: SkillGetRequest
  SkillGetWorkflowRequest: SkillGetWorkflowRequest
  SkillListRequest: SkillListRequest
  SkillMuteRequest: SkillMuteRequest
  SkillUpdateRequest: SkillUpdateRequest
  SkillUpdateWorkflowRequest: SkillUpdateWorkflowRequest
  SlackOAuthExchangeRequest: SlackOAuthExchangeRequest
  SlackOAuthRefreshRequest: SlackOAuthRefreshRequest
  SlackOAuthValidateRequest: SlackOAuthValidateRequest
  StripeOAuthExchangeRequest: StripeOAuthExchangeRequest
  StripeOAuthRefreshRequest: StripeOAuthRefreshRequest
  StripeOAuthValidateRequest: StripeOAuthValidateRequest
  SubmitFeedbackRequest: SubmitFeedbackRequest
  SupabaseOAuthExchangeRequest: SupabaseOAuthExchangeRequest
  SupabaseOAuthRefreshRequest: SupabaseOAuthRefreshRequest
  SupabaseOAuthSelectProjectRequest: SupabaseOAuthSelectProjectRequest
  SupabaseOAuthValidateRequest: SupabaseOAuthValidateRequest
  ThreadsOAuthExchangeRequest: ThreadsOAuthExchangeRequest
  ThreadsOAuthRefreshRequest: ThreadsOAuthRefreshRequest
  ThreadsOAuthValidateRequest: ThreadsOAuthValidateRequest
  TikTokOAuthExchangeRequest: TikTokOAuthExchangeRequest
  TikTokOAuthRefreshRequest: TikTokOAuthRefreshRequest
  TikTokOAuthValidateRequest: TikTokOAuthValidateRequest
  ToolCallListRequest: ToolCallListRequest
  TwitterOAuthExchangeRequest: TwitterOAuthExchangeRequest
  TwitterOAuthRefreshRequest: TwitterOAuthRefreshRequest
  TwitterOAuthValidateRequest: TwitterOAuthValidateRequest
  TypeformOAuthExchangeRequest: TypeformOAuthExchangeRequest
  UpdateAuthRequest: UpdateAuthRequest
  UsageDataRequest: UsageDataRequest
  UsageLogsRequest: UsageLogsRequest
  WebflowOAuthExchangeRequest: WebflowOAuthExchangeRequest
  WebflowOAuthRefreshRequest: WebflowOAuthRefreshRequest
  WebflowOAuthValidateRequest: WebflowOAuthValidateRequest
  WhatsAppQRStartRequest: WhatsAppQRStartRequest
  WhatsAppQRStatusRequest: WhatsAppQRStatusRequest
  WordPressOAuthExchangeRequest: WordPressOAuthExchangeRequest
  WordPressOAuthRefreshRequest: WordPressOAuthRefreshRequest
  WordPressOAuthValidateRequest: WordPressOAuthValidateRequest
  WorkflowAutofillRequest: WorkflowAutofillRequest
  WorkflowBuilderEditRequest: WorkflowBuilderEditRequest
  WorkflowCheckpointCreateRequest: WorkflowCheckpointCreateRequest
  WorkflowCheckpointDeleteRequest: WorkflowCheckpointDeleteRequest
  WorkflowCheckpointListRequest: WorkflowCheckpointListRequest
  WorkflowCheckpointRestoreRequest: WorkflowCheckpointRestoreRequest
  WorkflowClearNodeStateRequest: WorkflowClearNodeStateRequest
  WorkflowCollabTokenRequest: WorkflowCollabTokenRequest
  WorkflowCreateRequest: WorkflowCreateRequest
  WorkflowDeleteRequest: WorkflowDeleteRequest
  WorkflowExecuteRequest: WorkflowExecuteRequest
  WorkflowExecutionCountsRequest: WorkflowExecutionCountsRequest
  WorkflowExecutionDetailRequest: WorkflowExecutionDetailRequest
  WorkflowExecutionListRequest: WorkflowExecutionListRequest
  WorkflowGetNodeOutputHistoryRequest: WorkflowGetNodeOutputHistoryRequest
  WorkflowGetNodeOutputsRequest: WorkflowGetNodeOutputsRequest
  WorkflowGetRequest: WorkflowGetRequest
  WorkflowListRequest: WorkflowListRequest
  WorkflowListTrashRequest: WorkflowListTrashRequest
  WorkflowLoadNodeStateRequest: WorkflowLoadNodeStateRequest
  WorkflowMCPCreateWorkflowRequest: WorkflowMCPCreateWorkflowRequest
  WorkflowMCPDeleteWorkflowRequest: WorkflowMCPDeleteWorkflowRequest
  WorkflowMCPGetExecutionStatusRequest: WorkflowMCPGetExecutionStatusRequest
  WorkflowMCPGetNodeConfigRequest: WorkflowMCPGetNodeConfigRequest
  WorkflowMCPGetNodeConfigSchemaRequest: WorkflowMCPGetNodeConfigSchemaRequest
  WorkflowMCPGetNodeInputRequest: WorkflowMCPGetNodeInputRequest
  WorkflowMCPGetNodeOutputRequest: WorkflowMCPGetNodeOutputRequest
  WorkflowMCPGetOpenWorkflowRequest: WorkflowMCPGetOpenWorkflowRequest
  WorkflowMCPGetSelectedNodeRequest: WorkflowMCPGetSelectedNodeRequest
  WorkflowMCPListCredentialsRequest: WorkflowMCPListCredentialsRequest
  WorkflowMCPListSavedOutputsRequest: WorkflowMCPListSavedOutputsRequest
  WorkflowMCPListWorkflowsRequest: WorkflowMCPListWorkflowsRequest
  WorkflowMCPLoadFieldOptionsRequest: WorkflowMCPLoadFieldOptionsRequest
  WorkflowMCPOpenWorkflowRequest: WorkflowMCPOpenWorkflowRequest
  WorkflowMCPResponseRequest: WorkflowMCPResponseRequest
  WorkflowMCPRunNodeRequest: WorkflowMCPRunNodeRequest
  WorkflowMCPRunWorkflowRequest: WorkflowMCPRunWorkflowRequest
  WorkflowMCPSearchNodesRequest: WorkflowMCPSearchNodesRequest
  WorkflowMCPUpdateInterfaceRequest: WorkflowMCPUpdateInterfaceRequest
  WorkflowMCPUpdateWorkflowMetadataRequest: WorkflowMCPUpdateWorkflowMetadataRequest
  WorkflowMoveToFolderRequest: WorkflowMoveToFolderRequest
  WorkflowNodeConfigSchemaRequest: WorkflowNodeConfigSchemaRequest
  WorkflowNodeEvaluateExpressionRequest: WorkflowNodeEvaluateExpressionRequest
  WorkflowNodeGetConfigRequest: WorkflowNodeGetConfigRequest
  WorkflowNodeLoadOptionsRequest: WorkflowNodeLoadOptionsRequest
  WorkflowNodeLoadValueRequest: WorkflowNodeLoadValueRequest
  WorkflowNodeOutputRequest: WorkflowNodeOutputRequest
  WorkflowNodeSetConfigRequest: WorkflowNodeSetConfigRequest
  WorkflowNodeValidateConfigRequest: WorkflowNodeValidateConfigRequest
  WorkflowPermanentDeleteRequest: WorkflowPermanentDeleteRequest
  WorkflowRestoreRequest: WorkflowRestoreRequest
  WorkflowSaveNodeStateRequest: WorkflowSaveNodeStateRequest
  WorkflowStateGetRequest: WorkflowStateGetRequest
  WorkflowStateKeysRequest: WorkflowStateKeysRequest
  WorkflowStateSetRequest: WorkflowStateSetRequest
  WorkflowUpdateRequest: WorkflowUpdateRequest
  YjsSyncRequest: Uint8Array | number[]
  ZendeskOAuthExchangeRequest: ZendeskOAuthExchangeRequest
  ZendeskOAuthRefreshRequest: ZendeskOAuthRefreshRequest
  ZendeskOAuthValidateRequest: ZendeskOAuthValidateRequest
  ZoomOAuthExchangeRequest: ZoomOAuthExchangeRequest
  ZoomOAuthRefreshRequest: ZoomOAuthRefreshRequest
  ZoomOAuthValidateRequest: ZoomOAuthValidateRequest
}

// Request to Response Type Mapping (auto-discovered)
export interface RequestResponseMap {
  AirtableOAuthExchangeRequest: AirtableOAuthExchangeResponse;
  AirtableOAuthRefreshRequest: AirtableOAuthRefreshResponse;
  AirtableOAuthValidateRequest: AirtableOAuthValidateResponse;
  ApolloOAuthExchangeRequest: ApolloOAuthExchangeResponse;
  ApolloOAuthRefreshRequest: ApolloOAuthRefreshResponse;
  ApolloOAuthValidateRequest: ApolloOAuthValidateResponse;
  AsanaOAuthExchangeRequest: AsanaOAuthExchangeResponse;
  AsanaOAuthRefreshRequest: AsanaOAuthRefreshResponse;
  AsanaOAuthValidateRequest: AsanaOAuthValidateResponse;
  AtlassianOAuthExchangeRequest: AtlassianOAuthExchangeResponse;
  AtlassianOAuthRefreshRequest: AtlassianOAuthRefreshResponse;
  AtlassianOAuthValidateRequest: AtlassianOAuthValidateResponse;
  AttioOAuthExchangeRequest: AttioOAuthExchangeResponse;
  AttioOAuthRefreshRequest: AttioOAuthRefreshResponse;
  AttioOAuthValidateRequest: AttioOAuthValidateResponse;
  BambooHROAuthExchangeRequest: BambooHROAuthExchangeResponse;
  BambooHROAuthRefreshRequest: BambooHROAuthRefreshResponse;
  BambooHROAuthValidateRequest: BambooHROAuthValidateResponse;
  BoxOAuthExchangeRequest: BoxOAuthExchangeResponse;
  BoxOAuthRefreshRequest: BoxOAuthRefreshResponse;
  BoxOAuthValidateRequest: BoxOAuthValidateResponse;
  CalComOAuthExchangeRequest: CalComOAuthExchangeResponse;
  CalComOAuthRefreshRequest: CalComOAuthRefreshResponse;
  CalComOAuthValidateRequest: CalComOAuthValidateResponse;
  CalendlyOAuthExchangeRequest: CalendlyOAuthExchangeResponse;
  CalendlyOAuthRefreshRequest: CalendlyOAuthRefreshResponse;
  CalendlyOAuthValidateRequest: CalendlyOAuthValidateResponse;
  CanvaOAuthExchangeRequest: CanvaOAuthExchangeResponse;
  CanvaOAuthRefreshRequest: CanvaOAuthRefreshResponse;
  CanvaOAuthValidateRequest: CanvaOAuthValidateResponse;
  ClaudeCodeAuthExchangeRequest: ClaudeCodeAuthExchangeResponse;
  ClaudeCodeAuthStartRequest: ClaudeCodeAuthStartResponse;
  ClickUpOAuthExchangeRequest: ClickUpOAuthExchangeResponse;
  ClickUpOAuthRefreshRequest: ClickUpOAuthRefreshResponse;
  ClickUpOAuthValidateRequest: ClickUpOAuthValidateResponse;
  CloudflareOAuthExchangeRequest: CloudflareOAuthExchangeResponse;
  CloudflareOAuthRefreshRequest: CloudflareOAuthRefreshResponse;
  CloudflareOAuthValidateRequest: CloudflareOAuthValidateResponse;
  CodexDeviceCodePollRequest: CodexDeviceCodePollResponse;
  CodexDeviceCodeStartRequest: CodexDeviceCodeStartResponse;
  CredentialCreateRequest: CredentialCreateResponse;
  CredentialDeleteRequest: CredentialDeleteResponse;
  CredentialGetRequest: CredentialGetResponse;
  CredentialListRequest: CredentialListResponse;
  CredentialRequestCancelRequest: CredentialRequestCancelResponse;
  CredentialRequestCreateRequest: CredentialRequestCreateResponse;
  CredentialRequestListRequest: CredentialRequestListResponse;
  CredentialTestConnectionRequest: CredentialTestConnectionResponse;
  CredentialUpdateRequest: CredentialUpdateResponse;
  DiscordOAuthExchangeRequest: DiscordOAuthExchangeResponse;
  DiscordOAuthRefreshRequest: DiscordOAuthRefreshResponse;
  DiscordOAuthValidateRequest: DiscordOAuthValidateResponse;
  DropboxOAuthExchangeRequest: DropboxOAuthExchangeResponse;
  DropboxOAuthRefreshRequest: DropboxOAuthRefreshResponse;
  DropboxOAuthValidateRequest: DropboxOAuthValidateResponse;
  FacebookOAuthExchangeRequest: FacebookOAuthExchangeResponse;
  FacebookOAuthRefreshRequest: FacebookOAuthRefreshResponse;
  FacebookOAuthValidateRequest: FacebookOAuthValidateResponse;
  FacebookPagesOAuthExchangeRequest: FacebookPagesOAuthExchangeResponse;
  FacebookPagesOAuthRefreshRequest: FacebookPagesOAuthRefreshResponse;
  FacebookPagesOAuthValidateRequest: FacebookPagesOAuthValidateResponse;
  FathomOAuthExchangeRequest: FathomOAuthExchangeResponse;
  FathomOAuthRefreshRequest: FathomOAuthRefreshResponse;
  FathomOAuthValidateRequest: FathomOAuthValidateResponse;
  FolderCreateRequest: FolderCreateResponse;
  FolderDeleteRequest: FolderDeleteResponse;
  FolderGetRequest: FolderGetResponse;
  FolderListRequest: FolderListResponse;
  FolderUpdateRequest: FolderUpdateResponse;
  GitLabOAuthExchangeRequest: GitLabOAuthExchangeResponse;
  GitLabOAuthRefreshRequest: GitLabOAuthRefreshResponse;
  GitLabOAuthValidateRequest: GitLabOAuthValidateResponse;
  GithubOAuthExchangeRequest: GithubOAuthExchangeResponse;
  GithubOAuthRefreshRequest: GithubOAuthRefreshResponse;
  GithubOAuthValidateRequest: GithubOAuthValidateResponse;
  GoogleOAuthExchangeRequest: GoogleOAuthExchangeResponse;
  GoogleOAuthRefreshRequest: GoogleOAuthRefreshResponse;
  GoogleOAuthValidateRequest: GoogleOAuthValidateResponse;
  HubSpotOAuthExchangeRequest: HubSpotOAuthExchangeResponse;
  HubSpotOAuthRefreshRequest: HubSpotOAuthRefreshResponse;
  HubSpotOAuthValidateRequest: HubSpotOAuthValidateResponse;
  InstagramLoginOAuthExchangeRequest: InstagramLoginOAuthExchangeResponse;
  InstagramLoginOAuthRefreshRequest: InstagramLoginOAuthRefreshResponse;
  InstagramLoginOAuthValidateRequest: InstagramLoginOAuthValidateResponse;
  IntercomOAuthExchangeRequest: IntercomOAuthExchangeResponse;
  IntercomOAuthRefreshRequest: IntercomOAuthRefreshResponse;
  IntercomOAuthValidateRequest: IntercomOAuthValidateResponse;
  KlaviyoOAuthExchangeRequest: KlaviyoOAuthExchangeResponse;
  KlaviyoOAuthRefreshRequest: KlaviyoOAuthRefreshResponse;
  KlaviyoOAuthValidateRequest: KlaviyoOAuthValidateResponse;
  LinearOAuthExchangeRequest: LinearOAuthExchangeResponse;
  LinearOAuthRefreshRequest: LinearOAuthRefreshResponse;
  LinearOAuthValidateRequest: LinearOAuthValidateResponse;
  LinkedInOAuthExchangeRequest: LinkedInOAuthExchangeResponse;
  LinkedInOAuthRefreshRequest: LinkedInOAuthRefreshResponse;
  LinkedInOAuthValidateRequest: LinkedInOAuthValidateResponse;
  MCPOAuthDiscoverRequest: MCPOAuthDiscoverResponse;
  MCPOAuthExchangeRequest: MCPOAuthExchangeResponse;
  MCPOAuthRegisterClientRequest: MCPOAuthRegisterClientResponse;
  MailchimpOAuthExchangeRequest: MailchimpOAuthExchangeResponse;
  MetaOAuthExchangeRequest: MetaOAuthExchangeResponse;
  MetaOAuthRefreshRequest: MetaOAuthRefreshResponse;
  MetaOAuthValidateRequest: MetaOAuthValidateResponse;
  MicrosoftOAuthExchangeRequest: MicrosoftOAuthExchangeResponse;
  MicrosoftOAuthRefreshRequest: MicrosoftOAuthRefreshResponse;
  MicrosoftOAuthValidateRequest: MicrosoftOAuthValidateResponse;
  MondayOAuthExchangeRequest: MondayOAuthExchangeResponse;
  MondayOAuthRefreshRequest: MondayOAuthRefreshResponse;
  MondayOAuthValidateRequest: MondayOAuthValidateResponse;
  NotionOAuthExchangeRequest: NotionOAuthExchangeResponse;
  NotionOAuthRefreshRequest: NotionOAuthRefreshResponse;
  NotionOAuthValidateRequest: NotionOAuthValidateResponse;
  PagerDutyOAuthExchangeRequest: PagerDutyOAuthExchangeResponse;
  PagerDutyOAuthRefreshRequest: PagerDutyOAuthRefreshResponse;
  PagerDutyOAuthValidateRequest: PagerDutyOAuthValidateResponse;
  ParallelOAuthExchangeRequest: ParallelOAuthExchangeResponse;
  ParallelOAuthValidateRequest: ParallelOAuthValidateResponse;
  PipedriveOAuthExchangeRequest: PipedriveOAuthExchangeResponse;
  PipedriveOAuthRefreshRequest: PipedriveOAuthRefreshResponse;
  PipedriveOAuthValidateRequest: PipedriveOAuthValidateResponse;
  PostHogOAuthExchangeRequest: PostHogOAuthExchangeResponse;
  PostHogOAuthRefreshRequest: PostHogOAuthRefreshResponse;
  PostHogOAuthValidateRequest: PostHogOAuthValidateResponse;
  QuickBooksOAuthExchangeRequest: QuickBooksOAuthExchangeResponse;
  QuickBooksOAuthRefreshRequest: QuickBooksOAuthRefreshResponse;
  QuickBooksOAuthValidateRequest: QuickBooksOAuthValidateResponse;
  RedditOAuthExchangeRequest: RedditOAuthExchangeResponse;
  RedditOAuthRefreshRequest: RedditOAuthRefreshResponse;
  RedditOAuthValidateRequest: RedditOAuthValidateResponse;
  RehearsalRunRequest: RehearsalRunResponse;
  RehearsalScenariosRequest: RehearsalScenariosResponse;
  ResourceCreateRequest: ResourceCreateResponse;
  ResourceDatasetAppendRequest: ResourceDatasetAppendResponse;
  ResourceDatasetDeleteRowsRequest: ResourceDatasetDeleteRowsResponse;
  ResourceDatasetRowsRequest: ResourceDatasetRowsResponse;
  ResourceDatasetUpdateRowRequest: ResourceDatasetUpdateRowResponse;
  ResourceDeleteRequest: ResourceDeleteResponse;
  ResourceDownloadUrlRequest: ResourceDownloadUrlResponse;
  ResourceForkRequest: ResourceForkResponse;
  ResourceGetRequest: ResourceGetResponse;
  ResourceListRequest: ResourceListResponse;
  ResourceUploadUrlRequest: ResourceUploadUrlResponse;
  RunShareCreateRequest: RunShareCreateResponse;
  SalesforceOAuthExchangeRequest: SalesforceOAuthExchangeResponse;
  SalesforceOAuthRefreshRequest: SalesforceOAuthRefreshResponse;
  SalesforceOAuthValidateRequest: SalesforceOAuthValidateResponse;
  SavedOutputCreateRequest: SavedOutputCreateResponse;
  SavedOutputDeleteRequest: SavedOutputDeleteResponse;
  SavedOutputGetRequest: SavedOutputGetResponse;
  SavedOutputListRequest: SavedOutputListResponse;
  SavedOutputUpdateRequest: SavedOutputUpdateResponse;
  SentryOAuthExchangeRequest: SentryOAuthExchangeResponse;
  SentryOAuthRefreshRequest: SentryOAuthRefreshResponse;
  SentryOAuthValidateRequest: SentryOAuthValidateResponse;
  ShareCreateRequest: ShareCreateResponse;
  ShareDeleteRequest: ShareDeleteResponse;
  ShareInviteAcceptRequest: ShareInviteAcceptResponse;
  ShareInviteLinkRequest: ShareInviteLinkResponse;
  ShareLeaveRequest: ShareLeaveResponse;
  ShareListRequest: ShareListResponse;
  ShareListSharedWithMeRequest: ShareListSharedWithMeResponse;
  ShareUpdateRequest: ShareUpdateResponse;
  SharedAgentResumeRequest: SharedAgentResumeResponse;
  ShopifyOAuthExchangeRequest: ShopifyOAuthExchangeResponse;
  ShopifyOAuthRefreshRequest: ShopifyOAuthRefreshResponse;
  ShopifyOAuthValidateRequest: ShopifyOAuthValidateResponse;
  SkillCreateRequest: SkillCreateResponse;
  SkillDeleteRequest: SkillDeleteResponse;
  SkillGetRequest: SkillGetResponse;
  SkillListRequest: SkillListResponse;
  SkillMuteRequest: SkillMuteResponse;
  SkillUpdateRequest: SkillUpdateResponse;
  SkillUpdateWorkflowRequest: SkillUpdateWorkflowResponse;
  SlackOAuthExchangeRequest: SlackOAuthExchangeResponse;
  SlackOAuthRefreshRequest: SlackOAuthRefreshResponse;
  SlackOAuthValidateRequest: SlackOAuthValidateResponse;
  StripeOAuthExchangeRequest: StripeOAuthExchangeResponse;
  StripeOAuthRefreshRequest: StripeOAuthRefreshResponse;
  StripeOAuthValidateRequest: StripeOAuthValidateResponse;
  SupabaseOAuthExchangeRequest: SupabaseOAuthExchangeResponse;
  ThreadsOAuthExchangeRequest: ThreadsOAuthExchangeResponse;
  ThreadsOAuthRefreshRequest: ThreadsOAuthRefreshResponse;
  ThreadsOAuthValidateRequest: ThreadsOAuthValidateResponse;
  TikTokOAuthExchangeRequest: TikTokOAuthExchangeResponse;
  TikTokOAuthRefreshRequest: TikTokOAuthRefreshResponse;
  TikTokOAuthValidateRequest: TikTokOAuthValidateResponse;
  TwitterOAuthExchangeRequest: TwitterOAuthExchangeResponse;
  TwitterOAuthRefreshRequest: TwitterOAuthRefreshResponse;
  TwitterOAuthValidateRequest: TwitterOAuthValidateResponse;
  TypeformOAuthExchangeRequest: TypeformOAuthExchangeResponse;
  WebflowOAuthExchangeRequest: WebflowOAuthExchangeResponse;
  WebflowOAuthRefreshRequest: WebflowOAuthRefreshResponse;
  WebflowOAuthValidateRequest: WebflowOAuthValidateResponse;
  WhatsAppQRStartRequest: WhatsAppQRStartResponse;
  WhatsAppQRStatusRequest: WhatsAppQRStatusResponse;
  WordPressOAuthExchangeRequest: WordPressOAuthExchangeResponse;
  WordPressOAuthRefreshRequest: WordPressOAuthRefreshResponse;
  WordPressOAuthValidateRequest: WordPressOAuthValidateResponse;
  WorkflowCheckpointCreateRequest: WorkflowCheckpointCreateResponse;
  WorkflowCheckpointDeleteRequest: WorkflowCheckpointDeleteResponse;
  WorkflowCheckpointListRequest: WorkflowCheckpointListResponse;
  WorkflowCheckpointRestoreRequest: WorkflowCheckpointRestoreResponse;
  WorkflowCollabTokenRequest: WorkflowCollabTokenResponse;
  WorkflowCreateRequest: WorkflowCreateResponse;
  WorkflowDeleteRequest: WorkflowDeleteResponse;
  WorkflowExecutionCountsRequest: WorkflowExecutionCountsResponse;
  WorkflowExecutionListRequest: WorkflowExecutionListResponse;
  WorkflowGetRequest: WorkflowGetResponse;
  WorkflowListRequest: WorkflowListResponse;
  WorkflowListTrashRequest: WorkflowListTrashResponse;
  WorkflowMCPCreateWorkflowRequest: WorkflowMCPCreateWorkflowResponse;
  WorkflowMCPDeleteWorkflowRequest: WorkflowMCPDeleteWorkflowResponse;
  WorkflowMCPGetNodeConfigRequest: WorkflowMCPGetNodeConfigResponse;
  WorkflowMCPUpdateInterfaceRequest: WorkflowMCPUpdateInterfaceResponse;
  WorkflowMCPUpdateWorkflowMetadataRequest: WorkflowMCPUpdateWorkflowMetadataResponse;
  WorkflowMoveToFolderRequest: WorkflowMoveToFolderResponse;
  WorkflowNodeConfigSchemaRequest: WorkflowNodeConfigSchemaResponse;
  WorkflowNodeLoadOptionsRequest: WorkflowNodeLoadOptionsResponse;
  WorkflowNodeLoadValueRequest: WorkflowNodeLoadValueResponse;
  WorkflowNodeValidateConfigRequest: WorkflowNodeValidateConfigResponse;
  WorkflowPermanentDeleteRequest: WorkflowPermanentDeleteResponse;
  WorkflowRestoreRequest: WorkflowRestoreResponse;
  WorkflowUpdateRequest: WorkflowUpdateResponse;
  ZendeskOAuthExchangeRequest: ZendeskOAuthExchangeResponse;
  ZendeskOAuthRefreshRequest: ZendeskOAuthRefreshResponse;
  ZendeskOAuthValidateRequest: ZendeskOAuthValidateResponse;
  ZoomOAuthExchangeRequest: ZoomOAuthExchangeResponse;
  ZoomOAuthRefreshRequest: ZoomOAuthRefreshResponse;
  ZoomOAuthValidateRequest: ZoomOAuthValidateResponse;
}

// Helper type to infer response type from request
export type InferResponseType<T> = T extends keyof RequestResponseMap ? RequestResponseMap[T] : any;


// Companion objects for each event type (mirrors Python's event_name ClassVar)
// These allow you to access event_name at runtime and create properly typed events

export const ActivityListRequest = {
  event_name: 'activity:list' as const,
  create: (data: ActivityListRequest) => ({ event_name: 'activity:list' as const, ...data })
};
export const AgentBuilderDecisionRequest = {
  event_name: 'agent:builder_decision' as const,
  create: (data: AgentBuilderDecisionRequest) => ({ event_name: 'agent:builder_decision' as const, ...data })
};
export const AgentCopyFromRequest = {
  event_name: 'agent:copy:from' as const,
  create: (data: AgentCopyFromRequest) => ({ event_name: 'agent:copy:from' as const, ...data })
};
export const AgentCopyToRequest = {
  event_name: 'agent:copy:to' as const,
  create: (data: AgentCopyToRequest) => ({ event_name: 'agent:copy:to' as const, ...data })
};
export const AgentEditFileRequest = {
  event_name: 'agent:edit:file' as const,
  create: (data: AgentEditFileRequest) => ({ event_name: 'agent:edit:file' as const, ...data })
};
export const AgentListFilesRequest = {
  event_name: 'agent:list:files' as const,
  create: (data: AgentListFilesRequest) => ({ event_name: 'agent:list:files' as const, ...data })
};
export const AgentPauseRequest = {
  event_name: 'agent:pause' as const,
  create: (data: AgentPauseRequest) => ({ event_name: 'agent:pause' as const, ...data })
};
export const AgentReadFileRequest = {
  event_name: 'agent:read:file' as const,
  create: (data: AgentReadFileRequest) => ({ event_name: 'agent:read:file' as const, ...data })
};
export const AgentRunCommandRequest = {
  event_name: 'agent:run:command' as const,
  create: (data: AgentRunCommandRequest) => ({ event_name: 'agent:run:command' as const, ...data })
};
export const AgentSetCwdRequest = {
  event_name: 'agent:set:cwd' as const,
  create: (data: AgentSetCwdRequest) => ({ event_name: 'agent:set:cwd' as const, ...data })
};
export const AgentShareGetOrCreateRequest = {
  event_name: 'agent_share:get_or_create' as const,
  create: (data: AgentShareGetOrCreateRequest) => ({ event_name: 'agent_share:get_or_create' as const, ...data })
};
export const AgentShareRotateRequest = {
  event_name: 'agent_share:rotate' as const,
  create: (data: AgentShareRotateRequest) => ({ event_name: 'agent_share:rotate' as const, ...data })
};
export const AgentShareSetActiveRequest = {
  event_name: 'agent_share:set_active' as const,
  create: (data: AgentShareSetActiveRequest) => ({ event_name: 'agent_share:set_active' as const, ...data })
};
export const AgentWorkspaceDeleteRequest = {
  event_name: 'agent_workspace:delete' as const,
  create: (data: AgentWorkspaceDeleteRequest) => ({ event_name: 'agent_workspace:delete' as const, ...data })
};
export const AgentWorkspaceListRequest = {
  event_name: 'agent_workspace:list' as const,
  create: (data: AgentWorkspaceListRequest) => ({ event_name: 'agent_workspace:list' as const, ...data })
};
export const AgentWriteFileRequest = {
  event_name: 'agent:write:file' as const,
  create: (data: AgentWriteFileRequest) => ({ event_name: 'agent:write:file' as const, ...data })
};
export const AirtableOAuthExchangeRequest = {
  event_name: 'airtable:oauth:exchange' as const,
  create: (data: AirtableOAuthExchangeRequest) => ({ event_name: 'airtable:oauth:exchange' as const, ...data })
};
export const AirtableOAuthRefreshRequest = {
  event_name: 'airtable:oauth:refresh' as const,
  create: (data: AirtableOAuthRefreshRequest) => ({ event_name: 'airtable:oauth:refresh' as const, ...data })
};
export const AirtableOAuthValidateRequest = {
  event_name: 'airtable:oauth:validate' as const,
  create: (data: AirtableOAuthValidateRequest) => ({ event_name: 'airtable:oauth:validate' as const, ...data })
};
export const ApolloOAuthExchangeRequest = {
  event_name: 'apollo:oauth:exchange' as const,
  create: (data: ApolloOAuthExchangeRequest) => ({ event_name: 'apollo:oauth:exchange' as const, ...data })
};
export const ApolloOAuthRefreshRequest = {
  event_name: 'apollo:oauth:refresh' as const,
  create: (data: ApolloOAuthRefreshRequest) => ({ event_name: 'apollo:oauth:refresh' as const, ...data })
};
export const ApolloOAuthValidateRequest = {
  event_name: 'apollo:oauth:validate' as const,
  create: (data: ApolloOAuthValidateRequest) => ({ event_name: 'apollo:oauth:validate' as const, ...data })
};
export const ApprovalListRequest = {
  event_name: 'approval:list' as const,
  create: (data: ApprovalListRequest) => ({ event_name: 'approval:list' as const, ...data })
};
export const ApprovalRespondRequest = {
  event_name: 'approval:respond' as const,
  create: (data: ApprovalRespondRequest) => ({ event_name: 'approval:respond' as const, ...data })
};
export const AsanaOAuthExchangeRequest = {
  event_name: 'asana:oauth:exchange' as const,
  create: (data: AsanaOAuthExchangeRequest) => ({ event_name: 'asana:oauth:exchange' as const, ...data })
};
export const AsanaOAuthRefreshRequest = {
  event_name: 'asana:oauth:refresh' as const,
  create: (data: AsanaOAuthRefreshRequest) => ({ event_name: 'asana:oauth:refresh' as const, ...data })
};
export const AsanaOAuthValidateRequest = {
  event_name: 'asana:oauth:validate' as const,
  create: (data: AsanaOAuthValidateRequest) => ({ event_name: 'asana:oauth:validate' as const, ...data })
};
export const AtlassianOAuthExchangeRequest = {
  event_name: 'atlassian:oauth:exchange' as const,
  create: (data: AtlassianOAuthExchangeRequest) => ({ event_name: 'atlassian:oauth:exchange' as const, ...data })
};
export const AtlassianOAuthRefreshRequest = {
  event_name: 'atlassian:oauth:refresh' as const,
  create: (data: AtlassianOAuthRefreshRequest) => ({ event_name: 'atlassian:oauth:refresh' as const, ...data })
};
export const AtlassianOAuthValidateRequest = {
  event_name: 'atlassian:oauth:validate' as const,
  create: (data: AtlassianOAuthValidateRequest) => ({ event_name: 'atlassian:oauth:validate' as const, ...data })
};
export const AttioOAuthExchangeRequest = {
  event_name: 'attio:oauth:exchange' as const,
  create: (data: AttioOAuthExchangeRequest) => ({ event_name: 'attio:oauth:exchange' as const, ...data })
};
export const AttioOAuthRefreshRequest = {
  event_name: 'attio:oauth:refresh' as const,
  create: (data: AttioOAuthRefreshRequest) => ({ event_name: 'attio:oauth:refresh' as const, ...data })
};
export const AttioOAuthValidateRequest = {
  event_name: 'attio:oauth:validate' as const,
  create: (data: AttioOAuthValidateRequest) => ({ event_name: 'attio:oauth:validate' as const, ...data })
};
export const BambooHROAuthExchangeRequest = {
  event_name: 'bamboohr:oauth:exchange' as const,
  create: (data: BambooHROAuthExchangeRequest) => ({ event_name: 'bamboohr:oauth:exchange' as const, ...data })
};
export const BambooHROAuthRefreshRequest = {
  event_name: 'bamboohr:oauth:refresh' as const,
  create: (data: BambooHROAuthRefreshRequest) => ({ event_name: 'bamboohr:oauth:refresh' as const, ...data })
};
export const BambooHROAuthValidateRequest = {
  event_name: 'bamboohr:oauth:validate' as const,
  create: (data: BambooHROAuthValidateRequest) => ({ event_name: 'bamboohr:oauth:validate' as const, ...data })
};
export const BoxOAuthExchangeRequest = {
  event_name: 'box:oauth:exchange' as const,
  create: (data: BoxOAuthExchangeRequest) => ({ event_name: 'box:oauth:exchange' as const, ...data })
};
export const BoxOAuthRefreshRequest = {
  event_name: 'box:oauth:refresh' as const,
  create: (data: BoxOAuthRefreshRequest) => ({ event_name: 'box:oauth:refresh' as const, ...data })
};
export const BoxOAuthValidateRequest = {
  event_name: 'box:oauth:validate' as const,
  create: (data: BoxOAuthValidateRequest) => ({ event_name: 'box:oauth:validate' as const, ...data })
};
export const CalComOAuthExchangeRequest = {
  event_name: 'calcom:oauth:exchange' as const,
  create: (data: CalComOAuthExchangeRequest) => ({ event_name: 'calcom:oauth:exchange' as const, ...data })
};
export const CalComOAuthRefreshRequest = {
  event_name: 'calcom:oauth:refresh' as const,
  create: (data: CalComOAuthRefreshRequest) => ({ event_name: 'calcom:oauth:refresh' as const, ...data })
};
export const CalComOAuthValidateRequest = {
  event_name: 'calcom:oauth:validate' as const,
  create: (data: CalComOAuthValidateRequest) => ({ event_name: 'calcom:oauth:validate' as const, ...data })
};
export const CalendlyOAuthExchangeRequest = {
  event_name: 'calendly:oauth:exchange' as const,
  create: (data: CalendlyOAuthExchangeRequest) => ({ event_name: 'calendly:oauth:exchange' as const, ...data })
};
export const CalendlyOAuthRefreshRequest = {
  event_name: 'calendly:oauth:refresh' as const,
  create: (data: CalendlyOAuthRefreshRequest) => ({ event_name: 'calendly:oauth:refresh' as const, ...data })
};
export const CalendlyOAuthValidateRequest = {
  event_name: 'calendly:oauth:validate' as const,
  create: (data: CalendlyOAuthValidateRequest) => ({ event_name: 'calendly:oauth:validate' as const, ...data })
};
export const CanvaOAuthExchangeRequest = {
  event_name: 'canva:oauth:exchange' as const,
  create: (data: CanvaOAuthExchangeRequest) => ({ event_name: 'canva:oauth:exchange' as const, ...data })
};
export const CanvaOAuthRefreshRequest = {
  event_name: 'canva:oauth:refresh' as const,
  create: (data: CanvaOAuthRefreshRequest) => ({ event_name: 'canva:oauth:refresh' as const, ...data })
};
export const CanvaOAuthValidateRequest = {
  event_name: 'canva:oauth:validate' as const,
  create: (data: CanvaOAuthValidateRequest) => ({ event_name: 'canva:oauth:validate' as const, ...data })
};
export const ChatMessageRequest = {
  event_name: 'chat:message' as const,
  create: (data: ChatMessageRequest) => ({ event_name: 'chat:message' as const, ...data })
};
export const ClaudeCodeAuthExchangeRequest = {
  event_name: 'claude-code:auth:exchange' as const,
  create: (data: ClaudeCodeAuthExchangeRequest) => ({ event_name: 'claude-code:auth:exchange' as const, ...data })
};
export const ClaudeCodeAuthStartRequest = {
  event_name: 'claude-code:auth:start' as const,
  create: (data: ClaudeCodeAuthStartRequest) => ({ event_name: 'claude-code:auth:start' as const, ...data })
};
export const ClickUpOAuthExchangeRequest = {
  event_name: 'clickup:oauth:exchange' as const,
  create: (data: ClickUpOAuthExchangeRequest) => ({ event_name: 'clickup:oauth:exchange' as const, ...data })
};
export const ClickUpOAuthRefreshRequest = {
  event_name: 'clickup:oauth:refresh' as const,
  create: (data: ClickUpOAuthRefreshRequest) => ({ event_name: 'clickup:oauth:refresh' as const, ...data })
};
export const ClickUpOAuthValidateRequest = {
  event_name: 'clickup:oauth:validate' as const,
  create: (data: ClickUpOAuthValidateRequest) => ({ event_name: 'clickup:oauth:validate' as const, ...data })
};
export const CloudflareOAuthExchangeRequest = {
  event_name: 'cloudflare:oauth:exchange' as const,
  create: (data: CloudflareOAuthExchangeRequest) => ({ event_name: 'cloudflare:oauth:exchange' as const, ...data })
};
export const CloudflareOAuthRefreshRequest = {
  event_name: 'cloudflare:oauth:refresh' as const,
  create: (data: CloudflareOAuthRefreshRequest) => ({ event_name: 'cloudflare:oauth:refresh' as const, ...data })
};
export const CloudflareOAuthValidateRequest = {
  event_name: 'cloudflare:oauth:validate' as const,
  create: (data: CloudflareOAuthValidateRequest) => ({ event_name: 'cloudflare:oauth:validate' as const, ...data })
};
export const CodexDeviceCodePollRequest = {
  event_name: 'codex:auth:poll' as const,
  create: (data: CodexDeviceCodePollRequest) => ({ event_name: 'codex:auth:poll' as const, ...data })
};
export const CodexDeviceCodeStartRequest = {
  event_name: 'codex:auth:start' as const,
  create: (data: CodexDeviceCodeStartRequest) => ({ event_name: 'codex:auth:start' as const, ...data })
};
export const CredentialAuthorizeForWorkflowRequest = {
  event_name: 'credential:authorize_for_workflow' as const,
  create: (data: CredentialAuthorizeForWorkflowRequest) => ({ event_name: 'credential:authorize_for_workflow' as const, ...data })
};
export const CredentialCreateRequest = {
  event_name: 'credential:create' as const,
  create: (data: CredentialCreateRequest) => ({ event_name: 'credential:create' as const, ...data })
};
export const CredentialDeleteRequest = {
  event_name: 'credential:delete' as const,
  create: (data: CredentialDeleteRequest) => ({ event_name: 'credential:delete' as const, ...data })
};
export const CredentialDisplayInfoRequest = {
  event_name: 'credential:display_info' as const,
  create: (data: CredentialDisplayInfoRequest) => ({ event_name: 'credential:display_info' as const, ...data })
};
export const CredentialGetRequest = {
  event_name: 'credential:get' as const,
  create: (data: CredentialGetRequest) => ({ event_name: 'credential:get' as const, ...data })
};
export const CredentialListRequest = {
  event_name: 'credential:list' as const,
  create: (data: CredentialListRequest) => ({ event_name: 'credential:list' as const, ...data })
};
export const CredentialRequestCancelRequest = {
  event_name: 'credential:request:cancel' as const,
  create: (data: CredentialRequestCancelRequest) => ({ event_name: 'credential:request:cancel' as const, ...data })
};
export const CredentialRequestCreateRequest = {
  event_name: 'credential:request:create' as const,
  create: (data: CredentialRequestCreateRequest) => ({ event_name: 'credential:request:create' as const, ...data })
};
export const CredentialRequestListRequest = {
  event_name: 'credential:request:list' as const,
  create: (data: CredentialRequestListRequest) => ({ event_name: 'credential:request:list' as const, ...data })
};
export const CredentialTestConnectionRequest = {
  event_name: 'credential:test_connection' as const,
  create: (data: CredentialTestConnectionRequest) => ({ event_name: 'credential:test_connection' as const, ...data })
};
export const CredentialUpdateRequest = {
  event_name: 'credential:update' as const,
  create: (data: CredentialUpdateRequest) => ({ event_name: 'credential:update' as const, ...data })
};
export const CredentialValidateAccessRequest = {
  event_name: 'credential:validate_access' as const,
  create: (data: CredentialValidateAccessRequest) => ({ event_name: 'credential:validate_access' as const, ...data })
};
export const DeleteConversationRequest = {
  event_name: 'conversation:delete' as const,
  create: (data: DeleteConversationRequest) => ({ event_name: 'conversation:delete' as const, ...data })
};
export const DiscordOAuthExchangeRequest = {
  event_name: 'discord:oauth:exchange' as const,
  create: (data: DiscordOAuthExchangeRequest) => ({ event_name: 'discord:oauth:exchange' as const, ...data })
};
export const DiscordOAuthRefreshRequest = {
  event_name: 'discord:oauth:refresh' as const,
  create: (data: DiscordOAuthRefreshRequest) => ({ event_name: 'discord:oauth:refresh' as const, ...data })
};
export const DiscordOAuthValidateRequest = {
  event_name: 'discord:oauth:validate' as const,
  create: (data: DiscordOAuthValidateRequest) => ({ event_name: 'discord:oauth:validate' as const, ...data })
};
export const DropboxOAuthExchangeRequest = {
  event_name: 'dropbox:oauth:exchange' as const,
  create: (data: DropboxOAuthExchangeRequest) => ({ event_name: 'dropbox:oauth:exchange' as const, ...data })
};
export const DropboxOAuthRefreshRequest = {
  event_name: 'dropbox:oauth:refresh' as const,
  create: (data: DropboxOAuthRefreshRequest) => ({ event_name: 'dropbox:oauth:refresh' as const, ...data })
};
export const DropboxOAuthValidateRequest = {
  event_name: 'dropbox:oauth:validate' as const,
  create: (data: DropboxOAuthValidateRequest) => ({ event_name: 'dropbox:oauth:validate' as const, ...data })
};
export const FacebookOAuthExchangeRequest = {
  event_name: 'facebook:oauth:exchange' as const,
  create: (data: FacebookOAuthExchangeRequest) => ({ event_name: 'facebook:oauth:exchange' as const, ...data })
};
export const FacebookOAuthRefreshRequest = {
  event_name: 'facebook:oauth:refresh' as const,
  create: (data: FacebookOAuthRefreshRequest) => ({ event_name: 'facebook:oauth:refresh' as const, ...data })
};
export const FacebookOAuthValidateRequest = {
  event_name: 'facebook:oauth:validate' as const,
  create: (data: FacebookOAuthValidateRequest) => ({ event_name: 'facebook:oauth:validate' as const, ...data })
};
export const FacebookPagesOAuthExchangeRequest = {
  event_name: 'facebook_pages:oauth:exchange' as const,
  create: (data: FacebookPagesOAuthExchangeRequest) => ({ event_name: 'facebook_pages:oauth:exchange' as const, ...data })
};
export const FacebookPagesOAuthRefreshRequest = {
  event_name: 'facebook_pages:oauth:refresh' as const,
  create: (data: FacebookPagesOAuthRefreshRequest) => ({ event_name: 'facebook_pages:oauth:refresh' as const, ...data })
};
export const FacebookPagesOAuthValidateRequest = {
  event_name: 'facebook_pages:oauth:validate' as const,
  create: (data: FacebookPagesOAuthValidateRequest) => ({ event_name: 'facebook_pages:oauth:validate' as const, ...data })
};
export const FathomOAuthExchangeRequest = {
  event_name: 'fathom:oauth:exchange' as const,
  create: (data: FathomOAuthExchangeRequest) => ({ event_name: 'fathom:oauth:exchange' as const, ...data })
};
export const FathomOAuthRefreshRequest = {
  event_name: 'fathom:oauth:refresh' as const,
  create: (data: FathomOAuthRefreshRequest) => ({ event_name: 'fathom:oauth:refresh' as const, ...data })
};
export const FathomOAuthValidateRequest = {
  event_name: 'fathom:oauth:validate' as const,
  create: (data: FathomOAuthValidateRequest) => ({ event_name: 'fathom:oauth:validate' as const, ...data })
};
export const FolderCreateRequest = {
  event_name: 'workflow_folder:create' as const,
  create: (data: FolderCreateRequest) => ({ event_name: 'workflow_folder:create' as const, ...data })
};
export const FolderDeleteRequest = {
  event_name: 'workflow_folder:delete' as const,
  create: (data: FolderDeleteRequest) => ({ event_name: 'workflow_folder:delete' as const, ...data })
};
export const FolderGetPathRequest = {
  event_name: 'workflow_folder:get_path' as const,
  create: (data: FolderGetPathRequest) => ({ event_name: 'workflow_folder:get_path' as const, ...data })
};
export const FolderGetRequest = {
  event_name: 'workflow_folder:get' as const,
  create: (data: FolderGetRequest) => ({ event_name: 'workflow_folder:get' as const, ...data })
};
export const FolderGetTreeRequest = {
  event_name: 'workflow_folder:get_tree' as const,
  create: (data: FolderGetTreeRequest) => ({ event_name: 'workflow_folder:get_tree' as const, ...data })
};
export const FolderListRequest = {
  event_name: 'workflow_folder:list' as const,
  create: (data: FolderListRequest) => ({ event_name: 'workflow_folder:list' as const, ...data })
};
export const FolderUpdateRequest = {
  event_name: 'workflow_folder:update' as const,
  create: (data: FolderUpdateRequest) => ({ event_name: 'workflow_folder:update' as const, ...data })
};
export const GetLatestConversationForWorkflowRequest = {
  event_name: 'conversation:get_latest_for_workflow' as const,
  create: (data: GetLatestConversationForWorkflowRequest) => ({ event_name: 'conversation:get_latest_for_workflow' as const, ...data })
};
export const GitLabOAuthExchangeRequest = {
  event_name: 'gitlab:oauth:exchange' as const,
  create: (data: GitLabOAuthExchangeRequest) => ({ event_name: 'gitlab:oauth:exchange' as const, ...data })
};
export const GitLabOAuthRefreshRequest = {
  event_name: 'gitlab:oauth:refresh' as const,
  create: (data: GitLabOAuthRefreshRequest) => ({ event_name: 'gitlab:oauth:refresh' as const, ...data })
};
export const GitLabOAuthValidateRequest = {
  event_name: 'gitlab:oauth:validate' as const,
  create: (data: GitLabOAuthValidateRequest) => ({ event_name: 'gitlab:oauth:validate' as const, ...data })
};
export const GithubOAuthExchangeRequest = {
  event_name: 'github:oauth:exchange' as const,
  create: (data: GithubOAuthExchangeRequest) => ({ event_name: 'github:oauth:exchange' as const, ...data })
};
export const GithubOAuthRefreshRequest = {
  event_name: 'github:oauth:refresh' as const,
  create: (data: GithubOAuthRefreshRequest) => ({ event_name: 'github:oauth:refresh' as const, ...data })
};
export const GithubOAuthValidateRequest = {
  event_name: 'github:oauth:validate' as const,
  create: (data: GithubOAuthValidateRequest) => ({ event_name: 'github:oauth:validate' as const, ...data })
};
export const GoogleOAuthExchangeRequest = {
  event_name: 'google:oauth:exchange' as const,
  create: (data: GoogleOAuthExchangeRequest) => ({ event_name: 'google:oauth:exchange' as const, ...data })
};
export const GoogleOAuthRefreshRequest = {
  event_name: 'google:oauth:refresh' as const,
  create: (data: GoogleOAuthRefreshRequest) => ({ event_name: 'google:oauth:refresh' as const, ...data })
};
export const GoogleOAuthValidateRequest = {
  event_name: 'google:oauth:validate' as const,
  create: (data: GoogleOAuthValidateRequest) => ({ event_name: 'google:oauth:validate' as const, ...data })
};
export const HubSpotOAuthExchangeRequest = {
  event_name: 'hubspot:oauth:exchange' as const,
  create: (data: HubSpotOAuthExchangeRequest) => ({ event_name: 'hubspot:oauth:exchange' as const, ...data })
};
export const HubSpotOAuthRefreshRequest = {
  event_name: 'hubspot:oauth:refresh' as const,
  create: (data: HubSpotOAuthRefreshRequest) => ({ event_name: 'hubspot:oauth:refresh' as const, ...data })
};
export const HubSpotOAuthValidateRequest = {
  event_name: 'hubspot:oauth:validate' as const,
  create: (data: HubSpotOAuthValidateRequest) => ({ event_name: 'hubspot:oauth:validate' as const, ...data })
};
export const InstagramLoginOAuthExchangeRequest = {
  event_name: 'instagram_login:oauth:exchange' as const,
  create: (data: InstagramLoginOAuthExchangeRequest) => ({ event_name: 'instagram_login:oauth:exchange' as const, ...data })
};
export const InstagramLoginOAuthRefreshRequest = {
  event_name: 'instagram_login:oauth:refresh' as const,
  create: (data: InstagramLoginOAuthRefreshRequest) => ({ event_name: 'instagram_login:oauth:refresh' as const, ...data })
};
export const InstagramLoginOAuthValidateRequest = {
  event_name: 'instagram_login:oauth:validate' as const,
  create: (data: InstagramLoginOAuthValidateRequest) => ({ event_name: 'instagram_login:oauth:validate' as const, ...data })
};
export const InstanceKeysDeleteRequest = {
  event_name: 'instance_keys:delete' as const,
  create: (data: InstanceKeysDeleteRequest) => ({ event_name: 'instance_keys:delete' as const, ...data })
};
export const InstanceKeysListRequest = {
  event_name: 'instance_keys:list' as const,
  create: (data: InstanceKeysListRequest) => ({ event_name: 'instance_keys:list' as const, ...data })
};
export const InstanceKeysSetRequest = {
  event_name: 'instance_keys:set' as const,
  create: (data: InstanceKeysSetRequest) => ({ event_name: 'instance_keys:set' as const, ...data })
};
export const InstanceOAuthDeleteRequest = {
  event_name: 'instance_oauth:delete' as const,
  create: (data: InstanceOAuthDeleteRequest) => ({ event_name: 'instance_oauth:delete' as const, ...data })
};
export const InstanceOAuthListRequest = {
  event_name: 'instance_oauth:list' as const,
  create: (data: InstanceOAuthListRequest) => ({ event_name: 'instance_oauth:list' as const, ...data })
};
export const InstanceOAuthSetRequest = {
  event_name: 'instance_oauth:set' as const,
  create: (data: InstanceOAuthSetRequest) => ({ event_name: 'instance_oauth:set' as const, ...data })
};
export const IntercomOAuthExchangeRequest = {
  event_name: 'intercom:oauth:exchange' as const,
  create: (data: IntercomOAuthExchangeRequest) => ({ event_name: 'intercom:oauth:exchange' as const, ...data })
};
export const IntercomOAuthRefreshRequest = {
  event_name: 'intercom:oauth:refresh' as const,
  create: (data: IntercomOAuthRefreshRequest) => ({ event_name: 'intercom:oauth:refresh' as const, ...data })
};
export const IntercomOAuthValidateRequest = {
  event_name: 'intercom:oauth:validate' as const,
  create: (data: IntercomOAuthValidateRequest) => ({ event_name: 'intercom:oauth:validate' as const, ...data })
};
export const KlaviyoOAuthExchangeRequest = {
  event_name: 'klaviyo:oauth:exchange' as const,
  create: (data: KlaviyoOAuthExchangeRequest) => ({ event_name: 'klaviyo:oauth:exchange' as const, ...data })
};
export const KlaviyoOAuthRefreshRequest = {
  event_name: 'klaviyo:oauth:refresh' as const,
  create: (data: KlaviyoOAuthRefreshRequest) => ({ event_name: 'klaviyo:oauth:refresh' as const, ...data })
};
export const KlaviyoOAuthValidateRequest = {
  event_name: 'klaviyo:oauth:validate' as const,
  create: (data: KlaviyoOAuthValidateRequest) => ({ event_name: 'klaviyo:oauth:validate' as const, ...data })
};
export const LinearOAuthExchangeRequest = {
  event_name: 'linear:oauth:exchange' as const,
  create: (data: LinearOAuthExchangeRequest) => ({ event_name: 'linear:oauth:exchange' as const, ...data })
};
export const LinearOAuthRefreshRequest = {
  event_name: 'linear:oauth:refresh' as const,
  create: (data: LinearOAuthRefreshRequest) => ({ event_name: 'linear:oauth:refresh' as const, ...data })
};
export const LinearOAuthValidateRequest = {
  event_name: 'linear:oauth:validate' as const,
  create: (data: LinearOAuthValidateRequest) => ({ event_name: 'linear:oauth:validate' as const, ...data })
};
export const LinkedInOAuthExchangeRequest = {
  event_name: 'linkedin:oauth:exchange' as const,
  create: (data: LinkedInOAuthExchangeRequest) => ({ event_name: 'linkedin:oauth:exchange' as const, ...data })
};
export const LinkedInOAuthRefreshRequest = {
  event_name: 'linkedin:oauth:refresh' as const,
  create: (data: LinkedInOAuthRefreshRequest) => ({ event_name: 'linkedin:oauth:refresh' as const, ...data })
};
export const LinkedInOAuthValidateRequest = {
  event_name: 'linkedin:oauth:validate' as const,
  create: (data: LinkedInOAuthValidateRequest) => ({ event_name: 'linkedin:oauth:validate' as const, ...data })
};
export const ListConversationsForAgentRequest = {
  event_name: 'conversation:list_for_agent' as const,
  create: (data: ListConversationsForAgentRequest) => ({ event_name: 'conversation:list_for_agent' as const, ...data })
};
export const ListConversationsRequest = {
  event_name: 'conversations:list' as const,
  create: (data: ListConversationsRequest) => ({ event_name: 'conversations:list' as const, ...data })
};
export const ListPendingBuilderRunsRequest = {
  event_name: 'workflow:builder:list_pending' as const,
  create: (data: ListPendingBuilderRunsRequest) => ({ event_name: 'workflow:builder:list_pending' as const, ...data })
};
export const MCPFolderGetTreeRequest = {
  event_name: 'workflow:mcp:get_folder_tree' as const,
  create: (data: MCPFolderGetTreeRequest) => ({ event_name: 'workflow:mcp:get_folder_tree' as const, ...data })
};
export const MCPOAuthDiscoverRequest = {
  event_name: 'mcp:oauth:discover' as const,
  create: (data: MCPOAuthDiscoverRequest) => ({ event_name: 'mcp:oauth:discover' as const, ...data })
};
export const MCPOAuthExchangeRequest = {
  event_name: 'mcp:oauth:exchange' as const,
  create: (data: MCPOAuthExchangeRequest) => ({ event_name: 'mcp:oauth:exchange' as const, ...data })
};
export const MCPOAuthRegisterClientRequest = {
  event_name: 'mcp:oauth:register-client' as const,
  create: (data: MCPOAuthRegisterClientRequest) => ({ event_name: 'mcp:oauth:register-client' as const, ...data })
};
export const MailchimpOAuthExchangeRequest = {
  event_name: 'mailchimp:oauth:exchange' as const,
  create: (data: MailchimpOAuthExchangeRequest) => ({ event_name: 'mailchimp:oauth:exchange' as const, ...data })
};
export const MetaOAuthExchangeRequest = {
  event_name: 'meta:oauth:exchange' as const,
  create: (data: MetaOAuthExchangeRequest) => ({ event_name: 'meta:oauth:exchange' as const, ...data })
};
export const MetaOAuthRefreshRequest = {
  event_name: 'meta:oauth:refresh' as const,
  create: (data: MetaOAuthRefreshRequest) => ({ event_name: 'meta:oauth:refresh' as const, ...data })
};
export const MetaOAuthValidateRequest = {
  event_name: 'meta:oauth:validate' as const,
  create: (data: MetaOAuthValidateRequest) => ({ event_name: 'meta:oauth:validate' as const, ...data })
};
export const MicrosoftOAuthExchangeRequest = {
  event_name: 'microsoft:oauth:exchange' as const,
  create: (data: MicrosoftOAuthExchangeRequest) => ({ event_name: 'microsoft:oauth:exchange' as const, ...data })
};
export const MicrosoftOAuthRefreshRequest = {
  event_name: 'microsoft:oauth:refresh' as const,
  create: (data: MicrosoftOAuthRefreshRequest) => ({ event_name: 'microsoft:oauth:refresh' as const, ...data })
};
export const MicrosoftOAuthValidateRequest = {
  event_name: 'microsoft:oauth:validate' as const,
  create: (data: MicrosoftOAuthValidateRequest) => ({ event_name: 'microsoft:oauth:validate' as const, ...data })
};
export const MondayOAuthExchangeRequest = {
  event_name: 'monday:oauth:exchange' as const,
  create: (data: MondayOAuthExchangeRequest) => ({ event_name: 'monday:oauth:exchange' as const, ...data })
};
export const MondayOAuthRefreshRequest = {
  event_name: 'monday:oauth:refresh' as const,
  create: (data: MondayOAuthRefreshRequest) => ({ event_name: 'monday:oauth:refresh' as const, ...data })
};
export const MondayOAuthValidateRequest = {
  event_name: 'monday:oauth:validate' as const,
  create: (data: MondayOAuthValidateRequest) => ({ event_name: 'monday:oauth:validate' as const, ...data })
};
export const NodeOutputSchemaRequest = {
  event_name: 'workflow:node:schema' as const,
  create: (data: NodeOutputSchemaRequest) => ({ event_name: 'workflow:node:schema' as const, ...data })
};
export const NotificationPrefsGetRequest = {
  event_name: 'notifications:prefs:get' as const,
  create: (data: NotificationPrefsGetRequest) => ({ event_name: 'notifications:prefs:get' as const, ...data })
};
export const NotificationPrefsUpdateRequest = {
  event_name: 'notifications:prefs:update' as const,
  create: (data: NotificationPrefsUpdateRequest) => ({ event_name: 'notifications:prefs:update' as const, ...data })
};
export const NotionOAuthExchangeRequest = {
  event_name: 'notion:oauth:exchange' as const,
  create: (data: NotionOAuthExchangeRequest) => ({ event_name: 'notion:oauth:exchange' as const, ...data })
};
export const NotionOAuthRefreshRequest = {
  event_name: 'notion:oauth:refresh' as const,
  create: (data: NotionOAuthRefreshRequest) => ({ event_name: 'notion:oauth:refresh' as const, ...data })
};
export const NotionOAuthValidateRequest = {
  event_name: 'notion:oauth:validate' as const,
  create: (data: NotionOAuthValidateRequest) => ({ event_name: 'notion:oauth:validate' as const, ...data })
};
export const OnboardingCompletionGetRequest = {
  event_name: 'onboarding:completion:get' as const,
  create: (data: OnboardingCompletionGetRequest) => ({ event_name: 'onboarding:completion:get' as const, ...data })
};
export const OnboardingCompletionUpdateRequest = {
  event_name: 'onboarding:completion:update' as const,
  create: (data: OnboardingCompletionUpdateRequest) => ({ event_name: 'onboarding:completion:update' as const, ...data })
};
export const OnboardingSkipRequest = {
  event_name: 'onboarding:skip' as const,
  create: (data: OnboardingSkipRequest) => ({ event_name: 'onboarding:skip' as const, ...data })
};
export const OnboardingSubmitRequest = {
  event_name: 'onboarding:submit' as const,
  create: (data: OnboardingSubmitRequest) => ({ event_name: 'onboarding:submit' as const, ...data })
};
export const PagerDutyOAuthExchangeRequest = {
  event_name: 'pagerduty:oauth:exchange' as const,
  create: (data: PagerDutyOAuthExchangeRequest) => ({ event_name: 'pagerduty:oauth:exchange' as const, ...data })
};
export const PagerDutyOAuthRefreshRequest = {
  event_name: 'pagerduty:oauth:refresh' as const,
  create: (data: PagerDutyOAuthRefreshRequest) => ({ event_name: 'pagerduty:oauth:refresh' as const, ...data })
};
export const PagerDutyOAuthValidateRequest = {
  event_name: 'pagerduty:oauth:validate' as const,
  create: (data: PagerDutyOAuthValidateRequest) => ({ event_name: 'pagerduty:oauth:validate' as const, ...data })
};
export const ParallelOAuthExchangeRequest = {
  event_name: 'parallel:oauth:exchange' as const,
  create: (data: ParallelOAuthExchangeRequest) => ({ event_name: 'parallel:oauth:exchange' as const, ...data })
};
export const ParallelOAuthValidateRequest = {
  event_name: 'parallel:oauth:validate' as const,
  create: (data: ParallelOAuthValidateRequest) => ({ event_name: 'parallel:oauth:validate' as const, ...data })
};
export const PipedriveOAuthExchangeRequest = {
  event_name: 'pipedrive:oauth:exchange' as const,
  create: (data: PipedriveOAuthExchangeRequest) => ({ event_name: 'pipedrive:oauth:exchange' as const, ...data })
};
export const PipedriveOAuthRefreshRequest = {
  event_name: 'pipedrive:oauth:refresh' as const,
  create: (data: PipedriveOAuthRefreshRequest) => ({ event_name: 'pipedrive:oauth:refresh' as const, ...data })
};
export const PipedriveOAuthValidateRequest = {
  event_name: 'pipedrive:oauth:validate' as const,
  create: (data: PipedriveOAuthValidateRequest) => ({ event_name: 'pipedrive:oauth:validate' as const, ...data })
};
export const PostHogOAuthExchangeRequest = {
  event_name: 'posthog:oauth:exchange' as const,
  create: (data: PostHogOAuthExchangeRequest) => ({ event_name: 'posthog:oauth:exchange' as const, ...data })
};
export const PostHogOAuthRefreshRequest = {
  event_name: 'posthog:oauth:refresh' as const,
  create: (data: PostHogOAuthRefreshRequest) => ({ event_name: 'posthog:oauth:refresh' as const, ...data })
};
export const PostHogOAuthValidateRequest = {
  event_name: 'posthog:oauth:validate' as const,
  create: (data: PostHogOAuthValidateRequest) => ({ event_name: 'posthog:oauth:validate' as const, ...data })
};
export const QuickBooksOAuthExchangeRequest = {
  event_name: 'quickbooks:oauth:exchange' as const,
  create: (data: QuickBooksOAuthExchangeRequest) => ({ event_name: 'quickbooks:oauth:exchange' as const, ...data })
};
export const QuickBooksOAuthRefreshRequest = {
  event_name: 'quickbooks:oauth:refresh' as const,
  create: (data: QuickBooksOAuthRefreshRequest) => ({ event_name: 'quickbooks:oauth:refresh' as const, ...data })
};
export const QuickBooksOAuthValidateRequest = {
  event_name: 'quickbooks:oauth:validate' as const,
  create: (data: QuickBooksOAuthValidateRequest) => ({ event_name: 'quickbooks:oauth:validate' as const, ...data })
};
export const RedditOAuthExchangeRequest = {
  event_name: 'reddit:oauth:exchange' as const,
  create: (data: RedditOAuthExchangeRequest) => ({ event_name: 'reddit:oauth:exchange' as const, ...data })
};
export const RedditOAuthRefreshRequest = {
  event_name: 'reddit:oauth:refresh' as const,
  create: (data: RedditOAuthRefreshRequest) => ({ event_name: 'reddit:oauth:refresh' as const, ...data })
};
export const RedditOAuthValidateRequest = {
  event_name: 'reddit:oauth:validate' as const,
  create: (data: RedditOAuthValidateRequest) => ({ event_name: 'reddit:oauth:validate' as const, ...data })
};
export const RehearsalRunRequest = {
  event_name: 'rehearsal:run' as const,
  create: (data: RehearsalRunRequest) => ({ event_name: 'rehearsal:run' as const, ...data })
};
export const RehearsalScenariosRequest = {
  event_name: 'rehearsal:scenarios' as const,
  create: (data: RehearsalScenariosRequest) => ({ event_name: 'rehearsal:scenarios' as const, ...data })
};
export const ResourceCreateRequest = {
  event_name: 'resource:create' as const,
  create: (data: ResourceCreateRequest) => ({ event_name: 'resource:create' as const, ...data })
};
export const ResourceDatasetAppendRequest = {
  event_name: 'resource:dataset:append' as const,
  create: (data: ResourceDatasetAppendRequest) => ({ event_name: 'resource:dataset:append' as const, ...data })
};
export const ResourceDatasetDeleteRowsRequest = {
  event_name: 'resource:dataset:delete_rows' as const,
  create: (data: ResourceDatasetDeleteRowsRequest) => ({ event_name: 'resource:dataset:delete_rows' as const, ...data })
};
export const ResourceDatasetRowsRequest = {
  event_name: 'resource:dataset:rows' as const,
  create: (data: ResourceDatasetRowsRequest) => ({ event_name: 'resource:dataset:rows' as const, ...data })
};
export const ResourceDatasetUpdateRowRequest = {
  event_name: 'resource:dataset:update_row' as const,
  create: (data: ResourceDatasetUpdateRowRequest) => ({ event_name: 'resource:dataset:update_row' as const, ...data })
};
export const ResourceDeleteRequest = {
  event_name: 'resource:delete' as const,
  create: (data: ResourceDeleteRequest) => ({ event_name: 'resource:delete' as const, ...data })
};
export const ResourceDownloadUrlRequest = {
  event_name: 'resource:download_url' as const,
  create: (data: ResourceDownloadUrlRequest) => ({ event_name: 'resource:download_url' as const, ...data })
};
export const ResourceForkRequest = {
  event_name: 'resource:fork' as const,
  create: (data: ResourceForkRequest) => ({ event_name: 'resource:fork' as const, ...data })
};
export const ResourceGetRequest = {
  event_name: 'resource:get' as const,
  create: (data: ResourceGetRequest) => ({ event_name: 'resource:get' as const, ...data })
};
export const ResourceListRequest = {
  event_name: 'resource:list' as const,
  create: (data: ResourceListRequest) => ({ event_name: 'resource:list' as const, ...data })
};
export const ResourceUploadUrlRequest = {
  event_name: 'resource:upload_url' as const,
  create: (data: ResourceUploadUrlRequest) => ({ event_name: 'resource:upload_url' as const, ...data })
};
export const ResumeConversationRequest = {
  event_name: 'conversation:resume' as const,
  create: (data: ResumeConversationRequest) => ({ event_name: 'conversation:resume' as const, ...data })
};
export const RunShareCreateRequest = {
  event_name: 'run_share:create' as const,
  create: (data: RunShareCreateRequest) => ({ event_name: 'run_share:create' as const, ...data })
};
export const SalesforceOAuthExchangeRequest = {
  event_name: 'salesforce:oauth:exchange' as const,
  create: (data: SalesforceOAuthExchangeRequest) => ({ event_name: 'salesforce:oauth:exchange' as const, ...data })
};
export const SalesforceOAuthRefreshRequest = {
  event_name: 'salesforce:oauth:refresh' as const,
  create: (data: SalesforceOAuthRefreshRequest) => ({ event_name: 'salesforce:oauth:refresh' as const, ...data })
};
export const SalesforceOAuthValidateRequest = {
  event_name: 'salesforce:oauth:validate' as const,
  create: (data: SalesforceOAuthValidateRequest) => ({ event_name: 'salesforce:oauth:validate' as const, ...data })
};
export const SavedOutputCreateRequest = {
  event_name: 'saved_output:create' as const,
  create: (data: SavedOutputCreateRequest) => ({ event_name: 'saved_output:create' as const, ...data })
};
export const SavedOutputDeleteRequest = {
  event_name: 'saved_output:delete' as const,
  create: (data: SavedOutputDeleteRequest) => ({ event_name: 'saved_output:delete' as const, ...data })
};
export const SavedOutputGetRequest = {
  event_name: 'saved_output:get' as const,
  create: (data: SavedOutputGetRequest) => ({ event_name: 'saved_output:get' as const, ...data })
};
export const SavedOutputListRequest = {
  event_name: 'saved_output:list' as const,
  create: (data: SavedOutputListRequest) => ({ event_name: 'saved_output:list' as const, ...data })
};
export const SavedOutputUpdateRequest = {
  event_name: 'saved_output:update' as const,
  create: (data: SavedOutputUpdateRequest) => ({ event_name: 'saved_output:update' as const, ...data })
};
export const SentryOAuthExchangeRequest = {
  event_name: 'sentry:oauth:exchange' as const,
  create: (data: SentryOAuthExchangeRequest) => ({ event_name: 'sentry:oauth:exchange' as const, ...data })
};
export const SentryOAuthRefreshRequest = {
  event_name: 'sentry:oauth:refresh' as const,
  create: (data: SentryOAuthRefreshRequest) => ({ event_name: 'sentry:oauth:refresh' as const, ...data })
};
export const SentryOAuthValidateRequest = {
  event_name: 'sentry:oauth:validate' as const,
  create: (data: SentryOAuthValidateRequest) => ({ event_name: 'sentry:oauth:validate' as const, ...data })
};
export const ShareBuilderAskRequest = {
  event_name: 'workflow:builder:share_ask' as const,
  create: (data: ShareBuilderAskRequest) => ({ event_name: 'workflow:builder:share_ask' as const, ...data })
};
export const ShareCreateRequest = {
  event_name: 'share:create' as const,
  create: (data: ShareCreateRequest) => ({ event_name: 'share:create' as const, ...data })
};
export const ShareDeleteRequest = {
  event_name: 'share:delete' as const,
  create: (data: ShareDeleteRequest) => ({ event_name: 'share:delete' as const, ...data })
};
export const ShareInviteAcceptRequest = {
  event_name: 'share:invite_accept' as const,
  create: (data: ShareInviteAcceptRequest) => ({ event_name: 'share:invite_accept' as const, ...data })
};
export const ShareInviteLinkRequest = {
  event_name: 'share:invite_link' as const,
  create: (data: ShareInviteLinkRequest) => ({ event_name: 'share:invite_link' as const, ...data })
};
export const ShareLeaveRequest = {
  event_name: 'share:leave' as const,
  create: (data: ShareLeaveRequest) => ({ event_name: 'share:leave' as const, ...data })
};
export const ShareListRequest = {
  event_name: 'share:list' as const,
  create: (data: ShareListRequest) => ({ event_name: 'share:list' as const, ...data })
};
export const ShareListSharedWithMeRequest = {
  event_name: 'share:list_shared_with_me' as const,
  create: (data: ShareListSharedWithMeRequest) => ({ event_name: 'share:list_shared_with_me' as const, ...data })
};
export const ShareUpdateRequest = {
  event_name: 'share:update' as const,
  create: (data: ShareUpdateRequest) => ({ event_name: 'share:update' as const, ...data })
};
export const SharedAgentResumeRequest = {
  event_name: 'shared_agent:resume' as const,
  create: (data: SharedAgentResumeRequest) => ({ event_name: 'shared_agent:resume' as const, ...data })
};
export const SharedAgentSendRequest = {
  event_name: 'shared_agent:send' as const,
  create: (data: SharedAgentSendRequest) => ({ event_name: 'shared_agent:send' as const, ...data })
};
export const ShopifyOAuthExchangeRequest = {
  event_name: 'shopify:oauth:exchange' as const,
  create: (data: ShopifyOAuthExchangeRequest) => ({ event_name: 'shopify:oauth:exchange' as const, ...data })
};
export const ShopifyOAuthRefreshRequest = {
  event_name: 'shopify:oauth:refresh' as const,
  create: (data: ShopifyOAuthRefreshRequest) => ({ event_name: 'shopify:oauth:refresh' as const, ...data })
};
export const ShopifyOAuthValidateRequest = {
  event_name: 'shopify:oauth:validate' as const,
  create: (data: ShopifyOAuthValidateRequest) => ({ event_name: 'shopify:oauth:validate' as const, ...data })
};
export const SkillCreateRequest = {
  event_name: 'skill:create' as const,
  create: (data: SkillCreateRequest) => ({ event_name: 'skill:create' as const, ...data })
};
export const SkillDeleteRequest = {
  event_name: 'skill:delete' as const,
  create: (data: SkillDeleteRequest) => ({ event_name: 'skill:delete' as const, ...data })
};
export const SkillGetRequest = {
  event_name: 'skill:get' as const,
  create: (data: SkillGetRequest) => ({ event_name: 'skill:get' as const, ...data })
};
export const SkillGetWorkflowRequest = {
  event_name: 'skill:get_workflow' as const,
  create: (data: SkillGetWorkflowRequest) => ({ event_name: 'skill:get_workflow' as const, ...data })
};
export const SkillListRequest = {
  event_name: 'skill:list' as const,
  create: (data: SkillListRequest) => ({ event_name: 'skill:list' as const, ...data })
};
export const SkillMuteRequest = {
  event_name: 'skill:mute' as const,
  create: (data: SkillMuteRequest) => ({ event_name: 'skill:mute' as const, ...data })
};
export const SkillUpdateRequest = {
  event_name: 'skill:update' as const,
  create: (data: SkillUpdateRequest) => ({ event_name: 'skill:update' as const, ...data })
};
export const SkillUpdateWorkflowRequest = {
  event_name: 'skill:update_workflow' as const,
  create: (data: SkillUpdateWorkflowRequest) => ({ event_name: 'skill:update_workflow' as const, ...data })
};
export const SlackOAuthExchangeRequest = {
  event_name: 'slack:oauth:exchange' as const,
  create: (data: SlackOAuthExchangeRequest) => ({ event_name: 'slack:oauth:exchange' as const, ...data })
};
export const SlackOAuthRefreshRequest = {
  event_name: 'slack:oauth:refresh' as const,
  create: (data: SlackOAuthRefreshRequest) => ({ event_name: 'slack:oauth:refresh' as const, ...data })
};
export const SlackOAuthValidateRequest = {
  event_name: 'slack:oauth:validate' as const,
  create: (data: SlackOAuthValidateRequest) => ({ event_name: 'slack:oauth:validate' as const, ...data })
};
export const StripeOAuthExchangeRequest = {
  event_name: 'stripe:oauth:exchange' as const,
  create: (data: StripeOAuthExchangeRequest) => ({ event_name: 'stripe:oauth:exchange' as const, ...data })
};
export const StripeOAuthRefreshRequest = {
  event_name: 'stripe:oauth:refresh' as const,
  create: (data: StripeOAuthRefreshRequest) => ({ event_name: 'stripe:oauth:refresh' as const, ...data })
};
export const StripeOAuthValidateRequest = {
  event_name: 'stripe:oauth:validate' as const,
  create: (data: StripeOAuthValidateRequest) => ({ event_name: 'stripe:oauth:validate' as const, ...data })
};
export const SubmitFeedbackRequest = {
  event_name: 'feedback:submit' as const,
  create: (data: SubmitFeedbackRequest) => ({ event_name: 'feedback:submit' as const, ...data })
};
export const SupabaseOAuthExchangeRequest = {
  event_name: 'supabase:oauth:exchange' as const,
  create: (data: SupabaseOAuthExchangeRequest) => ({ event_name: 'supabase:oauth:exchange' as const, ...data })
};
export const SupabaseOAuthRefreshRequest = {
  event_name: 'supabase:oauth:refresh' as const,
  create: (data: SupabaseOAuthRefreshRequest) => ({ event_name: 'supabase:oauth:refresh' as const, ...data })
};
export const SupabaseOAuthSelectProjectRequest = {
  event_name: 'supabase:oauth:select_project' as const,
  create: (data: SupabaseOAuthSelectProjectRequest) => ({ event_name: 'supabase:oauth:select_project' as const, ...data })
};
export const SupabaseOAuthValidateRequest = {
  event_name: 'supabase:oauth:validate' as const,
  create: (data: SupabaseOAuthValidateRequest) => ({ event_name: 'supabase:oauth:validate' as const, ...data })
};
export const ThreadsOAuthExchangeRequest = {
  event_name: 'threads:oauth:exchange' as const,
  create: (data: ThreadsOAuthExchangeRequest) => ({ event_name: 'threads:oauth:exchange' as const, ...data })
};
export const ThreadsOAuthRefreshRequest = {
  event_name: 'threads:oauth:refresh' as const,
  create: (data: ThreadsOAuthRefreshRequest) => ({ event_name: 'threads:oauth:refresh' as const, ...data })
};
export const ThreadsOAuthValidateRequest = {
  event_name: 'threads:oauth:validate' as const,
  create: (data: ThreadsOAuthValidateRequest) => ({ event_name: 'threads:oauth:validate' as const, ...data })
};
export const TikTokOAuthExchangeRequest = {
  event_name: 'tiktok:oauth:exchange' as const,
  create: (data: TikTokOAuthExchangeRequest) => ({ event_name: 'tiktok:oauth:exchange' as const, ...data })
};
export const TikTokOAuthRefreshRequest = {
  event_name: 'tiktok:oauth:refresh' as const,
  create: (data: TikTokOAuthRefreshRequest) => ({ event_name: 'tiktok:oauth:refresh' as const, ...data })
};
export const TikTokOAuthValidateRequest = {
  event_name: 'tiktok:oauth:validate' as const,
  create: (data: TikTokOAuthValidateRequest) => ({ event_name: 'tiktok:oauth:validate' as const, ...data })
};
export const ToolCallListRequest = {
  event_name: 'tool_calls:list' as const,
  create: (data: ToolCallListRequest) => ({ event_name: 'tool_calls:list' as const, ...data })
};
export const TwitterOAuthExchangeRequest = {
  event_name: 'twitter:oauth:exchange' as const,
  create: (data: TwitterOAuthExchangeRequest) => ({ event_name: 'twitter:oauth:exchange' as const, ...data })
};
export const TwitterOAuthRefreshRequest = {
  event_name: 'twitter:oauth:refresh' as const,
  create: (data: TwitterOAuthRefreshRequest) => ({ event_name: 'twitter:oauth:refresh' as const, ...data })
};
export const TwitterOAuthValidateRequest = {
  event_name: 'twitter:oauth:validate' as const,
  create: (data: TwitterOAuthValidateRequest) => ({ event_name: 'twitter:oauth:validate' as const, ...data })
};
export const TypeformOAuthExchangeRequest = {
  event_name: 'typeform:oauth:exchange' as const,
  create: (data: TypeformOAuthExchangeRequest) => ({ event_name: 'typeform:oauth:exchange' as const, ...data })
};
export const UpdateAuthRequest = {
  event_name: 'update_auth' as const,
  create: (data: UpdateAuthRequest) => ({ event_name: 'update_auth' as const, ...data })
};
export const UsageDataRequest = {
  event_name: 'usage:data' as const,
  create: (data: UsageDataRequest) => ({ event_name: 'usage:data' as const, ...data })
};
export const UsageLogsRequest = {
  event_name: 'usage:logs' as const,
  create: (data: UsageLogsRequest) => ({ event_name: 'usage:logs' as const, ...data })
};
export const WebflowOAuthExchangeRequest = {
  event_name: 'webflow:oauth:exchange' as const,
  create: (data: WebflowOAuthExchangeRequest) => ({ event_name: 'webflow:oauth:exchange' as const, ...data })
};
export const WebflowOAuthRefreshRequest = {
  event_name: 'webflow:oauth:refresh' as const,
  create: (data: WebflowOAuthRefreshRequest) => ({ event_name: 'webflow:oauth:refresh' as const, ...data })
};
export const WebflowOAuthValidateRequest = {
  event_name: 'webflow:oauth:validate' as const,
  create: (data: WebflowOAuthValidateRequest) => ({ event_name: 'webflow:oauth:validate' as const, ...data })
};
export const WhatsAppQRStartRequest = {
  event_name: 'whatsapp:qr:start' as const,
  create: (data: WhatsAppQRStartRequest) => ({ event_name: 'whatsapp:qr:start' as const, ...data })
};
export const WhatsAppQRStatusRequest = {
  event_name: 'whatsapp:qr:status' as const,
  create: (data: WhatsAppQRStatusRequest) => ({ event_name: 'whatsapp:qr:status' as const, ...data })
};
export const WordPressOAuthExchangeRequest = {
  event_name: 'wordpress:oauth:exchange' as const,
  create: (data: WordPressOAuthExchangeRequest) => ({ event_name: 'wordpress:oauth:exchange' as const, ...data })
};
export const WordPressOAuthRefreshRequest = {
  event_name: 'wordpress:oauth:refresh' as const,
  create: (data: WordPressOAuthRefreshRequest) => ({ event_name: 'wordpress:oauth:refresh' as const, ...data })
};
export const WordPressOAuthValidateRequest = {
  event_name: 'wordpress:oauth:validate' as const,
  create: (data: WordPressOAuthValidateRequest) => ({ event_name: 'wordpress:oauth:validate' as const, ...data })
};
export const WorkflowAutofillRequest = {
  event_name: 'workflow:builder:autofill' as const,
  create: (data: WorkflowAutofillRequest) => ({ event_name: 'workflow:builder:autofill' as const, ...data })
};
export const WorkflowBuilderEditRequest = {
  event_name: 'workflow:builder:edit' as const,
  create: (data: WorkflowBuilderEditRequest) => ({ event_name: 'workflow:builder:edit' as const, ...data })
};
export const WorkflowCheckpointCreateRequest = {
  event_name: 'workflow:checkpoint:create' as const,
  create: (data: WorkflowCheckpointCreateRequest) => ({ event_name: 'workflow:checkpoint:create' as const, ...data })
};
export const WorkflowCheckpointDeleteRequest = {
  event_name: 'workflow:checkpoint:delete' as const,
  create: (data: WorkflowCheckpointDeleteRequest) => ({ event_name: 'workflow:checkpoint:delete' as const, ...data })
};
export const WorkflowCheckpointListRequest = {
  event_name: 'workflow:checkpoint:list' as const,
  create: (data: WorkflowCheckpointListRequest) => ({ event_name: 'workflow:checkpoint:list' as const, ...data })
};
export const WorkflowCheckpointRestoreRequest = {
  event_name: 'workflow:checkpoint:restore' as const,
  create: (data: WorkflowCheckpointRestoreRequest) => ({ event_name: 'workflow:checkpoint:restore' as const, ...data })
};
export const WorkflowClearNodeStateRequest = {
  event_name: 'workflow:clear_node_state' as const,
  create: (data: WorkflowClearNodeStateRequest) => ({ event_name: 'workflow:clear_node_state' as const, ...data })
};
export const WorkflowCollabTokenRequest = {
  event_name: 'workflow:collab_token' as const,
  create: (data: WorkflowCollabTokenRequest) => ({ event_name: 'workflow:collab_token' as const, ...data })
};
export const WorkflowCreateRequest = {
  event_name: 'workflow:create' as const,
  create: (data: WorkflowCreateRequest) => ({ event_name: 'workflow:create' as const, ...data })
};
export const WorkflowDeleteRequest = {
  event_name: 'workflow:delete' as const,
  create: (data: WorkflowDeleteRequest) => ({ event_name: 'workflow:delete' as const, ...data })
};
export const WorkflowExecuteRequest = {
  event_name: 'workflow:execute' as const,
  create: (data: WorkflowExecuteRequest) => ({ event_name: 'workflow:execute' as const, ...data })
};
export const WorkflowExecutionCountsRequest = {
  event_name: 'workflow:get_execution_counts' as const,
  create: (data: WorkflowExecutionCountsRequest) => ({ event_name: 'workflow:get_execution_counts' as const, ...data })
};
export const WorkflowExecutionDetailRequest = {
  event_name: 'workflow:get_execution_detail' as const,
  create: (data: WorkflowExecutionDetailRequest) => ({ event_name: 'workflow:get_execution_detail' as const, ...data })
};
export const WorkflowExecutionListRequest = {
  event_name: 'workflow:list_executions' as const,
  create: (data: WorkflowExecutionListRequest) => ({ event_name: 'workflow:list_executions' as const, ...data })
};
export const WorkflowGetNodeOutputHistoryRequest = {
  event_name: 'workflow:get_node_output_history' as const,
  create: (data: WorkflowGetNodeOutputHistoryRequest) => ({ event_name: 'workflow:get_node_output_history' as const, ...data })
};
export const WorkflowGetNodeOutputsRequest = {
  event_name: 'workflow:get_node_outputs' as const,
  create: (data: WorkflowGetNodeOutputsRequest) => ({ event_name: 'workflow:get_node_outputs' as const, ...data })
};
export const WorkflowGetRequest = {
  event_name: 'workflow:get' as const,
  create: (data: WorkflowGetRequest) => ({ event_name: 'workflow:get' as const, ...data })
};
export const WorkflowListRequest = {
  event_name: 'workflow:list' as const,
  create: (data: WorkflowListRequest) => ({ event_name: 'workflow:list' as const, ...data })
};
export const WorkflowListTrashRequest = {
  event_name: 'workflow:list_trash' as const,
  create: (data: WorkflowListTrashRequest) => ({ event_name: 'workflow:list_trash' as const, ...data })
};
export const WorkflowLoadNodeStateRequest = {
  event_name: 'workflow:load_node_state' as const,
  create: (data: WorkflowLoadNodeStateRequest) => ({ event_name: 'workflow:load_node_state' as const, ...data })
};
export const WorkflowMCPCreateWorkflowRequest = {
  event_name: 'workflow:mcp:create_workflow' as const,
  create: (data: WorkflowMCPCreateWorkflowRequest) => ({ event_name: 'workflow:mcp:create_workflow' as const, ...data })
};
export const WorkflowMCPDeleteWorkflowRequest = {
  event_name: 'workflow:mcp:delete_workflow' as const,
  create: (data: WorkflowMCPDeleteWorkflowRequest) => ({ event_name: 'workflow:mcp:delete_workflow' as const, ...data })
};
export const WorkflowMCPGetExecutionStatusRequest = {
  event_name: 'workflow:mcp:get_execution_status' as const,
  create: (data: WorkflowMCPGetExecutionStatusRequest) => ({ event_name: 'workflow:mcp:get_execution_status' as const, ...data })
};
export const WorkflowMCPGetNodeConfigRequest = {
  event_name: 'workflow:mcp:get_node_config' as const,
  create: (data: WorkflowMCPGetNodeConfigRequest) => ({ event_name: 'workflow:mcp:get_node_config' as const, ...data })
};
export const WorkflowMCPGetNodeConfigSchemaRequest = {
  event_name: 'workflow:mcp:get_node_config_schema' as const,
  create: (data: WorkflowMCPGetNodeConfigSchemaRequest) => ({ event_name: 'workflow:mcp:get_node_config_schema' as const, ...data })
};
export const WorkflowMCPGetNodeInputRequest = {
  event_name: 'workflow:mcp:get_node_input' as const,
  create: (data: WorkflowMCPGetNodeInputRequest) => ({ event_name: 'workflow:mcp:get_node_input' as const, ...data })
};
export const WorkflowMCPGetNodeOutputRequest = {
  event_name: 'workflow:mcp:get_node_output' as const,
  create: (data: WorkflowMCPGetNodeOutputRequest) => ({ event_name: 'workflow:mcp:get_node_output' as const, ...data })
};
export const WorkflowMCPGetOpenWorkflowRequest = {
  event_name: 'workflow:mcp:get_open_workflow' as const,
  create: (data: WorkflowMCPGetOpenWorkflowRequest) => ({ event_name: 'workflow:mcp:get_open_workflow' as const, ...data })
};
export const WorkflowMCPGetSelectedNodeRequest = {
  event_name: 'workflow:mcp:get_selected_node' as const,
  create: (data: WorkflowMCPGetSelectedNodeRequest) => ({ event_name: 'workflow:mcp:get_selected_node' as const, ...data })
};
export const WorkflowMCPListCredentialsRequest = {
  event_name: 'workflow:mcp:list_credentials' as const,
  create: (data: WorkflowMCPListCredentialsRequest) => ({ event_name: 'workflow:mcp:list_credentials' as const, ...data })
};
export const WorkflowMCPListSavedOutputsRequest = {
  event_name: 'workflow:mcp:list_saved_outputs' as const,
  create: (data: WorkflowMCPListSavedOutputsRequest) => ({ event_name: 'workflow:mcp:list_saved_outputs' as const, ...data })
};
export const WorkflowMCPListWorkflowsRequest = {
  event_name: 'workflow:mcp:list_workflows' as const,
  create: (data: WorkflowMCPListWorkflowsRequest) => ({ event_name: 'workflow:mcp:list_workflows' as const, ...data })
};
export const WorkflowMCPLoadFieldOptionsRequest = {
  event_name: 'workflow:mcp:load_field_options' as const,
  create: (data: WorkflowMCPLoadFieldOptionsRequest) => ({ event_name: 'workflow:mcp:load_field_options' as const, ...data })
};
export const WorkflowMCPOpenWorkflowRequest = {
  event_name: 'workflow:mcp:open_workflow' as const,
  create: (data: WorkflowMCPOpenWorkflowRequest) => ({ event_name: 'workflow:mcp:open_workflow' as const, ...data })
};
export const WorkflowMCPResponseRequest = {
  event_name: 'workflow:mcp:response' as const,
  create: (data: WorkflowMCPResponseRequest) => ({ event_name: 'workflow:mcp:response' as const, ...data })
};
export const WorkflowMCPRunNodeRequest = {
  event_name: 'workflow:mcp:run_node' as const,
  create: (data: WorkflowMCPRunNodeRequest) => ({ event_name: 'workflow:mcp:run_node' as const, ...data })
};
export const WorkflowMCPRunWorkflowRequest = {
  event_name: 'workflow:mcp:run_workflow' as const,
  create: (data: WorkflowMCPRunWorkflowRequest) => ({ event_name: 'workflow:mcp:run_workflow' as const, ...data })
};
export const WorkflowMCPSearchNodesRequest = {
  event_name: 'workflow:mcp:search_nodes' as const,
  create: (data: WorkflowMCPSearchNodesRequest) => ({ event_name: 'workflow:mcp:search_nodes' as const, ...data })
};
export const WorkflowMCPUpdateInterfaceRequest = {
  event_name: 'workflow:mcp:update_interface' as const,
  create: (data: WorkflowMCPUpdateInterfaceRequest) => ({ event_name: 'workflow:mcp:update_interface' as const, ...data })
};
export const WorkflowMCPUpdateWorkflowMetadataRequest = {
  event_name: 'workflow:mcp:update_workflow_metadata' as const,
  create: (data: WorkflowMCPUpdateWorkflowMetadataRequest) => ({ event_name: 'workflow:mcp:update_workflow_metadata' as const, ...data })
};
export const WorkflowMoveToFolderRequest = {
  event_name: 'workflow_folder:move_workflow' as const,
  create: (data: WorkflowMoveToFolderRequest) => ({ event_name: 'workflow_folder:move_workflow' as const, ...data })
};
export const WorkflowNodeConfigSchemaRequest = {
  event_name: 'workflow:node:get_config_schema' as const,
  create: (data: WorkflowNodeConfigSchemaRequest) => ({ event_name: 'workflow:node:get_config_schema' as const, ...data })
};
export const WorkflowNodeEvaluateExpressionRequest = {
  event_name: 'workflow:node:evaluate_expression' as const,
  create: (data: WorkflowNodeEvaluateExpressionRequest) => ({ event_name: 'workflow:node:evaluate_expression' as const, ...data })
};
export const WorkflowNodeGetConfigRequest = {
  event_name: 'workflow:node:get_config' as const,
  create: (data: WorkflowNodeGetConfigRequest) => ({ event_name: 'workflow:node:get_config' as const, ...data })
};
export const WorkflowNodeLoadOptionsRequest = {
  event_name: 'workflow:node:load_options' as const,
  create: (data: WorkflowNodeLoadOptionsRequest) => ({ event_name: 'workflow:node:load_options' as const, ...data })
};
export const WorkflowNodeLoadValueRequest = {
  event_name: 'workflow:node:load_value' as const,
  create: (data: WorkflowNodeLoadValueRequest) => ({ event_name: 'workflow:node:load_value' as const, ...data })
};
export const WorkflowNodeOutputRequest = {
  event_name: 'workflow:get_node_output' as const,
  create: (data: WorkflowNodeOutputRequest) => ({ event_name: 'workflow:get_node_output' as const, ...data })
};
export const WorkflowNodeSetConfigRequest = {
  event_name: 'workflow:node:set_config' as const,
  create: (data: WorkflowNodeSetConfigRequest) => ({ event_name: 'workflow:node:set_config' as const, ...data })
};
export const WorkflowNodeValidateConfigRequest = {
  event_name: 'workflow:node:validate_config' as const,
  create: (data: WorkflowNodeValidateConfigRequest) => ({ event_name: 'workflow:node:validate_config' as const, ...data })
};
export const WorkflowPermanentDeleteRequest = {
  event_name: 'workflow:permanent_delete' as const,
  create: (data: WorkflowPermanentDeleteRequest) => ({ event_name: 'workflow:permanent_delete' as const, ...data })
};
export const WorkflowRestoreRequest = {
  event_name: 'workflow:restore' as const,
  create: (data: WorkflowRestoreRequest) => ({ event_name: 'workflow:restore' as const, ...data })
};
export const WorkflowSaveNodeStateRequest = {
  event_name: 'workflow:save_node_state' as const,
  create: (data: WorkflowSaveNodeStateRequest) => ({ event_name: 'workflow:save_node_state' as const, ...data })
};
export const WorkflowStateGetRequest = {
  event_name: 'workflow:state:get' as const,
  create: (data: WorkflowStateGetRequest) => ({ event_name: 'workflow:state:get' as const, ...data })
};
export const WorkflowStateKeysRequest = {
  event_name: 'workflow:state:keys' as const,
  create: (data: WorkflowStateKeysRequest) => ({ event_name: 'workflow:state:keys' as const, ...data })
};
export const WorkflowStateSetRequest = {
  event_name: 'workflow:state:set' as const,
  create: (data: WorkflowStateSetRequest) => ({ event_name: 'workflow:state:set' as const, ...data })
};
export const WorkflowUpdateRequest = {
  event_name: 'workflow:update' as const,
  create: (data: WorkflowUpdateRequest) => ({ event_name: 'workflow:update' as const, ...data })
};
export const YjsSyncRequest = {
  event_name: 'yjs:sync' as const,
  create: (data: Uint8Array | number[]) => ({ event_name: 'yjs:sync' as const, data })
};
export const ZendeskOAuthExchangeRequest = {
  event_name: 'zendesk:oauth:exchange' as const,
  create: (data: ZendeskOAuthExchangeRequest) => ({ event_name: 'zendesk:oauth:exchange' as const, ...data })
};
export const ZendeskOAuthRefreshRequest = {
  event_name: 'zendesk:oauth:refresh' as const,
  create: (data: ZendeskOAuthRefreshRequest) => ({ event_name: 'zendesk:oauth:refresh' as const, ...data })
};
export const ZendeskOAuthValidateRequest = {
  event_name: 'zendesk:oauth:validate' as const,
  create: (data: ZendeskOAuthValidateRequest) => ({ event_name: 'zendesk:oauth:validate' as const, ...data })
};
export const ZoomOAuthExchangeRequest = {
  event_name: 'zoom:oauth:exchange' as const,
  create: (data: ZoomOAuthExchangeRequest) => ({ event_name: 'zoom:oauth:exchange' as const, ...data })
};
export const ZoomOAuthRefreshRequest = {
  event_name: 'zoom:oauth:refresh' as const,
  create: (data: ZoomOAuthRefreshRequest) => ({ event_name: 'zoom:oauth:refresh' as const, ...data })
};
export const ZoomOAuthValidateRequest = {
  event_name: 'zoom:oauth:validate' as const,
  create: (data: ZoomOAuthValidateRequest) => ({ event_name: 'zoom:oauth:validate' as const, ...data })
};


// Event routing configuration (imported from backend's event_routing.py)
export const EventRouting = {
  'activity:list': 'API',
  'agent:builder_decision': 'API',
  'agent:pause': 'API',
  'agent:set:cwd': 'API',
  'agent:update_model': 'API',
  'agent_share:get_or_create': 'API',
  'agent_share:rotate': 'API',
  'agent_share:set_active': 'API',
  'agent_workspace:delete': 'API',
  'agent_workspace:list': 'API',
  'airtable:oauth:exchange': 'API',
  'airtable:oauth:refresh': 'API',
  'airtable:oauth:validate': 'API',
  'apollo:oauth:exchange': 'API',
  'apollo:oauth:refresh': 'API',
  'apollo:oauth:validate': 'API',
  'approval:list': 'API',
  'approval:respond': 'API',
  'asana:oauth:exchange': 'API',
  'asana:oauth:refresh': 'API',
  'asana:oauth:validate': 'API',
  'atlassian:oauth:exchange': 'API',
  'atlassian:oauth:refresh': 'API',
  'atlassian:oauth:validate': 'API',
  'attio:oauth:exchange': 'API',
  'attio:oauth:refresh': 'API',
  'attio:oauth:validate': 'API',
  'bamboohr:oauth:exchange': 'API',
  'bamboohr:oauth:refresh': 'API',
  'bamboohr:oauth:validate': 'API',
  'box:oauth:exchange': 'API',
  'box:oauth:refresh': 'API',
  'box:oauth:validate': 'API',
  'calcom:oauth:exchange': 'API',
  'calcom:oauth:refresh': 'API',
  'calcom:oauth:validate': 'API',
  'calendly:oauth:exchange': 'API',
  'calendly:oauth:refresh': 'API',
  'calendly:oauth:validate': 'API',
  'canva:oauth:exchange': 'API',
  'canva:oauth:refresh': 'API',
  'canva:oauth:validate': 'API',
  'chat:message': 'API',
  'claude-code:auth:exchange': 'API',
  'claude-code:auth:start': 'API',
  'clickup:oauth:exchange': 'API',
  'clickup:oauth:refresh': 'API',
  'clickup:oauth:validate': 'API',
  'cloudflare:oauth:exchange': 'API',
  'cloudflare:oauth:refresh': 'API',
  'cloudflare:oauth:validate': 'API',
  'codex:auth:poll': 'API',
  'codex:auth:start': 'API',
  'conversation:delete': 'API',
  'conversation:get_latest_for_workflow': 'API',
  'conversation:list_for_agent': 'API',
  'conversation:resume': 'API',
  'conversations:list': 'API',
  'credential:authorize_for_workflow': 'API',
  'credential:create': 'API',
  'credential:delete': 'API',
  'credential:display_info': 'API',
  'credential:get': 'API',
  'credential:list': 'API',
  'credential:request:cancel': 'API',
  'credential:request:create': 'API',
  'credential:request:list': 'API',
  'credential:test_connection': 'API',
  'credential:update': 'API',
  'credential:validate_access': 'API',
  'discord:oauth:exchange': 'API',
  'discord:oauth:refresh': 'API',
  'discord:oauth:validate': 'API',
  'dropbox:oauth:exchange': 'API',
  'dropbox:oauth:refresh': 'API',
  'dropbox:oauth:validate': 'API',
  'email:check_local_part': 'API',
  'email:reserve_address': 'API',
  'facebook:oauth:exchange': 'API',
  'facebook:oauth:refresh': 'API',
  'facebook:oauth:validate': 'API',
  'facebook_pages:oauth:exchange': 'API',
  'facebook_pages:oauth:refresh': 'API',
  'facebook_pages:oauth:validate': 'API',
  'fathom:oauth:exchange': 'API',
  'fathom:oauth:refresh': 'API',
  'fathom:oauth:validate': 'API',
  'feedback:submit': 'API',
  'github:oauth:exchange': 'API',
  'github:oauth:refresh': 'API',
  'github:oauth:validate': 'API',
  'gitlab:oauth:exchange': 'API',
  'gitlab:oauth:refresh': 'API',
  'gitlab:oauth:validate': 'API',
  'google:oauth:exchange': 'API',
  'google:oauth:refresh': 'API',
  'google:oauth:validate': 'API',
  'hubspot:oauth:exchange': 'API',
  'hubspot:oauth:refresh': 'API',
  'hubspot:oauth:validate': 'API',
  'instance_keys:delete': 'API',
  'instance_keys:list': 'API',
  'instance_keys:set': 'API',
  'instance_oauth:delete': 'API',
  'instance_oauth:list': 'API',
  'instance_oauth:set': 'API',
  'intercom:oauth:exchange': 'API',
  'intercom:oauth:refresh': 'API',
  'intercom:oauth:validate': 'API',
  'klaviyo:oauth:exchange': 'API',
  'klaviyo:oauth:refresh': 'API',
  'klaviyo:oauth:validate': 'API',
  'linear:oauth:exchange': 'API',
  'linear:oauth:refresh': 'API',
  'linear:oauth:validate': 'API',
  'linkedin:oauth:exchange': 'API',
  'linkedin:oauth:refresh': 'API',
  'linkedin:oauth:validate': 'API',
  'mailchimp:oauth:exchange': 'API',
  'mcp:oauth:discover': 'API',
  'mcp:oauth:exchange': 'API',
  'mcp:oauth:register-client': 'API',
  'meta:oauth:exchange': 'API',
  'meta:oauth:refresh': 'API',
  'meta:oauth:validate': 'API',
  'microsoft:oauth:exchange': 'API',
  'microsoft:oauth:refresh': 'API',
  'microsoft:oauth:validate': 'API',
  'monday:oauth:exchange': 'API',
  'monday:oauth:refresh': 'API',
  'monday:oauth:validate': 'API',
  'notifications:prefs:get': 'API',
  'notifications:prefs:update': 'API',
  'notion:oauth:exchange': 'API',
  'notion:oauth:refresh': 'API',
  'notion:oauth:validate': 'API',
  'onboarding:completion:get': 'API',
  'onboarding:completion:update': 'API',
  'onboarding:skip': 'API',
  'onboarding:submit': 'API',
  'organization:check_slug': 'API',
  'organization:create': 'API',
  'organization:delete': 'API',
  'organization:get': 'API',
  'organization:invites:accept': 'API',
  'organization:invites:get': 'API',
  'organization:invites:list': 'API',
  'organization:invites:revoke': 'API',
  'organization:list_mine': 'API',
  'organization:members:invite': 'API',
  'organization:members:list': 'API',
  'organization:members:remove': 'API',
  'organization:members:update_role': 'API',
  'organization:sso:configure': 'API',
  'organization:sso:disable': 'API',
  'organization:sso:info': 'API',
  'organization:switch': 'API',
  'organization:transfer_ownership': 'API',
  'organization:update': 'API',
  'organization:upload_icon': 'API',
  'pagerduty:oauth:exchange': 'API',
  'pagerduty:oauth:refresh': 'API',
  'pagerduty:oauth:validate': 'API',
  'parallel:oauth:exchange': 'API',
  'parallel:oauth:validate': 'API',
  'pipedrive:oauth:exchange': 'API',
  'pipedrive:oauth:refresh': 'API',
  'pipedrive:oauth:validate': 'API',
  'posthog:oauth:exchange': 'API',
  'posthog:oauth:refresh': 'API',
  'posthog:oauth:validate': 'API',
  'quickbooks:oauth:exchange': 'API',
  'quickbooks:oauth:refresh': 'API',
  'quickbooks:oauth:validate': 'API',
  'reddit:oauth:exchange': 'API',
  'reddit:oauth:refresh': 'API',
  'reddit:oauth:validate': 'API',
  'rehearsal:run': 'API',
  'rehearsal:scenarios': 'API',
  'resource:create': 'API',
  'resource:dataset:append': 'API',
  'resource:dataset:delete_rows': 'API',
  'resource:dataset:rows': 'API',
  'resource:dataset:update_row': 'API',
  'resource:delete': 'API',
  'resource:download_url': 'API',
  'resource:fork': 'API',
  'resource:get': 'API',
  'resource:list': 'API',
  'resource:upload_url': 'API',
  'run_share:create': 'API',
  'salesforce:oauth:exchange': 'API',
  'salesforce:oauth:refresh': 'API',
  'salesforce:oauth:validate': 'API',
  'saved_output:create': 'API',
  'saved_output:delete': 'API',
  'saved_output:get': 'API',
  'saved_output:list': 'API',
  'saved_output:update': 'API',
  'sentry:oauth:exchange': 'API',
  'sentry:oauth:refresh': 'API',
  'sentry:oauth:validate': 'API',
  'share:create': 'API',
  'share:delete': 'API',
  'share:invite_accept': 'API',
  'share:invite_link': 'API',
  'share:leave': 'API',
  'share:list': 'API',
  'share:list_shared_with_me': 'API',
  'share:update': 'API',
  'shared_agent:resume': 'API',
  'shared_agent:send': 'API',
  'shopify:oauth:exchange': 'API',
  'shopify:oauth:refresh': 'API',
  'shopify:oauth:validate': 'API',
  'skill:create': 'API',
  'skill:delete': 'API',
  'skill:get': 'API',
  'skill:get_workflow': 'API',
  'skill:list': 'API',
  'skill:mute': 'API',
  'skill:update': 'API',
  'skill:update_workflow': 'API',
  'slack:oauth:exchange': 'API',
  'slack:oauth:refresh': 'API',
  'slack:oauth:validate': 'API',
  'stripe:oauth:exchange': 'API',
  'stripe:oauth:refresh': 'API',
  'stripe:oauth:validate': 'API',
  'supabase:oauth:exchange': 'API',
  'supabase:oauth:refresh': 'API',
  'supabase:oauth:select_project': 'API',
  'supabase:oauth:validate': 'API',
  'threads:oauth:exchange': 'API',
  'threads:oauth:refresh': 'API',
  'threads:oauth:validate': 'API',
  'tiktok:oauth:exchange': 'API',
  'tiktok:oauth:refresh': 'API',
  'tiktok:oauth:validate': 'API',
  'tool_calls:list': 'API',
  'twitter:oauth:exchange': 'API',
  'twitter:oauth:refresh': 'API',
  'twitter:oauth:validate': 'API',
  'typeform:oauth:exchange': 'API',
  'typeform:oauth:refresh': 'API',
  'typeform:oauth:validate': 'API',
  'usage:data': 'API',
  'usage:logs': 'API',
  'webflow:oauth:exchange': 'API',
  'webflow:oauth:refresh': 'API',
  'webflow:oauth:validate': 'API',
  'whatsapp:qr:start': 'API',
  'whatsapp:qr:status': 'API',
  'wordpress:oauth:exchange': 'API',
  'wordpress:oauth:refresh': 'API',
  'wordpress:oauth:validate': 'API',
  'workflow:builder:autofill': 'API',
  'workflow:builder:edit': 'API',
  'workflow:builder:get_state': 'API',
  'workflow:builder:input_response': 'API',
  'workflow:builder:list_pending': 'API',
  'workflow:builder:share_ask': 'API',
  'workflow:builder:usage': 'API',
  'workflow:checkpoint:create': 'API',
  'workflow:checkpoint:delete': 'API',
  'workflow:checkpoint:list': 'API',
  'workflow:checkpoint:restore': 'API',
  'workflow:clear_node_state': 'API',
  'workflow:collab_token': 'API',
  'workflow:create': 'API',
  'workflow:delete': 'API',
  'workflow:execute': 'API',
  'workflow:get': 'API',
  'workflow:get_execution_counts': 'API',
  'workflow:get_execution_detail': 'API',
  'workflow:get_node_output': 'API',
  'workflow:get_node_output_history': 'API',
  'workflow:get_node_outputs': 'API',
  'workflow:list': 'API',
  'workflow:list_executions': 'API',
  'workflow:list_trash': 'API',
  'workflow:load_node_state': 'API',
  'workflow:mcp:create_workflow': 'API',
  'workflow:mcp:delete_workflow': 'API',
  'workflow:mcp:get_execution_status': 'API',
  'workflow:mcp:get_folder_tree': 'API',
  'workflow:mcp:get_node_config': 'API',
  'workflow:mcp:get_node_config_schema': 'API',
  'workflow:mcp:get_node_input': 'API',
  'workflow:mcp:get_node_output': 'API',
  'workflow:mcp:get_open_workflow': 'API',
  'workflow:mcp:get_selected_node': 'API',
  'workflow:mcp:list_credentials': 'API',
  'workflow:mcp:list_saved_outputs': 'API',
  'workflow:mcp:list_workflows': 'API',
  'workflow:mcp:load_field_options': 'API',
  'workflow:mcp:open_workflow': 'API',
  'workflow:mcp:response': 'API',
  'workflow:mcp:run_node': 'API',
  'workflow:mcp:run_workflow': 'API',
  'workflow:mcp:search_nodes': 'API',
  'workflow:mcp:update_interface': 'API',
  'workflow:mcp:update_workflow_metadata': 'API',
  'workflow:node:evaluate_expression': 'API',
  'workflow:node:get_config': 'API',
  'workflow:node:get_config_schema': 'API',
  'workflow:node:load_options': 'API',
  'workflow:node:load_value': 'API',
  'workflow:node:schema': 'API',
  'workflow:node:set_config': 'API',
  'workflow:node:validate_config': 'API',
  'workflow:permanent_delete': 'API',
  'workflow:restore': 'API',
  'workflow:save_node_state': 'API',
  'workflow:state:get': 'API',
  'workflow:state:keys': 'API',
  'workflow:state:set': 'API',
  'workflow:stop': 'API',
  'workflow:update': 'API',
  'workflow_folder:create': 'API',
  'workflow_folder:delete': 'API',
  'workflow_folder:get': 'API',
  'workflow_folder:get_path': 'API',
  'workflow_folder:get_tree': 'API',
  'workflow_folder:list': 'API',
  'workflow_folder:move_workflow': 'API',
  'workflow_folder:update': 'API',
  'yjs:sync': 'API',
  'zendesk:oauth:exchange': 'API',
  'zendesk:oauth:refresh': 'API',
  'zendesk:oauth:validate': 'API',
  'zoom:oauth:exchange': 'API',
  'zoom:oauth:refresh': 'API',
  'zoom:oauth:validate': 'API',
} as const;

export type SocketEnvironment = 'API';
