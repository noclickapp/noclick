import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { TeltelNode } from '../../app/components/workflow/nodes/integrations/teltel';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-teltel']);

describe('Teltel integration', () => {
    it('exposes the 20 documented operations in communication', () => {
        expect(TeltelNode.category).toBe('communication');
        const operations = getAgentToolOperations('automation-teltel').map(op => op.operation);
        expect(operations).toHaveLength(20);
        expect(operations).toContain('send_sms');
        expect(operations).toContain('create_contact');
        expect(operations).toContain('list_calls');
    });

    it('connects with a manually pasted API key', () => {
        expect(credentialRequirements('automation-teltel').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-teltel')?.acceptedTypes).toContain('teltel_api_key');
    });
});
