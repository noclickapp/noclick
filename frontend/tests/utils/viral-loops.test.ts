import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { requirementsFromSchema, methodFromRequirement } from '~/components/credential/credentialMethods';
const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/viral-loops.json'), 'utf8'));
describe('Viral Loops connect method', () => {
    it('offers a pasted campaign API token and explains its campaign scope', () => {
        const methods = requirementsFromSchema(schema).map(methodFromRequirement);
        expect(methods).toHaveLength(1);
        expect(methods[0]).toMatchObject({ credential_type: 'viral_loops_api_token', method_kind: 'api_key', is_oauth: false });
        const credential = schema.$defs.ViralLoopsCredential;
        expect(credential.title).toBe('Viral Loops API Token');
        expect(credential.properties.api_token['ui:widget']).toBe('password');
        expect(credential['x-credential-instructions']).toContain('Each token selects one campaign');
    });
});
