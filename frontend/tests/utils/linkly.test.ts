import { beforeAll, expect, it } from 'vitest';
import {
    loadNodeSchemas,
    getNodeCredentialInfo,
    getAgentToolOperations,
} from '~/utils/nodeSchemas';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';
import { getCredentialTypeFromSchemaTitle } from '~/utils/credentialTypeMap';
import schema from '~/schemas/nodes/linkly.json';

beforeAll(() => loadNodeSchemas(['automation-linkly']));
it('discovers Linkly API key credentials and 22 operations', () => {
    expect(getNodeCredentialInfo('automation-linkly')?.acceptedTypes).toEqual([
        'linkly_api_key',
    ]);
    expect(getCredentialTypeFromSchemaTitle('Linkly API Key')).toBe(
        'linkly_api_key'
    );
    expect(
        methodFromRequirement(requirementsFromSchema(schema)[0])
    ).toMatchObject({ method_kind: 'api_key', is_oauth: false });
    expect(getAgentToolOperations('automation-linkly')).toHaveLength(22);
    expect(
        getAgentToolOperations('automation-linkly').map((op) => op.operation)
    ).toContain('create_conversion');
});
