import { expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/niftyimages.json';

it('discovers NiftyImages with one manual API key method', () => {
    expect(NODE_SCHEMA_TYPES).toContain('automation-niftyimages');
    const requirements = requirementsFromSchema(schema);
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0])).toMatchObject({
        credential_type: 'niftyimages_api_key', method_kind: 'api_key', is_oauth: false,
    });
});
