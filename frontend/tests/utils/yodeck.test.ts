// Yodeck uses a manually supplied token with a workspace witness.
// Check its generated credential method so connect UI does not offer OAuth.
import { expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '../../app/schemas/nodes/yodeck.json';
it('offers a Yodeck API token method', () => {
    expect(methodFromRequirement(requirementsFromSchema(schema)[0]).method_kind).toBe('api_key');
    expect(schema.$defs.YodeckTokenCredential.title).toBe('Yodeck API Token');
    expect(JSON.stringify(schema)).not.toContain('x-oauth-provider');
});
