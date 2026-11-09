// SureCart offers a secret API key people can paste by hand. These checks
// pin its catalog label, connection method and commerce action discovery.
import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-surecart']));
it('offers a manually entered SureCart API key', () => {
    expect(getNodeCredentialInfo('automation-surecart')?.acceptedTypes).toEqual(['surecart_api_key']);
    expect(getNodeCredentialInfo('automation-surecart')?.label).toBe('SureCart API Key');
    expect(credentialRequirements('automation-surecart').map(req => methodFromRequirement(req).method_kind)).toEqual(['api_key']);
});
it('discovers twenty-five commerce actions', () => {
    const operations = getAgentToolOperations('automation-surecart').map(op => op.operation);
    expect(operations).toHaveLength(25);
    expect(operations).toContain('create_customer');
    expect(operations).toContain('revoke_purchase');
    expect(operations).toContain('cancel_subscription');
});
