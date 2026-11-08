// Typefully's catalog metadata must expose its operations and pasted-key connection.
// These checks protect the self-registering definition and generated credential metadata.
import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { TypefullyNode } from '../../app/components/workflow/nodes/integrations/typefully';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';
import { humanizeCredentialLabel } from '../../app/utils/credentialLabels';

await loadNodeSchemas(['automation-typefully']);

describe('Typefully integration', () => {
    it('exposes the social publishing operation catalog', () => {
        expect(TypefullyNode.type).toBe('automation-typefully');
        const operations = getAgentToolOperations('automation-typefully').map(o => o.operation);
        expect(operations).toHaveLength(17);
        expect(operations).toContain('create_draft');
        expect(operations).toContain('replace_queue_schedule');
        expect(operations).toContain('get_current_user');
    });
    it('offers a pasted API key with readable labels', () => {
        expect(credentialRequirements('automation-typefully').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-typefully')?.acceptedTypes).toContain('typefully_api_key');
        expect(humanizeCredentialLabel('Typefully API Key')).toBe('Typefully API Key');
    });
});
