// Pins the generated US Global Mail credential to the shared manual-connect form.
// A person supplies one API key; no OAuth or hidden required context is needed.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/us-global-mail.json'), 'utf8'));

describe('US Global Mail manual connect', () => {
    it('asks for one pasted key and supplies the credential type', () => {
        const requirements = requirementsFromSchema(schema);
        expect(requirements).toHaveLength(1);
        const method = methodFromRequirement(requirements[0]);
        expect(method).toMatchObject({ credential_type: 'us_global_mail_api_key', method_kind: 'api_key', is_oauth: false });
        expect(method.credential_fields).toEqual([expect.objectContaining({ name: 'api_key', required: true, type: 'password' })]);
        expect(method.instructions).toContain('Live keys use production');
        expect(schema.$defs.USGlobalMailCredential.properties.credential_type.default).toBe('us_global_mail_api_key');
    });
});
