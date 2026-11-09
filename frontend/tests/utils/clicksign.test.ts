import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/clicksign.json'), 'utf8'));

describe('Clicksign manual connection', () => {
    it('offers a pasted access token and fixed environment choice', () => {
        const methods = requirementsFromSchema(schema).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'clicksign_access_token', method_kind: 'api_key', is_oauth: false });
        const credential = schema.$defs.ClicksignAccessTokenCredential;
        expect(credential.title).toBe('Clicksign Access Token');
        expect(credential.properties.credential_type.default).toBe('clicksign_access_token');
        expect(credential.properties.access_token['ui:widget']).toBe('password');
        expect(credential.properties.environment.enum).toEqual(['production', 'sandbox']);
        expect(credential['x-credential-instructions']).toContain('without a Bearer prefix');
        expect(credential['x-credential-url']).toBe('https://developers.clicksign.com/docs/access-token');
    });
});
