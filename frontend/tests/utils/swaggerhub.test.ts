import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { SwaggerHubNode } from '../../app/components/workflow/nodes/integrations/swaggerhub';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-swaggerhub']);
describe('SwaggerHub integration', () => {
  it('exposes the Registry API operations in developer tools', () => {
    expect(SwaggerHubNode.category).toBe('developer-tools');
    expect(getAgentToolOperations('automation-swaggerhub')).toHaveLength(21);
  });
  it('connects using a manually supplied API key', () => {
    expect(credentialRequirements('automation-swaggerhub').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
    expect(getNodeCredentialInfo('automation-swaggerhub')?.acceptedTypes).toContain('swaggerhub_api_key');
  });
});
