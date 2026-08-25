"""Accept authenticated in-app feedback and pass it to the configured
feedback persistence and notification service.
"""

import logging
from typing import Callable, Dict, Optional

from utils.database_pool import DatabasePoolMixin
from wss.schema import SocketIOHandler
from wss.sender import send_event
from wss.sender.events import ResponseEvent
from wss.receiver.client_events import SubmitFeedbackRequest

logger = logging.getLogger(__name__)


class FeedbackHandler(DatabasePoolMixin, SocketIOHandler):
    """Handler for user feedback / bug report submissions"""

    def __init__(self, sio):
        super().__init__(sio)

    def get_events(self) -> Dict[str, Callable]:
        """Register which events this handler processes"""
        return {
            "feedback:submit": self.handle_submit_feedback,
        }

    async def setup_user(self, sid: str) -> None:
        _ = sid

    async def handle_submit_feedback(self, sid: str, request: SubmitFeedbackRequest) -> None:
        """Persist a feedback submission to the user_feedback table"""
        try:
            session = await self.sio.get_session(sid)
            user_id = session.get('user_id')

            if not user_id:
                logger.error(f"[FeedbackHandler] No user_id in session for sid {sid}")
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=None,
                    error="Not authenticated"
                ))
                return

            message = (request.message or "").strip()
            if not message:
                await send_event(self.sio, sid, ResponseEvent(
                    request_id=request.request_id,
                    data=None,
                    error="Feedback message is empty"
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

            from utils.feedback import record_feedback

            await record_feedback(
                pool,
                user_id=user_id,
                feedback_type=request.feedback_type,
                message=message,
                page_url=request.page_url,
                metadata=request.metadata or {},
            )

            logger.info(f"[FeedbackHandler] Saved {request.feedback_type} feedback for user {user_id}")

            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data={'success': True}
            ))

        except Exception as e:
            logger.error(f"[FeedbackHandler] Error saving feedback: {e}")
            await send_event(self.sio, sid, ResponseEvent(
                request_id=request.request_id,
                data=None,
                error=str(e)
            ))

