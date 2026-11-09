// Review the generated Flashquotes credential method and discoverable operations.
// This keeps the new integration's catalog metadata tied to its native schema.
import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { FlashquotesNode } from '~/components/workflow/nodes/integrations/flashquotes';
import { getAgentToolOperations, getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';

await loadNodeSchemas(['automation-flashquotes']);

describe('Flashquotes integration', () => {
    it('exposes all eleven contract reads in Bookings & Events', () => {
        expect(FlashquotesNode.category).toBe('bookings');
        expect(getAgentToolOperations('automation-flashquotes').map(o => o.operation)).toHaveLength(11);
    });
    it('connects by pasting an API key', () => {
        expect(credentialRequirements('automation-flashquotes').map(r => methodFromRequirement(r).method_kind)).toEqual(['api_key']);
        expect(getNodeCredentialInfo('automation-flashquotes')?.acceptedTypes).toContain('flashquotes_api_key');
    });
});
