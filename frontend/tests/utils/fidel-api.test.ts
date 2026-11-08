import { beforeAll, expect, it, vi } from 'vitest';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({
    valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() },
}));
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import {
    getNodeCredentialInfo,
    getNodeSchema,
    getAgentToolOperations,
    loadNodeSchemas,
} from '~/utils/nodeSchemas';
import {
    requirementsFromSchema,
    methodFromRequirement,
} from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-fidel-api']));
it('discovers one manually entered API key method and its schema aliases', () => {
    expect(
        getCredentialTypeFromSchemaTitle('FidelAPIKeyCredential')
    ).toBe('fidel_api_key');
    expect(getCredentialTypeFromSchemaTitle('Fidel API Key')).toBe(
        'fidel_api_key'
    );
    expect(
        getNodeCredentialInfo('automation-fidel-api')?.acceptedTypes
    ).toEqual(['fidel_api_key']);
    const requirements = requirementsFromSchema(
        getNodeSchema('automation-fidel-api')
    );
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0])).toMatchObject({
        method_kind: 'api_key',
        is_oauth: false,
    });
});
it('offers the account read and brand, program, offer and webhook automations', () => {
    const operations = getAgentToolOperations('automation-fidel-api').map(
        (op) => op.operation
    );
    expect(operations).toHaveLength(25);
    expect(operations).toEqual(
        expect.arrayContaining([
            'list_brands',
            'create_brand',
            'get_program',
            'create_offer',
            'delete_offer',
            'create_webhook_program',
            'list_transactions_by_program',
        ])
    );
});
