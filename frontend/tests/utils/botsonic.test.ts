import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/botsonic.json';
import meta from '~/schemas/nodeMeta/botsonic.json';

describe('Botsonic connection metadata', () => {
    it('offers a pasted bot token as an API key connection', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['botsonic_api_token']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
        expect(meta.credentialTypes.BotsonicCredential).toBe('botsonic_api_token');
        expect(schema.$defs.BotsonicCredential.required).toEqual(['api_token']);
        expect(meta.autoSelectCredential).toBe(true);
    });
});
