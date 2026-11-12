import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
vi.mock('~/lib/socket-sender', () => ({ sendEventAsync: vi.fn() }));
vi.mock('~/lib/indexeddb', () => ({ valtioCache: { get: vi.fn(), set: vi.fn(), delete: vi.fn() } }));
import { methodFromRequirement, requirementsFromSchema } from '~/components/credential/credentialMethods';
const schema = JSON.parse(readFileSync(join(__dirname, '../../app/schemas/nodes/apigee.json'), 'utf8'));
describe('Registry API manual connection', () => {
    it('exposes the token, project and location through the shared connect form', () => {
        const method = methodFromRequirement(requirementsFromSchema(schema)[0]);
        expect(method).toMatchObject({ method_kind: 'api_key', is_oauth: false });
        expect(method.credential_fields?.map(field => field.name)).toEqual(['access_token', 'project', 'location']);
    });
});
