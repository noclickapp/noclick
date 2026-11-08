import { beforeAll, expect, it } from 'vitest';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
import { NODE_SCHEMAS, loadNodeSchemas } from '~/utils/nodeSchemas';

beforeAll(() => loadNodeSchemas(['automation-bouncer']));
it('offers a pasted Bouncer API key', () => {
    const methods = requirementsFromSchema(NODE_SCHEMAS['automation-bouncer']).map(methodFromRequirement);
    expect(methods).toHaveLength(1);
    expect(methods[0]).toMatchObject({ credential_type: 'bouncer_api_key', method_kind: 'api_key', is_oauth: false });
});
