// Glean's manual connect method must include both the token and its instance URL.
// Exercise the same schema and metadata helpers that drive the connect surfaces.
import { beforeAll, describe, expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({
    valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() },
}));
import {
    credentialRequirements,
    methodFromRequirement,
} from '~/components/credential/credentialMethods';
import {
    getAgentToolOperations,
    getNodeCredentialInfo,
    loadNodeSchemas,
} from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';

describe('Glean integration metadata', () => {
    beforeAll(() => loadNodeSchemas(['automation-glean']));
    it('provides the complete manual token method', () => {
        const requirements = credentialRequirements('automation-glean');
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method).toMatchObject({
            credential_type: 'glean_api_token',
            method_kind: 'api_key',
            is_oauth: false,
        });
        expect(method.credential_fields.map((field) => field.name)).toEqual([
            'api_token',
            'backend_url',
        ]);
        expect(method.credential_fields.every((field) => field.required)).toBe(
            true
        );
        expect(method.credential_fields[0].type).toBe('password');
        expect(
            getNodeCredentialInfo('automation-glean')?.acceptedTypes
        ).toEqual(['glean_api_token']);
        expect(
            getCredentialTypeFromSchemaTitle('GleanAPITokenCredential')
        ).toBe('glean_api_token');
        expect(getCredentialTypeFromSchemaTitle('Glean API Token')).toBe(
            'glean_api_token'
        );
    });
    it('exposes the 21 actions as agent tools', () => {
        const operations = getAgentToolOperations('automation-glean').map(
            (op) => op.operation
        );
        expect(operations).toHaveLength(21);
        expect(operations).toEqual(
            expect.arrayContaining([
                'search',
                'create_answer',
                'create_collection',
                'create_shortcut',
                'list_trigger_presets',
            ])
        );
        expect(operations).not.toContain('on_event');
    });
});
