import { describe, expect, it } from 'vitest';
import schema from '../../app/schemas/nodes/postiz.json';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

describe('Postiz credentials', () => {
    it('offers both manually supplied credentials in the connect dialog', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map((requirement) => requirement.credential_type)).toEqual([
            'postiz_api_key', 'postiz_access_token',
        ]);
        const methods = requirements.map(methodFromRequirement);
        expect(methods.map((method) => method.is_oauth)).toEqual([false, false]);
        expect(methods[0].credential_fields?.map((field) => field.name)).toContain('api_key');
        expect(methods[1].credential_fields?.map((field) => field.name)).toContain('access_token');
    });
});
