"""NoClick self-hosted backend application assembly.

Builds one ASGI app for Socket.IO, REST, MCP, and webhook traffic. Run
directly with `python server.py` or `uvicorn server:web_app`.
"""
import os
import tracemalloc
if os.getenv("TRACEMALLOC") == "1":
    tracemalloc.start()


def _run_configured_bootstrap() -> None:
    """Let a deployment register its own backends and routes before anything is
    built, without this file knowing what they are.

    `NOCLICK_BOOTSTRAP=package.module:function` names a callable; it runs once,
    here, ahead of every seam lookup and the app assembly below. Unset — a plain
    install — is the normal case and does nothing.

    The name lives in the environment rather than in this file on purpose: the
    engine ships publicly and must not carry the module names of whatever is
    deploying it. A hosted entry point that imports this module directly can
    call its bootstrap itself and leave this unset.
    """
    target = (os.getenv("NOCLICK_BOOTSTRAP") or "").strip()
    if not target:
        return
    module_name, _, attribute = target.partition(":")
    if not module_name or not attribute:
        raise RuntimeError(
            f"NOCLICK_BOOTSTRAP must look like 'module:function', got {target!r}"
        )
    import importlib

    # Deliberately unguarded: a deployment that asked for a bootstrap and did
    # not get one is misconfigured, and starting anyway would serve a system
    # that is quietly missing whatever the bootstrap was for.
    getattr(importlib.import_module(module_name), attribute)()


_run_configured_bootstrap()

# Boot-time patches that must run before any module that might trigger the
# patched code path. Each module's docstring explains the why. Order matters
# — keep these three at the very top.
import utils.fork_safety_env       # noqa: F401 — macOS proxy_bypass / Obj-C fork safety (subprocesses we spawn for tooling)
import utils.ws_compression_patch  # noqa: F401 — kills permessage_deflate on the send path

# No multiprocessing.set_start_method() needed: builder/execute workloads
# run inline on the asyncio loop. JS execution routes through a dedicated
# thread pool in utils.threaded_executors. The forkserver model was deleted
# in the inline-async refactor.

import asyncio
import logging
import threading
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
import socketio
import jwt
# Import clients with expensive module initialization before the event loop
# exists, so the first request cannot synchronously pay that cost.
import utils.r2_cloudflare  # noqa: F401
import nodes.agent.handlers.llm  # noqa: F401
from socketio.exceptions import ConnectionRefusedError as SocketIOConnectionError
from utils.auth import verify_socket_token
from utils.slack import (
    login_notifications_enabled,
    mark_session_complete,
    send_login_notification,
)
from utils.geo import extract_client_ip
from utils.edition import is_local_edition
from dotenv import load_dotenv
from utils.otel import init_otel, shutdown_otel
from utils.otel_health import start_health_emitter, stop_health_emitter
from utils.otel_loop_monitor import init_loop_monitor
# Telemetry workers start inside the lifespan so importing the app stays
# side-effect-free for tests and tooling.
from wss.receiver import SocketIOProxy
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor


# Configure logging to show INFO level messages
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

ORIGINS = [
    "http://localhost:3000",
    *[f"http://localhost:{port}" for port in range(5173, 5191)],
    "https://noclick.com",
    "https://www.noclick.com",
    # MCP client origins (needed for OAuth flow + widget communication)
    "https://chatgpt.com",
    "https://claude.ai",
    # ngrok tunnels for local dev testing
    "https://example.ngrok-free.dev",
]


def _origin_aliases(url: str) -> list:
    """The origin plus its loopback spelling. A browser sends the origin exactly
    as typed, so an install configured as 127.0.0.1 still fails CORS when its
    operator visits localhost (and vice versa)."""
    origin = url.strip().rstrip("/")
    if not origin:
        return []
    aliases = {origin}
    if "//localhost" in origin:
        aliases.add(origin.replace("//localhost", "//127.0.0.1"))
    elif "//127.0.0.1" in origin:
        aliases.add(origin.replace("//127.0.0.1", "//localhost"))
    return sorted(aliases)


# A self-hosted install may add another port, LAN address, or domain.
ORIGINS.extend(a for a in _origin_aliases(os.environ.get("FRONTEND_URL", ""))
               if a not in ORIGINS)
for configured_origin in os.environ.get("SOCKET_CORS_ORIGINS", "").split(","):
    ORIGINS.extend(
        alias for alias in _origin_aliases(configured_origin)
        if alias not in ORIGINS
    )

