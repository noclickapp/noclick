// Self-registering Mirakl schema, definition and credential selection contracts.
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { MiraklNode } from '~/components/workflow/nodes/integrations/mirakl';
import { NODE_SCHEMAS, loadAllNodeSchemas, getAgentToolOperations, getNodeCredentialInfo, filterConfigForExecution, isAgentToolProviderType } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { invalidateCredentialsCache, removeCredentialsFromCache, setActiveCredentialWorkflow, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';

import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';

await loadAllNodeSchemas();
const type = 'automation-mirakl';
const operations = ["get_access_scope","get_shop","list_categories","list_product_attributes","list_channels","list_currencies","list_locales","list_offer_states","get_values_list","get_products","list_shop_offers","get_offer","list_orders","create_offer","replace_offer","delete_offer","get_offer_import"];
describe('Mirakl native source and generated artifacts', () => {
    it('wires an issued MAS token and exactly seventeen scoped operations', () => {
        expect(MiraklNode.type).toBe(type);
        expect(MiraklNode.label).toBe('Mirakl');
        expect(CREDENTIAL_TYPE_MAP.MiraklMASCredential).toBe('mirakl_mas_token');
        expect(getNodeCredentialInfo(type)).toEqual({ providerKey: 'mirakl', acceptedTypes: ['mirakl_mas_token'], label: 'Mirakl Platform' });
        expect(humanizeCredentialLabel('Mirakl Platform')).toBe('Mirakl Platform');
        expect(getAgentToolOperations(type).map(op => op.operation).sort()).toEqual([...operations].sort());
        expect(isAgentToolProviderType(type)).toBe(true);
        expect(credentialRequirements(type).map(req => methodFromRequirement(req).method_kind)).toEqual(['api_key']);
        const cred = NODE_SCHEMAS[type].$defs.MiraklMASCredential;
        expect(cred.properties.credential_type.const).toBe('mirakl_mas_token');
        expect(cred.required).toEqual(expect.arrayContaining(['access_token', 'marketplace_url', 'marketplace_id', 'role', 'shop_id']));
        expect(cred.properties.access_token['ui:widget']).toBe('password');
        expect(cred['x-oauth-provider']).toBeUndefined();
        expect(cred.properties.client_secret).toBeUndefined();
        expect(cred.properties.password).toBeUndefined();
    });
    it('filters stale payload and preserves scoped parents and explicit reset acknowledgment', () => {
        expect(filterConfigForExecution(type, { operation: 'list_orders', limit: 50, offset: 0, offer_id: 22, shop_sku: 'stale' }))
            .toEqual({ operation: 'list_orders', limit: 50, offset: 0 });
        const defs = Object.values<any>(NODE_SCHEMAS[type].$defs);
        const get = defs.find(def => def.properties?.operation?.const === 'get_offer');
        expect(get.required).toEqual(expect.arrayContaining(['offer_id', 'product_sku']));
        const replace = defs.find(def => def.properties?.operation?.const === 'replace_offer');
        expect(replace.required).toEqual(expect.arrayContaining(['offer_id', 'shop_sku', 'price', 'quantity', 'acknowledge_field_resets']));
        expect(replace.properties.acknowledge_field_resets.const).toBe(true);
        for (const op of ['accept_order', 'ship_order', 'refund_order', 'create_product_import', 'send_message', 'get_download_url'])
            expect(operations).not.toContain(op);
    });
    it('retains the exact official wordmark and actual registrations', () => {
        const tree = join(__dirname, '../..');
        expect(readFileSync(join(tree, 'public/icons/mirakl.svg'), 'utf8')).toContain('viewBox="0 0 306 67"');
        expect(readFileSync(join(tree, 'app/components/workflow/nodes/integrations/mirakl.tsx'), 'utf8')).toContain("type: 'automation-mirakl'");
        expect(readFileSync(join(tree, 'app/schemas/nodeMeta/mirakl.json'), 'utf8')).toContain('mirakl_mas_token');
    });
});
describe('real Mirakl credential cache selection', () => {
    beforeEach(() => {
        removeCredentialsFromCache(['native-mirakl', 'foreign-mirakl', 'owner-mirakl']);
        invalidateCredentialsCache();
        setActiveCredentialWorkflow('fixture-workflow');
    });
    it('selects only the owned native current descriptor', () => {
        upsertCredentialsIntoCache([
            { id: 'foreign-mirakl', credential_type: 'foreign_token', name: 'Foreign', owned_by_me: true },
            { id: 'owner-mirakl', credential_type: 'mirakl_mas_token', name: 'Owner descriptor', owned_by_me: false },
        ]);
        expect(autoSelectCredentialFromCache(type)).toEqual({});
        upsertCredentialsIntoCache([{ id: 'native-mirakl', credential_type: 'mirakl_mas_token', name: 'Native', owned_by_me: true }]);
        expect(autoSelectCredentialFromCache(type)).toEqual({ mirakl_mas_token: 'native-mirakl' });
    });
});
