// Check Entra's generated credential through the shared connect-form consumers.
// Directory access must reuse the working Microsoft OAuth sign-in and request its scopes.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/microsoft-entra-id.json'), 'utf8'));

describe('Microsoft Entra ID connection', () => {
    it('uses the shared Microsoft OAuth method with directory and identity permissions', () => {
        const methods = requirementsFromSchema(schema).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'microsoft_oauth', method_kind: 'oauth', is_oauth: true });
        const credential = schema.$defs.EntraOAuthCredential;
        expect(credential.title).toBe('Microsoft Entra ID OAuth');
        expect(credential['x-oauth-provider']).toBe('microsoft');
        expect(credential['x-oauth-scopes']).toEqual(expect.arrayContaining([
            'https://graph.microsoft.com/User.Read',
            'https://graph.microsoft.com/User.ReadWrite.All',
            'https://graph.microsoft.com/User.EnableDisableAccount.All',
            'https://graph.microsoft.com/Group.ReadWrite.All',
            'offline_access',
        ]));
        expect(credential['x-credential-instructions']).toContain('administrator consent');
    });
});
