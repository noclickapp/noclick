import { beforeAll, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/dodo.json'), 'utf8'));

describe('Nookipedia integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-dodo']));
    it('discovers the manual API key connection', () => {
        expect(getNodeCredentialInfo('automation-dodo')?.acceptedTypes).toEqual(['dodo_api_key']);
        expect(getNodeCredentialInfo('automation-dodo')?.label).toBe('Nookipedia API Key');
        expect(methodFromRequirement(requirementsFromSchema(schema)[0])).toMatchObject({ method_kind: 'api_key', is_oauth: false });
        expect(getCredentialTypeFromSchemaTitle('DodoAPIKeyCredential')).toBe('dodo_api_key');
        expect(getCredentialTypeFromSchemaTitle('Nookipedia API Key')).toBe('dodo_api_key');
    });
    it('exposes twenty-five reads from the provider contract', () => {
        const operations = getAgentToolOperations('automation-dodo').map(op => op.operation);
        expect(operations).toHaveLength(25);
        expect(operations).toEqual(expect.arrayContaining(['list_villagers', 'list_events', 'get_recipe', 'list_fossils', 'get_gyroid']));
        expect(operations.every(op => op.startsWith('list_') || op.startsWith('get_'))).toBe(true);
    });
});
