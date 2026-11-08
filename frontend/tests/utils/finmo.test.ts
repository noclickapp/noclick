import { beforeAll, expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getAgentToolOperations } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
import { NODE_SCHEMAS } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-finmo']));
it('offers pasted Finmo keys and fixed operations', () => {
    const schema = NODE_SCHEMAS['automation-finmo'];
    const methods = requirementsFromSchema(schema).map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0]).toMatchObject({ credential_type: 'finmo_api_key', method_kind: 'api_key', is_oauth: false });
    expect(getAgentToolOperations('automation-finmo')).toHaveLength(22);
});
