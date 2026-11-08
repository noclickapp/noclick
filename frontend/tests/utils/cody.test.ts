import { beforeAll, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/cody.json'), 'utf8'));

describe('Cody integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-cody']));
    it('discovers the human API key label and manual connect method', () => {
        expect(getNodeCredentialInfo('automation-cody')?.acceptedTypes).toEqual(['cody_api_key']);
        expect(getNodeCredentialInfo('automation-cody')?.label).toBe('Cody API Key');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        expect(getCredentialTypeFromSchemaTitle('CodyApiKeyCredential')).toBe('cody_api_key');
        expect(getCredentialTypeFromSchemaTitle('Cody API Key')).toBe('cody_api_key');
    });
    it('discovers all 21 provider operations including reads and writes', () => {
        const operations = getAgentToolOperations('automation-cody').map(op => op.operation);
        expect(operations).toHaveLength(21);
        expect(operations).toEqual(expect.arrayContaining(['list_bots', 'send_message', 'create_document', 'delete_document', 'get_uploads_signed_url']));
    });
});
