import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { OpenAlexNode } from '../../app/components/workflow/nodes/integrations/openalex';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-openalex']);

describe('OpenAlex integration', () => {
    it('exposes research reads and a manual API key connection', () => {
        expect(OpenAlexNode.category).toBe('content-research');
        const operations = getAgentToolOperations('automation-openalex').map(op => op.operation);
        expect(operations).toHaveLength(24);
        expect(operations).toContain('get_rate_limit');
        expect(operations).toContain('list_works');
        expect(operations).toContain('autocomplete');
        expect(credentialRequirements('automation-openalex').map(methodFromRequirement)).toEqual([
            expect.objectContaining({ method_kind: 'api_key', is_oauth: false }),
        ]);
        expect(getNodeCredentialInfo('automation-openalex')?.acceptedTypes).toContain('openalex_api_key');
    });
});
