// Exercise Crelate metadata, credential selection and operation filtering.
// These checks use the discovered integration definition and generated schema.
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ send: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: mocks.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(async () => null), set: vi.fn(async () => undefined) } }));
import schema from '~/schemas/nodes/crelate.json';
import { NODE_SCHEMAS, filterConfigForExecution, getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { cachedCredentialsOfType, prefetchCredentials } from '~/utils/credentialAutoSelect';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { CrelateNode } from '~/components/workflow/nodes/integrations/crelate';
const type = 'automation-crelate';
beforeAll(() => loadNodeSchemas([type]));
beforeEach(() => mocks.send.mockReset());
describe('Crelate native schema and actual canvas selection', () => {
    it('resolves native API3 fields and a header key without fabricated OAuth', () => {
        expect(CrelateNode.type).toBe(type);
        expect(NODE_SCHEMAS[type]).toBeDefined();
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['crelate_api_key']);
        expect(schema.$defs.CrelateAPIKeyCredential.properties.api_key['ui:widget']).toBe('password');
        expect(schema.$defs.CrelateAPIKeyCredential.required).toContain('api_key');
        expect(getAgentToolOperations(type)).toHaveLength(30);
        expect(humanizeCredentialLabel('CrelateAPIKey')).toBe('Crelate API Key');
    });
    it('loads the stored Crelate family into the credential cache', async () => {
        mocks.send.mockResolvedValue({ credentials: [{ id: 'owned-fixture', credential_type: 'crelate_api_key', updated_at: '2026-10-06T00:00:00Z' }] });
        await prefetchCredentials();
        expect(cachedCredentialsOfType('crelate_api_key')?.map(credential => credential.id)).toEqual(['owned-fixture']);
    });
    it('filters known write fields and retains unknown sidecars for backend rejection', () => {
        const result = filterConfigForExecution(type, { operation: 'list_contacts', limit: 50,
            display: 'Known write field', task_id: '00000000-0000-4000-8000-000000000030', endpoint: 'unknown-sidecar' });
        expect(result).toMatchObject({ operation: 'list_contacts', limit: 50, endpoint: 'unknown-sidecar' });
        expect(result.display).toBeUndefined();
        expect(result.task_id).toBeUndefined();
    });
});
