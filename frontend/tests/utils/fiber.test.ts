import { beforeAll, expect, it, vi } from 'vitest';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, getNodeSchema, getAgentToolOperations, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-fiber']));
it('offers a manually entered Fiber API key and resolves both schema aliases', () => {
    expect(getCredentialTypeFromSchemaTitle('FiberAPIKeyCredential')).toBe('fiber_api_key');
    expect(getCredentialTypeFromSchemaTitle('Fiber API Key')).toBe('fiber_api_key');
    expect(getNodeCredentialInfo('automation-fiber')?.acceptedTypes).toEqual(['fiber_api_key']);
    const requirements = requirementsFromSchema(getNodeSchema('automation-fiber'));
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0])).toMatchObject({ method_kind: 'api_key', is_oauth: false });
});
it('exposes prospecting, audience management and explicit enrichment operations', () => {
    const operations = getAgentToolOperations('automation-fiber').map(op => op.operation);
    expect(operations).toHaveLength(19);
    expect(operations).toEqual(expect.arrayContaining([
        'list_audiences', 'create_audience', 'archive_audience', 'search_companies',
        'search_people', 'resolve_people', 'find_work_email', 'estimate_enrichment', 'start_enrichment',
    ]));
});
