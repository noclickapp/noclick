import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { AviatoNode } from '~/components/workflow/nodes/integrations/aviato';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';

await loadNodeSchemas(['automation-aviato']);

describe('Aviato integration', () => {
    it('exposes its native operations in the CRM section', () => {
        expect(getAgentToolOperations('automation-aviato')).toHaveLength(25);
        expect(AviatoNode.category).toBe('crm-sales');
        expect(AviatoNode.type).toBe('automation-aviato');
    });
    it('offers a manually pasted API key', () => {
        expect(credentialRequirements('automation-aviato').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-aviato')?.acceptedTypes).toContain('aviato_api_key');
    });
});
