import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/smartsheet.json';
import meta from '~/schemas/nodeMeta/smartsheet.json';

describe('Smartsheet self-registering credentials', () => {
    it('offers OAuth and an API token with human labels', () => {
        const methods = requirementsFromSchema(schema).map(methodFromRequirement);
        expect(methods.map(method => [method.credential_type, method.method_kind])).toEqual([
            ['smartsheet_oauth', 'oauth'], ['smartsheet_pat', 'api_key'],
        ]);
        expect(meta.credentialTypes['Smartsheet Account']).toBe('smartsheet_oauth');
        expect(meta.credentialTypes['Smartsheet API Token']).toBe('smartsheet_pat');
        expect(meta.providerLabels.smartsheet).toBe('Smartsheet Account');
    });
    it('connects through the generic Smartsheet OAuth declaration', () => {
        expect(meta.oauthProviders).toEqual([expect.objectContaining({
            provider: 'smartsheet', credentialType: 'smartsheet_oauth',
            authorizeUrl: 'https://app.smartsheet.com/b/authorize',
            clientIdEnv: 'SMARTSHEET_CLIENT_ID',
            clientSecretEnv: 'SMARTSHEET_CLIENT_SECRET',
            redirectUriEnv: 'SMARTSHEET_REDIRECT_URI',
            scopes: ['ADMIN_SHEETS', 'CREATE_SHEETS', 'DELETE_SHEETS', 'READ_SHEETS', 'WRITE_SHEETS'],
        })]);
        expect(meta.type).toBe('automation-smartsheet');
        expect(meta.autoSelectCredential).toBe(true);
    });
});
