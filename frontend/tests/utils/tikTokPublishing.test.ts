// @vitest-environment jsdom
// Exercise the same validation gate used by the Run control and node validator.
// Ordinary unattended configurations and unrelated operations must remain runnable.
import { describe, expect, it } from 'vitest';
import type { Node } from '@xyflow/react';
import { tikTokNodePublishingError } from '~/utils/tikTokPublishing';

function node(operation: string, config: Record<string, unknown>): Node {
    return {
        id: 'test',
        type: 'automation-tiktok',
        position: { x: 0, y: 0 },
        data: { operation, config },
    };
}
describe('TikTok publishing run gate', () => {
    it('feeds disclosure errors into full-workflow validation', async () => {
        const { validateNode } = await import('~/utils/workflowNodeValidation');
        const result = validateNode(
            node('direct_post_video', {
                video_url: 'https://example.com/v.mp4',
                privacy_level: 'SELF_ONLY',
                disclose_commercial_content: 'true',
            })
        );
        expect(result.isComplete).toBe(false);
        expect(
            result.issues.find(
                (issue) => issue.fieldKey === 'disclose_commercial_content'
            )?.message
        ).toContain('Select your own brand');
    }, 30000);
    it.each(['direct_post_video', 'direct_post_photo'])(
        'blocks incomplete commercial %s',
        (operation) => {
            expect(
                tikTokNodePublishingError(
                    node(operation, { disclose_commercial_content: 'true' })
                )
            ).toContain('Select your own brand');
            expect(
                tikTokNodePublishingError(
                    node(operation, {
                        disclose_commercial_content: 'true',
                        brand_content_toggle: 'true',
                        privacy_level: 'SELF_ONLY',
                    })
                )
            ).toContain('cannot be private');
        }
    );
    it('permits configured unattended publishing and unrelated operations', () => {
        expect(
            tikTokNodePublishingError(
                node('direct_post_video', { privacy_level: 'SELF_ONLY' })
            )
        ).toBeUndefined();
        expect(
            tikTokNodePublishingError(
                node('direct_post_photo', {
                    disclose_commercial_content: 'true',
                    brand_organic_toggle: 'true',
                })
            )
        ).toBeUndefined();
        expect(
            tikTokNodePublishingError(
                node('query_creator_info', {
                    disclose_commercial_content: 'true',
                })
            )
        ).toBeUndefined();
        expect(tikTokNodePublishingError(null)).toBeUndefined();
        expect(
            tikTokNodePublishingError(
                node('direct_post_video', {
                    disclose_commercial_content: 'true',
                    brand_organic_toggle: '{{ input.promotional }}',
                })
            )
        ).toBeUndefined();
    });
});
