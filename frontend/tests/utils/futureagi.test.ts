import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { FutureagiNode } from '../../app/components/workflow/nodes/integrations/futureagi';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-futureagi']);

describe('Futureagi integration', () => {
    it('discovers annotation reads and writes in AI', () => {
        expect(FutureagiNode.type).toBe('automation-futureagi');
        expect(FutureagiNode.category).toBe('ai');
        const operations = getAgentToolOperations('automation-futureagi').map(op => op.operation);
        expect(operations).toHaveLength(16);
        expect(operations).toContain('list_queues');
        expect(operations).toContain('bulk_create_scores');
        expect(operations).toContain('restore_label');
    });
    it('offers a manual API key credential', () => {
        expect(credentialRequirements('automation-futureagi').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-futureagi')?.acceptedTypes).toContain('futureagi_api_key');
    });
});
