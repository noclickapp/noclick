import { beforeAll, expect, it } from 'vitest';
import { MemNode } from '~/components/workflow/nodes/integrations/mem';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-mem']));

it('offers a Mem API key and discovers the native operations', () => {
    expect(MemNode.type).toBe('automation-mem');
    expect(MemNode.label).toBe('Mem');
    expect(CREDENTIAL_TYPE_MAP['Mem API Key']).toBe('mem_api_key');
    expect(getNodeCredentialInfo('automation-mem')?.acceptedTypes).toEqual(['mem_api_key']);
    const methods = credentialRequirements('automation-mem').map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0].method_kind).toBe('api_key');
    expect(methods[0].is_oauth).toBe(false);
    expect(methods[0].credential_fields.map(field => field.name)).toEqual(['api_key']);
    const ops = getAgentToolOperations('automation-mem').map(op => op.operation);
    expect(ops).toHaveLength(20);
    expect(ops).toContain('update_note');
    expect(ops).toContain('move_note');
    expect(ops).toContain('mem_it');
});
