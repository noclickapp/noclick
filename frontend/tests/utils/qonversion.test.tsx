// Actual generated native schema, node definition and credential-cache fixtures.
// Covers read-only scope and Secret Key selection without asserting live account or entitlement access.
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import schema from '~/schemas/nodes/qonversion.json';
import { QonversionNode } from '~/components/workflow/nodes/integrations/qonversion';
import { NODE_SCHEMAS, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { isAgentToolProviderType, isTriggerSource } from '~/utils/nodeMeta';

const boundary=vi.hoisted(()=>({send:vi.fn(),get:vi.fn(),set:vi.fn(),delete:vi.fn()}));
vi.mock('~/lib/socket-sender',()=>({sendEventAsync:boundary.send}));
vi.mock('~/lib/indexeddb',()=>({valtioCache:{get:boundary.get,set:boundary.set,delete:boundary.delete}}));
const { prefetchCredentials, invalidateCredentialsCache, removeCredentialsFromCache, upsertCredentialsIntoCache }=await import('~/utils/credentialAutoSelect');
const { autoSelectCredentialFromCache } = await import('~/utils/credentialAutoSelectForNode');
beforeAll(async () => { await loadNodeSchemas(['automation-qonversion']); });
beforeEach(()=>{invalidateCredentialsCache();vi.clearAllMocks();boundary.get.mockResolvedValue(undefined);});
afterEach(()=>{removeCredentialsFromCache(['qon-healthy','qon-revoked','qon-shared','foreign']);invalidateCredentialsCache();});

describe('native Qonversion v4 metadata',()=>{
    it('registers the Secret Key and exact eight reads without SDK or mutations',()=>{
        expect(NODE_SCHEMAS['automation-qonversion']).toBe(schema);
        expect(getNodeCredentialInfo('automation-qonversion')).toEqual({providerKey:'qonversion',acceptedTypes:['qonversion_secret_key'],label:'Qonversion Secret Key'});
        expect(schema.$defs.QonversionSecretKeyCredential.properties.secret_key['ui:widget']).toBe('password');
        expect(schema.$defs.QonversionSecretKeyCredential.properties.credential_type.const).toBe('qonversion_secret_key');
        expect(schema.$defs.QonversionSecretKeyCredential).not.toHaveProperty('x-oauth-provider');
        expect(Object.keys(schema.properties.config.discriminator.mapping).sort()).toEqual(['check_connection','get_entitlement_definition','get_product','get_remote_configuration','get_user','list_entitlement_definitions','list_products','list_remote_configurations']);
        expect(schema.$defs.GetUser.required).toContain('confirm_user_metadata');
        expect(schema.$defs.GetUser.required).toContain('expected_environment');
        expect(schema.$defs.ListProducts.properties.limit.maximum).toBe(100);
        expect(schema.$defs.ListProducts.properties).not.toHaveProperty('starting_after');
        expect(schema.$defs.ListProducts.properties).not.toHaveProperty('environment');
        expect(isAgentToolProviderType(QonversionNode.type)).toBe(true);
        expect(isTriggerSource(QonversionNode.type,'list_products')).toBe(false);
    });
    it('prefetches only healthy owned native keys through actual selection/cache',async()=>{
        boundary.send.mockResolvedValue({credentials:[
            {id:'foreign',name:'Foreign',credential_type:'slack_oauth',updated_at:'2026-10-07T01:00:00Z'},
            {id:'qon-revoked',name:'Revoked',credential_type:'qonversion_secret_key',revoked_at:'2026-10-07T00:00:00Z',updated_at:'2026-10-07T00:00:00Z'},
            {id:'qon-healthy',name:'Fixture Qonversion',credential_type:'qonversion_secret_key',updated_at:'2026-10-06T23:00:00Z'},
        ]});
        await prefetchCredentials();upsertCredentialsIntoCache([{id:'qon-shared',name:'Shared descriptor',credential_type:'qonversion_secret_key',owned_by_me:false}]);
        expect(autoSelectCredentialFromCache('automation-qonversion')).toEqual({qonversion_secret_key:'qon-healthy'});
        expect(boundary.send).toHaveBeenCalledTimes(1);expect(boundary.send.mock.calls[0][0].event_name).toBe('credential:list');
    });
    it('renders the provider vector mark',()=>{
        expect(renderToStaticMarkup(<QonversionNode.Icon />)).toContain('/icons/qonversion-brand-vector.svg');
    });
});
