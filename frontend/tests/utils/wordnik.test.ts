import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-wordnik']));

it('discovers the Wordnik key as one manual API key method', () => {
    expect(getCredentialTypeFromSchemaTitle('WordnikAPIKeyCredential')).toBe('wordnik_api_key');
    expect(getCredentialTypeFromSchemaTitle('Wordnik API Key')).toBe('wordnik_api_key');
    expect(getNodeCredentialInfo('automation-wordnik')?.acceptedTypes).toEqual(['wordnik_api_key']);
    const requirements = requirementsFromSchema(NODE_SCHEMAS['automation-wordnik']);
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0])).toMatchObject({ method_kind: 'api_key', is_oauth: false });
});
