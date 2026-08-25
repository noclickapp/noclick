import os
import logging
import asyncio
import threading
import time
import inspect
from typing import Dict, List, Optional, Type, Any
from pydantic import BaseModel, ValidationError

import psutil
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode


# Shared psutil.Process handle for resource snapshots. Cheap to instantiate but
# we reuse to avoid the per-call fd open in /proc/self.
_proc = psutil.Process()


def _snapshot_resources() -> dict:
    """Cheap snapshot of process-wide resource counters. Captured before and
    after each socket event so the delta can be stamped as a span attribute.

    Caveat: these counters are PROCESS-WIDE. Under concurrent in-flight events,
    the delta attributed to one event includes work done by sibling events. At
    higher concurrency each per-call delta is noisy, but aggregation by event
    type can still surface a systematic leak.

    Deliberately excludes the open-fd count: psutil's ``num_fds()`` scandirs
    /proc/self/fd, adding avoidable filesystem work twice per event. FD leaks
    remain visible through the periodic process-health sampler; the hot path
    does not pay for that scandir. memory_info() remains a single procfs read.
    The
    per-event hot path. memory_info() (one /proc/self/statm read) and the
    in-process task/thread counts are cheap and stay.
    """
    return {
        "rss_bytes": _proc.memory_info().rss,
        "task_count": len(asyncio.all_tasks()) if asyncio._get_running_loop() else 0,
        "thread_count": threading.active_count(),
    }


def _stamp_resource_delta(span, before: dict) -> None:
    """Compute and stamp the per-event resource delta as span attributes.

    Negative deltas are normal (GC reclaimed memory during the handler,
    a task finished, a thread shut down) and are recorded verbatim — the
    AVG over many calls is what matters, and dropping negatives would
    bias the signal upward.
    """
    try:
        after = _snapshot_resources()
        # KB rather than bytes — Honeycomb breakdowns are easier to read.
        rss_delta_kb = (after["rss_bytes"] - before["rss_bytes"]) / 1024
        span.set_attribute("resource.rss_delta_kb", rss_delta_kb)
        span.set_attribute("resource.task_delta", after["task_count"] - before["task_count"])
        span.set_attribute("resource.thread_delta", after["thread_count"] - before["thread_count"])
        # resource.fd_delta intentionally dropped — see _snapshot_resources;
        # fd trends are tracked by container.health's process.open_fds instead.
    except Exception:
        # Telemetry must never break the request.
        pass

from wss.schema import SocketIOProxyConfig
from wss.receiver.rate_limiter import RateLimiter
from wss.receiver.rate_limits import get_rate_limit_config
from wss.receiver.chunk_reassembly import ChunkReassemblyManager
from wss.sender import send_event, ErrorEvent
from wss.receiver import client_events
from wss.receiver.client_events import ClientEventBase
from utils.constants import IGNORE_EVENTS

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer("noclick.socket")

# Aftershock detection: any handler that exceeds HEAVY_THRESHOLD_MS gets recorded
# as a "heavy event" for AFTERSHOCK_WINDOW_S seconds. New spans on the same
# container then carry `socket.recent_heavy_event=<name>` so we can `GROUP BY` it
# in Honeycomb to spot post-event degradation. Self-tuning: any slow handler
# qualifies; fast handlers never pollute the column.
HEAVY_THRESHOLD_MS = 200.0
AFTERSHOCK_WINDOW_S = 60.0

# The ONLY events an anonymous share-link session (session carries
# 'share_scope', no 'user_id') may invoke — enforced in _route_event_impl.
SHARED_VISITOR_ALLOWED_EVENTS = frozenset({"shared_agent:send", "shared_agent:resume"})

