import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-gotify']));
it('discovers Gotify as a manual client-token connection', () => {
    expect(getCredentialTypeFromSchemaTitle('GotifyClientToken')).toBe('gotify_client_token');
    expect(getCredentialTypeFromSchemaTitle('Gotify Client Token')).toBe('gotify_client_token');
    expect(getNodeCredentialInfo('automation-gotify')?.acceptedTypes).toEqual(['gotify_client_token']);
    const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-gotify']);
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0])).toMatchObject({ method_kind: 'api_key', is_oauth: false });
});
