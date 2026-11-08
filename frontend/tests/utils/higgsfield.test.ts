import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-higgsfield']));

it('offers a pasted Higgsfield API key and ten generation and lifecycle actions', () => {
    expect(getNodeCredentialInfo('automation-higgsfield')?.acceptedTypes).toEqual(['higgsfield_api_key']);
    expect(getCredentialTypeFromSchemaTitle('Higgsfield API Key')).toBe('higgsfield_api_key');
    expect(credentialRequirements('automation-higgsfield').map(methodFromRequirement).map(method => method.method_kind)).toEqual(['api_key']);
    const operations = getAgentToolOperations('automation-higgsfield').map(op => op.operation);
    expect(operations).toHaveLength(10);
    expect(operations).toContain('generate_soul_image');
    expect(operations).toContain('get_request_outputs');
    expect(operations).toContain('cancel_request');
    expect(operations).toContain('delete_request');
});
