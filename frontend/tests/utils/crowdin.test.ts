import { beforeAll, describe, expect, it } from 'vitest';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { loadNodeSchemas } from '~/utils/nodeSchemas';
import metadata from '../../app/schemas/nodeMeta/crowdin.json';

beforeAll(() => loadNodeSchemas(['automation-crowdin']));

describe('Crowdin connection methods', () => {
    it('offers standard Crowdin OAuth and a personal access token', () => {
        const methods = credentialRequirements('automation-crowdin').map(methodFromRequirement);
        expect(methods.map(method => method.method_kind).sort()).toEqual(['api_key', 'oauth']);
        const oauth = methods.find(method => method.method_kind === 'oauth');
        expect(oauth?.oauth_provider).toBe('crowdin');
        expect(oauth?.oauth_scopes).toEqual(['*']);
        expect(metadata.oauthProviders[0]).toMatchObject({
            provider: 'crowdin', pkce: true,
            authorizeUrl: 'https://accounts.crowdin.com/oauth/authorize',
            credentialType: 'crowdin_oauth',
        });
    });
});
