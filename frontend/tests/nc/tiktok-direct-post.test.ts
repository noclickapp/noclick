// Check the real TikTok settings panel in a controlled developer workflow.
// This smoke test is read-only and never initiates a publish.
import { nc } from '~/lib/nc';

// Open a controlled TikTok direct-post node's configuration before running.
// Read-only: this test never runs a node, changes visibility, or publishes content.
export default async function () {
    await nc.wait.forElement('[data-testid="tiktok-publishing-panel"]');
    const panel = document.querySelector(
        '[data-testid="tiktok-publishing-panel"]'
    )!;
    nc.assert.truthy(
        panel.textContent?.includes('without an inbox confirmation'),
        'Direct publishing is explained'
    );
    nc.assert.truthy(
        panel.querySelector('a[href*="music-usage-confirmation"]'),
        'Music usage terms are accessible'
    );
    nc.assert.truthy(
        panel.querySelector('select'),
        'Privacy is a creator-controlled dropdown'
    );
    const inputs = Array.from(
        panel.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')
    );
    nc.assert.gt(
        inputs.length,
        2,
        'Interaction and disclosure controls are present'
    );
    return { controls: inputs.length, noPublishPerformed: true };
}
