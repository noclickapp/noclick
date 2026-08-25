import traceback
import asyncio
import logging
import y_py as Y
from functools import partial
from utils.ypy_utils import (
    SyncedState,
    read_message,
    create_message,
    create_sync_step2_message,
    create_update_message,
    YMessageType,
    YSyncMessageType,
)
from wss.schema import SocketIOHandler
from typing import Dict, Callable
from wss.sender import send_event, YjsSyncEvent
from wss.receiver.client_events import YjsSyncRequest

logger = logging.getLogger(__name__)

class YPYHandler(SocketIOHandler):
    def __init__(self, sio):
        self.sio = sio
        self.loop = None
        self.update_callbacks = {}  # Store callbacks for each sid

    def get_events(self) -> Dict[str, Callable]:
        return {
            "yjs:sync": self.handle_sync
        }

    async def setup_user(self, sid: str) -> None:
        self.loop = asyncio.get_event_loop()
        user_synced_state = SyncedState(loop=self.loop)
        user_synced_state["requests"] = {}

        # Attach the observer so that whenever the doc is changed,
        # we'll broadcast an update to other clients.
        user_synced_state.ydoc.observe_after_transaction(partial(self.on_update, sid))

        # Save the synced state to the session
        session = await self.sio.get_session(sid)
        session["synced_state"] = user_synced_state
        await self.sio.save_session(sid, session)
        
    def register_update_callback(self, sid: str, callback):
        """Register a callback function to be called after sync updates for a specific sid.
        
        Args:
            sid: The session ID to watch for updates
            callback: Async function to be called with (sid, ydoc) after updates
        """
        if sid not in self.update_callbacks:
            self.update_callbacks[sid] = []
        self.update_callbacks[sid].append(callback)

    def unregister_update_callbacks(self, sid: str):
        """Remove a previously registered callback for a specific sid."""
        if sid in self.update_callbacks:
            del self.update_callbacks[sid]

    async def _notify_callbacks(self, sid: str, state: SyncedState):
        """Notify all registered callbacks for a given sid."""
        if sid in self.update_callbacks:
            for callback in self.update_callbacks[sid]:
                try:
                    await callback(sid, state)
                except Exception as e:
                    logging.error(f"Error in update callback: {e}")
                    logging.error(traceback.format_exc())

    async def handle_sync(self, sid: str, yjs_sync_request: YjsSyncRequest):
        try:
            message_bytes = yjs_sync_request.data
            
            state = await YPYHandler.get_synced_state(self.sio, sid)
            
            if state is None:
                return

            # That means payload is empty
            if len(message_bytes) < 2:
                return  # Invalid message

            msg_type = message_bytes[0]
            sync_msg_type = message_bytes[1]
            payload = read_message(bytes(message_bytes[2:]))

            # If not a SYNC message (it could be an awareness message, which we're not using)
            if msg_type != YMessageType.SYNC:
                return

            if sync_msg_type == YSyncMessageType.SYNC_STEP1:
                # encode our state vector and reply with a sync2 message
                update = Y.encode_state_as_update(state.ydoc, payload)
                reply = create_sync_step2_message(update)
                event = YjsSyncEvent(data=reply)
                await send_event(self.sio, sid, event)

                # send our own sync1 message to the client now that we know it's alive
                await self.send_sync1(sid)

            elif sync_msg_type in (YSyncMessageType.SYNC_STEP2, YSyncMessageType.SYNC_UPDATE):
                # In both step2 and update, we apply the doc changes
                if payload not in (b"\x00\x00", b""):
                    Y.apply_update(state.ydoc, payload)
                    if sync_msg_type == YSyncMessageType.SYNC_UPDATE:
                        await self._notify_callbacks(sid, state)
        except Exception as e:
            logging.error(f"Error in yjs:sync handler: {e}")

    def on_update(self, sid: str, transaction_event: Y.AfterTransactionEvent):
        """
        Called automatically by y_py after a successful transaction. We broadcast
        a SYNC_UPDATE message to other clients so they can apply the doc changes.
        """
        try:
            update = create_update_message(transaction_event.get_update())
            # Create a task in the existing event loop instead of using run_until_complete
            event = YjsSyncEvent(data=update)
            from utils.async_helpers import spawn
            spawn(send_event(self.sio, sid, event), name=f"yjs-sync-broadcast:{sid}")
        except Exception as e:
            logging.error(f"on_update broadcast error: {e}")
            logging.error(traceback.format_exc())

    async def send_sync1(self, sid: str):
        state = await YPYHandler.get_synced_state(self.sio, sid)
        state_vector = Y.encode_state_vector(state.ydoc)
        sync_message = create_message(state_vector, YSyncMessageType.SYNC_STEP1)
        event = YjsSyncEvent(data=sync_message)
        await send_event(self.sio, sid, event)

    @staticmethod
    async def get_synced_state(sio, sid: str) -> SyncedState:
        """Get or create SyncedState for a user"""
        session = await sio.get_session(sid)
        return session.get("synced_state")
    
    async def cleanup_user(self, sid: str) -> None:
        """
        Cleanup is handled by consumers of YPYHandler (e.g., cache_valtio_handler.py)
        which call cleanup_synced_state() after ensuring state is persisted.
        This prevents premature cleanup before state can be saved.
        """
        # Intentionally empty - see cleanup_synced_state()
        pass
    
    async def cleanup_synced_state(self, sid: str) -> None:
        """
        Helper method to clean up YJS synced state for a user.
        Called by other handlers after they've finished with the state.
        
        Args:
            sid: Session ID of the user to clean up
        """
        # Always release the in-memory callback list first — it's local state
        # and must not leak even if the engine.io session is already gone.
        # The YDoc itself is GC'd implicitly once the session dict drops it;
        # y_py has no API to detach individual observers.
        self.unregister_update_callbacks(sid)

        try:
            session = await self.sio.get_session(sid)
        except KeyError as e:
            # Engine.io has already evicted the session (race with disconnect
            # cleanup). Nothing to clear from the session dict — callbacks are
            # already gone above, so this is a clean no-op.
            logger.debug(f"YJS cleanup: session {sid} already gone ({e.args[0]})")
            return
        except Exception as e:
            logger.error(f"Error cleaning up YJS state for {sid}: {e}")
            return

        if "synced_state" in session:
            del session["synced_state"]
            await self.sio.save_session(sid, session)
            logger.info(f"Cleaned up YJS state for session {sid}")
