// Run the reusable nc recovery scenario in real Chromium.
// Provider authorization and analytics are isolated from this UI check.
import { expect, it, vi } from 'vitest';
import recovery from '../nc/claude-oauth-recovery.test';
vi.mock('~/hooks/useAgentOAuthAnalytics', () => ({
    useAgentOAuthAnalytics: () => ({
        started: vi.fn(),
        completed: vi.fn(),
        failed: vi.fn(),
    }),
}));
it('recovers from a consumed Claude authorization in the browser', async () => {
    expect(await recovery()).toEqual({
        success: true,
        exchanges: 1,
        starts: 2,
    });
});
