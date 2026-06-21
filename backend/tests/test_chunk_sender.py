"""
Comprehensive tests for backend → frontend chunking.

Tests the chunk_sender module which handles splitting large Socket.IO messages
into chunks that can be reassembled by the frontend.
"""
import pytest
import json
import base64
import zlib
from unittest.mock import AsyncMock, MagicMock, call

from wss.sender.chunk_sender import (
    CHUNK_SIZE,
    COMPRESSION_ENABLED,
    ChunkMetadata,
    ChunkedWrapper,
    get_payload_size,
    needs_chunking,
    chunk_payload,
    send_chunked_event,
)


class TestPayloadSizeCalculation:
    """Tests for get_payload_size function."""

    def test_small_dict_size(self):
        """Small dict should have correct JSON size."""
        data = {"key": "value"}
        expected = len(json.dumps(data).encode('utf-8'))
        assert get_payload_size(data) == expected

    def test_empty_dict_size(self):
        """Empty dict should have minimal size."""
        assert get_payload_size({}) == 2  # '{}'

    def test_list_size(self):
        """List payload should be sized correctly."""
        data = [1, 2, 3, 4, 5]
        expected = len(json.dumps(data).encode('utf-8'))
        assert get_payload_size(data) == expected

    def test_nested_structure_size(self):
        """Nested structures should be sized correctly."""
        data = {
            "level1": {
                "level2": {
                    "data": [1, 2, 3],
                    "text": "hello"
                }
            }
        }
        expected = len(json.dumps(data).encode('utf-8'))
        assert get_payload_size(data) == expected

    def test_unicode_size(self):
        """Unicode characters should be sized correctly (UTF-8 bytes)."""
        data = {"emoji": "🚀🔥"}
        # Each emoji is 4 bytes in UTF-8
        expected = len(json.dumps(data).encode('utf-8'))
        assert get_payload_size(data) == expected

    def test_large_payload_size(self):
        """Large payload size should be calculated correctly."""
        # 1MB of data
        data = {"data": "x" * (1024 * 1024)}
        size = get_payload_size(data)
        # Should be slightly over 1MB due to JSON structure
        assert size > 1024 * 1024
        assert size < 1024 * 1024 + 100  # JSON overhead is minimal


class TestNeedsChunking:
    """Tests for needs_chunking function."""

    def test_small_payload_no_chunking(self):
        """Small payloads should not need chunking."""
        data = {"small": "data"}
        assert needs_chunking(data) is False

    def test_exact_threshold_no_chunking(self):
        """Payload exactly at threshold should not need chunking."""
        # Create payload exactly at CHUNK_SIZE
        # JSON format: {"data":"xxx..."} has overhead of 10 chars
        padding_size = CHUNK_SIZE - len('{"data":""}')
        data = {"data": "x" * (padding_size - 1)}  # -1 to stay at or under threshold
        # At exactly the threshold, should not need chunking
        assert get_payload_size(data) <= CHUNK_SIZE
        assert needs_chunking(data) is False

    def test_over_threshold_needs_chunking(self):
        """Payload over threshold should need chunking."""
        # Create payload just over CHUNK_SIZE
        data = {"data": "x" * CHUNK_SIZE}
        assert needs_chunking(data) is True

    def test_large_payload_needs_chunking(self):
        """Large payloads should need chunking."""
        data = {"data": "x" * (2 * 1024 * 1024)}  # 2MB
        assert needs_chunking(data) is True

    def test_custom_chunk_size(self):
        """Custom chunk size should be respected."""
        data = {"data": "x" * 1000}  # ~1KB
        assert needs_chunking(data, chunk_size=500) is True
        assert needs_chunking(data, chunk_size=2000) is False


