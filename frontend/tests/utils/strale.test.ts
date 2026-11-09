// Checks Strale's generated credential metadata. The workflow and connect forms must offer a manual API key.
import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/strale.json';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { NODE_SCHEMA_TYPES, isAgentToolProviderType } from '~/utils/nodeMeta';

describe('Strale credential discovery', () => {
    it('offers the manual key method and discovers credential aliases', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-strale');
        expect(isAgentToolProviderType('automation-strale')).toBe(true);
        expect(CREDENTIAL_TYPE_MAP.StraleAPIKeyCredential).toBe('strale_api_key');
        expect(CREDENTIAL_TYPE_MAP['Strale API Key']).toBe('strale_api_key');
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['strale_api_key']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
    });
});
