import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { EnforcedflowNode } from '../../app/components/workflow/nodes/integrations/enforcedflow';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-enforcedflow']);
describe('Enforcedflow integration', () => {
    it('discovers routing and agent management actions', () => {
        expect(EnforcedflowNode.type).toBe('automation-enforcedflow');
        const operations = getAgentToolOperations('automation-enforcedflow').map(o => o.operation);
        expect(operations).toHaveLength(10);
        expect(operations).toContain('next_agent');
        expect(operations).toContain('email_next_agent');
        expect(operations).toContain('upsert_agent');
    });
    it('offers a pasted Provider Key', () => {
        expect(credentialRequirements('automation-enforcedflow').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-enforcedflow')?.acceptedTypes).toContain('enforcedflow_provider_key');
    });
});
