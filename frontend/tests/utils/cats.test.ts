import { beforeAll, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import {
    loadNodeSchemas,
    getNodeCredentialInfo,
    getAgentToolOperations,
} from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';

const schema = JSON.parse(
    readFileSync(join(__dirname, '../../app/schemas/nodes/cats.json'), 'utf8')
);

describe('CATS metadata', () => {
    beforeAll(() => loadNodeSchemas(['automation-cats']));
    it('offers a manual API key with a masked field', () => {
        expect(getNodeCredentialInfo('automation-cats')?.acceptedTypes).toEqual(
            ['cats_api_key']
        );
        expect(getCredentialTypeFromSchemaTitle('CATS API Key')).toBe(
            'cats_api_key'
        );
        const method = methodFromRequirement(requirementsFromSchema(schema)[0]);
        expect(method.method_kind).toBe('api_key');
        expect(method.credential_fields).toEqual(
            expect.arrayContaining([
                expect.objectContaining({
                    name: 'api_key',
                    label: 'API Key',
                    type: 'password',
                    required: true,
                }),
            ])
        );
    });
    it('discovers 25 recruiting operations', () => {
        const operations = getAgentToolOperations('automation-cats').map(
            (op) => op.operation
        );
        expect(operations).toHaveLength(25);
        expect(operations).toEqual(
            expect.arrayContaining([
                'get_site',
                'search_candidates',
                'create_candidate',
                'update_contact',
                'create_job',
                'create_pipeline',
                'update_task',
            ])
        );
    });
});
