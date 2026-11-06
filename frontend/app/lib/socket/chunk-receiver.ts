/**
 * Frontend chunk receiver for large Socket.IO messages from the backend.
 *
 * Mirrors the backend's chunk_sender.py pattern. When the backend sends a message
 * exceeding the chunk threshold, it sends chunks via __chunk__ event followed by
 * a wrapper via the original event name. This module reassembles them.
 */

import pako from 'pako';

// Chunk metadata received from backend (matches ChunkMetadata in chunk_sender.py)
export interface ChunkMetadata {
  __chunk_id: string;
  __chunk_index: number;
  __chunk_total: number;
  __chunk_data: string; // Base64 encoded chunk data
}

// Wrapper received via original event name (matches ChunkedWrapper in chunk_sender.py)
export interface ChunkedWrapper {
  __chunked: true;
  __chunk_id: string;
  __chunk_total: number;
  __compressed: boolean;
}

// Internal buffer for collecting chunks
interface ChunkBuffer {
  chunkId: string;
  totalChunks: number;
  chunks: Map<number, string>; // index -> base64 data
  createdAt: number;
  compressed: boolean;
}

/**
 * Check if data is a chunked wrapper from the backend
 */
export function isChunkedWrapper(data: unknown): data is ChunkedWrapper {
  return (
    typeof data === 'object' &&
    data !== null &&
    '__chunked' in data &&
    (data as ChunkedWrapper).__chunked === true
  );
}

/**
 * Decode base64 to Uint8Array without stack overflow for large data
 */
function base64ToBytes(base64: string): Uint8Array {
  const binaryString = atob(base64);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return bytes;
}

/**
 * Chunk reassembly manager for backend -> frontend messages
 */
export class ChunkReassemblyManager {
  private buffers = new Map<string, ChunkBuffer>();
  private reassembled = new Map<string, unknown>(); // chunk_id -> payload
  private readonly timeoutMs: number;
  private cleanupInterval: ReturnType<typeof setInterval> | null = null;

  constructor(timeoutMs = 30000) {
    this.timeoutMs = timeoutMs;
  }

  /**
   * Start the cleanup interval for stale buffers
   */
  start(): void {
    if (this.cleanupInterval) return;

    this.cleanupInterval = setInterval(() => {
      this.cleanupStaleBuffers();
    }, 60000); // Check every minute
  }

  /**
   * Stop the cleanup interval
   */
  stop(): void {
    if (this.cleanupInterval) {
      clearInterval(this.cleanupInterval);
      this.cleanupInterval = null;
    }
  }

  /**
   * Remove buffers older than timeout
   */
  private cleanupStaleBuffers(): void {
    const cutoff = Date.now() - this.timeoutMs;
    let removedCount = 0;

    for (const [chunkId, buffer] of this.buffers) {
      if (buffer.createdAt < cutoff) {
        this.buffers.delete(chunkId);
        removedCount++;
        console.warn(
          `[ChunkReceiver] Removed stale buffer ${chunkId} ` +
            `(received ${buffer.chunks.size}/${buffer.totalChunks} chunks)`
        );
      }
    }

    if (removedCount > 0) {
      console.log(`[ChunkReceiver] Cleaned up ${removedCount} stale buffers`);
    }
  }

  /**
   * Handle an incoming chunk. Returns null (waiting for wrapper or more chunks).
   */
  handleChunk(chunk: ChunkMetadata): void {
    const { __chunk_id, __chunk_index, __chunk_total, __chunk_data } = chunk;

    // Get or create buffer
    if (!this.buffers.has(__chunk_id)) {
      this.buffers.set(__chunk_id, {
        chunkId: __chunk_id,
        totalChunks: __chunk_total,
        chunks: new Map(),
        createdAt: Date.now(),
        compressed: false, // Will be set by wrapper
      });
    }

    const buffer = this.buffers.get(__chunk_id)!;
    buffer.chunks.set(__chunk_index, __chunk_data);

    console.debug(
      `[ChunkReceiver] Received chunk ${__chunk_index + 1}/${__chunk_total} for ${__chunk_id}`
    );

    // Check if complete
    if (buffer.chunks.size === buffer.totalChunks) {
      console.log(
        `[ChunkReceiver] All ${__chunk_total} chunks received for ${__chunk_id}, awaiting wrapper`
      );
    }
  }

  /**
   * Handle a chunked wrapper. Reassembles and returns the original payload.
   * Returns null if chunks haven't arrived yet (shouldn't happen in normal flow).
   */
  handleWrapper(wrapper: ChunkedWrapper): unknown | null {
    const { __chunk_id, __chunk_total, __compressed } = wrapper;

    const buffer = this.buffers.get(__chunk_id);
    if (!buffer) {
      console.error(`[ChunkReceiver] No buffer found for chunk_id ${__chunk_id}`);
      return null;
    }

    // Update compression flag from wrapper
    buffer.compressed = __compressed;

    // Check if all chunks received
    if (buffer.chunks.size !== __chunk_total) {
      console.error(
        `[ChunkReceiver] Incomplete chunks for ${__chunk_id}: ` +
          `${buffer.chunks.size}/${__chunk_total}`
      );
      return null;
    }

    // Reassemble
    try {
      // Decode each chunk and concatenate
      const byteChunks: Uint8Array[] = [];
      for (let i = 0; i < __chunk_total; i++) {
        const chunkB64 = buffer.chunks.get(i);
        if (!chunkB64) {
          console.error(`[ChunkReceiver] Missing chunk ${i} for ${__chunk_id}`);
          return null;
        }
        byteChunks.push(base64ToBytes(chunkB64));
      }

      // Concatenate all chunks
      const totalLength = byteChunks.reduce((sum, chunk) => sum + chunk.length, 0);
      const combined = new Uint8Array(totalLength);
      let offset = 0;
      for (const chunk of byteChunks) {
        combined.set(chunk, offset);
        offset += chunk.length;
      }

      // Decompress if needed
      let jsonBytes: Uint8Array;
      if (__compressed) {
        jsonBytes = pako.inflate(combined);
        console.log(
          `[ChunkReceiver] Decompressed ${combined.length} -> ${jsonBytes.length} bytes`
        );
      } else {
        jsonBytes = combined;
      }

      // Parse JSON
      const jsonString = new TextDecoder().decode(jsonBytes);
      const payload = JSON.parse(jsonString);

      // Cleanup
      this.buffers.delete(__chunk_id);

      console.log(`[ChunkReceiver] Successfully reassembled ${__chunk_id}`);
      return payload;
    } catch (error) {
      // Keep the format string constant: chunk ids arrive over the socket and
      // may contain printf-style tokens interpreted by console implementations.
      console.error('[ChunkReceiver] Failed to reassemble chunk:', __chunk_id, error);
      this.buffers.delete(__chunk_id);
      return null;
    }
  }

  /**
   * Clear all buffers (call on disconnect)
   */
  clear(): void {
    const count = this.buffers.size;
    this.buffers.clear();
    this.reassembled.clear();
    if (count > 0) {
      console.log(`[ChunkReceiver] Cleared ${count} buffers`);
    }
  }
}

// Singleton instance
export const chunkReceiver = new ChunkReassemblyManager();
