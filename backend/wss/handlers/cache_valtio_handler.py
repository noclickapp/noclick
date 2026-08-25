"""
Handler for persisting and restoring YJS cachedb state to/from Redis.
Provides automatic state persistence with 60-second debouncing and restoration on connect.

Multi-device/tab support: Timestamps are stored with each cache entry. The frontend performs
selective merge on cache restoration, comparing IndexedDB timestamps with remote cache timestamp
to prevent stale data from overwriting recent changes.
"""

import os
import asyncio
import logging
import time
import redis.asyncio as redis
import y_py as Y
from typing import Optional
from wss.schema import SocketIOHandler
from wss.sender import send_event, CacheValtioStateEvent
from wss.handlers.ypy_handler import YPYHandler
from utils.ypy_utils import SyncedState

logger = logging.getLogger(__name__)


class CacheValtioHandler(SocketIOHandler):
    """
    Lifecycle handler that manages Redis persistence of YJS cachedb state.
    - Automatically restores state on user connection
    - Saves state changes with 60-second debouncing
    - Ensures final save on disconnect
    """
    
    def __init__(self, sio, ypy_handler: YPYHandler):
        super().__init__(sio)
        self.ypy_handler = ypy_handler
        self.redis_client = None
        self.pending_uploads = {}  # sid -> asyncio.Task
        self.upload_timers = {}    # sid -> asyncio.Task for debouncing
        self.DEBOUNCE_SECONDS = 60
        
        # Optional: without Redis this handler is a no-op and cached state
        # falls back to the browser's IndexedDB copy.
        from utils.redis_client import redis_url_or_none

        redis_url = redis_url_or_none()
        if redis_url:
            try:
                self.redis_client = redis.from_url(redis_url)
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
    
    def get_events(self):
        """No direct events handled - this is a lifecycle-only handler"""
        return {}
    
    async def get_user_id(self, sid: str) -> Optional[str]:
        """Extract user ID from session"""
        session = await self.sio.get_session(sid)
        if not session:
            return None
        
        # Get user ID from session (adjust based on your auth structure)
        # Assuming session has 'user_id' or 'email'
        return session.get('user_id') or session.get('email')
    
    async def setup_user(self, sid: str) -> None:
        """
        Called when user connects and is authenticated.
        Immediately sets up change monitoring, then attempts state restoration in background.
        """
        if not self.redis_client:
            return
        
        try:
            # 1. Get user ID (fast, synchronous)
            user_id = await self.get_user_id(sid)
            if not user_id:
                logger.warning(f"No user_id found for session {sid}")
                return
            
            # 2. IMMEDIATELY register callback for state changes (don't wait for Redis)
            async def on_state_change(sid: str, synced_state: SyncedState):
                await self.handle_state_change(sid, synced_state)
            
            self.ypy_handler.register_update_callback(sid, on_state_change)
            
            # 3. Start background task to restore state from Redis (fire-and-forget)
            from utils.async_helpers import spawn
            spawn(
                self._restore_state_background(sid, user_id),
                name=f"cache-restore-state:{sid}",
            )
            
        except Exception as e:
            logger.error(f"Error in setup_user for {sid}: {e}")
    
    async def _restore_state_background(self, sid: str, user_id: str):
        """
        Background task to restore cached state from Redis with timeout handling.
        Failures here don't affect user connection.
        """
        try:
            redis_key = f"cachedb:{user_id}"

            # Add timeout to prevent blocking
            # Retrieve both state and timestamp from hash
            cached_data = await asyncio.wait_for(
                self.redis_client.hgetall(redis_key),
                timeout=5.0  # 5 second timeout
            )

            if cached_data and b'state' in cached_data:
                timestamp = int(cached_data.get(b'timestamp', b'0'))
                logger.debug(f"Restoring cached state for user {user_id} with timestamp {timestamp}")
                # Send cached state with timestamp to frontend
                event = CacheValtioStateEvent(
                    state_update=list(cached_data[b'state']),
                    cache_timestamp=timestamp
                )
                await send_event(self.sio, sid, event)
            else:
                logger.debug(f"No cached state found for user {user_id}")
                
        except asyncio.TimeoutError:
            logger.warning(f"Redis timeout when restoring state for user {user_id} - user connection unaffected")
        except Exception as e:
            logger.error(f"Error restoring state for user {user_id}: {e} - user connection unaffected")
    
    async def handle_state_change(self, sid: str, synced_state: SyncedState):
        """
        Called when YJS state changes. Implements debouncing to avoid excessive Redis writes.
        """
        if not self.redis_client:
            return
        
        try:
            # Encode the state immediately while on the same thread
            # This prevents thread safety issues with YDoc objects
            state_bytes = Y.encode_state_as_update(synced_state.ydoc)
            
            # Cancel existing timer if present
            if sid in self.upload_timers:
                self.upload_timers[sid].cancel()
                logger.debug(f"Cancelled existing upload timer for {sid}")
            
            # Schedule new upload after debounce period
            # Pass the encoded bytes instead of the SyncedState object
            self.upload_timers[sid] = asyncio.create_task(
                self.delayed_upload(sid, state_bytes)
            )
            logger.debug(f"Scheduled upload for {sid} in {self.DEBOUNCE_SECONDS} seconds")
            
        except Exception as e:
            logger.error(f"Error handling state change for {sid}: {e}")
    
    async def delayed_upload(self, sid: str, state_bytes: bytes):
        """
        Performs the actual upload to Redis after debounce period.
        
        Args:
            sid: Session ID
            state_bytes: Pre-encoded YDoc state bytes (avoids thread safety issues)
        """
        try:
            await asyncio.sleep(self.DEBOUNCE_SECONDS)
            
            # Get user ID
            user_id = await self.get_user_id(sid)
            if not user_id:
                logger.warning(f"Cannot save state - no user_id for {sid}")
                return
            
            redis_key = f"cachedb:{user_id}"

            # Save to Redis with timestamp (last write wins) with timeout
            # state_bytes is already encoded, no need to access YDoc here
            timestamp_ms = int(time.time() * 1000)
            await asyncio.wait_for(
                self.redis_client.hset(redis_key, mapping={
                    'state': state_bytes,
                    'timestamp': timestamp_ms
                }),
                timeout=10.0  # 10 second timeout
            )
            logger.info(f"Saved state to Redis for user {user_id} with timestamp {timestamp_ms}")
            
            # Clean up timer reference
            if sid in self.upload_timers:
                del self.upload_timers[sid]
                
        except asyncio.CancelledError:
            logger.debug(f"Upload cancelled for {sid}")
            raise
        except asyncio.TimeoutError:
            logger.warning(f"Redis timeout when saving state for {sid}")
        except Exception as e:
            logger.error(f"Error uploading state for {sid}: {e}")
    
    async def cleanup_user(self, sid: str) -> None:
        """
        Called when user disconnects. Ensures any pending state is saved,
        then cleans up YJS memory.
        """
        try:
            # Important: Save any pending state before cleanup
            pending_upload = self.upload_timers.get(sid)
            if pending_upload:
                pending_upload.cancel()

            if self.redis_client and pending_upload:
                logger.info(f"Saving final state for disconnecting user {sid}")
                
                # Get current state and save immediately
                state = await YPYHandler.get_synced_state(self.sio, sid)
                if state:
                    user_id = await self.get_user_id(sid)
                    if user_id:
                        # Encode state immediately to avoid thread safety issues
                        update = Y.encode_state_as_update(state.ydoc)
                        redis_key = f"cachedb:{user_id}"
                        timestamp_ms = int(time.time() * 1000)

                        # Use asyncio.shield to protect from cancellation with timeout
                        await asyncio.shield(
                            asyncio.wait_for(
                                self.redis_client.hset(redis_key, mapping={
                                    'state': update,
                                    'timestamp': timestamp_ms
                                }),
                                timeout=5.0  # 5 second timeout
                            )
                        )
                        logger.info(f"Saved final state for user {user_id} with timestamp {timestamp_ms}")
                
        except KeyError as e:
            # Engine.io may evict the session before handler cleanup runs.
            # There is no session-backed state left to persist in that case.
            logger.debug(
                f"Cache cleanup: session {sid} already gone ({e.args[0]})"
            )
        except asyncio.TimeoutError:
            logger.warning(f"Redis timeout during cleanup for {sid}")
        except Exception as e:
            logger.error(f"Error saving final state for {sid}: {e}")
        finally:
            # Local YJS callbacks must be released even when Redis is disabled,
            # the socket session has already disappeared, or the final save
            # fails. cleanup_synced_state handles a missing session itself.
            self.upload_timers.pop(sid, None)
            await self.ypy_handler.cleanup_synced_state(sid)
