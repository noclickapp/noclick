import { beforeAll, describe, expect, it, vi } from 'vitest';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({
    valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() },
}));
import schema from '~/schemas/nodes/dynamic-mockups.json';
import { DynamicMockupsNode } from '~/components/workflow/nodes/integrations/dynamic-mockups';
import {
    loadNodeSchemas,
    getNodeCredentialInfo,
    getAgentToolOperations,
    filterConfigForExecution,
} from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';

describe('Dynamic Mockups native integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-dynamic-mockups']));

    it('discovers the manual API key method and both generated credential aliases', () => {
        expect(
            getNodeCredentialInfo('automation-dynamic-mockups')?.acceptedTypes
        ).toEqual(['dynamic_mockups_api_key']);
        expect(
            methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind
        ).toBe('api_key');
        expect(
            getCredentialTypeFromSchemaTitle('DynamicMockupsAPIKeyCredential')
        ).toBe('dynamic_mockups_api_key');
        expect(
            getCredentialTypeFromSchemaTitle('Dynamic Mockups API Key')
        ).toBe('dynamic_mockups_api_key');
        expect(schema.$defs.DynamicMockupsAPIKeyCredential.required).toEqual([
            'api_key',
        ]);
        expect(
            schema.$defs.DynamicMockupsAPIKeyCredential.properties.api_key[
                'ui:widget'
            ]
        ).toBe('password');
    });

    it('exposes 22 operation choices and keeps only fields for the selected operation', () => {
        const operations = getAgentToolOperations(
            'automation-dynamic-mockups'
        ).map((op) => op.operation);
        expect(operations).toHaveLength(22);
        expect(operations).toEqual(
            expect.arrayContaining([
                'list_catalogs',
                'create_render',
                'create_ai_mockup',
                'get_motion_status',
            ])
        );
        expect(
            filterConfigForExecution('automation-dynamic-mockups', {
                operation: 'create_collection',
                name: 'My store',
                catalog_uuid: 'catalog-one',
                psd_uuid: 'stale-psd',
            })
        ).toEqual({
            operation: 'create_collection',
            name: 'My store',
            catalog_uuid: 'catalog-one',
        });
    });

    it('lists under Media & Video with the official mark', () => {
        expect(DynamicMockupsNode.category).toBe('media');
        expect(DynamicMockupsNode.label).toBe('Dynamic Mockups');
        expect(DynamicMockupsNode.type).toBe('automation-dynamic-mockups');
    });
});
