import { afterEach, describe, expect, it, vi } from 'vitest';
import { ChunkReassemblyManager } from './chunk-receiver';
import { REDACTED_SOCKET_DATA } from '~/lib/socket-diagnostics';

describe('ChunkReassemblyManager', () => {
    afterEach(() => vi.restoreAllMocks());

    it('does not treat a remote chunk id as a console format string', () => {
        const errorSpy = vi
            .spyOn(console, 'error')
            .mockImplementation(() => undefined);
        const manager = new ChunkReassemblyManager();
        const chunkId = '%s%s-remote';

        manager.handleChunk({
            __chunk_id: chunkId,
            __chunk_index: 0,
            __chunk_total: 1,
            __chunk_data: 'bm90LWpzb24=',
        });
        expect(
            manager.handleWrapper({
                __chunked: true,
                __chunk_id: chunkId,
                __chunk_total: 1,
                __compressed: false,
            })
        ).toBeNull();

        expect(errorSpy).toHaveBeenCalledWith(
            '[ChunkReceiver] Failed to reassemble chunk:',
            chunkId,
            REDACTED_SOCKET_DATA
        );
    });

    it('omits malformed payload exceptions and preserves cleanup and valid reassembly', () => {
        const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined);
        const manager = new ChunkReassemblyManager();
        const chunkId = 'synthetic-malformed-chunk';
        const wrapper = {
            __chunked: true as const,
            __chunk_id: chunkId,
            __chunk_total: 1,
            __compressed: false,
        };
        manager.handleChunk({
            __chunk_id: chunkId,
            __chunk_index: 0,
            __chunk_total: 1,
            __chunk_data: btoa('{"access_token":"synthetic-chunk-secret","broken":}'),
        });

        expect(manager.handleWrapper(wrapper)).toBeNull();
        expect(errorSpy).toHaveBeenNthCalledWith(
            1,
            '[ChunkReceiver] Failed to reassemble chunk:',
            chunkId,
            REDACTED_SOCKET_DATA
        );
        // Failed parsing still clears the buffer, before any event is known.
        expect(manager.handleWrapper(wrapper)).toBeNull();
        expect(errorSpy).toHaveBeenNthCalledWith(
            2,
            `[ChunkReceiver] No buffer found for chunk_id ${chunkId}`
        );

        const originalPayload = { access_token: 'synthetic-chunk-secret', count: 3 };
        manager.handleChunk({
            __chunk_id: chunkId,
            __chunk_index: 0,
            __chunk_total: 1,
            __chunk_data: btoa(JSON.stringify(originalPayload)),
        });
        expect(manager.handleWrapper(wrapper)).toEqual(originalPayload);
        expect(errorSpy).toHaveBeenCalledTimes(2);
    });
});
