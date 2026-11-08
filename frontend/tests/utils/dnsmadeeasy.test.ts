// Verifies discovery of the DNS Made Easy credential method.
// Protects the aliases consumed by the connection UI.
import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/dnsmadeeasy.json';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { NODE_SCHEMA_TYPES, isAgentToolProviderType } from '~/utils/nodeMeta';

describe('DNS Made Easy credential discovery', () => {
    it('offers the discovered API key method and maps credential aliases', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-dnsmadeeasy');
        expect(isAgentToolProviderType('automation-dnsmadeeasy')).toBe(true);
        expect(CREDENTIAL_TYPE_MAP.DNSMadeEasyAPIKeyCredential).toBe('dnsmadeeasy_api_key');
        expect(CREDENTIAL_TYPE_MAP['DNS Made Easy API Key and Secret']).toBe('dnsmadeeasy_api_key');
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['dnsmadeeasy_api_key']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
    });
});
