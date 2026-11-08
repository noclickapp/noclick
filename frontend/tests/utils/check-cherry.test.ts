// Exercise the Check Cherry credential schema through the shared form consumers.
// This pins pasted-key authentication and the setup instructions for connection evidence.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/check-cherry.json'), 'utf8'));

describe('Check Cherry credentials', () => {
    it('offers a pasted integration key with a password field and permission instructions', () => {
        const methods = requirementsFromSchema(schema).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'check_cherry_api_key', method_kind: 'api_key', is_oauth: false });
        const credential = schema.$defs.CheckCherryCredential;
        expect(credential.title).toBe('Check Cherry API Key');
        expect(credential.properties.api_key['ui:widget']).toBe('password');
        expect(credential['x-credential-url']).toBe('https://www.checkcherry.com/api/docs');
        expect(credential['x-credential-instructions']).toContain('lead_read');
    });
});
