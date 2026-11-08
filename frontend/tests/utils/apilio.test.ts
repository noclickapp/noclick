import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { ApilioNode } from '../../app/components/workflow/nodes/integrations/apilio';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-apilio']);

describe('Apilio integration', () => {
    it('offers the 19 published read and write actions', () => {
        expect(ApilioNode.category).toBe('industry');
        const operations = getAgentToolOperations('automation-apilio').map(op => op.operation);
        expect(operations).toHaveLength(19);
        expect(operations).toContain('update_boolean_variable');
        expect(operations).toContain('evaluate_logicblock');
        expect(operations).toContain('set_logicblock_active');
    });

    it('connects by pasting a Basic API token', () => {
        expect(credentialRequirements('automation-apilio').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-apilio')?.acceptedTypes).toContain('apilio_api_token');
    });
});
