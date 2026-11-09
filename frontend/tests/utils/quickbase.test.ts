// Quickbase connects through the shared manual user-token form.
// Pin the generated credential method so discovery cannot turn it into an OAuth flow.
import { expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/quickbase.json';

it('discovers Quickbase as a manual token integration', () => {
    expect(NODE_SCHEMA_TYPES).toContain('automation-quickbase');
    const requirements = requirementsFromSchema(schema);
    expect(requirements).toHaveLength(1);
    expect(methodFromRequirement(requirements[0])).toMatchObject({
        credential_type: 'quickbase_user_token', method_kind: 'api_key', is_oauth: false,
    });
});
