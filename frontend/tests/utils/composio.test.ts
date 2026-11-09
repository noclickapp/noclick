// Pin Composio's manual key method and discoverable credential metadata.
// This guards the account-connect UI as integration metadata is generated.
import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-composio']));
it('discovers one manual Composio API key method', () => {
    expect(getCredentialTypeFromSchemaTitle('ComposioAPIKeyCredential')).toBe('composio_api_key');
    expect(getNodeCredentialInfo('automation-composio')?.acceptedTypes).toEqual(['composio_api_key']);
    const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-composio']);
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0])).toMatchObject({ method_kind: 'api_key', is_oauth: false });
});
