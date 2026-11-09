// Checks Rkvst manual credentials and the operation catalog.
// The shared connect UI relies on this generated metadata.
import { beforeAll, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/rkvst.json'), 'utf8'));

describe('Rkvst integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-rkvst']));
    it('discovers the human API key label and manual connect method', () => {
        expect(getNodeCredentialInfo('automation-rkvst')?.acceptedTypes).toEqual(['rkvst_bearer_token']);
        expect(getNodeCredentialInfo('automation-rkvst')?.label).toBe('Rkvst Bearer Token');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        expect(getCredentialTypeFromSchemaTitle('RkvstBearerTokenCredential')).toBe('rkvst_bearer_token');
        expect(getCredentialTypeFromSchemaTitle('Rkvst Bearer Token')).toBe('rkvst_bearer_token');
    });
    it('discovers all 17 provider operations including reads and writes', () => {
        const operations = getAgentToolOperations('automation-rkvst').map(op => op.operation);
        expect(operations).toHaveLength(17);
        expect(operations).toEqual(expect.arrayContaining(['list_assets', 'create_asset', 'create_event', 'update_location', 'delete_location']));
    });
});
