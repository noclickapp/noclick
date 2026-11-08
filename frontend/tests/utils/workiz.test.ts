import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { WorkizNode } from '../../app/components/workflow/nodes/integrations/workiz';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';
import { humanizeCredentialLabel } from '../../app/utils/credentialLabels';

await loadNodeSchemas(['automation-workiz']);
describe('Workiz integration', () => {
  it('offers the contract operations', () => {
    expect(WorkizNode.type).toBe('automation-workiz');
    expect(getAgentToolOperations('automation-workiz')).toHaveLength(23);
    expect(getAgentToolOperations('automation-workiz').map(o => o.operation)).toContain('convert_lead');
  });
  it('offers a manually pasted token with a readable label', () => {
    expect(credentialRequirements('automation-workiz').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
    expect(getNodeCredentialInfo('automation-workiz')?.acceptedTypes).toContain('workiz_api_token');
    expect(humanizeCredentialLabel('Workiz API Token')).toBe('Workiz API Token');
  });
});
