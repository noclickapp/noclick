// Verifies discovery of the TrackVia operations and pasted API-key method.
// Guards the generated credential aliases used by manual connection forms.
import { beforeAll, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/trackvia.json'), 'utf8'));

describe('TrackVia integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-trackvia']));
    it('discovers the human API key label and manual connect method', () => {
        expect(getNodeCredentialInfo('automation-trackvia')?.acceptedTypes).toEqual(['trackvia_api_token']);
        expect(getNodeCredentialInfo('automation-trackvia')?.label).toBe('TrackVia API Token');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        expect(getCredentialTypeFromSchemaTitle('TrackViaTokenCredential')).toBe('trackvia_api_token');
        expect(getCredentialTypeFromSchemaTitle('TrackVia API Token')).toBe('trackvia_api_token');
    });
    it('discovers all 16 provider operations including reads and writes', () => {
        const operations = getAgentToolOperations('automation-trackvia').map(op => op.operation);
        expect(operations).toHaveLength(16);
        expect(operations).toEqual(expect.arrayContaining(['list_apps', 'list_records', 'create_record', 'update_record', 'delete_record']));
    });
});
