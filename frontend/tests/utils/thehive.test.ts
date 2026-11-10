// TheHive API keys must be connectable by hand with a public instance URL.
// These assertions cover the generated schema's path into the credential form.
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';

const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/thehive.json'), 'utf8'));
describe('TheHive manual connection', () => {
    it('offers the instance URL, API key and optional organization', () => {
        const method = methodFromRequirement(requirementsFromSchema(schema)[0]);
        expect(method.method_kind).toBe('api_key');
        expect(method.credential_fields?.map(field => field.name)).toEqual(['base_url', 'api_key', 'organisation']);
    });
});
