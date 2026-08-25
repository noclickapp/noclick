"""
Centralized socket.io event sender with type safety via Pydantic models.
All socket emissions should go through this module to ensure consistency and type validation.
"""
from typing import Union, Optional
from contextvars import ContextVar
from pydantic import BaseModel
import logging
from utils.constants import IGNORE_EVENTS

logger = logging.getLogger(__name__)

# Context variable for the active execution relay (set per-execution in workflow_execution_handler)
# This allows send_event to automatically route through the WebSocket relay without
# threading the relay instance through every call site.
_active_execution_relay: ContextVar = ContextVar('_active_execution_relay', default=None)

IGNORE_EVENT_LOGGING = {"yjs:sync", "chat:message"} | IGNORE_EVENTS

# Cache SDK client sids with their workflow scope (set at connect, cleared at disconnect).
# Avoids async session lookup on every execution event emission.
_sdk_sids: dict[str, str | None] = {}  # sid -> workflow_id (or None if unscoped)

def mark_sdk_client(sid: str, workflow_id: str | None = None) -> None:
    """Called at connect time to cache SDK client status and workflow scope."""
    _sdk_sids[sid] = workflow_id

def unmark_sdk_client(sid: str) -> None:
    """Called at disconnect time to clean up."""
    _sdk_sids.pop(sid, None)

def is_sdk_client(sid: str) -> bool:
    """Check if a sid is an SDK client (cached, no async lookup needed)."""
    return sid in _sdk_sids

def get_sdk_sids_for_workflow(workflow_id: str, exclude_sid: str | None = None) -> list[str]:
    """Get all SDK client sids connected to a specific workflow."""
    return [s for s, wf in _sdk_sids.items() if wf == workflow_id and s != exclude_sid]

async def send_event(
    sio,
    sid: str,
    event: BaseModel,
    room: Optional[str] = None,
    user_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    execution_relay=None,
) -> None:
    """
    Send a socket.io event using a Pydantic model.

    Args:
        sio: Socket.io server instance
        sid: Session ID of the recipient
        event: Pydantic model instance with event_name class variable
        room: Optional room to send to (defaults to sid)
        user_id: If provided, broadcast via Event Relay (event relay) instead of Socket.IO.
                 Use this for webhook handlers, cron jobs, and cross-container events.
        workflow_id: If provided, broadcast via workflow relay for execution events.
                     This routes exclusively through workflow relay — no Socket.IO emit.
        execution_relay: If provided, send execution events through this WebSocket
                        relay (ExecutionRelay instance) instead of HTTP POST.
                        Guarantees in-order delivery.

    Raises:
        ValueError: If event doesn't have event_name defined
        Exception: If socket emission fails
    """
    # Execution events: route through workflow relay via WebSocket
    if workflow_id:
        # Check context variable if no explicit relay passed
        if execution_relay is None:
            execution_relay = _active_execution_relay.get(None)

        if execution_relay and execution_relay.connected:
            event_name = getattr(event, 'event_name', None)
            data = event.model_dump(mode='json', exclude_none=True)
            if event_name:
                data['type'] = event_name
            await execution_relay.send_event(data)
            # Still emit directly to SDK clients (they don't subscribe to the relay)
            if is_sdk_client(sid):
                pass  # Fall through to Socket.IO emit below
            else:
                return

    # Relay events (non-execution): route through event relay
    if user_id:
        from utils.event_relay import broadcast_to_user_safe
        await broadcast_to_user_safe(user_id, event)
        return
    # A falsy sid with no room must NEVER reach sio.emit: python-socketio
    # coalesces to="" into room=None, which BROADCASTS to every client in the
    # namespace.
    # Broadcasts through this API are explicit — room=/user_id=/workflow_id=.
    if not sid and not room:
        logger.error(
            "[SENDER] dropped %s emit with empty sid and no room (would broadcast to all clients)",
            getattr(event, "event_name", event.__class__.__name__),
        )
        return

    # Get event name from the model class
    if not hasattr(event, 'event_name'):
        raise ValueError(f"{event.__class__.__name__} must define event_name class variable")

    event_name = event.event_name

    # Entry logging for debugging
    if event_name not in IGNORE_EVENT_LOGGING:
        logger.debug(f"[SENDER] send_event called: event={event_name}, sid={sid}, room={room}")

    # Get the data payload
    try:
        # Check if model has custom model_dump implementation
        data = event.model_dump(mode='json', exclude_none=True)
    except TypeError:
        # Some events override model_dump to return non-dict types
        data = event.model_dump()

    # Send the event normally (with chunking if payload is too large)
    from .chunk_sender import maybe_chunk, send_chunked_event

    try:
        if event_name not in IGNORE_EVENT_LOGGING:
            logger.debug(f"[SENDER] About to emit {event_name} to {room or sid}")

        # Serialize + size-check + (if large) chunk in a worker thread so a
        # multi-MB payload (cache_valtio:state, get_node_output_history) never
        # blocks the event loop on json.dumps. Returns None for normal-sized
        # payloads, which are emitted directly below.
        prepared = await maybe_chunk(data)
        if prepared is not None:
            chunks, wrapper = prepared
            await send_chunked_event(sio, sid, event_name, chunks, wrapper, room=room)
        elif room:
            await sio.emit(event_name, data, room=room)
        else:
            await sio.emit(event_name, data, to=sid)

        # More detailed logging for response events and mount status
        if event_name == 'response':
            logger.debug(f"[SENDER] Emitted {event_name} to {sid[:8]}... with request_id: {data.get('request_id', 'N/A')}")
        elif event_name == 'usage:event':
            logger.debug(f"[SENDER] Emitted {event_name} to {sid} - cost: ${data.get('total_cost', 0):.6f}")
        elif event_name not in IGNORE_EVENT_LOGGING:
            logger.debug(f"Emitted {event_name} to {room or sid}")
    except Exception as e:
        logger.error(f"Failed to emit {event_name}: {str(e)}", exc_info=True)
        raise


