// Verify that Alegra exposes a manual token connection and discoverable sales tools.
// The generated metadata must also distinguish its event triggers from agent tools.
import { expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { AlegraNode } from '../../app/components/workflow/nodes/integrations/alegra';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-alegra']);

it('places Alegra in accounting with sales tools and a pasted token', () => {
    expect(AlegraNode.category).toBe('finance-accounting');
    const operations = getAgentToolOperations('automation-alegra').map(op => op.operation);
    expect(operations).toHaveLength(20);
    expect(operations).toContain('create_invoice');
    expect(operations).not.toContain('on_new_invoice');
    expect(credentialRequirements('automation-alegra').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
    expect(getNodeCredentialInfo('automation-alegra')?.acceptedTypes).toContain('alegra_api_token');
});
