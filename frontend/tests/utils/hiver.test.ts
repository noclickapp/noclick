import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-hiver']));
it('offers a manually entered Hiver API key', () => {
    expect(getNodeCredentialInfo('automation-hiver')?.acceptedTypes).toEqual(['hiver_api_key']);
    expect(getNodeCredentialInfo('automation-hiver')?.label).toBe('Hiver API Key');
    expect(credentialRequirements('automation-hiver').map(req => methodFromRequirement(req).method_kind)).toEqual(['api_key']);
});
it('discovers all twelve published Hiver operations', () => {
    const operations = getAgentToolOperations('automation-hiver').map(op => op.operation);
    expect(operations).toHaveLength(12);
    expect(operations).toContain('create_note');
    expect(operations).toContain('update_conversation');
    expect(operations).toContain('create_shared_draft');
});
