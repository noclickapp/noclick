import { beforeAll, describe, expect, it } from 'vitest';
import {
    loadNodeSchemas,
    getNodeCredentialInfo,
    getAgentToolOperations,
    getTriggerOperations,
} from '~/utils/nodeSchemas';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';
import { DexNode } from '~/components/workflow/nodes/integrations/dex';

describe('Dex integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-dex']));
    it('offers a manually connectable API key in CRM', async () => {
        const { default: schema } = await import('~/schemas/nodes/dex.json');
        expect(DexNode.category).toBe('crm-sales');
        expect(getNodeCredentialInfo('automation-dex')?.acceptedTypes).toEqual([
            'dex_api_key',
        ]);
        expect(
            requirementsFromSchema(schema).map(methodFromRequirement)
        ).toEqual([
            expect.objectContaining({
                method_kind: 'api_key',
                is_oauth: false,
            }),
        ]);
    });
    it('exposes contact triggers and routine CRM actions', () => {
        const operations = getAgentToolOperations('automation-dex').map(
            (op) => op.operation
        );
        expect(operations).toHaveLength(22);
        expect(operations).toEqual(
            expect.arrayContaining([
                'create_contact',
                'create_note',
                'create_reminder',
            ])
        );
        expect(
            getTriggerOperations('automation-dex').map((op) => op.operation)
        ).toEqual(['on_new_contact', 'on_updated_contact']);
    });
});
