import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-mailercloud']));

it('discovers the Mailercloud key as one manual API key method', () => {
    expect(getCredentialTypeFromSchemaTitle('MailercloudAPIKeyCredential')).toBe('mailercloud_api_key');
    expect(getCredentialTypeFromSchemaTitle('Mailercloud API Key')).toBe('mailercloud_api_key');
    expect(getNodeCredentialInfo('automation-mailercloud')?.acceptedTypes).toEqual(['mailercloud_api_key']);
    const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-mailercloud']);
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0])).toMatchObject({ method_kind: 'api_key', is_oauth: false });
});
