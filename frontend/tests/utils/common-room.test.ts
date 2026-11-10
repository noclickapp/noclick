import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/common-room.json';

describe('Common Room connection metadata', () => {
    beforeAll(() => loadNodeSchemas(['automation-common-room']));
    it('offers a pasted API key with the Common Room label', () => {
        expect(getNodeCredentialInfo('automation-common-room')?.acceptedTypes).toEqual(['common_room_api_token']);
        expect(getCredentialTypeFromSchemaTitle('Common Room API Token')).toBe('common_room_api_token');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    });
    it('offers all 21 native operations', () => {
        const ops = getAgentToolOperations('automation-common-room').map(op => op.operation);
        expect(ops).toHaveLength(21);
        expect(ops).toContain('list_contacts');
        expect(ops).toContain('update_contacts');
        expect(ops).toContain('create_segment');
    });
});