# Re-export all event models for convenience
from .events import (
    ChatMessageEvent,
    ChatTranscriptionEvent,
    ConversationResumeEvent,
    ConversationListEvent,
    CreditsExhaustedEvent,
    YjsSyncEvent,
    CacheValtioStateEvent,
    ErrorEvent,
    ResponseEvent,
    ServerDataEvent,
    AgentStateEvent,
    # Usage Dashboard Events
    UsageDataEvent,
    UsageEventUpdateEvent,
    # Workflow Execution Events
    WorkflowNodeStateEvent,
    WorkflowNodeOutputEvent,
    WorkflowNodeProgressEvent,
    WorkflowStartedEvent,
    WorkflowCompleteEvent,
    # Approval Feed Events
    ApprovalRequestCreatedEvent,
    ApprovalRequestResolvedEvent,
    ActivityLogCreatedEvent,
)
from .schema import AgenticStep

__all__ = [
    'send_event',
    'ChatMessageEvent',
    'ChatTranscriptionEvent',
    'ConversationResumeEvent',
    'ConversationListEvent',
    'CreditsExhaustedEvent',
    'YjsSyncEvent',
    'CacheValtioStateEvent',
    'ErrorEvent',
    'ResponseEvent',
    'ServerDataEvent',
    'AgentStateEvent',
    'AgenticStep',
    # Usage Dashboard Events
    'UsageDataEvent',
    'UsageEventUpdateEvent',
    # Workflow Execution Events
    'WorkflowNodeStateEvent',
    'WorkflowNodeOutputEvent',
    'WorkflowNodeProgressEvent',
    'WorkflowStartedEvent',
    'WorkflowCompleteEvent',
    # Approval Feed Events
    'ApprovalRequestCreatedEvent',
    'ApprovalRequestResolvedEvent',
    'ActivityLogCreatedEvent',
]
