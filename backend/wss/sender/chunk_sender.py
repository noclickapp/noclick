"""
Backend-to-frontend chunk sender for large Socket.IO messages.

Mirrors the frontend's chunking.ts pattern. Messages exceeding CHUNK_SIZE are split
into base64-encoded chunks sent via __chunk__ event, followed by a wrapper via the
original event name. Frontend's chunk-receiver.ts reassembles them.
"""
import json
import base64
import zlib
import logging
import uuid
from typing import Any, List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Chunk size threshold (1 MB - conservative to work with any infrastructure limit)
CHUNK_SIZE = 1 * 1024 * 1024

# Enable compression for better efficiency
# Level 1 chosen for speed: our YJS data compresses 80x+ at any level, so we
# prioritize fast compression (~4ms) over marginal size gains at higher levels.
# Benchmarks show level 1-3 are 2.5x faster than level 6 with only 2x larger output.
COMPRESSION_ENABLED = True
COMPRESSION_LEVEL = 1


@dataclass
class ChunkMetadata:
    """Metadata for a single chunk, matching frontend's ChunkMetadata interface."""
    chunk_id: str
    chunk_index: int
    chunk_total: int
    chunk_data: str  # Base64 encoded chunk data

    def to_dict(self) -> dict:
        """Convert to dict with __ prefixed keys for frontend compatibility."""
        return {
            '__chunk_id': self.chunk_id,
            '__chunk_index': self.chunk_index,
            '__chunk_total': self.chunk_total,
            '__chunk_data': self.chunk_data,
        }


@dataclass
class ChunkedWrapper:
    """Wrapper sent via original event name, matching frontend's ChunkedMessageWrapper."""
    chunked: bool = True
    chunk_id: str = ""
    chunk_total: int = 0
    compressed: bool = False

    def to_dict(self) -> dict:
        """Convert to dict with __ prefixed keys for frontend compatibility."""
        return {
            '__chunked': self.chunked,
            '__chunk_id': self.chunk_id,
            '__chunk_total': self.chunk_total,
            '__compressed': self.compressed,
        }


def get_payload_size(data: Any) -> int:
    """Calculate the serialized size of a payload in bytes."""
    try:
        serialized = json.dumps(data, default=str)
        return len(serialized.encode('utf-8'))
    except (TypeError, ValueError):
        return 0


def needs_chunking(data: Any, chunk_size: int = CHUNK_SIZE) -> bool:
    """Check if a payload exceeds the chunk size threshold."""
    return get_payload_size(data) > chunk_size


def chunk_payload(
    data: Any,
    chunk_size: int = CHUNK_SIZE,
    compress: bool = COMPRESSION_ENABLED
) -> Tuple[List[ChunkMetadata], ChunkedWrapper]:
    """
    Split a large payload into chunks.

    Args:
        data: The payload to chunk (will be JSON serialized)
        chunk_size: Maximum size per chunk in bytes
        compress: Whether to compress the payload before chunking

    Returns:
        Tuple of (list of chunks, wrapper to send via original event)
    """
    # Serialize payload to bytes
    serialized = json.dumps(data, default=str).encode('utf-8')

    # Optionally compress
    if compress:
        payload_bytes = zlib.compress(serialized, level=COMPRESSION_LEVEL)
        original_size = len(serialized)
        compressed_size = len(payload_bytes)
        logger.info(
            f"[CHUNK] Compressed payload: {original_size} -> {compressed_size} bytes "
            f"({100 - (compressed_size / original_size * 100):.1f}% reduction)"
        )
    else:
        payload_bytes = serialized

    # Generate chunk ID
    chunk_id = f"chunk_{uuid.uuid4().hex[:12]}"

    # Calculate total chunks
    total_chunks = (len(payload_bytes) + chunk_size - 1) // chunk_size

    # Split into chunks
    chunks: List[ChunkMetadata] = []
    for i in range(total_chunks):
        start = i * chunk_size
        end = min(start + chunk_size, len(payload_bytes))
        chunk_bytes = payload_bytes[start:end]

        chunks.append(ChunkMetadata(
            chunk_id=chunk_id,
            chunk_index=i,
            chunk_total=total_chunks,
            chunk_data=base64.b64encode(chunk_bytes).decode('ascii'),
        ))

    # Create wrapper
    wrapper = ChunkedWrapper(
        chunked=True,
        chunk_id=chunk_id,
        chunk_total=total_chunks,
        compressed=compress,
    )

    logger.info(
        f"[CHUNK] Split payload into {total_chunks} chunks "
        f"(chunk_id={chunk_id}, total_bytes={len(payload_bytes)})"
    )

    return chunks, wrapper


async def send_chunked_event(
    sio,
    sid: str,
    event_name: str,
    chunks: List[ChunkMetadata],
    wrapper: ChunkedWrapper,
    room: Optional[str] = None,
) -> None:
    """
    Send a chunked payload: first all chunks via __chunk__, then wrapper via original event.

    Args:
        sio: Socket.io server instance
        sid: Session ID of the recipient
        event_name: Original event name for the wrapper
        chunks: List of chunk metadata
        wrapper: Wrapper to send via original event name
        room: Optional room to send to (defaults to sid)
    """
    target = room or sid

    # Send all chunks first
    for chunk in chunks:
        await sio.emit('__chunk__', chunk.to_dict(), to=target)

    # Send wrapper via original event name
    await sio.emit(event_name, wrapper.to_dict(), to=target)

    logger.info(
        f"[CHUNK] Sent {len(chunks)} chunks + wrapper for {event_name} to {target}"
    )
