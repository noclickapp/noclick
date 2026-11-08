import { expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { BolnaNode } from '~/components/workflow/nodes/integrations/bolna';
import { getAgentToolOperations, loadNodeSchemas } from '~/utils/nodeSchemas';
await loadNodeSchemas(['automation-bolna']);
it('publishes Bolna operations and a manual API key connection', () => {
    expect(BolnaNode.category).toBe('ai');
    expect(getAgentToolOperations('automation-bolna')).toHaveLength(21);
    expect(credentialRequirements('automation-bolna').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
});
