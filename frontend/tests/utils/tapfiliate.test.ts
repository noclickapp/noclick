// Reviews the generated Tapfiliate credential through the shared form consumers.
// This keeps the pasted-key method and setup guidance aligned with the provider docs.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/tapfiliate.json'), 'utf8'));

describe('Tapfiliate manual credential', () => {
    it('offers a single pasted API key with the documented profile link and permission guidance', () => {
        const methods = requirementsFromSchema(schema).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'tapfiliate_api_key', method_kind: 'api_key', is_oauth: false });
        const credential = schema.$defs.TapfiliateAPIKeyCredential;
        expect(credential.title).toBe('Tapfiliate API Key');
        expect(credential.properties.api_key['ui:widget']).toBe('password');
        expect(credential['x-credential-url']).toBe('https://app.tapfiliate.com/a/profile/');
        expect(credential['x-credential-instructions']).toContain('Approve commissions');
        expect(credential['x-credential-instructions']).toContain('reading your programs');
    });
});
