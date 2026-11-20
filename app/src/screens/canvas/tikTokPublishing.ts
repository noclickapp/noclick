// Share TikTok disclosure validation between the editor and execution controls.
// Invalid settings must be blocked before a manual run as well as at the API boundary.
import type { Node } from '@xyflow/react';

export function tikTokDisclosureError(
    config: Record<string, unknown>
): string | undefined {
    // Upstream expressions are checked after resolution by backend preflight.
    if (
        [
            'disclose_commercial_content',
            'brand_content_toggle',
            'brand_organic_toggle',
            'privacy_level',
        ].some(
            (key) =>
                typeof config[key] === 'string' &&
                String(config[key]).includes('{{')
        )
    )
        return;
    const commercial = config.disclose_commercial_content === 'true';
    const paid = config.brand_content_toggle === 'true';
    const ownBrand = config.brand_organic_toggle === 'true';
    if (commercial && !paid && !ownBrand)
        return 'Select your own brand, a paid partnership, or both before running.';
    if (!commercial && (paid || ownBrand))
        return 'Enable commercial content disclosure for promotional content.';
    if (paid && config.privacy_level === 'SELF_ONLY')
        return 'Paid partnerships cannot be private. Select another visibility before running.';
}

export function tikTokNodePublishingError(
    node: Node | null
): string | undefined {
    if (
        node?.type !== 'automation-tiktok' ||
        !['direct_post_video', 'direct_post_photo'].includes(
            String(node.data.operation)
        )
    )
        return;
    return tikTokDisclosureError(
        (node.data.config ?? {}) as Record<string, unknown>
    );
}
