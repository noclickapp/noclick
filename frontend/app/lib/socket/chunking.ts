/**
 * Socket message chunking utilities for handling large payloads.
 *
 * Some reverse proxies have a 2 MiB limit per Socket.IO message.
 * This module handles chunking large messages transparently for ANY event.
 */

import { SOCKET_CHUNK_SIZE } from './config';

// Export for testing/override purposes
export const DEFAULT_CHUNK_SIZE = SOCKET_CHUNK_SIZE;

// Chunk metadata sent with each chunk
export interface ChunkMetadata {
  __chunk_id: string;        // Unique ID for this chunked message
  __chunk_index: number;     // Current chunk index (0-based)
  __chunk_total: number;     // Total number of chunks
  __chunk_data: string;      // Base64 encoded chunk data
}

// Final indicator wraps the original payload with chunking metadata
export interface ChunkedMessageWrapper {
  __chunked: true;
  __chunk_id: string;
  __chunk_total: number;
  __original_payload: any;   // Original payload (indicator only, actual data in chunks)
}

/**
 * Generate a unique chunk ID for a chunked message
 */
export function generateChunkId(): string {
  return `chunk_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`;
}

/**
 * Check if a payload needs to be chunked based on serialized size
 */
export function needsChunking(payload: unknown, chunkSize: number = DEFAULT_CHUNK_SIZE): boolean {
  const sizeInBytes = getPayloadSize(payload);
  return sizeInBytes > chunkSize;
}

/**
 * Serialize any payload to bytes for size calculation and chunking
 */
function serializePayload(payload: unknown): Uint8Array {
  let serializable = payload;

  // Convert Uint8Array to regular array for proper JSON serialization
  // (Uint8Array stringifies as object {"0":1,"1":2} instead of array [1,2,3])
  if (payload instanceof Uint8Array) {
    serializable = Array.from(payload);
  }

  // Serialize to JSON (works for any type - objects, arrays, primitives)
  const serialized = JSON.stringify(serializable);
  return new TextEncoder().encode(serialized);
}

/**
 * Calculate the serialized size of any payload in bytes
 */
export function getPayloadSize(payload: unknown): number {
  return serializePayload(payload).length;
}

/**
 * Convert Uint8Array to base64 without stack overflow.
 * Can't use String.fromCharCode(...bytes) for large arrays (causes stack overflow).
 */
function bytesToBase64(bytes: Uint8Array): string {
  let binary = '';
  const batchSize = 8192; // Process 8KB at a time to avoid stack overflow
  for (let i = 0; i < bytes.length; i += batchSize) {
    const batch = bytes.subarray(i, Math.min(i + batchSize, bytes.length));
    binary += String.fromCharCode(...batch);
  }
  return btoa(binary);
}

/**
 * Split any large payload into chunks
 */
export function chunkPayload(
  payload: unknown,
  chunkSize: number = DEFAULT_CHUNK_SIZE
): { chunks: ChunkMetadata[]; wrapper: ChunkedMessageWrapper } {
  // Serialize payload to bytes
  const bytes = serializePayload(payload);
  const chunkId = generateChunkId();
  const totalChunks = Math.ceil(bytes.length / chunkSize);

  // Split into chunks
  const chunks: ChunkMetadata[] = [];
  for (let i = 0; i < totalChunks; i++) {
    const start = i * chunkSize;
    const end = Math.min(start + chunkSize, bytes.length);
    const chunkBytes = bytes.slice(start, end);

    chunks.push({
      __chunk_id: chunkId,
      __chunk_index: i,
      __chunk_total: totalChunks,
      __chunk_data: bytesToBase64(chunkBytes),
    });
  }

  // Wrapper replaces original payload
  const wrapper: ChunkedMessageWrapper = {
    __chunked: true,
    __chunk_id: chunkId,
    __chunk_total: totalChunks,
    __original_payload: null, // Chunks contain the actual data
  };

  return { chunks, wrapper };
}

/**
 * Intercept and chunk payload if needed, return payload to emit
 */
export function maybeChunk(
  socket: { emit: (event: string, data: unknown) => void },
  payload: unknown,
  chunkSize: number = DEFAULT_CHUNK_SIZE
): unknown {
  if (getPayloadSize(payload) <= chunkSize) {
    return payload; // No chunking needed
  }

  const { chunks, wrapper } = chunkPayload(payload, chunkSize);
  console.log(`[Chunking] Splitting payload into ${chunks.length} chunks (${getPayloadSize(payload)} bytes)`);

  // Send chunks first
  chunks.forEach(chunk => socket.emit('__chunk__', chunk));

  // Return wrapper to be emitted with original event name
  return wrapper;
}
