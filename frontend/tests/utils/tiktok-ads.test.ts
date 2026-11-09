import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import { TikTokAdsNode } from '~/components/workflow/nodes/integrations/tiktok-ads';

await loadNodeSchemas(['automation-tiktok-ads']);

describe('TikTok Ads', () => {
    it('discovers a manually connected access token', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-tiktok-ads');
        const requirements = credentialRequirements('automation-tiktok-ads');
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'tiktok_ads_access_token', method_kind: 'api_key', is_oauth: false,
        });
    });
    it('belongs in marketing and describes its Smart+ operations', () => {
        expect(TikTokAdsNode.category).toBe('marketing');
        expect(TikTokAdsNode.label).toBe('TikTok Ads');
        expect(TikTokAdsNode.description).toContain('Smart+');
    });
});
