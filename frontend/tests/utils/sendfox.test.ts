import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/sendfox.json';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';

describe('SendFox credential discovery', () => {
    it('offers a pasted personal token and generated credential aliases', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-sendfox');
        expect(CREDENTIAL_TYPE_MAP.SendfoxTokenCredential).toBe('sendfox_token');
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['sendfox_token']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
    });
});
