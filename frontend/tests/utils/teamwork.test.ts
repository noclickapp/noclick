import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/teamwork.json';
import meta from '~/schemas/nodeMeta/teamwork.json';

describe('Teamwork credential metadata', () => {
    it('offers API key and the declared OAuth sign-in', () => {
        const methods = Object.fromEntries(requirementsFromSchema(schema).map(req => [req.credential_type, methodFromRequirement(req).method_kind]));
        expect(methods).toEqual({ teamwork_oauth: 'oauth', teamwork_api_key: 'api_key' });
        expect(meta.providerLabels.teamwork).toBe('Teamwork Account');
        expect(meta.oauthProviders[0].provider).toBe('teamwork');
        expect(meta.oauthProviders[0].authorizeUrl).toBe('https://www.teamwork.com/launchpad/login/');
        expect(meta.autoSelectCredential).toBe(true);
    });
});