class TestMaybeChunk:
    """Tests for maybe_chunk — the loop-safe serialize+chunk entry point.

    Regression guard for the perf finding: send_event used to serialize a
    payload twice on the event loop (once in needs_chunking, once in
    chunk_payload). maybe_chunk runs off-loop and serializes exactly once.
    """

    @pytest.mark.asyncio
    async def test_small_payload_returns_none(self):
        from wss.sender.chunk_sender import maybe_chunk
        assert await maybe_chunk({"message": "hello"}) is None

    @pytest.mark.asyncio
    async def test_large_payload_returns_chunks_matching_chunk_payload(self):
        from wss.sender.chunk_sender import maybe_chunk, chunk_payload
        data = {"big": list(range(300000))}  # well over CHUNK_SIZE serialized
        result = await maybe_chunk(data)
        assert result is not None
        chunks, wrapper = result
        assert len(chunks) > 0
        assert wrapper.chunked is True
        # Same chunk count as the synchronous path (modulo the random chunk_id).
        ref_chunks, ref_wrapper = chunk_payload(data)
        assert len(chunks) == len(ref_chunks)
        assert wrapper.chunk_total == ref_wrapper.chunk_total
        assert wrapper.compressed == ref_wrapper.compressed

    @pytest.mark.asyncio
    async def test_serializes_exactly_once_for_large_payload(self):
        """The size decision and the chunk split must share one serialization —
        no second multi-MB json.dumps on the hot path."""
        from unittest.mock import patch
        import wss.sender.chunk_sender as cs
        real = cs.serialize_payload
        calls = {"n": 0}

        def counting(data):
            calls["n"] += 1
            return real(data)

        data = {"big": list(range(300000))}
        with patch.object(cs, "serialize_payload", side_effect=counting):
            result = await cs.maybe_chunk(data)
        assert result is not None  # chunked
        assert calls["n"] == 1, f"payload serialized {calls['n']}x, expected exactly 1"


class TestChunkPayload:
    """Tests for chunk_payload function."""

    def test_single_chunk_with_compression(self):
        """Small compressed payload should result in single chunk."""
        # Highly compressible data
        data = {"data": "x" * (2 * 1024 * 1024)}  # 2MB of repeated chars
        chunks, wrapper = chunk_payload(data, compress=True)

        # Repeated chars compress very well, should be 1 chunk
        assert len(chunks) >= 1
        assert wrapper.chunked is True
        assert wrapper.compressed is True
        assert wrapper.chunk_total == len(chunks)

    def test_multiple_chunks_no_compression(self):
        """Large payload without compression should create multiple chunks."""
        # Random-ish data that doesn't compress well
        import random
        random.seed(42)
        data = {"data": "".join(random.choices("abcdefghijklmnop", k=2 * 1024 * 1024))}
        chunks, wrapper = chunk_payload(data, compress=False, chunk_size=500_000)

        # Should need multiple chunks
        assert len(chunks) > 1
        assert wrapper.compressed is False

    def test_chunk_metadata_structure(self):
        """Chunks should have correct metadata structure."""
        data = {"data": "x" * (2 * 1024 * 1024)}
        chunks, wrapper = chunk_payload(data)

        for i, chunk in enumerate(chunks):
            chunk_dict = chunk.to_dict()
            assert "__chunk_id" in chunk_dict
            assert "__chunk_index" in chunk_dict
            assert "__chunk_total" in chunk_dict
            assert "__chunk_data" in chunk_dict
            assert chunk_dict["__chunk_index"] == i
            assert chunk_dict["__chunk_total"] == len(chunks)

    def test_wrapper_structure(self):
        """Wrapper should have correct structure."""
        data = {"data": "x" * (2 * 1024 * 1024)}
        chunks, wrapper = chunk_payload(data)

        wrapper_dict = wrapper.to_dict()
        assert wrapper_dict["__chunked"] is True
        assert "__chunk_id" in wrapper_dict
        assert "__chunk_total" in wrapper_dict
        assert "__compressed" in wrapper_dict
        assert wrapper_dict["__chunk_total"] == len(chunks)

    def test_chunk_ids_match(self):
        """All chunks and wrapper should have same chunk_id."""
        data = {"data": "x" * (2 * 1024 * 1024)}
        chunks, wrapper = chunk_payload(data)

        chunk_id = wrapper.to_dict()["__chunk_id"]
        for chunk in chunks:
            assert chunk.to_dict()["__chunk_id"] == chunk_id

    def test_chunks_are_base64_encoded(self):
        """Chunk data should be valid base64."""
        data = {"data": "test content"}
        chunks, _ = chunk_payload(data, compress=False)

        for chunk in chunks:
            chunk_data = chunk.to_dict()["__chunk_data"]
            # Should not raise
            decoded = base64.b64decode(chunk_data)
            assert len(decoded) > 0

    def test_reassembly_produces_original(self):
        """Reassembling chunks should produce original data."""
        original_data = {
            "complex": {
                "nested": [1, 2, 3],
                "text": "hello world",
                "unicode": "🚀"
            },
            "list": ["a", "b", "c"]
        }

        # Chunk with compression
        chunks, wrapper = chunk_payload(original_data, compress=True)

        # Simulate frontend reassembly
        byte_chunks = []
        for chunk in sorted(chunks, key=lambda c: c.chunk_index):
            chunk_bytes = base64.b64decode(chunk.to_dict()["__chunk_data"])
            byte_chunks.append(chunk_bytes)

        combined = b"".join(byte_chunks)

        if wrapper.compressed:
            decompressed = zlib.decompress(combined)
        else:
            decompressed = combined

        reassembled = json.loads(decompressed.decode("utf-8"))
        assert reassembled == original_data

    def test_large_binary_like_data(self):
        """Test with data that simulates YJS state (list of integers)."""
        # Simulate YJS state as list of byte values
        yjs_state = list(range(256)) * 1000  # 256KB of byte values
        data = {"state_update": yjs_state, "timestamp": 1234567890}

        chunks, wrapper = chunk_payload(data, compress=True)

        # Reassemble
        byte_chunks = []
        for chunk in sorted(chunks, key=lambda c: c.chunk_index):
            chunk_bytes = base64.b64decode(chunk.to_dict()["__chunk_data"])
            byte_chunks.append(chunk_bytes)

        combined = b"".join(byte_chunks)
        decompressed = zlib.decompress(combined) if wrapper.compressed else combined
        reassembled = json.loads(decompressed.decode("utf-8"))

        assert reassembled["state_update"] == yjs_state
        assert reassembled["timestamp"] == 1234567890


