import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { ConvertAPINode } from '../../app/components/workflow/nodes/integrations/convertapi';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';
await loadNodeSchemas(['automation-convertapi']);
describe('ConvertAPI integration', () => {
  it('exposes sixteen fixed operations', () => {
    expect(ConvertAPINode.type).toBe('automation-convertapi');
    expect(getAgentToolOperations('automation-convertapi')).toHaveLength(16);
  });
  it('offers a pasted secret', () => {
    expect(credentialRequirements('automation-convertapi').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
    expect(getNodeCredentialInfo('automation-convertapi')?.acceptedTypes).toContain('convertapi_api_secret');
  });
});
