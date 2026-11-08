import { beforeAll, describe, expect, it } from 'vitest';
import { SimpleroNode } from '~/components/workflow/nodes/integrations/simplero';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas, NODE_SCHEMAS } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

describe('Simplero integration', () => {
    beforeAll(() => loadNodeSchemas(['automation-simplero']));
    it('offers one pasted API key method with reviewed instructions', () => {
        const schema = NODE_SCHEMAS['automation-simplero'];
        expect(SimpleroNode.type).toBe('automation-simplero');
        expect(SimpleroNode.label).toBe('Simplero');
        expect(getNodeCredentialInfo('automation-simplero')?.acceptedTypes).toEqual(['simplero_api_key']);
        expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
        expect(schema.$defs.SimpleroAPIKeyCredential.title).toBe('Simplero API Key');
        expect(schema.$defs.SimpleroAPIKeyCredential['x-credential-instructions']).toContain('Settings > Integrations');
        expect(schema.$defs.SimpleroAPIKeyCredential.properties.api_key['ui:widget']).toBe('password');
    });
    it('exposes all 24 contact, marketing and sales operations', () => {
        expect(getAgentToolOperations('automation-simplero').map(op => op.operation).sort()).toEqual([
            'add_tag', 'create_customer', 'create_list', 'get_automation', 'get_customer',
            'get_list', 'get_product', 'get_purchase', 'get_subscription', 'get_tag',
            'list_automations', 'list_customers', 'list_lists', 'list_products', 'list_purchases',
            'list_subscriptions', 'list_tags', 'remove_tag', 'start_automation', 'stop_automation',
            'subscribe_contact', 'unsubscribe', 'update_customer', 'update_tag',
        ]);
    });
});
