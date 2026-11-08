import { beforeAll, describe, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { kindFromCredentialType } from '~/lib/credentialMethodKind';

describe('Carbone integration metadata', () => {
    beforeAll(() => loadNodeSchemas(['automation-carbone']));
    it('offers a pasted API token with the provider label', () => {
        expect(getNodeCredentialInfo('automation-carbone')?.acceptedTypes).toEqual(['carbone_api_token']);
        expect(getCredentialTypeFromSchemaTitle('Carbone API Token')).toBe('carbone_api_token');
        expect(kindFromCredentialType('carbone_api_token')).toBe('api_key');
    });
    it('offers all 11 published operations', () => {
        const operations = getAgentToolOperations('automation-carbone').map(op => op.operation);
        expect(operations).toHaveLength(11);
        expect(operations).toContain('list_templates');
        expect(operations).toContain('generate_document');
        expect(operations).toContain('download_document');
        expect(operations).toContain('upload_template');
        expect(operations).toContain('update_template');
    });
});
