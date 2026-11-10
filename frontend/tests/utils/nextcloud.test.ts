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

beforeAll(() => loadNodeSchemas(['automation-nextcloud']));
it('discovers one manually connected Nextcloud app password with all required fields', () => {
    expect(getCredentialTypeFromSchemaTitle('Nextcloud App Password')).toBe(
        'nextcloud_app_password'
    );
    expect(
        getNodeCredentialInfo('automation-nextcloud')?.acceptedTypes
    ).toEqual(['nextcloud_app_password']);
    const requirements = requirementsFromSchema(
        NODE_SCHEMAS['automation-nextcloud']
    );
    expect(requirements).toHaveLength(1);
    const method = methodFromRequirement(requirements[0]);
    expect(method.method_kind).toBe('api_key');
    expect(method.is_oauth).toBe(false);
    expect(
        method.credential_fields
            ?.filter((field) => field.required)
            .map((field) => field.name)
            .sort()
    ).toEqual(['app_password', 'server_url', 'username']);
});
