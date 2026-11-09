import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

describe('Outseta connection metadata', () => {
    beforeAll(() => loadNodeSchemas(['automation-outseta']));
    it('offers a pasted API key with a human provider label', () => {
        expect(getNodeCredentialInfo('automation-outseta')?.acceptedTypes).toEqual(['outseta_api_key']);
        expect(getCredentialTypeFromSchemaTitle('Outseta API Key')).toBe('outseta_api_key');
        const schema = NODE_SCHEMAS['automation-outseta'];
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    });
    it('offers all 24 native operations', () => {
        const ops = getAgentToolOperations('automation-outseta').map(op => op.operation);
        expect(ops).toHaveLength(24);
        expect(ops).toContain('create_person');
        expect(ops).toContain('update_deal');
        expect(ops).toContain('subscribe_person');
    });
});
