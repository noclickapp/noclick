import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { CardlyNode } from '../../app/components/workflow/nodes/integrations/cardly';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';
import { humanizeCredentialLabel } from '../../app/utils/credentialLabels';

await loadNodeSchemas(['automation-cardly']);

describe('Cardly integration', () => {
    it('exposes contact and card workflows in the catalog', () => {
        expect(CardlyNode.type).toBe('automation-cardly');
        const operations = getAgentToolOperations('automation-cardly').map(o => o.operation);
        expect(operations).toHaveLength(24);
        expect(operations).toEqual(expect.arrayContaining(['sync_contact', 'preview_order', 'place_order', 'list_contact_lists']));
    });
    it('connects using a pasted API key with readable labels', () => {
        expect(credentialRequirements('automation-cardly').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-cardly')?.acceptedTypes).toContain('cardly_api_key');
        expect(humanizeCredentialLabel('Cardly API Key')).toBe('Cardly API Key');
    });
});
