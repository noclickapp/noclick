// Run the memory-management regression in real Chromium as part of CI.
// The same test is available through the nc bridge for interactive verification.
import { expect, it } from 'vitest';
import verifyMemories from '../nc/coordinator-memories.test';

it('browses, edits and forgets memories without losing concurrent changes', async () => {
    const result = await verifyMemories();
    expect(result).toMatchObject({
        writes: 2,
        deletes: 1,
        conflictProtected: true,
        separateDescription: true,
    });
});
