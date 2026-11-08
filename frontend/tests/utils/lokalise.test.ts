// Verify Lokalise discovery and its pasted-token connection method.
// This prevents generated metadata from presenting an unsupported sign-in flow.
import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { LokaliseNode } from '../../app/components/workflow/nodes/integrations/lokalise';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';
import { humanizeCredentialLabel } from '../../app/utils/credentialLabels';

await loadNodeSchemas(['automation-lokalise']);

describe('Lokalise integration', () => {
    it('discovers translation reads and writes', () => {
        expect(LokaliseNode.type).toBe('automation-lokalise');
        const operations = getAgentToolOperations('automation-lokalise').map(op => op.operation);
        expect(operations).toHaveLength(19);
        expect(operations).toContain('list_projects');
        expect(operations).toContain('update_translation');
        expect(operations).toContain('create_comments');
    });

    it('offers one clearly labelled manual token method', () => {
        const methods = credentialRequirements('automation-lokalise').map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'lokalise_api_token', method_kind: 'api_key', is_oauth: false });
        expect(getNodeCredentialInfo('automation-lokalise')?.acceptedTypes).toContain('lokalise_api_token');
        expect(humanizeCredentialLabel('Lokalise API Token')).toBe('Lokalise API Token');
    });
});