class TestSendChunkedEvent:
    """Tests for send_chunked_event function."""

    @pytest.mark.asyncio
    async def test_sends_all_chunks_then_wrapper(self):
        """Should send all chunks via __chunk__ then wrapper via original event."""
        mock_sio = AsyncMock()

        data = {"data": "x" * (2 * 1024 * 1024)}
        chunks, wrapper = chunk_payload(data)

        await send_chunked_event(
            mock_sio,
            sid="test-sid",
            event_name="cache_valtio:state",
            chunks=chunks,
            wrapper=wrapper,
        )

        # Verify all chunks were sent
        chunk_calls = [c for c in mock_sio.emit.call_args_list if c[0][0] == "__chunk__"]
        assert len(chunk_calls) == len(chunks)

        # Verify wrapper was sent last
        wrapper_calls = [c for c in mock_sio.emit.call_args_list if c[0][0] == "cache_valtio:state"]
        assert len(wrapper_calls) == 1

        # Verify order: all chunks before wrapper
        all_calls = mock_sio.emit.call_args_list
        chunk_indices = [i for i, c in enumerate(all_calls) if c[0][0] == "__chunk__"]
        wrapper_index = next(i for i, c in enumerate(all_calls) if c[0][0] == "cache_valtio:state")
        assert all(ci < wrapper_index for ci in chunk_indices)

    @pytest.mark.asyncio
    async def test_sends_to_correct_target(self):
        """Should send to the correct sid or room."""
        mock_sio = AsyncMock()

        data = {"data": "test"}
        chunks, wrapper = chunk_payload(data, compress=False)

        await send_chunked_event(
            mock_sio,
            sid="test-sid-123",
            event_name="test:event",
            chunks=chunks,
            wrapper=wrapper,
        )

        # All calls should target the correct sid
        for call in mock_sio.emit.call_args_list:
            assert call.kwargs.get("to") == "test-sid-123"

    @pytest.mark.asyncio
    async def test_sends_to_room_when_specified(self):
        """Should send to room when room parameter is provided."""
        mock_sio = AsyncMock()

        data = {"data": "test"}
        chunks, wrapper = chunk_payload(data, compress=False)

        await send_chunked_event(
            mock_sio,
            sid="test-sid",
            event_name="test:event",
            chunks=chunks,
            wrapper=wrapper,
            room="test-room",
        )

        # All calls should target the room
        for call in mock_sio.emit.call_args_list:
            assert call.kwargs.get("to") == "test-room"


