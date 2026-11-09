import { describe, expect, it } from 'vitest';
import {
    methodFromRequirement,
    requirementsFromSchema,
} from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/snitcher.json';
import meta from '~/schemas/nodeMeta/snitcher.json';

describe('Snitcher manual connection', () => {
    it('offers one personal access token method with a default credential type', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements.map((req) => req.credential_type)).toEqual([
            'snitcher_token',
        ]);
        expect(methodFromRequirement(requirements[0]).method_kind).toBe(
            'api_key'
        );
        expect(meta.autoSelectCredential).toBe(true);
        expect(schema.$defs.SnitcherTokenCredential.required).toEqual([
            'api_token',
        ]);
        expect(
            schema.$defs.SnitcherTokenCredential.properties.credential_type
                .default
        ).toBe('snitcher_token');
        expect(
            schema.$defs.SnitcherTokenCredential.properties.api_token[
                'ui:widget'
            ]
        ).toBe('password');
    });
});
