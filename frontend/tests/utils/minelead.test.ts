import { beforeAll, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/minelead.json'), 'utf8'));

describe('Minelead manual connect and catalog', () => {
    beforeAll(() => loadNodeSchemas(['automation-minelead']));
    it('exposes one manually entered API key', () => {
        expect(getNodeCredentialInfo('automation-minelead')?.acceptedTypes).toEqual(['minelead_api_key']);
        const method = methodFromRequirement(requirementsFromSchema(schema)[0]);
        expect(method.method_kind).toBe('api_key');
        expect(method.credential_fields).toEqual([
            expect.objectContaining({ name: 'api_key', label: 'API Key', type: 'password', required: true }),
        ]);
    });
    it('discovers seventeen independently configurable API operations', () => {
        const operations = getAgentToolOperations('automation-minelead').map(op => op.operation);
        expect(operations).toHaveLength(17);
        expect(operations).toEqual(expect.arrayContaining(['search_emails', 'get_account', 'add_leads', 'delete_leads', 'create_recipients', 'edit_recipients']));
    });
});
