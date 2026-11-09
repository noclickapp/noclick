import { beforeAll, expect, it } from 'vitest';
import { loadNodeSchemas, NODE_SCHEMAS, getNodeCredentialInfo } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { MightyCallNode } from '~/components/workflow/nodes/integrations/mightycall';

beforeAll(() => loadNodeSchemas(['automation-mightycall']));
it('discovers manually entered API credentials and both call triggers in communication', () => {
    const schema = NODE_SCHEMAS['automation-mightycall'];
    expect(getNodeCredentialInfo('automation-mightycall')?.acceptedTypes).toEqual(['mightycall_api_token']);
    const requirements = requirementsFromSchema(schema);
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0])).toMatchObject({
        credential_type: 'mightycall_api_token', method_kind: 'api_key', is_oauth: false,
    });
    expect(Object.keys(schema.properties.config.discriminator.mapping)).toHaveLength(22);
    expect(schema.$defs.MightyCallTokenCredential.required).toEqual(['api_key', 'access_token']);
    expect(schema.$defs.MightyCallTokenCredential.properties.credential_type.default).toBe('mightycall_api_token');
    expect(schema.$defs.MightyCallOnNewCallConfig['x-is-trigger']).toBe(true);
    expect(schema.$defs.MightyCallOnNewVoicemailConfig['x-is-trigger']).toBe(true);
    expect(MightyCallNode.category).toBe('communication');
});
