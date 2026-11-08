// Power BI must enter the existing Microsoft flow with Graph identity first.
// This guards the generated credential's consent ordering and family metadata.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
import { augmentScopes } from '~/utils/oauthProviders';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/microsoft-power-bi.json'), 'utf8'));

describe('Power BI Microsoft consent', () => {
    it('requests both audiences while keeping Graph identity first', () => {
        const credential = schema.$defs.PowerBIOAuthCredential;
        expect(credential['x-oauth-provider']).toBe('microsoft');
        const scopes = augmentScopes('microsoft', credential['x-oauth-scopes']);
        expect(scopes[0]).toBe('https://graph.microsoft.com/User.Read');
        expect(scopes).toContain('offline_access');
        for (const permission of ['Workspace.Read.All', 'Dataset.ReadWrite.All', 'Report.ReadWrite.All', 'Dashboard.Read.All', 'Content.Create']) {
            expect(scopes).toContain(`https://analysis.windows.net/powerbi/api/${permission}`);
        }
        expect(credential.properties.power_bi_access_token['ui:hidden']).toBe(true);
        expect(credential.required).not.toContain('power_bi_access_token');
    });

    it('discovers the OAuth method and resolves its generated credential alias', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('oauth');
        expect(CREDENTIAL_TYPE_MAP.PowerBIOAuthCredential).toBe('microsoft_oauth');
    });
});
