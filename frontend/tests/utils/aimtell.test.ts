// Verifies Aimtell's generated credential discovery and manual API-key method.
// This protects the connect form from treating the pasted key as OAuth.
import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/aimtell.json';
import { CREDENTIAL_TYPE_MAP } from '~/utils/credentialTypeMap';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';

describe('Aimtell credential discovery', () => {
    it('offers a pasted API key with generated aliases', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-aimtell');
        expect(CREDENTIAL_TYPE_MAP.AimtellAPIKeyCredential).toBe('aimtell_api_key');
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map(req => req.credential_type)).toEqual(['aimtell_api_key']);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe('api_key');
    });
});
