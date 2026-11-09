import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/webcrm.json';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { NODE_SCHEMA_TYPES, isAgentToolProviderType } from '~/utils/nodeMeta';

describe('webCRM credential discovery', () => {
    it('offers a manually pasted token and discovers its credential aliases', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-webcrm');
        expect(isAgentToolProviderType('automation-webcrm')).toBe(true);
        expect(CREDENTIAL_TYPE_MAP.WebCRMAccessTokenCredential).toBe('webcrm_access_token');
        expect(CREDENTIAL_TYPE_MAP['webCRM Access Token']).toBe('webcrm_access_token');
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['webcrm_access_token']);
        const method = methodFromRequirement(requirements[0]);
        expect(method.method_kind).toBe('api_key');
        expect(method.credential_fields?.map(field => field.name)).toEqual(['access_token']);
    });
});
