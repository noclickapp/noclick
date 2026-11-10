import { expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/traccar.json';
it('discovers a manually connected Traccar token', () => {
    expect(NODE_SCHEMA_TYPES).toContain('automation-traccar');
    const requirements = requirementsFromSchema(schema);
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0])).toMatchObject({credential_type: 'traccar_token', method_kind: 'api_key', is_oauth: false});
});
