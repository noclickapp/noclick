import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/recruitee.json';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { NODE_SCHEMA_TYPES, isAgentToolProviderType } from '~/utils/nodeMeta';

describe('Recruitee credential discovery', () => {
    it('offers the discovered API key method and maps credential aliases', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-recruitee');
        expect(isAgentToolProviderType('automation-recruitee')).toBe(true);
        expect(CREDENTIAL_TYPE_MAP.RecruiteeCredential).toBe('recruitee_api_token');
        expect(CREDENTIAL_TYPE_MAP['Recruitee Personal API Token']).toBe('recruitee_api_token');
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['recruitee_api_token']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
    });
});
