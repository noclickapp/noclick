import { afterEach, describe, expect, it, vi } from 'vitest';
import { ChunkReassemblyManager } from './chunk-receiver';

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
            expect.anything()
        );
    });
});
