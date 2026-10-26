"""
Rate limit configurations for socket events.
Centralized location for all event rate limits to keep the receiver class clean.
"""

from wss.schema import SocketIORateLimit, SocketIORateLimitConfig


def get_rate_limit_config() -> SocketIORateLimitConfig:
    """
    Returns the rate limit configuration for all socket events.
    
    TODO: This configuration might need to be fetched over network
    for easier deployment and dynamic updates.
    Perhaps PostHog feature flags can be used here to keep limits configurable.
    """
    return SocketIORateLimitConfig(
        per_event_rate_limits={
            # YJS sync events
            "yjs:sync": SocketIORateLimit(second=50, minute=500),

            # Notification preference events
            "notifications:prefs:get": SocketIORateLimit(second=5, minute=30),
            "notifications:prefs:update": SocketIORateLimit(second=3, minute=20),

            # Verified phone identity (the service also caps sends per user and per number)
            "phone:status": SocketIORateLimit(second=5, minute=30),
            "phone:link:start": SocketIORateLimit(second=1, minute=5),
            "phone:link:check": SocketIORateLimit(second=2, minute=10),
            "phone:link:code": SocketIORateLimit(second=1, minute=10),
            "phone_number:coverage": SocketIORateLimit(second=2, minute=20),
            "phone_number:places": SocketIORateLimit(second=2, minute=30),
            "phone_number:search": SocketIORateLimit(second=2, minute=30),
            "phone_number:buy": SocketIORateLimit(second=1, minute=5),
            "phone_number:documents": SocketIORateLimit(second=2, minute=30),
            "phone_number:document_upload": SocketIORateLimit(second=2, minute=20),
            "phone_number:document_remove": SocketIORateLimit(second=2, minute=20),
            "phone_number:orders": SocketIORateLimit(second=2, minute=30),
            "phone_number:resubmit": SocketIORateLimit(second=1, minute=5),
            "phone:unlink": SocketIORateLimit(second=1, minute=5),

            # A live tab beats every 15s and withdraws on blur. The hook spaces its
            # claims, so focus flapping stays well inside this: a refused withdrawal
            # would leave a claim standing until it lapses.
            "presence:chat": SocketIORateLimit(second=4, minute=60),

            # Relay viewer tokens. A tab mints one per relay (re)connect and
            # retries a failed mint with backoff; presence mints one per
            # workflow it opens. Generous for real tabs, a wall for a loop.
            "relay:user_token": SocketIORateLimit(second=2, minute=20),
            "workflow:collab_token": SocketIORateLimit(second=5, minute=60),

            # Account coordinator (a send is one billed agent turn)
            "coordinator:open": SocketIORateLimit(second=5, minute=30),
            "coordinator:send": SocketIORateLimit(second=1, minute=12),
            "coordinator:attachment:upload_url": SocketIORateLimit(second=5, minute=60),
            "coordinator:attachments:list": SocketIORateLimit(second=5, minute=60),
            "coordinator:reset": SocketIORateLimit(second=1, minute=5),
            "coordinator:memories:list": SocketIORateLimit(second=5, minute=60),
            "coordinator:memories:get": SocketIORateLimit(second=5, minute=60),
            "coordinator:memories:save": SocketIORateLimit(second=2, minute=30),
            "coordinator:memories:delete": SocketIORateLimit(second=2, minute=30),
            "coordinator:jobs": SocketIORateLimit(second=5, minute=60),
            "coordinator:alarms": SocketIORateLimit(second=5, minute=60),
            "referral:get": SocketIORateLimit(second=2, minute=30),
            "coordinator:arrival": SocketIORateLimit(second=1, minute=10),
            "coordinator:email:ensure": SocketIORateLimit(second=2, minute=30),
            "coordinator:email:set": SocketIORateLimit(second=1, minute=10),
            "coordinator:email:inbound": SocketIORateLimit(second=1, minute=10),
            # Each followed operation opens a job whose end is a billed coordinator turn.
            "coordinator:platform:follow": SocketIORateLimit(second=1, minute=10),

            # Proving a credential works: each call is a real provider round
            # trip, so it is bounded well below a click-happy user.
            "credential:test_connection": SocketIORateLimit(second=2, minute=20),
            "rehearsal:scenarios": SocketIORateLimit(second=3, minute=30),
            # Creating things in someone's account: tighter than a read, because
            # a runaway client here leaves real artifacts behind.
            # A rehearsal is a real agent turn plus a model call per tool call.
            "rehearsal:run": SocketIORateLimit(second=1, minute=6),

            # In-app feedback / bug report
            "feedback:submit": SocketIORateLimit(second=2, minute=15),

            # Settings → Usage: the page re-reads at most every 5s while charges land;
            # Download CSV pages through every charge back to back.
            "usage:page": SocketIORateLimit(second=2, minute=30),
            "usage:charges": SocketIORateLimit(second=20, minute=600),
            # Settings → Plan and billing's monthly spending cap.
            "spend_cap:get": SocketIORateLimit(second=3, minute=30),
            "spend_cap:set": SocketIORateLimit(second=1, minute=10),

            # Organization operation events
            "organization:create": SocketIORateLimit(second=1, minute=1),
            "organization:get": SocketIORateLimit(second=5, minute=30),
            "organization:update": SocketIORateLimit(second=3, minute=3),
            "organization:delete": SocketIORateLimit(second=1, minute=3),
            "organization:list_mine": SocketIORateLimit(second=5, minute=30),
            "organization:switch": SocketIORateLimit(second=3, minute=20),
            "organization:upload_icon": SocketIORateLimit(second=2, minute=10),
            "organization:members:list": SocketIORateLimit(second=5, minute=30),
            "organization:members:invite": SocketIORateLimit(second=3, minute=20),
            "organization:members:remove": SocketIORateLimit(second=3, minute=20),
            "organization:members:update_role": SocketIORateLimit(second=3, minute=20),
            "organization:transfer_ownership": SocketIORateLimit(second=1, minute=3),
            "organization:invites:list": SocketIORateLimit(second=5, minute=30),
            "organization:invites:get": SocketIORateLimit(second=5, minute=30),
            "organization:invites:accept": SocketIORateLimit(second=3, minute=10),
            "organization:invites:revoke": SocketIORateLimit(second=3, minute=20),
            "organization:sso:configure": SocketIORateLimit(second=1, minute=5),
            "organization:sso:disable": SocketIORateLimit(second=1, minute=5),
            "organization:sso:info": SocketIORateLimit(second=5, minute=30),
            # Inline expression live-preview (debounced on the client; keystroke-rate)
            "workflow:node:evaluate_expression": SocketIORateLimit(second=10, minute=200),
            # Inbound-email trigger reservation events
            "email:check_local_part": SocketIORateLimit(second=5, minute=30),
            "email:reserve_address": SocketIORateLimit(second=3, minute=20),
            # Workflow checkpoint events (version control)
            "workflow:checkpoint:create": SocketIORateLimit(second=1, minute=2),
            "workflow:checkpoint:list": SocketIORateLimit(second=5, minute=30),
            "workflow:checkpoint:restore": SocketIORateLimit(second=2, minute=15),
            "workflow:checkpoint:delete": SocketIORateLimit(second=3, minute=20),

            # Workflow resource events
            "resource:create": SocketIORateLimit(second=5, minute=30),
            "resource:list": SocketIORateLimit(second=10, minute=60),
            "resource:get": SocketIORateLimit(second=10, minute=60),
            "resource:delete": SocketIORateLimit(second=5, minute=30),
            "resource:upload_url": SocketIORateLimit(second=5, minute=30),
            "resource:download_url": SocketIORateLimit(second=10, minute=60),
            "resource:dataset:rows": SocketIORateLimit(second=10, minute=60),
            "resource:dataset:append": SocketIORateLimit(second=5, minute=30),
            "resource:dataset:update_row": SocketIORateLimit(second=5, minute=30),
            "resource:dataset:delete_rows": SocketIORateLimit(second=5, minute=30),
            # Settings' list of published pages: one app read per page.
            "publish:list": SocketIORateLimit(second=3, minute=30),

            # Resource sharing invite-link events. accept is the redemption path
            # for an open token, so cap it to blunt token enumeration/abuse.
            "share:invite_link": SocketIORateLimit(second=2, minute=20),
            "share:invite_accept": SocketIORateLimit(second=2, minute=15),

            # Shared agent links. Visitor events run on anonymous sessions —
            # these per-sid limits blunt bursts only; real access control is
            # the restricted-session gate + the owner's credit gates.
            "agent_workspace:list": SocketIORateLimit(second=3, minute=40),
            "agent_workspace:delete": SocketIORateLimit(second=2, minute=30),
            "mcp_host:status": SocketIORateLimit(second=2, minute=40),
            "agent:builder_decision": SocketIORateLimit(second=3, minute=30),
            "workflow:builder:share_ask": SocketIORateLimit(second=2, minute=15),
            "agent_share:get_or_create": SocketIORateLimit(second=2, minute=15),
            "agent_share:rotate": SocketIORateLimit(second=1, minute=6),
            "agent_share:set_active": SocketIORateLimit(second=2, minute=15),
            "run_share:create": SocketIORateLimit(second=1, minute=10),
            "shared_agent:send": SocketIORateLimit(second=1, minute=6),
            "shared_agent:resume": SocketIORateLimit(second=2, minute=30),

            # Display-only credential metadata for a workflow's nodes (does a
            # check_resource_access + workflows SELECT + credentials JOIN per call).
            "credential:display_info": SocketIORateLimit(second=5, minute=60),
            "credential:authorize_for_workflow": SocketIORateLimit(second=10, minute=120),

            # Credential request events
            "credential:request:create": SocketIORateLimit(second=2, minute=10),
            "credential:request:list": SocketIORateLimit(second=5, minute=30),
            "credential:request:cancel": SocketIORateLimit(second=3, minute=15),

            # Setup flow events

            # Codex device code auth events
            "codex:auth:start": SocketIORateLimit(second=2, minute=10),
            "codex:auth:poll": SocketIORateLimit(second=2, minute=30),

            # Claude Code OAuth PKCE auth events
            "claude-code:auth:start": SocketIORateLimit(second=2, minute=10),
            "claude-code:auth:exchange": SocketIORateLimit(second=2, minute=10),

            # Approval feed events
            "approval:list": SocketIORateLimit(second=5, minute=30),
            "approval:respond": SocketIORateLimit(second=2, minute=20),

            # Dashboard tab
            "dashboard:overview": SocketIORateLimit(second=3, minute=30),
            "dashboard:attention": SocketIORateLimit(second=3, minute=30),
            "dashboard:notifications:read": SocketIORateLimit(second=3, minute=30),

            # Internal system events
        }
    )
