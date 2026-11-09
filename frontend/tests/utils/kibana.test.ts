import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { KibanaNode } from '../../app/components/workflow/nodes/integrations/kibana';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-kibana']);

describe('Kibana integration', () => {
    it('offers 22 published operations in monitoring', () => {
        expect(KibanaNode.category).toBe('monitoring');
        const operations = getAgentToolOperations('automation-kibana').map(op => op.operation);
        expect(operations).toHaveLength(22);
        expect(operations).toContain('create_data_view');
        expect(operations).toContain('enable_rule');
        expect(operations).toContain('list_spaces');
    });
    it('connects with a manually supplied API key', () => {
        expect(credentialRequirements('automation-kibana').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-kibana')?.acceptedTypes).toContain('kibana_api_key');
    });
});
