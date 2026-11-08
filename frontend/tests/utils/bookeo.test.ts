// Prepared source only. Native generation and a root frontend lane are required.
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ send: vi.fn() }));
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: mocks.send }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(async () => null), set: vi.fn(async () => undefined) } }));
import schema from '~/schemas/nodes/bookeo.json';
import { NODE_SCHEMAS, filterConfigForExecution, getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { prefetchCredentials } from '~/utils/credentialAutoSelect';
import { autoSelectCredentialFromCache, autoSelectCredentialsForNewNode } from '~/utils/credentialAutoSelectForNode';
import { humanizeCredentialLabel } from '~/utils/credentialLabels';
import { BookeoNode } from '~/components/workflow/nodes/integrations/bookeo';
const type = 'automation-bookeo';
beforeAll(async () => { await loadNodeSchemas([type]); });
beforeEach(() => mocks.send.mockReset());

describe('Bookeo native schema, credential families and canvas selection', () => {
    it('resolves the actual schema and key/token widgets with native OAuth and retained manual choices', () => {
        expect(BookeoNode.type).toBe(type);
        expect(NODE_SCHEMAS[type]).toBeDefined();
        expect(getNodeCredentialInfo(type)?.acceptedTypes).toEqual(['bookeo_oauth', 'bookeo_api_key', 'bookeo_bearer_token']);
        expect(schema.$defs.BookeoAPIKeyCredential.properties.secret_key['ui:widget']).toBe('password');
        expect(schema.$defs.BookeoAPIKeyCredential.properties.api_key['ui:widget']).toBe('password');
        expect(schema.$defs.BookeoBearerTokenCredential.required).toContain('expires_at');
        expect(getAgentToolOperations(type)).toHaveLength(16);
        expect(humanizeCredentialLabel(schema.$defs.BookeoAPIKeyCredential.title)).toBe('Bookeo API Key');
    });
    it.each(['bookeo_oauth', 'bookeo_api_key', 'bookeo_bearer_token'])('preserves the real first-family canvas contract for %s', async family => {
        mocks.send.mockResolvedValue({ credentials: [{ id: 'owned-fixture', credential_type: family, updated_at: '2026-10-06T00:00:00Z' }] });
        await prefetchCredentials();
        expect(autoSelectCredentialFromCache(type)).toEqual(family === 'bookeo_oauth' ? { [family]: 'owned-fixture' } : {});
        const setNodes = vi.fn();
        autoSelectCredentialsForNewNode({ id: 'native-fixture', type, position: { x: 0, y: 0 },
            data: { credentialIds: { [family]: 'owned-fixture' } } }, setNodes, 'owned-workflow-fixture');
        expect(setNodes).not.toHaveBeenCalled(); // Explicit Bearer selection survives.
    });
    it('filters known write fields while retaining unknown sidecars under the actual shared contract', () => {
        const result = filterConfigForExecution(type, { operation: 'list_customers', items_per_page: 50,
            people_numbers: [{ people_category_id: 'adult', number: 1 }], event_id: 'event42', endpoint: 'unknown-sidecar' });
        expect(result).toMatchObject({ operation: 'list_customers', items_per_page: 50, endpoint: 'unknown-sidecar' });
        expect(result.people_numbers).toBeUndefined();
        expect(result.event_id).toBeUndefined();
        // The real backend factory rejects the retained arbitrary sidecar.
    });
});