class SocketIOProxy:
    def __init__(self, sio, env=None):
        """Cheap construction only — must NOT spawn threads.

        Heavy init (handler instantiation, frontend Pydantic model registry
        build) is deferred to ``setup()`` and called from ``app_lifespan``
        AFTER the forkserver warm-up. The DB pool is a native asyncpg pool
        created on the main event loop by ``app_lifespan``'s
        ``init_native_pool()`` before ``setup()`` runs — handlers own no
        pool of their own and must not touch the DB before lifespan startup
        (``get_native_pool()`` raises until then).

        The catch-all socket.io decorator is wired here (cheap) so events
        arriving before ``setup()`` returns are deflected with a clear
        "not ready" error rather than crashing on attribute access. In
        practice FastAPI's lifespan runs to completion before connections
        are accepted, so this only matters for defensive correctness.
        """
        self.sio = sio
        self.SOCKET_PROXY_ENV = env or os.getenv("SOCKET_PROXY_ENV", "API")

        # Cheap state — dicts and a manager whose own __init__ is just dicts.
        self.chunk_manager = ChunkReassemblyManager()
        self._sessions: Dict[str, str] = {}            # sid -> user_id
        self._user_sessions: Dict[str, List[str]] = {} # user_id -> [sids]
        self._last_heavy_completion: Dict[str, float] = {}  # aftershock window

        # Heavy state — populated by setup(). Defaults are None so an
        # accidental pre-setup access fails loudly with AttributeError on
        # the missing field rather than a silent empty-dict path.
        self.handler_instances: Optional[Dict[Any, Any]] = None
        self.config: Optional[SocketIOProxyConfig] = None
        self.lifecycle_handlers: Optional[Dict[str, list]] = None
        self.rate_limiter: Optional[RateLimiter] = None
        self.frontend_request_pydantic_models: Optional[Dict[str, Type[BaseModel]]] = None

        # Wire the catch-all decorator now so the closure exists when
        # uvicorn registers routes. Calling route_event before setup()
        # finishes raises a clear ProxyNotReadyError below.
        self.setup_events()

        # Set global instance for internal event routing.
        global _receiver_instance
        _receiver_instance = self

    async def setup(self) -> None:
        """Heavy init — handler instantiation, DB pool spawn, model build.

        Idempotent. Call from ``app_lifespan`` AFTER the forkserver warm-up
        so the ``DatabasePoolThread`` (spawned by ``DatabasePoolMixin.__init__``
        on every handler) doesn't violate the warm-up's single-thread
        precondition. Safe to call multiple times — second call no-ops.
        """
        if self.handler_instances is not None:
            return
        self.handler_instances = self._create_handler_instances()
        self.config = SocketIOProxyConfig(
            rate_limits=get_rate_limit_config(),
            event_handlers=self._build_event_handlers(self.handler_instances),
        )
        self.lifecycle_handlers = self._build_lifecycle_handlers(self.handler_instances)
        self.rate_limiter = RateLimiter(self.config.rate_limits)
        self.frontend_request_pydantic_models = self._build_frontend_request_pydantic_models()
        logger.info(
            "[PROXY] setup complete (handlers=%d, env=%s)",
            sum(1 for v in self.handler_instances.values() if v is not None),
            self.SOCKET_PROXY_ENV,
        )

    async def _set_debug_context_for_sid(self, sid: str):
        """
        Set debug user context from session for SQL query logging.
        Returns a callable that undoes it, or None when there's nothing to undo.

        Nothing here knows what the context is for. A platform registers a hook
        (see handler_registry.register_request_context) and gets back the undo;
        an installation without one does no work.
        """
        from .handler_registry import enter_request_context

        user_email = None
        try:
            session = await self.sio.get_session(sid)
            if session:
                user_email = session.get('user_data', {}).get('email')
        except Exception:
            pass
        return enter_request_context(user_email, sid)

    @staticmethod
    def _reset_debug_context(undo) -> None:
        if undo is not None:
            undo()

    def _register_session(self, sid: str, user_id: str) -> None:
        """Register a session ID with a user ID for frontend SID lookups."""
        self._sessions[sid] = user_id
        if user_id not in self._user_sessions:
            self._user_sessions[user_id] = []
        if sid not in self._user_sessions[user_id]:
            self._user_sessions[user_id].append(sid)


    def _unregister_session(self, sid: str) -> None:
        """Unregister a session ID."""
        user_id = self._sessions.pop(sid, None)
        if not user_id:
            return
        if user_id in self._user_sessions:
            if sid in self._user_sessions[user_id]:
                self._user_sessions[user_id].remove(sid)
            if not self._user_sessions[user_id]:
                self._user_sessions.pop(user_id, None)

    async def setup_user(self, sid):
        """
        This function is only called when a client has been successfully authenticated.
        Once we know a client is real, we can tell our handlers to provision resources for them.
        """
        # Register session for frontend SID lookups
        try:
            session = await self.sio.get_session(sid)
            if session:
                user_id = session.get('user_id')
                if user_id:
                    self._register_session(sid, user_id)
        except Exception:
            pass

        debug_undo = await self._set_debug_context_for_sid(sid)
        try:
            await self._run_handler_method_for_all(sid, 'setup_user', with_timing=True, timing_threshold_ms=20)
        finally:
            self._reset_debug_context(debug_undo)

    async def cleanup_user(self, sid):
        """Clean up resources for a disconnected user."""
        # Clean up SDK client cache
        from wss.sender import unmark_sdk_client
        unmark_sdk_client(sid)

        # Unregister session
        self._unregister_session(sid)

        # Clean up rate limiter data first
        await self.rate_limiter.cleanup_user(sid)

        # Clean up chunk reassembly buffers
        self.chunk_manager.cleanup_user(sid)

        debug_undo = await self._set_debug_context_for_sid(sid)
        try:
            await self._run_handler_method_for_all(sid, 'cleanup_user', with_timing=False, timing_threshold_ms=100)
        finally:
            self._reset_debug_context(debug_undo)

    def setup_events(self):
        """
        Simply listens for all events and routes them to the route_event method.
        """
        @self.sio.on('*')
        async def _route_event(event, sid, data):
            if event not in IGNORE_EVENTS:
                logger.debug(f"[PROXY] _route_event called: event={event}, sid={sid}")
            # skip "connect" event and handle that separately
            # because we want to make sure auth is verified before
            # we accept events from a given sid
            # also skip "disconnect" cause we do that in cleanup_user()
            if event == "connect" or event == "disconnect":
                logger.debug(f"[PROXY] Skipping {event} event")
                return

            if event not in IGNORE_EVENTS:
                logger.debug(f"[PROXY] Calling route_event for {event}")
                
            # Call the exposed route_event method
            result = await self.route_event(event, sid, data)
            
            # If error, send error event with request_id so frontend can correlate
            if isinstance(result, dict) and "error" in result:
                req_id = data.get("request_id") if isinstance(data, dict) else getattr(data, "request_id", None)
                event_obj = ErrorEvent(type=result["error"], message=result["message"], request_id=req_id)
                await send_event(self.sio, sid, event_obj)
    

    async def route_event(self, event: str, sid: str, data):
        """
        Route an event through the handler system.
        This is the core routing logic extracted from _route_event.
        Can be called programmatically for internal routing.

        Args:
            event: Event name to route
            sid: Session ID
            data: Event data (raw or Pydantic model)

        Returns:
            Result from handler(s) or error dict with 'error' and 'message' keys
        """
        if self.config is None:
            # Defensive: setup() runs in app_lifespan before uvicorn accepts
            # connections, so this should be unreachable in production. If
            # it ever fires, fail loudly rather than crash with a confusing
            # AttributeError downstream.
            logger.error(
                "[PROXY] route_event called before setup() — event=%s sid=%s", event, sid,
            )
            return {"error": "proxy_not_ready", "message": "SocketIOProxy.setup() has not been called yet"}
        with _tracer.start_as_current_span(f"socket {event}") as span:
            span.set_attribute("socket.event", event)
            span.set_attribute("socket.sid", sid)
            # Stamp well-known correlation IDs as span attributes so an op
            # like "find the trace for conversation X" works in Honeycomb
            # without breakdown-by-user.email + guess-by-duration. Pure
            # additive — missing fields are simply skipped. Applies to
            # EVERY socket event (not just builder ones), so any future
            # debugging of e.g. workflow:execute or credential:save can
            # filter on the same attribute names.
            self._stamp_correlation_ids(span, data)
            # Wire-latency: if the FE stamped client_sent_at_ms before
            # emit, compute the wall-clock delta from receive. Useful for
            # spotting "user clicked but BE didn't see for 5s" cases
            # (socket reconnect, browser tab throttled, network blip).
            # Clock skew can make this negative — record verbatim and
            # let dashboards filter outliers downstream.
            self._stamp_wire_latency(span, data)
            self._tag_aftershock(span)
            span_start_ms = int(time.time() * 1000)
            # Resource-delta snapshot for automatic leak attribution. See
            # _snapshot_resources docstring for the why. Captured BEFORE
            # _route_event_impl runs and again in the finally below; the
            # delta gets stamped on this span so a Honeycomb query like
            # `AVG(resource.thread_delta) GROUP BY socket.event` instantly
            # surfaces which event types leak resources per call.
            res_before = _snapshot_resources()
            try:
                try:
                    result = await self._route_event_impl(event, sid, data)
                except Exception as exc:
                    span.set_attribute("error", True)
                    span.set_attribute("exception.slug", "err-socket-handler-unhandled")
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    pass
                    raise
                if isinstance(result, dict) and "error" in result:
                    span.set_attribute("error", True)
                    span.set_attribute("error.type", str(result.get("error")))
                    span.set_attribute("error.message", str(result.get("message", "")))
                    span.set_status(Status(StatusCode.ERROR, str(result.get("error"))))
                pass
                return result
            finally:
                _stamp_resource_delta(span, res_before)


    # Correlation IDs that show up on builder / workflow events. We pull these
    # off the raw payload at span open time (before any handler validation /
    # mutation) so traces are searchable by them regardless of whether the
    # handler succeeds, fails fast, or never gets called. Keep this list small —
    # every key here lands on every matching socket span as a Honeycomb column.
    _CORRELATION_KEYS_TO_ATTR = (
        ("conversation_id", "conversation_id"),
        ("generation_id", "generation_id"),
        ("workflow_id", "workflow_id"),
        ("request_id", "request_id"),
        ("ask_id", "ask_id"),
    )

    def _stamp_correlation_ids(self, span, data) -> None:
        """Set well-known IDs from `data` as span attributes.

        Defensive: data shape is per-event and may be a dict, Pydantic model
        already validated by socketio, a primitive (event with no payload),
        or — under malformed clients — something weird. We accept dict-likes
        and silently no-op on anything else.
        """
        if not isinstance(data, dict):
            return
        for key, attr_name in self._CORRELATION_KEYS_TO_ATTR:
            value = data.get(key)
            # Cast to str so unexpected types (UUID objects, ints) become
            # searchable in Honeycomb without per-key type guessing.
            if value:
                span.set_attribute(attr_name, str(value))

    def _stamp_wire_latency(self, span, data) -> None:
        """Compute FE→BE wire latency from FE-stamped client_sent_at_ms.

        The FE socket-sender auto-injects ``_client_sent_at_ms`` into every
        emit (see frontend/app/lib/socket-sender.ts). Underscore prefix marks
        it as transport metadata that should not feed into any Pydantic
        request model — strip it after reading so handlers see the original
        payload shape.
        """
        if not isinstance(data, dict):
            return
        raw = data.pop("_client_sent_at_ms", None)
        if raw is None:
            return
        try:
            client_ts = float(raw)
        except (TypeError, ValueError):
            return
        wire_latency_ms = int(time.time() * 1000) - client_ts
        # Browser clock skew can make this huge in either direction; record
        # the value verbatim so dashboards can compute percentiles and flag
        # outliers per-user rather than silently dropping suspect samples.
        span.set_attribute("socket.wire_latency_ms", wire_latency_ms)

    def _tag_aftershock(self, span) -> None:
        """Tag the span with the most-recently-completed heavy event (within window)."""
        if not self._last_heavy_completion:
            return
        now = time.monotonic()
        recent = [
            (name, now - ts)
            for name, ts in self._last_heavy_completion.items()
            if now - ts <= AFTERSHOCK_WINDOW_S
        ]
        if not recent:
            return
        name, age_s = min(recent, key=lambda x: x[1])
        span.set_attribute("socket.recent_heavy_event", name)
        span.set_attribute("socket.recent_heavy_age_ms", age_s * 1000)

    async def _route_event_impl(self, event: str, sid: str, data):
        span = trace.get_current_span()

        # Handle chunk messages (transparent reassembly for all events)
        if event == '__chunk__':
            self.chunk_manager.handle_chunk(sid, data)
            return None  # Chunks are buffered, wrapper event will retrieve payload

        # Handle chunked wrappers (transparent reassembly for all events)
        if self.chunk_manager.is_chunked_wrapper(data):
            chunk_id = self.chunk_manager.get_chunk_id(data)
            if not chunk_id:
                logger.error(f"Invalid chunked wrapper from {sid}")
                return {"error": "invalid_chunk", "message": "Invalid chunked message"}

            logger.info(f"Waiting for reassembly of {chunk_id} from {sid}")
            data = await self.chunk_manager.wait_for_reassembly(sid, chunk_id)
            if data is None:
                logger.error(f"Failed to reassemble chunks for {chunk_id} from {sid}")
                return {"error": "chunk_timeout", "message": "Chunk reassembly failed"}
            logger.info(f"Successfully reassembled {chunk_id} from {sid}")

        # Check rate limit (always enforced for security)
        allowed, error_msg = await self.rate_limiter.check_rate_limit(sid, event)
        if not allowed:
            logger.warning(f"Rate limit exceeded for {sid} on event '{event}': {error_msg}")
            return {"error": "rate_limit", "message": error_msg}
        
        # Enforce SDK permissions for API key-authenticated connections
        session = await self.sio.get_session(sid) if hasattr(self, 'sio') else {}
        if session:
            user_id = session.get('user_id')
            if user_id:
                span.set_attribute("user.id", user_id)
                # Coarse "is the user looking at NoClick" signal for agents'
                # email-vs-chat steering. Throttled + spawned — no added latency.
                from utils.user_presence import touch_user_presence

                touch_user_presence(user_id)
            user_email = session.get('user_data', {}).get('email') if isinstance(session.get('user_data'), dict) else None
            if user_email:
                span.set_attribute("user.email", user_email)

        # Restricted share-link sessions (anonymous public agent chat) may only
        # invoke the shared-agent surface. Fail-closed: no handler ever sees a
        # restricted session for any other event.
        share_scope = session.get('share_scope') if session else None
        if share_scope is not None and event not in SHARED_VISITOR_ALLOWED_EVENTS:
            logger.warning(f"[ShareGate] Restricted session {sid} denied event '{event}'")
            return {"error": "permission_denied", "message": "This connection may only use shared-agent events"}

        sdk_permissions = session.get('sdk_permissions') if session else None
        if sdk_permissions is not None:
            from utils.sdk_permissions import check_sdk_permission
            # Extract workflow_id from request data for scope checking
            request_workflow_id = None
            if isinstance(data, dict):
                request_workflow_id = data.get('workflow_id')
            elif hasattr(data, 'workflow_id'):
                request_workflow_id = getattr(data, 'workflow_id', None)

            error = check_sdk_permission(
                event, sdk_permissions,
                sdk_workflow_id=session.get('sdk_workflow_id'),
                request_workflow_id=request_workflow_id,
            )
            if error:
                logger.warning(f"[SDK Permissions] Denied {event} for {sid}: {error}")
                return {"error": "permission_denied", "message": error}

        env_handlers = self.config.event_handlers.get(self.SOCKET_PROXY_ENV, {})

        # Check if event is in config
        if event not in env_handlers:
            logger.error(f"Event '{event}' not found in handlers for {self.SOCKET_PROXY_ENV}")
            return {"error": "unknown_event", "message": f"Unknown event: {event}"}
        
        # Validate frontend requests against their pydantic models
        validated_data = data
        if event in self.frontend_request_pydantic_models:
            try:
                model_class = self.frontend_request_pydantic_models[event]
                if event == "yjs:sync" and (isinstance(data, list) or isinstance(data, bytes)):
                    # yjs:sync can be a raw byte array or bytes - wrap it in expected format
                    validated_data = model_class.model_validate({"data": data})
                elif event == "yjs:sync" and isinstance(data, dict) and "data" not in data and data:
                    # Transitional shim: FE builds before 2026-07-19 spread the
                    # Uint8Array update into an indexed object ({'0': 0, ...},
                    # plus a _client_sent_at_ms stamp) — every collab sync frame
                    # failed validation. Reconstruct the byte array so tabs that
                    # haven't picked up the fixed bundle keep syncing. Remove
                    # once pre-fix sessions have aged out.
                    try:
                        byte_items = sorted(
                            ((int(k), v) for k, v in data.items() if k.isdigit()),
                            key=lambda kv: kv[0],
                        )
                        validated_data = model_class.model_validate(
                            {"data": bytes(v for _, v in byte_items)}
                        )
                    except (ValueError, TypeError) as e:
                        logger.error(f"Validation error for event '{event}': {e}")
                        return {"error": "validation_error", "message": str(e)}
                else:
                    validated_data = model_class.model_validate(data)
            except ValidationError as e:
                logger.error(f"Validation error for event '{event}': {e}")
                return {"error": "validation_error", "message": str(e)}

        # Set debug context for SQL query logging (allows database_pool to log queries per-user)
        debug_undo = await self._set_debug_context_for_sid(sid)

        try:
            # Route to handlers and collect results
            results = []
            for handler in env_handlers[event]:
                if handler is None:
                    logger.error(f"[RECEIVER] Handler is None for event {event} in {self.SOCKET_PROXY_ENV}")
                    continue

                event_handlers = handler.get_events()
                if event in event_handlers:
                    logger.debug(f"Calling handler for {event}: {handler.__class__.__name__}")
                    span.set_attribute("socket.handler", handler.__class__.__name__)
                    handler_start = time.perf_counter()
                    try:
                        result = await event_handlers[event](sid, validated_data)
                    finally:
                        duration_ms = (time.perf_counter() - handler_start) * 1000
                        span.set_attribute("socket.handler_duration_ms", duration_ms)
                        if duration_ms > HEAVY_THRESHOLD_MS:
                            self._last_heavy_completion[event] = time.monotonic()
                    results.append(result)
                else:
                    logger.warning(f"Handler {handler.__class__.__name__} doesn't have {event} in get_events()")
        finally:
            # Always reset debug context
            self._reset_debug_context(debug_undo)
        
        # Return single result if only one handler, otherwise return list
        final_result = results[0] if len(results) == 1 else results
        return final_result

    def _create_handler_instances(self):
        """
        This function instantiates all handlers separately because some of them
        depend on each other and it's tedious to define these dependencies in a
        configuration file to automate handler creation.
        """
         # Import handlers here to avoid circular imports
        from wss.handlers.agent_handler import AgentHandler
        from wss.handlers.ypy_handler import YPYHandler
        from wss.handlers.cache_valtio_handler import CacheValtioHandler
        from wss.handlers.usage_dashboard_handler import UsageDashboardHandler
        from wss.handlers.workflow_execution_handler import WorkflowExecutionHandler
        from wss.handlers.workflow_handler import WorkflowHandler
        from wss.handlers.workflow_mcp_handler import WorkflowMCPHandler
        from wss.handlers.credentials_handler import CredentialsHandler
        from wss.handlers.oauth import (
            GoogleOAuthHandler, AirtableOAuthHandler, AtlassianOAuthHandler, CanvaOAuthHandler,
            DiscordOAuthHandler, DropboxOAuthHandler, FacebookOAuthHandler, FathomOAuthHandler, ThreadsOAuthHandler, InstagramLoginOAuthHandler, FacebookPagesOAuthHandler, GithubOAuthHandler,
            HubSpotOAuthHandler, LinearOAuthHandler, QuickBooksOAuthHandler, CalendlyOAuthHandler, SentryOAuthHandler, PostHogOAuthHandler, CalComOAuthHandler, GitLabOAuthHandler, BoxOAuthHandler, AsanaOAuthHandler, MondayOAuthHandler, AttioOAuthHandler, IntercomOAuthHandler, PipedriveOAuthHandler, LinkedInOAuthHandler, ZendeskOAuthHandler, BambooHROAuthHandler, KlaviyoOAuthHandler, PagerDutyOAuthHandler, MailchimpOAuthHandler,
            MicrosoftOAuthHandler, NotionOAuthHandler, RedditOAuthHandler, SalesforceOAuthHandler,
            ShopifyOAuthHandler, SlackOAuthHandler, StripeOAuthHandler, TikTokOAuthHandler, TwitterOAuthHandler, TypeformOAuthHandler,
            WordPressOAuthHandler, MCPOAuthHandler, WhatsAppQRHandler, SupabaseOAuthHandler, ClickUpOAuthHandler,
            ParallelOAuthHandler, WebflowOAuthHandler, ZoomOAuthHandler, CloudflareOAuthHandler,
            ApolloOAuthHandler, MetaOAuthHandler,
        )
        from wss.handlers.saved_output_handler import SavedOutputHandler
        from wss.handlers.organization_handler import OrganizationHandler
        from wss.handlers.workflow_checkpoint_handler import WorkflowCheckpointHandler
        from wss.handlers.agent_share_handler import AgentShareHandler
        from wss.handlers.agent_workspace_handler import AgentWorkspaceHandler
        from wss.handlers.share_handler import ShareHandler
        from wss.handlers.onboarding_handler import OnboardingHandler
        from wss.handlers.notification_prefs_handler import NotificationPrefsHandler
        from wss.handlers.instance_oauth_handler import InstanceOAuthHandler
        from wss.handlers.feedback_handler import FeedbackHandler
        try:
            from wss.handlers.workflow_builder_handler import WorkflowBuilderHandler
        except ImportError:  # open build — AI builder is a cloud capability
            WorkflowBuilderHandler = None
        from wss.handlers.folder_handler import FolderHandler
        from wss.handlers.resource_handler import ResourceHandler
        from wss.handlers.skill_handler import SkillHandler
        from wss.handlers.feed_handler import FeedHandler
        from wss.handlers.oauth.codex_auth_handler import CodexAuthHandler
        from wss.handlers.oauth.claude_code_auth_handler import ClaudeCodeAuthHandler
        from .event_routing import Handler
        from .handler_registry import registered_handlers
        
        ypy_handler = YPYHandler(self.sio)
        # Initialize cache valtio handler for Redis persistence
        cache_valtio_handler = CacheValtioHandler(self.sio, ypy_handler) if self.SOCKET_PROXY_ENV == "API" else None
        agent_handler = AgentHandler(self.sio)
        # Initialize usage dashboard handler (API only)
        usage_dashboard_handler = UsageDashboardHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize workflow execution handler (API only)
        workflow_execution_handler = WorkflowExecutionHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize workflow handler (API only)
        workflow_handler = WorkflowHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize workflow MCP handler (API only - for AI agent workflow manipulation)
        workflow_mcp_handler = WorkflowMCPHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize credentials handler (API only)
        credentials_handler = CredentialsHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Google OAuth handler (API only)
        google_oauth_handler = GoogleOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Airtable OAuth handler (API only)
        airtable_oauth_handler = AirtableOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Stripe OAuth handler (API only)
        stripe_oauth_handler = StripeOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize GitHub OAuth handler (API only)
        github_oauth_handler = GithubOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Atlassian OAuth handler (API only)
        atlassian_oauth_handler = AtlassianOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Canva OAuth handler (API only)
        canva_oauth_handler = CanvaOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Discord OAuth handler (API only)
        discord_oauth_handler = DiscordOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Dropbox OAuth handler (API only)
        dropbox_oauth_handler = DropboxOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Facebook OAuth handler (API only)
        facebook_oauth_handler = FacebookOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        threads_oauth_handler = ThreadsOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        instagram_login_oauth_handler = InstagramLoginOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        facebook_pages_oauth_handler = FacebookPagesOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        meta_oauth_handler = MetaOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Fathom OAuth handler (API only)
        fathom_oauth_handler = FathomOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize HubSpot OAuth handler (API only)
        hubspot_oauth_handler = HubSpotOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Mailchimp OAuth handler (API only)
        mailchimp_oauth_handler = MailchimpOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Typeform OAuth handler (API only)
        typeform_oauth_handler = TypeformOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Supabase OAuth handler (API only)
        supabase_oauth_handler = SupabaseOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Zoom OAuth handler (API only)
        zoom_oauth_handler = ZoomOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Linear OAuth handler (API only)
        linear_oauth_handler = LinearOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize QuickBooks OAuth handler (API only)
        quickbooks_oauth_handler = QuickBooksOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        calendly_oauth_handler = CalendlyOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        sentry_oauth_handler = SentryOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        posthog_oauth_handler = PostHogOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Cal.com OAuth handler (API only)
        calcom_oauth_handler = CalComOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize GitLab OAuth handler (API only)
        gitlab_oauth_handler = GitLabOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Box OAuth handler (API only)
        box_oauth_handler = BoxOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Asana OAuth handler (API only)
        asana_oauth_handler = AsanaOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Monday OAuth handler (API only)
        monday_oauth_handler = MondayOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Attio OAuth handler (API only)
        attio_oauth_handler = AttioOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Intercom OAuth handler (API only)
        intercom_oauth_handler = IntercomOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Pipedrive OAuth handler (API only)
        pipedrive_oauth_handler = PipedriveOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize PagerDuty OAuth handler (API only)
        pagerduty_oauth_handler = PagerDutyOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Webflow OAuth handler (API only)
        webflow_oauth_handler = WebflowOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Cloudflare OAuth handler (API only)
        cloudflare_oauth_handler = CloudflareOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Apollo OAuth handler (API only)
        apollo_oauth_handler = ApolloOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize LinkedIn OAuth handler (API only)
        linkedin_oauth_handler = LinkedInOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize ClickUp OAuth handler (API only)
        clickup_oauth_handler = ClickUpOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Zendesk OAuth handler (API only)
        zendesk_oauth_handler = ZendeskOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        bamboohr_oauth_handler = BambooHROAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        klaviyo_oauth_handler = KlaviyoOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Microsoft OAuth handler (API only)
        microsoft_oauth_handler = MicrosoftOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Notion OAuth handler (API only)
        notion_oauth_handler = NotionOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Reddit OAuth handler (API only)
        reddit_oauth_handler = RedditOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Salesforce OAuth handler (API only)
        salesforce_oauth_handler = SalesforceOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Shopify OAuth handler (API only)
        shopify_oauth_handler = ShopifyOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Slack OAuth handler (API only)
        slack_oauth_handler = SlackOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize TikTok OAuth handler (API only)
        tiktok_oauth_handler = TikTokOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Twitter OAuth handler (API only)
        twitter_oauth_handler = TwitterOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize WordPress OAuth handler (API only)
        wordpress_oauth_handler = WordPressOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Parallel OAuth handler (API only)
        parallel_oauth_handler = ParallelOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize MCP OAuth handler (API only - for connecting to external MCP servers)
        mcp_oauth_handler = MCPOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize saved output handler (API only)
        saved_output_handler = SavedOutputHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize debug handler (API only - for query timing and performance metrics)
        # Initialize workflow checkpoint handler (API only - for version control)
        workflow_checkpoint_handler = WorkflowCheckpointHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Set global debug handler instance so other handlers can log queries
        # Initialize organization handler (API only)
        organization_handler = OrganizationHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize share handler (API only - for resource sharing)
        share_handler = ShareHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize agent share handler (API only - public agent chat links)
        agent_share_handler = AgentShareHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize agent workspace handler (API only - chat workspace file view)
        agent_workspace_handler = AgentWorkspaceHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize onboarding handler (API only - for user onboarding questionnaire)
        onboarding_handler = OnboardingHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize notification prefs handler (API only - system alert email opt-outs)
        notification_prefs_handler = NotificationPrefsHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        instance_oauth_handler = InstanceOAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize feedback handler (API only - in-app feedback / bug reports)
        feedback_handler = FeedbackHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize workflow builder handler (API only - for AI-powered workflow generation)
        workflow_builder_handler = WorkflowBuilderHandler(self.sio) if WorkflowBuilderHandler and self.SOCKET_PROXY_ENV == "API" else None
        # Initialize folder handler (API only)
        folder_handler = FolderHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize resource handler (API only - for workflow resources: datasets, blobs)
        resource_handler = ResourceHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize skill handler (API only - for agent-context skills)
        skill_handler = SkillHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None

        # Initialize setup execution handler (API only - guided template onboarding)
        # Initialize Codex device code auth handler (API only)
        codex_auth_handler = CodexAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize Claude Code OAuth PKCE auth handler (API only)
        claude_code_auth_handler = ClaudeCodeAuthHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize WhatsApp QR code auth handler (API only)
        whatsapp_qr_handler = WhatsAppQRHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None
        # Initialize feed handler (API only - approvals, activity logs, monitoring)
        feed_handler = FeedHandler(self.sio) if self.SOCKET_PROXY_ENV == "API" else None

        # Link usage_tracker with usage_dashboard_handler for cache invalidation
        if usage_dashboard_handler:
            from billing.usage_tracker import usage_tracker
            usage_tracker.usage_dashboard_handler = usage_dashboard_handler
            logger.info("[RECEIVER] Linked usage_tracker with UsageDashboardHandler for cache invalidation")
        
        # Create handler instance mapping
        return {
            Handler.AGENT: agent_handler,
            Handler.YPY: ypy_handler,

            Handler.CACHE_VALTIO: cache_valtio_handler,
            Handler.USAGE_DASHBOARD: usage_dashboard_handler,
            Handler.WORKFLOW_EXECUTION: workflow_execution_handler,
            Handler.WORKFLOW: workflow_handler,
            Handler.WORKFLOW_MCP: workflow_mcp_handler,
            Handler.CREDENTIALS: credentials_handler,
            Handler.GOOGLE_OAUTH: google_oauth_handler,
            Handler.AIRTABLE_OAUTH: airtable_oauth_handler,
            Handler.STRIPE_OAUTH: stripe_oauth_handler,
            Handler.GITHUB_OAUTH: github_oauth_handler,
            Handler.ATLASSIAN_OAUTH: atlassian_oauth_handler,
            Handler.CANVA_OAUTH: canva_oauth_handler,
            Handler.DISCORD_OAUTH: discord_oauth_handler,
            Handler.DROPBOX_OAUTH: dropbox_oauth_handler,
            Handler.FACEBOOK_OAUTH: facebook_oauth_handler,
            Handler.THREADS_OAUTH: threads_oauth_handler,
            Handler.INSTAGRAM_LOGIN_OAUTH: instagram_login_oauth_handler,
            Handler.FACEBOOK_PAGES_OAUTH: facebook_pages_oauth_handler,
            Handler.META_OAUTH: meta_oauth_handler,
            Handler.FATHOM_OAUTH: fathom_oauth_handler,
            Handler.HUBSPOT_OAUTH: hubspot_oauth_handler,
            Handler.MAILCHIMP_OAUTH: mailchimp_oauth_handler,
            Handler.TYPEFORM_OAUTH: typeform_oauth_handler,
            Handler.SUPABASE_OAUTH: supabase_oauth_handler,
            Handler.ZOOM_OAUTH: zoom_oauth_handler,
            Handler.LINEAR_OAUTH: linear_oauth_handler,
            Handler.QUICKBOOKS_OAUTH: quickbooks_oauth_handler,
            Handler.CALENDLY_OAUTH: calendly_oauth_handler,
            Handler.SENTRY_OAUTH: sentry_oauth_handler,
            Handler.POSTHOG_OAUTH: posthog_oauth_handler,
            Handler.CALCOM_OAUTH: calcom_oauth_handler,
            Handler.GITLAB_OAUTH: gitlab_oauth_handler,
            Handler.BOX_OAUTH: box_oauth_handler,
            Handler.ASANA_OAUTH: asana_oauth_handler,
            Handler.MONDAY_OAUTH: monday_oauth_handler,
            Handler.ATTIO_OAUTH: attio_oauth_handler,
            Handler.INTERCOM_OAUTH: intercom_oauth_handler,
            Handler.PIPEDRIVE_OAUTH: pipedrive_oauth_handler,
            Handler.PAGERDUTY_OAUTH: pagerduty_oauth_handler,
            Handler.WEBFLOW_OAUTH: webflow_oauth_handler,
            Handler.CLOUDFLARE_OAUTH: cloudflare_oauth_handler,
            Handler.APOLLO_OAUTH: apollo_oauth_handler,
            Handler.LINKEDIN_OAUTH: linkedin_oauth_handler,
            Handler.CLICKUP_OAUTH: clickup_oauth_handler,
            Handler.ZENDESK_OAUTH: zendesk_oauth_handler,
            Handler.BAMBOOHR_OAUTH: bamboohr_oauth_handler,
            Handler.KLAVIYO_OAUTH: klaviyo_oauth_handler,
            Handler.MICROSOFT_OAUTH: microsoft_oauth_handler,
            Handler.NOTION_OAUTH: notion_oauth_handler,
            Handler.REDDIT_OAUTH: reddit_oauth_handler,
            Handler.SALESFORCE_OAUTH: salesforce_oauth_handler,
            Handler.SHOPIFY_OAUTH: shopify_oauth_handler,
            Handler.SLACK_OAUTH: slack_oauth_handler,
            Handler.TIKTOK_OAUTH: tiktok_oauth_handler,
            Handler.TWITTER_OAUTH: twitter_oauth_handler,
            Handler.WORDPRESS_OAUTH: wordpress_oauth_handler,
            Handler.PARALLEL_OAUTH: parallel_oauth_handler,
            Handler.MCP_OAUTH: mcp_oauth_handler,
            Handler.SAVED_OUTPUT: saved_output_handler,
            Handler.ORGANIZATION: organization_handler,
            Handler.WORKFLOW_CHECKPOINT: workflow_checkpoint_handler,
            Handler.SHARE: share_handler,
            Handler.AGENT_SHARE: agent_share_handler,
            Handler.AGENT_WORKSPACE: agent_workspace_handler,
            Handler.ONBOARDING: onboarding_handler,
            Handler.NOTIFICATION_PREFS: notification_prefs_handler,
            Handler.INSTANCE_OAUTH: instance_oauth_handler,
            Handler.FEEDBACK: feedback_handler,
            Handler.WORKFLOW_BUILDER: workflow_builder_handler,
            Handler.FOLDER: folder_handler,
            Handler.RESOURCE: resource_handler,
            Handler.SKILL: skill_handler,
            Handler.CODEX_AUTH: codex_auth_handler,
            Handler.CLAUDE_CODE_AUTH: claude_code_auth_handler,
            Handler.WHATSAPP_QR: whatsapp_qr_handler,
            Handler.FEED: feed_handler,
            # Handlers the platform running this engine contributed. It
            # registered them before the receiver was built; nothing here knows
            # their names.
            **registered_handlers(self.sio),
        }

    
    def _build_event_handlers(self, handler_instances):
        """
        Essentially takes in EVENT_ROUTING and returns a dict of {env: {event: [handler]}}
        where the enums are replaces with actual instances.
                
        Args:
            handler_instances: Dict mapping Handler to handler instances
            event_routing: Dict of {env: {event: Handler}}

        Returns:
            Dict of {env: {event: [handler_instance]}}
        """
        from .event_routing import EVENT_ROUTING

        event_handlers = {}
        
        for env, event_map in EVENT_ROUTING.items():
            event_handlers[env] = {}
            
            for event, handler_enum in event_map.items():
                handler = handler_instances.get(handler_enum)
                
                if handler:
                    event_handlers[env][event] = [handler]
                else:
                    # Handler might be None if not initialized for this environment
                    if handler_enum not in handler_instances or handler_instances[handler_enum] is not None:
                        logger.warning(f"Handler {handler_enum.value} not found or not initialized for event {event} in env {env}")
        
        return event_handlers
    
    def _build_lifecycle_handlers(self, handler_instances):
        """
        Essentially takes in LIFECYCLE_HANDLERS and returns a dict of {env: [handler]}
        where the enums are replaces with actual instances.

        Args:
            handler_instances: Dict mapping Handler to handler instances

        Returns:
            Dict of {env: [handler_instance]}
        """
        from .event_routing import LIFECYCLE_HANDLERS

        # Build lifecycle handlers from configuration
        # Only include handlers that are actually instantiated (not None)
        lifecycle_handlers = {}
        for env, handler_enums in LIFECYCLE_HANDLERS.items():
            env_handlers = []
            for handler_enum in handler_enums:
                handler = handler_instances.get(handler_enum)
                if handler:  # Only add if handler was actually instantiated
                    env_handlers.append(handler)
            lifecycle_handlers[env] = env_handlers

        return lifecycle_handlers

    def _build_frontend_request_pydantic_models(self):
        """
        Creates a dict of {event_name: pydantic_model} for all requests that come from the frontend.
        Every time we receive a request from the frontend, we validate it against the event's pydantic model.
        """
        frontend_request_pydantic_models = {}
        for _, obj in inspect.getmembers(client_events, inspect.isclass):
            if issubclass(obj, ClientEventBase) and hasattr(obj, 'event_name'):
                # Skip the base class itself
                if obj is not ClientEventBase:
                    frontend_request_pydantic_models[obj.event_name] = obj

        assert len(frontend_request_pydantic_models) > 10, "Frontend request pydantic models not found"
        logger.info(f"Auto-discovered {len(frontend_request_pydantic_models)} event models: {list(frontend_request_pydantic_models.keys())}")
        return frontend_request_pydantic_models
        
    def _get_all_unique_handlers(self):
        """Get all unique handlers for the current environment.
        
        Returns:
            Set of unique handler instances
        """
        unique_handlers = set()
        
        # Add event handlers
        env_handlers = self.config.event_handlers.get(self.SOCKET_PROXY_ENV, {})
        for event_handlers in env_handlers.values():
            unique_handlers.update(event_handlers)
        
        # Add lifecycle handlers
        if self.SOCKET_PROXY_ENV in self.lifecycle_handlers:
            unique_handlers.update(self.lifecycle_handlers[self.SOCKET_PROXY_ENV])
        
        return unique_handlers
    
    async def _run_handler_method_for_all(self, sid: str, method_name: str, with_timing: bool = False, timing_threshold_ms: int = 50):
        """Concurrently run a specific method on all handlers for the current environment in an async way.
        
        Args:
            sid: Session ID
            method_name: Name of the method to call on each handler (e.g., 'setup_user', 'cleanup_user')
            with_timing: Whether to log timing information for each handler
            timing_threshold_ms: Threshold in milliseconds for performance warnings (default: 50ms)
        """
        handlers = self._get_all_unique_handlers()
        
        if not handlers:
            return
        
        # Create tasks for all handlers
        tasks = []
        handler_names = []
        
        for handler in handlers:
            method = getattr(handler, method_name, None)
            if method:
                tasks.append(method(sid))
                handler_names.append(handler.__class__.__name__)
        
        if not tasks:
            return
        
        if with_timing:
            
            # Create wrapper to time individual handlers
            async def timed_execution(task, handler_name):
                handler_start = time.perf_counter()
                result = await task
                handler_duration_ms = (time.perf_counter() - handler_start) * 1000
                if handler_duration_ms > timing_threshold_ms:
                    logger.error(f"Handler {handler_name} {method_name} took {handler_duration_ms:.1f}ms (>{timing_threshold_ms}ms limit) for sid {sid}")
                return result

            timed_tasks = [
                timed_execution(task, name)
                for task, name in zip(tasks, handler_names)
            ]
            await asyncio.gather(*timed_tasks)
        else:
            # Run all tasks without timing
            await asyncio.gather(*tasks)
    
    async def get_rate_limit_stats(self, sid: str) -> dict:
        """Get current rate limit usage statistics for a user."""
        return await self.rate_limiter.get_usage_stats(sid)

    def get_frontend_sids_for_user(self, user_id: str) -> list[str]:
        """
        Get all frontend session IDs for a user by user_id.

        This is used to broadcast events to all of a user's connected frontend sessions,
        for example when MCP operations via OAuth need to notify the frontend.

        Args:
            user_id: The user's ID

        Returns:
            List of frontend session IDs for this user.
            Empty list if user has no connected sessions.
        """
        return self._user_sessions.get(user_id, [])

    def get_frontend_sids_from_oauth_sid(self, oauth_sid: str) -> list[str]:
        """
        Get all frontend session IDs for the user from an OAuth virtual sid.

        OAuth sids have format "oauth:{user_id}". This extracts the user_id
        and returns all real Socket.IO sessions for that user.

        Args:
            oauth_sid: Virtual session ID in format "oauth:{user_id}"

        Returns:
            List of frontend session IDs for the user.
            Empty list if not an OAuth sid or user has no connected sessions.
        """
        if not oauth_sid.startswith("oauth:"):
            return []

        user_id = oauth_sid[6:]  # Extract user_id after "oauth:" prefix
        return self.get_frontend_sids_for_user(user_id)

    def get_connected_user_ids(self) -> list[str]:
        """
        Get all user IDs with active sessions on this backend instance.

        This is used for webhook registration to ensure only webhooks for
        currently connected users are registered with the relay.

        Returns:
            List of user IDs with at least one active session.
        """
        return list(self._user_sessions.keys())


# Global receiver instance for internal event routing
_receiver_instance = None

def get_receiver_instance():
    """Get the global receiver instance for internal event routing"""
    global _receiver_instance
    return _receiver_instance
