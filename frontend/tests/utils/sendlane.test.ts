import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { SendlaneNode } from '../../app/components/workflow/nodes/integrations/sendlane';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';
import { humanizeCredentialLabel } from '../../app/utils/credentialLabels';

await loadNodeSchemas(['automation-sendlane']);

describe('Sendlane integration', () => {
    it('offers audience writes and campaign reads', () => {
        expect(SendlaneNode.type).toBe('automation-sendlane');
        const operations = getAgentToolOperations('automation-sendlane').map(op => op.operation);
        expect(operations).toHaveLength(25);
        expect(operations).toContain('add_list_contact');
        expect(operations).toContain('get_campaign_report');
    });

    it('connects with a clearly labelled pasted API token', () => {
        expect(credentialRequirements('automation-sendlane').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-sendlane')?.acceptedTypes).toContain('sendlane_api_token');
        expect(humanizeCredentialLabel('Sendlane API Token')).toBe('Sendlane API Token');
    });
});
