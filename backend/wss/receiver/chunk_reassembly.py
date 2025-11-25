"""
Chunk reassembly manager for handling large Socket.IO messages.

Some reverse proxies have a 2 MiB limit per Socket.IO message.
This module handles reassembling chunked messages from the frontend transparently.
"""
import json
import base64
import asyncio
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class ChunkBuffer:
    """Buffer for collecting chunks of a chunked message"""
    chunk_id: str
    total_chunks: int
    chunks: Dict[int, str]  # chunk_index -> chunk_data (base64)
    created_at: datetime

    def is_complete(self) -> bool:
        """Check if all chunks have been received"""
        return len(self.chunks) == self.total_chunks

    def reassemble(self) -> Any:
        """Reassemble chunks into original payload"""
        # Decode each chunk individually (can't concatenate base64 strings due to padding)
        byte_chunks = []
        for i in range(self.total_chunks):
            chunk_b64 = self.chunks[i]
            chunk_bytes = base64.b64decode(chunk_b64)
            byte_chunks.append(chunk_bytes)

        # Concatenate all decoded bytes
        data_bytes = b''.join(byte_chunks)

        # Deserialize JSON to get original payload
        return json.loads(data_bytes.decode('utf-8'))


class ChunkReassemblyManager:
    """Manages chunk reassembly for all users"""

    def __init__(self, timeout_seconds: int = 30):
        self.buffers: Dict[str, Dict[str, ChunkBuffer]] = {}  # sid -> chunk_id -> buffer
        self.reassembled: Dict[str, Dict[str, Any]] = {}  # sid -> chunk_id -> payload (temp storage)
        self.timeout_seconds = timeout_seconds
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start_cleanup_task(self):
        """Start background task to clean up stale buffers"""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self):
        """Background task to periodically clean up stale buffers"""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                await self.cleanup_stale_buffers()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in chunk cleanup loop: {e}")

    async def cleanup_stale_buffers(self):
        """Remove buffers older than timeout"""
        cutoff = datetime.now() - timedelta(seconds=self.timeout_seconds)
        removed_count = 0

        for sid in list(self.buffers.keys()):
            user_buffers = self.buffers[sid]
            for chunk_id in list(user_buffers.keys()):
                buffer = user_buffers[chunk_id]
                if buffer.created_at < cutoff:
                    del user_buffers[chunk_id]
                    removed_count += 1
                    logger.warning(
                        f"Removed stale chunk buffer {chunk_id} for {sid} "
                        f"(received {len(buffer.chunks)}/{buffer.total_chunks} chunks)"
                    )

            # Clean up empty user entries
            if not user_buffers:
                del self.buffers[sid]

        if removed_count > 0:
            logger.info(f"Cleaned up {removed_count} stale chunk buffers")

    def handle_chunk(self, sid: str, chunk_data: dict) -> Optional[Any]:
        """
        Handle a chunk message. Returns None (waiting for more chunks or wrapper).
        Stores reassembled payload for retrieval by wrapper event.
        """
        chunk_id = chunk_data.get('__chunk_id')
        chunk_index = chunk_data.get('__chunk_index')
        chunk_total = chunk_data.get('__chunk_total')
        chunk_b64 = chunk_data.get('__chunk_data')

        if not all([chunk_id, chunk_total is not None, chunk_index is not None, chunk_b64]):
            logger.error(f"Invalid chunk data received from {sid}: {chunk_data.keys()}")
            return None

        # Get or create buffer for this user
        if sid not in self.buffers:
            self.buffers[sid] = {}

        user_buffers = self.buffers[sid]

        # Get or create buffer for this chunk_id
        if chunk_id not in user_buffers:
            user_buffers[chunk_id] = ChunkBuffer(
                chunk_id=chunk_id,
                total_chunks=chunk_total,
                chunks={},
                created_at=datetime.now()
            )

        buffer = user_buffers[chunk_id]

        # Store chunk
        buffer.chunks[chunk_index] = chunk_b64

        # Check if complete
        if buffer.is_complete():
            logger.info(f"All {chunk_total} chunks received for {chunk_id}, reassembling...")
            try:
                payload = buffer.reassemble()

                # Store reassembled payload (don't clean up yet - wrapper event needs it)
                if sid not in self.reassembled:
                    self.reassembled[sid] = {}
                self.reassembled[sid][chunk_id] = payload

                # Clean up buffer (but keep reassembled payload)
                del user_buffers[chunk_id]
                if not user_buffers:
                    del self.buffers[sid]

                logger.info(f"Successfully reassembled {chunk_id}, stored for wrapper retrieval")
                return None  # Wrapper event will retrieve the payload
            except Exception as e:
                logger.error(f"Failed to reassemble chunks for {chunk_id}: {e}")
                del user_buffers[chunk_id]
                return None
        else:
            logger.debug(
                f"Chunk {chunk_index + 1}/{chunk_total} received for {chunk_id} from {sid}"
            )
            return None

    def is_chunked_wrapper(self, data: Any) -> bool:
        """Check if data is a chunked message wrapper"""
        return isinstance(data, dict) and data.get('__chunked') is True

    def get_chunk_id(self, data: dict) -> Optional[str]:
        """Extract chunk_id from a chunked wrapper"""
        if self.is_chunked_wrapper(data):
            return data.get('__chunk_id')
        return None

    async def wait_for_reassembly(self, sid: str, chunk_id: str, timeout: float = 30.0) -> Optional[Any]:
        """
        Wait for all chunks to arrive and return reassembled payload.
        Used when processing a chunked wrapper.
        """
        start_time = asyncio.get_event_loop().time()

        while True:
            # Check if payload was already reassembled (fast path)
            if sid in self.reassembled and chunk_id in self.reassembled[sid]:
                payload = self.reassembled[sid][chunk_id]
                # Clean up reassembled storage
                del self.reassembled[sid][chunk_id]
                if not self.reassembled[sid]:
                    del self.reassembled[sid]
                logger.info(f"Retrieved reassembled payload for {chunk_id}")
                return payload

            # Check if buffer exists and is complete (fallback - shouldn't happen)
            if sid in self.buffers and chunk_id in self.buffers[sid]:
                buffer = self.buffers[sid][chunk_id]
                if buffer.is_complete():
                    try:
                        payload = buffer.reassemble()
                        # Clean up
                        del self.buffers[sid][chunk_id]
                        if not self.buffers[sid]:
                            del self.buffers[sid]
                        logger.info(f"Reassembled payload directly for {chunk_id}")
                        return payload
                    except Exception as e:
                        logger.error(f"Failed to reassemble chunks for {chunk_id}: {e}")
                        return None

            # Check timeout
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                logger.error(f"Timeout waiting for chunks {chunk_id} from {sid}")
                # Clean up partial buffer
                if sid in self.buffers and chunk_id in self.buffers[sid]:
                    del self.buffers[sid][chunk_id]
                return None

            # Wait a bit before checking again
            await asyncio.sleep(0.01)

    def cleanup_user(self, sid: str):
        """Clean up all buffers for a disconnected user"""
        buffer_count = 0
        reassembled_count = 0

        if sid in self.buffers:
            buffer_count = len(self.buffers[sid])
            del self.buffers[sid]

        if sid in self.reassembled:
            reassembled_count = len(self.reassembled[sid])
            del self.reassembled[sid]

        if buffer_count > 0 or reassembled_count > 0:
            logger.info(
                f"Cleaned up {buffer_count} chunk buffers and {reassembled_count} "
                f"reassembled payloads for disconnected user {sid}"
            )

    async def stop(self):
        """Stop the cleanup task"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
