import { beforeAll, expect, it } from 'vitest';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import {
    getNodeCredentialInfo,
    NODE_SCHEMAS,
    loadNodeSchemas,
} from '~/utils/nodeSchemas';
import {
    requirementsFromSchema,
    methodFromRequirement,
} from '~/components/credential/credentialMethods';

beforeAll(() => loadNodeSchemas(['automation-platerecognizer']));
it('discovers the personal Plate Recognizer token as a manual API key method', () => {
    expect(getCredentialTypeFromSchemaTitle('Plate Recognizer API Token')).toBe(
        'platerecognizer_api_token'
    );
    expect(
        getNodeCredentialInfo('automation-platerecognizer')?.acceptedTypes
    ).toEqual(['platerecognizer_api_token']);
    const requirements = requirementsFromSchema(
        NODE_SCHEMAS['automation-platerecognizer']
    );
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
    expect(methodFromRequirement(requirements[0]).is_oauth).toBe(false);
});
