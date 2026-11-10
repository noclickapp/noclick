// Verify that self-registration exposes Tovuti's manual connection and actions.
// This protects the account setup path and keeps poll triggers out of agent tools.
import { beforeAll, expect, it, vi } from 'vitest';

vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({
    valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() },
}));
import {
    loadNodeSchemas,
    getNodeCredentialInfo,
    getAgentToolOperations,
    getNodeSchema,
} from '~/utils/nodeSchemas';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-tovuti']));

it('offers a manually pasted token with no inaccessible required fields', () => {
    expect(getNodeCredentialInfo('automation-tovuti')?.acceptedTypes).toEqual([
        'tovuti_api_token',
    ]);
    const schema = getNodeSchema('automation-tovuti');
    const method = methodFromRequirement(requirementsFromSchema(schema)[0]);
    expect(method).toMatchObject({
        credential_type: 'tovuti_api_token',
        method_kind: 'api_key',
        is_oauth: false,
    });
    expect(method.credential_fields.map((field) => field.name)).toEqual([
        'api_token',
    ]);
});

it('exposes 22 LMS actions to agents', () => {
    const operations = getAgentToolOperations('automation-tovuti').map(
        (op) => op.operation
    );
    expect(operations).toHaveLength(22);
    expect(operations).toContain('create_user');
    expect(operations).toContain('create_assignment');
    expect(operations).toContain('update_course_progress');
    expect(operations.some((op) => op.startsWith('on_updated_'))).toBe(false);
});
