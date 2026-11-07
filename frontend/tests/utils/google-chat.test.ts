import { describe, expect, it } from 'vitest';
import schema from '~/schemas/nodes/google-chat.json';
import { credentialRequirements, methodFromRequirement } from '~/components/credential/credentialMethods';
import { getNodeCredentialInfo, loadNodeSchemas } from '~/utils/nodeSchemas';
import { isAgentToolProviderType } from '~/utils/nodeMeta';

await loadNodeSchemas(['automation-google-chat']);

describe('Google Chat connection on staging', () => {
    it('accepts the generic credential returned by the existing Google handler with Chat scopes', () => {
        expect(getNodeCredentialInfo('automation-google-chat')).toEqual({
            providerKey: 'google_chat', acceptedTypes: ['google_oauth'], label: 'Google Chat Account',
        });
        const methods = credentialRequirements('automation-google-chat').map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({
            credential_type: 'google_oauth', method_kind: 'oauth', is_oauth: true,
            oauth_provider: 'google',
            oauth_scopes: [
                'https://www.googleapis.com/auth/chat.memberships',
                'https://www.googleapis.com/auth/chat.messages',
                'https://www.googleapis.com/auth/chat.spaces',
            ],
        });
        expect(isAgentToolProviderType('automation-google-chat')).toBe(true);
        expect(Object.keys(schema.properties.config.discriminator.mapping)).toHaveLength(28);
    });
});
