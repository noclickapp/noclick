// Verify Textmagic discovery and the manual credential form derived from its schema.
// API keys must expose both username and key without initiating an OAuth flow.
import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeCredentialInfo, getAgentToolOperations } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';

beforeAll(() => loadNodeSchemas(['automation-textmagic']));
it('Textmagic exposes its API key credential and all native operations', async () => {
    const { NODE_SCHEMAS } = await import('~/utils/nodeSchemas');
    expect(getNodeCredentialInfo('automation-textmagic')?.acceptedTypes).toEqual(['textmagic_api_key']);
    expect(getCredentialTypeFromSchemaTitle('Textmagic API Key')).toBe('textmagic_api_key');
    const method = methodFromRequirement(requirementsFromSchema(NODE_SCHEMAS['automation-textmagic'])[0]);
    expect(method).toMatchObject({ method_kind: 'api_key', is_oauth: false });
    expect(method.credential_fields.map(f => f.name)).toEqual(['username', 'api_key']);
    expect(getAgentToolOperations('automation-textmagic')).toHaveLength(25);
});