# Create Socket.IO with the explicit application/operator origin allowlist.
# Authentication is still enforced in the connect handler.
sio = socketio.AsyncServer(
    async_mode='asgi',
    transports=['websocket', 'polling'],
    cors_allowed_origins=ORIGINS,
    # python-engineio expresses heartbeat settings in seconds, not milliseconds.
    ping_timeout=20,
    ping_interval=25,
    # If seeing random socket disconnection loops, try increasing this limit
    max_http_buffer_size=10_000_000,  # 10MB limit for YJS sync messages (default is 1MB)
    logger=False,
    engineio_logger=False,
    cookie="io"
)

# Expose the shared server to stateless HTTP routes that have no request
# socket of their own.
from utils.socket_singleton import set_sio
set_sio(sio)

socketio_proxy = SocketIOProxy(sio)

# Create MCP server for external clients (Claude Code, Cursor)
from mcp_server import NoClickMCPServer, set_mcp_server
mcp_server = NoClickMCPServer(sio)
set_mcp_server(mcp_server)


# Create custom lifespan for startup/shutdown hooks
@asynccontextmanager
async def app_lifespan(app: FastAPI):
    """Initialize and cleanly stop self-hosted application resources."""

    # Thread-spawning inits run here in lifespan rather than at import time
    # so module imports stay side-effect-free for tests/tooling.
    init_otel()  # spawns BatchSpanProcessor thread
    init_loop_monitor(asyncio.get_running_loop())  # captures main thread id (the loop-monitor regression pattern pattern)

    # Native asyncpg pool on the main event loop. Must precede handler
    # instantiation below: setup_user() on some handlers hits the DB on the
    # first user connect, and rejecting a request with "pool not
    # initialized" would be worse than the startup-order bug it'd surface.
    from utils.database_pool import init_native_pool
    await init_native_pool()

    # Self-hosted OAuth apps configured through Settings live in the database;
    # copy them into the environment (never over a real env var) so every
    # get_<provider>_client_config() reads them without knowing they exist.
    if is_local_edition():
        from utils.database_pool import get_native_pool
        from utils.instance_oauth import apply_to_environment

        try:
            await apply_to_environment(get_native_pool())
        except Exception as e:
            # A missing table on an un-migrated install must not stop boot; the
            # providers simply stay unconfigured and the setup page says so.
            logger.warning(f"[InstanceOAuth] could not apply stored apps: {e}")

    # Instantiate and register the WebSocket handler singletons before the
    # server begins accepting connections.
    await socketio_proxy.setup()

    # Start MCP server lifespan (initializes StreamableHTTPSessionManager)
    await mcp_server.startup()

    # Local edition: in-process cron ticker replaces the Cloudflare scheduler
    # (the /local-cron REST API is mounted at module level; the ticker fires due rows).
    from utils.edition import is_local_edition as _is_local
    if _is_local():
        from utils.local_cron import start_local_cron
        start_local_cron()

    # Start container-health emitter for OTel/Honeycomb (3s cadence)
    start_health_emitter(interval_seconds=3.0)


    yield

    # Ask in-flight builder work to stop cooperatively before shared
    # transports and the database pool are closed.
    try:
        from utils.cancellation import cancel_all_builder_scopes
        drained = cancel_all_builder_scopes()
        if drained:
            logger.info(f"[shutdown] drain-cancelled {drained} in-flight builder run(s)")
    except Exception as e:
        logger.warning(f"[shutdown] builder drain-cancel failed: {e}")

    # Stop the lifespan-owned tracked loop, then give one-shot background work
    # (CAS persistence, notifications, analytics) a bounded chance to finish
    # while the DB pool and HTTP clients are still usable.
    try:
        from utils.async_helpers import drain_spawned_tasks
        completed, cancelled = await drain_spawned_tasks(timeout=2)
        if completed or cancelled:
            logger.info(
                "[shutdown] background tasks completed=%d cancelled=%d",
                completed,
                cancelled,
            )
    except Exception as e:
        logger.warning(f"Background task drain failed: {e}")

    if _is_local():
        from utils.local_cron import stop_local_cron
        await stop_local_cron()

    # Shutdown with timeouts so hot-reload doesn't hang
    try:
        await asyncio.wait_for(mcp_server.shutdown(), timeout=3)
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(f"MCP server shutdown timed out or failed: {e}")

    try:
        await asyncio.wait_for(stop_health_emitter(), timeout=2)
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(f"Health emitter shutdown timed out or failed: {e}")

    # Close the native DB pool last among the async shutdowns — anything
    # cancelled above may want a final DB write on the way out.
    try:
        from utils.database_pool import close_native_pool
        await asyncio.wait_for(close_native_pool(), timeout=3)
    except (asyncio.TimeoutError, Exception) as e:
        logger.warning(f"Native DB pool shutdown timed out or failed: {e}")

    shutdown_otel()

