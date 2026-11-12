import { beforeAll, expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations, getTriggerOperations, getNodeSchema } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
beforeAll(() => loadNodeSchemas(['automation-merge-dev']));
it('offers a manual Merge.dev API key connection', () => {
    expect(getNodeCredentialInfo('automation-merge-dev')?.acceptedTypes).toEqual(['merge_dev_api_key']);
    expect(methodFromRequirement(requirementsFromSchema(getNodeSchema('automation-merge-dev'))[0]).method_kind).toBe('api_key');
});
it('exposes 21 actions and three polling triggers', () => {
    expect(getAgentToolOperations('automation-merge-dev')).toHaveLength(21);
    expect(getTriggerOperations('automation-merge-dev')).toHaveLength(3);
});
