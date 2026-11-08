// Check FullEnrich's generated credential with the same consumers as the connect UI.
// This guards discovery, the manual API-key method, and its operation catalog.
import { beforeAll, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/fullenrich.json'), 'utf8'));

describe('FullEnrich metadata', () => {
    beforeAll(() => loadNodeSchemas(['automation-fullenrich']));
    it('offers a manual API key with a masked field', () => {
        expect(getNodeCredentialInfo('automation-fullenrich')?.acceptedTypes).toEqual(['fullenrich_api_key']);
        expect(getCredentialTypeFromSchemaTitle('Fullenrich API Key')).toBe('fullenrich_api_key');
        const method = methodFromRequirement(requirementsFromSchema(schema)[0]);
        expect(method.method_kind).toBe('api_key');
        expect(method.credential_fields).toEqual(expect.arrayContaining([
            expect.objectContaining({ name: 'api_key', label: 'API key', type: 'password', required: true }),
        ]));
    });
    it('discovers fourteen read and write operations', () => {
        const operations = getAgentToolOperations('automation-fullenrich').map(op => op.operation);
        expect(operations).toHaveLength(14);
        expect(operations).toEqual(expect.arrayContaining([
            'verify_api_key', 'enrich_contacts', 'search_people', 'lookup_company', 'update_sub_account',
        ]));
    });
});