fastapi_app = FastAPI(lifespan=app_lifespan)
FastAPIInstrumentor.instrument_app(fastapi_app)
HTTPXClientInstrumentor().instrument()
# LiteLLM's streaming completion path uses aiohttp, not httpx; both client
# instrumentors are needed to capture all outbound LLM/API traffic.
AioHttpClientInstrumentor().instrument()
# asyncpg: per-query spans for DB-latency attribution. Must run before the
# first pool is created so the monkey-patch is in place on every connection.
# DatabasePoolMixin._db lazy-property defers pool creation until first request,
# so module-top init here is comfortably ahead of it.
AsyncPGInstrumentor().instrument()

# Add CORS middleware
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Webhook and inbound-email traffic share the self-hosted API process.
from utils.webhook_routes import router as webhook_router
from utils.supabase_webhook_routes import router as supabase_webhook_router
from utils.email_routes import router as email_router
fastapi_app.include_router(webhook_router)
fastapi_app.include_router(supabase_webhook_router)
fastapi_app.include_router(email_router)

# Register public routes for unauthenticated access to shared resources
from utils.public_routes import router as public_router
fastapi_app.include_router(public_router)

# Frontend telemetry ingest — accepts wide events from the browser and emits
# one OTel span per event for Honeycomb (latency, disconnect lifecycle, etc.).

# Register model catalog endpoint (unified OpenRouter + LiteLLM + static list)
from utils.models_routes import router as models_router
fastapi_app.include_router(models_router)

# Register credential request routes for external credential provision
from utils.credential_request_routes import router as credential_request_router
fastapi_app.include_router(credential_request_router)

# Builder input bridge: public bearer-capability links let a recipient answer
# a parked builder run without creating an account. The link is scoped, expires,
# and is consumed once; the community builder includes this route explicitly.
from utils.builder_bridge_routes import router as builder_bridge_router
fastapi_app.include_router(builder_bridge_router)

# Agent workspace files (/agent/workspace/file) — signed streamed reads off a
# conversation's workspace volume for the chat's file view.
from utils.agent_workspace_routes import router as agent_workspace_router
fastapi_app.include_router(agent_workspace_router)

# Register health check routes for monitoring services
from utils.health_routes import router as health_router, well_known_router
fastapi_app.include_router(health_router)
fastapi_app.include_router(well_known_router)

# Register API key management routes
from utils.api_key_routes import router as api_key_router
fastapi_app.include_router(api_key_router)


# Routes contributed by the platform running this engine, if any. It registered
# them before the engine was imported; the engine does not know their names.
from utils.route_registry import apply_registered_routes  # noqa: E402

apply_registered_routes(fastapi_app, sio)

# Local edition: serve the event-relay WebSocket protocols in-process so the
# browser's relay clients (VITE_RELAY_URL → ws://<backend>/relay) work without
# the external relay services.
if is_local_edition():
    from utils.local_relay_routes import router as local_relay_router
    from utils.local_cron import router as local_cron_router
    fastapi_app.include_router(local_relay_router)
    fastapi_app.include_router(local_cron_router)
    logger.info("[local] mounted in-process event relay (/relay) + cron scheduler (/local-cron)")

# Local-harness tool endpoint (/local-agent-mcp/{token}): turn-scoped MCP
# server for subprocess CLI agents. Token-capability gated; inert unless the
# local harness runner mints a turn-scoped session.
from nodes.agent.local_harness import router as local_harness_router
fastapi_app.include_router(local_harness_router)

# Register MCP OAuth routes (discovery, registration, authorization, token exchange)
fastapi_app.include_router(mcp_server.get_oauth_router())

# Mount Socket.IO to FastAPI, with MCP auth middleware wrapping the FastAPI app
web_app = socketio.ASGIApp(
    socketio_server=sio,
    other_asgi_app=mcp_server.create_asgi_middleware(fastapi_app),
    socketio_path='/socket.io/'
)

