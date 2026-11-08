// Checks the SharePoint credential metadata consumed by the connection UI.
// It pins the shared Microsoft provider so a separate sign-in handler is never required.
import { beforeAll, describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';

beforeAll(() => loadNodeSchemas(['automation-microsoft-sharepoint']));

describe('SharePoint connection', () => {
    it('uses the shared Microsoft OAuth flow with its generated credential alias', () => {
        const [requirement] = credentialRequirements('automation-microsoft-sharepoint');
        expect(requirement.label).toBe('Microsoft 365 Account');
        expect(CREDENTIAL_TYPE_MAP.SharePointOAuthCredential).toBe('microsoft_sharepoint_oauth');
        const method = methodFromRequirement(requirement);
        expect(method.method_kind).toBe('oauth');
        expect(method.oauth_provider).toBe('microsoft');
        expect(method.oauth_scopes).toContain('https://graph.microsoft.com/Sites.ReadWrite.All');
    });
});
