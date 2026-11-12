// Stigg schema, self-registering definition and credential-cache regressions.
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { StiggNode } from '~/components/workflow/nodes/integrations/stigg';
import { NODE_SCHEMAS, loadNodeSchemas, getAgentToolOperations, getNodeCredentialInfo, isAgentToolProviderType } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { invalidateCredentialsCache, removeCredentialsFromCache, setActiveCredentialWorkflow, upsertCredentialsIntoCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';

const type = 'automation-stigg';
beforeAll(async () => { await loadNodeSchemas([type]); });
const operations = ['get_customer', 'provision_customer', 'update_customer', 'list_products', 'get_paywall',
    'get_entitlements', 'get_entitlement', 'list_active_subscriptions', 'get_active_subscription'];

describe('Stigg native wiring and generated contracts', () => {
    it('uses issued environment server keys and exactly nine native operations', () => {
        expect(StiggNode.type).toBe(type);
        expect(StiggNode.label).toBe('Stigg');
        expect(CREDENTIAL_TYPE_MAP.StiggServerCredential).toBe('stigg_server_api_key');
        expect(getNodeCredentialInfo(type)).toEqual({ providerKey: 'stigg', acceptedTypes: ['stigg_server_api_key'], label: 'Stigg Environment' });
        expect(humanizeCredentialLabel('StiggServer')).toBe('Stigg Server');
        expect(getAgentToolOperations(type).map(op => op.operation).sort()).toEqual([...operations].sort());
        expect(isAgentToolProviderType(type)).toBe(true);
        const credential = NODE_SCHEMAS[type].$defs.StiggServerCredential;
        expect(credential.properties.credential_type.const).toBe('stigg_server_api_key');
        expect(credential.required).toEqual(expect.arrayContaining(['api_key', 'validation_customer_id']));
        expect(credential.properties.api_key['ui:widget']).toBe('password');
        expect(credential['x-oauth-provider']).toBeUndefined();
        expect(credential.properties.client_secret).toBeUndefined();
        expect(credential.properties.environment_id).toBeUndefined();
        expect(credential.properties.endpoint).toBeUndefined();
    });
    it('declares native fields and dependent picker parents', () => {
        const defs = Object.values<any>(NODE_SCHEMAS[type].$defs);
        const check = defs.find(def => def.properties?.operation?.const === 'get_entitlement');
        expect(check.required).toEqual(expect.arrayContaining(['customer_id', 'feature_id']));
        expect(check.properties.query).toBeUndefined();
        expect(check.properties.environmentId).toBeUndefined();
        expect(check.properties.feature_id['x-dynamic-options'].depends_on).toEqual(['customer_id']);
        const write = defs.find(def => def.properties?.operation?.const === 'provision_customer');
        expect(write.required).toEqual(expect.arrayContaining(['customer_id', 'name']));
        expect(write.properties.subscriptionParams).toBeUndefined();
        for (const op of ['provision_subscription', 'report_usage', 'consume_credits', 'grant_promotional_entitlements', 'rotate_api_key'])
            expect(operations).not.toContain(op);
    });
    it('retains the exact official SVG and actual registries', () => {
        const tree = join(__dirname, '../..');
        const svg = readFileSync(join(tree, 'public/icons/stigg.svg'), 'utf8');
        expect(svg).toContain('viewBox="0 0 93 26"');
        expect(svg).toContain('class="stigg-nav-logo"');
        expect(svg).not.toContain('<script');
        expect(StiggNode.category).toBe('developer-tools');
    });
});

describe('real Stigg credential cache selection', () => {
    beforeEach(() => {
        removeCredentialsFromCache(['native-stigg', 'foreign-stigg', 'owner-stigg']);
        invalidateCredentialsCache();
        setActiveCredentialWorkflow('fixture-workflow');
    });
    it('selects only an owned native current descriptor', () => {
        upsertCredentialsIntoCache([
            { id: 'foreign-stigg', credential_type: 'foreign_key', name: 'Foreign', owned_by_me: true },
            { id: 'owner-stigg', credential_type: 'stigg_server_api_key', name: 'Owner descriptor', owned_by_me: false },
        ]);
        expect(autoSelectCredentialFromCache(type)).toEqual({});
        upsertCredentialsIntoCache([{ id: 'native-stigg', credential_type: 'stigg_server_api_key', name: 'Native', owned_by_me: true }]);
        expect(autoSelectCredentialFromCache(type)).toEqual({ stigg_server_api_key: 'native-stigg' });
    });
});
