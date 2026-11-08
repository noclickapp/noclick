import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/basin.json';

describe('Basin connection metadata', () => {
    beforeAll(() => loadNodeSchemas(['automation-basin']));
    it('offers a pasted API key with the Basin label', () => {
        expect(getNodeCredentialInfo('automation-basin')?.acceptedTypes).toEqual(['basin_api_key']);
        expect(getCredentialTypeFromSchemaTitle('Basin API Key')).toBe('basin_api_key');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    });
    it('offers all 24 native operations', () => {
        const ops = getAgentToolOperations('automation-basin').map(op => op.operation);
        expect(ops).toHaveLength(24);
        expect(ops).toContain('list_forms');
        expect(ops).toContain('update_submission');
        expect(ops).toContain('create_form_webhook');
    });
});