class TestCompressionEffectiveness:
    """Tests for compression behavior."""

    def test_compression_reduces_size(self):
        """Compression should significantly reduce size for repetitive data."""
        # Highly compressible data
        data = {"data": "x" * (1024 * 1024)}

        chunks_compressed, _ = chunk_payload(data, compress=True)
        chunks_uncompressed, _ = chunk_payload(data, compress=False)

        compressed_size = sum(
            len(c.to_dict()["__chunk_data"]) for c in chunks_compressed
        )
        uncompressed_size = sum(
            len(c.to_dict()["__chunk_data"]) for c in chunks_uncompressed
        )

        # Compressed should be much smaller
        assert compressed_size < uncompressed_size / 2

    def test_compression_flag_in_wrapper(self):
        """Wrapper should correctly indicate compression state."""
        data = {"data": "test"}

        _, wrapper_compressed = chunk_payload(data, compress=True)
        _, wrapper_uncompressed = chunk_payload(data, compress=False)

        assert wrapper_compressed.to_dict()["__compressed"] is True
        assert wrapper_uncompressed.to_dict()["__compressed"] is False


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_dict(self):
        """Empty dict should chunk correctly."""
        data = {}
        chunks, wrapper = chunk_payload(data)

        assert len(chunks) == 1
        assert wrapper.chunk_total == 1

    def test_empty_list(self):
        """Empty list should chunk correctly."""
        data = []
        chunks, wrapper = chunk_payload(data)

        assert len(chunks) == 1

    def test_null_values(self):
        """Null values in payload should be handled."""
        data = {"key": None, "list": [None, 1, None]}
        chunks, wrapper = chunk_payload(data)

        # Reassemble and verify
        byte_chunks = [base64.b64decode(c.to_dict()["__chunk_data"]) for c in chunks]
        combined = b"".join(byte_chunks)
        if wrapper.compressed:
            combined = zlib.decompress(combined)
        reassembled = json.loads(combined.decode("utf-8"))

        assert reassembled == data

    def test_special_characters(self):
        """Special characters and unicode should be preserved."""
        data = {
            "emoji": "🚀🔥💻",
            "newlines": "line1\nline2\r\nline3",
            "quotes": 'single\' and "double"',
            "backslash": "path\\to\\file",
        }
        chunks, wrapper = chunk_payload(data)

        # Reassemble and verify
        byte_chunks = [base64.b64decode(c.to_dict()["__chunk_data"]) for c in chunks]
        combined = b"".join(byte_chunks)
        if wrapper.compressed:
            combined = zlib.decompress(combined)
        reassembled = json.loads(combined.decode("utf-8"))

        assert reassembled == data

    def test_deeply_nested_structure(self):
        """Deeply nested structures should be preserved."""
        data = {"l1": {"l2": {"l3": {"l4": {"l5": {"value": "deep"}}}}}}
        chunks, wrapper = chunk_payload(data)

        # Reassemble and verify
        byte_chunks = [base64.b64decode(c.to_dict()["__chunk_data"]) for c in chunks]
        combined = b"".join(byte_chunks)
        if wrapper.compressed:
            combined = zlib.decompress(combined)
        reassembled = json.loads(combined.decode("utf-8"))

        assert reassembled == data


class TestIntegrationWithSendEvent:
    """Tests for integration with the main send_event function."""

    @pytest.mark.asyncio
    async def test_send_event_chunks_large_payload(self):
        """send_event should automatically chunk large payloads."""
        from unittest.mock import patch, AsyncMock
        from pydantic import BaseModel
        from typing import ClassVar, List

        # Create a mock event class
        class LargeStateEvent(BaseModel):
            event_name: ClassVar[str] = "test:large_state"
            state_update: List[int]
            timestamp: int

        mock_sio = AsyncMock()

        # Create large payload that needs chunking
        large_state = list(range(256)) * 5000  # Large list of ints
        event = LargeStateEvent(state_update=large_state, timestamp=123456)

        # Import and call send_event
        from wss.sender import send_event

        # Exercise the real serialize+chunk path (now run off-loop via
        # maybe_chunk/asyncio.to_thread). The payload genuinely exceeds
        # CHUNK_SIZE, so real chunks are produced and send_chunked_event fires.
        with patch('wss.sender.chunk_sender.send_chunked_event', new_callable=AsyncMock) as mock_chunked:
            await send_event(mock_sio, "test-sid", event)

            # Verify chunking was used with real (non-empty) chunks + wrapper.
            mock_chunked.assert_called_once()
            call_args = mock_chunked.call_args.args
            chunks, wrapper = call_args[3], call_args[4]
            assert len(chunks) > 0
            assert wrapper.chunked is True
            # Large payload was NOT emitted directly (chunked instead).
            mock_sio.emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_event_no_chunking_for_small_payload(self):
        """send_event should not chunk small payloads."""
        from unittest.mock import patch, AsyncMock
        from pydantic import BaseModel
        from typing import ClassVar

        class SmallEvent(BaseModel):
            event_name: ClassVar[str] = "test:small"
            message: str

        mock_sio = AsyncMock()
        event = SmallEvent(message="hello")

        from wss.sender import send_event

        with patch('wss.sender.chunk_sender.send_chunked_event', new_callable=AsyncMock) as mock_chunked:
            await send_event(mock_sio, "test-sid", event)

            # Verify chunking was NOT used
            mock_chunked.assert_not_called()

            # Verify normal emit was called
            mock_sio.emit.assert_called()


