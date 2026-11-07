// ClickFunnels must appear with its full operation schema and select the saved API key on canvas add.
// These tests cover the registration seams users depend on before their first workflow execution.
import { describe, expect, it } from 'vitest';
import { upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { loadNodeSchemas, NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { NODE_DEFINITION_FILES } from '~/components/workflow/nodes/nodeDefinitions';

describe('ClickFunnels registration', () => {
    it('loads all twenty documented operations with the manual credential', async () => {
        await loadNodeSchemas(['automation-clickfunnels']);
        const schema = NODE_SCHEMAS['automation-clickfunnels'];
        const operations = Object.values(schema.$defs ?? {})
            .map((definition: any) => definition.properties?.operation?.const)
            .filter(Boolean);
        expect(operations).toHaveLength(20);
        expect(operations).toEqual(expect.arrayContaining(['create_contact', 'apply_contact_tag', 'create_order', 'create_invoice', 'create_enrollment']));
        expect(NODE_DEFINITION_FILES).toContainEqual(['automation-clickfunnels', 'integrations/clickfunnels']);
        expect(schema.$defs?.ClickFunnelsAPIKeyCredential.properties.api_key['ui:widget']).toBe('password');
    });

    it('selects the saved ClickFunnels API key from the node schema', async () => {
        await loadNodeSchemas(['automation-clickfunnels']);
        upsertCredentialsIntoCache([{
            id: 'clickfunnels-test-credential', name: 'ClickFunnels test',
            credential_type: 'clickfunnels_api_key', owned_by_me: true,
        }]);
        expect(autoSelectCredentialFromCache('automation-clickfunnels')).toEqual({
            clickfunnels_api_key: 'clickfunnels-test-credential',
        });
    });
});
