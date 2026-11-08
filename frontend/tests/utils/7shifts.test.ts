import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { SevenShiftsNode } from '../../app/components/workflow/nodes/integrations/7shifts';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';
import { humanizeCredentialLabel } from '../../app/utils/credentialLabels';

await loadNodeSchemas(['automation-7shifts']);

describe('7Shifts integration', () => {
    it('discovers workforce reads and writes', () => {
        expect(SevenShiftsNode.type).toBe('automation-7shifts');
        const operations = getAgentToolOperations('automation-7shifts').map(op => op.operation);
        expect(operations).toHaveLength(23);
        for (const operation of ['create_user', 'create_shift', 'delete_shift', 'create_time_punch', 'update_time_off']) {
            expect(operations).toContain(operation);
        }
    });

    it('offers a clearly labelled pasted access token', () => {
        expect(credentialRequirements('automation-7shifts').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-7shifts')?.acceptedTypes).toContain('7shifts_access_token');
        expect(humanizeCredentialLabel('7shifts Access Token')).toBe('7shifts Access Token');
    });
});
