import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { createElement, type ComponentType } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import schema from '~/schemas/nodes/sap-concur.json';
import { SAPConcurNode } from '~/components/workflow/nodes/integrations/sap-concur';
import { NODE_SCHEMAS, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { isAgentToolProviderType, isTriggerSource } from '~/utils/nodeMeta';

const boundary = vi.hoisted(() => ({ send: vi.fn(), get: vi.fn(), set: vi.fn(), delete: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: boundary.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: boundary.get, set: boundary.set, delete: boundary.delete } }));
const { prefetchCredentials, invalidateCredentialsCache, removeCredentialsFromCache, upsertCredentialsIntoCache } = await import('~/utils/credentialAutoSelect');
const { autoSelectCredentialFromCache } = await import('~/utils/credentialAutoSelectForNode');
beforeAll(() => loadNodeSchemas(['automation-sap-concur']));
beforeEach(() => { invalidateCredentialsCache(); vi.clearAllMocks(); boundary.get.mockResolvedValue(undefined); });
afterEach(() => { removeCredentialsFromCache(['concur-healthy', 'concur-revoked', 'concur-owner', 'foreign']); invalidateCredentialsCache(); });

describe('native SAP Concur configuration, saved selection and official asset', () => {
    it('uses issued OAuth tokens, regional binding and thirteen closed operations', () => {
        expect(NODE_SCHEMAS['automation-sap-concur']).toBeDefined();
        expect(getNodeCredentialInfo('automation-sap-concur')).toEqual({ providerKey: 'sap_concur', acceptedTypes: ['sap_concur_oauth'], label: 'SAP Concur OAuth Tokens' });
        const credential = schema.$defs.SAPConcurOAuthCredential;
        expect(credential.properties.credential_type.const).toBe('sap_concur_oauth');
        expect(credential.properties.access_token['ui:widget']).toBe('password');
        expect(credential.properties.client_secret['ui:widget']).toBe('password');
        expect(credential.required).toEqual(expect.arrayContaining(['access_token', 'geolocation']));
        expect(credential.properties.geolocation.enum).toHaveLength(5);
        expect(credential).not.toHaveProperty('x-oauth-provider');
        expect(Object.keys(schema.properties.config.discriminator.mapping)).toHaveLength(13);
        expect(schema.$defs.GetItem.properties.item_id['x-dynamic-options'].depends_on).toBe('list_id');
        expect(schema.$defs.CreateList.required).toEqual(expect.arrayContaining(['value', 'confirm_configuration_change']));
        expect(schema.$defs.CreateItem.required).toEqual(expect.arrayContaining(['list_id', 'value', 'short_code', 'confirm_configuration_change']));
        expect(isAgentToolProviderType(SAPConcurNode.type)).toBe(true);
        expect(isTriggerSource(SAPConcurNode.type, 'list_lists')).toBe(false);
    });
    it('selects a healthy owned native connection from actual prefetch and cache', async () => {
        boundary.send.mockResolvedValue({ credentials: [
            { id: 'foreign', name: 'Foreign', credential_type: 'slack_oauth', updated_at: '2026-10-06T12:00:00Z' },
            { id: 'concur-revoked', name: 'Revoked', credential_type: 'sap_concur_oauth', revoked_at: '2026-10-06T11:00:00Z', updated_at: '2026-10-06T11:00:00Z' },
            { id: 'concur-healthy', name: 'Fixture SAP Concur', credential_type: 'sap_concur_oauth', updated_at: '2026-10-06T10:00:00Z' },
        ] });
        await prefetchCredentials();
        upsertCredentialsIntoCache([{ id: 'concur-owner', name: 'Owner descriptor', credential_type: 'sap_concur_oauth', owned_by_me: false }]);
        expect(autoSelectCredentialFromCache('automation-sap-concur')).toEqual({ sap_concur_oauth: 'concur-healthy' });
        expect(boundary.send).toHaveBeenCalledTimes(1);
        expect(boundary.send.mock.calls[0][0].event_name).toBe('credential:list');
    });
    it('renders the exact official SVG path', () => {
        expect(renderToStaticMarkup(createElement(SAPConcurNode.Icon as ComponentType))).toContain('/icons/sap-concur-brand.svg');
    });
});
