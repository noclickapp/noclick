// Run the chat's Memories panel regression in CI's real Chromium suite.
// The shared nc test also runs interactively without modifying account data.
import { expect, it } from 'vitest';
import verifyMemoriesPanel from '../nc/coordinator-memories-panel.test';

it('loads memories only once the panel opens and reads one in a single column', async () => {
    expect(await verifyMemoriesPanel()).toEqual({ lazy: true, singleColumn: true, updates: true });
});