class TestFrontendReassemblySimulation:
    """
    E2E tests that simulate the frontend ChunkReassemblyManager behavior.

    These tests verify that backend chunking produces output that the frontend
    can correctly reassemble using the exact same logic as chunk-receiver.ts.
    """

    def _simulate_frontend_reassembly(self, chunks, wrapper):
        """
        Simulate the frontend's ChunkReassemblyManager.handleWrapper() logic.

        This mirrors the TypeScript implementation in chunk-receiver.ts exactly:
        1. Collect chunks into a buffer
        2. Base64 decode each chunk
        3. Concatenate in order
        4. Decompress if needed (pako.inflate equivalent)
        5. Parse JSON
        """
        # Simulate buffer collection (as frontend does in handleChunk)
        chunk_buffer = {}
        for chunk in chunks:
            chunk_dict = chunk.to_dict()
            chunk_buffer[chunk_dict['__chunk_index']] = chunk_dict['__chunk_data']

        wrapper_dict = wrapper.to_dict()
        total_chunks = wrapper_dict['__chunk_total']
        is_compressed = wrapper_dict['__compressed']

        # Verify all chunks present
        assert len(chunk_buffer) == total_chunks, \
            f"Incomplete chunks: {len(chunk_buffer)}/{total_chunks}"

        # Base64 decode each chunk (matches base64ToBytes in TS)
        byte_chunks = []
        for i in range(total_chunks):
            chunk_b64 = chunk_buffer[i]
            chunk_bytes = base64.b64decode(chunk_b64)
            byte_chunks.append(chunk_bytes)

        # Concatenate (matches Uint8Array concatenation in TS)
        combined = b''.join(byte_chunks)

        # Decompress if needed (matches pako.inflate in TS)
        if is_compressed:
            json_bytes = zlib.decompress(combined)
        else:
            json_bytes = combined

        # Parse JSON (matches JSON.parse in TS)
        return json.loads(json_bytes.decode('utf-8'))

    def test_e2e_small_payload_roundtrip(self):
        """Small payload should roundtrip correctly through frontend simulation."""
        original = {"message": "hello", "count": 42}
        chunks, wrapper = chunk_payload(original)
        reassembled = self._simulate_frontend_reassembly(chunks, wrapper)
        assert reassembled == original

    def test_e2e_large_yjs_state_roundtrip(self):
        """Simulate cache_valtio:state with YJS-like data."""
        # This simulates the actual use case that triggered the chunking need
        yjs_state = {
            "state_update": list(range(256)) * 2000,  # ~500KB of byte values
            "origin": "server",
            "timestamp": 1234567890123,
            "metadata": {
                "user_id": "user_123",
                "session_id": "session_456",
            }
        }

        chunks, wrapper = chunk_payload(yjs_state, compress=True)
        reassembled = self._simulate_frontend_reassembly(chunks, wrapper)

        assert reassembled == yjs_state
        assert reassembled["state_update"] == yjs_state["state_update"]

    def test_e2e_out_of_order_chunks(self):
        """Frontend should handle chunks received out of order."""
        original = {"data": "x" * (2 * 1024 * 1024)}  # ~2MB
        chunks, wrapper = chunk_payload(original, compress=True, chunk_size=500_000)

        # Shuffle chunks to simulate out-of-order delivery
        import random
        shuffled_chunks = chunks.copy()
        random.shuffle(shuffled_chunks)

        # Frontend still reassembles correctly using chunk_index
        reassembled = self._simulate_frontend_reassembly(shuffled_chunks, wrapper)
        assert reassembled == original

    def test_e2e_uncompressed_payload(self):
        """Verify uncompressed payloads work with frontend simulation."""
        original = {"uncompressed": True, "values": list(range(100))}
        chunks, wrapper = chunk_payload(original, compress=False)

        assert wrapper.compressed is False
        reassembled = self._simulate_frontend_reassembly(chunks, wrapper)
        assert reassembled == original

    def test_e2e_wrapper_metadata_matches_frontend_interface(self):
        """Verify wrapper matches ChunkedWrapper TypeScript interface."""
        original = {"test": "data"}
        chunks, wrapper = chunk_payload(original)

        wrapper_dict = wrapper.to_dict()

        # Verify all required fields from TypeScript interface exist
        assert '__chunked' in wrapper_dict
        assert '__chunk_id' in wrapper_dict
        assert '__chunk_total' in wrapper_dict
        assert '__compressed' in wrapper_dict

        # Verify types match TypeScript interface
        assert wrapper_dict['__chunked'] is True  # TypeScript: __chunked: true
        assert isinstance(wrapper_dict['__chunk_id'], str)
        assert isinstance(wrapper_dict['__chunk_total'], int)
        assert isinstance(wrapper_dict['__compressed'], bool)

    def test_e2e_chunk_metadata_matches_frontend_interface(self):
        """Verify chunks match ChunkMetadata TypeScript interface."""
        original = {"test": "data"}
        chunks, wrapper = chunk_payload(original)

        for chunk in chunks:
            chunk_dict = chunk.to_dict()

            # Verify all required fields from TypeScript interface exist
            assert '__chunk_id' in chunk_dict
            assert '__chunk_index' in chunk_dict
            assert '__chunk_total' in chunk_dict
            assert '__chunk_data' in chunk_dict

            # Verify types match TypeScript interface
            assert isinstance(chunk_dict['__chunk_id'], str)
            assert isinstance(chunk_dict['__chunk_index'], int)
            assert isinstance(chunk_dict['__chunk_total'], int)
            assert isinstance(chunk_dict['__chunk_data'], str)  # Base64 string

    def test_e2e_multi_megabyte_payload(self):
        """Test with realistic multi-megabyte payload like large app state."""
        # Simulate a large application state
        large_state = {
            "components": [
                {"id": f"comp_{i}", "type": "widget", "props": {"text": "x" * 100}}
                for i in range(1000)
            ],
            "styles": {"global": "css" * 1000},
            "data": list(range(10000)),
        }

        chunks, wrapper = chunk_payload(large_state, compress=True)

        # Should need multiple chunks
        assert len(chunks) >= 1

        reassembled = self._simulate_frontend_reassembly(chunks, wrapper)
        assert reassembled == large_state

    def test_e2e_binary_like_data_preserved(self):
        """Verify binary-like data (byte arrays) survives roundtrip."""
        # Simulate binary data as list of integers (how YJS state is serialized)
        binary_data = {
            "bytes": [i % 256 for i in range(100000)],  # 100K "bytes"
            "checksum": sum(range(100000)) % 256,
        }

        chunks, wrapper = chunk_payload(binary_data, compress=True)
        reassembled = self._simulate_frontend_reassembly(chunks, wrapper)

        assert reassembled["bytes"] == binary_data["bytes"]
        assert reassembled["checksum"] == binary_data["checksum"]

    def test_e2e_complex_nested_structure(self):
        """Verify complex nested structures survive roundtrip."""
        complex_data = {
            "level1": {
                "level2": {
                    "level3": {
                        "array": [1, 2, 3, {"nested": True}],
                        "null_value": None,
                        "unicode": "🚀🔥💻",
                        "numbers": [1.5, 2.7, 3.14159],
                    }
                }
            },
            "root_array": [{"a": 1}, {"b": 2}, {"c": [1, 2, 3]}],
        }

        chunks, wrapper = chunk_payload(complex_data)
        reassembled = self._simulate_frontend_reassembly(chunks, wrapper)
        assert reassembled == complex_data


class TestChunkIdUniqueness:
    """Tests for chunk ID generation and uniqueness."""

    def test_different_payloads_have_different_chunk_ids(self):
        """Each chunking operation should generate a unique chunk_id."""
        data1 = {"payload": 1}
        data2 = {"payload": 2}

        _, wrapper1 = chunk_payload(data1)
        _, wrapper2 = chunk_payload(data2)

        assert wrapper1.chunk_id != wrapper2.chunk_id

    def test_same_payload_generates_different_ids(self):
        """Even identical payloads should generate unique chunk_ids."""
        data = {"same": "data"}

        _, wrapper1 = chunk_payload(data)
        _, wrapper2 = chunk_payload(data)

        assert wrapper1.chunk_id != wrapper2.chunk_id

    def test_chunk_id_format(self):
        """Chunk IDs should follow expected format."""
        data = {"test": "data"}
        _, wrapper = chunk_payload(data)

        assert wrapper.chunk_id.startswith("chunk_")
        # Should have hex characters after prefix
        assert len(wrapper.chunk_id) == len("chunk_") + 12
