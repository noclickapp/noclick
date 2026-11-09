// PreciseFP's generated metadata must expose the registered OAuth sign-in.
// This checks the credential method that the connect UI will offer to a person.
import { describe, expect, it } from 'vitest';
import { loadNodeSchemas, getNodeSchema } from '~/utils/nodeSchemas';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { NODE_SCHEMA_TYPES, isAgentToolProviderType } from '~/utils/nodeMeta';

describe('PreciseFP credential discovery', () => {
    it('offers the declared OAuth method and human credential label', async () => {
        await loadNodeSchemas(['automation-precisefp']);
        expect(NODE_SCHEMA_TYPES).toContain('automation-precisefp');
        expect(isAgentToolProviderType('automation-precisefp')).toBe(true);
        expect(CREDENTIAL_TYPE_MAP.PreciseFPOAuthCredential).toBe('precisefp_oauth');
        expect(CREDENTIAL_TYPE_MAP['PreciseFP Account']).toBe('precisefp_oauth');
        const schema = getNodeSchema('automation-precisefp');
        expect(schema).toBeTruthy();
        const requirements = requirementsFromSchema(schema!);
        expect(requirements.map(req => req.credential_type)).toEqual(['precisefp_oauth']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('oauth');
    });
});
