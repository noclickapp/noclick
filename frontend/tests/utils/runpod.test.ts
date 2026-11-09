import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { RunpodNode } from '../../app/components/workflow/nodes/integrations/runpod';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';

await loadNodeSchemas(['automation-runpod']);
describe('Runpod integration', () => {
    it('discovers cloud hosting and its REST operations', () => {
        expect(RunpodNode.type).toBe('automation-runpod');
        expect(RunpodNode.category).toBe('cloud-hosting');
        const operations = getAgentToolOperations('automation-runpod').map(o => o.operation);
        expect(operations).toHaveLength(23);
        expect(operations).toContain('create_pod');
        expect(operations).toContain('stop_pod');
        expect(operations).toContain('update_endpoint');
        expect(operations).toContain('create_network_volume');
    });
    it('offers a manually pasted API key', () => {
        expect(credentialRequirements('automation-runpod').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-runpod')?.acceptedTypes).toContain('runpod_api_key');
    });
});
