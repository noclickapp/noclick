// Verify the discovered Mem0 schema offers a manual key and all memory tools.
// This guards the provider label and connect method shown across credential surfaces.
import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { methodFromRequirement, credentialRequirements } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-mem0']));
it('exposes Mem0 as a manually pasted API key', () => {
    expect(getNodeCredentialInfo('automation-mem0')?.acceptedTypes).toEqual(['mem0_api_key']);
    expect(getNodeCredentialInfo('automation-mem0')?.label).toBe('Mem0 API Key');
    expect(credentialRequirements('automation-mem0').map(methodFromRequirement)).toEqual([
        expect.objectContaining({ credential_type: 'mem0_api_key', method_kind: 'api_key', is_oauth: false }),
    ]);
});
it('exposes memory reads, writes and async event tracking', () => {
    const operations = getAgentToolOperations('automation-mem0').map(op => op.operation);
    expect(operations).toHaveLength(20);
    expect(operations).toEqual(expect.arrayContaining(['add_memories', 'search_memories', 'update_memory', 'delete_memory', 'get_event', 'batch_delete_memories']));
});
