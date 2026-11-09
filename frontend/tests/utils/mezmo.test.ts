// Verifies the generated Mezmo credential is available through native connect metadata.
// A pasted access key must render as a manual API key method with its default type tag.
import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import schema from '~/schemas/nodes/mezmo.json';

describe('Mezmo manual access key', () => {
    it('discovers its single manual credential method', () => {
        const methods = requirementsFromSchema(schema).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'mezmo_access_key', method_kind: 'api_key', is_oauth: false });
        expect(schema.$defs.MezmoAccessKeyCredential.properties.credential_type.default).toBe('mezmo_access_key');
        expect(schema.$defs.MezmoAccessKeyCredential.required).toEqual(['access_key']);
    });
});
