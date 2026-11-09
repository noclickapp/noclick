import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
import { NODE_SCHEMA_TYPES } from '~/utils/nodeMeta';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/fareharbor.json'), 'utf8'));

describe('FareHarbor manual connection', () => {
    it('discovers API keys and asks for both keys and a company shortname', () => {
        expect(NODE_SCHEMA_TYPES).toContain('automation-fareharbor');
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method.credential_type).toBe('fareharbor_api_key');
        expect(method.method_kind).toBe('api_key');
        expect(method.is_oauth).toBe(false);
        const credential = schema.$defs.FareHarborAPIKeyCredential;
        expect(credential.required).toEqual(['app_key', 'user_key', 'company_shortname']);
        expect(credential.properties.credential_type.default).toBe('fareharbor_api_key');
        expect(credential.properties.app_key['ui:widget']).toBe('password');
        expect(credential.properties.user_key['ui:widget']).toBe('password');
    });
});
