// Pin the public Loopy Loyalty operation catalog and manual connection method.
// This protects discovery and category placement without requiring a provider account.
import { expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { LoopyLoyaltyNode } from '~/components/workflow/nodes/integrations/loopy-loyalty';
import { getAgentToolOperations, loadNodeSchemas } from '~/utils/nodeSchemas';

await loadNodeSchemas(['automation-loopy-loyalty']);
it('publishes loyalty operations with a manual API key connection', () => {
    expect(LoopyLoyaltyNode.category).toBe('marketing');
    expect(getAgentToolOperations('automation-loopy-loyalty')).toHaveLength(16);
    expect(credentialRequirements('automation-loopy-loyalty').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
});
