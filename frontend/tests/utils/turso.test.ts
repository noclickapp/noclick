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

beforeAll(() => loadNodeSchemas(['automation-turso']));
it('offers Turso as one manually pasted Platform API token', () => {
    expect(getCredentialTypeFromSchemaTitle('TursoAPITokenCredential')).toBe(
        'turso_api_token'
    );
    expect(getCredentialTypeFromSchemaTitle('Turso API Token')).toBe(
        'turso_api_token'
    );
    expect(getNodeCredentialInfo('automation-turso')?.acceptedTypes).toEqual([
        'turso_api_token',
    ]);
    const methods = requirementsFromSchema(
        NODE_SCHEMAS['automation-turso']
    ).map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0]).toMatchObject({
        method_kind: 'api_key',
        is_oauth: false,
    });
});
