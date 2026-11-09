import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/recruitcrm.json';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { NODE_SCHEMA_TYPES, isAgentToolProviderType } from '~/utils/nodeMeta';

describe('Recruit CRM manual connection', () => {
    it('discovers one token method without an OAuth flow', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-recruitcrm');
        expect(isAgentToolProviderType('automation-recruitcrm')).toBe(true);
        expect(CREDENTIAL_TYPE_MAP.RecruitCRMTokenCredential).toBe('recruitcrm_api_token');
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['recruitcrm_api_token']);
        expect(methodFromRequirement(requirements[0])).toMatchObject({ method_kind: 'api_key', is_oauth: false });
    });
});
