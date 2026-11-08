import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/emailvalidation.json';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { NODE_SCHEMA_TYPES, isAgentToolProviderType } from '~/utils/nodeMeta';

describe('Emailvalidation discovery', () => {
    it('discovers the API key method and credential aliases', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-emailvalidation');
        expect(isAgentToolProviderType('automation-emailvalidation')).toBe(true);
        expect(CREDENTIAL_TYPE_MAP.EmailvalidationAPIKeyCredential).toBe('emailvalidation_api_key');
        expect(CREDENTIAL_TYPE_MAP['Emailvalidation API Key']).toBe('emailvalidation_api_key');
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['emailvalidation_api_key']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
    });
});
