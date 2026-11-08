// Verifies that generated Rentman metadata exposes a pasted token connection.
// This prevents catalog discovery and credential UI from drifting apart.
import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/rentman.json';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { NODE_SCHEMA_TYPES, isAgentToolProviderType } from '~/utils/nodeMeta';

describe('Rentman credential discovery', () => {
    it('offers a pasted API token with the Rentman label', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-rentman');
        expect(isAgentToolProviderType('automation-rentman')).toBe(true);
        expect(CREDENTIAL_TYPE_MAP.RentmanAPITokenCredential).toBe('rentman_api_token');
        expect(CREDENTIAL_TYPE_MAP['Rentman API Token']).toBe('rentman_api_token');
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['rentman_api_token']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
    });
});
