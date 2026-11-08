import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { FaradayNode } from '../../app/components/workflow/nodes/integrations/faraday';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-faraday']);

describe('Faraday integration', () => {
    it('discovers prediction reads and writes in AI', () => {
        expect(FaradayNode.type).toBe('automation-faraday');
        expect(FaradayNode.category).toBe('ai');
        const operations = getAgentToolOperations('automation-faraday').map(op => op.operation);
        expect(operations).toHaveLength(22);
        for (const operation of ['get_current_account', 'create_cohort', 'create_outcome', 'rerun_target', 'lookup_target']) {
            expect(operations).toContain(operation);
        }
    });
    it('offers a pasted API key', () => {
        expect(credentialRequirements('automation-faraday').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-faraday')?.acceptedTypes).toContain('faraday_api_key');
    });
});
