import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import metadata from '~/schemas/nodeMeta/miro.json';

await loadNodeSchemas(['automation-miro']);

describe('Miro OAuth connection', () => {
    it('uses the declared provider for its OAuth credential', () => {
        const methods = credentialRequirements('automation-miro').map(methodFromRequirement);
        expect(methods.map(m => m.credential_type)).toEqual(['miro_oauth', 'miro_mcp']); // and its vendor's MCP server, last (backend nodes/core/vendor_mcp.py)
        expect(methods[0]).toMatchObject({
            credential_type: 'miro_oauth', method_kind: 'oauth', is_oauth: true,
            oauth_provider: 'miro', oauth_scopes: ['boards:read', 'boards:write'],
        });
        expect(metadata.oauthProviders[0]).toMatchObject({
            provider: 'miro', credentialType: 'miro_oauth',
            authorizeUrl: 'https://miro.com/oauth/authorize',
            clientIdEnv: 'MIRO_CLIENT_ID', clientSecretEnv: 'MIRO_CLIENT_SECRET',
            redirectUriEnv: 'MIRO_REDIRECT_URI',
        });
    });
});
