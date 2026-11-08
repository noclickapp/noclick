import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { AddresszenNode } from '../../app/components/workflow/nodes/integrations/addresszen';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';
import { humanizeCredentialLabel } from '../../app/utils/credentialLabels';

await loadNodeSchemas(['automation-addresszen']);

describe('Addresszen integration', () => {
    it('offers lookups and management operations', () => {
        expect(AddresszenNode.type).toBe('automation-addresszen');
        const operations = getAgentToolOperations('automation-addresszen').map(op => op.operation);
        expect(operations).toHaveLength(20);
        expect(operations).toContain('verify_address');
        expect(operations).toContain('create_licensee');
        expect(operations).toContain('update_config');
    });

    it('connects using pasted API and management keys', () => {
        expect(credentialRequirements('automation-addresszen').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-addresszen')?.acceptedTypes).toContain('addresszen_api_keys');
        expect(humanizeCredentialLabel('Addresszen API Keys')).toBe('Addresszen API Keys');
    });
});
