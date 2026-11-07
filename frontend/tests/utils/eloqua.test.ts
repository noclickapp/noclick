import { beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ send: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: mocks.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(async () => null), set: vi.fn(async () => undefined) } }));
import schema from '~/schemas/nodes/eloqua.json';
import { NODE_SCHEMAS, filterConfigForExecution, getAgentToolOperations, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { prefetchCredentials } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache, autoSelectCredentialsForNewNode } from '~/utils/credentialAutoSelectForNode';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { EloquaNode } from '~/components/workflow/nodes/integrations/eloqua';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
vi.mock('~/components/workflow/nodes/base/AutomationNode', () => ({ default: () => null }));
await loadNodeSchemas(['automation-eloqua']);
const type = 'automation-eloqua';
beforeEach(() => mocks.send.mockReset());
describe('Eloqua actual native consumers', () => {
    it('resolves both supplied families and the actual typed schema', () => {
        expect(EloquaNode.type).toBe(type);
        expect(NODE_SCHEMAS[type]).toBeDefined();
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['eloqua_basic', 'eloqua_bearer_token']);
        expect(schema.$defs.EloquaBasicCredential.properties.password['ui:widget']).toBe('password');
        expect(schema.$defs.EloquaBearerTokenCredential.required).toContain('expires_at');
        expect(getAgentToolOperations(type)).toHaveLength(21);
        expect(schema.$defs.GetContact.properties.contact_id['x-dynamic-options']).toMatchObject({ field_name: 'contact_id', searchable: true, allow_custom: true });
        expect(humanizeCredentialLabel('Oracle Eloqua Basic Authentication')).toBe('Oracle Eloqua Basic Authentication');
        expect(humanizeCredentialLabel('Oracle Eloqua Issued Bearer Token')).toBe('Oracle Eloqua Issued Bearer Token');
        for (const req of requirementsFromSchema(schema)) {
            const method = methodFromRequirement(req);
            expect(method.method_kind).toBe('api_key');
            expect(method.is_oauth).toBe(false);
        }
    });
    it.each(['eloqua_basic', 'eloqua_bearer_token'])('uses staging default selection and preserves explicit %s selection', async family => {
        mocks.send.mockResolvedValue({ credentials: [{ id: 'owned-fixture', credential_type: family, updated_at: '2026-10-06T00:00:00Z' }] });
        await prefetchCredentials();
        expect(autoSelectCredentialFromCache(type)).toEqual(family === 'eloqua_basic' ? { [family]: 'owned-fixture' } : {});
        const setNodes = vi.fn();
        autoSelectCredentialsForNewNode({ id: 'native-fixture', type, position: { x: 0, y: 0 }, data: { credentialIds: { [family]: 'owned-fixture' } } }, setNodes, 'owned-workflow-fixture');
        expect(setNodes).not.toHaveBeenCalled();
    });
    it('filters known write fields and retains unknown sidecars for backend rejection', () => {
        const result = filterConfigForExecution(type, { operation: 'list_contacts', count: 50,
            email_address: 'private@example.test', record_id: '40', endpoint: 'unknown-sidecar' });
        expect(result).toMatchObject({ operation: 'list_contacts', count: 50, endpoint: 'unknown-sidecar' });
        expect(result.email_address).toBeUndefined();
        expect(result.record_id).toBeUndefined();
    });
});
