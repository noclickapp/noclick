"""
Onboarding Handler

Handles saving onboarding questionnaire responses for new users and tracking
onboarding completion progress (checklist items, welcome experience, etc.).
After saving questionnaire, signals frontend to refresh JWT to get updated onboarding_completed claim.
"""

import logging
from typing import Any, Callable, Dict
from uuid import UUID

from utils.database_pool import DatabasePoolMixin
from utils.analytics import set_person_properties_background
from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent
from wss.receiver.client_events import (
    OnboardingSubmitRequest,
    OnboardingSkipRequest,
    OnboardingCompletionGetRequest,
    OnboardingCompletionUpdateRequest,
)

logger = logging.getLogger(__name__)


def deep_merge(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge updates into base dict, preserving nested structure"""
    result = base.copy()
    for key, value in updates.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class OnboardingHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for onboarding questionnaire and completion tracking operations"""

    def __init__(self, sio):
        """Initialize the OnboardingHandler"""
        super().__init__(sio)

    def get_events(self) -> Dict[str, Callable]:
        """Register which events this handler processes"""
        return {
            "onboarding:submit": self.handle_onboarding_submit,
            "onboarding:skip": self.handle_onboarding_skip,
            "onboarding:completion:get": self.handle_completion_get,
            "onboarding:completion:update": self.handle_completion_update,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def handle_onboarding_submit(self, sid: str, request: OnboardingSubmitRequest) -> None:
        """Save onboarding questionnaire responses"""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                logger.error(f"[OnboardingHandler] No user_id found in session for sid {sid}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=None,
                    error="Not authenticated"
                ))
                return

            responses = request.responses
            version = request.version

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=None,
                    error="Database connection not available"
                ))
                return

            async with pool.acquire() as conn:
                # Insert or update onboarding responses (upsert)
                await conn.execute("""
                    INSERT INTO user_onboarding_responses (user_id, responses, version)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id) DO UPDATE SET
                        responses = $2,
                        version = $3,
                        completed_at = NOW()
                """, UUID(user_id), responses, version)

            logger.info(f"[OnboardingHandler] Saved onboarding for user {user_id}")

            # Mirror persona answers to PostHog as person properties so the acquisition
            # funnel can be segmented by who the user is (role, build intent, org size).
            # DB stays the source of truth; this just makes the same data queryable
            # alongside campaign cohorts. set_once so a re-submit can't churn the segment.
            if isinstance(responses, dict) and responses:
                persona = {
                    f"onboarding_{k}": v
                    for k, v in responses.items()
                    if isinstance(v, (str, int, float, bool))
                }
                if persona:
                    set_person_properties_background(user_id, persona, set_once=True)

            # Send success response with flag to refresh JWT
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={
                    'success': True,
                    'refresh_jwt': True  # Signal to frontend to refresh JWT
                }
            ))

        except Exception as e:
            logger.error(f"[OnboardingHandler] Error saving onboarding: {e}")
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=None,
                error=str(e)
            ))

    async def handle_onboarding_skip(self, sid: str, request: OnboardingSkipRequest) -> None:
        """Persist an onboarding skip for scaffold / agent-SEO arrivals.

        These users are routed straight into a pre-built workflow instead of the
        questionnaire. Without a durable server-side mark, `onboarding_completed`
        (derived from the presence of a `user_onboarding_responses` row) stays
        false and the questionnaire re-appears on the next dashboard remount.
        Insert a synthetic row (DO NOTHING so a real prior submission is never
        clobbered) and signal a JWT refresh so the flipped claim propagates.
        Mirrors the invite-join onboarding write in repositories/share.py.
        """
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                logger.error(f"[OnboardingHandler] No user_id found in session for sid {sid}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=None,
                    error="Not authenticated"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=None,
                    error="Database connection not available"
                ))
                return

            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    INSERT INTO user_onboarding_responses (user_id, responses, version)
                    VALUES ($1, $2::jsonb, 1)
                    ON CONFLICT (user_id) DO NOTHING
                    RETURNING id
                """, UUID(user_id), {"skipped": True, "source": request.source})

            # `row` is None when a real (or prior skip) row already existed — the
            # claim is already true, so a refresh is only needed when we inserted.
            inserted = row is not None
            logger.info(
                f"[OnboardingHandler] Onboarding skip for user {user_id} "
                f"(source={request.source}, inserted={inserted})"
            )

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={'success': True, 'refresh_jwt': inserted}
            ))

        except Exception as e:
            logger.error(f"[OnboardingHandler] Error skipping onboarding: {e}")
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=None,
                error=str(e)
            ))

    async def handle_completion_get(self, sid: str, request: OnboardingCompletionGetRequest) -> None:
        """Get user's onboarding completion state"""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                logger.error(f"[OnboardingHandler] No user_id found in session for sid {sid}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=None,
                    error="Not authenticated"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=None,
                    error="Database connection not available"
                ))
                return

            async with pool.acquire() as conn:
                row = await conn.fetchrow("""
                    SELECT data FROM user_onboarding_completion
                    WHERE user_id = $1
                """, UUID(user_id))

                if row:
                    data = row['data']
                else:
                    # Lazy init if not found (shouldn't happen with trigger, but handle gracefully)
                    default_data = {
                        "workflow_checklist": {
                            "create_workflow": False,
                            "open_flow_helper": False,
                            "drag_node": False,
                            "configure_node": False,
                            "open_sidebar_chat": False,
                            "join_discord": False,
                        },
                        "has_seen_welcome": False,
                        "checklist_dismissed": False
                    }
                    await conn.execute("""
                        INSERT INTO user_onboarding_completion (user_id, data)
                        VALUES ($1, $2)
                        ON CONFLICT (user_id) DO NOTHING
                    """, UUID(user_id), default_data)
                    data = default_data

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={'completion': data}
            ))

        except Exception as e:
            logger.error(f"[OnboardingHandler] Error getting completion: {e}")
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=None,
                error=str(e)
            ))

    async def handle_completion_update(self, sid: str, request: OnboardingCompletionUpdateRequest) -> None:
        """Update user's onboarding completion state (deep merge)"""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                logger.error(f"[OnboardingHandler] No user_id found in session for sid {sid}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=None,
                    error="Not authenticated"
                ))
                return

            pool = await self.get_pool()
            if not pool:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=None,
                    error="Database connection not available"
                ))
                return

            async with pool.acquire() as conn:
                # Get current data
                row = await conn.fetchrow("""
                    SELECT data FROM user_onboarding_completion
                    WHERE user_id = $1
                """, UUID(user_id))

                if row:
                    current_data = row['data']
                else:
                    # Initialize with defaults if not found
                    current_data = {
                        "workflow_checklist": {
                            "create_workflow": False,
                            "open_flow_helper": False,
                            "drag_node": False,
                            "configure_node": False,
                            "open_sidebar_chat": False,
                            "join_discord": False,
                        },
                        "has_seen_welcome": False,
                        "checklist_dismissed": False
                    }

                # Deep merge updates
                merged_data = deep_merge(current_data, request.data)

                # Upsert the merged data
                await conn.execute("""
                    INSERT INTO user_onboarding_completion (user_id, data)
                    VALUES ($1, $2)
                    ON CONFLICT (user_id) DO UPDATE SET
                        data = $2,
                        updated_at = NOW()
                """, UUID(user_id), merged_data)

            logger.info(f"[OnboardingHandler] Updated completion for user {user_id}")

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={'success': True, 'completion': merged_data}
            ))

        except Exception as e:
            logger.error(f"[OnboardingHandler] Error updating completion: {e}")
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=None,
                error=str(e)
            ))
