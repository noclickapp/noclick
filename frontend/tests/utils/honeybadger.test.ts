import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';
import schema from '~/schemas/nodes/honeybadger.json';

describe('Honeybadger manual credentials', () => {
    it('discovers a single pasted API token method', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-honeybadger');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        expect(methodFromRequirement(requirements[0])).toMatchObject({
            credential_type: 'honeybadger_api_token', method_kind: 'api_key', is_oauth: false,
        });
    });
    it('requires only a person-supplied token and defaults its credential type', () => {
        const credential = schema.$defs.HoneybadgerAPITokenCredential;
        expect(credential.required).toEqual(['api_token']);
        expect(credential.properties.credential_type.default).toBe('honeybadger_api_token');
        expect(credential.properties.region.enum).toEqual(['us', 'eu']);
        expect(credential['x-credential-instructions']).toContain('preview');
    });
});
