// Verify the discovered Vybit definition and the generated manual connection method.
// This keeps the catalog category, operation count and credential label reviewable together.
import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { VybitNotificationsNode } from '../../app/components/workflow/nodes/integrations/vybit-notifications';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';
import { humanizeCredentialLabel } from '../../app/utils/credentialLabels';

await loadNodeSchemas(['automation-vybit-notifications']);
describe('Vybit Notifications integration', () => {
    it('discovers 25 operations in communication', () => {
        expect(VybitNotificationsNode.category).toBe('communication');
        expect(getAgentToolOperations('automation-vybit-notifications')).toHaveLength(25);
        expect(getAgentToolOperations('automation-vybit-notifications').map(o => o.operation)).toContain('trigger_vybit');
    });
    it('offers a readable API key connection', () => {
        expect(credentialRequirements('automation-vybit-notifications').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-vybit-notifications')?.acceptedTypes).toContain('vybit_notifications_api_key');
        expect(humanizeCredentialLabel('Vybit Notifications API Key')).toBe('Vybit Notifications API Key');
    });
});
