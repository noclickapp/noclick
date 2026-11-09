// Check that Kenect can be found and connected with the published API credentials.
// This covers the catalog and credential UI metadata generated from its node.
import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { KenectTextMessagingNode } from '~/components/workflow/nodes/integrations/kenect-text-messaging';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';

await loadNodeSchemas(['automation-kenect-text-messaging']);
describe('Kenect Text Messaging', () => {
    it('belongs in communication', () => {
        expect(KenectTextMessagingNode.category).toBe('communication');
        expect(KenectTextMessagingNode.label).toBe('Kenect Text Messaging');
    });
    it('connects by hand using an API key', () => {
        expect(credentialRequirements('automation-kenect-text-messaging').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-kenect-text-messaging')?.acceptedTypes).toContain('kenect_text_messaging_api_key');
    });
});
