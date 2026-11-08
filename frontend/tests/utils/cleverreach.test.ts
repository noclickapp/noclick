import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/cleverreach.json'), 'utf8'));
const meta = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodeMeta/cleverreach.json'), 'utf8'));

describe('CleverReach connection', () => {
    it('uses the documented pasted token as a manual credential', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['cleverreach_access_token']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
        expect(schema.$defs.CleverreachAccessTokenCredential.required).toEqual(['access_token']);
        expect(meta.credentialTypes.CleverreachAccessTokenCredential).toBe('cleverreach_access_token');
        expect(meta.autoSelectCredential).toBe(true);
        expect(meta.oauthProviders).toBeUndefined();
    });
});
