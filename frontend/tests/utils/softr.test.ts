import { describe, expect, it } from 'vitest';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/softr.json';
import meta from '~/schemas/nodeMeta/softr.json';

describe('Softr integration', () => {
    it('offers a pasted API key with discovered metadata', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map((req) => req.credential_type)).toEqual([
            'softr_api_key',
        ]);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe(
            'api_key'
        );
        expect(schema.$defs.SoftrAPIKey.required).toEqual(['api_key']);
        expect(meta.credentialTypes.SoftrAPIKey).toBe('softr_api_key');
        expect(meta.autoSelectCredential).toBe(true);
    });
});
