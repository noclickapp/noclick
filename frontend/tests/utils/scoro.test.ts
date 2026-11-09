import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { ScoroNode } from '../../app/components/workflow/nodes/integrations/scoro';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-scoro']);

describe('Scoro integration', () => {
    it('discovers the operations and productivity category', () => {
        expect(ScoroNode.category).toBe('productivity');
        const operations = getAgentToolOperations('automation-scoro').map(op => op.operation);
        expect(operations).toHaveLength(25);
        expect(operations).toEqual(expect.arrayContaining(['create_company', 'update_task', 'create_invoice', 'create_time_entry', 'get_current_user']));
    });

    it('offers the declared OAuth connection', () => {
        const methods = credentialRequirements('automation-scoro').map(methodFromRequirement);
        expect(methods).toEqual([expect.objectContaining({ credential_type: 'scoro_oauth', method_kind: 'oauth', is_oauth: true })]);
        expect(getNodeCredentialInfo('automation-scoro')?.acceptedTypes).toContain('scoro_oauth');
    });
});
