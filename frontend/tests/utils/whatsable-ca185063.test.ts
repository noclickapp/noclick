import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { WhatsAbleNode } from '../../app/components/workflow/nodes/integrations/whatsable-ca185063';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '../../app/utils/nodeSchemas';
import { humanizeCredentialLabel } from '../../app/utils/credentialLabels';

await loadNodeSchemas(['automation-whatsable-ca185063']);
describe('WhatsAble integration', () => {
    it('discovers its operations in the communication catalog', () => {
        expect(WhatsAbleNode.category).toBe('communication');
        const operations = getAgentToolOperations(WhatsAbleNode.type).map(o => o.operation);
        expect(operations).toHaveLength(25);
        expect(operations).toContain('get_me');
        expect(operations).toContain('send_message');
        expect(operations).toContain('schedule_message');
    });
    it('connects with a manually pasted API key', () => {
        expect(credentialRequirements(WhatsAbleNode.type).map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo(WhatsAbleNode.type)?.acceptedTypes).toContain('whatsable_ca185063_api_key');
        expect(humanizeCredentialLabel('Whatsable API Key')).toBe('Whatsable API Key');
    });
});
