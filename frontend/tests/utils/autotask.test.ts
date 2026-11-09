import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-autotask']));
it('offers a manual Autotask API key', () => {
    expect(getNodeCredentialInfo('automation-autotask')?.acceptedTypes).toEqual(['autotask_api_key']);
    expect(getNodeCredentialInfo('automation-autotask')?.label).toBe('Autotask API Key');
    expect(credentialRequirements('automation-autotask').map(req => methodFromRequirement(req).method_kind)).toEqual(['api_key']);
});
it('exposes twenty read and write actions', () => {
    const operations = getAgentToolOperations('automation-autotask').map(op => op.operation);
    expect(operations).toHaveLength(20);
    expect(operations).toContain('create_ticket');
    expect(operations).toContain('update_company');
    expect(operations).toContain('list_companies');
    expect(operations).toContain('create_ticket_note');
});
