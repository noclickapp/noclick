import { describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import { INTEGRATION_METADATA } from '~/utils/integrationMetadata';

await loadNodeSchemas(['automation-spotify']);

describe('Spotify connection', () => {
    it('discovers the declared Spotify OAuth sign-in', () => {
        const methods = credentialRequirements('automation-spotify').map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({
            credential_type: 'spotify_oauth', method_kind: 'oauth', is_oauth: true,
            oauth_provider: 'spotify',
        });
        expect(INTEGRATION_METADATA.oauthProviders.spotify).toMatchObject({
            authorizeUrl: 'https://accounts.spotify.com/authorize',
            clientIdEnv: 'SPOTIFY_CLIENT_ID',
            pkce: false,
        });
        expect(INTEGRATION_METADATA.oauthProviders.spotify.scopes).toContain('user-read-recently-played');
    });
});