def _sanitize_auth_reason(raw_message: str, default: str = 'Authentication failed', code: str = 'auth_failed') -> dict:
    """Build a limited payload summarizing why authentication was refused."""
    message = (raw_message or '').strip()
    prefix = 'Authentication failed:'
    if message.lower().startswith(prefix.lower()):
        message = message[len(prefix):].strip()
    payload = {'message': default, 'code': code}
    if message:
        payload['reason'] = message
    return payload


@sio.event
async def connect(sid, environ, auth):
    """Handle client connection with authentication"""
    try:
        if not auth:
            raise SocketIOConnectionError({'message': 'Authentication required', 'code': 'missing_auth'})

        # --- API Key auth (external SDK connections) ---
        if 'api_key' in auth:
            from utils.api_keys import validate_api_key
            from utils.database_pool import get_native_pool
            async with get_native_pool().acquire() as conn:
                key_info = await validate_api_key(conn, auth['api_key'])
            if not key_info:
                raise SocketIOConnectionError({'message': 'Invalid or expired API key', 'code': 'invalid_api_key'})

            session_data = {
                'user_id': key_info['user_id'],
                'user_data': {'email': f'sdk:{key_info["key_id"][:8]}'},
                'sdk_key_id': key_info['key_id'],
                'sdk_workflow_id': key_info.get('workflow_id'),
                'sdk_permissions': key_info.get('permissions', []),
            }

            await sio.save_session(sid, session_data)
            await socketio_proxy.setup_user(sid)
            from wss.sender import mark_sdk_client
            mark_sdk_client(sid, key_info.get('workflow_id'))
            logger.info(
                "SDK client connected: %s (key_id: %s)",
                sid,
                key_info["key_id"],
            )
            return True

        # --- Anonymous share-link auth (public agent chat page) ---
        # Restricted session: carries share_scope but deliberately NO user_id,
        # so every handler treats it as unauthenticated. The receiver's
        # restricted-session gate limits it to the shared_agent:* events.
        if 'share_link_id' in auth:
            import uuid as uuid_module

            from repositories.shared_agent_link import SharedAgentLinkRepo
            from utils.database_pool import get_native_pool

            link = await SharedAgentLinkRepo(get_native_pool()).load_for_visit(
                str(auth['share_link_id'])
            )
            if not link:
                raise SocketIOConnectionError({'message': 'Share link not found or inactive', 'code': 'invalid_share_link'})
            try:
                visitor_id = str(uuid_module.UUID(str(auth.get('visitor_id'))))
            except (ValueError, TypeError):
                raise SocketIOConnectionError({'message': 'Invalid visitor id', 'code': 'invalid_visitor_id'})

            await sio.save_session(sid, {
                'share_scope': {
                    'link_id': str(link['id']),
                    'workflow_id': str(link['workflow_id']),
                    'node_id': link['node_id'],
                    'owner_id': str(link['user_id']),
                    'organization_id': str(link['organization_id']) if link['organization_id'] else None,
                    'visitor_id': visitor_id,
                },
            })
            await socketio_proxy.setup_user(sid)  # no-ops without user_id
            logger.info(f"Share-link visitor connected: {sid} (link: {str(link['id'])[:8]}...)")
            return True

        # --- Token auth (browser frontend connections) ---
        # The FE sends the Supabase access token from getSession(); identity is
        # the verified JWT's sub (docs/auth-refactor-spec.md). The raw
        # document.cookie payload was retired 2026-07-17 — stale bundles get
        # missing_auth and recover on reload.
        token = auth.get('token')
        if not token:
            raise SocketIOConnectionError({'message': 'Authentication token or API key required', 'code': 'missing_auth'})

        try:
            user_id, user_data = await verify_socket_token(token)
        except jwt.ExpiredSignatureError as expiry_error:
            # Recoverable: the client refreshes its session and reconnects.
            payload = _sanitize_auth_reason(
                str(expiry_error),
                default='Access token expired',
                code='token_expired'
            )
            logger.info(f"Authentication rejected for {sid}: token expired")
            raise SocketIOConnectionError(payload) from expiry_error
        except jwt.InvalidTokenError as verification_error:
            payload = _sanitize_auth_reason(
                str(verification_error),
                default='Token verification failed',
                code='token_invalid'
            )
            logger.warning(f"Authentication rejected for {sid}: {payload.get('reason', payload['message'])}")
            raise SocketIOConnectionError(payload) from verification_error

        # Login notifications are an operator opt-in. Gate before even
        # extracting the address so a default self-hosted login cannot trigger
        # geo-IP work or log proxy/client address headers.
        slack_result = None
        if login_notifications_enabled():
            client_ip = extract_client_ip(environ)
            slack_result = await send_login_notification(user_id, user_data, client_ip)
        slack_thread_ts = slack_result.get('ts') if slack_result else None
        slack_channel = slack_result.get('channel') if slack_result else None

        # Store user info in socket session (including slack thread for replies)
        session_data = {
            'user_id': user_id,
            'user_data': user_data,
            'slack_thread_ts': slack_thread_ts,  # Thread for activity notifications
            'slack_channel': slack_channel,  # Channel where login was posted
        }

        await sio.save_session(sid, session_data)

        await socketio_proxy.setup_user(sid)

        logger.info(f"Client authenticated and connected: {sid} (user_id: {session_data['user_id']}, pid={os.getpid()})")
        return True

    except SocketIOConnectionError:
        raise
    except ValueError as auth_error:
        payload = _sanitize_auth_reason(str(auth_error))
        logger.warning(f"Authentication rejected for {sid}: {payload.get('reason', payload['message'])}")
        raise SocketIOConnectionError(payload) from auth_error
    except Exception as e:
        logger.error(f"Authentication failed for {sid}: {str(e)}")
        logger.error(f"Formatted Traceback: {traceback.format_exc()}")
        raise SocketIOConnectionError({'message': 'Authentication failed', 'detail': 'internal_error'}) from e

