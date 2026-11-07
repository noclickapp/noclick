import { describe, it, expect } from 'vitest';
import schema from '~/schemas/nodes/zenoti.json';
import { ZenotiNode } from '~/components/workflow/nodes/integrations/zenoti';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

await loadNodeSchemas(['automation-zenoti']);
describe('Zenoti integration metadata', () => {
    it('registers two supplied credential methods without an OAuth flow', () => {
        expect(ZenotiNode.type).toBe('automation-zenoti');
        expect(getNodeCredentialInfo(ZenotiNode.type)).toEqual({
            providerKey: 'zenoti', acceptedTypes: ['zenoti_api_key', 'zenoti_bearer_token'], label: 'Zenoti Account',
        });
        expect(requirementsFromSchema(schema).map(methodFromRequirement).map(m => m.method_kind)).toEqual(['api_key', 'api_key']);
        expect(Object.keys(schema.properties.config.discriminator.mapping)).toHaveLength(13);
    });
});
