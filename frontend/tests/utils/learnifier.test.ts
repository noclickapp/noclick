// Learnifier must offer a complete manual API connection and useful agent actions.
// These checks cover the generated schema and metadata consumed by the shared UI.
import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-learnifier']));
it('offers a manual Learnifier API key and secret', () => {
    expect(getNodeCredentialInfo('automation-learnifier')?.acceptedTypes).toEqual(['learnifier_api_key']);
    expect(getNodeCredentialInfo('automation-learnifier')?.label).toBe('Learnifier API Key');
    const methods = credentialRequirements('automation-learnifier').map(methodFromRequirement);
    expect(methods.map(method => method.method_kind)).toEqual(['api_key']);
});
it('exposes learner, enrollment and award actions to agents', () => {
    const operations = getAgentToolOperations('automation-learnifier').map(op => op.operation);
    expect(operations).toHaveLength(23);
    expect(operations).toContain('create_user');
    expect(operations).toContain('create_participant');
    expect(operations).toContain('create_user_award');
});