@sio.event
async def disconnect(sid):
    """Handle client disconnection.

    Session data is read synchronously (before python-socketio clears it),
    then the heavy cleanup (webhook unregistration, Slack API calls) is
    fire-and-forget so uvicorn's hot-reload doesn't hang.
    """
    # Read session NOW — python-socketio clears it as soon as this handler returns
    try:
        session = await sio.get_session(sid)
    except KeyError:
        session = None

    slack_thread_ts = session.get('slack_thread_ts') if session else None
    slack_channel = session.get('slack_channel') if session else None

    async def _cleanup():
        try:
            await socketio_proxy.cleanup_user(sid)

            if slack_thread_ts and slack_channel:
                await mark_session_complete(slack_channel, slack_thread_ts)

            logger.info(f"Client disconnected: {sid}")
        except Exception as e:
            logger.error(f"Error in disconnect handler: {str(e)}")
            logger.error(f"Formatted Traceback: {traceback.format_exc()}")

    from utils.async_helpers import spawn
    spawn(_cleanup(), name=f"socket-disconnect-cleanup:{sid}")

@sio.event
async def update_auth(sid, data):
    """Handle authentication update when frontend token refreshes"""
    try:
        # Restricted share-link sessions must never graft cookie auth onto
        # themselves — this raw @sio.event bypasses the receiver's gate.
        try:
            existing = await sio.get_session(sid)
        except KeyError:
            existing = None
        if existing and existing.get('share_scope'):
            logger.warning(f"update_auth rejected for restricted share session {sid}")
            return {'success': False, 'error': 'Not available on shared sessions'}

        if not data or not data.get('token'):
            logger.warning(f"update_auth called without token for {sid}")
            return {'success': False, 'error': 'No token provided'}

        # Verify the refreshed access token (identity = verified sub)
        user_id, user_data = await verify_socket_token(data['token'])

        # Get current session
        session = await sio.get_session(sid)
        if not session:
            logger.error(f"No session found for {sid} during auth update")
            return {'success': False, 'error': 'Session not found'}

        # A token for a DIFFERENT user must never graft onto this session —
        # update_auth deliberately never rewrites user_id. During mimic the
        # session's user_id is the impersonated target, so compare against the
        # admin's real id when present.
        expected_user_id = str(session.get('real_user_id') or session.get('user_id') or '')
        if expected_user_id and expected_user_id != user_id:
            logger.warning(f"update_auth user mismatch for {sid}")
            return {'success': False, 'error': 'Token user mismatch'}

        session['user_data'] = user_data  # Update user data in case it changed
        await sio.save_session(sid, session)

        logger.info(f"Auth updated successfully for {sid} (user_id: {user_id})")
        return {'success': True, 'message': 'Authentication updated'}

    except Exception as e:
        logger.error(f"Failed to update auth for {sid}: {str(e)}")
        logger.error(f"Formatted Traceback: {traceback.format_exc()}")
        return {'success': False, 'error': 'Authentication update failed'}


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")), help="Port to run on")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host to bind to")
    args, _ = parser.parse_known_args()

    uvicorn.run(
        "server:web_app",
        host=args.host,
        port=args.port,
        reload=True,
        log_level="info",
    )
