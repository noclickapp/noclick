// Verify that Gladia's generated credential metadata reaches the connect UI.
// A pasted API key must render as a single manual connection method.
import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import { getNodeCredentialInfo, NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-gladia']));
it('discovers Gladia as one manual API key method', () => {
    expect(getCredentialTypeFromSchemaTitle('GladiaAPIKeyCredential')).toBe('gladia_api_key');
    expect(getCredentialTypeFromSchemaTitle('Gladia API Key')).toBe('gladia_api_key');
    expect(getNodeCredentialInfo('automation-gladia')?.acceptedTypes).toEqual(['gladia_api_key']);
    const methods = requirementsFromSchema(NODE_SCHEMAS['automation-gladia']).map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0]).toMatchObject({ method_kind: 'api_key', is_oauth: false });
});
