import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ send: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: mocks.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(async () => null), set: vi.fn(async () => undefined) } }));
import schema from '~/schemas/nodes/adyen.json';
import { loadNodeSchemas, NODE_SCHEMAS, filterConfigForExecution, getAgentToolOperations, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { prefetchCredentials } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache, autoSelectCredentialsForNewNode } from '~/utils/credentialAutoSelectForNode';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { AdyenNode } from '~/components/workflow/nodes/integrations/adyen';
const type = 'automation-adyen';
beforeEach(async () => { mocks.send.mockReset(); await loadNodeSchemas([type]); });
describe('Adyen actual native consumers', () => {
    it('resolves the API key family, native operations and dependent store selectors', () => {
        expect(AdyenNode.type).toBe(type);
        expect(NODE_SCHEMAS[type]).toBeDefined();
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['adyen_api_key']);
        expect(schema.$defs.AdyenApiKeyCredential.properties.api_key['ui:widget']).toBe('password');
        expect(schema.$defs.AdyenApiKeyCredential.required).toContain('expected_api_credential_id');
        expect(schema.$defs.GetStore.properties.store_id['x-dynamic-options']).toMatchObject({ field_name: 'store_id', depends_on: 'merchant_id' });
        expect(getAgentToolOperations(type)).toHaveLength(8);
        expect(humanizeCredentialLabel('AdyenApiKey')).toBe('Adyen API Key');
    });
    it('selects the saved native family and preserves explicit selection', async () => {
        const family = 'adyen_api_key';
        mocks.send.mockResolvedValue({ credentials: [{ id: 'owned-fixture', credential_type: family, updated_at: '2026-10-06T00:00:00Z' }] });
        await prefetchCredentials();
        expect(autoSelectCredentialFromCache(type)).toEqual({ [family]: 'owned-fixture' });
        const setNodes = vi.fn();
        autoSelectCredentialsForNewNode({ id: 'native-fixture', type, position: { x: 0, y: 0 }, data: { credentialIds: { [family]: 'owned-fixture' } } }, setNodes, 'owned-workflow-fixture');
        expect(setNodes).not.toHaveBeenCalled();
    });
    it('filters known store writes and retains unknown sidecars for backend rejection', () => {
        const result = filterConfigForExecution(type, { operation: 'list_merchants', page_size: 50,
            description: 'private-description', confirm_store_change: true, store_id: 'STORE', endpoint: 'unknown-sidecar' });
        expect(result).toMatchObject({ operation: 'list_merchants', page_size: 50, endpoint: 'unknown-sidecar' });
        expect(result.description).toBeUndefined();
        expect(result.confirm_store_change).toBeUndefined();
        expect(result.store_id).toBeUndefined();
    });
});
