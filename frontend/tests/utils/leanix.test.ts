import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ send: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: mocks.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(async () => null), set: vi.fn(async () => undefined) } }));
import schema from '~/schemas/nodes/leanix.json';
import { loadNodeSchemas, getNodeSchema, filterConfigForExecution, getAgentToolOperations, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { upsertCredentialsIntoCache, removeCredentialsFromCache } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache } from '~/utils/credentialAutoSelectForNode';
import { LeanIXNode } from '~/components/workflow/nodes/integrations/leanix';
const type = 'automation-leanix';
beforeEach(() => mocks.send.mockReset());
describe('SAP LeanIX actual native consumers', () => {
    beforeAll(async () => { await loadNodeSchemas([type]); });
    it('resolves the supplied token family, five reads and current type parent', () => {
        expect(LeanIXNode.type).toBe(type);
        expect(getNodeSchema(type)).toEqual(schema);
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['leanix_api_token']);
        expect(schema.$defs.LeanIXApiTokenCredential.properties.api_token['ui:widget']).toBe('password');
        expect(schema.$defs.LeanIXApiTokenCredential.required).toEqual(expect.arrayContaining(['api_token', 'workspace_subdomain', 'witness_fact_sheet_id']));
        expect(schema.$defs.GetFactSheet.properties.fact_sheet_id['x-dynamic-options']).toMatchObject({ field_name: 'fact_sheet_id', depends_on: 'fact_sheet_type' });
        expect(getAgentToolOperations(type)).toHaveLength(5);
    });
    it('selects a saved native family', () => {
        const family = 'leanix_api_token';
        try {
            upsertCredentialsIntoCache([{ id: 'leanix-owned', name: 'LeanIX', credential_type: family, owned_by_me: true }]);
            expect(autoSelectCredentialFromCache(type)).toEqual({ [family]: 'leanix-owned' });
        } finally { removeCredentialsFromCache(['leanix-owned']); }
    });
    it('filters known paging/fit fields and preserves actual unknown sidecar behavior', () => {
        const result = filterConfigForExecution(type, { operation: 'test_authentication', technical_fit: 'unreasonable', page_size: 10,
            fact_sheet_id: '00000000-0000-4000-8000-000000000042', endpoint: 'unknown-sidecar' });
        expect(result).toMatchObject({ operation: 'test_authentication', endpoint: 'unknown-sidecar' });
        expect(result.fact_sheet_id).toBeUndefined();
        expect(result.technical_fit).toBeUndefined();
        expect(result.page_size).toBeUndefined();
    });
});
