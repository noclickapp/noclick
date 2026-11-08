import { describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/figma.json';
import metadata from '~/schemas/nodeMeta/figma.json';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

describe('Figma connection methods', () => {
    it('offers the declared OAuth provider and a personal token', () => {
        const methods = requirementsFromSchema(schema).map(methodFromRequirement);
        expect(methods.map(method => [method.credential_type, method.method_kind])).toEqual([
            ['figma_oauth', 'oauth'], ['figma_pat', 'api_key'],
        ]);
        expect(methods[0].oauth_provider).toBe('figma');
        expect(methods[0].oauth_scopes).toContain('current_user:read');
        expect(metadata.oauthProviders[0]).toMatchObject({
            provider: 'figma', credentialType: 'figma_oauth', pkce: true,
            authorizeUrl: 'https://www.figma.com/oauth',
        });
        expect(metadata.credentialTypes.FigmaPATCredential).toBe('figma_pat');
        expect(methods[1].credential_fields).toEqual([
            expect.objectContaining({ name: 'access_token', type: 'password', required: true }),
        ]);
    });
});
