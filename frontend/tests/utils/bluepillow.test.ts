// Verifies Bluepillow metadata reaches the shared credential and integration UI.
// Guards the manual API-key form, operation discovery, and bookings category.
import { beforeAll, expect, it } from 'vitest';
import {
    loadNodeSchemas,
    NODE_SCHEMAS,
    getNodeCredentialInfo,
} from '~/utils/nodeSchemas';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';
import { BluepillowNode } from '~/components/workflow/nodes/integrations/bluepillow';

beforeAll(() => loadNodeSchemas(['automation-bluepillow']));
it('discovers a manually entered key and 11 operations in bookings', () => {
    const schema = NODE_SCHEMAS['automation-bluepillow'];
    expect(
        getNodeCredentialInfo('automation-bluepillow')?.acceptedTypes
    ).toEqual(['bluepillow_api_key']);
    const requirements = requirementsFromSchema(schema);
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0])).toMatchObject({
        credential_type: 'bluepillow_api_key',
        method_kind: 'api_key',
        is_oauth: false,
    });
    expect(
        Object.keys(schema.properties.config.discriminator.mapping)
    ).toHaveLength(11);
    expect(schema.$defs.BluepillowAPIKeyCredential.required).toEqual([
        'api_key',
    ]);
    expect(
        schema.$defs.BluepillowAPIKeyCredential.properties.credential_type
            .default
    ).toBe('bluepillow_api_key');
    expect(BluepillowNode.category).toBe('bookings');
});
