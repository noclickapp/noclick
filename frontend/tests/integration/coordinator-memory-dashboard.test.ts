// Run the dashboard memory navigation regression in CI's real Chromium suite.
// The shared nc test also runs interactively without modifying account data.
import { expect, it } from 'vitest';
import verifyDashboardMemories from '../nc/coordinator-memory-dashboard.test';

it('previews memories in a bento and opens the full dashboard reading view', async () => {
    expect(await verifyDashboardMemories()).toEqual({
        preview: true,
        fullPage: true,
        updates: true,
        gated: true,
    });
});
