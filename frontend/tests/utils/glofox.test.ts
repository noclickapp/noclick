import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { GlofoxNode } from '~/components/workflow/nodes/integrations/glofox';

beforeAll(async () => { await loadNodeSchemas(['automation-glofox']); });
it('discovers Glofox and its hand-connected API key and token', () => {
    expect(GlofoxNode.category).toBe('industry');
    expect(getNodeCredentialInfo(GlofoxNode.type)?.acceptedTypes).toEqual(['glofox_api_key_token']);
    expect(credentialRequirements(GlofoxNode.type).map(methodFromRequirement)).toEqual([
        expect.objectContaining({ credential_type: 'glofox_api_key_token', method_kind: 'api_key', is_oauth: false }),
    ]);
});
